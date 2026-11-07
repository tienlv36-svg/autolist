"""Registry các nguồn. Thêm nguồn mới: tạo config/sources/<name>.yaml (+ lớp con nếu cần)."""
from __future__ import annotations

from ..config import list_source_names, load_source_config
from .base import ConfigSource
from .dgts import DgtsSource
from .taisancong import TaiSanCongSource

SOURCE_CLASSES: dict[str, type[ConfigSource]] = {
    "dgts": DgtsSource,
    "taisancong": TaiSanCongSource,
}


def get_source(name: str) -> ConfigSource:
    cfg = load_source_config(name)
    return SOURCE_CLASSES.get(name, ConfigSource)(cfg)


def all_sources() -> list[str]:
    return list_source_names()
