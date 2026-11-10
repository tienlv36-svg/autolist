"""Thông báo cá nhân qua Telegram (mỗi tài khoản liên kết Telegram riêng bằng mã /start):
- Bộ lọc đã lưu: sau mỗi lượt thu thập, báo tài sản MỚI (tài sản mới hoặc có phiên mới) khớp bộ lọc.
- Nhắc hạn (mỗi ngày 1 lần): tài sản trong giỏ sắp hết hạn đăng ký; việc được giao sắp/đã quá hạn;
  với quản trị thêm tài sản ưu tiên Cao/Rất cao sắp hết hạn.
Tin gửi riêng từng người (giỏ hàng, bộ lọc là riêng tư) – không gửi vào nhóm chung.
"""
from __future__ import annotations

import logging
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import parse_qs

from sqlalchemy import func, or_, select

from .config import Settings
from .notify import esc, recent_messages, send_to
from .realestate.db import CartItem, Property, SavedSearch, Task, User
from .storage import NoticeRow, Repository

log = logging.getLogger(__name__)
REMIND_DAYS = 3          # nhắc khi hạn đăng ký còn <= 3 ngày
MAX_LIST = 10


class _QP(dict):
    """Giả lập request.query_params cho Filters.from_request."""
    def getlist(self, k):
        return list(self.get_all(k))

    def get_all(self, k):
        return super().get(k, [])

    def get(self, k, default=None):
        v = super().get(k)
        return v[0] if v else default


def filters_from_query(query: str):
    from .web.queries import Filters
    return Filters.from_request(_QP(parse_qs(query or "", keep_blank_values=False)))


def new_link_code() -> str:
    return secrets.token_hex(3).upper()


def link_users(settings: Settings, repo: Repository, transport=None) -> int:
    """Liên kết tài khoản với Telegram: người dùng nhắn cho bot '/start <MÃ>' (mã hiện ở trang Tài khoản)."""
    try:
        msgs = recent_messages(settings, transport)
    except Exception as e:  # noqa: BLE001
        log.warning("Đọc tin Telegram lỗi: %r", e)
        return 0
    n = 0
    with repo.Session.begin() as s:
        pending = {u.tg_link_code: u for u in s.scalars(select(User).where(User.tg_link_code.is_not(None)))}
        for m in msgs:
            code = re.sub(r"^/start\s*", "", m["text"].strip(), flags=re.I).strip().upper()
            if u := pending.pop(code, None):
                u.tg_chat_id, u.tg_link_code = m["chat_id"], None
                n += 1
                send_to(settings, u.tg_chat_id, f"✅ Đã liên kết với tài khoản <b>{esc(u.full_name)}</b> trên hệ thống "
                                                f"đấu giá BĐS. Bạn sẽ nhận bộ lọc đã lưu và nhắc hạn tại đây.", transport)
    return n


def _base_url(settings: Settings) -> str:
    p = settings.path("data/.domain")
    try:
        d = p.read_text().strip() if p.exists() else ""
    except OSError:
        d = ""
    return f"https://{d}" if d else ""


def _line(p: Property, base: str) -> str:
    from .web import fmt
    price = fmt.money(p.eff("price_latest")) if p.eff("price_latest") else "chưa có giá"
    disc = f", −{fmt.num(p.discount_pct)}%" if p.discount_pct else ""
    dl = f", hạn ĐK {p.registration_end:%d/%m}" if p.registration_end else ""
    title = esc((p.title or "")[:90])
    link = f'<a href="{base}/p/{p.id}">#{p.id}</a>' if base else f"#{p.id}"
    return f"• {link} {title} – <b>{price}</b>{disc}{dl}"


def new_matches(s, ss: SavedSearch, since: datetime) -> list[Property]:
    """Tài sản khớp bộ lọc và MỚI kể từ `since`: tài sản mới tạo hoặc thông báo mới nhất xuất hiện sau mốc."""
    from .web.queries import build_query
    f = filters_from_query(ss.query)
    q = build_query(f, ss.user_id).order_by(None)
    q = q.outerjoin(NoticeRow, NoticeRow.id == Property.latest_notice_id).where(
        or_(Property.created_at >= since, NoticeRow.first_seen >= since))
    return s.scalars(q.order_by(Property.registration_end.is_(None), Property.registration_end)).all()


@dataclass
class AlertStats:
    linked: int = 0
    searches: int = 0
    search_msgs: int = 0
    reminder_msgs: int = 0
    errors: list[str] = field(default_factory=list)


