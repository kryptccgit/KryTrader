"""The paper account's exchange: Kalshi's portfolio API, answered locally.

In Paper mode kalshi_api's account functions (place/cancel/get order, fills,
positions, balance) route here instead of signing a request. Every engine that
trades the account — the auto-trader, the terminal ticket, phone orders,
standing rules — therefore runs its REAL code path against paper, and none of
them needed a paper branch of its own. The responses are Kalshi-shaped
(fixed-point `_fp` / `_dollars` fields), because those engines parse exactly
that shape and a second shape would be a second set of parsers to get wrong.

How a paper order behaves, and why:

  * Prices are production's. The book is read from Kalshi's PUBLIC order-book
    endpoint, unsigned — which is also why Paper needs no Kalshi account.
  * The part of an order that crosses the book when it is placed fills at once,
    walking the visible levels (paper_book.simulate_fill) at their prices, with
    Kalshi's taker fee.
  * The remainder RESTS, like a real limit order, and fills only when the real
    book later crosses its limit — never on a print at its price, because where
    it would have stood in the queue is unknowable. A resting fill is booked at
    the order's own limit and still charged the taker fee formula: the
    conservative choice, so paper P&L never flatters the strategy. And since
    a paper fill does not deplete the real book, liquidity an order already
    took (or saw when placed) never fills it again: only depth beyond what it
    last saw crossing its limit is new.
  * A sell is refused beyond what the account holds (net of resting sells).
    Real Kalshi would open the other side instead; on paper that would be a
    position nobody asked for.
  * A buy is refused beyond the cash not already promised to resting buys.
  * Holding both sides of one market nets, as on Kalshi: each matched pair is
    redeemed for $1.00 on the spot.
  * Resting orders on a market that has closed are cancelled; positions settle
    at the real outcome (paper_book.settle_pending).

The ledger is paper_book's (owner 'account'), and so is the one bankroll.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import db
import paper_book

logger = logging.getLogger("paper_exchange")

ACCOUNT = paper_book.ACCOUNT_AGENT
DEFAULT_BANKROLL_USD = 1000.0
_CLOSED_STATUSES = {"closed", "settled", "finalized", "determined"}

_bankroll_usd: float = DEFAULT_BANKROLL_USD
_configured = False
_lock = asyncio.Lock()
_last_applied: dict[str, float] = {}
_consumed: dict[tuple[str, str, float], int] = {}


def set_bankroll(usd: float) -> None:
    """The configured starting balance (`paper_bankroll_usd`): what the book
    starts from the first time, and what each Reset puts it back to. It does
    not move the cash of a book already running (paper_book.effective_bankroll)."""
    global _bankroll_usd, _configured
    try:
        v = float(usd)
    except (TypeError, ValueError):
        return
    if v > 0:
        _bankroll_usd = v
        _configured = True


def bankroll() -> float:
    """The starting balance IN EFFECT for the current paper book."""
    return paper_book.effective_bankroll(_bankroll_usd, _configured)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _iso(s: Optional[str]) -> Optional[str]:
    return (str(s) + "Z") if s and not str(s).endswith("Z") else s


def _err(status: int, code: str, message: str):
    import kalshi_api
    return kalshi_api.KalshiAPIError(status, {"error": {"code": code, "message": message}})


def _fee_usd(price_cents: float, contracts: int) -> float:
    import terminal
    return terminal._fee_usd(price_cents, contracts)



async def _book(ticker: str) -> Optional[dict]:
    """Production's order book for `ticker`, in paper_book's level shape, or
    None when it could not be read (never an empty book standing in for an
    unreadable one — an empty book fills nothing, which is a claim)."""
    import kalshi_api
    try:
        raw = await kalshi_api.read_orderbook(ticker)
    except Exception as e:
        logger.debug("paper book read failed for %s: %s", ticker, e)
        return None
    if not isinstance(raw, dict):
        return None
    out: dict = {"yes": [], "no": []}
    for side in ("yes", "no"):
        for lvl in raw.get(side) or []:
            try:
                px, n = float(lvl[0]), int(float(lvl[1]))
            except (TypeError, ValueError, IndexError):
                continue
            if 0 < px < 100 and n >= 1:
                out[side].append({"priceCents": px, "contracts": n})
    return out



def _account_rows(conn, ticker: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM paper_fills WHERE agent_id=?"
    args: list = [ACCOUNT]
    if ticker:
        sql += " AND ticker=?"
        args.append(ticker)
    return [dict(r) for r in conn.execute(sql + " ORDER BY id ASC", args).fetchall()]


def _positions_by_ticker(rows: list[dict]) -> dict[str, dict]:
    """{ticker: {yes:{n,cost,fees}, no:{...}, realized, traded}} replayed from
    the account's fills. Cost EXCLUDES fees (Kalshi's market_exposure does;
    fees are reported beside it), average-cost accounting."""
    out: dict[str, dict] = {}
    for r in rows:
        t = r["ticker"]
        p = out.setdefault(t, {"yes": {"n": 0, "cost": 0.0, "fees": 0.0},
                               "no": {"n": 0, "cost": 0.0, "fees": 0.0},
                               "realized": 0.0, "traded": 0.0})
        s = p[r["side"]]
        n = int(r["contracts"])
        px = float(r["price_cents"])
        fee = float(r["fee_usd"] or 0.0)
        p["traded"] += n * px / 100.0
        if r["kind"] == "buy":
            s["n"] += n
            s["cost"] += n * px / 100.0
            s["fees"] += fee
            continue
        if s["n"] <= 0:
            continue
        n = min(n, s["n"])
        avg = s["cost"] / s["n"]
        p["realized"] += n * px / 100.0 - avg * n - fee
        s["cost"] -= avg * n
        s["n"] -= n
        s["fees"] += fee
    return out


def _held(conn, ticker: str, side: str) -> int:
    return int(_positions_by_ticker(_account_rows(conn, ticker)).get(ticker, {})
               .get(side, {}).get("n") or 0)


def _resting(conn, ticker: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM paper_orders WHERE status='resting'"
    args: list = []
    if ticker:
        sql += " AND ticker=?"
        args.append(ticker)
    return [dict(r) for r in conn.execute(sql + " ORDER BY created_at ASC", args).fetchall()]


def _reserved_buy_usd(conn) -> float:
    """Cash promised to resting buys: their unfilled remainder at the limit,
    plus the fee that remainder would pay."""
    total = 0.0
    for o in _resting(conn):
        if o["action"] != "buy":
            continue
        rem = int(o["count"]) - int(o["filled"])
        if rem > 0:
            total += rem * float(o["limit_cents"]) / 100.0 + _fee_usd(float(o["limit_cents"]), rem)
    return total


def _reserved_sell(conn, ticker: str, side: str) -> int:
    return sum(int(o["count"]) - int(o["filled"]) for o in _resting(conn, ticker)
               if o["action"] == "sell" and o["side"] == side)


def _order(conn, order_id: str) -> Optional[dict]:
    r = conn.execute("SELECT * FROM paper_orders WHERE order_id=?", (order_id,)).fetchone()
    return dict(r) if r else None



def _order_json(o: dict) -> dict:
    limit = float(o["limit_cents"])
    yes_c = limit if o["side"] == "yes" else 100.0 - limit
    count = int(o["count"])
    filled = int(o["filled"])
    remaining = count - filled if o["status"] == "resting" else 0
    return {
        "order_id": o["order_id"],
        "client_order_id": o["client_order_id"],
        "ticker": o["ticker"],
        "side": o["side"],
        "action": o["action"],
        "type": "limit",
        "status": o["status"],
        "yes_price_dollars": f"{yes_c / 100:.4f}",
        "no_price_dollars": f"{(100.0 - yes_c) / 100:.4f}",
        "initial_count_fp": f"{count:.2f}",
        "fill_count_fp": f"{filled:.2f}",
        "remaining_count_fp": f"{remaining:.2f}",
        "taker_fill_cost_dollars": f"{float(o['fill_cost_usd']):.4f}",
        "maker_fill_cost_dollars": "0.0000",
        "taker_fees_dollars": f"{float(o['fees_usd']):.4f}",
        "maker_fees_dollars": "0.0000",
        "created_time": _iso(o["created_at"]),
        "last_update_time": _iso(o["updated_at"]),
        "paper": True,
    }


def _fill_json(r: dict) -> dict:
    px = float(r["price_cents"])
    yes_c = px if r["side"] == "yes" else 100.0 - px
    n = int(r["contracts"])
    try:
        ts = int(datetime.strptime(str(r["created_at"])[:19], "%Y-%m-%dT%H:%M:%S")
                 .replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        ts = None
    return {
        "trade_id": f"paperfill-{r['id']}", "fill_id": f"paperfill-{r['id']}",
        "order_id": r.get("order_id"), "ticker": r["ticker"],
        "side": r["side"], "action": r["kind"],
        "count": n, "count_fp": f"{n:.2f}",
        "yes_price_dollars": f"{yes_c / 100:.4f}",
        "no_price_dollars": f"{(100.0 - yes_c) / 100:.4f}",
        "is_taker": True, "fee_cost": f"{float(r['fee_usd'] or 0):.4f}",
        "created_time": _iso(r["created_at"]), "ts": ts, "paper": True,
    }



def _ladder_of(side: str, action: str) -> str:
    """Which of Kalshi's two BID ladders an order trades against: buying YES
    lifts a mirrored NO bid, selling YES hits a YES bid (paper_book._levels)."""
    if action == "buy":
        return "no" if side == "yes" else "yes"
    return side


def _reconcile_consumed(ticker: str, book: dict) -> None:
    """Bring the taken-depth memory in line with what is on screen now: a
    level that thinned keeps at most its new depth as taken, a level that
    left the book is forgotten."""
    depth: dict[tuple[str, str, float], int] = {}
    for ladder in ("yes", "no"):
        for lvl in book.get(ladder) or []:
            k = (ticker, ladder, float(lvl["priceCents"]))
            depth[k] = depth.get(k, 0) + int(lvl["contracts"])
    for k in [k for k in _consumed if k[0] == ticker]:
        left = min(_consumed[k], depth.get(k, 0))
        if left > 0:
            _consumed[k] = left
        else:
            del _consumed[k]


def _untaken(ticker: str, book: dict) -> dict:
    """`book` less the depth paper orders already took from it."""
    out: dict = {"yes": [], "no": []}
    for ladder in ("yes", "no"):
        for lvl in book.get(ladder) or []:
            px = float(lvl["priceCents"])
            n = int(lvl["contracts"]) - _consumed.get((ticker, ladder, px), 0)
            if n > 0:
                out[ladder].append({"priceCents": px, "contracts": n})
    return out


def _walk(book: dict, side: str, action: str, count: int,
          limit: float) -> list[tuple[float, float, int]]:
    """The levels a `count` fill takes, best-first, as (traded cents, raw
    ladder cents, contracts)."""
    out: list[tuple[float, float, int]] = []
    mirror = action == "buy"
    levels = sorted(
        ((round(100 - float(lv["priceCents"]), 2) if mirror else float(lv["priceCents"]),
          float(lv["priceCents"]), int(lv["contracts"]))
         for lv in book.get(_ladder_of(side, action)) or []),
        key=lambda x: x[0] if mirror else -x[0])
    remaining = int(count)
    for px, raw, n in levels:
        if remaining <= 0:
            break
        if (px > limit) if action == "buy" else (px < limit):
            break
        take = min(n, remaining)
        if take > 0:
            out.append((px, raw, take))
            remaining -= take
    return out


def _apply_fill(conn, o: dict, book: Optional[dict], *, resting: bool) -> int:
    """Fill what the book allows of order `o`. Returns contracts filled.

    `book` None means it could not be read: nothing fills AND nothing about
    the order's memory of the book changes. Read as an empty book, a failed
    read reset seen_cross_qty, and the next good read "refilled" the same
    offer and filled the order twice."""
    remaining = int(o["count"]) - int(o["filled"])
    if remaining <= 0 or book is None:
        return 0
    if o["action"] == "sell":
        remaining = min(remaining, _held(conn, o["ticker"], o["side"]))
        if remaining <= 0:
            _set_status(conn, o["order_id"], "canceled", "nothing left to sell")
            return 0
    limit = float(o["limit_cents"])
    cross = sum(n for px_, n in paper_book._levels(book, o["side"], o["action"])
                if (px_ <= limit if o["action"] == "buy" else px_ >= limit))
    seen = int(o.get("seen_cross_qty") or 0)
    if resting:
        remaining = min(remaining, max(0, cross - seen))
    if cross != seen:
        conn.execute("UPDATE paper_orders SET seen_cross_qty=? WHERE order_id=?",
                     (int(cross), o["order_id"]))
        o["seen_cross_qty"] = cross
    if remaining <= 0:
        return 0
    t = o["ticker"]
    _reconcile_consumed(t, book)
    taken = _walk(_untaken(t, book) if resting else book,
                  o["side"], o["action"], remaining, limit)
    n = sum(k for _, _, k in taken)
    if n <= 0:
        return 0
    ladder = _ladder_of(o["side"], o["action"])
    for _, raw, k in taken:
        _consumed[(t, ladder, raw)] = min(
            _consumed.get((t, ladder, raw), 0) + k,
            sum(int(lv["contracts"]) for lv in book.get(ladder) or []
                if float(lv["priceCents"]) == raw))
    parts = [(limit, n)] if resting else [(px, k) for px, _, k in taken]
    cost = 0.0
    fees = 0.0
    for px, k in parts:
        fee = _fee_usd(px, k)
        paper_book.record_fill(
            ticker=t, title="", side=o["side"], action=o["action"],
            contracts=k, price_cents=px, fee_usd=fee, forecast_id=None,
            client="paper-exchange", env=db.PAPER_ENV, agent_id=ACCOUNT,
            order_id=o["order_id"], conn=conn,
        )
        cost += k * px / 100.0
        fees += fee
    filled = int(o["filled"]) + n
    conn.execute(
        """UPDATE paper_orders SET filled=?, fill_cost_usd=fill_cost_usd+?,
           fees_usd=fees_usd+?, status=?, updated_at=? WHERE order_id=?""",
        (filled, round(cost, 4), round(fees, 4),
         "executed" if filled >= int(o["count"]) else "resting", _now(), o["order_id"]),
    )
    o["filled"] = filled
    if o["action"] == "buy":
        _net(conn, t)
    logger.info("[paper] %s %s %s x%d at %s (%s)", o["action"], t, o["side"].upper(), n,
                ", ".join(f"{k}@{px:g}c" for px, k in parts),
                "resting fill" if resting else "on entry")
    return n


def _net(conn, ticker: str) -> None:
    """Both sides held: redeem the matched pairs for $1.00 each, as Kalshi
    does. Booked as two settle rows that sum to exactly $1 per pair, split at
    the YES side's average cost so neither leg books an invented gain."""
    p = _positions_by_ticker(_account_rows(conn, ticker)).get(ticker)
    if not p:
        return
    m = min(p["yes"]["n"], p["no"]["n"])
    if m <= 0:
        return
    x = round(max(0.0, min(100.0, p["yes"]["cost"] / p["yes"]["n"] * 100.0)), 4)
    for side, px in (("yes", x), ("no", round(100.0 - x, 4))):
        paper_book.record_fill(
            ticker=ticker, title="", side=side, action="settle", contracts=m,
            price_cents=px, fee_usd=0.0, forecast_id=None, client="paper-net",
            env=db.PAPER_ENV, agent_id=ACCOUNT, conn=conn,
        )


