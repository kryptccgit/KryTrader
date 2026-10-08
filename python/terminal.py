"""Krypt Terminal — the manual half of the app.

The bot answers "should I act, right now, on this one thing I am watching?".
The terminal answers "what is going on, and what should I do about it?" — for
ANY market the user names, not just the ones a scanner happened to observe.

Three rules govern everything in this module:

1. **A value nobody could produce is None.**  It is never coerced to 0, to a
   default, or to a "safe" assumption. Kalshi's REST shapes make this a live
   hazard rather than a style point: ``yes_bid: 0`` means the book side is
   EMPTY (quotes live in 1..99), ``yes_ask: 100`` likewise, and
   ``last_price: 0`` means the market has never traded. Coerced to numbers,
   each of those is a specific, confident lie a user would trade on.

2. **Per-field provenance.**  Every assembled row carries which source produced
   which number — our own websocket, a REST read this second, or a cached one.
   A terminal that shows a price without saying where it came from is asking
   for trust, which is exactly what it is trying not to require.

3. **A cost budget.**  A bot makes a handful of requests; a terminal polls
   four columns, a chart, a book and a portfolio forever. Everything public
   goes through a per-host serial gate with a minimum gap and a 429 park, and
   everything is TTL-cached at a horizon tuned to how fast that data actually
   changes.

Nothing here accepts a URL or a host from its caller. The renderer names an
ENTITY (a ticker), a COLUMN, an INTERVAL; this module decides which of
kalshi_api's hardcoded hosts to contact. That is the structural fix for SSRF —
a URL validator in the middle would be the fragile one.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import secrets
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

import backtest as _bt
import kalshi_api
import kalshi_auth
import kalshi_ws

logger = logging.getLogger("terminal")


SWEEP_TTL = 45.0
MARKET_TTL = 6.0
BOOK_TTL = 2.0
CANDLE_TTL = 20.0
TAPE_TTL = 5.0
SERIES_TTL = 900.0
EVENT_TTL = 60.0
PORTFOLIO_TTL = 5.0

SWEEP_MAX_PAGES = 12

MIN_GAP_PUBLIC = 0.12
PARK_AFTER_FAILS = 3
PARK_BASE_SEC = 8.0
PARK_MAX_SEC = 120.0

WS_SUBSCRIPTION_TTL = 150.0

MIN_RESOLVED_CHECKS = 4

MIN_CALIBRATION_TRADES = 5

MANUAL_ORDER_PREFIX = "krypt-term-"

SOURCED_FIELDS = (
    "yesBid", "yesAsk", "lastPrice", "volume", "volume24h",
    "openInterest", "liquidity", "status",
)


class ProviderParked(Exception):
    """The public API is in 429 backoff. Raised INSTEAD of queueing, so a burst
    of doomed low-value calls cannot starve a high-value one behind them — the
    failure mode that once blanked the chart while a plain curl to the same
    endpoint returned 200."""



def price_cents(v: Any) -> Optional[float]:
    """A Kalshi price in cents, or None when there is no price.

    Only the SENTINELS are absent — 0, 100, None, "", a non-number. They mean
    ABSENT, not "cheap" and not "expensive":

      * ``yes_bid == 0``    → nobody is bidding for YES
      * ``yes_ask == 100``  → nobody is offering YES (yes_ask = 100 - no_bid,
                              and no_bid == 0 means the NO side is empty)
      * ``last_price == 0`` → this market has never traded

    Deci-cent series (the tapered 15m crypto books) keep their 0.1c
    resolution; whole-cent markets come back as x.0.

    The bound used to be 1..99, which threw away REAL levels: the tapered
    series tick in 0.1c below 10c and above 90c, so 99.4c and 0.6c are valid
    quotes — kalshi_api.place_limit_order accepts 0.1..99.9 as tick-valid, and
    the repo's own recorded history (300,441 15m-crypto candles) has 6.7% of
    candles closing with a top of book inside the discarded band. The effect
    was not a missing number but a WRONG one: with bids at 99.4/99.2/98.0 the
    first two were dropped and 98.0 was reported as the best bid, so a stop
    armed "below 99" sold into a bid that did not exist.
    """
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    f = round(f, 1)
    if f <= 0.0 or f >= 100.0:
        return None
    return f


def _count(v: Any) -> Optional[int]:
    """A contract count. Unlike a price, 0 IS a real value here — a market can
    genuinely have traded nothing. Only a missing/unreadable field is None."""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or f < 0:
        return None
    return int(round(f))


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _dollar_price(v: Any) -> Optional[float]:
    """Kalshi's current wire format quotes DOLLAR strings — ``"0.9400"`` is
    94c, ``"0.0000"`` is an empty book side. Same 1..99 honesty rule as
    `price_cents`, applied after the conversion."""
    n = _num(v)
    if n is None:
        return None
    return price_cents(round(n * 100.0, 1))


def _text(v: Any) -> Optional[str]:
    if not isinstance(v, str):
        return None
    s = v.strip()
    return s or None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_iso(v: Any) -> Optional[datetime]:
    s = _text(v)
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _iso(v: Any) -> Optional[str]:
    dt = _parse_iso(v)
    return dt.isoformat(timespec="seconds").replace("+00:00", "Z") if dt else None


def _minutes_until(v: Any) -> Optional[float]:
    dt = _parse_iso(v)
    if dt is None:
        return None
    return round((dt - datetime.now(timezone.utc)).total_seconds() / 60.0, 1)



class _HostGate:
    """Serial queue for one host, with a minimum gap between requests and a
    park on repeated failure.

    Not a global limiter — per host, so a slow public sweep never delays a
    signed portfolio read.
    """

    def __init__(self, min_gap: float) -> None:
        self._lock = asyncio.Lock()
        self._min_gap = min_gap
        self._last = 0.0
        self._parked_until = 0.0
        self._fails = 0

    def parked_sec(self) -> float:
        return max(0.0, self._parked_until - time.monotonic())

    def note_ok(self) -> None:
        self._fails = 0
        self._parked_until = 0.0

    def note_fail(self) -> None:
        self._fails += 1
        if self._fails >= PARK_AFTER_FAILS:
            over = self._fails - PARK_AFTER_FAILS
            wait = min(PARK_MAX_SEC, PARK_BASE_SEC * (2 ** over))
            self._parked_until = time.monotonic() + wait
            logger.info(
                "terminal: public API parked for %.0fs after %d consecutive "
                "failures", wait, self._fails,
            )

    async def run(self, fn, *args, **kwargs):
        """Fail fast while parked — WITHOUT taking the lock, so doomed calls do
        not hold the queue."""
        parked = self.parked_sec()
        if parked > 0:
            raise ProviderParked(
                f"Kalshi's public API is rate-limiting us; backing off for "
                f"{parked:.0f}s more. Nothing is broken — this clears itself."
            )
        async with self._lock:
            gap = self._min_gap - (time.monotonic() - self._last)
            if gap > 0:
                await asyncio.sleep(gap)
            try:
                out = await fn(*args, **kwargs)
            except Exception:
                self.note_fail()
                raise
            finally:
                self._last = time.monotonic()
        if out is None:
            self.note_fail()
        else:
            self.note_ok()
        return out


_public_gate = _HostGate(MIN_GAP_PUBLIC)


class _TTLCache:
    def __init__(self) -> None:
        self._d: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, ttl: float) -> tuple[Any, float] | None:
        hit = self._d.get(key)
        if hit is None:
            return None
        at, val = hit
        age = time.monotonic() - at
        if age > ttl:
            return None
        return val, age

    def put(self, key: str, val: Any) -> Any:
        if len(self._d) > 4000:
            self._d.clear()
        self._d[key] = (time.monotonic(), val)
        return val

    def drop(self, key: str) -> None:
        self._d.pop(key, None)

    def clear(self) -> None:
        self._d.clear()


_cache = _TTLCache()


_ws_interest: dict[str, float] = {}


def note_interest(ticker: str) -> None:
    t = (ticker or "").strip().upper()
    if t:
        _ws_interest[t] = time.monotonic()


def subscribed_tickers() -> set[str]:
    """Tickers the terminal currently wants on the websocket. service.py unions
    this into the main loop's subscription set every pass."""
    now = time.monotonic()
    dead = [t for t, at in _ws_interest.items() if now - at > WS_SUBSCRIPTION_TTL]
    for t in dead:
        _ws_interest.pop(t, None)
    return set(_ws_interest)



def _spread_mid(bid: Optional[float], ask: Optional[float]) -> tuple[Optional[float], Optional[float]]:
    """A one-sided book has no spread — it has an UNKNOWN one. Both or
    neither."""
    if bid is None or ask is None:
        return None, None
    return round(ask - bid, 1), round((ask + bid) / 2.0, 1)


def market_row(m: dict, source: str = "kalshi-rest",
               ctx: Optional[dict] = None) -> dict:
    """One Kalshi market record → the terminal's MarketSummary shape.

    Kalshi quotes DOLLAR strings (``yes_bid_dollars: "0.9400"``) and fixed-point
    counts (``volume_fp: "345.67"``). The legacy cent integers (``yes_bid: 94``)
    are GONE — re-probed 2026-08-25, production no longer returns them —
    so the legacy reads below are a fallback for old
    recorded data, not a live path. Reading only the legacy names produced a
    universe of markets with no prices and no volume that still rendered without
    error, which is why every count and price here is read both ways.

    `ctx` carries what the market record itself does not have: category,
    series and mutual-exclusivity all live on the parent EVENT.
    """
    ctx = ctx or {}
    yes_bid = price_cents(m.get("yes_bid")) or _dollar_price(m.get("yes_bid_dollars"))
    yes_ask = price_cents(m.get("yes_ask")) or _dollar_price(m.get("yes_ask_dollars"))
    no_bid = price_cents(m.get("no_bid")) or _dollar_price(m.get("no_bid_dollars"))
    no_ask = price_cents(m.get("no_ask")) or _dollar_price(m.get("no_ask_dollars"))
    last = price_cents(m.get("last_price")) or _dollar_price(m.get("last_price_dollars"))
    prev = price_cents(m.get("previous_price")) or _dollar_price(m.get("previous_price_dollars"))

    if no_bid is None and yes_ask is not None:
        no_bid = price_cents(100 - yes_ask)
    if no_ask is None and yes_bid is not None:
        no_ask = price_cents(100 - yes_bid)
    if yes_ask is None and no_bid is not None:
        yes_ask = price_cents(100 - no_bid)
    if yes_bid is None and no_ask is not None:
        yes_bid = price_cents(100 - no_ask)

    spread, mid = _spread_mid(yes_bid, yes_ask)

    def _cnt(*keys: str) -> Optional[int]:
        for k in keys:
            v = _count(m.get(k))
            if v is not None:
                return v
        return None

    volume = _cnt("volume", "volume_fp")
    volume24 = _cnt("volume_24h", "volume_24h_fp")
    oi = _cnt("open_interest", "open_interest_fp")
    liq = _num(m.get("liquidity_dollars"))
    if liq is None:
        liq_cents = _num(m.get("liquidity"))
        liq = liq_cents / 100.0 if liq_cents is not None else None

    settle_c = _num(m.get("settlement_value"))
    if settle_c is None:
        settle_d = _num(m.get("settlement_value_dollars"))
        settle_c = settle_d * 100.0 if settle_d is not None else None

    ticker = _text(m.get("ticker")) or ""
    sources: dict[str, str] = {}
    for field, val in (
        ("yesBid", yes_bid), ("yesAsk", yes_ask), ("lastPrice", last),
        ("volume", volume), ("volume24h", volume24), ("openInterest", oi),
        ("liquidity", liq), ("status", _text(m.get("status"))),
    ):
        if val is not None:
            sources[field] = source

    return {
        "ticker": ticker,
        "eventTicker": _text(m.get("event_ticker")) or _text(ctx.get("eventTicker")),
        "seriesTicker": (
            _text(m.get("series_ticker")) or _text(ctx.get("seriesTicker"))
            or (ticker.split("-")[0] if ticker else None)
        ),
        "title": _text(m.get("title")) or ticker,
        "yesSubTitle": _text(m.get("yes_sub_title")),
        "category": _text(m.get("category")) or _text(ctx.get("category")),
        "status": _text(m.get("status")),
        "openTime": _iso(m.get("open_time")),
        "closeTime": _iso(m.get("close_time")),
        "expirationTime": _iso(m.get("expiration_time")) or _iso(m.get("latest_expiration_time")),
        "yesBid": yes_bid,
        "yesAsk": yes_ask,
        "noBid": no_bid,
        "noAsk": no_ask,
        "yesBidSize": _cnt("yes_bid_size", "yes_bid_size_fp"),
        "yesAskSize": _cnt("yes_ask_size", "yes_ask_size_fp"),
        "lastPrice": last,
        "previousPrice": prev,
        "spreadCents": spread,
        "midCents": mid,
        "volume": volume,
        "volume24h": volume24,
        "openInterest": oi,
        "liquidityUsd": liq,
        "result": _text(m.get("result")),
        "settlementValue": settle_c,
        "exchangeIndex": _count(m.get("exchange_index")),
        "canCloseEarly": m.get("can_close_early") if isinstance(m.get("can_close_early"), bool) else None,
        "minutesToClose": _minutes_until(m.get("close_time")),
        "sources": sources,
        "observedAt": _now_iso(),
    }


def _copy_row(r: dict) -> dict:
    """A row copy whose `sources` is also a copy.

    The sweep cache hands out the same row objects for 45s, so anything that
    mutates provenance has to own its own dict or it edits the cache."""
    out = dict(r)
    src = out.get("sources")
    if isinstance(src, dict):
        out["sources"] = dict(src)
    return out


def _apply_live_quote(row: dict) -> dict:
    """Overlay our OWN websocket quote when we have one, and say so.

    Priority is the guide's: our own authoritative read, then our own live feed,
    then the best third party, then None. A provider that has nothing to say
    must never erase one that does — so this patches field by field rather than
    spreading one dict over another.
    """
    q = kalshi_ws.ticker_quote(row.get("ticker") or "")
    if not q:
        return row
    bid = price_cents(q.get("yes_bid_cents"))
    ask = price_cents(q.get("yes_ask_cents"))
    last = price_cents(q.get("last_cents"))
    if bid is not None:
        row["yesBid"] = bid
        row["noAsk"] = price_cents(100 - bid)
        row["sources"]["yesBid"] = "kalshi-ws"
    if ask is not None:
        row["yesAsk"] = ask
        row["noBid"] = price_cents(100 - ask)
        row["sources"]["yesAsk"] = "kalshi-ws"
    if last is not None:
        row["lastPrice"] = last
        row["sources"]["lastPrice"] = "kalshi-ws"
    if bid is not None or ask is not None:
        row["spreadCents"], row["midCents"] = _spread_mid(row["yesBid"], row["yesAsk"])
    vol = _count(q.get("volume"))
    if vol is not None:
        row["volume"] = vol
        row["sources"]["volume"] = "kalshi-ws"
    oi = _count(q.get("open_interest"))
    if oi is not None:
        row["openInterest"] = oi
        row["sources"]["openInterest"] = "kalshi-ws"
    row["observedAt"] = _now_iso()
    return row


def _apply_book_quote(row: dict, book: Optional[dict]) -> tuple[dict, Optional[float]]:
    """Overlay the ORDER BOOK's top of book onto a market row, and report how
    far the two disagreed.

    The market record and the order book are separate reads. On a slow market
    they agree exactly (measured: 0.0c drift across every market with more than
    a day to run). On a 15-minute crypto market seconds from settlement they
    routinely differ by 6-7c — which is real movement, not an error, but it
    put three different asks on one screen: the header's, the ladder's, and the
    ticket's.

    The book wins, because it is both the more granular read (deci-cent levels,
    and the live websocket book when this market is subscribed) and the thing
    an order actually executes against. The drift is returned rather than
    swallowed, so the page can say "this market is moving faster than one page
    load" instead of leaving the user to notice two numbers and guess.
    """
    if not book:
        return row, None
    bid, ask = book.get("yesBid"), book.get("yesAsk")
    if bid is None and ask is None:
        return row, None

    drifts = [
        abs(a - b) for a, b in (
            (row.get("yesBid"), bid), (row.get("yesAsk"), ask),
        ) if a is not None and b is not None
    ]
    src = book.get("source") or "kalshi-rest"
    if bid is not None:
        row["yesBid"] = bid
        row["noAsk"] = price_cents(100 - bid)
        row["sources"]["yesBid"] = src
    if ask is not None:
        row["yesAsk"] = ask
        row["noBid"] = price_cents(100 - ask)
        row["sources"]["yesAsk"] = src
    row["spreadCents"], row["midCents"] = _spread_mid(row["yesBid"], row["yesAsk"])
    row["observedAt"] = book.get("observedAt") or _now_iso()
    return row, (round(max(drifts), 1) if drifts else None)



