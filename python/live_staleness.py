#!/usr/bin/env python3
"""Standalone LIVE runner for the staleness-entry edge on Kalshi 15m crypto.

THE STRATEGY (validated out-of-sample on 14h of HF data, +2.8-5c/ct net of fee
at the >=8bp threshold — a HYPOTHESIS, not a proven money machine):
  When the underlying spot makes a fast move (>= MOVE_BPS over LOOKBACK_SEC)
  while the Kalshi book has NOT repriced yet (mid moved <= BOOK_STALE_C cents),
  take the stale quote: buy the side spot moved toward, as a marketable taker,
  and HOLD TO SETTLEMENT. No trailing exit — holding beats every exit rule we
  tested. The whole edge is speed: you must lift the stale ask before the book
  catches up (~1-3s), which is why this is a standalone, minimal, fast loop.

It reuses the app's battle-tested signing (kalshi_auth), real-time order book
(kalshi_ws), and Coinbase spot feed (spot_ws), but is otherwise self-contained
and reads its keys + params from a .env file. It runs FINE alongside the main
app/scanner (separate WS connection, same account).

╔═══════════════════════════════════════════════════════════════════════════╗
║ REAL MONEY. Read this.                                                      ║
║  • DRY-RUN by default. It places NO orders unless ST_LIVE=1.                ║
║  • The edge is validated on ONE 14h same-day session with modest OOS n.     ║
║    It is NOT proven across regimes. Paper/observe first. Size tiny.         ║
║  • Hard caps below bound the damage: per-order size, max concurrent open,   ║
║    max entries/day, and MAX DAILY SPEND (~= max daily loss, since a losing  ║
║    binary settles to $0). It stops entering when a cap is hit.              ║
║  • Ctrl-C stops cleanly. There is NO auto-exit; positions ride to           ║
║    settlement, so a cap breach or a crash leaves open bets to settle.       ║
╚═══════════════════════════════════════════════════════════════════════════╝

Usage:
  cp .env.staleness.example .env.staleness   # then fill in keys
  python live_staleness.py [path/to/.env.staleness]   # default: ./.env.staleness
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("staleness")

ASSET_SERIES = {
    "BTC": "KXBTC15M", "ETH": "KXETH15M", "SOL": "KXSOL15M",
    "XRP": "KXXRP15M", "DOGE": "KXDOGE15M",
}


def parse_close_epoch(s) -> float | None:
    """ISO8601 close_time -> epoch seconds (UTC)."""
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None



def load_env_file(path: Path) -> dict:
    env: dict[str, str] = {}
    if not path.exists():
        log.error(f"env file not found: {path}")
        log.error("copy .env.staleness.example -> .env.staleness and fill it in")
        sys.exit(2)
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _f(env: dict, k: str, d: float) -> float:
    try:
        return float(env.get(k, d))
    except (TypeError, ValueError):
        return d


def _i(env: dict, k: str, d: int) -> int:
    try:
        return int(float(env.get(k, d)))
    except (TypeError, ValueError):
        return d


def _b(env: dict, k: str, d: bool = False) -> bool:
    return str(env.get(k, "1" if d else "0")).strip().lower() in ("1", "true", "yes", "on")


class Params:
    def __init__(self, env: dict) -> None:
        self.kalshi_env = (env.get("KALSHI_ENV") or "production").strip().lower()
        self.key_id = (env.get("KALSHI_KEY_ID") or "").strip()
        self.pem_path = (env.get("KALSHI_PRIVATE_KEY_PATH") or "").strip()
        self.pem_inline = env.get("KALSHI_PRIVATE_KEY") or ""
        self.userdata = (env.get("ST_USERDATA") or "./.staleness_data").strip()

        self.live = _b(env, "ST_LIVE", False)
        self.move_bps = _f(env, "ST_MOVE_BPS", 8.0)
        self.lookback_sec = _f(env, "ST_LOOKBACK_SEC", 3.0)
        self.book_stale_c = _f(env, "ST_BOOK_STALE_C", 2.0)
        self.contracts = _i(env, "ST_CONTRACTS", 1)
        self.cross_buffer_c = _i(env, "ST_CROSS_BUFFER_C", 1)
        self.min_price_c = _i(env, "ST_MIN_PRICE_C", 20)
        self.max_price_c = _i(env, "ST_MAX_PRICE_C", 80)
        self.entry_min_mins = _f(env, "ST_ENTRY_MIN_MINS", 2.0)
        self.entry_max_mins = _f(env, "ST_ENTRY_MAX_MINS", 13.0)
        self.sample_ms = _i(env, "ST_SAMPLE_MS", 10)
        self.prewarm_sec = _f(env, "ST_PREWARM_SEC", 30.0)
        self.per_ticker_once = _b(env, "ST_PER_TICKER_ONCE", True)
        self.cancel_remainder = _b(env, "ST_CANCEL_REMAINDER", True)
        raw_assets = (env.get("ST_ASSETS") or "BTC,ETH,SOL,XRP,DOGE").upper()
        self.asset_series = {
            a.strip(): ASSET_SERIES[a.strip()]
            for a in raw_assets.split(",") if a.strip() in ASSET_SERIES
        }
        self.max_concurrent = _i(env, "ST_MAX_CONCURRENT", 5)
        self.max_entries_day = _i(env, "ST_MAX_ENTRIES_DAY", 50)
        self.max_daily_spend = _f(env, "ST_MAX_DAILY_SPEND_USD", 25.0)

    def load_pem(self) -> str:
        if self.pem_path:
            p = Path(self.pem_path)
            if not p.exists():
                log.error(f"KALSHI_PRIVATE_KEY_PATH not found: {p}")
                sys.exit(2)
            return p.read_text(encoding="utf-8")
        if self.pem_inline:
            return self.pem_inline.replace("\\n", "\n")
        log.error("no RSA key: set KALSHI_PRIVATE_KEY_PATH (recommended) or KALSHI_PRIVATE_KEY")
        sys.exit(2)



def bootstrap_credentials(p: Params):
    os.environ["KRYPT_TRADER_USERDATA"] = str(Path(p.userdata).resolve())
    import kalshi_auth
    if p.kalshi_env != "production":
        log.error(f"KALSHI_ENV must be production, got {p.kalshi_env}")
        sys.exit(2)
    if not p.key_id:
        log.error("KALSHI_KEY_ID is empty")
        sys.exit(2)
    kalshi_auth.set_env(p.kalshi_env)
    try:
        kalshi_auth.save_credentials(p.key_id, p.load_pem(), p.kalshi_env)
    except Exception as e:
        log.error(f"credentials rejected: {e}")
        sys.exit(2)
    fp = kalshi_auth.credentials_status(p.kalshi_env)
    log.info(f"creds loaded: env={p.kalshi_env} key…{p.key_id[-4:]} rsaFingerprint={fp.get('fingerprint')}")
    return kalshi_auth



class Runner:
    def __init__(self, p: Params):
        self.p = p
        self.spot_hist: dict[str, deque] = {}
        self.mid_hist: dict[str, deque] = {}
        self._cur_spot: dict[str, float] = {}
        self._spot_appended: dict[str, float] = {}
        self._mid_appended: dict[str, float] = {}
        self._ring_append_sec = 0.05
        self.markets: dict[str, dict] = {}
        self.entered: dict[str, float] = {}
        self.entries_today = 0
        self.spend_today = 0.0
        self.day = self._utc_day()
        self.total_signals = 0
        self.total_orders = 0
        self.stop = False

    @staticmethod
    def _utc_day() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _roll_day(self):
        d = self._utc_day()
        if d != self.day:
            log.info(f"── UTC day rollover {self.day} -> {d}: caps reset ──")
            self.day, self.entries_today, self.spend_today = d, 0, 0.0

    def _concurrent(self, now: float) -> int:
        return sum(1 for ce in self.entered.values() if ce > now)

    def _lookback(self, ring: deque, now: float, ago: float):
        """Newest sample at least `ago` seconds old (or the oldest we have)."""
        target = now - ago
        chosen = None
        for ts, v in ring:
            if ts <= target:
                chosen = v
            else:
                break
        return chosen if chosen is not None else (ring[0][1] if ring else None)

    async def discover(self, kalshi_api, kalshi_ws):
        """~every 6s: list active 15m markets per series via the PUBLIC markets
        endpoint (no auth, no heavy snapshot) and keep the WS subscribed. Off
        the hot path; failures are non-fatal (keep the last-known market set)."""
        while not self.stop:
            m: dict[str, dict] = {}
            for asset, series in self.p.asset_series.items():
                try:
                    mkts, _ = await kalshi_api.fetch_markets(status="open", series_ticker=series)
                except Exception as e:
                    log.debug(f"discover {series}: {e}")
                    continue
                for mk in mkts:
                    tk = mk.get("ticker")
                    ce = parse_close_epoch(mk.get("close_time"))
                    if tk and ce:
                        m[tk] = {"asset": asset, "close_epoch": ce}
            if m:
                self.markets = m
                if kalshi_ws.is_connected():
                    kalshi_ws.set_ticker_markets(set(m))
                    kalshi_ws.set_orderbook_markets(set(m))
            await asyncio.sleep(6.0)

    async def prewarm(self, kalshi_api):
        """Keep the signed HTTP connection HOT. Signals are sparse (~once/7min)
        but httpx keep-alive expires at 60s, so without this almost every order
        would pay a fresh TCP+TLS handshake (~100-300ms) on the critical path.
        A cheap signed GET every prewarm_sec keeps the socket warm so the order
        POST is just one round-trip. Doubles as a live auth/balance check."""
        first = True
        while not self.stop:
            try:
                bal = await kalshi_api.get_balance()
                if first:
                    cents = (bal or {}).get("balance")
                    log.info(f"signed connection warm — account balance: {cents}")
                    first = False
            except Exception as e:
                log.warning(f"prewarm/balance failed (auth or network?): {e}")
            await asyncio.sleep(max(5.0, self.p.prewarm_sec))

    async def hot_loop(self, kalshi_ws, spot_ws, kalshi_api):
        """Fast loop: detect spot-vs-book divergence and fire taker entries.

        Runs as tight as the OS timer allows (default 10ms; the Windows system
        timer is bumped to 1ms in _amain so the sleep is honoured). 'now' spot
        and book are read FRESH every tick; the rings only hold the ~3s-ago
        reference and are appended on a 50ms throttle to stay small."""
        interval = max(0.002, self.p.sample_ms / 1000.0)
        while not self.stop:
            now = time.time()
            self._roll_day()
            for a in {m["asset"] for m in self.markets.values()}:
                s = spot_ws.spot(a)
                if s is None:
                    continue
                self._cur_spot[a] = float(s)
                if now - self._spot_appended.get(a, 0.0) >= self._ring_append_sec:
                    r = self.spot_hist.setdefault(a, deque())
                    r.append((now, float(s)))
                    self._spot_appended[a] = now
                    while r and now - r[0][0] > self.p.lookback_sec + 2:
                        r.popleft()
            for tk, meta in list(self.markets.items()):
                try:
                    self._scan_one(tk, meta, now, kalshi_ws, kalshi_api)
                except Exception as e:
                    log.debug(f"scan {tk} error: {e}")
            await asyncio.sleep(interval)

    def _scan_one(self, tk, meta, now, kalshi_ws, kalshi_api):
        ce = meta["close_epoch"]
        mins_left = (ce - now) / 60.0
        if not (self.p.entry_min_mins <= mins_left <= self.p.entry_max_mins):
            return
        if self.p.per_ticker_once and tk in self.entered:
            return
        q = kalshi_ws.ticker_quote(tk)
        if not q:
            return
        yb, ya = q.get("yes_bid_cents"), q.get("yes_ask_cents")
        if yb is None or ya is None or not (0 < yb <= ya < 100):
            return
        mid = (yb + ya) / 2.0
        ring = self.mid_hist.setdefault(tk, deque())
        if now - self._mid_appended.get(tk, 0.0) >= self._ring_append_sec:
            ring.append((now, mid))
            self._mid_appended[tk] = now
            while ring and now - ring[0][0] > self.p.lookback_sec + 2:
                ring.popleft()
        asset = meta["asset"]
        sr = self.spot_hist.get(asset)
        spot_now = self._cur_spot.get(asset)
        if not sr or spot_now is None:
            return
        spot_then = self._lookback(sr, now, self.p.lookback_sec)
        if not spot_then or spot_then <= 0:
            return
        aret_bps = (spot_now - spot_then) / spot_then * 1e4
        mid_then = self._lookback(ring, now, self.p.lookback_sec)
        if mid_then is None:
            return
        book_move_c = abs(mid - mid_then)
        if abs(aret_bps) < self.p.move_bps or book_move_c > self.p.book_stale_c:
            return
        side = "up" if aret_bps > 0 else "down"
        cost_c = ya if side == "up" else (100 - yb)
        if not (self.p.min_price_c <= cost_c <= self.p.max_price_c):
            return
        self.total_signals += 1
        self._fire(tk, side, int(round(cost_c)), meta, now, aret_bps, book_move_c, kalshi_api)

    def _fire(self, tk, side, cost_c, meta, now, aret_bps, book_move_c, kalshi_api):
        if self._concurrent(now) >= self.p.max_concurrent:
            return
        if self.entries_today >= self.p.max_entries_day:
            return
        est_spend = cost_c / 100.0 * self.p.contracts
        if self.spend_today + est_spend > self.p.max_daily_spend:
            log.info(f"daily spend cap ${self.p.max_daily_spend:.2f} would be exceeded — standing down")
            return
        price_c = min(99, cost_c + self.p.cross_buffer_c)
        api_side = "yes" if side == "up" else "no"
        tag = (f"{tk} {side.upper()} ask={cost_c}c pay<= {price_c}c x{self.p.contracts}  "
               f"(Δspot={aret_bps:+.1f}bp/{self.p.lookback_sec:.0f}s book+{book_move_c:.1f}c "
               f"{mins_left_str(meta, now)})")
        self.entered[tk] = meta["close_epoch"]
        self.entries_today += 1
        self.spend_today += est_spend
        if not self.p.live:
            log.info(f"DRY-RUN would BUY {tag}")
            return
        log.info(f"LIVE BUY {tag}")
        asyncio.create_task(self._place(tk, api_side, price_c, kalshi_api))

    async def _place(self, tk, api_side, price_c, kalshi_api):
        coid = str(uuid.uuid4())
        try:
            resp = await kalshi_api.place_limit_order(
                ticker=tk, side=api_side, action="buy",
                count=self.p.contracts, price_cents=price_c, client_order_id=coid,
            )
        except Exception as e:
            log.error(f"ORDER FAILED {tk}: {e}")
            return
        self.total_orders += 1
        order = (resp.get("order") if isinstance(resp, dict) else None) or {}
        oid, status = order.get("order_id"), order.get("status")
        log.info(f"  order {tk}: id={oid} status={status}")
        if self.p.cancel_remainder and oid and str(status).lower() in ("resting", "open", "canceled_partially"):
            await asyncio.sleep(0.4)
            try:
                await kalshi_api.cancel_order(oid)
                log.info(f"  cancelled resting remainder {tk} {oid}")
            except Exception as e:
                log.debug(f"remainder cancel {tk}: {e}")

    def summary(self):
        log.info(f"── session: {self.total_signals} signals, {self.total_orders} orders placed, "
                 f"{self.entries_today} entries today, ${self.spend_today:.2f} spent ──")


def mins_left_str(meta, now):
    return f"{(meta['close_epoch']-now)/60.0:.1f}m left"



async def _amain(p: Params, kalshi_auth):
    import kalshi_api
    import kalshi_ws
    import spot_ws

    spot_ws.start()
    kalshi_ws.start(p.kalshi_env)
    kalshi_ws.set_cf_enabled(True)

    for _ in range(20):
        if kalshi_ws.is_connected():
            break
        await asyncio.sleep(0.5)
    log.info(f"kalshi_ws connected={kalshi_ws.is_connected()}  spot_ws running={spot_ws.is_running()}")

    r = Runner(p)
    tasks = [
        asyncio.create_task(r.prewarm(kalshi_api)),
        asyncio.create_task(r.discover(kalshi_api, kalshi_ws)),
        asyncio.create_task(r.hot_loop(kalshi_ws, spot_ws, kalshi_api)),
    ]
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        r.stop = True
        for t in tasks:
            t.cancel()
        try:
            await kalshi_ws.stop()
        except Exception:
            pass
        try:
            await spot_ws.stop()
        except Exception:
            pass
        r.summary()


def _banner(p: Params):
    mode = "🔴 LIVE — REAL ORDERS" if p.live else "🟢 DRY-RUN (no orders)"
    print("=" * 74)
    print(f"  staleness-entry runner   [{mode}]   env={p.kalshi_env}")
    print(f"  signal : spot move >= {p.move_bps:.0f}bp / {p.lookback_sec:.0f}s  AND  book stale <= {p.book_stale_c:.0f}c")
    print(f"  entry  : buy favored side taker, {p.contracts} ct, price {p.min_price_c}-{p.max_price_c}c, "
          f"{p.entry_min_mins:.0f}-{p.entry_max_mins:.0f}m left, HOLD to settle")
    print(f"  caps   : {p.max_concurrent} concurrent, {p.max_entries_day}/day, ${p.max_daily_spend:.2f}/day spend")
    print(f"  speed  : {p.sample_ms}ms hot loop, connection pre-warmed every {p.prewarm_sec:.0f}s "
          f"(1ms timer on win32)")
    print("=" * 74)


def main():
    env_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".env.staleness")
    p = Params(load_env_file(env_path))
    _banner(p)
    kalshi_auth = bootstrap_credentials(p)
    if p.live:
        print("\n  LIVE mode: placing REAL orders in 5s. Ctrl-C to abort.\n")
        try:
            time.sleep(5)
        except KeyboardInterrupt:
            print("aborted."); return
    winmm = None
    if sys.platform == "win32":
        try:
            import ctypes
            winmm = ctypes.WinDLL("winmm")
            winmm.timeBeginPeriod(1)
        except Exception as e:
            log.debug(f"timeBeginPeriod unavailable: {e}")
    try:
        asyncio.run(_amain(p, kalshi_auth))
    except KeyboardInterrupt:
        log.info("stopped by user")
    finally:
        if winmm is not None:
            try:
                winmm.timeEndPeriod(1)
            except Exception:
                pass


if __name__ == "__main__":
    main()
