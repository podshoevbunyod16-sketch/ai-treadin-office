import json

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from .test_api import ACC


@pytest.fixture
def client(use_bridge):
    from app.main import create_app
    from app.state import accounts

    with TestClient(create_app()) as c:
        yield c
    accounts.runtimes.clear()


def recv_until(ws, pred, limit=200):
    for _ in range(limit):
        msg = json.loads(ws.receive_text())
        if pred(msg):
            return msg
    raise AssertionError("message not received")


def test_ws_requires_token(client):
    with pytest.raises(WebSocketDisconnect) as e:
        with client.websocket_connect("/ws?token=bad") as ws:
            ws.receive_text()
    assert e.value.code == 4401


def test_ws_streams_account_data(client, terminal):
    r = client.post("/api/auth/setup", json={"username": "admin", "password": "Sup3r-secret-pw"})
    token = r.json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    aid = client.post("/api/accounts", headers=h, json=ACC).json()["id"]
    client.put(f"/api/accounts/{aid}/watchlist", headers=h, json={"symbols": ["EURUSD"]})
    assert client.post(f"/api/accounts/{aid}/connect", headers=h).status_code == 200
    with client.websocket_connect(f"/ws?token={token}") as ws:
        assert json.loads(ws.receive_text())["type"] == "hello"
        ws.send_text(json.dumps({"action": "subscribe", "topics": [f"account:{aid}", "invalid topic!"]}))
        st = recv_until(ws, lambda m: m["type"] == "status")
        assert st["data"]["status"] == "connected"
        ticks = recv_until(ws, lambda m: m["type"] == "ticks")
        assert ticks["data"]["EURUSD"]["bid"] > 0
        client.post(f"/api/accounts/{aid}/orders/market", headers=h, json={"symbol": "EURUSD", "side": "buy", "volume": 0.1})
        snap = recv_until(ws, lambda m: m["type"] == "snapshot" and m["data"]["positions"])
        assert snap["data"]["positions"][0]["symbol"] == "EURUSD"
        assert snap["data"]["account"]["login"] == 5000001
    client.post(f"/api/accounts/{aid}/disconnect", headers=h)
