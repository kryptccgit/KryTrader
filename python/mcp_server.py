from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import db
import forecast_ledger
import kalshi_auth
import paper_book

logger = logging.getLogger("mcp")

SERVER_NAME = "krypt-trader"
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PORT = 47821
TOKEN_SECRET = "mcp_token"
TRADE_MODES = ("off", "paper", "live")

APPROVAL_TTL_SEC = 600

FORECAST_TTL_SEC = 1800

RATE_WINDOW = 60.0
RATE_MAX = 120

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
    submit: Optional[Callable[[dict], Awaitable[dict]]] = None
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


def get_token(create: bool = False) -> Optional[str]:
    tok = kalshi_auth.read_secret(TOKEN_SECRET)
    if not tok and create:
        tok = rotate_token()
    return tok


def rotate_token() -> str:
    tok = "kt_" + secrets.token_urlsafe(32)
    kalshi_auth.save_secret(TOKEN_SECRET, tok)
    try:
        import logscrub
        logscrub.refresh_known_secrets()
    except Exception:
        pass
    return tok


def trade_mode(cfg: dict) -> str:
    m = str(cfg.get("mcp_trade_mode") or "off").lower()
    return m if m in TRADE_MODES else "off"


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


def spent_today(mode: str) -> float:
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(committed_usd), 0) FROM mcp_orders "
            "WHERE (ok=1 OR status='pending') AND action='buy' AND mode=? "
            "AND substr(created_at,1,10)=?",
            (mode, _today())).fetchone()
    return float(row[0] or 0.0)


