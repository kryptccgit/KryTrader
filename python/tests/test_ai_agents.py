"""AI agents over MCP, the paper book, and the forecast scoreboard.

The MCP server is the second surface (after remote control) where something
other than a hand at this desk can spend money. Most of what is pinned here is
what it REFUSES: a buy with no forecast, a forecast with no edge after fees, an
order over the agent's caps, a sell of the user's own position, a request from
a host or origin that is not this machine. And the scoreboard must refuse to
crown a winner on a sample that cannot support it.
"""
from __future__ import annotations

import asyncio
import io
import json
import socket
import sys
from datetime import datetime, timedelta, timezone

import pytest

import db
import forecast_ledger
import kalshi_auth
import mcp_bridge
import mcp_server
import paper_book
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
    "yes": [{"priceCents": 50.0, "contracts": 30}, {"priceCents": 48.0, "contracts": 100}],
    "no": [{"priceCents": 46.0, "contracts": 20}, {"priceCents": 44.0, "contracts": 100}],
    "yesBid": 50.0, "yesAsk": 54.0, "stale": False, "source": "kalshi-ws",
}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    db.init_db()
    with db.get_db() as conn:
        for t in ("ai_forecasts", "paper_fills", "paper_state", "mcp_orders"):
            conn.execute(f"DELETE FROM {t}")
    mcp_server._hits.clear()
    cfg = {"account_mode": "live", "mcp_enabled": True, "mcp_trade_mode": "paper"}
    state = {"cfg": cfg, "authed": False}
    mcp_server.configure(
        get_cfg=lambda: merge_with_defaults(dict(state["cfg"])),
        is_authed=lambda: state["authed"], submit=None, cancel=None,
        emit=None, notify_phone=None, version="test")

    async def _row(ticker):
        return dict(MARKET, ticker=ticker) if ticker == TICKER else None

    async def _book(ticker):
        return dict(BOOK)

    monkeypatch.setattr(mcp_server, "_market_row", _row)
    monkeypatch.setattr(terminal, "book", _book)
    yield state


def _call(name, args=None, ctx=None):
    res = run(mcp_server.call_tool(name, args or {}, ctx or {"client": "pytest"}))
    text = res["content"][0]["text"]
    try:
        body = json.loads(text)
    except ValueError:
        body = text
    return res["isError"], body


def _forecast(fv=70, ticker=TICKER):
    err, body = _call("record_forecast", {
        "ticker": ticker, "fair_value_cents": fv,
        "rationale": "Base rates and the rules text both point this way."})
    assert not err, body
    return body["forecastId"]


def _audit_rows():
    with db.get_db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM mcp_orders ORDER BY id")]



def test_initialize_negotiates_a_version_and_names_the_rules():
    ctx = {}
    res = run(mcp_server.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18",
                   "clientInfo": {"name": "cursor", "version": "1.7"}}}, ctx))
    assert res["result"]["protocolVersion"] == "2025-06-18"
    assert "not zero" in res["result"]["instructions"].lower() or \
        "never zero" in res["result"]["instructions"].lower()
    assert ctx["client"] == "cursor 1.7"
    res = run(mcp_server.handle_message({
        "jsonrpc": "2.0", "id": 2, "method": "initialize",
        "params": {"protocolVersion": "1999-01-01"}}, {}))
    assert res["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSIONS[0]


def test_an_unknown_method_is_a_clean_rpc_error():
    """Claude Code's v2 client probes with `server/discover` (2026-07-28) and
    falls back to `initialize` only if the probe gets a completed, non-auth,
    non-5xx answer. A JSON-RPC 'method not found' is that answer."""
    res = run(mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 9, "method": "server/discover"}, {}))
    assert res["error"]["code"] == -32601


def test_notifications_get_no_reply():
    assert run(mcp_server.handle_message(
        {"jsonrpc": "2.0", "method": "notifications/initialized"}, {})) is None


