"""Standing instructions, Discover filters, and our own microstructure.

The rules engine is the only thing in the app that acts without a click at the
moment it acts, so most of what is pinned here is what it does NOT do: fire on
a price nobody could produce, fire on a mid no bid supports, or sell more than
is held.
"""
from __future__ import annotations

import asyncio
import sqlite3

import pytest

import db
import kalshi_auth
import terminal


@pytest.fixture()
def conn(tmp_path, monkeypatch):
    path = tmp_path / "t.sqlite"
    monkeypatch.setattr(db, "db_path", lambda: path)
    monkeypatch.setattr(kalshi_auth, "get_env", lambda: "paper")
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    c.commit()
    yield c
    c.close()



def test_a_stop_defaults_to_watching_for_the_price_falling(conn):
    r = terminal.create_rule({
        "kind": "stop", "ticker": "KXA-1", "side": "yes", "thresholdCents": 30,
    })
    assert r["direction"] == "below"
    assert r["status"] == "armed"
    assert r["thresholdCents"] == 30.0


def test_a_take_profit_defaults_to_watching_for_the_price_rising(conn):
    r = terminal.create_rule({
        "kind": "take", "ticker": "KXA-1", "side": "yes", "thresholdCents": 80,
    })
    assert r["direction"] == "above"


def test_a_threshold_outside_the_tradeable_range_is_refused(conn):
    for bad in (0, 100, -5, None, "abc"):
        with pytest.raises(ValueError, match="1c and 99c"):
            terminal.create_rule({
                "kind": "stop", "ticker": "KXA-1", "side": "yes",
                "thresholdCents": bad,
            })


def test_an_unknown_kind_is_refused(conn):
    with pytest.raises(ValueError, match="kind must be"):
        terminal.create_rule({
            "kind": "moon", "ticker": "KXA-1", "side": "yes", "thresholdCents": 50,
        })


def test_cancelling_a_rule_takes_it_out_of_the_armed_set(conn):
    r = terminal.create_rule({
        "kind": "alert", "ticker": "KXA-1", "side": "yes", "thresholdCents": 50,
    })
    assert terminal.cancel_rule(r["id"])["ok"] is True
    assert terminal.list_rules()["armedCount"] == 0
    assert terminal.cancel_rule(r["id"])["ok"] is False


def test_rules_are_scoped_to_the_environment(conn):
    terminal.create_rule({
        "kind": "alert", "ticker": "KXA-1", "side": "yes", "thresholdCents": 50,
    })
    with db.get_db() as c:
        c.execute("UPDATE terminal_rules SET kalshi_env='production'")
    assert terminal.list_rules()["rules"] == []



def test_a_below_rule_fires_at_or_under_the_threshold():
    assert terminal._rule_fires("below", 29.0, 30.0) is True
    assert terminal._rule_fires("below", 30.0, 30.0) is True
    assert terminal._rule_fires("below", 30.1, 30.0) is False


def test_an_above_rule_fires_at_or_over_the_threshold():
    assert terminal._rule_fires("above", 81.0, 80.0) is True
    assert terminal._rule_fires("above", 80.0, 80.0) is True
    assert terminal._rule_fires("above", 79.9, 80.0) is False


def test_the_exit_price_is_the_bid_you_could_actually_sell_into():
    book = {"yesBid": 40.0, "yesAsk": 44.0, "midCents": 42.0, "source": "kalshi-ws"}
    assert terminal._exit_price_for(book, "yes") == (40.0, "kalshi-ws")
    assert terminal._exit_price_for(book, "no") == (56.0, "kalshi-ws")


def test_a_one_sided_book_yields_no_exit_price_rather_than_a_guess():
    assert terminal._exit_price_for({"yesBid": None, "yesAsk": 44.0}, "yes")[0] is None
    assert terminal._exit_price_for({"yesBid": 40.0, "yesAsk": None}, "no")[0] is None
    assert terminal._exit_price_for(None, "yes") == (None, None)



def _armed(kind="stop", threshold=30.0, direction="below", side="yes"):
    return terminal.create_rule({
        "kind": kind, "ticker": "KXA-1", "side": side,
        "thresholdCents": threshold, "direction": direction,
    })


