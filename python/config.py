from __future__ import annotations
from typing import Any

import rules


DEFAULT_CONFIG: dict[str, Any] = {
    "account_mode": "paper",
    "paper_bankroll_usd": 1000.0,
    "shard_auto_move": True,
    "shard_auto_move_max_usd_day": 1000.0,
    "enable_trading": False,
    "auto_upgrade_api_level": True,

    "trade_whales": True,
    "trade_momentum": True,
    "trade_convergence": False,

    "min_edge_pts_whale": 5.0,
    "min_edge_pts_momentum": 5.0,
    "min_confidence_whale": 55.0,
    "min_confidence_momentum": 55.0,
    "fee_aware_edge": True,
    "max_entry_slippage_cents": 5,
    "min_market_volume": 100.0,
    "max_trade_age_min": 15,
    "min_entry_price_cents": 15,
    "max_entry_price_cents": 85,
    "max_resolution_days": 30,
    "allowed_momentum_signal_types": ["trade_cluster"],
    "allowed_categories": None,
    "allowed_whale_categories": None,
    "allowed_momentum_categories": None,
    "contrarian_only": True,

    "sizing_mode": "percent",
    "fixed_trade_usd": 5.0,

    "base_size_fraction": 0.03,
    "min_size_fraction": 0.02,
    "max_size_fraction": 0.06,
    "sizing_base_edge": 5.0,
    "sizing_max_edge": 10.0,
    "hard_max_position_usd": 50.0,
    "min_cash_reserve_fraction": 0.05,

    "order_style": "limit_cross",
    "cross_spread_fallback_offset": 2,
    "order_expiration_sec": 90,

    "max_open_positions": 25,
    "max_positions_per_event": 1,
    "max_daily_new_positions": 40,
    "unlimited_daily_new_positions": False,
    "max_total_exposure_fraction": 0.35,

    "trade_scan_interval": 20,
    "position_poll_interval": 30,
    "balance_poll_interval": 60,
    "resolution_check_interval": 300,
    "whale_scan_interval": 120,
    "momentum_scan_interval": 90,
    "market_refresh_interval": 300,
    "db_cleanup_interval": 3600,

    "max_signal_age_sec": 120,

    "start_bankroll_usd": 0.0,
    "stop_loss_on_day": -50.0,
    "stop_loss_on_day_pct": 0.05,
    "take_profit_on_day": 0.0,

    "trading_hours_enabled": False,
    "trading_hours_start": "00:00",
    "trading_hours_end": "23:59",
    "trading_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    "trading_timezone_offset_min": 0,

    "min_whale_usd": 2500.0,
    "min_entry_price_frac": 0.50,

    "crypto15m_time_delay_min": 8.0,
    "crypto15m_entry_threshold": 0.70,
    "crypto15m_strict_threshold": True,
    "crypto15m_entry_max": 0.98,
    "crypto15m_exit_threshold": 0.40,
    "crypto15m_stop_slippage_cents": 0,
    "crypto15m_take_profit_cents": 0,
    "crypto15m_stop_loss_pct": 0.0,
    "crypto15m_session_take_profit_usd": 0.0,
    "crypto15m_min_delta_pct": 0.0,
    "crypto15m_min_rsi": 0.0,
    "crypto15m_min_macd_hist": 0.0,
    "crypto15m_entry_diff": 0.02,
    "crypto15m_entry_style": "maker",
    "crypto15m_maker_cancel_min": 1.0,
    "crypto15m_hours_start_utc": 0,
    "crypto15m_hours_end_utc": 24,
    "crypto15m_hours": None,
    "crypto15m_enabled": False,
    "crypto15m_live": False,
    "crypto15m_sizing_mode": "fixed",
    "crypto15m_order_size": 1,
    "crypto15m_balance_pct": 0.02,
    "crypto15m_max_loss_pct": 0.0,
    "crypto15m_max_total_pct": 0.10,
    "crypto15m_max_concurrent": 3,
    "crypto15m_assets": None,
    "crypto15m_runners": None,
    "crypto15m_poll_sec": 4,
    "crypto15m_direction_mode": "favorite",
    "crypto15m_model_min_prob": 0.97,
    "crypto15m_model_min_edge_cents": 2.0,
    "crypto15m_model_final_minute": True,
    "crypto15m_model_midwindow": False,
    "crypto15m_model_autopause": True,
    "crypto15m_record_signals": True,
    "main_record_signals": True,

    "scripts_live_enabled": False,
    "scripts_paper_mode": False,
    "script_poll_sec": 5,
    "script_max_entry_cents": 97,
    "script_max_contracts": 20,
    "script_max_open": 2,
    "script_daily_loss_usd": 25.0,
    "script_max_enabled": 10,

    "remote_discord_enabled": False,
    "remote_telegram_enabled": False,
    "remote_trading_enabled": False,
    "remote_alerts_enabled": True,
    "remote_discord_user_id": "",
    "remote_telegram_chat_id": "",

    "ai_provider": "anthropic",
    "ai_model": "claude-opus-5",
    "ai_web_search": False,

    "mcp_enabled": False,
    "mcp_port": 47821,
    "mcp_trade_mode": "paper",
    "mcp_max_order_usd": 25.0,
    "mcp_daily_spend_usd": 100.0,
    "mcp_max_positions": 10,
    "mcp_min_edge_cents": 3.0,
    "mcp_daily_loss_usd": 50.0,
    "mcp_live_approval": True,
    "mcp_http_enabled": False,

    "autopilot_enabled": False,
    "autopilot_interval_min": 60,
    "autopilot_max_runs_per_day": 12,
    "autopilot_daily_token_budget": 1_500_000,
    "autopilot_max_steps": 15,
    "autopilot_mission": "",
    "autopilot_agent_id": "default",
    "mcp_agents": None,
    "mcp_allow_research": False,
    "mcp_allow_scripts": False,
    "mcp_allow_script_run": False,
    "mcp_allow_config": False,
    "mcp_allow_live_switches": False,

    "terminal_max_contracts": 1000,
    "terminal_max_notional_usd": 500.0,

    "perps_ws_enabled": True,
    "perps_farm_enabled": False,
    "perps_farm_symbol": "KXBTCPERP",
    "perps_farm_clip_contracts": 1,
    "perps_farm_max_inventory_contracts": 3,
    "perps_farm_min_spread_ticks": 2,
    "perps_farm_requote_ticks": 1,
    "perps_farm_daily_loss_usd": 2.0,
    "perps_farm_daily_volume_usd": 0.0,
    "perps_farm_max_cost_bps": 4.0,
    "perps_farm_max_fee_bps": 0.0,

    "crypto15m_indicator_detect": True,
    "crypto15m_spot_ws": True,
    "crypto15m_arb_detect": True,
    "crypto15m_arb_min_edge_cents": 3.0,
    "crypto15m_use_rules": False,
    "crypto15m_rules": [],
    "crypto15m_rules_no": [],

    "crypto15m_pairs_enabled": False,
    "crypto15m_directional_enabled": True,
    "crypto15m_pairs_ceiling_cents": 95.0,
    "crypto15m_pairs_dip_cents": 2.0,
    "crypto15m_pairs_clip": 5,
    "crypto15m_pairs_first_leg_min_cents": 35.0,
    "crypto15m_pairs_first_leg_max_cents": 60.0,

    "event_webhook_url": "",
    "stats_webhook_url": "",
    "whale_webhook_url": "",
    "momentum_webhook_url": "",
    "stats_push_interval": 3600,
    "stats_chart_window_hours": 168,
    "enable_discord": True,
}



