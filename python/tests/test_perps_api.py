"""kalshi_perps_api: money helpers, signed-path/env-pinning discipline,
candle range chunking, order-body validation. No network — transport is
monkeypatched."""
from __future__ import annotations

import asyncio

import pytest

import kalshi_api
import kalshi_auth
import kalshi_perps_api as papi



def test_usd_micro_roundtrip():
    assert papi.usd_micro("6.3500") == 6_350_000
    assert papi.micro_str(6_350_000) == "6.3500"
    assert papi.usd_micro("5000.000000") == 5_000_000_000
    assert papi.usd_micro("0.0001") == 100
    assert papi.usd_micro(None) is None
    assert papi.usd_micro("garbage") is None


def test_cc_roundtrip():
    assert papi.cc("1200.00") == 120_000
    assert papi.cc("0.01") == 1
    assert papi.cc(None) is None
    assert papi.cc_str(120_000) == "1200"
    assert papi.cc_str(50) == "0.5"


def test_micro_to_usd_and_cc_to_contracts():
    assert papi.micro_to_usd(6_350_000) == 6.35
    assert papi.micro_to_usd(None) is None
    assert papi.cc_to_contracts(120_000) == 1200.0


def test_rfc3339_to_sqlite():
    assert papi.rfc3339_to_sqlite("2026-07-05T20:00:00Z") == "2026-07-05 20:00:00"
    assert papi.rfc3339_to_sqlite("2026-07-05T20:00:00.123456Z") == "2026-07-05 20:00:00"
    assert papi.rfc3339_to_sqlite("2026-07-05T20:00:00+00:00") == "2026-07-05 20:00:00"


def test_env_ticker():
    assert papi.env_ticker("KXBTCPERP", "production") == "KXBTCPERP"
    assert papi.env_ticker("kxbtcperp", "paper") == "KXBTCPERP"


def test_paper_refuses_every_signed_perps_call(monkeypatch):
    """Perps have no paper book. In Paper a signed perps call is refused
    before anything is signed or sent."""
    def _sign(*_a):
        raise AssertionError("must not sign in paper")
    monkeypatch.setattr(papi, "sign_headers", _sign)
    monkeypatch.setattr(papi, "get_env", lambda: "paper")
    with pytest.raises(kalshi_api.KalshiAPIError) as ei:
        asyncio.run(papi._signed_request("GET", "/margin/balance"))
    assert ei.value.status == 403 and "paper_mode" in str(ei.value.body)
    with pytest.raises(kalshi_api.KalshiAPIError):
        asyncio.run(papi._signed_request("GET", "/margin/balance", pin_env="paper"))



class _FakeResp:
    def __init__(self, status: int, body):
        self.status_code = status
        self._body = body
        self.headers = {}
        self.text = str(body)

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.is_closed = False

    async def request(self, method, path, **kw):
        self.calls.append((method, path, kw))
        return self.responses.pop(0)

    async def get(self, path, params=None):
        self.calls.append(("GET", path, {"params": params}))
        return self.responses.pop(0)

    async def aclose(self):
        self.is_closed = True


def test_signed_request_signs_full_margin_path(monkeypatch):
    """The RSA signature must cover /trade-api/v2/margin/... — signing the
    bare /margin path is a guaranteed 401."""
    seen = {}

    def fake_sign(method, path):
        seen["path"] = path
        return {"KALSHI-ACCESS-KEY": "k"}

    fake = _FakeClient([_FakeResp(200, {"ok": True})])

    async def fake_client():
        return fake

    monkeypatch.setattr(papi, "sign_headers", fake_sign)
    monkeypatch.setattr(papi, "_get_signed_client", fake_client)
    out = asyncio.run(papi._signed_request("GET", "/margin/balance"))
    assert out == {"ok": True}
    assert seen["path"] == "/trade-api/v2/margin/balance"


def test_env_pinning_aborts_on_flip(monkeypatch):
    envs = iter(["production", "paper", "paper"])
    monkeypatch.setattr(papi, "get_env", lambda: next(envs))
    monkeypatch.setattr(papi, "sign_headers", lambda m, p: {})
    fake = _FakeClient([_FakeResp(500, {}), _FakeResp(200, {"ok": True})])

    async def fake_client():
        return fake

    monkeypatch.setattr(papi, "_get_signed_client", fake_client)
    with pytest.raises(kalshi_api.KalshiAPIError) as ei:
        asyncio.run(papi._signed_request("GET", "/margin/balance"))
    assert ei.value.status == 409


