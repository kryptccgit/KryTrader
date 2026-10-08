"""Backtest a user strategy script over the recorded tick corpus.

Same data, same fill honesty as `replay.py` (recorded-ask taker fills,
Kalshi fee curve with per-order round-up), but the entry decision comes from
the script's `decide(ctx)` instead of the built-in gates. Windows are
replayed in chronological close-time order so a stateful script sees history
the way it would live; `state` persists across the whole run and `on_start`
/ `on_fill` / `on_settle` fire at the equivalent points.

Structurally order-free: this module never imports kalshi_api and the
sandbox exposes no order functions — decide() returns data, the harness
does the accounting. A backtest cannot place an order by construction.
"""
from __future__ import annotations

import math
import time
from typing import Any, Optional

import backtest as bt
import crypto15m
import db as dbmod
import replay
import script_sandbox

MAX_RUN_SECS = 90.0
DECIDE_BUDGET_MS = 20.0


def sanitize_intent(raw: Any) -> tuple[Optional[dict], Optional[str]]:
    """Coerce whatever decide() returned into a clean order intent, or a
    human-readable rejection. Shared by backtest and the live engine so the
    two can never disagree on the contract."""
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        return None, f"decide() returned {type(raw).__name__}, expected dict or None"
    side = str(raw.get("side") or "").lower()
    if side not in ("up", "down"):
        return None, f"intent side must be 'up' or 'down', got {raw.get('side')!r}"
    price = raw.get("price")
    if price != "ask":
        try:
            price = int(price)
        except (TypeError, ValueError):
            return None, "intent price must be \"ask\" or an integer 1-99 (cents)"
        if not (1 <= price <= 99):
            return None, f"intent price {price}c out of range 1-99"
    out: dict[str, Any] = {"side": side, "price": price}
    if raw.get("size") is not None:
        try:
            size = int(raw["size"])
        except (TypeError, ValueError):
            return None, "intent size must be an integer"
        if size < 1:
            return None, f"intent size {size} must be >= 1"
        out["size"] = size
    if raw.get("take_profit_pct") is not None:
        try:
            tpp = float(raw["take_profit_pct"])
        except (TypeError, ValueError):
            return None, "take_profit_pct must be a number (e.g. 0.15 = +15%)"
        if not (0.0 < tpp <= 10.0):
            return None, f"take_profit_pct {tpp} out of range (0, 10]"
        out["take_profit_pct"] = tpp
    if raw.get("stop_loss_cents") is not None:
        try:
            slc = int(raw["stop_loss_cents"])
        except (TypeError, ValueError):
            return None, "stop_loss_cents must be an integer 1-99"
        if not (1 <= slc <= 99):
            return None, f"stop_loss_cents {slc} out of range 1-99"
        out["stop_loss_cents"] = slc
    if raw.get("reason") is not None:
        out["reason"] = str(raw["reason"])[:200]
    return out, None


def sanitize_manage(raw: Any) -> tuple[Optional[dict], Optional[str]]:
    """Coerce whatever manage() returned into a clean action, or a rejection.
    None / "hold" = keep holding; "sell" (or {"action":"sell"}) = flatten the
    whole position at the bid now; {"action":"update", take_profit_pct?,
    stop_loss_cents?} = retune the exit targets (0 clears one)."""
    if raw is None or raw == "hold":
        return None, None
    if raw == "sell":
        return {"action": "sell"}, None
    if not isinstance(raw, dict):
        return None, f"manage() returned {type(raw).__name__}, expected None/'hold'/'sell'/dict"
    action = str(raw.get("action") or "").lower()
    if action == "sell":
        return {"action": "sell"}, None
    if action != "update":
        return None, f"unknown manage action {raw.get('action')!r}"
    out: dict[str, Any] = {"action": "update"}
    if "take_profit_pct" in raw:
        try:
            tpp = float(raw["take_profit_pct"] or 0.0)
        except (TypeError, ValueError):
            return None, "take_profit_pct must be a number (0 clears it)"
        if not (0.0 <= tpp <= 10.0):
            return None, f"take_profit_pct {tpp} out of range [0, 10]"
        out["take_profit_pct"] = tpp
    if "stop_loss_cents" in raw:
        try:
            slc = int(raw["stop_loss_cents"] or 0)
        except (TypeError, ValueError):
            return None, "stop_loss_cents must be an integer 0-99 (0 clears it)"
        if not (0 <= slc <= 99):
            return None, f"stop_loss_cents {slc} out of range 0-99"
        out["stop_loss_cents"] = slc
    return out, None


