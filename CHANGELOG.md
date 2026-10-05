# Changelog

## Unreleased

### AI agents over MCP
- **Connect Cursor, Claude Code, Claude Desktop or Codex** to a loopback MCP
  server inside the app (AI Agents page). One click copies a ready config for
  each client; the token goes main → clipboard and is never shown on screen.
- **Three permissions: read only, paper, live.** Paper fills immediate-or-cancel
  against the REAL order book with imaginary money and settles on the real
  outcome — demo's synthetic books would teach an agent to trade demo. Live is
  its own confirmed switch and runs through the desktop ticket's submit path.
- **No buy without a forecast, no forecast without an edge.** An agent must
  record its fair value first, and the order is refused unless it beats the
  price by your minimum edge after Kalshi's fee. Agent caps (per order, per
  day, open positions) stack on the terminal's; an agent can only sell or
  cancel what it opened; every attempt, refused or not, is logged.

### Agent workbench (each behind its own toggle, all off by default)
- **Research:** collected 15m signals/ticks, whale trades, momentum alerts and
  trade history; bucketed win rates (gross edge vs price paid, said as gross);
  the Backtest page's own backtesters with a hypothetical config change.
- **Strategy scripts:** the script guide, validate, backtest, save — always
  sandboxed and always saved disabled. A separate toggle lets an agent switch
  on the scripts it wrote; the Scripts page still decides paper vs live.
- **Settings:** strategy settings, and — a separate, confirmed toggle — engine
  on/off, live switches and risk limits. Every config key is classified; the
  environment, credentials, trusted scripts and the agent's own permissions
  and caps are never changeable by an agent.

### Safety for live agents
- **Ask me first** (on by default): a live agent order waits for your approval
  in the app or by phone (`agents`, `approve N`, `reject N`). It is re-checked
  against the market at the moment you approve, counts against the daily
  spend cap while it waits, and expires after 10 minutes.
- **Daily loss stop**: realised losses today plus open losses at the bid. At
  the limit, agent buys stop for the UTC day; selling to exit never does.

### Autopilot
- The app can run an agent on a schedule with your own AI key — the same tools
  and rails as a connected client, nothing more. Off by default, with three
  budgets: runs per day, tokens per day, tool calls per run. Every run is
  logged with its tokens, cost (where the provider publishes prices), each
  tool it called and its own report.

### Client setup
- Claude Code configs use `--scope user` (the default scope only loads in the
  folder the command was run from). Codex now connects over HTTP directly
  (`http_headers`) instead of through the stdio bridge.

### Forecast scoreboard
- Every AI fair value — from the Analyse button and from agents — is scored
  against the market price at the moment it was made, once the market settles.
  Brier score, paired; one forecast per market; no verdict under 30 settled
  markets or inside two standard errors.

### Fixes
- CI now runs the renderer (vitest) suite as well as typecheck and pytest.
- **Analyse always failed.** `_h_ai_analyze` called `terminal.market_detail`
  without its keyword-only `authed`, so every click raised `TypeError` before
  reaching the provider.

## 6.0.0 — 2026-08-25

The "trade it yourself" release. Everything up to 5.0 answered *should the bot act
on this one thing it is watching?*. This one adds the other half: a terminal for
any market you name, the prices to judge it against, a phone in the loop — and a
privacy stance the code now enforces rather than promises.

