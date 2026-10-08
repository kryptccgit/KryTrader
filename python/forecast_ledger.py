"""Every AI fair value, kept until the market settles, then scored.

The question this answers is the only one that matters before anybody sizes a
position off a model: *does it beat the price?* Not "is it usually right" — a
model that says 90% on every market priced at 90c is usually right and has no
edge at all. The benchmark is the market's own mid at the moment the forecast
was made, and the score is the Brier score of each against what actually
happened.

Rules this module holds to:

  * The comparison is PAIRED. A forecast is scored against the mid that existed
    when it was made, never a later one — scoring a 2pm forecast against the
    5pm price would hand the market the afternoon's news for free, or take it
    away.
  * A forecast made when there was no two-sided quote has no market to beat.
    Its market Brier is None (invariant 1), it is counted in the AI-only score,
    and it is excluded from the head-to-head rather than compared against an
    invented 50c.
  * One forecast per market per source is scored — the most recent. A user who
    re-runs the analysis five times on one market must not get five correlated
    samples counted as five pieces of evidence.
  * "The AI beat the market" is a claim that needs a sample. Under
    MIN_SCORED the verdict is "too few", and inside two standard errors it is
    "indistinguishable". A scoreboard that crowns a winner after six markets is
    a confident lie with a chart on it.

Outcomes come from Kalshi's public market record, which is always production
(kalshi_api.PUBLIC_BASE) — so a forecast is scored the same way whichever
environment the app happened to be pointed at.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Optional

import db

logger = logging.getLogger("forecast_ledger")

SOURCES = ("panel", "mcp")

MIN_SCORED = 30

RESOLVE_BATCH = 200


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _cents_or_none(v: Any) -> Optional[float]:
    """1..99 or None. 0 and 100 are settled outcomes, not prices — the same
    rule terminal.price_cents applies, kept local so this module stays
    importable without the terminal."""
    x = _f(v)
    if x is None or x < 1 or x > 99:
        return None
    return x


def record(*, ticker: str, prob_yes: float, source: str, model: str = "",
           market: Optional[dict] = None, rationale: str = "",
           env: str = "", client: str = "", agent_id: Optional[str] = None) -> int:
    """Store one forecast with the market as it stood at that moment.

    `market` is a terminal MarketSummary row. Its absent fields stay absent:
    a market with no bid has no mid, and the row says so.

    `agent_id` is the user's named agent that made it (mcp source); the
    panel's forecasts belong to no agent. It is what lets a buy cite only a
    forecast ITS OWN agent made, and the scoreboard say which agent is any
    good."""
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}")
    p = _f(prob_yes)
    if p is None or not (0.01 <= p <= 0.99):
        raise ValueError("probability must be between 0.01 and 0.99")
    ticker = (ticker or "").strip().upper()
    if not ticker:
        raise ValueError("ticker required")
    m = market or {}
    if source == "mcp":
        agent_id = str(agent_id or "") or "default"
    else:
        agent_id = None
    with db.get_db() as conn:
        cur = conn.execute(
            """INSERT INTO ai_forecasts
               (kalshi_env, ticker, title, source, model, client, prob_yes,
                market_mid_cents, yes_bid_cents, yes_ask_cents, close_time,
                rationale, agent_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (env or "", ticker, str(m.get("title") or "")[:300], source,
             str(model or "")[:80], str(client or "")[:80], round(p, 4),
             _cents_or_none(m.get("midCents")),
             _cents_or_none(m.get("yesBid")),
             _cents_or_none(m.get("yesAsk")),
             m.get("closeTime"), str(rationale or "")[:2000], agent_id),
        )
        return int(cur.lastrowid)


def get(forecast_id: int) -> Optional[dict]:
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT * FROM ai_forecasts WHERE id=?", (int(forecast_id),)).fetchone()
    return dict(row) if row else None


def outcome_of(market: Optional[dict]) -> Optional[float]:
    """Raw Kalshi market record -> YES payout in 0..1, or None if unsettled.

    Delegates to the trader's reader so the bot, the paper book and this
    scoreboard can never disagree about what a market paid."""
    from trader import _market_yes_payout
    return _market_yes_payout(market)


async def fetch_outcomes(tickers: list[str]) -> dict[str, Optional[float]]:
    """{ticker: payout or None}. A ticker Kalshi did not return is omitted —
    'we could not read it' is not 'it has not settled'."""
    import kalshi_api
    if not tickers:
        return {}
    found = await kalshi_api.fetch_markets_by_tickers(tickers) or {}
    return {t: outcome_of(m) for t, m in found.items()}


def _pending_tickers(conn, limit: int) -> list[str]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute(
        """SELECT ticker, MIN(COALESCE(last_checked_at, '')) AS lc
           FROM ai_forecasts
           WHERE outcome IS NULL
             AND (close_time IS NULL OR substr(close_time, 1, 19) <= ?)
           GROUP BY ticker ORDER BY lc ASC LIMIT ?""",
        (now, int(limit)),
    ).fetchall()
    return [r["ticker"] for r in rows]


