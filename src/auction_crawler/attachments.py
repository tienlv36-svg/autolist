"""Tải, LƯU LẠI và đọc file đính kèm (thông báo, quy chế đấu giá...) của các tin BĐS.

- Mọi file tải về được giữ trong data/files/<nguồn>/<năm-tháng>/<mã tin>/ (không xoá), kèm file .txt chứa
  chữ đọc được. PDF có lớp chữ -> đọc thẳng; PDF scan / ảnh -> OCR Tesseract tiếng Việt; .docx -> đọc XML.
- Từ chữ của tài liệu, trích thông số tài sản theo ĐÚNG quy tắc thận trọng của bộ trích xuất (chỉ nhận khi có
  nhãn rõ và một giá trị). Kết quả mỗi tin lưu ở notices.doc_info; bước gom phiên ưu tiên số liệu từ tài liệu.
- CHỈ tài sản CÒN HẠN đăng ký (mọi phiên của tài sản đó, kể cả phiên cũ), ưu tiên cao / sắp hết hạn trước.
  Tài sản đã hết hạn: không tải; khi có phiên mới (tài sản còn hạn trở lại) thì tải bổ sung ở lượt sau.
- Mỗi lượt chạy có giới hạn thời gian; ổ cứng quá ngưỡng -> dừng tải, báo cáo.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, and_, case, func, select
from sqlalchemy.orm import Mapped, mapped_column

from .config import Settings
from .http_client import is_outage
from .normalize import strip_accents
from .realestate.extract import RealEstateInfo, _one, asset_location, extract, ward_key
from .storage import Base, NoticeRow, Repository

log = logging.getLogger(__name__)

DOC_FIELDS = ("land_area", "residential_area", "other_land_area", "floor_area", "width", "length",
              "map_sheet", "parcel_no")
MAX_BYTES = 60 * 1024 * 1024
TEXT_EXT = {".pdf", ".docx", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}


class NoticeFile(Base):
    """Một file đính kèm của một thông báo, đã tải về và lưu trên máy chủ."""
    __tablename__ = "notice_files"
    __table_args__ = (UniqueConstraint("notice_id", "url", name="uq_notice_file"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("notices.id", ondelete="CASCADE"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    path: Mapped[str | None] = mapped_column(Text)          # tương đối so với thư mục data/
    size: Mapped[int | None] = mapped_column(Integer)
    sha1: Mapped[str | None] = mapped_column(String(40))
    method: Mapped[str | None] = mapped_column(String(16))  # text | ocr | docx | none | unsupported
    chars: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    info: Mapped[dict[str, Any] | None] = mapped_column(JSON)   # thông số trích từ file này
    orig_size: Mapped[int | None] = mapped_column(Integer)      # dung lượng gốc trước khi nén (đã nén -> có giá trị)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)   # chỉ giữ chữ (.txt), bỏ file gốc (tài sản đã hết hạn)


@dataclass
class DocStats:
    notices: int = 0
    files: int = 0
    bytes: int = 0
    ocr_files: int = 0
    with_info: int = 0
    errors: int = 0
    saved: int = 0                 # byte tiết kiệm nhờ nén
    stopped: str | None = None
    details: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ nén bản scan
COMPRESS_MIN = 1_500_000          # chỉ nén PDF > 1,5 MB


def gs_available() -> bool:
    return bool(shutil.which("gs"))


def compress_pdf(path: Path) -> int | None:
    """Nén PDF (chủ yếu bản scan) bằng Ghostscript, ảnh 150 dpi – vẫn đọc rõ. Thay file gốc khi nhỏ hơn ≥ 20%.
    Trả dung lượng mới, hoặc None nếu không nén."""
    if path.suffix.lower() != ".pdf" or not gs_available() or not path.exists() or path.stat().st_size < COMPRESS_MIN:
        return None
    tmp = path.with_name(path.name + ".gs.pdf")
    try:
        r = subprocess.run(["nice", "-n", "10", "gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite",
                            "-dPDFSETTINGS=/ebook", "-dCompatibilityLevel=1.5", f"-sOutputFile={tmp}", str(path)],
                           capture_output=True, timeout=600)
        if r.returncode == 0 and tmp.exists() and 0 < tmp.stat().st_size < path.stat().st_size * 0.8:
            tmp.replace(path)
            return path.stat().st_size
    except Exception as e:  # noqa: BLE001
        log.debug("nén lỗi %s: %r", path, e)
    finally:
        tmp.unlink(missing_ok=True)
    return None


def prune_expired(settings: Settings, repo: Repository, days: int = 30, now: datetime | None = None) -> tuple[int, int]:
    """Dọn file gốc của tài sản đã HẾT HẠN đăng ký quá `days` ngày mà không ra phiên mới: xoá file, GIỮ chữ đã đọc (.txt)
    và thông số. Trừ tài sản đang trong giỏ hàng của ai đó hoặc mức ưu tiên Cao/Rất cao. Trả (số file, số byte)."""
    from .realestate.db import CartItem, Property, PropertyNotice
    if days <= 0:
        return 0, 0
    now = now or datetime.now()
    base = settings.path(settings.data_dir)
    keep = select(CartItem.property_id)
    with repo.session() as s:
        rows = s.execute(select(NoticeFile.id, NoticeFile.path, NoticeFile.size)
                         .join(PropertyNotice, PropertyNotice.notice_id == NoticeFile.notice_id)
                         .join(Property, Property.id == PropertyNotice.property_id)
                         .where(NoticeFile.path.is_not(None), NoticeFile.removed_at.is_(None),
                                Property.registration_end < now - timedelta(days=days),
                                Property.priority < 3, Property.id.not_in(keep))).all()
    n = freed = 0
    for fid, rel, size in rows:
        f = base / rel
        if f.exists():
            f.unlink()
            freed += size or 0
            n += 1
        with repo.Session.begin() as s:
            s.get(NoticeFile, fid).removed_at = now
    log.info("Dọn file tài sản hết hạn > %s ngày: %s file, %.1f GB", days, n, freed / 1e9)
    return n, freed


def compress_existing(settings: Settings, repo: Repository, minutes: float = 20) -> tuple[int, int]:
    """Nén dần các PDF đã lưu mà chưa nén (lớn nhất trước). Trả (số file, số byte tiết kiệm)."""
    if not gs_available() or minutes <= 0:
        return 0, 0
    base = settings.path(settings.data_dir)
    deadline = time.monotonic() + minutes * 60
    n = saved = 0
    with repo.session() as s:
        rows = s.execute(select(NoticeFile.id, NoticeFile.path, NoticeFile.size)
                         .where(NoticeFile.path.is_not(None), NoticeFile.orig_size.is_(None),
                                NoticeFile.removed_at.is_(None), NoticeFile.size >= COMPRESS_MIN)
                         .order_by(NoticeFile.size.desc())).all()
    for fid, rel, size in rows:
        if time.monotonic() > deadline:
            break
        if not rel.lower().endswith(".pdf"):
            continue
        new = compress_pdf(base / rel)
        with repo.Session.begin() as s:
            nf = s.get(NoticeFile, fid)
            nf.orig_size = size                       # đánh dấu đã thử nén (kể cả không nhỏ hơn)
            if new:
                nf.size = new
                saved += size - new
                n += 1
    log.info("Nén file đính kèm: %s file, tiết kiệm %.1f GB", n, saved / 1e9)
    return n, saved


# ------------------------------------------------------------------ đọc chữ
def ocr_available() -> bool:
    return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))


def _ocr_image(img: Path) -> str:
    # nice: nhường CPU cho web; OMP_THREAD_LIMIT=1: mỗi tiến trình 1 luồng (song song bằng nhiều tin cùng lúc)
    res = subprocess.run(["nice", "-n", "10", "tesseract", str(img), "-", "-l", "vie", "--psm", "6"],
                         capture_output=True, text=True, timeout=300, env={**os.environ, "OMP_THREAD_LIMIT": "1"})
    return res.stdout


def section_complete(text: str) -> bool:
    """Đã đọc qua hết đoạn mô tả tài sản (có tiêu đề tài sản và sau đó là 'giá khởi điểm'/'tiền đặt trước'…)."""
    norm = strip_accents(text or "")
    m = START_RE.search(norm)
    return bool(m and STOP_RE.search(norm, m.end() + 20))


def _ocr_pdf(path: Path, max_pages: int, pages: int) -> str:
    """OCR từng trang từ đầu, DỪNG khi đã qua hết đoạn mô tả tài sản (thường 1–3 trang đầu) hoặc tới max_pages."""
    out: list[str] = []
    last = min(max_pages, pages) if pages else max_pages
    with tempfile.TemporaryDirectory() as d:
        for i in range(1, last + 1):
            r = subprocess.run(["nice", "-n", "10", "pdftoppm", "-r", "200", "-gray", "-f", str(i), "-l", str(i),
                                "-png", str(path), f"{d}/p{i}"], capture_output=True, timeout=300)
            imgs = sorted(Path(d).glob(f"p{i}*.png"))
            if r.returncode != 0 or not imgs:
                break                                         # quá trang cuối
            out.append(_ocr_image(imgs[0]))
            imgs[0].unlink(missing_ok=True)
            if section_complete("\n".join(out)):
                break
    return "\n".join(out)


def read_text(path: Path, ocr_max_pages: int = 8, allow_ocr: bool = True) -> tuple[str, str]:
    """(chữ, cách đọc). PDF có lớp chữ: đọc HẾT các trang. PDF scan / ảnh: OCR từ trang đầu, dừng khi đã qua đoạn mô tả
    tài sản (tối đa ocr_max_pages trang). allow_ocr=False -> file cần OCR trả ('', 'deferred') để đọc sau."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        text, pages = "", 0
        try:
            from pypdf import PdfReader
            r = PdfReader(str(path))
            pages = len(r.pages)
            text = "\n".join((p.extract_text() or "") for p in r.pages)
        except Exception as e:  # noqa: BLE001
            log.debug("pypdf lỗi %s: %r", path, e)
        # có lớp chữ: trung bình >= 150 ký tự/trang
        if text.strip() and len(text.strip()) >= 150 * max(1, min(pages, 3)):
            return text, "text"
        if not ocr_available():
            return text, "none"
        if not allow_ocr:
            return "", "deferred"
        return _ocr_pdf(path, ocr_max_pages, pages), "ocr"
    if ext == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml).replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"), "docx"
    if ext in (".jpg", ".jpeg", ".png", ".tif", ".tiff") and ocr_available():
        return (_ocr_image(path), "ocr") if allow_ocr else ("", "deferred")
    return "", "unsupported"


