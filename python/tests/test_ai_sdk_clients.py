"""The REAL Anthropic and OpenAI SDKs, built on our HTTP client, offline.

Every other AI test fakes the SDK module, and a fake accepts whatever client
it is handed. That is how the default provider shipped broken: anthropic 1.x
isinstance-checks for an `httpx2.Client`, counted_client returned an
`httpx.Client`, and every Analyse click and every Autopilot run died with a
TypeError before a byte was sent. Nothing here touches the network: requests
go to an httpx2.MockTransport.
"""
from __future__ import annotations

import asyncio
import json

import anthropic
import httpx
import httpx2
import openai
import pytest

import ai_analyst
import ai_providers as ap


def test_both_real_sdks_accept_the_counted_client():
    for cls in (anthropic.Anthropic, openai.OpenAI):
        http = ap.counted_client(5.0)
        try:
            client = cls(api_key="sk-test", max_retries=0, http_client=http)
            assert client._client is http
        finally:
            http.close()


def test_the_selftest_check_passes_and_would_catch_the_regression(monkeypatch):
    assert ap.sdk_selfcheck() == []
    monkeypatch.setattr(ap, "counted_client",
                        lambda timeout, transport=None: httpx.Client(timeout=timeout))
    failures = ap.sdk_selfcheck()
    assert any("anthropic client on counted_client: TypeError" in f for f in failures), failures


def test_the_counted_client_does_not_follow_redirects():
    http = ap.counted_client(5.0)
    try:
        assert http.follow_redirects is False
    finally:
        http.close()


_ANTHROPIC_REPLY = {
    "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5",
    "content": [{"type": "text", "text": json.dumps({
        "summary": "s", "fairValueCents": 41, "fairValueLowCents": 33,
        "fairValueHighCents": 49, "verdict": "cheap", "confidence": "medium"})}],
    "stop_reason": "end_turn", "stop_sequence": None,
    "usage": {"input_tokens": 1200, "output_tokens": 300},
}
_OPENAI_REPLY = {
    "id": "resp_1", "object": "response", "created_at": 0, "model": "gpt-5",
    "status": "completed", "parallel_tool_calls": False, "tool_choice": "auto",
    "tools": [],
    "output": [{"type": "message", "id": "m1", "role": "assistant", "status": "completed",
                "content": [{"type": "output_text", "annotations": [],
                             "text": json.dumps({"summary": "s", "fairValueCents": 41,
                                                 "verdict": "cheap"})}]}],
    "usage": {"input_tokens": 1000, "output_tokens": 200, "total_tokens": 1200,
              "input_tokens_details": {"cached_tokens": 0},
              "output_tokens_details": {"reasoning_tokens": 0}},
}


@pytest.fixture
def wire(monkeypatch):
    """Route counted_client through a mock transport; record what was sent,
    what the Privacy panel counted, and every client handed out."""
    st = {"requests": [], "counted": [], "clients": []}

    def handler(request):
        st["requests"].append(request)
        if request.url.path.endswith("/messages"):
            return httpx2.Response(200, json=_ANTHROPIC_REPLY)
        if request.url.path.endswith("/responses"):
            return httpx2.Response(200, json=_OPENAI_REPLY)
        return httpx2.Response(404, json={"error": {"message": "no route"}})

    real = ap.counted_client

    def counted(timeout, transport=None):
        c = real(timeout, transport=httpx2.MockTransport(handler))
        st["clients"].append(c)
        return c

    monkeypatch.setattr(ap, "counted_client", counted)
    monkeypatch.setattr(ap, "_note", lambda url, ok, ms, err="":
                        st["counted"].append((ap.stat_host(url), ok)))
    monkeypatch.setattr(ai_analyst, "_read_key", lambda p: "sk-test")
    monkeypatch.setattr(ai_analyst, "has_key", lambda p: True)
    return st


def _detail():
    return {"market": {"ticker": "KX-1", "title": "Will it?", "yesBid": None,
                       "yesAsk": 44}, "fetchedAt": "2026-10-06T12:00:00Z"}


@pytest.mark.parametrize("provider,model,host", [
    ("anthropic", "claude-opus-5", "api.anthropic.com"),
    ("openai", "gpt-5", "api.openai.com"),
])
def test_analyse_runs_end_to_end_through_the_real_sdk(wire, provider, model, host):
    res = ai_analyst.analyze(_detail(), {"ai_provider": provider, "ai_model": model})
    assert res["fairValueCents"] == 41 and res["verdict"] == "cheap"
    assert [r.url.host for r in wire["requests"]] == [host]
    assert wire["counted"] == [(host, True)]
    assert len(wire["clients"]) == 1 and wire["clients"][0].is_closed


def test_autopilot_runs_end_to_end_through_the_real_anthropic_sdk(wire):
    import autopilot
    import db
    import mcp_server
    from config import merge_with_defaults
    db.init_db()
    with db.get_db() as conn:
        conn.execute("DELETE FROM autopilot_runs")
    cfg = {"autopilot_enabled": True, "mcp_trade_mode": "off",
           "ai_provider": "anthropic", "ai_model": "claude-opus-5"}
    mcp_server.configure(get_cfg=lambda: merge_with_defaults(dict(cfg)),
                         is_authed=lambda: False, emit=None, rpc=None,
                         submit=None, cancel=None, notify_phone=None)
    autopilot.STATE.running = False
    res = asyncio.run(autopilot.run_once(merge_with_defaults(dict(cfg)), "manual"))
    assert res["ok"], res
    assert autopilot.runs(1)[0]["status"] == "ok"
    assert wire["counted"] == [("api.anthropic.com", True)]
    assert all(c.is_closed for c in wire["clients"])
