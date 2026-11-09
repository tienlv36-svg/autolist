# Hướng dẫn cài đặt, vận hành và sử dụng

> **Cài trên VPS chưa có tên miền?** Làm theo [HUONG_DAN_VPS.md](HUONG_DAN_VPS.md) – từng bước, có script cài tự động.

Tài liệu gồm 3 phần:

- **Phần A – Cài đặt máy chủ** (cho người phụ trách kỹ thuật, làm 1 lần)
- **Phần B – Vận hành** (lấy dữ liệu, chạy tự động, sao lưu, cập nhật, xử lý sự cố)
- **Phần C – Hướng dẫn sử dụng** (cho mọi nhân viên dùng ứng dụng web)

Các lệnh trong tài liệu đã được chạy thử trên bản cài mới từ repo này (11/2026).

---

## Phần A – Cài đặt máy chủ

### A1. Chuẩn bị

| Hạng mục | Khuyến nghị |
|---|---|
| Máy chủ | VPS/máy chủ **Ubuntu 22.04 hoặc 24.04**, 2 vCPU, 4 GB RAM, ổ cứng 40 GB trở lên (nhiều ảnh/video thì cần nhiều hơn) |
| Mạng | Truy cập được `dgts.moj.gov.vn` và `taisancong.vn` (máy chủ đặt ở Việt Nam là tốt nhất) |
| Tên miền | Tuỳ chọn, ví dụ `daugia.congty.vn`, nếu muốn truy cập qua Internet có HTTPS |
| Phần mềm | Python 3.10 trở lên, git (Ubuntu 22.04/24.04 có sẵn Python phù hợp) |

> Dùng Windows? Xem mục **A8**. Khuyến nghị vẫn là máy chủ Ubuntu vì dễ chạy tự động 24/7.

### A2. Cài phần mềm hệ thống

Đăng nhập máy chủ bằng SSH rồi chạy:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
```

Tuỳ chọn – cài OCR để đọc giá từ PDF của taisancong.vn (trang này không đăng giá trên web):

```bash
sudo apt install -y tesseract-ocr tesseract-ocr-vie poppler-utils
```

### A3. Tạo tài khoản hệ thống và tải mã nguồn

Ứng dụng chạy dưới tài khoản riêng `auction`, cài tại `/opt/autolist`:

```bash
sudo useradd --system --create-home --shell /bin/bash auction
sudo mkdir -p /opt/autolist && sudo chown auction:auction /opt/autolist
sudo -u auction git clone https://github.com/tienlv36-svg/autolist.git /opt/autolist
```

Repo đang để **Private** nên git sẽ hỏi đăng nhập. Dùng tên GitHub và một *Personal access token*
(GitHub → Settings → Developer settings → Personal access tokens → Fine-grained, quyền
*Contents: Read* cho repo `autolist`) làm mật khẩu.

### A4. Cài thư viện Python

```bash
cd /opt/autolist
sudo -u auction python3 -m venv .venv
sudo -u auction .venv/bin/pip install -e ".[ocr]"
```

(Mất khoảng 20–60 giây. Bỏ `[ocr]` nếu không dùng OCR.)

Kiểm tra cài đặt – toàn bộ test phải báo `passed`:

```bash
sudo -u auction .venv/bin/pip install pytest && sudo -u auction .venv/bin/pytest -q
```

Từ đây trở đi, các lệnh `auction ...` đều chạy trong thư mục `/opt/autolist` dưới dạng:

```bash
sudo -u auction /opt/autolist/.venv/bin/auction <lệnh>
```

Để gõ ngắn hơn, có thể chuyển sang tài khoản `auction` một lần rồi gõ trực tiếp:

```bash
sudo -iu auction
cd /opt/autolist && source .venv/bin/activate
auction --help
```

### A5. Cấu hình

File `config/settings.yaml` – các mục hay chỉnh:

```yaml
db_url: sqlite:///data/auction.db   # CSDL (SQLite là đủ cho vài trăm nghìn tin, 5-20 người dùng)
raw_cache_dir: data/raw             # lưu bản gốc trang đã tải; đặt "" để TẮT (khuyên tắt khi chạy thật)
crawl:
  max_pages: 50                     # số trang tối đa mỗi lần quét tăng dần
