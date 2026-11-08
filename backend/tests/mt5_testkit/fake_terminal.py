"""TEST-ONLY in-memory double of the MetaTrader5 Python API.

It is used exclusively by the automated test-suite (it lives in ``tests/`` and is never imported by the
application) to exercise the real MT5Client / gateway / bot code paths on Linux CI where the official
Windows-only package cannot be installed. It mirrors the official function signatures, namedtuple field
names, constants and return-codes so that serialisation and request building are verified.
"""
from __future__ import annotations

import itertools
import math
import time
from collections import namedtuple

import numpy as np

AccountInfo = namedtuple("AccountInfo", "login trade_mode leverage limit_orders margin_so_mode trade_allowed trade_expert "
                         "margin_mode currency_digits fifo_close balance credit profit equity margin margin_free "
                         "margin_level margin_so_call margin_so_so name server currency company")
TerminalInfo = namedtuple("TerminalInfo", "community_account community_connection connected dlls_allowed trade_allowed "
                          "tradeapi_disabled ping_last build name company language path data_path")
SymbolInfo = namedtuple("SymbolInfo", "name description path digits point visible select currency_base currency_profit "
                        "trade_mode trade_exemode volume_min volume_max volume_step volume_limit filling_mode "
                        "trade_contract_size trade_tick_size trade_stops_level spread bid ask")
BookInfo = namedtuple("BookInfo", "type price volume volume_dbl")
Tick = namedtuple("Tick", "time bid ask last volume time_msc flags volume_real")
TradePosition = namedtuple("TradePosition", "ticket time time_msc time_update time_update_msc type magic identifier "
                           "reason volume price_open sl tp price_current swap profit symbol comment external_id")
TradeOrder = namedtuple("TradeOrder", "ticket time_setup time_setup_msc time_done time_done_msc time_expiration type "
                        "type_time type_filling state magic position_id position_by_id reason volume_initial "
                        "volume_current price_open sl tp price_current price_stoplimit symbol comment external_id")
TradeDeal = namedtuple("TradeDeal", "ticket order time time_msc type entry magic position_id reason volume price "
                       "commission swap profit fee symbol comment external_id")
TradeRequest = namedtuple("TradeRequest", "action magic order symbol volume price stoplimit sl tp deviation type "
                          "type_filling type_time expiration comment position position_by")
OrderSendResult = namedtuple("OrderSendResult", "retcode deal order volume price bid ask comment request_id "
                             "retcode_external request")
OrderCheckResult = namedtuple("OrderCheckResult", "retcode balance equity profit margin margin_free margin_level "
                              "comment request")

TF_SECONDS = {1: 60, 5: 300, 15: 900, 30: 1800, 16385: 3600, 16388: 14400, 16408: 86400}
RATE_DTYPE = np.dtype([("time", "<i8"), ("open", "<f8"), ("high", "<f8"), ("low", "<f8"), ("close", "<f8"),
                       ("tick_volume", "<u8"), ("spread", "<i4"), ("real_volume", "<u8")])


