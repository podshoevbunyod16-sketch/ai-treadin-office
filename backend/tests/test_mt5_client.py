import pytest

from app.mt5.client import MT5Client, MT5Error

L, P, S = 5000001, "demo-pass-1", "TestBroker-Demo"


@pytest.fixture
def client(terminal):
    c = MT5Client(terminal, sleep=lambda s: None)
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
    assert not r["ok"] and r["retcode"] == 10013 and r["retcode_text"].startswith("Неправильный запрос")


def test_connect_retries_ipc_timeout(terminal):
    terminal.init_failures = [(-10005, "IPC timeout")]
    st = MT5Client(terminal, sleep=lambda s: None).connect(login=L, password=P, server=S)
    assert st["account"]["login"] == L and st["version"]["build"] == 4000


def test_connect_error_has_hint(terminal):
    terminal.init_failures = [(-10003, "IPC initialize failed, MetaTrader 5 x64 not found")]
    with pytest.raises(MT5Error, match="terminal64.exe"):
        MT5Client(terminal, sleep=lambda s: None).connect(login=L, password=P, server=S)


def test_attach_to_logged_in_terminal_without_password(terminal):
    st = MT5Client(terminal).connect(login=L)
    assert st["account"]["login"] == L
    with pytest.raises(MT5Error, match="ожидался 123"):
        MT5Client(terminal).connect(login=123)


@pytest.mark.parametrize("attr,match", [
    ("algo_trading", "Алго-трейдинг"),
    ("acc_trade_allowed", "инвесторскому"),
    ("acc_trade_expert", "запретил автоматическую"),
])
def test_pre_trade_checks(client, terminal, attr, match):
    setattr(terminal, attr, False)
    with pytest.raises(MT5Error, match=match):
        client.market_order("EURUSD", "buy", 0.01)
    assert terminal.sent_requests == []


def test_python_api_disabled(client, terminal):
    terminal.api_disabled = True
    with pytest.raises(MT5Error, match="Python API"):
        client.pending_order("EURUSD", "buy_limit", 0.01, price=1.0)


def test_symbol_trade_modes(client, terminal):
    terminal.symbols["EURUSD"]["trade_mode"] = 1  # long only
    with pytest.raises(MT5Error, match="только покупки"):
        client.market_order("EURUSD", "sell", 0.01)
    assert client.market_order("EURUSD", "buy", 0.01)["ok"]
    terminal.symbols["EURUSD"]["trade_mode"] = 3  # close only
    with pytest.raises(MT5Error, match="только закрытие"):
        client.market_order("EURUSD", "buy", 0.01)
    assert client.close_position(client.positions()[0]["ticket"])["ok"]  # closing is still allowed
    terminal.symbols["EURUSD"]["trade_mode"] = 0
    with pytest.raises(MT5Error, match="запрещена брокером"):
        client.market_order("EURUSD", "buy", 0.01)


def test_stops_validation(client, terminal):
    t = client.ticks(["XAUUSD"])["XAUUSD"]  # stops level 50 points = 0.50
    with pytest.raises(MT5Error, match="Stop Loss .* ниже"):
        client.market_order("XAUUSD", "buy", 0.01, sl=t["bid"] - 0.2)
    with pytest.raises(MT5Error, match="Take Profit .* ниже"):
        client.market_order("XAUUSD", "sell", 0.01, tp=t["ask"] - 0.1)
    r = client.market_order("XAUUSD", "buy", 0.01, sl=t["bid"] - 5, tp=t["bid"] + 5)
    assert r["ok"]
    with pytest.raises(MT5Error, match="Stop Loss"):
        client.modify_position(client.positions()[0]["ticket"], sl=t["bid"] + 1)


def test_price_normalised_to_tick_size(client, terminal):
    r = client.market_order("XAUUSD", "buy", 0.01, sl_points=1003)  # 10.03 -> rounded to 0.05 tick size
    sl = r["request"]["sl"]
    assert abs(round(sl / 0.05) * 0.05 - sl) < 1e-9


def test_requote_is_retried(client, terminal):
    terminal.requotes = 2
    r = client.market_order("EURUSD", "buy", 0.01)
    assert r["ok"] and r["attempts"] == 3
    terminal.requotes = 5
    r = client.market_order("EURUSD", "buy", 0.01)
    assert not r["ok"] and r["retcode"] == 10004 and r["attempts"] == 3


def test_pending_price_validation(client):
    t = client.ticks(["EURUSD"])["EURUSD"]
    with pytest.raises(MT5Error, match="должна быть ниже"):
        client.pending_order("EURUSD", "buy_limit", 0.01, price=t["ask"] + 0.01)
    with pytest.raises(MT5Error, match="должна быть выше"):
        client.pending_order("EURUSD", "buy_stop", 0.01, price=t["ask"] - 0.01)
    assert client.pending_order("EURUSD", "sell_stop", 0.01, price=t["bid"] - 0.01)["ok"]


def test_close_volume_larger_than_position(client):
    client.market_order("EURUSD", "buy", 0.02)
    with pytest.raises(MT5Error, match="больше объёма позиции"):
        client.close_position(client.positions()[0]["ticket"], volume=0.05)


def test_calc_margin_and_profit(client):
    t = client.ticks(["EURUSD"])["EURUSD"]
    r = client.calc("EURUSD", "buy", 0.1, sl=round(t["ask"] - 0.001, 5), tp=round(t["ask"] + 0.002, 5))
    assert r["margin"] == pytest.approx(0.1 * 100000 * t["ask"] / 100, abs=0.01)
    assert r["profit_at_sl"] == pytest.approx(-10.0, abs=0.01)
    assert r["profit_at_tp"] == pytest.approx(20.0, abs=0.01)
    assert r["point_value"] == pytest.approx(0.1, abs=0.01) and r["currency"] == "USD"


def test_market_book(client):
    assert client.market_book("EURUSD")["available"] is False
    b = client.market_book("XAUUSD")
    assert b["available"] and len(b["items"]) == 6
    prices = [i["price"] for i in b["items"]]
    assert prices == sorted(prices, reverse=True) and b["items"][0]["type"] == "sell"
    client.disconnect()


def test_diagnostics(client, terminal):
    d = client.diagnostics()
    assert d["ready"] and {c["key"] for c in d["checks"]} >= {"algo_button", "python_api", "account_expert"}
    terminal.algo_trading = False
    d = client.diagnostics()
    assert not d["ready"]
    bad = [c for c in d["checks"] if not c["ok"] and c["level"] == "error"]
    assert bad[0]["key"] == "algo_button"


def test_server_offset_estimation(client, terminal, monkeypatch):
    import time as _t
    client.ticks(["EURUSD"])
    real = terminal.symbol_info_tick

    def shifted(sym):
        t = real(sym)
        return t._replace(time=int(_t.time()) + 3 * 3600 - 5) if t else t

    terminal.symbol_info_tick = shifted
    assert client.server_offset() == 3 * 3600
    assert client.status()["server_offset_s"] == 3 * 3600
