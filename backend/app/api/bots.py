from __future__ import annotations

import re
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..bots.strategies import RISK, STRATEGIES
from ..db import get_db
from ..models import Bot, BotLog, BotOrder, BrokerAccount, User
from ..mt5.constants import TIMEFRAMES
from ..services.audit import audit
from ..state import accounts, bots
from .deps import client_ip, current_user, require

router = APIRouter(prefix="/api/bots", tags=["bots"])
SYMBOL_RE = re.compile(r"^[A-Za-z0-9._#&+\-!@$]{1,64}$")
MAGIC_BASE = 7_310_000


class BotIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    account_id: int
    strategy: str
    symbol: str = Field(pattern=SYMBOL_RE.pattern)
    timeframe: str = "M15"
    params: dict = Field(default_factory=dict)
    risk: dict = Field(default_factory=dict)
    trade_mode: Literal["live", "signals"] = "live"


class BotPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    account_id: int | None = None
    strategy: str | None = None
    symbol: str | None = Field(default=None, pattern=SYMBOL_RE.pattern)
    timeframe: str | None = None
    params: dict | None = None
    risk: dict | None = None
    trade_mode: Literal["live", "signals"] | None = None


def bot_out(b: Bot) -> dict:
    return {
        "id": b.id, "name": b.name, "account_id": b.account_id, "strategy": b.strategy,
        "strategy_title": STRATEGIES[b.strategy].title if b.strategy in STRATEGIES else b.strategy,
        "symbol": b.symbol, "timeframe": b.timeframe, "params": b.params, "risk": b.risk, "trade_mode": b.trade_mode,
        "magic": b.magic, "status": b.status if bots.is_running(b.id) or b.status == "error" else "stopped",
        "desired_running": b.desired_running, "state": b.state, "last_error": b.last_error,
        "last_heartbeat": b.last_heartbeat.isoformat() if b.last_heartbeat else None,
        "started_at": b.started_at.isoformat() if b.started_at else None,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "metrics": bots.metrics(b.id),
    }


def _get(db: Session, bot_id: int) -> Bot:
    b = db.get(Bot, bot_id)
    if b is None:
        raise HTTPException(404, "Бот не найден")
    return b


def _validated(db: Session, strategy: str, timeframe: str, params: dict, risk: dict, account_id: int) -> tuple[dict, dict]:
    if strategy not in STRATEGIES:
        raise HTTPException(422, f"Неизвестная стратегия {strategy}")
    if timeframe not in TIMEFRAMES:
        raise HTTPException(422, f"Неизвестный таймфрейм {timeframe}")
    if db.get(BrokerAccount, account_id) is None:
        raise HTTPException(422, "Счёт не найден")
    try:
        return STRATEGIES[strategy].validate(params), RISK.validate(risk)
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/strategies")
def strategies(_: User = Depends(current_user)):
    return {"strategies": [s.describe() for s in STRATEGIES.values()], "risk": [p.as_dict() for p in RISK.params],
            "timeframes": list(TIMEFRAMES)}


@router.get("")
def list_bots(_: User = Depends(current_user), db: Session = Depends(get_db)):
    return [bot_out(b) for b in db.scalars(select(Bot).order_by(Bot.id))]


