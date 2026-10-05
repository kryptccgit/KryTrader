from __future__ import annotations

import asyncio
import logging
import math
from decimal import Decimal
import re
from typing import Any, Optional
import time
import uuid

import httpx

import kalshi_ws
from kalshi_auth import sign_headers, get_env, sync_server_time, ENV_LOCK

logger = logging.getLogger(__name__)

PUBLIC_BASE = "https://api.elections.kalshi.com/trade-api/v2"

_TRADE_BASES = {
    "demo": "https://demo-api.kalshi.co",
    "production": "https://api.elections.kalshi.com",
}

PATH_PREFIX = "/trade-api/v2"
REQUEST_TIMEOUT = 25.0
MAX_RETRIES = 3
RETRY_BACKOFF = 1.5
HOT_TIMEOUT = httpx.Timeout(connect=4.0, read=6.0, write=6.0, pool=6.0)
KEEPALIVE_SEC = 60.0

NET_STATS: dict[str, dict] = {}


def _host_of(url: str) -> str:
    try:
        rest = url.split("://", 1)[1]
    except IndexError:
        return url[:80]
    return rest.split("/", 1)[0]


def note_call(host: str, *, ok: bool, ms: float, error: str = "") -> None:
    st = NET_STATS.setdefault(host, {
        "calls": 0, "errors": 0, "lastMs": None, "totalMs": 0.0,
        "lastAt": None, "lastError": None,
    })
    st["calls"] += 1
    st["lastMs"] = round(ms, 1)
    st["totalMs"] += ms
    st["lastAt"] = time.time()
    if not ok:
        st["errors"] += 1
        st["lastError"] = (error or "failed")[:200]


def counting_hooks() -> dict:
    async def _on_request(request) -> None:
        try:
            request.extensions["_krypt_t0"] = time.monotonic()
        except Exception:
            pass

    async def _on_response(response) -> None:
        try:
            t0 = response.request.extensions.get("_krypt_t0")
            ms = (time.monotonic() - t0) * 1000 if t0 else 0.0
            ok = response.status_code < 400
            note_call(
                response.request.url.host or "", ok=ok, ms=ms,
                error="" if ok else f"HTTP {response.status_code}",
            )
        except Exception:
            pass

    return {"request": [_on_request], "response": [_on_response]}


def net_stats() -> dict[str, dict]:
    return {
        h: {
            "calls": v["calls"],
            "errors": v["errors"],
            "lastMs": v["lastMs"],
            "avgMs": round(v["totalMs"] / v["calls"], 1) if v["calls"] else None,
            "lastAt": v["lastAt"],
            "lastError": v["lastError"],
        }
        for h, v in NET_STATS.items()
    }


_pub_client: Optional[httpx.AsyncClient] = None
_signed_client: Optional[httpx.AsyncClient] = None
_signed_env: str = ""


async def _get_pub_client() -> httpx.AsyncClient:
    global _pub_client
    if _pub_client is None or _pub_client.is_closed:
        _pub_client = httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            headers={
                "Accept": "application/json",
                "User-Agent": "KryptTrader/1.0",
            },
            limits=httpx.Limits(
                max_connections=20, max_keepalive_connections=10,
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
            base_url=_TRADE_BASES[env],
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


class KalshiAPIError(Exception):
    def __init__(self, status: int, body: Any):
        self.status = status
        self.body = body
        super().__init__(f"HTTP {status}: {body}")


class KalshiTruncatedResult(Exception):
    pass




async def _pub_get(url: str, params: dict | None = None) -> Any:
    data, _status = await _pub_get_ex(url, params)
    return data


async def _pub_get_ex(url: str, params: dict | None = None) -> tuple[Any, Optional[int]]:
    host = _host_of(url)
    last_status: Optional[int] = None
    for attempt in range(1, MAX_RETRIES + 1):
        t0 = time.monotonic()
        try:
            client = await _get_pub_client()
            resp = await client.get(url, params=params)
            note_call(
                host, ok=resp.status_code < 400,
                ms=(time.monotonic() - t0) * 1000,
                error="" if resp.status_code < 400 else f"HTTP {resp.status_code}",
            )
            last_status = resp.status_code
            if resp.status_code == 429:
                wait = float(resp.headers.get("retry-after", 5))
                await asyncio.sleep(min(wait, 10))
                continue
            if resp.status_code >= 500 and attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF * attempt)
                continue
            try:
                return (resp.json() if resp.status_code < 400 else None,
                        resp.status_code)
            except Exception:
                return None, resp.status_code
        except (httpx.NetworkError, httpx.TimeoutException) as e:
            note_call(host, ok=False, ms=(time.monotonic() - t0) * 1000,
                      error=f"{type(e).__name__}: {e}")
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF * attempt)
                continue
            logger.warning(f"public GET failed {url}: {e}")
            return None, None
    return None, last_status


