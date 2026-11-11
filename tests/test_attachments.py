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
    st = fetch_docs(s, repo, minutes=5, workers=1)
    # tài sản còn hạn trước; sau đó tài sản năm 2026 đã hết hạn còn thiếu thông tin
    assert st.notices == 2 and st.files == 4 and st.with_info == 2
    assert calls[0].endswith("auctionInfoId=11") and any("auctionInfoId=12" in c for c in calls)
    with repo.session() as ss:
        files = ss.query(NoticeFile).all()
        exists = {f.notice_id: [] for f in files}
        for f in files:
            exists[f.notice_id].append((s.path(s.data_dir) / f.path).exists() or f.removed_at is not None)
        assert all(all(v) for v in exists.values())
        n11 = ss.query(NoticeRow).filter_by(source_id="11").one().id
        n12 = ss.query(NoticeRow).filter_by(source_id="12").one().id
        open_files = [f for f in files if f.notice_id == n11]
        assert all((s.path(s.data_dir) / f.path).exists() for f in open_files)      # còn hạn: LƯU file gốc
        old_doc = [f for f in files if f.notice_id == n12 and f.filename.endswith(".docx")][0]
        assert old_doc.removed_at and not (s.path(s.data_dir) / old_doc.path).exists()   # hết hạn: chỉ giữ chữ
        assert (s.path(s.data_dir) / (old_doc.path + ".txt")).exists()
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
    # phiên mới của tài sản -> tải file của TIN GẦN NHẤT; phiên cũ đã có file thì thôi
    fut = datetime.now() + timedelta(days=15)
    repo.upsert(AuctionNotice(source="dgts", source_id="13", title=PORTAL.replace("156", "157") + " lô 12",
                              asset_name=PORTAL.replace("156", "157"), asset_owner="Chi cục THADS TP.HCM",
                              starting_price=13_000_000_000, auction_date=fut + timedelta(days=3),
                              registration_end=fut, publish_date=datetime.now().date(),
                              asset_type="quyen_su_dung_dat", origin="thi_hanh_an", property_count=1,
                              detail_fetched=True))
    rebuild(repo)
    st = fetch_docs(s, repo, minutes=5)
    assert st.notices == 1 and any("auctionInfoId=13" in c for c in calls)
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
        assert st.errors == 2
    assert fetch_docs(s, repo, minutes=5).errors == 0      # đã tạm bỏ qua sau 3 lần lỗi


def test_due_order_prefers_time_left_and_missing_data(tmp_path):
    from auction_crawler.attachments import due_notices
    repo = Repository(f"sqlite:///{tmp_path}/o.db")
    repo.init_db()
    now = datetime.now()
    cases = [("1", 1, False), ("2", 5, True), ("3", 6, False), ("4", -1, False)]   # (mã, còn ngày, đã đủ số liệu)
    for sid, days, full in cases:
        t = f"Quyền sử dụng đất thửa đất số {sid}0, tờ bản đồ số 9, tọa lạc tại phường Long Phước, TP. Hồ Chí Minh"
        if full:
            t += "; diện tích: 100m2"
        repo.upsert(AuctionNotice(source="dgts", source_id=sid, title=t, asset_name=t, starting_price=1_000_000_000,
                                  registration_end=now + timedelta(days=days), auction_date=now + timedelta(days=days + 2),
                                  asset_type="quyen_su_dung_dat", origin="thi_hanh_an", property_count=1))
    rebuild(repo)
    with repo.Session.begin() as s:          # tin cũ (không phải tin mới về trong 36 giờ)
        for n in s.query(NoticeRow):
            n.first_seen = now - timedelta(days=5)
    with repo.session() as s:
        order = [s.get(NoticeRow, i).source_id for i in due_notices(s, 10)]
    # còn ≥2 ngày & thiếu → còn ≥2 ngày đủ → sắp hết hạn → đã hết hạn năm 2026 còn thiếu
    assert order == ["3", "2", "1", "4"]
    with repo.Session.begin() as s:          # tin 1 mới về -> lấy trước
        s.query(NoticeRow).filter_by(source_id="1").one().first_seen = now
    with repo.session() as s:
        assert [s.get(NoticeRow, i).source_id for i in due_notices(s, 10)][0] == "1"


def test_ocr_stops_after_asset_section(monkeypatch, tmp_path):
    import auction_crawler.attachments as att
    pages = ["Căn cứ Luật đấu giá...", "1. Tên tài sản: thửa đất số 5, diện tích: 90m2", "2. Giá khởi điểm: 1 tỷ",
             "Quy chế trang 4", "Quy chế trang 5"]
    calls = []

    class R:
        returncode = 0

    def fake_run(cmd, **kw):
        i = int(cmd[cmd.index("-f") + 1])
        (pathlib.Path(cmd[-1] + "-1.png")).write_bytes(b"x")
        calls.append(i)
        return R()
    import pathlib
    monkeypatch.setattr(att.subprocess, "run", fake_run)
    monkeypatch.setattr(att, "_ocr_image", lambda img: pages[int(img.name[1:].split("-")[0]) - 1])
    text = att._ocr_pdf(tmp_path / "x.pdf", 8, 5)
    assert calls == [1, 2, 3] and "Giá khởi điểm" in text and "trang 4" not in text
    assert att.section_complete(text) and not att.section_complete("1. Tên tài sản: thửa đất")


@pytest.mark.skipif(not __import__("shutil").which("gs"), reason="cần ghostscript")
def test_compress_scanned_pdf(tmp_path):
    import random

    from PIL import Image

    from auction_crawler.attachments import compress_pdf
    im = Image.new("L", (2480, 3508), 245)
    px = im.load()
    for _ in range(300000):
        px[random.randrange(2480), random.randrange(3508)] = random.randint(0, 255)
    f = tmp_path / "scan.pdf"
    im.save(f, resolution=300, quality=95)
    before = f.stat().st_size
    assert before > 1_500_000
    after = compress_pdf(f)
    assert after and after < before * 0.8 and f.stat().st_size == after
    small = tmp_path / "small.pdf"
    small.write_bytes(b"%PDF-1.4 tiny")
    assert compress_pdf(small) is None


def test_too_big_file_keeps_link_only(env, monkeypatch):
    s, repo = env
    from auction_crawler import pipeline
    orig = pipeline.make_fetcher

    def handler(req):
        if "viewDetailAuctionInfo" in req.url.path:
            return httpx.Response(200, json={"listFile": [{"fileName": "to.pdf", "linkFile": "/u/to.pdf"}]})
        return httpx.Response(200, content=b"%PDF" + b"0" * 3000)
    monkeypatch.setattr(pipeline, "make_fetcher", lambda st, src, transport=None: orig(st, src, httpx.MockTransport(handler)))
    fetch_docs(s, repo, minutes=5, max_file_mb=0.001)
    with repo.session() as ss:
        f = ss.query(NoticeFile).first()
        assert f.path is None and f.method == "too_big" and "chỉ lưu đường link" in f.error
