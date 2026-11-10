# auction-crawler

> 🚀 **Cài lên VPS Vietnix + hangdg.com:** [docs/CAI_DAT_HANGDG.md](docs/CAI_DAT_HANGDG.md)
> · **Cập nhật Đợt 1** (Telegram, Google Drive, khoá SSH): [docs/CAP_NHAT_DOT_1.md](docs/CAP_NHAT_DOT_1.md)
> · **Quy ước phiên, giá, % giảm, quét lịch sử giá:** [docs/QUY_UOC_GIA_PHIEN.md](docs/QUY_UOC_GIA_PHIEN.md)
> · **Điều khiển VPS bằng Claude (Remote Control):** [docs/CLAUDE_TREN_VPS.md](docs/CLAUDE_TREN_VPS.md)
>
> 📘 **Hướng dẫn chi tiết từng bước** (cài máy chủ, chạy tự động, HTTPS, sao lưu, hướng dẫn sử dụng cho nhân viên):
> [docs/HUONG_DAN.md](docs/HUONG_DAN.md). **Cài trên VPS (chưa có tên miền):** [docs/HUONG_DAN_VPS.md](docs/HUONG_DAN_VPS.md)
> – script cài tự động `deploy/install-vps.sh`, lấy dữ liệu lần đầu `deploy/first-load.sh`.

Thu thập, phân loại và thống kê tin đăng đấu giá tài sản từ 2 nguồn (cấu trúc đã kiểm chứng 07/11/2026):

| Nguồn | Mã | Cách lấy dữ liệu | Quy mô |
|---|---|---|---|
| Cổng ĐGTS quốc gia – Bộ Tư pháp | `dgts` | API JSON công khai mà trang dùng (`/portal/search/auction-notice`, `/portal/propertyInfo`) | ~657.000 thông báo, ~5.000 mới/tuần |
| Tài sản công – Bộ Tài chính | `taisancong` | HTML render sẵn, phân trang `&BRSR=<offset>` | ~35.400 tin, 20 tin/trang |

Dữ liệu thu được mỗi tin: tên tài sản, người có tài sản (+ địa chỉ), tổ chức đấu giá, nơi có tài sản,
địa điểm đấu giá, giá khởi điểm, tiền đặt trước, tiền hồ sơ, ngày đăng, thời gian đăng ký, thời gian
đấu giá, danh sách tài sản con (dgts), file đính kèm (taisancong), tỉnh/thành (34 tỉnh mới),
loại tài sản, nguồn gốc tài sản, loại tài sản chính thức (dgts), nhóm tin trùng giữa 2 nguồn.

> taisancong **không đăng giá** trên trang, giá chỉ có trong PDF đính kèm (thường là bản scan)
> → lệnh `ocr-prices` đọc bằng OCR tiếng Việt, cột "Nguồn giá" = `pdf-ocr` để phân biệt với giá chính thức.

## Kiến trúc

```
config/sources/*.yaml   config/categories.yaml
        │                        │
Fetcher ─► Source.iter_pages ─► Source.enrich (song song) ─► build_notice ─► Repository ─► stats/export
(httpx, retry,  (dgts: API JSON;     (dgts: propertyInfo;      chuẩn hoá tiền/ngày/   SQLite/Postgres   Excel/CSV
 giới hạn tốc độ  taisancong: HTML)   taisancong: trang HTML)   tỉnh + phân loại       upsert, lịch sử
 dùng chung)
                         + tag-types (loại TS chính thức) · ocr-prices (giá từ PDF) · dedupe (gộp trùng)
```

