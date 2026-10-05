from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Callable, Optional

from datetime import datetime, timezone

import crypto15m
import crypto15m_trader
import db
import kalshi_api
import kalshi_auth
import script_sandbox
import trader
from script_backtest import (
    sanitize_intent, sanitize_manage, sanitize_signal_action, signal_to_js,
)

logger = logging.getLogger("krypt.script_engine")

_SUPERVISE_KEYS: dict[str, str] = {
    "enable_trading": "bool",
    "trade_whales": "bool",
    "trade_momentum": "bool",
    "crypto15m_enabled": "bool",
    "crypto15m_direction_mode": "mode",
    "crypto15m_entry_threshold": "float",
    "crypto15m_entry_max": "float",
    "crypto15m_min_delta_pct": "float",
    "crypto15m_time_delay_min": "float",
}
_SUPERVISE_MIN_INTERVAL_S = 30.0
_last_patch_t: dict[str, float] = {}

_sig_marks: dict[str, Optional[int]] = {"whale": None, "momentum": None}

DECIDE_BUDGET_MS = 50.0
TRUSTED_TIMEOUT_S = 0.25
COMPILE_TIMEOUT_S = 5.0
SANDBOX_TIMEOUT_S = 0.75
STATE_SAVE_EVERY_S = 60.0

_SCRIPT_MGMT_SNAPSHOT = json.dumps({
    "crypto15m_exit_threshold": 0.0,
    "crypto15m_stop_loss_pct": 0.0,
    "crypto15m_take_profit_cents": 0,
    "crypto15m_stop_slippage_cents": 0,
    "crypto15m_entry_style": "taker",
})

_compiled: dict[str, script_sandbox.CompiledScript] = {}
_notified_fill: set[int] = set()
_notified_settle: set[int] = set()
_lifecycle_primed = False
_last_state_save = 0.0

_emit: Optional[Callable] = None


def set_event_callback(cb: Callable) -> None:
    global _emit
    _emit = cb


async def _emit_event(name: str, data: Any) -> None:
    if _emit is None:
        return
    try:
        await _emit(name, data)
    except Exception:
        pass


def _disable(sid: str, reason: str) -> None:
    try:
        with db.get_db() as conn:
            db.update_user_script(conn, sid, enabled=0, last_error=reason[:500])
        logger.warning(f"[scripts] disabled {sid[:8]}: {reason}")
    except Exception as e:
        logger.error(f"[scripts] failed to persist disable for {sid[:8]}: {e}")


async def _get_compiled(row: dict) -> Optional[script_sandbox.CompiledScript]:
    sid = str(row["id"])
    trusted = bool(row.get("trusted"))
    want = script_sandbox.code_hash(str(row.get("code") or ""), trusted)
    cur = _compiled.get(sid)
    if cur is not None and cur.hash == want:
        return cur
    saved_state: dict = {}
    try:
        saved_state = json.loads(row.get("state_json") or "{}")
        if not isinstance(saved_state, dict):
            saved_state = {}
    except Exception:
        saved_state = {}
    try:
        mod = await _run_bounded(
            lambda: script_sandbox.CompiledScript(
                sid, str(row.get("code") or ""), trusted=trusted,
                state=saved_state),
            COMPILE_TIMEOUT_S, f"script-{sid[:8]}-compile")
        await _run_bounded(
            lambda: mod.call("on_start", mod.state, budget_ms=DECIDE_BUDGET_MS),
            COMPILE_TIMEOUT_S, f"script-{sid[:8]}-on_start")
    except Exception as e:
        _compiled.pop(sid, None)
        _disable(sid, f"compile/on_start failed: {e}")
        return None
    _compiled[sid] = mod
    return mod


async def _run_bounded(fn: Callable[[], Any], timeout_s: float, name: str) -> Any:
    import asyncio
    import threading
    result: dict[str, Any] = {}

    def _run() -> None:
        try:
            result["value"] = fn()
        except BaseException as e:
            result["error"] = e

    t = threading.Thread(target=_run, daemon=True, name=name)
    t.start()
    await asyncio.to_thread(t.join, timeout_s)
    if t.is_alive():
        raise script_sandbox.ScriptBudgetExceeded(
            f"{name} still running after {timeout_s:.2f}s (thread abandoned)")
    if "error" in result:
        raise result["error"]
    return result.get("value")


