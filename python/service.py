from __future__ import annotations

import asyncio
import concurrent.futures as _cf
import io
import json
import logging
import logging.handlers
import multiprocessing as _mp
import os
import random
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

if __name__ == "__main__" and "--mcp-stdio" in sys.argv[1:]:
    import mcp_bridge
    sys.exit(mcp_bridge.main(sys.argv[1:]))


_log_q: asyncio.Queue | None = None


class _StdoutHandler(logging.Handler):

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        source = "backend"
        if record.name.startswith("trader"):
            source = "trader"
        elif record.name.startswith("scanner"):
            source = "whale" if "whale" in msg.lower()[:20] else "momentum"
        elif record.name.startswith("remote"):
            source = "remote"
        elif record.name.startswith("terminal") or record.name.startswith("crossvenue"):
            source = "terminal"
        elif record.name.startswith("webhook") or record.name.startswith("discord"):
            source = "discord"
        try:
            evt = {
                "type": "log",
                "level": record.levelname,
                "source": source,
                "msg": msg,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            sys.stdout.write(json.dumps(evt) + "\n")
            sys.stdout.flush()
        except Exception:
            pass


def _setup_logging() -> None:
    log_dir_base = os.environ.get("KRYPT_TRADER_USERDATA")
    if log_dir_base:
        log_dir = Path(log_dir_base) / "logs"
    else:
        log_dir = Path(__file__).resolve().parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "[%(asctime)s] %(levelname)-7s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    try:
        import logscrub
        _scrub_filter = logscrub.ScrubFilter()
    except Exception:
        _scrub_filter = None
    fh = logging.handlers.RotatingFileHandler(
        log_dir / "backend.log", maxBytes=10 * 1024 * 1024,
        backupCount=5, encoding="utf-8",
    )
    fh.setFormatter(fmt)
    if _scrub_filter is not None:
        fh.addFilter(_scrub_filter)
    root.addHandler(fh)
    sh = _StdoutHandler()
    sh.setFormatter(fmt)
    if _scrub_filter is not None:
        sh.addFilter(_scrub_filter)
    root.addHandler(sh)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    logging.getLogger("httpcore2").setLevel(logging.WARNING)




_setup_logging()
logger = logging.getLogger("service")


import db
import kalshi_api
import kalshi_auth
import scanner
import crypto15m
import trader
import crypto15m_trader
import crypto15m_record
import script_engine
import script_sandbox
import perps_ws
import perps_farmer
import kalshi_perps_api
import webhook
import kalshi_ws
import spot_ws
import terminal
import remote
import ai_analyst
import forecast_ledger
import paper_book
import paper_exchange
import mcp_server
import mcp_agents
import mcp_workbench
import shard_rail
import autopilot
import health
import kalshi_key_check
import remote_discord
import remote_telegram
from config import DEFAULT_CONFIG, merge_with_defaults, scope_env

DATA_ENV = "production"


def _iso_utc(s: Any) -> Any:
    if not s:
        return s
    if not isinstance(s, str):
        return s
    s = s.strip()
    if not s:
        return s
    if s.endswith("Z") or "+" in s[10:] or s.count("-") > 2:
        return s.replace(" ", "T")
    return s.replace(" ", "T") + "Z"




class State:
    cfg: dict[str, Any] = dict(DEFAULT_CONFIG)
    auth_ok: bool = False
    paused: bool = False
    last_whale_scan_at: str | None = None
    last_momentum_scan_at: str | None = None
    last_trade_scan_at: str | None = None
    started_at: str = ""
    active_run_id: int = 0
    ws_fill_pending: bool = False
    ws_resolve_pending: bool = False
    ws_whale_pending: bool = False
    ws_c15_pending: bool = False
    api_tier: str = ""
    last_api_upgrade_at: float = 0.0


STATE = State()
shard_rail.GET_CFG = lambda: merge_with_defaults(dict(STATE.cfg or {}))

FORECAST_RESOLVE_SEC = 300.0




_stdout_lock = asyncio.Lock()


async def _send(obj: dict) -> None:
    line = json.dumps(obj, default=str) + "\n"
    async with _stdout_lock:
        sys.stdout.write(line)
        sys.stdout.flush()


async def emit_event(name: str, data: Any = None) -> None:
    await _send({"type": "event", "name": name, "data": data})


async def respond_ok(req_id: str, result: Any = None) -> None:
    await _send({"type": "rpc", "id": req_id, "ok": True, "result": result})


async def respond_err(req_id: str, msg: str, code: Optional[str] = None) -> None:
    out = {"type": "rpc", "id": req_id, "ok": False, "error": msg}
    if code:
        out["code"] = code
    await _send(out)


def human_error(e: BaseException) -> str:
    """What a failed RPC tells the user: the exception's own words, never
    "KeyError: 'x'" or "TimeoutError: " — the class goes in the response's
    `code` and the full detail in the log. Scrubbed like a log line, because
    an exception message can quote whatever the failing call was handed."""
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        msg = str(e).strip() or "Timed out waiting for a reply. Try again."
    elif isinstance(e, KeyError):
        msg = f"Missing value: {e.args[0]}" if e.args else "A required value was missing."
    else:
        msg = str(e).strip() or "Something went wrong in the backend. Details are in the log."
    try:
        import logscrub
        msg = logscrub.scrub(msg)
    except Exception:
        pass
    return msg[:500]




async def _start_run_if_balance_known(env: str, cents: int) -> None:
    """Start a bot_run only when the balance is actually known. A cold/failed
    balance fetch returns (0,0); recording that as start_total would poison
    bot_runs (the per-run P&L shown on History), so defer instead."""
    if trader.cached_balance(env) is None:
        logger.warning(f"deferring bot_run start ({env}): balance not yet known")
        return
    with db.get_db() as conn:
        stats = db.aggregate_stats(conn, env)
        port_usd = (db.open_filled_cost_usd(conn, env)
                    + db.open_crypto15m_filled_cost_usd(conn, env))
        STATE.active_run_id = db.start_bot_run(
            conn, env=env,
            cash_usd=cents / 100.0,
            portfolio_usd=port_usd,
            lifetime_trades=int(stats.get("total_opened") or 0),
            lifetime_wins=int(stats.get("wins") or 0),
            lifetime_losses=int(stats.get("losses") or 0),
        )
    logger.info(
        f"Bot run #{STATE.active_run_id} started "
        f"(env={env}, start_total=${cents / 100.0 + port_usd:.2f})"
    )


async def _build_account_snapshot() -> dict:
    env = kalshi_auth.get_env()
    cash_cents = 0
    balance_known = False
    if STATE.auth_ok:
        try:
            await trader.refresh_balance(STATE.cfg, force=False)
        except Exception:
            pass
        bal = trader.cached_balance(env)
        if bal is not None:
            cash_cents = int(bal.get("cents", 0))
            balance_known = True
    cash_usd = cash_cents / 100.0
    with db.get_db() as conn:
        stats_env = db.aggregate_stats(conn, env)
        stats_paper = db.aggregate_stats(conn, db.PAPER_ENV)
        stats_prod = db.aggregate_stats(conn, db.LIVE_ENV)
        stats_retired = db.aggregate_stats(conn, db.RETIRED_ENV)
        crypto_open_cost = db.open_crypto15m_filled_cost_usd(conn, env)
        account_open_cost = db.open_filled_cost_usd(conn, env)
        balance_syncing = db.recent_balance_transition(conn, env)
    open_cost = stats_env["open_cost"]
    port_usd = account_open_cost + crypto_open_cost
    if env == db.PAPER_ENV:
        try:
            port_usd += paper_book.agents_open_cost_usd()
        except Exception as e:
            logger.debug(f"paper agents' open cost unavailable: {e}")
    total = cash_usd + port_usd

    paper = env == db.PAPER_ENV
    user_start = float(STATE.cfg.get("start_bankroll_usd", 0.0) or 0.0)
    if paper:
        baseline = paper_exchange.bankroll()
        baseline_source = "paper"
    elif user_start > 0:
        baseline = user_start
        baseline_source = "user"
    else:
        with db.get_db() as conn:
            earliest = db.earliest_pnl_total(conn, env)
        if earliest and earliest > 0:
            baseline = earliest
            baseline_source = "auto"
        else:
            baseline = total if total > 0 else 0.0
            baseline_source = "live"
    roi = ((total - baseline) / baseline * 100.0) if baseline > 0 else 0.0

    wl = stats_env["wins"] + stats_env["losses"]
    wr = (stats_env["wins"] / wl * 100.0) if wl else 0.0
    unrealized = 0.0

    with db.get_db() as conn:
        first_today = db.first_snapshot_of_today(
            conn, env, int(STATE.cfg.get("trading_timezone_offset_min", 0) or 0))
        bankroll_baseline_snap = db.earliest_pnl_total(conn, env)
        active_run = db.get_active_run(conn, env) if STATE.active_run_id else None

    today_balance_baseline = (
        float(first_today["total_usd"]) if first_today else None
    )
    today_balance_pnl = (
        total - today_balance_baseline
        if today_balance_baseline is not None else 0.0
    )
    alltime_balance_baseline = (
        float(bankroll_baseline_snap)
        if bankroll_baseline_snap is not None else baseline
    )
    alltime_balance_pnl = total - alltime_balance_baseline

    if active_run:
        session_baseline = float(active_run.get("start_total_usd") or 0.0)
        session_started_at = _iso_utc(
            active_run.get("started_at") or STATE.started_at
        )
        session_run_id = int(active_run.get("id") or 0)
    else:
        session_baseline = total
        session_started_at = STATE.started_at
        session_run_id = 0
    session_pnl = total - session_baseline if session_baseline > 0 else 0.0
    session_roi = (
        (session_pnl / session_baseline * 100.0)
        if session_baseline > 0 else 0.0
    )

    shard_cash = None
    if STATE.auth_ok:
        shards = trader.cached_shard_balances(env)
        if shards:
            shard_cash = {
                str(idx): {
                    "name": kalshi_api.shard_name(idx),
                    "cashUsd": round(float(dollars), 2),
                }
                for idx, dollars in sorted(shards.items())
            }

    return {
        "shardCash": shard_cash,
        "shardTransferUrl": kalshi_api.web_exchange_indexes_url(env),
        "accountMode": "paper" if paper else "live",
        "balanceKnown": balance_known,
        "cashUsd": cash_usd,
        "portfolioUsd": port_usd,
        "totalUsd": total,
        "apiTier": STATE.api_tier or None,
        "balanceSyncing": balance_syncing,
        "startBankrollUsd": baseline,
        "bankrollSource": baseline_source,
        "roiPct": roi,
        "realizedPnlUsd": stats_env["realized_pnl"],
        "todayPnlUsd": today_balance_pnl,
        "alltimePnlUsd": alltime_balance_pnl,
        "todayBaselineUsd": today_balance_baseline,
        "alltimeBaselineUsd": alltime_balance_baseline,
        "sessionPnlUsd": session_pnl,
        "sessionRoiPct": session_roi,
        "sessionBaselineUsd": session_baseline,
        "sessionStartedAt": session_started_at,
        "sessionRunId": session_run_id,
        "todayWins": stats_env["today_wins"],
        "todayLosses": stats_env["today_losses"],
        "unrealizedPnlUsd": unrealized,
        "openCostUsd": open_cost,
        "feesUsd": stats_env["fees"],
        "wins": stats_env["wins"],
        "losses": stats_env["losses"],
        "winRate": wr,
        "pendingCount": stats_env["pending"],
        "openCount": stats_env["open_filled"],
        "resolvedCount": stats_env["resolved_count"],
        "totalOpened": stats_env["total_opened"],
        "byEnv": {
            "paper": {
                "wins": stats_paper["wins"],
                "losses": stats_paper["losses"],
                "realizedPnl": stats_paper["realized_pnl"],
            },
            "demo": {
                "wins": stats_retired["wins"],
                "losses": stats_retired["losses"],
                "realizedPnl": stats_retired["realized_pnl"],
            },
            "production": {
                "wins": stats_prod["wins"],
                "losses": stats_prod["losses"],
                "realizedPnl": stats_prod["realized_pnl"],
            },
        },
    }




def _live_pnl_usd(r: dict) -> float | None:
    """Unrealized (mark-to-market) P&L for an OPEN filled position: held
    contracts valued at the live mark price minus cost. None for resolved rows
    (use realized pnl), unfilled rows, or rows without a mark yet."""
    if r.get("resolved"):
        return None
    mark = r.get("mark_price_cents")
    if mark is None:
        return None
    filled = int(r.get("filled_contracts") or 0)
    if filled <= 0:
        return None
    market_value = filled * float(mark) / 100.0
    return round(market_value - float(r.get("cost_usd") or 0.0), 2)


def _position_row_to_js(r: dict) -> dict:
    return {
        "id": int(r["id"]),
        "signalSource": r["signal_source"],
        "signalId": int(r["signal_id"]),
        "ticker": r["ticker"],
        "eventTicker": r.get("event_ticker") or "",
        "title": r.get("title") or "",
        "category": r.get("category") or "",
        "direction": r["direction"],
        "action": r.get("action") or "buy",
        "targetContracts": int(r.get("target_contracts") or 0),
        "limitPriceCents": int(r.get("limit_price_cents") or 0),
        "filledContracts": int(r.get("filled_contracts") or 0),
        "avgFillPriceCents": (
            float(r["avg_fill_price_cents"])
            if r.get("avg_fill_price_cents") is not None
            else None
        ),
        "costUsd": float(r.get("cost_usd") or 0),
        "feesUsd": float(r.get("fees_usd") or 0),
        "clientOrderId": r.get("client_order_id") or "",
        "kalshiOrderId": r.get("kalshi_order_id"),
        "status": r["status"],
        "confidence": float(r.get("confidence") or 0),
        "edgePts": (None if (r.get("signal_source") or "") == "manual"
                    or r.get("edge_pts") is None else float(r["edge_pts"])),
        "signalPriceCents": float(r.get("signal_price") or 0),
        "resolved": bool(r.get("resolved") or 0),
        "outcomeCorrect": (
            int(r["outcome_correct"])
            if r.get("outcome_correct") is not None
            else None
        ),
        "settlementUsd": (
            float(r["settlement_usd"])
            if r.get("settlement_usd") is not None
            else None
        ),
        "pnlUsd": float(r["pnl_usd"]) if r.get("pnl_usd") is not None else None,
        "markPriceCents": (
            float(r["mark_price_cents"])
            if r.get("mark_price_cents") is not None
            else None
        ),
        "livePnlUsd": _live_pnl_usd(r),
        "balanceBeforeUsd": (
            float(r["balance_before_usd"])
            if r.get("balance_before_usd") is not None
            else None
        ),
        "kalshiEnv": r.get("kalshi_env") or db.RETIRED_ENV,
        "createdAt": _iso_utc(r.get("created_at")) or "",
        "lastUpdated": _iso_utc(r.get("last_updated")) or "",
        "resolvedAt": _iso_utc(r.get("resolved_at")),
        "error": r.get("error"),
    }


def _signal_row_to_js(r: dict, source: str, traded: bool) -> dict:
    if source == "whale":
        price_frac = float(r.get("price") or 0)
        price_c = int(round(price_frac * 100))
        return {
            "id": int(r["id"]),
            "source": "whale",
            "ticker": r["ticker"],
            "eventTicker": r.get("event_ticker") or "",
            "title": r.get("title") or r.get("ticker", ""),
            "category": r.get("category") or "",
            "direction": (r.get("taker_side") or "yes").lower(),
            "priceCents": price_c,
            "confidence": float(r.get("confidence") or 0),
            "edgePts": float(r.get("confidence") or 0) - price_c,
            "dollarValue": float(r.get("dollar_value") or 0),
            "createdAt": _iso_utc(r.get("created_at")) or "",
            "resolved": bool(r.get("resolved") or 0),
            "outcomeCorrect": (
                int(r["outcome_correct"])
                if r.get("outcome_correct") is not None
                else None
            ),
            "pnlEstimate": (
                float(r["pnl_estimate"])
                if r.get("pnl_estimate") is not None
                else None
            ),
            "traded": traded,
        }
    direction = (r.get("direction") or "yes").lower()
    price_frac = float(r.get("price") or 0)
    yes_c = int(round(price_frac * 100))
    cost_c = yes_c if direction == "yes" else max(0, 100 - yes_c)
    implied = yes_c if direction == "yes" else 100 - yes_c
    return {
        "id": int(r["id"]),
        "source": "momentum",
        "ticker": r["ticker"],
        "eventTicker": r.get("event_ticker") or "",
        "title": r.get("title") or r.get("ticker", ""),
        "category": r.get("category") or "",
        "direction": direction,
        "priceCents": cost_c,
        "confidence": float(r.get("confidence") or 0),
        "edgePts": float(r.get("confidence") or 0) - implied,
        "signalType": r.get("signal_type") or "",
        "createdAt": _iso_utc(r.get("created_at")) or "",
        "resolved": bool(r.get("resolved") or 0),
        "outcomeCorrect": (
            int(r["outcome_correct"])
            if r.get("outcome_correct") is not None
            else None
        ),
        "pnlEstimate": (
            float(r["pnl_estimate"])
            if r.get("pnl_estimate") is not None
            else None
        ),
        "traded": traded,
    }




_loop_task: asyncio.Task | None = None
_c15_task: asyncio.Task | None = None
_script_task: asyncio.Task | None = None
_loop_stop: asyncio.Event | None = None

_bg_tasks: set[asyncio.Task] = set()


def _fire_and_forget(coro) -> None:
    """Run a notification coroutine (Discord webhook) as a background task —
    a slow or unreachable Discord must never stall the trading loop (inline
    awaits cost up to 8s per send, multiplied by event bursts). Errors are
    swallowed (webhooks are best-effort); a strong reference is kept so the
    task can't be garbage-collected mid-flight."""
    async def _quiet():
        try:
            await coro
        except Exception:
            pass
    try:
        t = asyncio.get_event_loop().create_task(_quiet())
    except RuntimeError:
        return
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)


