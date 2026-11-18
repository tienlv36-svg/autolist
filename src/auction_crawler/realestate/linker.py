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

from ..normalize import plausible_dt, strip_accents
from ..storage import AssetRow, NoticeRow, Repository
from .db import Activity, Comment, FileView, Property, PropertyFile, PropertyNotice, Task
from ..attachments import doc_price
from . import wardmap
from .history import gcn_serials
from .extract import RealEstateInfo, clause_location, extract, place_rejection, ward_key

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
    doc: dict | None = None
    gcn: frozenset = frozenset()     # số giấy chứng nhận nhắc trong tin (vd "BR 234700")
    places: tuple = ()               # nơi có từng tài sản (thông báo nhiều tài sản: mỗi tài sản một nơi)          # thông số trích từ file đính kèm (attachments.merge_file_infos)


MAX_PRICE_RATIO = 5      # một tài sản không thể có giá khởi điểm chênh nhau quá 5 lần giữa các phiên


class DSU:
    def __init__(self) -> None:
        self.p: dict[int, int] = {}
        self.lock: dict[int, int | None] = {}   # root -> property_id bị khoá thủ công
        self.lo: dict[int, int | None] = {}      # root -> giá thấp nhất / cao nhất trong cụm
        self.hi: dict[int, int | None] = {}

    def add(self, x: int, locked: int | None, price: int | None = None) -> None:
        self.p[x] = x
        self.lock[x] = locked
        self.lo[x] = self.hi[x] = price or None

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int, check_price: bool = True) -> bool:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return True
        la, lb = self.lock[ra], self.lock[rb]
        if la and lb and la != lb:
            return False  # hai tài sản người dùng đã tách riêng -> không gộp
        los = [v for v in (self.lo[ra], self.lo[rb]) if v]
        his = [v for v in (self.hi[ra], self.hi[rb]) if v]
        if check_price and los and his and max(his) > MAX_PRICE_RATIO * min(los):
            return False  # giá chênh > 5 lần -> gần như chắc chắn là tài sản khác
        self.p[rb] = ra
        self.lock[ra] = la or lb
        self.lo[ra], self.hi[ra] = (min(los) if los else None), (max(his) if his else None)
        return True


def load_items(repo: Repository) -> list[Item]:
    with repo.session() as s:
        rows = s.execute(select(
            NoticeRow.id, NoticeRow.source, NoticeRow.title, NoticeRow.asset_name, NoticeRow.address,
            NoticeRow.asset_owner, NoticeRow.origin, NoticeRow.province, NoticeRow.asset_type, NoticeRow.official_type,
            NoticeRow.starting_price, NoticeRow.deposit, NoticeRow.auction_date, NoticeRow.registration_end,
            NoticeRow.publish_date, NoticeRow.dup_group, NoticeRow.owner_address, NoticeRow.property_count,
            NoticeRow.doc_info)).all()
        assets: dict[int, list[str]] = defaultdict(list)
        places: dict[int, list[str]] = defaultdict(list)
        for nid, name, place in s.execute(select(AssetRow.notice_id, AssetRow.name, AssetRow.place)):
            assets[nid].extend(x for x in (name, place) if x)
            if place and not place_rejection(place):
                places[nid].append(place)
    out = []
    for r in rows:
        cat = is_real_estate(r.asset_type, f"{r.title} {r.asset_name or ''}", r.official_type)
        if not cat:
            continue
        bad_place = place_rejection(r.address, r.asset_owner, r.owner_address)
        address = None if bad_place else r.address
        info = extract(r.title, r.asset_name, address, r.asset_type, assets.get(r.id))
        if bad_place:
            info.notes.append(f"Địa chỉ tài sản để trống: {bad_place}")
        price = r.starting_price if (r.property_count or 1) == 1 else None
        if r.doc_info:
            price, pnote = doc_price(r.doc_info, price, r.property_count)
            if pnote:
                info.notes.append(pnote)
        # giá: chỉ dùng giá chính thức khi nguồn đăng MỘT giá cho thông báo (kể cả gói "trọn gói" nhiều thửa
        # bán chung 1 giá). Thông báo có nhiều tài sản, mỗi tài sản một giá -> không cộng, để trống.
        single = (r.property_count or 1) == 1
        out.append(Item(r.id, r.source, r.title, r.asset_owner, r.origin, info.province, address,
                        price if single else None, r.deposit if single else None,
                        plausible_dt(r.auction_date), plausible_dt(r.registration_end), plausible_dt(r.publish_date),
                        r.dup_group, cat, info,
                        r.property_count, r.doc_info if (r.property_count or 1) == 1 else None,
                        frozenset(gcn_serials(f"{r.title} {r.asset_name or ''}"[:3000])),
                        tuple(dict.fromkeys([*places.get(r.id, []), *(x.strip() for x in (address or "").split("|")
                                                                       if x.strip())]))))
    return out


