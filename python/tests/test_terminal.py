from __future__ import annotations

import terminal


def test_price_cents_accepts_the_tradeable_range():
    assert terminal.price_cents(1) == 1.0
    assert terminal.price_cents(50) == 50.0
    assert terminal.price_cents(99) == 99.0
    assert terminal.price_cents("94") == 94.0


def test_zero_bid_is_an_empty_book_side_not_a_zero_cent_bid():
    assert terminal.price_cents(0) is None
    assert terminal.price_cents("0.00") is None


def test_hundred_cent_ask_is_an_empty_book_side():
    assert terminal.price_cents(100) is None


def test_price_cents_rejects_junk_without_defaulting():
    for junk in (None, "", "abc", float("nan"), float("inf"), True, [1]):
        assert terminal.price_cents(junk) is None


def test_deci_cent_resolution_survives():
    assert terminal.price_cents(1.1) == 1.1
    assert terminal.price_cents(98.7) == 98.7


def test_dollar_strings_are_the_live_wire_format():
    assert terminal._dollar_price("0.9400") == 94.0
    assert terminal._dollar_price("0.0110") == 1.1
    assert terminal._dollar_price("0.0000") is None
    assert terminal._dollar_price("1.0000") is None
    assert terminal._dollar_price(None) is None


def test_zero_volume_is_a_real_zero_but_missing_volume_is_unknown():
    assert terminal._count(0) == 0
    assert terminal._count("0.00") == 0
    assert terminal._count(None) is None
    assert terminal._count("") is None


LIVE_MARKET = {
    "ticker": "KXTEST-26AUG24-A", "event_ticker": "KXTEST-26AUG24",
    "title": "Test market", "yes_sub_title": "Above 100", "status": "active",
    "yes_bid_dollars": "0.4700", "yes_ask_dollars": "0.4800",
    "no_bid_dollars": "0.5200", "no_ask_dollars": "0.5300",
    "last_price_dollars": "0.4750", "volume_fp": "1234.00",
    "volume_24h_fp": "56.00", "open_interest_fp": "789.00",
    "yes_bid_size_fp": "40.00", "yes_ask_size_fp": "12.00",
    "close_time": "2030-01-01T00:00:00Z", "can_close_early": False,
}

LEGACY_MARKET = {
    "ticker": "KXTEST-26AUG24-A", "title": "Test market", "status": "active",
    "yes_bid": 47, "yes_ask": 48, "last_price": 47, "volume": 1234,
    "volume_24h": 56, "open_interest": 789,
}


def test_market_row_reads_the_live_dollar_shape():
    r = terminal.market_row(LIVE_MARKET)
    assert (r["yesBid"], r["yesAsk"]) == (47.0, 48.0)
    assert r["lastPrice"] == 47.5
    assert (r["volume"], r["volume24h"], r["openInterest"]) == (1234, 56, 789)
    assert (r["yesBidSize"], r["yesAskSize"]) == (40, 12)


def test_market_row_still_reads_the_legacy_cent_shape():
    r = terminal.market_row(LEGACY_MARKET)
    assert (r["yesBid"], r["yesAsk"], r["lastPrice"]) == (47.0, 48.0, 47.0)
    assert r["volume"] == 1234


def test_spread_and_mid_need_both_sides():
    r = terminal.market_row(LIVE_MARKET)
    assert (r["spreadCents"], r["midCents"]) == (1.0, 47.5)

    one_sided = dict(LIVE_MARKET)
    one_sided["yes_ask_dollars"] = "0.0000"
    one_sided["no_bid_dollars"] = "0.0000"
    r2 = terminal.market_row(one_sided)
    assert r2["yesAsk"] is None
    assert r2["spreadCents"] is None and r2["midCents"] is None


def test_a_missing_side_is_never_derived_from_another_missing_side():
    empty = {"ticker": "T", "title": "t", "yes_bid_dollars": "0.0000",
             "yes_ask_dollars": "0.0000", "no_bid_dollars": "0.0000",
             "no_ask_dollars": "0.0000"}
    r = terminal.market_row(empty)
    assert r["yesBid"] is None and r["yesAsk"] is None
    assert r["noBid"] is None and r["noAsk"] is None


