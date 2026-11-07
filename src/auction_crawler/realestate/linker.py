"""Lọc tin bất động sản và gom các thông báo của CÙNG MỘT tài sản thành các phiên đấu giá.

Quy tắc gom (union-find):
  1. Cùng tỉnh + cùng xã/phường + cùng tập (tờ, thửa)            -> cùng tài sản (mạnh)
  2. Cùng tỉnh + cùng người có tài sản + mô tả gần như trùng khớp -> cùng tài sản
     (tin đấu giá lại thường giữ nguyên mô tả, chỉ thêm "lần 2", đổi giá/ngày)
  3. Cùng dup_group (một phiên đăng ở cả 2 nguồn)                  -> cùng tài sản, cùng phiên
  4. Liên kết thủ công (người dùng gộp/tách) luôn được tôn trọng.
Phiên = các thông báo cùng ngày đấu giá; đánh số theo thời gian. Giá phiên 1 = giá khởi điểm phiên
sớm nhất có giá; giá hiện tại = phiên gần nhất có giá; % giảm = (phiên 1 - hiện tại) / phiên 1.

Danh tính tài sản ổn định qua các lần chạy: cụm mới tái sử dụng id tài sản cũ của thành viên;
nếu cụm gom nhiều tài sản cũ -> gộp vào id nhỏ nhất (chuyển nhận xét, file, việc, nhật ký).
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update

from ..normalize import strip_accents
from ..storage import AssetRow, NoticeRow, Repository
from .db import Activity, Comment, FileView, Property, PropertyFile, PropertyNotice, Task
from .extract import RealEstateInfo, extract

log = logging.getLogger(__name__)

RE_TYPES = {"quyen_su_dung_dat", "nha_o_cong_trinh"}
MAT_BANG_RE = re.compile(r"mat bang|kiot|ki ot|can tin|canteen|\bnha\b|\bdat\b|m2|ky tuc|van phong|cua hang")
DEBT_RE_RE = re.compile(r"quyen su dung dat|\bthua\b|nha o|\bdat\b|tai san bao dam la|bat dong san|can ho")


def is_real_estate(asset_type: str | None, title: str, official_type: str | None) -> str | None:
    """Trả category ('dat' | 'nha_dat' | 'mat_bang') hoặc None nếu không phải BĐS."""
    n = strip_accents(title or "")
    if asset_type in RE_TYPES or (official_type and "quyen su dung dat" in strip_accents(official_type)):
        return "nha_dat" if re.search(r"\bnha\b|can ho|tai san gan lien|cong trinh|biet thu", n) else "dat"
    if asset_type == "cho_thue_mat_bang" and MAT_BANG_RE.search(n):
        return "mat_bang"
    if asset_type == "khoan_no" and DEBT_RE_RE.search(n):
        return "nha_dat" if re.search(r"\bnha\b|can ho", n) else "dat"
    return None


def _owner_key(s: str | None) -> str:
    t = strip_accents(s or "")
    t = re.sub(r"\(.*", "", t)
    t = re.sub(r"\b(phong|chi cuc|cuc|thi hanh an dan su|thads|khu vuc|so|cong ty|tnhh|chi nhanh|cn|ngan hang|"
               r"tinh|thanh pho|tp|huyen|quan)\b", " ", t)
    return re.sub(r"[^a-z0-9]", "", t)[:30]


GENERIC_RE = re.compile(r"^(tai san|quyen su dung dat|thong bao)[^0-9]{0,40}theo quy dinh|^tai san (thi hanh an|cua)\b[^0-9]{0,60}$")
MULTI_LOT_RE = re.compile(r"\bcac (lo|thua|khu|o dat|can|nen|diem)\b|\b\d+\s*(lo|thua|o dat|can ho|can nha|nen)\b|tron goi|danh muc")


def _text_linkable(title: str) -> bool:
    """Chỉ gom theo mô tả khi mô tả đủ cụ thể: có số liệu (thửa, m2, số nhà...), không phải câu chung chung
    ('Tài sản là quyền sử dụng đất theo quy định...') và không phải thông báo nhiều lô (mỗi phiên có thể khác lô)."""
    n = strip_accents(title or "")
    return len(n) >= 50 and bool(re.search(r"\d", n)) and not GENERIC_RE.search(n) and not MULTI_LOT_RE.search(n)


def _text_key(s: str) -> str:
    t = strip_accents(s or "")
    t = re.sub(r"\(?\s*(dau gia )?lan (thu )?\d+\s*\)?|dau gia lai|giam gia|\d{1,2}/\d{1,2}/\d{4}", " ", t)
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return hashlib.md5(t[:400].encode()).hexdigest()


@dataclass
class Item:
    nid: int
    source: str
    title: str
    owner: str | None
    origin: str | None
    province: str | None
    address: str | None
    price: int | None
    deposit: int | None
    auction_date: datetime | None
    registration_end: datetime | None
    publish_date: object
    dup_group: int | None
    category: str
    info: RealEstateInfo
    property_count: int | None = None


class DSU:
    def __init__(self) -> None:
        self.p: dict[int, int] = {}
        self.lock: dict[int, int | None] = {}   # root -> property_id bị khoá thủ công

    def add(self, x: int, locked: int | None) -> None:
        self.p[x] = x
        self.lock[x] = locked

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        la, lb = self.lock[ra], self.lock[rb]
        if la and lb and la != lb:
            return  # hai tài sản người dùng đã tách riêng -> không gộp
        self.p[rb] = ra
        self.lock[ra] = la or lb


def load_items(repo: Repository) -> list[Item]:
    with repo.session() as s:
        rows = s.execute(select(
            NoticeRow.id, NoticeRow.source, NoticeRow.title, NoticeRow.asset_name, NoticeRow.address,
            NoticeRow.asset_owner, NoticeRow.origin, NoticeRow.province, NoticeRow.asset_type, NoticeRow.official_type,
            NoticeRow.starting_price, NoticeRow.deposit, NoticeRow.auction_date, NoticeRow.registration_end,
            NoticeRow.publish_date, NoticeRow.dup_group, NoticeRow.owner_address, NoticeRow.property_count)).all()
        assets: dict[int, list[str]] = defaultdict(list)
        for nid, name, place in s.execute(select(AssetRow.notice_id, AssetRow.name, AssetRow.place)):
            assets[nid].extend(x for x in (name, place) if x)
    out = []
    for r in rows:
        cat = is_real_estate(r.asset_type, f"{r.title} {r.asset_name or ''}", r.official_type)
        if not cat:
            continue
        info = extract(r.title, r.asset_name, r.address, r.asset_type, assets.get(r.id))
        # giá: chỉ dùng giá chính thức khi nguồn đăng MỘT giá cho thông báo (kể cả gói "trọn gói" nhiều thửa
        # bán chung 1 giá). Thông báo có nhiều tài sản, mỗi tài sản một giá -> không cộng, để trống.
        single = (r.property_count or 1) == 1
        out.append(Item(r.id, r.source, r.title, r.asset_owner, r.origin, info.province, r.address,
                        r.starting_price if single else None, r.deposit if single else None,
                        r.auction_date, r.registration_end, r.publish_date, r.dup_group, cat, info,
                        r.property_count))
    return out


def cluster(items: list[Item], manual: dict[int, int]) -> list[list[Item]]:
    dsu = DSU()
    for it in items:
        dsu.add(it.nid, manual.get(it.nid))
    by_manual: dict[int, list[int]] = defaultdict(list)
    for nid, pid in manual.items():
        if nid in dsu.p:
            by_manual[pid].append(nid)
    for nids in by_manual.values():
        for x in nids[1:]:
            dsu.union(nids[0], x)
    strong: dict[tuple, int] = {}
    textk: dict[tuple, int] = {}
    dups: dict[int, int] = {}
    for it in items:
        # khoá mạnh: CHỈ khi tin xác định được duy nhất một cặp tờ/thửa và một xã/phường
        if it.info.map_sheet and it.info.parcel_no and it.info.ward and it.province:
            k = (it.province, strip_accents(it.info.ward), it.info.map_sheet.lstrip("0"), it.info.parcel_no.lstrip("0"))
            if k in strong:
                dsu.union(strong[k], it.nid)
            else:
                strong[k] = it.nid
        if _text_linkable(it.title):
            k2 = (it.province, _owner_key(it.owner), _text_key(it.title))
            if k2 in textk:
                dsu.union(textk[k2], it.nid)
            else:
                textk[k2] = it.nid
        if it.dup_group:
            if it.dup_group in dups:
                dsu.union(dups[it.dup_group], it.nid)
            else:
                dups[it.dup_group] = it.nid
    groups: dict[int, list[Item]] = defaultdict(list)
    for it in items:
        groups[dsu.find(it.nid)].append(it)
    return list(groups.values())


def _sessions(members: list[Item]) -> list[list[Item]]:
    by_day: dict[object, list[Item]] = defaultdict(list)
    for it in members:
        key = it.dup_group and f"g{it.dup_group}" or (it.auction_date.date() if it.auction_date else it.publish_date)
        by_day[key].append(it)
    def when(g: list[Item]):
        dts = [x.auction_date for x in g if x.auction_date] or \
              [datetime.combine(x.publish_date, datetime.min.time()) for x in g if x.publish_date]
        return min(dts) if dts else datetime.max
    return sorted(by_day.values(), key=when)


def _session_price(g: list[Item]) -> tuple[int | None, int | None]:
    best = sorted(g, key=lambda x: (x.source != "dgts", x.price is None))
    for x in best:
        if x.price:
            return x.price, x.deposit
    return None, None


def _merge_into(s, target: Property, other: Property) -> None:
    for model in (Comment, PropertyFile, Task):
        s.execute(update(model).where(model.property_id == other.id).values(property_id=target.id))
    s.execute(update(FileView).where(FileView.property_id == other.id).values(property_id=target.id))
    s.execute(update(Activity).where(Activity.property_id == other.id).values(property_id=target.id))
    for col in Property.__table__.columns.keys():
        if col.endswith("_manual") and getattr(target, col) in (None, "") and getattr(other, col) not in (None, ""):
            setattr(target, col, getattr(other, col))
    target.priority = max(target.priority or 0, other.priority or 0)
    if other.verified and not target.verified:
        target.verified, target.verified_by, target.verified_at = True, other.verified_by, other.verified_at
    s.add(Activity(property_id=target.id, action="merge", detail=f"Tự động gộp tài sản #{other.id} vào #{target.id}"))
    s.delete(other)


def rebuild(repo: Repository) -> dict[str, int]:
    items = load_items(repo)
    with repo.session() as s:
        links = {nid: (pid, man) for nid, pid, man in
                 s.execute(select(PropertyNotice.notice_id, PropertyNotice.property_id, PropertyNotice.manual))}
    manual = {nid: pid for nid, (pid, man) in links.items() if man}
    clusters = cluster(items, manual)
    stats = {"notices": len(items), "properties": len(clusters), "created": 0, "merged": 0}
    with repo.Session.begin() as s:
        pn_all = {pn.notice_id: pn for pn in s.scalars(select(PropertyNotice))}
        pn_by_prop: dict[int, dict[int, PropertyNotice]] = defaultdict(dict)
        for pn in pn_all.values():
            pn_by_prop[pn.property_id][pn.notice_id] = pn
        used: set[int] = set()
        for members in clusters:
            old = sorted({links[m.nid][0] for m in members if m.nid in links} - used)
            pid_manual = next((manual[m.nid] for m in members if m.nid in manual), None)
            pid = pid_manual if pid_manual and pid_manual not in used else (old[0] if old else None)
            prop = s.get(Property, pid) if pid else None
            if prop is None:
                prop = Property(title=members[0].title[:500])
                s.add(prop)
                s.flush()
                stats["created"] += 1
            for opid in old:
                if opid != prop.id and (o := s.get(Property, opid)) is not None:
                    _merge_into(s, prop, o)
                    stats["merged"] += 1
            used.add(prop.id)
            _apply(s, prop, members, pn_all, pn_by_prop)
        # tài sản không còn thông báo nào và không có dữ liệu người dùng -> xoá
        s.flush()
        for prop in s.scalars(select(Property).where(~Property.links.any())).all():
            has_user_data = s.scalar(select(Comment.id).where(Comment.property_id == prop.id).limit(1)) or \
                s.scalar(select(PropertyFile.id).where(PropertyFile.property_id == prop.id).limit(1))
            if not has_user_data:
                s.delete(prop)
    return stats


def _apply(s, prop: Property, members: list[Item], pn_all: dict, pn_by_prop: dict) -> None:
    sessions = _sessions(members)
    existing = dict(pn_by_prop.get(prop.id, {}))
    for no, g in enumerate(sessions, start=1):
        for it in g:
            pn = existing.pop(it.nid, None) or pn_all.get(it.nid)
            if pn is None:
                pn = PropertyNotice(notice_id=it.nid, property_id=prop.id)
                s.add(pn)
                pn_all[it.nid] = pn
            if pn.property_id != prop.id:
                pn_by_prop.get(pn.property_id, {}).pop(it.nid, None)
                pn.property_id = prop.id
            pn_by_prop[prop.id][it.nid] = pn
            pn.session_no = no
    for nid, pn in existing.items():      # thông báo đã rời cụm / không còn là BĐS
        if not pn.manual and pn.property_id == prop.id:
            s.delete(pn)
            pn_all.pop(nid, None)
            pn_by_prop[prop.id].pop(nid, None)
    priced = [(g, *_session_price(g)) for g in sessions]
    priced = [x for x in priced if x[1]]
    latest_g = sessions[-1]
    latest = max(latest_g, key=lambda x: (x.source == "dgts", x.price or 0))
    prop.title = (latest.title or prop.title)[:500]
    prop.category = "nha_dat" if any(m.category == "nha_dat" for m in members) else latest.category
    prop.sale_form = latest.info.sale_form
    prop.owner_type = latest.origin
    prop.owner_name = latest.owner
    # thuộc tính: chỉ nhận khi các thông báo KHÔNG mâu thuẫn nhau (mọi giá trị khác None phải bằng nhau)
    notes: list[str] = []

    def agree(getter, label):
        vals = [v for v in (getter(m) for m in members) if v not in (None, "")]
        uniq = list(dict.fromkeys(vals))
        if len(uniq) > 1:
            notes.append(f"Các thông báo ghi {label} khác nhau – để trống")
            return None
        return uniq[0] if uniq else None

    prop.province = agree(lambda m: m.province, "tỉnh/thành")
    prop.ward = agree(lambda m: m.info.ward, "xã/phường")
    prop.address = next((m.address for m in sorted(members, key=lambda x: x.auction_date or datetime.min,
                                                   reverse=True) if m.address), None)
    for f, lbl in (("land_area", "tổng diện tích"), ("residential_area", "diện tích đất ở"),
                   ("other_land_area", "diện tích đất khác"), ("floor_area", "diện tích sàn"),
                   ("width", "chiều ngang"), ("length", "chiều dài")):
        setattr(prop, f, agree(lambda m, f=f: getattr(m.info, f), lbl))
    prop.map_sheet = agree(lambda m: m.info.map_sheet, "số tờ")
    prop.parcel_no = agree(lambda m: m.info.parcel_no, "số thửa")
    parcels = []
    for m in members:
        for p_ in m.info.parcels:
            if list(p_) not in parcels:
                parcels.append(list(p_))
    prop.parcels = parcels[:30]
    for m in members:
        notes += m.info.notes
    if any((m.property_count or 1) > 1 for m in members):
        notes.append("Thông báo gồm nhiều tài sản, mỗi tài sản một giá – giá để trống (xem bảng tài sản), nhập tay nếu cần")
    if not prop.province:
        notes.append("Tin không ghi rõ tỉnh/thành nơi có tài sản")
    prop.auto_notes = list(dict.fromkeys(notes))[:12]
    prop.session_count = len(sessions)
    prop.price_first = priced[0][1] if priced and priced[0][0] is sessions[0] else None
    prop.price_latest = priced[-1][1] if priced and priced[-1][0] is latest_g else None
    prop.deposit_latest = priced[-1][2] if priced and priced[-1][0] is latest_g else None
    if priced and priced[-1][0] is not latest_g:
        notes_ = list(prop.auto_notes or [])
        notes_.append("Phiên gần nhất chưa có giá – giá hiện tại để trống")
        prop.auto_notes = notes_
    # cảnh báo gom phiên bất thường: giá phiên sau cao hơn phiên trước >5%, hoặc tổng giảm > 70%
    warn = None
    ps = [x[1] for x in priced]
    if any(b > a * 1.05 for a, b in zip(ps, ps[1:])):
        warn = "Giá phiên sau cao hơn phiên trước – có thể đã gộp nhầm tài sản khác"
    elif len(ps) > 1 and ps[0] and (ps[0] - ps[-1]) / ps[0] > 0.7:
        warn = "Giảm hơn 70% so với phiên 1 – kiểm tra lại các phiên đã gộp"
    prop.link_warning = warn
    prop.recompute_discount()
    prop.auction_date = max((m.auction_date for m in latest_g if m.auction_date), default=None)
    prop.registration_end = max((m.registration_end for m in latest_g if m.registration_end), default=None)
    prop.publish_date = max((m.publish_date for m in members if m.publish_date), default=None)
    prop.latest_notice_id = latest.nid
