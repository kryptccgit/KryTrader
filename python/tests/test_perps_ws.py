"""perps_ws: wire-frame parsing into micro-units, drain semantics, sub
ACK/NAK bookkeeping, buffer caps, reconnect state. Frames are driven as raw
dicts through _handle (test_kalshi_ws pattern) — no sockets."""
from __future__ import annotations

import pytest

import perps_ws


@pytest.fixture
def client():
    c = perps_ws._Client()
    c.env = "production"
    c.connected = True
    return c


def _ticker_frame(ticker="KXBTCPERP", **over):
    msg = {
        "market_ticker": ticker,
        "price": "6.3542",
        "bid": "6.3495",
        "ask": "6.3530",
        "bid_size_fp": "1200.00",
        "ask_size_fp": "800.00",
        "last_trade_size_fp": "5.00",
        "volume": "1605598112.00",
        "volume_notional_value_dollars": "10084034769.2675",
        "volume_24h": "5231866.00",
        "volume_24h_notional_value_dollars": "32960317.9976",
        "open_interest": "718719.00",
        "open_interest_notional_value_dollars": "4566884.2698",
        "reference_price": {"price": "6.3529", "ts_ms": 1783295841000},
        "settlement_mark_price": {"price": "6.3536", "ts_ms": 1783295837134},
        "liquidation_mark_price": {"price": "6.3530", "ts_ms": 1783295840000},
        "funding_rate": 0.0002,
        "ts_ms": 1783295841500,
    }
    msg.update(over)
    return {"type": "ticker", "sid": 1, "msg": msg}


def test_ticker_parsed_to_micro_units(client):
    client._handle(_ticker_frame())
    rows = client.drain_ticks()
    assert len(rows) == 1
    r = rows[0]
    assert r["ticker"] == "KXBTCPERP"
    assert r["last_usd_micro"] == 6_354_200
    assert r["bid_usd_micro"] == 6_349_500
    assert r["ask_usd_micro"] == 6_353_000
    assert r["bid_size_cc"] == 120_000
    assert r["ask_size_cc"] == 80_000
    assert r["ref_usd_micro"] == 6_352_900
    assert r["ref_ts_ms"] == 1783295841000
    assert r["settle_mark_usd_micro"] == 6_353_600
    assert r["liq_mark_usd_micro"] == 6_353_000
    assert r["funding_rate"] == pytest.approx(0.0002)
    assert r["ts_ms"] == 1783295841500
    assert r["src"] == "ws"
    assert r["kalshi_env"] == "production"
    assert client.drain_ticks() == []


def test_ticker_optional_fields_none(client):
    client._handle(_ticker_frame(
        reference_price=None, settlement_mark_price=None,
        liquidation_mark_price=None, funding_rate=None,
    ))
    r = client.drain_ticks()[0]
    assert r["ref_usd_micro"] is None
    assert r["settle_mark_usd_micro"] is None
    assert r["funding_rate"] is None


def test_ticker_nested_funding_rate_dict(client):
    client._handle(_ticker_frame(
        funding_rate={"rate": 0.0011, "next_funding_time_ms": 1783310400000},
    ))
    r = client.drain_ticks()[0]
    assert r["funding_rate"] == pytest.approx(0.0011)
    assert r["next_funding_ms"] == 1783310400000


def test_trade_parsed_and_taker_side_verbatim(client):
    client._handle({"type": "trade", "sid": 2, "msg": {
        "trade_id": "abc-123",
        "market_ticker": "KXBTCPERP",
        "price": "6.3521",
        "count": "5.00",
        "taker_side": "bid",
        "ts_ms": 1783295841000,
    }})
    rows = client.drain_trades()
    assert len(rows) == 1
    r = rows[0]
    assert r["price_usd_micro"] == 6_352_100
    assert r["count_cc"] == 500
    assert r["taker_side"] == "bid"
    assert client.drain_trades() == []


def test_malformed_frames_dropped_silently(client):
    client._handle({"type": "ticker", "msg": {}})
    client._handle({"type": "trade", "msg": {"market_ticker": "X",
                                             "price": "junk", "count": "1.00"}})
    client._handle({"type": "unknown_type", "msg": {"x": 1}})
    assert client.drain_ticks() == []
    assert client.drain_trades() == []


def test_quote_cache_latest_wins(client):
    client._handle(_ticker_frame(price="6.0000"))
    client._handle(_ticker_frame(price="6.1000"))
    assert client.quote("KXBTCPERP")["last_usd_micro"] == 6_100_000
    client.connected = False
    assert client.quote("KXBTCPERP") is None


def test_subscribe_ack_nak_bookkeeping(client):
    client._chan_sids["ticker"] = -1
    client._inflight[7] = ("chan", "ticker")
    client._handle({"type": "subscribed", "id": 7, "msg": {"channel": "ticker", "sid": 42}})
    assert client._chan_sids["ticker"] == 42

    client._chan_sids["trade"] = -1
    client._inflight[8] = ("chan", "trade")
    client._handle({"type": "error", "id": 8, "msg": {"code": 6, "msg": "nope"}})
    assert "trade" not in client._chan_sids


def test_reconnect_clears_subs_keeps_buffers(client):
    client._handle(_ticker_frame())
    client._chan_sids["ticker"] = 42
    client._inflight[1] = ("chan", "trade")
    client._reset_sub_state()
    assert client._chan_sids == {}
    assert client._inflight == {}
    assert len(client.drain_ticks()) == 1


def test_buffer_cap_drops_oldest(client, monkeypatch):
    monkeypatch.setattr(perps_ws, "_TICK_BUF_MAX", 50)
    for i in range(60):
        client._handle(_ticker_frame(ts_ms=i))
    rows = client.drain_ticks()
    assert len(rows) <= 50
    assert client.dropped_ticks > 0
    assert rows[-1]["ts_ms"] == 59


def test_kill_switch_env_var(monkeypatch):
    monkeypatch.setattr(perps_ws, "_DISABLED", True)
    c = perps_ws._Client()
    c.start("production")
    assert c._task is None


def test_stats_shape(client):
    s = client.stats()
    for key in ("enabled", "connected", "env", "symbols", "bufferedTicks",
                "bufferedTrades", "droppedTicks", "droppedTrades"):
        assert key in s
