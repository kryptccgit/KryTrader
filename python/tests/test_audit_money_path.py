"""Pre-release audit (v6), the money path: paper fills and the Paper<->Live seam.

Each test here is a bug that was real on v6-ai-agents before release:

  * a paper order filled TWICE from one offer after a single failed book read
    (the failure read as an empty book and reset what the order had seen), or
    after a sweep holding an older read was applied after an entry fill;
  * two resting paper orders both filled from the same 30-lot offer;
  * a fill across two price levels was booked as one row at the average,
    which the fill parsers rounded, so ledger cost drifted from paper cash;
  * a live agent approval clicked while the app flipped to Paper went out on
    paper, was booked as a LIVE agent fill, and later authorised the agent to
    sell the user's real contracts;
  * a manual order booked its ledger row in whatever scope was in force after
    the submit's awaits, not the one it was sent in;
  * engines cancelled and re-read orders unpinned after awaits;
  * switching to Live left Paper's auth_ok=True standing while the key was
    still being verified;
  * a ticket filled in on PAPER could be sent after a switch to LIVE.
"""
from __future__ import annotations

import asyncio

import pytest

import db
import kalshi_api
import kalshi_auth
import paper_exchange
import terminal
import trader
from config import merge_with_defaults


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def paper_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "audit-paper.db"
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
    def _sign(*_a, **_k):
        raise AssertionError("a request was signed in Paper mode")

    async def _client(*_a, **_k):
        raise AssertionError("the signed Kalshi client was opened in Paper mode")
    monkeypatch.setattr(kalshi_api, "sign_headers", _sign)
    monkeypatch.setattr(kalshi_api, "_get_signed_client", _client)


@pytest.fixture
def public_book(monkeypatch):
    """Kalshi's public order book, scripted; `fail` makes the read fail the
    way a network blip does (no response at all)."""
    state = {"book": {"yes": [[58, 100]], "no": [[40, 100]]}, "fail": False}

    async def _pub_get(url, params=None):
        if state["fail"]:
            return None
        if url.endswith("/orderbook"):
            return {"orderbook": state["book"]}
        return None
    monkeypatch.setattr(kalshi_api, "_pub_get", _pub_get)
    return state


def _filled(oid: str) -> int:
    with db.get_db() as conn:
        return int(conn.execute("SELECT filled FROM paper_orders WHERE order_id=?",
                                (oid,)).fetchone()[0])


def _buy(ticker, count, price, coid):
    return run(kalshi_api.place_limit_order(ticker=ticker, side="yes", action="buy",
                                            count=count, price_cents=price,
                                            client_order_id=coid))["order"]



def test_a_failed_book_read_never_refills_the_same_offer(paper_db, no_signing, public_book):
    public_book["book"] = {"yes": [[50, 100]], "no": [[40, 30]]}
    o = _buy("KXA-1", 100, 60, "a1")
    assert o["fill_count_fp"] == "30.00"
    run(paper_exchange.sweep())
    assert _filled(o["order_id"]) == 30
    public_book["fail"] = True
    run(paper_exchange.sweep())
    public_book["fail"] = False
    run(paper_exchange.sweep())
    assert _filled(o["order_id"]) == 30, "one failed read refilled the same offer"
    with db.get_db() as conn:
        seen = conn.execute("SELECT seen_cross_qty FROM paper_orders WHERE order_id=?",
                            (o["order_id"],)).fetchone()[0]
    assert seen == 30
    public_book["fail"] = True
    assert run(kalshi_api.read_orderbook("KXA-1")) is None
    assert run(kalshi_api.get_orderbook("KXA-1")) == {"yes": [], "no": []}


def test_an_older_sweep_read_is_not_applied_after_an_entry_fill(paper_db, monkeypatch):
    t = "KXA-2"
    full = {"yes": [], "no": [{"priceCents": 40.0, "contracts": 30}]}
    thin = {"yes": [], "no": [{"priceCents": 40.0, "contracts": 10}]}

    async def scenario():
        gate = asyncio.Event()

        async def _now_book(_t):
            return {"yes": [], "no": [dict(lv) for lv in full["no"]]}

        async def _stale_book(_t):
            await gate.wait()
            return thin

        monkeypatch.setattr(paper_exchange, "_book", _now_book)
        x = await paper_exchange.place_order(ticker=t, side="yes", action="buy", count=100,
                                             price_cents=60, client_order_id="x")
        assert x["order"]["fill_count_fp"] == "30.00"
        monkeypatch.setattr(paper_exchange, "_book", _stale_book)
        sweep = asyncio.create_task(paper_exchange._match_resting({t}))
        await asyncio.sleep(0.05)
        monkeypatch.setattr(paper_exchange, "_book", _now_book)
        await paper_exchange.place_order(ticker=t, side="yes", action="buy", count=5,
                                         price_cents=60, client_order_id="y")
        gate.set()
        await sweep
        await paper_exchange._match_resting({t})
        return x["order"]["order_id"]

    oid = run(scenario())
    assert _filled(oid) == 30, "the stale read made the offer look like it left and came back"