# ------------------------------------------------------------------ trích thông số từ tài liệu
START_RE = re.compile(r"ten tai san|tai san dau gia|tai san ban dau gia|thong tin (ve )?tai san|mo ta tai san|"
                      r"tai san (dem ra )?dau gia|dac diem tai san|danh muc tai san|tai san gom")
STOP_RE = re.compile(r"gia khoi diem|tien dat truoc|buoc gia|thoi gian,? dia diem|ho so tham gia|"
                     r"phuong thuc (tra gia|dau gia)|hinh thuc dau gia")


def asset_section(text: str) -> str:
    """Đoạn mô tả TÀI SẢN trong tài liệu (bỏ căn cứ pháp lý, thể lệ...). Có thể gồm nhiều đoạn
    (thông báo + quy chế nhắc lại tài sản). Không thấy tiêu đề nào -> 6.000 ký tự đầu."""
    norm = strip_accents(text or "")
    norm = re.sub(r"[ \t]+", " ", norm)
    parts = []
    for m in START_RE.finditer(norm):
        if parts and m.start() < parts[-1][1]:
            continue
        stop = STOP_RE.search(norm, m.end() + 20)
        end = min(stop.start() if stop else len(norm), m.start() + 5000)
        parts.append((m.start(), end))
    if not parts:
        return norm[:6000]
    return "\n".join(norm[a:b] for a, b in parts)


