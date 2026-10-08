"""Paper mode: the app-wide account mode that replaced Kalshi's demo exchange.

What is pinned here, and why each matters:

  * Migration. A demo profile lands on Paper; a production profile lands on
    Live so an existing live trader's app does not silently stop (or change)
    trading; a config that already names its mode keeps it.
  * The seam. In Paper NO real order is reachable from any engine: every
    account call in kalshi_api routes to paper_exchange, `_signed_request`
    refuses, and `kalshi_auth.sign_headers` refuses before a key is read. The
    tests below make signing itself an assertion failure and drive each
    engine's real code path.
  * Master only narrows. Paper overrides every engine's own live switch; an
    engine's live switch never widens Paper.
  * No account needed. Paper reads Kalshi's public market data unsigned and
    works with no credentials on disk at all.
  * Scoping. Paper rows and live rows never count toward each other's caps,
    exposure or ownership; old demo rows count toward neither.
"""
from __future__ import annotations

import asyncio

import pytest

import config
import db
import kalshi_api
import kalshi_auth
import kalshi_perps_api
import mcp_agents
import mcp_server
import paper_book
import paper_exchange
import terminal
import trader
from config import merge_with_defaults


def run(coro):
    return asyncio.run(coro)



@pytest.fixture
def paper_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "paper-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    monkeypatch.setenv("KRYPT_TRADER_USERDATA", str(tmp_path))
    kalshi_auth.reset_credential_cache()
    monkeypatch.setattr(kalshi_auth, "_current_env", kalshi_auth.PAPER, raising=False)
    monkeypatch.setattr(trader, "_balance_cache", {}, raising=False)
    paper_exchange.set_bankroll(1000.0)
    yield dbfile


@pytest.fixture
def no_signing(monkeypatch):
    """Signing anything, or opening the signed client, fails the test."""
    def _sign(*_a, **_k):
        raise AssertionError("a request was signed in Paper mode")

    async def _client(*_a, **_k):
        raise AssertionError("the signed Kalshi client was opened in Paper mode")

    monkeypatch.setattr(kalshi_api, "sign_headers", _sign)
    monkeypatch.setattr(kalshi_perps_api, "sign_headers", _sign)
    monkeypatch.setattr(kalshi_api, "_get_signed_client", _client)
    monkeypatch.setattr(kalshi_perps_api, "_get_signed_client", _client)


@pytest.fixture
def public_book(monkeypatch):
    """Kalshi's PUBLIC order book (unsigned), scripted. YES bids at 58c and
    NO bids at 40c — i.e. YES is offered at 60c — 100 deep each."""
    state = {"book": {"yes": [[58, 100]], "no": [[40, 100]]}, "urls": []}

    async def _pub_get(url, params=None):
        state["urls"].append(url)
        if url.endswith("/orderbook"):
            return {"orderbook": state["book"]}
        return None

    monkeypatch.setattr(kalshi_api, "_pub_get", _pub_get)
    return state



def test_a_demo_profile_lands_on_paper():
    cfg = merge_with_defaults({"kalshi_env": "demo", "enable_trading": True})
    assert cfg["account_mode"] == "paper"
    assert "kalshi_env" not in cfg
    assert cfg["enable_trading"] is True


def test_a_production_profile_lands_on_live_with_its_switches_untouched():
    """An existing live trader's app keeps doing exactly what it did."""
    user = {"kalshiEnv": "production", "crypto15mLive": True, "scriptsLiveEnabled": True,
            "mcpTradeMode": "live", "enableTrading": True}
    cfg = merge_with_defaults(user)
    assert cfg["account_mode"] == "live"
    assert cfg["crypto15m_live"] is True and cfg["scripts_live_enabled"] is True
    assert cfg["mcp_trade_mode"] == "live" and cfg["enable_trading"] is True


def test_no_env_at_all_is_paper_and_garbage_is_paper():
    assert merge_with_defaults({})["account_mode"] == "paper"
    assert merge_with_defaults({"account_mode": "LIVE!"})["account_mode"] == "paper"
    assert merge_with_defaults({"accountMode": "live"})["account_mode"] == "live"


