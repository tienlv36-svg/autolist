"""Bộ lọc đã lưu + Telegram cá nhân, nhắc hạn, gợi ý gộp phiên, độ đầy đủ dữ liệu."""
import json
from datetime import datetime, timedelta

import httpx
import pytest

from auction_crawler.alerts import filters_from_query, run_alerts
from auction_crawler.config import Settings
from auction_crawler.models import AuctionNotice
from auction_crawler.realestate.db import CartItem, Property, SavedSearch, Task, User
from auction_crawler.realestate.linker import rebuild
from test_web import csrf, env, login  # noqa: F401  (fixture)


class FakeTG:
    def __init__(self, updates=()):
        self.sent, self.updates = [], list(updates)

    def transport(self):
        def h(req):
            m = req.url.path.rsplit("/", 1)[-1]
            body = json.loads(req.content or b"{}")
            if m == "getUpdates":
                return httpx.Response(200, json={"ok": True, "result": self.updates})
            if m == "sendMessage":
                self.sent.append(body)
                return httpx.Response(200, json={"ok": True, "result": {}})
            return httpx.Response(200, json={"ok": True, "result": {"username": "hangdg_bot"}})
        return httpx.MockTransport(h)


def upd(chat, text):
    return {"update_id": 1, "message": {"chat": {"id": chat, "type": "private", "first_name": "A"}, "text": text}}


@pytest.fixture
def tg(monkeypatch):
    monkeypatch.setenv("AUCTION_TELEGRAM_TOKEN", "x")
    monkeypatch.setenv("AUCTION_TELEGRAM_CHAT", "-100")


def test_filters_from_query_roundtrip():
    f = filters_from_query("owner_type=ngan_hang_bao_dam&owner_type=thi_hanh_an&province=Hà+Nội&price_max=5&open_only=1")
    assert f.owner_type == ["ngan_hang_bao_dam", "thi_hanh_an"] and f.province == "Hà Nội" and f.price_max == 5
    assert f.open_only


def test_saved_search_link_and_alerts(env, tg):  # noqa: F811
    repo, c = env
    login(c, "nv1")
    tok = csrf(c, "/")
    c.post("/searches", data={"csrf": tok, "name": "Đồng Tháp", "query": "province=Đồng+Tháp&page=2", "notify": "1"})
    page = c.get("/searches").text
    assert "Đồng Tháp" in page and "1 tài sản" in page
    with repo.session() as s:
        ss = s.query(SavedSearch).one()
        assert ss.query == "province=Đồng+Tháp" and ss.notify
    # liên kết Telegram: tạo mã -> người dùng gửi /start <mã> cho bot
    c.post("/account/telegram", data={"csrf": tok, "action": "code"})
    with repo.session() as s:
        code = s.query(User).filter_by(username="nv1").one().tg_link_code
    assert code and code in c.get("/account").text
    fake = FakeTG([upd(555, f"/start {code}")])
    s_ = Settings(db_url=repo.engine.url.render_as_string(hide_password=False), raw_cache_dir=None)
    # đặt mốc "mới" về trước khi có dữ liệu -> tài sản Đồng Tháp là mới
    with repo.Session.begin() as s:
        s.query(SavedSearch).one().checked_at = datetime.now() - timedelta(days=1)
    st = run_alerts(s_, repo, transport=fake.transport())
    assert st.linked == 1 and st.search_msgs == 1
    msgs = [m for m in fake.sent if m["chat_id"] == "555"]
    assert any("Đã liên kết" in m["text"] for m in msgs)
    alert = [m for m in msgs if "Đồng Tháp" in m["text"] and "tài sản mới" in m["text"]][0]
    assert "1 tài sản mới" in alert["text"]
    assert not any(m["chat_id"] == "-100" for m in fake.sent)          # không gửi vào nhóm chung
    # lần sau: không có gì mới -> không gửi lại
    fake2 = FakeTG()
    assert run_alerts(s_, repo, transport=fake2.transport()).search_msgs == 0
    # tài sản mới khớp bộ lọc -> báo
    repo.upsert(AuctionNotice(source="dgts", source_id="9", title="QSDĐ thửa đất số 77, tờ bản đồ số 3, phường Cao Lãnh, "
                              "tỉnh Đồng Tháp diện tích 120m2", asset_type="quyen_su_dung_dat", province="Đồng Tháp",
                              origin="thi_hanh_an", starting_price=2_000_000_000))
    rebuild(repo)
    fake3 = FakeTG()
    assert run_alerts(s_, repo, transport=fake3.transport()).search_msgs == 1
    assert "1 tài sản mới" in fake3.sent[0]["text"] and "thửa đất số 77" in fake3.sent[0]["text"]
    # bộ lọc là riêng tư
    c.post("/logout")
    login(c, "admin")
    with repo.session() as s:
        sid = s.query(SavedSearch).one().id
    assert "Đồng Tháp" not in c.get("/searches").text
    assert c.get(f"/searches/{sid}/open", follow_redirects=False).status_code == 404


