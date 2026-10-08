"""Regression tests for the pre-launch risk-control fixes:
  - exposure must count committed notional of unfilled/resting orders
    (so max_total_exposure_fraction can't be bypassed in one scan cycle, and
    so account total = cash + committed is P&L-neutral on open);
  - baseline P&L queries must ignore $0 (cold-cache) snapshots (so the daily
    stop-loss can't be silently disabled by a poisoned baseline);
  - factory_reset must wipe the crypto15m tables.
"""
from __future__ import annotations

import asyncio

import pytest

import crypto15m
import db
import trader


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "risk-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


def _pos(**over) -> dict:
    row = {
        "signal_source": "whale", "signal_id": "s1", "ticker": "T",
        "direction": "yes", "target_contracts": 100, "limit_price_cents": 50,
        "filled_contracts": 0, "cost_usd": 0.0, "client_order_id": "c1",
        "status": "submitted", "kalshi_env": "paper",
    }
    row.update(over)
    return row


def test_exposure_counts_committed_notional_for_unfilled(fresh_db):
    with db.get_db() as conn:
        db.insert_bot_position(conn, _pos(
            signal_id="a", client_order_id="a", status="submitted",
            target_contracts=100, limit_price_cents=50, cost_usd=0.0))
        exposure = db.current_total_exposure_usd(conn, "paper")
    assert exposure == pytest.approx(50.0)


def test_exposure_uses_actual_cost_for_filled(fresh_db):
    with db.get_db() as conn:
        db.insert_bot_position(conn, _pos(
            signal_id="b", client_order_id="b", status="filled",
            target_contracts=100, limit_price_cents=50,
            filled_contracts=100, cost_usd=47.0))
        exposure = db.current_total_exposure_usd(conn, "paper")
    assert exposure == pytest.approx(47.0)


def test_exposure_accumulates_across_one_cycle(fresh_db):
    with db.get_db() as conn:
        for i in range(3):
            db.insert_bot_position(conn, _pos(
                signal_id=f"x{i}", client_order_id=f"x{i}", status="submitted",
                target_contracts=100, limit_price_cents=30, cost_usd=0.0))
        exposure = db.current_total_exposure_usd(conn, "paper")
    assert exposure == pytest.approx(90.0)


def test_open_filled_cost_excludes_unfilled(fresh_db):
    with db.get_db() as conn:
        db.insert_bot_position(conn, _pos(
            signal_id="u", client_order_id="u", status="submitted",
            target_contracts=100, limit_price_cents=70, cost_usd=0.0))
        db.insert_bot_position(conn, _pos(
            signal_id="f", client_order_id="f", status="filled",
            target_contracts=50, limit_price_cents=40,
            filled_contracts=50, cost_usd=20.0))
        filled = db.open_filled_cost_usd(conn, "paper")
        committed = db.current_total_exposure_usd(conn, "paper")
    assert filled == pytest.approx(20.0)
    assert committed == pytest.approx(90.0)


def test_resolved_positions_excluded_from_exposure(fresh_db):
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, _pos(
            signal_id="r", client_order_id="r", status="filled",
            filled_contracts=100, limit_price_cents=50, cost_usd=50.0))
        db.update_bot_position(conn, pid, resolved=1)
        exposure = db.current_total_exposure_usd(conn, "paper")
    assert exposure == pytest.approx(0.0)


def test_baseline_queries_ignore_zero_balance_rows(fresh_db):
    with db.get_db() as conn:
        db.insert_pnl_snapshot(conn, cash_usd=0.0, portfolio_usd=0.0,
                               realized_pnl_usd=0.0, wins=0, losses=0,
                               open_positions=0, env="paper")
        db.insert_pnl_snapshot(conn, cash_usd=100.0, portfolio_usd=20.0,
                               realized_pnl_usd=0.0, wins=0, losses=0,
                               open_positions=1, env="paper")
        earliest = db.earliest_pnl_total(conn, "paper")
        first_today = db.first_snapshot_of_today(conn, "paper")
    assert earliest == pytest.approx(120.0)
    assert first_today is not None
    assert float(first_today["total_usd"]) == pytest.approx(120.0)


