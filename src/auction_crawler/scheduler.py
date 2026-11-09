"""Lập lịch chạy định kỳ bằng APScheduler (có thể thay bằng cron hệ thống / systemd timer)."""
from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import Settings
from .pipeline import crawl_source
from .sources import all_sources
from .storage import Repository

log = logging.getLogger(__name__)


def run_once(settings: Settings, repo: Repository) -> None:
    """Một lượt đầy đủ: crawl tăng dần mọi nguồn -> gắn loại TS chính thức (dgts, 14 ngày gần nhất)
    -> OCR giá (nếu bật) -> đánh dấu tin trùng giữa các nguồn -> dựng lại tài sản BĐS."""
    from datetime import date, timedelta

    from .dedupe import find_duplicates
    from .pipeline import ocr_prices, tag_official_types
    from .realestate.linker import rebuild

    sch = settings.schedule
    for name in all_sources():
        try:
            st = crawl_source(name, settings, repo)
            log.info("[%s] xong: mới=%s cập nhật=%s lỗi=%s", name, st.inserted, st.updated, st.errors)
        except Exception:
            log.exception("[%s] lỗi", name)
    steps = [
        ("tag-types", lambda: tag_official_types(settings, repo, since=date.today() - timedelta(days=14))
         if "dgts" in all_sources() else None),
        ("ocr-prices", lambda: ocr_prices("taisancong", settings, repo, limit=int(sch.get("ocr_limit", 0)))
         if int(sch.get("ocr_limit", 0)) > 0 and "taisancong" in all_sources() else None),
        ("dedupe", lambda: find_duplicates(repo)),
        ("re-build", lambda: rebuild(repo)),          # tài sản BĐS: gom phiên, giá, % giảm
    ]
    for label, fn in steps:
        try:
            fn()
        except Exception:
            log.exception("bước %s lỗi", label)


def run_scheduler(settings: Settings, repo: Repository, cron: str) -> None:
    sched = BlockingScheduler(timezone="Asia/Ho_Chi_Minh")
    sched.add_job(run_once, CronTrigger.from_crontab(cron, timezone="Asia/Ho_Chi_Minh"),
                  args=[settings, repo], max_instances=1, coalesce=True, id="crawl_all")
    log.info("Lịch: %s (Asia/Ho_Chi_Minh). Ctrl+C để dừng.", cron)
    if settings.schedule.get("run_on_start", False):
        run_once(settings, repo)
    job = sched.get_job("crawl_all")
    log.info("Lượt chạy tiếp theo: %s", getattr(job, "next_run_time", None) or job.trigger.get_next_fire_time(None, datetime.now(job.trigger.timezone)))
    sched.start()
