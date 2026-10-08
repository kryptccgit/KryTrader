# Contributing to Krypt Trader

Thanks for your interest! This is a real-money trading app, so correctness and safety matter — please
keep changes small, tested, and easy to review.

## Development setup

**Prerequisites:** Node.js 18+ and Python 3.11+ on PATH (CI and the release builds freeze the
backend with 3.11, and `websockets` 17 needs at least 3.11).

```bash
npm install
npm run dev          # vite + electron + python backend; `predev` sets up python/.venv
```

## Before you open a PR

```bash
npm run test:all     # typecheck + vitest + pytest — all three must pass
```

That is the same as running the three individually:

```bash
npm run typecheck    # TypeScript must pass (renderer + electron)
npm test             # vitest — renderer hooks and Electron-side helpers
npm run py:test      # Python tests must pass
```

All three are enforced by CI on every pull request.

`python/live_*_check.py` are **manual** harnesses that hit the real Kalshi,
Polymarket, Discord and Telegram APIs. They are deliberately not part of
`pytest` — run them by hand when you touch those paths, and say so in the PR.

## Guidelines

- **Match the surrounding code.** Naming, comment density, and idioms should look native to the file.
- **Add tests for logic changes** — especially anything touching the trading engine, sizing, P&L, or
  reconciliation. The Python tests live in `python/tests/`.
- **Never commit secrets or local state.** No API keys, RSA keys, `.env` files, local databases, or
  logs. The `.gitignore` is set up to prevent this — don't override it.
- **Be careful with money paths.** Changes to order placement, settlement, or reconciliation should be
  conservative and well-tested. When in doubt, gate new behavior behind a config flag that defaults off.
- **Keep PRs focused.** One logical change per PR, with a clear description of what and why.

## Architecture quick reference

Three processes, and data only flows one way. The renderer has no network, no
filesystem and no secrets; it names an *entity* and the backend decides which
host to contact. That is the structural fix for SSRF — a URL validator in the
middle would be the fragile one.

- `electron/` — main process, preload (`window.krypt` API surface), IPC, system
  integration. Renderer input is scrubbed in `electron/system/sanitize.ts`,
  kept out of `ipc.ts` **because** `ipc.ts` imports `electron` and so cannot be
  loaded by a test.
- `python/` — backend: `service.py` (the RPC loop; handlers live in
  `_HANDLERS`), `scanner.py`, `trader.py`, `crypto15m*.py`, `db.py` for the
  bot; `terminal.py` for manual trading, `crossvenue.py` +
  `polymarket_public.py` for cross-venue pricing, `remote*.py` for the chat
  bots, `logscrub.py` for credential redaction. Renderer ↔ backend talk
  JSON-RPC over stdio.
- `src/` — React UI.
- **Two contracts, deliberately separate.** `shared/types.ts` is the *engine*
  (bot positions, signals, config); `shared/market.ts` is the *terminal* (any
  market the user names). Don't merge them — a `BotPosition` only exists for a
  market the bot traded, and folding the terminal into it would produce a shape
  that is half-populated most of the time.

**The one rule that outranks style:** a value nobody could produce is `null` /
`None`, and renders as an em dash. Never coerce it to `0` or a default. Kalshi
REST is full of zeros meaning "absent" — `yes_bid: 0` is an empty book side
(quotes live in 1..99) and `last_price: 0` means the market has never traded.
Each one, coerced, is a specific lie someone would trade on.

## Reporting bugs / security issues

Open a GitHub issue for bugs. For **security** issues, follow [SECURITY.md](./SECURITY.md) instead of
filing a public issue.
