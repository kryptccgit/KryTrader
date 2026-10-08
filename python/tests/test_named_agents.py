"""The user's own named agents: identity, rules, ownership, records.

Before this, every client shared one token and one set of rails, so "an agent
may only sell what it opened" meant "any client may sell what any client
opened", and two traders with different instructions were indistinguishable
on the scoreboard. What is pinned here:

  * the token decides the agent — on MCP, HTTP and the stdio bridge — and the
    original token is the Default agent's, so old configs keep working;
  * a deleted agent's token stops working at once, and its file is removed;
  * every rule refuses with the agent's name, and NO rule can loosen a global
    rail (an agent min edge under the global one, caps over the global ones);
  * per-agent and global spend both hold under concurrency (_money_lock);
  * one agent cannot sell or cancel what another opened;
  * the global trade mode is the master over each agent's paper/live;
  * Autopilot runs as the agent the user picked, inside its rules;
  * the migrations are idempotent and safe on a pre-agents database.
"""
from __future__ import annotations

import asyncio
import io
import json
import socket
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

import autopilot
import db
import forecast_ledger
import kalshi_auth
import mcp_agents
import mcp_bridge
import mcp_server
import mcp_workbench as wb
import paper_book
import terminal
from config import DEFAULT_CONFIG, merge_with_defaults

SPORTS = "KXNBA-26OCT-LALBOS"
CRYPTO = "KXBTC-26OCT-T100"
NOCAT = "KXODD-26OCT-T1"


