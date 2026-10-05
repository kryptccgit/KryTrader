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
                f"mode={st.get('tradeMode')} env={st.get('kalshiEnvironment')}")

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
