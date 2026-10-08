"""MCP server: an AI agent the user already runs, trading inside our rails.

Cursor, Claude Code, Claude Desktop and Codex can all call tools over the Model
Context Protocol. This module exposes Kalshi to them — discover, read, forecast,
and (if the user allows it) trade — so an agent can work the market list
without the app having an AI account of its own.

That makes it the second surface, after remote control, where something other
than a human hand at this desk can spend money. It is built the same way: the
agent gets MORE rails than the desktop ticket, never fewer.

  1. **Off until switched on, loopback only.** The listener binds 127.0.0.1,
     requires a bearer token from the encrypted credential store, and refuses
     any request whose Host or Origin is not this machine — a web page in the
     user's browser can reach localhost, and DNS rebinding can make it look
     like it is localhost. Both checks exist because either alone is
     bypassable.

  2. **Reading, paper and live are three different permissions.** The trade
     mode is off | paper | live. Paper is the default once enabled: it fills
     against the real order book with imaginary money (paper_book). Live
     needs its own deliberate switch, and live orders run through
     terminal.submit — every cap, status check and the backend pause gate
     the desktop ticket has.

  3. **No buy without a forecast, and no forecast without an edge.** A buy
     must name a forecast the agent recorded on that market in the last
     FORECAST_TTL_SEC, and the order is refused unless that forecast beats
     the limit price by the configured edge AFTER Kalshi's fee. The agent
     cannot buy "because it looks good"; it has to commit to a number first,
     and that number is scored against the market when it settles
     (forecast_ledger). An agent that is not beating the price shows up as
     not beating the price.

  4. **Its own money caps, on top of the ticket's.** Per-order dollars, a
     daily spend cap, and a cap on open positions. The tighter of these and
     the terminal's caps binds.

  5. **It touches only what it opened.** In live mode it can sell or cancel
     only positions and orders it placed itself; the user's own book is not
     its to manage. "Opened" means contracts its buys actually FILLED, in the
     account mode the app is in now — not what it asked for, and not paper.

  6. **Nothing is silent.** Every attempt, refused or not, is written to
     mcp_orders and shown on the AI Agents page. Live orders also go to the
     paired phone if remote alerts are on.

  7. **One dispatcher, two doors.** The plain HTTP API (/api/v1, for scripts,
     n8n, LangChain — anything that does not speak MCP) is served by the SAME
     listener, behind the SAME Host/Origin/token checks, and every tool call it
     makes goes through call_tool exactly as an MCP tools/call does. It has no
     handler of its own that could drift from the MCP rails, and it is off
     until its own switch (mcp_http_enabled) is on.

  8. **Every caller is one of the user's named agents** (mcp_agents.py), and
     its TOKEN says which — never anything the caller writes. An agent's rules
     stack on top of every rail above and can only narrow them; its spend,
     its positions and "only what it opened" are its own, while the global
     caps still bind all agents together. The built-in Default agent holds
     the original token, so configs copied before agents existed keep working.

What this cannot protect against, stated rather than glossed: whatever the
agent reads — market data and, in live mode, your positions — goes to the AI
provider behind the client (Anthropic, OpenAI, Cursor). That is how an agent
works. And a forecast with an "edge" is still only the model's opinion; the
scoreboard is the only evidence that opinion is worth anything.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import db
import forecast_ledger
import kalshi_auth
import mcp_agents
import paper_book

logger = logging.getLogger("mcp")

SERVER_NAME = "krypt-trader"
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PORT = 47821
TOKEN_SECRET = "mcp_token"
TRADE_MODES = ("off", "paper", "live")

APPROVAL_TTL_SEC = 600
DECIDING_GRACE_SEC = 300

FORECAST_TTL_SEC = 1800

RATE_WINDOW = 60.0
RATE_MAX = 120
RATE_GLOBAL_MAX = 480

MAX_BODY = 256 * 1024
MAX_HEAD = 16 * 1024
IDLE_SEC = 75.0
_LOOPBACK = "127.0.0.1"
_LOCALHOST = "localhost"

_TRADABLE_STATUSES = ("active", "open")
_DEAD_STATUSES = ("closed", "settled", "finalized", "determined")



@dataclass
class Hooks:
    get_cfg: Callable[[], dict] = lambda: {}
    is_authed: Callable[[], bool] = lambda: False
    submit: Optional[Callable[..., Awaitable[dict]]] = None
    cancel: Optional[Callable[[str], Awaitable[dict]]] = None
    rpc: Optional[Callable[[str, dict], Awaitable[Any]]] = None
    emit: Optional[Callable[[str, Any], Awaitable[None]]] = None
    notify_phone: Optional[Callable[[str], Awaitable[None]]] = None
    version: str = ""


HOOKS = Hooks()


def configure(**kw: Any) -> None:
    for k, v in kw.items():
        if not hasattr(HOOKS, k):
            raise AttributeError(k)
        setattr(HOOKS, k, v)


_LOCK: Optional[tuple[Any, asyncio.Lock]] = None


def _money_lock() -> asyncio.Lock:
    global _LOCK
    loop = asyncio.get_running_loop()
    if _LOCK is None or _LOCK[0] is not loop:
        _LOCK = (loop, asyncio.Lock())
    return _LOCK[1]



DEFAULT_AGENT = mcp_agents.DEFAULT_ID
_TOKENS: dict[str, Optional[str]] = {}
_TOKENS_DIR: list = [None]


def _refresh_scrubber() -> None:
    try:
        import logscrub
        logscrub.refresh_known_secrets()
    except Exception:
        pass


def _token_cache() -> dict[str, Optional[str]]:
    d = str(kalshi_auth._credentials_dir())
    if _TOKENS_DIR[0] != d:
        _TOKENS.clear()
        _TOKENS_DIR[0] = d
    return _TOKENS


def get_token(create: bool = False, agent_id: str = DEFAULT_AGENT) -> Optional[str]:
    _token_cache()
    tok = _TOKENS.get(agent_id)
    if not tok:
        tok = kalshi_auth.read_secret(mcp_agents.token_secret(agent_id))
        if tok:
            _TOKENS[agent_id] = tok
    if not tok and create:
        if kalshi_auth.has_secret(mcp_agents.token_secret(agent_id)):
            raise RuntimeError("This agent's token could not be read from the "
                               "credential store. Try again; nothing was changed.")
        tok = rotate_token(agent_id)
    return tok


def rotate_token(agent_id: str = DEFAULT_AGENT) -> str:
    """A fresh token for one agent. Every client configured with its old one
    stops working, which is the point of rotating it; the other agents'
    tokens are untouched."""
    tok = "kt_" + secrets.token_urlsafe(32)
    kalshi_auth.save_secret(mcp_agents.token_secret(agent_id), tok)
    _token_cache()[agent_id] = tok
    _refresh_scrubber()
    return tok


def has_token(agent_id: str = DEFAULT_AGENT) -> bool:
    return bool(get_token(False, agent_id))


def delete_token(agent_id: str) -> None:
    """A deleted agent's token is removed from disk and from memory. It
    already stopped working the moment the agent left config (resolve_token
    only matches agents that exist); this makes sure it cannot come back if
    an agent with the same id is ever created again."""
    if agent_id == DEFAULT_AGENT:
        return
    kalshi_auth.clear_secret(mcp_agents.token_secret(agent_id))
    _token_cache().pop(agent_id, None)
    _refresh_scrubber()


def deleted_agents(before: Optional[set], after: Optional[set]) -> set:
    """Agent ids the USER deleted between two configs main sent: in the one
    before, missing from the one after. Pure.

    Never "every token not in the current list". The backend starts on
    built-in defaults (Default only), main itself falls back to defaults on a
    corrupt or missing settings.json, and a reset writes defaults — pruning
    against any of those deleted every named agent's token for good, so a
    restored settings file came back with agents no client could reach. A
    deleted agent's token is refused at once regardless (resolve_token only
    matches agents in config); this is just the cleanup of its file."""
    if before is None or after is None:
        return set()
    return {a for a in before - after if a != DEFAULT_AGENT and mcp_agents.valid_id(a)}


def delete_tokens(ids: set) -> list[str]:
    gone = []
    for aid in sorted(ids):
        if kalshi_auth.has_secret(mcp_agents.token_secret(aid)):
            gone.append(aid)
        delete_token(aid)
    return gone


def resolve_token(supplied: str, cfg: dict) -> Optional[dict]:
    """The agent whose token this is, or None. Only agents that exist in
    config can match — a deleted agent's token stops working at once, even
    before its file is pruned. Every candidate is compared in constant time."""
    if not supplied:
        return None
    hit = None
    for a in mcp_agents.agents(cfg):
        tok = get_token(False, a["id"])
        if tok and secrets.compare_digest(supplied, tok) and hit is None:
            hit = a
    return hit


def _agent(ctx: dict, cfg: dict) -> Optional[dict]:
    """The agent a call runs as. Set by the transport from the token (HTTP,
    MCP, the bridge) or by Autopilot in-process; a ctx with none is the
    Default agent, which is what every in-process caller was before."""
    return mcp_agents.get(cfg, str(ctx.get("agent") or DEFAULT_AGENT))


def _agent_mode(cfg: dict, agent: Optional[dict]) -> str:
    return mcp_agents.effective_mode(trade_mode(cfg), agent)


def _agent_rails(cfg: dict, agent: Optional[dict]) -> dict:
    return mcp_agents.effective_rails(_rails(cfg), agent)


def _agent_name(agent: Optional[dict]) -> str:
    return (agent or {}).get("name") or "The agent"



def trade_mode(cfg: dict) -> str:
    """The global agent trade mode, under the account mode. In Paper the app
    places no real order for anyone, so a global "live" is paper there —
    the account mode only ever narrows this, never widens it. Both the
    setting and the scope actually in force must say Live."""
    m = str(cfg.get("mcp_trade_mode") or "off").lower()
    m = m if m in TRADE_MODES else "off"
    if m == "live" and (str(cfg.get("account_mode") or "").lower() != "live"
                        or kalshi_auth.is_paper()):
        return "paper"
    return m


def _rails(cfg: dict) -> dict:
    return {
        "maxOrderUsd": float(cfg.get("mcp_max_order_usd") or 25.0),
        "dailySpendUsd": float(cfg.get("mcp_daily_spend_usd") or 100.0),
        "maxOpenPositions": int(cfg.get("mcp_max_positions") or 10),
        "minEdgeCents": float(cfg.get("mcp_min_edge_cents") or 0.0),
        "dailyLossUsd": float(cfg.get("mcp_daily_loss_usd") or 50.0),
        "forecastTtlMin": FORECAST_TTL_SEC // 60,
    }



def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def spent_today(mode: str, exclude_id: Optional[int] = None,
                agent_id: Optional[str] = None) -> float:
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(committed_usd), 0) FROM mcp_orders "
            "WHERE (ok=1 OR status IN ('deciding','unknown') OR " + _LIVE_PENDING_SQL + ") "
            "AND action='buy' "
            "AND mode=? AND kalshi_env=? AND substr(created_at,1,10)=? AND id<>? "
            "AND (? IS NULL OR COALESCE(NULLIF(agent_id,''),'default')=?)",
            (_pending_cutoff(), mode, kalshi_auth.get_env(), _today(),
             int(exclude_id) if exclude_id is not None else -1,
             agent_id, agent_id)).fetchone()
    return float(row[0] or 0.0)


_LIVE_PENDING_SQL = "(status='pending' AND julianday(created_at) > julianday('now', ?))"


def _pending_cutoff() -> str:
    return f"-{int(APPROVAL_TTL_SEC)} seconds"


def _audit(*, mode: str, client: str, req: dict, ok: bool, message: str,
           forecast_id: Optional[int] = None, committed: Optional[float] = None,
           order_id: Optional[str] = None, filled: Optional[int] = None,
           avg: Optional[float] = None, status: Optional[str] = None,
           agent_id: str = DEFAULT_AGENT, env: Optional[str] = None) -> int:
    env = env or kalshi_auth.get_env()
    with db.get_db() as conn:
        cur = conn.execute(
            """INSERT INTO mcp_orders
               (created_at, kalshi_env, mode, client, ticker, side, action,
                count, price_cents, forecast_id, committed_usd, ok, order_id,
                filled, avg_fill_cents, message, status, agent_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), env, mode, (client or "")[:80],
             req.get("ticker") or "", req.get("side") or "",
             req.get("action") or "", int(req.get("count") or 0),
             float(req.get("priceCents") or 0), forecast_id,
             round(committed, 4) if committed is not None else None,
             1 if ok else 0, order_id, filled, avg, (message or "")[:500], status,
             agent_id or DEFAULT_AGENT),
        )
        return int(cur.lastrowid)


def _row_agent(r: Any) -> str:
    try:
        return str(r["agent_id"] or "") or DEFAULT_AGENT
    except (IndexError, KeyError):
        return DEFAULT_AGENT


def _names() -> dict[str, str]:
    try:
        return {a["id"]: a["name"] for a in mcp_agents.agents(HOOKS.get_cfg())}
    except Exception:
        return {}


def activity(limit: int = 100) -> list[dict]:
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM mcp_orders ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    names = _names()
    return [{
        "id": int(r["id"]), "at": r["created_at"], "env": r["kalshi_env"],
        "mode": r["mode"], "client": r["client"] or None,
        "agentId": _row_agent(r),
        "agentName": names.get(_row_agent(r)),
        "ticker": r["ticker"], "side": r["side"], "action": r["action"],
        "count": int(r["count"]), "priceCents": float(r["price_cents"]),
        "forecastId": r["forecast_id"], "committedUsd": r["committed_usd"],
        "ok": bool(r["ok"]), "orderId": r["order_id"], "filled": r["filled"],
        "avgFillCents": r["avg_fill_cents"], "message": _effective_message(r),
        "status": _effective_status(r),
    } for r in rows]


def _effective_message(r: Any) -> str:
    if r["status"] == "deciding" and _effective_status(r) == "failed":
        return ("approval never finished (the app stopped mid-send?) — check "
                "your Kalshi orders before approving anything like it again")
    return r["message"] or ""


def _effective_status(r: Any) -> Optional[str]:
    st = r["status"]
    if st == "pending" and (_age_sec(r["created_at"]) or 0) > APPROVAL_TTL_SEC:
        return "expired"
    if st == "deciding" and (_age_sec(r["created_at"]) or 0) > APPROVAL_TTL_SEC + DECIDING_GRACE_SEC:
        return "failed"
    return st


