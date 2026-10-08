from __future__ import annotations

import random

import pytest

import trader
from config import merge_with_defaults


@pytest.fixture
def cfg() -> dict:
    return merge_with_defaults({})




def test_size_below_base_edge_uses_min_fraction(cfg):
    assert trader._compute_position_usd(1000.0, 3.0, cfg) == 20.0


def test_size_above_max_edge_capped_by_hard_max(cfg):
    assert trader._compute_position_usd(1000.0, 25.0, cfg) == 50.0


def test_size_interpolates_between_edges(cfg):
    assert trader._compute_position_usd(1000.0, 7.5, cfg) == pytest.approx(40.0)
    assert trader._compute_position_usd(1000.0, 12.5, cfg) == pytest.approx(50.0)


def test_fixed_sizing_returns_flat_amount_ignoring_balance_and_edge(cfg):
    cfg["sizing_mode"] = "fixed"
    cfg["fixed_trade_usd"] = 3.0
    cfg["hard_max_position_usd"] = 50.0
    assert trader._compute_position_usd(1000.0, 25.0, cfg) == 3.0
    assert trader._compute_position_usd(5.0, -10.0, cfg) == 3.0


def test_fixed_sizing_capped_by_hard_max(cfg):
    cfg["sizing_mode"] = "fixed"
    cfg["fixed_trade_usd"] = 100.0
    cfg["hard_max_position_usd"] = 25.0
    assert trader._compute_position_usd(1000.0, 10.0, cfg) == 25.0




def test_signal_cost_whale_uses_taker_side_price():
    direction, cents = trader._signal_cost_cents(
        {"taker_side": "no", "price": 0.62}, "whale"
    )
    assert (direction, cents) == ("no", 62)


def test_signal_cost_momentum_no_side_inverts_price():
    direction, cents = trader._signal_cost_cents(
        {"direction": "no", "price": 0.30}, "momentum"
    )
    assert (direction, cents) == ("no", 70)


def test_compute_edge_momentum_no_side():
    edge = trader._compute_edge(
        {"direction": "no", "price": 0.30, "confidence": 80.0}, "momentum"
    )
    assert edge == pytest.approx(10.0)




def test_should_trade_passes_clean_whale(cfg):
    sig = {"ticker": "X", "price": 0.60, "confidence": 70.0,
           "taker_side": "yes", "category": "sports"}
    ok, reason = trader.should_trade(sig, "whale", cfg)
    assert ok is True and reason == "ok"


def test_should_trade_blocks_when_source_disabled(cfg):
    cfg["trade_whales"] = False
    ok, reason = trader.should_trade({"price": 0.6, "confidence": 70.0,
                                      "taker_side": "yes"}, "whale", cfg)
    assert ok is False and reason == "whales disabled"


def test_should_trade_blocks_low_confidence(cfg):
    ok, reason = trader.should_trade(
        {"ticker": "X", "price": 0.60, "confidence": 50.0,
         "taker_side": "yes"}, "whale", cfg)
    assert ok is False and reason.startswith("conf ")


def test_should_trade_blocks_entry_above_max(cfg):
    ok, reason = trader.should_trade(
        {"ticker": "X", "price": 0.90, "confidence": 99.0,
         "taker_side": "yes"}, "whale", cfg)
    assert ok is False and reason == "entry 90c > 85c"


def _iso_in_days(days: float) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_should_trade_resolution_days_gate(cfg):
    base = {"ticker": "X", "price": 0.60, "confidence": 70.0,
            "taker_side": "yes", "category": "sports"}

    cfg["max_resolution_days"] = 0
    assert trader.should_trade({**base, "close_time": _iso_in_days(120)}, "whale", cfg)[0] is True

    cfg["max_resolution_days"] = 30
    ok, reason = trader.should_trade({**base, "close_time": _iso_in_days(120)}, "whale", cfg)
    assert ok is False and "resolves" in reason
    assert trader.should_trade({**base, "close_time": _iso_in_days(10)}, "whale", cfg)[0] is True
    assert trader.should_trade({**base, "close_time": ""}, "whale", cfg)[0] is True
    assert trader.should_trade({**base, "close_time": "garbage"}, "whale", cfg)[0] is True
    assert trader.should_trade(base, "whale", cfg)[0] is True


