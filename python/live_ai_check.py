"""LIVE check of the AI analysis path. Run by hand. SPENDS YOUR MONEY.

The unit suite (`tests/test_ai_analyst.py`) covers everything that can be
checked offline: what we hand the model, and what we accept back. It cannot
cover the half that only exists on the wire -- whether the model id is real,
whether the web-search tool type is accepted for it, what an SDK exception is
actually called when a key is wrong, and whether a real model returns the JSON
the panel expects. That is what this does.

It is deliberately not part of pytest. It hits the provider, and each run is a
billed request against the key in YOUR credential store.

    python/.venv/Scripts/python.exe python/live_ai_check.py [TICKER] [--search]

With no ticker it uses whatever Kalshi is currently trending, so the market is
real, open, and has an event with siblings -- the shape the prompt is built for.
--search adds the web-search tool regardless of the saved setting, because that
is the request shape most likely to be rejected and least likely to be
exercised by accident.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if not os.environ.get("KRYPT_TRADER_USERDATA"):
    print("Set KRYPT_TRADER_USERDATA to your real user-data dir -- this check")
    print("reads the API key out of that dir's credential store.")
    print(r'  Windows: %APPDATA%\Krypt Trader')
    sys.exit(2)

import ai_analyst
import config
import terminal

WANT_SEARCH = "--search" in sys.argv[1:]
TICKER = next((a for a in sys.argv[1:] if not a.startswith("-")), None)


def rule(title):
    print(f"\n=== {title} " + "=" * max(0, 60 - len(title)))


async def main() -> int:
    cfg = config.merge_with_defaults({})
    provider = cfg["ai_provider"]
    if WANT_SEARCH:
        cfg["ai_web_search"] = True

    rule("setup")
    st = ai_analyst.status(cfg)
    print(f"provider   : {st['provider']}")
    print(f"model      : {st['model']}")
    print(f"web search : {cfg['ai_web_search']}")
    print(f"keys       : {st['keys']}")
    if not st["hasKey"]:
        print(f"\nNo {provider} key saved. Add one in Settings first.")
        return 2

    ticker = TICKER
    if not ticker:
        rule("picking a live market")
        found = await terminal.discover("trending", limit=5)
        rows = (found or {}).get("rows") or []
        if not rows:
            print("Kalshi returned nothing trending; pass a ticker explicitly.")
            return 1
        ticker = rows[0]["ticker"]
        print(f"using {ticker} -- {rows[0].get('title')}")

    rule("fetching the market detail")
    detail = await terminal.market_detail(ticker, authed=False)
    market = detail.get("market") or {}
    print(f"{market.get('ticker')}  yes bid={market.get('yesBid')} ask={market.get('yesAsk')}")
    print(f"siblings   : {len((detail.get('event') or {}).get('siblings') or [])}")
    print(f"panel errors: {detail.get('errors')}")

    rule("the prompt the model will see")
    prompt = ai_analyst.render_market(detail)
    print(prompt)
    for bad in (" 0c", "=0c", "bid 0", "ask 0"):
        if bad in prompt:
            print(f"\n!! FAIL: a zero-priced field reached the prompt ({bad!r}).")
            print("!! Kalshi reports absent quotes as zeros; they must render as --.")
            return 1
    print("\nok: no zero-priced field in the prompt")

    rule("calling the provider (this costs money)")
    try:
        out = await asyncio.to_thread(ai_analyst.analyze, detail, cfg)
    except ai_analyst.AiError as e:
        print(f"!! AiError: {e}")
        print("!! That message is what the panel shows. Is it actionable?")
        return 1

    rule("result")
    print(json.dumps(out, indent=2)[:4000])

    rule("verdict")
    fails = []
    if out.get("raw"):
        fails.append("model did not return parseable JSON (panel falls back to raw text)")
    if not out.get("summary") and not out.get("raw"):
        fails.append("empty summary")
    fv = out.get("fairValueCents")
    if fv is not None and not (1 <= fv <= 99):
        fails.append(f"fair value {fv} escaped the 1..99 clamp")
    if fv is None and out.get("verdict") != "unclear":
        fails.append("verdict without a fair value behind it")
    if cfg["ai_web_search"] and not out.get("citations"):
        print("note: web search was on but the model cited nothing.")
    if out.get("costUsd") is None and out["provider"] == "anthropic":
        fails.append("no cost estimate for a model we publish prices for")

    for f in fails:
        print(f"  FAIL: {f}")
    if not fails:
        print(f"  PASS -- {out['provider']}/{out['model']} in {out['elapsedSec']}s, "
              f"{out['inputTokens']} in / {out['outputTokens']} out, "
              f"cost {out['costUsd']}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
