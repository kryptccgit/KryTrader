"""The paper book: real books, imaginary money.

One ledger (paper_fills) and one bankroll (`paper_bankroll_usd`) for every
kind of paper trading in the app:

  * The paper ACCOUNT — the whole app in Paper mode. Its orders come through
    kalshi_api's account functions, which route to paper_exchange; their fills
    are booked here under agent id 'account'.
  * AI agents trading in paper mode (mcp_server), each under its own agent id.
  * The 15m engine and scripts keep their own paper simulation rows in
    crypto15m_positions (scope 'paper'); their cash effect is folded into the
    same balance (book_cash), so the user sees one number.

A paper order fills against the same live order book the terminal shows for
the real market, walking the depth level by level, and settles on the real
outcome. That is the closest thing to a live result that costs nothing — and
it is what the scoreboard should be read next to.

What it deliberately does NOT model, stated so nobody reads the P&L as more
than it is:

  * Queue position. An agent's paper order is immediate-or-cancel: it takes
    what is offered up to its limit and the rest is dropped. The account's
    orders may rest (paper_exchange), but a resting paper order fills only when
    the real book later CROSSES its limit — never on a print at its price,
    because where it would have stood in the queue is unknowable.
  * Its own market impact. The book is not depleted by a paper fill, so two
    paper orders a second apart both see the same depth.
  * Depth beyond the visible ladder. An order bigger than that fills
    partially, which is the conservative error.

Fees use the exchange formula from the ticket (terminal._fee_usd), so paper
P&L is net of fees exactly the way live P&L is.

Every fill belongs to one owner: an agent (mcp_agents) or the account.
Positions are kept PER OWNER — two agents long the same market are two
positions, each with its own average cost — because "an agent may only sell
what it opened" has to hold on paper too, or one agent's exit sells another's
position and both records are wrong. The cash is shared (one bankroll), and
the whole-book figures are exactly the sum of the owners' own.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import db

logger = logging.getLogger("paper_book")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _levels(book: dict, side: str, action: str) -> list[tuple[float, int]]:
    """The prices a taker would trade at, best-first, as (cents, contracts).

    Kalshi's book holds only BIDS on each side. Buying YES lifts a NO bid
    mirrored (a 40c NO bid is a 60c YES offer); selling YES hits a YES bid."""
    yes = book.get("yes") or []
    no = book.get("no") or []
    def _pairs(ladder: list, mirror: bool) -> list[tuple[float, int]]:
        out = []
        for lvl in ladder:
            p = lvl.get("priceCents")
            n = lvl.get("contracts")
            if p is None or not n:
                continue
            out.append((round(100 - p, 2) if mirror else p, int(n)))
        return out
    if action == "buy":
        offers = _pairs(no if side == "yes" else yes, mirror=True)
        return sorted(offers, key=lambda x: x[0])
    bids = _pairs(yes if side == "yes" else no, mirror=False)
    return sorted(bids, key=lambda x: -x[0])


def simulate_fill(book: Optional[dict], side: str, action: str, count: int,
                  limit_cents: float) -> dict:
    """Walk the book up to the limit. Pure; the caller decides what to do
    with a partial or empty fill."""
    if not book:
        return {"filled": 0, "avgPriceCents": None, "levels": 0,
                "note": "No order book was available for this market."}
    levels = _levels(book, side, action)
    remaining = int(count)
    filled = 0
    notional = 0.0
    used = 0
    for px, size in levels:
        if action == "buy" and px > limit_cents:
            break
        if action == "sell" and px < limit_cents:
            break
        take = min(size, remaining)
        if take <= 0:
            break
        filled += take
        notional += take * px
        remaining -= take
        used += 1
        if remaining == 0:
            break
    avg = round(notional / filled, 2) if filled else None
    note = None
    if not levels:
        note = (f"Nobody is {'offering' if action == 'buy' else 'bidding'} "
                f"{side.upper()} right now — nothing to trade against.")
    elif filled == 0:
        best = levels[0][0]
        note = (f"Best {'offer' if action == 'buy' else 'bid'} is {best:g}c; a "
                f"{limit_cents:g}c limit crosses nothing. Paper orders do not rest.")
    elif remaining:
        note = (f"Filled {filled} of {count}; the visible book ran out inside "
                f"your limit. The rest was not placed.")
    return {"filled": filled, "avgPriceCents": avg, "levels": used, "note": note}


DEFAULT_AGENT = "default"
ACCOUNT_AGENT = "account"


def _agent_of(r: dict) -> str:
    return str(r.get("agent_id") or "") or DEFAULT_AGENT


def _rows(conn, agent_id: Optional[str] = None) -> list[dict]:
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM paper_fills ORDER BY id ASC").fetchall()]
    if agent_id is None:
        return rows
    return [r for r in rows if _agent_of(r) == agent_id]


def _replay_all(rows: list[dict]) -> tuple[dict, float]:
    """Positions keyed (agent, ticker, side), and realised P&L summed over
    agents. Each agent is replayed on its own fills only."""
    by_agent: dict[str, list[dict]] = {}
    for r in rows:
        by_agent.setdefault(_agent_of(r), []).append(r)
    pos: dict[tuple[str, str, str], dict] = {}
    realized = 0.0
    for aid, rs in by_agent.items():
        p, real = _replay(rs)
        realized += real
        for (t, side), v in p.items():
            pos[(aid, t, side)] = v
    return pos, realized


def _replay(rows: list[dict]) -> tuple[dict, float]:
    """Positions by (ticker, side) with average cost, plus realised P&L.
    Average-cost accounting, same as the manual-trading history."""
    pos: dict[tuple[str, str], dict] = {}
    realized = 0.0
    for r in rows:
        key = (r["ticker"], r["side"])
        p = pos.setdefault(key, {"ticker": r["ticker"], "side": r["side"],
                                 "title": r.get("title") or None,
                                 "contracts": 0, "costUsd": 0.0})
        n = int(r["contracts"])
        if r["kind"] == "buy":
            p["contracts"] += n
            p["costUsd"] += float(r["cash_delta_usd"]) * -1.0
        else:
            if p["contracts"] <= 0:
                continue
            n = min(n, p["contracts"])
            avg = p["costUsd"] / p["contracts"]
            realized += float(r["cash_delta_usd"]) - avg * n
            p["costUsd"] -= avg * n
            p["contracts"] -= n
    return pos, realized


def engine_paper_cash_usd(conn) -> float:
    """Cash effect of the 15m engine's and scripts' paper simulation — rows
    they keep in crypto15m_positions under the 'paper' scope rather than in
    this ledger. Realised P&L of what has resolved, minus the residual cost of
    what is still open (matched pairs excluded, as the live account total
    does). Paper rows a LIVE session's paper runners write are scoped
    'production' and are not part of the paper account."""
    row = conn.execute(
        """SELECT COALESCE(SUM(pnl_usd), 0) FROM crypto15m_positions
           WHERE kalshi_env=? AND resolved=1 AND pnl_usd IS NOT NULL""",
        (db.PAPER_ENV,)).fetchone()
    realized = float(row[0] or 0.0)
    return realized - float(db._c15_matched_adjusted_cost(conn, db.PAPER_ENV))


def effective_bankroll(default_usd: float, seed: bool = True) -> float:
    """The starting balance in effect for the current paper book. Seeded from
    `default_usd` (the configured value) the first time the book is read, and
    re-fixed only by a Reset — see db.paper_state. `seed=False` reads without
    fixing anything (the backend before the user's settings have arrived)."""
    with db.get_db() as conn:
        row = conn.execute("SELECT value FROM paper_state WHERE key='bankroll'").fetchone()
        if row is not None:
            try:
                return float(row[0])
            except (TypeError, ValueError):
                pass
        if not seed:
            return float(default_usd)
        conn.execute("INSERT OR REPLACE INTO paper_state (key, value) VALUES ('bankroll', ?)",
                     (str(float(default_usd)),))
    return float(default_usd)


def set_effective_bankroll(usd: float) -> None:
    with db.get_db() as conn:
        conn.execute("INSERT OR REPLACE INTO paper_state (key, value) VALUES ('bankroll', ?)",
                     (str(float(usd)),))


def book_cash(bankroll_usd: float, seed: bool = True) -> float:
    """The paper account's cash: the starting bankroll in effect (see
    effective_bankroll; `bankroll_usd` seeds it), plus every fill and
    settlement in the ledger (account and agents alike), plus the 15m/script
    paper simulation. One balance for the whole paper book."""
    start = effective_bankroll(bankroll_usd, seed)
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(cash_delta_usd), 0) FROM paper_fills").fetchone()
        engine = engine_paper_cash_usd(conn)
    return start + float(row[0] or 0.0) + engine


