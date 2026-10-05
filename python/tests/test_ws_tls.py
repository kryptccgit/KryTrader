from __future__ import annotations

import os
import re
import ssl

import pytest

PY_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _modules_opening_websockets() -> list[str]:
    found = []
    for name in sorted(os.listdir(PY_DIR)):
        if not name.endswith(".py") or name == "ws_ssl.py":
            continue
        path = os.path.join(PY_DIR, name)
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        if "websockets.connect(" in src:
            found.append(name)
    return found


def test_some_module_actually_opens_a_websocket():
    assert _modules_opening_websockets(), "no websockets.connect() call sites found"


@pytest.mark.parametrize("module", _modules_opening_websockets())
def test_websocket_client_passes_certifi_context(module):
    with open(os.path.join(PY_DIR, module), encoding="utf-8") as fh:
        src = fh.read()
    assert "ws_ssl" in src, (
        module + " opens a websocket but never imports ws_ssl -- its handshakes "
        "will fail on every frozen macOS build. Pass "
        "ssl=ws_ssl.client_context()."
    )
    assert re.search(r"ssl=ws_ssl[.]client_context[(][)]", src), (
        module + " imports ws_ssl but no websockets.connect() call passes "
        "ssl=ws_ssl.client_context()."
    )


def test_client_context_is_a_verifying_context_with_real_roots():
    import ws_ssl

    ctx = ws_ssl.client_context()
    assert ctx is not None, "certifi missing -- client_context() fell back to None"
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert ctx.cert_store_stats()["x509_ca"] > 0, "context loaded zero CA roots"


def test_client_context_is_cached():
    import ws_ssl

    assert ws_ssl.client_context() is ws_ssl.client_context()


def test_certifi_is_a_direct_requirement():
    with open(os.path.join(PY_DIR, "requirements.txt"), encoding="utf-8") as fh:
        reqs = fh.read()
    assert re.search(r"^certifi", reqs, re.M), "certifi is not a direct requirement"
