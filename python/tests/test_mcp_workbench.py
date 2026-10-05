from __future__ import annotations

import asyncio
import json

import pytest

import db
import mcp_server
import mcp_workbench as wb
import service
from config import DEFAULT_CONFIG, merge_with_defaults

SAFE_SCRIPT = '''"""
name: Agent test
version: 1
"""

def decide(ctx):
    return None
'''


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def state():
    db.init_db()
    with db.get_db() as conn:
        for t in ("mcp_actions", "user_scripts", "crypto15m_signals",
                  "whale_trades", "alerts"):
            conn.execute(f"DELETE FROM {t}")
    mcp_server._hits.clear()
    wb._last_patch = 0.0
    st = {"cfg": {"mcp_enabled": True, "mcp_trade_mode": "paper"}, "events": []}

    async def _emit(name, data):
        st["events"].append((name, data))

    mcp_server.configure(
        get_cfg=lambda: merge_with_defaults(dict(st["cfg"])),
        is_authed=lambda: False, rpc=service._mcp_rpc, emit=_emit,
        notify_phone=None, submit=None, cancel=None)
    yield st


def _call(name, args=None):
    res = run(mcp_server.call_tool(name, args or {}, {"client": "pytest"}))
    text = res["content"][0]["text"]
    try:
        return res["isError"], json.loads(text)
    except ValueError:
        return res["isError"], text


def _patches(state):
    return [d["patch"] for n, d in state["events"] if n == "mcp:configPatch"]


def _allow(state, *perms):
    for p in perms:
        state["cfg"][p] = True


def test_every_config_key_is_classified():
    unclassified = [k for k in DEFAULT_CONFIG if wb.classify(k) == "unknown"]
    assert not unclassified, unclassified
    overlap = (wb.LIVE & wb.SETTINGS) | (wb.PROTECTED & (wb.LIVE | wb.SETTINGS))
    assert not overlap, overlap


def test_the_lines_no_toggle_crosses():
    for k in ("kalshi_env", "mcp_trade_mode", "mcp_max_order_usd",
              "mcp_allow_live_switches", "remote_trading_enabled", "ai_model",
              "stats_webhook_url", "terminal_max_notional_usd",
              "crypto15m_record_signals"):
        assert wb.classify(k) == "protected", k
    for k in ("enable_trading", "crypto15m_live", "scripts_live_enabled",
              "stop_loss_on_day", "max_total_exposure_fraction", "fee_aware_edge"):
        assert wb.classify(k) == "live", k


def test_permissions_cannot_be_switched_on_by_a_malformed_config():
    cfg = merge_with_defaults({"mcp_allow_live_switches": "true",
                               "mcp_allow_scripts": 1})
    assert cfg["mcp_allow_live_switches"] is False
    assert cfg["mcp_allow_scripts"] is False


def test_workbench_tools_are_absent_until_switched_on(state):
    names = {t.name for t in mcp_server.visible_tools(merge_with_defaults(state["cfg"]))}
    assert not names & {"summarize_research", "save_script", "update_engine_config",
                        "set_script_enabled"}
    err, body = _call("summarize_research", {"dataset": "whale_trades", "group_by": "category"})
    assert err and "disabled" in body
    _allow(state, "mcp_allow_research")
    names = {t.name for t in mcp_server.visible_tools(merge_with_defaults(state["cfg"]))}
    assert "summarize_research" in names and "save_script" not in names


def test_settings_permission_does_not_reach_live_switches(state):
    _allow(state, "mcp_allow_config")
    err, body = _call("update_engine_config", {"patch": {"enable_trading": True}})
    assert err and "live switch" in body
    assert _patches(state) == []
    err, body = _call("update_engine_config",
                      {"patch": {"crypto15m_entry_threshold": 0.8}})
    assert not err, body
    assert _patches(state) == [{"crypto15mEntryThreshold": 0.8}]


def test_live_permission_can_start_an_engine_and_is_audited(state):
    _allow(state, "mcp_allow_live_switches")
    err, body = _call("update_engine_config",
                      {"patch": {"enableTrading": True, "crypto15m_live": True}})
    assert not err, body
    assert _patches(state) == [{"enableTrading": True, "crypto15mLive": True}]
    acts = wb.actions()
    assert acts[0]["ok"] and "enable_trading" in acts[0]["summary"]