_event_webhook_last: dict[int, str] = {}


def _should_fire_event_webhook(pos_id: int, kind: str) -> bool:
    if not pos_id:
        return True
    if _event_webhook_last.get(pos_id) == kind:
        return False
    _event_webhook_last[pos_id] = kind
    if len(_event_webhook_last) > 2000:
        for old in list(_event_webhook_last)[:500]:
            _event_webhook_last.pop(old, None)
    return True


def _on_ws_fill(_msg: dict) -> None:
    """A WebSocket fill arrived — wake the order poll on the next loop tick
    instead of waiting out the 30s timer. REST poll remains the accounting
    truth; this only removes the detection latency."""
    STATE.ws_fill_pending = True
    STATE.ws_c15_pending = True


def _on_ws_lifecycle(msg: dict) -> None:
    """A market was determined/settled — wake the resolution check immediately."""
    if (msg or {}).get("event_type") in ("determined", "settled"):
        STATE.ws_resolve_pending = True


def _on_ws_trade(trade: dict) -> None:
    """Per-trade WS hook (sync, must stay cheap): flag whale-sized prints so the
    scanner runs immediately instead of waiting out whale_scan_interval."""
    try:
        count = float(trade.get("count_fp") or 0)
        side = trade.get("taker_side") or ""
        price = float(
            (trade.get("yes_price_dollars") if side == "yes"
             else trade.get("no_price_dollars")) or 0
        )
        if count * price >= float(STATE.cfg.get("min_whale_usd", 2500) or 2500):
            STATE.ws_whale_pending = True
    except (TypeError, ValueError):
        pass


def _ws_held_tickers() -> set[str]:
    """Tickers we currently hold/work (open bot positions + open 15m positions),
    for the env in play — the set the WS subscribes orderbook/ticker/lifecycle to."""
    env = kalshi_auth.get_env()
    out: set[str] = set()
    try:
        with db.get_db() as conn:
            for r in db.get_open_bot_positions(conn):
                if r.get("kalshi_env") == env and r.get("ticker"):
                    out.add(r["ticker"])
            for r in db.get_open_crypto15m(conn, env):
                if r.get("ticker"):
                    out.add(r["ticker"])
    except Exception:
        pass
    return out


async def _maybe_upgrade_api_level() -> None:
    """Auto-request Kalshi's Advanced API usage level (3x order throughput, free).

    Self-healing: reads the current tier; if it's still `basic`, POSTs the
    upgrade. Kalshi requires >=1 API-placed order in the last 100 (else 403), so
    a brand-new account can't upgrade until the bot has traded once — this keeps
    trying (rate-limited to ~5 min) and lands right after the first order. Never
    raises into the loop. Fully skippable via `auto_upgrade_api_level`."""
    if not STATE.cfg.get("auto_upgrade_api_level", True) or not STATE.auth_ok:
        return
    try:
        lim = await kalshi_api.get_account_limits()
    except Exception:
        return
    tier = str((lim or {}).get("usage_tier") or "").lower()
    if tier:
        STATE.api_tier = tier
    if tier and tier != "basic":
        return
    now = asyncio.get_event_loop().time()
    if STATE.last_api_upgrade_at and now - STATE.last_api_upgrade_at < 300:
        return
    STATE.last_api_upgrade_at = now
    try:
        await kalshi_api.upgrade_api_usage_level()
        logger.info("[api] upgraded to Advanced API usage level (3x order throughput)")
        try:
            lim2 = await kalshi_api.get_account_limits()
            STATE.api_tier = str((lim2 or {}).get("usage_tier") or STATE.api_tier).lower()
        except Exception:
            pass
    except kalshi_api.KalshiAPIError as e:
        if e.status == 403:
            logger.info("[api] API-level upgrade deferred — needs 1 API-placed order first; will auto-retry")
        else:
            logger.debug(f"[api] API-level upgrade failed ({e.status})")
    except Exception as e:
        logger.debug(f"[api] API-level upgrade error: {e}")


async def _reverify_auth_if_needed() -> bool:
    """Self-heal a latched-off auth state.

    The one-shot startup verify in _main() sets STATE.auth_ok=False on a single
    transient failure (network stack not ready when Electron spawns Python at cold
    boot/resume, a Kalshi 5xx/429 burst that outlasts the in-call retry window).
    Every live path — trade scan, order poll, reconcile, resolution — is gated on
    STATE.auth_ok, and nothing else in the loop ever flips it back True, so one
    boot blip silently disables trading for the whole session until the user
    manually re-tests credentials. This re-primes and re-verifies against Kalshi;
    on success it re-enables trading. Returns True iff it flipped auth_ok True.
    """
    if STATE.auth_ok:
        return False
    if kalshi_auth.is_paper():
        STATE.auth_ok = True
        await emit_event("backend:authChanged", {"authOk": True})
        return True
    if not kalshi_auth.credentials_present():
        return False
    async with kalshi_auth.ENV_LOCK:
        env0 = kalshi_auth.get_env()
        kalshi_auth.prime_credentials(sync_time=False)
    await asyncio.to_thread(kalshi_auth.sync_server_time, True)
    bal = await kalshi_api.get_balance(pin_env=env0)
    int(bal.get("balance", 0))
    STATE.auth_ok = True
    await emit_event("backend:authChanged", {"authOk": True})
    return True


async def _scanner_and_trader_loop() -> None:
    last_whale = 0.0
    last_momentum = 0.0
    last_auth_retry = 0.0
    last_api_level_check = 0.0
    last_trade = 0.0
    last_poll = 0.0
    last_resolve = 0.0
    last_market_sync = 0.0
    last_event_sync = 0.0
    last_account_emit = 0.0
    last_snapshot_persist = 0.0
    last_reconcile = 0.0
    last_terminal_rules = 0.0
    last_remote_sync = 0.0
    last_forecast_resolve = 0.0
    last_autopilot_check = 0.0
    _consec_reconcile_fails = 0
    last_crypto15m_record = 0.0
    last_perps_farm = 0.0
    last_ws_subs = 0.0
    last_paper_sweep = 0.0
    last_cleanup = 0.0
    last_stats_push = asyncio.get_event_loop().time()

    try:
        cnt = await scanner.sync_markets(max_pages=10)
        logger.info(f"Initial market sync: {cnt} markets")
    except Exception as e:
        logger.warning(f"initial market sync failed: {e}")


    while not (_loop_stop and _loop_stop.is_set()):
        now = asyncio.get_event_loop().time()
        cfg = STATE.cfg

        kalshi_ws.set_env(kalshi_auth.get_env())
        perps_ws.set_env(kalshi_auth.get_env())

        if STATE.paused:
            await asyncio.sleep(1)
            continue

        try:
            if not STATE.auth_ok and now - last_auth_retry >= 60:
                last_auth_retry = now
                if await _reverify_auth_if_needed():
                    logger.info("auth re-verified — trading re-enabled")
        except Exception as e:
            logger.debug(f"auth re-verify failed (will retry): {e}")

        try:
            if STATE.auth_ok and not kalshi_auth.is_paper() \
                    and STATE.api_tier not in ("advanced", "expert", "premier", "paragon", "prime", "prestige") \
                    and now - last_api_level_check >= 120:
                last_api_level_check = now
                await asyncio.wait_for(_maybe_upgrade_api_level(), 12)
        except Exception as e:
            logger.debug(f"api-level check failed: {e}")

        try:
            if now - last_market_sync >= float(cfg.get("market_refresh_interval", 300)):
                await scanner.sync_markets(max_pages=10)
                last_market_sync = now
            if now - last_event_sync >= 600:
                await scanner.sync_events()
                last_event_sync = now
        except Exception as e:
            logger.warning(f"sync error: {e}")

        try:
            collect_main = bool(cfg.get("main_record_signals", True)) or bool(
                cfg.get("enable_trading")
            )
            whale_due = collect_main and (
                now - last_whale >= float(cfg.get("whale_scan_interval", 120))
                or (STATE.ws_whale_pending and now - last_whale >= 2)
            )
            if whale_due:
                STATE.ws_whale_pending = False
                cnt, rows = await scanner.scan_whales(cfg)
                last_whale = now
                STATE.last_whale_scan_at = datetime.now(timezone.utc).isoformat()
                if cnt:
                    logger.info(f"whale scan: {cnt} new")
                    last_trade = 0.0
                with db.get_db() as conn:
                    seen = db.already_traded_signal_ids(
                        conn, "whale", kalshi_auth.get_env()
                    )
                for row in rows:
                    js = _signal_row_to_js(row, "whale", int(row["id"]) in seen)
                    await emit_event("signal:new", js)
                    if cfg.get("enable_discord"):
                        _fire_and_forget(webhook.send_whale(
                            cfg.get("whale_webhook_url", ""), row
                        ))
        except Exception as e:
            logger.warning(f"whale scan error: {e}")

        try:
            if collect_main and now - last_momentum >= float(cfg.get("momentum_scan_interval", 90)):
                cnt, rows = await scanner.scan_momentum(cfg)
                last_momentum = now
                STATE.last_momentum_scan_at = datetime.now(timezone.utc).isoformat()
                if cnt:
                    logger.info(f"momentum scan: {cnt} new")
                with db.get_db() as conn:
                    seen = db.already_traded_signal_ids(
                        conn, "momentum", kalshi_auth.get_env()
                    )
                for row in rows:
                    js = _signal_row_to_js(row, "momentum", int(row["id"]) in seen)
                    await emit_event("signal:new", js)
                    if cfg.get("enable_discord"):
                        _fire_and_forget(webhook.send_momentum(
                            cfg.get("momentum_webhook_url", ""), row
                        ))
        except Exception as e:
            logger.warning(f"momentum scan error: {e}")

        try:
            if (
                STATE.auth_ok
                and now - last_trade >= float(cfg.get("trade_scan_interval", 20))
            ):
                placed = await trader.scan_for_trades(cfg)
                last_trade = now
                STATE.last_trade_scan_at = datetime.now(timezone.utc).isoformat()
                for row in placed:
                    js = _position_row_to_js(row)
                    await emit_event("position:new", js)
                    if (
                        cfg.get("enable_discord")
                        and _should_fire_event_webhook(int(row.get("id") or 0), "placed")
                    ):
                        _fire_and_forget(webhook.send_event(
                            cfg.get("event_webhook_url", ""),
                            "placed", row, kalshi_auth.get_env(),
                        ))
        except Exception as e:
            logger.error(f"trade scan error: {e}", exc_info=True)

        try:
            if (
                STATE.auth_ok
                and (now - last_poll >= float(cfg.get("position_poll_interval", 30))
                     or STATE.ws_fill_pending)
            ):
                STATE.ws_fill_pending = False
                updated = await trader.poll_open_orders(cfg)
                last_poll = now
                for row in updated:
                    js = _position_row_to_js(row)
                    await emit_event("position:update", js)
                    if cfg.get("enable_discord"):
                        kind = row["status"]
                        if (
                            kind in ("filled", "partial", "canceled", "gone", "error")
                            and _should_fire_event_webhook(
                                int(row.get("id") or 0), kind
                            )
                        ):
                            _fire_and_forget(webhook.send_event(
                                cfg.get("event_webhook_url", ""),
                                kind, row, kalshi_auth.get_env(),
                            ))
        except Exception as e:
            logger.error(f"poll error: {e}", exc_info=True)

        try:
            if STATE.auth_ok and now - last_reconcile >= 30:
                summary, changed = await trader.reconcile_positions_with_kalshi()
                last_reconcile = now
                _consec_reconcile_fails = 0
                if any(summary.values()):
                    logger.info(f"reconcile: {summary}")
                    await emit_event("backend:reconciled", summary)
                for row in changed:
                    await emit_event(
                        "position:update", _position_row_to_js(row),
                    )
        except Exception as e:
            _consec_reconcile_fails += 1
            if _consec_reconcile_fails == 10:
                logger.warning(
                    f"periodic reconcile has failed {_consec_reconcile_fails}x "
                    f"in a row ({e}) — positions may be stale; open-count "
                    f"gating may block new entries"
                )
                await emit_event("backend:degraded", {
                    "component": "reconcile", "error": str(e)[:200],
                    "action": "retrying",
                })
            else:
                logger.debug(f"periodic reconcile failed: {e}")

        try:
            if (
                STATE.auth_ok
                and (now - last_resolve >= float(cfg.get("resolution_check_interval", 300))
                     or STATE.ws_resolve_pending)
            ):
                STATE.ws_resolve_pending = False
                resolved_pos = await trader.mark_resolved_positions(cfg)
                await scanner.resolve_alerts_from_markets()
                await scanner.resolve_whales_from_markets()
                last_resolve = now
                for row in resolved_pos:
                    js = _position_row_to_js(row)
                    await emit_event("position:update", js)
                    if cfg.get("enable_discord"):
                        kind = "won" if row.get("outcome_correct") == 1 else (
                            "lost" if row.get("outcome_correct") == 0 else "na"
                        )
                        if _should_fire_event_webhook(
                            int(row.get("id") or 0), kind
                        ):
                            _fire_and_forget(webhook.send_event(
                                cfg.get("event_webhook_url", ""),
                                kind, row, kalshi_auth.get_env(),
                            ))
        except Exception as e:
            logger.error(f"resolution error: {e}", exc_info=True)


        try:
            if (
                cfg.get("crypto15m_record_signals", True)
                and now - last_crypto15m_record >= 25
            ):
                await crypto15m_record.record_tick(cfg)
                last_crypto15m_record = now
        except Exception as e:
            logger.debug(f"crypto15m record error: {e}")

        try:
            perps_farmer.ensure_ws(cfg, kalshi_auth.get_env())
            if (
                cfg.get("perps_farm_enabled", False)
                and STATE.auth_ok
                and not kalshi_auth.is_paper()
                and now - last_perps_farm >= 2.5
            ):
                await perps_farmer.farm_tick(cfg)
                last_perps_farm = now
            elif not cfg.get("perps_farm_enabled", False):
                await perps_farmer.ensure_stopped()
        except Exception as e:
            logger.debug(f"perps farm error: {e}")

        try:
            if now - last_cleanup >= float(cfg.get("db_cleanup_interval", 3600)):
                summary = await asyncio.get_event_loop().run_in_executor(
                    None, db.run_maintenance
                )
                if summary.get("deleted") or summary.get("vacuumed"):
                    logger.info(
                        f"db maintenance: pruned {summary['deleted']} rows, "
                        f"vacuumed={summary['vacuumed']} "
                        f"(reclaimable {summary['reclaimable_mb']}MB)"
                    )
                last_cleanup = now
        except Exception as e:
            logger.warning(f"db maintenance failed: {e}")

        try:
            if now - last_remote_sync >= 10:
                last_remote_sync = now
                await _sync_remote_bots()
        except Exception as e:
            logger.debug(f"remote bot sync error: {e}")

        try:
            if kalshi_auth.is_paper() and now - last_paper_sweep >= 10:
                last_paper_sweep = now
                res = await paper_exchange.sweep()
                if res.get("filled"):
                    STATE.ws_fill_pending = True
        except Exception as e:
            logger.debug(f"paper sweep error: {e}")

        try:
            if now - last_forecast_resolve >= FORECAST_RESOLVE_SEC:
                last_forecast_resolve = now
                await forecast_ledger.resolve_pending()
                await paper_book.settle_pending()
        except Exception as e:
            logger.debug(f"forecast/paper settlement error: {e}")

        try:
            if now - last_autopilot_check >= 30:
                last_autopilot_check = now
                acfg = merge_with_defaults(dict(cfg or {}))
                if autopilot.due(acfg) and autopilot.blocked_reason(acfg) is None:
                    t = asyncio.create_task(autopilot.run_once(acfg, "schedule"))
                    _bg_tasks.add(t)
                    t.add_done_callback(_bg_tasks.discard)
        except Exception as e:
            logger.debug(f"autopilot schedule error: {e}")

        try:
            terminal.sample_microstructure()
        except Exception as e:
            logger.debug(f"terminal microstructure sample error: {e}")

        try:
            if now - last_terminal_rules >= terminal.RULE_CHECK_SEC:
                last_terminal_rules = now
                fired = await terminal.evaluate_rules(
                    cfg, authed=STATE.auth_ok, on_event=_rule_event,
                )
                del fired
        except Exception as e:
            logger.warning(f"terminal rule evaluation failed: {e}")

        try:
            if kalshi_ws.is_connected() and now - last_ws_subs >= 5:
                watch = (
                    _ws_held_tickers()
                    | crypto15m.active_tickers()
                    | terminal.subscribed_tickers()
                )
                kalshi_ws.set_orderbook_markets(watch)
                kalshi_ws.set_ticker_markets(watch)
                kalshi_ws.set_lifecycle_markets(watch)
                last_ws_subs = now
        except Exception as e:
            logger.debug(f"ws subscription reconcile error: {e}")

        try:
            if now - last_account_emit >= 15:
                snap = await _build_account_snapshot()
                balance_known = trader.cached_balance(kalshi_auth.get_env()) is not None
                if STATE.auth_ok and balance_known and now - last_snapshot_persist >= 60:
                    last_snapshot_persist = now
                    with db.get_db() as conn:
                        db.insert_pnl_snapshot(
                            conn,
                            cash_usd=snap["cashUsd"],
                            portfolio_usd=snap["portfolioUsd"],
                            realized_pnl_usd=snap["realizedPnlUsd"],
                            wins=snap["wins"], losses=snap["losses"],
                            open_positions=snap["openCount"] + snap["pendingCount"],
                            env=kalshi_auth.get_env(),
                        )
                        if STATE.active_run_id:
                            db.heartbeat_bot_run(
                                conn, STATE.active_run_id,
                                cash_usd=snap["cashUsd"],
                                portfolio_usd=snap["portfolioUsd"],
                                lifetime_trades=snap["totalOpened"],
                                lifetime_wins=snap["wins"],
                                lifetime_losses=snap["losses"],
                            )
                await emit_event("account:update", snap)
                last_account_emit = now
        except Exception as e:
            logger.debug(f"account snapshot error: {e}")

        try:
            push_iv = float(cfg.get("stats_push_interval", 3600) or 3600)
            if (
                cfg.get("enable_discord")
                and cfg.get("stats_webhook_url")
                and now - last_stats_push >= push_iv
            ):
                snap_for_stats = await _build_account_snapshot()
                try:
                    if not snap_for_stats.get("balanceKnown"):
                        raise RuntimeError("balance not read yet")
                    await webhook.send_stats(
                        cfg.get("stats_webhook_url", ""),
                        snap_for_stats,
                        kalshi_auth.get_env(),
                    )
                    logger.info(
                        f"stats webhook fired (next in "
                        f"{int(push_iv // 60)}m)"
                    )
                except Exception as e:
                    logger.debug(f"stats webhook send failed: {e}")
                last_stats_push = now
        except Exception as e:
            logger.debug(f"stats webhook scheduler error: {e}")


        await asyncio.sleep(1)