CRYPTO15M_PRESETS: list[dict[str, Any]] = [
    {
        "id": "c15-sniper",
        "name": "★ Settlement Sniper",
        "tagline": "Final-minute only: strike while the settlement average is being computed.",
        "description": (
            "The one mechanism that survived this app's historical replay of "
            "19,819 settled windows: enter ONLY inside the final 60 seconds, "
            "when >=30 of the 60 settlement prints are already realized, the "
            "settlement model is ~3-sigma certain, and the quote still leaves "
            ">=2c net of fees. Mid-window model entries measured NO edge and "
            "stay off. Rare entries by design; tail losses are real — "
            "paper-trade first, size small."
        ),
        "config": {
            "crypto15m_direction_mode": "model",
            "crypto15m_model_min_prob": 0.99,
            "crypto15m_model_min_edge_cents": 2.0,
            "crypto15m_model_final_minute": True,
            "crypto15m_model_midwindow": False,
            "crypto15m_entry_style": "taker",
            "crypto15m_exit_threshold": 0.40,
            "crypto15m_indicator_detect": True,
            "crypto15m_use_rules": False,
        },
    },
    {
        "id": "c15-favorite",
        "name": "Deep Favorite",
        "tagline": "Only the deepest favorites: buy at 95-98c.",
        "description": (
            "Buy the favorite only when it is already >=95c — the single "
            "price band that did not lose money in this app's replay of "
            "531 settled 15-minute markets (+2.8c/contract net of fees, "
            "16/16 wins). CAUTION: that sample is far too small to prove "
            "an edge; one loss at 97c wipes out ~35 wins. Paper-trade "
            "first."
        ),
        "config": {
            "crypto15m_direction_mode": "favorite",
            "crypto15m_entry_threshold": 0.95,
            "crypto15m_entry_max": 0.98,
            "crypto15m_min_delta_pct": 0.0,
            "crypto15m_exit_threshold": 0.40,
            "crypto15m_entry_style": "maker",
            "crypto15m_use_rules": False,
        },
    },
    {
        "id": "c15-contrarian",
        "name": "Contrarian Fade",
        "tagline": "Fade extreme favorites — buy the cheap underdog.",
        "description": (
            "When a side is an extreme favorite (>=90c), buy the CHEAP "
            "opposite side, betting the 15-minute move reverts before "
            "close. Low win rate, high payoff (longshot); holds to "
            "settlement, no stop. Measured roughly break-even (+1.0c/"
            "contract, t=0.3, n=64) on the recorded data — no proven "
            "edge. Paper-trade hard."
        ),
        "config": {
            "crypto15m_direction_mode": "contrarian",
            "crypto15m_entry_threshold": 0.90,
            "crypto15m_entry_max": 0.98,
            "crypto15m_min_delta_pct": 0.0,
            "crypto15m_exit_threshold": 0.0,
            "crypto15m_entry_style": "maker",
            "crypto15m_use_rules": False,
        },
    },
    {
        "id": "c15-momentum",
        "name": "Momentum (Δ-confirmed)",
        "tagline": "Buy the favorite only after the underlying has already moved.",
        "description": (
            "Enter the favorite only once the underlying has moved >=0.2% from "
            "the 15-minute open — a momentum filter. Unproven; paper-trade first."
        ),
        "config": {
            "crypto15m_direction_mode": "favorite",
            "crypto15m_entry_threshold": 0.80,
            "crypto15m_entry_max": 0.98,
            "crypto15m_min_delta_pct": 0.002,
            "crypto15m_exit_threshold": 0.40,
            "crypto15m_entry_style": "maker",
            "crypto15m_use_rules": False,
        },
    },
    {
        "id": "c15-fav-90-95",
        "name": "Favorite 90-95c",
        "tagline": "Favorites in the 90-95c pocket.",
        "description": (
            "Buy favorites priced 90-95c. Priced off the mid and unconfirmed on "
            "real fills near close — paper-trade first."
        ),
        "config": {
            "crypto15m_direction_mode": "favorite",
            "crypto15m_entry_threshold": 0.90,
            "crypto15m_entry_max": 0.95,
            "crypto15m_min_delta_pct": 0.0,
            "crypto15m_exit_threshold": 0.40,
            "crypto15m_entry_style": "maker",
            "crypto15m_use_rules": False,
        },
    },
    {
        "id": "c15-macd-trend",
        "name": "MACD Trend (rules)",
        "tagline": "Enter Up when Up is favored and the underlying MACD is bullish.",
        "description": (
            "Experimental rule-builder preset: enter Up when Up is favored "
            "(>=55%) and the 1-minute underlying MACD histogram is positive, in "
            "the last 6 minutes. Uses the new MACD field — recorded, not yet "
            "backtested. Paper-trade first."
        ),
        "config": {
            "crypto15m_direction_mode": "favorite",
            "crypto15m_entry_style": "maker",
            "crypto15m_exit_threshold": 0.40,
            "crypto15m_min_delta_pct": 0.0,
            "crypto15m_indicator_detect": True,
            "crypto15m_use_rules": True,
            "crypto15m_rules": [
                {"field": "upProb", "op": ">=", "value": 0.55},
                {"field": "macdHist", "op": ">", "value": 0.0},
                {"field": "minsLeft", "op": "<=", "value": 6.0},
            ],
        },
    },
]


