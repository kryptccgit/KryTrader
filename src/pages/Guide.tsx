import {
  Activity, AlertTriangle, BarChart3, BookOpen, Bot, Briefcase, CheckCircle2,
  ExternalLink, Eye, FlaskConical, Gift, KeyRound, Layers, PlayCircle, Sparkles, Target, Twitter, Zap,
} from 'lucide-react';
import { Card, Page, Section } from '../components/common';
import {
  GUIDE_VIDEO_URL, KALSHI_API_KEYS_URL, openKalshiReferral,
} from '../utils/links';
import { followYuhgo, X_PROFILE } from '../utils/share';

export function GuidePage() {
  const open = (url: string) => () => void window.krypt.app.openExternal(url);

  return (
    <Page
      title="Guide"
      subtitle="How Krypt Trader works, what each setting does, and the trading edge it tries to capture."
    >
      <Card className="mb-6 border-krypt-win/30 bg-gradient-to-br from-krypt-win/10 via-transparent to-transparent">
        <div className="flex flex-col items-start gap-4 md:flex-row md:items-center">
          <div className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-krypt-win/20">
            <PlayCircle className="h-7 w-7 text-krypt-win" />
          </div>
          <div className="flex-1">
            <div className="text-sm font-semibold text-white">Prefer watching? Full video walkthrough.</div>
            <p className="mt-1 text-xs text-krypt-muted">
              Setup, API keys, the 15m Settlement Sniper, Multi-Run, backtesting and safety
              switches — the whole app in one guided video.
            </p>
          </div>
          <button onClick={open(GUIDE_VIDEO_URL)} className="krypt-btn-primary shrink-0">
            <PlayCircle className="h-4 w-4" /> Watch the video guide <ExternalLink className="h-3 w-3" />
          </button>
        </div>
      </Card>

      <Card className="mb-6 border-krypt-purple/30 bg-gradient-to-br from-krypt-purple/15 via-krypt-glow/20 to-transparent">
        <div className="flex flex-col items-start gap-4 md:flex-row md:items-center">
          <div className="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-krypt-glow shadow-krypt-strong">
            <Gift className="h-6 w-6 text-white" />
          </div>
          <div className="flex-1">
            <div className="text-sm font-semibold text-white">
              New to Kalshi? Claim $25 free with our referral.
            </div>
            <p className="mt-1 text-xs text-krypt-muted">
              Sign up via the Krypt referral link and Kalshi credits your account
              with $25 after your first deposit. Costs you nothing — the referral
              credit goes to the authors or a community member who shared their link.
              Use it before connecting your API keys to maximize your starting
              bankroll.
            </p>
          </div>
          <div className="flex flex-col gap-2 shrink-0">
            <button onClick={() => void openKalshiReferral()} className="krypt-btn-primary">
              <Gift className="h-4 w-4" /> Claim $25 on Kalshi <ExternalLink className="h-3 w-3" />
            </button>
            <button
              onClick={() => void followYuhgo()}
              className="krypt-btn-default"
              title={`Open ${X_PROFILE} on X`}
            >
              <Twitter className="h-4 w-4" /> Follow {X_PROFILE} <ExternalLink className="h-3 w-3" />
            </button>
          </div>
        </div>
      </Card>

      <Section title="Paper vs Live — the one switch that matters">
        <Card>
          <div className="grid gap-4 md:grid-cols-2" data-testid="guide-paper-live">
            <div className="rounded-xl border border-krypt-purple/30 bg-krypt-purple/[0.05] p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-krypt-purple">
                <FlaskConical className="h-4 w-4" /> Paper (where everyone starts)
              </div>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-relaxed text-krypt-muted">
                <li>Real Kalshi markets and real prices — with <span className="text-white">imaginary money</span>.</li>
                <li>No Kalshi account or key needed. Nothing can send a real order.</li>
                <li>Every part of the app works: the bot, your AI agents, the Terminal, scripts.</li>
                <li>A purple <span className="text-white">PAPER</span> label next to the balance says you are here.</li>
              </ul>
            </div>
            <div className="rounded-xl border border-krypt-loss/30 bg-krypt-loss/[0.05] p-4">
              <div className="flex items-center gap-2 text-sm font-semibold text-krypt-loss">
                <AlertTriangle className="h-4 w-4" /> Live (real money)
              </div>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-relaxed text-krypt-muted">
                <li>Orders spend the money in <span className="text-white">your own Kalshi account</span>.</li>
                <li>Needs a Kalshi API key, then Settings → Account → Go live, which checks everything first.</li>
                <li>Each engine (the bot, agents, 15-minute crypto, scripts) still has its own on/off switch.</li>
                <li>A red <span className="text-white">LIVE</span> label says you are here. Back to Paper is one click.</li>
              </ul>
            </div>
          </div>
          <p className="mt-3 text-xs text-krypt-muted">
            Paper and Live keep separate records: a paper win never shows up in your Live totals, and
            pages like Positions and History let you pick which book you are looking at.
          </p>
        </Card>
      </Section>

      <Section title="AI agents, in plain words">
        <Card>
          <div className="space-y-3 text-sm leading-relaxed text-krypt-muted" data-testid="guide-ai-agents">
            <p>
              <Bot className="mr-1.5 inline h-4 w-4 text-krypt-purple" />
              An <span className="text-white">AI agent</span> is an AI (like Claude or ChatGPT) that can
              look at Kalshi markets for you, write down what it thinks will happen, and — if you let
              it — place trades. The app keeps it inside rules it cannot change.
            </p>
            <ol className="list-decimal space-y-2 pl-5 text-xs">
              <li>
                <span className="text-white">Connect one.</span> On the AI Agents page, the easiest
                choice is <span className="text-white">In-app Autopilot</span>: nothing to install, the
                app runs the agent itself with an AI key you add (or a free model on your computer). If
                you already use Claude Desktop, there is a one-click <span className="text-white">Add
                to Claude Desktop</span> button; Claude Code, Cursor and Codex work too.
              </li>
              <li>
                <span className="text-white">Paper first.</span> Agents start on paper — real prices,
                imaginary money — and must write down a forecast that beats the price (after Kalshi&apos;s
                fee) before every buy.
              </li>
              <li>
                <span className="text-white">Named agents.</span> Make several, each with its own
                personality, rules (which markets, what prices, how much) and record. A rule you set is
                enforced by the app on every order that agent places.
              </li>
              <li>
                <span className="text-white">The scoreboard.</span> Once markets settle, every forecast
                is scored against what the market itself said at that moment. If an agent doesn&apos;t
                beat the market there, it has no edge — whatever it sounds like.
              </li>
              <li>
                <span className="text-white">Go live — only if the record says so.</span> Real money
                needs the app in Live and agent trading set to Live. Live agent orders wait for your
                approval by default, and a daily loss limit stops new buys for the day.
              </li>
            </ol>
          </div>
        </Card>
      </Section>

      <Section title="Two halves: the Terminal and the bot">
        <Card>
          <div className="space-y-3 text-sm leading-relaxed text-krypt-muted">
            <p>
              The <span className="text-white">Terminal</span> (the Manual
              group in the sidebar) is for you: browse every Kalshi market,
              read its resolution risk, and place orders by hand. The{' '}
              <span className="text-white">Automation</span> group below it is
              the bot. They share one Kalshi account but not one record —
              hand-placed trades do not count toward the bot&apos;s win rate and
              cannot trip its daily stop-loss, so a bad afternoon of your own
              trading never silently halts the engine.
            </p>
            <p>
              One rule runs through every screen and is worth knowing before
              you trade on anything you see:{' '}
              <span className="text-white">a value nobody could produce shows
              as an em dash, never as zero.</span> Kalshi reports a
              <span className="font-mono"> yes_bid</span> of 0 when nobody is
              bidding and a last price of 0 for a market that has never traded.
              Rendered as &ldquo;0&cent;&rdquo; those are confident lies you
              would act on, so they are shown as &ldquo;—&rdquo; with an
              explanation on hover. A total that could not be computed is
              missing rather than wrong.
            </p>
          </div>
        </Card>

        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <FeatureCard
            icon={Eye}
            title="Resolution risk, not price risk"
            body="Every market page scores who settles it, against what named source, how discretionary the wording is, and how long your capital is locked after close. The score averages only the checks that actually resolved and refuses to print at all below four — an unread check is never counted as a pass."
          />
          <FeatureCard
            icon={Target}
            title="Stops in probability points"
            body="A stop loss says 'get me out below 30¢', not '-25%'. It watches the best BID on the side you hold — what you could actually sell into — because a mid is a price nobody has offered to buy at. If there is no bid it stays armed and says so rather than firing into a book that cannot fill it."
          />
          <FeatureCard
            icon={Layers}
            title="Cost basis from Kalshi's ledger"
            body="What a fill really cost includes the exchange fee and every partial fill at a worse price. My Book reads the basis back from Kalshi rather than from what the app asked to pay; a position it cannot price is marked unreconciled and excluded from the totals, never counted as break-even."
          />
        </div>
      </Section>

      <Section title="The Terminal, screen by screen">
        <Card>
          <div className="space-y-3 text-sm leading-relaxed text-krypt-muted">
            <p>
              <span className="text-white">Terminal</span> — Trending ranks by
              what is actually printing on Kalshi&apos;s public tape right now,
              not by a 24h counter that keeps yesterday&apos;s finished events
              at the top. Filters narrow ~20,000 markets; a market whose volume
              has not arrived is <em>skipped</em> and counted rather than
              treated as a zero, while one with no category is{' '}
              <em>excluded</em> by a category filter — &ldquo;unknown&rdquo; is
              not a member of a set you named.
            </p>
            <p>
              <span className="text-white">A market page</span> — a probability
              chart on a fixed 0–100 axis (it IS a probability), where a period
              with no trades draws a gap rather than a straight line through it.
              The <span className="text-white">Our feed</span> tab is built from
              our own websocket book: real spread over time, how long a quote
              survives, and how often a price would have been fillable. That one
              needs a verified API key, because Kalshi&apos;s websocket
              handshake is signed.
            </p>
            <p>
              <span className="text-white">Other venues</span> — the same
              question priced on Polymarket, when a confident match exists. Read
              only: this app never sends an order to Polymarket. A price
              difference there is a price difference, not free money — Kalshi
              settles under CFTC exchange rules against named sources,
              Polymarket through the UMA oracle, and two identically-worded
              markets can still resolve differently.
            </p>
            <p>
              <span className="text-white">My Book</span> — positions, resting
              orders, standing instructions, and your calibration: when you paid
              70&cent;, did it happen 70% of the time? These contracts settle to
              exactly 0 or 1, so that is arithmetic rather than a model. A price
              band with fewer than five settled trades shows its sample count
              instead of a hit rate.
            </p>
          </div>
        </Card>
      </Section>

      <Section title="Trading from your phone">
        <Card>
          <div className="space-y-3 text-sm leading-relaxed text-krypt-muted">
            <p>
              The <span className="text-white">Remote</span> page connects a
              Discord or Telegram bot you own, so you can leave this running and
              check it — or trade — from a phone. The bot answers exactly one
              identity: your Discord user id, or the Telegram chat that
              completed a pairing code. Group and server channels are ignored.
            </p>
            <p>
              Reading and trading are separate switches, and trading is off by
              default. When it is on, no order fires from a single message: the
              bot quotes it and waits for a confirmation code tied to that exact
              order, and every cap from the desktop ticket still applies.
            </p>
            <p className="text-krypt-warn">
              Anything you ask it for travels through Discord&apos;s or
              Telegram&apos;s servers in a form they can read. That is inherent
              to using a chat app as a terminal. The Privacy page names every
              host this app can contact, what each is for, and how many times it
              actually has.
            </p>
          </div>
        </Card>
      </Section>

      <Section title="At a glance">
        <div className="grid gap-4 md:grid-cols-3">
          <FeatureCard
            icon={Eye}
            title="Two scanners"
            body="Whale tracker watches large taker fills (smart-money-style flow). Momentum tracker hunts price/volume divergences across active markets."
          />
          <FeatureCard
            icon={Target}
            title="Edge-based sizing"
            body="Position size scales linearly with the gap between signal confidence and the market's implied probability. Bigger edge → bigger bet, capped by your hard limits."
          />
          <FeatureCard
            icon={Layers}
            title="Risk gates everywhere"
            body="Per-market dedupe, per-event dedupe, max open positions, max daily new positions, exposure ceiling, daily stop-loss, and minimum cash reserve."
          />
        </div>
      </Section>

      <Section title="Setup in 5 minutes">
        <Card>
          <ol className="space-y-4 text-sm">
            <Step
              n={1}
              title="Start on paper — no account needed"
              body={
                <>
                  The app opens in <span className="text-white">Paper</span> mode: Kalshi&apos;s real
                  markets and prices, imaginary money. Nothing to sign up for, no key to paste. Every
                  engine works in Paper — the bot, 15-minute crypto, scripts, the Terminal ticket,
                  phone orders and AI agents — and none of them can send a real order.
                </>
              }
            />
            <Step
              n={2}
              title="Make your own strategy"
              body={
                <>
                  Nothing ships pre-made — no built-in strategy has a proven
                  edge. Tune the gates, sizing and scanners in Settings and save
                  them on <Sparkles className="inline h-3.5 w-3.5" /> Strategies,
                  write one as code on Scripts, or let an AI agent with
                  &ldquo;Change strategy settings&rdquo; on tune them for you.
                </>
              }
            />
            <Step
              n={3}
              title="Run it on paper and judge it"
              body={
                <>
                  Turn auto-trading on and let it rack up a few hundred resolved paper trades, then
                  read the <span className="text-white">History</span> page. Paper fills walk the
                  real order book and pay Kalshi&apos;s fee, so a paper loss is a real warning. Reset
                  the paper account any time from Settings → Account.
                </>
              }
            />
            <Step
              n={4}
              title="Ready for real money: add a Kalshi key"
              body={
                <>
                  Sign up to Kalshi (the referral link above gives $25 after your first deposit),
                  then on{' '}
                  <button onClick={open(KALSHI_API_KEYS_URL)} className="text-krypt-purple hover:underline">
                    kalshi.com
                  </button>{' '}
                  go to <span className="text-white">Account → API Keys → New Key</span>. Paste the
                  key ID and private key on the <KeyRound className="inline h-3.5 w-3.5" /> API Keys
                  page (the step-by-step wizard checks both).
                </>
              }
            />
            <Step
              n={5}
              title="Go live"
              body={
                <>
                  Settings → Account → <span className="text-white">Go live</span> verifies the key,
                  lists every engine that will start spending real money, and asks you to confirm.
                  Each engine&apos;s own live switch still applies on top. Paper is one click away,
                  and the Pause button at the top right is your kill-switch.
                </>
              }
            />
          </ol>
        </Card>
      </Section>

      <Section title="Paper mode: real prices, imaginary money">
        <Card className="border-krypt-win/25 bg-krypt-win/[0.03]">
          <div className="mb-4 flex items-start gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-krypt-win/15 text-krypt-win">
              <FlaskConical className="h-5 w-5" />
            </div>
            <p className="text-sm text-krypt-muted">
              Paper trades Kalshi&apos;s <span className="text-white">real production markets</span>{' '}
              against a local book with a starting balance you choose. It reads Kalshi&apos;s public
              prices and order books — no Kalshi account, no key, nothing signed — and it is the
              master switch: while the app is in Paper, no engine can reach your real account.
            </p>
          </div>
          <ul className="list-disc space-y-1.5 pl-5 text-sm text-krypt-muted">
            <li>
              An order fills at once against the real order book, level by level, up to its limit,
              with Kalshi&apos;s fee. The rest rests and fills only if the real book later crosses
              your price — never on a print at it, since your place in the queue is unknowable.
            </li>
            <li>Positions settle on the real outcome. Your size never moves the paper book.</li>
            <li>
              Paper and Live keep separate books: paper positions never count toward Live caps,
              and the reverse. A <span className="text-white">PAPER</span> pill by the balance always
              says which one you are looking at.
            </li>
            <li>
              Not modelled: queue position, market impact, depth beyond the visible book. Read
              paper P&amp;L as a rehearsal of a strategy, not a promise of what Live will pay.
            </li>
          </ul>
        </Card>
      </Section>

      <Section title="How a trade flows">
        <Card>
          <FlowDiagram />
          <div className="mt-4 grid gap-3 text-xs text-krypt-muted md:grid-cols-3">
            <div>
              <div className="text-[11px] uppercase tracking-wider text-white">
                1. Scan
              </div>
              Whale tracker hits Kalshi every {`~`}2 min looking for taker fills above
              your dollar threshold. Momentum tracker scans markets every {`~`}90s for
              moves that match your signal types. Both write rows into the local DB.
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wider text-white">
                2. Filter &amp; size
              </div>
              Trader checks confidence, edge, allowed categories, dedup, exposure
              caps, and daily risk gates. If a candidate passes, sizing maps the
              edge in pts to a $ stake between your min and max fractions.
            </div>
            <div>
              <div className="text-[11px] uppercase tracking-wider text-white">
                3. Place &amp; track
              </div>
              Order goes in as a limit cross (or mid, depending on order style).
              Polled every 30s for fill status. On settlement, the resolver reads
              the market's binary outcome and writes the final P&amp;L.
            </div>
          </div>
        </Card>
      </Section>

      <Section title="Setting cheat sheet">
        <Card>
          <div className="grid gap-x-8 gap-y-3 md:grid-cols-2">
            <SettingRow
              label="Min confidence (Signal gates)"
              hint="The signal's quality score (0–100). Higher = pickier, fewer trades."
            />
            <SettingRow
              label="Min edge (Signal gates)"
              hint="How far the signal's confidence must be above the market price, in points. 5 = a small edge, 12+ = strong."
            />
            <SettingRow
              label="Min size / Max size (Position sizing)"
              hint="The share of your balance bet at the smallest and biggest edge; sizes in between scale. A hard dollar cap sits on top."
            />
            <SettingRow
              label="Max open positions (Concurrency & risk)"
              hint="The most unsettled bets at once. Protects against a burst of signals."
            />
            <SettingRow
              label="Max total exposure (Position sizing)"
              hint="Money at risk can't exceed this share of your balance. New bets shrink when it's full."
            />
            <SettingRow
              label="Daily stop-loss (Concurrency & risk)"
              hint="If today's settled losses reach this, the bot opens nothing new until tomorrow."
            />
            <SettingRow
              label="Daily take-profit"
              hint="Same idea the other way — stop for the day once you're up this much."
            />
            <SettingRow
              label="Order style (Order placement)"
              hint="Cross the spread to fill fast, sit at the middle to pay less (may not fill), or market."
            />
            <SettingRow
              label="Categories"
              hint="Which kinds of market the bot may trade (Sports, Politics, Crypto…). None picked = nothing."
            />
            <SettingRow
              label="Min cash reserve (Position sizing)"
              hint="Always keep at least this share of your balance in cash."
            />
          </div>
        </Card>
      </Section>

      <Section title="Reading the dashboard">
        <Card>
          <ul className="space-y-2 text-sm text-krypt-muted">
            <Row
              icon={BarChart3}
              label="Total Balance"
              body="Cash + portfolio (live mark-to-market). Updated from Kalshi every snapshot."
            />
            <Row
              icon={Target}
              label="ROI"
              body="(Total - bankroll baseline) / baseline. Baseline is your manual start_bankroll_usd, or auto-detected from your first snapshot."
            />
            <Row
              icon={CheckCircle2}
              label="Today P&L"
              body="Sum of realized P&L on positions resolved today (rolls over at midnight). Does not include unrealized swing on still-open bets."
            />
            <Row
              icon={Briefcase}
              label="Open Positions"
              body="Count of filled / partial bets that haven't settled yet. The cap is max_open_positions."
            />
            <Row
              icon={Activity}
              label="Recent resolutions"
              body="The latest settled bets with their P&L. Pair this with the Positions page's Won / Lost tabs to see the whole story."
            />
          </ul>
        </Card>
      </Section>

      <Section title="When P&amp;L looks weird">
        <Card>
          <div className="mb-3 flex items-start gap-3 rounded-lg border border-krypt-warn/30 bg-krypt-warn/5 p-3">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-krypt-warn" />
            <div className="text-xs text-krypt-muted">
              <span className="text-white">Today P&L can be negative while your balance climbs.</span>
              {' '}Realized P&L only counts <span className="text-white">settled</span> bets.
              If your open positions are appreciating, your total balance goes up
              even though "Today P&L" reflects only the bets that already
              resolved. That's normal — wait for settlement.
            </div>
          </div>
          <div className="text-sm text-krypt-muted">
            If something looks broken (wrong wins/losses, stuck positions, etc.):
          </div>
          <ul className="mt-2 space-y-1.5 text-sm text-krypt-muted">
            <li>
              <span className="text-white">Positions → Refresh</span> — checks every
              open and pending order again and re-syncs the list with your account.
            </li>
            <li>
              Check the <span className="text-white">Book</span> picker on Positions and
              History — Paper and Live are kept apart, so a missing trade is often in the
              other book.
            </li>
            <li>
              <span className="text-white">Restart</span> button (top bar) — restarts the
              trading engine (the background part of the app) if it&apos;s stuck.
            </li>
            <li>
              <span className="text-white">Logs → Copy diagnostics</span> — copies a
              report without any keys in it, to paste into a bug report.
            </li>
          </ul>
        </Card>
      </Section>

      <Section title="Strategy intuition">
        <Card>
          <div className="grid gap-4 md:grid-cols-3">
            <StratBlock
              icon={Zap}
              tone="loss"
              title="High Risk"
              body="Lower confidence floor (~60), wider edge tolerance, higher max size fraction. Lots of fills, lots of swings, biggest variance. Best for finding what works fast on paper."
            />
            <StratBlock
              icon={Activity}
              tone="purple"
              title="Balanced"
              body="Default. Confidence ~70, edge ≥ 5pts, sizing 1.5–6% of bankroll. Mix of whale and momentum signals. Reasonable variance, plenty of trades to evaluate."
            />
            <StratBlock
              icon={CheckCircle2}
              tone="win"
              title="Conservative"
              body="Confidence ≥ 78, edge ≥ 8pts, smaller sizing, tight per-event dedupe. Fewer trades but higher hit-rate. Best when you want to ride out long stretches."
            />
          </div>
          <div className="mt-4 text-xs text-krypt-dim">
            These are descriptions of three styles, not built-in presets — the app ships
            none, because none has a proven edge. Set the numbers yourself in Settings, save
            them as a Profile, and watch History for a few days on Paper before any real money.
          </div>
        </Card>
      </Section>

      <Section title="Write your own strategy (Scripts tab)">
        <Card>
          <p className="text-sm text-krypt-muted">
            The <span className="text-white">Scripts</span> tab runs Python strategy
            code you write (or AI-generate) against the 15-minute crypto markets.
            Scripts run <span className="text-white">sandboxed by default</span> — no
            filesystem, network, or imports — and every script, trusted or not, sits
            behind hard money rails: a max entry price, max contracts per order, max
            open positions per script, and a per-script daily loss stop that
            auto-disables it.
          </p>
          <ul className="mt-3 space-y-2 text-sm text-krypt-muted">
            <li>
              <FlaskConical className="mr-2 inline h-3.5 w-3.5" />
              <span className="text-white">Backtest first.</span> Replay any script over
              your recorded market data (taker fills at the recorded ask, fees included)
              before it touches money — then paper mode, then live.
            </li>
            <li>
              <AlertTriangle className="mr-2 inline h-3.5 w-3.5" />
              <span className="text-white">Trusted mode is dangerous.</span> It removes
              the sandbox entirely and runs full Python in the process holding your
              decrypted API key. Only trust code you wrote or have read line by line —
              scripts shared by others are untrusted code, and AI-generated code can be
              confidently wrong.
            </li>
            <li>
              <Zap className="mr-2 inline h-3.5 w-3.5" />
              <span className="text-white">Scripts have their own live switch.</span> The
              master &quot;Scripts live&quot; toggle arms them independently of the main
              Auto-trading switch. Your script&apos;s P&amp;L is your own — no script,
              yours or anyone&apos;s, comes with a proven edge.
            </li>
          </ul>
        </Card>
      </Section>

      <Section title="Tips">
        <Card>
          <ul className="space-y-2 text-sm text-krypt-muted">
            <li>
              <BookOpen className="mr-2 inline h-3.5 w-3.5" />
              Run the bot on Paper for at least a few hundred settled trades before
              going Live. The Profiles page lets you compare settings.
            </li>
            <li>
              <BookOpen className="mr-2 inline h-3.5 w-3.5" />
              Narrow the <span className="text-white">Categories</span> in Settings if you
              don&apos;t trust certain markets (e.g. thinly traded regional sports).
            </li>
            <li>
              <BookOpen className="mr-2 inline h-3.5 w-3.5" />
              Use <span className="text-white">Order expiration</span> (Settings → Order placement) to
              cancel orders that haven&apos;t filled. A late fill at a stale price eats the edge.
            </li>
            <li>
              <BookOpen className="mr-2 inline h-3.5 w-3.5" />
              The History page's Daily P&L chart is the truest signal of whether
              your config has edge. Don't judge from a single trade.
            </li>
          </ul>
        </Card>
      </Section>
    </Page>
  );
}


