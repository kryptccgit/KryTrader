from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import db
from mcp_server import HOOKS, Tool, ToolError, _obj, _s, register

logger = logging.getLogger("mcp")

PROTECTED_PREFIXES = ("mcp_", "remote_", "ai_", "autopilot_")
PROTECTED = frozenset({
    "kalshi_env",
    "terminal_max_contracts", "terminal_max_notional_usd",
    "event_webhook_url", "stats_webhook_url", "whale_webhook_url",
    "momentum_webhook_url", "enable_discord", "stats_push_interval",
    "stats_chart_window_hours",
    "auto_upgrade_api_level", "db_cleanup_interval",
    "balance_poll_interval", "position_poll_interval", "resolution_check_interval",
    "market_refresh_interval", "momentum_scan_interval", "whale_scan_interval",
    "trade_scan_interval", "crypto15m_poll_sec", "script_poll_sec",
    "perps_ws_enabled", "crypto15m_spot_ws",
    "crypto15m_record_signals", "main_record_signals",
})

LIVE = frozenset({
    "enable_trading", "trade_whales", "trade_momentum", "trade_convergence",
    "crypto15m_enabled", "crypto15m_live", "crypto15m_runners",
    "crypto15m_pairs_enabled", "crypto15m_directional_enabled",
    "scripts_live_enabled", "scripts_paper_mode", "perps_farm_enabled",
    "gambling_mode", "gambling_trade_probability",
    "stop_loss_on_day", "stop_loss_on_day_pct", "take_profit_on_day",
    "max_total_exposure_fraction", "max_open_positions", "max_daily_new_positions",
    "unlimited_daily_new_positions", "max_positions_per_event",
    "hard_max_position_usd", "min_cash_reserve_fraction", "max_size_fraction",
    "base_size_fraction", "min_size_fraction", "fixed_trade_usd", "sizing_mode",
    "start_bankroll_usd", "fee_aware_edge", "max_resolution_days",
    "trading_hours_enabled", "trading_days", "trading_hours_start",
    "trading_hours_end", "trading_timezone_offset_min",
    "crypto15m_max_loss_pct", "crypto15m_max_total_pct", "crypto15m_balance_pct",
    "crypto15m_order_size", "crypto15m_sizing_mode", "crypto15m_max_concurrent",
    "crypto15m_session_take_profit_usd", "crypto15m_stop_loss_pct",
    "script_daily_loss_usd", "script_max_contracts", "script_max_entry_cents",
    "script_max_open", "script_max_enabled",
    "perps_farm_daily_loss_usd", "perps_farm_daily_volume_usd",
    "perps_farm_max_inventory_contracts", "perps_farm_clip_contracts",
})

SETTINGS = frozenset({
    "allowed_categories", "allowed_momentum_categories",
    "allowed_momentum_signal_types", "allowed_whale_categories",
    "contrarian_only", "cross_spread_fallback_offset",
    "crypto15m_arb_detect", "crypto15m_arb_min_edge_cents", "crypto15m_assets",
    "crypto15m_direction_mode", "crypto15m_entry_diff", "crypto15m_entry_max",
    "crypto15m_entry_style", "crypto15m_entry_threshold",
    "crypto15m_exit_threshold", "crypto15m_hours", "crypto15m_hours_end_utc",
    "crypto15m_hours_start_utc", "crypto15m_indicator_detect",
    "crypto15m_maker_cancel_min", "crypto15m_min_delta_pct",
    "crypto15m_min_macd_hist", "crypto15m_min_rsi", "crypto15m_model_autopause",
    "crypto15m_model_final_minute", "crypto15m_model_midwindow",
    "crypto15m_model_min_edge_cents", "crypto15m_model_min_prob",
    "crypto15m_pairs_ceiling_cents", "crypto15m_pairs_clip",
    "crypto15m_pairs_dip_cents", "crypto15m_pairs_first_leg_max_cents",
    "crypto15m_pairs_first_leg_min_cents", "crypto15m_rules", "crypto15m_rules_no",
    "crypto15m_stop_slippage_cents", "crypto15m_strict_threshold",
    "crypto15m_take_profit_cents", "crypto15m_time_delay_min",
    "crypto15m_use_rules",
    "max_entry_price_cents", "max_entry_slippage_cents", "max_signal_age_sec",
    "max_trade_age_min", "min_confidence_momentum", "min_confidence_whale",
    "min_edge_pts_momentum", "min_edge_pts_whale", "min_entry_price_cents",
    "min_entry_price_frac", "min_market_volume", "min_whale_usd",
    "order_expiration_sec", "order_style",
    "perps_farm_max_cost_bps", "perps_farm_max_fee_bps",
    "perps_farm_min_spread_ticks", "perps_farm_requote_ticks", "perps_farm_symbol",
    "sizing_base_edge", "sizing_max_edge",
})


