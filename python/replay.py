from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Optional

import backtest as bt
import capturetrail as ct
import crypto15m
import crypto15m_trader
import db as dbmod

_DERIVABLE = {
    "hasMarket", "favorite", "favoritePrice", "entryCost", "minsLeft",
    "inWindow", "signal", "modelProb", "edgeNetCents", "settlePrints",
    "upAsk", "downAsk", "yesBid", "yesAsk", "upProb", "downProb",
    "deltaPct", "deltaSignedPct", "sigma1m", "spotUsd", "strikeUsd",
    "macd", "macdSignal", "macdHist", "macdCross", "rsi", "hourUtc",
    "closeTime", "ticker", "asset", "series",
    "vwap1h", "ema12", "sma20", "sma50", "priceVsVwapPct", "ema12VsSma20Pct",
    "ema1VsSma5Pct", "velocity1mPct", "change5mPct", "change15mPct",
}


def tick_to_asset(row: dict, cfg: dict, close_iso: str) -> dict:
    up_prob = row.get("up_prob")
    yes_bid, yes_ask = row.get("yes_bid"), row.get("yes_ask")
    no_ask = row.get("no_ask")
    if no_ask is None and yes_bid is not None:
        no_ask = round(1.0 - float(yes_bid), 4)
    fav = None
    fav_price = None
    if up_prob is not None:
        fav = "up" if float(up_prob) >= 0.5 else "down"
        fav_price = float(up_prob) if fav == "up" else 1.0 - float(up_prob)
    ml = row.get("mins_left")
    in_window = (
        ml is not None
        and 1.0 <= float(ml) <= float(crypto15m._const(cfg, "time_delay_min"))
    )
    hour = None
    ts = row.get("observed_at") or ""
    try:
        hour = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S").hour
    except Exception:
        pass
    entry_cost = None
    if fav == "up":
        entry_cost = yes_ask
    elif fav == "down":
        entry_cost = no_ask
    strict = bool(cfg.get("crypto15m_strict_threshold", True))
    two_sided = bool(yes_bid and yes_ask)
    min_dp = crypto15m._const(cfg, "min_delta_pct")
    ds = row.get("delta_signed_pct")
    if ds is None or min_dp <= 0:
        delta_ok = True
    elif fav == "up":
        delta_ok = float(ds) >= min_dp
    else:
        delta_ok = float(ds) <= -min_dp
    signal = bool(
        in_window
        and fav_price is not None
        and fav_price >= crypto15m._const(cfg, "entry_threshold")
        and entry_cost is not None
        and float(entry_cost) <= crypto15m._const(cfg, "entry_max")
        and delta_ok
        and (hour is None or crypto15m.hours_ok(cfg, hour=hour))
        and (not strict or (two_sided and float(entry_cost) >= crypto15m._const(cfg, "entry_threshold")))
    )
    return {
        "asset": row.get("asset"), "ticker": row.get("ticker"),
        "series": f"KX{row.get('asset')}15M", "hasMarket": True,
        "closeTime": close_iso,
        "favorite": fav, "favoritePrice": fav_price, "entryCost": entry_cost,
        "minsLeft": float(ml) if ml is not None else None,
        "inWindow": in_window, "signal": signal, "hourUtc": hour,
        "modelProb": row.get("model_prob"),
        "edgeNetCents": row.get("edge_net_cents"),
        "settlePrints": int(row.get("settle_prints") or 0),
        "upAsk": yes_ask, "downAsk": no_ask,
        "yesBid": yes_bid, "yesAsk": yes_ask,
        "upProb": up_prob,
        "downProb": (1.0 - float(up_prob)) if up_prob is not None else None,
        "deltaPct": row.get("delta_pct"),
        "deltaSignedPct": row.get("delta_signed_pct"),
        "sigma1m": row.get("sigma1m"),
        "spotUsd": row.get("spot"), "strikeUsd": row.get("strike"),
        "macd": row.get("macd"), "macdSignal": row.get("macd_signal"),
        "macdHist": row.get("macd_hist"), "macdCross": row.get("macd_cross"),
        "rsi": row.get("rsi"),
        "vwap1h": row.get("vwap1h"), "ema12": row.get("ema12"),
        "sma20": row.get("sma20"), "sma50": row.get("sma50"),
        "priceVsVwapPct": row.get("price_vs_vwap_pct"),
        "ema12VsSma20Pct": row.get("ema12_vs_sma20_pct"),
        "ema1VsSma5Pct": row.get("ema1_vs_sma5_pct"),
        "velocity1mPct": row.get("velocity1m_pct"),
        "change5mPct": row.get("change5m_pct"),
        "change15mPct": row.get("change15m_pct"),
    }


