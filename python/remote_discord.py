"""Discord transport: a minimal Gateway client.

Deliberately hand-rolled on `websockets` rather than pulling in discord.py. The
app ships a PyInstaller bundle and its whole dependency list is three packages;
adding a full framework to receive direct messages and post replies would be
the largest thing in the build. The Gateway subset needed here is small and the
codebase already hand-rolls a resilient websocket client (kalshi_ws.py), so
this follows the same shape.

What it does: IDENTIFY, heartbeat, listen for MESSAGE_CREATE, and POST replies
over the REST API.

── The security rule this file exists to enforce ───────────────────────────
Only a DIRECT message from the exact paired user id is ever passed to the
command engine. Two independent checks, because either one alone has a failure
mode:

  * the author's id must equal the configured id — otherwise anyone who can
    reach the bot can drive it;
  * the channel must be a DM (guild_id absent, channel type 1) — otherwise
    inviting the bot to a server would let it answer "what are my positions"
    in front of everyone in it.

Everything else is dropped silently. A bot that explains itself to strangers is
a bot that confirms to strangers that it exists.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Optional

import httpx

import kalshi_api
import ws_ssl

logger = logging.getLogger("remote.discord")

try:
    import websockets
    _WS_OK = True
except Exception:
    websockets = None
    _WS_OK = False

API = "https://discord.com/api/v10"
GATEWAY = "wss://gateway.discord.gg/?v=10&encoding=json"

INTENTS = (1 << 12) | (1 << 15)

_RECONNECT_MIN = 2.0
_RECONNECT_MAX = 60.0


class DiscordBot:
    def __init__(self) -> None:
        self.token: str = ""
        self.user_id: str = ""
        self.task: Optional[asyncio.Task] = None
        self.connected = False
        self.last_error: Optional[str] = None
        self.last_message_at: Optional[float] = None
        self.bot_name: Optional[str] = None
        self._stop = asyncio.Event()
        self._dm_channel: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._on_command: Optional[Callable] = None
        self._seq: Optional[int] = None
        self._saw_content = False

    def start(self, token: str, user_id: str, on_command: Callable) -> None:
        if self.task and not self.task.done():
            return
        self.token = (token or "").strip()
        self.user_id = (user_id or "").strip()
        self._on_command = on_command
        self._stop = asyncio.Event()
        self.task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except (asyncio.CancelledError, Exception):
                pass
        self.task = None
        self.connected = False
        if self._client is not None and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception:
                pass
        self._client = None

    def status(self) -> dict:
        return {
            "configured": bool(self.token and self.user_id),
            "running": bool(self.task and not self.task.done()),
            "connected": self.connected,
            "botName": self.bot_name,
            "lastError": self.last_error,
            "lastMessageAt": self.last_message_at,
            "sawMessageContent": self._saw_content,
        }

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=15.0,
                headers={
                    "Authorization": f"Bot {self.token}",
                    "User-Agent": "KryptTrader (https://krypt.cc, 1.0)",
                    "Content-Type": "application/json",
                },
                event_hooks=kalshi_api.counting_hooks(),
            )
        return self._client

    async def _dm_channel_id(self) -> Optional[str]:
        if self._dm_channel:
            return self._dm_channel
        try:
            c = await self._http()
            r = await c.post(f"{API}/users/@me/channels",
                             json={"recipient_id": self.user_id})
            if r.status_code < 300:
                self._dm_channel = str(r.json().get("id") or "") or None
        except Exception as e:
            logger.info("discord: could not open a DM channel: %s", e)
        return self._dm_channel

    async def send(self, text: str) -> bool:
        """Push a message to the paired user. Used for replies AND alerts."""
        chan = await self._dm_channel_id()
        if not chan:
            return False
        try:
            c = await self._http()
            for chunk in _chunks(text, 1900):
                r = await c.post(f"{API}/channels/{chan}/messages",
                                 json={"content": chunk})
                if r.status_code >= 300:
                    self.last_error = f"send failed: HTTP {r.status_code}"
                    return False
            return True
        except Exception as e:
            self.last_error = f"send failed: {e}"
            return False

    async def _run(self) -> None:
        if not _WS_OK:
            self.last_error = "the websockets package is unavailable"
            return
        backoff = _RECONNECT_MIN
        while not self._stop.is_set():
            try:
                await self._connect_once()
                backoff = _RECONNECT_MIN
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.connected = False
                self.last_error = str(e)
                logger.info("discord gateway: %s (retry in %.0fs)", e, backoff)
            if self._stop.is_set():
                return
            await asyncio.sleep(backoff)
            backoff = min(_RECONNECT_MAX, backoff * 2)

    async def _connect_once(self) -> None:
        async with websockets.connect(
            GATEWAY, max_size=2 ** 22, ssl=ws_ssl.client_context(),
        ) as ws:
            hello = json.loads(await ws.recv())
            interval = float(hello["d"]["heartbeat_interval"]) / 1000.0
            await ws.send(json.dumps({
                "op": 2,
                "d": {
                    "token": self.token,
                    "intents": INTENTS,
                    "properties": {"os": "windows", "browser": "krypt",
                                   "device": "krypt"},
                },
            }))
            hb = asyncio.create_task(self._heartbeat(ws, interval))
            try:
                async for raw in ws:
                    if self._stop.is_set():
                        break
                    await self._handle(json.loads(raw))
            finally:
                hb.cancel()
                self.connected = False

    async def _heartbeat(self, ws, interval: float) -> None:
        while True:
            await asyncio.sleep(interval)
            try:
                await ws.send(json.dumps({"op": 1, "d": self._seq}))
            except Exception:
                return

    async def _handle(self, msg: dict) -> None:
        if msg.get("s") is not None:
            self._seq = msg["s"]
        op = msg.get("op")
        if op == 9:
            raise RuntimeError(
                "Discord rejected the session (invalid token, or the "
                "MESSAGE CONTENT intent is not enabled on the bot)")
        if op != 0:
            return

        event, data = msg.get("t"), msg.get("d") or {}
        if event == "READY":
            self.connected = True
            self.last_error = None
            user = data.get("user") or {}
            self.bot_name = user.get("username")
            logger.info("discord: connected as %s", self.bot_name)
            return
        if event != "MESSAGE_CREATE":
            return

        author = (data.get("author") or {})
        if str(author.get("id") or "") != self.user_id:
            return
        if data.get("guild_id"):
            return
        if author.get("bot"):
            return

        content = (data.get("content") or "").strip()
        if content:
            self._saw_content = True
        else:
            self.last_error = (
                "A message arrived with no text. Enable the MESSAGE CONTENT "
                "intent for your bot in the Discord developer portal.")
            await self.send(self.last_error)
            return

        self.last_message_at = time.time()
        self._dm_channel = str(data.get("channel_id") or "") or self._dm_channel
        if self._on_command is None:
            return
        try:
            reply = await self._on_command(content, f"discord:{self.user_id}")
        except Exception as e:
            logger.warning("discord command failed: %s", e)
            reply = f"That failed: {e}"
        if reply:
            await self.send(reply)


def _chunks(text: str, size: int):
    """Split on line boundaries where possible — a table cut mid-row is
    unreadable on a phone."""
    if len(text) <= size:
        yield text
        return
    buf = ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > size:
            if buf:
                yield buf
            buf = line
        else:
            buf += line
    if buf:
        yield buf


BOT = DiscordBot()
