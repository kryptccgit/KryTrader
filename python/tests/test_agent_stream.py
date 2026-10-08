"""The MCP tool-call stream: one event per call, from the one dispatcher.

The Agent Hub and onboarding watch the user's real agents through this
stream, so what is pinned is (1) that every path an agent can take — an MCP
client over HTTP, the stdio bridge, Autopilot — produces it, because they all
go through call_tool; (2) that nothing an agent typed reaches the event raw —
an agent can be prompt-injected into putting its own bearer token in any
argument, so a token fed through every field must come out absent in every
case; (3) that a looping agent is throttled rather than streamed.
"""
from __future__ import annotations

import asyncio
import io
import json
import socket
import sys
import types
from types import SimpleNamespace as NS

import pytest

import ai_analyst
import autopilot
import db
import forecast_ledger
import kalshi_auth
import logscrub
import mcp_bridge
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
    "yes": [{"priceCents": 50.0, "contracts": 30}],
    "no": [{"priceCents": 46.0, "contracts": 20}],
    "yesBid": 50.0, "yesAsk": 54.0, "stale": False, "source": "kalshi-ws",
}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def events(monkeypatch):
    db.init_db()
    with db.get_db() as conn:
        for t in ("ai_forecasts", "paper_fills", "paper_state", "mcp_orders", "autopilot_runs"):
            conn.execute(f"DELETE FROM {t}")
    mcp_server._hits.clear()
    mcp_server.SEEN.clear()
    mcp_server._MODELS.clear()
    mcp_server._THROTTLE = mcp_server._Throttle()
    got: list[dict] = []

    async def _emit(name, data):
        got.append({"name": name, **json.loads(json.dumps(data))})

    state = {"cfg": {"mcp_enabled": True, "mcp_trade_mode": "paper"}}
    mcp_server.configure(
        get_cfg=lambda: merge_with_defaults(dict(state["cfg"])),
        is_authed=lambda: False, submit=None, cancel=None, rpc=None,
        emit=_emit, notify_phone=None, version="test")

    async def _row(ticker):
        return dict(MARKET, ticker=ticker) if ticker == TICKER else None

    async def _book(ticker):
        return dict(BOOK)

    async def _detail(ticker, authed=False):
        raise RuntimeError(f"Kalshi has no market called {ticker}. Check the ticker.")

    async def _no_marks(tickers):
        return {}

    monkeypatch.setattr(mcp_server, "_market_row", _row)
    monkeypatch.setattr(terminal, "book", _book)
    monkeypatch.setattr(terminal, "market_detail", _detail)
    import kalshi_api
    monkeypatch.setattr(kalshi_api, "fetch_markets_by_tickers", _no_marks)
    yield got
    mcp_server.configure(emit=None)


def calls(got):
    return [e for e in got if e["name"] == mcp_server.TOOLCALL_EVENT and e["kind"] == "call"]


def _call(name, args=None, client="claude-code 2.1"):
    return run(mcp_server.call_tool(name, args or {}, {"client": client}))



def test_an_mcp_client_connecting_and_calling_is_streamed(events):
    ctx: dict = {}
    run(mcp_server.handle_message({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18",
                   "clientInfo": {"name": "claude-code", "version": "2.1"}}}, ctx))
    run(mcp_server.handle_message({
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "get_orderbook", "arguments": {"ticker": "kxtest-26oct-t1"}}}, ctx))
    kinds = [(e["kind"], e["client"]) for e in events]
    assert kinds[0] == ("connect", "claude-code 2.1")
    ev = calls(events)[-1]
    assert ev["tool"] == "get_orderbook" and ev["ticker"] == TICKER
    assert ev["outcome"] == "ok" and ev["summary"] == f"get_orderbook {TICKER}"
    assert isinstance(ev["durationMs"], int) and ev["durationMs"] >= 0
    assert isinstance(ev["at"], int) and ev["v"] == 1


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_the_stdio_bridge_path_is_streamed(events, monkeypatch):
    """The bridge forwards to the HTTP listener, which dispatches through
    call_tool: the event comes from the same place for both."""
    port = _free_port()
    token = mcp_server.rotate_token()

    def _bridge(lines):
        stdin = type("S", (), {"buffer": io.BytesIO("".join(lines).encode())})()
        out = io.BytesIO()
        monkeypatch.setattr(sys, "stdin", stdin)
        monkeypatch.setattr(sys, "stdout", type("S", (), {"buffer": out})())
        monkeypatch.setenv("KRYPT_MCP_TOKEN", token)
        return mcp_bridge.main(["--port", str(port)])

    async def _go():
        await mcp_server.start(port)
        try:
            rc = await asyncio.to_thread(_bridge, [
                json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                            "params": {"protocolVersion": "2025-06-18",
                                       "clientInfo": {"name": "claude-ai", "version": "0.9"}}}) + "\n",
                json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                            "params": {"name": "get_status", "arguments": {}}}) + "\n",
            ])
            assert rc == 0
        finally:
            await mcp_server.stop()

    run(_go())
    ev = calls(events)[-1]
    assert ev["tool"] == "get_status" and ev["outcome"] == "ok"
    assert ev["client"] == "claude-ai 0.9"
    assert ev["summary"] == "get_status · paper"
    assert any(e["kind"] == "connect" and e["client"] == "claude-ai 0.9" for e in events)


