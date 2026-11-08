"""Vectorised technical indicators (numpy)."""
from __future__ import annotations

import numpy as np


def sma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if n <= 0 or len(x) < n:
        return out
    c = np.cumsum(np.insert(x.astype(float), 0, 0.0))
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    if n <= 0 or len(x) < n:
        return out
    k = 2.0 / (n + 1)
    out[n - 1] = float(np.mean(x[:n]))
    for i in range(n, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out


def rsi(x: np.ndarray, n: int = 14) -> np.ndarray:
    """Wilder's RSI."""
    out = np.full(len(x), np.nan)
    if len(x) <= n:
        return out
    d = np.diff(x.astype(float))
    gain, loss = np.clip(d, 0, None), np.clip(-d, 0, None)
    ag, al = gain[:n].mean(), loss[:n].mean()

    def val(g: float, l: float) -> float:
        if l == 0:
            return 100.0 if g > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + g / l)

    out[n] = val(ag, al)
    for i in range(n, len(d)):
        ag = (ag * (n - 1) + gain[i]) / n
        al = (al * (n - 1) + loss[i]) / n
        out[i + 1] = val(ag, al)
    return out


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = 14) -> np.ndarray:
    out = np.full(len(close), np.nan)
    if len(close) <= n:
        return out
    prev = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    out[n - 1] = tr[:n].mean()
    for i in range(n, len(close)):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def rolling_max(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = np.max(x[i - n + 1: i + 1])
    return out


def rolling_min(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        out[i] = np.min(x[i - n + 1: i + 1])
    return out