async def fetch_markets(
    status: str = "open",
    limit: int = 1000,
    cursor: str = "",
    series_ticker: str = "",
) -> tuple[list, str]:
    params: dict = {"limit": min(limit, 1000)}
    if status:
        params["status"] = status
    if cursor:
        params["cursor"] = cursor
    if series_ticker:
        params["series_ticker"] = series_ticker
    data = await _pub_get(f"{PUBLIC_BASE}/markets", params=params)
    if not isinstance(data, dict):
        return [], ""
    markets = data.get("markets", []) or []
    for m in markets:
        _note_shard(m)
    return markets, data.get("cursor", "")


async def fetch_market(ticker: str) -> dict | None:
    data = await _pub_get(f"{PUBLIC_BASE}/markets/{ticker}")
    if not isinstance(data, dict):
        return None
    m = data.get("market", data)
    _note_shard(m)
    return m


async def fetch_market_checked(ticker: str) -> tuple[dict | None, str]:
    data, status = await _pub_get_ex(f"{PUBLIC_BASE}/markets/{ticker}")
    if isinstance(data, dict):
        m = data.get("market", data)
        return (m, "found") if isinstance(m, dict) and m.get("ticker") else (None, "missing")
    if status is not None and 400 <= status < 500:
        return None, "missing"
    return None, "unreachable"


_TICKER_BATCH = 50


async def fetch_markets_by_tickers(tickers) -> dict:
    uniq = [t for t in dict.fromkeys(tickers) if t]
    out: dict = {}
    for i in range(0, len(uniq), _TICKER_BATCH):
        chunk = uniq[i:i + _TICKER_BATCH]
        data = await _pub_get(
            f"{PUBLIC_BASE}/markets",
            params={"tickers": ",".join(chunk), "limit": 1000},
        )
        for m in ((data or {}).get("markets") or []):
            tk = m.get("ticker")
            if tk:
                out[tk] = m
                _note_shard(m)
    return out


async def fetch_markets_map(tickers, concurrency: int = 8) -> dict:
    uniq = [t for t in dict.fromkeys(tickers) if t]
    if not uniq:
        return {}
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(tk: str):
        async with sem:
            try:
                return tk, await fetch_market(tk)
            except Exception:
                return tk, None

    pairs = await asyncio.gather(*[_one(t) for t in uniq])
    return {tk: m for tk, m in pairs if m}


async def fetch_all_open_markets(max_pages: int = 10) -> list:
    out: list = []
    cursor = ""
    for _ in range(max_pages):
        m, cursor = await fetch_markets(status="open", limit=1000, cursor=cursor)
        if not m:
            break
        out.extend(m)
        if not cursor:
            break
        await asyncio.sleep(0.25)
    return out


async def fetch_recent_trades(limit: int = 1000) -> list | None:
    data = await _pub_get(f"{PUBLIC_BASE}/markets/trades", params={"limit": limit})
    if not isinstance(data, dict):
        return None
    return data.get("trades", []) or []


async def fetch_trades_for_market(ticker: str, limit: int = 100) -> list | None:
    data = await _pub_get(
        f"{PUBLIC_BASE}/markets/trades",
        params={"ticker": ticker, "limit": min(int(limit), 1000)},
    )
    if not isinstance(data, dict):
        return None
    return data.get("trades", []) or []


async def fetch_events(
    status: str = "open", limit: int = 200, cursor: str = "",
    with_nested_markets: bool = False,
) -> tuple[list, str] | None:
    params: dict = {"limit": min(limit, 200)}
    if status:
        params["status"] = status
    if cursor:
        params["cursor"] = cursor
    if with_nested_markets:
        params["with_nested_markets"] = "true"
    data = await _pub_get(f"{PUBLIC_BASE}/events", params=params)
    if not isinstance(data, dict):
        return None
    return data.get("events", []) or [], data.get("cursor", "")


