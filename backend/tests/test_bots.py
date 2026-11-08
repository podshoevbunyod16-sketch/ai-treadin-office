from app.bots.runner import BotRunner
from app.state import accounts

from .conftest import BRIDGE_TOKEN, make_admin, wait_for
from .test_api import ACC

UP_CROSS = [10, 9.8, 9.6, 9.4, 9.2, 9.0, 8.8, 8.6, 8.4, 8.2, 8.0, 10.5]
DOWN_CROSS = [8, 8.2, 8.4, 8.6, 8.8, 9.0, 9.2, 9.4, 9.6, 9.8, 10.0, 7.5]
M1 = 1


def scale(xs, base=1.1):
    return [base * x / 10 for x in xs]


async def setup(c, terminal, closes=UP_CROSS, **bot):
    h = await make_admin(c)
    aid = (await c.post("/api/accounts", headers=h, json=ACC)).json()["id"]
    assert (await c.post(f"/api/accounts/{aid}/connect", headers=h)).status_code == 200
    terminal.set_closes("EURUSD", M1, scale(closes))
    body = {"name": "Cross bot", "account_id": aid, "strategy": "sma_cross", "symbol": "EURUSD", "timeframe": "M1",
            "params": {"fast": 3, "slow": 6}, "risk": {"volume": 0.05, "sl_points": 200, "tp_points": 400}}
    body.update(bot)
    r = await c.post("/api/bots", headers=h, json=body)
    assert r.status_code == 201, r.text
    return h, aid, r.json()


async def test_strategies_catalog(app_client):
    h = await make_admin(app_client)
    cat = (await app_client.get("/api/bots/strategies", headers=h)).json()
    assert {s["key"] for s in cat["strategies"]} == {"sma_cross", "rsi_reversion", "donchian_breakout", "ml_logistic"}
    assert "M15" in cat["timeframes"] and any(p["key"] == "max_daily_loss" for p in cat["risk"])


async def test_bot_validation(app_client, use_bridge, terminal):
    h, aid, bot = await setup(app_client, terminal)
    r = await app_client.post("/api/bots", headers=h, json={"name": "x", "account_id": aid, "strategy": "nope",
                                                             "symbol": "EURUSD"})
    assert r.status_code == 422
    r = await app_client.post("/api/bots", headers=h, json={"name": "x", "account_id": aid, "strategy": "sma_cross",
                                                             "symbol": "EURUSD", "params": {"fast": 50, "slow": 10}})
    assert r.status_code == 422 and "меньше" in r.json()["detail"]
    # each bot gets a unique magic number (isolated orders in MT5)
    r2 = await app_client.post("/api/bots", headers=h, json={"name": "b2", "account_id": aid, "strategy": "rsi_reversion",
                                                              "symbol": "XAUUSD"})
    assert r2.json()["magic"] == bot["magic"] + 1


async def test_bot_live_trading_lifecycle(app_client, use_bridge, terminal):
    c = app_client
    h, aid, bot = await setup(c, terminal, risk={"volume": 0.05, "sl_points": 200, "tp_points": 400,
                                                 "close_on_stop": True})
    bid = bot["id"]
    r = await c.post(f"/api/bots/{bid}/start", headers=h)
    assert r.status_code == 200 and r.json()["status"] in ("starting", "running")
    pos = await wait_for(lambda: [p for p in terminal.positions.values() if p["magic"] == bot["magic"]])
    p = pos[0]
    assert p["type"] == 0 and p["volume"] == 0.05 and p["comment"] == f"ato#{bid}"
    assert p["sl"] > 0 and p["tp"] > p["price_open"] > p["sl"]

    assert (await c.patch(f"/api/bots/{bid}", headers=h, json={"name": "x"})).status_code == 409
    assert (await c.delete(f"/api/bots/{bid}", headers=h)).status_code == 409

    info = (await c.get(f"/api/bots/{bid}", headers=h)).json()
    assert info["status"] == "running" and info["state"]["last_signal"] == 1
    assert info["metrics"]["orders_sent"] == 1
    logs = (await c.get(f"/api/bots/{bid}/logs", headers=h)).json()
    assert {"signal", "trade"} <= {l["level"] for l in logs}
    orders = (await c.get(f"/api/bots/{bid}/orders", headers=h)).json()
    assert orders[0]["ok"] and orders[0]["retcode"] == 10009
    assert len((await c.get(f"/api/bots/{bid}/positions", headers=h)).json()) == 1

    r = await c.post(f"/api/bots/{bid}/stop", headers=h)
    assert r.json()["status"] == "stopped"
    assert not [p for p in terminal.positions.values() if p["magic"] == bot["magic"]]  # close_on_stop
    perf = (await c.get(f"/api/bots/{bid}/performance", headers=h)).json()
    assert perf["trades"] == 1 and len(perf["deals"]) == 2 and len(perf["equity_curve"]) == 1

    assert (await c.post(f"/api/bots/{bid}/reset-state", headers=h)).json()["state"] == {}
    assert (await c.delete(f"/api/bots/{bid}", headers=h)).status_code == 200


