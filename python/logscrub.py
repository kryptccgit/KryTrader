"""Keep credentials out of the logs.

This matters more now than it did. The app holds a Kalshi API key, an RSA
private key, a Discord bot token and a Telegram bot token — and it is about to
be handed to beta users who will, reasonably, paste their logs into a chat
window when something breaks. A log line is the most likely way a secret
escapes this app, and it escapes to exactly the people trying to help.

Two independent passes, because each catches what the other misses:

  * **By value.** The literal secrets currently loaded are redacted wherever
    they appear, whatever the surrounding text. This is exact and catches a
    token logged by a library we do not control.
  * **By shape.** Discord and Telegram token patterns, AI provider keys with a
    known prefix (sk-..., AIza...), PEM private-key blocks and bearer headers
    are redacted even when the value is one we have never
    seen — a token the user pasted into the wrong box, or a second account's.

Deliberately NOT scrubbed: bare UUIDs. Kalshi order ids are UUIDs and they are
the single most useful thing in a trading log; blanket-redacting them would
make every bug report unreadable to save nothing, since the API key is caught
by value anyway.
"""
from __future__ import annotations

import logging
import re
from typing import Iterable

REDACTED = "[redacted]"

_DISCORD = re.compile(r"\b[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6,7}\.[A-Za-z0-9_-]{27,40}\b")
_TELEGRAM = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,45}\b")
_PEM = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
    re.S)
_AUTH_HEADER = re.compile(r"(?i)\b(authorization|x-api-key)\s*[:=]\s*\S.*")
_SCHEME_TOKEN = re.compile(r"(?i)\b(?:bearer|bot)\s+[A-Za-z0-9._\-]{8,}")
_TG_URL = re.compile(r"(api\.telegram\.org/bot)[^/\s]+")

_DISCORD_WEBHOOK_URL = re.compile(
    r"(discord(?:app)?\.com/api/webhooks/\d+/)[A-Za-z0-9_\-]+")

_SK_KEY = re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_\-]{19,}")
_GOOGLE_KEY = re.compile(r"\bAIza[0-9A-Za-z_\-]{35}(?![0-9A-Za-z_\-])")

_SHAPES = (_PEM, _DISCORD, _TELEGRAM, _SK_KEY, _GOOGLE_KEY, _SCHEME_TOKEN, _AUTH_HEADER)

_values: list[str] = []


def set_known_secrets(values: Iterable[str]) -> None:
    """Register the literal secrets currently loaded, longest first so a
    substring of one cannot mask a longer match."""
    global _values
    vals = sorted({v.strip() for v in values if v and len(v.strip()) >= 12},
                  key=len, reverse=True)
    _values = vals


def refresh_known_secrets() -> None:
    """Re-read every secret this app holds. Cheap; called after any change."""
    try:
        import kalshi_auth
        found: list[str] = []
        names = ["discord_bot_token", "telegram_bot_token",
                 "ai_anthropic_key", "ai_openai_key",
                 "ai_openrouter_key", "ai_gemini_key", "mcp_token"]
        try:
            names += [n for n in kalshi_auth.list_secret_names("mcp_token_")
                      if n not in names]
        except Exception:
            pass
        for name in names:
            v = kalshi_auth.read_secret(name)
            if v:
                found.append(v)
        try:
            key = kalshi_auth.saved_api_key_id()
            if key:
                found.append(key)
        except Exception:
            pass
        set_known_secrets(found)
    except Exception:
        pass


def looks_secret(text: str) -> bool:
    """True when `text` carries any part of a known secret, in ANY case, or a
    secret's shape.

    scrub() matches known values literally, which is right for a log line we
    wrote ourselves. It is not enough for a string an AI agent chose: the MCP
    tool-call stream shows a ticker it passed, and the tool upper-cases
    tickers — so an agent that echoed its own bearer token as a "ticker" would
    hand scrub() `KT_ABC…`, which matches nothing. This folds case, and also
    catches a FRAGMENT (12+ chars) of a known value, because a display field
    gets clipped and a clipped token is still most of a token."""
    if not text:
        return False
    if scrub(text) != text:
        return True
    low = text.lower()
    for v in _values:
        vl = v.lower()
        if vl in low:
            return True
        if len(low) >= 12 and low in vl:
            return True
    return False


def scrub(text: str) -> str:
    if not text:
        return text
    out = text
    for v in _values:
        if v in out:
            out = out.replace(v, REDACTED)
    for pattern in _SHAPES:
        if pattern is _AUTH_HEADER:
            out = pattern.sub(lambda m: f"{m.group(1)}: {REDACTED}", out)
        else:
            out = pattern.sub(REDACTED, out)
    out = _TG_URL.sub(r"\1" + REDACTED, out)
    out = _DISCORD_WEBHOOK_URL.sub(r"\1" + REDACTED, out)
    return out


class ScrubFilter(logging.Filter):
    """Attach to the ROOT logger so every handler — file and stdout — is
    covered by one thing, rather than each remembering to scrub."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            cleaned = scrub(msg)
            if cleaned != msg:
                record.msg = cleaned
                record.args = ()
        except Exception:
            pass
        return True
