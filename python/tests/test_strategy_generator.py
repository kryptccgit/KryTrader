from __future__ import annotations

import strategy_generator as g
from config import merge_with_defaults


def test_generates_a_sizeable_valid_corpus():
    gen = g.generate()
    assert len(gen) >= 80
    names = [x["name"] for x in gen]
    assert len(names) == len(set(names))
    for x in gen:
        c = merge_with_defaults(dict(x["config"]))
        if c.get("crypto15m_direction_mode") == "model":
            assert c["crypto15m_use_rules"] is False
            continue
        assert c["crypto15m_use_rules"] is True
        assert c["crypto15m_rules"] and c["crypto15m_rules_no"]


def test_recipes_are_coin_agnostic():
    for x in g.generate():
        assert x["asset"] is None
        assert "crypto15m_assets" not in x["config"]


def test_spans_the_key_archetypes():
    archs = {x["archetype"] for x in g.generate()}
    for a in ("momentum", "vwap_momentum", "ema_sma_cross", "velocity",
              "mean_reversion", "favorite"):
        assert a in archs