def run_alerts(settings: Settings, repo: Repository, now: datetime | None = None, transport=None) -> AlertStats:
    now = now or datetime.now()
    st = AlertStats(linked=link_users(settings, repo, transport))
    base = _base_url(settings)
    with repo.Session.begin() as s:
        users = {u.id: u for u in s.scalars(select(User).where(User.active.is_(True)))}
        for ss in s.scalars(select(SavedSearch).where(SavedSearch.notify.is_(True))):
            u = users.get(ss.user_id)
            st.searches += 1
            found = new_matches(s, ss, ss.checked_at)
            ss.last_new, ss.checked_at = len(found), now
            if not found or not (u and u.tg_chat_id):
                continue
            lines = [f"🔔 <b>{esc(ss.name)}</b>: {len(found)} tài sản mới"] + [_line(p, base) for p in found[:MAX_LIST]]
            if len(found) > MAX_LIST:
                lines.append(f"… và {len(found) - MAX_LIST} tài sản khác"
                             + (f' – <a href="{base}/searches/{ss.id}/open">xem tất cả</a>' if base else ""))
            if send_to(settings, u.tg_chat_id, "\n".join(lines), transport):
                st.search_msgs += 1
        today = now.date()
        for u in users.values():
            if not u.tg_chat_id or u.last_reminder_on == today:
                continue
            text = reminder_text(s, u, now, base)
            u.last_reminder_on = today
            if text and send_to(settings, u.tg_chat_id, text, transport):
                st.reminder_msgs += 1
    return st


def reminders(s, u: User, now: datetime) -> dict[str, list]:
    """Danh sách cần nhắc của 1 tài khoản (dùng cho Telegram và banner trên web)."""
    soon = now + timedelta(days=REMIND_DAYS)
    cart = s.scalars(select(Property).join(CartItem, CartItem.property_id == Property.id)
                     .where(CartItem.user_id == u.id, Property.registration_end >= now,
                            Property.registration_end <= soon).order_by(Property.registration_end)).all()
    tasks = s.scalars(select(Task).where(Task.assignee_id == u.id, Task.status.in_(["moi", "dang_lam"]),
                                         Task.due_date.is_not(None), Task.due_date <= now.date() + timedelta(days=1))
                      .order_by(Task.due_date)).all()
    prio = []
    if u.role == "admin":
        prio = s.scalars(select(Property).where(Property.priority >= 3, Property.registration_end >= now,
                                                Property.registration_end <= soon)
                         .order_by(Property.registration_end)).all()
    return {"cart": cart, "tasks": tasks, "priority": prio}


def reminder_text(s, u: User, now: datetime, base: str) -> str | None:
    r = reminders(s, u, now)
    if not any(r.values()):
        return None
    lines = [f"⏰ <b>Nhắc hạn {now:%d/%m}</b>"]
    if r["cart"]:
        lines.append(f"<b>Trong giỏ của bạn – hết hạn đăng ký trong {REMIND_DAYS} ngày:</b>")
        lines += [_line(p, base) for p in r["cart"][:MAX_LIST]]
    if r["tasks"]:
        lines.append("<b>Việc được giao sắp/đã quá hạn:</b>")
        for t in r["tasks"][:MAX_LIST]:
            late = " (QUÁ HẠN)" if t.due_date < now.date() else ""
            lines.append(f"• {esc(t.title)} – hạn {t.due_date:%d/%m}{late}"
                         + (f" – tài sản #{t.property_id}" if t.property_id else ""))
    if r["priority"]:
        lines.append(f"<b>Ưu tiên Cao/Rất cao – hết hạn đăng ký trong {REMIND_DAYS} ngày:</b>")
        lines += [_line(p, base) for p in r["priority"][:MAX_LIST]]
    return "\n".join(lines)


def count_reminders(s, u: User, now: datetime) -> int:
    return sum(len(v) for v in reminders(s, u, now).values())


def search_counts(s, user_id: int) -> dict[int, int]:
    """Số tài sản khớp hiện tại của từng bộ lọc (hiển thị trên trang Bộ lọc của tôi)."""
    from .web.queries import build_query
    out = {}
    for ss in s.scalars(select(SavedSearch).where(SavedSearch.user_id == user_id)):
        q = build_query(filters_from_query(ss.query), user_id).order_by(None)
        out[ss.id] = s.scalar(select(func.count()).select_from(q.subquery())) or 0
    return out
