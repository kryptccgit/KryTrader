from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

import db as dbmod
import indicators

logger = logging.getLogger("crypto15m_backfill")

_HYPERLIQUID_URL = "https://api.hyperliquid.xyz/info"
_LOOKBACK_MIN = 90

_NEW_COLS = [
    "vwap1h", "ema12", "sma20", "sma50", "price_vs_vwap_pct",
    "ema12_vs_sma20_pct", "ema1_vs_sma5_pct", "velocity1m_pct",
    "change5m_pct", "change15m_pct",
]

_KEY_TO_COL = {
    "vwap1h": "vwap1h", "ema12": "ema12", "sma20": "sma20", "sma50": "sma50",
    "priceVsVwapPct": "price_vs_vwap_pct", "ema12VsSma20Pct": "ema12_vs_sma20_pct",
    "ema1VsSma5Pct": "ema1_vs_sma5_pct", "velocity1mPct": "velocity1m_pct",
    "change5mPct": "change5m_pct", "change15mPct": "change15m_pct",
}


def _epoch_ms(observed_at: str) -> Optional[int]:
    try:
        dt = datetime.strptime(observed_at[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


async def _fetch_candles(asset: str, client: httpx.AsyncClient, end_ms: int) -> tuple[list[float], list[float]]:
    body = {"type": "candleSnapshot", "req": {
        "coin": asset, "interval": "1m",
        "startTime": end_ms - _LOOKBACK_MIN * 60_000, "endTime": end_ms}}
    resp = await client.post(_HYPERLIQUID_URL, json=body, timeout=15.0)
    resp.raise_for_status()
    rows = resp.json()
    if not isinstance(rows, list):
        return [], []
    closes, vols = [], []
    for r in rows:
        if not isinstance(r, dict) or not r.get("c"):
            continue
        try:
            closes.append(float(r["c"]))
        except (TypeError, ValueError):
            continue
        try:
            vols.append(float(r.get("v")) if r.get("v") is not None else 0.0)
        except (TypeError, ValueError):
            vols.append(0.0)
    return closes, vols


def _pending_groups(env: str, since_days: int, limit: int) -> dict[tuple[str, str], list[int]]:
    with dbmod.get_db() as conn:
        rows = conn.execute(
            f"""SELECT id, asset, observed_at FROM crypto15m_ticks
                WHERE kalshi_env=? AND price_vs_vwap_pct IS NULL
                  AND observed_at >= datetime('now', ?)
                ORDER BY observed_at DESC""",
            (env, f"-{int(since_days)} days"),
        ).fetchall()
    groups: dict[tuple[str, str], list[int]] = {}
    for r in rows:
        minute = str(r["observed_at"])[:16]
        key = (str(r["asset"]), minute)
        groups.setdefault(key, []).append(int(r["id"]))
        if len(groups) >= limit and key not in groups:
            break
    if len(groups) > limit:
        groups = dict(list(groups.items())[:limit])
    return groups


async def backfill(env: str = "production", since_days: int = 90, limit: int = 500,
                   concurrency: int = 8) -> dict:
    groups = _pending_groups(env, since_days, limit)
    if not groups:
        return {"groups": 0, "rowsUpdated": 0, "fetchErrors": 0, "noData": 0}
    sem = asyncio.Semaphore(concurrency)

    async def fetch_group(client: httpx.AsyncClient, key: tuple[str, str]):
        asset, minute = key
        end_ms = _epoch_ms(minute + ":30")
        if end_ms is None:
            return ("skip", key)
        async with sem:
            try:
                closes, vols = await _fetch_candles(asset, client, end_ms)
            except Exception as e:
                logger.debug(f"backfill fetch {asset} {minute}: {e}")
                return ("err", key)
        data = indicators.compute(closes, vols)
        sets = {col: data.get(k) for k, col in _KEY_TO_COL.items()}
        if all(v is None for v in sets.values()):
            return ("nodata", key)
        return ("ok", sets, groups[key])

    async with httpx.AsyncClient() as client:
        results = await asyncio.gather(*[fetch_group(client, k) for k in groups])

    updated = errors = nodata = 0
    with dbmod.get_db() as conn:
        for r in results:
            tag = r[0]
            if tag == "err":
                errors += 1
            elif tag == "nodata":
                nodata += 1
            elif tag == "ok":
                _, sets, ids = r
                cols_sql = ", ".join(f"{c}=?" for c in sets)
                q = "?, " * (len(ids) - 1) + "?"
                conn.execute(
                    f"UPDATE crypto15m_ticks SET {cols_sql} WHERE id IN ({q})",
                    list(sets.values()) + ids,
                )
                updated += len(ids)
    return {"groups": len(groups), "rowsUpdated": updated,
            "fetchErrors": errors, "noData": nodata}


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser(description="Backfill trend/VWAP tick fields from Hyperliquid.")
    ap.add_argument("--env", default="production")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--limit", type=int, default=500, help="max (asset,minute) groups per run")
    ap.add_argument("--loop", action="store_true", help="repeat until nothing pending")
    args = ap.parse_args()
    total = {"groups": 0, "rowsUpdated": 0, "fetchErrors": 0}
    while True:
        res = asyncio.run(backfill(args.env, args.days, args.limit))
        for k in total:
            total[k] += res[k]
        print(f"pass: {res}")
        if not args.loop or res["groups"] == 0:
            break
    print(f"TOTAL: {total}")


if __name__ == "__main__":
    main()
