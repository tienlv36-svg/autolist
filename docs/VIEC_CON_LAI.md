# Việc còn lại – làm theo thứ tự (hướng dẫn chi tiết)

Phần mềm đã viết xong mọi tính năng đã thống nhất. Còn lại là **cài đặt và bật các tính năng trên VPS**. Làm lần lượt
từ Bước 1 đến Bước 8. Mỗi bước có dòng **“Đúng khi”** để tự kiểm tra; sai thì chụp màn hình gửi phiên phát triển.

| Bước | Việc | Ai làm | Thời gian |
|---|---|---|---|
| 1 | Cập nhật phần mềm lên bản mới nhất | Phiên **VPS hangdg** (bạn bấm Cho phép) | 10 phút |
| 2 | Bật Telegram (bot + nhóm báo cáo) | Bạn, qua SSH | 15 phút |
| 3 | Mỗi người liên kết Telegram cá nhân | Từng thành viên, trên web | 2 phút/người |
| 4 | Sao lưu lên Google Drive | Bạn: máy tính + SSH | 15 phút |
| 5 | Đăng nhập VPS bằng khoá SSH, tắt mật khẩu root | Bạn: máy tính + SSH | 15 phút |
| 6 | Tạo tài khoản web cho thành viên | Quản trị, trên web | 2 phút/người |
| 7 | Cài web lên điện thoại | Từng người | 1 phút |
| 8 | Kiểm tra sau 1–2 ngày, gửi ảnh để tinh chỉnh | Bạn | 5 phút |

> **Quy tắc an toàn:** mật khẩu, **token Telegram**, **mã Google Drive** chỉ dán vào cửa sổ **SSH** (hoặc PowerShell),
> **không** dán vào app Claude (kể cả phiên VPS hangdg) và không chụp màn hình gửi đi.

---

## Bước 1 – Cập nhật phần mềm (qua phiên VPS hangdg)

Bản mới gồm: bộ lọc đã lưu + Telegram cá nhân, nhắc hạn, gợi ý gộp phiên, trang Độ đầy đủ, trang **Thống kê**,
**biểu đồ giá** qua các phiên, cài lên điện thoại, và sửa lỗi lượt quét đọc thừa 40–50 phút.

1. Mở app Claude → **Code** → **VPS hangdg** → **Phiên mới**.
2. Dán nguyên đoạn sau rồi gửi:

   > Cập nhật phiên bản mới cho mình, hỏi trước mỗi lệnh có tác động:
   > 1. Kiểm tra không có lượt thu thập hay tiến trình ghi CSDL nào đang chạy (tmux ls, pgrep). Nếu đang chạy thì
   >    báo mình khi nào xong rồi mới làm tiếp.
   > 2. Sao lưu (`deploy/backup.sh`), rồi `cd /root/autolist && git pull && sudo bash deploy/install-vps.sh`.
   > 3. Kiểm tra 4 dịch vụ và lịch tự động (journalctl -u auction-scheduler -n 5), rồi tóm tắt kết quả cho mình.

3. Khi app hiện **Allow / Cho phép** cho lệnh sao lưu, `git pull`, `install-vps.sh` → bấm cho phép.

**Đúng khi:** Claude báo cập nhật xong, 4 dịch vụ `active`. Mở https://hangdg.com thấy menu: *Tài sản · Việc của tôi ·
🛒 Giỏ hàng · 🔔 Bộ lọc · Xác nhận vị trí · Thống kê · Độ đầy đủ*.

> Không dùng được app? Làm qua SSH:
> ```bash
> sudo -u auction /opt/autolist/deploy/backup.sh && cd /root/autolist && git pull && sudo bash deploy/install-vps.sh
> ```

---

## Bước 2 – Bật Telegram (bot + nhóm báo cáo)

Sau bước này: nhóm Telegram nhận **báo cáo sau lượt quét 2:00 mỗi ngày** (số tin mới, dữ liệu đã lấp trong ngày, lỗi, ổ cứng, sao lưu…),
và bot dùng để gửi **tin cá nhân** (bộ lọc, nhắc hạn) ở Bước 3.

