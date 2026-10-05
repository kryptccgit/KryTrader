from __future__ import annotations

import capturetrail as ct


def _run(marks, p, entry=None):
    st = ct.CTState.open(entry if entry is not None else marks[0])
    for i, m in enumerate(marks):
        done, reason = ct.step(st, m, p)
        if done:
            return i, reason, st
    return None, "", st


def test_disabled_never_fires():
    p = ct.CTParams(enabled=False, reversal_pct=0.05)
    i, _, _ = _run([1.0, 2.0, 1.0, 0.5], p)
    assert i is None


def test_all_zero_triggers_is_inactive():
    p = ct.CTParams(enabled=True)
    assert not p.active()
    i, _, _ = _run([1.0, 2.0, 0.1], p)
    assert i is None


def test_peak_tracking_and_trailing_exit():
    p = ct.CTParams(enabled=True, reversal_pct=0.10)
    marks = [1.00, 1.50, 2.00, 1.95, 1.85, 1.79]
    i, reason, st = _run(marks, p, entry=1.00)
    assert reason == "ct_trail"
    assert i == 5
    assert st.peak_mark == 2.00
    assert st.closed is True


def test_no_exit_while_within_reversal_band():
    p = ct.CTParams(enabled=True, reversal_pct=0.10)
    i, _, _ = _run([1.0, 1.1, 1.2, 1.15, 1.25, 1.20], p, entry=1.0)
    assert i is None


def test_arm_latch_requires_min_profit():
    p = ct.CTParams(enabled=True, min_arm_pct=0.05, reversal_pct=0.02)
    i, _, st = _run([1.00, 1.02, 1.03, 1.00, 0.98], p, entry=1.00)
    assert i is None
    assert st.armed is False


def test_arm_then_trail():
    p = ct.CTParams(enabled=True, min_arm_pct=0.05, reversal_pct=0.02)
    marks = [1.00, 1.06, 1.05, 1.038]
    i, reason, st = _run(marks, p, entry=1.00)
    assert st.armed is True
    assert reason == "ct_trail"
    assert i == 3


def test_unarmed_stop_caps_early_loss():
    p = ct.CTParams(enabled=True, min_arm_pct=0.10, unarmed_stop_pct=0.04,
                    reversal_pct=0.02)
    i, reason, _ = _run([1.00, 0.99, 0.955], p, entry=1.00)
    assert reason == "ct_unarmed_stop"
    assert i == 2


def test_armed_position_ignores_unarmed_stop():
    p = ct.CTParams(enabled=True, min_arm_pct=0.03, unarmed_stop_pct=0.01,
                    reversal_pct=0.50)
    i, _, st = _run([1.00, 1.04, 0.98], p, entry=1.00)
    assert st.armed is True
    assert i is None


def test_noise_band_suppresses_tiny_giveback():
    p = ct.CTParams(enabled=True, reversal_pct=0.03, noise_pct=0.05)
    i, _, _ = _run([1.00, 1.02, 0.985], p, entry=1.00)
    assert i is None


def test_sticky_close_is_idempotent():
    p = ct.CTParams(enabled=True, reversal_pct=0.10)
    st = ct.CTState.open(1.00)
    ct.step(st, 2.00, p)
    done, _ = ct.step(st, 1.70, p)
    assert done and st.closed
    for m in (2.50, 3.00, 0.10):
        again, reason = ct.step(st, m, p)
        assert again is False and reason == ""


def test_short_mirror_via_favorable_mark():
    entry = 100.0
    prices = [100.0, 98.0, 96.0, 97.0, 97.5]
    marks = [ct.favorable_mark("short", px, entry) for px in prices]
    assert marks[2] > marks[0]
    p = ct.CTParams(enabled=True, reversal_pct=0.01)
    i, reason, _ = _run(marks, p, entry=ct.favorable_mark("short", entry, entry))
    assert reason == "ct_trail"
    assert i == 4


def test_params_from_cfg_reads_prefixed_block():
    cfg = {
        "crypto15m_ct_enabled": True,
        "crypto15m_ct_min_arm_pct": 0.03,
        "crypto15m_ct_unarmed_stop_pct": 0.15,
        "crypto15m_ct_reversal_pct": 0.055,
        "crypto15m_ct_noise_pct": 0.01,
        "crypto15m_ct_override": True,
    }
    p = ct.params_from_cfg(cfg, "crypto15m")
    assert p.enabled and p.override
    assert p.min_arm_pct == 0.03
    assert p.unarmed_stop_pct == 0.15
    assert p.reversal_pct == 0.055
    assert p.noise_pct == 0.01
    assert p.active()


def test_params_from_cfg_defaults_disabled():
    p = ct.params_from_cfg({}, "perps_strat")
    assert not p.enabled
    assert not p.active()
