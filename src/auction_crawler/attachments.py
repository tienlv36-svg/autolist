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
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, and_, case, func, select, update
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
    compress_level: Mapped[int | None] = mapped_column(Integer)  # 2 = đã nén mạnh (xám 130 dpi)
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


GS_STRONG = ["-sColorConversionStrategy=Gray", "-dProcessColorModel=/DeviceGray", "-dDownsampleGrayImages=true",
             "-dGrayImageResolution=130", "-dDownsampleColorImages=true", "-dColorImageResolution=130",
             "-dGrayImageDownsampleType=/Bicubic", "-dPassThroughJPEGImages=false", "-dJPEGQ=50"]


def compress_pdf(path: Path, strong: bool = True, min_size: int = COMPRESS_MIN) -> int | None:
    """Nén PDF (chủ yếu bản scan) bằng Ghostscript. strong: ảnh xám 130 dpi (đọc rõ trên màn hình; chữ đã được đọc
    và lưu riêng trước khi nén) – nhỏ hơn bản 150 dpi màu khoảng 2 lần. Thay file khi nhỏ hơn ≥ 15%.
    Trả dung lượng mới, hoặc None nếu không nén."""
    if path.suffix.lower() != ".pdf" or not gs_available() or not path.exists() or path.stat().st_size < min_size:
        return None
    tmp = path.with_name(path.name + ".gs.pdf")
    try:
        r = subprocess.run(["nice", "-n", "10", "gs", "-q", "-dNOPAUSE", "-dBATCH", "-dSAFER", "-sDEVICE=pdfwrite",
                            "-dPDFSETTINGS=/ebook", *(GS_STRONG if strong else []), "-dCompatibilityLevel=1.5",
                            f"-sOutputFile={tmp}", str(path)], capture_output=True, timeout=600)
        if r.returncode == 0 and tmp.exists() and 0 < tmp.stat().st_size < path.stat().st_size * 0.85:
            tmp.replace(path)
            return path.stat().st_size
    except Exception as e:  # noqa: BLE001
        log.debug("nén lỗi %s: %r", path, e)
    finally:
        tmp.unlink(missing_ok=True)
    return None


# Tài liệu "thường lệ" của tin (quy chế, thông báo, quyết định…): dọn sau docs_keep_expired_days (30) ngày.
# Tài liệu KHÁC (bản vẽ sơ đồ thửa đất, sổ hồng/giấy chứng nhận, ảnh, trích lục…): giữ tới docs_delete_all_days (90).
CORE_DOC_RE = re.compile(r"quy\s*che|\bqc\b|thong\s*bao|\btb\b|quyet\s*dinh|\bqd\b|bien\s*ban|hop\s*dong|"
                         r"danh\s*muc|phu\s*luc|to\s*trinh|cong\s*van|giay\s*moi|mau\s*don|don\s*dang\s*ky")


def is_core_doc(filename: str | None) -> bool:
    return bool(CORE_DOC_RE.search(strip_accents(filename or "").replace("_", " ").replace("-", " ")))