def test_reminders_cart_and_tasks(env, tg):  # noqa: F811
    repo, c = env
    with repo.Session.begin() as s:
        nv = s.query(User).filter_by(username="nv1").one()
        adm = s.query(User).filter_by(username="admin").one()
        nv.tg_chat_id = "777"
        soon = s.query(Property).filter(Property.registration_end >= datetime.now()).first()
        soon.registration_end = datetime.now() + timedelta(days=2)          # hết hạn trong 3 ngày -> nhắc
        s.add(CartItem(user_id=nv.id, property_id=soon.id))
        s.add(Task(title="Đi xem hiện trạng", assigner_id=adm.id, assignee_id=nv.id,
                   due_date=datetime.now().date() - timedelta(days=1)))
        pid = soon.id
    login(c, "nv1")
    page = c.get("/").text
    assert "2</b> mục cần chú ý" in page
    r = c.get("/reminders").text
    assert f"#{pid}" in r and "Đi xem hiện trạng" in r and "quá hạn" in r
    fake = FakeTG()
    s_ = Settings(db_url=repo.engine.url.render_as_string(hide_password=False), raw_cache_dir=None)
    assert run_alerts(s_, repo, transport=fake.transport()).reminder_msgs == 1
    assert "Nhắc hạn" in fake.sent[0]["text"] and "QUÁ HẠN" in fake.sent[0]["text"]
    assert run_alerts(s_, repo, transport=FakeTG().transport()).reminder_msgs == 0   # mỗi ngày 1 lần


TXT = "Quyền sử dụng đất thửa đất số {p}, tờ bản đồ số 12, diện tích {a}m2 đất ở tại {w}, tỉnh Đồng Tháp"


def test_auto_merge_old_and_new_ward_names(env):  # noqa: F811
    repo, c = env
    fut, past = datetime.now() + timedelta(days=8), datetime(2026, 3, 1)
    # cùng tờ/thửa + diện tích, xã ghi tên cũ (trước 7/2025) và tên mới "(nay là …)" -> TỰ ĐỘNG gộp
    for sid, w, when, price in [("50", "tọa lạc tại xã Mỹ Tân, thành phố Cao Lãnh, tỉnh Đồng Tháp (nay là phường Mỹ Ngãi, tỉnh Đồng Tháp)", fut, 900_000_000),
                                ("51", "tọa lạc tại xã Mỹ Tân, thành phố Cao Lãnh, tỉnh Đồng Tháp", past, 1_000_000_000)]:
        t = f"Quyền sử dụng đất thửa đất số 345, tờ bản đồ số 12, diện tích 123,4m2 đất ở {w}"
        repo.upsert(AuctionNotice(source="dgts", source_id=sid, title=t, asset_name=t, asset_owner="Ngân hàng X",
                                  starting_price=price, auction_date=when, registration_end=when - timedelta(days=3),
                                  asset_type="quyen_su_dung_dat", origin="ngan_hang_bao_dam", property_count=1))
    # cùng tờ/thửa nhưng khác diện tích -> không gộp
    t = "Quyền sử dụng đất thửa đất số 345, tờ bản đồ số 12, diện tích 300m2 tọa lạc tại xã Tân Hội, tỉnh Đồng Tháp"
    repo.upsert(AuctionNotice(source="dgts", source_id="52", title=t, asset_name=t, starting_price=1_000_000_000,
                              auction_date=past, asset_type="quyen_su_dung_dat", origin="ngan_hang_bao_dam"))
    rebuild(repo)
    with repo.session() as s:
        ps = s.query(Property).filter(Property.parcel_no == "345").all()
        assert len(ps) == 2
        p = [x for x in ps if x.session_count == 2][0]
        assert p.price_first == 1_000_000_000 and p.discount_pct == 10.0
        assert p.ward == "Phường Mỹ Ngãi" and p.province == "Đồng Tháp"     # tên mới thắng tên cũ
    login(c)
    assert "Gợi ý gộp" not in c.get("/").text and c.get("/merges").status_code == 404


def test_quality_page_and_missing_filter(env):  # noqa: F811
    repo, c = env
    login(c)
    page = c.get("/quality").text
    assert "Độ đầy đủ dữ liệu" in page and "Tổng diện tích đất" in page and "Diện tích sàn" in page
    with repo.session() as s:
        total_open = s.query(Property).filter(Property.registration_end >= datetime.now()).count()
    assert f"<b>{total_open}</b> tài sản" in page
    r = c.get("/?open_only=1&missing=floor_area").text
    assert "tài sản" in r
    # mặt bằng không có diện tích sàn nhưng không thuộc phạm vi 'nhà + đất' -> không tính thiếu
    assert "0</strong> tài sản" in c.get("/?missing=floor_area").text


