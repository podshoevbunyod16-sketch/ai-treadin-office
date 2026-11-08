import argparse

import MetaTrader5  # test double from tests/mt5_testkit (on sys.path via conftest)

from app.mt5 import diagnose


def args(**kw):
    base = dict(login=None, password=None, server=None, path=None, symbol="EURUSD", trade=False)
    base.update(kw)
    return argparse.Namespace(**base)


def test_diagnose_full_run_with_demo_trade(capsys, monkeypatch):
    MetaTrader5._terminal.reset()
    monkeypatch.setattr(diagnose.time, "sleep", lambda s: None)
    code = diagnose.run(args(login=5000001, password="demo-pass-1", server="TestBroker-Demo", trade=True))
    out = capsys.readouterr().out
    assert code == 0, out
    assert "Открытие BUY" in out and "Закрытие #" in out and "всё работает" in out
    assert MetaTrader5._terminal.positions == {}


def test_diagnose_reports_disabled_algo_trading(capsys):
    MetaTrader5._terminal.reset()
    MetaTrader5._terminal.algo_trading = False
    code = diagnose.run(args())
    out = capsys.readouterr().out
    assert code == 1 and "[FAIL] Кнопка «Алго-трейдинг»" in out
    MetaTrader5._terminal.reset()


def test_diagnose_refuses_trade_on_real(capsys):
    MetaTrader5._terminal.reset()
    MetaTrader5._terminal.trade_mode = 2
    code = diagnose.run(args(trade=True))
    out = capsys.readouterr().out
    assert code == 1 and "счёт не DEMO" in out and MetaTrader5._terminal.sent_requests == []
    MetaTrader5._terminal.reset()


def test_diagnose_bad_password(capsys):
    MetaTrader5._terminal.reset()
    code = diagnose.run(args(login=5000001, password="wrong", server="TestBroker-Demo"))
    assert code == 1 and "Authorization failed" in capsys.readouterr().out
