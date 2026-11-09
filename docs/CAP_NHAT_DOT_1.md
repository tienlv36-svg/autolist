# Cập nhật Đợt 1 – bảo mật, Telegram, sao lưu Google Drive (VPS hangdg.com)

Đợt 1 gồm:

| Tính năng | Bạn cần làm gì |
|---|---|
| Khoá tạm khi đăng nhập web sai nhiều lần (10 lần/IP hoặc 20 lần/tài khoản trong 15 phút) | Không – tự có sau khi cập nhật |
| Trang **Hệ thống** (menu trên cùng, chỉ quản trị viên): dịch vụ, lịch, dữ liệu, ổ cứng, sao lưu, đăng nhập sai | Không |
| Nút **⬇ Xuất Excel** trên trang Tài sản (xuất đúng danh sách đang lọc) | Không |
| fail2ban – tự chặn IP dò mật khẩu SSH | Không |
| Không cho 2 lượt thu thập chạy chồng nhau | Không |
| **Quét lịch sử giá** cho tài sản còn hạn đăng ký (tìm phiên cũ, giá phiên đầu, nhịp giảm giá) – tự chạy mỗi ngày 2:00 | Chạy tay 1 lần sau khi cập nhật (cuối Phần A) |
| **Báo cáo Telegram** sau mỗi lượt 2:00 sáng + cảnh báo khi lỗi | **Phần B** (10 phút) |
| **Sao lưu lên Google Drive** | **Phần C** (15 phút) |
| **Đăng nhập VPS bằng khoá SSH**, tắt mật khẩu root | **Phần D** (10 phút) |

Làm Phần A trước, các phần B/C/D làm theo thứ tự nào cũng được.

---

## Phần A – Cập nhật phần mềm

> **Chỉ làm khi `first-load.sh` đã xong** (nhật ký có `HOÀN TẤT`). Kiểm tra:
> ```bash
> tail -n 3 /opt/autolist/data/first-load.log
> ```

Đăng nhập VPS (`ssh root@14.225.218.174`), rồi:

```bash
cd /root/autolist && git pull && sudo bash deploy/install-vps.sh
```

Kết quả đúng (rút gọn) – chú ý các dòng mới:

```
=== 3/8 Môi trường Python & thư viện ===
73 passed, 1 warning in ...                <- số có thể lớn hơn, không có "failed"
=== 5/8 Dịch vụ chạy nền & sao lưu ===
  auction-web: active | auction-scheduler: ...
  Sao lưu tự động 4:15 mỗi sáng vào /opt/autolist/backups
=== 6/8 Caddy – HTTPS thật (Let's Encrypt) cho hangdg.com ===
=== 7/8 Tường lửa ===
...
  fail2ban: active                         <- mới
=== 8/8 Tài khoản quản trị web ===
  Đã có tài khoản quản trị – bỏ qua
```

Nếu đã bật lịch tự động trước đó, khởi động lại để nhận mã mới:

```bash
sudo systemctl restart auction-scheduler
```

**Quét lịch sử giá lần đầu** (bản `first-load.sh` bạn đã chạy chưa có bước này). Chạy trong tmux, khoảng
4–5 giây mỗi tài sản (1.500 tài sản ≈ 2 giờ):

```bash
tmux new -s lichsu
```

```bash
sudo -u auction /opt/autolist/.venv/bin/auction history-scan -n 1500
```

(`Ctrl + B` rồi `D` để tách ra.) Kết quả cuối dạng *“Quét 1500 tài sản còn hạn: thêm 420 thông báo cũ cho 95 tài
sản, lỗi 0”*. Từ hôm sau, lượt 2:00 tự quét tiếp tối đa 500 tài sản/ngày. Quy ước chi tiết:
[QUY_UOC_GIA_PHIEN.md](QUY_UOC_GIA_PHIEN.md).

**Kiểm tra trên web:** vào https://hangdg.com → menu trên cùng có thêm **Hệ thống** → mở ra thấy 3 khung
*Dịch vụ & lịch* (3 dịch vụ `active`, *Lượt tiếp theo 02:00 ...*), *Dữ liệu*, *Ổ cứng & sao lưu*.
Trang **Tài sản** có nút **⬇ Xuất Excel** cạnh số tài sản.

---

## Phần B – Thông báo Telegram

Kết quả: nhóm Telegram nhận báo cáo mỗi sáng sau lượt 2:00, ví dụ:

```
✅ Thu thập 02:00 11/11 (34.5 phút)
• dgts: 812 tin mới, 15 cập nhật
• taisancong: 38 tin mới, 0 cập nhật
• Tài sản BĐS: 19.640 (+245 mới)
• Ổ cứng: 9.8% đã dùng
• Sao lưu gần nhất: 2026-11-10 04:15:02 (86M, VPS + Google Drive)
```