def prune_expired(settings: Settings, repo: Repository, days: int = 30, now: datetime | None = None,
                  pressure_pct: float = 0, target_pct: float = 75, all_days: int = 90) -> tuple[int, int]:
    """Dọn file gốc của tài sản đã HẾT HẠN đăng ký mà không ra phiên mới (giữ chữ đã đọc .txt và thông số):
    - quá `days` (30) ngày: chỉ dọn tài liệu thường lệ (quy chế, thông báo…); bản vẽ sơ đồ, sổ hồng, ảnh… GIỮ LẠI;
    - quá `all_days` (90) ngày: dọn HẾT mọi file;
    - ổ dùng >= pressure_pct: dọn sớm tài liệu thường lệ của tài sản đã hết hạn chưa đủ ngày (hết hạn lâu nhất trước)
      tới khi ổ < target_pct.
    Trừ tài sản đang trong giỏ hàng của ai đó hoặc mức ưu tiên Cao/Rất cao. Trả (số file, số byte)."""
    from .realestate.db import CartItem, Property, PropertyNotice
    if days <= 0:
        return 0, 0
    now = now or datetime.now()
    base = settings.path(settings.data_dir)
    keep = select(CartItem.property_id)
    pressure = bool(pressure_pct) and _disk_pct(base) >= pressure_pct
    cutoff = now if pressure else now - timedelta(days=days)
    with repo.session() as s:
        rows = s.execute(select(NoticeFile.id, NoticeFile.path, NoticeFile.size, NoticeFile.filename,
                                Property.registration_end)
                         .join(PropertyNotice, PropertyNotice.notice_id == NoticeFile.notice_id)
                         .join(Property, Property.id == PropertyNotice.property_id)
                         .where(NoticeFile.path.is_not(None), NoticeFile.removed_at.is_(None),
                                Property.registration_end < cutoff,
                                Property.priority < 3, Property.id.not_in(keep))
                         .order_by(Property.registration_end)).all()
    n = freed = 0
    old_all = now - timedelta(days=all_days) if all_days > 0 else None
    for i, (fid, rel, size, name, reg_end) in enumerate(rows):
        if not (is_core_doc(name) or (old_all and reg_end < old_all)):
            continue                                  # sơ đồ thửa đất, sổ hồng, ảnh…: giữ tới all_days
        if pressure and i % 20 == 0 and _disk_pct(base) < target_pct and not (old_all and reg_end < old_all):
            break
        f = base / rel
        if f.exists():
            f.unlink()
            freed += size or 0
            n += 1
        with repo.Session.begin() as s:
            s.get(NoticeFile, fid).removed_at = now
    log.info("Dọn file tài sản hết hạn%s: %s file, %.1f GB",
             " (ổ gần đầy – dọn sớm quy chế/thông báo)" if pressure else "", n, freed / 1e9)
    return n, freed


def purge_files(settings: Settings, repo: Repository) -> tuple[int, int]:
    """Xoá MỌI file gốc đính kèm đã lưu (giữ chữ đã đọc .txt và thông số; file vẫn mở được qua link nguồn).
    Trả (số file, số byte)."""
    base = settings.path(settings.data_dir)
    with repo.session() as s:
        rows = s.execute(select(NoticeFile.id, NoticeFile.path, NoticeFile.size)
                         .where(NoticeFile.path.is_not(None), NoticeFile.removed_at.is_(None))).all()
    n = freed = 0
    now = datetime.now()
    for i in range(0, len(rows), 500):
        chunk = rows[i:i + 500]
        for _, rel, size in chunk:
            f = base / rel
            if f.exists():
                f.unlink()
                freed += size or 0
                n += 1
        with repo.Session.begin() as s:
            s.execute(update(NoticeFile).where(NoticeFile.id.in_([r[0] for r in chunk])).values(removed_at=now))
    log.info("Xoá file gốc đính kèm: %s file, %.1f GB (giữ chữ đã đọc)", n, freed / 1e9)
    return n, freed


def compress_existing(settings: Settings, repo: Repository, minutes: float = 20) -> tuple[int, int]:
    """Nén dần các PDF đã lưu (lớn nhất trước): file chưa nén, và file đã nén kiểu cũ (màu 150 dpi) còn > 500 KB
    được nén lại kiểu mạnh (xám 130 dpi). Trả (số file, số byte tiết kiệm)."""
    if not gs_available() or minutes <= 0:
        return 0, 0
    base = settings.path(settings.data_dir)
    deadline = time.monotonic() + minutes * 60
    n = saved = 0
    with repo.session() as s:
        rows = s.execute(select(NoticeFile.id, NoticeFile.path, NoticeFile.size)
                         .where(NoticeFile.path.is_not(None), NoticeFile.removed_at.is_(None),
                                func.coalesce(NoticeFile.compress_level, 0) < 2,
                                NoticeFile.size >= 500_000)
                         .order_by(NoticeFile.size.desc())).all()
    for fid, rel, size in rows:
        if time.monotonic() > deadline:
            break
        if not rel.lower().endswith(".pdf"):
            continue
        new = compress_pdf(base / rel, strong=True, min_size=500_000)
        with repo.Session.begin() as s:
            nf = s.get(NoticeFile, fid)
            nf.orig_size = nf.orig_size or size
            nf.compress_level = 2                     # đã thử nén mạnh (kể cả không nhỏ hơn)
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


