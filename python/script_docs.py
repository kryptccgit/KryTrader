from __future__ import annotations

import db as dbmod
import replay
import script_sandbox

LIVE_ONLY_FIELDS = ("peersAgree", "marketBias", "arbEdgeCents")

FIELD_DOCS: dict[str, str] = {
    "asset": "str — coin symbol: BTC, ETH, SOL, XRP, DOGE, HYPE or BNB",
    "ticker": "str — the market's unique id for this window",
    "series": "str — Kalshi series id, e.g. 'KXBTC15M'",
    "hasMarket": "bool — a live Up/Down market exists right now",
    "closeTime": "str — ISO close time of the current window",
    "minsLeft": "float|None — minutes until the window settles",
    "hourUtc": "int|None — current UTC hour 0-23",
    "inWindow": "bool — inside the configured entry window (time_delay_min)",
    "signal": "bool — the built-in favorite-follow signal fired this tick",
    "favorite": "str|None — 'up' or 'down', the side priced >= 50%",
    "favoritePrice": "float|None — favorite mid probability, 0..1",
    "entryCost": "float|None — cost to BUY the favorite, 0..1",
    "upProb": "float|None — up/yes mid probability, 0..1",
    "downProb": "float|None — 1 - upProb",
    "upAsk": "float|None — order-book best ask for UP (yes side), 0..1 (None = no executable quote — you cannot buy up this tick)",
    "downAsk": "float|None — order-book best ask for DOWN (no side), 0..1 (None = no executable quote)",
    "yesBid": "float|None — yes/up best bid, 0..1",
    "yesAsk": "float|None — yes/up best ask, 0..1",
    "deltaPct": "float|None — abs(spot - window open)/open, fraction",
    "deltaSignedPct": "float|None — (spot - open)/open, SIGNED fraction (positive = price above open)",
    "sigma1m": "float|None — realized 1-min volatility of the underlying (fraction/sqrt-min)",
    "spotUsd": "float|None — live underlying price, USD",
    "strikeUsd": "float|None — the window-open reference the market settles against, USD",
    "modelProb": "float|None — the app's terminal-spot model P(up), 0..1",
    "edgeNetCents": "float|None — the model's best fee-net edge across both sides, cents",
    "settlePrints": "int — prints of the final-minute settlement average already observed (0 outside the final minute)",
    "macd": "float|None — MACD line on 1-min underlying closes",
    "macdSignal": "float|None — MACD signal line",
    "macdHist": "float|None — MACD histogram (macd - signal)",
    "macdCross": "int|None — +1 bullish cross this bar, -1 bearish, 0 none",
    "rsi": "float|None — Wilder RSI(14) on 1-min closes, 0..100",
    "vwap1h": "float|None — 1-hour VWAP of the underlying, USD",
    "ema12": "float|None — EMA(12) of 1-min closes, USD",
    "sma20": "float|None — SMA(20) of 1-min closes, USD",
    "sma50": "float|None — SMA(50) of 1-min closes, USD",
    "priceVsVwapPct": "float|None — (spot - vwap1h)/vwap1h, percent (>0 = above VWAP)",
    "ema12VsSma20Pct": "float|None — (ema12 - sma20)/sma20, percent",
    "ema1VsSma5Pct": "float|None — (ema1 - sma5)/sma5, percent (fast momentum)",
    "velocity1mPct": "float|None — 1-minute percent change of the underlying",
    "change5mPct": "float|None — 5-minute percent change",
    "change15mPct": "float|None — 15-minute percent change",
    "peersAgree": "float|None — fraction of other coins whose favorite points the same way",
    "marketBias": "float|None — snapshot-wide up-bias across coins",
    "arbEdgeCents": "float|None — up+down combined-ask arb edge, cents",
}