def _close_in(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


MARKETS = {
    SPORTS: {"ticker": SPORTS, "title": "Lakers at Celtics", "status": "active",
             "category": "Sports", "closeTime": _close_in(20)},
    CRYPTO: {"ticker": CRYPTO, "title": "BTC above 100k", "status": "active",
             "category": "Crypto", "closeTime": _close_in(24 * 6)},
    NOCAT: {"ticker": NOCAT, "title": "Something odd", "status": "active",
            "category": None, "closeTime": _close_in(10)},
}
QUOTE = {"yesBid": 50.0, "yesAsk": 54.0, "noBid": 46.0, "noAsk": 50.0,
         "midCents": 52.0, "spreadCents": 4.0}
BOOK = {
    "yes": [{"priceCents": 50.0, "contracts": 500}, {"priceCents": 15.0, "contracts": 500}],
    "no": [{"priceCents": 46.0, "contracts": 500}, {"priceCents": 10.0, "contracts": 500}],
    "yesBid": 50.0, "yesAsk": 54.0, "stale": False, "source": "kalshi-ws",
}

SAM = {"id": "sam1", "name": "Sports Sam", "emoji": "🏀", "color": "#F59E0B",
       "guide": "You trade NBA games only. Skip anything you can't explain in a sentence.",
       "mode": "paper", "enabled": True,
       "rules": {"categoriesAllow": ["sports"], "minPriceCents": 20, "maxPriceCents": 80,
                 "maxHoursToClose": 48}}
RES = {"id": "res1", "name": "Careful Researcher", "mode": "paper", "enabled": True,
       "guide": "Forecast everything, trade rarely.", "rules": {}}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def rig(monkeypatch):
    db.init_db()
    with db.get_db() as conn:
        for t in ("ai_forecasts", "paper_fills", "paper_state", "mcp_orders"):
            conn.execute(f"DELETE FROM {t}")
    mcp_server._hits.clear()
    mcp_server.AGENT_SEEN.clear()
    old_env = kalshi_auth.get_env()
    kalshi_auth.set_env("production")
    st = {"cfg": {"account_mode": "live", "mcp_enabled": True, "mcp_http_enabled": True, "mcp_trade_mode": "paper",
                  "mcp_min_edge_cents": 0.0,
                  "mcp_agents": [{"id": "default", "name": "Default"}, dict(SAM), dict(RES)]},
          "sent": [], "fills": {}, "events": [], "phone": []}

    async def _submit(req, scope=None):
        await asyncio.sleep(0.01)
        st["sent"].append(req)
        return {"ok": True, "orderId": f"ord-{len(st['sent'])}", "message": "Placed.",
                "filledContracts": 0, "avgFillCents": None, "status": "resting"}

    async def _cancel(oid):
        return {"ok": True, "message": "Cancelled."}

    async def _emit(name, data):
        st["events"].append((name, data))

    async def _phone(text):
        st["phone"].append(text)

    mcp_server.configure(get_cfg=lambda: merge_with_defaults(dict(st["cfg"])),
                         is_authed=lambda: True, submit=_submit, cancel=_cancel,
                         emit=_emit, notify_phone=_phone, version="test")

    async def _row(ticker):
        await asyncio.sleep(0.01)
        m = MARKETS.get(ticker)
        return dict(m, **QUOTE) if m else None

    async def _book(ticker):
        await asyncio.sleep(0.002)
        return dict(BOOK, ticker=ticker)

    async def _no_series(_m):
        return None

    async def _pf(authed):
        tickers = {r["ticker"] for r in st["sent"] if r["action"] == "buy"}
        return {"positions": [{"ticker": t, "side": "yes", "contracts": 100,
                               "unrealizedUsd": 0.0} for t in tickers]}

    async def _fills(order_id, side, pin_env=None):
        return st["fills"].get(order_id, (0, None))

    async def _resting(authed):
        return {"orders": [{"orderId": f"ord-{i + 1}", "ticker": r["ticker"]}
                           for i, r in enumerate(st["sent"])]}

    monkeypatch.setattr(mcp_server, "_market_row", _row)
    monkeypatch.setattr(terminal, "book", _book)
    monkeypatch.setattr(terminal, "portfolio", _pf)
    monkeypatch.setattr(terminal, "manual_history", lambda limit=300: {"trades": []})
    monkeypatch.setattr(terminal, "_reconcile_fills", _fills)
    monkeypatch.setattr(terminal, "resting_orders", _resting)
    monkeypatch.setattr(mcp_server, "_THROTTLE", mcp_server._Throttle())
    import kalshi_api

    async def _series(_t):
        return None
    monkeypatch.setattr(kalshi_api, "fetch_series", _series)
    yield st
    kalshi_auth.set_env(old_env)


def _agents(st, *upd):
    """Replace agents by id with updated copies."""
    cur = {a["id"]: dict(a) for a in st["cfg"]["mcp_agents"]}
    for a in upd:
        cur[a["id"]] = a
    st["cfg"]["mcp_agents"] = list(cur.values())


def _call(name, args=None, agent=None, client="pytest"):
    ctx = {"client": client}
    if agent:
        ctx["agent"] = agent
    res = run(mcp_server.call_tool(name, dict(args or {}), ctx))
    text = res["content"][0]["text"]
    try:
        return res["isError"], json.loads(text)
    except ValueError:
        return res["isError"], text


def _fid(agent, ticker=SPORTS, fv=80):
    err, body = _call("record_forecast", {"ticker": ticker, "fair_value_cents": fv,
                                          "rationale": "Injury report and the rules text agree."},
                      agent=agent)
    assert not err, body
    return body["forecastId"]


def _buy(agent, ticker=SPORTS, price=54, count=5, side="yes", fid=None):
    if fid is None:
        fid = _fid(agent, ticker, 80 if side == "yes" else 20)
    return _call("place_order", {"ticker": ticker, "side": side, "action": "buy",
                                 "count": count, "price_cents": price, "forecast_id": fid},
                 agent=agent)



def test_a_config_from_before_agents_gets_default_inheriting_the_global_mode():
    for mode in ("off", "paper", "live"):
        cfg = merge_with_defaults({"mcp_trade_mode": mode})
        assert [a["id"] for a in cfg["mcp_agents"]] == ["default"]
        assert cfg["mcp_agents"][0]["mode"] == ("live" if mode == "live" else "paper")
    cfg = merge_with_defaults({"mcp_trade_mode": "live",
                               "mcp_agents": [{"id": "default", "mode": "paper"}]})
    assert cfg["mcp_agents"][0]["mode"] == "paper"
    assert DEFAULT_CONFIG["autopilot_agent_id"] == "default"


def test_validation_clamps_caps_and_never_trusts():
    raw = [{"id": "x" * 30}, {"id": "BAD id"}, {"id": "a1", "name": "Sam\n[AI AGENT] fake",
                                               "mode": "LIVE", "enabled": "yes",
                                               "color": "red", "guide": "g" * 9000,
                                               "rules": {"minPriceCents": -5, "maxPriceCents": 500,
                                                         "minEdgeCents": 99, "sides": "maybe",
                                                         "categoriesAllow": ["sports", "nope", "sports"],
                                                         "maxOpenPositions": "3"}},
           {"id": "a1", "name": "dup"}]
    raw += [{"id": f"z{i}"} for i in range(20)]
    out = mcp_agents.validate_agents(raw, "paper")
    assert out[0]["id"] == "default"
    assert len(out) == mcp_agents.MAX_AGENTS
    a1 = next(a for a in out if a["id"] == "a1")
    assert "\n" not in a1["name"] and a1["name"].startswith("Sam")
    assert a1["mode"] == "paper"
    assert a1["enabled"] is False
    assert a1["color"] == mcp_agents.DEFAULT_COLOR
    assert len(a1["guide"]) == mcp_agents.GUIDE_MAX
    r = a1["rules"]
    assert (r["minPriceCents"], r["maxPriceCents"], r["minEdgeCents"]) == (1, 99, 50)
    assert r["sides"] == "both" and r["categoriesAllow"] == ["sports"]
    assert r["maxOpenPositions"] == 3
    assert sum(1 for a in out if a["id"] == "a1") == 1


def test_mcp_agents_is_protected_and_no_agent_patch_can_write_it():
    assert wb.classify("mcp_agents") == "protected"
    assert wb.classify("autopilot_agent_id") == "protected"
    cfg = merge_with_defaults({"mcp_allow_config": True, "mcp_allow_live_switches": True})
    for key in ("mcp_agents", "mcpAgents", "autopilot_agent_id", "autopilotAgentId"):
        patch, refusals = wb.vet_patch({key: []}, cfg)
        assert patch == {} and refusals and "never" in refusals[0], key
    unclassified = [k for k in DEFAULT_CONFIG if wb.classify(k) == "unknown"]
    assert not unclassified, unclassified



def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def _http(port, method, path, token, body=None):
    async def _go():
        r, w = await asyncio.open_connection("127.0.0.1", port)
        data = json.dumps(body).encode() if body is not None else b""
        head = (f"{method} {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                f"Content-Type: application/json\r\nUser-Agent: pytest-bot/1\r\n")
        if token:
            head += f"Authorization: Bearer {token}\r\n"
        head += f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n"
        w.write(head.encode() + data)
        await w.drain()
        raw = await r.read()
        w.close()
        return raw
    raw = asyncio.run(_go())
    hdr, _, payload = raw.partition(b"\r\n\r\n")
    status = int(hdr.split(b" ", 2)[1])
    return status, (json.loads(payload) if payload else None)


def _serve(port, fn):
    async def _go():
        await mcp_server.start(port)
        try:
            return await asyncio.to_thread(fn)
        finally:
            await mcp_server.stop()
    return asyncio.run(_go())


def test_each_token_is_its_agent_over_http_and_default_keeps_the_old_token(rig):
    port = _free_port()
    old = mcp_server.rotate_token()
    assert kalshi_auth.read_secret("mcp_token") == old
    sam = mcp_server.rotate_token("sam1")
    assert kalshi_auth.read_secret("mcp_token_sam1") == sam and sam != old

    def _who(tok):
        return _http(port, "POST", "/api/v1/tools/get_my_agent", tok, {})

    def body():
        return _who(old), _who(sam), _who("kt_nope"), _who(None)
    (s1, b1), (s2, b2), (s3, _), (s4, _) = _serve(port, body)
    assert s1 == 200 and b1["result"]["name"] == "Default"
    assert s2 == 200 and b2["result"]["name"] == "Sports Sam"
    assert s3 == 401 and s4 == 401


def test_rotating_one_agents_token_leaves_the_others_working(rig):
    port = _free_port()
    old = mcp_server.rotate_token()
    sam = mcp_server.rotate_token("sam1")
    sam2 = mcp_server.rotate_token("sam1")

    def body():
        return (_http(port, "GET", "/api/v1/tools", old)[0],
                _http(port, "GET", "/api/v1/tools", sam)[0],
                _http(port, "GET", "/api/v1/tools", sam2)[0])
    assert _serve(port, body) == (200, 401, 200)


def test_a_deleted_agents_token_is_refused_at_once_and_pruned(rig):
    port = _free_port()
    mcp_server.rotate_token()
    sam = mcp_server.rotate_token("sam1")
    rig["cfg"]["mcp_agents"] = [a for a in rig["cfg"]["mcp_agents"] if a["id"] != "sam1"]
    assert kalshi_auth.has_secret("mcp_token_sam1")
    st, _ = _serve(port, lambda: _http(port, "GET", "/api/v1/tools", sam))
    assert st == 401
    import service
    service._MAIN_AGENT_IDS[0] = {"default", "sam1", "res1"}
    service._prune_deleted_agent_tokens({"mcpAgents": rig["cfg"]["mcp_agents"]})
    assert not kalshi_auth.has_secret("mcp_token_sam1")
    assert kalshi_auth.has_secret("mcp_token")
    _agents(rig, dict(SAM))
    st, _ = _serve(port, lambda: _http(port, "GET", "/api/v1/tools", sam))
    assert st == 401


def test_a_restart_never_prunes_the_named_agents_tokens(rig):
    """The backend syncs the listener at startup on built-in defaults, whose
    agent list is just Default — before main has sent the user's config.
    Pruning against that would delete every named agent's token on every
    restart, and every client connected as one would stop working."""
    import service
    mcp_server.rotate_token("sam1")
    run(mcp_server.sync(merge_with_defaults({"mcp_enabled": False})))
    assert kalshi_auth.has_secret("mcp_token_sam1")
    service._MAIN_AGENT_IDS[0] = None
    service._prune_deleted_agent_tokens({"mcpAgents": [{"id": "default"}]})
    assert kalshi_auth.has_secret("mcp_token_sam1")
    service._MAIN_AGENT_IDS[0] = {"default", "sam1"}
    service._prune_deleted_agent_tokens({})
    assert kalshi_auth.has_secret("mcp_token_sam1")
    assert service._MAIN_AGENT_IDS[0] == {"default", "sam1"}
    assert mcp_server.deleted_agents({"default", "sam1"}, {"default"}) == {"sam1"}
    assert mcp_server.deleted_agents(None, {"default"}) == set()
    assert mcp_server.deleted_agents({"default"}, set()) == set()
    service._MAIN_AGENT_IDS[0] = None


def test_an_unreadable_token_is_not_cached_or_rotated_over(rig, monkeypatch):
    tok = mcp_server.rotate_token("sam1")
    mcp_server._TOKENS.clear()
    real = kalshi_auth.read_secret
    monkeypatch.setattr(kalshi_auth, "read_secret", lambda name: None)
    assert mcp_server.get_token(False, "sam1") is None
    with pytest.raises(RuntimeError):
        mcp_server.get_token(True, "sam1")
    monkeypatch.setattr(kalshi_auth, "read_secret", real)
    assert mcp_server.get_token(False, "sam1") == tok


def test_scripts_are_owned_per_agent_and_forecast_only_agents_write_none(rig):
    wb._last_patch = 0.0
    rig["cfg"].update(mcp_allow_scripts=True, mcp_allow_script_run=True, mcp_allow_config=True)
    with db.get_db() as conn:
        conn.execute("DELETE FROM user_scripts WHERE id LIKE 'qa-%'")
        conn.execute("INSERT INTO user_scripts (id, name, code, author, enabled, trusted) "
                     "VALUES ('qa-sam', 'sam', 'x', 'mcp:sam1', 0, 0)")
        conn.execute("INSERT INTO user_scripts (id, name, code, author, enabled, trusted) "
                     "VALUES ('qa-def', 'old', 'x', 'mcp', 0, 0)")
    err, body = _call("set_script_enabled", {"id": "qa-sam", "enabled": True}, agent="res1")
    assert err and "another agent's" in body
    err, body = _call("save_script", {"id": "qa-sam", "code": "def f(): pass"}, agent="res1")
    assert err and "another of the user's agents" in body
    err, body = _call("set_script_enabled", {"id": "qa-def", "enabled": True}, agent="sam1")
    assert err
    _agents(rig, dict(RES, rules={"maxOpenPositions": 0}))
    err, body = _call("update_engine_config", {"patch": {"crypto15m_entry_threshold": 0.8}}, agent="res1")
    assert err and "records forecasts only" in body
    err, body = _call("save_script", {"code": "def f(): pass"}, agent="res1")
    assert err and "records forecasts only" in body
    with db.get_db() as conn:
        conn.execute("DELETE FROM user_scripts WHERE id LIKE 'qa-%'")


def test_place_refuses_an_agent_deleted_after_the_dispatch_check(rig, monkeypatch):
    calls = {"n": 0}
    real = mcp_server.HOOKS.get_cfg

    def flaky():
        calls["n"] += 1
        c = real()
        if calls["n"] > 1:
            c = dict(c, mcp_agents=[a for a in c["mcp_agents"] if a["id"] != "sam1"])
        return c
    fid = _fid("sam1")
    monkeypatch.setattr(mcp_server.HOOKS, "get_cfg", flaky)
    calls["n"] = 0
    err, body = _call("place_order", {"ticker": SPORTS, "side": "yes", "action": "buy",
                                      "count": 5, "price_cents": 54, "forecast_id": fid}, agent="sam1")
    assert err and "no longer exists" in body
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM mcp_orders").fetchone()[0] == 0


def test_a_switched_off_agent_is_refused(rig):
    port = _free_port()
    mcp_server.rotate_token()
    sam = mcp_server.rotate_token("sam1")
    _agents(rig, dict(SAM, enabled=False))
    st, body = _serve(port, lambda: _http(port, "GET", "/api/v1/tools", sam))
    assert st == 403 and "switched off" in body["error"]
    err, text = _call("get_status", agent="sam1")
    assert err and "switched off" in text


def test_mcp_initialize_names_the_agent_its_guide_and_rules(rig):
    port = _free_port()
    mcp_server.rotate_token()
    sam = mcp_server.rotate_token("sam1")

    def body():
        return _http(port, "POST", "/mcp", sam, {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "clientInfo": {"name": "pytest"}}})
    st, res = _serve(port, body)
    text = res["result"]["instructions"]
    assert st == 200 and text.startswith(mcp_server.INSTRUCTIONS)
    assert "YOU ARE: Sports Sam" in text
    assert SAM["guide"] in text
    assert "Only Sports markets." in text and "Entry price between 20¢ and 80¢." in text
    assert "close within 48h" in text
    assert mcp_server.instructions_for({}) == mcp_server.INSTRUCTIONS


def test_the_stdio_bridge_is_the_agent_whose_token_it_carries(rig, monkeypatch):
    port = _free_port()
    mcp_server.rotate_token()
    sam = mcp_server.rotate_token("sam1")

    def _bridge():
        lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                             "params": {"protocolVersion": "2025-06-18"}}) + "\n",
                 json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                             "params": {"name": "get_my_agent", "arguments": {}}}) + "\n"]
        stdin = type("S", (), {"buffer": io.BytesIO("".join(lines).encode())})()
        out = io.BytesIO()
        monkeypatch.setattr(sys, "stdin", stdin)
        monkeypatch.setattr(sys, "stdout", type("S", (), {"buffer": out})())
        monkeypatch.setenv("KRYPT_MCP_TOKEN", sam)
        rc = mcp_bridge.main(["--port", str(port)])
        return rc, [json.loads(x) for x in out.getvalue().decode().splitlines()]
    rc, replies = _serve(port, _bridge)
    assert rc == 0
    me = json.loads(replies[1]["result"]["content"][0]["text"])
    assert me["name"] == "Sports Sam" and me["rules"]["categoriesAllow"] == ["sports"]


