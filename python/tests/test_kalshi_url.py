from __future__ import annotations

import asyncio

import kalshi_api


def _run(coro):
    return asyncio.run(coro)


def _stub_series(title):
    async def _fetch(_series_ticker):
        return {"title": title} if title is not None else None
    return _fetch




def test_slugify_matches_live_url():
    assert kalshi_api._slugify("Bitcoin price Above/below") == "bitcoin-price-abovebelow"


def test_slugify_collapses_and_trims():
    assert kalshi_api._slugify("  S&P 500  Daily ") == "sp-500-daily"
    assert kalshi_api._slugify("") == ""


def test_event_from_ticker_strips_strike():
    assert kalshi_api._event_from_ticker("KXBTCD-26JUN1400-T72299.99") == "KXBTCD-26JUN1400"
    assert kalshi_api._event_from_ticker("KXBTCD-26JUN1400") == "KXBTCD-26JUN1400"
    assert kalshi_api._event_from_ticker("") == ""




def test_deep_link_production(monkeypatch):
    monkeypatch.setattr(kalshi_api, "fetch_series", _stub_series("Bitcoin price Above/below"))
    url = _run(kalshi_api.web_market_url(
        event_ticker="KXBTCD-26JUN1400",
        ticker="KXBTCD-26JUN1400-T72299.99",
        env="production",
    ))
    assert url == "https://kalshi.com/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-26jun1400"


def test_deep_link_demo_host_and_event_derived_from_ticker(monkeypatch):
    monkeypatch.setattr(kalshi_api, "fetch_series", _stub_series("Bitcoin price Above/below"))
    url = _run(kalshi_api.web_market_url(
        ticker="KXBTCD-26JUN1400-T72299.99",
        env="demo",
    ))
    assert url == "https://demo.kalshi.co/markets/kxbtcd/bitcoin-price-abovebelow/kxbtcd-26jun1400"


def test_falls_back_to_series_page_when_no_slug(monkeypatch):
    monkeypatch.setattr(kalshi_api, "fetch_series", _stub_series(None))
    url = _run(kalshi_api.web_market_url(event_ticker="KXNBA-26JUN12", env="production"))
    assert url == "https://kalshi.com/markets/kxnba"


def test_falls_back_to_series_page_when_lookup_raises(monkeypatch):
    async def _boom(_s):
        raise RuntimeError("network down")
    monkeypatch.setattr(kalshi_api, "fetch_series", _boom)
    url = _run(kalshi_api.web_market_url(ticker="KXETHD-26JUN1400-T2000", env="demo"))
    assert url == "https://demo.kalshi.co/markets/kxethd"


def test_unknown_env_defaults_to_production_host(monkeypatch):
    monkeypatch.setattr(kalshi_api, "fetch_series", _stub_series("Whatever"))
    url = _run(kalshi_api.web_market_url(event_ticker="KXFOO-1", env="staging"))
    assert url.startswith("https://kalshi.com/markets/kxfoo/")


def test_empty_inputs_return_empty_string():
    assert _run(kalshi_api.web_market_url(env="production")) == ""
    assert _run(kalshi_api.web_market_url(ticker="", event_ticker="", env="demo")) == ""