def test_trade_tools_are_hidden_and_refused_when_trading_is_off(_clean):
    _clean["cfg"]["mcp_trade_mode"] = "off"
    res = run(mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, {}))
    names = {t["name"] for t in res["result"]["tools"]}
    assert "place_order" not in names and "get_portfolio" not in names
    assert {"get_market", "record_forecast", "get_scoreboard"} <= names
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes",
                                      "action": "buy", "count": 1, "price_cents": 54})
    assert err and "disabled" in body


def test_place_order_is_marked_destructive_for_the_client():
    spec = next(t.spec() for t in mcp_server.TOOLS if t.name == "place_order")
    assert spec["annotations"]["destructiveHint"] is True
    assert spec["annotations"]["readOnlyHint"] is False



def test_a_buy_without_a_forecast_is_refused_and_audited():
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes",
                                      "action": "buy", "count": 5, "price_cents": 54})
    assert err and "forecast_id" in body
    rows = _audit_rows()
    assert len(rows) == 1 and rows[0]["ok"] == 0


def test_a_forecast_without_edge_after_fees_cannot_buy():
    fid = _forecast(57)
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "buy",
                                      "count": 10, "price_cents": 54, "forecast_id": fid})
    assert err and "No trade" in body
    assert paper_book.open_tickers() == []


def test_edge_is_computed_for_the_side_being_bought():
    assert mcp_server.edge_cents(30, "no", 50, 10) > 15
    assert mcp_server.edge_cents(30, "yes", 54, 10) < 0


def test_a_forecast_for_another_market_cannot_back_a_buy(monkeypatch):
    other = "KXOTHER-1"
    fid = forecast_ledger.record(ticker=other, prob_yes=0.9, source="mcp", market=MARKET)
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "buy",
                                      "count": 1, "price_cents": 54, "forecast_id": fid})
    assert err and other in body


def test_a_panel_forecast_cannot_back_an_agent_order():
    fid = forecast_ledger.record(ticker=TICKER, prob_yes=0.9, source="panel", market=MARKET)
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "buy",
                                      "count": 1, "price_cents": 54, "forecast_id": fid})
    assert err and "through this server" in body


def test_a_stale_forecast_cannot_back_a_buy():
    fid = _forecast(80)
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    with db.get_db() as conn:
        conn.execute("UPDATE ai_forecasts SET created_at=? WHERE id=?", (old, fid))
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "buy",
                                      "count": 1, "price_cents": 54, "forecast_id": fid})
    assert err and "older than" in body


def test_forecasts_reject_certainty_and_need_a_reason():
    err, body = _call("record_forecast", {"ticker": TICKER, "fair_value_cents": 100,
                                          "rationale": "x" * 40})
    assert err
    err, body = _call("record_forecast", {"ticker": TICKER, "fair_value_cents": 60,
                                          "rationale": "yes"})
    assert err and "rationale" in body


def test_record_forecast_reports_an_absent_side_as_null(monkeypatch):
    async def _row(ticker):
        return dict(MARKET, yesAsk=None, noBid=None, midCents=None)
    monkeypatch.setattr(mcp_server, "_market_row", _row)
    fid = _forecast(60)
    row = forecast_ledger.get(fid)
    assert row["market_mid_cents"] is None
    err, body = _call("record_forecast", {"ticker": TICKER, "fair_value_cents": 60,
                                          "rationale": "Same again, the book is one-sided."})
    assert body["buyYes"] is None



def test_paper_buy_walks_the_real_book_up_to_the_limit():
    fid = _forecast(80)
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "buy",
                                      "count": 25, "price_cents": 56, "forecast_id": fid})
    assert not err, body
    assert body["filled"] == 25
    assert body["avgFillCents"] == pytest.approx((20 * 54 + 5 * 56) / 25, abs=0.01)
    assert paper_book.held(TICKER, "yes") == 25


