"""Định dạng hiển thị kiểu Việt Nam."""
from __future__ import annotations

from datetime import date, datetime


def money(v: int | float | None, short: bool = True) -> str:
    if v in (None, 0):
        return "—"
    if not short:
        return f"{int(v):,}".replace(",", ".") + " đ"
    if v >= 1e9:
        return f"{v / 1e9:,.2f}".rstrip("0").rstrip(".").replace(".", ",") + " tỷ"
    if v >= 1e6:
        return f"{v / 1e6:,.0f}".replace(",", ".") + " triệu"
    return f"{int(v):,}".replace(",", ".") + " đ"


def area(v: float | None) -> str:
    if v in (None, 0):
        return "—"
    s = f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return s.removesuffix(",0") + " m²"


def num(v: float | None, unit: str = "") -> str:
    if v in (None, ""):
        return "—"
    s = f"{v:,.2f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s}{unit}"


def dt(v: datetime | date | None, with_time: bool = True) -> str:
    if not v:
        return "—"
    if isinstance(v, datetime):
        return v.strftime("%H:%M %d/%m/%Y") if with_time and (v.hour or v.minute) else v.strftime("%d/%m/%Y")
    return v.strftime("%d/%m/%Y")


def days_left(v: datetime | None) -> tuple[str, str]:
    """(nhãn, mức) cho hạn đăng ký: mức = expired | urgent | soon | ok"""
    if not v:
        return "Chưa rõ hạn", "unknown"
    d = (v - datetime.now()).total_seconds() / 86400
    if d < 0:
        return "Đã hết hạn", "expired"
    if d < 1:
        return f"Còn {int(d * 24)} giờ", "urgent"
    return f"Còn {int(d)} ngày", "urgent" if d < 3 else "soon" if d < 7 else "ok"


def size(v: int | None) -> str:
    if not v:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024:
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} TB"


def plain(v) -> str:
    return "trống" if v in (None, "") else str(v)
