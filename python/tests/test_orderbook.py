from __future__ import annotations

import kalshi_api
import trader


def test_normalize_fp_dollars_to_cents():
    raw = {"orderbook_fp": {"no_dollars": [["0.3800", "12.00"]], "yes_dollars": []}}
    assert kalshi_api._normalize_orderbook(raw) == {"yes": [], "no": [[38, 12.0]]}


def test_normalize_legacy_cents():
    raw = {"orderbook": {"yes": [[30, 10]], "no": [[45, 5], [40, 3]]}}
    book = kalshi_api._normalize_orderbook(raw)
    assert book["yes"] == [[30, 10.0]]
    assert book["no"] == [[45, 5.0], [40, 3.0]]


def test_normalize_garbage_is_empty():
    assert kalshi_api._normalize_orderbook(None) == {"yes": [], "no": []}
    assert kalshi_api._normalize_orderbook({}) == {"yes": [], "no": []}


def test_fp_orderbook_restores_cross_pricing():
    raw = {"orderbook_fp": {"no_dollars": [["0.38", "12"]], "yes_dollars": []}}
    book = kalshi_api._normalize_orderbook(raw)
    assert trader._best_cross_price_cents(book, "yes") == 62


def test_cross_pricing_rounds_decicent_levels_not_truncates():
    """Main-engine regression: book levels are deci-cent floats now. int(5.7)
    truncated to 5 -> cross 95c, a 1c overbid vs the historical round(5.7)=6 ->
    cross 94c behavior."""
    raw = {"orderbook_fp": {"no_dollars": [["0.0570", "100.00"]], "yes_dollars": []}}
    book = kalshi_api._normalize_orderbook(raw)
    assert book["no"] == [[5.7, 100.0]]
    assert trader._best_cross_price_cents(book, "yes") == 94


def test_normalize_preserves_decicent_levels():
    """tapered_deci_cent books (all 7 15m crypto series) carry real 0.1c levels
    in the deep-favorite band — quantizing to whole cents merged them and made
    resting exits look 'at the bid' 0.1-0.5c above the TRUE bid (never filled).
    Live wire shape verified 2026-07-16: dollar strings at 3dp ("0.0110")."""
    raw = {"orderbook_fp": {
        "yes_dollars": [["0.9470", "100.00"], ["0.9480", "50.00"]],
        "no_dollars": [["0.0110", "651.00"]],
    }}
    book = kalshi_api._normalize_orderbook(raw)
    assert book["yes"] == [[94.7, 100.0], [94.8, 50.0]]
    assert book["no"] == [[1.1, 651.0]]


def test_place_limit_order_decicent_validation(monkeypatch):
    """Deci-cent prices are accepted and hit the wire as exact 4dp dollars;
    off-grid prices are rejected before any network call."""
    import asyncio
    sent = {}

    async def _capture(method, path, **kw):
        sent.update(kw.get("json") or {})
        return {"order": {"order_id": "X"}}
    monkeypatch.setattr(kalshi_api, "_signed_request", _capture)

    asyncio.run(kalshi_api.place_limit_order(
        ticker="KXBTC15M-T", side="yes", action="sell", count=4, price_cents=94.7))
    assert sent["price"] == "0.9470"
    assert sent["side"] == "ask"

    sent.clear()
    asyncio.run(kalshi_api.place_limit_order(
        ticker="KXBTC15M-T", side="no", action="sell", count=1, price_cents=1.1))
    assert sent["price"] == "0.9890"

    import pytest
    with pytest.raises(ValueError):
        asyncio.run(kalshi_api.place_limit_order(
            ticker="T", side="yes", action="sell", count=1, price_cents=94.75))
    with pytest.raises(ValueError):
        asyncio.run(kalshi_api.place_limit_order(
            ticker="T", side="yes", action="sell", count=1, price_cents=0.05))