async def fetch_markets_closing_before(
    max_close_ts: int, min_close_ts: int = 0, limit: int = 200,
) -> list | None:
    params: dict = {"status": "open", "limit": min(int(limit), 1000),
                    "max_close_ts": int(max_close_ts)}
    if min_close_ts:
        params["min_close_ts"] = int(min_close_ts)
    data = await _pub_get(f"{PUBLIC_BASE}/markets", params=params)
    if not isinstance(data, dict):
        return None
    return data.get("markets", []) or []


_series_cache: dict[str, dict] = {}


async def fetch_series(series_ticker: str) -> dict | None:
    if series_ticker in _series_cache:
        return _series_cache[series_ticker]
    data = await _pub_get(f"{PUBLIC_BASE}/series/{series_ticker}")
    if not isinstance(data, dict):
        return None
    s = data.get("series", data)
    if len(_series_cache) < 5000:
        _series_cache[series_ticker] = s
    return s


async def fetch_event(event_ticker: str, with_nested: bool = True) -> dict | None:
    params = {"with_nested_markets": "true"} if with_nested else None
    data = await _pub_get(f"{PUBLIC_BASE}/events/{event_ticker}", params=params)
    if not isinstance(data, dict):
        return None
    ev = data.get("event", data)
    if with_nested and isinstance(ev, dict) and "markets" not in ev:
        mk = data.get("markets")
        if isinstance(mk, list):
            ev = {**ev, "markets": mk}
    return ev


async def fetch_orders(
    *, status: str = "", ticker: str = "", limit: int = 200,
    pin_env: str | None = None,
) -> list[dict]:
    out: list[dict] = []
    cursor: Optional[str] = None
    pages = 0
    while True:
        params: dict = {"limit": int(limit)}
        if status:
            params["status"] = status
        if ticker:
            params["ticker"] = ticker
        if cursor:
            params["cursor"] = cursor
        data = await _signed_request(
            "GET", "/portfolio/orders", params=params, pin_env=pin_env,
        )
        chunk = (data.get("orders") if isinstance(data, dict) else data) or []
        out.extend(chunk)
        cursor = data.get("cursor") if isinstance(data, dict) else None
        pages += 1
        if not cursor or pages >= 5:
            break
    return out


async def fetch_candlesticks(
    *, ticker: str, series_ticker: str = "", start_ts: int, end_ts: int,
    period_interval: int = 1,
) -> list[dict] | None:
    q = {
        "start_ts": int(start_ts),
        "end_ts": int(end_ts),
        "period_interval": int(period_interval),
    }
    series = (series_ticker or "").strip() or (ticker or "").split("-")[0]
    paths = [
        f"{PUBLIC_BASE}/series/{series}/markets/{ticker}/candlesticks",
        f"{PUBLIC_BASE}/historical/markets/{ticker}/candlesticks",
    ]
    for path in paths:
        data = await _pub_get(path, params=q)
        if isinstance(data, dict):
            candles = data.get("candlesticks")
            if isinstance(candles, list):
                return candles
    return None


_WEB_HOSTS = {
    "production": "kalshi.com",
    "demo": "demo.kalshi.co",
}


def web_exchange_indexes_url(env: str = "production") -> str:
    return f"https://{_WEB_HOSTS.get(env, 'kalshi.com')}/account/exchange-indexes"

def _slugify(text: str) -> str:
    s = (text or "").strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"[^a-z0-9-]", "", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s


def _event_from_ticker(ticker: str) -> str:
    parts = (ticker or "").split("-")
    if len(parts) >= 3:
        return "-".join(parts[:-1])
    return ticker or ""


async def web_market_url(
    *, event_ticker: str = "", ticker: str = "", env: str = "production",
) -> str:
    event = (event_ticker or "").strip() or _event_from_ticker(ticker)
    base = event or (ticker or "").strip()
    if not base:
        return ""
    series_l = base.split("-")[0].lower()
    host = _WEB_HOSTS.get(env, "kalshi.com")

    slug = ""
    try:
        s = await fetch_series(base.split("-")[0])
        if s:
            slug = _slugify(str(s.get("title", "")))
    except Exception:
        slug = ""

    if slug and event:
        return f"https://{host}/markets/{series_l}/{slug}/{event.lower()}"
    if slug:
        return f"https://{host}/markets/{series_l}/{slug}"
    return f"https://{host}/markets/{series_l}"




