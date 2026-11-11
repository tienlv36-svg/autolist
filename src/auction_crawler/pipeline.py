"""Pipeline: danh sách -> chi tiết (song song) -> chuẩn hoá -> phân loại -> lưu DB."""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

import httpx
from sqlalchemy import select

from .classifier import RuleClassifier
from .config import Settings
from .http_client import BrowserFetcher, Fetcher
from .models import AssetItem, AuctionNotice
from .normalize import clean_text, detect_province, parse_date, parse_datetime, parse_vnd
from .sources import get_source
from .sources.base import ConfigSource
from .storage import NoticeRow, Repository

log = logging.getLogger(__name__)

MONEY = ("starting_price", "deposit", "dossier_fee")
DATETIMES = ("auction_date", "registration_start", "registration_end")
TEXT = ("asset_name", "asset_owner", "owner_address", "auction_org", "address", "auction_place",
        "content", "official_type")


@dataclass
class RunStats:
    pages: int = 0
    found: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    errors: int = 0
    error_samples: list[str] = field(default_factory=list)

    def error(self, msg: str) -> None:
        self.errors += 1
        if len(self.error_samples) < 10:
            self.error_samples.append(msg)


def build_notice(source: str, item: dict, classifier: RuleClassifier) -> AuctionNotice:
    """Ghép dữ liệu thô (list + detail) thành AuctionNotice đã chuẩn hoá & phân loại."""
    raw = {k: v for k, v in item.items() if not k.startswith("_") and k not in ("assets",)
           and k not in TEXT and k not in MONEY and k not in DATETIMES and k not in ("title", "url", "source_id")}
    if "_list_json" in item:
        raw["list_json"] = item["_list_json"]
    raw = json.loads(json.dumps(raw, default=str, ensure_ascii=False))  # đảm bảo lưu được dạng JSON

    def txt(k: str) -> str | None:
        v = item.get(k)
        return clean_text(v) if isinstance(v, str) else None

    pc = item.get("property_count")
    n = AuctionNotice(
        source=source,
        source_id=str(item["source_id"]),
        url=item.get("url"),
        title=txt("title") or txt("asset_name") or "",
        publish_date=parse_date(item.get("publish_date")),
        property_count=int(pc) if pc else None,
        detail_fetched=bool(item.get("_detail")),
        assets=[AssetItem(**a) for a in item.get("assets") or []],
        raw=raw,
        **{k: txt(k) for k in TEXT},
        **{k: parse_vnd(item.get(k)) for k in MONEY},
        **{k: parse_datetime(item.get(k)) for k in DATETIMES},
    )
    # tỉnh nơi có TÀI SẢN: chỉ từ địa chỉ/mô tả tài sản (không đoán từ tên chủ tài sản hay nơi đấu giá)
    from .realestate.extract import detect_province_strict
    n.province, n.province_raw = detect_province_strict(n.address, n.asset_name, n.title)
    labels = classifier.classify(n.classify_fields())
    if "asset_type" in labels:
        n.asset_type, n.classify_score = labels["asset_type"].code, labels["asset_type"].score
    if "origin" in labels:
        n.origin = labels["origin"].code
    return n


def make_fetcher(settings: Settings, src: ConfigSource, transport: httpx.BaseTransport | None = None) -> Fetcher:
    if src.cfg.get("fetcher") == "browser":
        return BrowserFetcher(settings, src.name, wait_selector=src.cfg["list"].get("item"),
                              http_overrides={**src.http_overrides(), "concurrency": 1})
    return Fetcher(settings, src.name, transport=transport, http_overrides=src.http_overrides())


def _enrich_many(src: ConfigSource, fetcher: Fetcher, items: list[dict], stats: RunStats,
                 on_done: Callable[[dict], None]) -> None:
    """Tải chi tiết song song (giới hạn tốc độ nằm trong Fetcher); ghi DB ở luồng chính."""
    def work(it: dict) -> tuple[dict, Exception | None]:
        try:
            return src.enrich(fetcher, it), None
        except Exception as e:  # noqa: BLE001
            return it, e

    workers = max(1, fetcher.http.concurrency)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for it, err in pool.map(work, items):
            if err:
                stats.error(f"{it.get('url')}: {err!r}")
                log.warning("[%s] lỗi chi tiết %s: %r (vẫn lưu dữ liệu danh sách)", src.name, it.get("url"), err)
            on_done(it)