def pending(limit: int = 50) -> list[dict]:
    return [a for a in activity(limit * 4) if a["status"] == "pending"][:limit]


async def day_loss(mode: str) -> dict:
    """Today's agent P&L (UTC) for the daily loss stop: realised today plus
    the open positions' unrealised P&L at the bid. The spend cap bounds how
    much goes OUT in a day; this bounds how much is LOST, which the spend cap
    cannot — a cheap position can still go to zero.

    A position nobody bids (or whose market could not be read) is valued at
    the worst case, its whole cost: it is the one most likely to be worth
    nothing. Read as zero it was invisible to the stop, so the stop failed
    OPEN exactly when the book went quiet — or when the marks read failed.
    The live portfolio read failing at all sets `positionsUnreadable`, and the
    vet then refuses buys (exits are never blocked).

    Live figures come from the terminal's own ledger and portfolio for the
    tickers the agent has traded. If the user also hand-traded one of those
    tickers, their P&L is counted too: the stop errs toward halting early,
    never toward missing a loss."""
    import kalshi_api
    import terminal
    today = _today()
    if mode == "paper":
        tickers = paper_book.open_tickers(agents_only=True)
        marks: dict = {}
        if tickers:
            try:
                found = await terminal._public_gate.run(
                    kalshi_api.fetch_markets_by_tickers, tickers) or {}
                marks = {t: terminal.market_row(m) for t, m in found.items()}
            except Exception as e:
                logger.debug("loss-stop marks failed: %s", e)
        d = paper_book.day_pnl(today, marks)
    else:
        mine = _live_agent_tickers()
        realized = unreal = unmarked_cost = 0.0
        unmarked: list = []
        unreadable = False
        if mine:
            hist = await asyncio.to_thread(terminal.manual_history, 300)
            for t in hist.get("trades") or []:
                if (t.get("ticker") in mine and t.get("resolved")
                        and str(t.get("resolvedAt") or "")[:10] == today
                        and t.get("pnlUsd") is not None):
                    realized += float(t["pnlUsd"])
            try:
                pf = await terminal.portfolio(HOOKS.is_authed())
                for p in pf.get("positions") or []:
                    if p.get("ticker") not in mine:
                        continue
                    if p.get("unrealizedUsd") is None:
                        unmarked.append(p.get("ticker"))
                        cost = p.get("costBasisUsd")
                        unmarked_cost += (float(cost) if cost is not None
                                          else float(p.get("contracts") or 0))
                    else:
                        unreal += float(p["unrealizedUsd"])
            except Exception as e:
                logger.debug("loss-stop portfolio failed: %s", e)
                unreadable = True
        d = {"realizedUsd": round(realized, 2), "unrealizedUsd": round(unreal, 2),
             "unmarked": unmarked, "unmarkedCostUsd": round(unmarked_cost, 2)}
        if unreadable:
            d["positionsUnreadable"] = True
    d["lossUsd"] = round(max(0.0, -(d["realizedUsd"] + min(0.0, d["unrealizedUsd"])
                                    - float(d.get("unmarkedCostUsd") or 0.0))), 2)
    return d


_AGENT_SQL = "AND (? IS NULL OR COALESCE(NULLIF(agent_id,''),'default')=?) "


def _live_agent_net(ticker: str, side: str, agent_id: str = DEFAULT_AGENT) -> int:
    """Contracts the agent may sell: what its buys actually FILLED, minus what
    its sells may have sold.

    Buys count their fills, never their requested size. Counting the request
    let a 1c buy of 10 that rested (or was cancelled) unfilled authorise a sell
    of 10 — and terminal.preview's held check then passed on the USER's own
    contracts, which are on the same account. A buy whose fills are unknown
    counts 0: unknown is not a position.

    Sells are the other way round: one counts its full requested size for as
    long as it could still fill, and only its actual fills once it has been
    cancelled (t_cancel marks it). Counting a resting sell's fills (0) would
    let the agent place a second sell for the same contracts, and when both
    fill the second one is the user's. A sell whose send errored ('unknown')
    may be on Kalshi, so it counts in full too."""
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(CASE "
            "  WHEN action='buy' THEN COALESCE(filled, 0) "
            "  WHEN status='cancelled' THEN -COALESCE(filled, count) "
            "  ELSE -count END), 0) "
            "FROM mcp_orders WHERE (ok=1 OR status='unknown') AND mode='live' AND kalshi_env=? "
            "AND ticker=? AND side=? " + _AGENT_SQL,
            (kalshi_auth.get_env(), ticker, side, agent_id, agent_id)).fetchone()
    return max(0, int(row[0] or 0))


def _live_agent_exposure(ticker: str, agent_id: str,
                         exclude_id: Optional[int] = None) -> int:
    """Contracts this agent has in (or could still get into) one market, for
    its per-market cap. Errs HIGH: a buy counts its full size until it is
    known cancelled, queued and errored buys count, and a sell only takes off
    what it is known to have filled — so the cap can refuse a buy it might
    have allowed, never allow one it should have refused."""
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(CASE "
            "  WHEN action='buy' AND status='cancelled' THEN COALESCE(filled, 0) "
            "  WHEN action='buy' THEN count "
            "  WHEN ok=1 THEN -COALESCE(filled, 0) "
            "  ELSE 0 END), 0) "
            "FROM mcp_orders WHERE (ok=1 OR status IN ('deciding','unknown') OR "
            + _LIVE_PENDING_SQL + ") "
            "AND mode='live' AND kalshi_env=? AND ticker=? AND id<>? " + _AGENT_SQL,
            (_pending_cutoff(), kalshi_auth.get_env(), ticker,
             int(exclude_id) if exclude_id is not None else -1,
             agent_id, agent_id)).fetchone()
    return max(0, int(row[0] or 0))


async def _refresh_agent_fills(ticker: str, side: str) -> None:
    """Re-read from Kalshi's fills ledger every agent order on (ticker, side)
    whose fill count could still have moved: buys not yet known to be fully
    filled, and cancelled sells (a fill can land in the moment before a
    cancel, and the ledger can lag the cancel). Run before a sell is vetted,
    so the allowance is computed from fills as they are now.

    A count only ever goes UP here: fills are never undone, and a ledger read
    that comes back short (paging, lag) must not shrink a sell we already know
    happened. An unreadable ledger leaves the row as it was."""
    import terminal
    if not HOOKS.is_authed():
        return
    env = kalshi_auth.get_env()
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT id, order_id, count, filled FROM mcp_orders "
            "WHERE ok=1 AND mode='live' AND kalshi_env=? AND ticker=? AND side=? "
            "AND order_id IS NOT NULL AND COALESCE(filled, -1) < count "
            "AND (action='buy' OR status='cancelled')",
            (env, ticker, side)).fetchall()
    for r in rows:
        n, avg = await terminal._reconcile_fills(r["order_id"], side, pin_env=env)
        if n is None:
            continue
        n = min(int(r["count"]), max(int(r["filled"] or 0), int(n)))
        if n != r["filled"]:
            with db.get_db() as conn:
                conn.execute(
                    "UPDATE mcp_orders SET filled=?, "
                    "avg_fill_cents=COALESCE(?, avg_fill_cents) WHERE id=?",
                    (n, avg, int(r["id"])))


def _live_agent_tickers(agent_id: Optional[str] = None) -> set[str]:
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM mcp_orders "
            "WHERE (ok=1 OR status='unknown') AND mode='live' AND action='buy' "
            "AND kalshi_env=? " + _AGENT_SQL,
            (kalshi_auth.get_env(), agent_id, agent_id)).fetchall()
    return {r[0] for r in rows}


def _live_agent_order_ids(agent_id: Optional[str] = None) -> set[str]:
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT order_id FROM mcp_orders WHERE ok=1 AND mode='live' "
            "AND kalshi_env=? AND order_id IS NOT NULL " + _AGENT_SQL,
            (kalshi_auth.get_env(), agent_id, agent_id)).fetchall()
    return {r[0] for r in rows}



_ROW_KEYS = ("ticker", "title", "yesSubTitle", "category", "status", "yesBid",
             "yesAsk", "noBid", "noAsk", "midCents", "spreadCents", "lastPrice",
             "volume24h", "openInterest", "closeTime", "minutesToClose")


def _compact(m: dict) -> dict:
    return {k: m.get(k) for k in _ROW_KEYS}


async def _market_row(ticker: str) -> Optional[dict]:
    import kalshi_api
    import terminal
    raw = await terminal._public_gate.run(kalshi_api.fetch_market, ticker)
    return terminal._apply_live_quote(terminal.market_row(raw)) if raw else None


async def _market_category(m: Optional[dict]) -> Optional[str]:
    """The canonical category of a market, for an agent's category rule, or
    None if Kalshi publishes none we can map.

    A market record carries no category (it is an EVENT property), so this
    reads the series record — public, and cached in kalshi_api for the life
    of the process. It never falls back to a keyword guess: an agent told
    "Sports only" must not buy a market a guess called sports."""
    import kalshi_api
    import terminal
    m = m or {}
    cat = mcp_agents.map_category(m.get("category"))
    if cat:
        return cat
    series = m.get("seriesTicker") or (str(m.get("ticker") or "").split("-")[0] or None)
    if not series:
        return None
    try:
        s = await terminal._public_gate.run(kalshi_api.fetch_series, series)
    except Exception as e:
        logger.debug("mcp: series read failed for %s: %s", series, e)
        return None
    return mcp_agents.map_category((s or {}).get("category"))


def edge_cents(fair_yes_c: float, side: str, price_c: float, count: int) -> float:
    """What the forecast says this order is worth, per contract, after fee.

    Uses the per-ORDER fee rounding the exchange charges (terminal._fee_usd),
    so a 1-lot is charged like a 1-lot. Near 50c that alone is ~2c."""
    import terminal
    p_side = fair_yes_c if side == "yes" else 100.0 - fair_yes_c
    fee_c = terminal._fee_usd(price_c, max(1, count)) / max(1, count) * 100.0
    return round(p_side - price_c - fee_c, 2)



_hits: list[float] = []
_agent_hits: dict[str, list[float]] = {}


def _rate_refusal(agent_id: str = DEFAULT_AGENT) -> Optional[str]:
    """None, or why this call is over a rate limit. A call refused by its own
    agent's bucket does not count toward the shared ceiling, so a runaway
    agent cannot spend the other agents' share."""
    now = time.monotonic()
    for k in [k for k, v in _agent_hits.items() if not v or now - v[-1] >= RATE_WINDOW]:
        del _agent_hits[k]
    mine = _agent_hits.setdefault(agent_id or DEFAULT_AGENT, [])
    mine[:] = [t for t in mine if now - t < RATE_WINDOW]
    mine.append(now)
    if len(mine) > RATE_MAX:
        return f"more than {RATE_MAX} calls in a minute from this agent"
    _hits[:] = [t for t in _hits if now - t < RATE_WINDOW]
    _hits.append(now)
    if len(_hits) > RATE_GLOBAL_MAX:
        return f"more than {RATE_GLOBAL_MAX} calls in a minute from all agents together"
    return None


def _rate_ok(agent_id: str = DEFAULT_AGENT) -> bool:
    return _rate_refusal(agent_id) is None



TOOLCALL_EVENT = "mcp:toolCall"
EVENT_BURST = 12
EVENT_RATE_PER_SEC = 4.0
SEEN_MAX = 32

_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-]{1,47}$")
_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_LABEL_STRIP = re.compile(r"[^A-Za-z0-9 ._()/+:@-]")
_LONG_RUN = re.compile(r"[A-Za-z0-9_]{28,}")
_RUN16 = re.compile(r"[A-Za-z0-9_]{16,}")
_KEY_PREFIX = re.compile(r"(?i)(?:^|[^a-z0-9])(?:kt_|sk[-_]|pk[-_]|rk[-_]|ghp_|gho_|xox[abpr]-|hf_|aiza)")
_SAFE_COLUMNS = ("trending", "closing", "new", "volume")