def info_from_text(text: str) -> dict[str, Any]:
    sec = asset_section(text)
    out: dict[str, Any] = {}
    if len(sec.strip()) >= 30:
        info: RealEstateInfo = extract("", sec)
        out = {f: getattr(info, f) for f in DOC_FIELDS if getattr(info, f) not in (None, "")}
        if info.multi:
            out = {"multi": True}
        if info.notes:
            out["notes"] = info.notes[:5]
    if not out.get("multi"):
        # vị trí: cụm "tọa lạc tại / địa chỉ thửa đất / nơi có tài sản …" trong TOÀN văn bản (giữ dấu tiếng Việt)
        loc = asset_location(text)
        if loc.ward:
            out["ward"], out["ward_new"] = loc.ward, loc.ward_new
        if loc.province:
            out["province"] = loc.province
    return out


def merge_file_infos(infos: list[tuple[dict, str]]) -> dict[str, Any]:
    """Gộp thông số các file của MỘT thông báo: mỗi trường chỉ nhận khi các file không mâu thuẫn.
    infos: [(info, method)]. Trả {trường: giá trị, 'methods': {trường: 'text'|'ocr'}, 'notes': [...]}."""
    out: dict[str, Any] = {"methods": {}, "notes": []}
    if any(i.get("multi") for i, _ in infos):
        out["multi"] = True
        out["notes"].append("Tài liệu gồm nhiều thửa/lô – không lấy số liệu từ tài liệu")
        return out
    for f in (*DOC_FIELDS, "ward", "province"):
        vals = [(i[f], m) for i, m in infos if i.get(f) not in (None, "")]
        if not vals:
            continue
        if f == "ward":                           # tên mới "(nay là …)" thắng tên cũ
            new = [(v, m) for (v, m), i in zip(vals, [i for i, _ in infos if i.get("ward")]) if i.get("ward_new")]
            vals = new or vals
            out["ward_new"] = bool(new)
        if isinstance(vals[0][0], str):
            uniq = list(dict.fromkeys(ward_key(str(v)).lstrip("0") or "0" for v, _ in vals))
            v = vals[0][0] if len(uniq) == 1 else None
        else:
            v = _one([float(x) for x, _ in vals])
        if v is None:
            out["notes"].append(f"Các tài liệu ghi {f} khác nhau – để trống")
            continue
        out[f] = v
        out["methods"][f] = "text" if any(m in ("text", "docx") for _, m in vals) else "ocr"
    return out