def test_category_and_series_come_from_the_parent_event():
    r = terminal.market_row(LIVE_MARKET, ctx={
        "category": "Sports", "seriesTicker": "KXTEST", "eventTicker": "KXTEST-26AUG24",
    })
    assert r["category"] == "Sports"
    assert r["seriesTicker"] == "KXTEST"


def test_provenance_is_recorded_only_for_fields_that_resolved():
    sparse = {"ticker": "T", "title": "t", "status": "active",
              "yes_bid_dollars": "0.4700"}
    r = terminal.market_row(sparse, source="kalshi-ws")
    assert r["sources"]["yesBid"] == "kalshi-ws"
    assert "lastPrice" not in r["sources"]


def test_sourced_fields_match_the_typescript_contract():
    assert terminal.SOURCED_FIELDS == (
        "yesBid", "yesAsk", "lastPrice", "volume", "volume24h",
        "openInterest", "liquidity", "status",
    )


def test_candles_are_sorted_and_deduplicated():
    raw = [
        {"end_period_ts": 300, "price": {"close": "0.50"}},
        {"end_period_ts": 100, "price": {"close": "0.10"}},
        {"end_period_ts": 200, "price": {"close": "0.20"}},
        {"end_period_ts": 200, "price": {"close": "0.25"}},
    ]
    out = terminal.normalize_candles(raw)
    assert [c["ts"] for c in out] == [100, 200, 300]
    assert out[1]["close"] == 25.0


def test_a_period_with_no_trades_keeps_its_slot_with_null_prices():
    raw = [
        {"end_period_ts": 100, "price": {"close": "0.40"}},
        {"end_period_ts": 160, "price": {"close": None},
         "yes_bid": {"close": "0.39"}, "yes_ask": {"close": "0.42"}},
    ]
    out = terminal.normalize_candles(raw)
    assert len(out) == 2
    assert out[1]["close"] is None
    assert (out[1]["yesBidClose"], out[1]["yesAskClose"]) == (39.0, 42.0)


def test_candles_read_both_tier_shapes():
    hist = [{"end_period_ts": 1, "price": {"close": "0.94"}}]
    live = [{"end_period_ts": 1, "price": {"close_dollars": "0.9400"}}]
    assert terminal.normalize_candles(hist)[0]["close"] == 94.0
    assert terminal.normalize_candles(live)[0]["close"] == 94.0


def test_candles_without_a_usable_timestamp_are_dropped():
    raw = [{"price": {"close": "0.40"}}, {"end_period_ts": 0}, {"end_period_ts": 5}]
    assert [c["ts"] for c in terminal.normalize_candles(raw)] == [5]


def _row(**kw):
    base = {"ticker": "T", "title": "t", "volume": 0, "minutesToClose": 10,
            "openTime": "2026-01-01T00:00:00Z", "yesBid": 40.0, "yesAsk": 41.0}
    base.update(kw)
    base.setdefault("eventTicker", f"EV-{base['ticker']}")
    return base


def test_an_unknown_metric_is_skipped_and_counted_not_sorted_to_the_bottom():
    rows = [_row(ticker="A", volume=100), _row(ticker="B", volume=None)]
    ranked, skipped, _ = terminal._rank(rows, "volume", 10)
    assert [r["ticker"] for r in ranked] == ["A"]
    assert skipped == 1


def test_a_genuine_zero_is_excluded_without_being_counted_as_unknown():
    rows = [_row(ticker="A", volume=100), _row(ticker="B", volume=0)]
    ranked, skipped, _ = terminal._rank(rows, "volume", 10)
    assert [r["ticker"] for r in ranked] == ["A"]
    assert skipped == 0


def test_closing_soon_excludes_markets_nobody_can_act_on():
    rows = [
        _row(ticker="A", minutesToClose=5),
        _row(ticker="B", minutesToClose=1, yesBid=None, yesAsk=None),
        _row(ticker="C", minutesToClose=-3),
    ]
    ranked, skipped, _ = terminal._rank(rows, "closing", 10)
    assert [r["ticker"] for r in ranked] == ["A"]
    assert skipped == 0


