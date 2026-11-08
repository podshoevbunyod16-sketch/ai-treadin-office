from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..db import session_scope
from ..models import AuditLog, User


def audit(db: Session | None, user: User | None, action: str, target: str | None = None, ok: bool = True,
          details: dict[str, Any] | None = None, ip: str | None = None) -> None:
    entry = AuditLog(user_id=user.id if user else None, username=user.username if user else None, action=action,
                     target=target, ok=ok, details=details, ip=ip)
    if db is None:
        with session_scope() as s:
            s.add(entry)
    else:
        db.add(entry)
        db.commit()
