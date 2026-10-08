"""The manual ledger, and the wall between the operator and the bot.

Before this, a hand-placed trade was invisible to the app: the 30s reconcile
pass adopted it as an anonymous 'external' position, its P&L landed in the
bot's win rate, and its mark-to-market bleed fed the bot's daily stop-loss —
so a losing manual trade could halt the automation with nothing on screen
saying why. These tests pin the fix from both sides: manual trades ARE
recorded, and they are NOT counted as the bot's.
"""
from __future__ import annotations

import asyncio
import sqlite3

import pytest

import db
import kalshi_auth
import terminal


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    """A real schema on a throwaway file — these are SQL-shape assertions, so a
    fake would only test the fake.

    `db.db_path` is redirected (the project's convention) so the functions that
    open their own connection via `get_db()` hit this file too, not the
    developer's real trading database.
    """
    path = tmp_path / "t.sqlite"
    monkeypatch.setattr(db, "db_path", lambda: path)
    monkeypatch.setattr(kalshi_auth, "get_env", lambda: "paper")

    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    c.commit()
    yield c
    c.close()


def _pos(conn, **over) -> int:
    row = {
        "signal_source": "whale", "signal_id": 1, "ticker": "KXT-1",
        "event_ticker": "KXT", "title": "t", "category": "",
        "direction": "yes", "action": "buy", "target_contracts": 10,
        "limit_price_cents": 40, "filled_contracts": 10,
        "avg_fill_price_cents": 40.0, "cost_usd": 4.0,
        "client_order_id": f"c{over.get('signal_id', 1)}-{over.get('signal_source', 'whale')}",
        "kalshi_order_id": None, "status": "filled", "confidence": 0.0,
        "edge_pts": 0.0, "signal_price": 0.0, "kalshi_env": "paper",
    }
    row.update(over)
    return db.insert_bot_position(conn, row)



def test_manual_positions_do_not_eat_the_bots_open_slots(conn):
    _pos(conn, signal_source="whale", signal_id=1)
    _pos(conn, signal_source="manual", signal_id=2, ticker="KXT-2")
    _pos(conn, signal_source="external", signal_id=3, ticker="KXT-3")
    assert db.count_open_bot_positions(conn, "paper") == 1


def test_manual_pnl_stays_out_of_the_bots_win_rate(conn):
    _pos(conn, signal_source="whale", signal_id=1, resolved=1)
    conn.execute(
        "UPDATE bot_positions SET resolved=1, outcome_correct=1, pnl_usd=6.0, "
        "resolved_at=datetime('now') WHERE signal_source='whale'")
    _pos(conn, signal_source="manual", signal_id=2, ticker="KXT-2")
    conn.execute(
        "UPDATE bot_positions SET resolved=1, outcome_correct=0, pnl_usd=-99.0, "
        "resolved_at=datetime('now') WHERE signal_source='manual'")

    stats = db.aggregate_stats(conn, "paper")
    assert stats["wins"] == 1 and stats["losses"] == 0
    assert stats["realized_pnl"] == 6.0
    assert stats["today_pnl"] == 6.0


def test_a_losing_manual_trade_cannot_trip_the_bots_daily_stop(conn):
    _pos(conn, signal_source="manual", signal_id=1, cost_usd=50.0)
    conn.execute("UPDATE bot_positions SET mark_price_cents=1.0")
    assert db.open_unrealized_pnl_usd(conn, "paper") == 0.0

    _pos(conn, signal_source="momentum", signal_id=2, ticker="KXT-2", cost_usd=4.0)
    conn.execute(
        "UPDATE bot_positions SET mark_price_cents=10.0 WHERE signal_source='momentum'")
    assert db.open_unrealized_pnl_usd(conn, "paper") == pytest.approx(-3.0)


def test_manual_money_still_counts_as_committed_capital(conn):
    _pos(conn, signal_source="manual", signal_id=1, cost_usd=25.0)
    assert db.current_total_exposure_usd(conn, "paper") == pytest.approx(25.0)



