"""LIVE cross-venue check. Run by hand.

Unit tests pin the matcher against gold cases I chose; this runs it over both
live universes, where the pairs I did not think of live. It prints every
confident pair so they can be eyeballed, because the failure mode that matters
is not a crash — it is a confident, plausible, WRONG pairing that renders as an
inviting price difference between two different questions.

    python/.venv/Scripts/python.exe python/live_crossvenue_check.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import crossvenue as cv
import kalshi_api
import polymarket_public as pm
import terminal


async def main() -> int:
    print("\nCross-venue live check\n")

    try:
        poly = await pm.sweep()
    except Exception as e:
        print(f"  FAIL polymarket sweep: {e}")
        if pm.geoblocked():
            print("  (region-blocked from here — the panel degrades to a notice)")
        return 1
    pmarkets = [m for m in poly["markets"] if m["yesBid"] is not None]
    print(f"  polymarket: {len(poly['markets'])} markets, "
          f"{len(pmarkets)} quoted, truncated={poly['truncated']}")

    k = await terminal.discover("volume", limit=200)
    krows = k["rows"]
    print(f"  kalshi:     {len(krows)} markets\n")

    confident = 0
    candidates = 0
    print("=== confident pairs (READ THESE — a wrong one is the whole risk) ===")
    for kr in krows:
        matches = cv.find_matches(kr, pmarkets, limit=1)
        if not matches:
            continue
        m = matches[0]
        if m["confident"]:
            confident += 1
            c = cv.compare(kr, m["market"])
            k_label = f"{kr['title']} {kr.get('yesSubTitle') or ''}".strip()
            print(f"  {m['confidence']:.2f}  K: {k_label[:62]}")
            print(f"        P: {m['market']['question'][:62]}")
            print(f"        kalshi {c['kalshiMid']}c vs poly {c['polyMid']}c "
                  f"| diff {c['differenceCents']}c | cheaper: {c['cheaperToBuyYes']}")
            print(f"        why: {'; '.join(m['reasons'])}")
        else:
            candidates += 1

    print(f"\n  {confident} confident, {candidates} unconfirmed candidates, "
          f"{len(krows) - confident - candidates} with nothing close")

    print("\n=== automated sanity: confident pairs with clashing proper nouns ===")
    bad = 0
    for kr in krows:
        matches = cv.find_matches(kr, pmarkets, limit=1)
        if not matches or not matches[0]["confident"]:
            continue
        k_text = f"{kr['title']} {kr.get('yesSubTitle') or ''}"
        p_text = matches[0]["market"]["question"]
        kp, pp = cv.proper_nouns(k_text), cv.proper_nouns(p_text)
        if kp and pp and not (kp & pp):
            bad += 1
            print(f"  SUSPECT no shared name: {k_text[:52]!r} <-> {p_text[:52]!r}")
    print(f"  {bad} suspect pair(s)")

    await kalshi_api.close_clients()
    await pm.close_clients()
    print(f"\n{'FAILED' if bad else 'OK'} — {bad} suspect pairing(s)")
    return 1 if bad else 0


raise SystemExit(asyncio.run(main()))
