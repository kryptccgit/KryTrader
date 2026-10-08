#!/usr/bin/env python3
"""Assemble a SELF-CONTAINED bundle of the live staleness runner to hand off.

live_staleness.py imports a handful of sibling modules (signing, WS, orders).
This copies the exact closure into ../staleness_dist/ alongside a requirements
file, the .env template, and a README — so a recipient only needs Python +
`pip install -r requirements.txt`. Re-run this whenever any bundled module
changes, then zip staleness_dist/ and send it.

    python bundle_staleness.py
"""
from __future__ import annotations

import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "staleness_dist"

MODULES = [
    "live_staleness.py",
    "kalshi_auth.py",
    "kalshi_api.py",
    "kalshi_ws.py",
    "spot_ws.py",
    "cf_ws.py",
]

REQUIREMENTS = """\
httpx>=0.28.0
websockets>=12.0
cryptography>=42.0.0
"""

README = """\
# Staleness-entry live runner (Kalshi 15m crypto)

Self-contained. You need Python 3.10+ and three packages — nothing else from
the original project.

## Setup
    pip install -r requirements.txt
    cp .env.staleness.example .env.staleness      # then edit it

Fill in `.env.staleness`:
  - KALSHI_KEY_ID           : your Kalshi API key id
  - KALSHI_PRIVATE_KEY_PATH : path to your Kalshi RSA private key .pem
  - leave ST_LIVE=0 for a dry run first (it places NO orders)

## Run
    python live_staleness.py                 # uses ./.env.staleness
    python live_staleness.py /path/to/other.env

Watch it in DRY-RUN — it logs `DRY-RUN would BUY ...` for every signal. When
you're happy, set `ST_LIVE=1` in the env file and run again (5s abort window).

## What it does
When spot moves fast (>= ST_MOVE_BPS over ST_LOOKBACK_SEC seconds) while the
Kalshi book hasn't repriced (mid moved <= ST_BOOK_STALE_C cents), it buys the
side spot moved toward as a marketable taker and HOLDS TO SETTLEMENT. No exit
management. The edge is speed — it keeps the signed HTTP connection pre-warmed
and reacts on a ~10ms loop.

## It does NOT need any other program running
It opens its OWN WebSocket connections (Kalshi book + Coinbase spot). It can run
alongside anything else on the same account. Its data/credentials live in an
isolated folder (ST_USERDATA, default ./.staleness_data).

## REAL MONEY — read this
- DRY-RUN by default; places orders only when ST_LIVE=1.
- Hard caps bound the loss: ST_MAX_CONCURRENT, ST_MAX_ENTRIES_DAY, and
  ST_MAX_DAILY_SPEND_USD (~= max daily loss, since a losing binary settles $0).
- There is NO auto-exit; open positions ride to settlement.
- The edge is validated on limited data. Start dry-run, then tiny size.

## Fastest setup
Run on a cloud box in the region nearest Kalshi's API — the network round-trip
to Kalshi is the main remaining latency, and location cuts it more than anything
in the code.
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    missing = [m for m in MODULES if not (HERE / m).exists()]
    if missing:
        raise SystemExit(f"missing modules: {missing}")
    for m in MODULES:
        shutil.copy2(HERE / m, OUT / m)
    shutil.copy2(HERE / ".env.staleness.example", OUT / ".env.staleness.example")
    (OUT / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")
    (OUT / "README.md").write_text(README, encoding="utf-8")
    print(f"bundled {len(MODULES)} modules + requirements + README + env template into:")
    print(f"  {OUT}")
    print("zip that folder and send it.")


if __name__ == "__main__":
    main()
