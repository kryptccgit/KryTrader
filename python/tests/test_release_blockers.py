"""Regression tests for the ten release blockers found by the v6.0.0 audit.

Each test pins ONE defect by the state it produced, not by the code shape. They
live together because they share a theme the rest of the suite was missing: what
the app does when an order is REFUSED, UNCONFIRMED, or answered by a read that
has not caught up yet. Four of the ten blockers lived in exactly that gap.
"""
from __future__ import annotations

import asyncio
import inspect

import pytest

import crossvenue as cv
import crypto15m_trader as ct
import kalshi_api
import kalshi_ws
import terminal
import trader


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def fresh_manual_db(tmp_path, monkeypatch):
    """An empty ledger on the demo env, for the manual buy/sell money paths."""
    import db
    import kalshi_auth
    dbfile = tmp_path / "manual-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    monkeypatch.setattr(kalshi_auth, "_current_env", "paper", raising=False)
    yield



def test_b10_shard_transfer_is_sent_exactly_once(monkeypatch):
    """_signed_request retries on timeout, 5xx and 429 for every method, and
    re-signs each attempt, so Kalshi sees independent valid requests. The
    transfer body carries no idempotency key, so a retry after a lost response
    moves the money a second time. place_limit_order is safe only because it
    mints one client_order_id outside the loop; this had no equivalent."""
    attempts = []

    async def _bal(pin_env=None):
        return {"shard_balances": {0: 500.0, 2: 0.0}}

    async def _req(method, path, **kw):
        attempts.append(path)
        assert kw.get("retry") is False, "the transfer must opt out of retries"
        return {"transfer_id": "t1"}

    monkeypatch.setattr(kalshi_api, "get_balance", _bal)
    monkeypatch.setattr(kalshi_api, "_signed_request", _req)
    run(kalshi_api.transfer_between_shards(
        amount_usd=12.00, source_shard=0, destination_shard=2))
    assert len(attempts) == 1


def test_b10_ordinary_reads_still_retry():
    """The opt-out must be opt-IN only - everything else keeps its retries."""
    sig = inspect.signature(kalshi_api._signed_request)
    assert sig.parameters["retry"].default is True



def test_b6_deci_cent_levels_survive_parsing():
    """The tapered 15m crypto series tick in 0.1c below 10c and above 90c, and
    place_limit_order accepts 0.1..99.9 as tick-valid. The old 1..99 bound threw
    those away: with bids at 99.4/99.2/98.0 the first two vanished and 98.0 was
    reported as best bid, so a stop armed "below 99" sold into a bid that did
    not exist. 6.7% of the repo's 300k recorded candles close in that band."""
    for good in (0.1, 0.6, 0.9, 1.0, 50.0, 99.0, 99.4, 99.9):
        assert terminal.price_cents(good) == good, good
    for absent in (0, 0.0, "0.0000", 100, 100.0, -1, "", None, "x"):
        assert terminal.price_cents(absent) is None, absent


def test_b6_a_deci_cent_book_reports_its_true_best_bid():
    row = terminal.market_row({
        "ticker": "KXBTC15M-X",
        "yes_bid_dollars": "0.9940", "yes_ask_dollars": "0.9960",
    })
    assert row["yesBid"] == 99.4
    assert row["yesAsk"] == 99.6



def test_b5_shared_position_mark_is_converted_not_bound_raw():
    """db.get_market_quotes returns {ticker: {...}} in 0..1 dollars. Binding that
    dict into the REAL mark_price_cents column raised sqlite3.ProgrammingError
    and aborted the whole reconcile pass mid-iteration, every cycle, while two
    local rows shared one Kalshi position - which is what a hand-buy on a market
    the bot already holds produces."""
    quote = {"yes_bid": 0.40, "yes_ask": 0.42, "last_price": 0.41}
    mark = trader._side_mark_cents(quote, "yes")
    assert isinstance(mark, (int, float)) and not isinstance(mark, bool)
    assert mark == pytest.approx(41.0)
    assert trader._side_mark_cents(quote, "no") == pytest.approx(59.0)
    assert trader._side_mark_cents(None, "yes") is None



