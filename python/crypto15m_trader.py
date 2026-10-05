from __future__ import annotations

import asyncio
import json
import logging
import math
import statistics
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Optional

import crypto15m
import db
import kalshi_api
import kalshi_auth
import kalshi_ws
import rules as rules_engine
import trader

logger = logging.getLogger("crypto15m")

_DEAD_ORDER_STATUSES = frozenset({"canceled", "cancelled", "executed", "expired"})

_CLOSED_ORDER_GRACE_SEC = 60.0

_warn_at: dict[str, float] = {}


def _warn_once(key: str, every_sec: float) -> bool:
    now = time.monotonic()
    last = _warn_at.get(key, 0.0)
    if now - last < every_sec:
        return False
    _warn_at[key] = now
    if len(_warn_at) > 500:
        _warn_at.clear()
    return True

_block_reasons: dict[str, str] = {}

_CAL_CACHE: dict = {"at": 0.0, "ok": True, "n": 0, "rate": None, "lb": None}
_CAL_CHECK_SEC = 300.0
_CAL_WINDOW = 40
_CAL_MIN_N = 20
_CAL_PAUSE_LB = 0.85
_CAL_RESUME_LB = 0.88


def _wilson_lb(wins: int, n: int, z: float = 1.645) -> float:
    if n <= 0:
        return 0.0
    p = wins / n
    denom = 1.0 + z * z / n
    center = p + z * z / (2 * n)
    rad = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (center - rad) / denom)


def check_model_calibration(env: str) -> dict:
    now = time.time()
    if now - _CAL_CACHE["at"] < _CAL_CHECK_SEC:
        return dict(_CAL_CACHE)
    try:
        with db.get_db() as conn:
            rows = conn.execute(
                """SELECT t.ticker, t.model_prob, s.up_won
                   FROM crypto15m_ticks t
                   JOIN crypto15m_signals s
                     ON s.ticker = t.ticker AND s.kalshi_env = t.kalshi_env
                   WHERE s.resolved = 1 AND s.up_won IS NOT NULL
                     AND t.kalshi_env = ? AND t.model_prob IS NOT NULL
                     AND t.observed_at >= datetime('now', '-3 days')
                     AND t.mins_left <= 5 AND t.mins_left >= 0.5
                     AND (t.model_prob >= 0.97 OR t.model_prob <= 0.03)
                   ORDER BY t.observed_at""",
                (env,),
            ).fetchall()
    except Exception:
        return dict(_CAL_CACHE)
    last_by_ticker: dict = {}
    for r in rows:
        last_by_ticker[r["ticker"]] = r
    recent = list(last_by_ticker.values())[-_CAL_WINDOW:]
    n = len(recent)
    wins = sum(
        1 for r in recent
        if (float(r["model_prob"]) >= 0.5) == bool(r["up_won"])
    )
    lb = _wilson_lb(wins, n)
    prev_ok = bool(_CAL_CACHE.get("ok", True))
    if n < _CAL_MIN_N:
        ok = True
    elif prev_ok:
        ok = lb >= _CAL_PAUSE_LB
    else:
        ok = lb >= _CAL_RESUME_LB
    if prev_ok and not ok:
        logger.warning(
            f"[crypto15m] MODEL CALIBRATION DEGRADED: {wins}/{n} recent "
            f"sniper-band predictions hit (LB {lb:.3f} < {_CAL_PAUSE_LB}) — "
            f"auto-pausing model-mode entries"
        )
    elif not prev_ok and ok:
        logger.info(f"[crypto15m] model calibration recovered (LB {lb:.3f}) — resuming")
    _CAL_CACHE.update({
        "at": now, "ok": ok, "n": n,
        "rate": round(wins / n, 4) if n else None, "lb": round(lb, 4),
    })
    return dict(_CAL_CACHE)




def edge_health(env: str) -> dict:
    with db.get_db() as conn:
        rows = db.crypto15m_resolved_for_health(conn, env, since_days=90)
    now = time.time()

    def _age_days(iso: str) -> float:
        try:
            dt = datetime.strptime(iso[:19], "%Y-%m-%d %H:%M:%S")
            return (now - dt.replace(tzinfo=timezone.utc).timestamp()) / 86400.0
        except Exception:
            return 1e9

    buckets: dict = {}
    for r in rows:
        strat = (r.get("strategy") or "legacy") or "legacy"
        mode = "paper" if r.get("dry_run") else "live"
        filled = int(r.get("filled_contracts") or 0)
        if filled <= 0:
            continue
        ppc = float(r["pnl_usd"]) * 100.0 / filled
        age = _age_days(r.get("resolved_at") or "")
        b = buckets.setdefault((strat, mode), [])
        b.append((age, ppc, float(r.get("avg_entry_cents") or 0.0)))

    def _agg(obs: list) -> Optional[dict]:
        if not obs:
            return None
        n = len(obs)
        vals = [o[1] for o in obs]
        mean = sum(vals) / n
        sd = (sum((v - mean) ** 2 for v in vals) / n) ** 0.5
        t = (mean / (sd / math.sqrt(n))) if (sd > 0 and n > 1) else None
        wins = sum(1 for v in vals if v > 0)
        losses = n - wins
        since_loss = 0
        for _, v, _px in reversed(obs):
            if v <= 0:
                break
            since_loss += 1
        return {
            "n": n, "wins": wins, "losses": losses,
            "winRate": round(wins / n, 4),
            "netCentsPerContract": round(mean, 2),
            "t": round(t, 2) if t is not None else None,
            "avgEntryCents": round(sum(o[2] for o in obs) / n, 1),
            "sinceLastLoss": since_loss if losses else n,
        }

    def _verdict(w30: Optional[dict], w90: Optional[dict]) -> str:
        a = w30 or w90
        if a is None:
            return "no resolved positions"
        if a["n"] < 30:
            return f"n too small ({a['n']}) — keep collecting"
        t = a.get("t")
        if t is None:
            if a["losses"] == 0 and a["netCentsPerContract"] > 0:
                return "edge holding (unbroken streak — tail unobserved)"
            if a["wins"] == 0 and a["netCentsPerContract"] < 0:
                return "measured NEGATIVE — stop"
            return "degenerate sample"
        if t >= 2.0:
            return "edge holding (significant so far)"
        if t <= -2.0:
            return "measured NEGATIVE — stop"
        if w90 and w30 and w90.get("t") and w90["t"] >= 2.0 \
                and w30["netCentsPerContract"] <= 0:
            return "possible decay — 30d flat vs positive 90d"
        return "no significant edge yet"

    out = []
    for (strat, mode), obs in sorted(buckets.items()):
        w7 = _agg([o for o in obs if o[0] <= 7])
        w30 = _agg([o for o in obs if o[0] <= 30])
        w90 = _agg(obs)
        out.append({
            "strategy": strat, "mode": mode,
            "w7": w7, "w30": w30, "w90": w90,
            "verdict": _verdict(w30, w90),
        })
    cal = check_model_calibration(env)
    return {
        "rows": out,
        "calibration": {
            "ok": bool(cal.get("ok", True)),
            "rate": cal.get("rate"), "n": cal.get("n"), "lb": cal.get("lb"),
        },
        "note": (
            "Measured on YOUR resolved positions, rolling windows, after fees. "
            "Paper and live are separate rows. On this venue edges decay — a "
            "one-time backtest is never evidence an edge still exists."
        ),
    }


def direction_for_favorite(favorite: str) -> str:
    return "yes" if favorite == "up" else "no"


def evaluate_rules(asset: dict, rules: list) -> tuple[bool, str]:
    return rules_engine.evaluate_rules(asset, rules)


def entry_limit_cents(entry_cost: float, entry_diff: float) -> int:
    cents = round((float(entry_cost) + float(entry_diff)) * 100)
    return max(1, min(99, int(cents)))


def maker_limit_cents(side: str, yes_bid, yes_ask, entry_cost: float) -> int:
    bid = None
    if side == "up":
        bid = yes_bid
    elif side == "down" and yes_ask:
        bid = 1.0 - float(yes_ask)
    if not bid or bid <= 0:
        bid = max(0.01, float(entry_cost) - 0.01)
    return max(1, min(99, int(round(float(bid) * 100))))


def side_prob_from_market(market: Optional[dict], direction: str) -> Optional[float]:
    if not market:
        return None
    yes_bid = crypto15m._price_dollars(market, "yes_bid")
    yes_ask = crypto15m._price_dollars(market, "yes_ask")
    up = crypto15m._mid_up(yes_bid, yes_ask, crypto15m._price_dollars(market, "last_price"))
    if up is None:
        return None
    return up if direction == "yes" else (1.0 - up)


_WS_QUOTE_MAX_AGE_MS = 15_000.0


def _ws_quote_market(ticker: str) -> Optional[dict]:
    q = kalshi_ws.ticker_quote(ticker)
    if not q:
        return None
    ts = float(q.get("ts_ms") or 0)
    if ts <= 0 or (time.time() * 1000.0 - ts) > _WS_QUOTE_MAX_AGE_MS:
        return None
    out: dict = {}
    for src, dst in (("yes_bid_cents", "yes_bid_dollars"),
                     ("yes_ask_cents", "yes_ask_dollars"),
                     ("last_cents", "last_price_dollars")):
        v = q.get(src)
        out[dst] = (v / 100.0) if v is not None else None
    if not (out["yes_bid_dollars"] or out["yes_ask_dollars"] or out["last_price_dollars"]):
        return None
    return out


def _is_directional_rules(cfg: dict) -> bool:
    return bool(cfg.get("crypto15m_use_rules")) and bool(cfg.get("crypto15m_rules_no"))


def _directional_rules_side(asset: dict, cfg: dict) -> tuple[Optional[str], str]:
    ok_y, _ = evaluate_rules(asset, cfg.get("crypto15m_rules") or [])
    if ok_y:
        return "up", "yes-rules matched"
    ok_n, _ = evaluate_rules(asset, cfg.get("crypto15m_rules_no") or [])
    if ok_n:
        return "down", "no-rules matched"
    return None, "no directional rule matched"


def _bought_side(asset: dict, cfg: dict) -> Optional[str]:
    if _is_directional_rules(cfg):
        return _directional_rules_side(asset, cfg)[0]
    mode = (cfg.get("crypto15m_direction_mode") or "favorite").lower()
    if mode == "model":
        mp = asset.get("modelProb")
        if mp is None:
            return None
        return "up" if float(mp) >= 0.5 else "down"
    fav = asset.get("favorite")
    if fav not in ("up", "down"):
        return None
    if mode == "contrarian":
        return "down" if fav == "up" else "up"
    return fav


