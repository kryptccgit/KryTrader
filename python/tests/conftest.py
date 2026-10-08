import pytest

import kalshi_auth


@pytest.fixture(autouse=True)
def _reset_server_offset():
    """server_now() is local time + measured Kalshi offset; clock-sync tests
    set the offset and would silently skew every close-time guard in later
    tests. Pin it to zero around each test."""
    old = kalshi_auth._server_offset_ms
    kalshi_auth._server_offset_ms = 0
    yield
    kalshi_auth._server_offset_ms = old


@pytest.fixture(autouse=True)
def _live_scope_unless_a_test_says_paper():
    """The backend starts in Paper (kalshi_auth.DEFAULT_ENV) — test_paper_mode
    pins that. Most engine tests exercise the LIVE order path with Kalshi
    mocked out, so each test starts in the production scope and a paper test
    switches to paper itself. Restored afterwards so no test leaks its scope
    into the next."""
    old = kalshi_auth._current_env
    kalshi_auth._current_env = kalshi_auth.PRODUCTION
    yield
    kalshi_auth._current_env = old


@pytest.fixture(autouse=True)
def _fresh_paper_book_memory():
    """paper_exchange remembers, per ticker, which book it last applied and
    how much of each real level paper orders already took. Tests reuse
    tickers, so one test's memory must not gate the next one's fills."""
    import paper_exchange
    paper_exchange._last_applied.clear()
    paper_exchange._consumed.clear()
    yield
    paper_exchange._last_applied.clear()
    paper_exchange._consumed.clear()


@pytest.fixture(autouse=True)
def _fresh_agent_rate_buckets():
    """Each agent has its own per-minute bucket. Fixtures clear the shared
    `_hits`; a whole suite of Default-agent calls inside one minute must not
    trip a later test's rate limit through the per-agent one."""
    import sys
    m = sys.modules.get("mcp_server")
    if m is not None:
        m._agent_hits.clear()
    yield