CONTRACT_DOC = '''\
Your reply must be EXACTLY one fenced ```python code block and nothing else —
no prose before or after it. The first lines of the script MUST be this
metadata header (comments):

# krypt-script v1
# name: <short strategy name>
# description: <one sentence>

The script must define a top-level function:

    def decide(ctx):
        ...

`decide(ctx)` is called once per coin per engine tick (~every 5s live; once
per recorded tick, ~25s apart, in backtest) while an Up/Down market is open.
`ctx` is a plain dict of market fields (full reference below). Return None
to do nothing, or an order-intent dict to buy one side of the market:

    {"side": "up" | "down",        # REQUIRED - which side to buy
     "price": "ask" | <int 1-99>,  # REQUIRED - "ask" = cross the book now
                                   #   (taker). An integer rests a limit at
                                   #   that many cents (fills only if the
                                   #   ask comes to it; not modeled as a
                                   #   maker fill in backtests).
     "size": <int>,                # optional contracts; capped by the user's
                                   #   safety rails, defaulted from settings
     "take_profit_pct": <float>,   # optional, e.g. 0.15 = sell at +15%
     "stop_loss_cents": <int>,     # optional, sell if our side's bid <= this
     "reason": "<short note>"}     # optional, shown in the trade history

Winning contracts settle at $1.00, losing at $0.00. Kalshi taker fee per
contract: 0.07 x P x (1 - P) dollars at price P (~1.7c at 50c, ~0.7c at
90c), and the per-ORDER fee is rounded UP to the next cent — small orders
pay proportionally more.
At most ONE position per market window per script — after your first intent
in a window (even one refused by the rails) that window is consumed.

ctx["portfolio"] is always present: {"balanceUsd" (None in backtests),
"openCount", "openPositions" (list of this script's open position dicts),
"todayPnlUsd"} — use it for "stop after -$10 today" / "size down when busy"
logic.

OPTIONAL HOOKS (define any subset; a script must define at least one of
decide / manage / decide_signal / supervise):

    def manage(position, ctx):
        # Called every tick for EACH open position this script holds.
        # Return None or "hold" to keep holding, "sell" to flatten NOW at
        # the bid, or {"action": "update", "take_profit_pct": 0.2,
        # "stop_loss_cents": 30} to retune the exit targets (0 clears one).
        # This is how you build trailing stops, signal-reversal exits, and
        # time-based exits. `position`: {ticker, asset, side, contracts,
        # avgEntryCents, curBidCents, minsLeft, tpPct, slCents,
        # unrealizedPct}.

    def decide_signal(signal):
        # Called for each NEW whale/momentum signal the scanner records.
        # Return None to skip, True to follow it, or {"follow": True,
        # "sizeUsd": 10} to size it. Follows buy the SIGNAL'S side (you
        # filter and size; side-flipping isn't supported because it can't
        # be backtested honestly). `signal`: {source: "whale"|"momentum",
        # ticker, category, title, price (0..1), side, dollarValue,
        # confidence, edgePts, costCents, signalType, hourUtc, createdAt}.

    def supervise(app):
        # Called once per engine tick. Return None or {"set": {key: value}}
        # to change WHITELISTED app config — this is how a script switches
        # engines/strategy posture dynamically ("volatility high -> model
        # mode", "past 2am UTC -> disable momentum"). Whitelisted keys:
        # enable_trading, trade_whales, trade_momentum, crypto15m_enabled
        # (booleans, OFF-only — scripts can disarm engines, never arm them);
        # crypto15m_direction_mode ("favorite"|"contrarian"|"model");
        # crypto15m_entry_threshold, crypto15m_entry_max,
        # crypto15m_min_delta_pct, crypto15m_time_delay_min (numbers).
        # Anything else is ignored. Rate-limited to one change per 30s;
        # every change is logged.
        # `app`: {hourUtc, balanceUsd, scriptTodayPnlUsd, engines: {...},
        # config: {current whitelisted values}, assets: [{asset, minsLeft,
        # sigma1m, modelProb, favoritePrice}]}.
        # NOTE: supervise() is NOT simulated in backtests.

    def on_start(state):            # once when the script loads
    def on_fill(position, state):   # an entry order filled
    def on_settle(position, state): # a position exited or settled

Available globals (sandboxed scripts may use ONLY these — no imports):
`math`, `statistics`, `state` (a persistent dict that survives between
ticks — use it for cross-tick memory), and `log(msg)` (shows in the app;
print() is aliased to it).
'''

