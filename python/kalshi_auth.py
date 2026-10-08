from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
import sys
import threading
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional, Union

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, padding, rsa


logger = logging.getLogger(__name__)



_DPAPI_MARKER = b"#KRYPT-DPAPI-v1\n"
_warned_plaintext = False


def _dpapi_available() -> bool:
    return sys.platform == "win32"


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_char))]

    def _to_blob(data: bytes) -> "_DATA_BLOB":
        buf = ctypes.create_string_buffer(bytes(data), len(data))
        return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _from_blob(blob: "_DATA_BLOB") -> bytes:
        try:
            return ctypes.string_at(blob.pbData, blob.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob.pbData)

    def _dpapi_encrypt(data: bytes) -> bytes:
        out = _DATA_BLOB()
        blob_in = _to_blob(data)
        if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(out)
        ):
            raise OSError("CryptProtectData failed")
        return _from_blob(out)

    def _dpapi_decrypt(data: bytes) -> bytes:
        out = _DATA_BLOB()
        blob_in = _to_blob(data)
        if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(out)
        ):
            raise OSError("CryptUnprotectData failed")
        return _from_blob(out)
else:
    def _dpapi_encrypt(data: bytes) -> bytes:
        raise OSError("DPAPI not available")

    def _dpapi_decrypt(data: bytes) -> bytes:
        raise OSError("DPAPI not available")


