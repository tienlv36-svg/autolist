# CLAUDE.md – Vận hành phần mềm Đấu giá BĐS trên VPS hangdg.com

Bạn (Claude) đang chạy **trên VPS sản xuất** của phần mềm thu thập & quản lý tài sản đấu giá bất động sản,
được người dùng điều khiển từ xa (Remote Control). Người dùng là chủ hệ thống, giao tiếp **bằng tiếng Việt**,
không phải lập trình viên: giải thích ngắn gọn, dễ hiểu, nói rõ kết quả và việc cần họ quyết định.

## Hệ thống

| Thành phần | Vị trí / tên |
|---|---|
| Phần mềm đang chạy | `/opt/autolist` (chủ sở hữu: tài khoản hệ thống `auction`) |
| Môi trường Python | `/opt/autolist/.venv` – lệnh CLI: `/opt/autolist/.venv/bin/auction` |
| Cơ sở dữ liệu | `/opt/autolist/data/auction.db` (SQLite) |
| File tải lên | `/opt/autolist/data/media/` |
| File đính kèm của tài sản còn hạn (lưu vĩnh viễn) | `/opt/autolist/data/files/<nguồn>/<năm-tháng>/<mã tin>/` (+ `.txt` chữ đã đọc), bảng `notice_files` |
| Cấu hình | `/opt/autolist/config/settings.yaml`, nguồn: `config/sources/*.yaml`, phân loại: `config/categories.yaml` |
| Bí mật (KHÔNG in ra, KHÔNG gửi đi) | `data/secret.key`, `data/telegram.json`, `~auction/.config/rclone/rclone.conf` |
| Bản sao lưu | `/opt/autolist/backups/` (sau **mỗi** lượt thu thập 0:00 & 12:00, giữ 28 bản; + Google Drive nếu cấu hình). `data/files` không nằm trong bản nén (quá lớn); có file `data/.drive_files` thì đồng bộ dần lên Drive |
| Mã nguồn git (để cập nhật) | `/root/autolist` (clone từ GitHub `tienlv36-svg/autolist`) |
| Dịch vụ systemd | `auction-web` (web, 127.0.0.1:8000), `auction-scheduler` (lượt tự động 0:00 và 12:00), `caddy` (HTTPS hangdg.com), `fail2ban` |
| Web | https://hangdg.com |

Luồng dữ liệu mỗi lượt (0:00 và 12:00, `auction schedule` / `auction run-now`): thu thập tin mới 2 nguồn
(dgts.moj.gov.vn qua API JSON, taisancong.vn qua HTML) → gắn loại tài sản chính thức → OCR (nếu bật) → đánh dấu tin
trùng → gom phiên tài sản BĐS (`re-build`) → quét lịch sử giá cho tài sản còn hạn đăng ký → tải + lưu + đọc file
đính kèm của tài sản còn hạn đăng ký (tối đa `docs_minutes` phút; số liệu tài liệu được ưu tiên) → gom phiên lại → sao lưu →
báo cáo Telegram.

## Chạy lệnh đúng cách

- Lệnh phần mềm chạy **dưới tài khoản `auction`**, trong thư mục `/opt/autolist`:
  `sudo -u auction /opt/autolist/.venv/bin/auction <lệnh>`
- Lệnh chạy lâu (> vài phút: `crawl`, `enrich`, `history-scan`, `docs-fetch`, `run-now`, `re-build` trên dữ liệu lớn) → chạy trong
  **tmux** (`tmux new -d -s <tên> '<lệnh>'`) và báo người dùng cách theo dõi, không chạy chặn phiên.
- **Không chạy 2 tiến trình ghi CSDL cùng lúc.** Trước khi chạy lệnh ghi, kiểm tra `tmux ls` và
  `pgrep -af "auction (crawl|enrich|re-build|history-scan|docs-fetch|docs-reparse|run-now|schedule)"` / `pgrep -af first-load`.
  Lượt tự động và `first-load.sh` dùng chung khoá `data/.run.lock`.
- Đọc CSDL: `sqlite3 -readonly /opt/autolist/data/auction.db "<SELECT ...>"`. **Không** UPDATE/DELETE trực tiếp
  trừ khi người dùng yêu cầu rõ và đã sao lưu.

Các lệnh CLI hay dùng (`auction --help` để xem đủ):

| Lệnh | Việc |
|---|---|
| `run-now` | Chạy ngay 1 lượt như lịch tự động (kèm sao lưu + báo cáo Telegram) |
| `crawl [-s dgts\|taisancong] [--since YYYY-MM-DD] [--no-detail] [-p N]` | Thu thập |
| `enrich -s dgts --realestate -n N` | Lấy giá/tiền đặt trước/nơi có TS cho tin BĐS chưa có chi tiết |
| `re-build` | Lọc BĐS, trích thông số, gom phiên, tính giá phiên 1 / hiện tại / % giảm |
| `history-scan -n N` | Quét lịch sử giá (phiên cũ) cho tài sản còn hạn đăng ký |
| `docs-fetch -m PHÚT [-n N]` | Tải, lưu, đọc file đính kèm (còn hạn trước) rồi gom phiên lại |
| `docs-reparse` | Trích lại số liệu từ chữ đã lưu (không tải lại) rồi gom phiên lại |
| `dedupe`, `tag-types` | Tin trùng giữa 2 nguồn; loại tài sản chính thức (dgts) |
| `stats`, `export -f xlsx` | Thống kê nhanh; xuất Excel ra `data/exports/` |
| `user-add <tên> --name "<Họ tên>" [--admin]` | Tạo tài khoản web |
| `telegram-test`, `notify "<nội dung>"` | Thông báo Telegram |

