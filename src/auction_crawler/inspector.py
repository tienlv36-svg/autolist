"""Công cụ hỗ trợ dò cấu trúc trang: gợi ý selector danh sách, phân trang, endpoint API."""
from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

API_HINT = re.compile(r"""["'`]([^"'`\s]*(?:/api/|ajax|\.json|/services?/|handler|\.ashx|\.asmx|getlist|search)[^"'`\s]*)["'`]""", re.I)
PAGE_HINT = re.compile(r"(page|trang|pageindex|p)=\d+|/page[-/]\d+|trang-\d+", re.I)


def _sig(el: Tag) -> str:
    cls = ".".join(sorted(el.get("class") or []))
    return f"{el.name}{'.' + cls if cls else ''}"


def _css_path(el: Tag) -> str:
    parts = []
    while el is not None and el.name not in ("[document]", "html", "body") and len(parts) < 4:
        if el.get("id"):
            parts.append(f"#{el['id']}")
            break
        parts.append(_sig(el))
        el = el.parent
    return " > ".join(reversed(parts))


def analyze_html(html: str, base_url: str) -> dict[str, Any]:
    raw = html
    soup = BeautifulSoup(html, "lxml")
    scripts_src = [urljoin(base_url, s["src"]) for s in soup.find_all("script", src=True)]
    inline_js = "\n".join(s.get_text() for s in soup.find_all("script") if not s.get("src"))

    # 1) Khối lặp lại có chứa link -> ứng viên item danh sách
    candidates = Counter()
    examples: dict[str, str] = {}
    for parent in soup.find_all(True):
        kids = [c for c in parent.find_all(recursive=False) if isinstance(c, Tag)]
        if len(kids) < 4:
            continue
        sigs = Counter(_sig(k) for k in kids if k.find("a", href=True))
        for sig, n in sigs.items():
            if n >= 4:
                path = f"{_css_path(parent)} > {sig}"
                candidates[path] = max(candidates[path], n)
                k = next(k for k in kids if _sig(k) == sig and k.find("a", href=True))
                examples[path] = re.sub(r"\s+", " ", k.get_text(" ", strip=True))[:160]
    list_candidates = [{"selector": s, "count": n, "example": examples[s]} for s, n in candidates.most_common(8)]

    # 2) Link phân trang
    pages = sorted({urljoin(base_url, a["href"]) for a in soup.find_all("a", href=True) if PAGE_HINT.search(a["href"])})[:15]
    onclick_pages = sorted({a.get("onclick") or a.get("href") for a in soup.find_all("a")
                            if re.search(r"__doPostBack|javascript:.*(page|trang)", (a.get("onclick") or a.get("href") or ""), re.I)})[:10]

    # 3) Form (có thể phân trang/lọc bằng POST)
    forms = []
    for f in soup.find_all("form"):
        forms.append({
            "action": urljoin(base_url, f.get("action") or ""), "method": (f.get("method") or "GET").upper(),
            "inputs": [{"name": i.get("name"), "type": i.get("type"), "value": (i.get("value") or "")[:40]}
                       for i in f.find_all(["input", "select"]) if i.get("name")][:30],
        })

    # 4) Gợi ý endpoint API trong JS
    api_hints = sorted(set(API_HINT.findall(inline_js)) | set(API_HINT.findall(raw)))[:30]

    text_len = len(soup.get_text(" ", strip=True))
    return {
        "title": soup.title.get_text(strip=True) if soup.title else None,
        "text_length": text_len,
        "likely_js_rendered": text_len < 1500 or bool(soup.select("app-root, #app, #root, [ng-app], [ng-version]")),
        "list_candidates": list_candidates,
        "pagination_links": pages,
        "postback_pagination": onclick_pages,
        "forms": forms,
        "api_hints": api_hints,
        "scripts": scripts_src[:20],
    }