class FakeTerminal:
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_H1 = 1, 5, 15, 16385

    LOGIN, PASSWORD, SERVER = 5000001, "demo-pass-1", "TestBroker-Demo"

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.initialized = False
        self.logged_in: int | None = None
        self.trade_mode = 0
        self.balance = 10000.0
        self.error = (1, "Success")
        self.symbols = {
            "EURUSD": dict(digits=5, point=0.00001, base=1.10000, filling=2, contract=100000, cur=("EUR", "USD"),
                           trade_mode=4, stops=0, tick_size=0.00001),
            "XAUUSD": dict(digits=2, point=0.01, base=2000.00, filling=1, contract=100, cur=("XAU", "USD"),
                           trade_mode=4, stops=50, tick_size=0.05),
        }
        self.selected: set[str] = set()
        self.positions: dict[int, dict] = {}
        self.orders: dict[int, dict] = {}
        self.deals: list[dict] = []
        self.history_orders: list[dict] = []
        self.tickets = itertools.count(100001)
        self.custom_closes: dict[tuple[str, int], list[float]] = {}
        self.sent_requests: list[dict] = []
        self.price_offset: dict[str, float] = {}
        self.margin_mode = 2              # 0 netting, 2 hedging
        self.algo_trading = True          # terminal "Algo Trading" button
        self.api_disabled = False         # "Disable trading via external Python API"
        self.acc_trade_allowed = True     # False when logged in with investor password
        self.acc_trade_expert = True
        self.requotes = 0                 # next N market requests answer 10004 (requote)
        self.init_failures: list[tuple[int, str]] = []  # queued initialize() failures
        self.books: set[str] = set()
        self.book_symbols = {"XAUUSD"}    # symbols with depth of market

    # ------------------------------------------------------------------ helpers
    def _fail(self, code: int, msg: str):
        self.error = (code, msg)
        return None

    def _ok(self):
        self.error = (1, "Success")

    def _price(self, symbol: str) -> tuple[float, float]:
        s = self.symbols[symbol]
        mid = s["base"] * (1 + 0.001 * math.sin(time.time() / 30.0)) + self.price_offset.get(symbol, 0.0)
        spread = 10 * s["point"]
        return round(mid - spread / 2, s["digits"]), round(mid + spread / 2, s["digits"])

    def set_closes(self, symbol: str, timeframe: int, closes: list[float]) -> None:
        """Test helper: the *closed* bars will have exactly these closes (a forming bar is appended)."""
        self.custom_closes[(symbol, timeframe)] = list(closes)

    # ------------------------------------------------------------------ connection
    def initialize(self, path=None, login=None, password=None, server=None, timeout=60000, portable=False):
        if self.init_failures:
            self.error = self.init_failures.pop(0)
            return False
        if path is not None and "missing" in str(path):
            return bool(self._fail(-10003, "IPC initialize failed, MetaTrader 5 x64 not found"))
        if login is not None:
            if int(login) != self.LOGIN or password != self.PASSWORD or server != self.SERVER:
                return bool(self._fail(-6, "Terminal: Authorization failed"))
        self.initialized = True
        self.logged_in = self.LOGIN
        self._ok()
        return True

    def login(self, login, password=None, server=None, timeout=60000):
        if int(login) != self.LOGIN or password != self.PASSWORD:
            return bool(self._fail(-6, "Terminal: Authorization failed"))
        self.logged_in = int(login)
        return True

    def shutdown(self):
        self.initialized = False
        return True

    def last_error(self):
        return self.error

    def version(self):
        return (500, 4000, "01 Jan 2026")

    def account_info(self):
        if not self.initialized:
            return self._fail(-10004, "No IPC connection")
        profit = sum(self._pos_profit(p) for p in self.positions.values())
        margin = sum(p["volume"] * 1000 for p in self.positions.values())
        eq = self.balance + profit
        return AccountInfo(self.logged_in, self.trade_mode, 100, 200, 0, self.acc_trade_allowed, self.acc_trade_expert,
                           self.margin_mode, 2, False,
                           round(self.balance, 2), 0.0, round(profit, 2), round(eq, 2), margin, round(eq - margin, 2),
                           (eq / margin * 100) if margin else 0.0, 50.0, 30.0, "Test Trader", self.SERVER, "USD",
                           "Test Broker Ltd")

    def terminal_info(self):
        if not self.initialized:
            return self._fail(-10004, "No IPC connection")
        return TerminalInfo(False, False, True, False, self.algo_trading, self.api_disabled, 25000, 4000,
                            "MetaTrader 5", "MetaQuotes Ltd.",
                            "en", "C:\\MT5", "C:\\MT5\\data")

    # ------------------------------------------------------------------ symbols / market data
    def _info(self, name: str) -> SymbolInfo:
        s = self.symbols[name]
        bid, ask = self._price(name)
        return SymbolInfo(name, f"{name} test", f"Forex\\{name}", s["digits"], s["point"], name in self.selected,
                          name in self.selected, s["cur"][0], s["cur"][1], s["trade_mode"], 2, 0.01, 100.0, 0.01, 0.0,
                          s["filling"], s["contract"], s["tick_size"], s["stops"], 10, bid, ask)

    def symbols_total(self):
        return len(self.symbols)

    def market_book_add(self, symbol):
        if symbol not in self.book_symbols:
            self.error = (-1, "Terminal: Call failed")
            return False
        self.books.add(symbol)
        return True

    def market_book_get(self, symbol):
        if symbol not in self.books:
            return None
        bid, ask = self._price(symbol)
        p = self.symbols[symbol]["point"]
        return tuple([BookInfo(1, round(ask + i * 10 * p, 2), 5 + i, 5.0 + i) for i in range(3)][::-1]
                     + [BookInfo(2, round(bid - i * 10 * p, 2), 4 + i, 4.0 + i) for i in range(3)])

    def market_book_release(self, symbol):
        self.books.discard(symbol)
        return True

    def order_calc_margin(self, action, symbol, volume, price):
        if symbol not in self.symbols:
            return self._fail(-2, "Invalid params")
        return round(volume * self.symbols[symbol]["contract"] * price / 100, 2)  # leverage 1:100

    def order_calc_profit(self, action, symbol, volume, price_open, price_close):
        if symbol not in self.symbols:
            return self._fail(-2, "Invalid params")
        diff = (price_close - price_open) if action == 0 else (price_open - price_close)
        return round(diff * volume * self.symbols[symbol]["contract"], 2)

    def symbols_get(self, group=None):
        if not self.initialized:
            return self._fail(-10004, "No IPC connection")
        return tuple(self._info(n) for n in self.symbols)

    def symbol_info(self, symbol):
        if symbol not in self.symbols:
            return self._fail(-1, "Terminal: Call failed")
        return self._info(symbol)

    def symbol_select(self, symbol, enable=True):
        if symbol not in self.symbols:
            return False
        self.selected.add(symbol)
        return True

    def symbol_info_tick(self, symbol):
        if symbol not in self.symbols or symbol not in self.selected:
            return self._fail(-1, "Terminal: Call failed")
        bid, ask = self._price(symbol)
        now = time.time()
        return Tick(int(now), bid, ask, 0.0, 0, int(now * 1000), 6, 0.0)

    def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
        if symbol not in self.symbols:
            return self._fail(-2, "Invalid params")
        sec = TF_SECONDS.get(timeframe, 60)
        now = int(time.time()) // sec * sec
        closes = self.custom_closes.get((symbol, timeframe))
        if closes is None:
            base = self.symbols[symbol]["base"]
            closes = [base * (1 + 0.002 * math.sin(i / 7.0)) for i in range(count)]
        closes = list(closes) + [closes[-1]]  # forming bar
        closes = closes[-count:]
        n = len(closes)
        arr = np.zeros(n, dtype=RATE_DTYPE)
        for i, c in enumerate(closes):
            o = closes[i - 1] if i else c
            arr[i] = (now - (n - 1 - i) * sec, o, max(o, c) * 1.0002, min(o, c) * 0.9998, c, 100 + i, 10, 0)
        return arr

    # ------------------------------------------------------------------ positions / orders / history
    def _pos_profit(self, p: dict) -> float:
        bid, ask = self._price(p["symbol"])
        cur = bid if p["type"] == 0 else ask
        diff = (cur - p["price_open"]) if p["type"] == 0 else (p["price_open"] - cur)
        return round(diff * p["volume"] * self.symbols[p["symbol"]]["contract"], 2)

    def _pos_tuple(self, p: dict) -> TradePosition:
        bid, ask = self._price(p["symbol"])
        cur = bid if p["type"] == 0 else ask
        return TradePosition(p["ticket"], p["time"], p["time"] * 1000, p["time"], p["time"] * 1000, p["type"], p["magic"],
                             p["ticket"], 3, p["volume"], p["price_open"], p["sl"], p["tp"], cur, 0.0,
                             self._pos_profit(p), p["symbol"], p["comment"], "")

    def positions_get(self, symbol=None, group=None, ticket=None):
        if not self.initialized:
            return self._fail(-10004, "No IPC connection")
        items = list(self.positions.values())
        if symbol:
            items = [p for p in items if p["symbol"] == symbol]
        if ticket:
            items = [p for p in items if p["ticket"] == ticket]
        return tuple(self._pos_tuple(p) for p in items)

    def positions_total(self):
        return len(self.positions)

    def _order_tuple(self, o: dict) -> TradeOrder:
        return TradeOrder(o["ticket"], o["time"], o["time"] * 1000, 0, 0, o.get("expiration", 0), o["type"],
                          o.get("type_time", 0), o.get("type_filling", 2), 1, o["magic"], 0, 0, 3, o["volume"],
                          o["volume"], o["price"], o["sl"], o["tp"], o["price"], o.get("stoplimit", 0.0), o["symbol"],
                          o["comment"], "")

    def orders_get(self, symbol=None, group=None, ticket=None):
        if not self.initialized:
            return self._fail(-10004, "No IPC connection")
        items = list(self.orders.values())
        if symbol:
            items = [o for o in items if o["symbol"] == symbol]
        if ticket:
            items = [o for o in items if o["ticket"] == ticket]
        return tuple(self._order_tuple(o) for o in items)

    def history_deals_get(self, date_from, date_to, group=None, ticket=None, position=None):
        if not self.initialized:
            return self._fail(-10004, "No IPC connection")
        f, t = date_from.timestamp(), date_to.timestamp()
        return tuple(TradeDeal(**d) for d in self.deals if f <= d["time"] <= t)

    def history_orders_get(self, date_from, date_to, group=None, ticket=None, position=None):
        if not self.initialized:
            return self._fail(-10004, "No IPC connection")
        f, t = date_from.timestamp(), date_to.timestamp()
        return tuple(self._order_tuple(o) for o in self.history_orders if f <= o["time"] <= t)

    # ------------------------------------------------------------------ trading
    def _result(self, retcode, request, deal=0, order=0, volume=0.0, price=0.0, comment=""):
        bid, ask = self._price(request.get("symbol")) if request.get("symbol") in self.symbols else (0.0, 0.0)
        tr = TradeRequest(**{f: request.get(f, 0 if f not in ("symbol", "comment") else "") for f in TradeRequest._fields})
        return OrderSendResult(retcode, deal, order, volume, price, bid, ask, comment, 1, 0, tr)

    def order_check(self, request):
        if not self.initialized:
            return self._fail(-10004, "No IPC connection")
        margin = request.get("volume", 0) * 1000
        acc = self.account_info()
        tr = TradeRequest(**{f: request.get(f, 0 if f not in ("symbol", "comment") else "") for f in TradeRequest._fields})
        return OrderCheckResult(0, acc.balance, acc.equity, acc.profit, margin, acc.margin_free - margin, 0.0, "Done", tr)

    def order_send(self, request):
        if not self.initialized:
            return self._fail(-10004, "No IPC connection")
        self.sent_requests.append(dict(request))
        action = request.get("action")
        sym = request.get("symbol")
        now = int(time.time())
        if action == 1 and self.requotes > 0:
            self.requotes -= 1
            return self._result(10004, request, comment="Requote")
        if action == 1:  # DEAL
            info = self.symbols.get(sym)
            if info is None:
                return self._result(10013, request, comment="Invalid request")
            if request["type_filling"] not in (info["filling"] - 1, 2):
                return self._result(10030, request, comment="Unsupported filling mode")
            vol = request["volume"]
            if vol < 0.01 or abs(round(vol / 0.01) * 0.01 - vol) > 1e-9:
                return self._result(10014, request, comment="Invalid volume")
            bid, ask = self._price(sym)
            price = ask if request["type"] == 0 else bid
            order_ticket, deal_ticket = next(self.tickets), next(self.tickets)
            pos_ticket = request.get("position")
            if pos_ticket:
                p = self.positions.get(pos_ticket)
                if p is None:
                    return self._result(10036, request, comment="Position closed")
                close_vol = min(vol, p["volume"])
                diff = (price - p["price_open"]) if p["type"] == 0 else (p["price_open"] - price)
                profit = round(diff * close_vol * info["contract"], 2)
                self.balance += profit
                p["volume"] = round(p["volume"] - close_vol, 2)
                if p["volume"] <= 0:
                    del self.positions[pos_ticket]
                entry, magic = 1, p["magic"]
            else:
                pos_ticket, profit, entry, magic = order_ticket, 0.0, 0, request.get("magic", 0)
                self.positions[pos_ticket] = dict(ticket=pos_ticket, time=now, type=request["type"], magic=magic,
                                                  volume=vol, price_open=price, sl=request.get("sl", 0.0),
                                                  tp=request.get("tp", 0.0), symbol=sym,
                                                  comment=request.get("comment", ""))
            self.deals.append(dict(ticket=deal_ticket, order=order_ticket, time=now, time_msc=now * 1000,
                                   type=request["type"], entry=entry, magic=magic, position_id=pos_ticket, reason=3,
                                   volume=vol, price=price, commission=0.0, swap=0.0, profit=profit, fee=0.0,
                                   symbol=sym, comment=request.get("comment", ""), external_id=""))
            self.history_orders.append(dict(ticket=order_ticket, time=now, type=request["type"], magic=magic, volume=vol,
                                            price=price, sl=0.0, tp=0.0, symbol=sym, comment=request.get("comment", "")))
            return self._result(10009, request, deal=deal_ticket, order=order_ticket, volume=vol, price=price,
                                comment="Request executed")
        if action == 5:  # PENDING
            t = next(self.tickets)
            self.orders[t] = dict(ticket=t, time=now, type=request["type"], magic=request.get("magic", 0),
                                  volume=request["volume"], price=request["price"], sl=request.get("sl", 0.0),
                                  tp=request.get("tp", 0.0), symbol=sym, comment=request.get("comment", ""),
                                  type_time=request.get("type_time", 0), expiration=request.get("expiration", 0))
            return self._result(10008, request, order=t, volume=request["volume"], price=request["price"],
                                comment="Request placed")
        if action == 6:  # SLTP
            p = self.positions.get(request.get("position"))
            if p is None:
                return self._result(10036, request)
            p["sl"], p["tp"] = request.get("sl", 0.0), request.get("tp", 0.0)
            return self._result(10009, request, comment="Request executed")
        if action == 7:  # MODIFY
            o = self.orders.get(request.get("order"))
            if o is None:
                return self._result(10013, request)
            o.update(price=request["price"], sl=request.get("sl", 0.0), tp=request.get("tp", 0.0))
            return self._result(10009, request, order=o["ticket"], comment="Request executed")
        if action == 8:  # REMOVE
            o = self.orders.pop(request.get("order"), None)
            if o is None:
                return self._result(10013, request, comment="Invalid request")
            return self._result(10009, request, order=o["ticket"], comment="Request executed")
        return self._result(10013, request, comment="Invalid request")
