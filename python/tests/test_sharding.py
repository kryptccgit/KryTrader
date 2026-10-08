"""Exchange sharding.

Kalshi split trading across matching engines in August 2026. On the 24th,
crypto moved to shard 2 — which is exactly where this app's 15m engine trades —
and tennis/baseball to shard 3.

Two things broke for a client that ignores it, and the tests below pin both.
A third thing did NOT break, and that is pinned too, because it is the one that
would have been catastrophic: if `/portfolio/positions` had become shard-scoped
by default, the reconcile pass would have seen every crypto position vanish,
orphan-closed them, and booked fabricated P&L.
"""
from __future__ import annotations

import asyncio

import pytest

import kalshi_api


def run(coro):
    return asyncio.run(coro)



BREAKDOWN = {
    "balance": 1000,
    "balance_dollars": "10.0000",
    "portfolio_value": 500,
    "balance_breakdown": [
        {"exchange_index": 0, "balance": "10.0000"},
        {"exchange_index": 2, "balance": "35.5000"},
        {"exchange_index": 3, "balance": "4.5000"},
    ],
}


def _stub(monkeypatch, payload):
    async def fake(method, path, **kw):
        return payload
    monkeypatch.setattr(kalshi_api, "_signed_request", fake)


def test_the_account_total_sums_every_shard(monkeypatch):
    _stub(monkeypatch, BREAKDOWN)
    data = run(kalshi_api.get_balance())
    assert data["total_balance_cents"] == 5000
    assert data["sharded"] is True
    assert data["shard_balances"] == {0: 10.0, 2: 35.5, 3: 4.5}


def test_the_scoped_balance_field_is_left_untouched(monkeypatch):
    _stub(monkeypatch, BREAKDOWN)
    data = run(kalshi_api.get_balance())
    assert data["balance"] == 1000


def test_a_response_with_no_breakdown_falls_back_to_the_scoped_value(monkeypatch):
    _stub(monkeypatch, {"balance": 2500, "portfolio_value": 0})
    data = run(kalshi_api.get_balance())
    assert data["total_balance_cents"] == 2500
    assert data["sharded"] is False
    assert data["shard_balances"] == {}


def test_a_malformed_breakdown_entry_is_skipped_not_guessed(monkeypatch):
    _stub(monkeypatch, {
        "balance": 100,
        "balance_breakdown": [
            {"exchange_index": 0, "balance": "1.0000"},
            {"exchange_index": "bad", "balance": "9.0000"},
            {"exchange_index": 2},
            {"exchange_index": 3, "balance": "not a number"},
            "nonsense",
        ],
    })
    data = run(kalshi_api.get_balance())
    assert data["shard_balances"] == {0: 1.0}
    assert data["total_balance_cents"] == 100


def test_a_non_dict_response_passes_through_untouched(monkeypatch):
    _stub(monkeypatch, None)
    assert run(kalshi_api.get_balance()) is None



def test_every_order_is_auto_routed_by_ticker(monkeypatch):
    """Without this, an order for a shard-2 crypto market is sent to shard 0.
    -1 means 'route by ticker' and is correct both before and after the
    27 August change that makes auto-routing the default for an omitted
    value."""
    sent = {}

    async def fake(method, path, *, json=None, **kw):
        sent.update(json or {})
        return {"order": {"order_id": "o1", "status": "resting"}}

    monkeypatch.setattr(kalshi_api, "_signed_request", fake)
    run(kalshi_api.place_limit_order(
        ticker="KXBTC15M-26AUG250415-15", side="yes", action="buy",
        count=1, price_cents=45))
    assert sent["exchange_index"] == -1
    assert sent["ticker"] == "KXBTC15M-26AUG250415-15"