async def _signed_request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    timeout: httpx.Timeout | float | None = None,
    pin_env: str | None = None,
    retry: bool = True,
) -> Any:
    assert path.startswith("/")
    signed_path = f"{PATH_PREFIX}{path}"
    method = method.upper()
    last_exc: Optional[Exception] = None
    env0: Optional[str] = pin_env

    for attempt in range(1, MAX_RETRIES + 1):
        cur_env = get_env()
        if env0 is None:
            env0 = cur_env
        elif cur_env != env0:
            raise KalshiAPIError(
                409, {"error": {"code": "env_changed",
                                "message": "environment switched mid-request; aborted"}},
            )
        headers = sign_headers(method, signed_path)
        client = await _get_signed_client()
        signed_host = _host_of(_TRADE_BASES[env0])
        t0 = time.monotonic()
        try:
            resp = await client.request(
                method, signed_path, headers=headers, json=json, params=params,
                **({"timeout": timeout} if timeout is not None else {}),
            )
            note_call(
                signed_host, ok=resp.status_code < 400,
                ms=(time.monotonic() - t0) * 1000,
                error="" if resp.status_code < 400 else f"HTTP {resp.status_code}",
            )
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            note_call(signed_host, ok=False, ms=(time.monotonic() - t0) * 1000,
                      error=f"{type(e).__name__}: {e}")
            last_exc = e
            if retry and attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_BACKOFF * attempt)
                continue
            raise

        if resp.status_code == 429 and retry:
            wait = float(resp.headers.get("retry-after", 2.0))
            await asyncio.sleep(min(wait, 10))
            continue

        if 500 <= resp.status_code < 600 and retry and attempt < MAX_RETRIES:
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


SHARD_NAMES = {
    0: "general",
    1: "combos",
    2: "crypto",
    3: "tennis & baseball",
}


_STATUS_TTL = 45.0
_status_cache: dict[str, Any] = {"at": 0.0, "val": None}


async def fetch_exchange_status(refresh: bool = False) -> dict | None:
    now = time.time()
    if not refresh and _status_cache["val"] is not None:
        if now - _status_cache["at"] < _STATUS_TTL:
            return _status_cache["val"]

    data = await _pub_get(f"{PUBLIC_BASE}/exchange/status")
    if not isinstance(data, dict):
        return None

    shards: dict[int, dict] = {}
    for row in (data.get("exchange_index_statuses") or []):
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("exchange_index"))
        except (TypeError, ValueError):
            continue
        desc = (row.get("description") or "").strip()
        shards[idx] = {
            "exchangeActive": bool(row.get("exchange_active")),
            "tradingActive": bool(row.get("trading_active")),
            "transfersActive": bool(row.get("intra_exchange_transfers_active")),
            "name": desc or shard_name(idx),
        }

    out = {
        "exchangeActive": bool(data.get("exchange_active")),
        "tradingActive": bool(data.get("trading_active")),
        "shards": shards,
        "fetchedAt": now,
    }
    _status_cache["at"] = now
    _status_cache["val"] = out
    return out


_CENTICENTS_PER_DOLLAR = 10_000


