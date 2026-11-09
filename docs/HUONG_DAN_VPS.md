# Hướng dẫn cài đặt trên VPS (chưa có tên miền) – từng bước

Làm lần lượt từ Bước 0 đến Bước 9. Mỗi bước ghi rõ **gõ lệnh gì** và **kết quả đúng trông thế nào**.
Tổng thời gian thao tác khoảng 30 phút; việc lấy dữ liệu lần đầu (Bước 7) máy tự chạy thêm vài giờ.

Sau khi xong, cả nhóm truy cập phần mềm tại **`https://<địa-chỉ-IP-VPS>`**.

> Các script trong hướng dẫn này đã được chạy thử trên Ubuntu 24.04 (cài mới, chạy lại để cập nhật,
> lấy dữ liệu, sao lưu/khôi phục, truy cập HTTPS bằng địa chỉ IP).

---

## Bước 0 – Chuẩn bị VPS

Thuê một VPS với cấu hình:

| Hạng mục | Tối thiểu | Khuyến nghị |
|---|---|---|
| Hệ điều hành | **Ubuntu 24.04 LTS** (hoặc 22.04) | Ubuntu 24.04 LTS |
| CPU / RAM | 2 vCPU / 2 GB | 2 vCPU / 4 GB |
| Ổ cứng | 30 GB SSD | 60 GB SSD trở lên nếu lưu nhiều ảnh/video |
| Vị trí | Việt Nam | Việt Nam (truy cập ổn định tới cổng thông tin nhà nước) |

Sau khi thuê, nhà cung cấp gửi cho bạn 3 thông tin – ghi lại:

- **Địa chỉ IP**, ví dụ `103.12.34.56` (trong tài liệu này viết là `<IP>`)
- Tên đăng nhập: thường là **`root`**
- **Mật khẩu root**

---

## Bước 1 – Tạo “chìa khoá” để VPS tải được mã nguồn từ GitHub

Repo `autolist` đang để **Private**, nên VPS cần một token (giống mật khẩu riêng, chỉ có quyền đọc repo này).

1. Đăng nhập https://github.com bằng tài khoản `tienlv36-svg`.
2. Bấm ảnh đại diện (góc phải trên) → **Settings** → cuối menu trái chọn **Developer settings**.
3. Chọn **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
4. Điền:
   - *Token name*: `vps-autolist`
   - *Expiration*: 1 năm (hoặc tuỳ chọn)
   - *Repository access*: **Only select repositories** → chọn `tienlv36-svg/autolist`
   - *Permissions* → *Repository permissions* → **Contents: Read-only**
5. Bấm **Generate token**, **sao chép ngay** chuỗi bắt đầu bằng `github_pat_...` (chỉ hiện một lần) và lưu
   vào chỗ an toàn.

---

## Bước 2 – Kết nối vào VPS

**Trên Windows 10/11:** bấm phím Windows, gõ `PowerShell`, mở lên.
**Trên macOS:** mở ứng dụng *Terminal*.

Gõ lệnh sau (thay `<IP>` bằng IP thật):

```bash
ssh root@<IP>
```

- Lần đầu sẽ hỏi `Are you sure you want to continue connecting (yes/no)?` → gõ `yes` rồi Enter.
- Nhập mật khẩu root (khi gõ **không hiện ký tự** – cứ gõ rồi Enter).
- Thành công khi thấy dòng nhắc dạng `root@ten-may:~#`.

> Mọi lệnh ở các bước sau đều gõ trong cửa sổ này. Mẹo: trong PowerShell, **chuột phải** để dán lệnh đã sao chép.

---

## Bước 3 – Cập nhật hệ điều hành

```bash
apt update && apt upgrade -y
```

Mất 1–5 phút. Nếu hiện bảng màu tím hỏi về khởi động lại dịch vụ, nhấn **Enter** để chọn mặc định.
Nếu cuối cùng có dòng `*** System restart required ***`, khởi động lại rồi làm lại Bước 2:

```bash
reboot
```

**Chỉ khi VPS có 2 GB RAM** – tạo thêm 2 GB bộ nhớ ảo (swap) cho ổn định:

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

---

## Bước 4 – Tải mã nguồn về VPS

```bash
git clone https://github.com/tienlv36-svg/autolist.git /root/autolist
```

Khi được hỏi:

- `Username for 'https://github.com':` → gõ `tienlv36-svg`
- `Password for ...:` → **dán token** `github_pat_...` ở Bước 1 (không hiện ký tự), Enter.

Đúng khi thấy `Receiving objects: 100%` và không có dòng `fatal`.

---

## Bước 5 – Chạy script cài đặt tự động

```bash
sudo bash /root/autolist/deploy/install-vps.sh
```

Script tự làm 8 việc (mất khoảng 3–5 phút), in ra từng mục `=== 1/8 ... ===` đến `=== 8/8 ... ===`:

