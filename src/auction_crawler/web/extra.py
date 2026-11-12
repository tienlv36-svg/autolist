"""Trang bổ sung: bộ lọc đã lưu, liên kết Telegram cá nhân, nhắc hạn, gợi ý gộp phiên, độ đầy đủ dữ liệu."""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from urllib.parse import urlencode

from fastapi import BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import case, func, select

from ..alerts import link_users, new_link_code, reminders, search_counts
from ..notify import bot_username, is_configured
from ..realestate.db import Property, PropertyNotice, SavedSearch
from .auth import check_csrf, current_user
from .queries import MISSING

log = logging.getLogger(__name__)
_rebuild_lock = threading.Lock()


def rebuild_in_background(settings, repo) -> None:
    """Gom phiên lại ở nền (sau gộp/tách). Đang có lượt thu thập -> bỏ qua: lượt đó sẽ gom lại, liên kết tay vẫn giữ."""
    from ..realestate.linker import rebuild
    from ..scheduler import AlreadyRunning, run_lock
    if not _rebuild_lock.acquire(blocking=False):
        return
    try:
        with run_lock(settings):
            rebuild(repo)
    except AlreadyRunning:
        log.info("Đang có lượt thu thập – gom phiên sẽ chạy trong lượt đó")
    except Exception:  # noqa: BLE001
        log.exception("gom phiên nền lỗi")
    finally:
        _rebuild_lock.release()


def merge_into(s, src: int, target: int) -> None:
    """Gộp mọi thông báo của tài sản src vào target và khoá cố định (người dùng đã xác nhận)."""
    for pn in s.scalars(select(PropertyNotice).where(PropertyNotice.property_id.in_([src, target]))):
        pn.property_id, pn.manual = target, True
        if pn.link_source in (None, "auto"):
            pn.link_source = "manual"