async def transfer_between_shards(
    *, amount_usd: float, source_shard: int, destination_shard: int,
) -> dict:
    try:
        amt = float(amount_usd)
    except (TypeError, ValueError):
        raise ValueError("The transfer amount must be a number.")
    if not math.isfinite(amt):
        raise ValueError("The transfer amount must be a real number.")
    if amt <= 0:
        raise ValueError("The transfer amount must be more than $0.00.")

    try:
        src = int(source_shard)
        dst = int(destination_shard)
    except (TypeError, ValueError):
        raise ValueError("Exchange shard must be a whole number.")
    if src == dst:
        raise ValueError("Source and destination are the same exchange.")
    if not (0 <= src <= 100) or not (0 <= dst <= 100):
        raise ValueError("Exchange shard is out of range.")

    cents = int(Decimal(str(amt)) * 100)
    if cents <= 0:
        raise ValueError("The transfer amount rounds to $0.00.")

    bal = await get_balance()
    shards = (bal or {}).get("shard_balances") or {}
    have = shards.get(src)
    if have is not None and cents > int(round(have * 100)):
        raise ValueError(
            f"{shard_name(src)} holds ${have:,.2f}; cannot move "
            f"${cents / 100:,.2f} from it."
        )

    body = {
        "source": "event_contract",
        "destination": "event_contract",
        "source_exchange_shard": src,
        "destination_exchange_shard": dst,
        "amount": cents * (_CENTICENTS_PER_DOLLAR // 100),
    }
    async with ENV_LOCK:
        env0 = get_env()
    logger.info(
        "transferring $%.2f from %s to %s", cents / 100,
        shard_name(src), shard_name(dst),
    )
    res = await _signed_request(
        "POST", "/portfolio/intra_exchange_instance_transfer",
        json=body, timeout=HOT_TIMEOUT, pin_env=env0, retry=False,
    )
    _status_cache["at"] = 0.0
    return res if isinstance(res, dict) else {"transfer_id": ""}

def cached_exchange_status() -> dict | None:
    return _status_cache["val"]

def shard_trading_halted(status: dict | None, index: int | None) -> Optional[str]:
    if not status or index is None:
        return None
    row = (status.get("shards") or {}).get(int(index))
    if row is None:
        if not status.get("tradingActive") and int(index) == 0:
            return shard_name(index)
        return None
    if row["tradingActive"] and row["exchangeActive"]:
        return None
    return row["name"]

_series_shard: dict[str, int] = {}


def _note_shard(m: Any) -> None:
    if not isinstance(m, dict):
        return
    idx = m.get("exchange_index")
    if idx is None:
        return
    tk = str(m.get("ticker") or "")
    series = str(m.get("series_ticker") or "").strip() or (tk.split("-")[0] if tk else "")
    if not series:
        return
    try:
        v = int(idx)
    except (TypeError, ValueError):
        return
    if len(_series_shard) < 5000:
        _series_shard[series.upper()] = v


def shard_for_ticker(ticker: str) -> Optional[int]:
    tk = (ticker or "").strip().upper()
    if not tk:
        return None
    return _series_shard.get(tk.split("-")[0])

def shard_name(index: int | None) -> str:
    if index is None:
        return "unknown"
    return SHARD_NAMES.get(int(index), f"shard {index}")


def _balance_breakdown(data: Any) -> dict[int, float]:
    out: dict[int, float] = {}
    if not isinstance(data, dict):
        return out
    for row in (data.get("balance_breakdown") or []):
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("exchange_index"))
        except (TypeError, ValueError):
            continue
        raw = row.get("balance")
        if raw is None:
            continue
        try:
            out[idx] = float(raw)
        except (TypeError, ValueError):
            continue
    return out


async def get_balance(pin_env: str | None = None) -> dict:
    data = await _signed_request("GET", "/portfolio/balance", pin_env=pin_env)
    if not isinstance(data, dict):
        return data
    shards = _balance_breakdown(data)
    if shards:
        total_cents = int(round(sum(shards.values()) * 100))
    else:
        try:
            total_cents = int(data.get("balance") or 0)
        except (TypeError, ValueError):
            total_cents = 0
    return {
        **data,
        "total_balance_cents": total_cents,
        "shard_balances": shards,
        "sharded": bool(shards),
    }


def is_user_not_found(err: Exception) -> bool:
    if not isinstance(err, KalshiAPIError):
        return False
    return "user_not_found" in str(err.body) or "user not found" in str(err.body)