class _Throttle:
    """Token bucket. `take()` False = drop this event; `suppressed` counts the
    drops so the next event that does go out can say so."""

    def __init__(self, burst: int = EVENT_BURST, rate: float = EVENT_RATE_PER_SEC,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.burst = burst
        self.rate = rate
        self.clock = clock
        self.tokens = float(burst)
        self.last = clock()
        self.suppressed = 0

    def take(self) -> bool:
        now = self.clock()
        self.tokens = min(float(self.burst), self.tokens + (now - self.last) * self.rate)
        self.last = now
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        self.suppressed += 1
        return False


_THROTTLE = _Throttle()
SEEN: dict[str, dict] = {}
_MODELS: dict[tuple[str, str], str] = {}
_MODELS_MAX = 256


def _model_key(client: str, ctx_or_agent: Any) -> tuple[str, str]:
    aid = (ctx_or_agent.get("agent") if isinstance(ctx_or_agent, dict) else ctx_or_agent)
    return (client or "unknown", str(aid or DEFAULT_AGENT))


def _secretish(s: str) -> bool:
    try:
        import logscrub
        return logscrub.looks_secret(s)
    except Exception:
        return True


def _word_bad(w: str) -> bool:
    if _LONG_RUN.search(w) or _KEY_PREFIX.search(w):
        return True
    for run in _RUN16.findall(w):
        if any(c.isdigit() for c in run) and any(c.islower() for c in run) \
                and any(c.isupper() for c in run):
            return True
    return _secretish(w)


def _bad(s: str) -> bool:
    return _secretish(s) or any(_word_bad(w) for w in s.split())


def safe_label(raw: Any, limit: int = 48) -> str:
    """A client or model name fit for display, or "". Agent-supplied (the
    MCP handshake's clientInfo, record_forecast's `model`), so a label with
    anything credential-shaped in it is dropped whole, not trimmed."""
    s = _LABEL_STRIP.sub("", str(raw or "")).strip()[:limit].strip()
    if not s or _bad(s):
        return ""
    return s


def safe_ticker(raw: Any) -> Optional[str]:
    s = str(raw or "").strip().upper()
    if not _TICKER_RE.match(s):
        return None
    if _bad(s):
        return None
    return s


def safe_reason(text: Any, limit: int = 160) -> Optional[str]:
    """The first real line of a refusal, made safe for display. Refusals are
    our own sentences, but several quote the agent's input back ("Kalshi has
    no market called X"), so each word is checked like a label."""
    lines = [ln.strip().lstrip("-").strip() for ln in str(text or "").splitlines()]
    lines = [ln for ln in lines if ln and ln.lower().rstrip(":") != "refused"]
    if not lines:
        return None
    words = ["[redacted]" if _word_bad(w) else w for w in lines[0].split()]
    out = " ".join(words)
    try:
        import logscrub
        out = logscrub.scrub(out)
    except Exception:
        return None
    return out if len(out) <= limit else out[:limit - 1].rstrip() + "…"


def _num(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None


def _cents_txt(v: float) -> str:
    return f"{v:g}¢"


def _edge_txt(v: float) -> str:
    r = round(v) if abs(v) >= 1 else round(v, 1)
    return f"{'+' if v >= 0 else '−'}{abs(r):g}¢"


def summarize_call(name: str, args: Any, res: Any, mode: str) -> dict:
    """The display fields for one call, built ONLY from whitelisted pieces.
    Pure (no I/O), so the whitelist is unit-tested."""
    a = args if isinstance(args, dict) else {}
    r = res if isinstance(res, dict) else {}
    out: dict = {"summary": name.replace("_", " "), "ticker": None,
                 "fairCents": None, "edgeCents": None, "midCents": None,
                 "side": None, "mode": None}
    ticker = safe_ticker(a.get("ticker"))
    out["ticker"] = ticker
    tk = f" {ticker}" if ticker else ""

    if name == "get_status":
        tm = r.get("tradeMode")
        out["summary"] = f"get_status · {tm}" if tm in TRADE_MODES else "get_status"
    elif name == "discover_markets":
        col = a.get("column") if a.get("column") in _SAFE_COLUMNS else "trending"
        n = len(r.get("markets") or []) if isinstance(r.get("markets"), list) else None
        out["summary"] = f"discover {col}" + (f" · {n} markets" if n is not None else "")
    elif name == "search_markets":
        n = len(r.get("markets") or []) if isinstance(r.get("markets"), list) else None
        out["summary"] = "search markets" + (f" · {n} found" if n is not None else "")
    elif name in ("get_market", "get_orderbook"):
        out["summary"] = f"{name}{tk}"
    elif name == "record_forecast":
        fv = _num(a.get("fair_value_cents"))
        fv = fv if fv is not None and 1 <= fv <= 99 else None
        out["fairCents"] = fv
        best = None
        for side, key in (("yes", "buyYes"), ("no", "buyNo")):
            e = _num((r.get(key) or {}).get("edgeCentsAfterFee10Lot")) if isinstance(r.get(key), dict) else None
            if e is not None and (best is None or e > best[1]):
                best = (side, e)
        if best:
            out["side"], out["edgeCents"] = best[0], round(best[1], 2)
        mid = _num((r.get("market") or {}).get("midCents")) if isinstance(r.get("market"), dict) else None
        out["midCents"] = mid if mid is not None and 1 <= mid <= 99 else None
        head = f"forecast{tk}" + (f" {_cents_txt(fv)}" if fv is not None else "")
        tail = (f"edge {_edge_txt(best[1])} {best[0].upper()}" if best
                else "no side offered" if r else None)
        out["summary"] = head + (f" · {tail}" if tail else "")
    elif name in ("place_order", "preview_order"):
        side = a.get("side") if a.get("side") in ("yes", "no") else None
        action = a.get("action") if a.get("action") in ("buy", "sell") else None
        c = a.get("count")
        cnt = c if isinstance(c, int) and not isinstance(c, bool) and 0 < c <= 100000 else None
        px = _num(a.get("price_cents"))
        px = px if px is not None and 1 <= px <= 99 else None
        out["side"] = side
        out["mode"] = mode if mode in ("paper", "live") else None
        bits = [x for x in (action, str(cnt) if cnt else None,
                            side.upper() if side else None) if x]
        head = ("preview " if name == "preview_order" else "") + " ".join(bits)
        out["summary"] = f"{head}{tk}" + (f" @{_cents_txt(px)}" if px is not None else "")
        if name == "place_order" and r.get("pending"):
            aid = r.get("approvalId")
            out["summary"] += f" · awaiting approval #{aid}" if isinstance(aid, int) else " · awaiting approval"
        elif name == "place_order" and isinstance(r.get("filled"), int):
            avg = _num(r.get("avgFillCents"))
            out["summary"] += f" · filled {r['filled']}" + (f" @{avg:g}¢" if avg is not None else "")
        elif name == "preview_order" and "wouldPlace" in r:
            out["summary"] += " · would place" if r.get("wouldPlace") else " · blocked"
    elif name == "get_portfolio":
        out["summary"] = f"portfolio · {mode}" if mode in TRADE_MODES else "portfolio"
        out["mode"] = mode if mode in ("paper", "live") else None
    elif name in ("list_orders", "cancel_order", "get_order_status"):
        out["mode"] = mode if mode in ("paper", "live") else None
        aid = a.get("approval_id")
        out["summary"] = (f"order status #{aid}" if name == "get_order_status" and isinstance(aid, int)
                          else name.replace("_", " "))
    elif name == "move_funds":
        import kalshi_api
        moved = _num(r.get("movedUsd"))
        to = r.get("to") if isinstance(r.get("to"), str) and r.get("to") in kalshi_api.SHARD_NAMES.values() else None
        out["mode"] = "live"
        out["summary"] = ("move funds" + (f" ${moved:,.2f}" if moved is not None and 0 < moved < 1e7 else "")
                          + (f" to {to}" if to else ""))
    elif name.startswith("backtest_"):
        days = a.get("days")
        out["summary"] = name.replace("_", " ") + (f" · {days}d" if isinstance(days, int) and 0 < days < 3650 else "")
    return out


def _ms() -> int:
    return int(time.time() * 1000)


AGENT_SEEN: dict[str, dict] = {}
AGENT_SEEN_CLIENTS = 4


def _note_seen(client: str, *, call: bool, agent_id: Optional[str] = None) -> None:
    key = client or "unknown"
    e = SEEN.get(key)
    now = _ms()
    if e is None:
        if len(SEEN) >= SEEN_MAX:
            SEEN.pop(min(SEEN, key=lambda k: SEEN[k]["lastAt"]))
        e = SEEN[key] = {"client": key, "firstAt": now, "lastAt": now, "calls": 0}
    e["lastAt"] = now
    if call:
        e["calls"] += 1
    m = _MODELS.get(_model_key(key, agent_id))
    e["model"] = m or None
    if agent_id and mcp_agents.valid_id(agent_id):
        e["agentId"] = agent_id
        a = AGENT_SEEN.get(agent_id)
        if a is None:
            if len(AGENT_SEEN) >= SEEN_MAX:
                AGENT_SEEN.pop(min(AGENT_SEEN, key=lambda k: AGENT_SEEN[k]["lastAt"]))
            a = AGENT_SEEN[agent_id] = {"agentId": agent_id, "firstAt": now,
                                        "lastAt": now, "calls": 0, "clients": []}
        a["lastAt"] = now
        if call:
            a["calls"] += 1
        if key in a["clients"]:
            a["clients"].remove(key)
        a["clients"].insert(0, key)
        del a["clients"][AGENT_SEEN_CLIENTS:]


def seen() -> dict:
    """Clients seen this session. Memory only: no disk, no network."""
    return {"clients": sorted(SEEN.values(), key=lambda e: -e["lastAt"]),
            "agents": sorted(AGENT_SEEN.values(), key=lambda e: -e["lastAt"]),
            "now": _ms()}


def safe_agent_name(raw: Any, limit: int = 40) -> str:
    """An agent's name fit for the tool-call stream. The USER wrote it, but it
    rides the same event an injected model's fields do, so it gets the same
    treatment: control characters stripped (no forged lines in a toast or a
    log), length capped, and blanked whole if it carries a known secret."""
    s = mcp_agents.clean_name(raw, "")[:limit].strip()
    if not s or _secretish(s):
        return "Agent"
    return s


async def _publish(ev: dict) -> None:
    if not HOOKS.emit:
        return
    if not _THROTTLE.take():
        return
    ev["suppressed"] = _THROTTLE.suppressed
    _THROTTLE.suppressed = 0
    try:
        await HOOKS.emit(TOOLCALL_EVENT, ev)
    except Exception:
        pass


async def _emit_call(*, name: str, args: Any, ctx: dict, res: Any, outcome: str,
                     reason: Optional[str], started: float, mode: str) -> None:
    try:
        client = safe_label(ctx.get("client")) or "unknown"
        aid, aname = _event_agent(ctx)
        _note_seen(client, call=True, agent_id=aid)
        tool = name if _NAME_RE.match(name or "") else "unknown"
        fields = summarize_call(tool, args, res if outcome == "ok" else None, mode)
        if tool == "record_forecast" and outcome == "ok":
            m = safe_label((args or {}).get("model") if isinstance(args, dict) else None, 40)
            if m:
                if len(_MODELS) >= _MODELS_MAX:
                    _MODELS.pop(next(iter(_MODELS)))
                _MODELS[_model_key(client, aid)] = m
                SEEN[client]["model"] = m
        transport = ctx.get("transport")
        ev = {
            "v": 1, "kind": "call", "at": _ms(), "client": client,
            "transport": transport if isinstance(transport, str) and _NAME_RE.match(transport) else None,
            "model": _MODELS.get(_model_key(client, aid)), "tool": tool, "outcome": outcome,
            "reason": safe_reason(reason) if reason else None,
            "durationMs": max(0, int((time.monotonic() - started) * 1000)),
            "agentId": aid, "agentName": aname,
            **fields,
        }
        await _publish(ev)
    except Exception as e:
        logger.debug("[mcp] tool-call event skipped: %s", type(e).__name__)


def _event_agent(ctx: dict) -> tuple[Optional[str], Optional[str]]:
    """(agent id, display name) for the stream. The id is ours (a shape-
    checked config id, resolved from the token), the name the user's."""
    aid = str(ctx.get("agent") or DEFAULT_AGENT)
    if not mcp_agents.valid_id(aid):
        return None, None
    try:
        a = mcp_agents.get(HOOKS.get_cfg(), aid)
    except Exception:
        a = None
    return aid, (safe_agent_name(a["name"]) if a else None)


async def _emit_connect(ctx: dict) -> None:
    try:
        client = safe_label(ctx.get("client")) or "unknown"
        aid, aname = _event_agent(ctx)
        _note_seen(client, call=False, agent_id=aid)
        await _publish({"v": 1, "kind": "connect", "at": _ms(), "client": client,
                        "transport": None, "model": _MODELS.get(_model_key(client, aid)), "tool": None,
                        "outcome": "ok", "reason": None, "durationMs": 0,
                        "summary": "connected", "ticker": None, "fairCents": None,
                        "edgeCents": None, "midCents": None, "side": None, "mode": None,
                        "agentId": aid, "agentName": aname})
    except Exception as e:
        logger.debug("[mcp] connect event skipped: %s", type(e).__name__)



class ToolError(Exception):
    """A refusal the agent should read and act on — returned as a tool result
    with isError, not as a protocol error, so the model actually sees it."""


@dataclass
class Tool:
    name: str
    title: str
    description: str
    schema: dict
    handler: Callable[[dict, dict], Awaitable[Any]]
    perm: Optional[str] = None
    read_only: bool = True
    destructive: bool = False

    def spec(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "description": self.description,
            "inputSchema": self.schema,
            "annotations": {
                "title": self.title,
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": self.read_only,
                "openWorldHint": True,
            },
        }


def _obj(props: dict, required: tuple = ()) -> dict:
    return {"type": "object", "properties": props, "required": list(required),
            "additionalProperties": False}


_TICKER = {"type": "string", "description": "Kalshi market ticker, e.g. KXFED-26DEC-T4.25"}
_SIDE = {"type": "string", "enum": ["yes", "no"]}
_ACTION = {"type": "string", "enum": ["buy", "sell"]}
_COUNT = {"type": "integer", "minimum": 1, "maximum": 100000}
_PRICE = {"type": "number", "minimum": 1, "maximum": 99,
          "description": "Limit price in cents (1-99). Buys pay at most this; sells take at least this."}


def _s(args: dict, key: str) -> str:
    return str(args.get(key) or "").strip()


async def t_status(_args: dict, ctx: dict) -> dict:
    cfg = HOOKS.get_cfg()
    agent = _agent(ctx, cfg)
    mode = _agent_mode(cfg, agent)
    rails = _agent_rails(cfg, agent)
    out: dict = {
        "tradeMode": mode,
        "agent": {"id": agent["id"], "name": agent["name"], "mode": mode,
                  "note": "Call get_my_agent for your guide and rules."} if agent else None,
        "accountMode": "paper" if kalshi_auth.is_paper() else "live",
        "kalshiCredentialsVerified": HOOKS.is_authed() and not kalshi_auth.is_paper(),
        "rails": {**rails, "spentTodayUsd": round(spent_today(mode), 2) if mode != "off" else None,
                  "yourSpentTodayUsd": (round(spent_today(mode, agent_id=agent["id"]), 2)
                                        if mode != "off" and agent else None),
                  "lossTodayUsd": (await day_loss(mode))["lossUsd"] if mode != "off" else None},
        "notes": [],
    }
    if mode == "off":
        out["notes"].append("Trading is OFF for agents. You can read markets and "
                            "record forecasts; the user enables paper or live in the app.")
    elif mode == "paper":
        pf = paper_book.portfolio(float(cfg.get("paper_bankroll_usd") or 1000.0),
                                  agent_id=agent["id"] if agent else DEFAULT_AGENT)
        out["paper"] = {"cashUsd": pf["cashUsd"], "bankrollUsd": pf["bankrollUsd"],
                        "realizedUsd": pf["realizedUsd"],
                        "openPositions": len(pf["positions"])}
        out["notes"].append("PAPER mode: orders fill against the real order book "
                            "with imaginary money, immediate-or-cancel. Cash is one "
                            "book shared by all of the user's agents; positions and "
                            "realised P&L here are yours.")
        if trade_mode(cfg) == "live":
            out["notes"].append("The app is live for some agents, but not for you: "
                                "your orders stay on paper.")
        elif kalshi_auth.is_paper():
            out["notes"].append("The app is in Paper mode: nobody's orders spend "
                                "real money until the user switches it to Live.")
    else:
        out["notes"].append("LIVE mode: orders spend the user's real Kalshi balance.")
        try:
            import kalshi_api
            import shard_rail
            import trader
            shards = trader.cached_shard_balances()
            if shards:
                out["exchanges"] = {kalshi_api.shard_name(i): round(float(v), 2)
                                    for i, v in sorted(shards.items())}
            out["autoMoveFunds"] = shard_rail.enabled(cfg)
            out["notes"].append(
                "Cash is held per exchange (general, crypto, ...). "
                + ("The app moves a buy's shortfall onto its market's exchange by itself; "
                   if shard_rail.enabled(cfg) else
                   "The user has switched automatic moves off; ")
                + "move_funds moves cash between exchanges yourself, within a daily cap.")
        except Exception as e:
            logger.debug("status: shard split unavailable: %s", e)
    return out


async def t_move_funds(args: dict, ctx: dict) -> dict:
    """Move cash between the user's own Kalshi exchange shards. Live only.
    Nothing leaves the account; shard_rail caps it (with the app's own
    automatic moves) per day and audits every move under this agent's id."""
    import shard_rail
    cfg = HOOKS.get_cfg()
    agent = _require_agent(ctx, cfg)
    if _agent_mode(cfg, agent) != "live":
        raise ToolError("Moving funds is for live trading: paper has one pool of money, "
                        "so there is nothing to move.")
    if not HOOKS.is_authed():
        raise ToolError("No verified Kalshi credentials.")
    try:
        to = shard_rail.parse_shard(args.get("to_exchange"))
        frm = shard_rail.parse_shard(args["from_exchange"]) if args.get("from_exchange") not in (None, "") else None
    except ValueError as e:
        raise ToolError(str(e))
    async with _money_lock():
        try:
            res = await shard_rail.move(amount_usd=args.get("amount_usd"), to_shard=to,
                                        from_shard=frm, by=f"agent:{agent['id']}")
        except ValueError as e:
            raise ToolError(str(e))
    logger.info("[mcp] move_funds $%.2f -> %s by %s", res["movedUsd"], res["to"], agent["id"])
    return {"ok": True, **res}


async def t_discover(args: dict, _ctx: dict) -> dict:
    import terminal
    column = _s(args, "column") or "trending"
    if column not in ("trending", "closing", "new", "volume"):
        raise ToolError("column must be trending, closing, new or volume")
    limit = max(1, min(int(args.get("limit") or 25), 50))
    res = await terminal.discover(column, limit=limit)
    return {"column": column, "note": res.get("note"),
            "markets": [_compact(r) for r in res.get("rows") or []]}


async def t_search(args: dict, _ctx: dict) -> dict:
    import terminal
    q = _s(args, "query")
    if len(q) < 2:
        raise ToolError("query must be at least 2 characters")
    limit = max(1, min(int(args.get("limit") or 25), 50))
    res = await terminal.search(q, limit=limit)
    return {"query": q, "note": res.get("note"),
            "markets": [_compact(r) for r in res.get("rows") or []]}


async def t_market(args: dict, _ctx: dict) -> str:
    """The same rendering the in-app analyst reads: absent fields are "--",
    every price carries its source, and the resolution rules are included."""
    import ai_analyst
    import terminal
    ticker = _s(args, "ticker").upper()
    if not ticker:
        raise ToolError("ticker required")
    try:
        detail = await terminal.market_detail(ticker, authed=HOOKS.is_authed())
    except RuntimeError as e:
        raise ToolError(str(e))
    return ("A field shown as -- is ABSENT (nobody published it), not zero. "
            "Prices are cents = implied probability.\n\n"
            + ai_analyst.render_market(detail))


async def t_book(args: dict, _ctx: dict) -> dict:
    import terminal
    ticker = _s(args, "ticker").upper()
    if not ticker:
        raise ToolError("ticker required")
    b = await terminal.book(ticker)
    return {
        "ticker": ticker,
        "explain": ("Kalshi books hold only bids. 'yes' = bids to buy YES; 'no' = "
                    "bids to buy NO. Buying YES lifts NO bids at (100 - price)."),
        "yesBid": b.get("yesBid"), "yesAsk": b.get("yesAsk"),
        "spreadCents": b.get("spreadCents"), "midCents": b.get("midCents"),
        "yes": b.get("yes"), "no": b.get("no"),
        "source": b.get("source"), "stale": b.get("stale"), "note": b.get("note"),
    }


async def t_portfolio(_args: dict, ctx: dict) -> dict:
    cfg = HOOKS.get_cfg()
    agent = _agent(ctx, cfg)
    aid = agent["id"] if agent else DEFAULT_AGENT
    mode = _agent_mode(cfg, agent)
    if mode == "paper":
        import kalshi_api
        import terminal
        tickers = paper_book.open_tickers(aid)
        marks: dict = {}
        if tickers:
            try:
                found = await terminal._public_gate.run(
                    kalshi_api.fetch_markets_by_tickers, tickers) or {}
                marks = {t: terminal.market_row(m) for t, m in found.items()}
            except Exception as e:
                logger.debug("paper marks failed: %s", e)
        pf = paper_book.portfolio(float(cfg.get("paper_bankroll_usd") or 1000.0), marks,
                                  agent_id=aid)
        pf["fills"] = pf["fills"][:20]
        return {"mode": "paper", **pf}
    if mode == "live":
        import terminal
        pf = await terminal.portfolio(HOOKS.is_authed())
        mine = _live_agent_tickers(aid)
        return {
            "mode": "live", "env": pf.get("env"), "cashUsd": pf.get("cashUsd"),
            "note": pf.get("note"),
            "positions": [{**{k: p.get(k) for k in (
                "ticker", "title", "side", "contracts", "avgCostCents",
                "markCents", "unrealizedUsd")}, "openedByAgent": p.get("ticker") in mine}
                for p in pf.get("positions") or []],
        }
    raise ToolError("Trading is off for agents, so there is no agent portfolio. "
                    "The user can enable paper or live trading in the app.")


async def t_forecast(args: dict, ctx: dict) -> dict:
    ticker = _s(args, "ticker").upper()
    try:
        fv = float(args.get("fair_value_cents"))
    except (TypeError, ValueError):
        raise ToolError("fair_value_cents must be a number 1-99")
    if not (1 <= fv <= 99):
        raise ToolError("fair_value_cents must be between 1 and 99 — a forecast "
                        "of 0 or 100 is a claim of certainty, not a price")
    rationale = _s(args, "rationale")
    if len(rationale) < 20:
        raise ToolError("Give a rationale (at least a sentence): what drives your "
                        "number and what the resolution rules require.")
    m = await _market_row(ticker)
    if not m:
        raise ToolError(f"Kalshi has no market called {ticker}.")
    status = (m.get("status") or "").lower()
    if status in _DEAD_STATUSES:
        raise ToolError(f"{ticker} is {status}; a forecast now would be scored "
                        f"against an outcome that may already be known.")
    client = safe_label(ctx.get("client"), 80)
    model = safe_label(_s(args, "model"), 80) or _MODELS.get(
        _model_key(safe_label(ctx.get("client")) or "unknown", ctx), "")
    cfg = HOOKS.get_cfg()
    agent = _agent(ctx, cfg)
    fid = forecast_ledger.record(
        ticker=ticker, prob_yes=fv / 100.0, source="mcp", model=model,
        client=client, market=m, rationale=rationale, env=kalshi_auth.PRODUCTION,
        agent_id=agent["id"] if agent else DEFAULT_AGENT)

    def _edge(side: str) -> Optional[dict]:
        px = m.get("yesAsk") if side == "yes" else m.get("noAsk")
        if px is None:
            return None
        return {"atPriceCents": px, "edgeCentsAfterFee10Lot": edge_cents(fv, side, px, 10)}

    return {
        "forecastId": fid,
        "fairValueCents": fv,
        "market": {k: m.get(k) for k in ("yesBid", "yesAsk", "noBid", "noAsk", "midCents")},
        "buyYes": _edge("yes"),
        "buyNo": _edge("no"),
        "minEdgeCents": _agent_rails(cfg, agent)["minEdgeCents"],
        "validForMin": FORECAST_TTL_SEC // 60,
        "note": ("Scored against the market mid at this moment once the market "
                 "settles. A null side means nobody is offering it."),
    }


async def t_scoreboard(_args: dict, ctx: dict) -> dict:
    sb = forecast_ledger.scoreboard(recent=15)
    out = {k: sb[k] for k in ("totalForecasts", "pending", "resolved",
                               "scoredMarkets", "minScored", "overall",
                               "bySource", "buckets", "recent")}
    aid = str(ctx.get("agent") or DEFAULT_AGENT)
    out["you"] = next((r for r in sb.get("byAgent") or [] if r["agentId"] == aid), None)
    out["recent"] = [r for r in out["recent"] if r.get("agentId") in (aid, None)]
    return out


async def t_my_agent(_args: dict, ctx: dict) -> dict:
    """Who this caller is: the user's named agent its token belongs to."""
    cfg = HOOKS.get_cfg()
    agent = _agent(ctx, cfg)
    if agent is None:
        raise ToolError("This agent no longer exists in Krypt Trader.")
    mode = _agent_mode(cfg, agent)
    view = mcp_agents.public_view(agent, _agent_rails(cfg, agent), mode)
    view["note"] = ("Your guide is how the user wants you to think. Your rules are "
                    "enforced by the app on every order whatever the guide says; "
                    "an order outside them is refused.")
    return view


@dataclass
class Vetted:
    req: dict
    blockers: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    market: Optional[dict] = None
    book: Optional[dict] = None
    forecast_id: Optional[int] = None
    edge: Optional[float] = None
    cost: Optional[float] = None
    fee: Optional[float] = None


async def vet(args: dict, cfg: dict, mode: str, forecast_grace: float = 0.0,
              exclude_id: Optional[int] = None, agent: Optional[dict] = None) -> Vetted:
    """Every agent-specific rail, for both preview and place. Live orders get
    the terminal's own rails on top, inside terminal.submit.

    `agent` is the user's named agent placing it (None = Default). Its rules
    are checked on top of the global rails, never instead of them: the
    global caps bind all agents together, and its own caps, positions and
    sell allowance are computed from its own rows.

    `exclude_id` is the approval row being re-vetted, so the daily spend cap
    does not count that order against itself.

    A vet is only a promise while nothing else spends in between: place and
    decide hold _money_lock() from this call until the order is sent and
    recorded. preview_order does not, because it spends nothing."""
    import terminal
    if agent is None:
        agent = mcp_agents.get(cfg, DEFAULT_AGENT)
    aid = agent["id"] if agent else DEFAULT_AGENT
    name = _agent_name(agent)
    rules = (agent or {}).get("rules") or {}
    ticker = _s(args, "ticker").upper()
    side = _s(args, "side").lower()
    action = _s(args, "action").lower()
    try:
        count = int(args.get("count"))
    except (TypeError, ValueError):
        count = 0
    px = terminal.price_cents(args.get("price_cents"))
    req = {"ticker": ticker, "side": side, "action": action, "count": count,
           "priceCents": px}
    v = Vetted(req=req)
    grails = _rails(cfg)
    rails = mcp_agents.effective_rails(grails, agent)

    if mode == "off":
        v.blockers.append("Trading is off for agents. The user enables paper or "
                          "live trading in Krypt Trader -> AI Agents.")
        return v
    if not ticker:
        v.blockers.append("ticker required")
    if side not in ("yes", "no"):
        v.blockers.append("side must be yes or no")
    if action not in ("buy", "sell"):
        v.blockers.append("action must be buy or sell")
    if count < 1:
        v.blockers.append("count must be at least 1")
    if px is None:
        v.blockers.append("price_cents must be between 1 and 99")
    if v.blockers:
        return v

    try:
        v.market = await _market_row(ticker)
    except Exception as e:
        logger.debug("mcp vet: market read failed for %s: %s", ticker, e)
    if not v.market:
        v.blockers.append(f"Could not read market {ticker} from Kalshi.")
        return v
    status = (v.market.get("status") or "").lower()
    if status and status not in _TRADABLE_STATUSES:
        v.blockers.append(f"{ticker} is {status}, not open for trading.")
    try:
        v.book = await terminal.book(ticker)
    except Exception as e:
        logger.debug("mcp vet: book read failed for %s: %s", ticker, e)

    v.fee = terminal._fee_usd(px, count)
    gross = round(count * px / 100.0, 2)

    if action == "buy":
        v.cost = round(gross + v.fee, 2)
        fid = args.get("forecast_id")
        f = None
        try:
            f = forecast_ledger.get(int(fid)) if fid is not None else None
        except (TypeError, ValueError):
            f = None
        if f is not None and (str(f.get("agent_id") or "") or DEFAULT_AGENT) != aid:
            f = None
        if f is None:
            v.blockers.append("A buy needs forecast_id from record_forecast on this "
                              "market. Commit to a fair value first.")
        else:
            v.forecast_id = int(f["id"])
            age = _age_sec(f.get("created_at"))
            if f["ticker"] != ticker:
                v.blockers.append(f"Forecast {fid} is for {f['ticker']}, not {ticker}.")
            elif f["source"] != "mcp":
                v.blockers.append("Only a forecast recorded through this server can "
                                  "back an agent order.")
            elif f.get("kalshi_env") and f["kalshi_env"] not in (
                    kalshi_auth.PRODUCTION, kalshi_auth.PAPER):
                v.blockers.append(f"Forecast {fid} was recorded against Kalshi's "
                                  f"retired demo exchange. Record a new one.")
            elif age is None or age > FORECAST_TTL_SEC + forecast_grace:
                v.blockers.append(f"Forecast {fid} is older than "
                                  f"{FORECAST_TTL_SEC // 60} minutes. Re-read the "
                                  f"market and record a new one.")
            else:
                v.edge = edge_cents(float(f["prob_yes"]) * 100.0, side, px, count)
                if v.edge < rails["minEdgeCents"]:
                    whose = (f" ({name}'s rules)" if rails["minEdgeCents"] > grails["minEdgeCents"]
                             else "")
                    v.blockers.append(
                        f"Your forecast ({float(f['prob_yes']) * 100:g}c YES) gives "
                        f"{v.edge:+.2f}c per contract on {side.upper()} at {px:g}c "
                        f"after fees; the minimum is {rails['minEdgeCents']:g}c{whose}. "
                        f"No trade.")
        v.blockers.extend(mcp_agents.entry_blockers(
            agent or {}, side=side, price_cents=px,
            category=await _market_category(v.market) if (
                rules.get("categoriesAllow") or rules.get("categoriesDeny")) else None,
            hours_left=mcp_agents.hours_to_close(v.market.get("closeTime"))))
        if v.cost > grails["maxOrderUsd"]:
            v.blockers.append(f"${v.cost:,.2f} (fees included) is over the agent "
                              f"per-order cap of ${grails['maxOrderUsd']:,.2f}.")
        elif v.cost > rails["maxOrderUsd"]:
            v.blockers.append(f"${v.cost:,.2f} (fees included) is over {name}'s "
                              f"per-order cap of ${rails['maxOrderUsd']:,.2f}.")
        spent = spent_today(mode, exclude_id=exclude_id)
        if spent + v.cost > grails["dailySpendUsd"]:
            v.blockers.append(f"Would bring today's agent spend to "
                              f"${spent + v.cost:,.2f}, over the daily cap of "
                              f"${grails['dailySpendUsd']:,.2f}.")
        elif rules.get("dailySpendUsd") is not None:
            mine = spent_today(mode, exclude_id=exclude_id, agent_id=aid)
            if mine + v.cost > rails["dailySpendUsd"]:
                v.blockers.append(f"Would bring {name}'s spend today to "
                                  f"${mine + v.cost:,.2f}, over {name}'s daily cap of "
                                  f"${rails['dailySpendUsd']:,.2f}.")
        if mode == "paper":
            active = {a["id"] for a in mcp_agents.agents(cfg) if a.get("enabled", True)}
            held_tickers = {t for owner, ts in paper_book.open_tickers_by_agent().items()
                            if owner in active for t in ts}
            my_tickers = set(paper_book.open_tickers(aid))
            pf = paper_book.portfolio(float(cfg.get("paper_bankroll_usd") or 1000.0))
            import paper_exchange
            free = pf["cashUsd"] - paper_exchange.reserved_buy_usd()
            if free < v.cost:
                v.blockers.append(f"Free paper cash ${max(0.0, free):,.2f} is less than "
                                  f"${v.cost:,.2f}.")
        else:
            held_tickers = await _live_agent_held_tickers()
            my_tickers = (await _live_agent_held_tickers(aid)
                          if rules.get("maxOpenPositions") is not None else set())
        if ticker not in held_tickers and len(held_tickers) >= rails["maxOpenPositions"]:
            v.blockers.append(f"The agent already holds {len(held_tickers)} positions "
                              f"(cap {rails['maxOpenPositions']}).")
        cap = rules.get("maxOpenPositions")
        if cap is not None and ticker not in my_tickers and len(my_tickers) >= cap:
            v.blockers.append(
                f"{name}'s rules: no positions — it records forecasts only." if cap == 0
                else f"{name}'s rules: at most {cap} open position{'s' if cap != 1 else ''}; "
                     f"it holds {len(my_tickers)}.")
        per_mkt = rules.get("maxContractsPerMarket")
        if per_mkt is not None:
            have = (paper_book.held(ticker, "yes", aid) + paper_book.held(ticker, "no", aid)
                    if mode == "paper" else _live_agent_exposure(ticker, aid, exclude_id))
            if have + count > per_mkt:
                v.blockers.append(
                    f"{name}'s rules: at most {per_mkt} contracts in one market; it has "
                    f"{have} on {ticker} and this buy adds {count}.")
        dl = await day_loss(mode)
        if dl.get("positionsUnreadable"):
            v.blockers.append(
                "Daily loss stop: the agents' open live positions could not be read, "
                "so today's loss is unknown. No new buys until they can be; selling "
                "to exit is still allowed.")
        elif dl["lossUsd"] >= rails["dailyLossUsd"]:
            v.blockers.append(
                f"Daily loss stop: the agent is down ${dl['lossUsd']:,.2f} today (UTC) "
                f"in {mode}, at or over the ${rails['dailyLossUsd']:,.2f} limit. No new "
                f"buys until tomorrow; selling to exit is still allowed.")
    else:
        v.cost = round(gross - v.fee, 2)
        if mode == "paper":
            have = paper_book.held(ticker, side, aid)
            if count > have:
                v.blockers.append(f"The paper book holds {have} {side.upper()} on "
                                  f"{ticker} for {name}; cannot sell {count}. An agent "
                                  f"sells only what it opened, not another agent's.")
        else:
            try:
                await _refresh_agent_fills(ticker, side)
            except Exception as e:
                logger.debug("mcp vet: fill refresh failed for %s: %s", ticker, e)
            net = _live_agent_net(ticker, side, aid)
            if count > net:
                v.blockers.append(
                    f"The agent's live buys of {side.upper()} on {ticker} have "
                    f"{net} filled contracts it has not sold; it can only sell "
                    f"what it opened. Unfilled or cancelled buys open nothing, "
                    f"and the rest is the user's — or another agent's ({name} "
                    f"sells only its own).")

    if mode == "live":
        if not HOOKS.is_authed():
            v.blockers.append("No verified Kalshi credentials.")
        if v.book and v.book.get("stale"):
            v.warnings.append("The order book is a REST snapshot, not the live feed.")
    return v


async def _live_agent_held_tickers(agent_id: Optional[str] = None) -> set[str]:
    import terminal
    mine = _live_agent_tickers(agent_id)
    if not mine:
        return set()
    try:
        pf = await terminal.portfolio(HOOKS.is_authed())
    except Exception:
        return mine
    return {p["ticker"] for p in pf.get("positions") or [] if p.get("ticker") in mine}


def _age_sec(created_at: Any) -> Optional[float]:
    if not created_at:
        return None
    try:
        s = str(created_at).replace("T", " ").replace("Z", "")[:19]
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


def _require_agent(ctx: dict, cfg: dict) -> dict:
    """The calling agent from THIS cfg read, or a refusal. call_tool checked
    it on an earlier read; an agent deleted or switched off in between must
    be refused here, never vetted as Default (usually looser rules)."""
    agent = _agent(ctx, cfg)
    if agent is None:
        raise ToolError("This agent no longer exists in Krypt Trader. Nothing was executed.")
    if not agent.get("enabled", True):
        raise ToolError(f"{agent['name']} is switched off in Krypt Trader. Nothing was executed.")
    return agent


async def t_preview(args: dict, ctx: dict) -> dict:
    cfg = HOOKS.get_cfg()
    agent = _require_agent(ctx, cfg)
    mode = _agent_mode(cfg, agent)
    v = await vet(args, cfg, mode, agent=agent)
    if mode == "live" and not v.blockers:
        import kalshi_api
        import terminal
        try:
            ex = await terminal._public_gate.run(kalshi_api.fetch_exchange_status)
        except Exception:
            ex = None
        pv = terminal.preview(v.req, cfg=cfg, authed=HOOKS.is_authed(),
                              market=v.market, book_snapshot=v.book,
                              position=None, exchange_status=ex)
        v.blockers.extend(pv.get("blockers") or [])
        v.warnings.extend(pv.get("warnings") or [])
    out = {"mode": mode, "wouldPlace": not v.blockers, "blockers": v.blockers,
           "warnings": v.warnings, "edgeCentsAfterFee": v.edge,
           ("costUsd" if v.req.get("action") == "buy" else "proceedsUsd"): v.cost,
           "feeUsd": v.fee}
    if mode == "paper" and v.book and not v.blockers:
        out["paperFill"] = paper_book.simulate_fill(
            v.book, v.req["side"], v.req["action"], v.req["count"], v.req["priceCents"])
    return out


async def t_place(args: dict, ctx: dict) -> dict:
    cfg = HOOKS.get_cfg()
    agent = _require_agent(ctx, cfg)
    env = kalshi_auth.get_env()
    mode = _agent_mode(cfg, agent)
    client = ctx.get("client") or ""
    async with _money_lock():
        out, announce = await _place_locked(args, cfg, mode, client, agent, env=env)
    if announce:
        await announce()
    return out


async def _place_locked(args: dict, cfg: dict, mode: str, client: str,
                        agent: Optional[dict] = None, env: Optional[str] = None
                        ) -> tuple[dict, Optional[Callable[[], Awaitable[None]]]]:
    env = env or kalshi_auth.get_env()
    if agent is None:
        agent = mcp_agents.get(cfg, DEFAULT_AGENT)
    aid = agent["id"] if agent else DEFAULT_AGENT
    who = safe_agent_name(_agent_name(agent))
    v = await vet(args, cfg, mode, agent=agent)
    req = v.req
    if v.blockers:
        _audit(mode=mode, client=client, req=req, ok=False,
               message=v.blockers[0], forecast_id=v.forecast_id, agent_id=aid, env=env)
        raise ToolError("Refused:\n- " + "\n- ".join(v.blockers))

    if mode == "paper":
        fill = paper_book.simulate_fill(v.book, req["side"], req["action"],
                                        req["count"], req["priceCents"])
        if not fill["filled"]:
            _audit(mode=mode, client=client, req=req, ok=False,
                   message=fill["note"] or "nothing filled", forecast_id=v.forecast_id,
                   agent_id=aid, env=env)
            raise ToolError(fill["note"] or "Nothing filled.")
        import terminal
        avg = fill["avgPriceCents"]
        fee = terminal._fee_usd(avg, fill["filled"])
        paper_book.record_fill(
            ticker=req["ticker"], title=(v.market or {}).get("title") or "",
            side=req["side"], action=req["action"], contracts=fill["filled"],
            price_cents=avg, fee_usd=fee, forecast_id=v.forecast_id,
            client=client, env=env, agent_id=aid)
        spend = round(fill["filled"] * avg / 100.0 + fee, 4) if req["action"] == "buy" else None
        msg = (f"PAPER {req['action']} {fill['filled']} {req['side'].upper()} "
               f"{req['ticker']} @ {avg:g}c avg, fee ${fee:.2f}")
        _audit(mode=mode, client=client, req=req, ok=True, message=msg,
               forecast_id=v.forecast_id, committed=spend,
               filled=fill["filled"], avg=avg, agent_id=aid, env=env)
        return ({"mode": "paper", "ok": True, "message": msg, "agent": agent["name"] if agent else None,
                 "filled": fill["filled"], "avgFillCents": avg, "feeUsd": fee,
                 "note": fill["note"]},
                lambda: _announce(mode, f"{who}: {msg}"))

    if cfg.get("mcp_live_approval", True):
        oid = _audit(mode=mode, client=client, req=req, ok=False,
                     message="waiting for the user's approval",
                     forecast_id=v.forecast_id,
                     committed=v.cost if req["action"] == "buy" else None,
                     status="pending", agent_id=aid, env=env)
        msg = (f"{who} wants to {req['action'].upper()} {req['count']} "
               f"{req['side'].upper()} {req['ticker']} @ {req['priceCents']:g}c "
               f"(${v.cost:,.2f}) on {'PAPER' if env == kalshi_auth.PAPER else 'LIVE'} — approval #{oid}")
        logger.info("[mcp] %s", msg)

        async def _tell() -> None:
            if HOOKS.emit:
                try:
                    await HOOKS.emit("mcp:order", {"mode": "live", "message": msg,
                                                   "approvalId": oid})
                except Exception:
                    pass
            if HOOKS.notify_phone:
                try:
                    await HOOKS.notify_phone(
                        f"[AI AGENT] {msg}\nApprove in the app, or reply: approve {oid}"
                        f"  (reject {oid} to refuse; expires in "
                        f"{APPROVAL_TTL_SEC // 60} min)")
                except Exception:
                    pass
        return ({"mode": "live", "ok": True, "pending": True, "approvalId": oid,
                 "message": ("Queued for the user's approval. Nothing has been sent. "
                             f"Check with get_order_status; it expires in "
                             f"{APPROVAL_TTL_SEC // 60} minutes.")},
                _tell)
    out, msg = await _execute_live(v, mode, client, agent_id=aid, env=env)
    return out, (lambda: _announce(mode, f"{who}: {msg}"))


async def _execute_live(v: Vetted, mode: str, client: str,
                        row_id: Optional[int] = None,
                        agent_id: str = DEFAULT_AGENT,
                        env: Optional[str] = None) -> tuple[dict, str]:
    """Send one vetted order and record what came back. Returns the tool
    result and the line to announce; the caller announces it once the money
    lock is released. Raises ToolError on a refusal, already recorded.

    `env` is the scope the order was decided in (an approval: the one it was
    QUEUED in). The send is pinned to it, so a switch while the re-vet read
    the market refuses the order instead of sending it in the other book."""
    req = v.req
    env = env or kalshi_auth.get_env()
    if HOOKS.submit is None:
        raise ToolError("Live trading is not wired in this build.")
    try:
        res = await HOOKS.submit(dict(req), scope=env)
    except Exception as e:
        why = (f"send errored ({type(e).__name__}); it may or may not have "
               f"reached Kalshi — check your Kalshi orders before retrying")
        committed = v.cost if req["action"] == "buy" else None
        if row_id is None:
            _audit(mode=mode, client=client, req=req, ok=False, message=why,
                   forecast_id=v.forecast_id, committed=committed, status="unknown",
                   agent_id=agent_id, env=env)
        else:
            with db.get_db() as conn:
                conn.execute(
                    "UPDATE mcp_orders SET ok=0, status='unknown', committed_usd=?, "
                    "message=? WHERE id=?", (committed, why, row_id))
        logger.warning("[mcp] live send errored: %s: %s", type(e).__name__, e)
        raise ToolError(why)
    ok = bool(res.get("ok"))
    committed = v.cost if (ok and req["action"] == "buy") else None
    if row_id is None:
        _audit(mode=mode, client=client, req=req, ok=ok,
               message=str(res.get("message") or ""), forecast_id=v.forecast_id,
               committed=committed, order_id=res.get("orderId"),
               filled=res.get("filledContracts"), avg=res.get("avgFillCents"),
               agent_id=agent_id, env=env)
    else:
        with db.get_db() as conn:
            conn.execute(
                "UPDATE mcp_orders SET ok=?, status=?, committed_usd=?, order_id=?, "
                "filled=?, avg_fill_cents=?, message=? WHERE id=?",
                (1 if ok else 0, "approved" if ok else "failed", committed,
                 res.get("orderId"), res.get("filledContracts"),
                 res.get("avgFillCents"), str(res.get("message") or "")[:500], row_id))
    if not ok:
        raise ToolError(f"Kalshi/terminal refused: {res.get('message')}")
    msg = (f"LIVE {req['action']} {req['count']} {req['side'].upper()} "
           f"{req['ticker']} @ {req['priceCents']:g}c "
           f"{'on PAPER' if env == kalshi_auth.PAPER else 'with real money'} "
           f"— {res.get('message')}")
    return ({"mode": "live", "ok": True, "orderId": res.get("orderId"),
             "status": res.get("status"), "filled": res.get("filledContracts"),
             "avgFillCents": res.get("avgFillCents"), "feesUsd": res.get("feesUsd"),
             "message": res.get("message")}, msg)


async def decide(row_id: int, approve: bool, via: str = "app") -> dict:
    """The user's answer to a pending live order. Approval RE-VETS against the
    market as it is now — the agent asked minutes ago, and the price, the
    position cap or today's loss may have moved since.

    The whole answer runs under the money lock: two approvals clicked
    together must re-vet one after the other, each seeing what the other
    spent, or both pass a cap that fits one."""
    async with _money_lock():
        out, msg = await _decide_locked(int(row_id), approve, via)
    if msg:
        await _announce("live", msg)
    return out


async def _decide_locked(row_id: int, approve: bool, via: str) -> tuple[dict, Optional[str]]:
    with db.get_db() as conn:
        r = conn.execute("SELECT * FROM mcp_orders WHERE id=?", (row_id,)).fetchone()
        if r is None or r["status"] != "pending":
            return {"ok": False, "message": f"No pending agent order #{row_id}."}, None
        if _effective_status(r) == "expired":
            conn.execute("UPDATE mcp_orders SET status='expired' WHERE id=?", (row_id,))
            return {"ok": False, "message": f"Agent order #{row_id} expired; nothing was sent."}, None
        if not approve:
            conn.execute("UPDATE mcp_orders SET status='rejected', message=? WHERE id=?",
                         (f"rejected by the user ({via})", row_id))
            logger.info("[mcp] approval #%s rejected via %s", row_id, via)
            return {"ok": True, "message": f"Rejected agent order #{row_id}."}, None
        queued_env = r["kalshi_env"] or ""
        cur_env = kalshi_auth.get_env()
        if queued_env != cur_env:
            why = (f"queued on {queued_env or 'an unknown environment'}, but the "
                   f"app is now on {cur_env}; nothing was sent")
            conn.execute("UPDATE mcp_orders SET status='failed', message=? WHERE id=?",
                         (why, row_id))
            logger.info("[mcp] approval #%s refused: %s", row_id, why)
            return {"ok": False, "message": f"Agent order #{row_id} was {why}."}, None
        conn.execute("UPDATE mcp_orders SET status='deciding' WHERE id=?", (row_id,))
    sent = False
    try:
        cfg = HOOKS.get_cfg()
        aid = _row_agent(r)
        agent = mcp_agents.get(cfg, aid)
        mode = _agent_mode(cfg, agent)
        args = {"ticker": r["ticker"], "side": r["side"], "action": r["action"],
                "count": r["count"], "price_cents": r["price_cents"],
                "forecast_id": r["forecast_id"]}
        v = None
        if agent is None:
            blockers = ["the agent that asked for it no longer exists"]
        elif not agent.get("enabled", True):
            blockers = [f"{agent['name']} is switched off"]
        elif mode != "live":
            blockers = ([f"agent trading is now {trade_mode(cfg)}, not live"]
                        if trade_mode(cfg) != "live"
                        else [f"{agent['name']} is now on paper, not live"])
        else:
            v = await vet(args, cfg, mode, forecast_grace=APPROVAL_TTL_SEC,
                          exclude_id=row_id, agent=agent)
            blockers = v.blockers
        if blockers or v is None:
            with db.get_db() as conn:
                conn.execute("UPDATE mcp_orders SET status='failed', message=? WHERE id=?",
                             ("approved, but refused on re-check: " + blockers[0], row_id))
            return {"ok": False, "message": "Approved, but it no longer passes: " + blockers[0]}, None
        sent = True
        try:
            res, msg = await _execute_live(v, mode, r["client"] or "", row_id=row_id,
                                           agent_id=aid, env=queued_env)
            msg = f"{safe_agent_name(agent['name'])}: {msg}"
        except ToolError as e:
            return {"ok": False, "message": str(e)}, None
        logger.info("[mcp] approval #%s approved via %s", row_id, via)
        return {"ok": True, "message": f"Approved #{row_id}: {res.get('message')}"}, msg
    except Exception as e:
        if sent:
            st, why = "unknown", (f"approval errored while sending ({type(e).__name__}); "
                                  f"check your Kalshi orders before retrying")
        else:
            st, why = "failed", (f"approval errored during the re-check "
                                 f"({type(e).__name__}); nothing was sent")
        logger.warning("[mcp] approval #%s errored: %s: %s", row_id, type(e).__name__, e)
        try:
            with db.get_db() as conn:
                conn.execute(
                    "UPDATE mcp_orders SET status=?, message=? "
                    "WHERE id=? AND status='deciding'", (st, why, row_id))
        except Exception:
            pass
        return {"ok": False, "message": f"Agent order #{row_id}: {why}."}, None


async def t_order_status(args: dict, ctx: dict) -> dict:
    try:
        rid = int(args.get("approval_id"))
    except (TypeError, ValueError):
        raise ToolError("approval_id must be the number place_order returned")
    with db.get_db() as conn:
        r = conn.execute("SELECT * FROM mcp_orders WHERE id=?", (rid,)).fetchone()
    if r is None or _row_agent(r) != str(ctx.get("agent") or DEFAULT_AGENT):
        raise ToolError(f"No agent order #{rid}.")
    return {"approvalId": rid,
            "status": _effective_status(r) or ("sent" if r["ok"] else "refused"),
            "orderId": r["order_id"], "filled": r["filled"],
            "avgFillCents": r["avg_fill_cents"], "message": _effective_message(r),
            "env": r["kalshi_env"] or None}


async def _announce(mode: str, msg: str) -> None:
    logger.info("[mcp] %s", msg)
    if HOOKS.emit:
        try:
            await HOOKS.emit("mcp:order", {"mode": mode, "message": msg})
        except Exception:
            pass
    if mode == "live" and HOOKS.notify_phone:
        try:
            await HOOKS.notify_phone(f"[AI AGENT] {msg}")
        except Exception:
            pass


async def t_orders(_args: dict, ctx: dict) -> dict:
    cfg = HOOKS.get_cfg()
    agent = _agent(ctx, cfg)
    if _agent_mode(cfg, agent) != "live":
        return {"orders": [], "note": "Paper orders never rest — they fill or are dropped."}
    import terminal
    mine = _live_agent_order_ids(agent["id"] if agent else DEFAULT_AGENT)
    res = await terminal.resting_orders(HOOKS.is_authed())
    return {"orders": [o for o in res.get("orders") or [] if o.get("orderId") in mine],
            "note": "Only orders this agent placed are shown."}


async def t_cancel(args: dict, ctx: dict) -> dict:
    cfg = HOOKS.get_cfg()
    agent = _agent(ctx, cfg)
    if _agent_mode(cfg, agent) != "live":
        raise ToolError("Nothing to cancel: paper orders never rest.")
    oid = _s(args, "order_id")
    if oid not in _live_agent_order_ids(agent["id"] if agent else DEFAULT_AGENT):
        if oid in _live_agent_order_ids():
            raise ToolError("That order was placed by another of the user's agents; "
                            "an agent cancels only its own.")
        raise ToolError("That order was not placed by an agent; it is the user's.")
    if HOOKS.cancel is None:
        raise ToolError("Cancel is not wired in this build.")
    res = await HOOKS.cancel(oid)
    logger.info("[mcp] cancel %s by %s -> %s", oid, ctx.get("client"), res.get("message"))
    if res.get("ok"):
        try:
            await _note_cancelled(oid)
        except Exception as e:
            logger.debug("mcp cancel bookkeeping failed for %s: %s", oid, e)
    return {"ok": bool(res.get("ok")), "message": res.get("message")}


async def _note_cancelled(order_id: str) -> None:
    """Book a cancelled agent order at what it actually filled. A cancelled
    buy opened only its fills (which _live_agent_net already counts); a
    cancelled sell stops counting its full size against the sell allowance
    once its fills are KNOWN — if Kalshi's ledger cannot be read, it keeps
    counting in full, because a sell that filled unseen and was then
    forgotten would let the agent sell the same contracts twice."""
    import terminal
    env = kalshi_auth.get_env()
    with db.get_db() as conn:
        r = conn.execute(
            "SELECT id, action, side, count, filled FROM mcp_orders "
            "WHERE ok=1 AND mode='live' AND kalshi_env=? AND order_id=? "
            "ORDER BY id DESC LIMIT 1",
            (env, order_id)).fetchone()
    if r is None:
        return
    n = avg = None
    if HOOKS.is_authed():
        n, avg = await terminal._reconcile_fills(order_id, r["side"], pin_env=env)
    if n is None and r["action"] == "sell":
        return
    filled = r["filled"] if n is None else min(int(r["count"]), max(int(r["filled"] or 0), int(n)))
    with db.get_db() as conn:
        conn.execute(
            "UPDATE mcp_orders SET status='cancelled', filled=?, "
            "avg_fill_cents=COALESCE(?, avg_fill_cents) WHERE id=?",
            (filled, avg, int(r["id"])))



async def close_agent_paper(agent_id: Any) -> dict:
    """Sell one agent's open PAPER positions at the bid, for the user.

    A deleted or switched-off agent cannot sell what it holds (every tool
    refuses it), and its positions used to sit in the paper book for good —
    spending the shared position cap and the loss stop. This is the way out.
    It is the USER's action: service exposes it to the app
    (mcp_agent_close_paper); it is not a tool and not in _MCP_RPC_ALLOWED, so
    no agent can call it, for itself or for another agent.

    Paper only — it touches paper_book and nothing else, whatever the account
    mode. Each position walks the real bids down to 1c (what a marketable
    sell would get); depth that runs out, or a side nobody bids, stays open
    and is reported as such rather than closed at an invented price."""
    import terminal
    aid = str(agent_id or "").strip().lower()
    if aid != DEFAULT_AGENT and not mcp_agents.valid_id(aid):
        return {"ok": False, "message": "No such agent.", "closed": [], "open": []}
    who = safe_agent_name(_names().get(aid) or "the deleted agent")
    closed: list[dict] = []
    left: list[dict] = []
    async with _money_lock():
        for p in paper_book.open_positions(aid):
            try:
                book = await terminal.book(p["ticker"])
            except Exception as e:
                logger.debug("close paper: book read failed for %s: %s", p["ticker"], e)
                book = None
            fill = paper_book.simulate_fill(book, p["side"], "sell", p["contracts"], 1.0)
            n = int(fill.get("filled") or 0)
            if n > 0:
                avg = float(fill["avgPriceCents"])
                fee = terminal._fee_usd(avg, n)
                paper_book.record_fill(
                    ticker=p["ticker"], title=p.get("title") or "", side=p["side"],
                    action="sell", contracts=n, price_cents=avg, fee_usd=fee,
                    forecast_id=None, client="app (closed by the user)",
                    env=kalshi_auth.get_env(), agent_id=aid)
                _audit(mode="paper", client="app (closed by the user)",
                       req={"ticker": p["ticker"], "side": p["side"], "action": "sell",
                            "count": n, "priceCents": avg},
                       ok=True, message=(f"PAPER sell {n} {p['side'].upper()} {p['ticker']} "
                                         f"@ {avg:g}c avg, closed by the user"),
                       filled=n, avg=avg, agent_id=aid)
                closed.append({"ticker": p["ticker"], "side": p["side"], "contracts": n,
                               "avgPriceCents": avg, "feeUsd": fee})
            if n < p["contracts"]:
                left.append({"ticker": p["ticker"], "side": p["side"],
                             "contracts": p["contracts"] - n,
                             "reason": (fill.get("note") or "nobody is bidding it")})
    if closed:
        await _announce("paper", f"Closed {sum(c['contracts'] for c in closed)} paper "
                                 f"contract(s) of {who} at the bid.")
    if not closed and not left:
        msg = "Nothing to close: this agent holds no paper positions."
    elif left:
        msg = (f"Closed {len(closed)} position(s); {len(left)} could not be closed "
               f"in full (no bid deep enough). Try again when the market trades.")
    else:
        msg = f"Closed {len(closed)} paper position(s) at the bid."
    return {"ok": not left, "message": msg, "closed": closed, "open": left}


TOOLS: list[Tool] = [
    Tool("get_status", "Status and rails",
         "Trading mode (off/paper/live), Kalshi environment, the agent's money "
         "caps and today's spend. Call this first.",
         _obj({}), t_status),
    Tool("get_my_agent", "Who you are",
         "The user's named agent you are connected as: your name, the guide the "
         "user wrote for you (how they want you to think and decide), your hard "
         "rules (categories, price band, time to close, sides, sizes, minimum "
         "edge, money caps — enforced by the app on every order) and whether you "
         "trade paper or live. Read it before trading.",
         _obj({}), t_my_agent),
    Tool("discover_markets", "Discover markets",
         "List open Kalshi markets by column: trending (live tape), closing "
         "(soonest close that can still trade), new, volume. Prices in cents; "
         "null means absent (no bid / never traded), never zero.",
         _obj({"column": {"type": "string", "enum": ["trending", "closing", "new", "volume"]},
               "limit": {"type": "integer", "minimum": 1, "maximum": 50}}),
         t_discover),
    Tool("search_markets", "Search markets",
         "Search open Kalshi markets by words in the question.",
         _obj({"query": {"type": "string"},
               "limit": {"type": "integer", "minimum": 1, "maximum": 50}}, ("query",)),
         t_search),
    Tool("get_market", "Read one market",
         "Everything the terminal knows about one market: quote with per-field "
         "source, the event and sibling markets, the RESOLUTION RULES, a "
         "resolution-risk check, and the order book. Read the rules before "
         "forecasting — markets settle on their terms, not their headline.",
         _obj({"ticker": _TICKER}, ("ticker",)), t_market),
    Tool("get_orderbook", "Order book",
         "Live order book ladders for one market.",
         _obj({"ticker": _TICKER}, ("ticker",)), t_book),
    Tool("record_forecast", "Record a forecast",
         "Commit to your fair value for YES on a market, in cents (1-99), with "
         "your reasoning. Returns a forecast_id (needed to buy) and your edge "
         "on each side after fees. Every forecast is scored against the market "
         "price at this moment once the market settles — record honest numbers, "
         "including ones that say 'no trade'.",
         _obj({"ticker": _TICKER,
               "fair_value_cents": {"type": "number", "minimum": 1, "maximum": 99},
               "rationale": {"type": "string", "maxLength": 2000},
               "model": {"type": "string", "description": "Your model name, for the scoreboard."}},
              ("ticker", "fair_value_cents", "rationale")),
         t_forecast, read_only=False),
    Tool("get_scoreboard", "Forecast scoreboard",
         "How AI forecasts have scored against the market on settled markets "
         "(Brier score, lower is better; paired against the market mid at the "
         "time). If the AI is not beating the market, its edges are not real.",
         _obj({}), t_scoreboard),
    Tool("get_portfolio", "Agent portfolio",
         "The agent's positions: the paper book in paper mode, the live account "
         "in live mode (positions the agent opened are marked).",
         _obj({}), t_portfolio, perm="trade"),
    Tool("preview_order", "Preview an order",
         "Run every rail on an order without placing it: edge after fees versus "
         "your forecast, per-order and daily caps, position cap, cost.",
         _obj({"ticker": _TICKER, "side": _SIDE, "action": _ACTION,
               "count": _COUNT, "price_cents": _PRICE,
               "forecast_id": {"type": "integer"}},
              ("ticker", "side", "action", "count", "price_cents")),
         t_preview, perm="trade"),
    Tool("place_order", "Place an order",
         "Place a limit order (paper or live, per the user's setting). A buy "
         "requires forecast_id from record_forecast on this market within the "
         "last 30 minutes, and is refused unless that forecast beats the price "
         "by the minimum edge after fees. A live sell may only close contracts "
         "your own buys have FILLED on this environment. Paper orders are "
         "immediate-or-cancel against the real book.",
         _obj({"ticker": _TICKER, "side": _SIDE, "action": _ACTION,
               "count": _COUNT, "price_cents": _PRICE,
               "forecast_id": {"type": "integer"}},
              ("ticker", "side", "action", "count", "price_cents")),
         t_place, perm="trade", read_only=False, destructive=True),
    Tool("get_order_status", "Order / approval status",
         "Status of an order place_order queued for the user's approval: "
         "pending, approved, rejected, expired or failed — or unknown if the "
         "send errored and it may have reached Kalshi, cancelled if you "
         "cancelled it.",
         _obj({"approval_id": {"type": "integer"}}, ("approval_id",)),
         t_order_status, perm="trade"),
    Tool("list_orders", "Resting orders",
         "Live resting orders this agent placed.",
         _obj({}), t_orders, perm="trade"),
    Tool("cancel_order", "Cancel an order",
         "Cancel a live resting order this agent placed.",
         _obj({"order_id": {"type": "string"}}, ("order_id",)),
         t_cancel, perm="trade", read_only=False),
    Tool("move_funds", "Move cash between exchanges",
         "LIVE only. Kalshi keeps the user's cash per exchange (general, combos, "
         "crypto, tennis & baseball), and an order can only be backed by the "
         "exchange its market trades on. Moves amount_usd onto to_exchange, from "
         "from_exchange or (omitted) whichever holds the most. The money stays "
         "in the user's account. Capped per day together with the app's own "
         "automatic moves; get_status shows the split.",
         _obj({"amount_usd": {"type": "number", "minimum": 0.01},
               "to_exchange": {"type": "string", "description": "general, combos, crypto, tennis & baseball, or the exchange number"},
               "from_exchange": {"type": "string"}},
              ("amount_usd", "to_exchange")),
         t_move_funds, perm="trade", read_only=False, destructive=True),
]
_BY_NAME = {t.name: t for t in TOOLS}


def register(tools: list[Tool]) -> None:
    for t in tools:
        if t.name in _BY_NAME:
            raise ValueError(f"duplicate MCP tool {t.name}")
        TOOLS.append(t)
        _BY_NAME[t.name] = t


PERMISSIONS = ("mcp_allow_research", "mcp_allow_scripts", "mcp_allow_script_run",
               "mcp_allow_config", "mcp_allow_live_switches")


def allowed(tool: Tool, cfg: dict) -> bool:
    if tool.perm is None:
        return True
    if tool.perm == "trade":
        return trade_mode(cfg) != "off"
    if tool.perm == "mcp_allow_config":
        return bool(cfg.get("mcp_allow_config") or cfg.get("mcp_allow_live_switches"))
    return bool(cfg.get(tool.perm))


def visible_tools(cfg: dict) -> list[Tool]:
    return [t for t in TOOLS if allowed(t, cfg)]


INSTRUCTIONS = """Krypt Trader: Kalshi prediction markets, from the user's own desktop app.

Prices are cents 1-99 and read as probabilities (62c ~ 62%). A null or "--" \
field is ABSENT — no bid, never traded — never zero; do not reason about it as 0.

How to trade here:
1. get_status — see the mode (off / paper / live) and your caps; get_my_agent \
— who you are, the user's guide for you, and your rules.
2. discover_markets / search_markets, then get_market. Read the resolution rules.
3. record_forecast with your honest fair value and reasoning. It returns your \
edge on each side AFTER Kalshi's fee.
4. Only if the edge clears the minimum: place_order with that forecast_id.

Most markets should end at step 3 with no trade: a liquid market's price is a \
strong forecast, and fees eat small edges. Every forecast is scored against the \
market once it settles (get_scoreboard). Paper fills are real-book, \
imaginary-money, immediate-or-cancel. Never invent a number you could not justify."""


def instructions_for(ctx: dict, cfg: Optional[dict] = None) -> str:
    """INSTRUCTIONS, plus — for one of the user's customised agents — who it
    is, the user's guide and a plain summary of its hard rules, so it does
    not spend calls on orders that will be refused."""
    cfg = cfg if cfg is not None else HOOKS.get_cfg()
    agent = _agent(ctx, cfg)
    if agent is None:
        return INSTRUCTIONS
    return mcp_agents.instructions(INSTRUCTIONS, agent, _agent_rails(cfg, agent),
                                   _agent_mode(cfg, agent))



def _ok(mid: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _rpc_err(mid: Any, code: int, msg: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


async def call_tool(name: str, args: dict, ctx: dict) -> dict:
    """The one dispatcher: MCP over HTTP, the stdio bridge (via HTTP),
    Autopilot, and any later transport all land here, so every rail below —
    and the tool-call event — applies to all of them."""
    started = time.monotonic()
    tool = _BY_NAME.get(name)
    cfg = HOOKS.get_cfg()
    agent = _agent(ctx, cfg)
    mode = _agent_mode(cfg, agent)

    async def _done(out: dict, outcome: str, reason: Optional[str] = None,
                    res: Any = None) -> dict:
        await _emit_call(name=name if tool is not None else "unknown", args=args, ctx=ctx,
                         res=res, outcome=outcome, reason=reason, started=started, mode=mode)
        return out

    if agent is None or not agent.get("enabled", True):
        why = ("This agent no longer exists in Krypt Trader." if agent is None
               else f"{agent['name']} is switched off in Krypt Trader → AI Agents. "
                    f"Nothing was executed.")
        return await _done({"content": [{"type": "text", "text": why}], "isError": True},
                           "refused", why)
    if tool is None or not allowed(tool, cfg):
        return await _done({"content": [{"type": "text", "text": f"Unknown or disabled tool: {name}"}],
                            "isError": True}, "refused", "unknown or disabled tool")
    over = _rate_refusal(agent["id"])
    if over:
        return await _done({"content": [{"type": "text", "text": (
            f"Rate limit: {over}. Slow down; nothing was executed.")}],
            "isError": True}, "refused", f"rate limit: {over}")
    STATUS.calls += 1
    STATUS.last_call_at = _now()
    STATUS.last_tool = name
    try:
        res = await tool.handler(args if isinstance(args, dict) else {}, ctx)
    except ToolError as e:
        return await _done({"content": [{"type": "text", "text": str(e)}], "isError": True},
                           "refused", str(e))
    except Exception as e:
        logger.warning("[mcp] tool %s failed: %s: %s", name, type(e).__name__, e)
        return await _done({"content": [{"type": "text", "text": f"{name} failed: {type(e).__name__}: {e}"}],
                            "isError": True}, "error", f"{name} failed ({type(e).__name__})")
    text = res if isinstance(res, str) else json.dumps(res, default=str, indent=1)
    return await _done({"content": [{"type": "text", "text": text}], "isError": False},
                       "ok", res=res)


async def handle_message(msg: Any, ctx: dict) -> Optional[dict]:
    """One JSON-RPC message in, one response (or None for a notification) out."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _rpc_err(None, -32600, "invalid request")
    mid = msg.get("id")
    method = msg.get("method")
    if method is None:
        return None
    is_note = "id" not in msg
    params = msg.get("params") or {}

    if method == "initialize":
        want = str(params.get("protocolVersion") or "")
        ver = want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        info = params.get("clientInfo") or {}
        name = str(info.get("name") or "unknown")[:40]
        version = str(info.get("version") or "")[:20]
        ctx["client"] = f"{name} {version}".strip()
        await _emit_connect(ctx)
        return _ok(mid, {
            "protocolVersion": ver,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": "Krypt Trader",
                           "version": HOOKS.version or "0"},
            "instructions": instructions_for(ctx),
        })
    if is_note:
        return None
    if method == "ping":
        return _ok(mid, {})
    if method == "tools/list":
        return _ok(mid, {"tools": [t.spec() for t in visible_tools(HOOKS.get_cfg())]})
    if method == "tools/call":
        name = str(params.get("name") or "")
        return _ok(mid, await call_tool(name, params.get("arguments") or {}, ctx))
    return _rpc_err(mid, -32601, f"method not found: {method}")



@dataclass
class _Status:
    running: bool = False
    port: Optional[int] = None
    last_error: Optional[str] = None
    calls: int = 0
    last_call_at: Optional[str] = None
    last_tool: Optional[str] = None
    clients: dict = field(default_factory=dict)
    seen: dict = field(default_factory=dict)


STATUS = _Status()
_server: Optional[asyncio.AbstractServer] = None
_REASONS = {200: "OK", 202: "Accepted", 400: "Bad Request", 401: "Unauthorized",
            403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
            411: "Length Required", 413: "Payload Too Large",
            422: "Unprocessable Entity", 429: "Too Many Requests",
            431: "Request Header Fields Too Large", 500: "Internal Server Error"}


def _note_client(name: str) -> None:
    if not name:
        return
    STATUS.seen.pop(name, None)
    STATUS.seen[name] = _now()
    while len(STATUS.seen) > 64:
        STATUS.seen.pop(next(iter(STATUS.seen)))


def last_seen() -> Optional[dict]:
    if not STATUS.seen:
        return None
    name = next(reversed(STATUS.seen))
    return {"client": name, "at": STATUS.seen[name]}


API_PREFIX = "/api/v1"


def check_request(method: str, path: str, headers: dict, port: int,
                  token: Any) -> Optional[tuple[int, str]]:
    """(status, reason) to refuse with, or None to proceed. Pure, so the
    security checks are testable without a socket.

    `token` is one token (str), or a matcher (callable: supplied -> bool)
    that knows every agent's — the listener passes the matcher, which also
    records WHICH agent the token belongs to. Falsy = no token exists at all.

    The MCP endpoint and the HTTP API pass through the same Host, Origin and
    token checks in the same order; only the method rule differs, and the API
    applies its own per route."""
    route = path.split("?", 1)[0]
    is_mcp = route == "/mcp"
    if not is_mcp and route != API_PREFIX and not route.startswith(API_PREFIX + "/"):
        return 404, "not found"
    host = (headers.get("host") or "").lower()
    if host not in (f"{_LOOPBACK}:{port}", f"{_LOCALHOST}:{port}", _LOOPBACK, _LOCALHOST):
        return 403, "host not allowed"
    origin = (headers.get("origin") or "").lower()
    if origin and origin != "null" and origin not in (
            f"http://{_LOOPBACK}:{port}", f"http://{_LOCALHOST}:{port}"):
        return 403, "origin not allowed"
    if not token:
        return 401, "server has no token"
    auth = headers.get("authorization") or ""
    supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    ok = (bool(token(supplied)) if callable(token)
          else secrets.compare_digest(supplied, token)) if supplied else False
    if not ok:
        return 401, "bad or missing bearer token"
    if is_mcp and method != "POST":
        return 405, "POST only"
    return None



_TOOL_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_RATE_LIMIT_TEXT = "Rate limit:"
_UA_CLEAN = re.compile(r"[^A-Za-z0-9 ._/()+:;,-]")


def http_client_name(user_agent: Optional[str]) -> str:
    """How an HTTP caller appears in activity and audit: `http:<user-agent>`.

    Self-declared, exactly like an MCP client's clientInfo name, so it is a
    LABEL for the user to read and never a security boundary. Cleaned to
    printable characters and capped so a hostile header cannot forge extra
    log lines or blow out the audit column."""
    ua = _UA_CLEAN.sub("", str(user_agent or "")).strip()
    ua = re.sub(r"\s+", " ", ua)[:60].strip()
    return f"http:{ua or 'unknown'}"


def _api_err(status: int, msg: str, tool: Optional[str] = None,
             extra: Optional[dict] = None) -> tuple[int, dict, Optional[dict]]:
    body: dict = {"ok": False, "error": msg}
    if tool:
        body["tool"] = tool
    return status, body, extra


def _result_body(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return text


async def handle_api(method: str, path: str, body: bytes, headers: dict,
                     port: int, agent_id: str = DEFAULT_AGENT) -> tuple[int, Any, Optional[dict]]:
    """One authenticated /api/v1 request -> (status, JSON body, extra headers).
    Host, Origin and token were already checked by check_request, and the
    token named `agent_id` — the agent every call here runs as."""
    cfg = HOOKS.get_cfg()
    if not cfg.get("mcp_http_enabled"):
        return _api_err(403, "The HTTP API is switched off. Turn it on in Krypt "
                             "Trader -> AI Agents -> HTTP API.")
    route = path.split("?", 1)[0][len(API_PREFIX):].rstrip("/")
    actx = {"agent": agent_id}

    if route == "/tools":
        if method != "GET":
            return _api_err(405, "GET only", extra={"Allow": "GET"})
        agent = _agent(actx, cfg)
        return 200, {"tools": [t.spec() for t in visible_tools(cfg)],
                     "tradeMode": _agent_mode(cfg, agent),
                     "agent": {"id": agent["id"], "name": agent["name"]} if agent else None,
                     "instructions": instructions_for(actx, cfg)}, None

    if route == "/openapi.json":
        if method != "GET":
            return _api_err(405, "GET only", extra={"Allow": "GET"})
        return 200, openapi_spec(cfg, port, instructions_for(actx, cfg)), None

    if route.startswith("/tools/"):
        name = route[len("/tools/"):]
        if not _TOOL_NAME_RE.fullmatch(name):
            return _api_err(404, f"Unknown or disabled tool: {name[:64]}")
        if method != "POST":
            return _api_err(405, "POST only", name, {"Allow": "POST"})
        try:
            args = json.loads(body) if body.strip() else {}
        except ValueError:
            return _api_err(400, "The body must be a JSON object of tool arguments.", name)
        if not isinstance(args, dict):
            return _api_err(400, "The body must be a JSON object of tool arguments.", name)
        tool = _BY_NAME.get(name)
        known = tool is not None and allowed(tool, cfg)
        client = http_client_name(headers.get("user-agent"))
        _note_client(client)
        res = await call_tool(name, args, {"client": client, "transport": "http",
                                           "agent": agent_id})
        text = res["content"][0]["text"] if res.get("content") else ""
        if not res.get("isError"):
            return 200, {"ok": True, "tool": name, "result": _result_body(text)}, None
        if not known:
            return _api_err(404, text, name)
        if text.startswith(_RATE_LIMIT_TEXT):
            return _api_err(429, text, name, {"Retry-After": str(int(RATE_WINDOW))})
        return _api_err(422, text, name)

    return _api_err(404, "not found")


_API_ERROR_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean", "const": False},
                   "error": {"type": "string",
                             "description": "Why it was refused, in the same words an MCP client gets."},
                   "tool": {"type": "string"}},
    "required": ["ok", "error"],
}


def openapi_spec(cfg: dict, port: int, instructions: Optional[str] = None) -> dict:
    """OpenAPI 3.1, built from the SAME Tool objects tools/list serves, and
    only the ones visible under the user's current switches — the document
    never advertises a tool a call would refuse as disabled."""
    def _err(desc: str) -> dict:
        return {"description": desc,
                "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}

    common = {
        "401": _err("Missing or wrong bearer token."),
        "403": _err("Foreign Host/Origin, or the HTTP API is switched off."),
        "404": _err("Unknown tool, or one the user has not enabled."),
        "422": _err("Refused by a rail (trade mode, forecast gate, caps, loss stop...). "
                    "Read `error` and act on it."),
        "429": _err("Rate limited. Nothing was executed."),
    }
    paths: dict = {
        f"{API_PREFIX}/tools": {"get": {
            "operationId": "list_tools",
            "summary": "List the tools available right now",
            "description": "Names, descriptions and JSON input schemas. Changes when "
                           "the user changes trade mode or permissions.",
            "responses": {"200": {"description": "Tool list",
                                  "content": {"application/json": {"schema": {"type": "object"}}}},
                          "401": common["401"], "403": common["403"]},
        }},
    }
    for t in visible_tools(cfg):
        paths[f"{API_PREFIX}/tools/{t.name}"] = {"post": {
            "operationId": t.name,
            "summary": t.title,
            "description": t.description,
            "requestBody": {
                "required": bool(t.schema.get("required")),
                "content": {"application/json": {"schema": t.schema}},
            },
            "responses": {
                "200": {"description": "The tool's result.",
                        "content": {"application/json": {"schema": {
                            "type": "object",
                            "properties": {"ok": {"type": "boolean", "const": True},
                                           "tool": {"type": "string"},
                                           "result": {}},
                            "required": ["ok", "result"]}}}},
                **common,
            },
            "x-krypt-read-only": t.read_only,
            "x-krypt-destructive": t.destructive,
        }}
    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Krypt Trader agent API",
            "version": HOOKS.version or "0",
            "description": ((instructions or INSTRUCTIONS) + "\n\nEvery call runs through the same rails "
                            "as the MCP server: trade mode, forecast before every buy, "
                            "minimum edge after fees, caps, approvals and the daily loss "
                            "stop. Loopback only."),
        },
        "servers": [{"url": f"http://{_LOOPBACK}:{int(port)}"}],
        "security": [{"bearer": []}],
        "components": {
            "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
            "schemas": {"Error": _API_ERROR_SCHEMA},
        },
        "paths": paths,
    }


async def _respond(writer: asyncio.StreamWriter, status: int, body: bytes = b"",
                   extra: Optional[dict] = None, close: bool = False) -> None:
    lines = [f"HTTP/1.1 {status} {_REASONS.get(status, 'Error')}",
             f"Content-Length: {len(body)}",
             "Cache-Control: no-store",
             f"Connection: {'close' if close else 'keep-alive'}"]
    if body:
        lines.append("Content-Type: application/json")
    for k, v in (extra or {}).items():
        lines.append(f"{k}: {v}")
    writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1") + body)
    await writer.drain()


def _json_body(obj: Any) -> bytes:
    return json.dumps(obj, default=str).encode("utf-8")


async def _handle_conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    port = STATUS.port or 0
    try:
        while True:
            try:
                head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), IDLE_SEC)
            except asyncio.LimitOverrunError:
                await _respond(writer, 431, close=True)
                return
            text = head.decode("latin-1")
            first, _, rest = text.partition("\r\n")
            parts = first.split(" ")
            if len(parts) < 2:
                await _respond(writer, 400, close=True)
                return
            method, path = parts[0].upper(), parts[1]
            headers: dict[str, str] = {}
            for ln in rest.split("\r\n"):
                if ":" in ln:
                    k, _, v = ln.partition(":")
                    headers[k.strip().lower()] = v.strip()
            if "chunked" in (headers.get("transfer-encoding") or "").lower():
                await _respond(writer, 411, close=True)
                return
            try:
                length = int(headers.get("content-length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > MAX_BODY:
                await _respond(writer, 413, close=True)
                return
            body = await asyncio.wait_for(reader.readexactly(length), IDLE_SEC) if length else b""
            close = (headers.get("connection") or "").lower() == "close"

            cfg = HOOKS.get_cfg()
            matched: dict = {}

            def _match(supplied: str) -> bool:
                matched["agent"] = resolve_token(supplied, cfg)
                return matched["agent"] is not None

            any_token = any(has_token(a["id"]) for a in mcp_agents.agents(cfg))
            refusal = check_request(method, path, headers, port, _match if any_token else None)
            agent = matched.get("agent")
            if refusal is None and agent is not None and not agent.get("enabled", True):
                refusal = (403, f"agent '{safe_agent_name(agent['name'])}' is switched off "
                                f"in Krypt Trader -> AI Agents")
            if refusal:
                code, why = refusal
                extra = {"WWW-Authenticate": "Bearer"} if code == 401 else (
                    {"Allow": "POST"} if code == 405 else None)
                await _respond(writer, code, _json_body({"error": why}), extra, close=close)
                if close:
                    return
                continue
            agent_id = agent["id"] if agent else DEFAULT_AGENT

            if path.split("?", 1)[0] != "/mcp":
                code, obj, extra = await handle_api(method, path, body, headers, port,
                                                    agent_id=agent_id)
                await _respond(writer, code, _json_body(obj), extra, close=close)
                if close:
                    return
                continue

            sid = headers.get("mcp-session-id") or ""
            ctx = {"client": STATUS.clients.get(sid, ""), "agent": agent_id}
            if ctx["client"]:
                _note_client(ctx["client"])
            try:
                payload = json.loads(body or b"null")
            except ValueError:
                await _respond(writer, 400, _json_body(_rpc_err(None, -32700, "parse error")),
                               close=close)
                continue
            msgs = payload if isinstance(payload, list) else [payload]
            replies = [r for r in [await handle_message(m, ctx) for m in msgs] if r is not None]
            extra = None
            if any(isinstance(m, dict) and m.get("method") == "initialize" for m in msgs):
                sid = secrets.token_hex(16)
                STATUS.clients[sid] = ctx.get("client") or "unknown"
                if len(STATUS.clients) > 64:
                    STATUS.clients.pop(next(iter(STATUS.clients)))
                extra = {"Mcp-Session-Id": sid}
                _note_client(STATUS.clients[sid])
                logger.info("[mcp] client connected: %s", STATUS.clients[sid])
            if not replies:
                await _respond(writer, 202, extra=extra, close=close)
            else:
                out = replies if isinstance(payload, list) else replies[0]
                await _respond(writer, 200, _json_body(out), extra, close=close)
            if close:
                return
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError):
        return
    except Exception as e:
        logger.debug("[mcp] connection error: %s", e)
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def start(port: int) -> None:
    global _server
    if _server is not None and STATUS.port == port:
        return
    await stop()
    get_token(create=True)
    try:
        _server = await asyncio.start_server(
            _handle_conn, host=_LOOPBACK, port=port, limit=MAX_HEAD)
    except OSError as e:
        STATUS.running = False
        STATUS.port = port
        STATUS.last_error = (f"Could not listen on {_LOOPBACK}:{port} — {e.strerror or e}. "
                             f"Another program may be using that port; pick another.")
        logger.warning("[mcp] %s", STATUS.last_error)
        return
    STATUS.running = True
    STATUS.port = port
    STATUS.last_error = None
    logger.info("[mcp] listening on %s:%d", _LOOPBACK, port)


async def stop() -> None:
    global _server
    if _server is not None:
        _server.close()
        try:
            await asyncio.wait_for(_server.wait_closed(), 3.0)
        except Exception:
            pass
        logger.info("[mcp] stopped")
    _server = None
    STATUS.running = False


async def sync(cfg: dict) -> None:
    if not cfg.get("mcp_enabled"):
        if _server is not None:
            await stop()
        return
    port = int(cfg.get("mcp_port") or DEFAULT_PORT)
    if _server is None or STATUS.port != port:
        await start(port)


def status(cfg: dict) -> dict:
    return {
        "enabled": bool(cfg.get("mcp_enabled")),
        "running": STATUS.running,
        "port": STATUS.port or int(cfg.get("mcp_port") or DEFAULT_PORT),
        "lastError": STATUS.last_error,
        "hasToken": bool(kalshi_auth.has_secret(TOKEN_SECRET)),
        "tradeMode": trade_mode(cfg),
        "env": kalshi_auth.get_env(),
        "calls": STATUS.calls,
        "lastCallAt": STATUS.last_call_at,
        "lastTool": STATUS.last_tool,
        "clients": sorted(set(STATUS.clients.values()) | set(STATUS.seen)),
        "lastSeen": last_seen(),
        "httpEnabled": bool(cfg.get("mcp_http_enabled")),
        "spentTodayUsd": round(spent_today(trade_mode(cfg)), 2),
        "rails": _rails(cfg),
        "permissions": {k: bool(cfg.get(k)) for k in PERMISSIONS},
        "liveApproval": bool(cfg.get("mcp_live_approval", True)),
        "pending": pending(),
        "toolCount": len(visible_tools(cfg)),
        "agents": agents_status(cfg),
    }


def agents_status(cfg: dict) -> list[dict]:
    """Per named agent: does it have a token, the mode it actually trades in,
    its spend today, and when it was last seen this session (memory only).
    Never the token itself."""
    out = []
    for a in mcp_agents.agents(cfg):
        mode = _agent_mode(cfg, a)
        s = AGENT_SEEN.get(a["id"]) or {}
        out.append({
            "id": a["id"], "hasToken": has_token(a["id"]), "effectiveMode": mode,
            "serverName": mcp_agents.server_name(a),
            "spentTodayUsd": (round(spent_today(mode, agent_id=a["id"]), 2)
                              if mode in ("paper", "live") else None),
            "lastSeenAt": s.get("lastAt"), "calls": s.get("calls", 0),
            "clients": list(s.get("clients") or []),
        })
    return out



CLIENTS = ("cursor", "claude-code", "claude-desktop", "codex")


def bridge_command() -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, ["--mcp-stdio"]
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "service.py")
    return sys.executable, [here, "--mcp-stdio"]


def client_config(client: str, port: int, token: str, agent: Optional[dict] = None) -> str:
    """One agent's config for one client. The token is the agent's own, so
    the client IS that agent; the server name is the agent's own too
    (mcp_agents.server_name), so two agents in one client sit side by side.
    Default keeps `krypt-trader`, the name every existing config uses."""
    url = f"http://{_LOOPBACK}:{port}/mcp"
    name = mcp_agents.server_name(agent) if agent else SERVER_NAME
    if client == "cursor":
        return json.dumps({"mcpServers": {name: {
            "url": url, "headers": {"Authorization": f"Bearer {token}"}}}}, indent=2)
    if client == "claude-code":
        return (f'claude mcp add --scope user --transport http {name} {url} '
                f'--header "Authorization: Bearer {token}"')
    if client == "codex":
        return (f"[mcp_servers.{name}]\n"
                f"url = '{url}'\n"
                f"http_headers = {{ Authorization = 'Bearer {token}' }}\n")
    cmd, args = bridge_command()
    args = args + ["--port", str(port)]
    if client == "claude-desktop":
        return json.dumps({"mcpServers": {name: {
            "command": cmd, "args": args, "env": {"KRYPT_MCP_TOKEN": token}}}}, indent=2)
    raise ValueError(f"client must be one of {CLIENTS}")


_HTTP_SNIPPET = """\
# Krypt Trader HTTP API - loopback only. The token below is a password.
# Every call runs through the same rails as MCP: trade mode, a forecast before
# every buy, minimum edge after fees, caps, approvals and the daily loss stop.

# --- curl (in Windows PowerShell type curl.exe, not curl) ---
curl -s -H "Authorization: Bearer __TOKEN__" __BASE__/tools
curl -s -X POST -H "Authorization: Bearer __TOKEN__" -H "Content-Type: application/json" -d "{}" __BASE__/tools/get_status
# OpenAPI document, for LangChain / n8n import:
curl -s -H "Authorization: Bearer __TOKEN__" -o krypt-openapi.json __BASE__/openapi.json

# --- Python (pip install requests) ---
import requests

KRYPT = "__BASE__"
HEADERS = {"Authorization": "Bearer __TOKEN__", "User-Agent": "my-bot/1.0"}


def call(tool, **args):
    r = requests.post(f"{KRYPT}/tools/{tool}", json=args, headers=HEADERS, timeout=120)
    body = r.json()
    if not body.get("ok"):
        # A refusal (no forecast, over a cap, trading off...) arrives here with
        # the reason in plain words. Read it; do not retry blindly.
        raise RuntimeError(f"{tool} -> HTTP {r.status_code}: {body.get('error')}")
    return body["result"]


print(call("get_status"))
"""


def http_snippet(port: int, token: str) -> str:
    base = f"http://{_LOOPBACK}:{int(port)}{API_PREFIX}"
    return _HTTP_SNIPPET.replace("__BASE__", base).replace("__TOKEN__", token)
