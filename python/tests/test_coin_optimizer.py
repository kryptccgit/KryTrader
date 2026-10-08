"""Coin Optimizer: bucketing + aggregation logic (pure, network-free)."""
from __future__ import annotations

import coin_optimizer as co


def test_buckets_cover_24h():
    assert co._buckets(4) == [(0, 4), (4, 8), (8, 12), (12, 16), (16, 20), (20, 24)]
    assert co._buckets(24) == [(0, 24)]
    assert co._buckets(6) == [(0, 6), (6, 12), (12, 18), (18, 24)]
    assert co._buckets(5) == co._buckets(4)


def test_bucket_of():
    b = co._buckets(4)
    assert co._bucket_of(3, b) == (0, 4)
    assert co._bucket_of(4, b) == (4, 8)
    assert co._bucket_of(23, b) == (20, 24)
    assert co._bucket_of(-1, b) is None


def test_hour_of_parses_observed_at():
    assert co._hour_of("2026-07-14 09:31:05") == 9
    assert co._hour_of(None) is None
    assert co._hour_of("garbage") is None


def test_agg_per_contract_and_winrate():
    trades = [{"pnlUsd": 0.30, "won": True}, {"pnlUsd": -0.80, "won": False},
              {"pnlUsd": 0.30, "won": True}]
    a = co._agg(trades)
    assert a["n"] == 3 and a["wins"] == 2
    assert a["winRate"] == round(2 / 3, 4)
    assert abs(a["netCents"] - (sum(t["pnlUsd"] for t in trades) / 3 * 100)) < 1e-2


def test_agg_empty():
    a = co._agg([])
    assert a["n"] == 0 and a["winRate"] is None and a["netCents"] == 0.0
