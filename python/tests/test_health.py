"""Connection health checks.

Two things are pinned. First, each row says what is wrong in words a user can
act on, and points at the place to fix it. Second — the rule that keeps a
diagnostics panel from becoming account traffic — the network checks (signed
Kalshi read, AI key check, loopback call) run ONLY on a deep run, which only
the "Run checks" click asks for. The open-time run touches nothing.
"""
from __future__ import annotations

import asyncio
import socket

import pytest

import ai_analyst
import health
import kalshi_api
import kalshi_auth
import mcp_server
import service
from config import merge_with_defaults


def run(coro):
    return asyncio.run(coro)



def test_kalshi_without_a_key_points_at_api_keys():
    r = health.check_kalshi("production", present=False, auth_ok=False)
    assert r["status"] == "fail" and r["action"] == {"kind": "nav", "page": "api",
                                                      "label": "Open API Keys"}
    assert r["network"] is False and r["tested"] is False


def test_paper_without_a_key_is_not_a_fault():
    """Paper needs no Kalshi account: no key in Paper is the normal state of a
    new user, not a red row."""
    r = health.check_kalshi("paper", present=False, auth_ok=True)
    assert r["status"] == "ok" and r["network"] is False
    assert "does not need one" in r["detail"]
    r = health.check_kalshi("paper", present=True, auth_ok=True)
    assert r["status"] == "ok" and not r["tested"] and "nothing is signed" in r["detail"]


def test_kalshi_local_state_is_not_dressed_up_as_a_test():
    r = health.check_kalshi("prod", present=True, auth_ok=True)
    assert r["status"] == "ok" and not r["tested"]
    r = health.check_kalshi("prod", present=True, auth_ok=False)
    assert r["status"] == "warn" and "Run checks" in r["fix"]


def test_kalshi_probe_results():
    ok = health.check_kalshi("production", True, True, probed=True, probe_ok=True)
    assert ok["status"] == "ok" and ok["tested"]
    bad = health.check_kalshi("production", True, False, probed=True, probe_ok=False,
                              probe_error=kalshi_api.KalshiAPIError(401, {"code": "unauthorized"}))
    assert bad["status"] == "fail" and "401" in bad["detail"]
    assert "kalshi.com" in bad["fix"] and "demo" not in bad["fix"].lower()


@pytest.mark.parametrize("err,needle", [
    (kalshi_api.KalshiAPIError(403, "forbidden"), "read/trade access"),
    (RuntimeError("request timestamp outside window"), "clock"),
    (RuntimeError("ConnectError: getaddrinfo failed"), "internet connection"),
    (RuntimeError("credentials not set for prod"), "API Keys"),
    (ValueError("something novel"), "diagnostics"),
])
def test_kalshi_failures_get_a_specific_fix(err, needle):
    _detail, fix = health.kalshi_error_fix("prod", err)
    assert needle in fix



def test_ai_rows_without_the_provider_check():
    r = health.check_ai("anthropic", active=True, has_key=False, can_probe=False)
    assert r["status"] == "off" and r["detail"] == "Not set up."
    assert r["action"]["page"] == "settings"
    r = health.check_ai("anthropic", active=True, has_key=False, can_probe=False, needed=True)
    assert r["status"] == "warn" and r["action"]["page"] == "settings"
    r = health.check_ai("openai", active=False, has_key=False, can_probe=False)
    assert r["status"] == "off"
    r = health.check_ai("openai", active=False, has_key=True, can_probe=False)
    assert r["status"] == "ok" and r["network"] is False and "not tested" in r["detail"]


def test_ai_rows_with_the_provider_check():
    r = health.check_ai("anthropic", active=True, has_key=True, can_probe=True)
    assert r["status"] == "ok" and r["network"] and not r["tested"]
    r = health.check_ai("anthropic", active=True, has_key=True, can_probe=True, probed=True,
                        probe={"ok": True, "message": "Key accepted.", "models": ["a", "b"]})
    assert r["status"] == "ok" and r["tested"] and "2 models" in r["detail"]
    r = health.check_ai("openai", active=True, has_key=True, can_probe=True, probed=True,
                        probe={"ok": False, "message": "Incorrect API key provided."})
    assert r["status"] == "fail" and r["detail"] == "Incorrect API key provided."
    r = health.check_ai("openai", active=True, has_key=True, can_probe=True, probed=True,
                        probe_error=TimeoutError())
    assert r["status"] == "fail" and "timed out" in r["detail"]
    assert "TimeoutError" not in r["detail"]


