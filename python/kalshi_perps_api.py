"""Kalshi perpetual-futures ("margin") REST client.

Sibling of kalshi_api.py for the perps API (https://docs.kalshi.com/margin).
Same RSA-PSS signing (kalshi_auth.sign_headers), same retry/429/clock-resync
ladder, but a DIFFERENT host pair and price convention:

  * Host: external-api.kalshi.com — NOT the event-contract host. Paths
    live under /trade-api/v2/margin/*.
  * Prices are FIXED-POINT DOLLAR STRINGS up to 4dp on the wire (tick 0.0001,
    responses may carry 6dp); quantities are fixed-point count strings
    ("1200.00"). NEVER the event API's 1-99 integer cents — and never floats:
    wire strings are parsed with Decimal into integer micro-dollars
    (usd_micro) / centi-contracts (cc), the units the perp_* DB tables store.
  * Public market data (markets, orderbook, candlesticks, trades, funding
    rates) is UNAUTHENTICATED and always read from PRODUCTION — research data
    keeps flowing whatever mode the app is in, creds or not. Signed
    portfolio calls need Live: Paper has no perps book, and in Paper every
    signed perps call is refused before anything is signed.
  * Timestamps: REST query params are unix SECONDS (start_ts/end_ts);
    responses mix RFC3339 date-times and unix-second ints; WS uses epoch-ms.

No batch endpoints, no queue position, no RFQs on margin.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Optional
import uuid

import httpx

from kalshi_api import KalshiAPIError, _paper_mode_error
from kalshi_auth import sign_headers, get_env, sync_server_time, ENV_LOCK, PAPER

logger = logging.getLogger(__name__)

_PERPS_BASES = {
    "production": "https://external-api.kalshi.com",
}
PUBLIC_BASE = _PERPS_BASES["production"]

PATH_PREFIX = "/trade-api/v2"
REQUEST_TIMEOUT = 25.0
MAX_RETRIES = 3
RETRY_BACKOFF = 1.5
HOT_TIMEOUT = httpx.Timeout(connect=4.0, read=6.0, write=6.0, pool=6.0)
KEEPALIVE_SEC = 60.0
CANDLE_CHUNK = 3000
PERIOD_MIN_VALID = (1, 60, 1440)

_pub_client: Optional[httpx.AsyncClient] = None
_signed_client: Optional[httpx.AsyncClient] = None
_signed_env: str = ""



_MICRO = Decimal("1000000")
_CC = Decimal("100")


def usd_micro(s) -> int | None:
    """Wire dollar string → integer micro-dollars ('6.3500' → 6_350_000).
    Decimal end-to-end: usd_micro('0.0001') == 100 exactly. None-safe."""
    if s is None:
        return None
    try:
        return int((Decimal(str(s)) * _MICRO).to_integral_value(ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        return None


def micro_str(m: int, dp: int = 4) -> str:
    """Integer micro-dollars → wire string (6_350_000 → '6.3500')."""
    q = Decimal(int(m)) / _MICRO
    return f"{q:.{dp}f}"


def cc(s) -> int | None:
    """Wire FixedPointCount string → integer centi-contracts ('1200.00' → 120_000)."""
    if s is None:
        return None
    try:
        return int((Decimal(str(s)) * _CC).to_integral_value(ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        return None


def cc_str(c: int) -> str:
    """Integer centi-contracts → wire count string. Whole contracts are emitted
    without decimals (fractional_trading_enabled is false on all live perps)."""
    q = Decimal(int(c)) / _CC
    if q == q.to_integral_value():
        return str(int(q))
    return f"{q.normalize()}"


def micro_to_usd(m) -> float | None:
    """Loader-side convenience: 6_350_000 → 6.35 (research code wants floats)."""
    if m is None:
        return None
    return int(m) / 1_000_000


def cc_to_contracts(c) -> float | None:
    if c is None:
        return None
    return int(c) / 100


def rfc3339_to_sqlite(s: str) -> str:
    """'2026-07-05T20:00:00Z' / '...T20:00:00.123456Z' → '2026-07-05 20:00:00'
    (the repo-wide SQLite TEXT format replay's bucketizers slice)."""
    s = (s or "").strip().replace("T", " ").rstrip("Z")
    if "." in s:
        s = s.split(".", 1)[0]
    if "+" in s:
        s = s.split("+", 1)[0]
    return s[:19]


def env_ticker(symbol: str, env: str) -> str:
    """Symbol → wire ticker. Production is the only perps venue, so this is
    the upper-cased symbol; kept as a function so callers stay unchanged."""
    return (symbol or "").upper()



async def _get_pub_client() -> httpx.AsyncClient:
    global _pub_client
    if _pub_client is None or _pub_client.is_closed:
        _pub_client = httpx.AsyncClient(
            base_url=PUBLIC_BASE,
            timeout=REQUEST_TIMEOUT,
            headers={
                "Accept": "application/json",
                "User-Agent": "KryptTrader/1.0",
            },
            limits=httpx.Limits(
                max_connections=10, max_keepalive_connections=5,
                keepalive_expiry=KEEPALIVE_SEC,
            ),
            follow_redirects=True,
        )
    return _pub_client


async def _get_signed_client() -> httpx.AsyncClient:
    global _signed_client, _signed_env
    env = get_env()
    if (
        _signed_client is None
        or _signed_client.is_closed
        or _signed_env != env
    ):
        if _signed_client is not None and not _signed_client.is_closed:
            try:
                await _signed_client.aclose()
            except Exception:
                pass
        _signed_client = httpx.AsyncClient(
            base_url=_PERPS_BASES[env],
            timeout=REQUEST_TIMEOUT,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "KryptTrader/1.0",
            },
            limits=httpx.Limits(
                max_connections=10, max_keepalive_connections=5,
                keepalive_expiry=KEEPALIVE_SEC,
            ),
        )
        _signed_env = env
    return _signed_client


