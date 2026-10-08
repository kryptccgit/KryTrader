<div align="center">

<img src="resources/krypt.png" alt="Krypt Trader" width="108" />

# Krypt Trader

**Put your own AI agent on Kalshi, and find out whether it actually beats the market.**

Connect the AI you already use: Claude, OpenAI models, Gemini, or a local model. Let it research Kalshi markets, record forecasts and trade on paper. A scoreboard tells you whether those forecasts beat the market price. You go live only when you choose to, and only inside hard rails.

[![License: MIT](https://img.shields.io/badge/License-MIT-6366F1)](LICENSE)
&nbsp;[![Windows 10 | 11](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows&logoColor=white)](#download)
&nbsp;[![macOS | Linux](https://img.shields.io/badge/macOS%20%7C%20Linux-unsigned-6B7280)](#download)
&nbsp;[![Status: beta](https://img.shields.io/badge/status-beta-F59E0B)](#download)
&nbsp;[![Price: free](https://img.shields.io/badge/Price-free-EC4899)](#download)

<a href="../../releases/latest"><img src="https://img.shields.io/badge/Download-Krypt%20Trader-A855F7?style=for-the-badge&logo=github&logoColor=white" alt="Download Krypt Trader" /></a>
&nbsp;<a href="https://discord.gg/muzFKR657F"><img src="https://img.shields.io/badge/Join%20the-Discord-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Join the Discord" /></a>
&nbsp;<a href="https://krypt.cc/tools"><img src="https://img.shields.io/badge/More%20free%20tools-krypt.cc%2Ftools-EC4899?style=for-the-badge&logo=googlechrome&logoColor=white" alt="More free tools at krypt.cc/tools" /></a>

</div>

---

Krypt Trader is a free, open-source desktop app. It runs a small agent server on your own computer. Your AI client connects to it, reads real Kalshi markets, commits to a forecast, and trades against the real order book with imaginary money. Each forecast is scored against the market price at the moment it was made, once the market settles. Most AI "edges" on a liquid market turn out to be the model being wrong. The scoreboard is how you find out before a dollar is at risk.

> [!WARNING]
> **Nothing here has a proven edge. That includes your AI.** A language model that sounds confident about a market is still only giving its opinion, and on a liquid market the price is usually the better forecast. The app's bundled strategies are heuristics with no proven, fee-adjusted edge either. This is **not financial advice**. Live trading places **real orders with real money**, and you can lose it. The app ships in **Paper** mode (Kalshi's real prices, imaginary money) with every live switch off. Real money needs a Kalshi key **and** the Go live checklist. Please read the full [**Disclaimer**](DISCLAIMER.md).

## Get started in 5 minutes

1. **Install.** Download the installer for your OS from [Releases](../../releases/latest) (see [Download](#download)).
2. **Start on paper — no Kalshi account needed.** The app opens in **Paper** mode: Kalshi's real production markets, order books and outcomes, with an imaginary bankroll you choose (Settings → Account, with a Reset). Every engine works in Paper — the bot, 15-minute crypto, scripts, the Terminal ticket, phone orders, AI agents and Autopilot — and none of them can send a real order. Market data comes from Kalshi's public endpoints, unsigned.
3. **Connect an AI.** On **AI Agents**, pick one:
   - **Autopilot (in-app).** Bring an API key for Anthropic, OpenAI, OpenRouter or Gemini, or point it at a local Ollama or LM Studio (the model has to support tool calls). It runs the agent on a timer you set, within daily run, token and tool-call budgets. It is off until you switch it on.
   - **Your own MCP client:** Claude Code, Cursor, Claude Desktop or Codex. Click **Copy config** and paste it into the client. The token travels backend → clipboard and never appears on screen.
   - **The HTTP API** (`/api/v1`, with an OpenAPI spec), for scripts, n8n, LangChain or anything else that doesn't speak MCP. It is off until its own switch is on.

   Not sure where to start? First-run setup includes a short voiced video guide to AI agents (1:35), and anyone upgrading sees it once too. The **Connections** panel checks your Kalshi key, AI key and agent server when you click **Run checks**. It never checks on its own.
4. **Build your own traders (optional).** Make **named agents**, each with its own name, emoji, colour, a guide written for the model, its own rules and its own token. Point one client at "Value hunter" and another at "Closing-soon scalper", and the scoreboard, positions and spend are tracked per agent. An agent's rules can only make it stricter than your global settings: a higher minimum edge, smaller caps, or paper-only while the others trade live. Switch an agent off or delete it and its token stops working.
5. **Paper trade.** Agents start in **paper** mode: real order books, real outcomes, imaginary money. Ask it something like *"Use krypt-trader. Look through closing markets, read the rules, record honest forecasts, and only trade where your edge clears the minimum."*
6. **Check the scoreboard.** *Does the AI beat the market?* scores every forecast against the market price at the moment it was made (Brier score), per agent. It won't give a verdict before 30 settled markets, and it calls a difference within two standard errors "no measurable difference".
7. **Go live, if you choose.** Add a Kalshi key from kalshi.com on **API Keys** (a step-by-step wizard checks it), then **Settings → Account → Go live**: the key verified on a click, every engine that would start spending named, and an explicit acknowledgement. Each engine's own live switch still applies on top — it can only narrow Live, never widen Paper. For agents, the **Go live** button on AI Agents adds their record, caps and approvals. **Paper** is always one click away.

## The rails

These are enforced in the backend, not just in the UI:

- **No buy without a forecast, no forecast without an edge.** A buy has to cite a forecast the agent recorded on that market in the last 30 minutes, and it has to beat the limit price by your minimum edge **after Kalshi's fee**.
- **Caps.** Per order, per day, and open positions. They stack on top of the terminal's own caps.
- **Approvals on by default.** Each live order waits for you, in the app or from your phone (`approve N`). It is re-checked against the market when you approve it and expires after 10 minutes. Turning approvals off takes its own confirmation.
- **Daily loss stop.** Realised plus open losses for the UTC day. Unrealised gains never offset them. Once it trips, it halts agent buys; exits are never blocked.
- **Agents only exit what they opened.** Your own positions are not theirs to sell or cancel, and named agents can't touch each other's either.
- **Every agent answers to the global settings.** Its rules can only narrow them, and your global caps still bind all agents together. Each agent has its own rate limit under a shared ceiling, so one looping agent can't crowd out the others.
- **Paper and Live are separate books.** Paper positions never count toward live caps or ownership, and the reverse. Agents cannot switch the account mode or refill the paper bankroll. Live trade mode is its own deliberate switch.
- **Loopback only, with a token.** The server binds `127.0.0.1`, needs a bearer token from the app's credential store, and refuses requests with a foreign Host or Origin.
- **Agents never reach** your keys, their own permissions or caps, the Paper/Live switch, or un-sandboxed scripts. Anything beyond single-market trading (research data, writing scripts, changing strategy settings) is a separate switch, and all of them start off.
- **Moving funds stays inside your account.** Kalshi keeps your cash split across its exchanges and doesn't rebalance it. A live agent can move cash between your own exchanges, never out of the account. Those moves share one daily cap with the app's automatic ones, and every move is audited.
- **Every attempt is logged,** refused ones included, on the AI Agents page.

## Also included

- **Trading terminal.** Search or browse any Kalshi market and work it from a full market page: order book, trade tape, probability chart, your position and a trade ticket. Every figure says where it came from. A number nobody could produce shows as a dash, not a `0` you might trade on. It also has standing stop-loss, take-profit and alert rules, and read-only Polymarket prices for the same question (a gap between the two is never called an arbitrage).
- **AI analysis.** Click **Analyse** on any market for a fair value and an argument, using your own key or a model on your own machine (Ollama, LM Studio). It runs only on a click. It has no trade button, and every fair value it gives is scored on the same scoreboard.
- **The bot and scanners.** A whale tracker, a momentum scanner and an auto-trader that sizes, places and reconciles orders. Plus a fee-aware backtest (`npm run py:backtest`) to run on your own resolved signals.
- **15-minute crypto.** Kalshi's 15-min BTC, ETH, SOL and other crypto markets, with a configurable strategy and a paper/live executor.
- **Strategy scripts.** Write your own Python strategies and backtest them in-app. They are sandboxed by default, with an entry-price cap, size caps and a per-script daily loss stop. The optional trusted mode runs un-sandboxed Python, so treat scripts shared by others as untrusted until you've read them.
- **Trading across Kalshi's exchanges.** In Live, before a buy is sent, the app moves the collateral it needs onto the exchange that holds that market, from your other exchanges, within a daily cap you set. It never does this for a sell or in Paper. You can also move funds yourself.
- **Agent Hub.** A read-only 3D view of your agents at work, driven only by things that really happened. Your named agents appear as themselves, the Council seats each agent behind its own forecasts, and you can walk the Spaceship and the Council in first person and talk to the crew.
- **Remote control.** Check on the app, approve agent orders, or trade from your phone over a Discord or Telegram bot you own. It is bound to one paired account and DMs only. Trading is a separate switch, off by default, and every order needs a confirmation code.

## Privacy

**No telemetry:** no analytics, no crash reporting, no per-install identifier, and nothing about your balance, positions or P&L is sent to the authors. The app has no backend of its own. It talks to Kalshi, public price feeds, and whatever you configure. **AI calls go from your machine straight to the provider you choose**, whether that's Autopilot or Analyse with your key, or the MCP client you connect, which sends what it reads to its own provider. In live mode, what it reads includes your positions. The in-app **Privacy** page lists every outbound host and how to switch it off.

Keys and trade history stay on your machine, under `%APPDATA%/Krypt Trader/` on Windows. On Windows, credentials are encrypted at rest with DPAPI and tied to your user account. On macOS and Linux they are stored in files readable only by your user. Logs are scrubbed of API keys, private keys, bot tokens and the agent token before they reach disk.

The one deliberate exception is **Discord Rich Presence**. If the Discord desktop app is running, it shows "Auto-trading on Kalshi" over a local pipe, with no account data at all. Details are in the [Disclaimer](DISCLAIMER.md).

## Download

<a href="../../releases/latest"><img src="https://img.shields.io/badge/Download-Krypt%20Trader-A855F7?style=for-the-badge&logo=github&logoColor=white" alt="Download Krypt Trader" /></a>

Grab the latest build from the [**Releases**](../../releases/latest) page: a Windows installer, plus **unsigned Linux (AppImage/deb) and macOS (dmg, Intel and Apple Silicon)** builds. The Linux and macOS builds get less testing than the Windows one. Every build starts in Paper mode with every live switch off.

> Builds aren't code-signed yet, so the first launch on Windows may show a SmartScreen prompt. Click **More info → Run anyway**. The full source is right here if you'd rather build it yourself.

### Opening it on macOS

The mac builds are ad-hoc signed, not notarized, because Apple charges $99/yr for the
certificate that would make this step unnecessary. So the first launch needs
one manual approval:

1. Open the `.dmg` and drag **Krypt Trader** to Applications.
2. Launch it once. macOS refuses and offers **Done** / **Move to Trash**. Pick
   Done.
3. Go to **System Settings → Privacy & Security** and scroll to Security. Next to *"Krypt Trader
   was blocked"*, click **Open Anyway**, then confirm.

That is the whole procedure on macOS 15 and later. Control-click → Open no
longer bypasses Gatekeeper there, and `xattr -dr com.apple.quarantine` is not
needed. If you were told to run it against an older build, that build had a
different problem: packaging broke its signature, and macOS reported it as
*"is damaged and can't be opened"*. That was fixed in v6.4.0, the first v6 release.

## Build from source

```bash
git clone https://github.com/scripflipped/krypt-trader.git
cd krypt-trader
npm install
npm run dev      # auto-creates python/.venv on first run (~30s)
npm run dist     # build the installer for your OS into /release
```

Requires [Node.js](https://nodejs.org) 18+ and [Python](https://python.org) 3.11+ on PATH. Development runs on macOS, Linux and Windows. `npm run dist` builds the installer for the OS you're on. CI builds Windows, Linux (AppImage/deb) and macOS (dmg, both architectures) installers and attaches them to each GitHub Release.

## Need a Kalshi account?

Sign up through our referral and Kalshi gives you **$25 free** after your first deposit. The referral credit goes to the authors, or to a community member who donated their link, and it costs you nothing extra:
<https://kalshi.com/sign-up/?referral=b1483a75-2984-48c0-87d4-42a1d4714e78>

## Links

- **Website**: [krypt.cc](https://krypt.cc) · more free tools at [krypt.cc/tools](https://krypt.cc/tools)
- **Support and community**: [Discord](https://discord.gg/muzFKR657F)
- **Contributing**: see [CONTRIBUTING.md](CONTRIBUTING.md)

## License

Released under the [MIT License](LICENSE): free to use, fork and share. Please don't rebrand and resell it. Provided **as-is, with no warranty**; see the [Disclaimer](DISCLAIMER.md).

<div align="center"><sub>Built by the Krypt team · <a href="https://krypt.cc">krypt.cc</a></sub></div>
