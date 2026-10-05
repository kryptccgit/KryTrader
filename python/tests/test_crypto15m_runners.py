from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import crypto15m
import crypto15m_trader as ct
import db
import kalshi_api
import trader
from config import merge_with_defaults


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "c15-runners-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


@pytest.fixture
def env_demo(monkeypatch):
    monkeypatch.setattr(trader, "get_env", lambda: "demo")
    return "demo"


@pytest.fixture
def cfg():
    c = merge_with_defaults({})
    c["kalshi_env"] = "demo"
    c["crypto15m_enabled"] = True
    c["crypto15m_entry_style"] = "taker"
    return c


def run_async(coro):
    return asyncio.run(coro)


def signal_asset(asset="BTC", favorite="up", entry_cost=0.86, ticker=None,
                 mins_left=5.0):
    close = (datetime.now(timezone.utc) + timedelta(minutes=mins_left)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    up = 0.9 if favorite == "up" else 0.1
    return {
        "asset": asset, "series": f"KX{asset}15M", "spotUsd": 100.0,
        "open15mUsd": 100.0, "deltaUsd": 0.5, "hasMarket": True,
        "ticker": ticker or f"KX{asset}15M-T1", "closeTime": close,
        "minsLeft": mins_left, "upProb": up, "downProb": 1 - up,
        "favorite": favorite, "favoritePrice": 0.86, "entryCost": entry_cost,
        "yesBid": 0.85, "yesAsk": 0.87,
        "inWindow": True, "signal": True, "openMarketCount": 1, "error": None,
    }


def _stub_snapshot(assets):
    async def _snap(_cfg):
        return {"assets": assets, "constants": {}, "fetchedAt": "",
                "spotOk": True, "spotSource": "stub"}
    return _snap


def _no_real_orders(monkeypatch):
    async def _boom(**kw):
        raise AssertionError("paper runner must not place a real order")
    monkeypatch.setattr(kalshi_api, "place_limit_order", _boom)


def runner(rid, coins, mode="paper", enabled=True, config=None):
    return {"id": rid, "name": rid, "coins": coins, "mode": mode,
            "enabled": enabled, "config": config or {}}


def test_resolve_default_runner_when_none(cfg):
    cfg["crypto15m_runners"] = None
    cfg["crypto15m_live"] = True
    runners = ct._resolve_runners(cfg)
    assert len(runners) == 1
    r = runners[0]
    assert r["id"] == "" and r["mode"] == "live" and r["enabled"] is True
    assert set(r["coins"]) == set(crypto15m.ALL_ASSETS)


def test_default_runner_disabled_when_not_live(cfg):
    cfg["crypto15m_runners"] = None
    cfg["crypto15m_live"] = False
    assert ct._resolve_runners(cfg)[0]["enabled"] is False


def test_coin_ownership_earlier_enabled_runner_wins(cfg):
    cfg["crypto15m_runners"] = [
        runner("a", ["BTC", "ETH"]),
        runner("b", ["ETH", "SOL"]),
    ]
    a, b = ct._resolve_runners(cfg)
    assert a["coins"] == ["BTC", "ETH"]
    assert b["coins"] == ["SOL"]


def test_disabled_runner_does_not_claim_coins(cfg):
    cfg["crypto15m_runners"] = [
        runner("a", ["BTC"], enabled=False),
        runner("b", ["BTC"], enabled=True),
    ]
    a, b = ct._resolve_runners(cfg)
    assert b["coins"] == ["BTC"]


def test_scheduled_runner_swaps_config_by_hour(cfg, monkeypatch):
    import datetime as _dt
    import kalshi_auth
    epoch = _dt.datetime(2026, 7, 14, 10, 30, tzinfo=_dt.timezone.utc).timestamp()
    monkeypatch.setattr(kalshi_auth, "server_now", lambda: epoch)
    c = merge_with_defaults({"crypto15mRunners": [{
        "id": "s", "name": "sched", "coins": ["BTC"], "mode": "paper", "enabled": True,
        "schedule": [
            {"startHour": 0, "endHour": 8, "name": "A", "config": {"crypto15mTakeProfitCents": 90}},
            {"startHour": 8, "endHour": 16, "name": "B", "config": {"crypto15mTakeProfitCents": 95}},
        ]}]})
    r = ct._resolve_runners(c)[0]
    assert r["scheduled"] is True
    assert r["cfg"]["crypto15m_take_profit_cents"] == 95
    assert r["coins"] == ["BTC"]


def test_scheduled_runner_idle_when_no_slot(cfg, monkeypatch):
    import datetime as _dt
    import kalshi_auth
    epoch = _dt.datetime(2026, 7, 14, 20, 0, tzinfo=_dt.timezone.utc).timestamp()
    monkeypatch.setattr(kalshi_auth, "server_now", lambda: epoch)
    c = merge_with_defaults({"crypto15mRunners": [{
        "id": "s", "name": "sched", "coins": ["BTC"], "mode": "paper", "enabled": True,
        "schedule": [{"startHour": 0, "endHour": 16, "name": "A", "config": {}}]}]})
    r = ct._resolve_runners(c)[0]
    assert r["coins"] == []


def test_runner_cfg_overrides_layer_over_base(cfg):
    cfg["crypto15m_runners"] = [runner("a", ["BTC"], config={"crypto15m_take_profit_cents": 97})]
    r = ct._resolve_runners(cfg)[0]
    assert r["cfg"]["crypto15m_take_profit_cents"] == 97
    assert r["cfg"]["crypto15m_enabled"] is True


def test_validate_runners_sanitizes_and_dedups():
    c = merge_with_defaults({"crypto15m_runners": [
        {"id": "x", "name": "X", "coins": ["btc", "nope"], "mode": "weird", "enabled": True,
         "config": {"crypto15m_take_profit_cents": 90, "enable_trading": True, "junk": 1}},
        {"id": "x", "coins": None, "mode": "live"},
    ]})
    runners = c["crypto15m_runners"]
    assert len(runners) == 1
    r = runners[0]
    assert r["coins"] == ["BTC"]
    assert r["mode"] == "paper"
    assert r["config"] == {"crypto15m_take_profit_cents": 90}


def test_validate_empty_runners_is_none():
    assert merge_with_defaults({"crypto15m_runners": []})["crypto15m_runners"] is None
    assert merge_with_defaults({"crypto15m_runners": "bad"})["crypto15m_runners"] is None


def test_runner_order_size_override_pins_fixed_under_balance_pct_base():
    c = merge_with_defaults({
        "crypto15m_sizing_mode": "balance_pct",
        "crypto15m_balance_pct": 0.20,
        "crypto15m_runners": [
            {"id": "r1", "coins": ["BTC"], "mode": "live", "enabled": True,
             "config": {"crypto15m_order_size": 1}},
        ],
    })
    override = c["crypto15m_runners"][0]["config"]
    assert override["crypto15m_sizing_mode"] == "fixed"
    rcfg = ct._resolve_runners(c)[0]["cfg"]
    n = ct.compute_entry_contracts(
        rcfg, entry_limit_cents=90, balance_usd=500.0,
        order_size=int(rcfg["crypto15m_order_size"]),
    )
    assert n == 1


def test_runner_balance_pct_override_pins_that_mode():
    c = merge_with_defaults({
        "crypto15m_sizing_mode": "fixed",
        "crypto15m_runners": [
            {"id": "r1", "coins": ["ETH"], "mode": "live", "enabled": True,
             "config": {"crypto15m_balance_pct": 0.05}},
        ],
    })
    assert c["crypto15m_runners"][0]["config"]["crypto15m_sizing_mode"] == "balance_pct"


def test_runner_numeric_overrides_are_range_clamped_like_base():
    c = merge_with_defaults({"crypto15m_runners": [
        {"id": "r1", "coins": ["BTC"], "mode": "live", "enabled": True,
         "config": {"crypto15m_order_size": 100000,
                    "crypto15m_balance_pct": 5.0,
                    "crypto15m_max_concurrent": 999}},
    ]})
    override = c["crypto15m_runners"][0]["config"]
    assert override["crypto15m_order_size"] == 10_000
    assert override["crypto15m_balance_pct"] == 1.0
    assert override["crypto15m_max_concurrent"] == 50


def test_mgmt_snapshot_survives_runner_config_drift(fresh_db, env_demo):
    open_cfg = merge_with_defaults({
        "crypto15m_stop_loss_pct": 0.15,
        "crypto15m_take_profit_cents": 70,
    })
    snap = ct._mgmt_snapshot_json(open_cfg)
    with db.get_db() as conn:
        pid = db.insert_crypto15m_position(conn, {
            "asset": "BTC", "series": "KXBTC15M", "ticker": "KXBTC15M-T1",
            "side": "up", "direction": "yes", "target_contracts": 1,
            "entry_limit_cents": 90, "client_order_id": "c1",
            "status": "filled", "kalshi_env": env_demo, "mgmt_config": snap,
        })
        pos = db.fetch_crypto15m_by_id(conn, pid)

    base_cfg = merge_with_defaults({})
    assert base_cfg["crypto15m_stop_loss_pct"] == 0.0
    eff = ct._with_mgmt_snapshot(pos, base_cfg)
    assert eff["crypto15m_stop_loss_pct"] == 0.15
    assert eff["crypto15m_take_profit_cents"] == 70


def test_mgmt_snapshot_absent_falls_through_to_live_cfg():
    base = merge_with_defaults({"crypto15m_stop_loss_pct": 0.2})
    assert ct._with_mgmt_snapshot({"mgmt_config": None}, base) is base
    assert ct._with_mgmt_snapshot({}, base) is base
    assert ct._with_mgmt_snapshot({"mgmt_config": "not json"}, base) is base


def test_runner_cannot_override_account_exposure_cap():
    c = merge_with_defaults({
        "crypto15m_max_total_pct": 0.10,
        "crypto15m_runners": [
            {"id": "r1", "coins": ["BTC"], "mode": "live", "enabled": True,
             "config": {"crypto15m_max_total_pct": 0.0,
                        "crypto15m_take_profit_cents": 90}},
        ],
    })
    override = c["crypto15m_runners"][0]["config"]
    assert "crypto15m_max_total_pct" not in override
    assert override["crypto15m_take_profit_cents"] == 90
    rcfg = ct._resolve_runners(c)[0]["cfg"]
    assert rcfg["crypto15m_max_total_pct"] == 0.10


def test_exposure_cap_blocks_live_entry_when_balance_unreadable(fresh_db, env_demo):
    cfg = merge_with_defaults({})
    cfg["crypto15m_enabled"] = True
    cfg["crypto15m_entry_style"] = "taker"
    assert cfg["crypto15m_max_total_pct"] > 0
    a = signal_asset("BTC")
    live = run_async(ct._open_entry(a, cfg, "demo", 0.0, paper=False))
    assert live is None
    paper = run_async(ct._open_entry(a, cfg, "demo", 0.0, paper=True))
    assert paper is not None and paper["dry_run"] == 1


def test_runner_explicit_sizing_mode_is_respected():
    c = merge_with_defaults({
        "crypto15m_runners": [
            {"id": "r1", "coins": ["BTC"], "mode": "live", "enabled": True,
             "config": {"crypto15m_order_size": 3,
                        "crypto15m_sizing_mode": "balance_pct"}},
        ],
    })
    assert c["crypto15m_runners"][0]["config"]["crypto15m_sizing_mode"] == "balance_pct"


def _insert_pos(conn, **over):
    row = dict(asset="BTC", series="KXBTC15M", ticker="KXBTC15M-X", side="up",
               direction="yes", target_contracts=1, filled_contracts=1,
               entry_limit_cents=87, avg_entry_cents=87, cost_usd=0.87,
               status="filled", kalshi_env="demo", dry_run=0,
               client_order_id="x1")
    row.update(over)
    return db.insert_crypto15m_position(conn, row)


def _iso_min_ago(mins):
    return (datetime.now(timezone.utc) - timedelta(minutes=mins)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_sweep_settles_other_envs_closed_position(fresh_db, env_demo, monkeypatch):
    with db.get_db() as conn:
        pid = _insert_pos(conn, kalshi_env="production", ticker="KXBTC15M-P",
                          close_time=_iso_min_ago(2), client_order_id="p1")

    async def _settled(_t):
        return {"status": "finalized", "result": "yes",
                "yes_bid_dollars": 1.0, "yes_ask_dollars": 1.0}
    monkeypatch.setattr(kalshi_api, "fetch_market", _settled)

    run_async(ct._sweep_other_envs_and_reap("demo"))
    with db.get_db() as conn:
        row = db.fetch_crypto15m_by_id(conn, pid)
    assert row["resolved"] == 1 and row["status"] == "settled"
    assert row["pnl_usd"] > 0


def test_sweep_settles_other_envs_exiting_row_with_env_pinned_order_calls(fresh_db, env_demo, monkeypatch):
    with db.get_db() as conn:
        pid = _insert_pos(conn, kalshi_env="production", ticker="KXBTC15M-XE",
                          status="exiting", close_time=_iso_min_ago(2),
                          client_order_id="xe1")
        db.update_crypto15m_position(conn, pid, exit_kalshi_order_id="XKID",
                                     exit_limit_cents=40, exit_filled_contracts=0)

    pins = {"cancel": "unset", "get": "unset"}

    async def _settled(_t):
        return {"status": "finalized", "result": "yes",
                "yes_bid_dollars": 1.0, "yes_ask_dollars": 1.0}

    async def _cancel(_kid, *, pin_env=None):
        pins["cancel"] = pin_env

    async def _get(_kid, *, pin_env=None):
        pins["get"] = pin_env
        return {"order": {"status": "canceled", "fill_count_fp": "0.00",
                          "remaining_count_fp": "0.00"}}
    monkeypatch.setattr(kalshi_api, "fetch_market", _settled)
    monkeypatch.setattr(kalshi_api, "cancel_order", _cancel)
    monkeypatch.setattr(kalshi_api, "get_order", _get)

    run_async(ct._sweep_other_envs_and_reap("demo"))
    assert pins["cancel"] == "production"
    assert pins["get"] == "production"
    with db.get_db() as conn:
        row = db.fetch_crypto15m_by_id(conn, pid)
    assert row["resolved"] == 1 and row["status"] == "settled"
    assert row["pnl_usd"] > 0


def test_sweep_reaps_stuck_filled_as_error_without_guessing_pnl(fresh_db, env_demo, monkeypatch):
    with db.get_db() as conn:
        pid = _insert_pos(conn, close_time=_iso_min_ago(75), client_order_id="s1")

    async def _unsettleable(_t):
        return {"status": "open", "result": ""}
    monkeypatch.setattr(kalshi_api, "fetch_market", _unsettleable)

    run_async(ct._sweep_other_envs_and_reap("demo"))
    with db.get_db() as conn:
        row = db.fetch_crypto15m_by_id(conn, pid)
    assert row["resolved"] == 1 and row["status"] == "error"
    assert row["pnl_usd"] is None


def test_sweep_reaps_stuck_unfilled_as_canceled(fresh_db, env_demo, monkeypatch):
    with db.get_db() as conn:
        pid = _insert_pos(conn, status="submitted", filled_contracts=0, dry_run=1,
                          close_time=_iso_min_ago(75), client_order_id="u1")
    run_async(ct._sweep_other_envs_and_reap("demo"))
    with db.get_db() as conn:
        row = db.fetch_crypto15m_by_id(conn, pid)
    assert row["resolved"] == 1 and row["status"] == "canceled"


def test_sweep_leaves_not_yet_closed_positions_alone(fresh_db, env_demo, monkeypatch):
    with db.get_db() as conn:
        pid = _insert_pos(conn, kalshi_env="production", ticker="KXBTC15M-F",
                          close_time=(datetime.now(timezone.utc) + timedelta(minutes=5))
                          .strftime("%Y-%m-%dT%H:%M:%SZ"), client_order_id="f1")

    async def _boom(_t):
        raise AssertionError("must not fetch/settle a still-open window")
    monkeypatch.setattr(kalshi_api, "fetch_market", _boom)

    run_async(ct._sweep_other_envs_and_reap("demo"))
    with db.get_db() as conn:
        row = db.fetch_crypto15m_by_id(conn, pid)
    assert row["resolved"] == 0 and row["status"] == "filled"


def test_paper_runner_opens_dry_run_row(fresh_db, env_demo, cfg, monkeypatch):
    _no_real_orders(monkeypatch)
    cfg["crypto15m_runners"] = [runner("r1", ["BTC"])]
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset("BTC")]))
    run_async(ct.run_tick(cfg, authed=False))
    with db.get_db() as conn:
        rows = db.get_open_crypto15m(conn, "demo")
    assert len(rows) == 1
    assert rows[0]["dry_run"] == 1
    assert rows[0]["runner_id"] == "r1"
    assert rows[0]["status"] == "submitted"


