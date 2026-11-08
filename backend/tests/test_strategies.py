import numpy as np
import pytest

from app.bots import indicators as ind
from app.bots.runner import hours_allowed
from app.bots.strategies import RISK, STRATEGIES


def bars_from(closes):
    c = np.array(closes, dtype=float)
    return {"open": c, "high": c * 1.001, "low": c * 0.999, "close": c, "tick_volume": np.ones(len(c))}


def test_sma_and_ema():
    x = np.arange(1, 11, dtype=float)
    assert np.isnan(ind.sma(x, 3)[1])
    assert ind.sma(x, 3)[-1] == pytest.approx(9.0)
    assert ind.ema(x, 3)[2] == pytest.approx(2.0)


def test_rsi_extremes_and_reference():
    up = np.arange(1, 40, dtype=float)
    assert ind.rsi(up, 14)[-1] == 100.0
    # Reference values from Wilder's original example (period 14)
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28, 46.28,
              46.00, 46.03, 46.41, 46.22, 45.64]
    r = ind.rsi(np.array(closes), 14)
    assert r[14] == pytest.approx(70.46, abs=0.1)
    assert r[-1] == pytest.approx(57.9, abs=0.6)


def test_validation_errors():
    with pytest.raises(ValueError, match="меньше медленной"):
        STRATEGIES["sma_cross"].validate({"fast": 30, "slow": 10})
    with pytest.raises(ValueError):
        STRATEGIES["rsi_reversion"].validate({"period": 1})
    assert RISK.validate({})["volume"] == 0.01
    with pytest.raises(ValueError):
        RISK.validate({"volume": 0})


def test_sma_cross_signals():
    s = STRATEGIES["sma_cross"]
    p = s.validate({"fast": 3, "slow": 6})
    down_then_up = [10, 9.8, 9.6, 9.4, 9.2, 9.0, 8.8, 8.6, 8.4, 8.2, 8.0, 10.5]
    d = s.evaluate(bars_from(down_then_up), p, 0, {})
    assert d.target == 1
    up_then_down = [8, 8.2, 8.4, 8.6, 8.8, 9.0, 9.2, 9.4, 9.6, 9.8, 10.0, 7.5]
    assert s.evaluate(bars_from(up_then_down), p, 0, {}).target == -1
    p2 = s.validate({"fast": 3, "slow": 6, "allow_short": False})
    assert s.evaluate(bars_from(up_then_down), p2, 1, {}).target == 0
    assert s.evaluate(bars_from(list(range(1, 20))), p, 0, {}).target is None


def test_rsi_reversion_signals():
    s = STRATEGIES["rsi_reversion"]
    p = s.validate({"period": 5})
    falling = [100 - i for i in range(20)] + [95]
    assert s.evaluate(bars_from(falling), p, 0, {}).target == 1
    rising = [100 + i for i in range(20)] + [104]
    assert s.evaluate(bars_from(rising), p, 0, {}).target == -1


def test_donchian_breakout():
    s = STRATEGIES["donchian_breakout"]
    p = s.validate({"entry": 5, "exit": 3})
    flat = [10.0] * 10
    assert s.evaluate(bars_from(flat + [11.0]), p, 0, {}).target == 1
    assert s.evaluate(bars_from(flat + [9.0]), p, 0, {}).target == -1
    assert s.evaluate(bars_from(flat + [10.0]), p, 0, {}).target is None


def test_ml_logistic_learns_pattern():
    s = STRATEGIES["ml_logistic"]
    p = s.validate({"train_bars": 300, "lags": 2, "threshold": 0.6, "min_accuracy": 0.55})
    # Deterministic alternating returns: up-day always followed by down-day -> perfectly learnable
    c, closes = 100.0, []
    for i in range(500):
        c *= 1.002 if i % 2 == 0 else 0.999
        closes.append(c)
    st = {}
    d = s.evaluate(bars_from(closes), p, 0, st)
    assert d.values["val_accuracy"] > 0.9
    assert d.target in (1, -1)
    # last move was down (i=499 odd) -> next expected up
    assert d.target == 1 and d.values["prob_up"] > 0.6
    assert "weights" in st["model"]


def test_ml_logistic_refuses_noise():
    s = STRATEGIES["ml_logistic"]
    p = s.validate({"train_bars": 300, "min_accuracy": 0.7})
    rng = np.random.default_rng(1)
    closes = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, 500)))
    d = s.evaluate(bars_from(closes), p, 0, {})
    assert d.target is None and "ниже порога" in d.reason


def test_trading_hours():
    assert hours_allowed(5, 0, 24)
    assert hours_allowed(8, 7, 17) and not hours_allowed(18, 7, 17)
    assert hours_allowed(23, 22, 6) and hours_allowed(3, 22, 6) and not hours_allowed(12, 22, 6)