def test_positions_are_never_filtered_to_one_shard():
    """`exchange_index` on positions/orders/fills is an optional FILTER, and
    omitting it returns every shard. Adding one would make the reconcile pass
    believe crypto positions had vanished, orphan-close them, and book
    fabricated P&L on contracts still held."""
    import inspect
    for fn in (kalshi_api.get_positions, kalshi_api.get_settled_positions,
               kalshi_api.fetch_orders, kalshi_api.get_fills_since):
        src = inspect.getsource(fn)
        assert "exchange_index" not in src, (
            f"{fn.__name__} must not filter by shard — omitting the parameter "
            f"is what returns the whole account")



def test_shards_have_names_a_person_can_act_on():
    assert kalshi_api.shard_name(2) == "crypto"
    assert kalshi_api.shard_name(3) == "tennis & baseball"
    assert kalshi_api.shard_name(0) == "general"
    assert kalshi_api.shard_name(1) == "combos"


def test_an_unknown_shard_is_named_not_hidden():
    assert kalshi_api.shard_name(9) == "shard 9"
    assert kalshi_api.shard_name(None) == "unknown"



def _status(**halted):
    """A live-shaped status with the named shards' trading switched off."""
    shards = {}
    for idx, name in kalshi_api.SHARD_NAMES.items():
        shards[idx] = {
            "exchangeActive": True,
            "tradingActive": idx not in halted.get("off", ()),
            "transfersActive": True,
            "name": name,
        }
    return {"exchangeActive": True, "tradingActive": True,
            "shards": shards, "fetchedAt": 0.0}


def test_a_halt_on_one_shard_is_not_visible_in_the_top_level_flag():
    """The whole reason this reads the array: the top-level flag still says
    trading is on while the engine hosting the market is stopped."""
    st = _status(off=(2,))
    assert st["tradingActive"] is True
    assert kalshi_api.shard_trading_halted(st, 2) == "crypto"
    assert kalshi_api.shard_trading_halted(st, 0) is None


def test_an_unreadable_status_blocks_nothing():
    """None means UNKNOWN. Refusing to trade because a status endpoint blipped
    would be a worse failure than the one it guards against."""
    assert kalshi_api.shard_trading_halted(None, 2) is None
    assert kalshi_api.shard_trading_halted(_status(), None) is None
    assert kalshi_api.shard_trading_halted(_status(), 99) is None


def test_a_halted_shard_blocks_the_order_ticket():
    import terminal
    market = terminal.market_row({
        "ticker": "KXBTC15M-X", "title": "t", "status": "active",
        "yes_bid_dollars": "0.4000", "yes_ask_dollars": "0.4100",
        "close_time": "2099-01-01T00:00:00Z", "exchange_index": 2,
    })
    req = {"ticker": "KXBTC15M-X", "side": "yes", "action": "buy",
           "count": 5, "priceCents": 41}
    book = {"yesBid": 40.0, "yesAsk": 41.0, "source": "kalshi-rest",
            "yesLevels": [{"price": 40.0, "count": 500}],
            "noLevels": [{"price": 59.0, "count": 500}]}

    pv = terminal.preview(req, cfg={}, authed=True, market=market,
                          book_snapshot=book, position=None,
                          exchange_status=_status(off=(2,)))
    assert any("halted" in b for b in pv["blockers"]), pv["blockers"]

    ok = terminal.preview(req, cfg={}, authed=True, market=market,
                          book_snapshot=book, position=None,
                          exchange_status=_status())
    assert not any("halted" in b for b in ok["blockers"]), ok["blockers"]


def test_a_market_on_a_running_shard_is_unaffected_by_another_shards_halt():
    """A crypto halt must not stop someone trading politics."""
    import terminal
    market = terminal.market_row({
        "ticker": "KXPRES-X", "title": "t", "status": "active",
        "yes_bid_dollars": "0.4000", "yes_ask_dollars": "0.4100",
        "close_time": "2099-01-01T00:00:00Z", "exchange_index": 0,
    })
    pv = terminal.preview(
        {"ticker": "KXPRES-X", "side": "yes", "action": "buy",
         "count": 5, "priceCents": 41},
        cfg={}, authed=True, market=market,
        book_snapshot={"yesBid": 40.0, "yesAsk": 41.0, "source": "kalshi-rest",
                       "yesLevels": [], "noLevels": []},
        position=None, exchange_status=_status(off=(2,)))
    assert not any("halted" in b for b in pv["blockers"]), pv["blockers"]



