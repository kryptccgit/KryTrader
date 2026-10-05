from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


def _data_dir() -> Path:
    base = os.environ.get("KRYPT_TRADER_USERDATA")
    if base:
        d = Path(base) / "data"
    else:
        d = Path(__file__).resolve().parent / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return _data_dir() / "krypt-trader.db"


@contextmanager
def get_db():
    conn = sqlite3.connect(str(db_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()




SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    ticker TEXT PRIMARY KEY,
    event_ticker TEXT DEFAULT '',
    series_ticker TEXT DEFAULT '',
    title TEXT DEFAULT '',
    yes_sub_title TEXT DEFAULT '',
    category TEXT DEFAULT '',
    status TEXT DEFAULT 'open',
    close_time TEXT DEFAULT '',
    volume REAL DEFAULT 0,
    volume_24h REAL DEFAULT 0,
    open_interest REAL DEFAULT 0,
    yes_bid REAL DEFAULT 0,
    yes_ask REAL DEFAULT 0,
    last_price REAL DEFAULT 0,
    prev_yes_bid REAL DEFAULT 0,
    prev_price REAL DEFAULT 0,
    result TEXT DEFAULT '',
    settlement_value REAL DEFAULT NULL,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS events (
    event_ticker TEXT PRIMARY KEY,
    series_ticker TEXT DEFAULT '',
    title TEXT DEFAULT '',
    sub_title TEXT DEFAULT '',
    category TEXT DEFAULT '',
    status TEXT DEFAULT 'open',
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS trades (
    trade_id TEXT PRIMARY KEY,
    ticker TEXT NOT NULL,
    event_ticker TEXT DEFAULT '',
    count_fp REAL DEFAULT 0,
    yes_price REAL DEFAULT 0,
    no_price REAL DEFAULT 0,
    taker_side TEXT DEFAULT '',
    dollar_value REAL DEFAULT 0,
    category TEXT DEFAULT '',
    created_time TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    event_ticker TEXT DEFAULT '',
    title TEXT DEFAULT '',
    category TEXT DEFAULT '',
    signal_type TEXT DEFAULT '',
    direction TEXT DEFAULT '',
    volume_24h REAL DEFAULT 0,
    price REAL DEFAULT 0,
    price_change REAL DEFAULT 0,
    confidence REAL DEFAULT 0,
    discord_sent INTEGER DEFAULT 0,
    resolved INTEGER DEFAULT 0,
    outcome_correct INTEGER DEFAULT NULL,
    resolved_price REAL DEFAULT NULL,
    pnl_estimate REAL DEFAULT NULL,
    resolved_at TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS whale_trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT UNIQUE,
    ticker TEXT NOT NULL,
    event_ticker TEXT DEFAULT '',
    title TEXT DEFAULT '',
    yes_sub_title TEXT DEFAULT '',
    category TEXT DEFAULT '',
    taker_side TEXT DEFAULT '',
    count_fp REAL DEFAULT 0,
    price REAL DEFAULT 0,
    dollar_value REAL DEFAULT 0,
    market_volume REAL DEFAULT 0,
    open_interest REAL DEFAULT 0,
    confidence REAL DEFAULT 0,
    discord_sent INTEGER DEFAULT 0,
    resolved INTEGER DEFAULT 0,
    outcome_correct INTEGER DEFAULT NULL,
    resolved_price REAL DEFAULT NULL,
    pnl_estimate REAL DEFAULT NULL,
    resolved_at TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    volume REAL DEFAULT 0,
    volume_24h REAL DEFAULT 0,
    open_interest REAL DEFAULT 0,
    yes_bid REAL DEFAULT 0,
    last_price REAL DEFAULT 0,
    snapshot_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bot_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_source TEXT NOT NULL,
    signal_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    event_ticker TEXT DEFAULT '',
    title TEXT DEFAULT '',
    category TEXT DEFAULT '',
    direction TEXT NOT NULL,
    action TEXT DEFAULT 'buy',
    target_contracts INTEGER NOT NULL,
    limit_price_cents INTEGER NOT NULL,
    filled_contracts INTEGER DEFAULT 0,
    avg_fill_price_cents REAL DEFAULT NULL,
    cost_usd REAL DEFAULT 0,
    fees_usd REAL DEFAULT 0,
    client_order_id TEXT UNIQUE NOT NULL,
    kalshi_order_id TEXT DEFAULT NULL,
    status TEXT NOT NULL,
    confidence REAL DEFAULT 0,
    edge_pts REAL DEFAULT 0,
    signal_price REAL DEFAULT 0,
    error TEXT DEFAULT NULL,
    resolved INTEGER DEFAULT 0,
    outcome_correct INTEGER DEFAULT NULL,
    settlement_usd REAL DEFAULT NULL,
    pnl_usd REAL DEFAULT NULL,
    mark_price_cents REAL DEFAULT NULL,
    closed_early INTEGER DEFAULT 0,
    balance_before_usd REAL DEFAULT NULL,
    kalshi_env TEXT DEFAULT 'demo',
    created_at TEXT DEFAULT (datetime('now')),
    last_updated TEXT DEFAULT (datetime('now')),
    resolved_at TEXT DEFAULT NULL,
    UNIQUE(signal_source, signal_id, kalshi_env)
);

CREATE TABLE IF NOT EXISTS order_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    kalshi_status TEXT DEFAULT NULL,
    filled_contracts INTEGER DEFAULT NULL,
    fill_cost_cents INTEGER DEFAULT NULL,
    note TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_stats (
    day TEXT NOT NULL,
    kalshi_env TEXT NOT NULL,
    opened INTEGER DEFAULT 0,
    resolved INTEGER DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    realized_pnl_usd REAL DEFAULT 0,
    ending_balance_usd REAL DEFAULT 0,
    last_updated TEXT DEFAULT (datetime('now')),
    PRIMARY KEY(day, kalshi_env)
);

CREATE TABLE IF NOT EXISTS pnl_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT DEFAULT (datetime('now')),
    kalshi_env TEXT DEFAULT 'demo',
    cash_usd REAL NOT NULL,
    portfolio_usd REAL NOT NULL,
    total_usd REAL NOT NULL,
    realized_pnl_usd REAL DEFAULT 0,
    wins INTEGER DEFAULT 0,
    losses INTEGER DEFAULT 0,
    open_positions INTEGER DEFAULT 0
);

-- risk_state: tiny per-(env, kind) persistence for the daily-risk gate.
-- The 180s breach-persistence window used to live only in a module-global
-- dict, so a backend restart mid-breach re-enabled both engines until the
-- timer re-elapsed — restarting the app is exactly what a user does after a
-- losing streak. breach_started_at is unix seconds (wall clock); NULL/absent
-- means no active breach.
CREATE TABLE IF NOT EXISTS risk_state (
    kalshi_env TEXT NOT NULL,
    kind TEXT NOT NULL,
    breach_started_at REAL,
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (kalshi_env, kind)
);

CREATE TABLE IF NOT EXISTS crypto15m_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    asset TEXT NOT NULL,
    series TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,                 -- 'up' | 'down' (display)
    direction TEXT NOT NULL,            -- 'yes' | 'no' (Kalshi side bought)
    target_contracts INTEGER NOT NULL,
    filled_contracts INTEGER DEFAULT 0,
    entry_limit_cents INTEGER NOT NULL,
    avg_entry_cents REAL DEFAULT NULL,
    cost_usd REAL DEFAULT 0,
    fees_usd REAL DEFAULT 0,            -- Kalshi trading fees on the entry order
    client_order_id TEXT UNIQUE NOT NULL,
    kalshi_order_id TEXT DEFAULT NULL,
    -- stop-loss exit leg
    exit_client_order_id TEXT DEFAULT NULL,
    exit_kalshi_order_id TEXT DEFAULT NULL,
    exit_limit_cents INTEGER DEFAULT NULL,
    exit_filled_contracts INTEGER DEFAULT 0,
    proceeds_usd REAL DEFAULT NULL,
    exit_fees_usd REAL DEFAULT 0,       -- Kalshi trading fees on the exit order
    -- lifecycle
    status TEXT NOT NULL,               -- dry_run|submitted|filled|exiting|exited|settled|canceled|error
    exit_reason TEXT DEFAULT NULL,      -- 'stop_loss' | 'settlement' | 'unfilled_expired'
    close_time TEXT DEFAULT '',
    confidence REAL DEFAULT 0,          -- favorite prob at entry (×100)
    entry_delta_usd REAL DEFAULT NULL,
    outcome_correct INTEGER DEFAULT NULL,
    settlement_usd REAL DEFAULT NULL,
    pnl_usd REAL DEFAULT NULL,
    resolved INTEGER DEFAULT 0,
    kalshi_env TEXT DEFAULT 'demo',
    dry_run INTEGER DEFAULT 0,
    error TEXT DEFAULT NULL,
    runner_id TEXT DEFAULT '',           -- Multi-Run: which runner opened this row
    created_at TEXT DEFAULT (datetime('now')),
    last_updated TEXT DEFAULT (datetime('now')),
    resolved_at TEXT DEFAULT NULL
);

-- crypto15m_signals: a passive research log for the 15-min crypto
-- strategy. One row per market (quarter window): a decision-point
-- snapshot captured live (favorite side + price + underlying delta a few
-- minutes before close), then the settled outcome filled in afterward.
-- This is what makes the 15m strategy backtestable — independent of
-- whether the user ever enables the executor. No orders, no money.
CREATE TABLE IF NOT EXISTS crypto15m_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    asset TEXT NOT NULL,
    series TEXT DEFAULT '',
    close_time TEXT DEFAULT '',
    observed_at TEXT DEFAULT (datetime('now')),
    mins_left REAL,                    -- minutes to close at the observation
    favorite TEXT,                     -- 'up' | 'down' at the decision point
    favorite_price REAL,               -- favorite mid probability (fraction)
    entry_cost REAL,                   -- cost to BUY the favorite (fraction)
    up_prob REAL,                      -- yes/up mid probability (fraction)
    delta_pct REAL,                    -- abs(open-live)/open underlying move
    open_spot REAL,
    obs_spot REAL,
    macd REAL,                         -- underlying MACD line (1-min closes)
    macd_signal REAL,                  -- MACD signal line
    macd_hist REAL,                    -- MACD histogram = macd - signal
    macd_cross INTEGER,                -- +1 bullish / -1 bearish / 0 no cross
    rsi REAL,                          -- Wilder RSI(14) of the underlying
    resolved INTEGER DEFAULT 0,
    up_won INTEGER DEFAULT NULL,       -- 1 if the up/yes side settled true
    settled_at TEXT DEFAULT NULL,
    kalshi_env TEXT DEFAULT 'demo'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_c15sig_ticker ON crypto15m_signals(ticker);
CREATE INDEX IF NOT EXISTS idx_c15sig_resolved ON crypto15m_signals(resolved, close_time);

-- crypto15m_ticks: high-frequency companion to crypto15m_signals. One
-- row per active 15-min market every ~25s across the WHOLE window (not
-- just the decision point), so strategies can be tested for entry
-- timing, quote staleness vs spot, and maker-fill behaviour. Outcomes
-- come from joining crypto15m_signals on ticker. Pruned by
-- cleanup_old_data after `_C15_TICKS_KEEP_DAYS`.
CREATE TABLE IF NOT EXISTS crypto15m_ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    asset TEXT NOT NULL,
    observed_at TEXT DEFAULT (datetime('now')),
    mins_left REAL,
    yes_bid REAL,                      -- fraction 0..1
    yes_ask REAL,                      -- fraction 0..1
    up_prob REAL,                      -- mid, fraction 0..1
    spot REAL,                         -- live underlying USD
    open_spot REAL,                    -- quarter-open underlying USD
    delta_pct REAL,                    -- abs(open-live)/open
    macd REAL,                         -- underlying MACD line (1-min closes)
    macd_signal REAL,                  -- MACD signal line
    macd_hist REAL,                    -- MACD histogram = macd - signal
    macd_cross INTEGER,                -- +1 bullish / -1 bearish / 0 no cross
    rsi REAL,                          -- Wilder RSI(14) of the underlying
    kalshi_env TEXT DEFAULT 'demo'
);
CREATE INDEX IF NOT EXISTS idx_c15tick_ticker ON crypto15m_ticks(ticker, observed_at);
CREATE INDEX IF NOT EXISTS idx_c15tick_time ON crypto15m_ticks(observed_at);