def crawl_source(name: str, settings: Settings, repo: Repository, *, max_pages: int | None = None,
                 fetch_detail: bool | None = None, full: bool = False, since: date | None = None,
                 transport: httpx.BaseTransport | None = None) -> RunStats:
    src = get_source(name)
    max_pages = max_pages or settings.crawl.max_pages
    fetch_detail = settings.crawl.fetch_detail if fetch_detail is None else fetch_detail
    classifier = RuleClassifier()
    stats = RunStats()
    run_id = repo.start_run(name)
    fetcher = make_fetcher(settings, src, transport)
    status, message = "ok", None

    def save(it: dict) -> None:
        try:
            res = repo.upsert(build_notice(name, it, classifier))
            setattr(stats, res, getattr(stats, res) + 1)
        except Exception as e:  # noqa: BLE001
            stats.error(f"{it.get('url')}: {e!r}")
            log.warning("[%s] lỗi lưu %s: %r", name, it.get("url"), e)

    try:
        for page, items in src.iter_pages(fetcher, max_pages, since=since):
            stats.pages += 1
            stats.found += len(items)
            ids = [it["source_id"] for it in items]
            known = repo.existing_ids(name, ids)
            known_detail = repo.existing_ids(name, ids, with_detail=True) if fetch_detail else known
            log.info("[%s] trang %s: %s tin (%s đã có)", name, page, len(items), len(known))
            todo_detail, plain = [], []
            # chạy tăng dần (không --since): tin ĐÃ CÓ trong CSDL là tin cũ -> không tải chi tiết lại ở đây
            # (tin cũ chưa có chi tiết do lấy lần đầu bằng --no-detail: bước enrich bổ sung cho tin BĐS)
            skip = known if (not full and not since) else known_detail
            for it in items:
                if since and it.get("_date") and it["_date"] < since:
                    continue
                if not full and it["source_id"] in skip:
                    repo.touch(name, it["source_id"])
                    stats.unchanged += 1
                elif fetch_detail and src.has_detail():
                    todo_detail.append(it)
                else:
                    plain.append(it)
            for it in plain:
                save(it)
            if todo_detail:
                _enrich_many(src, fetcher, todo_detail, stats, save)
            dated = [it["_date"] for it in items if it.get("_date")]
            if since and dated and max(dated) < since:
                log.info("[%s] trang %s cũ hơn %s -> dừng", name, page, since)
                break
            if (settings.crawl.stop_when_page_all_seen and not full and not since
                    and known and len(known) == len(items)):
                log.info("[%s] trang %s toàn tin đã có -> dừng (chạy tăng dần)", name, page)
                break
    except Exception as e:  # noqa: BLE001
        status, message = "failed", repr(e)
        log.exception("[%s] crawl thất bại", name)
    finally:
        fetcher.close()
        repo.finish_run(run_id, pages=stats.pages, found=stats.found, inserted=stats.inserted,
                        updated=stats.updated, errors=stats.errors, status=status,
                        message=message or "\n".join(stats.error_samples) or None)
    if status == "failed":
        raise RuntimeError(message)
    return stats


def enrich_missing(name: str, settings: Settings, repo: Repository, *, limit: int = 1000,
                   since: date | None = None, realestate: bool = False) -> RunStats:
    """Tải chi tiết cho các tin đã có trong DB nhưng chưa có chi tiết (sau khi backfill --no-detail).
    realestate=True: chỉ tin thuộc tài sản BĐS (cần chạy `re-build` trước), ưu tiên tài sản nhiều phiên."""
    src = get_source(name)
    q = select(NoticeRow).where(NoticeRow.source == name, NoticeRow.detail_fetched.is_not(True))
    if since:
        q = q.where(NoticeRow.publish_date >= since)
    if realestate:
        from .realestate.db import Property, PropertyNotice
        q = (q.join(PropertyNotice, PropertyNotice.notice_id == NoticeRow.id)
             .join(Property, Property.id == PropertyNotice.property_id)
             .order_by(Property.session_count.desc(), NoticeRow.publish_date.desc()).limit(limit))
    else:
        q = q.order_by(NoticeRow.publish_date.desc()).limit(limit)
    with repo.session() as s:
        rows = s.scalars(q).all()
    items = []
    for r in rows:
        it: dict[str, Any] = {k: getattr(r, k) for k in ("source_id", "url", "title", *TEXT, *MONEY, *DATETIMES)}
        it["publish_date"] = r.publish_date
        items.append(it)
    stats = RunStats(found=len(items))
    clf = RuleClassifier()
    fetcher = make_fetcher(settings, src)

    def save(it: dict) -> None:
        res = repo.upsert(build_notice(name, it, clf))
        setattr(stats, res, getattr(stats, res) + 1)

    try:
        _enrich_many(src, fetcher, items, stats, save)
    finally:
        fetcher.close()
    return stats


