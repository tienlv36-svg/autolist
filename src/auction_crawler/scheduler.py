"""Lập lịch chạy định kỳ bằng APScheduler + báo cáo qua Telegram."""
from __future__ import annotations

import fcntl
import logging
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Any, Iterator

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Settings
from .notify import disk_usage_pct, esc, send
from .pipeline import crawl_source
from .sources import all_sources
from .storage import Repository

log = logging.getLogger(__name__)
DISK_WARN_PCT = 85


def num(n: int | None) -> str:
    """1234567 -> '1.234.567' (kiểu Việt Nam)."""
    return f"{n or 0:,}".replace(",", ".")


class AlreadyRunning(RuntimeError):
    pass


@contextmanager
def run_lock(settings: Settings) -> Iterator[None]:
    """Khoá dùng chung với deploy/first-load.sh (data/.run.lock): không cho 2 lượt ghi CSDL cùng lúc."""
    p = settings.path("data/.run.lock")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise AlreadyRunning("Đang có tiến trình thu thập khác chạy (vd first-load.sh)") from e
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def run_once(settings: Settings, repo: Repository) -> dict[str, Any]:
    """Một lượt đầy đủ: crawl tăng dần mọi nguồn -> gắn loại TS chính thức (dgts, 14 ngày gần nhất)
    -> OCR giá (nếu bật) -> đánh dấu tin trùng giữa các nguồn -> dựng lại tài sản BĐS -> quét lịch sử giá
    -> tải + đọc file đính kèm -> sao lưu -> báo Telegram."""
    t0 = time.time()
    started = datetime.now()
    report: dict[str, Any] = {"sources": {}, "steps": {}, "warnings": [], "started": started}
    try:
        with run_lock(settings):
            _run_steps(settings, repo, report)
            report["backup"] = run_backup(settings)      # sao lưu ngay sau mỗi lượt quét
    except AlreadyRunning as e:
        report["warnings"].append(str(e) + " – bỏ qua lượt này")
        log.warning("%s", e)
    report["minutes"] = round((time.time() - t0) / 60, 1)
    report["text"] = format_report(settings, repo, report)
    send(settings, report["text"])
    return report


def _run_steps(settings: Settings, repo: Repository, report: dict[str, Any]) -> None:
    from .dedupe import find_duplicates
    from .pipeline import ocr_prices, tag_official_types
    from .realestate.linker import rebuild

    sch = settings.schedule
    for name in all_sources():
        try:
            st = crawl_source(name, settings, repo)
            report["sources"][name] = {"ok": True, "found": st.found, "inserted": st.inserted,
                                       "updated": st.updated, "errors": st.errors}
            log.info("[%s] xong: mới=%s cập nhật=%s lỗi=%s", name, st.inserted, st.updated, st.errors)
            if st.found == 0:
                report["warnings"].append(f"{name}: không đọc được tin nào – website có thể đã đổi cấu trúc")
        except Exception as e:  # noqa: BLE001
            log.exception("[%s] lỗi", name)
            report["sources"][name] = {"ok": False, "error": repr(e)[:300]}
    steps = [
        ("tag-types", lambda: tag_official_types(settings, repo, since=date.today() - timedelta(days=14))
         if "dgts" in all_sources() else None),
        ("ocr-prices", lambda: ocr_prices("taisancong", settings, repo, limit=int(sch.get("ocr_limit", 0)))
         if int(sch.get("ocr_limit", 0)) > 0 and "taisancong" in all_sources() else None),
        ("dedupe", lambda: find_duplicates(repo)),
        ("re-build", lambda: rebuild(repo)),          # tài sản BĐS: gom phiên, giá, % giảm
        ("enrich-re", lambda: _enrich_re(settings, repo, int(sch.get("enrich_limit", 2000)))),  # tin BĐS cũ chưa có giá
        ("history", lambda: _history_then_rebuild(settings, repo, int(sch.get("history_limit", 500)))),
        ("docs", lambda: _docs_then_rebuild(settings, repo)),   # tải + đọc file đính kèm, ưu tiên số liệu tài liệu
        ("suggest", lambda: _suggest(repo)),                     # gợi ý gộp phiên (người dùng duyệt trên web)
        ("alerts", lambda: _alerts(settings, repo)),             # bộ lọc đã lưu + nhắc hạn (Telegram cá nhân)
    ]
    for label, fn in steps:
        try:
            res = fn()
            report["steps"][label] = {"ok": True, "result": res}
        except Exception as e:  # noqa: BLE001
            log.exception("bước %s lỗi", label)
            report["steps"][label] = {"ok": False, "error": repr(e)[:300]}