async def _crypto15m_loop() -> None:
    """Dedicated 15m-executor loop, ISOLATED from the main scanner/trader loop.

    The main loop is one long serial iteration (market sync, scans, order poll,
    reconcile, resolution) — a Kalshi 5xx storm or a slow 10-page market sync
    stalled the 15m tick 5-80s, exactly the windows where a stop-loss needed
    its 4s cadence to protect capital in a fast drop. run_tick manages its own
    concurrency through DB state, and only this task calls it, so ticks never
    overlap. A WS fill wakes the next tick within ~0.5s (STATE.ws_c15_pending)
    so a just-filled entry arms its stop-loss/TP without waiting out the poll."""
    last_tick = 0.0
    while not (_loop_stop and _loop_stop.is_set()):
        try:
            cfg = STATE.cfg
            now = asyncio.get_event_loop().time()
            want_spot_ws = bool(cfg.get("crypto15m_spot_ws", True))
            kalshi_ws.set_cf_enabled(want_spot_ws)
            if want_spot_ws and not spot_ws.is_running():
                spot_ws.start()
            elif not want_spot_ws and spot_ws.is_running():
                await spot_ws.stop()
            due = (
                not STATE.paused
                and (
                    now - last_tick >= float(cfg.get("crypto15m_poll_sec", 4))
                    or (STATE.ws_c15_pending and now - last_tick >= 1)
                )
            )
            if due:
                STATE.ws_c15_pending = False
                changed = await crypto15m_trader.run_tick(
                    cfg, authed=STATE.auth_ok, session_start=STATE.started_at
                )
                last_tick = asyncio.get_event_loop().time()
                if changed:
                    _fire_and_forget(trader.refresh_balance(cfg, force=True))
        except Exception as e:
            logger.error(f"crypto15m tick error: {e}", exc_info=True)
        await asyncio.sleep(0.5)


async def _script_loop() -> None:
    """User-script executor (Scripts tab), in ITS OWN task for the same
    reason the 15m loop is isolated from the main loop: script hooks can
    legally run near their per-call wall budgets, and when they ticked
    serially inside _crypto15m_loop a heavy script delayed the 15m stop-loss
    cadence that exists to protect capital in fast drops. Positions scripts
    open are still managed to settlement by the crypto15m pass, so a slow or
    disabled script never strands an open bet. Script errors auto-disable
    the script — they can never take this loop down."""
    last_script = 0.0
    while not (_loop_stop and _loop_stop.is_set()):
        try:
            if (
                not STATE.paused
                and STATE.cfg.get("scripts_live_enabled")
                and asyncio.get_event_loop().time() - last_script
                >= float(STATE.cfg.get("script_poll_sec", 5))
            ):
                await script_engine.run_tick(STATE.cfg, authed=STATE.auth_ok)
                last_script = asyncio.get_event_loop().time()
        except Exception as e:
            logger.error(f"script engine tick error: {e}", exc_info=True)
        await asyncio.sleep(0.5)


def _watchdog_restart(name: str, factory):
    """Done-callback for the core loop tasks: if one DIES (a loop-killing
    exception like MemoryError escaping the per-section try/excepts), the
    process previously kept serving RPCs — balances refreshed, the UI stayed
    green — while all scanning/trading/exits were silently dead. Log loud,
    tell the renderer, and restart the loop after a short breather."""
    def _cb(task: asyncio.Task) -> None:
        if task.cancelled() or (_loop_stop and _loop_stop.is_set()):
            return
        exc = task.exception()
        logger.critical(
            f"{name} DIED unexpectedly ({type(exc).__name__ if exc else 'no exception'}: "
            f"{exc}) — restarting in 5s", exc_info=exc,
        )

        async def _restart():
            await asyncio.sleep(5)
            if _loop_stop and _loop_stop.is_set():
                return
            await emit_event("backend:degraded", {
                "component": name, "error": str(exc)[:200] if exc else "",
                "action": "restarted",
            })
            factory()
        _fire_and_forget(_restart())
    return _cb


def _spawn_main_loop() -> None:
    global _loop_task
    try:
        import logscrub
        logscrub.refresh_known_secrets()
    except Exception:
        pass
    _loop_task = asyncio.create_task(_scanner_and_trader_loop())
    _loop_task.add_done_callback(_watchdog_restart("trader loop", _spawn_main_loop))


def _spawn_c15_loop() -> None:
    global _c15_task
    _c15_task = asyncio.create_task(_crypto15m_loop())
    _c15_task.add_done_callback(_watchdog_restart("crypto15m loop", _spawn_c15_loop))


def _spawn_script_loop() -> None:
    global _script_task
    _script_task = asyncio.create_task(_script_loop())
    _script_task.add_done_callback(_watchdog_restart("script loop", _spawn_script_loop))


async def _start_loop() -> None:
    global _loop_task, _c15_task, _loop_stop
    if _loop_task and not _loop_task.done():
        return
    _loop_stop = asyncio.Event()
    _spawn_main_loop()
    _spawn_c15_loop()
    _spawn_script_loop()


async def _stop_loop() -> None:
    global _loop_task, _c15_task, _loop_stop
    if _loop_stop:
        _loop_stop.set()
    for task in (_loop_task, _c15_task, _script_task):
        if task:
            try:
                await asyncio.wait_for(task, timeout=5)
            except Exception:
                pass




async def _h_ping(_p: dict) -> dict:
    return {"pong": True, "ts": datetime.now(timezone.utc).isoformat()}


async def _h_setConfig(p: dict) -> dict:
    cfg = merge_with_defaults(p.get("config") or {})
    STATE.cfg = cfg
    logger.info(
        f"setConfig applied: enable_trading={cfg.get('enable_trading')} "
        f"trade_whales={cfg.get('trade_whales')} "
        f"trade_momentum={cfg.get('trade_momentum')} "
        f"max_open={cfg.get('max_open_positions')} "
        f"max_daily="
        f"{'∞' if cfg.get('unlimited_daily_new_positions') else cfg.get('max_daily_new_positions')} "
        f"stop_loss={cfg.get('stop_loss_on_day')} "
        f"account={cfg.get('account_mode')}"
    )
    paper_exchange.set_bankroll(cfg.get("paper_bankroll_usd"))
    new_env = scope_env(cfg)
    verify_auth = False
    async with kalshi_auth.ENV_LOCK:
        prev_env = kalshi_auth.get_env()
        kalshi_auth.set_env(new_env)
        env_changed = new_env != prev_env
        if env_changed:
            kalshi_auth.reset_credential_cache()
            STATE.auth_ok = new_env == kalshi_auth.PAPER
            if new_env != kalshi_auth.PAPER and kalshi_auth.credentials_present():
                try:
                    kalshi_auth.prime_credentials(sync_time=False)
                    verify_auth = True
                except Exception as e:
                    logger.warning(f"env-switch auth failed: {e}")

    if env_changed and verify_auth:
        try:
            await asyncio.to_thread(kalshi_auth.sync_server_time, True)
            bal = await kalshi_api.get_balance(pin_env=new_env)
            int(bal.get("balance", 0))
            ok = True
        except Exception as e:
            logger.warning(f"env-switch auth failed: {e}")
            ok = False
        if kalshi_auth.get_env() == new_env:
            STATE.auth_ok = ok

    if env_changed:
        await emit_event("backend:authChanged", {"authOk": STATE.auth_ok})

        try:
            if STATE.active_run_id:
                with db.get_db() as conn:
                    db.end_bot_run(conn, STATE.active_run_id)
                STATE.active_run_id = 0
            if STATE.auth_ok:
                cents, _ = await trader.refresh_balance(STATE.cfg, force=True)
                await _start_run_if_balance_known(new_env, cents)
        except Exception as e:
            logger.warning(f"could not roll bot_run on env switch: {e}")

    try:
        await _sync_remote_bots()
    except Exception as e:
        logger.warning(f"could not sync remote bots after config change: {e}")
    try:
        _prune_deleted_agent_tokens(p.get("config"),
                                    prune=p.get("pruneAgentTokens") is True)
    except Exception as e:
        logger.warning(f"could not remove deleted agents' tokens: {type(e).__name__}")
    try:
        await _sync_mcp()
    except Exception as e:
        logger.warning(f"could not sync MCP server after config change: {e}")
    return {"ok": True}


async def _h_setCredentials(p: dict) -> dict:
    p = p or {}
    api_key = p.get("apiKey", "")
    rsa_pem = p.get("rsaPem", "")
    if p.get("env") not in (None, "production"):
        raise ValueError("Kalshi keys are saved for production only")
    kalshi_auth.save_credentials(api_key, rsa_pem)
    try:
        import logscrub
        logscrub.refresh_known_secrets()
    except Exception:
        pass
    status = kalshi_auth.credentials_status_all()
    await emit_event("credentials:changed", status)
    return status


async def _h_clearCredentials(p: dict) -> dict:
    kalshi_auth.clear_credentials()
    if not kalshi_auth.is_paper():
        STATE.auth_ok = False
        await emit_event("backend:authChanged", {"authOk": False})
    status = kalshi_auth.credentials_status_all()
    await emit_event("credentials:changed", status)
    return status


async def _h_credentialStatus(_p: dict) -> dict:
    return kalshi_auth.credentials_status_all()


