"""Shared SSL context for outbound WebSocket (wss://) connections.

Why this file exists: the app worked on Windows and was dead on macOS.

A frozen (PyInstaller) build ships its own Python, and that Python's OpenSSL
default verify paths point at the build machine, not the user's. On macOS
nothing fills the gap — there is no system CA store where OpenSSL was
compiled to look — so every `websockets.connect` to a wss:// URL fails the
handshake with SSLCertVerificationError ("unable to get local issuer
certificate"). REST keeps working the whole time, because httpx verifies
against the certifi bundle it carries, which is why this reads as "the app
opens but no prices ever arrive" rather than as a network error.

Build the websocket context from that same certifi bundle so both stacks trust
the same roots on every platform.
"""
from __future__ import annotations

import ssl
from typing import Optional

_ctx: Optional[ssl.SSLContext] = None


def client_context() -> Optional[ssl.SSLContext]:
    """certifi-backed client SSLContext, cached after the first build.

    Returns None when certifi is unavailable — `websockets.connect(ssl=None)`
    keeps its stock default-context behaviour, so this can only ever improve
    verification, never disable or break it.
    """
    global _ctx
    if _ctx is None:
        try:
            import certifi
            _ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            return None
    return _ctx
