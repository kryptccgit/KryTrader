from __future__ import annotations

from turbine_import import _ge, _gt, _le, _lt, _price_band_rules

_BANDS = [
    [0.25, 0.75], [0.35, 0.65], [0.45, 0.55], [0.20, 0.80],
    [0.55, 0.78], [0.25, 0.55], [0.60, 0.85],
]
_CHG_THRESH = [0.05, 0.1, 0.2, 0.4]
_VEL_THRESH = [0.1, 0.25, 0.5]
_MR_DIPS = [0.25, 0.30, 0.35, 0.40]
_FAV_PROBS = [0.80, 0.85, 0.90]

_MODEL_PROBS = [0.95, 0.97, 0.99]
_MODEL_EDGES = [1.0, 2.0, 3.0, 5.0]


def _recipe(name: str, arch: str, yes: list, no: list, band: list | None) -> dict:
    if band:
        yes = yes + _price_band_rules("up", band)
        no = no + _price_band_rules("down", band)
    return {
        "name": name, "asset": None, "archetype": arch,
        "config": {
            "crypto15m_use_rules": True,
            "crypto15m_rules": yes,
            "crypto15m_rules_no": no,
            "crypto15m_entry_style": "taker",
            "crypto15m_order_size": 1,
        },
    }


def _band_tag(b: list) -> str:
    return f"{int(b[0] * 100)}-{int(b[1] * 100)}"


def generate() -> list[dict]:
    out: list[dict] = []

    for cf, cf_tag in (("change5mPct", "5m"), ("change15mPct", "15m")):
        for thr in _CHG_THRESH:
            for band in _BANDS[:4]:
                bt = _band_tag(band)
                out.append(_recipe(
                    f"gen mom {cf_tag}>{thr} {bt}c", "momentum",
                    [_gt(cf, thr)], [_lt(cf, -thr)], band))
                out.append(_recipe(
                    f"gen vwap+mom {cf_tag}>{thr} {bt}c", "vwap_momentum",
                    [_gt("priceVsVwapPct", 0), _gt(cf, thr)],
                    [_lt("priceVsVwapPct", 0), _lt(cf, -thr)], band))

    for band in _BANDS:
        bt = _band_tag(band)
        out.append(_recipe(f"gen vwap {bt}c", "vwap_trend",
                           [_gt("priceVsVwapPct", 0)], [_lt("priceVsVwapPct", 0)], band))
        out.append(_recipe(f"gen ema12/sma20 {bt}c", "ema_sma_cross",
                           [_gt("ema12VsSma20Pct", 0)], [_lt("ema12VsSma20Pct", 0)], band))
        out.append(_recipe(f"gen ema1/sma5 {bt}c", "ema_sma_cross",
                           [_gt("ema1VsSma5Pct", 0)], [_lt("ema1VsSma5Pct", 0)], band))
        out.append(_recipe(f"gen vwap+ema {bt}c", "ema_sma_vwap",
                           [_gt("ema12VsSma20Pct", 0), _gt("priceVsVwapPct", 0)],
                           [_lt("ema12VsSma20Pct", 0), _lt("priceVsVwapPct", 0)], band))

    for v in _VEL_THRESH:
        for band in _BANDS[:4]:
            out.append(_recipe(f"gen vel>{v} {_band_tag(band)}c", "velocity",
                               [_gt("velocity1mPct", v)], [_lt("velocity1mPct", -v)], band))

    for dip in _MR_DIPS:
        out.append(_recipe(f"gen meanrev <={int(dip*100)}c", "mean_reversion",
                           [_le("upAsk", dip)], [_le("downAsk", dip)], None))

    for p in _FAV_PROBS:
        out.append(_recipe(f"gen favorite >={int(p*100)}%", "favorite",
                           [_ge("upProb", p)], [_ge("downProb", p)], None))

    for p in _MODEL_PROBS:
        for e in _MODEL_EDGES:
            for fm in (True, False):
                out.append({
                    "name": f"gen model p>={p} edge>={int(e)}c{' +fm' if fm else ''}",
                    "asset": None, "archetype": "model",
                    "config": {
                        "crypto15m_use_rules": False,
                        "crypto15m_direction_mode": "model",
                        "crypto15m_model_min_prob": p,
                        "crypto15m_model_min_edge_cents": e,
                        "crypto15m_model_final_minute": fm,
                        "crypto15m_entry_style": "taker",
                        "crypto15m_order_size": 1,
                    },
                })

    return out