class _FakeAnthropic:
    script: list = []

    def __init__(self, **kw):
        self.messages = self

    def create(self, **kw):
        if not _FakeAnthropic.script:
            return NS(content=[NS(type="text", text="done")], stop_reason="end_turn",
                      usage=NS(input_tokens=10, output_tokens=5,
                               cache_creation_input_tokens=0, cache_read_input_tokens=0))
        return _FakeAnthropic.script.pop(0)


def test_autopilot_calls_are_streamed_through_the_same_dispatcher(events, monkeypatch):
    cfg = {"autopilot_enabled": True, "mcp_trade_mode": "off", "mcp_enabled": True,
           "ai_provider": "anthropic", "ai_model": "claude-opus-5"}
    mcp_server.configure(get_cfg=lambda: merge_with_defaults(dict(cfg)))
    monkeypatch.setattr(ai_analyst, "has_key", lambda p: True)
    monkeypatch.setattr(ai_analyst, "_read_key", lambda p: "sk-test")
    fake = types.ModuleType("anthropic")
    fake.Anthropic = _FakeAnthropic
    fake.APIError = type("APIError", (Exception,), {})
    monkeypatch.setitem(sys.modules, "anthropic", fake)
    u = NS(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0,
           cache_read_input_tokens=0)
    _FakeAnthropic.script = [
        NS(content=[NS(type="tool_use", name="get_status", input={}, id="t1")],
           stop_reason="tool_use", usage=u),
    ]
    autopilot.STATE.running = False
    res = run(autopilot.run_once(merge_with_defaults(dict(cfg)), "manual"))
    assert res["ok"], res
    ev = calls(events)[-1]
    assert ev["tool"] == "get_status" and ev["client"].startswith("autopilot (")
    assert ev["outcome"] == "ok"



def test_a_forecast_event_carries_its_number_and_edge(events):
    r = _call("record_forecast", {"ticker": TICKER, "fair_value_cents": 70, "model": "opus",
                                  "rationale": "Base rates and the rules text both point this way."})
    assert not r["isError"]
    ev = calls(events)[-1]
    assert ev["fairCents"] == 70 and ev["side"] == "yes" and ev["edgeCents"] > 0
    assert ev["midCents"] == 52
    assert ev["summary"].startswith(f"forecast {TICKER} 70¢ · edge +")
    _call("get_status")
    assert calls(events)[-1]["model"] == "opus"
    row = forecast_ledger.scoreboard()["recent"][0]
    assert row["client"] == "claude-code 2.1" and row["model"] == "opus"
    _call("record_forecast", {"ticker": TICKER, "fair_value_cents": 66,
                              "rationale": "Same agent, a second look at the same market."})
    fs = forecast_ledger.scoreboard()["byForecaster"]
    assert [(f["client"], f["model"], f["total"]) for f in fs] == [("claude-code 2.1", "opus", 2)]


