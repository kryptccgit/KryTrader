from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import crypto15m
import db
import kalshi_api
import kalshi_auth

logger = logging.getLogger(__name__)

CAPTURE_LOOKBACK_MIN = 8.0
_RESOLVE_PER_TICK = 8


def _settled_up_won(m: dict) -> Optional[bool]:
    if not isinstance(m, dict):
        return None
    result = (m.get("result") or "").lower()
    if result == "yes":
        return True
    if result == "no":
        return False
    status = (m.get("status") or "").lower()
    if status not in ("settled", "finalized", "closed", "determined"):
        return None
    sv = m.get("settlement_value_dollars")
    if sv is not None:
        try:
            return float(sv) >= 0.5
        except (TypeError, ValueError):
            return None
    sv = m.get("settlement_value")
    if sv is not None:
        try:
            return float(sv) >= 50.0
        except (TypeError, ValueError):
            return None
    return None


def _capture_ticks(snap: dict, env: str) -> int:
    captured = 0
    with db.get_db() as conn:
        for a in snap.get("assets", []):
            if not a.get("hasMarket") or not a.get("ticker"):
                continue
            db.insert_crypto15m_tick(conn, {
                "ticker": a["ticker"],
                "asset": a["asset"],
                "mins_left": a.get("minsLeft"),
                "yes_bid": a.get("yesBid"),
                "yes_ask": a.get("yesAsk"),
                "up_prob": a.get("upProb"),
                "spot": a.get("spotUsd"),
                "open_spot": a.get("open15mUsd"),
                "delta_pct": a.get("deltaPct"),
                "macd": a.get("macd"),
                "macd_signal": a.get("macdSignal"),
                "macd_hist": a.get("macdHist"),
                "macd_cross": a.get("macdCross"),
                "rsi": a.get("rsi"),
                "strike": a.get("strikeUsd"),
                "delta_signed_pct": a.get("deltaSignedPct"),
                "sigma1m": a.get("sigma1m"),
                "model_prob": a.get("modelProb"),
                "edge_net_cents": a.get("edgeNetCents"),
                "settle_prints": a.get("settlePrints"),
                "no_ask": a.get("downAsk"),
                "vwap1h": a.get("vwap1h"),
                "ema12": a.get("ema12"),
                "sma20": a.get("sma20"),
                "sma50": a.get("sma50"),
                "price_vs_vwap_pct": a.get("priceVsVwapPct"),
                "ema12_vs_sma20_pct": a.get("ema12VsSma20Pct"),
                "ema1_vs_sma5_pct": a.get("ema1VsSma5Pct"),
                "velocity1m_pct": a.get("velocity1mPct"),
                "change5m_pct": a.get("change5mPct"),
                "change15m_pct": a.get("change15mPct"),
                "spot_source": snap.get("spotSource"),
                "kalshi_env": env,
            })
            captured += 1
    return captured


def _capture(snap: dict, env: str) -> int:
    captured = 0
    for a in snap.get("assets", []):
        if not a.get("hasMarket") or not a.get("ticker"):
            continue
        ml = a.get("minsLeft")
        fav = a.get("favorite")
        if ml is None or ml > CAPTURE_LOOKBACK_MIN or fav not in ("up", "down"):
            continue
        row = {
            "ticker": a["ticker"],
            "asset": a["asset"],
            "series": a.get("series", ""),
            "close_time": a.get("closeTime", ""),
            "mins_left": ml,
            "favorite": fav,
            "favorite_price": a.get("favoritePrice"),
            "entry_cost": a.get("entryCost"),
            "up_prob": a.get("upProb"),
            "delta_pct": a.get("deltaPct"),
            "open_spot": a.get("open15mUsd"),
            "obs_spot": a.get("spotUsd"),
            "macd": a.get("macd"),
            "macd_signal": a.get("macdSignal"),
            "macd_hist": a.get("macdHist"),
            "macd_cross": a.get("macdCross"),
            "rsi": a.get("rsi"),
            "strike": a.get("strikeUsd"),
            "model_prob": a.get("modelProb"),
            "edge_net_cents": a.get("edgeNetCents"),
            "kalshi_env": env,
        }
        with db.get_db() as conn:
            if db.insert_crypto15m_signal(conn, row):
                captured += 1
    return captured


async def _resolve(now_epoch: float) -> int:
    with db.get_db() as conn:
        pending = db.unresolved_crypto15m_signals(conn, limit=200)
    resolved = 0
    for s in pending:
        if resolved >= _RESOLVE_PER_TICK:
            break
        ce = crypto15m._parse_close_epoch(s.get("close_time") or "")
        if ce is not None and ce > now_epoch:
            continue
        try:
            m = await kalshi_api.fetch_market(s["ticker"])
        except Exception:
            continue
        up_won = _settled_up_won(m or {})
        if up_won is None:
            continue
        with db.get_db() as conn:
            db.resolve_crypto15m_signal(conn, s["ticker"], 1 if up_won else 0)
        resolved += 1
    return resolved


async def record_tick(cfg: dict) -> dict:
    env = kalshi_auth.get_env()
    now_epoch = datetime.now(timezone.utc).timestamp()
    captured = 0
    resolved = 0
    ticks = 0
    try:
        snap = await crypto15m.snapshot(cfg)
    except Exception as e:
        logger.debug(f"crypto15m snapshot failed: {e}")
        snap = None
    if snap:
        try:
            ticks = _capture_ticks(snap, env)
        except Exception as e:
            logger.debug(f"crypto15m tick capture failed: {e}")
        try:
            captured = _capture(snap, env)
        except Exception as e:
            logger.debug(f"crypto15m capture failed: {e}")
    try:
        resolved = await _resolve(now_epoch)
    except Exception as e:
        logger.debug(f"crypto15m resolve failed: {e}")
    if captured or resolved:
        logger.debug(f"crypto15m signals: +{captured} captured, {resolved} resolved")
    return {"captured": captured, "resolved": resolved, "ticks": ticks}