-- Kalshi perpetual futures (margin API) market data. Prices are INTEGER
-- micro-dollars (1 = $0.000001; perp tick is $0.0001, wire allows 6dp) and
-- counts INTEGER centi-contracts (1 = 0.01 contracts) — exact fixed-point,
-- parsed via Decimal at the wire boundary, never float (this codebase's
-- cents-vs-dollars history earned that rule). Funding rates stay REAL.
-- kalshi_env defaults 'production': the public REST recorder path always
-- reads prod (unauthenticated) regardless of the trading env.

-- (perp_ticks / perp_trades / perp_candles / perp_funding / perp_positions —
-- the perps research recorder + strategy engine's tables — were REMOVED
-- 2026-07-16 with those modules; a migration below drops them. Only the
-- farmer's perp_farm_fills survives.)

-- perp_farm_fills: the volume farmer's own fills (accounting source of truth
-- for volume/fees/realized P&L; deduped on trade_id like perp_trades).
CREATE TABLE IF NOT EXISTS perp_farm_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id TEXT NOT NULL,
    order_id TEXT DEFAULT '',
    ticker TEXT NOT NULL,
    observed_at TEXT DEFAULT (datetime('now')),
    ts_ms INTEGER,
    side TEXT,                                  -- our order side: 'bid' | 'ask'
    count_cc INTEGER NOT NULL,
    price_usd_micro INTEGER NOT NULL,
    fee_usd_micro INTEGER DEFAULT 0,
    is_taker INTEGER DEFAULT 0,
    realized_pnl_usd_micro INTEGER DEFAULT 0,   -- avg-cost realized on this fill
    inventory_after_cc INTEGER,
    kalshi_env TEXT DEFAULT 'production',
    UNIQUE(trade_id, kalshi_env)
);
CREATE INDEX IF NOT EXISTS idx_perpfarm_time ON perp_farm_fills(observed_at);
CREATE INDEX IF NOT EXISTS idx_perpfarm_ticker ON perp_farm_fills(ticker, observed_at);

-- bot_runs: each row is a single launch of the bot (start → stop).
-- This is what powers the user-facing "session P&L" model — every
-- restart starts a fresh run, and `start_balance` is what we benchmark
-- against. Per-run aggregates (P&L, trades opened/won/lost) get
-- updated periodically and finalised on shutdown.
CREATE TABLE IF NOT EXISTS bot_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kalshi_env TEXT NOT NULL DEFAULT 'demo',
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    ended_at TEXT,
    start_cash_usd REAL NOT NULL DEFAULT 0,
    start_portfolio_usd REAL NOT NULL DEFAULT 0,
    start_total_usd REAL NOT NULL DEFAULT 0,
    end_cash_usd REAL,
    end_portfolio_usd REAL,
    end_total_usd REAL,
    pnl_usd REAL DEFAULT 0,
    trades_opened INTEGER DEFAULT 0,
    trades_won INTEGER DEFAULT 0,
    trades_lost INTEGER DEFAULT 0,
    -- Lifetime counters captured at run start. The run's per-session
    -- trade/W/L counts are computed as `current_lifetime - start_lifetime`
    -- on every heartbeat. Without this baseline the heartbeat just
    -- stored lifetime totals into every run, which is why every row in
    -- the History → Run history table looked the same.
    start_trades_opened INTEGER DEFAULT 0,
    start_trades_won INTEGER DEFAULT 0,
    start_trades_lost INTEGER DEFAULT 0,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_env ON bot_runs(kalshi_env, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_open ON bot_runs(ended_at, kalshi_env);

-- user_scripts: user-authored strategy scripts (the Scripts tab). Code is
-- stored verbatim; `trusted` unlocks full Python (scary-confirmed in the
-- UI); `state_json` is the script's persistent `state` dict snapshotted by
-- the engine so restarts don't fully reset cross-tick memory. A table (not
-- app config) so per-script live P&L joins cleanly against
-- crypto15m_positions.script_id.
-- Standing instructions written by hand in the Terminal: stop losses, take
-- profits and price alerts.
--
-- These are the ONE category of thing in the app that acts without a click at
-- the moment it acts — and that is the entire point of a stop loss, so it is
-- not a contradiction. What makes it honest is that every row here was typed
-- by the user, is listed on one page, and can be cancelled from there. Nothing
-- creates a row in this table except an explicit instruction.
--
-- threshold_cents is in PROBABILITY POINTS, not a percentage of cost. On a
-- market that is already a probability, "get me out if this drops below 30c"
-- is the sentence a trader actually means; "-25%" makes them do arithmetic
-- against a cost basis to find out what price that is.
CREATE TABLE IF NOT EXISTS terminal_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                  -- stop | take | alert
    ticker TEXT NOT NULL,
    title TEXT DEFAULT '',
    side TEXT NOT NULL,                  -- yes | no  (the side being watched/held)
    threshold_cents REAL NOT NULL,
    direction TEXT NOT NULL,             -- below | above
    contracts INTEGER DEFAULT NULL,      -- exits: NULL = the whole position
    status TEXT NOT NULL DEFAULT 'armed',-- armed | triggered | cancelled | error
    note TEXT DEFAULT '',
    last_error TEXT DEFAULT NULL,
    last_checked_at TEXT DEFAULT NULL,
    last_price_cents REAL DEFAULT NULL,
    last_price_source TEXT DEFAULT NULL,
    -- Consecutive checks with no usable price. A market with no bid for a
    -- moment is normal and the rule stays armed; one that never comes back is
    -- a rule polling forever, so this drives a bounded liveness check.
    unevaluable_count INTEGER DEFAULT 0,
    triggered_at TEXT DEFAULT NULL,
    triggered_order_id TEXT DEFAULT NULL,
    kalshi_env TEXT NOT NULL DEFAULT 'demo',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_scripts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    code TEXT NOT NULL,
    enabled INTEGER DEFAULT 0,
    trusted INTEGER DEFAULT 0,
    notes TEXT DEFAULT '',
    state_json TEXT DEFAULT '{}',
    last_error TEXT DEFAULT NULL,
    last_error_at TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Every AI fair value (in-app panel or an MCP agent), held until the market
-- settles and then scored against the market mid AT THE TIME it was made.
-- The mid/bid/ask are NULL when that side was absent — a forecast made with no
-- two-sided quote has no market price to beat, and is left out of the
-- head-to-head rather than compared against an invented 50c.
CREATE TABLE IF NOT EXISTS ai_forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT DEFAULT (datetime('now')),
    kalshi_env TEXT DEFAULT '',
    ticker TEXT NOT NULL,
    title TEXT DEFAULT '',
    source TEXT NOT NULL,                -- panel | mcp
    model TEXT DEFAULT '',
    prob_yes REAL NOT NULL,              -- 0.01..0.99
    market_mid_cents REAL DEFAULT NULL,
    yes_bid_cents REAL DEFAULT NULL,
    yes_ask_cents REAL DEFAULT NULL,
    close_time TEXT DEFAULT NULL,
    rationale TEXT DEFAULT '',
    outcome REAL DEFAULT NULL,           -- YES payout 0..1; NULL = unsettled
    resolved_at TEXT DEFAULT NULL,
    last_checked_at TEXT DEFAULT NULL
);

-- The agents' paper book: real order books, imaginary money. buy/sell rows are
-- simulated immediate-or-cancel fills; settle rows pay out at the real result.
CREATE TABLE IF NOT EXISTS paper_fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT DEFAULT (datetime('now')),
    kalshi_env TEXT DEFAULT '',
    ticker TEXT NOT NULL,
    title TEXT DEFAULT '',
    side TEXT NOT NULL,                  -- yes | no
    kind TEXT NOT NULL,                  -- buy | sell | settle
    contracts INTEGER NOT NULL,
    price_cents REAL NOT NULL,
    fee_usd REAL NOT NULL DEFAULT 0,
    cash_delta_usd REAL NOT NULL,
    forecast_id INTEGER DEFAULT NULL,
    client TEXT DEFAULT ''
);

-- Every order an MCP agent attempted, refused ones included. This is both the
-- audit trail the AI Agents page shows and the ledger the daily spend cap and
-- "it may only touch what it opened" rails are computed from.
CREATE TABLE IF NOT EXISTS mcp_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT DEFAULT (datetime('now')),
    kalshi_env TEXT DEFAULT '',
    mode TEXT NOT NULL,                  -- paper | live
    client TEXT DEFAULT '',
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    action TEXT NOT NULL,
    count INTEGER NOT NULL,
    price_cents REAL NOT NULL,
    forecast_id INTEGER DEFAULT NULL,
    committed_usd REAL DEFAULT NULL,     -- worst-case outlay of a buy, fees in
    ok INTEGER NOT NULL DEFAULT 0,
    order_id TEXT DEFAULT NULL,
    filled INTEGER DEFAULT NULL,
    avg_fill_cents REAL DEFAULT NULL,
    message TEXT DEFAULT '',
    -- NULL for orders that went straight through; pending | deciding |
    -- approved | rejected | expired | failed when the user approves live
    -- agent orders one by one.
    status TEXT DEFAULT NULL
);

-- Everything an agent did that is not an order: scripts saved or switched,
-- settings changed — and every refusal. Orders have mcp_orders.
CREATE TABLE IF NOT EXISTS mcp_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT DEFAULT (datetime('now')),
    client TEXT DEFAULT '',
    tool TEXT NOT NULL,
    ok INTEGER NOT NULL DEFAULT 0,
    summary TEXT DEFAULT ''
);

-- One row per Autopilot session: what it cost and what it did. The token
-- columns are what the daily budget is enforced from.
CREATE TABLE IF NOT EXISTS autopilot_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT DEFAULT NULL,
    trigger TEXT DEFAULT 'schedule',     -- schedule | manual
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    status TEXT DEFAULT 'running',       -- running | ok | steps | budget | stopped | error
    steps INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT NULL,          -- NULL where the provider publishes no price
    summary TEXT DEFAULT '',
    tool_log TEXT DEFAULT '[]',
    error TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_aif_pending ON ai_forecasts(outcome, ticker);
