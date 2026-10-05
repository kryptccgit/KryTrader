from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CTParams:
    enabled: bool = False
    min_arm_pct: float = 0.0
    unarmed_stop_pct: float = 0.0
    reversal_pct: float = 0.0
    noise_pct: float = 0.0
    override: bool = False

    def active(self) -> bool:
        return bool(self.enabled) and (
            self.reversal_pct > 0 or self.unarmed_stop_pct > 0
        )


@dataclass
class CTState:
    entry_mark: float
    peak_mark: float
    armed: bool = False
    closed: bool = False

    @classmethod
    def open(cls, entry_mark: float) -> "CTState":
        return cls(entry_mark=float(entry_mark), peak_mark=float(entry_mark))


def params_from_cfg(cfg: dict, prefix: str) -> CTParams:
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
    if side == "short":
        return 2.0 * float(entry_px) - float(price)
    return float(price)


def step(state: CTState, mark: float, p: CTParams) -> tuple[bool, str]:
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