def test_pwa_assets(env):  # noqa: F811
    _, c = env
    m = c.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.json()["display"] == "standalone" and "manifest" in m.headers["content-type"]
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw.headers["content-type"] and "serviceWorker" not in sw.text
    assert c.get("/offline").status_code == 200 and c.get("/static/icon-512.png").status_code == 200
    page = c.get("/login").text
    assert 'rel="manifest"' in page and "serviceWorker.register" in page


def test_price_chart_and_stats(env):  # noqa: F811
    repo, c = env
    login(c)
    with repo.session() as s:
        pid = s.query(Property).filter(Property.session_count == 2).one().id
    page = c.get(f"/p/{pid}").text
    assert 'class="pchart"' in page and "Phiên 1" in page and "800 triệu" in page
    st = c.get("/stats").text
    assert "Tài sản còn hạn đăng ký" in st and "Đồng Tháp" in st and "Ngân hàng / TCTD" in st and "Tuần" in st


LOC = "Quyền sử dụng đất thửa đất số {p}, tờ bản đồ số 3, diện tích 85m2 tọa lạc tại {w}"


def _add(repo, sid, text, place=None, when=None, doc=None):
    when = when or datetime.now() + timedelta(days=9)
    repo.upsert(AuctionNotice(source="dgts", source_id=sid, title=text, asset_name=text, address=place,
                              asset_owner="Chi cục THADS", starting_price=1_000_000_000, auction_date=when,
                              registration_end=when - timedelta(days=2), asset_type="quyen_su_dung_dat",
                              origin="thi_hanh_an", property_count=1))
    if doc is not None:
        from auction_crawler.storage import NoticeRow
        with repo.Session.begin() as s:
            s.query(NoticeRow).filter_by(source_id=sid).one().doc_info = doc


def test_location_sources_and_confirmation(env):  # noqa: F811
    repo, c = env
    # A: ô nơi có tài sản ghi địa chỉ ngân hàng (bị loại) + mô tả "tọa lạc tại" -> lấy từ mô tả
    _add(repo, "A", LOC.format(p=1, w="xã Tân Hội, thành phố Cao Lãnh, tỉnh Đồng Tháp"),
         place="Ngân hàng Agribank, 2 Láng Hạ, Hà Nội")
    # B: nơi có tài sản và mô tả ghi 2 xã khác nhau -> trống + ứng viên
    _add(repo, "B", LOC.format(p=2, w="xã Tân Hội, tỉnh Đồng Tháp"), place="xã Tân Thuận Đông, tỉnh Đồng Tháp")
    # C: tin không ghi xã; tài liệu OCR ghi sai 1 dấu/ký tự tên xã đã biết trong tỉnh -> chuẩn hoá
    _add(repo, "C", "Quyền sử dụng đất thửa đất số 3, tờ bản đồ số 3, diện tích 85m2, tỉnh Đồng Tháp",
         doc={"ward": "Xa Tan Hoi", "province": "Đồng Tháp", "methods": {"ward": "ocr", "province": "ocr"}})
    # D: tài liệu OCR ghi tên xã chưa từng gặp -> không dùng, chờ xác nhận
    _add(repo, "D", "Quyền sử dụng đất thửa đất số 4, tờ bản đồ số 3, diện tích 85m2, tỉnh Đồng Tháp",
         doc={"ward": "Xã Hòa Bìnhh Thạnh", "province": "Đồng Tháp", "methods": {"ward": "ocr", "province": "ocr"}})
    rebuild(repo)
    with repo.session() as s:
        get = lambda n: s.query(Property).filter(Property.parcel_no == str(n)).one()  # noqa: E731
        a, b, cc, d = get(1), get(2), get(3), get(4)
        assert (a.ward, a.province, a.address) == ("Xã Tân Hội", "Đồng Tháp", None)
        assert b.ward is None and b.province == "Đồng Tháp" and len(b.loc_candidates) == 2
        assert cc.ward == "Xã Tân Hội" and cc.field_sources.get("ward") == "tài liệu (OCR)"
        assert d.ward is None and any(x["ward"] == "Xã Hòa Bìnhh Thạnh" for x in d.loc_candidates)
        bid, did = b.id, d.id
    login(c, "nv1")
    page = c.get("/locations").text
    assert f"#{bid}" in page and f"#{did}" in page and "Xã Tân Thuận Đông" in page
    tok = csrf(c, "/locations")
    c.post(f"/p/{bid}/location", data={"csrf": tok, "ward": "Xã Tân Hội", "province": "Đồng Tháp"})
    with repo.session() as s:
        assert s.get(Property, bid).eff("ward") == "Xã Tân Hội"
    assert f"#{bid}" not in c.get("/locations").text