def test_closing_soon_skips_a_market_with_no_close_time():
    rows = [_row(ticker="A", minutesToClose=5), _row(ticker="B", minutesToClose=None)]
    ranked, skipped, _ = terminal._rank(rows, "closing", 10)
    assert [r["ticker"] for r in ranked] == ["A"]
    assert skipped == 1


def test_closing_soon_drops_a_one_sided_phantom_quote_nobody_has_traded():
    rows = [
        _row(ticker="REAL", minutesToClose=5),
        _row(ticker="RUNG", minutesToClose=1, yesBid=None, yesAsk=1.0,
             volume=0, openInterest=0, lastPrice=None),
    ]
    ranked, skipped, dropped = terminal._rank(rows, "closing", 10)
    assert [r["ticker"] for r in ranked] == ["REAL"]
    assert dropped["untradeable"] == 1
    assert skipped == 0


def test_a_one_sided_market_survives_if_somebody_actually_traded_it():
    traded = _row(ticker="T1", minutesToClose=2, yesBid=None, yesAsk=97.0,
                  volume=140, openInterest=0)
    held = _row(ticker="H1", minutesToClose=3, yesBid=None, yesAsk=97.0,
                volume=0, openInterest=25)
    ranked, _, dropped = terminal._rank([traded, held], "closing", 10)
    assert [r["ticker"] for r in ranked] == ["T1", "H1"]
    assert dropped["untradeable"] == 0


def test_unknown_volume_is_not_treated_as_evidence_of_trading():
    r = _row(ticker="U", minutesToClose=2, yesBid=None, yesAsk=1.0,
             volume=None, openInterest=None)
    ranked, _, dropped = terminal._rank([r], "closing", 10)
    assert ranked == []
    assert dropped["untradeable"] == 1


def test_one_event_cannot_fill_the_whole_column():
    ladder = [_row(ticker=f"KXNDX-T{i}", eventTicker="KXNDX-H1400",
                   minutesToClose=260.3) for i in range(50)]
    other = _row(ticker="OTHER", eventTicker="EV-OTHER", minutesToClose=300.0)
    ranked, _, dropped = terminal._rank(ladder + [other], "closing", 10)
    tickers = [r["ticker"] for r in ranked]
    assert len(tickers) == terminal.EVENT_CAP + 1
    assert "OTHER" in tickers, "the cap must not starve other events"
    assert dropped["collapsed"] == 50 - terminal.EVENT_CAP


def test_markets_with_no_event_ticker_are_not_collapsed_together():
    rows = [_row(ticker=f"M{i}", eventTicker=None, minutesToClose=5 + i)
            for i in range(10)]
    kept, collapsed = terminal._cap_per_event(rows, 3)
    assert len(kept) == 10
    assert collapsed == 0

def test_candle_volume_and_open_interest_read_the_fixed_point_fields():
    raw = [{
        "end_period_ts": 1787666340,
        "volume_fp": "243864.78",
        "open_interest_fp": "412028.01",
        "price": {"close_dollars": "0.0100", "open_dollars": "0.0440"},
    }]
    c = terminal.normalize_candles(raw)[0]
    assert c["volume"] == 243865
    assert c["openInterest"] == 412028
    assert c["close"] == 1.0


def test_a_candle_that_genuinely_traded_nothing_still_reports_zero_not_none():
    raw = [{"end_period_ts": 1, "volume_fp": "0.00", "open_interest_fp": "0.00"}]
    c = terminal.normalize_candles(raw)[0]
    assert c["volume"] == 0 and c["openInterest"] == 0


def test_a_candle_with_no_volume_field_at_all_is_unknown():
    raw = [{"end_period_ts": 1, "price": {"close_dollars": "0.5000"}}]
    c = terminal.normalize_candles(raw)[0]
    assert c["volume"] is None and c["openInterest"] is None


def test_settlement_value_is_read_from_the_dollar_field_and_reported_in_cents():
    row = terminal.market_row({"ticker": "X", "settlement_value_dollars": "1.0000"})
    assert row["settlementValue"] == 100.0
    legacy = terminal.market_row({"ticker": "X", "settlement_value": 100})
    assert legacy["settlementValue"] == 100.0
    absent = terminal.market_row({"ticker": "X"})
    assert absent["settlementValue"] is None


