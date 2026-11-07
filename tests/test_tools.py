from datetime import datetime

from auction_crawler.config import Settings
from auction_crawler.dedupe import find_duplicates
from auction_crawler.models import AuctionNotice
from auction_crawler.ocr import extract_prices
from auction_crawler.storage import NoticeRow, Repository

# Trích từ OCR thật của một PDF taisancong (bảng bị méo nhãn "Giá khởi điểm")
OCR_SAMPLE = """Điều 2. Thông tin về tài sản đấu giá:
4_ | Nơi có tài sản đầu giá cớ, tính Đồng Tháp.
432.000.000 đồng (Bằng chữ: Bốn trăm ba
Si, 5226055 mươi hai triệu đông). Thời gian cho thuê là 24
Tiẫn đX¿ rước 86.000.000 đồng (Bằng chữ: Tám mươi sáu
ă h 100.000 đồng/hồ sơ (Bằng chữ: Một trăm nghìn"""


def test_extract_prices_from_garbled_ocr():
    # nhãn "Giá khởi điểm" bị OCR làm méo -> mặc định KHÔNG đoán giá khởi điểm
    assert extract_prices(OCR_SAMPLE) == {"deposit": 86_000_000, "dossier_fee": 100_000}
    assert extract_prices(OCR_SAMPLE, heuristic=True)["starting_price"] == 432_000_000


def test_extract_prices_labeled():
    t = "Giá khởi điểm: 1.200.000.000 đồng. Tiền đặt trước: 240.000.000 đồng. Tiền mua hồ sơ: 500.000 đồng"
    assert extract_prices(t) == {"starting_price": 1_200_000_000, "deposit": 240_000_000, "dossier_fee": 500_000}


def test_dedupe_across_sources(tmp_path):
    repo = Repository(Settings(db_url=f"sqlite:///{tmp_path}/d.db").db_url)
    repo.init_db()
    when = datetime(2026, 11, 18, 9, 30)
    for src, sid, org, title in [
        ("dgts", "1", "Công ty Đấu giá hợp danh Vạn Thành", "Thanh lý 4 xe ôtô Ford Mondeo Toyota Camry của Phân hiệu Học viện Hành chính"),
        ("taisancong", "2", "Công ty Đấu giá Hợp danh Vạn Thành", "Đấu giá thanh lý 4 xe ôtô của Phân hiệu Học viện Hành chính và Quản trị công"),
        ("taisancong", "3", "Công ty Đấu giá Hợp danh Vạn Thành", "Đấu giá quyền sử dụng đất khu dân cư phường An Lạc"),
    ]:
        repo.upsert(AuctionNotice(source=src, source_id=sid, title=title, auction_org=org, auction_date=when))
    assert find_duplicates(repo) == 2
    with repo.session() as s:
        g = {r.source_id: r.dup_group for r in s.query(NoticeRow)}
    assert g["1"] == g["2"] is not None and g["3"] is None