# ------------------------------------------------------------------ danh sách file của tin
def list_files(n: NoticeRow, fetcher) -> list[tuple[str, str]]:
    if n.source == "dgts":
        data = fetcher.get_json("https://dgts.moj.gov.vn/portal/viewDetailAuctionInfo",
                                params={"auctionInfoId": n.source_id}) or {}
        out = []
        for f in data.get("listFile") or []:
            if f.get("linkFile"):
                out.append((f.get("fileName") or f["linkFile"].rsplit("/", 1)[-1],
                            f"https://dgts.moj.gov.vn/common/download?name={quote(f.get('fileName') or '')}"
                            f"&path={quote(f['linkFile'])}"))
        return out
    return [(unquote(u.rsplit("/", 1)[-1]), u) for u in (n.raw or {}).get("attachments") or []]


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w.\-() ]+", "_", unquote(name)).strip(" ._") or "file"
    stem, dot, ext = name.rpartition(".")
    return (stem[:120] + dot + ext[:8]) if dot else name[:128]


def _disk_pct(p: Path) -> float:
    p.mkdir(parents=True, exist_ok=True)
    u = shutil.disk_usage(p)
    return u.used / u.total * 100


# ------------------------------------------------------------------ chạy
BACKFILL_SINCE = datetime(2026, 1, 1)