_UNF = {"error": {"code": "user_not_found:_f6a16bc5", "message": "user not found: f6a16bc5"}}


def _unf_error():
    return kalshi_api.KalshiAPIError(400, _UNF)


def test_the_rejection_is_recognised():
    assert kalshi_api.is_user_not_found(_unf_error())
    assert not kalshi_api.is_user_not_found(
        kalshi_api.KalshiAPIError(400, {"error": {"code": "insufficient_balance"}}))
    assert not kalshi_api.is_user_not_found(ValueError("nope"))


def test_an_unfunded_shard_is_named_as_the_cause(monkeypatch):
    """Balance reads fine, so the credential is valid — the engine hosting the
    market simply holds none of the user's collateral."""
    async def _bal(pin_env=None):
        return {"total_balance_cents": 25000, "sharded": True,
                "shard_balances": {0: 250.0, 2: 0.0}}
    monkeypatch.setattr(kalshi_api, "get_balance", _bal)

    msg = run(kalshi_api.explain_order_rejection(
        _unf_error(), ticker="KXBTC15M-X", exchange_index=2))
    assert "crypto" in msg
    assert "$0.00" in msg
    assert "general $250.00" in msg, msg
    assert "Re-add your keys" not in msg


def test_a_dead_or_wrong_environment_credential_is_named_instead(monkeypatch):
    """Balance fails the SAME way, so the account itself is not recognised —
    the opposite fix: re-add the keys."""
    async def _bal(pin_env=None):
        raise kalshi_api.KalshiAPIError(400, _UNF)
    monkeypatch.setattr(kalshi_api, "get_balance", _bal)

    msg = run(kalshi_api.explain_order_rejection(
        _unf_error(), ticker="KXBTC15M-X", exchange_index=2))
    assert "re-add it under API Keys" in msg
    assert "kalshi.com" in msg
    assert "collateral" not in msg


def test_an_undiagnosable_failure_says_so_rather_than_guessing(monkeypatch):
    async def _bal(pin_env=None):
        raise RuntimeError("connection reset")
    monkeypatch.setattr(kalshi_api, "get_balance", _bal)

    msg = run(kalshi_api.explain_order_rejection(
        _unf_error(), ticker="KXBTC15M-X", exchange_index=2))
    assert "could not tell" in msg


def test_an_unrelated_rejection_is_passed_through_untouched(monkeypatch):
    """No extra balance call, no invented explanation."""
    called = []

    async def _bal(pin_env=None):
        called.append(1)
        return {}
    monkeypatch.setattr(kalshi_api, "get_balance", _bal)

    err = kalshi_api.KalshiAPIError(400, {"error": {"code": "insufficient_balance"}})
    msg = run(kalshi_api.explain_order_rejection(err, ticker="X"))
    assert msg == str(err)
    assert not called, "an unrelated error must not trigger a balance probe"



@pytest.fixture
def shard_env(monkeypatch):
    """A known series->shard map and a known balance cache, both restored."""
    import crypto15m_trader, trader, kalshi_auth
    monkeypatch.setitem(kalshi_api._series_shard, "KXBTC15M", 2)
    monkeypatch.setattr(kalshi_auth, "_current_env", "demo", raising=False)

    def set_balance(shards):
        trader._balance_cache["demo"] = {
            "cents": 25000, "portfolio_cents": 0, "at": 0.0, "shards": shards}
    monkeypatch.setattr(trader, "_balance_cache", dict(trader._balance_cache))
    return crypto15m_trader, set_balance