### Krypt Terminal (manual trading)
- **Discover any market**, not just the ones a scanner happened to observe:
  trending (ranked off the live tape, not a 24h counter still showing
  yesterday's finished events), closing soon, newest, most traded, watchlist.
- **A full market page** — live order book, trade tape, probability chart,
  microstructure and calibration panels, resolution-risk notes, your position,
  and a trade ticket.
- **Per-field provenance.** Every number says whether it came from our own
  websocket, a REST read this second, or a cached one. A price without an
  attribution is asking for trust the app is trying not to require.
- **Absent is absent.** Kalshi returns `yes_bid: 0` for an EMPTY book side and
  `last_price: 0` for a market that has NEVER traded. Coerced to numbers those
  are confident lies you would trade on, so they render as an em dash instead.

### Standing rules
- Stop loss, take profit and price alerts attach to a position. Thresholds are
  in **probability points**, not percent-of-cost: on a market that already is a
  probability, "get me out below 30¢" is the sentence a trader means.
- A stop watches the best **bid** on the side you hold — what you could
  actually sell into. A mid is a price at which nobody has offered to buy
  anything, and a stop that fires on one fires into a book that cannot fill it.

### Cross-venue (Polymarket, read-only)
- The same question priced on both venues, side by side.
- The matcher weights tokens by **rarity** and treats proper nouns as identity,
  because plain token overlap scored "Barack Obama" against "Michelle Obama" as
  a strong match while rejecting the true "Marco Rubio" pair — the boilerplate
  swamped the one word carrying the meaning. A mispair does not degrade
  gracefully; it renders as a large, inviting spread between two different
  questions.
- **Read-only on purpose**: trading Polymarket needs a Polygon wallet and a
  custody surface this app should not grow by accident, and it geoblocks US
  persons anyway. A price gap is **never** called an arbitrage — the two venues
  can settle the same English question differently.

### Remote control (Discord / Telegram)
- Check status, balance, positions, orders, rules and history — or quote and
  place a trade — from your phone, through a bot whose token you own.
- **Bound to one identity**: direct messages only, from the exact user id you
  paired (Discord) or the chat that completed a one-time pairing code
  (Telegram). Guild and group channels are ignored outright.
- **Reading and trading are separate permissions**, and trading is off by
  default. Turning on alerts does not turn on spending.
- **No order fires from a single message.** Every trade is quoted first and
  needs a confirmation code tied to that exact order, so an autocorrect or a
  message sent to the wrong window cannot trade.
- Orders run through the same rails as the desktop — size cap, notional cap,
  market status, and the "you cannot sell what you do not hold" check.

### Privacy: no telemetry
- **The anonymous P&L leaderboard is removed.** The app used to post profit and
  strategy settings to Krypt-owned Discord webhooks on a ~30-minute timer, on
  by default. There is now no analytics, no crash reporting, no usage
  reporting and no per-install identifier.
- This is **enforced, not promised**: a test fails the build if the module
  returns, if any backend file so much as mentions it, or if a hardcoded
  webhook URL appears anywhere in the backend.
- A new **Privacy screen** lists every host the app can contact, what it sends,
  when, how to switch it off — and a live count of how often it actually has.
- Discord Rich Presence remains, and is now stated plainly: it travels over a
  local pipe to your own Discord client, carries no account information at all,
  and stops when Discord does.

### Logs stop leaking credentials
- Log records are scrubbed on the way to disk, by **value** (the secrets
  currently loaded, wherever they appear) and by **shape** (Discord and
  Telegram token patterns, PEM private-key blocks, bearer headers) — so a token
  from a library we do not control, or one pasted into the wrong box, is caught.
- Kalshi order ids are deliberately **not** redacted. They are UUIDs and the
  single most useful thing in a trading log; blanket-redacting them would make
  every bug report unreadable to save nothing.

### Under the hood
- IPC input scrubbing moved out of `ipc.ts` into `electron/system/sanitize.ts`
  so it can actually be tested — `ipc.ts` imports `electron` and cannot load
  outside a real Electron process, which left the functions standing between a
  hostile renderer and a backend that spends money unreachable by any test.
- A **vitest** suite for the renderer and Electron-side helpers (`npm test`),
  alongside the existing Python tests. `npm run test:all` runs everything.
- The terminal contract lives in `shared/market.ts`, kept separate from the
  engine's `shared/types.ts` rather than growing a second half of
  half-populated fields onto it.

### Exchange balances, and a stuck-order fix
- **Fixed: a 15m entry could retry its cancel forever.** Requiring a terminal
  order status before booking "canceled" is right — booking a live order as
  dead is how contracts settle off the books — but on its own it gave the loop
  no way to STOP. An order Kalshi kept reporting as `resting` retried every
  poll indefinitely; a beta log showed the same order id repeating at ~4s
  intervals, drowning everything else. Kalshi stops matching at the close, so
  a resting order on a CLOSED market can never fill again — that is the
  terminating condition, and a confirmed fill still wins over it. The warning
  is also throttled now: a line inside a 4s poll is not a warning, it is a
  denial of service on the log file and on the diagnostics bundle.
- **Cash by exchange is always on screen.** Kalshi allocates collateral per
  exchange shard and does not rebalance for retail accounts, so "I have
  $2,000" is not one number — an order can only be filled on an exchange your
  money is on. The split now shows permanently on the portfolio and 15m crypto
  screens rather than only when a shard hits zero, which is the question a
  user has BEFORE it does.
- **Funds can be moved between any two exchanges from that bar** — pick a
  source, a destination and an amount. Same rails as before: a confirmation
  naming the exact figure and both engines, the button disabled in flight
  because the endpoint takes no idempotency key, and every check re-enforced
  in the backend, which refuses to overdraw the source on a freshly read
  balance. The link out to Kalshi's own page is kept beside it.
### Beta reporting
- **The diagnostics bundle now carries the log file, not just this session.**
  It read an in-memory buffer that starts empty on every launch — and the
  usual way a beta report arrives is "it broke, I restarted, here you go", at
  which point that buffer held nothing but startup chatter and the evidence
  was only on disk. It now includes the tail of `backend.log` as well, which
  survives the restart and is already scrubbed by the backend's own filter.
  Both are kept: the file has the backend's detail, the session buffer has the
  main-process and IPC lines that never reach it. Only the last 512KB of the
  file is read, so a 10MB log does not stall the button.
### Release audit: all 28 defects found and fixed
A 61-agent adversarial audit of the whole program raised 47 findings; each was
attacked by an independent skeptic and 36 survived, merging to 28 defects. The
whole set is fixed here — ten release blockers, a credential leak, an exposure
cap the engine could over-deploy past, five ledger defects that reported the
wrong money, three remote-control faults, two privacy-catalogue gaps and seven
wrong numbers on screen.
In almost every case the CORRECT implementation already existed elsewhere in
the same file — these were divergences from the codebase's own pattern.

- **A transient refusal no longer disarms a stop loss.** Every non-ok submit
  wrote `status='error'`, which is terminal: the armed-only query, claim,
  cancel and the stranded-rule recovery all require `armed`, so nothing ever
  re-armed it. A matching-engine halt or a failed portfolio read therefore
  switched a stop off for good, with the price free to gap. A refusal means
  nothing was sent, so the rule now stays armed; only a genuinely UNCONFIRMED
  send — which may be live on Kalshi — stops and asks for a human.
- **A still-live 15m entry is no longer booked "canceled".** A cancel that
  timed out or 5xx'd leaves the buy resting, and the follow-up read then says
  what any unfilled resting order says: `resting`, fill 0. Booking that as
  canceled resolved the row, and since open positions filter on unresolved and
  the main reconcile skips the 15m series, the order stayed live, filled and
  settled with no row, no stop-loss and no P&L — the same shape as the −$6.56
  incident that function's docstring records. It now requires a terminal
  status (or nothing left to fill) and otherwise keeps the row open to retry.
- **A live pair leg is no longer booked "error" when the LOOKUP fails.**
  `find_order_by_client_id` raises on a failed request and returns None only on
  a confirmed absence; collapsing both read "the lookup broke" as "no such
  order". The directional path always drew that distinction — this leg was the
  sole exception.
- **A question and its exact opposite no longer pair.** `above`, `below`,
  `over`, `under` are stopwords and lowercase, so direction reached neither the
  overlap score nor the proper-noun rule: measured on the shipped module, a
  threshold and its complement scored **1.000**, and a negated question 0.833.
  Their prices sum to ~100c by construction, so the panel rendered a permanent,
  maximum-width fake spread. Direction and negation are now disqualifiers; both
  cases now score 0.050 and every legitimate pair still matches.
- **Reconcile no longer crashes every cycle** once two local rows share one
  Kalshi position (a hand-buy on a market the bot already holds). It passed the
  per-ticker quote DICT into the numeric `mark_price_cents` column; sqlite
  refused the bind and the pass aborted mid-iteration, so orphan-closing,
  rescue and import all stopped and the inflated open count quietly blocked new
  entries. It now converts through `_side_mark_cents`, as the branch 30 lines
  below always did.
- **Real deci-cent book levels are no longer discarded.** The price parser
  rejected anything outside 1..99c, but the tapered 15m crypto series tick in
  0.1c below 10c and above 90c and the order layer accepts 0.1..99.9 as
  tick-valid. Against the repo's own recorded history, **6.7% of 300,441
  candles** close with a top of book inside the discarded band. The effect was
  not a missing number but a wrong one: with bids at 99.4/99.2/98.0 the first
  two vanished and 98.0 was reported as best bid, so a stop armed "below 99"
  sold into a bid that did not exist. Only the sentinels (0 and 100) are
  absent now.
- **Two exit rules can no longer sell more than is held.** The oversell guard
  was rebuilt empty on every pass and Kalshi's position does not shrink until a
  sell FILLS, so an exit still resting from an earlier pass was invisible. The
  live resting-sell size is now read once per pass and counted against what a
  rule may sell — failing OPEN if that read fails, since blocking every exit on
  an unreadable list would strand the protections entirely.
- **A hand-placed buy no longer reads as an instant day loss.** The account
  total used the bot-only open cost, which deliberately excludes manual rows,
  while cash comes from Kalshi and does fall on a manual fill — so the total
  dropped by the full cost of every hand-buy. That figure feeds the daily
  stop-loss: a $60 buy on a $500 account tripped a 5% day stop and halted the
  main engine, the 15m engine and every user script, with nothing lost.
- **The websocket no longer reports `connected` with no socket.** The
  silent-link watchdog returns from inside the `async with`, skipping the
  clean-up that sat after it; the quote and book accessors gate only on that
  flag, and order pricing prefers the websocket book over REST — so a ≥30s-old
  book was priced against as live for up to ~15s per fire. Now a `try/finally`,
  matching the sibling client that always had one.
- **The shard transfer is no longer auto-retried.** Its body carries no
  idempotency key, but the transport retries on timeout, 5xx and 429 for every
  method and re-signs each attempt — so one lost response could move the money
  two or three times while the UI reported failure. Order placement is safe
  only because it mints one client_order_id outside the loop; this had no
  equivalent and now opts out of retrying entirely.
- **A rejected webhook URL no longer leaks its token.** A Discord webhook's
  credential IS its last path segment, and `urlparse` returns no hostname for
  a scheme-less paste — so the fallback printed the whole URL at WARNING on
  every whale, momentum, order and stats event. That line lands in
  backend.log, is pushed to the Logs page, and ships inside the diagnostics
  bundle, which states in the same breath that secrets are never included.
  Fixed at both layers: the log line now reports scheme and host only (never a
  path, since a URL that failed the allow-list could be anything), and the
  scrubber gained a shape rule for Discord webhook URLs — neither of its two
  passes caught them before, because a webhook pasted into Settings is never
  registered as a known value and its token has no distinctive shape.
- **A partially-filled manual order is booked `partial`, not `filled`.**
  `filled` tells the rest of the app that nothing is still working on the
  book, and three systems act on that: the exposure cap values `filled` rows
  at cost rather than committed notional, so 10 of 100 contracts at 50c
  counted as $5 instead of $50 and the engine over-deployed past its own cap;
  the pending-order poll skips them, so nothing watched the live order; and
  Cancel All selects only `submitted`/`partial`, so the button that exists to
  flatten working orders would not touch it. Nothing demoted such a row
  afterwards either. Both manual-buy paths now use the same mapping the rest
  of the engine has always used, with the merge path judging the combined
  fill against the combined target.
- **A partial manual exit now books its realised P&L and its exit fee.** Both
  were computed and then written to no numeric column at all — they reached
  only an event note, which is never read back for money. So the gain
  vanished, later settlement recomputed P&L off the shrunk basis, and the
  row's recorded fees FELL after paying one. Selling 60 of 100 bought at 20c
  for 90c and letting the rest settle reported about −$8.45 on a sequence that
  netted about +$32.50. The contracts that left are now booked as a resolved
  row carrying their cost, their share of the entry fee plus the whole exit
  fee, and the realised amount, while the original keeps the remainder on its
  own basis.
- **A second manual buy on the same market merges its money, not just its
  contracts.** Cost, average price and fees stayed at the first buy's values.
  The 30s reconcile usually rewrote the basis and hid it, but a buy-buy-sell
  inside one window books P&L off the stale figure and resolves the row: 10 at
  30c plus 10 at 70c sold at 60c booked about +$8.90 on a trade that made
  about +$1.90.
- **The sell ticket quotes the entry fee it will actually charge.** The cost
  basis it quotes against is fee-exclusive, so subtracting only the exit fee
  overstated the result by exactly the entry fee — always in the user's
  favour, under a label reading "Realised P&L", while the portfolio screen
  says fees are already included. 100 at 50c sold at 60c quoted +$8.25 and
  booked +$6.50.
- **15-minute sizing is bounded by the shard that collateralises it.** Only
  cash on the crypto shard can back a crypto order, but `balance_pct` sizing
  read the account-wide sum: $1,950 general plus $50 crypto at 5% asked for
  ~$99 against $50, was rejected, and recomputed identically every window
  while the UI showed a healthy bankroll. The starved-shard banner stayed
  hidden too, because it tests for an affirmative zero rather than "not
  enough". Clamped only when the shard balance is known.
- **A corrected remote identity now takes effect.** The bot sync gated on
  liveness alone and `start()` returns early when a task is running, so it
  never re-assigned the identity — correcting a mistyped Discord user id did
  nothing, and DMs from the OLD id kept executing trades while the new one was
  ignored, with the panel showing the new value and no way to see the live
  one. A rotated bot token was never applied either. The sync now compares
  what the bot is actually running with, and a config change applies at once
  instead of waiting for a tick that no-op'd.
- **A Telegram pairing survives a restart.** Python only mutated its in-memory
  copy and emitted an event nothing listened to, so the pairing was lost on
  restart and wiped within a session by any config push — after which every
  rule alert was dropped silently and the user had to re-pair. Main now
  persists it, exactly as it does a script config patch.
- **The remote `orders` reply prints a usable order id.** It truncated to 10
  characters while `cancel` passes the token straight through to Kalshi, whose
  ids are 36-char UUIDs — so the only risk-reducing command available away
  from the desk could not be used at all.
- **A resting order's size is readable again.** The order parser read only
  the pre-August-2026 integer names, so every working order rendered its size
  as an em dash claiming Kalshi reported no remaining count, and the remote
  reply printed the literal string `None` — the user was asked to cancel
  blind. Chained on presence rather than truthiness, because 0 remaining is a
  real count on a filled order.
- **Provenance is per-row again.** The sweep cache hands out the same row
  objects for 45s and the copy taken from it was shallow, so a live quote
  wrote its value onto the copy but its provenance into the shared dict — a
  later request could return the REST number badged as our own websocket.
- **An exact cent amount transfers exactly.** `int(amount * 100)` floored the
  binary float rather than the cent grid, so $2.01 moved $2.00; about 6% of
  two-decimal amounts were a cent short, and the UI prefills two decimals. The
  deliberate sub-cent floor is unchanged — $1.239 still moves $1.23.
- **The credential test reports the account balance**, not shard 0's slice, so
  an account holding its collateral on the crypto shard no longer verifies as
  "balance $0.00".
- **A rule that cannot read the book now says so.** The failure branch wrote
  only a fresh timestamp, leaving the stale price beside it — and the panel
  gates its warning on a null price, so an armed rule matched no branch at
  all: a recent check, an old price, and no warning, while nothing had been
  evaluated.
- **Quote lifetime no longer interpolates across gaps.** Samples are only
  taken while the socket is up and the book valid, and every reconnect
  invalidates it, so an ordinary blip leaves a hole — which was charged to a
  single quote as if it had stood still. The panel's own note says gaps are
  never interpolated; now they are not.
- **The Privacy panel stops claiming zero for what it never measured.** Only
  two modules counted their calls, so eight catalogued hosts — including the
  crypto price feeds, which run every few seconds — showed a confident
  "0 calls / not called yet this session" while being contacted. Those
  clients now count, and a host with genuinely no measurement renders as an
  em dash rather than a zero, the same honest-null rule the prices follow.
- **The webhook allow-list matches the published catalogue.** Three Discord
  aliases were accepted while appearing nowhere on the Privacy screen, so a
  legacy `discordapp.com` webhook sent cash, portfolio, P&L and per-position
  cost to a hostname the "every host this app can contact" list never showed.
  A test now pins that every accepted host is catalogued.
- **The cross-venue comparison shows how old its Polymarket price is.** The
  Kalshi side is read live per request while the Polymarket side comes from a
  90s cache re-rendered on a 30s poll, so the panel could assert one venue was
  "currently" cheaper on a number up to two minutes old, with no age on
  either side.
### Kalshi's August 2026 API changes, audited against the changelog
- **Exchange sharding is handled**, and re-verified live: crypto (including
  KXBTC15M/KXETH15M) on shard 2, tennis and baseball on shard 3, everything
  else on 0. `/portfolio/balance` is now shard-scoped, so the balance read
  folds in the `balance_breakdown` — reading it unchanged would have
  understated cash the moment any collateral sat off shard 0, and that number
  feeds the daily stop-loss. Orders route with `exchange_index: -1`
  (auto-route by ticker). Positions, orders and fills are deliberately left
  unfiltered: there the index is a filter, and a shard-scoped read would have
  made the reconcile pass orphan-close every crypto position.
- **Fixed: block trades counted as whale signals.** Kalshi now stamps every
  print with `is_block_trade` (present on 1000/1000 of a live sample). A block
  is privately negotiated away from the book and printed afterwards — it
  carries a taker side and a large size, so it cleared every gate in the whale
  scanner, but nobody swept the public book, which is the entire premise of
  the signal. Blocks are large BY CONSTRUCTION, so the bias was systematic
  rather than occasional. They are now excluded from scanning and LABELLED in
  the terminal tape rather than hidden — it is still a real trade.
  The flag is carried through the websocket tape too, which is the path the
  scanner actually prefers.
- **Per-shard trading status is now a rail.** Kalshi halts a matching ENGINE,
  not the whole exchange, and `/exchange/status`'s top-level `trading_active`
  describes shard 0 only — so a crypto halt on shard 2 leaves it reading true.
  The order ticket now reads `exchange_index_statuses` and refuses an order
  into a stopped engine with a message saying so, rather than letting Kalshi
  return a bare rejection. It is enforced at submit (fresh read) as well as in
  the quote, on the desktop and over remote alike. An unreadable status is
  UNKNOWN and blocks nothing: refusing to trade because a status endpoint
  blipped would be a worse failure than the one it guards against.
- **You can move collateral between exchanges from inside the app.** Kalshi
  does not rebalance for retail accounts — auto-rebalancing is an
  institutional feature — so the fix for an unfunded shard was always a trip
  to their site. The warning now carries an amount box and a Move funds button
  that calls `/portfolio/intra_exchange_instance_transfer` directly, with the
  link out kept alongside it.
  Real money, so it is fenced accordingly: a confirmation dialog states the
  exact figure and both engines, the button is disabled in flight because the
  endpoint takes no idempotency key and a double click would move it twice,
  and NOTHING the renderer sends is trusted — the backend re-validates the
  amount and both shard indices and refuses to overdraw the source, reading
  the balance fresh to do it. Kalshi takes the amount in CENTICENTS (dollars ×
  10,000), a third money unit alongside the cents and dollar-strings already
  on the wire and the one where an off-by-100 moves a hundred times the
  intended amount; the conversion happens in exactly one place and a
  sub-cent remainder is dropped rather than rounded up.
- **The 15m crypto page warns about its own shard.** That page is where a user
  is looking when an entry is rejected, so the answer belongs there and not
  only on the portfolio screen. It names the exchange, prints the split across
  every shard, says how much to move — for one entry and for a full book of
  concurrent positions, as ceilings rather than estimates since a contract
  costs at most 99c — and links straight to Kalshi's exchange-balances page.
  It appears only on an affirmative $0: a banner raised on a balance we could
  not read would tell users to move money they already have.
- **Every shard message now names the page that fixes it.** Per-shard cash was
  already read and shown (the Cash card breaks down as "general $250 ·
  crypto $0"), and a starved shard already raised a warning — but nothing said
  where to go, and "move funds to that exchange on Kalshi" is not a
  destination. The portfolio warning now carries a button straight to Kalshi's
  exchange-balances page, and the rejection diagnosis and the 15m skip line
  both print the URL. It follows the ACTIVE environment, so a demo user is
  never sent to kalshi.com.
- **Entries are refused before they are sent when the shard holds no
  collateral.** Kalshi allocates collateral per exchange shard, so an account
  whose cash all sits on the general shard cannot open a crypto position — and
  the 15m engine would retry that doomed order every cycle. It now checks
  first and logs one clear line naming the shard and what to do. Both halves
  are free: the series-to-shard map fills itself from market reads the app
  already makes, and the per-shard balance comes from the existing balance
  cache, so nothing new runs in a path that fires seconds before a market
  closes. It FAILS OPEN on every unknown — no balance read yet, a key with no
  per-shard breakdown, or a series not yet seen — because blocking trading on
  a number we could not read is worse than the rejection it prevents.
- **`user not found` now explains itself.** A beta report on 2026-08-25 showed
  a BTC 15m entry rejected with `HTTP 400 user_not_found: <uuid>` — a member
  id and nothing else. It has two causes needing opposite fixes, so the app no
  longer guesses: it re-reads the balance, which is signed with the same
  credential but is NOT scoped to the market's matching engine. If the balance
  reads, the credential is fine and the engine hosting the market holds none
  of your collateral (Kalshi allocates it per shard, and crypto is shard 2) —
  the message names the shard, the $0.00, and where your cash actually is. If
  the balance fails the same way, the account itself is not recognised: a key
  deleted or rotated on Kalshi, or one created in the other environment, and
  the message says to re-add the keys instead. An undiagnosable case says so
  rather than inventing a cause. Applied to the 15m crypto engine, the manual
  ticket and remote alike.
- Checked and clear: none of the endpoints or fields Kalshi removed this
  summer are referenced anywhere (the multivariate lookup REST endpoint and WS
  channel, `/exchange/announcements`, `response_price_units`,
  `fractional_trading_enabled`, `resting_orders_count`, the `service` error
  field).
- Checked and clear: tick precision. Every one of 6,000 live markets surveyed
  — combo shards included — is `deci_cent` with a 0.1c step, which is exactly
  what the price parser rounds to. The centi-cent structure named in Kalshi's
  changelog is not live on any market yet.
### Release audit: the Kalshi field migration, and two false pairings
- **Fixed: every candle reported a null volume and open interest.** Kalshi's
  candle tier moved to `volume_fp` / `open_interest_fp` and dropped the legacy
  names; the parser read only the legacy ones. Prices kept parsing, so nothing
  looked broken — the chart tooltip just silently stopped showing contract
  counts. Measured 0/14 periods on live data, now 7/7. The live provider check
  now asserts volume too, because prices being right was never evidence the
  counts were.
- **Fixed: a websocket tick could zero out a real volume.** `_fp()` answers
  `0.0` for an absent field — correct for an order-book delta, wrong for a
  published count. A ticker message without `volume_fp` would have overwritten
  a market's REST volume with a confident `0`, attributed to our own feed.
  Absent now stays absent, and the REST read survives.
- **Fixed: settled markets reported no settlement value.** Same migration; it
  read only the removed cent field.
- **Fixed: "announce a run" was paired with "win the election".** Every
  cross-venue disqualifier required BOTH sides to state something, so a title
  that simply stayed silent counted as agreeing. Live 2026-08-25, this scored
  0.59 — confident — and rendered 23.0c against 1.95c. An absent qualifier is
  now unknown rather than agreement.
- **Fixed: a combined market was paired with its own single leg.** "Will Gavin
  Newsom and JD Vance be the 2028 nominees" matched "Will Gavin Newsom win the
  2028 Democratic nomination" at 0.78. P(A and B) ≤ P(A) by construction, so
  that pair manufactures a permanent one-directional "spread" rather than an
  occasional wrong number. Both bad pairs are gone and all ten legitimate ones
  survive.
- Audited and found correct: the fee formula (exact against Kalshi's published
  0.07·p·(1−p) across the whole 1–99c range), the order rails (negative, zero,
  NaN and oversized counts, out-of-range and infinite prices, selling what you
  do not hold — all refused), the remote confirmation flow, and the
  stop-loss-on-the-bid rule.
### Discover: one event can no longer fill a column
- **Fixed: "Closing soon" showed nothing but untraded index-ladder rungs.**
  A deep out-of-the-money rung carries `no_bid: 0.99`, which mirrors into a 1¢
  YES ask — and the filter asked only whether *either* side was quoted, so that
  phantom passed. Measured 2026-08-25: all 60 rows were NASDAQ-100 rungs with
  no bid, a 1¢ ask, no last trade and zero volume. A market now has to be
  genuinely actionable: a two-sided book, or one side with real volume or open
  interest behind it. Unknown volume stays unknown — it is not counted as
  evidence of trading, and not held against the market either.
- **Per-event cap across every discovery column.** A Kalshi event is often a
  strike ladder, not a question: 774 of the 999 markets closing within 6h that
  day were rungs of two ladders, all sharing one close time, so ranking by time
  to close handed them every slot. At most 3 markets from any one event now
  appear, and the column reports how many siblings it hid. Markets with no
  event ticker are not collapsed together — an unknown event is not evidence
  of a shared one.
- **The closing horizon widens on what survives**, not on what Kalshi returned.
  A 6h window can hold 999 markets and still yield an almost empty column once
  the untradeable ones are dropped; it now expands to 24h or 72h to fill.

---

## 5.0.0 — 2026-07-23

The "write your own strategy" release. 5.0 opens the trading engine up: a full
user scripting platform where your own Python strategies run behind the same
kind of hard money rails as everything else — plus a community referral pool
and cross-platform installers.

### Scripts tab (user scripting platform)
- **Python strategy scripts**: write (or AI-generate) your own strategy for
  the 15m crypto markets — plus an optional whale/momentum signal handler —
  and let it trade paper or live. Scripts run **sandboxed by default**: no
  filesystem, network, or import access.
- **Trusted mode (opt-in, dangerous)**: unlocks full un-sandboxed Python for
  a script, running in the process that holds your decrypted API key. Only
  for code you wrote or fully read; a warning modal stands in the way.
- **Money rails on every script, trusted included**: max entry price, max
  contracts per order, max open positions per script, and a per-script daily
  loss stop that auto-disables the script. Rails limit losses — they don't
  eliminate them.
- **In-app backtester**: replay any script over your recorded market data
  before it touches money — taker fills at the recorded ask, Kalshi fees
  included, same rails as live.
- **Live docs + AI prompt pack**: the scripting API reference is generated
  from the running engine, and a one-click context pack lets you draft
  scripts with an LLM. AI code can be confidently wrong — backtest it, paper
  it, read it.
- Scripts have their own master **"Scripts live" switch**, separate from the
  main auto-trading toggle. As always: no script, bundled or yours, comes
  with a proven edge.

### Community referral pool
- The in-app Kalshi referral is now drawn from an encrypted pool of links
  donated by community users (plus one owner link). Each install picks **one
  at random on first launch** and keeps it, stored encrypted — so for most
  installs the referral credit goes to a random community donor, not the
  authors. Docs and disclosures updated to match.

### Build & fixes
- CI now builds **Linux (AppImage/deb) and macOS (dmg, Intel + Apple
  Silicon)** installers alongside Windows and attaches all of them to the
  GitHub Release. The non-Windows builds are unsigned and less tested.
- Cross-order price rounding fixed, and orders are pinned to the environment
  they were placed on (regression-review findings).
- Readable tooltips on all 8 charts; video walkthrough card on the Guide page.

---

## 4.0.0 — 2026-07-16

The "point everything at the real edge" release. 4.0 is the product of a
measure-first cycle: every strategy surface in the app was backtested on real
recorded data, the losers were removed, and the machinery now centers on the
one statistically significant edge we could verify.

### The edge
- **Settlement Edge (★) strategies**: the settlement-model sniper with a
  fee-aware edge filter is now the flagship 15m strategy family, pinned first
  in the strategy library. It prices Kalshi's real settlement rule (the
  60-second CF index average) and only enters when the model's probability
  beats the ask by a configurable net-of-fees margin. Measured on 60 days of
  recorded production windows: the only strategy class that stays positive on
  walk-forward holdout. Calibration-checked: model P(up) matches realized
  outcomes at the extremes it trades.
- **Model calibration auto-pause**: model-mode entries pause automatically
  when recent live predictions stop hitting.

### Multi-Run + Coin Optimizer
- **Multi-Run**: several strategies trade different coins in parallel, each
  with its own config, mode (paper/live), P&L attribution and per-runner
  settings panel (bet size, stop-loss, take-profit, entry style…).
- **Coin Optimizer**: sweeps a 144-candidate strategy corpus per coin and
  hour-bucket over your recorded history (with a walk-forward holdout that
  catches overfits) and assembles the best 24h schedule; scheduled runners
  execute it live. Runs in a subprocess so optimization can never starve the
  trading loop.
- **Turbine strategy library**: 38 imported community 15m strategies +
  indicator features (VWAP/EMA/SMA/MACD/RSI/velocity), all backtestable on
  your own recorded data.

### Trading engine hardening (adversarial money-path audit)
- Per-runner fixed order sizes are honored (a "1 contract" runner could
  previously inherit %-of-balance sizing and over-buy) and all per-runner
  config overrides are range-clamped like the base config.
- Positions snapshot their exit rules (stop-loss/take-profit/exit threshold)
  at entry — editing or deleting a runner can no longer silently change a
  live position's protection.
- Closed positions in the non-active environment are settled every tick (an
  env switch can no longer strand a position), and rows stuck unsettleable
  long past close are reaped instead of leaking slots/exposure/coins.
- Paper maker entries fill at the posted limit, not the ask — paper P&L no
  longer flatters what live would do.
- Kalshi API usage level auto-upgrades to Advanced (3× order throughput).
- Hot paths hardened against RPC-timeout starvation.

### Removed (measured, found wanting)
- **Perps research program**: an 11-strategy audit on real recorded perps
  data found zero profitable configurations (fees exceed every measurable
  edge; funding ~zero; books index-pegged), re-verified on 10 more days of
  data. The recorder, strategy builder and research tables are gone. The
  maker-only **volume farmer stays** — it earns Kalshi's one-time perps
  signup reward (trade $50 → $25) for a few cents in fees, then halts itself.
- **HF book recorder / trailing exits**: the exit-latency study concluded the
  15m edge is entirely entry-side — hold-to-settlement beats every realizable
  trailing exit. The recorder and its bulky table are gone (dropped on first
  launch; the database VACUUMs the space back).

### Quality of life
- Positions, trade history and 15m rows deep-link to their Kalshi market page.
- Multi-source spot feed for the 15m tab (Kalshi CF index stream → Coinbase
  WS → REST fallbacks) with the exact settlement average sharpening the model
  in the final seconds before each window closes.
- Test suite: 588 Python tests (from ~150 at 3.x), including regression tests
  for every money-path fix above.

**Upgrade note**: the first launch after upgrading drops the removed research
tables (perps ticks/trades/candles/funding/positions, HF book ticks) and
VACUUMs the database — expect a one-time pause and a smaller DB file.

---

## 3.x — 2026-06

Multi-page Electron app: scanner engine (whales + momentum), 15m Crypto
monitor + executor with paper mode, fee-aware backtesting on self-recorded
data, strategy presets ranked by measured edge, DPAPI credential encryption,
DB maintenance, packaging fixes. See git history for details.