def test_days_until_close_parses_and_fails_soft():
    assert trader._days_until_close("") is None
    assert trader._days_until_close("nonsense") is None
    d = trader._days_until_close(_iso_in_days(10))
    assert d is not None and 9.8 < d < 10.1


def test_should_trade_category_filter_excludes(cfg):
    cfg["allowed_categories"] = ["politics"]
    ok, reason = trader.should_trade(
        {"ticker": "X", "price": 0.60, "confidence": 70.0,
         "taker_side": "yes", "category": "sports"}, "whale", cfg)
    assert ok is False and "not in allowed set" in reason


def test_should_trade_empty_category_list_blocks_everything(cfg):
    cfg["allowed_categories"] = []
    ok, reason = trader.should_trade(
        {"ticker": "X", "price": 0.60, "confidence": 70.0,
         "taker_side": "yes", "category": "sports"}, "whale", cfg)
    assert ok is False and reason == "no categories enabled"


def test_should_trade_per_source_whale_category_blocks(cfg):
    cfg["allowed_whale_categories"] = ["crypto"]
    ok, reason = trader.should_trade(
        {"ticker": "X", "price": 0.60, "confidence": 70.0,
         "taker_side": "yes", "category": "sports"}, "whale", cfg)
    assert ok is False and "whale set" in reason


_GATE_PROBES = [
    ({"ticker": "X", "price": 0.95, "confidence": 1.0,
      "taker_side": "yes", "category": "world"}, "whale"),
    ({"ticker": "X", "price": 0.60, "confidence": 70.0,
      "taker_side": "yes", "category": "crypto"}, "whale"),
    ({"ticker": "X", "price": 0.60, "confidence": 99.0,
      "taker_side": "yes", "category": "sports"}, "momentum"),
    ({"ticker": "X", "price": 0.99, "confidence": 99.0,
      "taker_side": "yes", "category": "sports"}, "whale"),
]


@pytest.mark.parametrize("sig,source", _GATE_PROBES)
def test_stale_gambling_mode_trades_exactly_like_its_absence(cfg, monkeypatch, sig, source):
    monkeypatch.setattr(random, "random", lambda: 0.0)
    legacy = dict(cfg, gambling_mode=True, gambling_trade_probability=1.0)
    assert (trader.should_trade(dict(sig), source, legacy)
            == trader.should_trade(dict(sig), source, cfg))


def test_stale_gambling_mode_signal_still_meets_the_confidence_gate(cfg):
    legacy = dict(cfg, gambling_mode=True, gambling_trade_probability=1.0)
    ok, reason = trader.should_trade(
        {"ticker": "X", "price": 0.95, "confidence": 1.0,
         "taker_side": "yes", "category": "world"}, "whale", legacy)
    assert ok is False and reason.startswith("conf 1.0 <")


def test_merge_drops_the_removed_gambling_keys():
    for raw in ({"gamblingMode": True, "gamblingTradeProbability": 1.0},
                {"gambling_mode": True, "gambling_trade_probability": 1.0}):
        cfg = merge_with_defaults(raw)
        assert "gambling_mode" not in cfg
        assert "gambling_trade_probability" not in cfg


def test_balance_fetch_not_poisoned_by_concurrent_cred_test(monkeypatch):
    import asyncio
    import kalshi_auth

    async def _bal(*a, **k):
        return {"balance": 9999 if kalshi_auth.get_env() == "production" else 11,
                "portfolio_value": 0}
    monkeypatch.setattr(trader, "get_balance", _bal)
    trader._balance_cache.clear()

    async def scenario():
        kalshi_auth.set_env("production")
        released = asyncio.Event()

        async def cred_test():
            async with kalshi_auth.ENV_LOCK:
                kalshi_auth.set_env("paper")
                await released.wait()
                kalshi_auth.set_env("production")

        t = asyncio.create_task(cred_test())
        await asyncio.sleep(0)
        rb = asyncio.create_task(
            trader.refresh_balance(merge_with_defaults({}), force=True))
        await asyncio.sleep(0.05)
        assert not rb.done()
        released.set()
        cents, _ = await rb
        await t
        return cents

    assert asyncio.run(scenario()) == 9999