async def _sweep(refresh: bool = False) -> dict:
    """The open universe, cached — swept over EVENTS, not markets.

    ``/markets?status=open`` is not the listing view any more. Measured
    2026-08-24, 7,999 of the first 8,000 rows were auto-generated multivariate
    "parlay shard" markets (``KXMVECROSSCATEGORY-…``) with no volume and no
    real event page, and the cursor was still going. Any ranking over that list
    ranks combinatorial noise, and — worse — it *looks* like it worked.

    ``/events?with_nested_markets=true`` is the real listing view: it returns
    none of the shards, carries the category / series / mutual-exclusivity that
    a market record does not have, and covers ~8 markets per row, so ~20,000
    real markets arrive in about 3 seconds.
    """
    if not refresh:
        hit = _cache.get("sweep", SWEEP_TTL)
        if hit:
            val, age = hit
            return {**val, "ageSec": round(age, 1)}

    events: list[dict] = []
    rows: list[dict] = []
    cursor = ""
    truncated = False
    for page in range(SWEEP_MAX_PAGES):
        page_out = await _public_gate.run(
            kalshi_api.fetch_events, "open", 200, cursor, True,
        )
        if page_out is None:
            if rows:
                truncated = True
                break
            raise RuntimeError(
                "Kalshi's events endpoint did not answer, so the market list "
                "could not be built. Nothing is shown rather than an empty "
                "list that would look like an empty exchange."
            )
        chunk, cursor = page_out
        if not chunk:
            break
        for ev in chunk:
            ctx = {
                "category": _text(ev.get("category")),
                "seriesTicker": _text(ev.get("series_ticker")),
                "eventTicker": _text(ev.get("event_ticker")),
            }
            events.append(ev)
            for m in (ev.get("markets") or []):
                rows.append(market_row(m, ctx=ctx))
        if not cursor:
            break
        if page == SWEEP_MAX_PAGES - 1 and cursor:
            truncated = True

    out = {
        "markets": rows,
        "eventCount": len(events),
        "categories": sorted({
            c for c in (r.get("category") for r in rows) if c
        }),
        "truncated": truncated,
        "fetchedAt": _now_iso(),
    }
    _cache.put("sweep", out)
    return {**out, "ageSec": 0.0}


def apply_filters(rows: list[dict], f: Optional[dict]) -> tuple[list[dict], int, int]:
    """Filter a row set. Returns (kept, skipped, excluded).

    The asymmetry here is deliberate and is the honest-null rule applied to
    filtering:

      * A NUMERIC filter ("volume ≥ 500", "closing within 6h") is a threshold on
        a quantity. If that quantity has not arrived for a row, the threshold
        has not been evaluated — so the row is SKIPPED and counted, and the UI
        says how many. It is not a low score; it is an unmeasured one.

      * A CATEGORICAL filter ("category = Politics") is the user naming a set.
        "I don't know" is not a member of that set, so a row with no category is
        EXCLUDED — a definite non-match, not an unmeasured one, and not counted
        as skipped.

    Both behaviours are pinned by tests, because the difference is exactly the
    kind of thing a later refactor flattens into one branch.
    """
    if not f:
        return rows, 0, 0

    cats = {c.lower() for c in (f.get("categories") or []) if c}
    min_price = _num(f.get("minPriceCents"))
    max_price = _num(f.get("maxPriceCents"))
    min_volume = _count(f.get("minVolume"))
    max_hours = _num(f.get("maxHoursToClose"))

    kept: list[dict] = []
    skipped = 0
    excluded = 0
    for r in rows:
        if cats:
            cat = (r.get("category") or "").lower()
            if not cat or cat not in cats:
                excluded += 1
                continue

        if min_price is not None or max_price is not None:
            mid = r.get("midCents")
            if mid is None:
                skipped += 1
                continue
            if min_price is not None and mid < min_price:
                continue
            if max_price is not None and mid > max_price:
                continue

        if min_volume is not None:
            vol = r.get("volume")
            if vol is None:
                skipped += 1
                continue
            if vol < min_volume:
                continue

        if max_hours is not None:
            mins = r.get("minutesToClose")
            if mins is None:
                skipped += 1
                continue
            if mins > max_hours * 60 or mins <= 0:
                continue

        kept.append(r)
    return kept, skipped, excluded


def _filter_note(skipped: int, excluded: int) -> str:
    bits = []
    if skipped:
        bits.append(
            f"{skipped:,} market(s) skipped by the numeric filters: the value "
            f"being compared had not arrived for them, so the comparison never "
            f"happened. They are unmeasured, not low."
        )
    if excluded:
        bits.append(
            f"{excluded:,} excluded by the category filter (including any with "
            f"no category — an unknown category is not a member of a set you "
            f"named)."
        )
    return " ".join(bits)


EVENT_CAP = 3


def _cap_per_event(rows: list[dict], cap: int) -> tuple[list[dict], int]:
    """Keep at most `cap` markets from any one event, preserving order.

    `KXNASDAQ100U-26AUG25H1400` is not a market, it is ~400 rungs of one
    ladder that share a title, a close time and an auto-quoter. Ranked by
    anything those rungs tie on — and every rung closes at the same instant —
    a single event fills the column and every other event in the window
    becomes unreachable. Measured 2026-08-25: 774 of the 999 markets closing
    within 6h were rungs of just two NASDAQ-100 ladders, and all 60 rows this
    column returned came from one of them.

    A row with no event ticker is NOT collapsed with other such rows: an
    unknown event is not evidence that two markets share one. Each falls back
    to its own ticker and is kept.
    """
    seen: dict[tuple, int] = {}
    kept: list[dict] = []
    collapsed = 0
    for r in rows:
        ev = _text(r.get("eventTicker"))
        key = ("event", ev) if ev else ("ticker", r.get("ticker"))
        n = seen.get(key, 0)
        if n >= cap:
            collapsed += 1
            continue
        seen[key] = n + 1
        kept.append(r)
    return kept, collapsed


def _actionable_before_close(r: dict) -> bool:
    """Is there something a user could actually DO about this market?

    A two-sided book means yes: a price to buy at and a price to sell into.

    A one-sided book usually does not, and on a strike ladder it is an
    artifact rather than an offer. A market maker quotes every rung, so a deep
    out-of-the-money rung carries `no_bid: 0.99` — which `market_row` mirrors
    into a 1c YES ask — while nobody has ever traded it and nobody holds it.
    The old test here was "is EITHER side quoted", and that 1c phantom passed
    it, which is how this column came to show 60 untraded ladder rungs.

    So a one-sided market has to earn its place with evidence that it is real:
    somebody has traded it, or somebody is holding it. A `volume` or
    `openInterest` of None is UNKNOWN — it is not that evidence, but it is not
    held against the market either; it simply is not a reason to include it.
    """
    if r.get("yesBid") is not None and r.get("yesAsk") is not None:
        return True
    vol = r.get("volume")
    oi = r.get("openInterest")
    return (vol is not None and vol > 0) or (oi is not None and oi > 0)

def _rank(rows: list[dict], column: str,
          limit: int) -> tuple[list[dict], int, dict]:
    """Rank a sweep for one column, returning (rows, skipped, dropped).

    Numeric columns SKIP rows whose metric has not arrived — a threshold on a
    quantity nobody has produced yet is not a judgement about that row, so it is
    left out of the ranking and counted, not silently sorted to the bottom as if
    it were a zero.

    `dropped` counts the two things removed AFTER a row was judged rankable, so
    the caller can say so rather than silently returning a short column:
    `untradeable` (closing only) and `collapsed` (the per-event cap).
    """
    skipped = 0
    untradeable = 0
    keyed: list[tuple[float, dict]] = []
    for r in rows:
        if column == "volume":
            v = r.get("volume")
            if v is None:
                skipped += 1
                continue
            if v <= 0:
                continue
            keyed.append((-float(v), r))
        elif column == "closing":
            mins = r.get("minutesToClose")
            if mins is None:
                skipped += 1
                continue
            if mins <= 0:
                continue
            if not _actionable_before_close(r):
                untradeable += 1
                continue
            keyed.append((float(mins), r))
        elif column == "new":
            dt = _parse_iso(r.get("openTime"))
            if dt is None:
                skipped += 1
                continue
            keyed.append((-dt.timestamp(), r))
        else:
            keyed.append((0.0, r))
    keyed.sort(key=lambda kv: kv[0])
    ranked, collapsed = _cap_per_event([r for _, r in keyed], EVENT_CAP)
    return ranked[:limit], skipped, {"untradeable": untradeable,
                                     "collapsed": collapsed}


async def _trending(limit: int) -> dict:
    """Rank by what is ACTUALLY trading right now, from the public tape.

    Not by a `volume_24h` field: a 24h counter makes this morning's finished
    event look as busy as the market printing trades this second, and it is the
    field most likely to be stale or absent. One request to the tape gives real
    activity, we aggregate the notional ourselves, and then we price only the
    handful of tickers that won — computing the metric rather than trusting a
    sort we did not define.
    """
    trades = await _public_gate.run(kalshi_api.fetch_recent_trades, 1000)
    if trades is None:
        raise RuntimeError("Kalshi's public trade tape did not answer.")

    notional: dict[str, float] = {}
    counts: dict[str, int] = {}
    oldest = None
    for t in trades:
        tk = _text(t.get("ticker"))
        if not tk or tk.startswith("KXMVE"):
            continue
        n = _count(t.get("count")) or _count(t.get("count_fp"))
        px = price_cents(t.get("yes_price")) or _dollar_price(t.get("yes_price_dollars"))
        if n is None or px is None:
            continue
        notional[tk] = notional.get(tk, 0.0) + n * px / 100.0
        counts[tk] = counts.get(tk, 0) + 1
        ts = _parse_iso(t.get("created_time"))
        if ts and (oldest is None or ts < oldest):
            oldest = ts

    top = sorted(notional, key=lambda k: -notional[k])[:min(limit * 2, 150)]
    if not top:
        return {
            "column": "trending", "rows": [], "scanned": len(trades),
            "truncated": False,
            "note": "Kalshi's public tape had no non-parlay prints in its last page.",
            "fetchedAt": _now_iso(), "ageSec": 0.0,
        }

    found = await _public_gate.run(kalshi_api.fetch_markets_by_tickers, top) or {}
    priced = [_apply_live_quote(market_row(found[t])) for t in top if t in found]
    rows, collapsed = _cap_per_event(priced, EVENT_CAP)
    rows = rows[:limit]

    window = ""
    if oldest:
        secs = max(0.0, (datetime.now(timezone.utc) - oldest).total_seconds())
        window = (
            f" spanning the last {secs:.0f}s" if secs < 90
            else f" spanning the last {secs / 60:.0f} minutes"
        )
    missing = len(top) - len(priced)
    note = (
        f"Ranked by traded notional across Kalshi's most recent "
        f"{len(trades):,} public prints{window} — real activity, not a 24h "
        f"counter. {len(notional):,} markets printed in that window."
    )
    if missing:
        note += (
            f" {missing} of the top tickers could not be priced and are "
            f"omitted — they trade but are not in the open-events sweep, "
            f"usually because they have just settled."
        )
    if collapsed:
        note += (
            f" {collapsed:,} sibling market(s) hidden so that no single event "
            f"can fill the column — open an event to see every strike."
        )
    return {
        "column": "trending", "rows": rows, "scanned": len(trades),
        "truncated": False, "note": note, "fetchedAt": _now_iso(), "ageSec": 0.0,
    }


async def _closing(limit: int) -> dict:
    """Server-side window query. Kalshi honours max_close_ts/min_close_ts
    (verified 2026-08-24) and the filtered result is free of parlay shards, so
    this is a query rather than a rank over a sweep."""
    now = int(time.time())
    horizon_h = 6
    raw: list = []
    ranked: list = []
    skipped = 0
    dropped: dict = {"untradeable": 0, "collapsed": 0}
    for horizon_h in (6, 24, 72):
        raw = await _public_gate.run(
            kalshi_api.fetch_markets_closing_before, now + horizon_h * 3600, now, 1000,
        )
        if raw is None:
            raise RuntimeError("Kalshi did not answer the closing-soon query.")
        rows = [market_row(m) for m in raw
                if not (_text(m.get("ticker")) or "").startswith("KXMVE")]
        ranked, skipped, dropped = _rank(rows, "closing", limit)
        if len(ranked) >= limit:
            break

    ranked = [_apply_live_quote(dict(r)) for r in ranked]
    note = (
        f"Markets closing in the next {horizon_h}h that you could actually act "
        f"on — a two-sided book, or one side with real trading behind it."
    )
    if dropped["untradeable"]:
        note += (
            f" {dropped['untradeable']:,} excluded as unquoted, or quoted on "
            f"one side only with no volume and no open interest — a market "
            f"maker's ladder rung, not an offer."
        )
    if dropped["collapsed"]:
        note += (
            f" {dropped['collapsed']:,} sibling market(s) hidden so that no "
            f"single event can fill the column — open an event to see every "
            f"strike in its ladder."
        )
    if skipped:
        note += f" {skipped} skipped for having no close time."
    return {
        "column": "closing", "rows": ranked, "scanned": len(raw), "truncated": False,
        "note": note, "fetchedAt": _now_iso(), "ageSec": 0.0,
    }


async def discover(column: str, limit: int = 60, refresh: bool = False,
                   watchlist: Optional[list[str]] = None,
                   filters: Optional[dict] = None) -> dict:
    limit = max(1, min(int(limit or 60), 250))

    if column == "watchlist":
        tickers = [t for t in (watchlist or []) if t][:min(limit, 60)]
        if not tickers:
            return {
                "column": "watchlist", "rows": [], "scanned": 0, "truncated": False,
                "note": None, "fetchedAt": _now_iso(), "ageSec": 0.0,
            }
        for t in tickers:
            note_interest(t)
        found = await _public_gate.run(
            kalshi_api.fetch_markets_by_tickers, tickers) or {}
        rows = [_apply_live_quote(market_row(found[t])) for t in tickers if t in found]
        missing = [t for t in tickers if t not in found]
        note = None
        if missing:
            note = (
                f"{len(missing)} watched ticker(s) could not be read from Kalshi "
                f"({', '.join(missing[:4])}{'…' if len(missing) > 4 else ''}) — "
                f"they may have settled and rotated out of the public API."
            )
        return {
            "column": "watchlist", "rows": rows, "scanned": len(tickers),
            "truncated": False, "note": note, "fetchedAt": _now_iso(), "ageSec": 0.0,
        }

    if column in ("trending", "closing"):
        key = f"col:{column}"
        ttl = TAPE_TTL * 4 if column == "trending" else SWEEP_TTL
        raw_limit = limit if not filters else min(250, max(limit * 4, 120))
        hit = None if (refresh or filters) else _cache.get(key, ttl)
        if hit:
            val, age = hit
            return {**val, "ageSec": round(age, 1)}
        got = await (_trending(raw_limit) if column == "trending"
                     else _closing(raw_limit))
        if filters:
            kept, skipped, excluded = apply_filters(got["rows"], filters)
            note = " ".join(x for x in (got.get("note"),
                                        _filter_note(skipped, excluded)) if x)
            return {**got, "rows": kept[:limit], "note": note or None}
        return _cache.put(key, got)

    sweep = await _sweep(refresh=refresh)
    pool, f_skipped, f_excluded = apply_filters(sweep["markets"], filters)
    rows, skipped, dropped = _rank(pool, column, limit)
    rows = [_apply_live_quote(_copy_row(r)) for r in rows]

    notes = [
        f"Swept {len(sweep['markets']):,} markets across "
        f"{sweep['eventCount']:,} open events."
    ]
    if sweep["truncated"]:
        notes.append(
            "Kalshi had more pages than this sweep reads, so a market outside "
            "that slice cannot appear here — type its exact ticker to reach it."
        )
    if skipped:
        metric = {"volume": "lifetime volume", "new": "an open time"}.get(
            column, "the ranking metric")
        notes.append(
            f"{skipped:,} skipped: {metric} had not arrived for them. They are "
            f"not ranked low — they are unranked."
        )
    if dropped["collapsed"]:
        notes.append(
            f"{dropped['collapsed']:,} sibling market(s) hidden so that no "
            f"single event can fill the column — many Kalshi events are strike "
            f"ladders of hundreds of near-identical markets."
        )
    fnote = _filter_note(f_skipped, f_excluded)
    if fnote:
        notes.append(fnote)
    return {
        "column": column,
        "rows": rows,
        "categories": sweep.get("categories", []),
        "scanned": len(sweep["markets"]),
        "truncated": bool(sweep["truncated"]),
        "note": " ".join(notes) or None,
        "fetchedAt": sweep["fetchedAt"],
        "ageSec": sweep.get("ageSec"),
    }