và cảnh báo **❌ / ⚠️** khi: một nguồn lỗi, không đọc được tin nào (website nguồn đổi cấu trúc), ổ cứng ≥ 85%,
sao lưu lỗi hoặc quá 2 ngày chưa sao lưu, hai lượt chạy chồng nhau.

### B1. Tạo bot (trên điện thoại hoặc Telegram máy tính)

1. Tìm **@BotFather** (có dấu tích xanh) → **Start**.
2. Gửi `/newbot`.
3. Đặt tên hiển thị, ví dụ: `Dau gia BDS hangdg`.
4. Đặt username (phải kết thúc bằng `bot`, chưa ai dùng), ví dụ: `hangdg_daugia_bot`.
5. BotFather trả về **token** dạng `7123456789:AAH...` → sao chép, lưu tạm vào Notepad.
   **Không gửi token này cho ai** (kể cả trong ảnh chụp màn hình gửi hỗ trợ).

### B2. Tạo nhóm và thêm bot

1. Telegram → **Nhóm mới** → đặt tên `Đấu giá BĐS – thông báo` → thêm các thành viên cần nhận tin.
2. Vào nhóm → **Thêm thành viên** → tìm username bot (`hangdg_daugia_bot`) → thêm.
3. Gửi tin `/start` trong nhóm.

### B3. Kết nối trên VPS

Thay `TOKEN_CUA_BAN` bằng token ở B1 (giữ nguyên dấu nháy đơn):

```bash
sudo -u auction /opt/autolist/.venv/bin/auction telegram-setup --token 'TOKEN_CUA_BAN'
```

**Kết quả đúng:**

```
Bot: @hangdg_daugia_bot
Nhóm: Đấu giá BĐS – thông báo (id -100xxxxxxxxxx)
Đã lưu cấu hình (/opt/autolist/data/telegram.json) và gửi tin thử vào nhóm.
```

và nhóm Telegram nhận tin *“✅ Đấu giá BĐS: đã kết nối thông báo Telegram…”*.

| Báo | Xử lý |
|---|---|
| `Token không hợp lệ` | Chép thiếu/thừa ký tự – lấy lại token: @BotFather → `/mybots` → chọn bot → *API Token* |
| `Chưa thấy nhóm nào` | Chưa thêm bot vào nhóm hoặc chưa gửi `/start` trong nhóm (B2) → làm lại rồi chạy lại lệnh |
| `Bot đang ở nhiều cuộc trò chuyện – chạy lại kèm --chat-id <ID>` | Chọn ID của nhóm (số âm, bắt đầu `-100`) trong danh sách in ra, chạy lại lệnh thêm `--chat-id -100xxxxxxxxxx` |

Thử lại bất cứ lúc nào: trên web → **Hệ thống** → nút **Gửi thử** cạnh Telegram.

Muốn nhận báo cáo ngay (không đợi 2:00), chạy một lượt thủ công – mất 10–60 phút, chạy trong tmux:

```bash
tmux new -s chaytay
```

```bash
sudo -u auction /opt/autolist/.venv/bin/auction run-now
```

(`Ctrl + B` rồi `D` để tách ra; Telegram sẽ nhận báo cáo khi xong.)

---

## Phần C – Sao lưu lên Google Drive

Mỗi sáng 4:15, bản sao lưu được chép thêm lên Google Drive (thư mục `autolist-backups`), giữ 30 ngày. Hỏng hẳn
VPS vẫn khôi phục được.

> Nên dùng một tài khoản Google riêng cho công ty (hoặc tài khoản có đủ dung lượng – mỗi bản sao lưu khoảng vài
> chục đến vài trăm MB, 30 bản).

### C1. Lấy “giấy phép” Google Drive trên máy tính Windows

1. Vào https://rclone.org/downloads/ → mục **Windows** → tải bản **AMD64 - 64 Bit** (file `.zip`).
2. Giải nén → đổi tên thư mục vừa giải nén thành `rclone` và chép vào `C:\` (để có file `C:\rclone\rclone.exe`).
3. Mở **PowerShell** (trên máy tính, không SSH) và chạy:
   ```powershell
   C:\rclone\rclone.exe authorize "drive"
   ```
4. Trình duyệt tự mở trang Google → chọn tài khoản → **Cho phép (Allow)** → trang báo *Success*.
5. Quay lại PowerShell, sẽ thấy:
   ```
   Paste the following into your remote machine --->
   {"access_token":"ya29....","token_type":"Bearer","refresh_token":"1//0g...","expiry":"..."}
   <---End paste
   ```
   Sao chép **đúng 1 dòng** bắt đầu bằng `{` và kết thúc bằng `}` (bôi đen trong PowerShell rồi nhấn Enter là chép).
   Dán vào Notepad để kiểm tra không bị xuống dòng.

### C2. Cấu hình trên VPS

Thay `DAN_JSON_VAO_DAY` bằng dòng `{...}` ở C1 (giữ nguyên **dấu nháy đơn** bao quanh):

```bash
sudo -u auction rclone config create gdrive drive token 'DAN_JSON_VAO_DAY' --non-interactive
```

Kiểm tra kết nối (không báo lỗi là được; Drive trống thì không in gì):

```bash
sudo -u auction rclone lsd gdrive:
```

Chạy sao lưu thử ngay:

```bash
sudo -u auction /opt/autolist/deploy/backup.sh
```

**Kết quả đúng** – dòng cuối có `offsite=true`:

```
2026-11-10 10:05:12 OK /opt/autolist/backups/autolist_20261110_1005.tar.gz (86M) offsite=true
```

Trên Google Drive (drive.google.com) xuất hiện thư mục **autolist-backups** chứa file vừa sao lưu.
Trang **Hệ thống** và báo cáo Telegram hiện *“VPS + Google Drive”*.

| Báo | Xử lý |
|---|---|
| `offsite=false` | Chưa có remote `gdrive` – kiểm tra `sudo -u auction rclone listremotes` phải in `gdrive:`; làm lại C2 |
| `couldn't fetch token` / `invalid_grant` | Dán thiếu dòng JSON hoặc giấy phép hết hạn – làm lại C1 và C2 (chạy C2 lần nữa sẽ ghi đè) |

