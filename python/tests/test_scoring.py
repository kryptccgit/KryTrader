from __future__ import annotations

import scanner




def test_whale_score_basic_yes_favorite():
    score = scanner.compute_whale_score(
        dollar_value=3000, price=0.70, taker_side="yes"
    )
    assert score == 75.0


def test_whale_score_no_side_with_all_bonuses():
    score = scanner.compute_whale_score(
        dollar_value=12_000, price=0.55, taker_side="no",
        market_volume=300_000, open_interest=60_000,
        days_to_close=0.5, category="crypto",
    )
    assert score == 63.5


def test_whale_size_bonus_is_monotonic():
    scores = [
        scanner.compute_whale_score(dollar_value=d, price=0.70, taker_side="yes")
        for d in (1_000, 3_000, 7_000, 12_000, 30_000)
    ]
    assert scores == sorted(scores)


def test_whale_score_clamps_to_ceiling_97():
    score = scanner.compute_whale_score(
        dollar_value=30_000, price=0.95, taker_side="yes",
        market_volume=300_000, open_interest=60_000,
    )
    assert score == 97.0


def test_whale_score_clamps_to_floor_5():
    score = scanner.compute_whale_score(
        dollar_value=100, price=0.05, taker_side="yes"
    )
    assert score == 5.0




def test_momentum_confidence_trade_cluster_underdog():
    score = scanner.compute_momentum_confidence(
        volume_spike_ratio=3.0, price_change_abs=0.10,
        trade_cluster_count=6, trade_cluster_dollars=6_000,
        market_volume=60_000, open_interest=12_000,
        days_to_close=5, price=0.20, direction="yes",
        signal_type="trade_cluster",
    )
    assert score == 28.0


def test_momentum_confidence_no_signal_is_implied_only():
    score = scanner.compute_momentum_confidence(
        volume_spike_ratio=0.0, price_change_abs=0.0,
        trade_cluster_count=0, trade_cluster_dollars=0,
        market_volume=0, open_interest=0,
        days_to_close=None, price=0.70, direction="no",
        signal_type="",
    )
    assert score == 30.0


def test_momentum_confidence_never_exceeds_ceiling():
    score = scanner.compute_momentum_confidence(
        volume_spike_ratio=10.0, price_change_abs=0.50,
        trade_cluster_count=50, trade_cluster_dollars=50_000,
        market_volume=1_000_000, open_interest=500_000,
        days_to_close=0.5, price=0.95, direction="yes",
        signal_type="trade_cluster", category="crypto",
    )
    assert score == 97.0
