from __future__ import annotations

import logging
import secrets
import string
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("remote")

PAIR_CODE_LEN = 6
PAIR_CODE_TTL = 600.0

CONFIRM_TTL = 120.0

RATE_WINDOW = 60.0
RATE_MAX = 30

READ_COMMANDS = ("help", "status", "balance", "positions", "orders", "quote",
                 "rules", "history", "agents")
TRADE_COMMANDS = ("buy", "sell", "cancel", "confirm", "approve", "reject")


@dataclass
class Pending:
    code: str
    req: dict
    summary: str
    created: float = field(default_factory=time.monotonic)

    def expired(self) -> bool:
        return time.monotonic() - self.created > CONFIRM_TTL


@dataclass
class RemoteState:
    telegram_code: Optional[str] = None
    telegram_code_at: float = 0.0
    pending: dict[str, Pending] = field(default_factory=dict)
    hits: dict[str, list] = field(default_factory=dict)


STATE = RemoteState()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S UTC")


def new_pair_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    alphabet = "".join(c for c in alphabet if c not in "O0I1")
    STATE.telegram_code = "".join(secrets.choice(alphabet) for _ in range(PAIR_CODE_LEN))
    STATE.telegram_code_at = time.monotonic()
    return STATE.telegram_code


def pair_code_valid() -> Optional[str]:
    if not STATE.telegram_code:
        return None
    if time.monotonic() - STATE.telegram_code_at > PAIR_CODE_TTL:
        return None
    return STATE.telegram_code


def check_pair_code(supplied: str) -> bool:
    live = pair_code_valid()
    if not live:
        return False
    ok = secrets.compare_digest(live.upper(), (supplied or "").strip().upper())
    if ok:
        STATE.telegram_code = None
    return ok


def rate_ok(sender: str) -> bool:
    now = time.monotonic()
    hits = [t for t in STATE.hits.get(sender, []) if now - t < RATE_WINDOW]
    hits.append(now)
    STATE.hits[sender] = hits
    if len(STATE.hits) > 200:
        STATE.hits.clear()
    return len(hits) <= RATE_MAX


def _cents(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:g}c"


