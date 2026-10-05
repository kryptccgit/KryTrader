from __future__ import annotations

import asyncio
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import kalshi_api
import kalshi_auth

RESULTS: list[tuple[str, bool, str]] = []


def rec(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:38} {detail}")


WATCHED = {
    "KXBTC15M": "the 15m crypto engine",
    "KXETH15M": "the 15m crypto engine",
    "KXSOLD": "crypto",
    "KXBTCD": "crypto (daily)",
    "KXMLBGAME": "sports",
    "KXATPMATCH": "sports",
    "KXNFLGAME": "sports",
    "KXPRESNOMD": "politics",
}


async def markets() -> dict[str, int]:
    print("=== where do our series live now? ===")
    found: dict[str, int] = {}
    for series, why in WATCHED.items():
        rows, _ = await kalshi_api.fetch_markets("open", 5, "", series)
        if not rows:
            print(f"  {series:14} (no open markets right now)")
            continue
        idxs = {r.get("exchange_index") for r in rows}
        idx = next(iter(idxs)) if len(idxs) == 1 else None
        found[series] = idx if idx is not None else -1
        label = kalshi_api.shard_name(idx) if idx is not None else f"MIXED {idxs}"
        print(f"  {series:14} shard {str(idx):>4}  ({label}) — {why}")
    rec("markets report a shard", bool(found),
        f"{len(found)} series resolved")
    return found


async def orders_are_routed() -> None:
    print("\n=== order routing ===")
    import inspect
    src = inspect.getsource(kalshi_api.place_limit_order)
    rec("orders auto-route by ticker", '"exchange_index": -1' in src,
        "-1 = route by ticker, correct before and after 27 Aug")


async def shard_status() -> None:
    print("")
    print("=== per-shard trading status ===")
    st = await kalshi_api.fetch_exchange_status()
    if not st:
        rec("exchange status", False, "could not be read")
        return
    rec("exchange status", True,
        f"{len(st['shards'])} shard(s) described; "
        f"top-level trading_active={st['tradingActive']}")
    for idx in sorted(st["shards"]):
        r = st["shards"][idx]
        state = "trading" if r["tradingActive"] else "HALTED"
        print(f"  shard {idx:<4} {r['name']:<22} {state}")
    halted = sorted(i for i in st["shards"]
                    if not st["shards"][i]["tradingActive"])
    names = ", ".join(kalshi_api.shard_name(i) for i in halted)
    rec("per-shard halts surfaced", True,
        f"{len(halted)} engine(s) halted"
        + (f": {names}" if halted else " — all engines trading"))


async def positions_unfiltered() -> None:
    print("\n=== position reads span every shard ===")
    import inspect
    bad = [fn.__name__ for fn in (
        kalshi_api.get_positions, kalshi_api.fetch_orders,
        kalshi_api.get_fills_since)
        if "exchange_index" in inspect.getsource(fn)]
    rec("positions/orders/fills unfiltered", not bad,
        "omitting the filter returns the whole account"
        if not bad else f"SHARD-FILTERED: {bad} — reconcile would orphan-close")


async def collateral(series_shards: dict[str, int]) -> None:
    print("\n=== collateral, per shard ===")
    if not kalshi_auth.credentials_present():
        rec("collateral check", True,
            "SKIPPED — no saved credentials for this environment")
        return
    try:
        bal = await kalshi_api.get_balance()
    except Exception as e:
        rec("balance read", False, f"{type(e).__name__}: {e}")
        return

    shards = bal.get("shard_balances") or {}
    total = (bal.get("total_balance_cents") or 0) / 100.0
    scoped = (bal.get("balance") or 0) / 100.0
    rec("balance read", True,
        f"total ${total:,.2f} across {len(shards) or 1} shard(s); "
        f"the scoped `balance` field alone says ${scoped:,.2f}")

    if not shards:
        print("     (no per-shard breakdown — subaccount-restricted key)")
        return
    for idx, amount in sorted(shards.items()):
        print(f"     shard {idx} ({kalshi_api.shard_name(idx)}): ${amount:,.2f}")

    needed = {idx for idx in series_shards.values() if idx is not None and idx >= 0}
    starved = [i for i in needed if shards.get(i, 0.0) <= 0.0]
    if starved:
        names = ", ".join(f"{i} ({kalshi_api.shard_name(i)})" for i in sorted(starved))
        rec("collateral where our markets live", False,
            f"NO cash on shard(s) {names} — orders there will be refused for "
            f"collateral, and the rejection will not say so")
    else:
        rec("collateral where our markets live", True,
            "every shard we trade on is funded")


async def main() -> int:
    print("\nKalshi exchange sharding — live check\n")
    series_shards = await markets()
    await orders_are_routed()
    await shard_status()
    await positions_unfiltered()
    await collateral(series_shards)

    await kalshi_api.close_clients()
    fails = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(fails)} ok, {len(fails)} failed")
    for name, _ok, detail in fails:
        print(f"  FAILED {name}: {detail}")
    return 1 if fails else 0


raise SystemExit(asyncio.run(main()))