def portfolio(bankroll_usd: float, marks: Optional[dict] = None,
              agent_id: Optional[str] = None) -> dict:
    """`marks` maps ticker -> MarketSummary row. A position whose side has no
    bid has no mark, and its unrealised P&L is None rather than a guess.

    With `agent_id`, only that agent's positions, fills and realised P&L.
    Without one, every AGENT's — the paper account's own positions are shown
    by the terminal portfolio, not here. The cash is always the one shared
    book's (there is one bankroll)."""
    marks = marks or {}
    with db.get_db() as conn:
        all_rows = _rows(conn)
    if agent_id is None:
        rows = [r for r in all_rows if _agent_of(r) != ACCOUNT_AGENT]
    else:
        rows = [r for r in all_rows if _agent_of(r) == agent_id]
    keyed, realized = _replay_all(rows)
    cash = book_cash(bankroll_usd)
    out = []
    for (aid, _t, _s), p in keyed.items():
        if p["contracts"] <= 0:
            continue
        m = marks.get(p["ticker"]) or {}
        bid = m.get("yesBid") if p["side"] == "yes" else m.get("noBid")
        avg_c = round(p["costUsd"] / p["contracts"] * 100, 2)
        unreal = None
        if bid is not None:
            unreal = round(p["contracts"] * bid / 100.0 - p["costUsd"], 2)
        out.append({
            "ticker": p["ticker"], "title": p["title"] or m.get("title"),
            "side": p["side"], "contracts": p["contracts"],
            "avgCostCents": avg_c, "costUsd": round(p["costUsd"], 2),
            "markCents": bid, "unrealizedUsd": unreal, "agentId": aid,
        })
    return {
        "bankrollUsd": round(effective_bankroll(bankroll_usd), 2),
        "cashUsd": round(cash, 2),
        "realizedUsd": round(realized, 2),
        "positions": out,
        "fills": [
            {"id": int(r["id"]), "at": r["created_at"], "ticker": r["ticker"],
             "side": r["side"], "kind": r["kind"], "contracts": int(r["contracts"]),
             "priceCents": float(r["price_cents"]), "feeUsd": float(r["fee_usd"]),
             "cashDeltaUsd": float(r["cash_delta_usd"]),
             "forecastId": r.get("forecast_id"), "agentId": _agent_of(r)}
            for r in reversed(rows[-50:])
        ],
    }