def _usd(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"${v:,.2f}"


HELP = """Krypt Terminal — remote

Reading:
  status          engine, environment, connection
  balance         cash and portfolio value
  positions       what you hold
  orders          resting orders
  quote TICKER    live bid/ask and the resolution-risk score
  rules           armed stop losses, take profits and alerts
  history         your last hand-placed trades
  agents          AI agent orders waiting for your approval

Trading (only if you switched it on in the app):
  buy TICKER yes|no COUNT PRICE
  sell TICKER yes|no COUNT PRICE
  cancel ORDER_ID
  confirm CODE    the second step every order needs
  approve N       send AI agent order #N (re-checked first)
  reject N        refuse AI agent order #N

Prices are in cents, 1-99. Nothing trades without a confirm."""


async def handle(text: str, sender: str, *, cfg: dict, authed: bool,
                 trading_enabled: bool) -> str:
    raw = (text or "").strip()
    if not raw:
        return HELP
    if not rate_ok(sender):
        return ("Too many messages in a minute — ignoring the rest of this "
                "burst. Nothing was executed.")

    parts = raw.split()
    cmd = parts[0].lstrip("/").lower()
    args = parts[1:]

    if cmd in ("help", "start", "commands"):
        return HELP

    if cmd in TRADE_COMMANDS and not trading_enabled:
        return ("Remote trading is switched OFF. Turn it on in the app under "
                "Remote if you want to trade from here — reading is separate "
                "from spending, on purpose.")

    try:
        if cmd == "status":
            return await _status(authed, trading_enabled)
        if cmd == "balance":
            return await _balance(authed)
        if cmd == "positions":
            return await _positions(authed)
        if cmd == "orders":
            return await _orders(authed)
        if cmd == "quote":
            return await _quote(args)
        if cmd == "rules":
            return await _rules()
        if cmd == "history":
            return await _history()
        if cmd in ("buy", "sell"):
            return await _stage_order(cmd, args, sender, cfg=cfg, authed=authed)
        if cmd == "confirm":
            return await _confirm(args, sender, cfg=cfg, authed=authed)
        if cmd == "cancel":
            return await _cancel(args, authed)
        if cmd == "agents":
            return _agents()
        if cmd in ("approve", "reject"):
            return await _agent_decide(cmd, args)
    except Exception as e:
        logger.warning("remote command %r failed: %s", cmd, e)
        return f"That failed: {e}"

    return f"Unknown command {cmd!r}. Send 'help' for the list."


async def _status(authed: bool, trading_enabled: bool) -> str:
    import kalshi_auth
    import kalshi_ws
    import terminal
    env = kalshi_auth.get_env()
    ws = kalshi_ws.stats()
    lines = [
        f"Environment: {env}",
        f"Credentials: {'verified' if authed else 'MISSING'}",
        f"Remote trading: {'ON' if trading_enabled else 'off'}",
        f"Websocket: {'connected' if ws.get('connected') else 'off'}",
        f"Watching: {len(terminal.subscribed_tickers())} market(s)",
        f"As of {_now()}",
    ]
    return "\n".join(lines)


async def _balance(authed: bool) -> str:
    import terminal
    pf = await terminal.portfolio(authed)
    if not authed:
        return pf["note"] or "No verified credentials."
    lines = [
        f"Cash: {_usd(pf['cashUsd'])}",
        f"Cost basis: {_usd(pf['totalCostBasisUsd'])}",
        f"Market value: {_usd(pf['totalMarketValueUsd'])}",
        f"Unrealised: {_usd(pf['totalUnrealizedUsd'])}",
        f"Environment: {pf['env']}",
    ]
    if pf["unreconciledCount"]:
        lines.append(
            f"NOTE: {pf['unreconciledCount']} position(s) have no readable cost "
            f"basis and are excluded from those totals.")
    return "\n".join(lines)


async def _positions(authed: bool) -> str:
    import terminal
    pf = await terminal.portfolio(authed)
    rows = pf["positions"]
    if not rows:
        return pf["note"] or "No open positions."
    out = []
    for p in rows[:20]:
        out.append(
            f"{p['ticker']}\n"
            f"  {p['side'].upper()} {p['contracts']} @ {_cents(p['avgCostCents'])} "
            f"avg | mark {_cents(p['markCents'])} | "
            f"unreal {_usd(p['unrealizedUsd'])}"
        )
    if len(rows) > 20:
        out.append(f"…and {len(rows) - 20} more.")
    return "\n".join(out)


async def _orders(authed: bool) -> str:
    import terminal
    res = await terminal.resting_orders(authed)
    rows = res["orders"]
    if not rows:
        return res.get("note") or "Nothing resting."
    out = [f"{o['orderId']}\n  {o['action'] or '--'} {o['remaining'] or o['count']} "
           f"{(o['side'] or '--').upper()} {o['ticker']} @ {_cents(o['priceCents'])}"
           for o in rows[:20]]
    out.append("Cancel one with: cancel ORDER_ID")
    return "\n".join(out)


async def _quote(args: list[str]) -> str:
    import terminal
    if not args:
        return "Usage: quote TICKER"
    ticker = args[0].strip().upper()
    detail = await terminal.market_detail(ticker, authed=False)
    m = detail["market"]
    risk = detail["risk"]
    lines = [
        m["title"][:120],
        f"{ticker}",
        f"YES bid {_cents(m['yesBid'])} / ask {_cents(m['yesAsk'])}"
        + (f"  (spread {_cents(m['spreadCents'])})" if m["spreadCents"] is not None else ""),
        f"Last {_cents(m['lastPrice'])} | volume {m['volume'] if m['volume'] is not None else '—'}",
    ]
    mins = m["minutesToClose"]
    if mins is not None:
        lines.append(f"Closes in {mins / 60:.1f}h" if mins > 90 else f"Closes in {mins:.0f}m")
    lines.append(
        f"Resolution risk: {risk['score'] if risk['score'] is not None else '—'}"
        f" ({risk['resolvedCount']}/{risk['totalCount']} checks resolved)")
    return "\n".join(lines)


async def _rules() -> str:
    import terminal
    res = await __import__("asyncio").to_thread(terminal.list_rules, 100)
    rows = [r for r in res["rules"] if r["status"] == "armed"]
    if not rows:
        return "No armed instructions."
    out = []
    for r in rows[:20]:
        seen = _cents(r["lastPriceCents"])
        out.append(
            f"{r['kind']} {r['ticker']} {r['side'].upper()} "
            f"{'<=' if r['direction'] == 'below' else '>='} "
            f"{_cents(r['thresholdCents'])} | last seen {seen}"
        )
    return "\n".join(out)


async def _history() -> str:
    import asyncio
    import terminal
    h = await asyncio.to_thread(terminal.manual_history, 40)
    closed = [t for t in h["trades"] if t["resolved"]]
    if not closed:
        return "No settled hand-placed trades yet."
    rate = h["winRate"]
    rate_txt = "—" if rate is None else f"{rate * 100:.0f}%"
    lines = [
        f"Settled: {h['closedCount']} | hit rate {rate_txt} | "
        f"realised {_usd(h['realizedUsd'])}",
    ]
    for t in closed[:10]:
        lines.append(
            f"  {t['ticker']} {t['side'].upper()} {t['contracts']} @ "
            f"{_cents(t['avgCostCents'])} -> {_usd(t['pnlUsd'])}")
    return "\n".join(lines)


def _order_code() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(4))