async def _h_testCredentials(p: dict) -> dict:
    """One signed balance read with the saved key, on the user's click.

    Works in Paper too — checking the key is the step before going live — and
    never flips the global env to do it (kalshi_api.verify_saved_key signs
    with the key pair directly), so no engine sees "production" mid-test."""
    if not kalshi_auth.credentials_present():
        raise RuntimeError("Kalshi credentials not set")
    bal = await kalshi_api.verify_saved_key()
    cents = int(bal.get("total_balance_cents", bal.get("balance", 0)))
    if not kalshi_auth.is_paper() and not STATE.auth_ok:
        async with kalshi_auth.ENV_LOCK:
            kalshi_auth.reset_credential_cache()
            try:
                kalshi_auth.prime_credentials(sync_time=False)
            except Exception:
                pass
        STATE.auth_ok = True
        await emit_event("backend:authChanged", {"authOk": True})
    return {"env": "production", "balanceUsd": cents / 100.0}


async def _h_verifyCredentials(p: dict) -> dict:
    """testCredentials, but a failure is an ANSWER rather than an exception:
    {ok: False, code, title, fix}, from kalshi_key_check.

    Runs only on the user's click (the setup wizard's save, or Test on the API
    Keys page) — a signed read is account traffic."""
    try:
        res = await _h_testCredentials({})
        return {"ok": True, **res}
    except Exception as e:
        d = kalshi_key_check.diagnose(e)
        try:
            import logscrub
            d = {k: (logscrub.scrub(v) if isinstance(v, str) else v) for k, v in d.items()}
        except Exception:
            pass
        logger.info(f"credential check failed: {d['code']}")
        return {"ok": False, "env": "production", **d}


async def _h_account(_p: dict) -> dict:
    return await _build_account_snapshot()


async def _h_pnlSeries(p: dict) -> list:
    hours = int((p or {}).get("sinceHours", 168))
    env = kalshi_auth.get_env()
    with db.get_db() as conn:
        rows = db.get_pnl_snapshots(conn, since_hours=hours, env=env)
    return [
        {
            "at": _iso_utc(r["at"]),
            "cashUsd": float(r["cash_usd"] or 0),
            "portfolioUsd": float(r["portfolio_usd"] or 0),
            "totalUsd": float(r["total_usd"] or 0),
            "realizedPnlUsd": float(r["realized_pnl_usd"] or 0),
            "openPositions": int(r["open_positions"] or 0),
        }
        for r in rows
    ]


_POSITION_ENVS = (db.PAPER_ENV, kalshi_auth.PRODUCTION, db.RETIRED_ENV)


async def _h_positions(p: dict) -> list:
    f = p or {}
    status = f.get("status")
    resolved = f.get("resolved")
    src = f.get("signalSource")
    limit = int(f.get("limit") or 500)
    env = str(f.get("env") or "").strip().lower() or kalshi_auth.get_env()
    if env != "all" and env not in _POSITION_ENVS:
        raise ValueError("env must be paper, production, demo or all")

    sql = "SELECT * FROM bot_positions WHERE 1=1"
    args: list = []
    if env != "all":
        sql += " AND kalshi_env = ?"
        args.append(env)
    if status:
        placeholders = ",".join("?" for _ in status)
        sql += f" AND status IN ({placeholders})"
        args.extend(status)
    if resolved is not None:
        sql += " AND resolved = ?"
        args.append(1 if resolved else 0)
    if src:
        sql += " AND signal_source = ?"
        args.append(src)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)

    with db.get_db() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_position_row_to_js(dict(r)) for r in rows]


async def _h_signals(p: dict) -> list:
    f = p or {}
    src = f.get("source")
    min_conf = float(f.get("minConfidence") or 0)
    limit = int(f.get("limit") or 200)

    out: list[dict] = []
    env = kalshi_auth.get_env()
    with db.get_db() as conn:
        if src in (None, "whale"):
            rows = conn.execute(
                """SELECT * FROM whale_trades
                   WHERE confidence >= ?
                   ORDER BY created_at DESC LIMIT ?""",
                (min_conf, limit),
            ).fetchall()
            seen = db.already_traded_signal_ids(conn, "whale", env)
            for r in rows:
                d = dict(r)
                out.append(_signal_row_to_js(d, "whale", int(d["id"]) in seen))
        if src in (None, "momentum"):
            rows = conn.execute(
                """SELECT * FROM alerts
                   WHERE confidence >= ?
                   ORDER BY created_at DESC LIMIT ?""",
                (min_conf, limit),
            ).fetchall()
            seen = db.already_traded_signal_ids(conn, "momentum", env)
            for r in rows:
                d = dict(r)
                out.append(_signal_row_to_js(d, "momentum", int(d["id"]) in seen))
    out.sort(key=lambda s: s["createdAt"], reverse=True)
    return out[:limit]


async def _h_scannerStats(_p: dict) -> dict:
    with db.get_db() as conn:
        markets = conn.execute(
            "SELECT COUNT(*) FROM markets WHERE status IN ('active','open')"
        ).fetchone()[0]
        wt = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN discord_sent=1 THEN 1 ELSE 0 END) AS sent,
                      SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) AS resolved,
                      SUM(CASE WHEN outcome_correct=1 THEN 1 ELSE 0 END) AS wins
               FROM whale_trades"""
        ).fetchone()
        al = conn.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN discord_sent=1 THEN 1 ELSE 0 END) AS sent,
                      SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) AS resolved,
                      SUM(CASE WHEN outcome_correct=1 THEN 1 ELSE 0 END) AS wins
               FROM alerts"""
        ).fetchone()

    def wr(d) -> dict:
        total = int(d["total"] or 0)
        resolved = int(d["resolved"] or 0)
        wins = int(d["wins"] or 0)
        return {
            "total": total,
            "sent": int(d["sent"] or 0),
            "resolved": resolved,
            "winRate": (wins / resolved * 100.0) if resolved else 0.0,
        }

    return {
        "whales": wr(wt),
        "momentum": wr(al),
        "marketsTracked": int(markets or 0),
        "lastWhaleScanAt": STATE.last_whale_scan_at,
        "lastMomentumScanAt": STATE.last_momentum_scan_at,
        "lastTradeScanAt": STATE.last_trade_scan_at,
    }


async def _h_cancelAllOpen(_p: dict) -> dict:
    if not STATE.auth_ok:
        raise RuntimeError("not authenticated")
    n = await trader.cancel_all_open()
    return {"canceled": n}


async def _h_flatten(_p: dict) -> dict:
    if not STATE.auth_ok:
        raise RuntimeError("not authenticated")
    canceled = await trader.cancel_all_open()
    return {"closed": canceled}


async def _h_runOnce(p: dict) -> dict:
    action = (p or {}).get("action")
    if action == "syncMarkets":
        cnt = await scanner.sync_markets(max_pages=10)
        return {"summary": f"Synced {cnt} markets"}
    if action == "pollOrders":
        upd = await trader.poll_open_orders(STATE.cfg)
        return {"summary": f"Polled, {len(upd)} updates"}
    if action == "resolveAll":
        rp = await trader.mark_resolved_positions(STATE.cfg)
        ra = await scanner.resolve_alerts_from_markets()
        rw = await scanner.resolve_whales_from_markets()
        return {"summary": f"Positions:{len(rp)} alerts:{ra} whales:{rw}"}
    if action == "reconcilePositions":
        s, changed = await trader.reconcile_positions_with_kalshi()
        for row in changed:
            await emit_event("position:update", _position_row_to_js(row))
        return {
            "summary": (
                f"Reconciled — rescued {s.get('rescued', 0)}, "
                f"resurrected {s.get('resurrected', 0)}, "
                f"imported {s.get('imported_unknowns', 0)}"
            ),
        }
    if action == "recomputePnl":
        s = await trader.recompute_pnl_from_kalshi()
        return {
            "summary": f"Re-resolved {s['recomputed']} of {s['cleared']} positions from Kalshi",
        }
    if action == "reconcileFills":
        s = await trader.reconcile_fills_from_kalshi()
        return {
            "summary": (
                f"Reconciled {s['fills_reconciled']} orders from Kalshi fills, "
                f"re-resolved {s['pnl_recomputed']} of {s['pnl_cleared']}"
            ),
        }
    if action == "auditPnl":
        s = await trader.audit_pnl(200)
        worst_lines = []
        for x in s.get("samples", [])[:8]:
            worst_lines.append(
                f"  {x['ticker']} {x['direction']}: stored ${x['stored_pnl']:+.2f} → fresh ${x['fresh_pnl']:+.2f} (Δ ${x['delta']:+.2f})"
            )
        msg = (
            f"Audited {s['checked']} resolved positions: {s['flagged']} flagged. "
            f"Sum stored=${s['sum_stored_pnl']:+.2f} vs fresh=${s['sum_recompute_pnl']:+.2f} "
            f"(Δ ${s['delta']:+.2f})"
        )
        if worst_lines:
            msg += "\n" + "\n".join(worst_lines)
        return {"summary": msg, "audit": s}
    raise ValueError(f"unknown action: {action}")


async def _h_pause(p: dict) -> dict:
    STATE.paused = bool((p or {}).get("paused", False))
    return {"paused": STATE.paused}


def _run_row_to_js(r: dict) -> dict:
    return {
        "id": int(r["id"]),
        "kalshiEnv": r.get("kalshi_env") or db.RETIRED_ENV,
        "startedAt": _iso_utc(r.get("started_at")) or "",
        "endedAt": _iso_utc(r.get("ended_at")),
        "startCashUsd": float(r.get("start_cash_usd") or 0),
        "startPortfolioUsd": float(r.get("start_portfolio_usd") or 0),
        "startTotalUsd": float(r.get("start_total_usd") or 0),
        "endCashUsd": (
            float(r["end_cash_usd"])
            if r.get("end_cash_usd") is not None else None
        ),
        "endPortfolioUsd": (
            float(r["end_portfolio_usd"])
            if r.get("end_portfolio_usd") is not None else None
        ),
        "endTotalUsd": (
            float(r["end_total_usd"])
            if r.get("end_total_usd") is not None else None
        ),
        "pnlUsd": float(r.get("pnl_usd") or 0),
        "tradesOpened": int(r.get("trades_opened") or 0),
        "tradesWon": int(r.get("trades_won") or 0),
        "tradesLost": int(r.get("trades_lost") or 0),
        "isActive": r.get("ended_at") is None,
    }


async def _h_botRuns(p: dict) -> dict:
    env = (p or {}).get("env")
    limit = int((p or {}).get("limit") or 100)
    with db.get_db() as conn:
        rows = db.get_recent_runs(conn, env=env, limit=limit)
        active = (
            db.get_active_run(conn, kalshi_auth.get_env())
            if STATE.active_run_id else None
        )
    return {
        "runs": [_run_row_to_js(r) for r in rows],
        "activeRunId": STATE.active_run_id,
        "activeRun": _run_row_to_js(active) if active else None,
    }


async def _h_shutdown(_p: dict) -> dict:
    asyncio.create_task(_shutdown())
    return {"shutting_down": True}


async def _h_factoryReset(_p: dict) -> dict:
    logger.warning("factory reset: STARTING — pausing trader loop")
    await _stop_loop()

    if STATE.active_run_id:
        try:
            with db.get_db() as conn:
                db.end_bot_run(conn, STATE.active_run_id)
        except Exception as e:
            logger.warning(f"factoryReset: end_bot_run: {e}")
        STATE.active_run_id = 0

    summary = await asyncio.to_thread(db.factory_reset)
    deleted_total = sum(
        v for k, v in summary.items()
        if not k.startswith("_") and isinstance(v, int) and v > 0
    )
    if summary.get("_errors"):
        logger.error(
            f"factory reset: PARTIAL — deleted {deleted_total} rows, "
            f"errors={summary['_errors']}"
        )
    else:
        logger.warning(
            f"factory reset: COMPLETE — deleted {deleted_total} rows "
            f"({summary})"
        )

    STATE.last_whale_scan_at = ""
    STATE.last_momentum_scan_at = ""
    STATE.last_trade_scan_at = ""

    if STATE.auth_ok:
        try:
            cents, _ = await trader.refresh_balance(STATE.cfg, force=True)
            await _start_run_if_balance_known(kalshi_auth.get_env(), cents)
        except Exception as e:
            logger.warning(f"factoryReset: post-reset run start: {e}")

    await emit_event("data:reset", {"summary": summary})
    snap = await _build_account_snapshot()
    await emit_event("account:update", snap)

    await _start_loop()
    logger.info("factory reset: trader loop resumed")

    return {"ok": True, "deleted": summary}


async def _h_crypto15m(_p: dict) -> dict:
    return await crypto15m.snapshot(STATE.cfg)


async def _h_crypto15mStatus(_p: dict) -> dict:
    return await crypto15m_trader.status(
        STATE.cfg, authed=STATE.auth_ok, session_start=STATE.started_at
    )


async def _h_kalshiMarketUrl(p: dict) -> dict:
    url = await kalshi_api.web_market_url(
        event_ticker=str(p.get("eventTicker") or ""),
        ticker=str(p.get("ticker") or ""),
        env=str(p.get("env") or "production"),
    )
    return {"url": url}



async def _h_trading_status(p: dict) -> dict:
    """Ordered gate checklist for both engines — the "why isn't it trading"
    panel. Each row: {id, label, state: ok|blocked|off, reason}. The first
    blocked row is the answer."""
    cfg = STATE.cfg
    env = trader.get_env()
    main: list[dict] = []

    def gate(gid: str, label: str, ok: bool, reason: str = "", off: bool = False) -> None:
        main.append({
            "id": gid, "label": label,
            "state": "off" if off else ("ok" if ok else "blocked"),
            "reason": reason if not ok else "",
        })

    gate("paused", "Engine not paused", not STATE.paused, "paused by user")
    if env == db.PAPER_ENV:
        gate("auth", "Paper account", True)
    else:
        gate("auth", "Kalshi auth", bool(STATE.auth_ok), "auth failed — check API keys")
    enabled = bool(cfg.get("enable_trading"))
    gate("master", "Trading enabled", enabled, "master switch is OFF", off=not enabled)
    try:
        blocked, why = trader._is_blocked_by_daily_risk(cfg, env)
        gate("dailyRisk", "Daily stop/take-profit", not blocked, why or "")
    except Exception:
        gate("dailyRisk", "Daily stop/take-profit", True)
    try:
        hblocked, hwhy = trader._is_blocked_by_trading_hours(cfg)
        gate("hours", "Trading hours", not hblocked, hwhy or "")
    except Exception:
        gate("hours", "Trading hours", True)
    lc = dict(getattr(trader, "last_cycle", {}) or {})
    if lc.get("skipReason"):
        gate("cycle", "Last scan cycle", False, str(lc.get("skipReason")))
    else:
        gate("cycle", "Last scan cycle", True)

    c15 = await crypto15m_trader.status(cfg, authed=STATE.auth_ok, session_start=STATE.started_at)
    return {
        "main": main,
        "mainFilterCounts": lc.get("filterCounts") or {},
        "mainCandidates": lc.get("candidates") or 0,
        "mainPlaced": lc.get("placed") or 0,
        "c15": {
            "enabled": c15.get("enabled"),
            "live": c15.get("live"),
            "authed": bool(STATE.auth_ok),
            "env": env,
            "blockReasons": c15.get("blockReasons") or {},
            "takeProfitHalted": c15.get("takeProfitHalted"),
        },
    }



async def _h_c15_backtest(p: dict) -> dict:
    """Replay the CURRENT (or supplied) 15m config over recorded ticks using
    the live entry gates. Read-heavy — run off the event loop."""
    import replay
    from config import merge_with_defaults as _merge
    cfg = dict(STATE.cfg or {})
    patch = (p or {}).get("config") or {}
    if isinstance(patch, dict):
        cfg.update(patch)
    cfg = _merge(cfg)
    since = int((p or {}).get("sinceDays") or 60)
    env = str((p or {}).get("env") or "production")
    return await asyncio.to_thread(replay.replay, cfg, env=env, since_days=since)



