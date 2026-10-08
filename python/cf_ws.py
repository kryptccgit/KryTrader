"""CF Benchmarks value feed state — the EXACT settlement index, pushed live.

Kalshi's crypto up/down markets settle on a 60-second average of the CF
Benchmarks Real-Time Index, and Kalshi's own WebSocket exposes that index as
the `cfbenchmarks_value` CHANNEL on the standard trade-api socket (see
docs.kalshi.com/asyncapi.yaml). Each ~1/sec tick carries:

  * the raw index frame (the true "spot" Kalshi settles against),
  * `avg_60s_data`: the trailing 60s average, per tick, and
  * `last_60s_windowed_average_15min`: the settlement value being computed
    live, with its `window_size` = "how many settlement prints are already in".

    OBSERVED (2026-07-15, 3 consecutive windows, all 7 assets, identical):
    Kalshi does NOT publish this frame across the whole final minute — it
    first appears only ~15s before the close and its `window_size` reaches
    just ~15 by settlement (ramping +1/sec from ~1 at close-15s), NOT 60.
    So this exact number is live for only the last ~15s of a window; before
    that, `settle_partial` returns (0,0) and consumers fall through to the
    spot_ws (Coinbase) sampler, which covers the fuller final minute. Treat
    cf_ws as a last-~15s sharpener over the proxy, not a full-minute source.
    (Kalshi still SETTLES on the 60s average — we just don't see all 60 of
    its prints on this channel.)

kalshi_ws owns the connection and subscription (set_cf_enabled) and forwards
`cfbenchmarks_value` frames here; this module just parses and holds state for
the 15m model. Freshness is timestamp-gated per record, so a dead socket
simply ages the data out and consumers fall through to the next source
(spot_ws → REST). It IS the exact settlement number in the last ~15s — but
only there; the Coinbase sampler carries the rest of the final minute.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

logger = logging.getLogger("cf_ws")

_FRESH_SEC = 10.0
_SETTLE_FRESH_SEC = 6.0

_INDEX_RE = re.compile(r"^([A-Z]+)USD_RTI$")
_SPECIAL_INDEX = {"BRTI": "BTC"}


def _index_to_asset(index_id: str) -> Optional[str]:
    if not index_id:
        return None
    if index_id in _SPECIAL_INDEX:
        return _SPECIAL_INDEX[index_id]
    m = _INDEX_RE.match(index_id)
    return m.group(1) if m else None


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f > 0 else None


class _State:
    def __init__(self) -> None:
        self.values: dict[str, tuple[float, float]] = {}
        self.settle: dict[str, tuple[float, float, int, float]] = {}


    def handle_message(self, m: dict) -> None:
        if not isinstance(m, dict) or m.get("type") != "cfbenchmarks_value":
            return
        msg = m.get("msg") or {}
        asset = _index_to_asset(str(msg.get("index_id") or ""))
        if not asset:
            return
        now = time.time()

        val: Optional[float] = None
        data = msg.get("data")
        if isinstance(data, str):
            try:
                frame = json.loads(data)
                val = _f((frame or {}).get("value"))
            except Exception:
                val = None
        elif isinstance(data, dict):
            val = _f(data.get("value"))
        if val is None:
            val = _f(((msg.get("avg_60s_data") or {}).get("value")))
        if val is not None:
            self.values[asset] = (now, val)

        sw = msg.get("last_60s_windowed_average_15min")
        if isinstance(sw, dict):
            avg = _f(sw.get("value"))
            try:
                n = int(sw.get("window_size") or 0)
            except (TypeError, ValueError):
                n = 0
            try:
                end_ms = float(sw.get("window_end_ts_exclusive") or 0)
            except (TypeError, ValueError):
                end_ms = 0.0
            if avg is not None and n > 0:
                self.settle[asset] = (now, avg, n, end_ms)


    def spot(self, asset: str) -> Optional[float]:
        rec = self.values.get((asset or "").upper())
        if not rec:
            return None
        ts, v = rec
        if time.time() - ts > _FRESH_SEC:
            return None
        return v

    def fresh_spots(self) -> dict[str, float]:
        now = time.time()
        return {
            a: v for a, (ts, v) in self.values.items() if now - ts <= _FRESH_SEC
        }

    def settle_partial(self, asset: str, close_epoch: float) -> tuple[float, int]:
        """(sum, count) of the settlement average Kalshi has ALREADY computed
        for the window closing at `close_epoch` — i.e. avg × window_size from
        the feed's final-minute message. (0, 0) when not in the final minute,
        the feed is cold/stale, or the message belongs to a different window
        (its end timestamp must fall inside this window's final minute)."""
        rec = self.settle.get((asset or "").upper())
        if not rec:
            return 0.0, 0
        ts, avg, n, end_ms = rec
        if time.time() - ts > _SETTLE_FRESH_SEC:
            return 0.0, 0
        end_s = end_ms / 1000.0
        if not (close_epoch - 60.0 <= end_s <= close_epoch + 2.0):
            return 0.0, 0
        return avg * n, n

    def stats(self) -> dict:
        return {
            "assets": sorted(self.fresh_spots()),
            "settleAssets": sorted(self.settle),
        }


_client = _State()


def handle_message(m: dict) -> None:
    _client.handle_message(m)


def spot(asset: str) -> Optional[float]:
    return _client.spot(asset)


def fresh_spots() -> dict[str, float]:
    return _client.fresh_spots()


def settle_partial(asset: str, close_epoch: float) -> tuple[float, int]:
    return _client.settle_partial(asset, close_epoch)


def stats() -> dict:
    return _client.stats()
