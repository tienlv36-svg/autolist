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