async def explain_order_rejection(err: Exception, *, ticker: str = "",
                                  exchange_index: int | None = None) -> str:
    base = str(err)
    if not is_user_not_found(err):
        return base

    if exchange_index is None and ticker:
        try:
            m = await fetch_market(ticker)
            if isinstance(m, dict) and m.get("exchange_index") is not None:
                exchange_index = int(m["exchange_index"])
        except Exception:
            pass

    where = f" hosting {ticker}" if ticker else ""
    shard = shard_name(exchange_index) if exchange_index is not None else ""
    engine = f" ({shard})" if shard and shard != "unknown" else ""

    try:
        bal = await get_balance()
    except Exception as probe_err:
        if is_user_not_found(probe_err):
            return (
                f"{base} — Kalshi does not recognise this API key's account "
                f"at all (the balance read fails the same way). The key was "
                f"most likely deleted or rotated on Kalshi, or it was created "
                f"in the other environment: demo keys do not exist in "
                f"production and vice versa. Re-add your keys under API Keys "
                f"and check the environment switch."
            )
        return (
            f"{base} — could not tell whether the account or the exchange "
            f"shard is the problem, because the balance read also failed "
            f"({probe_err})."
        )

    shards = bal.get("shard_balances") or {}
    total = (bal.get("total_balance_cents") or 0) / 100.0
    if exchange_index is not None and shards:
        here = shards.get(int(exchange_index))
        if here is not None and here <= 0:
            elsewhere = ", ".join(
                f"{shard_name(i)} ${v:,.2f}" for i, v in sorted(shards.items())
                if v > 0) or "nowhere"
            return (
                f"{base} — your account is fine, but the matching engine"
                f"{where}{engine} holds $0.00 of your collateral. Kalshi "
                f"allocates collateral per exchange shard, and an order can "
                f"only be filled on a shard your money is on. Your cash is "
                f"on: {elsewhere}. Move some to "
                f"{shard_name(exchange_index)} at "
                f"{web_exchange_indexes_url(get_env())}, then this order will "
                f"go through."
            )

    return (
        f"{base} — your credentials still work (balance reads "
        f"${total:,.2f}), so this is the matching engine{where}{engine} "
        f"refusing the account rather than a bad key. Check that this shard "
        f"has collateral allocated to it at "
        f"{web_exchange_indexes_url(get_env())}."
    )

async def get_account_limits(pin_env: str | None = None) -> dict:
    return await _signed_request("GET", "/account/limits", pin_env=pin_env)


async def upgrade_api_usage_level(pin_env: str | None = None) -> dict:
    return await _signed_request("POST", "/account/api_usage_level/upgrade", pin_env=pin_env)


_POSITIONS_MAX_PAGES = 25


async def get_positions(
    limit: int = 200, *, settlement_status: str | None = None,
    paginate: bool = True,
) -> list[dict]:
    out: list[dict] = []
    cursor: Optional[str] = None
    pages = 0
    while True:
        params: dict = {"limit": int(limit)}
        if settlement_status:
            params["settlement_status"] = settlement_status
        if cursor:
            params["cursor"] = cursor
        data = await _signed_request(
            "GET", "/portfolio/positions", params=params,
        )
        if isinstance(data, dict):
            out.extend(data.get("market_positions", []) or [])
            cursor = data.get("cursor") or None
        else:
            out.extend(data or [])
            cursor = None
        pages += 1
        if not paginate or not cursor:
            break
        if pages >= _POSITIONS_MAX_PAGES:
            raise KalshiTruncatedResult(
                f"/portfolio/positions pagination hit the {pages}-page cap "
                f"with more rows remaining; refusing to return a truncated "
                f"snapshot"
            )
    return out


async def get_settled_positions(limit: int = 200) -> list[dict]:
    try:
        data = await _signed_request(
            "GET",
            "/portfolio/positions",
            params={"limit": limit, "settlement_status": "settled"},
        )
    except KalshiAPIError:
        return []
    if isinstance(data, dict):
        return data.get("market_positions", []) or []
    return data or []


async def get_order(order_id: str, *, pin_env: str | None = None) -> dict:
    return await _signed_request(
        "GET", f"/portfolio/orders/{order_id}", timeout=HOT_TIMEOUT,
        pin_env=pin_env,
    )


async def find_order_by_client_id(
    client_order_id: str, *, ticker: str = "", limit: int = 200,
    pin_env: str | None = None,
) -> dict | None:
    params: dict = {"limit": int(limit)}
    if ticker:
        params["ticker"] = ticker
    data = await _signed_request("GET", "/portfolio/orders", params=params, pin_env=pin_env)
    orders = (data.get("orders") if isinstance(data, dict) else data) or []
    for o in orders:
        if isinstance(o, dict) and str(o.get("client_order_id") or "") == str(client_order_id):
            return o
    return None


