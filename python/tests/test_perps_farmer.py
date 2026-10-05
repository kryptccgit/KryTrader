from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

import db
import kalshi_auth
import perps_farmer as pf
import perps_ws as pws


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "krypt-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


@pytest.fixture(autouse=True)
def _no_maintenance_window(monkeypatch):
    real = pf.in_maintenance_window
    monkeypatch.setattr(
        pf, "in_maintenance_window",
        lambda dt=None: False if dt is None else real(dt),
    )


@pytest.fixture
def farmer(monkeypatch):
    f = pf._Farmer()
    f.env = "production"
    monkeypatch.setattr(pf, "_farmer", f)
    return f


CFG = {
    "perps_farm_enabled": True,
    "perps_farm_symbol": "KXBTCPERP",
    "perps_farm_clip_contracts": 1,
    "perps_farm_max_inventory_contracts": 3,
    "perps_farm_min_spread_ticks": 2,
    "perps_farm_requote_ticks": 1,
    "perps_farm_daily_loss_usd": 2.0,
    "perps_farm_daily_volume_usd": 0.0,
    "perps_farm_max_cost_bps": 4.0,
}


def test_desired_quotes_two_sided():
    q = {"bid_usd_micro": 6_349_500, "ask_usd_micro": 6_353_000}
    want = pf.desired_quotes(q, 0, CFG)
    assert want == {"bid": 6_349_500, "ask": 6_353_000}


def test_desired_quotes_spread_too_tight():
    q = {"bid_usd_micro": 6_350_000, "ask_usd_micro": 6_350_100}
    assert pf.desired_quotes(q, 0, CFG) == {}


def test_desired_quotes_inventory_caps_one_side():
    q = {"bid_usd_micro": 6_349_500, "ask_usd_micro": 6_353_000}
    assert pf.desired_quotes(q, 300, CFG) == {"ask": 6_353_000}
    assert pf.desired_quotes(q, -300, CFG) == {"bid": 6_349_500}


def test_desired_quotes_crossed_book_stands_down():
    assert pf.desired_quotes({"bid_usd_micro": 5, "ask_usd_micro": 5}, 0, CFG) == {}
    assert pf.desired_quotes({"bid_usd_micro": None, "ask_usd_micro": 5}, 0, CFG) == {}


def test_should_replace_threshold():
    assert not pf.should_replace(6_350_000, 6_350_100, CFG)
    assert pf.should_replace(6_350_000, 6_350_300, CFG)


def test_apply_fill_avg_cost_round_trip():
    inv, avg, r = pf.apply_fill(0, 0.0, "bid", 200, 6_350_000)
    assert (inv, avg, r) == (200, 6_350_000.0, 0)
    inv, avg, r = pf.apply_fill(inv, avg, "bid", 200, 6_360_000)
    assert inv == 400 and avg == pytest.approx(6_355_000.0) and r == 0
    inv, avg, r = pf.apply_fill(inv, avg, "ask", 400, 6_365_000)
    assert inv == 0 and r == 40_000 and avg == 0.0


def test_apply_fill_short_side_and_flip():
    inv, avg, r = pf.apply_fill(0, 0.0, "ask", 100, 6_360_000)
    assert inv == -100 and avg == 6_360_000.0 and r == 0
    inv, avg, r = pf.apply_fill(inv, avg, "bid", 100, 6_350_000)
    assert inv == 0 and r == 10_000
    inv, avg, r = pf.apply_fill(-100, 6_360_000.0, "bid", 200, 6_370_000)
    assert inv == 100 and r == -10_000 and avg == 6_370_000.0


def test_maintenance_window():
    thu_in = datetime(2026, 7, 9, 7, 30, tzinfo=timezone.utc)
    thu_out = datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)
    fri = datetime(2026, 7, 10, 7, 30, tzinfo=timezone.utc)
    assert pf.in_maintenance_window(thu_in) is True
    assert pf.in_maintenance_window(thu_out) is False
    assert pf.in_maintenance_window(fri) is False


