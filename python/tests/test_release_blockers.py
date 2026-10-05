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
    import db
    import kalshi_auth
    dbfile = tmp_path / "manual-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    monkeypatch.setattr(kalshi_auth, "_current_env", "demo", raising=False)
    yield


def test_b10_shard_transfer_is_sent_exactly_once(monkeypatch):
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
    sig = inspect.signature(kalshi_api._signed_request)
    assert sig.parameters["retry"].default is True


def test_b6_deci_cent_levels_survive_parsing():
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
    quote = {"yes_bid": 0.40, "yes_ask": 0.42, "last_price": 0.41}
    mark = trader._side_mark_cents(quote, "yes")
    assert isinstance(mark, (int, float)) and not isinstance(mark, bool)
    assert mark == pytest.approx(41.0)
    assert trader._side_mark_cents(quote, "no") == pytest.approx(59.0)
    assert trader._side_mark_cents(None, "yes") is None


def _idf(*titles):
    return cv.build_idf([cv.tokens(t) for t in titles])


def test_b4_opposite_directions_never_pair():
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
    src = inspect.getsource(ct._open_pair_leg)
    assert "_lookup_lost_order" in src, "must use the confirming lookup"
    assert "if not lookup_ok:" in src, "an unconfirmed lookup needs its own branch"
    unconfirmed = src.split("if not lookup_ok:", 1)[1].split("row.update", 1)[0]
    assert "_mark_resolved" not in unconfirmed


def test_b2_a_still_resting_order_is_not_booked_canceled():
    assert "resting" not in ct._DEAD_ORDER_STATUSES
    assert "pending" not in ct._DEAD_ORDER_STATUSES
    for dead in ("canceled", "cancelled", "executed", "expired"):
        assert dead in ct._DEAD_ORDER_STATUSES
    src = inspect.getsource(ct._cancel_entry_and_finalize)
    assert "final_dead" in src
    assert "elif read_ok and (final_dead or market_closed):" in src, (
        "a zero-fill read alone is not enough")


def test_b2_a_resting_order_on_a_closed_market_does_terminate():
    src = inspect.getsource(ct._cancel_entry_and_finalize)
    assert "market_closed" in src
    assert "_CLOSED_ORDER_GRACE_SEC" in src
    assert src.index('if final_filled > 0:') < src.index('market_closed or') \
        if 'market_closed or' in src else True
    assert "_warn_once(" in src


def test_b2_the_poll_warning_is_throttled():
    ct._warn_at.clear()
    assert ct._warn_once("k", 60.0) is True
    assert ct._warn_once("k", 60.0) is False, "a 4s poll must not log every pass"
    assert ct._warn_once("other", 60.0) is True, "throttling is per key"


def test_b7_resting_sells_are_counted_against_available_contracts():
    src = inspect.getsource(terminal.evaluate_rules)
    assert "resting_sold" in src
    assert "await resting_orders(" in src, "the live book must be read per pass"
    assert "already += resting_sold" in src, \
        "resting size must reduce what a rule may sell"


def test_b8_the_account_total_counts_manual_positions():
    import service
    src = inspect.getsource(service)
    assert "account_open_cost = db.open_filled_cost_usd(conn, env)" in src
    assert "port_usd = account_open_cost + crypto_open_cost" in src
    import db as _db
    assert "!= 'manual'" not in inspect.getsource(_db.open_filled_cost_usd)


def test_p1_a_rejected_webhook_url_is_never_logged_in_full():
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
    import logscrub
    secret = "AbCdEfGh-IjKlMnOpQrStUvWxYz_TOKEN"
    for host in ("discord.com", "discordapp.com"):
        line = f"POST https://{host}/api/webhooks/1234567890/{secret} failed"
        out = logscrub.scrub(line)
        assert secret not in out, out
        assert f"{host}/api/webhooks/1234567890/" in out
        assert logscrub.REDACTED in out


def test_l3_a_partially_filled_manual_order_is_booked_partial():
    assert terminal._manual_status(3, 10) == "partial"
    assert terminal._manual_status(10, 10) == "filled"
    assert terminal._manual_status(12, 10) == "filled"
    assert terminal._manual_status(0, 10) == "submitted"
    assert terminal._manual_status(None, 10) == "submitted"
    assert terminal._manual_status(5, 0) == "filled"


def test_l3_both_manual_buy_paths_use_the_shared_mapping():
    src = inspect.getsource(terminal.record_manual_buy)
    assert '"filled" if (filled or 0) > 0' not in src, "the old mapping is gone"
    assert src.count("_manual_status(") == 2, "both the insert and merge paths"


