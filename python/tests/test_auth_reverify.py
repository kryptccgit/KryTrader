from __future__ import annotations

import asyncio

import pytest

import kalshi_api
import kalshi_auth
import service


def run_async(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _base(monkeypatch):
    service.STATE.auth_ok = False

    async def _noop_emit(*a, **k):
        return None

    monkeypatch.setattr(service, "emit_event", _noop_emit)
    monkeypatch.setattr(kalshi_auth, "get_env", lambda: "demo")
    monkeypatch.setattr(kalshi_auth, "prime_credentials", lambda *a, **k: True)
    monkeypatch.setattr(kalshi_auth, "sync_server_time", lambda *a, **k: 0)
    yield
    service.STATE.auth_ok = False


def test_reverify_recovers_when_creds_valid(monkeypatch):
    monkeypatch.setattr(kalshi_auth, "credentials_present", lambda env=None: True)

    async def _bal(*a, **k):
        return {"balance": 4200}

    monkeypatch.setattr(kalshi_api, "get_balance", _bal)
    assert run_async(service._reverify_auth_if_needed()) is True
    assert service.STATE.auth_ok is True


def test_reverify_noop_without_credentials(monkeypatch):
    monkeypatch.setattr(kalshi_auth, "credentials_present", lambda env=None: False)
    calls = {"n": 0}

    async def _bal(*a, **k):
        calls["n"] += 1
        return {"balance": 1}

    monkeypatch.setattr(kalshi_api, "get_balance", _bal)
    assert run_async(service._reverify_auth_if_needed()) is False
    assert service.STATE.auth_ok is False
    assert calls["n"] == 0


def test_reverify_stays_off_when_verify_fails(monkeypatch):
    monkeypatch.setattr(kalshi_auth, "credentials_present", lambda env=None: True)

    async def _bal(*a, **k):
        raise RuntimeError("kalshi 503")

    monkeypatch.setattr(kalshi_api, "get_balance", _bal)
    with pytest.raises(RuntimeError):
        run_async(service._reverify_auth_if_needed())
    assert service.STATE.auth_ok is False


def test_reverify_noop_when_already_authed(monkeypatch):
    service.STATE.auth_ok = True
    calls = {"n": 0}

    async def _bal(*a, **k):
        calls["n"] += 1
        return {"balance": 1}

    monkeypatch.setattr(kalshi_auth, "credentials_present", lambda env=None: True)
    monkeypatch.setattr(kalshi_api, "get_balance", _bal)
    assert run_async(service._reverify_auth_if_needed()) is False
    assert calls["n"] == 0