def classify(key: str) -> str:
    if key in PROTECTED or key.startswith(PROTECTED_PREFIXES):
        return "protected"
    if key in LIVE:
        return "live"
    if key in SETTINGS:
        return "settings"
    return "unknown"


def _snake(k: str) -> str:
    from config import _camel_to_snake
    return k if "_" in k or k.islower() else _camel_to_snake(k)


def _camel(k: str) -> str:
    head, *rest = k.split("_")
    return head + "".join(p[:1].upper() + p[1:] for p in rest)


def audit(tool: str, client: str, ok: bool, summary: str) -> None:
    with db.get_db() as conn:
        conn.execute(
            "INSERT INTO mcp_actions (created_at, client, tool, ok, summary) "
            "VALUES (?,?,?,?,?)",
            (datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
             (client or "")[:80], tool, 1 if ok else 0, (summary or "")[:1000]))
    logger.info("[mcp] %s %s: %s", tool, "ok" if ok else "REFUSED", summary[:200])


def actions(limit: int = 100) -> list[dict]:
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM mcp_actions ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    return [{"id": int(r["id"]), "at": r["created_at"], "client": r["client"] or None,
             "tool": r["tool"], "ok": bool(r["ok"]), "summary": r["summary"] or ""}
            for r in rows]


async def _announce(text: str) -> None:
    if HOOKS.emit:
        try:
            await HOOKS.emit("mcp:order", {"mode": "action", "message": text})
        except Exception:
            pass


LIST_CAP = 25


def trim(v: Any, cap: int = LIST_CAP) -> Any:
    if isinstance(v, dict):
        return {k: trim(x, cap) for k, x in v.items()}
    if isinstance(v, list):
        out = [trim(x, cap) for x in v[:cap]]
        if len(v) > cap:
            out.append(f"... {len(v) - cap} more not shown")
        return out
    return v


async def _rpc(method: str, params: dict) -> Any:
    if HOOKS.rpc is None:
        raise ToolError("This build has no RPC hook wired for the workbench.")
    try:
        return await HOOKS.rpc(method, params)
    except ValueError as e:
        raise ToolError(str(e))


def _since(args: dict, default: int = 60) -> int:
    try:
        return max(1, min(int(args.get("since_days") or default), 365))
    except (TypeError, ValueError):
        return default


_DATASETS = {
    "crypto15m_signals": ("crypto15m_signals", "observed_at", "asset"),
    "crypto15m_ticks": ("crypto15m_ticks", "observed_at", "asset"),
    "whale_trades": ("whale_trades", "created_at", "category"),
    "momentum_alerts": ("alerts", "created_at", "category"),
}
_HIDDEN_COLS = {"discord_sent"}


def _cutoff(days: int) -> str:
    return datetime.fromtimestamp(time.time() - days * 86400, timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S")


async def t_inventory(_args: dict, _ctx: dict) -> dict:
    return trim(await _rpc("collectionStats", {}), 10)


async def t_sample(args: dict, _ctx: dict) -> dict:
    ds = _s(args, "dataset")
    if ds not in _DATASETS:
        raise ToolError(f"dataset must be one of {', '.join(_DATASETS)}")
    table, tcol, fcol = _DATASETS[ds]
    limit = max(1, min(int(args.get("limit") or 50), 200))
    where = [f"substr(replace({tcol},'T',' '),1,19) >= ?"]
    params: list = [_cutoff(_since(args, 7))]
    flt = _s(args, "filter")
    if flt:
        where.append(f"{fcol} = ?")
        params.append(flt.upper() if fcol == "asset" else flt)
    if args.get("resolved_only") and ds != "crypto15m_ticks":
        where.append("resolved = 1")
    with db.get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} WHERE {' AND '.join(where)} "
            f"ORDER BY id DESC LIMIT ?", (*params, limit)).fetchall()
    out = [{k: r[k] for k in r.keys() if k not in _HIDDEN_COLS} for r in rows]
    return {"dataset": ds, "rows": out, "count": len(out),
            "note": ("Prices in crypto15m tables are FRACTIONS (0.62 = 62c). NULL "
                     "means not recorded, never zero.")}


