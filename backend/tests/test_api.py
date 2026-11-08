import pytest

from app.models import BrokerAccount
from app.db import session_scope

from .conftest import BRIDGE_TOKEN, make_admin, wait_for

ACC = {"name": "Demo", "connection_type": "bridge", "login": 5000001, "server": "TestBroker-Demo",
       "password": "demo-pass-1", "bridge_url": "http://bridge.test:8765", "bridge_token": BRIDGE_TOKEN}


async def test_setup_login_and_roles(app_client):
    c = app_client
    assert (await c.get("/api/auth/state")).json() == {"setup_required": True}
    assert (await c.get("/api/accounts")).status_code == 401
    r = await c.post("/api/auth/setup", json={"username": "admin", "password": "weak"})
    assert r.status_code == 422
    h = await make_admin(c)
    assert (await c.post("/api/auth/setup", json={"username": "xx2", "password": "Another-pass-1"})).status_code == 409
    assert (await c.get("/api/auth/me", headers=h)).json()["role"] == "admin"

    r = await c.post("/api/users", headers=h, json={"username": "viewer1", "password": "Viewer-pass-1", "role": "viewer"})
    assert r.status_code == 201
    r = await c.post("/api/auth/login", json={"username": "viewer1", "password": "Viewer-pass-1"})
    vh = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert (await c.get("/api/accounts", headers=vh)).status_code == 200
    assert (await c.post("/api/accounts", headers=vh, json=ACC)).status_code == 403
    assert (await c.get("/api/users", headers=vh)).status_code == 403

    # role change invalidates existing tokens
    uid = r.json()["user"]["id"]
    await c.patch(f"/api/users/{uid}", headers=h, json={"role": "trader"})
    assert (await c.get("/api/auth/me", headers=vh)).status_code == 401


async def test_login_throttling(app_client):
    c = app_client
    await make_admin(c)
    codes = [(await c.post("/api/auth/login", json={"username": "admin", "password": "bad-password1"})).status_code
             for _ in range(11)]
    assert codes[:10] == [401] * 10 and codes[10] == 429


async def test_change_password_revokes_tokens(app_client):
    c = app_client
    h = await make_admin(c)
    r = await c.post("/api/auth/change-password", headers=h,
                     json={"current_password": "Sup3r-secret-pw", "password": "N3w-secret-pass"})
    assert r.status_code == 200
    assert (await c.get("/api/auth/me", headers=h)).status_code == 401
    assert (await c.post("/api/auth/login", json={"username": "admin", "password": "N3w-secret-pass"})).status_code == 200


async def test_account_secrets_are_encrypted_and_hidden(app_client):
    c = app_client
    h = await make_admin(c)
    r = await c.post("/api/accounts", headers=h, json=ACC)
    assert r.status_code == 201
    body = r.json()
    assert "password" not in body and body["has_password"] and body["has_bridge_token"]
    assert "demo-pass-1" not in r.text and BRIDGE_TOKEN not in r.text
    with session_scope() as s:
        row = s.get(BrokerAccount, body["id"])
        assert row.password_enc and "demo-pass-1" not in row.password_enc
    bad = dict(ACC, bridge_url="ftp://x")
    assert (await c.post("/api/accounts", headers=h, json=bad)).status_code == 422
    no_token = dict(ACC, bridge_token=None)
    assert (await c.post("/api/accounts", headers=h, json=no_token)).status_code == 422


async def test_not_connected_account_returns_409(app_client):
    c = app_client
    h = await make_admin(c)
    aid = (await c.post("/api/accounts", headers=h, json=ACC)).json()["id"]
    r = await c.get(f"/api/accounts/{aid}/positions", headers=h)
    assert r.status_code == 409 and "не подключён" in r.json()["detail"]


