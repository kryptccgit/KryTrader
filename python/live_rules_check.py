import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USERDATA = Path(sys.argv[1] if len(sys.argv) > 1
                else Path(os.environ.get("TEMP", ".")) / "krypt-rules-check")
(USERDATA / "data").mkdir(parents=True, exist_ok=True)

env = dict(os.environ)
env.update({
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUNBUFFERED": "1",
    "KRYPT_KALSHI_WS": "0",
    "KRYPT_TRADER_USERDATA": str(USERDATA),
})

proc = subprocess.Popen(
    [str(ROOT / "python" / ".venv" / "Scripts" / "python.exe"),
     str(ROOT / "python" / "service.py")],
    cwd=str(ROOT / "python"),
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, encoding="utf-8", env=env, bufsize=1,
)

pending: dict = {}
events: list = []
_id = 0


def send(method, params=None):
    global _id
    _id += 1
    rid = f"r{_id}"
    proc.stdin.write(json.dumps(
        {"type": "rpc", "id": rid, "method": method, "params": params or {}}) + "\n")
    proc.stdin.flush()
    return rid


def pump(until, timeout=60.0):
    end = time.time() + timeout
    while (until - set(pending)) and time.time() < end:
        line = proc.stdout.readline()
        if not line:
            break
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        if m.get("type") == "rpc":
            pending[m["id"]] = m
        elif m.get("type") == "event":
            events.append(m)


def call(method, params=None, timeout=60.0):
    rid = send(method, params)
    pump({rid}, timeout)
    return pending.get(rid)


print("=== finding live tickers ===")
disc = call("terminalDiscover", {"column": "trending", "limit": 6})
rows = (disc or {}).get("result", {}).get("rows", [])
print(f"  {len(rows)} rows")
if not rows:
    print("  no markets; aborting")
    proc.terminate()
    raise SystemExit(1)

quoted = next((r for r in rows if r["yesBid"] is not None), rows[0])
print(f"  quoted: {quoted['ticker']} bid={quoted['yesBid']} ask={quoted['yesAsk']}")

CASES = [
    ("alert fires immediately", {
        "kind": "alert", "ticker": quoted["ticker"], "side": "yes",
        "thresholdCents": 1, "direction": "above"}),
    ("alert never fires", {
        "kind": "alert", "ticker": quoted["ticker"], "side": "yes",
        "thresholdCents": 99, "direction": "above"}),
    ("stop, no credentials", {
        "kind": "stop", "ticker": quoted["ticker"], "side": "yes",
        "thresholdCents": 99, "direction": "below"}),
    ("take, no credentials", {
        "kind": "take", "ticker": quoted["ticker"], "side": "no",
        "thresholdCents": 1, "direction": "above"}),
    ("rule on a settled/unknown market", {
        "kind": "alert", "ticker": "KXDOESNOTEXIST-99ZZZ-X", "side": "yes",
        "thresholdCents": 50, "direction": "above"}),
    ("deci-cent threshold", {
        "kind": "alert", "ticker": quoted["ticker"], "side": "yes",
        "thresholdCents": 1.5, "direction": "above"}),
]

print("\n=== arming rules ===")
for name, req in CASES:
    res = call("terminalRuleCreate", req, timeout=45)
    ok = res and res.get("ok")
    detail = (res or {}).get("result") if ok else (res or {}).get("error")
    print(f"  {'OK  ' if ok else 'ERR '} {name:34} "
          f"{json.dumps(detail)[:110] if ok else detail}")

print("\n=== rejected inputs (must be refused, not crash) ===")
for name, req in [
    ("threshold 0", {"kind": "alert", "ticker": quoted["ticker"], "side": "yes", "thresholdCents": 0}),
    ("threshold 100", {"kind": "alert", "ticker": quoted["ticker"], "side": "yes", "thresholdCents": 100}),
    ("bad kind", {"kind": "nuke", "ticker": quoted["ticker"], "side": "yes", "thresholdCents": 50}),
    ("empty ticker", {"kind": "alert", "ticker": "", "side": "yes", "thresholdCents": 50}),
]:
    res = call("terminalRuleCreate", req, timeout=30)
    refused = res and not res.get("ok")
    print(f"  {'OK  ' if refused else 'BAD '} {name:20} -> "
          f"{(res or {}).get('error', 'ACCEPTED — should have been refused')[:90]}")

print("\n=== letting the evaluator run (25s) ===")
deadline = time.time() + 25
while time.time() < deadline:
    line = proc.stdout.readline()
    if not line:
        break
    line = line.strip()
    if line.startswith("{"):
        try:
            m = json.loads(line)
            if m.get("type") == "event":
                events.append(m)
                if m.get("name") == "terminal:rule":
                    print(f"  EVENT {m['data']['message'][:110]}")
        except Exception:
            pass

print("\n=== final rule state ===")
res = call("terminalRules", {}, timeout=30)
for r in (res or {}).get("result", {}).get("rules", []):
    print(f"  [{r['status']:9}] {r['kind']:5} {r['ticker'][:34]:36} "
          f"{r['direction']} {r['thresholdCents']}c  "
          f"last={r['lastPriceCents']} src={r['lastPriceSource']} "
          f"err={(r['lastError'] or '')[:60]}")

print("\n=== microstructure with the socket off ===")
res = call("terminalMicro", {"ticker": quoted["ticker"]}, timeout=30)
m = (res or {}).get("result", {})
print(f"  samples={m.get('sampleCount')} median={m.get('medianSpreadCents')} "
      f"note={(m.get('note') or '')[:110]}")

send("shutdown", {})
time.sleep(1.5)
proc.terminate()

print("\n=== backend.log: anything that threw ===")
log = USERDATA / "logs" / "backend.log"
bad = []
if log.exists():
    text = log.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"^.*(Traceback|ERROR|CRITICAL|Exception|failed).*$",
                         text, re.MULTILINE):
        line = m.group(0).strip()
        low = line.lower()
        if any(x in low for x in (
            "credentials", "not authenticated",
            "threshold must be", "kind must be one of", "no ticker",
            "has no market called",
        )):
            continue
        if line.strip() == "Traceback (most recent call last):":
            continue
        bad.append(line)
for line in bad[:20]:
    print(f"  {line[:170]}")
print(f"  {len(bad)} suspicious log line(s)")

stderr = proc.stderr.read()
if "Traceback" in stderr:
    print("\n=== stderr traceback ===")
    print(stderr[-2500:])