def test_a_rule_with_no_bid_does_nothing_and_records_why(conn, monkeypatch):
    _armed()

    async def fake_book(t):
        return {"yesBid": None, "yesAsk": None, "source": "kalshi-rest"}
    monkeypatch.setattr(terminal, "book", fake_book)

    changed = asyncio.run(terminal.evaluate_rules({}, authed=True))
    assert changed == []
    r = terminal.list_rules()["rules"][0]
    assert r["status"] == "armed"
    assert r["lastPriceCents"] is None
    assert "Nobody is bidding" in r["lastError"]


def test_an_unreadable_book_leaves_the_rule_armed_with_the_error(conn, monkeypatch):
    _armed()

    async def boom(t):
        raise RuntimeError("provider parked")
    monkeypatch.setattr(terminal, "book", boom)

    asyncio.run(terminal.evaluate_rules({}, authed=True))
    r = terminal.list_rules()["rules"][0]
    assert r["status"] == "armed"
    assert "provider parked" in r["lastError"]


def test_a_rule_above_its_threshold_records_the_price_and_stays_armed(conn, monkeypatch):
    _armed(threshold=30.0)

    async def fake_book(t):
        return {"yesBid": 45.0, "yesAsk": 46.0, "source": "kalshi-ws"}
    monkeypatch.setattr(terminal, "book", fake_book)

    assert asyncio.run(terminal.evaluate_rules({}, authed=True)) == []
    r = terminal.list_rules()["rules"][0]
    assert r["status"] == "armed"
    assert r["lastPriceCents"] == 45.0
    assert r["lastPriceSource"] == "kalshi-ws"
    assert r["lastError"] is None


def test_an_alert_fires_once_and_notifies_without_trading(conn, monkeypatch):
    _armed(kind="alert", threshold=50.0, direction="above")

    async def fake_book(t):
        return {"yesBid": 55.0, "yesAsk": 56.0, "source": "kalshi-ws"}
    monkeypatch.setattr(terminal, "book", fake_book)

    sent: list = []

    async def on_event(name, data):
        sent.append((name, data))

    def no_orders(*a, **k):
        raise AssertionError("an alert must never place an order")
    monkeypatch.setattr(terminal, "submit", no_orders)

    changed = asyncio.run(
        terminal.evaluate_rules({}, authed=True, on_event=on_event))
    assert len(changed) == 1 and changed[0]["status"] == "triggered"
    assert sent and sent[0][0] == "terminal:rule"

    assert asyncio.run(terminal.evaluate_rules({}, authed=True)) == []


def test_a_triggered_stop_sells_through_the_bid_so_it_actually_fills(conn, monkeypatch):
    _armed(kind="stop", threshold=40.0, direction="below")

    async def fake_book(t):
        return {"yesBid": 35.0, "yesAsk": 37.0, "source": "kalshi-ws"}
    monkeypatch.setattr(terminal, "book", fake_book)

    async def fake_portfolio(authed):
        return {"positions": [{"ticker": "KXA-1", "side": "yes", "contracts": 12}]}
    monkeypatch.setattr(terminal, "portfolio", fake_portfolio)

    seen: list = []

    async def fake_submit(req, *, cfg, authed, scope=None):
        seen.append(req)
        return {"ok": True, "message": "Filled 12 at 35c", "orderId": "ord-1"}
    monkeypatch.setattr(terminal, "submit", fake_submit)

    changed = asyncio.run(terminal.evaluate_rules(
        {"terminal_stop_slippage_cents": 2}, authed=True))
    assert len(changed) == 1 and changed[0]["status"] == "triggered"
    assert changed[0]["triggeredOrderId"] == "ord-1"
    req = seen[0]
    assert req["action"] == "sell" and req["side"] == "yes"
    assert req["count"] == 12
    assert req["priceCents"] == 33.0