def test_client_configs_carry_the_agents_token_and_its_own_server_name(rig):
    sam = merge_with_defaults(dict(rig["cfg"]))["mcp_agents"][1]
    cur = json.loads(mcp_server.client_config("cursor", 47821, "kt_x", sam))
    (name, srv), = cur["mcpServers"].items()
    assert name.startswith("krypt-trader-sports-sam") and srv["headers"]["Authorization"] == "Bearer kt_x"
    assert mcp_server.client_config("codex", 47821, "kt_x", sam).startswith(f"[mcp_servers.{name}]")
    d = merge_with_defaults({})["mcp_agents"][0]
    assert "krypt-trader" in json.loads(mcp_server.client_config("cursor", 1, "t", d))["mcpServers"]



def test_get_my_agent_returns_guide_rules_and_effective_rails(rig):
    rig["cfg"]["mcp_min_edge_cents"] = 3.0
    _agents(rig, dict(SAM, rules=dict(SAM["rules"], minEdgeCents=1, maxOrderUsd=5)))
    err, me = _call("get_my_agent", agent="sam1")
    assert not err
    assert me["name"] == "Sports Sam" and me["guide"] == SAM["guide"] and me["mode"] == "paper"
    assert me["effectiveRails"]["minEdgeCents"] == 3.0
    assert me["effectiveRails"]["maxOrderUsd"] == 5.0
    assert any("Sports" in s for s in me["rulesInWords"])
    err, stt = _call("get_status", agent="sam1")
    assert stt["agent"]["name"] == "Sports Sam" and stt["tradeMode"] == "paper"



