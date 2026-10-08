"""Autopilot: the app runs an AI agent on a schedule, with the user's own key.

Everything else that talks to a model in this app does it on a click, because
every call is billed to the user (invariant 8). Autopilot is the one deliberate
exception, and it is built so that it cannot become a surprise on a bill or a
surprise in an account:

  * **Off until switched on**, with its own confirmation, separate from the
    MCP server and from every permission.
  * **It is just another MCP client.** It sees exactly the tools a connected
    Cursor or Claude would (mcp_server.visible_tools) and calls them through
    mcp_server.call_tool — the same forecast gate, caps, daily loss stop,
    "only what it opened" rule and, in live mode, the same approval queue.
    Autopilot adds no order path of its own.
  * **Three budgets, all enforced here before a call is made:** runs per UTC
    day, tokens per UTC day across all runs, and tool calls per run. A run
    that would cross the token budget mid-way stops, and says so.
  * **One run at a time.** A slow run is never overlapped by the next tick.
  * **Switching it off stops a run in progress** at the next step.
  * **Every run is recorded** — model, steps, tokens, cost where the provider
    publishes prices, every tool it called, and its own report of what it did.

The key, provider and model are the AI Analysis settings: one key, one bill.

Any provider works whose model can call tools — Autopilot does nothing except
through tools, so a model that cannot is refused BEFORE the run starts, with
the reason, rather than failing on its first turn. Anthropic and OpenAI keep
their SDK loops below; OpenRouter, Gemini, Ollama and LM Studio run through
ai_providers.ToolChat. The budgets are enforced by the same code for all of
them. Where a provider reports no token usage (a local server can omit it),
the run counts an estimate from the text length instead of counting zero,
and its report says the figures are estimates.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import ai_analyst
import db
import mcp_server

logger = logging.getLogger("autopilot")

_MAX_TOKENS = 4000
_TIMEOUT_SEC = 120.0
_RESULT_CHARS = 12000

_LOCK = asyncio.Lock()


class _State:
    running: bool = False
    started_at: Optional[str] = None
    current_step: int = 0
    last_error: Optional[str] = None


STATE = _State()


SYSTEM = """You are Krypt Autopilot: an agent the user has scheduled to run \
unattended inside their Krypt Trader app. Nobody is watching this run live; \
the user reads your report afterwards.

{instructions}

How to run:
- Start with get_status. Respect the mode and caps it reports.
- Work the user's mission below. Be selective: a few markets examined \
properly beats many skimmed.
- Record a forecast for every market you form a view on, including ones you \
decide not to trade. Those forecasts are how the user learns whether you are \
any good.
- You have at most {max_steps} tool calls in this run. Stop early when you \
are done.
- Finish with a short plain-text report: what you looked at, forecasts \
recorded (with your fair value vs the market), orders placed or queued for \
approval and why, and anything the user should look at.