def test_a_stop_never_sells_more_than_is_actually_held(conn, monkeypatch):
    terminal.create_rule({
        "kind": "stop", "ticker": "KXA-1", "side": "yes",
        "thresholdCents": 40, "contracts": 999,
    })

    async def fake_book(t):
        return {"yesBid": 35.0, "yesAsk": 37.0, "source": "kalshi-ws"}
    monkeypatch.setattr(terminal, "book", fake_book)

    async def fake_portfolio(authed):
        return {"positions": [{"ticker": "KXA-1", "side": "yes", "contracts": 4}]}
    monkeypatch.setattr(terminal, "portfolio", fake_portfolio)

    seen: list = []

    async def fake_submit(req, *, cfg, authed, scope=None):
        seen.append(req)
        return {"ok": True, "message": "ok", "orderId": "o"}
    monkeypatch.setattr(terminal, "submit", fake_submit)

    asyncio.run(terminal.evaluate_rules({}, authed=True))
    assert seen[0]["count"] == 4


def test_a_stop_on_a_position_that_is_already_gone_retires_itself(conn, monkeypatch):
    _armed(kind="stop", threshold=40.0)

    async def fake_book(t):
        return {"yesBid": 35.0, "yesAsk": 37.0, "source": "kalshi-ws"}
    monkeypatch.setattr(terminal, "book", fake_book)

    async def fake_portfolio(authed):
        return {"positions": []}
    monkeypatch.setattr(terminal, "portfolio", fake_portfolio)

    def no_orders(*a, **k):
        raise AssertionError("nothing to close — must not send an order")
    monkeypatch.setattr(terminal, "submit", no_orders)

    changed = asyncio.run(terminal.evaluate_rules({}, authed=True))
    assert changed[0]["status"] == "cancelled"
    assert "already gone" in changed[0]["lastError"]


def test_without_credentials_a_triggered_exit_sends_nothing(conn, monkeypatch):
    _armed(kind="stop", threshold=40.0)

    async def fake_book(t):
        return {"yesBid": 35.0, "yesAsk": 37.0, "source": "kalshi-ws"}
    monkeypatch.setattr(terminal, "book", fake_book)

    def no_orders(*a, **k):
        raise AssertionError("must not trade without credentials")
    monkeypatch.setattr(terminal, "submit", no_orders)

    asyncio.run(terminal.evaluate_rules({}, authed=False))
    r = terminal.list_rules()["rules"][0]
    assert r["status"] == "armed"
    assert "no verified credentials" in r["lastError"].lower()


def test_a_refused_exit_stays_armed_because_nothing_was_sent(conn, monkeypatch):
    _armed(kind="stop", threshold=40.0)

    async def fake_book(t):
        return {"yesBid": 35.0, "yesAsk": 37.0, "source": "kalshi-ws"}
    monkeypatch.setattr(terminal, "book", fake_book)

    async def fake_portfolio(authed):
        return {"positions": [{"ticker": "KXA-1", "side": "yes", "contracts": 3}]}
    monkeypatch.setattr(terminal, "portfolio", fake_portfolio)

    async def fake_submit(req, *, cfg, authed, scope=None):
        return {"ok": False, "message": "Kalshi rejected the order: closed"}
    monkeypatch.setattr(terminal, "submit", fake_submit)

    changed = asyncio.run(terminal.evaluate_rules({}, authed=True))
    assert changed[0]["status"] == "armed"
    assert "rejected" in changed[0]["lastError"]


def test_an_unconfirmed_exit_stops_and_asks_for_a_human(conn, monkeypatch):
    """The one case that must NOT re-arm: the order may be LIVE on Kalshi, so
    firing again could double the exit."""
    _armed(kind="stop", threshold=40.0)

    async def fake_book(t):
        return {"yesBid": 35.0, "yesAsk": 37.0, "source": "kalshi-ws"}
    monkeypatch.setattr(terminal, "book", fake_book)

    async def fake_portfolio(authed):
        return {"positions": [{"ticker": "KXA-1", "side": "yes", "contracts": 3}]}
    monkeypatch.setattr(terminal, "portfolio", fake_portfolio)

    async def fake_submit(req, *, cfg, authed, scope=None):
        return {"ok": False, "status": "unconfirmed",
                "message": "sent but Kalshi's reply was lost"}
    monkeypatch.setattr(terminal, "submit", fake_submit)

    changed = asyncio.run(terminal.evaluate_rules({}, authed=True))
    assert changed[0]["status"] == "error"



