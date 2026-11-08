"""Command-line check of the MetaTrader 5 integration on a real terminal.

Run on the Windows machine where MetaTrader 5 is installed (from the ``backend`` folder)::

    python -m app.mt5.diagnose                                   # attach to the logged-in terminal
    python -m app.mt5.diagnose --login 5012345 --server MetaQuotes-Demo   # password is asked
    python -m app.mt5.diagnose --symbol EURUSD --trade           # + open & close minimal position (DEMO only)

It uses exactly the same MT5Client code as the web application.
"""
from __future__ import annotations

import argparse
import getpass
import sys
import time
from datetime import datetime, timezone

from .client import MT5Client, MT5Error, MT5Unavailable


class Report:
    def __init__(self) -> None:
        self.failed = 0

    def ok(self, title: str, detail: str = "") -> None:
        print(f"  [OK]   {title}" + (f": {detail}" if detail else ""))

    def warn(self, title: str, detail: str = "") -> None:
        print(f"  [WARN] {title}" + (f": {detail}" if detail else ""))

    def fail(self, title: str, detail: str = "") -> None:
        self.failed += 1
        print(f"  [FAIL] {title}" + (f": {detail}" if detail else ""))

    @staticmethod
    def section(title: str) -> None:
        print(f"\n== {title}")


def run(args: argparse.Namespace) -> int:
    r = Report()
    r.section("Пакет MetaTrader5")
    try:
        client = MT5Client()
    except MT5Unavailable as exc:
        r.fail("import MetaTrader5", str(exc))
        return 1
    r.ok("import MetaTrader5", f"версия пакета {getattr(client.mt5, '__version__', '?')}")

    r.section("Подключение к терминалу")
    password = args.password
    if args.login and password is None:
        password = getpass.getpass(f"Пароль счёта {args.login} (Enter — использовать уже авторизованный терминал): ") or None
    try:
        st = client.connect(login=args.login, password=password, server=args.server, path=args.path)
    except MT5Error as exc:
        r.fail("initialize/login", str(exc))
        return 1
    acc, term = st["account"], st["terminal"]
    r.ok("Терминал", f"{term.get('name')} build {st['version']['build'] if st.get('version') else '?'}, {term.get('path')}")
    r.ok("Счёт", f"#{acc['login']} {acc['name']} | {acc['server']} | {acc['company']} | "
                 f"{acc['trade_mode_name'].upper()} | {acc['margin_mode_name']} | 1:{acc['leverage']}")
    r.ok("Баланс/эквити", f"{acc['balance']} / {acc['equity']} {acc['currency']}, свободная маржа {acc['margin_free']}")

    r.section("Настройки для торговли через Python API")
    diag = client.diagnostics()
    for c in diag["checks"]:
        (r.ok if c["ok"] else r.fail if c["level"] == "error" else r.warn)(c["title"], c["detail"])

    r.section(f"Рыночные данные: {args.symbol}")
    try:
        info = client.symbol_info(args.symbol)
        r.ok("symbol_info", f"digits {info['digits']}, лот {info['volume_min']}..{info['volume_max']} шаг "
                            f"{info['volume_step']}, режим {info['trade_mode_name']}, исполнение {info['trade_exemode_name']}, "
                            f"stops level {info.get('trade_stops_level')}")
        tick = client.ticks([args.symbol])[args.symbol]
        if tick:
            age = time.time() + (client.server_offset() or 0) - tick["time"]
            r.ok("Котировка", f"bid {tick['bid']} ask {tick['ask']} спред {tick['spread_points']} п., "
                              f"время сервера {datetime.fromtimestamp(tick['time'], timezone.utc):%Y-%m-%d %H:%M:%S}"
                              + (f" (котировке ~{int(age)} с)" if client.server_offset() is not None else ""))
        else:
            r.fail("Котировка", "нет тика")
        bars = client.rates(args.symbol, "M1", 10)
        r.ok("copy_rates_from_pos M1", f"{len(bars)} баров, последний close {bars[-1]['close']}")
        off = client.server_offset()
        (r.ok if off is not None else r.warn)("Смещение времени сервера",
                                               f"UTC{off // 3600:+d}" if off is not None else "не определено (рынок закрыт?)")
        vol = info["volume_min"]
        calc = client.calc(args.symbol, "buy", vol)
        r.ok("order_calc_margin", f"{vol} лот = маржа {calc['margin']} {calc['currency']}, 1 пункт = {calc['point_value']}")
        chk = client.check_market_order(args.symbol, "buy", vol)
        (r.ok if chk["ok"] else r.fail)("order_check", f"{chk['retcode_text']} (retcode {chk.get('retcode')})")
    except MT5Error as exc:
        r.fail("Рыночные данные", str(exc))

    r.section("Торговое состояние")
    try:
        r.ok("positions_get", f"{len(client.positions())} открытых позиций")
        r.ok("orders_get", f"{len(client.orders())} отложенных ордеров")
        deals = client.history_deals(time.time() - 7 * 86400, time.time() + 86400)
        r.ok("history_deals_get", f"{len(deals)} сделок за 7 дней")
    except MT5Error as exc:
        r.fail("Торговое состояние", str(exc))

    if args.trade:
        r.section("Тестовая сделка (только DEMO)")
        if acc["trade_mode"] != 0:
            r.fail("Тестовая сделка", "счёт не DEMO — тестовая сделка не выполняется")
        else:
            try:
                vol = client.symbol_info(args.symbol)["volume_min"]
                res = client.market_order(args.symbol, "buy", vol, magic=999999, comment="ato diagnose")
                (r.ok if res["ok"] else r.fail)("Открытие BUY", f"{res['retcode_text']} (retcode {res['retcode']}, "
                                                               f"ордер {res.get('order')}, сделка {res.get('deal')}, цена {res.get('price')})")
                if res["ok"]:
                    time.sleep(2)
                    pos = [p for p in client.positions(symbol=args.symbol, magic=999999)]
                    if not pos:
                        r.fail("Позиция", "не найдена после открытия")
                    for p in pos:
                        c = client.close_position(p["ticket"], comment="ato diagnose")
                        (r.ok if c["ok"] else r.fail)(f"Закрытие #{p['ticket']}",
                                                      f"{c['retcode_text']} (retcode {c['retcode']}, цена {c.get('price')})")
                    time.sleep(1)
                    d = client.history_deals(time.time() - 3600, time.time() + 86400, magic=999999)
                    r.ok("История", f"сделок с magic 999999 за час: {len(d)}, P/L "
                                    f"{round(sum(x['profit'] + x['commission'] + x['swap'] for x in d), 2)}")
            except MT5Error as exc:
                r.fail("Тестовая сделка", str(exc))

    client.disconnect()
    print(f"\nИтог: {'всё работает' if not r.failed else f'ошибок: {r.failed}'}")
    return 1 if r.failed else 0


def main() -> None:  # pragma: no cover - CLI
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    p = argparse.ArgumentParser(description="Проверка интеграции с MetaTrader 5")
    p.add_argument("--login", type=int)
    p.add_argument("--password")
    p.add_argument("--server")
    p.add_argument("--path", help="путь к terminal64.exe")
    p.add_argument("--symbol", default="EURUSD")
    p.add_argument("--trade", action="store_true", help="открыть и закрыть минимальную позицию (только DEMO)")
    sys.exit(run(p.parse_args()))


if __name__ == "__main__":  # pragma: no cover
    main()
