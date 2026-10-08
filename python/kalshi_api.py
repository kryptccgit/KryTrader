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

import kalshi_auth
import kalshi_ws
from kalshi_auth import sign_headers, get_env, sync_server_time, ENV_LOCK, PAPER

logger = logging.getLogger(__name__)

PUBLIC_BASE = "https://api.elections.kalshi.com/trade-api/v2"

_TRADE_BASES = {
    "production": "https://api.elections.kalshi.com",
}



def _paper_mode_error() -> "KalshiAPIError":
    return KalshiAPIError(403, {"error": {
        "code": "paper_mode",
        "message": ("Paper mode: this needs your real Kalshi account. Add a "
                    "Kalshi key and switch to Live to use it."),
    }})


def _routes_to_paper(pin_env: str | None = None) -> bool:
    return (pin_env or get_env()) == PAPER


def _scope_changed_error(decided: str, now: str) -> "KalshiAPIError":
    return KalshiAPIError(409, {"error": {
        "code": "scope_changed",
        "message": (f"The app switched from {'Paper' if decided == PAPER else 'Live'} to "
                    f"{'Paper' if now == PAPER else 'Live'} after this was decided; "
                    f"nothing was sent."),
    }})


def is_scope_changed(err: Exception) -> bool:
    """The order was refused because the app switched Paper<->Live after it
    was decided. Raised before routing or signing: NOT delivered, so callers
    book a plain rejection and skip lost-order recovery."""
    return (isinstance(err, KalshiAPIError) and err.status == 409
            and "scope_changed" in str(err.body))


def _check_scope(pin_env: str | None) -> None:
    """A call decided under one scope (paper | production) must not be carried
    out under the other. Without this a buy sized from the paper balance and
    booked as a paper row could go out with real money after a Go live in the
    seconds between deciding and sending — and a Live exit could sell paper
    contracts after a switch back."""
    if pin_env is not None:
        now = get_env()
        if pin_env != now:
            raise _scope_changed_error(pin_env, now)


def _paper():
    import paper_exchange
    return paper_exchange

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
    """httpx event hooks that feed `note_call` for every request on a client.

    So a module can be counted by adding one argument at client construction
    rather than by remembering at each call site — which is why eight
    catalogued hosts went uncounted: the crypto price feeds, the two chat
    transports and the perps API all build their own clients, and the Privacy
    panel could only ever show what this module happened to measure.

    Network failures never produce a response, so they are not counted here;
    the panel's error column stays a lower bound for those hosts.
    """
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
    """A paginated portfolio read hit its page cap with a cursor still
    outstanding — the collected rows are an INCOMPLETE snapshot. Callers that
    treat the list as authoritative (reconcile orphan-closing) must treat this
    as a failed fetch, not as 'everything past the cut is no longer held'."""




async def _pub_get(url: str, params: dict | None = None) -> Any:
    """Public GET, or None. See `_pub_get_ex` when the caller needs to tell a
    404 apart from a failure."""
    data, _status = await _pub_get_ex(url, params)
    return data


async def _pub_get_ex(url: str, params: dict | None = None) -> tuple[Any, Optional[int]]:
    """Public GET returning (data, http_status).

    `_pub_get` collapses "Kalshi says this does not exist" (404) and "we could
    not reach Kalshi" (timeout, DNS, park) into the same None, and callers that
    act on the difference were quietly getting it wrong — a rule armed on a
    typo'd ticker reported "nobody is bidding" and re-polled forever, because
    an empty book and a missing market look identical downstream.

    status is None when no response was obtained at all.
    """
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
    """(market, 'found' | 'missing' | 'unreachable').

    'missing' is Kalshi telling us there is no such market; 'unreachable' is us
    failing to ask. Callers that refuse an action must only refuse on 'missing'
    — refusing on 'unreachable' would turn a flaky network into a lockout."""
    data, status = await _pub_get_ex(f"{PUBLIC_BASE}/markets/{ticker}")
    if isinstance(data, dict):
        m = data.get("market", data)
        return (m, "found") if isinstance(m, dict) and m.get("ticker") else (None, "missing")
    if status is not None and 400 <= status < 500 and status not in (408, 429):
        return None, "missing"
    return None, "unreachable"


_TICKER_BATCH = 50