def test_category_rule(rig):
    err, body = _buy("sam1", ticker=CRYPTO)
    assert err and "Sports Sam's rules: only Sports markets; this one is Crypto." in body
    err, body = _buy("sam1", ticker=NOCAT)
    assert err and "Sports Sam's rules" in body and "no category" in body
    _agents(rig, dict(RES, rules={"categoriesDeny": ["crypto"]}))
    err, body = _buy("res1", ticker=CRYPTO)
    assert err and "Careful Researcher's rules: never Crypto markets." in body


def test_price_band_rule(rig):
    err, body = _buy("sam1", price=85, fid=_fid("sam1", fv=99))
    assert err and "entry at 85¢ is above Sports Sam's 80¢ max" in body
    err, body = _buy("sam1", price=15, fid=_fid("sam1", fv=90))
    assert err and "below Sports Sam's 20¢ minimum" in body


def test_time_to_close_rule(rig):
    _agents(rig, dict(SAM, rules={"maxHoursToClose": 48}))
    err, body = _buy("sam1", ticker=CRYPTO)
    assert err and "closes in 6.0 days; Sports Sam trades ≤48h" in body
    _agents(rig, dict(SAM, rules={"minHoursToClose": 72}))
    err, body = _buy("sam1", ticker=SPORTS)
    assert err and "wants at least 3 days to close" in body


def test_sides_rule(rig):
    _agents(rig, dict(SAM, rules={"sides": "yes"}))
    err, body = _buy("sam1", side="no", price=50)
    assert err and "Sports Sam's rules: buys YES only." in body


def test_position_and_per_market_rules(rig):
    _agents(rig, dict(SAM, rules={"maxContractsPerMarket": 8}))
    err, body = _buy("sam1", count=5)
    assert not err, body
    err, body = _buy("sam1", count=5)
    assert err and "at most 8 contracts in one market; it has 5" in body
    _agents(rig, dict(SAM, rules={"maxOpenPositions": 1}))
    err, body = _buy("sam1", ticker=CRYPTO, price=54)
    assert err and "at most 1 open position; it holds 1" in body
    _agents(rig, dict(RES, rules={"maxOpenPositions": 0}))
    err, body = _buy("res1")
    assert err and "Careful Researcher's rules: no positions — it records forecasts only." in body


def test_agent_money_rules_bind_with_the_agents_name(rig):
    _agents(rig, dict(SAM, rules={"maxOrderUsd": 2}))
    err, body = _buy("sam1", count=5)
    assert err and "over Sports Sam's per-order cap of $2.00" in body
    _agents(rig, dict(SAM, rules={"dailySpendUsd": 4}))
    assert not _buy("sam1", count=5)[0]
    err, body = _buy("sam1", count=5)
    assert err and "over Sports Sam's daily cap of $4.00" in body
    assert not _buy("res1", count=5)[0]
    _agents(rig, dict(SAM, rules={"minEdgeCents": 30}))
    err, body = _buy("sam1", count=5, fid=_fid("sam1", fv=70))
    assert err and "the minimum is 30c (Sports Sam's rules)" in body


def test_rules_never_loosen_the_global_rails(rig):
    rig["cfg"].update(mcp_min_edge_cents=20.0, mcp_max_order_usd=3.0, mcp_daily_spend_usd=5.0)
    _agents(rig, dict(SAM, rules={"minEdgeCents": 0, "maxOrderUsd": 1e6, "dailySpendUsd": 1e7}))
    err, body = _buy("sam1", count=5, fid=_fid("sam1", fv=70))
    assert err and "the minimum is 20c." in body and "Sports Sam's rules)" not in body
    err, body = _buy("sam1", count=10, fid=_fid("sam1", fv=95))
    assert err and "over the agent per-order cap of $3.00" in body
    assert not _buy("sam1", count=4, fid=_fid("sam1", fv=95))[0]
    err, body = _buy("sam1", count=5, fid=_fid("sam1", fv=95))
    assert err and "over the daily cap of $5.00" in body
    eff = mcp_agents.effective_rails(mcp_server._rails(merge_with_defaults(rig["cfg"])),
                                     mcp_agents.get(merge_with_defaults(rig["cfg"]), "sam1"))
    assert (eff["minEdgeCents"], eff["maxOrderUsd"], eff["dailySpendUsd"]) == (20.0, 3.0, 5.0)


