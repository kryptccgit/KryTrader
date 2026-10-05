from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Optional

import httpx

import kalshi_api

logger = logging.getLogger("remote.telegram")

API = "https://api.telegram.org"
POLL_TIMEOUT = 25
_RECONNECT_MIN = 2.0
_RECONNECT_MAX = 60.0


class TelegramBot:
    def __init__(self) -> None:
        self.token: str = ""
        self.chat_id: str = ""
        self.task: Optional[asyncio.Task] = None
        self.connected = False
        self.last_error: Optional[str] = None
        self.last_message_at: Optional[float] = None
        self.bot_name: Optional[str] = None
        self._offset = 0
        self._stop = asyncio.Event()
        self._client: Optional[httpx.AsyncClient] = None
        self._on_command: Optional[Callable] = None
        self._on_paired: Optional[Callable] = None
        self._check_code: Optional[Callable] = None

    def start(self, token: str, chat_id: str, on_command: Callable,
              check_code: Callable, on_paired: Callable) -> None:
        if self.task and not self.task.done():
            return
        self.token = (token or "").strip()
        self.chat_id = (chat_id or "").strip()
        self._on_command = on_command
        self._check_code = check_code
        self._on_paired = on_paired
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
            "configured": bool(self.token),
            "paired": bool(self.chat_id),
            "running": bool(self.task and not self.task.done()),
            "connected": self.connected,
            "botName": self.bot_name,
            "lastError": self.last_error,
            "lastMessageAt": self.last_message_at,
        }

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=POLL_TIMEOUT + 10,
                event_hooks=kalshi_api.counting_hooks(),
            )
        return self._client

    async def _call(self, method: str, **params) -> Any:
        c = await self._http()
        try:
            r = await c.post(f"{API}/bot{self.token}/{method}", json=params)
        except Exception as e:
            self.last_error = f"{method}: {e}"
            return None
        if r.status_code >= 400:
            body = r.text[:160]
            self.last_error = f"{method}: HTTP {r.status_code} {body}"
            if r.status_code == 401:
                self.last_error = "Telegram rejected the bot token."
            elif r.status_code == 409:
                self.last_error = (
                    "Another program is already using this Telegram bot token "
                    "— Telegram allows only one. Close the other copy of Krypt "
                    "Trader, or make a second bot with @BotFather.")
            return None
        try:
            data = r.json()
        except Exception:
            return None
        return data.get("result") if data.get("ok") else None

    async def send(self, text: str, chat: Optional[str] = None) -> bool:
        target = chat or self.chat_id
        if not target:
            return False
        for chunk in _chunks(text, 3900):
            res = await self._call("sendMessage", chat_id=target, text=chunk,
                                   disable_web_page_preview=True)
            if res is None:
                return False
        return True

    async def _run(self) -> None:
        backoff = _RECONNECT_MIN
        me = await self._call("getMe")
        if me:
            self.bot_name = me.get("username")
            self.connected = True
            self.last_error = None
        while not self._stop.is_set():
            try:
                updates = await self._call(
                    "getUpdates", offset=self._offset, timeout=POLL_TIMEOUT,
                    allowed_updates=["message"])
                if updates is None:
                    self.connected = False
                    await asyncio.sleep(backoff)
                    backoff = min(_RECONNECT_MAX, backoff * 2)
                    continue
                self.connected = True
                backoff = _RECONNECT_MIN
                for u in updates:
                    self._offset = max(self._offset, int(u.get("update_id", 0)) + 1)
                    await self._handle(u)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.connected = False
                self.last_error = str(e)
                logger.info("telegram poll: %s", e)
                await asyncio.sleep(backoff)
                backoff = min(_RECONNECT_MAX, backoff * 2)

    async def _handle(self, update: dict) -> None:
        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        chat_id = str(chat.get("id") or "")
        text = (msg.get("text") or "").strip()
        if not chat_id or not text:
            return

        if chat.get("type") != "private":
            return

        if not self.chat_id:
            parts = text.split()
            cmd = parts[0].lstrip("/").lower() if parts else ""
            if cmd == "pair" and len(parts) > 1 and self._check_code:
                if self._check_code(parts[1]):
                    self.chat_id = chat_id
                    if self._on_paired:
                        self._on_paired(chat_id)
                    logger.info("telegram: paired with chat %s", chat_id)
                    await self.send(
                        "Paired. This chat can now reach your terminal.\n"
                        "Send 'help' for what it can do.", chat=chat_id)
                    return
                await self.send("That pairing code is not valid.", chat=chat_id)
                return
            await self.send(
                "This bot is not paired. Open Krypt Trader, go to Remote, and "
                "send the code it shows you as:  pair CODE", chat=chat_id)
            return

        if chat_id != self.chat_id:
            return

        self.last_message_at = time.time()
        if self._on_command is None:
            return
        try:
            reply = await self._on_command(text, f"telegram:{chat_id}")
        except Exception as e:
            logger.warning("telegram command failed: %s", e)
            reply = f"That failed: {e}"
        if reply:
            await self.send(reply)


def _chunks(text: str, size: int):
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


BOT = TelegramBot()