async def fetch_markets_by_tickers(tickers) -> dict:
    """Many markets in ONE request each 50 → {ticker: market}.

    The per-ticker alternative (`fetch_markets_map`) fires one HTTP request per
    market and does it INSIDE a gather, so it slips past any per-host rate gate
    wrapped around the call. Measured at 86 requests for a single Discover
    refresh, and enough to earn an HTTP 429 mid-pass. Prefer this whenever the
    ticker list is known up front.
    """
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
    """Fetch many markets concurrently → {ticker: market}, skipping misses.

    Replaces the serial `for t in tickers: await fetch_market(t)` chains in the
    resolution paths, where one slow endpoint could stall the whole pass
    (N tickers × the per-request timeout). A semaphore caps the in-flight burst
    so even a large unresolved backlog stays friendly to Kalshi's rate limits
    (fetch_market's own retry/backoff still applies per request)."""
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
    """The public tape, or None when the endpoint did not answer.

    None and [] mean different things and callers act on the difference: [] is
    "the tape genuinely has no prints", None is "we could not ask". Returning
    [] for a timeout made a dead provider look like a quiet market, and made
    the caller's own `if trades is None` guard dead code."""
    data = await _pub_get(f"{PUBLIC_BASE}/markets/trades", params={"limit": limit})
    if not isinstance(data, dict):
        return None
    return data.get("trades", []) or []


async def fetch_trades_for_market(ticker: str, limit: int = 100) -> list | None:
    """Recent public prints for ONE market. Returns None when the endpoint did
    not answer — distinct from `[]`, which means the market genuinely has no
    prints. The terminal renders those two very differently."""
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
    """One page of events. `with_nested_markets` is what makes /events usable
    as a discovery sweep: it returns each event's markets inline, so one
    request covers ~8 real markets instead of one, and the auto-generated
    multivariate parlay shards that dominate /markets never appear."""
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
    """Markets closing inside a time window, filtered SERVER-side.

    Verified honored (probe 2026-08-24), and it returns real listed markets
    rather than the multivariate parlay shards — which is why "closing soon"
    is a query here rather than a client-side rank over a sweep."""
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
    """One event plus (optionally) its markets — the sibling legs of the same
    question, which is what makes an entity page show a distribution instead of
    one leg of it."""
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
    """Working/resting orders for the signed account.

    Kalshi paginates this; we walk at most 5 pages. A truncated walk is
    reported by the CALLER as truncated rather than presented as "that's all
    your orders" — an order missing from a list the user cancels from is worse
    than a slow list."""
    if _routes_to_paper(pin_env):
        return await _paper().list_orders(status=status, ticker=ticker)
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
    """OHLC candles for one market. Returns None when NEITHER path answered —
    which the terminal renders as "no history available", never as an empty
    (i.e. flat) chart.

    Verified gotchas (research probes 2026-07-16, see
    python/data/research/kalshi-hist-2026-07/backfill_hist.py):
      * the endpoint 400s without BOTH start_ts and end_ts
      * the historical tier and the live tier live on different paths, and
        which one has a given market depends on Kalshi's rolling cutoff — so
        try both rather than guessing
      * price groups come back as {"close": "0.94"} on the historical tier and
        {"close_dollars": "0.9400"} on the live tier
    """
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


_WEB_HOST = "kalshi.com"


def web_exchange_indexes_url(env: str = "production") -> str:
    """Where a user actually moves collateral between exchange shards.

    Worth a named helper rather than a string inlined at each call site: every
    message about an unfunded shard has to end with somewhere to GO, and
    "move funds to that exchange on Kalshi" is not that. `env` is accepted
    for older callers; there is one Kalshi web host."""
    return f"https://{_WEB_HOST}/account/exchange-indexes"

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
    host = _WEB_HOST

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
    """Signed request with retries.

    `retry=False` for a NON-IDEMPOTENT write that carries no dedupe token of
    its own. Every retry below re-signs with a fresh timestamp, so Kalshi sees
    independent valid requests: if the first one was applied and only its
    RESPONSE was lost, retrying applies it again. `place_limit_order` is safe
    without this because it mints one `client_order_id` outside the loop;
    anything that cannot do that must not be retried at all.

    Env safety: the env is PINNED (to `pin_env` when given — read under
    ENV_LOCK by order placement — else to the env seen on the first attempt).
    If a credential test / env switch flips the global env at any point,
    attempts ABORT instead of silently signing for (and sending real money to)
    the other account. Signing + client fetch are back-to-back with no lock held
    across the HTTP call itself, so a slow request or its 429/backoff ladder can
    never wedge other callers (the old design held ENV_LOCK around whole calls —
    one hung balance poll blocked every order placement behind it).
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
    """Exchange status with the per-shard breakdown, or None if unreadable.

        {"exchangeActive": bool, "tradingActive": bool,   # shard 0 / overall
         "shards": {2: {"exchangeActive": bool, "tradingActive": bool,
                        "transfersActive": bool, "name": str}},
         "fetchedAt": float}

    None means we could not read it. That is UNKNOWN, and a caller must never
    treat it as "halted" — refusing to trade because a status endpoint blipped
    would be a worse failure than the one it is guarding against.
    """
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
    """Move collateral between exchange shards. Returns {transfer_id}.

    Kalshi allocates collateral per shard and does NOT rebalance for retail
    accounts (auto-rebalancing is an institutional feature), so cash sitting
    on the general shard cannot back a crypto order. This is the endpoint
    behind the "Move funds" button.

    Every rail is here rather than in the renderer, because this spends from
    a real balance and the renderer is assumed hostile.
    """
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
    """The last status read, without touching the network. None if never read.

    Exists so a SYNCHRONOUS caller (terminal.preview) is guarded by default
    rather than only when someone remembers to pass the status in. A guard a
    caller has to opt into is a guard that eventually gets missed."""
    return _status_cache["val"]

def shard_trading_halted(status: dict | None, index: int | None) -> Optional[str]:
    """The name of the halted engine hosting `index`, or None.

    None covers three different things on purpose — status unreadable, shard
    unknown, engine running — because all three mean "no reason to stop the
    user". Only an affirmative `trading_active: false` blocks anything.
    """
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
    """The engine hosting this ticker's series, or None if no market from it
    has been read yet this session.

    None means UNKNOWN and must never be treated as shard 0: defaulting an
    unknown series to the general engine would make a collateral check pass on
    the wrong shard's balance."""
    tk = (ticker or "").strip().upper()
    if not tk:
        return None
    return _series_shard.get(tk.split("-")[0])

