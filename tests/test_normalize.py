from datetime import datetime

import pytest

from auction_crawler.normalize import detect_province, parse_datetime, parse_vnd


@pytest.mark.parametrize("s,v", [
    ("1.234.567.890 đồng", 1234567890),
    ("Giá khởi điểm: 1,5 tỷ đồng", 1_500_000_000),
    ("2 tỷ 350 triệu đồng", 2_350_000_000),
    ("500.000đ (Bằng chữ: năm trăm nghìn đồng)", 500_000),
    ("40.000.000,00 VNĐ", 40_000_000),
    ("liên hệ", None),
])
def test_parse_vnd(s, v):
    assert parse_vnd(s) == v


def test_parse_datetime():
    assert parse_datetime("09 giờ 00 phút, ngày 25/11/2026") == datetime(2026, 11, 25, 9, 0)
    assert parse_datetime("08:30 12-11-2026") == datetime(2026, 11, 12, 8, 30)
    assert parse_datetime("ngày 3 tháng 12 năm 2026") == datetime(2026, 12, 3)
    assert parse_datetime("Từ ngày 01/11/2026 đến 17 giờ ngày 20/11/2026") == datetime(2026, 11, 20, 17, 0)
    assert parse_datetime("2026-11-12T08:30:00") == datetime(2026, 11, 12, 8, 30)


@pytest.mark.parametrize("s,new,raw", [
    ("Xóm 3, xã X, huyện Y, tỉnh Nam Định", "Ninh Bình", "Nam Định"),
    ("Phường Phú Hội, TP Huế, tỉnh Thừa Thiên Huế", "Huế", "Thừa Thiên Huế"),
    ("Thủ Dầu Một, Bình Dương", "TP. Hồ Chí Minh", "Bình Dương"),
    ("Quận Ba Đình, Hà Nội", "Hà Nội", "Hà Nội"),
    ("Không có địa chỉ", None, None),
])
def test_detect_province(s, new, raw):
    assert detect_province(s) == (new, raw)


def test_time_after_date():
    assert parse_datetime("26-11-2026 09:00") == datetime(2026, 11, 26, 9, 0)
    assert parse_datetime(datetime(2026, 1, 2, 3, 4)) == datetime(2026, 1, 2, 3, 4)


def test_plausible_dt():
    from datetime import datetime
    from auction_crawler.normalize import plausible_dt
    from auction_crawler.sources.dgts import ms_to_vn
    assert plausible_dt(datetime(1970, 1, 1)) is None
    assert plausible_dt(datetime(2003, 3, 7)) is None
    assert plausible_dt(datetime(2021, 6, 15)) == datetime(2021, 6, 15)
    assert ms_to_vn(-25200000) is None and ms_to_vn(1) is None
    assert ms_to_vn(1762740000000).year == 2025