1. Cài phần mềm cần thiết (Python, OCR tiếng Việt, Caddy, tường lửa...), đặt múi giờ Việt Nam
2. Tạo tài khoản hệ thống `auction`, đặt phần mềm tại `/opt/autolist`
3. Cài thư viện và **chạy kiểm thử** – phải thấy dòng `58 passed` (con số có thể lớn hơn ở bản mới)
4. Cấu hình chạy thật (tắt lưu bản gốc trang web để tiết kiệm ổ cứng)
5. Tạo dịch vụ web tự khởi động, đặt lịch **sao lưu tự động 4:15 mỗi sáng**
6. Bật **HTTPS trên địa chỉ IP** (chứng chỉ tự ký – xem Bước 6)
7. Bật tường lửa: chỉ mở cổng SSH (22), 80, 443
8. Tạo **tài khoản quản trị web**: script hỏi
   - `Tên đăng nhập quản trị [admin]:` → Enter để dùng `admin` (hoặc gõ tên khác)
   - `Họ tên:` → ví dụ `Nguyễn Văn A`
   - `Password:` và `Repeat for confirmation:` → đặt mật khẩu **ít nhất 8 ký tự**, ghi nhớ lại

Kết thúc đúng khi thấy:

```
 XONG. Mở trình duyệt:  https://<IP>
```

và ở mục 5/8 có `auction-web: active`, mục 6/8 có `caddy: active`.

---

## Bước 6 – Mở phần mềm lần đầu

Trên máy tính, mở Chrome/Edge, vào **`https://<IP>`** (nhớ có `https://`).

Vì chưa có tên miền, trình duyệt **sẽ cảnh báo** “Kết nối của bạn không phải là kết nối riêng tư”.
Đây là bình thường: kết nối **vẫn được mã hoá**, chỉ là chứng chỉ do chính máy chủ tự cấp chứ không phải
của tổ chức chứng thực. Cách đi tiếp:

- **Chrome / Edge / Cốc Cốc:** bấm **Nâng cao** (Advanced) → **Tiếp tục truy cập <IP> (không an toàn)**.
- **Firefox:** **Nâng cao…** → **Chấp nhận rủi ro và tiếp tục**.
- **Điện thoại:** tương tự, bấm *Nâng cao / Chi tiết* → *Truy cập trang web*.

Mỗi trình duyệt chỉ phải làm việc này một lần. Đăng nhập bằng tài khoản quản trị vừa tạo ở Bước 5.
Danh sách tài sản lúc này còn trống – làm Bước 7.

> Không nên truy cập bằng `http://<IP>:8000`: cổng này đã bị chặn, và nếu mở ra thì mật khẩu sẽ truyền
> không mã hoá.

---

## Bước 7 – Lấy dữ liệu lần đầu (máy tự chạy vài giờ)

Vẫn trong cửa sổ SSH. Mở một phiên **tmux** để việc chạy không bị ngắt khi bạn tắt máy tính:

```bash
tmux new -s napdulieu
```

Chạy script lấy dữ liệu (mặc định: tin dgts đăng trong **180 ngày** gần nhất + toàn bộ taisancong):

```bash
sudo -u auction bash /opt/autolist/deploy/first-load.sh
```

Muốn lấy dài hơn, ví dụ 1 năm, thì dùng lệnh này thay cho lệnh trên:

```bash
sudo -u auction env DAYS=365 bash /opt/autolist/deploy/first-load.sh
```

Script chạy 8 bước, mỗi bước in một dòng `>>> ...` kèm kết quả:

| Bước | Việc | Thời gian ước tính (180 ngày) |
|---|---|---|
| 1 | Danh sách tin dgts | 30–60 phút |
| 2 | Danh sách tin taisancong | 1–2 giờ |
| 3–4 | Đánh dấu tin trùng, lọc BĐS, gom phiên | vài phút – **từ đây đã xem được trên web** |
| 5 | Giá, tiền đặt trước, nơi có tài sản của tin BĐS dgts | **lâu nhất: 5–15 giờ** (tuỳ tốc độ dgts) |
| 6 | Chi tiết tin taisancong | 1–2 giờ |
| 7–8 | Loại tài sản chính thức, tính lại giá phiên / % giảm | 10–20 phút |

**Tách khỏi tmux để máy tự chạy:** nhấn `Ctrl + B`, thả ra, rồi nhấn `D`. Bây giờ có thể đóng cửa sổ.

**Xem tiến độ** (kết nối SSH lại bất cứ lúc nào):

```bash
tail -f /opt/autolist/data/first-load.log
```

(Nhấn `Ctrl + C` để thoát chế độ xem.) Hoặc quay lại màn hình đang chạy:

```bash
tmux attach -t napdulieu
```