def _history_then_rebuild(settings: Settings, repo: Repository, limit: int):
    """Quét lịch sử giá cho tài sản còn hạn đăng ký; tìm thấy phiên cũ thì gom phiên lại."""
    from .realestate.history import scan_open_properties
    from .realestate.linker import rebuild
    if limit <= 0:
        return None
    st = scan_open_properties(settings, repo, limit=limit)
    if st.found_notices:
        rebuild(repo)
    return st


def _docs_then_rebuild(settings: Settings, repo: Repository):
    from .attachments import fetch_docs
    from .realestate.linker import rebuild
    sch = settings.schedule
    minutes = float(sch.get("docs_minutes", 300))
    if minutes <= 0:
        return None
    st = fetch_docs(settings, repo, minutes=minutes, max_disk_pct=float(sch.get("docs_max_disk_pct", 85)),
                    ocr_max_pages=int(sch.get("ocr_max_pages", 8)), workers=int(sch.get("docs_workers", 0)),
                    min_days=float(sch.get("docs_min_days", 2)))
    if st.notices:
        rebuild(repo)
    return st


def _enrich_re(settings: Settings, repo: Repository, limit: int) -> int:
    """Lấy chi tiết (giá, tiền đặt trước…) cho tin BĐS cũ chưa có chi tiết, rồi gom phiên lại nếu có bổ sung."""
    from .pipeline import enrich_missing
    from .realestate.linker import rebuild
    if limit <= 0:
        return 0
    n = 0
    for name in all_sources():
        n += enrich_missing(name, settings, repo, limit=limit, realestate=True).updated
    if n:
        rebuild(repo)
    return n


def _suggest(repo: Repository) -> int:
    from .realestate.suggest import compute
    return compute(repo)


def _alerts(settings: Settings, repo: Repository):
    from .alerts import run_alerts
    return run_alerts(settings, repo)


def run_backup(settings: Settings) -> dict[str, Any]:
    """Chạy deploy/backup.sh (CSDL + file tải lên + cấu hình; đẩy Google Drive nếu đã cấu hình)."""
    import subprocess
    script = settings.path("deploy/backup.sh")
    if not script.exists():
        return {"ok": False, "error": "không thấy deploy/backup.sh"}
    try:
        r = subprocess.run(["bash", str(script)], capture_output=True, text=True, timeout=3 * 3600)
        log.info("Sao lưu: %s", (r.stdout or r.stderr).strip()[-300:])
        return {"ok": r.returncode == 0, "error": None if r.returncode == 0 else (r.stderr or r.stdout)[-300:]}
    except Exception as e:  # noqa: BLE001
        log.exception("sao lưu lỗi")
        return {"ok": False, "error": repr(e)[:300]}