def test_a_buy_must_cite_its_own_agents_forecast(rig):
    fid = _fid("res1")
    err, body = _buy("sam1", fid=fid)
    assert err and "A buy needs forecast_id from record_forecast" in body
    assert "Careful Researcher" not in body


def test_rules_never_block_an_exit(rig):
    assert not _buy("sam1", count=5)[0]
    _agents(rig, dict(SAM, rules={"categoriesAllow": ["politics"], "maxPriceCents": 10,
                                  "maxOpenPositions": 0, "sides": "no"}))
    err, body = _call("place_order", {"ticker": SPORTS, "side": "yes", "action": "sell",
                                      "count": 5, "price_cents": 40}, agent="sam1")
    assert not err, body



def test_paper_one_agent_cannot_sell_anothers_position(rig):
    assert not _buy("sam1", count=5)[0]
    sell = {"ticker": SPORTS, "side": "yes", "action": "sell", "count": 5, "price_cents": 40}
    err, body = _call("place_order", sell, agent="res1")
    assert err and "holds 0 YES" in body and "not another agent's" in body
    assert paper_book.held(SPORTS, "yes", "sam1") == 5
    assert not _call("place_order", sell, agent="sam1")[0]
    assert paper_book.held(SPORTS, "yes", "sam1") == 0


def test_live_one_agent_cannot_sell_or_cancel_anothers(rig):
    rig["cfg"].update(mcp_trade_mode="live", mcp_live_approval=False, mcp_daily_spend_usd=500.0)
    _agents(rig, dict(SAM, mode="live"), dict(RES, mode="live"))
    err, body = _buy("sam1", count=10)
    assert not err, body
    oid = body["orderId"]
    rig["fills"][oid] = (10, 54.0)
    sell = {"ticker": SPORTS, "side": "yes", "action": "sell", "count": 10, "price_cents": 40}
    err, body = _call("place_order", sell, agent="res1")
    assert err and "0 filled contracts" in body and "Careful Researcher sells only its own" in body
    err, body = _call("cancel_order", {"order_id": oid}, agent="res1")
    assert err and "another of the user's agents" in body
    err, body = _call("list_orders", agent="res1")
    assert not err and body["orders"] == []
    assert [o["orderId"] for o in _call("list_orders", agent="sam1")[1]["orders"]] == [oid]
    err, body = _call("place_order", sell, agent="sam1")
    assert not err, body
    err, body = _call("cancel_order", {"order_id": oid}, agent="sam1")
    assert not err and body["ok"]


def test_an_agent_reads_only_its_own_approvals(rig):
    rig["cfg"].update(mcp_trade_mode="live", mcp_live_approval=True)
    _agents(rig, dict(SAM, mode="live"))
    err, body = _buy("sam1")
    assert not err and body["pending"]
    rid = body["approvalId"]
    assert _call("get_order_status", {"approval_id": rid}, agent="sam1")[1]["status"] == "pending"
    err, body = _call("get_order_status", {"approval_id": rid}, agent="res1")
    assert err and f"No agent order #{rid}" in body



def _gather(calls):
    async def go():
        return await asyncio.gather(*[mcp_server.call_tool(n, dict(a), {"client": "pytest", "agent": ag})
                                      for n, a, ag in calls])
    return run(go())


def test_parallel_buys_from_two_agents_respect_both_caps(rig):
    rig["cfg"].update(mcp_trade_mode="live", mcp_live_approval=False, mcp_daily_spend_usd=10.0)
    _agents(rig, dict(SAM, mode="live", rules={"dailySpendUsd": 4}), dict(RES, mode="live"))
    fs, fr = _fid("sam1"), _fid("res1")
    buy = {"ticker": SPORTS, "side": "yes", "action": "buy", "count": 5, "price_cents": 54}
    calls = [("place_order", dict(buy, forecast_id=fs), "sam1")] * 4
    calls += [("place_order", dict(buy, forecast_id=fr), "res1")] * 4
    res = _gather(calls)
    ok = [r for r in res if not r["isError"]]
    assert len(ok) == 3 == len(rig["sent"])
    env = kalshi_auth.get_env()
    assert mcp_server.spent_today("live") <= 10.0
    assert mcp_server.spent_today("live", agent_id="sam1") <= 4.0
    assert sum(1 for r in res[:4] if not r["isError"]) == 1
    assert env == "production"


def test_parallel_approvals_reveted_as_their_agent(rig):
    rig["cfg"].update(mcp_trade_mode="live", mcp_live_approval=True, mcp_daily_spend_usd=100.0)
    _agents(rig, dict(SAM, mode="live", rules={"dailySpendUsd": 4}))
    ids = [_buy("sam1")[1]["approvalId"] for _ in range(1)]
    _agents(rig, dict(SAM, mode="live", rules={"dailySpendUsd": 1}))
    out = run(mcp_server.decide(ids[0], True))
    assert not out["ok"] and "Sports Sam's daily cap" in out["message"]
    assert rig["sent"] == []



@pytest.mark.parametrize("glob,agent_mode,want", [
    ("off", "paper", "off"), ("off", "live", "off"),
    ("paper", "paper", "paper"), ("paper", "live", "paper"),
    ("live", "paper", "paper"), ("live", "live", "live"),
])
def test_mode_matrix(rig, glob, agent_mode, want):
    rig["cfg"].update(mcp_trade_mode=glob, mcp_live_approval=False)
    _agents(rig, dict(SAM, mode=agent_mode))
    cfg = merge_with_defaults(dict(rig["cfg"]))
    assert mcp_server._agent_mode(cfg, mcp_agents.get(cfg, "sam1")) == want
    fid = _fid("sam1")
    err, body = _call("place_order", {"ticker": SPORTS, "side": "yes", "action": "buy",
                                      "count": 5, "price_cents": 54, "forecast_id": fid},
                      agent="sam1")
    if want == "off":
        assert err and ("off" in body or "disabled" in body)
        assert rig["sent"] == []
    elif want == "paper":
        assert not err and body["mode"] == "paper" and rig["sent"] == []
    else:
        assert not err and body["mode"] == "live" and len(rig["sent"]) == 1