def test_a_paper_limit_that_crosses_nothing_does_not_rest():
    fill = paper_book.simulate_fill(BOOK, "yes", "buy", 10, 53)
    assert fill["filled"] == 0 and "do not rest" in fill["note"]


def test_paper_sell_hits_bids_and_cannot_sell_what_it_does_not_hold():
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "sell",
                                      "count": 5, "price_cents": 49})
    assert err and "holds 0" in body
    fill = paper_book.simulate_fill(BOOK, "yes", "sell", 40, 48)
    assert fill["filled"] == 40
    assert fill["avgPriceCents"] == pytest.approx((30 * 50 + 10 * 48) / 40, abs=0.01)


def test_paper_accounting_settles_at_the_real_outcome(monkeypatch):
    paper_book.record_fill(ticker=TICKER, title="t", side="yes", action="buy",
                           contracts=10, price_cents=54, fee_usd=0.18,
                           forecast_id=None, client="", env="paper")
    pf = paper_book.portfolio(1000.0)
    assert pf["cashUsd"] == pytest.approx(1000 - 5.40 - 0.18)
    assert pf["positions"][0]["unrealizedUsd"] is None

    async def _outcomes(tickers):
        return {TICKER: 1.0}
    monkeypatch.setattr(forecast_ledger, "fetch_outcomes", _outcomes)
    assert run(paper_book.settle_pending()) == 1
    pf = paper_book.portfolio(1000.0)
    assert pf["positions"] == []
    assert pf["realizedUsd"] == pytest.approx(10 - 5.58, abs=0.01)
    assert pf["cashUsd"] == pytest.approx(1000 - 5.58 + 10, abs=0.01)
    assert run(paper_book.settle_pending()) == 0



def test_the_agent_per_order_cap_binds(_clean):
    _clean["cfg"]["mcp_max_order_usd"] = 5.0
    fid = _forecast(80)
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "buy",
                                      "count": 20, "price_cents": 54, "forecast_id": fid})
    assert err and "per-order cap" in body


def test_the_daily_spend_cap_counts_earlier_fills(_clean):
    _clean["cfg"]["mcp_daily_spend_usd"] = 12.0
    fid = _forecast(80)
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "buy",
                                      "count": 20, "price_cents": 54, "forecast_id": fid})
    assert not err, body
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "buy",
                                      "count": 2, "price_cents": 56, "forecast_id": fid})
    assert err and "daily cap" in body


def test_unknown_trade_mode_falls_to_off_not_paper():
    cfg = merge_with_defaults({"mcp_trade_mode": "LIVEE"})
    assert cfg["mcp_trade_mode"] == "off"
    assert merge_with_defaults({})["mcp_enabled"] is False
    assert merge_with_defaults({"mcp_port": 80})["mcp_port"] == 1024



def test_live_orders_take_the_desktop_submit_path(_clean):
    _clean["cfg"]["mcp_trade_mode"] = "live"
    _clean["cfg"]["mcp_live_approval"] = False
    _clean["authed"] = True
    sent = []

    async def _submit(req, scope=None):
        sent.append(req)
        return {"ok": True, "orderId": "ord-1", "message": "Filled 3.",
                "filledContracts": 3, "avgFillCents": 54.0, "status": "executed"}
    mcp_server.configure(submit=_submit)

    async def _pf(authed):
        return {"positions": []}
    import pytest as _pt
    mp = _pt.MonkeyPatch()
    mp.setattr(terminal, "portfolio", _pf)
    try:
        fid = _forecast(80)
        err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "buy",
                                          "count": 3, "price_cents": 54, "forecast_id": fid})
    finally:
        mp.undo()
    assert not err, body
    assert sent == [{"ticker": TICKER, "side": "yes", "action": "buy",
                     "count": 3, "priceCents": 54.0}]
    assert _audit_rows()[-1]["order_id"] == "ord-1"


