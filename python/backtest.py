from __future__ import annotations

import argparse
import math
import os
import sqlite3
import sys
from pathlib import Path
from typing import Optional

DEFAULT_FEE_COEFF = 0.07




def kalshi_fee_per_contract(
    price: float, fee_coeff: float = DEFAULT_FEE_COEFF,
    contracts: Optional[int] = None,
) -> float:
    p = max(0.0, min(1.0, float(price)))
    raw = fee_coeff * p * (1.0 - p)
    if not contracts or contracts <= 0:
        return raw
    return math.ceil(raw * contracts * 100.0) / 100.0 / contracts


def net_pnl_per_contract(
    cost: float, correct: bool, fee_coeff: float = DEFAULT_FEE_COEFF,
    contracts: Optional[int] = None,
) -> float:
    gross = (1.0 - cost) if correct else (-cost)
    return gross - kalshi_fee_per_contract(cost, fee_coeff, contracts)


def signal_cost(row: dict, source: str) -> float:
    price = float(row.get("price") or 0.0)
    if source == "whale":
        return max(0.0, min(1.0, price))
    direction = (row.get("direction") or "yes").lower()
    cost = price if direction == "yes" else (1.0 - price)
    return max(0.0, min(1.0, cost))




def summarize(
    signals: list[dict], fee_coeff: float = DEFAULT_FEE_COEFF,
    contracts: Optional[int] = None,
) -> dict:
    n = len(signals)
    if n == 0:
        return {"n": 0, "wins": 0, "win_rate": 0.0, "gross_ev": 0.0,
                "fee_ev": 0.0, "net_ev": 0.0, "se": 0.0, "t": 0.0,
                "total_net": 0.0, "avg_cost": 0.0, "net_roi": 0.0}

    nets, grosses, fees = [], [], []
    wins = 0
    for s in signals:
        cost, correct = s["cost"], bool(s["correct"])
        if correct:
            wins += 1
        grosses.append((1.0 - cost) if correct else (-cost))
        fees.append(kalshi_fee_per_contract(cost, fee_coeff, contracts))
        nets.append(net_pnl_per_contract(cost, correct, fee_coeff, contracts))

    mean_net = sum(nets) / n
    var = sum((x - mean_net) ** 2 for x in nets) / (n - 1) if n > 1 else 0.0
    sd = math.sqrt(var)
    se = sd / math.sqrt(n) if n > 0 else 0.0
    avg_cost = sum(s["cost"] for s in signals) / n
    return {
        "n": n, "wins": wins, "win_rate": wins / n,
        "gross_ev": sum(grosses) / n,
        "fee_ev": sum(fees) / n,
        "net_ev": mean_net,
        "se": se,
        "t": (mean_net / se) if se > 0 else 0.0,
        "total_net": sum(nets),
        "avg_cost": avg_cost,
        "net_roi": (mean_net / avg_cost) if avg_cost > 0 else 0.0,
    }


def threshold_sweep(
    signals: list[dict], thresholds: list[float], fee_coeff: float = DEFAULT_FEE_COEFF
) -> list[dict]:
    out = []
    for th in thresholds:
        sub = [s for s in signals if s["confidence"] >= th]
        out.append({"threshold": th, **summarize(sub, fee_coeff)})
    return out


PRICE_BUCKETS = [
    (0.00, 0.30, "<30c"), (0.30, 0.50, "30-50c"), (0.50, 0.70, "50-70c"),
    (0.70, 0.85, "70-85c"), (0.85, 1.01, "85c+"),
]


def _price_label(cost: float) -> str:
    for lo, hi, label in PRICE_BUCKETS:
        if lo <= cost < hi:
            return label
    return "?"


def summarize_fade(signals: list[dict], fee_coeff: float = DEFAULT_FEE_COEFF) -> dict:
    faded = [{"cost": 1.0 - s["cost"], "correct": (not s["correct"]),
              "confidence": s["confidence"]} for s in signals]
    return summarize(faded, fee_coeff)


def group_summaries(signals: list[dict], key, fee_coeff: float = DEFAULT_FEE_COEFF) -> dict:
    groups: dict[str, list] = {}
    for s in signals:
        groups.setdefault(key(s), []).append(s)
    return {k: summarize(v, fee_coeff) for k, v in groups.items()}


