"""Gợi ý gộp phiên: tìm các cặp tài sản nghi là CÙNG một BĐS mà bước gom phiên tự động chưa gộp
(vì thiếu căn cứ chắc chắn). Máy chỉ GỢI Ý – người dùng bấm "Đồng ý" mới gộp, "Không phải" thì không gợi ý lại.

Chỉ xét tài sản CÒN HẠN đăng ký (a) với tài sản có phiên SỚM HƠN (b). Cần ít nhất 2 dấu hiệu trùng:
cùng tờ+thửa, cùng diện tích đất, cùng xã/phường, cùng chủ tài sản, mô tả gần giống, cùng số giấy chứng nhận.
Loại: khác tỉnh; tờ/thửa mâu thuẫn; tin nhiều thửa; phiên cũ rẻ hơn phiên mới > 5% (giá đấu lại thường giảm).
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from ..normalize import strip_accents
from ..storage import NoticeRow, Repository
from .db import MergeSuggestion, Property
from .history import gcn_serials

STOP = set("quyen su dung dat va tai san gan lien voi tai thua so to ban do tinh huyen xa phuong thi tran thanh pho "
           "quan khu pho ap thon to dan cua ong ba cong ty tnhh dia chi the dien tich m2 nha o".split())


@dataclass
class P:
    id: int
    province: str | None
    ward: str | None
    sheet: str | None
    parcel: str | None
    area: float | None
    owner: str
    words: frozenset
    gcn: frozenset
    price: int | None
    when: datetime | None
    open: bool
    multi: bool


def _norm(x) -> str | None:
    return (str(x).lstrip("0") or "0") if x not in (None, "") else None


def _words(t: str) -> frozenset:
    return frozenset(w for w in re.findall(r"[a-z0-9]+", strip_accents(t or "")) if w not in STOP and len(w) > 1)


def _owner(t: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", strip_accents(t or ""))[:40]


def load(repo: Repository) -> list[P]:
    now = datetime.now()
    out = []
    with repo.session() as s:
        texts = {i: t for i, t in s.execute(select(NoticeRow.id, NoticeRow.asset_name))}
        for p in s.scalars(select(Property)):
            text = f"{p.title} {texts.get(p.latest_notice_id) or ''}"
            out.append(P(p.id, p.eff("province"), p.eff("ward"), _norm(p.eff("map_sheet")), _norm(p.eff("parcel_no")),
                         p.eff("land_area"), _owner(p.owner_name), _words(p.title), frozenset(gcn_serials(text)),
                         p.eff("price_latest"), p.auction_date, bool(p.registration_end and p.registration_end >= now),
                         len(p.parcels or []) > 1))
    return out


def score_pair(a: P, b: P) -> tuple[int, list[str]] | None:
    if a.multi or b.multi or not a.province or a.province != b.province:
        return None
    if a.parcel and b.parcel and (a.parcel, a.sheet) != (b.parcel, b.sheet):
        return None                                           # tờ/thửa mâu thuẫn
    if a.price and b.price and b.price < a.price * 0.95:
        return None                                           # phiên cũ rẻ hơn hẳn -> khó là cùng BĐS đấu lại
    why = []
    if a.parcel and a.parcel == b.parcel and a.sheet and a.sheet == b.sheet:
        why.append(f"cùng tờ {a.sheet} thửa {a.parcel}")
    if a.gcn & b.gcn:
        why.append(f"cùng số giấy chứng nhận {sorted(a.gcn & b.gcn)[0]}")
    if a.area and b.area and abs(a.area - b.area) <= 0.5:
        why.append(f"cùng diện tích {a.area:g} m²")
    if a.ward and a.ward == b.ward:
        why.append(f"cùng {a.ward}")
    if a.owner and a.owner == b.owner:
        why.append("cùng chủ tài sản")
    if a.words and b.words:
        sim = len(a.words & b.words) / len(a.words | b.words)
        if sim >= 0.75:
            why.append(f"mô tả giống {round(sim * 100)}%")
    hard = [w for w in why if w.startswith(("cùng tờ", "cùng số giấy", "cùng diện tích"))]
    if len(why) < 2 or not hard:
        return None                                           # phải có ít nhất 1 dấu hiệu "cứng"
    if hard == [w for w in why if w.startswith("cùng diện tích")] and a.area % 5 == 0 and len(why) < 3:
        return None                                           # diện tích chẵn (100, 120 m²…) dễ trùng -> cần thêm căn cứ
    return len(why), why


def compute(repo: Repository, limit: int = 2000) -> int:
    """Tạo gợi ý mới (giữ nguyên gợi ý đã quyết). Trả số gợi ý mới."""
    props = load(repo)
    by_key: dict[tuple, list[P]] = defaultdict(list)
    for p in props:
        if p.parcel:
            by_key[("t", p.province, p.sheet, p.parcel)].append(p)
        if p.area:
            by_key[("a", p.province, round(p.area))].append(p)
        for g in p.gcn:
            by_key[("g", g)].append(p)
    found: dict[tuple[int, int], tuple[int, str]] = {}
    for a in (p for p in props if p.open):
        cands = {b.id: b for k in _keys(a) for b in by_key.get(k, []) if b.id != a.id}
        for b in cands.values():
            if b.when and a.when and b.when >= a.when:
                continue                                      # chỉ ghép với phiên SỚM HƠN
            r = score_pair(a, b)
            if r:
                found[(a.id, b.id)] = (r[0], ", ".join(r[1]))
    with repo.Session.begin() as s:
        known = {(m.a_id, m.b_id) for m in s.scalars(select(MergeSuggestion))}
        known |= {(b, a) for a, b in known}
        new = 0
        for (a, b), (sc, why) in sorted(found.items(), key=lambda x: -x[1][0])[:limit]:
            if (a, b) in known:
                continue
            s.add(MergeSuggestion(a_id=a, b_id=b, score=sc, reason=why))
            new += 1
        # gợi ý chờ duyệt mà 2 tài sản đã gộp/xoá -> bỏ
        ids = {p.id for p in props}
        for m in s.scalars(select(MergeSuggestion).where(MergeSuggestion.status == "pending")):
            if m.a_id not in ids or m.b_id not in ids:
                s.delete(m)
    return new


def _keys(a: P):
    if a.parcel:
        yield ("t", a.province, a.sheet, a.parcel)
    if a.area:
        for d in (-1, 0, 1):
            yield ("a", a.province, round(a.area) + d)
    for g in a.gcn:
        yield ("g", g)
