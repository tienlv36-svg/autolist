"""Tự động gộp các phiên đấu giá lại của cùng một tài sản – và KHÔNG gộp các lô khác nhau."""
from datetime import datetime, timedelta

import pytest

from auction_crawler.models import AuctionNotice
from auction_crawler.realestate.db import Property
from auction_crawler.realestate.linker import rebuild
from auction_crawler.storage import Repository

D = datetime(2026, 6, 1, 9)


@pytest.fixture
def repo(tmp_path):
    r = Repository(f"sqlite:///{tmp_path}/m.db")
    r.init_db()
    return r


def add(repo, sid, title, price, days, owner="Ngân hàng TMCP Sài Gòn Thương Tín – CN Long An", place=None):
    when = D + timedelta(days=days)
    repo.upsert(AuctionNotice(source="dgts", source_id=sid, title=title, asset_name=title, address=place,
                              asset_owner=owner, starting_price=price, auction_date=when,
                              registration_end=when - timedelta(days=3), asset_type="nha_o_cong_trinh",
                              origin="ngan_hang_bao_dam", property_count=1))


def props(repo):
    with repo.session() as s:
        return sorted((p.session_count, p.price_first, p.price_latest) for p in s.query(Property))


def test_reauction_identical_text_without_parcel_is_merged(repo):
    t = "Quyền sở hữu nhà ở và quyền sử dụng đất tại số 12 đường Nguyễn Huệ, khu phố 3, phường Tân An, tỉnh Tây Ninh"
    add(repo, "1", t + " (đấu giá lần 1)", 3_000_000_000, 0)
    add(repo, "2", t + " – đấu giá lại lần 2, giá khởi điểm 2.700.000.000 đồng", 2_700_000_000, 40)
    add(repo, "3", t + " (lần 3) ngày 15/09/2026", 2_430_000_000, 90)
    rebuild(repo)
    assert props(repo) == [(3, 3_000_000_000, 2_430_000_000)]


def test_different_units_same_building_not_merged(repo):
    base = "Căn hộ {} chung cư Sunrise, đường Lê Lợi, phường Tân An, tỉnh Tây Ninh, diện tích sử dụng 75m2"
    add(repo, "1", base.format("A12.05"), 2_000_000_000, 0)
    add(repo, "2", base.format("A12.06"), 1_900_000_000, 30)
    rebuild(repo)
    assert len(props(repo)) == 2                 # khác số căn -> khác tài sản


def test_lots_same_auction_day_not_merged(repo):
    base = "Quyền sử dụng đất tại khu dân cư Phú Mỹ, phường Tân An, tỉnh Tây Ninh"
    add(repo, "1", base, 1_000_000_000, 0)
    add(repo, "2", base, 1_200_000_000, 0)       # cùng ngày, cùng mô tả -> 2 lô của 1 cuộc đấu giá
    rebuild(repo)
    assert len(props(repo)) == 2


def test_price_increase_without_hard_evidence_not_merged(repo):
    t = "Quyền sử dụng đất và nhà tại số 7 đường Trần Phú, phường Tân An, tỉnh Tây Ninh"
    add(repo, "1", t, 1_000_000_000, 0)
    add(repo, "2", t.replace("Trần Phú, ", "Trần Phú (gần chợ), "), 1_500_000_000, 60)   # đắt hơn 50% -> nghi khác
    rebuild(repo)
    assert len(props(repo)) == 2


def test_identical_text_with_price_increase_is_flagged(repo):
    t = "Quyền sử dụng đất và nhà tại số 7 đường Trần Phú, phường Tân An, tỉnh Tây Ninh"
    add(repo, "1", t, 1_000_000_000, 0)
    add(repo, "2", t, 1_500_000_000, 60)          # mô tả y hệt: gộp nhưng cảnh báo giá tăng
    rebuild(repo)
    with repo.session() as s:
        p = s.query(Property).one()
        assert p.session_count == 2 and p.link_warning and p.discount_pct is None


def test_same_parcel_same_ward_owner_merged_even_without_area(repo):
    a = "Quyền sử dụng đất thửa đất số 88, tờ bản đồ số 4 tọa lạc tại xã Mỹ Yên, tỉnh Tây Ninh"
    b = "QSDĐ thửa số 88 tờ bản đồ 04, xã Mỹ Yên, tỉnh Tây Ninh – tài sản bảo đảm của ông Nguyễn Văn B"
    add(repo, "1", a, 900_000_000, 0)
    add(repo, "2", b, 810_000_000, 45)
    rebuild(repo)
    assert props(repo) == [(2, 900_000_000, 810_000_000)]


def test_old_town_name_vs_new_commune_name_merged(repo):
    a = "Quyền sử dụng đất thửa đất số 5, tờ bản đồ số 9, diện tích 150m2 tọa lạc tại thị trấn Thạnh Mỹ, huyện Nam Giang, tỉnh Quảng Nam"
    b = "Quyền sử dụng đất thửa đất số 5, tờ bản đồ số 9, diện tích 150m2 tọa lạc tại xã Thạnh Mỹ, thành phố Đà Nẵng"
    add(repo, "1", a, 700_000_000, 0, owner="Chi cục THADS Nam Giang")
    add(repo, "2", b, 630_000_000, 50, owner="Phòng THADS khu vực 5 TP Đà Nẵng")
    rebuild(repo)
    assert props(repo) == [(2, 700_000_000, 630_000_000)]


def test_price_ratio_over_5x_never_merged(repo):
    t = "Quyền sử dụng đất thửa đất số 88, tờ bản đồ số 4, diện tích 120m2 tọa lạc tại xã Mỹ Yên, tỉnh Tây Ninh"
    add(repo, "1", t, 3_900_000_000, 0)
    add(repo, "2", t, 305_800_000_000, 60)       # cùng tờ/thửa, diện tích nhưng giá gấp 78 lần -> không gộp
    rebuild(repo)
    assert len(props(repo)) == 2


def test_machine_pinned_links_split_on_price_ratio_but_user_merge_kept(repo):
    from auction_crawler.realestate.db import PropertyNotice
    add(repo, "1", "Căn hộ tầng 5 chung cư F-Home, phường Hải Châu, TP Đà Nẵng", 3_900_000_000, 0)
    add(repo, "2", "Toàn bộ tòa nhà F-Home 20 tầng, phường Hải Châu, TP Đà Nẵng", 305_800_000_000, 30)
    rebuild(repo)
    with repo.Session.begin() as s:                 # giả lập: máy (quét lịch sử) từng khoá 2 tin vào cùng tài sản
        pns = s.query(PropertyNotice).all()
        pid = pns[0].property_id
        for pn in pns:
            pn.property_id, pn.manual, pn.link_source = pid, True, "history"
    rebuild(repo)
    assert len(props(repo)) == 2                    # máy khoá nhầm, giá chênh 78 lần -> tự tách
    with repo.Session.begin() as s:                 # người dùng chủ động gộp -> tôn trọng
        pns = s.query(PropertyNotice).all()
        pid = pns[0].property_id
        for pn in pns:
            pn.property_id, pn.manual, pn.link_source = pid, True, "manual"
    rebuild(repo)
    assert len(props(repo)) == 1