def due_notices(s, limit: int, min_days: float = 2, backfill_since: datetime | None = BACKFILL_SINCE,
                now: datetime | None = None) -> list[int]:
    """Tin cần tải + đọc file. Chỉ TIN GẦN NHẤT của mỗi tài sản (phiên cũ đã có file thì thôi, chưa có thì bỏ qua).
    Thứ tự:
      1. tin MỚI (ghi nhận trong 36 giờ qua) của tài sản còn hạn – dữ liệu mới về lấp đầy ngay;
      2. tài sản còn hạn ≥ min_days ngày; 3. còn hạn < min_days ngày;
         (trong mỗi nhóm: đang THIẾU xã/phường, tỉnh, diện tích hoặc tờ/thửa trước → ưu tiên cao → hạn gần hơn)
      4. sau cùng: tài sản đã hết hạn từ backfill_since (năm 2026) còn THIẾU thông tin, kết thúc gần đây trước."""
    from .realestate.db import Property, PropertyNotice
    now = now or datetime.now()
    eff = lambda c: func.coalesce(getattr(Property, f"{c}_manual"), getattr(Property, c))  # noqa: E731
    has_all = and_(*(eff(c).is_not(None) for c in ("land_area", "parcel_no", "ward", "province")))
    is_open = Property.registration_end >= now
    scope = is_open
    if backfill_since:
        scope = scope | and_(Property.registration_end >= backfill_since, ~has_all)
    q = (select(NoticeRow.id)
         .join(PropertyNotice, PropertyNotice.notice_id == NoticeRow.id)
         .join(Property, Property.id == PropertyNotice.property_id)
         .where(NoticeRow.docs_at.is_(None), NoticeRow.id == Property.latest_notice_id, scope)
         .order_by(case((and_(is_open, NoticeRow.first_seen >= now - timedelta(hours=36)), 0),
                        (Property.registration_end >= now + timedelta(days=min_days), 1),
                        (is_open, 2), else_=3),
                   case((has_all, 1), else_=0),
                   Property.priority.desc(),
                   case((is_open, Property.registration_end), else_=None).asc(),
                   Property.registration_end.desc(), NoticeRow.publish_date.desc())
         .limit(limit))
    return list(s.scalars(q))


_FILE_ORDER = (r"thong bao", r"quy che", r"")      # thông báo đấu giá thường mô tả tài sản rõ nhất


def _file_rank(name: str) -> int:
    n = strip_accents(name or "")
    return next(i for i, k in enumerate(_FILE_ORDER) if k in n)


def _complete(infos: list[tuple[dict, str]]) -> bool:
    """Đã có đủ diện tích đất + tờ/thửa từ các file đã đọc -> không cần OCR thêm file scan khác."""
    m = merge_file_infos(infos)
    return bool(m.get("multi") or (m.get("land_area") and m.get("parcel_no")))


_fetch_lock = threading.Lock()


def _fetcher(fetchers: dict, settings: Settings, name: str):
    from .pipeline import make_fetcher
    from .sources import get_source
    with _fetch_lock:
        if name not in fetchers:
            fetchers[name] = make_fetcher(settings, get_source(name))
        return fetchers[name]


class _Skip(Exception):
    pass


