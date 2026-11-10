"""File đính kèm: tải + lưu + đọc chữ, trích thông số thận trọng, ưu tiên tài liệu khi gom phiên."""
import io
import json
import zipfile
from datetime import datetime, timedelta

import httpx
import pytest

from auction_crawler.attachments import (NoticeFile, asset_section, fetch_docs, info_from_text, merge_file_infos,
                                         reparse)
from auction_crawler.config import Settings
from auction_crawler.models import AuctionNotice
from auction_crawler.realestate.db import Property
from auction_crawler.realestate.linker import rebuild
from auction_crawler.sources.base import ConfigSource
from auction_crawler.storage import NoticeRow, Repository

PORTAL = "Quyền sử dụng đất tại thửa đất số 156, tờ bản đồ số 25, phường Long Phước, TP. Hồ Chí Minh"
DOC = ("CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM\nTHÔNG BÁO ĐẤU GIÁ TÀI SẢN\nCăn cứ Luật Đấu giá tài sản năm 2016; "
       "Điều 5 quy định diện tích tối thiểu 30m2 khi tách thửa.\n"
       "1. Tên tài sản đấu giá: Quyền sử dụng đất tại thửa đất số 156, tờ bản đồ số 25, diện tích: 120,5m2 "
       "(đất ở tại đô thị), chiều ngang 5m; nhà ở diện tích sàn: 210m2.\n"
       "2. Giá khởi điểm: 14.580.000.000 đồng. 3. Tiền đặt trước: 2.900.000.000 đồng.")


