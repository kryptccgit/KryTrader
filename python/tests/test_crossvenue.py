"""Cross-venue matching.

The gold cases below are real titles pulled from both live APIs, chosen because
a plain token-overlap matcher got them WRONG in the most dangerous direction:
it paired Barack Obama with Michelle Obama, Mark Cuban with Mark Kelly, Jon
Stewart with Jon Ossoff and John Fetterman with John Thune — each of which
would have rendered as a double-digit "spread" between two different people —
while rejecting the true Marco Rubio and J.D. Vance pairs because the
boilerplate swamped the name.

A false pair is far worse than a missed one here. A missed pair shows nothing;
a false pair invites a trade on a market that is not the one on screen. Every
must-not-match case below is therefore a regression test on that failure.
"""
from __future__ import annotations

import crossvenue as cv
import polymarket_public as pm

MUST_NOT_MATCH = [
    ("Will Barack Obama be the Democratic Presidential nominee?", "Barack Obama",
     "Will Michelle Obama win the 2028 Democratic presidential nomination?"),
    ("Will Mark Cuban be the Democratic Presidential nominee?", "Mark Cuban",
     "Will Mark Kelly win the 2028 Democratic presidential nomination?"),
    ("Will Jon Stewart be the Democratic Presidential nominee?", "Jon Stewart",
     "Will Jon Ossoff win the 2028 Democratic presidential nomination?"),
    ("Will John Fetterman be the Democratic Presidential nominee?", "John Fetterman",
     "Will John Thune win the 2028 Republican presidential nomination?"),
]

MUST_MATCH = [
    ("Will Marco Rubio be the nominee for the Presidency for the Republican Party?",
     "Marco Rubio",
     "Will Marco Rubio win the 2028 Republican presidential nomination?"),
    ("Will J.D. Vance be the nominee for the Presidency for the Republican Party?",
     "J.D. Vance",
     "Will J.D. Vance win the 2028 Republican presidential nomination?"),
    ("Will Gavin Newsom be the Democratic Presidential nominee?", "Gavin Newsom",
     "Will Gavin Newsom win the 2028 Democratic presidential nomination?"),
    ("Will Alexandria Ocasio-Cortez be the Democratic Presidential nominee?",
     "Alexandria Ocasio-Cortez",
     "Will Alexandria Ocasio-Cortez win the 2028 Democratic presidential nomination?"),
]

CORPUS = [q for _t, _s, q in MUST_NOT_MATCH + MUST_MATCH] + [
    "Will the Fed decrease interest rates by 25 bps after the September 2026 meeting?",
    "Will Bitcoin reach $150,000 by December 31, 2026?",
    "Will Bitcoin reach $200,000 by December 31, 2026?",
    "Atlanta Dream vs. Los Angeles Sparks",
    "Pittsburgh Pirates vs. San Diego Padres",
    "Will Donald Trump win the 2028 Republican presidential nomination?",
    "Will Kamala Harris win the 2028 Democratic presidential nomination?",
    "Will Josh Shapiro win the 2028 Democratic presidential nomination?",
    "Will the Iranian regime fall before 2027?",
    "Will Trump buy Greenland?",
]


def _idf(k_text: str):
    return cv.build_idf([cv.tokens(k_text)] + [cv.tokens(q) for q in CORPUS])


def _score(title, sub, question, k_close=None, p_close=None):
    k_text = f"{title} {sub}"
    return cv.score_pair(k_text, question, _idf(k_text), k_close, p_close)



def test_two_different_people_never_pair():
    for title, sub, question in MUST_NOT_MATCH:
        conf, why = _score(title, sub, question)
        assert conf < cv.CONFIDENT, (
            f"{sub!r} was paired with {question!r} at {conf} — this would show a "
            f"price difference between two different people. Reasons: {why}"
        )
        assert any("different names" in w for w in why), why


def test_the_same_person_pairs_across_different_phrasings():
    for title, sub, question in MUST_MATCH:
        conf, why = _score(title, sub, question)
        assert conf >= cv.CONFIDENT, (
            f"{sub!r} did not pair with {question!r} (scored {conf}). "
            f"Reasons: {why}"
        )


def test_a_shared_surname_alone_is_not_a_match():
    conf, why = _score("Will Barack Obama be the Democratic nominee?", "Barack Obama",
                       "Will Michelle Obama win the nomination?")
    assert conf < cv.CONFIDENT
    assert any("different names" in w for w in why)


def test_a_rephrasing_is_not_treated_as_a_different_question():
    conf, _why = _score(
        "Will Marco Rubio be the nominee for the Presidency for the Republican Party?",
        "Marco Rubio",
        "Will Marco Rubio win the 2028 Republican presidential nomination?")
    assert conf >= cv.CONFIDENT



def test_different_strikes_do_not_pair():
    conf, why = _score("Will Bitcoin reach $150,000 by December 31, 2026?", "",
                       "Will Bitcoin reach $200,000 by December 31, 2026?")
    assert conf < cv.CONFIDENT
    assert any("different numbers" in w for w in why), why