def day_pnl(day: str, marks: Optional[dict] = None) -> dict:
    """Realised P&L booked on `day` (UTC, YYYY-MM-DD) plus the unrealised P&L
    of what is still open, marked at the bid on the held side.

    A position with no bid (nobody bids its side, or the marks could not be
    read at all) is not in `unrealizedUsd` — no price exists to mark it at —
    but it is listed in `unmarked` and its whole cost is in
    `unmarkedCostUsd`: the worst case, which the loss stop counts. Left out
    of the stop entirely it read as a $0 loss, so a failed marks read or a
    market gone quiet switched the stop off."""
    marks = marks or {}
    with db.get_db() as conn:
        rows = [r for r in _rows(conn) if _agent_of(r) != ACCOUNT_AGENT]
    pos: dict[tuple[str, str, str], dict] = {}
    realized_today = 0.0
    for r in rows:
        key = (_agent_of(r), r["ticker"], r["side"])
        p = pos.setdefault(key, {"contracts": 0, "costUsd": 0.0})
        n = int(r["contracts"])
        if r["kind"] == "buy":
            p["contracts"] += n
            p["costUsd"] -= float(r["cash_delta_usd"])
            continue
        if p["contracts"] <= 0:
            continue
        n = min(n, p["contracts"])
        avg = p["costUsd"] / p["contracts"]
        if str(r["created_at"])[:10] == day:
            realized_today += float(r["cash_delta_usd"]) - avg * n
        p["costUsd"] -= avg * n
        p["contracts"] -= n
    unreal = 0.0
    unmarked = []
    unmarked_cost = 0.0
    for (_aid, t, side), p in pos.items():
        if p["contracts"] <= 0:
            continue
        m = marks.get(t) or {}
        bid = m.get("yesBid") if side == "yes" else m.get("noBid")
        if bid is None:
            unmarked.append(t)
            unmarked_cost += p["costUsd"]
            continue
        unreal += p["contracts"] * bid / 100.0 - p["costUsd"]
    return {"realizedUsd": round(realized_today, 2), "unrealizedUsd": round(unreal, 2),
            "unmarked": unmarked, "unmarkedCostUsd": round(unmarked_cost, 2)}