def test_should_trade_per_source_lets_each_source_keep_its_categories(cfg):
    cfg["allowed_whale_categories"] = ["crypto"]
    cfg["allowed_momentum_categories"] = ["sports"]
    ok, _ = trader.should_trade(
        {"ticker": "X", "price": 0.60, "confidence": 70.0,
         "taker_side": "yes", "category": "crypto"}, "whale", cfg)
    assert ok is True
    ok2, reason2 = trader.should_trade(
        {"ticker": "X", "price": 0.30, "confidence": 80.0, "direction": "no",
         "signal_type": "trade_cluster", "category": "crypto"}, "momentum", cfg)
    assert ok2 is False and "momentum set" in reason2


def test_should_trade_momentum_signal_type_not_allowed(cfg):
    sig = {"ticker": "X", "price": 0.30, "confidence": 80.0,
           "direction": "no", "signal_type": "price_move"}
    ok, reason = trader.should_trade(sig, "momentum", cfg)
    assert ok is False and "not allowed" in reason




def test_best_cross_price_yes_reads_opposing_no_book():
    book = {"yes": [[30, 10]], "no": [[45, 5], [40, 3]]}
    assert trader._best_cross_price_cents(book, "yes") == 55


def test_best_cross_price_empty_book_returns_none():
    assert trader._best_cross_price_cents({"yes": [], "no": []}, "yes") is None




def test_parse_kalshi_order_sums_taker_and_maker():
    parsed = trader._parse_kalshi_order({
        "taker_fill_count": 3, "maker_fill_count": 2,
        "taker_fill_cost": 180, "maker_fill_cost": 120,
        "status": "executed", "place_count": 5, "remaining_count": 0,
    })
    assert parsed["filled"] == 5
    assert parsed["cost_cents"] == 300
    assert parsed["avg_cents"] == 60.0
    assert parsed["status"] == "executed"


def test_parse_kalshi_order_new_fp_dollars_shape():
    parsed = trader._parse_kalshi_order({
        "fill_count_fp": "5.00",
        "taker_fill_cost_dollars": "2.40",
        "maker_fill_cost_dollars": "0.60",
        "initial_count_fp": "5.00",
        "remaining_count_fp": "0.00",
        "status": "executed",
    })
    assert parsed["filled"] == 5
    assert parsed["cost_cents"] == 300
    assert parsed["avg_cents"] == 60.0
    assert parsed["remaining"] == 0
    assert parsed["place_count"] == 5


def test_parse_kalshi_order_resting_fp_reports_remaining():
    parsed = trader._parse_kalshi_order({
        "fill_count_fp": "0.00", "remaining_count_fp": "1.00",
        "initial_count_fp": "1.00", "taker_fill_cost_dollars": "0.000000",
        "maker_fill_cost_dollars": "0.000000", "status": "resting",
    })
    assert parsed["filled"] == 0
    assert parsed["remaining"] == 1
    assert parsed["place_count"] == 1


def test_parse_kalshi_fill_live_fp_dollars_shape():
    fill = {
        "count_fp": "1.00", "count": None,
        "side": "no", "action": "buy",
        "yes_price_dollars": "0.0100", "no_price_dollars": "0.9900",
        "order_id": "abc",
    }
    parsed = trader._parse_kalshi_fill(fill, default_side="no")
    assert parsed["count"] == 1
    assert parsed["side"] == "no"
    assert parsed["price_cents"] == 99


