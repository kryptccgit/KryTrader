from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from collections import deque
from typing import Optional

import ws_ssl

logger = logging.getLogger("spot_ws")

try:
    import websockets
    _WS_IMPORT_OK = True
except Exception:
    websockets = None
    _WS_IMPORT_OK = False

_URL = os.environ.get("KRYPT_SPOT_WS_URL") or "wss://advanced-trade-ws.coinbase.com"

_DISABLED = os.environ.get("KRYPT_SPOT_WS", "1").strip().lower() in (
    "0", "off", "false", "no",
)

PRODUCTS: dict[str, str] = {
    "BTC": "BTC-USD",
    "ETH": "ETH-USD",
    "SOL": "SOL-USD",
    "XRP": "XRP-USD",
    "DOGE": "DOGE-USD",
}
_ASSET_BY_PRODUCT = {v: k for k, v in PRODUCTS.items()}

_FRESH_SEC = 10.0
_SILENT_TIMEOUT_SEC = 30.0
_RECONNECT_MAX_SEC = 60.0
_SAMPLES_MAX = 180
_SETTLE_WINDOW_SEC = 60


class _Client:
    def __init__(self) -> None:
        self.connected: bool = False
        self._stop: bool = False
        self._task: Optional[asyncio.Task] = None
        self._sampler_task: Optional[asyncio.Task] = None
        self._ws = None
        self.last_msg_t: float = 0.0
        self.prices: dict[str, tuple[float, float]] = {}
        self.samples: dict[str, deque] = {
            a: deque(maxlen=_SAMPLES_MAX) for a in PRODUCTS
        }

    def start(self) -> None:
        if _DISABLED or not _WS_IMPORT_OK:
            if not _WS_IMPORT_OK and not _DISABLED:
                logger.warning("spot_ws: `websockets` not installed — staying on REST")
            return
        self._stop = False
        loop = asyncio.get_event_loop()
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._run(), name="spot_ws")
            logger.info("spot_ws: starting (coinbase)")
        if self._sampler_task is None or self._sampler_task.done():
            self._sampler_task = loop.create_task(self._sampler(), name="spot_ws_sampler")

    async def stop(self) -> None:
        self._stop = True
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass
        for t in (self._task, self._sampler_task):
            if t is not None:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        self._task = None
        self._sampler_task = None
        self.connected = False

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run(self) -> None:
        attempt = 0
        while not self._stop:
            try:
                await self._connect_once()
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                attempt += 1
                backoff = min(2.0 ** attempt, _RECONNECT_MAX_SEC)
                backoff *= random.uniform(0.75, 1.25)
                logger.warning(
                    f"spot_ws: disconnected ({type(e).__name__}: {e}); "
                    f"reconnect in {backoff:.0f}s"
                )
                self.connected = False
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise

    async def _connect_once(self) -> None:
        kwargs = dict(ping_interval=10, ping_timeout=10, close_timeout=5,
                      max_size=2 ** 22, ssl=ws_ssl.client_context())
        async with websockets.connect(_URL, **kwargs) as ws:
            self._ws = ws
            self.connected = True
            self.last_msg_t = time.time()
            await ws.send(json.dumps({
                "type": "subscribe", "channel": "heartbeats",
            }))
            await ws.send(json.dumps({
                "type": "subscribe", "channel": "ticker",
                "product_ids": sorted(PRODUCTS.values()),
            }))
            logger.info(f"spot_ws: connected → {_URL}")
            while not self._stop:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                except asyncio.TimeoutError:
                    if time.time() - self.last_msg_t > _SILENT_TIMEOUT_SEC:
                        logger.warning("spot_ws: silent link — forcing reconnect")
                        return
                    continue
                self.last_msg_t = time.time()
                try:
                    self.handle_message(json.loads(raw))
                except Exception as e:
                    logger.debug(f"spot_ws: handle error: {e}")
        self.connected = False
        self._ws = None

    def handle_message(self, m: dict) -> None:
        if not isinstance(m, dict) or m.get("channel") != "ticker":
            return
        now = time.time()
        for ev in m.get("events") or []:
            for tk in (ev or {}).get("tickers") or []:
                asset = _ASSET_BY_PRODUCT.get((tk or {}).get("product_id") or "")
                if not asset:
                    continue
                try:
                    px = float(tk.get("price"))
                except (TypeError, ValueError):
                    continue
                if px > 0:
                    self.prices[asset] = (now, px)

    def _sample_once(self, now: Optional[float] = None) -> None:
        if now is None:
            import kalshi_auth
            now = kalshi_auth.server_now()
        sec = int(now)
        for asset, (ts, px) in list(self.prices.items()):
            if now - ts > _FRESH_SEC:
                continue
            ring = self.samples[asset]
            if ring and ring[-1][0] >= sec:
                continue
            ring.append((sec, px))

    async def _sampler(self) -> None:
        while not self._stop:
            try:
                self._sample_once()
            except Exception as e:
                logger.debug(f"spot_ws: sampler error: {e}")
            await asyncio.sleep(1.0)

    def spot(self, asset: str) -> Optional[float]:
        rec = self.prices.get((asset or "").upper())
        if not rec:
            return None
        ts, px = rec
        if time.time() - ts > _FRESH_SEC:
            return None
        return px

    def fresh_spots(self) -> dict[str, float]:
        if not self.connected:
            return {}
        now = time.time()
        return {
            a: px for a, (ts, px) in self.prices.items()
            if now - ts <= _FRESH_SEC
        }

    def window_partial(
        self, asset: str, close_epoch: float, now: Optional[float] = None,
    ) -> tuple[float, int]:
        ring = self.samples.get((asset or "").upper())
        if not ring:
            return 0.0, 0
        if now is None:
            import kalshi_auth
            now = kalshi_auth.server_now()
        start = close_epoch - _SETTLE_WINDOW_SEC
        end = min(now, close_epoch)
        total, count = 0.0, 0
        for sec, px in ring:
            if start <= sec < end:
                total += px
                count += 1
        return total, count

    def stats(self) -> dict:
        return {
            "enabled": not _DISABLED and _WS_IMPORT_OK,
            "connected": self.connected,
            "assets": sorted(self.fresh_spots()),
            "lastMsgAgeSec": round(max(0.0, time.time() - self.last_msg_t), 1)
            if self.connected else None,
        }


_client = _Client()


def start() -> None:
    _client.start()


async def stop() -> None:
    await _client.stop()


def is_connected() -> bool:
    return _client.connected


def is_running() -> bool:
    return _client.is_running()


def spot(asset: str) -> Optional[float]:
    return _client.spot(asset)


def fresh_spots() -> dict[str, float]:
    return _client.fresh_spots()


def window_partial(asset: str, close_epoch: float, now: Optional[float] = None) -> tuple[float, int]:
    return _client.window_partial(asset, close_epoch, now)


def stats() -> dict:
    return _client.stats()