_PRICE_RE = re.compile(r"gia\s*khoi\s*diem[^0-9]{0,80}?(\d{1,3}(?:[.,]\d{3}){2,})")
_WORDS_RE = re.compile(r"^\s*(?:dong|vnd|d\b)?[^a-z]{0,15}\(?\s*(?:bang\s*chu|viet\s*bang\s*chu)\s*:?\s*([a-z\s,.-]{5,220}?)\s*(?:dong|vnd|\))")
_DIGITS = {"khong": 0, "mot": 1, "hai": 2, "ba": 3, "bon": 4, "tu": 4, "nam": 5, "lam": 5, "nham": 5, "sau": 6,
           "bay": 7, "tam": 8, "chin": 9}
_SCALES = {"nghin": 1_000, "ngan": 1_000, "trieu": 1_000_000, "ty": 1_000_000_000, "ti": 1_000_000_000}


def words_to_number(s: str) -> int | None:
    """"chín tỷ sáu trăm ba mươi triệu" -> 9630000000 (chữ đã bỏ dấu). Không hiểu được -> None."""
    total = group = 0
    pend: int | None = None
    seen = False
    for w in re.findall(r"[a-z]+", strip_accents(s or "")):
        if w in _DIGITS:
            pend, seen = _DIGITS[w], True
        elif w == "muoi":
            group += (pend if pend is not None else 1) * 10
            pend, seen = None, True
        elif w == "tram":
            group += (pend or 0) * 100
            pend = None
        elif w in ("linh", "le", "chan", "va"):
            continue
        elif w in _SCALES:
            group += pend or 0
            total += (group or 1) * _SCALES[w]
            group, pend = 0, None
        else:
            return None                               # từ lạ (OCR sai) -> không tin
    if not seen:
        return None
    return total + group + (pend or 0)


def labeled_starting_prices(text: str) -> set[int]:
    """Các số tiền đứng ngay sau nhãn "giá khởi điểm" (từ 1 triệu trở lên)."""
    return {v for v, _ in labeled_prices_with_words(text)}


# câu nói về MỘT PHẦN giá khởi điểm (tiền đặt trước "10% giá khởi điểm", bước giá…) hoặc giá theo đơn vị (/m², /tháng)
_NOT_PRICE_BEFORE = re.compile(r"(%|phan tram|dat truoc|tien coc|dat coc|buoc gia|bang\s*\d|toi thieu|so voi)[^.;:\n]{0,40}$")
_NOT_PRICE_GAP = re.compile(r"%|phan tram|dat truoc|buoc gia|m2|/\s*m|mot\s*(m|met|thang|nam)|/\s*thang|/\s*nam|"
                            r"moi\s*(m|thang|nam)|thue|tra\s*gia\s*toi\s*thieu|"
                            # giá THÀNH PHẦN: "- Giá trị quyền sử dụng đất: N", "nhà/tài sản trên đất: N"
                            r"gia\s*tri|quyen\s*su\s*dung|tren\s*dat|cong\s*trinh|nha\s*o|vat\s*kien\s*truc")
# một LÔ / GÓI trong thông báo nhiều lô: "Gói 1 … Giá khởi điểm", "7.1. Giá khởi điểm", "Lô số 2"
_LOT_BEFORE = re.compile(r"(\bgoi\s*(so\s*)?\d|\blo\s*(so\s*)?\d|tai\s*san\s*(so\s*)?\d+\s*[:.)-]|"
                         r"(?:^|\s)\d+\.\d+\.?\s*$)")
