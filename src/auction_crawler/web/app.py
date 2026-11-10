"""Ứng dụng web: `auction web` -> http://localhost:8000"""
from __future__ import annotations

import logging
import mimetypes
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from starlette.middleware.sessions import SessionMiddleware

from ..config import get_settings
from ..attachments import NoticeFile
from ..realestate.db import (CATEGORIES, CartItem, EDITABLE, MONEY_FIELDS, OWNER_TYPES, PRIORITIES, SALE_FORMS, TASK_STATUS, Activity,
                             Comment, FileView, Property, PropertyFile, PropertyNotice, Task, User)
from ..storage import AssetRow, NoticeRow, Repository
from ..normalize import PROVINCE_MERGE, parse_vnd
from ..realestate.extract import parse_number
from . import fmt
from .auth import LoginRequired, authenticate, client_ip, login_blocked, record_login, check_csrf, csrf_token, current_user, hash_password, load_secret
from .queries import SORTS, Filters, build_query
from .sourcedocs import needs_sync, sync_source_docs

log = logging.getLogger(__name__)
DOC_METHODS = {"text": "đọc chữ", "docx": "đọc chữ", "ocr": "OCR", "none": "không đọc được",
               "unsupported": "chỉ lưu"}
HERE = Path(__file__).parent
PAGE_SIZE = 30
EXPORT_MAX = 20000
MAX_UPLOAD = 1024 * 1024 * 1024  # 1 GB / file
FOLDERS = ["Hình ảnh", "Video", "Pháp lý", "Hiện trạng", "Định giá", "Tài liệu"]


def kind_of(mime: str | None, name: str) -> str:
    m = mime or mimetypes.guess_type(name)[0] or ""
    return "image" if m.startswith("image/") else "video" if m.startswith("video/") else "document"


