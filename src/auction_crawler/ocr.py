"""Trích giá khởi điểm / tiền đặt trước / tiền hồ sơ từ file PDF đính kèm (taisancong.vn không đăng giá
trên trang). PDF có lớp chữ -> đọc trực tiếp (pypdf); PDF scan -> OCR bằng Tesseract tiếng Việt.

Yêu cầu hệ thống (chỉ cho OCR):  apt-get install -y tesseract-ocr tesseract-ocr-vie poppler-utils
Python:                          pip install -e .[ocr]

Bảng trong bản scan thường bị OCR làm méo nhãn ("Giá khởi điểm" -> rác) nhưng số tiền kèm
"(Bằng chữ: ...)" vẫn đọc tốt, nên dùng 2 tầng:
  1. nhãn đọc được ngay trước số tiền -> gán trực tiếp
  2. heuristic: tiền hồ sơ đi kèm "/hồ sơ"; giá khởi điểm = số lớn nhất; tiền đặt trước = số
     đầu tiên còn lại nằm trong 5%-25% giá khởi điểm (theo Luật ĐGTS: 5%-20%).
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .normalize import strip_accents

log = logging.getLogger(__name__)

AMOUNT_RE = re.compile(r"(\d{1,3}(?:[.,]\d{3})+|\d{4,})\s*(?:đồng|dong|đ|vnđ|vnd)", re.I)


def ocr_available() -> bool:
    return bool(shutil.which("tesseract") and shutil.which("pdftoppm"))


def pdf_text(path: Path, max_pages: int = 3, dpi: int = 200) -> tuple[str, str]:
    """Trả (text, method). method: 'text' | 'ocr' | 'none'."""
    try:
        from pypdf import PdfReader
        r = PdfReader(str(path))
        t = "\n".join((p.extract_text() or "") for p in r.pages[:max_pages])
        if len(t.strip()) > 200:
            return t, "text"
    except Exception as e:  # noqa: BLE001
        log.debug("pypdf lỗi %s: %r", path, e)
    if not ocr_available():
        return "", "none"
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-gray", "-f", "1", "-l", str(max_pages), "-png",
                        str(path), f"{d}/pg"], check=True, capture_output=True, timeout=180)
        out = []
        for img in sorted(Path(d).glob("pg-*.png")):
            res = subprocess.run(["tesseract", str(img), "-", "-l", "vie", "--psm", "6"],
                                 capture_output=True, text=True, timeout=180)
            out.append(res.stdout)
    return "\n".join(out), "ocr"


def extract_prices(text: str) -> dict[str, int]:
    norm = strip_accents(text)
    cands = []  # (pos, value, context_before, context_after)
    for m in AMOUNT_RE.finditer(norm):
        v = int(re.sub(r"\D", "", m.group(1)))
        if v < 10_000:
            continue
        before = norm[max(0, m.start() - 80):m.start()]
        after = norm[m.end():m.end() + 40]
        cands.append((m.start(), v, before, after))
    out: dict[str, int] = {}
    rest = []
    for pos, v, before, after in cands:
        near = before[-45:]
        if "/ho so" in after[:12] or "/ 01 ho so" in after[:15] or re.search(r"(mua|ban) ho so\W*$", near):
            out.setdefault("dossier_fee", v)
        elif re.search(r"khoi\s*diem", near):
            out.setdefault("starting_price", v)
        elif re.search(r"dat\s*tr[uư]oc|r[uư]oc\W*$", near):
            out.setdefault("deposit", v)
        else:
            rest.append(v)
    if "starting_price" not in out:
        pool = [v for v in rest if v != out.get("deposit")]
        if pool:
            out["starting_price"] = max(pool)
    sp = out.get("starting_price")
    if sp and "deposit" not in out:
        for v in rest:
            if 0.05 * sp <= v <= 0.25 * sp and v != sp:
                out["deposit"] = v
                break
    return out