### 2.1. Tạo bot (trên điện thoại)
1. Mở Telegram → tìm **@BotFather** (có dấu tích xanh) → **Start**.
2. Gửi `/newbot`.
3. Đặt tên hiển thị, ví dụ `Dau gia BDS hangdg`.
4. Đặt username, phải kết thúc bằng `bot`, ví dụ `hangdg_daugia_bot`.
5. BotFather gửi lại **token** dạng `7123456789:AAH…` → bấm giữ để sao chép, gửi vào **Tin nhắn đã lưu (Saved
   Messages)** của chính bạn để lát nữa chép sang máy tính. **Không gửi token cho ai.**

### 2.2. Tạo nhóm báo cáo
1. Telegram → **Nhóm mới** → tên `Đấu giá BĐS – báo cáo` → thêm những người cần nhận báo cáo.
2. Vào nhóm → **Thêm thành viên** → tìm username bot → thêm.
3. Gửi `/start` trong nhóm.

### 2.3. Kết nối trên VPS (qua SSH)
1. Máy tính: mở **PowerShell** → `ssh root@14.225.218.174` → nhập mật khẩu (hoặc vào thẳng nếu đã làm Bước 5).
2. Dán lệnh dưới, **thay `TOKEN_CUA_BAN`** bằng token ở 2.1, giữ nguyên dấu nháy đơn:

```bash
sudo -u auction /opt/autolist/.venv/bin/auction telegram-setup --token 'TOKEN_CUA_BAN'
```

**Đúng khi:** in ra `Bot: @…`, `Nhóm: Đấu giá BĐS – báo cáo (id -100…)`, `Đã lưu cấu hình…` và nhóm nhận tin
*“✅ Đấu giá BĐS: đã kết nối thông báo Telegram…”*.

| Báo lỗi | Xử lý |
|---|---|
| `Token không hợp lệ` | Chép thiếu/thừa ký tự. Lấy lại: @BotFather → `/mybots` → chọn bot → *API Token* |
| `Chưa thấy nhóm nào` | Chưa thêm bot vào nhóm hoặc chưa gửi `/start` trong nhóm → làm lại 2.2 rồi chạy lại lệnh |
| `Bot đang ở nhiều cuộc trò chuyện…` | Chạy lại lệnh, thêm `--chat-id -100xxxxxxxxxx` (ID **số âm** của nhóm trong danh sách in ra) |

Không cần khởi động lại dịch vụ: lượt quét kế tiếp tự dùng Telegram.

Thử lại bất cứ lúc nào: web → **Hệ thống** → **Gửi thử** cạnh Telegram.

---

## Bước 3 – Liên kết Telegram cá nhân (từng thành viên tự làm)

Để nhận **riêng** tài sản mới theo bộ lọc và nhắc hạn. Tin cá nhân không gửi vào nhóm.

1. Đăng nhập https://hangdg.com → bấm **tên mình** (góc phải trên) → mục **Telegram cá nhân** → **Liên kết Telegram**.
2. Trang hiện mã 6 ký tự và link **mở bot** → bấm link (mở Telegram) → bấm **Start**.
   (Hoặc tự tìm bot, gửi `/start MÃ`.)
3. Quay lại trang web → bấm **Kiểm tra**.

**Đúng khi:** trang báo **“Đã liên kết”** và bot gửi tin *“✅ Đã liên kết với tài khoản …”*.

4. Tạo bộ lọc nhận tin: trang **Tài sản** → chọn bộ lọc (vd *Ngân hàng*, *Hà Nội*, *Giá đến 5 tỷ*, *Còn hạn đăng ký*)
   → bấm **Lọc** → **💾 Lưu bộ lọc** → đặt tên → để tích *Báo tài sản mới qua Telegram* → **Lưu**.
   Quản lý ở menu **🔔 Bộ lọc**.

Từ đó, sau lượt quét 2:00 mỗi ngày: tài sản **mới** hoặc **có phiên mới** khớp bộ lọc được gửi cho riêng bạn; mỗi
ngày 1 tin **nhắc hạn** (tài sản trong giỏ sắp hết hạn đăng ký, việc được giao sắp/đã quá hạn).

---

## Bước 4 – Sao lưu lên Google Drive