CREATE INDEX IF NOT EXISTS idx_paper_ticker ON paper_fills(ticker, side);
CREATE INDEX IF NOT EXISTS idx_mcp_orders_day ON mcp_orders(mode, created_at);
CREATE INDEX IF NOT EXISTS idx_termrules_armed ON terminal_rules(status, kalshi_env);
CREATE INDEX IF NOT EXISTS idx_termrules_ticker ON terminal_rules(ticker, status);
CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker);
CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(created_time DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_time ON alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_ticker ON alerts(ticker, direction, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_whale_trade_id ON whale_trades(trade_id);
CREATE INDEX IF NOT EXISTS idx_whale_cat ON whale_trades(category, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_whale_convergence ON whale_trades(ticker, taker_side, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_snapshots ON market_snapshots(ticker, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_markets_vol ON markets(volume DESC);
CREATE INDEX IF NOT EXISTS idx_bp_status ON bot_positions(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_bp_ticker ON bot_positions(ticker, direction, status);
CREATE INDEX IF NOT EXISTS idx_bp_resolved ON bot_positions(resolved, status);
CREATE INDEX IF NOT EXISTS idx_bp_created ON bot_positions(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_oe_pos ON order_events(position_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pnl_at ON pnl_snapshots(at DESC);
CREATE INDEX IF NOT EXISTS idx_pnl_env_at ON pnl_snapshots(kalshi_env, at);
CREATE INDEX IF NOT EXISTS idx_c15_open ON crypto15m_positions(resolved, status);
CREATE INDEX IF NOT EXISTS idx_c15_asset ON crypto15m_positions(asset, kalshi_env, resolved);
-- the executor tick reads errored/stopped ticker sets every ~4s; without this
-- both are full-table DISTINCT scans that grow with history
CREATE INDEX IF NOT EXISTS idx_c15_env_status ON crypto15m_positions(kalshi_env, status);
CREATE INDEX IF NOT EXISTS idx_c15_env_exit ON crypto15m_positions(kalshi_env, exit_reason);
-- NOTE: idx_c15_runner (on the added runner_id column) is created in the
-- migration block below, AFTER the ALTER — an existing DB whose table predates
-- runner_id would fail this whole schema script if the index lived here.
"""


def _to_float(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(SCHEMA)
        for migration in [
            "ALTER TABLE bot_positions ADD COLUMN closed_early INTEGER DEFAULT 0",
            "ALTER TABLE bot_positions ADD COLUMN mark_price_cents REAL DEFAULT NULL",
            "ALTER TABLE alerts ADD COLUMN yes_sub_title TEXT DEFAULT ''",
            "ALTER TABLE bot_runs ADD COLUMN start_trades_opened INTEGER DEFAULT 0",
            "ALTER TABLE bot_runs ADD COLUMN start_trades_won INTEGER DEFAULT 0",
            "ALTER TABLE bot_runs ADD COLUMN start_trades_lost INTEGER DEFAULT 0",
            "ALTER TABLE crypto15m_signals ADD COLUMN macd REAL",
            "ALTER TABLE crypto15m_signals ADD COLUMN macd_signal REAL",
            "ALTER TABLE crypto15m_signals ADD COLUMN macd_hist REAL",
            "ALTER TABLE crypto15m_signals ADD COLUMN macd_cross INTEGER",
            "ALTER TABLE crypto15m_signals ADD COLUMN rsi REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN macd REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN macd_signal REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN macd_hist REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN macd_cross INTEGER",
            "ALTER TABLE crypto15m_ticks ADD COLUMN rsi REAL",
            "ALTER TABLE crypto15m_positions ADD COLUMN fees_usd REAL DEFAULT 0",
            "ALTER TABLE crypto15m_positions ADD COLUMN exit_fees_usd REAL DEFAULT 0",
            "ALTER TABLE crypto15m_ticks ADD COLUMN strike REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN delta_signed_pct REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN sigma1m REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN model_prob REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN edge_net_cents REAL",
            "ALTER TABLE crypto15m_signals ADD COLUMN strike REAL",
            "ALTER TABLE crypto15m_signals ADD COLUMN model_prob REAL",
            "ALTER TABLE crypto15m_signals ADD COLUMN edge_net_cents REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN settle_prints INTEGER",
            "ALTER TABLE crypto15m_ticks ADD COLUMN no_ask REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN spot_source TEXT",
            "ALTER TABLE crypto15m_ticks ADD COLUMN vwap1h REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN ema12 REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN sma20 REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN sma50 REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN price_vs_vwap_pct REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN ema12_vs_sma20_pct REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN ema1_vs_sma5_pct REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN velocity1m_pct REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN change5m_pct REAL",
            "ALTER TABLE crypto15m_ticks ADD COLUMN change15m_pct REAL",
            "ALTER TABLE crypto15m_positions ADD COLUMN strategy TEXT DEFAULT ''",
            "ALTER TABLE crypto15m_positions ADD COLUMN runner_id TEXT DEFAULT ''",
            "CREATE INDEX IF NOT EXISTS idx_c15_runner ON crypto15m_positions(kalshi_env, runner_id, resolved)",
            "ALTER TABLE crypto15m_positions ADD COLUMN mgmt_config TEXT",
            "ALTER TABLE terminal_rules ADD COLUMN unevaluable_count INTEGER DEFAULT 0",
            "DROP TABLE IF EXISTS crypto15m_ticks_hf",
            "DROP TABLE IF EXISTS perp_ticks",
            "DROP TABLE IF EXISTS perp_trades",
            "DROP TABLE IF EXISTS perp_candles",
            "DROP TABLE IF EXISTS perp_funding",
            "DROP TABLE IF EXISTS perp_positions",
            "ALTER TABLE crypto15m_positions ADD COLUMN script_id TEXT DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN tp_pct REAL DEFAULT NULL",
            "ALTER TABLE crypto15m_positions ADD COLUMN sl_cents INTEGER DEFAULT NULL",
            "ALTER TABLE bot_positions ADD COLUMN script_id TEXT DEFAULT NULL",
            "ALTER TABLE user_scripts ADD COLUMN author TEXT DEFAULT NULL",
            "ALTER TABLE mcp_orders ADD COLUMN status TEXT DEFAULT NULL",
        ]:
            try:
                conn.execute(migration)
            except sqlite3.OperationalError:
                pass


def factory_reset(*, wipe_markets: bool = False) -> dict:
    backup_research()
    targets = [
        "bot_positions",
        "bot_runs",
        "pnl_snapshots",
        "daily_stats",
        "order_events",
        "alerts",
        "whale_trades",
        "crypto15m_positions",
        "crypto15m_signals",
        "crypto15m_ticks",
        "perp_farm_fills",
        "terminal_rules",
        "paper_fills",
        "mcp_orders",
        "mcp_actions",
        "autopilot_runs",
    ]
    if wipe_markets:
        targets.extend(["markets", "events", "trades", "market_snapshots"])

    summary: dict[str, int] = {}
    errors: dict[str, str] = {}

    for t in targets:
        try:
            with get_db() as conn:
                cur = conn.execute(f"SELECT COUNT(*) FROM {t}")
                count = int(cur.fetchone()[0])
                conn.execute(f"DELETE FROM {t}")
                summary[t] = count
        except sqlite3.OperationalError as e:
            errors[t] = str(e)
            summary[t] = -1

    try:
        with get_db() as conn:
            conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN "
                "('bot_positions','bot_runs','pnl_snapshots',"
                "'daily_stats','order_events','alerts','whale_trades',"
                "'crypto15m_positions','crypto15m_signals','crypto15m_ticks',"
                "'perp_farm_fills',"
                "'markets','events','trades','market_snapshots')",
            )
    except sqlite3.OperationalError:
        pass

    try:
        conn = sqlite3.connect(str(db_path()), timeout=30)
        conn.isolation_level = None
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("VACUUM")
        except sqlite3.OperationalError:
            pass
        conn.close()
    except sqlite3.OperationalError:
        pass

    if errors:
        summary["_errors"] = errors
    return summary




def upsert_market(conn, market: dict) -> None:
    conn.execute(
        """
        INSERT INTO markets (ticker, event_ticker, series_ticker, title, yes_sub_title,
            category, status, close_time, volume, volume_24h, open_interest,
            yes_bid, yes_ask, last_price, prev_yes_bid, prev_price,
            result, settlement_value, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticker) DO UPDATE SET
            event_ticker=excluded.event_ticker,
            series_ticker=excluded.series_ticker,
            title=COALESCE(excluded.title, title),
            yes_sub_title=COALESCE(excluded.yes_sub_title, yes_sub_title),
            category=COALESCE(NULLIF(excluded.category,''), category),
            status=excluded.status,
            close_time=excluded.close_time,
            prev_yes_bid=markets.yes_bid,
            prev_price=markets.last_price,
            volume=excluded.volume,
            volume_24h=excluded.volume_24h,
            open_interest=excluded.open_interest,
            yes_bid=excluded.yes_bid,
            yes_ask=excluded.yes_ask,
            last_price=excluded.last_price,
            result=excluded.result,
            settlement_value=excluded.settlement_value,
            last_updated=excluded.last_updated
        """,
        (
            market.get("ticker", ""),
            market.get("event_ticker", ""),
            market.get("series_ticker", ""),
            market.get("title", ""),
            market.get("yes_sub_title", ""),
            market.get("category", ""),
            market.get("status", "open"),
            market.get("close_time", ""),
            _to_float(market.get("volume", 0)),
            _to_float(market.get("volume_24h", 0)),
            _to_float(market.get("open_interest", 0)),
            _to_float(market.get("yes_bid", 0)),
            _to_float(market.get("yes_ask", 0)),
            _to_float(market.get("last_price", 0)),
            0,
            0,
            market.get("result", ""),
            _to_float(market.get("settlement_value")) if market.get("settlement_value") is not None else None,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def get_market(conn, ticker: str) -> dict | None:
    row = conn.execute("SELECT * FROM markets WHERE ticker = ?", (ticker,)).fetchone()
    return dict(row) if row else None


def get_active_markets(conn, min_volume: float = 0, limit: int = 500) -> list:
    rows = conn.execute(
        "SELECT * FROM markets WHERE status IN ('active','open') AND volume >= ? "
        "ORDER BY volume DESC LIMIT ?",
        (min_volume, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_event(conn, event: dict) -> None:
    conn.execute(
        """
        INSERT INTO events (event_ticker, series_ticker, title, sub_title, category, status, last_updated)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_ticker) DO UPDATE SET
            series_ticker=excluded.series_ticker,
            title=COALESCE(excluded.title, title),
            sub_title=COALESCE(excluded.sub_title, sub_title),
            category=COALESCE(NULLIF(excluded.category,''), category),
            status=excluded.status,
            last_updated=excluded.last_updated
        """,
        (
            event.get("event_ticker", ""),
            event.get("series_ticker", ""),
            event.get("title", ""),
            event.get("sub_title", ""),
            event.get("category", ""),
            event.get("status", "open"),
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def trade_exists(conn, trade_id: str) -> bool:
    return (
        conn.execute("SELECT 1 FROM trades WHERE trade_id = ?", (trade_id,)).fetchone()
        is not None
    )


def insert_trade(conn, trade: dict) -> bool:
    try:
        conn.execute(
            """
            INSERT INTO trades (trade_id, ticker, event_ticker, count_fp, yes_price,
                no_price, taker_side, dollar_value, category, created_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.get("trade_id", ""),
                trade.get("ticker", ""),
                trade.get("event_ticker", ""),
                _to_float(trade.get("count_fp", 0)),
                _to_float(trade.get("yes_price", 0)),
                _to_float(trade.get("no_price", 0)),
                trade.get("taker_side", ""),
                _to_float(trade.get("dollar_value", 0)),
                trade.get("category", ""),
                trade.get("created_time", ""),
            ),
        )
        return True
    except sqlite3.IntegrityError:
        return False




def insert_alert(conn, alert: dict) -> int:
    cur = conn.execute(
        """
        INSERT INTO alerts (ticker, event_ticker, title, yes_sub_title, category, signal_type,
            direction, volume_24h, price, price_change, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            alert.get("ticker", ""),
            alert.get("event_ticker", ""),
            alert.get("title", ""),
            alert.get("yes_sub_title", ""),
            alert.get("category", ""),
            alert.get("signal_type", ""),
            alert.get("direction", ""),
            alert.get("volume_24h", 0),
            alert.get("price", 0),
            alert.get("price_change", 0),
            alert.get("confidence", 0),
        ),
    )
    return cur.lastrowid


def mark_alert_discord_sent(conn, alert_id: int) -> None:
    conn.execute("UPDATE alerts SET discord_sent = 1 WHERE id = ?", (alert_id,))


def recent_alert_exists(
    conn, ticker: str, signal_type: str, direction: str, cooldown_minutes: int = 30
) -> bool:
    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
    ).strftime("%Y-%m-%d %H:%M:%S")
    row = conn.execute(
        """
        SELECT 1 FROM alerts
        WHERE ticker = ? AND signal_type = ? AND direction = ? AND created_at >= ?
        """,
        (ticker, signal_type, direction, cutoff),
    ).fetchone()
    return row is not None


def fetch_tradeable_momentum_signals(
    conn,
    *,
    min_confidence: float,
    max_age_sec: int,
    allowed_types: list[str],
    seen_ids: set[int],
    limit: int = 50,
) -> list[dict]:
    if not allowed_types:
        return []
    placeholders = ",".join("?" for _ in allowed_types)
    rows = conn.execute(
        f"""SELECT a.* FROM alerts a
            WHERE a.confidence >= ?
              AND a.resolved = 0
              AND (julianday('now') - julianday(a.created_at)) * 86400 <= ?
              AND a.signal_type IN ({placeholders})
            ORDER BY a.created_at DESC
            LIMIT ?""",
        [min_confidence, max_age_sec, *allowed_types, limit * 2],
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        if int(d["id"]) in seen_ids:
            continue
        out.append(d)
        if len(out) >= limit:
            break
    return out




def whale_trade_exists(conn, trade_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM whale_trades WHERE trade_id = ?", (trade_id,)
        ).fetchone()
        is not None
    )


def insert_whale_trade(conn, trade: dict) -> int:
    try:
        cur = conn.execute(
            """
            INSERT INTO whale_trades
                (trade_id, ticker, event_ticker, title, yes_sub_title, category, taker_side,
                 count_fp, price, dollar_value, market_volume, open_interest, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade.get("trade_id", ""),
                trade.get("ticker", ""),
                trade.get("event_ticker", ""),
                trade.get("title", ""),
                trade.get("yes_sub_title", ""),
                trade.get("category", ""),
                trade.get("taker_side", ""),
                _to_float(trade.get("count_fp", 0)),
                _to_float(trade.get("price", 0)),
                _to_float(trade.get("dollar_value", 0)),
                _to_float(trade.get("market_volume", 0)),
                _to_float(trade.get("open_interest", 0)),
                trade.get("confidence", 0),
            ),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return 0


def mark_whale_discord_sent(conn, whale_id: int) -> None:
    conn.execute("UPDATE whale_trades SET discord_sent = 1 WHERE id = ?", (whale_id,))


def fetch_tradeable_whale_signals(
    conn,
    *,
    min_confidence: float,
    max_age_sec: int,
    seen_ids: set[int],
    limit: int = 50,
) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM whale_trades
           WHERE confidence >= ?
             AND resolved = 0
             AND (julianday('now') - julianday(created_at)) * 86400 <= ?
           ORDER BY created_at DESC
           LIMIT ?""",
        (min_confidence, max_age_sec, limit * 2),
    ).fetchall()
    out: list[dict] = []
    for r in rows:
        d = dict(r)
        if int(d["id"]) in seen_ids:
            continue
        out.append(d)
        if len(out) >= limit:
            break
    return out


def get_recent_whales_for_convergence(conn, hours: int = 2) -> dict:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    rows = conn.execute(
        """
        SELECT ticker, taker_side, dollar_value, confidence, price,
               count_fp, title, category, created_at,
               id, event_ticker, market_volume
        FROM whale_trades WHERE created_at >= ?
        ORDER BY created_at DESC
        """,
        (cutoff,),
    ).fetchall()
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        key = (r[0], r[1])
        groups.setdefault(key, []).append(
            {
                "dollar_value": r[2],
                "confidence": r[3],
                "price": r[4],
                "count_fp": r[5],
                "title": r[6],
                "category": r[7],
                "created_at": r[8],
                "id": r[9],
                "event_ticker": r[10],
                "market_volume": r[11],
            }
        )
    return groups




def save_snapshot(conn, ticker: str, market: dict) -> None:
    conn.execute(
        """INSERT INTO market_snapshots (ticker, volume, volume_24h, open_interest, yes_bid, last_price)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            ticker,
            _to_float(market.get("volume", 0)),
            _to_float(market.get("volume_24h", 0)),
            _to_float(market.get("open_interest", 0)),
            _to_float(market.get("yes_bid", 0)),
            _to_float(market.get("last_price", 0)),
        ),
    )


def get_previous_snapshot(conn, ticker: str) -> dict | None:
    row = conn.execute(
        """SELECT * FROM market_snapshots WHERE ticker = ?
           ORDER BY snapshot_at DESC LIMIT 1 OFFSET 1""",
        (ticker,),
    ).fetchone()
    return dict(row) if row else None


def get_previous_snapshots_bulk(conn, tickers) -> dict:
    out: dict[str, dict] = {}
    uniq = [t for t in dict.fromkeys(tickers) if t]
    CHUNK = 400
    for i in range(0, len(uniq), CHUNK):
        chunk = uniq[i:i + CHUNK]
        placeholders = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"""SELECT ticker, volume_24h, yes_bid, last_price FROM (
                   SELECT ticker, volume_24h, yes_bid, last_price,
                          ROW_NUMBER() OVER (
                              PARTITION BY ticker ORDER BY snapshot_at DESC, id DESC
                          ) AS rn
                   FROM market_snapshots
                   WHERE ticker IN ({placeholders})
               ) WHERE rn = 2""",
            chunk,
        ).fetchall()
        for r in rows:
            out[r["ticker"]] = dict(r)
    return out




def get_unresolved_alerts(conn, days: int = 30) -> list:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    rows = conn.execute(
        """SELECT id, ticker, direction, price, created_at
           FROM alerts WHERE resolved = 0 AND created_at >= ?""",
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_unresolved_whale_trades(conn, days: int = 30) -> list:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    rows = conn.execute(
        """SELECT id, ticker, taker_side, price, dollar_value, created_at
           FROM whale_trades WHERE resolved = 0 AND created_at >= ?""",
        (cutoff,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_alert_resolved(
    conn, alert_id: int, correct: bool, resolved_price: float, pnl_est: float
) -> None:
    conn.execute(
        """UPDATE alerts SET resolved = 1, outcome_correct = ?, resolved_price = ?,
              pnl_estimate = ?, resolved_at = ? WHERE id = ?""",
        (
            1 if correct else 0,
            resolved_price,
            pnl_est,
            datetime.now(timezone.utc).isoformat(),
            alert_id,
        ),
    )


def mark_whale_resolved(
    conn, trade_id: int, correct: bool, resolved_price: float, pnl_est: float
) -> None:
    conn.execute(
        """UPDATE whale_trades SET resolved = 1, outcome_correct = ?, resolved_price = ?,
              pnl_estimate = ?, resolved_at = ? WHERE id = ?""",
        (
            1 if correct else 0,
            resolved_price,
            pnl_est,
            datetime.now(timezone.utc).isoformat(),
            trade_id,
        ),
    )




def insert_bot_position(conn, row: dict) -> int:
    cur = conn.execute(
        """
        INSERT INTO bot_positions (
            signal_source, signal_id, ticker, event_ticker, title, category,
            direction, action, target_contracts, limit_price_cents,
            filled_contracts, avg_fill_price_cents, cost_usd,
            client_order_id, kalshi_order_id, status,
            confidence, edge_pts, signal_price, error,
            balance_before_usd, kalshi_env
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            row["signal_source"],
            row["signal_id"],
            row["ticker"],
            row.get("event_ticker", ""),
            row.get("title", ""),
            row.get("category", ""),
            row["direction"],
            row.get("action", "buy"),
            int(row["target_contracts"]),
            int(row["limit_price_cents"]),
            int(row.get("filled_contracts", 0)),
            row.get("avg_fill_price_cents"),
            float(row.get("cost_usd", 0.0)),
            row["client_order_id"],
            row.get("kalshi_order_id"),
            row["status"],
            float(row.get("confidence", 0.0)),
            float(row.get("edge_pts", 0.0)),
            float(row.get("signal_price", 0.0)),
            row.get("error"),
            row.get("balance_before_usd"),
            row.get("kalshi_env", "demo"),
        ),
    )
    return cur.lastrowid


def update_bot_position(conn, bot_id: int, **fields) -> None:
    if not fields:
        return
    stamp_last = fields.pop("_stamp_last_updated", True)
    cols, vals = [], []
    for k, v in fields.items():
        cols.append(f"{k}=?")
        vals.append(v)
    if stamp_last:
        cols.append("last_updated=datetime('now')")
    vals.append(bot_id)
    conn.execute(
        f"UPDATE bot_positions SET {', '.join(cols)} WHERE id=?", vals
    )


def log_event(
    conn,
    position_id: int,
    kind: str,
    *,
    kalshi_status: str | None = None,
    filled_contracts: int | None = None,
    fill_cost_cents: int | None = None,
    note: str | None = None,
) -> None:
    conn.execute(
        """INSERT INTO order_events
              (position_id, kind, kalshi_status, filled_contracts,
               fill_cost_cents, note)
           VALUES (?,?,?,?,?,?)""",
        (position_id, kind, kalshi_status, filled_contracts, fill_cost_cents, note),
    )


def count_open_bot_positions(conn, env: str | None = None) -> int:
    sql = (
        "SELECT COUNT(*) FROM bot_positions "
        "WHERE status IN ('submitted','partial','filled') AND resolved=0 "
        "AND COALESCE(signal_source,'') NOT IN ('external','manual')"
    )
    args: tuple = ()
    if env:
        sql += " AND kalshi_env = ?"
        args = (env,)
    return conn.execute(sql, args).fetchone()[0]


def get_market_quotes(conn, tickers) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for t in {x for x in tickers if x}:
        row = conn.execute(
            "SELECT yes_bid, yes_ask, last_price FROM markets WHERE ticker=?",
            (t,),
        ).fetchone()
        if row:
            out[t] = {
                "yes_bid": float(row["yes_bid"] or 0),
                "yes_ask": float(row["yes_ask"] or 0),
                "last_price": float(row["last_price"] or 0),
            }
    return out


def count_new_positions_today(conn, env: str | None = None, offset_min: int = 0) -> int:
    mod = f"{int(offset_min):+d} minutes"
    sql = (
        "SELECT COUNT(*) FROM bot_positions "
        "WHERE date(created_at, ?)=date('now', ?) "
        "AND status IN ('submitted','partial','filled') "
        "AND COALESCE(signal_source,'') != 'external'"
    )
    args: tuple = (mod, mod)
    if env:
        sql += " AND kalshi_env = ?"
        args = (mod, mod, env)
    return conn.execute(sql, args).fetchone()[0]


def recent_resolved_position_exists(
    conn,
    ticker: str,
    direction: str,
    env: str,
    within_hours: int = 24,
) -> bool:
    row = conn.execute(
        """SELECT 1 FROM bot_positions
           WHERE ticker = ? AND direction = ? AND kalshi_env = ?
             AND resolved = 1
             AND resolved_at IS NOT NULL
             AND resolved_at >= datetime('now', ?)
           LIMIT 1""",
        (ticker, direction, env, f"-{int(within_hours)} hours"),
    ).fetchone()
    return row is not None


def find_flat_resolved_position(
    conn, ticker: str, direction: str, env: str, qty: int
) -> dict | None:
    row = conn.execute(
        """SELECT * FROM bot_positions
           WHERE ticker=? AND direction=? AND kalshi_env=?
             AND resolved=1
             AND status != 'dry_run'
             AND COALESCE(pnl_usd, 0)=0
             AND COALESCE(settlement_usd, 0)=0
             AND outcome_correct IS NULL
           ORDER BY (filled_contracts = ?) DESC, resolved_at DESC, id DESC
           LIMIT 1""",
        (ticker, direction, env, int(qty)),
    ).fetchone()
    return dict(row) if row else None


def exists_position_in_event(conn, event_ticker: str, env: str) -> bool:
    if not event_ticker:
        return False
    row = conn.execute(
        """SELECT 1 FROM bot_positions
           WHERE event_ticker=? AND resolved=0 AND kalshi_env=?
             AND status IN ('submitted','partial','filled')
           LIMIT 1""",
        (event_ticker, env),
    ).fetchone()
    return row is not None


def count_positions_in_event(conn, event_ticker: str, env: str) -> int:
    if not event_ticker:
        return 0
    row = conn.execute(
        """SELECT COUNT(*) AS c FROM bot_positions
           WHERE event_ticker=? AND resolved=0 AND kalshi_env=?
             AND status IN ('submitted','partial','filled')""",
        (event_ticker, env),
    ).fetchone()
    return int(row["c"]) if row and row["c"] is not None else 0


def exists_position_in_market(
    conn, ticker: str, direction: str, env: str
) -> bool:
    row = conn.execute(
        """SELECT 1 FROM bot_positions
           WHERE ticker=? AND direction=? AND resolved=0 AND kalshi_env=?
             AND status IN ('submitted','partial','filled')
           LIMIT 1""",
        (ticker, direction, env),
    ).fetchone()
    return row is not None


def current_total_exposure_usd(conn, env: str) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(
              CASE WHEN status='filled' THEN COALESCE(cost_usd, 0)
                   ELSE MAX(COALESCE(cost_usd, 0),
                            COALESCE(target_contracts, 0) * COALESCE(limit_price_cents, 0) / 100.0)
              END
           ), 0) FROM bot_positions
           WHERE resolved=0 AND status IN ('submitted','partial','filled') AND kalshi_env=?""",
        (env,),
    ).fetchone()
    return float(row[0] or 0.0)


def open_filled_cost_usd(conn, env: str) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(cost_usd), 0) FROM bot_positions
           WHERE resolved=0 AND status IN ('filled','partial') AND kalshi_env=?""",
        (env,),
    ).fetchone()
    return float(row[0] or 0.0)


def open_unrealized_pnl_usd(conn, env: str) -> float:
    row = conn.execute(
        """SELECT COALESCE(SUM(
              filled_contracts * mark_price_cents / 100.0 - COALESCE(cost_usd, 0)
           ), 0) FROM bot_positions
           WHERE resolved=0 AND status='filled' AND kalshi_env=?
             AND COALESCE(signal_source,'') != 'manual'
             AND mark_price_cents IS NOT NULL AND filled_contracts > 0""",
        (env,),
    ).fetchone()
    return float(row[0] or 0.0)


def _c15_matched_adjusted_cost(conn, env: str) -> float:
    rows = conn.execute(
        """SELECT ticker, direction,
                  SUM(MAX(0, filled_contracts - COALESCE(exit_filled_contracts, 0))) f,
                  SUM(COALESCE(cost_usd, 0)
                      * MAX(0, filled_contracts - COALESCE(exit_filled_contracts, 0))
                      / filled_contracts) c
           FROM crypto15m_positions
           WHERE resolved=0 AND filled_contracts > 0 AND kalshi_env=?
           GROUP BY ticker, direction""",
        (env,),
    ).fetchall()
    by_ticker: dict[str, dict[str, tuple[int, float]]] = {}
    for r in rows:
        d = by_ticker.setdefault(r["ticker"], {})
        d[r["direction"]] = (int(r["f"] or 0), float(r["c"] or 0.0))
    total = 0.0
    for sides in by_ticker.values():
        fy, cy = sides.get("yes", (0, 0.0))
        fn, cn = sides.get("no", (0, 0.0))
        matched = min(fy, fn)
        total += (cy * (fy - matched) / fy if fy else 0.0)
        total += (cn * (fn - matched) / fn if fn else 0.0)
    return total


def open_crypto15m_filled_cost_usd(conn, env: str) -> float:
    return _c15_matched_adjusted_cost(conn, env)


def get_pending_bot_positions(conn, env: str | None = None) -> list[dict]:
    sql = """SELECT * FROM bot_positions
           WHERE resolved=0
             AND signal_source != 'external'
             AND (
               status IN ('submitted','partial')
               OR (status='filled' AND (cost_usd IS NULL OR cost_usd=0))
               OR (status IN ('canceled','expired','gone','error')
                   AND (cost_usd IS NULL OR cost_usd=0)
                   AND (julianday('now')-julianday(created_at))*86400 < 86400)
             )"""
    args: tuple = ()
    if env:
        sql += " AND kalshi_env = ?"
        args = (env,)
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, args).fetchall()
    return [dict(r) for r in rows]


def get_open_bot_positions(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM bot_positions
           WHERE status IN ('submitted','partial','filled') AND resolved=0
           ORDER BY created_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_unresolved_bot_positions(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM bot_positions
           WHERE resolved=0 AND status IN ('filled','partial','expired','canceled','gone')
           ORDER BY created_at ASC"""
    ).fetchall()
    return [dict(r) for r in rows]


def already_traded_signal_ids(conn, source: str, env: str) -> set[int]:
    rows = conn.execute(
        "SELECT signal_id FROM bot_positions WHERE signal_source=? AND kalshi_env=?",
        (source, env),
    ).fetchall()
    return {int(r["signal_id"]) for r in rows}


def fetch_position_by_id(conn, pos_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM bot_positions WHERE id=?", (pos_id,)
    ).fetchone()
    return dict(row) if row else None




def insert_crypto15m_position(conn, row: dict) -> int:
    cur = conn.execute(
        """INSERT INTO crypto15m_positions (
              asset, series, ticker, side, direction, target_contracts,
              filled_contracts, entry_limit_cents, avg_entry_cents, cost_usd,
              client_order_id, kalshi_order_id, status, exit_reason, close_time,
              confidence, entry_delta_usd, kalshi_env, dry_run, error, strategy,
              runner_id, mgmt_config, script_id, tp_pct, sl_cents
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row["asset"], row["series"], row["ticker"], row["side"],
            row["direction"], int(row["target_contracts"]),
            int(row.get("filled_contracts", 0)),
            int(row["entry_limit_cents"]),
            row.get("avg_entry_cents"),
            float(row.get("cost_usd", 0.0)),
            row["client_order_id"], row.get("kalshi_order_id"),
            row["status"], row.get("exit_reason"), row.get("close_time", ""),
            float(row.get("confidence", 0.0)),
            row.get("entry_delta_usd"),
            row.get("kalshi_env", "demo"),
            1 if row.get("dry_run") else 0,
            row.get("error"),
            row.get("strategy", "") or "",
            row.get("runner_id", "") or "",
            row.get("mgmt_config"),
            row.get("script_id"),
            row.get("tp_pct"),
            row.get("sl_cents"),
        ),
    )
    return cur.lastrowid


def update_crypto15m_position(conn, pid: int, **fields) -> None:
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        cols.append(f"{k}=?")
        vals.append(v)
    cols.append("last_updated=datetime('now')")
    vals.append(pid)
    conn.execute(
        f"UPDATE crypto15m_positions SET {', '.join(cols)} WHERE id=?", vals
    )


def fetch_crypto15m_by_id(conn, pid: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM crypto15m_positions WHERE id=?", (pid,)
    ).fetchone()
    return dict(row) if row else None


def get_open_crypto15m(conn, env: str) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM crypto15m_positions
           WHERE resolved=0 AND kalshi_env=?
           ORDER BY created_at DESC""",
        (env,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_open_crypto15m_by_asset(conn, asset: str, env: str) -> dict | None:
    row = conn.execute(
        """SELECT * FROM crypto15m_positions
           WHERE resolved=0 AND asset=? AND kalshi_env=?
           ORDER BY created_at DESC LIMIT 1""",
        (asset, env),
    ).fetchone()
    return dict(row) if row else None


def count_open_crypto15m(conn, env: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM crypto15m_positions WHERE resolved=0 AND kalshi_env=?",
        (env,),
    ).fetchone()[0]


def crypto15m_errored_tickers(conn, env: str) -> set:
    rows = conn.execute(
        """SELECT DISTINCT ticker FROM crypto15m_positions
           WHERE kalshi_env=? AND status='error' AND ticker IS NOT NULL""",
        (env,),
    ).fetchall()
    return {r["ticker"] for r in rows}


def crypto15m_stopped_tickers(conn, env: str) -> set:
    rows = conn.execute(
        """SELECT DISTINCT ticker FROM crypto15m_positions
           WHERE kalshi_env=? AND exit_reason='stop_loss' AND ticker IS NOT NULL""",
        (env,),
    ).fetchall()
    return {r["ticker"] for r in rows}



def list_user_scripts(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM user_scripts ORDER BY created_at ASC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_user_script(conn, sid: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM user_scripts WHERE id=?", (sid,)
    ).fetchone()
    return dict(row) if row else None


def upsert_user_script(conn, row: dict) -> None:
    conn.execute(
        """INSERT INTO user_scripts (id, name, description, code, enabled,
              trusted, notes, state_json)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(id) DO UPDATE SET
              name=excluded.name, description=excluded.description,
              code=excluded.code, notes=excluded.notes,
              updated_at=datetime('now')""",
        (
            str(row["id"]), str(row.get("name") or "Untitled script"),
            str(row.get("description") or ""), str(row.get("code") or ""),
            1 if row.get("enabled") else 0,
            1 if row.get("trusted") else 0,
            str(row.get("notes") or ""),
            str(row.get("state_json") or "{}"),
        ),
    )


def update_user_script(conn, sid: str, **fields) -> None:
    if not fields:
        return
    cols, vals = [], []
    for k, v in fields.items():
        if k not in ("name", "description", "code", "enabled", "trusted",
                     "notes", "state_json", "last_error", "last_error_at"):
            continue
        cols.append(f"{k}=?")
        vals.append(v)
    if "last_error" in fields and fields["last_error"]:
        cols.append("last_error_at=datetime('now')")
    cols.append("updated_at=datetime('now')")
    vals.append(sid)
    conn.execute(f"UPDATE user_scripts SET {', '.join(cols)} WHERE id=?", vals)


def delete_user_script(conn, sid: str) -> None:
    conn.execute("DELETE FROM user_scripts WHERE id=?", (sid,))


def script_live_stats(conn, env: str) -> dict[str, dict]:
    agg = """SELECT script_id,
                    COUNT(*) AS n,
                    SUM(CASE WHEN resolved=0 THEN 1 ELSE 0 END) AS open_n,
                    SUM(CASE WHEN resolved=1 AND COALESCE(pnl_usd,0) > 0 THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN resolved=1 AND COALESCE(pnl_usd,0) < 0 THEN 1 ELSE 0 END) AS losses,
                    COALESCE(SUM(CASE WHEN resolved=1 THEN pnl_usd ELSE 0 END), 0) AS pnl
             FROM {table}
             WHERE script_id IS NOT NULL AND kalshi_env=? AND target_contracts > 0
                   {live_only}
             GROUP BY script_id"""
    out: dict[str, dict] = {}
    for table, live_only in (
        ("crypto15m_positions", "AND COALESCE(dry_run,0)=0"),
        ("bot_positions", ""),
    ):
        for r in conn.execute(
            agg.format(table=table, live_only=live_only), (env,)
        ).fetchall():
            s = out.setdefault(str(r["script_id"]), {
                "n": 0, "open": 0, "wins": 0, "losses": 0, "pnlUsd": 0.0})
            s["n"] += int(r["n"] or 0)
            s["open"] += int(r["open_n"] or 0)
            s["wins"] += int(r["wins"] or 0)
            s["losses"] += int(r["losses"] or 0)
            s["pnlUsd"] = round(s["pnlUsd"] + float(r["pnl"] or 0.0), 2)
    return out


def open_crypto15m_committed_usd(conn, env: str) -> float:
    filled_cost = _c15_matched_adjusted_cost(conn, env)
    row = conn.execute(
        """SELECT COALESCE(SUM(
              MAX(0, COALESCE(target_contracts, 0) - COALESCE(filled_contracts, 0))
              * COALESCE(entry_limit_cents, 0) / 100.0
           ), 0) FROM crypto15m_positions
           WHERE resolved=0 AND status='submitted' AND kalshi_env=?""",
        (env,),
    ).fetchone()
    return filled_cost + float(row[0] or 0.0)


def recent_crypto15m(conn, env: str, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM crypto15m_positions
           WHERE kalshi_env=?
           ORDER BY created_at DESC LIMIT ?""",
        (env, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def crypto15m_stats(conn, env: str) -> dict:
    row = conn.execute(
        """SELECT
              SUM(CASE WHEN resolved=0 THEN 1 ELSE 0 END) AS open_count,
              SUM(CASE WHEN resolved=1 AND outcome_correct=1 THEN 1 ELSE 0 END) AS wins,
              SUM(CASE WHEN resolved=1 AND outcome_correct=0 THEN 1 ELSE 0 END) AS losses,
              COALESCE(SUM(CASE WHEN resolved=1 THEN pnl_usd END),0) AS realized_pnl,
              COUNT(*) AS total
           FROM crypto15m_positions WHERE kalshi_env=?""",
        (env,),
    ).fetchone()
    return {
        "openCount": int(row["open_count"] or 0),
        "wins": int(row["wins"] or 0),
        "losses": int(row["losses"] or 0),
        "realizedPnlUsd": float(row["realized_pnl"] or 0.0),
        "total": int(row["total"] or 0),
    }


def crypto15m_resolved_for_health(conn, env: str, since_days: int = 90) -> list[dict]:
    rows = conn.execute(
        """SELECT strategy, dry_run, filled_contracts, pnl_usd,
                  avg_entry_cents, resolved_at
           FROM crypto15m_positions
           WHERE kalshi_env=? AND resolved=1 AND filled_contracts>0
             AND pnl_usd IS NOT NULL
             AND resolved_at >= datetime('now', ?)
           ORDER BY resolved_at""",
        (env, f"-{max(1, int(since_days))} days"),
    ).fetchall()
    return [dict(r) for r in rows]


def crypto15m_session_realized_pnl(conn, env: str, since: str | None) -> float:
    if since:
        row = conn.execute(
            """SELECT COALESCE(SUM(pnl_usd), 0) AS pnl
                 FROM crypto15m_positions
                WHERE kalshi_env=? AND resolved=1 AND pnl_usd IS NOT NULL
                  AND resolved_at IS NOT NULL AND resolved_at >= datetime(?)""",
            (env, since),
        ).fetchone()
    else:
        row = conn.execute(
            """SELECT COALESCE(SUM(pnl_usd), 0) AS pnl
                 FROM crypto15m_positions
                WHERE kalshi_env=? AND resolved=1 AND pnl_usd IS NOT NULL""",
            (env,),
        ).fetchone()
    return float(row["pnl"] or 0.0)




def insert_crypto15m_signal(conn, row: dict) -> bool:
    cur = conn.execute(
        """INSERT OR IGNORE INTO crypto15m_signals (
              ticker, asset, series, close_time, mins_left, favorite,
              favorite_price, entry_cost, up_prob, delta_pct, open_spot,
              obs_spot, macd, macd_signal, macd_hist, macd_cross, rsi,
              strike, model_prob, edge_net_cents, kalshi_env
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row["ticker"], row["asset"], row.get("series", ""),
            row.get("close_time", ""), row.get("mins_left"),
            row.get("favorite"), row.get("favorite_price"),
            row.get("entry_cost"), row.get("up_prob"), row.get("delta_pct"),
            row.get("open_spot"), row.get("obs_spot"),
            row.get("macd"), row.get("macd_signal"), row.get("macd_hist"),
            row.get("macd_cross"), row.get("rsi"),
            row.get("strike"), row.get("model_prob"), row.get("edge_net_cents"),
            row.get("kalshi_env", "demo"),
        ),
    )
    return (cur.rowcount or 0) > 0


def unresolved_crypto15m_signals(conn, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM crypto15m_signals
           WHERE resolved=0
           ORDER BY close_time ASC LIMIT ?""",
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


def resolve_crypto15m_signal(conn, ticker: str, up_won: int) -> None:
    conn.execute(
        """UPDATE crypto15m_signals
              SET resolved=1, up_won=?, settled_at=datetime('now')
            WHERE ticker=?""",
        (int(up_won), ticker),
    )


def fetch_resolved_crypto15m_signals(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT * FROM crypto15m_signals
           WHERE resolved=1 AND up_won IS NOT NULL"""
    ).fetchall()
    return [dict(r) for r in rows]


def crypto15m_signal_counts(conn) -> dict:
    row = conn.execute(
        """SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) AS resolved,
              SUM(CASE WHEN resolved=0 THEN 1 ELSE 0 END) AS pending
           FROM crypto15m_signals"""
    ).fetchone()
    return {
        "total": int(row["total"] or 0),
        "resolved": int(row["resolved"] or 0),
        "pending": int(row["pending"] or 0),
    }


_C15_TICKS_KEEP_DAYS = 60


def insert_crypto15m_tick(conn, row: dict) -> None:
    conn.execute(
        """INSERT INTO crypto15m_ticks (
              ticker, asset, mins_left, yes_bid, yes_ask, up_prob,
              spot, open_spot, delta_pct, macd, macd_signal, macd_hist,
              macd_cross, rsi, strike, delta_signed_pct, sigma1m,
              model_prob, edge_net_cents, settle_prints, no_ask, spot_source,
              kalshi_env, vwap1h, ema12, sma20, sma50, price_vs_vwap_pct,
              ema12_vs_sma20_pct, ema1_vs_sma5_pct, velocity1m_pct,
              change5m_pct, change15m_pct
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row["ticker"], row["asset"], row.get("mins_left"),
            row.get("yes_bid"), row.get("yes_ask"), row.get("up_prob"),
            row.get("spot"), row.get("open_spot"), row.get("delta_pct"),
            row.get("macd"), row.get("macd_signal"), row.get("macd_hist"),
            row.get("macd_cross"), row.get("rsi"),
            row.get("strike"), row.get("delta_signed_pct"), row.get("sigma1m"),
            row.get("model_prob"), row.get("edge_net_cents"),
            row.get("settle_prints"), row.get("no_ask"), row.get("spot_source"),
            row.get("kalshi_env", "demo"),
            row.get("vwap1h"), row.get("ema12"), row.get("sma20"), row.get("sma50"),
            row.get("price_vs_vwap_pct"), row.get("ema12_vs_sma20_pct"),
            row.get("ema1_vs_sma5_pct"), row.get("velocity1m_pct"),
            row.get("change5m_pct"), row.get("change15m_pct"),
        ),
    )


def crypto15m_strategy_stats(conn, env: str) -> list[dict]:
    rows = conn.execute(
        """SELECT COALESCE(NULLIF(strategy, ''), 'directional') strategy,
                  COUNT(*) n,
                  SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) wins,
                  SUM(CASE WHEN pnl_usd <= 0 THEN 1 ELSE 0 END) losses,
                  ROUND(SUM(pnl_usd), 4) pnl_usd,
                  ROUND(SUM(COALESCE(fees_usd,0) + COALESCE(exit_fees_usd,0)), 4) fees_usd
           FROM crypto15m_positions
           WHERE kalshi_env=? AND resolved=1 AND filled_contracts>0
             AND dry_run=0 AND pnl_usd IS NOT NULL
           GROUP BY 1 ORDER BY SUM(pnl_usd) DESC""",
        (env,),
    ).fetchall()
    return [dict(r) for r in rows]


def crypto15m_runner_stats(conn, env: str) -> list[dict]:
    rows = conn.execute(
        """SELECT COALESCE(runner_id, '') runner_id,
                  CASE WHEN dry_run=1 THEN 'paper' ELSE 'live' END mode,
                  COUNT(*) n,
                  SUM(CASE WHEN pnl_usd > 0 THEN 1 ELSE 0 END) wins,
                  SUM(CASE WHEN pnl_usd <= 0 THEN 1 ELSE 0 END) losses,
                  ROUND(SUM(pnl_usd), 4) pnl_usd,
                  ROUND(SUM(COALESCE(fees_usd,0) + COALESCE(exit_fees_usd,0)), 4) fees_usd
           FROM crypto15m_positions
           WHERE kalshi_env=? AND resolved=1 AND filled_contracts>0
             AND pnl_usd IS NOT NULL
           GROUP BY 1, 2 ORDER BY SUM(pnl_usd) DESC""",
        (env,),
    ).fetchall()
    out = [dict(r) for r in rows]
    open_rows = conn.execute(
        """SELECT COALESCE(runner_id, '') runner_id,
                  CASE WHEN dry_run=1 THEN 'paper' ELSE 'live' END mode,
                  COUNT(*) open_n
           FROM crypto15m_positions
           WHERE kalshi_env=? AND resolved=0 GROUP BY 1, 2""",
        (env,),
    ).fetchall()
    open_map = {(r["runner_id"], r["mode"]): r["open_n"] for r in open_rows}
    seen = set()
    for o in out:
        key = (o["runner_id"], o["mode"])
        o["open_n"] = open_map.get(key, 0)
        seen.add(key)
    for (rid, mode), n in open_map.items():
        if (rid, mode) not in seen:
            out.append({"runner_id": rid, "mode": mode, "n": 0, "wins": 0,
                        "losses": 0, "pnl_usd": 0.0, "fees_usd": 0.0, "open_n": n})
    return out


def recent_crypto15m_resolved(conn, env: str, limit: int = 200,
                              include_paper: bool = False) -> list[dict]:
    paper_clause = "" if include_paper else "AND dry_run=0"
    rows = conn.execute(
        f"""SELECT * FROM crypto15m_positions
            WHERE kalshi_env=? AND resolved=1 AND filled_contracts>0 {paper_clause}
            ORDER BY resolved_at DESC, id DESC LIMIT ?""",
        (env, int(limit)),
    ).fetchall()
    return [dict(r) for r in rows]


def crypto15m_tick_count(conn) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM crypto15m_ticks").fetchone()[0])


def insert_perp_farm_fill(conn, row: dict) -> bool:
    cur = conn.execute(
        """INSERT OR IGNORE INTO perp_farm_fills
              (trade_id, order_id, ticker, ts_ms, side, count_cc,
               price_usd_micro, fee_usd_micro, is_taker,
               realized_pnl_usd_micro, inventory_after_cc, kalshi_env)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            row.get("trade_id"), row.get("order_id", ""), row.get("ticker"),
            row.get("ts_ms"), row.get("side"), row.get("count_cc"),
            row.get("price_usd_micro"), row.get("fee_usd_micro", 0),
            1 if row.get("is_taker") else 0,
            row.get("realized_pnl_usd_micro", 0),
            row.get("inventory_after_cc"), row.get("kalshi_env"),
        ),
    )
    return bool(cur.rowcount and cur.rowcount > 0)


def perp_farm_fill_seen(conn, trade_id: str, env: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM perp_farm_fills WHERE trade_id=? AND kalshi_env=? LIMIT 1",
        (trade_id, env),
    ).fetchone()
    return row is not None


def perp_farm_stats(conn, env: str, *, day_utc: str | None = None) -> dict:
    where = "kalshi_env=?"
    params: list = [env]
    if day_utc:
        where += " AND observed_at >= ? AND observed_at < datetime(?, '+1 day')"
        params += [f"{day_utc} 00:00:00", f"{day_utc} 00:00:00"]
    row = conn.execute(
        f"""SELECT COUNT(*),
                   COALESCE(SUM(CAST(price_usd_micro AS REAL) * count_cc / 100.0), 0),
                   COALESCE(SUM(fee_usd_micro), 0),
                   COALESCE(SUM(realized_pnl_usd_micro), 0),
                   MAX(observed_at)
            FROM perp_farm_fills WHERE {where}""",
        params,
    ).fetchone()
    return {
        "fills": int(row[0] or 0),
        "volume_usd_micro": int(row[1] or 0),
        "fees_usd_micro": int(row[2] or 0),
        "realized_usd_micro": int(row[3] or 0),
        "lastAt": row[4],
    }


def perp_farm_effective_fee_bps(conn, env: str, *, since_days: int = 30) -> float | None:
    row = conn.execute(
        """SELECT COALESCE(SUM(fee_usd_micro), 0),
                  COALESCE(SUM(CAST(price_usd_micro AS REAL) * ABS(count_cc) / 100.0), 0)
             FROM perp_farm_fills
            WHERE kalshi_env = ? AND is_taker = 0
              AND observed_at >= datetime('now', ?)""",
        (env, f"-{int(since_days)} days"),
    ).fetchone()
    if not row:
        return None
    fee, notional = float(row[0] or 0), float(row[1] or 0)
    if notional <= 0:
        return None
    return (fee / notional) * 10_000.0






def insert_pnl_snapshot(
    conn,
    *,
    cash_usd: float,
    portfolio_usd: float,
    realized_pnl_usd: float,
    wins: int,
    losses: int,
    open_positions: int,
    env: str,
) -> None:
    conn.execute(
        """INSERT INTO pnl_snapshots
              (kalshi_env, cash_usd, portfolio_usd, total_usd, realized_pnl_usd,
               wins, losses, open_positions)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            env,
            float(cash_usd),
            float(portfolio_usd),
            float(cash_usd) + float(portfolio_usd),
            float(realized_pnl_usd),
            int(wins),
            int(losses),
            int(open_positions),
        ),
    )


def get_risk_breach_start(conn, env: str, kind: str) -> float | None:
    row = conn.execute(
        "SELECT breach_started_at FROM risk_state WHERE kalshi_env=? AND kind=?",
        (env, kind),
    ).fetchone()
    if row is None or row[0] is None:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def set_risk_breach_start(
    conn, env: str, kind: str, started_at: float | None
) -> None:
    conn.execute(
        """INSERT INTO risk_state (kalshi_env, kind, breach_started_at, updated_at)
           VALUES (?,?,?,datetime('now'))
           ON CONFLICT(kalshi_env, kind) DO UPDATE SET
             breach_started_at=excluded.breach_started_at,
             updated_at=excluded.updated_at""",
        (env, kind, started_at),
    )


def earliest_pnl_total(conn, env: str) -> float | None:
    row = conn.execute(
        """SELECT total_usd FROM pnl_snapshots
           WHERE kalshi_env = ? AND total_usd > 0
           ORDER BY at ASC LIMIT 1""",
        (env,),
    ).fetchone()
    if row is None:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def first_snapshot_of_today(conn, env: str, offset_min: int = 0) -> dict | None:
    now_local = datetime.utcnow() + timedelta(minutes=int(offset_min))
    day_start_utc = (
        datetime(now_local.year, now_local.month, now_local.day)
        - timedelta(minutes=int(offset_min))
    )
    row = conn.execute(
        """SELECT * FROM pnl_snapshots
           WHERE kalshi_env = ? AND at >= ? AND total_usd > 0
           ORDER BY at ASC LIMIT 1""",
        (env, day_start_utc.strftime("%Y-%m-%d %H:%M:%S")),
    ).fetchone()
    return dict(row) if row else None


def latest_snapshot(conn, env: str) -> dict | None:
    row = conn.execute(
        """SELECT * FROM pnl_snapshots
           WHERE kalshi_env = ?
           ORDER BY at DESC LIMIT 1""",
        (env,),
    ).fetchone()
    return dict(row) if row else None




def start_bot_run(
    conn, *, env: str, cash_usd: float, portfolio_usd: float,
    lifetime_trades: int = 0, lifetime_wins: int = 0, lifetime_losses: int = 0,
) -> int:
    conn.execute(
        """UPDATE bot_runs
           SET ended_at = COALESCE(ended_at, strftime('%Y-%m-%dT%H:%M:%fZ','now')),
               notes    = COALESCE(notes, '') || ' [auto-closed on next start]'
           WHERE kalshi_env = ? AND ended_at IS NULL""",
        (env,),
    )
    total = float(cash_usd) + float(portfolio_usd)
    cur = conn.execute(
        """INSERT INTO bot_runs (
              kalshi_env, start_cash_usd, start_portfolio_usd,
              start_total_usd, end_cash_usd, end_portfolio_usd,
              end_total_usd, pnl_usd,
              start_trades_opened, start_trades_won, start_trades_lost,
              trades_opened, trades_won, trades_lost
           ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 0, 0, 0)""",
        (
            env, float(cash_usd), float(portfolio_usd), total,
            float(cash_usd), float(portfolio_usd), total,
            int(lifetime_trades), int(lifetime_wins), int(lifetime_losses),
        ),
    )
    return int(cur.lastrowid or 0)


def heartbeat_bot_run(
    conn, run_id: int, *, cash_usd: float, portfolio_usd: float,
    lifetime_trades: int = 0, lifetime_wins: int = 0, lifetime_losses: int = 0,
) -> None:
    if not run_id:
        return
    total = float(cash_usd) + float(portfolio_usd)
    conn.execute(
        """UPDATE bot_runs
              SET end_cash_usd = ?,
                  end_portfolio_usd = ?,
                  end_total_usd = ?,
                  pnl_usd = ? - start_total_usd,
                  trades_opened = MAX(0, ? - start_trades_opened),
                  trades_won    = MAX(0, ? - start_trades_won),
                  trades_lost   = MAX(0, ? - start_trades_lost)
            WHERE id = ?""",
        (
            float(cash_usd), float(portfolio_usd), total, total,
            int(lifetime_trades), int(lifetime_wins), int(lifetime_losses),
            int(run_id),
        ),
    )


def end_bot_run(conn, run_id: int) -> None:
    if not run_id:
        return
    conn.execute(
        "UPDATE bot_runs SET ended_at = strftime('%Y-%m-%dT%H:%M:%fZ','now') "
        "WHERE id = ? AND ended_at IS NULL",
        (int(run_id),),
    )


def get_active_run(conn, env: str) -> dict | None:
    row = conn.execute(
        """SELECT * FROM bot_runs
            WHERE kalshi_env = ? AND ended_at IS NULL
            ORDER BY started_at DESC LIMIT 1""",
        (env,),
    ).fetchone()
    return dict(row) if row else None


def get_recent_runs(conn, env: str | None = None, limit: int = 50) -> list[dict]:
    if env:
        rows = conn.execute(
            """SELECT * FROM bot_runs
                WHERE kalshi_env = ?
                ORDER BY started_at DESC LIMIT ?""",
            (env, int(limit)),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM bot_runs ORDER BY started_at DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(r) for r in rows]


def get_pnl_snapshots(
    conn, *, since_hours: int = 168, env: str | None = None,
    max_points: int = 2000,
) -> list[dict]:
    since_hours = max(1, min(int(since_hours), 24 * 365))
    sql = "SELECT * FROM pnl_snapshots WHERE at >= datetime('now', ?)"
    args: list = [f"-{since_hours} hours"]
    if env:
        sql += " AND kalshi_env = ?"
        args.append(env)
    sql += " ORDER BY at ASC"
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    if max_points and len(rows) > max_points:
        stride = -(-len(rows) // max_points)
        sampled = rows[::stride]
        if sampled[-1] is not rows[-1]:
            sampled.append(rows[-1])
        rows = sampled
    return rows


def recent_balance_transition(conn, env: str, within_sec: int = 180) -> bool:
    args = (env, f"-{int(within_sec)} seconds", f"-{int(within_sec)} seconds")
    for table, extra in (("bot_positions", ""),
                         ("crypto15m_positions", "AND dry_run = 0")):
        row = conn.execute(
            f"""SELECT 1 FROM {table}
                WHERE kalshi_env = ? {extra}
                  AND ((resolved_at IS NOT NULL AND resolved_at >= datetime('now', ?))
                    OR (created_at >= datetime('now', ?)
                        AND status IN ('submitted', 'partial', 'filled')))
                LIMIT 1""",
            args,
        ).fetchone()
        if row:
            return True
    return False


def insert_terminal_rule(conn, row: dict) -> int:
    cur = conn.execute(
        """INSERT INTO terminal_rules (
             kind, ticker, title, side, threshold_cents, direction,
             contracts, note, kalshi_env
           ) VALUES (?,?,?,?,?,?,?,?,?)""",
        (row["kind"], row["ticker"], row.get("title", ""), row["side"],
         float(row["threshold_cents"]), row["direction"], row.get("contracts"),
         row.get("note", ""), row["kalshi_env"]),
    )
    return int(cur.lastrowid)


def list_terminal_rules(conn, env: str, *, armed_only: bool = False,
                        limit: int = 300) -> list[dict]:
    sql = "SELECT * FROM terminal_rules WHERE kalshi_env=?"
    args: list = [env]
    if armed_only:
        sql += " AND status='armed'"
    sql += " ORDER BY (status='armed') DESC, created_at DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def update_terminal_rule(conn, rule_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    conn.execute(
        f"UPDATE terminal_rules SET {cols} WHERE id=?",
        [*fields.values(), int(rule_id)],
    )


def claim_terminal_rule(conn, rule_id: int, env: str) -> bool:
    cur = conn.execute(
        "UPDATE terminal_rules SET status='firing' "
        "WHERE id=? AND kalshi_env=? AND status='armed'",
        (int(rule_id), env),
    )
    return cur.rowcount > 0


def cancel_terminal_rule(conn, rule_id: int, env: str) -> bool:
    cur = conn.execute(
        "UPDATE terminal_rules SET status='cancelled' "
        "WHERE id=? AND kalshi_env=? AND status='armed'",
        (int(rule_id), env),
    )
    return cur.rowcount > 0


def manual_positions(
    conn, env: str, *, resolved: bool | None = None, limit: int = 500,
) -> list[dict]:
    sql = ("SELECT * FROM bot_positions "
           "WHERE signal_source='manual' AND kalshi_env=?")
    args: list = [env]
    if resolved is not None:
        sql += " AND resolved=?"
        args.append(1 if resolved else 0)
    sql += " ORDER BY COALESCE(resolved_at, created_at) DESC LIMIT ?"
    args.append(int(limit))
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def find_open_manual_position(conn, ticker: str, side: str, env: str) -> dict | None:
    row = conn.execute(
        """SELECT * FROM bot_positions
           WHERE signal_source='manual' AND ticker=? AND direction=?
             AND kalshi_env=? AND resolved=0
             AND status IN ('submitted','partial','filled')
           ORDER BY created_at DESC LIMIT 1""",
        (ticker, side, env),
    ).fetchone()
    return dict(row) if row else None


def bot_owns_position(conn, ticker: str, side: str, env: str) -> bool:
    row = conn.execute(
        """SELECT 1 FROM bot_positions
           WHERE ticker=? AND direction=? AND kalshi_env=? AND resolved=0
             AND status IN ('submitted','partial','filled')
             AND COALESCE(signal_source,'') NOT IN ('manual','external')
           LIMIT 1""",
        (ticker, side, env),
    ).fetchone()
    return row is not None


def aggregate_stats(conn, env: str | None = None) -> dict:
    cond = ""
    args: list = []
    if env:
        cond = "AND kalshi_env=?"
        args = [env]
    row = conn.execute(
        f"""SELECT
              SUM(CASE WHEN status IN ('submitted','partial') AND resolved=0 THEN 1 ELSE 0 END) AS pending,
              SUM(CASE WHEN status='filled' AND resolved=0 THEN 1 ELSE 0 END) AS open_filled,
              SUM(CASE WHEN resolved=1 AND outcome_correct=1 THEN 1 ELSE 0 END) AS wins,
              SUM(CASE WHEN resolved=1 AND outcome_correct=0 THEN 1 ELSE 0 END) AS losses,
              COALESCE(SUM(CASE WHEN resolved=1 THEN pnl_usd END),0) AS realized_pnl,
              COALESCE(SUM(CASE WHEN resolved=1 AND date(resolved_at)=date('now') THEN pnl_usd END),0) AS today_pnl,
              SUM(CASE WHEN resolved=1 AND outcome_correct=1 AND date(resolved_at)=date('now') THEN 1 ELSE 0 END) AS today_wins,
              SUM(CASE WHEN resolved=1 AND outcome_correct=0 AND date(resolved_at)=date('now') THEN 1 ELSE 0 END) AS today_losses,
              COALESCE(SUM(CASE WHEN resolved=0 AND status IN ('filled','partial') THEN cost_usd END),0) AS open_cost,
              COALESCE(SUM(fees_usd),0) AS fees,
              SUM(CASE WHEN resolved=1 THEN 1 ELSE 0 END) AS resolved_count,
              COUNT(*) AS total_opened
           FROM bot_positions
           WHERE status!='dry_run'
             AND COALESCE(signal_source,'') != 'manual' {cond}""",
        args,
    ).fetchone()
    return {
        "pending": int(row["pending"] or 0),
        "open_filled": int(row["open_filled"] or 0),
        "wins": int(row["wins"] or 0),
        "losses": int(row["losses"] or 0),
        "realized_pnl": float(row["realized_pnl"] or 0.0),
        "today_pnl": float(row["today_pnl"] or 0.0),
        "today_wins": int(row["today_wins"] or 0),
        "today_losses": int(row["today_losses"] or 0),
        "open_cost": float(row["open_cost"] or 0.0),
        "fees": float(row["fees"] or 0.0),
        "resolved_count": int(row["resolved_count"] or 0),
        "total_opened": int(row["total_opened"] or 0),
    }



_DELETE_BATCH = 50_000


def _delete_batched(
    where_sql: str, params: tuple, table: str, *, batch: int = _DELETE_BATCH
) -> int:
    sql = (
        f"DELETE FROM {table} WHERE rowid IN "
        f"(SELECT rowid FROM {table} WHERE {where_sql} LIMIT ?)"
    )
    total = 0
    while True:
        with get_db() as conn:
            n = conn.execute(sql, (*params, batch)).rowcount or 0
        total += n
        if n < batch:
            return total


def cleanup_old_data(
    conn=None, *, trade_hours: int = 48, alert_days: int = 45,
    snapshot_hours: int = 6, pnl_days: int = 45,
    event_days: int = 30, c15_signal_days: int = 60,
) -> int:
    now = datetime.now(timezone.utc)
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    trade_cutoff = (now - timedelta(hours=trade_hours)).strftime("%Y-%m-%d %H:%M:%S")
    alert_cutoff = (now - timedelta(days=alert_days)).strftime("%Y-%m-%d %H:%M:%S")
    snap_cutoff = (now - timedelta(hours=snapshot_hours)).strftime("%Y-%m-%d %H:%M:%S")
    pnl_cutoff = (now - timedelta(days=pnl_days)).strftime("%Y-%m-%d %H:%M:%S")
    settled_cutoff = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
    event_cutoff = (now - timedelta(days=event_days)).strftime("%Y-%m-%d %H:%M:%S")
    c15sig_cutoff = (now - timedelta(days=c15_signal_days)).strftime("%Y-%m-%d %H:%M:%S")

    ticks_cutoff = (now - timedelta(days=_C15_TICKS_KEEP_DAYS)).strftime("%Y-%m-%d %H:%M:%S")

    deleted = 0
    deleted += _delete_batched("created_time < ?", (trade_cutoff,), "trades")
    deleted += _delete_batched("snapshot_at < ?", (snap_cutoff,), "market_snapshots")
    deleted += _delete_batched("observed_at < ?", (ticks_cutoff,), "crypto15m_ticks")
    deleted += _delete_batched("created_at < ?", (event_cutoff,), "order_events")
    deleted += _delete_batched(
        "resolved = 1 AND observed_at < ?", (c15sig_cutoff,), "crypto15m_signals")
    deleted += _delete_batched(
        "status NOT IN ('active','open') AND last_updated < ?", (settled_cutoff,), "markets")
    deleted += _delete_batched(
        "close_time != '' AND close_time < ? AND last_updated < ?",
        (now_iso, settled_cutoff), "markets")
    deleted += _delete_batched("volume < 10 AND volume_24h < 5", (), "markets")
    with get_db() as c:
        deleted += c.execute(
            "DELETE FROM alerts WHERE resolved = 1 AND created_at < ?", (alert_cutoff,)
        ).rowcount or 0
        deleted += c.execute(
            "DELETE FROM whale_trades WHERE resolved = 1 AND created_at < ?", (alert_cutoff,)
        ).rowcount or 0
        deleted += c.execute(
            "DELETE FROM alerts WHERE resolved = 0 AND created_at < ?", (alert_cutoff,)
        ).rowcount or 0
        deleted += c.execute(
            "DELETE FROM whale_trades WHERE resolved = 0 AND created_at < ?", (alert_cutoff,)
        ).rowcount or 0
        deleted += c.execute(
            """DELETE FROM pnl_snapshots WHERE at < ?
               AND id NOT IN (SELECT MIN(id) FROM pnl_snapshots
                              WHERE total_usd > 0 GROUP BY kalshi_env)""",
            (pnl_cutoff,),
        ).rowcount or 0
        deleted += c.execute(
            "DELETE FROM events WHERE last_updated < ?", (event_cutoff,)
        ).rowcount or 0
    return deleted


def _reclaimable_mb() -> float:
    with get_db() as conn:
        ps = conn.execute("PRAGMA page_size").fetchone()[0]
        fl = conn.execute("PRAGMA freelist_count").fetchone()[0]
    return fl * ps / 1e6


def vacuum() -> None:
    conn = sqlite3.connect(str(db_path()), timeout=120)
    conn.isolation_level = None
    try:
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass
        conn.execute("VACUUM")
    finally:
        conn.close()


def backup_research(keep: int = 7) -> str | None:
    try:
        src = str(db_path())
        bdir = os.path.join(os.path.dirname(src), "backups")
        os.makedirs(bdir, exist_ok=True)
        stamp = datetime.utcnow().strftime("%Y%m%d")
        dest = os.path.join(bdir, f"research-{stamp}.db")
        if os.path.exists(dest):
            return dest
        with get_db() as conn:
            out = sqlite3.connect(dest)
            try:
                conn.backup(out)
            finally:
                out.close()
        snaps = sorted(
            f for f in os.listdir(bdir)
            if f.startswith("research-") and f.endswith(".db")
        )
        for old_f in snaps[:-keep]:
            try:
                os.remove(os.path.join(bdir, old_f))
            except OSError:
                pass
        return dest
    except Exception:
        return None


def run_maintenance(*, vacuum_min_free_mb: float = 50.0, force_vacuum: bool = False) -> dict:
    deleted = cleanup_old_data()
    backed_up = backup_research()
    free_mb = _reclaimable_mb()
    vacuumed = False
    if force_vacuum or free_mb >= vacuum_min_free_mb:
        vacuum()
        vacuumed = True
    return {"deleted": deleted, "reclaimable_mb": round(free_mb, 1), "vacuumed": vacuumed,
            "backup": backed_up}
