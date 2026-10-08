"""First-run Kalshi key setup: Ed25519 keys, and failures that say what to do.

Keys here are generated at test time and thrown away; nothing key-shaped is
committed.
"""
from __future__ import annotations

import asyncio
import base64

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa

import kalshi_api
import kalshi_auth as ka
import kalshi_key_check as kc

KEY_ID = "0f1e2d3c-4b5a-4968-8776-a5b4c3d2e1f0"


def _pem(key, fmt) -> str:
    return key.private_bytes(serialization.Encoding.PEM, fmt,
                             serialization.NoEncryption()).decode()


@pytest.fixture
def creds_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("KRYPT_TRADER_USERDATA", str(tmp_path))
    ka.reset_credential_cache()
    old = ka.get_env()
    ka.set_env("production")
    yield tmp_path
    ka.set_env(old)
    ka.reset_credential_cache()


def _api_err(status, code, details=None):
    body = {"error": {"code": code, "message": "x"}}
    if details:
        body["error"]["details"] = details
    return kalshi_api.KalshiAPIError(status, body)



def test_ed25519_key_saves_and_signs_the_documented_way(creds_dir):
    """Kalshi's key page creates Ed25519 by default. Before this, saving one
    failed with "not an RSA private key"."""
    key = ed25519.Ed25519PrivateKey.generate()
    ka.save_credentials(KEY_ID, _pem(key, serialization.PrivateFormat.PKCS8))
    h = ka.sign_headers("GET", "/trade-api/v2/portfolio/balance")
    assert h["KALSHI-ACCESS-KEY"] == KEY_ID
    msg = (h["KALSHI-ACCESS-TIMESTAMP"] + "GET/trade-api/v2/portfolio/balance").encode()
    key.public_key().verify(base64.b64decode(h["KALSHI-ACCESS-SIGNATURE"]), msg)
    st = ka.credentials_status()
    assert st["keyType"] == "ed25519" and len(st["fingerprint"]) == 8


def test_rsa_still_signs_pss_sha256_and_keeps_its_fingerprint(creds_dir):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ka.save_credentials(KEY_ID, _pem(key, serialization.PrivateFormat.TraditionalOpenSSL))
    h = ka.sign_headers("GET", "/p")
    msg = (h["KALSHI-ACCESS-TIMESTAMP"] + "GET/p").encode()
    key.public_key().verify(
        base64.b64decode(h["KALSHI-ACCESS-SIGNATURE"]), msg,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32), hashes.SHA256())
    st = ka.credentials_status()
    import hashlib
    want = hashlib.sha256(str(key.public_key().public_numbers().n).encode()).hexdigest()[:8].upper()
    assert st["fingerprint"] == want and st["keyType"] == "rsa"


def test_encrypted_key_is_refused_in_words(creds_dir):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    enc = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.BestAvailableEncryption(b"pw")).decode()
    with pytest.raises(ValueError, match="password-protected"):
        ka.save_credentials(KEY_ID, enc)


def test_load_env_credentials_leaves_env_and_cache_alone(creds_dir):
    """The key test runs in Paper too, and must not flip the app to production
    to do it: it reads the pair straight from disk."""
    key = ed25519.Ed25519PrivateKey.generate()
    ka.save_credentials(KEY_ID, _pem(key, serialization.PrivateFormat.PKCS8))
    ka.set_env("paper")
    ka.reset_credential_cache()
    kid, loaded = ka.load_env_credentials("production")
    assert kid == KEY_ID and isinstance(loaded, ed25519.Ed25519PrivateKey)
    assert ka.get_env() == "paper"
    assert ka._cached_api_key is None and ka._cached_private_key is None
    with pytest.raises(ValueError):
        ka.load_env_credentials("demo")


def test_there_is_one_key_slot_and_no_demo_slot(creds_dir):
    key = ed25519.Ed25519PrivateKey.generate()
    with pytest.raises(ValueError):
        ka.save_credentials(KEY_ID, _pem(key, serialization.PrivateFormat.PKCS8), "demo")
    ka.save_credentials(KEY_ID, _pem(key, serialization.PrivateFormat.PKCS8))
    assert set(ka.credentials_status_all()) == {"current", "production"}
    assert ka.credentials_present() and not ka.credentials_present("demo")
    assert not ka.credentials_present("paper")
    with pytest.raises(ValueError):
        ka.set_env("demo")


