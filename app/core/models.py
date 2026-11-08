from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


@dataclass(slots=True)
class Position:
    symbol: str
    quantity: float = 0.0
    average_price: float = 0.0


@dataclass(slots=True)
class PaperOrder:
    agent_id: str
    symbol: str
    side: Side
    quantity: float
    price: float
    fee: float


@dataclass(slots=True)
class AgentAccount:
    agent_id: str
    cash: float
    starting_cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    realized_pnl: float = 0.0
    orders: list[PaperOrder] = field(default_factory=list)

    def equity(self, prices: dict[str, float]) -> float:
        return self.cash + sum(
            position.quantity * prices.get(symbol, position.average_price)
            for symbol, position in self.positions.items()
        )

    def unrealized_pnl(self, prices: dict[str, float]) -> float:
        return sum(
            position.quantity * (prices.get(symbol, position.average_price) - position.average_price)
            for symbol, position in self.positions.items()
        )