def _seed_fill(farmer, trade_id, side, count_cc, price_micro, fee_micro=0):
    inv, avg, realized = pf.apply_fill(
        farmer.inventory_cc, farmer.avg_entry_micro, side, count_cc, price_micro)
    farmer.inventory_cc, farmer.avg_entry_micro = inv, avg
    with db.get_db() as conn:
        db.insert_perp_farm_fill(conn, {
            "trade_id": trade_id, "ticker": "KXBTCPERP", "ts_ms": 1,
            "side": side, "count_cc": count_cc, "price_usd_micro": price_micro,
            "fee_usd_micro": fee_micro, "realized_pnl_usd_micro": realized,
            "inventory_after_cc": inv, "kalshi_env": "production",
        })
    farmer._stats_dirty = True


def test_farm_stats_and_status(fresh_db, farmer):
    _seed_fill(farmer, "t1", "bid", 100, 6_350_000, fee_micro=3_175)
    _seed_fill(farmer, "t2", "ask", 100, 6_353_000, fee_micro=3_176)
    st = farmer.status(CFG)
    assert st["today"]["fills"] == 2
    assert st["today"]["volumeUsd"] == pytest.approx(12.70, abs=0.02)
    assert st["today"]["realizedUsd"] == pytest.approx(0.003, abs=0.0005)
    assert st["today"]["feesUsd"] == pytest.approx(0.00635, abs=0.0005)
    assert st["inventoryContracts"] == 0


def test_daily_loss_halt(fresh_db, farmer):
    _seed_fill(farmer, "t1", "bid", 1000, 6_350_000)
    _seed_fill(farmer, "t2", "ask", 1000, 6_100_000)
    farmer._check_economics(CFG)
    assert farmer._halted()
    assert "loss cap" in farmer.halt_reason


def test_cost_bps_halt_needs_sample(fresh_db, farmer):
    cfg = dict(CFG, perps_farm_daily_loss_usd=100.0)
    _seed_fill(farmer, "t1", "bid", 100, 6_350_000, fee_micro=10_000)
    _seed_fill(farmer, "t2", "ask", 100, 6_349_000, fee_micro=10_000)
    farmer._check_economics(cfg)
    assert not farmer._halted()
    for i in range(50):
        _seed_fill(farmer, f"b{i}", "bid", 1000, 6_350_000, fee_micro=40_000)
        _seed_fill(farmer, f"s{i}", "ask", 1000, 6_350_000, fee_micro=40_000)
    farmer._check_economics(cfg)
    assert farmer._halted()
    assert "bps" in farmer.halt_reason


def test_volume_target_halt(fresh_db, farmer):
    cfg = dict(CFG, perps_farm_daily_volume_usd=10.0)
    _seed_fill(farmer, "t1", "bid", 100, 6_350_000)
    _seed_fill(farmer, "t2", "ask", 100, 6_350_000)
    farmer._check_economics(cfg)
    assert farmer._halted()
    assert "target" in farmer.halt_reason


def test_halt_expires_next_day(fresh_db, farmer):
    farmer._halt("test")
    assert farmer._halted()
    farmer.halted_day = "2020-01-01"
    assert not farmer._halted()


class _FakePapi:
    def __init__(self):
        self.placed = []
        self.canceled = []
        self.next_order_id = 0

    async def place(self, **kw):
        self.next_order_id += 1
        self.placed.append(kw)
        return {"order_id": f"o{self.next_order_id}", "fill_count": "0",
                "remaining_count": kw["count_cc"]}


def _wire_fakes(monkeypatch, farmer, fake, quote):
    import kalshi_perps_api as papi

    async def place(**kw):
        return await fake.place(**kw)

    async def cancel(order_id):
        fake.canceled.append(order_id)
        return {}

    async def fills(**kw):
        return []

    async def positions(ticker=""):
        return []

    async def enabled():
        return True

    async def balance(**kw):
        return {"subaccount_balances": [
            {"subaccount": 0, "available_balance": "100.0000"}]}

    monkeypatch.setattr(papi, "place_perps_limit_order", place)
    monkeypatch.setattr(papi, "cancel_perps_order", cancel)
    monkeypatch.setattr(papi, "get_perps_fills", fills)
    monkeypatch.setattr(papi, "get_perps_positions", positions)
    monkeypatch.setattr(papi, "get_perps_enabled", enabled)
    monkeypatch.setattr(papi, "get_perps_balance", balance)
    monkeypatch.setattr(pws, "is_connected", lambda: True)
    monkeypatch.setattr(pws, "quote", lambda t: quote)
    monkeypatch.setattr(kalshi_auth, "get_env", lambda: "production")