EXAMPLE_SIMPLE = '''\
# krypt-script v1
# name: Late Favorite Follow
# description: Buys the favorite in the last 3 minutes when it is 80-95c with an executable ask.

def decide(ctx):
    ml = ctx["minsLeft"]
    if ml is None or ml > 3.0:
        return None
    fav = ctx["favorite"]
    if fav not in ("up", "down"):
        return None
    ask = ctx["upAsk"] if fav == "up" else ctx["downAsk"]
    if ask is None:
        return None          # no executable quote this tick - never trade blind
    if 0.80 <= ask <= 0.95:
        return {"side": fav, "price": "ask", "reason": "late favorite"}
    return None
'''

EXAMPLE_STATEFUL = '''\
# krypt-script v1
# name: Momentum Confirm
# description: Buys the direction of a sustained 5-minute move, confirmed across two ticks, with a stop.

def on_start(state):
    state["last_dir"] = {}

def decide(ctx):
    ch = ctx["change5mPct"]
    ml = ctx["minsLeft"]
    if ch is None or ml is None or ml > 8.0 or ml < 2.0:
        return None
    direction = "up" if ch > 0.05 else ("down" if ch < -0.05 else None)
    prev = state["last_dir"].get(ctx["asset"])
    state["last_dir"][ctx["asset"]] = direction
    if direction is None or prev != direction:
        return None          # need two consecutive ticks agreeing
    ask = ctx["upAsk"] if direction == "up" else ctx["downAsk"]
    if ask is None or ask > 0.65:
        return None          # only take it while the book still prices doubt
    return {"side": direction, "price": "ask",
            "stop_loss_cents": 20, "reason": "5m momentum x2"}
'''


EXAMPLE_MANAGE = '''\
# krypt-script v1
# name: Trailing Exit
# description: Buys cheap momentum, then trails a stop up behind the bid instead of holding to settlement.

def decide(ctx):
    ml = ctx["minsLeft"]
    ch = ctx["change5mPct"]
    if ml is None or ch is None or ml > 10.0 or ml < 4.0:
        return None
    direction = "up" if ch > 0.1 else ("down" if ch < -0.1 else None)
    if direction is None:
        return None
    ask = ctx["upAsk"] if direction == "up" else ctx["downAsk"]
    if ask is None or ask > 0.55:
        return None
    return {"side": direction, "price": "ask",
            "stop_loss_cents": 25, "reason": "cheap momentum"}

def manage(position, ctx):
    bid = position["curBidCents"]
    if bid is None:
        return None
    sl = position["slCents"] or 0
    trail = int(bid) - 12            # keep the stop ~12c under the bid
    if trail > sl:
        return {"action": "update", "stop_loss_cents": trail}
    if position["minsLeft"] is not None and position["minsLeft"] < 1.0 and bid >= 85:
        return "sell"                # bank a near-certain win before the wire
    return None
'''

EXAMPLE_SUPERVISOR = '''\
# krypt-script v1
# name: Night Shift
# description: Runs the crypto engine in model mode only when volatility is high, and pauses momentum overnight.

def supervise(app):
    changes = {}
    vols = [a["sigma1m"] for a in app["assets"] if a["sigma1m"] is not None]
    if vols:
        hot = max(vols) > 0.002
        want_mode = "model" if hot else "favorite"
        if app["config"]["crypto15m_direction_mode"] != want_mode:
            changes["crypto15m_direction_mode"] = want_mode
    quiet = 2 <= app["hourUtc"] < 8
    if app["engines"]["momentum"] and quiet:
        changes["trade_momentum"] = False
    return {"set": changes} if changes else None
'''