def cluster(items: list[Item], manual: dict[int, int], pinned: dict[int, int] | None = None) -> list[list[Item]]:
    """manual: liên kết NGƯỜI DÙNG gộp/tách (luôn giữ). pinned: liên kết máy tự khoá (quét lịch sử, phiên hiện có) –
    vẫn giữ nhưng có kiểm tra giá (chênh > 5 lần thì tách ra)."""
    pinned = pinned or {}
    dsu = DSU()
    for it in items:
        dsu.add(it.nid, manual.get(it.nid) or pinned.get(it.nid), it.price)
    for links, check in ((manual, False), (pinned, True)):
        by_pid: dict[int, list[int]] = defaultdict(list)
        for nid, pid in links.items():
            if nid in dsu.p:
                by_pid[pid].append(nid)
        for nids in by_pid.values():
            for x in nids[1:]:
                dsu.union(nids[0], x, check_price=check)
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
                dsu.union(dups[it.dup_group], it.nid, check_price=False)   # cùng một tin đăng ở 2 nguồn
            else:
                dups[it.dup_group] = it.nid
    _auto_merge(items, dsu)
    groups: dict[int, list[Item]] = defaultdict(list)
    for it in items:
        groups[dsu.find(it.nid)].append(it)
    return list(groups.values())


def _area(it: Item) -> float | None:
    return it.info.land_area or ((it.doc or {}).get("land_area") if it.doc and not it.info.multi else None)


def _same_area(a: Item, b: Item) -> bool:
    x, y = _area(a), _area(b)
    return bool(x and y and abs(x - y) <= 0.5)


def _area_conflict(a: Item, b: Item) -> bool:
    x, y = _area(a), _area(b)
    return bool(x and y and abs(x - y) > max(0.5, 0.01 * max(x, y)))


def _parcel(it: Item):
    sheet, no = it.info.map_sheet, it.info.parcel_no
    if not (sheet and no) and it.doc and not it.info.multi:
        sheet, no = it.doc.get("map_sheet"), it.doc.get("parcel_no")
    return (str(sheet).lstrip("0"), str(no).lstrip("0")) if sheet and no else None


_WARD_PREFIX_RE = re.compile(r"^(xa|phuong|thi tran|dac khu)\s+")


def _core_ward(w: str | None) -> str:
    """Tên xã/phường bỏ dấu, bỏ chữ "xã/phường/thị trấn" (thị trấn Thạnh Mỹ -> xã Thạnh Mỹ vẫn là "thanh my")."""
    return _WARD_PREFIX_RE.sub("", ward_key(w))


def _ward_conflict(a: Item, b: Item) -> bool:
    """Hai tin ghi xã/phường CÙNG thời kỳ tên gọi (cùng tên cũ hoặc cùng tên mới) mà khác nhau -> khác nơi."""
    return bool(a.info.ward and b.info.ward and a.info.ward_new == b.info.ward_new
                and _core_ward(a.info.ward) != _core_ward(b.info.ward))


