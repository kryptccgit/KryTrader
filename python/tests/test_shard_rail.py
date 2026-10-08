"""The shard rail: collateral moved to the exchange an order needs.

Kalshi keeps collateral per matching-engine shard and does not rebalance a
retail account, so cross-market auto-trading stalls the moment an engine
leaves the shard the money sits on. The rail moves the SHORTFALL before a live
buy; AI agents can move funds themselves with `move_funds`. These pin the
money rules: only the shortfall, richest source first, never in Paper, never
retried, a daily cap shared by both and kept across restarts, sells untouched.
"""
from __future__ import annotations

import asyncio

import pytest

import db
import kalshi_api
import kalshi_auth
import shard_rail
import trader
from config import merge_with_defaults


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def live(tmp_path, monkeypatch):
    dbfile = tmp_path / "rail.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    monkeypatch.setattr(kalshi_auth, "_current_env", "production", raising=False)
    cfg = {"shard_auto_move": True, "shard_auto_move_max_usd_day": 1000.0}
    monkeypatch.setattr(shard_rail, "GET_CFG", lambda: cfg)
    monkeypatch.setattr(kalshi_api, "shard_for_ticker", lambda t: 2)
    monkeypatch.setattr(trader, "cached_shard_balances", lambda env=None: None)

    async def _refresh(*a, **k):
        return (0, 0)
    monkeypatch.setattr(trader, "refresh_balance", _refresh)

    state = {"shards": {0: 50.0, 2: 0.10}, "reads": 0, "moves": [], "fail": False}

    async def _bal(pin_env=None):
        state["reads"] += 1
        return {"shard_balances": dict(state["shards"])}
    monkeypatch.setattr(kalshi_api, "get_balance", _bal)

    async def _xfer(*, amount_usd, source_shard, destination_shard):
        state["moves"].append((amount_usd, source_shard, destination_shard))
        if state["fail"]:
            raise RuntimeError("timeout")
        state["shards"][source_shard] -= amount_usd
        state["shards"][destination_shard] = state["shards"].get(destination_shard, 0) + amount_usd
        return {"transfer_id": "t"}
    monkeypatch.setattr(kalshi_api, "transfer_between_shards", _xfer)
    return state, cfg


def ensure(count=10, price=40):
    return run(shard_rail.ensure_collateral(ticker="KXBTC-X", count=count, price_cents=price, env="production"))


def test_moves_only_the_shortfall_from_the_richest_shard(live):
    state, _ = live
    note = ensure()
    assert state["moves"] == [(4.10, 0, 2)]
    assert note.startswith("moved $4.10")


def test_spreads_the_move_over_several_shards(live):
    state, _ = live
    state["shards"] = {0: 2.0, 1: 3.0, 2: 0.0}
    ensure()
    assert state["moves"] == [(3.0, 1, 2), (1.2, 0, 2)]


def test_a_shard_that_already_covers_it_costs_no_network(live, monkeypatch):
    state, _ = live
    monkeypatch.setattr(trader, "cached_shard_balances", lambda env=None: {0: 1.0, 2: 99.0})
    assert ensure() is None
    assert state["reads"] == 0 and state["moves"] == []


def test_enough_on_a_fresh_read_moves_nothing(live):
    state, _ = live
    state["shards"] = {0: 5.0, 2: 10.0}
    assert ensure() is None
    assert state["moves"] == []


def test_paper_never_moves_anything(live, monkeypatch):
    state, _ = live
    monkeypatch.setattr(kalshi_auth, "_current_env", "paper", raising=False)
    assert run(shard_rail.ensure_collateral(ticker="KXBTC-X", count=10, price_cents=40, env="paper")) is None
    assert state["moves"] == [] and state["reads"] == 0


def test_switched_off_moves_nothing(live):
    state, cfg = live
    cfg["shard_auto_move"] = False
    assert ensure() is None
    assert state["moves"] == []


def test_unknown_shard_fails_open(live, monkeypatch):
    state, _ = live
    monkeypatch.setattr(kalshi_api, "shard_for_ticker", lambda t: None)

    async def _no_market(t):
        raise RuntimeError("offline")
    monkeypatch.setattr(kalshi_api, "fetch_market", _no_market)
    assert ensure() is None
    assert state["moves"] == []


def test_a_failed_transfer_is_recorded_not_retried_and_never_raises(live):
    state, _ = live
    state["fail"] = True
    note = ensure()
    assert len(state["moves"]) == 1
    assert "failed" in note
    with db.get_db() as conn:
        rows = conn.execute("SELECT ok, by FROM shard_transfers").fetchall()
    assert [(r["ok"], r["by"]) for r in rows] == [(0, "auto")]
    assert shard_rail.moved_today_usd("production") == 0.0


def test_the_daily_cap_binds_and_survives_a_restart(live):
    state, cfg = live
    cfg["shard_auto_move_max_usd_day"] = 5.0
    shard_rail.record("production", 0, 2, 4.0, "auto", True)
    note = ensure()
    assert state["moves"] == [(1.0, 0, 2)]
    assert "daily cap" in note
    state["moves"].clear()
    state["shards"][2] = 0.0
    note = ensure()
    assert state["moves"] == []
    assert "used up" in note