schedule:
  cron: "0 2 * * *"                 # chạy tự động mỗi ngày lúc 2:00 sáng (giờ Việt Nam)
  ocr_limit: 0                      # >0: mỗi lượt OCR giá cho N tin taisancong (mỗi tin ~13 giây)
```

> **Quan trọng:** `data/raw` lưu bản gốc mọi trang/JSON đã tải. Khi lấy toàn bộ dữ liệu, thư mục này
> có thể lên vài GB. Khi chạy thật nên đặt `raw_cache_dir: ""`, hoặc dọn định kỳ (mục B5).

Tốc độ tải từng nguồn nằm trong `config/sources/dgts.yaml` và `taisancong.yaml`
(`delay_seconds`, `concurrency`). Giữ như mặc định để không gây tải cho cổng thông tin nhà nước.

Muốn dùng PostgreSQL thay SQLite (khi có trên ~20 người dùng đồng thời): cài thêm
`pip install -e ".[postgres]"` và đặt `db_url: postgresql+psycopg://user:matkhau@localhost:5432/auction`.

### A6. Tạo tài khoản quản trị và chạy thử web

```bash
cd /opt/autolist
sudo -u auction .venv/bin/auction user-add admin --name "Quản trị viên" --admin
```

(Lệnh sẽ hỏi mật khẩu 2 lần.) Chạy thử:

```bash
sudo -u auction .venv/bin/auction web --host 0.0.0.0 --port 8000
```

Mở trình duyệt vào `http://<IP-máy-chủ>:8000`, đăng nhập `admin`. Danh sách lúc này còn trống,
xem **B1** để lấy dữ liệu. Nhấn `Ctrl+C` để dừng, rồi làm tiếp A7 để chạy nền.

### A7. Chạy nền 24/7 và bật HTTPS

**1) Dịch vụ tự khởi động** (web + thu thập tự động):

```bash
sudo cp /opt/autolist/deploy/auction-web.service /opt/autolist/deploy/auction-scheduler.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now auction-web auction-scheduler
```

Kiểm tra trạng thái:

```bash
systemctl status auction-web auction-scheduler
```

**2) HTTPS với tên miền** (khuyên dùng nếu truy cập qua Internet). Trỏ bản ghi DNS `A` của tên miền về IP
máy chủ, mở cổng 80/443, rồi cài Caddy (Ubuntu 24.04 có sẵn gói `caddy`; Ubuntu 22.04 xem
https://caddyserver.com/docs/install):

```bash
sudo apt install -y caddy
```

Sửa tên miền trong `deploy/Caddyfile` rồi áp dụng:

```bash
sudo cp /opt/autolist/deploy/Caddyfile /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

Caddy tự xin chứng chỉ HTTPS. Truy cập `https://daugia.congty.vn`. Dịch vụ web chỉ nghe ở `127.0.0.1:8000`
nên không ai truy cập thẳng được cổng 8000.

**3) Tường lửa** (nếu dùng ufw):

```bash
sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable
```

Chỉ dùng trong mạng nội bộ, không có tên miền? Bỏ bước 2, sửa `--host 127.0.0.1` thành
`--host 0.0.0.0` trong `/etc/systemd/system/auction-web.service`, chạy `sudo systemctl daemon-reload &&
sudo systemctl restart auction-web`, rồi truy cập `http://<IP-nội-bộ>:8000`.

### A8. Cài trên Windows (máy văn phòng)

1. Cài **Python 3.12** từ https://www.python.org/downloads/ (tích *Add python.exe to PATH*) và **Git** từ https://git-scm.com.
2. Mở **PowerShell**:
   ```powershell
   git clone https://github.com/tienlv36-svg/autolist.git C:\autolist
   cd C:\autolist
   python -m venv .venv
   .venv\Scripts\pip install -e .
   .venv\Scripts\auction user-add admin --name "Quản trị viên" --admin
   .venv\Scripts\auction web --host 0.0.0.0 --port 8000
   ```