_NOISE_RE = re.compile(r"\(?\s*(dau gia\s*)?(lai\s*)?lan\s*(thu\s*)?\d+\s*\)?|\d{1,2}/\d{1,2}/\d{2,4}|"
                       r"\d{1,2}\s*gio(\s*\d{1,2}\s*phut)?|gia khoi diem[^.;]*|\d[\d.,]*\s*(dong|vnd|vnđ|ty|trieu)\b")


def _title_sig(it: Item) -> tuple[frozenset, frozenset]:
    """(các từ, các con số) của mô tả – bỏ "lần N", ngày giờ, số tiền (thay đổi giữa các phiên đấu lại)."""
    n = _NOISE_RE.sub(" ", strip_accents(f"{it.title} "))
    words = frozenset(w for w in re.findall(r"[a-z]+", n) if len(w) > 1)
    nums = frozenset(x.lstrip("0") for x in re.findall(r"\d+", n))
    return words, nums


def _same_day(a: Item, b: Item) -> bool:
    return bool(a.auction_date and b.auction_date and a.auction_date.date() == b.auction_date.date())


def _price_ok(a: Item, b: Item) -> bool:
    """Đấu giá lại thường GIẢM giá: phiên sau không đắt hơn phiên trước quá 5%."""
    if not (a.price and b.price and a.auction_date and b.auction_date):
        return True
    old, new = (a, b) if a.auction_date <= b.auction_date else (b, a)
    return new.price <= old.price * 1.05


def same_property(a: Item, b: Item, sig: dict) -> bool:
    """Hai tin là CÙNG một BĐS (đấu giá lại) – quyết định tự động, có chốt chặn chống gộp nhầm lô khác."""
    if a.info.multi or b.info.multi or (a.province and b.province and a.province != b.province):
        return False
    pa, pb = _parcel(a), _parcel(b)
    if (pa and pb and pa != pb) or _area_conflict(a, b) or _ward_conflict(a, b):
        return False
    parcel_eq, gcn_eq, area_eq = bool(pa and pa == pb), bool(a.gcn & b.gcn), _same_area(a, b)
    ward_eq = bool(a.info.ward and b.info.ward and _core_ward(a.info.ward) == _core_ward(b.info.ward))
    owner_eq = bool(_owner_key(a.owner) and _owner_key(a.owner) == _owner_key(b.owner))
    hard = parcel_eq or gcn_eq
    if _same_day(a, b) and not hard:
        return False                                  # cùng ngày đấu giá: thường là các lô khác nhau của 1 cuộc
    if not hard and not _price_ok(a, b):
        return False
    if parcel_eq and (area_eq or gcn_eq or ward_eq or owner_eq):
        return True
    if gcn_eq and (parcel_eq or area_eq) and not (bool(pa) != bool(pb)):
        return True
    (wa, na), (wb, nb) = sig[a.nid], sig[b.nid]
    sim = len(wa & wb) / len(wa | wb) if wa and wb else 0.0
    place_ok = ward_eq or (not a.info.ward and not b.info.ward and a.province and a.province == b.province)
    if area_eq and ward_eq and (owner_eq or sim >= 0.7) and na == nb:
        return True
    # tin đấu lại gần như y hệt (chỉ khác "lần N", ngày, giá): cùng chủ, cùng nơi, mọi con số trong mô tả trùng nhau
    return bool(owner_eq and place_ok and sim >= 0.9 and na and na == nb)


