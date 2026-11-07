"""Phát hiện cùng một cuộc đấu giá được đăng ở cả 2 nguồn (để thống kê không bị đếm trùng).

Quy tắc: cùng thời điểm đấu giá (đến phút) + tên tổ chức đấu giá gần giống + tên tài sản
có độ trùng từ (Jaccard) >= ngưỡng. Kết quả ghi vào notices.dup_group = id nhỏ nhất của nhóm.
"""
from __future__ import annotations

import re
from collections import defaultdict

from sqlalchemy import select, update

from .normalize import strip_accents
from .storage import NoticeRow, Repository

STOP = set("dau gia tai san thong bao viec cua tai cac va la so ve ban doi voi danh muc tinh xa phuong huyen".split())


def _tokens(s: str | None) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", strip_accents(s or "")) if len(w) > 1 and w not in STOP}


def _org_key(s: str | None) -> str:
    t = strip_accents(s or "")
    t = re.sub(r"\b(cong ty|dau gia|hop danh|tnhh|trung tam|dich vu|tai san|chi nhanh|so)\b", " ", t)
    return re.sub(r"[^a-z0-9]", "", t)[:24]


def find_duplicates(repo: Repository, threshold: float = 0.35) -> int:
    with repo.session() as s:
        rows = s.execute(select(NoticeRow.id, NoticeRow.source, NoticeRow.auction_date, NoticeRow.auction_org,
                                NoticeRow.asset_name, NoticeRow.title)
                         .where(NoticeRow.auction_date.is_not(None))).all()
    buckets: dict[tuple, list] = defaultdict(list)
    for r in rows:
        buckets[(r.auction_date.replace(second=0, microsecond=0), _org_key(r.auction_org))].append(r)
    groups: dict[int, int] = {}
    for items in buckets.values():
        if len({r.source for r in items}) < 2:
            continue
        toks = {r.id: _tokens(r.asset_name or r.title) for r in items}
        for i, a in enumerate(items):
            for b in items[i + 1:]:
                if a.source == b.source:
                    continue
                ta, tb = toks[a.id], toks[b.id]
                if ta and tb and len(ta & tb) / len(ta | tb) >= threshold:
                    g = min(groups.get(a.id, a.id), groups.get(b.id, b.id), a.id, b.id)
                    groups[a.id] = groups[b.id] = g
    with repo.Session.begin() as s:
        s.execute(update(NoticeRow).values(dup_group=None))
        for nid, g in groups.items():
            s.execute(update(NoticeRow).where(NoticeRow.id == nid).values(dup_group=g))
    return len(groups)