def _row(**kw):
    base = {"ticker": "T", "title": "t", "category": "Sports", "volume": 100,
            "midCents": 50.0, "minutesToClose": 120.0}
    base.update(kw)
    return base


def test_no_filters_is_a_passthrough():
    rows = [_row(), _row()]
    assert terminal.apply_filters(rows, None) == (rows, 0, 0)
    assert terminal.apply_filters(rows, {}) == (rows, 0, 0)


def test_a_numeric_filter_skips_rows_whose_value_never_arrived():
    rows = [_row(ticker="A", volume=500), _row(ticker="B", volume=None)]
    kept, skipped, excluded = terminal.apply_filters(rows, {"minVolume": 100})
    assert [r["ticker"] for r in kept] == ["A"]
    assert (skipped, excluded) == (1, 0)


def test_a_numeric_filter_does_not_count_a_real_miss_as_skipped():
    rows = [_row(ticker="A", volume=500), _row(ticker="B", volume=5)]
    kept, skipped, excluded = terminal.apply_filters(rows, {"minVolume": 100})
    assert [r["ticker"] for r in kept] == ["A"]
    assert (skipped, excluded) == (0, 0)


def test_a_category_filter_excludes_uncategorised_rows_without_calling_them_skipped():
    rows = [_row(ticker="A", category="Sports"), _row(ticker="B", category=None)]
    kept, skipped, excluded = terminal.apply_filters(rows, {"categories": ["Sports"]})
    assert [r["ticker"] for r in kept] == ["A"]
    assert (skipped, excluded) == (0, 1)


def test_category_matching_is_case_insensitive():
    rows = [_row(category="Politics")]
    kept, _s, _e = terminal.apply_filters(rows, {"categories": ["politics"]})
    assert len(kept) == 1


def test_a_price_band_skips_markets_with_no_two_sided_quote():
    rows = [_row(ticker="A", midCents=50.0), _row(ticker="B", midCents=None)]
    kept, skipped, _e = terminal.apply_filters(
        rows, {"minPriceCents": 20, "maxPriceCents": 80})
    assert [r["ticker"] for r in kept] == ["A"]
    assert skipped == 1


def test_a_close_window_excludes_already_closed_markets():
    rows = [
        _row(ticker="A", minutesToClose=60.0),
        _row(ticker="B", minutesToClose=-5.0),
        _row(ticker="C", minutesToClose=None),
        _row(ticker="D", minutesToClose=60 * 40),
    ]
    kept, skipped, _e = terminal.apply_filters(rows, {"maxHoursToClose": 6})
    assert [r["ticker"] for r in kept] == ["A"]
    assert skipped == 1


def test_filters_combine():
    rows = [
        _row(ticker="A", category="Sports", volume=900, midCents=50.0),
        _row(ticker="B", category="Politics", volume=900, midCents=50.0),
        _row(ticker="C", category="Sports", volume=2, midCents=50.0),
    ]
    kept, _s, _e = terminal.apply_filters(
        rows, {"categories": ["Sports"], "minVolume": 100})
    assert [r["ticker"] for r in kept] == ["A"]


def test_the_note_distinguishes_skipped_from_excluded():
    note = terminal._filter_note(3, 4)
    assert "3" in note and "unmeasured, not low" in note
    assert "4" in note and "not a member of a set you named" in note
    assert terminal._filter_note(0, 0) == ""



def test_an_unrecorded_market_reports_nothing_rather_than_zeros(monkeypatch):
    terminal._micro.clear()
    monkeypatch.setattr(terminal.kalshi_ws, "is_connected", lambda: True)
    m = terminal.microstructure("KXNONE")
    assert m["sampleCount"] == 0
    assert m["medianSpreadCents"] is None
    assert m["twoSidedPct"] is None
    assert m["quoteLifetimeSec"] is None
    assert m["note"]


def _seed(ticker: str, rows: list[tuple]) -> None:
    from collections import deque
    terminal._micro[ticker] = deque(
        [{"ts": ts, "bid": b, "ask": a, "bidSize": 10, "askSize": 10}
         for ts, b, a in rows],
        maxlen=terminal.MICRO_MAX_SAMPLES,
    )


