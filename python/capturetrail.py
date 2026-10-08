"""CaptureTrail — an adaptive trailing-exit engine.

A user-suggested exit strategy for high-volatility windows (perps + 15m
crypto binaries). It is a *trailing take-profit* with an armed/unarmed phase:

    unarmed  → a tight protective stop just below entry (small loss cap)
    armed    → after peak profit clears `min_arm_pct`, switch to trailing the
               profit peak; exit when the mark gives back `reversal_pct` of
               that peak (a momentum-reversal exit, not a fixed target)
    sticky   → once it fires, the trade stays closed (no re-entry that window)

The engine is deliberately UNIT-AGNOSTIC. It reasons about a single
"favorable mark" `m` — a number that RISES as the position gains — plus the
entry mark. Callers normalise their own price into that space:

    15m binary (long the held side):  m = side probability (0..1),  em = entry cost
    perps long:                       m = price,                     em = entry price
    perps short:                      m = 2*em - price  (mirror; short gains as px falls)

Everything downstream (peak, drawdown, arm threshold) is expressed as a
fraction of the entry mark, so the same parameters mean the same thing in
either domain even though the raw units differ.

This module is pure and side-effect free (state is an explicit dataclass the
caller owns) so it drops into the live loop AND the backtester unchanged —
the same honesty contract replay.py keeps.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CTParams:
    """A CaptureTrail configuration, already normalised to fractions.

    All *_pct fields are fractions of the entry mark (0.055 = 5.5%), except
    `reversal_pct` which is a fraction of the *peak* mark (that is what a
    trailing stop trails). 0 disables the individual mechanism.
    """
    enabled: bool = False
    min_arm_pct: float = 0.0
    unarmed_stop_pct: float = 0.0
    reversal_pct: float = 0.0
    noise_pct: float = 0.0
    override: bool = False

    def active(self) -> bool:
        """Would this config ever act? Off if disabled or every trigger is 0."""
        return bool(self.enabled) and (
            self.reversal_pct > 0 or self.unarmed_stop_pct > 0
        )


@dataclass
class CTState:
    """Per-position CaptureTrail state. The caller creates one at entry and
    threads it through each tick. `closed` latches the sticky-sell."""
    entry_mark: float
    peak_mark: float
    armed: bool = False
    closed: bool = False

    @classmethod
    def open(cls, entry_mark: float) -> "CTState":
        return cls(entry_mark=float(entry_mark), peak_mark=float(entry_mark))


def params_from_cfg(cfg: dict, prefix: str) -> CTParams:
    """Read a CaptureTrail block from `cfg` under `<prefix>_ct_*` keys.

    prefix is the domain: "crypto15m" or "perps_strat". Missing keys fall back
    to a disabled default so partially-configured profiles never half-arm.
    """
    def f(key: str, default: float = 0.0) -> float:
        try:
            return float(cfg.get(f"{prefix}_ct_{key}", default) or 0.0)
        except (TypeError, ValueError):
            return default

    return CTParams(
        enabled=bool(cfg.get(f"{prefix}_ct_enabled", False)),
        min_arm_pct=max(0.0, f("min_arm_pct")),
        unarmed_stop_pct=max(0.0, f("unarmed_stop_pct")),
        reversal_pct=max(0.0, f("reversal_pct")),
        noise_pct=max(0.0, f("noise_pct")),
        override=bool(cfg.get(f"{prefix}_ct_override", False)),
    )


def favorable_mark(side: str, price: float, entry_px: float) -> float:
    """Normalise a raw price into the engine's favorable-mark space for the
    perps domain. Long: the price itself. Short: mirrored about entry so the
    mark rises as price falls. Binary callers pass the held-side probability
    directly and don't need this."""
    if side == "short":
        return 2.0 * float(entry_px) - float(price)
    return float(price)


def step(state: CTState, mark: float, p: CTParams) -> tuple[bool, str]:
    """Advance one tick. Updates `state` in place (peak, armed, closed) and
    returns (should_exit, reason). Reasons: "ct_trail" (armed reversal),
    "ct_unarmed_stop" (pre-arm protective stop), "" (hold).

    Idempotent once closed: a closed state always returns (False, "") so a
    caller that keeps stepping after booking the exit won't re-fire.
    """
    if not p.enabled or state.closed:
        return False, ""
    if mark is None or not (state.entry_mark > 0):
        return False, ""

    if mark > state.peak_mark:
        state.peak_mark = mark

    if not state.armed:
        peak_gain = (state.peak_mark - state.entry_mark) / state.entry_mark
        if p.min_arm_pct <= 0 or peak_gain >= p.min_arm_pct:
            state.armed = True

    giveback = state.peak_mark - mark
    noise_floor = p.noise_pct * state.entry_mark

    if state.armed:
        if p.reversal_pct > 0 and state.peak_mark > 0:
            drawdown = (state.peak_mark - mark) / state.peak_mark
            if drawdown >= p.reversal_pct and giveback >= noise_floor:
                state.closed = True
                return True, "ct_trail"
    else:
        if p.unarmed_stop_pct > 0:
            loss = (state.entry_mark - mark) / state.entry_mark
            if loss >= p.unarmed_stop_pct and giveback >= noise_floor:
                state.closed = True
                return True, "ct_unarmed_stop"

    return False, ""