def test_approval_refused_when_the_agent_went_back_to_paper_or_was_deleted(rig):
    rig["cfg"].update(mcp_trade_mode="live", mcp_live_approval=True)
    _agents(rig, dict(SAM, mode="live"))
    r1 = _buy("sam1")[1]["approvalId"]
    r2 = _buy("sam1")[1]["approvalId"]
    assert any("Sports Sam wants to BUY" in t for t in rig["phone"])
    _agents(rig, dict(SAM, mode="paper"))
    out = run(mcp_server.decide(r1, True))
    assert not out["ok"] and "Sports Sam is now on paper" in out["message"]
    rig["cfg"]["mcp_agents"] = [a for a in rig["cfg"]["mcp_agents"] if a["id"] != "sam1"]
    out = run(mcp_server.decide(r2, True))
    assert not out["ok"] and "no longer exists" in out["message"]
    assert rig["sent"] == []



def test_autopilot_runs_as_its_agent_and_inside_its_rules(rig):
    rig["cfg"]["autopilot_agent_id"] = "sam1"
    cfg = merge_with_defaults(dict(rig["cfg"]))
    r = autopilot._Run(cfg, "manual")
    assert r.ctx["agent"] == "sam1"
    sys_prompt = r.system()
    assert "YOU ARE RUNNING AS: Sports Sam" in sys_prompt and SAM["guide"] in sys_prompt
    assert "Only Sports markets." in sys_prompt
    fid = run(r.tool("record_forecast", {"ticker": CRYPTO, "fair_value_cents": 80,
                                          "rationale": "ETF flows and the strike distance."}))
    fid = json.loads(fid[0])["forecastId"]
    text, is_err = run(r.tool("place_order", {"ticker": CRYPTO, "side": "yes", "action": "buy",
                                               "count": 5, "price_cents": 54, "forecast_id": fid}))
    assert is_err and "Sports Sam's rules: only Sports markets" in text
    assert forecast_ledger.get(fid)["agent_id"] == "sam1"


def test_autopilot_refuses_to_run_as_a_missing_or_switched_off_agent(rig):
    cfg = merge_with_defaults(dict(rig["cfg"], autopilot_agent_id="gone1"))
    assert "no longer exists" in autopilot.blocked_reason(cfg)
    _agents(rig, dict(SAM, enabled=False))
    cfg = merge_with_defaults(dict(rig["cfg"], autopilot_agent_id="sam1"))
    assert "switched off" in autopilot.blocked_reason(cfg)
    assert autopilot.status(cfg)["agentName"] == "Sports Sam"



def test_scoreboard_scores_each_agent_on_its_own_forecasts(rig):
    for ag, fv in (("sam1", 80), ("res1", 30)):
        _fid(ag, SPORTS, fv)
    forecast_ledger.record(ticker=SPORTS, prob_yes=0.6, source="panel", market=dict(QUOTE))
    with db.get_db() as conn:
        conn.execute("UPDATE ai_forecasts SET outcome=1.0")
    sb = forecast_ledger.scoreboard()
    by = {r["agentId"]: r for r in sb["byAgent"]}
    assert set(by) == {"sam1", "res1"}
    assert by["sam1"]["n"] == 1 and by["sam1"]["brierAi"] == round((0.8 - 1) ** 2, 4)
    assert by["res1"]["brierAi"] == round((0.3 - 1) ** 2, 4)
    assert by["sam1"]["verdict"] == "too-few"
    err, body = _call("get_scoreboard", agent="sam1")
    assert body["you"]["agentId"] == "sam1"


def test_paper_pnl_is_kept_per_agent(rig):
    assert not _buy("sam1", count=5)[0]
    assert not _buy("res1", count=3)[0]
    marks = {SPORTS: dict(QUOTE)}
    s, r = paper_book.agent_summary("sam1", marks), paper_book.agent_summary("res1", marks)
    assert (s["openPositions"], s["fills"], r["fills"]) == (1, 1, 1)
    whole = paper_book.portfolio(1000.0, marks)
    assert sorted((p["agentId"], p["contracts"]) for p in whole["positions"]) == \
        [("res1", 3), ("sam1", 5)]
    rows = mcp_server.activity()
    assert {(o["agentId"], o["agentName"]) for o in rows} == \
        {("sam1", "Sports Sam"), ("res1", "Careful Researcher")}



def test_the_event_carries_the_agent_with_a_sanitized_name(rig):
    tok = mcp_server.rotate_token("res1")
    _agents(rig, dict(SAM, name="Sam\u202e\x07 the\tGreat " + "x" * 80), dict(RES, name=tok))
    _call("get_status", agent="sam1")
    _call("get_status", agent="res1")
    evs = [d for n, d in rig["events"] if n == mcp_server.TOOLCALL_EVENT]
    assert evs[-2]["agentId"] == "sam1"
    name = evs[-2]["agentName"]
    assert name.startswith("Sam the Great") and len(name) <= 40
    assert not any(ord(c) < 32 or 0x202a <= ord(c) <= 0x202e for c in name)
    assert evs[-1]["agentName"] == "Agent" and tok not in json.dumps(evs)
    assert mcp_server.seen()["agents"][0]["agentId"] in ("sam1", "res1")



_OLD_SCHEMA = """
CREATE TABLE mcp_orders (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT,
  kalshi_env TEXT DEFAULT '', mode TEXT NOT NULL, client TEXT DEFAULT '',
  ticker TEXT NOT NULL, side TEXT NOT NULL, action TEXT NOT NULL, count INTEGER NOT NULL,
  price_cents REAL NOT NULL, forecast_id INTEGER, committed_usd REAL, ok INTEGER NOT NULL DEFAULT 0,
  order_id TEXT, filled INTEGER, avg_fill_cents REAL, message TEXT DEFAULT '');
CREATE TABLE paper_fills (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT,
  kalshi_env TEXT DEFAULT '', ticker TEXT NOT NULL, title TEXT DEFAULT '', side TEXT NOT NULL,
  kind TEXT NOT NULL, contracts INTEGER NOT NULL, price_cents REAL NOT NULL,
  fee_usd REAL NOT NULL DEFAULT 0, cash_delta_usd REAL NOT NULL, forecast_id INTEGER, client TEXT DEFAULT '');
CREATE TABLE ai_forecasts (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT DEFAULT (datetime('now')),
  kalshi_env TEXT DEFAULT '', ticker TEXT NOT NULL, title TEXT DEFAULT '', source TEXT NOT NULL,
  model TEXT DEFAULT '', prob_yes REAL NOT NULL, market_mid_cents REAL, yes_bid_cents REAL,
  yes_ask_cents REAL, close_time TEXT, rationale TEXT DEFAULT '', outcome REAL,
  resolved_at TEXT, last_checked_at TEXT);
INSERT INTO mcp_orders (created_at, mode, ticker, side, action, count, price_cents, ok, filled)
  VALUES ('2026-01-01T00:00:00', 'live', 'KXOLD', 'yes', 'buy', 7, 50, 1, 7);
INSERT INTO paper_fills (created_at, ticker, side, kind, contracts, price_cents, cash_delta_usd)
  VALUES ('2026-01-01T00:00:00', 'KXOLD', 'yes', 'buy', 4, 50, -2.1);
INSERT INTO ai_forecasts (ticker, source, prob_yes) VALUES ('KXOLD', 'mcp', 0.6);
INSERT INTO ai_forecasts (ticker, source, prob_yes) VALUES ('KXOLD', 'panel', 0.4);
"""