async def search(query: str, limit: int = 60) -> dict:
    q = (query or "").strip()
    limit = max(1, min(int(limit or 60), 250))
    if not q:
        return {
            "column": "search", "rows": [], "scanned": 0, "truncated": False,
            "note": None, "fetchedAt": _now_iso(), "ageSec": 0.0,
        }

    rows: list[dict] = []
    seen: set[str] = set()

    if re.fullmatch(r"[A-Za-z0-9_.\-]{3,80}", q):
        try:
            exact = await _public_gate.run(kalshi_api.fetch_market, q.upper())
        except ProviderParked:
            exact = None
        if exact:
            row = _apply_live_quote(market_row(exact))
            rows.append(row)
            seen.add(row["ticker"])

    note = None
    scanned: Optional[int] = None
    try:
        sweep = await _sweep()
        needle = q.lower()
        for r in sweep["markets"]:
            if len(rows) >= limit:
                break
            if r["ticker"] in seen:
                continue
            hay = " ".join(filter(None, [
                r["ticker"], r["title"], r.get("yesSubTitle") or "",
                r.get("eventTicker") or "", r.get("category") or "",
            ])).lower()
            if needle in hay:
                rows.append(_apply_live_quote(_copy_row(r)))
                seen.add(r["ticker"])
        scanned = len(sweep["markets"])
        if sweep["truncated"]:
            note = (
                f"Searched {scanned:,} markets across the open events this "
                f"sweep reached. A market outside it is still reachable by "
                f"typing its exact ticker."
            )
    except ProviderParked as e:
        note = str(e)

    return {
        "column": "search", "rows": rows, "scanned": scanned, "truncated": False,
        "note": note, "fetchedAt": _now_iso(), "ageSec": 0.0,
    }



def _ladder(levels: list, limit: int = 12) -> tuple[list[dict], Optional[int]]:
    """Raw [[price, size], …] → best-first levels with a running cumulative."""
    clean: list[tuple[float, int]] = []
    for lvl in levels or []:
        try:
            p = price_cents(lvl[0])
            n = _count(lvl[1]) if len(lvl) > 1 else None
        except (TypeError, IndexError):
            continue
        if p is None or n is None or n <= 0:
            continue
        clean.append((p, n))
    if not clean:
        return [], None
    clean.sort(key=lambda pn: -pn[0])
    out: list[dict] = []
    cum = 0
    for p, n in clean:
        cum += n
        if len(out) < limit:
            out.append({"priceCents": p, "contracts": n, "cumulative": cum})
    return out, cum


async def book(ticker: str) -> dict:
    ticker = (ticker or "").strip().upper()
    note_interest(ticker)

    raw = kalshi_ws.orderbook(ticker)
    source = "kalshi-ws"
    stale = False
    note = None
    if raw is None or not (raw.get("yes") or raw.get("no")):
        hit = _cache.get(f"book:{ticker}", BOOK_TTL)
        if hit:
            val, age = hit
            return {**val, "source": "kalshi-cache", "stale": age > BOOK_TTL / 2,
                    "note": f"REST snapshot, {age:.0f}s old"}
        raw = await _public_gate.run(kalshi_api.get_orderbook, ticker)
        source = "kalshi-rest"
        stale = True
        note = (
            "REST snapshot. The live websocket book is not available for this "
            "market — it subscribes a moment after you open the page, and "
            "re-snapshots after any sequence gap."
        )
    if raw is None:
        raise RuntimeError(f"Kalshi returned no order book for {ticker}")

    yes, yes_depth = _ladder(raw.get("yes") or [])
    no, no_depth = _ladder(raw.get("no") or [])
    yes_bid = yes[0]["priceCents"] if yes else None
    yes_ask = price_cents(100 - no[0]["priceCents"]) if no else None
    spread, mid = _spread_mid(yes_bid, yes_ask)

    out = {
        "ticker": ticker,
        "yes": yes,
        "no": no,
        "yesBid": yes_bid,
        "yesAsk": yes_ask,
        "spreadCents": spread,
        "midCents": mid,
        "yesDepthContracts": yes_depth,
        "noDepthContracts": no_depth,
        "source": source,
        "observedAt": _now_iso(),
        "stale": stale,
        "note": note,
    }
    if source == "kalshi-rest":
        _cache.put(f"book:{ticker}", out)
    return out



_CANDLE_GROUPS = (("price", ""), ("yes_bid", "yesBid"), ("yes_ask", "yesAsk"))


def _candle_field(c: dict, group: str, key: str) -> Optional[float]:
    """Historical tier: {"yes_bid": {"close": "0.94"}}. Live tier:
    {"yes_bid": {"close_dollars": "0.9400"}}. Both are dollars."""
    d = c.get(group)
    if not isinstance(d, dict):
        return None
    v = d.get(key)
    if v is None:
        v = d.get(f"{key}_dollars")
    n = _num(v)
    if n is None:
        return None
    cents = n * 100.0 if abs(n) <= 1.5 else n
    return price_cents(cents)


def normalize_candles(raw: list[dict]) -> list[dict]:
    """Providers emit duplicate period stamps (the same bucket twice in one
    response), and a chart library throws on a non-ascending series. Sort and
    collapse at the source — the LAST record for a stamp wins, since a repeat
    is a correction rather than a second period."""
    by_ts: dict[int, dict] = {}
    for c in raw or []:
        if not isinstance(c, dict):
            continue
        ts = _count(c.get("end_period_ts"))
        if ts is None or ts <= 0:
            continue
        volume = _count(c.get("volume"))
        if volume is None:
            volume = _count(c.get("volume_fp"))
        oi = _count(c.get("open_interest"))
        if oi is None:
            oi = _count(c.get("open_interest_fp"))
        by_ts[ts] = {
            "ts": ts,
            "open": _candle_field(c, "price", "open"),
            "high": _candle_field(c, "price", "high"),
            "low": _candle_field(c, "price", "low"),
            "close": _candle_field(c, "price", "close"),
            "mean": _candle_field(c, "price", "mean"),
            "yesBidClose": _candle_field(c, "yes_bid", "close"),
            "yesAskClose": _candle_field(c, "yes_ask", "close"),
            "volume": volume,
            "openInterest": oi,
        }
    return [by_ts[k] for k in sorted(by_ts)]


async def candles(ticker: str, interval_min: int = 1, lookback_min: int = 240) -> dict:
    ticker = (ticker or "").strip().upper()
    note_interest(ticker)
    if interval_min not in (1, 60, 1440):
        interval_min = 1
    lookback_min = max(interval_min, min(int(lookback_min or 240), 60 * 24 * 90))
    end_ts = int(time.time())
    start_ts = end_ts - lookback_min * 60
    key = f"candles:{ticker}:{interval_min}:{lookback_min // max(1, interval_min)}"
    hit = _cache.get(key, CANDLE_TTL)
    if hit:
        val, _age = hit
        return val

    series_ticker = ticker.split("-")[0] if ticker else ""
    raw = await _public_gate.run(
        kalshi_api.fetch_candlesticks,
        ticker=ticker, series_ticker=series_ticker,
        start_ts=start_ts, end_ts=end_ts, period_interval=interval_min,
    )
    if raw is None:
        raise RuntimeError(
            f"Kalshi returned no candle history for {ticker} at "
            f"{interval_min}m. Very new markets have none yet; very old ones "
            f"can rotate off the public tier."
        )

    rows = normalize_candles(raw)
    empty = sum(1 for c in rows if c["close"] is None)
    note = None
    if not rows:
        note = (
            f"Kalshi has no {interval_min}m candles for this market in the last "
            f"{lookback_min / 60:.0f}h. Markets shorter than the interval have "
            f"none by construction — try a finer interval."
        )
    elif empty:
        note = (
            f"{empty} of {len(rows)} periods had no trades — those points are "
            f"gaps, not flat prices."
        )
    out = {
        "ticker": ticker,
        "intervalMin": interval_min,
        "candles": rows,
        "emptyPeriods": empty,
        "startTs": start_ts,
        "endTs": end_ts,
        "source": "kalshi-rest",
        "note": note,
    }
    return _cache.put(key, out)



def _tape_row(t: dict, source: str) -> dict:
    yes = price_cents(t.get("yes_price"))
    if yes is None:
        yes = price_cents(_num(t.get("yes_price_dollars")) * 100
                          if _num(t.get("yes_price_dollars")) is not None else None)
    no = price_cents(t.get("no_price"))
    if no is None:
        no = price_cents(_num(t.get("no_price_dollars")) * 100
                         if _num(t.get("no_price_dollars")) is not None else None)
    if no is None and yes is not None:
        no = price_cents(100 - yes)
    n = _count(t.get("count"))
    if n is None:
        n = _count(t.get("count_fp"))
    side = _text(t.get("taker_side"))
    side = side.lower() if side in ("yes", "no", "YES", "NO") else None

    observed = None
    ms = _count(t.get("observed_ms"))
    if ms:
        observed = datetime.fromtimestamp(ms / 1000.0, timezone.utc)\
            .isoformat(timespec="milliseconds").replace("+00:00", "Z")

    created = _iso(t.get("created_time"))
    if created is None:
        cm = _count(t.get("created_time"))
        if cm and cm > 1_000_000_000_000:
            created = datetime.fromtimestamp(cm / 1000.0, timezone.utc)\
                .isoformat(timespec="seconds").replace("+00:00", "Z")

    notional = None
    if n is not None and yes is not None and side is not None:
        px = yes if side == "yes" else (no if no is not None else None)
        if px is not None:
            notional = round(n * px / 100.0, 2)

    return {
        "tradeId": _text(t.get("trade_id")) or "",
        "ticker": _text(t.get("ticker")) or "",
        "takerSide": side,
        "yesPrice": yes,
        "noPrice": no,
        "contracts": n,
        "notionalUsd": notional,
        "createdAt": created,
        "observedAt": observed,
        "isBlockTrade": bool(t.get("is_block_trade")),
        "source": source,
    }


async def tape(ticker: str, limit: int = 50) -> dict:
    ticker = (ticker or "").strip().upper()
    note_interest(ticker)
    limit = max(1, min(int(limit or 50), 200))

    ws = kalshi_ws.recent_trades(2000)
    if ws:
        mine = [_tape_row(t, "kalshi-ws") for t in ws if t.get("ticker") == ticker]
        if mine:
            return {
                "ticker": ticker, "trades": mine[:limit], "source": "kalshi-ws",
                "note": (
                    "Our own websocket tape — the 'seen' column is when this "
                    "machine received the print, not when Kalshi stamped it."
                ),
                "fetchedAt": _now_iso(),
            }

    hit = _cache.get(f"tape:{ticker}", TAPE_TTL)
    if hit:
        val, age = hit
        return {**val, "source": "kalshi-cache", "note": f"REST tape, {age:.0f}s old"}

    trades = await _public_gate.run(
        kalshi_api.fetch_trades_for_market, ticker, limit,
    )
    if trades is None:
        raise RuntimeError(f"Kalshi returned no trade tape for {ticker}")
    out = {
        "ticker": ticker,
        "trades": [_tape_row(t, "kalshi-rest") for t in trades][:limit],
        "source": "kalshi-rest",
        "note": (
            "REST tape. Open this market's page for a moment and the websocket "
            "takes over, adding local arrival timestamps."
        ),
        "fetchedAt": _now_iso(),
    }
    return _cache.put(f"tape:{ticker}", out)



_HEDGE_TERMS = (
    "at the discretion", "sole discretion", "reasonable", "reasonably",
    "approximately", "substantially", "may determine", "as determined by",
    "in the opinion", "generally", "widely reported", "credible source",
    "if available", "best available", "or similar", "and/or",
)

_VERDICT_SCORE = {"pass": 100.0, "warn": 50.0, "fail": 0.0}


def _check(cid: str, label: str, verdict: str, detail: str) -> dict:
    return {"id": cid, "label": label, "verdict": verdict, "detail": detail}


