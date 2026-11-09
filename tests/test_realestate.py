"""Các câu mẫu lấy nguyên văn từ tin đấu giá thật (11/2026)."""
import pytest

from auction_crawler.realestate.extract import detect_sale_form, detect_ward, extract, parse_number


@pytest.mark.parametrize("s,v", [("3.198,1", 3198.1), ("1.036", 1036), ("76.4", 76.4), ("136,1", 136.1), ("1288", 1288)])
def test_parse_number(s, v):
    assert parse_number(s) == v


def test_parcel_and_area_residential():
    t = ("Tài sản của ông Doãn Cương; thửa đất số: 30; tờ bản đồ số: 59; diện tích: 130 m² đất tại đô thị, "
         "địa chỉ thửa đất: Bản Thẳm Mạy, phường Chiềng An")
    i = extract(t)
    assert i.parcels == [("59", "30")] and i.land_area == 130


def test_breakdown_residential_other():
    t = ("Tài sản đấu giá (lần 5) là: Quyền sử dụng 210,6 m2 đất (trong đó 150 m2 đất ở nông thôn, "
         "60,6 m2 đất trồng cây lâu năm) tại thửa đất số 12, tờ bản đồ số 7")
    i = extract(t)
    assert (i.land_area, i.residential_area, i.other_land_area) == (210.6, 150, 60.6)
    assert i.session_hint == 5


def test_floor_area_not_land():
    t = ("Quyền sử dụng đất thửa số 273, tờ bản đồ số 51, diện tích 120,5m2 đất ở tại đô thị và nhà ở diện tích "
         "xây dựng 103,5m2, diện tích sàn 212,4m2 tọa lạc tại Đường Lê Quý Đôn, phường 5, thành phố Bạc Liêu")
    i = extract(t)
    assert i.land_area == 120.5 and i.residential_area == 120.5 and i.floor_area == 212.4
    assert i.parcels == [("51", "273")] and i.has_house


def test_other_land_type_code():
    i = extract("Quyền sử dụng đất thuộc thửa đất số 14(41); Tờ bản đồ số 18(9); Diện tích: 3.198,1m2; "
                "Loại đất: Đất chuyên trồng lúa nước.")
    assert i.land_area == 3198.1 and i.parcels == [("18", "14")]


def test_tbd_abbrev_and_ward_nay_la():
    t = ("Nhà, đất tại thửa đất số: 574, TBĐ số: 32, B8/26A, Ấp 2, X.Tân Quý Tây, H.Bình Chánh "
         "(Nay là X.Bình Chánh, TP.HCM) (Nơi có tài sản); DT: 422,9 m²")
    i = extract(t)
    assert i.parcels == [("32", "574")] and i.land_area == 422.9
    assert i.ward == "Xã Bình Chánh"


def test_ward_prefers_current_name():
    a = "ấp 1, xã Mỹ Tân, thành phố Cao Lãnh, tỉnh Đồng Tháp (nay là phường Mỹ Ngãi, tỉnh Đồng Tháp);"
    assert detect_ward(a) == "Phường Mỹ Ngãi"
    assert detect_ward("Xóm 3, xã Hải Anh, tỉnh Ninh Bình") == "Xã Hải Anh"


def test_dimensions():
    i = extract("Kích thước mặt tiền rộng 12,7m, mặt hậu rộng 12,04m, chiều sâu bình quân 36,7m. Diện tích 466m2")
    assert (i.width, i.length) == (12.7, 36.7)
    # "kích thước A x B" không nói chiều nào là ngang -> không suy luận
    i = extract("nhà xây dựng trên đất có kích thước 10,1m x 5,1m, cao 6,2m")
    assert (i.width, i.length) == (None, None)
    # cạnh thửa ("phía Đông giáp ... chiều dài") không phải chiều dài thửa
    i = extract("Phía Đông giáp hộ ông Bình có chiều dài 21,6m; Phía Tây giáp đường đê có chiều dài 21,43m")
    assert i.length is None


@pytest.mark.parametrize("title,form", [
    ("Cho thuê quyền sử dụng đất nông nghiệp sử dụng vào mục đích công ích tại xã Phú Lộc", "cho_thue"),
    ("Đấu giá quyền khai thác mặt bằng căn tin", "cho_thue"),
    ("Khoản nợ của khách hàng Lương Hữu Cường tại Agribank", "khoan_no"),
    ("Quyền sử dụng 33 lô đất còn lại Khu dân cư mới", "ban"),
])
def test_sale_form(title, form):
    assert detect_sale_form(title, None) == form


