from __future__ import annotations

import platform
import sys
import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import __version__
from ..config import get_settings
from ..db import get_db
from ..models import AuditLog, User
from ..mt5.gateway import ProcessGateway
from ..services.hub import hub
from ..state import accounts, bots
from .deps import current_user, require

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health():
    return {"ok": True, "version": __version__, "time": time.time()}


@router.get("/system/status")
def system_status(_: User = Depends(current_user)):
    s = get_settings()
    pkg = ProcessGateway.package_available()
    return {
        "version": __version__, "server_time": time.time(), "python": sys.version.split()[0],
        "platform": platform.platform(), "os": sys.platform,
        "mt5_package_installed": pkg,
        "local_mode_available": pkg and sys.platform == "win32",
        "local_mode_note": None if pkg else (
            "Пакет MetaTrader5 не установлен на сервере. Режим «local» невозможен; "
            "используйте режим «bridge» (агент на Windows рядом с терминалом MT5)."),
        "allow_real_trading": s.allow_real_trading, "environment": s.environment,
        "accounts": [rt.public() for rt in accounts.runtimes.values()],
        "bots_running": [bid for bid in bots.runners if bots.is_running(bid)],
        "ws_clients": hub.clients,
    }


@router.get("/audit")
def audit_log(limit: int = Query(200, ge=1, le=2000), action: str | None = None,
              _: User = Depends(require("trader")), db: Session = Depends(get_db)):
    q = select(AuditLog)
    if action:
        q = q.where(AuditLog.action.like(f"{action}%"))
    rows = db.scalars(q.order_by(AuditLog.id.desc()).limit(limit))
    return [{"id": r.id, "ts": r.ts.isoformat(), "username": r.username, "action": r.action, "target": r.target,
             "ok": r.ok, "details": r.details, "ip": r.ip} for r in rows]