THE USER'S MISSION
{mission}"""

AGENT_BLOCK = """
YOU ARE RUNNING AS: {name}
{guide}
YOUR HARD RULES (the app refuses any order outside them):
{rules}
"""


def run_agent(cfg: dict) -> Optional[dict]:
    """The named agent Autopilot runs as, or None if it no longer exists."""
    return mcp_server.mcp_agents.get(cfg, str(cfg.get("autopilot_agent_id") or "default"))

DEFAULT_MISSION = (
    "Look through markets closing in the next few days. Pick the ones where "
    "you can actually reason about the outcome, read their resolution rules, "
    "and record honest forecasts. Trade only where your edge after fees clears "
    "the minimum, and keep sizes small."
)



def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def usage_today() -> dict:
    with db.get_db() as conn:
        r = conn.execute(
            "SELECT COUNT(*) AS runs, COALESCE(SUM(input_tokens),0) AS i, "
            "COALESCE(SUM(output_tokens),0) AS o, SUM(cost_usd) AS c, "
            "SUM(CASE WHEN cost_usd IS NULL THEN 1 ELSE 0 END) AS unpriced "
            "FROM autopilot_runs WHERE substr(started_at,1,10)=?", (_today(),)).fetchone()
    runs = int(r["runs"] or 0)
    return {
        "runs": runs,
        "tokens": int(r["i"] or 0) + int(r["o"] or 0),
        "costUsd": (round(float(r["c"]), 4) if r["c"] is not None and not r["unpriced"]
                    else None),
    }


def last_started_at() -> Optional[str]:
    with db.get_db() as conn:
        r = conn.execute("SELECT MAX(started_at) FROM autopilot_runs").fetchone()
    return r[0] if r and r[0] else None


def runs(limit: int = 30) -> list[dict]:
    with db.get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM autopilot_runs ORDER BY id DESC LIMIT ?", (int(limit),)).fetchall()
    out = []
    for r in rows:
        try:
            tools = json.loads(r["tool_log"] or "[]")
        except ValueError:
            tools = []
        out.append({
            "id": int(r["id"]), "startedAt": r["started_at"], "finishedAt": r["finished_at"],
            "trigger": r["trigger"], "provider": r["provider"], "model": r["model"],
            "status": r["status"], "steps": int(r["steps"] or 0),
            "inputTokens": r["input_tokens"], "outputTokens": r["output_tokens"],
            "costUsd": r["cost_usd"], "summary": r["summary"] or "",
            "error": r["error"], "tools": tools,
        })
    return out



def _limits(cfg: dict) -> dict:
    return {
        "intervalMin": int(cfg.get("autopilot_interval_min") or 60),
        "maxRunsPerDay": int(cfg.get("autopilot_max_runs_per_day") or 12),
        "dailyTokenBudget": int(cfg.get("autopilot_daily_token_budget") or 1_500_000),
        "maxSteps": int(cfg.get("autopilot_max_steps") or 15),
    }


def blocked_reason(cfg: dict) -> Optional[str]:
    """Why a run cannot start now, or None."""
    lim = _limits(cfg)
    provider = _provider(cfg)
    agent = run_agent(cfg)
    if agent is None:
        return ("The agent Autopilot runs as no longer exists. Pick one under "
                "AI Agents → Autopilot → Run as agent.")
    if not agent.get("enabled", True):
        return f"Autopilot runs as {agent['name']}, which is switched off."
    if not ai_analyst.ready(provider):
        return (f"No {ai_analyst.CAPS[provider].label} key — set it "
                f"under Settings → AI analysis.")
    u = usage_today()
    if u["runs"] >= lim["maxRunsPerDay"]:
        return f"Already ran {u['runs']} times today (limit {lim['maxRunsPerDay']})."
    if u["tokens"] >= lim["dailyTokenBudget"]:
        return f"Today's token budget is spent ({u['tokens']:,} of {lim['dailyTokenBudget']:,})."
    return None


def _provider(cfg: dict) -> str:
    return ai_analyst._norm_provider(cfg.get("ai_provider"))


def tool_refusal(cfg: dict) -> Optional[str]:
    """Why this provider/model cannot run Autopilot at all, or None.

    Blocking — for a per-model provider it is a local call or a free listing —
    so it is NOT part of blocked_reason(), which the scheduler and the status
    poll read on the event loop. run_once() and the Run-now handler ask it
    off the loop, before anything is recorded or billed."""
    provider = _provider(cfg)
    ok, why = ai_analyst.tool_support(provider, cfg.get("ai_model"))
    if ok:
        return None
    return why or (f"{ai_analyst.CAPS[provider].label} can't call tools with this "
                   f"model, and Autopilot works only through tools.")


def _parse(ts: Optional[str]) -> Optional[float]:
    if not ts:
        return None
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def next_due_at(cfg: dict) -> Optional[float]:
    if not cfg.get("autopilot_enabled"):
        return None
    last = _parse(last_started_at())
    if last is None:
        return time.time()
    return last + _limits(cfg)["intervalMin"] * 60


def due(cfg: dict) -> bool:
    nd = next_due_at(cfg)
    return nd is not None and time.time() >= nd and not STATE.running


def status(cfg: dict) -> dict:
    nd = next_due_at(cfg)
    return {
        "enabled": bool(cfg.get("autopilot_enabled")),
        "running": STATE.running,
        "startedAt": STATE.started_at,
        "step": STATE.current_step,
        "lastError": STATE.last_error,
        "nextRunAt": (datetime.fromtimestamp(nd, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                      if nd else None),
        "blockedReason": blocked_reason(cfg) if cfg.get("autopilot_enabled") else None,
        "today": usage_today(),
        "limits": _limits(cfg),
        "provider": _provider(cfg),
        "providerLabel": ai_analyst.CAPS[_provider(cfg)].label,
        "model": ai_analyst.normalize_model(_provider(cfg), cfg.get("ai_model")),
        "tokenAccounting": ai_analyst.CAPS[_provider(cfg)].tokens,
        "toolCount": len(mcp_server.visible_tools(cfg)),
        "agentId": str(cfg.get("autopilot_agent_id") or "default"),
        "agentName": (run_agent(cfg) or {}).get("name"),
    }



def _clip(text: str) -> str:
    if len(text) <= _RESULT_CHARS:
        return text
    return text[:_RESULT_CHARS] + f"\n[... {len(text) - _RESULT_CHARS} more characters cut]"


def _cost(model: str, i: int, o: int, cache_write: int = 0, cache_read: int = 0) -> Optional[float]:
    eff_in = i + int(cache_write * 1.25) + int(cache_read * 0.1)
    return ai_analyst._cost_usd(model, eff_in, o)


class _Run:
    def __init__(self, cfg: dict, trigger: str):
        self.cfg = cfg
        self.trigger = trigger
        self.provider = _provider(cfg)
        self.model = ai_analyst.normalize_model(self.provider, cfg.get("ai_model"))
        self.lim = _limits(cfg)
        self.in_tok = 0
        self.out_tok = 0
        self.cost: Optional[float] = 0.0
        self.estimated = False
        self.steps = 0
        self.tool_log: list[dict] = []
        self.agent_id = str(cfg.get("autopilot_agent_id") or "default")
        self.ctx = {"client": f"autopilot ({self.model})", "agent": self.agent_id}
        self.budget_left = self.lim["dailyTokenBudget"] - usage_today()["tokens"]

    def system(self) -> str:
        mission = str(self.cfg.get("autopilot_mission") or "").strip() or DEFAULT_MISSION
        text = SYSTEM.format(instructions=mcp_server.INSTRUCTIONS,
                             max_steps=self.lim["maxSteps"], mission=mission)
        agent = run_agent(self.cfg)
        if agent is not None and mcp_server.mcp_agents.is_customised(agent):
            rails = mcp_server._agent_rails(self.cfg, agent)
            mode = mcp_server._agent_mode(self.cfg, agent)
            rules = "\n".join(f"- {s}" for s in
                              mcp_server.mcp_agents.rules_summary(agent, rails, mode))
            guide = (f"\nTHE USER'S GUIDE FOR YOU:\n{agent['guide']}\n"
                     if agent.get("guide") else "")
            text += "\n" + AGENT_BLOCK.format(name=agent["name"], guide=guide, rules=rules)
        return text

    def tools(self) -> list[dict]:
        return [t.spec() for t in mcp_server.visible_tools(self.cfg)]

    def add_usage(self, i: int, o: int, cost: Optional[float]) -> None:
        self.in_tok += i
        self.out_tok += o
        self.cost = None if (self.cost is None or cost is None) else self.cost + cost

    def over_budget(self) -> bool:
        return self.in_tok + self.out_tok >= self.budget_left

    async def tool(self, name: str, args: Any) -> tuple[str, bool]:
        self.steps += 1
        STATE.current_step = self.steps
        res = await mcp_server.call_tool(name, args if isinstance(args, dict) else {}, self.ctx)
        text = res["content"][0]["text"] if res.get("content") else ""
        self.tool_log.append({"tool": name, "ok": not res.get("isError"),
                              "brief": text[:160]})
        return _clip(text), bool(res.get("isError"))

    def should_stop(self) -> Optional[str]:
        live_cfg = mcp_server.HOOKS.get_cfg()
        if not live_cfg.get("autopilot_enabled") and self.trigger == "schedule":
            return "stopped"
        if self.over_budget():
            return "budget"
        return None


async def _loop_anthropic(run: _Run, key: str) -> tuple[str, str]:
    http = ai_analyst.ai_providers.counted_client(_TIMEOUT_SEC)
    try:
        return await _anthropic_turns(run, key, http)
    finally:
        http.close()


async def _anthropic_turns(run: _Run, key: str, http) -> tuple[str, str]:
    import anthropic
    client = anthropic.Anthropic(api_key=key, timeout=_TIMEOUT_SEC, max_retries=2,
                                 http_client=http)
    tools = [{"name": t["name"], "description": t["description"],
              "input_schema": t["inputSchema"]} for t in run.tools()]
    system = [{"type": "text", "text": run.system(), "cache_control": {"type": "ephemeral"}}]
    messages: list = [{"role": "user", "content": "Run now. Today is "
                       + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") + "."}]
    final = ""
    while True:
        stop = run.should_stop()
        if stop:
            return final or "Stopped before finishing.", stop
        try:
            resp = await asyncio.to_thread(
                client.messages.create, model=run.model, max_tokens=_MAX_TOKENS,
                system=system, thinking={"type": "adaptive"}, tools=tools,
                messages=messages)
        except anthropic.APIError as e:
            raise ai_analyst.anthropic_error(e, run.model) from e
        u = resp.usage
        cw = int(getattr(u, "cache_creation_input_tokens", 0) or 0)
        cr = int(getattr(u, "cache_read_input_tokens", 0) or 0)
        i = int(u.input_tokens or 0)
        o = int(u.output_tokens or 0)
        run.add_usage(i + cw + cr, o, _cost(run.model, i, o, cw, cr))
        texts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        if texts:
            final = "\n".join(texts).strip()
        calls = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
        if resp.stop_reason == "refusal":
            return final or "The model declined to continue.", "error"
        if resp.stop_reason != "tool_use" or not calls:
            return final, "ok"
        if run.steps + len(calls) > run.lim["maxSteps"]:
            return final or "Reached the tool-call limit for one run.", "steps"
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for c in calls:
            text, is_err = await run.tool(c.name, c.input)
            results.append({"type": "tool_result", "tool_use_id": c.id,
                            "content": text, "is_error": is_err})
        messages.append({"role": "user", "content": results})


async def _loop_openai(run: _Run, key: str) -> tuple[str, str]:
    http = ai_analyst.ai_providers.counted_client(_TIMEOUT_SEC)
    try:
        return await _openai_turns(run, key, http)
    finally:
        http.close()


async def _openai_turns(run: _Run, key: str, http) -> tuple[str, str]:
    import openai
    client = openai.OpenAI(api_key=key, timeout=_TIMEOUT_SEC, max_retries=2,
                           http_client=http)
    tools = [{"type": "function", "name": t["name"], "description": t["description"],
              "parameters": t["inputSchema"], "strict": False} for t in run.tools()]
    items: list = [{"role": "user", "content": "Run now. Today is "
                    + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") + "."}]
    final = ""
    while True:
        stop = run.should_stop()
        if stop:
            return final or "Stopped before finishing.", stop
        try:
            resp = await asyncio.to_thread(
                client.responses.create, model=run.model, instructions=run.system(),
                input=items, tools=tools, max_output_tokens=_MAX_TOKENS)
        except openai.APIError as e:
            raise ai_analyst.openai_error(e, run.model) from e
        u = getattr(resp, "usage", None)
        run.add_usage(int(getattr(u, "input_tokens", 0) or 0),
                      int(getattr(u, "output_tokens", 0) or 0), None)
        if getattr(resp, "output_text", None):
            final = resp.output_text.strip()
        calls = [it for it in (resp.output or []) if getattr(it, "type", None) == "function_call"]
        if not calls:
            return final, "ok"
        if run.steps + len(calls) > run.lim["maxSteps"]:
            return final or "Reached the tool-call limit for one run.", "steps"
        items += list(resp.output)
        for c in calls:
            try:
                args = json.loads(c.arguments or "{}")
            except ValueError:
                args = {}
            text, _err = await run.tool(c.name, args)
            items.append({"type": "function_call_output", "call_id": c.call_id,
                          "output": text})


async def _loop_generic(run: _Run, key: str) -> tuple[str, str]:
    """OpenRouter, Gemini, Ollama, LM Studio. Same order of checks as the two
    SDK loops — stop/budget, call, account, refusal, done, step limit, tools —
    so a budget means the same thing whichever provider is spending it."""
    import ai_providers
    first = ("Run now. Today is "
             + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") + ".")
    chat = await asyncio.to_thread(
        ai_providers.open_tool_chat, run.provider, key or None, run.model,
        run.system(), run.tools(), first)
    run.model = chat.model
    run.ctx = {**run.ctx, "client": f"autopilot ({run.model})"}
    final = ""
    while True:
        stop = run.should_stop()
        if stop:
            return final or "Stopped before finishing.", stop
        too_big = chat.context_problem()
        if too_big:
            return (final + "\n\n" if final else "") + too_big, "context"
        turn = await asyncio.to_thread(chat.send)
        run.estimated = run.estimated or turn.estimated
        run.add_usage(turn.input_tokens, turn.output_tokens, turn.cost)
        if getattr(turn, "failed", None):
            raise ai_analyst.AiError(turn.failed)
        if turn.text:
            final = turn.text
        if turn.refusal:
            return final or "The model declined to continue.", "error"
        if not turn.calls:
            return final, "ok"
        if run.steps + len(turn.calls) > run.lim["maxSteps"]:
            return final or "Reached the tool-call limit for one run.", "steps"
        results = []
        for c in turn.calls:
            text, is_err = await run.tool(c.name, c.args)
            results.append((c, text, is_err))
        chat.add_results(turn, results)


async def run_once(cfg: dict, trigger: str = "schedule") -> dict:
    """One autopilot session. Returns the stored run row."""
    if _LOCK.locked():
        return {"ok": False, "message": "Autopilot is already running."}
    why = blocked_reason(cfg)
    if not why:
        why = await asyncio.to_thread(tool_refusal, cfg)
    if why:
        STATE.last_error = why
        return {"ok": False, "message": why}
    async with _LOCK:
        STATE.running = True
        STATE.started_at = _now()
        STATE.current_step = 0
        run = _Run(cfg, trigger)
        with db.get_db() as conn:
            cur = conn.execute(
                "INSERT INTO autopilot_runs (started_at, trigger, provider, model, status) "
                "VALUES (?,?,?,?, 'running')",
                (STATE.started_at, trigger, run.provider, run.model))
            rid = int(cur.lastrowid)
        summary, status_, error = "", "error", None
        try:
            key = ai_analyst._read_key(run.provider)
            loop = {"openai": _loop_openai,
                    "anthropic": _loop_anthropic}.get(run.provider, _loop_generic)
            summary, status_ = await loop(run, key or "")
            if run.estimated:
                summary = ((summary or "").rstrip() + "\n\n[Token counts for this run "
                           "are estimates from text length: "
                           f"{ai_analyst.CAPS[run.provider].label} did not report usage "
                           "for every turn. The daily budget counted the estimates.]")
            STATE.last_error = None
        except ai_analyst.AiError as e:
            error = str(e)
            STATE.last_error = error
        except Exception as e:
            logger.warning("[autopilot] run %s failed: %s: %s", rid, type(e).__name__, e)
            error = f"{type(e).__name__}: {e}"
            STATE.last_error = error
        finally:
            with db.get_db() as conn:
                conn.execute(
                    "UPDATE autopilot_runs SET finished_at=?, model=?, status=?, steps=?, "
                    "input_tokens=?, output_tokens=?, cost_usd=?, summary=?, "
                    "tool_log=?, error=? WHERE id=?",
                    (_now(), run.model, status_ if error is None else "error", run.steps,
                     run.in_tok, run.out_tok,
                     round(run.cost, 4) if run.cost is not None else None,
                     (summary or "")[:6000], json.dumps(run.tool_log[:80]), error, rid))
            STATE.running = False
            STATE.current_step = 0
        logger.info("[autopilot] run %s %s: %d steps, %d tokens",
                    rid, status_ if error is None else "error", run.steps,
                    run.in_tok + run.out_tok)
        if mcp_server.HOOKS.emit:
            try:
                head = (error or summary or "").strip().splitlines()
                await mcp_server.HOOKS.emit("mcp:order", {
                    "mode": "action",
                    "message": f"Autopilot run {'failed' if error else 'finished'}: "
                               + (head[0][:160] if head else f"{run.steps} steps")})
            except Exception:
                pass
        return {"ok": error is None, "message": error or "Run finished.",
                "run": runs(1)[0] if runs(1) else None}