def resolution_risk(
    *, ticker: str, market: Optional[dict], series: Optional[dict],
    event: Optional[dict] = None, book_snapshot: Optional[dict] = None,
    siblings: Optional[list[dict]] = None,
) -> dict:
    """Resolution risk, not price risk.

    In crypto the equivalent panel asks "can this rug". Here the question is
    "will this settle the way the wording implies" — who resolves it, on what
    source, how ambiguous the wording is, how long after close it settles, and
    whether a related market's price contradicts this one. Almost nobody
    surfaces it, and it is where a prediction-market terminal earns its keep.
    """
    checks: list[dict] = []
    m = market or {}

    sources_raw = None
    if isinstance(event, dict) and event.get("settlement_sources"):
        sources_raw = event.get("settlement_sources")
    elif isinstance(series, dict):
        sources_raw = series.get("settlement_sources")
    settlement_sources: Optional[list[dict]] = None
    _found_sources = isinstance(sources_raw, list) and bool(sources_raw)
    if not _found_sources and (series is None or event is None):
        missing = "event" if event is None else "series"
        checks.append(_check(
            "settlement_source", "Settlement source", "unknown",
            f"The {missing} record could not be read, and nothing else named a "
            f"settlement source — so we cannot say what this market settles "
            f"against. Retry; the terminal will not guess one.",
        ))
    elif _found_sources:
        settlement_sources = [
            {"name": _text(s.get("name")) or _text(s.get("url")) or "unnamed source",
             "url": _text(s.get("url"))}
            for s in sources_raw if isinstance(s, dict)
        ] or None
        names = ", ".join(s["name"] for s in (settlement_sources or [])[:3])
        checks.append(_check(
            "settlement_source", "Settlement source", "pass",
            f"Settles against {names}.",
        ))
    else:
        checks.append(_check(
            "settlement_source", "Settlement source", "warn",
            "Neither the event nor the series names an external settlement "
            "source — this market settles on Kalshi's own determination under "
            "its rules.",
        ))

    rules_primary = _text(m.get("rules_primary"))
    rules_secondary = _text(m.get("rules_secondary"))
    if market is None:
        checks.append(_check("rules_present", "Published rules", "unknown",
                             "The market record could not be read."))
    elif rules_primary and len(rules_primary) >= 60:
        checks.append(_check(
            "rules_present", "Published rules", "pass",
            f"{len(rules_primary)} characters of primary rules"
            + (f" plus secondary rules." if rules_secondary else "."),
        ))
    elif rules_primary:
        checks.append(_check(
            "rules_present", "Published rules", "warn",
            f"Only {len(rules_primary)} characters of rules text — thin for a "
            f"contract you settle against. Read it in full below.",
        ))
    else:
        checks.append(_check(
            "rules_present", "Published rules", "fail",
            "This market ships no primary rules text at all.",
        ))

    if not rules_primary:
        checks.append(_check("rules_ambiguity", "Wording (heuristic)", "unknown",
                             "No rules text to scan."))
    else:
        blob = f"{rules_primary} {rules_secondary or ''}".lower()
        hits = sorted({t for t in _HEDGE_TERMS if t in blob})
        if hits:
            checks.append(_check(
                "rules_ambiguity", "Wording (heuristic)", "warn",
                f"The rules contain discretionary language: "
                f"{', '.join(repr(h) for h in hits[:4])}. This is a keyword "
                f"scan, not a legal reading — it flags wording worth reading "
                f"yourself, it does not claim the market is unfair.",
            ))
        else:
            checks.append(_check(
                "rules_ambiguity", "Wording (heuristic)", "pass",
                "No discretionary phrasing matched the keyword scan. That is "
                "weak evidence of clarity, not proof of it.",
            ))

    cce = m.get("can_close_early")
    condition = _text(m.get("early_close_condition"))
    if isinstance(cce, bool):
        if cce:
            detail = (
                f"Trading can stop before the stated close time: {condition}"
                if condition else
                "Kalshi may close this market before its stated close time, so "
                "a resting order can be stranded."
            )
        else:
            detail = "This market trades until its stated close time."
        checks.append(_check("early_close", "Early close",
                             "warn" if cce else "pass", detail))
    else:
        checks.append(_check("early_close", "Early close", "unknown",
                             "Kalshi did not report an early-close flag."))

    close_dt = _parse_iso(m.get("close_time"))
    exp_dt = _parse_iso(m.get("expiration_time")) or _parse_iso(m.get("latest_expiration_time"))
    if close_dt and exp_dt:
        hours = (exp_dt - close_dt).total_seconds() / 3600.0
        if hours <= 1:
            v, d = "pass", f"Settles within {hours * 60:.0f} minutes of close."
        elif hours <= 48:
            v, d = "warn", f"Capital is locked for about {hours:.0f}h after close."
        else:
            v, d = "warn", (
                f"Capital is locked for about {hours / 24:.0f} days after "
                f"close — price that against what else you could do with it."
            )
        checks.append(_check("settlement_delay", "Close → settlement", v, d))
    else:
        checks.append(_check(
            "settlement_delay", "Close → settlement", "unknown",
            "Kalshi did not give both a close time and an expiration time for "
            "this market, so the gap cannot be computed.",
        ))

    strike_type = _text(m.get("strike_type"))
    strike_val = _num(m.get("floor_strike"))
    if strike_val is None:
        strike_val = _num(m.get("cap_strike"))
    custom = m.get("custom_strike")
    if not strike_type:
        checks.append(_check(
            "strike", "Strike definition", "unknown",
            "Not a strike-based market — this check does not apply, and it is "
            "excluded from the score rather than counted against it.",
        ))
    elif strike_val is not None or (isinstance(custom, dict) and custom):
        detail = f"Strike type {strike_type}"
        detail += f", level {strike_val:g}." if strike_val is not None else ", custom levels published."
        checks.append(_check("strike", "Strike definition", "pass", detail))
    else:
        checks.append(_check(
            "strike", "Strike definition", "warn",
            f"Declared as strike type {strike_type} but no strike level is "
            f"published on the market record.",
        ))

    if not book_snapshot:
        checks.append(_check("exitability", "Exit liquidity", "unknown",
                             "The order book has not loaded yet."))
    else:
        spread = book_snapshot.get("spreadCents")
        yd = book_snapshot.get("yesDepthContracts")
        nd = book_snapshot.get("noDepthContracts")
        if spread is None:
            checks.append(_check(
                "exitability", "Exit liquidity", "warn",
                "The book is one-sided — there is no spread because one side "
                "has no resting orders. You may be able to enter and not exit.",
            ))
        elif spread <= 3:
            checks.append(_check(
                "exitability", "Exit liquidity", "pass",
                f"{spread:g}c spread, {yd or 0} YES / {nd or 0} NO contracts resting.",
            ))
        elif spread <= 10:
            checks.append(_check(
                "exitability", "Exit liquidity", "warn",
                f"{spread:g}c spread — a round trip costs that before fees.",
            ))
        else:
            checks.append(_check(
                "exitability", "Exit liquidity", "fail",
                f"{spread:g}c spread. Crossing it twice is most of the edge in "
                f"any realistic trade here.",
            ))

    sib_mids = [s.get("midCents") for s in (siblings or []) if s.get("midCents") is not None]
    exclusive = (event or {}).get("mutually_exclusive")
    if not isinstance(event, dict):
        checks.append(_check(
            "coherence", "Sibling coherence", "unknown",
            "The parent event could not be read, so this price has nothing to "
            "be cross-checked against.",
        ))
    elif exclusive is not True:
        checks.append(_check(
            "coherence", "Sibling coherence", "unknown",
            "This event's legs are not mutually exclusive, so their prices are "
            "not meant to sum to 100c — the check does not apply and is "
            "excluded from the score rather than counted against it.",
        ))
    elif len(sib_mids) < 2:
        checks.append(_check(
            "coherence", "Sibling coherence", "unknown",
            "Fewer than two sibling legs are quoted, so there is nothing to "
            "cross-check this price against.",
        ))
    elif len(sib_mids) < len([x for x in (siblings or []) if isinstance(x, dict)]) \
            and sum(sib_mids) < 85:
        unquoted = len([x for x in (siblings or []) if isinstance(x, dict)]) - len(sib_mids)
        checks.append(_check(
            "coherence", "Sibling coherence", "unknown",
            f"{unquoted} of this event's legs are not quoted, so the "
            f"{sum(sib_mids):.0f}c the quoted ones add up to is only a lower "
            f"bound. There is nothing to conclude from it.",
        ))
    else:
        total = sum(sib_mids)
        if 85 <= total <= 115:
            checks.append(_check(
                "coherence", "Sibling coherence", "pass",
                f"The {len(sib_mids)} quoted legs of this event price to "
                f"{total:.0f}c in total — coherent for a mutually exclusive set.",
            ))
        else:
            checks.append(_check(
                "coherence", "Sibling coherence", "warn",
                f"The {len(sib_mids)} quoted legs price to {total:.0f}c in "
                f"total. Either a leg is mispriced, or the legs are not "
                f"mutually exclusive — check the event before assuming an arb.",
            ))

    status = _text(m.get("status"))
    if not status:
        checks.append(_check("status", "Status consistency", "unknown",
                             "Kalshi reported no status for this market."))
    elif status in ("settled", "finalized", "determined"):
        checks.append(_check(
            "status", "Status consistency", "pass",
            f"Already {status} — there is nothing left to resolve.",
        ))
    elif close_dt and close_dt < datetime.now(timezone.utc) and status in ("active", "open"):
        checks.append(_check(
            "status", "Status consistency", "warn",
            f"Kalshi still reports this market as {status}, but its close time "
            f"has passed. Orders may be rejected.",
        ))
    else:
        checks.append(_check("status", "Status consistency", "pass",
                             f"Reported as {status}, consistent with its clock."))

    resolved = [c for c in checks if c["verdict"] != "unknown"]
    if len(resolved) >= MIN_RESOLVED_CHECKS:
        score = round(sum(_VERDICT_SCORE[c["verdict"]] for c in resolved) / len(resolved))
        note = (
            f"Averaged over the {len(resolved)} of {len(checks)} checks that "
            f"resolved. Unresolved checks are excluded, not treated as passes."
        )
    else:
        score = None
        note = (
            f"Only {len(resolved)} of {len(checks)} checks resolved — fewer than "
            f"the {MIN_RESOLVED_CHECKS} needed for a score to mean anything. "
            f"Read the individual checks instead."
        )

    return {
        "ticker": ticker,
        "checks": checks,
        "resolvedCount": len(resolved),
        "totalCount": len(checks),
        "score": score,
        "scoreNote": note,
        "settlementSources": settlement_sources,
        "rulesPrimary": rules_primary,
        "rulesSecondary": rules_secondary,
        "closeTime": _iso(m.get("close_time")),
        "expirationTime": _iso(m.get("expiration_time")) or _iso(m.get("latest_expiration_time")),
        "settlementTimerSeconds": _count(m.get("settlement_timer_seconds")),
        "canCloseEarly": cce if isinstance(cce, bool) else None,
        "venue": "kalshi",
        "venueNote": (
            "Kalshi is a CFTC-regulated US designated contract market. Contracts "
            "settle against the exchange's published rules and are held in a "
            "segregated member account — a different legal footing from an "
            "offshore or on-chain prediction venue. Fees and settlement here are "
            "Kalshi's, and the terminal never blurs one venue's guarantees into "
            "another's."
        ),
    }



def _position_row(p: dict, mark: Optional[dict]) -> dict:
    """One /portfolio/positions record → a TerminalPosition.

    Cost basis comes from Kalshi's OWN ledger (`market_exposure_dollars`), never
    from what we asked to pay: the real cost of a fill includes the taker fee
    and any partial fill at a worse price, and every one of those makes a
    naive number wrong in the user's favour on every single row.

    A row whose exposure could not be read is marked unreconciled, its derived
    figures are None, and it is excluded from every total.
    """
    ticker = _text(p.get("ticker")) or ""
    qty = _num(p.get("position_fp"))
    if qty is None:
        qty = _num(p.get("position"))
    contracts = int(abs(round(qty))) if qty is not None else 0
    side = "yes" if (qty or 0) > 0 else "no"

    exposure = _num(p.get("market_exposure_dollars"))
    if exposure is None:
        cents = _num(p.get("market_exposure"))
        exposure = cents / 100.0 if cents is not None else None

    fees = _num(p.get("fees_paid_dollars"))
    if fees is None:
        fc = _num(p.get("fees_paid"))
        fees = fc / 100.0 if fc is not None else None

    realized = _num(p.get("realized_pnl_dollars"))
    if realized is None:
        rc = _num(p.get("realized_pnl"))
        realized = rc / 100.0 if rc is not None else None

    reconciled = exposure is not None and contracts > 0
    note = None
    if not reconciled:
        note = (
            "Kalshi's ledger reported no cost basis for this position — it is "
            "excluded from every total above rather than counted as break-even."
        )
    avg = round(exposure * 100.0 / contracts, 2) if reconciled else None

    mark_cents = None
    if mark:
        yes_mark = mark.get("midCents")
        if yes_mark is None:
            yes_mark = mark.get("lastPrice")
        if yes_mark is not None:
            mark_cents = yes_mark if side == "yes" else price_cents(100 - yes_mark)

    mv = round(contracts * mark_cents / 100.0, 2) if mark_cents is not None else None
    unreal = round(mv - exposure, 2) if (mv is not None and reconciled) else None

    return {
        "ticker": ticker,
        "title": (mark or {}).get("title"),
        "eventTicker": (mark or {}).get("eventTicker"),
        "side": side,
        "contracts": contracts,
        "avgCostCents": avg,
        "costBasisUsd": round(exposure, 2) if reconciled else None,
        "feesPaidUsd": round(fees, 2) if fees is not None else None,
        "markCents": mark_cents,
        "marketValueUsd": mv,
        "unrealizedUsd": unreal,
        "realizedUsd": round(realized, 2) if realized is not None else None,
        "reconciled": reconciled,
        "reconcileNote": note,
        "closeTime": (mark or {}).get("closeTime"),
        "status": (mark or {}).get("status"),
    }


async def portfolio(authed: bool) -> dict:
    env = kalshi_auth.get_env()
    if not authed:
        return {
            "positions": [], "unreconciledCount": 0,
            "totalCostBasisUsd": None, "totalMarketValueUsd": None,
            "totalUnrealizedUsd": None, "totalRealizedUsd": None,
            "cashUsd": None, "env": env, "fetchedAt": _now_iso(),
            "note": (
                "No verified Kalshi credentials. Add a key in API Keys and the "
                "terminal will read your real positions — it shows nothing "
                "rather than showing zeros. Or switch to Paper, which needs no "
                "key."
            ),
        }

    raw = await kalshi_api.get_positions(limit=200)
    live = [p for p in raw if abs(_num(p.get("position_fp")) or _num(p.get("position")) or 0) >= 1]
    tickers = [_text(p.get("ticker")) for p in live]
    marks: dict[str, dict] = {}
    if tickers:
        try:
            found = await _public_gate.run(
                kalshi_api.fetch_markets_by_tickers, [t for t in tickers if t],
            )
            marks = {k: _apply_live_quote(market_row(v)) for k, v in (found or {}).items()}
        except ProviderParked as e:
            logger.info("terminal: marks unavailable — %s", e)

    rows = [_position_row(p, marks.get(_text(p.get("ticker")) or "")) for p in live]
    good = [r for r in rows if r["reconciled"]]
    unreconciled = len(rows) - len(good)

    def _tot(field: str) -> Optional[float]:
        """Sum the reconciled rows. With no positions at all the total is a real
        zero; with positions whose value nobody could produce it is None — the
        difference between "you hold nothing" and "we could not price what you
        hold" is the whole point of this module."""
        if not rows:
            return 0.0
        vals = [r[field] for r in good if r[field] is not None]
        return round(sum(vals), 2) if vals else None

    cash = None
    shard_cash: dict = {}
    try:
        bal = await kalshi_api.get_balance()
        total = _num((bal or {}).get("total_balance_cents"))
        if total is not None:
            cash = total / 100.0
        else:
            cents = _num((bal or {}).get("balance"))
            dollars = _num((bal or {}).get("balance_dollars"))
            cash = dollars if dollars is not None else (
                cents / 100.0 if cents is not None else None)
        shard_cash = {
            str(i): {"name": kalshi_api.shard_name(int(i)), "cashUsd": round(v, 2)}
            for i, v in ((bal or {}).get("shard_balances") or {}).items()
        }
    except Exception as e:
        logger.debug("terminal: balance read failed: %s", e)

    starved: list[str] = []
    for pos in rows:
        m = marks.get(pos["ticker"]) or {}
        idx = m.get("exchangeIndex")
        if idx is None:
            continue
        entry = shard_cash.get(str(idx))
        if entry is not None and entry["cashUsd"] <= 0:
            starved.append(entry["name"])

    note = None
    if starved:
        uniq = sorted(set(starved))
        note = (
            f"No cash on the {', '.join(uniq)} exchange"
            f"{'s' if len(uniq) > 1 else ''}. Kalshi splits collateral per "
            f"exchange shard, so orders there will be refused even though your "
            f"total balance looks fine. Move funds on Kalshi's exchange "
            f"balances page — the button below opens it."
        )
    if unreconciled:
        note = ((note + " ") if note else "") + (
            f"{unreconciled} position(s) have no readable cost basis on Kalshi's "
            f"ledger and are excluded from the totals. Cost basis is AVERAGE "
            f"cost, not FIFO."
        )
    return {
        "positions": rows,
        "unreconciledCount": unreconciled,
        "totalCostBasisUsd": _tot("costBasisUsd"),
        "totalMarketValueUsd": _tot("marketValueUsd"),
        "totalUnrealizedUsd": _tot("unrealizedUsd"),
        "totalRealizedUsd": _tot("realizedUsd"),
        "cashUsd": round(cash, 2) if cash is not None else None,
        "shardCash": shard_cash,
        "shardTransferUrl": kalshi_api.web_exchange_indexes_url(env),
        "env": env,
        "fetchedAt": _now_iso(),
        "note": note,
    }


def _first_count(o: dict, *keys: str) -> Optional[int]:
    """First readable count among `keys`, or None if none of them parse.

    `is not None` rather than `or`, because 0 is a real count — a fully filled
    order genuinely has 0 remaining, and truthiness would skip past it to the
    next name and report a stale one."""
    for k in keys:
        v = _count(o.get(k))
        if v is not None:
            return v
    return None


def _order_row(o: dict, title: Optional[str] = None) -> dict:
    side = _text(o.get("side"))
    side = side.lower() if side in ("yes", "no", "YES", "NO") else "yes"
    action = _text(o.get("action")) or ""
    action = action.lower() if action.lower() in ("buy", "sell") else "buy"
    px = price_cents(o.get("yes_price") if side == "yes" else o.get("no_price"))
    if px is None:
        d = _num(o.get("yes_price_dollars") if side == "yes" else o.get("no_price_dollars"))
        px = price_cents(d * 100) if d is not None else None
    if px is None:
        d = _num(o.get("price"))
        px = price_cents(d * 100 if d is not None and d <= 1.5 else d)
    coid = _text(o.get("client_order_id"))
    return {
        "orderId": _text(o.get("order_id")) or _text(o.get("id")) or "",
        "clientOrderId": coid,
        "ticker": _text(o.get("ticker")) or "",
        "title": title,
        "side": side,
        "action": action,
        "priceCents": px,
        "count": _first_count(o, "initial_count_fp", "place_count", "count"),
        "remaining": _first_count(o, "remaining_count_fp", "remaining_count"),
        "status": _text(o.get("status")) or "unknown",
        "createdAt": _iso(o.get("created_time")),
        "manual": bool(coid and coid.startswith(MANUAL_ORDER_PREFIX)),
    }


async def resting_orders(authed: bool, ticker: str = "") -> dict:
    if not authed:
        return {"orders": [], "note": "No verified credentials for this environment."}
    raw = await kalshi_api.fetch_orders(status="resting", ticker=ticker or "")
    orders = [_order_row(o) for o in raw]
    note = None
    if len(raw) >= 1000:
        note = (
            "This list walked its page cap — you may have more resting orders "
            "than are shown. Cancel from the Kalshi web app if one is missing."
        )
    return {"orders": orders, "note": note}



def _fee_usd(price_c: float, contracts: int) -> float:
    """Kalshi's trading fee for this order, in dollars — the exchange's own
    formula (0.07·p·(1−p) per contract, rounded UP per order to the next cent),
    reused from the backtester rather than re-derived, so the ticket and the
    P&L maths can never drift apart."""
    p = max(0.01, min(0.99, price_c / 100.0))
    return round(_bt.kalshi_fee_per_contract(p, contracts=max(1, contracts)) * contracts, 2)


def mode_mismatch(req: dict, scope: str) -> Optional[str]:
    """Why a ticket must not go out in `scope`, or None.

    The ticket names the account mode it was filled in (`expectMode`:
    'paper' | 'live'). Paper and Live trade the same tickers at the same
    prices, so a ticket priced while the app said PAPER and sent after a
    switch to Live would look identical — and spend real money. Absent means
    the caller did not say (an older renderer, a rule, a phone order), and
    the scope in force decides, as before."""
    want = str((req or {}).get("expectMode") or "").strip().lower()
    if want not in ("paper", "live"):
        return None
    have = "paper" if scope == kalshi_auth.PAPER else "live"
    if want == have:
        return None
    return (f"Not sent: this ticket was filled in on {want.upper()}, but the app "
            f"is now on {have.upper()}. Check the ticket and send it again.")


