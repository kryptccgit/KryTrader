"""Connection health: one row per connection, each with a fix the user can act on.

Every surface this app connects — Kalshi, the AI provider, the agent server
and its HTTP API, Autopilot, the phone bots, the market feed — already reports
its own state somewhere, in its own words, on its own page. When something is
broken the user has to know which page to look at. This module puts them in
one list, and pairs every non-green row with the thing to do about it.

Two kinds of check, and the difference is the point:

  * **Local** checks read state this process already holds (is the listener
    up, is a token saved, did a bot connect, how much Autopilot budget is
    left). Free, instant, safe to run whenever the panel opens.
  * **Network** checks prove a connection end to end: a signed Kalshi read, a
    provider's free model-listing call, a loopback request to our own API.
    They run ONLY when the user clicks "Run checks" (`deep=True`), never on a
    poll and never on open. A signed read on a timer is account traffic the
    user did not ask for, and a provider call is billed or rate-limited
    against their key (invariant 8's rule, applied to diagnostics).

The builders here are pure: service.py gathers the state, these turn it into
rows. That keeps every row's wording and status testable without a socket.
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Optional

OK, WARN, FAIL, OFF = "ok", "warn", "fail", "off"

_PROVIDER_LABEL = {
    "anthropic": "Anthropic", "openai": "OpenAI", "openrouter": "OpenRouter",
    "gemini": "Gemini", "ollama": "Ollama", "lmstudio": "LM Studio",
}


def row(id: str, label: str, status: str, detail: str, fix: Optional[str] = None,
        action: Optional[dict] = None, network: bool = False,
        tested: bool = False) -> dict:
    """`network` says whether this check CAN touch the network (shown so the
    user knows why some rows wait for a click); `tested` says whether this
    particular result came from an end-to-end probe or from local state."""
    return {"id": id, "label": label, "status": status, "detail": detail,
            "fix": fix, "action": action, "network": network, "tested": tested}


def error_text(e: BaseException) -> str:
    """An exception in words for a row's detail. Never the Python class name
    ("TimeoutError: " told the user nothing; the log keeps the detail)."""
    if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
        return "it timed out"
    if isinstance(e, (ConnectionError, OSError)) and not str(e).strip():
        return "the connection failed"
    return str(e).strip()[:140] or "an unexpected error (details are in the log)"


def nav(page: str, label: str) -> dict:
    return {"kind": "nav", "page": page, "label": label}


def copy(text: str, label: str = "Copy fix command") -> dict:
    return {"kind": "copy", "text": text, "label": label}


def port_owner_command(port: int) -> str:
    if sys.platform == "win32":
        return f"netstat -ano | findstr :{int(port)}"
    return f"lsof -nP -iTCP:{int(port)} -sTCP:LISTEN"



def kalshi_error_fix(env: str, err: BaseException) -> tuple[str, str]:
    """(detail, fix) for a failed signed read, by what actually went wrong.
    "Test failed" with no reason is the message that makes people paste their
    private key into a support chat. `env` is kept for callers; there is one
    Kalshi venue and one key."""
    status = getattr(err, "status", None)
    text = str(err)
    low = text.lower()
    if status == 401 or "401" in low or "unauthorized" in low or "signature" in low:
        return ("Kalshi rejected the signed request (401).",
                "The key id and private key do not match, or the key was deleted. "
                "Create a new API key on kalshi.com and paste both halves again "
                "under API Keys.")
    if status == 403 or "403" in low or "forbidden" in low:
        return ("Kalshi refused the request (403).",
                "The key exists but is not allowed to read the portfolio. Create a "
                "key with read/trade access under API Keys.")
    if "timestamp" in low or "clock" in low or "skew" in low:
        return ("Kalshi says the request timestamp is off.",
                "Your computer clock is wrong. Turn on 'Set time automatically' in "
                "the system date & time settings, then run the check again.")
    if "not set" in low or "no credentials" in low or "missing" in low:
        return ("No Kalshi API key is saved.",
                "Add your API key id and private key from kalshi.com under API Keys.")
    if any(s in low for s in ("timeout", "timed out", "connect", "network",
                              "name resolution", "getaddrinfo", "ssl", "unreachable")):
        return ("Could not reach Kalshi.",
                "Check your internet connection, VPN or firewall, then run the "
                "check again. Kalshi's status page will say if it is down.")
    return (f"The signed read failed: {text[:160] or error_text(err)}",
            "Re-check the key under API Keys. If it persists, copy diagnostics "
            "from the Logs page.")


def check_kalshi(env: str, present: bool, auth_ok: bool, *,
                 probed: bool = False, probe_ok: Optional[bool] = None,
                 probe_error: Optional[BaseException] = None) -> dict:
    """`env` is the account scope: "paper" or "production" (Live)."""
    paper = env == "paper"
    label = "Kalshi API key"
    if not present:
        if paper:
            return row("kalshi", label, OK,
                       "No key saved — Paper mode does not need one.",
                       "Add a key from kalshi.com under API Keys when you want "
                       "to go live.", nav("api", "Open API Keys"))
        return row("kalshi", label, FAIL, "No API key saved, and the app is in Live mode.",
                   "Add your API key id and private key from kalshi.com under API "
                   "Keys, or switch back to Paper.", nav("api", "Open API Keys"))
    if probed:
        if probe_ok:
            return row("kalshi", label, OK,
                       "Signed balance read succeeded.",
                       network=True, tested=True)
        detail, fix = kalshi_error_fix(env, probe_error or RuntimeError("unknown"))
        return row("kalshi", label, FAIL, detail, fix,
                   nav("api", "Open API Keys"), network=True, tested=True)
    if paper:
        return row("kalshi", label, OK,
                   "Key saved. The app is in Paper mode, so nothing is signed with "
                   "it; Run checks tests it.", network=True)
    if auth_ok:
        return row("kalshi", label, OK,
                   "Key saved and verified by the backend. Run checks to test it again.",
                   network=True)
    return row("kalshi", label, WARN, "Key saved but not verified yet.",
               "Run checks to test it end to end, or re-enter it under API Keys.",
               nav("api", "Open API Keys"), network=True)



def check_ai(provider: str, *, active: bool, has_key: bool, can_probe: bool,
             probed: bool = False, probe: Optional[dict] = None,
             probe_error: Optional[BaseException] = None, local: bool = False,
             idle: bool = False, needed: bool = False) -> dict:
    """`idle`: a saved key for a provider that is NOT selected, on a deep run.
    It is deliberately not contacted -- the Privacy page promises that only
    the selected provider ever is -- so the row says so instead of implying
    the key was tested.

    `needed`: something is waiting on this provider right now (Autopilot is
    on and uses it). Only then is a missing key a problem; the provider a
    user who never set up AI happens to have selected by default is just
    "not set up"."""
    name = _PROVIDER_LABEL.get(provider, provider.title())
    rid = f"ai:{provider}"
    if local:
        label = f"{name} (on this machine)" + (" (active)" if active else "")
        if not probed:
            return row(rid, label, OK,
                       "Selected. Run checks to see whether its local server answers.",
                       network=True)
    else:
        label = f"{name} API key" + (" (active)" if active else "")
    if not has_key:
        if active and needed:
            return row(rid, label, WARN, f"No {name} key saved, and Autopilot is on.",
                       "Autopilot needs it to run. Add it under Settings -> AI analysis.",
                       nav("settings", "Open Settings"))
        if active:
            return row(rid, label, OFF, "Not set up.",
                       "Optional: Analyse and Autopilot use it. Add a key under "
                       "Settings -> AI analysis when you want them.",
                       nav("settings", "Open Settings"))
        return row(rid, label, OFF, "Not configured.")
    if not can_probe:
        return row(rid, label, OK,
                   "Key saved (encrypted). This build cannot test it without a "
                   "billed call, so it is not tested here.")
    if idle:
        return row(rid, label, OK,
                   "Key saved (encrypted). Not tested: Run checks contacts only the "
                   "provider selected under Settings -> AI analysis.")
    if not probed:
        return row(rid, label, OK, "Key saved. Run checks to test it.", network=True)
    if probe_error is not None:
        return row(rid, label, FAIL,
                   (f"Could not reach {name}: " if local else "Could not test the key: ")
                   + error_text(probe_error),
                   "Check your connection and run the check again.",
                   nav("settings", "Open Settings"), network=True, tested=True)
    probe = probe or {}
    msg = str(probe.get("message") or "")
    if probe.get("ok"):
        models = probe.get("models") or []
        extra = f" {len(models)} models available." if models else ""
        return row(rid, label, OK, (msg or (f"{name} is running." if local else f"{name} accepted the key.")) + extra,
                   network=True, tested=True)
    if local:
        return row(rid, label, FAIL, msg or f"{name} didn't answer.",
                   f"Start {name} and make sure the model selected under Settings -> "
                   f"AI analysis is pulled/loaded there, then run the check again.",
                   nav("settings", "Open Settings"), network=True, tested=True)
    if probe.get("reason") == "model":
        return row(rid, label, FAIL, msg,
                   "Pick a model from the list under Settings -> AI analysis.",
                   nav("settings", "Open Settings"), network=True, tested=True)
    return row(rid, label, FAIL, msg or f"{name} rejected the key.",
               f"Paste a fresh {name} key under Settings -> AI analysis.",
               nav("settings", "Open Settings"), network=True, tested=True)



def check_mcp(st: dict) -> dict:
    """`st` is mcp_server.status() (plus lastSeen). Local only."""
    port = st.get("port")
    if not st.get("enabled"):
        return row("mcp", "MCP server", OFF, "Switched off.",
                   "Turn on 'Enable the MCP server' on this page to let agents connect.")
    if not st.get("running"):
        return row("mcp", "MCP server", FAIL,
                   st.get("lastError") or f"Not listening on 127.0.0.1:{port}.",
                   f"Another program may own port {port}. Find it with the command "
                   f"below, or pick another port here and re-copy your client configs.",
                   copy(port_owner_command(port or 0)))
    if not st.get("hasToken"):
        return row("mcp", "MCP server", FAIL, "Listening, but no token is saved.",
                   "Switch the server off and on again to create one.")
    seen = st.get("lastSeen")
    ag = st.get("agents") or []
    agents_txt = ""
    if ag:
        with_tok = sum(1 for a in ag if a.get("hasToken"))
        seen_n = sum(1 for a in ag if a.get("lastSeenAt"))
        agents_txt = (f" Agents: {len(ag)}, {with_tok} with a token, "
                      f"{seen_n} seen this session.")
    if not seen:
        return row("mcp", "MCP server", WARN,
                   f"Listening on 127.0.0.1:{port}. No client has connected this session."
                   + agents_txt,
                   "Copy a client config from 'Connect a client' into Cursor, Claude "
                   "or Codex, then restart that client.")
    return row("mcp", "MCP server", OK,
               f"Listening on 127.0.0.1:{port}. Last client: {seen['client']} at "
               f"{seen['at']} UTC." + agents_txt)


def check_http(st: dict, *, probed: bool = False, probe: Optional[dict] = None) -> dict:
    label = "HTTP API"
    if not st.get("enabled"):
        return row("http", label, OFF, "The MCP server is off, so the HTTP API is too.",
                   network=True)
    if not st.get("httpEnabled"):
        return row("http", label, OFF, "Switched off.",
                   "Turn on the HTTP API on this page for scripts, n8n or LangChain.",
                   network=True)
    if not st.get("running"):
        return row("http", label, FAIL, "The listener it shares with MCP is not running.",
                   "Fix the MCP server row first.", network=True)
    if not probed:
        return row("http", label, OK,
                   f"Served at 127.0.0.1:{st.get('port')}/api/v1. Run checks to call it.",
                   network=True)
    probe = probe or {}
    if probe.get("ok"):
        return row("http", label, OK,
                   f"Answered on loopback: {probe.get('tools')} tools listed.",
                   network=True, tested=True)
    code = probe.get("status")
    if code == 401:
        return row("http", label, FAIL, "The server refused its own token (401).",
                   "Rotate the token on this page, then re-copy every client config.",
                   network=True, tested=True)
    return row("http", label, FAIL,
               f"No answer on 127.0.0.1:{st.get('port')}: {probe.get('error') or code}.",
               "A firewall or security tool may be blocking loopback connections. "
               "Allow Krypt Trader, or check the port with the command below.",
               copy(port_owner_command(st.get("port") or 0)), network=True, tested=True)


def _socket_error(e: BaseException) -> str:
    if isinstance(e, ConnectionRefusedError):
        return "connection refused"
    if isinstance(e, ConnectionResetError):
        return "the connection was reset"
    return error_text(e)


async def probe_http(port: int, token: str, timeout: float = 3.0) -> dict:
    """GET /api/v1/tools on our own loopback listener, with our own token.
    Hand-rolled over a socket so it needs no HTTP client and cannot be pointed
    anywhere but 127.0.0.1: the host is a constant, the port is ours."""
    try:
        r, w = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", int(port)), timeout)
    except Exception as e:
        return {"ok": False, "status": None, "error": _socket_error(e)}
    try:
        head = (f"GET /api/v1/tools HTTP/1.1\r\nHost: 127.0.0.1:{int(port)}\r\n"
                f"Authorization: Bearer {token}\r\nUser-Agent: krypt-health-check\r\n"
                f"Connection: close\r\n\r\n")
        w.write(head.encode("latin-1"))
        await w.drain()
        raw = await asyncio.wait_for(r.read(4 * 1024 * 1024), timeout)
    except Exception as e:
        return {"ok": False, "status": None, "error": _socket_error(e)}
    finally:
        try:
            w.close()
        except Exception:
            pass
    hdr, _, body = raw.partition(b"\r\n\r\n")
    try:
        code = int(hdr.split(b" ", 2)[1])
    except (IndexError, ValueError):
        return {"ok": False, "status": None, "error": "malformed response"}
    if code != 200:
        return {"ok": False, "status": code, "error": f"HTTP {code}"}
    try:
        n = len(json.loads(body).get("tools") or [])
    except ValueError:
        return {"ok": False, "status": code, "error": "unreadable body"}
    return {"ok": True, "status": code, "tools": n}



def check_autopilot(st: dict) -> dict:
    """`st` is autopilot.status(). Local only."""
    label = "Autopilot"
    if not st.get("enabled"):
        return row("autopilot", label, OFF, "Switched off.")
    lim = st.get("limits") or {}
    today = st.get("today") or {}
    runs_left = max(0, int(lim.get("maxRunsPerDay") or 0) - int(today.get("runs") or 0))
    tok_left = max(0, int(lim.get("dailyTokenBudget") or 0) - int(today.get("tokens") or 0))
    budget = f"{runs_left} runs and {tok_left:,} tokens left today (UTC)."
    blocked = st.get("blockedReason")
    if blocked:
        fix = ("Add the key under Settings -> AI analysis." if "key" in blocked.lower()
               else "It resumes at 00:00 UTC, or raise the budget in the Autopilot panel.")
        act = nav("settings", "Open Settings") if "key" in blocked.lower() else None
        return row("autopilot", label, WARN, f"Blocked: {blocked}", fix, act)
    if st.get("lastError"):
        return row("autopilot", label, WARN, f"Last run failed: {st['lastError'][:160]}. {budget}",
                   "Open the run log in the Autopilot panel for the step that failed.")
    nxt = st.get("nextRunAt")
    when = ("On, running now." if st.get("running")
            else f"On, next run {nxt} UTC." if nxt else "On.")
    return row("autopilot", label, OK, f"{when} {budget}")



def check_remote(which: str, *, enabled: bool, has_token: bool, paired: bool,
                 bot: dict) -> dict:
    """`bot` is the transport's BOT.status(). Local only: it reports the
    connection the bot already holds, it does not send anything."""
    name = which.title()
    rid = f"remote:{which}"
    label = f"{name} bot"
    open_remote = nav("remote", "Open Remote")
    if not enabled:
        return row(rid, label, OFF, "Switched off.")
    if not has_token:
        return row(rid, label, FAIL, "Enabled, but no bot token is saved.",
                   f"Paste the {name} bot token on the Remote page.", open_remote)
    if not paired:
        how = ("Enter your Discord user id" if which == "discord"
               else "Send the pairing code to your bot from Telegram")
        return row(rid, label, WARN, "Token saved, but not paired with your account.",
                   f"{how} on the Remote page.", open_remote)
    if bot.get("connected"):
        nm = f" as {bot['botName']}" if bot.get("botName") else ""
        return row(rid, label, OK, f"Connected{nm} and paired.")
    err = bot.get("lastError")
    if not bot.get("running"):
        return row(rid, label, FAIL, err or "Not running.",
                   "Switch it off and on again on the Remote page.", open_remote)
    return row(rid, label, WARN, err or "Connecting...",
               "If it does not connect within a minute, check the token on the "
               "Remote page" + (" and that the bot has the Message Content intent."
                                if which == "discord" else "."), open_remote)



def check_ws(stats: Optional[dict], *, authed: bool) -> dict:
    """`stats` is kalshi_ws.stats(). Local only."""
    label = "Kalshi live feed"
    if stats is None:
        return row("ws", label, OFF, "Not available in this build.")
    if not stats.get("enabled"):
        return row("ws", label, OFF, "Disabled; prices come from REST polling.")
    if stats.get("connected"):
        age = stats.get("lastMsgAgeSec")
        if age is not None and age > 60:
            return row("ws", label, WARN,
                       f"Connected but silent for {age:.0f}s; quotes may be stale.",
                       "It reconnects by itself. If this persists, restart Krypt Trader.")
        return row("ws", label, OK,
                   f"Connected ({stats.get('env')}), {stats.get('books', 0)} live books.")
    if not authed:
        return row("ws", label, WARN, "Not connected: the feed needs verified Kalshi credentials.",
                   "Fix the Kalshi row first. Prices fall back to REST meanwhile.",
                   nav("api", "Open API Keys"))
    return row("ws", label, WARN, "Not connected; prices are coming from REST polling.",
               "It retries by itself. A VPN or firewall blocking wss:// connections "
               "is the usual cause.")
