from __future__ import annotations

import pytest

import db
import scanner


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "conv-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


_seq = 0


def _seed_whale(*, ticker="KXTEST-A", side="yes", price=0.60, dollars=3000.0,
                ago_sql: str = "now") -> int:
    """Insert a whale_trades row `ago_sql` old (SQLite datetime modifier)."""
    global _seq
    _seq += 1
    with db.get_db() as conn:
        wid = db.insert_whale_trade(conn, {
            "trade_id": f"t-{_seq}",
            "ticker": ticker,
            "event_ticker": ticker.rsplit("-", 1)[0],
            "title": f"Test market {ticker}",
            "yes_sub_title": "",
            "category": "sports",
            "taker_side": side,
            "count_fp": dollars / max(price, 0.01),
            "price": price,
            "dollar_value": dollars,
            "market_volume": 50_000,
            "open_interest": 10_000,
            "confidence": 70.0,
        })
        if ago_sql != "now":
            conn.execute(
                "UPDATE whale_trades SET created_at=datetime('now', ?) WHERE id=?",
                (ago_sql, wid),
            )
    return int(wid)


def _build(max_age_sec: int = 120) -> list[dict]:
    with db.get_db() as conn:
        return scanner.build_convergence_signals(conn, max_signal_age_sec=max_age_sec)


def test_three_same_side_whales_build_a_signal(fresh_db):
    _seed_whale(price=0.60, dollars=3000)
    _seed_whale(price=0.62, dollars=4000)
    last = _seed_whale(price=0.64, dollars=5000)

    sigs = _build()
    assert len(sigs) == 1
    s = sigs[0]
    assert s["ticker"] == "KXTEST-A"
    assert s["direction"] == "yes"
    assert s["whale_count"] == 3
    assert s["id"] == last
    assert s["price"] == pytest.approx(0.6233, abs=1e-3)
    assert s["confidence"] == pytest.approx(62.3 + 4.0, abs=0.2)
    assert s["event_ticker"] == "KXTEST"
    assert s["total_usd"] == pytest.approx(12000)


def test_fewer_than_three_whales_is_not_convergence(fresh_db):
    _seed_whale(price=0.60)
    _seed_whale(price=0.62)
    assert _build() == []


def test_opposite_sides_do_not_merge(fresh_db):
    _seed_whale(side="yes")
    _seed_whale(side="yes")
    _seed_whale(side="no")
    _seed_whale(side="no")
    assert _build() == []


def test_stale_group_is_not_fresh(fresh_db):
    for _ in range(3):
        _seed_whale(ago_sql="-30 minutes")
    assert _build(max_age_sec=120) == []
    _seed_whale(price=0.61)
    sigs = _build(max_age_sec=120)
    assert len(sigs) == 1 and sigs[0]["whale_count"] == 4


def test_convergence_score_scales_with_pack_size():
    s3 = scanner.compute_convergence_score(count=3, total_usd=9_000, implied=60)
    s4 = scanner.compute_convergence_score(count=4, total_usd=12_000, implied=60)
    s5 = scanner.compute_convergence_score(count=5, total_usd=15_000, implied=60)
    big = scanner.compute_convergence_score(count=5, total_usd=30_000, implied=60)
    assert s3 == 64.0 and s4 == 66.0 and s5 == 68.0
    assert big == 69.0
    assert scanner.compute_convergence_score(count=9, total_usd=99_000, implied=95) <= 97.0


def test_trade_age_sec_parses_and_fails_open():
    from datetime import datetime, timedelta, timezone
    fresh = (datetime.now(timezone.utc) - timedelta(seconds=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    age = scanner._trade_age_sec({"created_time": fresh})
    assert age is not None and 55 <= age <= 70
    sqlite_fmt = (datetime.now(timezone.utc) - timedelta(seconds=90)).strftime("%Y-%m-%d %H:%M:%S")
    age = scanner._trade_age_sec({"created_time": sqlite_fmt})
    assert age is not None and 85 <= age <= 100
    assert scanner._trade_age_sec({"created_time": ""}) is None
    assert scanner._trade_age_sec({}) is None
    assert scanner._trade_age_sec({"created_time": "not-a-date"}) is None
