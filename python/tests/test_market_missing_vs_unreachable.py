"""A market Kalshi says is missing vs. one we could not ask about.

The real-key smoke test of 6.4.0 opened a live market right after a burst of
searches and was told "Kalshi has no market called KXYUMTBFT-26OCT08-T99.5" —
the market existed (HTTP 200 a second later). The public gate had parked on
Kalshi's rate limit, and the market page read every failure as "missing".
Underneath, `fetch_market_checked` counted a 429 as "missing" too, which is the
answer the stop-loss arming check refuses on.
"""
from __future__ import annotations

import asyncio

import pytest

import kalshi_api
import terminal

TICKER = "KXTEST-26OCT08-T1"


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("status,expect", [
    (404, "missing"),
    (400, "missing"),
    (429, "unreachable"),
    (408, "unreachable"),
    (503, "unreachable"),
    (None, "unreachable"),
])
def test_only_kalshi_saying_no_is_missing(monkeypatch, status, expect):
    async def fake(url, params=None):
        return None, status
    monkeypatch.setattr(kalshi_api, "_pub_get_ex", fake)
    assert run(kalshi_api.fetch_market_checked(TICKER)) == (None, expect)


@pytest.fixture
def page(monkeypatch):
    monkeypatch.setattr(terminal, "_public_gate", terminal._HostGate(0))

    async def no_book(t):
        return None
    monkeypatch.setattr(terminal, "book", no_book)


def test_unreachable_market_is_not_called_missing(page, monkeypatch):
    async def fake(t):
        return None, "unreachable"
    monkeypatch.setattr(kalshi_api, "fetch_market_checked", fake)
    with pytest.raises(RuntimeError) as e:
        run(terminal.market_detail(TICKER, authed=False))
    assert "no market called" not in str(e.value)
    assert "try again" in str(e.value)


def test_parked_gate_says_so(page, monkeypatch):
    gate = terminal._HostGate(0)
    gate._parked_until = terminal.time.monotonic() + 60
    monkeypatch.setattr(terminal, "_public_gate", gate)
    with pytest.raises(RuntimeError) as e:
        run(terminal.market_detail(TICKER, authed=False))
    assert "rate-limiting" in str(e.value)
    assert "no market called" not in str(e.value)


def test_missing_market_still_says_missing(page, monkeypatch):
    async def fake(t):
        return None, "missing"
    monkeypatch.setattr(kalshi_api, "fetch_market_checked", fake)
    with pytest.raises(RuntimeError, match="no market called"):
        run(terminal.market_detail(TICKER, authed=False))
