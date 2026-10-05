from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import kalshi_api
import terminal

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
_results: list[tuple[str, str, str]] = []


def rec(name: str, verdict: str, detail: str) -> None:
    _results.append((name, verdict, detail))
    print(f"  {verdict:4}  {name:26} {detail}", flush=True)


def fmt(v) -> str:
    return "—" if v is None else str(v)


async def check_sweep() -> list[dict]:
    t0 = time.monotonic()
    try:
        res = await terminal.discover("trending", limit=8)
    except Exception as e:
        rec("discover/trending", FAIL, f"{type(e).__name__}: {e}")
        return []
    dt = time.monotonic() - t0
    rows = res["rows"]
    if not rows:
        rec("discover/trending", FAIL, f"no rows (scanned {res['scanned']})")
        return []
    rec("discover/trending", PASS,
        f"{len(rows)} rows over {res['scanned']:,} markets in {dt:.1f}s"
        f"{' (TRUNCATED)' if res['truncated'] else ''}")
    if res["note"]:
        print(f"        note: {res['note']}")
    top = rows[0]
    print(f"        top: {top['ticker']}  bid={fmt(top['yesBid'])} "
          f"ask={fmt(top['yesAsk'])} last={fmt(top['lastPrice'])} "
          f"vol24={fmt(top['volume24h'])} src={top['sources']}")

    bad = [r["ticker"] for r in rows
           if r["yesBid"] in (0, 100) or r["yesAsk"] in (0, 100)
           or r["lastPrice"] in (0, 100)]
    rec("honest-null quotes", FAIL if bad else PASS,
        f"{len(bad)} rows carry a 0c/100c price: {bad[:3]}" if bad
        else "no 0c/100c prices survived parsing")

    return rows


async def check_cache() -> None:
    t0 = time.monotonic()
    await terminal.discover("volume", limit=5, refresh=True)
    cold = time.monotonic() - t0
    t1 = time.monotonic()
    await terminal.discover("new", limit=5)
    warm = time.monotonic() - t1
    rec("sweep TTL cache", PASS if warm < max(0.25, cold / 3) else FAIL,
        f"cold {cold:.1f}s, warm {warm:.2f}s")


async def check_columns() -> None:
    for col in ("closing", "new", "volume"):
        try:
            res = await terminal.discover(col, limit=5)
        except Exception as e:
            rec(f"discover/{col}", FAIL, f"{type(e).__name__}: {e}")
            continue
        n = len(res["rows"])
        extra = ""
        if col == "closing" and res["rows"]:
            extra = f" (soonest {fmt(res['rows'][0]['minutesToClose'])} min)"
        rec(f"discover/{col}", PASS if n else FAIL, f"{n} rows{extra}")


async def check_market(ticker: str) -> None:
    try:
        d = await terminal.market_detail(ticker, authed=False)
    except Exception as e:
        rec("market detail", FAIL, f"{type(e).__name__}: {e}")
        return
    m = d["market"]
    rec("market detail", PASS,
        f"{m['ticker']} status={fmt(m['status'])} "
        f"close={fmt(m['closeTime'])} siblings="
        f"{len(d['event']['siblings']) if d['event'] else 0}")
    if d["errors"]:
        for e in d["errors"]:
            print(f"        panel {e['panel']} failed: {e['message'][:110]}")

    r = d["risk"]
    rec("resolution risk", PASS if r["totalCount"] >= 8 else FAIL,
        f"score={fmt(r['score'])} over {r['resolvedCount']}/{r['totalCount']} "
        f"resolved; sources={fmt(r['settlementSources'])}")
    for c in r["checks"]:
        print(f"        [{c['verdict']:7}] {c['label']}: {c['detail'][:96]}")

    b = d["book"]
    if b:
        rec("orderbook", PASS if (b["yes"] or b["no"]) else FAIL,
            f"src={b['source']} bid={fmt(b['yesBid'])} ask={fmt(b['yesAsk'])} "
            f"spread={fmt(b['spreadCents'])} depth={fmt(b['yesDepthContracts'])}/"
            f"{fmt(b['noDepthContracts'])}")
    else:
        rec("orderbook", FAIL, "no book returned")