def test_no_toggle_lets_an_agent_change_env_or_its_own_rails(state):
    _allow(state, *mcp_server.PERMISSIONS)
    for key in ("kalshi_env", "mcp_max_order_usd", "mcp_trade_mode",
                "mcp_allow_live_switches", "kalshiEnv", "mcpDailySpendUsd"):
        err, body = _call("update_engine_config", {"patch": {key: "x"}})
        assert err and "never" in body, key
        wb._last_patch = 0.0
    assert _patches(state) == []
    assert not wb.actions()[0]["ok"]


def test_a_mixed_patch_is_all_or_nothing_unless_partial_is_asked_for(state):
    _allow(state, "mcp_allow_config")
    patch = {"crypto15m_entry_threshold": 0.83, "kalshi_env": "production"}
    err, body = _call("update_engine_config", {"patch": patch})
    assert err and "nothing applied" in body
    err, body = _call("update_engine_config", {"patch": patch, "apply_partial": True})
    assert not err
    assert _patches(state) == [{"crypto15mEntryThreshold": 0.83}]


def test_values_are_reported_after_the_normal_clamps(state):
    _allow(state, "mcp_allow_live_switches")
    sanitized, refusals = wb.vet_patch({"max_open_positions": 10 ** 9},
                                       merge_with_defaults(state["cfg"]))
    assert not refusals
    assert sanitized["max_open_positions"] < 10 ** 9


def test_settings_changes_are_rate_limited(state):
    _allow(state, "mcp_allow_config")
    assert not _call("update_engine_config", {"patch": {"crypto15m_entry_threshold": 0.71}})[0]
    err, body = _call("update_engine_config", {"patch": {"crypto15m_entry_threshold": 0.72}})
    assert err and "per" in body


def test_unknown_keys_are_refused():
    sanitized, refusals = wb.vet_patch({"definitely_not_a_key": 1},
                                       merge_with_defaults({"mcp_allow_live_switches": True}))
    assert not sanitized and "not a setting" in refusals[0]


def _user_script(sid="user-1", trusted=False, author=None):
    with db.get_db() as conn:
        db.upsert_user_script(conn, {"id": sid, "name": "Mine", "code": SAFE_SCRIPT})
        conn.execute("UPDATE user_scripts SET trusted=?, author=? WHERE id=?",
                     (1 if trusted else 0, author, sid))


def test_agent_scripts_are_saved_sandboxed_and_off(state):
    _allow(state, "mcp_allow_scripts")
    err, body = _call("save_script", {"code": SAFE_SCRIPT})
    assert not err, body
    row = wb._script(body["id"])
    assert row["author"] == "mcp" and row["enabled"] == 0 and row["trusted"] == 0
    assert body["id"].startswith("mcp-")


def test_an_agent_cannot_overwrite_the_users_script(state):
    _allow(state, "mcp_allow_scripts")
    _user_script()
    err, body = _call("save_script", {"id": "user-1", "code": SAFE_SCRIPT + "\n# x"})
    assert err and "written by the user" in body
    assert "# x" not in wb._script("user-1")["code"]


def test_an_agent_cannot_edit_a_script_the_user_made_trusted(state):
    _allow(state, "mcp_allow_scripts", "mcp_allow_script_run")
    _user_script("mcp-abc", trusted=True, author="mcp")
    err, body = _call("save_script", {"id": "mcp-abc", "code": SAFE_SCRIPT})
    assert err and "trusted" in body
    err, body = _call("set_script_enabled", {"id": "mcp-abc", "enabled": True})
    assert err and "Trusted" in body


def test_saving_new_code_disarms_a_running_agent_script(state):
    _allow(state, "mcp_allow_scripts")
    _user_script("mcp-run", author="mcp")
    with db.get_db() as conn:
        conn.execute("UPDATE user_scripts SET enabled=1 WHERE id='mcp-run'")
    assert not _call("save_script", {"id": "mcp-run", "code": SAFE_SCRIPT + "\n"})[0]
    assert wb._script("mcp-run")["enabled"] == 0