def test_live_agent_cannot_sell_the_users_own_position(_clean):
    _clean["cfg"]["mcp_trade_mode"] = "live"
    _clean["authed"] = True
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "sell",
                                      "count": 5, "price_cents": 50})
    assert err and "only sell what it opened" in body


def test_live_agent_cannot_cancel_the_users_orders(_clean):
    _clean["cfg"]["mcp_trade_mode"] = "live"
    err, body = _call("cancel_order", {"order_id": "someone-elses"})
    assert err and "user's" in body



def _h(**kw):
    base = {"host": "127.0.0.1:47821", "authorization": "Bearer tok"}
    base.update(kw)
    return {k: v for k, v in base.items() if v is not None}


def test_request_checks_refuse_everything_that_is_not_a_local_client():
    chk = mcp_server.check_request
    assert chk("POST", "/mcp", _h(), 47821, "tok") is None
    assert chk("POST", "/other", _h(), 47821, "tok")[0] == 404
    assert chk("POST", "/mcp", _h(host="evil.example:47821"), 47821, "tok")[0] == 403
    assert chk("POST", "/mcp", _h(origin="https://evil.example"), 47821, "tok")[0] == 403
    assert chk("POST", "/mcp", _h(authorization=None), 47821, "tok")[0] == 401
    assert chk("POST", "/mcp", _h(authorization="Bearer nope"), 47821, "tok")[0] == 401
    assert chk("POST", "/mcp", _h(), 47821, None)[0] == 401
    assert chk("GET", "/mcp", _h(), 47821, "tok")[0] == 405


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_http_round_trip_and_stdio_bridge(monkeypatch):
    """The real listener, then the real bridge against it."""
    port = _free_port()
    token = mcp_server.rotate_token()

    async def _post(body, sid=None):
        r, w = await asyncio.open_connection("127.0.0.1", port)
        data = json.dumps(body).encode()
        head = (f"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                f"Authorization: Bearer {token}\r\nContent-Type: application/json\r\n"
                f"Content-Length: {len(data)}\r\nConnection: close\r\n")
        if sid:
            head += f"Mcp-Session-Id: {sid}\r\n"
        w.write((head + "\r\n").encode() + data)
        await w.drain()
        raw = await r.read()
        w.close()
        hdr, _, payload = raw.partition(b"\r\n\r\n")
        return hdr.decode(), payload

    def _bridge(lines):
        stdin = type("S", (), {"buffer": io.BytesIO("".join(lines).encode())})()
        out = io.BytesIO()
        stdout = type("S", (), {"buffer": out})()
        monkeypatch.setattr(sys, "stdin", stdin)
        monkeypatch.setattr(sys, "stdout", stdout)
        monkeypatch.setenv("KRYPT_MCP_TOKEN", token)
        rc = mcp_bridge.main(["--port", str(port)])
        return rc, [json.loads(x) for x in out.getvalue().decode().splitlines()]

    async def _go():
        await mcp_server.start(port)
        try:
            hdr, body = await _post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                     "params": {"protocolVersion": "2025-06-18",
                                                "clientInfo": {"name": "pytest"}}})
            assert " 200 " in hdr.splitlines()[0]
            sid = next(l.split(":", 1)[1].strip() for l in hdr.splitlines()
                       if l.lower().startswith("mcp-session-id"))
            assert json.loads(body)["result"]["serverInfo"]["name"] == "krypt-trader"
            hdr, body = await _post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
            assert " 202 " in hdr.splitlines()[0]
            hdr, body = await _post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
            assert any(t["name"] == "place_order" for t in json.loads(body)["result"]["tools"])

            rc, replies = await asyncio.to_thread(_bridge, [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": "2025-06-18"}}) + "\n",
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n",
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                            "params": {"name": "get_status", "arguments": {}}}) + "\n",
            ])
            assert rc == 0
            assert [r["id"] for r in replies] == [1, 2]
            status = json.loads(replies[1]["result"]["content"][0]["text"])
            assert status["tradeMode"] == "paper"
        finally:
            await mcp_server.stop()

    run(_go())


