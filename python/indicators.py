from __future__ import annotations

from typing import Optional

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
RSI_PERIOD = 14


def _floats(values) -> list[float]:
    out: list[float] = []
    for v in values or []:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f == f:
            out.append(f)
    return out


def ema_series(values: list[float], period: int) -> list[float]:
    n = len(values)
    if period <= 0 or n < period:
        return []
    k = 2.0 / (period + 1.0)
    seed = sum(values[:period]) / period
    out = [seed]
    prev = seed
    for v in values[period:]:
        prev = v * k + prev * (1.0 - k)
        out.append(prev)
    return out


def macd(
    closes: list[float],
    fast: int = MACD_FAST,
    slow: int = MACD_SLOW,
    signal: int = MACD_SIGNAL,
) -> Optional[dict]:
    vals = _floats(closes)
    if len(vals) < slow + signal:
        return None
    ema_fast = ema_series(vals, fast)
    ema_slow = ema_series(vals, slow)
    if not ema_fast or not ema_slow:
        return None
    m = min(len(ema_fast), len(ema_slow))
    macd_line = [ema_fast[-m + i] - ema_slow[-m + i] for i in range(m)]
    signal_line = ema_series(macd_line, signal)
    if len(signal_line) < 2:
        return None
    sm = min(len(macd_line), len(signal_line))
    hist = [macd_line[-sm + i] - signal_line[-sm + i] for i in range(sm)]
    last, prev = hist[-1], hist[-2]
    cross = 1 if (prev <= 0 < last) else (-1 if (prev >= 0 > last) else 0)
    return {
        "macd": round(macd_line[-1], 6),
        "signal": round(signal_line[-1], 6),
        "hist": round(last, 6),
        "cross": cross,
    }


def rsi(closes: list[float], period: int = RSI_PERIOD) -> Optional[float]:
    vals = _floats(closes)
    if len(vals) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    for i in range(1, period + 1):
        ch = vals[i] - vals[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses -= ch
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(vals)):
        ch = vals[i] - vals[i - 1]
        gain = ch if ch > 0 else 0.0
        loss = -ch if ch < 0 else 0.0
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


SIGMA_WINDOW = 30


def sigma1m(closes: list[float], window: int = SIGMA_WINDOW) -> Optional[float]:
    vals = _floats(closes)
    if len(vals) < window + 1:
        return None
    rets = []
    for i in range(len(vals) - window, len(vals)):
        prev = vals[i - 1]
        if prev <= 0:
            return None
        rets.append((vals[i] - prev) / prev)
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    if var < 0:
        return None
    return var ** 0.5


def sma(closes: list[float], period: int) -> Optional[float]:
    vals = _floats(closes)
    if period <= 0 or len(vals) < period:
        return None
    return sum(vals[-period:]) / period


def ema_last(closes: list[float], period: int) -> Optional[float]:
    series = ema_series(_floats(closes), period)
    return series[-1] if series else None


def vwap(closes: list[float], volumes: Optional[list[float]], window: int) -> Optional[float]:
    vals = _floats(closes)
    if window <= 0 or len(vals) < window:
        return None
    cw = vals[-window:]
    vols = _floats(volumes) if volumes is not None else []
    if len(vols) >= window:
        vw = vols[-window:]
        denom = sum(vw)
        if denom > 0:
            return sum(c * v for c, v in zip(cw, vw)) / denom
    return sum(cw) / window


def pct_change(closes: list[float], lookback: int) -> Optional[float]:
    vals = _floats(closes)
    if lookback <= 0 or len(vals) < lookback + 1:
        return None
    prev = vals[-1 - lookback]
    if prev == 0:
        return None
    return (vals[-1] - prev) / prev * 100.0


def _rel_pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return (a - b) / b * 100.0


def compute(closes, volumes=None) -> dict:
    vals = _floats(closes)
    m = macd(vals)
    spot = vals[-1] if vals else None
    vwap1h = vwap(vals, volumes, 60)
    ema12 = ema_last(vals, 12)
    ema1 = ema_last(vals, 1)
    sma20 = sma(vals, 20)
    sma50 = sma(vals, 50)
    sma5 = sma(vals, 5)
    return {
        "macd": m["macd"] if m else None,
        "macdSignal": m["signal"] if m else None,
        "macdHist": m["hist"] if m else None,
        "macdCross": m["cross"] if m else None,
        "rsi": rsi(vals),
        "sigma1m": sigma1m(vals),
        "vwap1h": round(vwap1h, 6) if vwap1h is not None else None,
        "ema12": round(ema12, 6) if ema12 is not None else None,
        "sma20": round(sma20, 6) if sma20 is not None else None,
        "sma50": round(sma50, 6) if sma50 is not None else None,
        "priceVsVwapPct": _round(_rel_pct(spot, vwap1h)),
        "ema12VsSma20Pct": _round(_rel_pct(ema12, sma20)),
        "ema1VsSma5Pct": _round(_rel_pct(ema1, sma5)),
        "velocity1mPct": _round(pct_change(vals, 1)),
        "change5mPct": _round(pct_change(vals, 5)),
        "change15mPct": _round(pct_change(vals, 15)),
    }


def _round(v: Optional[float]) -> Optional[float]:
    return round(v, 6) if v is not None else None
