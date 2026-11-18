"""Mẫu thật (hangdg.com 12/11/2026) – tài sản từng phải xác nhận vị trí tay. Mỗi mẫu: (tên tài sản, ô nơi có tài sản,
xã/phường mong đợi, tỉnh mong đợi). None = nguồn không ghi rõ, để trống là đúng."""
import pytest

from auction_crawler.realestate.extract import extract, place_rejection

CASES = [
    # A. thiếu tỉnh
    ("2-can-tho", "Quyền sử dụng đất của bà Nguyễn Thị A", "P. Mỹ Xuyên, TP Cần Thơ | X. Thạnh Thới An, TP Cần Thơ | "
     "P. Khánh Hòa, TP Cần Thơ", None, "Cần Thơ"),
    ("4-khanh-hoa", "Quyền sử dụng đất và tài sản gắn liền", "Tổ 5, phường Đông Hải | Tổ 7, phường Đông Hải | "
     "số 12 Trần Phú, phường Đông Hải, tỉnh Khánh Hòa", "Phường Đông Hải", "Khánh Hòa"),
    ("6-nay-la-tinh", "Quyền sử dụng đất tại thị trấn Thạnh Hoá",
     "khu phố 3, thị trấn Thạnh Hoá, huyện Thạnh Hoá, tỉnh Long An (nay là khu phố 3, xã Thạnh Hoá, tỉnh Tây Ninh)",
     "Xã Thạnh Hoá", "Tây Ninh"),
    ("7-dia-chi-co-nhan", "Tài sản của Trường Cao đẳng Kỹ thuật và Nghiệp vụ Hà Nội (Địa chỉ: Số 169 Nguyễn Ngọc Vũ, "
     "Phường Yên Hòa, TP Hà Nội)", "Trường Cao đẳng Kỹ thuật và Nghiệp vụ Hà Nội", "Phường Yên Hòa", "Hà Nội"),
    ("8-nay-la-giua", "Quyền sử dụng đất tại phường Đông Lương",
     "Khu phố 2, phường Đông Lương, thành phố Đông Hà (nay là phường Nam Đông Hà), tỉnh Quảng Trị",
     "Phường Nam Đông Hà", "Quảng Trị"),
    ("9-quan-ly", "Đất công do UBND xã Đông Thành quản lý, tỉnh Vĩnh Long", "tại nơi có tài sản",
     "Xã Đông Thành", "Vĩnh Long"),
    ("10-tdp", "Nhà đất tại phường 1", "Khu phố 4, phường 1, thành phố Đông Hà (nay là tổ dân phố Hữu Nghị, "
     "phường Đông Hà), tỉnh Quảng Trị", "Phường Đông Hà", "Quảng Trị"),
    ("3-khong-tinh", "Quyền sử dụng đất tại xã Thuận An", "UBND xã Thuận An", "Xã Thuận An", None),
    ("1-khong-tinh", "Quyền sử dụng đất nuôi trồng thủy sản tại phường Bồng Lai", "Chi tiết trong Bảng kê kèm Thông báo",
     "Phường Bồng Lai", None),
    # B. thiếu xã
    ("12-nay-thuoc", "Quyền sử dụng đất thửa số 12 tại thôn Bằng Trình, xã Thiệu Hợp, huyện Thiệu Hóa, tỉnh Thanh Hóa "
     "(nay thuộc thôn Bằng Trình, xã Thiệu Quang, tỉnh Thanh Hóa)", "UBND xã Thiệu Quang, tỉnh Thanh Hóa",
     "Xã Thiệu Quang", "Thanh Hóa"),
    ("14-taisancong", "Đấu giá QSDĐ năm 2026 xã Bằng Thành (lần 2), tỉnh Thái Nguyên", None, "Xã Bằng Thành", "Thái Nguyên"),
    ("15-nay-la-khong-ngoac", "Quyền sử dụng đất tại tổ 5 (phường Thọ Quang, Quận Sơn Trà) nay là phường Sơn Trà, "
     "thành phố Đà Nẵng", "Thi hành án dân sự thành phố Đà Nẵng", "Phường Sơn Trà", "Đà Nẵng"),
    ("17-xa-binh-duong", "Quyền sử dụng đất tại xã Bình Dương", "thôn 3, xã Bình Dương, tỉnh Gia Lai",
     "Xã Bình Dương", "Gia Lai"),
    ("19-nay-la-lao-cai", "Quyền sử dụng đất tại thị trấn Mậu A, huyện Văn Yên, tỉnh Yên Bái, nay là thôn Mậu A 4, "
     "xã Mậu A, tỉnh Lào Cai", "Trung tâm Phát triển quỹ đất tỉnh Lào Cai", "Xã Mậu A", "Lào Cai"),
    ("20-tan-an-lap", "5 thửa đất công tại phường Tân An, tỉnh Tây Ninh do Phòng KT-HT-ĐT phường Tân An quản lý",
     None, "Phường Tân An", "Tây Ninh"),
    # C. cũ / mới
    ("21-truoc-day", "Nhà đất tại phường An Bình", "khóm 2, phường An Bình, tỉnh Đồng Tháp (trước đây là khóm 2, "
     "phường An Bình B, thành phố Hồng Ngự, tỉnh Đồng Tháp)", "Phường An Bình", "Đồng Tháp"),
    ("22-tt-thanh-my", "Quyền sử dụng đất", "thôn Hà Nha, thị trấn Thạnh Mỹ, huyện Nam Giang (nay là xã Thạnh Mỹ, "
     "TP Đà Nẵng)", "Xã Thạnh Mỹ", "Đà Nẵng"),
    ("24-ha-tinh", "Quyền sử dụng đất", "thôn Tân An, xã Thạch Hạ, TP Hà Tĩnh nay là TDP Tân An, phường Trần Phú, "
     "tỉnh Hà Tĩnh", "Phường Trần Phú", "Hà Tĩnh"),
    ("25-ha-dong", "Quyền sử dụng đất", "số 5 ngõ 10, phường Văn Quán, quận Hà Đông, TP Hà Nội nay là số 5 ngõ 10, "
     "phường Hà Đông, TP Hà Nội", "Phường Hà Đông", "Hà Nội"),
]


