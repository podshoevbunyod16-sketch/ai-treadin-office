from fastapi.testclient import TestClient

from app.main import app, engine

client = TestClient(app)


def setup_function() -> None:
    engine.accounts.clear()
    engine.prices.clear()


def test_health_marks_paper_mode() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["mode"] == "paper-trading"


def test_agent_price_and_paper_order_flow() -> None:
    assert client.post("/api/agents", json={"agent_id": "demo", "allocation": 500}).status_code == 201
    assert client.post("/api/market/price", json={"symbol": "ETH-USD", "price": 50}).status_code == 200
    order = client.post("/api/agents/demo/orders", json={"symbol": "ETH-USD", "side": "buy", "quantity": 1})
    assert order.status_code == 201
    assert order.json()["mode"] == "paper"
    portfolio = client.get("/api/agents/demo/portfolio").json()
    assert portfolio["positions"]["ETH-USD"]["quantity"] == 1