_C15_GROUPS = {
    "asset": "asset",
    "favorite": "favorite",
    "hour_utc": "CAST(substr(close_time, 12, 2) AS INTEGER)",
    "entry_cost_bucket": "CAST(entry_cost * 10 AS INTEGER) * 10",
    "mins_left_bucket": "CAST(mins_left / 3 AS INTEGER) * 3",
    "macd_cross": "macd_cross",
    "rsi_bucket": "CAST(rsi / 10 AS INTEGER) * 10",
}
_PRICE_C = "NULLIF(CASE WHEN price <= 1.0 THEN price * 100 ELSE price END, 0)"
_SIG_GROUPS = {
    "category": "category",
    "side": "{side}",
    "price_bucket": f"CAST({_PRICE_C} / 10 AS INTEGER) * 10",
    "confidence_bucket": "CAST(confidence / 10 AS INTEGER) * 10",
}


async def t_summarize(args: dict, _ctx: dict) -> dict:
    ds = _s(args, "dataset")
    group = _s(args, "group_by")
    since = _cutoff(_since(args, 60))
    if ds == "crypto15m_signals":
        if group not in _C15_GROUPS:
            raise ToolError(f"group_by must be one of {', '.join(_C15_GROUPS)}")
        expr = _C15_GROUPS[group]
        flt = _s(args, "filter").upper()
        sql = (f"SELECT {expr} AS bucket, COUNT(*) AS n, "
               "AVG(CASE WHEN (favorite='up' AND up_won=1) OR (favorite='down' AND up_won=0) "
               "THEN 1.0 ELSE 0.0 END) AS favorite_win_rate, "
               "AVG(entry_cost) AS avg_entry_cost "
               "FROM crypto15m_signals WHERE resolved=1 AND up_won IS NOT NULL "
               "AND entry_cost IS NOT NULL AND kalshi_env='production' "
               "AND substr(replace(observed_at,'T',' '),1,19) >= ?"
               + (" AND asset = ?" if flt else "")
               + " GROUP BY bucket ORDER BY bucket")
        params: tuple = (since, flt) if flt else (since,)
    elif ds in ("whale_trades", "momentum_alerts"):
        if group not in _SIG_GROUPS:
            raise ToolError(f"group_by must be one of {', '.join(_SIG_GROUPS)}")
        table = "whale_trades" if ds == "whale_trades" else "alerts"
        expr = _SIG_GROUPS[group].format(
            side="taker_side" if table == "whale_trades" else "direction")
        sql = (f"SELECT {expr} AS bucket, COUNT(*) AS n, "
               "AVG(CASE WHEN outcome_correct=1 THEN 1.0 ELSE 0.0 END) AS hit_rate, "
               f"AVG({_PRICE_C}) AS avg_price_cents, AVG(pnl_estimate) AS avg_pnl_estimate "
               f"FROM {table} WHERE resolved=1 AND outcome_correct IS NOT NULL "
               "AND substr(replace(created_at,'T',' '),1,19) >= ? "
               "GROUP BY bucket ORDER BY n DESC LIMIT 40")
        params = (since,)
    else:
        raise ToolError("dataset must be crypto15m_signals, whale_trades or momentum_alerts")
    with db.get_db() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    for r in rows:
        for k, v in list(r.items()):
            if isinstance(v, float):
                r[k] = round(v, 4)
        if "favorite_win_rate" in r and r.get("avg_entry_cost") is not None:
            r["gross_edge_cents"] = round((r["favorite_win_rate"] - r["avg_entry_cost"]) * 100, 2)
    return {"dataset": ds, "groupBy": group, "buckets": rows,
            "note": ("GROSS of Kalshi's fee (~0.07*p*(1-p) per contract, ~1.75c at "
                     "50c, ~0.4c at 94c). Settled markets only. Small buckets are "
                     "noise: treat n < 100 as anecdote.")}


