"""Trading strategies. Each strategy works only on CLOSED bars received from MT5.

``evaluate`` returns a :class:`Decision` with a *target* exposure:
  1 = long, -1 = short, 0 = flat, None = keep current exposure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from . import indicators as ind


@dataclass
class Decision:
    target: int | None
    reason: str
    values: dict[str, Any] = field(default_factory=dict)


@dataclass
class Param:
    key: str
    label: str
    type: str  # int | float | bool
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    help: str = ""

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


class Strategy:
    key = ""
    title = ""
    description = ""
    params: list[Param] = []

    def defaults(self) -> dict:
        return {p.key: p.default for p in self.params}

    def validate(self, values: dict | None) -> dict:
        values = dict(values or {})
        out = {}
        for p in self.params:
            v = values.get(p.key, p.default)
            try:
                if p.type == "int":
                    v = int(v)
                elif p.type == "float":
                    v = float(v)
                elif p.type == "bool":
                    v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Параметр «{p.label}»: неверное значение {v!r}") from exc
            if p.type in ("int", "float"):
                if p.min is not None and v < p.min:
                    raise ValueError(f"Параметр «{p.label}» должен быть ≥ {p.min}")
                if p.max is not None and v > p.max:
                    raise ValueError(f"Параметр «{p.label}» должен быть ≤ {p.max}")
            out[p.key] = v
        self.check(out)
        return out

    def check(self, params: dict) -> None:
        pass

    def min_bars(self, params: dict) -> int:
        raise NotImplementedError

    def evaluate(self, bars: dict[str, np.ndarray], params: dict, position: int, state: dict) -> Decision:
        raise NotImplementedError

    def describe(self) -> dict:
        return {"key": self.key, "title": self.title, "description": self.description,
                "params": [p.as_dict() for p in self.params]}


def _short(target: int, allow_short: bool) -> int:
    return target if target >= 0 or allow_short else 0


class SmaCross(Strategy):
    key = "sma_cross"
    title = "Пересечение скользящих средних"
    description = "Покупка при пересечении быстрой MA снизу вверх медленной, продажа — при обратном пересечении."
    params = [
        Param("fast", "Быстрая MA", "int", 10, 2, 500),
        Param("slow", "Медленная MA", "int", 30, 3, 1000),
        Param("use_ema", "Использовать EMA", "bool", False),
        Param("allow_short", "Разрешить шорт", "bool", True),
    ]

    def check(self, p: dict) -> None:
        if p["fast"] >= p["slow"]:
            raise ValueError("Быстрая MA должна быть меньше медленной")

    def min_bars(self, p: dict) -> int:
        return p["slow"] + 3

    def evaluate(self, bars, p, position, state) -> Decision:
        c = bars["close"]
        f = (ind.ema if p["use_ema"] else ind.sma)(c, p["fast"])
        s = (ind.ema if p["use_ema"] else ind.sma)(c, p["slow"])
        vals = {"fast": round(float(f[-1]), 6), "slow": round(float(s[-1]), 6)}
        if np.isnan(f[-2]) or np.isnan(s[-2]):
            return Decision(None, "Недостаточно данных", vals)
        if f[-2] <= s[-2] and f[-1] > s[-1]:
            return Decision(1, "Быстрая MA пересекла медленную снизу вверх", vals)
        if f[-2] >= s[-2] and f[-1] < s[-1]:
            return Decision(_short(-1, p["allow_short"]), "Быстрая MA пересекла медленную сверху вниз", vals)
        return Decision(None, "Пересечения нет", vals)


class RsiReversion(Strategy):
    key = "rsi_reversion"
    title = "Возврат к среднему по RSI"
    description = "Вход в лонг при выходе RSI из зоны перепроданности, в шорт — из зоны перекупленности; выход у уровня 50."
    params = [
        Param("period", "Период RSI", "int", 14, 2, 200),
        Param("oversold", "Перепроданность", "float", 30, 1, 49),
        Param("overbought", "Перекупленность", "float", 70, 51, 99),
        Param("exit_long", "Выход из лонга (RSI ≥)", "float", 55, 1, 99),
        Param("exit_short", "Выход из шорта (RSI ≤)", "float", 45, 1, 99),
        Param("allow_short", "Разрешить шорт", "bool", True),
    ]

    def min_bars(self, p: dict) -> int:
        return p["period"] + 5

    def evaluate(self, bars, p, position, state) -> Decision:
        r = ind.rsi(bars["close"], p["period"])
        vals = {"rsi": round(float(r[-1]), 2)}
        if np.isnan(r[-2]):
            return Decision(None, "Недостаточно данных", vals)
        if r[-2] < p["oversold"] <= r[-1]:
            return Decision(1, f"RSI вышел из перепроданности ({r[-1]:.1f})", vals)
        if r[-2] > p["overbought"] >= r[-1]:
            return Decision(_short(-1, p["allow_short"]), f"RSI вышел из перекупленности ({r[-1]:.1f})", vals)
        if position > 0 and r[-1] >= p["exit_long"]:
            return Decision(0, f"RSI достиг уровня выхода из лонга ({r[-1]:.1f})", vals)
        if position < 0 and r[-1] <= p["exit_short"]:
            return Decision(0, f"RSI достиг уровня выхода из шорта ({r[-1]:.1f})", vals)
        return Decision(None, "Нет сигнала", vals)


class DonchianBreakout(Strategy):
    key = "donchian_breakout"
    title = "Пробой канала Дончиана"
    description = "Трендовая стратегия: вход при пробое максимума/минимума N баров, выход по каналу M баров."
    params = [
        Param("entry", "Канал входа (баров)", "int", 20, 3, 500),
        Param("exit", "Канал выхода (баров)", "int", 10, 2, 500),
        Param("allow_short", "Разрешить шорт", "bool", True),
    ]

    def min_bars(self, p: dict) -> int:
        return max(p["entry"], p["exit"]) + 3

    def evaluate(self, bars, p, position, state) -> Decision:
        h, l, c = bars["high"], bars["low"], bars["close"]
        up = float(np.max(h[-p["entry"] - 1:-1]))
        dn = float(np.min(l[-p["entry"] - 1:-1]))
        xup = float(np.max(h[-p["exit"] - 1:-1]))
        xdn = float(np.min(l[-p["exit"] - 1:-1]))
        vals = {"upper": up, "lower": dn, "exit_upper": xup, "exit_lower": xdn, "close": float(c[-1])}
        if c[-1] > up:
            return Decision(1, f"Пробой верхней границы {up}", vals)
        if c[-1] < dn:
            return Decision(_short(-1, p["allow_short"]), f"Пробой нижней границы {dn}", vals)
        if position > 0 and c[-1] < xdn:
            return Decision(0, f"Выход из лонга: цена ниже {xdn}", vals)
        if position < 0 and c[-1] > xup:
            return Decision(0, f"Выход из шорта: цена выше {xup}", vals)
        return Decision(None, "Цена внутри канала", vals)


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


class MlLogistic(Strategy):
    key = "ml_logistic"
    title = "AI: логистическая регрессия"
    description = ("Модель машинного обучения переобучается на каждом новом баре на истории MT5 "
                   "(доходности, RSI, отклонение от SMA в ATR) и прогнозирует вероятность роста следующего бара. "
                   "Торгует только если точность на отложенной выборке выше порога.")
    params = [
        Param("lags", "Лагов доходности", "int", 5, 1, 30),
        Param("train_bars", "Баров для обучения", "int", 500, 100, 5000),
        Param("threshold", "Порог вероятности", "float", 0.58, 0.5, 0.95, 0.01),
        Param("min_accuracy", "Мин. точность на валидации", "float", 0.52, 0.0, 1.0, 0.01),
        Param("l2", "L2-регуляризация", "float", 0.01, 0.0, 10.0, 0.001),
        Param("allow_short", "Разрешить шорт", "bool", True),
    ]

    def min_bars(self, p: dict) -> int:
        return p["train_bars"] + p["lags"] + 40

    @staticmethod
    def features(bars: dict[str, np.ndarray], lags: int) -> np.ndarray:
        c, h, l = bars["close"].astype(float), bars["high"].astype(float), bars["low"].astype(float)
        ret = np.concatenate([[0.0], np.diff(np.log(c))])
        vol = np.array([np.std(ret[max(0, i - 19): i + 1]) or 1e-9 for i in range(len(ret))])
        cols = [np.roll(ret, k) / vol for k in range(lags)]
        r = ind.rsi(c, 14)
        a = ind.atr(h, l, c, 14)
        m = ind.sma(c, 20)
        cols.append((r - 50.0) / 50.0)
        cols.append((c - m) / np.where(a > 0, a, np.nan))
        X = np.column_stack(cols)
        X[: max(lags, 20)] = np.nan
        return X

    @staticmethod
    def fit(X: np.ndarray, y: np.ndarray, l2: float, iters: int = 400, lr: float = 0.2) -> np.ndarray:
        Xb = np.column_stack([np.ones(len(X)), X])
        w = np.zeros(Xb.shape[1])
        for _ in range(iters):
            p = _sigmoid(Xb @ w)
            grad = Xb.T @ (p - y) / len(y)
            grad[1:] += l2 * w[1:]
            w -= lr * grad
        return w

    def evaluate(self, bars, p, position, state) -> Decision:
        X = self.features(bars, p["lags"])
        c = bars["close"]
        y = (np.roll(c, -1) > c).astype(float)
        X_now = X[-1]
        Xt, yt = X[:-1], y[:-1]
        mask = ~np.isnan(Xt).any(axis=1)
        Xt, yt = Xt[mask][-p["train_bars"]:], yt[mask][-p["train_bars"]:]
        if len(Xt) < 60 or np.isnan(X_now).any():
            return Decision(None, "Недостаточно данных для обучения", {})
        mu, sd = Xt.mean(axis=0), Xt.std(axis=0)
        sd[sd == 0] = 1.0
        Z, z_now = (Xt - mu) / sd, (X_now - mu) / sd
        split = int(len(Z) * 0.8)
        w_val = self.fit(Z[:split], yt[:split], p["l2"])
        pv = _sigmoid(np.column_stack([np.ones(len(Z) - split), Z[split:]]) @ w_val)
        val_acc = float(np.mean((pv > 0.5) == (yt[split:] > 0.5)))
        w = self.fit(Z, yt, p["l2"])
        prob = float(_sigmoid(np.concatenate([[1.0], z_now]) @ w))
        vals = {"prob_up": round(prob, 4), "val_accuracy": round(val_acc, 4), "samples": int(len(Z))}
        state["model"] = {"weights": [round(float(x), 5) for x in w], "val_accuracy": vals["val_accuracy"]}
        if val_acc < p["min_accuracy"]:
            return Decision(0 if position else None,
                            f"Точность модели {val_acc:.2%} ниже порога {p['min_accuracy']:.0%} — торговля приостановлена", vals)
        if prob >= p["threshold"]:
            return Decision(1, f"Вероятность роста {prob:.2%}", vals)
        if prob <= 1 - p["threshold"]:
            return Decision(_short(-1, p["allow_short"]), f"Вероятность падения {1 - prob:.2%}", vals)
        return Decision(None, f"Неуверенный прогноз ({prob:.2%})", vals)


STRATEGIES: dict[str, Strategy] = {s.key: s for s in (SmaCross(), RsiReversion(), DonchianBreakout(), MlLogistic())}


RISK_PARAMS = [
    Param("volume", "Объём (лот)", "float", 0.01, 0.0, 1000, 0.01),
    Param("sl_points", "Stop Loss (пунктов, 0 = нет)", "int", 0, 0, 1_000_000),
    Param("tp_points", "Take Profit (пунктов, 0 = нет)", "int", 0, 0, 1_000_000),
    Param("max_positions", "Макс. открытых позиций", "int", 1, 1, 50),
    Param("max_spread_points", "Макс. спред (пунктов, 0 = без ограничения)", "int", 0, 0, 100000),
    Param("max_daily_loss", "Макс. дневной убыток (валюта счёта, 0 = нет)", "float", 0, 0, 1e9),
    Param("deviation_points", "Допустимое проскальзывание (пунктов)", "int", 20, 0, 10000),
    Param("hours_from", "Торговать с (час UTC)", "int", 0, 0, 23),
    Param("hours_to", "Торговать до (час UTC, не включая)", "int", 24, 1, 24),
    Param("close_on_stop", "Закрывать позиции при остановке", "bool", False),
]


class _Risk(Strategy):
    params = RISK_PARAMS

    def check(self, p: dict) -> None:
        if p["volume"] <= 0:
            raise ValueError("Объём должен быть больше 0")


RISK = _Risk()