def test_mid_up_one_sided_book_not_halved():
    assert crypto15m._mid_up(0.60, 0.64, 0.0) == pytest.approx(0.62)
    assert crypto15m._mid_up(0.70, 0.0, 0.0) == pytest.approx(0.70)
    assert crypto15m._mid_up(0.0, 0.80, 0.0) == pytest.approx(0.80)
    assert crypto15m._mid_up(0.0, 0.0, 0.55) == pytest.approx(0.55)
    assert crypto15m._mid_up(0.0, 0.0, 1.5) == pytest.approx(1.0)


def test_crypto15m_series_recognized_for_reconcile_skip():
    assert "KXBTC15M-26JUN282330-30".split("-")[0] in trader._CRYPTO15M_SERIES
    assert "KXETH15M".split("-")[0] in trader._CRYPTO15M_SERIES
    assert "KXMLBGAME-26JUN25-HOU".split("-")[0] not in trader._CRYPTO15M_SERIES


def test_open_crypto15m_cost_excludes_unfilled(fresh_db):
    with db.get_db() as conn:
        db.insert_crypto15m_position(conn, {
            "asset": "BTC", "series": "KXBTC15M", "ticker": "KXBTC15M-T1",
            "side": "yes", "direction": "yes", "target_contracts": 5,
            "filled_contracts": 5, "entry_limit_cents": 90, "avg_entry_cents": 90,
            "cost_usd": 4.5, "client_order_id": "c1", "kalshi_order_id": "E1",
            "status": "filled", "close_time": "", "confidence": 0,
            "entry_delta_usd": 0, "kalshi_env": "paper", "dry_run": 0, "error": None,
        })
        db.insert_crypto15m_position(conn, {
            "asset": "ETH", "series": "KXETH15M", "ticker": "KXETH15M-T1",
            "side": "yes", "direction": "yes", "target_contracts": 5,
            "filled_contracts": 0, "entry_limit_cents": 90, "avg_entry_cents": None,
            "cost_usd": 0.0, "client_order_id": "c2", "kalshi_order_id": "E2",
            "status": "submitted", "close_time": "", "confidence": 0,
            "entry_delta_usd": 0, "kalshi_env": "paper", "dry_run": 0, "error": None,
        })
        cost = db.open_crypto15m_filled_cost_usd(conn, "paper")
    assert cost == pytest.approx(4.5)


def test_factory_reset_wipes_crypto15m_positions(fresh_db):
    with db.get_db() as conn:
        db.insert_crypto15m_position(conn, {
            "asset": "BTC", "series": "KXBTC15M", "ticker": "KXBTC15M-T1",
            "side": "yes", "direction": "yes", "target_contracts": 5,
            "filled_contracts": 5, "entry_limit_cents": 90, "avg_entry_cents": 90,
            "cost_usd": 4.5, "client_order_id": "c", "kalshi_order_id": "E",
            "status": "filled", "close_time": "", "confidence": 0,
            "entry_delta_usd": 0, "kalshi_env": "paper", "dry_run": 0, "error": None,
        })
        assert db.count_open_crypto15m(conn, "paper") == 1

    db.factory_reset()

    with db.get_db() as conn:
        assert db.count_open_crypto15m(conn, "paper") == 0



def test_open_count_excludes_external_positions(fresh_db):
    with db.get_db() as conn:
        db.insert_bot_position(conn, _pos(
            signal_id="eng", client_order_id="eng", signal_source="whale",
            status="filled", filled_contracts=10, cost_usd=5.0))
        db.insert_bot_position(conn, _pos(
            signal_id="ext", client_order_id="ext", signal_source="external",
            status="filled", filled_contracts=10, cost_usd=5.0))
        n = db.count_open_bot_positions(conn, "paper")
    assert n == 1



