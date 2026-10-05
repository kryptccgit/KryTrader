from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from typing import Callable, Optional

import kalshi_auth
import ws_ssl
from kalshi_perps_api import usd_micro, cc

logger = logging.getLogger("perps_ws")

try:
    import websockets
    _WS_IMPORT_OK = True
except Exception:
    websockets = None
    _WS_IMPORT_OK = False

_WS_BASES = {
    "demo": "wss://external-api-margin-ws.demo.kalshi.co/trade-api/ws/v2/margin",
    "production": "wss://external-api-margin-ws.kalshi.com/trade-api/ws/v2/margin",
}
_WS_PATH = "/trade-api/ws/v2/margin"
_WS_PATH_FALLBACK = "/trade-api/ws/v2"

_DISABLED = os.environ.get("KRYPT_PERPS_WS", "1").strip().lower() in (
    "0", "off", "false", "no",
)

_TICK_BUF_MAX = 30_000
_TRADE_BUF_MAX = 30_000
_RECONNECT_MAX_SEC = 60.0
_SILENT_TIMEOUT_SEC = 30.0
_RECONCILE_MIN_INTERVAL_SEC = 1.0

TickerCb = Callable[[dict], None]


def _mark(v) -> tuple[Optional[int], Optional[int]]:
    if isinstance(v, dict):
        return usd_micro(v.get("price")), v.get("ts_ms")
    return usd_micro(v), None


