from __future__ import annotations

import asyncio
import itertools

import pytest

import db
import trader
from config import merge_with_defaults
from kalshi_api import KalshiAPIError




@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "krypt-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


@pytest.fixture
def env_demo(monkeypatch):
    monkeypatch.setattr(trader, "get_env", lambda: "demo")
    return "demo"


@pytest.fixture
def cfg():
    c = merge_with_defaults({})
    c["kalshi_env"] = "demo"
    return c


def run_async(coro):
    return asyncio.run(coro)


_ids = itertools.count(1)


def seed_position(**over) -> int:
    n = next(_ids)
    row = {
        "signal_source": over.get("signal_source", "whale"),
        "signal_id": over.get("signal_id", n),
        "ticker": over.get("ticker", f"TCK-{n}"),
        "event_ticker": over.get("event_ticker", ""),
        "direction": over.get("direction", "yes"),
        "target_contracts": over.get("target_contracts", 10),
        "limit_price_cents": over.get("limit_price_cents", 50),
        "filled_contracts": over.get("filled_contracts", 0),
        "cost_usd": over.get("cost_usd", 0.0),
        "client_order_id": over.get("client_order_id", f"co-{n}"),
        "kalshi_order_id": over.get("kalshi_order_id"),
        "status": over.get("status", "filled"),
        "kalshi_env": over.get("kalshi_env", "demo"),
    }
    with db.get_db() as conn:
        pid = db.insert_bot_position(conn, row)
        if "created_at_offset_sec" in over:
            conn.execute(
                "UPDATE bot_positions SET created_at=datetime('now', ?) WHERE id=?",
                (f"{int(over['created_at_offset_sec'])} seconds", pid),
            )
    return pid


def whale_signal(**over) -> dict:
    s = {
        "id": 1, "ticker": "WHALE-1", "event_ticker": "", "title": "t",
        "category": "sports", "price": 0.60, "confidence": 80.0,
        "taker_side": "yes",
    }
    s.update(over)
    return s


def count_rows() -> int:
    with db.get_db() as conn:
        return conn.execute("SELECT COUNT(*) FROM bot_positions").fetchone()[0]


def fetch(pid: int) -> dict:
    with db.get_db() as conn:
        return db.fetch_position_by_id(conn, pid)


async def _stub_empty_book(_ticker):
    return {}




def test_execute_skips_when_max_open_positions_hit(fresh_db, env_demo, cfg):
    cfg["max_open_positions"] = 1
    seed_position(status="filled")
    result = run_async(
        trader.execute_signal(whale_signal(id=100, ticker="NEW"), "whale", cfg, 1000.0)
    )
    assert result is None
    assert count_rows() == 1


def test_execute_skips_when_daily_cap_hit(fresh_db, env_demo, cfg):
    cfg["max_open_positions"] = 100
    cfg["unlimited_daily_new_positions"] = False
    cfg["max_daily_new_positions"] = 2
    seed_position(status="filled")
    seed_position(status="filled")
    result = run_async(
        trader.execute_signal(whale_signal(id=101, ticker="NEW"), "whale", cfg, 1000.0)
    )
    assert result is None
    assert count_rows() == 2


def test_daily_cap_counts_only_real_positions(fresh_db, env_demo):
    for st in ("submitted", "partial", "filled"):
        seed_position(status=st)
    for st in ("canceled", "error", "gone", "expired", "dry_run"):
        seed_position(status=st)
        seed_position(status=st)
    with db.get_db() as conn:
        assert db.count_new_positions_today(conn, "demo") == 3


def test_daily_cap_excludes_external_and_prior_days(fresh_db, env_demo):
    seed_position(status="filled")
    seed_position(status="filled", signal_source="external")
    seed_position(status="filled", created_at_offset_sec=-90000)
    with db.get_db() as conn:
        assert db.count_new_positions_today(conn, "demo") == 1