def test_migration_is_idempotent_and_an_explicit_mode_wins():
    once = merge_with_defaults({"kalshi_env": "production"})
    assert merge_with_defaults(dict(once)) == once
    assert merge_with_defaults({"account_mode": "paper", "kalshi_env": "production"})[
        "account_mode"] == "paper"


def test_the_agents_paper_bankroll_becomes_the_one_paper_bankroll():
    cfg = merge_with_defaults({"mcp_paper_bankroll_usd": 250.0})
    assert cfg["paper_bankroll_usd"] == 250.0
    assert "mcp_paper_bankroll_usd" not in cfg
    assert merge_with_defaults({"paper_bankroll_usd": 5.0})["paper_bankroll_usd"] >= 10.0


def test_the_backend_starts_in_paper():
    assert kalshi_auth.DEFAULT_ENV == kalshi_auth.PAPER
    assert config.DEFAULT_CONFIG["account_mode"] == "paper"
    assert config.scope_env({}) == "paper"
    assert config.scope_env({"account_mode": "live"}) == "production"



def test_every_account_call_routes_to_paper_and_signs_nothing(paper_db, no_signing, public_book):
    r = run(kalshi_api.place_limit_order(ticker="KXT-1", side="yes", action="buy",
                                         count=5, price_cents=62, client_order_id="c1"))
    oid = r["order"]["order_id"]
    assert oid.startswith("paper-") and r["order"]["status"] == "executed"
    assert run(kalshi_api.get_order(oid))["order"]["fill_count_fp"] == "5.00"
    assert run(kalshi_api.find_order_by_client_id("c1"))["order_id"] == oid
    assert [f["order_id"] for f in run(kalshi_api.get_fills_for_order(oid))] == [oid]
    assert run(kalshi_api.get_fills_since(0))
    pos = run(kalshi_api.get_positions())
    assert [(p["ticker"], p["position_fp"]) for p in pos] == [("KXT-1", "5.00")]
    assert run(kalshi_api.get_settled_positions()) == []
    bal = run(kalshi_api.get_balance())
    assert bal["paper"] is True and bal["total_balance_cents"] < 100_000
    assert run(kalshi_api.fetch_orders(status="resting")) == []
    for coro in (kalshi_api.get_account_limits(), kalshi_api.upgrade_api_usage_level()):
        with pytest.raises(kalshi_api.KalshiAPIError) as ei:
            run(coro)
        assert ei.value.status == 403 and "paper_mode" in str(ei.value.body)
    with pytest.raises(kalshi_api.KalshiAPIError):
        run(kalshi_api.transfer_between_shards(amount_usd=5, source_shard=0,
                                               destination_shard=2))


def test_a_pinned_live_call_in_paper_is_refused_not_signed(paper_db, no_signing):
    """The 15m cross-env sweep pins order lookups to a row's own scope. In
    Paper a LIVE row's lookup must not sign for the real account."""
    with pytest.raises(kalshi_api.KalshiAPIError):
        run(kalshi_api.get_order("live-order", pin_env="production"))
    with pytest.raises(kalshi_api.KalshiAPIError):
        run(kalshi_api.cancel_order("live-order", pin_env="production"))


def test_sign_headers_itself_refuses_in_paper(paper_db):
    with pytest.raises(kalshi_auth.PaperModeError):
        kalshi_auth.sign_headers("POST", "/trade-api/v2/portfolio/events/orders")