def test_paper_fill_then_settlement_books_pnl(fresh_db, env_demo, cfg, monkeypatch):
    _no_real_orders(monkeypatch)
    cfg["crypto15m_runners"] = [runner("r1", ["BTC"])]
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset("BTC")]))
    run_async(ct.run_tick(cfg, authed=False))

    async def _quote(_ticker):
        return {"yes_bid_dollars": 0.85, "yes_ask_dollars": 0.87,
                "status": "open", "result": ""}
    monkeypatch.setattr(kalshi_api, "fetch_market", _quote)
    run_async(ct.run_tick(cfg, authed=False))
    with db.get_db() as conn:
        row = db.get_open_crypto15m(conn, "demo")[0]
    assert row["status"] == "filled"
    assert row["filled_contracts"] == 1
    assert row["cost_usd"] > 0

    async def _settled(_ticker):
        return {"status": "finalized", "result": "yes",
                "yes_bid_dollars": 1.0, "yes_ask_dollars": 1.0}
    monkeypatch.setattr(kalshi_api, "fetch_market", _settled)
    with db.get_db() as conn:
        db.update_crypto15m_position(
            conn, row["id"],
            close_time=(datetime.now(timezone.utc) - timedelta(minutes=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"))
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([]))
    run_async(ct.run_tick(cfg, authed=False))
    with db.get_db() as conn:
        settled = db.fetch_crypto15m_by_id(conn, row["id"])
    assert settled["resolved"] == 1
    assert settled["status"] == "settled"
    assert settled["pnl_usd"] > 0


def test_paper_stop_loss_exits_on_price_drop(fresh_db, env_demo, cfg, monkeypatch):
    _no_real_orders(monkeypatch)
    cfg["crypto15m_runners"] = [runner("r1", ["BTC"], config={"crypto15m_stop_loss_pct": 0.20})]
    monkeypatch.setattr(crypto15m, "snapshot", _stub_snapshot([signal_asset("BTC")]))
    run_async(ct.run_tick(cfg, authed=False))
    with db.get_db() as conn:
        rid = db.get_open_crypto15m(conn, "demo")[0]["id"]

    async def _fill(_ticker):
        return {"yes_bid_dollars": 0.85, "yes_ask_dollars": 0.87}
    monkeypatch.setattr(kalshi_api, "fetch_market", _fill)
    run_async(ct.run_tick(cfg, authed=False))

    async def _drop(_ticker):
        return {"yes_bid_dollars": 0.40, "yes_ask_dollars": 0.42}
    monkeypatch.setattr(kalshi_api, "fetch_market", _drop)
    run_async(ct.run_tick(cfg, authed=False))
    with db.get_db() as conn:
        row = db.fetch_crypto15m_by_id(conn, rid)
    assert row["resolved"] == 1
    assert row["exit_reason"] == "stop_loss"
    assert row["pnl_usd"] < 0


def test_two_paper_runners_trade_different_coins_in_parallel(fresh_db, env_demo, cfg, monkeypatch):
    _no_real_orders(monkeypatch)
    cfg["crypto15m_runners"] = [
        runner("btc", ["BTC"], config={"crypto15m_take_profit_cents": 95}),
        runner("eth", ["ETH"], config={"crypto15m_take_profit_cents": 90}),
    ]
    monkeypatch.setattr(crypto15m, "snapshot",
                        _stub_snapshot([signal_asset("BTC"), signal_asset("ETH")]))
    run_async(ct.run_tick(cfg, authed=False))
    with db.get_db() as conn:
        rows = {r["asset"]: r for r in db.get_open_crypto15m(conn, "demo")}
    assert set(rows) == {"BTC", "ETH"}
    assert rows["BTC"]["runner_id"] == "btc"
    assert rows["ETH"]["runner_id"] == "eth"


def test_runner_stats_split_paper_and_live(fresh_db, env_demo, cfg):
    with db.get_db() as conn:
        for i, pnl in enumerate((1.5, -0.5)):
            pid = db.insert_crypto15m_position(conn, {
                "asset": "BTC", "series": "KXBTC15M", "ticker": f"T{i}",
                "side": "up", "direction": "yes", "target_contracts": 1,
                "entry_limit_cents": 80, "client_order_id": f"c{i}",
                "status": "settled", "kalshi_env": "demo", "dry_run": True,
                "runner_id": "r1",
            })
            db.update_crypto15m_position(conn, pid, resolved=1, filled_contracts=1,
                                         pnl_usd=pnl)
        stats = db.crypto15m_runner_stats(conn, "demo")
    paper = [s for s in stats if s["runner_id"] == "r1" and s["mode"] == "paper"]
    assert len(paper) == 1
    assert paper[0]["n"] == 2 and paper[0]["wins"] == 1


def test_history_excludes_paper_unless_requested(fresh_db, env_demo):
    with db.get_db() as conn:
        for i, dry in enumerate((True, False)):
            pid = db.insert_crypto15m_position(conn, {
                "asset": "BTC", "series": "KXBTC15M", "ticker": f"T{i}",
                "side": "up", "direction": "yes", "target_contracts": 1,
                "entry_limit_cents": 80, "client_order_id": f"c{i}",
                "status": "settled", "kalshi_env": "demo", "dry_run": dry,
            })
            db.update_crypto15m_position(conn, pid, resolved=1, filled_contracts=1, pnl_usd=0.1)
        real_only = db.recent_crypto15m_resolved(conn, "demo")
        with_paper = db.recent_crypto15m_resolved(conn, "demo", include_paper=True)
    assert len(real_only) == 1 and all(not r["dry_run"] for r in real_only)
    assert len(with_paper) == 2
