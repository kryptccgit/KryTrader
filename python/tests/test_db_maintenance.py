from __future__ import annotations

from datetime import datetime, timezone

import pytest

import db


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "maint.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


_OLD = "2000-01-01 00:00:00"


def _add_trade(c, tid: str, when: str) -> None:
    c.execute(
        "INSERT INTO trades (trade_id,ticker,event_ticker,count_fp,yes_price,"
        "no_price,taker_side,dollar_value,category,created_time) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (tid, "KX", "E", 1.0, 50, 50, "yes", 100.0, "crypto", when),
    )


def test_cleanup_prunes_old_keeps_recent(fresh_db):
    now = _now()
    with db.get_db() as c:
        _add_trade(c, "old1", _OLD)
        _add_trade(c, "old2", _OLD)
        _add_trade(c, "fresh", now)
        c.execute(
            "INSERT INTO market_snapshots (ticker,volume,volume_24h,open_interest,"
            "yes_bid,last_price,snapshot_at) VALUES (?,?,?,?,?,?,?)",
            ("KX", 100, 50, 10, 50, 50, _OLD),
        )
        c.execute(
            "INSERT INTO market_snapshots (ticker,volume,volume_24h,open_interest,"
            "yes_bid,last_price,snapshot_at) VALUES (?,?,?,?,?,?,?)",
            ("KX", 100, 50, 10, 50, 50, now),
        )

    deleted = db.cleanup_old_data()

    with db.get_db() as c:
        trades = [r["trade_id"] for r in c.execute("SELECT trade_id FROM trades")]
        snaps = c.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]
    assert trades == ["fresh"]
    assert snaps == 1
    assert deleted >= 3


def test_batched_delete_clears_a_large_backlog(fresh_db):
    import db as _db
    with db.get_db() as c:
        for i in range(250):
            _add_trade(c, f"t{i}", _OLD)
    n = _db._delete_batched("created_time < ?", (_now(),), "trades", batch=100)
    assert n == 250
    with db.get_db() as c:
        assert c.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0


def test_run_maintenance_compacts_when_forced(fresh_db):
    with db.get_db() as c:
        for i in range(1000):
            _add_trade(c, f"t{i}", _OLD)
    summary = db.run_maintenance(force_vacuum=True)
    assert summary["vacuumed"] is True
    assert summary["deleted"] >= 1000
    with db.get_db() as c:
        assert c.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 0




def test_unresolved_alerts_and_whales_age_out(fresh_db):
    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO alerts (ticker, title, signal_type, direction, price,
                                   confidence, resolved, created_at)
               VALUES ('OLD-A', 't', 'trade_cluster', 'yes', 0.4, 60, 0,
                       datetime('now', '-60 days'))"""
        )
        conn.execute(
            """INSERT INTO whale_trades (trade_id, ticker, title, taker_side,
                                         count_fp, price, dollar_value, confidence,
                                         resolved, created_at)
               VALUES ('OLD-W', 'OLD-W-T', 't', 'yes', 100, 0.5, 5000, 70, 0,
                       datetime('now', '-60 days'))"""
        )
        conn.execute(
            """INSERT INTO alerts (ticker, title, signal_type, direction, price,
                                   confidence, resolved)
               VALUES ('NEW-A', 't', 'trade_cluster', 'yes', 0.4, 60, 0)"""
        )

    db.cleanup_old_data()

    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM alerts WHERE ticker='OLD-A'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM whale_trades WHERE trade_id='OLD-W'").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM alerts WHERE ticker='NEW-A'").fetchone()[0] == 1


def test_events_table_is_pruned(fresh_db):
    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO events (event_ticker, title, last_updated)
               VALUES ('OLD-EV', 'old', datetime('now', '-45 days'))"""
        )
        conn.execute(
            """INSERT INTO events (event_ticker, title, last_updated)
               VALUES ('NEW-EV', 'new', datetime('now'))"""
        )
    db.cleanup_old_data()
    with db.get_db() as conn:
        rows = {r[0] for r in conn.execute("SELECT event_ticker FROM events").fetchall()}
    assert rows == {"NEW-EV"}


def test_pnl_snapshots_query_downsamples(fresh_db):
    with db.get_db() as conn:
        for i in range(500):
            conn.execute(
                """INSERT INTO pnl_snapshots (at, kalshi_env, cash_usd,
                                              portfolio_usd, total_usd)
                   VALUES (datetime('now', ?), 'paper', 100, 0, ?)""",
                (f"-{500 - i} minutes", 100.0 + i),
            )
    with db.get_db() as conn:
        rows = db.get_pnl_snapshots(conn, since_hours=24, env="paper", max_points=100)
    assert 0 < len(rows) <= 101
    assert rows[-1]["total_usd"] == pytest.approx(599.0)
    with db.get_db() as conn:
        rows_1h = db.get_pnl_snapshots(conn, since_hours=1, env="paper", max_points=0)
    assert 55 <= len(rows_1h) <= 62


def test_pnl_prune_keeps_alltime_anchor_snapshot(fresh_db):
    with db.get_db() as c:
        for total, at in [
            (0.0, "-100 days"),
            (200.0, "-99 days"),
            (180.0, "-98 days"),
        ]:
            c.execute(
                "INSERT INTO pnl_snapshots (at, kalshi_env, cash_usd, "
                "portfolio_usd, total_usd) VALUES (datetime('now', ?), 'paper', ?, 0, ?)",
                (at, total, total),
            )
        c.execute(
            "INSERT INTO pnl_snapshots (kalshi_env, cash_usd, portfolio_usd, "
            "total_usd) VALUES ('paper', 120.0, 0, 120.0)",
        )

    db.cleanup_old_data()

    with db.get_db() as c:
        totals = [
            float(r["total_usd"])
            for r in c.execute("SELECT total_usd FROM pnl_snapshots ORDER BY id")
        ]
        earliest = db.earliest_pnl_total(c, "paper")
    assert totals == [200.0, 120.0]
    assert earliest == pytest.approx(200.0)