async def check_candles(ticker: str, long_dated: str = "") -> None:
    probes = [(ticker, 1, 240, "1m/4h")]
    if long_dated:
        probes.append((long_dated, 60, 60 * 24 * 14, "1h/14d"))
        probes.append((long_dated, 1440, 60 * 24 * 90, "1d/90d"))
    for tk, interval, lookback, label in probes:
        try:
            s = await terminal.candles(tk, interval_min=interval, lookback_min=lookback)
        except Exception as e:
            rec(f"candles {label}", FAIL, f"{type(e).__name__}: {e}")
            continue
        n = len(s["candles"])
        traded = [c for c in s["candles"] if c["close"] is not None]
        rec(f"candles {label}", PASS if n else FAIL,
            f"{tk}: {n} periods, {len(traded)} with trades, "
            f"{s['emptyPeriods']} empty")
        if s["note"]:
            print(f"        note: {s['note']}")
        ts = [c["ts"] for c in s["candles"]]
        rec(f"candles {label} ordering",
            PASS if ts == sorted(set(ts)) and len(ts) == len(set(ts)) else FAIL,
            "strictly ascending, no duplicate stamps")
        if traded:
            with_vol = [c for c in traded if c["volume"] is not None]
            rec(f"candles {label} volume",
                PASS if with_vol else FAIL,
                f"{len(with_vol)}/{len(traded)} traded periods carry a volume"
                + ("" if with_vol else " — the _fp field names have moved again"))


async def check_tape(ticker: str) -> None:
    try:
        t = await terminal.tape(ticker, limit=10)
    except Exception as e:
        rec("tape", FAIL, f"{type(e).__name__}: {e}")
        return
    rec("tape", PASS, f"{len(t['trades'])} prints via {t['source']}")
    for x in t["trades"][:3]:
        print(f"        {fmt(x['createdAt'])} {fmt(x['takerSide']):4} "
              f"{fmt(x['contracts']):>5} @ yes={fmt(x['yesPrice'])} "
              f"seen={fmt(x['observedAt'])}")


async def check_signed() -> None:
    try:
        import kalshi_auth
        ok = kalshi_auth.has_credentials() if hasattr(kalshi_auth, "has_credentials") else False
    except Exception:
        ok = False
    if not ok:
        rec("portfolio (signed)", SKIP, "no saved credentials for the active env")
        rec("orders (signed)", SKIP, "no saved credentials for the active env")
        return
    try:
        pf = await terminal.portfolio(True)
        rec("portfolio (signed)", PASS,
            f"{len(pf['positions'])} positions, {pf['unreconciledCount']} "
            f"unreconciled, cash={fmt(pf['cashUsd'])}")
    except Exception as e:
        rec("portfolio (signed)", FAIL, f"{type(e).__name__}: {e}")
    try:
        o = await terminal.resting_orders(True)
        rec("orders (signed)", PASS, f"{len(o['orders'])} resting")
    except Exception as e:
        rec("orders (signed)", FAIL, f"{type(e).__name__}: {e}")


async def main() -> int:
    print("\nKrypt Terminal — live provider check")
    print(f"public base: {kalshi_api.PUBLIC_BASE}\n")

    rows = await check_sweep()
    await check_columns()
    await check_cache()

    ticker = sys.argv[1] if len(sys.argv) > 1 else (rows[0]["ticker"] if rows else "")
    if not ticker:
        print("\nNo ticker to probe; stopping.")
        return 1
    long_dated = ""
    try:
        vol = await terminal.discover("volume", limit=40)
        far = [r for r in vol["rows"] if (r.get("minutesToClose") or 0) > 60 * 24 * 20]
        long_dated = far[0]["ticker"] if far else ""
    except Exception:
        pass

    suffix = f" (long-dated: {long_dated})" if long_dated else ""
    print(f"\nprobing market: {ticker}{suffix}\n")
    await check_market(ticker)
    await check_candles(ticker, long_dated)
    await check_tape(ticker)
    await check_signed()

    await kalshi_api.close_clients()
    fails = [r for r in _results if r[1] == FAIL]
    print(f"\n{len(_results) - len(fails)} ok, {len(fails)} failed, "
          f"{sum(1 for r in _results if r[1] == SKIP)} skipped")
    for name, _v, detail in fails:
        print(f"  FAILED  {name}: {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
