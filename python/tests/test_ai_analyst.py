"""AI analysis: the parts that must never be confidently wrong.

Nothing here touches the network. Every test is about the two seams where this
feature could put a fabricated number in front of someone about to trade:

  1. What we hand the model. A Kalshi `yes_bid: 0` means "no bid"; if it
     reaches the prompt as a zero, the model produces confident analysis of a
     price that does not exist and the user never sees the substitution.
  2. What we accept back. A fair value is the one field in the panel someone
     would size a position from, so an out-of-band, unparseable or absent one
     has to arrive as None rather than as a plausible default.
"""
from __future__ import annotations

import ai_analyst as ai



def _detail(**over):
    d = {
        "market": {
            "ticker": "KXTEST-26", "title": "Will it rain?",
            "yesSubTitle": "Above 1 inch",
            "yesBid": None, "yesAsk": 44, "noBid": 56, "noAsk": None,
            "lastPrice": None, "previousPrice": None,
            "midCents": None, "spreadCents": None,
            "volume": None, "volume24h": None, "openInterest": None,
            "status": "active", "closeTime": None, "minutesToClose": None,
            "sources": {"yesAsk": "rest"},
        },
        "event": None, "series": None, "risk": {}, "book": None,
        "position": None, "restingOrders": [], "quoteDriftCents": None,
        "errors": [], "fetchedAt": "2026-08-26T12:00:00Z",
    }
    d.update(over)
    return d


def test_absent_prices_render_as_absent_never_zero():
    """The whole point. Kalshi reports no-bid and never-traded as zeros; a
    prompt that carries them through as 0 is a lie the model cannot detect."""
    text = ai.render_market(_detail())
    assert "yes bid --" in text
    assert "no ask --" in text
    assert "last --" in text
    assert "0c" not in text
    assert "yes ask 44c" in text


def test_prompt_tells_the_model_what_the_dash_means():
    """The rendering is only half the fix -- a model that reads '--' as a
    missing digit rather than a missing fact is back where it started."""
    assert "is ABSENT" in ai._SYSTEM
    assert "It is not zero" in ai._SYSTEM


def test_yes_subtitle_is_shown_when_present():
    """What YES resolves to. Without it the model is guessing which side of
    the question it has been asked to price."""
    assert "YES means: Above 1 inch" in ai.render_market(_detail())


def test_provenance_reaches_the_prompt():
    assert "sources: yesAsk=rest" in ai.render_market(_detail())


def test_stale_book_is_flagged_to_the_model():
    d = _detail(book={
        "yes": [{"priceCents": 44, "contracts": 300}], "no": [],
        "yesDepthContracts": 300, "noDepthContracts": None,
        "source": "rest", "stale": True, "note": "seq gap",
    })
    text = ai.render_market(d)
    assert "STALE" in text and "seq gap" in text


def test_unreconciled_position_is_not_offered_as_a_cost_basis():
    d = _detail(position={
        "contracts": 50, "side": "yes", "avgCostCents": None, "markCents": 44,
        "unrealizedUsd": None, "reconciled": False, "reconcileNote": "fills page 429d",
    })
    text = ai.render_market(d)
    assert "UNRECONCILED" in text
    assert "unknown, not break-even" in text
    assert "average cost --" in text


def test_failed_panels_are_reported_as_missing_not_empty():
    d = _detail(errors=[{"panel": "tape", "message": "timeout"}])
    assert "missing, not empty" in ai.render_market(d)


def test_render_never_raises_on_a_hollow_detail():
    """market_detail returns per-panel errors instead of raising, so half of
    this payload is routinely absent."""
    assert ai.render_market({}) is not None
    assert ai.render_market({"market": {}}) is not None



def test_extract_json_handles_a_fenced_reply():
    got = ai._extract_json('Sure:\n```json\n{"summary": "x"}\n```')
    assert got == {"summary": "x"}


def test_extract_json_handles_prose_around_nested_braces():
    got = ai._extract_json('Here it is {"a": {"b": 1}, "c": "}"} -- hope that helps')
    assert got == {"a": {"b": 1}, "c": "}"}


def test_extract_json_gives_up_cleanly():
    assert ai._extract_json("no json here") is None
    assert ai._extract_json("") is None
    assert ai._extract_json('{"unclosed": ') is None