def test_spread_statistics_come_from_two_sided_samples_only():
    _seed("KXA", [
        (1.0, 40.0, 41.0),
        (2.0, 40.0, 45.0),
        (3.0, None, 45.0),
        (4.0, 40.0, 43.0),
    ])
    m = terminal.microstructure("KXA")
    assert m["sampleCount"] == 4
    assert m["bestSpreadCents"] == 1.0
    assert m["medianSpreadCents"] == 3.0
    assert m["twoSidedPct"] == 0.75


def test_quote_lifetime_measures_how_long_the_top_of_book_survives():
    _seed("KXA", [
        (0.0, 40.0, 41.0),
        (1.0, 40.0, 41.0),
        (2.0, 40.0, 41.0),
        (3.0, 39.0, 41.0),
        (4.0, 39.0, 41.0),
        (5.0, 38.0, 41.0),
    ])
    m = terminal.microstructure("KXA")
    assert m["quoteLifetimeSec"] == 2.5


def test_fillability_is_measured_over_the_window_not_modelled():
    _seed("KXA", [
        (1.0, 40.0, 41.0),
        (2.0, 40.0, 44.0),
        (3.0, 40.0, 48.0),
        (4.0, 40.0, 41.0),
    ])
    m = terminal.microstructure("KXA", probe_cents=44)
    assert m["probeCents"] == 44.0
    assert m["probeFillablePct"] == 0.75
    assert terminal.microstructure("KXA", probe_cents=41)["probeFillablePct"] == 0.5


def test_an_out_of_range_probe_is_treated_as_no_probe():
    _seed("KXA", [(1.0, 40.0, 41.0)])
    assert terminal.microstructure("KXA", probe_cents=0)["probeFillablePct"] is None
    assert terminal.microstructure("KXA", probe_cents=100)["probeCents"] is None


def test_the_recorder_drops_markets_nobody_is_looking_at_any_more(monkeypatch):
    terminal._micro.clear()
    terminal._ws_interest.clear()
    _seed("KXOLD", [(1.0, 40.0, 41.0)])
    monkeypatch.setattr(terminal.kalshi_ws, "is_connected", lambda: True)
    monkeypatch.setattr(terminal.kalshi_ws, "orderbook", lambda t: None)
    terminal._micro_last_sample = 0.0
    terminal.sample_microstructure()
    assert "KXOLD" not in terminal._micro


def test_nothing_is_recorded_while_the_socket_is_down(monkeypatch):
    terminal._micro.clear()
    terminal.note_interest("KXA")
    monkeypatch.setattr(terminal.kalshi_ws, "is_connected", lambda: False)
    terminal._micro_last_sample = 0.0
    assert terminal.sample_microstructure() == 0
    assert terminal._micro == {}



def test_a_404_is_distinguished_from_a_failure_to_ask(monkeypatch):
    import kalshi_api

    async def missing(url, params=None):
        return None, 404

    async def unreachable(url, params=None):
        return None, None

    async def found(url, params=None):
        return {"market": {"ticker": "KXA-1", "status": "active"}}, 200

    monkeypatch.setattr(kalshi_api, "_pub_get_ex", missing)
    assert asyncio.run(kalshi_api.fetch_market_checked("X"))[1] == "missing"

    monkeypatch.setattr(kalshi_api, "_pub_get_ex", unreachable)
    assert asyncio.run(kalshi_api.fetch_market_checked("X"))[1] == "unreachable"

    monkeypatch.setattr(kalshi_api, "_pub_get_ex", found)
    m, status = asyncio.run(kalshi_api.fetch_market_checked("KXA-1"))
    assert status == "found" and m["ticker"] == "KXA-1"


def test_a_rule_on_a_nonexistent_market_is_refused_at_arm_time(conn):
    with pytest.raises(ValueError, match="no market called"):
        terminal.create_rule({
            "kind": "alert", "ticker": "KXNOPE-1", "side": "yes",
            "thresholdCents": 50,
        }, market_status="missing")
    assert terminal.list_rules()["rules"] == []


