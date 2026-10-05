from __future__ import annotations

import asyncio

import kalshi_api
import service


def _run(coro):
    return asyncio.run(coro)


def _reset(cfg_on=True, tier=""):
    service.STATE.auth_ok = True
    service.STATE.cfg = {"auto_upgrade_api_level": cfg_on}
    service.STATE.api_tier = tier
    service.STATE.last_api_upgrade_at = 0.0


def test_skips_when_already_advanced(monkeypatch):
    _reset()
    posted = []
    async def _lim(): return {"usage_tier": "advanced", "read": {}, "write": {}}
    async def _up(): posted.append(1); return {}
    monkeypatch.setattr(kalshi_api, "get_account_limits", _lim)
    monkeypatch.setattr(kalshi_api, "upgrade_api_usage_level", _up)
    _run(service._maybe_upgrade_api_level())
    assert service.STATE.api_tier == "advanced"
    assert posted == []


def test_posts_when_basic_then_rereads(monkeypatch):
    _reset()
    calls = {"n": 0}
    async def _lim():
        calls["n"] += 1
        return {"usage_tier": "basic" if calls["n"] == 1 else "advanced", "read": {}, "write": {}}
    posted = []
    async def _up(): posted.append(1); return {}
    monkeypatch.setattr(kalshi_api, "get_account_limits", _lim)
    monkeypatch.setattr(kalshi_api, "upgrade_api_usage_level", _up)
    _run(service._maybe_upgrade_api_level())
    assert posted == [1]
    assert service.STATE.api_tier == "advanced"


def test_defers_on_403_without_raising(monkeypatch):
    _reset()
    async def _lim(): return {"usage_tier": "basic", "read": {}, "write": {}}
    async def _up(): raise kalshi_api.KalshiAPIError(403, {"error": {"code": "no_api_order"}})
    monkeypatch.setattr(kalshi_api, "get_account_limits", _lim)
    monkeypatch.setattr(kalshi_api, "upgrade_api_usage_level", _up)
    _run(service._maybe_upgrade_api_level())
    assert service.STATE.api_tier == "basic"


def test_disabled_by_config(monkeypatch):
    _reset(cfg_on=False)
    touched = []
    async def _lim(): touched.append(1); return {"usage_tier": "basic"}
    monkeypatch.setattr(kalshi_api, "get_account_limits", _lim)
    _run(service._maybe_upgrade_api_level())
    assert touched == []


def test_rate_limited_second_attempt(monkeypatch):
    _reset()
    async def _lim(): return {"usage_tier": "basic", "read": {}, "write": {}}
    posted = []
    async def _up(): posted.append(1); return {}
    monkeypatch.setattr(kalshi_api, "get_account_limits", _lim)
    monkeypatch.setattr(kalshi_api, "upgrade_api_usage_level", _up)
    _run(service._maybe_upgrade_api_level())
    _run(service._maybe_upgrade_api_level())
    assert posted == [1]