def crypto15m_preset_config(preset_id: str) -> dict[str, Any] | None:
    for p in CRYPTO15M_PRESETS:
        if p["id"] == preset_id:
            return dict(p["config"])
    return None


def _camel_to_snake(name: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(name):
        if ch.isupper() and i > 0:
            out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch.lower() if ch.isupper() else ch)
    return "".join(out)


def _clampf(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f:
        return default
    return max(lo, min(hi, f))


def _clampi(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


_FRACTION_KEYS = [
    "base_size_fraction", "min_size_fraction", "max_size_fraction",
    "min_cash_reserve_fraction", "max_total_exposure_fraction",
]
_UNIT_KEYS = [
    "crypto15m_entry_threshold", "crypto15m_entry_max", "crypto15m_exit_threshold",
    "crypto15m_min_delta_pct", "crypto15m_entry_diff", "min_entry_price_frac",
]

_CRYPTO15M_RULE_FIELDS = [
    "favoritePrice", "entryCost", "upProb", "downProb", "deltaPct",
    "deltaSignedPct", "minsLeft", "hourUtc", "peersAgree", "marketBias",
    "arbEdgeCents", "macd", "macdSignal", "macdHist", "macdCross", "rsi",
    "settlePrints", "upAsk", "downAsk",
    "sigma1m", "modelProb", "edgeNetCents",
    "vwap1h", "ema12", "sma20", "sma50",
    "priceVsVwapPct", "ema12VsSma20Pct", "ema1VsSma5Pct",
    "velocity1mPct", "change5mPct", "change15mPct",
]


_C15_RUNNER_MODES = ("paper", "live")


def _sanitize_runner_config(raw: Any) -> dict:
    """A Multi-Run runner stores only the crypto15m_* keys it OVERRIDES on top
    of the base config. Keep exactly those (never let a runner nest runners),
    coercing each to the type of its DEFAULT_CONFIG entry so an imported/edited
    runner can't smuggle a wrong-typed value into the sizing path."""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for rk, v in raw.items():
        if not isinstance(rk, str):
            continue
        k = rk if rk.startswith("crypto15m_") else _camel_to_snake(rk)
        if not k.startswith("crypto15m_"):
            continue
        if k == "crypto15m_runners" or k not in DEFAULT_CONFIG:
            continue
        if k == "crypto15m_max_total_pct":
            continue
        dv = DEFAULT_CONFIG[k]
        try:
            if isinstance(dv, bool):
                out[k] = bool(v)
            elif isinstance(dv, int):
                out[k] = int(v)
            elif isinstance(dv, float):
                out[k] = float(v)
            elif isinstance(dv, str):
                out[k] = str(v)
            else:
                out[k] = v
        except (TypeError, ValueError):
            continue
    if "crypto15m_sizing_mode" not in out:
        if "crypto15m_order_size" in out:
            out["crypto15m_sizing_mode"] = "fixed"
        elif "crypto15m_balance_pct" in out:
            out["crypto15m_sizing_mode"] = "balance_pct"
    if out:
        validated = _validate_config({**DEFAULT_CONFIG, **out})
        out = {k: validated[k] for k in out if k in validated}
    return out


def _validate_schedule(raw: Any) -> list | None:
    """A scheduled runner's hour→config map (Coin Optimizer output). Each slot
    is {startHour, endHour, name, config}; hours clamp to 0..24, slots with
    end<=start are dropped, config sanitized like a runner override."""
    if not isinstance(raw, list) or not raw:
        return None
    out: list[dict] = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        try:
            sh = max(0, min(24, int(s.get("startHour"))))
            eh = max(0, min(24, int(s.get("endHour"))))
        except (TypeError, ValueError):
            continue
        if eh <= sh:
            continue
        out.append({
            "startHour": sh, "endHour": eh,
            "name": (str(s.get("name") or ""))[:60],
            "config": _sanitize_runner_config(s.get("config")),
        })
    return out or None


def _validate_c15_runners(raw: Any) -> list | None:
    """Validate the Multi-Run runner list. None/empty = legacy single-engine
    mode (one implicit default runner). Drops malformed entries, dedups ids,
    restricts coins to known assets, and clamps mode to paper|live."""
    if not isinstance(raw, list) or not raw:
        return None
    try:
        from crypto15m import ALL_ASSETS as _C15_ALL
        valid_assets = {a.upper() for a in _C15_ALL}
    except Exception:
        valid_assets = {"BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"}
    out: list[dict] = []
    seen: set[str] = set()
    for i, r in enumerate(raw):
        if not isinstance(r, dict):
            continue
        rid = (str(r.get("id") or "").strip() or f"r{i}")[:40]
        if rid in seen:
            continue
        seen.add(rid)
        coins = r.get("coins")
        if isinstance(coins, list):
            coins = [c.upper() for c in coins if isinstance(c, str) and c.upper() in valid_assets]
        else:
            coins = None
        mode = str(r.get("mode") or "paper").lower()
        if mode not in _C15_RUNNER_MODES:
            mode = "paper"
        out.append({
            "id": rid,
            "name": (str(r.get("name") or rid))[:60],
            "coins": coins,
            "mode": mode,
            "enabled": bool(r.get("enabled", False)),
            "config": _sanitize_runner_config(r.get("config")),
            "schedule": _validate_schedule(r.get("schedule")),
        })
    return out or None


def _validate_config(cfg: dict[str, Any]) -> dict[str, Any]:
    d = DEFAULT_CONFIG
    for k in _FRACTION_KEYS:
        cfg[k] = _clampf(cfg.get(k), 0.0, 1.0, d[k])
    for k in _UNIT_KEYS:
        cfg[k] = _clampf(cfg.get(k), 0.0, 1.0, d[k])
    if cfg["min_size_fraction"] > cfg["max_size_fraction"]:
        cfg["min_size_fraction"] = cfg["max_size_fraction"]

    if cfg.get("sizing_mode") not in ("percent", "fixed"):
        cfg["sizing_mode"] = d["sizing_mode"]
    cfg["fixed_trade_usd"] = _clampf(cfg.get("fixed_trade_usd"), 0.0, 1e9, d["fixed_trade_usd"])
    cfg["hard_max_position_usd"] = _clampf(cfg.get("hard_max_position_usd"), 0.0, 1e9, d["hard_max_position_usd"])
    cfg["min_entry_price_cents"] = _clampi(cfg.get("min_entry_price_cents"), 1, 99, d["min_entry_price_cents"])
    cfg["max_entry_price_cents"] = _clampi(cfg.get("max_entry_price_cents"), 1, 99, d["max_entry_price_cents"])
    if cfg["min_entry_price_cents"] > cfg["max_entry_price_cents"]:
        cfg["min_entry_price_cents"], cfg["max_entry_price_cents"] = (
            cfg["max_entry_price_cents"], cfg["min_entry_price_cents"],
        )
    cfg["max_open_positions"] = _clampi(cfg.get("max_open_positions"), 0, 100_000, d["max_open_positions"])
    cfg["max_resolution_days"] = _clampi(cfg.get("max_resolution_days"), 0, 100_000, d["max_resolution_days"])
    cfg["max_daily_new_positions"] = _clampi(cfg.get("max_daily_new_positions"), 0, 100_000, d["max_daily_new_positions"])
    cfg["max_positions_per_event"] = _clampi(cfg.get("max_positions_per_event"), 1, 100_000, d["max_positions_per_event"])
    cfg["stop_loss_on_day"] = -abs(_clampf(cfg.get("stop_loss_on_day"), -1e9, 1e9, d["stop_loss_on_day"]))
    cfg["stop_loss_on_day_pct"] = abs(_clampf(cfg.get("stop_loss_on_day_pct"), -1.0, 1.0, d["stop_loss_on_day_pct"]))
    cfg["take_profit_on_day"] = _clampf(cfg.get("take_profit_on_day"), 0.0, 1e9, d["take_profit_on_day"])
    cfg["fee_aware_edge"] = bool(cfg.get("fee_aware_edge", d["fee_aware_edge"]))
    cfg["max_entry_slippage_cents"] = _clampi(cfg.get("max_entry_slippage_cents"), 0, 99, d["max_entry_slippage_cents"])
    cfg["min_market_volume"] = _clampf(cfg.get("min_market_volume"), 0.0, 1e12, d["min_market_volume"])
    cfg["max_trade_age_min"] = _clampi(cfg.get("max_trade_age_min"), 1, 1440, d["max_trade_age_min"])
    cfg["auto_upgrade_api_level"] = bool(cfg.get("auto_upgrade_api_level", True))
    cfg["crypto15m_live"] = bool(cfg.get("crypto15m_live", False))
    cfg["crypto15m_order_size"] = _clampi(cfg.get("crypto15m_order_size"), 1, 10_000, d["crypto15m_order_size"])
    cfg["crypto15m_max_concurrent"] = _clampi(cfg.get("crypto15m_max_concurrent"), 1, 50, d["crypto15m_max_concurrent"])
    aw = cfg.get("crypto15m_assets")
    if isinstance(aw, list):
        try:
            from crypto15m import ALL_ASSETS as _C15_ALL
            valid = {a.upper() for a in _C15_ALL}
        except Exception:
            valid = {"BTC", "ETH", "SOL", "XRP", "DOGE", "HYPE", "BNB"}
        cfg["crypto15m_assets"] = [
            a.upper() for a in aw if isinstance(a, str) and a.upper() in valid
        ]
    elif aw is not None:
        cfg["crypto15m_assets"] = None
    cfg["crypto15m_runners"] = _validate_c15_runners(cfg.get("crypto15m_runners"))
    if cfg.get("crypto15m_sizing_mode") not in ("fixed", "balance_pct"):
        cfg["crypto15m_sizing_mode"] = d["crypto15m_sizing_mode"]
    cfg["crypto15m_balance_pct"] = _clampf(cfg.get("crypto15m_balance_pct"), 0.0, 1.0, d["crypto15m_balance_pct"])
    cfg["crypto15m_max_loss_pct"] = _clampf(cfg.get("crypto15m_max_loss_pct"), 0.0, 1.0, d["crypto15m_max_loss_pct"])
    cfg["crypto15m_max_total_pct"] = _clampf(cfg.get("crypto15m_max_total_pct"), 0.0, 1.0, d["crypto15m_max_total_pct"])
    cfg["crypto15m_time_delay_min"] = _clampf(cfg.get("crypto15m_time_delay_min"), 0.0, 15.0, d["crypto15m_time_delay_min"])
    if cfg.get("crypto15m_direction_mode") not in ("favorite", "contrarian", "model"):
        cfg["crypto15m_direction_mode"] = d["crypto15m_direction_mode"]
    cfg["crypto15m_model_min_prob"] = _clampf(cfg.get("crypto15m_model_min_prob"), 0.50, 1.0, d["crypto15m_model_min_prob"])
    cfg["crypto15m_model_min_edge_cents"] = _clampf(cfg.get("crypto15m_model_min_edge_cents"), 0.0, 50.0, d["crypto15m_model_min_edge_cents"])
    cfg["crypto15m_model_final_minute"] = bool(cfg.get("crypto15m_model_final_minute", d["crypto15m_model_final_minute"]))
    cfg["crypto15m_model_midwindow"] = bool(cfg.get("crypto15m_model_midwindow", d["crypto15m_model_midwindow"]))
    cfg["crypto15m_model_autopause"] = bool(cfg.get("crypto15m_model_autopause", d["crypto15m_model_autopause"]))
    cfg["main_record_signals"] = bool(cfg.get("main_record_signals", d["main_record_signals"]))
    if cfg.get("crypto15m_entry_style") not in ("maker", "taker"):
        cfg["crypto15m_entry_style"] = d["crypto15m_entry_style"]
    cfg["crypto15m_maker_cancel_min"] = _clampf(cfg.get("crypto15m_maker_cancel_min"), 0.0, 15.0, d["crypto15m_maker_cancel_min"])
    cfg["crypto15m_stop_slippage_cents"] = _clampi(cfg.get("crypto15m_stop_slippage_cents"), 0, 50, d["crypto15m_stop_slippage_cents"])
    cfg["crypto15m_take_profit_cents"] = _clampi(cfg.get("crypto15m_take_profit_cents"), 0, 99, d["crypto15m_take_profit_cents"])
    cfg["crypto15m_stop_loss_pct"] = _clampf(cfg.get("crypto15m_stop_loss_pct"), 0.0, 1.0, d["crypto15m_stop_loss_pct"])
    cfg["crypto15m_session_take_profit_usd"] = _clampf(cfg.get("crypto15m_session_take_profit_usd"), 0.0, 1e9, d["crypto15m_session_take_profit_usd"])
    cfg["crypto15m_min_rsi"] = _clampf(cfg.get("crypto15m_min_rsi"), 0.0, 100.0, d["crypto15m_min_rsi"])
    cfg["crypto15m_min_macd_hist"] = _clampf(cfg.get("crypto15m_min_macd_hist"), 0.0, 1e9, d["crypto15m_min_macd_hist"])
    cfg["crypto15m_hours_start_utc"] = _clampi(cfg.get("crypto15m_hours_start_utc"), 0, 24, d["crypto15m_hours_start_utc"])
    cfg["crypto15m_hours_end_utc"] = _clampi(cfg.get("crypto15m_hours_end_utc"), 0, 24, d["crypto15m_hours_end_utc"])
    hh = cfg.get("crypto15m_hours")
    if isinstance(hh, list):
        cfg["crypto15m_hours"] = sorted({
            int(h) for h in hh if isinstance(h, (int, float)) and 0 <= int(h) <= 23
        })
    elif hh is not None:
        cfg["crypto15m_hours"] = None
    cfg["crypto15m_indicator_detect"] = bool(cfg.get("crypto15m_indicator_detect", True))
    cfg["crypto15m_spot_ws"] = bool(cfg.get("crypto15m_spot_ws", d["crypto15m_spot_ws"]))
    cfg["crypto15m_strict_threshold"] = bool(cfg.get("crypto15m_strict_threshold", d["crypto15m_strict_threshold"]))
    cfg["crypto15m_arb_detect"] = bool(cfg.get("crypto15m_arb_detect", True))
    cfg["crypto15m_arb_min_edge_cents"] = _clampf(cfg.get("crypto15m_arb_min_edge_cents"), 0.0, 100.0, d["crypto15m_arb_min_edge_cents"])
    cfg["crypto15m_use_rules"] = bool(cfg.get("crypto15m_use_rules", False))
    cfg["crypto15m_rules"] = rules.sanitize_rules(cfg.get("crypto15m_rules"), _CRYPTO15M_RULE_FIELDS)
    cfg["crypto15m_rules_no"] = rules.sanitize_rules(cfg.get("crypto15m_rules_no"), _CRYPTO15M_RULE_FIELDS)
    cfg["crypto15m_pairs_enabled"] = False
    cfg["crypto15m_directional_enabled"] = True
    cfg["crypto15m_pairs_ceiling_cents"] = _clampf(cfg.get("crypto15m_pairs_ceiling_cents"), 50.0, 99.0, d["crypto15m_pairs_ceiling_cents"])
    cfg["crypto15m_pairs_dip_cents"] = _clampf(cfg.get("crypto15m_pairs_dip_cents"), 0.5, 30.0, d["crypto15m_pairs_dip_cents"])
    cfg["crypto15m_pairs_clip"] = _clampi(cfg.get("crypto15m_pairs_clip"), 1, 1000, d["crypto15m_pairs_clip"])
    cfg["crypto15m_pairs_first_leg_min_cents"] = _clampf(cfg.get("crypto15m_pairs_first_leg_min_cents"), 1.0, 90.0, d["crypto15m_pairs_first_leg_min_cents"])
    cfg["crypto15m_pairs_first_leg_max_cents"] = _clampf(cfg.get("crypto15m_pairs_first_leg_max_cents"), 5.0, 95.0, d["crypto15m_pairs_first_leg_max_cents"])
    if cfg["crypto15m_pairs_first_leg_min_cents"] > cfg["crypto15m_pairs_first_leg_max_cents"]:
        cfg["crypto15m_pairs_first_leg_min_cents"], cfg["crypto15m_pairs_first_leg_max_cents"] = (
            cfg["crypto15m_pairs_first_leg_max_cents"], cfg["crypto15m_pairs_first_leg_min_cents"],
        )
    cfg["perps_ws_enabled"] = bool(cfg.get("perps_ws_enabled", d["perps_ws_enabled"]))
    cfg["perps_farm_enabled"] = bool(cfg.get("perps_farm_enabled", d["perps_farm_enabled"]))
    sym = str(cfg.get("perps_farm_symbol") or d["perps_farm_symbol"]).strip().upper().rstrip("1")
    cfg["perps_farm_symbol"] = sym if (sym.startswith("KX") and sym.endswith("PERP")) else d["perps_farm_symbol"]
    cfg["perps_farm_clip_contracts"] = _clampi(cfg.get("perps_farm_clip_contracts"), 1, 100, d["perps_farm_clip_contracts"])
    cfg["perps_farm_max_inventory_contracts"] = _clampi(cfg.get("perps_farm_max_inventory_contracts"), 1, 1000, d["perps_farm_max_inventory_contracts"])
    cfg["perps_farm_min_spread_ticks"] = _clampi(cfg.get("perps_farm_min_spread_ticks"), 1, 100, d["perps_farm_min_spread_ticks"])
    cfg["perps_farm_requote_ticks"] = _clampi(cfg.get("perps_farm_requote_ticks"), 1, 100, d["perps_farm_requote_ticks"])
    cfg["perps_farm_daily_loss_usd"] = _clampf(cfg.get("perps_farm_daily_loss_usd"), 0.1, 10000.0, d["perps_farm_daily_loss_usd"])
    cfg["perps_farm_daily_volume_usd"] = _clampf(cfg.get("perps_farm_daily_volume_usd"), 0.0, 1e9, d["perps_farm_daily_volume_usd"])
    cfg["perps_farm_max_cost_bps"] = _clampf(cfg.get("perps_farm_max_cost_bps"), 0.1, 100.0, d["perps_farm_max_cost_bps"])
    cfg["perps_farm_max_fee_bps"] = _clampf(cfg.get("perps_farm_max_fee_bps"), 0.0, 100.0, d["perps_farm_max_fee_bps"])
    cfg["trade_scan_interval"] = _clampi(cfg.get("trade_scan_interval"), 5, 3600, d["trade_scan_interval"])
    cfg["position_poll_interval"] = _clampi(cfg.get("position_poll_interval"), 5, 3600, d["position_poll_interval"])
    cfg["balance_poll_interval"] = _clampi(cfg.get("balance_poll_interval"), 10, 3600, d["balance_poll_interval"])
    cfg["resolution_check_interval"] = _clampi(cfg.get("resolution_check_interval"), 30, 86400, d["resolution_check_interval"])
    cfg["whale_scan_interval"] = _clampi(cfg.get("whale_scan_interval"), 30, 3600, d["whale_scan_interval"])
    cfg["momentum_scan_interval"] = _clampi(cfg.get("momentum_scan_interval"), 30, 3600, d["momentum_scan_interval"])
    cfg["market_refresh_interval"] = _clampi(cfg.get("market_refresh_interval"), 30, 86400, d["market_refresh_interval"])
    cfg["crypto15m_poll_sec"] = _clampi(cfg.get("crypto15m_poll_sec"), 2, 60, d["crypto15m_poll_sec"])
    cfg["scripts_live_enabled"] = bool(cfg.get("scripts_live_enabled", False))
    cfg["scripts_paper_mode"] = bool(cfg.get("scripts_paper_mode", False))
    cfg["script_poll_sec"] = _clampi(cfg.get("script_poll_sec"), 2, 3600, d["script_poll_sec"])
    cfg["script_max_entry_cents"] = _clampi(
        cfg.get("script_max_entry_cents"), 1, 99, d["script_max_entry_cents"])
    cfg["script_max_contracts"] = _clampi(
        cfg.get("script_max_contracts"), 1, 10_000, d["script_max_contracts"])
    cfg["script_max_open"] = _clampi(cfg.get("script_max_open"), 1, 100, d["script_max_open"])
    cfg["script_daily_loss_usd"] = _clampf(
        cfg.get("script_daily_loss_usd"), 0.0, 1e6, d["script_daily_loss_usd"])
    cfg["script_max_enabled"] = _clampi(
        cfg.get("script_max_enabled"), 1, 50, d["script_max_enabled"])
    for _k in ("remote_discord_enabled", "remote_telegram_enabled",
               "remote_trading_enabled", "remote_alerts_enabled"):
        cfg[_k] = bool(cfg.get(_k, d[_k]))
    for _k in ("remote_discord_user_id", "remote_telegram_chat_id"):
        v = cfg.get(_k, d[_k])
        v = "".join(ch for ch in str(v or "") if ch.isdigit())
        cfg[_k] = v[:32]
    import ai_analyst as _ai
    _p = str(cfg.get("ai_provider") or "").strip().lower()
    cfg["ai_provider"] = _p if _p in _ai.PROVIDERS else d["ai_provider"]
    cfg["ai_model"] = _ai.normalize_model(cfg["ai_provider"], cfg.get("ai_model"))
    cfg["ai_web_search"] = bool(cfg.get("ai_web_search", d["ai_web_search"]))
    cfg["mcp_enabled"] = bool(cfg.get("mcp_enabled", d["mcp_enabled"]))
    for _k in ("mcp_allow_research", "mcp_allow_scripts", "mcp_allow_script_run",
               "mcp_allow_config", "mcp_allow_live_switches", "mcp_http_enabled"):
        cfg[_k] = cfg.get(_k, d[_k]) is True
    cfg["mcp_port"] = _clampi(cfg.get("mcp_port"), 1024, 65535, d["mcp_port"])
    _m = str(cfg.get("mcp_trade_mode") or "").strip().lower()
    cfg["mcp_trade_mode"] = _m if _m in ("off", "paper", "live") else "off"
    cfg["mcp_max_order_usd"] = _clampf(
        cfg.get("mcp_max_order_usd"), 1.0, 1e6, d["mcp_max_order_usd"])
    cfg["mcp_daily_spend_usd"] = _clampf(
        cfg.get("mcp_daily_spend_usd"), 1.0, 1e7, d["mcp_daily_spend_usd"])
    cfg["mcp_max_positions"] = _clampi(
        cfg.get("mcp_max_positions"), 1, 200, d["mcp_max_positions"])
    cfg["mcp_live_approval"] = cfg.get("mcp_live_approval", True) is not False
    cfg["autopilot_enabled"] = cfg.get("autopilot_enabled", False) is True
    cfg["autopilot_interval_min"] = _clampi(
        cfg.get("autopilot_interval_min"), 15, 1440, d["autopilot_interval_min"])
    cfg["autopilot_max_runs_per_day"] = _clampi(
        cfg.get("autopilot_max_runs_per_day"), 1, 96, d["autopilot_max_runs_per_day"])
    cfg["autopilot_daily_token_budget"] = _clampi(
        cfg.get("autopilot_daily_token_budget"), 50_000, 50_000_000,
        d["autopilot_daily_token_budget"])
    cfg["autopilot_max_steps"] = _clampi(
        cfg.get("autopilot_max_steps"), 3, 40, d["autopilot_max_steps"])
    cfg["autopilot_mission"] = str(cfg.get("autopilot_mission") or "")[:2000]
    import mcp_agents as _ag
    cfg["mcp_agents"] = _ag.validate_agents(cfg.get("mcp_agents"), cfg["mcp_trade_mode"])
    _aid = str(cfg.get("autopilot_agent_id") or "").strip().lower()
    cfg["autopilot_agent_id"] = _aid if _ag.valid_id(_aid) else _ag.DEFAULT_ID
    cfg["mcp_daily_loss_usd"] = _clampf(
        cfg.get("mcp_daily_loss_usd"), 1.0, 1e6, d["mcp_daily_loss_usd"])
    cfg["mcp_min_edge_cents"] = _clampf(
        cfg.get("mcp_min_edge_cents"), 0.0, 50.0, d["mcp_min_edge_cents"])
    _am = str(cfg.get("account_mode") or "").strip().lower()
    cfg["account_mode"] = "live" if _am == "live" else "paper"
    cfg["paper_bankroll_usd"] = _clampf(
        cfg.get("paper_bankroll_usd"), 10.0, 1e7, d["paper_bankroll_usd"])
    cfg["shard_auto_move"] = cfg.get("shard_auto_move", True) is not False
    cfg["shard_auto_move_max_usd_day"] = _clampf(
        cfg.get("shard_auto_move_max_usd_day"), 1.0, 1e7, d["shard_auto_move_max_usd_day"])
    cfg["terminal_max_contracts"] = _clampi(
        cfg.get("terminal_max_contracts"), 1, 100_000, d["terminal_max_contracts"])
    cfg["terminal_max_notional_usd"] = _clampf(
        cfg.get("terminal_max_notional_usd"), 1.0, 1e7, d["terminal_max_notional_usd"])
    _oe = cfg.get("order_expiration_sec")
    if _oe in (None, 0, "0"):
        cfg["order_expiration_sec"] = None
    else:
        cfg["order_expiration_sec"] = _clampi(_oe, 10, 3600, d["order_expiration_sec"])
    return cfg


_REMOVED_KEYS = frozenset({
    "gambling_mode", "gambling_trade_probability",
    "kalshi_env",
    "mcp_paper_bankroll_usd",
})


def _migrate_account_mode(user: dict[str, Any]) -> dict[str, Any]:
    """A config from before account_mode existed: production -> live (an
    existing live trader keeps trading exactly as before, every per-engine
    live switch untouched); demo, or no env at all -> paper. Idempotent: a
    config that names account_mode is left alone, whatever env it also names.

    The Electron store migrates settings.json the same way on load; this is
    the backend's own copy so a config that skipped that (an old profile, a
    hand-written file) still lands on the side that cannot spend money."""
    if not isinstance(user, dict):
        return {}
    out = dict(user)
    if "account_mode" not in out and "accountMode" not in out:
        env = out.get("kalshi_env", out.get("kalshiEnv"))
        out["account_mode"] = "live" if env == "production" else "paper"
    if "paper_bankroll_usd" not in out and "paperBankrollUsd" not in out:
        old = out.get("mcp_paper_bankroll_usd", out.get("mcpPaperBankrollUsd"))
        if old is not None:
            out["paper_bankroll_usd"] = old
    return out


def account_live(cfg: dict[str, Any]) -> bool:
    """True only in Live mode. The master check every engine narrows under."""
    return str((cfg or {}).get("account_mode") or "").lower() == "live"


def scope_env(cfg: dict[str, Any]) -> str:
    """The ledger scope the account mode trades in: 'production' when Live,
    'paper' otherwise (see db.LIVE_ENV / db.PAPER_ENV)."""
    return "production" if account_live(cfg) else "paper"


def merge_with_defaults(user: dict[str, Any]) -> dict[str, Any]:
    out = dict(DEFAULT_CONFIG)
    for k, v in _migrate_account_mode(user or {}).items():
        if k in out:
            out[k] = v
            continue
        sk = _camel_to_snake(k)
        if sk in _REMOVED_KEYS:
            continue
        out[sk] = v
    return _validate_config(out)