def test_crypto15m_asset_enabled_gate():
    import config
    assert crypto15m.asset_enabled({}, "BTC") is True
    assert crypto15m.asset_enabled({"crypto15m_assets": None}, "DOGE") is True
    cfg = {"crypto15m_assets": ["BTC", "eth"]}
    assert crypto15m.asset_enabled(cfg, "BTC") is True
    assert crypto15m.asset_enabled(cfg, "ETH") is True
    assert crypto15m.asset_enabled(cfg, "SOL") is False
    assert crypto15m.asset_enabled({"crypto15m_assets": []}, "BTC") is False
    m = config.merge_with_defaults({"crypto15mAssets": ["btc", "ETH", "nope"]})
    assert m["crypto15m_assets"] == ["BTC", "ETH"]
    assert config.merge_with_defaults({})["crypto15m_assets"] is None



def _mock_kalshi(monkeypatch, live, market=None):
    monkeypatch.setattr(trader, "get_env", lambda: "paper")

    async def _gp(limit=1000, **_kw):
        return live

    async def _fm(ticker):
        return market

    monkeypatch.setattr(trader, "get_positions", _gp)
    monkeypatch.setattr(trader, "fetch_market", _fm)
    trader._orphan_miss_streak.clear()


def test_reconcile_closes_orphan_gone_from_kalshi(fresh_db, monkeypatch):
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, _pos(
            signal_id="orph", client_order_id="orph", ticker="KXBTC-OLD",
            direction="yes", status="filled", filled_contracts=10, cost_usd=5.0))
        conn.execute(
            "UPDATE bot_positions SET created_at=datetime('now','-1 hour') WHERE id=?",
            (pid,))
    _mock_kalshi(monkeypatch, [
        {"ticker": "KXOTHER-X", "position": 3, "market_exposure": 150},
    ], market=None)

    s1, _ = asyncio.run(trader.reconcile_positions_with_kalshi())
    assert s1["closed_orphans"] == 0
    with db.get_db() as conn:
        assert db.fetch_position_by_id(conn, pid)["resolved"] == 0

    s2, _ = asyncio.run(trader.reconcile_positions_with_kalshi())
    assert s2["closed_orphans"] == 1
    with db.get_db() as conn:
        row = db.fetch_position_by_id(conn, pid)
    assert row["resolved"] == 1
    assert row["status"] == "gone"


def test_reconcile_defers_orphan_pending_settlement(fresh_db, monkeypatch):
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, _pos(
            signal_id="pend", client_order_id="pend", ticker="KXBTC-PEND",
            direction="yes", status="filled", filled_contracts=10, cost_usd=5.0))
        conn.execute(
            "UPDATE bot_positions SET created_at=datetime('now','-1 hour') WHERE id=?",
            (pid,))
    _mock_kalshi(monkeypatch, [
        {"ticker": "KXOTHER-X", "position": 3, "market_exposure": 150},
    ], market={"status": "closed"})

    for _ in range(2):
        summary, _ = asyncio.run(trader.reconcile_positions_with_kalshi())
        assert summary["closed_orphans"] == 0
    with db.get_db() as conn:
        assert db.fetch_position_by_id(conn, pid)["resolved"] == 0


def test_reconcile_keeps_position_still_held(fresh_db, monkeypatch):
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, _pos(
            signal_id="hold", client_order_id="hold", ticker="KXBTC-HOLD",
            direction="yes", status="filled", filled_contracts=10, cost_usd=5.0))
    _mock_kalshi(monkeypatch, [
        {"ticker": "KXBTC-HOLD", "position": 10, "market_exposure": 500},
    ])

    summary, _ = asyncio.run(trader.reconcile_positions_with_kalshi())

    assert summary["closed_orphans"] == 0
    with db.get_db() as conn:
        row = db.fetch_position_by_id(conn, pid)
    assert row["resolved"] == 0


