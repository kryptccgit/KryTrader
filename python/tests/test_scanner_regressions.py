from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

import db
import kalshi_api
import kalshi_ws
import scanner


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    dbfile = tmp_path / "scan-test.db"
    monkeypatch.setattr(db, "db_path", lambda: dbfile)
    db.init_db()
    return dbfile


def run_async(coro):
    return asyncio.run(coro)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")




WHALE_CFG = {
    "min_whale_usd": 2500,
    "min_entry_price_frac": 0.50,
    "max_trade_age_min": 15,
}


def _tape_trade(trade_id: str, taker_side, ticker: str = "KXTEST-A") -> dict:
    t = {
        "trade_id": trade_id,
        "ticker": ticker,
        "count_fp": 5000,
        "yes_price_dollars": 0.40,
        "no_price_dollars": 0.60,
        "created_time": _now_iso(),
    }
    if taker_side is not None:
        t["taker_side"] = taker_side
    return t


def _stub_network(monkeypatch, tape: list[dict]):
    monkeypatch.setattr(kalshi_ws, "recent_trades", lambda limit=1000: tape)

    async def _no_markets(_tickers):
        return {}

    monkeypatch.setattr(kalshi_api, "fetch_markets_map", _no_markets)

    async def _no_series(_st):
        return None

    monkeypatch.setattr(kalshi_api, "fetch_series", _no_series)


def test_scan_whales_skips_sideless_tape_rows(fresh_db, monkeypatch):
    _stub_network(monkeypatch, [
        _tape_trade("t-blank", ""),
        _tape_trade("t-missing", None),
    ])
    n, rows = run_async(scanner.scan_whales(WHALE_CFG))
    assert n == 0 and rows == []
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM whale_trades").fetchone()[0] == 0


def test_scan_whales_keeps_valid_no_side(fresh_db, monkeypatch):
    _stub_network(monkeypatch, [_tape_trade("t-no", "no")])
    n, rows = run_async(scanner.scan_whales(WHALE_CFG))
    assert n == 1
    assert rows[0]["taker_side"] == "no"
    assert rows[0]["price"] == pytest.approx(0.60)
    assert rows[0]["dollar_value"] == pytest.approx(3000.0)




MOM_CFG = {
    "contrarian_only": False,
    "allowed_momentum_signal_types": ["price_move"],
    "max_trade_age_min": 15,
}


def _market_row(yes_bid: float, volume_24h: float = 1000.0) -> dict:
    return {
        "ticker": "KXMOM-A", "event_ticker": "KXMOM", "series_ticker": "KXMOM",
        "title": "Momentum test market", "yes_sub_title": "",
        "category": "sports", "status": "open", "close_time": "",
        "volume": 5000, "volume_24h": volume_24h, "open_interest": 100,
        "yes_bid": yes_bid, "yes_ask": yes_bid + 0.02, "last_price": yes_bid,
        "result": "", "settlement_value": None,
    }


def test_momentum_baseline_is_previous_scan_not_two_back(fresh_db, monkeypatch):
    monkeypatch.setattr(kalshi_ws, "recent_trades", lambda limit=1000: [])
    with db.get_db() as conn:
        db.save_snapshot(conn, "KXMOM-A", _market_row(0.36))
        db.save_snapshot(conn, "KXMOM-A", _market_row(0.40))
        db.upsert_market(conn, _market_row(0.45))

    n, alerts = run_async(scanner.scan_momentum(MOM_CFG))
    assert n == 0 and alerts == []

    with db.get_db() as conn:
        db.upsert_market(conn, _market_row(0.55))
    n, alerts = run_async(scanner.scan_momentum(MOM_CFG))
    assert n == 1
    assert alerts[0]["signal_type"] == "price_move"
    assert alerts[0]["direction"] == "yes"
    assert alerts[0]["price_change"] == pytest.approx(10.0, abs=0.01)




def test_resolve_category_unmapped_falls_to_keyword_bucket(monkeypatch):
    async def _series(_st):
        return {"category": "Never Heard Of It"}

    monkeypatch.setattr(kalshi_api, "fetch_series", _series)
    cat = run_async(scanner._resolve_category("KXFOO-BAR", "Will the Fed cut rates?"))
    assert cat == "economics"
    cat = run_async(scanner._resolve_category("KXFOO-BAR", "nothing recognizable"))
    assert cat == "world"


def test_resolve_category_exotics_is_first_class(monkeypatch):
    async def _series(_st):
        return {"category": "Exotics"}

    monkeypatch.setattr(kalshi_api, "fetch_series", _series)
    assert run_async(scanner._resolve_category("KXEXOTIC-X", "whatever")) == "exotics"

    async def _series_caps(_st):
        return {"category": "EXOTICS"}

    monkeypatch.setattr(kalshi_api, "fetch_series", _series_caps)
    assert run_async(scanner._resolve_category("KXEXOTIC-X", "whatever")) == "exotics"




def test_a_block_trade_is_not_scored_as_a_whale(fresh_db, monkeypatch):
    """Kalshi stamps every print with `is_block_trade` (present on 1000/1000 of
    a live sample, 2026-08-25). A block is privately negotiated away from the
    book and printed afterwards: it carries a taker_side and a large size, so
    it clears every gate here — but nobody swept the public book, which is the
    whole premise of the signal. Blocks are large BY CONSTRUCTION, so the bias
    is systematic rather than occasional."""
    block = dict(_tape_trade("t-block", "no"), is_block_trade=True)
    _stub_network(monkeypatch, [block])
    n, rows = run_async(scanner.scan_whales(WHALE_CFG))
    assert n == 0 and rows == []
    with db.get_db() as conn:
        assert conn.execute("SELECT COUNT(*) FROM whale_trades").fetchone()[0] == 0


def test_an_identical_ordinary_print_still_scores(fresh_db, monkeypatch):
    """Control: same size, same price, same side — only the flag differs."""
    _stub_network(monkeypatch, [dict(_tape_trade("t-ord", "no"),
                                     is_block_trade=False)])
    n, _rows = run_async(scanner.scan_whales(WHALE_CFG))
    assert n == 1


def test_the_websocket_tape_carries_the_block_flag():
    """scan_whales PREFERS the websocket tape over REST, so a flag that only
    survived the REST path would leave the primary path unfiltered — which is
    the same as not filtering at all."""
    c = kalshi_ws._Client()
    c._on_trade({"msg": {"market_ticker": "X", "trade_id": "b",
                         "count_fp": "10", "yes_price_dollars": "0.5",
                         "taker_side": "yes", "is_block_trade": True}})
    assert c.trades[-1]["is_block_trade"] is True
    c._on_trade({"msg": {"market_ticker": "X", "trade_id": "n",
                         "count_fp": "10", "yes_price_dollars": "0.5",
                         "taker_side": "yes"}})
    assert c.trades[-1]["is_block_trade"] is False
