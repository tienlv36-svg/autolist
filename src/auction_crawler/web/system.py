"""Số liệu cho trang Hệ thống (quản trị): lượt thu thập, dữ liệu, ổ cứng, sao lưu, lịch, Telegram, đăng nhập sai."""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select

from ..notify import is_configured
from ..realestate.db import LoginAttempt, Property
from ..storage import CrawlRun, NoticeRow


def _dir_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _service_state(name: str) -> str:
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True, timeout=3)
        return r.stdout.strip() or "?"
    except (OSError, subprocess.SubprocessError):
        return "?"


def system_status(s, settings, media_root: Path) -> dict[str, Any]:
    st: dict[str, Any] = {}
    st["runs"] = s.scalars(select(CrawlRun).order_by(CrawlRun.id.desc()).limit(15)).all()
    st["notices"] = s.execute(select(NoticeRow.source, func.count(), func.count(NoticeRow.starting_price))
                              .group_by(NoticeRow.source)).all()
    st["props"] = s.execute(select(func.count(Property.id), func.count(Property.price_latest),
                                   func.sum(Property.verified.cast(int_type())),
                                   func.count(Property.discount_pct))).one()
    db = settings.resolved_db_url
    st["db_size"] = Path(db.removeprefix("sqlite:///")).stat().st_size if db.startswith("sqlite:///") \
        and Path(db.removeprefix("sqlite:///")).exists() else None
    data_dir = settings.path("data")
    try:
        u = shutil.disk_usage(data_dir)
        st["disk"] = {"total": u.total, "used": u.used, "free": u.free, "pct": round(u.used / u.total * 100, 1)}
    except OSError:
        st["disk"] = None
    st["media_size"] = _dir_size(media_root) if media_root.exists() else 0
    bdir = settings.path("backups")
    backups = sorted(bdir.glob("autolist_*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True) if bdir.exists() else []
    st["backups"] = [{"name": b.name, "size": b.stat().st_size, "at": datetime.fromtimestamp(b.stat().st_mtime)}
                     for b in backups[:5]]
    st["backup_count"] = len(backups)
    cron = settings.schedule.get("cron", "0 2 * * *")
    try:
        trig = CronTrigger.from_crontab(cron, timezone="Asia/Ho_Chi_Minh")
        st["next_run"] = trig.get_next_fire_time(None, datetime.now(trig.timezone))
    except ValueError:
        st["next_run"] = None
    st["cron"] = cron
    st["services"] = {n: _service_state(n) for n in ("auction-web", "auction-scheduler", "caddy")}
    st["telegram"] = is_configured(settings)
    since = datetime.now() - timedelta(hours=24)
    st["failed_logins"] = s.execute(
        select(LoginAttempt.ip, func.count(), func.max(LoginAttempt.at), func.group_concat(LoginAttempt.username.distinct()))
        .where(LoginAttempt.success.is_(False), LoginAttempt.at >= since)
        .group_by(LoginAttempt.ip).order_by(func.count().desc()).limit(10)).all()
    log = settings.path("data/first-load.log")
    st["first_load_tail"] = log.read_text(errors="ignore").splitlines()[-6:] if log.exists() else []
    return st


def int_type():
    from sqlalchemy import Integer
    return Integer
