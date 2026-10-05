# Backend tests

Fast, hermetic unit tests for the Krypt Trader Python backend.

## Run

```bash
npm run py:test              # from the repo root (sets up the venv if needed)
npm run py:test -- -k whale  # forward args to pytest
```

…or directly against the venv:

```bash
cd python
.venv/Scripts/python.exe -m pytest      # Windows
.venv/bin/python -m pytest              # macOS/Linux
```

`conftest.py` (in `python/`) puts the backend modules on `sys.path` and
points `KRYPT_TRADER_USERDATA` at a throwaway temp dir, so the suite
never touches your real `<userData>` DB, logs, or credentials.

## What's covered

Pure decision logic — the functions whose past regressions are
documented in `trader.py`'s docstring/comments:

- **`test_scoring.py`** — `compute_whale_score`, `compute_momentum_confidence`
  (golden values, ceiling/floor clamps).
- **`test_trader_logic.py`** — position sizing, signal-cost/edge interpretation,
  the `should_trade` gate matrix, limit-cross pricing, Kalshi order/position
  parsing, the order→DB status machine, and binary settlement payout.
- **`test_serialize.py`** — `_iso_utc` (the SQLite-naive-UTC → ISO 8601 fix).

DB-backed integration (real temp SQLite via the `fresh_db` fixture, all
Kalshi calls stubbed on the `trader` module, engine driven with
`asyncio.run`):

- **`test_engine_integration.py`** —
  - `execute_signal` entry gates: max-open, daily cap, one-per-event,
    duplicate market/side, and the exposure-headroom sizing cut-off;
    plus the dry-run / live-order / API-error placement paths.
  - `poll_open_orders`: fill detection from the order endpoint, the
    "don't retire on a single bad poll" failure threshold (→ `gone`
    only after 6), and stale-resting-order auto-cancel.
  - `mark_resolved_positions`: winning YES, losing NO, no-fill close-at-$0,
    and the physical-bounds P&L clamp.

## Not yet covered (good next steps)

- `scan_for_trades` orchestration (candidate ranking + per-cycle balance
  re-check) and `reconcile_positions_with_kalshi` (rescue / resurrect /
  import-unknowns paths).
- async API-layer retry/429/backoff in `kalshi_api.py`.
- `kalshi_auth` RSA-PSS request signing + the per-env credential isolation.