def test_bridge_explains_a_closed_app_instead_of_hanging(monkeypatch):
    port = _free_port()
    stdin = type("S", (), {"buffer": io.BytesIO(
        (json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}) + "\n").encode())})()
    out = io.BytesIO()
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", type("S", (), {"buffer": out})())
    monkeypatch.setenv("KRYPT_MCP_TOKEN", "x")
    assert mcp_bridge.main(["--port", str(port)]) == 0
    reply = json.loads(out.getvalue())
    assert reply["id"] == 7 and "not running" in reply["error"]["message"]


def test_client_configs_carry_the_token_and_parse():
    tok = "kt_abc"
    cur = json.loads(mcp_server.client_config("cursor", 47821, tok))
    srv = cur["mcpServers"]["krypt-trader"]
    assert srv["url"].endswith(":47821/mcp") and tok in srv["headers"]["Authorization"]
    desk = json.loads(mcp_server.client_config("claude-desktop", 47821, tok))
    assert "--mcp-stdio" in desk["mcpServers"]["krypt-trader"]["args"]
    assert desk["mcpServers"]["krypt-trader"]["env"]["KRYPT_MCP_TOKEN"] == tok
    toml = mcp_server.client_config("codex", 47821, tok)
    import tomllib
    codex = tomllib.loads(toml)["mcp_servers"]["krypt-trader"]
    assert codex["http_headers"]["Authorization"] == f"Bearer {tok}"
    assert codex["url"].endswith(":47821/mcp")
    cc = mcp_server.client_config("claude-code", 47821, tok)
    assert "--scope user" in cc
    assert cc.index("--header") > cc.index("/mcp")


def test_the_token_is_registered_with_the_log_scrubber():
    import logscrub
    tok = mcp_server.rotate_token()
    assert tok not in logscrub.scrub(f"Authorization: header {tok} leaked")
    assert kalshi_auth.has_secret(mcp_server.TOKEN_SECRET)



def _resolved(ticker, p, mid, outcome, source="mcp"):
    fid = forecast_ledger.record(ticker=ticker, prob_yes=p, source=source,
                                 market={"midCents": mid})
    with db.get_db() as conn:
        conn.execute("UPDATE ai_forecasts SET outcome=? WHERE id=?", (outcome, fid))
    return fid


def test_scoreboard_will_not_crown_a_winner_on_a_small_sample():
    for i in range(10):
        _resolved(f"T{i}", 0.9, 50, 1.0)
    sb = forecast_ledger.scoreboard()
    assert sb["overall"]["skill"] > 0
    assert sb["overall"]["verdict"] == "too-few"


def test_scoreboard_verdicts_follow_the_paired_difference():
    for i in range(40):
        o = 1.0 if i % 2 else 0.0
        _resolved(f"A{i}", 0.8 if o else 0.2, 50, o)
    assert forecast_ledger.scoreboard()["overall"]["verdict"] == "ai-better"
    with db.get_db() as conn:
        conn.execute("DELETE FROM ai_forecasts")
    for i in range(40):
        o = 1.0 if i % 2 else 0.0
        _resolved(f"B{i}", 0.5, 90 if o else 10, o)
    assert forecast_ledger.scoreboard()["overall"]["verdict"] == "market-better"


def test_no_mid_means_no_head_to_head_not_a_50c_market():
    _resolved("NOQ", 0.7, None, 1.0)
    s = forecast_ledger.scoreboard()["overall"]
    assert s["n"] == 1 and s["nPaired"] == 0
    assert s["brierMarket"] is None and s["brierAi"] == pytest.approx(0.09)


def test_repeated_forecasts_on_one_market_count_once():
    for p in (0.6, 0.7, 0.8):
        _resolved("SAME", p, 50, 1.0)
    sb = forecast_ledger.scoreboard()
    assert sb["totalForecasts"] == 3 and sb["scoredMarkets"] == 1
    assert sb["overall"]["brierAi"] == pytest.approx(0.04)