def _missing_rule_fields(cfg: dict) -> list[str]:
    if not cfg.get("crypto15m_use_rules"):
        return []
    fields = {str(c.get("field")) for c in (cfg.get("crypto15m_rules") or [])}
    return sorted(fields - _DERIVABLE)


def load_windows(env: str, since_days: int) -> dict[str, list[dict]]:
    with dbmod.get_db() as conn:
        rows = conn.execute(
            """SELECT t.*, s.up_won, s.close_time AS sig_close
               FROM crypto15m_ticks t
               JOIN crypto15m_signals s
                 ON s.ticker = t.ticker AND s.kalshi_env = t.kalshi_env
               WHERE s.resolved = 1 AND s.up_won IS NOT NULL
                 AND t.kalshi_env = ?
                 AND t.observed_at >= datetime('now', ?)
               ORDER BY t.ticker, t.observed_at""",
            (env, f"-{int(since_days)} days"),
        ).fetchall()
    by_window: dict[str, list[dict]] = {}
    for r in rows:
        by_window.setdefault(r["ticker"], []).append(dict(r))
    return by_window


def replay_windows(by_window: dict[str, list[dict]], cfg: dict) -> tuple[list[dict], int]:
    contracts = max(1, int(cfg.get("crypto15m_order_size") or 1))
    trades: list[dict] = []
    n_windows = 0
    for ticker, ticks in by_window.items():
        if not crypto15m.asset_enabled(cfg, str(ticks[0].get("asset") or "")):
            continue
        n_windows += 1
        up_won = int(ticks[0].get("up_won") or 0)
        close_iso = str(ticks[0].get("sig_close") or "")
        for t in ticks:
            asset = tick_to_asset(t, cfg, close_iso)
            try:
                ok, _why = crypto15m_trader.should_enter(
                    asset, cfg, has_open=False, open_count=0,
                )
            except Exception:
                ok = False
            if not ok:
                continue
            side = crypto15m_trader._bought_side(asset, cfg)
            if side not in ("up", "down"):
                break
            cost = asset["upAsk"] if side == "up" else asset["downAsk"]
            if not cost or not (0.0 < float(cost) < 1.0):
                break
            cost = float(cost)
            fee = bt.kalshi_fee_per_contract(cost, contracts=contracts)
            won = up_won if side == "up" else (1 - up_won)
            pnl_ct = (1.0 - cost - fee) if won else (-cost - fee)
            trades.append({
                "ticker": ticker, "asset": asset["asset"], "side": side,
                "costCents": round(cost * 100, 1),
                "minsLeft": asset["minsLeft"], "won": bool(won),
                "pnlUsd": round(pnl_ct * contracts, 4),
                "at": t.get("observed_at"),
            })
            break
    return trades, n_windows


def _replay_cfg(cfg: dict) -> dict:
    cfg = dict(cfg)
    cfg["crypto15m_enabled"] = True
    cfg["crypto15m_model_autopause"] = False
    return cfg


def replay(cfg: dict, *, env: str = "production", since_days: int = 60,
           max_concurrent_ignored: bool = True) -> dict:
    cfg = _replay_cfg(cfg)
    contracts = max(1, int(cfg.get("crypto15m_order_size") or 1))
    by_window = load_windows(env, since_days)
    trades, n_windows = replay_windows(by_window, cfg)

    caveats = [
        "Entries fill at the recorded ask (taker); real fills can be worse and marketable orders sometimes miss entirely.",
        "Positions are held to settlement — stop-loss/take-profit exits are NOT simulated.",
        f"Ticks are 4-25s apart over {since_days} days of app uptime only; the gate could have fired between ticks.",
        "In-sample: any threshold tuned against this panel is fit to the past. Paper-trade before arming.",
        "Live model-calibration auto-pause is NOT simulated — live trading can pause where this replay keeps trading.",
    ]
    missing = _missing_rule_fields(cfg)
    if missing:
        caveats.insert(0, (
            "Rules reference fields not recorded in ticks — those conditions "
            f"never match in replay (0 trades is expected): {', '.join(missing)}"
        ))
    return _summarize(trades, contracts, n_windows, caveats)