def test_daily_cap_not_saturated_by_dead_rows(fresh_db, env_demo, cfg):
    cfg["max_open_positions"] = 100
    cfg["unlimited_daily_new_positions"] = False
    cfg["max_daily_new_positions"] = 2
    for st in ("canceled", "error", "gone", "canceled", "error"):
        seed_position(status=st)
    with db.get_db() as conn:
        today = db.count_new_positions_today(conn, "demo")
    assert today == 0
    assert today < cfg["max_daily_new_positions"]


def test_execute_skips_second_position_in_same_event(fresh_db, env_demo, cfg):
    cfg["max_positions_per_event"] = 1
    seed_position(status="filled", event_ticker="EVT-A", ticker="A-1")
    result = run_async(
        trader.execute_signal(
            whale_signal(id=102, ticker="A-2", event_ticker="EVT-A"),
            "whale", cfg, 1000.0,
        )
    )
    assert result is None


def test_execute_skips_duplicate_market_and_side(fresh_db, env_demo, cfg):
    seed_position(status="filled", ticker="DUP", direction="yes")
    result = run_async(
        trader.execute_signal(
            whale_signal(id=103, ticker="DUP", taker_side="yes"), "whale", cfg, 1000.0
        )
    )
    assert result is None


def test_execute_skips_when_exposure_leaves_under_one_dollar(fresh_db, env_demo, cfg):
    seed_position(status="filled", ticker="EXP-SEED", cost_usd=749.50)
    result = run_async(
        trader.execute_signal(
            whale_signal(id=104, ticker="EXP-NEW"), "whale", cfg, 1000.0
        )
    )
    assert result is None
    assert count_rows() == 1




def test_execute_skips_when_trading_disabled(fresh_db, env_demo, cfg, monkeypatch):
    cfg["enable_trading"] = False
    monkeypatch.setattr(trader, "get_orderbook", _stub_empty_book)

    def _boom(**_kw):
        raise AssertionError("place_limit_order must not be called when trading is disabled")

    monkeypatch.setattr(trader, "place_limit_order", _boom)

    row = run_async(
        trader.execute_signal(whale_signal(id=200, ticker="OFF"), "whale", cfg, 1000.0)
    )
    assert row is None
    assert count_rows() == 0


def test_execute_real_order_records_kalshi_order_id(fresh_db, env_demo, cfg, monkeypatch):
    cfg["enable_trading"] = True
    monkeypatch.setattr(trader, "get_orderbook", _stub_empty_book)

    calls: list[dict] = []

    async def _place(**kw):
        calls.append(kw)
        return {"order": {"order_id": "OID-1", "status": "resting"}}

    monkeypatch.setattr(trader, "place_limit_order", _place)

    row = run_async(
        trader.execute_signal(whale_signal(id=201, ticker="LIVE"), "whale", cfg, 1000.0)
    )
    assert row["status"] == "submitted"
    assert row["kalshi_order_id"] == "OID-1"
    assert len(calls) == 1
    assert calls[0]["count"] == 80
    assert calls[0]["price_cents"] == 62
    assert calls[0]["side"] == "yes"
    assert calls[0]["action"] == "buy"


def test_execute_api_error_is_persisted_as_error_row(fresh_db, env_demo, cfg, monkeypatch):
    cfg["enable_trading"] = True
    monkeypatch.setattr(trader, "get_orderbook", _stub_empty_book)

    async def _place(**_kw):
        raise KalshiAPIError(400, {"error": "insufficient_balance"})

    monkeypatch.setattr(trader, "place_limit_order", _place)

    row = run_async(
        trader.execute_signal(whale_signal(id=202, ticker="BAD"), "whale", cfg, 1000.0)
    )
    assert row["status"] == "error"
    assert "HTTP 400" in row["error"]
    assert row["kalshi_order_id"] is None