def preview(
    req: dict, *, cfg: dict, authed: bool, market: Optional[dict],
    book_snapshot: Optional[dict], position: Optional[dict],
    exchange_status: Optional[dict] = None,
) -> dict:
    """Price and vet a manual ticket. Everything here runs in the backend: the
    renderer never computes what an order costs and hands the number back, and
    every rail below is enforced again at submit time."""
    ticker = (req.get("ticker") or "").strip().upper()
    side = (req.get("side") or "yes").lower()
    action = (req.get("action") or "buy").lower()
    count = _count(req.get("count")) or 0
    px = price_cents(req.get("priceCents"))

    warnings: list[str] = []
    blockers: list[str] = []

    env = kalshi_auth.get_env()
    mismatch = mode_mismatch(req, env)
    if mismatch:
        blockers.append(mismatch)
    if not authed:
        blockers.append(
            "No verified Kalshi credentials. Add a key in API Keys before "
            "trading live, or switch to Paper, which needs no key."
        )
    if side not in ("yes", "no"):
        blockers.append("Side must be YES or NO.")
    if action not in ("buy", "sell"):
        blockers.append("Action must be buy or sell.")
    if count <= 0:
        blockers.append("Enter a contract count of at least 1.")
    if px is None:
        blockers.append(
            "Enter a limit price between 1c and 99c. Kalshi has no price "
            "outside that range — 0c and 100c are not prices, they are the "
            "settled outcomes."
        )

    held_here = (position or {}).get("contracts") if position else None
    reducing = (
        action == "sell"
        and bool(held_here)
        and (position or {}).get("side") == side
        and count <= int(held_here)
    )

    max_contracts = _count(cfg.get("terminal_max_contracts")) or 100
    max_notional = _num(cfg.get("terminal_max_notional_usd")) or 500.0
    if count > max_contracts and not reducing:
        blockers.append(
            f"{count} contracts exceeds the manual-trading cap of "
            f"{max_contracts}. Raise it in Settings if you mean it."
        )

    cost = fee = total = payout = max_profit = max_loss = breakeven = None
    if px is not None and count > 0:
        gross = round(count * px / 100.0, 2)
        fee = _fee_usd(px, count)
        if action == "buy":
            cost = gross
            total = round(gross + fee, 2)
            payout = round(count * 1.0, 2)
            max_profit = round(payout - total, 2)
            max_loss = total
            breakeven = round(total / count, 4)
        else:
            cost = gross
            total = round(gross - fee, 2)
            payout = None
            basis = (position or {}).get("avgCostCents") if position else None
            if basis is not None:
                entry_fee_share = _manual_entry_fee_share(ticker, side, count)
                max_profit = round(
                    (px - basis) * count / 100.0 - fee - entry_fee_share, 2)
                max_loss = None
            else:
                warnings.append(
                    "No reconciled cost basis for this position, so the realised "
                    "P&L of this sale is unknown — it is not zero."
                )
        if total is not None and abs(total) > max_notional and not reducing:
            blockers.append(
                f"${abs(total):,.2f} exceeds the manual-trading notional cap of "
                f"${max_notional:,.2f}. Raise it in Settings if you mean it."
            )
        elif total is not None and abs(total) > max_notional and reducing:
            warnings.append(
                f"${abs(total):,.2f} is over the ${max_notional:,.2f} manual cap, "
                f"but this order REDUCES a position you already hold — the cap "
                f"guards against opening something you did not mean to, and "
                f"never against getting out."
            )

    if market is None:
        warnings.append(
            "The market record could not be read, so its status and close time "
            "could not be checked before this order."
        )
    else:
        status = market.get("status")
        if status not in ("active", "open", None):
            blockers.append(f"This market is {status} — it is not accepting orders.")
        st = exchange_status
        if st is None:
            st = kalshi_api.cached_exchange_status()
        halted = kalshi_api.shard_trading_halted(st, market.get("exchangeIndex"))
        if halted:
            blockers.append(
                f"Kalshi has halted trading on the {halted} matching engine, "
                f"which hosts this market. Orders would be rejected until it "
                f"reopens — this is Kalshi's status, not a connection problem."
            )

        mins = market.get("minutesToClose")
        if mins is not None and mins <= 0:
            blockers.append("This market's close time has passed.")
        elif mins is not None and mins <= 5:
            warnings.append(f"Closes in {mins:.0f} minute(s).")
        if market.get("canCloseEarly"):
            warnings.append(
                "Kalshi may close this market early — a resting order can be "
                "stranded unfilled."
            )

    if action == "sell":
        held = (position or {}).get("contracts") if position else None
        held_side = (position or {}).get("side") if position else None
        if not held or held_side != side:
            blockers.append(
                f"You hold no {side.upper()} contracts in this market. To take "
                f"the other side, BUY {'NO' if side == 'yes' else 'YES'} — on "
                f"Kalshi a sell only reduces an existing position."
            )
        elif count > held:
            blockers.append(f"You hold {held} {side.upper()} contract(s); cannot sell {count}.")

    resting_best = None
    marketable = None
    if book_snapshot:
        if action == "buy":
            resting_best = book_snapshot.get("yesAsk") if side == "yes" else (
                price_cents(100 - book_snapshot["yesBid"])
                if book_snapshot.get("yesBid") is not None else None
            )
            if resting_best is not None and px is not None:
                marketable = px >= resting_best
        else:
            resting_best = book_snapshot.get("yesBid") if side == "yes" else (
                price_cents(100 - book_snapshot["yesAsk"])
                if book_snapshot.get("yesAsk") is not None else None
            )
            if resting_best is not None and px is not None:
                marketable = px <= resting_best
        if resting_best is None:
            warnings.append(
                f"Nothing is resting on the side you are taking, so this order "
                f"cannot fill immediately — it will sit in the book."
            )
        elif marketable is False:
            warnings.append(
                f"Best available is {resting_best:g}c; this order rests until "
                f"someone crosses to it."
            )
        spread = book_snapshot.get("spreadCents")
        if spread is not None and spread >= 10:
            warnings.append(
                f"The spread is {spread:g}c. Entering and exiting costs that "
                f"much twice, before fees."
            )
    else:
        warnings.append("The order book has not loaded, so this price is unchecked against it.")

    if not blockers:
        try:
            import db
            with db.get_db() as conn:
                if db.bot_owns_position(conn, ticker, side, env):
                    warnings.append(
                        "The bot is managing a position on this side of this "
                        "market. Trading it by hand changes what the engine is "
                        "working with — pause trading first if that is not what "
                        "you want."
                    )
        except Exception as e:
            logger.debug("terminal: bot-ownership check failed for %s: %s", ticker, e)

    if env == "production" and not blockers:
        warnings.append("LIVE — this spends real money.")
    elif env == kalshi_auth.PAPER and not blockers:
        warnings.append("PAPER — real prices, imaginary money. Nothing is sent "
                        "to Kalshi.")

    return {
        "ticker": ticker, "side": side, "action": action,
        "count": count, "priceCents": px if px is not None else 0,
        "costUsd": cost, "feeUsd": fee, "totalUsd": total,
        "maxPayoutUsd": payout, "maxProfitUsd": max_profit, "maxLossUsd": max_loss,
        "breakevenProb": breakeven,
        "restingBestCents": resting_best,
        "marketableNow": marketable,
        "warnings": warnings,
        "blockers": blockers,
    }


async def submit(req: dict, *, cfg: dict, authed: bool,
                 scope: Optional[str] = None) -> dict:
    """Place a manual order, then RECONCILE it against Kalshi's own fills
    ledger before reporting what it cost.

    Every rail from `preview` is re-run here. The renderer's preview is a
    convenience; this is the gate. Assume the renderer is hostile.
    """
    ticker = (req.get("ticker") or "").strip().upper()
    side = (req.get("side") or "yes").lower()
    action = (req.get("action") or "buy").lower()
    count = _count(req.get("count")) or 0
    px = price_cents(req.get("priceCents"))
    scope = scope or kalshi_auth.get_env()
    if scope != kalshi_auth.get_env():
        return {
            "ok": False, "orderId": None, "clientOrderId": "", "status": None,
            "filledContracts": None, "avgFillCents": None, "feesUsd": None,
            "reconciled": False,
            "message": ("Not sent: the app switched between Paper and Live after "
                        "this order was decided."),
        }
    mismatch = mode_mismatch(req, scope)
    if mismatch:
        return {
            "ok": False, "orderId": None, "clientOrderId": "", "status": None,
            "filledContracts": None, "avgFillCents": None, "feesUsd": None,
            "reconciled": False, "message": mismatch,
        }

    market = None
    book_snapshot = None
    position = None
    try:
        raw = await _public_gate.run(kalshi_api.fetch_market, ticker)
        market = _apply_live_quote(market_row(raw)) if raw else None
    except Exception as e:
        logger.info("terminal submit: market read failed for %s: %s", ticker, e)
    try:
        book_snapshot = await book(ticker)
    except Exception as e:
        logger.info("terminal submit: book read failed for %s: %s", ticker, e)
    if authed:
        try:
            pf = await portfolio(True)
            position = next((p for p in pf["positions"] if p["ticker"] == ticker), None)
        except Exception as e:
            logger.info("terminal submit: portfolio read failed: %s", e)

    ex_status = None
    try:
        ex_status = await _public_gate.run(kalshi_api.fetch_exchange_status)
    except Exception as e:
        logger.info("terminal submit: exchange status read failed: %s", e)

    pv = preview(req, cfg=cfg, authed=authed, market=market,
                 book_snapshot=book_snapshot, position=position,
                 exchange_status=ex_status)
    if pv["blockers"]:
        return {
            "ok": False, "message": pv["blockers"][0], "orderId": None,
            "clientOrderId": "", "status": None, "filledContracts": None,
            "avgFillCents": None, "feesUsd": None, "reconciled": False,
        }

    client_order_id = f"{MANUAL_ORDER_PREFIX}{uuid.uuid4()}"
    try:
        resp = await kalshi_api.place_limit_order(
            ticker=ticker, side=side, action=action, count=count,
            price_cents=px, client_order_id=client_order_id,
            pin_env=scope,
        )
    except Exception as e:
        if kalshi_api.is_scope_changed(e):
            return {
                "ok": False, "message": f"Not sent: {e.body.get('error', {}).get('message')}",
                "orderId": None, "clientOrderId": client_order_id, "status": None,
                "filledContracts": None, "avgFillCents": None, "feesUsd": None,
                "reconciled": False,
            }
        found = None
        lookup_ok = False
        try:
            found = await kalshi_api.find_order_by_client_id(
                client_order_id, ticker=ticker, pin_env=scope)
            lookup_ok = True
        except Exception as le:
            logger.warning(
                "terminal submit: POST raised (%s) AND the order lookup failed "
                "(%s) — the order may be live on Kalshi; booking it as "
                "unconfirmed rather than rejected.", e, le,
            )
        if not found and not lookup_ok:
            if action == "buy":
                record_manual_buy(
                    ticker=ticker, side=side, count=count, price_cents=px,
                    client_order_id=client_order_id, order_id=None,
                    status="unconfirmed", filled=None, avg_cents=None,
                    fees_usd=None, env=scope,
                    title=(market or {}).get("title") or "",
                    event_ticker=(market or {}).get("eventTicker") or "",
                    category=(market or {}).get("category") or "",
                )
            return {
                "ok": False,
                "message": (
                    f"The order was sent but Kalshi's reply was lost, and we "
                    f"could not confirm whether it exists ({e}). It may be "
                    f"LIVE. Check your resting orders before retrying — this "
                    f"is recorded as unconfirmed, not as rejected."
                ),
                "orderId": None, "clientOrderId": client_order_id,
                "status": "unconfirmed", "filledContracts": None,
                "avgFillCents": None, "feesUsd": None, "reconciled": False,
            }
        if found:
            resp = found
            logger.warning(
                "terminal submit: POST raised (%s) but order %s is live on "
                "Kalshi — recovered by client_order_id", e, client_order_id,
            )
        else:
            why = kalshi_api.rejection_text(e)
            if kalshi_api.is_user_not_found(e):
                try:
                    why = await kalshi_api.explain_order_rejection(
                        e, ticker=ticker,
                        exchange_index=(market or {}).get("exchangeIndex"))
                except Exception:
                    pass
            return {
                "ok": False, "message": f"Kalshi rejected the order: {why}",
                "orderId": None, "clientOrderId": client_order_id, "status": None,
                "filledContracts": None, "avgFillCents": None, "feesUsd": None,
                "reconciled": False,
            }

    order = (resp or {}).get("order") if isinstance(resp, dict) else None
    order = order if isinstance(order, dict) else (resp if isinstance(resp, dict) else {})
    order_id = _text(order.get("order_id")) or _text(order.get("id"))
    status = _text(order.get("status"))

    filled = avg = fees = None
    reconciled = False
    if order_id:
        await asyncio.sleep(0.4)
        try:
            fills = await kalshi_api.get_fills_for_order(order_id, pin_env=scope)
            mine = [f for f in fills if str(f.get("order_id") or "") == str(order_id)]
            import trader as _trader
            total_n = 0
            total_c = 0.0
            for f in mine:
                fp = _trader._parse_kalshi_fill(f, default_side=side)
                if fp["count"] <= 0 or fp["price_cents"] is None:
                    continue
                total_n += fp["count"]
                total_c += fp["count"] * fp["price_cents"]
            if total_n:
                filled = total_n
                avg = round(total_c / total_n, 2)
                fees = _fee_usd(avg, total_n)
                reconciled = True
            elif not mine:
                filled = 0
                reconciled = True
        except Exception as e:
            logger.info("terminal submit: fill reconciliation failed for %s: %s", order_id, e)

    if action == "buy":
        record_manual_buy(
            ticker=ticker, side=side, count=count, price_cents=px,
            client_order_id=client_order_id, order_id=order_id, status=status,
            filled=filled, avg_cents=avg, fees_usd=fees, env=scope,
            title=(market or {}).get("title") or "",
            event_ticker=(market or {}).get("eventTicker") or "",
            category=(market or {}).get("category") or "",
        )
    else:
        await record_manual_sell(
            ticker=ticker, side=side, count=count, price_cents=px,
            order_id=order_id, status=status, filled=filled, env=scope,
        )

    paper = scope == kalshi_auth.PAPER
    if reconciled and filled:
        msg = (f"PAPER: filled {filled} at {avg:g}c average against the real book "
               f"(paper ledger, fees ${fees:.2f})." if paper else
               f"Filled {filled} at {avg:g}c average (Kalshi's ledger, fees ${fees:.2f}).")
    elif reconciled:
        msg = (f"PAPER: order resting at {px:g}c — it fills only if the real book "
               f"crosses it." if paper else f"Order resting at {px:g}c — no fills yet.")
    else:
        msg = (
            f"Order accepted ({status or 'unknown status'}), but Kalshi's fills "
            f"ledger could not be read. It is recorded as unreconciled and "
            f"excluded from portfolio figures until it can be."
        )
    shard_note = resp.get("krypt_shard_note") if isinstance(resp, dict) else None
    if shard_note:
        msg = f"{msg} The app {shard_note}." if shard_note.startswith("moved") else f"{msg} Note: {shard_note}."

    _cache.drop(f"book:{ticker}")
    return {
        "ok": True, "message": msg, "orderId": order_id,
        "clientOrderId": client_order_id, "status": status,
        "filledContracts": filled, "avgFillCents": avg, "feesUsd": fees,
        "reconciled": reconciled,
    }


async def cancel(order_id: str, *, authed: bool) -> dict:
    oid = (order_id or "").strip()
    if not authed:
        return {
            "ok": False, "message": "No verified credentials for this environment.",
            "orderId": oid, "clientOrderId": "", "status": None,
            "filledContracts": None, "avgFillCents": None, "feesUsd": None,
            "reconciled": False,
        }
    if not oid:
        return {
            "ok": False, "message": "No order id.", "orderId": None,
            "clientOrderId": "", "status": None, "filledContracts": None,
            "avgFillCents": None, "feesUsd": None, "reconciled": False,
        }
    ticker = None
    try:
        for o in (await resting_orders(authed)).get("orders") or []:
            if str(o.get("orderId") or "") == oid:
                ticker = o.get("ticker")
                break
    except Exception as e:
        logger.info("terminal cancel: could not look up %s's market: %s", oid, e)
    try:
        await kalshi_api.cancel_order(oid, ticker=ticker)
    except Exception as e:
        logger.warning("terminal cancel %s refused: %s", oid, e)
        return {
            "ok": False, "message": f"Kalshi refused the cancel: {kalshi_api.rejection_text(e)}",
            "orderId": oid, "clientOrderId": "", "status": None,
            "filledContracts": None, "avgFillCents": None, "feesUsd": None,
            "reconciled": False,
        }
    try:
        import db
        with db.get_db() as conn:
            row = conn.execute(
                """SELECT id FROM bot_positions
                   WHERE signal_source='manual' AND kalshi_order_id=?
                     AND kalshi_env=? LIMIT 1""",
                (oid, kalshi_auth.get_env()),
            ).fetchone()
            if row:
                db.log_event(conn, int(row["id"]), "manual-cancel",
                             note=f"user cancelled order {oid}")
    except Exception as e:
        logger.debug("terminal: could not log manual cancel %s: %s", oid, e)

    return {
        "ok": True, "message": "Cancelled.", "orderId": oid, "clientOrderId": "",
        "status": "canceled", "filledContracts": None, "avgFillCents": None,
        "feesUsd": None, "reconciled": False,
    }




