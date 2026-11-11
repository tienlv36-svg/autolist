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

from .config import DEFAULT_CRON, DEFAULT_FILL_CRON, Settings
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
def run_lock(settings: Settings, wait_seconds: float = 0) -> Iterator[None]:
    """Khoá dùng chung với deploy/first-load.sh (data/.run.lock): không cho 2 lượt ghi CSDL cùng lúc.
    wait_seconds > 0: chờ tối đa chừng đó giây nếu đang có lượt khác chạy."""
    p = settings.path("data/.run.lock")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w") as f:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as e:
                if time.monotonic() >= deadline:
                    raise AlreadyRunning("Đang có tiến trình thu thập khác chạy (vd first-load.sh)") from e
                time.sleep(15)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def run_once(settings: Settings, repo: Repository) -> dict[str, Any]:
    """Lượt chính (2:00): crawl tin mới mọi nguồn -> gắn loại TS chính thức -> OCR giá (nếu bật) -> tin trùng
    -> gom phiên -> lấy giá tin BĐS còn thiếu -> quét lịch sử giá -> đọc file đính kèm (tin mới trước) -> bộ lọc
    đã lưu + nhắc hạn -> sao lưu -> báo Telegram (kèm kết quả các lượt lấp dữ liệu trong ngày)."""
    t0 = time.time()
    started = datetime.now()
    report: dict[str, Any] = {"sources": {}, "steps": {}, "warnings": [], "started": started}
    try:
        with run_lock(settings, wait_seconds=20 * 60):     # lượt lấp dữ liệu đang dở -> chờ nó dừng
            _run_steps(settings, repo, report)
            report["backup"] = run_backup(settings)      # sao lưu ngay sau mỗi lượt quét
    except AlreadyRunning as e:
        report["warnings"].append(str(e) + " – bỏ qua lượt này")
        log.warning("%s", e)
    report["minutes"] = round((time.time() - t0) / 60, 1)
    report["fill"] = _pop_fill_stats(settings)
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
        ("docs", lambda: _docs_then_rebuild(settings, repo, float(sch.get("docs_minutes", 180)))),  # file đính kèm
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


def _docs_then_rebuild(settings: Settings, repo: Repository, minutes: float):
    from .attachments import fetch_docs
    from .realestate.linker import rebuild
    sch = settings.schedule
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


def _alerts(settings: Settings, repo: Repository):
    from .alerts import run_alerts
    return run_alerts(settings, repo)


# ---------------------------------------------------------------- lấp dữ liệu còn thiếu (ngoài giờ quét chính)
FILL_STATS = "data/.fill_stats.json"


def _main_hour(settings: Settings) -> tuple[int, int]:
    """Giờ:phút của lượt chính (từ cron dạng 'M H * * *'); mặc định 2:00."""
    try:
        m, h = settings.schedule.get("cron", DEFAULT_CRON).split()[:2]
        return int(h.split(",")[0]), int(m.split(",")[0])
    except ValueError:
        return 2, 0


def run_fill(settings: Settings, repo: Repository, now: datetime | None = None) -> dict[str, Any] | None:
    """Lượt lấp dữ liệu: lấy giá tin BĐS còn thiếu + đọc file đính kèm (tài sản còn hạn thiếu thông tin trước, rồi tài
    sản năm 2026). Dừng trước lượt chính 15 phút. Đang có lượt khác chạy -> bỏ qua. Không gửi Telegram (cộng dồn vào
    báo cáo lượt chính)."""
    import json
    sch = settings.schedule
    now = now or datetime.now()
    h, m = _main_hour(settings)
    stop_at = now.replace(hour=h, minute=m, second=0, microsecond=0) - timedelta(minutes=15)
    if stop_at <= now:
        stop_at += timedelta(days=1)
    budget = min(float(sch.get("fill_minutes", 110)), (stop_at - now).total_seconds() / 60)
    if budget < 10:
        return None
    t0 = time.time()
    res: dict[str, Any] = {"enriched": 0, "docs_notices": 0, "docs_with_info": 0, "ocr_files": 0}
    try:
        with run_lock(settings):
            res["enriched"] = _enrich_re(settings, repo, int(sch.get("enrich_limit", 2000)))
            left = budget - (time.time() - t0) / 60
            if left > 5:
                st = _docs_then_rebuild(settings, repo, left)
                if st:
                    res.update(docs_notices=st.notices, docs_with_info=st.with_info, ocr_files=st.ocr_files)
            if res["enriched"] or res["docs_notices"]:
                bk = last_backup(settings)
                try:
                    old = not bk or datetime.now() - datetime.strptime(bk["at"], "%Y-%m-%d %H:%M:%S") > timedelta(hours=6)
                except (KeyError, ValueError):
                    old = True
                if old:
                    res["backup"] = run_backup(settings)
    except AlreadyRunning:
        log.info("Lấp dữ liệu: đang có lượt khác chạy – bỏ qua")
        return None
    p = settings.path(FILL_STATS)
    try:
        acc = json.loads(p.read_text()) if p.exists() else {}
    except (OSError, ValueError):
        acc = {}
    for k in ("enriched", "docs_notices", "docs_with_info", "ocr_files"):
        acc[k] = int(acc.get(k, 0)) + int(res[k] or 0)
    acc["runs"] = int(acc.get("runs", 0)) + 1
    p.write_text(json.dumps(acc))
    log.info("Lấp dữ liệu xong (%.0f phút): %s", (time.time() - t0) / 60, res)
    return res


def _pop_fill_stats(settings: Settings) -> dict[str, int] | None:
    import json
    p = settings.path(FILL_STATS)
    try:
        acc = json.loads(p.read_text()) if p.exists() else None
        p.unlink(missing_ok=True)
        return acc
    except (OSError, ValueError):
        return None


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
    al = (steps.get("alerts") or {}).get("result")
    if al is not None and (getattr(al, "search_msgs", 0) or getattr(al, "reminder_msgs", 0)):
        lines.append(f"• Đã gửi {num(al.search_msgs)} tin bộ lọc, {num(al.reminder_msgs)} tin nhắc hạn (Telegram cá nhân)")
    fl = report.get("fill")
    if fl and fl.get("runs"):
        lines.append(f"• Lấp dữ liệu trong ngày ({num(fl['runs'])} lượt): bổ sung giá {num(fl.get('enriched'))} tin, "
                     f"đọc file {num(fl.get('docs_notices'))} tin (OCR {num(fl.get('ocr_files'))} file), "
                     f"có số liệu {num(fl.get('docs_with_info'))} tin")
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
    fill_cron = settings.schedule.get("fill_cron", DEFAULT_FILL_CRON)
    if fill_cron:
        sched.add_job(run_fill, CronTrigger.from_crontab(fill_cron, timezone="Asia/Ho_Chi_Minh"),
                      args=[settings, repo], max_instances=1, coalesce=True, id="fill")
    log.info("Lịch quét tin mới: %s; lấp dữ liệu còn thiếu: %s (Asia/Ho_Chi_Minh). Ctrl+C để dừng.", cron, fill_cron)
    if settings.schedule.get("run_on_start", False):
        run_once(settings, repo)
    job = sched.get_job("crawl_all")
    log.info("Lượt chạy tiếp theo: %s", getattr(job, "next_run_time", None)
             or job.trigger.get_next_fire_time(None, datetime.now(job.trigger.timezone)))
    sched.start()