def sanitize_signal_action(raw: Any) -> tuple[Optional[dict], Optional[str]]:
    """decide_signal() contract: None = skip; True (or {"follow": True,
    "sizeUsd"?}) = follow the signal's own side with follower economics.
    Scripts FILTER and SIZE signals — they can't flip sides (side-flipped
    fills aren't derivable from the recorded data, so they'd be
    unbacktestable)."""
    if raw is None or raw is False:
        return None, None
    if raw is True:
        return {"follow": True}, None
    if not isinstance(raw, dict):
        return None, f"decide_signal() returned {type(raw).__name__}, expected None/True/dict"
    if not raw.get("follow"):
        return None, None
    out: dict[str, Any] = {"follow": True}
    if raw.get("sizeUsd") is not None:
        try:
            sz = float(raw["sizeUsd"])
        except (TypeError, ValueError):
            return None, "sizeUsd must be a number"
        if not (1.0 <= sz <= 100_000.0):
            return None, f"sizeUsd {sz} out of range [1, 100000]"
        out["sizeUsd"] = sz
    return out, None


def signal_to_js(sig: dict, source: str) -> dict:
    """The dict handed to decide_signal(signal) — shared by the live engine
    and the backtest so they can never drift. Confidence/edge/cost come from
    the same helpers the main engine's gates use."""
    import trader as trader_mod
    try:
        _, cost_cents = trader_mod._signal_cost_cents(sig, source)
    except Exception:
        cost_cents = None
    try:
        edge = trader_mod._compute_edge(sig, source)
    except Exception:
        edge = None
    ts = str(sig.get("created_at") or "")
    hour = None
    try:
        hour = int(ts[11:13])
    except (ValueError, IndexError):
        pass
    price = sig.get("price")
    direction = (sig.get("direction") or "yes").lower()
    if source == "momentum" and direction == "no" and price is not None:
        price = 1.0 - float(price)
    return {
        "source": source,
        "ticker": sig.get("ticker") or "",
        "category": sig.get("category") or "",
        "title": sig.get("title") or sig.get("yes_sub_title") or "",
        "price": float(price) if price is not None else None,
        "side": sig.get("taker_side") or sig.get("direction") or "",
        "dollarValue": sig.get("dollar_value"),
        "confidence": float(sig.get("confidence") or 0.0),
        "edgePts": edge,
        "costCents": cost_cents,
        "signalType": sig.get("signal_type") or "",
        "hourUtc": hour,
        "createdAt": ts,
    }


def _exec_ask(t: dict, side: str) -> Optional[float]:
    """Executable ask (0..1) to BUY `side` from a recorded tick: up buys YES
    at yes_ask; down buys NO at no_ask (or 1−yes_bid on the complementary
    book, same convention as replay.tick_to_asset). None = no executable
    quote this tick."""
    if side == "up":
        a = t.get("yes_ask")
    else:
        a = t.get("no_ask")
        if a is None and t.get("yes_bid") is not None:
            a = round(1.0 - float(t["yes_bid"]), 4)
    if a is None:
        return None
    a = float(a)
    return a if 0.0 < a < 1.0 else None


def _t_stat(trades: list[dict]) -> Optional[float]:
    """t-statistic of the mean per-trade P&L (is the edge distinguishable
    from noise?). None below 3 trades or at zero variance."""
    n = len(trades)
    if n < 3:
        return None
    pnls = [float(t.get("pnlUsd") or 0.0) for t in trades]
    mean = sum(pnls) / n
    var = sum((p - mean) ** 2 for p in pnls) / (n - 1)
    if var <= 0:
        return None
    return round(mean / math.sqrt(var / n), 3)