def test_migrations_are_idempotent_and_hand_old_rows_to_default(tmp_path, monkeypatch):
    monkeypatch.setenv("KRYPT_TRADER_USERDATA", str(tmp_path))
    conn = sqlite3.connect(str(db.db_path()))
    conn.executescript(_OLD_SCHEMA)
    conn.commit()
    conn.close()
    db.init_db()
    db.init_db()
    with db.get_db() as c:
        assert c.execute("SELECT agent_id FROM mcp_orders").fetchone()[0] == "default"
        assert c.execute("SELECT agent_id FROM paper_fills").fetchone()[0] == "default"
        rows = dict(c.execute("SELECT source, agent_id FROM ai_forecasts").fetchall())
    assert rows == {"mcp": "default", "panel": None}
    old_env = kalshi_auth.get_env()
    try:
        kalshi_auth.set_env("production")
        with db.get_db() as c:
            c.execute("UPDATE mcp_orders SET kalshi_env='production'")
        assert mcp_server._live_agent_net("KXOLD", "yes") == 7
        assert mcp_server._live_agent_net("KXOLD", "yes", "sam1") == 0
    finally:
        kalshi_auth.set_env(old_env)
    assert paper_book.held("KXOLD", "yes") == 4
    assert paper_book.held("KXOLD", "yes", "sam1") == 0



def _scope_checking_submit(rig):
    """What terminal.submit does with a scope: refuses it in any other."""
    async def _submit(req, scope=None):
        rig["sent"].append(dict(req, scope=scope, now=kalshi_auth.get_env()))
        if scope != kalshi_auth.get_env():
            return {"ok": False, "orderId": None, "status": None, "filledContracts": None,
                    "avgFillCents": None, "message": "Not sent: the app switched between "
                    "Paper and Live after this order was decided."}
        return {"ok": True, "orderId": f"ord-{len(rig['sent'])}", "message": "Placed.",
                "filledContracts": 5, "avgFillCents": 54.0, "status": "executed"}
    mcp_server.configure(submit=_submit)


def _flip_to_paper_during_reads(monkeypatch):
    real = mcp_server._market_row

    async def _row(ticker):
        kalshi_auth.set_env("paper")
        return await real(ticker)
    monkeypatch.setattr(mcp_server, "_market_row", _row)


def _last_order():
    with db.get_db() as conn:
        return dict(conn.execute("SELECT * FROM mcp_orders ORDER BY id DESC LIMIT 1").fetchone())


def test_an_approval_is_sent_only_in_the_scope_it_was_queued_in(rig, monkeypatch):
    rig["cfg"].update(mcp_trade_mode="live", mcp_live_approval=True)
    _agents(rig, dict(SAM, mode="live"))
    err, body = _buy("sam1")
    assert not err and body["pending"]
    _scope_checking_submit(rig)
    _flip_to_paper_during_reads(monkeypatch)
    out = run(mcp_server.decide(body["approvalId"], True))
    assert [s["scope"] for s in rig["sent"]] == ["production"]
    assert not out["ok"]
    row = _last_order()
    assert row["kalshi_env"] == "production" and row["ok"] == 0
    kalshi_auth.set_env("production")
    assert mcp_server._live_agent_net(SPORTS, "yes", "sam1") == 0


def test_a_direct_live_order_is_pinned_and_audited_in_its_own_scope(rig, monkeypatch):
    rig["cfg"].update(mcp_trade_mode="live", mcp_live_approval=False)
    _agents(rig, dict(SAM, mode="live"))
    fid = _fid("sam1")
    _scope_checking_submit(rig)
    _flip_to_paper_during_reads(monkeypatch)
    err, _ = _call("place_order", {"ticker": SPORTS, "side": "yes", "action": "buy",
                                   "count": 5, "price_cents": 54, "forecast_id": fid},
                   agent="sam1")
    assert err
    assert [s["scope"] for s in rig["sent"]] == ["production"]
    assert _last_order()["kalshi_env"] == "production"


def test_expired_approvals_spend_nothing(rig):
    rig["cfg"].update(mcp_trade_mode="live", mcp_live_approval=True, mcp_daily_spend_usd=10.0)
    _agents(rig, dict(SAM, mode="live"), dict(RES, mode="live"))
    ids = []
    for _ in range(3):
        err, body = _buy("sam1")
        assert not err and body["pending"], body
        ids.append(body["approvalId"])
    assert mcp_server.spent_today("live") > 8.0
    assert mcp_server._live_agent_exposure(SPORTS, "sam1") == 15
    with db.get_db() as conn:
        conn.execute("UPDATE mcp_orders SET created_at=datetime('now','-11 minutes') "
                     "WHERE id IN (%s)" % ",".join(map(str, ids)))
    assert all(_call("get_order_status", {"approval_id": i}, agent="sam1")[1]["status"]
               == "expired" for i in ids)
    assert mcp_server.spent_today("live") == 0.0
    assert mcp_server._live_agent_exposure(SPORTS, "sam1") == 0
    err, body = _buy("res1")
    assert not err and body["pending"], body


