"""Asynchronous gateways used by the backend to reach a MetaTrader 5 terminal."""
from __future__ import annotations

import asyncio
import importlib.util
import itertools
import multiprocessing as mp
from typing import Any

import httpx

from .client import MT5Error, MT5Unavailable

BRIDGE_PROTOCOL_VERSION = 1


class Gateway:
    kind = "base"

    async def start(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    async def call(self, method: str, **params: Any) -> Any:  # pragma: no cover - interface
        raise NotImplementedError

    async def close(self) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    @property
    def alive(self) -> bool:  # pragma: no cover - interface
        return True


class ProcessGateway(Gateway):
    """Runs :class:`MT5Client` in a dedicated child process (one terminal per process)."""

    kind = "local"

    def __init__(self, timeout_s: float = 30.0):
        self.timeout_s = timeout_s
        self._proc: mp.Process | None = None
        self._conn = None
        self._lock = asyncio.Lock()
        self._ids = itertools.count(1)

    @staticmethod
    def package_available() -> bool:
        return importlib.util.find_spec("MetaTrader5") is not None

    async def start(self) -> None:
        if not self.package_available():
            from .client import load_mt5_module

            load_mt5_module()  # raises MT5Unavailable with a detailed message
        from .worker import worker_main

        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        proc = ctx.Process(target=worker_main, args=(child,), daemon=True, name="mt5-worker")
        proc.start()
        child.close()
        self._proc, self._conn = proc, parent
        ready = await asyncio.to_thread(parent.poll, 60)
        if not ready:
            await self.close()
            raise MT5Error("MT5-воркер не запустился за 60 секунд")
        tag, payload = await asyncio.to_thread(parent.recv)
        if tag == "init_error":
            await self.close()
            raise MT5Unavailable(payload)

    def _roundtrip(self, method: str, params: dict) -> Any:
        if self._conn is None or self._proc is None or not self._proc.is_alive():
            raise MT5Error("MT5-воркер не запущен")
        req_id = next(self._ids)
        self._conn.send((req_id, method, params))
        if not self._conn.poll(self.timeout_s):
            self._proc.kill()
            raise MT5Error(f"Таймаут {self.timeout_s}s при вызове {method}; воркер перезапущен")
        rid, ok, payload, code = self._conn.recv()
        if rid != req_id:
            raise MT5Error("Нарушен протокол MT5-воркера")
        if not ok:
            raise MT5Error(payload, code)
        return payload

    async def call(self, method: str, **params: Any) -> Any:
        async with self._lock:
            try:
                return await asyncio.to_thread(self._roundtrip, method, params)
            except (EOFError, BrokenPipeError, OSError) as exc:
                raise MT5Error(f"MT5-воркер аварийно завершился: {exc}") from exc

    @property
    def alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    async def close(self) -> None:
        proc, conn = self._proc, self._conn
        self._proc = self._conn = None
        if conn is not None:
            try:
                conn.send(None)
            except Exception:  # noqa: BLE001
                pass
        if proc is not None:
            await asyncio.to_thread(proc.join, 5)
            if proc.is_alive():
                proc.kill()
                await asyncio.to_thread(proc.join, 2)
        if conn is not None:
            conn.close()


class BridgeGateway(Gateway):
    """HTTP(S) client of the MT5 bridge agent (``python -m app.mt5.bridge_server``)."""

    kind = "bridge"

    def __init__(self, url: str, token: str, timeout_s: float = 30.0, transport: httpx.AsyncBaseTransport | None = None):
        if not url:
            raise MT5Error("Не указан URL MT5-моста")
        if not token:
            raise MT5Error("Не указан токен MT5-моста")
        self.url = url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self.url, timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
                                         transport=transport,
                                         headers={"Authorization": f"Bearer {token}"})
        self._alive = False
        self.info: dict = {}

    async def _request(self, method: str, path: str, **kw) -> dict:
        try:
            r = await self._client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            self._alive = False
            detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            raise MT5Error(f"MT5-мост {self.url} недоступен ({detail}). Проверьте, что агент запущен и порт доступен "
                           f"с этого сервера.") from exc
        if r.status_code == 401:
            raise MT5Error("MT5-мост отклонил токен (401)")
        if r.status_code >= 400:
            raise MT5Error(f"MT5-мост вернул HTTP {r.status_code}: {r.text[:300]}")
        return r.json()

    async def start(self) -> None:
        info = await self._request("GET", "/health")
        if info.get("protocol") != BRIDGE_PROTOCOL_VERSION:
            raise MT5Error(f"Несовместимая версия протокола MT5-моста: {info.get('protocol')}")
        if not info.get("mt5_package"):
            raise MT5Unavailable(f"На машине моста не установлен пакет MetaTrader5: {info.get('error')}")
        self.info = info
        self._alive = True

    async def call(self, method: str, **params: Any) -> Any:
        data = await self._request("POST", "/rpc", json={"method": method, "params": params})
        self._alive = True
        if not data.get("ok"):
            raise MT5Error(data.get("error") or "Ошибка MT5-моста", data.get("code"))
        return data.get("result")

    @property
    def alive(self) -> bool:
        return self._alive

    async def close(self) -> None:
        if self._alive:
            try:
                await self.call("disconnect")
            except MT5Error:
                pass
        await self._client.aclose()
        self._alive = False