Hiện bản sao lưu chỉ nằm trên VPS (hỏng VPS là mất cả hai). Sau bước này, mỗi lần sao lưu (sau mỗi lượt quét) được
chép thêm lên Google Drive, thư mục `autolist-backups`, giữ 30 ngày. Nên dùng tài khoản Google riêng của công ty.

### 4.1. Lấy giấy phép Google Drive (trên máy tính Windows)
1. Vào https://rclone.org/downloads/ → mục **Windows** → tải **AMD64 – 64 Bit** (file .zip).
2. Giải nén → đổi tên thư mục thành `rclone`, chép vào `C:\` (có file `C:\rclone\rclone.exe`).
3. Mở **PowerShell** (trên máy tính, **không** SSH):
   ```powershell
   C:\rclone\rclone.exe authorize "drive"
   ```
4. Trình duyệt mở trang Google → chọn tài khoản → **Cho phép** → trang báo *Success*.
5. Quay lại PowerShell, sao chép **đúng 1 dòng** bắt đầu bằng `{` và kết thúc bằng `}` (giữa
   `Paste the following…` và `<---End paste`). Dán thử vào Notepad, phải nằm trên 1 dòng.

### 4.2. Cấu hình trên VPS (cửa sổ SSH)
Thay `DAN_JSON_VAO_DAY` bằng dòng `{…}` ở 4.1, giữ nguyên dấu nháy đơn:

```bash
sudo -u auction rclone config create gdrive drive token 'DAN_JSON_VAO_DAY' --non-interactive
```

```bash
sudo -u auction /opt/autolist/deploy/backup.sh
```

**Đúng khi:** dòng cuối có `offsite=true`; trên drive.google.com có thư mục **autolist-backups**.

| Báo | Xử lý |
|---|---|
| `offsite=false` | `sudo -u auction rclone listremotes` phải in `gdrive:`; nếu không, làm lại 4.2 |
| `couldn't fetch token` / `invalid_grant` | Dán thiếu dòng JSON hoặc giấy phép hết hạn → làm lại 4.1 và 4.2 |

(Tuỳ chọn) đẩy cả **file đính kèm** đã lưu lên Drive (chỉ phần mới mỗi lần; Drive miễn phí 15 GB):
```bash
sudo -u auction touch /opt/autolist/data/.drive_files
```

---

## Bước 5 – Đăng nhập VPS bằng khoá SSH, tắt mật khẩu root

Mật khẩu root từng lộ trong ảnh chụp, nên bước này quan trọng. Sau bước này chỉ máy tính có khoá mới SSH vào được.
Console trên Portal Vietnix (*Open Xterm.js Console*) vẫn đăng nhập bằng mật khẩu – lối dự phòng.
Remote Control (phiên VPS hangdg) **không bị ảnh hưởng**.

### 5.1. Tạo khoá (PowerShell trên máy tính)
```powershell
ssh-keygen -t ed25519
```
Nhấn **Enter** 3 lần (lưu chỗ mặc định, không đặt passphrase – hoặc đặt passphrase và nhớ kỹ).

### 5.2. Chép khoá lên VPS (PowerShell trên máy tính – hỏi mật khẩu root lần cuối)
```powershell
type $env:USERPROFILE\.ssh\id_ed25519.pub | ssh root@14.225.218.174 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

### 5.3. Thử đăng nhập bằng khoá
```powershell
ssh root@14.225.218.174
```
**Đúng khi:** vào thẳng `root@hangdg-euqo:~#`, **không hỏi mật khẩu root**. Còn hỏi mật khẩu → làm lại 5.2.
**Chưa đúng thì KHÔNG làm 5.4.**

### 5.4. Tắt đăng nhập bằng mật khẩu (trong cửa sổ SSH vừa vào ở 5.3)
```bash
sudo bash /root/autolist/deploy/harden-ssh.sh
```
**Giữ nguyên cửa sổ đó**, mở **PowerShell mới**, chạy `ssh root@14.225.218.174` → vào được là xong.
Không vào được → quay lại cửa sổ cũ chạy `sudo bash /root/autolist/deploy/harden-ssh.sh --undo`.

### 5.5. Đổi mật khẩu root (dùng cho Console dự phòng)
Trong cửa sổ SSH:
```bash
passwd
```
Gõ mật khẩu mới 2 lần (màn hình không hiện ký tự – bình thường). Lưu vào trình quản lý mật khẩu, **không chụp màn hình**.