async def _call_hook(mod: script_sandbox.CompiledScript, hook: str, *args: Any) -> Any:
    timeout = TRUSTED_TIMEOUT_S if mod.trusted else SANDBOX_TIMEOUT_S
    return await _run_bounded(
        lambda: mod.call(hook, *args, budget_ms=DECIDE_BUDGET_MS),
        timeout, f"script-{mod.script_id[:8]}-{hook}")


def _script_daily_pnl(conn, sid: str, env: str, *, paper: bool) -> float:
    total = 0.0
    try:
        row = conn.execute(
            """SELECT COALESCE(SUM(pnl_usd), 0) FROM crypto15m_positions
               WHERE script_id=? AND kalshi_env=? AND resolved=1 AND dry_run=?
                 AND date(COALESCE(resolved_at, last_updated)) = date('now')""",
            (sid, env, 1 if paper else 0),
        ).fetchone()
        total += float(row[0] or 0.0)
    except Exception:
        pass
    if not paper:
        try:
            row = conn.execute(
                """SELECT COALESCE(SUM(pnl_usd), 0) FROM bot_positions
                   WHERE script_id=? AND kalshi_env=? AND resolved=1
                     AND date(COALESCE(resolved_at, last_updated)) = date('now')""",
                (sid, env),
            ).fetchone()
            total += float(row[0] or 0.0)
        except Exception:
            pass
    return total


def _count_open_for_script(conn, sid: str, env: str, *, paper: bool) -> int:
    n = 0
    try:
        n += conn.execute(
            """SELECT COUNT(*) FROM crypto15m_positions
               WHERE script_id=? AND kalshi_env=? AND resolved=0 AND dry_run=?""",
            (sid, env, 1 if paper else 0),
        ).fetchone()[0]
    except Exception:
        pass
    if not paper:
        try:
            n += conn.execute(
                """SELECT COUNT(*) FROM bot_positions
                   WHERE script_id=? AND kalshi_env=? AND resolved=0""",
                (sid, env),
            ).fetchone()[0]
        except Exception:
            pass
    return n