async def test_bot_reversal_and_isolation(app_client, use_bridge, terminal):
    c = app_client
    h, aid, bot = await setup(c, terminal)
    # a manual position on the same symbol must not be touched by the bot
    await c.post(f"/api/accounts/{aid}/orders/market", headers=h, json={"symbol": "EURUSD", "side": "buy", "volume": 0.01})
    runner = BotRunner(bot["id"], accounts)
    await runner.cycle()
    mine = lambda: [p for p in terminal.positions.values() if p["magic"] == bot["magic"]]  # noqa: E731
    assert [p["type"] for p in mine()] == [0]
    terminal.set_closes("EURUSD", M1, scale(DOWN_CROSS))
    runner.state.pop("last_bar_time")
    await runner.cycle()
    assert [p["type"] for p in mine()] == [1]  # long closed, short opened
    manual = [p for p in terminal.positions.values() if p["magic"] == 0]
    assert len(manual) == 1
    # same bar is not evaluated twice
    n = len(terminal.sent_requests)
    await runner.cycle()
    assert len(terminal.sent_requests) == n


async def test_signals_mode_sends_no_orders(app_client, use_bridge, terminal):
    c = app_client
    h, aid, bot = await setup(c, terminal, trade_mode="signals")
    runner = BotRunner(bot["id"], accounts)
    await runner.cycle()
    assert terminal.positions == {}
    logs = (await c.get(f"/api/bots/{bot['id']}/logs", headers=h)).json()
    assert any("только сигналы" in l["message"] for l in logs)


async def test_risk_manager_blocks_wide_spread(app_client, use_bridge, terminal):
    c = app_client
    h, aid, bot = await setup(c, terminal, risk={"volume": 0.01, "max_spread_points": 5})
    runner = BotRunner(bot["id"], accounts)
    await runner.cycle()
    assert terminal.positions == {}
    logs = (await c.get(f"/api/bots/{bot['id']}/logs", headers=h, params={"level": "warning"})).json()
    assert "спред 10 > 5" in logs[0]["message"]


async def test_bot_waits_for_disconnected_account(app_client, use_bridge, terminal):
    c = app_client
    h, aid, bot = await setup(c, terminal)
    await c.post(f"/api/accounts/{aid}/disconnect", headers=h)
    await c.post(f"/api/bots/{bot['id']}/start", headers=h)
    info = await wait_for(lambda: _metrics_waiting(c, bot["id"], h))
    assert "Ожидание подключения" in info["metrics"]["waiting_reason"]
    await c.post(f"/api/accounts/{aid}/connect", headers=h)
    await c.post(f"/api/bots/stop-all", headers=h)
    assert (await c.get(f"/api/bots/{bot['id']}", headers=h)).json()["status"] == "stopped"


async def _metrics_waiting(c, bid, h):
    b = (await c.get(f"/api/bots/{bid}", headers=h)).json()
    return b if b["metrics"] and b["metrics"]["waiting_reason"] else None


async def test_bot_stops_after_repeated_errors(app_client, use_bridge, terminal, monkeypatch):
    import app.bots.runner as runner_mod

    monkeypatch.setattr(runner_mod, "MAX_CONSECUTIVE_ERRORS", 2)
    c = app_client
    h, aid, bot = await setup(c, terminal, symbol="NOPE")
    runner = BotRunner(bot["id"], accounts)
    monkeypatch.setattr(runner, "poll_interval", lambda: 0.05)
    runner.start()
    await runner.task
    b = (await c.get(f"/api/bots/{bot['id']}", headers=h)).json()
    assert b["status"] == "error" and "не найден" in b["last_error"]


async def test_netting_account_warning_on_start(app_client, use_bridge, terminal):
    c = app_client
    terminal.margin_mode = 0
    h, aid, bot = await setup(c, terminal, trade_mode="signals")
    await c.post(f"/api/accounts/{aid}/disconnect", headers=h)
    await c.post(f"/api/accounts/{aid}/connect", headers=h)
    await c.post(f"/api/bots/{bot['id']}/start", headers=h)

    async def warned():
        logs = (await c.get(f"/api/bots/{bot['id']}/logs", headers=h, params={"level": "warning"})).json()
        return logs if any("Неттинговый счёт" in l["message"] for l in logs) else None

    assert await wait_for(warned)
    await c.post("/api/bots/stop-all", headers=h)


def test_server_day_start():
    import time

    from app.bots.runner import server_day_start

    now = time.time()
    assert abs(server_day_start(None) - (now - now % 86400)) < 2
    start = server_day_start(3 * 3600)
    assert start % 86400 == 0 and 0 <= now + 3 * 3600 - start < 86400
