"""Test với dữ liệu THẬT đã lưu từ 2 nguồn (07/11/2026) qua HTTP giả lập - không cần mạng."""
import json
from datetime import datetime
from pathlib import Path

import httpx
import pytest

from auction_crawler.config import Settings
from auction_crawler.pipeline import crawl_source
from auction_crawler.sources import get_source
from auction_crawler.storage import AssetRow, NoticeRow, Repository

FX = Path(__file__).parent / "fixtures"
read = lambda n: (FX / n).read_text(encoding="utf-8")  # noqa: E731


def dgts_transport():
    search = json.loads(read("dgts_search.json"))
    props = json.loads(read("dgts_property.json"))

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/portal/search/auction-notice":
            page = int(req.url.params["p"])
            data = {**search, "pageCount": 1} if page == 1 else {**search, "items": []}
            return httpx.Response(200, json=data)
        if req.url.path == "/portal/propertyInfo":
            return httpx.Response(200, json=props[req.url.params["auctionInfoId"]])
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def tsc_transport():
    def handler(req: httpx.Request) -> httpx.Response:
        if "BRSR=" in str(req.url):          # trang 2 trở đi -> rỗng để dừng
            return httpx.Response(200, html="<html></html>")
        if "thong-tin-ban-dau-gia" in req.url.path:
            return httpx.Response(200, html=read("taisancong_list.html"))
        return httpx.Response(200, html=read("taisancong_detail.html"))
    return httpx.MockTransport(handler)


@pytest.fixture
def env(tmp_path):
    s = Settings(db_url=f"sqlite:///{tmp_path}/t.db", raw_cache_dir=None)
    s.http.delay_seconds = 0
    repo = Repository(s.db_url)
    repo.init_db()
    return s, repo


def _no_delay(monkeypatch):
    from auction_crawler.sources.base import ConfigSource
    orig = ConfigSource.http_overrides
    monkeypatch.setattr(ConfigSource, "http_overrides", lambda self: {**orig(self), "delay_seconds": 0})


def test_dgts_end_to_end(env, monkeypatch):
    _no_delay(monkeypatch)
    s, repo = env
    st = crawl_source("dgts", s, repo, max_pages=3, transport=dgts_transport())
    assert (st.inserted, st.errors) == (5, 0)
    with repo.session() as ss:
        r = ss.query(NoticeRow).filter_by(source_id="673244").one()
        assets = ss.query(AssetRow).filter_by(notice_id=r.id).all()
    assert r.starting_price == 590_632_515 and r.deposit == 60_000_000 and r.dossier_fee == 200_000
    assert r.auction_date == datetime(2026, 12, 11, 11, 0)          # 11:00 11/12/2026 như trên web
    assert r.registration_end == datetime(2026, 12, 8, 17, 0)
    assert r.asset_owner.startswith("Thi hành án dân sự tỉnh Đồng Tháp")
    assert r.auction_org == "Công ty đấu giá hợp danh Tây Đô Đồng Tháp"
    assert r.province == "Đồng Tháp" and r.detail_fetched
    assert r.asset_type == "quyen_su_dung_dat" and r.origin == "thi_hanh_an"
    assert r.url.endswith("-673244.html") and len(assets) == 1
    st2 = crawl_source("dgts", s, repo, max_pages=3, transport=dgts_transport())
    assert st2.inserted == 0 and st2.unchanged == 5


def test_dgts_detail_html():
    src = get_source("dgts")
    d = src.parse_detail_html(read("dgts_detail_page.html"))
    assert d["owner_address"].startswith("Số 07, đường Lê Văn Chánh")
    assert d["auction_place"].startswith("Công ty đấu giá hợp danh Tây Đô Đồng Tháp")


def test_taisancong_list():
    src = get_source("taisancong")
    items = src.parse_list(read("taisancong_list.html"), src.cfg["list"]["url"])
    assert len(items) == 20
    it = items[0]
    assert it["source_id"] == "57042"
    assert it["title"].startswith("Đấu giá quyền khai thác Bến đò Kênh Tháp Mười")
    assert it["asset_owner"] == "Trung tâm Cung ứng dịch vụ công xã Mỹ Thành"
    assert it["auction_org"] == "Công ty Đấu giá Hợp danh Gò Công"
    assert it["registration_start"].startswith("06-11-2026 14:00")
    assert it["registration_end"].startswith("23-11-2026 17:00")
    assert src.page_url(3)[0].endswith("thong-tin-ban-dau-gia&BRSR=40")


def test_taisancong_end_to_end(env, monkeypatch):
    _no_delay(monkeypatch)
    s, repo = env
    st = crawl_source("taisancong", s, repo, max_pages=3, transport=tsc_transport())
    assert st.inserted == 20 and st.errors == 0
    with repo.session() as ss:
        r = ss.query(NoticeRow).filter_by(source_id="57042").one()
    assert r.auction_date == datetime(2026, 11, 26, 9, 0)
    assert r.registration_end == datetime(2026, 11, 23, 17, 0)
    assert r.publish_date.isoformat() == "2026-11-06"
    assert r.owner_address == "Ấp 6, Xã Mỹ Thành, Tỉnh Đồng Tháp"
    assert r.province == "Đồng Tháp"
    assert r.raw["attachments"][0].endswith(".pdf")


def test_label_not_matched_inside_longer_phrase():
    from auction_crawler.sources.extract import extract_by_labels, soupify
    soup = soupify("<p>Thời gian tổ chức đấu giá: 09 giờ ngày 25/11/2026</p>"
                   "<ul><li>1. Tổ chức đấu giá: Công ty ĐGHD Sao Việt</li></ul>")
    d = extract_by_labels(soup, {"auction_org": ["Tổ chức đấu giá"], "auction_date": ["Thời gian tổ chức"]})
    assert d["auction_org"] == "Công ty ĐGHD Sao Việt"
    assert d["auction_date"] == "09 giờ ngày 25/11/2026"