def test_a_live_quote_that_omits_volume_cannot_zero_out_the_rest_volume():
    import kalshi_ws
    assert kalshi_ws._fp_or_none(None) is None
    assert kalshi_ws._fp_or_none("0.00") == 0.0

    c0 = kalshi_ws._Client()
    c0._on_ticker({"msg": {"market_ticker": "QQ", "yes_bid_dollars": "0.4100",
                           "yes_ask_dollars": "0.4200"}})
    assert c0.quotes["QQ"]["volume"] is None
    assert c0.quotes["QQ"]["open_interest"] is None
    assert c0.quotes["QQ"]["yes_bid_cents"] == 41.0
    c0._on_ticker({"msg": {"market_ticker": "QQ", "volume_fp": "0.00"}})
    assert c0.quotes["QQ"]["volume"] == 0.0, "a real zero still reports zero"

    row = terminal.market_row({"ticker": "ZZ", "volume_fp": "5000",
                               "yes_bid_dollars": "0.4000",
                               "yes_ask_dollars": "0.4100"})
    assert row["volume"] == 5000
    c = kalshi_ws._client
    saved_q, saved_conn = dict(c.quotes), c.connected
    try:
        c.quotes["ZZ"] = {
            "yes_bid_cents": 41.0, "yes_ask_cents": 42.0,
            "last_cents": None, "volume": None, "open_interest": None,
        }
        c.connected = True
        out = terminal._apply_live_quote(dict(row))
    finally:
        c.quotes.clear()
        c.quotes.update(saved_q)
        c.connected = saved_conn
    assert out["volume"] == 5000, "the websocket had nothing to say about volume"
    assert out["yesBid"] == 41.0


def test_the_tape_labels_a_block_trade_rather_than_hiding_it():
    row = terminal._tape_row(
        {"trade_id": "t1", "ticker": "X", "taker_side": "yes",
         "count_fp": "500", "yes_price_dollars": "0.4000",
         "is_block_trade": True}, "kalshi-rest")
    assert row["isBlockTrade"] is True
    assert row["contracts"] == 500, "it is still a real print and still shown"

    normal = terminal._tape_row(
        {"trade_id": "t2", "ticker": "X", "taker_side": "yes",
         "count_fp": "5", "yes_price_dollars": "0.4000"}, "kalshi-rest")
    assert normal["isBlockTrade"] is False

def test_ladder_is_best_first_with_a_running_cumulative():
    levels, depth = terminal._ladder([[40, 10], [42, 5], [41, 20]])
    assert [lv["priceCents"] for lv in levels] == [42, 41, 40]
    assert [lv["cumulative"] for lv in levels] == [5, 25, 35]
    assert depth == 35


def test_ladder_discards_unusable_levels_rather_than_zeroing_them():
    levels, depth = terminal._ladder([[0, 10], [40, 0], [41, 7], ["x", 3]])
    assert [lv["priceCents"] for lv in levels] == [41]
    assert depth == 7


def test_empty_ladder_reports_unknown_depth_not_zero_depth():
    levels, depth = terminal._ladder([])
    assert levels == [] and depth is None


FULL_MARKET = {
    "ticker": "KXTEST-1", "status": "active",
    "rules_primary": "The market resolves YES if the published index closes at "
                     "or above the strike on the settlement date, per the named "
                     "source. Otherwise it resolves NO.",
    "rules_secondary": "Settlement follows the exchange rulebook.",
    "can_close_early": False,
    "close_time": "2030-01-01T00:00:00Z",
    "expiration_time": "2030-01-01T00:30:00Z",
    "strike_type": "greater", "floor_strike": 100.0,
    "settlement_timer_seconds": 60,
}
FULL_SERIES = {"settlement_sources": [{"name": "CF Benchmarks", "url": "https://x"}]}
GOOD_BOOK = {"spreadCents": 1.0, "yesDepthContracts": 500, "noDepthContracts": 400}


def test_risk_scores_only_over_the_checks_that_resolved():
    r = terminal.resolution_risk(
        ticker="KXTEST-1", market=FULL_MARKET, series=FULL_SERIES,
        event={"mutually_exclusive": True},
        book_snapshot=GOOD_BOOK,
        siblings=[{"midCents": 40.0}, {"midCents": 60.0}],
    )
    assert r["resolvedCount"] == r["totalCount"] == len(r["checks"])
    assert r["score"] == 100
    assert f"{r['resolvedCount']} of {r['totalCount']}" in r["scoreNote"]