def test_manual_positions_query_is_scoped_to_source_and_env(conn):
    _pos(conn, signal_source="manual", signal_id=1, ticker="KXA")
    _pos(conn, signal_source="manual", signal_id=2, ticker="KXB", kalshi_env="production")
    _pos(conn, signal_source="whale", signal_id=3, ticker="KXC")
    rows = db.manual_positions(conn, "paper")
    assert [r["ticker"] for r in rows] == ["KXA"]


def test_finding_the_open_manual_row_is_what_stops_duplicate_positions(conn):
    _pos(conn, signal_source="manual", signal_id=1, ticker="KXA", direction="yes")
    assert db.find_open_manual_position(conn, "KXA", "yes", "paper") is not None
    assert db.find_open_manual_position(conn, "KXA", "no", "paper") is None
    assert db.find_open_manual_position(conn, "KXA", "yes", "production") is None


def test_a_resolved_manual_row_is_not_reused_by_a_later_buy(conn):
    _pos(conn, signal_source="manual", signal_id=1, ticker="KXA")
    conn.execute("UPDATE bot_positions SET resolved=1")
    assert db.find_open_manual_position(conn, "KXA", "yes", "paper") is None


def test_bot_ownership_detects_only_the_engines_own_positions(conn):
    _pos(conn, signal_source="whale", signal_id=1, ticker="KXA", direction="yes")
    _pos(conn, signal_source="manual", signal_id=2, ticker="KXB", direction="yes")
    _pos(conn, signal_source="external", signal_id=3, ticker="KXC", direction="yes")
    assert db.bot_owns_position(conn, "KXA", "yes", "paper") is True
    assert db.bot_owns_position(conn, "KXB", "yes", "paper") is False
    assert db.bot_owns_position(conn, "KXC", "yes", "paper") is False
    assert db.bot_owns_position(conn, "KXA", "no", "paper") is False



def _trade(cents: float, won: bool, *, early: bool = False, pnl: float = 1.0) -> dict:
    return {
        "id": 1, "ticker": "T", "title": None, "side": "yes", "contracts": 1,
        "avgCostCents": cents, "costUsd": cents / 100, "feesUsd": 0.01,
        "status": "filled", "resolved": True, "outcomeCorrect": won,
        "pnlUsd": pnl, "settlementUsd": None, "closedEarly": early,
        "createdAt": None, "resolvedAt": None,
    }


def _buckets(trades: list[dict]) -> dict:
    """Run just the bucketing half of manual_history over supplied trades."""
    calibratable = [t for t in trades if not t["closedEarly"]]
    out = {}
    for lo in range(0, 100, 10):
        inb = [t for t in calibratable if lo <= t["avgCostCents"] < lo + 10]
        wins = sum(1 for t in inb if t["outcomeCorrect"])
        enough = len(inb) >= terminal.MIN_CALIBRATION_TRADES
        out[lo] = {
            "trades": len(inb), "wins": wins,
            "hitRate": round(wins / len(inb), 4) if enough else None,
        }
    return out


def test_a_thin_bucket_prints_no_hit_rate_at_all():
    thin = [_trade(72, True), _trade(75, False), _trade(78, True)]
    assert _buckets(thin)[70]["hitRate"] is None
    assert _buckets(thin)[70]["trades"] == 3


def test_a_bucket_at_the_minimum_reports_its_rate():
    fat = [_trade(70 + i, i < 4) for i in range(terminal.MIN_CALIBRATION_TRADES)]
    b = _buckets(fat)[70]
    assert b["trades"] == terminal.MIN_CALIBRATION_TRADES
    assert b["hitRate"] == pytest.approx(4 / terminal.MIN_CALIBRATION_TRADES)


