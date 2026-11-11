"""Nạp cấu hình từ config/*.yaml, cho phép ghi đè bằng biến môi trường AUCTION_*."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

ROOT = Path(os.environ.get("AUCTION_HOME", Path(__file__).resolve().parents[2]))
CONFIG_DIR = ROOT / "config"


class HttpSettings(BaseModel):
    timeout: float = 30
    max_retries: int = 4
    delay_seconds: float = 1.5
    user_agent: str = "Mozilla/5.0"
    verify_tls: bool = True
    concurrency: int = 1          # số luồng tải trang chi tiết song song


class CrawlSettings(BaseModel):
    max_pages: int = 50
    fetch_detail: bool = True
    stop_when_page_all_seen: bool = True


DEFAULT_CRON = "0 2 * * *"         # quét tin mới mỗi ngày 1 lần lúc 2:00 (giờ Việt Nam)
DEFAULT_FILL_CRON = "10 0,6-22/2 * * *"   # lấp dữ liệu còn thiếu: 0:10 và mỗi 2 giờ từ 6:10 đến 22:10


class Settings(BaseModel):
    db_url: str = "sqlite:///data/auction.db"
    raw_cache_dir: str | None = "data/raw"
    export_dir: str = "data/exports"
    data_dir: str = "data"            # nơi lưu file đính kèm (data/files/...)
    log_level: str = "INFO"
    http: HttpSettings = Field(default_factory=HttpSettings)
    crawl: CrawlSettings = Field(default_factory=CrawlSettings)
    schedule: dict[str, Any] = Field(default_factory=lambda: {"cron": DEFAULT_CRON, "run_on_start": False})

    def path(self, p: str) -> Path:
        q = Path(p)
        return q if q.is_absolute() else ROOT / q

    @property
    def resolved_db_url(self) -> str:
        # sqlite đường dẫn tương đối -> tính từ ROOT, đảm bảo thư mục tồn tại
        if self.db_url.startswith("sqlite:///") and not self.db_url.startswith("sqlite:////"):
            p = self.path(self.db_url.removeprefix("sqlite:///"))
            p.parent.mkdir(parents=True, exist_ok=True)
            return f"sqlite:///{p}"
        return self.db_url


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def get_settings() -> Settings:
    data = _load_yaml(CONFIG_DIR / "settings.yaml")
    if v := os.environ.get("AUCTION_DB_URL"):
        data["db_url"] = v
    if v := os.environ.get("AUCTION_LOG_LEVEL"):
        data["log_level"] = v
    return Settings(**data)


def load_source_config(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / "sources" / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Không thấy cấu hình nguồn: {path}")
    return _load_yaml(path)


def list_source_names() -> list[str]:
    return sorted(p.stem for p in (CONFIG_DIR / "sources").glob("*.yaml"))


@lru_cache
def load_categories() -> dict[str, Any]:
    return _load_yaml(CONFIG_DIR / "categories.yaml")
