"""Gửi thông báo qua Telegram Bot API.

Cấu hình lưu trong data/telegram.json (không nằm trong git), tạo bằng lệnh:
    auction telegram-setup --token <TOKEN_TU_BOTFATHER>
Hoặc dùng biến môi trường AUCTION_TELEGRAM_TOKEN / AUCTION_TELEGRAM_CHAT.
Gửi thông báo không bao giờ làm hỏng việc thu thập: lỗi mạng chỉ ghi log.
"""
from __future__ import annotations

import html
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

import httpx

from .config import Settings

log = logging.getLogger(__name__)
API = "https://api.telegram.org"
MAX_LEN = 4000          # Telegram giới hạn 4096 ký tự / tin


def config_path(settings: Settings) -> Path:
    return settings.path("data/telegram.json")


def load_config(settings: Settings) -> dict[str, str]:
    cfg: dict[str, str] = {}
    p = config_path(settings)
    if p.exists():
        try:
            cfg = json.loads(p.read_text())
        except (OSError, ValueError) as e:
            log.warning("Không đọc được %s: %r", p, e)
    if v := os.environ.get("AUCTION_TELEGRAM_TOKEN"):
        cfg["token"] = v
    if v := os.environ.get("AUCTION_TELEGRAM_CHAT"):
        cfg["chat_id"] = v
    return cfg


def save_config(settings: Settings, token: str, chat_id: str) -> Path:
    p = config_path(settings)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"token": token, "chat_id": str(chat_id)}))
    p.chmod(0o600)
    return p


def is_configured(settings: Settings) -> bool:
    c = load_config(settings)
    return bool(c.get("token") and c.get("chat_id"))


def _call(token: str, method: str, transport: httpx.BaseTransport | None = None, **params: Any) -> dict:
    with httpx.Client(timeout=20, transport=transport) as c:
        r = c.post(f"{API}/bot{token}/{method}", json=params)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description") or f"HTTP {r.status_code}")
    return data["result"]


def get_me(token: str, transport: httpx.BaseTransport | None = None) -> dict:
    return _call(token, "getMe", transport)


def discover_chats(token: str, transport: httpx.BaseTransport | None = None) -> list[dict[str, str]]:
    """Các nhóm/cuộc trò chuyện bot vừa nhận được tin (sau khi được thêm vào nhóm hoặc được nhắn /start)."""
    chats: dict[str, dict[str, str]] = {}
    for u in _call(token, "getUpdates", transport, timeout=0, allowed_updates=["message", "my_chat_member",
                                                                               "channel_post"]):
        for key in ("message", "my_chat_member", "channel_post", "edited_message"):
            chat = (u.get(key) or {}).get("chat")
            if chat:
                name = chat.get("title") or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
                chats[str(chat["id"])] = {"id": str(chat["id"]), "type": chat.get("type", ""), "name": name or ""}
    return list(chats.values())


def send(settings: Settings, text: str, transport: httpx.BaseTransport | None = None) -> bool:
    """Gửi tin (HTML). Trả False nếu chưa cấu hình hoặc lỗi - không bao giờ ném lỗi."""
    cfg = load_config(settings)
    if not (cfg.get("token") and cfg.get("chat_id")):
        return False
    ok = True
    for part in [text[i:i + MAX_LEN] for i in range(0, len(text), MAX_LEN)] or [""]:
        try:
            _call(cfg["token"], "sendMessage", transport, chat_id=cfg["chat_id"], text=part,
                  parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:  # noqa: BLE001
            log.warning("Gửi Telegram lỗi: %r", e)
            ok = False
    return ok


def esc(s: Any) -> str:
    return html.escape(str(s), quote=False)


def disk_usage_pct(path: Path) -> float:
    u = shutil.disk_usage(path)
    return round(u.used / u.total * 100, 1)