def test_execute_skips_when_live_cross_exceeds_entry_cap(fresh_db, env_demo, cfg, monkeypatch):
    cfg["enable_trading"] = True

    async def _moved_book(_ticker):
        return {"no": [[5, 100]]}

    monkeypatch.setattr(trader, "get_orderbook", _moved_book)

    def _boom(**_kw):
        raise AssertionError("place_limit_order must not be called above the cap")

    monkeypatch.setattr(trader, "place_limit_order", _boom)

    row = run_async(
        trader.execute_signal(whale_signal(id=203, ticker="MOVED"), "whale", cfg, 1000.0)
    )
    assert row is None
    assert count_rows() == 0




def test_poll_marks_order_filled_from_order_endpoint(fresh_db, env_demo, cfg, monkeypatch):
    trader._poll_failures.clear()
    pid = seed_position(status="submitted", kalshi_order_id="OID-9",
                        target_contracts=5, cost_usd=0.0)

    async def _no_positions(*_a, **_k):
        return []

    async def _get_order(_oid):
        return {"order": {
            "status": "executed", "taker_fill_count": 5, "maker_fill_count": 0,
            "taker_fill_cost": 300, "maker_fill_cost": 0,
            "place_count": 5, "remaining_count": 0,
        }}

    monkeypatch.setattr(trader, "get_positions", _no_positions)
    monkeypatch.setattr(trader, "get_order", _get_order)

    updated = run_async(trader.poll_open_orders(cfg))
    assert len(updated) == 1
    row = fetch(pid)
    assert row["status"] == "filled"
    assert row["filled_contracts"] == 5
    assert row["cost_usd"] == pytest.approx(3.0)
    assert row["avg_fill_price_cents"] == pytest.approx(60.0)


def test_poll_canceled_partial_collapses_target_and_exposure(fresh_db, env_demo, cfg, monkeypatch):
    trader._poll_failures.clear()
    pid = seed_position(status="submitted", kalshi_order_id="OID-CP",
                        target_contracts=5, limit_price_cents=50)

    async def _no_positions(*_a, **_k):
        return []

    async def _canceled_partial(_oid):
        return {"order": {
            "status": "canceled", "taker_fill_count": 2, "maker_fill_count": 0,
            "taker_fill_cost": 100, "maker_fill_cost": 0,
            "place_count": 5, "remaining_count": 3,
        }}

    monkeypatch.setattr(trader, "get_positions", _no_positions)
    monkeypatch.setattr(trader, "get_order", _canceled_partial)

    run_async(trader.poll_open_orders(cfg))
    row = fetch(pid)
    assert row["status"] == "partial"
    assert row["filled_contracts"] == 2
    assert row["target_contracts"] == 2
    with db.get_db() as conn:
        exposure = db.current_total_exposure_usd(conn, "demo")
    assert exposure == pytest.approx(1.0)


def test_poll_resting_partial_keeps_full_committed_exposure(fresh_db, env_demo, cfg, monkeypatch):
    trader._poll_failures.clear()
    pid = seed_position(status="submitted", kalshi_order_id="OID-RP",
                        target_contracts=5, limit_price_cents=50)

    async def _no_positions(*_a, **_k):
        return []

    async def _resting_partial(_oid):
        return {"order": {
            "status": "resting", "taker_fill_count": 2, "maker_fill_count": 0,
            "taker_fill_cost": 100, "maker_fill_cost": 0,
            "place_count": 5, "remaining_count": 3,
        }}

    monkeypatch.setattr(trader, "get_positions", _no_positions)
    monkeypatch.setattr(trader, "get_order", _resting_partial)

    run_async(trader.poll_open_orders(cfg))
    row = fetch(pid)
    assert row["status"] == "partial"
    assert row["target_contracts"] == 5
    with db.get_db() as conn:
        exposure = db.current_total_exposure_usd(conn, "demo")
    assert exposure == pytest.approx(2.5)


