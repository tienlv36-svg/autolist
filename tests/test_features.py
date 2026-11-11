"""Bộ lọc đã lưu + Telegram cá nhân, nhắc hạn, gợi ý gộp phiên, độ đầy đủ dữ liệu."""
import json
from datetime import datetime, timedelta

import httpx
import pytest

from auction_crawler.alerts import filters_from_query, run_alerts
from auction_crawler.config import Settings
from auction_crawler.models import AuctionNotice
from auction_crawler.realestate.db import CartItem, MergeSuggestion, Property, SavedSearch, Task, User
from auction_crawler.realestate.linker import rebuild
from auction_crawler.realestate.suggest import compute
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


def test_merge_suggestion_and_accept(env):  # noqa: F811
    repo, c = env
    fut, past = datetime.now() + timedelta(days=8), datetime(2026, 3, 1)
    # cùng tờ/thửa nhưng xã/phường ghi khác (tên cũ / mới) -> gom tự động không gộp; gợi ý gộp
    for sid, w, when, price in [("50", "phường Mỹ Phú", fut, 900_000_000), ("51", "xã Mỹ Tân", past, 1_000_000_000)]:
        t = TXT.format(p=345, a="123,4", w=w)
        repo.upsert(AuctionNotice(source="dgts", source_id=sid, title=t, asset_name=t, asset_owner="Ngân hàng X",
                                  starting_price=price, auction_date=when, registration_end=when - timedelta(days=3),
                                  asset_type="quyen_su_dung_dat", origin="ngan_hang_bao_dam", property_count=1))
    # khác thửa -> không gợi ý
    t = TXT.format(p=346, a="123,4", w="phường Mỹ Phú")
    repo.upsert(AuctionNotice(source="dgts", source_id="52", title=t, asset_name=t, starting_price=1_000_000_000,
                              auction_date=past, asset_type="quyen_su_dung_dat", origin="ngan_hang_bao_dam"))
    rebuild(repo)
    with repo.session() as s:
        a = s.query(Property).filter(Property.parcel_no == "345", Property.registration_end >= datetime.now()).one().id
        b = s.query(Property).filter(Property.parcel_no == "345", Property.id != a).one().id
    assert compute(repo) == 1
    assert compute(repo) == 0                                   # không tạo trùng
    with repo.session() as s:
        m = s.query(MergeSuggestion).one()
        assert (m.a_id, m.b_id) == (a, b) and "cùng tờ 12 thửa 345" in m.reason and "cùng diện tích" in m.reason
    login(c, "nv1")
    page = c.get("/merges").text
    assert f"#{a}" in page and f"#{b}" in page and "Gợi ý gộp <span class=\"cnt\">1</span>" in page
    tok = csrf(c, "/merges")
    c.post(f"/merges/{m.id}", data={"csrf": tok, "action": "accept"})
    with repo.session() as s:
        p = s.get(Property, a)
        assert p.session_count == 2 and p.price_first == 1_000_000_000 and p.discount_pct == 10.0
        assert s.get(Property, b) is None
        assert s.query(MergeSuggestion).one().status == "accepted"
    assert compute(repo) == 0


def test_reject_is_remembered(env):  # noqa: F811
    repo, c = env
    with repo.Session.begin() as s:
        ids = [p.id for p in s.query(Property).limit(2)]
        s.add(MergeSuggestion(a_id=ids[0], b_id=ids[1], reason="x", score=2))
    login(c)
    tok = csrf(c, "/merges")
    with repo.session() as s:
        mid = s.query(MergeSuggestion).one().id
    c.post(f"/merges/{mid}", data={"csrf": tok, "action": "reject"})
    assert "Không có gợi ý" in c.get("/merges").text and "#" in c.get("/merges?status=rejected").text


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
