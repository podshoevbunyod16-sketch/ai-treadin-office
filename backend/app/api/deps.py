from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import ROLE_LEVEL, decode_access_token

bearer = HTTPBearer(auto_error=False)


def user_from_token(db: Session, token: str) -> User:
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия истекла, войдите снова")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный токен")
    user = db.get(User, int(payload["sub"]))
    if user is None or not user.is_active or user.token_version != payload.get("tv"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Сессия недействительна")
    return user


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация",
                            headers={"WWW-Authenticate": "Bearer"})
    return user_from_token(db, creds.credentials)


def require(role: str):
    def dep(user: User = Depends(current_user)) -> User:
        if ROLE_LEVEL.get(user.role, -1) < ROLE_LEVEL[role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"Недостаточно прав (нужна роль {role})")
        return user

    return dep


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None
