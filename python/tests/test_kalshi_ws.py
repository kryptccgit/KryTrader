from __future__ import annotations

import asyncio
import json

import kalshi_ws
from kalshi_ws import _Client, _cents


def _trade(ticker="M", tid="a", ts=1):
    return {"type": "trade", "msg": {
        "market_ticker": ticker, "trade_id": tid, "count_fp": "5.00",
        "yes_price_dollars": "0.30", "no_price_dollars": "0.70",
        "taker_side": "yes", "ts_ms": ts,
    }}


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send(self, raw):
        self.sent.append(json.loads(raw))


def _subs_for(ws, channel):
    return [m for m in ws.sent
            if m.get("cmd") == "subscribe"
            and channel in (m.get("params") or {}).get("channels", [])]


def _snapshot(ticker="T1", seq=5):
    return {
        "type": "orderbook_snapshot", "sid": 2, "seq": seq,
        "msg": {
            "market_ticker": ticker,
            "yes_dollars_fp": [["0.40", "100.00"], ["0.42", "50.00"]],
            "no_dollars_fp": [["0.55", "30.00"]],
        },
    }


def _delta(ticker, seq, price, delta, side):
    return {
        "type": "orderbook_delta", "seq": seq,
        "msg": {"market_ticker": ticker, "price_dollars": price,
                "delta_fp": delta, "side": side},
    }


def test_cents_parses_dollar_strings():
    assert _cents("0.40") == 40
    assert _cents("0.965") == 96.5
    assert _cents("0.9470") == 94.7
    assert _cents("1.00") == 100
    assert _cents(None) is None
    assert _cents("nope") is None


def test_snapshot_builds_book_and_best_bid():
    c = _Client()
    c.connected = True
    c._handle(_snapshot("T1", seq=5))
    ob = c.orderbook("T1")
    assert ob is not None
    assert sorted(ob["yes"]) == [[40, 100.0], [42, 50.0]]
    assert ob["no"] == [[55, 30.0]]
    assert c.best_bid_cents("T1", "yes") == 42
    assert c.best_bid_cents("T1", "no") == 55


def test_delta_add_and_remove_levels():
    c = _Client()
    c.connected = True
    c._handle(_snapshot("T1", seq=5))
    c._handle(_delta("T1", 6, "0.42", "25.00", "yes"))
    assert dict(c.books["T1"]["yes"])[42] == 75.0
    c._handle(_delta("T1", 7, "0.40", "-100.00", "yes"))
    assert 40 not in c.books["T1"]["yes"]
    assert c.best_bid_cents("T1", "yes") == 42


def test_stale_or_duplicate_delta_ignored():
    c = _Client()
    c.connected = True
    c._handle(_snapshot("T1", seq=5))
    c._handle(_delta("T1", 6, "0.42", "10.00", "yes"))
    before = dict(c.books["T1"]["yes"])
    c._handle(_delta("T1", 6, "0.42", "999.00", "yes"))
    c._handle(_delta("T1", 4, "0.42", "999.00", "yes"))
    assert dict(c.books["T1"]["yes"]) == before


def test_seq_gap_invalidates_book_and_queues_resnapshot():
    c = _Client()
    c.connected = True
    c._handle(_snapshot("T1", seq=5))
    assert c.orderbook("T1") is not None
    c._handle(_delta("T1", 9, "0.42", "10.00", "yes"))
    assert c.orderbook("T1") is None
    assert c.best_bid_cents("T1", "yes") is None
    assert "T1" in c._resnap
    c._handle(_snapshot("T1", seq=20))
    assert c.orderbook("T1") is not None


def test_reads_return_none_when_disconnected():
    c = _Client()
    c._handle(_snapshot("T1", seq=5))
    c.connected = False
    assert c.orderbook("T1") is None
    assert c.best_bid_cents("T1", "yes") is None
    assert c.recent_trades() is None
    assert c.ticker_quote("T1") is None