def momentum_filters_ok(asset: dict, cfg: dict) -> tuple[bool, str]:
    try:
        min_rsi = float(cfg.get("crypto15m_min_rsi", 0.0) or 0.0)
    except (TypeError, ValueError):
        min_rsi = 0.0
    try:
        min_macd = float(cfg.get("crypto15m_min_macd_hist", 0.0) or 0.0)
    except (TypeError, ValueError):
        min_macd = 0.0
    if min_rsi <= 0 and min_macd <= 0:
        return True, "ok"
    side = _bought_side(asset, cfg)
    if side is None:
        return False, "no favorite"
    up = side == "up"
    if min_rsi > 0:
        rsi = asset.get("rsi")
        if rsi is None:
            return False, "rsi unavailable (turn on Detect MACD/RSI)"
        rsi = float(rsi)
        if up and rsi < min_rsi:
            return False, f"rsi {rsi:.0f} < {min_rsi:.0f}"
        if (not up) and rsi > (100.0 - min_rsi):
            return False, f"rsi {rsi:.0f} > {100.0 - min_rsi:.0f}"
    if min_macd > 0:
        mh = asset.get("macdHist")
        if mh is None:
            return False, "macd unavailable (turn on Detect MACD/RSI)"
        mh = float(mh)
        if up and mh < min_macd:
            return False, f"macdHist {mh:.3f} < {min_macd:.3f}"
        if (not up) and mh > -min_macd:
            return False, f"macdHist {mh:.3f} > {-min_macd:.3f}"
    return True, "ok"


_FM_MIN_PRINTS = 30
_FM_MAX_PRINTS = 54
_FM_MIN_PROB = 0.9985


def should_enter(asset: dict, cfg: dict, *, has_open: bool, open_count: int) -> tuple[bool, str]:
    if not cfg.get("crypto15m_enabled"):
        return False, "disabled"
    if has_open:
        return False, "already open"
    max_conc = int(cfg.get("crypto15m_max_concurrent", len(crypto15m.SERIES)))
    if open_count >= max_conc:
        return False, "max concurrent"
    if not asset.get("hasMarket"):
        return False, "no market"
    if asset.get("favorite") not in ("up", "down"):
        return False, "no favorite"
    if not crypto15m.hours_ok(cfg, hour=asset.get("hourUtc")):
        return False, "outside trading hours"
    if cfg.get("crypto15m_use_rules"):
        ml = asset.get("minsLeft")
        if ml is not None and float(ml) < 1.0:
            return False, "final minute (custom rules are blocked here — model mode only)"
        if _is_directional_rules(cfg):
            side, why = _directional_rules_side(asset, cfg)
            if side is None:
                return False, why
        else:
            ok, why = evaluate_rules(asset, cfg.get("crypto15m_rules") or [])
            if not ok:
                return ok, why
        rside = _bought_side(asset, cfg)
        rask = asset.get("upAsk") if rside == "up" else (
            asset.get("downAsk") if rside == "down" else None
        )
        if rask and float(rask) > crypto15m._const(cfg, "entry_max"):
            return False, f"ask {float(rask)*100:.0f}c above the entry cap"
        return True, "ok"
    if (cfg.get("crypto15m_direction_mode") or "favorite").lower() == "model":
        mp = asset.get("modelProb")
        if mp is None:
            return False, "model unavailable (needs indicators + spot feed)"
        mp = float(mp)
        p_side = mp if mp >= 0.5 else 1.0 - mp
        if cfg.get("crypto15m_model_autopause", True):
            cal = check_model_calibration(trader.get_env())
            if not cal.get("ok", True):
                return False, (
                    f"model calibration degraded ({cal.get('rate', 0):.0%} hit over "
                    f"last {cal.get('n', 0)} windows) — auto-paused"
                )
        ml = asset.get("minsLeft")
        final_minute = ml is not None and 0.0 < float(ml) < 1.0
        if final_minute:
            if not cfg.get("crypto15m_model_final_minute", True):
                return False, "final minute (disabled)"
            prints = int(asset.get("settlePrints") or 0)
            if prints < _FM_MIN_PRINTS:
                return False, f"only {prints}/{_FM_MIN_PRINTS} settlement prints in"
            if prints > _FM_MAX_PRINTS:
                return False, "too close to the close for an order round-trip"
            if p_side < _FM_MIN_PROB:
                return False, f"model {p_side:.4f} < {_FM_MIN_PROB} (3-sigma gate)"
        elif not asset.get("inWindow"):
            return False, "outside entry window"
        elif not cfg.get("crypto15m_model_midwindow", False):
            return False, "mid-window model entries disabled (no measured edge)"
        else:
            min_p = float(cfg.get("crypto15m_model_min_prob", 0.97) or 0.97)
            if p_side < min_p:
                return False, f"model {p_side:.3f} < {min_p:.2f}"
        edge = asset.get("edgeNetCents")
        min_e = float(cfg.get("crypto15m_model_min_edge_cents", 2.0) or 0.0)
        if edge is None or float(edge) < min_e:
            return False, f"net edge {edge}c < {min_e:.1f}c"
        ask = asset.get("upAsk") if mp >= 0.5 else asset.get("downAsk")
        if not ask or not (0.0 < float(ask) <= crypto15m._const(cfg, "entry_max")):
            return False, "no executable ask under the entry cap"
        return True, "ok"
    if not asset.get("signal"):
        return False, "no signal"
    return momentum_filters_ok(asset, cfg)


