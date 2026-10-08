"""The agent money rails under pressure: concurrency, fills, environments.

test_ai_agents.py pins what each rail refuses one call at a time. This file
pins the ways those rails were walked around in the v6 audit:

  * five place_order calls sent at once all read "$0 spent today" and all went
    to Kalshi ($41.85 against a $10 cap); two approvals clicked together did
    the same — so vet -> send -> record is one critical section;
  * a buy that rested unfilled (or was cancelled) authorised a sell of the
    same size, and the contracts sold were the USER's — so the sell allowance
    is what the agent's buys actually filled;
  * demo agent trades authorised sells on production, and an approval queued
    on demo went out on production after an env switch — so everything is
    scoped to, and pinned on, the environment;
  * an approval whose re-check raised was left in 'deciding' forever.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

import db
import kalshi_auth
import mcp_server
import terminal
from config import merge_with_defaults

TICKER = "KXTEST-26OCT-T1"
MARKET = {
    "ticker": TICKER, "title": "Will the test pass?", "status": "active",
    "yesBid": 50.0, "yesAsk": 54.0, "noBid": 46.0, "noAsk": 50.0,
    "midCents": 52.0, "spreadCents": 4.0, "closeTime": None,
}
BOOK = {
    "ticker": TICKER,
    "yes": [{"priceCents": 50.0, "contracts": 300}],
    "no": [{"priceCents": 46.0, "contracts": 300}],
    "yesBid": 50.0, "yesAsk": 54.0, "stale": False, "source": "kalshi-ws",
}
BUY15 = {"ticker": TICKER, "side": "yes", "action": "buy", "count": 15, "price_cents": 54}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def rig(monkeypatch):
    db.init_db()
    with db.get_db() as conn:
        for t in ("ai_forecasts", "paper_fills", "paper_state", "mcp_orders"):
            conn.execute(f"DELETE FROM {t}")
    mcp_server._hits.clear()
    old_env = kalshi_auth.get_env()
    kalshi_auth.set_env("production")
    st = {"cfg": {"account_mode": "live", "mcp_enabled": True, "mcp_trade_mode": "live",
                  "mcp_live_approval": False, "mcp_daily_spend_usd": 10.0,
                  "mcp_max_order_usd": 25.0},
          "sent": [], "fills": {}, "submit_error": None}

    async def _submit(req, scope=None):
        await asyncio.sleep(0.01)
        if st["submit_error"]:
            raise st["submit_error"]
        st["sent"].append(req)
        return {"ok": True, "orderId": f"ord-{len(st['sent'])}", "message": "Placed.",
                "filledContracts": 0, "avgFillCents": None, "status": "resting"}

    async def _cancel(oid):
        return {"ok": True, "message": "Cancelled."}

    mcp_server.configure(get_cfg=lambda: merge_with_defaults(dict(st["cfg"])),
                         is_authed=lambda: True, submit=_submit, cancel=_cancel,
                         emit=None, notify_phone=None, version="test")

    async def _row(ticker):
        await asyncio.sleep(0.02)
        return dict(MARKET, ticker=ticker)

    async def _book(ticker):
        await asyncio.sleep(0.005)
        return dict(BOOK, ticker=ticker)

    async def _pf(authed):
        tickers = {TICKER} | {r["ticker"] for r in st["sent"] if r["action"] == "buy"}
        return {"positions": [{"ticker": t, "side": "yes", "contracts": 100,
                               "unrealizedUsd": 0.0} for t in tickers]}

    async def _fills(order_id, side, pin_env=None):
        return st["fills"].get(order_id, (0, None))

    monkeypatch.setattr(mcp_server, "_market_row", _row)
    monkeypatch.setattr(terminal, "book", _book)
    monkeypatch.setattr(terminal, "portfolio", _pf)
    monkeypatch.setattr(terminal, "manual_history", lambda limit=300: {"trades": []})
    monkeypatch.setattr(terminal, "_reconcile_fills", _fills)
    yield st
    kalshi_auth.set_env(old_env)


def _call(name, args):
    res = run(mcp_server.call_tool(name, dict(args), {"client": "pytest"}))
    text = res["content"][0]["text"]
    try:
        return res["isError"], json.loads(text)
    except ValueError:
        return res["isError"], text


def _fid(fv=80, ticker=TICKER):
    err, body = _call("record_forecast", {"ticker": ticker, "fair_value_cents": fv,
                                          "rationale": "Base rates and the rules text agree."})
    assert not err, body
    return body["forecastId"]


def _row(rid):
    with db.get_db() as conn:
        return dict(conn.execute("SELECT * FROM mcp_orders WHERE id=?", (rid,)).fetchone())


def _gather(calls):
    async def go():
        return await asyncio.gather(*[mcp_server.call_tool(n, dict(a), {"client": "pytest"})
                                      for n, a in calls])
    return run(go())



def test_concurrent_live_buys_spend_the_daily_cap_once(rig):
    fid = _fid()
    res = _gather([("place_order", dict(BUY15, forecast_id=fid))] * 5)
    oks = [r for r in res if not r["isError"]]
    assert len(oks) == 1 and len(rig["sent"]) == 1
    assert mcp_server.spent_today("live") <= 10.0
    refused = [r["content"][0]["text"] for r in res if r["isError"]]
    assert len(refused) == 4 and all("daily cap" in t for t in refused)


def test_concurrent_buys_cannot_exceed_the_position_cap(rig):
    rig["cfg"]["mcp_max_positions"] = 1
    rig["cfg"]["mcp_daily_spend_usd"] = 100.0
    other = "KXTEST-26OCT-T2"
    f1, f2 = _fid(), _fid(ticker=other)
    res = _gather([("place_order", dict(BUY15, forecast_id=f1)),
                   ("place_order", dict(BUY15, ticker=other, forecast_id=f2))])
    assert sum(not r["isError"] for r in res) == 1 and len(rig["sent"]) == 1


def test_concurrent_paper_buys_cannot_overdraw_paper_cash(rig, monkeypatch):
    import kalshi_api

    async def _marks(tickers):
        await asyncio.sleep(0.01)
        return {}
    monkeypatch.setattr(kalshi_api, "fetch_markets_by_tickers", _marks)
    rig["cfg"].update(mcp_trade_mode="paper", mcp_daily_spend_usd=1000.0,
                      paper_bankroll_usd=10.0)
    import paper_book
    paper_book.record_fill(ticker="KXOTHER-26OCT-T1", title="", side="yes", action="buy",
                           contracts=1, price_cents=10, fee_usd=0.0, forecast_id=None,
                           client="", env="paper")
    fid = _fid()
    res = _gather([("place_order", dict(BUY15, forecast_id=fid))] * 4)
    assert sum(not r["isError"] for r in res) == 1
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM paper_fills "
                            "WHERE ticker=?", (TICKER,)).fetchone()[0] == 1
    assert paper_book.portfolio(10.0)["cashUsd"] >= 0


def test_two_approvals_at_once_send_only_what_the_cap_allows(rig):
    rig["cfg"].update(mcp_live_approval=True, mcp_daily_spend_usd=100.0)
    fid = _fid()
    ids = []
    for _ in range(2):
        err, body = _call("place_order", dict(BUY15, forecast_id=fid))
        assert not err and body["pending"], body
        ids.append(body["approvalId"])
    rig["cfg"]["mcp_daily_spend_usd"] = 10.0

    async def go():
        return await asyncio.gather(*[mcp_server.decide(i, True) for i in ids])
    res = run(go())
    assert sum(r["ok"] for r in res) == 1 and len(rig["sent"]) == 1
    assert sorted(_row(i)["status"] for i in ids) == ["approved", "failed"]


def test_an_order_being_approved_still_counts_toward_spend(rig):
    rig["cfg"].update(mcp_live_approval=True, mcp_daily_spend_usd=100.0)
    err, body = _call("place_order", dict(BUY15, forecast_id=_fid()))
    rid = body["approvalId"]
    with db.get_db() as conn:
        conn.execute("UPDATE mcp_orders SET status='deciding' WHERE id=?", (rid,))
    spent = mcp_server.spent_today("live")
    assert spent == pytest.approx(_row(rid)["committed_usd"])
    assert mcp_server.spent_today("live", exclude_id=rid) == 0



def _sell(n, px=1):
    return _call("place_order", {"ticker": TICKER, "side": "yes", "action": "sell",
                                 "count": n, "price_cents": px})


def test_an_unfilled_resting_buy_opens_nothing_to_sell(rig):
    err, body = _call("place_order", dict(BUY15, count=10, price_cents=1, forecast_id=_fid()))
    assert not err, body
    err, body = _sell(10)
    assert err and "only sell what it opened" in body
    assert [r["action"] for r in rig["sent"]] == ["buy"]


def test_a_cancelled_buy_opens_nothing_to_sell(rig):
    err, body = _call("place_order", dict(BUY15, count=10, price_cents=1, forecast_id=_fid()))
    oid = body["orderId"]
    err, body = _call("cancel_order", {"order_id": oid})
    assert not err and body["ok"], body
    with db.get_db() as conn:
        r = conn.execute("SELECT status, filled FROM mcp_orders WHERE order_id=?", (oid,)).fetchone()
    assert r["status"] == "cancelled" and r["filled"] == 0
    err, body = _sell(10)
    assert err and "only sell what it opened" in body
    assert all(r["action"] == "buy" for r in rig["sent"])


def test_a_partial_fill_lets_the_agent_sell_only_the_fill(rig):
    err, body = _call("place_order", dict(BUY15, count=10, forecast_id=_fid()))
    rig["fills"][body["orderId"]] = (4, 54.0)
    err, body = _sell(5, px=50)
    assert err and "only sell what it opened" in body
    err, body = _sell(4, px=50)
    assert not err, body
    assert rig["sent"][-1]["action"] == "sell" and rig["sent"][-1]["count"] == 4
    err, body = _sell(1, px=50)
    assert err and "only sell what it opened" in body


def test_a_resting_sell_keeps_counting_until_it_is_cancelled(rig):
    err, body = _call("place_order", dict(BUY15, count=5, forecast_id=_fid()))
    rig["fills"][body["orderId"]] = (5, 54.0)
    err, body = _sell(5, px=99)
    assert not err, body
    sell_oid = body["orderId"]
    err, body = _sell(5, px=50)
    assert err and "only sell what it opened" in body
    rig["fills"][sell_oid] = (2, 99.0)
    err, body = _call("cancel_order", {"order_id": sell_oid})
    assert not err, body
    err, body = _sell(4, px=50)
    assert err and "only sell what it opened" in body
    err, body = _sell(3, px=50)
    assert not err, body


def test_a_cancelled_sell_with_an_unreadable_ledger_keeps_counting_in_full(rig, monkeypatch):
    err, body = _call("place_order", dict(BUY15, count=5, forecast_id=_fid()))
    rig["fills"][body["orderId"]] = (5, 54.0)
    err, body = _sell(5, px=99)
    sell_oid = body["orderId"]

    async def _unreadable(order_id, side, pin_env=None):
        return (None, None)
    monkeypatch.setattr(terminal, "_reconcile_fills", _unreadable)
    err, body = _call("cancel_order", {"order_id": sell_oid})
    assert not err, body
    err, body = _sell(1, px=50)
    assert err and "only sell what it opened" in body



def _retire(rid_or_all=None):
    """Re-file agent orders as Kalshi's retired demo exchange: rows from
    before Paper replaced it. They stay in the table and count for nothing."""
    with db.get_db() as conn:
        conn.execute("UPDATE mcp_orders SET kalshi_env='demo'")


def test_retired_demo_agent_buys_do_not_authorise_live_sells(rig):
    err, body = _call("place_order", dict(BUY15, count=10, price_cents=1, forecast_id=_fid()))
    rig["fills"][body["orderId"]] = (10, 1.0)
    demo_oid = body["orderId"]
    _retire()
    err, body = _sell(10)
    assert err and "only sell what it opened" in body
    err, body = _call("cancel_order", {"order_id": demo_oid})
    assert err and "user's" in body
    assert all(r["action"] == "buy" for r in rig["sent"])


def test_paper_scope_never_authorises_live_sells(rig):
    """The paper account's rows (scope 'paper') and the real account's
    ('production') are separate books: a buy in one is not the agent's to
    sell in the other."""
    err, body = _call("place_order", dict(BUY15, count=10, price_cents=1, forecast_id=_fid()))
    rig["fills"][body["orderId"]] = (10, 1.0)
    with db.get_db() as conn:
        conn.execute("UPDATE mcp_orders SET kalshi_env='paper'")
    err, body = _sell(10)
    assert err and "only sell what it opened" in body


def test_the_daily_spend_cap_is_per_book(rig):
    err, body = _call("place_order", dict(BUY15, forecast_id=_fid()))
    assert not err, body
    assert mcp_server.spent_today("live") > 8
    kalshi_auth.set_env("paper")
    assert mcp_server.spent_today("live") == 0
    kalshi_auth.set_env("production")
    _retire()
    assert mcp_server.spent_today("live") == 0


def test_a_retired_demo_forecast_cannot_back_a_buy(rig):
    fid = _fid()
    with db.get_db() as conn:
        conn.execute("UPDATE ai_forecasts SET kalshi_env='demo' WHERE id=?", (fid,))
    err, body = _call("place_order", dict(BUY15, forecast_id=fid))
    assert err and "retired demo exchange" in body and rig["sent"] == []


def test_a_forecast_made_in_paper_backs_a_live_buy(rig):
    """Paper and Live trade the same production book, so a forecast argued in
    Paper is argued against the prices a Live buy pays."""
    kalshi_auth.set_env("paper")
    fid = _fid()
    kalshi_auth.set_env("production")
    err, body = _call("place_order", dict(BUY15, forecast_id=fid))
    assert not err, body
    assert len(rig["sent"]) == 1


def test_an_approval_queued_live_never_executes_in_paper(rig):
    rig["cfg"]["mcp_live_approval"] = True
    err, body = _call("place_order", dict(BUY15, count=5, forecast_id=_fid()))
    rid = body["approvalId"]
    pend = mcp_server.pending()
    assert [p["env"] for p in pend] == ["production"]
    kalshi_auth.set_env("paper")
    rig["cfg"]["account_mode"] = "paper"
    res = run(mcp_server.decide(rid, True))
    assert not res["ok"]
    assert rig["sent"] == [] and _row(rid)["status"] == "failed"
    kalshi_auth.set_env("production")
    rig["cfg"]["account_mode"] = "live"
    assert not run(mcp_server.decide(rid, True))["ok"] and rig["sent"] == []


def test_the_phone_listing_names_the_account_mode(rig):
    import remote
    rig["cfg"]["mcp_live_approval"] = True
    err, body = _call("place_order", dict(BUY15, count=5, forecast_id=_fid()))
    listing = run(remote.handle("agents", "discord:1", cfg={}, authed=True,
                                trading_enabled=False))
    assert f"#{body['approvalId']} [LIVE]" in listing



def test_an_approval_whose_recheck_raises_is_failed_not_stuck(rig, monkeypatch):
    fid = _fid()
    err, body = _call("place_order", dict(BUY15, count=1, forecast_id=fid))
    assert not err, body
    rig["cfg"]["mcp_live_approval"] = True
    err, body = _call("place_order", dict(BUY15, count=5, forecast_id=fid))
    rid = body["approvalId"]

    def _boom(limit=300):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(terminal, "manual_history", _boom)
    res = run(mcp_server.decide(rid, True))
    assert not res["ok"] and "nothing was sent" in res["message"]
    assert _row(rid)["status"] == "failed" and len(rig["sent"]) == 1
    err, st = _call("get_order_status", {"approval_id": rid})
    assert st["status"] == "failed"


def test_a_send_that_errors_is_unknown_and_still_counts(rig):
    rig["cfg"]["mcp_live_approval"] = True
    err, body = _call("place_order", dict(BUY15, count=5, forecast_id=_fid()))
    rid = body["approvalId"]
    rig["submit_error"] = TimeoutError("read timed out")
    res = run(mcp_server.decide(rid, True))
    assert not res["ok"] and "check your Kalshi orders" in res["message"]
    r = _row(rid)
    assert r["status"] == "unknown"
    assert mcp_server.spent_today("live") == pytest.approx(r["committed_usd"])


def test_a_deciding_row_left_by_a_restart_reads_as_failed(rig):
    rig["cfg"]["mcp_live_approval"] = True
    err, body = _call("place_order", dict(BUY15, count=5, forecast_id=_fid()))
    rid = body["approvalId"]
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
    with db.get_db() as conn:
        conn.execute("UPDATE mcp_orders SET status='deciding', created_at=? WHERE id=?",
                     (old, rid))
    act = [a for a in mcp_server.activity() if a["id"] == rid][0]
    assert act["status"] == "failed" and "check your Kalshi orders" in act["message"]