def test_l1_a_partial_exit_books_its_realised_pnl_and_fee(fresh_manual_db, monkeypatch):
    import db

    terminal.record_manual_buy(
        ticker="KXT-1", side="yes", count=100, price_cents=20,
        client_order_id="m-1", order_id="O1", status="executed",
        filled=100, avg_cents=20.0, fees_usd=1.12, title="t")

    async def _sold(order_id, side):
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
    import db

    terminal.record_manual_buy(
        ticker="KXT-2", side="yes", count=10, price_cents=50,
        client_order_id="m-1", order_id="O1", status="executed",
        filled=10, avg_cents=50.0, fees_usd=0.09, title="t")

    async def _sold(order_id, side):
        return 4, 60.0
    monkeypatch.setattr(terminal, "_reconcile_fills", _sold)
    run(terminal.record_manual_sell(
        ticker="KXT-2", side="yes", count=4, price_cents=60,
        order_id="O2", status="executed", filled=4))

    with db.get_db() as conn:
        found = db.find_open_manual_position(conn, "KXT-2", "yes", "demo")
    assert found is not None
    assert int(found["filled_contracts"]) == 6, "only the live remainder"


def test_l2_a_second_manual_buy_merges_cost_fees_and_average(fresh_manual_db):
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
        row = db.find_open_manual_position(conn, "KXT-3", "yes", "demo")
    assert int(row["filled_contracts"]) == 20
    assert row["cost_usd"] == pytest.approx(10.0)
    assert row["avg_fill_price_cents"] == pytest.approx(50.0)
    assert row["fees_usd"] == pytest.approx(0.30)


def test_l4_the_sell_quote_includes_the_entry_fee(fresh_manual_db):
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
    assert terminal._manual_entry_fee_share("KXNOPE-1", "yes", 10) == 0.0


def test_l5_balance_pct_sizing_is_clamped_to_the_crypto_shard(monkeypatch):
    import kalshi_auth

    async def _bal(cfg, force=False):
        return (200_000, 0)
    monkeypatch.setattr(trader, "refresh_balance", _bal)
    monkeypatch.setattr(kalshi_auth, "_current_env", "demo", raising=False)
    monkeypatch.setitem(kalshi_api._series_shard, "KXBTC15M", 2)
    monkeypatch.setattr(trader, "_balance_cache", dict(trader._balance_cache))

    def set_shards(shards):
        trader._balance_cache["demo"] = {
            "cents": 200_000, "portfolio_cents": 0, "at": 0.0, "shards": shards}

    set_shards({0: 1950.0, 2: 50.0})
    assert run(ct._bankroll_usd({}, True)) == pytest.approx(50.0)

    set_shards({0: 100.0, 2: 1900.0})
    assert run(ct._bankroll_usd({}, True)) == pytest.approx(1900.0)

    set_shards({})
    assert run(ct._bankroll_usd({}, True)) == pytest.approx(2000.0)


def test_r1_a_changed_identity_or_token_restarts_the_bot():
    import service
    src = inspect.getsource(service._sync_remote_bots)
    assert "BOT.user_id != uid" in src
    assert "BOT.token != token_d" in src, "a rotated token must restart it too"
    assert "remote_telegram.BOT.token != token_t" in src
    assert "_sync_remote_bots()" in inspect.getsource(service._h_setConfig)


def test_r3_the_orders_reply_prints_a_usable_order_id():
    import remote
    src = inspect.getsource(remote._orders)
    assert "orderId'][:10]" not in src and 'orderId"][:10]' not in src
    assert "o['orderId']" in src or 'o["orderId"]' in src


def test_u1_order_sizes_read_the_fixed_point_names():
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
    cached = {"ticker": "X", "yesBid": 40.0, "sources": {"yesBid": "kalshi-rest"}}
    copy = terminal._copy_row(cached)
    copy["sources"]["yesBid"] = "kalshi-ws"
    assert cached["sources"]["yesBid"] == "kalshi-rest", "the cache must not be edited"


def test_u5_transfer_amounts_are_not_floored_by_binary_float(monkeypatch):
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
    import webhook
    assert webhook._is_allowed_webhook("https://discord.com/api/webhooks/1/t")
    for alias in ("discordapp.com", "canary.discord.com", "ptb.discord.com"):
        assert not webhook._is_allowed_webhook(f"https://{alias}/api/webhooks/1/t")
    catalogued = {h["host"] for h in terminal.HOSTS}
    assert webhook._ALLOWED_WEBHOOK_HOSTS <= catalogued
