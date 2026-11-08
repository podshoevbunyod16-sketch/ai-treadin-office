from types import SimpleNamespace

import pytest

from app.market_data.mt5_connector import MT5Connector, MT5Settings


def settings(**overrides):
    values = dict(
        enabled=True, environment="demo", login=123456, password="demo-secret",
        server="Exness-MT5Trial15", terminal_path=None,
    )
    values.update(overrides)
    return MT5Settings(**values)


def test_status_never_exposes_password():
    result = MT5Connector(settings()).status()
    assert result["access"] == "read-only"
    assert result["trading_mode"] == "paper"
    assert "password" not in result


def test_disabled_connector_refuses_connect():
    connector = MT5Connector(settings(enabled=False))
    with pytest.raises(RuntimeError, match="disabled"):
        connector.connect()


def test_real_environment_is_rejected():
    connector = MT5Connector(settings(environment="real"))
    with pytest.raises(RuntimeError, match="Only MT5 demo"):
        connector.connect()


def test_tick_requires_connection():
    connector = MT5Connector(settings())
    with pytest.raises(RuntimeError, match="not connected"):
        connector.tick("EURUSD")


def test_demo_connection_and_tick_with_fake_mt5(monkeypatch):
    class FakeMT5:
        ACCOUNT_TRADE_MODE_DEMO = 0

        def initialize(self, **kwargs):
            assert kwargs["server"] == "Exness-MT5Trial15"
            return True

        def account_info(self):
            return SimpleNamespace(
                trade_mode=0, login=123456, server="Exness-MT5Trial15", currency="USD"
            )

        def symbols_get(self):
            return [SimpleNamespace(name="EURUSD"), SimpleNamespace(name="GBPUSD")]

        def symbol_select(self, symbol, enabled):
            return symbol == "EURUSD" and enabled

        def symbol_info_tick(self, symbol):
            return SimpleNamespace(bid=1.1, ask=1.2, last=1.15, volume=10, time_msc=123)

        def shutdown(self):
            return True

        def last_error(self):
            return (0, "ok")

    import app.market_data.mt5_connector as module
    monkeypatch.setattr(module.platform, "system", lambda: "Windows")
    connector = MT5Connector(settings(), mt5_module=FakeMT5())
    result = connector.connect()
    assert result["status"] == "connected"
    assert connector.symbols() == ["EURUSD", "GBPUSD"]
    assert connector.tick("EURUSD")["bid"] == 1.1
    connector.disconnect()
    assert connector.status()["connected"] is False
