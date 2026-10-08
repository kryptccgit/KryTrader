"""Perps volume farmer — maker-only, two-sided, loss-capped.

Kalshi's in-app perps rewards pay volume bonuses (observed 2026-07:
trade $50 → $25, $100K notional → $40, $1M → $200 ≈ 2-4 bps of volume).
This engine generates qualifying volume at the lowest achievable cost:
join the best bid AND best ask with small post_only clips, let the market
fill both sides, and let captured spread offset the maker fees. It is a
volume engine with a loss budget — NOT a profit strategy:

    net cost / $ volume ≈ maker fee (5 bps today, 4 at the $100K 30-day
    tier from ~Jul 8) − captured half-spread (~1-3 bps on KXBTCPERP)
    ± adverse selection (unknowable up front — measured live below).

The whole design hangs on MEASURED economics: every fill lands in
perp_farm_fills (volume, fees, avg-cost realized P&L) and the engine
auto-halts for the UTC day when the realized cost per $ of volume exceeds
`perps_farm_max_cost_bps` (default = the ~4 bps bonus rate: if farming
costs more than the bonus pays, stop burning) or the hard daily loss cap.

Compliance: single-account genuine two-sided resting liquidity — exactly
what venue programs pay for. No self-matches: quotes never cross each
other (cross-guard + venue self-trade prevention), no wash trades, no
prearranged volume (Rulebook 5.17).

Mechanics per ~2.5s tick (gated from the service main loop, never raises):
  * gates: enabled, WS quote fresh, spread ≥ min ticks, not in the Thu
    maintenance window, margin enabled + funded (cached), daily halts
  * desired quotes: join best bid / best ask, post_only, clip contracts;
    an inventory beyond ±cap quotes only the reducing side
  * requote: cancel/replace a resting order when the touch moved more than
    `requote_ticks` away from its price
  * fills: polled via GET /margin/fills since the last seen fill, deduped
    into perp_farm_fills; inventory + avg-cost realized P&L updated here
  * reconcile: positions endpoint every ~60s is the inventory tiebreaker

Live orders are recovered by client_order_id after lost responses, the
same discipline as the event-side engines."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

import db
import kalshi_auth
import kalshi_perps_api as papi
import perps_ws as pws
from kalshi_api import KalshiAPIError

logger = logging.getLogger("perps_farmer")

TICK_MICRO = 100
_QUOTE_FRESH_MS = 180_000
_RECONCILE_SEC = 60.0
_BALANCE_CACHE_SEC = 60.0
_DEFAULT_MAKER_FEE_BPS = 5.0
_FEE_REFRESH_SEC = 300.0
_MIN_COST_SAMPLE_USD = 500.0
_MAINT_START_UTC = (6, 50)
_MAINT_END_UTC = (9, 10)


def _utc_day(ts: float | None = None) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d")


def in_maintenance_window(dt: datetime | None = None) -> bool:
    dt = dt or datetime.now(timezone.utc)
    if dt.weekday() != 3:
        return False
    hm = (dt.hour, dt.minute)
    return _MAINT_START_UTC <= hm < _MAINT_END_UTC



def desired_quotes(
    quote: dict, inventory_cc: int, cfg: dict,
) -> dict[str, int]:
    """{'bid': price_micro, 'ask': price_micro} we WANT resting, given the
    live top-of-book and our inventory. Empty dict = stand down this tick."""
    bid = quote.get("bid_usd_micro")
    ask = quote.get("ask_usd_micro")
    if not bid or not ask or ask <= bid:
        return {}
    min_spread = int(cfg.get("perps_farm_min_spread_ticks", 2)) * TICK_MICRO
    if ask - bid < min_spread:
        return {}
    max_inv = int(cfg.get("perps_farm_max_inventory_contracts", 3)) * 100
    out: dict[str, int] = {}
    if inventory_cc < max_inv:
        out["bid"] = bid
    if inventory_cc > -max_inv:
        out["ask"] = ask
    return out


def should_replace(live_price_micro: int, target_micro: int, cfg: dict) -> bool:
    tol = int(cfg.get("perps_farm_requote_ticks", 1)) * TICK_MICRO
    return abs(live_price_micro - target_micro) > tol


def apply_fill(inv_cc: int, avg_micro: float, side: str, count_cc: int,
               price_micro: int) -> tuple[int, float, int]:
    """Avg-cost inventory accounting. Returns (new_inv_cc, new_avg_micro,
    realized_pnl_usd_micro). side is OUR order side: bid = buy (+), ask = sell (−)."""
    signed = count_cc if side == "bid" else -count_cc
    realized = 0.0
    if inv_cc == 0 or (inv_cc > 0) == (signed > 0):
        total = abs(inv_cc) + abs(signed)
        avg_micro = (avg_micro * abs(inv_cc) + price_micro * abs(signed)) / total
        inv_cc += signed
    else:
        reduce_cc = min(abs(inv_cc), abs(signed))
        direction = 1 if inv_cc > 0 else -1
        realized = direction * (price_micro - avg_micro) * reduce_cc / 100.0
        inv_cc += signed
        if (inv_cc > 0) != (direction > 0) and inv_cc != 0:
            avg_micro = float(price_micro)
        elif inv_cc == 0:
            avg_micro = 0.0
    return inv_cc, avg_micro, int(round(realized))



class _Farmer:
    def __init__(self) -> None:
        self.env: str = "production"
        self.running: bool = False
        self.halted_day: str = ""
        self.halt_reason: str = ""
        self.inventory_cc: int = 0
        self.avg_entry_micro: float = 0.0
        self.live: dict[str, dict] = {}
        self.last_fill_ts: int = 0
        self._last_reconcile: float = 0.0
        self._last_balance_t: float = 0.0
        self._maker_fee_bps: float | None = None
        self._last_fee_calc: float = 0.0
        self._balance_ok: bool = False
        self._margin_enabled: bool | None = None
        self.last_error: str = ""
        self.day_stats: dict = {}
        self._stats_dirty: bool = True
        self._stats_day: str = ""


    def _wire_ticker(self, cfg: dict) -> str:
        sym = str(cfg.get("perps_farm_symbol") or "KXBTCPERP").upper().rstrip("1")
        return papi.env_ticker(sym, self.env)

    def _halted(self) -> bool:
        return self.halted_day == _utc_day()

    def _halt(self, reason: str) -> None:
        if not self._halted():
            logger.warning(f"perps_farmer: HALTED for {_utc_day()} — {reason}")
        self.halted_day = _utc_day()
        self.halt_reason = reason

    async def stop(self, *, cancel_orders: bool = True) -> None:
        self.running = False
        if cancel_orders:
            await self._cancel_all()


    async def _cancel_all(self) -> None:
        for side in list(self.live):
            o = self.live.pop(side, None)
            if not o or not o.get("order_id"):
                continue
            try:
                await papi.cancel_perps_order(o["order_id"])
            except Exception as e:
                logger.debug(f"perps_farmer: cancel {side} failed: {e}")

    async def _place(self, ticker: str, side: str, price_micro: int, count_cc: int) -> None:
        coid = str(uuid.uuid4())
        try:
            resp = await papi.place_perps_limit_order(
                ticker=ticker, side=side, count_cc=count_cc,
                price_usd_micro=price_micro, post_only=True,
                client_order_id=coid,
            )
            oid = str(resp.get("order_id") or "")
            if oid:
                self.live[side] = {
                    "order_id": oid, "price_micro": price_micro,
                    "count_cc": count_cc, "client_order_id": coid,
                }
        except KalshiAPIError as e:
            logger.debug(f"perps_farmer: place {side} rejected: {e}")
        except Exception as e:
            try:
                o = await papi.find_perps_order_by_client_id(coid, ticker=ticker)
            except Exception:
                o = None
            if o and str(o.get("order_id") or ""):
                self.live[side] = {
                    "order_id": str(o["order_id"]), "price_micro": price_micro,
                    "count_cc": count_cc, "client_order_id": coid,
                }
            else:
                logger.debug(f"perps_farmer: place {side} failed: {e}")


    async def _poll_fills(self, ticker: str, cfg: dict) -> None:
        min_ts = self.last_fill_ts - 5 if self.last_fill_ts else int(time.time()) - 3600
        try:
            fills = await papi.get_perps_fills(min_ts=min_ts)
        except Exception as e:
            logger.debug(f"perps_farmer: fills poll failed: {e}")
            return
        new_rows = []
        for f in fills:
            tkr = f.get("market_ticker") or f.get("ticker") or ""
            if tkr != ticker:
                continue
            trade_id = str(f.get("fill_id") or f.get("trade_id") or "")
            if not trade_id:
                continue
            price = papi.usd_micro(f.get("price"))
            count = papi.cc(f.get("count"))
            if price is None or count is None:
                continue
            ts_ms = f.get("ts_ms")
            if ts_ms is None and f.get("created_time"):
                try:
                    dt = datetime.fromisoformat(
                        str(f["created_time"]).replace("Z", "+00:00"))
                    ts_ms = int(dt.timestamp() * 1000)
                except ValueError:
                    ts_ms = None
            new_rows.append({
                "trade_id": trade_id,
                "order_id": str(f.get("order_id") or ""),
                "ticker": tkr,
                "ts_ms": ts_ms,
                "side": str(f.get("side") or ""),
                "count_cc": count,
                "price_usd_micro": price,
                "fee_usd_micro": papi.usd_micro(
                    f.get("fees") if f.get("fees") is not None
                    else f.get("fee_cost")) or 0,
                "is_taker": bool(f.get("is_taker")),
            })
        if not new_rows:
            return
        new_rows.sort(key=lambda r: r["ts_ms"] or 0)
        with db.get_db() as conn:
            for r in new_rows:
                if db.perp_farm_fill_seen(conn, r["trade_id"], self.env):
                    continue
                inv, avg, realized = apply_fill(
                    self.inventory_cc, self.avg_entry_micro,
                    r["side"], r["count_cc"], r["price_usd_micro"],
                )
                self.inventory_cc, self.avg_entry_micro = inv, avg
                r["realized_pnl_usd_micro"] = realized
                r["inventory_after_cc"] = inv
                r["kalshi_env"] = self.env
                db.insert_perp_farm_fill(conn, r)
                self._stats_dirty = True
                if r["ts_ms"]:
                    self.last_fill_ts = max(self.last_fill_ts, int(r["ts_ms"] // 1000))
                for side, o in list(self.live.items()):
                    if o.get("order_id") == r["order_id"]:
                        self.live.pop(side, None)

    def _refresh_day_stats(self) -> dict:
        day = _utc_day()
        if not self._stats_dirty and self._stats_day == day and self.day_stats:
            return self.day_stats
        try:
            with db.get_db() as conn:
                self.day_stats = db.perp_farm_stats(conn, self.env, day_utc=day)
            self._stats_day = day
            self._stats_dirty = False
        except Exception as e:
            logger.debug(f"perps_farmer: stats failed: {e}")
        return self.day_stats

    def _refresh_maker_fee(self) -> None:
        """Refresh the measured maker fee (bps) at most every _FEE_REFRESH_SEC.
        None until enough real fills exist; the gate then assumes Tier-0."""
        now = time.monotonic()
        if self._last_fee_calc and now - self._last_fee_calc < _FEE_REFRESH_SEC:
            return
        self._last_fee_calc = now
        try:
            with db.get_db() as conn:
                self._maker_fee_bps = db.perp_farm_effective_fee_bps(conn, self.env)
        except Exception as e:
            logger.debug(f"perps_farmer: fee calc failed: {e}")

    def _fee_gate_blocks(self, cfg: dict) -> str:
        """Non-empty reason when the maker fee we're charged exceeds the user's
        cap (0 = off). Cost of farming ≈ the maker fee, so this keeps the farmer
        idle until fees are actually worth it."""
        max_fee = float(cfg.get("perps_farm_max_fee_bps", 0) or 0)
        if max_fee <= 0:
            return ""
        fee = self._maker_fee_bps if self._maker_fee_bps is not None else _DEFAULT_MAKER_FEE_BPS
        if fee > max_fee + 1e-9:
            assumed = " (assumed Tier-0)" if self._maker_fee_bps is None else ""
            return (
                f"maker fee ~{fee:.1f} bps{assumed} exceeds your {max_fee:.1f} bps cap — "
                f"standing by; farm resumes automatically once the fee drops to your cap"
            )
        return ""

    def _check_economics(self, cfg: dict) -> None:
        s = self._refresh_day_stats()
        if not s:
            return
        vol_usd = s["volume_usd_micro"] / 1e6
        net_micro = s["realized_usd_micro"] - s["fees_usd_micro"]
        max_loss = float(cfg.get("perps_farm_daily_loss_usd", 2.0))
        if net_micro / 1e6 <= -max_loss:
            self._halt(f"daily loss cap hit (net ${net_micro / 1e6:.2f})")
            return
        max_cost_bps = float(cfg.get("perps_farm_max_cost_bps", 4.0))
        if vol_usd >= _MIN_COST_SAMPLE_USD and net_micro < 0:
            cost_bps = (-net_micro / 1e6) / vol_usd * 10_000
            if cost_bps > max_cost_bps:
                self._halt(
                    f"measured cost {cost_bps:.1f} bps/volume$ exceeds "
                    f"{max_cost_bps:.1f} bps cap"
                )
                return
        target = float(cfg.get("perps_farm_daily_volume_usd", 0) or 0)
        if target > 0 and vol_usd >= target:
            self._halt(f"daily volume target ${target:,.0f} reached")


    async def _reconcile(self, ticker: str) -> None:
        try:
            positions = await papi.get_perps_positions(ticker)
        except Exception as e:
            logger.debug(f"perps_farmer: reconcile failed: {e}")
            return
        remote_cc = 0
        remote_avg = 0.0
        for p in positions:
            if (p.get("market_ticker") or "") != ticker:
                continue
            remote_cc = papi.cc(p.get("position")) or 0
            remote_avg = float(papi.usd_micro(p.get("entry_price")) or 0)
        if remote_cc != self.inventory_cc:
            logger.info(
                f"perps_farmer: inventory reconcile {self.inventory_cc}→{remote_cc}cc "
                f"(exchange is source of truth)"
            )
            self.inventory_cc = remote_cc
            if remote_avg:
                self.avg_entry_micro = remote_avg

    async def _account_gates_ok(self, cfg: dict) -> bool:
        now = time.monotonic()
        if now - self._last_balance_t > _BALANCE_CACHE_SEC:
            self._last_balance_t = now
            try:
                if self._margin_enabled is None:
                    self._margin_enabled = await papi.get_perps_enabled()
                bal = await papi.get_perps_balance()
                avail = 0.0
                for sub in (bal.get("subaccount_balances") or []):
                    if int(sub.get("subaccount") or 0) == 0:
                        avail = float(papi.micro_to_usd(
                            papi.usd_micro(sub.get("available_balance"))) or 0)
                self._balance_ok = bool(self._margin_enabled) and avail > 1.0
                if not self._balance_ok:
                    self.last_error = (
                        "margin not enabled for account" if not self._margin_enabled
                        else "perps wallet unfunded (available < $1) — transfer funds first"
                    )
            except Exception as e:
                logger.debug(f"perps_farmer: balance gate failed: {e}")
                self._balance_ok = False
                self.last_error = f"balance check failed: {e}"
        return self._balance_ok


    async def farm_tick(self, cfg: dict) -> None:
        """Awaited from the service loop every ≥2.5s while enabled. Never raises."""
        try:
            await self._tick(cfg)
        except Exception as e:
            self.last_error = str(e)
            logger.debug(f"perps_farmer: tick error: {e}")

    async def _tick(self, cfg: dict) -> None:
        self.env = kalshi_auth.get_env()
        ticker = self._wire_ticker(cfg)
        self.running = True

        await self._poll_fills(ticker, cfg)
        self._check_economics(cfg)
        self._refresh_maker_fee()

        if self._halted() or in_maintenance_window():
            await self._cancel_all()
            return
        if not pws.is_connected():
            self.last_error = "perps stream offline"
            await self._cancel_all()
            return
        q = pws.quote(ticker)
        now_ms = int(time.time() * 1000)
        age_ref = q.get("recv_ms") or q.get("ts_ms") if q else None
        if not q or (age_ref and now_ms - int(age_ref) > _QUOTE_FRESH_MS):
            self.last_error = "quote stale"
            await self._cancel_all()
            return
        if not await self._account_gates_ok(cfg):
            await self._cancel_all()
            return
        fee_block = self._fee_gate_blocks(cfg)
        if fee_block:
            self.last_error = fee_block
            await self._cancel_all()
            return
        self.last_error = ""

        if time.monotonic() - self._last_reconcile > _RECONCILE_SEC:
            self._last_reconcile = time.monotonic()
            await self._reconcile(ticker)

        want = desired_quotes(
            {"bid_usd_micro": q.get("bid_usd_micro"),
             "ask_usd_micro": q.get("ask_usd_micro")},
            self.inventory_cc, cfg,
        )
        clip_cc = max(1, int(cfg.get("perps_farm_clip_contracts", 1))) * 100

        for side in list(self.live):
            if side not in want:
                o = self.live.pop(side)
                try:
                    await papi.cancel_perps_order(o["order_id"])
                except Exception:
                    pass

        for side, target in want.items():
            other = self.live.get("ask" if side == "bid" else "bid")
            if other:
                if side == "bid" and target >= other["price_micro"]:
                    continue
                if side == "ask" and target <= other["price_micro"]:
                    continue
            o = self.live.get(side)
            if o and not should_replace(o["price_micro"], target, cfg) \
                    and o["count_cc"] == clip_cc:
                continue
            if o:
                self.live.pop(side, None)
                try:
                    await papi.cancel_perps_order(o["order_id"])
                except Exception:
                    pass
            await self._place(ticker, side, target, clip_cc)

    async def flatten(self, cfg: dict) -> dict:
        """Cancel quotes and close inventory with reduce_only IOC at the touch."""
        ticker = self._wire_ticker(cfg)
        await self._cancel_all()
        closed = 0
        for _ in range(3):
            await self._reconcile(ticker)
            if self.inventory_cc == 0:
                break
            q = pws.quote(ticker)
            if not q:
                break
            side = "ask" if self.inventory_cc > 0 else "bid"
            px = q.get("bid_usd_micro") if side == "ask" else q.get("ask_usd_micro")
            if not px:
                break
            try:
                await papi.place_perps_limit_order(
                    ticker=ticker, side=side, count_cc=abs(self.inventory_cc),
                    price_usd_micro=px, time_in_force="immediate_or_cancel",
                    reduce_only=True,
                )
                closed += 1
            except Exception as e:
                logger.warning(f"perps_farmer: flatten leg failed: {e}")
                break
            await asyncio.sleep(1.0)
        await self._poll_fills(ticker, cfg)
        return {"inventoryCc": self.inventory_cc, "attempts": closed}

    def status(self, cfg: dict) -> dict:
        day = self._refresh_day_stats()
        self._refresh_maker_fee()
        vol = day.get("volume_usd_micro", 0) / 1e6 if day else 0.0
        fees = day.get("fees_usd_micro", 0) / 1e6 if day else 0.0
        realized = day.get("realized_usd_micro", 0) / 1e6 if day else 0.0
        net = realized - fees
        cost_bps = (-net / vol * 10_000) if vol > 0 and net < 0 else 0.0
        return {
            "enabled": bool(cfg.get("perps_farm_enabled", False)),
            "running": self.running,
            "halted": self._halted(),
            "haltReason": self.halt_reason if self._halted() else "",
            "lastError": self.last_error,
            "symbol": str(cfg.get("perps_farm_symbol") or "KXBTCPERP"),
            "makerFeeBps": (round(self._maker_fee_bps, 2)
                            if self._maker_fee_bps is not None else None),
            "maxFeeBps": float(cfg.get("perps_farm_max_fee_bps", 0) or 0),
            "inventoryContracts": self.inventory_cc / 100,
            "avgEntry": (self.avg_entry_micro / 1e6) if self.inventory_cc else None,
            "liveOrders": [
                {"side": s, "price": o["price_micro"] / 1e6,
                 "contracts": o["count_cc"] / 100}
                for s, o in self.live.items()
            ],
            "today": {
                "fills": day.get("fills", 0) if day else 0,
                "volumeUsd": round(vol, 2),
                "feesUsd": round(fees, 4),
                "realizedUsd": round(realized, 4),
                "netUsd": round(net, 4),
                "costBps": round(cost_bps, 2),
            },
            "maintenanceWindow": in_maintenance_window(),
        }


_farmer = _Farmer()


async def farm_tick(cfg: dict) -> None:
    await _farmer.farm_tick(cfg)


async def ensure_stopped() -> None:
    """Called when the toggle goes off — cancel resting quotes exactly once."""
    if _farmer.running or _farmer.live:
        await _farmer.stop(cancel_orders=True)


async def flatten(cfg: dict) -> dict:
    return await _farmer.flatten(cfg)


def status(cfg: dict) -> dict:
    return _farmer.status(cfg)


def ensure_ws(cfg: dict, env: str) -> None:
    """Config-reconcile the farmer's quote feed (owned here since the perps
    recorder was removed): the margin WS runs iff the farmer is enabled, the WS
    toggle is on, and credentials exist for the env (the margin WS handshake is
    always signed). Subscribes ONLY the farm symbol. perps_ws buffers are
    capped drop-oldest, so nothing drains them to the DB anymore — unconsumed
    rows simply age out; the farmer reads the live quote cache, not the tape."""
    want = (
        bool(cfg.get("perps_farm_enabled", False))
        and bool(cfg.get("perps_ws_enabled", True))
        and kalshi_auth.credentials_present(env)
    )
    if want:
        sym = str(cfg.get("perps_farm_symbol") or "KXBTCPERP")
        pws.set_symbols([papi.env_ticker(sym, env)])
        pws.set_env(env)
        if not pws.is_running():
            pws.start(env)
    elif pws.is_running():
        asyncio.get_event_loop().create_task(pws.stop())



_WALLET_TTL_SEC = 20.0
_wallet_cache: dict = {"t": 0.0, "data": None}


async def wallet(env: str) -> dict | None:
    """Perps (margin) wallet balance — the SEPARATE perps wallet, distinct from
    the main Kalshi cash balance. Powers the Perps page's wallet card.

    Cached ~20s: the available-balance computation costs 50 rate tokens/call and
    the page polls status every 3s. Never flashes a spurious zero — a failed or
    malformed poll serves the last-known snapshot (balance-flash-zero guard);
    returns None only before the first good read or when creds/env are absent."""
    if not kalshi_auth.credentials_present(env):
        return None
    now = time.monotonic()
    cached = _wallet_cache["data"]
    fresh = cached is not None and cached.get("env") == env \
        and now - _wallet_cache["t"] < _WALLET_TTL_SEC
    if fresh:
        return cached
    same_env_cache = cached if (cached and cached.get("env") == env) else None
    try:
        bal = await papi.get_perps_balance()
    except Exception as e:
        logger.debug(f"perps wallet fetch failed: {e}")
        return same_env_cache
    subs = bal.get("subaccount_balances") if isinstance(bal, dict) else None
    sub0 = next((s for s in (subs or []) if int(s.get("subaccount") or 0) == 0), None)
    if sub0 is None:
        return same_env_cache

    def d(x):
        return papi.micro_to_usd(papi.usd_micro(x))

    data = {
        "env": env,
        "settledUsd": d(bal.get("settled_funds")),
        "availableUsd": d(sub0.get("available_balance")),
        "positionValueUsd": d(sub0.get("position_value")),
        "restingMarginUsd": d(sub0.get("resting_orders_margin")),
        "maintenanceMarginUsd": d(sub0.get("maintenance_margin")),
    }
    _wallet_cache["t"] = now
    _wallet_cache["data"] = data
    return data
