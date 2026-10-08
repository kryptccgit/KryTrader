"""Script-engine money-rail regressions from the v5.0.0 launch review:
paper/live bucket separation, env-scoped attempt dedupe, the account-wide
daily-risk gate, the manage-sell fire-sale guard, insert-before-POST on
signal follows, lifecycle notification priming, and backtest/live parity
of the ask-intent entry-cap refusal."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import crypto15m
import crypto15m_trader
import db
import kalshi_api
import script_backtest
import script_engine as se
import trader
from config import merge_with_defaults


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "scripts-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


@pytest.fixture(autouse=True)
def reset_engine_state():
    se._notified_fill.clear()
    se._notified_settle.clear()
    se._lifecycle_primed = False
    se._compiled.clear()
    se._sig_marks["whale"] = None
    se._sig_marks["momentum"] = None
    yield
    se._compiled.clear()


@pytest.fixture
def cfg():
    c = merge_with_defaults({})
    c["scripts_live_enabled"] = True
    c["scripts_paper_mode"] = False
    return c


def run_async(coro):
    return asyncio.run(coro)


def _pos_row(sid="s1", ticker="KXBTC15M-T1", env="paper", dry_run=0):
    close = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    return {
        "asset": "BTC", "series": "KXBTC15M", "ticker": ticker, "side": "up",
        "direction": "yes", "target_contracts": 1, "entry_limit_cents": 86,
        "client_order_id": f"t-{ticker}-{dry_run}", "close_time": close,
        "confidence": 86.0, "kalshi_env": env, "status": "filled",
        "dry_run": dry_run, "strategy": f"script:{sid}", "script_id": sid,
    }


def _insert_resolved(conn, sid, ticker, env, dry_run, pnl):
    pid = db.insert_crypto15m_position(conn, _pos_row(sid, ticker, env, dry_run))
    conn.execute(
        """UPDATE crypto15m_positions
           SET resolved=1, pnl_usd=?, resolved_at=datetime('now'),
               filled_contracts=1
           WHERE id=?""",
        (pnl, pid),
    )
    return pid




def test_daily_pnl_scoped_by_mode(fresh_db):
    """Paper wins must never offset live losses in the daily-loss breaker."""
    with db.get_db() as conn:
        _insert_resolved(conn, "s1", "T-PAPER", "paper", dry_run=1, pnl=40.0)
        _insert_resolved(conn, "s1", "T-LIVE", "paper", dry_run=0, pnl=-30.0)
        assert se._script_daily_pnl(conn, "s1", "paper", paper=False) == -30.0
        assert se._script_daily_pnl(conn, "s1", "paper", paper=True) == 40.0


def test_open_count_scoped_by_mode(fresh_db):
    with db.get_db() as conn:
        db.insert_crypto15m_position(conn, _pos_row("s1", "T-P", "paper", dry_run=1))
        db.insert_crypto15m_position(conn, _pos_row("s1", "T-L", "paper", dry_run=0))
        assert se._count_open_for_script(conn, "s1", "paper", paper=False) == 1
        assert se._count_open_for_script(conn, "s1", "paper", paper=True) == 1


def test_script_live_stats_excludes_paper(fresh_db):
    with db.get_db() as conn:
        _insert_resolved(conn, "s1", "T-PAPER", "paper", dry_run=1, pnl=40.0)
        _insert_resolved(conn, "s1", "T-LIVE", "paper", dry_run=0, pnl=-30.0)
        stats = db.script_live_stats(conn, "paper")
        assert stats["s1"]["pnlUsd"] == -30.0
        assert stats["s1"]["n"] == 1




def test_already_attempted_scoped_by_env(fresh_db):
    with db.get_db() as conn:
        db.insert_crypto15m_position(conn, _pos_row("s1", "T-X", "paper"))
        assert se._already_attempted(conn, "s1", "T-X", "paper")
        assert not se._already_attempted(conn, "s1", "T-X", "production")



MANAGE_SELL = """\
# krypt-script v1
# name: Seller
def decide(ctx):
    return None

def manage(pos, ctx):
    return {"action": "sell"}