async def close_clients() -> None:
    global _pub_client, _signed_client
    for c in (_pub_client, _signed_client):
        if c and not c.is_closed:
            try:
                await c.aclose()
            except Exception:
                pass
    _pub_client = None
    _signed_client = None


async def _pub_get(path: str, params: dict | None = None) -> Any:
    """Unauthenticated GET against the PROD perps host. Soft-fails to None
    (kalshi_api._pub_get semantics: 429 honors retry-after, 5xx backoff,
    network errors → None, never raises)."""
    assert path.startswith("/")
    url = f"{PATH_PREFIX}{path}"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            client = await _get_pub_client()
            resp = await client.get(url, params=params)
            if resp.status_code == 429:
                wait = float(resp.headers.get("retry-after", 5))
                await asyncio.sleep(min(wait, 10))
                continue
            if resp.status_code >= 500 and attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF * attempt)
                continue
            try:
                return resp.json() if resp.status_code < 400 else None
            except Exception:
                return None
        except (httpx.NetworkError, httpx.TimeoutException) as e:
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF * attempt)
                continue
            logger.warning(f"perps public GET failed {path}: {e}")
            return None
    return None


async def _signed_request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    timeout: httpx.Timeout | float | None = None,
    pin_env: str | None = None,
) -> Any:
    """Signed request with the kalshi_api retry ladder (429 wait, 5xx backoff,
    timestamp-401 clock resync) against the perps host for the current env.

    Env safety mirrors kalshi_api._signed_request: the env is pinned to
    `pin_env` (or the env seen on the first attempt) and an env switch
    mid-flight ABORTS instead of silently signing for the other account.
    """
    assert path.startswith("/")
    signed_path = f"{PATH_PREFIX}{path}"
    method = method.upper()
    last_exc: Optional[Exception] = None
    env0: Optional[str] = pin_env
    if env0 == PAPER:
        raise _paper_mode_error()

    for attempt in range(1, MAX_RETRIES + 1):
        cur_env = get_env()
        if env0 is None:
            env0 = cur_env
        elif cur_env != env0:
            raise KalshiAPIError(
                409, {"error": {"code": "env_changed",
                                "message": "environment switched mid-request; aborted"}},
            )
        if cur_env == PAPER:
            raise _paper_mode_error()
        headers = sign_headers(method, signed_path)
        client = await _get_signed_client()
        try:
            resp = await client.request(
                method, signed_path, headers=headers, json=json, params=params,
                **({"timeout": timeout} if timeout is not None else {}),
            )
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_exc = e
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF * attempt)
                continue
            raise

        if resp.status_code == 429:
            wait = float(resp.headers.get("retry-after", 2.0))
            await asyncio.sleep(min(wait, 10))
            continue

        if 500 <= resp.status_code < 600 and attempt < MAX_RETRIES:
            await asyncio.sleep(RETRY_BACKOFF * attempt)
            continue

        try:
            body = resp.json()
        except Exception:
            body = resp.text

        if resp.status_code == 401 and attempt < MAX_RETRIES:
            code = ((body.get("error") or {}).get("code") or "") if isinstance(body, dict) else ""
            if "timestamp" in code:
                await asyncio.to_thread(sync_server_time, True)
                await asyncio.sleep(0.2)
                continue

        if resp.status_code >= 400:
            raise KalshiAPIError(resp.status_code, body)
        return body

    if last_exc:
        raise last_exc
    raise RuntimeError("exhausted retries without response")