Xong khi nhật ký có dòng **`HOÀN TẤT`**. Nếu thấy dòng **`DỪNG:`** thì thường là do mạng tới website nguồn
– kiểm tra bằng lệnh dưới (phải thấy `HTTP/... 200`), rồi chạy lại script (dữ liệu đã lấy không bị lấy lại):

```bash
curl -I https://dgts.moj.gov.vn
```

---

## Bước 8 – Bật thu thập tự động

Sau khi Bước 7 báo `HOÀN TẤT`:

```bash
sudo systemctl enable --now auction-scheduler
```

Từ đây **mỗi ngày lúc 2:00 sáng** phần mềm tự: lấy tin mới của cả 2 nguồn (kèm giá) → gắn loại tài sản →
đánh dấu tin trùng → gom phiên, tính giá phiên 1 / hiện tại / % giảm. Kiểm tra:

```bash
systemctl status auction-scheduler --no-pager
```

Phải thấy `Active: active (running)`.

---

## Bước 9 – Tạo tài khoản cho nhân viên

Trên web, đăng nhập quản trị → menu **Tài khoản** → khung **Tạo tài khoản**: nhập tên đăng nhập (chữ thường,
không dấu, ví dụ `lan.nguyen`), họ tên, mật khẩu tạm (≥ 8 ký tự), quyền *Thành viên* → **Tạo**.
Gửi cho nhân viên: địa chỉ `https://<IP>`, tên đăng nhập, mật khẩu tạm; dặn họ đổi mật khẩu bằng cách bấm
vào tên mình ở góc phải trên.

