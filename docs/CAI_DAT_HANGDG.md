# Cài đặt lên VPS Vietnix với tên miền hangdg.com

Hướng dẫn riêng cho cấu hình đã mua: **VPS Vietnix LINUX 2 (Ubuntu 24.04)** + tên miền **hangdg.com**.
Làm theo thứ tự. Kết quả cuối cùng: cả nhóm truy cập **https://hangdg.com**, có ổ khoá HTTPS hợp lệ
(không còn cảnh báo bảo mật).

Thời gian thao tác: ~30 phút. Lấy dữ liệu lần đầu máy tự chạy thêm vài giờ.

Ký hiệu dùng trong tài liệu:

- `<IP>` = địa chỉ IP của VPS, có trong email Vietnix gửi khi kích hoạt VPS (ví dụ `103.x.x.x`)
- Lệnh trong khung xám: sao chép rồi dán (trong cửa sổ PowerShell/SSH: **chuột phải** để dán)

---

## Bước 1 – Trỏ tên miền về VPS (làm trước tiên)

DNS cần 5–30 phút (đôi khi vài giờ) để có hiệu lực, nên làm ngay bước này, trong lúc chờ thì làm các bước sau.

1. Đăng nhập trang quản lý tên miền nơi bạn mua `hangdg.com` (nếu mua ở Vietnix: https://portal.vietnix.vn →
   **Dịch vụ của tôi / Tên miền** → chọn `hangdg.com` → **Quản lý DNS**).
2. Tạo (hoặc sửa nếu đã có) **2 bản ghi**:

   | Loại (Type) | Tên (Host/Name) | Giá trị (Value/Points to) | TTL |
   |---|---|---|---|
   | **A** | `@` | `<IP>` | 300 (hoặc mặc định) |
   | **A** | `www` | `<IP>` | 300 (hoặc mặc định) |

3. Nếu đang có bản ghi **A** hoặc **CNAME** khác cho `@` / `www` (ví dụ trỏ tới trang “đậu tên miền” của nhà cung
   cấp) → **xoá** đi. Mỗi tên chỉ để 1 bản ghi A trỏ về `<IP>`.
4. Lưu lại.

**Kiểm tra** (trên máy tính của bạn, mở PowerShell):

```powershell
nslookup hangdg.com
```

Đúng khi phần `Address:` cuối cùng hiện **đúng `<IP>`** của VPS. Nếu chưa, đợi thêm rồi thử lại – trong lúc đó cứ làm tiếp.

---

## Bước 2 – Tạo token GitHub (để VPS tải được mã nguồn)

1. Đăng nhập https://github.com (tài khoản `tienlv36-svg`) → ảnh đại diện → **Settings** → **Developer settings**
   → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
2. *Token name* `vps-hangdg`; *Expiration* 1 năm; *Repository access* → **Only select repositories** → `autolist`;
   *Permissions* → **Contents: Read-only** → **Generate token**.
3. Sao chép chuỗi `github_pat_...` (chỉ hiện một lần), lưu vào chỗ an toàn.

---

## Bước 3 – Đăng nhập vào VPS

Mở **PowerShell** (Windows) hoặc **Terminal** (macOS):

```bash
ssh root@<IP>
```

Gõ `yes` nếu được hỏi, rồi nhập mật khẩu root trong email Vietnix (gõ không hiện ký tự, gõ xong Enter).
Thành công khi thấy dấu nhắc `root@...:~#`.

---

## Bước 4 – Kiểm tra VPS (1 phút)

**4a. Hệ điều hành phải là Ubuntu 24.04** (hoặc 22.04):

```bash
grep PRETTY_NAME /etc/os-release
```

Đúng: `PRETTY_NAME="Ubuntu 24.04... LTS"`.

**4b. Cổng 80/443 phải đang trống** (không có web server cài sẵn):

```bash
ss -ltnp | grep -E ':(80|443) ' || echo "TRỐNG - OK"
```