def agents_open_cost_usd() -> float:
    """Cost basis (fees in) of every AGENT's open paper position. Their buys
    already left the shared cash, so the paper account total adds this back —
    the account's own positions are valued from bot_positions instead."""
    with db.get_db() as conn:
        rows = [r for r in _rows(conn) if _agent_of(r) != ACCOUNT_AGENT]
    pos, _ = _replay_all(rows)
    return sum(p["costUsd"] for p in pos.values() if p["contracts"] > 0)


def held(ticker: str, side: str, agent_id: str = DEFAULT_AGENT) -> int:
    """Contracts THIS agent holds. Another agent's position on the same side
    of the same market is not this one's to sell."""
    with db.get_db() as conn:
        pos, _ = _replay(_rows(conn, agent_id))
    return int((pos.get((ticker, side)) or {}).get("contracts") or 0)


def open_tickers(agent_id: Optional[str] = None, *, agents_only: bool = False) -> list[str]:
    """Markets with an open paper position — every owner's, one's, or (with
    agents_only) every agent's but not the paper account's."""
    with db.get_db() as conn:
        rows = _rows(conn, agent_id)
    if agents_only:
        rows = [r for r in rows if _agent_of(r) != ACCOUNT_AGENT]
    pos, _ = _replay_all(rows)
    return sorted({t for (_a, t, _s), p in pos.items() if p["contracts"] > 0})


def open_tickers_by_agent() -> dict[str, set]:
    """{agent id: markets it holds an open paper position in}, every agent's
    (the paper account's own excluded)."""
    with db.get_db() as conn:
        rows = [r for r in _rows(conn) if _agent_of(r) != ACCOUNT_AGENT]
    pos, _ = _replay_all(rows)
    out: dict[str, set] = {}
    for (aid, t, _s), p in pos.items():
        if p["contracts"] > 0:
            out.setdefault(aid, set()).add(t)
    return out


def open_positions(agent_id: str) -> list[dict]:
    """One agent's open paper positions: ticker, side, contracts, cost."""
    with db.get_db() as conn:
        pos, _ = _replay(_rows(conn, agent_id))
    return [{"ticker": p["ticker"], "side": p["side"], "title": p["title"],
             "contracts": int(p["contracts"]), "costUsd": round(p["costUsd"], 4)}
            for p in pos.values() if p["contracts"] > 0]