def test_the_auto_trader_trades_paper_through_its_real_path(paper_db, no_signing, public_book, monkeypatch):
    async def _empty(_t):
        return {}
    monkeypatch.setattr(trader, "get_orderbook", _empty)
    monkeypatch.setattr(trader, "get_env", lambda: "paper")
    cfg = merge_with_defaults({"enable_trading": True})
    sig = {"id": 7, "ticker": "KXT-2", "event_ticker": "", "title": "t",
           "category": "sports", "price": 0.60, "confidence": 80.0, "taker_side": "yes"}
    row = run(trader.execute_signal(sig, "whale", cfg, 1000.0))
    assert row["kalshi_env"] == "paper" and row["kalshi_order_id"].startswith("paper-")
    updated = run(trader.poll_open_orders(cfg))
    assert updated and updated[0]["status"] == "filled"
    assert updated[0]["avg_fill_price_cents"] == pytest.approx(60.0)
    with db.get_db() as conn:
        assert db.count_open_bot_positions(conn, "paper") == 1
        assert db.count_open_bot_positions(conn, "production") == 0


def test_the_terminal_ticket_and_phone_orders_trade_paper(paper_db, no_signing, public_book, monkeypatch):
    async def _none(*_a, **_k):
        return None
    monkeypatch.setattr(kalshi_api, "fetch_market", _none)
    monkeypatch.setattr(kalshi_api, "fetch_exchange_status", _none)
    monkeypatch.setattr(terminal, "book", _none)

    async def _marks(_t):
        return {}
    monkeypatch.setattr(kalshi_api, "fetch_markets_by_tickers", _marks)
    cfg = merge_with_defaults({})
    pv = terminal.preview({"ticker": "KXT-3", "side": "yes", "action": "buy",
                           "count": 3, "priceCents": 61}, cfg=cfg, authed=True,
                          market=None, book_snapshot=None, position=None)
    assert any("PAPER" in w for w in pv["warnings"])
    res = run(terminal.submit({"ticker": "KXT-3", "side": "yes", "action": "buy",
                               "count": 3, "priceCents": 61}, cfg=cfg, authed=True))
    assert res["ok"] and res["filledContracts"] == 3 and res["avgFillCents"] == 60
    pf = run(terminal.portfolio(True))
    assert pf["env"] == "paper"
    assert [(p["ticker"], p["contracts"]) for p in pf["positions"]] == [("KXT-3", 3)]
    assert pf["cashUsd"] is not None and pf["cashUsd"] < 1000.0


def test_scripts_are_forced_onto_their_paper_path_in_paper(paper_db, monkeypatch):
    """scripts_paper_mode off and scripts live on: in Paper every entry is
    still simulated, and run_tick never needs auth to do it."""
    import script_engine
    seen = {}

    async def _snap(_cfg):
        return {"assets": []}

    def _list(_conn):
        seen["listed"] = True
        return []

    monkeypatch.setattr(script_engine.crypto15m, "snapshot", _snap)
    monkeypatch.setattr(script_engine.db, "list_user_scripts", _list)
    run(script_engine.run_tick(merge_with_defaults(
        {"scripts_live_enabled": True, "scripts_paper_mode": False}), authed=False))
    assert seen.get("listed") is True


def test_perps_never_run_in_paper(paper_db, no_signing):
    with pytest.raises(kalshi_api.KalshiAPIError):
        run(kalshi_perps_api._signed_request("GET", "/margin/balance"))



@pytest.mark.parametrize("account,agents,expected", [
    ("paper", "off", "off"), ("paper", "paper", "paper"), ("paper", "live", "paper"),
    ("live", "off", "off"), ("live", "paper", "paper"), ("live", "live", "live"),
])
def test_agent_trade_mode_is_narrowed_by_the_account(account, agents, expected, monkeypatch):
    monkeypatch.setattr(kalshi_auth, "_current_env",
                        "production" if account == "live" else "paper", raising=False)
    cfg = {"account_mode": account, "mcp_trade_mode": agents}
    assert mcp_server.trade_mode(cfg) == expected
    agent = {"id": "default", "mode": "live"}
    eff = mcp_agents.effective_mode(mcp_server.trade_mode(cfg), agent)
    assert eff != "live" or account == "live"


def test_a_live_setting_on_a_paper_scope_is_still_paper(monkeypatch):
    """Both the setting and the scope in force must say Live."""
    monkeypatch.setattr(kalshi_auth, "_current_env", "paper", raising=False)
    assert mcp_server.trade_mode({"account_mode": "live", "mcp_trade_mode": "live"}) == "paper"