async def resolve_pending() -> int:
    """Look up settled outcomes for forecasts whose markets have closed.
    Returns how many forecast rows were resolved."""
    with db.get_db() as conn:
        tickers = _pending_tickers(conn, RESOLVE_BATCH)
    if not tickers:
        return 0
    outcomes = await fetch_outcomes(tickers)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    n = 0
    with db.get_db() as conn:
        for t in tickers:
            o = outcomes.get(t)
            if o is None:
                conn.execute(
                    "UPDATE ai_forecasts SET last_checked_at=? "
                    "WHERE ticker=? AND outcome IS NULL", (stamp, t))
                continue
            cur = conn.execute(
                "UPDATE ai_forecasts SET outcome=?, resolved_at=?, last_checked_at=? "
                "WHERE ticker=? AND outcome IS NULL", (o, stamp, stamp, t))
            n += cur.rowcount or 0
    if n:
        logger.info("[forecast] resolved %d forecast(s) across %d market(s)",
                    n, sum(1 for t in tickers if outcomes.get(t) is not None))
    return n



def _latest_per_market(rows: list[dict], per_source: bool = True) -> list[dict]:
    seen: dict[tuple, dict] = {}
    for r in rows:
        seen[(r["source"] if per_source else "", r["ticker"])] = r
    return list(seen.values())


def _verdict(n: int, mean: Optional[float], se: Optional[float]) -> str:
    if n < MIN_SCORED or mean is None:
        return "too-few"
    if se is None or mean == 0 or abs(mean) < 2 * se:
        return "indistinguishable"
    return "ai-better" if mean < 0 else "market-better"


def score(rows: list[dict]) -> dict:
    """Score already-resolved, already-deduplicated forecasts. Pure."""
    ai_sq: list[float] = []
    diffs: list[float] = []
    mkt_sq: list[float] = []
    for r in rows:
        o = _f(r.get("outcome"))
        p = _f(r.get("prob_yes"))
        if o is None or p is None:
            continue
        a = (p - o) ** 2
        ai_sq.append(a)
        mid = _cents_or_none(r.get("market_mid_cents"))
        if mid is not None:
            m = (mid / 100.0 - o) ** 2
            mkt_sq.append(m)
            diffs.append(a - m)

    n_pair = len(diffs)
    mean = se = None
    if n_pair:
        mean = sum(diffs) / n_pair
        if n_pair > 1:
            var = sum((d - mean) ** 2 for d in diffs) / (n_pair - 1)
            se = math.sqrt(var / n_pair)
    brier_mkt = (sum(mkt_sq) / len(mkt_sq)) if mkt_sq else None
    brier_ai_paired = (brier_mkt + mean) if (brier_mkt is not None and mean is not None) else None
    skill = None
    if brier_mkt and brier_ai_paired is not None:
        skill = 1.0 - brier_ai_paired / brier_mkt
    return {
        "n": len(ai_sq),
        "nPaired": n_pair,
        "brierAi": round(sum(ai_sq) / len(ai_sq), 4) if ai_sq else None,
        "brierAiPaired": round(brier_ai_paired, 4) if brier_ai_paired is not None else None,
        "brierMarket": round(brier_mkt, 4) if brier_mkt is not None else None,
        "skill": round(skill, 4) if skill is not None else None,
        "diffMean": round(mean, 5) if mean is not None else None,
        "diffSe": round(se, 5) if se is not None else None,
        "verdict": _verdict(n_pair, mean, se),
    }


def buckets(rows: list[dict], width: float = 0.1) -> list[dict]:
    """Reliability table: of the times the AI said ~30%, how often was it YES?
    Empty buckets are omitted rather than drawn at zero."""
    out: dict[int, list] = {}
    for r in rows:
        o = _f(r.get("outcome"))
        p = _f(r.get("prob_yes"))
        if o is None or p is None:
            continue
        k = min(int(p / width), int(1 / width) - 1)
        out.setdefault(k, []).append((p, o))
    res = []
    for k in sorted(out):
        pts = out[k]
        res.append({
            "lo": round(k * width, 2), "hi": round((k + 1) * width, 2),
            "n": len(pts),
            "meanForecast": round(sum(p for p, _ in pts) / len(pts), 4),
            "hitRate": round(sum(o for _, o in pts) / len(pts), 4),
        })
    return res


OPEN_WINDOW_HOURS = 48
OPEN_PER_FORECASTER = 20
MAX_FORECASTERS = 24


def _who(r: dict) -> tuple[str, str, str, Optional[str]]:
    return (r["source"], (r.get("client") or "").strip(), (r.get("model") or "").strip(),
            _agent_key(r))


def _ts(v: Any) -> Optional[float]:
    """SQLite's datetime('now') text ("2026-10-06 12:00:00", UTC) to epoch."""
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "").replace(" ", "T")[:19])
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc).timestamp()


