"""Quét lịch sử giá cho tài sản CÒN HẠN ĐĂNG KÝ: tìm các phiên đấu giá cũ (kể cả ngoài khoảng thời gian
đã thu thập) bằng từ khoá đặc trưng lấy từ tên/mô tả tài sản, KIỂM CHỨNG CHẶT rồi gắn vào tài sản.

Quy ước (xem docs/QUY_UOC_GIA_PHIEN.md):
- Chỉ quét tài sản còn hạn đăng ký (hạn đăng ký >= hiện tại). Tài sản đã hết hạn: không quét.
- Mỗi tài sản quét 1 lần; quét lại khi tài sản có phiên mới (ngày đăng mới hơn lần quét trước).
- Từ khoá theo độ đặc trưng: số giấy chứng nhận (vd "BR 234700") > tên chủ là cá nhân > "thửa đất số N".
- Chỉ nhận thông báo cũ khi:
    (1) cùng số giấy chứng nhận, và tờ/thửa không mâu thuẫn; hoặc
    (2) cùng đúng (tờ, thửa) + cùng tỉnh, và thêm ít nhất 1 điểm trùng: diện tích, xã/phường, tên chủ.
  Không đạt -> bỏ qua (không suy đoán). Thông báo nhiều tài sản (mỗi tài sản một giá) -> bỏ qua.
- Thông báo được nhận: lưu vào CSDL, lấy giá chính thức (dgts), gắn vào tài sản (link_source = 'history'),
  được giữ cố định khi gom phiên lại.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import case, or_, select

from ..classifier import RuleClassifier
from ..config import Settings
from ..normalize import strip_accents
from ..storage import AssetRow, NoticeRow, Repository
from .db import Property, PropertyNotice
from .extract import RealEstateInfo, extract

log = logging.getLogger(__name__)

GCN_RE = re.compile(r"\b([A-Z]{2})\s?(\d{6})\b")
TITLE_RE = re.compile(r"\b(?:ông|bà)\s+", re.I)


def person_name(text: str) -> str | None:
    """Tên cá nhân đầu tiên sau 'ông/bà': các từ viết hoa chữ đầu liền nhau (2-5 từ), vd 'Võ Minh Hùng'."""
    for m in TITLE_RE.finditer(text or ""):
        words = []
        for w in re.findall(r"[^\W\d_]+", text[m.end():m.end() + 60]):
            if not w[0].isupper():
                break
            words.append(w)
            if len(words) == 5:
                break
        if 2 <= len(words):
            return " ".join(words)
    return None
MAX_PAGES = {"gcn": 5, "chu": 2, "thua": 2}   # số trang kết quả tối đa theo loại từ khoá
PAGE_SIZE = 100


@dataclass
class ScanStats:
    scanned: int = 0
    found_notices: int = 0
    props_updated: int = 0
    errors: int = 0
    details: list[str] = field(default_factory=list)


def gcn_serials(text: str) -> set[str]:
    return {f"{a} {b}" for a, b in GCN_RE.findall(text or "")}


def keywords(text: str, info: RealEstateInfo) -> list[tuple[str, str]]:
    """[(loại, từ khoá)] theo thứ tự đặc trưng giảm dần."""
    out: list[tuple[str, str]] = []
    for s in sorted(gcn_serials(text))[:2]:
        out.append(("gcn", s))
    if name := person_name(text):
        out.append(("chu", name))
    if info.parcel_no and info.map_sheet and not out:
        out.append(("thua", f"thửa đất số {info.parcel_no}"))
    return out


def _norm_num(x: str | None) -> str | None:
    return x.lstrip("0") or "0" if x else None


def verify(p_text: str, p_info: RealEstateInfo, p_owner: str | None,
           c_text: str, c_info: RealEstateInfo, c_owner: str | None) -> str | None:
    """Lý do nhận (chuỗi) hoặc None nếu không đủ căn cứ."""
    if p_info.multi or c_info.multi:
        return None                                  # thông báo nhiều lô: không xác định được lô nào
    p_parcel = (_norm_num(p_info.map_sheet), _norm_num(p_info.parcel_no)) if p_info.parcel_no else None
    c_parcel = (_norm_num(c_info.map_sheet), _norm_num(c_info.parcel_no)) if c_info.parcel_no else None
    if bool(p_parcel) != bool(c_parcel) or (p_parcel and p_parcel != c_parcel):
        return None                                  # tờ/thửa mâu thuẫn hoặc chỉ một bên có -> không đủ căn cứ
    same_area = bool(p_info.land_area and c_info.land_area and abs(p_info.land_area - c_info.land_area) <= 0.5)
    shared = gcn_serials(p_text) & gcn_serials(c_text)
    # 1 giấy chứng nhận có thể chứa nhiều thửa/tài sản -> phải trùng thêm tờ/thửa (hoặc diện tích nếu cả 2 không ghi tờ/thửa)
    if shared and (p_parcel or same_area):
        return f"cùng số giấy chứng nhận {sorted(shared)[0]}" + (f", cùng tờ {p_parcel[0]} thửa {p_parcel[1]}"
                                                                 if p_parcel else ", cùng diện tích")
    if not (p_parcel and c_parcel and p_info.province and p_info.province == c_info.province):
        return None
    extra = []
    if same_area:
        extra.append("diện tích")
    if p_info.ward and c_info.ward and strip_accents(p_info.ward) == strip_accents(c_info.ward):
        extra.append("xã/phường")
    pn, cn = person_name(p_text), person_name(c_text)
    if pn and cn and strip_accents(pn) == strip_accents(cn):
        extra.append("tên chủ")
    if extra:
        return f"cùng tờ {p_parcel[0]} thửa {p_parcel[1]}, {p_info.province} + " + ", ".join(extra)
    return None


def _property_text(s, prop: Property) -> tuple[str, str | None, NoticeRow | None]:
    n = s.get(NoticeRow, prop.latest_notice_id) if prop.latest_notice_id else None
    if not n:
        return prop.title or "", prop.owner_name, None
    names = [a for a, in s.execute(select(AssetRow.name).where(AssetRow.notice_id == n.id)) if a]
    return " \n".join(x for x in [n.asset_name or n.title, *names] if x), n.asset_owner, n


def due_properties(s, limit: int) -> list[Property]:
    now = datetime.now()
    q = (select(Property).where(Property.registration_end >= now,
                                or_(Property.history_scanned_at.is_(None),
                                    Property.history_scanned_at < Property.publish_date))
         .order_by(case((Property.session_hint_max > Property.session_count, 0), else_=1),   # thiếu lịch sử trước
                   Property.priority.desc(), Property.registration_end.asc()).limit(limit))
    return s.scalars(q).all()


def scan_open_properties(settings: Settings, repo: Repository, limit: int = 500,
                         transport: Any = None) -> ScanStats:
    from ..pipeline import build_notice, make_fetcher
    from ..sources import get_source

    stats = ScanStats()
    src = get_source("dgts")
    fetcher = make_fetcher(settings, src, transport)
    clf = RuleClassifier()
    try:
        with repo.session() as s:
            pids = [p.id for p in due_properties(s, limit)]
        for pid in pids:
            try:
                found = _scan_one(pid, src, fetcher, repo, clf, build_notice)
                stats.scanned += 1
                if found:
                    stats.found_notices += found
                    stats.props_updated += 1
            except Exception as e:  # noqa: BLE001
                stats.errors += 1
                log.warning("Quét lịch sử #%s lỗi: %r", pid, e)
    finally:
        fetcher.close()
    log.info("Quét lịch sử: %s tài sản, thêm %s thông báo cũ cho %s tài sản, lỗi %s",
             stats.scanned, stats.found_notices, stats.props_updated, stats.errors)
    return stats


def _scan_one(pid: int, src, fetcher, repo: Repository, clf, build_notice) -> int:
    with repo.session() as s:
        prop = s.get(Property, pid)
        p_text, p_owner, latest = _property_text(s, prop)
        linked = {nid for nid, in s.execute(select(PropertyNotice.notice_id).where(PropertyNotice.property_id == pid))}
        linked_src = {sid for sid, in s.execute(select(NoticeRow.source_id).where(
            NoticeRow.id.in_(linked), NoticeRow.source == "dgts"))} if linked else set()
    p_info = extract(p_text[:300], p_text, latest.address if latest else None)
    if p_info.multi:
        with repo.Session.begin() as s:
            prop = s.get(Property, pid)
            prop.history_scanned_at = datetime.now()
            prop.history_note = "thông báo gồm nhiều lô – không quét lịch sử (không xác định được lô)"
        return 0
    keys = keywords(p_text, p_info)
    accepted: dict[str, tuple[dict, str]] = {}
    for kind, kw in keys:
        for page in range(1, MAX_PAGES.get(kind, 2) + 1):
            data = src.search(fetcher, page, PAGE_SIZE, assetName=kw)
            rows = data.get("items") or []
            for r in rows:
                sid = str(r["id"])
                if sid in linked_src or sid in accepted:
                    continue
                it = src.row_to_item(r)
                c_text = it.get("asset_name") or it.get("title") or ""
                c_info = extract(c_text[:300], c_text)
                reason = verify(p_text, p_info, p_owner, c_text, c_info, it.get("asset_owner"))
                if reason:
                    accepted[sid] = (it, reason)
            if page >= (data.get("pageCount") or 0) or not rows:
                break
        if accepted and kind == "gcn":
            break                                    # đã có kết quả từ từ khoá mạnh nhất
    added = skipped = 0
    for sid, (it, reason) in accepted.items():
        with repo.session() as s:      # thông báo đã thuộc tài sản khác -> không giành (dấu hiệu từ khoá không duy nhất)
            other = s.execute(select(PropertyNotice.property_id).join(NoticeRow, NoticeRow.id == PropertyNotice.notice_id)
                              .where(NoticeRow.source == "dgts", NoticeRow.source_id == sid,
                                     PropertyNotice.property_id != pid)).first()
        if other:
            skipped += 1
            continue
        det = src.enrich(fetcher, it)
        if (det.get("property_count") or 1) > 1:
            continue                                 # nhiều tài sản, mỗi tài sản một giá -> không dùng
        n = build_notice("dgts", det, clf)
        repo.upsert(n)
        with repo.Session.begin() as s:
            nid = s.scalar(select(NoticeRow.id).where(NoticeRow.source == "dgts", NoticeRow.source_id == sid))
            pn = s.scalar(select(PropertyNotice).where(PropertyNotice.notice_id == nid))
            if pn is None:
                pn = PropertyNotice(notice_id=nid, property_id=pid)
                s.add(pn)
            pn.property_id, pn.manual, pn.link_source = pid, True, "history"
            # khoá các phiên hiện có vào tài sản để khi gom lại, phiên cũ và phiên hiện tại luôn đi cùng nhau
            for cur in s.scalars(select(PropertyNotice).where(PropertyNotice.property_id == pid)):
                cur.manual = True
                if cur.link_source is None:
                    cur.link_source = "auto"
            row = s.get(NoticeRow, nid)
            row.raw = {**(row.raw or {}), "history_reason": reason}
        added += 1
    with repo.Session.begin() as s:
        prop = s.get(Property, pid)
        prop.history_scanned_at = datetime.now()
        if not keys:
            prop.history_note = "không có từ khoá đặc trưng để tìm phiên cũ"
        elif added:
            prop.history_note = f"tìm thêm {added} thông báo cũ (từ khoá: {', '.join(k for _, k in keys)})"
            if skipped:
                prop.history_note += f"; bỏ qua {skipped} thông báo đang thuộc tài sản khác"
        else:
            prop.history_note = f"không tìm thấy phiên cũ hơn (từ khoá: {', '.join(k for _, k in keys)})"
    return added