def _crypto_patch(args: dict) -> dict:
    patch = args.get("config_patch") or {}
    if not isinstance(patch, dict):
        raise ToolError("config_patch must be an object of config keys")
    out = {}
    for k, v in patch.items():
        sk = _snake(str(k))
        if classify(sk) == "protected":
            raise ToolError(f"{k} cannot be set, even hypothetically.")
        out[sk] = v
    return out


async def t_backtest_c15(args: dict, _ctx: dict) -> dict:
    res = await _rpc("c15Backtest", {"config": _crypto_patch(args),
                                     "sinceDays": _since(args)})
    return {"note": "Hypothetical: nothing is saved or traded. Replays the LIVE "
                    "entry gates over recorded ticks, held to settlement, net of fees.",
            "result": trim(res)}


async def t_backtest_signals(args: dict, _ctx: dict) -> dict:
    res = await _rpc("mainBacktest", {"config": _crypto_patch(args),
                                      "sinceDays": _since(args)})
    return {"note": "Hypothetical: replays recorded whale/momentum signals through "
                    "the live should_trade gates with follower economics.",
            "result": trim(res)}


async def t_history(args: dict, _ctx: dict) -> dict:
    kind = _s(args, "kind") or "manual"
    limit = max(1, min(int(args.get("limit") or 100), 300))
    if kind == "manual":
        return trim(await _rpc("terminalHistory", {"limit": limit}), 50)
    if kind == "crypto15m":
        return trim(await _rpc("c15History", {"limit": limit, "includePaper": True}), 50)
    raise ToolError("kind must be manual or crypto15m")


AGENT_AUTHOR = "mcp"


def _script(sid: str) -> Optional[dict]:
    with db.get_db() as conn:
        return db.get_user_script(conn, sid)


def _summary(r: dict) -> dict:
    return {"id": r.get("id"), "name": r.get("name"),
            "description": r.get("description") or "",
            "enabled": bool(r.get("enabled")), "trusted": bool(r.get("trusted")),
            "writtenByAgent": r.get("author") == AGENT_AUTHOR,
            "lastError": r.get("last_error"), "updatedAt": r.get("updated_at"),
            "codeChars": len(r.get("code") or "")}


async def t_script_guide(_args: dict, _ctx: dict) -> str:
    res = await _rpc("scriptContextPack", {})
    return str(res.get("text") or "")


async def t_list_scripts(_args: dict, _ctx: dict) -> dict:
    with db.get_db() as conn:
        rows = db.list_user_scripts(conn)
    return {"scripts": [_summary(dict(r)) for r in rows]}


async def t_get_script(args: dict, _ctx: dict) -> dict:
    r = _script(_s(args, "id"))
    if not r:
        raise ToolError("No script with that id.")
    return {**_summary(r), "code": r.get("code") or ""}


async def t_validate(args: dict, _ctx: dict) -> dict:
    code = str(args.get("code") or "")
    if not code.strip():
        raise ToolError("code required")
    return await _rpc("scriptValidate", {"code": code, "trusted": False})


async def t_backtest_script(args: dict, _ctx: dict) -> dict:
    code = str(args.get("code") or "")
    sid = _s(args, "id")
    if not code and sid:
        r = _script(sid)
        if not r:
            raise ToolError("No script with that id.")
        if r.get("trusted"):
            raise ToolError("That script is trusted (un-sandboxed). Trusted scripts "
                            "are backtested from the Scripts page, by the user.")
        code = r.get("code") or ""
    if not code.strip():
        raise ToolError("Give code, or the id of a script.")
    res = await _rpc("scriptBacktest", {"code": code, "sinceDays": _since(args),
                                        "config": _crypto_patch(args)})
    return {"note": "Order-free replay over recorded resolved windows, net of fees.",
            "result": trim(res)}