def test_run_permission_is_separate_and_only_covers_its_own_scripts(state):
    _allow(state, "mcp_allow_scripts")
    _user_script("mcp-own", author="mcp")
    err, body = _call("set_script_enabled", {"id": "mcp-own", "enabled": True})
    assert err and "disabled" in body
    _allow(state, "mcp_allow_script_run")
    _user_script("user-2")
    err, body = _call("set_script_enabled", {"id": "user-2", "enabled": True})
    assert err and "only switch scripts it wrote" in body
    err, body = _call("set_script_enabled", {"id": "mcp-own", "enabled": True})
    assert not err, body
    assert wb._script("mcp-own")["enabled"] == 1
    assert "signal-only" in body["scriptsMode"]


def test_a_trusted_script_is_never_backtested_unsandboxed_by_an_agent(state):
    _allow(state, "mcp_allow_scripts")
    _user_script("t-1", trusted=True)
    err, body = _call("backtest_script", {"id": "t-1"})
    assert err and "trusted" in body.lower()


def test_crypto15m_summary_reports_gross_edge_against_price_paid(state):
    _allow(state, "mcp_allow_research")
    with db.get_db() as conn:
        for i in range(10):
            conn.execute(
                "INSERT INTO crypto15m_signals (ticker, asset, close_time, favorite, "
                "entry_cost, resolved, up_won, kalshi_env, observed_at) "
                "VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
                (f"T{i}", "BTC", "2026-10-04T12:15:00Z", "up", 0.94, 1,
                 1 if i < 9 else 0, "production"))
    err, body = _call("summarize_research",
                      {"dataset": "crypto15m_signals", "group_by": "asset"})
    assert not err, body
    b = body["buckets"][0]
    assert b["n"] == 10 and b["favorite_win_rate"] == 0.9
    assert b["gross_edge_cents"] == pytest.approx(-4.0)
    assert "GROSS" in body["note"]


def test_signal_prices_are_normalised_and_zero_is_absent(state):
    _allow(state, "mcp_allow_research")
    with db.get_db() as conn:
        conn.execute("INSERT INTO whale_trades (trade_id, ticker, category, price, "
                     "resolved, outcome_correct) VALUES ('a','X','sports',0.62,1,1)")
        conn.execute("INSERT INTO whale_trades (trade_id, ticker, category, price, "
                     "resolved, outcome_correct) VALUES ('b','Y','sports',0,1,0)")
        conn.execute("INSERT INTO alerts (ticker, category, price, resolved, "
                     "outcome_correct) VALUES ('Z','sports',62,1,1)")
    _, whales = _call("summarize_research", {"dataset": "whale_trades", "group_by": "category"})
    assert whales["buckets"][0]["avg_price_cents"] == 62.0
    assert whales["buckets"][0]["hit_rate"] == 0.5
    _, alerts = _call("summarize_research", {"dataset": "momentum_alerts", "group_by": "category"})
    assert alerts["buckets"][0]["avg_price_cents"] == 62.0


def test_group_by_is_a_closed_set():
    with pytest.raises(mcp_server.ToolError):
        run(wb.t_summarize({"dataset": "whale_trades",
                            "group_by": "category; DROP TABLE whale_trades"}, {}))


def test_sample_rows_are_capped_and_hide_internal_columns(state):
    _allow(state, "mcp_allow_research")
    with db.get_db() as conn:
        for i in range(5):
            conn.execute("INSERT INTO whale_trades (trade_id, ticker, price) "
                         "VALUES (?, 'X', 0.5)", (f"s{i}",))
    err, body = _call("sample_research_rows", {"dataset": "whale_trades", "limit": 3})
    assert not err and body["count"] == 3
    assert "discord_sent" not in body["rows"][0]


def test_backtest_results_are_trimmed_for_the_model():
    out = wb.trim({"trades": list(range(100)), "summary": {"n": 100}})
    assert len(out["trades"]) == wb.LIST_CAP + 1
    assert "75 more" in out["trades"][-1]
    assert out["summary"] == {"n": 100}


def test_the_rpc_door_only_opens_onto_named_handlers():
    for m in ("setConfig", "setCredentials", "terminalSubmit", "scriptSetTrusted",
              "factoryReset"):
        with pytest.raises(ValueError):
            run(service._mcp_rpc(m, {}))
