from __future__ import annotations

import pytest

import crypto15m_trader
import script_backtest
import script_sandbox
from script_sandbox import CompiledScript, ScriptError


VALID = """\
# krypt-script v1
# name: Test
# description: A test script.

def decide(ctx):
    ml = ctx["minsLeft"]
    if ml is None or ml > 3.0:
        return None
    return {"side": "up", "price": "ask"}
"""



def test_valid_script_compiles_and_decides():
    s = CompiledScript("t1", VALID, trusted=False)
    assert "decide" in s.hooks
    assert s.call("decide", {"minsLeft": 2.0}) == {"side": "up", "price": "ask"}
    assert s.call("decide", {"minsLeft": None}) is None


def test_header_parsed():
    meta = script_sandbox.parse_header(VALID)
    assert meta["version"] == "v1"
    assert meta["name"] == "Test"
    assert meta["description"] == "A test script."


def test_find_ctx_fields():
    assert script_sandbox.find_ctx_fields(VALID) == ["minsLeft"]


def test_requires_an_entry_hook():
    errs = script_sandbox.validate("x = 1\n")
    assert any("must define at least one" in e for e in errs)


@pytest.mark.parametrize("code,frag", [
    ("import os\ndef decide(ctx):\n    return None\n", "imports are not allowed"),
    ("def decide(ctx):\n    return eval('1')\n", "not available"),
    ("def decide(ctx):\n    return ctx.__class__\n", "not allowed"),
    ("def decide(ctx):\n    open('x')\n", "not available"),
    ("class A:\n    pass\ndef decide(ctx):\n    return None\n", "classes are not supported"),
    ("def decide(ctx):\n    global x\n    return None\n", "global/nonlocal"),
    ("def decide(ctx):\n    return undefined_name\n", "unknown name"),
])
def test_sandbox_rejections(code, frag):
    errs = script_sandbox.validate(code)
    assert errs and any(frag in e for e in errs), errs


def test_generator_frame_escape_blocked():
    code = (
        "def decide(ctx):\n"
        "    g = (x for x in [1])\n"
        "    return g.gi_frame\n"
    )
    errs = script_sandbox.validate(code)
    assert any("gi_frame" in e for e in errs)


def test_str_format_escape_blocked():
    code = 'def decide(ctx):\n    return "{0}".format(ctx)\n'
    errs = script_sandbox.validate(code)
    assert any(".format" in e or "'format'" in e or "format" in e for e in errs)


def test_trusted_skips_sandbox_but_keeps_contract():
    code = "import math\ndef decide(ctx):\n    return None\n"
    assert script_sandbox.validate(code, trusted=False)
    assert script_sandbox.validate(code, trusted=True) == []
    assert script_sandbox.validate("x = 1\n", trusted=True)



def test_busy_loop_is_killed():
    code = (
        "def decide(ctx):\n"
        "    n = 0\n"
        "    while True:\n"
        "        n = n + 1\n"
    )
    s = CompiledScript("t2", code, trusted=False)
    with pytest.raises(script_sandbox.ScriptBudgetExceeded):
        s.call("decide", {}, budget_ms=20.0)


def test_runtime_error_wrapped_as_script_error():
    code = "def decide(ctx):\n    return ctx[\"missing\"]\n"
    s = CompiledScript("t3", code, trusted=False)
    with pytest.raises(ScriptError):
        s.call("decide", {})


def test_state_persists_between_calls():
    code = (
        "def decide(ctx):\n"
        "    state[\"n\"] = state.get(\"n\", 0) + 1\n"
        "    return None\n"
    )
    s = CompiledScript("t4", code, trusted=False)
    s.call("decide", {})
    s.call("decide", {})
    assert s.state["n"] == 2


def test_log_lines_captured_and_capped():
    code = "def decide(ctx):\n    log(\"hello\", 1)\n    return None\n"
    s = CompiledScript("t5", code, trusted=False)
    s.call("decide", {})
    assert s.drain_logs() == ["hello 1"]
    assert s.drain_logs() == []



def test_sanitize_intent():
    ok, err = script_backtest.sanitize_intent({"side": "up", "price": "ask"})
    assert err is None and ok == {"side": "up", "price": "ask"}
    ok, err = script_backtest.sanitize_intent(
        {"side": "down", "price": 55, "size": 3,
         "take_profit_pct": 0.2, "stop_loss_cents": 30, "reason": "x"})
    assert err is None
    assert ok["price"] == 55 and ok["size"] == 3
    assert script_backtest.sanitize_intent(None) == (None, None)
    for bad in ({"side": "yes", "price": "ask"}, {"side": "up", "price": 0},
                {"side": "up", "price": 150}, {"side": "up"},
                {"side": "up", "price": "ask", "size": 0},
                {"side": "up", "price": "ask", "take_profit_pct": 99},
                "buy up", 42):
        _, err = script_backtest.sanitize_intent(bad)
        assert err, bad


def test_sanitize_manage():
    assert script_backtest.sanitize_manage(None) == (None, None)
    assert script_backtest.sanitize_manage("hold") == (None, None)
    assert script_backtest.sanitize_manage("sell") == ({"action": "sell"}, None)
    ok, err = script_backtest.sanitize_manage(
        {"action": "update", "stop_loss_cents": 40})
    assert err is None and ok == {"action": "update", "stop_loss_cents": 40}
    _, err = script_backtest.sanitize_manage({"action": "yolo"})
    assert err


def test_sanitize_signal_action():
    assert script_backtest.sanitize_signal_action(None) == (None, None)
    assert script_backtest.sanitize_signal_action(True) == ({"follow": True}, None)
    ok, err = script_backtest.sanitize_signal_action({"follow": True, "sizeUsd": 10})
    assert err is None and ok["sizeUsd"] == 10.0
    _, err = script_backtest.sanitize_signal_action({"follow": True, "sizeUsd": 0})
    assert err



def _pos(**kw):
    base = {"status": "filled", "filled_contracts": 5, "avg_entry_cents": 50.0,
            "cost_usd": 2.5}
    base.update(kw)
    return base


_CFG = {"crypto15m_exit_threshold": 0.0, "crypto15m_stop_loss_pct": 0.0,
        "crypto15m_take_profit_cents": 0}


def test_row_stop_loss_override():
    pos = _pos(sl_cents=30)
    assert crypto15m_trader.should_stop_loss(pos, 0.30, _CFG) is True
    assert crypto15m_trader.should_stop_loss(pos, 0.31, _CFG) is False
    assert crypto15m_trader.should_stop_loss(_pos(), 0.01, _CFG) is False


def test_row_take_profit_override():
    pos = _pos(tp_pct=0.2)
    assert crypto15m_trader.should_take_profit(pos, 0.60, _CFG) is True
    assert crypto15m_trader.should_take_profit(pos, 0.59, _CFG) is False
    assert crypto15m_trader.should_take_profit(_pos(), 0.99, _CFG) is False
