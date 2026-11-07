"""Truy vấn danh sách tài sản với bộ lọc (dùng giá trị hiệu lực = nhập tay ưu tiên)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import and_, func, or_, select

from ..realestate.db import Property, Task


def eff(col: str):
    return func.coalesce(getattr(Property, f"{col}_manual"), getattr(Property, col))


SORTS = {
    "han_dang_ky": ("Sắp hết hạn đăng ký", lambda: [Property.registration_end.is_(None), Property.registration_end.asc()]),
    "moi_nhat": ("Mới đăng", lambda: [Property.publish_date.desc().nulls_last(), Property.id.desc()]),
    "gia_tang": ("Giá thấp → cao", lambda: [eff("price_latest").is_(None), eff("price_latest").asc()]),
    "gia_giam": ("Giá cao → thấp", lambda: [eff("price_latest").desc().nulls_last()]),
    "giam_nhieu": ("Giảm giá nhiều nhất", lambda: [Property.discount_pct.desc().nulls_last()]),
    "uu_tien": ("Ưu tiên cao", lambda: [Property.priority.desc(), Property.registration_end.asc()]),
    "dien_tich": ("Diện tích lớn", lambda: [eff("land_area").desc().nulls_last()]),
}


@dataclass
class Filters:
    q: str = ""
    owner_type: list[str] = field(default_factory=list)
    sale_form: list[str] = field(default_factory=list)
    category: list[str] = field(default_factory=list)
    province: str = ""
    ward: str = ""
    price_min: float | None = None      # tỷ đồng
    price_max: float | None = None
    area_min: float | None = None       # m2
    area_max: float | None = None
    priority_min: int | None = None
    verified: str = ""                  # "" | "1" | "0"
    open_only: bool = False             # còn hạn đăng ký
    discounted: bool = False
    multi_session: bool = False
    mine: bool = False                  # được giao cho tôi
    sort: str = "han_dang_ky"
    page: int = 1

    @classmethod
    def from_request(cls, qp) -> "Filters":
        def num(k):
            v = (qp.get(k) or "").replace(",", ".").strip()
            try:
                return float(v) if v else None
            except ValueError:
                return None
        pm = num("priority_min")
        return cls(
            q=(qp.get("q") or "").strip(), owner_type=qp.getlist("owner_type"), sale_form=qp.getlist("sale_form"),
            category=qp.getlist("category"), province=qp.get("province") or "", ward=qp.get("ward") or "",
            price_min=num("price_min"), price_max=num("price_max"), area_min=num("area_min"), area_max=num("area_max"),
            priority_min=int(pm) if pm is not None else None, verified=qp.get("verified") or "",
            open_only=qp.get("open_only") == "1", discounted=qp.get("discounted") == "1",
            multi_session=qp.get("multi_session") == "1", mine=qp.get("mine") == "1",
            sort=qp.get("sort") if qp.get("sort") in SORTS else "han_dang_ky",
            page=max(1, int(num("page") or 1)),
        )


def build_query(f: Filters, user_id: int):
    q = select(Property)
    conds = []
    if f.q:
        like = f"%{f.q}%"
        conds.append(or_(Property.title.ilike(like), eff("address").ilike(like), Property.owner_name.ilike(like),
                         eff("parcel_no") == f.q, eff("ward").ilike(like)))
    if f.owner_type:
        types = set(f.owner_type)
        if "doanh_nghiep_ca_nhan" in types:
            types.add("ca_nhan_so_huu")
        conds.append(Property.owner_type.in_(types))
    if f.sale_form:
        conds.append(Property.sale_form.in_(f.sale_form))
    if f.category:
        conds.append(Property.category.in_(f.category))
    if f.province:
        conds.append(eff("province") == f.province)
    if f.ward:
        conds.append(eff("ward") == f.ward)
    if f.price_min is not None:
        conds.append(eff("price_latest") >= int(f.price_min * 1e9))
    if f.price_max is not None:
        conds.append(eff("price_latest") <= int(f.price_max * 1e9))
    if f.area_min is not None:
        conds.append(eff("land_area") >= f.area_min)
    if f.area_max is not None:
        conds.append(eff("land_area") <= f.area_max)
    if f.priority_min:
        conds.append(Property.priority >= f.priority_min)
    if f.verified in ("0", "1"):
        conds.append(Property.verified.is_(f.verified == "1"))
    if f.open_only:
        conds.append(Property.registration_end >= datetime.now())
    if f.discounted:
        conds.append(Property.discount_pct > 0)
    if f.multi_session:
        conds.append(Property.session_count > 1)
    if f.mine:
        conds.append(Property.id.in_(select(Task.property_id).where(
            Task.assignee_id == user_id, Task.status.in_(["moi", "dang_lam"]))))
    if conds:
        q = q.where(and_(*conds))
    return q.order_by(*SORTS[f.sort][1](), Property.id.desc())