Hướng dẫn sử dụng cho nhân viên: [HUONG_DAN.md – Phần C](HUONG_DAN.md#phần-c--hướng-dẫn-sử-dụng-cho-nhân-viên).

---

## Nguyên tắc dữ liệu: chưa chắc chắn thì để trống

Phần mềm **chỉ tự điền khi thông tin được ghi rõ trong tin đăng**, có nhãn rõ ràng và **chỉ có một giá trị**.
Không suy luận, không cộng dồn, không tính hiệu số. Những ô để trống sẽ có dòng giải thích màu vàng
*“Để trống vì chưa đủ căn cứ”* trên trang chi tiết; nhân viên đối chiếu hồ sơ rồi **nhập tay**.

| Thông tin | Tự điền khi | Để trống khi |
|---|---|---|
| Số tờ, số thửa | Tin chỉ có **một** cặp tờ/thửa (tờ “nay là” được dùng số mới) | Nhiều thửa, nhiều tờ |
| Tổng diện tích đất | Có nhãn “Diện tích…” và chỉ một con số | Nhiều số khác nhau (vd theo sổ ≠ đo đạc), tin nhiều thửa/lô |
| Diện tích đất ở / đất khác | Con số **đi kèm trực tiếp** loại đất (“150 m2 đất ở”, “(ODT) 36m2”) | Chỉ ghi “mục đích sử dụng: đất ở” mà không có số; không khớp tổng |
| Diện tích sàn | Có nhãn “diện tích sàn” / “tổng diện tích sàn”, một giá trị | Nhiều công trình, nhiều số |
| Chiều ngang / dài | Có nhãn “chiều ngang / mặt tiền / chiều dài / chiều sâu” | “kích thước 10m x 5m” (không rõ chiều nào), số đo cạnh giáp ranh |
| Xã/phường | Ghi trong “(nay là …)” hoặc tin chỉ nhắc một xã/phường | Nhắc nhiều xã/phường |
| Tỉnh/thành | Ghi trong mô tả/địa chỉ **tài sản** (tên tỉnh cũ được quy đổi theo NQ sáp nhập 2025) | Không ghi; **không** đoán từ tên chủ tài sản hay nơi đấu giá |
| Giá | Giá khởi điểm **chính thức** do nguồn đăng (dgts) cho thông báo một giá | Thông báo nhiều tài sản mỗi cái một giá; phiên chưa có giá |
| % giảm | Có giá phiên 1 và giá phiên gần nhất, không có cảnh báo gộp phiên | Thiếu một trong hai giá, hoặc nhãn ⚠ |
| Giá từ PDF (taisancong) | Chỉ hiện làm **tham khảo** (khung xanh), không dùng để lọc | Luôn cần người xác nhận rồi nhập tay |

Giá trị nhập tay luôn được ưu tiên, được dùng khi lọc/tính % giảm, và **không bị ghi đè** khi phần mềm cập nhật.

---

## Việc định kỳ cho người quản trị

**Hằng tuần (2 phút):**

```bash
ssh root@<IP>
```

```bash
systemctl is-active auction-web auction-scheduler caddy
```

Phải thấy 3 dòng `active`. Xem 5 lượt thu thập gần nhất:

```bash
sqlite3 /opt/autolist/data/auction.db "select source, started_at, status, found, inserted from crawl_runs order by id desc limit 5;"
```

Xem dung lượng ổ cứng (cột `Use%` nên dưới 80%) và các bản sao lưu:

```bash
df -h / && ls -lh /opt/autolist/backups | tail -5
```

**Hằng tháng:** chép bản sao lưu mới nhất về máy tính (chạy trên **máy tính của bạn**, không phải trong SSH;
thay tên file cho đúng):

```bash
scp root@<IP>:/opt/autolist/backups/autolist_YYYYMMDD_HHMM.tar.gz .
```

### Cập nhật phiên bản mới

```bash
cd /root/autolist && git pull
```

(Nhập lại `tienlv36-svg` và token nếu được hỏi.) Sau đó chạy lại script cài đặt – an toàn, giữ nguyên dữ liệu,
tài khoản và file cấu hình đã chỉnh, tự khởi động lại dịch vụ:

```bash
sudo bash /root/autolist/deploy/install-vps.sh
```

### Khôi phục từ bản sao lưu

```bash
sudo systemctl stop auction-web auction-scheduler
```

```bash
mkdir -p /tmp/restore && tar -xzf /opt/autolist/backups/autolist_YYYYMMDD_HHMM.tar.gz -C /tmp/restore
```

```bash
cp /tmp/restore/auction.db /opt/autolist/data/ && cp -r /tmp/restore/media /tmp/restore/secret.key /opt/autolist/data/ && chown -R auction:auction /opt/autolist/data
```

```bash
sudo systemctl start auction-web auction-scheduler
```

---

## Tăng bảo mật (khuyến nghị)

**Chỉ cho phép IP văn phòng truy cập web** (nếu văn phòng có IP tĩnh, ví dụ `14.161.1.2`):

```bash
ufw delete allow 80/tcp && ufw delete allow 443/tcp
```

```bash
ufw allow from 14.161.1.2 to any port 80,443 proto tcp
```

**Đổi mật khẩu root** thành mật khẩu mạnh:

```bash
passwd
```

---

## Khi có tên miền

1. Tại nơi quản lý tên miền, tạo 2 bản ghi **A**: `@` → `<IP>` và `www` → `<IP>`. Chờ 5–30 phút, kiểm tra trên máy
   tính bằng `nslookup ten-mien.com` (phải ra đúng `<IP>`).
2. Chạy lại script cài đặt kèm tên miền – script tự kiểm tra DNS, xin chứng chỉ HTTPS thật (Let's Encrypt), chuyển
   `www` về tên miền chính và ghi nhớ tên miền cho các lần cập nhật sau:
   ```bash
   cd /root/autolist && git pull && sudo DOMAIN=ten-mien.com EMAIL=email-cua-ban@gmail.com bash deploy/install-vps.sh
   ```
3. Truy cập `https://ten-mien.com` – không còn cảnh báo chứng chỉ.

Hướng dẫn cụ thể cho tên miền **hangdg.com**: [CAI_DAT_HANGDG.md](CAI_DAT_HANGDG.md).

---

## Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| `ssh` báo *Connection refused / timed out* | Kiểm tra IP; VPS đang bật chưa (trang quản lý của nhà cung cấp) |
| `git clone` báo *Authentication failed* | Token sai/hết hạn hoặc chưa cấp quyền repo `autolist` – làm lại Bước 1 |
| Script cài báo lỗi ở mục 3/8 (`failed`) | Chụp màn hình gửi người phụ trách kỹ thuật; chạy lại script sau khi sửa |
| Trình duyệt không mở được `https://<IP>` | Chạy `systemctl status caddy auction-web --no-pager`; `ufw status` phải có 443 ALLOW |
| Báo *502 Bad Gateway* | Web đang khởi động lại hoặc lỗi: `journalctl -u auction-web -n 50 --no-pager` |
| Danh sách trống | Chưa chạy xong Bước 7 (ít nhất tới bước 4 của script) |
| Thẻ tài sản ghi “Chưa có giá” | Tin chưa lấy được chi tiết, hoặc thông báo nhiều tài sản (xem dòng giải thích) – nhập tay nếu cần |
| `first-load.log` có dòng `DỪNG:` | Mạng tới website nguồn có vấn đề – kiểm tra `curl -I https://dgts.moj.gov.vn`, chạy lại script |
| Ổ cứng đầy | `du -sh /opt/autolist/data/*` xem thư mục lớn; xoá bớt file trong `backups/` cũ hoặc nâng ổ cứng VPS |
| Quên mật khẩu quản trị web | `sudo -u auction /opt/autolist/.venv/bin/auction user-add admin2 --name "Quản trị 2" --admin`, đăng nhập `admin2` rồi đặt lại mật khẩu trong menu Tài khoản |