def test_unparseable_reply_keeps_the_text_instead_of_discarding_it():
    """The user already paid for this call. Showing what the model said beats
    an error that throws the answer away."""
    shaped = ai._shape(None, "I could not produce JSON but here is my view.")
    assert shaped["raw"].startswith("I could not produce JSON")
    assert shaped["fairValueCents"] is None
    assert shaped["verdict"] == "unclear"


def test_fair_value_outside_the_tradable_band_is_none():
    """1..99 is where Kalshi prices live. A 0 or a 100 is not a fair value a
    trader can act on, and neither is a model saying 'maybe'."""
    for bad in (0, 100, -5, 250, "maybe", None, float("nan")):
        assert ai._cents_or_none(bad) is None, bad
    assert ai._cents_or_none(41) == 41
    assert ai._cents_or_none("41.4") == 41


def test_a_value_that_only_rounds_into_the_band_is_none():
    """Checked before rounding. 0.62 used to round to 1 -- inside the band --
    and survived as a confident 1c fair value; True is an int to Python;
    and Infinity (which json.loads accepts) crashed the whole analysis with
    an OverflowError."""
    for bad in (0.62, 0.99, 0.5, 99.6, True, False, float("inf"), float("-inf"),
                "NaN", "Infinity", "62%"):
        assert ai._cents_or_none(bad) is None, bad
    assert ai._cents_or_none(1) == 1 and ai._cents_or_none(99) == 99
    assert ai._cents_or_none(98.6) == 99


def test_a_fair_value_given_as_a_probability_is_none_and_unclear():
    """Invariant 8: the model answered 0.62 for 62%. Not converted -- which
    unit it meant is a guess -- so no number, no verdict, nothing recorded."""
    shaped = ai._shape({"fairValueCents": 0.62, "fairValueLowCents": 0.55,
                        "fairValueHighCents": 0.7, "verdict": "cheap"}, "")
    assert shaped["fairValueCents"] is None
    assert shaped["fairValueLowCents"] is None and shaped["fairValueHighCents"] is None
    assert shaped["verdict"] == "unclear"
    shaped = ai._shape({"fairValueCents": 1.0, "fairValueLowCents": 0.9,
                        "fairValueHighCents": 1, "verdict": "rich"}, "")
    assert shaped["fairValueCents"] is None and shaped["verdict"] == "unclear"


def test_infinity_in_the_reply_is_an_absent_number_not_a_crash():
    parsed = ai._extract_json('{"fairValueCents": Infinity, "verdict": "cheap"}')
    shaped = ai._shape(parsed, "")
    assert shaped["fairValueCents"] is None and shaped["verdict"] == "unclear"


def test_a_fair_value_outside_its_own_range_is_none():
    shaped = ai._shape({"fairValueCents": 41, "fairValueLowCents": 50,
                        "fairValueHighCents": 60, "verdict": "cheap"}, "")
    assert shaped["fairValueCents"] is None and shaped["verdict"] == "unclear"


def test_a_probability_shaped_answer_never_reaches_the_forecast_ledger(monkeypatch):
    """The panel's handler records fairValueCents in the scoreboard. A 0.62
    used to land there as prob_yes 0.01 and score the model on a number it
    never meant."""
    import asyncio
    import forecast_ledger
    import service
    recorded = []
    monkeypatch.setattr(forecast_ledger, "record", lambda **kw: recorded.append(kw) or 1)
    monkeypatch.setattr(ai, "has_key", lambda p: True)
    monkeypatch.setattr(ai, "_read_key", lambda p: "sk-test")
    monkeypatch.setattr(ai, "_call_anthropic", lambda *a, **k: {
        "text": '{"summary": "s", "fairValueCents": 0.62, "verdict": "cheap"}',
        "citations": [], "inputTokens": 1, "outputTokens": 1, "costUsd": None})
    import terminal

    async def _detail(ticker, **kw):
        return {"market": {"ticker": ticker, "midCents": 50}}
    monkeypatch.setattr(terminal, "market_detail", _detail)
    monkeypatch.setattr(service.STATE, "cfg", {"ai_provider": "anthropic"})
    res = asyncio.run(service._h_ai_analyze({"ticker": "KX-1"}))
    assert res["ok"], res
    assert res["analysis"]["fairValueCents"] is None
    assert res["analysis"]["verdict"] == "unclear"
    assert recorded == []
    monkeypatch.setattr(ai, "_call_anthropic", lambda *a, **k: {
        "text": '{"summary": "s", "fairValueCents": 62, "verdict": "cheap"}',
        "citations": [], "inputTokens": 1, "outputTokens": 1, "costUsd": None})
    asyncio.run(service._h_ai_analyze({"ticker": "KX-1"}))
    assert len(recorded) == 1 and abs(recorded[0]["prob_yes"] - 0.62) < 1e-9