def shard_name(index: int | None) -> str:
    if index is None:
        return "unknown"
    return SHARD_NAMES.get(int(index), f"shard {index}")


def _balance_breakdown(data: Any) -> dict[int, float]:
    """{exchange_index: dollars} from a /portfolio/balance response."""
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
    """Account balance, with the shard split folded in.

    Kalshi's `balance` field is now scoped to one exchange shard (0 unless
    asked otherwise). Callers here want the ACCOUNT's cash, so the response is
    augmented with:

      total_balance_cents  — every shard summed, or the scoped value when the
                             breakdown is absent (subaccount-restricted keys)
      shard_balances       — {index: dollars}, for showing WHERE the money is
      sharded              — whether a breakdown was present at all

    `balance` is left untouched so nothing that reads it changes meaning
    silently; the new key is the one to prefer.
    """
    if _routes_to_paper(pin_env):
        return await _paper().balance()
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


async def verify_saved_key() -> dict:
    """One signed balance read with the SAVED production key, sent to the
    hardcoded production host. Returns get_balance's shape or raises
    KalshiAPIError / a transport error.

    Only for the key test the user clicks (setup wizard, API Keys page). It
    deliberately bypasses _signed_request: that path signs with the GLOBAL
    env, which is "paper" while the user is still practising — and the test
    has to work then, because checking the key is the step before going live.
    Flipping the global env to production for the length of the test (what
    this used to do) would let every engine's ledger writes see "production"
    mid-flip. No retries: it is a yes/no question asked once, on a click.
    """
    from kalshi_auth import load_env_credentials, sign_headers_with
    api_key, key = load_env_credentials("production")
    base = _TRADE_BASES["production"]
    path = f"{PATH_PREFIX}/portfolio/balance"
    headers = sign_headers_with(api_key, key, "GET", path)
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(base_url=base, timeout=8.0) as c:
            resp = await c.get(path, headers=headers)
    except (httpx.TimeoutException, httpx.NetworkError) as e:
        note_call(_host_of(base), ok=False, ms=(time.monotonic() - t0) * 1000,
                  error=type(e).__name__)
        raise
    note_call(_host_of(base), ok=resp.status_code < 400,
              ms=(time.monotonic() - t0) * 1000,
              error="" if resp.status_code < 400 else f"HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception:
        body = resp.text
    if resp.status_code >= 400:
        raise KalshiAPIError(resp.status_code, body)
    if not isinstance(body, dict):
        raise KalshiAPIError(resp.status_code, {"error": "malformed balance"})
    shards = _balance_breakdown(body)
    if shards:
        total_cents = int(round(sum(shards.values()) * 100))
    else:
        try:
            total_cents = int(body.get("balance") or 0)
        except (TypeError, ValueError):
            total_cents = 0
    return {**body, "total_balance_cents": total_cents,
            "shard_balances": shards, "sharded": bool(shards)}


LOCATION_ATTESTATION_HELP = (
    "Kalshi needs you to confirm your location before it accepts orders from "
    "the API. Open the Kalshi app or kalshi.com, verify your location there, "
    "then send the order again. Nothing was placed.")


def rejection_text(err: Exception) -> str:
    """Kalshi's own words for a rejected request, not the HTTP dump around them.

    A KalshiAPIError stringifies as `HTTP 403: {'error': {'code': ..., 'message':
    ...}}` — a Python dict repr, which is what the real-key smoke test of 6.4.0
    put in front of the user. Kalshi's `message` is written for people; use it.
    Location attestation gets its own sentence: it is an account step on
    Kalshi's side that no setting in this app can satisfy, and a user who
    reads "403" goes looking for a broken key instead.
    """
    if not isinstance(err, KalshiAPIError):
        return str(err)
    body = err.body
    inner = body.get("error") if isinstance(body, dict) else None
    code = msg = ""
    if isinstance(inner, dict):
        code = str(inner.get("code") or "")
        msg = str(inner.get("message") or "")
    elif isinstance(inner, str):
        msg = inner
    if "location" in f"{code} {msg}".lower() and "attest" in f"{code} {msg}".lower():
        return LOCATION_ATTESTATION_HELP
    msg = msg.strip()
    if msg:
        return msg if msg.endswith((".", "!", "?")) else msg + "."
    return f"HTTP {err.status}" + (f" ({code})" if code else "")


def is_user_not_found(err: Exception) -> bool:
    """Kalshi's `user_not_found: <member uuid>` rejection.

    Reported by a beta user on 2026-08-25 against a BTC 15m entry — a crypto
    market, which lives on shard 2. The message names a UUID and nothing else,
    so on its own it tells the user nothing they can act on.
    """
    if not isinstance(err, KalshiAPIError):
        return False
    return "user_not_found" in str(err.body) or "user not found" in str(err.body)


async def explain_order_rejection(err: Exception, *, ticker: str = "",
                                  exchange_index: int | None = None) -> str:
    """Turn an opaque order rejection into something the user can act on.

    `user_not_found` has two very different causes and the message is the same
    for both, so this DISTINGUISHES them instead of guessing: it re-reads the
    balance, which is signed with the same credential but is not scoped to the
    market's matching engine.

      * balance reads fine  -> the credential is valid and the account exists.
        The engine hosting this market does not know it, which is what an
        unfunded shard looks like: Kalshi preallocates collateral per shard,
        and an account whose cash all sits on shard 0 cannot open a position
        on shard 2.
      * balance fails the same way -> the credential itself no longer matches
        any account: a key deleted or rotated on Kalshi.

    Always returns a string; never raises. A diagnosis that can itself throw
    inside an error handler is worse than no diagnosis.
    """
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
                f"most likely deleted or rotated on Kalshi. Make a new one on "
                f"kalshi.com and re-add it under API Keys."
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
    """Current API usage tier + rate-limit buckets + grants. Response:
    {usage_tier, read:{refill_rate,bucket_capacity}, write:{...}, grants:[...]}.
    Cheap read used to decide whether an upgrade is needed."""
    return await _signed_request("GET", "/account/limits", pin_env=pin_env)


async def upgrade_api_usage_level(pin_env: str | None = None) -> dict:
    """Grant this account the Advanced API usage level (3x write throughput).
    201 on success/refresh. Raises KalshiAPIError(403) when no API-created order
    is in the last 100 Predictions orders (the eligibility gate) — callers treat
    403 as 'retry after the first order', not a hard failure."""
    return await _signed_request("POST", "/account/api_usage_level/upgrade", pin_env=pin_env)


_POSITIONS_MAX_PAGES = 25


async def get_positions(
    limit: int = 200, *, settlement_status: str | None = None,
    paginate: bool = True, pin_env: str | None = None,
) -> list[dict]:
    _check_scope(pin_env)
    if _routes_to_paper():
        return await _paper().positions(settlement_status=settlement_status)
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
    if _routes_to_paper():
        return await _paper().positions(settlement_status="settled")
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
    """pin_env: sign against a SPECIFIC env regardless of the active one —
    needed when managing a position that belongs to the non-active env (the
    cross-env settlement sweep), where signing with the active env 404s the
    other env's order forever."""
    if _routes_to_paper(pin_env):
        return await _paper().get_order(order_id)
    return await _signed_request(
        "GET", f"/portfolio/orders/{order_id}", timeout=HOT_TIMEOUT,
        pin_env=pin_env,
    )


async def find_order_by_client_id(
    client_order_id: str, *, ticker: str = "", limit: int = 200,
    pin_env: str | None = None,
) -> dict | None:
    """Look an order up by our client_order_id. Used after a POST whose
    response was lost (timeout / dropped connection): the order may be live on
    Kalshi even though place_limit_order raised, and booking it as 'error'
    would leave an untracked real-money position. Returns the order dict or
    None when no order with that client id exists.

    Pass pin_env=<env the order was placed under> so an env switch mid-lookup
    aborts (env_changed) instead of silently querying the OTHER account —
    a miss there says nothing about whether this order is live."""
    if _routes_to_paper(pin_env):
        return await _paper().find_by_client_id(client_order_id)
    params: dict = {"limit": int(limit)}
    if ticker:
        params["ticker"] = ticker
    data = await _signed_request("GET", "/portfolio/orders", params=params, pin_env=pin_env)
    orders = (data.get("orders") if isinstance(data, dict) else data) or []
    for o in orders:
        if isinstance(o, dict) and str(o.get("client_order_id") or "") == str(client_order_id):
            return o
    return None


async def get_fills_for_order(order_id: str, limit: int = 200, *,
                              pin_env: str | None = None) -> list[dict]:
    _check_scope(pin_env)
    if _routes_to_paper():
        return await _paper().fills(order_id=order_id)
    out: list[dict] = []
    cursor: Optional[str] = None
    pages = 0
    while True:
        params: dict = {"order_id": order_id, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        try:
            data = await _signed_request("GET", "/portfolio/fills", params=params,
                                         pin_env=pin_env)
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
    if _routes_to_paper():
        return await _paper().fills(min_ts=int(after_ts_unix))
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


async def read_orderbook(ticker: str) -> Optional[dict]:
    """The order book, or None when NO book could be read at all.

    get_orderbook() answers an unreadable book as an empty one, which its
    callers (signals, exits) treat as "nothing to trade against" — harmless
    there. The paper exchange cannot: it compares each read with the depth it
    last saw, so one failed read standing in as an empty book reset that
    memory, and the next good read "refilled" the same offer and filled the
    order twice."""
    wb = kalshi_ws.orderbook(ticker)
    if wb is not None and (wb["yes"] or wb["no"]):
        return wb
    if not _routes_to_paper():
        try:
            book = _normalize_orderbook(await _signed_request(
                "GET", f"/markets/{ticker}/orderbook", timeout=HOT_TIMEOUT,
            ))
            if book["yes"] or book["no"]:
                return book
        except Exception:
            pass
    raw = await _pub_get(f"{PUBLIC_BASE}/markets/{ticker}/orderbook")
    if not isinstance(raw, dict):
        return None
    return _normalize_orderbook(raw)


async def get_orderbook(ticker: str) -> dict:
    book = await read_orderbook(ticker)
    return book if book is not None else {"yes": [], "no": []}


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
    pin_env: Optional[str] = None,
) -> dict:
    """`pin_env`: the scope (paper | production) the caller decided and booked
    this order under. If the app has switched since, the order is refused
    before it is routed or signed (409 scope_changed — not delivered)."""
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
    if pin_env is not None and pin_env != env0:
        raise _scope_changed_error(pin_env, env0)
    if env0 == PAPER:
        return await _paper().place_order(
            ticker=ticker, side=side, action=action, count=int(count),
            price_cents=price_cents, client_order_id=body["client_order_id"],
        )
    shard_note = None
    if action == "buy":
        import shard_rail
        shard_note = await shard_rail.ensure_collateral(
            ticker=ticker, count=int(count), price_cents=price_cents, env=env0)
    res = await _signed_request(
        "POST", ORDERS_V2_PATH, json=body, timeout=HOT_TIMEOUT, pin_env=env0,
    )
    if shard_note and isinstance(res, dict):
        res["krypt_shard_note"] = shard_note
    return res


async def cancel_order(order_id: str, *, ticker: str | None = None,
                       pin_env: str | None = None) -> dict:
    """Cancel a resting order. Pass its `ticker` whenever you have it.

    The v2 cancel is routed per exchange shard and DEFAULTS TO SHARD 0: an
    order on the crypto shard, cancelled by id alone, comes back 404
    "not found" while it keeps resting. Orders are placed with
    exchange_index -1 (auto-route by ticker), so the cancel says the same —
    -1 plus the market ticker. Found by the real-key test of the shard rail."""
    if pin_env is None:
        async with ENV_LOCK:
            pin_env = get_env()
    if pin_env == PAPER:
        return await _paper().cancel_order(order_id)
    tk = (ticker or "").strip().upper()
    params = {"exchange_index": -1, "market_ticker": tk} if tk else None
    return await _signed_request(
        "DELETE", f"{ORDERS_V2_PATH}/{order_id}", params=params,
        timeout=HOT_TIMEOUT, pin_env=pin_env,
    )