def test_the_same_strike_pairs():
    conf, _ = _score("Will Bitcoin reach $150,000 by December 31, 2026?", "",
                     "Will Bitcoin reach $150,000 by December 31, 2026?")
    assert conf >= cv.CONFIDENT


def test_far_apart_close_dates_are_penalised():
    near, _ = _score("Will Gavin Newsom be the Democratic Presidential nominee?",
                     "Gavin Newsom",
                     "Will Gavin Newsom win the 2028 Democratic presidential nomination?",
                     "2028-11-07T00:00:00Z", "2028-11-07T00:00:00Z")
    far, why = _score("Will Gavin Newsom be the Democratic Presidential nominee?",
                      "Gavin Newsom",
                      "Will Gavin Newsom win the 2028 Democratic presidential nomination?",
                      "2026-01-01T00:00:00Z", "2028-11-07T00:00:00Z")
    assert far < near
    assert any("days apart" in w for w in why)


def test_every_score_carries_its_reasons():
    for title, sub, question in MUST_MATCH + MUST_NOT_MATCH:
        _conf, why = _score(title, sub, question)
        assert why and all(isinstance(w, str) and w for w in why)



def _poly(question, **over):
    row = {"conditionId": "0x" + question[:6].encode().hex(), "question": question,
           "endDate": "2028-11-07T00:00:00Z", "yesBid": 20.0, "yesAsk": 21.0,
           "slug": "s", "midCents": 20.5}
    row.update(over)
    return row


def test_find_matches_ranks_the_right_one_first_and_drops_the_impostors():
    k = {"title": "Will Jon Ossoff be the Democratic Presidential nominee?",
         "yesSubTitle": "Jon Ossoff", "closeTime": "2028-11-07T00:00:00Z"}
    pool = [
        _poly("Will Jon Stewart win the 2028 Democratic presidential nomination?"),
        _poly("Will Jon Ossoff win the 2028 Democratic presidential nomination?"),
        _poly("Atlanta Dream vs. Los Angeles Sparks"),
    ]
    out = cv.find_matches(k, pool)
    assert out, "the true pair should be found"
    assert "Ossoff" in out[0]["market"]["question"]
    assert out[0]["confident"] is True
    for m in out[1:]:
        assert m["confident"] is False


def test_nothing_is_returned_when_nothing_is_close():
    k = {"title": "Will Trump buy Greenland?", "yesSubTitle": "",
         "closeTime": "2029-01-20T00:00:00Z"}
    pool = [_poly("Atlanta Dream vs. Los Angeles Sparks"),
            _poly("Will the Fed decrease interest rates by 25 bps?")]
    assert cv.find_matches(k, pool) == []



def test_a_price_difference_is_never_called_an_edge():
    k = {"yesBid": 40.0, "yesAsk": 41.0}
    p = {"yesBid": 30.0, "yesAsk": 31.0}
    c = cv.compare(k, p)
    assert c["differenceCents"] == 10.0
    assert c["cheaperToBuyYes"] == "polymarket"
    assert not any("edge" in key.lower() or "arb" in key.lower() for key in c)
    assert "CFTC" in cv.VENUE_NOTE and "UMA" in cv.VENUE_NOTE


def test_a_missing_quote_makes_the_comparison_unknown_not_zero():
    c = cv.compare({"yesBid": None, "yesAsk": None}, {"yesBid": 30.0, "yesAsk": 31.0})
    assert c["kalshiMid"] is None
    assert c["differenceCents"] is None
    assert c["cheaperToBuyYes"] is None
    assert c["askDifferenceCents"] is None


def test_asks_are_compared_to_asks():
    c = cv.compare({"yesBid": 10.0, "yesAsk": 60.0}, {"yesBid": 40.0, "yesAsk": 41.0})
    assert c["cheaperToBuyYes"] == "polymarket"
    assert c["askDifferenceCents"] == 19.0


def test_near_identical_asks_report_neither_side_as_cheaper():
    c = cv.compare({"yesBid": 40.0, "yesAsk": 41.0}, {"yesBid": 40.0, "yesAsk": 41.2})
    assert c["cheaperToBuyYes"] == "neither"



def test_polymarket_prices_are_fractions_not_cents():
    assert pm.price_cents(0.18) == 18.0
    assert pm.price_cents("0.185") == 18.5
    assert pm.price_cents(0.002) == 0.2


def test_settled_extremes_are_not_quotes():
    for v in (0, 0.0, 1, 1.0, -0.5, 2, None, "", "abc"):
        assert pm.price_cents(v) is None


def test_a_market_row_keeps_the_midpoint_apart_from_the_quotes():
    row = pm.market_row({
        "conditionId": "0xabc", "question": "Q?", "slug": "q",
        "bestBid": 0.18, "bestAsk": 0.19,
        "outcomePrices": '["0.185", "0.815"]',
        "endDate": "2026-09-01T00:00:00Z", "volume24hr": 1234.5,
    })
    assert (row["yesBid"], row["yesAsk"]) == (18.0, 19.0)
    assert row["spreadCents"] == 1.0
    assert row["lastPrice"] == 18.5
    assert row["url"].endswith("/q")