_NOT_PRICE_AFTER = re.compile(r"^\s*(dong|vnd|d)?\s*(/\s*(m|thang|nam)|mot\s*(m|thang|nam)|m2)")
MAX_DOC_RATIO = 2.0          # giá thông báo chênh giá cổng quá 2 lần -> không thay (gần như chắc chắn đọc nhầm số khác)


def labeled_prices_with_words(text: str) -> list[tuple[int, int | None]]:
    """[(số, số đọc từ "Bằng chữ: …" ngay sau, nếu có)] của các giá khởi điểm. Bỏ: "10% giá khởi điểm: N" (tiền đặt
    trước), giá theo m²/tháng. Có "TỔNG giá khởi điểm" -> chỉ lấy (các) số tổng (giá thành phần QSDĐ + nhà… bỏ qua)."""
    norm = strip_accents(text or "")
    out, totals, lots = [], [], []
    for m in _PRICE_RE.finditer(norm):
        v = int(re.sub(r"\D", "", m.group(1)))
        if v < 1_000_000:
            continue
        before = norm[max(0, m.start() - 60):m.start()]
        gap = norm[m.start():m.start(1)]
        if (_NOT_PRICE_BEFORE.search(before) or _NOT_PRICE_GAP.search(gap)
                or _NOT_PRICE_AFTER.search(norm[m.end():m.end() + 25])):
            continue
        if _LOT_BEFORE.search(norm[max(0, m.start() - 300):m.start()].split("\n\n")[-1][-300:]):
            lots.append(v)                            # giá của một lô/gói -> không phải giá cả thông báo
            continue
        wm = _WORDS_RE.search(norm[m.end():m.end() + 260])
        item = (v, words_to_number(wm.group(1)) if wm else None)
        out.append(item)
        if re.search(r"tong\s*(cong\s*)?$", before.rstrip(" :")) or re.search(r"\btong\b", gap):
            totals.append(item)
    if lots:
        return []                                     # thông báo chia lô/gói: không lấy một giá chung
    return totals or out


def all_labeled_prices(text: str) -> list[int]:
    """MỌI số đứng sau nhãn "giá khởi điểm" (kể cả giá thành phần, tổng có thuế…) – để đối chiếu giá cổng."""
    norm = strip_accents(text or "")
    return sorted({int(re.sub(r"\D", "", m.group(1))) for m in _PRICE_RE.finditer(norm)
                   if int(re.sub(r"\D", "", m.group(1))) >= 1_000_000})


_AUCTION_LABEL = re.compile(r"(?:thoi\s*gian|to\s*chuc)[^.:\n]{0,40}?(?:cuoc|phien|buoi)\s*dau\s*gia")
_DATE_RE = re.compile(r"(\d{1,2})\s*[/.-]\s*(\d{1,2})\s*[/.-]\s*(20\d\d)|"
                      r"ngay\s*(\d{1,2})\s*thang\s*(\d{1,2})\s*nam\s*(20\d\d)")


def auction_dates(text: str) -> list[str]:
    """Ngày tổ chức cuộc đấu giá ghi trong file ("Thời gian tổ chức cuộc đấu giá: 9 giờ, ngày 25/11/2026") -> ["2026-11-25"]."""
    norm = strip_accents(text or "")
    out = set()
    for m in _AUCTION_LABEL.finditer(norm):
        d = _DATE_RE.search(norm, m.end(), m.end() + 160)
        if d:
            dd, mm, yy = (d.group(1), d.group(2), d.group(3)) if d.group(1) else (d.group(4), d.group(5), d.group(6))
            try:
                out.add(date(int(yy), int(mm), int(dd)).isoformat())
            except ValueError:
                pass
    return sorted(out)


def _near(a: float, b: float, tol: float = 0.005) -> bool:
    return bool(a and b) and abs(a - b) <= tol * b


