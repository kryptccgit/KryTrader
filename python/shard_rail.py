"""Moving collateral to the Kalshi exchange shard an order needs.

Kalshi keeps collateral PER matching-engine shard and does not rebalance a
retail account (that is an institutional feature). Cash on the general shard
cannot back a crypto order, and the rejection names nothing the user can act
on. Every engine that trades across markets — the auto-trader, 15-minute
crypto, scripts, the terminal, AI agents — hit this the moment it left the
shard the money happened to sit on.

Two ways money moves here, both through `kalshi_api.transfer_between_shards`
(overdraw guard, whole cents rounded DOWN, never retried — the endpoint has no
idempotency key, so a retry after a lost response moves the money twice):

* `ensure_collateral` — the app's own rail, called from the one live order
  path (`kalshi_api.place_limit_order`) before a BUY is signed. It moves only
  the shortfall: what the order can cost (price plus a fee allowance) minus
  what the shard already holds, from the shards with the most spare cash. On
  by default whenever the account is Live (`shard_auto_move`); Paper has one
  pool of money and nothing to move.
* `move` — an explicit transfer, for an AI agent's `move_funds` tool.

Both share one lock (two orders racing for the same shortfall would each move
it) and one daily cap (`shard_auto_move_max_usd_day`), read from the
`shard_transfers` audit table so a restart cannot reset it. Money never leaves
the account here: it moves between the user's own shards, and every move is
logged and audited.

Fails OPEN on unknowns, like the rest of the shard handling: an unknown shard
for the ticker, a key with no per-shard breakdown, a balance read that failed —
the order goes as it would have, and Kalshi decides. Blocking trading on a
number we could not read would be worse than the rejection it prevents.
"""
from __future__ import annotations

import asyncio
import logging
import math
from typing import Callable, Optional

import db
import kalshi_api
import kalshi_auth

logger = logging.getLogger(__name__)

FEE_ALLOWANCE_CENTS = 2

LAND_TIMEOUT_S = 4.0
LAND_POLL_S = 0.4

GET_CFG: Callable[[], dict] = lambda: {}

_lock_by_loop: dict = {}


def _lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lk = _lock_by_loop.get(id(loop))
    if lk is None or lk[0] is not loop:
        lk = (loop, asyncio.Lock())
        _lock_by_loop[id(loop)] = lk
    return lk[1]


def enabled(cfg: Optional[dict] = None) -> bool:
    """The app moves funds by itself: Live account, rail switched on."""
    cfg = cfg if cfg is not None else GET_CFG()
    if kalshi_auth.is_paper():
        return False
    return cfg.get("shard_auto_move", True) is not False


def daily_cap_usd(cfg: Optional[dict] = None) -> float:
    cfg = cfg if cfg is not None else GET_CFG()
    try:
        v = float(cfg.get("shard_auto_move_max_usd_day", 1000.0))
    except (TypeError, ValueError):
        v = 1000.0
    return v if math.isfinite(v) and v > 0 else 1000.0


def moved_today_usd(env: str) -> float:
    """Automatic and agent moves today (UTC). The user's own are uncapped."""
    with db.get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount_usd), 0) FROM shard_transfers "
            "WHERE kalshi_env=? AND ok=1 AND by<>'you' "
            "AND date(created_at)=date('now')",
            (env,),
        ).fetchone()
    return float(row[0] or 0.0)


def record(env: str, src: int, dst: int, amount: float, by: str, ok: bool, note: str = "") -> None:
    try:
        with db.get_db() as conn:
            conn.execute(
                "INSERT INTO shard_transfers (kalshi_env, from_shard, to_shard, amount_usd, by, ok, note) "
                "VALUES (?,?,?,?,?,?,?)",
                (env, int(src), int(dst), round(float(amount), 2), by[:80], 1 if ok else 0, note[:300]),
            )
    except Exception as e:
        logger.warning(f"shard transfer audit write failed: {type(e).__name__}")


def _cents_up(usd: float) -> float:
    return math.ceil(round(usd * 100, 6)) / 100.0


