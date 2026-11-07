"""Tài khoản: băm mật khẩu (scrypt), phiên đăng nhập (cookie ký), chống CSRF cho form."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..realestate.db import User


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${h.hex()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
        return hmac.compare_digest(calc.hex(), h)
    except (ValueError, TypeError):
        return False


def authenticate(s: Session, username: str, pw: str) -> User | None:
    u = s.scalar(select(User).where(User.username == username.strip().lower(), User.active.is_(True)))
    if u and verify_password(pw, u.password_hash):
        u.last_login = datetime.now()
        return u
    return None


def csrf_token(request: Request) -> str:
    tok = request.session.get("csrf")
    if not tok:
        tok = request.session["csrf"] = secrets.token_urlsafe(24)
    return tok


def check_csrf(request: Request, token: str | None) -> None:
    if not token or not hmac.compare_digest(token, request.session.get("csrf", "")):
        raise HTTPException(400, "Phiên làm việc hết hạn, vui lòng tải lại trang (CSRF).")


class LoginRequired(Exception):
    pass


def current_user(request: Request, s: Session) -> User:
    uid = request.session.get("uid")
    u = s.get(User, uid) if uid else None
    if not u or not u.active:
        raise LoginRequired()
    return u


def load_secret(path) -> str:
    if v := os.environ.get("AUCTION_SECRET"):
        return v
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(secrets.token_urlsafe(48))
        path.chmod(0o600)
    return path.read_text().strip()