def _set_status(conn, order_id: str, status: str, note: str = "") -> None:
    conn.execute("UPDATE paper_orders SET status=?, note=?, updated_at=? WHERE order_id=?",
                 (status, note[:200], _now(), order_id))


async def _match_resting(tickers: Optional[set] = None) -> int:
    """Try every resting order (or those on `tickers`) against the current
    book. Books are read outside the lock; state changes happen inside it."""
    with db.get_db() as conn:
        rows = _resting(conn)
    want = sorted({r["ticker"] for r in rows if tickers is None or r["ticker"] in tickers})
    n = 0
    for t in want:
        read_at = time.monotonic()
        book = await _book(t)
        if book is None:
            continue
        async with _lock:
            if read_at < _last_applied.get(t, 0.0):
                continue
            _last_applied[t] = read_at
            with db.get_db() as conn:
                for o in _resting(conn, t):
                    n += _apply_fill(conn, o, book, resting=True)
    return n


def reserved_buy_usd() -> float:
    """Cash promised to the account's resting paper buys. Agents' paper buys
    count it too, so one shared bankroll cannot be spent twice."""
    with db.get_db() as conn:
        return _reserved_buy_usd(conn)


async def sweep() -> dict:
    """Periodic pass while the app is in Paper: cancel resting orders on
    markets that have closed, then fill what the real books now cross."""
    import kalshi_api
    with db.get_db() as conn:
        tickers = sorted({r["ticker"] for r in _resting(conn)})
    if not tickers:
        return {"canceled": 0, "filled": 0}
    canceled = 0
    try:
        found = await kalshi_api.fetch_markets_by_tickers(tickers) or {}
    except Exception:
        found = {}
    closed = {t for t, m in found.items()
              if isinstance(m, dict) and str(m.get("status") or "").lower() in _CLOSED_STATUSES}
    if closed:
        async with _lock:
            with db.get_db() as conn:
                for o in _resting(conn):
                    if o["ticker"] in closed:
                        _set_status(conn, o["order_id"], "canceled", "market closed")
                        canceled += 1
    filled = await _match_resting(set(tickers) - closed)
    return {"canceled": canceled, "filled": filled}