def test_a_failing_local_provider_is_never_told_to_paste_a_key():
    r = health.check_ai("ollama", active=True, has_key=True, can_probe=True, probed=True,
                        local=True, probe={"ok": False, "message": "qwen3:8b isn't pulled"})
    assert r["status"] == "fail" and "key" not in r["fix"].lower()
    assert "Ollama" in r["fix"] and "pulled" in r["fix"]


def test_a_cloud_model_problem_is_not_called_a_key_problem():
    r = health.check_ai("gemini", active=True, has_key=True, can_probe=True, probed=True,
                        probe={"ok": False, "reason": "model",
                               "message": "Google Gemini accepted the key, but x isn't..."})
    assert r["status"] == "fail" and "Pick a model" in r["fix"]


def test_an_idle_provider_row_says_it_was_not_contacted():
    r = health.check_ai("openai", active=False, has_key=True, can_probe=True, idle=True)
    assert r["status"] == "ok" and not r["tested"] and not r["network"]
    assert "Not tested" in r["detail"] and "selected" in r["detail"]



def _st(**kw):
    base = {"enabled": True, "running": True, "port": 47821, "hasToken": True,
            "lastError": None, "lastSeen": None, "httpEnabled": True}
    base.update(kw)
    return base


def test_mcp_rows():
    assert health.check_mcp(_st(enabled=False))["status"] == "off"
    r = health.check_mcp(_st(running=False, lastError="Could not listen on 127.0.0.1:47821"))
    assert r["status"] == "fail" and r["action"]["kind"] == "copy"
    assert "47821" in r["action"]["text"]
    r = health.check_mcp(_st())
    assert r["status"] == "warn" and "No client" in r["detail"]
    r = health.check_mcp(_st(lastSeen={"client": "http:n8n", "at": "2026-10-06T12:00:00"}))
    assert r["status"] == "ok" and "http:n8n" in r["detail"]
    assert health.check_mcp(_st(hasToken=False))["status"] == "fail"


def test_http_rows():
    assert health.check_http(_st(enabled=False))["status"] == "off"
    assert health.check_http(_st(httpEnabled=False))["status"] == "off"
    assert health.check_http(_st(running=False))["status"] == "fail"
    r = health.check_http(_st())
    assert r["status"] == "ok" and not r["tested"]
    r = health.check_http(_st(), probed=True, probe={"ok": True, "status": 200, "tools": 9})
    assert r["status"] == "ok" and r["tested"] and "9 tools" in r["detail"]
    r = health.check_http(_st(), probed=True, probe={"ok": False, "status": 401})
    assert r["status"] == "fail" and "Rotate" in r["fix"]
    r = health.check_http(_st(), probed=True,
                          probe={"ok": False, "status": None, "error": "ConnectionRefusedError"})
    assert r["status"] == "fail" and r["action"]["kind"] == "copy"


def test_port_command_names_the_port_and_nothing_else():
    cmd = health.port_owner_command(47999)
    assert "47999" in cmd and "kt_" not in cmd


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_probe_http_against_the_real_listener():
    port = _free_port()
    token = mcp_server.rotate_token()
    cfg = {"mcp_enabled": True, "mcp_http_enabled": True, "mcp_trade_mode": "paper"}
    mcp_server.configure(get_cfg=lambda: merge_with_defaults(dict(cfg)))

    async def _go():
        await mcp_server.start(port)
        try:
            good = await health.probe_http(port, token)
            bad = await health.probe_http(port, "kt_wrong")
        finally:
            await mcp_server.stop()
        closed = await health.probe_http(port, token, timeout=1.0)
        return good, bad, closed

    good, bad, closed = run(_go())
    assert good["ok"] and good["tools"] >= 5
    assert not bad["ok"] and bad["status"] == 401
    assert not closed["ok"] and closed["status"] is None
    assert all("health" not in c for c in mcp_server.STATUS.seen)



def _ap(**kw):
    base = {"enabled": True, "running": False, "lastError": None, "nextRunAt": "2026-10-06T13:00:00",
            "blockedReason": None, "today": {"runs": 2, "tokens": 100_000},
            "limits": {"maxRunsPerDay": 12, "dailyTokenBudget": 1_500_000}}
    base.update(kw)
    return base