@pytest.mark.parametrize("account,c15_live,runner_mode,real", [
    ("paper", True, "live", False), ("paper", False, "live", False),
    ("paper", True, "paper", False), ("live", True, "live", True),
    ("live", False, "live", False), ("live", True, "paper", False),
])
def test_15m_real_orders_matrix(account, c15_live, runner_mode, real, paper_db, monkeypatch):
    import crypto15m_trader as ct
    env = "production" if account == "live" else "paper"
    monkeypatch.setattr(trader, "get_env", lambda: env)
    cfg = merge_with_defaults({
        "account_mode": account, "crypto15m_enabled": True, "crypto15m_live": c15_live,
        "crypto15m_runners": [{"id": "r1", "name": "r1", "coins": ["BTC"],
                               "mode": runner_mode, "enabled": True, "config": {}}],
    })
    st = run(ct.status(cfg, authed=True))
    assert st["runners"][0]["realOrders"] is real
    assert st["paperAccount"] is (account == "paper")



def test_paper_reads_public_market_data_with_no_credentials(paper_db, no_signing, public_book):
    assert not kalshi_auth.credentials_present()
    book = run(kalshi_api.get_orderbook("KXT-4"))
    assert book["yes"] and book["no"]
    assert public_book["urls"] == [f"{kalshi_api.PUBLIC_BASE}/markets/KXT-4/orderbook"]
    bal = run(paper_exchange.balance())
    assert bal["total_balance_cents"] == 100_000


def test_the_websocket_never_dials_in_paper():
    import kalshi_ws
    c = kalshi_ws._client.__class__()
    c.set_env("paper")
    assert c.env == "paper"
    calls = {"n": 0}

    async def go():
        orig = asyncio.sleep

        async def fast(_s):
            calls["n"] += 1
            await orig(0)
        asyncio.sleep = fast
        try:
            await c._connect_once(c._gen)
        finally:
            asyncio.sleep = orig
    run(go())
    assert calls["n"] == 1 and not c.connected



def test_a_limit_that_crosses_nothing_rests_and_fills_when_the_book_crosses(paper_db, no_signing, public_book):
    r = run(paper_exchange.place_order(ticker="KXT-5", side="yes", action="buy",
                                       count=10, price_cents=55, client_order_id="r1"))
    o = r["order"]
    assert o["status"] == "resting" and o["fill_count_fp"] == "0.00"
    public_book["book"] = {"yes": [[50, 10]], "no": [[46, 4]]}
    run(paper_exchange.sweep())
    o = run(paper_exchange.get_order(o["order_id"]))["order"]
    assert o["fill_count_fp"] == "4.00" and o["status"] == "resting"
    assert float(o["taker_fill_cost_dollars"]) == pytest.approx(4 * 0.55)
    run(paper_exchange.cancel_order(o["order_id"]))
    with pytest.raises(kalshi_api.KalshiAPIError) as ei:
        run(paper_exchange.cancel_order(o["order_id"]))
    assert ei.value.status == 404


def test_liquidity_already_taken_never_fills_the_same_order_twice(paper_db, no_signing, public_book):
    """A paper fill does not deplete the real book. The 100 offered at 60c
    that filled this order on entry is still on screen at the next sweep, and
    must not fill its resting remainder too; only NEW depth may."""
    o = run(paper_exchange.place_order(ticker="KXT-10", side="yes", action="buy",
                                       count=150, price_cents=62, client_order_id="big"))["order"]
    assert o["fill_count_fp"] == "100.00" and o["status"] == "resting"
    for _ in range(3):
        run(paper_exchange.sweep())
    assert run(paper_exchange.get_order(o["order_id"]))["order"]["fill_count_fp"] == "100.00"
    public_book["book"] = {"yes": [[58, 100]], "no": [[40, 130]]}
    run(paper_exchange.sweep())
    assert run(paper_exchange.get_order(o["order_id"]))["order"]["fill_count_fp"] == "130.00"


