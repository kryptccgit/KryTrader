<div align="center">

<img src="resources/krypt.png" alt="Krypt Trader" width="108" />

# Krypt Trader

**A free, open-source Kalshi auto-trading desktop app.**

Whale tracker, momentum scanner, a manual trading terminal and a configurable trading engine in one clean app — your API keys never leave your machine.

[![License: MIT](https://img.shields.io/badge/License-MIT-6366F1)](LICENSE)
&nbsp;[![Windows 10 | 11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows&logoColor=white)](#download)
&nbsp;[![Status: beta](https://img.shields.io/badge/status-beta-F59E0B)](#download)
&nbsp;[![Price: free](https://img.shields.io/badge/Price-free-EC4899)](#download)
&nbsp;[![Discord](https://img.shields.io/badge/Discord-join-5865F2?logo=discord&logoColor=white)](https://discord.gg/muzFKR657F)
&nbsp;[![Website](https://img.shields.io/badge/web-krypt.cc-A855F7?logo=googlechrome&logoColor=white)](https://krypt.cc)

</div>

---

Krypt Trader watches the public Kalshi markets for whale orders and momentum, scores them with built-in heuristics, and can size and place trades for you — or hands you a terminal to trade any market yourself. All wrapped in a modern desktop UI instead of a script you have to babysit. Your API keys and every trade stay in a local SQLite database on your machine. It talks to Kalshi and public crypto-price feeds, and sends nothing about you or your trading back to its authors (see the [Disclaimer](DISCLAIMER.md)).

> [!WARNING]
> **This app places real orders on your Kalshi account — trading carries real financial risk.** The bundled strategies are heuristics with **no proven, fee-adjusted edge** and may lose money. This is **not financial advice**. It ships on Kalshi's **demo** environment with **auto-trading off** (and every live switch off), so nothing trades for real until you deliberately switch to Production and arm it. Please read the full [**Disclaimer**](DISCLAIMER.md).

## What it does

- **Whale tracker** — watches the live Kalshi trade feed for big taker orders and surfaces the highest-edge ones in real time.
- **Momentum scanner** — flags volume spikes, price moves and trade clusters, with a contrarian mode that fades the crowd.
- **15-minute crypto** — monitors Kalshi's 15-min BTC, ETH, SOL and other crypto markets with a configurable momentum strategy and an optional paper/live executor.
- **Auto-trader** — sizes positions by edge, places limit-cross orders, tracks fills and resolutions, and reconciles its book against Kalshi on every restart.
- **Strategy scripts** — write your own Python strategies and backtest them in-app. Sandboxed by default, with hard money rails (entry-price cap, size caps, per-script daily loss stop); an optional trusted mode runs full un-sandboxed Python. Your code, your risk — and treat scripts shared by others as untrusted code until you've read them.
- **Trading terminal** — the manual half of the app: search or browse any Kalshi market (trending, closing soon, newest, most traded, or your watchlist), then work it from a full market page — live order book, trade tape, probability chart, your position, and a trade ticket. Every figure says where it came from, and a number nobody could produce renders as an em dash rather than a `0` you might trade on.
- **Standing rules** — attach a stop loss, take profit or price alert to a position. Thresholds are in probability points, because on a market that already *is* a probability, "get me out below 30¢" is the sentence you actually mean. Stops watch the best **bid** you could really sell into, not the mid.
- **Cross-venue prices** — see the same question priced on Polymarket next to Kalshi. Read-only, and the matcher is built to refuse rather than guess — it would sooner show you nothing than pair "Barack Obama" with "Michelle Obama", which is exactly what a plain word-overlap matcher did. A gap between the two is never called an arbitrage — the venues can genuinely settle differently.
- **Remote control** — check on the bot, or trade, from your phone over a Discord or Telegram bot you own. Bound to one paired account, DMs only; reading and trading are separate switches and trading is off by default; every order is quoted first and needs a confirmation code before anything fires.
- **Profiles & Discord** — save, import and export tuned configs, with optional Discord webhooks and Rich Presence.
- **Local-first** — keys and trade history live under `%APPDATA%/Krypt Trader/`. No account required; your keys and trades stay local. **No telemetry** — no analytics, no crash reporting, no per-install identifier; the in-app Privacy screen lists every outbound host and how to switch it off. See the [Disclaimer](DISCLAIMER.md).

## Safe by default

- Starts on **demo with auto-trading off** — you have to switch to Production *and* arm the trader before a single real order goes out. (The 15-minute crypto tab and the Scripts tab each have their own separate live switch, also off by default.)
- A **daily stop-loss / take-profit, trading-hours windows and a master kill-switch** gate the engine.
- **Credentials are encrypted at rest** on Windows (DPAPI), tied to your user account — never sent anywhere.
- A **fee-aware backtest** (`npm run py:backtest`) measures the net-of-fee edge on *your own* resolved signals — run it before trusting any preset.
- **Remote trading is its own switch**, off by default and separate from remote *reading* — turning on alerts never turns on spending. No single message can place an order.
- **Missing data is shown as missing.** Kalshi returns `0` for an empty book side and for a market that has never traded; the app never renders those as prices.
- **Logs are scrubbed** of API keys, RSA private keys and bot tokens before they hit disk — so pasting a log into a support chat doesn't leak your account.

## Download

<a href="../../releases/latest"><img src="https://img.shields.io/badge/Download%20for%20Windows-Krypt%20Trader-A855F7?style=for-the-badge&logo=windows&logoColor=white" alt="Download Krypt Trader" /></a>

Grab the latest installer from the [**Releases**](../../releases/latest) page, run it, then open **API Keys** and connect your Kalshi key + RSA private key. It starts on demo with auto-trading off, so nothing trades until you switch to Production and arm it. Releases also carry **unsigned Linux (AppImage/deb) and macOS (dmg, Intel + Apple Silicon)** builds — they get less testing than the Windows one.

> Builds aren't code-signed yet, so the first launch may show a SmartScreen prompt — click **More info → Run anyway**. The full source is right here if you'd rather build it yourself.

### Opening it on macOS

The mac builds are ad-hoc signed, not notarized — Apple charges $99/yr for the
certificate that would make this step unnecessary. So the first launch needs
one manual approval:

1. Open the `.dmg`, drag **Krypt Trader** to Applications.
2. Launch it once. macOS refuses and offers **Done** / **Move to Trash** — pick
   Done.
3. **System Settings → Privacy & Security**, scroll to Security: *"Krypt Trader
   was blocked"* → **Open Anyway**, then confirm.

That is the whole procedure on macOS 15 and later. Control-click → Open no
longer bypasses Gatekeeper there, and `xattr -dr com.apple.quarantine` is not
needed — if you were told to run it against an older build, that build had a
different problem (a signature broken by packaging, which reported itself as
*"is damaged and can't be opened"*; fixed in v6.0.0).

## Build from source

```bash
git clone https://github.com/scripflipped/krypt-trader.git
cd krypt-trader
npm install
npm run dev      # auto-creates python/.venv on first run (~30s)
npm run dist     # build the installer for your OS into /release
```

Requires [Node.js](https://nodejs.org) 18+ and [Python](https://python.org) 3.10+ on PATH. Development runs on macOS/Linux/Windows. `npm run dist` builds the installer for the OS you're on; CI builds Windows, Linux (AppImage/deb) and macOS (dmg, both architectures) installers and attaches them to each GitHub Release — the Linux/macOS ones are unsigned and less tested than Windows.

## Need a Kalshi account?

Sign up through our referral and Kalshi gives you **$25 free** after your first deposit (the referral credit goes to the authors or to a community member who donated their link — it costs you nothing extra):
<https://kalshi.com/sign-up/?referral=b1483a75-2984-48c0-87d4-42a1d4714e78>

## Links

- **Website** — [krypt.cc](https://krypt.cc) · more free tools at [krypt.cc/tools](https://krypt.cc/tools)
- **Support and community** — [Discord](https://discord.gg/muzFKR657F)
- **Contributing** — see [CONTRIBUTING.md](CONTRIBUTING.md)

## License

Released under the [MIT License](LICENSE) — free to use, fork and share. Please don't rebrand and resell it. Provided **as-is, with no warranty**; see the [Disclaimer](DISCLAIMER.md).

<div align="center"><sub>Built by the Krypt team · <a href="https://krypt.cc">krypt.cc</a></sub></div>