def _idf(*titles):
    return cv.build_idf([cv.tokens(t) for t in titles])


def test_b4_opposite_directions_never_pair():
    """above/below/over/under are STOPWORDS and lowercase, so they reached
    neither the overlap score nor the proper-noun disqualifier. A threshold and
    its complement scored 1.000 - and their prices sum to ~100c by construction,
    so the panel rendered a permanent maximum-width fake spread."""
    a = "Will Bitcoin be above 120000 on Dec 31 2026"
    b = "Will Bitcoin be below 120000 on Dec 31 2026"
    conf, why = cv.score_pair(a, b, _idf(a, b))
    assert conf < cv.CONFIDENT, (conf, why)
    assert any("opposite directions" in w for w in why)


def test_b4_a_one_sided_negation_never_pairs():
    a = "Will Jerome Powell remain Fed Chair through 2026"
    b = "Will Jerome Powell not remain Fed Chair through 2026"
    conf, why = cv.score_pair(a, b, _idf(a, b))
    assert conf < cv.CONFIDENT, (conf, why)
    assert any("opposite outcome" in w for w in why)


def test_b4_the_same_direction_on_both_sides_still_pairs():
    """The rule fires on a DIFFERENCE. Two venues asking the same threshold
    question must still match, and a range naming both edges states no single
    direction at all rather than a contradictory one."""
    a = "Will Chelsea win the English Premier League"
    b = "Will Chelsea win the 2026-27 English Premier League EPL Championship"
    corpus = [
        a, b,
        "Will Arsenal win the English Premier League",
        "Will Manchester City win the English Premier League",
        "Will Barcelona win the UEFA Champions League",
        "Will Real Madrid win the UEFA Champions League",
        "Will Bitcoin be above 120000 on Dec 31 2026",
        "Will Marco Rubio be the Republican nominee",
        "Will Trump acquire Greenland before 2027",
    ]
    conf, _ = cv.score_pair(a, b, _idf(*corpus))
    assert conf >= cv.CONFIDENT
    assert cv.direction("Will BTC close between 90000 and 120000") is None



def test_b9_the_connect_loop_clears_connected_in_a_finally():
    """The 30s silent-link watchdog exits with a bare `return` from inside the
    `async with`, so a trailing assignment after the block was skipped: the flag
    stayed True with no socket. orderbook() and ticker_quote() gate only on that
    flag with no age component, and get_orderbook prefers the WS book over REST
    for order pricing - so a >=30s-old book was priced against as live."""
    src = inspect.getsource(kalshi_ws._Client._connect_once)
    assert "finally:" in src, "the connect loop must clean up on every exit path"
    finally_block = src.split("finally:", 1)[1]
    assert "self.connected = False" in finally_block
    assert "self._ws = None" in finally_block


def test_b9_a_disconnected_client_serves_nothing():
    c = kalshi_ws._Client()
    c.connected = False
    c.quotes["X"] = {"yes_bid_cents": 41.0}
    assert c.ticker_quote("X") is None



def test_b3_pair_leg_distinguishes_a_broken_lookup_from_a_missing_order():
    """find_order_by_client_id RAISES when the request fails and returns None
    only on a confirmed absence. Collapsing both into None booked a LIVE order
    as a resolved error, and put the ticker in errored_tickers so its partner
    leg was blocked too - leaving an untracked naked-directional clip."""
    src = inspect.getsource(ct._open_pair_leg)
    assert "_lookup_lost_order" in src, "must use the confirming lookup"
    assert "if not lookup_ok:" in src, "an unconfirmed lookup needs its own branch"
    unconfirmed = src.split("if not lookup_ok:", 1)[1].split("row.update", 1)[0]
    assert "_mark_resolved" not in unconfirmed