def test_two_resting_orders_share_one_offer(paper_db, no_signing, public_book):
    public_book["book"] = {"yes": [[58, 100]], "no": []}
    a = _buy("KXA-3", 50, 60, "a")
    b = _buy("KXA-3", 50, 60, "b")
    assert a["fill_count_fp"] == b["fill_count_fp"] == "0.00"
    public_book["book"] = {"yes": [[58, 100]], "no": [[40, 30]]}
    run(paper_exchange.sweep())
    assert _filled(a["order_id"]) + _filled(b["order_id"]) == 30
    run(paper_exchange.sweep())
    assert _filled(a["order_id"]) + _filled(b["order_id"]) == 30
    public_book["book"] = {"yes": [[58, 100]], "no": [[40, 50]]}
    run(paper_exchange.sweep())
    assert _filled(a["order_id"]) + _filled(b["order_id"]) == 50



def test_a_fill_across_levels_is_booked_per_level_and_matches_the_cash(paper_db, no_signing,
                                                                      public_book):
    public_book["book"] = {"yes": [[30, 10]], "no": [[40, 10], [39, 10]]}
    cash0 = run(kalshi_api.get_balance())["total_balance_cents"]
    o = _buy("KXA-4", 20, 61, "lv")
    assert o["fill_count_fp"] == "20.00"
    fills = run(kalshi_api.get_fills_for_order(o["order_id"]))
    parsed = sorted((trader._parse_kalshi_fill(f)["price_cents"], trader._parse_kalshi_fill(f)["count"])
                    for f in fills)
    assert parsed == [(60, 10), (61, 10)]
    fees = terminal._fee_usd(60, 10) + terminal._fee_usd(61, 10)
    assert float(o["taker_fill_cost_dollars"]) == pytest.approx(12.10)
    assert float(o["taker_fees_dollars"]) == pytest.approx(fees)
    cash1 = run(kalshi_api.get_balance())["total_balance_cents"]
    assert (cash0 - cash1) / 100.0 == pytest.approx(12.10 + fees, abs=0.011)
    n, avg = run(terminal._reconcile_fills(o["order_id"], "yes"))
    assert (n, avg) == (20, 60.5)



def test_the_agent_send_hook_forwards_its_scope_to_the_terminal(monkeypatch):
    import service
    got = {}

    async def _submit(req, *, cfg, authed, scope=None):
        got["scope"] = scope
        return {"ok": False, "message": "x"}
    monkeypatch.setattr(terminal, "submit", _submit)
    monkeypatch.setattr(service.STATE, "paused", False, raising=False)
    run(service._mcp_submit({"ticker": "KXA-5"}, scope="production"))
    assert got["scope"] == "production"
    run(service._h_terminal_submit({"ticker": "KXA-5"}))
    assert got["scope"] is None



def test_a_manual_buy_is_booked_in_its_own_scope_after_a_switch(paper_db, no_signing,
                                                               public_book, monkeypatch):
    async def _none(*_a, **_k):
        return None
    monkeypatch.setattr(kalshi_api, "fetch_market", _none)
    monkeypatch.setattr(kalshi_api, "fetch_exchange_status", _none)
    monkeypatch.setattr(terminal, "book", _none)
    real_place = kalshi_api.place_limit_order

    async def _place_then_switch(**kw):
        out = await real_place(**kw)
        kalshi_auth._current_env = kalshi_auth.PRODUCTION
        return out
    monkeypatch.setattr(kalshi_api, "place_limit_order", _place_then_switch)
    res = run(terminal.submit({"ticker": "KXA-6", "side": "yes", "action": "buy",
                               "count": 3, "priceCents": 41}, cfg=merge_with_defaults({}),
                              authed=True))
    assert res["ok"]
    assert res["reconciled"] is False
    with db.get_db() as conn:
        envs = [r[0] for r in conn.execute(
            "SELECT kalshi_env FROM bot_positions WHERE ticker='KXA-6'").fetchall()]
    assert envs == ["paper"]