def _sim_exits(
    script: "script_sandbox.CompiledScript", ticks: list[dict], entry_idx: int,
    *, side: str, cost: float, size: int, tp_pct: Optional[float],
    sl_cents: Optional[int], ticker: str, asset_name: str, cfg: dict,
    close_iso: str, portfolio: dict,
) -> Optional[tuple[float, str]]:
    """Walk post-entry ticks simulating the exit layer: static tp/sl triggers
    (retunable by manage) checked first each tick, then the script's manage()
    hook. Sells fill into that tick's REAL bid with both taker fees charged.
    Returns (pnl_per_contract, reason) or None → held to settlement. Raises
    ScriptError if manage() dies or returns garbage (matches live, where that
    auto-disables the script)."""
    has_manage = "manage" in script.hooks
    if not has_manage and not tp_pct and not sl_cents:
        return None
    entry_fee = bt.kalshi_fee_per_contract(cost, contracts=size)
    want_sell = False
    for t2 in ticks[entry_idx + 1:]:
        bid = replay._held_bid(t2, side)

        def _sell(reason: str) -> tuple[float, str]:
            exit_fee = bt.kalshi_fee_per_contract(bid, contracts=size)
            return (bid - cost) - entry_fee - exit_fee, reason

        if bid is not None:
            if want_sell:
                return _sell("script_exit")
            if sl_cents and bid * 100.0 <= float(sl_cents):
                return _sell("stop_loss")
            if tp_pct and bid >= cost * (1.0 + float(tp_pct)):
                return _sell("take_profit")
        if not has_manage:
            continue
        ctx = replay.tick_to_asset(t2, cfg, close_iso)
        ctx["portfolio"] = dict(portfolio, openCount=1)
        pos = {
            "ticker": ticker, "asset": asset_name, "side": side,
            "contracts": size, "avgEntryCents": round(cost * 100, 1),
            "curBidCents": round(bid * 100, 1) if bid is not None else None,
            "minsLeft": ctx.get("minsLeft"),
            "tpPct": tp_pct, "slCents": sl_cents,
            "unrealizedPct": round((bid - cost) / cost, 4) if bid is not None and cost > 0 else None,
        }
        act_raw = script.call("manage", pos, ctx, budget_ms=DECIDE_BUDGET_MS)
        act, err = sanitize_manage(act_raw)
        if err:
            raise script_sandbox.ScriptError(f"manage(): {err}")
        if act is None:
            continue
        if act["action"] == "sell":
            if bid is not None:
                return _sell("script_exit")
            want_sell = True
        else:
            if "take_profit_pct" in act:
                tp_pct = act["take_profit_pct"] or None
            if "stop_loss_cents" in act:
                sl_cents = act["stop_loss_cents"] or None
    return None


