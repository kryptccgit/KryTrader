from __future__ import annotations

import asyncio

import kalshi_api
import kalshi_ws
import terminal
import trader

# Kalshi deprecated Order/Fill `action`/`side` and Trade `taker_side` on
# 2026-05-06 ("not removed before May 28, 2026"). These pin the reading of the
# replacement fields so the day the old ones vanish is a non-event.


def test_taker_outcome_side_prefers_new_fields():
    assert kalshi_ws.taker_outcome_side({"taker_outcome_side": "no", "taker_side": "yes"}) == "no"
    assert kalshi_ws.taker_outcome_side({"taker_book_side": "bid"}) == "yes"
    assert kalshi_ws.taker_outcome_side({"taker_book_side": "ask"}) == "no"
    assert kalshi_ws.taker_outcome_side({"taker_side": "YES"}) == "yes"
    assert kalshi_ws.taker_outcome_side({}) == ""


def test_rest_trades_get_taker_side_without_the_deprecated_field(monkeypatch):
    async def fake_get(url, params=None, **kw):
        return {"trades": [{"trade_id": "t1", "taker_outcome_side": "no"}]}

    monkeypatch.setattr(kalshi_api, "_pub_get", fake_get)
    trades = asyncio.run(kalshi_api.fetch_recent_trades(10))
    assert trades[0]["taker_side"] == "no"


def test_ws_trade_keeps_absent_fields_absent():
    c = kalshi_ws._Client()
    c._on_trade({"msg": {"market_ticker": "KXT", "taker_book_side": "ask"}})
    t = c.trades[-1]
    assert t["taker_side"] == "no"
    assert t["count_fp"] is None
    assert t["yes_price_dollars"] is None and t["no_price_dollars"] is None


def test_order_direction_legacy_fields_win():
    assert kalshi_api.order_direction({"action": "sell", "side": "yes", "outcome_side": "no"}) == ("sell", "yes")


def test_order_direction_from_outcome_side_uses_the_holding():
    o = {"outcome_side": "no"}
    # Flat: long NO is a buy of NO.
    assert kalshi_api.order_direction(o) == ("buy", "no")
    # Holding YES: the same order reduces it -- a sell of YES.
    assert kalshi_api.order_direction(o, held_side="yes") == ("sell", "yes")
    assert kalshi_api.order_direction(o, held_side="no") == ("buy", "no")
    assert kalshi_api.order_direction({"book_side": "bid"}) == ("buy", "yes")
    assert kalshi_api.order_direction({}) == (None, None)


def test_resting_sell_is_still_a_sell_without_legacy_fields(monkeypatch):
    async def fake_orders(**kw):
        return [{"order_id": "o1", "ticker": "KXT", "outcome_side": "no",
                 "yes_price_dollars": "0.6000", "no_price_dollars": "0.4000",
                 "remaining_count_fp": "3.00", "status": "resting"}]

    async def fake_positions(*a, **kw):
        return [{"ticker": "KXT", "position_fp": "5.00"}]

    monkeypatch.setattr(kalshi_api, "fetch_orders", fake_orders)
    monkeypatch.setattr(kalshi_api, "get_positions", fake_positions)
    row = asyncio.run(terminal.resting_orders(True))["orders"][0]
    assert (row["action"], row["side"]) == ("sell", "yes")
    assert row["priceCents"] == 60.0


def test_order_row_never_guesses_buy_yes():
    row = terminal._order_row({"order_id": "o2", "ticker": "KXT"})
    assert row["side"] is None and row["action"] is None


def test_entry_fill_filter_without_action():
    assert trader._is_entry_buy({"outcome_side": "yes"}, "yes")
    assert not trader._is_entry_buy({"outcome_side": "no"}, "yes")
    assert trader._is_entry_buy({}, "yes")
    assert not trader._is_entry_buy({"action": "sell", "side": "yes"}, "yes")


def test_fill_price_side_falls_back_to_outcome():
    f = {"count_fp": "2.00", "outcome_side": "no",
         "yes_price_dollars": "0.3000", "no_price_dollars": "0.7000"}
    parsed = trader._parse_kalshi_fill(f)
    assert parsed["side"] == "no" and parsed["price_cents"] == 70