@pytest.mark.parametrize("name,asset,place,ward,province", CASES, ids=[c[0] for c in CASES])
def test_location_samples(name, asset, place, ward, province):
    if place and place_rejection(place, "Chi cục THADS"):
        place = None
    info = extract(asset[:200], asset, place)
    assert (info.ward, info.province) == (ward, province), info.notes


def test_multi_asset_stays_blank():
    place = "xã Tân Hạnh, tỉnh Vĩnh Long | xã Long Hồ, tỉnh Vĩnh Long | xã Phú Quới, tỉnh Vĩnh Long"
    info = extract("5 tài sản", "Thông báo đấu giá 5 tài sản", place)
    assert info.ward is None and info.province == "Vĩnh Long"


@pytest.mark.parametrize("place", ["Nơi tài sản tọa lạc", "tại nơi có tài sản", "Chi tiết trong Bảng kê kèm Thông báo"])
def test_placeholder_place_rejected(place):
    assert place_rejection(place) is not None
    assert place_rejection("Nơi tài sản tọa lạc: thôn 3, xã Bản Lầu, tỉnh Lào Cai") is None


CASES2 = [
    ("8855", "Quyền sử dụng đất 2 thửa", "Thửa 296, TBĐ 20 – ĐC: 66A Đồng Nai, P.Nam Nha Trang, T. Khánh Hoà | Thửa 158, "
     "TBĐ 21 – ĐC: 39R Đồng Nai, P.Nam Nha Trang, T.Khánh Hòa", "Phường Nam Nha Trang", "Khánh Hòa"),
    ("42049", "Quyền sử dụng đất nông nghiệp", "Thôn Ta Ly, xã Ka Đô (đất nông nghiệp đối diện đường vào hồ Ka Zam)",
     "Xã Ka Đô", None),
    ("10124", "Quyền sử dụng đất thửa 12 và thửa 13, cùng địa chỉ: Phường 3 Bảo Lộc, tỉnh Lâm Đồng",
     "Phường 3 Bảo Lộc, tỉnh Lâm Đồng", "Phường 3 Bảo Lộc", "Lâm Đồng"),
    ("3385-tinh", "Căn hộ tại phường Tam Thắng, TPHCM và căn nhà tại P. Vũng Tàu, TPHCM",
     "Phòng THADS khu vực 11 – TP.Hồ Chí Minh", None, "TP. Hồ Chí Minh"),
    ("42165", "Quyền sử dụng đất tại xã Hợp Lý, huyện Lý Nhân (nay là xã Lý Nhân, tỉnh Ninh Bình)",
     "thửa 5, thuộc địa giới hành chính xã Lý Nhân, tỉnh Ninh Bình (địa phận xã Hợp Lý cũ)", "Xã Lý Nhân", "Ninh Bình"),
]