def test_risk_refuses_to_print_a_score_when_too_little_resolved():
    r = terminal.resolution_risk(ticker="KXTEST-1", market=None, series=None)
    assert r["resolvedCount"] < terminal.MIN_RESOLVED_CHECKS
    assert r["score"] is None
    assert "resolved" in r["scoreNote"]


def test_unresolved_checks_are_never_treated_as_passes():
    partial = terminal.resolution_risk(
        ticker="T", market=FULL_MARKET, series=FULL_SERIES, book_snapshot=None,
    )
    full = terminal.resolution_risk(
        ticker="T", market=FULL_MARKET, series=FULL_SERIES,
        event={"mutually_exclusive": True}, book_snapshot=GOOD_BOOK,
        siblings=[{"midCents": 50.0}, {"midCents": 50.0}],
    )
    assert partial["resolvedCount"] < full["resolvedCount"]
    assert partial["score"] == full["score"] == 100


def test_coherence_does_not_apply_to_a_non_exclusive_event():
    r = terminal.resolution_risk(
        ticker="T", market=FULL_MARKET, series=FULL_SERIES,
        event={"mutually_exclusive": False},
        siblings=[{"midCents": 80.0}, {"midCents": 75.0}],
    )
    coherence = next(c for c in r["checks"] if c["id"] == "coherence")
    assert coherence["verdict"] == "unknown"
    assert "not mutually exclusive" in coherence["detail"]


def test_coherence_flags_legs_that_contradict_each_other():
    r = terminal.resolution_risk(
        ticker="T", market=FULL_MARKET, series=FULL_SERIES,
        event={"mutually_exclusive": True},
        siblings=[{"midCents": 80.0}, {"midCents": 75.0}],
    )
    coherence = next(c for c in r["checks"] if c["id"] == "coherence")
    assert coherence["verdict"] == "warn"


def test_discretionary_wording_is_flagged_and_labelled_as_a_heuristic():
    m = dict(FULL_MARKET)
    m["rules_primary"] = ("Resolves YES if, at the sole discretion of the "
                          "exchange, the event has approximately occurred.")
    r = terminal.resolution_risk(ticker="T", market=m, series=FULL_SERIES)
    check = next(c for c in r["checks"] if c["id"] == "rules_ambiguity")
    assert check["verdict"] == "warn"
    assert "keyword scan" in check["detail"]


def test_a_market_with_no_rules_text_fails_that_check():
    m = dict(FULL_MARKET)
    m["rules_primary"] = ""
    r = terminal.resolution_risk(ticker="T", market=m, series=FULL_SERIES)
    assert next(c for c in r["checks"] if c["id"] == "rules_present")["verdict"] == "fail"


def test_the_event_settlement_source_wins_over_the_series_one():
    r = terminal.resolution_risk(
        ticker="T", market=FULL_MARKET, series=FULL_SERIES,
        event={"settlement_sources": [{"name": "ESPN", "url": "https://espn.com"}]},
    )
    assert [s["name"] for s in r["settlementSources"]] == ["ESPN"]


def test_a_source_with_nothing_to_say_does_not_erase_one_that_has():
    r = terminal.resolution_risk(
        ticker="T", market=FULL_MARKET, series=FULL_SERIES,
        event={"settlement_sources": []},
    )
    assert [s["name"] for s in r["settlementSources"]] == ["CF Benchmarks"]


def test_the_venue_is_stated_rather_than_implied():
    r = terminal.resolution_risk(ticker="T", market=FULL_MARKET, series=FULL_SERIES)
    assert r["venue"] == "kalshi"
    assert "CFTC" in r["venueNote"]


MARK = {"midCents": 60.0, "title": "Test", "eventTicker": "E", "status": "active",
        "closeTime": None, "lastPrice": 59.0}


