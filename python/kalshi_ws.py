from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from collections import deque
from typing import Awaitable, Callable, Optional

import cf_ws
import kalshi_auth
import ws_ssl

logger = logging.getLogger("kalshi_ws")

try:
    import websockets
    _WS_IMPORT_OK = True
except Exception:
    websockets = None
    _WS_IMPORT_OK = False

_WS_BASES = {
    "demo": "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
    "production": "wss://external-api-ws.kalshi.com/trade-api/ws/v2",
}
_WS_PATH = "/trade-api/ws/v2"

_DISABLED = os.environ.get("KRYPT_KALSHI_WS", "1").strip().lower() in (
    "0", "off", "false", "no",
)

_ACCOUNT_CHANNELS = ("trade", "fill", "market_positions")
_CF_CHANNEL = "cfbenchmarks_value"
_MULTI_CHANNELS = ("ticker", "market_lifecycle_v2")

_TRADE_BUF_MAX = 8000
_RECONNECT_MAX_SEC = 60.0
_SILENT_TIMEOUT_SEC = 30.0
_TRADE_STALE_SEC = 120.0
_ACCOUNT_RESUB_THROTTLE_SEC = 10.0
_ACCOUNT_RESUB_MAX_TRIES = 4

FillCb = Callable[[dict], Optional[Awaitable]]
LifecycleCb = Callable[[dict], Optional[Awaitable]]
TradeCb = Callable[[dict], None]

_RECONCILE_MIN_INTERVAL_SEC = 1.0