async def fetch_perps_markets(status: str = "") -> list[dict]:
    """All perps markets with live bid/ask/price, reference/settlement/
    liquidation mark prices, OI, volume, contract_size, leverage_estimates."""
    params = {"status": status} if status else None
    data = await _pub_get("/margin/markets", params=params)
    if not isinstance(data, dict):
        return []
    return data.get("markets", []) or []


async def fetch_perps_market(ticker: str) -> dict | None:
    data = await _pub_get(f"/margin/markets/{ticker}")
    if not isinstance(data, dict):
        return None
    return data.get("market", data)


async def fetch_perps_orderbook(ticker: str) -> dict | None:
    """Raw book: {'orderbook': {'bids': [[px_str, count_str]...], 'asks': ...}}
    — price levels stay dollar strings; convert with usd_micro at ingest."""
    data = await _pub_get(f"/margin/markets/{ticker}/orderbook")
    return data if isinstance(data, dict) else None


async def fetch_perps_candlesticks(
    ticker: str,
    start_ts: int,
    end_ts: int,
    period_interval: int = 1,
) -> list[dict]:
    """One request. Candles carry bid/ask quote OHLC (always present) + trade
    OHLC/mean (null when no trades) + volume + OI. Timestamps unix seconds;
    candles included are those ENDING in [start_ts, end_ts]."""
    if period_interval not in PERIOD_MIN_VALID:
        raise ValueError(f"period_interval must be one of {PERIOD_MIN_VALID}, got {period_interval}")
    data = await _pub_get(
        f"/margin/markets/{ticker}/candlesticks",
        params={
            "start_ts": int(start_ts),
            "end_ts": int(end_ts),
            "period_interval": int(period_interval),
        },
    )
    if not isinstance(data, dict):
        return []
    return data.get("candlesticks", []) or []


async def fetch_perps_candlesticks_range(
    ticker: str,
    start_ts: int,
    end_ts: int,
    period_interval: int = 1,
    *,
    sleep_between: float = 0.3,
    max_requests: int = 60,
) -> list[dict]:
    """Chunked fetch of an arbitrary window (backfill/top-up). Windows of
    CANDLE_CHUNK candles; if a non-empty page ends short of its window
    (undocumented server page cap), continue from the last candle instead of
    trusting the window was complete. Deduped on end_period_ts."""
    period_s = int(period_interval) * 60
    out: dict[int, dict] = {}
    cursor = int(start_ts)
    end_ts = int(end_ts)
    for _ in range(max_requests):
        if cursor > end_ts:
            break
        window_end = min(end_ts, cursor + CANDLE_CHUNK * period_s)
        batch = await fetch_perps_candlesticks(
            ticker, cursor, window_end, period_interval,
        )
        if not batch:
            cursor = window_end + period_s
            if window_end >= end_ts:
                break
            continue
        max_end = 0
        for c in batch:
            try:
                ets = int(c.get("end_period_ts") or 0)
            except (TypeError, ValueError):
                continue
            if ets:
                out[ets] = c
                max_end = max(max_end, ets)
        cursor = (max_end + period_s) if 0 < max_end < window_end else (window_end + period_s)
        if cursor > end_ts:
            break
        await asyncio.sleep(sleep_between)
    return [out[k] for k in sorted(out)]