def test_an_unquoted_market_has_no_spread_or_mid():
    row = pm.market_row({"conditionId": "0xabc", "question": "Q?",
                         "bestBid": 0, "bestAsk": 0})
    assert row["yesBid"] is None and row["yesAsk"] is None
    assert row["spreadCents"] is None and row["midCents"] is None


def test_a_market_with_no_condition_id_is_dropped():
    assert pm.market_row({"question": "Q?"}) is None
    assert pm.market_row(None) is None



def test_vice_presidency_is_not_the_presidency():
    conf, why = _score(
        "Will Marco Rubio be the nominee for the Vice Presidency for the Republican Party?",
        "Marco Rubio",
        "Will Marco Rubio win the 2028 Republican presidential nomination?")
    assert conf < cv.CONFIDENT, why
    assert any("different office" in w for w in why), why


def test_a_nomination_is_not_winning_the_election():
    conf, why = _score(
        "Will Alexandria Ocasio-Cortez be the Democratic Presidential nominee?",
        "Alexandria Ocasio-Cortez",
        "Will Alexandria Ocasio-Cortez win the 2028 US Presidential Election?")
    assert conf < cv.CONFIDENT, why
    assert any("different stage" in w for w in why), why


def test_office_detection_reads_vice_president_before_president():
    assert cv.office("nominee for the Vice Presidency") == "vice_president"
    assert cv.office("the Democratic Presidential nominee") == "president"
    assert cv.office("Will Chelsea win the Premier League?") is None


def test_stage_detection_separates_nomination_from_the_general():
    assert cv.stage("be the Democratic Presidential nominee") == "nomination"
    assert cv.stage("win the 2028 US Presidential Election") == "general_election"
    assert cv.stage("Will Chelsea win the Premier League?") is None


def test_matching_offices_and_stages_still_pair():
    conf, _why = _score(
        "Will Gavin Newsom be the Democratic Presidential nominee?", "Gavin Newsom",
        "Will Gavin Newsom win the 2028 Democratic presidential nomination?")
    assert conf >= cv.CONFIDENT


def test_questions_with_no_office_are_unaffected():
    conf, _ = _score("Will Chelsea win the English Premier League?", "Chelsea",
                     "Will Chelsea win the 2026-27 English Premier League (EPL) Championship?")
    assert conf >= cv.CONFIDENT


def test_reasons_read_as_english_not_as_python():
    _c, why = _score("Will Gavin Newsom be the Democratic Presidential nominee?",
                     "Gavin Newsom",
                     "Will Gavin Newsom win the 2028 Democratic presidential nomination?")
    blob = " ".join(why)
    assert "[" not in blob and "'" not in blob, blob
    assert "both name" in blob



def test_announcing_a_run_is_not_the_same_question_as_winning():
    """Live 2026-08-25: scored 0.59 confident and rendered 23.0c against 1.95c
    — a 21c "difference" between declaring a candidacy and winning an
    election. The Kalshi side states no stage, so the general-election stage
    on the Polymarket side had nothing to clash with."""
    conf, why = _score(
        "Will Donald Trump announce a run for President of the United States?",
        "Donald Trump",
        "Will Donald Trump win the 2028 US Presidential Election?")
    assert conf < cv.CONFIDENT, (conf, why)


def test_a_combined_market_is_not_its_own_single_leg():
    """Live 2026-08-25: scored 0.78 confident. P(A and B) <= P(A) by
    construction, so pairing a joint against one of its legs manufactures a
    permanent one-directional spread rather than an occasional wrong number."""
    conf, why = _score(
        "Will Gavin Newsom and JD Vance be the 2028 Democratic and Republican nominees?",
        "Gavin Newsom",
        "Will Gavin Newsom win the 2028 Democratic presidential nomination?")
    assert conf < cv.CONFIDENT, (conf, why)


def test_the_conjunction_rule_reads_names_not_any_and():
    assert cv.conjoins_names("Will Gavin Newsom and JD Vance be the nominees?")
    assert cv.conjoins_names("Will Trump and Putin meet before 2027?")
    assert not cv.conjoins_names(
        "Will Chelsea win the 2026-27 English Premier League (EPL) Championship?")
    assert not cv.conjoins_names("Will Trump acquire Greenland before 2027?")


def test_both_sides_combining_names_still_pair():
    """The rule fires on a DIFFERENCE, not on the presence of a conjunction —
    two venues asking the same combined question must still match."""
    conf, _why = _score(
        "Will Trump and Putin meet before 2027?", "",
        "Will Trump and Putin meet before 2027?")
    assert conf >= cv.CONFIDENT


def test_neither_side_stating_a_stage_is_not_penalised():
    """Sports and event markets state no stage at all. Silence on both sides is
    agreement by omission and must stay unpenalised."""
    conf, _ = _score("Will Trump buy Greenland? Before 2027", "",
                     "Will Trump acquire Greenland before 2027?")
    assert conf >= cv.CONFIDENT
