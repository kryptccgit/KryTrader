from __future__ import annotations

import asyncio

import pytest

import remote
import remote_discord
import remote_telegram

CFG = {"terminal_max_contracts": 1000, "terminal_max_notional_usd": 500.0}


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean():
    remote.STATE.pending.clear()
    remote.STATE.hits.clear()
    remote.STATE.telegram_code = None
    yield


def _say(text, sender="discord:1", trading=False, authed=True):
    return run(remote.handle(text, sender, cfg=CFG, authed=authed,
                             trading_enabled=trading))


def test_trading_commands_are_refused_while_trading_is_off():
    for cmd in ("buy KXA yes 1 50", "sell KXA yes 1 50", "cancel abc",
                "confirm 1234"):
        out = _say(cmd, trading=False)
        assert "switched OFF" in out, cmd


def test_reading_still_works_while_trading_is_off():
    out = _say("help", trading=False)
    assert "Reading:" in out
    assert "buy" in out


def test_an_order_is_quoted_and_waits_for_a_code(monkeypatch):
    import terminal
    sent = []

    async def fake_book(t):
        return {"yesBid": 44.0, "yesAsk": 45.0, "spreadCents": 1.0,
                "source": "kalshi-rest"}
    async def fake_pf(authed):
        return {"positions": []}
    async def fake_submit(req, *, cfg, authed):
        sent.append(req)
        return {"ok": True, "message": "Filled 10 at 45c"}
    async def fake_gate(fn, *a, **k):
        return {"ticker": "KXA", "title": "A market", "status": "active",
                "yes_bid": 44, "yes_ask": 45, "close_time": "2030-01-01T00:00:00Z"}

    monkeypatch.setattr(terminal, "book", fake_book)
    monkeypatch.setattr(terminal, "portfolio", fake_pf)
    monkeypatch.setattr(terminal, "submit", fake_submit)
    monkeypatch.setattr(terminal._public_gate, "run", fake_gate)

    out = _say("buy KXA yes 10 45", trading=True)
    assert "confirm" in out.lower()
    assert sent == [], "the order must not be sent by the first message"

    code = remote.STATE.pending["discord:1"].code
    out2 = _say(f"confirm {code}", trading=True)
    assert len(sent) == 1
    assert sent[0]["count"] == 10 and sent[0]["priceCents"] == 45
    assert "Sent" in out2


def test_a_wrong_confirmation_code_does_not_trade_and_does_not_discard(monkeypatch):
    import terminal
    sent = []

    async def fake_book(t):
        return {"yesBid": 44.0, "yesAsk": 45.0, "source": "kalshi-rest"}
    async def fake_pf(authed):
        return {"positions": []}
    async def fake_submit(req, *, cfg, authed):
        sent.append(req)
        return {"ok": True, "message": "ok"}
    async def fake_gate(fn, *a, **k):
        return {"ticker": "KXA", "title": "t", "status": "active",
                "close_time": "2030-01-01T00:00:00Z"}
    monkeypatch.setattr(terminal, "book", fake_book)
    monkeypatch.setattr(terminal, "portfolio", fake_pf)
    monkeypatch.setattr(terminal, "submit", fake_submit)
    monkeypatch.setattr(terminal._public_gate, "run", fake_gate)

    _say("buy KXA yes 10 45", trading=True)
    out = _say("confirm 0000", trading=True)
    assert sent == []
    assert "does not match" in out
    assert "discord:1" in remote.STATE.pending


def test_a_stale_confirmation_is_refused(monkeypatch):
    p = remote.Pending(code="1234", req={"ticker": "KXA"}, summary="s")
    p.created -= remote.CONFIRM_TTL + 1
    remote.STATE.pending["discord:1"] = p
    out = _say("confirm 1234", trading=True)
    assert "expired" in out
    assert "discord:1" not in remote.STATE.pending


def test_one_users_pending_order_cannot_be_confirmed_by_another():
    remote.STATE.pending["discord:1"] = remote.Pending(
        code="1234", req={"ticker": "KXA"}, summary="s")
    out = _say("confirm 1234", sender="telegram:999", trading=True)
    assert "Nothing waiting" in out
    assert "discord:1" in remote.STATE.pending


def test_a_blocked_order_never_reaches_the_pending_state(monkeypatch):
    import terminal

    async def fake_book(t):
        return {"yesBid": 44.0, "yesAsk": 45.0, "source": "kalshi-rest"}
    async def fake_pf(authed):
        return {"positions": []}
    async def fake_gate(fn, *a, **k):
        return {"ticker": "KXA", "title": "t", "status": "active",
                "close_time": "2030-01-01T00:00:00Z"}
    monkeypatch.setattr(terminal, "book", fake_book)
    monkeypatch.setattr(terminal, "portfolio", fake_pf)
    monkeypatch.setattr(terminal._public_gate, "run", fake_gate)

    out = _say("buy KXA yes 99999 99", trading=True)
    assert "Cannot place that" in out
    assert not remote.STATE.pending


def test_malformed_orders_are_explained_not_executed():
    assert "Usage" in _say("buy", trading=True)
    assert "Side must be" in _say("buy KXA maybe 1 50", trading=True)
    assert "whole number" in _say("buy KXA yes ten 50", trading=True)


def test_a_pairing_code_is_single_use():
    code = remote.new_pair_code()
    assert remote.check_pair_code(code) is True
    assert remote.check_pair_code(code) is False


def test_a_pairing_code_expires():
    code = remote.new_pair_code()
    remote.STATE.telegram_code_at -= remote.PAIR_CODE_TTL + 1
    assert remote.pair_code_valid() is None
    assert remote.check_pair_code(code) is False