def stop_loss_pct(cfg: dict) -> float:
    try:
        return max(0.0, min(1.0, float(cfg.get("crypto15m_stop_loss_pct", 0.0) or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def should_stop_loss(position: dict, side_prob: Optional[float], cfg: dict) -> bool:
    if side_prob is None:
        return False
    if position.get("status") != "filled":
        return False
    if int(position.get("filled_contracts") or 0) <= 0:
        return False
    slc = position.get("sl_cents")
    if slc:
        try:
            if float(side_prob) * 100.0 <= float(slc):
                return True
        except (TypeError, ValueError):
            pass
    if side_prob < crypto15m._const(cfg, "exit_threshold"):
        return True
    slp = stop_loss_pct(cfg)
    if slp > 0:
        filled = int(position.get("filled_contracts") or 0)
        cost = float(position.get("cost_usd") or 0.0)
        if cost > 0 and filled > 0:
            cur_value = filled * float(side_prob)
            if (cost - cur_value) / cost >= slp:
                return True
    return False


def take_profit_cents(cfg: dict) -> int:
    try:
        return max(0, min(99, int(cfg.get("crypto15m_take_profit_cents", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def should_take_profit(position: dict, side_prob: Optional[float], cfg: dict) -> bool:
    if side_prob is None:
        return False
    if position.get("status") != "filled":
        return False
    if int(position.get("filled_contracts") or 0) <= 0:
        return False
    tpp = position.get("tp_pct")
    if tpp:
        try:
            entry_c = float(position.get("avg_entry_cents")
                            or position.get("entry_limit_cents") or 0)
            if entry_c > 0 and side_prob * 100.0 >= entry_c * (1.0 + float(tpp)):
                return True
        except (TypeError, ValueError):
            pass
    tp = take_profit_cents(cfg)
    if tp <= 0:
        return False
    return side_prob * 100.0 >= tp


def exec_side_prob(market: Optional[dict], side: Optional[str],
                   mid_prob: Optional[float]) -> Optional[float]:
    bid_c = _paper_side_bid_cents(market, side or "")
    return (bid_c / 100.0) if bid_c is not None else mid_prob


def _stop_slippage(cfg: dict) -> int:
    try:
        return max(0, min(50, int(cfg.get("crypto15m_stop_slippage_cents", 0) or 0)))
    except (TypeError, ValueError):
        return 0


def _clamp01(v) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    if f != f:
        return 0.0
    return max(0.0, min(1.0, f))


_MGMT_KEYS = (
    "crypto15m_exit_threshold",
    "crypto15m_stop_loss_pct",
    "crypto15m_take_profit_cents",
    "crypto15m_stop_slippage_cents",
)


def _mgmt_snapshot_json(cfg: dict) -> str:
    return json.dumps({k: cfg[k] for k in _MGMT_KEYS if k in cfg})


def _with_mgmt_snapshot(pos: dict, cfg: dict) -> dict:
    raw = pos.get("mgmt_config")
    if not raw:
        return cfg
    try:
        snap = json.loads(raw)
    except (TypeError, ValueError):
        return cfg
    return {**cfg, **snap} if isinstance(snap, dict) and snap else cfg


def compute_entry_contracts(
    cfg: dict, *, entry_limit_cents: int, balance_usd: float, order_size: int
) -> int:
    price = max(0.01, int(entry_limit_cents) / 100.0)
    bal = max(0.0, float(balance_usd or 0.0))
    mode = (cfg.get("crypto15m_sizing_mode") or "fixed").lower()

    if mode == "balance_pct" and bal > 0:
        pct = _clamp01(cfg.get("crypto15m_balance_pct", 0.02))
        contracts = int((bal * pct) // price)
    else:
        contracts = max(1, int(order_size))

    max_loss = _clamp01(cfg.get("crypto15m_max_loss_pct", 0.0))
    if max_loss > 0 and bal > 0:
        contracts = min(contracts, int((bal * max_loss) // price))

    return max(0, contracts)


def _crypto_shard_cash_usd() -> Optional[float]:
    series = crypto15m.SERIES[0]["series"] if crypto15m.SERIES else ""
    idx = kalshi_api.shard_for_ticker(series)
    if idx is None:
        return None
    shards = trader.cached_shard_balances()
    if not shards:
        return None
    return shards.get(int(idx))


async def _bankroll_usd(cfg: dict, authed: bool) -> float:
    if authed:
        try:
            cents, _port = await trader.refresh_balance(cfg, force=False)
            if cents > 0:
                usd = cents / 100.0
                here = _crypto_shard_cash_usd()
                return min(usd, here) if here is not None else usd
        except Exception:
            pass
    return max(0.0, float(cfg.get("start_bankroll_usd", 0.0) or 0.0))




def _iso(s):
    if not s or not isinstance(s, str):
        return s
    s = s.strip()
    if not s:
        return s
    if s.endswith("Z") or "+" in s[10:]:
        return s.replace(" ", "T")
    return s.replace(" ", "T") + "Z"


def _pos_to_js(r: dict) -> dict:
    def _f(k):
        return float(r[k]) if r.get(k) is not None else None
    return {
        "id": int(r["id"]),
        "asset": r["asset"], "series": r.get("series") or "",
        "ticker": r.get("ticker") or "",
        "side": r.get("side") or "", "direction": r.get("direction") or "",
        "targetContracts": int(r.get("target_contracts") or 0),
        "filledContracts": int(r.get("filled_contracts") or 0),
        "entryLimitCents": float(r.get("entry_limit_cents") or 0),
        "avgEntryCents": _f("avg_entry_cents"),
        "costUsd": float(r.get("cost_usd") or 0.0),
        "status": r.get("status") or "",
        "exitReason": r.get("exit_reason"),
        "exitLimitCents": float(r["exit_limit_cents"]) if r.get("exit_limit_cents") is not None else None,
        "proceedsUsd": _f("proceeds_usd"),
        "feesUsd": float(r.get("fees_usd") or 0.0) + float(r.get("exit_fees_usd") or 0.0),
        "confidence": float(r.get("confidence") or 0.0),
        "entryDeltaUsd": _f("entry_delta_usd"),
        "outcomeCorrect": int(r["outcome_correct"]) if r.get("outcome_correct") is not None else None,
        "settlementUsd": _f("settlement_usd"),
        "pnlUsd": _f("pnl_usd"),
        "resolved": bool(r.get("resolved") or 0),
        "dryRun": bool(r.get("dry_run") or 0),
        "closeTime": _iso(r.get("close_time")) or "",
        "strategy": r.get("strategy") or "",
        "runnerId": r.get("runner_id") or "",
        "kalshiEnv": r.get("kalshi_env") or "demo",
        "createdAt": _iso(r.get("created_at")) or "",
        "resolvedAt": _iso(r.get("resolved_at")),
        "error": r.get("error"),
    }




def _unfunded_shard(ticker: str) -> Optional[str]:
    idx = kalshi_api.shard_for_ticker(ticker)
    if idx is None:
        return None
    shards = trader.cached_shard_balances()
    if not shards:
        return None
    here = shards.get(int(idx))
    if here is None or here > 0:
        return None
    return kalshi_api.shard_name(idx)

async def _open_entry(
    a: dict, cfg: dict, env: str, balance_usd: float,
    *, runner_id: str = "", paper: bool = False,
) -> Optional[dict]:
    mode = (cfg.get("crypto15m_direction_mode") or "favorite").lower()
    favorite = a.get("favorite")
    fav_price = float(a.get("favoritePrice") or 0.0)
    if _is_directional_rules(cfg):
        side = _directional_rules_side(a, cfg)[0]
        if side not in ("up", "down"):
            return None
        ask = a.get("upAsk") if side == "up" else a.get("downAsk")
        entry_cost = float(ask or a.get("entryCost") or (fav_price if side == favorite else 1.0 - fav_price))
        conf = entry_cost * 100.0
    elif mode == "contrarian":
        side = "down" if favorite == "up" else "up"
        entry_cost = max(0.01, 1.0 - fav_price)
        conf = entry_cost * 100.0
    elif mode == "model":
        mp_raw = a.get("modelProb")
        mp = float(mp_raw) if mp_raw is not None else 0.5
        side = "up" if mp >= 0.5 else "down"
        ask = a.get("upAsk") if side == "up" else a.get("downAsk")
        entry_cost = float(ask or a.get("entryCost") or fav_price)
        conf = (mp if side == "up" else 1.0 - mp) * 100.0
    else:
        side = favorite
        entry_cost = float(a.get("entryCost") or fav_price)
        conf = fav_price * 100.0
    # A market with no quotes has no favourite, and contrarian mode would flip
    # that None into "up"; the fallbacks above can also land on 0 or 1. Neither
    # is a price anyone could fill at.
    if side not in ("up", "down") or not (0.0 < entry_cost < 1.0):
        return None
    direction = direction_for_favorite(side)
    style = (cfg.get("crypto15m_entry_style") or "maker").lower()
    if mode == "model":
        style = "taker"
    if style == "maker":
        limit_cents = maker_limit_cents(side, a.get("yesBid"), a.get("yesAsk"), entry_cost)
    else:
        limit_cents = entry_limit_cents(entry_cost, crypto15m._const(cfg, "entry_diff"))
    if (
        mode == "favorite"
        and not cfg.get("crypto15m_use_rules")
        and bool(cfg.get("crypto15m_strict_threshold", True))
    ):
        thr_cents = int(round(crypto15m._const(cfg, "entry_threshold") * 100))
        if int(round(entry_cost * 100)) < thr_cents:
            logger.info(
                f"[crypto15m] skip {a.get('asset')}: strict threshold — buy price "
                f"{entry_cost * 100:.0f}c below the {thr_cents}c floor "
                f"(thin book: mid says favorite, ask disagrees)"
            )
            return None
        limit_cents = max(limit_cents, min(99, thr_cents))
    order_size = compute_entry_contracts(
        cfg,
        entry_limit_cents=limit_cents,
        balance_usd=balance_usd,
        order_size=max(1, int(cfg.get("crypto15m_order_size", 1))),
    )
    cap_pct = _clamp01(cfg.get("crypto15m_max_total_pct", 0.0))
    if cap_pct > 0 and balance_usd <= 0 and not paper:
        logger.info(
            f"[crypto15m] skip {a.get('asset')}: exposure cap armed "
            f"({cap_pct:.0%}) but bankroll unreadable — blocking LIVE entry"
        )
        return None
    if cap_pct > 0 and balance_usd > 0:
        with db.get_db() as conn:
            committed = db.open_crypto15m_committed_usd(conn, env)
            filled_cost = db.open_crypto15m_filled_cost_usd(conn, env)
        budget = (balance_usd + filled_cost) * cap_pct - committed
        price = max(0.01, limit_cents / 100.0)
        order_size = min(order_size, int(max(0.0, budget) // price))
        if order_size < 1:
            logger.info(
                f"[crypto15m] skip {a.get('asset')}: aggregate 15m exposure cap "
                f"(${committed:.2f} committed >= {cap_pct:.0%} of bankroll)"
            )
            return None
    if order_size < 1:
        logger.info(
            f"[crypto15m] skip {a.get('asset')}: sizing yielded 0 contracts "
            f"(risk budget too small at {limit_cents}c)"
        )
        return None
    close_epoch = crypto15m._parse_close_epoch(a.get("closeTime") or "")
    if close_epoch is not None and close_epoch - kalshi_auth.server_now() < 10.0:
        logger.info(f"[crypto15m] skip {a.get('asset')}: <10s to close at order time")
        return None
    ticker = a.get("ticker")
    coid = f"krypt-c15-{a['asset']}-{uuid.uuid4().hex[:8]}"
    ml = a.get("minsLeft")
    strategy = "rules" if cfg.get("crypto15m_use_rules") else mode
    if mode == "model" and ml is not None and float(ml) < 1.0:
        strategy = "model_fm"
    row = {
        "asset": a["asset"], "series": a["series"], "ticker": ticker,
        "side": side, "direction": direction,
        "target_contracts": order_size, "entry_limit_cents": limit_cents,
        "client_order_id": coid, "close_time": a.get("closeTime") or "",
        "confidence": conf, "strategy": strategy,
        "entry_delta_usd": a.get("deltaUsd"), "kalshi_env": env,
        "runner_id": runner_id,
        "mgmt_config": _mgmt_snapshot_json(cfg),
    }

    if paper:
        row.update({"status": "submitted", "dry_run": True})
        with db.get_db() as conn:
            pid = db.insert_crypto15m_position(conn, row)
            logger.info(
                f"[paper] entry {a['asset']} {direction} x{order_size} @ "
                f"{limit_cents}c (runner {runner_id or 'default'})"
            )
            return db.fetch_crypto15m_by_id(conn, pid)

    row.update({"status": "placing", "dry_run": False})
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, row)

    starved = _unfunded_shard(ticker or "")
    if starved and not paper:
        logger.error(
            f"[crypto15m] skip {a.get('asset')}: Kalshi holds $0.00 of your "
            f"collateral on the {starved} exchange shard, which hosts "
            f"{ticker}. Kalshi allocates collateral per shard — move funds to "
            f"{starved} at "
            f"{kalshi_api.web_exchange_indexes_url(kalshi_auth.get_env())} "
            f"and entries will place. Nothing was sent."
        )
        with db.get_db() as conn:
            db.update_crypto15m_position(
                conn, pid,
                error=f"no collateral on the {starved} exchange shard")
            _mark_resolved(conn, pid, status="error")
            return db.fetch_crypto15m_by_id(conn, pid)

    try:
        resp = await kalshi_api.place_limit_order(
            ticker=ticker, side=direction, action="buy",
            count=order_size, price_cents=limit_cents, client_order_id=coid,
        )
    except Exception as e:
        recovered, lookup_ok = await _lookup_lost_order(coid, ticker or "")
        detail = str(e)
        if kalshi_api.is_user_not_found(e):
            try:
                detail = await kalshi_api.explain_order_rejection(
                    e, ticker=ticker or "")
            except Exception:
                pass
        with db.get_db() as conn:
            if isinstance(recovered, dict) and recovered.get("order_id"):
                db.update_crypto15m_position(
                    conn, pid, status="submitted",
                    kalshi_order_id=recovered.get("order_id"),
                )
                logger.warning(
                    f"[crypto15m] entry {a['asset']} recovered via client_order_id "
                    f"after order error: {e}"
                )
            elif lookup_ok:
                db.update_crypto15m_position(conn, pid, error=detail[:400])
                _mark_resolved(conn, pid, status="error")
                logger.error(f"[crypto15m] entry order failed {a['asset']}: {detail}")
            else:
                db.update_crypto15m_position(conn, pid, error=f"UNCONFIRMED: {detail[:160]}")
            return db.fetch_crypto15m_by_id(conn, pid)

    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    with db.get_db() as conn:
        db.update_crypto15m_position(
            conn, pid, status="submitted",
            kalshi_order_id=order.get("order_id") if isinstance(order, dict) else None,
        )
        logger.info(f"[live] entry {a['asset']} {direction} x{order_size} @ {limit_cents}c")
        return db.fetch_crypto15m_by_id(conn, pid)




def _mark_resolved(conn, pid: int, **fields) -> None:
    db.update_crypto15m_position(conn, pid, resolved=1, **fields)
    conn.execute(
        "UPDATE crypto15m_positions SET resolved_at=datetime('now') WHERE id=?", (pid,)
    )


async def _poll_entry(pos: dict, cfg: dict) -> Optional[dict]:
    pid, kid = pos["id"], pos.get("kalshi_order_id")
    if not kid:
        coid = pos.get("client_order_id")
        if not coid:
            return None
        found, confirmed = await _lookup_lost_order(coid, pos.get("ticker") or "")
        with db.get_db() as conn:
            if found and found.get("order_id"):
                db.update_crypto15m_position(
                    conn, pid, status="submitted",
                    kalshi_order_id=found.get("order_id"),
                )
                logger.warning(f"[crypto15m] adopted orphan entry via coid ({pos.get('asset')})")
            elif confirmed:
                _mark_resolved(conn, pid, status="canceled", exit_reason="never_placed")
            return db.fetch_crypto15m_by_id(conn, pid)
    parsed = None
    try:
        resp = await kalshi_api.get_order(kid)
        order = (resp.get("order") if isinstance(resp, dict) else resp) or {}
        parsed = trader._parse_kalshi_order(order)
    except Exception as e:
        logger.debug(f"[crypto15m] entry poll {kid}: {e}")

    filled = int(parsed.get("filled") or 0) if parsed else 0
    remaining = int(parsed.get("remaining") or 0) if parsed else 0

    if filled > 0 and remaining <= 0:
        with db.get_db() as conn:
            db.update_crypto15m_position(
                conn, pid, status="filled",
                filled_contracts=filled,
                cost_usd=parsed["cost_cents"] / 100.0,
                avg_entry_cents=parsed["avg_cents"],
                fees_usd=float(parsed.get("fees_usd") or 0.0),
            )
            return db.fetch_crypto15m_by_id(conn, pid)

    if filled > 0 and filled != int(pos.get("filled_contracts") or 0):
        with db.get_db() as conn:
            db.update_crypto15m_position(
                conn, pid,
                filled_contracts=filled,
                cost_usd=parsed["cost_cents"] / 100.0,
                avg_entry_cents=parsed["avg_cents"],
                fees_usd=float(parsed.get("fees_usd") or 0.0),
            )

    if _entry_expired(pos, cfg):
        return await _cancel_entry_and_finalize(pos, kid, filled)
    return None


async def _cancel_entry_and_finalize(pos: dict, kid: str, filled: int) -> Optional[dict]:
    pid = pos["id"]
    try:
        await kalshi_api.cancel_order(kid, ticker=pos.get("ticker"))
    except Exception:
        pass
    final_filled, final_cost, final_avg, final_fees = filled, None, None, None
    read_ok = False
    final_dead = False
    final_status = ""
    _close_epoch = crypto15m._parse_close_epoch(pos.get("close_time") or "")
    market_closed = (_close_epoch is not None
                     and time.time() > _close_epoch + _CLOSED_ORDER_GRACE_SEC)
    for attempt in range(3):
        try:
            resp2 = await kalshi_api.get_order(kid)
            order2 = (resp2.get("order") if isinstance(resp2, dict) else resp2) or {}
            p2 = trader._parse_kalshi_order(order2)
            read_ok = True
            final_status = str(p2.get("status") or "").lower()
            final_dead = (
                final_status in _DEAD_ORDER_STATUSES
                or int(p2.get("remaining") or 0) <= 0
            )
            if int(p2.get("filled") or 0) >= final_filled:
                final_filled = int(p2["filled"])
                final_cost = p2["cost_cents"] / 100.0
                final_avg = p2["avg_cents"]
                final_fees = float(p2.get("fees_usd") or 0.0)
            break
        except Exception:
            if attempt < 2:
                await asyncio.sleep(0.5)
    with db.get_db() as conn:
        if final_filled > 0:
            upd = {"status": "filled", "filled_contracts": final_filled}
            if final_cost is not None:
                upd["cost_usd"] = final_cost
                upd["avg_entry_cents"] = final_avg
                upd["fees_usd"] = final_fees
            db.update_crypto15m_position(conn, pid, **upd)
        elif read_ok and (final_dead or market_closed):
            _mark_resolved(conn, pid, status="canceled", exit_reason="unfilled_expired")
        else:
            if _warn_once(f"cancel-unconfirmed:{pid}", 120.0):
                logger.warning(
                    f"[crypto15m] {pos.get('asset')} entry {kid}: cancel sent "
                    f"but the order is not confirmed dead "
                    f"(read_ok={read_ok}, status={final_status or '?'!r}) — "
                    f"keeping row open to retry"
                )
        return db.fetch_crypto15m_by_id(conn, pid)


def _entry_expired(pos: dict, cfg: dict) -> bool:
    if _pair_entry_stale(pos):
        return True
    close_epoch = crypto15m._parse_close_epoch(pos.get("close_time") or "")
    if close_epoch is None:
        return False
    lead = max(0.0, float(cfg.get("crypto15m_maker_cancel_min", 0.0) or 0.0)) * 60.0
    return kalshi_auth.server_now() >= close_epoch - lead


_PAIR_ENTRY_TTL_SEC = 30.0
_MARKETABLE_STRATEGIES = ("pair", "model", "model_fm")


def _pair_entry_stale(pos: dict) -> bool:
    if (pos.get("strategy") or "") not in _MARKETABLE_STRATEGIES:
        return False
    ca = str(pos.get("created_at") or "")
    try:
        dt = datetime.strptime(ca[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - dt).total_seconds() > _PAIR_ENTRY_TTL_SEC


async def _protect_partial_entry(pos: dict, cfg: dict) -> Optional[dict]:
    with db.get_db() as conn:
        fresh = db.fetch_crypto15m_by_id(conn, pos["id"]) or pos
    filled = int(fresh.get("filled_contracts") or 0)
    kid = fresh.get("kalshi_order_id")
    if filled <= 0 or not kid or fresh.get("dry_run") or fresh.get("resolved"):
        return None
    market = _ws_quote_market(fresh["ticker"])
    if market is None:
        try:
            market = await kalshi_api.fetch_market(fresh["ticker"])
        except Exception:
            return None
    mid = side_prob_from_market(market, fresh["direction"])
    view = {**fresh, "status": "filled"}
    if not should_stop_loss(view, exec_side_prob(market, fresh.get("side"), mid), cfg):
        return None
    logger.warning(
        f"[crypto15m] stop-loss on PARTIAL entry {fresh.get('asset')} "
        f"({filled}/{fresh.get('target_contracts')} filled) — canceling the "
        f"resting remainder and exiting the filled portion"
    )
    row = await _cancel_entry_and_finalize(fresh, kid, filled)
    if not row or row.get("status") != "filled" or int(row.get("filled_contracts") or 0) <= 0:
        return row
    return await _place_exit(row, market, cfg, reason="stop_loss") or row


async def _place_exit(
    pos: dict, market: Optional[dict], cfg: dict, *, reason: str = "stop_loss"
) -> Optional[dict]:
    pid, ticker, direction = pos["id"], pos["ticker"], pos["direction"]
    filled = int(pos.get("filled_contracts") or 0)
    slippage = _stop_slippage(cfg) if reason == "stop_loss" else 0
    exit_cents: Optional[float] = None
    try:
        book = await kalshi_api.get_orderbook(ticker)
        bids = book.get(direction) or []
        if bids:
            exit_cents = max(float(b[0]) for b in bids if b and b[0] is not None)
    except Exception:
        exit_cents = None
    if exit_cents is None:
        sp = side_prob_from_market(market, direction) or 0.0
        exit_cents = round(sp * 100, 1) - 2
    exit_cents = round(max(0.1, min(99.9, exit_cents - slippage)), 1)

    coid = f"krypt-c15x-{pos['asset']}-{uuid.uuid4().hex[:8]}"
    try:
        resp = await kalshi_api.place_limit_order(
            ticker=ticker, side=direction, action="sell",
            count=filled, price_cents=exit_cents, client_order_id=coid,
        )
    except Exception as e:
        found, confirmed = await _lookup_lost_order(coid, ticker)
        with db.get_db() as conn:
            if found:
                db.update_crypto15m_position(
                    conn, pid, status="exiting", exit_reason=reason,
                    exit_client_order_id=coid,
                    exit_kalshi_order_id=found.get("order_id"),
                    exit_limit_cents=exit_cents,
                )
                logger.warning(f"[live] {reason} sell {pos['asset']}: response lost, recovered via coid")
            elif confirmed:
                db.update_crypto15m_position(conn, pid, error=f"{reason} sell failed: {str(e)[:160]}")
            else:
                db.update_crypto15m_position(
                    conn, pid, status="exiting", exit_reason=reason,
                    exit_client_order_id=coid,
                    error=f"{reason} sell UNCONFIRMED: {str(e)[:120]}",
                )
            return db.fetch_crypto15m_by_id(conn, pid)

    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    label = reason.upper().replace("_", "-")
    with db.get_db() as conn:
        db.update_crypto15m_position(
            conn, pid, status="exiting", exit_reason=reason,
            exit_client_order_id=coid,
            exit_kalshi_order_id=order.get("order_id") if isinstance(order, dict) else None,
            exit_limit_cents=exit_cents,
        )
        logger.info(f"[live] {label} sell {pos['asset']} x{filled} @ {exit_cents}c")
        return db.fetch_crypto15m_by_id(conn, pid)


async def _lookup_lost_order(coid: str, ticker: str) -> tuple[Optional[dict], bool]:
    try:
        found = await kalshi_api.find_order_by_client_id(coid, ticker=ticker)
        return found, True
    except Exception:
        return None, False


async def _poll_exit(pos: dict) -> Optional[dict]:
    pid, kid = pos["id"], pos.get("exit_kalshi_order_id")
    if not kid:
        coid = pos.get("exit_client_order_id")
        if not coid:
            return None
        found, confirmed = await _lookup_lost_order(coid, pos.get("ticker") or "")
        with db.get_db() as conn:
            if found:
                db.update_crypto15m_position(
                    conn, pid, exit_kalshi_order_id=found.get("order_id")
                )
            elif confirmed:
                db.update_crypto15m_position(conn, pid, status="filled")
        return None
    try:
        resp = await kalshi_api.get_order(kid)
        order = (resp.get("order") if isinstance(resp, dict) else resp) or {}
        parsed = trader._parse_kalshi_order(order)
    except Exception:
        return None
    sold = int(parsed.get("filled") or 0)
    remaining = int(parsed.get("remaining") or 0)
    exit_fees = float(parsed.get("fees_usd") or 0.0)
    proceeds = sold - parsed["cost_cents"] / 100.0

    held = int(pos.get("filled_contracts") or 0)
    if sold > 0 and remaining <= 0 and sold >= held:
        pnl = (
            proceeds - float(pos.get("cost_usd") or 0.0)
            - float(pos.get("fees_usd") or 0.0) - exit_fees
        )
        with db.get_db() as conn:
            _mark_resolved(
                conn, pid, status="exited",
                exit_filled_contracts=sold, proceeds_usd=proceeds,
                exit_fees_usd=exit_fees,
                pnl_usd=pnl, outcome_correct=1 if pnl > 0 else 0,
            )
            return db.fetch_crypto15m_by_id(conn, pid)

    if sold > 0 and sold != int(pos.get("exit_filled_contracts") or 0):
        with db.get_db() as conn:
            db.update_crypto15m_position(
                conn, pid, exit_filled_contracts=sold, proceeds_usd=proceeds,
                exit_fees_usd=exit_fees,
            )
    return None


async def _settle_if_closed(pos: dict, *, pin_env: Optional[str] = None) -> Optional[dict]:
    try:
        market = await kalshi_api.fetch_market(pos["ticker"])
    except Exception:
        return None
    payout = trader._market_yes_payout(market) if market else None
    if payout is None:
        return None

    kid = pos.get("exit_kalshi_order_id")
    if not kid and pos.get("exit_client_order_id") and pos.get("status") == "exiting":
        return None
    if kid:
        try:
            await kalshi_api.cancel_order(kid, ticker=pos.get("ticker"), pin_env=pin_env)
        except Exception:
            pass
        try:
            resp = await kalshi_api.get_order(kid, pin_env=pin_env)
            parsed = trader._parse_kalshi_order(
                (resp.get("order") if isinstance(resp, dict) else resp) or {}
            )
            sold_final = int(parsed.get("filled") or 0)
            if sold_final > int(pos.get("exit_filled_contracts") or 0):
                with db.get_db() as conn:
                    db.update_crypto15m_position(
                        conn, pos["id"],
                        exit_filled_contracts=sold_final,
                        proceeds_usd=sold_final - parsed["cost_cents"] / 100.0,
                        exit_fees_usd=float(parsed.get("fees_usd") or 0.0),
                    )
                    pos = db.fetch_crypto15m_by_id(conn, pos["id"]) or pos
        except Exception:
            return None

    filled = int(pos.get("filled_contracts") or 0)
    cost_usd = float(pos.get("cost_usd") or 0.0)
    sold = int(pos.get("exit_filled_contracts") or 0)
    partial_proceeds = float(pos.get("proceeds_usd") or 0.0)
    residual = max(0, filled - sold)
    our = payout if pos["direction"] == "yes" else (1.0 - payout)
    settlement = residual * our
    pnl = (
        partial_proceeds + settlement - cost_usd
        - float(pos.get("fees_usd") or 0.0)
        - float(pos.get("exit_fees_usd") or 0.0)
    )
    correct = 1 if our >= 0.99 else (0 if our <= 0.01 else (1 if pnl > 0.01 else 0))
    with db.get_db() as conn:
        _mark_resolved(
            conn, pos["id"], status="settled",
            exit_reason=pos.get("exit_reason") or "settlement",
            outcome_correct=correct, settlement_usd=settlement, pnl_usd=pnl,
        )
        logger.info(
            f"[crypto15m] exiting->settled {pos['asset']} pnl=${pnl:+.2f} "
            f"(exit sold {sold}/{filled} before close)"
        )
        return db.fetch_crypto15m_by_id(conn, pos["id"])


async def _chase_exit(pos: dict, cfg: dict) -> Optional[dict]:
    if int(pos.get("exit_filled_contracts") or 0) > 0:
        return None
    filled = int(pos.get("filled_contracts") or 0)
    if filled <= 0:
        return None
    direction = pos["direction"]
    reason = pos.get("exit_reason") or "stop_loss"
    cur_limit = float(pos.get("exit_limit_cents") or 0)

    try:
        book = await kalshi_api.get_orderbook(pos["ticker"])
        bids = book.get(direction) or []
        best_bid = max((float(b[0]) for b in bids if b and b[0] is not None), default=0.0)
    except Exception:
        best_bid = 0.0
    if best_bid <= 0:
        return None
    if cur_limit and cur_limit <= best_bid + 1e-9:
        return None

    new_cents = round(max(0.1, min(99.9, best_bid - _stop_slippage(cfg))), 1)
    kid = pos.get("exit_kalshi_order_id")
    if not kid:
        return None
    if kid:
        try:
            await kalshi_api.cancel_order(kid, ticker=pos.get("ticker"))
        except Exception:
            pass
        try:
            resp = await kalshi_api.get_order(kid)
            parsed = trader._parse_kalshi_order(
                (resp.get("order") if isinstance(resp, dict) else resp) or {}
            )
        except Exception:
            return None
        sold = int(parsed.get("filled") or 0)
        if sold > 0:
            proceeds = sold - parsed["cost_cents"] / 100.0
            exit_fees = float(parsed.get("fees_usd") or 0.0)
            with db.get_db() as conn:
                if sold >= filled:
                    pnl = (
                        proceeds - float(pos.get("cost_usd") or 0.0)
                        - float(pos.get("fees_usd") or 0.0) - exit_fees
                    )
                    _mark_resolved(
                        conn, pos["id"], status="exited",
                        exit_filled_contracts=sold, proceeds_usd=proceeds,
                        exit_fees_usd=exit_fees,
                        pnl_usd=pnl, outcome_correct=1 if pnl > 0 else 0,
                    )
                else:
                    db.update_crypto15m_position(
                        conn, pos["id"],
                        exit_filled_contracts=sold, proceeds_usd=proceeds,
                        exit_fees_usd=exit_fees,
                    )
                return db.fetch_crypto15m_by_id(conn, pos["id"])
        if parsed.get("status") not in ("canceled", "cancelled") or sold > 0:
            return None

    coid = f"krypt-c15x-{pos['asset']}-{uuid.uuid4().hex[:8]}"
    try:
        resp = await kalshi_api.place_limit_order(
            ticker=pos["ticker"], side=direction, action="sell",
            count=filled, price_cents=new_cents, client_order_id=coid,
        )
    except Exception as e:
        found, confirmed = await _lookup_lost_order(coid, pos["ticker"])
        with db.get_db() as conn:
            if found:
                db.update_crypto15m_position(
                    conn, pos["id"], status="exiting", exit_reason=reason,
                    exit_client_order_id=coid,
                    exit_kalshi_order_id=found.get("order_id"),
                    exit_limit_cents=new_cents,
                )
                logger.warning(f"[live] {reason} re-price {pos['asset']}: response lost, recovered via coid")
            elif confirmed:
                db.update_crypto15m_position(
                    conn, pos["id"], error=f"{reason} re-price failed: {str(e)[:140]}"
                )
            else:
                db.update_crypto15m_position(
                    conn, pos["id"], status="exiting", exit_reason=reason,
                    exit_client_order_id=coid, exit_kalshi_order_id=None,
                    error=f"{reason} re-price UNCONFIRMED: {str(e)[:120]}",
                )
            return db.fetch_crypto15m_by_id(conn, pos["id"])
    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    with db.get_db() as conn:
        db.update_crypto15m_position(
            conn, pos["id"], status="exiting", exit_reason=reason,
            exit_client_order_id=coid,
            exit_kalshi_order_id=order.get("order_id") if isinstance(order, dict) else None,
            exit_limit_cents=new_cents,
        )
        logger.info(
            f"[live] {reason.upper().replace('_', '-')} re-price {pos['asset']} "
            f"x{filled} @ {new_cents}c (was {cur_limit}c — chasing the bid down)"
        )
        return db.fetch_crypto15m_by_id(conn, pos["id"])


_PAPER_FEE_COEFF = {"maker": 0.0175, "taker": 0.07}


def _paper_fee_usd(price_cents: int, contracts: int, style: str) -> float:
    p = max(0.0, min(1.0, price_cents / 100.0))
    coeff = _PAPER_FEE_COEFF.get(style, 0.07)
    return round(coeff * p * (1.0 - p) * max(0, contracts), 4)


def _paper_side_ask_cents(market: Optional[dict], side: str) -> Optional[float]:
    if not market:
        return None
    yb = crypto15m._price_dollars(market, "yes_bid")
    ya = crypto15m._price_dollars(market, "yes_ask")
    px = ya if side == "up" else ((1.0 - yb) if yb is not None else None)
    if px is None or px <= 0:
        return None
    return max(0.1, min(99.9, round(px * 100, 1)))


def _paper_side_bid_cents(market: Optional[dict], side: str) -> Optional[float]:
    if not market:
        return None
    yb = crypto15m._price_dollars(market, "yes_bid")
    ya = crypto15m._price_dollars(market, "yes_ask")
    px = yb if side == "up" else ((1.0 - ya) if ya is not None else None)
    if px is None or px <= 0:
        return None
    return max(0.1, min(99.9, round(px * 100, 1)))


async def _paper_manage_position(pos: dict, cfg: dict, env: str) -> Optional[dict]:
    pid = pos["id"]
    status = pos.get("status")
    direction = pos["direction"]
    side = pos.get("side")
    market = _ws_quote_market(pos["ticker"])
    if market is None:
        try:
            market = await kalshi_api.fetch_market(pos["ticker"])
        except Exception:
            market = None
    close_epoch = crypto15m._parse_close_epoch(pos.get("close_time") or "")
    closed = close_epoch is not None and kalshi_auth.server_now() >= close_epoch

    if status in ("submitted", "placing"):
        ask_c = _paper_side_ask_cents(market, side)
        if ask_c is not None and ask_c <= int(pos.get("entry_limit_cents") or 0):
            contracts = int(pos.get("target_contracts") or 0)
            if contracts > 0:
                style = (cfg.get("crypto15m_entry_style") or "maker").lower()
                fill_c = ask_c if style == "taker" else int(pos.get("entry_limit_cents") or ask_c)
                cost = contracts * fill_c / 100.0
                fee = _paper_fee_usd(fill_c, contracts, style)
                with db.get_db() as conn:
                    db.update_crypto15m_position(
                        conn, pid, status="filled", filled_contracts=contracts,
                        avg_entry_cents=fill_c, cost_usd=cost, fees_usd=fee,
                    )
                    logger.info(f"[paper] fill {pos['asset']} x{contracts} @ {fill_c}c")
                    return db.fetch_crypto15m_by_id(conn, pid)
        if closed or _entry_expired(pos, cfg):
            with db.get_db() as conn:
                _mark_resolved(conn, pid, status="canceled", exit_reason="unfilled_expired")
                return db.fetch_crypto15m_by_id(conn, pid)
        return None

    if status == "filled":
        if closed:
            return await _settle_if_closed(pos)
        side_prob = side_prob_from_market(market, direction)
        reason = None
        if should_take_profit(pos, side_prob, cfg):
            reason = "take_profit"
        elif should_stop_loss(pos, exec_side_prob(market, side, side_prob), cfg):
            reason = "stop_loss"
        if reason:
            bid_c = _paper_side_bid_cents(market, side)
            if bid_c is None:
                return None
            slip = _stop_slippage(cfg) if reason == "stop_loss" else 0
            exit_c = max(1, bid_c - slip)
            filled = int(pos.get("filled_contracts") or 0)
            cost = float(pos.get("cost_usd") or 0.0)
            proceeds = filled * exit_c / 100.0
            fee = _paper_fee_usd(exit_c, filled, "taker")
            pnl = proceeds - cost - float(pos.get("fees_usd") or 0.0) - fee
            with db.get_db() as conn:
                _mark_resolved(
                    conn, pid, status="settled", exit_reason=reason,
                    settlement_usd=proceeds, proceeds_usd=proceeds,
                    exit_filled_contracts=filled, exit_fees_usd=fee, pnl_usd=pnl,
                    outcome_correct=1 if pnl > 0.01 else 0,
                )
                logger.info(f"[paper] {reason} {pos['asset']} pnl=${pnl:+.2f}")
                return db.fetch_crypto15m_by_id(conn, pid)
        return None

    if closed:
        return await _settle_if_closed(pos)
    return None


async def _manage_position(pos: dict, cfg: dict, env: str) -> Optional[dict]:
    status = pos.get("status")
    cfg = _with_mgmt_snapshot(pos, cfg)

    if pos.get("dry_run"):
        return await _paper_manage_position(pos, cfg, env)

    if status in ("submitted", "placing"):
        row = await _poll_entry(pos, cfg)
        if row is None and status == "submitted":
            row = await _protect_partial_entry(pos, cfg)
        return row
    if status == "exiting":
        row = await _poll_exit(pos)
        if row:
            return row
        with db.get_db() as conn:
            pos = db.fetch_crypto15m_by_id(conn, pos["id"]) or pos
        row = await _chase_exit(pos, cfg)
        if row:
            return row
        return await _settle_if_closed(pos)
    if status == "error" and int(pos.get("filled_contracts") or 0) <= 0:
        with db.get_db() as conn:
            _mark_resolved(conn, pos["id"], status="error")
            return db.fetch_crypto15m_by_id(conn, pos["id"])
    if status != "filled":
        return None

    if (pos.get("strategy") or "") == "pair":
        return await _manage_pair(pos)

    pid = pos["id"]
    direction = pos["direction"]
    filled = int(pos.get("filled_contracts") or 0)
    cost_usd = float(pos.get("cost_usd") or 0.0)

    market = None
    ws_market = False
    close_epoch = crypto15m._parse_close_epoch(pos.get("close_time") or "")
    if close_epoch is not None and kalshi_auth.server_now() < close_epoch - 2:
        market = _ws_quote_market(pos["ticker"])
        ws_market = market is not None
    if market is None:
        try:
            market = await kalshi_api.fetch_market(pos["ticker"])
        except Exception:
            market = None

    payout = trader._market_yes_payout(market) if (market and not ws_market) else None
    if payout is not None:
        our = payout if direction == "yes" else (1.0 - payout)
        settlement = filled * our
        pnl = settlement - cost_usd - float(pos.get("fees_usd") or 0.0)
        correct = 1 if our >= 0.99 else (0 if our <= 0.01 else (1 if pnl > 0.01 else 0))
        with db.get_db() as conn:
            _mark_resolved(
                conn, pid, status="settled",
                exit_reason=(pos.get("exit_reason") or "settlement"),
                outcome_correct=correct, settlement_usd=settlement, pnl_usd=pnl,
            )
            return db.fetch_crypto15m_by_id(conn, pid)

    side_prob = side_prob_from_market(market, direction)
    if should_take_profit(pos, side_prob, cfg):
        return await _place_exit(pos, market, cfg, reason="take_profit")
    if should_stop_loss(pos, exec_side_prob(market, pos.get("side"), side_prob), cfg):
        return await _place_exit(pos, market, cfg, reason="stop_loss")

    return None




_PAIR_FIRST_LEG_MIN_MINS = 5.0
_PAIR_LEG_MIN_MINS = 1.0
_PAIR_HIST_MIN = 8
_PAIR_FIRST_HIST_MIN = 20
_PAIR_MAX_UNMATCHED = 2

_pair_ask_hist: dict[str, dict[str, deque]] = {}


def _update_pair_hist(assets: dict) -> None:
    live_tickers = set()
    for a in assets.values():
        t = a.get("ticker")
        if not a.get("hasMarket") or not t:
            continue
        live_tickers.add(t)
        hist = _pair_ask_hist.setdefault(
            t, {"yes": deque(maxlen=45), "no": deque(maxlen=45)}
        )
        ya, na = a.get("upAsk"), a.get("downAsk")
        if ya:
            hist["yes"].append(round(float(ya) * 100.0, 1))
        if na:
            hist["no"].append(round(float(na) * 100.0, 1))
    for t in [t for t in _pair_ask_hist if t not in live_tickers]:
        _pair_ask_hist.pop(t, None)


def _pair_leg_ok(
    ask_cents: float,
    own_hist,
    other_hist,
    *,
    other_cost_cents: Optional[float],
    ceiling_cents: float,
    dip_cents: float,
    first_leg_max_cents: float,
    mins_left: float,
    first_leg_min_cents: float = 35.0,
) -> tuple[bool, str]:
    if mins_left < _PAIR_LEG_MIN_MINS:
        return False, "final minute"
    if len(own_hist) < _PAIR_HIST_MIN:
        return False, "history warming up"
    med = statistics.median(own_hist)
    if med - ask_cents < dip_cents:
        return False, f"no dip (ask {ask_cents:.0f}c vs median {med:.0f}c)"
    if other_cost_cents is not None:
        if ask_cents + 1 > ceiling_cents - other_cost_cents:
            return False, (
                f"pair would cost up to {ask_cents + 1 + other_cost_cents:.0f}c "
                f"> {ceiling_cents:.0f}c ceiling"
            )
        return True, "ok"
    if mins_left < _PAIR_FIRST_LEG_MIN_MINS:
        return False, "too late to start a pair"
    if len(own_hist) < _PAIR_FIRST_HIST_MIN or len(other_hist) < _PAIR_FIRST_HIST_MIN:
        return False, "window too young for a first leg (~80s of ticks needed)"
    if ask_cents < first_leg_min_cents:
        return False, (
            f"first leg {ask_cents:.0f}c < {first_leg_min_cents:.0f}c floor "
            f"(strong favorite against — trend, not seesaw)"
        )
    if ask_cents > first_leg_max_cents:
        return False, f"first leg {ask_cents:.0f}c > {first_leg_max_cents:.0f}c max"
    if len(other_hist) < _PAIR_HIST_MIN:
        return False, "other side history warming up"
    expected_other = min(other_hist)
    if ask_cents > ceiling_cents - expected_other:
        return False, (
            f"complement unlikely to fit (other side's recent low "
            f"{expected_other:.0f}c, needs ≤ {ceiling_cents - ask_cents:.0f}c)"
        )
    return True, "ok"


async def _open_pair_leg(
    a: dict, cfg: dict, env: str, *, direction: str, count: int, limit_cents: int,
    runner_id: str = "",
) -> Optional[dict]:
    ticker = a["ticker"]
    coid = f"krypt-c15p-{a['asset']}-{direction}-{uuid.uuid4().hex[:8]}"
    row = {
        "asset": a["asset"], "series": a["series"], "ticker": ticker,
        "side": "up" if direction == "yes" else "down", "direction": direction,
        "target_contracts": count, "entry_limit_cents": limit_cents,
        "client_order_id": coid, "close_time": a.get("closeTime") or "",
        "confidence": float(limit_cents), "kalshi_env": env,
        "strategy": "pair", "runner_id": runner_id,
    }
    try:
        resp = await kalshi_api.place_limit_order(
            ticker=ticker, side=direction, action="buy",
            count=count, price_cents=limit_cents, client_order_id=coid,
        )
    except Exception as e:
        recovered, lookup_ok = await _lookup_lost_order(coid, ticker or "")
        if isinstance(recovered, dict) and recovered.get("order_id"):
            row.update({"status": "submitted",
                        "kalshi_order_id": recovered.get("order_id"),
                        "dry_run": False})
            with db.get_db() as conn:
                pid = db.insert_crypto15m_position(conn, row)
                logger.warning(
                    f"[pairs] {a['asset']} {direction} leg recovered via "
                    f"client_order_id after order error: {e}"
                )
                return db.fetch_crypto15m_by_id(conn, pid)
        if not lookup_ok:
            row.update({"status": "placing", "dry_run": False,
                        "error": f"UNCONFIRMED: {str(e)[:160]}"})
            with db.get_db() as conn:
                pid = db.insert_crypto15m_position(conn, row)
                logger.warning(
                    f"[pairs] {a['asset']} {direction} leg: POST failed ({e}) "
                    f"AND the lookup failed — order may be LIVE; keeping the "
                    f"row open to resolve next tick"
                )
                return db.fetch_crypto15m_by_id(conn, pid)

        row.update({"status": "error", "error": str(e)[:200], "dry_run": False})
        with db.get_db() as conn:
            pid = db.insert_crypto15m_position(conn, row)
            _mark_resolved(conn, pid, status="error")
            logger.error(f"[pairs] {a['asset']} {direction} leg failed: {e}")
            return db.fetch_crypto15m_by_id(conn, pid)

    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    row.update({
        "status": "submitted",
        "kalshi_order_id": order.get("order_id") if isinstance(order, dict) else None,
        "dry_run": False,
    })
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, row)
        logger.info(
            f"[live] PAIR {a['asset']} {direction} x{count} @ {limit_cents}c"
        )
        return db.fetch_crypto15m_by_id(conn, pid)


async def _run_pairs(
    cfg: dict, env: str, assets: dict, open_positions: list[dict],
    balance_usd: float, runner_id: str = "",
) -> list[dict]:
    if not crypto15m.hours_ok(cfg):
        return []
    ceiling = float(cfg.get("crypto15m_pairs_ceiling_cents", 95.0) or 95.0)
    dip = float(cfg.get("crypto15m_pairs_dip_cents", 2.0) or 2.0)
    clip = max(1, int(cfg.get("crypto15m_pairs_clip", 5) or 5))
    first_min = float(cfg.get("crypto15m_pairs_first_leg_min_cents", 35.0) or 35.0)
    first_max = float(cfg.get("crypto15m_pairs_first_leg_max_cents", 60.0) or 60.0)
    cap_pct = _clamp01(cfg.get("crypto15m_max_total_pct", 0.0))

    pair_rows: dict[tuple[str, str], dict] = {}
    directional_assets: set[str] = set()
    for p in open_positions:
        if (p.get("strategy") or "") == "pair":
            pair_rows[(p.get("ticker") or "", p.get("direction") or "")] = p
        else:
            directional_assets.add(p.get("asset") or "")

    def _unmatched_count() -> int:
        tickers: dict[str, int] = {}
        for (tk, _d) in pair_rows:
            tickers[tk] = tickers.get(tk, 0) + 1
        return sum(1 for n in tickers.values() if n == 1)

    with db.get_db() as conn:
        errored = db.crypto15m_errored_tickers(conn, env)

    updated: list[dict] = []
    for sym, a in assets.items():
        t = a.get("ticker")
        if not a.get("hasMarket") or not t or t in errored:
            continue
        if not crypto15m.asset_enabled(cfg, sym):
            continue
        if sym in directional_assets:
            continue
        mins_left = a.get("minsLeft")
        if mins_left is None:
            continue
        hist = _pair_ask_hist.get(t) or {"yes": deque(), "no": deque()}

        for direction, ask_key in (("yes", "upAsk"), ("no", "downAsk")):
            if (t, direction) in pair_rows:
                continue
            ask = a.get(ask_key)
            if not ask or not (0.0 < float(ask) < 1.0):
                continue
            ask_c = round(float(ask) * 100.0, 1)
            other_dir = "no" if direction == "yes" else "yes"
            other = pair_rows.get((t, other_dir))
            other_cost: Optional[float] = None
            count = clip
            if other is not None:
                filled = int(other.get("filled_contracts") or 0)
                if filled <= 0:
                    continue
                other_cost = float(other.get("avg_entry_cents") or
                                   other.get("entry_limit_cents") or 0)
                count = filled
            elif _unmatched_count() >= _PAIR_MAX_UNMATCHED:
                continue
            else:
                mp = a.get("modelProb")
                if mp is not None and (
                    (direction == "yes" and mp < 0.35)
                    or (direction == "no" and mp > 0.65)
                ):
                    continue
            ok, why = _pair_leg_ok(
                ask_c, hist.get(direction) or [], hist.get(other_dir) or [],
                other_cost_cents=other_cost, ceiling_cents=ceiling,
                dip_cents=dip, first_leg_max_cents=first_max,
                mins_left=float(mins_left),
                first_leg_min_cents=first_min,
            )
            if not ok:
                continue
            limit_cents = max(1, min(99, int(round(ask_c)) + 1))
            if cap_pct > 0 and balance_usd > 0:
                with db.get_db() as conn:
                    committed = db.open_crypto15m_committed_usd(conn, env)
                    filled_cost = db.open_crypto15m_filled_cost_usd(conn, env)
                budget = (balance_usd + filled_cost) * cap_pct - committed
                if count * limit_cents / 100.0 > budget:
                    logger.info(
                        f"[pairs] skip {sym} {direction}: aggregate 15m cap "
                        f"(${committed:.2f} committed)"
                    )
                    continue
            row = await _open_pair_leg(
                a, cfg, env, direction=direction, count=count,
                limit_cents=limit_cents, runner_id=runner_id,
            )
            if row:
                updated.append(row)
                pair_rows[(t, direction)] = row
                if other is not None and (row.get("status") or "") != "error":
                    oc = other_cost or 0.0
                    logger.info(
                        f"[pairs] {sym} pair complete: blended ≤ "
                        f"{limit_cents + oc:.0f}c vs {ceiling:.0f}c ceiling "
                        f"({count} matched)"
                    )
    return updated


async def _manage_pair(pos: dict) -> Optional[dict]:
    close_epoch = crypto15m._parse_close_epoch(pos.get("close_time") or "")
    if close_epoch is not None and kalshi_auth.server_now() < close_epoch - 2:
        return None
    try:
        market = await kalshi_api.fetch_market(pos["ticker"])
    except Exception:
        return None
    payout = trader._market_yes_payout(market) if market else None
    if payout is None:
        return None
    filled = int(pos.get("filled_contracts") or 0)
    cost_usd = float(pos.get("cost_usd") or 0.0)
    our = payout if pos["direction"] == "yes" else (1.0 - payout)
    settlement = filled * our
    pnl = settlement - cost_usd - float(pos.get("fees_usd") or 0.0)
    correct = 1 if our >= 0.99 else (0 if our <= 0.01 else (1 if pnl > 0.01 else 0))
    with db.get_db() as conn:
        _mark_resolved(
            conn, pos["id"], status="settled", exit_reason="settlement",
            outcome_correct=correct, settlement_usd=settlement, pnl_usd=pnl,
        )
        return db.fetch_crypto15m_by_id(conn, pos["id"])


def session_take_profit_target(cfg: dict) -> float:
    try:
        return max(0.0, float(cfg.get("crypto15m_session_take_profit_usd", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def session_realized_pnl(env: str, session_start: Optional[str]) -> float:
    with db.get_db() as conn:
        return db.crypto15m_session_realized_pnl(conn, env, session_start)


def is_blocked_by_session_take_profit(
    cfg: dict, env: str, session_start: Optional[str]
) -> tuple[bool, str, float]:
    target = session_take_profit_target(cfg)
    pnl = session_realized_pnl(env, session_start)
    if target > 0 and pnl >= target:
        return True, (
            f"15m session take-profit hit (session pnl=${pnl:+.2f}, "
            f"target=${target:+.2f})"
        ), pnl
    return False, "", pnl


def _runner_needs_balance(cfg: dict) -> bool:
    return (
        (cfg.get("crypto15m_sizing_mode") or "fixed").lower() == "balance_pct"
        or float(cfg.get("crypto15m_max_loss_pct") or 0.0) > 0.0
        or _clamp01(cfg.get("crypto15m_max_total_pct", 0.0)) > 0.0
        or bool(cfg.get("crypto15m_pairs_enabled"))
    )


def _resolve_runners(cfg: dict) -> list[dict]:
    raw = cfg.get("crypto15m_runners")
    all_assets = list(crypto15m.ALL_ASSETS)
    if not raw:
        coins = [a for a in all_assets if crypto15m.asset_enabled(cfg, a)]
        return [{
            "id": "", "name": "Default", "mode": "live",
            "enabled": bool(cfg.get("crypto15m_live")),
            "coins": coins, "cfg": cfg,
        }]
    valid = set(all_assets)
    claimed: set[str] = set()
    cur_hour = datetime.fromtimestamp(kalshi_auth.server_now(), timezone.utc).hour
    out: list[dict] = []
    for r in raw:
        rid = str(r.get("id") or "")
        rc = r.get("coins")
        if rc is None:
            cand = [a for a in all_assets if a not in claimed]
        else:
            cand = [a for a in rc if a in valid and a not in claimed]
        if r.get("enabled"):
            claimed.update(cand)
        active_cfg = dict(r.get("config") or {})
        entry_coins = cand
        sched = r.get("schedule")
        if sched:
            slot = next((s for s in sched
                         if int(s.get("startHour", 0)) <= cur_hour < int(s.get("endHour", 0))), None)
            if slot is None:
                entry_coins = []
            else:
                active_cfg.update(slot.get("config") or {})
        out.append({
            "id": rid,
            "name": r.get("name") or rid or "runner",
            "mode": (r.get("mode") or "paper"),
            "enabled": bool(r.get("enabled")),
            "coins": entry_coins,
            "cfg": {**cfg, **active_cfg},
            "scheduled": bool(sched),
        })
    return out


def _runner_cfg_for(pos: dict, runners: list[dict], base_cfg: dict) -> dict:
    rid = pos.get("runner_id") or ""
    for r in runners:
        if r["id"] == rid:
            return r["cfg"]
    return base_cfg


async def _run_runner_entries(
    r: dict, env: str, assets: dict, open_positions: list[dict],
    updated: list[dict], held: set[str], errored: set[str], stopped: set[str],
    live_ok: bool, balance_usd: float,
) -> list[dict]:
    rcfg = r["cfg"]
    paper = r["mode"] == "paper"
    rlive = (r["mode"] == "live") and live_ok
    if not (paper or rlive):
        for sym in r["coins"]:
            _block_reasons.setdefault(sym, "live runner not armed (needs production + auth)")
        return []
    out: list[dict] = []
    open_count = len([
        p for p in open_positions
        if (p.get("runner_id") or "") == r["id"] and (p.get("strategy") or "") != "pair"
    ])
    if rcfg.get("crypto15m_directional_enabled", True):
        for sym in r["coins"]:
            a = assets.get(sym)
            if a is None or sym in held:
                continue
            t = a.get("ticker")
            if t in errored or t in stopped:
                continue
            ok, why = should_enter(a, rcfg, has_open=False, open_count=open_count)
            if not ok:
                _block_reasons[sym] = why
                continue
            try:
                row = await _open_entry(
                    a, rcfg, env, balance_usd, runner_id=r["id"], paper=paper
                )
                if row:
                    out.append(row)
                    held.add(sym)
                    open_count += 1
            except Exception as e:
                logger.warning(f"[crypto15m] entry {sym} failed: {e}")
    if rcfg.get("crypto15m_pairs_enabled") and not paper:
        scoped = {s: assets[s] for s in r["coins"] if s in assets}
        live_rows = open_positions + [x for x in (updated + out) if x and not x.get("resolved")]
        try:
            out.extend(await _run_pairs(rcfg, env, scoped, live_rows, balance_usd, runner_id=r["id"]))
        except Exception as e:
            logger.warning(f"[pairs] runner {r['id'] or 'default'} tick failed: {e}")
    return out


_STALE_GIVEUP_SEC = 60 * 60


async def _reap_stale(pos: dict) -> Optional[dict]:
    pid = pos["id"]
    filled = int(pos.get("filled_contracts") or 0)
    with db.get_db() as conn:
        if filled <= 0:
            _mark_resolved(conn, pid, status="canceled", exit_reason="unfilled_expired")
        else:
            _mark_resolved(conn, pid, status="error",
                           error="stale: unsettleable >1h past close (manual review)")
        row = db.fetch_crypto15m_by_id(conn, pid)
    logger.warning(
        f"[crypto15m] REAPED stale {pos.get('asset')} id={pid} filled={filled} "
        f"env={pos.get('kalshi_env')} — freed slot/cap (PnL left for manual review)"
    )
    return row


async def _sweep_other_envs_and_reap(active_env: str) -> list[dict]:
    out: list[dict] = []
    now = kalshi_auth.server_now()
    for env in ("production", "demo"):
        with db.get_db() as conn:
            rows = db.get_open_crypto15m(conn, env)
        for pos in rows:
            ce = crypto15m._parse_close_epoch(pos.get("close_time") or "")
            if ce is None or now < ce:
                continue
            if env != active_env:
                try:
                    row = await _settle_if_closed(pos, pin_env=env)
                except Exception as e:
                    logger.warning(f"[crypto15m] cross-env settle {pos.get('asset')} ({env}) failed: {e}")
                    row = None
                if row:
                    out.append(row)
                    continue
            if now - ce >= _STALE_GIVEUP_SEC:
                reaped = await _reap_stale(pos)
                if reaped:
                    out.append(reaped)
    return out


async def run_tick(
    cfg: dict, *, authed: bool, session_start: Optional[str] = None
) -> list[dict]:
    env = trader.get_env()
    runners = _resolve_runners(cfg)

    with db.get_db() as conn:
        open_positions = db.get_open_crypto15m(conn, env)
        errored_tickers = db.crypto15m_errored_tickers(conn, env)
        stopped_tickers = db.crypto15m_stopped_tickers(conn, env)

    updated: list[dict] = []
    feature_on = bool(cfg.get("crypto15m_enabled"))
    assets: dict = {}
    if feature_on:
        snap = await crypto15m.snapshot(cfg)
        assets = {a["asset"]: a for a in snap.get("assets", [])}
        _update_pair_hist(assets)

    for pos in open_positions:
        try:
            row = await _manage_position(pos, _runner_cfg_for(pos, runners, cfg), env)
            if row:
                updated.append(row)
        except Exception as e:
            logger.warning(f"[crypto15m] manage {pos.get('asset')} failed: {e}")

    try:
        updated.extend(await _sweep_other_envs_and_reap(env))
    except Exception as e:
        logger.warning(f"[crypto15m] stale sweep failed: {e}")

    if not feature_on:
        return updated
    enabled = [r for r in runners if r["enabled"]]
    if not enabled:
        return updated

    blocked, why = trader._is_blocked_by_daily_risk(cfg, env)
    if blocked:
        logger.info(f"[crypto15m] skip entries: {why}")
        return updated

    _block_reasons.clear()
    tp_blocked, tp_why, _tp_pnl = is_blocked_by_session_take_profit(cfg, env, session_start)
    if tp_blocked:
        logger.info(f"[crypto15m] skip entries: {tp_why}")
        return updated

    live_ok = bool(authed) and env == "production"
    need_balance = any(_runner_needs_balance(r["cfg"]) for r in enabled)
    balance_usd = await _bankroll_usd(cfg, bool(authed)) if need_balance else 0.0

    held = {p["asset"] for p in open_positions}
    for r in enabled:
        try:
            updated.extend(await _run_runner_entries(
                r, env, assets, open_positions, updated, held,
                errored_tickers, stopped_tickers, live_ok, balance_usd,
            ))
        except Exception as e:
            logger.warning(f"[crypto15m] runner {r.get('id') or 'default'} failed: {e}")

    return updated


async def _sizing_preview(cfg: dict, authed: bool) -> dict:
    mode = (cfg.get("crypto15m_sizing_mode") or "fixed").lower()
    balance_pct = _clamp01(cfg.get("crypto15m_balance_pct", 0.02))
    max_loss_pct = _clamp01(cfg.get("crypto15m_max_loss_pct", 0.0))
    order_size = max(1, int(cfg.get("crypto15m_order_size", 1)))
    bal = await _bankroll_usd(cfg, bool(authed))

    thr = crypto15m._const(cfg, "entry_threshold")
    mode_now = (cfg.get("crypto15m_direction_mode") or "favorite").lower()
    if mode_now == "contrarian":
        base = 1.0 - thr
    elif mode_now == "model":
        base = 0.93
    else:
        base = thr
    if (cfg.get("crypto15m_entry_style") or "maker") == "maker":
        est_price_cents = max(1, min(99, int(round(base * 100)) - 1))
    else:
        est_price_cents = entry_limit_cents(base, crypto15m._const(cfg, "entry_diff"))
    est_contracts = compute_entry_contracts(
        cfg, entry_limit_cents=est_price_cents, balance_usd=bal, order_size=order_size,
    )
    est_cost = est_contracts * est_price_cents / 100.0

    note = ""
    if mode == "balance_pct" and bal <= 0:
        note = "No balance yet — using fixed order size. Connect Kalshi or set a start bankroll to size by %."
    elif max_loss_pct > 0 and bal > 0 and est_contracts < 1:
        note = f"Max-loss budget too small to fund a contract at ~{est_price_cents}c."

    return {
        "mode": mode,
        "balancePct": balance_pct,
        "maxLossPct": max_loss_pct,
        "balanceUsd": bal,
        "estPriceCents": est_price_cents,
        "estContracts": est_contracts,
        "estCostUsd": est_cost,
        "note": note,
    }


def _shard_funding(cfg: dict) -> dict:
    series = crypto15m.SERIES[0]["series"] if crypto15m.SERIES else ""
    idx = kalshi_api.shard_for_ticker(series)
    shards = trader.cached_shard_balances()
    here = None
    if shards and idx is not None:
        here = shards.get(int(idx))

    size = max(1, int(cfg.get("crypto15m_order_size", 1)))
    concurrent = max(1, int(cfg.get("crypto15m_max_concurrent",
                                    len(crypto15m.SERIES))))
    return {
        "index": idx,
        "name": kalshi_api.shard_name(idx) if idx is not None else None,
        "cashUsd": round(here, 2) if here is not None else None,
        "starved": bool(here is not None and here <= 0),
        "known": bool(idx is not None and here is not None),
        "perEntryMaxUsd": round(size * 1.0, 2),
        "allOpenMaxUsd": round(size * concurrent * 1.0, 2),
        "shards": ([{"index": int(i), "name": kalshi_api.shard_name(i),
                     "cashUsd": round(v, 2)}
                    for i, v in sorted(shards.items())] if shards else []),
        "transferUrl": kalshi_api.web_exchange_indexes_url(trader.get_env()),
    }

async def status(
    cfg: dict, *, authed: bool = False, session_start: Optional[str] = None
) -> dict:
    env = trader.get_env()
    with db.get_db() as conn:
        open_rows = db.get_open_crypto15m(conn, env)
        recent = db.recent_crypto15m(conn, env, limit=40)
        by_strategy = db.crypto15m_strategy_stats(conn, env)
        runner_stats = db.crypto15m_runner_stats(conn, env)
        stats = db.crypto15m_stats(conn, env)
    agg: dict[str, dict] = {}
    for s in runner_stats:
        b = agg.setdefault(s["runner_id"], {"n": 0, "wins": 0, "losses": 0, "pnlUsd": 0.0, "openN": 0})
        b["n"] += s["n"]
        b["wins"] += s["wins"]
        b["losses"] += s["losses"]
        b["pnlUsd"] += s["pnl_usd"] or 0.0
        b["openN"] += s["open_n"]
    runners_out = []
    for r in _resolve_runners(cfg):
        st = agg.get(r["id"], {})
        runners_out.append({
            "id": r["id"], "name": r["name"], "mode": r["mode"],
            "enabled": r["enabled"], "coins": r["coins"],
            "n": st.get("n", 0), "wins": st.get("wins", 0), "losses": st.get("losses", 0),
            "pnlUsd": round(st.get("pnlUsd", 0.0), 4), "openN": st.get("openN", 0),
        })
    live_armed = bool(cfg.get("crypto15m_live"))
    live_supported = env == "production"
    tp_target = session_take_profit_target(cfg)
    session_pnl = session_realized_pnl(env, session_start)
    return {
        "enabled": bool(cfg.get("crypto15m_enabled")),
        "blockReasons": dict(_block_reasons),
        "modelCalibration": dict(_CAL_CACHE),
        "live": bool(cfg.get("crypto15m_enabled")) and live_armed and bool(authed) and live_supported,
        "liveArmed": live_armed,
        "liveSupported": live_supported,
        "authed": bool(authed),
        "orderSize": int(cfg.get("crypto15m_order_size", 1)),
        "maxConcurrent": int(cfg.get("crypto15m_max_concurrent", len(crypto15m.SERIES))),
        "takeProfitCents": take_profit_cents(cfg),
        "sessionTakeProfitUsd": tp_target,
        "sessionPnlUsd": session_pnl,
        "takeProfitHalted": bool(tp_target > 0 and session_pnl >= tp_target),
        "sizing": await _sizing_preview(cfg, authed),
        "shardFunding": _shard_funding(cfg),
        "env": env,
        "stats": stats,
        "byStrategy": by_strategy,
        "runners": runners_out,
        "open": [_pos_to_js(r) for r in open_rows],
        "recent": [_pos_to_js(r) for r in recent],
    }