async def _h_main_backtest(p: dict) -> dict:
    """Replay recorded whale/momentum signals through the live should_trade
    gates with follower economics."""
    import replay
    from config import merge_with_defaults as _merge
    cfg = dict(STATE.cfg or {})
    patch = (p or {}).get("config") or {}
    if isinstance(patch, dict):
        cfg.update(patch)
    cfg = _merge(cfg)
    since = int((p or {}).get("sinceDays") or 60)
    return await asyncio.to_thread(replay.replay_main, cfg, since_days=since)



async def _h_collection_stats(p: dict) -> dict:
    """Inventory of the passively collected research data — what the Backtest
    page's "view data" area shows. Counts + spans + a recent sample per
    stream, all cheap indexed queries."""
    def _q() -> dict:
        with db.get_db() as conn:
            c15 = conn.execute(
                """SELECT COUNT(*) n, SUM(resolved) r, MIN(observed_at) a,
                          MAX(observed_at) b
                   FROM crypto15m_signals WHERE kalshi_env='production'"""
            ).fetchone()
            ticks = conn.execute(
                "SELECT COUNT(*) FROM crypto15m_ticks WHERE kalshi_env='production'"
            ).fetchone()[0]
            recent_c15 = conn.execute(
                """SELECT ticker, asset, favorite, favorite_price, up_won,
                          resolved, close_time
                   FROM crypto15m_signals WHERE kalshi_env='production'
                   ORDER BY id DESC LIMIT 12"""
            ).fetchall()
            wh = conn.execute(
                """SELECT COUNT(*) n, SUM(resolved) r, MIN(created_at) a,
                          MAX(created_at) b FROM whale_trades"""
            ).fetchone()
            al = conn.execute(
                """SELECT COUNT(*) n, SUM(resolved) r, MIN(created_at) a,
                          MAX(created_at) b FROM alerts"""
            ).fetchone()
            cats = conn.execute(
                """SELECT category, COUNT(*) n FROM whale_trades
                   GROUP BY category ORDER BY n DESC LIMIT 6"""
            ).fetchall()
            recent_main = conn.execute(
                """SELECT ticker, category, taker_side, price, dollar_value,
                          outcome_correct, resolved, created_at
                   FROM whale_trades ORDER BY id DESC LIMIT 12"""
            ).fetchall()
        return {
            "c15": {
                "windows": int(c15["n"] or 0),
                "resolved": int(c15["r"] or 0),
                "ticks": int(ticks or 0),
                "firstAt": c15["a"], "lastAt": c15["b"],
                "recent": [dict(r) for r in recent_c15],
            },
            "main": {
                "whales": int(wh["n"] or 0), "whalesResolved": int(wh["r"] or 0),
                "alerts": int(al["n"] or 0), "alertsResolved": int(al["r"] or 0),
                "firstAt": wh["a"] or al["a"], "lastAt": wh["b"] or al["b"],
                "topCategories": [dict(r) for r in cats],
                "recent": [dict(r) for r in recent_main],
            },
            "collecting": {
                "c15": bool((STATE.cfg or {}).get("crypto15m_record_signals", True)),
                "main": True,
            },
        }
    return await asyncio.to_thread(_q)



async def _h_c15_history(p: dict) -> dict:
    limit = min(500, int((p or {}).get("limit") or 200))
    include_paper = bool((p or {}).get("includePaper"))
    env = trader.get_env()
    def _q():
        with db.get_db() as conn:
            rows = db.recent_crypto15m_resolved(conn, env, limit=limit, include_paper=include_paper)
        return {"rows": [crypto15m_trader._pos_to_js(r) for r in rows]}
    return await asyncio.to_thread(_q)


async def _h_turbine_library(p: dict) -> dict:
    """The imported Turbine strategy library joined with the last saved
    backtest results (net-of-fee edge on OUR data). Each entry carries the
    crypto15m config slice so the UI can drop it straight into a Multi-Run
    runner. Optionally re-runs the backtest when p.rerun is set."""
    import json as _json
    import os as _os

    def _q():
        import turbine_import
        imported, skipped = turbine_import.import_all()
        results: dict = {}
        rpath = _os.path.join(_os.path.dirname(__file__), "data", "research",
                              "turbine_backtest_results.json")
        if (p or {}).get("rerun"):
            try:
                import turbine_backtest
                for r in turbine_backtest.run(env=DATA_ENV, since_days=int((p or {}).get("days") or 90)):
                    results[r["name"]] = r
            except Exception as e:
                logger.warning(f"turbine rerun failed: {e}")
        if not results:
            try:
                with open(rpath, "r", encoding="utf-8") as f:
                    for r in (_json.load(f) or []):
                        results[r["name"]] = r
            except Exception:
                pass
        out = []
        for it in imported:
            r = results.get(it["name"]) or {}
            out.append({
                "name": it["name"], "asset": it["asset"], "archetype": it["archetype"],
                "turbine": it["turbine"], "config": it["config"],
                "backtest": ({
                    "netCentsPerContract": r.get("netCentsPerContract"),
                    "t": r.get("t"), "n": r.get("n"), "winRate": r.get("winRate"),
                    "rankScore": r.get("rankScore"),
                } if r else None),
            })
        out.sort(key=lambda x: (str(x["name"]).startswith("★"),
                                (x["backtest"] or {}).get("rankScore", -999)), reverse=True)
        return {"strategies": out, "skipped": [s["name"] for s in skipped]}
    return await asyncio.to_thread(_q)


_PROC_POOL: "_cf.ProcessPoolExecutor | None" = None


def _proc_init() -> None:
    import os as _os
    import sys as _sys
    d = getattr(_sys, "_MEIPASS", _os.path.dirname(_os.path.abspath(__file__)))
    if d not in _sys.path:
        _sys.path.insert(0, d)
    try:
        _os.chdir(d)
    except Exception:
        pass


def _get_proc_pool() -> "_cf.ProcessPoolExecutor":
    global _PROC_POOL
    if _PROC_POOL is None:
        _PROC_POOL = _cf.ProcessPoolExecutor(
            max_workers=1, mp_context=_mp.get_context("spawn"), initializer=_proc_init,
        )
    return _PROC_POOL


async def _run_heavy(fn, params: dict):
    """Run a picklable module-level worker in the process pool; on any pool
    failure, reset it and fall back to a worker thread (never blocks the loop
    beyond the work itself)."""
    global _PROC_POOL
    loop = asyncio.get_event_loop()
    try:
        return await loop.run_in_executor(_get_proc_pool(), fn, params)
    except Exception as e:
        logger.warning(f"[heavy] {getattr(fn, '__name__', fn)} process pool failed ({e}); using thread")
        try:
            if _PROC_POOL is not None:
                _PROC_POOL.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        _PROC_POOL = None
        return await asyncio.to_thread(fn, params)


async def _h_coin_optimize(p: dict) -> dict:
    """Sweep the strategy library across hour-buckets for one coin and assemble
    a best-24h schedule (walk-forward holdout). Heavy CPU → runs in a subprocess
    off the event loop (see _run_heavy)."""
    import coin_optimizer
    return await _run_heavy(coin_optimizer.run_optimize, {**(p or {}), "env": DATA_ENV})


async def _h_export_research(p: dict) -> dict:
    """Dump the collected research data as CSVs the user can analyze anywhere.
    Written under data/exports/<stamp>/; the renderer reveals the folder."""
    import csv
    def _dump() -> dict:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        out_dir = os.path.join(os.path.dirname(str(db.db_path())), "exports", stamp)
        os.makedirs(out_dir, exist_ok=True)
        tables = ["crypto15m_signals", "crypto15m_ticks", "crypto15m_positions",
                  "whale_trades", "alerts"]
        files = []
        with db.get_db() as conn:
            for t in tables:
                rows = conn.execute(f"SELECT * FROM {t}").fetchall()
                path = os.path.join(out_dir, f"{t}.csv")
                with open(path, "w", newline="", encoding="utf-8") as f:
                    if rows:
                        w = csv.DictWriter(f, fieldnames=list(dict(rows[0]).keys()))
                        w.writeheader()
                        for r in rows:
                            w.writerow(dict(r))
                    else:
                        f.write("")
                files.append(path)
        return {"dir": out_dir, "files": files}
    return await asyncio.to_thread(_dump)


async def _h_edge_health(p: dict) -> dict:
    """Rolling per-strategy forward measurement (Edge Health panel)."""
    return await asyncio.to_thread(crypto15m_trader.edge_health, trader.get_env())


async def _h_perps_status(p: dict) -> dict:
    """Perps page status: the farmer (the public one-time-reward feature) and
    its wallet. The recorder/strategy research program was removed 2026-07-16
    (every backtested mechanism dead; re-check triggers cold)."""
    cfg = STATE.cfg or {}
    return {
        "farmer": await asyncio.to_thread(perps_farmer.status, cfg),
        "wallet": await perps_farmer.wallet(kalshi_auth.get_env()),
    }


async def _h_perps_farm_flatten(p: dict) -> dict:
    return await perps_farmer.flatten(STATE.cfg or {})




def _script_row_js(r: dict, stats: dict | None = None) -> dict:
    return {
        "id": r.get("id"), "name": r.get("name"),
        "description": r.get("description") or "",
        "code": r.get("code") or "",
        "enabled": bool(r.get("enabled")),
        "trusted": bool(r.get("trusted")),
        "notes": r.get("notes") or "",
        "lastError": r.get("last_error"),
        "lastErrorAt": _iso_utc(r.get("last_error_at")),
        "createdAt": _iso_utc(r.get("created_at")),
        "updatedAt": _iso_utc(r.get("updated_at")),
        "stats": (stats or {}).get(str(r.get("id"))) or None,
    }


async def _h_scripts_list(_p: dict) -> dict:
    env = kalshi_auth.get_env()
    with db.get_db() as conn:
        rows = db.list_user_scripts(conn)
        stats = db.script_live_stats(conn, env)
    return {"scripts": [_script_row_js(r, stats) for r in rows]}


def _script_warnings(code: str) -> list[str]:
    import replay
    missing = sorted(set(script_sandbox.find_ctx_fields(code)) - replay._DERIVABLE)
    warnings = []
    if missing:
        warnings.append(
            "Reads ctx fields that are LIVE-ONLY (None during backtests): "
            + ", ".join(missing))
    return warnings


async def _h_script_save(p: dict) -> dict:
    """Create or update a script. Validation runs in the script's declared
    trust mode; an invalid script still SAVES (so work isn't lost) but comes
    back with the errors and is force-disabled."""
    sid = str(p.get("id") or "").strip() or os.urandom(8).hex()
    code = str(p.get("code") or "")
    meta = script_sandbox.parse_header(code)
    name = str(p.get("name") or "").strip() or meta.get("name") or "Untitled script"
    desc = str(p.get("description") or "").strip() or meta.get("description") or ""
    with db.get_db() as conn:
        existing = db.get_user_script(conn, sid)
        trusted = bool(existing.get("trusted")) if existing else False
        errors = script_sandbox.validate(code, trusted=trusted)
        db.upsert_user_script(conn, {
            "id": sid, "name": name, "description": desc, "code": code,
            "notes": str(p.get("notes") or ""),
        })
        if errors:
            db.update_user_script(conn, sid, enabled=0,
                                  last_error="; ".join(errors[:3])[:500])
        else:
            db.update_user_script(conn, sid, last_error=None)
        row = db.get_user_script(conn, sid)
    return {"script": _script_row_js(row or {}), "errors": errors,
            "warnings": _script_warnings(code)}


async def _h_script_delete(p: dict) -> dict:
    with db.get_db() as conn:
        db.delete_user_script(conn, str(p.get("id") or ""))
    return {"ok": True}


async def _h_script_set_enabled(p: dict) -> dict:
    sid = str(p.get("id") or "")
    enabled = bool(p.get("enabled"))
    with db.get_db() as conn:
        row = db.get_user_script(conn, sid)
        if not row:
            raise ValueError("script not found")
        if enabled:
            errors = script_sandbox.validate(
                str(row.get("code") or ""), trusted=bool(row.get("trusted")))
            if errors:
                raise ValueError("script does not validate: " + errors[0])
            db.update_user_script(conn, sid, enabled=1, last_error=None)
        else:
            db.update_user_script(conn, sid, enabled=0)
        row = db.get_user_script(conn, sid)
    return {"script": _script_row_js(row or {})}


async def _h_script_set_trusted(p: dict) -> dict:
    """Flip the trusted (full-Python) flag. The renderer shows the scary
    consent modal BEFORE calling this; flipping re-validates in the new mode
    and always drops back to disabled so the user consciously re-arms."""
    sid = str(p.get("id") or "")
    trusted = bool(p.get("trusted"))
    with db.get_db() as conn:
        row = db.get_user_script(conn, sid)
        if not row:
            raise ValueError("script not found")
        db.update_user_script(conn, sid, trusted=1 if trusted else 0, enabled=0)
        row = db.get_user_script(conn, sid)
    return {"script": _script_row_js(row or {})}


async def _h_script_validate(p: dict) -> dict:
    """Validate code (editor button + the AI-output import path). Returns
    parsed metadata so the import flow can prefill name/description."""
    code = str(p.get("code") or "")
    trusted = bool(p.get("trusted"))
    errors = script_sandbox.validate(code, trusted=trusted)
    meta = script_sandbox.parse_header(code)
    return {
        "ok": not errors, "errors": errors,
        "warnings": _script_warnings(code),
        "name": meta.get("name") or "", "description": meta.get("description") or "",
        "hasHeader": bool(meta.get("version")),
        "ctxFields": script_sandbox.find_ctx_fields(code),
    }


async def _h_script_backtest(p: dict) -> dict:
    """Backtest a script (by id, or raw code from the editor) over the
    recorded tick corpus. Never places orders — script_backtest is
    structurally order-free."""
    import script_backtest
    cfg = dict(STATE.cfg or {})
    patch = (p or {}).get("config") or {}
    if isinstance(patch, dict):
        cfg.update(patch)
    cfg = merge_with_defaults(cfg)
    since = int((p or {}).get("sinceDays") or 60)
    env = DATA_ENV
    code = p.get("code")
    trusted = False
    if not code:
        with db.get_db() as conn:
            row = db.get_user_script(conn, str(p.get("id") or ""))
        if not row:
            raise ValueError("script not found")
        code = row.get("code") or ""
        trusted = bool(row.get("trusted"))
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                script_backtest.run, cfg, str(code),
                trusted=trusted, env=env, since_days=since,
            ),
            timeout=script_backtest.MAX_RUN_SECS + 30,
        )
    except asyncio.TimeoutError:
        raise ValueError(
            f"backtest exceeded {script_backtest.MAX_RUN_SECS + 30:.0f}s — "
            "the script likely contains an unbounded operation")


async def _h_script_context_pack(_p: dict) -> dict:
    import script_docs
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    text = await asyncio.to_thread(script_docs.build_context_pack, cfg, DATA_ENV)
    return {"text": text}