async def t_save_script(args: dict, ctx: dict) -> dict:
    code = str(args.get("code") or "")
    if not code.strip():
        raise ToolError("code required")
    sid = _s(args, "id")
    client = ctx.get("client") or ""
    if sid:
        r = _script(sid)
        if r and r.get("author") != AGENT_AUTHOR:
            audit("save_script", client, False, f"tried to overwrite user script {sid}")
            raise ToolError("That script was written by the user; an agent can only "
                            "edit scripts it created. Save under a new id instead.")
        if r and r.get("trusted"):
            audit("save_script", client, False, f"tried to edit trusted script {sid}")
            raise ToolError("That script is now trusted (un-sandboxed). Agents cannot "
                            "edit trusted code.")
    else:
        import os
        sid = "mcp-" + os.urandom(6).hex()
    res = await _rpc("scriptSave", {"id": sid, "code": code,
                                    "name": _s(args, "name"),
                                    "description": _s(args, "description"),
                                    "notes": f"Written by AI agent ({client or 'unknown'})."})
    with db.get_db() as conn:
        conn.execute("UPDATE user_scripts SET author=?, enabled=0, trusted=0 WHERE id=?",
                     (AGENT_AUTHOR, sid))
    errs = res.get("errors") or []
    audit("save_script", client, True,
          f"saved {sid} ({res.get('script', {}).get('name')})"
          + (f" with {len(errs)} validation error(s)" if errs else ""))
    await _announce(f"saved strategy script {res.get('script', {}).get('name')} (disabled)")
    return {"id": sid, "enabled": False, "errors": errs,
            "warnings": res.get("warnings") or [],
            "note": "Saved disabled. Backtest it before anyone enables it."}


async def t_set_script_enabled(args: dict, ctx: dict) -> dict:
    sid = _s(args, "id")
    enabled = bool(args.get("enabled"))
    client = ctx.get("client") or ""
    r = _script(sid)
    if not r:
        raise ToolError("No script with that id.")
    if r.get("author") != AGENT_AUTHOR:
        audit("set_script_enabled", client, False, f"user script {sid}")
        raise ToolError("An agent can only switch scripts it wrote.")
    if r.get("trusted"):
        audit("set_script_enabled", client, False, f"trusted script {sid}")
        raise ToolError("Trusted scripts are armed by the user only.")
    res = await _rpc("scriptSetEnabled", {"id": sid, "enabled": enabled})
    cfg = HOOKS.get_cfg()
    mode = ("LIVE" if cfg.get("scripts_live_enabled") else
            "paper" if cfg.get("scripts_paper_mode") else "signal-only (no orders)")
    audit("set_script_enabled", client, True,
          f"{'enabled' if enabled else 'disabled'} {sid} ({r.get('name')}); scripts mode {mode}")
    await _announce(f"{'ENABLED' if enabled else 'disabled'} script {r.get('name')} — scripts run {mode}")
    return {"script": {**_summary(r), "enabled": enabled},
            "scriptsMode": mode,
            "note": "The Scripts page's own live/paper switches decide whether it trades."}


_last_patch = 0.0
PATCH_MIN_INTERVAL = 10.0


async def t_get_config(args: dict, _ctx: dict) -> dict:
    cfg = HOOKS.get_cfg()
    keys = args.get("keys")
    want = [_snake(str(k)) for k in keys] if isinstance(keys, list) and keys else None
    out: dict = {"settings": {}, "liveSwitchesAndRiskLimits": {}}
    for k in sorted(SETTINGS | LIVE):
        if want and k not in want:
            continue
        bucket = "settings" if k in SETTINGS else "liveSwitchesAndRiskLimits"
        out[bucket][k] = cfg.get(k)
    out["youMayChange"] = {
        "settings": bool(cfg.get("mcp_allow_config")),
        "liveSwitchesAndRiskLimits": bool(cfg.get("mcp_allow_live_switches")),
    }
    out["environment"] = cfg.get("kalshi_env")
    return out


async def t_engine_status(_args: dict, _ctx: dict) -> dict:
    return trim(await _rpc("tradingStatus", {}))


