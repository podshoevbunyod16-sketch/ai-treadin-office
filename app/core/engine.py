from app.core.models import AgentAccount, PaperOrder, Position, Side
from app.core.risk import RiskConfig


class PaperTradingEngine:
    def __init__(self, starting_cash: float = 10_000.0,
                 risk: RiskConfig | None = None, fee_rate: float = 0.001) -> None:
        if starting_cash <= 0 or fee_rate < 0:
            raise ValueError("starting_cash must be positive and fee_rate non-negative")
        self.risk = risk or RiskConfig()
        self.fee_rate = fee_rate
        self.prices: dict[str, float] = {}
        self.accounts: dict[str, AgentAccount] = {}
        self.starting_cash = starting_cash

    def register_agent(self, agent_id: str, allocation: float | None = None) -> AgentAccount:
        if not agent_id or agent_id in self.accounts:
            raise ValueError("agent_id must be unique and non-empty")
        cash = self.starting_cash if allocation is None else allocation
        if cash <= 0:
            raise ValueError("allocation must be positive")
        account = AgentAccount(agent_id, cash, cash)
        self.accounts[agent_id] = account
        return account

    def update_price(self, symbol: str, price: float) -> None:
        if not symbol or price <= 0:
            raise ValueError("symbol and positive price are required")
        self.prices[symbol.upper()] = price

    def place_paper_order(self, agent_id: str, symbol: str, side: Side,
                          quantity: float) -> PaperOrder:
        account = self.accounts[agent_id]
        symbol = symbol.upper()
        if symbol not in self.prices:
            raise ValueError(f"No market price available for {symbol}")
        price = self.prices[symbol]
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if side == Side.BUY:
            self.risk.validate_order(account, symbol, quantity, price, self.prices)
            fee = quantity * price * self.fee_rate
            total = quantity * price + fee
            if total > account.cash:
                raise ValueError("insufficient virtual cash")
            old = account.positions.get(symbol, Position(symbol))
            new_quantity = old.quantity + quantity
            old.average_price = ((old.quantity * old.average_price) + total) / new_quantity
            old.quantity = new_quantity
            account.positions[symbol] = old
            account.cash -= total
        else:
            position = account.positions.get(symbol)
            if position is None or quantity > position.quantity:
                raise ValueError("insufficient position to sell")
            fee = quantity * price * self.fee_rate
            account.realized_pnl += quantity * (price - position.average_price) - fee
            position.quantity -= quantity
            account.cash += quantity * price - fee
            if position.quantity == 0:
                del account.positions[symbol]
        order = PaperOrder(agent_id, symbol, side, quantity, price, fee)
        account.orders.append(order)
        return order

    def portfolio(self, agent_id: str) -> dict[str, object]:
        account = self.accounts[agent_id]
        return {
            "agent_id": agent_id,
            "cash": round(account.cash, 8),
            "equity": round(account.equity(self.prices), 8),
            "realized_pnl": round(account.realized_pnl, 8),
            "unrealized_pnl": round(account.unrealized_pnl(self.prices), 8),
            "positions": {symbol: {"quantity": p.quantity, "average_price": p.average_price}
                          for symbol, p in account.positions.items()},
            "orders_count": len(account.orders),
        }
