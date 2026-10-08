"""Why a freshly saved Kalshi key failed its first signed read, in words a
first-time user can act on.

The setup wizard saves a key and immediately runs one signed balance read (on
the user's click). When that fails, "HTTP 401: {'error': {...}}" is the
message that ends a beginner's setup, or ends with them pasting their private
key into a support chat. Each failure Kalshi can actually produce gets its
own code, a one-line title, and a fix, so the wizard can show the right
next step rather than a generic "try again".

What Kalshi really sends (probed with a throwaway key):

    unknown key id      401 authentication_error, details NOT_FOUND
    malformed key id    401 authentication_error, details INVALID_PARAMETER
    stale timestamp     401 header_timestamp_expired

A key id that exists with the wrong private key is the remaining 401: it is
authentication_error with any other detail.

Keys come from kalshi.com only: the app trades Kalshi production, and practice
happens in Paper mode, which needs no key at all. This module stays pure so
every message is testable without a socket.
"""
from __future__ import annotations

from typing import Any, Optional

SITE = "kalshi.com"


def _error_fields(err: BaseException) -> tuple[Optional[int], str, str]:
    """(status, code, details) from a KalshiAPIError-shaped exception."""
    status = getattr(err, "status", None)
    body: Any = getattr(err, "body", None)
    code = details = ""
    if isinstance(body, dict):
        e = body.get("error")
        if isinstance(e, dict):
            code = str(e.get("code") or "")
            details = str(e.get("details") or "")
    return (status if isinstance(status, int) else None), code.lower(), details.upper()


def _is_network(err: BaseException) -> bool:
    names = {c.__name__ for c in type(err).__mro__}
    if names & {"TimeoutException", "NetworkError", "ConnectError", "ConnectTimeout",
                "ReadTimeout", "RemoteProtocolError", "TimeoutError",
                "ConnectionError", "gaierror"}:
        return True
    low = str(err).lower()
    return any(s in low for s in ("getaddrinfo", "name resolution", "timed out",
                                  "connection refused", "network is unreachable"))


def _is_not_found(err: BaseException) -> bool:
    status, code, details = _error_fields(err)
    return status == 401 and code == "authentication_error" and details == "NOT_FOUND"


def diagnose(err: BaseException) -> dict:
    """{code, title, fix} for a failed credential check."""
    status, code, details = _error_fields(err)
    text = str(err)
    low = text.lower()

    def out(c: str, title: str, fix: str, **extra: Any) -> dict:
        return {"code": c, "title": title, "fix": fix, **extra}

    if "credentials not set" in low or isinstance(err, FileNotFoundError):
        return out("no_credentials", "No Kalshi key is saved yet.",
                   "Paste your Key ID and private key from kalshi.com, then save.")

    if _is_not_found(err):
        return out(
            "key_not_found", "Kalshi doesn't know this Key ID.",
            f"Check you copied the whole Key ID from {SITE} (Account → API "
            f"keys), and that the key wasn't deleted there.")

    if status == 401 and code == "authentication_error" and details == "INVALID_PARAMETER":
        return out("bad_key_id", "Kalshi says the Key ID is malformed.",
                   "Copy the Key ID again from Kalshi's API keys page. It looks "
                   "like 1a2b3c4d-1a2b-1a2b-1a2b-1a2b3c4d5e6f.")

    if (status == 401 and "timestamp" in code) or (
            status is None and ("timestamp" in low or "clock" in low)):
        return out("clock_skew", "Your computer's clock is off.",
                   "Kalshi rejects signed requests stamped too far from its own "
                   "time. Turn on 'Set time automatically' in your system's date "
                   "and time settings, then test again.")

    if status == 401:
        return out("bad_signature", "The Key ID and private key don't match.",
                   "Each Key ID has its own private key file. Use the file Kalshi "
                   "gave you when you created THIS key, or create a new key and "
                   "paste both halves of it.")

    if status == 403:
        return out("forbidden", "Kalshi refused this key.",
                   "The key exists but isn't allowed to read your Kalshi "
                   "account. Create a new key on Kalshi and try again.")

    if status == 429:
        return out("rate_limited", "Kalshi asked us to slow down.",
                   "Wait a minute, then test again.")

    if status is not None and status >= 500:
        return out("kalshi_down", "Kalshi is having trouble right now.",
                   "Your key is saved. Test again in a few minutes.")

    if isinstance(err, (TypeError, ValueError)) and (
            "private key" in low or "deserialize" in low or "key file" in low):
        return out("bad_key_file", "The saved private key can't be read.",
                   "Paste the key again, or drop the key file Kalshi gave you.")

    if _is_network(err):
        return out("network", "Can't reach Kalshi.",
                   "Check your internet connection, VPN or firewall, then test "
                   "again. Your key is saved.")

    first = text.splitlines()[0][:160] if text else type(err).__name__
    return out("unknown", "Kalshi didn't accept the test.",
               f"{type(err).__name__}: {first}")