def doc_price(doc: dict | None, portal: int | None, property_count: int | None = 1,
              auction_date: datetime | date | None = None) -> tuple[int | None, str | None]:
    """Giá khởi điểm của MỘT phiên: giá trên cổng, trừ khi file thông báo ghi rõ MỘT giá khởi điểm khác -> dùng giá trong
    thông báo. Chỉ thay khi chắc chắn file là của ĐÚNG phiên này và không phải số khác:
    - giá cổng trùng một số "giá khởi điểm" bất kỳ trong file (giá trước thuế, giá thành phần…) -> cổng đúng;
    - file ghi ngày đấu giá khác ngày của phiên -> file của phiên khác, giữ cổng;
    - chênh đúng 10% (thuế VAT, hoặc giá phiên trước/sau giảm 10%) mà file không ghi ngày khớp -> giữ cổng;
    - chênh quá 2 lần -> giữ cổng; bản scan: số phải khớp phần "Bằng chữ". Trả (giá, ghi chú)."""
    if (property_count or 1) != 1 or not doc or doc.get("multi"):
        return portal, None
    v = doc.get("starting_price")
    words = doc.get("starting_price_words")
    if not v or (portal and abs(v - portal) <= 0.01 * portal):
        return portal, None
    if portal and words and abs(words - portal) <= 0.01 * portal:
        return portal, None                           # OCR đọc nhầm chữ số, phần bằng chữ khớp giá cổng -> cổng đúng
    if portal and any(_near(x, portal, 0.002) for x in doc.get("all_prices") or []):
        return portal, None                           # cổng = một giá ghi trong file (vd giá trước thuế) -> cổng đúng
    if portal and not (1 / MAX_DOC_RATIO <= v / portal <= MAX_DOC_RATIO):
        return portal, None                           # chênh quá xa: không phải cùng một giá -> tin giá cổng, không báo
    from .web.fmt import money
    dates = doc.get("auction_dates") or []
    ad = auction_date.date() if isinstance(auction_date, datetime) else auction_date
    date_ok = bool(ad and dates and any(abs((date.fromisoformat(d) - ad).days) <= 1 for d in dates))
    if portal and ad and dates and not date_ok:
        return portal, (f"File thông báo ghi giá {money(v)} nhưng là của phiên ngày "
                        f"{date.fromisoformat(dates[0]):%d/%m/%Y} – dùng giá cổng")
    if portal and not date_ok and any(_near(v, portal * k, 0.003) for k in (0.9, 1 / 0.9, 1.1, 1 / 1.1)):
        return portal, (f"File thông báo ghi {money(v)}, lệch đúng 10% so với cổng (thuế hoặc giá phiên trước/sau) – "
                        f"dùng giá cổng")
    method = (doc.get("methods") or {}).get("starting_price", "ocr")
    if method != "ocr" or (words and words == v):
        how = "" if method != "ocr" else " (bản scan, số và chữ khớp nhau)"
        return v, (f"Giá trên cổng ({money(portal)}) khác giá ghi trong thông báo ({money(v)}){how} – dùng giá trong "
                   f"thông báo" if portal else None)
    return portal, (f"Thông báo (OCR) ghi giá khởi điểm {money(v)}, khác giá trên cổng {money(portal)} – dùng giá cổng"
                    if portal else None)


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
        if (ap := all_labeled_prices(text)):
            out["all_prices"] = ap[:20]
        if (ad := auction_dates(text)):
            out["auction_dates"] = ad[:5]
        found = labeled_prices_with_words(text)
        if len({v for v, _ in found}) == 1:       # đúng MỘT giá khởi điểm ghi rõ trong văn bản
            out["starting_price"] = found[0][0]
            words = {w for _, w in found if w}
            if len(words) == 1:
                out["starting_price_words"] = words.pop()
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
    for f in ("all_prices", "auction_dates"):     # danh sách: gộp mọi file
        vals = sorted({x for i, _ in infos for x in (i.get(f) or [])})
        if vals:
            out[f] = vals[:30]
    for f in (*DOC_FIELDS, "ward", "province", "starting_price", "starting_price_words"):
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
                   keep_days: int = 30, all_days: int = 90, store_files: bool = False) -> dict[str, Any]:
    """store_files=False (mặc định): tải file về, đọc lấy chữ + thông số rồi XOÁ file gốc (chỉ giữ chữ .txt);
    người dùng mở file qua đường link nguồn."""
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
        drop_all = text_only and bool(reg_end and reg_end < datetime.now() - timedelta(days=all_days))
        if not store_files:
            text_only = drop_all = True
        fetcher = _fetcher(fetchers, settings, src_name)
        # nguồn đôi khi liệt kê CÙNG một file 2 lần trong một tin -> bỏ trùng theo đường dẫn
        files = sorted({u: (nm, u) for nm, u in reversed(list_files(n, fetcher))}.values(), key=lambda f: _file_rank(f[0]))
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
                keep_file = not text_only or not (drop_all or is_core_doc(nf.filename))
                if keep_file and nf.orig_size is None and (new := compress_pdf(p)):
                    nf.orig_size, nf.size = nf.size, new
                    stats.saved += (nf.orig_size or 0) - new
                if keep_file:
                    nf.compress_level = 2
                # hết hạn > 30 ngày: quy chế/thông báo chỉ đọc rồi bỏ; sơ đồ thửa, sổ hồng… vẫn lưu (tới 90 ngày)
                if not store_files or (text_only and method not in ("deferred", "unsupported")
                                       and (drop_all or is_core_doc(nf.filename))):
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