def test_poll_retires_order_to_gone_only_after_threshold(fresh_db, env_demo, cfg, monkeypatch):
    trader._poll_failures.clear()
    pid = seed_position(status="submitted", kalshi_order_id="OID-10",
                        target_contracts=5)

    async def _no_positions(*_a, **_k):
        return []

    async def _get_order_404(_oid):
        raise KalshiAPIError(404, "not found")

    monkeypatch.setattr(trader, "get_positions", _no_positions)
    monkeypatch.setattr(trader, "get_order", _get_order_404)

    run_async(trader.poll_open_orders(cfg))
    assert fetch(pid)["status"] == "submitted"

    for _ in range(5):
        run_async(trader.poll_open_orders(cfg))
    assert fetch(pid)["status"] == "gone"


def test_poll_auto_cancels_stale_resting_order(fresh_db, env_demo, cfg, monkeypatch):
    trader._poll_failures.clear()
    cfg["order_expiration_sec"] = 90
    pid = seed_position(status="submitted", kalshi_order_id="OID-11",
                        target_contracts=5, created_at_offset_sec=-200)

    async def _no_positions(*_a, **_k):
        return []

    async def _resting(_oid):
        return {"order": {
            "status": "resting", "taker_fill_count": 0, "maker_fill_count": 0,
            "taker_fill_cost": 0, "maker_fill_cost": 0,
            "place_count": 5, "remaining_count": 5,
        }}

    cancels: list[str] = []

    async def _cancel(oid, **_kw):
        cancels.append(oid)
        return {}

    monkeypatch.setattr(trader, "get_positions", _no_positions)
    monkeypatch.setattr(trader, "get_order", _resting)
    monkeypatch.setattr(trader, "cancel_order", _cancel)

    run_async(trader.poll_open_orders(cfg))
    assert cancels == ["OID-11"]
    assert fetch(pid)["status"] == "canceled"




def _settled_market(result: str):
    async def _fetch(_ticker):
        return {"result": result, "status": "finalized"}
    return _fetch


def test_resolve_winning_yes_position(fresh_db, env_demo, cfg, monkeypatch):
    pid = seed_position(status="filled", ticker="RES-WIN", direction="yes",
                        filled_contracts=10, cost_usd=6.0)
    monkeypatch.setattr(trader, "fetch_market", _settled_market("yes"))

    updated = run_async(trader.mark_resolved_positions(cfg))
    assert len(updated) == 1
    row = fetch(pid)
    assert bool(row["resolved"]) is True
    assert row["outcome_correct"] == 1
    assert row["settlement_usd"] == pytest.approx(10.0)
    assert row["pnl_usd"] == pytest.approx(4.0)


def test_resolve_losing_no_position(fresh_db, env_demo, cfg, monkeypatch):
    pid = seed_position(status="filled", ticker="RES-LOSS", direction="no",
                        filled_contracts=10, cost_usd=4.0)
    monkeypatch.setattr(trader, "fetch_market", _settled_market("yes"))

    run_async(trader.mark_resolved_positions(cfg))
    row = fetch(pid)
    assert row["outcome_correct"] == 0
    assert row["settlement_usd"] == pytest.approx(0.0)
    assert row["pnl_usd"] == pytest.approx(-4.0)


def test_resolve_no_fill_row_closes_at_zero_with_null_outcome(fresh_db, env_demo, cfg):
    pid = seed_position(status="canceled", ticker="RES-NOFILL",
                        filled_contracts=0, cost_usd=0.0)
    run_async(trader.mark_resolved_positions(cfg))
    row = fetch(pid)
    assert bool(row["resolved"]) is True
    assert row["outcome_correct"] is None
    assert row["pnl_usd"] == pytest.approx(0.0)


def test_resolve_clamps_pnl_to_physical_bounds(fresh_db, env_demo, cfg, monkeypatch):
    pid = seed_position(status="filled", ticker="CLAMP", direction="yes",
                        filled_contracts=10, cost_usd=6.0)
    monkeypatch.setattr(trader, "fetch_market", _settled_market("yes"))
    monkeypatch.setattr(trader, "_market_yes_payout", lambda _m: 5.0)

    run_async(trader.mark_resolved_positions(cfg))
    row = fetch(pid)
    assert row["pnl_usd"] == pytest.approx(4.0)
    assert row["settlement_usd"] == pytest.approx(10.0)





