"""The plain HTTP API (/api/v1) beside the MCP endpoint.

It is a second door onto the same agent, so almost everything pinned here is
PARITY: the same Host/Origin/token refusal as /mcp, and — the one that matters
— the same refusal, word for word, for an order the MCP path would refuse.
The API has no rails of its own; if a test here ever needs one, the two doors
have drifted.

Requests go over a real socket to the real listener, with Kalshi stubbed.
"""
from __future__ import annotations

import asyncio
import json
import re
import socket

import pytest

import db
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
UA = "pytest-bot/1.0"
BUY = {"ticker": TICKER, "side": "yes", "action": "buy", "count": 5, "price_cents": 54}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture(autouse=True)
def env(monkeypatch):
    db.init_db()
    with db.get_db() as conn:
        for t in ("ai_forecasts", "paper_fills", "paper_state", "mcp_orders"):
            conn.execute(f"DELETE FROM {t}")
    mcp_server._hits.clear()
    mcp_server.STATUS.seen.clear()
    state = {"cfg": {"account_mode": "live", "mcp_enabled": True, "mcp_http_enabled": True,
                     "mcp_trade_mode": "paper"},
             "authed": False, "sent": []}
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
    state["port"] = _free_port()
    state["token"] = mcp_server.rotate_token()
    yield state


def http(env, method, path, body=None, *, token=..., host=None, origin=None,
         ua=UA, raw_body=None):
    """One request against a freshly started listener. Returns (status,
    headers-text, parsed JSON or None)."""
    port = env["port"]
    tok = env["token"] if token is ... else token

    async def _go():
        await mcp_server.start(port)
        try:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            data = raw_body if raw_body is not None else (
                json.dumps(body).encode() if body is not None else b"")
            head = f"{method} {path} HTTP/1.1\r\nHost: {host or f'127.0.0.1:{port}'}\r\n"
            if tok:
                head += f"Authorization: Bearer {tok}\r\n"
            if origin:
                head += f"Origin: {origin}\r\n"
            if ua:
                head += f"User-Agent: {ua}\r\n"
            head += f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n"
            w.write(head.encode() + data)
            await w.drain()
            raw = await r.read()
            w.close()
            return raw
        finally:
            await mcp_server.stop()

    raw = asyncio.run(_go())
    hdr, _, payload = raw.partition(b"\r\n\r\n")
    status = int(hdr.split(b" ", 2)[1])
    try:
        parsed = json.loads(payload) if payload else None
    except ValueError:
        parsed = None
    return status, hdr.decode("latin-1"), parsed


def mcp_text(name, args, client="mcp-client"):
    res = asyncio.run(mcp_server.call_tool(name, args, {"client": client}))
    return res["isError"], res["content"][0]["text"]


def tool(env, name, args=None, **kw):
    return http(env, "POST", f"/api/v1/tools/{name}", args if args is not None else {}, **kw)


def forecast(env, fv=80):
    st, _, body = tool(env, "record_forecast", {
        "ticker": TICKER, "fair_value_cents": fv,
        "rationale": "Base rates and the rules text both point this way."})
    assert st == 200, body
    return body["result"]["forecastId"]


def audit_rows():
    with db.get_db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM mcp_orders ORDER BY id")]



def test_missing_or_wrong_token_is_401(env):
    for path, method in (("/api/v1/tools", "GET"), ("/api/v1/openapi.json", "GET"),
                         ("/api/v1/tools/get_status", "POST")):
        st, hdr, body = http(env, method, path, {} if method == "POST" else None, token=None)
        assert st == 401 and "WWW-Authenticate: Bearer" in hdr, path
        st, _, _ = http(env, method, path, {} if method == "POST" else None, token="kt_wrong")
        assert st == 401, path


def test_foreign_host_and_origin_are_refused(env):
    st, _, body = http(env, "GET", "/api/v1/tools", host="evil.example")
    assert st == 403 and "host" in body["error"]
    st, _, body = http(env, "GET", "/api/v1/tools", origin="https://evil.example")
    assert st == 403 and "origin" in body["error"]
    hdrs = {"host": "evil.example", "authorization": f"Bearer {env['token']}"}
    assert mcp_server.check_request("GET", "/api/v1/tools", hdrs, env["port"], env["token"])[0] == 403
    assert mcp_server.check_request("POST", "/mcp", hdrs, env["port"], env["token"])[0] == 403


def test_the_api_has_its_own_switch_and_it_is_off_by_default(env):
    assert merge_with_defaults({})["mcp_http_enabled"] is False
    assert merge_with_defaults({"mcp_http_enabled": "true"})["mcp_http_enabled"] is False
    env["cfg"]["mcp_http_enabled"] = False
    st, _, body = http(env, "GET", "/api/v1/tools")
    assert st == 403 and "switched off" in body["error"]
    st, _, body = tool(env, "get_status")
    assert st == 403
    assert mcp_server.check_request("POST", "/mcp", {
        "host": f"127.0.0.1:{env['port']}", "authorization": f"Bearer {env['token']}"},
        env["port"], env["token"]) is None


