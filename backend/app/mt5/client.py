"""Synchronous wrapper around the official ``MetaTrader5`` Python package (``import MetaTrader5 as mt5``).

The class talks to a real MetaTrader 5 terminal through the official package and converts every result
into JSON-serialisable dictionaries. It adds what the raw API does not do by itself:

* readable errors (``last_error`` codes + hints what to fix in the terminal);
* pre-trade checks (algo-trading button, investor password, broker EA permission, symbol trade mode);
* volume normalisation (min/max/step/limit) and price normalisation to the symbol tick size;
* client-side validation of SL/TP against ``trade_stops_level`` (instead of a cryptic 10016);
* automatic choice of the filling mode with fallback on retcode 10030;
* re-sending market requests with a fresh quote after requote / price-changed / no-prices;
* trade-server time offset estimation (MT5 timestamps are in trade-server time).

It runs either inside a dedicated worker process started by the backend (connection type ``local`` — the
recommended way: backend and terminal on the same Windows machine) or inside the optional MT5 bridge agent.
The official package exists only for Windows x64: https://pypi.org/project/MetaTrader5/
"""
from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable

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
            "и работает только рядом с установленным терминалом MetaTrader 5. Запустите сервер на Windows "
            "и выполните: pip install -r requirements.txt (пакет MetaTrader5 установится автоматически)."
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
        d["margin_mode_name"] = C.ACCOUNT_MARGIN_MODES.get(d.get("margin_mode"), "unknown")
    elif kind == "symbol":
        d["trade_mode_name"] = C.SYMBOL_TRADE_MODES.get(d.get("trade_mode"), "unknown")
        d["trade_exemode_name"] = C.SYMBOL_TRADE_EXECUTIONS.get(d.get("trade_exemode"), "unknown")
    return d