async def _h_script_api_docs(_p: dict) -> dict:
    """Structured script-API reference for the in-app docs panel. Rendered
    FROM the live modules (same sources as the context pack) so the panel can
    never drift from what the sandbox/engine/backtester actually do."""
    import replay
    import script_docs
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    return {
        "contract": script_docs.CONTRACT_DOC,
        "fields": [
            {"name": n, "doc": d, "backtestable": n in replay._DERIVABLE}
            for n, d in script_docs.FIELD_DOCS.items()
        ],
        "builtins": sorted(
            k for k in script_sandbox.SAFE_BUILTINS
            if k not in ("True", "False", "None")
        ),
        "rails": {
            "maxEntryCents": int(cfg.get("script_max_entry_cents") or 97),
            "maxContracts": int(cfg.get("script_max_contracts") or 20),
            "maxOpen": int(cfg.get("script_max_open") or 2),
            "dailyLossUsd": float(cfg.get("script_daily_loss_usd") or 25.0),
            "defaultOrderSize": int(cfg.get("crypto15m_order_size") or 1),
        },
        "examples": [
            {"name": "Late Favorite Follow", "code": script_docs.EXAMPLE_SIMPLE},
            {"name": "Momentum Confirm (stateful)", "code": script_docs.EXAMPLE_STATEFUL},
            {"name": "Trailing Exit (manage hook)", "code": script_docs.EXAMPLE_MANAGE},
            {"name": "Night Shift (supervisor)", "code": script_docs.EXAMPLE_SUPERVISOR},
        ],
    }




async def _h_terminal_discover(p: dict) -> dict:
    return await terminal.discover(
        str((p or {}).get("column") or "trending"),
        limit=int((p or {}).get("limit") or 60),
        refresh=bool((p or {}).get("refresh")),
        watchlist=[str(t) for t in ((p or {}).get("watchlist") or []) if t],
        filters=(p or {}).get("filters") or None,
    )


async def _h_terminal_search(p: dict) -> dict:
    return await terminal.search(
        str((p or {}).get("query") or ""), limit=int((p or {}).get("limit") or 60),
    )


async def _h_terminal_market(p: dict) -> dict:
    return await terminal.market_detail(
        str((p or {}).get("ticker") or ""), authed=STATE.auth_ok,
    )


async def _h_terminal_book(p: dict) -> dict:
    return await terminal.book(str((p or {}).get("ticker") or ""))


async def _h_terminal_candles(p: dict) -> dict:
    return await terminal.candles(
        str((p or {}).get("ticker") or ""),
        interval_min=int((p or {}).get("intervalMin") or 1),
        lookback_min=int((p or {}).get("lookbackMin") or 240),
    )


async def _h_terminal_tape(p: dict) -> dict:
    return await terminal.tape(
        str((p or {}).get("ticker") or ""), limit=int((p or {}).get("limit") or 50),
    )


async def _h_terminal_portfolio(_p: dict) -> dict:
    return await terminal.portfolio(STATE.auth_ok)


async def _h_terminal_orders(p: dict) -> dict:
    return await terminal.resting_orders(
        STATE.auth_ok, ticker=str((p or {}).get("ticker") or ""),
    )


async def _h_terminal_history(p: dict) -> dict:
    return await asyncio.to_thread(
        terminal.manual_history, int((p or {}).get("limit") or 300),
    )


async def _h_terminal_rules(p: dict) -> dict:
    return await asyncio.to_thread(
        terminal.list_rules, int((p or {}).get("limit") or 300),
    )


async def _h_terminal_rule_create(p: dict) -> dict:
    ticker = str((p or {}).get("ticker") or "").strip().upper()
    market = None
    status = "unreachable"
    try:
        raw, status = await terminal._public_gate.run(
            kalshi_api.fetch_market_checked, ticker)
        market = terminal.market_row(raw) if raw else None
    except Exception as e:
        logger.debug(f"terminal rule: market read failed for {ticker}: {e}")
    return await asyncio.to_thread(
        terminal.create_rule, p or {}, market=market, market_status=status)


async def _h_terminal_rule_cancel(p: dict) -> dict:
    return await asyncio.to_thread(
        terminal.cancel_rule, int((p or {}).get("id") or 0),
    )


async def _h_terminal_micro(p: dict) -> dict:
    probe = (p or {}).get("probeCents")
    return await asyncio.to_thread(
        terminal.microstructure,
        str((p or {}).get("ticker") or ""),
        float(probe) if probe is not None else None,
    )




async def _remote_command(text: str, sender: str) -> str:
    """Every chat message that survives its transport's identity check lands
    here. Trading is gated on its own switch, separately from reading.

    Every command is logged, including the read-only ones. For a control
    surface that can spend money from a phone, "what did the phone ask for,
    and when" is exactly the record you want afterwards — and it is the only
    place that history exists, since the chat app's own history is on a device
    that may be the thing you are trying to explain."""
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    first = (text or "").strip().split()[:1]
    verb = (first[0] if first else "?")[:24]
    logger.info(f"[remote] {sender} -> {verb}")
    try:
        reply = await remote.handle(
            text, sender, cfg=cfg, authed=STATE.auth_ok,
            trading_enabled=bool(cfg.get("remote_trading_enabled")),
        )
    except Exception as e:
        logger.warning(f"[remote] {sender} {verb} FAILED: {e}")
        raise
    head = (reply or "").strip().splitlines()[:1]
    logger.info(f"[remote] {sender} {verb} ok — {(head[0] if head else '')[:80]}")
    return reply


def _remote_set_telegram_chat(chat_id: str) -> None:
    """Persist the chat id the pairing handshake bound, so a restart does not
    ask the user to pair again."""
    STATE.cfg["remote_telegram_chat_id"] = str(chat_id)
    asyncio.create_task(emit_event("remote:paired", {"chatId": str(chat_id)}))


async def _sync_remote_bots() -> None:
    """Start/stop the bots to match the config. Called on every config change
    and periodically, so flipping a switch in the app takes effect without a
    restart."""
    cfg = merge_with_defaults(dict(STATE.cfg or {}))

    want_d = bool(cfg.get("remote_discord_enabled"))
    token_d = kalshi_auth.read_secret("discord_bot_token") or ""
    uid = str(cfg.get("remote_discord_user_id") or "")
    if want_d and token_d and uid:
        live_d = bool(remote_discord.BOT.task and not remote_discord.BOT.task.done())
        stale_d = live_d and (
            remote_discord.BOT.user_id != uid or remote_discord.BOT.token != token_d)
        if stale_d:
            logger.info("[remote] discord identity/token changed — restarting bot")
            await remote_discord.BOT.stop()
        if stale_d or not live_d:
            remote_discord.BOT.start(token_d, uid, _remote_command)
    elif remote_discord.BOT.task:
        await remote_discord.BOT.stop()

    want_t = bool(cfg.get("remote_telegram_enabled"))
    token_t = kalshi_auth.read_secret("telegram_bot_token") or ""
    if want_t and token_t:
        if (remote_telegram.BOT.task and not remote_telegram.BOT.task.done()
                and remote_telegram.BOT.token != token_t):
            logger.info("[remote] telegram token changed — restarting bot")
            await remote_telegram.BOT.stop()
        if not (remote_telegram.BOT.task and not remote_telegram.BOT.task.done()):
            remote_telegram.BOT.start(
                token_t, str(cfg.get("remote_telegram_chat_id") or ""),
                _remote_command, remote.check_pair_code,
                _remote_set_telegram_chat)
    elif remote_telegram.BOT.task:
        await remote_telegram.BOT.stop()


async def _remote_push(text: str) -> None:
    """Send an alert to whichever bots are live. Best effort: a chat outage
    must never affect trading."""
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    if not cfg.get("remote_alerts_enabled"):
        return
    for bot in (remote_discord.BOT, remote_telegram.BOT):
        try:
            if bot.task and not bot.task.done():
                await bot.send(text)
        except Exception as e:
            logger.debug(f"remote push failed: {e}")


async def _rule_event(name: str, data: Any) -> None:
    """A standing instruction fired: tell the window AND the phone. The whole
    point of the remote is to hear about this when you are not at the desk."""
    await emit_event(name, data)
    try:
        await _remote_push(remote.format_rule_event(data or {}))
    except Exception as e:
        logger.debug(f"remote rule push failed: {e}")



async def _h_ai_status(_p: dict) -> dict:
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    return await asyncio.to_thread(ai_analyst.status, cfg)


async def _h_ai_set_key(p: dict) -> dict:
    provider = str((p or {}).get("provider") or "")
    if provider not in ai_analyst.SECRET_NAMES:
        raise ValueError("provider must be one of " + ", ".join(ai_analyst.SECRET_NAMES))
    key = str((p or {}).get("key") or "").strip()
    has = await asyncio.to_thread(ai_analyst.save_key, provider, key)
    logger.info(f"[ai] {provider} API key {'saved' if key else 'cleared'}")
    return {"ok": True, "provider": provider, "hasKey": has}


async def _h_ai_check_provider(p: dict) -> dict:
    """Settings' "Test connection". The renderer names a provider id; the
    host, the key and the endpoint are all chosen here. Free endpoints only
    (model listings), so pressing it never bills the user."""
    provider = str((p or {}).get("provider") or "").strip().lower()
    if provider not in ai_analyst.PROVIDERS:
        raise ValueError("unknown AI provider")
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    res = await asyncio.to_thread(ai_analyst.check_provider, provider, cfg)
    logger.info(f"[ai] connection check {provider}: {'ok' if res.get('ok') else 'failed'}")
    return res


async def _h_ai_analyze(p: dict) -> dict:
    ticker = str((p or {}).get("ticker") or "").strip()
    if not ticker:
        raise ValueError("ticker required")
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    detail = await terminal.market_detail(ticker, authed=STATE.auth_ok)
    try:
        analysis = await asyncio.to_thread(ai_analyst.analyze, detail, cfg)
    except ai_analyst.AiError as e:
        return {"ok": False, "error": str(e)}
    except Exception as e:
        logger.warning(f"[ai] analysis failed for {ticker}: {type(e).__name__}: {e}")
        return {"ok": False, "error": f"The analysis failed: {type(e).__name__}."}
    fair = analysis.get("fairValueCents")
    if fair is not None:
        try:
            fid = forecast_ledger.record(
                ticker=ticker, prob_yes=float(fair) / 100.0, source="panel",
                model=str(analysis.get("model") or ""),
                market=detail.get("market") or {},
                rationale=str(analysis.get("summary") or ""),
                env=DATA_ENV,
            )
            analysis["forecastId"] = fid
        except Exception as e:
            logger.warning(f"[ai] could not record forecast for {ticker}: {e}")
    return {"ok": True, "analysis": analysis}



async def _h_ai_scoreboard(_p: dict) -> dict:
    return await asyncio.to_thread(forecast_ledger.scoreboard)


async def _h_mcp_status(_p: dict) -> dict:
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    st = await asyncio.to_thread(mcp_server.status, cfg)
    mode = mcp_server.trade_mode(cfg)
    st["lossToday"] = None
    if mode != "off":
        try:
            st["lossToday"] = await mcp_server.day_loss(mode)
        except Exception as e:
            logger.debug(f"mcp loss-today read failed: {e}")
    return st


async def _h_mcp_seen(_p: dict) -> dict:
    """Which agent clients connected or called this session — memory only.
    Onboarding asks this instead of mcpStatus, which runs the agent day-loss
    check and so can fetch Kalshi marks when trade mode is on."""
    return mcp_server.seen()


async def _h_autopilot_status(_p: dict) -> dict:
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    st = await asyncio.to_thread(autopilot.status, cfg)
    st["runs"] = await asyncio.to_thread(autopilot.runs, 30)
    return st


async def _h_autopilot_run_now(_p: dict) -> dict:
    """A run on the user's click. Started in the background: the renderer
    gets an answer now and watches the run on the status poll."""
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    if autopilot.STATE.running:
        return {"ok": False, "message": "Autopilot is already running."}
    why = autopilot.blocked_reason(cfg)
    if not why:
        why = await asyncio.to_thread(autopilot.tool_refusal, cfg)
    if why:
        return {"ok": False, "message": why}
    t = asyncio.create_task(autopilot.run_once(cfg, "manual"))
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return {"ok": True, "message": "Autopilot run started."}


async def _h_mcp_decide(p: dict) -> dict:
    """The user's answer to a live agent order waiting for approval. The
    renderer only names the row and yes/no; the order itself is the one the
    backend recorded, re-vetted here before anything is sent."""
    try:
        rid = int((p or {}).get("id"))
    except (TypeError, ValueError):
        raise ValueError("id required")
    return await mcp_server.decide(rid, bool((p or {}).get("approve")), via="app")


def _mcp_agent_param(p: dict, cfg: dict) -> dict:
    """The named agent a token request is for. Unknown is refused, never
    defaulted: copying Default's token when the user clicked "Connect" on
    Sports Sam would wire their client up as the wrong trader."""
    aid = str((p or {}).get("agentId") or "").strip().lower()
    agent = mcp_agents.get(cfg, aid) if mcp_agents.valid_id(aid) else None
    if agent is None:
        raise ValueError("No such agent. Refresh the AI Agents page.")
    return agent


async def _h_mcp_rotate_token(p: dict) -> dict:
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    agent = _mcp_agent_param(p, cfg)
    await asyncio.to_thread(mcp_server.rotate_token, agent["id"])
    logger.info(f"[mcp] token rotated for agent {agent['id']} — every client "
                f"configured as it must be updated")
    return {"ok": True}


async def _h_mcp_client_config(p: dict) -> dict:
    """The snippet WITH the token. Electron main calls this and puts the text
    on the clipboard; it is never forwarded to the renderer."""
    client = str((p or {}).get("client") or "")
    if client not in mcp_server.CLIENTS:
        raise ValueError(f"client must be one of {', '.join(mcp_server.CLIENTS)}")
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    agent = _mcp_agent_param(p, cfg)
    token = await asyncio.to_thread(mcp_server.get_token, True, agent["id"])
    return {"client": client,
            "text": mcp_server.client_config(client, int(cfg["mcp_port"]), token, agent)}


async def _h_mcp_http_snippet(p: dict) -> dict:
    """curl + Python examples for the HTTP API, WITH the token. Same rule as
    mcpClientConfig: only Electron main calls this, and it goes straight to
    the clipboard — the renderer never sees the text."""
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    agent = _mcp_agent_param(p, cfg)
    token = await asyncio.to_thread(mcp_server.get_token, True, agent["id"])
    return {"text": mcp_server.http_snippet(int(cfg["mcp_port"]), token)}



async def _health_kalshi(deep: bool) -> dict:
    env = kalshi_auth.get_env()
    present = kalshi_auth.credentials_present()
    if not (deep and present):
        return health.check_kalshi(env, present, STATE.auth_ok)
    try:
        await _h_testCredentials({})
    except Exception as e:
        return health.check_kalshi(env, True, STATE.auth_ok, probed=True,
                                   probe_ok=False, probe_error=e)
    return health.check_kalshi(env, True, STATE.auth_ok, probed=True, probe_ok=True)