def format_report(settings: Settings, repo: Repository, report: dict[str, Any]) -> str:
    from sqlalchemy import func, select

    from .realestate.db import Property

    srcs, steps, warns = report["sources"], report["steps"], list(report["warnings"])
    failed = [n for n, s in srcs.items() if not s.get("ok")] + [n for n, s in steps.items() if not s.get("ok")]
    try:
        pct = disk_usage_pct(settings.path("data"))
        if pct >= DISK_WARN_PCT:
            warns.append(f"Ổ cứng đã dùng {pct}% – cần dọn bớt hoặc nâng dung lượng")
    except OSError:
        pct = None
    icon = "❌" if failed else ("⚠️" if warns else "✅")
    lines = [f"{icon} <b>Thu thập {report['started']:%H:%M %d/%m}</b> ({report.get('minutes', 0)} phút)"]
    for n, s in srcs.items():
        if s.get("ok"):
            lines.append(f"• {esc(n)}: <b>{num(s['inserted'])}</b> tin mới, {num(s['updated'])} cập nhật"
                         + (f", {s['errors']} lỗi" if s["errors"] else ""))
        else:
            lines.append(f"• {esc(n)}: <b>THẤT BẠI</b> – {esc(s.get('error'))}")
    for n, s in steps.items():
        if not s.get("ok"):
            lines.append(f"• bước {esc(n)}: <b>LỖI</b> – {esc(s.get('error'))}")
    hs = (steps.get("history") or {}).get("result")
    if hs is not None and getattr(hs, "scanned", 0):
        lines.append(f"• Lịch sử giá: quét {num(hs.scanned)} tài sản còn hạn, thêm <b>{num(hs.found_notices)}</b> "
                     f"phiên cũ cho {num(hs.props_updated)} tài sản")
    ds = (steps.get("docs") or {}).get("result")
    if ds is not None and (getattr(ds, "notices", 0) or getattr(ds, "stopped", None)):
        mb = getattr(ds, "bytes", 0) / 1048576
        lines.append(f"• File đính kèm: đọc {num(ds.notices)} tin, lưu {num(ds.files)} file ({mb:.0f} MB, "
                     f"OCR {num(ds.ocr_files)}), có số liệu cho <b>{num(ds.with_info)}</b> tin"
                     + (f"; {esc(ds.details[-1])}" if ds.details else ""))
        if ds.stopped:
            warns.append(f"File đính kèm: {ds.stopped}")
    sg = (steps.get("suggest") or {}).get("result")
    if sg:
        lines.append(f"• Gợi ý gộp phiên mới: <b>{num(sg)}</b> (duyệt trên web: menu Gợi ý gộp)")
    al = (steps.get("alerts") or {}).get("result")
    if al is not None and (getattr(al, "search_msgs", 0) or getattr(al, "reminder_msgs", 0)):
        lines.append(f"• Đã gửi {num(al.search_msgs)} tin bộ lọc, {num(al.reminder_msgs)} tin nhắc hạn (Telegram cá nhân)")
    bkr = report.get("backup")
    if bkr is not None and not bkr.get("ok"):
        warns.append(f"Sao lưu sau lượt quét LỖI: {bkr.get('error')}")
    try:
        with repo.session() as ss:
            total = ss.scalar(select(func.count(Property.id))) or 0
            new = ss.scalar(select(func.count(Property.id)).where(Property.created_at >= report["started"])) or 0
        if srcs:
            lines.append(f"• Tài sản BĐS: {num(total)} (<b>+{num(new)}</b> mới)")
    except Exception:  # noqa: BLE001
        pass
    if pct is not None:
        lines.append(f"• Ổ cứng: {pct}% đã dùng")
    bk = last_backup(settings)
    if bk is None:
        warns.append("Chưa có bản sao lưu nào")
    else:
        where = "VPS + Google Drive" if bk.get("offsite") else "chỉ trên VPS"
        lines.append(f"• Sao lưu gần nhất: {esc(bk.get('at', '?'))} ({esc(bk.get('size', '?'))}, {where})")
        try:
            if datetime.now() - datetime.strptime(bk["at"], "%Y-%m-%d %H:%M:%S") > timedelta(days=2):
                warns.append("Sao lưu gần nhất đã quá 2 ngày – kiểm tra lịch sao lưu")
        except (KeyError, ValueError):
            pass
    lines += [f"⚠️ {esc(w)}" for w in warns]
    return "\n".join(lines)


def last_backup(settings: Settings) -> dict[str, Any] | None:
    import json
    p = settings.path("data/.last_backup.json")
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except (OSError, ValueError):
        return None


def run_scheduler(settings: Settings, repo: Repository, cron: str) -> None:
    sched = BlockingScheduler(timezone="Asia/Ho_Chi_Minh")
    sched.add_job(run_once, CronTrigger.from_crontab(cron, timezone="Asia/Ho_Chi_Minh"),
                  args=[settings, repo], max_instances=1, coalesce=True, id="crawl_all")
    log.info("Lịch: %s (Asia/Ho_Chi_Minh). Ctrl+C để dừng.", cron)
    if settings.schedule.get("run_on_start", False):
        run_once(settings, repo)
    job = sched.get_job("crawl_all")
    log.info("Lượt chạy tiếp theo: %s", getattr(job, "next_run_time", None)
             or job.trigger.get_next_fire_time(None, datetime.now(job.trigger.timezone)))
    sched.start()