def _auto_merge(items: list[Item], dsu: DSU) -> None:
    """Gộp TỰ ĐỘNG các tin cùng một BĐS (xem same_property). Ghép cặp trong các nhóm: cùng tờ/thửa, cùng số GCN,
    cùng diện tích, cùng chủ + xã/phường. Người dùng đã tách riêng (khoá tay) thì DSU không gộp."""
    pool = [it for it in items if not it.info.multi]
    sig = {it.nid: _title_sig(it) for it in pool}
    blocks: dict[tuple, list[Item]] = defaultdict(list)
    for it in pool:
        if (pc := _parcel(it)) and it.province:
            blocks[("t", it.province, *pc)].append(it)
        for g in it.gcn:
            blocks[("g", g)].append(it)
        if (ar := _area(it)) and it.province:
            blocks[("a", it.province, round(ar))].append(it)
        if (ok := _owner_key(it.owner)) and it.province:
            blocks[("o", it.province, ok, _core_ward(it.info.ward))].append(it)
    for grp in blocks.values():
        if len(grp) < 2 or len(grp) > 400:
            continue
        for i, a in enumerate(grp):
            for b in grp[i + 1:]:
                if dsu.find(a.nid) != dsu.find(b.nid) and same_property(a, b, sig):
                    dsu.union(a.nid, b.nid)


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
        rows = s.execute(select(PropertyNotice.notice_id, PropertyNotice.property_id, PropertyNotice.manual,
                                PropertyNotice.link_source)).all()
    links = {nid: (pid, man) for nid, pid, man, _ in rows}
    manual = {nid: pid for nid, pid, man, src in rows if man and src == "manual"}           # người dùng gộp/tách
    pinned = {nid: pid for nid, pid, man, src in rows if man and src != "manual"}           # máy tự khoá
    clusters = cluster(items, manual, pinned)
    known = known_wards(items)
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
            _apply(s, prop, members, pn_all, pn_by_prop, known)
        # tài sản không còn thông báo nào và không có dữ liệu người dùng -> xoá
        s.flush()
        for prop in s.scalars(select(Property).where(~Property.links.any())).all():
            has_user_data = s.scalar(select(Comment.id).where(Comment.property_id == prop.id).limit(1)) or \
                s.scalar(select(PropertyFile.id).where(PropertyFile.property_id == prop.id).limit(1))
            if not has_user_data:
                s.delete(prop)
    return stats


DOC_LABELS = {"land_area": "tổng diện tích", "residential_area": "diện tích đất ở",
              "other_land_area": "diện tích đất khác", "floor_area": "diện tích sàn",
              "width": "chiều ngang", "length": "chiều dài", "map_sheet": "số tờ", "parcel_no": "số thửa"}


def _same(a, b) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return ward_key(str(a)).lstrip("0") == ward_key(str(b)).lstrip("0")
    return abs(float(a) - float(b)) <= 0.05


def _doc_value(members: list[Item], f: str, label: str, portal, notes: list[str]):
    """Giá trị 1 trường, ƯU TIÊN file đính kèm (xem docs/QUY_UOC_GIA_PHIEN.md mục 5):
    - tài liệu các phiên ghi khác nhau -> để trống;
    - tài liệu đọc từ lớp chữ (PDF chữ/.docx) -> dùng, kể cả khi khác tin đăng (ghi chú chênh lệch);
    - tài liệu đọc bằng OCR mà khác tin đăng -> dùng tin đăng (OCR có thể đọc nhầm số), ghi chú;
    - không có tài liệu -> giá trị từ tin đăng.  Trả (giá trị, nguồn) với nguồn 'tài liệu' | 'tài liệu (OCR)' | None."""
    if any(m.info.multi for m in members):
        return portal, None                          # tin nhiều thửa/lô: không ghép số liệu tài liệu
    docs = [(m.doc[f], (m.doc.get("methods") or {}).get(f, "ocr")) for m in members
            if m.doc and m.doc.get(f) not in (None, "")]
    if not docs:
        return portal, None
    v = docs[0][0]
    if not all(_same(v, x) for x, _ in docs):
        notes.append(f"Tài liệu các phiên ghi {label} khác nhau – để trống")
        return None, None
    method = "text" if any(mm == "text" for _, mm in docs) else "ocr"
    if portal not in (None, "") and not _same(v, portal):
        if method == "ocr":                       # OCR có thể đọc nhầm số -> dùng số trên tin đăng (gõ tay, chính xác)
            notes.append(f"Tài liệu (OCR) ghi {label} {v}, tin đăng ghi {portal} – dùng tin đăng")
            return portal, None
        notes.append(f"Tin đăng ghi {label} {portal}, tài liệu ghi {v} – dùng số trong tài liệu")
    return v, "tài liệu" if method == "text" else "tài liệu (OCR)"


