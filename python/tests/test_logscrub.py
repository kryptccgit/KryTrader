"""Credentials must never reach a log.

A beta user pasting their log into a chat window is the most likely way a
secret escapes this app — and it escapes to exactly the people trying to help.
So this tests the real logging path, not just the regexes: a record logged on a
CHILD logger has to come out of the handler scrubbed.
"""
from __future__ import annotations

import io
import logging

import logscrub

DISCORD = "N0tAR3alD1scordBotToken1" + "." + "F4k3Ts" + "." + "n0tAR3alHmacSignatureXXXXXXXXX"
TELEGRAM = "1234567890" + ":" + "N0tAR3alT3l3gramBotTokenXXXXXXXXXX"


def setup_function():
    logscrub.set_known_secrets([])



def test_a_discord_token_is_redacted_even_if_never_registered():
    out = logscrub.scrub(f"connecting with {DISCORD} now")
    assert DISCORD not in out
    assert logscrub.REDACTED in out


def test_a_telegram_token_is_redacted_even_if_never_registered():
    out = logscrub.scrub(f"getMe failed for {TELEGRAM}")
    assert TELEGRAM not in out


def test_a_telegram_token_in_a_url_path_is_redacted():
    out = logscrub.scrub(
        f"POST https://api.telegram.org/bot{TELEGRAM}/getUpdates -> 200")
    assert TELEGRAM not in out
    assert "api.telegram.org/bot" in out


def test_a_private_key_block_is_redacted():
    pem = ("-----BEGIN RSA PRIVATE KEY-----\n"
           "MIIEowIBAAKCAQEAxxxxxxxxxxxxxxxxxxxx\n"
           "-----END RSA PRIVATE KEY-----")
    out = logscrub.scrub(f"loaded key: {pem}")
    assert "MIIEow" not in out
    assert logscrub.REDACTED in out


def test_authorization_headers_are_redacted():
    out = logscrub.scrub("headers: Authorization: Bot abcdef.ghijkl.mnopqr")
    assert "abcdef.ghijkl.mnopqr" not in out



def test_a_registered_secret_is_redacted_in_any_context():
    key = "e1f2a3b4-c5d6-7890-abcd-ef1234567890"
    logscrub.set_known_secrets([key])
    out = logscrub.scrub(f"signing request with key={key} for /portfolio")
    assert key not in out
    assert "/portfolio" in out


def test_longer_secrets_are_redacted_before_shorter_ones():
    logscrub.set_known_secrets(["abcdef123456", "abcdef123456789012"])
    out = logscrub.scrub("token=abcdef123456789012")
    assert "789012" not in out


def test_trivially_short_values_are_not_registered():
    logscrub.set_known_secrets(["demo", "abc"])
    assert logscrub.scrub("running on demo env") == "running on demo env"



def test_order_ids_survive():
    """Kalshi order ids are UUIDs and are the single most useful thing in a
    trading log. Blanket-redacting UUIDs would make every bug report
    unreadable to protect nothing — the API key is caught by value."""
    line = "order 0720ec42-ea21-b6b6-87ac-c5b4e2732435 filled 10 @ 45c"
    assert logscrub.scrub(line) == line


def test_ordinary_trading_lines_are_untouched():
    line = "[terminal] manual order buy 10 YES KXBTCD-26AUG24-T90000 @ 45c"
    assert logscrub.scrub(line) == line


def test_empty_and_none_are_safe():
    assert logscrub.scrub("") == ""
    assert logscrub.scrub(None) is None



def test_a_child_loggers_record_is_scrubbed_at_the_handler():
    """The bug this pins: a Filter attached to the ROOT LOGGER only runs for
    records created by that logger. Records from logging.getLogger("trader")
    propagate straight to the root's handlers without passing it — so the
    filter has to live on the HANDLERS."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(logscrub.ScrubFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        logging.getLogger("remote.telegram").warning(
            "token rejected: %s", TELEGRAM)
        handler.flush()
        out = stream.getvalue()
    finally:
        root.removeHandler(handler)

    assert TELEGRAM not in out
    assert logscrub.REDACTED in out
    assert "token rejected" in out


def test_a_secret_passed_as_a_lazy_arg_is_still_scrubbed():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(logscrub.ScrubFilter())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        logging.getLogger("kalshi_api").info("auth header %s", DISCORD)
        handler.flush()
        out = stream.getvalue()
    finally:
        root.removeHandler(handler)
    assert DISCORD not in out
