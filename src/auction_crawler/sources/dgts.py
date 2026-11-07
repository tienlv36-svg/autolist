"""Nguồn: Cổng thông tin điện tử quốc gia về đấu giá tài sản - Bộ Tư pháp (dgts.moj.gov.vn).

Trang danh sách là AngularJS; dữ liệu lấy từ API JSON công khai mà chính trang gọi
(tìm bằng cách đọc /assets/project/auction-notice/list.js và DetailAuctionInfo.js):

  GET /portal/search/auction-notice?p=<trang>&numberPerPage=<≤500>
        [&startPublishDate=dd/mm/yyyy&endPublishDate=dd/mm/yyyy&provinceId=&propertyTypeId=...]
      -> {items:[{id, propertyName, publishTime1, publishTime2, aucTime, aucRegTimeStart,
                  aucRegTimeEnd, fullname, org_name, ...}], rowCount, pageCount, ...}
  GET /portal/propertyInfo?auctionInfoId=<id>
      -> {items:[{propertyName, propertyPlace, propertyStartPrice, deposit, depositUnit,
                  fileCost, propertyTypeName, propertyAmount, detail}]}
  GET /common/getListPropertyType      -> 16 loại tài sản theo Luật Đấu giá tài sản
  GET /common/getListProvince          -> danh mục tỉnh (id nội bộ)
  Trang chi tiết HTML: /thong-bao-cong-khai-viec-dau-gia/<slug>-<id>.html
      (render sẵn phía server: địa chỉ người có tài sản, địa điểm đấu giá...)
Mọi thời gian là epoch mili-giây UTC -> đổi sang giờ Việt Nam.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from typing import Any

from bs4 import BeautifulSoup

from ..http_client import Fetcher
from ..normalize import clean_text, strip_accents
from .base import ConfigSource

log = logging.getLogger(__name__)
VN_TZ = timezone(timedelta(hours=7))
DEPOSIT_UNIT = {0: "VND", 1: "%", 2: "USD"}


def ms_to_vn(ms: Any) -> datetime | None:
    if ms in (None, "", 0):
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, VN_TZ).replace(tzinfo=None)
    except (ValueError, OSError, OverflowError):
        return None


def slugify(s: str, max_len: int = 80) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", strip_accents(s or "")).strip("-")
    return (s[:max_len].rstrip("-") or "thong-bao")


class DgtsSource(ConfigSource):
    name = "dgts"

    @property
    def api(self) -> dict:
        return self.cfg["api"]

    def _url(self, path: str) -> str:
        return self.base_url.rstrip("/") + path

    # ------------------------------------------------------------ danh sách
    def search(self, fetcher: Fetcher, page: int, size: int | None = None, **filters: Any) -> dict:
        params = {"p": page, "numberPerPage": size or self.api.get("page_size", 500), **filters}
        return fetcher.get_json(self._url(self.api["search_path"]), params=params)

    def iter_pages(self, fetcher: Fetcher, max_pages: int, since: date | None = None
                   ) -> Iterator[tuple[int, list[dict]]]:
        filters: dict[str, Any] = dict(self.api.get("extra_params") or {})
        if since:  # lọc phía server theo ngày đăng
            filters["startPublishDate"] = since.strftime("%d/%m/%Y")
            filters["endPublishDate"] = (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")
        for page in range(1, max_pages + 1):
            data = self.search(fetcher, page, **filters)
            rows = data.get("items") or []
            if page == 1:
                log.info("[dgts] tổng số tin khớp: %s (%s trang)", data.get("rowCount"), data.get("pageCount"))
            if not rows:
                return
            yield page, [self.row_to_item(r) for r in rows]
            if page >= (data.get("pageCount") or 0):
                return

    def row_to_item(self, r: dict) -> dict:
        sid = str(r["id"])
        name = clean_text(r.get("propertyName")) or clean_text(r.get("subPropertyName")) or ""
        pub = ms_to_vn(r.get("publishTime2") or r.get("publishTime1"))
        return {
            "source_id": sid,
            "url": self._url(f"/thong-bao-cong-khai-viec-dau-gia/{slugify(name)}-{sid}.html"),
            "title": name[:1000],
            "asset_name": name,
            "asset_owner": r.get("fullname"),
            "auction_org": r.get("org_name"),
            "publish_date": pub,
            "auction_date": ms_to_vn(r.get("aucTime")),
            "registration_start": ms_to_vn(r.get("aucRegTimeStart")),
            "registration_end": ms_to_vn(r.get("aucRegTimeEnd")),
            "official_type": r.get("propertyTypeName"),
            "_date": pub.date() if pub else None,
            "_list_json": r,
        }

    # ------------------------------------------------------------ chi tiết
    def has_detail(self) -> bool:
        return True

    def enrich(self, fetcher: Fetcher, item: dict) -> dict:
        sid = item["source_id"]
        data = fetcher.get_json(self._url(self.api["property_path"]), params={"auctionInfoId": sid})
        assets = []
        for p in data.get("items") or []:
            unit = DEPOSIT_UNIT.get(p.get("depositUnit"), str(p.get("depositUnit")))
            assets.append({
                "name": clean_text(p.get("propertyName")),
                "place": clean_text(p.get("propertyPlace")),
                "quantity": clean_text(str(p["propertyAmount"])) if p.get("propertyAmount") else None,
                "type_name": p.get("propertyTypeName"),
                "starting_price": int(p["propertyStartPrice"]) if p.get("propertyStartPrice") else None,
                "deposit": int(p["deposit"]) if p.get("deposit") else None,
                "deposit_unit": unit,
                "file_cost": int(p["fileCost"]) if p.get("fileCost") else None,
            })
        out = {**item, "assets": assets, "_detail": True}
        if assets:
            prices = [a["starting_price"] for a in assets if a["starting_price"]]
            deps = [a["deposit"] for a in assets if a["deposit"] and a["deposit_unit"] == "VND"]
            fees = [a["file_cost"] for a in assets if a["file_cost"]]
            out.update(
                property_count=len(assets),
                starting_price=sum(prices) if prices else None,
                deposit=sum(deps) if deps else None,
                dossier_fee=max(fees) if fees else None,
                address=" | ".join(dict.fromkeys(a["place"] for a in assets if a["place"]))[:2000] or None,
                official_type=item.get("official_type") or next((a["type_name"] for a in assets if a["type_name"]), None),
            )
        if self.cfg.get("detail_html"):
            out.update({k: v for k, v in self.parse_detail_html(fetcher.get_html(item["url"])).items() if v})
        return out

    def parse_detail_html(self, html: str) -> dict:
        """Trang chi tiết: các khối 'Nhãn:' / giá trị nằm trên các dòng kế tiếp.
        'Địa chỉ:' xuất hiện 2 lần (người có tài sản, tổ chức đấu giá) -> đọc tuần tự theo ngữ cảnh."""
        soup = BeautifulSoup(html, "lxml")
        for t in soup(["script", "style", "noscript", "header", "footer", "nav"]):
            t.decompose()
        lines = [x for x in soup.get_text("\n", strip=True).split("\n") if "{{" not in x]
        out: dict[str, str] = {}
        ctx = None
        for i, line in enumerate(lines[:-1]):
            n = strip_accents(line)
            nxt = clean_text(lines[i + 1])
            if n.startswith("ten nguoi co tai san"):
                ctx = "owner"
            elif n.startswith("ten don vi to chuc dau gia"):
                ctx = "org"
            elif n.startswith("dia chi") and ctx == "owner" and "owner_address" not in out:
                out["owner_address"] = nxt
            elif n.startswith("dia diem to chuc cuoc dau g"):  # trang viết sai chính tả "đấu gá"
                out["auction_place"] = nxt
            elif n.startswith("thoi gian to chuc cuoc dau gia") and "auction_date" not in out:
                out["auction_date"] = nxt
        return out

    # ------------------------------------------------------------ loại tài sản chính thức
    def property_types(self, fetcher: Fetcher) -> list[dict]:
        return fetcher.get_json(self._url("/common/getListPropertyType"))

    def iter_ids_by_type(self, fetcher: Fetcher, type_id: int, max_pages: int = 10_000,
                         since: date | None = None) -> Iterator[list[str]]:
        filters: dict[str, Any] = {"propertyTypeId": type_id}
        if since:
            filters["startPublishDate"] = since.strftime("%d/%m/%Y")
            filters["endPublishDate"] = (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")
        for page in range(1, max_pages + 1):
            data = self.search(fetcher, page, **filters)
            rows = data.get("items") or []
            if not rows:
                return
            yield [str(r["id"]) for r in rows]
            if page >= (data.get("pageCount") or 0):
                return