def _open_crypto_for_script(conn, sid: str, env: str) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM crypto15m_positions
           WHERE script_id=? AND kalshi_env=? AND resolved=0""",
        (sid, env),
    ).fetchall()
    return [dict(r) for r in rows]


def _already_attempted(conn, sid: str, ticker: str, env: str) -> bool:
    return conn.execute(
        """SELECT 1 FROM crypto15m_positions
           WHERE script_id=? AND ticker=? AND kalshi_env=? LIMIT 1""",
        (sid, ticker, env),
    ).fetchone() is not None


def _record_refusal(sid: str, a: dict, side: str, env: str, reason: str,
                    *, paper: bool = False) -> None:
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, {
            "asset": a["asset"], "series": a.get("series") or "",
            "ticker": a["ticker"], "side": side,
            "direction": crypto15m_trader.direction_for_favorite(side),
            "target_contracts": 0, "entry_limit_cents": 1,
            "client_order_id": f"krypt-scr-{uuid.uuid4().hex[:12]}",
            "close_time": a.get("closeTime") or "", "confidence": 0.0,
            "kalshi_env": env, "status": "canceled",
            "dry_run": 1 if paper else 0,
            "error": reason, "strategy": f"script:{sid[:8]}",
            "script_id": sid,
        })
        crypto15m_trader._mark_resolved(conn, pid, status="canceled",
                                        exit_reason="script_refused")


async def _place_intent(s: dict, a: dict, intent: dict, cfg: dict,
                        env: str, *, paper: bool) -> Optional[dict]:
    sid = str(s["id"])
    side = intent["side"]
    direction = crypto15m_trader.direction_for_favorite(side)
    ticker = a.get("ticker")
    max_cents = int(cfg.get("script_max_entry_cents") or 97)

    if intent["price"] == "ask":
        ask = a.get("upAsk") if side == "up" else a.get("downAsk")
        if not ask or not (0.0 < float(ask) < 1.0):
            return None
        limit_cents = min(max_cents + 1, int(round(float(ask) * 100)) + 1)
    else:
        limit_cents = int(intent["price"])

    if limit_cents > max_cents:
        _record_refusal(sid, a, side, env,
                        f"entry {limit_cents}c > script_max_entry_cents {max_cents}c",
                        paper=paper)
        return None

    size_cap = max(1, int(cfg.get("script_max_contracts") or 20))
    contracts = min(
        int(intent.get("size") or max(1, int(cfg.get("crypto15m_order_size", 1)))),
        size_cap,
    )

    close_epoch = crypto15m._parse_close_epoch(a.get("closeTime") or "")
    if close_epoch is not None and close_epoch - kalshi_auth.server_now() < 10.0:
        return None

    coid = f"krypt-scr-{a['asset']}-{uuid.uuid4().hex[:8]}"
    row = {
        "asset": a["asset"], "series": a.get("series") or "",
        "ticker": ticker, "side": side, "direction": direction,
        "target_contracts": contracts, "entry_limit_cents": limit_cents,
        "client_order_id": coid, "close_time": a.get("closeTime") or "",
        "confidence": float(a.get("favoritePrice") or 0.0) * 100.0,
        "kalshi_env": env, "strategy": f"script:{sid[:8]}", "script_id": sid,
        "tp_pct": intent.get("take_profit_pct"),
        "sl_cents": intent.get("stop_loss_cents"),
        "mgmt_config": _SCRIPT_MGMT_SNAPSHOT,
    }

    if paper:
        row.update({"status": "submitted", "dry_run": True})
        with db.get_db() as conn:
            pid = db.insert_crypto15m_position(conn, row)
            logger.info(
                f"[scripts] {sid[:8]} PAPER entry {a['asset']} {direction} "
                f"x{contracts} @ {limit_cents}c ({intent.get('reason') or 'no reason'})"
            )
            return db.fetch_crypto15m_by_id(conn, pid)

    row.update({"status": "placing", "dry_run": False})
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, row)

    try:
        resp = await kalshi_api.place_limit_order(
            ticker=ticker, side=direction, action="buy",
            count=contracts, price_cents=limit_cents, client_order_id=coid,
        )
    except Exception as e:
        recovered, lookup_ok = await crypto15m_trader._lookup_lost_order(
            coid, ticker or "")
        with db.get_db() as conn:
            if isinstance(recovered, dict) and recovered.get("order_id"):
                db.update_crypto15m_position(
                    conn, pid, status="submitted",
                    kalshi_order_id=recovered.get("order_id"),
                )
                logger.warning(
                    f"[scripts] {sid[:8]} entry {a['asset']} recovered via "
                    f"client_order_id after order error: {e}")
            elif lookup_ok:
                db.update_crypto15m_position(conn, pid, error=str(e)[:200])
                crypto15m_trader._mark_resolved(conn, pid, status="error")
                logger.error(f"[scripts] {sid[:8]} entry failed {a['asset']}: {e}")
            else:
                db.update_crypto15m_position(
                    conn, pid, error=f"UNCONFIRMED: {str(e)[:160]}")
            return db.fetch_crypto15m_by_id(conn, pid)

    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    with db.get_db() as conn:
        db.update_crypto15m_position(
            conn, pid, status="submitted",
            kalshi_order_id=order.get("order_id") if isinstance(order, dict) else None,
        )
        logger.info(
            f"[scripts] {sid[:8]} entry {a['asset']} {direction} "
            f"x{contracts} @ {limit_cents}c ({intent.get('reason') or 'no reason'})"
        )
        return db.fetch_crypto15m_by_id(conn, pid)


def _pos_lite(r: dict) -> dict:
    return {
        "id": r.get("id"), "ticker": r.get("ticker"), "asset": r.get("asset"),
        "side": r.get("side"), "contracts": r.get("filled_contracts") or 0,
        "avgEntryCents": r.get("avg_entry_cents"),
        "status": r.get("status"), "pnlUsd": r.get("pnl_usd"),
        "exitReason": r.get("exit_reason"), "won": r.get("outcome_correct"),
    }


def _snake_to_camel(k: str) -> str:
    parts = k.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def _sanitize_supervise(raw) -> tuple[dict, list[str]]:
    if raw is None:
        return {}, []
    if not isinstance(raw, dict) or not isinstance(raw.get("set"), dict):
        return {}, ["supervise() must return None or {\"set\": {key: value}}"]
    patch: dict = {}
    notes: list[str] = []
    for k, v in raw["set"].items():
        kind = _SUPERVISE_KEYS.get(str(k))
        if kind is None:
            notes.append(f"key '{k}' is not supervisable (ignored)")
            continue
        try:
            if kind == "bool":
                if bool(v):
                    notes.append(f"'{k}': scripts may turn engines off, not on "
                                 "(ignored)")
                    continue
                patch[str(k)] = False
            elif kind == "float":
                fv = float(v)
                if fv != fv or fv in (float("inf"), float("-inf")):
                    notes.append(f"'{k}': non-finite value (ignored)")
                    continue
                patch[str(k)] = fv
            elif kind == "mode":
                mv = str(v).lower()
                if mv not in ("favorite", "contrarian", "model"):
                    notes.append(f"'{k}' must be favorite|contrarian|model (ignored)")
                    continue
                patch[str(k)] = mv
        except (TypeError, ValueError):
            notes.append(f"'{k}' got a non-{kind} value (ignored)")
    return patch, notes


async def _run_supervise(s: dict, mod: script_sandbox.CompiledScript,
                         cfg: dict, app: dict) -> None:
    sid = str(s["id"])
    raw = await _call_hook(mod, "supervise", dict(app))
    patch, notes = _sanitize_supervise(raw)
    for n in notes:
        logger.info(f"[scripts] {sid[:8]} supervise: {n}")
    if not patch:
        return
    patch = {k: v for k, v in patch.items() if cfg.get(k) != v}
    if not patch:
        return
    if time.time() - _last_patch_t.get(sid, 0.0) < _SUPERVISE_MIN_INTERVAL_S:
        return
    _last_patch_t[sid] = time.time()
    camel = {_snake_to_camel(k): v for k, v in patch.items()}
    logger.warning(
        f"[scripts] {s.get('name')} ({sid[:8]}) SUPERVISOR config change: {patch}"
    )
    await _emit_event("script:configPatch", {
        "id": sid, "name": s.get("name"), "patch": camel,
    })


async def _paper_script_sell(pos: dict, env: str) -> None:
    market = crypto15m_trader._ws_quote_market(pos["ticker"])
    if market is None:
        try:
            market = await kalshi_api.fetch_market(pos["ticker"])
        except Exception:
            market = None
    bid_c = crypto15m_trader._paper_side_bid_cents(market, pos.get("side") or "")
    if bid_c is None:
        return
    filled = int(pos.get("filled_contracts") or 0)
    cost = float(pos.get("cost_usd") or 0.0)
    proceeds = filled * bid_c / 100.0
    fee = crypto15m_trader._paper_fee_usd(bid_c, filled, "taker")
    pnl = proceeds - cost - float(pos.get("fees_usd") or 0.0) - fee
    with db.get_db() as conn:
        crypto15m_trader._mark_resolved(
            conn, int(pos["id"]), status="settled", exit_reason="script_exit",
            settlement_usd=proceeds, proceeds_usd=proceeds,
            exit_filled_contracts=filled, exit_fees_usd=fee, pnl_usd=pnl,
            outcome_correct=1 if pnl > 0.01 else 0,
        )
    logger.info(f"[scripts] PAPER script_exit {pos.get('asset')} pnl=${pnl:+.2f}")


async def _manage_pass(s: dict, mod: script_sandbox.CompiledScript, cfg: dict,
                       env: str, assets_by_ticker: dict, portfolio: dict) -> None:
    sid = str(s["id"])
    with db.get_db() as conn:
        rows = _open_crypto_for_script(conn, sid, env)
    for pos in rows:
        if pos.get("status") != "filled" or int(pos.get("filled_contracts") or 0) <= 0:
            continue
        a = assets_by_ticker.get(str(pos.get("ticker")))
        ctx = dict(a) if a else {
            "ticker": pos.get("ticker"), "asset": pos.get("asset"),
            "hasMarket": False, "minsLeft": None,
        }
        ctx["portfolio"] = portfolio
        bid_cents = None
        if a:
            if pos.get("side") == "up":
                yb = a.get("yesBid")
                bid_cents = round(float(yb) * 100, 1) if yb else None
            else:
                ya = a.get("yesAsk")
                bid_cents = round((1.0 - float(ya)) * 100, 1) if ya else None
        entry_c = float(pos.get("avg_entry_cents") or pos.get("entry_limit_cents") or 0)
        pos_lite = {
            "ticker": pos.get("ticker"), "asset": pos.get("asset"),
            "side": pos.get("side"),
            "contracts": int(pos.get("filled_contracts") or 0),
            "avgEntryCents": entry_c, "curBidCents": bid_cents,
            "minsLeft": ctx.get("minsLeft"),
            "tpPct": pos.get("tp_pct"), "slCents": pos.get("sl_cents"),
            "unrealizedPct": round((bid_cents - entry_c) / entry_c, 4)
            if bid_cents is not None and entry_c > 0 else None,
        }
        act_raw = await _call_hook(mod, "manage", pos_lite, ctx)
        act, err = sanitize_manage(act_raw)
        if err:
            raise script_sandbox.ScriptError(f"manage(): {err}")
        if act is None:
            continue
        if act["action"] == "sell":
            if pos.get("dry_run"):
                await _paper_script_sell(pos, env)
            else:
                market = crypto15m_trader._ws_quote_market(pos["ticker"])
                if market is None:
                    try:
                        market = await kalshi_api.fetch_market(pos["ticker"])
                    except Exception:
                        market = None
                if market is None:
                    logger.info(
                        f"[scripts] {sid[:8]} manage sell {pos.get('asset')}: "
                        "no market quote — retry next tick")
                    continue
                await crypto15m_trader._place_exit(
                    pos, market, cfg, reason="script_exit")
        else:
            fields = {}
            if "take_profit_pct" in act:
                fields["tp_pct"] = act["take_profit_pct"] or None
            if "stop_loss_cents" in act:
                fields["sl_cents"] = act["stop_loss_cents"] or None
            if fields:
                with db.get_db() as conn:
                    db.update_crypto15m_position(conn, int(pos["id"]), **fields)


def _fetch_new_signals() -> list[tuple[dict, str]]:
    out: list[tuple[dict, str]] = []
    try:
        with db.get_db() as conn:
            for table, source in (("whale_trades", "whale"), ("alerts", "momentum")):
                mark = _sig_marks[source]
                if mark is None:
                    row = conn.execute(f"SELECT MAX(id) FROM {table}").fetchone()
                    _sig_marks[source] = int(row[0] or 0)
                    continue
                rows = conn.execute(
                    f"""SELECT * FROM {table} WHERE id > ?
                        ORDER BY id ASC LIMIT 50""",
                    (mark,),
                ).fetchall()
                for r in rows:
                    d = dict(r)
                    _sig_marks[source] = max(_sig_marks[source] or 0, int(d["id"]))
                    out.append((d, source))
    except Exception as e:
        logger.debug(f"[scripts] signal fetch: {e}")
    return out


async def _place_signal_follow(s: dict, sig: dict, source: str, act: dict,
                               cfg: dict, env: str) -> Optional[dict]:
    sid = str(s["id"])
    ticker = str(sig.get("ticker") or "")
    direction = str(sig.get("taker_side") or sig.get("direction") or "").lower()
    if not ticker or direction not in ("yes", "no"):
        return None
    max_cents = int(cfg.get("script_max_entry_cents") or 97)
    ask = None
    try:
        m = await kalshi_api.fetch_market(ticker)
        if m:
            ya = crypto15m._price_dollars(m, "yes_ask")
            yb = crypto15m._price_dollars(m, "yes_bid")
            if direction == "yes":
                ask = int(round(ya * 100)) if ya else None
            else:
                ask = int(round((1.0 - yb) * 100)) if yb else None
    except Exception as e:
        logger.debug(f"[scripts] signal quote {ticker}: {e}")
    if not ask or not (1 <= int(ask) <= 99):
        return None
    limit_cents = int(ask)
    if limit_cents > max_cents:
        return None
    spend = float(act.get("sizeUsd") or cfg.get("fixed_trade_usd") or 5.0)
    contracts = int(spend // (limit_cents / 100.0))
    contracts = min(max(contracts, 1), max(1, int(cfg.get("script_max_contracts") or 20)))
    coid = f"krypt-scrs-{uuid.uuid4().hex[:10]}"
    row = {
        "signal_source": f"script:{sid[:8]}:{source}",
        "signal_id": int(sig.get("id") or 0),
        "ticker": ticker, "event_ticker": sig.get("event_ticker") or "",
        "title": sig.get("title") or ticker,
        "category": sig.get("category") or "",
        "direction": direction, "action": "buy",
        "target_contracts": contracts, "limit_price_cents": limit_cents,
        "client_order_id": coid, "confidence": 0.0, "edge_pts": 0.0,
        "signal_price": float(limit_cents), "kalshi_env": env,
        "status": "submitted",
    }
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, row)
        conn.execute("UPDATE bot_positions SET script_id=? WHERE id=?",
                     (sid, pid))
    try:
        resp = await kalshi_api.place_limit_order(
            ticker=ticker, side=direction, action="buy",
            count=contracts, price_cents=limit_cents, client_order_id=coid,
        )
    except Exception as e:
        found, confirmed = await crypto15m_trader._lookup_lost_order(coid, ticker)
        with db.get_db() as conn:
            if isinstance(found, dict) and found.get("order_id"):
                db.update_bot_position(
                    conn, pid, kalshi_order_id=found.get("order_id"))
                logger.warning(
                    f"[scripts] {sid[:8]} signal follow {ticker} recovered via "
                    f"client_order_id after order error: {e}")
            elif confirmed:
                db.update_bot_position(
                    conn, pid, status="error", resolved=1,
                    error=str(e)[:200])
                logger.error(
                    f"[scripts] {sid[:8]} signal follow {ticker} failed: {e}")
            else:
                db.update_bot_position(
                    conn, pid, error=f"UNCONFIRMED: {str(e)[:160]}")
            return db.fetch_position_by_id(conn, pid)
    order = (resp.get("order") if isinstance(resp, dict) else None) or resp or {}
    oid = order.get("order_id") if isinstance(order, dict) else None
    with db.get_db() as conn:
        if oid:
            db.update_bot_position(conn, pid, kalshi_order_id=oid)
        logger.info(
            f"[scripts] {sid[:8]} follows {source} signal: {ticker} "
            f"{direction} x{contracts} @ {limit_cents}c"
        )
        return db.fetch_position_by_id(conn, pid)


async def _notify_lifecycle(scripts_by_id: dict[str, dict], env: str) -> None:
    with db.get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM crypto15m_positions
               WHERE script_id IS NOT NULL AND kalshi_env=?
                 AND (
                   (resolved=0 AND filled_contracts > 0)
                   OR (resolved=1 AND datetime(COALESCE(resolved_at, last_updated))
                       >= datetime('now', '-1 hour'))
                 )""",
            (env,),
        ).fetchall()
    global _lifecycle_primed
    if not _lifecycle_primed:
        for r in rows:
            r = dict(r)
            pid = int(r.get("id") or 0)
            if (r.get("filled_contracts") or 0) > 0:
                _notified_fill.add(pid)
            if r.get("resolved"):
                _notified_settle.add(pid)
        _lifecycle_primed = True
        return
    for r in rows:
        r = dict(r)
        sid = str(r.get("script_id") or "")
        s = scripts_by_id.get(sid)
        if not s or not s.get("enabled"):
            continue
        mod = _compiled.get(sid)
        if mod is None:
            continue
        pid = int(r.get("id") or 0)
        try:
            if (r.get("filled_contracts") or 0) > 0 and pid not in _notified_fill:
                _notified_fill.add(pid)
                await _call_hook(mod, "on_fill", _pos_lite(r), mod.state)
            if r.get("resolved") and pid not in _notified_settle:
                _notified_settle.add(pid)
                await _call_hook(mod, "on_settle", _pos_lite(r), mod.state)
        except script_sandbox.ScriptError as e:
            _disable(sid, str(e))
            await _emit_event("script:status",
                              {"id": sid, "enabled": False, "lastError": str(e)})
    current = {int(dict(r).get("id") or 0) for r in rows}
    _notified_fill.intersection_update(current)
    _notified_settle.intersection_update(current)