def test_the_loss_stop_counts_an_unmarked_paper_position_at_its_cost(rig, monkeypatch):
    import kalshi_api

    async def _unreadable(_tickers):
        raise RuntimeError("marks read failed")
    monkeypatch.setattr(kalshi_api, "fetch_markets_by_tickers", _unreadable)
    rig["cfg"].update(mcp_trade_mode="paper", mcp_max_order_usd=1000.0,
                      mcp_daily_spend_usd=1000.0, mcp_daily_loss_usd=50.0)
    err, body = _buy("sam1", count=100, price=54)
    assert not err, body
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for marks in ({}, {SPORTS: {"yesBid": None, "noBid": 99}}):
        d = paper_book.day_pnl(today, marks)
        assert d["unrealizedUsd"] == 0 and d["unmarked"] == [SPORTS]
        assert d["unmarkedCostUsd"] > 54.0
    dl = run(mcp_server.day_loss("paper"))
    assert dl["lossUsd"] > 54.0
    err, body = _buy("sam1", count=1)
    assert err and "Daily loss stop" in body
    err, body = _call("place_order", {"ticker": SPORTS, "side": "yes", "action": "sell",
                                      "count": 100, "price_cents": 40}, agent="sam1")
    assert not err, body


def test_an_unreadable_live_portfolio_stops_agent_buys(rig, monkeypatch):
    rig["cfg"].update(mcp_trade_mode="live", mcp_live_approval=False)
    _agents(rig, dict(SAM, mode="live"))
    assert not _buy("sam1")[0]

    async def _down(_authed):
        raise RuntimeError("portfolio read failed")
    monkeypatch.setattr(terminal, "portfolio", _down)
    dl = run(mcp_server.day_loss("live"))
    assert dl.get("positionsUnreadable") is True
    err, body = _buy("sam1")
    assert err and "could not be read" in body and len(rig["sent"]) == 1


def test_a_deleted_agents_paper_positions_free_the_cap_and_the_user_closes_them(rig, monkeypatch):
    import kalshi_api
    import service

    async def _no_marks(_tickers):
        return {}
    monkeypatch.setattr(kalshi_api, "fetch_markets_by_tickers", _no_marks)
    rig["cfg"].update(mcp_trade_mode="paper", mcp_max_positions=1)
    _agents(rig, dict(SAM, rules={}))
    assert not _buy("sam1", ticker=SPORTS)[0]
    held = paper_book.held(SPORTS, "yes", "sam1")
    assert held > 0
    err, body = _buy("res1", ticker=CRYPTO)
    assert err and "positions" in body
    rig["cfg"]["mcp_agents"] = [a for a in rig["cfg"]["mcp_agents"] if a["id"] != "sam1"]
    err, _ = _call("place_order", {"ticker": SPORTS, "side": "yes", "action": "sell",
                                   "count": 1, "price_cents": 40}, agent="sam1")
    assert err
    err, body = _buy("res1", ticker=CRYPTO)
    assert not err, body
    assert "mcp_agent_close_paper" in service._HANDLERS
    out = run(service._HANDLERS["mcp_agent_close_paper"]({"agentId": "sam1"}))
    assert out["ok"] and out["closed"][0]["contracts"] == held
    assert out["closed"][0]["avgPriceCents"] == 50.0
    assert paper_book.held(SPORTS, "yes", "sam1") == 0
    assert paper_book.held(CRYPTO, "yes", "res1") > 0
    assert not run(mcp_server.close_agent_paper("../etc"))["ok"]
    assert not any("close" in n and "paper" in n for n in mcp_server._BY_NAME)
    assert "mcp_agent_close_paper" not in service._MCP_RPC_ALLOWED


def test_a_settings_reset_never_prunes_the_agents_tokens(rig, monkeypatch):
    import service

    async def _noop(*_a, **_k):
        return None
    monkeypatch.setattr(service, "emit_event", _noop)
    monkeypatch.setattr(service, "_sync_remote_bots", _noop)
    monkeypatch.setattr(service, "_sync_mcp", _noop)
    monkeypatch.setattr(service.STATE, "cfg", dict(service.STATE.cfg), raising=False)
    mcp_server.rotate_token("sam1")
    base = {"accountMode": "live"}
    default_only = [{"id": "default", "name": "Default"}]
    try:
        service._MAIN_AGENT_IDS[0] = {"default", "sam1", "res1"}
        run(service._h_setConfig({"config": dict(base, mcpAgents=default_only)}))
        assert kalshi_auth.has_secret("mcp_token_sam1")
        run(service._h_setConfig({"config": dict(base, mcpAgents=default_only + [dict(SAM)])}))
        assert kalshi_auth.has_secret("mcp_token_sam1")
        run(service._h_setConfig({"config": dict(base, mcpAgents=default_only),
                                  "pruneAgentTokens": True}))
        assert not kalshi_auth.has_secret("mcp_token_sam1")
    finally:
        service._MAIN_AGENT_IDS[0] = None


def test_a_model_label_belongs_to_the_agent_not_the_client(rig):
    rig["cfg"].update(mcp_trade_mode="paper")
    err, _ = _call("record_forecast", {"ticker": SPORTS, "fair_value_cents": 60,
                                       "rationale": "Injury report and the rules text agree.",
                                       "model": "gpt-5"}, agent="sam1", client="cursor 1.0")
    assert not err
    err, body = _call("record_forecast", {"ticker": CRYPTO, "fair_value_cents": 60,
                                          "rationale": "ETF flows and the strike distance now."},
                      agent="res1", client="cursor 1.0")
    assert not err
    assert forecast_ledger.get(body["forecastId"])["model"] != "gpt-5"
    err, body = _call("record_forecast", {"ticker": CRYPTO, "fair_value_cents": 55,
                                          "rationale": "Same read, a little less confident."},
                      agent="sam1", client="cursor 1.0")
    assert forecast_ledger.get(body["forecastId"])["model"] == "gpt-5"


def test_another_agents_forecast_id_reveals_nothing(rig):
    rig["cfg"].update(mcp_trade_mode="paper")
    fid = _fid("sam1", SPORTS)
    err, body = _call("preview_order", {"ticker": CRYPTO, "side": "yes", "action": "buy",
                                        "count": 1, "price_cents": 54, "forecast_id": fid},
                      agent="res1")
    text = json.dumps(body)
    assert SPORTS not in text and "Sports Sam" not in text
    missing = _call("preview_order", {"ticker": CRYPTO, "side": "yes", "action": "buy",
                                      "count": 1, "price_cents": 54, "forecast_id": 999999},
                    agent="res1")[1]
    assert body["blockers"][0] == missing["blockers"][0]


def test_one_busy_agent_does_not_rate_limit_another(rig):
    import time
    now = time.monotonic()
    mcp_server._agent_hits["sam1"] = [now] * mcp_server.RATE_MAX
    err, body = _call("get_status", agent="sam1")
    assert err and body.startswith("Rate limit:")
    err, body = _call("get_status", agent="res1")
    assert not err, body
