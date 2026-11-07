"""Nguồn: taisancong.vn (Bộ Tài chính) - mục Thông tin bán đấu giá.

Trang render sẵn phía server (đã kiểm chứng 07/11/2026, ~35.400 tin, 20 tin/trang):
  Danh sách: div.all-daugia div.table-info div.tbody > div.row
             .b-tsb a (tên + link) | .b-dvico (đơn vị có TS) | .b-dvb (đơn vị bán đấu giá)
             .b-tdban (thời gian bán hồ sơ "dd-mm-yyyy HH:MM - dd-mm-yyyy HH:MM")
             .b-ngayban (ngày đấu giá) | .b-address (địa điểm đấu giá)
  Phân trang: <list_url>&BRSR=<offset>  (offset = 20, 40, ...; chú ý dùng '&' không có '?')
  Chi tiết:  tbody.table-body tr -> 14 dòng "N. Nhãn:" | giá trị; ngày đăng .article-date
  Lưu ý: trang KHÔNG có giá khởi điểm/tiền đặt trước - chỉ nằm trong file PDF đính kèm
         (thường là bản scan) -> xem tools/pdf_prices.py.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin

from ..http_client import Fetcher
from ..normalize import clean_text, parse_datetime, strip_accents
from .base import ConfigSource
from .extract import soupify

# nhãn (không dấu, bỏ số thứ tự) -> field
DETAIL_ROWS = {
    "loai noi dung": "content_type",
    "ten don vi dau gia": "auction_org",
    "dia chi don vi dau gia": "org_address",
    "dia diem ban dau gia": "auction_place",
    "ten don vi co tai san": "asset_owner",
    "dia chi don vi co tai san": "owner_address",
    "noi dung tai san ban": "asset_name",
    "thoi gian ban ho so": "registration",
    "thoi gian xem tai san": "viewing_time",
    "thoi gian ban dau gia": "auction_date",
    "so dien thoai lien he": "contact_phone",
    "dia chi email": "contact_email",
}


def split_range(s: str | None) -> tuple[str | None, str | None]:
    """'06-11-2026 14:00 - 23-11-2026 17:00' / 'từ ngày: X đến ngày: Y' -> (X, Y)"""
    if not s:
        return None, None
    parts = re.split(r"\s+-\s+|\bđến ngày\s*:?|\bđến\b", s, flags=re.I)
    parts = [p for p in (re.sub(r"(?i)từ ngày\s*:?", "", x).strip() for x in parts) if p]
    if not parts:
        return None, None
    return parts[0], parts[-1] if len(parts) > 1 else None


class TaiSanCongSource(ConfigSource):
    name = "taisancong"

    def post_list_item(self, item: dict) -> dict | None:
        start, end = split_range(item.pop("registration", None))
        item["registration_start"], item["registration_end"] = start, end
        # danh sách không có ngày đăng -> dùng ngày mở bán hồ sơ làm mốc cho --since
        dt = parse_datetime(start)
        item["_date"] = dt.date() if dt else None
        return item

    def has_detail(self) -> bool:
        return True

    def enrich(self, fetcher: Fetcher, item: dict) -> dict:
        html = fetcher.get_html(item["url"])
        return {**item, **{k: v for k, v in self.parse_detail(html, item["url"]).items() if v}, "_detail": True}

    def parse_detail(self, html: str, url: str) -> dict[str, Any]:
        soup = soupify(html)
        out: dict[str, Any] = {}
        for tr in soup.select("tbody.table-body tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            key = re.sub(r"^\d+\.\s*", "", strip_accents(tds[0].get_text(" ", strip=True))).rstrip(": ").strip()
            field = DETAIL_ROWS.get(key)
            if field:
                out[field] = clean_text(tds[1].get_text(" ", strip=True))
        files = [urljoin(url, a["href"]) for a in soup.select("tbody.table-body a[href]")
                 if re.search(r"\.(pdf|docx?|xlsx?|jpe?g|png|zip|rar)$", a["href"], re.I)]
        if files:
            out["attachments"] = files
        if el := soup.select_one(".article-date"):
            out["publish_date"] = clean_text(el.get_text(" ", strip=True))
        if t := soup.select_one("h1.article-detail-title"):
            out["page_title"] = clean_text(t.get_text(" ", strip=True))
        if reg := out.pop("registration", None):
            out["registration_start"], out["registration_end"] = split_range(reg)
        return out