def process_notice(nid: int, repo: Repository, settings: Settings, fetchers: dict, stats: DocStats,
                   ocr_max_pages: int = 8, max_bytes: int = 25 * 1048576, text_only_expired: bool = True,
                   keep_days: int = 30) -> dict[str, Any]:
    base = settings.path(settings.data_dir)
    with repo.session() as s:
        n = s.get(NoticeRow, nid)
        known = {f.url: f for f in s.scalars(select(NoticeFile).where(NoticeFile.notice_id == nid))}
        src_name, sid, pub = n.source, n.source_id, n.publish_date
        from .realestate.db import Property, PropertyNotice
        reg_end = s.scalar(select(Property.registration_end).join(PropertyNotice, PropertyNotice.property_id == Property.id)
                           .where(PropertyNotice.notice_id == nid))
        # hết hạn quá keep_days ngày (không ra phiên mới): chỉ đọc lấy thông số, không giữ file gốc
        text_only = text_only_expired and bool(reg_end and reg_end < datetime.now() - timedelta(days=keep_days))
        fetcher = _fetcher(fetchers, settings, src_name)
        files = sorted(list_files(n, fetcher), key=lambda f: _file_rank(f[0]))
    folder = Path("files") / src_name / (pub.strftime("%Y-%m") if pub else "khac") / _safe_name(sid)
    infos: list[tuple[dict, str]] = []
    seen_names: set[str] = set()
    for name, url in files:
        nf = known.get(url)
        if nf is None:
            nf = NoticeFile(notice_id=nid, filename=name[:255], url=url)
        if not nf.path:
            try:
                r = fetcher.request("GET", url)
                r.raise_for_status()
                body = r.content
                if len(body) > max_bytes:
                    nf.error = f"file {len(body) // 1048576} MB, quá lớn – chỉ lưu đường link tới file gốc"
                    nf.method = "too_big"
                    raise _Skip()
                fn = _safe_name(name)
                if fn in seen_names:
                    fn = f"{len(seen_names)}_{fn}"
                seen_names.add(fn)
                (base / folder).mkdir(parents=True, exist_ok=True)
                (base / folder / fn).write_bytes(body)
                nf.path, nf.size, nf.sha1 = str(folder / fn), len(body), hashlib.sha1(body).hexdigest()
                nf.error = None
                stats.files += 1
                stats.bytes += len(body)
            except _Skip:
                pass
            except Exception as e:  # noqa: BLE001
                if is_outage(e):
                    raise                                 # nguồn sập/bảo trì: bỏ dở tin này, lượt sau đọc lại
                nf.error = repr(e)[:300]
                stats.errors += 1
        if nf.path and nf.method in (None, "deferred") and not nf.removed_at:
            p = base / nf.path
            try:
                # đã đủ số liệu từ file trước -> file scan còn lại chỉ lưu, chưa OCR ('deferred', đọc khi cần)
                text, method = (read_text(p, ocr_max_pages, allow_ocr=not _complete(infos))
                                if p.suffix.lower() in TEXT_EXT else ("", "unsupported"))
                if text:
                    p.with_name(p.name + ".txt").write_text(text, encoding="utf-8")
                nf.method, nf.chars = method, len(text)
                nf.info = info_from_text(text) if text else {}
                if not text_only and nf.orig_size is None and (new := compress_pdf(p)):
                    nf.orig_size, nf.size = nf.size, new
                    stats.saved += (nf.orig_size or 0) - new
                if text_only and method not in ("deferred", "unsupported"):
                    p.unlink(missing_ok=True)             # tài sản đã hết hạn: chỉ giữ chữ đã đọc
                    nf.removed_at = datetime.now()
                stats.ocr_files += method == "ocr"
            except Exception as e:  # noqa: BLE001
                nf.method, nf.error = "none", repr(e)[:300]
                stats.errors += 1
        if nf.info:
            infos.append((nf.info, nf.method or "none"))
        with repo.Session.begin() as s:
            s.merge(nf) if nf.id else s.add(nf)
    doc = merge_file_infos(infos)
    with repo.Session.begin() as s:
        row = s.get(NoticeRow, nid)
        row.doc_info = doc
        row.docs_at = datetime.now()
    stats.notices += 1
    if any(f in doc for f in DOC_FIELDS):
        stats.with_info += 1
    return doc


def _open_latest():
    from .realestate.db import Property
    return select(Property.latest_notice_id).where(Property.registration_end >= datetime.now())


def default_workers() -> int:
    """Số tin xử lý song song = số nhân CPU (tối thiểu 2: còn chờ mạng khi tải file). OCR chạy với độ ưu tiên thấp
    (nice), nên web vẫn được ưu tiên CPU."""
    return max(2, os.cpu_count() or 2)