def run(cfg: dict, code: str, *, trusted: bool = False,
        env: str = "production", since_days: int = 60) -> dict:
    """Backtest `code` over recorded resolved windows. Returns the standard
    Crypto15mBacktest payload extended with scriptLogs / scriptError /
    intent-rejection counters."""
    cfg = dict(cfg)
    contracts = max(1, int(cfg.get("crypto15m_order_size") or 1))
    max_entry_cents = int(cfg.get("script_max_entry_cents") or 97)
    max_contracts = max(1, int(cfg.get("script_max_contracts") or 20))

    try:
        script = script_sandbox.CompiledScript(
            "backtest", code, trusted=trusted)
    except script_sandbox.ScriptError as e:
        return {"scriptError": str(e), "n": 0, "wins": 0, "winRate": 0.0,
                "netEvCentsPerContract": 0.0, "totalPnlUsd": 0.0,
                "tStat": None, "maxDrawdownUsd": 0.0, "contracts": contracts,
                "windowsScanned": 0, "byAsset": {}, "equity": [],
                "byHourUtc": [], "byDay": [], "trades": [],
                "caveats": [f"Script failed to compile: {e}"],
                "scriptLogs": []}

    by_window = replay.load_windows(env, since_days)
    windows = sorted(
        by_window.items(),
        key=lambda kv: str(kv[1][0].get("sig_close") or ""),
    )

    script_error: Optional[str] = None
    rejected_intents = 0
    rail_refusals = 0
    partial = False
    trades: list[dict] = []
    n_windows = 0
    started = time.perf_counter()
    run_pnl = 0.0
    day_pnl: dict[str, float] = {}

    try:
        script.call("on_start", script.state, budget_ms=DECIDE_BUDGET_MS)
    except script_sandbox.ScriptError as e:
        script_error = str(e)

    if "decide" not in script.hooks:
        windows = []

    for ticker, ticks in windows:
        if script_error:
            break
        if time.perf_counter() - started > MAX_RUN_SECS:
            partial = True
            break
        if not crypto15m.asset_enabled(cfg, str(ticks[0].get("asset") or "")):
            continue
        n_windows += 1
        up_won = int(ticks[0].get("up_won") or 0)
        close_iso = str(ticks[0].get("sig_close") or "")
        for i, t in enumerate(ticks):
            asset = replay.tick_to_asset(t, cfg, close_iso)
            day = str(t.get("observed_at") or "")[:10]
            portfolio = {
                "balanceUsd": None, "openCount": 0, "openPositions": [],
                "todayPnlUsd": round(day_pnl.get(day, 0.0), 4),
                "totalPnlUsd": round(run_pnl, 4),
            }
            ctx = dict(asset)
            ctx["portfolio"] = portfolio
            try:
                raw = script.call("decide", ctx, budget_ms=DECIDE_BUDGET_MS)
            except script_sandbox.ScriptError as e:
                script_error = str(e)
                break
            if raw is None:
                continue
            intent, err = sanitize_intent(raw)
            if err:
                rejected_intents += 1
                if rejected_intents <= 5:
                    script._log_lines.append(f"[harness] rejected intent: {err}")
                continue
            side = intent["side"]
            ask = _exec_ask(t, side)
            if ask is None:
                continue
            ask_cents = ask * 100.0
            if intent["price"] != "ask":
                limit_c = float(intent["price"])
                if limit_c > max_entry_cents:
                    rail_refusals += 1
                    break
                if ask_cents > limit_c:
                    continue
            if (intent["price"] == "ask"
                    and int(round(ask_cents)) + 1 > max_entry_cents):
                rail_refusals += 1
                break
            cost, fill_idx = float(ask), i
            size = min(int(intent.get("size") or contracts), max_contracts)
            fee = bt.kalshi_fee_per_contract(cost, contracts=size)
            won = up_won if side == "up" else (1 - up_won)
            pnl_ct = (1.0 - cost - fee) if won else (-cost - fee)
            exit_reason = "settlement"
            try:
                ex = _sim_exits(
                    script, ticks, fill_idx, side=side, cost=cost, size=size,
                    tp_pct=intent.get("take_profit_pct"),
                    sl_cents=intent.get("stop_loss_cents"),
                    ticker=ticker, asset_name=str(asset.get("asset")),
                    cfg=cfg, close_iso=close_iso, portfolio=portfolio,
                )
            except script_sandbox.ScriptError as e:
                script_error = str(e)
                ex = None
            if ex is not None:
                pnl_ct, exit_reason = ex
                won = pnl_ct > 0
            pos_lite = {
                "ticker": ticker, "asset": asset.get("asset"), "side": side,
                "costCents": round(cost * 100, 1), "contracts": size,
                "won": bool(won), "pnlUsd": round(pnl_ct * size, 4),
                "exitReason": exit_reason, "reason": intent.get("reason"),
            }
            try:
                fill_lite = dict(pos_lite, won=None, pnlUsd=None,
                                 exitReason=None)
                script.call("on_fill", fill_lite, script.state,
                            budget_ms=DECIDE_BUDGET_MS)
                script.call("on_settle", dict(pos_lite), script.state,
                            budget_ms=DECIDE_BUDGET_MS)
            except script_sandbox.ScriptError as e:
                script_error = str(e)
            trades.append({
                "ticker": ticker, "asset": asset.get("asset"), "side": side,
                "costCents": round(cost * 100, 1),
                "minsLeft": asset.get("minsLeft"), "won": bool(won),
                "pnlUsd": round(pnl_ct * size, 4), "contracts": size,
                "exitReason": exit_reason,
                "at": t.get("observed_at"),
            })
            run_pnl += pnl_ct * size
            day_pnl[day] = day_pnl.get(day, 0.0) + pnl_ct * size
            break

    caveats = [
        "Entries fill at the recorded executable ask (taker; Kalshi fee "
        "0.07·P·(1−P) per contract, per-order fee rounded UP to the cent — "
        "small orders pay proportionally more).",
        "Resting limits below the ask are NOT modeled as maker fills — an "
        "intent only fills when the recorded ask crosses its price.",
        "EXIT FILLS ARE OPTIMISTIC: take-profit / stop-loss / manage() sells "
        "fill into the recorded bid, but 15m books thin out fast and can gap "
        "straight through a stop — live, scripted exits realize less than "
        "shown here. Treat capped-downside backtests with suspicion.",
        "script_max_open and the per-script daily-loss breaker are NOT simulated: "
        "live, concurrent entries are capped and a losing day auto-disables the "
        "script, so live is a rail-limited SUBSET of these trades.",
        "Size is the intent size capped at script_max_contracts.",
        f"Ticks are ~4-25s apart over {since_days} days of app uptime only; "
        "decide() sees those ticks, not every live quote.",
        "In-sample: a script tuned against this panel is fit to the past. "
        "Watch it run before arming live.",
    ]
    if rejected_intents:
        caveats.insert(0, (
            f"{rejected_intents} intent(s) were malformed and skipped — see the "
            "script log for the first few reasons."
        ))
    if rail_refusals:
        caveats.append(
            f"{rail_refusals} entr(y/ies) refused by the safety rails "
            f"(price above script_max_entry_cents={max_entry_cents}c) — the same "
            "refusal happens live."
        )
    if partial:
        caveats.insert(0, (
            f"PARTIAL RESULT: the run hit the {MAX_RUN_SECS:.0f}s wall-clock cap "
            f"after {n_windows} windows — narrow sinceDays or simplify the script."
        ))
    if script_error:
        caveats.insert(0, (
            f"Script DIED mid-run: {script_error} — results cover only the "
            "windows before the error. Live, this same error would auto-disable "
            "the script."
        ))
    if n_windows == 0:
        caveats.insert(0, (
            f"No resolved 15m windows recorded in the last {since_days} days — "
            "the recorder captures data while the app runs, so let it "
            "accumulate first."
        ))
    missing = sorted(
        set(script_sandbox.find_ctx_fields(code)) - replay._DERIVABLE)
    if missing:
        caveats.insert(0, (
            "Script reads ctx fields not recorded in ticks (None during "
            f"backtest, live-only): {', '.join(missing)}"
        ))

    if "manage" in script.hooks:
        caveats.append(
            "manage() is simulated per recorded tick (~25s apart): live it runs "
            "every ~5s, so live exits can react faster than this replay shows."
        )
    if "supervise" in script.hooks:
        caveats.append(
            "supervise() is NOT simulated — config/engine switching has no "
            "backtestable counterfactual. Only its decide/manage effects show here."
        )

    out = replay._summarize(trades, contracts, n_windows, caveats)
    out["tStat"] = _t_stat(trades)
    out["scriptError"] = script_error
    if "decide_signal" in script.hooks and not script_error:
        try:
            out["signalResult"] = _replay_signals(
                script, cfg, since_days=since_days, started=started)
        except script_sandbox.ScriptError as e:
            out["signalResult"] = {"scriptError": str(e), "n": 0, "caveats": [
                f"decide_signal died: {e}"]}
    out["scriptLogs"] = script.drain_logs()[-200:]
    return out


