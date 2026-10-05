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

_SHAPES = (_PEM, _DISCORD, _TELEGRAM, _SCHEME_TOKEN, _AUTH_HEADER)

_values: list[str] = []


def set_known_secrets(values: Iterable[str]) -> None:
    global _values
    vals = sorted({v.strip() for v in values if v and len(v.strip()) >= 12},
                  key=len, reverse=True)
    _values = vals


def refresh_known_secrets() -> None:
    try:
        import kalshi_auth
        found: list[str] = []
        for name in ("discord_bot_token", "telegram_bot_token",
                     "ai_anthropic_key", "ai_openai_key", "mcp_token"):
            v = kalshi_auth.read_secret(name)
            if v:
                found.append(v)
        try:
            key = kalshi_auth._load_api_key()
            if key:
                found.append(key)
        except Exception:
            pass
        set_known_secrets(found)
    except Exception:
        pass


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