def fetch_docs(settings: Settings, repo: Repository, *, minutes: float = 300, limit: int = 100_000,
               max_disk_pct: float = 85, ocr_max_pages: int = 8, workers: int = 0, min_days: float = 2,
               max_file_mb: float = 25, text_only_expired: bool = True, keep_days: int = 30) -> DocStats:
    """Tải + đọc file đính kèm cho các tin chưa xử lý, song song nhiều tin, trong giới hạn thời gian / ổ cứng."""
    stats = DocStats()
    deadline = time.monotonic() + minutes * 60
    workers = workers or default_workers()
    with repo.session() as s:
        ids = due_notices(s, limit, min_days)
    fetchers: dict = {}

    def one(nid: int) -> DocStats:
        st = DocStats()
        try:
            process_notice(nid, repo, settings, fetchers, st, ocr_max_pages, int(max_file_mb * 1048576),
                           text_only_expired, keep_days)
        except Exception as e:  # noqa: BLE001
            if is_outage(e):                         # website nguồn sập/bảo trì: không tính lỗi cho tin, dừng lượt
                outage.append(repr(e)[:200])
                return st
            st.errors += 1
            log.warning("File đính kèm tin #%s lỗi: %r", nid, e)
            with repo.Session.begin() as s:          # lỗi 3 lần liên tiếp -> tạm bỏ qua (đọc lại khi tin cập nhật)
                row = s.get(NoticeRow, nid)
                tries = int((row.doc_info or {}).get("tries", 0)) + 1
                row.doc_info = {"tries": tries, "error": repr(e)[:200]}
                if tries >= 3:
                    row.docs_at = datetime.now()
        return st

    def add(st: DocStats) -> None:
        for k in ("notices", "files", "bytes", "ocr_files", "with_info", "errors", "saved"):
            setattr(stats, k, getattr(stats, k) + getattr(st, k))

    todo = list(ids)
    outage: list[str] = []
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            running: set = set()
            while todo or running:
                while todo and len(running) < workers and not stats.stopped:
                    if len(outage) >= 3:
                        stats.stopped = "website nguồn tạm không truy cập được (bảo trì?) – đọc tiếp ở lượt sau"
                    elif time.monotonic() > deadline:
                        stats.stopped = "hết thời gian của lượt – đọc tiếp ở lượt sau"
                    elif _disk_pct(settings.path(settings.data_dir)) >= max_disk_pct:
                        stats.stopped = f"ổ cứng đã dùng ≥ {max_disk_pct:.0f}% – dừng tải file"
                    else:
                        running.add(pool.submit(one, todo.pop(0)))
                if not running:
                    break
                done, running = wait(running, return_when=FIRST_COMPLETED)
                for f in done:
                    add(f.result())
    finally:
        for f in fetchers.values():
            f.close()
    with repo.session() as s:
        rest = due_notices(s, 1_000_000)
        n_open = s.scalar(select(func.count()).select_from(
            select(NoticeRow.id).where(NoticeRow.id.in_(rest[:200_000]), NoticeRow.id.in_(_open_latest())).subquery())) or 0
        dot = lambda x: f"{x:,}".replace(",", ".")  # noqa: E731
        stats.details.append(f"còn {dot(n_open)} tin tài sản còn hạn và {dot(len(rest) - n_open)} tin năm 2026 "
                             f"(đã hết hạn, còn thiếu thông tin) chưa đọc file")
    log.info("File đính kèm: %s tin, tải %s file (%.1f MB), OCR %s, có số liệu %s, lỗi %s, %s luồng%s",
             stats.notices, stats.files, stats.bytes / 1048576, stats.ocr_files, stats.with_info, stats.errors,
             workers, f" ({stats.stopped})" if stats.stopped else "")
    return stats


def reparse(repo: Repository, settings: Settings) -> int:
    """Trích lại thông số từ chữ đã lưu (.txt) – dùng khi cải tiến bộ trích xuất, không tải lại file."""
    base = settings.path(settings.data_dir)
    n = 0
    with repo.session() as s:
        nids = list(s.scalars(select(NoticeRow.id).where(NoticeRow.docs_at.is_not(None))))
    for nid in nids:
        with repo.Session.begin() as s:
            infos = []
            for nf in s.scalars(select(NoticeFile).where(NoticeFile.notice_id == nid)):
                if nf.path and (t := base / (nf.path + ".txt")).exists():
                    nf.info = info_from_text(t.read_text(encoding="utf-8"))
                if nf.info:
                    infos.append((nf.info, nf.method or "none"))
            s.get(NoticeRow, nid).doc_info = merge_file_infos(infos)
        n += 1
    return n
