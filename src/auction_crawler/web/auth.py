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

from ..realestate.db import LoginAttempt, User

LOCK_WINDOW_MIN = 15      # cửa sổ đếm & thời gian khoá (phút)
MAX_FAIL_PER_IP = 10      # sai từ 1 IP
MAX_FAIL_PER_USER = 20    # sai cho 1 tài khoản (từ nhiều IP) - chống dò phân tán


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


def login_blocked(s: Session, ip: str, username: str) -> int:
    """Số phút còn bị khoá (0 = được phép thử). Chỉ đếm lần sai trong 15 phút gần nhất VÀ sau lần
    đăng nhập đúng gần nhất (của IP / tài khoản đó). Lịch sử vẫn giữ nguyên để xem ở trang Hệ thống."""
    from datetime import timedelta

    from sqlalchemy import func
    window = datetime.now() - timedelta(minutes=LOCK_WINDOW_MIN)
    uname = username.strip().lower()
    for col, val, limit in ((LoginAttempt.ip, ip, MAX_FAIL_PER_IP), (LoginAttempt.username, uname, MAX_FAIL_PER_USER)):
        last_ok = s.scalar(select(func.max(LoginAttempt.at)).where(col == val, LoginAttempt.success.is_(True)))
        since = max(window, last_ok) if last_ok else window
        n, last = s.execute(select(func.count(), func.max(LoginAttempt.at)).where(
            col == val, LoginAttempt.success.is_(False), LoginAttempt.at > since)).one()
        if n >= limit and last:
            return max(1, LOCK_WINDOW_MIN - int((datetime.now() - last).total_seconds() // 60))
    return 0


def record_login(s: Session, ip: str, username: str, success: bool) -> None:
    from datetime import timedelta
    s.add(LoginAttempt(ip=ip[:64], username=username.strip().lower()[:64], success=success))
    # chỉ dọn bản ghi cũ hơn 30 ngày (giữ lịch sử để theo dõi)
    s.query(LoginAttempt).filter(LoginAttempt.at < datetime.now() - timedelta(days=30)).delete()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


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