def test_methods_and_bodies_are_checked(env):
    st, hdr, _ = http(env, "GET", "/api/v1/tools/get_status")
    assert st == 405 and "Allow: POST" in hdr
    st, hdr, _ = http(env, "POST", "/api/v1/tools", {})
    assert st == 405 and "Allow: GET" in hdr
    st, _, body = http(env, "POST", "/api/v1/tools/get_status", raw_body=b"{not json")
    assert st == 400 and "JSON object" in body["error"]
    st, _, body = http(env, "POST", "/api/v1/tools/get_status", raw_body=b"[1,2]")
    assert st == 400
    st, _, _ = http(env, "GET", "/api/v1/nowhere")
    assert st == 404



def test_tools_lists_exactly_what_mcp_lists(env):
    st, _, body = http(env, "GET", "/api/v1/tools")
    assert st == 200
    mcp = asyncio.run(mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, {}))["result"]["tools"]
    assert body["tools"] == json.loads(json.dumps(mcp))
    assert body["tradeMode"] == "paper"


def test_unknown_tool_is_404(env):
    st, _, body = tool(env, "no_such_tool")
    assert st == 404 and "Unknown or disabled tool" in body["error"]
    st, _, body = tool(env, "Bad-Name!")
    assert st == 404


def test_openapi_is_generated_from_the_tool_schemas(env):
    st, _, spec = http(env, "GET", "/api/v1/openapi.json")
    assert st == 200
    assert spec["openapi"].startswith("3.1")
    assert spec["servers"] == [{"url": f"http://127.0.0.1:{env['port']}"}]
    assert spec["components"]["securitySchemes"]["bearer"] == {"type": "http", "scheme": "bearer"}
    by_name = {t.name: t for t in mcp_server.visible_tools(merge_with_defaults(env["cfg"]))}
    tool_paths = {p.rsplit("/", 1)[1]: v["post"] for p, v in spec["paths"].items()
                  if p.startswith("/api/v1/tools/")}
    assert set(tool_paths) == set(by_name)
    po = tool_paths["place_order"]
    assert po["operationId"] == "place_order"
    assert po["requestBody"]["content"]["application/json"]["schema"] == json.loads(
        json.dumps(by_name["place_order"].schema))
    assert po["x-krypt-destructive"] is True
    assert {"401", "404", "422", "429"} <= set(po["responses"])
    env["cfg"]["mcp_trade_mode"] = "off"
    _, _, spec = http(env, "GET", "/api/v1/openapi.json")
    assert "/api/v1/tools/place_order" not in spec["paths"]
    assert "/api/v1/tools/record_forecast" in spec["paths"]



def test_a_buy_without_a_forecast_is_refused_exactly_as_over_mcp(env):
    err, mcp_msg = mcp_text("place_order", BUY)
    assert err and "forecast_id" in mcp_msg
    st, _, body = tool(env, "place_order", BUY)
    assert st == 422 and body["ok"] is False
    assert body["error"] == mcp_msg
    rows = audit_rows()
    assert [r["client"] for r in rows] == ["mcp-client", f"http:{UA}"]
    assert all(r["ok"] == 0 for r in rows)


def test_the_edge_gate_and_caps_bind_over_http(env):
    fid = forecast(env, 57)
    st, _, body = tool(env, "place_order", dict(BUY, count=10, forecast_id=fid))
    assert st == 422 and "No trade" in body["error"]
    env["cfg"]["mcp_max_order_usd"] = 2.0
    fid = forecast(env, 80)
    st, _, body = tool(env, "place_order", dict(BUY, count=20, forecast_id=fid))
    assert st == 422 and "per-order cap" in body["error"]
    assert paper_book.open_tickers() == []


def test_a_paper_order_that_passes_fills_and_is_attributed(env):
    fid = forecast(env, 80)
    st, _, body = tool(env, "place_order", dict(BUY, forecast_id=fid))
    assert st == 200 and body["ok"] and body["result"]["filled"] == 5
    assert audit_rows()[-1]["client"] == f"http:{UA}"
    assert mcp_server.last_seen()["client"] == f"http:{UA}"


def test_trading_off_refuses_orders_as_over_mcp(env):
    env["cfg"]["mcp_trade_mode"] = "off"
    _, mcp_msg = mcp_text("place_order", BUY)
    st, _, body = tool(env, "place_order", BUY)
    assert st == 404 and body["error"] == mcp_msg
    assert audit_rows() == []
    st, _, body = tool(env, "get_status")
    assert st == 200 and body["result"]["tradeMode"] == "off"


