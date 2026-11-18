"""Bảng xã/phường cũ -> mới (sắp xếp 2025)."""
import csv

import pytest

from auction_crawler.realestate import wardmap
from auction_crawler.realestate.extract import extract


@pytest.fixture
def wm_file(tmp_path, monkeypatch):
    p = tmp_path / "ward_mapping.csv"
    rows = [
        ("Đồng Tháp", "Phường Mỹ Ngãi", "Xã Mỹ Tân", "Thành phố Cao Lãnh", "0"),
        ("Đồng Tháp", "Phường Mỹ Ngãi", "Xã Tân Thuận Tây", "Thành phố Cao Lãnh", "0"),
        ("Đồng Tháp", "Xã Tân Hồng", "Xã Tân Thành", "Huyện Tân Hồng", "0"),
        ("Đồng Tháp", "Xã Lai Vung", "Xã Tân Thành", "Huyện Lai Vung", "0"),
        ("Đồng Tháp", "Xã Bình Thành", "Xã Bình Thạnh", "Huyện Thanh Bình", "1"),
        ("Đồng Tháp", "Xã Tân Long", "Xã Bình Thạnh", "Huyện Thanh Bình", "1"),
    ]
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(wardmap.COLUMNS + [])
        w.writerows([(a, b, c, d, "", e) for a, b, c, d, e in rows])
    monkeypatch.setattr(wardmap, "DEFAULT_PATH", p)
    return p


def test_to_new(wm_file):
    wm = wardmap.load()
    assert wm.to_new("Xã Mỹ Tân", "Đồng Tháp") == "Phường Mỹ Ngãi"
    assert wm.to_new("xã my tan", "Đồng Tháp") == "Phường Mỹ Ngãi"
    assert wm.to_new("Phường Mỹ Ngãi", "Đồng Tháp") is None           # đã là tên mới
    assert wm.to_new("Xã Mỹ Tân", "Hà Nội") is None                    # tỉnh khác
    assert wm.to_new("Xã Tân Thành", "Đồng Tháp") is None              # trùng tên 2 huyện, tin không ghi huyện
    assert wm.to_new("Xã Tân Thành", "Đồng Tháp", "xã Tân Thành, huyện Lai Vung") == "Xã Lai Vung"
    assert wm.to_new("Xã Bình Thạnh", "Đồng Tháp") is None             # xã cũ bị chia


def test_extract_uses_map(wm_file):
    info = extract("Quyền sử dụng đất tại xã Mỹ Tân, thành phố Cao Lãnh, tỉnh Đồng Tháp",
                   address="xã Mỹ Tân, thành phố Cao Lãnh, tỉnh Đồng Tháp")
    assert info.province == "Đồng Tháp"
    assert info.ward == "Phường Mỹ Ngãi" and info.ward_new
    assert any("nay là Phường Mỹ Ngãi" in n for n in info.notes)


def test_no_map_file_keeps_name(tmp_path, monkeypatch):
    monkeypatch.setattr(wardmap, "DEFAULT_PATH", tmp_path / "none.csv")
    info = extract("Đất tại xã Mỹ Tân, thành phố Cao Lãnh, tỉnh Đồng Tháp")
    assert info.ward and "Mỹ Tân" in info.ward


def test_parse_resolution():
    text = ("1. Sắp xếp toàn bộ diện tích tự nhiên, quy mô dân số của xã Mỹ Tân, xã Tân Thuận Tây và phường 6 "
            "thành phường mới có tên gọi là phường Mỹ Ngãi. 2. Sắp xếp toàn bộ diện tích tự nhiên, quy mô dân số "
            "của các xã An Bình, Bình Hàng Trung và một phần diện tích tự nhiên, quy mô dân số của xã Mỹ Hội "
            "thành xã mới có tên gọi là xã Mỹ Thọ.")
    rows = wardmap.parse_resolution_text(text, "Đồng Tháp")
    got = {(r["xa_cu"], r["xa_moi"], r["mot_phan"]) for r in rows}
    assert ("Xã Mỹ Tân", "Phường Mỹ Ngãi", "0") in got
    assert ("Xã Tân Thuận Tây", "Phường Mỹ Ngãi", "0") in got
    assert ("Phường 6", "Phường Mỹ Ngãi", "0") in got
    assert ("Xã An Bình", "Xã Mỹ Thọ", "0") in got
    assert ("Xã Bình Hàng Trung", "Xã Mỹ Thọ", "0") in got
    assert ("Xã Mỹ Hội", "Xã Mỹ Thọ", "1") in got


def test_import_csv_fuzzy_headers(tmp_path, monkeypatch):
    src = tmp_path / "ds.csv"
    src.write_text("STT,Tỉnh/thành phố mới,Tên xã/phường mới,Tên ĐVHC cấp xã cũ,Huyện cũ\n"
                   "1,Đồng Tháp,Phường Mỹ Ngãi,\"Xã Mỹ Tân, xã Tân Thuận Tây\",TP Cao Lãnh\n"
                   "2,,Xã Tân Hồng,Xã Tân Thành,Huyện Tân Hồng\n", encoding="utf-8")
    out = tmp_path / "map.csv"
    monkeypatch.setattr(wardmap, "DEFAULT_PATH", out)
    rows = wardmap.read_source(src)
    assert {r["xa_cu"] for r in rows} == {"Xã Mỹ Tân", "Xã Tân Thuận Tây", "Xã Tân Thành"}
    assert all(r["tinh_moi"] == "Đồng Tháp" for r in rows)
    assert wardmap.write_mapping(rows) == 3
    assert wardmap.write_mapping(rows) == 3            # thêm lại không nhân đôi
    assert wardmap.load().to_new("Xã Tân Thành", "Đồng Tháp") == "Xã Tân Hồng"
