from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.core.engine import PaperTradingEngine
from app.core.models import Side
from app.market_data.mt5_connector import MT5Connector, MT5Settings

app = FastAPI(
    title="AI Trading Office API",
    version="0.2.0",
    description="Paper-trading research platform with read-only MT5 demo market data.",
)
engine = PaperTradingEngine()
mt5 = MT5Connector(MT5Settings.from_env())


class AgentCreate(BaseModel):
    agent_id: str = Field(min_length=1, max_length=64)
    allocation: float | None = Field(default=None, gt=0)


class PriceUpdate(BaseModel):
    symbol: str = Field(min_length=1, max_length=24)
    price: float = Field(gt=0)


class OrderRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=24)
    side: Side
    quantity: float = Field(gt=0)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "mode": "paper-trading"}


@app.post("/api/agents", status_code=201)
def create_agent(payload: AgentCreate) -> dict[str, object]:
    try:
        account = engine.register_agent(payload.agent_id, payload.allocation)
        return {"agent_id": account.agent_id, "virtual_cash": account.cash}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/agents")
def list_agents() -> list[dict[str, object]]:
    return [engine.portfolio(agent_id) for agent_id in engine.accounts]


@app.post("/api/market/price")
def update_price(payload: PriceUpdate) -> dict[str, object]:
    try:
        engine.update_price(payload.symbol, payload.price)
        return {"symbol": payload.symbol.upper(), "price": payload.price, "source": "manual-paper-feed"}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/agents/{agent_id}/orders", status_code=201)
def place_order(agent_id: str, payload: OrderRequest) -> dict[str, object]:
    try:
        order = engine.place_paper_order(agent_id, payload.symbol, payload.side, payload.quantity)
        return {
            "agent_id": order.agent_id, "symbol": order.symbol, "side": order.side,
            "quantity": order.quantity, "price": order.price, "fee": order.fee, "mode": "paper",
        }
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/agents/{agent_id}/portfolio")
def get_portfolio(agent_id: str) -> dict[str, object]:
    try:
        return engine.portfolio(agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="agent not found") from exc


@app.get("/api/market/mt5/status")
def mt5_status() -> dict[str, object]:
    return mt5.status()


@app.post("/api/market/mt5/connect")
def mt5_connect() -> dict[str, object]:
    try:
        return mt5.connect()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/market/mt5/disconnect")
def mt5_disconnect() -> dict[str, str]:
    mt5.disconnect()
    return {"status": "disconnected"}


@app.get("/api/market/mt5/symbols")
def mt5_symbols() -> dict[str, object]:
    try:
        return {"symbols": mt5.symbols()}
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/market/mt5/tick/{symbol}")
def mt5_tick(symbol: str) -> dict[str, object]:
    try:
        tick = mt5.tick(symbol)
        engine.update_price(symbol, tick["last"] or tick["bid"])
        return tick
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