def test_paper_refuses_what_kalshi_would_and_what_it_cannot_honestly_model(paper_db, public_book):
    with pytest.raises(kalshi_api.KalshiAPIError) as ei:
        run(paper_exchange.place_order(ticker="KXT-6", side="yes", action="sell",
                                       count=1, price_cents=50, client_order_id="s1"))
    assert "hold 0" in str(ei.value.body)
    paper_exchange.set_bankroll(10.0)
    with pytest.raises(kalshi_api.KalshiAPIError) as ei:
        run(paper_exchange.place_order(ticker="KXT-6", side="yes", action="buy",
                                       count=100, price_cents=60, client_order_id="b1"))
    assert "insufficient_balance" in str(ei.value.body)
    paper_exchange.set_bankroll(1000.0)
    run(paper_exchange.place_order(ticker="KXT-6", side="yes", action="buy",
                                   count=1, price_cents=60, client_order_id="b2"))
    with pytest.raises(kalshi_api.KalshiAPIError) as ei:
        run(paper_exchange.place_order(ticker="KXT-6", side="yes", action="buy",
                                       count=1, price_cents=60, client_order_id="b2"))
    assert ei.value.status == 409 and "duplicate" in str(ei.value.body)


def test_holding_both_sides_nets_to_a_dollar_a_pair(paper_db, public_book):
    run(paper_exchange.place_order(ticker="KXT-7", side="yes", action="buy",
                                   count=3, price_cents=60, client_order_id="y"))
    cash_before = paper_book.book_cash(1000.0)
    run(paper_exchange.place_order(ticker="KXT-7", side="no", action="buy",
                                   count=2, price_cents=42, client_order_id="n"))
    pos = run(paper_exchange.positions())
    assert [(p["ticker"], p["position"]) for p in pos] == [("KXT-7", 1)]
    fee = terminal._fee_usd(42, 2)
    assert paper_book.book_cash(1000.0) == pytest.approx(cash_before - 0.84 - fee + 2.0)


def test_the_balance_is_one_book_including_the_15m_simulation(paper_db, public_book):
    with db.get_db() as conn:
        db.insert_crypto15m_position(conn, dict(
            asset="BTC", series="KXBTC15M", ticker="KXBTC15M-P", side="up", direction="yes",
            target_contracts=2, filled_contracts=2, entry_limit_cents=50, avg_entry_cents=50,
            cost_usd=1.0, status="filled", kalshi_env="paper", dry_run=1, client_order_id="p15"))
        db.insert_crypto15m_position(conn, dict(
            asset="ETH", series="KXETH15M", ticker="KXETH15M-L", side="up", direction="yes",
            target_contracts=5, filled_contracts=5, entry_limit_cents=50, avg_entry_cents=50,
            cost_usd=2.5, status="filled", kalshi_env="production", dry_run=1, client_order_id="l15"))
    assert paper_book.book_cash(1000.0) == pytest.approx(999.0)


def test_reset_starts_the_paper_book_over_and_touches_nothing_live(paper_db, public_book):
    run(paper_exchange.place_order(ticker="KXT-8", side="yes", action="buy",
                                   count=2, price_cents=60, client_order_id="z"))
    with db.get_db() as conn:
        for env in ("paper", "production", "demo"):
            db.insert_bot_position(conn, {
                "signal_source": "whale", "signal_id": hash(env) % 1000, "ticker": f"KX-{env}",
                "direction": "yes", "target_contracts": 1, "limit_price_cents": 50,
                "client_order_id": f"reset-{env}", "status": "filled", "kalshi_env": env})
    removed = run(paper_exchange.reset_account())
    assert removed["paper_fills"] >= 1 and removed["bot_positions"] == 1
    with db.get_db() as conn:
        envs = sorted(r[0] for r in conn.execute("SELECT kalshi_env FROM bot_positions"))
        assert envs == ["demo", "production"]
        assert conn.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0] == 0
    assert paper_book.book_cash(1000.0) == pytest.approx(1000.0)