def _fp_or_none(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _cents(price_dollars) -> Optional[float]:
    try:
        return round(float(price_dollars) * 100, 1)
    except (TypeError, ValueError):
        return None


def taker_outcome_side(t: dict) -> str:
    """'yes' / 'no' for a public trade's taker, or '' when Kalshi didn't say.

    `taker_side` was deprecated on 2026-05-06 ("not removed before May 28,
    2026" -- that date has passed). Its replacements carry the same bit:
    taker_outcome_side yes|no, taker_book_side bid|ask (bid == yes). Without
    a direction the scanner skips the trade, so dropping the old field would
    blind whale detection on every path that read it.
    """
    v = str(t.get("taker_outcome_side") or "").lower()
    if v in ("yes", "no"):
        return v
    b = str(t.get("taker_book_side") or "").lower()
    if b in ("bid", "ask"):
        return "yes" if b == "bid" else "no"
    v = str(t.get("taker_side") or "").lower()
    return v if v in ("yes", "no") else ""


def _fp(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


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
        self.last_trade_msg_t: float = 0.0

        self.want_orderbook: set[str] = set()
        self.want_ticker: set[str] = set()
        self.want_lifecycle: set[str] = set()
        self._ob_sids: dict[str, int] = {}
        self._multi_sids: dict[str, int] = {}
        self._multi_have: dict[str, set[str]] = {c: set() for c in _MULTI_CHANNELS}
        self._account_subbed: set[str] = set()
        self._account_attempt: dict[str, float] = {}
        self._account_tries: dict[str, int] = {}
        self._inflight: dict[int, tuple] = {}

        self.books: dict[str, dict[str, dict[int, float]]] = {}
        self._book_seq: dict[str, int] = {}
        self._book_valid: dict[str, bool] = {}
        self._resnap: set[str] = set()
        self.quotes: dict[str, dict] = {}
        self.trades: deque = deque(maxlen=_TRADE_BUF_MAX)

        self.on_fill: Optional[FillCb] = None
        self.on_lifecycle: Optional[LifecycleCb] = None
        self.on_trade: Optional[TradeCb] = None
        self.want_cf: bool = False

    def start(self, env: str, *, on_fill=None, on_lifecycle=None, on_trade=None) -> None:
        if _DISABLED or not _WS_IMPORT_OK:
            if not _WS_IMPORT_OK and not _DISABLED:
                logger.warning("kalshi_ws: `websockets` not installed — staying on REST")
            return
        self.env = env if env in _WS_BASES else "production"
        self.on_fill = on_fill
        self.on_lifecycle = on_lifecycle
        self.on_trade = on_trade
        self._stop = False
        loop = asyncio.get_event_loop()
        self._loop_time = loop.time
        if self._task is None or self._task.done():
            self._task = loop.create_task(self._run(), name="kalshi_ws")
            logger.info(f"kalshi_ws: starting ({self.env})")

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

    def set_env(self, env: str) -> None:
        env = env if env in _WS_BASES else "production"
        if env != self.env:
            self.env = env
            self._gen += 1
            logger.info(f"kalshi_ws: env → {env}, reconnecting")

    def set_cf_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self.want_cf:
            return
        self.want_cf = enabled
        logger.info(f"kalshi_ws: cfbenchmarks_value → {'on' if enabled else 'off'}")
        if not enabled and self.connected:
            self._gen += 1
        elif enabled:
            self._account_tries.pop(_CF_CHANNEL, None)
            self._account_attempt.pop(_CF_CHANNEL, None)

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
                    f"kalshi_ws: disconnected ({type(e).__name__}: {e}); "
                    f"reconnect in {backoff:.0f}s"
                )
                self.connected = False
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    raise

    async def _connect_once(self, gen: int) -> None:
        if not kalshi_auth.credentials_present(self.env):
            await asyncio.sleep(5)
            return
        url = os.environ.get("KRYPT_KALSHI_WS_URL") or _WS_BASES[self.env]
        headers = kalshi_auth.sign_headers("GET", _WS_PATH)
        kwargs = dict(ping_interval=10, ping_timeout=10, close_timeout=5,
                      max_size=2 ** 23, ssl=ws_ssl.client_context())
        try:
            conn = websockets.connect(url, additional_headers=headers, **kwargs)
        except TypeError:
            conn = websockets.connect(url, extra_headers=headers, **kwargs)

        try:
            async with conn as ws:
                self._ws = ws
                self.connected = True
                self.last_msg_t = self._loop_time()
                self._reset_sub_state()
                logger.info(f"kalshi_ws: connected → {url}")
                await self._subscribe_account(ws)
                await self._reconcile(ws)
                last_reconcile = self._loop_time()
                while not self._stop and gen == self._gen:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        await self._reconcile(ws)
                        last_reconcile = self._loop_time()
                        if self._loop_time() - self.last_msg_t > _SILENT_TIMEOUT_SEC:
                            logger.warning("kalshi_ws: silent link — forcing reconnect")
                            return
                        continue
                    self.last_msg_t = self._loop_time()
                    try:
                        self._handle(json.loads(raw))
                    except Exception as e:
                        logger.debug(f"kalshi_ws: handle error: {e}")
                    if self._loop_time() - last_reconcile >= _RECONCILE_MIN_INTERVAL_SEC:
                        await self._reconcile(ws)
                        last_reconcile = self._loop_time()
        finally:
            self.connected = False
            self._ws = None

    def _reset_sub_state(self) -> None:
        self._ob_sids.clear()
        self._multi_sids.clear()
        for c in _MULTI_CHANNELS:
            self._multi_have[c] = set()
        self._account_subbed.clear()
        self._account_attempt.clear()
        self._account_tries.clear()
        self._inflight.clear()
        for t in list(self._book_valid):
            self._book_valid[t] = False
        self._resnap.clear()
        for t in [q for q in self.quotes if q not in self.want_ticker]:
            self.quotes.pop(t, None)
        self.trades.clear()
        self.last_trade_msg_t = 0.0

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    async def _send(self, ws, obj: dict) -> None:
        await ws.send(json.dumps(obj))

    async def _subscribe_account(self, ws) -> None:
        now = self._loop_time()
        chans = _ACCOUNT_CHANNELS + ((_CF_CHANNEL,) if self.want_cf else ())
        for ch in chans:
            if ch in self._account_subbed:
                continue
            last = self._account_attempt.get(ch)
            if last is not None and (now - last) < _ACCOUNT_RESUB_THROTTLE_SEC:
                continue
            if self._account_tries.get(ch, 0) >= _ACCOUNT_RESUB_MAX_TRIES:
                continue
            for cid in [c for c, kk in self._inflight.items() if kk == ("account", ch)]:
                self._inflight.pop(cid, None)
            cid = self._next_id()
            self._inflight[cid] = ("account", ch)
            self._account_attempt[ch] = now
            self._account_tries[ch] = self._account_tries.get(ch, 0) + 1
            params: dict = {"channels": [ch]}
            if ch == _CF_CHANNEL:
                params["index_ids"] = ["all"]
            await self._send(ws, {"id": cid, "cmd": "subscribe",
                                  "params": params})

    async def _reconcile(self, ws) -> None:
        await self._subscribe_account(ws)
        for t in self.want_orderbook - set(self._ob_sids):
            cid = self._next_id()
            self._inflight[cid] = ("ob", t)
            await self._send(ws, {"id": cid, "cmd": "subscribe",
                                  "params": {"channels": ["orderbook_delta"],
                                             "market_ticker": t}})
            self._ob_sids[t] = -1
        for t in set(self._ob_sids) - self.want_orderbook:
            sid = self._ob_sids.pop(t)
            self._drop_book(t)
            if sid and sid > 0:
                cid = self._next_id()
                await self._send(ws, {"id": cid, "cmd": "unsubscribe",
                                      "params": {"sids": [sid]}})
        if self._resnap:
            for t in list(self._resnap):
                sid = self._ob_sids.get(t)
                if sid and sid > 0:
                    cid = self._next_id()
                    await self._send(ws, {"id": cid, "cmd": "update_subscription",
                                          "params": {"sids": [sid],
                                                     "market_tickers": [t],
                                                     "action": "get_snapshot"}})
                    self._resnap.discard(t)
        await self._reconcile_multi(ws, "ticker", self.want_ticker)
        await self._reconcile_multi(ws, "market_lifecycle_v2", self.want_lifecycle)

    async def _reconcile_multi(self, ws, channel: str, want: set[str]) -> None:
        have = self._multi_have[channel]
        sid = self._multi_sids.get(channel)
        if not want:
            if sid:
                cid = self._next_id()
                await self._send(ws, {"id": cid, "cmd": "unsubscribe",
                                      "params": {"sids": [sid]}})
                self._multi_sids.pop(channel, None)
                self._multi_have[channel] = set()
            return
        if sid is None:
            cid = self._next_id()
            self._inflight[cid] = ("multi", channel)
            await self._send(ws, {"id": cid, "cmd": "subscribe",
                                  "params": {"channels": [channel],
                                             "market_tickers": sorted(want)}})
            self._multi_have[channel] = set(want)
            return
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
            self._multi_have[channel] = set(want)

    def _handle(self, m: dict) -> None:
        t = m.get("type")
        if t == "subscribed":
            self._on_subscribed(m)
        elif t == "orderbook_snapshot":
            self._on_snapshot(m)
        elif t == "orderbook_delta":
            self._on_delta(m)
        elif t == "ticker":
            self._on_ticker(m)
        elif t == "trade":
            self._on_trade(m)
        elif t in ("fill", "user_order"):
            self._on_fill(m)
        elif t == "market_lifecycle_v2":
            self._on_lifecycle(m)
        elif t == "cfbenchmarks_value":
            cf_ws.handle_message(m)
        elif t == "cfbenchmarks_value_indexlist":
            pass
        elif t == "market_position":
            pass
        elif t == "error":
            msg = m.get("msg") or {}
            logger.debug(f"kalshi_ws: server error {msg.get('code')}: {msg.get('msg')}")
            cid = m.get("id")
            kind_key = self._inflight.pop(cid, None) if cid is not None else None
            if kind_key:
                kind, key = kind_key
                if kind == "ob" and self._ob_sids.get(key) == -1:
                    self._ob_sids.pop(key, None)
                elif kind == "multi":
                    self._multi_have[key] = set()

    def _on_subscribed(self, m: dict) -> None:
        cid = m.get("id")
        kind_key = self._inflight.pop(cid, None) if cid is not None else None
        if not kind_key:
            return
        kind, key = kind_key
        if kind == "account":
            self._account_subbed.add(key)
            return
        sid = (m.get("msg") or {}).get("sid")
        if sid is None:
            return
        if kind == "ob":
            self._ob_sids[key] = sid
        elif kind == "multi":
            self._multi_sids[key] = sid

    def _drop_book(self, t: str) -> None:
        self.books.pop(t, None)
        self._book_seq.pop(t, None)
        self._book_valid.pop(t, None)
        self.quotes.pop(t, None)

    def _on_snapshot(self, m: dict) -> None:
        msg = m.get("msg") or {}
        t = msg.get("market_ticker")
        if not t:
            return
        book = {"yes": {}, "no": {}}
        for side, key in (("yes", "yes_dollars_fp"), ("no", "no_dollars_fp")):
            for lvl in msg.get(key) or []:
                try:
                    c = _cents(lvl[0])
                    if c is not None:
                        book[side][c] = _fp(lvl[1])
                except (TypeError, IndexError):
                    continue
        self.books[t] = book
        self._book_seq[t] = int(m.get("seq") or 0)
        self._book_valid[t] = True

    def _on_delta(self, m: dict) -> None:
        msg = m.get("msg") or {}
        t = msg.get("market_ticker")
        if not t or t not in self.books:
            return
        seq = int(m.get("seq") or 0)
        prev = self._book_seq.get(t, 0)
        if seq <= prev:
            return
        if seq != prev + 1:
            self._book_valid[t] = False
            self._resnap.add(t)
            logger.debug(f"kalshi_ws: seq gap on {t} ({prev}→{seq}); re-snapshotting")
            return
        side = msg.get("side")
        c = _cents(msg.get("price_dollars"))
        if side in ("yes", "no") and c is not None:
            levels = self.books[t][side]
            levels[c] = levels.get(c, 0.0) + _fp(msg.get("delta_fp"))
            if levels[c] <= 0:
                levels.pop(c, None)
        self._book_seq[t] = seq

    def _on_ticker(self, m: dict) -> None:
        msg = m.get("msg") or {}
        t = msg.get("market_ticker")
        if not t:
            return
        self.quotes[t] = {
            "yes_bid_cents": _cents(msg.get("yes_bid_dollars")),
            "yes_ask_cents": _cents(msg.get("yes_ask_dollars")),
            "last_cents": _cents(msg.get("price_dollars")),
            "volume": _fp_or_none(msg.get("volume_fp")),
            "open_interest": _fp_or_none(msg.get("open_interest_fp")),
            "ts_ms": msg.get("ts_ms") or 0,
        }

    def _on_trade(self, m: dict) -> None:
        msg = m.get("msg") or {}
        t = msg.get("market_ticker")
        if not t:
            return
        self.last_trade_msg_t = self._loop_time()
        trade = {
            "trade_id": msg.get("trade_id", ""),
            "ticker": t,
            # Absent stays absent: a "0" default here read downstream as a
            # real zero-size or zero-price trade.
            "count_fp": msg.get("count_fp"),
            "yes_price_dollars": msg.get("yes_price_dollars"),
            "no_price_dollars": msg.get("no_price_dollars"),
            "taker_side": taker_outcome_side(msg),
            "is_block_trade": bool(msg.get("is_block_trade")),
            "created_time": msg.get("ts_ms") or msg.get("ts") or "",
            "observed_ms": int(time.time() * 1000),
        }
        self.trades.append(trade)
        if self.on_trade is not None:
            try:
                self.on_trade(trade)
            except Exception as e:
                logger.debug(f"kalshi_ws: on_trade cb error: {e}")

    def _on_fill(self, m: dict) -> None:
        if self.on_fill is None:
            return
        try:
            res = self.on_fill(m.get("msg") or {})
            if asyncio.iscoroutine(res):
                asyncio.create_task(res)
        except Exception as e:
            logger.debug(f"kalshi_ws: on_fill cb error: {e}")

    def _on_lifecycle(self, m: dict) -> None:
        if self.on_lifecycle is None:
            return
        try:
            res = self.on_lifecycle(m.get("msg") or {})
            if asyncio.iscoroutine(res):
                asyncio.create_task(res)
        except Exception as e:
            logger.debug(f"kalshi_ws: on_lifecycle cb error: {e}")

    def set_orderbook_markets(self, tickers) -> None:
        self.want_orderbook = {t for t in tickers if t}

    def set_ticker_markets(self, tickers) -> None:
        self.want_ticker = {t for t in tickers if t}

    def add_ticker_markets(self, tickers) -> None:
        self.want_ticker |= {t for t in tickers if t}

    def add_orderbook_markets(self, tickers) -> None:
        self.want_orderbook |= {t for t in tickers if t}

    def set_lifecycle_markets(self, tickers) -> None:
        self.want_lifecycle = {t for t in tickers if t}

    def orderbook(self, ticker: str) -> Optional[dict]:
        if not self.connected or not self._book_valid.get(ticker):
            return None
        b = self.books.get(ticker)
        if not b:
            return None
        return {
            "yes": [[c, s] for c, s in b["yes"].items()],
            "no": [[c, s] for c, s in b["no"].items()],
        }

    def best_bid_cents(self, ticker: str, side: str) -> Optional[float]:
        if not self.connected or not self._book_valid.get(ticker):
            return None
        b = self.books.get(ticker)
        if not b or side not in ("yes", "no") or not b[side]:
            return None
        return max(b[side].keys())

    def ticker_quote(self, ticker: str) -> Optional[dict]:
        return self.quotes.get(ticker) if self.connected else None

    def recent_trades(self, limit: int = 1000) -> Optional[list]:
        if not self.connected or not self.trades:
            return None
        if self._loop_time() - self.last_trade_msg_t > _TRADE_STALE_SEC:
            return None
        out = list(self.trades)[-limit:]
        out.reverse()
        return out

    def stats(self) -> dict:
        return {
            "enabled": not _DISABLED and _WS_IMPORT_OK,
            "connected": self.connected,
            "env": self.env,
            "books": sum(1 for v in self._book_valid.values() if v),
            "orderbookSubs": len(self._ob_sids),
            "tickerCache": len(self.quotes),
            "tradeBuf": len(self.trades),
            "lastMsgAgeSec": round(max(0.0, self._loop_time() - self.last_msg_t), 1)
            if self.connected else None,
        }


_client = _Client()

def start(env: str, *, on_fill=None, on_lifecycle=None, on_trade=None) -> None:
    _client.start(env, on_fill=on_fill, on_lifecycle=on_lifecycle, on_trade=on_trade)


async def stop() -> None:
    await _client.stop()


def set_env(env: str) -> None:
    _client.set_env(env)


def set_cf_enabled(enabled: bool) -> None:
    _client.set_cf_enabled(enabled)


def is_connected() -> bool:
    return _client.connected


def set_orderbook_markets(tickers) -> None:
    _client.set_orderbook_markets(tickers)


def set_ticker_markets(tickers) -> None:
    _client.set_ticker_markets(tickers)


def add_ticker_markets(tickers) -> None:
    _client.add_ticker_markets(tickers)


def add_orderbook_markets(tickers) -> None:
    _client.add_orderbook_markets(tickers)


def set_lifecycle_markets(tickers) -> None:
    _client.set_lifecycle_markets(tickers)


def orderbook(ticker: str) -> Optional[dict]:
    return _client.orderbook(ticker)


def best_bid_cents(ticker: str, side: str) -> Optional[float]:
    return _client.best_bid_cents(ticker, side)


def ticker_quote(ticker: str) -> Optional[dict]:
    return _client.ticker_quote(ticker)


def recent_trades(limit: int = 1000) -> Optional[list]:
    return _client.recent_trades(limit)


def stats() -> dict:
    return _client.stats()