async def fetch_perps_trades(
    ticker: str,
    *,
    min_ts: int | None = None,
    max_ts: int | None = None,
    limit: int = 1000,
    max_pages: int = 10,
) -> list[dict]:
    out: list[dict] = []
    cursor = ""
    for _ in range(max_pages):
        params: dict = {"ticker": ticker, "limit": min(int(limit), 1000)}
        if min_ts is not None:
            params["min_ts"] = int(min_ts)
        if max_ts is not None:
            params["max_ts"] = int(max_ts)
        if cursor:
            params["cursor"] = cursor
        data = await _pub_get("/margin/trades", params=params)
        if not isinstance(data, dict):
            break
        out.extend(data.get("trades", []) or [])
        cursor = data.get("cursor") or ""
        if not cursor:
            break
        await asyncio.sleep(0.15)
    return out


async def fetch_funding_rate_estimate(ticker: str) -> dict | None:
    """In-progress window estimate: time-weighted premium-index average over
    [last_funding_time, now), finalized at next_funding_time. Carries
    funding_rate (double), mark_price (FP$), computed_time, next_funding_time."""
    data = await _pub_get(
        "/margin/funding_rates/estimate", params={"ticker": ticker},
    )
    return data if isinstance(data, dict) else None


async def fetch_funding_rates_historical(
    ticker: str = "",
    *,
    start_ts: int | None = None,
    end_ts: int | None = None,
) -> list[dict]:
    """Finalized funding rates (+ mark price at funding). Empty ticker = ALL
    markets; omitted timestamps = full available history (verified tiny)."""
    params: dict = {}
    if ticker:
        params["ticker"] = ticker
    if start_ts is not None:
        params["start_ts"] = int(start_ts)
    if end_ts is not None:
        params["end_ts"] = int(end_ts)
    data = await _pub_get("/margin/funding_rates/historical", params=params or None)
    if not isinstance(data, dict):
        return []
    return data.get("funding_rates", []) or []


async def fetch_perps_exchange_status() -> dict | None:
    data = await _pub_get("/margin/exchange/status")
    return data if isinstance(data, dict) else None


async def fetch_perps_risk_parameters() -> dict | None:
    data = await _pub_get("/margin/risk_parameters")
    return data if isinstance(data, dict) else None



async def get_perps_enabled() -> bool:
    try:
        data = await _signed_request("GET", "/margin/enabled")
    except (KalshiAPIError, httpx.HTTPError):
        return False
    return bool(isinstance(data, dict) and data.get("enabled"))


async def get_perps_balance(*, compute_available_balance: bool = True,
                            pin_env: str | None = None) -> dict:
    params = {"compute_available_balance": "true"} if compute_available_balance else None
    return await _signed_request(
        "GET", "/margin/balance", params=params, pin_env=pin_env,
    )


async def get_perps_positions(ticker: str = "") -> list[dict]:
    params: dict = {}
    if ticker:
        params["ticker"] = ticker
    data = await _signed_request("GET", "/margin/positions", params=params or None)
    if isinstance(data, dict):
        return data.get("positions", []) or []
    return data or []


async def get_perps_fills(
    *, min_ts: int | None = None, limit: int = 1000, max_pages: int = 5,
) -> list[dict]:
    out: list[dict] = []
    cursor = ""
    for _ in range(max_pages):
        params: dict = {"limit": min(int(limit), 1000)}
        if min_ts is not None:
            params["min_ts"] = int(min_ts)
        if cursor:
            params["cursor"] = cursor
        try:
            data = await _signed_request("GET", "/margin/fills", params=params)
        except KalshiAPIError:
            return out
        chunk = (data.get("fills") if isinstance(data, dict) else data) or []
        out.extend(chunk)
        cursor = (data.get("cursor") if isinstance(data, dict) else "") or ""
        if not cursor:
            break
    return out


async def get_perps_funding_history(
    start_date: str, end_date: str, ticker: str = "",
) -> list[dict]:
    """Our paid/received funding payments joined with rates.
    Dates are inclusive UTC YYYY-MM-DD (both required by the API)."""
    params: dict = {"start_date": start_date, "end_date": end_date}
    if ticker:
        params["ticker"] = ticker
    try:
        data = await _signed_request("GET", "/margin/funding_history", params=params)
    except (KalshiAPIError, httpx.HTTPError) as e:
        logger.warning(f"perps funding_history fetch failed: {e}")
        return []
    if not isinstance(data, dict):
        return []
    return data.get("funding_history", data.get("payments", [])) or []


