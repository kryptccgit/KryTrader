"""LIVE check for the remote transports. Run by hand.

Unit tests pin our logic with the network stubbed; this pins the transports'
real behaviour — that the endpoints exist, that a bad token is REJECTED rather
than silently hanging (a bot that looks like it is connecting forever is the
worst failure mode here), and that the RPC surface works over the actual wire.

With no tokens configured it still runs: the reachability and bad-token checks
are the point, and they need no credentials.

    python/.venv/Scripts/python.exe python/live_remote_check.py
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import httpx
import remote
import remote_telegram

RESULTS: list[tuple[str, bool, str]] = []


def rec(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name:34} {detail}")


async def transports() -> None:
    print("=== reachability ===")
    async with httpx.AsyncClient(timeout=15.0) as c:
        try:
            r = await c.get("https://discord.com/api/v10/gateway")
            url = (r.json() or {}).get("url", "") if r.status_code == 200 else ""
            rec("discord gateway endpoint", r.status_code == 200 and "wss" in url,
                f"HTTP {r.status_code} {url}")
        except Exception as e:
            rec("discord gateway endpoint", False, f"{type(e).__name__}: {e}")

        try:
            r = await c.post(
                "https://api.telegram.org/bot123456:INVALIDTOKEN/getMe", json={})
            rec("telegram rejects a bad token", r.status_code == 401,
                f"HTTP {r.status_code}")
        except Exception as e:
            rec("telegram rejects a bad token", False, f"{type(e).__name__}: {e}")

    print("\n=== telegram client surfaces a bad token as an error ===")
    bot = remote_telegram.TelegramBot()
    bot.token = "123456:INVALIDTOKEN"
    me = await bot._call("getMe")
    ok = me is None and bot.last_error is not None
    rec("bad token -> last_error set", ok, str(bot.last_error)[:70])
    await bot.stop()


def rpc_surface() -> None:
    """Drive the real backend over stdio and exercise the remote RPCs."""
    print("\n=== backend RPC surface ===")
    userdata = Path(os.environ.get("TEMP", ".")) / "krypt-remote-check"
    env = dict(os.environ)
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1",
                "KRYPT_KALSHI_WS": "0", "KRYPT_TRADER_USERDATA": str(userdata)})
    proc = subprocess.Popen(
        [str(ROOT / "python" / ".venv" / "Scripts" / "python.exe"),
         str(ROOT / "python" / "service.py")],
        cwd=str(ROOT / "python"), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env, bufsize=1)

    pending: dict = {}
    n = [0]

    def call(method, params=None, timeout=30.0):
        n[0] += 1
        rid = f"r{n[0]}"
        proc.stdin.write(json.dumps({"type": "rpc", "id": rid, "method": method,
                                     "params": params or {}}) + "\n")
        proc.stdin.flush()
        end = time.time() + timeout
        while rid not in pending and time.time() < end:
            line = proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if line.startswith("{"):
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                if m.get("type") == "rpc":
                    pending[m["id"]] = m
        return pending.get(rid)

    try:
        res = call("remoteStatus")
        ok = bool(res and res.get("ok"))
        st = (res or {}).get("result", {})
        rec("remoteStatus", ok,
            f"discord configured={st.get('discord', {}).get('configured')} "
            f"telegram configured={st.get('telegram', {}).get('configured')} "
            f"trading={st.get('tradingEnabled')}")
        rec("remote trading defaults off", st.get("tradingEnabled") is False,
            f"tradingEnabled={st.get('tradingEnabled')}")

        res = call("remotePairCode")
        code = (res or {}).get("result", {}).get("code", "")
        rec("remotePairCode", bool(code) and len(code) == remote.PAIR_CODE_LEN,
            f"code={code}")

        res = call("remoteSetToken", {"which": "telegram", "token": "abc123"})
        ok = bool(res and res.get("ok")
                  and (res.get("result") or {}).get("hasToken"))
        rec("token stored via RPC", ok, "saved to the encrypted credential store")

        import kalshi_auth
        os.environ["KRYPT_TRADER_USERDATA"] = str(userdata)
        rec("token is not in settings.json",
            not (userdata / "settings.json").exists()
            or "abc123" not in (userdata / "settings.json").read_text(
                encoding="utf-8", errors="replace"),
            "checked settings.json for the raw token")

        res = call("remoteSetToken", {"which": "telegram", "token": ""})
        cleared = not (res or {}).get("result", {}).get("hasToken", True)
        rec("token cleared via RPC", cleared, "")

        res = call("remoteTest")
        sent = (res or {}).get("result", {}).get("sent", [])
        rec("remoteTest with no bot running", bool(res and res.get("ok")),
            f"sent={sent} (empty is correct with nothing configured)")
    finally:
        try:
            proc.stdin.write(json.dumps(
                {"type": "rpc", "id": "z", "method": "shutdown", "params": {}}) + "\n")
            proc.stdin.flush()
            time.sleep(1.0)
        except Exception:
            pass
        proc.terminate()


async def main() -> int:
    print("\nRemote transports — live check\n")
    await transports()
    rpc_surface()
    fails = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(fails)} ok, {len(fails)} failed")
    for name, _ok, detail in fails:
        print(f"  FAILED {name}: {detail}")
    return 1 if fails else 0


raise SystemExit(asyncio.run(main()))
