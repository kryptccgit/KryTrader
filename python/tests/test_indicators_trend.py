"""Trend/VWAP indicator fields added for the Turbine strategy library."""
from __future__ import annotations

import indicators as I


def test_sma_and_ema_last():
    closes = list(range(1, 21))
    assert I.sma(closes, 20) == sum(range(1, 21)) / 20
    assert I.sma(closes, 21) is None
    assert I.ema_last(closes, 5) is not None
    assert I.ema_last(closes, 5) < closes[-1]


def test_vwap_volume_weighted():
    closes = [10.0, 20.0, 30.0]
    vols = [1.0, 1.0, 8.0]
    v = I.vwap(closes, vols, 3)
    assert abs(v - (10 + 20 + 240) / 10.0) < 1e-9
    assert I.vwap(closes, None, 3) == 20.0
    assert I.vwap(closes, vols, 4) is None


def test_pct_change_is_percent():
    closes = [100.0, 101.0, 102.0]
    assert abs(I.pct_change(closes, 2) - 2.0) < 1e-9
    assert I.pct_change(closes, 5) is None


def test_compute_relative_fields_above_below():
    rising = [100 + i * 0.5 for i in range(70)]
    c = I.compute(rising, [10] * 70)
    assert c["priceVsVwapPct"] > 0
    assert c["ema12VsSma20Pct"] > 0
    assert c["change5mPct"] > 0
    falling = [100 - i * 0.5 for i in range(70)]
    cf = I.compute(falling, [10] * 70)
    assert cf["priceVsVwapPct"] < 0
    assert cf["ema12VsSma20Pct"] < 0
    assert cf["change5mPct"] < 0


def test_compute_none_safe_on_short_history():
    c = I.compute([1, 2, 3])
    for k in ("vwap1h", "ema12", "sma20", "priceVsVwapPct", "ema12VsSma20Pct",
              "change5mPct", "change15mPct"):
        assert c[k] is None
    assert I.compute([])["velocity1mPct"] is None