class MT5Client:
    METHODS = frozenset({
        "connect", "disconnect", "status", "version", "account_info", "terminal_info", "diagnostics", "symbols",
        "symbol_info", "ticks", "rates", "market_book", "positions", "orders", "history_deals", "history_orders",
        "calc", "check_market_order", "market_order", "pending_order", "close_position", "modify_position",
        "modify_order", "cancel_order",
    })
    MARKET_RETRIES = 3

    def __init__(self, mt5_module: Any | None = None, sleep: Callable[[float], None] = time.sleep):
        self.mt5 = mt5_module if mt5_module is not None else load_mt5_module()
        self.sleep = sleep
        self.connected = False
        self._selected: set[str] = set()
        self._symbol_cache: dict[str, Any] = {}
        self._books: set[str] = set()
        self._offset: int | None = None

    # ------------------------------------------------------------------ helpers
    def _last_error(self) -> tuple[int | None, str]:
        try:
            code, msg = self.mt5.last_error()
        except Exception:  # pragma: no cover
            return None, "unknown error"
        return code, msg

    def _raise_last(self, what: str, hint: str | None = None) -> None:
        code, msg = self._last_error()
        known = C.MT5_ERRORS.get(code) if code is not None else None
        text = f"{what}: {msg} (код {code}{', ' + known if known and known.lower() not in str(msg).lower() else ''})"
        if hint:
            text += f". {hint}"
        raise MT5Error(text, code)

    def _require(self) -> None:
        if not self.connected:
            raise MT5Error("Нет подключения к терминалу MetaTrader 5")

    def _symbol(self, symbol: str, refresh: bool = True):
        if not refresh and symbol in self._symbol_cache:
            return self._symbol_cache[symbol]
        info = self.mt5.symbol_info(symbol)
        if info is None:
            raise MT5Error(f"Символ «{symbol}» не найден у брокера (проверьте точное имя, например с суффиксом: EURUSD.m)")
        if not info.visible or symbol not in self._selected:
            if not self.mt5.symbol_select(symbol, True):
                self._raise_last(f"Не удалось добавить {symbol} в «Обзор рынка»")
            self._selected.add(symbol)
            info = self.mt5.symbol_info(symbol) or info
        self._symbol_cache[symbol] = info
        return info

    def _tick(self, symbol: str):
        tick = self.mt5.symbol_info_tick(symbol)
        if tick is None or (not tick.bid and not tick.ask):
            self._raise_last(f"Нет котировок по {symbol}", "Возможно, рынок закрыт или нет связи с сервером")
        return tick

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
        ok = False
        for attempt in range(2):
            ok = self.mt5.initialize(path, **kwargs) if path else self.mt5.initialize(**kwargs)
            if ok:
                break
            code, _ = self._last_error()
            if code not in (-10004, -10005) or attempt:  # retry only IPC timeouts (terminal still starting)
                break
            self.sleep(3)
        if not ok:
            code, _ = self._last_error()
            hint = {
                -10003: "Проверьте, что MetaTrader 5 установлен, и укажите путь к terminal64.exe в настройках счёта",
                -10005: "Терминал не ответил вовремя — запустите MetaTrader 5 вручную и повторите",
                -6: "Проверьте номер счёта, пароль и точное имя торгового сервера (как в окне входа MT5)",
                -2: "Неверные параметры подключения",
            }.get(code)
            self._raise_last("Не удалось подключиться к терминалу MetaTrader 5", hint)
        acc = self.mt5.account_info()
        if acc is None:
            self.mt5.shutdown()
            self._raise_last("Терминал запущен, но торговый счёт не авторизован",
                             "Войдите в счёт в терминале или укажите пароль в настройках счёта")
        if login and int(acc.login) != int(login):
            if not password:
                self.mt5.shutdown()
                raise MT5Error(f"Терминал авторизован под счётом {acc.login}, а ожидался {login}. Укажите пароль "
                               "счёта или войдите в нужный счёт в терминале.")
            if not self.mt5.login(int(login), password=password, server=server or "", timeout=int(timeout_ms)):
                code, msg = self._last_error()
                self.mt5.shutdown()
                raise MT5Error(f"Ошибка авторизации счёта {login}: {msg} (код {code})", code)
        self.connected = True
        self._selected.clear()
        self._symbol_cache.clear()
        self._books.clear()
        self._offset = None
        return self.status()

    def disconnect(self) -> dict:
        if self.connected:
            for sym in list(self._books):
                try:
                    self.mt5.market_book_release(sym)
                except Exception:  # noqa: BLE001
                    pass
            self.mt5.shutdown()
        self.connected = False
        self._books.clear()
        return {"connected": False}

    def version(self) -> dict | None:
        v = self.mt5.version()
        if not v:
            return None
        return {"version": v[0], "build": v[1], "date": v[2]}

    def server_offset(self) -> int | None:
        """Offset of the trade-server clock from UTC in seconds (estimated from fresh ticks).

        MT5 returns all times (ticks, bars, deals) as trade-server time encoded as a Unix timestamp.
        """
        best = None
        for sym in list(self._selected)[:30]:
            t = self.mt5.symbol_info_tick(sym)
            if t is not None and t.time and (best is None or t.time > best):
                best = t.time
        if best is not None:
            diff = best - time.time()
            rounded = round(diff / 3600) * 3600
            if abs(diff - rounded) <= 600 and abs(rounded) <= 14 * 3600:
                self._offset = int(rounded)
        return self._offset

    def status(self) -> dict:
        self._require()
        term = _plain(self.mt5.terminal_info())
        acc = _with_names(_plain(self.mt5.account_info()), "account")
        if term is None or acc is None:
            self._raise_last("Терминал недоступен", "Проверьте, что MetaTrader 5 запущен")
        return {"connected": bool(term.get("connected")), "terminal": term, "account": acc,
                "version": self.version(), "server_offset_s": self.server_offset()}

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

    def diagnostics(self) -> dict:
        """Checklist of everything that must be in place for trading through the Python API."""
        self._require()
        term, acc = self.mt5.terminal_info(), self.mt5.account_info()
        if term is None or acc is None:
            self._raise_last("Терминал недоступен")
        checks: list[dict] = []

        def add(key: str, ok: bool, title: str, detail: str, level: str = "error") -> None:
            checks.append({"key": key, "ok": bool(ok), "level": "ok" if ok else level, "title": title, "detail": detail})

        add("connected", term.connected, "Связь терминала с торговым сервером",
            "Есть" if term.connected else "Нет связи — проверьте интернет и имя сервера в терминале")
        add("algo_button", term.trade_allowed, "Кнопка «Алго-трейдинг» в терминале",
            "Включена" if term.trade_allowed else "Выключена — нажмите «Алго-трейдинг» (Algo Trading) на панели MT5")
        api_off = bool(getattr(term, "tradeapi_disabled", False))
        add("python_api", not api_off, "Торговля через Python API",
            "Разрешена" if not api_off else
            "Запрещена: Сервис → Настройки → Советники → снимите «Запретить торговлю через внешний Python API»")
        add("account_trade", acc.trade_allowed, "Торговля на счёте разрешена",
            "Да" if acc.trade_allowed else "Нет — вход выполнен по инвесторскому паролю или счёт заблокирован")
        add("account_expert", acc.trade_expert, "Брокер разрешает автоторговлю",
            "Да" if acc.trade_expert else "Нет — брокер запретил советников на этом счёте")
        mode = C.ACCOUNT_TRADE_MODES.get(acc.trade_mode, "unknown")
        add("account_type", mode != "real", "Тип счёта", mode.upper() + (
            "" if mode != "real" else " — торговля разрешается только при ATO_ALLOW_REAL_TRADING=true"), "warning")
        mm = C.ACCOUNT_MARGIN_MODES.get(getattr(acc, "margin_mode", 2), "unknown")
        add("margin_mode", mm == "hedging", "Учёт позиций", mm + (
            "" if mm == "hedging" else " — на неттинговом счёте по одному символу существует одна позиция: "
                                       "не запускайте несколько ботов на одном символе"), "warning")
        ping = float(getattr(term, "ping_last", 0) or 0) / 1000.0
        add("ping", 0 < ping < 500, "Пинг до сервера", f"{ping:.1f} мс" if ping else "нет данных", "warning")
        syms = self.mt5.symbols_total() if hasattr(self.mt5, "symbols_total") else None
        add("symbols", bool(syms), "Доступно символов", str(syms) if syms is not None else "нет данных", "warning")
        off = self.server_offset()
        add("server_time", off is not None, "Время торгового сервера",
            f"UTC{'+' if (off or 0) >= 0 else '-'}{abs(off or 0) // 3600}" if off is not None
            else "не определено (нет свежих котировок — рынок закрыт?)", "warning")
        ready = not any(c["level"] == "error" for c in checks)
        return {"ready": ready, "checks": checks,
                "version": self.version(), "terminal": _plain(term),
                "account": _with_names(_plain(acc), "account")}

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
        return _with_names(_plain(self._symbol(symbol)), "symbol")

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
            d["spread_points"] = round((d["ask"] - d["bid"]) / point) if point and d["ask"] and d["bid"] else None
            out[sym] = d
        return out

    def rates(self, symbol: str, timeframe: str = "M15", count: int = 300) -> list[dict]:
        self._require()
        tf = C.TIMEFRAMES.get(timeframe)
        if tf is None:
            raise MT5Error(f"Неизвестный таймфрейм {timeframe}")
        self._symbol(symbol, refresh=False)
        count = max(1, min(int(count), 50000))
        arr = None
        for attempt in range(3):  # the terminal may still be downloading history for a freshly selected symbol
            arr = self.mt5.copy_rates_from_pos(symbol, tf, 0, count)
            if arr is not None and len(arr):
                break
            self.sleep(0.5 * (attempt + 1))
        if arr is None:
            self._raise_last(f"Не удалось получить историю {symbol} {timeframe}",
                             "Терминал ещё загружает историю — повторите через несколько секунд")
        names = arr.dtype.names if hasattr(arr, "dtype") else None
        out = []
        for row in arr:
            out.append({n: _plain(row[n]) for n in names} if names else _plain(row))
        return out

    def market_book(self, symbol: str, depth: int = 20) -> dict:
        """Depth of market (DOM). Many forex brokers do not broadcast it — then ``available`` is False."""
        self._require()
        self._symbol(symbol, refresh=False)
        if symbol not in self._books:
            if not self.mt5.market_book_add(symbol):
                code, msg = self._last_error()
                return {"symbol": symbol, "available": False, "items": [],
                        "reason": f"Брокер не транслирует стакан по {symbol} ({msg})"}
            self._books.add(symbol)
        book = self.mt5.market_book_get(symbol)
        if not book:
            return {"symbol": symbol, "available": False, "items": [], "reason": "Стакан пуст или не транслируется"}
        items = [{"type": C.BOOK_TYPES.get(i.type, str(i.type)), "price": i.price,
                  "volume": getattr(i, "volume_dbl", None) or i.volume} for i in book]
        sells = sorted([i for i in items if i["type"].startswith("sell")], key=lambda x: x["price"])[:depth]
        buys = sorted([i for i in items if i["type"].startswith("buy")], key=lambda x: -x["price"])[:depth]
        return {"symbol": symbol, "available": True, "items": sorted(sells, key=lambda x: -x["price"]) + buys}

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
        """Deals in [date_from, date_to]; both are trade-server-time timestamps (like ``deal.time``)."""
        self._require()
        now = datetime.now(timezone.utc)
        res = self.mt5.history_deals_get(self._ts(date_from, datetime(2000, 1, 1, tzinfo=timezone.utc)),
                                         self._ts(date_to, now))
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

    # ------------------------------------------------------------------ trading helpers
    @staticmethod
    def _filling_candidates(info) -> list[int]:
        fm = int(getattr(info, "filling_mode", 0) or 0)
        first = C.ORDER_FILLING_FOK if fm & C.SYMBOL_FILLING_FOK else (
            C.ORDER_FILLING_IOC if fm & C.SYMBOL_FILLING_IOC else C.ORDER_FILLING_RETURN)
        return [first] + [m for m in (C.ORDER_FILLING_FOK, C.ORDER_FILLING_IOC, C.ORDER_FILLING_RETURN) if m != first]

    @staticmethod
    def _norm_volume(info, volume: float) -> float:
        step = float(getattr(info, "volume_step", 0) or 0.01)
        vol = round(round(float(volume) / step) * step, 8)
        if vol < float(info.volume_min) - 1e-12:
            raise MT5Error(f"Объём {volume} меньше минимального {info.volume_min} для {info.name}")
        if vol > float(info.volume_max) + 1e-12:
            raise MT5Error(f"Объём {volume} больше максимального {info.volume_max} для {info.name}")
        limit = float(getattr(info, "volume_limit", 0) or 0)
        if limit and vol > limit + 1e-12:
            raise MT5Error(f"Объём {volume} превышает лимит {limit} для {info.name}")
        return vol

    @staticmethod
    def _norm_price(info, price: float | None) -> float:
        if not price:
            return 0.0
        tick = float(getattr(info, "trade_tick_size", 0) or 0) or float(getattr(info, "point", 0) or 0)
        p = float(price)
        if tick > 0:
            p = round(p / tick) * tick
        return round(p, int(info.digits))

    def _pre_trade(self, info, side: str | None, closing: bool = False) -> None:
        term = self.mt5.terminal_info()
        if term is None:
            self._raise_last("Терминал недоступен")
        if not term.trade_allowed:
            raise MT5Error("Алготорговля выключена в терминале: нажмите кнопку «Алго-трейдинг» (Algo Trading) "
                           "на панели инструментов MetaTrader 5", 10027)
        if getattr(term, "tradeapi_disabled", False):
            raise MT5Error("В терминале запрещена торговля через Python API: Сервис → Настройки → Советники → "
                           "снимите «Запретить торговлю через внешний Python API»", 10027)
        if not term.connected:
            raise MT5Error("Терминал не подключён к торговому серверу", 10031)
        acc = self.mt5.account_info()
        if acc is None:
            self._raise_last("account_info")
        if not acc.trade_allowed:
            raise MT5Error("Торговля на счёте запрещена (вход по инвесторскому паролю или счёт заблокирован)", 10017)
        if not acc.trade_expert:
            raise MT5Error("Брокер запретил автоматическую торговлю на этом счёте", 10026)
        if info is None:
            return
        tm = int(getattr(info, "trade_mode", 4))
        name = info.name
        if tm == 0:
            raise MT5Error(f"Торговля по {name} запрещена брокером", 10017)
        if not closing:
            if tm == 3:
                raise MT5Error(f"По {name} разрешено только закрытие позиций", 10044)
            if tm == 1 and side == "sell":
                raise MT5Error(f"По {name} разрешены только покупки", 10042)
            if tm == 2 and side == "buy":
                raise MT5Error(f"По {name} разрешены только продажи", 10043)

    def _check_stops(self, info, tick, side: str, sl: float | None, tp: float | None) -> None:
        """Validate SL/TP for a position of ``side`` like the trade server does (Bid for buy, Ask for sell)."""
        point = float(info.point)
        level = max(int(getattr(info, "trade_stops_level", 0) or 0), 0) * point
        ref = tick.bid if side == "buy" else tick.ask
        digits = int(info.digits)
        if side == "buy":
            if sl and sl >= ref - level:
                raise MT5Error(f"Stop Loss {sl} для покупки должен быть ниже {round(ref - level, digits)} "
                               f"(Bid {ref}, минимальная дистанция {int(level / point)} пунктов)", 10016)
            if tp and tp <= ref + level:
                raise MT5Error(f"Take Profit {tp} для покупки должен быть выше {round(ref + level, digits)} "
                               f"(Bid {ref}, минимальная дистанция {int(level / point)} пунктов)", 10016)
        else:
            if sl and sl <= ref + level:
                raise MT5Error(f"Stop Loss {sl} для продажи должен быть выше {round(ref + level, digits)} "
                               f"(Ask {ref}, минимальная дистанция {int(level / point)} пунктов)", 10016)
            if tp and tp >= ref - level:
                raise MT5Error(f"Take Profit {tp} для продажи должен быть ниже {round(ref - level, digits)} "
                               f"(Ask {ref}, минимальная дистанция {int(level / point)} пунктов)", 10016)

    def _result(self, res, request: dict) -> dict:
        if res is None:
            code, msg = self._last_error()
            return {"ok": False, "retcode": None, "retcode_text": f"order_send вернул None: {msg} (код {code})",
                    "request": request}
        d = _plain(res)
        d["ok"] = d.get("retcode") in C.SUCCESS_RETCODES
        d["retcode_text"] = C.retcode_text(d.get("retcode"))
        if not d["ok"] and d.get("comment"):
            d["retcode_text"] += f" — {d['comment']}"
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
                        tp_points: int | None = None, validate: bool = True) -> tuple[dict, Any]:
        if side not in ("buy", "sell"):
            raise MT5Error("side должен быть buy или sell")
        info = self._symbol(symbol)
        if validate:
            self._pre_trade(info, side)
        tick = self._tick(symbol)
        price = tick.ask if side == "buy" else tick.bid
        sgn = 1 if side == "buy" else -1
        if sl_points and not sl:
            sl = price - sgn * float(sl_points) * float(info.point)
        if tp_points and not tp:
            tp = price + sgn * float(tp_points) * float(info.point)
        sl, tp = self._norm_price(info, sl), self._norm_price(info, tp)
        self._check_stops(info, tick, side, sl, tp)
        req = {
            "action": C.TRADE_ACTION_DEAL, "symbol": symbol, "volume": self._norm_volume(info, volume),
            "type": C.ORDER_TYPES[side], "price": self._norm_price(info, price), "deviation": int(deviation),
            "magic": int(magic), "comment": (comment or "")[:31], "type_time": C.ORDER_TIME_GTC,
            "type_filling": self._filling_candidates(info)[0],
        }
        if sl:
            req["sl"] = sl
        if tp:
            req["tp"] = tp
        return req, info

    # ------------------------------------------------------------------ trading
    def calc(self, symbol: str, side: str, volume: float, price: float | None = None, sl: float | None = None,
             tp: float | None = None) -> dict:
        """Margin and P/L at SL/TP via order_calc_margin / order_calc_profit (in account currency)."""
        self._require()
        if side not in ("buy", "sell"):
            raise MT5Error("side должен быть buy или sell")
        info = self._symbol(symbol)
        tick = self._tick(symbol)
        price = float(price) if price else (tick.ask if side == "buy" else tick.bid)
        vol = self._norm_volume(info, volume)
        action = C.ORDER_TYPES[side]
        margin = self.mt5.order_calc_margin(action, symbol, vol, price)
        if margin is None:
            self._raise_last("order_calc_margin")

        def profit(close: float | None) -> float | None:
            if not close:
                return None
            p = self.mt5.order_calc_profit(action, symbol, vol, price, float(close))
            return None if p is None else round(float(p), 2)

        one_point = profit(price + (1 if side == "buy" else -1) * float(info.point))
        acc = self.mt5.account_info()
        return {"symbol": symbol, "side": side, "volume": vol, "price": price, "margin": round(float(margin), 2),
                "profit_at_sl": profit(sl), "profit_at_tp": profit(tp), "point_value": one_point,
                "currency": acc.currency if acc else None,
                "margin_free_after": round(float(acc.margin_free) - float(margin), 2) if acc else None}

    def check_market_order(self, symbol: str, side: str, volume: float, sl: float | None = None,
                           tp: float | None = None, deviation: int = 20, magic: int = 0, comment: str = "") -> dict:
        self._require()
        req, _ = self._market_request(symbol, side, volume, sl, tp, deviation, magic, comment, validate=False)
        res = self.mt5.order_check(req)
        if res is None:
            self._raise_last("order_check")
        d = _plain(res)
        d["retcode_text"] = C.retcode_text(d.get("retcode")) if d.get("retcode") else "Проверка пройдена"
        d["ok"] = d.get("retcode") in (0, C.TRADE_RETCODE_DONE)
        d["request"] = req
        return d

    def market_order(self, symbol: str, side: str, volume: float, sl: float | None = None, tp: float | None = None,
                     deviation: int = 20, magic: int = 0, comment: str = "", sl_points: int | None = None,
                     tp_points: int | None = None) -> dict:
        """Market order. ``sl_points``/``tp_points`` are converted to prices from the execution quote.
        Requotes / changed prices are retried with a fresh quote."""
        self._require()
        res: dict = {}
        for attempt in range(self.MARKET_RETRIES):
            req, info = self._market_request(symbol, side, volume, sl, tp, deviation, magic, comment,
                                             sl_points, tp_points)
            res = self._send(req, info)
            res["attempts"] = attempt + 1
            if res.get("retcode") not in C.RETRY_RETCODES:
                break
            self.sleep(0.3)
        return res

    def pending_order(self, symbol: str, order_type: str, volume: float, price: float, sl: float | None = None,
                      tp: float | None = None, stoplimit: float | None = None, magic: int = 0, comment: str = "",
                      expiration: float | None = None) -> dict:
        self._require()
        if order_type not in ("buy_limit", "sell_limit", "buy_stop", "sell_stop", "buy_stop_limit", "sell_stop_limit"):
            raise MT5Error(f"Неверный тип отложенного ордера: {order_type}")
        info = self._symbol(symbol)
        side = "buy" if order_type.startswith("buy") else "sell"
        self._pre_trade(info, side)
        tick = self._tick(symbol)
        price_n = self._norm_price(info, price)
        level = max(int(getattr(info, "trade_stops_level", 0) or 0), 0) * float(info.point)
        market = tick.ask if side == "buy" else tick.bid
        rules = {"buy_limit": price_n <= market - level, "sell_limit": price_n >= market + level,
                 "buy_stop": price_n >= market + level, "sell_stop": price_n <= market - level,
                 "buy_stop_limit": price_n >= market + level, "sell_stop_limit": price_n <= market - level}
        if not rules[order_type]:
            where = "ниже" if order_type in ("buy_limit", "sell_stop", "sell_stop_limit") else "выше"
            raise MT5Error(f"Цена {price_n} для {order_type} должна быть {where} текущей ({market}) минимум на "
                           f"{int(level / float(info.point))} пунктов", 10015)
        req: dict[str, Any] = {
            "action": C.TRADE_ACTION_PENDING, "symbol": symbol, "volume": self._norm_volume(info, volume),
            "type": C.ORDER_TYPES[order_type], "price": price_n, "magic": int(magic),
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
        res: dict = {}
        for attempt in range(self.MARKET_RETRIES):
            found = self.mt5.positions_get(ticket=int(ticket))
            if not found:
                raise MT5Error(f"Позиция #{ticket} не найдена (уже закрыта?)", 10036)
            pos = found[0]
            info = self._symbol(pos.symbol)
            is_buy = pos.type == C.POSITION_TYPE_BUY
            self._pre_trade(info, "sell" if is_buy else "buy", closing=True)
            tick = self._tick(pos.symbol)
            vol = self._norm_volume(info, volume if volume else pos.volume)
            if vol > float(pos.volume) + 1e-9:
                raise MT5Error(f"Объём закрытия {vol} больше объёма позиции {pos.volume}", 10038)
            req = {
                "action": C.TRADE_ACTION_DEAL, "symbol": pos.symbol, "position": int(pos.ticket), "volume": vol,
                "type": C.ORDER_TYPES["sell" if is_buy else "buy"],
                "price": self._norm_price(info, tick.bid if is_buy else tick.ask), "deviation": int(deviation),
                "magic": int(pos.magic), "comment": (comment or "close")[:31], "type_time": C.ORDER_TIME_GTC,
                "type_filling": self._filling_candidates(info)[0],
            }
            res = self._send(req, info)
            res["attempts"] = attempt + 1
            if res.get("retcode") not in C.RETRY_RETCODES:
                break
            self.sleep(0.3)
        return res

    def modify_position(self, ticket: int, sl: float | None = None, tp: float | None = None) -> dict:
        self._require()
        res = self.mt5.positions_get(ticket=int(ticket))
        if not res:
            raise MT5Error(f"Позиция #{ticket} не найдена", 10036)
        pos = res[0]
        info = self._symbol(pos.symbol)
        side = "buy" if pos.type == C.POSITION_TYPE_BUY else "sell"
        self._pre_trade(info, side, closing=True)
        sl_n, tp_n = self._norm_price(info, sl), self._norm_price(info, tp)
        self._check_stops(info, self._tick(pos.symbol), side, sl_n, tp_n)
        req = {"action": C.TRADE_ACTION_SLTP, "symbol": pos.symbol, "position": int(pos.ticket),
               "sl": sl_n, "tp": tp_n, "magic": int(pos.magic)}
        return self._result(self.mt5.order_send(dict(req)), req)

    def modify_order(self, ticket: int, price: float, sl: float | None = None, tp: float | None = None) -> dict:
        self._require()
        res = self.mt5.orders_get(ticket=int(ticket))
        if not res:
            raise MT5Error(f"Ордер #{ticket} не найден", 10013)
        o = res[0]
        info = self._symbol(o.symbol)
        self._pre_trade(info, None, closing=True)
        req = {"action": C.TRADE_ACTION_MODIFY, "order": int(o.ticket), "symbol": o.symbol,
               "price": self._norm_price(info, price), "sl": self._norm_price(info, sl),
               "tp": self._norm_price(info, tp), "type_time": int(o.type_time),
               "expiration": int(o.time_expiration or 0)}
        return self._result(self.mt5.order_send(dict(req)), req)

    def cancel_order(self, ticket: int) -> dict:
        self._require()
        self._pre_trade(None, None, closing=True)
        req = {"action": C.TRADE_ACTION_REMOVE, "order": int(ticket)}
        return self._result(self.mt5.order_send(dict(req)), req)


def dispatch(client: MT5Client, method: str, params: dict | None) -> Any:
    if method not in MT5Client.METHODS:
        raise MT5Error(f"Метод {method} не разрешён")
    return getattr(client, method)(**(params or {}))