---

## Phần D – Đăng nhập VPS bằng khoá SSH, tắt mật khẩu root

Sau phần này, chỉ **máy tính có khoá** mới SSH vào được VPS; dò mật khẩu root trở nên vô ích.
Console trên Portal Vietnix (*Open Xterm.js Console*) **vẫn đăng nhập bằng mật khẩu được** – đó là lối dự phòng.

### D1. Tạo khoá trên máy tính (PowerShell trên máy tính)

```powershell
ssh-keygen -t ed25519
```

- `Enter file in which to save the key` → nhấn **Enter**.
- `Enter passphrase` → nhấn **Enter** (hoặc đặt mật khẩu bảo vệ khoá, nhớ kỹ) → nhắc lại → **Enter**.
- Kết quả: tạo `C:\Users\<tên>\.ssh\id_ed25519` (khoá bí mật – **không gửi cho ai**) và `id_ed25519.pub`.

### D2. Chép khoá lên VPS (vẫn PowerShell trên máy tính – hỏi mật khẩu root lần cuối)

```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@14.225.218.174 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

### D3. Thử đăng nhập bằng khoá

```powershell
ssh root@14.225.218.174
```

**Đúng:** vào thẳng `root@hangdg-euqo:~#` **không hỏi mật khẩu root** (nếu đặt passphrase ở D1 thì hỏi passphrase).
Nếu vẫn hỏi `root@14.225.218.174's password:` → khoá chưa được chép, làm lại D2. **Không làm D4 khi D3 chưa đúng.**

### D4. Tắt đăng nhập bằng mật khẩu (trong cửa sổ SSH vừa vào ở D3)

```bash
sudo bash /root/autolist/deploy/harden-ssh.sh
```

Kết quả đúng:

```
Tìm thấy 1 khoá trong /root/.ssh/authorized_keys:
  - ssh-ed25519 ... admin@MAY-TINH
XONG: SSH chỉ còn nhận đăng nhập bằng khoá.
QUAN TRỌNG: GIỮ NGUYÊN cửa sổ này, mở PowerShell MỚI và thử:  ssh root@<IP>
```

**Giữ nguyên cửa sổ đó**, mở **PowerShell mới** và thử `ssh root@14.225.218.174` → vào được là hoàn tất.
Không vào được → quay lại cửa sổ cũ chạy `sudo bash /root/autolist/deploy/harden-ssh.sh --undo`.

> **Máy tính khác** cần SSH vào VPS: làm D1 trên máy đó, rồi chép nội dung file `id_ed25519.pub` của máy đó vào
> cuối file `/root/.ssh/authorized_keys` trên VPS (dùng *Open Xterm.js Console* trên Portal Vietnix nếu không còn
> máy nào SSH được).
> **Lỡ bị khoá ngoài:** Portal Vietnix → VPS → **Open Xterm.js Console** → đăng nhập `root` + mật khẩu →
> `sudo bash /root/autolist/deploy/harden-ssh.sh --undo`.

---

## Phần E – Kiểm thử tự động trên GitHub (không cần làm gì)

Mỗi lần mã nguồn được đẩy lên GitHub, toàn bộ kiểm thử tự chạy. Xem tại repo **autolist** → tab **Actions**:
dấu ✅ xanh là đạt. Trước khi cập nhật VPS (Phần A), có thể xem lần đẩy mới nhất có ✅ không.

---

## Kiểm tra tổng sau khi làm xong

```bash
systemctl is-active auction-web auction-scheduler caddy fail2ban; ls /opt/autolist/data/telegram.json; sudo -u auction rclone listremotes
```

Đúng: 4 dòng `active`, đường dẫn `telegram.json`, và `gdrive:`.