def test_land_type_before_number():
    t = ("Quyền sử dụng đất thuộc thửa đất số 1204, tờ bản đồ số 5; diện tích 110,8m2; mục đích sử dụng: "
         "đất ở tại nông thôn 100m2, đất trồng cây hàng năm khác 10,8m2;")
    i = extract(t)
    assert (i.land_area, i.residential_area, i.other_land_area) == (110.8, 100, 10.8)


def test_multi_parcel_left_empty():
    t = ("Thửa đất số 61 tờ bản đồ số 13 diện tích 1.060,9m2 đất chuyên trồng lúa nước. "
         "Thửa đất số 62 tờ bản đồ số 13 diện tích 150m2 đất ở tại nông thôn")
    i = extract(t)
    assert (i.land_area, i.residential_area, i.other_land_area, i.map_sheet, i.parcel_no) == (None,) * 5
    assert i.multi and any("nhiều" in n for n in i.notes)
    assert i.parcels == [("13", "61"), ("13", "62")]      # vẫn liệt kê để tham khảo


def test_conflicting_areas_left_empty():
    i = extract("Quyền sử dụng đất diện tích 80,0 m2 (Theo sơ đồ đo đạc diện tích còn 76,4 m2), thửa đất số 27, tờ bản đồ số 5")
    assert i.land_area is None and i.parcel_no == "27"


def test_purpose_after_total_sentence():
    t = ("Quyền sử dụng đất thuộc thửa số 847, tờ bản đồ số 05, diện tích 369.1m2. Mục đích sử dụng đất: "
         "đất ở tại đô thị (ODT) 36m2, đất trồng cây lâu năm (CLN): 333.1m2, tọa lạc tại Phường 6")
    i = extract(t)
    assert (i.land_area, i.residential_area, i.other_land_area) == (369.1, 36, 333.1)


def test_purpose_without_number_not_inferred():
    # "mục đích sử dụng: Đất ở" không kèm số -> không tự gán toàn bộ là đất ở
    i = extract("thửa đất số: 464, tờ bản đồ số: 14, diện tích: 162,0m2, mục đích sử dụng đất: Đất ở tại đô thị, địa chỉ")
    assert (i.land_area, i.residential_area) == (162, None)


def test_province_strict():
    from auction_crawler.realestate.extract import detect_province_strict
    assert detect_province_strict("xã Mỹ Tân, tỉnh Đồng Tháp")[0] == "Đồng Tháp"
    assert detect_province_strict("phường Định Hòa, tỉnh Bình Dương (nay là phường Chánh Hiệp, Tp. Hồ Chí Minh)")[0] == "TP. Hồ Chí Minh"
    assert detect_province_strict("Tài sản thi hành án theo quy định của pháp luật") == (None, None)
    assert detect_province_strict("lô 1 tại tỉnh Lâm Đồng, lô 2 tại tỉnh Gia Lai") == (None, None)


def test_renumbered_parcel_and_boundary_refs():
    t = ("Quyền sử dụng đất tại thửa đất số 1628, tờ bản đồ số 14 (nay là tờ bản đồ số 52), diện tích 195m2, "
         "phía Bắc giáp thửa 620, phía Nam giáp thửa đất số 542")
    i = extract(t)
    assert (i.map_sheet, i.parcel_no, i.land_area, i.multi) == ("52", "1628", 195, False)


def test_duplicate_asset_text_not_double_counted():
    t = ("Tài sản đấu giá (lần 5) là: Quyền sử dụng 210,6 m2 đất (trong đó 150 m2 đất ở nông thôn, "
         "60,6 m2 đất nuôi trồng thủy sản) thuộc thửa đất số 343, tờ bản đồ số 21")
    i = extract(t, t, None, None, [t, "Xã Yên Phong, huyện Yên Mô"])
    assert (i.land_area, i.residential_area, i.other_land_area, i.notes) == (210.6, 150, 60.6, [])


@pytest.mark.parametrize("text,n", [
    ("Quyền sử dụng đất ... tỉnh Lào Cai (Đấu giá lần 3)", 3),
    ("Tài sản đấu giá (lần 5) là: Quyền sử dụng 210,6 m2 đất", 5),
    ("Đấu giá lại lần 2 quyền sử dụng đất", 2),
    ("... tại địa chỉ: Xã Phú Diễn, Thành phố Hà Nội (lần 3)", 3),
    ("GCN đứng tên bà Lâm, cập nhật biến động lần 01 chuyển mục đích sử dụng", None),
    ("Thông báo đăng lần 2 về việc đấu giá", None),
])
def test_session_hint(text, n):
    from auction_crawler.realestate.extract import detect_session_hint
    assert detect_session_hint(text) == n