def test_b2_a_still_resting_order_is_not_booked_canceled():
    """A cancel that 5xx'd or timed out leaves the buy RESTING, and the
    follow-up read then says exactly what an unfilled resting order says:
    status 'resting', fill 0. Booking that as canceled resolved the row, and
    since get_open_crypto15m filters resolved=0 and the main reconcile skips
    the crypto15m series, the order stayed live, filled, and settled with no
    row, no stop-loss and no P&L."""
    assert "resting" not in ct._DEAD_ORDER_STATUSES
    assert "pending" not in ct._DEAD_ORDER_STATUSES
    for dead in ("canceled", "cancelled", "executed", "expired"):
        assert dead in ct._DEAD_ORDER_STATUSES
    src = inspect.getsource(ct._cancel_entry_and_finalize)
    assert "final_dead" in src
    assert "elif read_ok and (final_dead or market_closed):" in src, (
        "a zero-fill read alone is not enough")


def test_b2_a_resting_order_on_a_closed_market_does_terminate():
    """The other half of B2, and the one the first fix missed. Requiring a
    terminal status gave the loop no way to STOP when Kalshi keeps reporting
    'resting': a beta log showed the same order retrying every ~4 seconds
    indefinitely, filling the log with one repeated line. Kalshi stops matching
    at the close, so a resting order on a CLOSED market can never fill again —
    that is the terminating condition a status check alone does not provide."""
    src = inspect.getsource(ct._cancel_entry_and_finalize)
    assert "market_closed" in src
    assert "_CLOSED_ORDER_GRACE_SEC" in src
    assert src.index('if final_filled > 0:') < src.index('market_closed or') \
        if 'market_closed or' in src else True
    assert "_warn_once(" in src


def test_b2_the_poll_warning_is_throttled():
    """A warning inside a ~4s poll is not a warning, it is a denial of service
    on the log file — and on the diagnostics bundle, which carries a fixed
    number of lines and would otherwise be entirely one repeated message."""
    ct._warn_at.clear()
    assert ct._warn_once("k", 60.0) is True
    assert ct._warn_once("k", 60.0) is False, "a 4s poll must not log every pass"
    assert ct._warn_once("other", 60.0) is True, "throttling is per key"



def test_b7_resting_sells_are_counted_against_available_contracts():
    """The oversell guard was a function-local dict rebuilt empty every 3s pass,
    and Kalshi's position does not shrink until a sell FILLS. Hold 100 with a
    take at 70c and a stop at 30c: the take fires for 70, 30 fill, the position
    reads 70, then the stop fires for another 70 - 140 sold against 100 held."""
    src = inspect.getsource(terminal.evaluate_rules)
    assert "resting_sold" in src
    assert "await resting_orders(" in src, "the live book must be read per pass"
    assert "already += resting_sold" in src, \
        "resting size must reduce what a rule may sell"



def test_b8_the_account_total_counts_manual_positions():
    """aggregate_stats deliberately excludes manual rows - it measures the bot.
    But cash comes from Kalshi and DOES fall on a manual fill, so using the
    bot-only figure for the account total made every hand-buy read as an instant
    loss of its full cost. That total feeds the daily stop, so a $60 hand-buy on
    a $500 account tripped a 5% day stop and halted the main engine, the 15m
    engine and every user script, with nothing actually lost."""
    import service
    src = inspect.getsource(service)
    assert "account_open_cost = db.open_filled_cost_usd(conn, env)" in src
    assert "port_usd = account_open_cost + crypto_open_cost" in src
    import db as _db
    assert "!= 'manual'" not in inspect.getsource(_db.open_filled_cost_usd)



def test_p1_a_rejected_webhook_url_is_never_logged_in_full():
    """A Discord webhook's TOKEN is its last path segment, so logging the URL
    logs the credential. urlparse returns hostname=None for a scheme-less
    paste, so the old `or url!r` fallback printed the whole string — at WARNING,
    on every whale/momentum/order/stats event. That line lands in backend.log,
    is pushed to the Logs page, and ships inside the diagnostics bundle, which
    states in the same breath that secrets are never included."""
    import webhook
    secret = "AbCdEfGh-IjKlMnOpQrStUvWxYz_TOKEN"
    for url in (
        f"discord.com/api/webhooks/1234567890/{secret}",
        f"<https://discord.com/api/webhooks/9/{secret}>",
        f"https://evil.example.com/api/webhooks/1/{secret}",
    ):
        described = webhook._describe_url(url)
        assert secret not in described, described
        assert "/api/webhooks/" not in described, described
    assert webhook._describe_url("http://evil.example.com/x") == "http://evil.example.com"