def _replay_signals(script: "script_sandbox.CompiledScript", cfg: dict, *,
                    since_days: int = 60, slippage_cents: float = 1.0,
                    started: Optional[float] = None) -> dict:
    """Replay recorded whale prints + momentum alerts through the script's
    decide_signal(signal) filter with follower economics — the same model as
    the main-engine backtest (entry at signal price + slippage, Kalshi fee,
    outcome from the recorded resolution). Shares the run's MAX_RUN_SECS
    wall-clock cap via `started` — a large corpus must not pin the backtest
    worker past the promised cap."""
    if started is None:
        started = time.perf_counter()
    partial = False
    fixed_usd = float(cfg.get("fixed_trade_usd") or 5.0)
    sig_max_entry_cents = float(cfg.get("script_max_entry_cents") or 97)
    sig_max_contracts = max(1, int(cfg.get("script_max_contracts") or 20))
    rail_skips = 0
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
    merged = sorted(
        [(dict(r), "whale") for r in whales] + [(dict(r), "momentum") for r in alerts],
        key=lambda x: str(x[0].get("created_at") or ""),
    )
    trades: list[dict] = []
    scanned = 0
    rejected = 0
    for sig, source in merged:
        if time.perf_counter() - started > MAX_RUN_SECS:
            partial = True
            break
        scanned += 1
        signal = signal_to_js(sig, source)
        raw = script.call("decide_signal", dict(signal),
                          budget_ms=DECIDE_BUDGET_MS)
        act, err = sanitize_signal_action(raw)
        if err:
            rejected += 1
            continue
        if act is None:
            continue
        price = signal.get("price")
        if price is None or not (0.0 < float(price) < 1.0):
            continue
        cost = min(0.99, float(price) + slippage_cents / 100.0)
        if cost * 100.0 > sig_max_entry_cents:
            rail_skips += 1
            continue
        spend = float(act.get("sizeUsd") or fixed_usd)
        n_ct = max(1, int(round(spend / max(cost, 0.01))))
        n_ct = min(n_ct, sig_max_contracts)
        fee = bt.kalshi_fee_per_contract(cost, contracts=n_ct)
        won = bool(sig.get("outcome_correct"))
        pnl_ct = (1.0 - cost - fee) if won else (-cost - fee)
        trades.append({
            "ticker": sig.get("ticker"), "asset": sig.get("category") or source,
            "side": signal.get("side") or "?",
            "costCents": round(cost * 100, 1), "minsLeft": None,
            "won": won, "pnlUsd": round(pnl_ct * n_ct, 4),
            "contracts": n_ct, "at": sig.get("created_at"),
        })
    caveats = [
        f"Follower economics: entry at the signal price +{slippage_cents:.0f}c slippage — live fills on fast markets can be worse.",
        "decide_signal() FILTERS the signal's own side (side-flipping isn't backtestable from recorded data).",
        f"Entry-price cap (script_max_entry_cents={sig_max_entry_cents:g}c) and size "
        f"cap (script_max_contracts={sig_max_contracts}) match live; but "
        "script_max_open and the per-script daily-loss breaker are NOT simulated.",
        "In-sample: signals were only recorded while the app was running.",
    ]
    if rail_skips:
        caveats.insert(0, f"{rail_skips} signal(s) skipped: price above the entry cap (refused live too).")
    if rejected:
        caveats.insert(0, f"{rejected} malformed decide_signal return(s) skipped.")
    if partial:
        caveats.insert(0, (
            f"PARTIAL RESULT: signal replay hit the shared {MAX_RUN_SECS:.0f}s "
            f"wall-clock cap after {scanned} of {len(merged)} signals."
        ))
    out = replay._summarize(trades, 5, scanned, caveats)
    out["tStat"] = _t_stat(trades)
    return out
