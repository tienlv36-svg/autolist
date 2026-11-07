"""Lấy danh sách tài liệu gốc (quy chế, thông báo PDF...) từ website nguồn vào thư mục tài sản.
Chạy khi mở trang chi tiết lần đầu (mỗi thông báo 1 lần), file mở bằng link gốc - không tải về máy chủ."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import httpx
from sqlalchemy import select

from ..realestate.db import Property, PropertyFile, PropertyNotice
from ..storage import NoticeRow


def needs_sync(s, prop: Property) -> bool:
    return any(n.source == "dgts" and not (n.raw or {}).get("files_synced") or
               n.source == "taisancong" and (n.raw or {}).get("attachments") and not (n.raw or {}).get("files_synced")
               for n in _notices(s, prop))


def _notices(s, prop: Property) -> list[NoticeRow]:
    return s.scalars(select(NoticeRow).join(PropertyNotice, PropertyNotice.notice_id == NoticeRow.id)
                     .where(PropertyNotice.property_id == prop.id)).all()


def _dgts_files(source_id: str, ua: str) -> list[tuple[str, str]]:
    r = httpx.get("https://dgts.moj.gov.vn/portal/viewDetailAuctionInfo", params={"auctionInfoId": source_id},
                  timeout=15, headers={"User-Agent": ua})
    r.raise_for_status()
    out = []
    for f in (r.json() or {}).get("listFile") or []:
        if f.get("linkFile"):
            out.append((f["fileName"], f"https://dgts.moj.gov.vn/common/download?name={quote(f['fileName'])}"
                                       f"&path={quote(f['linkFile'])}"))
    return out


def sync_source_docs(s, prop: Property, settings) -> bool:
    """Đồng bộ tài liệu nguồn cho mọi thông báo của tài sản (gọi mạng song song, 4 luồng)."""
    existing = s.scalars(select(PropertyFile).where(PropertyFile.property_id == prop.id,
                                                    PropertyFile.source_url.is_not(None))).all()
    have = {f.source_url for f in existing} | {f.filename for f in existing}   # dgts đăng trùng: cùng tên file
    todo = [n for n in _notices(s, prop) if not (n.raw or {}).get("files_synced")]
    dgts = [n for n in todo if n.source == "dgts"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        fetched = dict(zip([n.id for n in dgts],
                           pool.map(lambda n: _safe(_dgts_files, n.source_id, settings.http.user_agent), dgts)))
    changed = False
    for n in todo:
        raw = dict(n.raw or {})
        if n.source == "taisancong":
            docs = [(u.rsplit("/", 1)[-1], u) for u in raw.get("attachments") or []]
        else:
            docs = fetched.get(n.id)
            if docs is None:      # lỗi mạng -> thử lại lần mở sau
                continue
        for name, url in docs:
            if url not in have and name[:255] not in have:
                s.add(PropertyFile(property_id=prop.id, folder=f"Tài liệu nguồn ({n.source})", kind="document",
                                   filename=name[:255], source_url=url))
                have.update({url, name[:255]})
        raw["files_synced"] = True
        n.raw = raw
        changed = True
    return changed


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception:  # noqa: BLE001
        return None
