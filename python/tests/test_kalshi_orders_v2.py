from __future__ import annotations

import asyncio

import kalshi_api


def test_v2_fields_yes_buy():
    assert kalshi_api._v2_order_fields("yes", "buy", 94) == ("bid", "0.9400")


def test_v2_fields_yes_sell():
    assert kalshi_api._v2_order_fields("yes", "sell", 30) == ("ask", "0.3000")


def test_v2_fields_no_buy_mirrors_to_yes_ask():
    assert kalshi_api._v2_order_fields("no", "buy", 94) == ("ask", "0.0600")


def test_v2_fields_no_sell_mirrors_to_yes_bid():
    assert kalshi_api._v2_order_fields("no", "sell", 30) == ("bid", "0.7000")


def test_place_limit_order_posts_v2_events_path(monkeypatch):
    captured: dict = {}

    async def fake_signed(method, path, *, json=None, params=None, **kw):
        captured.update(method=method, path=path, json=json)
        return {"order_id": "ord_1", "fill_count": "0", "remaining_count": "5"}

    monkeypatch.setattr(kalshi_api, "_signed_request", fake_signed)

    resp = asyncio.run(kalshi_api.place_limit_order(
        ticker="KXBTC15M-T1", side="no", action="buy",
        count=5, price_cents=94, client_order_id="cid-1",
    ))

    assert resp["order_id"] == "ord_1"
    assert captured["method"] == "POST"
    assert captured["path"] == "/portfolio/events/orders"
    assert captured["json"] == {
        "ticker": "KXBTC15M-T1",
        "client_order_id": "cid-1",
        "side": "ask",
        "count": "5.00",
        "price": "0.0600",
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": "taker_at_cross",
        "exchange_index": -1,
    }


def test_place_limit_order_yes_buy_body(monkeypatch):
    captured: dict = {}

    async def fake_signed(method, path, *, json=None, params=None, **kw):
        captured.update(json=json)
        return {"order_id": "ord_2"}

    monkeypatch.setattr(kalshi_api, "_signed_request", fake_signed)

    asyncio.run(kalshi_api.place_limit_order(
        ticker="KXETH15M-T1", side="yes", action="buy",
        count=3, price_cents=88, client_order_id="cid-2",
    ))

    assert captured["json"]["side"] == "bid"
    assert captured["json"]["price"] == "0.8800"
    assert captured["json"]["count"] == "3.00"


def test_cancel_order_uses_v2_events_path(monkeypatch):
    captured: dict = {}

    async def fake_signed(method, path, *, json=None, params=None, **kw):
        captured.update(method=method, path=path)
        return {"order_id": "ord_1", "reduced_by": "5"}

    monkeypatch.setattr(kalshi_api, "_signed_request", fake_signed)
    asyncio.run(kalshi_api.cancel_order("ord_1"))

    assert captured["method"] == "DELETE"
    assert captured["path"] == "/portfolio/events/orders/ord_1"


def test_place_limit_order_rejects_bad_inputs():
    for bad in (
        dict(ticker="T", side="maybe", action="buy", count=1, price_cents=50),
        dict(ticker="T", side="yes", action="hold", count=1, price_cents=50),
        dict(ticker="T", side="yes", action="buy", count=1, price_cents=0),
        dict(ticker="T", side="yes", action="buy", count=1, price_cents=100),
        dict(ticker="T", side="yes", action="buy", count=0, price_cents=50),
    ):
        try:
            asyncio.run(kalshi_api.place_limit_order(**bad))
        except ValueError:
            continue
        raise AssertionError(f"expected ValueError for {bad}")



def test_get_positions_raises_on_page_cap(monkeypatch):
    async def fake_signed(method, path, *, json=None, params=None, **kw):
        return {
            "market_positions": [{"ticker": "T", "position": 1}],
            "cursor": "more",
        }

    monkeypatch.setattr(kalshi_api, "_signed_request", fake_signed)
    try:
        asyncio.run(kalshi_api.get_positions(limit=1000))
    except kalshi_api.KalshiTruncatedResult:
        return
    raise AssertionError("expected KalshiTruncatedResult at the page cap")


def test_get_positions_returns_when_cursor_exhausts(monkeypatch):
    calls = {"n": 0}

    async def fake_signed(method, path, *, json=None, params=None, **kw):
        calls["n"] += 1
        return {
            "market_positions": [{"ticker": f"T{calls['n']}", "position": 1}],
            "cursor": "more" if calls["n"] < 3 else "",
        }

    monkeypatch.setattr(kalshi_api, "_signed_request", fake_signed)
    out = asyncio.run(kalshi_api.get_positions(limit=1000))
    assert len(out) == 3
