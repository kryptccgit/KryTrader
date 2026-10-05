from __future__ import annotations

import pytest

import backtest as bt


def sig(cost, correct, confidence=60.0, source="whale"):
    return {"source": source, "confidence": confidence, "cost": cost,
            "correct": correct, "category": ""}




def test_fee_is_max_at_fifty_cents():
    assert bt.kalshi_fee_per_contract(0.50) == pytest.approx(0.0175)
    assert bt.kalshi_fee_per_contract(0.0) == 0.0
    assert bt.kalshi_fee_per_contract(1.0) == 0.0


def test_fee_is_symmetric_in_price():
    assert bt.kalshi_fee_per_contract(0.3) == pytest.approx(bt.kalshi_fee_per_contract(0.7))




def test_net_pnl_win_subtracts_fee():
    assert bt.net_pnl_per_contract(0.30, True) == pytest.approx(0.6853)


def test_net_pnl_loss_adds_fee_to_loss():
    assert bt.net_pnl_per_contract(0.30, False) == pytest.approx(-0.3147)




def test_signal_cost_whale_uses_taker_price():
    assert bt.signal_cost({"price": 0.62}, "whale") == pytest.approx(0.62)


def test_signal_cost_momentum_no_side_inverts():
    assert bt.signal_cost({"price": 0.30, "direction": "no"}, "momentum") == pytest.approx(0.70)
    assert bt.signal_cost({"price": 0.30, "direction": "yes"}, "momentum") == pytest.approx(0.30)




def test_fair_odds_lose_exactly_the_fee():
    s = summarize = bt.summarize([sig(0.50, True), sig(0.50, False)])
    assert s["win_rate"] == pytest.approx(0.5)
    assert s["gross_ev"] == pytest.approx(0.0)
    assert s["fee_ev"] == pytest.approx(0.0175)
    assert s["net_ev"] == pytest.approx(-0.0175)


def test_real_edge_survives_fees():
    signals = [sig(0.50, True) for _ in range(6)] + [sig(0.50, False) for _ in range(4)]
    s = bt.summarize(signals)
    assert s["n"] == 10
    assert s["gross_ev"] == pytest.approx(0.10)
    assert s["fee_ev"] == pytest.approx(0.0175)
    assert s["net_ev"] == pytest.approx(0.0825)
    assert s["t"] > 0


def test_empty_summary_is_zeroed():
    s = bt.summarize([])
    assert s["n"] == 0 and s["net_ev"] == 0.0




def test_threshold_sweep_filters_by_confidence():
    signals = [sig(0.5, True, confidence=60), sig(0.5, True, confidence=80)]
    rows = bt.threshold_sweep(signals, [50, 70, 90])
    by_th = {r["threshold"]: r["n"] for r in rows}
    assert by_th == {50: 2, 70: 1, 90: 0}




def test_verdict_flags_small_samples_inconclusive():
    s = bt.summarize([sig(0.5, True)])
    assert "INCONCLUSIVE" in bt.verdict(s, [])


def test_verdict_calls_negative_when_net_negative():
    signals = [sig(0.5, i % 2 == 0) for i in range(200)]
    rep = bt.build_report(signals, bt.DEFAULT_FEE_COEFF)
    assert "NEGATIVE" in rep["verdict"]