def test_an_empty_shard_is_refused_by_name(shard_env):
    c15, set_balance = shard_env
    set_balance({0: 250.0, 2: 0.0})
    assert c15._unfunded_shard("KXBTC15M-26AUG251015-15") == "crypto"


def test_a_funded_shard_places_normally(shard_env):
    c15, set_balance = shard_env
    set_balance({0: 250.0, 2: 40.0})
    assert c15._unfunded_shard("KXBTC15M-26AUG251015-15") is None


def test_the_check_fails_open_on_every_unknown(shard_env):
    """Three different unknowns, one rule: never block on a number we could not
    read. A lockout caused by an unreadable balance would be a worse failure
    than the rejection this prevents."""
    c15, set_balance = shard_env

    set_balance({0: 250.0, 2: 0.0})
    assert c15._unfunded_shard("KXNEVERSEEN-1") is None

    set_balance({})
    assert c15._unfunded_shard("KXBTC15M-X") is None

    set_balance({0: 250.0})
    assert c15._unfunded_shard("KXBTC15M-X") is None


def test_an_unknown_series_is_not_assumed_to_be_shard_zero():
    """Defaulting an unknown series to 0 would check the wrong shard's money."""
    assert kalshi_api.shard_for_ticker("KXTOTALLYUNKNOWN-1") is None
    assert kalshi_api.shard_for_ticker("") is None


def test_the_shard_map_fills_itself_from_ordinary_market_reads():
    """It is populated as a side effect of reads the app already makes, so the
    entry path never needs a lookup of its own."""
    kalshi_api._series_shard.pop("KXPROBE", None)
    kalshi_api._note_shard({"ticker": "KXPROBE-26AUG25-T1", "exchange_index": 3})
    assert kalshi_api.shard_for_ticker("KXPROBE-26AUG25-T1") == 3
    kalshi_api._series_shard.pop("KXNOIDX", None)
    kalshi_api._note_shard({"ticker": "KXNOIDX-1"})
    assert kalshi_api.shard_for_ticker("KXNOIDX-1") is None



def test_the_transfer_url_is_kalshi_com_whatever_it_is_asked():
    """One Kalshi web host. Paper has no shards, and an old env name must not
    produce a broken (or retired) URL."""
    for env in ("production", "paper", "demo", "something-else"):
        assert (kalshi_api.web_exchange_indexes_url(env)
                == "https://kalshi.com/account/exchange-indexes")


def test_every_unfunded_shard_message_says_where_to_go(monkeypatch):
    """A warning about collateral is only actionable with a destination, so the
    page is named in the rejection diagnosis as well as in the UI."""
    async def _bal(pin_env=None):
        return {"total_balance_cents": 25000, "sharded": True,
                "shard_balances": {0: 250.0, 2: 0.0}}
    monkeypatch.setattr(kalshi_api, "get_balance", _bal)
    msg = run(kalshi_api.explain_order_rejection(
        _unf_error(), ticker="KXBTC15M-X", exchange_index=2))
    assert "/account/exchange-indexes" in msg, msg



def test_the_crypto_status_reports_its_shard_funding(shard_env):
    c15, set_balance = shard_env
    set_balance({0: 250.0, 2: 0.0})
    f = c15._shard_funding({"crypto15m_order_size": 3, "crypto15m_max_concurrent": 4})
    assert f["starved"] is True
    assert f["name"] == "crypto"
    assert f["cashUsd"] == 0.0
    assert f["perEntryMaxUsd"] == 3.0
    assert f["allOpenMaxUsd"] == 12.0
    assert f["shards"] == [{"index": 0, "name": "general", "cashUsd": 250.0},
                           {"index": 2, "name": "crypto", "cashUsd": 0.0}]
    assert "/account/exchange-indexes" in f["transferUrl"]


