"""Synchronous wrapper around the official ``MetaTrader5`` Python package.

This class talks to a real MetaTrader 5 terminal through the official package and converts every
result into JSON-serialisable dictionaries. It is executed either:

* inside a dedicated worker process started by the backend (connection type ``local``), or
* inside the MT5 bridge agent (``python -m app.mt5.bridge_server``) running next to the terminal
  (connection type ``bridge``).

The official package is distributed only as Windows (win_amd64) wheels and requires an installed
MetaTrader 5 terminal, see https://pypi.org/project/MetaTrader5/ .
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import Any

from . import constants as C


class MT5Error(Exception):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class MT5Unavailable(MT5Error):
    """The MetaTrader5 package / terminal is not available on this machine."""


def load_mt5_module():
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError as exc:
        raise MT5Unavailable(
            "Python-пакет MetaTrader5 не установлен в этом окружении "
            f"(платформа: {sys.platform}). Официальный пакет MetaQuotes выпускается только для Windows x64 "
            "и работает только рядом с установленным терминалом MetaTrader 5. Установите его на Windows "
            "(pip install MetaTrader5) или используйте тип подключения «bridge» с агентом app.mt5.bridge_server."
        ) from exc
    return mt5


def _plain(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "_asdict"):
        return {k: _plain(v) for k, v in value._asdict().items()}
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, datetime):
        return int(value.timestamp())
    if hasattr(value, "item"):  # numpy scalar
        return value.item()
    return str(value)


def _with_names(d: dict | None, kind: str) -> dict | None:
    if d is None:
        return None
    if kind == "position":
        d["side"] = "buy" if d.get("type") == C.POSITION_TYPE_BUY else "sell"
    elif kind == "order":
        d["order_type"] = C.ORDER_TYPE_NAMES.get(d.get("type"), str(d.get("type")))
    elif kind == "deal":
        d["deal_type"] = C.DEAL_TYPES.get(d.get("type"), str(d.get("type")))
        d["deal_entry"] = C.DEAL_ENTRIES.get(d.get("entry"), str(d.get("entry")))
    elif kind == "account":
        d["trade_mode_name"] = C.ACCOUNT_TRADE_MODES.get(d.get("trade_mode"), "unknown")
    return d


class MT5Client:
    METHODS = frozenset({
        "connect", "disconnect", "status", "account_info", "terminal_info", "symbols", "symbol_info",
        "ticks", "rates", "positions", "orders", "history_deals", "history_orders", "check_market_order",
        "market_order", "pending_order", "close_position", "modify_position", "modify_order", "cancel_order",
    })

    def __init__(self, mt5_module: Any | None = None):
        self.mt5 = mt5_module if mt5_module is not None else load_mt5_module()
        self.connected = False
        self._selected: set[str] = set()
        self._symbol_cache: dict[str, Any] = {}

    # ------------------------------------------------------------------ helpers
    def _raise_last(self, what: str) -> None:
        try:
            code, msg = self.mt5.last_error()
        except Exception:  # pragma: no cover
            code, msg = None, "unknown error"
        raise MT5Error(f"{what}: {msg} (код {code})", code)

    def _require(self) -> None:
        if not self.connected:
            raise MT5Error("Нет подключения к терминалу MetaTrader 5")

    def _symbol(self, symbol: str, refresh: bool = True):
        if not refresh and symbol in self._symbol_cache:
            return self._symbol_cache[symbol]
        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise MT5Error(f"Символ «{symbol}» не найден у брокера")
        if not info.visible or symbol not in self._selected:
            if not self.mt5.symbol_select(symbol, True):
                self._raise_last(f"symbol_select({symbol})")
            self._selected.add(symbol)
            info = self.mt5.symbol_info(symbol) or info
        self._symbol_cache[symbol] = info
        return info

    @staticmethod
    def _ts(value: int | float | None, default: datetime) -> datetime:
        if value is None:
            return default
        return datetime.fromtimestamp(float(value), tz=timezone.utc)

    # ------------------------------------------------------------------ connection
    def connect(self, login: int | None = None, password: str | None = None, server: str | None = None,
                path: str | None = None, timeout_ms: int = 60000, portable: bool = False) -> dict:
        kwargs: dict[str, Any] = {"timeout": int(timeout_ms), "portable": bool(portable)}
        if login and password:
            kwargs.update(login=int(login), password=password, server=server or "")
        ok = self.mt5.initialize(path, **kwargs) if path else self.mt5.initialize(**kwargs)
        if not ok:
            self._raise_last("Не удалось инициализировать терминал MetaTrader 5")
        acc = self.mt5.account_info()
        if acc is None:
            self.mt5.shutdown()
            self._raise_last("Терминал запущен, но торговый счёт не авторизован")
        if login and int(acc.login) != int(login):
            if not password:
                self.mt5.shutdown()
                raise MT5Error(f"Терминал авторизован под счётом {acc.login}, а ожидался {login}. Укажите пароль.")
            if not self.mt5.login(int(login), password=password, server=server or "", timeout=int(timeout_ms)):
                code, msg = self.mt5.last_error()
                self.mt5.shutdown()
                raise MT5Error(f"Ошибка авторизации счёта {login}: {msg} (код {code})", code)
        self.connected = True
        self._selected.clear()
        self._symbol_cache.clear()
        return self.status()

    def disconnect(self) -> dict:
        if self.connected:
            self.mt5.shutdown()
        self.connected = False
        return {"connected": False}

    def status(self) -> dict:
        self._require()
        term = _plain(self.mt5.terminal_info())
        acc = _with_names(_plain(self.mt5.account_info()), "account")
        if term is None or acc is None:
            self._raise_last("Терминал недоступен")
        return {"connected": bool(term.get("connected")), "terminal": term, "account": acc}

    def account_info(self) -> dict:
        self._require()
        acc = self.mt5.account_info()
        if acc is None:
            self._raise_last("account_info")
        return _with_names(_plain(acc), "account")

    def terminal_info(self) -> dict:
        self._require()
        t = self.mt5.terminal_info()
        if t is None:
            self._raise_last("terminal_info")
        return _plain(t)

    # ------------------------------------------------------------------ market data
    def symbols(self, group: str | None = None) -> list[dict]:
        self._require()
        res = self.mt5.symbols_get(group=group) if group else self.mt5.symbols_get()
        if res is None:
            self._raise_last("symbols_get")
        keys = ("name", "description", "path", "digits", "visible", "currency_base", "currency_profit",
                "trade_mode", "volume_min", "volume_max", "volume_step", "point")
        return [{k: _plain(getattr(s, k, None)) for k in keys} for s in res]

    def symbol_info(self, symbol: str) -> dict:
        self._require()
        return _plain(self._symbol(symbol))

    def ticks(self, symbols: list[str]) -> dict[str, dict | None]:
        self._require()
        out: dict[str, dict | None] = {}
        for sym in symbols:
            try:
                info = self._symbol(sym, refresh=False)
            except MT5Error:
                out[sym] = None
                continue
            t = self.mt5.symbol_info_tick(sym)
            if t is None:
                out[sym] = None
                continue
            d = _plain(t)
            point = float(getattr(info, "point", 0) or 0)
            d["digits"] = int(getattr(info, "digits", 5))
            d["spread_points"] = round((d["ask"] - d["bid"]) / point) if point else None
            out[sym] = d
        return out

    def rates(self, symbol: str, timeframe: str = "M15", count: int = 300) -> list[dict]:
        self._require()
        tf = C.TIMEFRAMES.get(timeframe)
        if tf is None:
            raise MT5Error(f"Неизвестный таймфрейм {timeframe}")
        self._symbol(symbol, refresh=False)
        count = max(1, min(int(count), 50000))
        arr = self.mt5.copy_rates_from_pos(symbol, tf, 0, count)
        if arr is None:
            self._raise_last(f"copy_rates_from_pos({symbol},{timeframe})")
        names = arr.dtype.names if hasattr(arr, "dtype") else None
        out = []
        for row in arr:
            if names:
                out.append({n: _plain(row[n]) for n in names})
            else:
                out.append(_plain(row))
        return out

    # ------------------------------------------------------------------ trading state
    def positions(self, symbol: str | None = None, magic: int | None = None) -> list[dict]:
        self._require()
        res = self.mt5.positions_get(symbol=symbol) if symbol else self.mt5.positions_get()
        if res is None:
            self._raise_last("positions_get")
        items = [_with_names(_plain(p), "position") for p in res]
        if magic is not None:
            items = [p for p in items if p["magic"] == int(magic)]
        return items

    def orders(self, symbol: str | None = None, magic: int | None = None) -> list[dict]:
        self._require()
        res = self.mt5.orders_get(symbol=symbol) if symbol else self.mt5.orders_get()
        if res is None:
            self._raise_last("orders_get")
        items = [_with_names(_plain(o), "order") for o in res]
        if magic is not None:
            items = [o for o in items if o["magic"] == int(magic)]
        return items

    def history_deals(self, date_from: float | None = None, date_to: float | None = None,
                      magic: int | None = None, symbol: str | None = None) -> list[dict]:
        self._require()
        now = datetime.now(timezone.utc)
        dfrom = self._ts(date_from, datetime(2000, 1, 1, tzinfo=timezone.utc))
        dto = self._ts(date_to, now)
        res = self.mt5.history_deals_get(dfrom, dto)
        if res is None:
            self._raise_last("history_deals_get")
        items = [_with_names(_plain(d), "deal") for d in res]
        if magic is not None:
            items = [d for d in items if d["magic"] == int(magic)]
        if symbol:
            items = [d for d in items if d["symbol"] == symbol]
        return items

    def history_orders(self, date_from: float | None = None, date_to: float | None = None,
                       magic: int | None = None) -> list[dict]:
        self._require()
        now = datetime.now(timezone.utc)
        res = self.mt5.history_orders_get(self._ts(date_from, datetime(2000, 1, 1, tzinfo=timezone.utc)),
                                          self._ts(date_to, now))
        if res is None:
            self._raise_last("history_orders_get")
        items = [_with_names(_plain(o), "order") for o in res]
        if magic is not None:
            items = [o for o in items if o["magic"] == int(magic)]
        return items

    # ------------------------------------------------------------------ trading
    @staticmethod
    def _filling_candidates(info) -> list[int]:
        fm = int(getattr(info, "filling_mode", 0) or 0)
        first = C.ORDER_FILLING_FOK if fm & C.SYMBOL_FILLING_FOK else (
            C.ORDER_FILLING_IOC if fm & C.SYMBOL_FILLING_IOC else C.ORDER_FILLING_RETURN)
        return [first] + [m for m in (C.ORDER_FILLING_FOK, C.ORDER_FILLING_IOC, C.ORDER_FILLING_RETURN) if m != first]

    @staticmethod
    def _norm_volume(info, volume: float) -> float:
        step = float(info.volume_step or 0.01)
        vol = round(round(float(volume) / step) * step, 8)
        if vol < float(info.volume_min) - 1e-12:
            raise MT5Error(f"Объём {volume} меньше минимального {info.volume_min} для {info.name}")
        if vol > float(info.volume_max) + 1e-12:
            raise MT5Error(f"Объём {volume} больше максимального {info.volume_max} для {info.name}")
        return vol

    @staticmethod
    def _norm_price(info, price: float | None) -> float:
        if not price:
            return 0.0
        return round(float(price), int(info.digits))

    def _result(self, res, request: dict) -> dict:
        if res is None:
            code, msg = self.mt5.last_error()
            return {"ok": False, "retcode": None, "retcode_text": f"order_send вернул None: {msg} (код {code})",
                    "request": request}
        d = _plain(res)
        d["ok"] = d.get("retcode") in C.SUCCESS_RETCODES
        d["retcode_text"] = C.retcode_text(d.get("retcode"))
        d["request"] = request
        return d

    def _send(self, request: dict, info) -> dict:
        result: dict = {}
        for filling in self._filling_candidates(info):
            request["type_filling"] = filling
            result = self._result(self.mt5.order_send(dict(request)), dict(request))
            if result.get("retcode") != 10030:  # unsupported filling -> try next
                return result
        return result

    def _market_request(self, symbol: str, side: str, volume: float, sl: float | None, tp: float | None,
                        deviation: int, magic: int, comment: str, sl_points: int | None = None,
                        tp_points: int | None = None) -> tuple[dict, Any]:
        if side not in ("buy", "sell"):
            raise MT5Error("side должен быть buy или sell")
        info = self._symbol(symbol)
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None:
            self._raise_last(f"Нет котировок по {symbol}")
        price = tick.ask if side == "buy" else tick.bid
        sgn = 1 if side == "buy" else -1
        if sl_points and not sl:
            sl = price - sgn * float(sl_points) * float(info.point)
        if tp_points and not tp:
            tp = price + sgn * float(tp_points) * float(info.point)
        req = {
            "action": C.TRADE_ACTION_DEAL, "symbol": symbol, "volume": self._norm_volume(info, volume),
            "type": C.ORDER_TYPES[side], "price": self._norm_price(info, price), "deviation": int(deviation),
            "magic": int(magic), "comment": (comment or "")[:31], "type_time": C.ORDER_TIME_GTC,
            "type_filling": self._filling_candidates(info)[0],
        }
        if sl:
            req["sl"] = self._norm_price(info, sl)
        if tp:
            req["tp"] = self._norm_price(info, tp)
        return req, info

    def check_market_order(self, symbol: str, side: str, volume: float, sl: float | None = None,
                           tp: float | None = None, deviation: int = 20, magic: int = 0, comment: str = "") -> dict:
        self._require()
        req, _ = self._market_request(symbol, side, volume, sl, tp, deviation, magic, comment)
        res = self.mt5.order_check(req)
        if res is None:
            self._raise_last("order_check")
        d = _plain(res)
        d["retcode_text"] = C.retcode_text(d.get("retcode"))
        d["ok"] = d.get("retcode") in (0, C.TRADE_RETCODE_DONE)
        d["request"] = req
        return d

    def market_order(self, symbol: str, side: str, volume: float, sl: float | None = None, tp: float | None = None,
                     deviation: int = 20, magic: int = 0, comment: str = "", sl_points: int | None = None,
                     tp_points: int | None = None) -> dict:
        """Market order. ``sl_points``/``tp_points`` are converted to prices from the execution quote."""
        self._require()
        req, info = self._market_request(symbol, side, volume, sl, tp, deviation, magic, comment, sl_points, tp_points)
        return self._send(req, info)

    def pending_order(self, symbol: str, order_type: str, volume: float, price: float, sl: float | None = None,
                      tp: float | None = None, stoplimit: float | None = None, magic: int = 0, comment: str = "",
                      expiration: float | None = None) -> dict:
        self._require()
        if order_type not in ("buy_limit", "sell_limit", "buy_stop", "sell_stop", "buy_stop_limit", "sell_stop_limit"):
            raise MT5Error(f"Неверный тип отложенного ордера: {order_type}")
        info = self._symbol(symbol)
        req: dict[str, Any] = {
            "action": C.TRADE_ACTION_PENDING, "symbol": symbol, "volume": self._norm_volume(info, volume),
            "type": C.ORDER_TYPES[order_type], "price": self._norm_price(info, price), "magic": int(magic),
            "comment": (comment or "")[:31], "type_time": C.ORDER_TIME_GTC, "type_filling": C.ORDER_FILLING_RETURN,
        }
        if sl:
            req["sl"] = self._norm_price(info, sl)
        if tp:
            req["tp"] = self._norm_price(info, tp)
        if stoplimit:
            req["stoplimit"] = self._norm_price(info, stoplimit)
        if expiration:
            req["type_time"] = C.ORDER_TIME_SPECIFIED
            req["expiration"] = int(expiration)
        res = self._result(self.mt5.order_send(dict(req)), req)
        if res.get("retcode") == 10030:
            return self._send(req, info)
        return res

    def close_position(self, ticket: int, volume: float | None = None, deviation: int = 20, comment: str = "") -> dict:
        self._require()
        res = self.mt5.positions_get(ticket=int(ticket))
        if not res:
            raise MT5Error(f"Позиция #{ticket} не найдена")
        pos = res[0]
        info = self._symbol(pos.symbol)
        tick = self.mt5.symbol_info_tick(pos.symbol)
        if tick is None:
            self._raise_last(f"Нет котировок по {pos.symbol}")
        is_buy = pos.type == C.POSITION_TYPE_BUY
        req = {
            "action": C.TRADE_ACTION_DEAL, "symbol": pos.symbol, "position": int(pos.ticket),
            "volume": self._norm_volume(info, volume if volume else pos.volume),
            "type": C.ORDER_TYPES["sell" if is_buy else "buy"],
            "price": self._norm_price(info, tick.bid if is_buy else tick.ask), "deviation": int(deviation),
            "magic": int(pos.magic), "comment": (comment or "close")[:31], "type_time": C.ORDER_TIME_GTC,
            "type_filling": self._filling_candidates(info)[0],
        }
        return self._send(req, info)

    def modify_position(self, ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
        self._require()
        res = self.mt5.positions_get(ticket=int(ticket))
        if not res:
            raise MT5Error(f"Позиция #{ticket} не найдена")
        pos = res[0]
        info = self._symbol(pos.symbol)
        req = {"action": C.TRADE_ACTION_SLTP, "symbol": pos.symbol, "position": int(pos.ticket),
               "sl": self._norm_price(info, sl), "tp": self._norm_price(info, tp), "magic": int(pos.magic)}
        return self._result(self.mt5.order_send(dict(req)), req)

    def modify_order(self, ticket: int, price: float, sl: float | None = None, tp: float | None = None) -> dict:
        self._require()
        res = self.mt5.orders_get(ticket=int(ticket))
        if not res:
            raise MT5Error(f"Ордер #{ticket} не найден")
        o = res[0]
        info = self._symbol(o.symbol)
        req = {"action": C.TRADE_ACTION_MODIFY, "order": int(o.ticket), "symbol": o.symbol,
               "price": self._norm_price(info, price), "sl": self._norm_price(info, sl),
               "tp": self._norm_price(info, tp), "type_time": int(o.type_time),
               "expiration": int(o.time_expiration or 0)}
        return self._result(self.mt5.order_send(dict(req)), req)

    def cancel_order(self, ticket: int) -> dict:
        self._require()
        req = {"action": C.TRADE_ACTION_REMOVE, "order": int(ticket)}
        return self._result(self.mt5.order_send(dict(req)), req)


def dispatch(client: MT5Client, method: str, params: dict | None) -> Any:
    if method not in MT5Client.METHODS:
        raise MT5Error(f"Метод {method} не разрешён")
    return getattr(client, method)(**(params or {}))