```
src/auction_crawler/
  sources/dgts.py        adapter API dgts (tài liệu endpoint trong docstring)
  sources/taisancong.py  adapter HTML taisancong
  sources/base.py        lớp nguồn chung điều khiển bằng YAML (thêm nguồn mới dễ dàng)
  sources/extract.py     trích theo CSS / theo nhãn "Giá khởi điểm: ..." / JSON path
  normalize.py           "1,5 tỷ" → 1500000000; "09 giờ, ngày 25/11/2026" → datetime; tỉnh cũ → 34 tỉnh mới
  classifier.py          phân loại từ khoá có trọng số theo trường (loại tài sản + nguồn gốc)
  ocr.py                 đọc giá từ PDF (pypdf / Tesseract)
  dedupe.py              phát hiện cùng cuộc đấu giá đăng ở 2 nguồn
  storage.py             bảng notices, notice_assets, crawl_runs; tự thêm cột khi nâng cấp
  pipeline.py            crawl tăng dần, backfill theo ngày, enrich, tag-types, ocr, reclassify
  stats.py               thống kê pandas → Excel nhiều sheet / CSV
  inspector.py, cli.py, scheduler.py
tools/probe_browser.py   dò trang bằng Chromium + ghi lại XHR/JSON (cách đã dùng để tìm API dgts)
tools/check_sources.py   kiểm tra selector/API còn chạy (phát hiện web đổi giao diện), exit≠0 nếu hỏng
tests/                   25 test, dùng dữ liệu thật đã lưu (không cần mạng)
```

## Cài đặt

```bash
make install                 # .venv + thư viện
make install-ocr             # (tuỳ chọn) OCR giá từ PDF: tesseract tiếng Việt + poppler + pypdf
make install-browser         # (tuỳ chọn) Playwright cho tools/probe_browser.py
```

## Sử dụng

```bash
.venv/bin/auction crawl                         # tăng dần cả 2 nguồn (dừng khi gặp trang toàn tin cũ)
.venv/bin/auction crawl -s dgts --since 2026-10-01   # lấy lại theo khoảng ngày (có chi tiết)
.venv/bin/auction stats --from 2026-11-01
.venv/bin/auction export -f xlsx                # data/exports/dau_gia_YYYYmmdd_HHMM.xlsx
.venv/bin/auction schedule                      # chạy nền: crawl → tag-types → ocr → dedupe → re-build, mỗi ngày 2:00
```

### Lấy dữ liệu lịch sử lớn (backfill) nhanh

```bash
# 1) Chỉ danh sách: ~1.315 request cho toàn bộ 657k tin dgts (500 tin/request, ~3-4 giây/request)
.venv/bin/auction crawl -s dgts --since 2025-01-01 --no-detail -p 2000
.venv/bin/auction crawl -s taisancong --no-detail -p 1800
# 2) Bổ sung chi tiết (giá, tiền đặt trước, nơi có TS) dần dần, mới nhất trước - chạy được nhiều lần
.venv/bin/auction enrich -s dgts --limit 20000
.venv/bin/auction enrich -s taisancong --limit 5000
# 3) Gắn loại tài sản chính thức (16 loại theo Luật ĐGTS) - rất nhanh, ~150 request
.venv/bin/auction tag-types
# 4) Giá từ PDF cho taisancong (~13 giây/tin) và gộp trùng
.venv/bin/auction ocr-prices -n 500
.venv/bin/auction dedupe
```

Tốc độ đo thực tế (delay mặc định, lịch sự với máy chủ): danh sách dgts ~1.000 tin / 12 giây;
chi tiết dgts ~1,7 tin/giây (3 luồng); taisancong ~1 tin/giây; tuần ~5.000 tin mới dgts ≈ 50 phút.
Chỉnh `http.delay_seconds` / `http.concurrency` trong `config/sources/*.yaml`.

### Phân loại
- `config/categories.yaml`: 13 loại tài sản, 6 nhóm nguồn gốc; trọng số theo trường (nguồn gốc dựa chủ yếu
  vào "người có tài sản"). Trên mẫu 1.100 tin thật: "Khác" 3,4% (loại TS), ~0% (nguồn gốc).
- Soát và tinh chỉnh: `auction eval-classify -n 30` (in mẫu tin nhóm "Khác"), sửa YAML, `auction reclassify`.
- dgts còn có loại chính thức của Bộ Tư pháp (sheet "Loại TS chính thức") sau `tag-types`.

### Excel xuất ra
Sheet: Theo nguồn · Loại TS chính thức · Theo loại tài sản · Theo nguồn gốc · Theo tỉnh · Tỉnh × Loại ·
Theo tháng · Tháng × Loại · Top tổ chức ĐG · Top người có TS · Chi tiết. Các sheet tổng hợp
(trừ "Theo nguồn") đã loại tin trùng giữa 2 nguồn.

