"""Thống kê & xuất báo cáo (pandas -> Excel/CSV)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import select

from .classifier import RuleClassifier
from .storage import NoticeRow, Repository

COLUMNS_VI = {
    "source": "Nguồn", "source_id": "Mã tin", "title": "Tiêu đề", "asset_name": "Tài sản",
    "asset_type_label": "Loại tài sản", "origin_label": "Nguồn gốc", "asset_owner": "Người có tài sản",
    "auction_org": "Tổ chức đấu giá", "province": "Tỉnh/TP", "province_raw": "Tỉnh (theo tin)",
    "official_type": "Loại TS (theo nguồn)", "property_count": "Số tài sản",
    "address": "Nơi có tài sản", "auction_place": "Địa điểm đấu giá", "owner_address": "Địa chỉ người có TS",
    "dup_group": "Nhóm trùng", "starting_price": "Giá khởi điểm (đ)", "price_source": "Nguồn giá", "deposit": "Tiền đặt trước (đ)",
    "dossier_fee": "Tiền hồ sơ (đ)", "publish_date": "Ngày đăng", "auction_date": "Ngày đấu giá",
    "registration_start": "Mở đăng ký", "registration_end": "Hạn đăng ký", "url": "Link", "first_seen": "Thu thập lúc",
}


def load_df(repo: Repository, date_from: date | None = None, date_to: date | None = None,
            source: str | None = None) -> pd.DataFrame:
    q = select(NoticeRow)
    if source:
        q = q.where(NoticeRow.source == source)
    if date_from:
        q = q.where(NoticeRow.publish_date >= date_from)
    if date_to:
        q = q.where(NoticeRow.publish_date <= date_to)
    with repo.session() as s:
        rows = s.scalars(q).all()
    cols = [c.name for c in NoticeRow.__table__.columns if c.name not in ("raw", "content")]
    df = pd.DataFrame([{**{c: getattr(r, c) for c in cols},
                        "price_source": "web" if r.starting_price else ("pdf-ocr (tham khảo)" if (r.raw or {}).get("ocr_prices") else None)}
                       for r in rows], columns=[*cols, "price_source"])
    clf = RuleClassifier()
    df["asset_type_label"] = df["asset_type"].map(lambda c: clf.label_of("asset_type", c))
    df["origin_label"] = df["origin"].map(lambda c: clf.label_of("origin", c))
    df["month"] = pd.to_datetime(df["publish_date"].fillna(df["first_seen"])).dt.to_period("M").astype(str)
    return df


def dedup(df: pd.DataFrame) -> pd.DataFrame:
    """Bỏ bản trùng giữa các nguồn (giữ 1 bản mỗi dup_group) - dùng cho thống kê tổng hợp."""
    if df.empty or "dup_group" not in df:
        return df
    has = df["dup_group"].notna()
    return pd.concat([df[~has], df[has].drop_duplicates("dup_group")])


def _agg(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[*by, "so_tin", "tong_gia_khoi_diem", "gia_khoi_diem_tb"])
    g = df.groupby(by, dropna=False).agg(
        so_tin=("source_id", "count"),
        tong_gia_khoi_diem=("starting_price", "sum"),
        gia_khoi_diem_tb=("starting_price", "mean"),
    ).reset_index().sort_values("so_tin", ascending=False)
    g["gia_khoi_diem_tb"] = g["gia_khoi_diem_tb"].round(0)
    return g


def summary(df_all: pd.DataFrame) -> dict[str, pd.DataFrame]:
    df = dedup(df_all)
    return {
        "Theo nguồn": _agg(df_all, ["source"]),
        "Loại TS chính thức": _agg(df_all[df_all["official_type"].notna()], ["official_type"]) if not df_all.empty else pd.DataFrame(),
        "Theo loại tài sản": _agg(df, ["asset_type_label"]),
        "Theo nguồn gốc": _agg(df, ["origin_label"]),
        "Theo tỉnh": _agg(df, ["province"]),
        "Tỉnh x Loại": (df.pivot_table(index="province", columns="asset_type_label", values="source_id",
                                      aggfunc="count", fill_value=0, margins=True, margins_name="Tổng")
                        .reset_index() if not df.empty else pd.DataFrame()),
        "Theo tháng": _agg(df, ["month"]).sort_values("month"),
        "Tháng x Loại": (df.pivot_table(index="month", columns="asset_type_label", values="source_id",
                                       aggfunc="count", fill_value=0).reset_index()
                         if not df.empty else pd.DataFrame()),
        "Top tổ chức ĐG": _agg(df, ["auction_org"]).head(50),
        "Top người có TS": _agg(df, ["asset_owner"]).head(50),
    }


def export_excel(df: pd.DataFrame, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    detail = df[[c for c in COLUMNS_VI if c in df.columns]].rename(columns=COLUMNS_VI)
    for c in detail.select_dtypes(include=["datetimetz"]).columns:
        detail[c] = detail[c].dt.tz_localize(None)
    with pd.ExcelWriter(out, engine="openpyxl") as xw:
        for name, t in summary(df).items():
            t.to_excel(xw, sheet_name=name[:31], index=False)
        detail.to_excel(xw, sheet_name="Chi tiết", index=False)
        for ws in xw.book.worksheets:  # độ rộng cột cơ bản
            for col in ws.columns:
                width = min(60, max(10, *(len(str(c.value or "")) for c in col[:200])))
                ws.column_dimensions[col[0].column_letter].width = width + 2
            ws.freeze_panes = "A2"
    return out


def export_csv(df: pd.DataFrame, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    df[[c for c in COLUMNS_VI if c in df.columns]].rename(columns=COLUMNS_VI).to_csv(
        out, index=False, encoding="utf-8-sig")  # utf-8-sig để Excel mở đúng tiếng Việt
    return out