def test_p1_the_scrubber_also_catches_a_webhook_url_by_shape():
    """Defence in depth: the source no longer writes it, but a webhook URL
    logged by anything else (a library, a traceback) must still be caught. It
    was not before — refresh_known_secrets registers only the two bot tokens
    and the Kalshi key, so the by-value pass never saw a settings-file webhook,
    and no shape rule matched it either."""
    import logscrub
    secret = "AbCdEfGh-IjKlMnOpQrStUvWxYz_TOKEN"
    for host in ("discord.com", "discordapp.com"):
        line = f"POST https://{host}/api/webhooks/1234567890/{secret} failed"
        out = logscrub.scrub(line)
        assert secret not in out, out
        assert f"{host}/api/webhooks/1234567890/" in out
        assert logscrub.REDACTED in out



def test_l3_a_partially_filled_manual_order_is_booked_partial():
    """'filled' tells the rest of the app that nothing is still working on the
    book, and three systems act on that: the exposure cap values 'filled' rows
    at cost_usd instead of committed notional (10 of 100 at 50c counted as $5,
    not $50, so the engine over-deployed past its own cap), the pending-order
    poll skips them so nothing watched the live order, and Cancel All selects
    only 'submitted'/'partial' so the flatten button would not touch it. No
    path demoted such a row afterwards."""
    assert terminal._manual_status(3, 10) == "partial"
    assert terminal._manual_status(10, 10) == "filled"
    assert terminal._manual_status(12, 10) == "filled"
    assert terminal._manual_status(0, 10) == "submitted"
    assert terminal._manual_status(None, 10) == "submitted"
    assert terminal._manual_status(5, 0) == "filled"


def test_l3_both_manual_buy_paths_use_the_shared_mapping():
    """The merge path (a second buy on the same market/side) had the same bug,
    and must judge the COMBINED fill against the COMBINED target."""
    src = inspect.getsource(terminal.record_manual_buy)
    assert '"filled" if (filled or 0) > 0' not in src, "the old mapping is gone"
    assert src.count("_manual_status(") == 2, "both the insert and merge paths"



def test_l1_a_partial_exit_books_its_realised_pnl_and_fee(fresh_manual_db, monkeypatch):
    """The partial branch computed `realized` and `exit_fee` and then wrote
    NEITHER to a numeric column - they reached only an order_events note, which
    is never read back for money. So the gain vanished: manual_history sums
    pnl_usd over resolved rows, settlement recomputes P&L off the shrunk basis,
    and the row's recorded fees FELL after paying one. Buy 100 @20c, sell 60
    @90c and let the rest settle NO: about -$8.45 reported on a sequence that
    netted about +$32.50."""
    import db

    terminal.record_manual_buy(
        ticker="KXT-1", side="yes", count=100, price_cents=20,
        client_order_id="m-1", order_id="O1", status="executed",
        filled=100, avg_cents=20.0, fees_usd=1.12, title="t")

    async def _sold(order_id, side, pin_env=None):
        return 60, 90.0
    monkeypatch.setattr(terminal, "_reconcile_fills", _sold)

    run(terminal.record_manual_sell(
        ticker="KXT-1", side="yes", count=60, price_cents=90,
        order_id="O2", status="executed", filled=60))

    exit_fee = terminal._fee_usd(90.0, 60)
    expected = 60 * 0.90 - (20.0 * 60 / 100) - (1.12 * 60 / 100) - exit_fee

    hist = terminal.manual_history()
    assert hist["realizedUsd"] == pytest.approx(round(expected, 2), abs=0.01)
    assert hist["feesUsd"] == pytest.approx(1.12 + exit_fee, abs=0.01)

    with db.get_db() as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT filled_contracts, cost_usd, resolved, pnl_usd "
            "FROM bot_positions ORDER BY id")]
    open_row = next(r for r in rows if not r["resolved"])
    closed = next(r for r in rows if r["resolved"])
    assert open_row["filled_contracts"] == 40
    assert open_row["cost_usd"] == pytest.approx(8.0)
    assert closed["filled_contracts"] == 60
    assert closed["pnl_usd"] == pytest.approx(expected, abs=0.01)