function FeatureCard({
  icon: Icon, title, body,
}: { icon: React.ComponentType<{ className?: string }>; title: string; body: string }) {
  return (
    <Card>
      <div className="flex items-center gap-2">
        <div className="grid h-8 w-8 place-items-center rounded-lg bg-krypt-purple/15 text-krypt-purple">
          <Icon className="h-4 w-4" />
        </div>
        <div className="text-sm font-semibold text-white">{title}</div>
      </div>
      <p className="mt-3 text-xs leading-relaxed text-krypt-muted">{body}</p>
    </Card>
  );
}

function Step({
  n, title, body,
}: { n: number; title: string; body: React.ReactNode }) {
  return (
    <li className="flex items-start gap-3">
      <div className="grid h-7 w-7 shrink-0 place-items-center rounded-full border border-krypt-purple/40 bg-krypt-purple/10 text-xs font-semibold text-krypt-purple">
        {n}
      </div>
      <div>
        <div className="text-sm font-medium text-white">{title}</div>
        <p className="mt-0.5 text-xs leading-relaxed text-krypt-muted">{body}</p>
      </div>
    </li>
  );
}

function SettingRow({ label, hint }: { label: string; hint: string }) {
  return (
    <div>
      <div className="font-mono text-[11px] text-krypt-purple">{label}</div>
      <div className="mt-0.5 text-xs leading-relaxed text-krypt-muted">{hint}</div>
    </div>
  );
}