def test_a_verdict_without_a_number_behind_it_is_forced_to_unclear():
    """The verdict chip renders next to real prices. 'Looks cheap' with no
    fair value is a naked opinion wearing an analysis's clothes."""
    shaped = ai._shape({"summary": "s", "fairValueCents": None, "verdict": "cheap"}, "")
    assert shaped["verdict"] == "unclear"


def test_a_verdict_with_a_number_survives():
    shaped = ai._shape({"fairValueCents": 41, "verdict": "cheap"}, "")
    assert shaped["verdict"] == "cheap"
    assert shaped["fairValueCents"] == 41


def test_an_inverted_range_is_swapped_not_dropped():
    shaped = ai._shape(
        {"fairValueCents": 41, "fairValueLowCents": 49, "fairValueHighCents": 33}, "")
    assert (shaped["fairValueLowCents"], shaped["fairValueHighCents"]) == (33, 49)


def test_garbage_confidence_and_verdict_fall_back():
    shaped = ai._shape({"confidence": "extremely", "verdict": "buy"}, "")
    assert shaped["confidence"] == "low"
    assert shaped["verdict"] == "unclear"


def test_drivers_accept_both_shapes_and_drop_empties():
    shaped = ai._shape({"drivers": [
        {"heading": "Weather", "body": "Front arriving."},
        "a bare string",
        {"heading": "x", "body": ""},
    ]}, "")
    assert len(shaped["drivers"]) == 2
    assert shaped["drivers"][1]["heading"] == "Note"



def test_cost_is_none_when_we_have_no_published_price():
    """Rather than a plausible-looking guess. The user reads this number to
    decide whether to run another analysis."""
    assert ai._cost_usd("gpt-5.5", 1000, 500) is None
    assert ai._cost_usd("claude-opus-5", 1000, 500) == 0.0175


def test_cost_is_none_when_the_provider_reported_no_usage():
    assert ai._cost_usd("claude-opus-5", None, 500) is None


def test_unknown_model_falls_back_rather_than_travelling_to_the_api():
    assert ai.normalize_model("anthropic", "gpt-5.5") == "claude-opus-5"
    assert ai.normalize_model("openai", "claude-opus-5") == "gpt-5.5"
    assert ai.normalize_model("anthropic", None) == "claude-opus-5"
    assert ai.normalize_model("nonsense", "x") == "claude-opus-5"


def test_every_offered_model_is_a_real_option_for_its_provider():
    for provider, models in ai.MODELS.items():
        if ai.DEFAULT_MODEL[provider] or provider in ai.CURATED:
            assert ai.DEFAULT_MODEL[provider] in models, provider
        for m in models:
            assert ai.normalize_model(provider, m) == m


def test_analysis_without_a_key_says_where_to_put_one(monkeypatch):
    """The no-key path must never reach a provider, and must name the fix."""
    monkeypatch.setattr(ai, "_read_key", lambda provider: None)
    try:
        ai.analyze(_detail(), {"ai_provider": "anthropic"})
    except ai.AiError as e:
        assert "Settings" in str(e)
    else:
        raise AssertionError("expected AiError")


def test_the_ai_keys_are_registered_with_the_log_scrubber():
    """An API key that reaches backend.log is one the user has to rotate.
    Shape rules alone would not catch these."""
    import inspect
    import logscrub
    src = inspect.getsource(logscrub.refresh_known_secrets)
    for name in ai.SECRET_NAMES.values():
        assert name in src, name


def test_status_never_leaks_the_key_itself():
    got = ai.status({"ai_provider": "anthropic"})
    flat = repr(got)
    assert "hasKey" in got
    for name in ai.SECRET_NAMES.values():
        assert "sk-" not in flat