def _fr(v) -> Optional[float]:
    if isinstance(v, dict):
        v = v.get("rate", v.get("funding_rate"))
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class _Client:
    def __init__(self) -> None:
        self.env: str = "production"
        self.connected: bool = False
        self._stop: bool = False
        self._task: Optional[asyncio.Task] = None
        self._ws = None
        self._gen: int = 0
        self._id: int = 0
        self._loop_time: Callable[[], float] = lambda: 0.0
        self.last_msg_t: float = 0.0
        self._path_ok: Optional[str] = None

        self.want_symbols: set[str] = set()
        self._chan_sids: dict[str, int] = {}
        self._chan_have: dict[str, set[str]] = {"ticker": set(), "trade": set()}
        self._inflight: dict[int, tuple] = {}

        self._tick_buf: list[dict] = []
        self._trade_buf: list[dict] = []
        self.dropped_ticks: int = 0
        self.dropped_trades: int = 0
        self.quotes: dict[str, dict] = {}

        self.on_ticker: Optional[TickerCb] = None

    def start(self, env: str, *, on_ticker: Optional[TickerCb] = None) -> None:
        if _DISABLED or not _WS_IMPORT_OK:
            if not _WS_IMPORT_OK and not _DISABLED:
                logger.warning("perps_ws: `websockets` not installed — REST poll only")
            return
        self.env = env if env in _WS_BASES else "production"
        self.on_ticker = on_ticker
        self._stop = False
        loop = asyncio.get_event_loop()
        self._loop_time = loop.time
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._run(), name="perps_ws")
            logger.info(f"perps_ws: starting ({self.env})")

    async def stop(self) -> None:
        self._stop = True
        self._gen += 1
        await self._close_ws()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        self.connected = False

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done() and not self._stop

    def set_env(self, env: str) -> None:
        env = env if env in _WS_BASES else "production"
        if env != self.env:
            self.env = env
            self._gen += 1
            logger.info(f"perps_ws: env → {env}, reconnecting")

    def set_symbols(self, tickers) -> None:
        self.want_symbols = {t for t in tickers if t}

    async def _close_ws(self) -> None:
        ws = self._ws
        self._ws = None
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    async def _run(self) -> None:
        attempt = 0
        while not self._stop:
            gen = self._gen
            try:
                await self._connect_once(gen)
                attempt = 0
            except asyncio.CancelledError:
                raise
            except Exception as e:
                attempt += 1
                backoff = min(2.0 ** attempt, _RECONNECT_MAX_SEC)
                backoff *= random.uniform(0.75, 1.25)
                logger.warning(
                    f"perps_ws: disconnected ({type(e).__name__}: {e}); "
                    f"reconnect in {backoff:.0f}s"
                )
                self.connected = False
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise

    def _upgrade_status(self, e: Exception) -> int | None:
        sc = getattr(e, "status_code", None)
        if sc is None:
            sc = getattr(getattr(e, "response", None), "status_code", None)
        return sc

    async def _connect_once(self, gen: int) -> None:
        if not kalshi_auth.credentials_present(self.env):
            await asyncio.sleep(5)
            return
        url = os.environ.get("KRYPT_PERPS_WS_URL") or _WS_BASES[self.env]
        paths = [self._path_ok] if self._path_ok else [_WS_PATH, _WS_PATH_FALLBACK]
        kwargs = dict(ping_interval=10, ping_timeout=10, close_timeout=5,
                      max_size=2 ** 23, ssl=ws_ssl.client_context())
        conn = None
        last_401: Optional[Exception] = None
        for signed_path in paths:
            headers = kalshi_auth.sign_headers("GET", signed_path)
            try:
                conn = websockets.connect(url, additional_headers=headers, **kwargs)
            except TypeError:
                conn = websockets.connect(url, extra_headers=headers, **kwargs)
            try:
                ws = await conn
            except Exception as e:
                if self._upgrade_status(e) == 401 and signed_path != paths[-1]:
                    logger.info(
                        f"perps_ws: 401 signing {signed_path}; retrying with fallback path"
                    )
                    last_401 = e
                    continue
                raise
            if self._path_ok != signed_path:
                self._path_ok = signed_path
                logger.info(f"perps_ws: signed path {signed_path} accepted")
            break
        else:
            raise last_401 or RuntimeError("perps_ws: no signed path accepted")

        try:
            self._ws = ws
            self.connected = True
            self.last_msg_t = self._loop_time()
            self._reset_sub_state()
            logger.info(f"perps_ws: connected → {url}")
            await self._reconcile(ws)
            last_reconcile = self._loop_time()
            while not self._stop and gen == self._gen:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    await self._reconcile(ws)
                    last_reconcile = self._loop_time()
                    if self._loop_time() - self.last_msg_t > _SILENT_TIMEOUT_SEC:
                        logger.warning("perps_ws: silent link — forcing reconnect")
                        return
                    continue
                self.last_msg_t = self._loop_time()
                try:
                    self._handle(json.loads(raw))
                except Exception as e:
                    logger.debug(f"perps_ws: handle error: {e}")
                if self._loop_time() - last_reconcile >= _RECONCILE_MIN_INTERVAL_SEC:
                    await self._reconcile(ws)
                    last_reconcile = self._loop_time()
        finally:
            self.connected = False
            self._ws = None
            try:
                await ws.close()
            except Exception:
                pass

    def _reset_sub_state(self) -> None:
        self._chan_sids.clear()
        self._chan_have = {"ticker": set(), "trade": set()}
        self._inflight.clear()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    async def _send(self, ws, obj: dict) -> None:
        await ws.send(json.dumps(obj))

    async def _reconcile(self, ws) -> None:
        for ch in ("ticker", "trade"):
            want = self.want_symbols
            sid = self._chan_sids.get(ch)
            have = self._chan_have[ch]
            if not want:
                if sid and sid > 0:
                    cid = self._next_id()
                    await self._send(ws, {"id": cid, "cmd": "unsubscribe",
                                          "params": {"sids": [sid]}})
                    self._chan_sids.pop(ch, None)
                    self._chan_have[ch] = set()
                continue
            if sid is None:
                cid = self._next_id()
                self._inflight[cid] = ("chan", ch)
                self._chan_sids[ch] = -1
                await self._send(ws, {"id": cid, "cmd": "subscribe",
                                      "params": {"channels": [ch],
                                                 "market_tickers": sorted(want)}})
                self._chan_have[ch] = set(want)
                continue
            if sid == -1:
                continue
            add = sorted(want - have)
            rem = sorted(have - want)
            if add:
                cid = self._next_id()
                await self._send(ws, {"id": cid, "cmd": "update_subscription",
                                      "params": {"sids": [sid], "market_tickers": add,
                                                 "action": "add_markets"}})
            if rem:
                cid = self._next_id()
                await self._send(ws, {"id": cid, "cmd": "update_subscription",
                                      "params": {"sids": [sid], "market_tickers": rem,
                                                 "action": "delete_markets"}})
            if add or rem:
                self._chan_have[ch] = set(want)

    def _handle(self, m: dict) -> None:
        t = m.get("type")
        if t == "ticker":
            self._on_ticker(m)
        elif t == "trade":
            self._on_trade(m)
        elif t == "subscribed":
            self._on_subscribed(m)
        elif t == "error":
            msg = m.get("msg") or {}
            logger.debug(f"perps_ws: server error {msg.get('code')}: {msg.get('msg')}")
            cid = m.get("id")
            kind_key = self._inflight.pop(cid, None) if cid is not None else None
            if kind_key:
                kind, key = kind_key
                if kind == "chan" and self._chan_sids.get(key) == -1:
                    self._chan_sids.pop(key, None)
                    self._chan_have[key] = set()

    def _on_subscribed(self, m: dict) -> None:
        cid = m.get("id")
        kind_key = self._inflight.pop(cid, None) if cid is not None else None
        if not kind_key:
            return
        kind, key = kind_key
        sid = (m.get("msg") or {}).get("sid")
        if kind == "chan" and sid is not None:
            self._chan_sids[key] = sid

    def _buf_append(self, buf: list, row: dict, cap: int, drop_attr: str) -> None:
        if len(buf) >= cap:
            del buf[: max(1, cap // 10)]
            setattr(self, drop_attr, getattr(self, drop_attr) + max(1, cap // 10))
        buf.append(row)

    def _on_ticker(self, m: dict) -> None:
        msg = m.get("msg") or {}
        t = msg.get("market_ticker")
        if not t:
            return
        ref_micro, ref_ts = _mark(msg.get("reference_price"))
        settle_micro, _ = _mark(msg.get("settlement_mark_price"))
        liq_micro, _ = _mark(msg.get("liquidation_mark_price"))
        fr = msg.get("funding_rate")
        next_funding_ms = fr.get("next_funding_time_ms") if isinstance(fr, dict) else None
        row = {
            "ticker": t,
            "ts_ms": msg.get("ts_ms") or 0,
            "recv_ms": int(time.time() * 1000),
            "last_usd_micro": usd_micro(msg.get("price")),
            "bid_usd_micro": usd_micro(msg.get("bid")),
            "ask_usd_micro": usd_micro(msg.get("ask")),
            "bid_size_cc": cc(msg.get("bid_size_fp")),
            "ask_size_cc": cc(msg.get("ask_size_fp")),
            "volume_24h_cc": cc(msg.get("volume_24h")),
            "oi_cc": cc(msg.get("open_interest")),
            "ref_usd_micro": ref_micro,
            "ref_ts_ms": ref_ts,
            "settle_mark_usd_micro": settle_micro,
            "liq_mark_usd_micro": liq_micro,
            "funding_rate": _fr(fr),
            "next_funding_ms": next_funding_ms,
            "src": "ws",
            "kalshi_env": self.env,
        }
        self._buf_append(self._tick_buf, row, _TICK_BUF_MAX, "dropped_ticks")
        self.quotes[t] = row
        if self.on_ticker is not None:
            try:
                self.on_ticker(row)
            except Exception as e:
                logger.debug(f"perps_ws: on_ticker cb error: {e}")

    def _on_trade(self, m: dict) -> None:
        msg = m.get("msg") or {}
        t = msg.get("market_ticker")
        if not t:
            return
        price = usd_micro(msg.get("price"))
        count = cc(msg.get("count"))
        if price is None or count is None:
            return
        self._buf_append(self._trade_buf, {
            "trade_id": str(msg.get("trade_id") or ""),
            "ticker": t,
            "ts_ms": msg.get("ts_ms") or 0,
            "price_usd_micro": price,
            "count_cc": count,
            "taker_side": msg.get("taker_side", ""),
            "kalshi_env": self.env,
        }, _TRADE_BUF_MAX, "dropped_trades")

    def drain_ticks(self) -> list[dict]:
        out, self._tick_buf = self._tick_buf, []
        return out

    def drain_trades(self) -> list[dict]:
        out, self._trade_buf = self._trade_buf, []
        return out

    def quote(self, ticker: str) -> Optional[dict]:
        return self.quotes.get(ticker) if self.connected else None

    def stats(self) -> dict:
        return {
            "enabled": not _DISABLED and _WS_IMPORT_OK,
            "connected": self.connected,
            "env": self.env,
            "symbols": sorted(self.want_symbols),
            "bufferedTicks": len(self._tick_buf),
            "bufferedTrades": len(self._trade_buf),
            "droppedTicks": self.dropped_ticks,
            "droppedTrades": self.dropped_trades,
            "lastMsgAgeSec": round(max(0.0, self._loop_time() - self.last_msg_t), 1)
            if self.connected else None,
        }


_client = _Client()


def start(env: str, *, on_ticker: Optional[TickerCb] = None) -> None:
    _client.start(env, on_ticker=on_ticker)


async def stop() -> None:
    await _client.stop()


def is_running() -> bool:
    return _client.is_running()


def set_env(env: str) -> None:
    _client.set_env(env)


def is_connected() -> bool:
    return _client.connected


def set_symbols(tickers) -> None:
    _client.set_symbols(tickers)


def drain_ticks() -> list[dict]:
    return _client.drain_ticks()


def drain_trades() -> list[dict]:
    return _client.drain_trades()


def quote(ticker: str) -> Optional[dict]:
    return _client.quote(ticker)


def stats() -> dict:
    return _client.stats()
