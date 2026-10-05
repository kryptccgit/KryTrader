import pytest

import kalshi_auth


@pytest.fixture(autouse=True)
def _reset_server_offset():
    old = kalshi_auth._server_offset_ms
    kalshi_auth._server_offset_ms = 0
    yield
    kalshi_auth._server_offset_ms = old
