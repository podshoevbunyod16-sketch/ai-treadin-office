from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="trader")  # admin | trader | viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BrokerAccount(Base):
    __tablename__ = "broker_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    # "local"  - backend runs on Windows, spawns a dedicated MT5 worker process per account
    # "bridge" - a remote MT5 bridge agent (app.mt5.bridge_server) runs next to the terminal
    connection_type: Mapped[str] = mapped_column(String(16), default="bridge")
    login: Mapped[int] = mapped_column(Integer)
    server: Mapped[str] = mapped_column(String(128))
    password_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    terminal_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    bridge_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    bridge_token_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_connect: Mapped[bool] = mapped_column(Boolean, default=False)
    # Filled from MT5 account_info after a successful connection
    trade_mode: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0 demo, 1 contest, 2 real
    currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    company: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    bots: Mapped[list["Bot"]] = relationship(back_populates="account")


class Watchlist(Base):
    __tablename__ = "watchlists"
    __table_args__ = (UniqueConstraint("user_id", "account_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    account_id: Mapped[int] = mapped_column(ForeignKey("broker_accounts.id", ondelete="CASCADE"))
    symbols: Mapped[list[str]] = mapped_column(JSON, default=list)


class Bot(Base):
    __tablename__ = "bots"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    account_id: Mapped[int] = mapped_column(ForeignKey("broker_accounts.id", ondelete="RESTRICT"))
    strategy: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(64))
    timeframe: Mapped[str] = mapped_column(String(8), default="M15")
    params: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    risk: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    # live = sends orders to MT5; signals = computes and logs signals only (no orders)
    trade_mode: Mapped[str] = mapped_column(String(16), default="live")
    magic: Mapped[int] = mapped_column(Integer, unique=True)
    desired_running: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="stopped")  # stopped|starting|running|error
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    account: Mapped[BrokerAccount] = relationship(back_populates="bots")


class BotLog(Base):
    __tablename__ = "bot_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    level: Mapped[str] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class BotOrder(Base):
    """Every trade request a bot sent to MT5 together with the broker response."""

    __tablename__ = "bot_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    bot_id: Mapped[int] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    action: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str] = mapped_column(String(64))
    side: Mapped[str | None] = mapped_column(String(8), nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    retcode: Mapped[int | None] = mapped_column(Integer, nullable=True)
    order_ticket: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deal_ticket: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
