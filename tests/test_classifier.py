from auction_crawler.classifier import RuleClassifier

clf = RuleClassifier()


def test_land_thads():
    r = clf.classify("Đấu giá quyền sử dụng đất thửa số 12 của Chi cục Thi hành án dân sự")
    assert r["asset_type"].code == "quyen_su_dung_dat"
    assert r["origin"].code == "thi_hanh_an"


def test_vehicle_confiscated():
    r = clf.classify("Thông báo đấu giá xe ô tô là tang vật vi phạm hành chính bị tịch thu")
    assert r["asset_type"].code == "phuong_tien"
    assert r["origin"].code == "tich_thu"


def test_license_plate_beats_vehicle():
    r = clf.classify("Đấu giá biển số xe ô tô 30K-999.99")
    assert r["asset_type"].code == "bien_so_xe"


def test_fallback():
    assert clf.classify("abc xyz")["asset_type"].code == "khac"