"""


def _filled_live_pos(conn, sid="s1", ticker="KXBTC15M-T1"):
    pid = db.insert_crypto15m_position(conn, _pos_row(sid, ticker, "paper"))
    conn.execute(
        "UPDATE crypto15m_positions SET filled_contracts=1, status='filled' "
        "WHERE id=?", (pid,))
    return pid


def _manage_env(monkeypatch, market):
    """Stub the quote paths: WS quote returns `market`, REST fetch fails."""
    calls = []

    async def _fail_fetch(_t):
        raise RuntimeError("api down")

    async def _record_exit(pos, m, cfg, *, reason):
        calls.append((pos["id"], m, reason))

    monkeypatch.setattr(crypto15m_trader, "_ws_quote_market", lambda _t: market)
    monkeypatch.setattr(kalshi_api, "fetch_market", _fail_fetch)
    monkeypatch.setattr(crypto15m_trader, "_place_exit", _record_exit)
    return calls


def test_manage_sell_requires_market_dict(fresh_db, cfg, monkeypatch):
    """No reachable market quote → NO exit order, even with a snapshot bid.
    (The old `market is None and bid_cents is None` guard let _place_exit run
    with market=None, whose orderbook-failure fallback fire-sales at 0.1c.)"""
    with db.get_db() as conn:
        _filled_live_pos(conn)
    calls = _manage_env(monkeypatch, market=None)
    mod = se.script_sandbox.CompiledScript("s1", MANAGE_SELL, trusted=False)
    s = {"id": "s1", "enabled": 1}
    assets = {"KXBTC15M-T1": {"ticker": "KXBTC15M-T1", "asset": "BTC",
                              "yesBid": 0.85, "yesAsk": 0.87, "minsLeft": 4.0}}
    run_async(se._manage_pass(s, mod, cfg, "paper", assets, {}))
    assert calls == []


def test_manage_sell_places_exit_with_market(fresh_db, cfg, monkeypatch):
    with db.get_db() as conn:
        _filled_live_pos(conn)
    market = {"ticker": "KXBTC15M-T1"}
    calls = _manage_env(monkeypatch, market=market)
    mod = se.script_sandbox.CompiledScript("s1", MANAGE_SELL, trusted=False)
    s = {"id": "s1", "enabled": 1}
    assets = {"KXBTC15M-T1": {"ticker": "KXBTC15M-T1", "asset": "BTC",
                              "yesBid": 0.85, "yesAsk": 0.87, "minsLeft": 4.0}}
    run_async(se._manage_pass(s, mod, cfg, "paper", assets, {}))
    assert len(calls) == 1
    assert calls[0][1] is market and calls[0][2] == "script_exit"



BUYER = """\
# krypt-script v1
# name: Buyer
def decide(ctx):
    if ctx["upAsk"] is None:
        return None
    return {"side": "up", "price": "ask"}
"""


def _asset(ticker="KXBTC15M-T1"):
    close = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    return {
        "asset": "BTC", "series": "KXBTC15M", "ticker": ticker,
        "hasMarket": True, "closeTime": close, "minsLeft": 5.0,
        "favorite": "up", "favoritePrice": 0.86, "entryCost": 0.86,
        "upAsk": 0.87, "downAsk": 0.15, "yesBid": 0.85, "yesAsk": 0.87,
    }


def _run_tick_env(monkeypatch, *, blocked):
    placed = []

    async def _snap(_cfg):
        return {"assets": [_asset()]}

    async def _place(**kw):
        placed.append(kw)
        return {"order": {"order_id": "o1"}}

    async def _bal(_cfg, force=False):
        return 0, None

    monkeypatch.setattr(crypto15m, "snapshot", _snap)
    monkeypatch.setattr(kalshi_api, "place_limit_order", _place)
    monkeypatch.setattr(trader, "refresh_balance", _bal)
    monkeypatch.setattr(trader, "_is_blocked_by_daily_risk",
                        lambda _cfg, _env: (blocked, "day stop" if blocked else ""))
    monkeypatch.setattr(se.kalshi_auth, "get_env", lambda: "paper")
    row = {"id": "s1", "enabled": 1, "code": BUYER, "trusted": 0,
           "state_json": "{}", "name": "Buyer"}
    monkeypatch.setattr(db, "list_user_scripts", lambda conn: [row])
    return placed


def test_daily_risk_blocks_script_entries(fresh_db, cfg, monkeypatch):
    placed = _run_tick_env(monkeypatch, blocked=True)
    run_async(se.run_tick(cfg, authed=True))
    assert placed == []
    with db.get_db() as conn:
        n = conn.execute("SELECT COUNT(*) FROM crypto15m_positions").fetchone()[0]
    assert n == 0


def test_entries_flow_when_not_risk_blocked(fresh_db, cfg, monkeypatch):
    placed = _run_tick_env(monkeypatch, blocked=False)
    run_async(se.run_tick(cfg, authed=True))
    assert len(placed) == 1




def _sig():
    return {"id": 7, "ticker": "KXTEST-A", "taker_side": "yes",
            "event_ticker": "KXTEST", "title": "t", "category": "crypto"}


def _signal_env(monkeypatch, *, post, lookup):
    async def _fetch(_t):
        return {"m": 1}

    monkeypatch.setattr(kalshi_api, "fetch_market", _fetch)
    monkeypatch.setattr(crypto15m, "_price_dollars",
                        lambda m, k: 0.50 if k == "yes_ask" else 0.45)
    monkeypatch.setattr(kalshi_api, "place_limit_order", post)

    async def _lookup(coid, ticker, pin_env=None):
        return lookup

    monkeypatch.setattr(crypto15m_trader, "_lookup_lost_order", _lookup)


def test_signal_follow_books_row_before_post_error(fresh_db, cfg, monkeypatch):
    """POST raises + coid lookup confirms absence → row exists as resolved
    error (old code returned None with NO row — a delivered-but-timed-out
    order would have been live money invisible to every rail)."""
    async def _post(**kw):
        raise RuntimeError("timeout")

    _signal_env(monkeypatch, post=_post, lookup=(None, True))
    s = {"id": "s1", "enabled": 1}
    row = run_async(se._place_signal_follow(
        s, _sig(), "whale", {"action": "follow"}, cfg, "paper"))
    assert row is not None and row["status"] == "error" and row["resolved"] == 1


def test_signal_follow_recovers_delivered_order(fresh_db, cfg, monkeypatch):
    async def _post(**kw):
        raise RuntimeError("timeout")

    _signal_env(monkeypatch, post=_post, lookup=({"order_id": "oX"}, True))
    s = {"id": "s1", "enabled": 1}
    row = run_async(se._place_signal_follow(
        s, _sig(), "whale", {"action": "follow"}, cfg, "paper"))
    assert row["kalshi_order_id"] == "oX"
    assert row["status"] == "submitted" and not row["resolved"]


def test_signal_follow_success_books_row(fresh_db, cfg, monkeypatch):
    async def _post(**kw):
        return {"order": {"order_id": "o2"}}

    _signal_env(monkeypatch, post=_post, lookup=(None, False))
    s = {"id": "s1", "enabled": 1}
    row = run_async(se._place_signal_follow(
        s, _sig(), "whale", {"action": "follow"}, cfg, "paper"))
    assert row["kalshi_order_id"] == "o2"
    assert row["script_id"] == "s1"



COUNTER = """\
# krypt-script v1
# name: Counter
def decide(ctx):
    return None