def test_an_unreachable_api_does_not_block_arming_a_rule(conn):
    r = terminal.create_rule({
        "kind": "stop", "ticker": "KXA-1", "side": "yes", "thresholdCents": 30,
    }, market_status="unreachable")
    assert r["status"] == "armed"


def test_a_momentary_lack_of_bids_keeps_the_rule_armed(conn, monkeypatch):
    _armed()

    async def no_bid(t):
        return {"yesBid": None, "yesAsk": None, "source": "kalshi-rest"}
    monkeypatch.setattr(terminal, "book", no_bid)

    def no_lookup(*a, **k):
        raise AssertionError("must not spend a lookup on every empty check")
    monkeypatch.setattr(terminal.kalshi_api, "fetch_market_checked", no_lookup)

    for _ in range(terminal.RULE_LIVENESS_EVERY - 1):
        asyncio.run(terminal.evaluate_rules({}, authed=True))
    r = terminal.list_rules()["rules"][0]
    assert r["status"] == "armed"
    assert r["unevaluableCount"] == terminal.RULE_LIVENESS_EVERY - 1
    assert "stays armed" in r["lastError"]


def test_a_rule_whose_market_has_vanished_retires_itself(conn, monkeypatch):
    _armed()

    async def no_bid(t):
        return {"yesBid": None, "yesAsk": None, "source": "kalshi-rest"}
    monkeypatch.setattr(terminal, "book", no_bid)

    async def gone(ticker):
        return None, "missing"
    monkeypatch.setattr(terminal.kalshi_api, "fetch_market_checked", gone)

    changed = []
    for _ in range(terminal.RULE_LIVENESS_EVERY):
        changed = asyncio.run(terminal.evaluate_rules({}, authed=True)) or changed
    r = terminal.list_rules()["rules"][0]
    assert r["status"] == "cancelled"
    assert "no longer has a market" in r["lastError"]


def test_a_rule_on_a_settled_market_retires_itself(conn, monkeypatch):
    _armed()

    async def no_bid(t):
        return {"yesBid": None, "yesAsk": None, "source": "kalshi-rest"}
    monkeypatch.setattr(terminal, "book", no_bid)

    async def settled(ticker):
        return {"ticker": "KXA-1", "status": "settled"}, "found"
    monkeypatch.setattr(terminal.kalshi_api, "fetch_market_checked", settled)

    for _ in range(terminal.RULE_LIVENESS_EVERY):
        asyncio.run(terminal.evaluate_rules({}, authed=True))
    r = terminal.list_rules()["rules"][0]
    assert r["status"] == "cancelled"
    assert "settled" in r["lastError"]


def test_a_still_open_market_with_no_bid_stays_armed_and_says_so(conn, monkeypatch):
    _armed()

    async def no_bid(t):
        return {"yesBid": None, "yesAsk": None, "source": "kalshi-rest"}
    monkeypatch.setattr(terminal, "book", no_bid)

    async def alive(ticker):
        return {"ticker": "KXA-1", "status": "active"}, "found"
    monkeypatch.setattr(terminal.kalshi_api, "fetch_market_checked", alive)

    for _ in range(terminal.RULE_LIVENESS_EVERY):
        asyncio.run(terminal.evaluate_rules({}, authed=True))
    r = terminal.list_rules()["rules"][0]
    assert r["status"] == "armed"
    assert "still listed as active" in r["lastError"]


def test_the_unevaluable_counter_resets_once_a_price_arrives(conn, monkeypatch):
    _armed(threshold=1.0)
    state = {"bid": None}

    async def book(t):
        return {"yesBid": state["bid"], "yesAsk": 50.0, "source": "kalshi-rest"}
    monkeypatch.setattr(terminal, "book", book)

    asyncio.run(terminal.evaluate_rules({}, authed=True))
    assert terminal.list_rules()["rules"][0]["unevaluableCount"] == 1

    state["bid"] = 45.0
    asyncio.run(terminal.evaluate_rules({}, authed=True))
    r = terminal.list_rules()["rules"][0]
    assert r["unevaluableCount"] == 0
    assert r["lastPriceCents"] == 45.0
    assert r["lastError"] is None
