from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import db

logger = logging.getLogger("paper_book")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _levels(book: dict, side: str, action: str) -> list[tuple[float, int]]:
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


def _rows(conn) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM paper_fills ORDER BY id ASC").fetchall()]


def _replay(rows: list[dict]) -> tuple[dict, float]:
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


def portfolio(bankroll_usd: float, marks: Optional[dict] = None) -> dict:
    marks = marks or {}
    with db.get_db() as conn:
        rows = _rows(conn)
    pos, realized = _replay(rows)
    cash = float(bankroll_usd) + sum(float(r["cash_delta_usd"]) for r in rows)
    out = []
    for p in pos.values():
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
            "markCents": bid, "unrealizedUsd": unreal,
        })
    return {
        "bankrollUsd": round(float(bankroll_usd), 2),
        "cashUsd": round(cash, 2),
        "realizedUsd": round(realized, 2),
        "positions": out,
        "fills": [
            {"id": int(r["id"]), "at": r["created_at"], "ticker": r["ticker"],
             "side": r["side"], "kind": r["kind"], "contracts": int(r["contracts"]),
             "priceCents": float(r["price_cents"]), "feeUsd": float(r["fee_usd"]),
             "cashDeltaUsd": float(r["cash_delta_usd"]),
             "forecastId": r.get("forecast_id")}
            for r in reversed(rows[-50:])
        ],
    }


def day_pnl(day: str, marks: Optional[dict] = None) -> dict:
    marks = marks or {}
    with db.get_db() as conn:
        rows = _rows(conn)
    pos: dict[tuple[str, str], dict] = {}
    realized_today = 0.0
    for r in rows:
        key = (r["ticker"], r["side"])
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
    for (t, side), p in pos.items():
        if p["contracts"] <= 0:
            continue
        m = marks.get(t) or {}
        bid = m.get("yesBid") if side == "yes" else m.get("noBid")
        if bid is None:
            unmarked.append(t)
            continue
        unreal += p["contracts"] * bid / 100.0 - p["costUsd"]
    return {"realizedUsd": round(realized_today, 2), "unrealizedUsd": round(unreal, 2),
            "unmarked": unmarked}


def held(ticker: str, side: str) -> int:
    with db.get_db() as conn:
        pos, _ = _replay(_rows(conn))
    return int((pos.get((ticker, side)) or {}).get("contracts") or 0)


def open_tickers() -> list[str]:
    with db.get_db() as conn:
        pos, _ = _replay(_rows(conn))
    return sorted({t for (t, _s), p in pos.items() if p["contracts"] > 0})


def record_fill(*, ticker: str, title: str, side: str, action: str,
                contracts: int, price_cents: float, fee_usd: float,
                forecast_id: Optional[int], client: str, env: str) -> int:
    gross = contracts * price_cents / 100.0
    delta = -(gross + fee_usd) if action == "buy" else (gross - fee_usd)
    with db.get_db() as conn:
        cur = conn.execute(
            """INSERT INTO paper_fills
               (created_at, kalshi_env, ticker, title, side, kind, contracts,
                price_cents, fee_usd, cash_delta_usd, forecast_id, client)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (_now(), env, ticker, (title or "")[:300], side, action,
             int(contracts), float(price_cents), round(fee_usd, 2),
             round(delta, 4), forecast_id, (client or "")[:80]),
        )
        return int(cur.lastrowid)


async def settle_pending() -> int:
    import forecast_ledger
    tickers = open_tickers()
    if not tickers:
        return 0
    outcomes = await forecast_ledger.fetch_outcomes(tickers)
    with db.get_db() as conn:
        pos, _ = _replay(_rows(conn))
    n = 0
    for (t, side), p in pos.items():
        o = outcomes.get(t)
        if o is None or p["contracts"] <= 0:
            continue
        pay_c = round((o if side == "yes" else 1.0 - o) * 100.0, 2)
        with db.get_db() as conn:
            conn.execute(
                """INSERT INTO paper_fills
                   (created_at, kalshi_env, ticker, title, side, kind,
                    contracts, price_cents, fee_usd, cash_delta_usd, client)
                   VALUES (?,?,?,?,?,'settle',?,?,0,?,'')""",
                (_now(), "", t, p["title"] or "", side, p["contracts"],
                 pay_c, round(p["contracts"] * pay_c / 100.0, 4)),
            )
        n += 1
        logger.info("[paper] settled %s %s x%d at %gc", t, side.upper(),
                    p["contracts"], pay_c)
    return n


def reset() -> int:
    with db.get_db() as conn:
        cur = conn.execute("DELETE FROM paper_fills")
        return int(cur.rowcount or 0)