def tag_official_types(settings: Settings, repo: Repository, since: date | None = None) -> dict[str, int]:
    """dgts: API danh sách không trả loại tài sản, nhưng lọc được theo propertyTypeId.
    Duyệt từng loại (16 loại theo Luật ĐGTS) để gắn official_type cho tin đã có trong DB."""
    src = get_source("dgts")
    fetcher = make_fetcher(settings, src)
    out: dict[str, int] = {}
    try:
        for t in src.property_types(fetcher):  # type: ignore[attr-defined]
            n = 0
            for ids in src.iter_ids_by_type(fetcher, t["id"], since=since):  # type: ignore[attr-defined]
                n += repo.set_official_type("dgts", ids, t["name"])
            out[t["name"]] = n
            log.info("[dgts] %s: gắn %s tin", t["name"][:60], n)
    finally:
        fetcher.close()
    return out


def row_fields(row: NoticeRow) -> dict[str, str | None]:
    name = row.asset_name if row.asset_name and row.asset_name != row.title else None
    return {"title": row.title, "asset_name": name, "official_type": row.official_type,
            "asset_types": " | ".join(dict.fromkeys(a.type_name for a in row.assets if a.type_name)) or None,
            "asset_owner": row.asset_owner, "content": row.content}


def reclassify_all(repo: Repository) -> int:
    """Chạy lại phân loại + nhận diện tỉnh cho toàn bộ DB (sau khi sửa categories.yaml)."""
    clf = RuleClassifier()
    n = 0
    with repo.Session.begin() as s:
        for row in s.scalars(select(NoticeRow)).yield_per(2000):
            labels = clf.classify(row_fields(row))
            row.asset_type, row.classify_score = labels["asset_type"].code, labels["asset_type"].score
            row.origin = labels["origin"].code
            from .realestate.extract import detect_province_strict
            row.province, row.province_raw = detect_province_strict(row.address, row.asset_name, row.title)
            n += 1
    return n


def ocr_prices(name: str, settings: Settings, repo: Repository, *, limit: int = 50,
               since: date | None = None, keep_pdf: bool = False) -> RunStats:
    """Đọc giá từ PDF đính kèm cho tin chưa có giá (taisancong). Chậm (~5-10 giây/tin) -> chạy nền."""
    import tempfile
    from pathlib import Path

    from .ocr import extract_prices, pdf_text

    src = get_source(name)
    q = select(NoticeRow).where(NoticeRow.source == name, NoticeRow.starting_price.is_(None),  # noqa: E501
                                NoticeRow.detail_fetched.is_(True))
    if since:
        q = q.where(NoticeRow.publish_date >= since)
    with repo.session() as s:
        rows = [r for r in s.scalars(q.order_by(NoticeRow.publish_date.desc()).limit(limit * 3))
                if (r.raw or {}).get("attachments") and not (r.raw or {}).get("ocr_tried")][:limit]
    stats = RunStats(found=len(rows))
    fetcher = make_fetcher(settings, src)
    pdf_dir = settings.path(settings.raw_cache_dir or "data/raw") / name / "pdf"
    try:
        for r in rows:
            got: dict[str, int] = {}
            method = "none"
            for url in [u for u in r.raw["attachments"] if u.lower().endswith(".pdf")][:2]:
                try:
                    resp = fetcher.request("GET", url)
                    resp.raise_for_status()
                    if keep_pdf:
                        pdf_dir.mkdir(parents=True, exist_ok=True)
                        path = pdf_dir / url.rsplit("/", 1)[-1]
                        path.write_bytes(resp.content)
                        text, method = pdf_text(path)
                    else:
                        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
                            f.write(resp.content)
                            f.flush()
                            text, method = pdf_text(Path(f.name))
                    got = extract_prices(text)
                    if got.get("starting_price"):
                        break
                except Exception as e:  # noqa: BLE001
                    stats.error(f"{url}: {e!r}")
            with repo.Session.begin() as s:
                row = s.get(NoticeRow, r.id)
                # chỉ lưu làm THAM KHẢO (OCR có thể đọc sai số) - không ghi vào cột giá chính thức
                row.raw = {**(row.raw or {}), "ocr_tried": True,
                           "ocr_prices": {**got, "method": method} if got else None}
            if got:
                stats.updated += 1
            log.info("[%s] %s: %s (%s)", name, r.source_id, got or "không tìm thấy giá", method)
    finally:
        fetcher.close()
    return stats
