from __future__ import annotations

import json
import os
import sys
from typing import Optional

_BASE = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
_LIB_PATH = os.path.join(_BASE, "turbine_strategies.json")


def _ge(field: str, v: float) -> dict:
    return {"field": field, "op": ">=", "value": v}


def _le(field: str, v: float) -> dict:
    return {"field": field, "op": "<=", "value": v}


def _gt(field: str, v: float) -> dict:
    return {"field": field, "op": ">", "value": v}


def _lt(field: str, v: float) -> dict:
    return {"field": field, "op": "<", "value": v}


def _change_field(lookback_min: Optional[float]) -> str:
    lb = float(lookback_min or 5)
    return "change15mPct" if lb > 10 else "change5mPct"


def _price_band_rules(side: str, band: Optional[list]) -> list[dict]:
    if not band or len(band) != 2:
        return []
    ask = "upAsk" if side == "up" else "downAsk"
    lo, hi = float(band[0]), float(band[1])
    return [_ge(ask, lo), _le(ask, hi)]


def import_strategy(s: dict) -> Optional[dict]:
    arch = str(s.get("archetype") or "").lower()
    ind = s.get("indicators") or {}
    band = s.get("priceBand")
    chg_field = _change_field(ind.get("lookbackMin"))
    chg = float(ind.get("changePct") or 0.1)
    vel = float(ind.get("velocityPct") or 0.1)
    ema_field = "ema1VsSma5Pct" if ind.get("ema") == 1 else "ema12VsSma20Pct"

    yes: list[dict] = []
    no: list[dict] = []

    if arch in ("momentum",):
        yes, no = [_gt(chg_field, chg)], [_lt(chg_field, -chg)]
    elif arch in ("vwap_momentum",):
        yes = [_gt("priceVsVwapPct", 0), _gt(chg_field, chg)]
        no = [_lt("priceVsVwapPct", 0), _lt(chg_field, -chg)]
    elif arch in ("vwap_trend", "vwap_entry"):
        yes, no = [_gt("priceVsVwapPct", 0)], [_lt("priceVsVwapPct", 0)]
    elif arch in ("vwap_ema_trend", "vwap_ema_momentum"):
        yes = [_gt("priceVsVwapPct", 0), _gt("ema12VsSma20Pct", 0), _gt(chg_field, chg)]
        no = [_lt("priceVsVwapPct", 0), _lt("ema12VsSma20Pct", 0), _lt(chg_field, -chg)]
    elif arch in ("vwap_velocity",):
        yes = [_gt("priceVsVwapPct", 0), _gt("change5mPct", 0), _gt("velocity1mPct", vel)]
        no = [_lt("priceVsVwapPct", 0), _lt("change5mPct", 0), _lt("velocity1mPct", -vel)]
    elif arch in ("velocity", "velocity_scalp"):
        yes, no = [_gt("velocity1mPct", vel)], [_lt("velocity1mPct", -vel)]
    elif arch in ("ema_sma_cross",):
        yes, no = [_gt(ema_field, 0)], [_lt(ema_field, 0)]
    elif arch in ("ema_sma_vwap", "ema_sma_change", "vwap_ma_momentum"):
        yes = [_gt("ema12VsSma20Pct", 0), _gt("priceVsVwapPct", 0)]
        no = [_lt("ema12VsSma20Pct", 0), _lt("priceVsVwapPct", 0)]
        if "change" in arch or arch == "vwap_ma_momentum":
            yes.append(_gt(chg_field, chg))
            no.append(_lt(chg_field, -chg))
    elif arch in ("favorite_momentum",):
        yes, no = [_gt("change5mPct", 0)], [_lt("change5mPct", 0)]
    elif arch in ("favorite",):
        yes, no = [_ge("upProb", 0.80)], [_ge("downProb", 0.80)]
    elif arch in ("mean_reversion",):
        yes, no = [_le("upAsk", 0.35)], [_le("downAsk", 0.35)]
    elif arch in ("scalp",):
        b = band or [0.80, 0.90]
        yes = _price_band_rules("up", b)
        no = _price_band_rules("down", b)
    elif arch in ("sweep",):
        lo = float((band or [0.95, 0.99])[0])
        yes, no = [_ge("upAsk", lo)], [_ge("downAsk", lo)]
    else:
        return None

    if not yes and not no:
        return None

    if arch not in ("scalp", "sweep", "mean_reversion", "favorite"):
        yes = yes + _price_band_rules("up", band)
        no = no + _price_band_rules("down", band)

    return {
        "crypto15m_use_rules": True,
        "crypto15m_rules": yes,
        "crypto15m_rules_no": no,
        "crypto15m_assets": [s.get("asset")],
        "crypto15m_entry_style": "taker",
        "crypto15m_order_size": int(s.get("size") or 1),
    }


def load_library(path: str = _LIB_PATH) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return (json.load(f) or {}).get("strategies", [])


def _model_cfg(prob: float, edge: float, final_minute: bool,
               midwindow: bool = False) -> dict:
    return {
        "crypto15m_use_rules": False,
        "crypto15m_direction_mode": "model",
        "crypto15m_model_min_prob": prob,
        "crypto15m_model_min_edge_cents": edge,
        "crypto15m_model_final_minute": final_minute,
        "crypto15m_model_midwindow": midwindow,
        "crypto15m_entry_style": "taker",
        "crypto15m_order_size": 1,
    }


_HOUSE = [
    {"name": "★ Settlement Sniper — Final Minute (prints·~3σ·≥2¢)", "asset": None,
     "archetype": "model", "turbine": None,
     "config": _model_cfg(0.99, 2.0, True, midwindow=False)},
    {"name": "Settlement Edge — Mid-Window (measured NO edge · paper research)",
     "asset": None, "archetype": "model", "turbine": None,
     "config": _model_cfg(0.97, 2.0, True, midwindow=True)},
]


def import_all(path: str = _LIB_PATH) -> tuple[list[dict], list[dict]]:
    imported: list[dict] = [dict(h) for h in _HOUSE]
    skipped: list[dict] = []
    for s in load_library(path):
        cfg = import_strategy(s)
        entry = {"name": s.get("name"), "asset": s.get("asset"),
                 "archetype": s.get("archetype"), "turbine": s.get("turbine")}
        if cfg is None:
            skipped.append(entry)
        else:
            imported.append({**entry, "config": cfg})
    return imported, skipped