def format_breakdown(signals: list[dict], fee_coeff: float) -> str:
    L = ["", "════════════ BREAKDOWN ════════════"]
    for src in ("whale", "momentum"):
        sub = [s for s in signals if s["source"] == src]
        if not sub:
            continue
        L.append("")
        L.append(f"── {src.upper()}  (n={len(sub)}) ──")
        L.append("  by entry price:")
        pb = group_summaries(sub, lambda s: _price_label(s["cost"]), fee_coeff)
        for _, _, label in PRICE_BUCKETS:
            if label in pb:
                r = pb[label]
                L.append(f"    {label:<7} n={r['n']:<5} win {r['win_rate']*100:4.0f}%  "
                         f"net {_money(r['net_ev'])} (t={r['t']:+.1f})")
        cb = group_summaries([s for s in sub if s["category"]], lambda s: s["category"], fee_coeff)
        if cb:
            L.append("  by category (top 6 by n):")
            for cat, r in sorted(cb.items(), key=lambda kv: -kv[1]["n"])[:6]:
                L.append(f"    {cat:<13} n={r['n']:<5} win {r['win_rate']*100:4.0f}%  "
                         f"net {_money(r['net_ev'])} (t={r['t']:+.1f})")
        follow = summarize(sub, fee_coeff)["net_ev"]
        fade = summarize_fade(sub, fee_coeff)
        L.append(f"  FADE (bet opposite): net {_money(fade['net_ev'])} (t={fade['t']:+.1f})   "
                 f"vs follow {_money(follow)}")
    return "\n".join(L)


def verdict(overall: dict, sweep: list[dict]) -> str:
    if overall["n"] < 30:
        return ("INCONCLUSIVE — too few resolved signals (need ~100+). "
                "Run the bot longer to accumulate data.")
    best = max(
        (r for r in sweep if r["n"] >= 30), key=lambda r: r["net_ev"], default=None
    )
    if overall["net_ev"] > 0 and overall["t"] > 2:
        return "POSITIVE net-of-fee edge, and statistically significant. Worth hardening."
    if best and best["net_ev"] > 0 and best["t"] > 2:
        return (f"Net edge appears only when filtered to confidence >= {best['threshold']:.0f} "
                f"(net +${best['net_ev']:.4f}/contract, t={best['t']:.1f}). Tighten the gate.")
    if overall["net_ev"] > 0:
        return ("Marginally positive but WITHIN NOISE (t < 2). Not yet distinguishable "
                "from zero — need more data or a real edge.")
    return ("NEGATIVE after fees. The signals do not have a net-of-fee edge as configured — "
            "fix the strategy/fees before trading real money.")




