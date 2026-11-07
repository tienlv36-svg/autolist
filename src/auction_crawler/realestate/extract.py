"""Trích xuất thuộc tính bất động sản từ văn bản tin đấu giá (tiếng Việt, không chuẩn hoá).

Đã khảo sát trên ~1.000 tin thật. Các mẫu điển hình:
  "thửa đất số: 30; tờ bản đồ số: 59; diện tích: 130 m² đất tại đô thị"
  "Diện tích: 3.198,1m2; Loại đất: Đất chuyên trồng lúa nước"
  "diện tích 210,6 m2 đất (trong đó 150 m2 đất ở nông thôn, 60,6 m2 đất trồng cây lâu năm)"
  "Diện tích xây dựng: 206,1m2; Diện tích sàn: 439,5m2"
  "mặt tiền rộng 12,7m, ... chiều sâu bình quân 36,7m" | "kích thước 10,1m x 5,1m"
  "... tỉnh Bình Dương (nay là phường Chánh Hiệp, Tp. Hồ Chí Minh)"
Kết quả là ƯỚC LƯỢNG tự động - giao diện cho phép sửa tay (trường *_manual ưu tiên hơn).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..normalize import strip_accents

NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"
AREA_RE = re.compile(rf"({NUM})\s*(?:m2|m²|m\s*2\b|mét vuông|met vuong)", re.I)
RESIDENTIAL = re.compile(r"dat o\b|\bodt\b|\bont\b|dat o tai (do thi|nong thon)|dat o do thi|dat o nong thon|\bo dt\b|"
                         r"dat tai (do thi|nong thon)")
OTHER_LAND = re.compile(r"\b(cln|luc|bhk|lua|nts|hnk|skc|tmd|rsx|nkh|lnk|ctd)\b|trong (cay|lua)|cay lau nam|"
                        r"cay hang nam|nong nghiep|nuoi trong|thuy san|san xuat kinh doanh|thuong mai|"
                        r"rung san xuat|mat nuoc|giao thong|thuy loi|chuyen dung|phi nong nghiep")
WARD_RE = re.compile(r"\b(xã|phường|thị trấn|đặc khu|p\.|x\.|tt\.)\s*([^\W\d_][^,;()\n]{1,40}?|\d{1,2})"
                     r"(?=\s*(?:,|;|\)|\.\s|$|-|–|\btỉnh\b|\bthành phố\b|\btp\b|\bhuyện\b|\bquận\b|\bthị xã\b))",
                     re.I)
WARD_PREFIX = {"p.": "Phường", "x.": "Xã", "tt.": "Thị trấn"}


def parse_number(s: str) -> float | None:
    """'3.198,1' -> 3198.1 ; '1.036' -> 1036 ; '76.4' -> 76.4 ; '136,1' -> 136.1"""
    s = s.strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") == 1 and len(s.split(".")[1]) != 3:
        pass  # dấu chấm thập phân
    else:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


@dataclass
class RealEstateInfo:
    sale_form: str = "ban"                 # ban | cho_thue | khoan_no
    land_area: float | None = None         # tổng diện tích đất (m2)
    residential_area: float | None = None  # diện tích đất ở
    other_land_area: float | None = None   # diện tích đất khác
    floor_area: float | None = None        # diện tích sàn
    width: float | None = None             # chiều ngang / mặt tiền (m)
    length: float | None = None            # chiều dài / chiều sâu (m)
    parcels: list[tuple[str | None, str | None]] = field(default_factory=list)  # [(tờ, thửa)]
    ward: str | None = None
    session_hint: int | None = None        # "lần 3" trong tiêu đề
    has_house: bool = False

    def dict(self) -> dict:
        d = asdict(self)
        d["parcels"] = [list(p) for p in self.parcels]
        return d

    @property
    def parcel_text(self) -> str | None:
        if not self.parcels:
            return None
        to, thua = self.parcels[0]
        s = " · ".join(x for x in [f"Tờ {to}" if to else None, f"Thửa {thua}" if thua else None] if x)
        return s + (f" (+{len(self.parcels) - 1})" if len(self.parcels) > 1 else "")


def detect_sale_form(title: str, asset_type: str | None) -> str:
    n = strip_accents(title or "")
    if asset_type == "khoan_no" or re.search(r"khoan no|quyen (thu hoi|doi) no|hop dong tin dung", n):
        return "khoan_no"
    if re.search(r"\bcho thue\b|quyen (khai thac|thue)|thue mat bang|\bthoi gian (cho )?thue\b|\bthue\b.*\bthang\b", n):
        return "cho_thue"
    return "ban"


def _areas(text: str, norm: str) -> dict:
    land, resid, other, floor, generic = [], [], [], [], []
    in_breakdown_until = -1
    for m in AREA_RE.finditer(text):
        v = parse_number(m.group(1))
        if not v or v <= 0 or v > 50_000_000:
            continue
        # norm có cùng độ dài với text (strip_accents giữ độ dài với chữ tiếng Việt NFC)
        before = norm[max(0, m.start() - 70):m.start()]
        after = re.split(r"[(;]|trong do", norm[m.end():m.end() + 45])[0]  # ngữ cảnh sau, dừng ở '(' / 'trong đó'
        near_b = before[-40:]
        if re.search(r"(dien tich|dt)\s*san|tong dien tich san|san xay dung", near_b):
            floor.append(v)
            continue
        if re.search(r"(dien tich|dt)\s*xay dung|xay dung\s*:?\s*$|dien tich (nha|xay)|nha .{0,25}dien tich", near_b):
            continue  # diện tích xây dựng/nhà - không phải đất, không phải sàn
        if re.search(r"trong do|gom\s*:?\s*$", before[-25:]) or m.start() <= in_breakdown_until:
            in_breakdown_until = m.end() + 80
            target = resid if RESIDENTIAL.search(after[:35]) else other if OTHER_LAND.search(after[:40]) else None
            if target is not None:
                target.append(v)
            continue
        # loại đất có thể đứng SAU số ("130 m2 đất ở") hoặc TRƯỚC số trong cùng vế ("đất ở tại nông thôn 100m2")
        before_seg = re.split(r";|,(?!\d)|m2|m²|\.\s", before)[-1]
        after_seg = re.split(r"\.\s|:|,(?!\d)", after[:35])[0]
        typed_after = None
        if re.match(r"\s*(dat\b|\(?\s*[a-z]{3}\s*\)?(\W|$))", after_seg):   # ngay sau số: "130 m2 đất ở", "60 m2 (LUC)"
            typed_after = RESIDENTIAL.search(after_seg) and "r" or OTHER_LAND.search(after_seg) and "o"
        typed_before = RESIDENTIAL.search(before_seg) and "r" or OTHER_LAND.search(before_seg) and "o"
        if typed_before and re.search(r"dien tich|\bdt\b|tong", before_seg):
            typed_before = None                       # "đất ở ... diện tích 120m2" -> là tổng của thửa
        typed = typed_after or typed_before
        if typed == "r":
            resid.append(v)
            land.append(v)
        elif typed == "o":
            other.append(v)
            land.append(v)
        elif re.search(r"dien tich|\bdt\b|dien tich (thuc te|thuc do|do dac|ke bien)|quyen su dung|thua|lo dat|o dat|\bdat\b",
                       before[-45:] + after[:20]):
            generic.append(v)
    # chỉ có 1 diện tích tổng + mục đích sử dụng duy nhất ("mục đích sử dụng đất: Đất ở tại đô thị",
    # "Quyền sử dụng đất HNK diện tích ...") -> toàn bộ thuộc loại đó
    if generic and not land and not resid and not other:
        purpose = re.search(r"muc dich (su dung )?(dat)?\s*:?\s*([^;.]{0,60})", norm)
        seg = purpose.group(3) if purpose else ""
        if not seg and (m0 := re.search(r"quyen su dung dat\s+([a-z]{3})\b\s*(dien tich|dt)", norm)):
            seg = m0.group(1)
        if seg and not re.search(r"\d", seg[:40]):
            if RESIDENTIAL.search(seg) and not OTHER_LAND.search(seg):
                resid.append(generic[0])
            elif OTHER_LAND.search(seg) and not RESIDENTIAL.search(seg):
                other.append(generic[0])
    out: dict = {}
    # tổng diện tích đất: các diện tích có gắn loại đất + diện tích chung đầu tiên của mỗi thửa
    total = sum(land) if land else (generic[0] if generic else None)
    if generic and land and generic[0] > total:
        total = generic[0]
    if total and resid + other and sum(resid) + sum(other) > total + 0.5:
        total = sum(resid) + sum(other)               # nhiều thửa: tổng không nhỏ hơn tổng các phần
    if total:
        out["land_area"] = round(total, 2)
    if resid:
        out["residential_area"] = round(sum(resid), 2)
    if other:
        out["other_land_area"] = round(sum(other), 2)
    elif resid and total and total > sum(resid) + 0.5:
        out["other_land_area"] = round(total - sum(resid), 2)
    if floor:
        out["floor_area"] = round(max(floor) if len(set(floor)) == 1 else sum(floor), 2)
    return out


def _parcels(norm: str) -> list[tuple[str | None, str | None]]:
    """Ghép (tờ, thửa) theo thứ tự xuất hiện; hỗ trợ 'thửa ... tờ ...' và 'tờ ... thửa ...'."""
    toks = []
    for m in re.finditer(r"\bthua(?:\s+dat)?(?:\s+so)?\s*:?\s*(\d{1,6}[a-z]?(?:\(\d+\))?)", norm):
        toks.append(("thua", m.start(), re.sub(r"\(.*", "", m.group(1))))
    for m in re.finditer(r"\b(?:to ban do|tbd|to bd|to)(?:\s+so)?\s*:?\s*(\d{1,4}[a-z]?(?:\(\d+\))?)", norm):
        toks.append(("to", m.start(), re.sub(r"\(.*", "", m.group(1))))
    toks.sort(key=lambda t: t[1])
    pairs: list[tuple[str | None, str | None]] = []
    cur: dict[str, str | None] = {}
    for kind, _, val in toks:
        if kind in cur:
            pairs.append((cur.get("to"), cur.get("thua")))
            cur = {}
        cur[kind] = val
        if "to" in cur and "thua" in cur:
            pairs.append((cur["to"], cur["thua"]))
            cur = {}
    if cur.get("thua") or cur.get("to"):
        pairs.append((cur.get("to"), cur.get("thua")))
    seen, out = set(), []
    for p in pairs:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:30]


def _dimensions(norm: str) -> tuple[float | None, float | None]:
    w = l = None
    if m := re.search(rf"(?:chieu ngang|ngang|mat tien(?: rong)?|chieu rong)\s*:?\s*(?:khoang\s*)?({NUM})\s*m\b", norm):
        w = parse_number(m.group(1))
    if m := re.search(rf"(?:chieu dai|chieu sau|dai)(?: binh quan)?\s*:?\s*(?:khoang\s*)?({NUM})\s*m\b", norm):
        l = parse_number(m.group(1))
    if (w is None or l is None) and (m := re.search(rf"kich thuoc\s*:?\s*\(?\s*({NUM})\s*m?\s*x\s*({NUM})\s*m", norm)):
        a, b = parse_number(m.group(1)), parse_number(m.group(2))
        if a and b:
            w, l = w or min(a, b), l or max(a, b)
    return w, l


def detect_ward(*texts: str | None) -> str | None:
    """Xã/phường nơi có tài sản; ưu tiên tên hiện hành trong '(nay là ...)'."""
    for t in texts:
        if not t:
            continue
        for seg in re.findall(r"\(\s*nay l[àa]\s*:?\s*([^)]+)\)", t, re.I) or []:
            if w := _last_ward(seg):
                return w
        if w := _last_ward(t[:600]):
            return w
    return None


def _last_ward(t: str) -> str | None:
    hits = list(WARD_RE.finditer(t))
    if not hits:
        return None
    # địa chỉ viết nhỏ -> lớn: lấy xã/phường đầu tiên đứng sau 'tọa lạc|tại|địa chỉ' nếu có, không thì cái đầu
    m = hits[0]
    kind = m.group(1).lower()
    kind = WARD_PREFIX.get(kind, kind.capitalize())
    name = re.sub(r"\s+", " ", m.group(2)).strip(" .-")
    name = " ".join(w if w.isupper() and len(w) <= 3 else w[:1].upper() + w[1:] for w in name.split())
    return f"{kind} {name}"


def extract(title: str, asset_name: str | None = None, address: str | None = None,
            asset_type: str | None = None, extra: list[str] | None = None) -> RealEstateInfo:
    text = " \n".join(x for x in [asset_name or title, *(extra or [])] if x)
    norm = strip_accents(text)
    info = RealEstateInfo(sale_form=detect_sale_form(f"{title} {asset_name or ''}", asset_type))
    for k, v in _areas(text, norm).items():
        setattr(info, k, v)
    info.parcels = _parcels(norm)
    info.width, info.length = _dimensions(norm)
    info.ward = detect_ward(address, asset_name, title)
    if m := re.search(r"\blan\s*(?:thu\s*)?(\d{1,2})\b", strip_accents(title or "")):
        info.session_hint = int(m.group(1))
    info.has_house = bool(re.search(r"\bnha o\b|can ho|nha xay|tai san gan lien|cong trinh xay dung|biet thu|nha \d+ tang", norm))
    return info