async def _stage_order(action: str, args: list[str], sender: str, *,
                       cfg: dict, authed: bool) -> str:
    import terminal
    if len(args) < 4:
        return (f"Usage: {action} TICKER yes|no COUNT PRICE\n"
                f"e.g. {action} KXBTCD-26AUG24-T90000 yes 10 45")
    ticker = args[0].strip().upper()
    side = args[1].strip().lower()
    if side not in ("yes", "no"):
        return "Side must be yes or no."
    try:
        count = int(args[2])
        price = float(args[3])
    except ValueError:
        return "COUNT must be a whole number and PRICE a number in cents (1-99)."

    req = {"ticker": ticker, "side": side, "action": action,
           "count": count, "priceCents": price}

    market = book = position = None
    try:
        raw = await terminal._public_gate.run(
            __import__("kalshi_api").fetch_market, ticker)
        market = terminal._apply_live_quote(terminal.market_row(raw)) if raw else None
    except Exception:
        pass
    try:
        book = await terminal.book(ticker)
    except Exception:
        pass
    if authed:
        try:
            pf = await terminal.portfolio(True)
            position = next((p for p in pf["positions"] if p["ticker"] == ticker), None)
        except Exception:
            pass

    ex_status = None
    try:
        ex_status = await terminal._public_gate.run(
            __import__("kalshi_api").fetch_exchange_status)
    except Exception:
        pass

    pv = terminal.preview(req, cfg=cfg, authed=authed, market=market,
                          book_snapshot=book, position=position,
                          exchange_status=ex_status)
    if pv["blockers"]:
        return "Cannot place that:\n" + "\n".join(f"  - {b}" for b in pv["blockers"])

    code = _order_code()
    summary_lines = [
        f"{action.upper()} {count} {side.upper()} @ {price:g}c",
        (market or {}).get("title", ticker)[:100],
        ticker,
        f"{'Cost' if action == 'buy' else 'Proceeds'}: {_usd(pv['costUsd'])}"
        f" | fee {_usd(pv['feeUsd'])} | "
        f"{'total out' if action == 'buy' else 'net in'} {_usd(pv['totalUsd'])}",
    ]
    if pv["breakevenProb"] is not None:
        summary_lines.append(f"Breakeven: {pv['breakevenProb'] * 100:.1f}%")
    for w in pv["warnings"]:
        summary_lines.append(f"! {w}")
    summary = "\n".join(summary_lines)

    STATE.pending[sender] = Pending(code=code, req=req, summary=summary)
    return (summary + f"\n\nReply:  confirm {code}\n"
            f"(expires in {int(CONFIRM_TTL // 60)} minutes; nothing has been sent)")


async def _confirm(args: list[str], sender: str, *, cfg: dict, authed: bool) -> str:
    import terminal
    pending = STATE.pending.get(sender)
    if not pending:
        return "Nothing waiting to confirm."
    if pending.expired():
        STATE.pending.pop(sender, None)
        return ("That order expired — the market may have moved. Send it again "
                "if you still want it.")
    if not args:
        return f"Reply: confirm {pending.code}"
    if not secrets.compare_digest(args[0].strip(), pending.code):
        return "That code does not match the order waiting. Check and resend."

    STATE.pending.pop(sender, None)
    res = await terminal.submit(pending.req, cfg=cfg, authed=authed)
    logger.info("[remote] %s -> %s", pending.req, res.get("message"))
    return ("Sent.\n" + res["message"]) if res["ok"] else ("Rejected.\n" + res["message"])


async def _cancel(args: list[str], authed: bool) -> str:
    import terminal
    if not args:
        return "Usage: cancel ORDER_ID  (see: orders)"
    oid = args[0].strip()
    res = await terminal.cancel(oid, authed=authed)
    return res["message"]


def _agents() -> str:
    import mcp_server
    rows = mcp_server.pending()
    if not rows:
        return "No agent orders waiting."
    out = [f"#{r['id']} {r['action']} {r['count']} {r['side'].upper()} {r['ticker']} "
           f"@ {_cents(r['priceCents'])}  ({_usd(r['committedUsd'])})" for r in rows[:10]]
    out.append("Reply: approve N  or  reject N")
    return "\n".join(out)


async def _agent_decide(cmd: str, args: list[str]) -> str:
    import mcp_server
    try:
        rid = int((args or [""])[0].lstrip("#"))
    except ValueError:
        return f"Usage: {cmd} N   (see: agents)"
    res = await mcp_server.decide(rid, cmd == "approve", via="phone")
    return res["message"]


def format_rule_event(data: dict) -> str:
    rule = data.get("rule") or {}
    return (f"[{rule.get('kind', 'rule').upper()}] {data.get('message', '')}\n"
            f"{rule.get('ticker', '')}")
