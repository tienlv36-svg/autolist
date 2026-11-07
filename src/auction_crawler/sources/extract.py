"""Hàm trích xuất dùng chung: theo CSS selector, theo nhãn 'Nhãn: giá trị', theo đường dẫn JSON."""
from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag

from ..normalize import clean_text, strip_accents


def soupify(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(unicodedata.normalize("NFC", html), "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    return soup


def select_field(node: Tag, spec: dict[str, Any] | str, base_url: str | None = None) -> str | None:
    """spec: {css: "a.title, a", attr: text|html|href|<attr>, regex: "...", multi: false}
    CSS có thể liệt kê nhiều selector cách bởi dấu phẩy -> lấy phần tử đầu tiên khớp."""
    if isinstance(spec, str):
        spec = {"css": spec}
    css, attr = spec.get("css"), spec.get("attr", "text")
    els = node.select(css) if css else [node]
    if not els:
        return None
    if spec.get("multi"):
        vals = [_value(e, attr, base_url) for e in els]
        val = " | ".join(v for v in vals if v)
    else:
        val = _value(els[0], attr, base_url)
    if val and (rx := spec.get("regex")):
        m = re.search(rx, val, re.S)
        val = (m.group(1) if m and m.groups() else m.group(0)) if m else None
    return clean_text(val)


def _value(el: Tag, attr: str, base_url: str | None) -> str | None:
    if attr == "text":
        return el.get_text(" ", strip=True)
    if attr == "html":
        return str(el)
    v = el.get(attr)
    if isinstance(v, list):
        v = " ".join(v)
    if v and attr in ("href", "src") and base_url:
        v = urljoin(base_url, v)
    return v


# ------------------------------------------------------------ trích theo nhãn

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", strip_accents(s)).strip()


def _label_re(nl: str) -> re.Pattern:
    """Nhãn phải đứng đầu khối hoặc sau dấu ngắt (; . • - số thứ tự), để 'tổ chức đấu giá'
    không khớp nhầm bên trong 'thời gian tổ chức đấu giá'."""
    return re.compile(rf"(?:^\s*(?:[a-z0-9]{{1,3}}[.)])?\s*|[;.•*\-–+]\s*){re.escape(nl)}(?!\w)")


def extract_by_labels(soup: Tag, label_map: dict[str, list[str]], max_len: int = 600) -> dict[str, str]:
    """Tìm giá trị đứng sau các nhãn kiểu:
       <tr><td>Giá khởi điểm</td><td>1.000.000 đ</td></tr>
       <p><b>Giá khởi điểm:</b> 1.000.000 đồng</p>
       <li>Giá khởi điểm: 1.000.000 đồng; Tiền đặt trước: ...</li>
       <div class=label>Giá khởi điểm</div><div class=value>...</div>
    """
    all_labels = sorted({_norm(l) for ls in label_map.values() for l in ls}, key=len, reverse=True)
    result: dict[str, str] = {}
    text_nodes = [t for t in soup.find_all(string=True) if isinstance(t, NavigableString) and t.strip()]
    for field, labels in label_map.items():
        for label in labels:
            nl = _norm(label)
            val = None
            rx = _label_re(nl)
            for tn in text_nodes:
                if not rx.search(_norm(str(tn))):
                    continue
                val = _value_after_label(tn, nl, all_labels, max_len)
                if val:
                    break
            if val:
                result[field] = val
                break
    return result


def _cut_after(text: str, nl: str) -> str | None:
    """Phần văn bản sau nhãn (so khớp không dấu nhưng cắt trên chuỗi gốc)."""
    norm_chars = []  # map vị trí chuỗi chuẩn hoá -> vị trí gốc
    idx_map = []
    for i, ch in enumerate(text):
        n = strip_accents(ch)
        if n.isspace():
            if norm_chars and norm_chars[-1] == " ":
                continue
            n = " "
        for c in n:
            norm_chars.append(c)
            idx_map.append(i)
    ns = "".join(norm_chars).lstrip()
    lead = len("".join(norm_chars)) - len(ns)
    idx_map = idx_map[lead:]
    m = _label_re(nl).search(ns)
    if not m:
        return None
    end = m.end()
    orig_end = idx_map[end - 1] + 1 if end - 1 < len(idx_map) else len(text)
    return text[orig_end:]


def _trim(rest: str | None, all_labels: list[str], current: str, max_len: int) -> str | None:
    if rest is None:
        return None
    # nhãn có đuôi dài hơn: "Thời gian tổ chức| đấu giá: 09 giờ" -> bỏ phần chữ trước ':'
    rest = re.sub(r"^[^\d:：\n]{0,30}?[:：]\s*", "", rest, count=1) if re.match(r"^[^\d:：\n]{0,30}[:：]", rest) else rest
    rest = re.sub(r"^\s*(\([^)]*\))?\s*[:：\-–]\s*", "", rest)  # bỏ ':' và chú thích '(đồng)' ngay sau nhãn
    # cắt tại nhãn khác xuất hiện tiếp theo trong cùng khối
    nrest = strip_accents(rest)
    cut = len(rest)
    for ol in all_labels:
        if ol == current or current in ol:
            continue
        m = re.search(rf"(?:^|[\s;.,]){re.escape(ol)}\s*[:：]", nrest)
        if m and m.start() > 0:
            cut = min(cut, m.start())
    val = clean_text(rest[:cut])
    if val and len(val) > max_len:
        val = val[:max_len].rsplit(" ", 1)[0] + "…"
    return val if val and len(val) > 1 else None


def _value_after_label(tn: NavigableString, nl: str, all_labels: list[str], max_len: int) -> str | None:
    el = tn.parent
    # 1) văn bản sau nhãn trong chính phần tử, rồi đi lên tối đa 2 cấp (nhãn nằm trong <b>, <span>)
    for _ in range(3):
        if el is None:
            break
        val = _trim(_cut_after(el.get_text(" ", strip=True), nl), all_labels, nl, max_len)
        if val:
            return val
        if el.name in ("td", "th", "dt", "label") or "label" in (el.get("class") or []):
            break
        el = el.parent
    # 2) ô/khối kế bên: <td>nhãn</td><td>giá trị</td>, <dt>/<dd>, div.label + div.value
    node = tn.parent
    for _ in range(3):
        if node is None:
            break
        sib = node.find_next_sibling()
        if sib is not None:
            val = _trim(sib.get_text(" ", strip=True), all_labels, nl, max_len)
            if val:
                return val
        node = node.parent
    return None


# ------------------------------------------------------------ JSON

def json_path(obj: Any, path: str | None) -> Any:
    """'data.items' / 'result.0.name' -> giá trị; path rỗng -> obj."""
    if not path:
        return obj
    for part in path.split("."):
        if obj is None:
            return None
        if isinstance(obj, list):
            try:
                obj = obj[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj
