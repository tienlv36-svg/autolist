"""Bảng đối chiếu xã/phường CŨ -> MỚI theo sắp xếp đơn vị hành chính cấp xã năm 2025.

Dữ liệu nằm ở data/ward_mapping.csv (UTF-8), nạp bằng `auction ward-map-import <file>` từ danh sách chính thức
(Excel/CSV, hoặc văn bản Nghị quyết .txt/.pdf). Định dạng chuẩn (dòng đầu là tên cột):

    tinh_moi,xa_moi,xa_cu,huyen_cu,tinh_cu,mot_phan
    Đồng Tháp,Phường Mỹ Ngãi,Xã Mỹ Tân,Thành phố Cao Lãnh,Đồng Tháp,0

- tinh_moi, xa_moi: tên tỉnh và xã/phường SAU sắp xếp; xa_cu: tên xã/phường/thị trấn CŨ (có chữ "Xã/Phường/Thị trấn").
- huyen_cu, tinh_cu: huyện/tỉnh cũ (không bắt buộc – giúp phân biệt các xã cũ trùng tên trong cùng tỉnh mới).
- mot_phan = 1 nếu chỉ MỘT PHẦN xã cũ nhập vào xã mới (xã cũ bị chia) -> không dùng để quy đổi (không xác định được).

Quy đổi chỉ khi CHẮC CHẮN: tên đang dùng chưa phải tên xã mới của tỉnh đó, và tên cũ ứng với đúng MỘT xã mới (nếu trùng
tên ở nhiều huyện cũ thì phải khớp huyện ghi trong tin). Không chắc -> giữ nguyên tên trong tin.
"""
from __future__ import annotations

import csv
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from ..normalize import strip_accents

log = logging.getLogger(__name__)
COLUMNS = ["tinh_moi", "xa_moi", "xa_cu", "huyen_cu", "tinh_cu", "mot_phan"]
_PREFIX_RE = re.compile(r"^(xa|phuong|thi tran|dac khu|tt|p|x)\s+")
_DISTRICT_RE = re.compile(r"\b(?:huyện|quận|thị xã|thành phố|tp\.?|h\.|q\.|tx\.?)\s*[^,;()|\n]{2,30}?"
                          r"(?=\s*(?:[,;()|\n.]|$|\s(?:tỉnh|thành phố|tp)\b))", re.I)


_TONES = {"\u0300": "2", "\u0301": "1", "\u0309": "3", "\u0303": "4", "\u0323": "5"}


def plain(name: str | None) -> str:
    return re.sub(r"\s+", " ", strip_accents(name or "").replace(".", " ")).strip()


def key(name: str | None) -> str:
    """Khoá so sánh giữ THANH ĐIỆU (Thạnh ≠ Thành) nhưng không phụ thuộc vị trí dấu (Hoà = Hòa): mỗi tiếng = chữ
    không dấu + số thanh. Tên viết không dấu -> khoá không dấu (so bằng `plain`)."""
    if (name or "") == strip_accents(name or "") or not re.search(r"[^\x00-\x7f]", name or ""):
        return plain(name)
    out = []
    for w in re.sub(r"[.\s]+", " ", (name or "").lower()).split():
        d = unicodedata.normalize("NFD", w)
        tone = next((_TONES[c] for c in d if c in _TONES), "")
        out.append(strip_accents(w) + tone)
    return " ".join(out)


def _has_marks(name: str | None) -> bool:
    """Phần TÊN (bỏ chữ xã/phường/thị trấn) có viết dấu không."""
    n = re.sub(r"^\s*(xã|phường|thị trấn|đặc khu|xa|phuong|thi tran)\s+", "", (name or "").lower())
    return bool(re.search(r"[^\x00-\x7f]", n))


def core(name: str | None) -> str:
    """Tên bỏ chữ xã/phường/thị trấn: "Thị trấn Thạnh Mỹ" -> "thanh my"."""
    return _PREFIX_RE.sub("", plain(name))


def district(name: str | None) -> str:
    """"Huyện Lai Vung" / "TP. Cao Lãnh" -> "lai vung" / "cao lanh"."""
    return re.sub(r"^(huyen|quan|thi xa|thanh pho|tp|h|q|tx)\s+", "", plain(name))


def _province(name: str | None) -> str | None:
    from .extract import _provinces_in
    found = _provinces_in(name or "", prefer_explicit=False)
    return found[0][0] if found else (name.strip() if name else None)


@dataclass
class WardMap:
    new: dict[str, dict[str, str]] = field(default_factory=dict)            # tỉnh -> {khoá tên mới: tên mới}
    old: dict[tuple[str, str], list[tuple[str, str, bool]]] = field(default_factory=dict)   # (tỉnh, khoá cũ) -> [(huyện, mới, một phần)]
    new_plain: dict[str, set[str]] = field(default_factory=dict)            # cùng dữ liệu, khoá không dấu
    old_plain: dict[tuple[str, str], list[tuple[str, str, bool]]] = field(default_factory=dict)
    rows: int = 0

    def add(self, tinh_moi: str, xa_moi: str, xa_cu: str, huyen_cu: str = "", partial: bool = False) -> None:
        pv = _province(tinh_moi)
        if not (pv and xa_moi and xa_cu):
            return
        rec = (district(huyen_cu), xa_moi.strip(), partial)
        self.new.setdefault(pv, {})[key(xa_moi)] = xa_moi.strip()
        self.new_plain.setdefault(pv, set()).add(plain(xa_moi))
        self.old.setdefault((pv, key(xa_cu)), []).append(rec)
        self.old_plain.setdefault((pv, plain(xa_cu)), []).append(rec)
        self.rows += 1

    def __bool__(self) -> bool:
        return self.rows > 0

    def is_new(self, ward: str, province: str) -> bool:
        if _has_marks(ward):
            return key(ward) in self.new.get(province, {})
        return plain(ward) in self.new_plain.get(province, set())

    def to_new(self, ward: str | None, province: str | None, text: str = "") -> str | None:
        """Tên xã MỚI tương ứng tên cũ `ward` (hoặc None nếu không quy đổi chắc chắn được)."""
        if not (ward and province) or province not in self.new or self.is_new(ward, province):
            return None
        allc = (self.old if _has_marks(ward) else self.old_plain).get(
            (province, key(ward) if _has_marks(ward) else plain(ward)), [])
        cands = [c for c in allc if not c[2]]
        if not cands:
            return None                                  # chưa có / xã cũ bị chia cho nhiều xã mới -> không xác định
        news = {n for _, n, _ in cands}
        if len(news) == 1 and not any(p for _, _, p in allc):
            return news.pop()
        # trùng tên ở nhiều huyện cũ (hoặc một phần đi nơi khác) -> phải khớp huyện ghi trong tin
        districts = {district(m.group(0)) for m in _DISTRICT_RE.finditer(text or "")}
        news = {n for d, n, _ in allc if d and d in districts}
        if len(news) == 1 and all(not p for d, _, p in allc if d in districts):
            return news.pop()
        return None


_CACHE: dict[str, tuple[float, WardMap]] = {}
DEFAULT_PATH: Path | None = None


def mapping_path() -> Path:
    from ..config import ROOT
    return DEFAULT_PATH or ROOT / "data" / "ward_mapping.csv"


def load(path: Path | None = None) -> WardMap:
    p = Path(path or mapping_path())
    if not p.exists():
        return WardMap()
    mtime = p.stat().st_mtime
    hit = _CACHE.get(str(p))
    if hit and hit[0] == mtime:
        return hit[1]
    wm = WardMap()
    with p.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            wm.add(r.get("tinh_moi", ""), r.get("xa_moi", ""), r.get("xa_cu", ""), r.get("huyen_cu", "") or "",
                   str(r.get("mot_phan", "")).strip() in ("1", "true", "x", "có", "co"))
    _CACHE[str(p)] = (mtime, wm)
    log.info("Bảng xã cũ -> mới: %s dòng, %s tỉnh", wm.rows, len(wm.new))
    return wm


# ------------------------------------------------------------------ nạp từ nguồn chính thức
_HEADER_ALIASES = {
    "tinh_moi": ["tinh moi", "tinh thanh pho moi", "tinh/thanh pho moi", "tinh tp moi", "tinh sau sap xep", "tinh"],
    "xa_moi": ["xa moi", "ten xa moi", "xa phuong moi", "xa/phuong moi", "don vi moi", "dvhc moi", "ten don vi moi",
               "xa sau sap xep", "ten dvhc cap xa moi"],
    "xa_cu": ["xa cu", "ten xa cu", "xa phuong cu", "xa/phuong cu", "don vi cu", "dvhc cu", "ten don vi cu",
              "xa truoc sap xep", "ten dvhc cap xa cu", "cac don vi sap xep"],
    "huyen_cu": ["huyen cu", "quan huyen cu", "huyen/quan cu", "huyen truoc sap xep", "huyen"],
    "tinh_cu": ["tinh cu", "tinh truoc sap xep"],
    "mot_phan": ["mot phan", "sap nhap mot phan", "partial"],
}


def _match_header(h: str) -> str | None:
    """Nhận tên cột tiếng Việt thường gặp: "Tỉnh/thành phố mới", "Tên ĐVHC cấp xã mới", "Các xã cũ được sắp xếp"…"""
    k = re.sub(r"[_\-/]+", " ", plain(h)).strip()
    k = re.sub(r"\s+", " ", k)
    for col in COLUMNS:
        if k == col.replace("_", " "):
            return col
    words = set(k.split())
    is_new = bool(words & {"moi", "sau"})
    is_old = bool(words & {"cu", "truoc"}) or "duoc sap xep" in k or "sap nhap" in k and not is_new
    if "mot phan" in k:
        return "mot_phan"
    if words & {"tinh"} and not words & {"xa", "phuong", "dvhc", "huyen"}:
        return "tinh_cu" if is_old else "tinh_moi"
    if words & {"huyen", "quan"} and not words & {"xa", "phuong"}:
        return "huyen_cu"
    if words & {"xa", "phuong", "dvhc", "don vi"} or "don vi" in k:
        if is_old:
            return "xa_cu"
        if is_new:
            return "xa_moi"
    return None


def _split_old(s: str) -> list[str]:
    """"các xã Tân Hội, Tân Thuận và phường 1" -> ["Xã Tân Hội", "Xã Tân Thuận", "Phường 1"] (chữ loại đi trước áp
    cho các tên sau cho tới khi gặp loại khác)."""
    s = re.sub(r"\b(các|của)\s+", " ", s.strip(), flags=re.I)
    out, kind = [], ""
    for part in re.split(r",|\bvà\b|;", s):
        part = part.strip(" .")
        if not part:
            continue
        m = re.match(r"(xã|phường|thị trấn|đặc khu)\s+(.+)", part, re.I)
        if m:
            kind, name = m.group(1).capitalize(), m.group(2)
        else:
            name = part
        if kind:
            out.append(f"{kind} {name.strip()}")
    return out


_RESOLUTION_RE = re.compile(
    r"(?:sắp xếp|nhập)\s+(?:toàn bộ\s+)?(?:diện tích tự nhiên[^.]*?của|)\s*(.+?)\s+thành\s+(?:một\s+)?(xã|phường|đặc khu)"
    r"\s+mới(?:\s+có\s+tên\s+(?:gọi\s+)?là\s+(?:xã|phường|đặc khu))?\s+([^.;,\n]+)", re.I | re.S)


def parse_resolution_text(text: str, province: str) -> list[dict]:
    """Đọc văn bản Nghị quyết sắp xếp ĐVHC cấp xã: "Sắp xếp toàn bộ diện tích tự nhiên, quy mô dân số của xã A, xã B
    và thị trấn C thành xã mới có tên gọi là xã X." -> các dòng cũ -> mới. Phần "một phần diện tích … của xã Y" -> mot_phan."""
    rows = []
    text = re.sub(r"\s+", " ", text or "")
    for m in _RESOLUTION_RE.finditer(text):
        olds_raw, kind, new_name = m.group(1), m.group(2).capitalize(), m.group(3).strip()
        new_name = re.sub(r"\s*\(.*$", "", new_name)
        partial_parts = re.split(r"(?:và\s+)?một phần(?: diện tích tự nhiên[^,]*?)?(?:,\s*quy mô dân số)?\s+của", olds_raw)
        full = _split_old(partial_parts[0])
        part = [x for p in partial_parts[1:] for x in _split_old(p)]
        for o in full:
            rows.append({"tinh_moi": province, "xa_moi": f"{kind} {new_name}", "xa_cu": o, "mot_phan": "0"})
        for o in part:
            rows.append({"tinh_moi": province, "xa_moi": f"{kind} {new_name}", "xa_cu": o, "mot_phan": "1"})
    return rows


def read_source(path: Path, province: str | None = None) -> list[dict]:
    """Đọc file nguồn (.csv, .xlsx, .txt, .pdf) thành các dòng theo COLUMNS."""
    suf = path.suffix.lower()
    if suf in (".txt", ".pdf"):
        if suf == ".pdf":
            from pypdf import PdfReader
            text = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(path)).pages)
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
        if not province:
            m = re.search(r"(?:của|cấp xã của)\s+(tỉnh|thành phố)\s+([^\n.,;]{2,30}?)\s+năm\s+2025", text, re.I)
            province = m.group(2).strip() if m else None
        if not province:
            raise ValueError("Không xác định được tỉnh của Nghị quyết – chạy lại với --province \"Tên tỉnh\"")
        return parse_resolution_text(text, province)
    if suf in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        ws = load_workbook(path, read_only=True, data_only=True).active
        table = [[("" if c is None else str(c)) for c in r] for r in ws.iter_rows(values_only=True)]
    else:
        with path.open(encoding="utf-8-sig", newline="") as f:
            table = list(csv.reader(f))
    # tìm dòng tiêu đề trong 10 dòng đầu
    for hi, row in enumerate(table[:10]):
        cols = {i: _match_header(h) for i, h in enumerate(row)}
        if {"tinh_moi", "xa_moi", "xa_cu"} <= set(cols.values()) or (province and {"xa_moi", "xa_cu"} <= set(cols.values())):
            break
    else:
        raise ValueError("Không tìm thấy cột tiêu đề. Cần các cột: tinh_moi, xa_moi, xa_cu "
                         "(tuỳ chọn: huyen_cu, tinh_cu, mot_phan)")
    out = []
    last_new = {}
    for row in table[hi + 1:]:
        r = {c: (row[i].strip() if i < len(row) else "") for i, c in cols.items() if c}
        if province and not r.get("tinh_moi"):
            r["tinh_moi"] = province
        for c in ("tinh_moi", "xa_moi"):                # ô gộp (merged) trong Excel: lấy giá trị dòng trên
            if r.get(c):
                last_new[c] = r[c]
            else:
                r[c] = last_new.get(c, "")
        olds = _split_old(r.get("xa_cu", "")) if re.search(r",|\bvà\b", r.get("xa_cu", "")) else [r.get("xa_cu", "")]
        for o in olds:
            if o:
                out.append({**{c: r.get(c, "") for c in COLUMNS}, "xa_cu": o, "mot_phan": r.get("mot_phan") or "0"})
    return out


def write_mapping(rows: list[dict], path: Path | None = None, append: bool = True) -> int:
    p = Path(path or mapping_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if append and p.exists():
        with p.open(encoding="utf-8-sig", newline="") as f:
            existing = list(csv.DictReader(f))
    seen = set()
    allrows = []
    for r in [*existing, *rows]:
        k = (key(r.get("tinh_moi")), key(r.get("xa_moi")), key(r.get("xa_cu")), district(r.get("huyen_cu")))
        if k in seen or not (r.get("tinh_moi") and r.get("xa_moi") and r.get("xa_cu")):
            continue
        seen.add(k)
        allrows.append({c: r.get(c, "") for c in COLUMNS})
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(allrows)
    _CACHE.pop(str(p), None)
    return len(allrows)