## Ứng dụng quản lý tài sản BĐS đấu giá (web)

Lọc riêng tin bất động sản (bán, cho thuê, bán khoản nợ có tài sản bảo đảm là BĐS), gom các thông báo của
**cùng một tài sản** thành các phiên đấu giá, và cung cấp giao diện làm việc nhóm.

```bash
.venv/bin/auction re-build                        # lọc tin BĐS + trích thông số + gom phiên (chạy sau mỗi lần crawl)
.venv/bin/auction enrich -s dgts --realestate -n 5000   # lấy giá/tiền đặt trước cho tin BĐS (ưu tiên TS nhiều phiên)
.venv/bin/auction user-add admin --name "Quản trị" --admin
.venv/bin/auction web --host 0.0.0.0 --port 8000  # http://<máy chủ>:8000
```

**Danh sách** – thẻ tài sản: tổng DT đất, DT sàn, nhãn đã xác thực, giá hiện tại, hạn đăng ký (đếm ngược),
mức ưu tiên, % giảm so với phiên 1, tờ/thửa hoặc địa chỉ. Bộ lọc: chủ tài sản (ngân hàng / thi hành án /
cơ quan quản lý / tịch thu / phá sản / DN-cá nhân), hình thức (bán / cho thuê / khoản nợ), loại BĐS,
tỉnh, xã/phường nơi có tài sản, khoảng giá (tỷ), khoảng diện tích, ưu tiên, xác thực, còn hạn đăng ký,
đã giảm giá, nhiều phiên, việc được giao cho tôi; sắp xếp theo hạn đăng ký / giá / % giảm / ưu tiên...

**Chi tiết** – tổng DT đất, DT đất ở, DT đất khác, DT sàn, số tờ, số thửa, chiều ngang, chiều dài,
xã/phường, địa chỉ: giá trị **tự động** trích từ văn bản, sửa được bằng **nhập tay** (ưu tiên khi hiển thị
và lọc, giữ nguyên khi chạy lại); bảng các phiên (giá phiên 1, phiên gần nhất, % giảm, link nguồn, tách
phiên gộp nhầm / gộp với tài sản khác); thư mục ảnh/video/tài liệu (tải lên, phân thư mục, xem ảnh, phát
video, kèm **tài liệu gốc** quy chế/thông báo lấy từ website nguồn); **lịch sử xem tài liệu** (ai, xem/tải,
lúc nào); **nhận xét** (lưu tài khoản + thời gian, sửa/xoá của mình); **phân loại ưu tiên** thủ công;
**xác thực** (ai, lúc nào); **giao việc** giữa các tài khoản (người nhận, hạn, trạng thái) + trang
"Việc của tôi"; **nhật ký thao tác**.

Gom phiên: cùng tỉnh + xã/phường + (tờ, thửa) đầu tiên, hoặc cùng chủ tài sản + mô tả trùng khớp (tin đấu
giá lại thường giữ nguyên mô tả), hoặc cùng cuộc đấu giá đăng ở 2 nguồn. Gộp/tách thủ công luôn được tôn trọng.

File tải lên lưu ở `data/media/<id tài sản>/`; khoá ký cookie ở `data/secret.key` (hoặc biến `AUCTION_SECRET`).
Khi đưa lên mạng nội bộ/Internet nên đặt sau HTTPS (nginx/Caddy) và sao lưu định kỳ `data/`.

## Bảo trì
- `make check` (tools/check_sources.py) định kỳ; trả mã lỗi khi một nguồn hỏng → gắn vào cron/CI để cảnh báo.
- Khi web đổi giao diện: `auction probe <url>` hoặc `tools/probe_browser.py <url>` → sửa YAML/adapter →
  `auction test-selectors taisancong <file.html>` → lưu HTML mới vào `tests/fixtures/` và chạy `make test`.
- HTML/JSON gốc lưu ở `data/raw/` để parse lại mà không phải tải lại.
- PostgreSQL: `pip install -e .[postgres]`, `AUCTION_DB_URL=postgresql+psycopg://...`.
- Dữ liệu thu thập là thông tin công khai; giữ tốc độ thấp, chạy ngoài giờ cao điểm.
