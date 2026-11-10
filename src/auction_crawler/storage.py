"""Lưu trữ bằng SQLAlchemy (SQLite mặc định, chuyển PostgreSQL chỉ bằng đổi db_url)."""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import (JSON, BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, create_engine, inspect, select, text, update)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .models import AuctionNotice

log = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


class NoticeRow(Base):
    __tablename__ = "notices"
    __table_args__ = (UniqueConstraint("source", "source_id", name="uq_source_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[str] = mapped_column(String(255))
    url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    asset_name: Mapped[str | None] = mapped_column(Text)
    asset_owner: Mapped[str | None] = mapped_column(Text)
    owner_address: Mapped[str | None] = mapped_column(Text)
    auction_org: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    auction_place: Mapped[str | None] = mapped_column(Text)
    province: Mapped[str | None] = mapped_column(String(64), index=True)
    province_raw: Mapped[str | None] = mapped_column(String(64))
    starting_price: Mapped[int | None] = mapped_column(BigInteger)
    deposit: Mapped[int | None] = mapped_column(BigInteger)
    dossier_fee: Mapped[int | None] = mapped_column(BigInteger)
    property_count: Mapped[int | None] = mapped_column(Integer)
    publish_date: Mapped[date | None] = mapped_column(Date, index=True)
    auction_date: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    registration_start: Mapped[datetime | None] = mapped_column(DateTime)
    registration_end: Mapped[datetime | None] = mapped_column(DateTime)
    official_type: Mapped[str | None] = mapped_column(Text)
    asset_type: Mapped[str | None] = mapped_column(String(64), index=True)
    origin: Mapped[str | None] = mapped_column(String(64), index=True)
    classify_score: Mapped[float | None] = mapped_column(Float)
    content: Mapped[str | None] = mapped_column(Text)
    detail_fetched: Mapped[bool] = mapped_column(Boolean, default=False)
    dup_group: Mapped[int | None] = mapped_column(Integer, index=True)   # tin trùng giữa các nguồn
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    doc_info: Mapped[dict[str, Any] | None] = mapped_column(JSON)          # thông số trích từ file đính kèm
    docs_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)  # lúc đã tải + đọc file đính kèm
    content_hash: Mapped[str | None] = mapped_column(String(40))
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    last_seen: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_count: Mapped[int] = mapped_column(Integer, default=0)

    assets: Mapped[list["AssetRow"]] = relationship(back_populates="notice", cascade="all, delete-orphan")


class AssetRow(Base):
    __tablename__ = "notice_assets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    notice_id: Mapped[int] = mapped_column(ForeignKey("notices.id", ondelete="CASCADE"), index=True)
    name: Mapped[str | None] = mapped_column(Text)
    place: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[str | None] = mapped_column(Text)
    type_name: Mapped[str | None] = mapped_column(Text)
    starting_price: Mapped[int | None] = mapped_column(BigInteger)
    deposit: Mapped[int | None] = mapped_column(BigInteger)
    deposit_unit: Mapped[str | None] = mapped_column(String(8))
    file_cost: Mapped[int | None] = mapped_column(BigInteger)
    notice: Mapped[NoticeRow] = relationship(back_populates="assets")


class CrawlRun(Base):
    __tablename__ = "crawl_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    found: Mapped[int] = mapped_column(Integer, default=0)
    inserted: Mapped[int] = mapped_column(Integer, default=0)
    updated: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="running")
    message: Mapped[str | None] = mapped_column(Text)


FIELDS = [c for c in AuctionNotice.model_fields if c not in ("source", "source_id", "assets")]


class Repository:
    def __init__(self, db_url: str):
        kw = {"connect_args": {"check_same_thread": False, "timeout": 30}} if db_url.startswith("sqlite") else {}
        self.engine = create_engine(db_url, future=True, **kw)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def init_db(self) -> None:
        from . import attachments as _att  # noqa: F401  (bảng file đính kèm)
        from .realestate import db as _re_db  # noqa: F401  (đăng ký bảng nghiệp vụ BĐS)

        Base.metadata.create_all(self.engine)
        self._add_missing_columns()
        with self.engine.begin() as c:
            c.execute(text("UPDATE property_notices SET link_source = CASE WHEN manual THEN 'manual' ELSE 'auto' END "
                           "WHERE link_source IS NULL"))

    def _add_missing_columns(self) -> None:
        """Nâng cấp schema nhẹ: thêm cột mới vào bảng cũ (không cần Alembic cho thay đổi đơn giản)."""
        insp = inspect(self.engine)
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing:
                    ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {col.type.compile(self.engine.dialect)}'
                    log.info("schema: %s", ddl)
                    with self.engine.begin() as c:
                        c.execute(text(ddl))

    def existing_ids(self, source: str, ids: list[str], *, with_detail: bool = False) -> set[str]:
        if not ids:
            return set()
        with self.Session() as s:
            q = select(NoticeRow.source_id).where(NoticeRow.source == source, NoticeRow.source_id.in_(ids))
            if with_detail:
                q = q.where(NoticeRow.detail_fetched.is_(True))
            return set(s.scalars(q))

    def upsert(self, n: AuctionNotice) -> str:
        """Trả 'inserted' | 'updated' | 'unchanged'."""
        h = n.content_hash()
        now = datetime.now()
        data = n.model_dump(include=set(FIELDS))
        with self.Session.begin() as s:
            row = s.scalar(select(NoticeRow).where(NoticeRow.source == n.source, NoticeRow.source_id == n.source_id))
            if row is None:
                row = NoticeRow(source=n.source, source_id=n.source_id, content_hash=h,
                                first_seen=now, last_seen=now, **data)
                row.assets = [AssetRow(**a.model_dump()) for a in n.assets]
                s.add(row)
                return "inserted"
            row.last_seen = now
            if row.content_hash == h and (row.detail_fetched or not n.detail_fetched):
                return "unchanged"
            if row.detail_fetched and not n.detail_fetched:
                return "unchanged"  # chỉ có dữ liệu danh sách -> không ghi đè bản đã có chi tiết
            for k, v in data.items():
                if k == "raw":
                    row.raw = {**(row.raw or {}), **v}
                elif v is not None or k in ("asset_type", "origin", "classify_score"):
                    setattr(row, k, v)
            if n.assets:
                row.assets = [AssetRow(**a.model_dump()) for a in n.assets]
            row.content_hash = h
            row.docs_at = None   # tin thay đổi -> kiểm tra lại file đính kèm (file đã lưu không tải lại)
            row.updated_count = (row.updated_count or 0) + 1
            return "updated"

    def touch(self, source: str, source_id: str) -> None:
        with self.Session.begin() as s:
            s.execute(update(NoticeRow).where(NoticeRow.source == source, NoticeRow.source_id == source_id)
                      .values(last_seen=datetime.now()))

    def set_official_type(self, source: str, ids: list[str], type_name: str) -> int:
        with self.Session.begin() as s:
            r = s.execute(update(NoticeRow).where(NoticeRow.source == source, NoticeRow.source_id.in_(ids))
                          .values(official_type=type_name))
            return r.rowcount or 0

    def start_run(self, source: str) -> int:
        with self.Session.begin() as s:
            r = CrawlRun(source=source)
            s.add(r)
            s.flush()
            return r.id

    def finish_run(self, run_id: int, **kw: Any) -> None:
        with self.Session.begin() as s:
            r = s.get(CrawlRun, run_id)
            for k, v in kw.items():
                setattr(r, k, v)
            r.finished_at = datetime.now()

    def session(self) -> Session:
        return self.Session()
