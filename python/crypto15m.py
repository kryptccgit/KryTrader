from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Optional

import httpx

import cf_ws
import kalshi_api
import kalshi_auth
import kalshi_ws
import indicators
import spot_ws

logger = logging.getLogger(__name__)


SERIES: list[dict[str, str]] = [
    {"asset": "BTC",  "series": "KXBTC15M",  "cg": "bitcoin"},
    {"asset": "ETH",  "series": "KXETH15M",  "cg": "ethereum"},
    {"asset": "SOL",  "series": "KXSOL15M",  "cg": "solana"},
    {"asset": "XRP",  "series": "KXXRP15M",  "cg": "ripple"},
    {"asset": "DOGE", "series": "KXDOGE15M", "cg": "dogecoin"},
    {"asset": "HYPE", "series": "KXHYPE15M", "cg": "hyperliquid"},
    {"asset": "BNB",  "series": "KXBNB15M",  "cg": "binancecoin"},
]

ALL_ASSETS = [s["asset"] for s in SERIES]


def asset_enabled(cfg: dict, asset: str) -> bool:
    """True if the executor may open NEW positions on `asset`. None/missing
    `crypto15m_assets` = all enabled; a list restricts to those symbols (an
    empty list disables every asset). Monitoring/snapshots are unaffected —
    this only gates entries."""
    raw = (cfg or {}).get("crypto15m_assets")
    if isinstance(raw, list):
        return asset.upper() in {str(a).upper() for a in raw}
    return True

_DEFAULTS: dict[str, float] = {
    "time_delay_min": 8.0,
    "entry_threshold": 0.95,
    "exit_threshold": 0.40,
    "entry_max": 0.98,
    "min_delta_pct": 0.0,
    "entry_diff": 0.02,
}

_CRYPTOCOMPARE_URL = "https://min-api.cryptocompare.com/data/pricemulti"
_COINBASE_URL = "https://api.coinbase.com/v2/prices/{sym}-USD/spot"
_COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"
_SPOT_CACHE_TTL = 10.0
_QUARTER_SEC = 15 * 60

_spot_client: Optional[httpx.AsyncClient] = None

_spot_cache: dict = {"at": 0.0, "spots": {}, "source": "none"}

_window_open: dict[tuple[str, int], float] = {}


def _get_spot_client() -> httpx.AsyncClient:
    global _spot_client
    if _spot_client is None or _spot_client.is_closed:
        _spot_client = httpx.AsyncClient(
            timeout=8.0,
            headers={"Accept": "application/json", "User-Agent": "KryptTrader/1.0"},
            event_hooks=kalshi_api.counting_hooks(),
        )
    return _spot_client


async def close_clients() -> None:
    global _spot_client
    if _spot_client and not _spot_client.is_closed:
        try:
            await _spot_client.aclose()
        except Exception:
            pass
    _spot_client = None


def _const(cfg: dict, key: str) -> float:
    try:
        return float(cfg.get(f"crypto15m_{key}", _DEFAULTS[key]))
    except (TypeError, ValueError):
        return _DEFAULTS[key]


