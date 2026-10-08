"""Backtest the imported Turbine strategy library on OUR recorded ticks.

Runs each importable strategy through replay.replay (the live entry gate over
recorded ticks, held to settlement, fee-adjusted) and ranks them by
risk-adjusted net edge on our own data. Requires the trend/VWAP fields to be
present on the ticks — run crypto15m_backfill first, or the VWAP/momentum rules
match nothing (0 trades).
"""
from __future__ import annotations

import argparse
import json
import math
import time
from typing import Optional

import replay
import turbine_import
from config import merge_with_defaults


def _tstat(trades: list[dict]) -> Optional[float]:
    pnls = [float(t["pnlUsd"]) for t in trades]
    n = len(pnls)
    if n < 2:
        return None
    mean = sum(pnls) / n
    var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    if var <= 1e-6:
        return None
    t = mean / (math.sqrt(var) / math.sqrt(n))
    return max(-20.0, min(20.0, t))


_MIN_N = 15


def _rank_score(net_cents: float, t: Optional[float], n: int) -> float:
    """One-SE conservative lower bound on the edge (matches the Strategies page):
    net − |net|/t. Tiny samples are pushed to the bottom (a +15¢ edge on n=3 is
    noise, not a #1 strategy), and no t → treated as unproven."""
    if n is None or n < _MIN_N:
        return -100.0 + net_cents * 0.001
    if t is None or t == 0:
        return net_cents - abs(net_cents)
    return net_cents - abs(net_cents) / abs(t)


def run(env: str = "production", since_days: int = 90) -> list[dict]:
    imported, _skipped = turbine_import.import_all()
    out: list[dict] = []
    for item in imported:
        cfg = merge_with_defaults(dict(item["config"]))
        try:
            res = replay.replay(cfg, env=env, since_days=since_days)
        except Exception as e:
            out.append({**_meta(item), "error": str(e)[:120]})
            continue
        time.sleep(0.001)
        trades = res.get("trades") or []
        t = _tstat(trades)
        net = float(res.get("netEvCentsPerContract") or 0.0)
        out.append({
            **_meta(item),
            "n": res.get("n", 0),
            "winRate": res.get("winRate"),
            "netCentsPerContract": round(net, 3),
            "totalPnlUsd": res.get("totalPnlUsd"),
            "t": round(t, 2) if t is not None else None,
            "rankScore": round(_rank_score(net, t, res.get("n", 0)), 3),
            "windowsScanned": res.get("windowsScanned", 0),
        })
    out.sort(key=lambda r: r.get("rankScore", -999), reverse=True)
    return out


def _meta(item: dict) -> dict:
    tb = item.get("turbine") or {}
    return {"name": item["name"], "asset": item["asset"],
            "archetype": item["archetype"], "turbineNetPnl": tb.get("netPnl"),
            "turbineWinPct": tb.get("winPct")}


def run_worker(params: dict) -> list:
    """Picklable entrypoint for the service process pool."""
    return run(env=str((params or {}).get("env") or "production"),
               since_days=int((params or {}).get("sinceDays") or 90))


def main() -> None:
    ap = argparse.ArgumentParser(description="Backtest the Turbine library on our data.")
    ap.add_argument("--env", default="production")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()
    ranked = run(args.env, args.days)
    if args.json:
        print(json.dumps(ranked, indent=1))
        return
    print(f"\n{'#':>2}  {'net¢/ct':>8} {'t':>6} {'n':>5} {'win%':>5}  {'arch':<16} name")
    print("-" * 92)
    for i, r in enumerate(ranked, 1):
        if r.get("error"):
            print(f"{i:>2}  {'ERR':>8}  {r['error']}")
            continue
        wr = f"{r['winRate']*100:.0f}" if r.get("winRate") is not None else "-"
        t = f"{r['t']:.1f}" if r.get("t") is not None else "-"
        print(f"{i:>2}  {r['netCentsPerContract']:>8.2f} {t:>6} {r['n']:>5} {wr:>5}  "
              f"{r['archetype']:<16} {r['name']}")
    n_sig = sum(1 for r in ranked if r.get("t") and abs(r["t"]) >= 2 and r["n"] >= 30 and r["netCentsPerContract"] > 0)
    print(f"\n{len(ranked)} strategies · {n_sig} significant (+edge, |t|>=2, n>=30) on {args.days}d of {args.env} data")


if __name__ == "__main__":
    main()
