from __future__ import annotations

import re
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Bot, BrokerAccount, User, Watchlist
from ..mt5.constants import ACCOUNT_TRADE_MODES, TIMEFRAMES
from ..security import encrypt_secret
from ..services.audit import audit
from ..state import accounts
from .deps import client_ip, current_user, require

router = APIRouter(prefix="/api/accounts", tags=["accounts"])

SYMBOL_RE = re.compile(r"^[A-Za-z0-9._#&+\-!@$]{1,64}$")


def _check_symbol(s: str) -> str:
    if not SYMBOL_RE.match(s):
        raise ValueError(f"Недопустимое имя символа: {s!r}")
    return s


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    connection_type: Literal["local", "bridge"]
    login: int = Field(gt=0)
    server: str = Field(min_length=1, max_length=128)
    password: str | None = Field(default=None, max_length=256)
    terminal_path: str | None = Field(default=None, max_length=512)
    bridge_url: str | None = Field(default=None, max_length=512)
    bridge_token: str | None = Field(default=None, max_length=512)
    auto_connect: bool = False

    @field_validator("bridge_url")
    @classmethod
    def url_ok(cls, v: str | None) -> str | None:
        if v and not re.match(r"^https?://[^\s/]+(:\d+)?/?$", v):
            raise ValueError("URL моста должен иметь вид http(s)://host:port")
        return v or None


class AccountPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    connection_type: Literal["local", "bridge"] | None = None
    login: int | None = Field(default=None, gt=0)
    server: str | None = Field(default=None, min_length=1, max_length=128)
    password: str | None = Field(default=None, max_length=256)
    clear_password: bool = False
    terminal_path: str | None = Field(default=None, max_length=512)
    bridge_url: str | None = Field(default=None, max_length=512)
    bridge_token: str | None = Field(default=None, max_length=512)
    auto_connect: bool | None = None

    _url = field_validator("bridge_url")(AccountIn.url_ok.__func__)


def account_out(a: BrokerAccount) -> dict:
    rt = accounts.runtimes.get(a.id)
    return {
        "id": a.id, "name": a.name, "connection_type": a.connection_type, "login": a.login, "server": a.server,
        "has_password": bool(a.password_enc), "terminal_path": a.terminal_path, "bridge_url": a.bridge_url,
        "has_bridge_token": bool(a.bridge_token_enc), "auto_connect": a.auto_connect, "trade_mode": a.trade_mode,
        "trade_mode_name": ACCOUNT_TRADE_MODES.get(a.trade_mode) if a.trade_mode is not None else None,
        "currency": a.currency, "company": a.company,
        "last_connected_at": a.last_connected_at.isoformat() if a.last_connected_at else None,
        "runtime": rt.public() if rt else {"account_id": a.id, "status": "disconnected"},
    }


def _get(db: Session, account_id: int) -> BrokerAccount:
    a = db.get(BrokerAccount, account_id)
    if a is None:
        raise HTTPException(404, "Счёт не найден")
    return a


def _validate(a: BrokerAccount) -> None:
    if a.connection_type == "bridge" and (not a.bridge_url or not a.bridge_token_enc):
        raise HTTPException(422, "Для подключения через мост укажите URL и токен моста")
    if a.connection_type == "local" and not a.password_enc and not a.terminal_path:
        # Without password we attach to an already logged-in terminal - allowed, but path helps to pick it.
        pass


@router.get("")
def list_accounts(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return [account_out(a) for a in db.scalars(select(BrokerAccount).order_by(BrokerAccount.id))]


@router.post("", status_code=201)
def create_account(body: AccountIn, request: Request, user: User = Depends(require("trader")),
                   db: Session = Depends(get_db)):
    a = BrokerAccount(name=body.name, connection_type=body.connection_type, login=body.login, server=body.server,
                      password_enc=encrypt_secret(body.password), terminal_path=body.terminal_path or None,
                      bridge_url=body.bridge_url, bridge_token_enc=encrypt_secret(body.bridge_token),
                      auto_connect=body.auto_connect)
    _validate(a)
    db.add(a)
    db.commit()
    audit(db, user, "account.create", f"account:{a.id}", details={"login": a.login, "server": a.server},
          ip=client_ip(request))
    return account_out(a)


@router.get("/{account_id}")
def get_account(account_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return account_out(_get(db, account_id))


@router.patch("/{account_id}")
def patch_account(account_id: int, body: AccountPatch, request: Request, user: User = Depends(require("trader")),
                  db: Session = Depends(get_db)):
    a = _get(db, account_id)
    data = body.model_dump(exclude_unset=True)
    for k in ("name", "connection_type", "login", "server", "terminal_path", "bridge_url", "auto_connect"):
        if k in data and data[k] is not None:
            setattr(a, k, data[k] or None if k in ("terminal_path", "bridge_url") else data[k])
    if body.password:
        a.password_enc = encrypt_secret(body.password)
    elif body.clear_password:
        a.password_enc = None
    if body.bridge_token:
        a.bridge_token_enc = encrypt_secret(body.bridge_token)
    _validate(a)
    db.commit()
    audit(db, user, "account.update", f"account:{a.id}",
          details={k: v for k, v in data.items() if k not in ("password", "bridge_token")}, ip=client_ip(request))
    return account_out(a)


@router.delete("/{account_id}")
async def delete_account(account_id: int, request: Request, user: User = Depends(require("admin")),
                         db: Session = Depends(get_db)):
    a = _get(db, account_id)
    if db.scalar(select(Bot.id).where(Bot.account_id == account_id).limit(1)):
        raise HTTPException(409, "К счёту привязаны боты — сначала удалите их")
    await accounts.remove(account_id)
    db.delete(a)
    db.commit()
    audit(db, user, "account.delete", f"account:{account_id}", ip=client_ip(request))
    return {"ok": True}


@router.post("/{account_id}/connect")
async def connect(account_id: int, request: Request, user: User = Depends(require("trader")),
                  db: Session = Depends(get_db)):
    _get(db, account_id)
    try:
        rt = await accounts.connect(account_id)
    except Exception as exc:
        audit(db, user, "account.connect", f"account:{account_id}", ok=False, details={"error": str(exc)},
              ip=client_ip(request))
        raise
    audit(db, user, "account.connect", f"account:{account_id}", ip=client_ip(request))
    return rt.public()


@router.post("/{account_id}/disconnect")
async def disconnect(account_id: int, request: Request, user: User = Depends(require("trader")),
                     db: Session = Depends(get_db)):
    _get(db, account_id)
    rt = await accounts.disconnect(account_id)
    audit(db, user, "account.disconnect", f"account:{account_id}", ip=client_ip(request))
    return rt.public()


@router.get("/{account_id}/status")
def status(account_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    _get(db, account_id)
    rt = accounts.runtime(account_id)
    return {**rt.public(), "positions": rt.positions, "orders": rt.orders, "ticks": rt.ticks}


# ---------------------------------------------------------------- watchlist
class WatchlistIn(BaseModel):
    symbols: list[str] = Field(max_length=200)

    @field_validator("symbols")
    @classmethod
    def syms(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(_check_symbol(s.strip()) for s in v if s.strip()))


@router.get("/{account_id}/watchlist")
def get_watchlist(account_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _get(db, account_id)
    wl = db.scalar(select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.account_id == account_id))
    return {"symbols": wl.symbols if wl else []}


@router.put("/{account_id}/watchlist")
def put_watchlist(account_id: int, body: WatchlistIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _get(db, account_id)
    wl = db.scalar(select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.account_id == account_id))
    if wl is None:
        wl = Watchlist(user_id=user.id, account_id=account_id, symbols=body.symbols)
        db.add(wl)
    else:
        wl.symbols = body.symbols
    db.commit()
    accounts.invalidate_symbols(account_id)
    return {"symbols": wl.symbols}


# ---------------------------------------------------------------- market data
@router.get("/{account_id}/symbols")
async def symbols(account_id: int, group: str | None = Query(default=None, max_length=200),
                  _: User = Depends(current_user)):
    return await accounts.call(account_id, "symbols", group=group)


@router.get("/{account_id}/symbols/{symbol}")
async def symbol_info(account_id: int, symbol: str, _: User = Depends(current_user)):
    _check_symbol_http(symbol)
    return await accounts.call(account_id, "symbol_info", symbol=symbol)


def _check_symbol_http(symbol: str) -> None:
    if not SYMBOL_RE.match(symbol):
        raise HTTPException(422, "Недопустимое имя символа")


@router.get("/{account_id}/ticks")
async def ticks(account_id: int, symbols: str = Query(..., max_length=4000), _: User = Depends(current_user)):
    syms = [s.strip() for s in symbols.split(",") if s.strip()]
    for s in syms:
        _check_symbol_http(s)
    return await accounts.call(account_id, "ticks", symbols=syms)


@router.get("/{account_id}/rates")
async def rates(account_id: int, symbol: str, timeframe: str = "M15", count: int = Query(300, ge=1, le=10000),
                _: User = Depends(current_user)):
    _check_symbol_http(symbol)
    if timeframe not in TIMEFRAMES:
        raise HTTPException(422, "Неизвестный таймфрейм")
    return await accounts.call(account_id, "rates", symbol=symbol, timeframe=timeframe, count=count)


@router.get("/{account_id}/book")
async def market_book(account_id: int, symbol: str, _: User = Depends(current_user)):
    _check_symbol_http(symbol)
    return await accounts.call(account_id, "market_book", symbol=symbol)


@router.get("/{account_id}/diagnostics")
async def diagnostics(account_id: int, _: User = Depends(current_user)):
    """Checklist of terminal/account settings required for trading through the MetaTrader5 Python API."""
    return await accounts.call(account_id, "diagnostics")


# ---------------------------------------------------------------- trading state
@router.get("/{account_id}/positions")
async def positions(account_id: int, symbol: str | None = None, _: User = Depends(current_user)):
    return await accounts.call(account_id, "positions", symbol=symbol)


@router.get("/{account_id}/orders")
async def orders(account_id: int, symbol: str | None = None, _: User = Depends(current_user)):
    return await accounts.call(account_id, "orders", symbol=symbol)


@router.get("/{account_id}/history/deals")
async def history_deals(account_id: int, date_from: float | None = None, date_to: float | None = None,
                        _: User = Depends(current_user)):
    date_from = date_from if date_from is not None else time.time() - 30 * 86400
    date_to = date_to if date_to is not None else time.time() + 86400
    return await accounts.call(account_id, "history_deals", date_from=date_from, date_to=date_to)


@router.get("/{account_id}/history/orders")
async def history_orders(account_id: int, date_from: float | None = None, date_to: float | None = None,
                         _: User = Depends(current_user)):
    date_from = date_from if date_from is not None else time.time() - 30 * 86400
    date_to = date_to if date_to is not None else time.time() + 86400
    return await accounts.call(account_id, "history_orders", date_from=date_from, date_to=date_to)


# ---------------------------------------------------------------- trading actions
class MarketOrderIn(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    volume: float = Field(gt=0, le=10000)
    sl: float | None = Field(default=None, ge=0)
    tp: float | None = Field(default=None, ge=0)
    deviation: int = Field(default=20, ge=0, le=10000)
    comment: str = Field(default="ato manual", max_length=31)

    _sym = field_validator("symbol")(lambda cls, v: _check_symbol(v))


class PendingOrderIn(BaseModel):
    symbol: str
    order_type: Literal["buy_limit", "sell_limit", "buy_stop", "sell_stop", "buy_stop_limit", "sell_stop_limit"]
    volume: float = Field(gt=0, le=10000)
    price: float = Field(gt=0)
    sl: float | None = Field(default=None, ge=0)
    tp: float | None = Field(default=None, ge=0)
    stoplimit: float | None = Field(default=None, ge=0)
    expiration: float | None = None
    comment: str = Field(default="ato manual", max_length=31)

    _sym = field_validator("symbol")(lambda cls, v: _check_symbol(v))


class CloseIn(BaseModel):
    volume: float | None = Field(default=None, gt=0)
    deviation: int = Field(default=20, ge=0, le=10000)


class SlTpIn(BaseModel):
    sl: float | None = Field(default=None, ge=0)
    tp: float | None = Field(default=None, ge=0)


class ModifyOrderIn(SlTpIn):
    price: float = Field(gt=0)


async def _trade(request: Request, user: User, db: Session, account_id: int, action: str, method: str, **params):
    accounts.ensure_trading_allowed(account_id)
    try:
        res = await accounts.call(account_id, method, **params)
    except Exception as exc:
        audit(db, user, action, f"account:{account_id}", ok=False, details={"params": params, "error": str(exc)},
              ip=client_ip(request))
        raise
    audit(db, user, action, f"account:{account_id}", ok=bool(res.get("ok")),
          details={"params": params, "retcode": res.get("retcode"), "retcode_text": res.get("retcode_text"),
                   "order": res.get("order"), "deal": res.get("deal")}, ip=client_ip(request))
    return res


class CalcIn(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    volume: float = Field(gt=0, le=10000)
    price: float | None = Field(default=None, gt=0)
    sl: float | None = Field(default=None, ge=0)
    tp: float | None = Field(default=None, ge=0)

    _sym = field_validator("symbol")(lambda cls, v: _check_symbol(v))


@router.post("/{account_id}/orders/calc")
async def calc_order(account_id: int, body: CalcIn, _: User = Depends(current_user)):
    """Margin and P/L at SL/TP calculated by the terminal (order_calc_margin / order_calc_profit)."""
    return await accounts.call(account_id, "calc", **body.model_dump())


@router.post("/{account_id}/orders/check")
async def check_order(account_id: int, body: MarketOrderIn, _: User = Depends(require("trader"))):
    return await accounts.call(account_id, "check_market_order", **body.model_dump())


@router.post("/{account_id}/orders/market")
async def market_order(account_id: int, body: MarketOrderIn, request: Request, user: User = Depends(require("trader")),
                       db: Session = Depends(get_db)):
    return await _trade(request, user, db, account_id, "trade.market", "market_order", magic=0, **body.model_dump())


@router.post("/{account_id}/orders/pending")
async def pending_order(account_id: int, body: PendingOrderIn, request: Request,
                        user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    return await _trade(request, user, db, account_id, "trade.pending", "pending_order", magic=0, **body.model_dump())


@router.patch("/{account_id}/orders/{ticket}")
async def modify_order(account_id: int, ticket: int, body: ModifyOrderIn, request: Request,
                       user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    return await _trade(request, user, db, account_id, "trade.modify_order", "modify_order", ticket=ticket,
                        **body.model_dump())


@router.delete("/{account_id}/orders/{ticket}")
async def cancel_order(account_id: int, ticket: int, request: Request, user: User = Depends(require("trader")),
                       db: Session = Depends(get_db)):
    return await _trade(request, user, db, account_id, "trade.cancel_order", "cancel_order", ticket=ticket)


@router.post("/{account_id}/positions/{ticket}/close")
async def close_position(account_id: int, ticket: int, request: Request, body: CloseIn | None = None,
                         user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    body = body or CloseIn()
    return await _trade(request, user, db, account_id, "trade.close", "close_position", ticket=ticket,
                        volume=body.volume, deviation=body.deviation, comment="ato manual close")


@router.patch("/{account_id}/positions/{ticket}")
async def modify_position(account_id: int, ticket: int, body: SlTpIn, request: Request,
                          user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    return await _trade(request, user, db, account_id, "trade.modify_position", "modify_position", ticket=ticket,
                        **body.model_dump())


@router.post("/{account_id}/positions/close-all")
async def close_all(account_id: int, request: Request, user: User = Depends(require("trader")),
                    db: Session = Depends(get_db)):
    accounts.ensure_trading_allowed(account_id)
    results = []
    for p in await accounts.call(account_id, "positions"):
        results.append(await _trade(request, user, db, account_id, "trade.close", "close_position",
                                    ticket=p["ticket"], deviation=50, comment="ato close all"))
    return {"closed": sum(1 for r in results if r.get("ok")), "results": results}