def test_reconcile_fresh_fill_needs_second_miss(fresh_db, monkeypatch):
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, _pos(
            signal_id="fresh", client_order_id="fresh", ticker="KXBTC-NEW",
            direction="yes", status="filled", filled_contracts=10, cost_usd=5.0))
    _mock_kalshi(monkeypatch, [
        {"ticker": "KXOTHER-X", "position": 3, "market_exposure": 150},
    ], market=None)

    s1, _ = asyncio.run(trader.reconcile_positions_with_kalshi())
    assert s1["closed_orphans"] == 0
    with db.get_db() as conn:
        assert db.fetch_position_by_id(conn, pid)["resolved"] == 0

    s2, _ = asyncio.run(trader.reconcile_positions_with_kalshi())
    assert s2["closed_orphans"] == 1
    with db.get_db() as conn:
        assert db.fetch_position_by_id(conn, pid)["resolved"] == 1



def test_side_mark_cents_uses_mid_then_last():
    q = {"yes_bid": 0.59, "yes_ask": 0.61, "last_price": 0.60}
    assert trader._side_mark_cents(q, "yes") == pytest.approx(60.0)
    assert trader._side_mark_cents(q, "no") == pytest.approx(40.0)
    assert trader._side_mark_cents({"yes_bid": 0.0, "yes_ask": 0.7, "last_price": 0.0}, "yes") == pytest.approx(70.0)
    assert trader._side_mark_cents({"yes_bid": 0.0, "yes_ask": 0.0, "last_price": 0.0}, "yes") is None
    assert trader._side_mark_cents(None, "yes") is None


def test_live_pnl_only_for_open_marked_filled():
    import service
    base = {"resolved": 0, "mark_price_cents": 60.0, "filled_contracts": 10, "cost_usd": 5.0}
    assert service._live_pnl_usd(base) == pytest.approx(1.0)
    assert service._live_pnl_usd({**base, "resolved": 1}) is None
    assert service._live_pnl_usd({**base, "mark_price_cents": None}) is None
    assert service._live_pnl_usd({**base, "filled_contracts": 0}) is None


def test_reconcile_marks_open_position_for_live_pnl(fresh_db, monkeypatch):
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, _pos(
            signal_id="mk", client_order_id="mk", ticker="KXBTC-MARK",
            direction="yes", status="filled", filled_contracts=10, cost_usd=5.0))
        db.upsert_market(conn, {
            "ticker": "KXBTC-MARK", "event_ticker": "", "title": "", "status": "active",
            "yes_bid": 0.59, "yes_ask": 0.61, "last_price": 0.60,
        })
    _mock_kalshi(monkeypatch, [
        {"ticker": "KXBTC-MARK", "position": 10, "market_exposure": 500},
    ])

    asyncio.run(trader.reconcile_positions_with_kalshi())

    import service
    with db.get_db() as conn:
        row = dict(db.fetch_position_by_id(conn, pid))
    assert row["mark_price_cents"] == pytest.approx(60.0)
    assert service._live_pnl_usd(row) == pytest.approx(1.0)




def _risk_cfg(**over):
    from config import merge_with_defaults
    base = {"stop_loss_on_day": -50.0, "stop_loss_on_day_pct": 0.0}
    base.update(over)
    return merge_with_defaults(base)


def _reset_breach(monkeypatch, persist_sec=0.0):
    """Make daily-risk breaches gate immediately (persistence tested on its own)."""
    monkeypatch.setattr(trader, "_DAY_RISK_PERSIST_SEC", persist_sec)
    trader._day_risk_breach.clear()


def test_daily_stop_counts_open_position_mark_to_market(fresh_db, monkeypatch):
    _reset_breach(monkeypatch)
    monkeypatch.setattr(trader, "_today_pnl_balance_delta", lambda env, off=0: -10.0)
    monkeypatch.setattr(db, "open_unrealized_pnl_usd", lambda conn, env: -45.0)
    cfg = _risk_cfg()
    blocked, why = trader._is_blocked_by_daily_risk(cfg, "paper")
    assert blocked is True and "mark-to-market" in why

    monkeypatch.setattr(db, "open_unrealized_pnl_usd", lambda conn, env: 0.0)
    assert trader._is_blocked_by_daily_risk(cfg, "paper")[0] is False


