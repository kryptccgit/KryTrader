"""Autopilot: an AI agent on a timer, billed to the user's key.

The provider is faked with scripted replies. What is pinned: it calls tools
only through mcp_server (so every rail applies), it stops at each of its three
budgets, it stops when switched off, it never overlaps itself, and every run
is recorded with what it cost.
"""
from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace as NS

import pytest

import ai_analyst
import autopilot
import db
import mcp_server
from config import merge_with_defaults


def run(coro):
    return asyncio.run(coro)


def _usage(i=1000, o=200):
    return NS(input_tokens=i, output_tokens=o, cache_creation_input_tokens=0,
              cache_read_input_tokens=0)


def _tool_use(name, inp, uid="t1"):
    return NS(type="tool_use", name=name, input=inp, id=uid)


def _text(t):
    return NS(type="text", text=t)


class FakeAnthropic:
    """Replays a script of responses; records every request."""
    script: list = []
    calls: list = []

    def __init__(self, **kw):
        self.messages = self

    def create(self, **kw):
        FakeAnthropic.calls.append(kw)
        if not FakeAnthropic.script:
            return NS(content=[_text("done")], stop_reason="end_turn", usage=_usage())
        return FakeAnthropic.script.pop(0)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    db.init_db()
    with db.get_db() as conn:
        for t in ("autopilot_runs", "ai_forecasts", "mcp_orders"):
            conn.execute(f"DELETE FROM {t}")
    mcp_server._hits.clear()
    st = {"cfg": {"autopilot_enabled": True, "mcp_trade_mode": "off",
                  "ai_provider": "anthropic", "ai_model": "claude-opus-5"}}
    mcp_server.configure(get_cfg=lambda: merge_with_defaults(dict(st["cfg"])),
                         is_authed=lambda: False, emit=None, rpc=None,
                         submit=None, cancel=None, notify_phone=None)
    monkeypatch.setattr(ai_analyst, "has_key", lambda p: True)
    monkeypatch.setattr(ai_analyst, "_read_key", lambda p: "sk-test")
    fake = types.ModuleType("anthropic")
    fake.Anthropic = FakeAnthropic
    fake.APIError = type("APIError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    FakeAnthropic.script = []
    FakeAnthropic.calls = []
    autopilot.STATE.running = False
    yield st


def _cfg(st):
    return merge_with_defaults(dict(st["cfg"]))


def test_a_run_calls_tools_through_the_mcp_rails_and_is_recorded(env):
    FakeAnthropic.script = [
        NS(content=[_tool_use("get_status", {})], stop_reason="tool_use", usage=_usage()),
        NS(content=[_text("Looked at nothing worth trading.")], stop_reason="end_turn",
           usage=_usage(500, 100)),
    ]
    res = run(autopilot.run_once(_cfg(env), "manual"))
    assert res["ok"], res
    r = autopilot.runs(1)[0]
    assert r["status"] == "ok" and r["steps"] == 1
    assert r["inputTokens"] == 1500 and r["outputTokens"] == 300
    assert r["costUsd"] is not None and r["costUsd"] > 0
    assert r["tools"][0]["tool"] == "get_status" and r["tools"][0]["ok"]
    assert "worth trading" in r["summary"]
    offered = {t["name"] for t in FakeAnthropic.calls[0]["tools"]}
    assert offered == {t.name for t in mcp_server.visible_tools(_cfg(env))}
    assert "place_order" not in offered


def test_a_tool_the_permissions_forbid_comes_back_as_an_error(env):
    FakeAnthropic.script = [
        NS(content=[_tool_use("place_order", {"ticker": "X"})], stop_reason="tool_use",
           usage=_usage()),
    ]
    run(autopilot.run_once(_cfg(env), "manual"))
    r = autopilot.runs(1)[0]
    assert r["tools"][0] == {"tool": "place_order", "ok": False,
                             "brief": "Unknown or disabled tool: place_order"}
    tool_result = FakeAnthropic.calls[1]["messages"][-1]["content"][0]
    assert tool_result["is_error"] is True


def test_the_step_limit_ends_a_run(env):
    env["cfg"]["autopilot_max_steps"] = 3
    FakeAnthropic.script = [
        NS(content=[_tool_use("get_status", {}, f"t{i}")], stop_reason="tool_use",
           usage=_usage()) for i in range(10)]
    run(autopilot.run_once(_cfg(env), "manual"))
    r = autopilot.runs(1)[0]
    assert r["status"] == "steps" and r["steps"] == 3


def test_the_daily_token_budget_stops_a_run_mid_way(env):
    env["cfg"]["autopilot_daily_token_budget"] = 50_000
    FakeAnthropic.script = [
        NS(content=[_tool_use("get_status", {}, f"t{i}")], stop_reason="tool_use",
           usage=_usage(30_000, 1_000)) for i in range(10)]
    run(autopilot.run_once(_cfg(env), "manual"))
    r = autopilot.runs(1)[0]
    assert r["status"] == "budget"
    assert len(FakeAnthropic.calls) == 2
    res = run(autopilot.run_once(_cfg(env), "manual"))
    assert not res["ok"] and "token budget" in res["message"]
    assert len(FakeAnthropic.calls) == 2


def test_runs_per_day_are_capped(env):
    env["cfg"]["autopilot_max_runs_per_day"] = 1
    assert run(autopilot.run_once(_cfg(env), "manual"))["ok"]
    res = run(autopilot.run_once(_cfg(env), "manual"))
    assert not res["ok"] and "limit 1" in res["message"]


def test_switching_it_off_stops_a_scheduled_run(env):
    def _off_after_first(**kw):
        FakeAnthropic.calls.append(kw)
        env["cfg"]["autopilot_enabled"] = False
        return NS(content=[_tool_use("get_status", {})], stop_reason="tool_use",
                  usage=_usage())
    FakeAnthropic.create = staticmethod(_off_after_first)
    try:
        run(autopilot.run_once(_cfg(env), "schedule"))
    finally:
        del FakeAnthropic.create
    assert autopilot.runs(1)[0]["status"] == "stopped"
    assert len(FakeAnthropic.calls) == 1


def test_no_key_means_no_run(env, monkeypatch):
    monkeypatch.setattr(ai_analyst, "has_key", lambda p: False)
    res = run(autopilot.run_once(_cfg(env), "manual"))
    assert not res["ok"] and "key" in res["message"]
    assert FakeAnthropic.calls == [] and autopilot.runs(1) == []


def test_runs_never_overlap(env):
    async def _both():
        gate = asyncio.Event()
        orig = autopilot._loop_anthropic

        async def _slow(r, key):
            await gate.wait()
            return "ok", "ok"
        autopilot._loop_anthropic = _slow
        try:
            first = asyncio.create_task(autopilot.run_once(_cfg(env), "manual"))
            await asyncio.sleep(0.05)
            second = await autopilot.run_once(_cfg(env), "manual")
            gate.set()
            await first
            return second
        finally:
            autopilot._loop_anthropic = orig
    second = run(_both())
    assert not second["ok"] and "already running" in second["message"]


def test_schedule_respects_the_interval(env):
    cfg = _cfg(env)
    assert autopilot.due(cfg)
    run(autopilot.run_once(cfg, "schedule"))
    assert not autopilot.due(cfg)
    env["cfg"]["autopilot_enabled"] = False
    assert autopilot.next_due_at(_cfg(env)) is None


def test_openai_runs_are_recorded_without_inventing_a_price(env, monkeypatch):
    env["cfg"]["ai_provider"] = "openai"
    env["cfg"]["ai_model"] = "gpt-5.5"
    replies = [
        NS(output=[NS(type="function_call", name="get_status", arguments="{}",
                      call_id="c1")], output_text="", usage=NS(input_tokens=800,
                                                                output_tokens=50)),
        NS(output=[NS(type="message")], output_text="Nothing to do.",
           usage=NS(input_tokens=900, output_tokens=60)),
    ]

    class FakeOpenAI:
        def __init__(self, **kw):
            self.responses = self

        def create(self, **kw):
            return replies.pop(0)
    fake = types.ModuleType("openai")
    fake.OpenAI = FakeOpenAI
    fake.APIError = type("APIError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "openai", fake)
    assert run(autopilot.run_once(_cfg(env), "manual"))["ok"]
    r = autopilot.runs(1)[0]
    assert r["status"] == "ok" and r["steps"] == 1
    assert r["costUsd"] is None
    assert autopilot.usage_today()["costUsd"] is None


def test_an_agent_cannot_touch_autopilot_settings():
    import mcp_workbench as wb
    for k in ("autopilot_enabled", "autopilot_daily_token_budget", "autopilot_mission"):
        assert wb.classify(k) == "protected"


def test_budget_settings_are_clamped():
    cfg = merge_with_defaults({"autopilot_interval_min": 1,
                               "autopilot_daily_token_budget": 10 ** 12,
                               "autopilot_enabled": "yes"})
    assert cfg["autopilot_interval_min"] == 15
    assert cfg["autopilot_daily_token_budget"] == 50_000_000
    assert cfg["autopilot_enabled"] is False


def test_deleting_the_agent_autopilot_runs_as_blocks_it_never_falls_back(env):
    """Pre-release audit (v6): the agent Autopilot runs as is deleted. It must
    not quietly run as Default (usually looser rules); it blocks, says why,
    and records no run and no bill."""
    env["cfg"].update(autopilot_agent_id="gone1",
                      mcp_agents=[{"id": "default", "name": "Default"}])
    cfg = _cfg(env)
    assert cfg["autopilot_agent_id"] == "gone1"
    why = autopilot.blocked_reason(cfg)
    assert why and "no longer exists" in why
    assert autopilot.status(cfg)["blockedReason"] == why
    res = run(autopilot.run_once(cfg, "manual"))
    assert res["ok"] is False and "no longer exists" in res["message"]
    assert autopilot.runs(5) == [] and FakeAnthropic.calls == []
    env["cfg"].update(autopilot_agent_id="sam1", mcp_agents=[
        {"id": "default", "name": "Default"}, {"id": "sam1", "name": "Sam", "enabled": False}])
    assert "switched off" in autopilot.blocked_reason(_cfg(env))
