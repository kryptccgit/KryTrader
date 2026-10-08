# Disclaimer & Risk Notice

**Read this before using Krypt Trader with real money.**

Krypt Trader is free, open-source, experimental software for placing trades on
[Kalshi](https://kalshi.com). By downloading, building, or running it, you
acknowledge and accept everything below.

## Not financial advice
Krypt Trader, its strategies, signals, scores, and any documentation are for
informational and educational purposes only. Nothing here is financial,
investment, legal, or tax advice. The authors are **not** registered investment
advisors, commodity trading advisors, broker-dealers, or fiduciaries of any
kind, and nothing in this project creates such a relationship.

## Risk of loss
Trading event contracts involves substantial risk. **You can lose some or all
of the money in your account.** Automated trading can lose money quickly and at
scale, including while you are away from your computer. Only trade with money
you can afford to lose entirely.

## The strategies are unproven
The bundled strategies (whale tracker, momentum scanner, 15-minute crypto, etc.)
are **heuristics**. They:

- have **not** been validated with out-of-sample backtesting;
- do **not** currently account for Kalshi trading fees in their entry/sizing
  decisions, which can erode or eliminate any apparent edge;
- carry **no guarantee of profitability**.

Any performance figures, "edge" scores, or calibration claims are illustrative
and are **not** a promise of future results. Past or simulated performance does
not indicate future performance.

## No warranty
The software is provided "AS IS", without warranty of any kind, as stated in the
[LICENSE](./LICENSE). It may contain bugs that cause incorrect orders, missed
orders, or inaccurate P&L. The authors are not liable for any losses, damages,
or claims arising from its use.

## Your responsibilities
You are solely responsible for:

- Complying with [Kalshi's Terms of Service](https://kalshi.com/terms) and API
  terms, including any rules on automated/algorithmic trading. **Confirm that
  automated trading with your account is permitted before enabling it.**
- Complying with all laws and regulations in your jurisdiction, including
  eligibility, age, and licensing requirements.
- The security of your own Kalshi API keys and the machine you run this on.
- Every order the software places on your behalf.

## Start on paper, keep the live switches off
Krypt Trader ships in **Paper** mode — Kalshi's real prices with imaginary
money — with **auto-trading off** (and every per-feature live switch off).
Keep it that way until you fully understand the software and the risks.
Paper results are a rehearsal, not a promise: paper fills do not move the
market and do not model queue position. Going live requires adding a Kalshi
key, deliberately switching the app to **Live**, **and** arming the trader.

## No telemetry
Krypt Trader has no backend and sends **nothing** about you or your trading to
its authors. There is no analytics SDK, no crash reporting, no usage reporting
and no per-install identifier. The only servers this app talks to are the ones
you need it to: Kalshi, and anything you configure yourself (your own webhook,
your own Discord or Telegram bot). The Privacy screen inside the app lists
every outbound host, what it is for, and how to switch it off.

One thing is public by design: **Discord Rich Presence**. While the Discord
desktop app is running, Krypt Trader sets your Discord status to "Auto-trading
on Kalshi" with a link back to krypt.cc. This is how the app gets found, and it
is always on. It travels over a local pipe to your own Discord client rather
than to any Krypt server, and it carries no account information whatsoever — no
balance, no positions, no profit or loss, no tickers, not even whether trading
is currently running. Quitting Discord, or turning off activity sharing in
Discord's own settings, stops it.

## Affiliate disclosure
Links to Kalshi in this app and its documentation are **referral links**. If you
sign up through one, Kalshi may credit both you and the link's owner — either
the authors, or a community member whose donated referral link was randomly
selected when this install first launched. This is a material connection; using
a referral link is optional and costs you nothing extra.

## No affiliation
Krypt Trader is an independent project and is **not affiliated with, endorsed by,
or sponsored by** Kalshi, Discord, or any data provider. Your use of those
services is governed by their own terms, and you are responsible for complying
with them.

## Limitation of liability
To the maximum extent permitted by law, the authors and contributors shall not
be liable for any direct, indirect, incidental, special, consequential, or
exemplary damages — including, without limitation, trading losses, lost profits,
missed or erroneous orders, data loss, or account actions taken by Kalshi —
arising out of or relating to your use of (or inability to use) this software,
even if advised of the possibility of such damages. Your sole remedy is to stop
using the software.

If you do not agree with any of the above, do not use this software.

## Perpetual Futures (Kalshi "margin")

The Perpetuals features (data recorder, volume farmer, strategy builder,
backtester, paper mode, and live mode) interact with LEVERAGED derivatives.
In addition to everything above:

- **You can lose more than your posted margin.** Leveraged positions are
  liquidated automatically by the exchange when the market moves against you.
  At 5x leverage, roughly a 2% adverse move can wipe a position.
- **Fees are charged on notional, not margin.** A "small" position pays fees
  on its full size every fill. Funding payments accrue every 8 hours while a
  position is held.
- **Backtests and paper trading are simulations.** They use honest fill rules
  but cannot capture live slippage, partial fills, outages, liquidation
  engine behavior, or your own latency. A profitable backtest is more often
  an overfit artifact than a discovery — our own published audit of this
  venue (bundled under `python/data/research/`) backtested eleven strategy
  families and found zero profitable configurations.
- **The strategy builder executes YOUR rules.** The authors provide the tool,
  not the strategy; nothing in this software is investment advice, and no
  outcome is warranted. Use the daily loss caps, start in paper mode, and
  never fund the perps wallet with money you cannot afford to lose.

## User scripts (the Scripts tab)

The Scripts tab runs Python code **you** provide. In addition to everything
above:

- **Your code is your risk.** Scripts execute your rules; when the Scripts
  live switch is armed on production they place **real orders** with real
  money, including while you are away. The authors provide the runtime, not
  the strategy, and warrant no outcome.
- **"Trusted" mode disables the sandbox entirely.** A trusted script is
  arbitrary Python with **full access to your system**, running in the same
  process that holds your decrypted Kalshi API key. It can read files, reach
  the network, and exfiltrate your credentials. Only mark a script trusted if
  you wrote it or have read and understood **every line**.
- **Scripts shared by others are untrusted code.** Treat any script you did
  not write as potentially malicious until you have read it — especially
  before marking it trusted.
- **AI-generated scripts can be confidently wrong.** Code that reads well can
  still trade badly or misuse the API. Backtest it, paper it, and read it
  before letting it near money.
- **The sandbox and money rails are soft mitigations, not guarantees.** The
  sandbox restricts what a script can call but is not a security boundary —
  in particular it does **not** bound memory use, so a hostile script can
  exhaust your RAM. The per-script daily-loss stop, entry-price cap, and size
  caps limit losses; they do not eliminate them.
