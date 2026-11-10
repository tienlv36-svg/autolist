"""Chuẩn hoá chuỗi tiếng Việt: tiền VND, ngày giờ, tỉnh/thành."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

# ---------------------------------------------------------------- văn bản

def clean_text(s: str | None) -> str | None:
    if s is None:
        return None
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[ ​\t\r]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    s = re.sub(r"[ ]{2,}", " ", s)
    s = s.strip(" \n:;-–")
    return s or None


def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d")


# ---------------------------------------------------------------- tiền

_UNIT = {"tỷ": 10**9, "ty": 10**9, "triệu": 10**6, "trieu": 10**6, "nghìn": 10**3, "ngàn": 10**3, "nghin": 10**3}


def parse_vnd(s: str | int | float | None) -> int | None:
    """'1.234.567.890 đồng' -> 1234567890 ; '1,5 tỷ đồng' -> 1500000000 ;
    '2 tỷ 350 triệu' -> 2350000000. Trả None nếu không có số."""
    if s is None or s == "":
        return None
    if isinstance(s, (int, float)):
        return int(s)
    text = s.lower()
    # Bỏ phần "(Bằng chữ: ...)" để không nhiễu
    text = re.split(r"\(?\s*bằng chữ", text)[0]
    # Dạng có đơn vị: "2 tỷ 350 triệu", "1,5 tỷ"
    unit_hits = re.findall(r"(\d+(?:[.,]\d+)?)\s*(tỷ|ty|triệu|trieu|nghìn|ngàn|nghin)\b", text)
    if unit_hits:
        total = 0.0
        for num, unit in unit_hits:
            total += float(num.replace(",", ".")) * _UNIT[unit]
        return int(round(total))
    # Dạng số đầy đủ: lấy cụm số dài nhất
    nums = re.findall(r"\d[\d.,\s]*\d|\d", text)
    if not nums:
        return None
    best = max(nums, key=lambda x: len(re.sub(r"\D", "", x)))
    best = best.strip()
    # "1.234.567,50" -> phần thập phân sau dấu phẩy cuối nếu có đúng 1-2 chữ số
    m = re.match(r"^(.*?)[,](\d{1,2})$", best)
    if m and "." in m.group(1):
        best = m.group(1)
    digits = re.sub(r"\D", "", best)
    return int(digits) if digits else None


# ---------------------------------------------------------------- ngày giờ

_DATE_RE = re.compile(r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{4})")
_DATE_WORDS_RE = re.compile(r"ngày\s*(\d{1,2})\s*tháng\s*(\d{1,2})\s*năm\s*(\d{4})", re.I)
_ISO_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2}))?")
_TIME_RE = re.compile(r"(\d{1,2})\s*(?:giờ|h|:)\s*(\d{1,2})?\s*(?:phút)?", re.I)


def parse_datetime(s: str | None) -> datetime | None:
    """Hỗ trợ: '12/11/2026', '08 giờ 30 phút, ngày 12/11/2026', '08:30 12-11-2026',
    'ngày 12 tháng 11 năm 2026', ISO '2026-11-12T08:30'.
    Nếu có khoảng 'từ ... đến ...' -> lấy mốc CUỐI (thường là hạn chót)."""
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    if isinstance(s, date):
        return datetime(s.year, s.month, s.day)
    s = str(s)
    if m := _ISO_RE.search(s):
        y, mo, d, hh, mm = m.groups()
        try:
            return datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0))
        except ValueError:
            return None
    matches = list(_DATE_RE.finditer(s)) or list(_DATE_WORDS_RE.finditer(s))
    if not matches:
        return None
    m = matches[-1] if re.search(r"\bđến\b", s, re.I) else matches[0]
    d, mo, y = (int(x) for x in m.groups())
    # giờ ngay SAU ngày: '26-11-2026 09:00'
    if after := re.match(r"\s*(\d{1,2})\s*[:hg]\s*(\d{2})", s[m.end():]):
        try:
            return datetime(y, mo, d, int(after.group(1)), int(after.group(2)))
        except ValueError:
            pass
    # tìm giờ ngay trước ngày (trong cùng đoạn)
    seg_start = matches[matches.index(m) - 1].end() if matches.index(m) > 0 else 0
    before = s[seg_start:m.start()]
    hh = mm = 0
    times = list(_TIME_RE.finditer(before))
    if times:
        t = times[-1]
        hh, mm = int(t.group(1)), int(t.group(2) or 0)
        if hh > 23 or mm > 59:
            hh = mm = 0
    try:
        return datetime(y, mo, d, hh, mm)
    except ValueError:
        return None


MIN_PLAUSIBLE_YEAR = 2010


def plausible_dt(dt: datetime | None) -> datetime | None:
    """Ngày của thông báo đấu giá (đăng, hạn đăng ký, tổ chức) phải hợp lý: năm >= 2010 và không quá 5 năm
    tới. Ngoài khoảng đó (vd 01/01/1970 do nguồn để trống, 2003 do nhập nhầm) -> coi như KHÔNG CÓ (để trống),
    không đoán lại."""
    if dt is None:
        return None
    if dt.year < MIN_PLAUSIBLE_YEAR or dt.year > datetime.now().year + 5:
        return None
    return dt


def parse_date(s: str | None) -> date | None:
    dt = parse_datetime(s)
    return dt.date() if dt else None


# ---------------------------------------------------------------- tỉnh/thành
# 34 đơn vị hành chính cấp tỉnh (từ 01/7/2025) và các tỉnh cũ được sáp nhập.
PROVINCE_MERGE: dict[str, list[str]] = {
    "Hà Nội": [], "Huế": ["Thừa Thiên Huế"], "Lai Châu": [], "Điện Biên": [], "Sơn La": [],
    "Lạng Sơn": [], "Quảng Ninh": [], "Thanh Hóa": [], "Nghệ An": [], "Hà Tĩnh": [], "Cao Bằng": [],
    "Tuyên Quang": ["Hà Giang"], "Lào Cai": ["Yên Bái"], "Thái Nguyên": ["Bắc Kạn"],
    "Phú Thọ": ["Vĩnh Phúc", "Hòa Bình"], "Bắc Ninh": ["Bắc Giang"], "Hưng Yên": ["Thái Bình"],
    "Hải Phòng": ["Hải Dương"], "Ninh Bình": ["Hà Nam", "Nam Định"], "Quảng Trị": ["Quảng Bình"],
    "Đà Nẵng": ["Quảng Nam"], "Quảng Ngãi": ["Kon Tum"], "Gia Lai": ["Bình Định"],
    "Khánh Hòa": ["Ninh Thuận"], "Lâm Đồng": ["Đắk Nông", "Bình Thuận"], "Đắk Lắk": ["Phú Yên"],
    "Đồng Nai": ["Bình Phước"], "Tây Ninh": ["Long An"],
    "TP. Hồ Chí Minh": ["Hồ Chí Minh", "Bình Dương", "Bà Rịa - Vũng Tàu", "Bà Rịa Vũng Tàu", "Sài Gòn"],
    "Cần Thơ": ["Sóc Trăng", "Hậu Giang"], "Vĩnh Long": ["Bến Tre", "Trà Vinh"],
    "Đồng Tháp": ["Tiền Giang"], "Cà Mau": ["Bạc Liêu"], "An Giang": ["Kiên Giang"],
}
_ALIASES = {"Hồ Chí Minh": ["tp hcm", "tp.hcm", "hcm"], "Đắk Lắk": ["dak lak", "daklak"],
            "Đắk Nông": ["dak nong"], "Thanh Hóa": ["thanh hoa"], "Hòa Bình": ["hoa binh"],
            "Khánh Hòa": ["khanh hoa"]}

# name(không dấu) -> (tên hiện hành, tên gốc)
_PROVINCE_INDEX: list[tuple[str, str, str]] = []
for _new, _olds in PROVINCE_MERGE.items():
    for _n in [_new, *_olds]:
        _PROVINCE_INDEX.append((strip_accents(_n).replace("-", " ").replace(".", " "), _new, _n))
        for _a in _ALIASES.get(_n, []):
            _PROVINCE_INDEX.append((_a, _new, _n))
_PROVINCE_INDEX = [(re.sub(r"\s+", " ", k).strip(), v, o) for k, v, o in _PROVINCE_INDEX]
_PROVINCE_INDEX.sort(key=lambda t: -len(t[0]))  # khớp tên dài trước


def detect_province(*texts: str | None) -> tuple[str | None, str | None]:
    """Trả (tỉnh hiện hành, tên xuất hiện trong văn bản). Ưu tiên văn bản đầu tiên
    (thường là địa chỉ tài sản); trong một văn bản lấy tên xuất hiện CUỐI CÙNG
    (địa chỉ VN viết từ nhỏ đến lớn: '..., xã X, tỉnh Y')."""
    for t in texts:
        if not t:
            continue
        norm = " " + re.sub(r"[\s,.\-;:()]+", " ", strip_accents(t)) + " "
        best: tuple[int, str, str] | None = None
        taken: list[tuple[int, int]] = []
        for key, new, orig in _PROVINCE_INDEX:
            for m in re.finditer(rf"(?<=\s){re.escape(key)}(?=\s)", norm):
                span = (m.start(), m.end())
                if any(a <= span[0] < b for a, b in taken):
                    continue  # nằm trong tên dài hơn đã khớp (vd 'Huế' trong 'Thừa Thiên Huế')
                taken.append(span)
                if best is None or m.start() > best[0]:
                    best = (m.start(), new, orig)
        if best:
            return best[1], best[2]
    return None, None