def _restrict_dir(d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    if sys.platform != "win32":
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass


def _atomic_write_0600(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_BINARY", 0)
    fd = os.open(str(tmp), flags, 0o600)
    try:
        mv = memoryview(data)
        while mv:
            mv = mv[os.write(fd, mv):]
    finally:
        os.close(fd)
    if sys.platform != "win32":
        for p in (tmp, path):
            try:
                os.chmod(p, 0o600)
            except OSError:
                pass
    os.replace(str(tmp), str(path))
    if sys.platform != "win32":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _write_secret_bytes(path: Path, data: bytes) -> None:
    global _warned_plaintext
    _restrict_dir(path.parent)
    if _dpapi_available():
        try:
            _atomic_write_0600(path, _DPAPI_MARKER + base64.b64encode(_dpapi_encrypt(data)))
            return
        except Exception as e:
            logger.warning(f"DPAPI encrypt failed, storing plaintext (0600): {e}")
    if not _warned_plaintext:
        logger.warning(
            "Credentials stored UNENCRYPTED (no OS keystore on this platform); "
            "files restricted to your user (0600). Use a single-user machine."
        )
        _warned_plaintext = True
    _atomic_write_0600(path, data)


def _read_secret_bytes(path: Path, upgrade: bool = True) -> bytes:
    raw = path.read_bytes()
    if raw.startswith(_DPAPI_MARKER):
        return _dpapi_decrypt(base64.b64decode(raw[len(_DPAPI_MARKER):]))
    if upgrade and _dpapi_available():
        try:
            _write_secret_bytes(path, raw)
        except Exception:
            pass
    return raw


def _credentials_dir() -> Path:
    base = os.environ.get("KRYPT_TRADER_USERDATA")
    if base:
        return Path(base) / "credentials"
    return Path(__file__).resolve().parent / "credentials"




def _named_secret_file(name: str) -> Path:
    safe = "".join(c for c in name if c.isalnum() or c in "-_")
    return _credentials_dir() / f"secret.{safe}.txt"


def save_secret(name: str, value: str) -> None:
    """Store an arbitrary credential with the same protection as the API keys:
    DPAPI-encrypted on Windows, 0600 elsewhere, atomic write.

    Used for the Discord and Telegram bot tokens. A bot token is a credential —
    it belongs beside the others, not in settings.json where every profile
    export and backup would carry it."""
    d = _credentials_dir()
    _restrict_dir(d)
    v = (value or "").strip()
    if not v:
        raise ValueError("empty secret")
    _write_secret_bytes(_named_secret_file(name), (v + chr(10)).encode("utf-8"))


def read_secret(name: str) -> Optional[str]:
    path = _named_secret_file(name)
    if not path.exists():
        return None
    try:
        return _read_secret_bytes(path).decode("utf-8").strip() or None
    except Exception as e:
        logger.warning(f"could not read secret {name}: {e}")
        return None


def clear_secret(name: str) -> None:
    path = _named_secret_file(name)
    if path.exists():
        try:
            path.unlink()
        except Exception:
            pass


def has_secret(name: str) -> bool:
    return _named_secret_file(name).exists()


def list_secret_names(prefix: str) -> list[str]:
    """Names of the stored secrets that start with `prefix` — the per-agent
    MCP tokens (mcp_token_<id>), whose ids live in config, not here. Read by
    logscrub (so every agent's token is redacted, not only Default's) and by
    the token pruner (so a deleted agent's token is removed from disk)."""
    d = _credentials_dir()
    safe = "".join(c for c in prefix if c.isalnum() or c in "-_")
    if not d.exists():
        return []
    out = []
    for p in d.glob(f"secret.{safe}*.txt"):
        name = p.name[len("secret."):-len(".txt")]
        if name.startswith(safe):
            out.append(name)
    return sorted(out)


PRODUCTION = "production"
PAPER = "paper"
_ENVS = (PRODUCTION, PAPER)


class PaperModeError(RuntimeError):
    """A signed Kalshi request was attempted while the app is in Paper mode.
    Raised before any key is read, so a paper session can never reach the
    user's real account by any path that signs."""


def _env_api_key_file(env: str) -> Path:
    return _credentials_dir() / f"apikey.{env}.txt"


def _env_rsa_key_file(env: str) -> Path:
    return _credentials_dir() / f"rsakey.{env}.pem"


def _api_key_file(env: Optional[str] = None) -> Path:
    return _env_api_key_file(PRODUCTION)


def _rsa_key_file(env: Optional[str] = None) -> Path:
    return _env_rsa_key_file(PRODUCTION)


_SERVER_BASES = {
    PRODUCTION: "https://api.elections.kalshi.com",
}

SigningKey = Union[rsa.RSAPrivateKey, ed25519.Ed25519PrivateKey]
_SIGNING_KEY_TYPES = (rsa.RSAPrivateKey, ed25519.Ed25519PrivateKey)

_cached_api_key: Optional[str] = None
_cached_private_key: Optional[SigningKey] = None
_server_offset_ms: int = 0


def server_now() -> float:
    """Kalshi-server epoch seconds: local clock corrected by the measured
    signing offset. Every money-relevant time comparison (seconds-to-close
    guards, entry windows, settlement-print attribution) must use THIS, not
    time.time() — a consumer Windows box 20-30s slow turns "12s to close"
    into 2s and recreates the T-2s entry bug straight through its fix."""
    import time as _time
    return _time.time() + _server_offset_ms / 1000.0
_last_sync: float = 0.0
_RESYNC_INTERVAL_SEC = 300
_sync_lock = threading.Lock()
_sync_in_progress: bool = False

DEFAULT_ENV = PAPER
_current_env: str = DEFAULT_ENV

ENV_LOCK = asyncio.Lock()


def set_env(env: str) -> None:
    global _current_env, _last_sync
    if env not in _ENVS:
        raise ValueError(f"unknown env: {env}")
    if env != _current_env:
        _current_env = env
        _last_sync = 0.0


def get_env() -> str:
    return _current_env


def is_paper(env: Optional[str] = None) -> bool:
    return (env or _current_env) == PAPER


def _server_time_url() -> str:
    return f"{_SERVER_BASES[PRODUCTION]}/trade-api/v2/exchange/status"


def reset_credential_cache() -> None:
    global _cached_api_key, _cached_private_key
    _cached_api_key = None
    _cached_private_key = None


def _parse_api_key_text(text: str) -> Optional[str]:
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line and not line.startswith("---"):
            _, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            if val:
                return val
        else:
            return line
    return None


def _load_api_key() -> str:
    global _cached_api_key
    if _current_env == PAPER:
        raise PaperModeError("Paper mode: nothing is signed with your Kalshi key")
    if _cached_api_key is not None:
        return _cached_api_key
    f = _api_key_file()
    if not f.exists():
        raise FileNotFoundError(f"Kalshi API key not configured ({f})")
    val = _parse_api_key_text(_read_secret_bytes(f).decode("utf-8", "replace"))
    if not val:
        raise ValueError(f"No API key parsed from {f}")
    _cached_api_key = val
    return val


def saved_api_key_id() -> Optional[str]:
    """The saved key id, read for the log scrubber ONLY. Reading a key to
    redact it is not signing with it, so this works in Paper — where the
    first key test now always happens, and where the backend boots before the
    user's settings arrive. Never use it to sign."""
    f = _api_key_file()
    if not f.exists():
        return None
    try:
        return _parse_api_key_text(_read_secret_bytes(f, upgrade=False).decode("utf-8", "replace"))
    except Exception:
        return None


def _load_signing_key(pem_bytes: bytes) -> SigningKey:
    key = serialization.load_pem_private_key(pem_bytes, password=None)
    if not isinstance(key, _SIGNING_KEY_TYPES):
        raise TypeError("Kalshi key file is not an RSA or Ed25519 private key")
    return key


def _load_private_key() -> SigningKey:
    global _cached_private_key
    if _current_env == PAPER:
        raise PaperModeError("Paper mode: nothing is signed with your Kalshi key")
    if _cached_private_key is not None:
        return _cached_private_key
    f = _rsa_key_file()
    if not f.exists():
        raise FileNotFoundError(f"Kalshi private key not configured ({f})")
    key = _load_signing_key(_read_secret_bytes(f))
    _cached_private_key = key
    return key


def load_env_credentials(env: str = PRODUCTION) -> tuple[str, SigningKey]:
    """The saved (key id, private key), read straight from disk; the module
    cache and the global env are left alone.

    One caller: the key test the user clicks (kalshi_api.verify_saved_key).
    It signs ONE balance read with the production key without flipping the
    global env — which in Paper mode would briefly let every engine's ledger
    writes and order routing see "production" while the test ran."""
    if env != PRODUCTION:
        raise ValueError(f"unknown env: {env}")
    apk, pem = _api_key_file(env), _rsa_key_file(env)
    if not (apk.exists() and pem.exists()):
        raise FileNotFoundError("Kalshi credentials not set")
    key_id = _parse_api_key_text(_read_secret_bytes(apk).decode("utf-8", "replace"))
    if not key_id:
        raise ValueError("No API key parsed")
    return key_id, _load_signing_key(_read_secret_bytes(pem))


def key_fingerprint(key: SigningKey) -> str:
    """Eight hex characters naming a key pair without revealing it. RSA keeps
    the historical formula (sha256 of the modulus as decimal) so a fingerprint
    a user already noted down still matches."""
    if isinstance(key, rsa.RSAPrivateKey):
        n = key.public_key().public_numbers().n
        return hashlib.sha256(str(n).encode()).hexdigest()[:8].upper()
    raw = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:8].upper()


def key_type(key: SigningKey) -> str:
    return "rsa" if isinstance(key, rsa.RSAPrivateKey) else "ed25519"


def credentials_present(env: Optional[str] = None) -> bool:
    """Whether the production key pair is saved. `env` may name production
    (or be omitted); the paper scope has no credentials by definition."""
    if env not in (None, PRODUCTION):
        return False
    return _api_key_file().exists() and _rsa_key_file().exists()


def credentials_status(env: Optional[str] = None) -> dict:
    e = PRODUCTION
    apk = _api_key_file(e)
    rkf = _rsa_key_file(e)
    info = {
        "env": e,
        "hasApiKey": apk.exists(),
        "hasRsaKey": rkf.exists(),
        "apiKeyPreview": "",
        "fingerprint": "",
        "keyType": None,
    }
    if apk.exists():
        try:
            text = _read_secret_bytes(apk).decode("utf-8", "replace").strip().splitlines()[0]
            if "=" in text and not text.startswith("-"):
                _, _, text = text.partition("=")
            text = text.strip().strip('"').strip("'")
            if len(text) >= 4:
                info["apiKeyPreview"] = text[-4:]
        except Exception:
            pass
    if rkf.exists():
        try:
            key = _load_signing_key(_read_secret_bytes(rkf))
            info["fingerprint"] = key_fingerprint(key)
            info["keyType"] = key_type(key)
        except Exception:
            pass
    return info


def credentials_status_all() -> dict:
    return {
        "current": _current_env,
        "production": credentials_status(PRODUCTION),
    }


def save_credentials(api_key: str, rsa_pem: str, env: Optional[str] = None) -> None:
    if env not in (None, PRODUCTION):
        raise ValueError("Kalshi keys are saved for production only")
    e = PRODUCTION
    d = _credentials_dir()
    _restrict_dir(d)
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("API key is empty")
    try:
        key = serialization.load_pem_private_key(
            rsa_pem.encode("utf-8"), password=None
        )
    except TypeError as ex:
        raise ValueError(
            "This private key is password-protected. Use the key file exactly "
            "as Kalshi gave it to you.") from ex
    except Exception as ex:
        raise ValueError(f"The private key did not parse: {ex}") from ex
    if not isinstance(key, _SIGNING_KEY_TYPES):
        raise ValueError(
            "That is not a key type Kalshi signs with. Kalshi API keys are "
            "Ed25519 or RSA.")
    api_path = _env_api_key_file(e)
    pem_path = _env_rsa_key_file(e)
    _write_secret_bytes(api_path, (api_key + "\n").encode("utf-8"))
    _write_secret_bytes(pem_path, (rsa_pem.strip() + "\n").encode("utf-8"))
    reset_credential_cache()


def clear_credentials(env: Optional[str] = None) -> None:
    if env not in (None, PRODUCTION):
        raise ValueError("Kalshi keys are saved for production only")
    for p in (_env_api_key_file(PRODUCTION), _env_rsa_key_file(PRODUCTION)):
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
    reset_credential_cache()


def sync_server_time(force: bool = False) -> int:
    global _server_offset_ms, _last_sync
    now_local = time.time()
    if (not force) and (now_local - _last_sync) < _RESYNC_INTERVAL_SEC:
        return _server_offset_ms
    _last_sync = now_local
    try:
        with httpx.Client(timeout=5.0) as c:
            resp = c.head(_server_time_url())
            date_hdr = resp.headers.get("Date") or resp.headers.get("date")
        if date_hdr:
            server_dt = parsedate_to_datetime(date_hdr).timestamp()
            new_offset = int((server_dt - now_local) * 1000) - 750
            _server_offset_ms = new_offset
            logger.debug(f"Kalshi clock sync: offset = {new_offset} ms")
    except Exception as e:
        logger.warning(f"Kalshi clock sync failed ({e})")
    return _server_offset_ms


def _bg_sync() -> None:
    global _sync_in_progress
    try:
        sync_server_time(force=True)
    finally:
        with _sync_lock:
            _sync_in_progress = False


def now_ms() -> int:
    global _sync_in_progress
    if (time.time() - _last_sync) >= _RESYNC_INTERVAL_SEC:
        start = False
        with _sync_lock:
            if not _sync_in_progress:
                _sync_in_progress = True
                start = True
        if start:
            threading.Thread(
                target=_bg_sync, name="kalshi-clocksync", daemon=True
            ).start()
    return int(time.time() * 1000) + _server_offset_ms


def _sign_with(private_key: SigningKey, message: bytes) -> str:
    if isinstance(private_key, ed25519.Ed25519PrivateKey):
        signature = private_key.sign(message)
    else:
        signature = private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=hashes.SHA256().digest_size,
            ),
            hashes.SHA256(),
        )
    return base64.b64encode(signature).decode("ascii")


def _sign(message: bytes) -> str:
    return _sign_with(_load_private_key(), message)


def sign_headers_with(api_key: str, private_key: SigningKey,
                      method: str, path: str) -> dict[str, str]:
    """sign_headers for an explicit key pair (see load_env_credentials)."""
    ts = str(now_ms())
    message = (ts + method.upper() + path).encode("utf-8")
    return {
        "KALSHI-ACCESS-KEY": api_key,
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": _sign_with(private_key, message),
    }


def sign_headers(method: str, path: str) -> dict[str, str]:
    if _current_env == PAPER:
        raise PaperModeError("Paper mode: nothing is signed with your Kalshi key")
    ts = str(now_ms())
    message = (ts + method.upper() + path).encode("utf-8")
    return {
        "KALSHI-ACCESS-KEY": _load_api_key(),
        "KALSHI-ACCESS-TIMESTAMP": ts,
        "KALSHI-ACCESS-SIGNATURE": _sign(message),
    }


def prime_credentials(sync_time: bool = True) -> bool:
    _load_api_key()
    _load_private_key()
    if sync_time:
        sync_server_time(force=True)
    return True
