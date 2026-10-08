from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import pytest

import cf_ws
import crypto15m
import kalshi_api
import kalshi_ws
import spot_ws


def run_async(coro):
    return asyncio.run(coro)


def _fresh_client() -> cf_ws._State:
    return cf_ws._State()


def _value_msg(index_id="BRTI", value="68000.12", *, settle=None):
    msg = {
        "index_id": index_id,
        "received_at": int(time.time() * 1000),
        "data": json.dumps({"type": "value", "value": value}),
        "avg_60s_data": {"value": value, "window_size": 60},
    }
    if settle:
        msg["last_60s_windowed_average_15min"] = settle
    return {"type": "cfbenchmarks_value", "sid": 1, "seq": 1, "msg": msg}




def test_index_mapping():
    assert cf_ws._index_to_asset("BRTI") == "BTC"
    assert cf_ws._index_to_asset("ETHUSD_RTI") == "ETH"
    assert cf_ws._index_to_asset("SOLUSD_RTI") == "SOL"
    assert cf_ws._index_to_asset("DOGEUSD_RTI") == "DOGE"
    assert cf_ws._index_to_asset("SOMETHING_ELSE") is None
    assert cf_ws._index_to_asset("") is None


def test_handle_message_stores_raw_index_value():
    c = _fresh_client()
    c.handle_message(_value_msg("BRTI", "68000.12"))
    c.handle_message(_value_msg("ETHUSD_RTI", "3500.5"))
    assert c.spot("BTC") == pytest.approx(68000.12)
    assert c.spot("eth") == pytest.approx(3500.5)
    assert set(c.fresh_spots()) == {"BTC", "ETH"}


def test_handle_message_falls_back_to_avg_when_frame_unparseable():
    c = _fresh_client()
    m = _value_msg("BRTI", "68000.12")
    m["msg"]["data"] = "not-json{{{"
    m["msg"]["avg_60s_data"] = {"value": "67999.5"}
    c.handle_message(m)
    assert c.spot("BTC") == pytest.approx(67999.5)


def test_handle_message_ignores_junk():
    c = _fresh_client()
    c.handle_message({"type": "subscribed"})
    c.handle_message({"type": "cfbenchmarks_value", "msg": {"index_id": "WEIRD"}})
    c.handle_message("garbage")
    assert c.fresh_spots() == {}


def test_stale_values_not_served():
    c = _fresh_client()
    c.values["BTC"] = (time.time() - 60.0, 68000.0)
    assert c.spot("BTC") is None
    assert c.fresh_spots() == {}




def test_kalshi_ws_routes_cf_frames_to_cf_state(monkeypatch):
    fresh = cf_ws._State()
    monkeypatch.setattr(cf_ws, "_client", fresh)
    kc = kalshi_ws._Client()
    kc._handle(_value_msg("BRTI", "68123.45"))
    assert cf_ws.spot("BTC") == pytest.approx(68123.45)


def test_kalshi_ws_subscribes_cf_channel_with_index_ids():
    kc = kalshi_ws._Client()
    kc.want_cf = True
    sent = []

    class _WS:
        async def send(self, s):
            sent.append(json.loads(s))

    run_async(kc._subscribe_account(_WS()))
    cf_subs = [m for m in sent
               if m.get("params", {}).get("channels") == ["cfbenchmarks_value"]]
    assert len(cf_subs) == 1
    assert cf_subs[0]["params"]["index_ids"] == ["all"]
    others = [m for m in sent if m not in cf_subs]
    assert others and all("index_ids" not in m["params"] for m in others)


def test_kalshi_ws_omits_cf_channel_when_disabled():
    kc = kalshi_ws._Client()
    sent = []

    class _WS:
        async def send(self, s):
            sent.append(json.loads(s))

    run_async(kc._subscribe_account(_WS()))
    assert all(
        m.get("params", {}).get("channels") != ["cfbenchmarks_value"] for m in sent
    )




def test_settle_partial_matches_window_and_returns_sum_count():
    c = _fresh_client()
    close = time.time() + 30
    c.handle_message(_value_msg("BRTI", "68000", settle={
        "value": "68010.5", "window_size": 30,
        "window_start_ts_ms": (close - 60) * 1000,
        "window_end_ts_exclusive": (close - 30) * 1000,
    }))
    s, n = c.settle_partial("BTC", close)
    assert n == 30
    assert s == pytest.approx(68010.5 * 30)
    assert c.settle_partial("BTC", close - 900) == (0.0, 0)
    assert c.settle_partial("SOL", close) == (0.0, 0)


def test_settle_partial_goes_stale():
    c = _fresh_client()
    close = time.time() + 30
    c.settle["BTC"] = (time.time() - 30.0, 68010.5, 30, (close - 30) * 1000)
    assert c.settle_partial("BTC", close) == (0.0, 0)