async def place_order(*, ticker: str, side: str, action: str, count: int,
                      price_cents: float, client_order_id: str) -> dict:
    read_at = time.monotonic()
    book = await _book(ticker)
    async with _lock:
        if book is not None:
            _last_applied[ticker] = max(_last_applied.get(ticker, 0.0), read_at)
        with db.get_db() as conn:
            if conn.execute("SELECT 1 FROM paper_orders WHERE client_order_id=?",
                            (client_order_id,)).fetchone():
                raise _err(409, "duplicate_client_order_id",
                           "An order with this client_order_id already exists.")
            px = float(price_cents)
            if action == "sell":
                avail = _held(conn, ticker, side) - _reserved_sell(conn, ticker, side)
                if count > avail:
                    raise _err(400, "insufficient_position",
                               f"Paper: you hold {max(0, avail)} {side.upper()} "
                               f"contract(s) on {ticker} not already being sold.")
            else:
                need = count * px / 100.0 + _fee_usd(px, count)
                cash = paper_book.book_cash(_bankroll_usd, _configured) - _reserved_buy_usd(conn)
                if need > cash + 1e-9:
                    raise _err(400, "insufficient_balance",
                               f"Paper: this order needs ${need:,.2f} and the paper "
                               f"account has ${max(0.0, cash):,.2f} free.")
            oid = f"paper-{uuid.uuid4()}"
            now = _now()
            conn.execute(
                """INSERT INTO paper_orders
                   (order_id, client_order_id, created_at, updated_at, ticker,
                    side, action, limit_cents, count, status)
                   VALUES (?,?,?,?,?,?,?,?,?, 'resting')""",
                (oid, client_order_id, now, now, ticker, side, action, px, int(count)),
            )
            o = _order(conn, oid)
            _apply_fill(conn, o, book, resting=False)
            o = _order(conn, oid)
    return {"order": _order_json(o)}