def test_ticker_quote_parsed_to_cents():
    c = _Client()
    c.connected = True
    c._handle({"type": "ticker", "msg": {
        "market_ticker": "T1", "yes_bid_dollars": "0.45",
        "yes_ask_dollars": "0.53", "price_dollars": "0.48",
        "volume_fp": "100.00", "open_interest_fp": "50.00",
    }})
    q = c.ticker_quote("T1")
    assert q["yes_bid_cents"] == 45
    assert q["yes_ask_cents"] == 53
    assert q["last_cents"] == 48


def test_trade_buffer_matches_rest_shape_newest_first():
    c = _Client()
    c.connected = True
    for i, side in enumerate(("yes", "no")):
        c._handle({"type": "trade", "msg": {
            "market_ticker": f"M{i}", "trade_id": f"id{i}",
            "count_fp": "5.00", "yes_price_dollars": "0.30",
            "no_price_dollars": "0.70", "taker_side": side, "ts_ms": 100 + i,
        }})
    rt = c.recent_trades(10)
    assert len(rt) == 2
    assert rt[0]["trade_id"] == "id1"
    assert rt[0]["ticker"] == "M1"
    assert rt[0]["count_fp"] == "5.00"
    assert rt[0]["yes_price_dollars"] == "0.30"
    assert rt[0]["taker_side"] == "no"


def test_recent_trades_goes_stale_then_recovers():
    c = _Client()
    c.connected = True
    clock = {"t": 1000.0}
    c._loop_time = lambda: clock["t"]
    c._handle(_trade(tid="a"))
    assert c.recent_trades() is not None
    clock["t"] += kalshi_ws._TRADE_STALE_SEC + 1
    assert c.recent_trades() is None
    c._handle(_trade(tid="b"))
    assert c.recent_trades() is not None


def test_reset_sub_state_clears_trade_buffer():
    c = _Client()
    c.connected = True
    c._handle(_trade(tid="a"))
    assert c.recent_trades() is not None
    c._reset_sub_state()
    assert len(c.trades) == 0
    assert c.recent_trades() is None


def test_account_sub_acked_once_is_not_retried():
    c = _Client()
    clock = {"t": 0.0}
    c._loop_time = lambda: clock["t"]
    ws = _FakeWS()
    asyncio.run(c._subscribe_account(ws))
    assert len(_subs_for(ws, "trade")) == 1
    trade_cid = next(m["id"] for m in ws.sent
                     if "trade" in m["params"]["channels"])
    c._on_subscribed({"id": trade_cid, "msg": {}})
    assert "trade" in c._account_subbed
    clock["t"] += kalshi_ws._ACCOUNT_RESUB_THROTTLE_SEC + 1
    asyncio.run(c._subscribe_account(ws))
    assert len(_subs_for(ws, "trade")) == 1


def test_account_sub_retries_then_gives_up_when_never_acked():
    c = _Client()
    clock = {"t": 0.0}
    c._loop_time = lambda: clock["t"]
    ws = _FakeWS()
    for _ in range(kalshi_ws._ACCOUNT_RESUB_MAX_TRIES + 3):
        asyncio.run(c._subscribe_account(ws))
        clock["t"] += kalshi_ws._ACCOUNT_RESUB_THROTTLE_SEC + 1
    assert len(_subs_for(ws, "trade")) == kalshi_ws._ACCOUNT_RESUB_MAX_TRIES
    assert "trade" not in c._account_subbed


def test_account_sub_throttled_within_window():
    c = _Client()
    clock = {"t": 0.0}
    c._loop_time = lambda: clock["t"]
    ws = _FakeWS()
    asyncio.run(c._subscribe_account(ws))
    asyncio.run(c._subscribe_account(ws))
    assert len(_subs_for(ws, "trade")) == 1


def test_set_market_sets_filter_blanks():
    c = _Client()
    c.set_orderbook_markets({"A", "B", "", None})
    assert c.want_orderbook == {"A", "B"}
    c.set_ticker_markets(["X", "X", "Y"])
    assert c.want_ticker == {"X", "Y"}


def test_stats_shape():
    s = kalshi_ws.stats()
    assert "enabled" in s and "connected" in s and "env" in s