def register(app, repo, settings, render, back, log_act) -> None:
    # ------------------------------------------------------------------ bộ lọc đã lưu
    @app.get("/searches", response_class=HTMLResponse)
    def searches(request: Request, msg: str = ""):
        with repo.session() as s:
            user = current_user(request, s)
            items = s.scalars(select(SavedSearch).where(SavedSearch.user_id == user.id)
                              .order_by(SavedSearch.created_at.desc())).all()
            return render(request, "searches.html", user, items=items, counts=search_counts(s, user.id), msg=msg,
                          tg_ready=is_configured(settings))

    @app.post("/searches")
    def search_add(request: Request, csrf: str = Form(""), name: str = Form(""), query: str = Form(""),
                   notify: str = Form("")):
        check_csrf(request, csrf)
        query = "&".join(p for p in query.split("&") if p and not p.startswith(("page=", "csrf=")))
        with repo.Session.begin() as s:
            user = current_user(request, s)
            s.add(SavedSearch(user_id=user.id, name=(name.strip() or "Bộ lọc " + datetime.now().strftime("%d/%m"))[:120],
                              query=query[:2000], notify=notify == "1"))
        return back("/searches?msg=Đã lưu bộ lọc")

    def _own(s, user, sid: int) -> SavedSearch:
        ss = s.get(SavedSearch, sid)
        if not ss or ss.user_id != user.id:
            raise HTTPException(404)
        return ss

    @app.get("/searches/{sid}/open")
    def search_open(request: Request, sid: int):
        with repo.session() as s:
            ss = _own(s, current_user(request, s), sid)
            return back("/?" + ss.query)

    @app.post("/searches/{sid}")
    def search_edit(request: Request, sid: int, csrf: str = Form(""), action: str = Form("")):
        check_csrf(request, csrf)
        with repo.Session.begin() as s:
            ss = _own(s, current_user(request, s), sid)
            if action == "delete":
                s.delete(ss)
            elif action == "notify":
                ss.notify = not ss.notify
                ss.checked_at = datetime.now()
        return back("/searches")

    # ------------------------------------------------------------------ Telegram cá nhân
    @app.post("/account/telegram")
    def account_telegram(request: Request, csrf: str = Form(""), action: str = Form("")):
        check_csrf(request, csrf)
        msg = ""
        if action == "check":
            n = link_users(settings, repo)
            msg = "Đã liên kết Telegram" if n else "Chưa thấy mã – kiểm tra đã gửi đúng /start <mã> cho bot chưa"
        with repo.Session.begin() as s:
            u = current_user(request, s)
            if action == "code":
                u.tg_link_code = new_link_code()
            elif action == "unlink":
                u.tg_chat_id = u.tg_link_code = None
                msg = "Đã huỷ liên kết Telegram"
            elif action == "check" and u.tg_chat_id:
                msg = "Đã liên kết Telegram"
        return back("/account" + ("?" + urlencode({"msg": msg}) if msg else "") + "#telegram")

    app.state.bot_username = None

    def bot_name():
        if app.state.bot_username is None and is_configured(settings):
            app.state.bot_username = bot_username(settings) or ""
        return app.state.bot_username

    app.state.get_bot_name = bot_name

    # ------------------------------------------------------------------ nhắc hạn
    @app.get("/reminders", response_class=HTMLResponse)
    def reminders_page(request: Request):
        with repo.session() as s:
            user = current_user(request, s)
            return render(request, "reminders.html", user, r=reminders(s, user, datetime.now()), now=datetime.now())

    # ------------------------------------------------------------------ thống kê
    @app.get("/stats", response_class=HTMLResponse)
    def stats_page(request: Request):
        from datetime import timedelta

        from . import fmt
        from ..realestate.db import OWNER_TYPES
        now = datetime.now()
        with repo.session() as s:
            user = current_user(request, s)
            open_q = Property.registration_end >= now
            pv = func.coalesce(Property.province_manual, Property.province)
            kpi = {
                "open": s.scalar(select(func.count(Property.id)).where(open_q)) or 0,
                "new7": s.scalar(select(func.count(Property.id)).where(Property.created_at >= now - timedelta(days=7))) or 0,
                "disc": s.scalar(select(func.avg(Property.discount_pct)).where(open_q, Property.discount_pct > 0)),
                "multi": s.scalar(select(func.count(Property.id)).where(open_q, Property.session_count > 1)) or 0,
            }
            # tài sản mới theo tuần (12 tuần, tính từ thứ Hai)
            monday = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            weeks = []
            for i in range(11, -1, -1):
                a = monday - timedelta(weeks=i)
                n = s.scalar(select(func.count(Property.id)).where(Property.created_at >= a,
                                                                   Property.created_at < a + timedelta(weeks=1))) or 0
                weeks.append((f"{a:%d/%m}", n, f"Tuần {a:%d/%m}–{a + timedelta(days=6):%d/%m}: {n} tài sản mới"))
            def group(col):
                return s.execute(select(col, func.count(Property.id), func.avg(Property.discount_pct),
                                        func.sum(case((Property.discount_pct > 0, 1), else_=0)))
                                 .where(open_q).group_by(col).order_by(func.count(Property.id).desc())).all()
            by_prov = [r for r in group(pv) if r[0]]
            by_owner = [(OWNER_TYPES.get(k or "khac", k), n, d, nd) for k, n, d, nd in group(Property.owner_type)]
            return render(request, "stats.html", user, kpi=kpi, weekly=fmt.bar_chart(weeks), by_prov=by_prov,
                          by_owner=by_owner, maxn=max([n for _, n, *_ in by_prov] or [1]))

    # ------------------------------------------------------------------ độ đầy đủ dữ liệu
    @app.get("/quality", response_class=HTMLResponse)
    def quality(request: Request):
        now = datetime.now()
        with repo.session() as s:
            user = current_user(request, s)
            open_q = Property.registration_end >= now
            total = s.scalar(select(func.count(Property.id)).where(open_q)) or 0
            rows = []
            for key, (label, cond_fn) in MISSING.items():
                cond, scope = cond_fn()
                base = select(func.count(Property.id)).where(open_q, *scope)
                n_scope = s.scalar(base) or 0
                n_missing = s.scalar(base.where(cond)) or 0
                rows.append({"key": key, "label": label, "scope": n_scope, "missing": n_missing,
                             "pct": round((n_scope - n_missing) / n_scope * 100, 1) if n_scope else None})
            src = s.execute(select(func.sum(case((func.length(Property.field_sources) > 4, 1), else_=0)))
                            .where(open_q)).scalar() or 0
            return render(request, "quality.html", user, rows=rows, total=total, from_docs=src)