_OUTAGE_TXT = re.compile(r"\b5\d\d\b|429|ConnectError|ConnectTimeout|ReadTimeout|RemoteProtocolError|SourceDown|"
                         r"không truy cập được", re.I)


def requeue_outages(repo: Repository) -> int:
    """Tin bị bỏ qua sau 3 lần lỗi mà lỗi là do nguồn sập/bảo trì (trước khi có nhận diện bảo trì) -> xếp đọc lại."""
    n = 0
    with repo.Session.begin() as s:
        for row in s.scalars(select(NoticeRow).where(NoticeRow.docs_at.is_not(None),
                                                     func.json_extract(NoticeRow.doc_info, "$.tries").is_not(None))):
            if _OUTAGE_TXT.search(str((row.doc_info or {}).get("error", ""))):
                row.docs_at, row.doc_info = None, None
                n += 1
    if n:
        log.info("Xếp đọc lại %s tin từng lỗi do nguồn bảo trì/sập", n)
    return n


def default_workers() -> int:
    """Số tin xử lý song song = số nhân CPU (tối thiểu 2: còn chờ mạng khi tải file). OCR chạy với độ ưu tiên thấp
    (nice), nên web vẫn được ưu tiên CPU."""
    return max(2, os.cpu_count() or 2)


def fetch_docs(settings: Settings, repo: Repository, *, minutes: float = 300, limit: int = 100_000,
               max_disk_pct: float = 85, ocr_max_pages: int = 8, workers: int = 0, min_days: float = 2,
               max_file_mb: float = 25, text_only_expired: bool = True, keep_days: int = 30,
               all_days: int = 90, store_files: bool = False) -> DocStats:
    """Tải + đọc file đính kèm cho các tin chưa xử lý, song song nhiều tin, trong giới hạn thời gian / ổ cứng."""
    stats = DocStats()
    deadline = time.monotonic() + minutes * 60
    workers = workers or default_workers()
    requeue_outages(repo)
    with repo.session() as s:
        ids = due_notices(s, limit, min_days)
    fetchers: dict = {}

    def one(nid: int) -> DocStats:
        st = DocStats()
        try:
            process_notice(nid, repo, settings, fetchers, st, ocr_max_pages, int(max_file_mb * 1048576),
                           text_only_expired, keep_days, all_days, store_files)
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