def test_execute_duplicate_coid_rejection_adopts_live_order(fresh_db, env_demo, cfg, monkeypatch):
    cfg["enable_trading"] = True
    monkeypatch.setattr(trader, "get_orderbook", _stub_empty_book)

    async def _place(**_kw):
        raise KalshiAPIError(400, {"error": {
            "code": "duplicate_client_order_id",
            "message": "an order with this client_order_id already exists",
        }})

    async def _find(coid, ticker="", pin_env=None):
        return {"order_id": "OID-DUP", "status": "resting"}

    monkeypatch.setattr(trader, "place_limit_order", _place)
    monkeypatch.setattr(trader, "find_order_by_client_id", _find)

    row = run_async(
        trader.execute_signal(whale_signal(id=301, ticker="DUP-COID"), "whale", cfg, 1000.0)
    )
    assert row["status"] == "submitted"
    assert row["kalshi_order_id"] == "OID-DUP"
    with db.get_db() as conn:
        assert db.count_open_bot_positions(conn, "demo") == 1


def test_execute_duplicate_coid_but_lookup_misses_books_error(fresh_db, env_demo, cfg, monkeypatch):
    cfg["enable_trading"] = True
    monkeypatch.setattr(trader, "get_orderbook", _stub_empty_book)

    async def _place(**_kw):
        raise KalshiAPIError(400, {"error": {
            "code": "duplicate_client_order_id",
            "message": "an order with this client_order_id already exists",
        }})

    async def _find(coid, ticker="", pin_env=None):
        return None

    monkeypatch.setattr(trader, "place_limit_order", _place)
    monkeypatch.setattr(trader, "find_order_by_client_id", _find)

    row = run_async(
        trader.execute_signal(whale_signal(id=302, ticker="DUP-MISS"), "whale", cfg, 1000.0)
    )
    assert row["status"] == "error"


def test_execute_env_flip_books_unconfirmed_not_error(fresh_db, env_demo, cfg, monkeypatch):
    cfg["enable_trading"] = True
    monkeypatch.setattr(trader, "get_orderbook", _stub_empty_book)

    env_now = {"v": "demo"}
    monkeypatch.setattr(trader, "get_env", lambda: env_now["v"])

    async def _place(**_kw):
        env_now["v"] = "prod"
        raise KalshiAPIError(409, {"error": {
            "code": "env_changed",
            "message": "environment switched mid-request; aborted",
        }})

    async def _find(coid, ticker="", pin_env=None):
        raise AssertionError("lookup must not run against the wrong env")

    monkeypatch.setattr(trader, "place_limit_order", _place)
    monkeypatch.setattr(trader, "find_order_by_client_id", _find)

    row = run_async(
        trader.execute_signal(whale_signal(id=303, ticker="ENV-FLIP"), "whale", cfg, 1000.0)
    )
    assert row["status"] == "submitted"
    assert row["kalshi_order_id"] is None
    assert "UNCONFIRMED" in (row["error"] or "")
    with db.get_db() as conn:
        assert db.count_open_bot_positions(conn, "demo") == 1


def test_cancel_all_books_raced_partial_fill(fresh_db, env_demo, monkeypatch):
    pid = seed_position(status="submitted", kalshi_order_id="OID-CA1",
                        target_contracts=5, limit_price_cents=50)

    async def _cancel(_oid, **_kw):
        return {}

    async def _order(_oid):
        return {"order": {
            "status": "canceled", "taker_fill_count": 2, "maker_fill_count": 0,
            "taker_fill_cost": 100, "maker_fill_cost": 0,
            "place_count": 5, "remaining_count": 0,
        }}

    monkeypatch.setattr(trader, "cancel_order", _cancel)
    monkeypatch.setattr(trader, "get_order", _order)

    n = run_async(trader.cancel_all_open())
    assert n == 1
    row = fetch(pid)
    assert row["status"] == "partial"
    assert row["filled_contracts"] == 2
    assert row["target_contracts"] == 2
    assert row["cost_usd"] == pytest.approx(1.0)
    with db.get_db() as conn:
        assert db.count_open_bot_positions(conn, "demo") == 1