def _to_float(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _price_dollars(m: dict, key: str) -> float:
    d = m.get(f"{key}_dollars")
    if d is not None:
        return _to_float(d)
    return _to_float(m.get(key)) / 100.0


def _mid_up(yes_bid: float, yes_ask: float, last_price: float) -> float:
    """Up/yes probability (0..1) from quotes. Average ONLY when both sides are
    present — a one-sided book must use the single quote, never (bid+0)/2, which
    halves the probability and trips spurious stop-loss sells / wrong-side rule
    entries. Falls back to last_price when the book is empty."""
    if yes_bid and yes_ask:
        up = (yes_bid + yes_ask) / 2
    elif yes_bid:
        up = yes_bid
    elif yes_ask:
        up = yes_ask
    else:
        up = last_price
    return max(0.0, min(1.0, up))


def _parse_close_epoch(close_time: str) -> Optional[float]:
    if not close_time:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            ct = datetime.strptime(close_time, fmt)
            if ct.tzinfo is None:
                ct = ct.replace(tzinfo=timezone.utc)
            return ct.timestamp()
        except ValueError:
            continue
    return None


async def _spots_cryptocompare(client: httpx.AsyncClient) -> dict[str, float]:
    syms = ",".join(s["asset"] for s in SERIES)
    resp = await client.get(_CRYPTOCOMPARE_URL, params={"fsyms": syms, "tsyms": "USD"})
    resp.raise_for_status()
    data = resp.json() or {}
    if isinstance(data, dict) and data.get("Response") == "Error":
        raise RuntimeError(str(data.get("Message") or "cryptocompare error"))
    out: dict[str, float] = {}
    for s in SERIES:
        px = (data.get(s["asset"]) or {}).get("USD")
        if px is not None:
            out[s["asset"]] = float(px)
    return out


async def _spots_coinbase(client: httpx.AsyncClient) -> dict[str, float]:
    async def one(s: dict) -> tuple[str, Optional[float]]:
        try:
            r = await client.get(_COINBASE_URL.format(sym=s["asset"]))
            r.raise_for_status()
            amt = ((r.json() or {}).get("data") or {}).get("amount")
            return s["asset"], (float(amt) if amt is not None else None)
        except Exception:
            return s["asset"], None

    results = await asyncio.gather(*[one(s) for s in SERIES])
    return {a: px for a, px in results if px is not None}


async def _spots_coingecko(client: httpx.AsyncClient) -> dict[str, float]:
    ids = ",".join(s["cg"] for s in SERIES)
    resp = await client.get(_COINGECKO_URL, params={"ids": ids, "vs_currencies": "usd"})
    resp.raise_for_status()
    data = resp.json()
    out: dict[str, float] = {}
    for s in SERIES:
        px = (data.get(s["cg"]) or {}).get("usd")
        if px is not None:
            out[s["asset"]] = float(px)
    return out


_SPOT_SOURCES = [
    ("cryptocompare", _spots_cryptocompare),
    ("coinbase", _spots_coinbase),
    ("coingecko", _spots_coingecko),
]


async def fetch_spots() -> tuple[dict[str, float], str]:
    cf = cf_ws.fresh_spots()
    cb = spot_ws.fresh_spots()

    loop = asyncio.get_event_loop()
    now = loop.time()
    if _spot_cache["spots"] and (now - _spot_cache["at"]) < _SPOT_CACHE_TTL:
        base, source = dict(_spot_cache["spots"]), _spot_cache["source"]
    else:
        base, source = {}, "unavailable"
        client = _get_spot_client()
        for name, fn in _SPOT_SOURCES:
            try:
                spots = await fn(client)
            except Exception as e:
                logger.debug(f"crypto15m spot source {name} failed: {e}")
                continue
            if spots:
                _spot_cache.update(at=now, spots=dict(spots), source=name)
                base, source = dict(spots), name
                break
        if not base and _spot_cache["spots"]:
            base, source = dict(_spot_cache["spots"]), f"{_spot_cache['source']} (stale)"

    merged = {**base, **cb, **cf}
    if not merged:
        return base, source
    parts = []
    if cf:
        parts.append("kalshi-cf")
    if cb and (set(cb) - set(cf)):
        parts.append("coinbase-ws")
    if set(merged) - set(cf) - set(cb):
        parts.append(source)
    return merged, "+".join(parts) if parts else source


_HYPERLIQUID_URL = "https://api.hyperliquid.xyz/info"
_INDICATOR_LOOKBACK_MIN = 90
_INDICATOR_CACHE_TTL = 60.0
_indicator_cache: dict[str, dict] = {}


async def _fetch_closes(
    asset: str, client: httpx.AsyncClient, lookback_min: int
) -> tuple[list[float], list[float]]:
    """The last `lookback_min` one-minute (closes, volumes) for `asset` from
    Hyperliquid, oldest→newest and index-aligned. Volume powers the true VWAP
    field; a candle missing either is skipped so the two lists stay aligned.
    Empty lists on any error (caller degrades to None fields)."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    body = {
        "type": "candleSnapshot",
        "req": {
            "coin": asset,
            "interval": "1m",
            "startTime": now_ms - int(lookback_min) * 60_000,
            "endTime": now_ms,
        },
    }
    resp = await client.post(_HYPERLIQUID_URL, json=body)
    resp.raise_for_status()
    rows = resp.json()
    if not isinstance(rows, list):
        raise RuntimeError("unexpected candleSnapshot shape")
    closes: list[float] = []
    volumes: list[float] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        c = r.get("c")
        if not c:
            continue
        try:
            closes.append(float(c))
        except (TypeError, ValueError):
            continue
        try:
            volumes.append(float(r.get("v")) if r.get("v") is not None else 0.0)
        except (TypeError, ValueError):
            volumes.append(0.0)
    return closes, volumes


async def asset_indicators(asset: str) -> dict:
    """MACD/RSI bundle for one asset's underlying, cached ~60s and shared by
    the monitor poll, executor tick and recorder. All-None on any failure or
    until there's enough candle history."""
    loop = asyncio.get_event_loop()
    now = loop.time()
    cached = _indicator_cache.get(asset)
    if cached and (now - cached["at"]) < cached.get("ttl", _INDICATOR_CACHE_TTL):
        return cached["data"]
    try:
        closes, volumes = await _fetch_closes(asset, _get_spot_client(), _INDICATOR_LOOKBACK_MIN)
        data = indicators.compute(closes, volumes)
        _indicator_cache[asset] = {"at": now, "data": data, "ttl": _INDICATOR_CACHE_TTL}
        return data
    except Exception as e:
        logger.debug(f"crypto15m indicators {asset} failed: {e}")
        data = cached["data"] if cached else indicators.compute([])
        _indicator_cache[asset] = {"at": now, "data": data, "ttl": 10.0}
        return data


def _blank_asset(entry: dict, spot: Optional[float], error: Optional[str] = None) -> dict:
    return {
        "asset": entry["asset"], "series": entry["series"],
        "spotUsd": spot, "open15mUsd": None, "deltaUsd": None, "deltaPct": None,
        "hasMarket": False, "ticker": None, "closeTime": None, "minsLeft": None,
        "upProb": None, "downProb": None, "favorite": None,
        "favoritePrice": None, "entryCost": None, "yesBid": None, "yesAsk": None,
        "inWindow": False, "signal": False, "openMarketCount": 0, "error": error,
        "hourUtc": None, "peersAgree": None, "marketBias": None,
        "upAsk": None, "downAsk": None, "arbEdgeCents": None, "arbSignal": None,
        "macd": None, "macdSignal": None, "macdHist": None,
        "macdCross": None, "rsi": None,
        "strikeUsd": None, "deltaSignedPct": None, "sigma1m": None,
        "modelProb": None, "edgeNetCents": None,
        "settlePrints": 0,
    }


def hours_ok(cfg: dict, hour: Optional[int] = None) -> bool:
    hrs = (cfg or {}).get("crypto15m_hours")
    if isinstance(hrs, list):
        if hour is None:
            hour = datetime.now(timezone.utc).hour
        return int(hour) in {int(h) for h in hrs}
    try:
        start = int(cfg.get("crypto15m_hours_start_utc", 0) or 0)
        end = int(cfg.get("crypto15m_hours_end_utc", 24) or 24)
    except (TypeError, ValueError):
        return True
    start, end = start % 24, (end % 24 if end != 24 else 24)
    if start == end or (start == 0 and end == 24):
        return True
    if hour is None:
        hour = datetime.now(timezone.utc).hour
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _market_strike(m: dict) -> Optional[float]:
    """The market's strike / reference price — the level the underlying must be
    above at close for YES/up to win. The self-tracked `open15m` (first cached
    spot seen after the boundary) drifts from Kalshi's actual strike, and is
    plain WRONG after a mid-window restart; the market object carries the real
    number, so prefer it always."""
    for k in ("floor_strike", "floor_strike_dollars", "cap_strike",
              "strike", "strike_dollars"):
        v = m.get(k)
        if v in (None, ""):
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0:
            return f
    return None


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def model_up_prob(
    spot: Optional[float], strike: Optional[float],
    sigma_1m: Optional[float], mins_left: Optional[float],
) -> Optional[float]:
    """Terminal-spot model P(up): probability the spot ends above the strike at
    close, treating the remaining move as N(0, (σ√t·spot)²) with σ the realized
    1-minute return vol. Kept as the simple fallback — settlement_up_prob is
    the production model (Kalshi settles on a 60s AVERAGE, not the endpoint)."""
    if spot is None or strike is None or sigma_1m is None or mins_left is None:
        return None
    if spot <= 0 or strike <= 0 or sigma_1m <= 0:
        return None
    t = max(0.05, float(mins_left))
    sd_abs = sigma_1m * math.sqrt(t) * spot
    if sd_abs <= 0:
        return None
    return max(0.0, min(1.0, _norm_cdf((spot - strike) / sd_abs)))


_SETTLE_PRINTS = 60
_SETTLE_AVG_EQUIV_MIN = (60 * 61 * 121 / 6) / (60.0 ** 2) / 60.0


def settlement_up_prob(
    spot: Optional[float], strike: Optional[float],
    sigma_1m: Optional[float], mins_left: Optional[float],
    *, partial_sum: float = 0.0, partial_count: int = 0,
) -> Optional[float]:
    """P(up) under Kalshi's REAL settlement rule: the mean of ~60 one-second
    index prints over the final minute, not the terminal spot.

    Outside the final minute: diffusion to the window start plus the fixed
    variance of the 60-print average (≈0.342 min equivalent — continuous with
    the in-window branch at exactly 1 minute left).

    Inside the final minute the settlement value is being REALIZED print by
    print: `partial_sum/partial_count` are the prints already observed (from
    spot_ws.window_partial); only the future prints are uncertain, so with 30
    of 60 in, half the settlement is already locked. Elapsed-but-unobserved
    prints (feed started late) are approximated at the current spot — a small
    bias toward spot, zero variance, strictly better than ignoring them."""
    if spot is None or strike is None or sigma_1m is None or mins_left is None:
        return None
    if spot <= 0 or strike <= 0 or sigma_1m <= 0:
        return None

    if mins_left > 1.0:
        t_eff = (float(mins_left) - 1.0) + _SETTLE_AVG_EQUIV_MIN
        sd = sigma_1m * math.sqrt(t_eff) * spot
        if sd <= 0:
            return None
        return max(0.0, min(1.0, _norm_cdf((spot - strike) / sd)))

    n_future = max(1, int(round(max(0.0, float(mins_left)) * 60.0)))
    n_future = min(n_future, _SETTLE_PRINTS)
    elapsed = _SETTLE_PRINTS - n_future
    k = max(0, min(int(partial_count or 0), elapsed))
    s = float(partial_sum or 0.0) if k > 0 else 0.0
    if k > 0 and partial_count and k < int(partial_count):
        s = s * (k / float(partial_count))
    missing = elapsed - k
    mean = (s + (missing + n_future) * spot) / float(_SETTLE_PRINTS)
    sigma_1s = sigma_1m / math.sqrt(60.0)
    var = (
        (spot * sigma_1s) ** 2
        * (n_future * (n_future + 1) * (2 * n_future + 1) / 6.0)
        / float(_SETTLE_PRINTS ** 2)
    )
    if var <= 0:
        return None
    return max(0.0, min(1.0, _norm_cdf((mean - strike) / math.sqrt(var))))


def _fee_cents(price_cents: float, contracts: int = 1) -> float:
    """Kalshi taker fee in cents/contract, CEIL-aware: Kalshi rounds the
    per-order fee UP to the next cent, so a 1-lot at 97c pays 1.0c — not the
    0.20c the continuous 7·p·(1−p) curve claims. The continuous model
    overstated net edge by up to ~0.8c exactly at the deep-favorite prices
    the sniper buys. Defaults to the 1-lot (worst, most conservative) fee;
    per-contract fee only falls as size grows."""
    import backtest as _bt
    p = max(1.0, min(99.0, price_cents)) / 100.0
    return _bt.kalshi_fee_per_contract(p, contracts=max(1, int(contracts))) * 100.0


def model_edge_net_cents(
    up_prob: Optional[float], yes_ask: Optional[float], no_ask: Optional[float],
) -> Optional[float]:
    """Best fee-adjusted cents of edge the settlement model sees on EITHER
    side: buy-up edge = P(up)·100 − upAsk − fee, buy-down mirrored. Positive =
    the model thinks a side is underpriced net of the taker fee; the sign of
    which side is implied by upProb vs the asks. None when the model or both
    asks are unavailable."""
    if up_prob is None:
        return None
    edges = []
    if yes_ask and 0 < yes_ask < 1:
        ask_c = yes_ask * 100.0
        edges.append(up_prob * 100.0 - ask_c - _fee_cents(ask_c))
    if no_ask and 0 < no_ask < 1:
        ask_c = no_ask * 100.0
        edges.append((1.0 - up_prob) * 100.0 - ask_c - _fee_cents(ask_c))
    if not edges:
        return None
    return round(max(edges), 2)


def _track_window_open(asset: str, window_start: int, spot: Optional[float]) -> Optional[float]:
    if spot is None:
        return None
    key = (asset, window_start)
    if key not in _window_open:
        _window_open[key] = spot
        if len(_window_open) > 200:
            for old in sorted(_window_open, key=lambda k: k[1])[:50]:
                _window_open.pop(old, None)
    return _window_open[key]


async def _asset_snapshot(entry: dict, spot: Optional[float], cfg: dict, now_epoch: float) -> dict:
    asset, series = entry["asset"], entry["series"]
    try:
        markets, _ = await kalshi_api.fetch_markets(
            status="open", series_ticker=series, limit=200,
        )
    except Exception as e:
        return _blank_asset(entry, spot, f"market fetch failed: {e}")

    candidates: list[tuple[float, dict]] = []
    for m in markets:
        ce = _parse_close_epoch(m.get("close_time", ""))
        if ce is None or ce <= now_epoch:
            continue
        candidates.append((ce, m))

    out = _blank_asset(entry, spot)
    out["openMarketCount"] = len(candidates)
    if not candidates:
        return out

    candidates.sort(key=lambda x: x[0])
    close_epoch, m = candidates[0]

    wsq = kalshi_ws.ticker_quote(m.get("ticker") or "")
    if wsq:
        ts_ms = float(wsq.get("ts_ms") or 0)
        if ts_ms > 0 and (now_epoch * 1000.0 - ts_ms) <= 10_000.0:
            yb, ya = wsq.get("yes_bid_cents"), wsq.get("yes_ask_cents")
            lp = wsq.get("last_cents")
            if yb is not None:
                m = dict(m)
                m["yes_bid_dollars"] = yb / 100.0
                m["no_ask_dollars"] = (100 - yb) / 100.0
                if ya is not None:
                    m["yes_ask_dollars"] = ya / 100.0
                if lp is not None:
                    m["last_price_dollars"] = lp / 100.0

    window_start = int(close_epoch - _QUARTER_SEC)
    open15m = _track_window_open(asset, window_start, spot)
    strike = _market_strike(m)
    ref = strike if strike is not None else open15m
    delta_signed = ((spot - ref) / ref) if (ref and spot is not None) else None
    delta = abs(spot - ref) if (ref is not None and spot is not None) else None
    delta_pct = abs(delta_signed) if delta_signed is not None else None

    yes_bid = _price_dollars(m, "yes_bid")
    yes_ask = _price_dollars(m, "yes_ask")
    up = _mid_up(yes_bid, yes_ask, _price_dollars(m, "last_price"))
    down = 1.0 - up
    favorite = "up" if up >= down else "down"
    fav_price = up if favorite == "up" else down

    no_ask = _price_dollars(m, "no_ask")
    entry_cost = yes_ask if favorite == "up" else (no_ask if no_ask else 1.0 - yes_bid)
    entry_cost = max(0.0, min(1.0, entry_cost))

    mins_left = (close_epoch - now_epoch) / 60.0
    hour_utc = datetime.fromtimestamp(now_epoch, timezone.utc).hour
    in_window = 1.0 <= mins_left <= _const(cfg, "time_delay_min")
    strict = bool(cfg.get("crypto15m_strict_threshold", True))
    two_sided = bool(yes_bid and yes_ask)
    min_dp = _const(cfg, "min_delta_pct")
    if delta_signed is None or min_dp <= 0:
        delta_ok = True
    elif favorite == "up":
        delta_ok = delta_signed >= min_dp
    else:
        delta_ok = delta_signed <= -min_dp
    signal = (
        in_window
        and hours_ok(cfg)
        and fav_price >= _const(cfg, "entry_threshold")
        and entry_cost <= _const(cfg, "entry_max")
        and delta_ok
        and (not strict or (two_sided and entry_cost >= _const(cfg, "entry_threshold")))
    )

    out.update({
        "open15mUsd": open15m, "deltaUsd": delta, "deltaPct": delta_pct,
        "strikeUsd": ref, "deltaSignedPct": (
            round(delta_signed, 6) if delta_signed is not None else None
        ),
        "hasMarket": True, "ticker": m.get("ticker"),
        "closeTime": m.get("close_time"), "minsLeft": round(mins_left, 2),
        "upProb": round(up, 4), "downProb": round(down, 4),
        "favorite": favorite, "favoritePrice": round(fav_price, 4),
        "entryCost": round(entry_cost, 4),
        "yesBid": round(yes_bid, 4) if yes_bid else None,
        "yesAsk": round(yes_ask, 4) if yes_ask else None,
        "inWindow": in_window, "signal": signal, "hourUtc": hour_utc,
    })

    out["upAsk"] = round(yes_ask, 4) if yes_ask else None
    out["downAsk"] = round(no_ask, 4) if no_ask else None

    if cfg.get("crypto15m_arb_detect", True) and yes_ask and no_ask:
        thresh = float(cfg.get("crypto15m_arb_min_edge_cents", 1.0) or 0.0)
        up_ask_c = round(yes_ask * 100.0, 1)
        dn_ask_c = round(no_ask * 100.0, 1)
        edge_c = round(100.0 - (up_ask_c + dn_ask_c), 1)
        out["arbEdgeCents"] = edge_c
        out["arbSignal"] = edge_c >= thresh

    if cfg.get("crypto15m_indicator_detect", True):
        try:
            ind = await asyncio.wait_for(asset_indicators(asset), 4.0)
        except Exception:
            ind = {}
        out["macd"] = ind.get("macd")
        out["macdSignal"] = ind.get("macdSignal")
        out["macdHist"] = ind.get("macdHist")
        out["macdCross"] = ind.get("macdCross")
        out["rsi"] = ind.get("rsi")
        out["sigma1m"] = ind.get("sigma1m")
        out["vwap1h"] = ind.get("vwap1h")
        out["ema12"] = ind.get("ema12")
        out["sma20"] = ind.get("sma20")
        out["sma50"] = ind.get("sma50")
        out["priceVsVwapPct"] = ind.get("priceVsVwapPct")
        out["ema12VsSma20Pct"] = ind.get("ema12VsSma20Pct")
        out["ema1VsSma5Pct"] = ind.get("ema1VsSma5Pct")
        out["velocity1mPct"] = ind.get("velocity1mPct")
        out["change5mPct"] = ind.get("change5mPct")
        out["change15mPct"] = ind.get("change15mPct")
        psum, pcount = cf_ws.settle_partial(asset, close_epoch)
        if pcount == 0:
            psum, pcount = spot_ws.window_partial(asset, close_epoch)
        out["settlePrints"] = pcount
        mp = settlement_up_prob(
            spot, ref, ind.get("sigma1m"), mins_left,
            partial_sum=psum, partial_count=pcount,
        )
        out["modelProb"] = round(mp, 4) if mp is not None else None
        out["edgeNetCents"] = model_edge_net_cents(
            mp, yes_ask if yes_ask else None, no_ask if no_ask else None,
        )
    return out


def _apply_cross_asset(assets: list[dict], now_epoch: float) -> None:
    """Compute timing + cross-asset correlation fields across the whole snapshot
    and inject them per-asset (optional rule-builder fields, never forced gates):

      hourUtc     current UTC hour 0-23 (also stamped on blank/errored assets)
      marketBias  market-wide directional lean = (#up - #down) / #withFavorite,
                  range -1..1; same for every asset (a breadth gauge)
      peersAgree  fraction of the OTHER favorited assets whose favorite matches
                  this asset's, range 0..1 — high = the pack agrees."""
    hour_utc = datetime.fromtimestamp(now_epoch, timezone.utc).hour
    favs = [a.get("favorite") for a in assets
            if a.get("hasMarket") and a.get("favorite") in ("up", "down")]
    n_up = favs.count("up")
    n_down = favs.count("down")
    total = n_up + n_down
    market_bias = round((n_up - n_down) / total, 4) if total else None

    for a in assets:
        a["hourUtc"] = hour_utc
        a["marketBias"] = market_bias
        a["peersAgree"] = None
        fav = a.get("favorite")
        if not a.get("hasMarket") or fav not in ("up", "down") or total <= 1:
            continue
        peers = total - 1
        same = (n_up - 1) if fav == "up" else (n_down - 1)
        a["peersAgree"] = round(same / peers, 4) if peers else None


_snapshot_cache: dict = {"at": 0.0, "data": None}
_SNAPSHOT_TTL = 3.0


def active_tickers() -> set[str]:
    """Tickers of the CURRENT 15m window per asset (from the last snapshot) —
    the set the WS layer subscribes so entry/pairs decisions read live quotes,
    not just positions we already hold."""
    snap = _snapshot_cache.get("data") or {}
    return {
        a["ticker"] for a in snap.get("assets", [])
        if a.get("hasMarket") and a.get("ticker")
    }


def active_market_meta() -> list[dict]:
    """Per-ticker metadata for the CURRENT 15m window from the last snapshot —
    what the HF recorder needs to stamp each sample without re-fetching:
    {ticker, asset, closeTime, minsLeft, strikeUsd, favorite}. Reads the same
    ~3s snapshot cache active_tickers() does."""
    snap = _snapshot_cache.get("data") or {}
    out = []
    for a in snap.get("assets", []):
        if not (a.get("hasMarket") and a.get("ticker")):
            continue
        out.append({
            "ticker": a["ticker"], "asset": a.get("asset"),
            "closeTime": a.get("closeTime"), "minsLeft": a.get("minsLeft"),
            "strikeUsd": a.get("strikeUsd"), "favorite": a.get("favorite"),
        })
    return out


async def snapshot(cfg: dict) -> dict:
    """Build the full monitor snapshot for all seven series, then inject the
    cross-asset fields. Cached ~3s so the executor poll, the recorder and the
    open Crypto tab SHARE one snapshot instead of each firing the full fan-out
    (incl. the new Hyperliquid indicator calls) — well inside the poll interval
    and a 15-min window, so the slight staleness is immaterial."""
    now_epoch = kalshi_auth.server_now()
    cached = _snapshot_cache.get("data")
    if cached is not None and (now_epoch - _snapshot_cache.get("at", 0.0)) < _SNAPSHOT_TTL:
        return cached
    try:
        spots, spot_source = await fetch_spots()
    except Exception as e:
        logger.debug(f"crypto15m spot fetch failed: {e}")
        spots, spot_source = {}, "unavailable"
    spot_ok = bool(spots)

    results = await asyncio.gather(
        *[_asset_snapshot(s, spots.get(s["asset"]), cfg, now_epoch) for s in SERIES],
        return_exceptions=True,
    )
    assets: list[dict] = []
    for s, r in zip(SERIES, results):
        assets.append(
            r if not isinstance(r, Exception)
            else _blank_asset(s, spots.get(s["asset"]), str(r))
        )

    _apply_cross_asset(assets, now_epoch)

    result = {
        "fetchedAt": datetime.now(timezone.utc).isoformat(),
        "spotOk": spot_ok,
        "spotSource": spot_source,
        "hoursOk": hours_ok(cfg),
        "constants": {
            "timeDelayMin": _const(cfg, "time_delay_min"),
            "entryThreshold": _const(cfg, "entry_threshold"),
            "exitThreshold": _const(cfg, "exit_threshold"),
            "entryMax": _const(cfg, "entry_max"),
            "minDeltaPct": _const(cfg, "min_delta_pct"),
            "entryDiff": _const(cfg, "entry_diff"),
            "strictThreshold": bool(cfg.get("crypto15m_strict_threshold", True)),
            "directionMode": str(cfg.get("crypto15m_direction_mode", "favorite")),
            "entryStyle": str(cfg.get("crypto15m_entry_style", "maker")),
            "hoursStartUtc": int(cfg.get("crypto15m_hours_start_utc", 0) or 0),
            "hoursEndUtc": int(cfg.get("crypto15m_hours_end_utc", 24) or 24),
            "indicatorDetect": bool(cfg.get("crypto15m_indicator_detect", True)),
            "arbDetect": bool(cfg.get("crypto15m_arb_detect", True)),
            "useRules": bool(cfg.get("crypto15m_use_rules", False)),
        },
        "assets": assets,
    }
    _snapshot_cache["at"] = now_epoch
    _snapshot_cache["data"] = result
    return result
