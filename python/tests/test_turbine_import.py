from __future__ import annotations

import turbine_import as ti
from config import merge_with_defaults


def test_all_imports_produce_valid_configs():
    imported, skipped = ti.import_all()
    assert len(imported) >= 30
    assert all("Dual-Side" in s["name"] or "Panic Fade" in s["name"] for s in skipped)
    for it in imported:
        c = merge_with_defaults(dict(it["config"]))
        if c.get("crypto15m_direction_mode") == "model" and not c["crypto15m_use_rules"]:
            assert c["crypto15m_model_min_edge_cents"] >= 0
            continue
        assert c["crypto15m_use_rules"] is True
        assert c["crypto15m_rules"] and c["crypto15m_rules_no"]
        assert c["crypto15m_assets"] == [it["asset"]]


def test_vwap_momentum_maps_to_vwap_and_change():
    s = {"name": "x", "asset": "BTC", "archetype": "vwap_momentum",
         "indicators": {"vwap": "1h", "lookbackMin": 5, "changePct": 0.1},
         "priceBand": [0.25, 0.75], "size": 5}
    cfg = ti.import_strategy(s)
    yf = {r["field"] for r in cfg["crypto15m_rules"]}
    assert "priceVsVwapPct" in yf and "change5mPct" in yf and "upAsk" in yf
    nf = {r["field"] for r in cfg["crypto15m_rules_no"]}
    assert "priceVsVwapPct" in nf and "downAsk" in nf


def test_ema_cross_uses_relative_field():
    s = {"name": "x", "asset": "BTC", "archetype": "ema_sma_cross",
         "indicators": {"ema": 12, "sma": 20}, "priceBand": [0.45, 0.55], "size": 10}
    cfg = ti.import_strategy(s)
    assert any(r["field"] == "ema12VsSma20Pct" for r in cfg["crypto15m_rules"])
    s["indicators"] = {"ema": 1, "sma": 5}
    cfg2 = ti.import_strategy(s)
    assert any(r["field"] == "ema1VsSma5Pct" for r in cfg2["crypto15m_rules"])


def test_lookback_snaps_to_recorded_change_field():
    assert ti._change_field(5) == "change5mPct"
    assert ti._change_field(15) == "change15mPct"
    assert ti._change_field(12) == "change15mPct"
    assert ti._change_field(None) == "change5mPct"


def test_dual_side_and_panic_fade_are_skipped():
    assert ti.import_strategy({"archetype": "dual_side", "asset": "BTC"}) is None
    assert ti.import_strategy({"archetype": "panic_fade", "asset": "BTC"}) is None