def test_resolver_only_scores_settled_markets(monkeypatch):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    a = forecast_ledger.record(ticker="DONE", prob_yes=0.7, source="panel",
                               market={"closeTime": past, "midCents": 60})
    b = forecast_ledger.record(ticker="WAIT", prob_yes=0.7, source="panel",
                               market={"closeTime": past, "midCents": 60})

    async def _outcomes(tickers):
        return {"DONE": 0.0, "WAIT": None}
    monkeypatch.setattr(forecast_ledger, "fetch_outcomes", _outcomes)
    assert run(forecast_ledger.resolve_pending()) == 1
    assert forecast_ledger.get(a)["outcome"] == 0.0
    assert forecast_ledger.get(b)["outcome"] is None



def test_panel_analysis_passes_auth_and_records_its_forecast(monkeypatch):
    import ai_analyst
    import service
    seen = {}

    async def _detail(ticker, *, authed):
        seen["authed"] = authed
        return {"market": dict(MARKET)}

    def _analyze(detail, cfg):
        return {"ticker": TICKER, "model": "claude-opus-5", "fairValueCents": 61,
                "summary": "s", "verdict": "cheap"}
    monkeypatch.setattr(terminal, "market_detail", _detail)
    monkeypatch.setattr(ai_analyst, "analyze", _analyze)
    res = run(service._h_ai_analyze({"ticker": TICKER}))
    assert res["ok"] and "authed" in seen
    row = forecast_ledger.get(res["analysis"]["forecastId"])
    assert row["source"] == "panel" and row["prob_yes"] == pytest.approx(0.61)
    assert row["market_mid_cents"] == 52.0


def test_a_declined_fair_value_is_not_recorded(monkeypatch):
    import ai_analyst
    import service

    async def _detail(ticker, *, authed):
        return {"market": dict(MARKET)}
    monkeypatch.setattr(terminal, "market_detail", _detail)
    monkeypatch.setattr(ai_analyst, "analyze",
                        lambda d, c: {"model": "m", "fairValueCents": None})
    res = run(service._h_ai_analyze({"ticker": TICKER}))
    assert res["ok"] and "forecastId" not in res["analysis"]
    assert forecast_ledger.scoreboard()["totalForecasts"] == 0



@pytest.fixture
def live(_clean, monkeypatch):
    _clean["cfg"]["mcp_trade_mode"] = "live"
    _clean["authed"] = True
    sent = []

    async def _submit(req, scope=None):
        sent.append(req)
        return {"ok": True, "orderId": f"ord-{len(sent)}", "message": "Placed.",
                "filledContracts": 0, "avgFillCents": None, "status": "resting"}

    async def _pf(authed):
        return {"positions": []}

    def _hist(limit=300):
        return {"trades": []}
    mcp_server.configure(submit=_submit)
    monkeypatch.setattr(terminal, "portfolio", _pf)
    monkeypatch.setattr(terminal, "manual_history", _hist)
    return sent


def _queue(fv=80, count=3):
    fid = _forecast(fv)
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "buy",
                                      "count": count, "price_cents": 54, "forecast_id": fid})
    assert not err, body
    return body


def test_live_orders_wait_for_approval_by_default(live):
    body = _queue()
    assert body["pending"] and not live
    assert mcp_server.spent_today("live") == pytest.approx(1.68, abs=0.01)
    assert [p["id"] for p in mcp_server.pending()] == [body["approvalId"]]


def test_approving_re_vets_then_sends_once(live):
    body = _queue()
    res = run(mcp_server.decide(body["approvalId"], True))
    assert res["ok"], res
    assert len(live) == 1
    err, st = _call("get_order_status", {"approval_id": body["approvalId"]})
    assert st["status"] == "approved" and st["orderId"] == "ord-1"
    assert not run(mcp_server.decide(body["approvalId"], True))["ok"]
    assert len(live) == 1


