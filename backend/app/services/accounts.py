"""Runtime management of broker account connections + live market/account streaming."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..config import get_settings
from ..db import session_scope
from ..models import BrokerAccount, Bot, Watchlist
from ..mt5.client import MT5Error, MT5Unavailable
from ..mt5.gateway import BridgeGateway, Gateway, ProcessGateway
from ..security import decrypt_secret
from .hub import hub

log = logging.getLogger("ato.accounts")


class AccountNotConnected(MT5Error):
    pass


class TradingForbidden(MT5Error):
    pass


@dataclass
class AccountRuntime:
    account_id: int
    status: str = "disconnected"  # disconnected | connecting | connected | error
    error: str | None = None
    unavailable: bool = False  # MT5 package / terminal not available at all
    gateway: Gateway | None = None
    account: dict | None = None
    terminal: dict | None = None
    positions: list[dict] = field(default_factory=list)
    orders: list[dict] = field(default_factory=list)
    ticks: dict[str, Any] = field(default_factory=dict)
    version: dict | None = None
    server_offset_s: int | None = None
    connected_at: float | None = None
    last_update: float | None = None
    desired: bool = False
    task: asyncio.Task | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def public(self) -> dict:
        return {
            "account_id": self.account_id, "status": self.status, "error": self.error,
            "unavailable": self.unavailable, "account": self.account, "terminal": self.terminal,
            "version": self.version, "server_offset_s": self.server_offset_s,
            "connected_at": self.connected_at, "last_update": self.last_update,
            "positions_count": len(self.positions), "orders_count": len(self.orders),
        }


def make_gateway(acc: BrokerAccount) -> Gateway:
    s = get_settings()
    if acc.connection_type == "local":
        return ProcessGateway(timeout_s=s.mt5_call_timeout_s)
    if acc.connection_type == "bridge":
        return BridgeGateway(acc.bridge_url or "", decrypt_secret(acc.bridge_token_enc) or "", timeout_s=s.mt5_call_timeout_s)
    raise MT5Error(f"Неизвестный тип подключения {acc.connection_type}")


class AccountManager:
    def __init__(self) -> None:
        self.runtimes: dict[int, AccountRuntime] = {}
        self._watchdog: asyncio.Task | None = None
        self._symbols_cache: dict[int, tuple[float, list[str]]] = {}
        self.gateway_factory = make_gateway

    def runtime(self, account_id: int) -> AccountRuntime:
        rt = self.runtimes.get(account_id)
        if rt is None:
            rt = self.runtimes[account_id] = AccountRuntime(account_id)
        return rt

    async def _publish_status(self, rt: AccountRuntime) -> None:
        await hub.publish(f"account:{rt.account_id}", "status", rt.public())
        await hub.publish("accounts", "status", rt.public())

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        with session_scope() as s:
            ids = [a.id for a in s.scalars(select(BrokerAccount).where(BrokerAccount.auto_connect.is_(True)))]
        for aid in ids:
            asyncio.create_task(self._safe_connect(aid))
        self._watchdog = asyncio.create_task(self._watchdog_loop())

    async def _safe_connect(self, account_id: int) -> None:
        with contextlib.suppress(Exception):
            await self.connect(account_id, auto=True)

    async def shutdown(self) -> None:
        if self._watchdog:
            self._watchdog.cancel()
        for aid in list(self.runtimes):
            with contextlib.suppress(Exception):
                await self.disconnect(aid, keep_desired=True)

    async def _watchdog_loop(self) -> None:
        interval = get_settings().reconnect_interval_s
        while True:
            await asyncio.sleep(interval)
            for rt in list(self.runtimes.values()):
                if rt.desired and rt.status == "error" and not rt.unavailable and not rt.lock.locked():
                    log.info("Reconnecting account %s", rt.account_id)
                    await self._safe_connect(rt.account_id)

    # ------------------------------------------------------------------ connect / disconnect
    async def connect(self, account_id: int, auto: bool = False) -> AccountRuntime:
        """Connect an account. ``auto`` connections (startup / watchdog) keep being retried on failure;
        a manual connection that never succeeded is not retried in the background."""
        rt = self.runtime(account_id)
        async with rt.lock:
            rt.desired = True
            await self._teardown(rt)
            with session_scope() as s:
                acc = s.get(BrokerAccount, account_id)
                if acc is None:
                    raise MT5Error(f"Счёт {account_id} не найден")
                s.expunge(acc)
            rt.status, rt.error, rt.unavailable = "connecting", None, False
            await self._publish_status(rt)
            gw: Gateway | None = None
            try:
                gw = self.gateway_factory(acc)
                await gw.start()
                status = await gw.call("connect", login=acc.login, password=decrypt_secret(acc.password_enc),
                                       server=acc.server, path=acc.terminal_path or None)
            except MT5Error as exc:
                if gw is not None:
                    with contextlib.suppress(Exception):
                        await gw.close()
                rt.status, rt.error = "error", str(exc)
                rt.unavailable = isinstance(exc, MT5Unavailable)
                if not auto and rt.connected_at is None:
                    rt.desired = False
                await self._publish_status(rt)
                raise
            rt.gateway = gw
            rt.account, rt.terminal = status["account"], status["terminal"]
            rt.version, rt.server_offset_s = status.get("version"), status.get("server_offset_s")
            rt.status, rt.connected_at, rt.last_update = "connected", time.time(), time.time()
            with session_scope() as s:
                row = s.get(BrokerAccount, account_id)
                if row is not None:
                    row.trade_mode = rt.account.get("trade_mode")
                    row.currency = rt.account.get("currency")
                    row.company = rt.account.get("company")
                    row.last_connected_at = datetime.now(timezone.utc)
            rt.task = asyncio.create_task(self._stream_loop(rt), name=f"stream-{account_id}")
            await self._publish_status(rt)
            return rt

    async def _teardown(self, rt: AccountRuntime) -> None:
        if rt.task:
            rt.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await rt.task
            rt.task = None
        if rt.gateway:
            with contextlib.suppress(Exception):
                await rt.gateway.close()
            rt.gateway = None

    async def disconnect(self, account_id: int, keep_desired: bool = False) -> AccountRuntime:
        rt = self.runtime(account_id)
        async with rt.lock:
            rt.desired = keep_desired and rt.desired
            await self._teardown(rt)
            rt.status, rt.error = "disconnected", None
            rt.positions, rt.orders, rt.ticks = [], [], {}
            await self._publish_status(rt)
        return rt

    async def remove(self, account_id: int) -> None:
        await self.disconnect(account_id)
        self.runtimes.pop(account_id, None)

    # ------------------------------------------------------------------ calls
    async def call(self, account_id: int, method: str, **params: Any) -> Any:
        rt = self.runtimes.get(account_id)
        if rt is None or rt.status != "connected" or rt.gateway is None:
            raise AccountNotConnected(f"Счёт {account_id} не подключён к MT5")
        try:
            return await rt.gateway.call(method, **params)
        except MT5Error:
            if not rt.gateway.alive:
                await self._mark_error(rt, "Соединение с MT5 потеряно")
            raise

    async def _mark_error(self, rt: AccountRuntime, msg: str) -> None:
        if rt.status != "error":
            rt.status, rt.error = "error", msg
            await self._publish_status(rt)

    def ensure_trading_allowed(self, account_id: int) -> None:
        rt = self.runtimes.get(account_id)
        if rt is None or rt.status != "connected":
            raise AccountNotConnected(f"Счёт {account_id} не подключён к MT5")
        mode = (rt.account or {}).get("trade_mode")
        if mode == 2 and not get_settings().allow_real_trading:
            raise TradingForbidden(
                "Это РЕАЛЬНЫЙ счёт. Торговля на реальных счетах отключена (ATO_ALLOW_REAL_TRADING=false).")

    # ------------------------------------------------------------------ streaming
    def _stream_symbols(self, account_id: int) -> list[str]:
        cached = self._symbols_cache.get(account_id)
        if cached and time.time() - cached[0] < 5:
            return cached[1]
        syms: set[str] = set()
        with session_scope() as s:
            for wl in s.scalars(select(Watchlist).where(Watchlist.account_id == account_id)):
                syms.update(wl.symbols or [])
            for b in s.scalars(select(Bot).where(Bot.account_id == account_id)):
                syms.add(b.symbol)
        out = sorted(syms)
        self._symbols_cache[account_id] = (time.time(), out)
        return out

    def invalidate_symbols(self, account_id: int) -> None:
        self._symbols_cache.pop(account_id, None)

    async def _stream_loop(self, rt: AccountRuntime) -> None:
        s = get_settings()
        q_int, a_int = s.quote_interval_ms / 1000, s.account_interval_ms / 1000
        last_acc = 0.0
        fails = 0
        topic = f"account:{rt.account_id}"
        while True:
            try:
                symbols = await asyncio.to_thread(self._stream_symbols, rt.account_id)
                if symbols:
                    rt.ticks = await rt.gateway.call("ticks", symbols=symbols)
                    if hub.has_subscribers(topic):
                        await hub.publish(topic, "ticks", rt.ticks)
                if time.time() - last_acc >= a_int:
                    st = await rt.gateway.call("status")
                    rt.account, rt.terminal = st["account"], st["terminal"]
                    rt.server_offset_s = st.get("server_offset_s", rt.server_offset_s)
                    rt.positions = await rt.gateway.call("positions")
                    rt.orders = await rt.gateway.call("orders")
                    rt.last_update = last_acc = time.time()
                    await hub.publish(topic, "snapshot", {"account": rt.account, "terminal": rt.terminal,
                                                          "positions": rt.positions, "orders": rt.orders})
                    await hub.publish("accounts", "status", rt.public())
                fails = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                fails += 1
                log.warning("stream error account=%s: %s", rt.account_id, exc)
                if fails >= 3 or (rt.gateway and not rt.gateway.alive):
                    await self._mark_error(rt, f"Потеряна связь с MT5: {exc}")
                    return
            await asyncio.sleep(q_int)


manager = AccountManager()