3. Thu thập tự động: mở *Task Scheduler* → *Create Basic Task* → chạy `C:\autolist\.venv\Scripts\auction.exe`,
   tham số `crawl`, *Start in* `C:\autolist`, lặp hằng ngày lúc 2:00; tạo thêm một task tương tự với tham số `re-build`
   chạy sau đó 1 giờ. Web cần một cửa sổ PowerShell luôn mở, hoặc dùng NSSM (https://nssm.cc) để chạy như dịch vụ.
4. OCR trên Windows: cài Tesseract (bản UB Mannheim, chọn thêm ngôn ngữ *Vietnamese*) và Poppler, rồi thêm thư mục
   `bin` của cả hai vào PATH.

---

## Phần B – Vận hành

### B1. Lấy dữ liệu lần đầu (backfill)

Làm theo thứ tự. Các lệnh dài nên chạy trong `tmux` để không bị ngắt khi đóng SSH
(`sudo apt install -y tmux`, gõ `tmux` để mở, `Ctrl+B` rồi `D` để tách, `tmux attach` để quay lại).

```bash
sudo -iu auction
cd /opt/autolist && source .venv/bin/activate
```

| Bước | Lệnh | Thời gian ước tính | Ý nghĩa |
|---|---|---|---|
| 1 | `auction crawl -s dgts --since 2025-11-01 --no-detail -p 3000` | 1–2 giờ | Danh sách dgts 12 tháng (500 tin/request) |
| 2 | `auction crawl -s taisancong --no-detail --full -p 2000` | 1–2 giờ | Danh sách taisancong |
| 3 | `auction dedupe` | 1 phút | Đánh dấu cùng cuộc đấu giá đăng ở 2 nguồn |
| 4 | `auction re-build` | 1–5 phút | Lọc tin BĐS, trích thông số, gom phiên |
| 5 | `auction enrich -s dgts --realestate -n 20000` | 4–12 giờ | Lấy **giá, tiền đặt trước, nơi có tài sản** cho tin BĐS (ưu tiên tài sản nhiều phiên). Chạy lại nhiều lần cho đến khi hết |
| 6 | `auction enrich -s taisancong --realestate -n 5000` | 1–2 giờ | Chi tiết taisancong (ngày đăng, địa chỉ, file PDF) |
| 7 | `auction ocr-prices -n 500` | ~2 giờ / 500 tin | Tuỳ chọn – đọc giá từ PDF taisancong |
| 8 | `auction tag-types` | vài phút | Gắn loại tài sản chính thức (dgts) |
| 9 | `auction re-build` | 1–5 phút | Tính lại giá phiên 1 / phiên gần nhất / % giảm |

Có thể dùng ứng dụng web ngay sau bước 4; giá sẽ xuất hiện dần khi bước 5 chạy (sau mỗi lần `re-build`).
Thời gian phụ thuộc tốc độ phản hồi của dgts (khoảng 0,5–1,7 tin/giây).

### B2. Chạy tự động hằng ngày

Dịch vụ `auction-scheduler` (mục A7) chạy một lượt mỗi ngày lúc 2:00 sáng (đổi giờ: sửa `schedule.cron` trong `config/settings.yaml`):
quét tin mới cả 2 nguồn (kèm chi tiết) → gắn loại tài sản chính thức → OCR (nếu bật `ocr_limit`) →
đánh dấu tin trùng → dựng lại tài sản BĐS. Người dùng không cần làm gì thêm.

Xem nhật ký:

```bash
journalctl -u auction-scheduler -n 100 --no-pager
journalctl -u auction-web -f
```

### B3. Quản lý tài khoản người dùng

Cách dễ nhất: đăng nhập web bằng tài khoản quản trị → menu **Tài khoản**. Tại đây có thể tạo tài khoản,
đặt lại mật khẩu, đổi quyền (Thành viên / Quản trị), khoá tài khoản nghỉ việc (bỏ tích *Hoạt động*;
nhận xét và lịch sử của người đó vẫn được giữ). Hoặc dùng dòng lệnh:

```bash
auction user-add lan --name "Nguyễn Thị Lan"
```

Quyền **Quản trị** được thêm: quản lý tài khoản, xoá nhận xét/file của người khác, xem mọi việc được giao.

### B4. Sao lưu và khôi phục

Sao lưu gồm CSDL (an toàn khi đang chạy), toàn bộ file tải lên và khoá đăng nhập; giữ 14 bản gần nhất:

```bash
sudo -u auction /opt/autolist/deploy/backup.sh
```

Chạy tự động lúc 4:15 mỗi sáng (sau lượt thu thập 2:00): `sudo -u auction crontab -e` rồi thêm dòng

```
15 4 * * * /opt/autolist/deploy/backup.sh >> /opt/autolist/backups/backup.log 2>&1
```

Nên chép thư mục `/opt/autolist/backups` sang máy khác hoặc kho lưu trữ đám mây định kỳ (rclone, Google Drive...).

**Khôi phục** từ một bản sao lưu:

```bash
sudo systemctl stop auction-web auction-scheduler
cd /opt/autolist && sudo -u auction tar -xzf backups/autolist_YYYYMMDD_HHMM.tar.gz -C /tmp
sudo -u auction cp /tmp/auction.db data/auction.db
sudo -u auction cp -r /tmp/media /tmp/secret.key data/
sudo systemctl start auction-web auction-scheduler
```

### B5. Dọn dung lượng

```bash
du -sh /opt/autolist/data/*                                     # xem thư mục nào lớn
find /opt/autolist/data/raw -type f -mtime +14 -delete          # xoá bản gốc trang đã tải > 14 ngày
```

Có thể thêm dòng `find ...` trên vào crontab giống mục B4.

### B6. Cập nhật phiên bản mới

```bash
cd /opt/autolist
sudo -u auction git pull
sudo -u auction .venv/bin/pip install -e ".[ocr]"
sudo systemctl restart auction-web auction-scheduler
```

CSDL tự thêm cột mới khi khởi động, không cần thao tác thêm. Nên chạy `backup.sh` trước khi cập nhật.

### B7. Xử lý sự cố thường gặp

| Hiện tượng | Nguyên nhân / cách xử lý |
|---|---|
| Không mở được web | `systemctl status auction-web`; xem lỗi bằng `journalctl -u auction-web -n 50` |
| Danh sách trống | Chưa chạy B1 (ít nhất bước 1 và 4) |
| Thẻ tài sản không có giá | Tin chưa được lấy chi tiết → chạy `auction enrich -s dgts --realestate` rồi `auction re-build` |
| Lấy dữ liệu báo lỗi / 0 tin | Website nguồn đổi giao diện hoặc chặn. Chạy `.venv/bin/python tools/check_sources.py` để biết nguồn nào hỏng; đổi cấu hình theo README mục *Bảo trì* |
| `database is locked` | Hai tiến trình ghi cùng lúc (ví dụ đang chạy `re-build` tay khi lịch tự chạy). Chạy lại lệnh sau ít phút |
| Hết dung lượng ổ | Mục B5; kiểm tra `data/media` (ảnh/video) và `backups/` |
| Quên mật khẩu admin | `auction user-add admin2 --name "Quản trị 2" --admin` để tạo tài khoản quản trị khác, rồi đặt lại mật khẩu trong menu Tài khoản |
| Mọi người bị đăng xuất | File `data/secret.key` bị đổi/xoá – khôi phục từ bản sao lưu |

---

## Phần C – Hướng dẫn sử dụng (cho nhân viên)

### C1. Đăng nhập

Mở địa chỉ do quản trị cung cấp (ví dụ `https://daugia.congty.vn`), nhập tên đăng nhập và mật khẩu.
Đổi mật khẩu: bấm tên của bạn ở góc phải trên cùng. Phiên đăng nhập giữ 14 ngày.

### C2. Danh sách tài sản

Mỗi thẻ là **một bất động sản** (có thể đã qua nhiều phiên đấu giá):

| Trên thẻ | Ý nghĩa |
|---|---|
| Nhãn *Bán tài sản / Cho thuê / Bán khoản nợ* | Hình thức |
| ✓ *Đã xác thực* | Đã có người đối chiếu thông tin với hồ sơ gốc |
| *Thấp / Trung bình / Cao / Rất cao* | Mức ưu tiên do nhóm tự đặt |
| Tờ … · Thửa … — Xã/phường, Tỉnh | Vị trí (nếu tin không có tờ/thửa thì hiện địa chỉ) |
| Số lớn màu xanh | **Giá hiện tại** = giá khởi điểm của phiên gần nhất |
| *−x% so phiên 1* | Mức giảm so với giá phiên đầu tiên |
| ⚠ *kiểm tra* | Gom phiên có dấu hiệu bất thường – cần xem lại (mục C5) |
| DT đất / DT sàn | Tổng diện tích đất / diện tích sàn |
| Hạn ĐK + nhãn màu | Hạn đăng ký: đỏ < 3 ngày, vàng < 7 ngày, xanh còn lâu, xám đã hết hạn |
| Dòng cuối bên phải | Loại chủ tài sản |

**Bộ lọc** (cột trái; trên điện thoại bấm *Bộ lọc* để mở):

- **Chủ tài sản:** Ngân hàng/TCTD, Thi hành án, Cơ quan quản lý nhà nước, Tịch thu, Phá sản, DN/cá nhân.
- **Hình thức** và **Loại BĐS** (Đất / Nhà + đất / Mặt bằng).
- **Tỉnh/thành phố** → sau đó chọn **Xã/phường** (danh sách tự hiện, kèm số tài sản mỗi xã).
- **Giá từ/đến** tính bằng **tỷ đồng** (gõ `0,5` = 500 triệu); **DT đất** tính bằng m².
- **Còn hạn đăng ký**, **Đã giảm giá**, **Đấu giá nhiều phiên**, **Được giao cho tôi**, **Mức ưu tiên**, **Xác thực**.
- Ô **Tìm kiếm**: tên tài sản, địa chỉ, tên chủ tài sản, hoặc gõ đúng **số thửa**.

Bấm **Lọc** để áp dụng, **Xoá lọc** để bỏ hết. **Sắp xếp** (góc phải): sắp hết hạn đăng ký, mới đăng,
giá, giảm nhiều nhất, ưu tiên, diện tích. Có thể lưu địa chỉ trang (bookmark) để mở lại đúng bộ lọc.

Gợi ý bộ lọc hay dùng – *tài sản ngân hàng ở Hà Nội đã giảm giá, còn hạn đăng ký*: chọn Chủ tài sản =
Ngân hàng, Tỉnh = Hà Nội, tích *Còn hạn đăng ký* và *Đã giảm giá*, sắp xếp *Giảm giá nhiều nhất*.

### C3. Trang chi tiết tài sản

**Đầu trang:** giá hiện tại, giá phiên 1, % giảm và số phiên, hạn đăng ký, ngày đấu giá, tiền đặt trước.
Bấm vào tiêu đề để xem đầy đủ khi bị cắt ngắn.

**Thông số tài sản:** tổng diện tích đất, diện tích đất ở, đất khác, diện tích sàn, số tờ, số thửa,
chiều ngang, chiều dài, xã/phường, địa chỉ.

- Nhãn **từ tin gốc** = thông tin được ghi rõ trong tin đăng (phần mềm chỉ tự điền khi có nhãn rõ ràng và
  chỉ có một giá trị). Ô ghi **— chưa có** = tin không ghi, hoặc ghi chưa đủ rõ (nhiều thửa, nhiều con số khác
  nhau...). Lý do để trống hiện trong khung vàng *“Để trống vì chưa đủ căn cứ”*.
- Bấm **Sửa / nhập tay** để điền giá trị đúng theo sổ đỏ, trích lục... (kể cả **giá hiện tại, giá phiên 1,
  tỉnh/thành**). Chữ xám trong ô là giá trị từ tin gốc; **để trống** = dùng lại giá trị đó. Giá trị nhập tay
  có nhãn **nhập tay**, được dùng khi lọc và tính % giảm, và **không bị ghi đè** khi phần mềm cập nhật.
- *Mô tả đầy đủ trong thông báo gần nhất*: nguyên văn tin và bảng các tài sản trong thông báo.

**Các phiên đấu giá:** mỗi dòng một phiên – ngày đấu giá, hạn đăng ký, giá khởi điểm, % so phiên 1,
link mở tin gốc (`dgts ↗` / `taisancong ↗`). “(2 tin)” nghĩa là nguồn đăng 2 thông báo cho cùng phiên.

### C4. Ưu tiên, xác thực, tài liệu, nhận xét, giao việc

- **Phân loại ưu tiên** (cột phải): bấm một mức – áp dụng ngay, ghi vào nhật ký.
- **Xác thực:** sau khi đối chiếu diện tích, tờ/thửa, giá với hồ sơ gốc, bấm **✓ Xác thực**. Hệ thống ghi
  người và thời gian xác thực; thẻ tài sản hiện nhãn ✓.
- **Thư mục hình ảnh, video, tài liệu:** chọn file (chọn được nhiều file một lúc, tối đa 1 GB/file),
  chọn thư mục (Hình ảnh, Video, Pháp lý, Hiện trạng, Định giá, Tài liệu) hoặc gõ tên thư mục mới, bấm
  **Tải lên**. Ảnh hiện dạng lưới (bấm để xem lớn), video phát ngay trên trang. Thư mục
  *Tài liệu nguồn* do hệ thống tự lấy từ website (quy chế, thông báo PDF) khi mở trang lần đầu.
  Chỉ người tải lên hoặc quản trị viên được xoá file.
- **Lịch sử xem tài liệu:** ai đã **xem** hoặc **tải** file nào, lúc nào (ảnh thu nhỏ trong lưới không tính).
- **Nhận xét:** ghi chú về hiện trạng, pháp lý, giá…; lưu tên tài khoản và thời gian. Sửa/xoá được nhận xét
  của mình (quản trị viên xoá được mọi nhận xét).
- **Giao việc:** bấm **+ Giao việc mới** → nhập việc cần làm, chọn người nhận, hạn hoàn thành, ghi chú.
  Người nhận thấy việc ở menu **Việc của tôi** và đổi trạng thái *Mới → Đang làm → Hoàn thành* (hoặc *Huỷ*).
  Việc quá hạn có nhãn đỏ. Trong menu *Việc của tôi* có các tab *Được giao cho tôi* / *Tôi đã giao*.
- **Nhật ký thao tác:** mọi thay đổi (sửa thông số, đổi ưu tiên, xác thực, tải file, giao việc, gộp/tách)
  kèm người thực hiện và thời gian.

### C5. Khi hệ thống gom phiên sai

Hệ thống tự gom các thông báo của cùng một tài sản (cùng tờ/thửa và xã/phường, hoặc cùng chủ tài sản với
mô tả trùng khớp). Cách xử lý khi gom sai:

- **Gộp nhầm** (trong bảng phiên có thông báo của tài sản khác – thường kèm nhãn ⚠): bấm **Tách** ở dòng đó.
  Thông báo được chuyển thành tài sản riêng.
- **Bị tách rời** (cùng một BĐS nhưng hiện thành 2 thẻ): mở một thẻ, nhập số **#id** của thẻ kia
  (số hiện cạnh nhãn ở đầu trang chi tiết) vào ô *Gộp vào #* và bấm **Gộp**. Nhận xét, file, việc giao
  của cả hai được gộp chung.

Lựa chọn gộp/tách thủ công được hệ thống ghi nhớ, không bị thay đổi ở các lần cập nhật sau.

### C6. Nguyên tắc dữ liệu

- Phần mềm **không suy luận**: thông tin chưa chắc chắn được để trống để người dùng nhập tay. Bảng chi tiết
  từng loại thông tin (khi nào tự điền, khi nào để trống) xem [HUONG_DAN_VPS.md – Nguyên tắc dữ liệu](HUONG_DAN_VPS.md#nguyên-tắc-dữ-liệu-chưa-chắc-chắn-thì-để-trống).
- Giá taisancong chỉ có trong PDF; phần mềm đọc bằng OCR và hiện làm **giá tham khảo** (khung xanh), không dùng
  để lọc – đối chiếu file trong *Tài liệu nguồn* rồi nhập tay vào ô giá.
- Luôn đối chiếu hồ sơ gốc trước khi ra quyết định, rồi bấm **✓ Xác thực** để cả nhóm biết.
- Chỉ có dữ liệu từ 2 nguồn công khai (dgts.moj.gov.vn, taisancong.vn).