def docx_bytes(text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        body = "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in text.split("\n"))
        z.writestr("word/document.xml", f'<w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def test_asset_section_skips_legal_basis():
    sec = asset_section(DOC)
    assert "ten tai san" in sec and "toi thieu 30m2" not in sec and "gia khoi diem" not in sec
    info = info_from_text(DOC)
    assert info["land_area"] == 120.5 and info["floor_area"] == 210 and info["width"] == 5
    assert info["map_sheet"] == "25" and info["parcel_no"] == "156"


def test_merge_conflicting_files_blank():
    m = merge_file_infos([({"land_area": 120.5}, "text"), ({"land_area": 118.0, "floor_area": 90}, "ocr")])
    assert "land_area" not in m and m["floor_area"] == 90 and m["methods"]["floor_area"] == "ocr"
    assert merge_file_infos([({"multi": True}, "text"), ({"land_area": 5}, "text")]).get("multi")


@pytest.fixture
def env(tmp_path, monkeypatch):
    s = Settings(db_url=f"sqlite:///{tmp_path}/a.db", raw_cache_dir=None, data_dir=str(tmp_path / "data"))
    orig = ConfigSource.http_overrides
    monkeypatch.setattr(ConfigSource, "http_overrides", lambda self: {**orig(self), "delay_seconds": 0})
    repo = Repository(s.db_url)
    repo.init_db()
    fut = datetime.now() + timedelta(days=20)
    for sid, reg in (("11", fut), ("12", datetime.now() - timedelta(days=30))):
        repo.upsert(AuctionNotice(source="dgts", source_id=sid, title=PORTAL + f" lô {sid}" * (sid == "12"),
                                  asset_name=PORTAL.replace("156", "157") if sid == "12" else PORTAL,
                                  asset_owner="Chi cục THADS TP.HCM", starting_price=14_580_000_000,
                                  auction_date=reg + timedelta(days=3), registration_end=reg,
                                  publish_date=datetime.now().date(), asset_type="quyen_su_dung_dat",
                                  origin="thi_hanh_an", property_count=1, detail_fetched=True))
    rebuild(repo)
    return s, repo


def mock(calls):
    def handler(req: httpx.Request):
        calls.append(str(req.url))
        if "viewDetailAuctionInfo" in req.url.path:
            sid = req.url.params["auctionInfoId"]
            return httpx.Response(200, json={"listFile": [
                {"fileName": f"Thong bao {sid}.docx", "linkFile": f"/upload/{sid}/tb.docx"},
                {"fileName": "anh.zip", "linkFile": f"/upload/{sid}/anh.zip"}]})
        if "download" in req.url.path:
            if req.url.params["path"].endswith(".zip"):
                return httpx.Response(200, content=b"PK\x05\x06" + b"\0" * 18)
            sid = req.url.params["path"].split("/")[2]
            return httpx.Response(200, content=docx_bytes(DOC.replace("156", "157") if sid == "12" else DOC))
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_fetch_docs_saves_files_and_prefers_document(env, monkeypatch):
    s, repo = env
    calls: list[str] = []
    from auction_crawler import pipeline
    orig = pipeline.make_fetcher
    monkeypatch.setattr(pipeline, "make_fetcher", lambda st, src, transport=None: orig(st, src, mock(calls)))
    st = fetch_docs(s, repo, minutes=5)
    assert st.notices == 1 and st.files == 2 and st.with_info == 1
    # CHỈ tài sản còn hạn đăng ký; tài sản đã hết hạn (tin 12) không tải
    assert not any("auctionInfoId=12" in c or "/12/" in c for c in calls)
    with repo.session() as ss:
        files = ss.query(NoticeFile).all()
        assert all((s.path(s.data_dir) / f.path).exists() for f in files)        # LƯU lại mọi file
        tb = [f for f in files if f.filename.endswith(".docx")][0]
        assert (s.path(s.data_dir) / (tb.path + ".txt")).exists() and tb.method == "docx"
        assert {f.method for f in files if f.filename == "anh.zip"} == {"unsupported"}
    rebuild(repo)
    with repo.session() as ss:
        p = ss.query(Property).filter(Property.parcel_no == "156").one()
        assert p.land_area == 120.5 and p.floor_area == 210 and p.width == 5
        assert p.field_sources["land_area"] == "tài liệu"
    # chạy lại: không tải lại file đã lưu
    n = len(calls)
    assert fetch_docs(s, repo, minutes=5).notices == 0 and len(calls) == n
    # tài sản hết hạn có PHIÊN MỚI -> còn hạn trở lại -> tải bổ sung mọi phiên của nó
    fut = datetime.now() + timedelta(days=15)
    repo.upsert(AuctionNotice(source="dgts", source_id="13", title=PORTAL.replace("156", "157") + " lô 12",
                              asset_name=PORTAL.replace("156", "157"), asset_owner="Chi cục THADS TP.HCM",
                              starting_price=13_000_000_000, auction_date=fut + timedelta(days=3),
                              registration_end=fut, publish_date=datetime.now().date(),
                              asset_type="quyen_su_dung_dat", origin="thi_hanh_an", property_count=1,
                              detail_fetched=True))
    rebuild(repo)
    st = fetch_docs(s, repo, minutes=5)
    assert st.notices == 2 and any("auctionInfoId=12" in c for c in calls)
    assert reparse(repo, s) == 3


def test_ocr_value_conflicting_with_portal_is_blanked(env):
    s, repo = env
    with repo.Session.begin() as ss:
        n = ss.query(NoticeRow).filter(NoticeRow.source_id == "11").one()
        n.asset_name = PORTAL + ", diện tích: 118m2"
        n.doc_info = {"land_area": 120.5, "floor_area": 210, "methods": {"land_area": "ocr", "floor_area": "ocr"}}
    rebuild(repo)
    with repo.session() as ss:
        p = ss.query(Property).filter(Property.parcel_no == "156").one()
        assert p.land_area is None and p.floor_area == 210
        assert p.field_sources == {"floor_area": "tài liệu (OCR)"}
        assert any("OCR" in x for x in p.auto_notes)
    with repo.Session.begin() as ss:
        ss.query(NoticeRow).filter(NoticeRow.source_id == "11").one().doc_info = {
            "land_area": 120.5, "methods": {"land_area": "text"}}
    rebuild(repo)
    with repo.session() as ss:
        p = ss.query(Property).filter(Property.parcel_no == "156").one()
        assert p.land_area == 120.5 and any("dùng số trong tài liệu" in x for x in p.auto_notes)


def test_listing_error_retried_then_skipped(env, monkeypatch):
    s, repo = env
    from auction_crawler import pipeline
    orig = pipeline.make_fetcher
    bad = httpx.MockTransport(lambda r: httpx.Response(404))
    monkeypatch.setattr(pipeline, "make_fetcher", lambda st, src, transport=None: orig(st, src, bad))
    for i in range(3):
        st = fetch_docs(s, repo, minutes=5)
        assert st.errors == 1                               # chỉ tài sản còn hạn
    assert fetch_docs(s, repo, minutes=5).errors == 0      # đã tạm bỏ qua sau 3 lần lỗi