def test_rejecting_sends_nothing_and_frees_the_spend(live):
    body = _queue()
    assert run(mcp_server.decide(body["approvalId"], False))["ok"]
    assert live == [] and mcp_server.spent_today("live") == 0


def test_an_expired_approval_sends_nothing(live):
    body = _queue()
    old = (datetime.now(timezone.utc) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
    with db.get_db() as conn:
        conn.execute("UPDATE mcp_orders SET created_at=? WHERE id=?", (old, body["approvalId"]))
    assert mcp_server.pending() == []
    res = run(mcp_server.decide(body["approvalId"], True))
    assert not res["ok"] and "expired" in res["message"] and live == []


def test_approval_is_refused_if_the_world_changed(live, _clean):
    body = _queue()
    _clean["cfg"]["mcp_trade_mode"] = "paper"
    res = run(mcp_server.decide(body["approvalId"], True))
    assert not res["ok"] and live == []


def test_approval_cannot_be_disabled_by_a_mangled_config():
    assert merge_with_defaults({"mcp_live_approval": "no"})["mcp_live_approval"] is True
    assert merge_with_defaults({"mcp_live_approval": False})["mcp_live_approval"] is False



def test_the_daily_loss_stop_halts_buys_but_not_exits(_clean, monkeypatch):
    _clean["cfg"]["mcp_daily_loss_usd"] = 5.0
    paper_book.record_fill(ticker=TICKER, title="t", side="yes", action="buy",
                           contracts=20, price_cents=54, fee_usd=0.35,
                           forecast_id=None, client="", env="paper")

    async def _found(tickers):
        return {TICKER: {"ticker": TICKER, "yes_bid_dollars": "0.20",
                         "yes_ask_dollars": "0.22"}}
    import kalshi_api
    monkeypatch.setattr(kalshi_api, "fetch_markets_by_tickers", _found)
    fid = _forecast(80)
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "buy",
                                      "count": 1, "price_cents": 54, "forecast_id": fid})
    assert err and "Daily loss stop" in body
    err, body = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "sell",
                                      "count": 5, "price_cents": 49})
    assert not err, body


def test_unrealised_gains_do_not_pay_for_realised_losses():
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    paper_book.record_fill(ticker="A", title="", side="yes", action="buy", contracts=10,
                           price_cents=50, fee_usd=0, forecast_id=None, client="", env="")
    paper_book.record_fill(ticker="A", title="", side="yes", action="sell", contracts=10,
                           price_cents=20, fee_usd=0, forecast_id=None, client="", env="")
    paper_book.record_fill(ticker="B", title="", side="yes", action="buy", contracts=10,
                           price_cents=10, fee_usd=0, forecast_id=None, client="", env="")
    d = paper_book.day_pnl(day, {"B": {"yesBid": 90.0}})
    assert d["realizedUsd"] == pytest.approx(-3.0)
    assert d["unrealizedUsd"] == pytest.approx(8.0)
    loss = max(0.0, -(d["realizedUsd"] + min(0.0, d["unrealizedUsd"])))
    assert loss == pytest.approx(3.0)



def test_phone_approval_needs_the_remote_trading_switch(live):
    import remote
    body = _queue()
    reply = run(remote.handle(f"approve {body['approvalId']}", "discord:1", cfg={},
                              authed=True, trading_enabled=False))
    assert "OFF" in reply and live == []
    listing = run(remote.handle("agents", "discord:1", cfg={}, authed=True,
                                trading_enabled=False))
    assert f"#{body['approvalId']}" in listing


def test_phone_approval_sends_through_the_same_re_vet(live):
    import remote
    body = _queue()
    reply = run(remote.handle(f"approve #{body['approvalId']}", "discord:1", cfg={},
                              authed=True, trading_enabled=True))
    assert "Approved" in reply and len(live) == 1