async def _fresh_shards(env: str) -> Optional[dict[int, float]]:
    """{shard: dollars} read now, or None (unknown: fail open)."""
    try:
        bal = await kalshi_api.get_balance(pin_env=env)
    except Exception as e:
        logger.info(f"shard rail: balance read failed ({type(e).__name__}); not moving funds")
        return None
    shards = (bal or {}).get("shard_balances") or {}
    return {int(k): float(v) for k, v in shards.items()} or None


async def _await_landed(env: str, dst: int, need: float) -> bool:
    """Poll until shard `dst` holds `need`, or the timeout. True = landed."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + LAND_TIMEOUT_S
    while True:
        shards = await _fresh_shards(env)
        if shards and float(shards.get(dst, 0.0)) + 1e-9 >= need:
            return True
        if loop.time() >= deadline:
            logger.info(f"[shards] moved funds not showing on {kalshi_api.shard_name(dst)} after "
                        f"{LAND_TIMEOUT_S:.0f}s; sending the order anyway")
            return False
        await asyncio.sleep(LAND_POLL_S)


async def _refresh_cache() -> None:
    try:
        import trader
        await trader.refresh_balance(GET_CFG(), force=True)
    except Exception:
        pass


async def _shard_of(ticker: str) -> Optional[int]:
    idx = kalshi_api.shard_for_ticker(ticker)
    if idx is None:
        try:
            await kalshi_api.fetch_market(ticker)
        except Exception:
            return None
        idx = kalshi_api.shard_for_ticker(ticker)
    return int(idx) if idx is not None else None


async def _move_locked(env: str, dst: int, need_usd: float, by: str, shards: dict[int, float],
                       src: Optional[int] = None) -> tuple[float, list[str]]:
    """Move up to `need_usd` onto `dst`, richest source first (or only `src`).
    Returns (moved, notes). Caller holds the lock."""
    notes: list[str] = []
    room = daily_cap_usd() - moved_today_usd(env)
    if room <= 0:
        notes.append("the daily cap on automatic moves is used up")
        return 0.0, notes
    want = min(need_usd, room)
    if want < need_usd:
        notes.append(f"the daily cap allows ${room:,.2f} more today")
    sources = [src] if src is not None else sorted(
        (i for i in shards if i != dst), key=lambda i: shards.get(i, 0.0), reverse=True)
    moved = 0.0
    for s in sources:
        left = round(want - moved, 2)
        if left < 0.01:
            break
        have = math.floor(round(shards.get(s, 0.0) * 100, 6)) / 100.0
        take = round(min(left, have), 2)
        if take < 0.01:
            continue
        try:
            await kalshi_api.transfer_between_shards(amount_usd=take, source_shard=s, destination_shard=dst)
        except Exception as e:
            record(env, s, dst, take, by, False, f"{type(e).__name__}: {e}"[:300])
            notes.append(f"moving ${take:,.2f} from {kalshi_api.shard_name(s)} failed: "
                         f"{kalshi_api.rejection_text(e)}")
            break
        record(env, s, dst, take, by, True)
        logger.info(f"[shards] moved ${take:,.2f} {kalshi_api.shard_name(s)} -> "
                    f"{kalshi_api.shard_name(dst)} ({by})")
        moved = round(moved + take, 2)
        shards[s] = round(shards.get(s, 0.0) - take, 2)
        shards[dst] = round(shards.get(dst, 0.0) + take, 2)
    if moved:
        await _refresh_cache()
    return moved, notes


async def ensure_collateral(*, ticker: str, count: int, price_cents: float, env: str) -> Optional[str]:
    """Before a live BUY: make sure the shard hosting `ticker` can cover it.

    Returns a short note when it moved money or could not, else None. Never
    raises: the order goes either way, and Kalshi has the last word.
    """
    try:
        if env == kalshi_auth.PAPER or not enabled():
            return None
        need = _cents_up(max(0, int(count)) * (float(price_cents) + FEE_ALLOWANCE_CENTS) / 100.0)
        if need <= 0:
            return None
        dst = await _shard_of(ticker)
        if dst is None:
            return None
        import trader
        cached = trader.cached_shard_balances(env)
        if cached and float(cached.get(dst, 0.0)) >= need:
            return None
        async with _lock():
            shards = await _fresh_shards(env)
            if not shards:
                return None
            have = float(shards.get(dst, 0.0))
            short = _cents_up(need - have)
            if short <= 0:
                return None
            moved, notes = await _move_locked(env, dst, short, "auto", shards)
            if moved:
                await _await_landed(env, dst, min(need, have + moved))
        name = kalshi_api.shard_name(dst)
        if moved:
            msg = f"moved ${moved:,.2f} to the {name} exchange for this order"
            return msg + (f" ({'; '.join(notes)})" if notes else "")
        return f"could not fund the {name} exchange: {'; '.join(notes) or 'no other exchange has spare cash'}"
    except Exception as e:
        logger.warning(f"shard rail error (order goes as-is): {type(e).__name__}: {e}")
        return None


async def move(*, amount_usd: float, to_shard: int, from_shard: Optional[int], by: str) -> dict:
    """An explicit move (an AI agent's `move_funds`). Live only, capped by the
    same daily budget as the automatic rail. Raises ValueError with a sentence
    the agent can act on."""
    if kalshi_auth.is_paper():
        raise ValueError("Paper mode has one pool of money; there is nothing to move between exchanges.")
    try:
        amt = float(amount_usd)
    except (TypeError, ValueError):
        raise ValueError("amount_usd must be a number of dollars.")
    if not math.isfinite(amt) or amt < 0.01:
        raise ValueError("amount_usd must be at least $0.01.")
    amt = math.floor(round(amt * 100, 6)) / 100.0
    env = kalshi_auth.get_env()
    async with _lock():
        shards = await _fresh_shards(env)
        if not shards:
            raise ValueError("Kalshi did not return a per-exchange balance, so nothing was moved.")
        if to_shard not in shards and to_shard not in kalshi_api.SHARD_NAMES:
            raise ValueError(f"There is no exchange {to_shard} on this account.")
        if from_shard is not None:
            if from_shard == to_shard:
                raise ValueError("Source and destination are the same exchange.")
            have = shards.get(from_shard, 0.0)
            if amt > have + 1e-9:
                raise ValueError(f"The {kalshi_api.shard_name(from_shard)} exchange holds ${have:,.2f}; "
                                 f"cannot move ${amt:,.2f} from it.")
        else:
            spare = sum(v for i, v in shards.items() if i != to_shard)
            if amt > spare + 1e-9:
                raise ValueError(f"The other exchanges hold ${spare:,.2f} between them; cannot move ${amt:,.2f}.")
        before_dst = float(shards.get(to_shard, 0.0))
        moved, notes = await _move_locked(env, to_shard, amt, by, shards, src=from_shard)
        after = dict(shards)
        if moved:
            await _await_landed(env, to_shard, before_dst + moved)
    if not moved:
        raise ValueError("Nothing was moved: " + ("; ".join(notes) or "no exchange had spare cash") + ".")
    return {
        "movedUsd": moved,
        "to": kalshi_api.shard_name(to_shard),
        "notes": notes,
        "exchanges": {kalshi_api.shard_name(i): round(v, 2) for i, v in sorted(after.items())},
    }


def parse_shard(v) -> int:
    """An exchange named by number or by name ("crypto", "general", ...)."""
    if isinstance(v, bool):
        raise ValueError("Name the exchange by number or name.")
    if isinstance(v, (int, float)) and float(v).is_integer():
        i = int(v)
    else:
        s = str(v or "").strip().lower()
        if s.isdigit():
            i = int(s)
        else:
            by_name = {n.lower(): k for k, n in kalshi_api.SHARD_NAMES.items()}
            if s not in by_name:
                raise ValueError("Unknown exchange. Use one of: "
                                 + ", ".join(sorted(kalshi_api.SHARD_NAMES.values())) + ", or its number.")
            i = by_name[s]
    if not 0 <= i <= 100:
        raise ValueError("Exchange number out of range.")
    return i