@pytest.mark.parametrize("name,asset,place,ward,province", CASES2, ids=[c[0] for c in CASES2])
def test_location_samples_2(name, asset, place, ward, province):
    if place and place_rejection(place, "Chi cục THADS"):
        place = None
    info = extract(asset[:200], asset, place)
    assert (info.ward, info.province) == (ward, province), info.notes


CASES3 = [
    ("5046-ban-do", "Quyền sử dụng đất thửa 129", "thửa 129, tờ bản đồ địa chính số 260 Bản đồ địa chính phường Sầm Sơn "
     "chỉnh lý năm 2025, phường Trường Sơn, TP Sầm Sơn, tỉnh Thanh Hoá (nay là Tổ dân phố Sơn Lợi, phường Sầm Sơn, "
     "tỉnh Thanh Hoá)", "Phường Sầm Sơn", "Thanh Hóa"),
    ("42808-truoc-sap-xep", "Quyền sử dụng đất tại thị trấn Hưng Hà (trước sắp xếp) nay là thôn Đãn Chàng, xã Hưng Hà, "
     "giáp xã Kim Trung (trước sắp xếp)", "xã Hưng Hà, tỉnh Hưng Yên", "Xã Hưng Hà", "Hưng Yên"),
    ("42964-thieu-ngoac", "Quyền sử dụng đất", "khóm 1, xã Tân Hồng, tỉnh Đồng Tháp (trước đây là thị trấn Sa Rài, "
     "huyện Tân Hồng tỉnh Đồng Tháp", "Xã Tân Hồng", "Đồng Tháp"),
]


@pytest.mark.parametrize("name,asset,place,ward,province", CASES3, ids=[c[0] for c in CASES3])
def test_location_samples_3(name, asset, place, ward, province):
    assert place_rejection(place, "Chi cục THADS") is None
    info = extract(asset[:200], asset, place)
    assert (info.ward, info.province) == (ward, province), info.notes


def test_province_name_not_joined_across_comma():
    from auction_crawler.realestate.extract import _provinces_in
    assert [n for n, _ in _provinces_in("xã Hưng Hà, tỉnh Hưng Yên")] == ["Hưng Yên"]
    assert [n for n, _ in _provinces_in("phường Long Hà, Tĩnh Gia")] == []


def test_commune_owner_gives_ward_but_enforcement_office_does_not(tmp_path):
    from datetime import datetime, timedelta

    from auction_crawler.models import AuctionNotice
    from auction_crawler.realestate.db import Property
    from auction_crawler.realestate.linker import commune_owner, rebuild
    from auction_crawler.storage import Repository
    assert commune_owner("UBND xã Thượng Ninh, tỉnh Thanh Hóa") == ("Xã Thượng Ninh", "Thanh Hóa")
    assert commune_owner("Ủy ban nhân dân phường Hòa Thành") == ("Phường Hòa Thành", None)
    assert commune_owner("Chi cục Thi hành án dân sự tỉnh Nghệ An") == (None, None)
    repo = Repository(f"sqlite:///{tmp_path}/c.db")
    repo.init_db()
    when = datetime.now() + timedelta(days=10)
    for sid, owner, title in [("1", "UBND xã Thượng Ninh, tỉnh Thanh Hóa", "Quyền sử dụng đất công ích thửa đất số 5, tờ bản đồ số 2"),
                              ("2", "Chi cục THADS tỉnh Nghệ An", "Quyền sử dụng đất thửa đất số 7, tờ bản đồ số 3"),
                              ("3", "UBND xã Thượng Ninh, tỉnh Thanh Hóa", "Cho thuê đất thửa đất số 9, tờ bản đồ số 1 tại xã Yên Lạc, tỉnh Thanh Hóa")]:
        repo.upsert(AuctionNotice(source="dgts", source_id=sid, title=title, asset_name=title, asset_owner=owner,
                                  starting_price=100_000_000, auction_date=when, registration_end=when,
                                  asset_type="quyen_su_dung_dat", origin="tai_san_cong", property_count=1))
    rebuild(repo)
    with repo.session() as s:
        get = lambda n: s.query(Property).filter(Property.parcel_no == n).one()  # noqa: E731
        a, b, c = get("5"), get("7"), get("9")
        assert (a.ward, a.province) == ("Xã Thượng Ninh", "Thanh Hóa")
        assert a.field_sources["ward"].startswith("đơn vị có tài sản")
        assert (b.ward, b.province) == (None, None)               # thi hành án: không suy
        assert c.ward == "Xã Yên Lạc"                              # tin ghi xã riêng -> theo tin, không theo đơn vị