function Row({
  icon: Icon, label, body,
}: { icon: React.ComponentType<{ className?: string }>; label: string; body: string }) {
  return (
    <li className="flex items-start gap-3">
      <Icon className="mt-0.5 h-4 w-4 shrink-0 text-krypt-purple" />
      <div className="text-xs">
        <span className="text-white">{label}</span>
        <span className="ml-2 text-krypt-muted">{body}</span>
      </div>
    </li>
  );
}

function StratBlock({
  icon: Icon, tone, title, body,
}: {
  icon: React.ComponentType<{ className?: string }>;
  tone: 'win' | 'loss' | 'purple';
  title: string;
  body: string;
}) {
  const toneClasses = {
    win: 'border-krypt-win/30 bg-krypt-win/5 text-krypt-win',
    loss: 'border-krypt-loss/30 bg-krypt-loss/5 text-krypt-loss',
    purple: 'border-krypt-purple/30 bg-krypt-purple/5 text-krypt-purple',
  }[tone];
  return (
    <div className={`rounded-xl border p-4 ${toneClasses}`}>
      <div className="flex items-center gap-2">
        <Icon className="h-4 w-4" />
        <div className="text-sm font-semibold">{title}</div>
      </div>
      <p className="mt-2 text-xs leading-relaxed text-krypt-muted">{body}</p>
    </div>
  );
}