def test_the_crypto_status_does_not_cry_starved_on_an_unknown_balance(shard_env):
    """Same fail-open rule as the entry check: an unread balance is not a zero,
    and a banner shown on one would tell users to move money they already have."""
    c15, set_balance = shard_env
    set_balance({})
    f = c15._shard_funding({})
    assert f["starved"] is False and f["known"] is False
    assert f["cashUsd"] is None

    set_balance({0: 250.0, 2: 40.0})
    assert c15._shard_funding({})["starved"] is False



@pytest.mark.parametrize("kw,expect", [
    (dict(amount_usd=0, source_shard=0, destination_shard=2), "more than $0.00"),
    (dict(amount_usd=-5, source_shard=0, destination_shard=2), "more than $0.00"),
    (dict(amount_usd=float("nan"), source_shard=0, destination_shard=2), "real number"),
    (dict(amount_usd=float("inf"), source_shard=0, destination_shard=2), "real number"),
    (dict(amount_usd="abc", source_shard=0, destination_shard=2), "must be a number"),
    (dict(amount_usd=10, source_shard=2, destination_shard=2), "same exchange"),
    (dict(amount_usd=10, source_shard=0, destination_shard=999), "out of range"),
    (dict(amount_usd=0.004, source_shard=0, destination_shard=2), "rounds to $0.00"),
])
def test_a_hostile_transfer_is_refused_before_any_request(kw, expect, monkeypatch):
    called = []

    async def _bal(pin_env=None):
        called.append(1)
        return {}
    monkeypatch.setattr(kalshi_api, "get_balance", _bal)

    with pytest.raises(ValueError) as ei:
        run(kalshi_api.transfer_between_shards(**kw))
    assert expect in str(ei.value)
    assert not called, "validation must fail before the balance is even read"


def test_a_transfer_cannot_overdraw_its_source(monkeypatch):
    async def _bal(pin_env=None):
        return {"shard_balances": {0: 12.34, 2: 0.0}}
    monkeypatch.setattr(kalshi_api, "get_balance", _bal)
    with pytest.raises(ValueError) as ei:
        run(kalshi_api.transfer_between_shards(
            amount_usd=12.35, source_shard=0, destination_shard=2))
    assert "holds $12.34" in str(ei.value)


def test_the_amount_reaches_kalshi_in_centicents(monkeypatch):
    """Dollars x 10,000. This is a THIRD money unit alongside the cents and the
    dollar-strings already on the wire, and the one where an off-by-100 moves a
    hundred times the intended amount of real money."""
    sent = {}

    async def _bal(pin_env=None):
        return {"shard_balances": {0: 500.0, 2: 0.0}}

    async def _req(method, path, **kw):
        sent.update(kw.get("json") or {})
        sent["__path"] = path
        return {"transfer_id": "t1"}

    monkeypatch.setattr(kalshi_api, "get_balance", _bal)
    monkeypatch.setattr(kalshi_api, "_signed_request", _req)

    run(kalshi_api.transfer_between_shards(
        amount_usd=12.00, source_shard=0, destination_shard=2))
    assert sent["amount"] == 120_000, sent
    assert sent["source_exchange_shard"] == 0
    assert sent["destination_exchange_shard"] == 2
    assert sent["source"] == "event_contract"
    assert sent["destination"] == "event_contract"
    assert sent["__path"].endswith("/portfolio/intra_exchange_instance_transfer")


def test_a_sub_cent_remainder_is_dropped_not_rounded_up(monkeypatch):
    """Rounding a fraction of a cent UP would move money the user did not
    authorise. $1.239 moves $1.23."""
    sent = {}

    async def _bal(pin_env=None):
        return {"shard_balances": {0: 500.0}}

    async def _req(method, path, **kw):
        sent.update(kw.get("json") or {})
        return {"transfer_id": "t"}

    monkeypatch.setattr(kalshi_api, "get_balance", _bal)
    monkeypatch.setattr(kalshi_api, "_signed_request", _req)
    run(kalshi_api.transfer_between_shards(
        amount_usd=1.239, source_shard=0, destination_shard=2))
    assert sent["amount"] == 12_300, sent
