"""Coin Optimizer: sweep strategies across hour-buckets for one coin, elect a
per-hour winner, and assemble a best-24h schedule — with a walk-forward holdout.

Method (honest + cheap): each strategy is replayed ONCE over the coin's recorded
windows (replay.replay already enters one trade per window at the first
qualifying tick, held to settlement, fee-adjusted). Every trade carries its UTC
hour, so bucketing those trades by hour is identical to running each strategy
per-bucket — but N replays instead of N×buckets.

Overfit guard: winners are ELECTED on the TRAIN split (older data) and the
assembled schedule is scored on a held-out TEST split (recent data) it never
saw. A bucket elects nobody unless its best strategy clears `min_trades` on
train — so 2 days of data correctly elects nothing.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import replay
import turbine_import
from config import merge_with_defaults
from turbine_backtest import _rank_score, _tstat

_ALLOWED_GRANULARITY = (1, 2, 3, 4, 6, 8, 12, 24)


def _hour_of(at: Optional[str]) -> Optional[int]:
    if not at:
        return None
    try:
        return datetime.strptime(str(at)[:19], "%Y-%m-%d %H:%M:%S").hour
    except Exception:
        return None


def _buckets(granularity_h: int) -> list[tuple[int, int]]:
    g = granularity_h if granularity_h in _ALLOWED_GRANULARITY else 4
    return [(s, min(24, s + g)) for s in range(0, 24, g)]


def _bucket_of(hour: int, buckets: list[tuple[int, int]]) -> Optional[tuple[int, int]]:
    for b in buckets:
        if b[0] <= hour < b[1]:
            return b
    return None


def _agg(trades: list[dict]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "wins": 0, "winRate": None, "netCents": 0.0, "t": None, "pnlUsd": 0.0}
    wins = sum(1 for t in trades if t.get("won"))
    pnl = sum(float(t["pnlUsd"]) for t in trades)
    contracts = sum(int(t.get("contracts", 1) or 1) for t in trades)
    net_cents = (pnl / contracts * 100.0) if contracts else 0.0
    t = _tstat(trades)
    return {"n": n, "wins": wins, "winRate": round(wins / n, 4),
            "netCents": round(net_cents, 3), "t": round(t, 2) if t is not None else None,
            "pnlUsd": round(pnl, 4)}


def optimize(coin: str, *, strategies: Optional[list[dict]] = None,
             granularity_h: int = 4, since_days: int = 30,
             min_trades: int = 12, min_trades_coin: int = 30,
             holdout: str = "auto", env: str = "production") -> dict:
    coin = (coin or "BTC").upper()
    if strategies is None:
        import strategy_generator
        imported, _ = turbine_import.import_all()
        strategies = [{"name": s["name"], "config": s["config"]} for s in imported]
        strategies += [{"name": g["name"], "config": g["config"]} for g in strategy_generator.generate()]
    buckets = _buckets(granularity_h)

    now = datetime.now(timezone.utc)
    holdout_days = 0
    if holdout != "off" and since_days >= 8:
        holdout_days = max(2, since_days // 3)
    cutoff = (now - timedelta(days=holdout_days)).strftime("%Y-%m-%d %H:%M:%S") if holdout_days else None

    windows = replay.load_windows(env, since_days)
    swept: list[dict] = []
    for s in strategies:
        cfg = replay._replay_cfg(merge_with_defaults(
            {**dict(s["config"]), "crypto15m_assets": [coin], "crypto15m_order_size": 1}))
        try:
            trades, _n = replay.replay_windows(windows, cfg)
        except Exception:
            continue
        time.sleep(0.001)
        train = [t for t in trades if cutoff is None or str(t.get("at") or "") < cutoff]
        test = [t for t in trades if cutoff is not None and str(t.get("at") or "") >= cutoff]
        swept.append({"name": s["name"], "config": s["config"], "trades": trades,
                      "train": train, "test": test})

    schedule: list[dict] = []
    for b in buckets:
        label = f"{b[0]:02d}:00"
        best = None
        for s in swept:
            bt = [t for t in s["train"] if (_bucket_of(_hour_of(t.get("at")) if _hour_of(t.get("at")) is not None else -1, buckets) == b)]
            a = _agg(bt)
            if a["n"] < min_trades:
                continue
            score = _rank_score(a["netCents"], a["t"], a["n"])
            if best is None or score > best["score"]:
                best = {"name": s["name"], "score": score, "train": a, "strategyRef": s}
        if best is None:
            schedule.append({"bucket": label, "start": b[0], "end": b[1], "winner": None,
                             "config": None, "train": None, "holdout": None})
            continue
        htrades = [t for t in best["strategyRef"]["test"]
                   if _bucket_of(_hour_of(t.get("at")) if _hour_of(t.get("at")) is not None else -1, buckets) == b]
        schedule.append({"bucket": label, "start": b[0], "end": b[1],
                         "winner": best["name"],
                         "config": best["strategyRef"]["config"],
                         "train": best["train"],
                         "holdout": _agg(htrades) if cutoff else None})

    coin_winner = None
    for s in swept:
        a = _agg(s["train"])
        if a["n"] < min_trades_coin:
            continue
        score = _rank_score(a["netCents"], a["t"], a["n"])
        if coin_winner is None or score > coin_winner["score"]:
            coin_winner = {"name": s["name"], "score": score, **a}

    assembled: list[dict] = []
    for row in schedule:
        if not row["winner"]:
            continue
        src = swept
        sref = next((s for s in src if s["name"] == row["winner"]), None)
        if not sref:
            continue
        pool = sref["test"] if cutoff else sref["train"]
        b = (row["start"], row["end"])
        assembled += [t for t in pool if _bucket_of(_hour_of(t.get("at")) if _hour_of(t.get("at")) is not None else -1, buckets) == b]
    assembled_stats = _agg(assembled)

    return {
        "coin": coin, "granularityH": granularity_h, "sinceDays": since_days,
        "holdoutDays": holdout_days, "strategiesSwept": len(swept),
        "schedule": schedule, "coinWinner": coin_winner,
        "assembled": assembled_stats,
        "caveat": ("Winners elected on train, scored on a held-out recent split." if cutoff
                   else "No holdout (need >=8 days) — results are in-sample; treat as anecdote."),
    }


def run_optimize(params: dict) -> dict:
    """Picklable entrypoint for the service process pool (params in, dict out).
    Resolves the optional strategy-name filter inside the worker; env is passed
    explicitly (a spawned worker doesn't share the parent's runtime env)."""
    strategies = None
    names = params.get("strategyNames")
    if names:
        import turbine_import
        wanted = set(names)
        imported, _ = turbine_import.import_all()
        strategies = [{"name": s["name"], "config": s["config"]}
                      for s in imported if s["name"] in wanted]
    return optimize(
        str(params.get("coin") or "BTC"),
        strategies=strategies,
        granularity_h=int(params.get("granularityH") or 4),
        since_days=int(params.get("sinceDays") or 30),
        min_trades=int(params.get("minTrades") or 12),
        min_trades_coin=int(params.get("minTradesCoin") or 30),
        holdout=str(params.get("holdout") or "auto"),
        env=str(params.get("env") or "production"),
    )