@pytest.fixture
def live(env, monkeypatch):
    env["cfg"]["mcp_trade_mode"] = "live"
    env["authed"] = True

    async def _submit(req, scope=None):
        env["sent"].append(req)
        return {"ok": True, "orderId": f"ord-{len(env['sent'])}", "message": "Placed.",
                "filledContracts": 0, "avgFillCents": None, "status": "resting"}

    async def _pf(authed):
        return {"positions": []}
    mcp_server.configure(submit=_submit)
    monkeypatch.setattr(terminal, "portfolio", _pf)
    monkeypatch.setattr(terminal, "manual_history", lambda limit=300: {"trades": []})
    return env


def test_live_http_orders_queue_for_approval(live):
    fid = forecast(live, 80)
    st, _, body = tool(live, "place_order", dict(BUY, count=3, forecast_id=fid))
    assert st == 200 and body["result"]["pending"] is True
    assert live["sent"] == []
    pend = mcp_server.pending()
    assert len(pend) == 1 and pend[0]["client"] == f"http:{UA}"
    assert asyncio.run(mcp_server.decide(pend[0]["id"], True))["ok"]
    assert len(live["sent"]) == 1


def test_http_cannot_sell_or_cancel_the_users_own_book(live):
    st, _, body = tool(live, "place_order", {"ticker": TICKER, "side": "yes",
                                             "action": "sell", "count": 5, "price_cents": 50})
    assert st == 422 and "only sell what it opened" in body["error"]
    st, _, body = tool(live, "cancel_order", {"order_id": "users-own-order"})
    assert st == 422 and "user's" in body["error"]


def test_an_order_one_agent_door_opened_is_exitable_through_the_other(live, monkeypatch):
    """Scoping is per agent TOKEN, not per self-declared client name: what an
    MCP client opened, an HTTP script holding the same token may close (and
    vice versa), while the user's own book stays out of reach of both."""
    live["cfg"]["mcp_live_approval"] = False

    async def _fills(order_id, side, pin_env=None):
        return (3, 54.0) if order_id == "ord-1" else (0, None)
    monkeypatch.setattr(terminal, "_reconcile_fills", _fills)
    _, f = mcp_text("record_forecast", {"ticker": TICKER, "fair_value_cents": 80,
                                        "rationale": "Base rates and the rules text both point this way."})
    fid = json.loads(f)["forecastId"]
    err, _ = mcp_text("place_order", dict(BUY, count=3, forecast_id=fid))
    assert not err
    st, _, body = tool(live, "place_order", {"ticker": TICKER, "side": "yes",
                                             "action": "sell", "count": 3, "price_cents": 50})
    assert st == 200, body
    st, _, body = tool(live, "place_order", {"ticker": TICKER, "side": "yes",
                                             "action": "sell", "count": 1, "price_cents": 50})
    assert st == 422 and "only sell what it opened" in body["error"]


def test_rate_limit_is_per_agent_with_a_shared_ceiling_and_answers_429(env):
    import time
    now = time.monotonic()
    mcp_server._agent_hits["default"] = [now] * mcp_server.RATE_MAX
    st, hdr, body = tool(env, "get_status")
    assert st == 429 and "Retry-After" in hdr
    assert body["error"].startswith(mcp_server._RATE_LIMIT_TEXT)
    mcp_server._agent_hits.clear()
    mcp_server._agent_hits["sam1"] = [now] * mcp_server.RATE_MAX
    st, _, body = tool(env, "get_status")
    assert st == 200, body
    mcp_server._hits[:] = [now] * mcp_server.RATE_GLOBAL_MAX
    st, _, body = tool(env, "get_status")
    assert st == 429 and body["error"].startswith(mcp_server._RATE_LIMIT_TEXT)



def test_client_name_is_a_cleaned_label():
    assert mcp_server.http_client_name("n8n/1.2 (+bot)") == "http:n8n/1.2 (+bot)"
    assert mcp_server.http_client_name(None) == "http:unknown"
    forged = mcp_server.http_client_name("x\r\n[mcp] LIVE buy 999 \x00" + "a" * 200)
    assert "\r" not in forged and "\n" not in forged and "\x00" not in forged
    assert len(forged) <= len("http:") + 60


def test_the_snippet_carries_the_token_and_its_python_runs():
    text = mcp_server.http_snippet(47821, "kt_secret_example")
    assert "Bearer kt_secret_example" in text
    assert "http://127.0.0.1:47821/api/v1/tools" in text
    py = text.split("# --- Python", 1)[1].split("\n", 1)[1]
    compile(py, "<snippet>", "exec")
    assert re.search(r"__(BASE|TOKEN)__", text) is None
