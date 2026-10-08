"""A sold contract is priced on the side that was sold.

Kalshi's fills now carry `outcome_side`: "buy-yes and sell-no produce 'yes';
buy-no and sell-yes produce 'no'", and the deprecated `side` follows it. The
real-key smoke test of 6.4.0 bought 1 YES at 2c and sold it at 1c; the fill
came back as side 'no', the parser read its no_price (99c), and the ledger
booked a +$0.96 profit on a trade that lost about 2c. A false profit feeds the
History page, the stats card, the daily loss stop and an agent's record.
"""
from __future__ import annotations

import trader
from trader import _parse_kalshi_fill

SELL_YES_1C = {
    "order_id": "o-1", "ticker": "KXT", "count_fp": "1.00",
    "outcome_side": "no", "book_side": "ask", "side": "no", "action": "sell",
    "yes_price_dollars": "0.0100", "no_price_dollars": "0.9900",
}
BUY_YES_2C = {
    "order_id": "o-0", "ticker": "KXT", "count_fp": "1.00",
    "outcome_side": "yes", "book_side": "bid", "side": "yes", "action": "buy",
    "yes_price_dollars": "0.0200", "no_price_dollars": "0.9800",
}


def test_sell_yes_reads_the_yes_price_when_the_order_side_is_known():
    fp = _parse_kalshi_fill(SELL_YES_1C, default_side="yes")
    assert fp["price_cents"] == 1
    assert fp["side"] == "yes"


def test_sell_yes_without_an_order_side_flips_outcome_back():
    fp = _parse_kalshi_fill(SELL_YES_1C)
    assert (fp["side"], fp["price_cents"]) == ("yes", 1)


def test_buys_are_unchanged():
    assert _parse_kalshi_fill(BUY_YES_2C, default_side="yes")["price_cents"] == 2
    assert _parse_kalshi_fill(BUY_YES_2C)["price_cents"] == 2


def test_sell_no_reads_the_no_price():
    sell_no = dict(SELL_YES_1C, outcome_side="yes", book_side="bid", side="yes",
                   yes_price_dollars="0.9700", no_price_dollars="0.0300")
    assert _parse_kalshi_fill(sell_no, default_side="no")["price_cents"] == 3
    assert _parse_kalshi_fill(sell_no)["price_cents"] == 3


def test_legacy_fill_with_only_side_still_parses():
    legacy = {"count": 2, "side": "no", "no_price": 40, "yes_price": 60}
    assert _parse_kalshi_fill(legacy)["price_cents"] == 40
    assert trader._fill_contract_side(legacy) == "no"