def test_401_timestamp_self_heal(monkeypatch):
    calls = {"sync": 0}
    monkeypatch.setattr(papi, "sign_headers", lambda m, p: {})
    monkeypatch.setattr(papi, "get_env", lambda: "production")

    def fake_sync(force):
        calls["sync"] += 1
        return 0

    monkeypatch.setattr(papi, "sync_server_time", fake_sync)
    fake = _FakeClient([
        _FakeResp(401, {"error": {"code": "timestamp_expired"}}),
        _FakeResp(200, {"ok": True}),
    ])

    async def fake_client():
        return fake

    monkeypatch.setattr(papi, "_get_signed_client", fake_client)
    out = asyncio.run(papi._signed_request("GET", "/margin/balance"))
    assert out == {"ok": True}
    assert calls["sync"] == 1


def test_pub_get_soft_fails_to_none(monkeypatch):
    import httpx

    class _NetFailClient:
        is_closed = False

        async def get(self, path, params=None):
            raise httpx.ConnectError("no route")

    async def fake_client():
        return _NetFailClient()

    monkeypatch.setattr(papi, "_get_pub_client", fake_client)
    monkeypatch.setattr(papi, "RETRY_BACKOFF", 0.0)
    assert asyncio.run(papi._pub_get("/margin/markets")) is None
    assert asyncio.run(papi.fetch_perps_markets()) == []



def test_period_interval_validated():
    with pytest.raises(ValueError):
        asyncio.run(papi.fetch_perps_candlesticks("KXBTCPERP", 0, 60, 15))


def _mk_candle(end_ts):
    return {"end_period_ts": end_ts}


def test_candles_range_chunks_and_dedupes(monkeypatch):
    """Full window coverage across chunk boundaries, no duplicate periods,
    truncated pages resume from the last candle instead of skipping ahead."""
    windows = []

    async def fake_fetch(ticker, start_ts, end_ts, period):
        windows.append((start_ts, end_ts))
        if len(windows) == 1:
            return [_mk_candle(t) for t in range(start_ts, start_ts + 5 * 60, 60)]
        return [_mk_candle(t) for t in range(start_ts, min(end_ts, start_ts + 5 * 60), 60)]

    monkeypatch.setattr(papi, "fetch_perps_candlesticks", fake_fetch)
    monkeypatch.setattr(papi, "CANDLE_CHUNK", 10)

    out = asyncio.run(papi.fetch_perps_candlesticks_range(
        "KXBTCPERP", 0, 1500, 1, sleep_between=0.0,
    ))
    ends = [c["end_period_ts"] for c in out]
    assert ends == sorted(set(ends)), "duplicated or unsorted periods"
    assert windows[0] == (0, 600)
    assert windows[1][0] == 300


def test_candles_range_terminates_on_empty(monkeypatch):
    async def fake_fetch(ticker, start_ts, end_ts, period):
        return []

    monkeypatch.setattr(papi, "fetch_perps_candlesticks", fake_fetch)
    out = asyncio.run(papi.fetch_perps_candlesticks_range(
        "KXBTCPERP", 0, 10_000_000, 1, sleep_between=0.0, max_requests=5,
    ))
    assert out == []



def test_place_order_validation():
    with pytest.raises(ValueError):
        asyncio.run(papi.place_perps_limit_order(
            ticker="KXBTCPERP", side="yes", count_cc=100, price_usd_micro=6_350_000,
        ))
    with pytest.raises(ValueError):
        asyncio.run(papi.place_perps_limit_order(
            ticker="KXBTCPERP", side="bid", count_cc=0, price_usd_micro=6_350_000,
        ))
    with pytest.raises(ValueError):
        asyncio.run(papi.place_perps_limit_order(
            ticker="KXBTCPERP", side="ask", count_cc=100,
            price_usd_micro=6_350_000, reduce_only=True,
        ))


def test_place_order_body_is_fixed_point_strings(monkeypatch):
    fake = _FakeClient([_FakeResp(200, {"order_id": "x", "fill_count": "0",
                                        "remaining_count": "1"})])

    async def fake_client():
        return fake

    monkeypatch.setattr(papi, "_get_signed_client", fake_client)
    monkeypatch.setattr(papi, "sign_headers", lambda m, p: {})
    monkeypatch.setattr(papi, "get_env", lambda: "production")
    asyncio.run(papi.place_perps_limit_order(
        ticker="KXBTCPERP", side="bid", count_cc=100,
        price_usd_micro=6_350_100, time_in_force="immediate_or_cancel",
    ))
    method, path, kw = fake.calls[0]
    body = kw["json"]
    assert path == "/trade-api/v2/margin/orders"
    assert body["price"] == "6.3501"
    assert body["count"] == "1"
    assert body["side"] == "bid"
    assert body["time_in_force"] == "immediate_or_cancel"
    assert body["client_order_id"]