def test_a_refusal_is_streamed_with_the_rails_reason(events):
    _call("place_order", {"ticker": TICKER, "side": "yes", "action": "buy",
                          "count": 2, "price_cents": 54})
    ev = calls(events)[-1]
    assert ev["outcome"] == "refused" and ev["mode"] == "paper"
    assert "forecast_id" in ev["reason"]
    assert not ev["reason"].lower().startswith("refused")
    assert ev["summary"] == f"buy 2 YES {TICKER} @54¢"


def test_a_paper_fill_is_labelled_paper(events):
    fid = json.loads(_call("record_forecast", {
        "ticker": TICKER, "fair_value_cents": 80,
        "rationale": "Base rates and the rules text both point this way."})["content"][0]["text"])["forecastId"]
    r = _call("place_order", {"ticker": TICKER, "side": "yes", "action": "buy",
                              "count": 2, "price_cents": 54, "forecast_id": fid})
    assert not r["isError"], r
    ev = calls(events)[-1]
    assert ev["outcome"] == "ok" and ev["mode"] == "paper"
    assert ev["summary"].endswith("· filled 2 @54¢")


def test_a_disabled_or_unknown_tool_never_echoes_its_name(events):
    _call("definitely_not_a_tool_kt_" + "x" * 40)
    ev = calls(events)[-1]
    assert ev["tool"] == "unknown" and ev["outcome"] == "refused"
    assert "x" * 20 not in json.dumps(ev)



def test_token_and_key_material_fed_through_every_argument_is_absent(events):
    tok = mcp_server.rotate_token()
    logscrub.refresh_known_secrets()
    unregistered = "sk-ant-api03-" + "Q7x9" * 12
    for secret in (tok, unregistered, tok.upper()):
        ctx = {"client": secret}
        run(mcp_server.handle_message({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"clientInfo": {"name": secret, "version": secret[:12]}}}, {}))
        for name, args in (
            ("get_market", {"ticker": secret}),
            ("get_orderbook", {"ticker": secret}),
            ("search_markets", {"query": f"what about {secret}"}),
            ("discover_markets", {"column": secret}),
            ("record_forecast", {"ticker": secret, "fair_value_cents": 60,
                                 "model": secret, "rationale": secret * 2}),
            ("record_forecast", {"ticker": TICKER, "fair_value_cents": 60,
                                 "model": secret, "rationale": f"because {secret} said so"}),
            ("place_order", {"ticker": secret, "side": secret, "action": "buy",
                             "count": 1, "price_cents": 50, "forecast_id": secret}),
            ("backtest_crypto15m", {"days": secret}),
            (secret, {"ticker": secret}),
        ):
            run(mcp_server.call_tool(name, args, ctx))
    blob = json.dumps(events).lower()
    assert len(calls(events)) > 10
    for secret in (tok, unregistered):
        low = secret.lower()
        assert low not in blob
        for i in range(0, len(low) - 16, 4):
            assert low[i:i + 16] not in blob, low[i:i + 16]
    assert tok.lower()[:16] not in json.dumps(mcp_server.seen()).lower()


def test_labels_and_tickers_are_whitelisted_shapes():
    assert mcp_server.safe_ticker("kxfed-26dec-t4.25") == "KXFED-26DEC-T4.25"
    assert mcp_server.safe_ticker("KX" + "A" * 30) is None
    assert mcp_server.safe_ticker("a b") is None
    assert mcp_server.safe_label("Cursor 1.7\n\x00") == "Cursor 1.7"
    assert mcp_server.safe_label("Bearer abcdefghijk12345") == ""
    assert mcp_server.safe_reason("Refused:\n- A buy needs forecast_id.\n- other") == \
        "A buy needs forecast_id."



def test_the_throttle_drops_a_flood_and_counts_what_it_dropped():
    t = [0.0]
    th = mcp_server._Throttle(burst=3, rate=2.0, clock=lambda: t[0])
    assert [th.take() for _ in range(5)] == [True, True, True, False, False]
    assert th.suppressed == 2
    t[0] += 0.5
    assert th.take() is True and th.take() is False


def test_a_looping_agent_is_throttled_and_the_next_event_says_how_many(events, monkeypatch):
    clock = [100.0]
    mcp_server._THROTTLE = mcp_server._Throttle(clock=lambda: clock[0])
    for _ in range(40):
        _call("get_status")
    sent = calls(events)
    assert len(sent) == mcp_server.EVENT_BURST
    clock[0] += 10
    _call("get_status")
    last = calls(events)[-1]
    assert last["suppressed"] == 40 - mcp_server.EVENT_BURST
    assert mcp_server.STATUS.calls >= 41


