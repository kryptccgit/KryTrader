from __future__ import annotations

import pytest

import kalshi_auth as ka
from config import DEFAULT_CONFIG, merge_with_defaults




def test_oversized_fraction_is_clamped():
    assert merge_with_defaults({"max_size_fraction": 5.0})["max_size_fraction"] == 1.0
    assert merge_with_defaults({"min_cash_reserve_fraction": -2})["min_cash_reserve_fraction"] == 0.0


def test_entry_price_cents_clamped_and_ordered():
    c = merge_with_defaults({"min_entry_price_cents": 80, "max_entry_price_cents": 20})
    assert c["min_entry_price_cents"] == 20 and c["max_entry_price_cents"] == 80
    assert merge_with_defaults({"max_entry_price_cents": 500})["max_entry_price_cents"] == 99


def test_min_size_cannot_exceed_max_size():
    c = merge_with_defaults({"min_size_fraction": 0.5, "max_size_fraction": 0.1})
    assert c["min_size_fraction"] <= c["max_size_fraction"]


def test_stop_loss_forced_nonpositive_take_profit_nonnegative():
    assert merge_with_defaults({"stop_loss_on_day": 50})["stop_loss_on_day"] == -50.0
    assert merge_with_defaults({"stop_loss_on_day": -50})["stop_loss_on_day"] == -50.0
    assert merge_with_defaults({"stop_loss_on_day": 0})["stop_loss_on_day"] == 0.0
    assert merge_with_defaults({"stop_loss_on_day_pct": -0.1})["stop_loss_on_day_pct"] == 0.1
    assert merge_with_defaults({"take_profit_on_day": -10})["take_profit_on_day"] == 0.0


def test_garbage_value_falls_back_to_default():
    assert merge_with_defaults({"max_size_fraction": "abc"})["max_size_fraction"] == \
        DEFAULT_CONFIG["max_size_fraction"]


def test_crypto15m_knobs_clamped():
    c = merge_with_defaults({"crypto15m_entry_threshold": 1.5, "crypto15m_order_size": 0})
    assert c["crypto15m_entry_threshold"] == 1.0
    assert c["crypto15m_order_size"] == 1


def test_crypto15m_maker_and_hours_knobs_clamped():
    c = merge_with_defaults({
        "crypto15m_entry_style": "yolo",
        "crypto15m_maker_cancel_min": 99,
        "crypto15m_hours_start_utc": -5,
        "crypto15m_hours_end_utc": 99,
    })
    assert c["crypto15m_entry_style"] == "maker"
    assert c["crypto15m_maker_cancel_min"] == 15.0
    assert c["crypto15m_hours_start_utc"] == 0
    assert c["crypto15m_hours_end_utc"] == 24


def test_camelcase_keys_still_clamped():
    assert merge_with_defaults({"maxSizeFraction": 9.0})["max_size_fraction"] == 1.0




def test_dpapi_roundtrip():
    if not ka._dpapi_available():
        pytest.skip("DPAPI is Windows-only")
    enc = ka._dpapi_encrypt(b"super-secret")
    assert enc != b"super-secret"
    assert ka._dpapi_decrypt(enc) == b"super-secret"


def test_credentials_encrypted_at_rest(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    monkeypatch.setenv("KRYPT_TRADER_USERDATA", str(tmp_path))
    ka.reset_credential_cache()
    ka.set_env("demo")

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    ka.save_credentials("my-api-key-uuid", pem, "demo")

    assert ka._load_api_key() == "my-api-key-uuid"
    assert ka._load_private_key() is not None

    raw = ka._env_api_key_file("demo").read_bytes()
    if ka._dpapi_available():
        assert raw.startswith(ka._DPAPI_MARKER)
        assert b"my-api-key-uuid" not in raw

    ka.reset_credential_cache()


def _pkcs8_pem(key) -> str:
    from cryptography.hazmat.primitives import serialization
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def test_ed25519_key_saves_and_signs(tmp_path, monkeypatch):
    # Kalshi's web app has generated Ed25519 keys by default since 2026-10-01;
    # an RSA-only loader refused every new user's key.
    import base64
    from cryptography.hazmat.primitives.asymmetric import ed25519

    monkeypatch.setenv("KRYPT_TRADER_USERDATA", str(tmp_path))
    ka.reset_credential_cache()
    ka.set_env("demo")
    monkeypatch.setattr(ka, "now_ms", lambda: 1700000000000)

    key = ed25519.Ed25519PrivateKey.generate()
    ka.save_credentials("ed-key-uuid", _pkcs8_pem(key), "demo")

    h = ka.sign_headers("get", "/trade-api/v2/portfolio/balance")
    assert h["KALSHI-ACCESS-KEY"] == "ed-key-uuid"
    # Same pre-sign text as RSA, signed directly: verify() raises on mismatch.
    key.public_key().verify(
        base64.b64decode(h["KALSHI-ACCESS-SIGNATURE"]),
        b"1700000000000GET/trade-api/v2/portfolio/balance",
    )

    st = ka.credentials_status("demo")
    assert st["hasRsaKey"] and st["keyType"] == "ed25519"
    assert len(st["fingerprint"]) == 8
    ka.reset_credential_cache()


def test_rsa_key_still_signs_pss(tmp_path, monkeypatch):
    import base64
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    monkeypatch.setenv("KRYPT_TRADER_USERDATA", str(tmp_path))
    ka.reset_credential_cache()
    ka.set_env("demo")
    monkeypatch.setattr(ka, "now_ms", lambda: 1700000000000)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ka.save_credentials("rsa-key-uuid", _pkcs8_pem(key), "demo")
    h = ka.sign_headers("GET", "/trade-api/v2/portfolio/balance")
    key.public_key().verify(
        base64.b64decode(h["KALSHI-ACCESS-SIGNATURE"]),
        b"1700000000000GET/trade-api/v2/portfolio/balance",
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256().digest_size),
        hashes.SHA256(),
    )
    assert ka.credentials_status("demo")["keyType"] == "rsa"
    ka.reset_credential_cache()


def test_other_key_types_are_refused(tmp_path, monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import ec

    monkeypatch.setenv("KRYPT_TRADER_USERDATA", str(tmp_path))
    ka.reset_credential_cache()
    key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(ValueError, match="RSA or Ed25519"):
        ka.save_credentials("x", _pkcs8_pem(key), "demo")