def vet_patch(patch: Any, cfg: dict) -> tuple[dict, list[str]]:
    from config import merge_with_defaults
    if not isinstance(patch, dict) or not patch:
        return {}, ["patch must be a non-empty object of config keys"]
    refusals: list[str] = []
    accepted: dict = {}
    for k, v in patch.items():
        sk = _snake(str(k))
        cls = classify(sk)
        if cls == "protected":
            refusals.append(f"{k}: never changeable by an agent")
        elif cls == "unknown":
            refusals.append(f"{k}: not a setting an agent may change")
        elif cls == "live" and not cfg.get("mcp_allow_live_switches"):
            refusals.append(f"{k}: a live switch / risk limit — the user has not "
                            f"allowed agents to change those")
        elif cls == "settings" and not (cfg.get("mcp_allow_config")
                                        or cfg.get("mcp_allow_live_switches")):
            refusals.append(f"{k}: the user has not allowed agents to change settings")
        else:
            accepted[sk] = v
    if not accepted:
        return {}, refusals
    merged = merge_with_defaults({**cfg, **accepted})
    sanitized = {k: merged.get(k) for k in accepted}
    return sanitized, refusals


async def t_update_config(args: dict, ctx: dict) -> dict:
    global _last_patch
    cfg = HOOKS.get_cfg()
    client = ctx.get("client") or ""
    patch, refusals = vet_patch(args.get("patch"), cfg)
    if refusals and not args.get("apply_partial"):
        audit("update_engine_config", client, False, "; ".join(refusals))
        raise ToolError("Refused (nothing applied):\n- " + "\n- ".join(refusals)
                        + "\nPass apply_partial=true to apply only the allowed keys.")
    if not patch:
        raise ToolError("Nothing to apply.")
    changes = {k: v for k, v in patch.items() if cfg.get(k) != v}
    if not changes:
        return {"applied": {}, "note": "Already set to those values."}
    if time.monotonic() - _last_patch < PATCH_MIN_INTERVAL:
        raise ToolError(f"One settings change per {PATCH_MIN_INTERVAL:.0f}s. Wait and retry.")
    _last_patch = time.monotonic()
    before = {k: cfg.get(k) for k in changes}
    if HOOKS.emit is None:
        raise ToolError("Settings changes are not wired in this build.")
    await HOOKS.emit("mcp:configPatch", {"patch": {_camel(k): v for k, v in changes.items()},
                                         "client": client})
    live = sorted(k for k in changes if k in LIVE)
    summary = ", ".join(f"{k}: {json.dumps(before[k])} -> {json.dumps(v)}"
                        for k, v in changes.items())
    audit("update_engine_config", client, True, summary)
    await _announce(("LIVE/RISK " if live else "") + "settings changed: " + summary[:300])
    if live and HOOKS.notify_phone:
        try:
            await HOOKS.notify_phone(f"[AI AGENT] changed live/risk settings: {summary[:300]}")
        except Exception:
            pass
    return {"applied": changes, "before": before, "refusedKeys": refusals,
            "note": "Applied through the app's settings store; visible in Settings."}


_SINCE = {"type": "integer", "minimum": 1, "maximum": 365}
_PATCH = {"type": "object", "description": "Config keys (snake_case) to try. Hypothetical only."}