def test_cancel_all_confirmed_zero_fill_books_canceled(fresh_db, env_demo, monkeypatch):
    pid = seed_position(status="submitted", kalshi_order_id="OID-CA2",
                        target_contracts=5)

    async def _cancel(_oid, **_kw):
        return {}

    async def _order(_oid):
        return {"order": {
            "status": "canceled", "taker_fill_count": 0, "maker_fill_count": 0,
            "taker_fill_cost": 0, "maker_fill_cost": 0,
            "place_count": 5, "remaining_count": 5,
        }}

    monkeypatch.setattr(trader, "cancel_order", _cancel)
    monkeypatch.setattr(trader, "get_order", _order)

    n = run_async(trader.cancel_all_open())
    assert n == 1
    assert fetch(pid)["status"] == "canceled"


def test_cancel_all_unconfirmed_read_leaves_row_for_poll(fresh_db, env_demo, monkeypatch):
    pid = seed_position(status="submitted", kalshi_order_id="OID-CA3",
                        target_contracts=5)

    async def _cancel(_oid, **_kw):
        return {}

    async def _order(_oid):
        raise KalshiAPIError(500, "boom")

    monkeypatch.setattr(trader, "cancel_order", _cancel)
    monkeypatch.setattr(trader, "get_order", _order)

    n = run_async(trader.cancel_all_open())
    assert n == 1
    assert fetch(pid)["status"] == "submitted"


def test_poll_reentrancy_guard_skips_concurrent_run(fresh_db, env_demo, cfg, monkeypatch):
    def _boom(conn, env=None):
        raise AssertionError("a second poll ran while one was active")

    monkeypatch.setattr(db, "get_pending_bot_positions", _boom)
    trader._poll_orders_active = True
    try:
        assert run_async(trader.poll_open_orders(cfg)) == []
    finally:
        trader._poll_orders_active = False


def test_poll_cancel_404_rereads_fills_before_gone(fresh_db, env_demo, cfg, monkeypatch):
    trader._poll_failures.clear()
    cfg["order_expiration_sec"] = 90
    pid = seed_position(status="submitted", kalshi_order_id="OID-R404",
                        target_contracts=5, created_at_offset_sec=-200)

    async def _no_positions(*_a, **_k):
        return []

    calls = {"n": 0}

    async def _order(_oid):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"order": {
                "status": "resting", "taker_fill_count": 0, "maker_fill_count": 0,
                "taker_fill_cost": 0, "maker_fill_cost": 0,
                "place_count": 5, "remaining_count": 5,
            }}
        return {"order": {
            "status": "executed", "taker_fill_count": 5, "maker_fill_count": 0,
            "taker_fill_cost": 300, "maker_fill_cost": 0,
            "place_count": 5, "remaining_count": 0,
        }}

    async def _cancel_404(_oid, **_kw):
        raise KalshiAPIError(404, "order not found")

    monkeypatch.setattr(trader, "get_positions", _no_positions)
    monkeypatch.setattr(trader, "get_order", _order)
    monkeypatch.setattr(trader, "cancel_order", _cancel_404)

    run_async(trader.poll_open_orders(cfg))
    assert fetch(pid)["status"] == "submitted"


def test_poll_cancel_404_with_order_truly_unknown_books_gone(fresh_db, env_demo, cfg, monkeypatch):
    trader._poll_failures.clear()
    cfg["order_expiration_sec"] = 90
    pid = seed_position(status="submitted", kalshi_order_id="OID-R404B",
                        target_contracts=5, created_at_offset_sec=-200)

    async def _no_positions(*_a, **_k):
        return []

    calls = {"n": 0}

    async def _order(_oid):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"order": {
                "status": "resting", "taker_fill_count": 0, "maker_fill_count": 0,
                "taker_fill_cost": 0, "maker_fill_cost": 0,
                "place_count": 5, "remaining_count": 5,
            }}
        raise KalshiAPIError(404, "not found")

    async def _cancel_404(_oid, **_kw):
        raise KalshiAPIError(404, "order not found")

    monkeypatch.setattr(trader, "get_positions", _no_positions)
    monkeypatch.setattr(trader, "get_order", _order)
    monkeypatch.setattr(trader, "cancel_order", _cancel_404)

    run_async(trader.poll_open_orders(cfg))
    assert fetch(pid)["status"] == "gone"