def test_paper_live_and_retired_rows_never_count_toward_each_other(paper_db):
    with db.get_db() as conn:
        for i, env in enumerate(("paper", "paper", "production", "demo")):
            db.insert_bot_position(conn, {
                "signal_source": "whale", "signal_id": 100 + i, "ticker": f"KX-S{i}",
                "direction": "yes", "target_contracts": 10, "limit_price_cents": 50,
                "filled_contracts": 10, "cost_usd": 5.0,
                "client_order_id": f"scope-{i}", "status": "filled", "kalshi_env": env})
        assert db.count_open_bot_positions(conn, "paper") == 2
        assert db.count_open_bot_positions(conn, "production") == 1
        assert db.open_filled_cost_usd(conn, "production") == pytest.approx(5.0)
        assert db.current_total_exposure_usd(conn, "paper") == pytest.approx(10.0)


def test_the_account_is_not_an_agent(paper_db, public_book):
    """The paper account books its fills in the shared ledger as 'account'.
    No agent can be named that, and the agents' views and loss stop leave the
    account's trading out."""
    assert not mcp_agents.valid_id("account")
    assert mcp_agents.clean_agent({"id": "account", "name": "x"}) is None
    run(paper_exchange.place_order(ticker="KXT-9", side="yes", action="buy",
                                   count=2, price_cents=60, client_order_id="acct"))
    assert "account" not in paper_book.agent_ids()
    assert paper_book.open_tickers(agents_only=True) == []
    assert paper_book.open_tickers() == ["KXT-9"]
    assert paper_book.portfolio(1000.0)["positions"] == []
    assert paper_book.held("KXT-9", "yes") == 0



@pytest.fixture
def svc(paper_db, monkeypatch):
    import service
    events = []

    async def _emit(name, data=None):
        events.append(name)

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(service, "emit_event", _emit)
    monkeypatch.setattr(service, "_sync_remote_bots", _noop)
    monkeypatch.setattr(service, "_sync_mcp", _noop)
    monkeypatch.setattr(service, "_prune_deleted_agent_tokens", lambda *_a, **_k: None)
    monkeypatch.setattr(service.STATE, "active_run_id", 0, raising=False)
    monkeypatch.setattr(service.STATE, "cfg", dict(service.STATE.cfg), raising=False)
    monkeypatch.setattr(kalshi_auth, "_current_env", "production", raising=False)
    monkeypatch.setattr(service.STATE, "auth_ok", False, raising=False)
    return service


def test_paper_is_ready_with_no_kalshi_account(svc, no_signing, public_book):
    run(svc._h_setConfig({"config": {"accountMode": "paper", "paperBankrollUsd": 500}}))
    assert kalshi_auth.get_env() == "paper"
    assert svc.STATE.auth_ok is True
    snap = run(svc._build_account_snapshot())
    assert snap["accountMode"] == "paper"
    assert snap["cashUsd"] == pytest.approx(500.0)
    assert snap["startBankrollUsd"] == pytest.approx(500.0)
    assert snap["bankrollSource"] == "paper"


def test_live_without_a_key_is_not_authenticated(svc, no_signing):
    run(svc._h_setConfig({"config": {"accountMode": "paper"}}))
    run(svc._h_setConfig({"config": {"accountMode": "live"}}))
    assert kalshi_auth.get_env() == "production"
    assert svc.STATE.auth_ok is False


def test_paper_reset_handler_puts_cash_back(svc, public_book):
    run(svc._h_setConfig({"config": {"accountMode": "paper"}}))
    run(paper_exchange.place_order(ticker="KXT-11", side="yes", action="buy",
                                   count=5, price_cents=62, client_order_id="rs"))
    assert run(svc._h_paper_status({}))["cashUsd"] < 1000.0
    out = run(svc._h_paper_reset({}))
    assert out["ok"] is True
    assert run(svc._h_paper_status({}))["cashUsd"] == pytest.approx(1000.0)


