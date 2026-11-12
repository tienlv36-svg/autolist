"""Trích xuất thuộc tính bất động sản từ văn bản tin đấu giá - CHẾ ĐỘ THẬN TRỌNG.

Nguyên tắc: chỉ tự điền khi thông tin được GHI RÕ trong tin, có NHÃN rõ ràng và CHỈ CÓ MỘT giá trị.
Không suy luận, không cộng dồn, không lấy hiệu số. Có nhiều thửa / nhiều giá trị khác nhau / mâu thuẫn
-> để trống và ghi lý do vào `notes` để người dùng nhập tay.

Ví dụ ĐIỀN:  "thửa đất số 30, tờ bản đồ số 59, diện tích: 130 m2"          -> tờ 59, thửa 30, 130 m2
             "Diện tích: 319,5m2 (Trong đó có 100m2 đất ở ... và 219,5m2 đất trồng cây lâu năm)"
                                                                         -> tổng 319,5; đất ở 100; khác 219,5
             "Diện tích xây dựng: 206,1m2; Diện tích sàn: 439,5m2"        -> sàn 439,5
             "... tỉnh Bình Dương (nay là phường Chánh Hiệp, Tp. Hồ Chí Minh)" -> Phường Chánh Hiệp, TP.HCM
Ví dụ ĐỂ TRỐNG:
             "diện tích 80,0 m2 (Theo sơ đồ đo đạc diện tích còn 76,4 m2)"  -> 2 giá trị khác nhau
             "thửa 589 ... thửa 593 ..." (nhiều thửa)                     -> diện tích, tờ/thửa
             "diện tích 162m2, mục đích sử dụng: Đất ở" (không có số đi kèm loại đất) -> đất ở trống
             "kích thước 10,1m x 5,1m" (không rõ chiều nào là ngang)       -> ngang/dài trống
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from ..normalize import PROVINCE_MERGE, strip_accents

NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"
M2 = r"\s*(?:m2|m²|m\s*2\b|mét vuông|met vuong)"
RESIDENTIAL = re.compile(r"\bdat o\b|\bodt\b|\bont\b|\bo dt\b")
OTHER_LAND = re.compile(r"\b(cln|luc|bhk|lua|nts|hnk|skc|tmd|rsx|lnk|ctd|nhk|dgt|tsn)\b|trong (cay|lua)|cay lau nam|"
                        r"cay hang nam|nong nghiep|nuoi trong|thuy san|san xuat kinh doanh|thuong mai|dich vu|"
                        r"rung san xuat|mat nuoc|giao thong|thuy loi|chuyen dung|phi nong nghiep|chuyen trong")
MULTI_RE = re.compile(r"\bcac (lo|thua|o dat|can|nen)\b|\b\d+\s*(lo|thua|o dat|can ho|can nha|nen)\b|tron goi|"
                      r"\btai san (so )?\d+\s*:|\blo (so )?\d+\s*:|\(lo \d+\)")
WARD_RE = re.compile(r"\b(xã|phường|thị trấn|đặc khu|p\.|x\.|tt\.)\s*([^\W\d_][^,;()\n]{1,40}?|\d{1,2})"
                     r"(?=\s*(?:,|;|\||\(|\)|\.\s|$|-|–|\btỉnh\b|\bthành phố\b|\btp\b|\bhuyện\b|\bquận\b|\bthị xã\b))",
                     re.I)
WARD_PREFIX = {"p.": "Phường", "x.": "Xã", "tt.": "Thị trấn"}


def parse_number(s: str) -> float | None:
    """'3.198,1' -> 3198.1 ; '1.036' -> 1036 ; '76.4' -> 76.4 ; '136,1' -> 136.1"""
    s = s.strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") == 1 and len(s.split(".")[1]) != 3:
        pass
    else:
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def _one(values: list[float], tol: float = 0.05) -> float | None:
    """Trả giá trị nếu mọi giá trị trùng nhau (cùng một số được nhắc lại), ngược lại None."""
    if not values:
        return None
    return round(values[0], 2) if all(abs(v - values[0]) <= tol for v in values) else None


@dataclass
class RealEstateInfo:
    sale_form: str = "ban"                 # ban | cho_thue | khoan_no
    land_area: float | None = None
    residential_area: float | None = None
    other_land_area: float | None = None
    floor_area: float | None = None
    width: float | None = None
    length: float | None = None
    parcels: list[tuple[str | None, str | None]] = field(default_factory=list)  # mọi (tờ, thửa) nhắc trong tin
    map_sheet: str | None = None           # chỉ khi xác định được DUY NHẤT một cặp tờ/thửa
    parcel_no: str | None = None
    ward: str | None = None
    province: str | None = None
    province_raw: str | None = None
    ward_new: bool = False                 # tên xã/phường lấy từ "(nay là ...)" (tên sau sắp xếp 2025)
    loc_candidates: list[dict] = field(default_factory=list)   # các vị trí khác nhau tìm thấy (để xác nhận 1 chạm)
    multi: bool = False                    # tin gồm nhiều thửa/lô
    session_hint: int | None = None
    has_house: bool = False
    notes: list[str] = field(default_factory=list)   # lý do để trống

    def dict(self) -> dict:
        d = asdict(self)
        d["parcels"] = [list(p) for p in self.parcels]
        return d


def detect_sale_form(title: str, asset_type: str | None) -> str:
    n = strip_accents(title or "")
    if asset_type == "khoan_no" or re.search(r"khoan no|quyen (thu hoi|doi) no|hop dong tin dung", n):
        return "khoan_no"
    if re.search(r"\bcho thue\b|quyen (khai thac|thue)|thue mat bang|\bthoi gian (cho )?thue\b", n):
        return "cho_thue"
    return "ban"


# ------------------------------------------------------------------ tờ / thửa
def _parcel_tokens(norm: str) -> list[tuple[str, int, str]]:
    """Token (loại, vị trí, số). Bỏ qua thửa nhắc trong mô tả ranh giới ('giáp thửa 620');
    số trong '(nay là tờ bản đồ số 52)' là SỐ MỚI của cùng thửa -> thay cho số cũ, không tính thêm thửa."""
    nay_spans = [(m.start(), m.end()) for m in re.finditer(r"\(\s*nay(?: la)?\b[^)]*\)", norm)]
    toks: list[tuple[str, int, str]] = []
    pats = (("thua", r"\bthua(?:\s+dat)?(?:\s+so)?(?:\s+tach)?\s*:?\s*(\d{1,6}[a-z]?)(?:\(\d+\))?"),
            ("to", r"\b(?:to ban do|tbd|to bd)(?:\s+so)?\s*:?\s*(\d{1,4}[a-z]?)(?:\(\d+\))?"))
    for kind, pat in pats:
        for m in re.finditer(pat, norm):
            if re.search(r"(giap|tiep giap|ke ben|canh|lien ke|giap voi)\W*(voi\W*)?$", norm[max(0, m.start() - 20):m.start()]):
                continue
            toks.append((kind, m.start(), m.group(1)))
    toks.sort(key=lambda t: t[1])
    out: list[tuple[str, int, str]] = []
    for kind, pos, val in toks:
        if any(a <= pos < b for a, b in nay_spans):
            for j in range(len(out) - 1, -1, -1):          # thay số cũ cùng loại ngay trước đó
                if out[j][0] == kind:
                    out[j] = (kind, out[j][1], val)
                    break
            continue
        out.append((kind, pos, val))
    return out


def _parcels(norm: str) -> list[tuple[str | None, str | None]]:
    """Mọi cặp (tờ, thửa) theo thứ tự xuất hiện - để HIỂN THỊ tham khảo."""
    pairs: list[tuple[str | None, str | None]] = []
    cur: dict[str, str] = {}
    for kind, _, val in _parcel_tokens(norm):
        if kind in cur:
            pairs.append((cur.get("to"), cur.get("thua")))
            cur = {}
        cur[kind] = val
        if "to" in cur and "thua" in cur:
            pairs.append((cur["to"], cur["thua"]))
            cur = {}
    if cur:
        pairs.append((cur.get("to"), cur.get("thua")))
    out = []
    for p in pairs:
        if p not in out:
            out.append(p)
    return out[:30]


# ------------------------------------------------------------------ diện tích
def _areas(text: str, norm: str, info: RealEstateInfo) -> None:
    labeled, resid, other, floor = [], [], [], []
    for m in re.finditer(rf"({NUM}){M2}", norm):
        v = parse_number(m.group(1))
        if not v or v <= 0 or v > 50_000_000:
            continue
        before = norm[max(0, m.start() - 70):m.start()]
        after = norm[m.end():m.end() + 45]
        clause_b = re.split(r";|,(?!\d)|\.\s|m2|m²", before)[-1]            # vế câu ngay trước số
        clause_a = re.split(r"[;(]|,(?!\d)|\.\s|trong do", after)[0]       # vế câu ngay sau số
        if re.search(r"(dien tich|dt)\s*san|tong dien tich san|san xay dung", clause_b):
            floor.append((v, "tong" in clause_b))
            continue
        if re.search(r"xay dung|\bnha\b|cong trinh|phong|tang|mai|kiot|ki ot", clause_b):
            continue                                                        # diện tích nhà/công trình
        # loại đất GẮN TRỰC TIẾP với số: "100 m2 đất ở", "60 m2 (LUC)", "đất ở tại nông thôn 100m2", "(ODT) 36m2"
        typed = None
        a = after.lstrip()
        if mc := re.match(r"\(\s*([a-z]{3})\s*\)", a):
            seg = mc.group(1)
        elif a.startswith("dat"):
            seg = re.split(r"[;(]|trong do|,(?!\d)|\.\s", a)[0][:35]
        else:
            seg = ""
        if seg:
            typed = "r" if RESIDENTIAL.search(seg) else "o" if OTHER_LAND.search(seg) else None
        if typed is None and re.search(r"(dien tich|\bdt\b)\s*(dat\s*)?(o\b|odt|ont)[^0-9]{0,15}$", clause_b):
            typed = "r"                                                     # "Diện tích đất ở: 100m2"
        elif typed is None and not re.search(r"dien tich|\bdt\b|tong", clause_b):
            typed = "r" if RESIDENTIAL.search(clause_b) else "o" if OTHER_LAND.search(clause_b) else None
        is_labeled = bool(re.search(r"(dien tich|\bdt\b)[^0-9]{0,40}$|quyen su dung\s*$", clause_b)) and \
            not re.search(r"(dien tich|\bdt\b)\s*(dat\s*)?(o\b|odt|ont)", clause_b)
        if is_labeled:
            labeled.append(v)          # "Diện tích: 130 m2" ; "diện tích 120,5m2 đất ở" (vừa là tổng, vừa là đất ở)
        if typed == "r":
            resid.append(v)
        elif typed == "o":
            other.append(v)

    if info.multi:
        if labeled or resid or other:
            info.notes.append("Tin gồm nhiều thửa/lô – diện tích để trống, nhập tay theo từng tài sản")
    else:
        total = _one(labeled)
        if labeled and total is None:
            info.notes.append("Tin ghi nhiều diện tích khác nhau (vd theo sổ và theo đo đạc) – tổng diện tích để trống")
        r = _one(resid) if resid else None
        o = round(sum(other), 2) if other else None
        if total and (r or 0) + (o or 0) > total + 0.5:
            info.notes.append("Diện tích đất ở/đất khác không khớp tổng – để trống")
            r = o = None
        elif other and len(other) > 1 and not (total and abs((r or 0) + o - total) <= 0.5):
            o = None                                                        # chỉ cộng các phần khi khớp đúng tổng
        if resid and _one(resid) is None:
            info.notes.append("Có nhiều số liệu đất ở khác nhau – để trống")
        info.land_area, info.residential_area, info.other_land_area = total, r, o
        if total is None and not labeled and (r or o):
            info.notes.append("Tin không ghi tổng diện tích")
    # diện tích sàn: ưu tiên "tổng diện tích sàn"; nhiều giá trị khác nhau -> trống
    tot_floor = [v for v, is_total in floor if is_total]
    fl = _one(tot_floor) if tot_floor else _one([v for v, _ in floor])
    if floor and fl is None:
        info.notes.append("Có nhiều công trình/diện tích sàn khác nhau – diện tích sàn để trống")
    info.floor_area = fl


def _dimensions(norm: str, info: RealEstateInfo) -> None:
    def collect(label_re: str) -> list[float]:
        vals = []
        for m in re.finditer(rf"({label_re})\s*:?\s*(?:khoang\s*)?({NUM})\s*m\b", norm):
            ctx = norm[max(0, m.start() - 50):m.start()]
            if re.search(r"phia|giap|canh|mong|tuong|nha|xay|phong|mai|ket cau|cong|rao", ctx):
                continue                                                    # cạnh thửa / kích thước công trình
            if (v := parse_number(m.group(2))) is not None:
                vals.append(v)
        return vals
    w = collect(r"chieu ngang|mat tien(?: rong)?|chieu rong mat tien")
    l = collect(r"chieu dai|chieu sau(?: binh quan)?")
    info.width, info.length = _one(w), _one(l)
    if (w and info.width is None) or (l and info.length is None):
        info.notes.append("Có nhiều số đo chiều ngang/dài khác nhau – để trống")


# ------------------------------------------------------------------ vị trí
def _norm_ward(kind: str, name: str) -> str:
    kind = WARD_PREFIX.get(kind.lower(), kind.lower().capitalize())
    name = re.sub(r"\s+", " ", name).strip(" .-")
    name = " ".join(w if w.isupper() and len(w) <= 3 else w[:1].upper() + w[1:] for w in name.split())
    return f"{kind} {name}"


# chữ không thuộc tên xã/phường hay dính theo: "xã Đông Thành quản lý", "phường Tân An do …"
_WARD_STOP = {"quan", "ly", "do", "cua", "theo", "thuoc", "voi", "gom", "la", "co", "duoc", "da", "nay", "truoc", "tai",
              "thua", "dien", "nam", "lan", "cu", "moi", "va", "ban", "giao", "dang", "su", "dung", "cap", "ubnd"}


def _clean_ward_name(name: str) -> str:
    out = []
    for w in name.split():
        k = strip_accents(w).strip(".,")
        if out and (k in _WARD_STOP or k == "quản"):
            break
        out.append(w)
    return " ".join(out)


def _wards(t: str) -> list[str]:
    return list(dict.fromkeys(_norm_ward(m.group(1), _clean_ward_name(m.group(2))) for m in WARD_RE.finditer(t or "")))


def detect_ward(*texts: str | None) -> str | None:
    """Xã/phường: văn bản đầu tiên có nhắc xã/phường quyết định; chỉ nhận khi DUY NHẤT (ưu tiên tên mới có nhãn)."""
    for x in texts:
        if x and _wards(x):
            return clause_location(x).ward
    return None


# Cụm chỉ NƠI CÓ TÀI SẢN (không nhầm với địa chỉ chủ tài sản "ông A, địa chỉ: ...")
LOC_MARK = re.compile(r"t[oọ][aạ]\s*l[aạ]c(?:\s+t[aạ]i)?|đ[iị]a\s*ch[iỉ]\s+(?:th[uử]a\s*đ[aấ]t|t[aà]i\s*s[aả]n|nh[aà]\s*đ[aấ]t|"
                      r"b[aấ]t\s*đ[oộ]ng\s*s[aả]n|khu\s*đ[aấ]t|c[aă]n\s*nh[aà])|n[oơ]i\s*c[oó]\s*t[aà]i\s*s[aả]n|"
                      r"v[iị]\s*tr[ií]\s+(?:th[uử]a\s*đ[aấ]t|t[aà]i\s*s[aả]n|khu\s*đ[aấ]t)", re.I)
NAY_RE = re.compile(r"\(\s*nay\s*(?:l[àa]|thu[ộo]c)\s*:?\s*([^)]+)\)|"
                    r"\bnay\s*(?:l[àa]|thu[ộo]c)\s*:?\s*([^;()\n]+?)(?=$|;|\n|\)|\(|\.\s)", re.I)
PREV_RE = re.compile(r"\(\s*(?:tr[ưu][ớo]c\s*(?:đ[âa]y|kia)|c[ũu])\s*(?:l[àa]|thu[ộo]c)?\s*:?\s*[^)]*\)", re.I)


def _nay_parts(text: str) -> list[str]:
    return [a or b for a, b in NAY_RE.findall(text or "")]


def ward_key(w: str | None) -> str:
    """So sánh tên xã/phường bỏ dấu, bỏ khoảng trắng thừa (OCR hay sai dấu)."""
    return re.sub(r"\s+", " ", strip_accents(w or "")).strip()


def _cut_clause(seg: str) -> str:
    """Lấy vế câu vị trí: tới ';' / xuống dòng / '. ' nằm NGOÀI ngoặc."""
    depth, out = 0, []
    for i, ch in enumerate(seg):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and (ch in ";\n" or (ch == "." and seg[i + 1:i + 2] == " ")):
            break
        out.append(ch)
    return "".join(out)


@dataclass
class Loc:
    ward: str | None = None
    ward_new: bool = False
    province: str | None = None
    wards: list[str] = field(default_factory=list)        # mọi xã/phường khác nhau (cùng thời kỳ tên gọi)
    provinces: list[str] = field(default_factory=list)


def clause_location(text: str | None) -> Loc:
    """Vị trí trong MỘT đoạn chỉ địa điểm. Tên MỚI có nhãn: phần sau "nay là / nay thuộc", hoặc phần ngoài ngoặc khi
    trong ngoặc ghi "(trước đây là …)". Chỉ nhận khi các tên (bỏ dấu, bỏ trùng) chỉ có MỘT giá trị."""
    loc = Loc()
    if not text:
        return loc
    nay = _nay_parts(text)
    if nay:
        new = list(dict.fromkeys(w for seg in nay for w in _wards(seg)))
        prov_text = " ".join(nay)
    elif PREV_RE.search(text):
        new = _wards(PREV_RE.sub(" ", text))
        prov_text = PREV_RE.sub(" ", text)
    else:
        new, prov_text = [], ""
    rest = NAY_RE.sub(" ", PREV_RE.sub(" ", text))
    old = _wards(rest)
    pool, loc.ward_new = (new, True) if new else (old, False)
    uniq: dict[str, str] = {}
    for w in pool:
        uniq.setdefault(ward_key(w), w)
    loc.wards = list(uniq.values())
    if len(uniq) == 1:
        loc.ward = loc.wards[0]
    loc.provinces = list(dict.fromkeys(n for n, _ in (_provinces_in(prov_text) or _provinces_in(rest)
                                                      or _provinces_in(text))))
    if len(loc.provinces) == 1:
        loc.province = loc.provinces[0]
    return loc


def asset_location(text: str | None) -> Loc:
    """Vị trí tài sản từ các cụm 'tọa lạc tại …', 'địa chỉ thửa đất/tài sản …', 'nơi có tài sản …', 'vị trí thửa đất …'.
    Không dùng 'địa chỉ: …' trơn (thường là chỗ ở của chủ tài sản)."""
    if not text:
        return Loc()
    clauses = [_cut_clause(text[m.end():m.end() + 260]) for m in LOC_MARK.finditer(text)]
    if not clauses:
        return Loc()
    return clause_location(" ; ".join(clauses))


def pick_location(sources: list[tuple[str, Loc]]) -> tuple[str | None, bool, str | None, list[dict]]:
    """Chọn xã/phường + tỉnh từ nhiều nguồn (đã xếp theo độ tin cậy). Tên '(nay là …)' thắng tên cũ; các nguồn cùng
    thời kỳ phải KHỚP nhau (bỏ dấu), không khớp -> để trống. Trả (xã, là_tên_mới, tỉnh, ứng viên để xác nhận)."""
    cands: list[dict] = []
    for src, loc in sources:
        for w in loc.wards or [None]:
            if w or loc.province:
                cands.append({"ward": w, "province": loc.province, "source": src, "new": loc.ward_new})
    ward, ward_new = None, False
    for era in (True, False):
        vals = [loc for _, loc in sources if loc.wards and loc.ward_new == era]
        if not vals:
            continue
        keys = {ward_key(w) for loc in vals for w in loc.wards}
        if len(keys) == 1:
            ward, ward_new = vals[0].wards[0], era
        break                                   # có tên mới -> không xét tên cũ (tên cũ khác tên mới là bình thường)
    provs = {p for _, loc in sources for p in loc.provinces}
    province = provs.pop() if len(provs) == 1 else None
    seen, uniq = set(), []
    for c in cands:
        k = (ward_key(c["ward"]), c["province"])
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return ward, ward_new, province, uniq


def _province_keys() -> list[tuple[str, str, str]]:
    keys = []
    for new, olds in PROVINCE_MERGE.items():
        for n in [new, *olds]:
            k = re.sub(r"\s+", " ", strip_accents(n).replace("-", " ").replace(".", " ")).strip()
            keys.append((k, new, n))
    keys.append(("ho chi minh", "TP. Hồ Chí Minh", "Hồ Chí Minh"))
    keys.append(("tp hcm", "TP. Hồ Chí Minh", "Hồ Chí Minh"))
    return sorted(keys, key=lambda x: -len(x[0]))


_PKEYS = _province_keys()


_SUBUNIT_BEFORE = re.compile(r"(?:^|\s)(?:xa|phuong|p|x|thi tran|tt|huyen|h|quan|q|thi xa|tx|ap|thon|khu pho|kp|"
                             r"to dan pho|tdp|duong|pho|so|cum|khu|lang|ban)\s$")
_EXPLICIT_BEFORE = re.compile(r"(?:^|\s)(?:tinh|thanh pho|tp)\s$")


def _provinces_in(t: str) -> list[tuple[str, str]]:
    """Tỉnh/thành nhắc trong văn bản (đã quy đổi tên tỉnh cũ). Bỏ tên trùng tên xã/phường/huyện ("xã Bình Dương",
    "phường Khánh Hòa", "huyện Thạnh Hóa"); có tên đi sau chữ "tỉnh/thành phố" thì chỉ lấy các tên đó."""
    norm = " " + re.sub(r"[\s,.\-;:()]+", " ", strip_accents(t or "")) + " "
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, str, str, bool]] = []
    for key, new, orig in _PKEYS:
        for m in re.finditer(rf"(?<=\s){re.escape(key)}(?=\s)", norm):
            if any(a <= m.start() < b for a, b in taken):
                continue
            taken.append((m.start(), m.end()))
            before = norm[max(0, m.start() - 14):m.start()]
            explicit = bool(_EXPLICIT_BEFORE.search(before))
            if not explicit and _SUBUNIT_BEFORE.search(before):
                continue
            found.append((m.start(), new, orig, explicit))
    if any(e for *_, e in found):
        found = [f for f in found if f[3]]
    return [(n, o) for _, n, o, _ in sorted(found)]


def detect_province_strict(*texts: str | None) -> tuple[str | None, str | None]:
    """Tỉnh nơi có tài sản: chỉ từ văn bản mô tả/địa chỉ tài sản (không lấy từ tên chủ tài sản).
    Ưu tiên '(nay là ...)'. Tên tỉnh cũ được quy đổi theo Nghị quyết sáp nhập 2025 (quy đổi pháp lý, không đoán).
    Văn bản nhắc nhiều tỉnh (sau quy đổi) khác nhau -> None."""
    for t in texts:
        if not t:
            continue
        cur = []
        for seg in re.findall(r"\(\s*nay l[àa]\s*:?\s*([^)]+)\)", t, re.I):
            cur += _provinces_in(seg)
        found = cur or _provinces_in(t)
        if not found:
            continue
        news = {n for n, _ in found}
        if len(news) == 1:
            return found[-1]
        return None, None
    return None, None


# ------------------------------------------------------------------ "nơi có tài sản" có thật là nơi có tài sản?
OWNER_PLACE_RE = re.compile(r"^\W*(ngan hang|nh tmcp|chi nhanh ngan hang|(chi cuc|cuc|phong) thi hanh an|"
                            r"thi hanh an dan su|to chuc tin dung)\b")


def place_rejection(place: str | None, owner: str | None = None, owner_address: str | None = None) -> str | None:
    """Lý do KHÔNG dùng ô 'nơi có tài sản' của nguồn làm địa chỉ tài sản (hoặc None nếu dùng được).
    Một số đơn vị ghi địa chỉ trụ sở người có tài sản (ngân hàng, cơ quan thi hành án) vào ô này."""
    if not place:
        return None
    n = re.sub(r"\s+", " ", strip_accents(place)).strip()
    if (re.search(r"noi (co )?tai san|tai san toa lac|chi tiet|bang ke|danh muc|theo thong bao|kem theo|nhu tren", n)
            and not _wards(place) and not _provinces_in(place) and not re.search(r"\d", n)):
        return "ô 'nơi có tài sản' của nguồn không ghi địa chỉ cụ thể"
    if OWNER_PLACE_RE.search(n):
        return "ô 'nơi có tài sản' của nguồn ghi địa chỉ ngân hàng/cơ quan thi hành án"
    on = re.sub(r"\s+", " ", strip_accents(owner or "")).strip()
    if len(on) >= 10 and n.startswith(on[:25]):
        return "ô 'nơi có tài sản' của nguồn ghi tên/địa chỉ người có tài sản"
    oa = re.sub(r"\W+", "", strip_accents(owner_address or ""))
    if len(oa) >= 15 and re.sub(r"\W+", "", n) == oa:
        return "ô 'nơi có tài sản' trùng địa chỉ người có tài sản"
    if not re.search(r"\(\s*nay la", n) and len({x for x, _ in _provinces_in(place)}) > 1:
        return "ô 'nơi có tài sản' nhắc nhiều tỉnh/thành (thường là địa chỉ các chi nhánh)"
    return None


# ------------------------------------------------------------------ lần đấu giá
SESSION_HINT_RE = re.compile(r"dau gia\s*(?:lai\s*)?(?:\(\s*)?lan\s*(?:thu\s*)?(\d{1,2})\b|\(\s*lan\s*(?:thu\s*)?(\d{1,2})\s*\)")


def detect_session_hint(text: str) -> int | None:
    """'Đấu giá lần 3', 'đấu giá lại lần 2', 'Tài sản đấu giá (lần 5)', '... (lần 3)' -> số lần lớn nhất.
    Không nhận 'cập nhật biến động lần 01', 'đăng lần 2'..."""
    nums = [int(a or b) for a, b in SESSION_HINT_RE.findall(strip_accents(text or ""))]
    nums = [n for n in nums if 1 <= n <= 30]
    return max(nums) if nums else None


# ------------------------------------------------------------------ tổng hợp
def extract(title: str, asset_name: str | None = None, address: str | None = None,
            asset_type: str | None = None, extra: list[str] | None = None) -> RealEstateInfo:
    # bảng tài sản của nguồn thường lặp lại nguyên văn mô tả -> bỏ đoạn trùng để không đếm số liệu 2 lần
    parts: list[str] = []
    for x in [asset_name or title, *(extra or [])]:
        if not x:
            continue
        nx = re.sub(r"\W+", " ", strip_accents(x)).strip()
        if any(nx[:300] in re.sub(r"\W+", " ", strip_accents(p_)) for p_ in parts):
            continue
        parts.append(x)
    text = " \n".join(parts)
    norm = strip_accents(text)
    info = RealEstateInfo(sale_form=detect_sale_form(f"{title} {asset_name or ''}", asset_type))
    info.parcels = _parcels(norm)
    thua = {p[1] for p in info.parcels if p[1]}
    to = {p[0] for p in info.parcels if p[0]}
    info.multi = len(thua) > 1 or bool(MULTI_RE.search(strip_accents(f"{title} {asset_name or ''}")))
    # tờ/thửa: chỉ khi đúng MỘT thửa và MỘT tờ
    if not info.multi and len(thua) == 1 and len(to) == 1:
        info.map_sheet, info.parcel_no = next(iter(to)), next(iter(thua))
    elif len(thua) > 1 or len(to) > 1:
        info.notes.append("Tin nhắc nhiều tờ/thửa – số tờ, số thửa để trống")
    _areas(text, norm, info)
    _dimensions(norm, info)
    # vị trí: (1) ô nơi có tài sản, (2) cụm "tọa lạc tại…/địa chỉ thửa đất…" trong mô tả – phải khớp nhau;
    # (3) dự phòng: tên/mô tả tài sản (khi 1–2 không có), chỉ nhận khi duy nhất hoặc có nhãn "nay là"
    primary = [(s, l) for s, l in (("nơi có tài sản", clause_location(address)), ("mô tả tài sản", asset_location(text)))
               if l.wards or l.provinces]
    fb = clause_location(f"{asset_name or ''}\n{title}" if asset_name and title not in (asset_name or "") else
                         (asset_name or title))
    w, w_new, pv, cands = pick_location(primary) if primary else (None, False, None, [])
    if w is None and not any(l.wards for _, l in primary) and fb.wards:
        w, w_new = fb.ward, fb.ward_new
        if w is None:
            cands += [{"ward": x, "province": fb.province, "source": "tên tài sản", "new": fb.ward_new} for x in fb.wards]
    if pv is None and not any(l.provinces for _, l in primary):
        pv = fb.province
    info.ward, info.ward_new, info.loc_candidates = w, w_new, cands
    if w is None and (any(l.wards for _, l in primary) or len(fb.wards) > 1):
        info.notes.append("Các nguồn ghi xã/phường khác nhau – chờ xác nhận vị trí")
    if pv is None and len({p for _, l in primary for p in l.provinces} | set(fb.provinces)) > 1:
        info.notes.append("Các nguồn ghi tỉnh/thành khác nhau – chờ xác nhận vị trí")
    info.province = info.province_raw = pv
    return _finish(info, title, asset_name, norm)


def _finish(info: RealEstateInfo, title: str, asset_name: str | None, norm: str) -> RealEstateInfo:
    info.session_hint = detect_session_hint(f"{title} {asset_name or ''}")
    info.has_house = bool(re.search(r"\bnha o\b|can ho|nha xay|tai san gan lien|cong trinh xay dung|biet thu|nha \d+ tang", norm))
    return info