register([
    Tool("get_data_inventory", "Collected data inventory",
         "What the app has recorded: 15-minute crypto signals and ticks, whale "
         "trades, momentum alerts — counts, date spans, recent samples.",
         _obj({}), t_inventory, perm="mcp_allow_research"),
    Tool("sample_research_rows", "Sample recorded rows",
         "Raw recorded rows (newest first, max 200) from one dataset. Use "
         "summarize_research for statistics instead of pulling rows.",
         _obj({"dataset": {"type": "string", "enum": list(_DATASETS)},
               "limit": {"type": "integer", "minimum": 1, "maximum": 200},
               "since_days": _SINCE,
               "filter": {"type": "string", "description": "asset (crypto15m) or category"},
               "resolved_only": {"type": "boolean"}}, ("dataset",)),
         t_sample, perm="mcp_allow_research"),
    Tool("summarize_research", "Summarize recorded outcomes",
         "Win/hit rates over SETTLED recorded data, grouped by a bucket. "
         "crypto15m_signals groups: asset, favorite, hour_utc, entry_cost_bucket, "
         "mins_left_bucket, macd_cross, rsi_bucket. whale_trades / momentum_alerts "
         "groups: category, side, price_bucket, confidence_bucket. Gross of fees.",
         _obj({"dataset": {"type": "string",
                           "enum": ["crypto15m_signals", "whale_trades", "momentum_alerts"]},
               "group_by": {"type": "string"},
               "since_days": _SINCE,
               "filter": {"type": "string", "description": "crypto15m only: asset, e.g. BTC"}},
              ("dataset", "group_by")),
         t_summarize, perm="mcp_allow_research"),
    Tool("backtest_crypto15m", "Backtest the 15m crypto strategy",
         "Replay the 15-minute crypto entry gates over recorded ticks with a "
         "hypothetical config change. Nothing is saved.",
         _obj({"config_patch": _PATCH, "since_days": _SINCE}),
         t_backtest_c15, perm="mcp_allow_research"),
    Tool("backtest_signal_following", "Backtest whale/momentum following",
         "Replay recorded whale prints and momentum alerts through the live "
         "trade gates with a hypothetical config change. Nothing is saved.",
         _obj({"config_patch": _PATCH, "since_days": _SINCE}),
         t_backtest_signals, perm="mcp_allow_research"),
    Tool("get_trade_history", "Trade history",
         "Settled trades: kind=manual (hand-placed in the Terminal) or crypto15m "
         "(the 15-minute engine, paper and live).",
         _obj({"kind": {"type": "string", "enum": ["manual", "crypto15m"]},
               "limit": {"type": "integer", "minimum": 1, "maximum": 300}}),
         t_history, perm="mcp_allow_research"),
    Tool("get_script_guide", "Strategy script guide",
         "The full reference for writing Krypt strategy scripts: hooks, the ctx "
         "fields, what is live-only, the sandbox rules, worked examples. Read "
         "this before writing a script.",
         _obj({}), t_script_guide, perm="mcp_allow_scripts"),
    Tool("list_scripts", "List strategy scripts",
         "All strategy scripts, with whether each was written by an agent.",
         _obj({}), t_list_scripts, perm="mcp_allow_scripts"),
    Tool("get_script", "Read a script",
         "One script's code and status.",
         _obj({"id": {"type": "string"}}, ("id",)), t_get_script, perm="mcp_allow_scripts"),
    Tool("validate_script", "Validate script code",
         "Check code against the sandbox without saving it.",
         _obj({"code": {"type": "string"}}, ("code",)), t_validate, perm="mcp_allow_scripts"),
    Tool("backtest_script", "Backtest a script",
         "Backtest script code (or a saved script by id) over the recorded "
         "resolved windows. Order-free, net of fees.",
         _obj({"code": {"type": "string"}, "id": {"type": "string"},
               "since_days": _SINCE, "config_patch": _PATCH}),
         t_backtest_script, perm="mcp_allow_scripts"),
    Tool("save_script", "Save a script",
         "Save a strategy script (sandboxed). Always saved DISABLED. Omit id to "
         "create; pass the id of a script YOU wrote to update it.",
         _obj({"code": {"type": "string"}, "id": {"type": "string"},
               "name": {"type": "string"}, "description": {"type": "string"}},
              ("code",)),
         t_save_script, perm="mcp_allow_scripts", read_only=False),
    Tool("set_script_enabled", "Enable or disable a script",
         "Switch a script YOU wrote on or off. Whether it then places paper or "
         "live orders is decided by the Scripts page's own switches.",
         _obj({"id": {"type": "string"}, "enabled": {"type": "boolean"}}, ("id", "enabled")),
         t_set_script_enabled, perm="mcp_allow_script_run", read_only=False,
         destructive=True),
    Tool("get_engine_config", "Read engine settings",
         "The engines' settings, split into strategy settings and live "
         "switches & risk limits, and which of those you may change.",
         _obj({"keys": {"type": "array", "items": {"type": "string"}}}),
         t_get_config, perm="mcp_allow_config"),
    Tool("get_engine_status", "Engine status",
         "Why each engine is or is not trading right now: the gate checklist.",
         _obj({}), t_engine_status, perm="mcp_allow_config"),
    Tool("update_engine_config", "Change engine settings",
         "Change engine settings. Strategy settings need the user's settings "
         "permission; engine on/off, live switches and risk limits need the "
         "separate live permission. The Kalshi environment, credentials and your "
         "own MCP permissions/caps can never be changed. Back a change with a "
         "backtest first.",
         _obj({"patch": {"type": "object"}, "apply_partial": {"type": "boolean"}},
              ("patch",)),
         t_update_config, perm="mcp_allow_config", read_only=False, destructive=True),
])
