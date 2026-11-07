"""Mô hình dữ liệu chuẩn hoá cho một tin đấu giá (độc lập với nguồn)."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field


class AssetItem(BaseModel):
    """Một tài sản trong thông báo (một thông báo có thể gồm nhiều tài sản/lô)."""
    name: str | None = None
    place: str | None = None
    quantity: str | None = None
    type_name: str | None = None
    starting_price: int | None = None
    deposit: int | None = None
    deposit_unit: str | None = None      # VND | USD | %
    file_cost: int | None = None


class AuctionNotice(BaseModel):
    source: str
    source_id: str
    url: str | None = None
    title: str

    asset_name: str | None = None
    asset_owner: str | None = None         # người/đơn vị có tài sản
    owner_address: str | None = None
    auction_org: str | None = None         # tổ chức hành nghề đấu giá
    address: str | None = None             # nơi có tài sản
    auction_place: str | None = None       # địa điểm tổ chức cuộc đấu giá
    province: str | None = None            # tỉnh/thành theo đơn vị hành chính hiện hành (34 tỉnh)
    province_raw: str | None = None        # tên tỉnh như trong tin (có thể là tên cũ)

    starting_price: int | None = None      # VND (tổng các tài sản nếu có nhiều)
    deposit: int | None = None             # tiền đặt trước, VND
    dossier_fee: int | None = None         # tiền hồ sơ, VND
    property_count: int | None = None

    publish_date: date | None = None
    auction_date: datetime | None = None
    registration_start: datetime | None = None
    registration_end: datetime | None = None

    official_type: str | None = None       # loại tài sản theo phân loại của nguồn (nếu có)
    asset_type: str | None = None          # loại tài sản (bộ phân loại nội bộ)
    origin: str | None = None              # nguồn gốc tài sản
    classify_score: float | None = None

    content: str | None = None
    detail_fetched: bool = False
    assets: list[AssetItem] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        """Hash nội dung chính - để phát hiện tin bị sửa/cập nhật."""
        keys = ["title", "asset_name", "starting_price", "deposit", "auction_date", "registration_end",
                "address", "auction_org"]
        payload = json.dumps({k: getattr(self, k) for k in keys}, default=str, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(payload.encode()).hexdigest()

    def classify_fields(self) -> dict[str, str | None]:
        """Các trường đưa vào bộ phân loại (trọng số từng trường: categories.yaml/field_weights)."""
        name = self.asset_name if self.asset_name and self.asset_name != self.title else None
        return {
            "title": self.title, "asset_name": name, "official_type": self.official_type,
            "asset_types": " | ".join(dict.fromkeys(a.type_name for a in self.assets if a.type_name)) or None,
            "asset_owner": self.asset_owner, "content": self.content,
        }