Đúng: in ra `TRỐNG - OK`. Nếu thấy `nginx`, `apache2` hoặc `httpd` → lúc đặt hàng đã chọn bản cài kèm
aaPanel/1Panel. Vào portal Vietnix → VPS → **Cài lại hệ điều hành (Reinstall)** → chọn **`Ubuntu-24.04-LTS-x64`**
(bản không có chữ Aapanel/1Panel), rồi làm lại từ Bước 3.

**4c. VPS kết nối được tới 2 nguồn dữ liệu:**

```bash
curl -sI https://dgts.moj.gov.vn | head -1; curl -sI https://taisancong.vn | head -1
```

Đúng: 2 dòng có `200` (hoặc `301`/`302`). Nếu báo lỗi kết nối → liên hệ Vietnix (1800 1093).

---

## Bước 5 – Cập nhật hệ điều hành

```bash
apt update && apt upgrade -y
```

Nếu hiện bảng tím hỏi khởi động lại dịch vụ → nhấn **Enter**. Nếu cuối cùng có `*** System restart required ***`:

```bash
reboot
```

rồi đợi 1 phút và đăng nhập lại (Bước 3).

---

## Bước 6 – Tải mã nguồn

```bash
git clone https://github.com/tienlv36-svg/autolist.git /root/autolist
```

`Username` → `tienlv36-svg`; `Password` → dán token `github_pat_...` (không hiện ký tự) → Enter.

---

## Bước 7 – Cài đặt (1 lệnh)

Thay `email-cua-ban@gmail.com` bằng email của bạn (Let's Encrypt gửi thông báo nếu chứng chỉ có vấn đề):

```bash
sudo DOMAIN=hangdg.com EMAIL=email-cua-ban@gmail.com bash /root/autolist/deploy/install-vps.sh
```

Mất 3–5 phút, in lần lượt `=== 1/8 ===` … `=== 8/8 ===`. Những dòng cần thấy:

| Mục | Dòng đúng |
|---|---|
| 3/8 | `58 passed` (hoặc số lớn hơn) |
| 5/8 | `auction-web: active` |
| 6/8 | `Caddy – HTTPS thật (Let's Encrypt) cho hangdg.com` và `caddy: active` |
| 8/8 | hỏi tên đăng nhập quản trị (Enter = `admin`), họ tên, mật khẩu 2 lần (≥ 8 ký tự) |

Kết thúc: `XONG. Mở trình duyệt:  https://hangdg.com`.

> **Nếu mục 6/8 báo** `(!) hangdg.com chưa trỏ về <IP>` → DNS ở Bước 1 chưa có hiệu lực. Script tạm cấu hình
> truy cập bằng `https://<IP>` (có cảnh báo chứng chỉ). Khi `nslookup hangdg.com` đã ra đúng IP, chạy lại
> **chỉ một lệnh** dưới đây (an toàn, giữ nguyên mọi thứ đã cài):
>
> ```bash
> sudo bash /root/autolist/deploy/install-vps.sh
> ```

---

## Bước 8 – Mở phần mềm

Vào **https://hangdg.com** (hoặc `https://www.hangdg.com` – tự chuyển về `hangdg.com`).

- Lần đầu Caddy cần khoảng 30 giây để xin chứng chỉ. Nếu trình duyệt báo lỗi kết nối, đợi 1 phút rồi tải lại.
- Thanh địa chỉ có biểu tượng ổ khoá, không có cảnh báo.
- Đăng nhập bằng tài khoản quản trị vừa tạo. Danh sách còn trống – làm Bước 9.

---

## Bước 9 – Lấy dữ liệu lần đầu

Vẫn trong cửa sổ SSH. Mở phiên tmux (để việc chạy không dừng khi bạn tắt máy tính):

```bash
tmux new -s napdulieu
```

Chạy (mặc định lấy tin dgts 180 ngày gần nhất + toàn bộ taisancong):

```bash
sudo -u auction bash /opt/autolist/deploy/first-load.sh
```

Tách ra để máy tự chạy: nhấn **`Ctrl + B`**, thả tay, nhấn **`D`**. Có thể đóng cửa sổ.

Xem tiến độ bất cứ lúc nào (đăng nhập lại như Bước 3):

```bash
tail -n 30 /opt/autolist/data/first-load.log
```

| Giai đoạn | Thời gian ước tính |
|---|---|
| Danh sách dgts + taisancong | 1,5–3 giờ |
| Lọc BĐS, gom phiên → **từ đây đã xem được trên web** | vài phút |
| Lấy giá, tiền đặt trước, nơi có tài sản (dgts) | 5–15 giờ (tuỳ tốc độ dgts) |
| Hoàn tất | log có dòng `HOÀN TẤT` |

Nếu log có dòng `DỪNG:` → thường do mạng tới website nguồn; chạy lại lệnh `first-load.sh` (phần đã lấy không bị lấy lại).

---

## Bước 10 – Bật thu thập tự động

Khi log có `HOÀN TẤT`:

```bash
sudo systemctl enable --now auction-scheduler
```

Từ đây cứ 6 giờ phần mềm tự lấy tin mới, giá, gom phiên. Kiểm tra:

```bash
systemctl is-active auction-web auction-scheduler caddy
```

Đúng: 3 dòng `active`.

---

## Bước 11 – Tạo tài khoản nhân viên

Trên https://hangdg.com, đăng nhập quản trị → menu **Tài khoản** → **Tạo tài khoản** (tên đăng nhập không dấu,
ví dụ `lan.nguyen`; mật khẩu tạm ≥ 8 ký tự; quyền *Thành viên*). Gửi cho nhân viên: địa chỉ `https://hangdg.com`,
tên đăng nhập, mật khẩu tạm; dặn họ bấm vào tên mình (góc phải trên) để đổi mật khẩu.