def _inventory(env: str) -> str:
    lines: list[str] = []
    try:
        with dbmod.get_db() as conn:
            row = conn.execute(
                """SELECT COUNT(DISTINCT s.ticker) AS windows,
                          SUM(CASE WHEN s.resolved=1 AND s.up_won IS NOT NULL
                              THEN 1 ELSE 0 END) AS resolved,
                          MIN(s.observed_at) AS a, MAX(s.observed_at) AS b
                   FROM crypto15m_signals s WHERE s.kalshi_env=?""",
                (env,),
            ).fetchone()
            ticks = conn.execute(
                "SELECT COUNT(*) FROM crypto15m_ticks WHERE kalshi_env=?",
                (env,),
            ).fetchone()
        if row and int(row["windows"] or 0) > 0:
            lines.append(
                f"- 15m windows: {int(row['resolved'] or 0)} resolved of "
                f"{int(row['windows'] or 0)} recorded, {int(ticks[0] or 0)} ticks, "
                f"spanning {str(row['a'] or '?')[:10]} to {str(row['b'] or '?')[:10]}"
            )
    except Exception:
        pass
    if not lines:
        lines.append("- (no recorded windows yet — backtests will be empty until "
                     "the app has run and collected data)")
    return "\n".join(lines)


def build_context_pack(cfg: dict, env: str = "production") -> str:
    builtins_list = ", ".join(sorted(
        k for k in script_sandbox.SAFE_BUILTINS
        if k not in ("True", "False", "None")))
    fields = []
    for name, doc in FIELD_DOCS.items():
        bt_ok = name in replay._DERIVABLE
        flag = "" if bt_ok else "  [LIVE-ONLY: None during backtests]"
        fields.append(f"- ctx[\"{name}\"]: {doc}{flag}")
    rails = (
        f"- Max entry price: {int(cfg.get('script_max_entry_cents') or 97)}c\n"
        f"- Max contracts per order: {int(cfg.get('script_max_contracts') or 20)}\n"
        f"- Max open positions for this script: {int(cfg.get('script_max_open') or 2)}\n"
        f"- Per-script daily loss auto-disable: ${float(cfg.get('script_daily_loss_usd') or 25.0):.0f}\n"
        f"- Default order size: {int(cfg.get('crypto15m_order_size') or 1)} contracts"
    )
    return f"""You are writing a trading strategy script for KrypTrader, a
Kalshi desktop bot. The script trades 15-minute crypto "Up/Down" markets
(will BTC/ETH/SOL/... close this 15m window above its open price?). Each
side is a binary contract: win = $1.00, lose = $0.00.

{CONTRACT_DOC}

MARKET CONTEXT FIELDS (every field can be None — ALWAYS check before
comparing; a None you don't check will crash and disable the script):

{chr(10).join(fields)}

SANDBOX RULES (the script is validated before it runs):
- NO import statements, NO classes, NO async, NO global/nonlocal, NO names
  starting with __ , NO attributes starting with _ .
- Allowed builtins: {builtins_list}
- Per-call budget ~50ms / 200k steps: no heavy loops per tick; precompute
  into `state` incrementally instead.
- The budget bounds CPU time, NOT memory: a single huge allocation (e.g.
  [0]*10**9) is not interrupted and can exhaust RAM — never build unbounded
  data structures. Treat any script you didn't write as untrusted code.

THE USER'S SAFETY RAILS (applied to every intent — your script cannot
override these):
{rails}

THE USER'S RECORDED DATA (what a backtest can replay):
{_inventory(env)}

STRATEGY NOTES (hard-won, respect them):
- upAsk/downAsk are the executable order book. When they are None there is
  no quote and returning an intent does nothing useful — check them.
- These markets are efficiently priced most of the time; blindly buying the
  favorite loses the fee. An edge needs a reason: spot has moved and the
  book lags, momentum persistence, model-vs-book divergence (modelProb vs
  the ask), timing (minsLeft), regime filters (sigma1m, RSI).
- Backtest fills are at the recorded ask, ticks are ~25s apart, and the
  panel is in-sample — a green backtest is a hypothesis, not a promise.
- Positions hold to settlement unless you set take_profit_pct /
  stop_loss_cents; these markets can gap to zero, so size for full loss.

THREE VALID EXAMPLES (format + None-checking to imitate):

```python
{EXAMPLE_SIMPLE}```

```python
{EXAMPLE_STATEFUL}```

```python
{EXAMPLE_MANAGE}```

Now write ONE script implementing the strategy the user describes below (or
if they described none, propose a sensible one using the fields above).
Reply with ONLY the fenced python block.
"""