async def test_connect_trade_and_history_via_bridge(app_client, use_bridge, terminal):
    c = app_client
    h = await make_admin(c)
    aid = (await c.post("/api/accounts", headers=h, json=ACC)).json()["id"]
    r = await c.post(f"/api/accounts/{aid}/connect", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "connected" and r.json()["account"]["login"] == 5000001
    acc = (await c.get(f"/api/accounts/{aid}", headers=h)).json()
    assert acc["trade_mode_name"] == "demo" and acc["currency"] == "USD"

    assert len((await c.get(f"/api/accounts/{aid}/symbols", headers=h)).json()) == 2
    t = (await c.get(f"/api/accounts/{aid}/ticks", headers=h, params={"symbols": "EURUSD"})).json()
    assert t["EURUSD"]["bid"] > 0
    rates = (await c.get(f"/api/accounts/{aid}/rates", headers=h, params={"symbol": "EURUSD", "timeframe": "H1",
                                                                          "count": 20})).json()
    assert len(rates) == 20
    assert (await c.get(f"/api/accounts/{aid}/rates", headers=h, params={"symbol": "EUR USD"})).status_code == 422

    chk = await c.post(f"/api/accounts/{aid}/orders/check", headers=h, json={"symbol": "EURUSD", "side": "buy", "volume": 0.1})
    assert chk.json()["ok"]
    r = await c.post(f"/api/accounts/{aid}/orders/market", headers=h,
                     json={"symbol": "EURUSD", "side": "buy", "volume": 0.1})
    assert r.status_code == 200 and r.json()["ok"], r.text
    pos = (await c.get(f"/api/accounts/{aid}/positions", headers=h)).json()
    assert len(pos) == 1
    tk = pos[0]["ticket"]
    assert (await c.patch(f"/api/accounts/{aid}/positions/{tk}", headers=h, json={"sl": 1.0, "tp": 0})).json()["ok"]
    assert (await c.post(f"/api/accounts/{aid}/positions/{tk}/close", headers=h, json={})).json()["ok"]

    r = await c.post(f"/api/accounts/{aid}/orders/pending", headers=h,
                     json={"symbol": "EURUSD", "order_type": "sell_limit", "volume": 0.1, "price": 1.2})
    otk = r.json()["order"]
    assert (await c.patch(f"/api/accounts/{aid}/orders/{otk}", headers=h, json={"price": 1.21})).json()["ok"]
    assert (await c.delete(f"/api/accounts/{aid}/orders/{otk}", headers=h)).json()["ok"]

    deals = (await c.get(f"/api/accounts/{aid}/history/deals", headers=h)).json()
    assert len(deals) == 2
    assert len((await c.get(f"/api/accounts/{aid}/history/orders", headers=h)).json()) == 2

    audit = (await c.get("/api/audit", headers=h, params={"action": "trade"})).json()
    assert {a["action"] for a in audit} >= {"trade.market", "trade.close", "trade.pending", "trade.cancel_order"}

    # streaming snapshot reaches the runtime
    await c.put(f"/api/accounts/{aid}/watchlist", headers=h, json={"symbols": ["EURUSD", "XAUUSD"]})
    st = await wait_for(lambda: _status_with_ticks(c, aid, h))
    assert set(st["ticks"]) == {"EURUSD", "XAUUSD"}

    assert (await c.post(f"/api/accounts/{aid}/disconnect", headers=h)).json()["status"] == "disconnected"


async def _status_with_ticks(c, aid, h):
    st = (await c.get(f"/api/accounts/{aid}/status", headers=h)).json()
    return st if len(st.get("ticks") or {}) == 2 else None


async def test_real_account_trading_blocked(app_client, use_bridge, terminal):
    terminal.trade_mode = 2
    c = app_client
    h = await make_admin(c)
    aid = (await c.post("/api/accounts", headers=h, json=ACC)).json()["id"]
    await c.post(f"/api/accounts/{aid}/connect", headers=h)
    r = await c.post(f"/api/accounts/{aid}/orders/market", headers=h, json={"symbol": "EURUSD", "side": "buy", "volume": 0.1})
    assert r.status_code == 403 and "РЕАЛЬНЫЙ" in r.json()["detail"]
    assert terminal.positions == {}


async def test_connect_failure_is_reported(app_client, use_bridge):
    c = app_client
    h = await make_admin(c)
    aid = (await c.post("/api/accounts", headers=h, json=dict(ACC, password="wrong"))).json()["id"]
    r = await c.post(f"/api/accounts/{aid}/connect", headers=h)
    assert r.status_code == 502 and "Authorization failed" in r.json()["detail"]
    st = (await c.get(f"/api/accounts/{aid}", headers=h)).json()["runtime"]
    assert st["status"] == "error"


async def test_local_mode_connection(app_client):
    c = app_client
    h = await make_admin(c)
    body = dict(ACC, connection_type="local", bridge_url=None, bridge_token=None)
    aid = (await c.post("/api/accounts", headers=h, json=body)).json()["id"]
    r = await c.post(f"/api/accounts/{aid}/connect", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "connected", r.text
    r = await c.post(f"/api/accounts/{aid}/orders/market", headers=h, json={"symbol": "EURUSD", "side": "sell", "volume": 0.05})
    assert r.json()["ok"]
    await c.post(f"/api/accounts/{aid}/disconnect", headers=h)


async def test_system_status(app_client):
    c = app_client
    h = await make_admin(c)
    st = (await c.get("/api/system/status", headers=h)).json()
    assert st["allow_real_trading"] is False and "mt5_package_installed" in st
    assert (await c.get("/api/health")).json()["ok"]


async def test_auto_reconnect_after_connection_loss(app_client, use_bridge, terminal):
    c = app_client
    h = await make_admin(c)
    aid = (await c.post("/api/accounts", headers=h, json=ACC)).json()["id"]
    assert (await c.post(f"/api/accounts/{aid}/connect", headers=h)).status_code == 200
    original = terminal.terminal_info
    terminal.terminal_info = lambda: terminal._fail(-10004, "No IPC connection")

    async def status():
        return (await c.get(f"/api/accounts/{aid}", headers=h)).json()["runtime"]

    rt = await wait_for(lambda: _has_status(status, "error"))
    assert "No IPC connection" in rt["error"]
    terminal.terminal_info = original
    await wait_for(lambda: _has_status(status, "connected"), timeout=15)


async def _has_status(fn, value):
    rt = await fn()
    return rt if rt["status"] == value else None


async def test_input_validation_and_account_patch(app_client, use_bridge):
    c = app_client
    h = await make_admin(c)
    aid = (await c.post("/api/accounts", headers=h, json=ACC)).json()["id"]
    assert (await c.patch(f"/api/accounts/{aid}", headers=h, json={"bridge_url": "javascript:alert(1)"})).status_code == 422
    r = await c.patch(f"/api/accounts/{aid}", headers=h, json={"name": "Renamed", "clear_password": True})
    assert r.status_code == 200 and r.json()["name"] == "Renamed" and r.json()["has_password"] is False
    await c.post(f"/api/accounts/{aid}/connect", headers=h)  # terminal already logged in -> attach without password
    bad_symbol = {"symbol": "EUR'; DROP", "side": "buy", "volume": 0.1}
    assert (await c.post(f"/api/accounts/{aid}/orders/market", headers=h, json=bad_symbol)).status_code == 422
    assert (await c.post(f"/api/accounts/{aid}/orders/market", headers=h,
                         json={"symbol": "EURUSD", "side": "hold", "volume": 0.1})).status_code == 422
    assert (await c.post(f"/api/accounts/{aid}/orders/market", headers=h,
                         json={"symbol": "EURUSD", "side": "buy", "volume": -1})).status_code == 422
    wl = await c.put(f"/api/accounts/{aid}/watchlist", headers=h, json={"symbols": ["EURUSD", "EURUSD", " XAUUSD "]})
    assert wl.json()["symbols"] == ["EURUSD", "XAUUSD"]
    # account with bots cannot be deleted
    await c.post("/api/bots", headers=h, json={"name": "b", "account_id": aid, "strategy": "sma_cross", "symbol": "EURUSD"})
    assert (await c.delete(f"/api/accounts/{aid}", headers=h)).status_code == 409


async def test_diagnostics_calc_and_book_endpoints(app_client, use_bridge, terminal):
    c = app_client
    h = await make_admin(c)
    aid = (await c.post("/api/accounts", headers=h, json=ACC)).json()["id"]
    await c.post(f"/api/accounts/{aid}/connect", headers=h)
    d = (await c.get(f"/api/accounts/{aid}/diagnostics", headers=h)).json()
    assert d["ready"] and any(x["key"] == "algo_button" for x in d["checks"])
    calc = (await c.post(f"/api/accounts/{aid}/orders/calc", headers=h,
                         json={"symbol": "EURUSD", "side": "sell", "volume": 0.1})).json()
    assert calc["margin"] > 0 and calc["currency"] == "USD"
    assert (await c.get(f"/api/accounts/{aid}/book", headers=h, params={"symbol": "XAUUSD"})).json()["available"]
    assert not (await c.get(f"/api/accounts/{aid}/book", headers=h, params={"symbol": "EURUSD"})).json()["available"]
    terminal.algo_trading = False
    r = await c.post(f"/api/accounts/{aid}/orders/market", headers=h, json={"symbol": "EURUSD", "side": "buy", "volume": 0.1})
    assert r.status_code == 502 and "Алго-трейдинг" in r.json()["detail"]
    audit = (await c.get("/api/audit", headers=h, params={"action": "trade.market"})).json()
    assert audit[0]["ok"] is False