def test_daily_stop_pct_binds_when_tighter_than_flat(fresh_db, monkeypatch):
    _reset_breach(monkeypatch)
    monkeypatch.setattr(trader, "_today_pnl_balance_delta", lambda env, off=0: -22.0)
    monkeypatch.setattr(db, "open_unrealized_pnl_usd", lambda conn, env: 0.0)
    monkeypatch.setattr(
        db, "first_snapshot_of_today", lambda conn, env, off=0: {"total_usd": 400.0})
    cfg = _risk_cfg(stop_loss_on_day_pct=0.05)
    blocked, why = trader._is_blocked_by_daily_risk(cfg, "paper")
    assert blocked is True and "stop-loss" in why
    assert trader._is_blocked_by_daily_risk(_risk_cfg(), "paper")[0] is False


def test_daily_stop_ignores_transient_settlement_gap(fresh_db, monkeypatch):
    monkeypatch.setattr(trader, "_DAY_RISK_PERSIST_SEC", 180.0)
    trader._day_risk_breach.clear()
    monkeypatch.setattr(trader, "_today_pnl_balance_delta", lambda env, off=0: -10.0)
    monkeypatch.setattr(db, "open_unrealized_pnl_usd", lambda conn, env: 0.0)
    cfg = _risk_cfg(stop_loss_on_day=-5.0)
    assert trader._is_blocked_by_daily_risk(cfg, "paper")[0] is False
    trader._day_risk_breach[("paper", "sl")] = trader.time.time() - 181.0
    blocked, why = trader._is_blocked_by_daily_risk(cfg, "paper")
    assert blocked is True and "stop-loss" in why
    monkeypatch.setattr(db, "first_snapshot_of_today", lambda conn, env, off=0: None)
    assert trader._is_blocked_by_daily_risk(cfg, "production")[0] is False
    monkeypatch.setattr(trader, "_today_pnl_balance_delta", lambda env, off=0: +0.3)
    assert trader._is_blocked_by_daily_risk(cfg, "paper")[0] is False
    assert trader._day_risk_breach[("paper", "sl")] is None
    trader._day_risk_breach.clear()


def test_open_unrealized_pnl_uses_marks(fresh_db):
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, {
            "signal_source": "whale", "signal_id": 991, "ticker": "MTM-1",
            "direction": "yes", "target_contracts": 10, "limit_price_cents": 80,
            "filled_contracts": 10, "cost_usd": 8.0, "client_order_id": "mtm-1",
            "status": "filled", "kalshi_env": "paper",
        })
        db.update_bot_position(conn, pid, mark_price_cents=55.0)
        db.insert_bot_position(conn, {
            "signal_source": "whale", "signal_id": 992, "ticker": "MTM-2",
            "direction": "yes", "target_contracts": 5, "limit_price_cents": 60,
            "filled_contracts": 5, "cost_usd": 3.0, "client_order_id": "mtm-2",
            "status": "filled", "kalshi_env": "paper",
        })
        assert db.open_unrealized_pnl_usd(conn, "paper") == pytest.approx(-2.50)




def test_reconcile_treats_truncated_snapshot_as_failed(fresh_db, monkeypatch):
    from kalshi_api import KalshiTruncatedResult

    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, _pos(
            signal_id="tr", client_order_id="tr", ticker="KXTRUNC-1",
            direction="yes", status="filled", filled_contracts=10, cost_usd=5.0))
        conn.execute(
            "UPDATE bot_positions SET created_at=datetime('now','-1 hour') WHERE id=?",
            (pid,))
    monkeypatch.setattr(trader, "get_env", lambda: "paper")

    async def _gp(limit=1000, **_kw):
        raise KalshiTruncatedResult("page cap hit with rows remaining")

    monkeypatch.setattr(trader, "get_positions", _gp)
    trader._orphan_miss_streak.clear()

    for _ in range(3):
        summary, _ = asyncio.run(trader.reconcile_positions_with_kalshi())
        assert summary["closed_orphans"] == 0
    with db.get_db() as conn:
        assert db.fetch_position_by_id(conn, pid)["resolved"] == 0