def test_position_cost_basis_comes_from_kalshis_ledger():
    p = {"ticker": "T", "position_fp": "10", "market_exposure_dollars": "4.70",
         "fees_paid_dollars": "0.08", "realized_pnl_dollars": "0.00"}
    r = terminal._position_row(p, MARK)
    assert r["reconciled"] is True
    assert r["avgCostCents"] == 47.0
    assert r["costBasisUsd"] == 4.70
    assert r["marketValueUsd"] == 6.0
    assert r["unrealizedUsd"] == 1.30


def test_a_position_with_no_readable_cost_basis_is_unknown_not_break_even():
    p = {"ticker": "T", "position_fp": "10"}
    r = terminal._position_row(p, MARK)
    assert r["reconciled"] is False
    assert r["avgCostCents"] is None
    assert r["costBasisUsd"] is None
    assert r["unrealizedUsd"] is None
    assert r["reconcileNote"]


def test_a_short_position_marks_off_the_mirrored_price():
    p = {"ticker": "T", "position_fp": "-10", "market_exposure_dollars": "3.50"}
    r = terminal._position_row(p, MARK)
    assert r["side"] == "no"
    assert r["markCents"] == 40.0
    assert r["marketValueUsd"] == 4.0


def test_an_unpriceable_market_leaves_the_mark_unknown():
    p = {"ticker": "T", "position_fp": "10", "market_exposure_dollars": "4.70"}
    r = terminal._position_row(p, None)
    assert r["markCents"] is None
    assert r["marketValueUsd"] is None
    assert r["unrealizedUsd"] is None
    assert r["costBasisUsd"] == 4.70


CFG = {"terminal_max_contracts": 1000, "terminal_max_notional_usd": 500.0}
OPEN_MARKET = {"status": "active", "minutesToClose": 600.0, "canCloseEarly": False}
BOOK = {"yesBid": 47.0, "yesAsk": 48.0, "spreadCents": 1.0}


def _preview(**over):
    req = {"ticker": "T", "side": "yes", "action": "buy", "count": 10,
           "priceCents": 48}
    req.update(over)
    return terminal.preview(req, cfg=CFG, authed=True, market=OPEN_MARKET,
                            book_snapshot=BOOK, position=None)


def test_ticket_prices_a_buy_with_fees_and_a_breakeven():
    pv = _preview()
    assert pv["costUsd"] == 4.80
    assert pv["feeUsd"] > 0
    assert pv["totalUsd"] == round(4.80 + pv["feeUsd"], 2)
    assert pv["maxPayoutUsd"] == 10.0
    assert pv["maxLossUsd"] == pv["totalUsd"]
    assert 0.48 < pv["breakevenProb"] < 0.50
    assert not pv["blockers"]


def test_a_price_outside_one_to_ninety_nine_is_blocked_with_an_explanation():
    for bad in (0, 100, -5, None):
        pv = _preview(priceCents=bad)
        assert any("1c and 99c" in b for b in pv["blockers"]), bad


def test_size_and_notional_caps_are_enforced_in_the_backend():
    assert any("cap of 1000" in b for b in _preview(count=1001)["blockers"])
    assert any("notional cap" in b for b in _preview(count=600, priceCents=99)["blockers"])


def test_the_two_caps_bind_at_different_places():
    cheap = _preview(count=1001, priceCents=2)
    assert any("cap of 1000" in b for b in cheap["blockers"])
    assert not any("notional" in b for b in cheap["blockers"])
    rich = _preview(count=800, priceCents=90)
    assert any("notional cap" in b for b in rich["blockers"])
    assert not any("cap of 1000" in b for b in rich["blockers"])


def test_trading_without_credentials_is_blocked():
    pv = terminal.preview({"ticker": "T", "side": "yes", "action": "buy",
                           "count": 1, "priceCents": 50},
                          cfg=CFG, authed=False, market=OPEN_MARKET,
                          book_snapshot=BOOK, position=None)
    assert any("credentials" in b for b in pv["blockers"])


def test_a_closed_market_is_blocked():
    closed = {"status": "closed", "minutesToClose": -1.0}
    pv = terminal.preview({"ticker": "T", "side": "yes", "action": "buy",
                           "count": 1, "priceCents": 50},
                          cfg=CFG, authed=True, market=closed,
                          book_snapshot=BOOK, position=None)
    assert pv["blockers"]