def _lev1(a: str, b: str) -> bool:
    """a, b khác nhau tối đa 1 ký tự (thêm/bớt/thay) – sửa lỗi OCR nhỏ trong tên xã/phường."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return a[i + 1:] == b[i + 1:] or a[i + 1:] == b[i:] or a[i:] == b[i + 1:]


def known_wards(items: list[Item]) -> dict[str, dict[str, str]]:
    """Tên xã/phường đã gặp trong tin đăng (chữ gõ, tin cậy) theo tỉnh: {tỉnh: {khoá bỏ dấu: tên chuẩn}}."""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for it in items:
        if it.info.ward and it.province:
            d = out[it.province]
            k = ward_key(it.info.ward)
            if k not in d or it.info.ward_new:
                d[k] = it.info.ward
    return out


def canon_ward(w: str | None, province: str | None, known: dict) -> str | None:
    """Đối chiếu tên xã/phường đọc bằng OCR với tên đã biết trong cùng tỉnh: trùng (bỏ dấu) hoặc sai đúng 1 ký tự với
    DUY NHẤT một tên -> trả tên chuẩn; không đối chiếu được -> None (không dùng)."""
    if not w:
        return None
    d = known.get(province or "", {})
    k = ward_key(w)
    if k in d:
        return d[k]
    close = [v for kk, v in d.items() if len(k) >= 6 and _lev1(k, kk)]
    return close[0] if len(close) == 1 else None


_UBND_RE = re.compile(r"(?:ubnd|[uủ]y\s*ban\s*nh[âa]n\s*d[âa]n)\s+((?:xã|phường|thị trấn|đặc khu)\s+[^,;()|\n]+)", re.I)


def commune_owner(owner: str | None) -> tuple[str | None, str | None]:
    """Người có tài sản là "UBND xã/phường X[, tỉnh Y]" -> (Xã X, Y). Chỉ UBND cấp xã."""
    m = _UBND_RE.search(owner or "")
    if not m:
        return None, None
    loc = clause_location(owner[m.start(1):])
    return (loc.wards[0] if loc.wards else None), loc.province


def _location(members: list[Item], known: dict, notes: list[str]) -> tuple[str | None, str | None, dict, list]:
    """Xã/phường + tỉnh của tài sản. Nguồn: tin đăng (ô nơi có tài sản + cụm 'tọa lạc tại…') và file đính kèm.
    Tên '(nay là …)' thắng tên cũ; tài liệu chữ thắng tin đăng; OCR chỉ dùng khi đối chiếu được với tên đã biết.
    Trả (xã, tỉnh, nguồn các trường lấy từ tài liệu, ứng viên để xác nhận khi còn trống)."""
    srcs: dict = {}
    cands = [c for m in members for c in (m.info.loc_candidates or [])]
    # tin đăng: tên mới trước; các phiên cùng thời kỳ tên phải khớp
    # các phiên ghi khác nhau -> lấy theo PHIÊN GẦN NHẤT (tự xác nhận, không cần duyệt tay)
    recent = sorted(members, key=lambda m: (m.auction_date or datetime.min, m.publish_date or datetime.min.date()),
                    reverse=True)
    pw, pnew = None, False
    for era in (True, False):
        vals = [m for m in recent if m.info.ward and m.info.ward_new == era]
        if vals:
            pw, pnew = vals[0].info.ward, era
            if len({ward_key(m.info.ward) for m in vals}) > 1:
                notes.append(f"Các phiên ghi xã/phường khác nhau – lấy theo phiên gần nhất ({pw})")
            break
    pp = next((m.province for m in recent if m.province), None)
    if len({m.province for m in members if m.province}) > 1:
        notes.append(f"Các phiên ghi tỉnh/thành khác nhau – lấy theo phiên gần nhất ({pp})")
    docs = [m.doc for m in members if m.doc and not m.info.multi]
    # tỉnh từ tài liệu
    dps = {d["province"] for d in docs if d.get("province")}
    if len(dps) == 1:
        dp = next(iter(dps))
        dmeth = "text" if any((d.get("methods") or {}).get("province") == "text" for d in docs if d.get("province")) else "ocr"
        if pp and pp != dp:
            cands.append({"ward": None, "province": dp, "source": "tài liệu", "new": False})
            if dmeth == "text":
                notes.append(f"Tin đăng ghi {pp}, tài liệu ghi {dp} – dùng tài liệu")
                pp = dp
                srcs["province"] = "tài liệu"
            else:
                notes.append(f"Tài liệu (OCR) ghi tỉnh {dp}, tin đăng ghi {pp} – dùng tin đăng")
        elif not pp:
            pp, srcs["province"] = dp, "tài liệu" if dmeth == "text" else "tài liệu (OCR)"
    # xã/phường từ tài liệu
    dws = [(d["ward"], bool(d.get("ward_new")), (d.get("methods") or {}).get("ward", "ocr")) for d in docs if d.get("ward")]
    if dws:
        era = any(n for _, n, _ in dws)
        dws = [x for x in dws if x[1] == era]
        dw = dws[0][0] if len({ward_key(w) for w, _, _ in dws}) == 1 else None
        dmeth = "text" if any(mm == "text" for _, _, mm in dws) else "ocr"
        if dw and dmeth == "ocr":
            cw = canon_ward(dw, pp, known)
            cands.append({"ward": dw, "province": pp, "source": "tài liệu (OCR)", "new": era})
            dw = cw
        elif dw:
            cands.append({"ward": dw, "province": pp, "source": "tài liệu", "new": era})
        if dw:
            if pw is None or (era and not pnew):
                pw, srcs["ward"] = dw, "tài liệu" if dmeth == "text" else "tài liệu (OCR)"
            elif era == pnew and ward_key(dw) != ward_key(pw):
                if dmeth == "text":
                    notes.append(f"Tin đăng ghi {pw}, tài liệu ghi {dw} – dùng tài liệu")
                    pw, srcs["ward"] = dw, "tài liệu"
                else:
                    notes.append(f"Tài liệu (OCR) ghi {dw}, tin đăng ghi {pw} – dùng tin đăng")
    seen, uniq = set(), []
    for c in cands:
        k = (ward_key(c.get("ward")), c.get("province"))
        if k not in seen and (c.get("ward") or c.get("province")):
            seen.add(k)
            uniq.append(c)
    # tin không ghi xã/tỉnh nhưng người có tài sản là UBND cấp xã: UBND xã chỉ bán tài sản trên địa bàn mình -> lấy xã
    # (và tỉnh nếu tên đơn vị ghi tỉnh). KHÔNG áp dụng cho cơ quan thi hành án (có thể xử lý tài sản ở nơi khác).
    if pw is None or pp is None:
        ow, op = commune_owner(recent[0].owner if recent else None)
        if pw is None and ow and not any(m.info.wards_seen for m in members):
            pw, srcs["ward"] = ow, "đơn vị có tài sản (UBND xã)"
            notes.append(f"Xã/phường lấy theo người có tài sản: UBND {ow}")
        if pp is None and op:
            pp, srcs["province"] = op, "đơn vị có tài sản (UBND xã)"
    if pw and pp:                                    # tên cũ (tài liệu/UBND xã) -> tên sau sắp xếp 2025
        nw = wardmap.load().to_new(pw, pp, "\n".join(filter(None, (recent[0].address, recent[0].title))) if recent else "")
        if nw:
            notes.append(f"{pw} nay là {nw} (danh sách sắp xếp xã/phường 2025)")
            pw = nw
    return pw, pp, srcs, uniq


def _all_locations(prop: Property, members: list[Item]) -> tuple[str | None, str | None]:
    """Tin bán NHIỀU tài sản ở nhiều nơi: liệt kê MỌI xã/phường, tỉnh (để lọc theo nơi nào cũng ra).
    Trả (chuỗi hiển thị "Xã A, Xã B – Tỉnh X; …" khi nhiều nơi, chỉ mục "|Tỉnh|Xã A|…|" để lọc)."""
    pairs: list[tuple[str | None, str | None]] = []
    for m in members:
        for pl in m.places:
            loc = clause_location(pl)
            for w in loc.wards or [None]:
                if w or loc.province:
                    pairs.append((w, loc.province))
        if not m.places:
            pairs += [(c.get("ward"), c.get("province")) for c in (m.info.loc_candidates or [])]
    if prop.ward:
        pairs = [(prop.ward, prop.province)]           # đã xác định một nơi
    provs = list(dict.fromkeys(pv for _, pv in pairs if pv))
    if len(provs) == 1:
        pairs = [(w, pv or provs[0]) for w, pv in pairs]
    elif prop.province and not provs:
        pairs = [(w, prop.province) for w, _ in pairs]
    by_prov: dict[str, dict[str, str]] = defaultdict(dict)
    wm = wardmap.load()
    for w, pv in pairs:
        d = by_prov[pv or ""]
        w = (wm.to_new(w, pv) or w) if w and pv and wm else w
        if w:
            d.setdefault(_core_ward(w), w)
    names = {n for pv, d in by_prov.items() for n in (pv, *d.values()) if n}
    if prop.province:
        names.add(prop.province)
    index = ("|" + "|".join(sorted(names)) + "|") if names else None
    n_wards = sum(len(d) for d in by_prov.values())
    if n_wards <= 1 and len([p for p in by_prov if p]) <= 1:
        return None, index
    text = "; ".join(f"{', '.join(d.values()) or '(xã chưa rõ)'} – {pv or 'tỉnh chưa rõ'}" for pv, d in by_prov.items())
    return f"Nhiều nơi: {text}"[:500], index


def _apply(s, prop: Property, members: list[Item], pn_all: dict, pn_by_prop: dict, known: dict | None = None) -> None:
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

    prop.ward, prop.province, loc_src, loc_cands = _location(members, known or {}, notes)
    by_recent = sorted(members, key=lambda x: x.auction_date or datetime.min, reverse=True)
    prop.address = next((m.address for m in by_recent if m.address), None)
    if prop.sale_form == "khoan_no":            # khoản nợ: địa chỉ tài sản bảo đảm (ghi rõ) thay cho địa chỉ ngân hàng
        prop.address = next((f"TSBĐ: {m.info.collateral_address}" for m in by_recent
                             if m.info.collateral_address), prop.address)
    sources: dict[str, str] = {}
    for f, lbl in DOC_LABELS.items():
        portal = agree(lambda m, f=f: getattr(m.info, f), lbl)
        val, src = _doc_value(members, f, lbl, portal, notes)
        setattr(prop, f, val)
        if src:
            sources[f] = src
    sources.update(loc_src)
    prop.field_sources = sources
    prop.loc_multi, prop.loc_index = _all_locations(prop, members)
    prop.loc_candidates = loc_cands[:8] if (prop.ward is None or prop.province is None) and loc_cands else None
    parcels = []
    for m in members:
        for p_ in m.info.parcels:
            if list(p_) not in parcels:
                parcels.append(list(p_))
    prop.parcels = parcels[:30]
    for m in members:
        notes += m.info.notes
        notes += [f"Tài liệu: {x}" for x in (m.doc or {}).get("notes") or []]
    if any((m.property_count or 1) > 1 for m in members):
        notes.append("Thông báo gồm nhiều tài sản, mỗi tài sản một giá – giá để trống (xem bảng tài sản), nhập tay nếu cần")
    if not prop.province and prop.sale_form != "khoan_no":
        notes.append("Tin không ghi rõ tỉnh/thành nơi có tài sản")
    prop.auto_notes = list(dict.fromkeys(notes))[:12]
    prop.session_count = len(sessions)
    prop.session_hint_max = max((m.info.session_hint for m in members if m.info.session_hint), default=None)
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