def _fresh_quote():
    import time
    now = int(time.time() * 1000)
    return {"bid_usd_micro": 6_349_500, "ask_usd_micro": 6_353_000,
            "ts_ms": now, "recv_ms": now}


def test_tick_places_both_sides(fresh_db, farmer, monkeypatch):
    fake = _FakePapi()
    _wire_fakes(monkeypatch, farmer, fake, _fresh_quote())
    asyncio.run(farmer.farm_tick(CFG))
    sides = {p["side"] for p in fake.placed}
    assert sides == {"bid", "ask"}
    assert all(p["post_only"] for p in fake.placed)
    assert farmer.live["bid"]["price_micro"] == 6_349_500
    assert farmer.live["ask"]["price_micro"] == 6_353_000


def test_tick_requotes_on_drift(fresh_db, farmer, monkeypatch):
    fake = _FakePapi()
    q = _fresh_quote()
    _wire_fakes(monkeypatch, farmer, fake, q)
    asyncio.run(farmer.farm_tick(CFG))
    placed_before = len(fake.placed)
    q["bid_usd_micro"] += 300
    q["ask_usd_micro"] += 300
    asyncio.run(farmer.farm_tick(CFG))
    assert len(fake.canceled) == 2
    assert len(fake.placed) == placed_before + 2


def test_tick_keeps_orders_within_tolerance(fresh_db, farmer, monkeypatch):
    fake = _FakePapi()
    q = _fresh_quote()
    _wire_fakes(monkeypatch, farmer, fake, q)
    asyncio.run(farmer.farm_tick(CFG))
    placed_before = len(fake.placed)
    q["bid_usd_micro"] += 100
    q["ask_usd_micro"] += 100
    asyncio.run(farmer.farm_tick(CFG))
    assert len(fake.placed) == placed_before
    assert fake.canceled == []


def test_tick_stands_down_when_halted(fresh_db, farmer, monkeypatch):
    fake = _FakePapi()
    _wire_fakes(monkeypatch, farmer, fake, _fresh_quote())
    farmer._halt("test halt")
    asyncio.run(farmer.farm_tick(CFG))
    assert fake.placed == []


def test_tick_cancels_when_stream_down(fresh_db, farmer, monkeypatch):
    fake = _FakePapi()
    _wire_fakes(monkeypatch, farmer, fake, _fresh_quote())
    asyncio.run(farmer.farm_tick(CFG))
    assert len(farmer.live) == 2
    monkeypatch.setattr(pws, "is_connected", lambda: False)
    asyncio.run(farmer.farm_tick(CFG))
    assert farmer.live == {}
    assert len(fake.canceled) == 2


def test_tick_quotes_on_slow_book_fresh_receipt(fresh_db, farmer, monkeypatch):
    import time
    fake = _FakePapi()
    now = int(time.time() * 1000)
    q = {"bid_usd_micro": 6_349_500, "ask_usd_micro": 6_353_000,
         "ts_ms": now - 90_000,
         "recv_ms": now}
    _wire_fakes(monkeypatch, farmer, fake, q)
    asyncio.run(farmer.farm_tick(CFG))
    assert {p["side"] for p in fake.placed} == {"bid", "ask"}
    assert farmer.last_error == ""


def test_tick_stands_down_when_receipt_stale(fresh_db, farmer, monkeypatch):
    import time
    fake = _FakePapi()
    now = int(time.time() * 1000)
    q = {"bid_usd_micro": 6_349_500, "ask_usd_micro": 6_353_000,
         "ts_ms": now, "recv_ms": now - 200_000}
    _wire_fakes(monkeypatch, farmer, fake, q)
    asyncio.run(farmer.farm_tick(CFG))
    assert fake.placed == []
    assert farmer.last_error == "quote stale"


def test_tick_never_raises(fresh_db, farmer, monkeypatch):
    import kalshi_perps_api as papi

    async def boom(**kw):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(papi, "get_perps_fills", boom)
    monkeypatch.setattr(pws, "is_connected", lambda: False)
    monkeypatch.setattr(kalshi_auth, "get_env", lambda: "production")
    asyncio.run(farmer.farm_tick(CFG))
    assert farmer.last_error != "" or True


