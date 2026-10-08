"""Pre-release audit (v6), the RPC surface the app reads.

  * positions were every book's at once: the Dashboard's open positions and
    "Recent resolutions" mixed paper and live rows with nothing saying which;
  * an RPC failure reached the user as "KeyError: 'x'" — words go in `error`,
    the class in `code`;
  * an AI provider nobody set up read as "needs attention" in Connections;
  * a hand-placed row's edge was a confident 0 nobody produced (invariant 1);
  * capturetrail was in the bundle only by luck of static analysis.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import ai_analyst
import db
import kalshi_auth
import service
import terminal


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "db_path", lambda: tmp_path / "svc.db")
    db.init_db()


def _row(ticker: str, env: str, *, resolved: bool = False) -> None:
    terminal.record_manual_buy(ticker=ticker, side="yes", count=1, price_cents=40,
                               client_order_id=f"c-{ticker}", order_id=f"o-{ticker}",
                               status="executed", filled=1, avg_cents=40.0, fees_usd=0.01,
                               env=env)
    if resolved:
        with db.get_db() as conn:
            conn.execute("UPDATE bot_positions SET resolved=1, pnl_usd=0.6, "
                         "resolved_at=datetime('now') WHERE ticker=?", (ticker,))



def test_positions_are_the_current_books_unless_asked(fresh_db, monkeypatch):
    _row("KXP-1", "paper")
    _row("KXL-1", "production", resolved=True)
    _row("KXD-1", "demo", resolved=True)
    monkeypatch.setattr(kalshi_auth, "_current_env", "paper", raising=False)
    rows = run(service._h_positions({}))
    assert [(r["ticker"], r["kalshiEnv"]) for r in rows] == [("KXP-1", "paper")]
    monkeypatch.setattr(kalshi_auth, "_current_env", "production", raising=False)
    rows = run(service._h_positions({"resolved": True}))
    assert [(r["ticker"], r["kalshiEnv"]) for r in rows] == [("KXL-1", "production")]
    assert [r["ticker"] for r in run(service._h_positions({"env": "demo"}))] == ["KXD-1"]
    assert {r["kalshiEnv"] for r in run(service._h_positions({"env": "all"}))} == \
        {"paper", "production", "demo"}
    with pytest.raises(ValueError):
        run(service._h_positions({"env": "https://elsewhere"}))



def test_a_manual_rows_edge_is_absent_not_zero(fresh_db):
    _row("KXM-1", "paper")
    with db.get_db() as conn:
        r = dict(conn.execute("SELECT * FROM bot_positions WHERE ticker='KXM-1'").fetchone())
    assert r["edge_pts"] == 0.0
    assert service._position_row_to_js(r)["edgePts"] is None
    bot = dict(r, signal_source="whale", edge_pts=3.5)
    assert service._position_row_to_js(bot)["edgePts"] == 3.5
    assert service._position_row_to_js(dict(bot, edge_pts=None))["edgePts"] is None



@pytest.mark.parametrize("exc,words", [
    (KeyError("ticker"), "Missing value: ticker"),
    (TimeoutError(), "Timed out"),
    (ValueError("id required"), "id required"),
    (RuntimeError(""), "Something went wrong"),
])
def test_an_rpc_failure_is_words_with_the_class_as_a_code(monkeypatch, exc, words):
    sent = []

    async def _send(obj):
        sent.append(obj)

    async def _boom(_p):
        raise exc
    monkeypatch.setattr(service, "_send", _send)
    monkeypatch.setitem(service._HANDLERS, "auditBoom", _boom)
    run(service._dispatch_request({"id": "r1", "method": "auditBoom", "params": {}}))
    out = sent[-1]
    assert out["ok"] is False and out["code"] == type(exc).__name__
    assert out["error"].startswith(words)
    assert type(exc).__name__ not in out["error"]


def test_an_rpc_error_message_is_scrubbed_like_a_log_line(monkeypatch):
    import logscrub
    secret = "kt_" + "Q" * 40
    monkeypatch.setattr(logscrub, "scrub", lambda s: s.replace(secret, "[redacted]"))
    assert secret not in service.human_error(RuntimeError(f"bad token {secret}"))



def test_an_unconfigured_ai_provider_is_not_set_up_unless_autopilot_waits(monkeypatch):
    monkeypatch.setattr(ai_analyst, "has_key", lambda p: False)

    def _active(rows):
        return next(r for r in rows if r["id"] == "ai:anthropic")
    rows = run(service._health_ai(False, {"ai_provider": "anthropic"}))
    assert _active(rows)["status"] == "off" and _active(rows)["detail"] == "Not set up."
    assert all(r["status"] == "off" for r in rows)
    rows = run(service._health_ai(False, {"ai_provider": "anthropic",
                                          "autopilot_enabled": True}))
    assert _active(rows)["status"] == "warn"



def test_capturetrail_is_pinned_in_the_build_and_the_selftest():
    build = (Path(__file__).resolve().parents[2] / "scripts" / "build-python.mjs").read_text(
        encoding="utf-8")
    assert "'--hidden-import', 'capturetrail'" in build
    import inspect
    assert '"capturetrail"' in inspect.getsource(service._selftest)
