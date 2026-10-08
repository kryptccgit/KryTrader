from __future__ import annotations

import asyncio
import math
import time

import pytest

import crypto15m
import spot_ws


def run_async(coro):
    return asyncio.run(coro)


def _fresh_client() -> spot_ws._Client:
    c = spot_ws._Client()
    c.connected = True
    return c


def _ticker_msg(product: str, price: float) -> dict:
    return {
        "channel": "ticker",
        "timestamp": "2026-07-01T00:00:00Z",
        "events": [{"type": "update", "tickers": [
            {"type": "ticker", "product_id": product, "price": str(price)},
        ]}],
    }




def test_handle_message_stores_prices_by_asset():
    c = _fresh_client()
    c.handle_message(_ticker_msg("BTC-USD", 65000.5))
    c.handle_message(_ticker_msg("ETH-USD", 3500.25))
    assert c.spot("BTC") == pytest.approx(65000.5)
    assert c.spot("eth") == pytest.approx(3500.25)
    assert c.spot("BNB") is None
    assert set(c.fresh_spots()) == {"BTC", "ETH"}


def test_handle_message_ignores_junk():
    c = _fresh_client()
    c.handle_message({"channel": "heartbeats"})
    c.handle_message({"channel": "ticker", "events": [{"tickers": [
        {"product_id": "BTC-USD", "price": "not-a-number"},
        {"product_id": "DOGE-USD", "price": "-1"},
        {"product_id": "UNKNOWN-USD", "price": "5"},
    ]}]})
    c.handle_message("garbage")
    assert c.fresh_spots() == {}


def test_stale_prices_are_not_served():
    c = _fresh_client()
    c.prices["BTC"] = (time.time() - 60.0, 65000.0)
    assert c.spot("BTC") is None
    assert c.fresh_spots() == {}
    c.prices["BTC"] = (time.time(), 65000.0)
    c.connected = False
    assert c.fresh_spots() == {}




def test_sampler_dedupes_within_a_second():
    c = _fresh_client()
    now = float(int(time.time()))
    c.prices["BTC"] = (now, 65000.0)
    c._sample_once(now)
    c._sample_once(now + 0.4)
    c.prices["BTC"] = (now + 1.0, 65001.0)
    c._sample_once(now + 1.1)
    assert len(c.samples["BTC"]) == 2
    assert [px for _s, px in c.samples["BTC"]] == [65000.0, 65001.0]


def test_sampler_skips_stale_prices():
    c = _fresh_client()
    now = time.time()
    c.prices["BTC"] = (now - 30.0, 65000.0)
    c._sample_once(now)
    assert len(c.samples["BTC"]) == 0


def test_window_partial_filters_to_settlement_span():
    c = _fresh_client()
    close = 1_000_000.0
    for sec, px in [
        (int(close) - 70, 1.0), (int(close) - 61, 2.0),
        (int(close) - 60, 10.0), (int(close) - 30, 20.0), (int(close) - 1, 30.0),
        (int(close), 99.0),
    ]:
        c.samples["BTC"].append((sec, px))
    total, count = c.window_partial("BTC", close, now=close + 5)
    assert count == 3
    assert total == pytest.approx(60.0)
    total, count = c.window_partial("BTC", close, now=close - 30)
    assert count == 1 and total == pytest.approx(10.0)
    assert c.window_partial("XRP", close) == (0.0, 0)




def test_settlement_prob_continuous_at_final_minute_boundary():
    above = crypto15m.settlement_up_prob(100.2, 100.0, 0.001, 1.0001)
    below = crypto15m.settlement_up_prob(100.2, 100.0, 0.001, 0.9999)
    assert above is not None and below is not None
    assert abs(above - below) < 0.01


def test_settlement_prob_tighter_than_terminal_model():
    terminal = crypto15m.model_up_prob(100.1, 100.0, 0.002, 1.0)
    settle = crypto15m.settlement_up_prob(100.1, 100.0, 0.002, 1.0)
    assert terminal is not None and settle is not None
    assert settle > terminal


def test_settlement_prob_partial_prints_lock_in_the_average():
    psum, k = 101.0 * 50, 50
    p = crypto15m.settlement_up_prob(
        100.0, 100.0, 0.002, 10 / 60.0, partial_sum=psum, partial_count=k,
    )
    assert p is not None and p > 0.99
    p = crypto15m.settlement_up_prob(
        100.0, 100.0, 0.002, 10 / 60.0, partial_sum=99.0 * 50, partial_count=k,
    )
    assert p is not None and p < 0.01


def test_settlement_prob_no_prints_degrades_to_spot_approximation():
    p = crypto15m.settlement_up_prob(100.0, 100.0, 0.002, 0.5)
    assert p == pytest.approx(0.5, abs=1e-6)
    p_late = crypto15m.settlement_up_prob(100.05, 100.0, 0.002, 5 / 60.0)
    p_early = crypto15m.settlement_up_prob(100.05, 100.0, 0.002, 55 / 60.0)
    assert p_late is not None and p_early is not None
    assert p_late > p_early > 0.5


def test_settlement_prob_guards():
    assert crypto15m.settlement_up_prob(None, 100, 0.001, 5) is None
    assert crypto15m.settlement_up_prob(100, None, 0.001, 5) is None
    assert crypto15m.settlement_up_prob(100, 100, 0.0, 5) is None
    assert crypto15m.settlement_up_prob(100, 100, 0.001, None) is None
    p = crypto15m.settlement_up_prob(
        100.0, 100.0, 0.002, 0.9, partial_sum=100.0 * 59, partial_count=59,
    )
    assert p is not None and 0.0 <= p <= 1.0




def test_fetch_spots_overlays_ws_prices(monkeypatch):
    monkeypatch.setattr(spot_ws, "fresh_spots",
                        lambda: {"BTC": 65000.0, "ETH": 3500.0})
    monkeypatch.setattr(crypto15m, "_spot_cache", {
        "at": asyncio.new_event_loop().time(), "spots":
        {"BTC": 64900.0, "HYPE": 30.0, "BNB": 600.0}, "source": "cryptocompare",
    })

    async def _run():
        crypto15m._spot_cache["at"] = asyncio.get_event_loop().time()
        return await crypto15m.fetch_spots()

    spots, source = run_async(_run())
    assert spots["BTC"] == pytest.approx(65000.0)
    assert spots["HYPE"] == pytest.approx(30.0)
    assert source.startswith("coinbase-ws")


def test_fetch_spots_pure_rest_when_ws_cold(monkeypatch):
    monkeypatch.setattr(spot_ws, "fresh_spots", lambda: {})

    async def _run():
        crypto15m._spot_cache["at"] = asyncio.get_event_loop().time()
        crypto15m._spot_cache["spots"] = {"BTC": 64900.0}
        crypto15m._spot_cache["source"] = "cryptocompare"
        return await crypto15m.fetch_spots()

    spots, source = run_async(_run())
    assert spots == {"BTC": 64900.0}
    assert source == "cryptocompare"
