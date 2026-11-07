"""Nguồn dữ liệu điều khiển bằng cấu hình YAML.

Mỗi nguồn = 1 file config/sources/<name>.yaml + (tuỳ chọn) 1 lớp con để xử lý
đặc thù. Hai chế độ:
  - mode: html -> parse danh sách & chi tiết bằng CSS selector / nhãn
  - mode: api  -> gọi endpoint JSON (tìm bằng `auction probe`), map field bằng json path
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date
from typing import Any
from urllib.parse import urljoin

from ..http_client import Fetcher
from .extract import extract_by_labels, json_path, select_field, soupify

log = logging.getLogger(__name__)


class ConfigSource:
    name: str = "base"

    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.name = cfg.get("name", self.name)
        self.base_url = cfg.get("base_url", "")
        self.mode = cfg.get("mode", "html")

    # ------------------------------------------------------------ danh sách
    def page_url(self, page: int) -> tuple[str, dict | None]:
        lst = self.cfg["list"]
        pg = lst.get("pagination", {"type": "none"})
        typ = pg.get("type", "none")
        if typ == "query":
            if page == pg.get("start", 1) and pg.get("first_page_plain", False):
                return lst["url"], None
            return lst["url"], {pg.get("param", "page"): page, **pg.get("extra_params", {})}
        if typ == "template":
            if page == pg.get("start", 1):
                return lst["url"], None  # trang đầu dùng URL gốc
            size = pg.get("page_size", 20)
            return pg["url_template"].format(page=page, offset=(page - pg.get("start", 1)) * size), None
        return lst["url"], None

    def http_overrides(self) -> dict:
        return self.cfg.get("http", {}) or {}

    def iter_pages(self, fetcher: Fetcher, max_pages: int, since: date | None = None
                   ) -> Iterator[tuple[int, list[dict]]]:
        """Duyệt các trang danh sách (mới nhất trước). `since`: lớp con dùng để lọc phía server nếu
        hỗ trợ; pipeline còn tự dừng khi cả trang cũ hơn `since` (dựa vào item['_date'])."""
        if self.mode == "api":
            yield from self._iter_api_pages(fetcher, max_pages)
            return
        pg = self.cfg["list"].get("pagination", {})
        start = pg.get("start", 1)
        seen_ids: set[str] = set()
        for i in range(max_pages):
            page = start + i
            url, params = self.page_url(page)
            html = fetcher.get_html(url, params)
            items = self.parse_list(html, url)
            new = [it for it in items if it["source_id"] not in seen_ids]
            if not new:  # trang rỗng hoặc trang lặp lại (vượt trang cuối)
                log.info("[%s] hết dữ liệu tại trang %s", self.name, page)
                return
            seen_ids.update(it["source_id"] for it in new)
            yield page, new
            if pg.get("type", "none") == "none":
                return

    def parse_list(self, html: str, page_url: str) -> list[dict]:
        lst = self.cfg["list"]
        soup = soupify(html)
        out = []
        for node in soup.select(lst["item"]):
            item = {k: select_field(node, spec, page_url) for k, spec in lst.get("fields", {}).items()}
            if item.get("url"):
                item["url"] = urljoin(page_url, item["url"])
            if not item.get("title"):
                continue
            item["source_id"] = self.source_id(item)
            item = self.post_list_item(item)
            if item:
                out.append(item)
        return out

    def source_id(self, item: dict) -> str:
        rx = self.cfg["list"].get("source_id_regex")
        url = item.get("url") or ""
        if rx and (m := re.search(rx, url)):
            return m.group(1) if m.groups() else m.group(0)
        # fallback: URL (bỏ domain) hoặc tiêu đề
        return re.sub(r"^https?://[^/]+", "", url) or item["title"][:200]

    def post_list_item(self, item: dict) -> dict | None:
        """Hook cho lớp con: làm sạch / bỏ qua tin."""
        return item

    # ------------------------------------------------------------ API JSON
    def _iter_api_pages(self, fetcher: Fetcher, max_pages: int) -> Iterator[tuple[int, list[dict]]]:
        api = self.cfg["api"]
        if not api.get("url"):
            raise ValueError(f"[{self.name}] mode=api nhưng chưa khai báo api.url")
        for i in range(max_pages):
            page = api.get("page_start", 1) + i
            params = {api.get("page_param", "page"): page, **api.get("extra_params", {})}
            if api.get("page_size_param"):
                params[api["page_size_param"]] = api.get("page_size", 50)
            method = api.get("method", "GET").upper()
            data = fetcher.get_json(api["url"], method, params=params, json=params if method != "GET" else None)
            rows = json_path(data, api.get("items_path")) or []
            items = []
            for row in rows:
                it = {k: json_path(row, p) for k, p in api.get("fields", {}).items()}
                it = {k: (str(v) if v is not None and not isinstance(v, str) else v) for k, v in it.items()}
                it["source_id"] = str(it.get("source_id") or "")
                if not it["source_id"] or not it.get("title"):
                    continue
                if not it.get("url") and api.get("detail_url_template"):
                    it["url"] = api["detail_url_template"].format(**it)
                it["_json"] = row
                if it := self.post_list_item(it):
                    items.append(it)
            if not items:
                return
            yield page, items

    # ------------------------------------------------------------ chi tiết
    def has_detail(self) -> bool:
        return bool(self.cfg.get("detail"))

    def enrich(self, fetcher: Fetcher, item: dict) -> dict:
        """Bổ sung dữ liệu chi tiết cho một tin (chạy trong luồng phụ - không đụng DB).
        Mặc định: tải trang chi tiết HTML và trích theo nhãn/selector."""
        if not item.get("url"):
            return item
        detail = self.parse_detail(fetcher.get_html(item["url"]), item["url"])
        return {**item, **{k: v for k, v in detail.items() if v}, "_detail": True}

    def parse_detail(self, html: str, url: str) -> dict[str, Any]:
        det = self.cfg.get("detail") or {}
        soup = soupify(html)
        root = soup
        if css := det.get("root"):
            root = soup.select_one(css) or soup
        data: dict[str, Any] = extract_by_labels(root, det.get("labels", {}))
        for k, spec in det.get("fields", {}).items():
            v = select_field(root, spec, url)
            if v:
                data.setdefault(k, v)
        return self.post_detail(data, soup)

    def post_detail(self, data: dict, soup) -> dict:
        return data
