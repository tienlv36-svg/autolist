from datetime import datetime

import pytest

from auction_crawler.config import Settings
from auction_crawler.models import AuctionNotice
from auction_crawler.realestate.db import Comment, Property, PropertyNotice, User
from auction_crawler.realestate.linker import is_real_estate, rebuild
from auction_crawler.storage import Repository

LAND = ("Quyền sử dụng đất thửa đất số 2748, tờ bản đồ số 08 diện tích 80,3m2 đất ở tại đô thị, tọa lạc tại "
        "ấp 1, xã Mỹ Tân, thành phố Cao Lãnh, tỉnh Đồng Tháp (nay là phường Mỹ Ngãi, tỉnh Đồng Tháp)")


@pytest.fixture
def repo(tmp_path):
    r = Repository(Settings(db_url=f"sqlite:///{tmp_path}/l.db").db_url)
    r.init_db()
    return r


def add(repo, sid, title, price, when, owner="Phòng Thi hành án dân sự khu vực 6 - Đồng Tháp", src="dgts"):
    repo.upsert(AuctionNotice(source=src, source_id=sid, title=title, asset_name=title, asset_owner=owner,
                              province="Đồng Tháp", starting_price=price, auction_date=when,
                              asset_type="quyen_su_dung_dat", origin="thi_hanh_an"))


def test_is_real_estate():
    assert is_real_estate("quyen_su_dung_dat", "Quyền sử dụng đất", None) == "dat"
    assert is_real_estate("quyen_su_dung_dat", "Nhà, đất tại thửa 12", None) == "nha_dat"
    assert is_real_estate("khoan_no", "Khoản nợ ... tài sản bảo đảm là quyền sử dụng đất", None) == "dat"
    assert is_real_estate("khoan_no", "Khoản nợ tín chấp", None) is None
    assert is_real_estate("phuong_tien", "Xe ô tô", None) is None
    assert is_real_estate("cho_thue_mat_bang", "Cho thuê mặt bằng căn tin", None) == "mat_bang"


def test_sessions_and_discount(repo):
    add(repo, "1", LAND, 1_000_000_000, datetime(2026, 9, 1, 9))
    add(repo, "2", LAND + " (Đấu giá lần 2)", 900_000_000, datetime(2026, 10, 1, 9))
    add(repo, "3", "Quyền sử dụng đất thửa đất số 99, tờ bản đồ số 3 diện tích 200m2 tại xã Tân Thuận Đông, tỉnh Đồng Tháp",
        500_000_000, datetime(2026, 10, 5, 9))
    st = rebuild(repo)
    assert st["properties"] == 2
    with repo.session() as s:
        p = s.query(Property).join(PropertyNotice).filter(PropertyNotice.notice_id == 1).one()
        assert (p.session_count, p.price_first, p.price_latest, p.discount_pct) == (2, 1_000_000_000, 900_000_000, 10.0)
        assert p.land_area == 80.3 and p.residential_area == 80.3
        assert (p.map_sheet, p.parcel_no) == ("08", "2748") and p.ward == "Phường Mỹ Ngãi"
        assert p.sale_form == "ban" and p.owner_type == "thi_hanh_an"
        pid = p.id
        u = User(username="a", full_name="A", password_hash="x")
        s.add(u)
        s.flush()
        s.add(Comment(property_id=pid, user_id=u.id, body="đã xem hiện trạng"))
        p.land_area_manual, p.priority = 82.0, 3
        s.commit()
    # phiên 3 xuất hiện -> vẫn cùng tài sản, giữ nhận xét & trường nhập tay
    add(repo, "4", LAND + " (lần 3)", 810_000_000, datetime(2026, 11, 1, 9))
    rebuild(repo)
    with repo.session() as s:
        p = s.get(Property, pid)
        assert p.session_count == 3 and p.price_latest == 810_000_000 and p.discount_pct == 19.0
        assert p.eff("land_area") == 82.0 and p.priority == 3
        assert s.query(Comment).filter_by(property_id=pid).count() == 1


def test_generic_titles_not_merged(repo):
    g = "Tài sản là quyền sử dụng đất theo quy định của pháp luật về đất đai"
    add(repo, "10", g, 5_000_000_000, datetime(2026, 9, 1, 9))
    add(repo, "11", g, 300_000_000, datetime(2026, 9, 20, 9))
    add(repo, "12", "Quyền sử dụng 14 lô đất ở tại khu dân cư thôn Tân Trung", 9_000_000_000, datetime(2026, 9, 3))
    add(repo, "13", "Quyền sử dụng 14 lô đất ở tại khu dân cư thôn Tân Trung", 2_000_000_000, datetime(2026, 10, 3))
    assert rebuild(repo)["properties"] == 4


def test_price_increase_warning(repo):
    add(repo, "20", LAND, 500_000_000, datetime(2026, 9, 1, 9))
    add(repo, "21", LAND, 900_000_000, datetime(2026, 10, 1, 9))
    rebuild(repo)
    with repo.session() as s:
        assert "cao hơn" in s.query(Property).one().link_warning