def test_reconcile_keeps_working_partial_as_partial(fresh_db, monkeypatch):
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, _pos(
            signal_id="wp", client_order_id="wp", ticker="KXPART-1",
            direction="yes", status="submitted",
            target_contracts=10, limit_price_cents=60,
            filled_contracts=0, cost_usd=0.0))
    _mock_kalshi(monkeypatch, [
        {"ticker": "KXPART-1", "position": 6, "market_exposure": 360},
    ])

    asyncio.run(trader.reconcile_positions_with_kalshi())

    with db.get_db() as conn:
        row = db.fetch_position_by_id(conn, pid)
        exposure = db.current_total_exposure_usd(conn, "paper")
        pending_ids = [p["id"] for p in db.get_pending_bot_positions(conn, "paper")]
    assert row["status"] == "partial"
    assert row["filled_contracts"] == 6
    assert row["cost_usd"] == pytest.approx(3.6)
    assert exposure == pytest.approx(6.0)
    assert pid in pending_ids


def test_reconcile_flips_completed_order_to_filled(fresh_db, monkeypatch):
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, _pos(
            signal_id="fp", client_order_id="fp", ticker="KXPART-2",
            direction="yes", status="partial",
            target_contracts=10, limit_price_cents=60,
            filled_contracts=6, cost_usd=3.6))
    _mock_kalshi(monkeypatch, [
        {"ticker": "KXPART-2", "position": 10, "market_exposure": 600},
    ])

    asyncio.run(trader.reconcile_positions_with_kalshi())

    with db.get_db() as conn:
        row = db.fetch_position_by_id(conn, pid)
        exposure = db.current_total_exposure_usd(conn, "paper")
    assert row["status"] == "filled"
    assert row["filled_contracts"] == 10
    assert exposure == pytest.approx(6.0)


def test_reconcile_relinks_wrongly_resolved_row_instead_of_external(fresh_db, monkeypatch):
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, _pos(
            signal_id="rl", client_order_id="rl", ticker="KXRELINK-1",
            direction="yes", status="filled", filled_contracts=10, cost_usd=5.0))
        db.update_bot_position(
            conn, pid, status="gone", resolved=1,
            outcome_correct=None, pnl_usd=0.0, settlement_usd=0.0)
        conn.execute(
            "UPDATE bot_positions SET resolved_at=datetime('now','-2 days') WHERE id=?",
            (pid,))
    _mock_kalshi(monkeypatch, [
        {"ticker": "KXRELINK-1", "position": 10, "market_exposure": 500},
    ])

    summary, _ = asyncio.run(trader.reconcile_positions_with_kalshi())

    assert summary["imported_unknowns"] == 0
    assert summary["resurrected"] == 1
    with db.get_db() as conn:
        row = db.fetch_position_by_id(conn, pid)
        n_rows = conn.execute("SELECT COUNT(*) FROM bot_positions").fetchone()[0]
        open_count = db.count_open_bot_positions(conn, "paper")
    assert n_rows == 1
    assert row["resolved"] == 0
    assert row["status"] == "filled"
    assert open_count == 1