def test_poll_network_failures_do_not_feed_giveup_counter(fresh_db, env_demo, cfg, monkeypatch):
    trader._poll_failures.clear()
    pid_nokid = seed_position(status="submitted", kalshi_order_id=None,
                              target_contracts=5)
    pid_kid = seed_position(status="submitted", kalshi_order_id="OID-NET",
                            target_contracts=5)

    async def _net_down(*_a, **_k):
        raise OSError("network unreachable")

    monkeypatch.setattr(trader, "get_positions", _net_down)
    monkeypatch.setattr(trader, "find_order_by_client_id", _net_down)
    monkeypatch.setattr(trader, "get_order", _net_down)

    for _ in range(8):
        run_async(trader.poll_open_orders(cfg))

    assert fetch(pid_nokid)["status"] == "submitted"
    assert fetch(pid_kid)["status"] == "submitted"


def test_poll_confirmed_coid_miss_still_gives_up(fresh_db, env_demo, cfg, monkeypatch):
    trader._poll_failures.clear()
    pid = seed_position(status="submitted", kalshi_order_id=None,
                        target_contracts=5)

    async def _no_positions(*_a, **_k):
        return []

    async def _find_none(coid, ticker=""):
        return None

    monkeypatch.setattr(trader, "get_positions", _no_positions)
    monkeypatch.setattr(trader, "find_order_by_client_id", _find_none)

    for _ in range(6):
        run_async(trader.poll_open_orders(cfg))
    assert fetch(pid)["status"] == "gone"


def test_resolve_defers_fresh_gone_rows_to_poll_window(fresh_db, env_demo, cfg):
    pid = seed_position(status="gone", filled_contracts=0, cost_usd=0.0)

    run_async(trader.mark_resolved_positions(cfg))
    assert fetch(pid)["resolved"] == 0

    with db.get_db() as conn:
        conn.execute(
            "UPDATE bot_positions SET created_at=datetime('now','-25 hours') WHERE id=?",
            (pid,))
    run_async(trader.mark_resolved_positions(cfg))
    assert fetch(pid)["resolved"] == 1


def test_pending_query_is_env_scoped(fresh_db):
    seed_position(status="submitted", kalshi_order_id="OID-D1", kalshi_env="demo")
    seed_position(status="submitted", kalshi_order_id="OID-P1", kalshi_env="production")
    with db.get_db() as conn:
        demo = db.get_pending_bot_positions(conn, "demo")
        both = db.get_pending_bot_positions(conn)
    assert [r["kalshi_order_id"] for r in demo] == ["OID-D1"]
    assert len(both) == 2


def test_refresh_balance_is_per_env(monkeypatch):
    trader._balance_cache.clear()

    async def fake_balance(*a, **k):
        if trader.get_env() == "demo":
            return {"balance": 1000, "portfolio_value": 100}
        return {"balance": 5000, "portfolio_value": 500}

    monkeypatch.setattr(trader, "get_balance", fake_balance)
    cfg = {"balance_poll_interval": 60}

    monkeypatch.setattr(trader, "get_env", lambda: "demo")
    assert run_async(trader.refresh_balance(cfg, force=True)) == (1000, 100)

    monkeypatch.setattr(trader, "get_env", lambda: "production")
    assert run_async(trader.refresh_balance(cfg, force=True)) == (5000, 500)

    monkeypatch.setattr(trader, "get_env", lambda: "demo")
    assert run_async(trader.refresh_balance(cfg, force=False)) == (1000, 100)