def test_autopilot_rows():
    assert health.check_autopilot(_ap(enabled=False))["status"] == "off"
    r = health.check_autopilot(_ap())
    assert r["status"] == "ok" and "10 runs and 1,400,000 tokens left" in r["detail"]
    r = health.check_autopilot(_ap(blockedReason="No Anthropic key — set it under Settings → AI analysis."))
    assert r["status"] == "warn" and r["action"]["page"] == "settings"
    r = health.check_autopilot(_ap(blockedReason="Already ran 12 times today (limit 12)."))
    assert r["status"] == "warn" and r["action"] is None and "00:00 UTC" in r["fix"]


def test_remote_rows():
    bot = {"running": True, "connected": True, "botName": "kryptbot", "lastError": None}
    kw = dict(enabled=True, has_token=True, paired=True)
    assert health.check_remote("discord", **{**kw, "enabled": False}, bot=bot)["status"] == "off"
    r = health.check_remote("discord", **{**kw, "has_token": False}, bot=bot)
    assert r["status"] == "fail" and r["action"]["page"] == "remote"
    r = health.check_remote("telegram", **{**kw, "paired": False}, bot=bot)
    assert r["status"] == "warn" and "pairing code" in r["fix"]
    assert health.check_remote("telegram", **kw, bot=bot)["status"] == "ok"
    r = health.check_remote("discord", **kw, bot={**bot, "connected": False,
                                                  "lastError": "4014 disallowed intents"})
    assert r["status"] == "warn" and "Message Content intent" in r["fix"]
    r = health.check_remote("discord", **kw, bot={**bot, "running": False, "connected": False})
    assert r["status"] == "fail"


def test_ws_rows():
    assert health.check_ws(None, authed=True)["status"] == "off"
    assert health.check_ws({"enabled": False}, authed=True)["status"] == "off"
    ok = health.check_ws({"enabled": True, "connected": True, "env": "prod", "books": 4,
                          "lastMsgAgeSec": 2.0}, authed=True)
    assert ok["status"] == "ok"
    stale = health.check_ws({"enabled": True, "connected": True, "lastMsgAgeSec": 300.0},
                            authed=True)
    assert stale["status"] == "warn"
    r = health.check_ws({"enabled": True, "connected": False}, authed=False)
    assert r["status"] == "warn" and r["action"]["page"] == "api"



_REAL_CHECK_PROVIDER = ai_analyst.check_provider
PROBED: list = []

@pytest.fixture
def svc(monkeypatch):
    import db
    db.init_db()
    calls = {"test": 0, "provider": 0, "probe": 0}

    async def _test(_p):
        calls["test"] += 1
        return {"env": "production", "balanceUsd": 1.0}

    PROBED.clear()

    def _check(provider, cfg=None):
        calls["provider"] += 1
        PROBED.append((provider, cfg))
        return {"ok": True, "message": f"{provider} ok", "models": ["m"]}

    async def _probe(port, token, timeout=3.0):
        calls["probe"] += 1
        return {"ok": True, "status": 200, "tools": 7}

    monkeypatch.setattr(service, "_h_testCredentials", _test)
    monkeypatch.setattr(ai_analyst, "check_provider", _check, raising=False)
    monkeypatch.setattr(ai_analyst, "has_key", lambda p: True)
    monkeypatch.setattr(health, "probe_http", _probe)
    monkeypatch.setattr(kalshi_auth, "credentials_present", lambda env=None: True)
    monkeypatch.setattr(mcp_server.STATUS, "running", True)
    monkeypatch.setattr(service.STATE, "cfg", {
        "mcp_enabled": True, "mcp_http_enabled": True, "mcp_trade_mode": "paper"})
    mcp_server.rotate_token()
    return calls


def test_opening_the_panel_touches_no_network(svc):
    rep = run(service._h_health_check({}))
    assert svc == {"test": 0, "provider": 0, "probe": 0}
    assert rep["deep"] is False
    ids = [r["id"] for r in rep["rows"]]
    for want in ("kalshi", "ai:anthropic", "ai:openai", "mcp", "http", "autopilot",
                 "remote:discord", "remote:telegram", "ws"):
        assert want in ids
    assert all(not r["tested"] for r in rep["rows"])
    run(service._h_health_check({"deep": "yes"}))
    assert svc == {"test": 0, "provider": 0, "probe": 0}