def test_l1_the_closed_clone_is_invisible_to_the_open_position_lookup(
        fresh_manual_db, monkeypatch):
    """It must not become a second row the reconcile pass has to choose between
    - find_open_manual_position filters resolved=0, so a resolved clone is
    never returned."""
    import db

    terminal.record_manual_buy(
        ticker="KXT-2", side="yes", count=10, price_cents=50,
        client_order_id="m-1", order_id="O1", status="executed",
        filled=10, avg_cents=50.0, fees_usd=0.09, title="t")

    async def _sold(order_id, side, pin_env=None):
        return 4, 60.0
    monkeypatch.setattr(terminal, "_reconcile_fills", _sold)
    run(terminal.record_manual_sell(
        ticker="KXT-2", side="yes", count=4, price_cents=60,
        order_id="O2", status="executed", filled=4))

    with db.get_db() as conn:
        found = db.find_open_manual_position(conn, "KXT-2", "yes", "paper")
    assert found is not None
    assert int(found["filled_contracts"]) == 6, "only the live remainder"



def test_l2_a_second_manual_buy_merges_cost_fees_and_average(fresh_manual_db):
    """The add-to-existing branch updated only the contract counts and status,
    leaving cost_usd, avg_fill_price_cents and fees_usd at the FIRST buy's
    values. The 30s reconcile normally rewrote the basis and hid it, but a
    buy-buy-sell inside one window books P&L off the stale basis and resolves
    the row: 10 @30c + 10 @70c sold at 60c booked about +$8.9 on a trade that
    actually made about +$1.9."""
    import db

    terminal.record_manual_buy(
        ticker="KXT-3", side="yes", count=10, price_cents=30,
        client_order_id="m-1", order_id="O1", status="executed",
        filled=10, avg_cents=30.0, fees_usd=0.15, title="t")
    terminal.record_manual_buy(
        ticker="KXT-3", side="yes", count=10, price_cents=70,
        client_order_id="m-2", order_id="O2", status="executed",
        filled=10, avg_cents=70.0, fees_usd=0.15, title="t")

    with db.get_db() as conn:
        row = db.find_open_manual_position(conn, "KXT-3", "yes", "paper")
    assert int(row["filled_contracts"]) == 20
    assert row["cost_usd"] == pytest.approx(10.0)
    assert row["avg_fill_price_cents"] == pytest.approx(50.0)
    assert row["fees_usd"] == pytest.approx(0.30)



def test_l4_the_sell_quote_includes_the_entry_fee(fresh_manual_db):
    """`basis` comes from Kalshi's market exposure and is fee-EXCLUSIVE, so
    quoting proceeds minus only the exit fee overstated the result by exactly
    the entry fee - always in the user's favour, under a label reading
    "Realised P&L", while the portfolio screen says fees are already included.
    100 YES at 50c sold at 60c quoted +$8.25 and booked +$6.50."""
    terminal.record_manual_buy(
        ticker="KXT-4", side="yes", count=100, price_cents=50,
        client_order_id="m-1", order_id="O1", status="executed",
        filled=100, avg_cents=50.0, fees_usd=1.75, title="t")

    pv = terminal.preview(
        {"ticker": "KXT-4", "side": "yes", "action": "sell",
         "count": 100, "priceCents": 60},
        cfg={}, authed=True,
        market=terminal.market_row({
            "ticker": "KXT-4", "status": "active",
            "yes_bid_dollars": "0.6000", "yes_ask_dollars": "0.6100",
            "close_time": "2099-01-01T00:00:00Z"}),
        book_snapshot={"yesBid": 60.0, "yesAsk": 61.0, "source": "kalshi-rest",
                       "yesLevels": [], "noLevels": []},
        position={"ticker": "KXT-4", "side": "yes", "contracts": 100,
                  "avgCostCents": 50.0})
    exit_fee = terminal._fee_usd(60.0, 100)
    assert pv["maxProfitUsd"] == pytest.approx(
        100 * 0.10 - exit_fee - 1.75, abs=0.01)