def test_sold_out_trades_are_excluded_from_calibration():
    trades = [_trade(50, True, early=True) for _ in range(9)]
    assert _buckets(trades)[50]["trades"] == 0


def test_buckets_partition_the_whole_price_range_without_overlap():
    edges = [_trade(c, True) for c in (0.5, 9.9, 10.0, 49.9, 50.0, 98.9)]
    counts = _buckets(edges)
    assert sum(b["trades"] for b in counts.values()) == len(edges)
    assert counts[0]["trades"] == 2 and counts[10]["trades"] == 1
    assert counts[40]["trades"] == 1 and counts[50]["trades"] == 1
    assert counts[90]["trades"] == 1


def test_the_manual_signal_id_is_collision_resistant():
    ids = {terminal._manual_signal_id("KXA", "yes") for _ in range(200)}
    assert len(ids) == 200
    assert all(0 <= i < 2_000_000_000 for i in ids)



def _buy(**over) -> int | None:
    args = dict(
        ticker="KXA-1", side="yes", count=10, price_cents=40.0,
        client_order_id="krypt-term-abc", order_id="ord-1", status="resting",
        filled=10, avg_cents=40.0, fees_usd=0.17, title="A market",
        event_ticker="KXA", category="Sports",
    )
    args.update(over)
    return terminal.record_manual_buy(**args)


def test_a_manual_buy_claims_the_ticker_so_the_reconciler_leaves_it_alone(conn):
    pid = _buy()
    assert pid is not None
    assert db.find_open_manual_position(conn, "KXA-1", "yes", "paper") is not None

    row = db.fetch_position_by_id(conn, pid)
    assert row["signal_source"] == "manual"
    assert row["ticker"] == "KXA-1" and row["direction"] == "yes"
    assert row["filled_contracts"] == 10
    assert row["cost_usd"] == pytest.approx(4.0)
    assert row["title"] == "A market" and row["category"] == "Sports"


def test_a_second_buy_on_the_same_side_adds_to_the_row_rather_than_duplicating(conn):
    first = _buy()
    second = _buy(client_order_id="krypt-term-def", order_id="ord-2", count=5, filled=5)
    assert first == second
    rows = db.manual_positions(conn, "paper")
    assert len(rows) == 1
    assert rows[0]["target_contracts"] == 15
    assert rows[0]["filled_contracts"] == 15


def test_the_other_side_of_the_same_market_is_a_separate_position(conn):
    _buy(side="yes")
    other = _buy(side="no", client_order_id="krypt-term-no", order_id="ord-3")
    assert other is not None
    assert len(db.manual_positions(conn, "paper")) == 2


def test_a_sub_cent_limit_is_preserved_somewhere_readable(conn):
    pid = _buy(price_cents=0.4, filled=0, avg_cents=None)
    row = db.fetch_position_by_id(conn, pid)
    assert row["signal_price"] == pytest.approx(0.4)


def test_a_deci_cent_fill_price_is_stored_exactly(conn):
    pid = _buy(price_cents=1.1, filled=10, avg_cents=1.1)
    assert db.fetch_position_by_id(conn, pid)["avg_fill_price_cents"] == pytest.approx(1.1)


def test_an_unfilled_buy_is_recorded_as_resting_not_as_filled(conn):
    pid = _buy(filled=0, avg_cents=None, fees_usd=None)
    row = db.fetch_position_by_id(conn, pid)
    assert row["status"] == "submitted"
    assert row["filled_contracts"] == 0
    assert row["cost_usd"] == pytest.approx(0.0)


def _sell(monkeypatch, *, sold, avg_cents, **over):
    """Run a manual sell with the venue's fill ledger stubbed."""
    async def fake_fills(order_id, side, pin_env=None):
        return sold, avg_cents
    monkeypatch.setattr(terminal, "_reconcile_fills", fake_fills)
    args = dict(ticker="KXA-1", side="yes", count=sold or 0, price_cents=55.0,
                order_id="ord-9", status="executed", filled=sold)
    args.update(over)
    return asyncio.run(terminal.record_manual_sell(**args))