def agent_summary(agent_id: str, marks: Optional[dict] = None) -> dict:
    """One agent's paper record: realised P&L, open P&L at the bid (None if a
    held side has no bid — unmarked is not $0), positions and fill count."""
    marks = marks or {}
    with db.get_db() as conn:
        rows = _rows(conn, agent_id)
    pos, realized = _replay(rows)
    unreal: Optional[float] = 0.0
    n_open = 0
    for (t, side), p in pos.items():
        if p["contracts"] <= 0:
            continue
        n_open += 1
        m = marks.get(t) or {}
        bid = m.get("yesBid") if side == "yes" else m.get("noBid")
        if bid is None or unreal is None:
            unreal = None
            continue
        unreal += p["contracts"] * bid / 100.0 - p["costUsd"]
    return {
        "agentId": agent_id,
        "realizedUsd": round(realized, 2),
        "unrealizedUsd": round(unreal, 2) if unreal is not None else None,
        "openPositions": n_open,
        "fills": sum(1 for r in rows if r["kind"] in ("buy", "sell")),
    }


def agent_ids() -> list[str]:
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT COALESCE(NULLIF(agent_id, ''), 'default') FROM paper_fills"
        ).fetchall()
    return sorted(r[0] for r in rows if r[0] != ACCOUNT_AGENT)


def record_fill(*, ticker: str, title: str, side: str, action: str,
                contracts: int, price_cents: float, fee_usd: float,
                forecast_id: Optional[int], client: str, env: str,
                agent_id: str = DEFAULT_AGENT, order_id: Optional[str] = None,
                conn=None) -> int:
    gross = contracts * price_cents / 100.0
    delta = -(gross + fee_usd) if action == "buy" else (gross - fee_usd)
    args = (_now(), env, ticker, (title or "")[:300], side, action,
            int(contracts), float(price_cents), round(fee_usd, 2),
            round(delta, 4), forecast_id, (client or "")[:80],
            agent_id or DEFAULT_AGENT, order_id)
    sql = """INSERT INTO paper_fills
               (created_at, kalshi_env, ticker, title, side, kind, contracts,
                price_cents, fee_usd, cash_delta_usd, forecast_id, client, agent_id,
                order_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)"""
    if conn is not None:
        return int(conn.execute(sql, args).lastrowid)
    with db.get_db() as c:
        return int(c.execute(sql, args).lastrowid)


async def settle_pending() -> int:
    """Pay out paper positions whose markets have settled, at the real
    outcome. Returns the number of positions settled."""
    import forecast_ledger
    tickers = open_tickers()
    if not tickers:
        return 0
    outcomes = await forecast_ledger.fetch_outcomes(tickers)
    with db.get_db() as conn:
        pos, _ = _replay_all(_rows(conn))
    n = 0
    for (aid, t, side), p in pos.items():
        o = outcomes.get(t)
        if o is None or p["contracts"] <= 0:
            continue
        pay_c = round((o if side == "yes" else 1.0 - o) * 100.0, 2)
        with db.get_db() as conn:
            conn.execute(
                """INSERT INTO paper_fills
                   (created_at, kalshi_env, ticker, title, side, kind,
                    contracts, price_cents, fee_usd, cash_delta_usd, client, agent_id)
                   VALUES (?,?,?,?,?,'settle',?,?,0,?,'',?)""",
                (_now(), "", t, p["title"] or "", side, p["contracts"],
                 pay_c, round(p["contracts"] * pay_c / 100.0, 4), aid),
            )
        n += 1
        logger.info("[paper] settled %s %s x%d at %gc", t, side.upper(),
                    p["contracts"], pay_c)
    return n


def reset() -> int:
    """The ledger part of a paper reset. The whole reset — orders, the paper
    scope's positions and runs too — is paper_exchange.reset_account."""
    with db.get_db() as conn:
        cur = conn.execute("DELETE FROM paper_fills")
        return int(cur.rowcount or 0)
