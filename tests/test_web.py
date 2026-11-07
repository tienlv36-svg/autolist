import re
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from auction_crawler.config import Settings
from auction_crawler.models import AuctionNotice
from auction_crawler.realestate.db import FileView, Property, User
from auction_crawler.realestate.linker import rebuild
from auction_crawler.storage import Repository
from auction_crawler.web.app import create_app
from auction_crawler.web.auth import hash_password

LAND = ("Quyền sử dụng đất thửa đất số 2748, tờ bản đồ số 08 diện tích 80,3m2 đất ở tại đô thị, tọa lạc tại "
        "ấp 1, xã Mỹ Tân, tỉnh Đồng Tháp (nay là phường Mỹ Ngãi, tỉnh Đồng Tháp)")


@pytest.fixture
def env(tmp_path):
    repo = Repository(Settings(db_url=f"sqlite:///{tmp_path}/w.db").db_url)
    repo.init_db()
    soon = datetime.now() + timedelta(days=5)
    for sid, price, when, title in [("1", 1_000_000_000, datetime(2026, 9, 1), LAND),
                                    ("2", 800_000_000, soon + timedelta(days=3), LAND + " (lần 2)")]:
        repo.upsert(AuctionNotice(source="dgts", source_id=sid, title=title, asset_name=title, province="Đồng Tháp",
                                  asset_owner="Agribank chi nhánh Đồng Tháp", starting_price=price, auction_date=when,
                                  registration_end=soon if sid == "2" else when, asset_type="quyen_su_dung_dat",
                                  origin="ngan_hang_bao_dam", url="https://example.invalid/x"))
    repo.upsert(AuctionNotice(source="dgts", source_id="3", title="Cho thuê mặt bằng căn tin 50m2 tại phường Cao Lãnh",
                              province="Đồng Tháp", asset_owner="Bệnh viện", starting_price=50_000_000,
                              asset_type="cho_thue_mat_bang", origin="tai_san_cong"))
    rebuild(repo)
    with repo.Session.begin() as s:
        s.add_all([User(username="admin", full_name="Quản trị", password_hash=hash_password("matkhau123"), role="admin"),
                   User(username="nv1", full_name="Nhân viên 1", password_hash=hash_password("matkhau123"))])
    app = create_app(repo, media_root=tmp_path / "media", sync_docs=False)
    return repo, TestClient(app)


def login(c, u="admin"):
    r = c.post("/login", data={"username": u, "password": "matkhau123", "next": "/"}, follow_redirects=False)
    assert r.status_code == 303


def csrf(c, url):
    return re.search(r'name="csrf" value="([^"]+)"', c.get(url).text).group(1)


def test_requires_login(env):
    _, c = env
    assert c.get("/", follow_redirects=False).headers["location"].startswith("/login")
    r = c.post("/login", data={"username": "admin", "password": "sai"})
    assert "Sai tên đăng nhập" in r.text


def test_list_and_filters(env):
    repo, c = env
    login(c)
    r = c.get("/")
    assert "2</strong> tài sản" in r.text and "−20% so phiên 1" in r.text and "800 triệu" in r.text
    assert "Tờ 08 · Thửa 2748 — Phường Mỹ Ngãi, Đồng Tháp" in r.text
    assert "1</strong> tài sản" in c.get("/?sale_form=cho_thue").text
    assert "1</strong> tài sản" in c.get("/?owner_type=ngan_hang_bao_dam&price_min=0,5&price_max=0,9").text
    assert "0</strong> tài sản" in c.get("/?price_min=2").text
    assert "1</strong> tài sản" in c.get("/?province=Đồng Tháp&ward=Phường Mỹ Ngãi").text
    assert "1</strong> tài sản" in c.get("/?open_only=1&discounted=1").text
    assert c.get("/api/wards?province=Đồng Tháp").json()[0]["name"]


