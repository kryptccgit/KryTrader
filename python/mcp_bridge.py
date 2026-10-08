"""stdio <-> local HTTP bridge for MCP clients that only speak stdio.

Claude Desktop and Codex launch an MCP server as a child process and talk
JSON-RPC over its stdin/stdout. The trading engine cannot be that child — it is
already a child of the Electron app, holding the decrypted Kalshi key, the
websocket books and the rails. Starting a SECOND engine per AI client would
mean two processes placing orders against one account, which is exactly the
double-backend failure python-backend.ts exists to prevent.

So the client launches this instead: the same frozen executable with
`--mcp-stdio`, which forwards each line to the running app's loopback MCP
endpoint and writes the reply back. It holds no state beyond the session id,
imports nothing but the standard library, and never touches the engine.

It is dispatched from the very top of service.py, BEFORE logging is set up and
before any engine module is imported — the bridge must not open backend.log,
read credentials, or take a second copy of anything.
"""
from __future__ import annotations

import http.client
import json
import os
import sys

DEFAULT_PORT = 47821
_LOOPBACK = "127.0.0.1"
_TIMEOUT = 120.0


def _port(argv: list[str]) -> int:
    for i, a in enumerate(argv):
        if a == "--port" and i + 1 < len(argv):
            try:
                return int(argv[i + 1])
            except ValueError:
                pass
    try:
        return int(os.environ.get("KRYPT_MCP_PORT") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def _err(msg_id, text: str) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "id": msg_id,
                        "error": {"code": -32000, "message": text}})
            + "\n").encode("utf-8")


def main(argv: list[str]) -> int:
    port = _port(argv)
    token = (os.environ.get("KRYPT_MCP_TOKEN") or "").strip()
    out = sys.stdout.buffer
    if not token:
        sys.stderr.write(
            "krypt-trader MCP bridge: KRYPT_MCP_TOKEN is not set. Copy the "
            "client config from Krypt Trader -> AI Agents; it includes it.\n")
        return 2
    session = None
    for raw in sys.stdin.buffer:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        msg_id = msg.get("id") if isinstance(msg, dict) else None
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        }
        if session:
            headers["Mcp-Session-Id"] = session
        try:
            conn = http.client.HTTPConnection(_LOOPBACK, port, timeout=_TIMEOUT)
            conn.request("POST", "/mcp", body=line, headers=headers)
            resp = conn.getresponse()
            body = resp.read()
            sid = resp.getheader("Mcp-Session-Id")
            if sid:
                session = sid
            conn.close()
        except OSError:
            if msg_id is not None:
                out.write(_err(msg_id, (
                    f"Krypt Trader is not running, or its MCP server is off "
                    f"(port {port}). Open the app -> AI Agents and switch it on.")))
                out.flush()
            continue
        if resp.status == 202 or not body:
            continue
        if resp.status != 200:
            if msg_id is not None:
                try:
                    detail = json.loads(body).get("error") or body.decode("utf-8", "replace")
                except ValueError:
                    detail = body.decode("utf-8", "replace")
                out.write(_err(msg_id, f"Krypt Trader refused the request "
                                       f"(HTTP {resp.status}): {detail}"))
                out.flush()
            continue
        try:
            out.write((json.dumps(json.loads(body)) + "\n").encode("utf-8"))
        except ValueError:
            if msg_id is not None:
                out.write(_err(msg_id, "Krypt Trader returned a malformed reply."))
        out.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