def test_the_users_own_moves_do_not_count_against_the_cap(live):
    state, cfg = live
    cfg["shard_auto_move_max_usd_day"] = 5.0
    shard_rail.record("production", 0, 2, 500.0, "you", True)
    ensure()
    assert state["moves"] == [(4.10, 0, 2)]


def test_place_limit_order_runs_the_rail_on_buys_only(live, monkeypatch):
    calls = []

    async def _rail(**kw):
        calls.append(kw)
        return "moved $1.00 to the crypto exchange for this order"
    monkeypatch.setattr(shard_rail, "ensure_collateral", _rail)

    async def _signed(method, path, **kw):
        return {"order": {"order_id": "o1"}}
    monkeypatch.setattr(kalshi_api, "_signed_request", _signed)

    res = run(kalshi_api.place_limit_order(ticker="KXBTC-X", side="yes", action="buy", count=3, price_cents=40))
    assert len(calls) == 1 and calls[0]["count"] == 3
    assert res["krypt_shard_note"].startswith("moved")
    run(kalshi_api.place_limit_order(ticker="KXBTC-X", side="yes", action="sell", count=3, price_cents=40))
    assert len(calls) == 1



def test_agent_move_records_under_the_agent_and_shares_the_cap(live):
    state, cfg = live
    res = run(shard_rail.move(amount_usd=10, to_shard=2, from_shard=None, by="agent:alpha"))
    assert res["movedUsd"] == 10.0 and res["to"] == "crypto"
    assert state["moves"] == [(10.0, 0, 2)]
    assert shard_rail.moved_today_usd("production") == 10.0
    cfg["shard_auto_move_max_usd_day"] = 10.0
    with pytest.raises(ValueError, match="cap"):
        run(shard_rail.move(amount_usd=1, to_shard=2, from_shard=0, by="agent:alpha"))


def test_agent_move_refusals(live, monkeypatch):
    with pytest.raises(ValueError, match="same exchange"):
        run(shard_rail.move(amount_usd=1, to_shard=2, from_shard=2, by="agent:a"))
    with pytest.raises(ValueError, match="holds"):
        run(shard_rail.move(amount_usd=999, to_shard=2, from_shard=0, by="agent:a"))
    with pytest.raises(ValueError, match="at least"):
        run(shard_rail.move(amount_usd=0, to_shard=2, from_shard=None, by="agent:a"))
    monkeypatch.setattr(kalshi_auth, "_current_env", "paper", raising=False)
    with pytest.raises(ValueError, match="Paper"):
        run(shard_rail.move(amount_usd=1, to_shard=2, from_shard=None, by="agent:a"))


def test_exchanges_by_name_or_number():
    assert shard_rail.parse_shard("crypto") == 2
    assert shard_rail.parse_shard("General") == 0
    assert shard_rail.parse_shard(3) == 3
    assert shard_rail.parse_shard("1") == 1
    for bad in ("moon", True, -1, 500):
        with pytest.raises(ValueError):
            shard_rail.parse_shard(bad)


def test_move_funds_summary_shows_only_whitelisted_fields():
    import mcp_server
    s = mcp_server.summarize_call("move_funds", {"amount_usd": 5, "to_exchange": "crypto; token=abc"},
                                  {"movedUsd": 5.0, "to": "crypto"}, "live")
    assert s["summary"] == "move funds $5.00 to crypto"
    s = mcp_server.summarize_call("move_funds", {}, {"movedUsd": 5.0, "to": "<script>"}, "live")
    assert "<script>" not in s["summary"]



def test_on_by_default_and_only_an_explicit_false_turns_it_off():
    assert merge_with_defaults({})["shard_auto_move"] is True
    assert merge_with_defaults({"shardAutoMove": "nope"})["shard_auto_move"] is True
    assert merge_with_defaults({"shardAutoMove": False})["shard_auto_move"] is False
    assert merge_with_defaults({"shardAutoMoveMaxUsdDay": -5})["shard_auto_move_max_usd_day"] == 1.0


def test_no_agent_can_change_the_rail_or_its_cap():
    import mcp_workbench
    assert mcp_workbench.classify("shard_auto_move") == "protected"
    assert mcp_workbench.classify("shard_auto_move_max_usd_day") == "protected"



def _agent_call(monkeypatch, cfg_over: dict, args: dict):
    import json
    import mcp_server
    monkeypatch.setattr(mcp_server, "HOOKS", mcp_server.Hooks())
    monkeypatch.setattr(mcp_server, "_THROTTLE", mcp_server._Throttle())

    async def _emit(*a, **k):
        return None
    base = {"mcp_enabled": True, "accountMode": "live", **cfg_over}
    mcp_server.configure(get_cfg=lambda: merge_with_defaults(dict(base)),
                         is_authed=lambda: True, emit=_emit)
    res = run(mcp_server.call_tool("move_funds", dict(args), {"client": "pytest"}))
    text = res["content"][0]["text"]
    try:
        return res.get("isError", False), json.loads(text)
    except ValueError:
        return res.get("isError", False), text