def test_parse_kalshi_fill_legacy_cents_shape():
    fill = {"count": 3, "side": "yes", "yes_price": 60, "no_price": 40}
    parsed = trader._parse_kalshi_fill(fill, default_side="yes")
    assert parsed["count"] == 3
    assert parsed["price_cents"] == 60


def test_parse_kalshi_fill_out_of_range_price_is_none():
    fill = {"count_fp": "1.00", "side": "yes", "yes_price_dollars": "1.0000"}
    assert trader._parse_kalshi_fill(fill, "yes")["price_cents"] is None


def test_parse_kalshi_position_negative_qty_is_no_side():
    parsed = trader._parse_kalshi_position({
        "position_fp": -4, "market_exposure_dollars": 2.0,
    })
    assert parsed["filled"] == 4
    assert parsed["side"] == "no"
    assert parsed["cost_cents"] == 200


def test_db_status_executed_is_filled():
    parsed = {"status": "executed", "filled": 5}
    assert trader._db_status_from_order(parsed, target=5) == "filled"


def test_db_status_canceled_with_partial_fill():
    parsed = {"status": "canceled", "filled": 2}
    assert trader._db_status_from_order(parsed, target=5) == "partial"


def test_db_status_resting_unfilled_is_submitted():
    parsed = {"status": "resting", "filled": 0}
    assert trader._db_status_from_order(parsed, target=5) == "submitted"




def test_yes_payout_result_yes_is_one():
    assert trader._market_yes_payout({"result": "yes"}) == 1.0


def test_yes_payout_result_no_is_zero():
    assert trader._market_yes_payout({"result": "no"}) == 0.0


def test_yes_payout_unsettled_market_is_none():
    assert trader._market_yes_payout({"status": "open", "result": ""}) is None


def test_yes_payout_uses_settlement_value_dollars():
    m = {"status": "settled", "result": "", "settlement_value_dollars": 0.5}
    assert trader._market_yes_payout(m) == 0.5


def test_yes_payout_legacy_cents_field():
    m = {"status": "finalized", "result": "", "settlement_value": 75}
    assert trader._market_yes_payout(m) == 0.75


def test_yes_payout_none_market_is_none():
    assert trader._market_yes_payout(None) is None




def test_taker_fee_cents_shape():
    assert trader._taker_fee_cents(50) == pytest.approx(1.75)
    assert trader._taker_fee_cents(85) == pytest.approx(0.8925)
    assert trader._taker_fee_cents(95) < trader._taker_fee_cents(50)


def test_fee_aware_edge_gate_subtracts_taker_fee(cfg):
    sig = {"ticker": "X", "price": 0.50, "confidence": 59.0, "taker_side": "yes"}
    cfg["min_edge_pts_whale"] = 8.0
    ok, reason = trader.should_trade(sig, "whale", cfg)
    assert ok is False and "net edge" in reason
    cfg["fee_aware_edge"] = False
    assert trader.should_trade(sig, "whale", cfg)[0] is True


def test_min_market_volume_floor_fails_open_on_unknown(cfg):
    base = {"ticker": "X", "price": 0.60, "confidence": 75.0, "taker_side": "yes"}
    cfg["min_market_volume"] = 100.0
    ok, reason = trader.should_trade({**base, "market_volume": 40}, "whale", cfg)
    assert ok is False and "volume" in reason
    assert trader.should_trade({**base, "market_volume": 5000}, "whale", cfg)[0] is True
    assert trader.should_trade(base, "whale", cfg)[0] is True
    assert trader.should_trade({**base, "market_volume": 0}, "whale", cfg)[0] is True


def test_should_trade_convergence_gates_on_edge_too(cfg):
    cfg["trade_convergence"] = True
    cfg["min_confidence_whale"] = 55.0
    cfg["min_edge_pts_whale"] = 4.0
    weak = {"ticker": "X", "price": 0.60, "confidence": 64.0, "direction": "yes"}
    ok, reason = trader.should_trade(weak, "convergence", cfg)
    assert ok is False and "net edge" in reason
    strong = {**weak, "confidence": 66.0}
    assert trader.should_trade(strong, "convergence", cfg)[0] is True