Hướng dẫn sử dụng cho nhân viên: [HUONG_DAN.md – Phần C](HUONG_DAN.md#phần-c--hướng-dẫn-sử-dụng-cho-nhân-viên).

---

## Sau khi cài xong

- **Sao lưu** tự động 2:15 mỗi đêm vào `/opt/autolist/backups` (giữ 14 bản) + Vietnix sao lưu VPS hằng tuần.
  Mỗi tháng nên chép một bản về máy tính – xem [HUONG_DAN_VPS.md – Việc định kỳ](HUONG_DAN_VPS.md#việc-định-kỳ-cho-người-quản-trị).
- **Cập nhật phiên bản mới** (khi có thay đổi trên GitHub):
  ```bash
  cd /root/autolist && git pull && sudo bash deploy/install-vps.sh
  ```
  Tên miền được ghi nhớ, không cần gõ lại `DOMAIN=...`.
- **Chứng chỉ HTTPS** được Caddy tự gia hạn, không phải làm gì.
- **Đổi mật khẩu root** cho mạnh: `passwd`.
- Xử lý sự cố: bảng cuối [HUONG_DAN_VPS.md](HUONG_DAN_VPS.md#xử-lý-sự-cố).

| Hiện tượng riêng khi dùng tên miền | Cách xử lý |
|---|---|
| `https://hangdg.com` không vào được, `https://<IP>` vào được | DNS chưa trỏ đúng (Bước 1) – kiểm tra `nslookup`, rồi chạy lại `sudo bash /root/autolist/deploy/install-vps.sh` |
| Trình duyệt báo lỗi chứng chỉ với hangdg.com | Xem log: `journalctl -u caddy -n 50 --no-pager`. Thường do DNS mới đổi hoặc cổng 80 bị chặn – kiểm tra `ufw status` có `80/tcp ALLOW` |
| `www.hangdg.com` không chuyển hướng | Chưa có bản ghi A cho `www` lúc cài – thêm bản ghi rồi chạy lại script |