---

## Bước 6 – Tạo tài khoản web cho thành viên

1. Web → **Tài khoản** → mục tạo tài khoản → nhập tên đăng nhập, họ tên, mật khẩu tạm, chọn quyền:
   - **Thành viên**: xem/ghi chú/giỏ hàng/việc của mình; không thấy giỏ, bộ lọc của người khác.
   - **Quản trị**: thêm quản lý tài khoản, trang Hệ thống, xem giỏ hàng của mọi người.
2. Gửi tên đăng nhập + mật khẩu tạm cho người đó (nói trực tiếp/điện thoại). Người đó đăng nhập → bấm tên mình →
   **Đổi mật khẩu**, rồi làm **Bước 3** và **Bước 7**.

---

## Bước 7 – Cài web lên điện thoại (như một ứng dụng)

- **Android (Chrome):** mở https://hangdg.com → đăng nhập → menu **⋮** → **Thêm vào màn hình chính** (hoặc **Cài đặt
  ứng dụng**) → **Cài đặt**.
- **iPhone (Safari):** mở https://hangdg.com → nút **Chia sẻ** (ô vuông mũi tên lên) → **Thêm vào MH chính** → **Thêm**.

**Đúng khi:** màn hình điện thoại có biểu tượng hình thoi xanh **Đấu giá BĐS**, mở ra toàn màn hình.

---

## Bước 8 – Kiểm tra sau 1–2 ngày

Nhắn phiên **VPS hangdg**:

> Tóm tắt 2 lượt quét gần nhất: thời gian chạy, số tin mới, số tin BĐS được bổ sung giá, số file đính kèm đã đọc
> (bao nhiêu bằng OCR), số tài sản có số liệu từ tài liệu, gợi ý gộp mới, sao lưu có lên Google Drive không.

Rồi chụp gửi **phiên phát triển** (phiên này) để tinh chỉnh độ chính xác:
1. Trang **Độ đầy đủ**.
2. Trang **Hệ thống**.
3. 2–3 tài sản còn hạn có mục *File đính kèm đã lưu* (bấm **xem chữ** ở một file scan để thấy chất lượng OCR).
4. Vài tài sản bị **gộp phiên sai** (nếu có) và trang **Xác nhận vị trí**.

---

## Dùng hằng ngày – nhớ nhanh

| Muốn | Làm |
|---|---|
| Xem tài sản sắp hết hạn | Trang **Tài sản**, sắp xếp *Sắp hết hạn đăng ký* (mặc định), tích *Còn hạn đăng ký* |
| Theo dõi tài sản quan tâm | **＋ Giỏ** trên thẻ tài sản; xem ở **🛒 Giỏ hàng**; nhắc hạn tự động |
| Nhận tin tài sản mới theo tiêu chí | **💾 Lưu bộ lọc** (Bước 3) |
| Hai thẻ là cùng một BĐS | Phần mềm tự gộp khi đủ căn cứ; còn sót thì trong trang tài sản nhập số `#id` vào ô *Gộp vào #* |
| Xã/phường, tỉnh còn trống | Menu **Xác nhận vị trí** → bấm vị trí gợi ý (1 chạm) |
| Bổ sung số liệu còn thiếu | **Độ đầy đủ** → *Xem danh sách thiếu* → mở tài sản → **Sửa thông tin** |
| Xem xu hướng | **Thống kê** (tài sản mới theo tuần, theo tỉnh, theo chủ tài sản); biểu đồ giá trong từng tài sản |
| Hỏi tình hình hệ thống | App Claude → **VPS hangdg** |
| Sửa / thêm tính năng | Nhắn **phiên phát triển**; xong thì bảo VPS hangdg *“cập nhật phiên bản mới”* |

**Nếu phiên VPS hangdg biến mất** (VPS khởi động lại…): SSH vào VPS rồi chạy

```bash
tmux kill-session -t claude 2>/dev/null; tmux new -d -s claude 'cd /opt/autolist && claude remote-control --name "VPS hangdg"' && sleep 5 && tmux ls
```

**Đúng khi:** có dòng `claude: 1 windows`.
