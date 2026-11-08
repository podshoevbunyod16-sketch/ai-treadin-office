import pytest

from app.core.engine import PaperTradingEngine
from app.core.models import Side


def make_engine() -> PaperTradingEngine:
    engine = PaperTradingEngine(starting_cash=10_000, fee_rate=0.001)
    engine.register_agent("alpha", allocation=1_000)
    engine.update_price("BTC-USD", 100)
    return engine


def test_buy_updates_virtual_cash_and_position() -> None:
    engine = make_engine()
    order = engine.place_paper_order("alpha", "BTC-USD", Side.BUY, 2)
    portfolio = engine.portfolio("alpha")
    assert order.price == 100
    assert portfolio["cash"] == pytest.approx(799.8)
    assert portfolio["positions"]["BTC-USD"]["quantity"] == 2


def test_sell_realizes_pnl_and_removes_position() -> None:
    engine = make_engine()
    engine.place_paper_order("alpha", "BTC-USD", Side.BUY, 2)
    engine.update_price("BTC-USD", 110)
    engine.place_paper_order("alpha", "BTC-USD", Side.SELL, 2)
    portfolio = engine.portfolio("alpha")
    assert portfolio["realized_pnl"] == pytest.approx(19.58)
    assert portfolio["positions"] == {}


def test_rejects_position_over_risk_limit() -> None:
    engine = make_engine()
    with pytest.raises(ValueError, match="maximum position"):
        engine.place_paper_order("alpha", "BTC-USD", Side.BUY, 3)


def test_rejects_selling_more_than_held() -> None:
    engine = make_engine()
    with pytest.raises(ValueError, match="insufficient position"):
        engine.place_paper_order("alpha", "BTC-USD", Side.SELL, 1)


def test_agent_ids_must_be_unique() -> None:
    engine = make_engine()
    with pytest.raises(ValueError, match="unique"):
        engine.register_agent("alpha")