async def _health_ai(deep: bool, cfg: dict) -> list:
    check = getattr(ai_analyst, "check_provider", None)
    can_probe = callable(check)
    active = ai_analyst._norm_provider(cfg.get("ai_provider"))
    out = []
    for prov in ai_analyst.PROVIDERS:
        try:
            local = not ai_analyst.needs_key(prov)
        except Exception:
            local = False
        if local and prov != active:
            continue
        try:
            has = True if local else bool(ai_analyst.has_key(prov))
        except Exception:
            has = False
        if not (deep and has and can_probe):
            needed = prov == active and bool(cfg.get("autopilot_enabled"))
            out.append(health.check_ai(prov, active=prov == active, has_key=has,
                                       can_probe=can_probe, local=local, needed=needed))
            continue
        if prov != active:
            out.append(health.check_ai(prov, active=False, has_key=True,
                                       can_probe=True, local=local, idle=True))
            continue
        try:
            import inspect
            if inspect.iscoroutinefunction(check):
                res = await asyncio.wait_for(check(prov, cfg), 30.0)
            else:
                res = await asyncio.wait_for(asyncio.to_thread(check, prov, cfg), 30.0)
            out.append(health.check_ai(prov, active=prov == active, has_key=True,
                                       can_probe=True, probed=True, local=local,
                                       probe=res if isinstance(res, dict) else {}))
        except Exception as e:
            out.append(health.check_ai(prov, active=prov == active, has_key=True,
                                       can_probe=True, probed=True, probe_error=e,
                                       local=local))
    return out


async def _health_agents(deep: bool, cfg: dict) -> list:
    st = await asyncio.to_thread(mcp_server.status, cfg)
    rows = [health.check_mcp(st)]
    probe = None
    if deep and st.get("enabled") and st.get("httpEnabled") and st.get("running"):
        token = None
        for a in mcp_agents.agents(cfg):
            if a.get("enabled", True):
                token = await asyncio.to_thread(mcp_server.get_token, False, a["id"])
                if token:
                    break
        probe = (await health.probe_http(int(st["port"]), token) if token
                 else {"ok": False, "status": 401, "error": "no token"})
    rows.append(health.check_http(st, probed=probe is not None, probe=probe))
    return rows


def _health_local(cfg: dict) -> list:
    rows = [health.check_autopilot(autopilot.status(cfg))]
    for which, bot, paired in (
            ("discord", remote_discord.BOT, bool(cfg.get("remote_discord_user_id"))),
            ("telegram", remote_telegram.BOT,
             bool(cfg.get("remote_telegram_chat_id") or remote_telegram.BOT.chat_id))):
        rows.append(health.check_remote(
            which, enabled=bool(cfg.get(f"remote_{which}_enabled")),
            has_token=kalshi_auth.has_secret(f"{which}_bot_token"),
            paired=paired, bot=bot.status()))
    try:
        stats = kalshi_ws.stats()
    except Exception:
        stats = None
    rows.append(health.check_ws(stats, authed=STATE.auth_ok))
    return rows