async def get_fills_for_order(order_id: str, limit: int = 200) -> list[dict]:
    out: list[dict] = []
    cursor: Optional[str] = None
    pages = 0
    while True:
        params: dict = {"order_id": order_id, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        try:
            data = await _signed_request("GET", "/portfolio/fills", params=params)
        except KalshiAPIError as e:
            if e.status == 404:
                return []
            raise
        chunk = (data.get("fills") if isinstance(data, dict) else data) or []
        out.extend(chunk)
        cursor = data.get("cursor") if isinstance(data, dict) else None
        pages += 1
        if not cursor or pages >= 5:
            break
    return out


async def get_fills_since(after_ts_unix: int, limit: int = 200) -> list[dict]:
    out: list[dict] = []
    cursor: Optional[str] = None
    pages = 0
    while True:
        params: dict = {
            "min_ts": int(after_ts_unix),
            "limit": limit,
        }
        if cursor:
            params["cursor"] = cursor
        try:
            data = await _signed_request("GET", "/portfolio/fills", params=params)
        except KalshiAPIError:
            return out
        chunk = (data.get("fills") if isinstance(data, dict) else data) or []
        out.extend(chunk)
        cursor = data.get("cursor") if isinstance(data, dict) else None
        pages += 1
        if not cursor or pages >= 5:
            break
    return out


def _normalize_orderbook(raw: Any) -> dict:
    if not isinstance(raw, dict):
        return {"yes": [], "no": []}
    book = raw.get("orderbook") or raw.get("orderbook_fp") or raw
    out: dict = {"yes": [], "no": []}
    for side in ("yes", "no"):
        levels = book.get(side)
        is_dollars = levels is None
        if is_dollars:
            levels = book.get(f"{side}_dollars") or []
        for lvl in levels or []:
            try:
                price = round(float(lvl[0]) * 100, 1) if is_dollars else round(float(lvl[0]), 1)
                size = float(lvl[1]) if len(lvl) > 1 else 0.0
                out[side].append([price, size])
            except (TypeError, ValueError, IndexError):
                continue
    return out


async def get_orderbook(ticker: str) -> dict:
    wb = kalshi_ws.orderbook(ticker)
    if wb is not None and (wb["yes"] or wb["no"]):
        return wb
    try:
        book = _normalize_orderbook(await _signed_request(
            "GET", f"/markets/{ticker}/orderbook", timeout=HOT_TIMEOUT,
        ))
        if book["yes"] or book["no"]:
            return book
    except Exception:
        pass
    return _normalize_orderbook(await _pub_get(f"{PUBLIC_BASE}/markets/{ticker}/orderbook"))


ORDERS_V2_PATH = "/portfolio/events/orders"


def _v2_order_fields(side: str, action: str, price_cents: float) -> tuple[str, str]:
    if side == "yes":
        book_side = "bid" if action == "buy" else "ask"
        yes_cents = price_cents
    else:
        book_side = "ask" if action == "buy" else "bid"
        yes_cents = 100 - price_cents
    return book_side, f"{yes_cents / 100:.4f}"


async def place_limit_order(
    *,
    ticker: str,
    side: str,
    action: str,
    count: int,
    price_cents: int,
    client_order_id: Optional[str] = None,
) -> dict:
    side = side.lower()
    action = action.lower()
    if side not in ("yes", "no"):
        raise ValueError(f"side must be yes|no, got {side}")
    if action not in ("buy", "sell"):
        raise ValueError(f"action must be buy|sell, got {action}")
    price_cents = float(price_cents)
    if not (0.1 <= price_cents <= 99.9):
        raise ValueError(f"price_cents must be 0.1..99.9, got {price_cents}")
    if abs(price_cents * 10 - round(price_cents * 10)) > 1e-6:
        raise ValueError(f"price_cents must be a 0.1c multiple, got {price_cents}")
    price_cents = round(price_cents, 1)
    if count <= 0:
        raise ValueError(f"count must be positive, got {count}")

    book_side, price = _v2_order_fields(side, action, price_cents)
    body: dict = {
        "ticker": ticker,
        "client_order_id": client_order_id or str(uuid.uuid4()),
        "side": book_side,
        "count": f"{int(count)}.00",
        "price": price,
        "time_in_force": "good_till_canceled",
        "self_trade_prevention_type": "taker_at_cross",
        "exchange_index": -1,
    }
    async with ENV_LOCK:
        env0 = get_env()
    return await _signed_request(
        "POST", ORDERS_V2_PATH, json=body, timeout=HOT_TIMEOUT, pin_env=env0,
    )


async def cancel_order(order_id: str, *, pin_env: str | None = None) -> dict:
    if pin_env is None:
        async with ENV_LOCK:
            pin_env = get_env()
    return await _signed_request(
        "DELETE", f"{ORDERS_V2_PATH}/{order_id}", timeout=HOT_TIMEOUT, pin_env=pin_env,
    )
