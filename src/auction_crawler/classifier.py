"""Phân loại tin đấu giá theo quy tắc từ khoá (config/categories.yaml).

Mỗi chiều phân loại (asset_type, origin) có trọng số theo TRƯỜNG dữ liệu (field_weights), vd nguồn
gốc tài sản chủ yếu xác định từ 'người có tài sản', còn loại tài sản từ tên tài sản.
Điểm = Σ trọng_số_từ_khoá × trọng_số_trường × (1 + 0.25 × số lần lặp, tối đa 3).

Thiết kế dạng plugin: có thể thay RuleClassifier bằng mô hình ML cùng interface.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol

from .config import load_categories
from .normalize import strip_accents

DEFAULT_FIELD_WEIGHTS = {"text": 1.0}


@dataclass
class Label:
    dimension: str
    code: str | None
    score: float
    label: str | None = None


class Classifier(Protocol):
    def classify(self, text: str | dict[str, str | None]) -> dict[str, Label]: ...


class RuleClassifier:
    def __init__(self, rules: dict[str, Any] | None = None, fallback: str = "khac"):
        rules = rules if rules is not None else load_categories()
        self.field_weights: dict[str, dict[str, float]] = rules.get("field_weights", {})
        self.rules = {k: v for k, v in rules.items() if k != "field_weights"}
        self.fallback = fallback
        self._compiled: dict[str, list[tuple]] = {}
        for dim, groups in self.rules.items():
            items = []
            for code, g in (groups or {}).items():
                pats = [self._pat(k) for k in g.get("keywords", [])]
                excl = [self._pat(k) for k in g.get("exclude", [])]
                only = set(g.get("fields") or [])   # giới hạn trường áp dụng cho nhóm (tuỳ chọn)
                items.append((code, g.get("label", code), float(g.get("weight", 1)), pats, excl, only))
            self._compiled[dim] = items

    @staticmethod
    def _pat(k: str) -> re.Pattern:
        return re.compile(rf"(?<![a-z0-9]){re.escape(strip_accents(k).strip())}(?![a-z0-9])")

    def classify(self, text: str | dict[str, str | None]) -> dict[str, Label]:
        fields = {"text": text} if isinstance(text, str) else text
        norm = {k: strip_accents(v) for k, v in fields.items() if v}
        out: dict[str, Label] = {}
        for dim, items in self._compiled.items():
            fw = self.field_weights.get(dim) or {}
            best = Label(dim, self.fallback, 0.0, "Khác")
            for code, label, weight, pats, excl, only in items:
                score = 0.0
                for fname, ftext in norm.items():
                    if only and fname not in only and fname != "text":
                        continue
                    w = fw.get(fname, fw.get("*", 1.0)) if fw else 1.0
                    if not w:
                        continue
                    if any(e.search(ftext) for e in excl):
                        continue
                    for p in pats:
                        n = len(p.findall(ftext))
                        if n:
                            score += weight * w * (1 + min(n - 1, 3) * 0.25)
                if score > best.score:
                    best = Label(dim, code, round(score, 2), label)
            out[dim] = best
        return out

    def label_of(self, dim: str, code: str | None) -> str:
        if not code:
            return ""
        return (self.rules.get(dim, {}).get(code) or {}).get("label", code if code != "khac" else "Khác")
