from dataclasses import dataclass

from app.core.models import AgentAccount


@dataclass(frozen=True, slots=True)
class RiskConfig:
    max_position_fraction: float = 0.20
    max_drawdown_fraction: float = 0.15

    def __post_init__(self) -> None:
        if not 0 < self.max_position_fraction <= 1:
            raise ValueError("max_position_fraction must be in (0, 1]")
        if not 0 < self.max_drawdown_fraction < 1:
            raise ValueError("max_drawdown_fraction must be in (0, 1)")

    def validate_order(self, account: AgentAccount, symbol: str, quantity: float,
                       price: float, prices: dict[str, float]) -> None:
        if quantity <= 0 or price <= 0:
            raise ValueError("quantity and price must be positive")
        equity = account.equity(prices)
        if equity <= 0:
            raise ValueError("account equity must be positive")
        current = account.positions.get(symbol)
        current_value = current.quantity * price if current else 0.0
        if (current_value + quantity * price) > equity * self.max_position_fraction:
            raise ValueError("maximum position size exceeded")
        if equity < account.starting_cash * (1 - self.max_drawdown_fraction):
            raise ValueError("maximum drawdown limit reached")
