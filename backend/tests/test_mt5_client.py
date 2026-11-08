import pytest

from app.mt5.client import MT5Client, MT5Error

L, P, S = 5000001, "demo-pass-1", "TestBroker-Demo"


@pytest.fixture
def client(terminal):
    c = MT5Client(terminal)
    c.connect(login=L, password=P, server=S)
    return c


def test_connect_and_status(terminal):
    c = MT5Client(terminal)
    st = c.connect(login=L, password=P, server=S)
    assert st["account"]["login"] == L
    assert st["account"]["trade_mode_name"] == "demo"
    assert st["terminal"]["connected"] is True


def test_connect_wrong_password(terminal):
    with pytest.raises(MT5Error) as e:
        MT5Client(terminal).connect(login=L, password="bad", server=S)
    assert "Authorization failed" in str(e.value) and e.value.code == -6


def test_connect_missing_terminal(terminal):
    with pytest.raises(MT5Error, match="not found"):
        MT5Client(terminal).connect(login=L, password=P, server=S, path="C:/missing/terminal64.exe")


def test_calls_require_connection(terminal):
    with pytest.raises(MT5Error, match="Нет подключения"):
        MT5Client(terminal).positions()


def test_market_data(client):
    syms = client.symbols()
    assert {s["name"] for s in syms} == {"EURUSD", "XAUUSD"}
    t = client.ticks(["EURUSD", "NOPE"])
    assert t["NOPE"] is None
    assert t["EURUSD"]["ask"] > t["EURUSD"]["bid"] and t["EURUSD"]["spread_points"] == 10
    rates = client.rates("EURUSD", "M15", 50)
    assert len(rates) == 50 and set(rates[0]) >= {"time", "open", "high", "low", "close", "tick_volume"}
    assert rates[1]["time"] - rates[0]["time"] == 900
    with pytest.raises(MT5Error):
        client.rates("EURUSD", "M7", 10)


def test_market_order_open_modify_close(client, terminal):
    r = client.market_order("EURUSD", "buy", 0.1, magic=42, comment="test")
    assert r["ok"] and r["retcode"] == 10009 and r["deal"] > 0
    assert terminal.sent_requests[-1]["type_filling"] == 1  # IOC chosen from symbol filling_mode
    pos = client.positions(magic=42)
    assert len(pos) == 1 and pos[0]["side"] == "buy" and pos[0]["volume"] == 0.1
    assert client.positions(magic=7) == []
    m = client.modify_position(pos[0]["ticket"], sl=1.0, tp=1.3)
    assert m["ok"] and client.positions()[0]["sl"] == 1.0
    c = client.close_position(pos[0]["ticket"])
    assert c["ok"] and client.positions() == []
    deals = client.history_deals(magic=42)
    assert [d["deal_entry"] for d in deals] == ["in", "out"]


def test_partial_close(client):
    client.market_order("EURUSD", "sell", 0.3)
    t = client.positions()[0]["ticket"]
    assert client.close_position(t, volume=0.1)["ok"]
    assert client.positions()[0]["volume"] == pytest.approx(0.2)


def test_filling_fallback(client, terminal):
    terminal.symbols["EURUSD"]["filling"] = 1  # broker says FOK but rejects it -> falls back
    terminal.symbols["EURUSD"]["filling"] = 1
    orig = terminal.order_send

    def reject_fok(req):
        if req.get("type_filling") == 0:
            return terminal._result(10030, req)
        return orig(req)

    terminal.order_send = reject_fok
    r = client.market_order("EURUSD", "buy", 0.01)
    assert r["ok"] and r["request"]["type_filling"] != 0


def test_volume_validation(client):
    with pytest.raises(MT5Error, match="меньше минимального"):
        client.market_order("EURUSD", "buy", 0.001)
    r = client.market_order("EURUSD", "buy", 0.014)  # normalised to step 0.01
    assert r["ok"] and r["volume"] == 0.01


def test_pending_modify_cancel(client):
    r = client.pending_order("EURUSD", "buy_limit", 0.1, price=1.05, sl=1.04, tp=1.1)
    assert r["ok"] and r["retcode"] == 10008
    orders = client.orders()
    assert orders[0]["order_type"] == "buy_limit"
    assert client.modify_order(orders[0]["ticket"], price=1.06)["ok"]
    assert client.orders()[0]["price_open"] == 1.06
    assert client.cancel_order(orders[0]["ticket"])["ok"]
    assert client.orders() == []
    with pytest.raises(MT5Error):
        client.pending_order("EURUSD", "buy", 0.1, price=1.0)


def test_order_check(client):
    r = client.check_market_order("EURUSD", "buy", 0.1)
    assert r["ok"] and r["margin"] == 100.0


def test_failed_order_reports_retcode(client):
    r = client.cancel_order(999)
    assert not r["ok"] and r["retcode"] == 10013 and r["retcode_text"] == "Неправильный запрос"
