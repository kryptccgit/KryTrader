"""What a user reads when Kalshi refuses an order.

The real-key smoke test of 6.4.0 sent one 1c order and got back
`Kalshi rejected the order: HTTP 403: {'error': {'code': 'Your_location_attestation
_for_API_trading_is_missing_or_expired...` — a Python dict repr in a toast. Kalshi
wrote a perfectly good sentence; the app wrapped it in transport noise. And the
one thing that rejection needs (verify your location on Kalshi) is nothing a
setting here can do, so it gets its own instruction.
"""
from __future__ import annotations

import kalshi_api
from kalshi_api import KalshiAPIError, rejection_text

LOCATION = {"error": {
    "code": "Your_location_attestation_for_API_trading_is_missing_or_expired._Please_verify_your_location_in_the_Kalshi_app_or_website,_and_then_retry.",
    "message": "Your location attestation for API trading is missing or expired. Please verify your location in the Kalshi app or website, and then retry.",
}}


def test_location_attestation_is_an_instruction_not_a_403():
    msg = rejection_text(KalshiAPIError(403, LOCATION))
    assert msg == kalshi_api.LOCATION_ATTESTATION_HELP
    assert "HTTP" not in msg and "{" not in msg
    assert "Nothing was placed" in msg


def test_kalshis_own_message_is_used():
    err = KalshiAPIError(400, {"error": {"code": "market_closed", "message": "Market is closed"}})
    assert rejection_text(err) == "Market is closed."


def test_no_message_falls_back_to_status_and_code():
    assert rejection_text(KalshiAPIError(400, {"error": {"code": "invalid_order"}})) == "HTTP 400 (invalid_order)"
    assert rejection_text(KalshiAPIError(502, "bad gateway")) == "HTTP 502"


def test_non_kalshi_errors_pass_through():
    assert rejection_text(ValueError("count must be positive")) == "count must be positive"
