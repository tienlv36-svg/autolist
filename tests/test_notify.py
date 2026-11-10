import json
from datetime import datetime

import httpx
import pytest

from auction_crawler import notify, scheduler
from auction_crawler.config import Settings
from auction_crawler.storage import Repository


@pytest.fixture
def settings(tmp_path, monkeypatch):
    s = Settings(db_url=f"sqlite:///{tmp_path}/n.db", raw_cache_dir=None)
    monkeypatch.setattr(Settings, "path", lambda self, p: tmp_path / p)
    return s


def tg_transport(sent: list):
    def handler(req: httpx.Request) -> httpx.Response:
        method = req.url.path.rsplit("/", 1)[-1]
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {"username": "hangdg_bot"}})
        if method == "getUpdates":
            return httpx.Response(200, json={"ok": True, "result": [
                {"update_id": 1, "my_chat_member": {"chat": {"id": -100123, "type": "supergroup", "title": "Nhóm đấu giá"}}},
                {"update_id": 2, "message": {"chat": {"id": -100123, "type": "supergroup", "title": "Nhóm đấu giá"}}},
            ]})
        if method == "sendMessage":
            sent.append(json.loads(req.content))
            return httpx.Response(200, json={"ok": True, "result": {}})
        return httpx.Response(404, json={"ok": False, "description": "not found"})
    return httpx.MockTransport(handler)


def test_not_configured_is_silent(settings):
    assert notify.send(settings, "x") is False


def test_send_and_split(settings):
    sent = []
    notify.save_config(settings, "TOKEN", "-100123")
    assert notify.is_configured(settings)
    assert notify.send(settings, "a" * 9000, transport=tg_transport(sent))
    assert len(sent) == 3 and sent[0]["chat_id"] == "-100123" and sent[0]["parse_mode"] == "HTML"


def test_discover_chats():
    chats = notify.discover_chats("T", transport=tg_transport([]))
    assert chats == [{"id": "-100123", "type": "supergroup", "name": "Nhóm đấu giá"}]


def test_send_error_never_raises(settings):
    notify.save_config(settings, "TOKEN", "1")
    bad = httpx.MockTransport(lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"}))
    assert notify.send(settings, "x", transport=bad) is False


def test_report_format(settings):
    repo = Repository(settings.db_url)
    repo.init_db()
    rep = {"started": datetime(2026, 11, 11, 2, 0), "minutes": 35.2, "warnings": [],
           "sources": {"dgts": {"ok": True, "found": 500, "inserted": 1234, "updated": 5, "errors": 0},
                       "taisancong": {"ok": False, "error": "ConnectError('timeout, retry')"}},
           "steps": {"re-build": {"ok": True}}}
    txt = scheduler.format_report(settings, repo, rep)
    assert txt.startswith("❌ <b>Thu thập 02:00 11/11</b>")
    assert "<b>1.234</b> tin mới" in txt and "taisancong: <b>THẤT BẠI</b>" in txt
    assert "timeout, retry" in txt          # dấu phẩy trong thông báo lỗi giữ nguyên


def test_zero_found_warns(settings, monkeypatch):
    repo = Repository(settings.db_url)
    repo.init_db()

    class St:
        found = inserted = updated = errors = 0
    monkeypatch.setattr(scheduler, "crawl_source", lambda *a, **k: St())
    monkeypatch.setattr(scheduler, "all_sources", lambda: ["dgts"])
    import auction_crawler.pipeline as pl
    import auction_crawler.realestate.linker as lk
    monkeypatch.setattr(pl, "tag_official_types", lambda *a, **k: {})
    monkeypatch.setattr(lk, "rebuild", lambda *a, **k: {})
    sent, backups = [], []
    monkeypatch.setattr(scheduler, "send", lambda s, t: sent.append(t) or True)
    monkeypatch.setattr(scheduler, "run_backup", lambda s: backups.append(1) or {"ok": True})
    monkeypatch.setattr(scheduler, "_docs_then_rebuild", lambda s, r: None)
    rep = scheduler.run_once(settings, repo)
    assert "không đọc được tin nào" in rep["text"] and rep["text"].startswith("⚠️") and sent
    assert backups == [1]                     # sao lưu ngay sau mỗi lượt


def test_report_docs_and_backup_failure(settings):
    from auction_crawler.attachments import DocStats
    repo = Repository(settings.db_url)
    repo.init_db()
    ds = DocStats(notices=120, files=300, bytes=50 * 1048576, ocr_files=40, with_info=75,
                  stopped="hết thời gian của lượt – đọc tiếp ở lượt sau", details=["còn 9.000 tin chưa đọc file"])
    rep = {"started": datetime(2026, 11, 11, 12, 0), "minutes": 300, "warnings": [], "sources": {},
           "steps": {"docs": {"ok": True, "result": ds}}, "backup": {"ok": False, "error": "disk full"}}
    txt = scheduler.format_report(settings, repo, rep)
    assert "File đính kèm: đọc 120 tin, lưu 300 file (50 MB, OCR 40), có số liệu cho <b>75</b>" in txt
    assert "còn 9.000 tin chưa đọc file" in txt and "Sao lưu sau lượt quét LỖI: disk full" in txt


def test_run_lock_blocks_second_run(settings):
    with scheduler.run_lock(settings):
        with pytest.raises(scheduler.AlreadyRunning):
            with scheduler.run_lock(settings):
                pass


def test_report_backup_line(settings):
    repo = Repository(settings.db_url)
    repo.init_db()
    base = {"started": datetime(2026, 11, 11, 2, 0), "minutes": 1, "warnings": [], "steps": {},
            "sources": {"dgts": {"ok": True, "found": 500, "inserted": 1, "updated": 0, "errors": 0}}}
    assert "Chưa có bản sao lưu nào" in scheduler.format_report(settings, repo, dict(base, warnings=[]))
    (settings.path("data")).mkdir(parents=True, exist_ok=True)
    settings.path("data/.last_backup.json").write_text(
        json.dumps({"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "size": "85M", "offsite": True}))
    txt = scheduler.format_report(settings, repo, dict(base, warnings=[]))
    assert "VPS + Google Drive" in txt and txt.startswith("✅")
