from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import backtest
import crypto15m
import crypto15m_record
import db


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "krypt-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


def _sig(fav, fav_price, fav_won, *, entry_cost=None, delta_pct=0.1):
    return {
        "favorite": fav,
        "favorite_price": fav_price,
        "entry_cost": entry_cost if entry_cost is not None else fav_price,
        "fav_won": fav_won,
        "delta_pct": delta_pct,
        "mins_left": 7.0,
    }




def test_favorite_mode_wins_count_as_correct():
    sigs = [_sig("up", 0.8, True), _sig("down", 0.8, True), _sig("up", 0.8, False)]
    r = backtest.crypto15m_eval(sigs, mode="favorite")
    assert r["n"] == 3
    assert r["wins"] == 2
    assert r["avg_cost"] == pytest.approx(0.8)


def test_contrarian_is_the_mirror_image():
    sigs = [_sig("up", 0.8, False)]
    fav = backtest.crypto15m_eval(sigs, mode="favorite")
    con = backtest.crypto15m_eval(sigs, mode="contrarian")
    assert fav["wins"] == 0
    assert con["wins"] == 1
    assert con["avg_cost"] == pytest.approx(0.2)


def test_favorite_price_band_filters():
    sigs = [_sig("up", 0.60, True), _sig("up", 0.90, True)]
    r = backtest.crypto15m_eval(sigs, mode="favorite", min_fav=0.85)
    assert r["n"] == 1


def test_delta_filter_excludes_low_moves():
    sigs = [_sig("up", 0.8, True, delta_pct=0.0005),
            _sig("up", 0.8, True, delta_pct=0.003)]
    r = backtest.crypto15m_eval(sigs, mode="favorite", min_delta_pct=0.20)
    assert r["n"] == 1


def test_delta_filter_drops_none_delta():
    sigs = [_sig("up", 0.8, True, delta_pct=None)]
    assert backtest.crypto15m_eval(sigs, mode="favorite", min_delta_pct=0.1)["n"] == 0


def test_report_structure_and_collecting_verdict():
    sigs = [_sig("up", 0.8, True) for _ in range(5)]
    rep = backtest.crypto15m_report(sigs)
    assert rep["n"] == 5
    assert "favorite" in rep and "contrarian" in rep
    assert len(rep["favoriteSweep"]) == len(backtest._FAV_THRESHOLDS)
    assert "COLLECTING DATA" in rep["verdict"]




def test_settled_up_won_reads_result_and_value():
    assert crypto15m_record._settled_up_won({"result": "yes"}) is True
    assert crypto15m_record._settled_up_won({"result": "no"}) is False
    assert crypto15m_record._settled_up_won(
        {"status": "settled", "settlement_value_dollars": 1.0}) is True
    assert crypto15m_record._settled_up_won(
        {"status": "finalized", "settlement_value": 0}) is False
    assert crypto15m_record._settled_up_won({"status": "active", "result": ""}) is None




def test_signal_db_roundtrip(fresh_db):
    row = {
        "ticker": "KXBTC15M-X", "asset": "BTC", "series": "KXBTC15M",
        "close_time": "2026-06-08T02:45:00Z", "mins_left": 7.0,
        "favorite": "down", "favorite_price": 0.64, "entry_cost": 0.66,
        "up_prob": 0.36, "delta_pct": 0.001, "kalshi_env": "demo",
    }
    with db.get_db() as conn:
        assert db.insert_crypto15m_signal(conn, row) is True
        assert db.insert_crypto15m_signal(conn, row) is False
        counts = db.crypto15m_signal_counts(conn)
        assert counts == {"total": 1, "resolved": 0, "pending": 1}
        assert backtest.load_crypto15m_signals(conn) == []
        db.resolve_crypto15m_signal(conn, "KXBTC15M-X", up_won=0)
        loaded = backtest.load_crypto15m_signals(conn)
    assert len(loaded) == 1
    s = loaded[0]
    assert s["favorite"] == "down" and s["fav_won"] is True
    assert s["entry_cost"] == pytest.approx(0.66)




def test_record_tick_logs_ticks_and_decision_points(fresh_db, monkeypatch):
    close = (datetime.now(timezone.utc) + timedelta(minutes=12)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def asset(name, mins_left):
        return {
            "asset": name, "series": f"KX{name}15M", "hasMarket": True,
            "ticker": f"KX{name}15M-T1", "closeTime": close,
            "minsLeft": mins_left, "favorite": "up", "favoritePrice": 0.7,
            "entryCost": 0.71, "upProb": 0.7, "deltaPct": 0.001,
            "spotUsd": 100.0, "open15mUsd": 99.9,
            "yesBid": 0.69, "yesAsk": 0.71,
        }

    assets = [asset("BTC", 12.0), asset("ETH", 6.0)]

    async def _snap(_cfg):
        return {"assets": assets}
    monkeypatch.setattr(crypto15m, "snapshot", _snap)

    out = asyncio.run(crypto15m_record.record_tick({}))
    assert out["ticks"] == 2
    assert out["captured"] == 1
    with db.get_db() as conn:
        assert db.crypto15m_tick_count(conn) == 2
        tick = dict(conn.execute(
            "SELECT * FROM crypto15m_ticks WHERE asset='BTC'").fetchone())
        assert tick["yes_bid"] == pytest.approx(0.69)
        assert tick["yes_ask"] == pytest.approx(0.71)
        assert tick["spot"] == pytest.approx(100.0)
        sig_assets = [r["asset"] for r in conn.execute(
            "SELECT asset FROM crypto15m_signals").fetchall()]
        assert sig_assets == ["ETH"]

    out = asyncio.run(crypto15m_record.record_tick({}))
    assert out["ticks"] == 2
    assert out["captured"] == 0
    with db.get_db() as conn:
        assert db.crypto15m_tick_count(conn) == 4


def test_cleanup_prunes_old_ticks(fresh_db):
    with db.get_db() as conn:
        db.insert_crypto15m_tick(conn, {"ticker": "T-OLD", "asset": "BTC"})
        db.insert_crypto15m_tick(conn, {"ticker": "T-NEW", "asset": "BTC"})
        old = (datetime.now(timezone.utc)
               - timedelta(days=db._C15_TICKS_KEEP_DAYS + 1)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute("UPDATE crypto15m_ticks SET observed_at=? WHERE ticker='T-OLD'", (old,))
    db.cleanup_old_data()
    with db.get_db() as conn:
        rows = [r["ticker"] for r in conn.execute(
            "SELECT ticker FROM crypto15m_ticks").fetchall()]
    assert rows == ["T-NEW"]