def test_a_paper_agent_cannot_move_funds(live, monkeypatch):
    state, _ = live
    err, body = _agent_call(monkeypatch, {"mcpTradeMode": "paper"}, {"amount_usd": 5, "to_exchange": "crypto"})
    assert err and "live trading" in str(body)
    assert state["moves"] == []


def test_a_live_agent_moves_funds_and_it_is_audited_as_that_agent(live, monkeypatch):
    state, _ = live
    err, body = _agent_call(monkeypatch, {"mcpTradeMode": "live"}, {"amount_usd": 5, "to_exchange": "crypto"})
    assert not err, body
    assert body["movedUsd"] == 5.0 and body["to"] == "crypto"
    assert state["moves"] == [(5.0, 0, 2)]
    with db.get_db() as conn:
        by = conn.execute("SELECT by FROM shard_transfers WHERE ok=1").fetchone()["by"]
    assert by.startswith("agent:")


def test_15m_sizes_from_the_whole_account_when_the_rail_can_move_it(live, monkeypatch):
    import crypto15m_trader

    async def _bal(cfg, force=False):
        return (200_000, 0)
    monkeypatch.setattr(trader, "refresh_balance", _bal)
    monkeypatch.setattr(crypto15m_trader, "_crypto_shard_cash_usd", lambda: 50.0)
    on = {"shard_auto_move": True}
    off = {"shard_auto_move": False}
    assert run(crypto15m_trader._bankroll_usd(on, authed=True)) == 2000.0
    assert run(crypto15m_trader._bankroll_usd(off, authed=True)) == 50.0


def test_the_order_waits_until_the_moved_money_lands(live, monkeypatch):
    """Kalshi accepts a transfer before the destination can spend it: on the
    real account an order sent right behind a 3c move was refused for
    insufficient balance, the 3c showing on crypto a moment later."""
    state, _ = live
    monkeypatch.setattr(shard_rail, "LAND_POLL_S", 0.01)
    lag = {"reads_after_move": 0}
    real_bal = kalshi_api.get_balance

    async def _lagging(pin_env=None):
        res = await real_bal(pin_env)
        if state["moves"]:
            lag["reads_after_move"] += 1
            if lag["reads_after_move"] < 3:
                res["shard_balances"][2] = 0.10
        return res
    monkeypatch.setattr(kalshi_api, "get_balance", _lagging)
    ensure()
    assert state["moves"] == [(4.10, 0, 2)]
    assert lag["reads_after_move"] >= 3


def test_landing_gives_up_after_the_timeout(live, monkeypatch):
    state, _ = live
    monkeypatch.setattr(shard_rail, "LAND_POLL_S", 0.01)
    monkeypatch.setattr(shard_rail, "LAND_TIMEOUT_S", 0.05)
    real_bal = kalshi_api.get_balance

    async def _never(pin_env=None):
        res = await real_bal(pin_env)
        if state["moves"]:
            res["shard_balances"][2] = 0.10
        return res
    monkeypatch.setattr(kalshi_api, "get_balance", _never)
    note = ensure()
    assert state["moves"] == [(4.10, 0, 2)]
    assert note.startswith("moved")



def test_a_cancel_names_its_market_so_kalshi_routes_it_to_the_right_shard(monkeypatch):
    """The real-key test cancelled a resting order on the crypto shard by id
    alone and got 404 "not found": the v2 cancel defaults to shard 0."""
    monkeypatch.setattr(kalshi_auth, "_current_env", "production", raising=False)
    sent = {}

    async def _signed(method, path, **kw):
        sent.update(method=method, path=path, params=kw.get("params"))
        return {}
    monkeypatch.setattr(kalshi_api, "_signed_request", _signed)
    run(kalshi_api.cancel_order("o1", ticker="kxbtcprice-130000-27mar18"))
    assert sent["method"] == "DELETE" and sent["path"].endswith("/o1")
    assert sent["params"] == {"exchange_index": -1, "market_ticker": "KXBTCPRICE-130000-27MAR18"}
    run(kalshi_api.cancel_order("o2"))
    assert sent["params"] is None


def test_the_terminal_cancel_looks_up_the_orders_market(monkeypatch):
    import terminal
    monkeypatch.setattr(kalshi_auth, "_current_env", "production", raising=False)
    got = {}

    async def _resting(authed, ticker=""):
        return {"orders": [{"orderId": "o9", "ticker": "KXBTCPRICE-X"}]}

    async def _cancel(oid, *, ticker=None, pin_env=None):
        got.update(oid=oid, ticker=ticker)
        return {}
    monkeypatch.setattr(terminal, "resting_orders", _resting)
    monkeypatch.setattr(kalshi_api, "cancel_order", _cancel)
    run(terminal.cancel("o9", authed=True))
    assert got == {"oid": "o9", "ticker": "KXBTCPRICE-X"}
