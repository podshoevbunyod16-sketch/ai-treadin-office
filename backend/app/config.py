"""Application configuration (environment variables / .env file)."""
from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ATO_", extra="ignore")

    app_name: str = "AI Trading Office"
    environment: str = "development"  # development | production

    data_dir: Path = BASE_DIR / "data"
    database_url: str = ""  # default: sqlite file inside data_dir

    # Secrets. If empty they are generated once and persisted (chmod 600) inside data_dir.
    jwt_secret: str = ""
    encryption_key: str = ""  # Fernet key (urlsafe base64, 32 bytes)

    access_token_minutes: int = 12 * 60
    cors_origins: list[str] = Field(default_factory=list)

    # Safety: by default trading is only permitted on DEMO / CONTEST accounts.
    allow_real_trading: bool = False

    # Streaming intervals
    quote_interval_ms: int = 1000
    account_interval_ms: int = 2000
    reconnect_interval_s: int = 15

    mt5_call_timeout_s: float = 30.0

    frontend_dist: Path = BASE_DIR.parent / "frontend" / "dist"

    login_max_attempts: int = 10
    login_window_s: int = 300

    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{self.data_dir / 'trading_office.db'}"

    def _persisted_secret(self, filename: str, factory) -> str:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / filename
        if path.exists():
            return path.read_text().strip()
        value = factory()
        path.write_text(value)
        try:
            os.chmod(path, 0o600)
        except OSError:  # pragma: no cover - windows
            pass
        return value

    def get_jwt_secret(self) -> str:
        return self.jwt_secret or self._persisted_secret(".jwt_secret", lambda: secrets.token_urlsafe(64))

    def get_encryption_key(self) -> str:
        if self.encryption_key:
            return self.encryption_key
        from cryptography.fernet import Fernet

        return self._persisted_secret(".encryption_key", lambda: Fernet.generate_key().decode())


@lru_cache
def get_settings() -> Settings:
    return Settings()