def test_debt_collateral_location_and_address():
    t = ("Khoản nợ của Công ty TNHH Vạn Thắng (địa chỉ: số 5 Lê Lợi, phường Bến Thành, TP. Hồ Chí Minh) tại Agribank "
         "Chi nhánh 10. Tài sản bảo đảm là quyền sử dụng đất thửa đất số 120, tờ bản đồ số 7 tại ấp 3, xã Mỹ Yên, "
         "tỉnh Tây Ninh theo giấy chứng nhận số CS 123456")
    info = extract("Bán khoản nợ của Công ty TNHH Vạn Thắng", t, "Agribank Chi nhánh 10, TP. Hồ Chí Minh",
                   asset_type="khoan_no")
    assert info.sale_form == "khoan_no"
    assert (info.ward, info.province) == ("Xã Mỹ Yên", "Tây Ninh")
    assert info.collateral_address == "ấp 3, xã Mỹ Yên, tỉnh Tây Ninh"
    two = t + "; và tài sản bảo đảm là nhà đất tại phường 2, thành phố Tân An, tỉnh Long An"
    info2 = extract("Bán khoản nợ", two, None, asset_type="khoan_no")
    assert info2.ward is None and info2.collateral_address is None and info2.province == "Tây Ninh"


def test_debt_property_shows_collateral_address(tmp_path):
    from datetime import datetime, timedelta

    from auction_crawler.models import AuctionNotice
    from auction_crawler.realestate.db import Property
    from auction_crawler.realestate.linker import rebuild
    from auction_crawler.storage import Repository
    repo = Repository(f"sqlite:///{tmp_path}/d.db")
    repo.init_db()
    t = ("Khoản nợ của bà Lê Thị C tại BIDV. Tài sản bảo đảm là quyền sử dụng đất thửa đất số 12, tờ bản đồ số 3 "
         "tại thôn 2, xã Ka Đô, tỉnh Lâm Đồng theo giấy chứng nhận số BK 778899")
    when = datetime.now() + timedelta(days=9)
    repo.upsert(AuctionNotice(source="dgts", source_id="1", title="Bán khoản nợ của bà Lê Thị C", asset_name=t,
                              address="BIDV chi nhánh Lâm Đồng", asset_owner="BIDV", starting_price=500_000_000,
                              auction_date=when, registration_end=when, asset_type="khoan_no",
                              origin="ngan_hang_bao_dam", property_count=1))
    rebuild(repo)
    with repo.session() as s:
        p = s.query(Property).one()
        assert p.sale_form == "khoan_no" and (p.ward, p.province) == ("Xã Ka Đô", "Lâm Đồng")
        assert p.address == "TSBĐ: thôn 2, xã Ka Đô, tỉnh Lâm Đồng"


def test_nay_without_la():
    info = extract("Quyền sử dụng đất", "Quyền sử dụng đất",
                   "số 12, phường Nhị Châu, TP Hải Dương, tỉnh Hải Dương (nay phường Hải Dương, thành phố Hải Phòng)")
    assert (info.ward, info.province) == ("Phường Hải Dương", "Hải Phòng")
    info2 = extract("Nhà đất", "Nhà đất hiện nay đang cho thuê, tọa lạc tại xã Tân Hội, tỉnh Đồng Tháp", None)
    assert info2.ward == "Xã Tân Hội"                      # "hiện nay" không phải nhãn tên mới