def test_run_checks_probes_each_network_connection_once(svc):
    rep = run(service._h_health_check({"deep": True}))
    assert svc["test"] == 1 and svc["probe"] == 1
    assert svc["provider"] == 1
    assert [p for p, _cfg in PROBED] == ["anthropic"]
    by = {r["id"]: r for r in rep["rows"]}
    assert by["kalshi"]["tested"] and by["kalshi"]["status"] == "ok"
    assert by["http"]["tested"] and "7 tools" in by["http"]["detail"]
    assert by["ai:anthropic"]["tested"]
    for p in ai_analyst.PROVIDERS:
        if p != "anthropic" and ai_analyst.needs_key(p):
            assert not by[f"ai:{p}"]["tested"] and "Not tested" in by[f"ai:{p}"]["detail"]


def test_run_checks_tests_the_users_provider_and_model_not_the_default(svc, monkeypatch):
    """check_provider was called without cfg, so it fell back to the default
    model: an Ollama user with qwen3 pulled got a red 'llama3.1 not pulled'
    and a fix telling them to paste a key."""
    import ai_providers
    monkeypatch.setitem(service.STATE.cfg, "ai_provider", "ollama")
    monkeypatch.setitem(service.STATE.cfg, "ai_model", "qwen3:8b")
    run(service._h_health_check({"deep": True}))
    assert PROBED[-1][0] == "ollama" and PROBED[-1][1]["ai_model"] == "qwen3:8b"
    seen = []
    monkeypatch.setattr(ai_providers, "check", lambda p, key, model=None: (
        seen.append((p, model)) or {"ok": True, "message": "ok", "models": [model]}))
    monkeypatch.setattr(ai_analyst, "check_provider", _REAL_CHECK_PROVIDER)
    run(service._h_health_check({"deep": True}))
    assert seen == [("ollama", "qwen3:8b")]


def test_without_check_provider_the_ai_row_stays_offline(svc, monkeypatch):
    monkeypatch.delattr(ai_analyst, "check_provider", raising=False)
    rep = run(service._h_health_check({"deep": True}))
    assert svc["provider"] == 0
    ai = next(r for r in rep["rows"] if r["id"] == "ai:anthropic")
    assert ai["status"] == "ok" and not ai["tested"] and not ai["network"]


def test_a_failing_kalshi_test_is_a_row_not_a_crash(svc, monkeypatch):
    async def _boom(_p):
        raise kalshi_api.KalshiAPIError(401, "INCORRECT_API_KEY_SIGNATURE")
    monkeypatch.setattr(service, "_h_testCredentials", _boom)
    rep = run(service._h_health_check({"deep": True}))
    k = next(r for r in rep["rows"] if r["id"] == "kalshi")
    assert k["status"] == "fail" and k["tested"] and k["action"]["page"] == "api"


def test_a_broken_check_does_not_blank_the_panel(svc, monkeypatch):
    def _boom(cfg):
        raise RuntimeError("status exploded")
    monkeypatch.setattr(mcp_server, "status", _boom)
    rep = run(service._h_health_check({}))
    ids = [r["id"] for r in rep["rows"]]
    assert "kalshi" in ids and "autopilot" in ids
    assert any(r["status"] == "fail" and "check itself failed" in r["detail"]
               for r in rep["rows"])


def test_health_is_not_an_agent_door():
    assert "healthCheck" not in service._MCP_RPC_ALLOWED
    assert "mcpHttpSnippet" not in service._MCP_RPC_ALLOWED


def test_an_active_local_provider_is_a_server_row_not_a_missing_key(svc, monkeypatch):
    monkeypatch.setattr(ai_analyst, "has_key", lambda p: False)
    monkeypatch.setitem(service.STATE.cfg, "ai_provider", "ollama")
    rep = run(service._h_health_check({}))
    ollama = next(r for r in rep["rows"] if r["id"] == "ai:ollama")
    assert "on this machine" in ollama["label"] and "key" not in ollama["detail"].lower()
    assert ollama["status"] == "ok"
    assert not any(r["id"] == "ai:lmstudio" for r in rep["rows"])

    deep = run(service._h_health_check({"deep": True}))
    assert svc["provider"] >= 1
    ollama = next(r for r in deep["rows"] if r["id"] == "ai:ollama")
    assert ollama["tested"]