def test_cancel_all_pins_every_cancel_and_re_read(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "pin.db")
    db.init_db()
    terminal.record_manual_buy(ticker="KXA-7", side="yes", count=5, price_cents=40,
                               client_order_id="c", order_id="OID-7", status="resting",
                               filled=0, avg_cents=None, fees_usd=None, env="production")
    calls = []

    async def _cancel(oid, **kw):
        calls.append(("cancel", kw.get("pin_env")))
        return {}

    async def _get(oid, **kw):
        calls.append(("get", kw.get("pin_env")))
        return {"order": {"status": "canceled", "fill_count_fp": "0",
                          "remaining_count_fp": "0", "taker_fill_cost_dollars": "0",
                          "maker_fill_cost_dollars": "0"}}
    monkeypatch.setattr(trader, "cancel_order", _cancel)
    monkeypatch.setattr(trader, "get_order", _get)
    assert run(trader.cancel_all_open()) == 1
    assert calls and all(env == "production" for _, env in calls), calls



@pytest.fixture
def svc(paper_db, monkeypatch):
    import service

    async def _noop(*_a, **_k):
        return None
    monkeypatch.setattr(service, "emit_event", _noop)
    monkeypatch.setattr(service, "_sync_remote_bots", _noop)
    monkeypatch.setattr(service, "_sync_mcp", _noop)
    monkeypatch.setattr(service, "_prune_deleted_agent_tokens", lambda *_a, **_k: None)
    monkeypatch.setattr(service.STATE, "active_run_id", 0, raising=False)
    monkeypatch.setattr(service.STATE, "cfg", dict(service.STATE.cfg), raising=False)
    monkeypatch.setattr(service.STATE, "auth_ok", False, raising=False)
    monkeypatch.setattr(kalshi_auth, "_current_env", kalshi_auth.PRODUCTION, raising=False)
    monkeypatch.setattr(kalshi_auth, "credentials_present", lambda: True)
    monkeypatch.setattr(kalshi_auth, "prime_credentials", lambda sync_time=False: None)
    monkeypatch.setattr(kalshi_auth, "sync_server_time", lambda *_a, **_k: None)
    return service


@pytest.mark.parametrize("answers", [True, False])
def test_going_live_never_signs_on_papers_auth(svc, monkeypatch, answers):
    run(svc._h_setConfig({"config": {"accountMode": "paper"}}))
    assert svc.STATE.auth_ok is True
    seen = {}

    async def _bal(pin_env=None):
        seen.setdefault("authOkDuringVerify", svc.STATE.auth_ok)
        if not answers:
            raise kalshi_api.KalshiAPIError(401, {"error": {"code": "unauthorized"}})
        return {"balance": 1000, "total_balance_cents": 1000}
    monkeypatch.setattr(kalshi_api, "get_balance", _bal)
    monkeypatch.setattr(trader, "get_balance", _bal)
    run(svc._h_setConfig({"config": {"accountMode": "live"}}))
    assert seen["authOkDuringVerify"] is False
    assert svc.STATE.auth_ok is answers



def test_a_ticket_filled_in_on_paper_is_refused_after_a_switch(paper_db, no_signing,
                                                               public_book, monkeypatch):
    async def _none(*_a, **_k):
        return None
    monkeypatch.setattr(kalshi_api, "fetch_market", _none)
    monkeypatch.setattr(kalshi_api, "fetch_exchange_status", _none)
    monkeypatch.setattr(terminal, "book", _none)
    sent = []

    async def _place(**kw):
        sent.append(kw)
        return {"order": {"order_id": "x"}}
    monkeypatch.setattr(kalshi_api, "place_limit_order", _place)
    cfg = merge_with_defaults({})
    ticket = {"ticker": "KXA-8", "side": "yes", "action": "buy", "count": 1,
              "priceCents": 60, "expectMode": "live"}
    pv = terminal.preview(ticket, cfg=cfg, authed=True, market=None,
                          book_snapshot=None, position=None)
    assert any("filled in on LIVE" in b for b in pv["blockers"])
    res = run(terminal.submit(ticket, cfg=cfg, authed=True))
    assert res["ok"] is False and "now on PAPER" in res["message"] and sent == []
    assert terminal.mode_mismatch(dict(ticket, expectMode="paper"), "paper") is None
    assert terminal.mode_mismatch({"ticker": "KXA-8"}, "production") is None
    assert terminal.mode_mismatch(dict(ticket, expectMode="paper"), "production")
    assert terminal.mode_mismatch(dict(ticket, expectMode="bogus"), "production") is None