Tiện ích: `deploy/backup.sh` (sao lưu ngay), `deploy/first-load.sh` (lấy dữ liệu lần đầu),
`deploy/harden-ssh.sh [--undo]` (chỉ đăng nhập SSH bằng khoá), `tools/check_sources.py` (kiểm tra nguồn còn đọc được).

Kiểm tra nhanh:
```bash
systemctl is-active auction-web auction-scheduler caddy fail2ban
journalctl -u auction-scheduler -n 50 --no-pager      # lượt tự động
journalctl -u auction-web -n 50 --no-pager            # web
tail -n 30 /opt/autolist/data/first-load.log          # lấy dữ liệu lần đầu
sqlite3 -readonly /opt/autolist/data/auction.db "select source,status,started_at,found,inserted,errors from crawl_runs order by id desc limit 10;"
df -h / ; ls -lh /opt/autolist/backups | tail -3
```

## Cập nhật phiên bản

Mã nguồn được phát triển ở nơi khác và đẩy lên GitHub. Trên VPS **không sửa code trong `/opt/autolist`** (sẽ bị
ghi đè và lệch với GitHub). Cập nhật:
```bash
cd /root/autolist && git pull && sudo bash deploy/install-vps.sh
```
Script giữ nguyên dữ liệu, tài khoản, `config/settings.yaml`, tên miền; tự khởi động lại dịch vụ. Chạy
`deploy/backup.sh` trước khi cập nhật. Không cập nhật khi đang có tiến trình ghi CSDL. Nếu người dùng muốn **thay
đổi tính năng/sửa lỗi code**: mô tả rõ vấn đề (kèm log) để họ chuyển cho phiên phát triển, hoặc hỏi họ trước khi
tự sửa trong `/root/autolist` (token GitHub trên VPS chỉ có quyền đọc, không đẩy lên được).

## Nguyên tắc dữ liệu (bắt buộc giữ)

- **Không suy luận.** Chỉ tự điền khi thông tin được ghi rõ, có nhãn và chỉ có một giá trị; chưa đủ căn cứ thì để
  trống kèm lý do (`properties.auto_notes`). Giá trị nhập tay (`*_manual`) luôn ưu tiên và không bị ghi đè.
- **Giỏ hàng** (`cart_items`) là riêng tư theo tài khoản: thành viên chỉ thấy giỏ của mình, quản trị thấy tất cả.
  Không tiết lộ giỏ của tài khoản này cho tài khoản khác khi trả lời.
- Quy ước phiên, giá phiên 1, giá hiện tại, % giảm, quét lịch sử: `docs/QUY_UOC_GIA_PHIEN.md`.
- Giá taisancong (OCR từ PDF) chỉ là tham khảo, không phải giá chính thức.
- Số liệu tài sản (diện tích, tờ/thửa, kích thước) ưu tiên lấy từ file đính kèm; OCR khác tin đăng → để trống
  (`properties.field_sources` ghi trường nào lấy từ tài liệu). **Không xoá** `data/files/`.

## An toàn – PHẢI hỏi người dùng trước khi

- Xoá bất cứ thứ gì trong `/opt/autolist/data/` hoặc `/opt/autolist/backups/`, chạy `rm -rf`, khôi phục sao lưu.
- Sửa `config/settings.yaml`, `config/sources/*.yaml`, crontab, systemd, Caddyfile, tường lửa (`ufw`), cấu hình SSH.
- Dừng/tắt dịch vụ, khởi động lại VPS (`reboot`), cập nhật phiên bản, cài/gỡ gói hệ thống.
- Gửi tin Telegram (ngoài `telegram-test` người dùng yêu cầu), tạo/sửa/khoá tài khoản web.
- Việc cần mật khẩu (tạo tài khoản, đặt lại mật khẩu): hướng dẫn người dùng làm trên web (menu Tài khoản) để mật khẩu
  không nằm trong nội dung trò chuyện.

Không bao giờ: in hoặc gửi nội dung file bí mật/token/mật khẩu; tắt tường lửa hoặc mở lại đăng nhập SSH bằng mật
khẩu khi chưa được yêu cầu; chạy lệnh tải từ Internet không rõ nguồn; giảm `delay_seconds` dưới mặc định (tránh gây
tải cho cổng thông tin nhà nước).

## Tài liệu trong repo

`docs/CAI_DAT_HANGDG.md` (cài đặt VPS này), `docs/CAP_NHAT_DOT_1.md` (Telegram, Google Drive, khoá SSH),
`docs/CAP_NHAT_DOT_2.md` (file đính kèm, lịch 0:00 & 12:00, sao lưu sau mỗi lượt),
`docs/QUY_UOC_GIA_PHIEN.md` (giá & phiên), `docs/HUONG_DAN.md` (vận hành chung, hướng dẫn sử dụng),
`docs/CLAUDE_TREN_VPS.md` (cách người dùng chạy phiên Claude này).
