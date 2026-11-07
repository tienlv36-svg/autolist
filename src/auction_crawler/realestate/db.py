"""Bảng nghiệp vụ cho ứng dụng quản lý tài sản BĐS đấu giá."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..storage import Base, NoticeRow

PRIORITIES = {0: "Chưa xếp", 1: "Thấp", 2: "Trung bình", 3: "Cao", 4: "Rất cao"}
SALE_FORMS = {"ban": "Bán tài sản", "cho_thue": "Cho thuê", "khoan_no": "Bán khoản nợ"}
OWNER_TYPES = {
    "ngan_hang_bao_dam": "Ngân hàng / TCTD", "thi_hanh_an": "Thi hành án",
    "tai_san_cong": "Cơ quan quản lý nhà nước", "tich_thu": "Tịch thu / sở hữu toàn dân",
    "pha_san": "Phá sản", "doanh_nghiep_ca_nhan": "Doanh nghiệp / cá nhân",
    "ca_nhan_so_huu": "Doanh nghiệp / cá nhân", "khac": "Khác",
}
CATEGORIES = {"dat": "Đất", "nha_dat": "Nhà + đất", "mat_bang": "Mặt bằng / quyền khai thác"}
TASK_STATUS = {"moi": "Mới", "dang_lam": "Đang làm", "xong": "Hoàn thành", "huy": "Huỷ"}
# trường có thể sửa tay: tên -> nhãn
EDITABLE = {
    "land_area": "Tổng diện tích đất (m²)", "residential_area": "Diện tích đất ở (m²)",
    "other_land_area": "Diện tích đất khác (m²)", "floor_area": "Diện tích sàn (m²)",
    "width": "Chiều ngang (m)", "length": "Chiều dài (m)", "map_sheet": "Số tờ", "parcel_no": "Số thửa",
    "ward": "Xã/phường", "address": "Địa chỉ tài sản",
}


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    full_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(16), default="member")   # admin | member
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_login: Mapped[datetime | None] = mapped_column(DateTime)


class Property(Base):
    """Một bất động sản (có thể qua nhiều phiên đấu giá = nhiều thông báo)."""
    __tablename__ = "properties"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(16), index=True)
    sale_form: Mapped[str] = mapped_column(String(16), index=True, default="ban")
    owner_type: Mapped[str | None] = mapped_column(String(32), index=True)
    owner_name: Mapped[str | None] = mapped_column(Text)
    province: Mapped[str | None] = mapped_column(String(64), index=True)
    # giá trị tự động (bộ trích xuất) -- *_manual: nhập tay, ưu tiên khi hiển thị/lọc
    ward: Mapped[str | None] = mapped_column(String(128), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    land_area: Mapped[float | None] = mapped_column(Float)
    residential_area: Mapped[float | None] = mapped_column(Float)
    other_land_area: Mapped[float | None] = mapped_column(Float)
    floor_area: Mapped[float | None] = mapped_column(Float)
    width: Mapped[float | None] = mapped_column(Float)
    length: Mapped[float | None] = mapped_column(Float)
    map_sheet: Mapped[str | None] = mapped_column(String(64))
    parcel_no: Mapped[str | None] = mapped_column(String(64))
    parcels: Mapped[list[Any]] = mapped_column(JSON, default=list)
    ward_manual: Mapped[str | None] = mapped_column(String(128))
    address_manual: Mapped[str | None] = mapped_column(Text)
    land_area_manual: Mapped[float | None] = mapped_column(Float)
    residential_area_manual: Mapped[float | None] = mapped_column(Float)
    other_land_area_manual: Mapped[float | None] = mapped_column(Float)
    floor_area_manual: Mapped[float | None] = mapped_column(Float)
    width_manual: Mapped[float | None] = mapped_column(Float)
    length_manual: Mapped[float | None] = mapped_column(Float)
    map_sheet_manual: Mapped[str | None] = mapped_column(String(64))
    parcel_no_manual: Mapped[str | None] = mapped_column(String(64))
    # giá & phiên
    session_count: Mapped[int] = mapped_column(Integer, default=1)
    price_first: Mapped[int | None] = mapped_column(BigInteger)
    price_latest: Mapped[int | None] = mapped_column(BigInteger, index=True)
    deposit_latest: Mapped[int | None] = mapped_column(BigInteger)
    discount_pct: Mapped[float | None] = mapped_column(Float)
    auction_date: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    registration_end: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    publish_date: Mapped[date | None] = mapped_column(Date, index=True)
    latest_notice_id: Mapped[int | None] = mapped_column(Integer)
    link_warning: Mapped[str | None] = mapped_column(Text)
    # nghiệp vụ
    priority: Mapped[int] = mapped_column(Integer, default=0, index=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    links: Mapped[list["PropertyNotice"]] = relationship(back_populates="property", cascade="all, delete-orphan",
                                                         order_by="PropertyNotice.session_no")

    def eff(self, name: str) -> Any:
        """Giá trị hiệu lực: nhập tay nếu có, không thì tự động."""
        m = getattr(self, f"{name}_manual", None)
        return m if m not in (None, "") else getattr(self, name)


class PropertyNotice(Base):
    """Liên kết thông báo -> tài sản, kèm số thứ tự phiên."""
    __tablename__ = "property_notices"
    __table_args__ = (UniqueConstraint("notice_id", name="uq_notice_property"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("notices.id", ondelete="CASCADE"))
    session_no: Mapped[int] = mapped_column(Integer, default=1)
    manual: Mapped[bool] = mapped_column(Boolean, default=False)   # do người dùng gộp/tách -> linker giữ nguyên
    property: Mapped[Property] = relationship(back_populates="links")
    notice: Mapped[NoticeRow] = relationship()


class PropertyFile(Base):
    __tablename__ = "property_files"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    folder: Mapped[str] = mapped_column(String(64), default="Tài liệu")   # Hình ảnh | Video | Tài liệu | Pháp lý ...
    kind: Mapped[str] = mapped_column(String(16), default="document")     # image | video | document
    filename: Mapped[str] = mapped_column(Text)
    stored_path: Mapped[str | None] = mapped_column(Text)                 # file tải lên (tương đối data/media)
    source_url: Mapped[str | None] = mapped_column(Text)                  # tài liệu gốc từ website nguồn
    size: Mapped[int | None] = mapped_column(BigInteger)
    mime: Mapped[str | None] = mapped_column(String(128))
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class FileView(Base):
    __tablename__ = "file_views"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("property_files.id", ondelete="CASCADE"), index=True)
    property_id: Mapped[int] = mapped_column(Integer, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(16), default="view")    # view | download
    viewed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Comment(Base):
    __tablename__ = "comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    user: Mapped[User] = relationship()


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    assigner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    assignee_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    due_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), default="moi", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    assigner: Mapped[User] = relationship(foreign_keys=[assigner_id])
    assignee: Mapped[User] = relationship(foreign_keys=[assignee_id])
    property: Mapped[Property | None] = relationship()


class Activity(Base):
    """Nhật ký thao tác (sửa trường, đổi ưu tiên, xác thực, gộp/tách phiên...)."""
    __tablename__ = "activities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int | None] = mapped_column(Integer, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, server_default=func.now())
    user: Mapped[User | None] = relationship()