def _manual_signal_id(ticker: str, side: str) -> int:
    """bot_positions is UNIQUE(signal_source, signal_id, kalshi_env) — manual
    rows have no upstream signal, so synthesise a collision-resistant id.

    Random, not clock-derived: it used to hash time.time_ns(), which on Windows
    under Python < 3.13 ticks every 15.6 ms — the Python the installers are
    frozen with — so two manual buys of one ticker+side inside a tick got the
    same id and the second hit the UNIQUE constraint."""
    return secrets.randbelow(2_000_000_000)


async def _reconcile_fills(
    order_id: Optional[str], side: str, pin_env: Optional[str] = None,
) -> tuple[Optional[int], Optional[float]]:
    """(contracts, average price in cents) for one order, from Kalshi's fills.

    (None, None) when the ledger could not be read — which every caller must
    treat as "unknown", never as zero. This is the only source of truth for
    what a trade cost or made: the limit price is what we asked for, and the
    difference is fees and partial fills at worse prices, every one of which
    is wrong in the user's favour."""
    if not order_id:
        return None, None
    try:
        import trader as _trader
        fills = await kalshi_api.get_fills_for_order(order_id, pin_env=pin_env)
        mine = [f for f in fills if str(f.get("order_id") or "") == str(order_id)]
        total_n = 0
        total_c = 0.0
        for f in mine:
            fp = _trader._parse_kalshi_fill(f, default_side=side)
            if fp["count"] <= 0 or fp["price_cents"] is None:
                continue
            total_n += fp["count"]
            total_c += fp["count"] * fp["price_cents"]
        if total_n:
            return total_n, round(total_c / total_n, 2)
        return (0, None) if not mine else (None, None)
    except Exception as e:
        logger.info("terminal: fill reconciliation failed for %s: %s", order_id, e)
        return None, None


def _manual_entry_fee_share(ticker: str, side: str, count: int) -> float:
    """The entry fee already paid on `count` of the contracts being sold.

    Read from OUR manual ledger row, which records what the entry actually
    cost in fees. Returns 0.0 when there is no such row — a bot- or
    web-opened position has no manual entry fee for the user to have paid, and
    guessing one would understate the quote instead of overstating it.
    """
    import db
    try:
        with db.get_db() as conn:
            row = db.find_open_manual_position(
                conn, ticker, side, kalshi_auth.get_env())
        if not row:
            return 0.0
        held = int(row["filled_contracts"] or 0)
        fees = _num(row["fees_usd"]) or 0.0
        if held <= 0 or fees <= 0:
            return 0.0
        return round(fees * min(int(count), held) / held, 4)
    except Exception as e:
        logger.debug("terminal: entry-fee share unavailable for %s: %s", ticker, e)
        return 0.0


def _manual_status(filled: Optional[int], target: Optional[int]) -> str:
    """DB status for a manual order, matching trader._db_status_from_order.

    The distinction is load-bearing rather than cosmetic: 'filled' tells the
    rest of the app that nothing is still working on the book, and three
    separate systems act on that — the exposure cap, the pending-order poll,
    and Cancel All. A row born 'filled' with a live remainder is invisible to
    all three, and nothing demotes it later.
    """
    f = int(filled or 0)
    t = int(target or 0)
    if f <= 0:
        return "submitted"
    if t > 0 and f < t:
        return "partial"
    return "filled"


def record_manual_buy(
    *, ticker: str, side: str, count: int, price_cents: float,
    client_order_id: str, order_id: Optional[str], status: str,
    filled: Optional[int], avg_cents: Optional[float], fees_usd: Optional[float],
    title: str = "", event_ticker: str = "", category: str = "",
    env: Optional[str] = None,
) -> Optional[int]:
    """Book a hand-placed BUY. Returns the position row id.

    A second buy on the same side ADDS to the existing row rather than
    inserting a duplicate: Kalshi reports one aggregate position per
    (ticker, side) and the reconcile pass overwrites filled/cost from that
    aggregate, so two local rows would make the reconciler pick between them
    and would double-count the exposure.
    """
    import db
    env = env or kalshi_auth.get_env()
    try:
        with db.get_db() as conn:
            existing = db.find_open_manual_position(conn, ticker, side, env)
            if existing:
                new_filled = int(existing["filled_contracts"] or 0) + int(filled or 0)
                new_target = int(existing["target_contracts"] or 0) + int(count)
                money: dict = {}
                if filled:
                    add_cost = (avg_cents or 0.0) * int(filled) / 100.0
                    new_cost = round((_num(existing["cost_usd"]) or 0.0) + add_cost, 4)
                    money["cost_usd"] = new_cost
                    money["fees_usd"] = round(
                        (_num(existing["fees_usd"]) or 0.0) + float(fees_usd or 0.0), 4)
                    if new_filled > 0:
                        money["avg_fill_price_cents"] = round(
                            new_cost * 100.0 / new_filled, 4)
                db.update_bot_position(
                    conn, existing["id"],
                    target_contracts=new_target,
                    status=(_manual_status(new_filled, new_target)
                            if filled else existing["status"]),
                    kalshi_order_id=order_id or existing["kalshi_order_id"],
                    **({"filled_contracts": new_filled} if filled else {}),
                    **money,
                )
                db.log_event(
                    conn, existing["id"], "manual-buy",
                    kalshi_status=status, filled_contracts=filled,
                    note=(f"added {count} @ {price_cents:g}c "
                          f"(order {order_id or 'unconfirmed'})"),
                )
                return int(existing["id"])

            new_id = db.insert_bot_position(conn, {
                "signal_source": "manual",
                "signal_id": _manual_signal_id(ticker, side),
                "ticker": ticker,
                "event_ticker": event_ticker,
                "title": title or ticker,
                "category": category,
                "direction": side,
                "action": "buy",
                "target_contracts": int(count),
                "limit_price_cents": int(round(price_cents)),
                "filled_contracts": int(filled or 0),
                "avg_fill_price_cents": avg_cents,
                "cost_usd": round((avg_cents or 0) * (filled or 0) / 100.0, 4),
                "client_order_id": client_order_id,
                "kalshi_order_id": order_id,
                "status": _manual_status(filled, count),
                "confidence": 0.0,
                "edge_pts": 0.0,
                "signal_price": float(price_cents),
                "kalshi_env": env,
            })
            if fees_usd:
                db.update_bot_position(conn, new_id, fees_usd=fees_usd)
            db.log_event(
                conn, new_id, "manual-buy", kalshi_status=status,
                filled_contracts=filled,
                note=f"{count} @ {price_cents:g}c (order {order_id or 'unconfirmed'})",
            )
            return int(new_id)
    except Exception as e:
        logger.error(
            "terminal: could not record manual buy %s %s (order %s): %s",
            ticker, side, order_id, e,
        )
        return None


async def record_manual_sell(
    *, ticker: str, side: str, count: int, price_cents: float,
    order_id: Optional[str], status: str, filled: Optional[int],
    env: Optional[str] = None,
) -> None:
    """Book a hand-placed SELL against the position it reduces — including the
    money.

    A sale is not a new position, so it is recorded on the row it closes rather
    than as a second row. But it must actually book its PROCEEDS, and it must
    reconcile them from Kalshi's fills rather than from the limit price we
    asked for: the limit is what we hoped to get, the fills are what we got.

    Getting this wrong was a real, silent bug. Writing only `closed_early=1`
    left the row `resolved=0, filled_contracts=100, cost_usd=40` while the
    position was gone from Kalshi. The engine's own passes then finished the
    job on stale data — the orphan-close path (trader.py) books
    `settlement_usd=0, pnl_usd=0` on a market that is still active, so a +$40
    winning trade reported as $0.00; or, if the market settled first,
    mark_resolved_positions settled the FULL original size and fabricated a win
    or a loss on contracts the user no longer held.

    A full exit therefore resolves the row here and now. A partial exit reduces
    the position's size and basis (average cost, the convention this app
    states) so the remainder settles on its own. If the proceeds cannot be
    reconciled, P&L stays NULL — an em dash — rather than a number nobody
    earned.
    """
    import db
    env = env or kalshi_auth.get_env()
    try:
        with db.get_db() as conn:
            row = db.find_open_manual_position(conn, ticker, side, env)
        if not row:
            logger.info(
                "terminal: manual sell on %s %s has no manual position to "
                "book against (bot- or web-opened); Kalshi's ledger stays "
                "the record.", ticker, side,
            )
            return

        held = int(row["filled_contracts"] or 0)
        cost_usd = _num(row["cost_usd"]) or 0.0
        entry_fees = _num(row["fees_usd"]) or 0.0

        sold, avg_exit_cents = await _reconcile_fills(order_id, side, pin_env=env)
        if sold is None:
            sold = _count(filled)

        with db.get_db() as conn:
            db.log_event(
                conn, row["id"], "manual-sell", kalshi_status=status,
                filled_contracts=sold,
                note=(
                    f"sold {sold if sold is not None else count} of {held} "
                    f"@ {avg_exit_cents:g}c" if avg_exit_cents is not None
                    else f"sold {count} of {held} @ ~{price_cents:g}c "
                         f"(fills unreconciled)"
                ) + f" (order {order_id or 'unconfirmed'})",
            )

            if not sold or held <= 0:
                return

            if avg_exit_cents is None:
                db.update_bot_position(
                    conn, row["id"],
                    closed_early=1 if sold >= held else 0,
                    error=(
                        "A hand-placed sale could not be reconciled against "
                        "Kalshi's fills, so its proceeds are unknown."
                    ),
                )
                return

            proceeds = round(sold * avg_exit_cents / 100.0, 4)
            exit_fee = _fee_usd(avg_exit_cents, sold)

            if sold >= held:
                pnl = round(proceeds - cost_usd - entry_fees - exit_fee, 4)
                db.update_bot_position(
                    conn, row["id"],
                    status="filled", resolved=1, closed_early=1,
                    outcome_correct=None,
                    settlement_usd=proceeds,
                    pnl_usd=pnl,
                    fees_usd=round(entry_fees + exit_fee, 4),
                    resolved_at=_now_iso(),
                )
                logger.info(
                    f"[terminal] closed {ticker} {side} {sold} @ "
                    f"{avg_exit_cents:g}c — proceeds ${proceeds:.2f}, "
                    f"P&L ${pnl:+.2f}"
                )
            else:
                remaining = held - sold
                kept_cost = round(cost_usd * remaining / held, 4)
                kept_fees = round(entry_fees * remaining / held, 4)
                realized = round(
                    proceeds - (cost_usd - kept_cost) - (entry_fees - kept_fees)
                    - exit_fee, 4)
                db.update_bot_position(
                    conn, row["id"],
                    filled_contracts=remaining,
                    target_contracts=remaining,
                    cost_usd=kept_cost,
                    fees_usd=kept_fees,
                )
                closed_id = db.insert_bot_position(conn, {
                    "signal_source": "manual",
                    "signal_id": _manual_signal_id(ticker, side),
                    "ticker": ticker,
                    "event_ticker": row["event_ticker"] or "",
                    "title": row["title"] or ticker,
                    "category": row["category"] or "",
                    "direction": side,
                    "action": "buy",
                    "target_contracts": int(sold),
                    "limit_price_cents": int(round(avg_exit_cents or 0)),
                    "filled_contracts": int(sold),
                    "avg_fill_price_cents": (
                        round((cost_usd - kept_cost) * 100.0 / sold, 4)
                        if sold else None),
                    "cost_usd": round(cost_usd - kept_cost, 4),
                    "client_order_id": f"{MANUAL_ORDER_PREFIX}partial-{order_id or ''}",
                    "kalshi_order_id": order_id,
                    "status": "filled",
                    "confidence": 0.0,
                    "edge_pts": 0.0,
                    "kalshi_env": env,
                })
                db.update_bot_position(
                    conn, closed_id,
                    resolved=1, closed_early=1,
                    outcome_correct=None,
                    settlement_usd=proceeds,
                    pnl_usd=realized,
                    fees_usd=round((entry_fees - kept_fees) + exit_fee, 4),
                    resolved_at=_now_iso(),
                )
                db.log_event(
                    conn, row["id"], "manual-sell-partial",
                    note=(
                        f"realised ${realized:+.2f} on {sold} contract(s); "
                        f"{remaining} left at ${kept_cost:.2f} basis"
                    ),
                )
    except Exception as e:
        logger.error("terminal: could not record manual sell %s %s: %s",
                     ticker, side, e)


def manual_history(limit: int = 300) -> dict:
    """Closed and open hand-placed trades, plus calibration.

    Calibration is the question a prediction-market terminal can answer that
    almost nothing else can: **when you paid 70c for a side, did that side win
    70% of the time?** These contracts settle to exactly 0 or 1, so there is no
    mark-to-model anywhere in it — the answer is arithmetic on closed trades.

    It is also the easiest place in the app to lie. A bucket with three trades
    in it produces a hit rate that looks exactly like one computed from three
    hundred, so a bucket under the minimum reports `hitRate: None` and says how
    many more trades it needs, rather than printing a number.
    """
    import db
    env = kalshi_auth.get_env()
    with db.get_db() as conn:
        rows = db.manual_positions(conn, env, limit=limit)

    def _row(r: dict) -> dict:
        avg = _num(r.get("avg_fill_price_cents"))
        return {
            "id": int(r["id"]),
            "ticker": _text(r.get("ticker")) or "",
            "title": _text(r.get("title")),
            "side": (_text(r.get("direction")) or "yes").lower(),
            "contracts": _count(r.get("filled_contracts")) or 0,
            "avgCostCents": round(avg, 2) if avg is not None else None,
            "costUsd": _num(r.get("cost_usd")),
            "feesUsd": _num(r.get("fees_usd")),
            "status": _text(r.get("status")),
            "resolved": bool(r.get("resolved")),
            "outcomeCorrect": (
                None if r.get("outcome_correct") is None
                else bool(r.get("outcome_correct"))
            ),
            "pnlUsd": _num(r.get("pnl_usd")),
            "settlementUsd": _num(r.get("settlement_usd")),
            "closedEarly": bool(r.get("closed_early")),
            "createdAt": _iso(r.get("created_at")),
            "resolvedAt": _iso(r.get("resolved_at")),
        }

    trades = [_row(r) for r in rows]
    closed = [t for t in trades
              if t["resolved"] and t["outcomeCorrect"] is not None
              and t["avgCostCents"] is not None]

    calibratable = [t for t in closed if not t["closedEarly"]]

    buckets = []
    for lo in range(0, 100, 10):
        hi = lo + 10
        inb = [t for t in calibratable if lo <= t["avgCostCents"] < hi]
        wins = sum(1 for t in inb if t["outcomeCorrect"])
        enough = len(inb) >= MIN_CALIBRATION_TRADES
        buckets.append({
            "loCents": lo,
            "hiCents": hi,
            "trades": len(inb),
            "wins": wins,
            "hitRate": round(wins / len(inb), 4) if enough else None,
            "impliedRate": round(
                sum(t["avgCostCents"] for t in inb) / len(inb) / 100.0, 4
            ) if inb else None,
            "note": None if enough else (
                f"{MIN_CALIBRATION_TRADES - len(inb)} more settled trade(s) in "
                f"this price band before a hit rate means anything."
            ),
        })

    realized = [t["pnlUsd"] for t in trades if t["resolved"] and t["pnlUsd"] is not None]
    fees = [t["feesUsd"] for t in trades if t["feesUsd"] is not None]
    wins = sum(1 for t in closed if t["outcomeCorrect"])
    losses = len(closed) - wins

    return {
        "env": env,
        "trades": trades,
        "closedCount": len(closed),
        "openCount": sum(1 for t in trades if not t["resolved"]),
        "wins": wins,
        "losses": losses,
        "winRate": round(wins / len(closed), 4) if closed else None,
        "realizedUsd": round(sum(realized), 2) if realized else None,
        "feesUsd": round(sum(fees), 2) if fees else None,
        "buckets": buckets,
        "calibratableCount": len(calibratable),
        "minTradesPerBucket": MIN_CALIBRATION_TRADES,
        "fetchedAt": _now_iso(),
        "note": (
            None if calibratable else
            "No settled hand-placed trades yet. Calibration needs trades that "
            "ran to settlement — sold-out positions have a P&L but no yes/no "
            "outcome to score."
        ),
    }