async def get_perps_fee_tiers() -> dict | None:
    try:
        data = await _signed_request("GET", "/margin/fee_tiers")
    except (KalshiAPIError, httpx.HTTPError):
        return None
    return data if isinstance(data, dict) else None


async def get_perps_risk() -> dict | None:
    try:
        data = await _signed_request("GET", "/margin/risk")
    except (KalshiAPIError, httpx.HTTPError):
        return None
    return data if isinstance(data, dict) else None


async def get_perps_notional_risk_limit() -> dict | None:
    try:
        data = await _signed_request("GET", "/margin/notional_risk_limit")
    except (KalshiAPIError, httpx.HTTPError):
        return None
    return data if isinstance(data, dict) else None



async def place_perps_limit_order(
    *,
    ticker: str,
    side: str,
    count_cc: int,
    price_usd_micro: int,
    time_in_force: str = "good_till_canceled",
    post_only: bool = False,
    reduce_only: bool = False,
    client_order_id: Optional[str] = None,
) -> dict:
    side = side.lower()
    if side not in ("bid", "ask"):
        raise ValueError(f"side must be bid|ask, got {side}")
    if time_in_force not in ("good_till_canceled", "immediate_or_cancel", "fill_or_kill"):
        raise ValueError(f"bad time_in_force: {time_in_force}")
    if count_cc <= 0:
        raise ValueError(f"count_cc must be positive, got {count_cc}")
    if price_usd_micro <= 0:
        raise ValueError(f"price_usd_micro must be positive, got {price_usd_micro}")
    if reduce_only and time_in_force == "good_till_canceled":
        raise ValueError("reduce_only requires immediate_or_cancel or fill_or_kill")

    body: dict = {
        "ticker": ticker,
        "client_order_id": client_order_id or str(uuid.uuid4()),
        "side": side,
        "count": cc_str(int(count_cc)),
        "price": micro_str(int(price_usd_micro)),
        "time_in_force": time_in_force,
        "self_trade_prevention_type": "taker_at_cross",
    }
    if post_only:
        body["post_only"] = True
    if reduce_only:
        body["reduce_only"] = True
    async with ENV_LOCK:
        env0 = get_env()
    return await _signed_request(
        "POST", "/margin/orders", json=body, timeout=HOT_TIMEOUT, pin_env=env0,
    )


async def cancel_perps_order(order_id: str) -> dict:
    async with ENV_LOCK:
        env0 = get_env()
    return await _signed_request(
        "DELETE", f"/margin/orders/{order_id}", timeout=HOT_TIMEOUT, pin_env=env0,
    )


async def get_perps_order(order_id: str) -> dict:
    data = await _signed_request(
        "GET", f"/margin/orders/{order_id}", timeout=HOT_TIMEOUT,
    )
    if isinstance(data, dict):
        return data.get("order", data)
    return data


async def get_perps_orders(ticker: str = "", *, limit: int = 200) -> list[dict]:
    params: dict = {"limit": int(limit)}
    if ticker:
        params["ticker"] = ticker
    data = await _signed_request("GET", "/margin/orders", params=params)
    if isinstance(data, dict):
        return data.get("orders", []) or []
    return data or []


async def find_perps_order_by_client_id(
    client_order_id: str, *, ticker: str = "", pin_env: str | None = None,
) -> dict | None:
    """Lost-response recovery, mirroring kalshi_api.find_order_by_client_id:
    after a POST whose response was lost the order may be live — look it up by
    our client id before booking an error."""
    params: dict = {"limit": 200}
    if ticker:
        params["ticker"] = ticker
    data = await _signed_request(
        "GET", "/margin/orders", params=params, pin_env=pin_env,
    )
    orders = (data.get("orders") if isinstance(data, dict) else data) or []
    for o in orders:
        if isinstance(o, dict) and str(o.get("client_order_id") or "") == str(client_order_id):
            return o
    return None