def _audit(*, mode: str, client: str, req: dict, ok: bool, message: str,
           forecast_id: Optional[int] = None, committed: Optional[float] = None,
           order_id: Optional[str] = None, filled: Optional[int] = None,
           avg: Optional[float] = None, status: Optional[str] = None) -> int:
    with db.get_db() as conn:
        cur = conn.execute(
            """INSERT INTO mcp_orders
               (created_at, kalshi_env, mode, client, ticker, side, action,
                count, price_cents, forecast_id, committed_usd, ok, order_id,
                filled, avg_fill_cents, message, status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), kalshi_auth.get_env(), mode, (client or "")[:80],
             req.get("ticker") or "", req.get("side") or "",
             req.get("action") or "", int(req.get("count") or 0),
             float(req.get("priceCents") or 0), forecast_id,
             round(committed, 4) if committed is not None else None,
             1 if ok else 0, order_id, filled, avg, (message or "")[:500], status),
        )
        return int(cur.lastrowid)


def activity(limit: int = 100) -> list[dict]:
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM mcp_orders ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
    return [{
        "id": int(r["id"]), "at": r["created_at"], "env": r["kalshi_env"],
        "mode": r["mode"], "client": r["client"] or None,
        "ticker": r["ticker"], "side": r["side"], "action": r["action"],
        "count": int(r["count"]), "priceCents": float(r["price_cents"]),
        "forecastId": r["forecast_id"], "committedUsd": r["committed_usd"],
        "ok": bool(r["ok"]), "orderId": r["order_id"], "filled": r["filled"],
        "avgFillCents": r["avg_fill_cents"], "message": r["message"] or "",
        "status": _effective_status(r),
    } for r in rows]


def _effective_status(r: Any) -> Optional[str]:
    st = r["status"]
    if st == "pending" and (_age_sec(r["created_at"]) or 0) > APPROVAL_TTL_SEC:
        return "expired"
    return st


def pending(limit: int = 50) -> list[dict]:
    return [a for a in activity(limit * 4) if a["status"] == "pending"][:limit]


async def day_loss(mode: str) -> dict:
    import kalshi_api
    import terminal
    today = _today()
    if mode == "paper":
        tickers = paper_book.open_tickers()
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
        realized = unreal = 0.0
        unmarked: list = []
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
                    else:
                        unreal += float(p["unrealizedUsd"])
            except Exception as e:
                logger.debug("loss-stop portfolio failed: %s", e)
        d = {"realizedUsd": round(realized, 2), "unrealizedUsd": round(unreal, 2),
             "unmarked": unmarked}
    d["lossUsd"] = round(max(0.0, -(d["realizedUsd"] + min(0.0, d["unrealizedUsd"]))), 2)
    return d


def _live_agent_net(ticker: str, side: str) -> int:
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN action='buy' THEN count ELSE -count END), 0) "
            "FROM mcp_orders WHERE ok=1 AND mode='live' AND ticker=? AND side=?",
            (ticker, side)).fetchone()
    return max(0, int(row[0] or 0))


def _live_agent_tickers() -> set[str]:
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT ticker FROM mcp_orders "
            "WHERE ok=1 AND mode='live' AND action='buy'").fetchall()
    return {r[0] for r in rows}


def _live_agent_order_ids() -> set[str]:
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT order_id FROM mcp_orders WHERE ok=1 AND mode='live' "
            "AND order_id IS NOT NULL").fetchall()
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


def edge_cents(fair_yes_c: float, side: str, price_c: float, count: int) -> float:
    import terminal
    p_side = fair_yes_c if side == "yes" else 100.0 - fair_yes_c
    fee_c = terminal._fee_usd(price_c, max(1, count)) / max(1, count) * 100.0
    return round(p_side - price_c - fee_c, 2)


_hits: list[float] = []


def _rate_ok() -> bool:
    now = time.monotonic()
    _hits[:] = [t for t in _hits if now - t < RATE_WINDOW]
    _hits.append(now)
    return len(_hits) <= RATE_MAX


class ToolError(Exception):
    pass


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


async def t_status(_args: dict, _ctx: dict) -> dict:
    cfg = HOOKS.get_cfg()
    mode = trade_mode(cfg)
    rails = _rails(cfg)
    out: dict = {
        "tradeMode": mode,
        "kalshiEnvironment": kalshi_auth.get_env(),
        "kalshiCredentialsVerified": HOOKS.is_authed(),
        "rails": {**rails, "spentTodayUsd": round(spent_today(mode), 2) if mode != "off" else None,
                  "lossTodayUsd": (await day_loss(mode))["lossUsd"] if mode != "off" else None},
        "notes": [],
    }
    if mode == "off":
        out["notes"].append("Trading is OFF for agents. You can read markets and "
                            "record forecasts; the user enables paper or live in the app.")
    elif mode == "paper":
        pf = paper_book.portfolio(float(cfg.get("mcp_paper_bankroll_usd") or 1000.0))
        out["paper"] = {"cashUsd": pf["cashUsd"], "bankrollUsd": pf["bankrollUsd"],
                        "realizedUsd": pf["realizedUsd"],
                        "openPositions": len(pf["positions"])}
        out["notes"].append("PAPER mode: orders fill against the real order book "
                            "with imaginary money, immediate-or-cancel.")
    else:
        out["notes"].append(f"LIVE mode on the {kalshi_auth.get_env()} environment: "
                            f"orders spend the user's real Kalshi balance.")
    return out


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


async def t_portfolio(_args: dict, _ctx: dict) -> dict:
    cfg = HOOKS.get_cfg()
    mode = trade_mode(cfg)
    if mode == "paper":
        import kalshi_api
        import terminal
        tickers = paper_book.open_tickers()
        marks: dict = {}
        if tickers:
            try:
                found = await terminal._public_gate.run(
                    kalshi_api.fetch_markets_by_tickers, tickers) or {}
                marks = {t: terminal.market_row(m) for t, m in found.items()}
            except Exception as e:
                logger.debug("paper marks failed: %s", e)
        pf = paper_book.portfolio(float(cfg.get("mcp_paper_bankroll_usd") or 1000.0), marks)
        pf["fills"] = pf["fills"][:20]
        return {"mode": "paper", **pf}
    if mode == "live":
        import terminal
        pf = await terminal.portfolio(HOOKS.is_authed())
        mine = _live_agent_tickers()
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
    model = _s(args, "model") or ctx.get("client") or ""
    fid = forecast_ledger.record(
        ticker=ticker, prob_yes=fv / 100.0, source="mcp", model=model,
        market=m, rationale=rationale, env=kalshi_auth.get_env())

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
        "minEdgeCents": _rails(HOOKS.get_cfg())["minEdgeCents"],
        "validForMin": FORECAST_TTL_SEC // 60,
        "note": ("Scored against the market mid at this moment once the market "
                 "settles. A null side means nobody is offering it."),
    }


async def t_scoreboard(_args: dict, _ctx: dict) -> dict:
    sb = forecast_ledger.scoreboard(recent=15)
    return {k: sb[k] for k in ("totalForecasts", "pending", "resolved",
                                "scoredMarkets", "minScored", "overall",
                                "bySource", "buckets", "recent")}


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


async def vet(args: dict, cfg: dict, mode: str, forecast_grace: float = 0.0) -> Vetted:
    import terminal
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
    rails = _rails(cfg)

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
            elif age is None or age > FORECAST_TTL_SEC + forecast_grace:
                v.blockers.append(f"Forecast {fid} is older than "
                                  f"{FORECAST_TTL_SEC // 60} minutes. Re-read the "
                                  f"market and record a new one.")
            else:
                v.edge = edge_cents(float(f["prob_yes"]) * 100.0, side, px, count)
                if v.edge < rails["minEdgeCents"]:
                    v.blockers.append(
                        f"Your forecast ({float(f['prob_yes']) * 100:g}c YES) gives "
                        f"{v.edge:+.2f}c per contract on {side.upper()} at {px:g}c "
                        f"after fees; the minimum is {rails['minEdgeCents']:g}c. "
                        f"No trade.")
        if v.cost > rails["maxOrderUsd"]:
            v.blockers.append(f"${v.cost:,.2f} (fees included) is over the agent "
                              f"per-order cap of ${rails['maxOrderUsd']:,.2f}.")
        spent = spent_today(mode)
        if spent + v.cost > rails["dailySpendUsd"]:
            v.blockers.append(f"Would bring today's agent spend to "
                              f"${spent + v.cost:,.2f}, over the daily cap of "
                              f"${rails['dailySpendUsd']:,.2f}.")
        if mode == "paper":
            held_tickers = set(paper_book.open_tickers())
            pf = paper_book.portfolio(float(cfg.get("mcp_paper_bankroll_usd") or 1000.0))
            if pf["cashUsd"] < v.cost:
                v.blockers.append(f"Paper cash ${pf['cashUsd']:,.2f} is less than "
                                  f"${v.cost:,.2f}.")
        else:
            held_tickers = await _live_agent_held_tickers()
        if ticker not in held_tickers and len(held_tickers) >= rails["maxOpenPositions"]:
            v.blockers.append(f"The agent already holds {len(held_tickers)} positions "
                              f"(cap {rails['maxOpenPositions']}).")
        dl = await day_loss(mode)
        if dl["lossUsd"] >= rails["dailyLossUsd"]:
            v.blockers.append(
                f"Daily loss stop: the agent is down ${dl['lossUsd']:,.2f} today (UTC) "
                f"in {mode}, at or over the ${rails['dailyLossUsd']:,.2f} limit. No new "
                f"buys until tomorrow; selling to exit is still allowed.")
    else:
        v.cost = round(gross - v.fee, 2)
        if mode == "paper":
            have = paper_book.held(ticker, side)
            if count > have:
                v.blockers.append(f"The paper book holds {have} {side.upper()} on "
                                  f"{ticker}; cannot sell {count}.")
        else:
            net = _live_agent_net(ticker, side)
            if count > net:
                v.blockers.append(
                    f"The agent has opened {net} {side.upper()} on {ticker} live; "
                    f"it can only sell what it opened. The rest is the user's.")

    if mode == "live":
        if not HOOKS.is_authed():
            v.blockers.append(f"No verified Kalshi credentials for "
                              f"{kalshi_auth.get_env()}.")
        if v.book and v.book.get("stale"):
            v.warnings.append("The order book is a REST snapshot, not the live feed.")
    return v


async def _live_agent_held_tickers() -> set[str]:
    import terminal
    mine = _live_agent_tickers()
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


async def t_preview(args: dict, _ctx: dict) -> dict:
    cfg = HOOKS.get_cfg()
    mode = trade_mode(cfg)
    v = await vet(args, cfg, mode)
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
    mode = trade_mode(cfg)
    client = ctx.get("client") or ""
    v = await vet(args, cfg, mode)
    req = v.req
    if v.blockers:
        _audit(mode=mode, client=client, req=req, ok=False,
               message=v.blockers[0], forecast_id=v.forecast_id)
        raise ToolError("Refused:\n- " + "\n- ".join(v.blockers))

    if mode == "paper":
        fill = paper_book.simulate_fill(v.book, req["side"], req["action"],
                                        req["count"], req["priceCents"])
        if not fill["filled"]:
            _audit(mode=mode, client=client, req=req, ok=False,
                   message=fill["note"] or "nothing filled", forecast_id=v.forecast_id)
            raise ToolError(fill["note"] or "Nothing filled.")
        import terminal
        avg = fill["avgPriceCents"]
        fee = terminal._fee_usd(avg, fill["filled"])
        paper_book.record_fill(
            ticker=req["ticker"], title=(v.market or {}).get("title") or "",
            side=req["side"], action=req["action"], contracts=fill["filled"],
            price_cents=avg, fee_usd=fee, forecast_id=v.forecast_id,
            client=client, env=kalshi_auth.get_env())
        spend = round(fill["filled"] * avg / 100.0 + fee, 4) if req["action"] == "buy" else None
        msg = (f"PAPER {req['action']} {fill['filled']} {req['side'].upper()} "
               f"{req['ticker']} @ {avg:g}c avg, fee ${fee:.2f}")
        _audit(mode=mode, client=client, req=req, ok=True, message=msg,
               forecast_id=v.forecast_id, committed=spend,
               filled=fill["filled"], avg=avg)
        await _announce(mode, msg)
        return {"mode": "paper", "ok": True, "message": msg,
                "filled": fill["filled"], "avgFillCents": avg, "feeUsd": fee,
                "note": fill["note"]}

    if cfg.get("mcp_live_approval", True):
        oid = _audit(mode=mode, client=client, req=req, ok=False,
                     message="waiting for the user's approval",
                     forecast_id=v.forecast_id,
                     committed=v.cost if req["action"] == "buy" else None,
                     status="pending")
        msg = (f"wants to {req['action'].upper()} {req['count']} "
               f"{req['side'].upper()} {req['ticker']} @ {req['priceCents']:g}c "
               f"(${v.cost:,.2f}) — approval #{oid}")
        logger.info("[mcp] %s", msg)
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
        return {"mode": "live", "ok": True, "pending": True, "approvalId": oid,
                "message": ("Queued for the user's approval. Nothing has been sent. "
                            f"Check with get_order_status; it expires in "
                            f"{APPROVAL_TTL_SEC // 60} minutes.")}
    return await _execute_live(v, mode, client)


async def _execute_live(v: Vetted, mode: str, client: str,
                        row_id: Optional[int] = None) -> dict:
    req = v.req
    if HOOKS.submit is None:
        raise ToolError("Live trading is not wired in this build.")
    res = await HOOKS.submit(dict(req))
    ok = bool(res.get("ok"))
    committed = v.cost if (ok and req["action"] == "buy") else None
    if row_id is None:
        _audit(mode=mode, client=client, req=req, ok=ok,
               message=str(res.get("message") or ""), forecast_id=v.forecast_id,
               committed=committed, order_id=res.get("orderId"),
               filled=res.get("filledContracts"), avg=res.get("avgFillCents"))
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
           f"{req['ticker']} @ {req['priceCents']:g}c — {res.get('message')}")
    await _announce(mode, msg)
    return {"mode": "live", "ok": True, "orderId": res.get("orderId"),
            "status": res.get("status"), "filled": res.get("filledContracts"),
            "avgFillCents": res.get("avgFillCents"), "feesUsd": res.get("feesUsd"),
            "message": res.get("message")}


async def decide(row_id: int, approve: bool, via: str = "app") -> dict:
    with db.get_db() as conn:
        r = conn.execute("SELECT * FROM mcp_orders WHERE id=?", (int(row_id),)).fetchone()
        if r is None or r["status"] != "pending":
            return {"ok": False, "message": f"No pending agent order #{row_id}."}
        if _effective_status(r) == "expired":
            conn.execute("UPDATE mcp_orders SET status='expired' WHERE id=?", (row_id,))
            return {"ok": False, "message": f"Agent order #{row_id} expired; nothing was sent."}
        if not approve:
            conn.execute("UPDATE mcp_orders SET status='rejected', message=? WHERE id=?",
                         (f"rejected by the user ({via})", row_id))
            logger.info("[mcp] approval #%s rejected via %s", row_id, via)
            return {"ok": True, "message": f"Rejected agent order #{row_id}."}
        conn.execute("UPDATE mcp_orders SET status='deciding' WHERE id=?", (row_id,))
    cfg = HOOKS.get_cfg()
    mode = trade_mode(cfg)
    args = {"ticker": r["ticker"], "side": r["side"], "action": r["action"],
            "count": r["count"], "price_cents": r["price_cents"],
            "forecast_id": r["forecast_id"]}
    v = None
    if mode != "live":
        blockers = [f"agent trading is now {mode}, not live"]
    else:
        v = await vet(args, cfg, mode, forecast_grace=APPROVAL_TTL_SEC)
        blockers = v.blockers
    if blockers or v is None:
        with db.get_db() as conn:
            conn.execute("UPDATE mcp_orders SET status='failed', message=? WHERE id=?",
                         ("approved, but refused on re-check: " + blockers[0], row_id))
        return {"ok": False, "message": "Approved, but it no longer passes: " + blockers[0]}
    try:
        res = await _execute_live(v, mode, r["client"] or "", row_id=int(row_id))
    except ToolError as e:
        return {"ok": False, "message": str(e)}
    logger.info("[mcp] approval #%s approved via %s", row_id, via)
    return {"ok": True, "message": f"Approved #{row_id}: {res.get('message')}"}


async def t_order_status(args: dict, _ctx: dict) -> dict:
    try:
        rid = int(args.get("approval_id"))
    except (TypeError, ValueError):
        raise ToolError("approval_id must be the number place_order returned")
    with db.get_db() as conn:
        r = conn.execute("SELECT * FROM mcp_orders WHERE id=?", (rid,)).fetchone()
    if r is None:
        raise ToolError(f"No agent order #{rid}.")
    return {"approvalId": rid,
            "status": _effective_status(r) or ("sent" if r["ok"] else "refused"),
            "orderId": r["order_id"], "filled": r["filled"],
            "avgFillCents": r["avg_fill_cents"], "message": r["message"]}


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


async def t_orders(_args: dict, _ctx: dict) -> dict:
    cfg = HOOKS.get_cfg()
    if trade_mode(cfg) != "live":
        return {"orders": [], "note": "Paper orders never rest — they fill or are dropped."}
    import terminal
    mine = _live_agent_order_ids()
    res = await terminal.resting_orders(HOOKS.is_authed())
    return {"orders": [o for o in res.get("orders") or [] if o.get("orderId") in mine],
            "note": "Only orders this agent placed are shown."}


async def t_cancel(args: dict, ctx: dict) -> dict:
    cfg = HOOKS.get_cfg()
    if trade_mode(cfg) != "live":
        raise ToolError("Nothing to cancel: paper orders never rest.")
    oid = _s(args, "order_id")
    if oid not in _live_agent_order_ids():
        raise ToolError("That order was not placed by an agent; it is the user's.")
    if HOOKS.cancel is None:
        raise ToolError("Cancel is not wired in this build.")
    res = await HOOKS.cancel(oid)
    logger.info("[mcp] cancel %s by %s -> %s", oid, ctx.get("client"), res.get("message"))
    return {"ok": bool(res.get("ok")), "message": res.get("message")}


TOOLS: list[Tool] = [
    Tool("get_status", "Status and rails",
         "Trading mode (off/paper/live), Kalshi environment, the agent's money "
         "caps and today's spend. Call this first.",
         _obj({}), t_status),
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
         "by the minimum edge after fees. Paper orders are immediate-or-cancel "
         "against the real book.",
         _obj({"ticker": _TICKER, "side": _SIDE, "action": _ACTION,
               "count": _COUNT, "price_cents": _PRICE,
               "forecast_id": {"type": "integer"}},
              ("ticker", "side", "action", "count", "price_cents")),
         t_place, perm="trade", read_only=False, destructive=True),
    Tool("get_order_status", "Order / approval status",
         "Status of an order place_order queued for the user's approval: "
         "pending, approved, rejected, expired or failed.",
         _obj({"approval_id": {"type": "integer"}}, ("approval_id",)),
         t_order_status, perm="trade"),
    Tool("list_orders", "Resting orders",
         "Live resting orders this agent placed.",
         _obj({}), t_orders, perm="trade"),
    Tool("cancel_order", "Cancel an order",
         "Cancel a live resting order this agent placed.",
         _obj({"order_id": {"type": "string"}}, ("order_id",)),
         t_cancel, perm="trade", read_only=False),
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
1. get_status — see the mode (off / paper / live) and your caps.
2. discover_markets / search_markets, then get_market. Read the resolution rules.
3. record_forecast with your honest fair value and reasoning. It returns your \
edge on each side AFTER Kalshi's fee.
4. Only if the edge clears the minimum: place_order with that forecast_id.

Most markets should end at step 3 with no trade: a liquid market's price is a \
strong forecast, and fees eat small edges. Every forecast is scored against the \
market once it settles (get_scoreboard). Paper fills are real-book, \
imaginary-money, immediate-or-cancel. Never invent a number you could not justify."""


def _ok(mid: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _rpc_err(mid: Any, code: int, msg: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": msg}}


async def call_tool(name: str, args: dict, ctx: dict) -> dict:
    tool = _BY_NAME.get(name)
    cfg = HOOKS.get_cfg()
    if tool is None or not allowed(tool, cfg):
        return {"content": [{"type": "text", "text": f"Unknown or disabled tool: {name}"}],
                "isError": True}
    if not _rate_ok():
        return {"content": [{"type": "text", "text": (
            f"Rate limit: more than {RATE_MAX} calls in a minute. Slow down; "
            f"nothing was executed.")}], "isError": True}
    STATUS.calls += 1
    STATUS.last_call_at = _now()
    STATUS.last_tool = name
    try:
        res = await tool.handler(args if isinstance(args, dict) else {}, ctx)
    except ToolError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    except Exception as e:
        logger.warning("[mcp] tool %s failed: %s: %s", name, type(e).__name__, e)
        return {"content": [{"type": "text", "text": f"{name} failed: {type(e).__name__}: {e}"}],
                "isError": True}
    text = res if isinstance(res, str) else json.dumps(res, default=str, indent=1)
    return {"content": [{"type": "text", "text": text}], "isError": False}


async def handle_message(msg: Any, ctx: dict) -> Optional[dict]:
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
        return _ok(mid, {
            "protocolVersion": ver,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "title": "Krypt Trader",
                           "version": HOOKS.version or "0"},
            "instructions": INSTRUCTIONS,
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


STATUS = _Status()
_server: Optional[asyncio.AbstractServer] = None
_REASONS = {200: "OK", 202: "Accepted", 400: "Bad Request", 401: "Unauthorized",
            403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
            411: "Length Required", 413: "Payload Too Large",
            431: "Request Header Fields Too Large", 500: "Internal Server Error"}


def check_request(method: str, path: str, headers: dict, port: int,
                  token: Optional[str]) -> Optional[tuple[int, str]]:
    if path.split("?", 1)[0] != "/mcp":
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
    if not supplied or not secrets.compare_digest(supplied, token):
        return 401, "bad or missing bearer token"
    if method != "POST":
        return 405, "POST only"
    return None


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

            refusal = check_request(method, path, headers, port, get_token())
            if refusal:
                code, why = refusal
                extra = {"WWW-Authenticate": "Bearer"} if code == 401 else (
                    {"Allow": "POST"} if code == 405 else None)
                await _respond(writer, code, _json_body({"error": why}), extra, close=close)
                if close:
                    return
                continue

            sid = headers.get("mcp-session-id") or ""
            ctx = {"client": STATUS.clients.get(sid, "")}
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
        "clients": sorted(set(STATUS.clients.values())),
        "spentTodayUsd": round(spent_today(trade_mode(cfg)), 2),
        "rails": _rails(cfg),
        "permissions": {k: bool(cfg.get(k)) for k in PERMISSIONS},
        "liveApproval": bool(cfg.get("mcp_live_approval", True)),
        "pending": pending(),
        "toolCount": len(visible_tools(cfg)),
    }


CLIENTS = ("cursor", "claude-code", "claude-desktop", "codex")


def bridge_command() -> tuple[str, list[str]]:
    if getattr(sys, "frozen", False):
        return sys.executable, ["--mcp-stdio"]
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "service.py")
    return sys.executable, [here, "--mcp-stdio"]


def client_config(client: str, port: int, token: str) -> str:
    url = f"http://{_LOOPBACK}:{port}/mcp"
    if client == "cursor":
        return json.dumps({"mcpServers": {SERVER_NAME: {
            "url": url, "headers": {"Authorization": f"Bearer {token}"}}}}, indent=2)
    if client == "claude-code":
        return (f'claude mcp add --scope user --transport http {SERVER_NAME} {url} '
                f'--header "Authorization: Bearer {token}"')
    if client == "codex":
        return (f"[mcp_servers.{SERVER_NAME}]\n"
                f"url = '{url}'\n"
                f"http_headers = {{ Authorization = 'Bearer {token}' }}\n")
    cmd, args = bridge_command()
    args = args + ["--port", str(port)]
    if client == "claude-desktop":
        return json.dumps({"mcpServers": {SERVER_NAME: {
            "command": cmd, "args": args, "env": {"KRYPT_MCP_TOKEN": token}}}}, indent=2)
    raise ValueError(f"client must be one of {CLIENTS}")
