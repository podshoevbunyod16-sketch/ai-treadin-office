"""MetaTrader 5 constants (values identical to the official MetaTrader5 Python package)."""
from __future__ import annotations

TIMEFRAMES: dict[str, int] = {
    "M1": 1, "M2": 2, "M3": 3, "M4": 4, "M5": 5, "M6": 6, "M10": 10, "M12": 12, "M15": 15, "M20": 20, "M30": 30,
    "H1": 16385, "H2": 16386, "H3": 16387, "H4": 16388, "H6": 16390, "H8": 16392, "H12": 16396,
    "D1": 16408, "W1": 32769, "MN1": 49153,
}

TIMEFRAME_SECONDS: dict[str, int] = {
    "M1": 60, "M2": 120, "M3": 180, "M4": 240, "M5": 300, "M6": 360, "M10": 600, "M12": 720, "M15": 900,
    "M20": 1200, "M30": 1800, "H1": 3600, "H2": 7200, "H3": 10800, "H4": 14400, "H6": 21600, "H8": 28800,
    "H12": 43200, "D1": 86400, "W1": 604800, "MN1": 2592000,
}

TRADE_ACTION_DEAL = 1
TRADE_ACTION_PENDING = 5
TRADE_ACTION_SLTP = 6
TRADE_ACTION_MODIFY = 7
TRADE_ACTION_REMOVE = 8

ORDER_TYPES: dict[str, int] = {
    "buy": 0, "sell": 1, "buy_limit": 2, "sell_limit": 3, "buy_stop": 4, "sell_stop": 5,
    "buy_stop_limit": 6, "sell_stop_limit": 7,
}
ORDER_TYPE_NAMES = {v: k for k, v in ORDER_TYPES.items()}
ORDER_TYPE_NAMES[8] = "close_by"

ORDER_FILLING_FOK = 0
ORDER_FILLING_IOC = 1
ORDER_FILLING_RETURN = 2
ORDER_TIME_GTC = 0
ORDER_TIME_SPECIFIED = 2

SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2

POSITION_TYPE_BUY = 0
POSITION_TYPE_SELL = 1

DEAL_TYPES = {0: "buy", 1: "sell", 2: "balance", 3: "credit", 4: "charge", 5: "correction", 6: "bonus",
              7: "commission", 8: "commission_daily", 9: "commission_monthly", 10: "commission_agent_daily",
              11: "commission_agent_monthly", 12: "interest", 13: "buy_canceled", 14: "sell_canceled",
              15: "dividend", 16: "dividend_franked", 17: "tax"}
DEAL_ENTRIES = {0: "in", 1: "out", 2: "inout", 3: "out_by"}

ACCOUNT_TRADE_MODES = {0: "demo", 1: "contest", 2: "real"}

TRADE_RETCODE_PLACED = 10008
TRADE_RETCODE_DONE = 10009
TRADE_RETCODE_DONE_PARTIAL = 10010
SUCCESS_RETCODES = {TRADE_RETCODE_PLACED, TRADE_RETCODE_DONE, TRADE_RETCODE_DONE_PARTIAL}

RETCODES: dict[int, str] = {
    10004: "Реквота", 10006: "Запрос отклонён", 10007: "Запрос отменён трейдером",
    10008: "Ордер размещён", 10009: "Заявка выполнена", 10010: "Заявка выполнена частично",
    10011: "Ошибка обработки запроса", 10012: "Запрос отменён по истечении времени",
    10013: "Неправильный запрос", 10014: "Неправильный объём", 10015: "Неправильная цена",
    10016: "Неправильные стопы", 10017: "Торговля запрещена", 10018: "Рынок закрыт",
    10019: "Недостаточно средств", 10020: "Цены изменились", 10021: "Нет котировок",
    10022: "Неверная дата истечения ордера", 10023: "Состояние ордера изменилось",
    10024: "Слишком частые запросы", 10025: "В запросе нет изменений",
    10026: "Автотрейдинг запрещён сервером", 10027: "Автотрейдинг запрещён клиентским терминалом",
    10028: "Запрос заблокирован для обработки", 10029: "Ордер или позиция заморожены",
    10030: "Неподдерживаемый тип исполнения (filling)", 10031: "Нет соединения с торговым сервером",
    10032: "Операция разрешена только для реальных счетов", 10033: "Достигнут лимит отложенных ордеров",
    10034: "Достигнут лимит объёма ордеров и позиций по символу", 10035: "Неверный или запрещённый тип ордера",
    10036: "Позиция уже закрыта", 10038: "Объём закрытия превышает объём позиции",
    10039: "Для позиции уже есть ордер на закрытие", 10040: "Достигнут лимит открытых позиций",
    10041: "Запрос на активацию отложенного ордера отклонён", 10042: "Разрешены только длинные позиции",
    10043: "Разрешены только короткие позиции", 10044: "Разрешено только закрытие позиций",
    10045: "Закрытие разрешено только по правилу FIFO", 10046: "Запрещено открывать встречные позиции (хеджинг)",
}


def retcode_text(code: int | None) -> str:
    if code is None:
        return "Нет ответа"
    return RETCODES.get(int(code), f"Код {code}")

TRADE_ACTION_CLOSE_BY = 10

SYMBOL_TRADE_MODES = {0: "disabled", 1: "longonly", 2: "shortonly", 3: "closeonly", 4: "full"}
SYMBOL_TRADE_EXECUTIONS = {0: "request", 1: "instant", 2: "market", 3: "exchange"}
ACCOUNT_MARGIN_MODES = {0: "netting", 1: "exchange", 2: "hedging"}
BOOK_TYPES = {1: "sell", 2: "buy", 3: "sell_market", 4: "buy_market"}
COPY_TICKS_ALL = -1

# Retcodes after which a market request is re-sent with a fresh quote
RETRY_RETCODES = {10004, 10020, 10021}

# last_error() codes of the MetaTrader5 package
MT5_ERRORS = {
    1: "Успешно", -1: "Общая ошибка", -2: "Неверные параметры", -3: "Нет памяти", -4: "Нет истории",
    -5: "Неверная версия", -6: "Ошибка авторизации", -7: "Метод не поддерживается", -8: "Автотрейдинг отключён",
    -10000: "Внутренняя ошибка IPC", -10001: "Ошибка отправки IPC", -10002: "Ошибка приёма IPC",
    -10003: "Ошибка инициализации IPC (терминал не найден)", -10004: "Нет IPC-соединения с терминалом",
    -10005: "Таймаут IPC",
}
