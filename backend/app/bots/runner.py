"""Bot runtime: one isolated asyncio task per bot with its own state, logs, risk limits and MT5 magic number."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import traceback
from datetime import datetime, timezone
from typing import Any

import numpy as np
from sqlalchemy import select

from ..db import session_scope
from ..models import Bot, BotLog, BotOrder
from ..mt5.client import MT5Error
from ..mt5.constants import TIMEFRAME_SECONDS
from ..services.accounts import AccountManager, AccountNotConnected, TradingForbidden
from ..services.hub import hub
from .strategies import RISK, STRATEGIES, Decision

log = logging.getLogger("ato.bots")
MAX_CONSECUTIVE_ERRORS = 10


def server_day_start(offset_s: int | None) -> float:
    """Start of the current trading day in trade-server time (the coordinate system of MT5 deal times)."""
    server_now = time.time() + (offset_s or 0)
    return server_now - server_now % 86400


def hours_allowed(hour: int, start: int, end: int) -> bool:
    if start == end or (start == 0 and end == 24):
        return True
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


class BotRunner:
    def __init__(self, bot_id: int, accounts: AccountManager):
        self.bot_id = bot_id
        self.accounts = accounts
        self.stop_event = asyncio.Event()
        self.task: asyncio.Task | None = None
        self.started = time.time()
        self.cycles = 0
        self.errors = 0
        self.consecutive_errors = 0
        self.orders_sent = 0
        self.last_cycle: float | None = None
        self.waiting_reason: str | None = None
        self._symbol_info: dict | None = None
        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> None:
        with session_scope() as s:
            b = s.get(Bot, self.bot_id)
            if b is None:
                raise ValueError(f"Бот {self.bot_id} не найден")
            self.name, self.account_id, self.symbol, self.timeframe = b.name, b.account_id, b.symbol, b.timeframe
            self.strategy = STRATEGIES[b.strategy]
            self.params = self.strategy.validate(b.params)
            self.risk = RISK.validate(b.risk)
            self.trade_mode = b.trade_mode
            self.magic = b.magic
            self.state: dict[str, Any] = dict(b.state or {})

    def _save(self, **fields: Any) -> None:
        with session_scope() as s:
            b = s.get(Bot, self.bot_id)
            if b is None:
                return
            b.state = dict(self.state)
            b.last_heartbeat = datetime.now(timezone.utc)
            for k, v in fields.items():
                setattr(b, k, v)

    async def save(self, **fields: Any) -> None:
        await asyncio.to_thread(self._save, **fields)

    async def log(self, level: str, message: str, data: dict | None = None) -> None:
        def _w() -> dict:
            with session_scope() as s:
                row = BotLog(bot_id=self.bot_id, level=level, message=message, data=data)
                s.add(row)
                s.flush()
                return {"id": row.id, "ts": row.ts.isoformat(), "level": level, "message": message, "data": data}

        entry = await asyncio.to_thread(_w)
        getattr(log, "error" if level == "error" else "info")("bot %s: %s", self.bot_id, message)
        await hub.publish(f"bot:{self.bot_id}", "log", entry)

    def metrics(self) -> dict:
        return {
            "bot_id": self.bot_id, "running": self.task is not None and not self.task.done(),
            "uptime_s": round(time.time() - self.started), "cycles": self.cycles, "errors": self.errors,
            "consecutive_errors": self.consecutive_errors, "orders_sent": self.orders_sent,
            "last_cycle": self.last_cycle, "waiting_reason": self.waiting_reason, "state": self.state,
        }

    async def publish(self, status: str | None = None) -> None:
        data = self.metrics()
        if status:
            data["status"] = status
        await hub.publish(f"bot:{self.bot_id}", "metrics", data)
        await hub.publish("bots", "metrics", data)

    # ------------------------------------------------------------------ main loop
    def start(self) -> None:
        self.task = asyncio.create_task(self._run(), name=f"bot-{self.bot_id}")

    async def stop(self) -> None:
        self.stop_event.set()
        if self.task:
            with contextlib.suppress(Exception):
                await asyncio.wait_for(asyncio.shield(self.task), timeout=30)

    def poll_interval(self) -> float:
        return float(min(max(TIMEFRAME_SECONDS.get(self.timeframe, 60) / 12, 1.0), 10.0))

    async def _run(self) -> None:
        await self.save(status="running", started_at=datetime.now(timezone.utc), last_error=None)
        await self.log("info", f"Бот запущен: {self.strategy.title}, {self.symbol} {self.timeframe}, "
                               f"режим {'торговля' if self.trade_mode == 'live' else 'только сигналы'}, magic {self.magic}")
        await self.publish("running")
        await self._environment_warnings()
        final_status, final_error = "stopped", None
        try:
            while not self.stop_event.is_set():
                try:
                    await self.cycle()
                    self.consecutive_errors = 0
                except AccountNotConnected as exc:
                    self.waiting_reason = str(exc)
                    await self.save()
                except Exception as exc:  # noqa: BLE001 - isolate the bot from any failure
                    self.errors += 1
                    self.consecutive_errors += 1
                    msg = str(exc) if isinstance(exc, MT5Error) else f"{type(exc).__name__}: {exc}"
                    await self.log("error", f"Ошибка цикла: {msg}",
                                   None if isinstance(exc, MT5Error) else {"trace": traceback.format_exc(limit=5)})
                    await self.save(last_error=msg)
                    if self.consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        final_status, final_error = "error", f"Остановлен после {MAX_CONSECUTIVE_ERRORS} ошибок подряд: {msg}"
                        break
                self.last_cycle = time.time()
                await self.publish("running")
                with contextlib.suppress(asyncio.TimeoutError):
                    await asyncio.wait_for(self.stop_event.wait(), timeout=self.poll_interval())
            if self.risk["close_on_stop"] and self.trade_mode == "live":
                with contextlib.suppress(Exception):
                    await self.close_all("остановка бота")
        finally:
            fields: dict[str, Any] = {"status": final_status}
            if final_status == "error":
                fields.update(last_error=final_error, desired_running=False)
            with contextlib.suppress(Exception):
                await self.save(**fields)
            with contextlib.suppress(Exception):
                await self.log("error" if final_error else "info", final_error or "Бот остановлен")
            await self.publish(final_status)

    async def _environment_warnings(self) -> None:
        rt = self.accounts.runtimes.get(self.account_id)
        acc = (rt.account if rt else None) or {}
        if acc.get("margin_mode") is not None and acc.get("margin_mode") != 2:
            await self.log("warning", "Неттинговый счёт: по символу существует одна общая позиция. Не запускайте "
                                      "несколько ботов и не торгуйте вручную на том же символе.")
        if rt and rt.terminal and not rt.terminal.get("trade_allowed") and self.trade_mode == "live":
            await self.log("warning", "В терминале выключена кнопка «Алго-трейдинг» — ордера будут отклонены, "
                                      "пока её не включить.")

    # ------------------------------------------------------------------ cycle
    async def call(self, method: str, **params: Any) -> Any:
        return await self.accounts.call(self.account_id, method, **params)

    async def cycle(self) -> None:
        self.cycles += 1
        rt = self.accounts.runtimes.get(self.account_id)
        if rt is None or rt.status != "connected":
            raise AccountNotConnected("Ожидание подключения счёта к MT5")
        self.waiting_reason = None
        if self._symbol_info is None:
            self._symbol_info = await self.call("symbol_info", symbol=self.symbol)
        need = self.strategy.min_bars(self.params) + 1
        rates = await self.call("rates", symbol=self.symbol, timeframe=self.timeframe, count=need + 1)
        closed = rates[:-1]  # the last bar is still forming
        if len(closed) < self.strategy.min_bars(self.params):
            self.waiting_reason = f"История MT5 содержит {len(closed)} баров, нужно {self.strategy.min_bars(self.params)}"
            await self.save()
            return
        bar_time = int(closed[-1]["time"])
        if self.state.get("last_bar_time") == bar_time:
            await self.save()
            return
        positions = await self.call("positions", symbol=self.symbol, magic=self.magic)
        exposure = self._exposure(positions)
        bars = {k: np.array([r[k] for r in closed], dtype=float) for k in ("open", "high", "low", "close", "tick_volume")}
        decision = self.strategy.evaluate(bars, self.params, exposure, self.state)
        self.state.update({
            "last_bar_time": bar_time, "last_signal": decision.target, "last_reason": decision.reason,
            "last_values": decision.values, "exposure": exposure, "evaluated_at": time.time(),
        })
        if decision.target is not None:
            await self.log("signal", f"Сигнал {self._name(decision.target)}: {decision.reason}",
                           {"bar_time": bar_time, "values": decision.values, "exposure": exposure})
            if decision.target != exposure:
                await self.execute(decision, positions)
        await self.save()

    @staticmethod
    def _exposure(positions: list[dict]) -> int:
        buys = sum(1 for p in positions if p["side"] == "buy")
        sells = sum(1 for p in positions if p["side"] == "sell")
        return 1 if buys > sells else (-1 if sells > buys else 0)

    @staticmethod
    def _name(target: int | None) -> str:
        return {1: "ЛОНГ", -1: "ШОРТ", 0: "ВНЕ РЫНКА", None: "—"}[target]

    async def execute(self, d: Decision, positions: list[dict]) -> None:
        if self.trade_mode != "live":
            await self.log("info", "Режим «только сигналы»: ордер в MT5 не отправлялся")
            return
        try:
            self.accounts.ensure_trading_allowed(self.account_id)
        except TradingForbidden as exc:
            await self.log("warning", str(exc))
            return
        opposite = "sell" if d.target == 1 else ("buy" if d.target == -1 else None)
        for p in positions:
            if d.target == 0 or p["side"] == opposite:
                await self.order("close", lambda p=p: self.call("close_position", ticket=p["ticket"],
                                 deviation=self.risk["deviation_points"], comment=f"ato#{self.bot_id} close"),
                                 symbol=self.symbol, side=p["side"], volume=p["volume"])
        if d.target == 0:
            return
        side = "buy" if d.target == 1 else "sell"
        same = [p for p in positions if p["side"] == side]
        if same:
            return
        reason = await self.risk_block(side)
        if reason:
            await self.log("warning", f"Вход {side} заблокирован риск-менеджером: {reason}")
            return
        await self.order("open", lambda: self.call(
            "market_order", symbol=self.symbol, side=side, volume=self.risk["volume"],
            sl_points=self.risk["sl_points"] or None, tp_points=self.risk["tp_points"] or None,
            deviation=self.risk["deviation_points"], magic=self.magic, comment=f"ato#{self.bot_id}"),
            symbol=self.symbol, side=side, volume=self.risk["volume"])

    async def risk_block(self, side: str) -> str | None:
        now = datetime.now(timezone.utc)
        if not hours_allowed(now.hour, self.risk["hours_from"], self.risk["hours_to"]):
            return f"вне торговых часов {self.risk['hours_from']}-{self.risk['hours_to']} UTC"
        all_pos = await self.call("positions", magic=self.magic)
        if len(all_pos) >= self.risk["max_positions"]:
            return f"достигнут лимит позиций ({self.risk['max_positions']})"
        if self.risk["max_spread_points"]:
            ticks = await self.call("ticks", symbols=[self.symbol])
            t = ticks.get(self.symbol)
            if not t:
                return "нет котировки"
            if t.get("spread_points") is not None and t["spread_points"] > self.risk["max_spread_points"]:
                return f"спред {t['spread_points']} > {self.risk['max_spread_points']} пунктов"
        if self.risk["max_daily_loss"]:
            pnl = await self.daily_pnl(all_pos)
            if pnl <= -abs(self.risk["max_daily_loss"]):
                return f"дневной убыток {pnl:.2f} превысил лимит {self.risk['max_daily_loss']}"
        return None

    async def daily_pnl(self, positions: list[dict] | None = None) -> float:
        rt = self.accounts.runtimes.get(self.account_id)
        deals = await self.call("history_deals", date_from=server_day_start(rt.server_offset_s if rt else None),
                                date_to=time.time() + 86400, magic=self.magic)
        realized = sum(d["profit"] + d.get("commission", 0) + d.get("swap", 0) + d.get("fee", 0) for d in deals)
        if positions is None:
            positions = await self.call("positions", magic=self.magic)
        return float(realized + sum(p["profit"] + p.get("swap", 0) for p in positions))

    async def order(self, action: str, fn, symbol: str, side: str | None, volume: float | None) -> dict:
        try:
            res = await fn()
        except MT5Error as exc:
            res = {"ok": False, "retcode": exc.code, "retcode_text": str(exc)}
        self.orders_sent += 1

        def _w() -> None:
            with session_scope() as s:
                s.add(BotOrder(bot_id=self.bot_id, action=action, symbol=symbol, side=side, volume=volume,
                               price=res.get("price"), ok=bool(res.get("ok")), retcode=res.get("retcode"),
                               order_ticket=res.get("order"), deal_ticket=res.get("deal"),
                               comment=res.get("retcode_text") or res.get("comment"), response=res))

        await asyncio.to_thread(_w)
        lvl = "trade" if res.get("ok") else "error"
        await self.log(lvl, f"{'Открытие' if action == 'open' else 'Закрытие'} {side} {volume} {symbol}: "
                            f"{res.get('retcode_text')} (retcode {res.get('retcode')}, ордер {res.get('order')}, "
                            f"сделка {res.get('deal')}, цена {res.get('price')})", {"response": res})
        return res

    async def close_all(self, why: str) -> None:
        for p in await self.call("positions", magic=self.magic):
            await self.order("close", lambda p=p: self.call("close_position", ticket=p["ticket"],
                             deviation=self.risk["deviation_points"], comment=f"ato#{self.bot_id} stop"),
                             symbol=p["symbol"], side=p["side"], volume=p["volume"])
        await self.log("info", f"Все позиции бота закрыты ({why})")


class BotManager:
    def __init__(self, accounts: AccountManager):
        self.accounts = accounts
        self.runners: dict[int, BotRunner] = {}

    def is_running(self, bot_id: int) -> bool:
        r = self.runners.get(bot_id)
        return r is not None and r.task is not None and not r.task.done()

    async def start(self, bot_id: int) -> BotRunner:
        if self.is_running(bot_id):
            return self.runners[bot_id]
        runner = BotRunner(bot_id, self.accounts)
        await asyncio.to_thread(self._set_desired, bot_id, True)
        self.runners[bot_id] = runner
        runner.start()
        return runner

    @staticmethod
    def _set_desired(bot_id: int, value: bool) -> None:
        with session_scope() as s:
            b = s.get(Bot, bot_id)
            if b:
                b.desired_running = value
                if value:
                    b.status = "starting"

    async def stop(self, bot_id: int) -> None:
        await asyncio.to_thread(self._set_desired, bot_id, False)
        r = self.runners.pop(bot_id, None)
        if r:
            await r.stop()

    async def stop_all(self, persist: bool = True) -> list[int]:
        ids = list(self.runners)
        for bid in ids:
            if persist:
                await self.stop(bid)
            else:
                r = self.runners.pop(bid)
                await r.stop()
        return ids

    async def restore(self) -> None:
        with session_scope() as s:
            ids = [b.id for b in s.scalars(select(Bot).where(Bot.desired_running.is_(True)))]
        for bid in ids:
            with contextlib.suppress(Exception):
                await self.start(bid)

    def metrics(self, bot_id: int) -> dict | None:
        r = self.runners.get(bot_id)
        return r.metrics() if r else None
