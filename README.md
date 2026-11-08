# AI Trading Office

A modular **paper-trading** environment for autonomous strategy agents. It uses virtual balances only; it does not connect to brokers or place real-money orders.

## Stack
- Python 3.11+
- FastAPI + Pydantic
- Pytest

## Quick start
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```
Open `http://127.0.0.1:8000/docs` for the API.

## First iteration
- Independent virtual portfolios per agent
- Deterministic example strategy (moving-average signal)
- Simulated market ticks and paper orders
- Cash, positions, equity and realized/unrealized PnL
- Basic risk limits and unit tests

Market prices in this foundation are supplied through the API. A market-data adapter, PostgreSQL persistence, WebSockets and the 3D office UI are planned as separate modules.

## Safety boundary
This project is paper trading only. Never put broker credentials or real account tokens in this application. Simulated results are not evidence of future performance.
