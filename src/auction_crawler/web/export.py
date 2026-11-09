"""Xuất danh sách tài sản (theo bộ lọc đang chọn) ra Excel."""
from __future__ import annotations

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from ..realestate.db import CATEGORIES, OWNER_TYPES, PRIORITIES, SALE_FORMS

COLUMNS = [  # (tiêu đề, hàm lấy giá trị, độ rộng, định dạng số)
    ("Mã", lambda p: p.id, 7, None),
    ("Tên tài sản", lambda p: p.title, 60, None),
    ("Hình thức", lambda p: SALE_FORMS.get(p.sale_form, ""), 14, None),
    ("Loại BĐS", lambda p: CATEGORIES.get(p.category or "", ""), 14, None),
    ("Chủ tài sản (loại)", lambda p: OWNER_TYPES.get(p.owner_type or "khac", ""), 20, None),
    ("Người có tài sản", lambda p: p.owner_name, 35, None),
    ("Tỉnh/TP", lambda p: p.eff("province"), 16, None),
    ("Xã/phường", lambda p: p.eff("ward"), 20, None),
    ("Địa chỉ", lambda p: p.eff("address"), 40, None),
    ("Số tờ", lambda p: p.eff("map_sheet"), 8, None),
    ("Số thửa", lambda p: p.eff("parcel_no"), 9, None),
    ("Tổng DT đất (m²)", lambda p: p.eff("land_area"), 12, "#,##0.0"),
    ("DT đất ở (m²)", lambda p: p.eff("residential_area"), 12, "#,##0.0"),
    ("DT đất khác (m²)", lambda p: p.eff("other_land_area"), 12, "#,##0.0"),
    ("DT sàn (m²)", lambda p: p.eff("floor_area"), 11, "#,##0.0"),
    ("Ngang (m)", lambda p: p.eff("width"), 9, "#,##0.00"),
    ("Dài (m)", lambda p: p.eff("length"), 9, "#,##0.00"),
    ("Giá hiện tại (đ)", lambda p: p.eff("price_latest"), 16, "#,##0"),
    ("Giá phiên 1 (đ)", lambda p: p.eff("price_first"), 16, "#,##0"),
    ("Giảm so phiên 1 (%)", lambda p: p.discount_pct, 10, "0.0"),
    ("Số phiên", lambda p: p.session_count, 8, None),
    ("Tiền đặt trước (đ)", lambda p: p.deposit_latest, 15, "#,##0"),
    ("Hạn đăng ký", lambda p: p.registration_end, 17, "dd/mm/yyyy hh:mm"),
    ("Ngày đấu giá", lambda p: p.auction_date, 17, "dd/mm/yyyy hh:mm"),
    ("Ưu tiên", lambda p: PRIORITIES.get(p.priority or 0, ""), 11, None),
    ("Đã xác thực", lambda p: "Có" if p.verified else "", 10, None),
    ("Cảnh báo gom phiên", lambda p: p.link_warning, 25, None),
]


def properties_xlsx(items, base_url: str = "") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Tài sản"
    ws.append([c[0] for c in COLUMNS] + ["Link"])
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0F5C4D")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for p in items:
        row = [fn(p) for _, fn, _, _ in COLUMNS]
        url = f"{base_url}/p/{p.id}"
        ws.append(row + [url])
        ws.cell(row=ws.max_row, column=len(COLUMNS) + 1).hyperlink = url
    for i, (_, _, width, fmt) in enumerate(COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
        if fmt:
            for (cell,) in ws.iter_rows(min_row=2, min_col=i, max_col=i):
                cell.number_format = fmt
    ws.column_dimensions[get_column_letter(len(COLUMNS) + 1)].width = 30
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