@router.post("", status_code=201)
def create_bot(body: BotIn, request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    params, risk = _validated(db, body.strategy, body.timeframe, body.params, body.risk, body.account_id)
    magic = (db.scalar(select(func.max(Bot.magic))) or MAGIC_BASE) + 1
    b = Bot(name=body.name, account_id=body.account_id, strategy=body.strategy, symbol=body.symbol,
            timeframe=body.timeframe, params=params, risk=risk, trade_mode=body.trade_mode, magic=magic,
            created_by=user.id, state={})
    db.add(b)
    db.commit()
    accounts.invalidate_symbols(b.account_id)
    audit(db, user, "bot.create", f"bot:{b.id}", details={"strategy": b.strategy, "symbol": b.symbol},
          ip=client_ip(request))
    return bot_out(b)


@router.post("/stop-all")
async def stop_all(request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    ids = await bots.stop_all()
    audit(db, user, "bot.stop_all", None, details={"bots": ids}, ip=client_ip(request))
    return {"stopped": ids}


@router.get("/{bot_id}")
def get_bot(bot_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    return bot_out(_get(db, bot_id))


@router.patch("/{bot_id}")
def patch_bot(bot_id: int, body: BotPatch, request: Request, user: User = Depends(require("trader")),
              db: Session = Depends(get_db)):
    b = _get(db, bot_id)
    if bots.is_running(bot_id):
        raise HTTPException(409, "Остановите бота перед изменением настроек")
    data = body.model_dump(exclude_unset=True)
    strategy = data.get("strategy") or b.strategy
    params = data.get("params") if data.get("params") is not None else (b.params if strategy == b.strategy else {})
    params, risk = _validated(db, strategy, data.get("timeframe") or b.timeframe, params,
                              data.get("risk") if data.get("risk") is not None else b.risk,
                              data.get("account_id") or b.account_id)
    changed_core = any(k in data and data[k] != getattr(b, k) for k in ("strategy", "symbol", "timeframe", "account_id"))
    for k in ("name", "account_id", "strategy", "symbol", "timeframe", "trade_mode"):
        if data.get(k) is not None:
            setattr(b, k, data[k])
    b.params, b.risk = params, risk
    if changed_core:
        b.state = {}
    if b.status == "error":
        b.status = "stopped"
    db.commit()
    accounts.invalidate_symbols(b.account_id)
    audit(db, user, "bot.update", f"bot:{b.id}", details=data, ip=client_ip(request))
    return bot_out(b)


@router.delete("/{bot_id}")
def delete_bot(bot_id: int, request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    b = _get(db, bot_id)
    if bots.is_running(bot_id):
        raise HTTPException(409, "Остановите бота перед удалением")
    db.delete(b)
    db.commit()
    audit(db, user, "bot.delete", f"bot:{bot_id}", ip=client_ip(request))
    return {"ok": True}


@router.post("/{bot_id}/start")
async def start_bot(bot_id: int, request: Request, user: User = Depends(require("trader")),
                    db: Session = Depends(get_db)):
    b = _get(db, bot_id)
    try:
        STRATEGIES[b.strategy].validate(b.params)
        RISK.validate(b.risk)
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, f"Некорректные настройки бота: {exc}")
    await bots.start(bot_id)
    audit(db, user, "bot.start", f"bot:{bot_id}", ip=client_ip(request))
    db.refresh(b)
    return bot_out(b)


@router.post("/{bot_id}/stop")
async def stop_bot(bot_id: int, request: Request, user: User = Depends(require("trader")),
                   db: Session = Depends(get_db)):
    b = _get(db, bot_id)
    await bots.stop(bot_id)
    audit(db, user, "bot.stop", f"bot:{bot_id}", ip=client_ip(request))
    db.refresh(b)
    return bot_out(b)


@router.post("/{bot_id}/reset-state")
def reset_state(bot_id: int, request: Request, user: User = Depends(require("trader")), db: Session = Depends(get_db)):
    b = _get(db, bot_id)
    if bots.is_running(bot_id):
        raise HTTPException(409, "Остановите бота перед сбросом состояния")
    b.state, b.last_error, b.status = {}, None, "stopped"
    db.commit()
    audit(db, user, "bot.reset_state", f"bot:{bot_id}", ip=client_ip(request))
    return bot_out(b)


@router.post("/{bot_id}/close-positions")
async def close_positions(bot_id: int, request: Request, user: User = Depends(require("trader")),
                          db: Session = Depends(get_db)):
    b = _get(db, bot_id)
    accounts.ensure_trading_allowed(b.account_id)
    results = []
    for p in await accounts.call(b.account_id, "positions", magic=b.magic):
        r = await accounts.call(b.account_id, "close_position", ticket=p["ticket"], deviation=50,
                                comment=f"ato#{b.id} manual")
        results.append(r)
        db.add(BotOrder(bot_id=b.id, action="close_manual", symbol=p["symbol"], side=p["side"], volume=p["volume"],
                        price=r.get("price"), ok=bool(r.get("ok")), retcode=r.get("retcode"),
                        order_ticket=r.get("order"), deal_ticket=r.get("deal"), comment=r.get("retcode_text"),
                        response=r))
    db.commit()
    audit(db, user, "bot.close_positions", f"bot:{bot_id}", details={"count": len(results)}, ip=client_ip(request))
    return {"closed": sum(1 for r in results if r.get("ok")), "results": results}


@router.get("/{bot_id}/logs")
def bot_logs(bot_id: int, limit: int = Query(200, ge=1, le=2000), before_id: int | None = None,
             level: str | None = None, _: User = Depends(current_user), db: Session = Depends(get_db)):
    _get(db, bot_id)
    q = select(BotLog).where(BotLog.bot_id == bot_id)
    if before_id:
        q = q.where(BotLog.id < before_id)
    if level:
        q = q.where(BotLog.level == level)
    rows = db.scalars(q.order_by(BotLog.id.desc()).limit(limit)).all()
    return [{"id": r.id, "ts": r.ts.isoformat(), "level": r.level, "message": r.message, "data": r.data} for r in rows]


@router.delete("/{bot_id}/logs")
def clear_logs(bot_id: int, _: User = Depends(require("trader")), db: Session = Depends(get_db)):
    _get(db, bot_id)
    db.execute(delete(BotLog).where(BotLog.bot_id == bot_id))
    db.commit()
    return {"ok": True}


@router.get("/{bot_id}/orders")
def bot_orders(bot_id: int, limit: int = Query(200, ge=1, le=2000), _: User = Depends(current_user),
               db: Session = Depends(get_db)):
    _get(db, bot_id)
    rows = db.scalars(select(BotOrder).where(BotOrder.bot_id == bot_id).order_by(BotOrder.id.desc()).limit(limit))
    return [{"id": r.id, "ts": r.ts.isoformat(), "action": r.action, "symbol": r.symbol, "side": r.side,
             "volume": r.volume, "price": r.price, "ok": r.ok, "retcode": r.retcode, "order": r.order_ticket,
             "deal": r.deal_ticket, "comment": r.comment} for r in rows]


@router.get("/{bot_id}/positions")
async def bot_positions(bot_id: int, _: User = Depends(current_user), db: Session = Depends(get_db)):
    b = _get(db, bot_id)
    return await accounts.call(b.account_id, "positions", magic=b.magic)


@router.get("/{bot_id}/performance")
async def bot_performance(bot_id: int, days: int = Query(30, ge=1, le=3650), _: User = Depends(current_user),
                          db: Session = Depends(get_db)):
    """Performance computed from the real MT5 deal history filtered by the bot's magic number."""
    b = _get(db, bot_id)
    deals = await accounts.call(b.account_id, "history_deals", date_from=time.time() - days * 86400,
                                date_to=time.time() + 86400, magic=b.magic)
    positions = await accounts.call(b.account_id, "positions", magic=b.magic)
    closed = [d for d in deals if d.get("deal_entry") in ("out", "inout", "out_by")]
    net = [d["profit"] + d.get("commission", 0) + d.get("swap", 0) + d.get("fee", 0) for d in closed]
    costs_in = sum(d.get("commission", 0) + d.get("fee", 0) for d in deals if d.get("deal_entry") == "in")
    curve, acc = [], 0.0
    for d, v in sorted(zip(closed, net), key=lambda x: x[0]["time"]):
        acc += v
        curve.append({"time": d["time"], "pnl": round(acc, 2)})
    wins = [v for v in net if v > 0]
    losses = [v for v in net if v < 0]
    peak, mdd = 0.0, 0.0
    for pnt in curve:
        peak = max(peak, pnt["pnl"])
        mdd = max(mdd, peak - pnt["pnl"])
    return {
        "days": days, "deals": deals, "positions": positions, "trades": len(closed),
        "wins": len(wins), "losses": len(losses), "win_rate": (len(wins) / len(closed)) if closed else None,
        "realized_pnl": round(sum(net) + costs_in, 2), "floating_pnl": round(sum(p["profit"] for p in positions), 2),
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses else None, "max_drawdown": round(mdd, 2),
        "equity_curve": curve,
    }