def load_resolved_signals(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    out: list[dict] = []
    for src, table in (("whale", "whale_trades"), ("momentum", "alerts")):
        try:
            rows = conn.execute(
                f"SELECT * FROM {table} "
                f"WHERE resolved=1 AND outcome_correct IS NOT NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            continue
        for raw in rows:
            r = dict(raw)
            out.append({
                "source": src,
                "confidence": float(r.get("confidence") or 0.0),
                "cost": signal_cost(r, src),
                "correct": int(r["outcome_correct"]) == 1,
                "category": r.get("category") or "",
            })
    return out


def resolve_db_path(arg_db: Optional[str]) -> Path:
    if arg_db:
        return Path(arg_db)
    env = os.environ.get("KRYPT_TRADER_USERDATA")
    if env:
        return Path(env) / "data" / "krypt-trader.db"
    appdata = os.environ.get("APPDATA")
    if appdata:
        p = Path(appdata) / "Krypt Trader" / "data" / "krypt-trader.db"
        if p.exists():
            return p
    return Path(__file__).resolve().parent / "data" / "krypt-trader.db"




def build_report(signals: list[dict], fee_coeff: float) -> dict:
    thresholds = [50, 55, 60, 65, 70, 75, 80, 85, 90]
    overall = summarize(signals, fee_coeff)
    by_source = {
        src: summarize([s for s in signals if s["source"] == src], fee_coeff)
        for src in ("whale", "momentum")
    }
    sweep = threshold_sweep(signals, thresholds, fee_coeff)
    return {
        "overall": overall, "by_source": by_source, "sweep": sweep,
        "verdict": verdict(overall, sweep), "fee_coeff": fee_coeff,
    }


def _money(x: float) -> str:
    return f"{'+' if x >= 0 else '-'}${abs(x):.4f}"


def format_report(report: dict, source_label: str) -> str:
    o = report["overall"]
    L = []
    L.append("═══ Krypt Trader — fee-aware signal backtest ═══")
    L.append(f"source: {source_label}")
    L.append(f"fee model: {report['fee_coeff']:.3f} × C × P × (1−P)   "
             f"(continuous; verify vs Kalshi's current fee schedule)")
    n_w = sum(1 for k in ('whale',) for _ in [0]) if False else report['by_source']['whale']['n']
    n_m = report['by_source']['momentum']['n']
    L.append(f"resolved signals: {o['n']}  (whale {n_w}, momentum {n_m})")
    L.append("")
    if o["n"] == 0:
        L.append("No resolved signals found. Run the bot (even in demo/dry-run) long")
        L.append("enough for signals to settle, then re-run this backtest.")
        return "\n".join(L)

    L.append("OVERALL (1 contract per signal)")
    L.append(f"  win rate            {o['win_rate']*100:5.1f}%")
    L.append(f"  gross edge/contract {_money(o['gross_ev'])}")
    L.append(f"  fees/contract       {_money(-o['fee_ev'])}")
    L.append(f"  NET edge/contract   {_money(o['net_ev'])}   (t = {o['t']:+.1f})")
    L.append(f"  net ROI on cost     {o['net_roi']*100:+.1f}%")
    L.append(f"  total net P&L       {_money(o['total_net'])}")
    L.append("")
    L.append("BY SOURCE")
    for src in ("whale", "momentum"):
        s = report["by_source"][src]
        if s["n"] == 0:
            L.append(f"  {src:<9} (none)")
            continue
        L.append(f"  {src:<9} n={s['n']:<5} win {s['win_rate']*100:4.0f}%  "
                 f"gross {_money(s['gross_ev'])}  fee {_money(-s['fee_ev'])}  "
                 f"net {_money(s['net_ev'])} (t={s['t']:+.1f})")
    L.append("")
    L.append("CONFIDENCE THRESHOLD SWEEP")
    L.append("  conf≥   n      win    net/contract   t")
    for r in report["sweep"]:
        if r["n"] == 0:
            continue
        L.append(f"  {r['threshold']:>4.0f}   {r['n']:<6} {r['win_rate']*100:4.0f}%   "
                 f"{_money(r['net_ev']):>9}     {r['t']:+.1f}")
    L.append("")
    L.append(f"VERDICT: {report['verdict']}")
    return "\n".join(L)




def demo_signals(n: int = 4000, seed: int = 42) -> list[dict]:
    import random
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        src = "whale" if rng.random() < 0.6 else "momentum"
        cost = rng.uniform(0.18, 0.88)
        edge = rng.gauss(0.012, 0.035)
        true_prob = max(0.02, min(0.98, cost + edge))
        correct = rng.random() < true_prob
        confidence = max(5.0, min(97.0, true_prob * 100 + rng.gauss(0, 6)))
        out.append({"source": src, "confidence": confidence, "cost": cost,
                    "correct": correct, "category": ""})
    return out




def load_crypto15m_signals(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM crypto15m_signals WHERE resolved=1 AND up_won IS NOT NULL"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    out: list[dict] = []
    for raw in rows:
        r = dict(raw)
        fav = (r.get("favorite") or "").lower()
        if fav not in ("up", "down"):
            continue
        up_won = int(r["up_won"]) == 1
        fav_won = (fav == "up" and up_won) or (fav == "down" and not up_won)
        try:
            fav_price = float(r.get("favorite_price") or 0.0)
        except (TypeError, ValueError):
            fav_price = 0.0
        try:
            entry_cost = float(r.get("entry_cost") or fav_price)
        except (TypeError, ValueError):
            entry_cost = fav_price
        dp = r.get("delta_pct")
        out.append({
            "favorite": fav,
            "favorite_price": max(0.0, min(1.0, fav_price)),
            "entry_cost": max(0.0, min(1.0, entry_cost)),
            "fav_won": fav_won,
            "delta_pct": float(dp) if dp is not None else None,
            "mins_left": float(r["mins_left"]) if r.get("mins_left") is not None else None,
        })
    return out



def crypto15m_eval(
    signals: list[dict], *, mode: str = "favorite", min_fav: float = 0.0,
    max_fav: float = 1.0, min_delta_pct: float = 0.0,
    fee_coeff: float = DEFAULT_FEE_COEFF,
) -> dict:
    built: list[dict] = []
    for s in signals:
        fp = s["favorite_price"]
        if fp < min_fav or fp > max_fav:
            continue
        if min_delta_pct > 0:
            dp = s["delta_pct"]
            if dp is None or dp * 100.0 < min_delta_pct:
                continue
        if mode == "contrarian":
            cost = max(0.0, min(1.0, 1.0 - fp))
            correct = not s["fav_won"]
        else:
            cost = s["entry_cost"]
            correct = s["fav_won"]
        built.append({"cost": cost, "correct": correct, "confidence": fp * 100.0})
    return summarize(built, fee_coeff, contracts=1)


_FAV_THRESHOLDS = [50, 60, 70, 80, 85, 90, 95]
_DELTA_THRESHOLDS = [0.0, 0.05, 0.10, 0.20, 0.40]
_FAV_BANDS = [(50, 70), (70, 80), (80, 85), (85, 90), (90, 95), (95, 100)]


def crypto15m_report(signals: list[dict], fee_coeff: float = DEFAULT_FEE_COEFF) -> dict:
    favorite = {"mode": "favorite", **crypto15m_eval(signals, mode="favorite", fee_coeff=fee_coeff)}
    contrarian = {"mode": "contrarian", **crypto15m_eval(signals, mode="contrarian", fee_coeff=fee_coeff)}
    fav_sweep = [
        {"threshold": th, "mode": "favorite",
         **crypto15m_eval(signals, mode="favorite", min_fav=th / 100.0, fee_coeff=fee_coeff)}
        for th in _FAV_THRESHOLDS
    ]
    delta_sweep = [
        {"minDeltaPct": d, "mode": "favorite",
         **crypto15m_eval(signals, mode="favorite", min_delta_pct=d, fee_coeff=fee_coeff)}
        for d in _DELTA_THRESHOLDS
    ]
    band_sweep = [
        {"minFav": lo, "maxFav": hi, "mode": "favorite",
         **crypto15m_eval(signals, mode="favorite", min_fav=lo / 100.0,
                          max_fav=hi / 100.0, fee_coeff=fee_coeff)}
        for lo, hi in _FAV_BANDS
    ]
    candidates = [favorite, contrarian, *fav_sweep, *delta_sweep, *band_sweep]
    best = max(
        (c for c in candidates if c.get("n", 0) >= 30),
        key=lambda c: c["net_ev"], default=None,
    )
    return {
        "n": len(signals),
        "favorite": favorite,
        "contrarian": contrarian,
        "favoriteSweep": fav_sweep,
        "deltaSweep": delta_sweep,
        "bandSweep": band_sweep,
        "best": best,
        "fee_coeff": fee_coeff,
        "verdict": _crypto15m_verdict(len(signals), favorite, contrarian, best),
    }


def _crypto15m_verdict(n: int, favorite: dict, contrarian: dict, best: dict | None) -> str:
    if n < 30:
        return (f"COLLECTING DATA — {n} settled 15m signals so far (need ~100+). "
                "Leave the app open; the recorder logs every quarter automatically.")
    if best and best["net_ev"] > 0 and best["t"] > 2:
        mode = best.get("mode", "favorite")
        th = best.get("threshold")
        dd = best.get("minDeltaPct")
        lo, hi = best.get("minFav"), best.get("maxFav")
        if th:
            tag = f"favorite-follow ≥ {th}¢"
        elif dd:
            tag = f"favorite-follow, Δ ≥ {dd}%"
        elif lo is not None and hi is not None:
            tag = f"favorite-follow {lo}–{hi}¢"
        else:
            tag = "favorite-follow" if mode == "favorite" else "contrarian-fade"
        return (f"Net edge found: {tag} → +{best['net_ev']*100:.1f}¢/contract "
                f"(t={best['t']:.1f}, n={best['n']}). Still in-sample — paper-trade it.")
    if max(favorite["net_ev"], contrarian["net_ev"]) > 0:
        return ("Marginally positive but WITHIN NOISE (t < 2). Keep collecting — "
                "not yet distinguishable from zero.")
    return ("NEGATIVE after fees so far. No 15m variant shows a net edge on your "
            "data yet — keep collecting and try the delta filter.")


def format_crypto15m_report(report: dict, source_label: str) -> str:
    fc = report["fee_coeff"]
    L = ["═══ Krypt Trader — 15-minute crypto backtest ═══",
         f"source: {source_label}",
         f"fee model: ceil({fc:.3f} × C × P × (1−P)) per order, C=1 "
         f"(matches the 1-lot default; Kalshi rounds each order's fee up to the cent)",
         f"settled 15m signals: {report['n']}", ""]
    if report["n"] == 0:
        L.append("No settled 15m signals yet. Leave the app open — the recorder logs")
        L.append("each quarter's favorite + outcome automatically, then re-run this.")
        return "\n".join(L)

    def line(label: str, r: dict) -> str:
        return (f"  {label:<22} n={r['n']:<5} win {r['win_rate']*100:4.0f}%  "
                f"net {_money(r['net_ev'])}/contract (t={r['t']:+.1f})")

    L.append("OVERALL (1 contract per signal)")
    L.append(line("favorite-follow", report["favorite"]))
    L.append(line("contrarian-fade", report["contrarian"]))
    L.append("")
    L.append("FAVORITE-FOLLOW by minimum favorite price")
    L.append("  fav≥   n      win    net/contract   t")
    for r in report["favoriteSweep"]:
        if r["n"] == 0:
            continue
        L.append(f"  {r['threshold']:>4}¢  {r['n']:<6} {r['win_rate']*100:4.0f}%   "
                 f"{_money(r['net_ev']):>9}     {r['t']:+.1f}")
    L.append("")
    L.append("FAVORITE-FOLLOW by favorite-price band (disjoint)")
    L.append("  band      n      win    net/contract   t")
    for r in report["bandSweep"]:
        if r["n"] == 0:
            continue
        L.append(f"  {r['minFav']:>2}-{r['maxFav']:<3}¢  {r['n']:<6} {r['win_rate']*100:4.0f}%   "
                 f"{_money(r['net_ev']):>9}     {r['t']:+.1f}")
    L.append("")
    L.append("FAVORITE-FOLLOW by minimum underlying delta")
    L.append("  Δ≥     n      win    net/contract   t")
    for r in report["deltaSweep"]:
        if r["n"] == 0:
            continue
        L.append(f"  {r['minDeltaPct']:>4}%  {r['n']:<6} {r['win_rate']*100:4.0f}%   "
                 f"{_money(r['net_ev']):>9}     {r['t']:+.1f}")
    L.append("")
    L.append(f"VERDICT: {report['verdict']}")
    return "\n".join(L)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Fee-aware Krypt Trader signal backtest")
    ap.add_argument("--db", help="path to krypt-trader.db (default: auto-detect)")
    ap.add_argument("--fee", type=float, default=DEFAULT_FEE_COEFF,
                    help=f"fee coefficient (default {DEFAULT_FEE_COEFF})")
    ap.add_argument("--demo", action="store_true",
                    help="run on synthetic data instead of your DB")
    ap.add_argument("--breakdown", action="store_true",
                    help="also break down by entry-price, category, and a fade check")
    ap.add_argument("--c15", action="store_true",
                    help="backtest the 15-minute crypto strategy (crypto15m_signals)")
    args = ap.parse_args()

    if args.c15:
        db_path = resolve_db_path(args.db)
        if not db_path.exists():
            print(f"DB not found at: {db_path}")
            return 1
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            sigs = load_crypto15m_signals(conn)
        finally:
            conn.close()
        print(format_crypto15m_report(crypto15m_report(sigs, args.fee), str(db_path)))
        return 0

    if args.demo:
        print("⚠  SYNTHETIC DEMO DATA — not your real signals.\n")
        signals = demo_signals()
        report = build_report(signals, args.fee)
        print(format_report(report, "synthetic demo (4000 signals)"))
        if args.breakdown:
            print(format_breakdown(signals, args.fee))
        return 0

    db_path = resolve_db_path(args.db)
    if not db_path.exists():
        print(f"DB not found at: {db_path}")
        print("Pass --db <path>, or run `python backtest.py --demo` to see the format.")
        return 1
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        signals = load_resolved_signals(conn)
    finally:
        conn.close()
    report = build_report(signals, args.fee)
    print(format_report(report, str(db_path)))
    if args.breakdown:
        print(format_breakdown(signals, args.fee))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