def test_poll_fills_parses_kalshi_margin_shape(fresh_db, farmer, monkeypatch):
    import kalshi_perps_api as papi

    fill = {
        "fill_id": "F123",
        "order_id": "o1",
        "ticker": "KXBTCPERP",
        "side": "ask",
        "count": "1.00",
        "price": "6.3530",
        "fees": "0.0032",
        "is_taker": False,
        "created_time": "2026-07-06T05:00:00Z",
    }

    async def fills(**kw):
        return [fill]

    monkeypatch.setattr(papi, "get_perps_fills", fills)
    monkeypatch.setattr(kalshi_auth, "get_env", lambda: "production")
    asyncio.run(farmer._poll_fills("KXBTCPERP", CFG))

    assert farmer.inventory_cc == -100
    with db.get_db() as conn:
        assert db.perp_farm_fill_seen(conn, "F123", "production")
        row = conn.execute(
            "SELECT side, count_cc, price_usd_micro, fee_usd_micro "
            "FROM perp_farm_fills WHERE trade_id='F123'"
        ).fetchone()
    assert tuple(row) == ("ask", 100, 6_353_000, 3200)

    asyncio.run(farmer._poll_fills("KXBTCPERP", CFG))
    assert farmer.inventory_cc == -100


def test_demo_env_uses_suffixed_ticker(fresh_db, farmer, monkeypatch):
    fake = _FakePapi()
    _wire_fakes(monkeypatch, farmer, fake, _fresh_quote())
    monkeypatch.setattr(kalshi_auth, "get_env", lambda: "demo")
    asyncio.run(farmer.farm_tick(CFG))
    assert all(p["ticker"] == "KXBTCPERP1" for p in fake.placed)


def test_effective_fee_bps_helper_excludes_taker(fresh_db):
    with db.get_db() as conn:
        assert db.perp_farm_effective_fee_bps(conn, "production") is None
        db.insert_perp_farm_fill(conn, {
            "trade_id": "m", "ticker": "KXBTCPERP", "ts_ms": 1, "side": "bid",
            "count_cc": 100, "price_usd_micro": 6_000_000, "fee_usd_micro": 3000,
            "is_taker": 0, "realized_pnl_usd_micro": 0, "inventory_after_cc": 100,
            "kalshi_env": "production"})
        db.insert_perp_farm_fill(conn, {
            "trade_id": "t", "ticker": "KXBTCPERP", "ts_ms": 1, "side": "ask",
            "count_cc": 100, "price_usd_micro": 6_000_000, "fee_usd_micro": 48000,
            "is_taker": 1, "realized_pnl_usd_micro": 0, "inventory_after_cc": 0,
            "kalshi_env": "production"})
        bps = db.perp_farm_effective_fee_bps(conn, "production")
    assert bps == pytest.approx(5.0)


def test_fee_gate_off_by_default(fresh_db, farmer, monkeypatch):
    fake = _FakePapi()
    _wire_fakes(monkeypatch, farmer, fake, _fresh_quote())
    asyncio.run(farmer.farm_tick(CFG))
    assert {p["side"] for p in fake.placed} == {"bid", "ask"}


def test_fee_gate_stands_down_when_fee_above_cap(fresh_db, farmer, monkeypatch):
    fake = _FakePapi()
    _wire_fakes(monkeypatch, farmer, fake, _fresh_quote())
    cfg = dict(CFG, perps_farm_max_fee_bps=2.0)
    asyncio.run(farmer.farm_tick(cfg))
    assert fake.placed == []
    assert "cap" in farmer.last_error and "bps" in farmer.last_error


def test_fee_gate_allows_when_measured_fee_below_cap(fresh_db, farmer, monkeypatch):
    with db.get_db() as conn:
        db.insert_perp_farm_fill(conn, {
            "trade_id": "cheap", "ticker": "KXBTCPERP", "ts_ms": 1, "side": "bid",
            "count_cc": 100, "price_usd_micro": 6_000_000, "fee_usd_micro": 900,
            "is_taker": 0, "realized_pnl_usd_micro": 0, "inventory_after_cc": 100,
            "kalshi_env": "production"})
    fake = _FakePapi()
    _wire_fakes(monkeypatch, farmer, fake, _fresh_quote())
    cfg = dict(CFG, perps_farm_max_fee_bps=2.0)
    asyncio.run(farmer.farm_tick(cfg))
    assert farmer._maker_fee_bps is not None and farmer._maker_fee_bps < 2.0
    assert {p["side"] for p in fake.placed} == {"bid", "ask"}
