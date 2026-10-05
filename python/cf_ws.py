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