def on_fill(pos, state):
    state["fills"] = state.get("fills", 0) + 1

def on_settle(pos, state):
    state["settles"] = state.get("settles", 0) + 1
"""


def test_lifecycle_primes_without_refiring(fresh_db, monkeypatch):
    monkeypatch.setattr(se.kalshi_auth, "get_env", lambda: "paper")
    with db.get_db() as conn:
        _insert_resolved(conn, "s1", "T-OLD", "paper", dry_run=0, pnl=1.0)
        _filled_live_pos(conn, "s1", "T-OPEN")
    mod = se.script_sandbox.CompiledScript("s1", COUNTER, trusted=False)
    se._compiled["s1"] = mod
    scripts = {"s1": {"id": "s1", "enabled": 1}}
    run_async(se._notify_lifecycle(scripts, "paper"))
    assert mod.state.get("fills") is None and mod.state.get("settles") is None
    with db.get_db() as conn:
        _insert_resolved(conn, "s1", "T-NEW", "paper", dry_run=0, pnl=2.0)
    run_async(se._notify_lifecycle(scripts, "paper"))
    run_async(se._notify_lifecycle(scripts, "paper"))
    assert mod.state.get("settles") == 1
    assert mod.state.get("fills") == 1




def _bt_run(monkeypatch, ask, cfg):
    now = datetime.now(timezone.utc)
    tick = {
        "asset": "BTC", "yes_ask": ask, "yes_bid": ask - 0.02, "up_won": 1,
        "sig_close": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "observed_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    monkeypatch.setattr(script_backtest.replay, "load_windows",
                        lambda env, days: {"KXBTC15M-T1": [tick]})
    monkeypatch.setattr(
        script_backtest.replay, "tick_to_asset",
        lambda t, c, close: {"asset": t.get("asset"), "minsLeft": 2.0,
                             "upAsk": t.get("yes_ask"), "downAsk": None})
    return script_backtest.run(cfg, BUYER, trusted=False, env="paper",
                               since_days=7)


def test_backtest_refuses_cap_boundary_ask_like_live(fresh_db, cfg, monkeypatch):
    """Live submits ask intents at round(ask)+1 and refuses >cap — an ask of
    96.8c under the default 97c cap is refused live, so the backtest must not
    show it as a fill (it did: users backtested 97c-favorite scripts into
    phantom profits)."""
    out = _bt_run(monkeypatch, ask=0.968, cfg=cfg)
    assert out["n"] == 0
    assert any("refused by the safety rails" in c for c in out["caveats"])


def test_backtest_fills_below_cap_band(fresh_db, cfg, monkeypatch):
    out = _bt_run(monkeypatch, ask=0.90, cfg=cfg)
    assert out["n"] == 1