def test_a_wrong_pairing_code_is_refused_and_does_not_burn_the_real_one():
    code = remote.new_pair_code()
    assert remote.check_pair_code("XXXXXX") is False
    assert remote.pair_code_valid() == code


def test_regenerating_invalidates_the_previous_code():
    first = remote.new_pair_code()
    second = remote.new_pair_code()
    assert first != second
    assert remote.check_pair_code(first) is False


def test_pairing_codes_avoid_ambiguous_glyphs():
    for _ in range(40):
        assert not (set(remote.new_pair_code()) & set("O0I1"))


def test_a_flood_is_dropped_rather_than_executed():
    for _ in range(remote.RATE_MAX):
        assert remote.rate_ok("discord:1") is True
    assert remote.rate_ok("discord:1") is False
    out = _say("positions")
    assert "Too many messages" in out


def test_the_rate_limit_is_per_sender():
    for _ in range(remote.RATE_MAX + 1):
        remote.rate_ok("discord:1")
    assert remote.rate_ok("telegram:2") is True


def test_unknown_values_render_as_a_dash_on_the_phone_too():
    assert remote._cents(None) == "—"
    assert remote._usd(None) == "—"
    assert remote._cents(0) == "0c"
    assert remote._usd(0) == "$0.00"


def test_discord_ignores_everyone_but_the_paired_user():
    bot = remote_discord.DiscordBot()
    bot.user_id = "111"
    seen = []

    async def on_cmd(text, sender):
        seen.append((text, sender))
        return "ok"
    bot._on_command = on_cmd

    async def deliver(author_id, guild=None, is_bot=False, content="positions"):
        await bot._handle({
            "op": 0, "t": "MESSAGE_CREATE",
            "d": {"author": {"id": author_id, "bot": is_bot},
                  "content": content, "channel_id": "c1",
                  **({"guild_id": guild} if guild else {})},
        })

    async def scenario():
        await deliver("222")
        await deliver("111", guild="g1")
        await deliver("111", is_bot=True)
    run(scenario())
    assert seen == [], "only a DM from the paired user may reach the engine"


def test_discord_accepts_a_dm_from_the_paired_user(monkeypatch):
    bot = remote_discord.DiscordBot()
    bot.user_id = "111"
    seen = []

    async def on_cmd(text, sender):
        seen.append((text, sender))
        return ""
    bot._on_command = on_cmd

    async def scenario():
        await bot._handle({
            "op": 0, "t": "MESSAGE_CREATE",
            "d": {"author": {"id": "111"}, "content": "positions",
                  "channel_id": "c1"},
        })
    run(scenario())
    assert seen == [("positions", "discord:111")]


def test_telegram_ignores_groups_and_other_chats():
    bot = remote_telegram.TelegramBot()
    bot.chat_id = "555"
    seen = []

    async def on_cmd(text, sender):
        seen.append(sender)
        return ""
    bot._on_command = on_cmd

    async def scenario():
        await bot._handle({"message": {"chat": {"id": "555", "type": "group"},
                                       "text": "positions"}})
        await bot._handle({"message": {"chat": {"id": "999", "type": "private"},
                                       "text": "positions"}})
    run(scenario())
    assert seen == []


def test_telegram_pairs_only_with_a_valid_code():
    bot = remote_telegram.TelegramBot()
    sent = []

    async def fake_send(text, chat=None):
        sent.append((chat, text))
        return True
    bot.send = fake_send
    bot._check_code = remote.check_pair_code
    bot._on_paired = lambda cid: None

    code = remote.new_pair_code()

    async def scenario():
        await bot._handle({"message": {"chat": {"id": "77", "type": "private"},
                                       "text": "pair BADCODE"}})
        assert bot.chat_id == ""
        await bot._handle({"message": {"chat": {"id": "77", "type": "private"},
                                       "text": f"pair {code}"}})
    run(scenario())
    assert bot.chat_id == "77"
    assert any("Paired" in t for _c, t in sent)


def test_an_unpaired_telegram_bot_tells_a_stranger_nothing_useful():
    bot = remote_telegram.TelegramBot()
    sent = []

    async def fake_send(text, chat=None):
        sent.append(text)
        return True
    bot.send = fake_send
    bot._check_code = remote.check_pair_code

    async def scenario():
        await bot._handle({"message": {"chat": {"id": "77", "type": "private"},
                                       "text": "balance"}})
    run(scenario())
    assert sent and "not paired" in sent[0]
    assert "$" not in sent[0]


def test_long_replies_are_split_on_line_boundaries():
    text = "\n".join(f"line {i}" for i in range(500))
    chunks = list(remote_discord._chunks(text, 200))
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    assert "".join(chunks) == text


def test_a_factory_reset_disarms_standing_instructions(tmp_path, monkeypatch):
    import sqlite3
    import db
    path = tmp_path / "fr.sqlite"
    monkeypatch.setattr(db, "db_path", lambda: path)
    monkeypatch.setattr(db, "backup_research", lambda *a, **k: None)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.executescript(db.SCHEMA)
    db.insert_terminal_rule(c, {
        "kind": "stop", "ticker": "KXA-1", "side": "yes",
        "threshold_cents": 30.0, "direction": "below", "kalshi_env": "demo",
    })
    c.commit()
    assert len(db.list_terminal_rules(c, "demo", armed_only=True)) == 1

    db.factory_reset()
    assert db.list_terminal_rules(c, "demo") == []
    c.close()