def test_detail_workflow(env):
    repo, c = env
    login(c)
    with repo.session() as s:
        pid = s.query(Property).filter(Property.session_count == 2).one().id
    url = f"/p/{pid}"
    r = c.get(url)
    assert "Các phiên đấu giá" in r.text and "1 tỷ" in r.text and "−20%" in r.text
    tok = csrf(c, url)
    # nhập tay số tờ/thửa + diện tích
    c.post(f"{url}/fields", data={"csrf": tok, "map_sheet": "8", "parcel_no": "2748", "land_area": "81,5"})
    with repo.session() as s:
        p = s.get(Property, pid)
        assert p.map_sheet_manual == "8" and p.land_area_manual == 81.5 and p.eff("land_area") == 81.5
    # ưu tiên + xác thực
    c.post(f"{url}/priority", data={"csrf": tok, "priority": 4})
    c.post(f"{url}/verify", data={"csrf": tok})
    # nhận xét
    c.post(f"{url}/comments", data={"csrf": tok, "body": "Pháp lý sạch, đường ô tô vào"})
    # upload + xem file -> lịch sử xem
    c.post(f"{url}/files", data={"csrf": tok, "folder": "Pháp lý"},
           files=[("files", ("so-do.pdf", b"%PDF-1.4 test", "application/pdf")),
                  ("files", ("anh1.jpg", b"\xff\xd8\xff", "image/jpeg"))])
    page = c.get(url).text
    fid = re.search(r'href="/files/(\d+)" target="_blank">so-do.pdf', page).group(1)
    assert c.get(f"/files/{fid}").content == b"%PDF-1.4 test"
    c.get(f"/files/{fid}?download=1")
    # giao việc cho nv1
    with repo.session() as s:
        nv1 = s.query(User).filter_by(username="nv1").one().id
    c.post(f"{url}/tasks", data={"csrf": tok, "title": "Khảo sát hiện trạng", "assignee_id": nv1, "due_date": "2026-12-01"})
    page = c.get(url).text
    assert "Rất cao" in page and "✓ Đã xác thực" in page and "Pháp lý sạch" in page
    assert "Quản trị" in page and "📁 Pháp lý" in page and "Khảo sát hiện trạng" in page
    assert "nhập tay" in page and "81,5 m²" in page
    with repo.session() as s:
        assert [v.action for v in s.query(FileView).order_by(FileView.id)] == ["view", "download"]
    # nv1 thấy việc được giao và cập nhật trạng thái
    c.post("/logout")
    login(c, "nv1")
    t = c.get("/tasks").text
    assert "Khảo sát hiện trạng" in t
    tid = re.search(r'/tasks/(\d+)/status', t).group(1)
    c.post(f"/tasks/{tid}/status", data={"csrf": csrf(c, "/tasks"), "status": "xong"})
    assert "Khảo sát hiện trạng" not in c.get("/tasks").text   # mặc định chỉ hiện việc đang mở
    # nv1 không phải admin
    assert c.get("/admin/users").status_code == 403
    # dữ liệu nhập tay & nhận xét còn nguyên sau khi chạy lại linker
    rebuild(repo)
    with repo.session() as s:
        p = s.get(Property, pid)
        assert p.priority == 4 and p.verified and p.land_area_manual == 81.5


def test_csrf_and_admin(env):
    _, c = env
    login(c)
    assert c.post("/p/1/priority", data={"csrf": "sai", "priority": 3}).status_code == 400
    tok = csrf(c, "/admin/users")
    c.post("/admin/users", data={"csrf": tok, "username": "nv2", "full_name": "NV 2", "password": "12345678"})
    assert "@nv2" in c.get("/admin/users").text


def test_manual_price_and_province(env):
    repo, c = env
    login(c)
    with repo.session() as s:
        pid = s.query(Property).filter(Property.session_count == 2).one().id
    url = f"/p/{pid}"
    tok = csrf(c, url)
    c.post(f"{url}/fields", data={"csrf": tok, "price_latest": "700 triệu", "province": "Vĩnh Long"})
    with repo.session() as s:
        p = s.get(Property, pid)
        assert p.price_latest_manual == 700_000_000 and p.discount_pct == 30.0 and p.eff("province") == "Vĩnh Long"
    assert "1</strong> tài sản" in c.get("/?province=Vĩnh Long&price_max=0,7").text
    c.post(f"{url}/fields", data={"csrf": tok, "price_first": "1.200.000.000"})
    with repo.session() as s:
        assert s.get(Property, pid).discount_pct == 41.7