async def get_order(order_id: str) -> dict:
    with db.get_db() as conn:
        o = _order(conn, order_id)
    if o is None:
        raise _err(404, "not_found", "No such paper order.")
    if o["status"] == "resting":
        await _match_resting({o["ticker"]})
        with db.get_db() as conn:
            o = _order(conn, order_id)
    return {"order": _order_json(o)}


async def find_by_client_id(client_order_id: str) -> Optional[dict]:
    with db.get_db() as conn:
        r = conn.execute("SELECT * FROM paper_orders WHERE client_order_id=?",
                         (client_order_id,)).fetchone()
    return _order_json(dict(r)) if r else None


async def list_orders(*, status: str = "", ticker: str = "") -> list[dict]:
    if status in ("", "resting"):
        await _match_resting({ticker} if ticker else None)
    sql = "SELECT * FROM paper_orders WHERE 1=1"
    args: list = []
    if status:
        sql += " AND status=?"
        args.append(status)
    if ticker:
        sql += " AND ticker=?"
        args.append(ticker)
    with db.get_db() as conn:
        rows = conn.execute(sql + " ORDER BY created_at DESC LIMIT 1000", args).fetchall()
    return [_order_json(dict(r)) for r in rows]


async def cancel_order(order_id: str) -> dict:
    async with _lock:
        with db.get_db() as conn:
            o = _order(conn, order_id)
            if o is None or o["status"] != "resting":
                raise _err(404, "not_found", "No resting paper order with that id.")
            _set_status(conn, order_id, "canceled", "canceled")
            o = _order(conn, order_id)
    return {"order": _order_json(o)}


