from __future__ import annotations

import asyncio
import logging
import math
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger("polymarket")

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"

GAMMA_PAGE_MAX = 100
SWEEP_PAGES = 15
SWEEP_TTL = 90.0
QUOTE_TTL = 8.0
MIN_GAP = 0.15
REQUEST_TIMEOUT = 20.0

_client: Optional[httpx.AsyncClient] = None
_lock: Optional[asyncio.Lock] = None
_last_call = 0.0
_cache: dict[str, tuple[float, Any]] = {}

_geoblocked_at = 0.0
GEOBLOCK_TTL = 1800.0


def geoblocked() -> bool:
    return (time.time() - _geoblocked_at) < GEOBLOCK_TTL


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            headers={"Accept": "application/json", "User-Agent": "KryptTrader/1.0"},
            follow_redirects=True,
        )
    return _client


async def close_clients() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        try:
            await _client.aclose()
        except Exception:
            pass
    _client = None


async def _get(url: str, params: dict | None = None) -> Any:
    global _last_call, _lock, _geoblocked_at
    if _lock is None:
        _lock = asyncio.Lock()

    import kalshi_api
    host = kalshi_api._host_of(url)

    async with _lock:
        gap = MIN_GAP - (time.monotonic() - _last_call)
        if gap > 0:
            await asyncio.sleep(gap)
        t0 = time.monotonic()
        try:
            client = await _get_client()
            resp = await client.get(url, params=params)
        except Exception as e:
            kalshi_api.note_call(host, ok=False, ms=(time.monotonic() - t0) * 1000,
                                 error=f"{type(e).__name__}: {e}")
            logger.info("polymarket GET failed %s: %s", url, e)
            return None
        finally:
            _last_call = time.monotonic()

    kalshi_api.note_call(
        host, ok=resp.status_code < 400, ms=(time.monotonic() - t0) * 1000,
        error="" if resp.status_code < 400 else f"HTTP {resp.status_code}",
    )
    if resp.status_code in (403, 451):
        _geoblocked_at = time.time()
        logger.info("polymarket returned %s — treating as region-blocked",
                    resp.status_code)
        return None
    if resp.status_code >= 400:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def price_cents(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    if f <= 0.0 or f >= 1.0:
        return None
    return round(f * 100.0, 2)


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _text(v: Any) -> Optional[str]:
    if not isinstance(v, str):
        return None
    return v.strip() or None


def _iso(v: Any) -> Optional[str]:
    s = _text(v)
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z")


def market_row(raw: dict) -> Optional[dict]:
    if not isinstance(raw, dict):
        return None
    cid = _text(raw.get("conditionId")) or _text(raw.get("condition_id"))
    if not cid:
        return None

    bid = price_cents(raw.get("bestBid"))
    ask = price_cents(raw.get("bestAsk"))
    spread = round(ask - bid, 2) if (bid is not None and ask is not None) else None
    mid = round((ask + bid) / 2.0, 2) if (bid is not None and ask is not None) else None

    mids = raw.get("outcomePrices")
    if isinstance(mids, str):
        try:
            import json
            mids = json.loads(mids)
        except Exception:
            mids = None
    last = price_cents(mids[0]) if isinstance(mids, list) and mids else None

    vol24 = _num(raw.get("volume24hr"))
    return {
        "conditionId": cid,
        "slug": _text(raw.get("slug")),
        "question": _text(raw.get("question")) or cid,
        "endDate": _iso(raw.get("endDate")) or _iso(raw.get("endDateIso")),
        "yesBid": bid,
        "yesAsk": ask,
        "spreadCents": spread,
        "midCents": mid,
        "lastPrice": last,
        "volume24h": round(vol24, 2) if vol24 is not None else None,
        "liquidityUsd": _num(raw.get("liquidityNum")),
        "acceptingOrders": bool(raw.get("acceptingOrders")),
        "negRisk": bool(raw.get("negRisk")),
        "url": (f"https://polymarket.com/market/{_text(raw.get('slug'))}"
                if _text(raw.get("slug")) else "https://polymarket.com"),
        "observedAt": datetime.now(timezone.utc)
                      .isoformat(timespec="seconds").replace("+00:00", "Z"),
    }


async def sweep(refresh: bool = False) -> dict:
    if not refresh:
        hit = _cache.get("sweep")
        if hit and time.monotonic() - hit[0] < SWEEP_TTL:
            return {**hit[1], "ageSec": round(time.monotonic() - hit[0], 1)}

    rows: list[dict] = []
    truncated = False
    for page in range(SWEEP_PAGES):
        data = await _get(f"{GAMMA_BASE}/markets", params={
            "limit": GAMMA_PAGE_MAX,
            "offset": page * GAMMA_PAGE_MAX,
            "active": "true",
            "closed": "false",
            "order": "volume24hr",
            "ascending": "false",
        })
        if data is None:
            if rows:
                truncated = True
                break
            raise RuntimeError(
                "Polymarket's public API did not answer."
                + (" It looks region-blocked from here." if geoblocked() else "")
            )
        if not isinstance(data, list) or not data:
            break
        for raw in data:
            row = market_row(raw)
            if row:
                rows.append(row)
        if len(data) < GAMMA_PAGE_MAX:
            break
        if page == SWEEP_PAGES - 1:
            truncated = True

    out = {
        "markets": rows,
        "truncated": truncated,
        "fetchedAt": datetime.now(timezone.utc)
                     .isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    _cache["sweep"] = (time.monotonic(), out)
    return {**out, "ageSec": 0.0}


async def market(condition_id: str) -> Optional[dict]:
    cid = (condition_id or "").strip()
    if not cid:
        return None
    key = f"m:{cid}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < QUOTE_TTL:
        return hit[1]
    data = await _get(f"{GAMMA_BASE}/markets", params={"condition_ids": cid})
    row = None
    if isinstance(data, list) and data:
        row = market_row(data[0])
    if row:
        _cache[key] = (time.monotonic(), row)
    return row


def stats() -> dict:
    swept = _cache.get("sweep")
    return {
        "cachedMarkets": len(swept[1]["markets"]) if swept else 0,
        "sweepAgeSec": round(time.monotonic() - swept[0], 1) if swept else None,
        "geoblocked": geoblocked(),
    }
