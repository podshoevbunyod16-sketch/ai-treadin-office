from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..security import (ROLES, create_access_token, hash_password, login_throttle, validate_password_strength,
                        verify_password)
from ..services.audit import audit
from .deps import client_ip, current_user, require

router = APIRouter(prefix="/api", tags=["auth"])

USERNAME_RE = r"^[A-Za-z0-9_.-]{3,64}$"


class Credentials(BaseModel):
    username: str = Field(pattern=USERNAME_RE)
    password: str = Field(min_length=1, max_length=200)


class NewPassword(BaseModel):
    password: str

    @field_validator("password")
    @classmethod
    def strong(cls, v: str) -> str:
        validate_password_strength(v)
        return v


class SetupIn(NewPassword):
    username: str = Field(pattern=USERNAME_RE)


class ChangePasswordIn(NewPassword):
    current_password: str


class UserCreate(SetupIn):
    role: str = "trader"


class UserPatch(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    password: str | None = None


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role, "is_active": u.is_active,
            "created_at": u.created_at.isoformat() if u.created_at else None}


def token_out(u: User) -> dict:
    return {"access_token": create_access_token(u.id, u.role, u.token_version), "token_type": "bearer",
            "user": user_out(u)}


@router.get("/auth/state")
def auth_state(db: Session = Depends(get_db)):
    return {"setup_required": db.scalar(select(func.count(User.id))) == 0}


@router.post("/auth/setup")
def setup(body: SetupIn, request: Request, db: Session = Depends(get_db)):
    if db.scalar(select(func.count(User.id))) > 0:
        raise HTTPException(409, "Администратор уже создан")
    u = User(username=body.username, password_hash=hash_password(body.password), role="admin")
    db.add(u)
    db.commit()
    audit(db, u, "auth.setup", u.username, ip=client_ip(request))
    return token_out(u)


@router.post("/auth/login")
def login(body: Credentials, request: Request, db: Session = Depends(get_db)):
    key = f"{client_ip(request)}|{body.username.lower()}"
    if login_throttle.is_blocked(key):
        raise HTTPException(429, "Слишком много неудачных попыток входа. Повторите позже.")
    u = db.scalar(select(User).where(User.username == body.username))
    if u is None or not u.is_active or not verify_password(body.password, u.password_hash):
        login_throttle.fail(key)
        audit(db, u, "auth.login", body.username, ok=False, ip=client_ip(request))
        raise HTTPException(401, "Неверное имя пользователя или пароль")
    login_throttle.reset(key)
    audit(db, u, "auth.login", u.username, ip=client_ip(request))
    return token_out(u)


@router.get("/auth/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.post("/auth/change-password")
def change_password(body: ChangePasswordIn, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    u = db.get(User, user.id)
    if not verify_password(body.current_password, u.password_hash):
        raise HTTPException(400, "Текущий пароль неверен")
    u.password_hash = hash_password(body.password)
    u.token_version += 1
    db.commit()
    audit(db, u, "auth.change_password", u.username, ip=client_ip(request))
    return token_out(u)


@router.post("/auth/logout-all")
def logout_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    u = db.get(User, user.id)
    u.token_version += 1
    db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- users (admin)
@router.get("/users")
def list_users(_: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.id))]


@router.post("/users", status_code=201)
def create_user(body: UserCreate, request: Request, admin: User = Depends(require("admin")),
                db: Session = Depends(get_db)):
    if body.role not in ROLES:
        raise HTTPException(422, "Неверная роль")
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "Пользователь уже существует")
    u = User(username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(u)
    db.commit()
    audit(db, admin, "user.create", u.username, details={"role": u.role}, ip=client_ip(request))
    return user_out(u)


@router.patch("/users/{user_id}")
def patch_user(user_id: int, body: UserPatch, request: Request, admin: User = Depends(require("admin")),
               db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Пользователь не найден")
    if u.id == admin.id and (body.role not in (None, "admin") or body.is_active is False):
        raise HTTPException(400, "Нельзя понизить или заблокировать самого себя")
    if body.role is not None:
        if body.role not in ROLES:
            raise HTTPException(422, "Неверная роль")
        u.role = body.role
        u.token_version += 1
    if body.is_active is not None:
        u.is_active = body.is_active
        u.token_version += 1
    if body.password:
        try:
            validate_password_strength(body.password)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        u.password_hash = hash_password(body.password)
        u.token_version += 1
    db.commit()
    audit(db, admin, "user.update", u.username, details=body.model_dump(exclude={"password"}), ip=client_ip(request))
    return user_out(u)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, admin: User = Depends(require("admin")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, "Пользователь не найден")
    if u.id == admin.id:
        raise HTTPException(400, "Нельзя удалить самого себя")
    db.delete(u)
    db.commit()
    audit(db, admin, "user.delete", u.username, ip=client_ip(request))
    return {"ok": True}
