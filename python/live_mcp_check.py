"""LIVE check for the MCP server. Run by hand.

Unit tests pin the rails with Kalshi stubbed out; this drives the real thing
end to end, the way Claude Desktop or Codex would: it launches
`service.py --mcp-stdio` as a child process (proving the early dispatch in
service.py, the bridge, and the loopback listener), and calls the tools against
LIVE Kalshi public data.

It never places an order, paper or live. It records one forecast — into a
scratch data directory, not your real one — and previews an order against it,
expecting the edge gate to refuse a forecast that merely agrees with the market.

The workbench phase runs the research, backtest and script tools against a
COPY of your collected data (the installed app's database if there is one,
else the dev one), so the numbers are real and nothing of yours is written.

    python/.venv/Scripts/python.exe python/live_mcp_check.py
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / "python"
sys.path.insert(0, str(PY))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["KRYPT_TRADER_USERDATA"] = tempfile.mkdtemp(prefix="krypt-mcp-live-")


def _copy_real_db() -> str:
    """sqlite's backup API, not a file copy: the live app keeps the database in
    WAL mode and a raw copy can miss the newest pages."""
    import sqlite3
    cands = [Path(os.environ.get("APPDATA", "")) / "Krypt Trader" / "data" / "krypt-trader.db",
             PY / "data" / "krypt-trader.db"]
    src = next((c for c in cands if c.is_file()), None)
    if src is None:
        return "no collected-data database found; research checks run on an empty one"
    dst = Path(os.environ["KRYPT_TRADER_USERDATA"]) / "data"
    dst.mkdir(parents=True, exist_ok=True)
    a = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    b = sqlite3.connect(str(dst / "krypt-trader.db"))
    a.backup(b)
    a.close()
    b.close()
    return f"copied {src}"


DB_SOURCE = _copy_real_db()

import db
import mcp_server
from config import merge_with_defaults

RESULTS: list[tuple[str, bool, str]] = []


def rec(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:30} {detail}")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class Bridge:
    """The child process an MCP client would launch. Set KRYPT_BRIDGE_EXE to a
    built krypt-trader-backend executable to test the PACKAGED bridge — the
    path Claude Desktop actually launches."""

    def __init__(self, port: int, token: str):
        exe = os.environ.get("KRYPT_BRIDGE_EXE")
        cmd = ([exe] if exe else [sys.executable, str(PY / "service.py")])
        self.p = subprocess.Popen(
            cmd + ["--mcp-stdio", "--port", str(port)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={**os.environ, "KRYPT_MCP_TOKEN": token}, cwd=str(PY))
        self.n = 0

    def send(self, method: str, params: dict | None = None, note: bool = False):
        msg = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not note:
            self.n += 1
            msg["id"] = self.n
        self.p.stdin.write((json.dumps(msg) + "\n").encode())
        self.p.stdin.flush()
        if note:
            return None
        return json.loads(self.p.stdout.readline())

    def tool(self, name: str, args: dict | None = None):
        r = self.send("tools/call", {"name": name, "arguments": args or {}})
        res = r["result"]
        text = res["content"][0]["text"]
        try:
            body = json.loads(text)
        except ValueError:
            body = text
        return res["isError"], body

    def close(self) -> None:
        try:
            self.p.stdin.close()
            self.p.wait(10)
        except Exception:
            self.p.kill()


async def main() -> int:
    import service
    db.init_db()
    print(f"  data: {DB_SOURCE}")
    cfg = {"mcp_enabled": True, "mcp_trade_mode": "paper",
           "mcp_allow_research": True, "mcp_allow_scripts": True}
    patches: list = []

    async def _emit(name, data):
        if name == "mcp:configPatch":
            patches.append(data)
    mcp_server.configure(get_cfg=lambda: merge_with_defaults(dict(cfg)),
                         is_authed=lambda: False, version="live-check",
                         rpc=service._mcp_rpc, emit=_emit)
    port = _free_port()
    token = mcp_server.rotate_token()
    await mcp_server.start(port)
    rec("listener", mcp_server.STATUS.running, f"127.0.0.1:{port}")

    def drive() -> None:
        b = Bridge(port, token)
        try:
            init = b.send("initialize", {"protocolVersion": "2025-06-18",
                                         "clientInfo": {"name": "live-check", "version": "1"}})
            rec("initialize via stdio bridge", "result" in init,
                init.get("result", {}).get("protocolVersion", str(init)))
            b.send("notifications/initialized", note=True)
            tools = b.send("tools/list")["result"]["tools"]
            names = {t["name"] for t in tools}
            rec("tools/list (paper+research+scripts)",
                {"place_order", "summarize_research", "save_script"} <= names
                and "update_engine_config" not in names, f"{len(tools)} tools")

            err, st = b.tool("get_status")
            rec("get_status", not err and st.get("tradeMode") == "paper",
                f"mode={st.get('tradeMode')} account={st.get('accountMode')}")

            err, disc = b.tool("discover_markets", {"column": "closing", "limit": 15})
            rows = [] if err else disc["markets"]
            two_sided = [m for m in rows if m["yesBid"] is not None and m["yesAsk"] is not None]
            rec("discover_markets (live)", bool(rows),
                f"{len(rows)} markets, {len(two_sided)} two-sided")
            absent = sum(1 for m in rows for k in ("yesBid", "yesAsk") if m[k] is None)
            zeros = sum(1 for m in rows for k in ("yesBid", "yesAsk") if m[k] == 0)
            rec("absent quotes are null, not 0", zeros == 0, f"{absent} null, {zeros} zero")
            if not two_sided:
                rec("pick a market", False, "no two-sided market in the closing column")
                return
            m = two_sided[0]
            t = m["ticker"]

            err, text = b.tool("get_market", {"ticker": t})
            rec("get_market renders rules", not err and "THE MARKET" in str(text),
                f"{t}, {len(str(text))} chars")

            err, book = b.tool("get_orderbook", {"ticker": t})
            rec("get_orderbook", not err, f"source={book.get('source') if not err else book}")

            mid = round((m["yesBid"] + m["yesAsk"]) / 2)
            err, f = b.tool("record_forecast", {
                "ticker": t, "fair_value_cents": max(1, min(99, mid)),
                "rationale": "Live harness: a forecast that simply agrees with the market mid.",
                "model": "live-check"})
            rec("record_forecast", not err and isinstance(f, dict) and "forecastId" in f,
                f"id={f.get('forecastId') if isinstance(f, dict) else f}")
            if err:
                return
            err, pv = b.tool("preview_order", {
                "ticker": t, "side": "yes", "action": "buy", "count": 1,
                "price_cents": m["yesAsk"], "forecast_id": f["forecastId"]})
            refused = (not err) and not pv["wouldPlace"] and any(
                "No trade" in x for x in pv["blockers"])
            rec("edge gate refuses no-edge buy", refused,
                (pv["blockers"][0][:70] if not err and pv["blockers"] else str(pv)[:70]))

            err, sb = b.tool("get_scoreboard")
            rec("get_scoreboard", not err and sb["totalForecasts"] >= 1,
                f"total={sb.get('totalForecasts') if not err else sb}")

            err, inv = b.tool("get_data_inventory")
            rec("get_data_inventory", not err, (json.dumps(inv)[:70] if not err else str(inv)[:70]))
            err, sm = b.tool("summarize_research", {"dataset": "crypto15m_signals",
                                                    "group_by": "entry_cost_bucket",
                                                    "since_days": 365})
            rec("summarize crypto15m by entry", not err,
                f"{len(sm['buckets'])} buckets" if not err else str(sm)[:70])
            if not err:
                for bk in sm["buckets"][:12]:
                    print(f"        entry {bk['bucket']}c: n={bk['n']} "
                          f"win={bk['favorite_win_rate']} gross={bk.get('gross_edge_cents')}c")
            err, wh = b.tool("summarize_research", {"dataset": "whale_trades",
                                                    "group_by": "price_bucket",
                                                    "since_days": 365})
            rec("summarize whales by price", not err,
                f"{len(wh['buckets'])} buckets" if not err else str(wh)[:70])
            err, bt = b.tool("backtest_crypto15m", {"since_days": 30})
            rec("backtest_crypto15m (real ticks)", not err,
                (json.dumps(bt["result"])[:70] if not err else str(bt)[:70]))
            err, guide = b.tool("get_script_guide")
            rec("get_script_guide", not err and len(str(guide)) > 1000, f"{len(str(guide))} chars")
            import script_docs
            err, v = b.tool("validate_script", {"code": script_docs.EXAMPLE_SIMPLE})
            rec("validate_script (example)", not err and v.get("ok"), str(v.get("errors"))[:60])
            err, sbt = b.tool("backtest_script", {"code": script_docs.EXAMPLE_SIMPLE,
                                                  "since_days": 30})
            rec("backtest_script (example)", not err,
                (json.dumps(sbt["result"])[:70] if not err else str(sbt)[:70]))
            err, sv = b.tool("save_script", {"code": script_docs.EXAMPLE_SIMPLE,
                                             "name": "Live-check agent script"})
            rec("save_script lands disabled", not err and sv["enabled"] is False,
                sv.get("id", str(sv))[:40] if isinstance(sv, dict) else str(sv)[:60])
            err, up = b.tool("update_engine_config", {"patch": {"enable_trading": True}})
            rec("settings tool hidden w/o permission", err and "disabled" in str(up), str(up)[:60])
        finally:
            b.close()

    try:
        await asyncio.to_thread(drive)
    finally:
        await mcp_server.stop()

    cfg["mcp_http_enabled"] = True

    def api(method: str, path: str, body: dict | None = None, tok: str | None = token):
        import urllib.request
        import urllib.error
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/v1{path}", method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={**({"Authorization": f"Bearer {tok}"} if tok else {}),
                     "User-Agent": "live-check/1", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    await mcp_server.start(port)
    try:
        st, tl = await asyncio.to_thread(api, "GET", "/tools")
        rec("http GET /tools", st == 200 and len(tl.get("tools", [])) > 5,
            f"{st}, {len(tl.get('tools', [])) if isinstance(tl, dict) else tl} tools")
        st, spec = await asyncio.to_thread(api, "GET", "/openapi.json")
        rec("http openapi.json", st == 200 and "/api/v1/tools/place_order" in spec.get("paths", {}),
            f"{st}, {len(spec.get('paths', {}))} paths")
        st, disc = await asyncio.to_thread(api, "POST", "/tools/discover_markets",
                                           {"column": "closing", "limit": 5})
        rec("http discover_markets (live)", st == 200 and disc["ok"],
            f"{st}, {len(disc.get('result', {}).get('markets', []))} markets")
        t = (disc.get("result", {}).get("markets") or [{}])[0].get("ticker") or "KXNONE-1"
        st, buy = await asyncio.to_thread(api, "POST", "/tools/place_order", {
            "ticker": t, "side": "yes", "action": "buy", "count": 1, "price_cents": 50})
        rec("http buy without forecast refused", st == 422 and "forecast_id" in buy.get("error", ""),
            f"{st} {str(buy.get('error'))[:50]}")
        st, _ = await asyncio.to_thread(api, "GET", "/tools", None, "kt_wrong")
        rec("http wrong token refused", st == 401, str(st))
        st, _ = await asyncio.to_thread(api, "POST", "/tools/no_such_tool", {})
        rec("http unknown tool 404", st == 404, str(st))
    finally:
        await mcp_server.stop()

    bad = Bridge(port, "kt_wrong")
    try:
        await mcp_server.start(port)
        r = await asyncio.to_thread(bad.send, "initialize", {"protocolVersion": "2025-06-18"})
        rec("wrong token refused", "error" in r and "401" in r["error"]["message"],
            r.get("error", {}).get("message", "")[:60])
    finally:
        bad.close()
        await mcp_server.stop()

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
