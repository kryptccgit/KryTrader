from __future__ import annotations

import crypto15m_trader as ct
from config import merge_with_defaults


def _cfg():
    c = merge_with_defaults({
        "crypto15m_enabled": True,
        "crypto15m_use_rules": True,
        "crypto15m_rules": [{"field": "change5mPct", "op": ">", "value": 0.1}],
        "crypto15m_rules_no": [{"field": "change5mPct", "op": "<", "value": -0.1}],
    })
    return c


def _asset(change, ticker="KXBTC15M-T1"):
    return {
        "hasMarket": True, "ticker": ticker, "asset": "BTC",
        "favorite": "up", "favoritePrice": 0.60, "entryCost": 0.62,
        "upAsk": 0.62, "downAsk": 0.40, "minsLeft": 5.0, "hourUtc": 12,
        "change5mPct": change, "inWindow": True,
    }


def test_directional_flag_detected():
    assert ct._is_directional_rules(_cfg()) is True
    c = _cfg(); c["crypto15m_rules_no"] = []
    assert ct._is_directional_rules(c) is False


def test_side_follows_momentum():
    c = _cfg()
    assert ct._directional_rules_side(_asset(0.5), c)[0] == "up"
    assert ct._directional_rules_side(_asset(-0.5), c)[0] == "down"
    assert ct._directional_rules_side(_asset(0.0), c)[0] is None


def test_should_enter_gates_on_directional_match():
    c = _cfg()
    ok, _ = ct.should_enter(_asset(0.5), c, has_open=False, open_count=0)
    assert ok is True
    ok2, why = ct.should_enter(_asset(0.0), c, has_open=False, open_count=0)
    assert ok2 is False and "directional" in why


def test_bought_side_is_directional_when_no_rules_present():
    c = _cfg()
    assert ct._bought_side(_asset(-0.5), c) == "down"
