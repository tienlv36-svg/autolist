"""Quét lịch sử giá: tìm phiên cũ bằng từ khoá đặc trưng, kiểm chứng chặt, chỉ tài sản còn hạn."""
from datetime import datetime, timedelta

import httpx
import pytest

from auction_crawler.config import Settings
from auction_crawler.models import AuctionNotice
from auction_crawler.realestate.db import Property, PropertyNotice
from auction_crawler.realestate.extract import extract
from auction_crawler.realestate.history import keywords, scan_open_properties, verify
from auction_crawler.realestate.linker import rebuild
from auction_crawler.sources.base import ConfigSource
from auction_crawler.storage import NoticeRow, Repository

TXT = ("Quyền sử dụng đất thuộc thửa đất số 118; Tờ bản đồ số 28; Diện tích: 575,1m2; Loại đất: Đất ở tại nông thôn. "
       "Theo giấy chứng nhận số BR 234700 do UBND huyện Tam Bình cấp, tọa lạc xã Song Phú, tỉnh Vĩnh Long")
OTHER_PARCEL = TXT.replace("thửa đất số 118", "thửa đất số 119")
OWNER = "Ngân hàng Nông nghiệp – Chi nhánh Vĩnh Long"
ms = lambda d: int(d.timestamp() * 1000)  # noqa: E731


@pytest.fixture
def env(tmp_path, monkeypatch):
    s = Settings(db_url=f"sqlite:///{tmp_path}/h.db", raw_cache_dir=None)
    orig = ConfigSource.http_overrides
    monkeypatch.setattr(ConfigSource, "http_overrides", lambda self: {**orig(self), "delay_seconds": 0})
    repo = Repository(s.db_url)
    repo.init_db()
    future = datetime.now() + timedelta(days=10)
    for sid, price, when in [("1001", 8_190_000_000, datetime(2026, 9, 18, 10)), ("1002", 7_371_000_000, datetime(2026, 10, 29, 10))]:
        repo.upsert(AuctionNotice(source="dgts", source_id=sid, title=TXT, asset_name=TXT, asset_owner=OWNER,
                                  starting_price=price, auction_date=when, registration_end=future if sid == "1002" else when,
                                  asset_type="quyen_su_dung_dat", origin="ngan_hang_bao_dam", property_count=1,
                                  detail_fetched=True))
    rebuild(repo)
    return s, repo


def row(sid, text, when):
    return {"id": int(sid), "propertyName": text, "publishTime1": ms(when - timedelta(days=20)), "aucTime": ms(when),
            "aucRegTimeEnd": ms(when - timedelta(days=3)), "fullname": OWNER, "org_name": "Công ty ĐGHD Mekong"}


def transport(calls):
    rows = [row("1002", TXT, datetime(2026, 10, 29, 10)), row("1001", TXT, datetime(2026, 9, 18, 10)),
            row("900", TXT, datetime(2026, 3, 10, 10)), row("800", TXT, datetime(2026, 2, 1, 10)),
            row("850", OTHER_PARCEL, datetime(2026, 2, 20, 10)),      # cùng GCN nhưng khác thửa -> loại
            row("700", "Xe ô tô Toyota biển số 29A-12345", datetime(2026, 1, 5, 10))]
    prices = {"900": 10_000_000_000, "800": 11_000_000_000, "850": 1, "700": 1}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/portal/search/auction-notice":
            calls.append(req.url.params.get("assetName"))
            return httpx.Response(200, json={"items": rows, "pageCount": 1, "rowCount": len(rows)})
        if req.url.path == "/portal/propertyInfo":
            sid = req.url.params["auctionInfoId"]
            return httpx.Response(200, json={"items": [{"propertyName": TXT, "propertyStartPrice": prices[sid],
                                                        "deposit": 1, "depositUnit": 0, "fileCost": 1}]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_keywords_prefer_gcn():
    assert keywords(TXT, extract(TXT))[0] == ("gcn", "BR 234700")


def test_verify_rules():
    a = extract(TXT)
    assert verify(TXT, a, None, TXT, a, None).startswith("cùng số giấy chứng nhận")
    assert verify(TXT, a, None, OTHER_PARCEL, extract(OTHER_PARCEL), None) is None      # khác thửa
    no_gcn = TXT.replace("số BR 234700 ", "")
    assert verify(no_gcn, extract(no_gcn), None, no_gcn, extract(no_gcn), None).startswith("cùng tờ 28 thửa 118")
    other_area = no_gcn.replace("575,1m2", "300m2").replace("xã Song Phú", "xã Khác")
    assert verify(no_gcn, extract(no_gcn), None, other_area, extract(other_area), None) is None  # chỉ trùng thửa: chưa đủ


def test_scan_adds_older_sessions(env):
    s, repo = env
    calls = []
    st = scan_open_properties(s, repo, limit=10, transport=transport(calls))
    assert calls == ["BR 234700"] and (st.scanned, st.found_notices) == (1, 2)
    rebuild(repo)
    with repo.session() as ss:
        p = ss.query(Property).one()
        assert p.session_count == 4 and p.price_first == 11_000_000_000 and p.price_latest == 7_371_000_000
        assert p.discount_pct == 33.0 and "tìm thêm 2" in p.history_note
        hist = ss.query(PropertyNotice).filter_by(link_source="history").count()
        assert hist == 2
        assert ss.query(NoticeRow).filter_by(source_id="850").count() == 0   # tin khác thửa không được lưu
    # quét lại: không quét nữa (đã quét, chưa có phiên mới)
    assert scan_open_properties(s, repo, limit=10, transport=transport([])).scanned == 0


def test_expired_not_scanned(env):
    s, repo = env
    with repo.Session.begin() as ss:
        ss.query(Property).one().registration_end = datetime.now() - timedelta(days=1)
    assert scan_open_properties(s, repo, limit=10, transport=transport([])).scanned == 0


def test_shared_certificate_needs_parcel_or_area():
    lot1 = "Tài sản: QSDĐ theo giấy chứng nhận số BT 272878, diện tích 120m2 tại xã A, tỉnh Vĩnh Long"
    lot2 = "Tài sản: QSDĐ theo giấy chứng nhận số BT 272878, diện tích 45m2 tại xã A, tỉnh Vĩnh Long"
    assert verify(lot1, extract(lot1), None, lot2, extract(lot2), None) is None        # cùng GCN, khác diện tích
    assert verify(lot1, extract(lot1), None, lot1, extract(lot1), None).endswith("cùng diện tích")
    multi = "Tài sản 01: Quyền sử dụng đất số BT 272878, thửa 5 tờ 2. Tài sản 02: nhà ở"
    assert verify(multi, extract(multi), None, multi, extract(multi), None) is None    # nhiều lô


def test_does_not_steal_notice_of_other_property(env):
    s, repo = env
    # thông báo "900" đã có trong CSDL và thuộc một tài sản khác
    repo.upsert(AuctionNotice(source="dgts", source_id="900", title="Xe ô tô", asset_type="phuong_tien"))
    with repo.Session.begin() as ss:
        q = Property(title="tài sản khác")
        ss.add(q)
        ss.flush()
        ss.add(PropertyNotice(property_id=q.id, notice_id=ss.query(NoticeRow).filter_by(source_id="900").one().id))
    st = scan_open_properties(s, repo, limit=10, transport=transport([]))
    assert st.found_notices == 1        # chỉ lấy "800", bỏ qua "900"
    with repo.session() as ss:
        assert "bỏ qua 1" in ss.query(Property).filter(Property.history_note.is_not(None)).one().history_note