def test_reconcile_relinks_within_24h_window_too(fresh_db, monkeypatch):
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, _pos(
            signal_id="rl2", client_order_id="rl2", ticker="KXRELINK-2",
            direction="yes", status="gone", filled_contracts=10, cost_usd=5.0))
        db.update_bot_position(
            conn, pid, resolved=1, outcome_correct=None,
            pnl_usd=0.0, settlement_usd=0.0)
        conn.execute(
            "UPDATE bot_positions SET resolved_at=datetime('now') WHERE id=?", (pid,))
    _mock_kalshi(monkeypatch, [
        {"ticker": "KXRELINK-2", "position": 10, "market_exposure": 500},
    ])

    summary, _ = asyncio.run(trader.reconcile_positions_with_kalshi())

    assert summary["resurrected"] == 1
    with db.get_db() as conn:
        assert db.count_open_bot_positions(conn, "paper") == 1


def test_reconcile_does_not_relink_genuinely_settled_row(fresh_db, monkeypatch):
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, _pos(
            signal_id="st", client_order_id="st", ticker="KXSETTLED-1",
            direction="yes", status="filled", filled_contracts=10, cost_usd=5.0))
        db.update_bot_position(
            conn, pid, resolved=1, outcome_correct=0,
            pnl_usd=-5.0, settlement_usd=0.0)
        conn.execute(
            "UPDATE bot_positions SET resolved_at=datetime('now') WHERE id=?", (pid,))
    _mock_kalshi(monkeypatch, [
        {"ticker": "KXSETTLED-1", "position": 10, "market_exposure": 500},
    ])

    summary, _ = asyncio.run(trader.reconcile_positions_with_kalshi())

    assert summary["resurrected"] == 0
    assert summary["imported_unknowns"] == 0
    with db.get_db() as conn:
        row = db.fetch_position_by_id(conn, pid)
        n_rows = conn.execute("SELECT COUNT(*) FROM bot_positions").fetchone()[0]
    assert row["resolved"] == 1
    assert n_rows == 1


def test_c15_partial_exit_counts_residual_cost_only(fresh_db):
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, {
            "asset": "BTC", "series": "KXBTC15M", "ticker": "KXBTC15M-T9",
            "side": "yes", "direction": "yes", "target_contracts": 10,
            "filled_contracts": 10, "entry_limit_cents": 90, "avg_entry_cents": 90,
            "cost_usd": 9.0, "client_order_id": "c15-px", "kalshi_order_id": "E9",
            "status": "filled", "close_time": "", "confidence": 0,
            "entry_delta_usd": 0, "kalshi_env": "paper", "dry_run": 0, "error": None,
        })
        conn.execute(
            "UPDATE crypto15m_positions SET exit_filled_contracts=6, "
            "status='exiting', proceeds_usd=2.4 WHERE id=?", (pid,))
        cost = db.open_crypto15m_filled_cost_usd(conn, "paper")
    assert cost == pytest.approx(3.6)


def test_daily_stop_breach_survives_restart(fresh_db, monkeypatch):
    monkeypatch.setattr(trader, "_DAY_RISK_PERSIST_SEC", 180.0)
    trader._day_risk_breach.clear()
    monkeypatch.setattr(trader, "_today_pnl_balance_delta", lambda env, off=0: -60.0)
    monkeypatch.setattr(db, "open_unrealized_pnl_usd", lambda conn, env: 0.0)
    cfg = _risk_cfg()

    assert trader._is_blocked_by_daily_risk(cfg, "paper")[0] is False
    with db.get_db() as conn:
        assert db.get_risk_breach_start(conn, "paper", "sl") is not None

    trader._day_risk_breach.clear()
    with db.get_db() as conn:
        db.set_risk_breach_start(conn, "paper", "sl", trader.time.time() - 300.0)
    blocked, why = trader._is_blocked_by_daily_risk(cfg, "paper")
    assert blocked is True and "stop-loss" in why

    monkeypatch.setattr(trader, "_today_pnl_balance_delta", lambda env, off=0: +1.0)
    assert trader._is_blocked_by_daily_risk(cfg, "paper")[0] is False
    with db.get_db() as conn:
        assert db.get_risk_breach_start(conn, "paper", "sl") is None
    trader._day_risk_breach.clear()