RULE_KINDS = ("stop", "take", "alert")
RULE_CHECK_SEC = 3.0

RULE_LIVENESS_EVERY = 20


def _rule_row(r: dict) -> dict:
    return {
        "id": int(r["id"]),
        "kind": _text(r.get("kind")) or "alert",
        "ticker": _text(r.get("ticker")) or "",
        "title": _text(r.get("title")),
        "side": (_text(r.get("side")) or "yes").lower(),
        "thresholdCents": _num(r.get("threshold_cents")),
        "direction": (_text(r.get("direction")) or "below").lower(),
        "contracts": _count(r.get("contracts")),
        "status": _text(r.get("status")) or "armed",
        "note": _text(r.get("note")),
        "lastError": _text(r.get("last_error")),
        "lastCheckedAt": _iso(r.get("last_checked_at")),
        "lastPriceCents": _num(r.get("last_price_cents")),
        "lastPriceSource": _text(r.get("last_price_source")),
        "unevaluableCount": _count(r.get("unevaluable_count")) or 0,
        "triggeredAt": _iso(r.get("triggered_at")),
        "triggeredOrderId": _text(r.get("triggered_order_id")),
        "createdAt": _iso(r.get("created_at")),
    }


def list_rules(limit: int = 300) -> dict:
    import db
    env = kalshi_auth.get_env()
    with db.get_db() as conn:
        rows = db.list_terminal_rules(conn, env, limit=limit)
    out = [_rule_row(r) for r in rows]
    return {
        "rules": out,
        "armedCount": sum(1 for r in out if r["status"] == "armed"),
        "env": env,
        "fetchedAt": _now_iso(),
    }


def create_rule(req: dict, *, market: Optional[dict] = None,
                market_status: str = "unreachable") -> dict:
    import db
    env = kalshi_auth.get_env()
    kind = (req.get("kind") or "").lower()
    ticker = (req.get("ticker") or "").strip().upper()
    side = (req.get("side") or "yes").lower()
    threshold = price_cents(req.get("thresholdCents"))
    direction = (req.get("direction") or "").lower()
    contracts = _count(req.get("contracts"))

    if kind not in RULE_KINDS:
        raise ValueError(f"kind must be one of {', '.join(RULE_KINDS)}")
    if not ticker:
        raise ValueError("no ticker")
    if side not in ("yes", "no"):
        raise ValueError("side must be yes or no")
    if threshold is None:
        raise ValueError(
            "The threshold must be between 1c and 99c — outside that range "
            "there is no price for it to cross."
        )
    if direction not in ("below", "above"):
        direction = "below" if kind == "stop" else "above"
    if kind in ("stop", "take") and contracts is not None and contracts <= 0:
        raise ValueError("contracts must be positive, or omitted for the whole position")

    if market_status == "missing":
        raise ValueError(
            f"Kalshi has no market called {ticker}. Check the ticker — a rule "
            f"on a market that does not exist can never fire."
        )

    with db.get_db() as conn:
        rid = db.insert_terminal_rule(conn, {
            "kind": kind, "ticker": ticker,
            "title": (market or {}).get("title") or "",
            "side": side, "threshold_cents": threshold, "direction": direction,
            "contracts": contracts, "note": (req.get("note") or "")[:200],
            "kalshi_env": env,
        })
        row = conn.execute(
            "SELECT * FROM terminal_rules WHERE id=?", (rid,)).fetchone()
    note_interest(ticker)
    logger.info(
        f"[terminal] armed {kind} on {ticker} {side} {direction} {threshold:g}c"
    )
    return _rule_row(dict(row))


def cancel_rule(rule_id: int) -> dict:
    import db
    env = kalshi_auth.get_env()
    with db.get_db() as conn:
        ok = db.cancel_terminal_rule(conn, int(rule_id), env)
    return {"ok": bool(ok),
            "message": "Cancelled." if ok else "That rule is not armed."}


RULE_FIRING_STALE_SEC = 120.0


def _recover_stranded_rules(conn, env: str) -> None:
    """Deal with rules left mid-fire by a crash.

    A rule is claimed ('firing') before any money moves, so a process killed
    inside submit() leaves one stranded. It must NOT be re-armed: we do not
    know whether the order landed, and an unattended duplicate sell is a worse
    outcome than a lapsed instruction. So it is marked `error` and says exactly
    what to check — the user decides whether to re-arm."""
    import db as _db
    rows = conn.execute(
        "SELECT id, ticker FROM terminal_rules "
        "WHERE status='firing' AND kalshi_env=? "
        "AND (julianday('now') - julianday(COALESCE(last_checked_at, created_at)))"
        "    * 86400 > ?",
        (env, RULE_FIRING_STALE_SEC),
    ).fetchall()
    for r in rows:
        _db.update_terminal_rule(
            conn, int(r["id"]), status="error", last_error=(
                "The app stopped while this instruction was placing its order. "
                "It was NOT re-armed, because the order may have gone through "
                "and firing again could sell twice. Check your resting orders "
                "and positions, then arm it again if you still want it."
            ),
        )
        logger.warning(
            f"[terminal] rule {r['id']} ({r['ticker']}) was stranded mid-fire; "
            f"marked error rather than re-armed"
        )


def _exit_price_for(book_snapshot: Optional[dict], side: str) -> tuple[Optional[float], Optional[str]]:
    """What this side could actually be SOLD into right now, and where that
    number came from.

    Deliberately the best BID on the held side, not the mid and not the last
    print: a stop loss is a promise about getting out, and the mid is a price
    at which nobody has offered to buy anything. Triggering on a mid that no
    bid supports is how a stop 'fires' into a book that cannot fill it.
    """
    if not book_snapshot:
        return None, None
    if side == "yes":
        return book_snapshot.get("yesBid"), book_snapshot.get("source")
    ask = book_snapshot.get("yesAsk")
    return (price_cents(100 - ask) if ask is not None else None), book_snapshot.get("source")


def _rule_fires(direction: str, price: float, threshold: float) -> bool:
    return price <= threshold if direction == "below" else price >= threshold


async def evaluate_rules(cfg: dict, *, authed: bool, on_event=None) -> list[dict]:
    """One pass over the armed rules. Returns the ones that changed state.

    Failure policy is the whole design: a rule that cannot be priced does
    NOTHING and records why. It is never treated as "not triggered" quietly and
    never as "triggered" defensively — an unknown price is an unknown price,
    and the panel shows the rule as armed-but-unevaluable so the user can see
    that their protection is not currently protecting anything.
    """
    import db
    env = kalshi_auth.get_env()
    with db.get_db() as conn:
        _recover_stranded_rules(conn, env)
        armed = db.list_terminal_rules(conn, env, armed_only=True)
    if not armed:
        return []

    changed: list[dict] = []
    resting_sold: dict[tuple, int] = {}
    try:
        _ro = await resting_orders(True)
        for o in _ro.get("orders") or []:
            if o.get("action") != "sell":
                continue
            n = o.get("remaining")
            if n is None:
                n = o.get("count")
            if not n:
                continue
            key = (o.get("ticker") or "", o.get("side") or "")
            resting_sold[key] = resting_sold.get(key, 0) + int(n)
    except Exception as e:
        logger.info("terminal: resting-order read failed before rules: %s", e)

    slippage = _num(cfg.get("terminal_stop_slippage_cents"))
    slippage = 2.0 if slippage is None else max(0.0, slippage)
    committed: dict[tuple[str, str], int] = {}

    for r in armed:
        rid = int(r["id"])
        ticker = str(r["ticker"])
        side = str(r["side"]).lower()
        kind = str(r["kind"])
        note_interest(ticker)

        try:
            snap = await book(ticker)
        except Exception as e:
            with db.get_db() as conn:
                db.update_terminal_rule(
                    conn, rid, last_checked_at=_now_iso(),
                    last_price_cents=None, last_price_source=None,
                    unevaluable_count=int(r["unevaluable_count"] or 0) + 1,
                    last_error=f"could not read the book: {e}",
                )
            continue

        price, src = _exit_price_for(snap, side)
        if price is None:
            misses = int(r["unevaluable_count"] or 0) + 1
            note = (
                f"Nobody is bidding for {side.upper()} right now, so there is "
                f"no price this rule could act on. It stays armed and will "
                f"fire when a bid returns."
            )
            retire = None
            if misses % RULE_LIVENESS_EVERY == 0:
                try:
                    mkt, status = await _public_gate.run(
                        kalshi_api.fetch_market_checked, ticker)
                except Exception:
                    mkt, status = None, "unreachable"
                if status == "missing":
                    retire = (
                        f"Retired: Kalshi no longer has a market called "
                        f"{ticker}. Nothing here can fire."
                    )
                elif mkt is not None:
                    m_status = _text(mkt.get("status"))
                    if m_status and m_status not in ("active", "open"):
                        retire = (
                            f"Retired: this market is {m_status}, so it will "
                            f"not quote again and this rule cannot fire."
                        )
                    else:
                        note += (
                            f" (still listed as {m_status or 'open'} after "
                            f"{misses} checks with no bid.)"
                        )
            with db.get_db() as conn:
                if retire:
                    db.update_terminal_rule(
                        conn, rid, status="cancelled", last_checked_at=_now_iso(),
                        last_price_cents=None, last_price_source=None,
                        last_error=retire, triggered_at=_now_iso(),
                    )
                    row = conn.execute(
                        "SELECT * FROM terminal_rules WHERE id=?", (rid,)).fetchone()
                else:
                    db.update_terminal_rule(
                        conn, rid, last_checked_at=_now_iso(),
                        last_price_cents=None, last_price_source=None,
                        unevaluable_count=misses, last_error=note,
                    )
                    row = None
            if row is not None:
                changed.append(_rule_row(dict(row)))
                logger.info(f"[terminal] rule {rid} retired: {retire}")
            continue

        with db.get_db() as conn:
            db.update_terminal_rule(
                conn, rid, last_checked_at=_now_iso(),
                last_price_cents=price, last_price_source=src, last_error=None,
                unevaluable_count=0,
            )

        if not _rule_fires(str(r["direction"]), price, float(r["threshold_cents"])):
            continue

        with db.get_db() as conn:
            if not db.claim_terminal_rule(conn, rid, env):
                logger.info(
                    f"[terminal] rule {rid} was cancelled while it was being "
                    f"evaluated — not firing."
                )
                continue

        if kind == "alert":
            with db.get_db() as conn:
                db.update_terminal_rule(
                    conn, rid, status="triggered", triggered_at=_now_iso(),
                )
                row = conn.execute(
                    "SELECT * FROM terminal_rules WHERE id=?", (rid,)).fetchone()
            out = _rule_row(dict(row))
            changed.append(out)
            if on_event:
                await on_event("terminal:rule", {
                    "rule": out,
                    "message": (
                        f"{out['title'] or ticker}: {side.upper()} is "
                        f"{price:g}c ({r['direction']} {float(r['threshold_cents']):g}c)."
                    ),
                })
            continue

        if not authed:
            with db.get_db() as conn:
                db.update_terminal_rule(
                    conn, rid, status="armed", last_error=(
                        "Triggered, but there are no verified credentials for "
                        "this environment, so nothing was sent."
                    ),
                )
            continue

        try:
            pf = await portfolio(True)
            pos = next((x for x in pf["positions"]
                        if x["ticker"] == ticker and x["side"] == side), None)
        except Exception as e:
            with db.get_db() as conn:
                db.update_terminal_rule(
                    conn, rid, status="armed",
                    last_error=f"could not read the position: {e}")
            continue

        if not pos or pos["contracts"] <= 0:
            with db.get_db() as conn:
                db.update_terminal_rule(
                    conn, rid, status="cancelled", triggered_at=_now_iso(),
                    last_error=(
                        "Triggered, but the position was already gone — "
                        "nothing to close, so the rule retired itself."
                    ),
                )
                row = conn.execute(
                    "SELECT * FROM terminal_rules WHERE id=?", (rid,)).fetchone()
            changed.append(_rule_row(dict(row)))
            continue

        already = committed.get((ticker, side), 0)
        already += resting_sold.get((ticker, side), 0)
        avail = int(pos["contracts"]) - already
        if avail <= 0:
            with db.get_db() as conn:
                db.update_terminal_rule(
                    conn, rid, status="armed", last_error=(
                        f"All {pos['contracts']} contract(s) on this market are "
                        f"already committed to another exit — either fired this "
                        f"pass or still resting on the book. Still armed — it "
                        f"will act on whatever is left."
                    ),
                )
            continue
        want = _count(r["contracts"]) or avail
        want = min(want, avail)
        limit = price_cents(price - slippage) or price_cents(price) or price
        res = await submit({
            "ticker": ticker, "side": side, "action": "sell",
            "count": want, "priceCents": limit,
        }, cfg=cfg, authed=True, scope=env)

        with db.get_db() as conn:
            if res.get("ok"):
                committed[(ticker, side)] = already + want
                db.update_terminal_rule(
                    conn, rid, status="triggered", triggered_at=_now_iso(),
                    triggered_order_id=res.get("orderId"), last_error=None,
                )
            elif res.get("status") == "unconfirmed":
                db.update_terminal_rule(
                    conn, rid, status="error", triggered_at=_now_iso(),
                    last_error=res.get("message"),
                )
            else:
                db.update_terminal_rule(
                    conn, rid, status="armed", last_error=(
                        f"Kalshi refused this exit and nothing was sent: "
                        f"{res.get('message')} Still armed — it will try "
                        f"again on the next pass."
                    ),
                )
            row = conn.execute(
                "SELECT * FROM terminal_rules WHERE id=?", (rid,)).fetchone()
        out = _rule_row(dict(row))
        changed.append(out)
        logger.info(
            f"[terminal] {kind} fired on {ticker} {side} at {price:g}c "
            f"-> sell {want} @ {limit:g}c: {res.get('message')}"
        )
        if on_event:
            await on_event("terminal:rule", {
                "rule": out,
                "message": (
                    f"{kind.upper()} fired on {out['title'] or ticker}: "
                    f"{res.get('message')}"
                ),
            })
    return changed



MICRO_MAX_SAMPLES = 900
MICRO_SAMPLE_SEC = 1.0

_micro: dict[str, deque] = {}
_micro_last_sample = 0.0


def sample_microstructure() -> int:
    """Take one top-of-book sample for every market a screen currently has
    open. Cheap and synchronous: it reads the local websocket book, and records
    NOTHING when the socket is not live — a gap in this series means "we were
    not watching", which is a fact, whereas a REST-filled point would be a
    different measurement wearing the same shape."""
    global _micro_last_sample
    now = time.monotonic()
    if now - _micro_last_sample < MICRO_SAMPLE_SEC:
        return 0
    _micro_last_sample = now
    if not kalshi_ws.is_connected():
        return 0

    wanted = subscribed_tickers()
    for dead in [t for t in _micro if t not in wanted]:
        _micro.pop(dead, None)

    n = 0
    for t in wanted:
        raw = kalshi_ws.orderbook(t)
        if raw is None:
            continue
        yes, yes_depth = _ladder(raw.get("yes") or [], limit=1)
        no, no_depth = _ladder(raw.get("no") or [], limit=1)
        bid = yes[0]["priceCents"] if yes else None
        ask = price_cents(100 - no[0]["priceCents"]) if no else None
        buf = _micro.setdefault(t, deque(maxlen=MICRO_MAX_SAMPLES))
        buf.append({
            "ts": time.time(),
            "bid": bid,
            "ask": ask,
            "bidSize": yes[0]["contracts"] if yes else None,
            "askSize": no[0]["contracts"] if no else None,
        })
        n += 1
    return n