def test_a_full_sale_books_its_proceeds_and_resolves_the_row(conn, monkeypatch):
    pid = _buy()
    _sell(monkeypatch, sold=10, avg_cents=80.0)

    row = db.fetch_position_by_id(conn, pid)
    assert row["resolved"] == 1
    assert row["closed_early"] == 1
    assert row["settlement_usd"] == pytest.approx(8.0)
    exit_fee = terminal._fee_usd(80.0, 10)
    assert row["pnl_usd"] == pytest.approx(8.0 - 4.0 - 0.17 - exit_fee)
    assert row["pnl_usd"] > 0
    assert row["outcome_correct"] is None


def test_a_full_sale_is_priced_off_fills_not_off_the_limit(conn, monkeypatch):
    pid = _buy()
    _sell(monkeypatch, sold=10, avg_cents=70.0, price_cents=90.0)
    assert db.fetch_position_by_id(conn, pid)["settlement_usd"] == pytest.approx(7.0)


def test_a_sale_whose_fills_cannot_be_read_leaves_pnl_unknown(conn, monkeypatch):
    pid = _buy()
    _sell(monkeypatch, sold=None, avg_cents=None)
    row = db.fetch_position_by_id(conn, pid)
    assert row["pnl_usd"] is None
    assert row["settlement_usd"] is None


def test_a_partial_sale_shrinks_the_position_and_its_basis(conn, monkeypatch):
    pid = _buy()
    _sell(monkeypatch, sold=4, avg_cents=60.0)

    row = db.fetch_position_by_id(conn, pid)
    assert row["resolved"] == 0
    assert row["closed_early"] == 0
    assert row["filled_contracts"] == 6
    assert row["cost_usd"] == pytest.approx(2.4)
    assert row["target_contracts"] == 6


def test_selling_something_the_terminal_never_bought_is_not_an_error(conn, monkeypatch):
    _sell(monkeypatch, sold=1, avg_cents=50.0, ticker="KXZ-9")
    assert db.manual_positions(conn, "paper") == []


def test_a_sold_out_position_is_invisible_to_the_bots_orphan_close(conn, monkeypatch):
    pid = _buy()
    _sell(monkeypatch, sold=10, avg_cents=80.0)
    unresolved = db.get_unresolved_bot_positions(conn)
    assert pid not in [r["id"] for r in unresolved]


def test_history_reports_unknowns_rather_than_zeros(conn):
    _buy(filled=0, avg_cents=None, fees_usd=None)
    h = terminal.manual_history()
    assert h["closedCount"] == 0 and h["openCount"] == 1
    assert h["winRate"] is None
    assert h["realizedUsd"] is None
    t = h["trades"][0]
    assert t["avgCostCents"] is None
    assert t["outcomeCorrect"] is None


def test_history_scores_a_settled_trade(conn):
    pid = _buy()
    with db.get_db() as c:
        db.update_bot_position(
            c, pid, resolved=1, outcome_correct=1, pnl_usd=5.83,
            settlement_usd=10.0, resolved_at="2026-08-24 12:00:00",
        )
    h = terminal.manual_history()
    assert h["closedCount"] == 1 and h["wins"] == 1 and h["losses"] == 0
    assert h["winRate"] == 1.0
    assert h["realizedUsd"] == pytest.approx(5.83)
    bucket = next(b for b in h["buckets"] if b["loCents"] == 40)
    assert bucket["trades"] == 1
    assert bucket["hitRate"] is None
    assert "more settled trade" in bucket["note"]
    assert bucket["impliedRate"] == pytest.approx(0.40)


def test_history_is_scoped_to_the_active_environment(conn):
    _buy()
    with db.get_db() as c:
        c.execute("UPDATE bot_positions SET kalshi_env='production'")
    assert terminal.manual_history()["trades"] == []