def test_paper_signs_nothing_even_with_a_key_saved(creds_dir):
    key = ed25519.Ed25519PrivateKey.generate()
    ka.save_credentials(KEY_ID, _pem(key, serialization.PrivateFormat.PKCS8))
    ka.set_env("paper")
    with pytest.raises(ka.PaperModeError):
        ka.sign_headers("GET", "/trade-api/v2/portfolio/balance")
    with pytest.raises(ka.PaperModeError):
        ka.prime_credentials(sync_time=False)



def test_not_found_is_key_not_found_and_points_at_kalshi_com():
    e = _api_err(401, "authentication_error", "NOT_FOUND")
    d = kc.diagnose(e)
    assert d["code"] == "key_not_found"
    assert "kalshi.com" in d["fix"]
    assert "demo" not in (d["title"] + d["fix"]).lower()


def test_malformed_key_id():
    d = kc.diagnose(_api_err(401, "authentication_error", "INVALID_PARAMETER"))
    assert d["code"] == "bad_key_id"


def test_other_401_is_a_mismatched_pair():
    e = _api_err(401, "authentication_error", "INVALID_SIGNATURE")
    assert kc.diagnose(e)["code"] == "bad_signature"


def test_clock_skew_says_fix_the_clock():
    d = kc.diagnose(_api_err(401, "header_timestamp_expired"))
    assert d["code"] == "clock_skew" and "time automatically" in d["fix"]


def test_network_failures():
    for err in (httpx.ConnectError("boom"), httpx.ReadTimeout("slow"),
                OSError("getaddrinfo failed")):
        assert kc.diagnose(err)["code"] == "network", err


def test_server_side_and_throttle_and_forbidden():
    assert kc.diagnose(_api_err(503, "x"))["code"] == "kalshi_down"
    assert kc.diagnose(_api_err(429, "x"))["code"] == "rate_limited"
    assert kc.diagnose(_api_err(403, "x"))["code"] == "forbidden"


def test_missing_credentials():
    d = kc.diagnose(RuntimeError("Kalshi credentials not set"))
    assert d["code"] == "no_credentials"



def test_verify_credentials_failure_is_an_answer(monkeypatch):
    import service

    async def fail(_p):
        raise _api_err(401, "header_timestamp_expired")

    monkeypatch.setattr(service, "_h_testCredentials", fail)
    out = asyncio.run(service._h_verifyCredentials({}))
    assert out["ok"] is False and out["code"] == "clock_skew"


def test_verify_credentials_success(monkeypatch):
    import service

    async def good(_p):
        return {"env": "production", "balanceUsd": 12.5}

    monkeypatch.setattr(service, "_h_testCredentials", good)
    assert asyncio.run(service._h_verifyCredentials({})) == {
        "ok": True, "env": "production", "balanceUsd": 12.5}


def test_the_key_test_in_paper_signs_one_read_without_flipping_the_app(monkeypatch, creds_dir):
    """Checking a key is the step before going Live, so it works in Paper —
    through verify_saved_key, which signs with the saved pair directly. The
    global scope stays 'paper' throughout, and the backend stays authed."""
    import service
    key = ed25519.Ed25519PrivateKey.generate()
    ka.save_credentials(KEY_ID, _pem(key, serialization.PrivateFormat.PKCS8))
    ka.set_env("paper")
    seen = []

    async def verify():
        seen.append(ka.get_env())
        return {"balance": 100, "total_balance_cents": 1234}

    monkeypatch.setattr(kalshi_api, "verify_saved_key", verify)
    service.STATE.auth_ok = True
    out = asyncio.run(service._h_testCredentials({}))
    assert out == {"env": "production", "balanceUsd": 12.34}
    assert seen == ["paper"] and ka.get_env() == "paper"
    assert service.STATE.auth_ok is True


def test_ai_status_publishes_only_real_prices():
    import ai_analyst
    prices = ai_analyst.status({})["prices"]
    assert set(prices) == set(ai_analyst.PRICING)
    for m, (i, o) in ai_analyst.PRICING.items():
        assert prices[m] == {"inPerMTok": i, "outPerMTok": o}
