import pytest


@pytest.fixture(autouse=True)
def _no_real_ward_map(tmp_path_factory, monkeypatch):
    """Bài kiểm tra không dùng bảng xã cũ -> mới thật (data/ward_mapping.csv trên máy chủ); bài nào cần thì tự đặt."""
    from auction_crawler.realestate import wardmap
    monkeypatch.setattr(wardmap, "DEFAULT_PATH", tmp_path_factory.getbasetemp() / "no_ward_mapping.csv")
