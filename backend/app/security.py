"""Password hashing, JWT tokens, secret encryption, login throttling."""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings

ROLES = ("admin", "trader", "viewer")
ROLE_LEVEL = {"viewer": 0, "trader": 1, "admin": 2}


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode())
    except ValueError:
        return False


def validate_password_strength(password: str) -> None:
    if len(password) < 10:
        raise ValueError("Пароль должен содержать минимум 10 символов")
    if password.isdigit() or password.isalpha():
        raise ValueError("Пароль должен содержать буквы и цифры/символы")
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Пароль слишком длинный (максимум 72 байта)")


def create_access_token(user_id: int, role: str, token_version: int) -> str:
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "role": role,
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=s.access_token_minutes)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, s.get_jwt_secret(), algorithm="HS256")


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, get_settings().get_jwt_secret(), algorithms=["HS256"])
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(get_settings().get_encryption_key().encode())
    return _fernet


def reset_crypto_cache() -> None:
    global _fernet
    _fernet = None


def encrypt_secret(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    return _get_fernet().encrypt(value.encode("utf-8")).decode()


def decrypt_secret(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _get_fernet().decrypt(value.encode()).decode("utf-8")
    except InvalidToken as exc:  # key rotated / corrupted
        raise RuntimeError("Не удалось расшифровать секрет: неверный ключ шифрования (ATO_ENCRYPTION_KEY)") from exc


class LoginThrottle:
    """Sliding-window limiter of failed login attempts per (ip, username)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fails: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, now: float, window: int) -> deque[float]:
        q = self._fails[key]
        while q and now - q[0] > window:
            q.popleft()
        return q

    def is_blocked(self, key: str) -> bool:
        s = get_settings()
        with self._lock:
            return len(self._prune(key, time.monotonic(), s.login_window_s)) >= s.login_max_attempts

    def fail(self, key: str) -> None:
        with self._lock:
            self._fails[key].append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._fails.pop(key, None)


login_throttle = LoginThrottle()