def test_selling_what_you_do_not_hold_is_blocked_with_the_right_advice():
    pv = _preview(action="sell", priceCents=47)
    blocker = next(b for b in pv["blockers"] if "no YES contracts" in b)
    assert "BUY NO" in blocker


def test_selling_more_than_you_hold_is_blocked():
    pos = {"contracts": 5, "side": "yes", "avgCostCents": 40.0}
    pv = terminal.preview({"ticker": "T", "side": "yes", "action": "sell",
                           "count": 10, "priceCents": 47},
                          cfg=CFG, authed=True, market=OPEN_MARKET,
                          book_snapshot=BOOK, position=pos)
    assert any("cannot sell 10" in b for b in pv["blockers"])


def test_a_sale_without_a_cost_basis_reports_unknown_pnl_not_zero():
    pos = {"contracts": 10, "side": "yes", "avgCostCents": None}
    pv = terminal.preview({"ticker": "T", "side": "yes", "action": "sell",
                           "count": 10, "priceCents": 60},
                          cfg=CFG, authed=True, market=OPEN_MARKET,
                          book_snapshot=BOOK, position=pos)
    assert not pv["blockers"]
    assert pv["maxProfitUsd"] is None
    assert any("not zero" in w for w in pv["warnings"])


def test_a_sale_with_a_cost_basis_reports_realised_pnl():
    pos = {"contracts": 10, "side": "yes", "avgCostCents": 40.0}
    pv = terminal.preview({"ticker": "T", "side": "yes", "action": "sell",
                           "count": 10, "priceCents": 60},
                          cfg=CFG, authed=True, market=OPEN_MARKET,
                          book_snapshot=BOOK, position=pos)
    assert pv["maxProfitUsd"] == round(2.0 - pv["feeUsd"], 2)


def test_marketability_is_measured_against_the_live_book():
    assert _preview(priceCents=48)["marketableNow"] is True
    assert _preview(priceCents=45)["marketableNow"] is False
    assert any("rests until" in w for w in _preview(priceCents=45)["warnings"])


def test_a_wide_spread_is_surfaced_as_a_warning():
    wide = {"yesBid": 30.0, "yesAsk": 60.0, "spreadCents": 30.0}
    pv = terminal.preview({"ticker": "T", "side": "yes", "action": "buy",
                           "count": 1, "priceCents": 60},
                          cfg=CFG, authed=True, market=OPEN_MARKET,
                          book_snapshot=wide, position=None)
    assert any("spread is 30" in w for w in pv["warnings"])


def test_no_book_is_a_warning_rather_than_a_silent_pass():
    pv = terminal.preview({"ticker": "T", "side": "yes", "action": "buy",
                           "count": 1, "priceCents": 50},
                          cfg=CFG, authed=True, market=OPEN_MARKET,
                          book_snapshot=None, position=None)
    assert any("order book has not loaded" in w for w in pv["warnings"])


def test_interest_expires_so_the_recorder_is_not_an_unbounded_leak():
    terminal._ws_interest.clear()
    terminal.note_interest("KXA-1")
    assert terminal.subscribed_tickers() == {"KXA-1"}
    terminal._ws_interest["KXA-1"] -= terminal.WS_SUBSCRIPTION_TTL + 1
    assert terminal.subscribed_tickers() == set()


def test_interest_normalises_the_ticker_and_ignores_blanks():
    terminal._ws_interest.clear()
    terminal.note_interest(" kxa-1 ")
    terminal.note_interest("")
    assert terminal.subscribed_tickers() == {"KXA-1"}


def test_the_order_book_wins_over_the_market_record_and_the_drift_is_reported():
    row = terminal.market_row(LIVE_MARKET)
    book = {"yesBid": 53.0, "yesAsk": 54.0, "source": "kalshi-ws",
            "observedAt": "2026-08-24T00:00:00Z"}
    merged, drift = terminal._apply_book_quote(row, book)
    assert (merged["yesBid"], merged["yesAsk"]) == (53.0, 54.0)
    assert (merged["noBid"], merged["noAsk"]) == (46.0, 47.0)
    assert merged["spreadCents"] == 1.0 and merged["midCents"] == 53.5
    assert merged["sources"]["yesAsk"] == "kalshi-ws"
    assert drift == 6.0