def by_forecaster(all_rows: list[dict], now: Optional[datetime] = None) -> list[dict]:
    """One row per distinct (source, client, model, named agent): its own
    paired score on its own latest forecast per settled market, plus its open
    calls. Pure.

    The headline score answers "does AI beat the price"; this answers "does
    THIS one" — an agent losing to the market should not be able to hide
    behind one that is winning."""
    now = now or datetime.now(timezone.utc)
    cutoff = now.timestamp() - OPEN_WINDOW_HOURS * 3600
    groups: dict[tuple, list[dict]] = {}
    for r in all_rows:
        groups.setdefault(_who(r), []).append(r)
    out = []
    for (source, client, model, agent_id), rows in groups.items():
        resolved = _latest_per_market([r for r in rows if r.get("outcome") is not None])
        open_by_ticker: dict[str, dict] = {}
        for r in rows:
            if r.get("outcome") is not None:
                continue
            ts = _ts(r.get("created_at"))
            if ts is None or ts < cutoff:
                continue
            open_by_ticker[r["ticker"]] = r
        open_rows = sorted(open_by_ticker.values(), key=lambda r: r["id"], reverse=True)
        out.append({
            "source": source, "client": client or None, "model": model or None,
            "agentId": agent_id,
            "total": len(rows),
            "pending": sum(1 for r in rows if r.get("outcome") is None),
            "lastAt": rows[-1].get("created_at"),
            **score(resolved),
            "open": [{
                "ticker": r["ticker"],
                "fairValueCents": round(float(r["prob_yes"]) * 100, 1),
                "marketMidCents": _cents_or_none(r.get("market_mid_cents")),
                "createdAt": r.get("created_at"),
            } for r in open_rows[:OPEN_PER_FORECASTER]],
        })
    out.sort(key=lambda f: f["lastAt"] or "", reverse=True)
    return out[:MAX_FORECASTERS]


def _agent_key(r: dict) -> Optional[str]:
    if r.get("source") != "mcp":
        return None
    return str(r.get("agent_id") or "") or "default"


def by_agent(all_rows: list[dict]) -> list[dict]:
    """One row per named agent (mcp forecasts only): its own paired score on
    its own latest forecast per settled market. Pure.

    The forecaster rows above split by client and model — "Claude Code ·
    opus". This splits by the user's own agents, which is what the user
    compares when deciding which one goes live: two agents on the same model
    with different guides are two records, and one agent driven from two
    clients is one. Every agent is scored only on markets IT forecast."""
    groups: dict[str, list[dict]] = {}
    for r in all_rows:
        k = _agent_key(r)
        if k is not None:
            groups.setdefault(k, []).append(r)
    out = []
    for aid, rows in groups.items():
        resolved = _latest_per_market([r for r in rows if r.get("outcome") is not None])
        out.append({
            "agentId": aid,
            "total": len(rows),
            "pending": sum(1 for r in rows if r.get("outcome") is None),
            "lastAt": rows[-1].get("created_at"),
            **score(resolved),
        })
    out.sort(key=lambda f: f["lastAt"] or "", reverse=True)
    return out


def scoreboard(recent: int = 40) -> dict:
    with db.get_db() as conn:
        all_rows = [dict(r) for r in conn.execute(
            "SELECT * FROM ai_forecasts ORDER BY id ASC").fetchall()]
    resolved = [r for r in all_rows if r.get("outcome") is not None]
    deduped = _latest_per_market(resolved)
    overall_rows = _latest_per_market(resolved, per_source=False)

    by_source = []
    for s in SOURCES:
        rows = [r for r in deduped if r["source"] == s]
        by_source.append({"source": s, **score(rows)})

    def _row(r: dict) -> dict:
        o = _f(r.get("outcome"))
        p = _f(r.get("prob_yes"))
        mid = _cents_or_none(r.get("market_mid_cents"))
        return {
            "id": int(r["id"]),
            "createdAt": r.get("created_at"),
            "ticker": r["ticker"],
            "title": r.get("title") or None,
            "source": r["source"],
            "model": r.get("model") or None,
            "client": r.get("client") or None,
            "agentId": _agent_key(r),
            "fairValueCents": round(p * 100, 1) if p is not None else None,
            "marketMidCents": mid,
            "outcome": o,
            "resolvedAt": r.get("resolved_at"),
            "brierAi": round((p - o) ** 2, 4) if (o is not None and p is not None) else None,
            "brierMarket": round((mid / 100 - o) ** 2, 4) if (o is not None and mid is not None) else None,
        }

    return {
        "totalForecasts": len(all_rows),
        "pending": sum(1 for r in all_rows if r.get("outcome") is None),
        "resolved": len(resolved),
        "scoredMarkets": len(overall_rows),
        "minScored": MIN_SCORED,
        "overall": score(overall_rows),
        "bySource": by_source,
        "buckets": buckets(overall_rows),
        "byForecaster": by_forecaster(all_rows),
        "byAgent": by_agent(all_rows),
        "recent": [_row(r) for r in reversed(all_rows[-recent:])],
    }