def _snapshot_with(monkeypatch, market, cfg, spot=None, indicators=False):
    async def _markets(**kw):
        return [market], ""
    monkeypatch.setattr(kalshi_api, "fetch_markets", _markets)
    cfg["crypto15m_indicator_detect"] = indicators
    entry = {"asset": "BTC", "series": "KXBTC15M", "cg": "bitcoin"}
    now = datetime.now(timezone.utc).timestamp()
    return run_async(crypto15m._asset_snapshot(entry, spot, cfg, now))


def _rest_market():
    close = (datetime.now(timezone.utc) + timedelta(minutes=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "ticker": "KXBTC15M-T1", "close_time": close,
        "yes_bid_dollars": 0.40, "yes_ask_dollars": 0.60,
        "no_ask_dollars": 0.62, "last_price_dollars": 0.50,
    }


def test_asset_snapshot_overlays_fresh_ws_quote(monkeypatch):
    from config import merge_with_defaults
    now_ms = time.time() * 1000.0
    monkeypatch.setattr(kalshi_ws, "ticker_quote", lambda t: {
        "yes_bid_cents": 48, "yes_ask_cents": 52, "last_cents": 50,
        "ts_ms": now_ms - 500,
    })
    out = _snapshot_with(monkeypatch, _rest_market(), merge_with_defaults({}))
    assert out["yesBid"] == pytest.approx(0.48)
    assert out["yesAsk"] == pytest.approx(0.52)
    assert out["upAsk"] == pytest.approx(0.52)
    assert out["downAsk"] == pytest.approx(0.52)
    assert out["upProb"] == pytest.approx(0.50)


def test_asset_snapshot_ignores_stale_ws_quote(monkeypatch):
    from config import merge_with_defaults
    monkeypatch.setattr(kalshi_ws, "ticker_quote", lambda t: {
        "yes_bid_cents": 48, "yes_ask_cents": 52, "last_cents": 50,
        "ts_ms": time.time() * 1000.0 - 60_000,
    })
    out = _snapshot_with(monkeypatch, _rest_market(), merge_with_defaults({}))
    assert out["yesBid"] == pytest.approx(0.40)
    assert out["yesAsk"] == pytest.approx(0.60)
    assert out["downAsk"] == pytest.approx(0.62)


def test_active_tickers_reads_snapshot_cache(monkeypatch):
    monkeypatch.setitem(crypto15m._snapshot_cache, "data", {"assets": [
        {"asset": "BTC", "hasMarket": True, "ticker": "KXBTC15M-A"},
        {"asset": "ETH", "hasMarket": True, "ticker": "KXETH15M-B"},
        {"asset": "SOL", "hasMarket": False, "ticker": None},
    ]})
    assert crypto15m.active_tickers() == {"KXBTC15M-A", "KXETH15M-B"}
    monkeypatch.setitem(crypto15m._snapshot_cache, "data", None)
    assert crypto15m.active_tickers() == set()




def test_fetch_spots_prefers_cf_over_coinbase_over_rest(monkeypatch):
    monkeypatch.setattr(cf_ws, "fresh_spots", lambda: {"BTC": 68000.0})
    monkeypatch.setattr(spot_ws, "fresh_spots", lambda: {"BTC": 67990.0, "ETH": 3500.0})

    async def _run():
        crypto15m._spot_cache.update(
            at=asyncio.get_event_loop().time(),
            spots={"BTC": 67900.0, "HYPE": 30.0}, source="cryptocompare",
        )
        return await crypto15m.fetch_spots()

    spots, source = run_async(_run())
    assert spots["BTC"] == pytest.approx(68000.0)
    assert spots["ETH"] == pytest.approx(3500.0)
    assert spots["HYPE"] == pytest.approx(30.0)
    assert source == "kalshi-cf+coinbase-ws+cryptocompare"


def test_settle_partial_feeds_model_before_sampler(monkeypatch):
    from config import merge_with_defaults
    monkeypatch.setattr(kalshi_ws, "ticker_quote", lambda t: None)
    monkeypatch.setattr(cf_ws, "settle_partial", lambda a, ce: (68000.0 * 30, 30))

    def _boom(a, ce, now=None):
        raise AssertionError("sampler must not be consulted when cf has data")
    monkeypatch.setattr(spot_ws, "window_partial", _boom)

    cfg = merge_with_defaults({})

    async def _ind(_asset):
        return {"macd": None, "macdSignal": None, "macdHist": None,
                "macdCross": None, "rsi": None, "sigma1m": 0.001}
    monkeypatch.setattr(crypto15m, "asset_indicators", _ind)

    m = _rest_market()
    m["floor_strike"] = 67900.0
    out = _snapshot_with(monkeypatch, m, cfg, spot=68000.0, indicators=True)
    assert out["settlePrints"] == 30
    assert out["modelProb"] is not None