def _save_states() -> None:
    global _last_state_save
    if time.time() - _last_state_save < STATE_SAVE_EVERY_S:
        return
    _last_state_save = time.time()
    for sid, mod in list(_compiled.items()):
        try:
            blob = json.dumps(mod.state)[:64 * 1024]
            with db.get_db() as conn:
                db.update_user_script(conn, sid, state_json=blob)
        except (TypeError, ValueError):
            pass
        except Exception as e:
            logger.debug(f"[scripts] state save {sid[:8]}: {e}")


async def _drain_logs(sid: str, mod: script_sandbox.CompiledScript) -> None:
    lines = mod.drain_logs()
    if lines:
        await _emit_event("script:log", {"id": sid, "lines": lines[-40:]})


async def run_tick(cfg: dict, *, authed: bool) -> None:
    if not cfg.get("scripts_live_enabled"):
        return
    paper = bool(cfg.get("scripts_paper_mode"))
    if not authed and not paper:
        return
    with db.get_db() as conn:
        scripts = db.list_user_scripts(conn)
    enabled = [s for s in scripts if s.get("enabled")]
    max_enabled = int(cfg.get("script_max_enabled") or 10)
    enabled = enabled[:max_enabled]
    if not enabled:
        return
    env = kalshi_auth.get_env()
    scripts_by_id = {str(s["id"]): s for s in scripts}

    risk_blocked = False
    if not paper:
        try:
            risk_blocked, risk_reason = trader._is_blocked_by_daily_risk(cfg, env)
            if risk_blocked:
                logger.info(f"[scripts] entries blocked by daily risk: {risk_reason}")
        except Exception:
            risk_blocked = False

    try:
        await _notify_lifecycle(scripts_by_id, env)
    except Exception as e:
        logger.debug(f"[scripts] lifecycle notify: {e}")

    snap = await crypto15m.snapshot(cfg)
    assets = [a for a in (snap.get("assets") or [])
              if a.get("hasMarket") and a.get("ticker")]
    assets_by_ticker = {str(a.get("ticker")): a for a in assets}
    new_signals = _fetch_new_signals()
    balance_usd = None
    if authed:
        try:
            cents, _port = await trader.refresh_balance(cfg, force=False)
            if cents > 0:
                balance_usd = round(cents / 100.0, 2)
        except Exception:
            pass

    for s in enabled:
        sid = str(s["id"])
        mod = await _get_compiled(s)
        if mod is None:
            await _emit_event("script:status", {
                "id": sid, "enabled": False,
                "lastError": "compile failed (see script page)"})
            continue
        try:
            with db.get_db() as conn:
                day_pnl = _script_daily_pnl(conn, sid, env, paper=paper)
                open_count = _count_open_for_script(conn, sid, env, paper=paper)
                open_crypto = _open_crypto_for_script(conn, sid, env)
            _lc = cfg.get("script_daily_loss_usd")
            loss_cap = float(_lc) if _lc is not None else 25.0
            if loss_cap > 0 and day_pnl <= -loss_cap:
                reason = (f"daily loss cap hit ({day_pnl:.2f} <= "
                          f"-{loss_cap:.2f} USD) — re-enable tomorrow or raise the cap")
                _disable(sid, reason)
                await _emit_event("script:status",
                                  {"id": sid, "enabled": False, "lastError": reason})
                continue
        except Exception as e:
            logger.debug(f"[scripts] risk query {sid[:8]}: {e}")
            continue

        portfolio = {
            "balanceUsd": balance_usd,
            "openCount": open_count,
            "openPositions": [_pos_lite(p) for p in open_crypto],
            "todayPnlUsd": round(day_pnl, 2),
        }

        try:
            if "manage" in mod.hooks and open_crypto:
                await _manage_pass(s, mod, cfg, env, assets_by_ticker, portfolio)
        except script_sandbox.ScriptError as e:
            _disable(sid, str(e))
            await _emit_event("script:status",
                              {"id": sid, "enabled": False, "lastError": str(e)})
            await _drain_logs(sid, mod)
            continue

        max_open = int(cfg.get("script_max_open") or 2)
        died = False
        if "decide" in mod.hooks and not risk_blocked:
            for a in assets:
                if open_count >= max_open:
                    break
                if not crypto15m.asset_enabled(cfg, str(a.get("asset") or "")):
                    continue
                try:
                    with db.get_db() as conn:
                        if _already_attempted(conn, sid, str(a.get("ticker")), env):
                            continue
                except Exception:
                    continue
                ctx = dict(a)
                ctx["portfolio"] = portfolio
                try:
                    raw = await _call_hook(mod, "decide", ctx)
                except script_sandbox.ScriptError as e:
                    _disable(sid, str(e))
                    await _emit_event("script:status",
                                      {"id": sid, "enabled": False, "lastError": str(e)})
                    died = True
                    break
                if raw is None:
                    continue
                intent, err = sanitize_intent(raw)
                if err:
                    _disable(sid, f"malformed intent: {err}")
                    await _emit_event("script:status",
                                      {"id": sid, "enabled": False,
                                       "lastError": f"malformed intent: {err}"})
                    died = True
                    break
                try:
                    placed = await _place_intent(s, a, intent, cfg, env, paper=paper)
                except Exception as e:
                    logger.error(f"[scripts] place {sid[:8]} {a.get('asset')}: {e}")
                    continue
                if placed is not None:
                    open_count += 1
        if died:
            await _drain_logs(sid, mod)
            continue

        if ("decide_signal" in mod.hooks and new_signals
                and authed and not paper and not risk_blocked):
            for sig, source in new_signals:
                if open_count >= max_open:
                    break
                try:
                    raw = await _call_hook(mod, "decide_signal", signal_to_js(sig, source))
                except script_sandbox.ScriptError as e:
                    _disable(sid, str(e))
                    await _emit_event("script:status",
                                      {"id": sid, "enabled": False, "lastError": str(e)})
                    died = True
                    break
                act, err = sanitize_signal_action(raw)
                if err:
                    _disable(sid, f"malformed decide_signal return: {err}")
                    died = True
                    break
                if act is None:
                    continue
                try:
                    placed = await _place_signal_follow(s, sig, source, act, cfg, env)
                except Exception as e:
                    logger.error(f"[scripts] signal follow {sid[:8]}: {e}")
                    continue
                if placed is not None:
                    open_count += 1
        if died:
            await _drain_logs(sid, mod)
            continue

        try:
            if "supervise" in mod.hooks:
                app = {
                    "hourUtc": datetime.now(timezone.utc).hour,
                    "balanceUsd": balance_usd,
                    "scriptTodayPnlUsd": round(day_pnl, 2),
                    "engines": {
                        "mainTrading": bool(cfg.get("enable_trading")),
                        "whales": bool(cfg.get("trade_whales")),
                        "momentum": bool(cfg.get("trade_momentum")),
                        "crypto15m": bool(cfg.get("crypto15m_enabled")),
                    },
                    "config": {k: cfg.get(k) for k in _SUPERVISE_KEYS},
                    "assets": [{
                        "asset": a.get("asset"), "minsLeft": a.get("minsLeft"),
                        "sigma1m": a.get("sigma1m"), "modelProb": a.get("modelProb"),
                        "favoritePrice": a.get("favoritePrice"),
                    } for a in assets],
                }
                await _run_supervise(s, mod, cfg, app)
        except script_sandbox.ScriptError as e:
            _disable(sid, str(e))
            await _emit_event("script:status",
                              {"id": sid, "enabled": False, "lastError": str(e)})

        await _drain_logs(sid, mod)
    _save_states()