def test_seen_is_memory_only_and_counts_calls(events, monkeypatch):
    def _no(*a, **k):
        raise AssertionError("seen() must not touch the database or the network")
    _call("get_status", client="cursor 1.7")
    _call("get_status", client="cursor 1.7")
    monkeypatch.setattr(db, "get_db", _no)
    monkeypatch.setattr(kalshi_auth, "read_secret", _no)
    s = mcp_server.seen()
    row = next(c for c in s["clients"] if c["client"] == "cursor 1.7")
    assert row["calls"] == 2 and row["lastAt"] >= row["firstAt"]


def test_no_emit_hook_means_no_event_and_no_error():
    mcp_server.configure(emit=None)
    r = _call("get_status")
    assert not r["isError"]



def test_forecasters_are_split_by_client_and_model_with_their_open_calls():
    for client, model, fv in (("claude-code 2.1", "opus", 61), ("cursor 1.7", "opus", 55),
                              ("claude-code 2.1", "opus", 63)):
        forecast_ledger.record(ticker=TICKER, prob_yes=fv / 100, source="mcp", model=model,
                               client=client, market=MARKET, rationale="x" * 30)
    forecast_ledger.record(ticker="KXOTHER-1", prob_yes=0.4, source="panel",
                           model="claude-sonnet-4-5", market={}, rationale="y")
    fs = forecast_ledger.scoreboard()["byForecaster"]
    who = {(f["source"], f["client"], f["model"]): f for f in fs}
    cc = who[("mcp", "claude-code 2.1", "opus")]
    assert cc["total"] == 2 and cc["n"] == 0 and cc["brierAi"] is None
    assert cc["open"] == [{"ticker": TICKER, "fairValueCents": 63.0, "marketMidCents": 52.0,
                           "createdAt": cc["open"][0]["createdAt"]}]
    assert who[("mcp", "cursor 1.7", "opus")]["open"][0]["fairValueCents"] == 55.0
    panel = who[("panel", None, "claude-sonnet-4-5")]
    assert panel["open"][0]["marketMidCents"] is None
    assert panel["agentId"] is None and cc["agentId"] == "default"


def test_two_named_agents_on_one_client_and_model_are_two_forecasters():
    for aid, fv in (("default", 40), ("default", 45), ("sam1", 61)):
        forecast_ledger.record(ticker=TICKER, prob_yes=fv / 100, source="mcp", model="opus",
                               client="claude-code 2.1", market=MARKET, rationale="x" * 30,
                               agent_id=aid)
    with db.get_db() as conn:
        conn.execute("UPDATE ai_forecasts SET agent_id=NULL WHERE id=(SELECT MIN(id) FROM ai_forecasts)")
    fs = forecast_ledger.scoreboard()["byForecaster"]
    by = {f["agentId"]: f for f in fs}
    assert set(by) == {"default", "sam1"}
    assert by["default"]["total"] == 2 and by["default"]["open"][0]["fairValueCents"] == 45.0
    assert by["sam1"]["total"] == 1 and by["sam1"]["open"][0]["fairValueCents"] == 61.0
    assert all((f["client"], f["model"]) == ("claude-code 2.1", "opus") for f in fs)


def test_a_settled_forecaster_is_scored_on_its_own_calls():
    for i in range(3):
        t = f"KXS-{i}"
        forecast_ledger.record(ticker=t, prob_yes=0.8, source="mcp", model="opus",
                               client="claude-code 2.1", market={"midCents": 50}, rationale="z" * 30)
    with db.get_db() as conn:
        conn.execute("UPDATE ai_forecasts SET outcome=1.0")
    f = forecast_ledger.scoreboard()["byForecaster"][0]
    assert f["n"] == 3 and f["nPaired"] == 3
    assert f["brierAi"] == pytest.approx(0.04) and f["brierMarket"] == pytest.approx(0.25)
    assert f["skill"] > 0 and f["verdict"] == "too-few"
    assert f["open"] == []
