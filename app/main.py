from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.core.engine import PaperTradingEngine
from app.core.models import Side

app = FastAPI(title="AI Trading Office API", version="0.1.0",
              description="Virtual paper-trading sandbox. No broker execution.")
engine = PaperTradingEngine()


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
        return {"agent_id": order.agent_id, "symbol": order.symbol, "side": order.side,
                "quantity": order.quantity, "price": order.price, "fee": order.fee,
                "mode": "paper"}
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