def test_l4_a_position_with_no_manual_row_quotes_no_phantom_fee(fresh_manual_db):
    """A bot- or web-opened position has no manual entry fee the user paid, and
    inventing one would understate the quote instead of overstating it."""
    assert terminal._manual_entry_fee_share("KXNOPE-1", "yes", 10) == 0.0



def test_l5_balance_pct_sizing_is_clamped_to_the_crypto_shard(monkeypatch):
    """A 15m crypto order can only be collateralised by cash on the CRYPTO
    shard, but sizing read the account-wide sum. $1,950 general + $50 crypto at
    5% asked for ~$99 against $50: rejected, booked error, and recomputed
    identically every 15-minute window while the UI showed a healthy bankroll -
    and the starved-shard banner stayed hidden, because that test is for an
    affirmative ZERO, not for "not enough"."""
    import kalshi_auth

    async def _bal(cfg, force=False):
        return (200_000, 0)
    monkeypatch.setattr(trader, "refresh_balance", _bal)
    monkeypatch.setattr(kalshi_auth, "_current_env", "paper", raising=False)
    monkeypatch.setitem(kalshi_api._series_shard, "KXBTC15M", 2)
    monkeypatch.setattr(trader, "_balance_cache", dict(trader._balance_cache))

    def set_shards(shards):
        trader._balance_cache["paper"] = {
            "cents": 200_000, "portfolio_cents": 0, "at": 0.0, "shards": shards}

    set_shards({0: 1950.0, 2: 50.0})
    assert run(ct._bankroll_usd({}, True)) == pytest.approx(50.0)

    set_shards({0: 100.0, 2: 1900.0})
    assert run(ct._bankroll_usd({}, True)) == pytest.approx(1900.0)

    set_shards({})
    assert run(ct._bankroll_usd({}, True)) == pytest.approx(2000.0)



def test_r1_a_changed_identity_or_token_restarts_the_bot():
    """start() returns early when a task is live, so it never re-assigns the
    identity - and the sync gated only on liveness, so it did not even call it.
    Correcting a mistyped Discord user id therefore did nothing: DMs from the
    OLD id kept executing buy/sell/confirm while the new one was ignored, with
    the status panel reporting the new value and no way to see the live one.
    The same path meant a rotated bot token was never applied."""
    import service
    src = inspect.getsource(service._sync_remote_bots)
    assert "BOT.user_id != uid" in src
    assert "BOT.token != token_d" in src, "a rotated token must restart it too"
    assert "remote_telegram.BOT.token != token_t" in src
    assert "_sync_remote_bots()" in inspect.getsource(service._h_setConfig)


def test_r3_the_orders_reply_prints_a_usable_order_id():
    """Kalshi ids are 36-char UUIDs and `cancel` passes the token straight to
    DELETE /portfolio/orders/{id} with no prefix resolution, so a truncated id
    404s - making the only risk-reducing command available away from the desk
    unusable."""
    import remote
    src = inspect.getsource(remote._orders)
    assert "orderId'][:10]" not in src and 'orderId"][:10]' not in src
    assert "o['orderId']" in src or 'o["orderId"]' in src