async def fills(*, order_id: Optional[str] = None, min_ts: Optional[int] = None) -> list[dict]:
    sql = ("SELECT * FROM paper_fills WHERE agent_id=? AND kind IN ('buy','sell') "
           "AND order_id IS NOT NULL")
    args: list = [ACCOUNT]
    if order_id:
        sql += " AND order_id=?"
        args.append(order_id)
    if min_ts:
        sql += " AND created_at >= ?"
        args.append(datetime.fromtimestamp(int(min_ts), timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"))
    with db.get_db() as conn:
        rows = conn.execute(sql + " ORDER BY id DESC LIMIT 1000", args).fetchall()
    return [_fill_json(dict(r)) for r in rows]


async def positions(*, settlement_status: Optional[str] = None) -> list[dict]:
    """Open account positions, one row per market, signed like Kalshi's
    (YES positive, NO negative). Settled history is not kept in this shape:
    a settled-only query answers empty."""
    if settlement_status == "settled":
        return []
    with db.get_db() as conn:
        by_t = _positions_by_ticker(_account_rows(conn))
        resting = _resting(conn)
    rest_n: dict[str, int] = {}
    for o in resting:
        rest_n[o["ticker"]] = rest_n.get(o["ticker"], 0) + 1
    out = []
    for t, p in sorted(by_t.items()):
        side = "yes" if p["yes"]["n"] > 0 else ("no" if p["no"]["n"] > 0 else None)
        if side is None:
            continue
        s = p[side]
        signed = s["n"] if side == "yes" else -s["n"]
        out.append({
            "ticker": t,
            "position": signed,
            "position_fp": f"{signed:.2f}",
            "market_exposure": int(round(s["cost"] * 100)),
            "market_exposure_dollars": f"{s['cost']:.4f}",
            "fees_paid_dollars": f"{s['fees']:.4f}",
            "realized_pnl_dollars": f"{p['realized']:.4f}",
            "total_traded_dollars": f"{p['traded']:.4f}",
            "resting_orders_count": rest_n.get(t, 0),
            "paper": True,
        })
    return out


async def balance() -> dict:
    """The paper account's cash in /portfolio/balance shape. Like Kalshi's,
    it is NOT reduced by resting orders (order acceptance reserves for them
    separately), and it carries no shard breakdown: paper has one pool."""
    cash = paper_book.book_cash(_bankroll_usd, _configured)
    cents = int(round(cash * 100))
    with db.get_db() as conn:
        by_t = _positions_by_ticker(_account_rows(conn))
    held_cost = sum(p[s]["cost"] for p in by_t.values() for s in ("yes", "no"))
    return {
        "balance": cents,
        "balance_dollars": f"{cash:.4f}",
        "total_balance_cents": cents,
        "portfolio_value": int(round(held_cost * 100)),
        "shard_balances": {},
        "sharded": False,
        "paper": True,
    }



_PAPER_SCOPED_TABLES = (
    "bot_positions", "crypto15m_positions", "pnl_snapshots", "bot_runs",
    "risk_state", "daily_stats", "terminal_rules",
)


async def reset_account() -> dict:
    """Start the paper account over: no orders, no fills, no paper-scope
    positions or runs. Live rows, retired rows and forecasts are untouched,
    and so is the agents' order audit (mcp_orders) — it is a record of what
    they did, not a balance."""
    removed: dict[str, int] = {}
    async with _lock:
        _consumed.clear()
        with db.get_db() as conn:
            conn.execute(
                "DELETE FROM order_events WHERE position_id IN "
                "(SELECT id FROM bot_positions WHERE kalshi_env=?)", (db.PAPER_ENV,))
            for t in _PAPER_SCOPED_TABLES:
                try:
                    cur = conn.execute(f"DELETE FROM {t} WHERE kalshi_env=?", (db.PAPER_ENV,))
                    removed[t] = int(cur.rowcount or 0)
                except Exception as e:
                    logger.debug("paper reset skipped %s: %s", t, e)
            removed["paper_orders"] = int(conn.execute("DELETE FROM paper_orders").rowcount or 0)
            removed["paper_fills"] = int(conn.execute("DELETE FROM paper_fills").rowcount or 0)
            conn.execute("INSERT OR REPLACE INTO paper_state (key, value) VALUES ('bankroll', ?)",
                         (str(float(_bankroll_usd)),))
    logger.info("[paper] account reset: %s", removed)
    return removed