def test_a_new_starting_balance_applies_at_reset_never_mid_book(svc, public_book):
    """Typing a bigger bankroll must not be booked as an instant gain by every
    balance-delta P&L and daily-risk check; it applies when the book resets."""
    run(svc._h_setConfig({"config": {"accountMode": "paper", "paperBankrollUsd": 1000}}))
    assert run(svc._h_paper_status({}))["cashUsd"] == pytest.approx(1000.0)
    run(svc._h_setConfig({"config": {"accountMode": "paper", "paperBankrollUsd": 5000}}))
    st = run(svc._h_paper_status({}))
    assert st["cashUsd"] == pytest.approx(1000.0)
    assert st["bankrollUsd"] == pytest.approx(1000.0) and st["nextBankrollUsd"] == pytest.approx(5000.0)
    run(svc._h_paper_reset({}))
    assert run(svc._h_paper_status({}))["cashUsd"] == pytest.approx(5000.0)



@pytest.mark.parametrize("decided,now", [("paper", "production"), ("production", "paper")])
def test_an_order_decided_in_one_scope_is_never_sent_in_the_other(decided, now, paper_db,
                                                                no_signing, public_book):
    """A buy sized from the paper balance and booked as a paper row must not
    go out with real money after a Go live in the seconds before it is sent —
    nor a live exit sell paper contracts after a switch back. Refused before
    it is routed or signed, and marked as not delivered."""
    kalshi_auth._current_env = now
    with pytest.raises(kalshi_api.KalshiAPIError) as ei:
        run(kalshi_api.place_limit_order(ticker="KXT-12", side="yes", action="buy",
                                         count=1, price_cents=60, client_order_id="sc",
                                         pin_env=decided))
    assert kalshi_api.is_scope_changed(ei.value)
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0] == 0
    with pytest.raises(kalshi_api.KalshiAPIError):
        run(kalshi_api.get_positions(pin_env=decided))


def test_a_terminal_rule_or_ticket_decided_in_paper_is_not_sent_live(paper_db, monkeypatch):
    sent = []

    async def _place(**kw):
        sent.append(kw)
        return {"order": {"order_id": "x"}}
    monkeypatch.setattr(kalshi_api, "place_limit_order", _place)
    kalshi_auth._current_env = "production"
    res = run(terminal.submit({"ticker": "KXT-13", "side": "yes", "action": "sell",
                               "count": 1, "priceCents": 50},
                              cfg=merge_with_defaults({}), authed=True, scope="paper"))
    assert res["ok"] is False and "switched between Paper and Live" in res["message"]
    assert sent == []


def test_a_phone_quote_made_on_paper_is_never_confirmed_into_real_money(paper_db, monkeypatch):
    import remote
    submitted = []

    async def _submit(req, **kw):
        submitted.append(req)
        return {"ok": True, "message": "sent"}
    monkeypatch.setattr(terminal, "submit", _submit)
    remote.STATE.pending["discord:1"] = remote.Pending(
        code="123456", req={"ticker": "KXT-14"}, summary="PAPER quote", env="paper")
    kalshi_auth._current_env = "production"
    out = run(remote._confirm(["123456"], "discord:1", cfg={}, authed=True))
    assert "quoted on PAPER" in out and submitted == []


def test_the_key_id_is_scrubbed_from_logs_even_in_paper(tmp_path, monkeypatch):
    """The first key test now happens in Paper, where nothing is signed — the
    scrubber must still learn the key id, by reading it, not signing with it."""
    import logscrub
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519
    monkeypatch.setenv("KRYPT_TRADER_USERDATA", str(tmp_path))
    key_id = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"
    pem = ed25519.Ed25519PrivateKey.generate().private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    kalshi_auth.save_credentials(key_id, pem)
    kalshi_auth._current_env = "paper"
    logscrub.refresh_known_secrets()
    assert key_id not in logscrub.scrub(f"testing key {key_id} now")