def microstructure(ticker: str, probe_cents: Optional[float] = None) -> dict:
    ticker = (ticker or "").strip().upper()
    note_interest(ticker)
    buf = list(_micro.get(ticker) or [])

    if not buf:
        return {
            "ticker": ticker,
            "samples": [],
            "sampleCount": 0,
            "windowSec": None,
            "twoSidedPct": None,
            "medianSpreadCents": None,
            "p90SpreadCents": None,
            "bestSpreadCents": None,
            "quoteLifetimeSec": None,
            "probeCents": probe_cents,
            "probeFillablePct": None,
            "note": (
                "This is built from our own websocket book, and Kalshi's "
                "websocket handshake is signed — so it needs a verified API "
                "key for this environment before it can record anything. Add "
                "one in API Keys."
                if not kalshi_ws.is_connected()
                else "Recording — the first samples land within a few seconds."
            ),
        }

    spreads = [
        round(s["ask"] - s["bid"], 1)
        for s in buf if s["bid"] is not None and s["ask"] is not None
    ]
    two_sided = len(spreads)
    window = round(buf[-1]["ts"] - buf[0]["ts"], 1) if len(buf) > 1 else 0.0

    def _pct(vals: list[float], q: float) -> Optional[float]:
        if not vals:
            return None
        ordered = sorted(vals)
        idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
        return ordered[idx]

    lifetimes: list[float] = []
    run_start = buf[0]["ts"]
    prev = (buf[0]["bid"], buf[0]["ask"])
    prev_ts = buf[0]["ts"]
    for s in buf[1:]:
        cur = (s["bid"], s["ask"])
        if s["ts"] - prev_ts > MICRO_SAMPLE_SEC * 2:
            run_start = s["ts"]
            prev = cur
            prev_ts = s["ts"]
            continue
        if cur != prev:
            lifetimes.append(s["ts"] - run_start)
            run_start = s["ts"]
            prev = cur
        prev_ts = s["ts"]
    lifetime = round(sum(lifetimes) / len(lifetimes), 2) if lifetimes else None

    fillable = None
    probe = price_cents(probe_cents) if probe_cents is not None else None
    if probe is not None:
        asks = [s["ask"] for s in buf if s["ask"] is not None]
        if asks:
            fillable = round(sum(1 for a in asks if a <= probe) / len(asks), 4)

    return {
        "ticker": ticker,
        "samples": buf[:: max(1, len(buf) // 240)],
        "sampleCount": len(buf),
        "windowSec": window,
        "twoSidedPct": round(two_sided / len(buf), 4),
        "medianSpreadCents": _pct(spreads, 0.5),
        "p90SpreadCents": _pct(spreads, 0.9),
        "bestSpreadCents": min(spreads) if spreads else None,
        "quoteLifetimeSec": lifetime,
        "probeCents": probe,
        "probeFillablePct": fillable,
        "note": (
            f"Our own socket, {len(buf)} samples over {window:.0f}s. "
            f"Gaps mean the socket was down or this market was not subscribed "
            f"— nothing is interpolated."
        ),
    }



HOSTS: list[dict] = [
    {
        "host": "api.elections.kalshi.com",
        "purpose": "Kalshi's production API — market data, and your account "
                   "in Live mode. In Paper mode only the unauthenticated "
                   "market reads are made.",
        "when": "constantly while the Terminal or the bot is open",
        "sends": "your API key signature on account calls (Live mode only, "
                 "plus the key test you click); market reads are "
                 "unauthenticated",
        "required": True,
        "optional_off": None,
    },
    {
        "host": "external-api-ws.kalshi.com",
        "purpose": "Kalshi's production websocket — live quotes, order book "
                   "and fills. This is the feed the Terminal's own "
                   "microstructure view is built from.",
        "when": "one persistent connection while the backend runs in Live "
                "mode (never in Paper: its handshake is signed)",
        "sends": "your API key signature on the handshake",
        "required": True,
        "optional_off": "KRYPT_KALSHI_WS=0",
    },
    {
        "host": "external-api-margin-ws.kalshi.com",
        "purpose": "Kalshi's perpetual-futures websocket, for the Perpetuals "
                   "volume farmer.",
        "when": "only while the perps farmer is switched on",
        "sends": "your API key signature on the handshake",
        "required": False,
        "optional_off": "turn off Perpetuals",
    },
    {
        "host": "advanced-trade-ws.coinbase.com",
        "purpose": "Coinbase's public price feed — the spot reference the 15m "
                   "crypto model prices against.",
        "when": "while the 15m crypto engine is running",
        "sends": "nothing about you; it is a public market feed",
        "required": False,
        "optional_off": "turn off the 15m crypto engine",
    },
    {
        "host": "api.coinbase.com",
        "purpose": "Coinbase REST, used as the spot fallback when the socket "
                   "is down.",
        "when": "occasionally, while the 15m crypto engine is running",
        "sends": "nothing about you",
        "required": False,
        "optional_off": "turn off the 15m crypto engine",
    },
    {
        "host": "api.hyperliquid.xyz",
        "purpose": "Public candle history, used to backfill the 15m crypto "
                   "research dataset.",
        "when": "only when you run a backfill",
        "sends": "nothing about you",
        "required": False,
        "optional_off": "do not run backfills",
    },
    {
        "host": "min-api.cryptocompare.com",
        "purpose": "CF Benchmarks reference prices — the index Kalshi's crypto "
                   "markets actually settle against.",
        "when": "while the 15m crypto engine is running",
        "sends": "nothing about you",
        "required": False,
        "optional_off": "turn off the 15m crypto engine",
    },
    {
        "host": "api.coingecko.com",
        "purpose": "Public reference prices.",
        "when": "occasionally, as a spot fallback",
        "sends": "nothing about you",
        "required": False,
        "optional_off": "turn off the 15m crypto engine",
    },
    {
        "host": "discord.com",
        "purpose": "TWO things, both yours and both off unless you set them up. "
                   "(1) Your own webhook, if you paste one in Settings — that "
                   "posts your balance, P&L, positions and signals to a server "
                   "you control. (2) Replies from your own remote-control bot, "
                   "when the Discord remote is on, carrying whatever you asked "
                   "it for. Nothing is sent to us: this app has no backend and "
                   "reports nothing home.",
        "when": "your webhook: only when a URL is configured. Your bot: while "
                "the Discord remote is enabled.",
        "sends": "whatever you configured it to — balance, P&L, open "
                 "positions, signals",
        "required": False,
        "optional_off": "clear the webhook URLs in Settings, and turn off the "
                        "Discord remote",
    },
    {
        "host": "gateway.discord.gg",
        "purpose": "Discord's realtime gateway, for YOUR bot — the connection "
                   "that lets you message the terminal from a phone. Only "
                   "opened when you switch the Discord remote on.",
        "when": "a persistent connection while the Discord remote is enabled",
        "sends": "your bot token on the handshake",
        "required": False,
        "optional_off": "turn off the Discord remote",
    },
    {
        "host": "api.telegram.org",
        "purpose": "Telegram's bot API, for YOUR bot. Anything you ask it — "
                   "balance, positions, orders — is answered through "
                   "Telegram's servers, so those figures pass through them in "
                   "a form Telegram can read. That is inherent to using a chat "
                   "app as a terminal, and is why the remote is off by default.",
        "when": "a held long-poll while the Telegram remote is enabled",
        "sends": "your bot token, and the balance/position figures you ask for",
        "required": False,
        "optional_off": "turn off the Telegram remote",
    },
    {
        "host": "gamma-api.polymarket.com",
        "purpose": "Polymarket's public market metadata and quotes, used ONLY "
                   "to show you the same question's price on the other venue. "
                   "This app never sends an order to Polymarket — no wallet, "
                   "no collateral, no signing.",
        "when": "when you open the cross-venue panel on a market page",
        "sends": "nothing about you; it is an unauthenticated public read",
        "required": False,
        "optional_off": "do not open the cross-venue panel",
    },
    {
        "host": "clob.polymarket.com",
        "purpose": "Polymarket's order-book service, for a depth read on a "
                   "matched market. Public and unauthenticated.",
        "when": "when you open the cross-venue panel on a market page",
        "sends": "nothing about you",
        "required": False,
        "optional_off": "do not open the cross-venue panel",
    },
    {
        "host": "external-api.kalshi.com",
        "purpose": "Kalshi's perpetual-futures (margin) REST API — public perps "
                   "market data, and your perps wallet, positions and orders.",
        "when": "while the Perpetuals page is open, and while the volume "
                "farmer runs",
        "sends": "your API key signature on wallet/position/order calls; "
                 "market reads are unauthenticated",
        "required": False,
        "optional_off": "stay off the Perpetuals page and leave the farmer off",
    },
    {
        "host": "api.anthropic.com",
        "purpose": "Anthropic's API, when Claude is your AI provider: market "
                   "analysis, Autopilot, and the free model listing behind "
                   "Test connection.",
        "when": "only when you press Analyse or Test connection, or while "
                "Autopilot is on, with Anthropic selected",
        "sends": "your Anthropic API key, and the market data shown on the "
                 "page you analysed (prices, rules, your position in it). "
                 "Autopilot also sends the results of the tools it calls.",
        "required": False,
        "optional_off": "pick another AI provider, or do not use AI analysis",
    },
    {
        "host": "api.openai.com",
        "purpose": "OpenAI's API, when OpenAI is your AI provider: market "
                   "analysis, Autopilot, and the free model listing behind "
                   "Test connection.",
        "when": "only when you press Analyse or Test connection, or while "
                "Autopilot is on, with OpenAI selected",
        "sends": "your OpenAI API key, and the market data shown on the page "
                 "you analysed. Autopilot also sends its tool results.",
        "required": False,
        "optional_off": "pick another AI provider, or do not use AI analysis",
    },
    {
        "host": "openrouter.ai",
        "purpose": "OpenRouter, when it is your AI provider: one key routed to "
                   "the model you picked, which OpenRouter forwards to that "
                   "model's own company. Also the public model list.",
        "when": "only when you press Analyse or Test connection, or while "
                "Autopilot is on, with OpenRouter selected",
        "sends": "your OpenRouter key, and the market data you analysed — "
                 "which OpenRouter passes on to the model's provider. No app "
                 "name or referrer header is sent.",
        "required": False,
        "optional_off": "pick another AI provider, or do not use AI analysis",
    },
    {
        "host": "generativelanguage.googleapis.com",
        "purpose": "Google's Gemini API, when Gemini is your AI provider: "
                   "market analysis (optionally grounded with Google Search), "
                   "Autopilot, and the free model listing.",
        "when": "only when you press Analyse or Test connection, or while "
                "Autopilot is on, with Gemini selected",
        "sends": "your Gemini API key (in a header, never the URL), and the "
                 "market data you analysed. On Google's free tier, Google may "
                 "use what you send to improve its products.",
        "required": False,
        "optional_off": "pick another AI provider, or do not use AI analysis",
    },
    {
        "host": "127.0.0.1:11434",
        "purpose": "Ollama, on this machine, when it is your AI provider. The "
                   "model runs locally; nothing goes over the internet.",
        "when": "only when you press Analyse or Test connection, or while "
                "Autopilot is on, with Ollama selected",
        "sends": "the market data you analysed — to a program on this "
                 "machine, not to anyone else. No key.",
        "required": False,
        "optional_off": "pick another AI provider, or do not use AI analysis",
    },
    {
        "host": "127.0.0.1:1234",
        "purpose": "LM Studio's local server, on this machine, when it is your "
                   "AI provider. The model runs locally; nothing goes over the "
                   "internet.",
        "when": "only when you press Analyse or Test connection, or while "
                "Autopilot is on, with LM Studio selected",
        "sends": "the market data you analysed — to a program on this "
                 "machine, not to anyone else. No key.",
        "required": False,
        "optional_off": "pick another AI provider, or do not use AI analysis",
    },
]


def network_report() -> dict:
    """The Privacy panel's payload: the catalogue above, joined to live counts.

    A host with zero calls is still listed — the point is what the app CAN
    contact, not only what it happened to contact since launch.
    """
    stats = kalshi_api.net_stats()
    rows = []
    for h in HOSTS:
        st = stats.get(h["host"])
        rows.append({
            **h,
            "calls": st["calls"] if st else None,
            "errors": st["errors"] if st else None,
            "lastMs": st["lastMs"] if st else None,
            "avgMs": st["avgMs"] if st else None,
            "lastAt": (
                datetime.fromtimestamp(st["lastAt"], timezone.utc)
                .isoformat(timespec="seconds").replace("+00:00", "Z")
                if st and st.get("lastAt") else None
            ),
            "lastError": st["lastError"] if st else None,
        })

    named = {h["host"] for h in HOSTS}
    unlisted = [
        {"host": k, **v} for k, v in stats.items() if k not in named
    ]

    ws = kalshi_ws.stats()
    return {
        "hosts": rows,
        "unlisted": unlisted,
        "totalCalls": sum(r["calls"] or 0 for r in rows) + sum(
            u.get("calls") or 0 for u in unlisted),
        "websocket": {
            "enabled": bool(ws.get("enabled")),
            "connected": bool(ws.get("connected")),
            "env": ws.get("env"),
            "subscribedBooks": ws.get("books"),
            "lastMsgAgeSec": ws.get("lastMsgAgeSec"),
        },
        "fetchedAt": _now_iso(),
        "note": (
            "Counts are for this backend session only and reset when it "
            "restarts. There is no server in the middle: your machine talks to "
            "these hosts directly, which is also why this list is the whole "
            "story."
        ),
    }



async def market_detail(ticker: str, *, authed: bool) -> dict:
    """Assemble one entity page.

    Every panel is fetched concurrently and failures are collected per panel
    rather than raised: a dead order book must not hold the whole page shut,
    and the same on-chain-style read must not fire once per assembler.
    """
    ticker = (ticker or "").strip().upper()
    note_interest(ticker)
    errors: list[dict] = []

    async def _safe(panel: str, coro):
        try:
            return await coro
        except Exception as e:
            errors.append({"panel": panel, "message": str(e)})
            return None

    async def _market_checked(t: str):
        m, status = await kalshi_api.fetch_market_checked(t)
        if status == "unreachable":
            return None
        if m:
            kalshi_api._note_shard(m)
        return (m, status)

    checked, book_snapshot = await asyncio.gather(
        _safe("market", _public_gate.run(_market_checked, ticker)),
        _safe("book", book(ticker)),
    )
    if checked is None:
        why = next((e["message"] for e in errors if e["panel"] == "market"), None)
        raise RuntimeError(why or (
            f"Could not reach Kalshi to load {ticker} just now (network, or "
            f"Kalshi's rate limit). The ticker may be fine — try again in a "
            f"moment."))
    raw_market, found = checked
    if found != "found" or not raw_market:
        raise RuntimeError(
            f"Kalshi has no market called {ticker}. Check the ticker — the "
            f"terminal will not invent a page for a market that does not exist."
        )

    row = _apply_live_quote(market_row(raw_market))
    event_ticker = row.get("eventTicker")
    series_ticker = row.get("seriesTicker")

    raw_event, raw_series, pf = await asyncio.gather(
        _safe("event", _public_gate.run(kalshi_api.fetch_event, event_ticker))
        if event_ticker else _noop(),
        _safe("series", _public_gate.run(kalshi_api.fetch_series, series_ticker))
        if series_ticker else _noop(),
        _safe("portfolio", portfolio(authed)) if authed else _noop(),
    )

    event = None
    siblings: list[dict] = []
    if isinstance(raw_event, dict):
        ctx = {
            "category": _text(raw_event.get("category")),
            "seriesTicker": _text(raw_event.get("series_ticker")),
            "eventTicker": _text(raw_event.get("event_ticker")),
        }
        row = _apply_live_quote(market_row(raw_market, ctx=ctx))
        sib_raw = raw_event.get("markets")
        if isinstance(sib_raw, list):
            siblings = [_apply_live_quote(market_row(m, ctx=ctx)) for m in sib_raw
                        if _text(m.get("ticker")) != ticker]
        event = {
            "eventTicker": _text(raw_event.get("event_ticker")) or (event_ticker or ""),
            "title": _text(raw_event.get("title")),
            "subTitle": _text(raw_event.get("sub_title")),
            "category": _text(raw_event.get("category")),
            "siblings": siblings,
        }

    series = None
    if isinstance(raw_series, dict):
        series = {
            "seriesTicker": _text(raw_series.get("ticker")) or (series_ticker or ""),
            "title": _text(raw_series.get("title")),
            "frequency": _text(raw_series.get("frequency")),
            "contractUrl": _text(raw_series.get("contract_url")),
        }

    coherence_set = siblings + [row] if siblings else []
    risk = resolution_risk(
        ticker=ticker, market=raw_market,
        series=raw_series if isinstance(raw_series, dict) else None,
        event=raw_event if isinstance(raw_event, dict) else None,
        book_snapshot=book_snapshot, siblings=coherence_set,
    )

    row, drift = _apply_book_quote(row, book_snapshot)

    position = None
    if isinstance(pf, dict):
        position = next((p for p in pf.get("positions", []) if p["ticker"] == ticker), None)

    orders: list[dict] = []
    if authed:
        got = await _safe("orders", resting_orders(True, ticker))
        if isinstance(got, dict):
            orders = got.get("orders", [])

    return {
        "market": row,
        "event": event,
        "series": series,
        "risk": risk,
        "book": book_snapshot,
        "position": position,
        "restingOrders": orders,
        "quoteDriftCents": drift,
        "fetchedAt": _now_iso(),
        "errors": errors,
    }


async def _noop():
    return None