function FlowDiagram() {
  return (
    <svg viewBox="0 0 720 130" className="w-full text-krypt-muted">
      {[
        { x: 20, label: 'Kalshi API', sub: 'markets · fills' },
        { x: 175, label: 'Scanner', sub: 'whale + momentum' },
        { x: 330, label: 'Trader', sub: 'filter · size · place' },
        { x: 485, label: 'Order book', sub: 'limit cross' },
        { x: 620, label: 'Resolver', sub: 'settlement P&L' },
      ].map((n, i) => (
        <g key={i}>
          <rect
            x={n.x} y={35} width={90} height={60} rx={10}
            className="fill-krypt-surface2 stroke-krypt-border" strokeWidth={1}
          />
          <text x={n.x + 45} y={62} textAnchor="middle" className="fill-white text-[11px] font-semibold">
            {n.label}
          </text>
          <text x={n.x + 45} y={78} textAnchor="middle" className="fill-krypt-muted text-[10px]">
            {n.sub}
          </text>
        </g>
      ))}
      {[110, 265, 420, 575].map((x, i) => (
        <g key={i}>
          <line x1={x} y1={65} x2={x + 65} y2={65} stroke="currentColor" strokeWidth={1.5} markerEnd="url(#arrow)" />
        </g>
      ))}
      <defs>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
          <path d="M0,0 L10,5 L0,10 z" fill="currentColor" />
        </marker>
      </defs>
    </svg>
  );
}