def _held_bid(row: dict, side: str) -> Optional[float]:
    if side == "up":
        b = row.get("yes_bid")
        return float(b) if b and 0.0 < float(b) < 1.0 else None
    ya = row.get("yes_ask")
    if ya and 0.0 < float(ya) < 1.0:
        return round(1.0 - float(ya), 4)
    return None


def _simulate_capturetrail(ticks: list[dict], entry_i: int, side: str,
                           cost: float, params: ct.CTParams,
                           contracts: int) -> Optional[dict]:
    state = ct.CTState.open(cost)
    for row in ticks[entry_i + 1:]:
        bid = _held_bid(row, side)
        if bid is None:
            continue
        done, reason = ct.step(state, bid, params)
        if done:
            return {"price": bid, "at": row.get("observed_at"), "reason": reason}
    return None


def replay_capturetrail(cfg: dict, *, env: str = "production",
                        since_days: int = 60) -> dict:
    cfg = dict(cfg)
    cfg["crypto15m_enabled"] = True
    cfg["crypto15m_model_autopause"] = False
    params = ct.params_from_cfg(cfg, "crypto15m")
    contracts = max(1, int(cfg.get("crypto15m_order_size") or 1))

    with dbmod.get_db() as conn:
        rows = conn.execute(
            """SELECT t.*, s.up_won, s.close_time AS sig_close
               FROM crypto15m_ticks t
               JOIN crypto15m_signals s
                 ON s.ticker = t.ticker AND s.kalshi_env = t.kalshi_env
               WHERE s.resolved = 1 AND s.up_won IS NOT NULL
                 AND t.kalshi_env = ?
                 AND t.observed_at >= datetime('now', ?)
               ORDER BY t.ticker, t.observed_at""",
            (env, f"-{int(since_days)} days"),
        ).fetchall()

    by_window: dict[str, list[dict]] = {}
    for r in rows:
        by_window.setdefault(r["ticker"], []).append(dict(r))

    base_trades: list[dict] = []
    ct_trades: list[dict] = []
    n_windows = 0
    n_ct_exits = 0
    reasons: dict[str, int] = {}
    for ticker, ticks in by_window.items():
        if not crypto15m.asset_enabled(cfg, str(ticks[0].get("asset") or "")):
            continue
        n_windows += 1
        up_won = int(ticks[0].get("up_won") or 0)
        close_iso = str(ticks[0].get("sig_close") or "")
        for i, t in enumerate(ticks):
            asset = tick_to_asset(t, cfg, close_iso)
            try:
                ok, _why = crypto15m_trader.should_enter(
                    asset, cfg, has_open=False, open_count=0,
                )
            except Exception:
                ok = False
            if not ok:
                continue
            side = crypto15m_trader._bought_side(asset, cfg)
            if side not in ("up", "down"):
                break
            cost = asset["upAsk"] if side == "up" else asset["downAsk"]
            if not cost or not (0.0 < float(cost) < 1.0):
                break
            cost = float(cost)
            fee_in = bt.kalshi_fee_per_contract(cost, contracts=contracts)
            won = up_won if side == "up" else (1 - up_won)

            base_pnl = (1.0 - cost - fee_in) if won else (-cost - fee_in)
            base_trades.append({
                "ticker": ticker, "asset": asset["asset"], "side": side,
                "costCents": round(cost * 100, 1), "minsLeft": asset["minsLeft"],
                "won": bool(won), "pnlUsd": round(base_pnl * contracts, 4),
                "at": t.get("observed_at"),
            })

            exit_leg = _simulate_capturetrail(ticks, i, side, cost, params, contracts)
            if exit_leg is not None:
                px = float(exit_leg["price"])
                fee_out = bt.kalshi_fee_per_contract(px, contracts=contracts)
                ct_pnl = px - cost - fee_in - fee_out
                n_ct_exits += 1
                reasons[exit_leg["reason"]] = reasons.get(exit_leg["reason"], 0) + 1
                ct_trades.append({
                    "ticker": ticker, "asset": asset["asset"], "side": side,
                    "costCents": round(cost * 100, 1), "minsLeft": asset["minsLeft"],
                    "won": ct_pnl > 0, "pnlUsd": round(ct_pnl * contracts, 4),
                    "at": t.get("observed_at"), "reason": exit_leg["reason"],
                    "exitCents": round(px * 100, 1),
                })
            else:
                ct_trades.append({**base_trades[-1], "reason": "settled"})
            break

    base_caveats = [
        "Baseline holds every position to settlement (the live 15m default).",
        f"Ticks are 4-25s apart over {since_days} days of app uptime only.",
        "In-sample: any threshold tuned against this panel is fit to the past.",
    ]
    ct_caveats = [
        "CaptureTrail marks to the held-side BID (yes_bid / 1-yes_ask) — the "
        "position is down the spread from tick 1, and exits book at the bid.",
        "The trail only sees recorded ticks (4-25s apart); a real reversal "
        "between ticks would fill worse. Both legs pay Kalshi's per-order fee.",
        f"CaptureTrail exited {n_ct_exits} of {len(ct_trades)} trades early; "
        f"reasons: {reasons or 'none'}. The rest settled identically to baseline.",
    ] + base_caveats
    if not params.active():
        ct_caveats.insert(0, (
            "CaptureTrail is OFF or has no active trigger in this config — the "
            "two columns are identical. Set crypto15m_ct_enabled + a reversal_pct."
        ))

    base = _summarize(base_trades, contracts, n_windows, base_caveats)
    capt = _summarize(ct_trades, contracts, n_windows, ct_caveats)
    return {
        "baseline": base,
        "capturetrail": capt,
        "delta": {
            "totalPnlUsd": round(capt["totalPnlUsd"] - base["totalPnlUsd"], 2),
            "netEvCentsPerContract": round(
                capt["netEvCentsPerContract"] - base["netEvCentsPerContract"], 2),
            "winRate": round(capt["winRate"] - base["winRate"], 4),
            "maxDrawdownUsd": round(capt["maxDrawdownUsd"] - base["maxDrawdownUsd"], 2),
            "earlyExits": n_ct_exits,
            "exitReasons": reasons,
        },
        "params": {
            "enabled": params.enabled, "minArmPct": params.min_arm_pct,
            "unarmedStopPct": params.unarmed_stop_pct,
            "reversalPct": params.reversal_pct, "noisePct": params.noise_pct,
            "override": params.override,
        },
    }