def create_app(repo: Repository | None = None, media_root: Path | None = None,
               sync_docs: bool = True) -> FastAPI:
    settings = get_settings()
    repo = repo or Repository(settings.resolved_db_url)
    repo.init_db()
    media_root = media_root or settings.path("data/media")
    media_root.mkdir(parents=True, exist_ok=True)

    app = FastAPI(title="Quản lý tài sản đấu giá BĐS", docs_url=None, redoc_url=None)
    app.add_middleware(SessionMiddleware, secret_key=load_secret(media_root.parent / "secret.key"),
                       max_age=14 * 24 * 3600, same_site="lax", session_cookie="auction_session",
                       https_only=os.environ.get("AUCTION_COOKIE_SECURE") == "1")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    tpl = Jinja2Templates(directory=HERE / "templates")
    tpl.env.globals.update(fmt=fmt, PRIORITIES=PRIORITIES, SALE_FORMS=SALE_FORMS, OWNER_TYPES=OWNER_TYPES,
                           CATEGORIES=CATEGORIES, TASK_STATUS=TASK_STATUS, EDITABLE=EDITABLE, SORTS=SORTS,
                           FOLDERS=FOLDERS, MONEY_FIELDS=MONEY_FIELDS, PROVINCES=sorted(PROVINCE_MERGE))
    app.state.repo = repo

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc: LoginRequired):
        return RedirectResponse(f"/login?next={request.url.path}", status_code=303)

    def render(request: Request, name: str, user: User | None, **ctx: Any) -> HTMLResponse:
        if user is not None and "cart_count" not in ctx:
            with repo.session() as s:
                ctx["cart_count"] = s.scalar(select(func.count(CartItem.id)).where(CartItem.user_id == user.id)) or 0
        return tpl.TemplateResponse(request, name, {"user": user, "csrf": csrf_token(request), **ctx})

    def my_cart_ids(s, user: User) -> set[int]:
        return set(s.scalars(select(CartItem.property_id).where(CartItem.user_id == user.id)))

    def back(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    def log_act(s, pid: int | None, user: User, action: str, detail: str) -> None:
        s.add(Activity(property_id=pid, user_id=user.id, action=action, detail=detail))

    # ------------------------------------------------------------------ đăng nhập
    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next: str = "/", error: str = ""):
        return render(request, "login.html", None, next=next, error=error)

    @app.post("/login")
    def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/")):
        ip = client_ip(request)
        with repo.Session.begin() as s:
            if (mins := login_blocked(s, ip, username)):
                log.warning("Chặn đăng nhập: ip=%s user=%s (còn %s phút)", ip, username, mins)
                return render(request, "login.html", None, next=next,
                              error=f"Đăng nhập sai quá nhiều lần. Vui lòng thử lại sau {mins} phút.")
            u = authenticate(s, username, password)
            record_login(s, ip, username, bool(u))
            if not u:
                log.warning("Đăng nhập sai: ip=%s user=%s", ip, username)
                return render(request, "login.html", None, next=next, error="Sai tên đăng nhập hoặc mật khẩu")
            request.session.clear()
            request.session["uid"] = u.id
        return back(next if next.startswith("/") and not next.startswith("//") else "/")

    @app.post("/logout")
    def logout(request: Request):
        request.session.clear()
        return back("/login")

    @app.get("/account", response_class=HTMLResponse)
    def account(request: Request, msg: str = ""):
        with repo.session() as s:
            return render(request, "account.html", current_user(request, s), msg=msg)

    @app.post("/account")
    def account_save(request: Request, csrf: str = Form(""), old: str = Form(...), new: str = Form(...)):
        check_csrf(request, csrf)
        from .auth import verify_password
        with repo.Session.begin() as s:
            u = current_user(request, s)
            if not verify_password(old, u.password_hash) or len(new) < 8:
                return back("/account?msg=Mật khẩu cũ sai hoặc mật khẩu mới dưới 8 ký tự")
            u.password_hash = hash_password(new)
        return back("/account?msg=Đã đổi mật khẩu")

    # ------------------------------------------------------------------ danh sách
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        f = Filters.from_request(request.query_params)
        with repo.session() as s:
            user = current_user(request, s)
            q = build_query(f, user.id)
            total = s.scalar(select(func.count()).select_from(q.order_by(None).subquery()))
            items = s.scalars(q.offset((f.page - 1) * PAGE_SIZE).limit(PAGE_SIZE)).all()
            pv = func.coalesce(Property.province_manual, Property.province)
            provinces = [p for p, in s.execute(select(pv).where(pv.is_not(None)).group_by(pv).order_by(pv))]
            wards = _wards(s, f.province) if f.province else []
            qs = request.url.query
            base_qs = re.sub(r"(^|&)page=\d+", "", qs).lstrip("&")
            return render(request, "list.html", user, f=f, items=items, total=total, provinces=provinces,
                          wards=wards, page=f.page, pages=max(1, -(-total // PAGE_SIZE)), base_qs=base_qs,
                          now=datetime.now(), in_cart=my_cart_ids(s, user))

    def _wards(s, province: str) -> list[tuple[str, int]]:
        w = func.coalesce(Property.ward_manual, Property.ward)
        pv = func.coalesce(Property.province_manual, Property.province)
        return [(n, c) for n, c in s.execute(select(w, func.count()).where(pv == province, w.is_not(None))
                                             .group_by(w).order_by(w))]

    @app.get("/api/wards")
    def api_wards(request: Request, province: str = ""):
        with repo.session() as s:
            current_user(request, s)
            return JSONResponse([{"name": n, "count": c} for n, c in _wards(s, province)])

    # ------------------------------------------------------------------ chi tiết
    def _get_prop(s, pid: int) -> Property:
        p = s.get(Property, pid)
        if not p:
            raise HTTPException(404, "Không tìm thấy tài sản")
        return p

    syncing: set[int] = set()

    def _sync_bg(pid: int) -> None:
        try:
            with repo.Session.begin() as s2:
                if (p2 := s2.get(Property, pid)) is not None:
                    sync_source_docs(s2, p2, settings)
        except Exception as e:  # noqa: BLE001  (mạng lỗi không ảnh hưởng người dùng)
            log.warning("Không lấy được tài liệu nguồn #%s: %r", pid, e)
        finally:
            syncing.discard(pid)

    @app.get("/p/{pid}", response_class=HTMLResponse)
    def detail(request: Request, pid: int, bg: BackgroundTasks, edit: int = 0):
        with repo.session() as s:
            user = current_user(request, s)
            p = _get_prop(s, pid)
            docs_pending = sync_docs and needs_sync(s, p)
            if docs_pending and pid not in syncing:   # lấy tài liệu gốc ở nền, trang hiển thị ngay
                syncing.add(pid)
                bg.add_task(_sync_bg, pid)
            links = s.execute(select(PropertyNotice, NoticeRow).join(NoticeRow, NoticeRow.id == PropertyNotice.notice_id)
                              .where(PropertyNotice.property_id == pid)
                              .order_by(PropertyNotice.session_no, NoticeRow.source)).all()
            # gộp các thông báo trùng của cùng một phiên (dgts hay đăng lại) thành 1 dòng
            sessions: list[dict] = []
            for pn, n in links:
                if sessions and sessions[-1]["no"] == pn.session_no and (
                        sessions[-1]["n"].starting_price is None or n.starting_price is None
                        or sessions[-1]["n"].starting_price == n.starting_price):
                    sessions[-1]["dups"].append((pn, n))
                    if sessions[-1]["n"].starting_price is None and n.starting_price:
                        sessions[-1]["n"] = n
                    continue
                sessions.append({"no": pn.session_no, "pn": pn, "n": n, "dups": []})
            latest = s.get(NoticeRow, p.latest_notice_id) if p.latest_notice_id else None
            assets = s.scalars(select(AssetRow).where(AssetRow.notice_id == p.latest_notice_id)).all() if latest else []
            files = s.scalars(select(PropertyFile).where(PropertyFile.property_id == pid)
                              .order_by(PropertyFile.folder, PropertyFile.uploaded_at.desc())).all()
            folders: dict[str, list[PropertyFile]] = {}
            for fl in files:
                folders.setdefault(fl.folder, []).append(fl)
            users = {u.id: u for u in s.scalars(select(User))}
            views = s.execute(select(FileView, PropertyFile).join(PropertyFile, PropertyFile.id == FileView.file_id)
                              .where(FileView.property_id == pid).order_by(FileView.viewed_at.desc()).limit(100)).all()
            comments = s.scalars(select(Comment).where(Comment.property_id == pid, Comment.deleted.is_(False))
                                 .order_by(Comment.created_at.desc())).all()
            tasks = s.scalars(select(Task).where(Task.property_id == pid).order_by(Task.status, Task.due_date)).all()
            acts = s.scalars(select(Activity).where(Activity.property_id == pid).order_by(Activity.at.desc()).limit(50)).all()
            ocr_refs = [(n, (n.raw or {}).get("ocr_prices")) for _, n in links if (n.raw or {}).get("ocr_prices")]
            sess_no = {n.id: pn.session_no for pn, n in links}
            my_cart = s.scalar(select(CartItem).where(CartItem.user_id == user.id, CartItem.property_id == pid))
            # giỏ của tài khoản khác: CHỈ quản trị được thấy
            cart_others = s.scalars(select(CartItem).where(CartItem.property_id == pid, CartItem.user_id != user.id)
                                    .order_by(CartItem.added_at)).all() if user.role == "admin" else []
            saved = sorted(s.scalars(select(NoticeFile).where(NoticeFile.notice_id.in_(list(sess_no)))).all(),
                           key=lambda f: (-sess_no.get(f.notice_id, 0), f.filename))
            return render(request, "detail.html", user, p=p, links=links, sessions=sessions, ocr_refs=ocr_refs, latest=latest, assets=assets,
                          folders=folders, users=users, views=views, comments=comments, tasks=tasks, acts=acts,
                          edit=edit, now=datetime.now(), today=date.today(), docs_pending=docs_pending,
                          saved=saved, sess_no=sess_no, METHODS=DOC_METHODS,
                          my_cart=my_cart, cart_others=cart_others)

    @app.post("/p/{pid}/fields")
    async def save_fields(request: Request, pid: int):
        form = await request.form()
        check_csrf(request, form.get("csrf"))
        with repo.Session.begin() as s:
            user = current_user(request, s)
            p = _get_prop(s, pid)
            changes = []
            for name, label in EDITABLE.items():
                if name not in form:
                    continue                      # trường không gửi lên -> giữ nguyên
                raw = (form.get(name) or "").strip()
                col = f"{name}_manual"
                typ = Property.__table__.columns[col].type.python_type
                if raw == "":
                    val = None
                elif name in MONEY_FIELDS:
                    val = parse_vnd(raw)          # "5.373.459.000", "5,37 tỷ", "850 triệu"
                    if not val:
                        continue
                elif typ is float:
                    val = parse_number(raw)       # "81,5" | "1.036,5" | "76.4"
                    if val is None:
                        continue
                else:
                    val = raw[:500]
                if getattr(p, col) != val:
                    changes.append(f"{label}: {fmt.plain(getattr(p, col))} → {fmt.plain(val)}")
                    setattr(p, col, val)
            if changes:
                p.recompute_discount()
                log_act(s, pid, user, "edit", "; ".join(changes))
        return back(f"/p/{pid}")

    @app.post("/p/{pid}/priority")
    def set_priority(request: Request, pid: int, csrf: str = Form(""), priority: int = Form(...)):
        check_csrf(request, csrf)
        with repo.Session.begin() as s:
            user = current_user(request, s)
            p = _get_prop(s, pid)
            if priority in PRIORITIES and p.priority != priority:
                log_act(s, pid, user, "priority", f"{PRIORITIES[p.priority or 0]} → {PRIORITIES[priority]}")
                p.priority = priority
        return back(request.headers.get("referer") or f"/p/{pid}")

    @app.post("/p/{pid}/verify")
    def toggle_verify(request: Request, pid: int, csrf: str = Form("")):
        check_csrf(request, csrf)
        with repo.Session.begin() as s:
            user = current_user(request, s)
            p = _get_prop(s, pid)
            p.verified = not p.verified
            p.verified_by, p.verified_at = (user.id, datetime.now()) if p.verified else (None, None)
            log_act(s, pid, user, "verify", "Xác thực thông tin" if p.verified else "Bỏ xác thực")
        return back(f"/p/{pid}")

    # ------------------------------------------------------------------ nhận xét
    @app.post("/p/{pid}/comments")
    def add_comment(request: Request, pid: int, csrf: str = Form(""), body: str = Form(...)):
        check_csrf(request, csrf)
        with repo.Session.begin() as s:
            user = current_user(request, s)
            _get_prop(s, pid)
            if body.strip():
                s.add(Comment(property_id=pid, user_id=user.id, body=body.strip()[:10000]))
        return back(f"/p/{pid}#nhan-xet")

    @app.post("/comments/{cid}/edit")
    def edit_comment(request: Request, cid: int, csrf: str = Form(""), body: str = Form(...)):
        check_csrf(request, csrf)
        with repo.Session.begin() as s:
            user = current_user(request, s)
            c = s.get(Comment, cid)
            if not c or (c.user_id != user.id):
                raise HTTPException(403, "Chỉ sửa được nhận xét của mình")
            c.body, c.updated_at = body.strip()[:10000], datetime.now()
            pid = c.property_id
        return back(f"/p/{pid}#nhan-xet")

    @app.post("/comments/{cid}/delete")
    def delete_comment(request: Request, cid: int, csrf: str = Form("")):
        check_csrf(request, csrf)
        with repo.Session.begin() as s:
            user = current_user(request, s)
            c = s.get(Comment, cid)
            if not c or (c.user_id != user.id and user.role != "admin"):
                raise HTTPException(403, "Không có quyền xoá")
            c.deleted = True
            pid = c.property_id
            log_act(s, pid, user, "comment_delete", f"Xoá nhận xét #{cid}")
        return back(f"/p/{pid}#nhan-xet")

    # ------------------------------------------------------------------ file
    @app.post("/p/{pid}/files")
    async def upload(request: Request, pid: int, csrf: str = Form(""), folder: str = Form(""),
                     new_folder: str = Form(""), files: list[UploadFile] = File(...)):
        check_csrf(request, csrf)
        folder_name = (new_folder.strip() or folder.strip() or "")[:64]
        with repo.Session.begin() as s:
            user = current_user(request, s)
            _get_prop(s, pid)
            d = media_root / str(pid)
            d.mkdir(parents=True, exist_ok=True)
            names = []
            for up in files:
                if not up.filename:
                    continue
                safe = re.sub(r"[^\w.\-]+", "_", Path(up.filename).name)[-120:]
                rel = f"{pid}/{uuid.uuid4().hex[:12]}_{safe}"
                size = 0
                with (media_root / rel).open("wb") as out:
                    while chunk := await up.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_UPLOAD:
                            out.close()
                            (media_root / rel).unlink(missing_ok=True)
                            raise HTTPException(413, f"{up.filename}: vượt quá 1GB")
                        out.write(chunk)
                kind = kind_of(up.content_type, up.filename)
                fname = folder_name or {"image": "Hình ảnh", "video": "Video"}.get(kind, "Tài liệu")
                s.add(PropertyFile(property_id=pid, folder=fname, kind=kind, filename=up.filename[:255],
                                   stored_path=rel, size=size, mime=up.content_type, uploaded_by=user.id))
                names.append(up.filename)
            if names:
                log_act(s, pid, user, "upload", f"Tải lên {len(names)} file: " + ", ".join(names)[:500])
        return back(f"/p/{pid}#tai-lieu")

    @app.get("/files/{fid}")
    def get_file(request: Request, fid: int, download: int = 0, thumb: int = 0):
        with repo.Session.begin() as s:
            user = current_user(request, s)
            fl = s.get(PropertyFile, fid)
            if not fl:
                raise HTTPException(404)
            if not thumb:  # ảnh thu nhỏ trong thư viện không tính là "xem"
                s.add(FileView(file_id=fid, property_id=fl.property_id, user_id=user.id,
                               action="download" if download else "view"))
            stored, url, name, mime = fl.stored_path, fl.source_url, fl.filename, fl.mime
        if url:
            with repo.session() as s:      # đã lưu bản sao trên máy chủ -> mở bản sao (nguồn có thể gỡ file)
                nf = s.scalar(select(NoticeFile).where(NoticeFile.url == url, NoticeFile.path.is_not(None)).limit(1))
            if nf is None or not (local := _saved_path(nf.path)):
                return RedirectResponse(url, status_code=302)
            return FileResponse(local, media_type=mimetypes.guess_type(nf.filename)[0], filename=nf.filename,
                                content_disposition_type="attachment" if download else "inline")
        path = (media_root / stored).resolve()
        if media_root.resolve() not in path.parents or not path.exists():
            raise HTTPException(404, "File không còn trên máy chủ")
        return FileResponse(path, media_type=mime or mimetypes.guess_type(name)[0],
                            filename=name, content_disposition_type="attachment" if download else "inline")

    def _saved_path(rel: str) -> Path | None:
        root = settings.path(settings.data_dir).resolve() / "files"
        path = (settings.path(settings.data_dir) / rel).resolve()
        return path if root in path.parents and path.exists() else None

    @app.get("/nf/{nfid}")
    def saved_file(request: Request, nfid: int, download: int = 0, txt: int = 0):
        """File đính kèm đã tải về từ nguồn và lưu trên máy chủ (txt=1: chữ đọc được từ file)."""
        with repo.session() as s:
            current_user(request, s)
            nf = s.get(NoticeFile, nfid)
            if not nf or not nf.path:
                raise HTTPException(404)
            rel, name = nf.path + (".txt" if txt else ""), nf.filename + (".txt" if txt else "")
        if not (path := _saved_path(rel)):
            raise HTTPException(404, "File không còn trên máy chủ")
        mime = "text/plain; charset=utf-8" if txt else mimetypes.guess_type(name)[0]
        return FileResponse(path, media_type=mime, filename=name,
                            content_disposition_type="attachment" if download else "inline")

    @app.post("/files/{fid}/delete")
    def delete_file(request: Request, fid: int, csrf: str = Form("")):
        check_csrf(request, csrf)
        with repo.Session.begin() as s:
            user = current_user(request, s)
            fl = s.get(PropertyFile, fid)
            if not fl or (fl.uploaded_by != user.id and user.role != "admin"):
                raise HTTPException(403, "Chỉ người tải lên hoặc quản trị viên được xoá")
            pid = fl.property_id
            if fl.stored_path:
                (media_root / fl.stored_path).unlink(missing_ok=True)
            log_act(s, pid, user, "file_delete", f"Xoá file {fl.filename}")
            s.delete(fl)
        return back(f"/p/{pid}#tai-lieu")

    # ------------------------------------------------------------------ giao việc
    @app.post("/p/{pid}/tasks")
    def add_task(request: Request, pid: int, csrf: str = Form(""), title: str = Form(...), assignee_id: int = Form(...),
                 due_date: str = Form(""), description: str = Form("")):
        check_csrf(request, csrf)
        with repo.Session.begin() as s:
            user = current_user(request, s)
            _get_prop(s, pid)
            assignee = s.get(User, assignee_id)
            if not assignee or not assignee.active:
                raise HTTPException(400, "Người nhận không hợp lệ")
            due = datetime.strptime(due_date, "%Y-%m-%d").date() if due_date else None
            s.add(Task(property_id=pid, title=title.strip()[:500], description=description.strip() or None,
                       assigner_id=user.id, assignee_id=assignee_id, due_date=due))
            log_act(s, pid, user, "task", f"Giao việc '{title.strip()[:80]}' cho {assignee.full_name}")
        return back(f"/p/{pid}#giao-viec")

    @app.post("/tasks/{tid}/status")
    def task_status(request: Request, tid: int, csrf: str = Form(""), status: str = Form(...)):
        check_csrf(request, csrf)
        with repo.Session.begin() as s:
            user = current_user(request, s)
            t = s.get(Task, tid)
            if not t or status not in TASK_STATUS:
                raise HTTPException(400)
            if user.id not in (t.assignee_id, t.assigner_id) and user.role != "admin":
                raise HTTPException(403, "Chỉ người giao / người nhận được cập nhật")
            if t.status != status:
                log_act(s, t.property_id, user, "task_status", f"Việc '{t.title[:60]}': {TASK_STATUS[t.status]} → {TASK_STATUS[status]}")
                t.status = status
                t.completed_at = datetime.now() if status == "xong" else None
        return back(request.headers.get("referer") or "/tasks")

    @app.get("/tasks", response_class=HTMLResponse)
    def my_tasks(request: Request, scope: str = "assigned", status: str = "open"):
        with repo.session() as s:
            user = current_user(request, s)
            q = select(Task)
            q = q.where(Task.assigner_id == user.id) if scope == "created" else \
                q if scope == "all" and user.role == "admin" else q.where(Task.assignee_id == user.id)
            if status == "open":
                q = q.where(Task.status.in_(["moi", "dang_lam"]))
            elif status in TASK_STATUS:
                q = q.where(Task.status == status)
            tasks = s.scalars(q.order_by(Task.due_date.is_(None), Task.due_date, Task.created_at.desc())).all()
            return render(request, "tasks.html", user, tasks=tasks, scope=scope, status=status, today=date.today())

    # ------------------------------------------------------------------ giỏ hàng (riêng từng tài khoản)
    @app.post("/p/{pid}/cart")
    def cart_toggle(request: Request, pid: int, csrf: str = Form(""), action: str = Form("add"), note: str = Form("")):
        check_csrf(request, csrf)
        with repo.Session.begin() as s:
            user = current_user(request, s)
            _get_prop(s, pid)
            it = s.scalar(select(CartItem).where(CartItem.user_id == user.id, CartItem.property_id == pid))
            if action == "remove":
                if it:
                    s.delete(it)
            elif it is None:
                s.add(CartItem(user_id=user.id, property_id=pid, note=note.strip()[:1000] or None))
            elif action == "note":
                it.note = note.strip()[:1000] or None
        return back(request.headers.get("referer") or f"/p/{pid}")

    @app.post("/cart/{cid}/remove")
    def cart_remove(request: Request, cid: int, csrf: str = Form("")):
        """Bỏ khỏi giỏ: chủ giỏ, hoặc quản trị."""
        check_csrf(request, csrf)
        with repo.Session.begin() as s:
            user = current_user(request, s)
            it = s.get(CartItem, cid)
            if not it or (it.user_id != user.id and user.role != "admin"):
                raise HTTPException(404)
            s.delete(it)
        return back(request.headers.get("referer") or "/cart")

    @app.get("/cart", response_class=HTMLResponse)
    def cart_page(request: Request, u: str = ""):
        """Thành viên: chỉ giỏ của mình. Quản trị: giỏ của mình, của 1 tài khoản (u=<id>) hoặc tất cả (u=all)."""
        with repo.session() as s:
            user = current_user(request, s)
            q = select(CartItem).join(Property, Property.id == CartItem.property_id)
            owners: list[tuple[User, int]] = []
            if user.role == "admin":
                owners = s.execute(select(User, func.count(CartItem.id)).join(CartItem, CartItem.user_id == User.id)
                                   .group_by(User.id).order_by(User.full_name)).all()
                if u == "all":
                    pass
                elif u.isdigit():
                    q = q.where(CartItem.user_id == int(u))
                else:
                    q = q.where(CartItem.user_id == user.id)
            else:
                u = ""
                q = q.where(CartItem.user_id == user.id)
            items = s.scalars(q.order_by(CartItem.user_id != user.id, CartItem.user_id,
                                         Property.registration_end.is_(None), Property.registration_end)).all()
            return render(request, "cart.html", user, items=items, owners=owners, u=u, now=datetime.now())

    # ------------------------------------------------------------------ gộp / tách phiên
    @app.post("/p/{pid}/detach/{nid}")
    def detach(request: Request, pid: int, nid: int, csrf: str = Form("")):
        """Tách 1 thông báo (gộp nhầm) thành tài sản riêng; linker sẽ giữ nguyên lựa chọn này."""
        check_csrf(request, csrf)
        from ..realestate.linker import rebuild
        with repo.Session.begin() as s:
            user = current_user(request, s)
            p = _get_prop(s, pid)
            pn = s.scalar(select(PropertyNotice).where(PropertyNotice.notice_id == nid, PropertyNotice.property_id == pid))
            if not pn:
                raise HTTPException(404)
            for other in s.scalars(select(PropertyNotice).where(PropertyNotice.property_id == pid)):
                other.manual = True   # khoá các thông báo còn lại vào tài sản hiện tại
                if other.link_source in (None, "auto"):
                    other.link_source = "manual"
            newp = Property(title=p.title)
            s.add(newp)
            s.flush()
            pn.property_id, pn.manual, pn.link_source = newp.id, True, "manual"
            log_act(s, pid, user, "detach", f"Tách thông báo #{nid} thành tài sản #{newp.id}")
            new_id = newp.id
        rebuild(repo)
        return back(f"/p/{new_id}")

    @app.post("/p/{pid}/merge")
    def merge(request: Request, pid: int, csrf: str = Form(""), target: int = Form(...)):
        """Gộp tài sản này vào tài sản #target (cùng một BĐS đấu giá lại)."""
        check_csrf(request, csrf)
        from ..realestate.linker import rebuild
        with repo.Session.begin() as s:
            user = current_user(request, s)
            _get_prop(s, pid)
            _get_prop(s, target)
            if target == pid:
                return back(f"/p/{pid}")
            for pn in s.scalars(select(PropertyNotice).where(PropertyNotice.property_id.in_([pid, target]))):
                pn.property_id, pn.manual = target, True
                if pn.link_source in (None, "auto"):
                    pn.link_source = "manual"
            log_act(s, target, user, "merge", f"Gộp tài sản #{pid} vào #{target}")
        rebuild(repo)   # chuyển nhận xét/file/việc của #pid sang #target, tính lại phiên & giá
        return back(f"/p/{target}")

    # ------------------------------------------------------------------ xuất Excel theo bộ lọc
    @app.get("/export.xlsx")
    def export_xlsx(request: Request):
        from .export import properties_xlsx
        f = Filters.from_request(request.query_params)
        with repo.session() as s:
            user = current_user(request, s)
            items = s.scalars(build_query(f, user.id).limit(EXPORT_MAX)).all()
            data = properties_xlsx(items, base_url=str(request.base_url).rstrip("/"))
            log_act(s, None, user, "export", f"Xuất Excel {len(items)} tài sản")
            s.commit()
        name = f"tai_san_dau_gia_{datetime.now():%Y%m%d_%H%M}.xlsx"
        return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{name}"'})

    # ------------------------------------------------------------------ trang hệ thống (quản trị)
    @app.get("/admin/system", response_class=HTMLResponse)
    def system_page(request: Request, msg: str = ""):
        from .system import system_status
        with repo.session() as s:
            user = _admin(request, s)
            st = system_status(s, settings, media_root)
            return render(request, "system.html", user, st=st, msg=msg)

    @app.post("/admin/system/telegram-test")
    def system_telegram_test(request: Request, csrf: str = Form("")):
        check_csrf(request, csrf)
        from ..notify import send
        with repo.session() as s:
            user = _admin(request, s)
        ok = send(settings, f"🔔 Tin thử từ trang Hệ thống (người gửi: {user.full_name})")
        return back("/admin/system?msg=" + ("Đã gửi tin thử Telegram" if ok else "Gửi lỗi hoặc chưa cấu hình Telegram"))

    # ------------------------------------------------------------------ quản trị tài khoản
    def _admin(request, s) -> User:
        u = current_user(request, s)
        if u.role != "admin":
            raise HTTPException(403, "Chỉ quản trị viên")
        return u

    @app.get("/admin/users", response_class=HTMLResponse)
    def users_page(request: Request, msg: str = ""):
        with repo.session() as s:
            user = _admin(request, s)
            return render(request, "users.html", user, users=s.scalars(select(User).order_by(User.username)).all(), msg=msg)

    @app.post("/admin/users")
    def users_create(request: Request, csrf: str = Form(""), username: str = Form(...), full_name: str = Form(...),
                     password: str = Form(...), role: str = Form("member")):
        check_csrf(request, csrf)
        uname = username.strip().lower()
        if not re.fullmatch(r"[a-z0-9._-]{3,64}", uname) or len(password) < 8:
            return back("/admin/users?msg=Tên đăng nhập 3-64 ký tự [a-z0-9._-], mật khẩu ≥ 8 ký tự")
        with repo.Session.begin() as s:
            _admin(request, s)
            if s.scalar(select(User).where(User.username == uname)):
                return back("/admin/users?msg=Tên đăng nhập đã tồn tại")
            s.add(User(username=uname, full_name=full_name.strip(), password_hash=hash_password(password),
                       role="admin" if role == "admin" else "member"))
        return back(f"/admin/users?msg=Đã tạo tài khoản {uname}")

    @app.post("/admin/users/{uid}")
    def users_update(request: Request, uid: int, csrf: str = Form(""), role: str = Form("member"),
                     active: str = Form(""), password: str = Form("")):
        check_csrf(request, csrf)
        with repo.Session.begin() as s:
            me = _admin(request, s)
            u = s.get(User, uid)
            if not u:
                raise HTTPException(404)
            if u.id != me.id:   # không tự hạ quyền / khoá chính mình
                u.role = "admin" if role == "admin" else "member"
                u.active = active == "1"
            if password:
                if len(password) < 8:
                    return back("/admin/users?msg=Mật khẩu ≥ 8 ký tự")
                u.password_hash = hash_password(password)
        return back(f"/admin/users?msg=Đã cập nhật {u.username}")

    return app
