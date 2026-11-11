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


def price_chart(points: list[tuple]) -> str:
    """Biểu đồ đường giá khởi điểm qua các phiên (SVG nội tuyến, 1 dãy -> không cần chú giải).
    points: [(nhãn trục x, giá, chú thích khi rê chuột)]. Ít hơn 2 phiên có giá -> ''."""
    from html import escape
    pts = [(lbl, v, tip) for lbl, v, tip in points if v]
    if len(pts) < 2:
        return ""
    W, H, L, R, T, B = 640, 220, 64, 40, 16, 34
    lo, hi = min(v for _, v, _ in pts), max(v for _, v, _ in pts)
    lo = 0 if lo > 0 and (hi - lo) / hi > 0.6 else lo * 0.9          # trục bắt đầu gần giá thấp nhất cho dễ thấy nhịp giảm
    hi = hi * 1.04
    sx = lambda i: L + (W - L - R) * (i / (len(pts) - 1))  # noqa: E731
    sy = lambda v: T + (H - T - B) * (1 - (v - lo) / (hi - lo or 1))  # noqa: E731
    out = [f'<svg class="pchart" viewBox="0 0 {W} {H}" role="img" aria-label="Biểu đồ giá khởi điểm qua các phiên">']
    for k in range(4):                                                   # lưới ngang mờ + nhãn giá
        v = lo + (hi - lo) * k / 3
        y = sy(v)
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                   f'<text x="{L - 8}" y="{y + 4:.1f}" class="ax" text-anchor="end">{escape(money(v))}</text>')
    path = " ".join(f"{'M' if i == 0 else 'L'}{sx(i):.1f},{sy(v):.1f}" for i, (_, v, _) in enumerate(pts))
    out.append(f'<path d="{path}" class="ln"/>')
    for i, (lbl, v, tip) in enumerate(pts):
        x, y = sx(i), sy(v)
        out.append(f'<g class="pt"><circle cx="{x:.1f}" cy="{y:.1f}" r="14" class="hit"/>'
                   f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" class="dot"/>'
                   f'<title>{escape(tip)}</title></g>'
                   f'<text x="{x:.1f}" y="{H - 12}" class="ax" text-anchor="middle">{escape(lbl)}</text>')
    lx, ly = sx(len(pts) - 1), sy(pts[-1][1])                            # nhãn trực tiếp: chỉ điểm cuối
    out.append(f'<text x="{lx - 8:.1f}" y="{ly - 10:.1f}" class="lbl" text-anchor="end">{escape(money(pts[-1][1]))}</text>')
    out.append("</svg>")
    return "".join(out)


def bar_chart(bars: list[tuple[str, int, str]]) -> str:
    """Biểu đồ cột dọc 1 dãy (SVG): [(nhãn trục x, giá trị, chú thích khi rê chuột)]."""
    from html import escape
    if not bars:
        return ""
    W, H, L, B, T = 640, 200, 36, 30, 14
    hi = max(v for _, v, _ in bars) or 1
    step = (W - L - 8) / len(bars)
    bw = max(6, min(36, step - 6))
    out = [f'<svg class="pchart" viewBox="0 0 {W} {H}" role="img">']
    for k in range(3):
        v = hi * k / 2
        y = T + (H - T - B) * (1 - v / hi)
        out.append(f'<line x1="{L}" x2="{W - 8}" y1="{y:.1f}" y2="{y:.1f}" class="grid"/>'
                   f'<text x="{L - 6}" y="{y + 4:.1f}" class="ax" text-anchor="end">{int(v)}</text>')
    for i, (lbl, v, tip) in enumerate(bars):
        x = L + step * i + (step - bw) / 2
        h = (H - T - B) * v / hi
        y = H - B - h
        out.append(f'<g class="pt"><rect x="{x - 3:.1f}" y="{T}" width="{bw + 6:.1f}" height="{H - T - B}" class="hit"/>'
                   f'<path d="M{x:.1f},{H - B} V{y + min(4, h):.1f} q0,-{min(4, h):.1f} {min(4, h):.1f},-{min(4, h):.1f} '
                   f'H{x + bw - min(4, h):.1f} q{min(4, h):.1f},0 {min(4, h):.1f},{min(4, h):.1f} V{H - B} Z" class="bar"/>'
                   f'<title>{escape(tip)}</title></g>')
        if len(bars) <= 16 or i % 2 == 0:
            out.append(f'<text x="{x + bw / 2:.1f}" y="{H - 12}" class="ax" text-anchor="middle">{escape(lbl)}</text>')
    out.append("</svg>")
    return "".join(out)