def _bucketize(trades: list[dict]) -> dict:
    by_hour = {h: {"n": 0, "wins": 0, "pnlUsd": 0.0} for h in range(24)}
    by_day: dict[str, dict] = {}
    for t in trades:
        ts = str(t.get("at") or "")
        try:
            hour = int(ts[11:13])
        except (ValueError, IndexError):
            hour = None
        day = ts[:10] if len(ts) >= 10 else None
        if hour is not None:
            b = by_hour[hour]
            b["n"] += 1
            b["wins"] += 1 if t["won"] else 0
            b["pnlUsd"] = round(b["pnlUsd"] + t["pnlUsd"], 4)
        if day:
            d = by_day.setdefault(day, {"n": 0, "wins": 0, "pnlUsd": 0.0})
            d["n"] += 1
            d["wins"] += 1 if t["won"] else 0
            d["pnlUsd"] = round(d["pnlUsd"] + t["pnlUsd"], 4)
    return {
        "byHourUtc": [{"hour": h, **by_hour[h]} for h in range(24)],
        "byDay": [{"day": d, **v} for d, v in sorted(by_day.items())],
    }


def _summarize(trades: list[dict], contracts: int, n_windows: int,
               caveats: list[str]) -> dict:
    trades = sorted(trades, key=lambda t: str(t.get("at") or ""))
    n = len(trades)
    wins = sum(1 for t in trades if t["won"])
    total = sum(t["pnlUsd"] for t in trades)
    denom = sum(int(t.get("contracts", contracts) or contracts) for t in trades)
    ev_ct = (total / denom * 100.0) if denom else 0.0
    by_asset: dict[str, dict] = {}
    for t in trades:
        a = by_asset.setdefault(t.get("asset") or "?", {"n": 0, "wins": 0, "pnlUsd": 0.0})
        a["n"] += 1
        a["wins"] += 1 if t["won"] else 0
        a["pnlUsd"] = round(a["pnlUsd"] + t["pnlUsd"], 4)
    equity, run = [], 0.0
    for t in trades:
        run += t["pnlUsd"]
        equity.append({"at": t.get("at"), "value": round(run, 4)})
    max_dd, peak = 0.0, 0.0
    for e in equity:
        peak = max(peak, e["value"])
        max_dd = min(max_dd, e["value"] - peak)
    if n < 30:
        caveats = [f"Only {n} trades - far too few for a verdict; treat as anecdote."] + list(caveats)
    return {
        "n": n, "wins": wins,
        "winRate": round(wins / n, 4) if n else 0.0,
        "netEvCentsPerContract": round(ev_ct, 2),
        "totalPnlUsd": round(total, 2),
        "maxDrawdownUsd": round(max_dd, 2),
        "contracts": contracts,
        "windowsScanned": n_windows,
        "byAsset": by_asset,
        "equity": equity[-400:],
        "trades": trades[-50:],
        "caveats": caveats,
        **_bucketize(trades),
    }


def replay_main(cfg: dict, *, since_days: int = 60,
                slippage_cents: float = 1.0) -> dict:
    import trader as trader_mod
    contracts = 5
    fixed_usd = float(cfg.get("fixed_trade_usd") or 5.0)
    trades: list[dict] = []
    scanned = 0
    with dbmod.get_db() as conn:
        whales = conn.execute(
            """SELECT * FROM whale_trades WHERE resolved=1
               AND outcome_correct IS NOT NULL
               AND created_at >= datetime('now', ?)""",
            (f"-{int(since_days)} days",),
        ).fetchall()
        alerts = conn.execute(
            """SELECT * FROM alerts WHERE resolved=1
               AND outcome_correct IS NOT NULL
               AND created_at >= datetime('now', ?)""",
            (f"-{int(since_days)} days",),
        ).fetchall()

    def _sim(sig: dict, source: str, price, won: bool) -> None:
        if price is None or not (0.0 < float(price) < 1.0):
            return
        cost = min(0.99, float(price) + slippage_cents / 100.0)
        n_ct = max(1, int(round(fixed_usd / max(cost, 0.01))))
        fee = bt.kalshi_fee_per_contract(cost, contracts=n_ct)
        pnl_ct = (1.0 - cost - fee) if won else (-cost - fee)
        trades.append({
            "ticker": sig.get("ticker"), "asset": sig.get("category") or source,
            "side": sig.get("taker_side") or sig.get("direction") or "?",
            "costCents": round(cost * 100, 1), "minsLeft": None,
            "won": bool(won), "pnlUsd": round(pnl_ct * n_ct, 4),
            "contracts": n_ct,
            "at": sig.get("created_at"),
        })

    for r in whales:
        sig = dict(r)
        scanned += 1
        try:
            ok, _why = trader_mod.should_trade(sig, "whale", cfg)
        except Exception:
            ok = False
        if not ok:
            continue
        _sim(sig, "whale", sig.get("price"), bool(sig.get("outcome_correct")))
    for r in alerts:
        sig = dict(r)
        scanned += 1
        try:
            ok, _why = trader_mod.should_trade(sig, "momentum", cfg)
        except Exception:
            ok = False
        if not ok:
            continue
        price = sig.get("price")
        if (sig.get("direction") or "yes").lower() == "no" and price is not None:
            price = 1.0 - float(price)
        _sim(sig, "momentum", price, bool(sig.get("outcome_correct")))

    caveats = [
        f"Follower economics: entry at the signal price +{slippage_cents:.0f}c slippage - live fills on fast markets can be worse.",
        "One simulated trade per accepted signal; live caps (max open, per-event, daily) are NOT applied, so hot events stack correlated trades.",
        "Whale outcomes cluster (one game prints many whale signals) - day/hour buckets share that clustering.",
        "In-sample: signals were only recorded while the app was running.",
        "contrarianOnly and maxResolutionDays are NOT re-simulated: alerts inherit whatever filter was live when they were RECORDED (contrarianOnly gates at record time), and signal rows carry no close_time for the resolution-days gate to read.",
    ]
    return _summarize(trades, contracts, scanned, caveats)
