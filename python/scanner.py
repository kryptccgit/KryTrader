from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import db
import kalshi_api
import kalshi_ws
from categorize import (
    CATEGORY_EDGE, KALSHI_CATEGORY_MAP, KALSHI_CATEGORY_MAP_CI,
    categorize_by_keywords, is_micro_market,
)

logger = logging.getLogger(__name__)



MIN_VOLUME_24H = 50
MIN_VOLUME_SPIKE_RATIO = 2.0
MIN_PRICE_MOVE = 0.08
MIN_TRADE_CLUSTER_COUNT = 5
MIN_TRADE_CLUSTER_DOLLARS = 500
ALERT_COOLDOWN_MINUTES = 30
MOMENTUM_YES_MAX_YES_PRICE = 0.50
MOMENTUM_NO_MIN_YES_PRICE = 0.50
ALLOWED_MOMENTUM_SIGNALS = {"trade_cluster"}


def _to_float(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _parse_days_to_close(close_time: str) -> float | None:
    if not close_time:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            ct = datetime.strptime(close_time, fmt)
            if ct.tzinfo is None:
                ct = ct.replace(tzinfo=timezone.utc)
            delta = (ct - datetime.now(timezone.utc)).total_seconds()
            return max(delta / 86400, 0)
        except ValueError:
            continue
    return None


def _trade_age_sec(t: dict, now: datetime | None = None) -> float | None:
    ct = t.get("created_time")
    if ct in (None, ""):
        return None
    now_dt = now or datetime.now(timezone.utc)
    if isinstance(ct, (int, float)) or (isinstance(ct, str) and ct.isdigit()):
        try:
            v = float(ct)
        except (TypeError, ValueError):
            return None
        if v <= 0:
            return None
        if v > 1e11:
            v /= 1000.0
        return now_dt.timestamp() - v
    if not isinstance(ct, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try:
            ts = datetime.strptime(ct, fmt)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return (now_dt - ts).total_seconds()
        except ValueError:
            continue
    return None


def _max_trade_age_sec(cfg: dict) -> float:
    try:
        return max(1.0, float(cfg.get("max_trade_age_min", 15) or 15)) * 60.0
    except (TypeError, ValueError):
        return 15 * 60.0




async def _resolve_category(ticker: str, title: str = "") -> str:
    series_ticker = ticker.split("-")[0] if "-" in ticker else ""
    if series_ticker:
        series = await kalshi_api.fetch_series(series_ticker)
        if series:
            raw = series.get("category", "")
            if raw:
                mapped = KALSHI_CATEGORY_MAP.get(raw) or KALSHI_CATEGORY_MAP_CI.get(
                    raw.strip().lower()
                )
                if mapped:
                    return mapped
                fallback = categorize_by_keywords(title)
                logger.info(
                    f"unmapped Kalshi category {raw!r} for series {series_ticker}; "
                    f"bucketing as {fallback!r} via keywords"
                )
                return fallback
    return categorize_by_keywords(title)




def compute_whale_score(
    dollar_value: float,
    price: float,
    taker_side: str,
    *,
    market_volume: float = 0.0,
    open_interest: float = 0.0,
    days_to_close: float | None = None,
    category: str = "",
) -> float:
    implied = max(5, min(price * 100, 95))
    edge = 0.0
    if taker_side == "yes":
        if   price >= 0.90: edge += 0.5
        elif price >= 0.80: edge += 2
        elif price >= 0.65: edge += 4.5
        elif price >= 0.50: edge -= 1.5
        else:               edge -= 6
    else:
        if   price >= 0.80: edge -= 0.5
        elif price >= 0.65: edge += 0.5
        elif price >= 0.50: edge += 3.5
        elif price >= 0.35: edge -= 5
        else:               edge -= 8

    if dollar_value >= 25_000:   edge += 2
    elif dollar_value >= 10_000: edge += 1.5
    elif dollar_value >= 5_000:  edge += 1.5
    elif dollar_value >= 2_500:  edge += 0.5

    if market_volume >= 250_000:    edge += 1.5
    elif market_volume >= 50_000:   edge += 0.5
    elif 0 < market_volume < 1_000: edge -= 1.5

    if open_interest >= 50_000:
        edge += 0.5

    if days_to_close is not None and days_to_close > 0:
        if days_to_close <= 1: edge += 0.5
        elif days_to_close > 60: edge -= 0.5

    if category:
        edge += CATEGORY_EDGE.get(category, 0.0) * 0.5

    edge = max(-15, min(edge, 10))
    return max(5, min(round(implied + edge, 1), 97.0))


def compute_momentum_confidence(
    *,
    volume_spike_ratio: float,
    price_change_abs: float,
    trade_cluster_count: int,
    trade_cluster_dollars: float,
    market_volume: float,
    open_interest: float,
    days_to_close: float | None,
    price: float,
    direction: str,
    signal_type: str = "",
    category: str = "",
) -> float:
    if direction == "yes":
        implied = price * 100
    else:
        implied = (1.0 - price) * 100
    implied = max(5, min(implied, 95))

    edge = 0.0

    if signal_type == "trade_cluster":
        if implied < 15:   edge += 25
        elif implied < 25: edge += 18
        elif implied < 35: edge += 11
        elif implied < 50: edge += 7
        else:              edge += 3

    if trade_cluster_count >= 20:    edge += 2
    elif trade_cluster_count >= 10:  edge += 1.5
    elif trade_cluster_count >= 5:   edge += 1
    elif trade_cluster_count >= 3:   edge += 0.5
    if trade_cluster_dollars >= 5_000:
        edge += 1

    if volume_spike_ratio >= 5:    edge += 1.5
    elif volume_spike_ratio >= 3:  edge += 1
    elif volume_spike_ratio >= 2:  edge += 0.5

    if price_change_abs >= 0.15:    edge += 1.5
    elif price_change_abs >= 0.08:  edge += 1
    elif price_change_abs >= 0.05:  edge += 0.5

    if market_volume >= 250_000:    edge += 2
    elif market_volume >= 50_000:   edge += 1
    elif market_volume >= 10_000:   edge += 0.5
    elif 0 < market_volume < 1_000: edge -= 1.5

    if open_interest >= 50_000:    edge += 1
    elif open_interest >= 10_000:  edge += 0.5

    if days_to_close is not None and days_to_close > 0:
        if days_to_close <= 1:   edge += 1
        elif days_to_close <= 7: edge += 0.5
        elif days_to_close > 60: edge -= 0.5

    if category:
        edge += CATEGORY_EDGE.get(category, 0.0) * 0.5

    edge = max(-12, min(edge, 8))
    return max(5, min(round(implied + edge, 1), 97.0))




async def sync_markets(*, max_pages: int = 10) -> int:
    raw = await kalshi_api.fetch_all_open_markets(max_pages=max_pages)
    if not raw:
        return 0
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    count = 0
    with db.get_db() as conn:
        for m in raw:
            ticker = m.get("ticker", "")
            if not ticker or is_micro_market(ticker):
                continue
            close_time = m.get("close_time", "")
            if close_time and close_time < now_iso:
                continue
            vol = _to_float(m.get("volume_fp", 0))
            if vol < 10:
                continue
            event_ticker = m.get("event_ticker", "")
            series_ticker = (
                event_ticker.split("-")[0] if event_ticker and "-" in event_ticker else ""
            )
            db.upsert_market(
                conn,
                {
                    "ticker": ticker,
                    "event_ticker": event_ticker,
                    "series_ticker": series_ticker,
                    "title": m.get("title", "") or m.get("yes_sub_title", "") or ticker,
                    "yes_sub_title": m.get("yes_sub_title", ""),
                    "category": "",
                    "status": m.get("status", "open"),
                    "close_time": close_time,
                    "volume": m.get("volume_fp", 0),
                    "volume_24h": m.get("volume_24h_fp", 0),
                    "open_interest": m.get("open_interest_fp", 0),
                    "yes_bid": m.get("yes_bid_dollars", 0),
                    "yes_ask": m.get("yes_ask_dollars", 0),
                    "last_price": m.get("last_price_dollars", 0),
                    "result": m.get("result", ""),
                    "settlement_value": m.get("settlement_value_dollars"),
                },
            )
            count += 1
    return count


async def sync_events() -> int:
    _events_page = await kalshi_api.fetch_events(status="open", limit=200)
    events, _ = _events_page if _events_page is not None else ([], "")
    count = 0
    with db.get_db() as conn:
        for e in events:
            db.upsert_event(
                conn,
                {
                    "event_ticker": e.get("event_ticker", ""),
                    "series_ticker": e.get("series_ticker", ""),
                    "title": e.get("title", ""),
                    "sub_title": e.get("sub_title", ""),
                    "category": e.get("category", ""),
                    "status": "open",
                },
            )
            count += 1
    return count




async def scan_whales(cfg: dict) -> tuple[int, list[dict]]:
    raw = kalshi_ws.recent_trades(limit=1000)
    if raw is None:
        raw = await kalshi_api.fetch_recent_trades(limit=1000)
    if not raw:
        return 0, []

    min_usd = float(cfg.get("min_whale_usd", 2500))
    min_entry = float(cfg.get("min_entry_price_frac", 0.50))
    max_age = _max_trade_age_sec(cfg)
    now = datetime.now(timezone.utc)

    candidates: list[dict] = []
    for t in raw:
        age = _trade_age_sec(t, now)
        if age is not None and age > max_age:
            continue
        if t.get("is_block_trade"):
            continue
        count_fp = _to_float(t.get("count_fp", 0))
        yes_p = _to_float(t.get("yes_price_dollars", 0))
        no_p = _to_float(t.get("no_price_dollars", 0))
        side = (t.get("taker_side") or "").lower()
        if side not in ("yes", "no"):
            logger.debug(
                f"skip tape trade {t.get('trade_id', '')!r}: missing taker_side"
            )
            continue
        price = yes_p if side == "yes" else no_p
        dollar = count_fp * price
        if dollar < min_usd:
            continue
        if price < min_entry:
            continue
        ticker = t.get("ticker", "")
        if not ticker or is_micro_market(ticker):
            continue
        candidates.append(
            {
                "raw": t,
                "ticker": ticker,
                "count_fp": count_fp,
                "price": price,
                "dollar": dollar,
                "taker_side": side,
            }
        )

    if not candidates:
        return 0, []

    with db.get_db() as conn:
        pending: list[dict] = []
        for entry in candidates:
            trade_id = entry["raw"].get("trade_id", "")
            if not trade_id or db.whale_trade_exists(conn, trade_id):
                continue
            entry["trade_id"] = trade_id
            entry["mkt"] = db.get_market(conn, entry["ticker"])
            pending.append(entry)

    if not pending:
        return 0, []

    miss_tickers = {e["ticker"] for e in pending if not e["mkt"]}
    api_markets = await kalshi_api.fetch_markets_map(miss_tickers) if miss_tickers else {}
    fetched_markets: dict[str, dict] = {}
    for entry in pending:
        ticker = entry["ticker"]
        mkt = entry["mkt"]
        if not mkt:
            api_mkt = api_markets.get(ticker)
            if api_mkt:
                event_tk = api_mkt.get("event_ticker", "")
                series_tk = event_tk.split("-")[0] if event_tk and "-" in event_tk else ""
                mkt = {
                    "ticker": ticker,
                    "event_ticker": event_tk,
                    "series_ticker": series_tk,
                    "title": api_mkt.get("title", ""),
                    "yes_sub_title": api_mkt.get("yes_sub_title", ""),
                    "category": "",
                    "status": api_mkt.get("status", "open"),
                    "close_time": api_mkt.get("close_time", ""),
                    "volume": api_mkt.get("volume_fp", 0),
                    "volume_24h": api_mkt.get("volume_24h_fp", 0),
                    "open_interest": api_mkt.get("open_interest_fp", 0),
                    "yes_bid": api_mkt.get("yes_bid_dollars", 0),
                    "yes_ask": api_mkt.get("yes_ask_dollars", 0),
                    "last_price": api_mkt.get("last_price_dollars", 0),
                    "result": api_mkt.get("result", ""),
                    "settlement_value": api_mkt.get("settlement_value_dollars"),
                }
                fetched_markets[ticker] = mkt
            entry["mkt"] = mkt

        title = event_ticker = close_time = yes_sub = ""
        mkt_vol = oi = 0.0
        cat = ""
        if mkt:
            title = mkt.get("title", "") or mkt.get("yes_sub_title", "")
            yes_sub = mkt.get("yes_sub_title", "")
            event_ticker = mkt.get("event_ticker", "")
            close_time = mkt.get("close_time", "")
            mkt_vol = _to_float(mkt.get("volume", 0))
            oi = _to_float(mkt.get("open_interest", 0))
            cat = mkt.get("category", "")
        if not cat:
            cat = await _resolve_category(ticker, title)

        days_left = _parse_days_to_close(close_time)
        confidence = compute_whale_score(
            dollar_value=entry["dollar"], price=entry["price"],
            taker_side=entry["taker_side"], market_volume=mkt_vol,
            open_interest=oi, days_to_close=days_left, category=cat,
        )
        entry["data"] = {
            "trade_id": entry["trade_id"],
            "ticker": ticker,
            "event_ticker": event_ticker,
            "title": title or ticker,
            "yes_sub_title": yes_sub,
            "category": cat,
            "taker_side": entry["taker_side"],
            "count_fp": entry["count_fp"],
            "price": entry["price"],
            "dollar_value": entry["dollar"],
            "market_volume": mkt_vol,
            "open_interest": oi,
            "confidence": confidence,
        }

    new_rows: list[dict] = []
    with db.get_db() as conn:
        for entry in pending:
            if db.whale_trade_exists(conn, entry["trade_id"]):
                continue
            m = fetched_markets.get(entry["ticker"])
            if m:
                m["category"] = entry["data"].get("category", "") or m.get("category", "")
                db.upsert_market(conn, m)
            wid = db.insert_whale_trade(conn, entry["data"])
            if wid:
                row = conn.execute(
                    "SELECT * FROM whale_trades WHERE id=?", (wid,)
                ).fetchone()
                if row:
                    new_rows.append(dict(row))

    return len(new_rows), new_rows




async def scan_momentum(cfg: dict) -> tuple[int, list[dict]]:
    with db.get_db() as conn:
        markets = db.get_active_markets(conn, min_volume=MIN_VOLUME_24H, limit=500)

    if not markets:
        return 0, []

    recent_trades = kalshi_ws.recent_trades(limit=1000)
    if recent_trades is None:
        recent_trades = await kalshi_api.fetch_recent_trades(limit=1000)
    max_age = _max_trade_age_sec(cfg)
    now_utc = datetime.now(timezone.utc)
    trades_by_ticker: dict[str, list[dict]] = defaultdict(list)
    for t in recent_trades:
        ticker = t.get("ticker", "")
        if not ticker or is_micro_market(ticker):
            continue
        age = _trade_age_sec(t, now_utc)
        if age is not None and age > max_age:
            continue
        trades_by_ticker[ticker].append(t)

    new_alerts: list[dict] = []
    contrarian_only = bool(cfg.get("contrarian_only", True))
    allowed_signals = set(cfg.get("allowed_momentum_signal_types", ["trade_cluster"]))

    with db.get_db() as conn:
        for trade in recent_trades:
            tid = trade.get("trade_id", "")
            if tid and not db.trade_exists(conn, tid):
                count_fp = _to_float(trade.get("count_fp", 0))
                yes_p = _to_float(trade.get("yes_price_dollars", 0))
                no_p = _to_float(trade.get("no_price_dollars", 0))
                taker = trade.get("taker_side", "")
                dollar = count_fp * (yes_p if taker == "yes" else no_p)
                db.insert_trade(
                    conn,
                    {
                        "trade_id": tid,
                        "ticker": trade.get("ticker", ""),
                        "count_fp": count_fp,
                        "yes_price": yes_p,
                        "no_price": no_p,
                        "taker_side": taker,
                        "dollar_value": dollar,
                        "created_time": trade.get("created_time", ""),
                    },
                )

    with db.get_db() as conn:
        for market in markets:
            tk = market.get("ticker")
            if tk and not is_micro_market(tk):
                db.save_snapshot(conn, tk, market)
        prev_snaps = db.get_previous_snapshots_bulk(
            conn, [m.get("ticker") for m in markets if m.get("ticker")]
        )
        for market in markets:
            ticker = market["ticker"]
            if is_micro_market(ticker):
                continue

            vol_24h = _to_float(market.get("volume_24h", 0))
            cur_price = _to_float(market.get("yes_bid", 0)) or _to_float(
                market.get("last_price", 0)
            )
            oi = _to_float(market.get("open_interest", 0))
            close_time = market.get("close_time", "")
            days_left = _parse_days_to_close(close_time)

            prev = prev_snaps.get(ticker)
            prev_vol = _to_float(prev.get("volume_24h", 0)) if prev else 0
            prev_price = (
                _to_float(prev.get("yes_bid", 0) or prev.get("last_price", 0))
                if prev
                else 0
            )

            vol_spike = (vol_24h / prev_vol) if prev_vol > 10 else 0
            price_change = (cur_price - prev_price) if prev_price > 0 else 0

            ticker_trades = trades_by_ticker.get(ticker, [])
            yes_trades = [t for t in ticker_trades if t.get("taker_side") == "yes"]
            no_trades = [t for t in ticker_trades if t.get("taker_side") == "no"]
            yes_count = len(yes_trades)
            no_count = len(no_trades)
            yes_dollars = sum(
                _to_float(t.get("count_fp", 0))
                * _to_float(t.get("yes_price_dollars", 0))
                for t in yes_trades
            )
            no_dollars = sum(
                _to_float(t.get("count_fp", 0))
                * _to_float(t.get("no_price_dollars", 0))
                for t in no_trades
            )

            if yes_dollars > no_dollars:
                cluster_dir = "yes"
                cluster_count = yes_count
                cluster_dollars = yes_dollars
            elif no_dollars > yes_dollars:
                cluster_dir = "no"
                cluster_count = no_count
                cluster_dollars = no_dollars
            else:
                cluster_dir = "yes" if price_change >= 0 else "no"
                cluster_count = max(yes_count, no_count)
                cluster_dollars = max(yes_dollars, no_dollars)

            signals: list[str] = []
            if vol_spike >= MIN_VOLUME_SPIKE_RATIO and vol_24h >= MIN_VOLUME_24H:
                signals.append("volume_spike")
            if abs(price_change) >= MIN_PRICE_MOVE:
                signals.append("price_move")
            if (
                cluster_count >= MIN_TRADE_CLUSTER_COUNT
                and cluster_dollars >= MIN_TRADE_CLUSTER_DOLLARS
            ):
                signals.append("trade_cluster")
            if not signals:
                continue

            for stype in signals:
                if stype not in allowed_signals:
                    continue
                if stype == "price_move":
                    direction = "yes" if price_change > 0 else "no"
                else:
                    direction = cluster_dir
                if contrarian_only:
                    if direction == "yes" and cur_price > MOMENTUM_YES_MAX_YES_PRICE:
                        continue
                    if direction == "no" and cur_price < MOMENTUM_NO_MIN_YES_PRICE:
                        continue
                if db.recent_alert_exists(
                    conn, ticker, stype, direction, ALERT_COOLDOWN_MINUTES
                ):
                    continue

                category = market.get("category", "") or categorize_by_keywords(
                    market.get("title", "") or market.get("yes_sub_title", "")
                )
                total_vol = _to_float(market.get("volume", 0))

                confidence = compute_momentum_confidence(
                    volume_spike_ratio=vol_spike,
                    price_change_abs=abs(price_change),
                    trade_cluster_count=cluster_count,
                    trade_cluster_dollars=cluster_dollars,
                    market_volume=total_vol,
                    open_interest=oi,
                    days_to_close=days_left,
                    price=cur_price,
                    direction=direction,
                    signal_type=stype,
                    category=category,
                )
                title = (
                    market.get("title", "")
                    or market.get("yes_sub_title", "")
                    or ticker
                )
                alert_data = {
                    "ticker": ticker,
                    "event_ticker": market.get("event_ticker", ""),
                    "title": title,
                    "yes_sub_title": market.get("yes_sub_title", ""),
                    "category": category,
                    "signal_type": stype,
                    "direction": direction,
                    "volume_24h": vol_24h,
                    "price": cur_price,
                    "price_change": price_change * 100,
                    "confidence": confidence,
                }
                alert_id = db.insert_alert(conn, alert_data)
                row = conn.execute(
                    "SELECT * FROM alerts WHERE id=?", (alert_id,)
                ).fetchone()
                if row:
                    new_alerts.append(dict(row))

    return len(new_alerts), new_alerts




def compute_convergence_score(*, count: int, total_usd: float, implied: float) -> float:
    implied = max(5.0, min(float(implied), 95.0))
    if count >= 5:
        bonus = 8.0
    elif count == 4:
        bonus = 6.0
    else:
        bonus = 4.0
    if total_usd >= 25_000:
        bonus += 1.0
    bonus = min(bonus, 10.0)
    return max(5, min(round(implied + bonus, 1), 97.0))


def build_convergence_signals(
    conn, *, max_signal_age_sec: int, min_count: int = 3, hours: int = 2,
) -> list[dict]:
    groups = db.get_recent_whales_for_convergence(conn, hours=hours)
    out: list[dict] = []
    for (ticker, side), whales in groups.items():
        if not ticker or side not in ("yes", "no") or is_micro_market(ticker):
            continue
        if len(whales) < min_count:
            continue
        latest = max(whales, key=lambda w: (w.get("created_at") or "", w.get("id") or 0))
        age = _trade_age_sec({"created_time": latest.get("created_at") or ""})
        if age is None or age > max_signal_age_sec:
            continue
        total = sum(_to_float(w.get("dollar_value")) for w in whales)
        weighted = sum(
            _to_float(w.get("price")) * _to_float(w.get("dollar_value")) for w in whales
        )
        price = (weighted / total) if total > 0 else _to_float(latest.get("price"))
        if not (0.0 < price < 1.0):
            continue
        confidence = compute_convergence_score(
            count=len(whales), total_usd=total, implied=price * 100.0,
        )
        out.append({
            "id": int(latest.get("id") or 0),
            "ticker": ticker,
            "event_ticker": latest.get("event_ticker") or "",
            "title": latest.get("title") or ticker,
            "category": latest.get("category") or "",
            "direction": side,
            "taker_side": side,
            "price": price,
            "market_volume": latest.get("market_volume"),
            "confidence": confidence,
            "whale_count": len(whales),
            "total_usd": total,
            "signal_type": "convergence",
        })
    return out


async def resolve_alerts_from_markets() -> int:
    with db.get_db() as conn:
        unresolved = db.get_unresolved_alerts(conn, days=30)
    if not unresolved:
        return 0

    tickers = list({a["ticker"] for a in unresolved if a["ticker"]})
    resolved = 0
    markets = await kalshi_api.fetch_markets_map(tickers)
    with db.get_db() as conn:
        for ticker in tickers:
            market = markets.get(ticker)
            if not market:
                continue
            status = (market.get("status") or "").lower()
            result = (market.get("result") or "").lower()
            if status not in ("determined", "finalized", "settled") or not result:
                continue
            for a in [x for x in unresolved if x["ticker"] == ticker]:
                if a["direction"] == "yes":
                    correct = result == "yes"
                    pnl = (1.0 - a["price"]) if correct else (-a["price"])
                else:
                    correct = result == "no"
                    pnl = (a["price"]) if correct else (-(1.0 - a["price"]))
                db.mark_alert_resolved(
                    conn, a["id"], correct, 1.0 if correct else 0.0, pnl
                )
                resolved += 1
    return resolved


async def resolve_whales_from_markets() -> int:
    with db.get_db() as conn:
        unresolved = db.get_unresolved_whale_trades(conn, days=30)
    if not unresolved:
        return 0
    tickers = list({t["ticker"] for t in unresolved if t["ticker"]})
    resolved = 0
    markets = await kalshi_api.fetch_markets_map(tickers)
    with db.get_db() as conn:
        for ticker in tickers:
            market = markets.get(ticker)
            if not market:
                continue
            status = (market.get("status") or "").lower()
            result = (market.get("result") or "").lower()
            if status not in ("determined", "finalized", "settled") or not result:
                continue
            for t in [x for x in unresolved if x["ticker"] == ticker]:
                p = float(t["price"]) or 0.0
                contracts = (t["dollar_value"] / p) if p else 0.0
                correct = result == t["taker_side"]
                pnl = contracts * (1.0 - p) if correct else -t["dollar_value"]
                db.mark_whale_resolved(
                    conn, t["id"], correct, 1.0 if correct else 0.0, pnl
                )
                resolved += 1
    return resolved
