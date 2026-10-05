from __future__ import annotations

import asyncio
import time

import pytest

import crypto15m_trader as ct
import kalshi_api
import kalshi_ws
import service


def run_async(coro):
    return asyncio.run(coro)



class _FakeResp:
    def __init__(self, status_code=200, body=None):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.headers = {}

    def json(self):
        return self._body

    @property
    def text(self):
        return str(self._body)


def _stub_signing(monkeypatch, envs: list[str]):
    seq = list(envs)

    def _env():
        return seq.pop(0) if len(seq) > 1 else seq[0]

    monkeypatch.setattr(kalshi_api, "get_env", _env)
    monkeypatch.setattr(kalshi_api, "sign_headers", lambda m, p: {})
    return _env


def test_signed_request_aborts_when_env_flips_mid_retry(monkeypatch):
    _stub_signing(monkeypatch, ["production", "demo"])

    import httpx

    class _Client:
        async def request(self, *a, **k):
            raise httpx.ConnectTimeout("boom")

    async def _client():
        return _Client()

    monkeypatch.setattr(kalshi_api, "_get_signed_client", _client)

    async def _sleep(_s):
        return None

    monkeypatch.setattr(kalshi_api.asyncio, "sleep", _sleep)

    with pytest.raises(kalshi_api.KalshiAPIError) as ei:
        run_async(kalshi_api._signed_request("GET", "/portfolio/balance"))
    assert ei.value.status == 409
    assert "env_changed" in str(ei.value.body)


def test_signed_request_pin_env_rejects_preflipped_env(monkeypatch):
    _stub_signing(monkeypatch, ["demo"])
    sent = {"n": 0}

    class _Client:
        async def request(self, *a, **k):
            sent["n"] += 1
            return _FakeResp(200, {})

    async def _client():
        return _Client()

    monkeypatch.setattr(kalshi_api, "_get_signed_client", _client)

    with pytest.raises(kalshi_api.KalshiAPIError) as ei:
        run_async(kalshi_api._signed_request(
            "POST", kalshi_api.ORDERS_V2_PATH, json={}, pin_env="production",
        ))
    assert ei.value.status == 409
    assert sent["n"] == 0


def test_signed_request_happy_path_single_env(monkeypatch):
    _stub_signing(monkeypatch, ["production"])

    class _Client:
        async def request(self, *a, **k):
            return _FakeResp(200, {"balance": 123})

    async def _client():
        return _Client()

    monkeypatch.setattr(kalshi_api, "_get_signed_client", _client)
    out = run_async(kalshi_api._signed_request("GET", "/portfolio/balance"))
    assert out == {"balance": 123}



def _ws_quote(monkeypatch, quote):
    monkeypatch.setattr(kalshi_ws, "ticker_quote", lambda t: quote)


def test_ws_quote_market_fresh_quote_maps_to_market_shape(monkeypatch):
    now_ms = time.time() * 1000.0
    _ws_quote(monkeypatch, {
        "yes_bid_cents": 55, "yes_ask_cents": 58, "last_cents": 56,
        "ts_ms": now_ms - 1000,
    })
    m = ct._ws_quote_market("KXBTC15M-T1")
    assert m is not None
    assert m["yes_bid_dollars"] == pytest.approx(0.55)
    assert m["yes_ask_dollars"] == pytest.approx(0.58)
    assert ct.side_prob_from_market(m, "yes") == pytest.approx(0.565)


def test_ws_quote_market_rejects_stale_or_missing(monkeypatch):
    now_ms = time.time() * 1000.0
    _ws_quote(monkeypatch, {
        "yes_bid_cents": 55, "yes_ask_cents": 58, "last_cents": 56,
        "ts_ms": now_ms - 60_000,
    })
    assert ct._ws_quote_market("KXBTC15M-T1") is None
    _ws_quote(monkeypatch, None)
    assert ct._ws_quote_market("KXBTC15M-T1") is None
    _ws_quote(monkeypatch, {"ts_ms": 0})
    assert ct._ws_quote_market("KXBTC15M-T1") is None


def test_ws_quote_market_rejects_empty_quote(monkeypatch):
    _ws_quote(monkeypatch, {
        "yes_bid_cents": None, "yes_ask_cents": None, "last_cents": None,
        "ts_ms": time.time() * 1000.0,
    })
    assert ct._ws_quote_market("KXBTC15M-T1") is None



def test_on_ws_trade_flags_whale_sized_prints():
    service.STATE.cfg = dict(service.STATE.cfg, min_whale_usd=2500)
    service.STATE.ws_whale_pending = False

    service._on_ws_trade({"count_fp": "300", "taker_side": "yes",
                          "yes_price_dollars": "0.60"})
    assert service.STATE.ws_whale_pending is False

    service._on_ws_trade({"count_fp": "5000", "taker_side": "yes",
                          "yes_price_dollars": "0.60"})
    assert service.STATE.ws_whale_pending is True

    service.STATE.ws_whale_pending = False
    service._on_ws_trade({"count_fp": "10000", "taker_side": "no",
                          "yes_price_dollars": "0.97", "no_price_dollars": "0.03"})
    assert service.STATE.ws_whale_pending is False

    service._on_ws_trade({"count_fp": "abc"})
    service.STATE.ws_whale_pending = False


def test_on_ws_fill_wakes_both_pollers():
    service.STATE.ws_fill_pending = False
    service.STATE.ws_c15_pending = False
    service._on_ws_fill({})
    assert service.STATE.ws_fill_pending is True
    assert service.STATE.ws_c15_pending is True
    service.STATE.ws_fill_pending = False
    service.STATE.ws_c15_pending = False