async def _h_health_check(p: dict) -> dict:
    deep = (p or {}).get("deep") is True
    cfg = merge_with_defaults(dict(STATE.cfg or {}))

    async def _guard(label: str, coro) -> list:
        try:
            r = await coro
            return r if isinstance(r, list) else [r]
        except Exception as e:
            logger.warning(f"[health] {label} check failed: {type(e).__name__}: {e}")
            return [health.row(label.lower().replace(" ", "-"), label, health.FAIL,
                               f"The check itself failed: {type(e).__name__}.",
                               "Copy diagnostics from the Logs page if this persists.")]

    async def _local() -> list:
        return await asyncio.to_thread(_health_local, cfg)

    parts = await asyncio.gather(
        _guard("Kalshi", _health_kalshi(deep)),
        _guard("AI providers", _health_ai(deep, cfg)),
        _guard("AI agents", _health_agents(deep, cfg)),
        _guard("Local services", _local()),
    )
    rows = [r for part in parts for r in part]
    if deep:
        bad = [r["id"] for r in rows if r["status"] in (health.FAIL, health.WARN)]
        logger.info(f"[health] checks run: {len(rows)} rows, attention: {bad or 'none'}")
    return {"checkedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "deep": deep, "rows": rows}


async def _h_mcp_activity(p: dict) -> dict:
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    limit = max(1, min(int((p or {}).get("limit") or 100), 500))
    rows = await asyncio.to_thread(mcp_server.activity, limit)
    tickers = await asyncio.to_thread(paper_book.open_tickers, None, agents_only=True)
    marks: dict = {}
    if tickers:
        try:
            found = await terminal._public_gate.run(
                kalshi_api.fetch_markets_by_tickers, tickers) or {}
            marks = {t: terminal.market_row(m) for t, m in found.items()}
        except Exception as e:
            logger.debug(f"paper marks failed: {e}")
    paper = await asyncio.to_thread(
        paper_book.portfolio, float(cfg["paper_bankroll_usd"]), marks)
    ids = {a["id"] for a in mcp_agents.agents(cfg)}
    ids |= set(await asyncio.to_thread(paper_book.agent_ids))
    by_agent = {aid: await asyncio.to_thread(paper_book.agent_summary, aid, marks)
                for aid in sorted(ids)}
    acts = await asyncio.to_thread(mcp_workbench.actions, limit)
    return {"orders": rows, "paper": paper, "paperByAgent": by_agent, "actions": acts}


async def _h_paper_status(_p: dict) -> dict:
    """The paper account at a glance: mode, bankroll, cash, open orders.
    Local only — no network."""
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    bal = await paper_exchange.balance()
    with db.get_db() as conn:
        resting = conn.execute(
            "SELECT COUNT(*) FROM paper_orders WHERE status='resting'").fetchone()[0]
    return {
        "accountMode": cfg.get("account_mode"),
        "bankrollUsd": round(paper_exchange.bankroll(), 2),
        "nextBankrollUsd": round(float(cfg.get("paper_bankroll_usd") or 0.0), 2),
        "cashUsd": round(int(bal["balance"]) / 100.0, 2),
        "restingOrders": int(resting or 0),
        "hasKalshiKey": kalshi_auth.credentials_present(),
    }


async def _h_paper_reset(_p: dict) -> dict:
    """Start the paper account over at the bankroll. Confirmed in the app
    before it is sent; touches nothing live."""
    removed = await paper_exchange.reset_account()
    for k in [k for k in trader._day_risk_breach if k and k[0] == db.PAPER_ENV]:
        trader._day_risk_breach.pop(k, None)
    if kalshi_auth.is_paper():
        STATE.active_run_id = 0
        try:
            cents, _ = await trader.refresh_balance(STATE.cfg, force=True)
            await _start_run_if_balance_known(kalshi_auth.get_env(), cents)
        except Exception as e:
            logger.warning(f"paper reset: could not open a new run: {e}")
    await emit_event("data:reset", {"summary": removed, "scope": "paper"})
    try:
        await emit_event("account:update", await _build_account_snapshot())
    except Exception:
        pass
    return {"ok": True, "removed": removed}


async def _h_mcp_paper_reset(p: dict) -> dict:
    return await _h_paper_reset(p)


async def _h_mcp_agent_close_paper(p: dict) -> dict:
    """The user closing one agent's PAPER positions at the bid — the only
    way out for a deleted or switched-off agent's, which nothing it can call
    will sell. The app's own button; never in _MCP_RPC_ALLOWED, so no agent
    reaches it. Touches the paper book only."""
    return await mcp_server.close_agent_paper((p or {}).get("agentId"))


async def _mcp_submit(req: dict, scope: Optional[str] = None) -> dict:
    return await _h_terminal_submit(req, scope=scope)


async def _mcp_cancel(order_id: str) -> dict:
    return await _h_terminal_cancel({"orderId": order_id})


async def _mcp_rpc(method: str, params: dict) -> Any:
    if method not in _MCP_RPC_ALLOWED:
        raise ValueError(f"{method} is not available to agents")
    return await _HANDLERS[method](params or {})


_MCP_RPC_ALLOWED = frozenset({
    "collectionStats", "c15Backtest", "mainBacktest", "terminalHistory",
    "c15History", "scriptContextPack", "scriptValidate", "scriptBacktest",
    "scriptSave", "scriptSetEnabled", "tradingStatus",
})


async def _sync_mcp() -> None:
    await mcp_server.sync(merge_with_defaults(dict(STATE.cfg or {})))


_MAIN_AGENT_IDS: list = [None]


def _names_agents(raw_cfg: Any) -> Optional[set]:
    """The agent ids a config main sent lists, or None if it lists none (an
    old settings file): that config knows nothing about the user's agents."""
    if not isinstance(raw_cfg, dict):
        return None
    lst = raw_cfg.get("mcpAgents", raw_cfg.get("mcp_agents"))
    if not isinstance(lst, list) or not lst:
        return None
    return {str(a.get("id") or "").strip().lower() for a in lst if isinstance(a, dict)}


def _prune_deleted_agent_tokens(raw_cfg: Any, prune: bool = True) -> None:
    """`prune` False only moves the baseline. setConfig passes it from main's
    `pruneAgentTokens` flag, which main sets when the USER removed agents —
    never on a Settings reset or a profile replace. "Reset all trading
    settings" sent a Default-only list, and pruning against it deleted every
    named agent's token: their clients stopped working and could not be
    brought back by restoring the settings. The baseline still moves, so a
    later real deletion is measured from the config in force, not from
    before the reset."""
    after = _names_agents(raw_cfg)
    gone = mcp_server.deleted_agents(_MAIN_AGENT_IDS[0], after) if prune else set()
    if after is not None:
        _MAIN_AGENT_IDS[0] = after
    if gone:
        removed = mcp_server.delete_tokens(gone)
        logger.info(f"[mcp] removed the tokens of {len(removed)} deleted agent(s)")


async def _h_remote_status(_p: dict) -> dict:
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    return {
        "discord": {
            **remote_discord.BOT.status(),
            "enabled": bool(cfg.get("remote_discord_enabled")),
            "hasToken": kalshi_auth.has_secret("discord_bot_token"),
            "userId": str(cfg.get("remote_discord_user_id") or ""),
        },
        "telegram": {
            **remote_telegram.BOT.status(),
            "enabled": bool(cfg.get("remote_telegram_enabled")),
            "hasToken": kalshi_auth.has_secret("telegram_bot_token"),
            "chatId": str(cfg.get("remote_telegram_chat_id") or ""),
            "pairCode": remote.pair_code_valid(),
        },
        "tradingEnabled": bool(cfg.get("remote_trading_enabled")),
        "alertsEnabled": bool(cfg.get("remote_alerts_enabled")),
    }


async def _h_remote_set_token(p: dict) -> dict:
    which = str((p or {}).get("which") or "")
    token = str((p or {}).get("token") or "").strip()
    if which not in ("discord", "telegram"):
        raise ValueError("which must be discord or telegram")
    name = f"{which}_bot_token"
    if token:
        kalshi_auth.save_secret(name, token)
    else:
        kalshi_auth.clear_secret(name)
    try:
        import logscrub
        logscrub.refresh_known_secrets()
    except Exception:
        pass
    logger.info(f"[remote] {which} bot token {'saved' if token else 'cleared'}")
    await _sync_remote_bots()
    return {"ok": True, "hasToken": kalshi_auth.has_secret(name)}


async def _h_remote_pair_code(_p: dict) -> dict:
    return {"code": remote.new_pair_code(), "ttlSec": int(remote.PAIR_CODE_TTL)}


async def _h_remote_unpair(p: dict) -> dict:
    which = str((p or {}).get("which") or "")
    if which == "telegram":
        STATE.cfg["remote_telegram_chat_id"] = ""
        remote_telegram.BOT.chat_id = ""
        await remote_telegram.BOT.stop()
    elif which == "discord":
        STATE.cfg["remote_discord_user_id"] = ""
        await remote_discord.BOT.stop()
    await _sync_remote_bots()
    return {"ok": True}


async def _h_remote_test(_p: dict) -> dict:
    """Prove the round trip end to end, from the app, before trusting it."""
    sent = []
    for name, bot in (("discord", remote_discord.BOT),
                      ("telegram", remote_telegram.BOT)):
        if bot.task and not bot.task.done():
            ok = await bot.send(
                "Test message from Krypt Terminal. If you can read this, the "
                "link works — send 'help' for what it can do.")
            sent.append({"which": name, "ok": bool(ok),
                         "error": bot.last_error if not ok else None})
    return {"sent": sent}


async def _h_crossvenue(p: dict) -> dict:
    """The same question, priced on Polymarket.

    Read-only: this app never sends an order to Polymarket. Pairing is done
    locally because Gamma's search parameter is silently ignored, and a pair is
    only priced when the matcher is confident — an unconfident candidate is
    shown as a candidate, with its reasons, for the user to judge."""
    import crossvenue
    import polymarket_public
    ticker = str((p or {}).get("ticker") or "").strip().upper()
    if not ticker:
        raise ValueError("no ticker")

    raw = await terminal._public_gate.run(kalshi_api.fetch_market, ticker)
    if not raw:
        raise RuntimeError(f"Kalshi has no market called {ticker}.")
    krow = terminal._apply_live_quote(terminal.market_row(raw))

    try:
        sweep = await polymarket_public.sweep()
    except Exception as e:
        return {
            "ticker": ticker,
            "available": False,
            "geoblocked": polymarket_public.geoblocked(),
            "matches": [], "scanned": None,
            "note": str(e),
            "venueNote": crossvenue.VENUE_NOTE,
            "fetchedAt": terminal._now_iso(),
        }

    quoted = [m for m in sweep["markets"] if m["yesBid"] is not None]
    matches = await asyncio.to_thread(
        crossvenue.find_matches, krow, quoted, 4)
    out = []
    for m in matches:
        out.append({
            "confidence": m["confidence"],
            "confident": m["confident"],
            "reasons": m["reasons"],
            "market": m["market"],
            "comparison": (crossvenue.compare(krow, m["market"])
                           if m["confident"] else None),
        })

    note = None
    if sweep.get("truncated"):
        note = (
            f"Searched the {len(sweep['markets']):,} most-traded open "
            f"Polymarket markets. A thinner market that is not in that slice "
            f"would not be found."
        )
    return {
        "ticker": ticker,
        "available": True,
        "geoblocked": polymarket_public.geoblocked(),
        "matches": out,
        "scanned": len(quoted),
        "polymarketAgeSec": sweep.get("ageSec"),
        "kalshiObservedAt": krow.get("observedAt"),
        "note": note,
        "venueNote": crossvenue.VENUE_NOTE,
        "fetchedAt": terminal._now_iso(),
    }


async def _h_terminal_hosts(_p: dict) -> dict:
    return await asyncio.to_thread(terminal.network_report)


async def _h_terminal_preview(p: dict) -> dict:
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    ticker = str((p or {}).get("ticker") or "").strip().upper()
    market = book = position = None
    try:
        raw = await terminal._public_gate.run(kalshi_api.fetch_market, ticker)
        market = terminal._apply_live_quote(terminal.market_row(raw)) if raw else None
    except Exception as e:
        logger.debug(f"terminal preview: market read failed for {ticker}: {e}")
    try:
        book = await terminal.book(ticker)
    except Exception as e:
        logger.debug(f"terminal preview: book read failed for {ticker}: {e}")
    if STATE.auth_ok:
        try:
            pf = await terminal.portfolio(True)
            position = next(
                (x for x in pf["positions"] if x["ticker"] == ticker), None)
        except Exception as e:
            logger.debug(f"terminal preview: portfolio read failed: {e}")
    ex_status = None
    try:
        ex_status = await terminal._public_gate.run(
            kalshi_api.fetch_exchange_status)
    except Exception as e:
        logger.debug(f"terminal preview: exchange status read failed: {e}")
    return terminal.preview(
        p or {}, cfg=cfg, authed=STATE.auth_ok, market=market,
        book_snapshot=book, position=position, exchange_status=ex_status,
    )


async def _h_shard_transfer(p: dict) -> dict:
    """Move collateral between exchange shards. Real money — the renderer
    confirms, but every rail is enforced in kalshi_api regardless."""
    if kalshi_auth.is_paper():
        return {"ok": False, "message": "Paper mode has one pool of money — "
                "there is nothing to move between exchanges."}
    if not STATE.auth_ok:
        return {"ok": False, "message": "No verified Kalshi credentials."}
    p = p or {}
    try:
        res = await kalshi_api.transfer_between_shards(
            amount_usd=p.get("amountUsd"),
            source_shard=p.get("fromShard"),
            destination_shard=p.get("toShard"),
        )
    except ValueError as e:
        return {"ok": False, "message": str(e)}
    except Exception as e:
        logger.warning(f"shard transfer failed: {e}")
        return {"ok": False, "message": f"Kalshi refused the transfer: {kalshi_api.rejection_text(e)}"}
    try:
        shard_rail.record(kalshi_auth.get_env(), int(p.get("fromShard")), int(p.get("toShard")),
                          float(p.get("amountUsd") or 0), "you", True)
    except Exception:
        pass

    try:
        await trader.refresh_balance(merge_with_defaults(dict(STATE.cfg or {})),
                                     force=True)
    except Exception:
        pass
    return {
        "ok": True,
        "transferId": str((res or {}).get("transfer_id") or ""),
        "message": (
            f"Moved ${float(p.get('amountUsd') or 0):,.2f} to "
            f"{kalshi_api.shard_name(p.get('toShard'))}."
        ),
    }

async def _h_terminal_submit(p: dict, scope: Optional[str] = None) -> dict:
    """The desktop ticket's send, and every other manual-style order's.
    `scope` is never taken from the renderer's params (the ticket names the
    mode it expects as `expectMode`, which can only refuse): it comes from an
    in-process caller that decided the order in that scope."""
    if STATE.paused:
        return {
            "ok": False,
            "message": (
                "The backend is paused. Manual orders are gated the same way "
                "automated ones are."
            ),
            "orderId": None, "clientOrderId": "", "status": None,
            "filledContracts": None, "avgFillCents": None, "feesUsd": None,
            "reconciled": False,
        }
    cfg = merge_with_defaults(dict(STATE.cfg or {}))
    out = await terminal.submit(p or {}, cfg=cfg, authed=STATE.auth_ok, scope=scope)
    if out.get("ok"):
        STATE.ws_fill_pending = True
        if (out.get("filledContracts") or 0) > 0 and not kalshi_auth.is_paper():
            try:
                await trader.refresh_balance(STATE.cfg, force=True)
                await emit_event("account:update", await _build_account_snapshot())
            except Exception as e:
                logger.debug(f"post-fill balance refresh failed: {e}")
        logger.info(
            f"[terminal] manual order {out.get('orderId')} "
            f"{(p or {}).get('action')} {(p or {}).get('count')} "
            f"{(p or {}).get('side')} {(p or {}).get('ticker')} "
            f"@ {(p or {}).get('priceCents')}c — {out.get('message')}"
        )
    return out


async def _h_terminal_cancel(p: dict) -> dict:
    out = await terminal.cancel(str((p or {}).get("orderId") or ""), authed=STATE.auth_ok)
    if out.get("ok"):
        logger.info(f"[terminal] manual cancel {out.get('orderId')}")
    return out


_HANDLERS = {
    "ping": _h_ping,
    "terminalDiscover": _h_terminal_discover,
    "terminalSearch": _h_terminal_search,
    "terminalMarket": _h_terminal_market,
    "terminalBook": _h_terminal_book,
    "terminalCandles": _h_terminal_candles,
    "terminalTape": _h_terminal_tape,
    "terminalPortfolio": _h_terminal_portfolio,
    "terminalOrders": _h_terminal_orders,
    "terminalHistory": _h_terminal_history,
    "terminalRules": _h_terminal_rules,
    "terminalRuleCreate": _h_terminal_rule_create,
    "terminalRuleCancel": _h_terminal_rule_cancel,
    "terminalMicro": _h_terminal_micro,
    "terminalHosts": _h_terminal_hosts,
    "crossVenue": _h_crossvenue,
    "aiStatus": _h_ai_status,
    "aiSetKey": _h_ai_set_key,
    "aiCheckProvider": _h_ai_check_provider,
    "aiAnalyze": _h_ai_analyze,
    "aiScoreboard": _h_ai_scoreboard,
    "mcpStatus": _h_mcp_status,
    "mcpSeen": _h_mcp_seen,
    "mcpRotateToken": _h_mcp_rotate_token,
    "mcpClientConfig": _h_mcp_client_config,
    "mcpHttpSnippet": _h_mcp_http_snippet,
    "healthCheck": _h_health_check,
    "mcpActivity": _h_mcp_activity,
    "mcpPaperReset": _h_mcp_paper_reset,
    "mcp_agent_close_paper": _h_mcp_agent_close_paper,
    "paperStatus": _h_paper_status,
    "paperReset": _h_paper_reset,
    "mcpDecide": _h_mcp_decide,
    "autopilotStatus": _h_autopilot_status,
    "autopilotRunNow": _h_autopilot_run_now,
    "remoteStatus": _h_remote_status,
    "remoteSetToken": _h_remote_set_token,
    "remotePairCode": _h_remote_pair_code,
    "remoteUnpair": _h_remote_unpair,
    "remoteTest": _h_remote_test,
    "terminalPreview": _h_terminal_preview,
    "terminalSubmit": _h_terminal_submit,
    "shardTransfer": _h_shard_transfer,
    "terminalCancel": _h_terminal_cancel,
    "crypto15m": _h_crypto15m,
    "crypto15mStatus": _h_crypto15mStatus,
    "tradingStatus": _h_trading_status,
    "c15Backtest": _h_c15_backtest,
    "mainBacktest": _h_main_backtest,
    "scriptsList": _h_scripts_list,
    "scriptSave": _h_script_save,
    "scriptDelete": _h_script_delete,
    "scriptSetEnabled": _h_script_set_enabled,
    "scriptSetTrusted": _h_script_set_trusted,
    "scriptValidate": _h_script_validate,
    "scriptBacktest": _h_script_backtest,
    "scriptContextPack": _h_script_context_pack,
    "scriptApiDocs": _h_script_api_docs,
    "collectionStats": _h_collection_stats,
    "edgeHealth": _h_edge_health,
    "perpsStatus": _h_perps_status,
    "perpsFarmFlatten": _h_perps_farm_flatten,
    "c15History": _h_c15_history,
    "turbineLibrary": _h_turbine_library,
    "coinOptimize": _h_coin_optimize,
    "exportResearch": _h_export_research,
    "kalshiMarketUrl": _h_kalshiMarketUrl,
    "setConfig": _h_setConfig,
    "setCredentials": _h_setCredentials,
    "clearCredentials": _h_clearCredentials,
    "credentialStatus": _h_credentialStatus,
    "testCredentials": _h_testCredentials,
    "verifyCredentials": _h_verifyCredentials,
    "account": _h_account,
    "pnlSeries": _h_pnlSeries,
    "positions": _h_positions,
    "signals": _h_signals,
    "scannerStats": _h_scannerStats,
    "cancelAllOpen": _h_cancelAllOpen,
    "flatten": _h_flatten,
    "runOnce": _h_runOnce,
    "pause": _h_pause,
    "shutdown": _h_shutdown,
    "botRuns": _h_botRuns,
    "factoryReset": _h_factoryReset,
}


async def _dispatch_request(req: dict) -> None:
    rid = req.get("id", "")
    method = req.get("method", "")
    params = req.get("params") or {}
    h = _HANDLERS.get(method)
    if not h:
        await respond_err(rid, f"unknown method: {method}")
        return
    try:
        result = await h(params)
        await respond_ok(rid, result)
    except Exception as e:
        logger.warning(
            f"RPC {method} failed: {e}\n{traceback.format_exc(limit=3)}"
        )
        await respond_err(rid, human_error(e), code=type(e).__name__)




async def _stdin_reader() -> None:
    loop = asyncio.get_event_loop()

    def _readline() -> str:
        return sys.stdin.readline()

    while True:
        line = await loop.run_in_executor(None, _readline)
        if not line:
            await asyncio.sleep(0.1)
            await _shutdown()
            return
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        if not isinstance(req, dict):
            continue
        if req.get("type") != "rpc":
            continue
        t = asyncio.create_task(_dispatch_request(req))
        _bg_tasks.add(t)
        t.add_done_callback(_bg_tasks.discard)


_shutting_down = False


async def _shutdown() -> None:
    global _shutting_down
    if _shutting_down:
        return
    _shutting_down = True
    try:
        await _stop_loop()
    except Exception:
        pass
    try:
        if STATE.active_run_id:
            with db.get_db() as conn:
                db.end_bot_run(conn, STATE.active_run_id)
            STATE.active_run_id = 0
    except Exception:
        pass
    try:
        await kalshi_api.close_clients()
    except Exception:
        pass
    try:
        import polymarket_public
        await polymarket_public.close_clients()
    except Exception:
        pass
    for _bot in (remote_discord.BOT, remote_telegram.BOT):
        try:
            await _bot.stop()
        except Exception:
            pass
    try:
        await mcp_server.stop()
    except Exception:
        pass
    try:
        await crypto15m.close_clients()
    except Exception:
        pass
    try:
        await kalshi_ws.stop()
    except Exception:
        pass
    try:
        await perps_farmer.ensure_stopped()
    except Exception:
        pass
    try:
        await perps_ws.stop()
    except Exception:
        pass
    try:
        await kalshi_perps_api.close_clients()
    except Exception:
        pass
    try:
        await spot_ws.stop()
    except Exception:
        pass
    await emit_event("backend:shutdown", {})
    sys.stdout.flush()
    await asyncio.sleep(0.1)
    os._exit(0)




async def _main() -> None:
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
    STATE.started_at = datetime.now(timezone.utc).isoformat()
    db.init_db()
    script_engine.set_event_callback(emit_event)
    logger.info("Krypt Trader backend starting")

    active_env = scope_env(STATE.cfg)
    try:
        kalshi_auth.set_env(active_env)
    except Exception:
        pass

    STATE.auth_ok = active_env == kalshi_auth.PAPER
    if active_env != kalshi_auth.PAPER and kalshi_auth.credentials_present():
        try:
            kalshi_auth.prime_credentials(sync_time=True)
            bal = await kalshi_api.get_balance()
            int(bal.get("balance", 0))
            STATE.auth_ok = True
            logger.info("Saved credentials verified")
        except Exception as e:
            logger.warning(f"saved-credential verify failed: {e}")
            STATE.auth_ok = False

    await emit_event("backend:ready", {"startedAt": STATE.started_at})
    await emit_event("backend:authChanged", {"authOk": STATE.auth_ok})
    try:
        await emit_event(
            "credentials:changed", kalshi_auth.credentials_status_all(),
        )
    except Exception:
        pass

    if STATE.auth_ok:
        try:
            summary, changed = await trader.reconcile_positions_with_kalshi()
            if any(summary.values()):
                logger.info(f"Eager startup reconcile: {summary}")
            await emit_event("backend:reconciled", summary)
            for row in changed:
                await emit_event("position:update", _position_row_to_js(row))
        except Exception as e:
            logger.warning(f"eager startup reconcile failed: {e}")

    if STATE.auth_ok:
        try:
            cents, _ = await trader.refresh_balance(STATE.cfg, force=True)
            await _start_run_if_balance_known(kalshi_auth.get_env(), cents)
        except Exception as e:
            logger.warning(f"could not open bot_run: {e}")

    try:
        kalshi_ws.start(
            kalshi_auth.get_env(),
            on_fill=_on_ws_fill, on_lifecycle=_on_ws_lifecycle,
            on_trade=_on_ws_trade,
        )
    except Exception as e:
        logger.warning(f"kalshi_ws start failed (staying on REST): {e}")

    try:
        if STATE.cfg.get("crypto15m_spot_ws", True):
            kalshi_ws.set_cf_enabled(True)
            spot_ws.start()
    except Exception as e:
        logger.warning(f"spot feeds start failed (staying on REST spots): {e}")

    mcp_server.configure(
        get_cfg=lambda: merge_with_defaults(dict(STATE.cfg or {})),
        is_authed=lambda: STATE.auth_ok,
        submit=_mcp_submit,
        cancel=_mcp_cancel,
        rpc=_mcp_rpc,
        emit=emit_event,
        notify_phone=_remote_push,
        version=os.environ.get("KRYPT_APP_VERSION", ""),
    )
    try:
        await _sync_mcp()
    except Exception as e:
        logger.warning(f"MCP server start failed: {e}")

    await _start_loop()
    try:
        await _stdin_reader()
    except Exception as e:
        logger.error(f"reader crashed: {e}")
    finally:
        await _shutdown()


def _selftest() -> int:
    failures: list[str] = []

    mods = [
        "db", "scanner", "trader", "kalshi_api", "kalshi_auth", "categorize",
        "config", "webhook", "kalshi_ws", "crypto15m", "crypto15m_trader",
        "crypto15m_record", "backtest", "spot_ws", "cf_ws", "indicators",
        "replay", "rules", "turbine_import", "turbine_backtest",
        "crypto15m_backfill", "coin_optimizer", "strategy_generator",
        "script_sandbox", "script_engine", "script_backtest", "script_docs",
        "statistics", "terminal", "crossvenue", "polymarket_public", "remote",
        "remote_discord", "remote_telegram", "logscrub", "kalshi_perps_api",
        "perps_ws", "perps_farmer", "ws_ssl", "certifi",
        "ai_analyst", "ai_providers", "anthropic", "openai", "httpx",
        "httpx2", "httpcore2", "truststore",
        "forecast_ledger", "paper_book", "paper_exchange", "shard_rail", "mcp_server", "mcp_bridge",
        "mcp_workbench", "mcp_agents", "autopilot", "health", "kalshi_key_check",
        "capturetrail",
    ]
    import importlib
    for name in mods:
        try:
            importlib.import_module(name)
        except Exception as e:
            failures.append(f"import {name}: {type(e).__name__}: {e}")

    try:
        import logscrub
        probe = "selftest-secret-abcdef123456"
        logscrub.set_known_secrets([probe])
        if probe in logscrub.scrub(f"api key {probe} loaded"):
            failures.append("logscrub.scrub() did not redact a registered secret")
        logscrub.set_known_secrets([])
    except Exception as e:
        failures.append(f"logscrub check: {type(e).__name__}: {e}")

    try:
        import certifi
        import ws_ssl
        where = certifi.where()
        if not os.path.exists(where):
            failures.append(f"certifi CA bundle missing from the bundle at {where}")
        ctx = ws_ssl.client_context()
        if ctx is None:
            failures.append("ws_ssl.client_context() returned None — no certifi in the bundle")
        else:
            roots = ctx.cert_store_stats().get("x509_ca", 0)
            if roots < 1:
                failures.append(f"WebSocket SSL context loaded {roots} CA roots — every wss:// handshake will fail")
    except Exception as e:
        failures.append(f"websocket TLS check: {type(e).__name__}: {e}")

    try:
        import ai_providers
        failures.extend(f"AI SDK: {f}" for f in ai_providers.sdk_selfcheck())
    except Exception as e:
        failures.append(f"AI SDK check: {type(e).__name__}: {e}")

    if failures:
        print("SELFTEST FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"SELFTEST OK ({len(mods)} modules, certifi CA store loaded, AI SDK clients built)")
    return 0


if __name__ == "__main__":
    _mp.freeze_support()
    if "--selftest" in sys.argv[1:]:
        sys.exit(_selftest())
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
    finally:
        if _PROC_POOL is not None:
            try:
                _PROC_POOL.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
