import importlib.util

import httpx
import pytest

from app.mt5.client import MT5Error, MT5Unavailable
from app.mt5.gateway import BridgeGateway, ProcessGateway

from .conftest import BRIDGE_TOKEN

L, P, S = 5000001, "demo-pass-1", "TestBroker-Demo"


async def test_process_gateway_runs_worker_process():
    gw = ProcessGateway(timeout_s=20)
    await gw.start()
    try:
        assert gw.alive
        st = await gw.call("connect", login=L, password=P, server=S)
        assert st["account"]["login"] == L
        r = await gw.call("market_order", symbol="EURUSD", side="buy", volume=0.02, magic=9)
        assert r["ok"]
        pos = await gw.call("positions", magic=9)
        assert pos[0]["volume"] == 0.02
        with pytest.raises(MT5Error, match="не найдена"):
            await gw.call("close_position", ticket=1)
        with pytest.raises(MT5Error, match="не разрешён"):
            await gw.call("__init__")
    finally:
        await gw.close()
    assert not gw.alive


async def test_process_gateway_reports_missing_package(monkeypatch):
    real = importlib.util.find_spec
    monkeypatch.setattr(importlib.util, "find_spec", lambda n, *a: None if n == "MetaTrader5" else real(n, *a))
    import sys
    monkeypatch.delitem(sys.modules, "MetaTrader5", raising=False)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if "mt5_testkit" not in p])
    with pytest.raises(MT5Unavailable, match="только для Windows"):
        await ProcessGateway().start()


async def test_bridge_gateway(bridge_app, terminal):
    gw = BridgeGateway("http://bridge", BRIDGE_TOKEN, transport=httpx.ASGITransport(app=bridge_app))
    await gw.start()
    assert gw.info["mt5_package"] is True
    st = await gw.call("connect", login=L, password=P, server=S)
    assert st["account"]["server"] == S
    r = await gw.call("market_order", symbol="XAUUSD", side="sell", volume=0.01)
    assert r["ok"] and terminal.positions
    with pytest.raises(MT5Error, match="Authorization failed"):
        await gw.call("connect", login=L, password="nope", server=S)
    with pytest.raises(MT5Error, match="Неверные параметры"):
        await gw.call("positions", bogus=1)
    await gw.close()


async def test_bridge_rejects_bad_token(bridge_app):
    gw = BridgeGateway("http://bridge", "wrong-token-wrong-token-wrong", transport=httpx.ASGITransport(app=bridge_app))
    with pytest.raises(MT5Error, match="401"):
        await gw.start()


async def test_bridge_unreachable():
    gw = BridgeGateway("http://127.0.0.1:9", BRIDGE_TOKEN, timeout_s=2)
    with pytest.raises(MT5Error, match="недоступен"):
        await gw.start()


def test_bridge_requires_strong_token():
    from app.mt5.bridge_server import create_bridge_app

    with pytest.raises(SystemExit):
        create_bridge_app("short")


async def test_bridge_without_package():
    from app.mt5.bridge_server import create_bridge_app

    def factory():
        raise MT5Unavailable("no package")

    app = create_bridge_app(BRIDGE_TOKEN, client_factory=factory)
    gw = BridgeGateway("http://bridge", BRIDGE_TOKEN, transport=httpx.ASGITransport(app=app))
    with pytest.raises(MT5Unavailable, match="no package"):
        await gw.start()