def test_u1_order_sizes_read_the_fixed_point_names():
    """These two read only the pre-August-2026 integer names, so every working
    order rendered its size as an em dash claiming "Kalshi reported no
    remaining count" and the remote reply printed the literal string None -
    the user was asked to cancel blind. `initial_count` matched neither shape;
    the legacy name was `place_count`."""
    row = terminal._order_row({
        "order_id": "o1", "ticker": "X", "side": "yes", "action": "sell",
        "initial_count_fp": "25.00", "remaining_count_fp": "10.00",
        "yes_price_dollars": "0.4100",
    })
    assert row["count"] == 25
    assert row["remaining"] == 10
    zero = terminal._order_row({
        "order_id": "o2", "ticker": "X", "side": "yes",
        "initial_count_fp": "5.00", "remaining_count_fp": "0.00",
    })
    assert zero["remaining"] == 0
    legacy = terminal._order_row({
        "order_id": "o3", "ticker": "X", "side": "yes",
        "place_count": 7, "remaining_count": 3,
    })
    assert legacy["count"] == 7 and legacy["remaining"] == 3



def test_u2_a_row_copy_owns_its_own_provenance():
    """dict() is shallow, so the copy's `sources` WAS the cached sweep row's
    dict: _apply_live_quote wrote values onto the copy but provenance into the
    shared one. A later request off the same 45s cache, with the websocket
    quote now gone, returned the untouched REST value badged kalshi-ws."""
    cached = {"ticker": "X", "yesBid": 40.0, "sources": {"yesBid": "kalshi-rest"}}
    copy = terminal._copy_row(cached)
    copy["sources"]["yesBid"] = "kalshi-ws"
    assert cached["sources"]["yesBid"] == "kalshi-rest", "the cache must not be edited"



def test_u5_transfer_amounts_are_not_floored_by_binary_float(monkeypatch):
    """int(amt * 100) floors the BINARY float, not the cent grid: 2.01 * 100 is
    200.99999999999997, which floors to 200 and moves a cent short. The UI
    prefills toFixed(2), so the amount is always two-decimal."""
    sent = {}

    async def _bal(pin_env=None):
        return {"shard_balances": {0: 5000.0}}

    async def _req(method, path, **kw):
        sent.update(kw.get("json") or {})
        return {"transfer_id": "t"}

    monkeypatch.setattr(kalshi_api, "get_balance", _bal)
    monkeypatch.setattr(kalshi_api, "_signed_request", _req)

    for amount, expect_centicents in ((2.01, 20_100), (0.29, 2_900),
                                      (12.00, 120_000), (1.239, 12_300)):
        run(kalshi_api.transfer_between_shards(
            amount_usd=amount, source_shard=0, destination_shard=2))
        assert sent["amount"] == expect_centicents, (amount, sent["amount"])



def test_p2_the_price_feed_clients_are_counted():
    """Only the Kalshi and Polymarket clients reported their calls, so eight
    catalogued hosts that ARE contacted - the crypto price feeds run every few
    seconds while the 15m engine is on - showed a confident "0 calls" and a
    hover reading "not called yet this session"."""
    import crypto15m
    import remote_discord
    import remote_telegram
    for mod, fn in ((crypto15m, "_get_spot_client"),
                    (remote_discord.DiscordBot, "_http"),
                    (remote_telegram.TelegramBot, "_http")):
        src = inspect.getsource(getattr(mod, fn))
        assert "counting_hooks()" in src, fn

    hooks = kalshi_api.counting_hooks()
    assert "request" in hooks and "response" in hooks



def test_p3_only_the_catalogued_discord_host_is_accepted():
    """The aliases were accepted while appearing nowhere in terminal.HOSTS, so
    a legacy discordapp.com webhook sent cash, portfolio, P&L and per-position
    cost to a hostname the "Every host this app can contact" screen never
    showed."""
    import webhook
    assert webhook._is_allowed_webhook("https://discord.com/api/webhooks/1/t")
    for alias in ("discordapp.com", "canary.discord.com", "ptb.discord.com"):
        assert not webhook._is_allowed_webhook(f"https://{alias}/api/webhooks/1/t")
    catalogued = {h["host"] for h in terminal.HOSTS}
    assert webhook._ALLOWED_WEBHOOK_HOSTS <= catalogued