def test_no_drift_is_reported_when_the_two_reads_agree():
    row = terminal.market_row(LIVE_MARKET)
    _merged, drift = terminal._apply_book_quote(
        row, {"yesBid": 47.0, "yesAsk": 48.0, "source": "kalshi-rest"})
    assert drift == 0.0


def test_a_missing_book_never_erases_the_market_records_quote():
    row = terminal.market_row(LIVE_MARKET)
    for empty in (None, {}, {"yesBid": None, "yesAsk": None}):
        merged, drift = terminal._apply_book_quote(dict(row), empty)
        assert (merged["yesBid"], merged["yesAsk"]) == (47.0, 48.0)
        assert drift is None


def test_a_one_sided_book_only_overwrites_the_side_it_has():
    row = terminal.market_row(LIVE_MARKET)
    merged, _ = terminal._apply_book_quote(
        row, {"yesBid": 53.0, "yesAsk": None, "source": "kalshi-rest"})
    assert merged["yesBid"] == 53.0
    assert merged["yesAsk"] == 48.0


def test_known_tickers_are_fetched_in_batches_not_one_request_each(monkeypatch):
    import asyncio
    import kalshi_api

    calls: list[dict] = []

    async def fake_get(url, params=None):
        calls.append(params or {})
        return {"markets": [{"ticker": t}
                            for t in (params or {})["tickers"].split(",")]}

    monkeypatch.setattr(kalshi_api, "_pub_get", fake_get)

    tickers = [f"KX-{i}" for i in range(120)]
    out = asyncio.run(kalshi_api.fetch_markets_by_tickers(tickers))

    assert set(out) == set(tickers)
    assert len(calls) == 3
    assert all("," in c["tickers"] for c in calls)


def test_batched_lookup_deduplicates_and_drops_blanks(monkeypatch):
    import asyncio
    import kalshi_api

    asked: list[str] = []

    async def fake_get(url, params=None):
        asked.extend((params or {})["tickers"].split(","))
        return {"markets": []}

    monkeypatch.setattr(kalshi_api, "_pub_get", fake_get)
    asyncio.run(kalshi_api.fetch_markets_by_tickers(["A", "A", "", None, "B"]))
    assert asked == ["A", "B"]


def test_a_batch_that_returns_nothing_yields_no_rows_rather_than_raising(monkeypatch):
    import asyncio
    import kalshi_api

    async def fake_get(url, params=None):
        return None

    monkeypatch.setattr(kalshi_api, "_pub_get", fake_get)
    assert asyncio.run(kalshi_api.fetch_markets_by_tickers(["A"])) == {}


def test_the_caps_never_block_selling_a_position_you_hold():
    pos = {"contracts": 900, "side": "yes", "avgCostCents": 50.0}
    pv = terminal.preview(
        {"ticker": "T", "side": "yes", "action": "sell",
         "count": 900, "priceCents": 95},
        cfg=CFG, authed=True, market=OPEN_MARKET,
        book_snapshot=BOOK, position=pos,
    )
    assert not pv["blockers"]
    assert any("never against getting out" in w for w in pv["warnings"])


def test_the_caps_still_block_an_oversized_entry():
    pv = terminal.preview(
        {"ticker": "T", "side": "yes", "action": "buy",
         "count": 900, "priceCents": 95},
        cfg=CFG, authed=True, market=OPEN_MARKET,
        book_snapshot=BOOK, position={"contracts": 900, "side": "yes",
                                      "avgCostCents": 50.0},
    )
    assert any("notional cap" in b for b in pv["blockers"])


def test_selling_more_than_held_is_still_blocked_and_not_cap_exempt():
    pos = {"contracts": 10, "side": "yes", "avgCostCents": 50.0}
    pv = terminal.preview(
        {"ticker": "T", "side": "yes", "action": "sell",
         "count": 2000, "priceCents": 95},
        cfg=CFG, authed=True, market=OPEN_MARKET,
        book_snapshot=BOOK, position=pos,
    )
    assert any("cannot sell 2000" in b for b in pv["blockers"])
    assert any("cap of 1000" in b for b in pv["blockers"])
