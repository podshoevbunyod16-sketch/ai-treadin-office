from __future__ import annotations

import importlib
import os
import platform
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MT5Settings:
    enabled: bool
    environment: str
    login: int | None
    password: str | None
    server: str | None
    terminal_path: str | None

    @classmethod
    def from_env(cls) -> "MT5Settings":
        login_raw = os.getenv("MT5_LOGIN", "").strip()
        return cls(
            enabled=os.getenv("MT5_ENABLED", "false").lower() == "true",
            environment=os.getenv("MT5_ENVIRONMENT", "demo").lower(),
            login=int(login_raw) if login_raw else None,
            password=os.getenv("MT5_PASSWORD") or None,
            server=os.getenv("MT5_SERVER") or None,
            terminal_path=os.getenv("MT5_TERMINAL_PATH") or None,
        )


class MT5Connector:
    """Read-only MT5 market-data adapter. It intentionally exposes no order methods."""

    def __init__(self, settings: MT5Settings, mt5_module: Any | None = None) -> None:
        self.settings = settings
        self._mt5 = mt5_module
        self._connected = False

    def status(self) -> dict[str, object]:
        return {
            "enabled": self.settings.enabled,
            "environment": self.settings.environment,
            "configured": bool(self.settings.login and self.settings.password and self.settings.server),
            "connected": self._connected,
            "access": "read-only",
            "trading_mode": "paper",
            "server": self.settings.server,
        }

    def connect(self) -> dict[str, object]:
        if not self.settings.enabled:
            raise RuntimeError("MT5 connector is disabled; set MT5_ENABLED=true.")
        if self.settings.environment != "demo":
            raise RuntimeError("Only MT5 demo servers are supported by this connector.")
        if platform.system() != "Windows":
            raise RuntimeError(
                "The official MetaTrader5 Python package requires a Windows host with MT5 terminal installed."
            )
        if not (self.settings.login and self.settings.password and self.settings.server):
            raise RuntimeError("MT5_LOGIN, MT5_PASSWORD and MT5_SERVER must be configured.")
        mt5 = self._module()
        kwargs: dict[str, object] = {
            "login": self.settings.login,
            "password": self.settings.password,
            "server": self.settings.server,
        }
        if self.settings.terminal_path:
            kwargs["path"] = self.settings.terminal_path
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        account = mt5.account_info()
        if account is None:
            mt5.shutdown()
            raise RuntimeError(f"MT5 account_info failed: {mt5.last_error()}")
        # Refuse to proceed if the connected account is not a demo account.
        trade_mode = getattr(account, "trade_mode", None)
        demo_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0)
        if trade_mode != demo_mode:
            mt5.shutdown()
            raise RuntimeError("Connected account is not identified by MT5 as a demo account.")
        self._connected = True
        return {
            "status": "connected",
            "login": getattr(account, "login", None),
            "server": getattr(account, "server", self.settings.server),
            "currency": getattr(account, "currency", None),
            "access": "read-only",
            "trading_mode": "paper",
        }

    def disconnect(self) -> None:
        if self._mt5 is not None and self._connected:
            self._mt5.shutdown()
        self._connected = False

    def symbols(self) -> list[str]:
        mt5 = self._require_connection()
        items = mt5.symbols_get()
        if items is None:
            raise RuntimeError(f"MT5 symbols_get failed: {mt5.last_error()}")
        return [item.name for item in items]

    def tick(self, symbol: str) -> dict[str, object]:
        mt5 = self._require_connection()
        normalized = symbol.strip()
        if not normalized:
            raise ValueError("symbol is required")
        if not mt5.symbol_select(normalized, True):
            raise RuntimeError(f"MT5 symbol_select failed: {mt5.last_error()}")
        item = mt5.symbol_info_tick(normalized)
        if item is None:
            raise RuntimeError(f"MT5 symbol_info_tick failed: {mt5.last_error()}")
        return {
            "symbol": normalized,
            "bid": float(item.bid),
            "ask": float(item.ask),
            "last": float(item.last),
            "volume": float(item.volume),
            "time_msc": int(item.time_msc),
            "source": "mt5-demo-read-only",
        }

    def _module(self) -> Any:
        if self._mt5 is None:
            try:
                self._mt5 = importlib.import_module("MetaTrader5")
            except ImportError as exc:
                raise RuntimeError(
                    "MetaTrader5 package is missing. Install dependencies on Windows with MT5 terminal."
                ) from exc
        return self._mt5

    def _require_connection(self) -> Any:
        if not self._connected:
            raise RuntimeError("MT5 is not connected. Call the connect endpoint first.")
        return self._module()
