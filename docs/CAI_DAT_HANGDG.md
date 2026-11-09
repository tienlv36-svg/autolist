# Cài đặt lên VPS Vietnix với tên miền hangdg.com – hướng dẫn chi tiết

Hướng dẫn dành cho người **chưa từng làm việc với máy chủ**. Làm đúng thứ tự từ Phần 0 đến Phần 11.
Mỗi bước có: **làm gì** → **lệnh để dán** → **kết quả đúng trông thế nào** → **nếu sai thì làm gì**.

Kết quả cuối cùng: cả nhóm vào **https://hangdg.com**, có ổ khoá HTTPS hợp lệ.

| Phần | Việc | Thời gian |
|---|---|---|
| 0 | Chuẩn bị, tìm thông tin VPS | 5 phút |
| 1 | Trỏ tên miền về VPS | 5 phút (+ chờ DNS) |
| 2 | Tạo token GitHub | 5 phút |
| 3 | Đăng nhập VPS | 2 phút |
| 4 | Kiểm tra VPS | 2 phút |
| 5 | Cập nhật hệ điều hành | 3–10 phút |
| 6 | Tải mã nguồn | 1 phút |
| 7 | Cài đặt | 3–5 phút |
| 8 | Mở phần mềm | 1 phút |
| 9 | Lấy dữ liệu lần đầu | máy tự chạy 6–18 giờ |
| 10 | Bật thu thập tự động | 1 phút |
| 11 | Tạo tài khoản nhân viên | 2 phút/người |

---

## Phần 0 – Chuẩn bị

### 0.1. Tìm 2 thông tin của VPS

Khi VPS được kích hoạt, Vietnix gửi email (tới email đăng ký tài khoản Vietnix) có các thông tin đăng nhập VPS.
Tìm và chép ra giấy/Notepad:

| Thông tin | Ví dụ | Trong tài liệu này gọi là |
|---|---|---|
| Địa chỉ IP (IPv4) | `103.199.17.25` | `<IP>` |
| Tên đăng nhập | `root` | `root` |
| Mật khẩu | `aB3$...` | mật khẩu root |

Không thấy email? Đăng nhập https://portal.vietnix.vn → **Dịch vụ của tôi** → chọn VPS → trang chi tiết dịch vụ có IP
(và thường có mục xem/đặt lại mật khẩu). Vẫn không thấy: gọi Vietnix **1800 1093**.

> **Mỗi khi tài liệu ghi `<IP>`, hãy thay bằng IP thật** và **bỏ luôn dấu `<` `>`**.
> Ví dụ `ssh root@<IP>` → `ssh root@103.199.17.25`.

### 0.2. Cách sao chép và dán lệnh

1. Trong tài liệu, bôi đen lệnh trong khung xám (hoặc bấm nút copy ở góc khung trên GitHub) → `Ctrl + C`.
2. Trong cửa sổ PowerShell/SSH: **bấm chuột phải** là dán (hoặc `Ctrl + V` nếu dùng *Windows Terminal*).
3. Nhấn **Enter** để chạy.
4. Đợi đến khi dấu nhắc (`PS C:\...>` hoặc `root@...:~#`) hiện lại mới dán lệnh tiếp theo.

**Gõ mật khẩu trong cửa sổ đen không hiện ký tự gì** (cũng không hiện dấu `*`) – đó là bình thường, cứ gõ (hoặc
chuột phải để dán) rồi Enter.

---

## Phần 1 – Trỏ tên miền hangdg.com về VPS

Làm phần này **đầu tiên**: DNS cần từ vài phút đến vài giờ để có hiệu lực, trong lúc chờ ta làm các phần khác.

### 1.1. Nếu tên miền mua ở Vietnix

1. Đăng nhập https://portal.vietnix.vn.
2. Menu bên trái → **Quản lý tên miền** → bấm vào `hangdg.com`. Trang tên miền có 4 tab:
   **Tổng quan · Hồ sơ tên miền · Nameservers · Quản lý DNS**.
3. Tab **Nameservers**: phải đang chọn **“Sử dụng Nameserver mặc định của Vietnix”** với
   `ns1.vietnix.net` và `ns2.vietnix.net` → **giữ nguyên, không bấm “Thay đổi Nameservers”**.
   (Nếu đang chọn *Nameserver tuỳ chọn* → chọn lại *mặc định của Vietnix* → bấm **Thay đổi Nameservers**.)
4. Mở tab **Quản lý DNS**.
5. Xem danh sách bản ghi hiện có. **Xoá** các bản ghi có *Name/Host* là `@` (hoặc `hangdg.com`) và `www`
   (hoặc `www.hangdg.com`) nếu *Type* là **A**, **AAAA** hoặc **CNAME** – thường là bản ghi “đậu tên miền” mặc định.
   **Không xoá** bản ghi MX, TXT, NS.
6. Bấm nút thêm bản ghi (dấu **+**), điền:
   - **Type**: `A`
   - **Name**: `@` (một số giao diện để trống hoặc ghi `hangdg.com`)
   - **Content** (hoặc *Value/IPv4*): `<IP>`
   - **TTL**: chọn nhỏ nhất có thể (ví dụ *1 minute* / 300)
   - Bấm **Add / Lưu**.
7. Thêm bản ghi thứ hai giống hệt nhưng **Name** = `www` → **Add / Lưu**.

> Nếu giao diện tab *Quản lý DNS* khác mô tả, gọi Vietnix 1800 1093 và nói: *“tạo 2 bản ghi A cho hangdg.com và
> www.hangdg.com trỏ về IP VPS”*.

### 1.2. Nếu tên miền mua ở nơi khác (Mắt Bão, PA Việt Nam, GoDaddy...)

Đăng nhập trang quản lý tên miền ở nơi đó → mục *Quản lý DNS / DNS Management / Zone* → tạo đúng 2 bản ghi như bảng:

| Type | Name/Host | Value | TTL |
|---|---|---|---|
| A | `@` | `<IP>` | 300 |
| A | `www` | `<IP>` | 300 |

và xoá bản ghi A/AAAA/CNAME cũ của `@`, `www`.

### 1.3. Kiểm tra DNS (làm lại vài lần trong lúc chờ)

Trên **máy tính của bạn**, mở PowerShell (Phần 3.1 có cách mở) và chạy:

```powershell
nslookup hangdg.com 8.8.8.8
```

**Kết quả đúng** – phần cuối có đúng IP VPS:

```
Server:  dns.google
Address:  8.8.8.8

Non-authoritative answer:
Name:    hangdg.com
Address:  103.199.17.25        <- phải đúng <IP> của bạn
```

**Chưa đúng** (không có dòng `Address:` thứ hai, báo `Non-existent domain`, hoặc IP khác) → DNS chưa có hiệu lực
hoặc tạo sai bản ghi. Kiểm tra lại 1.1/1.2, rồi **cứ làm tiếp các phần sau**, quay lại kiểm tra trước Phần 7.

Kiểm tra cả `www`:

```powershell
nslookup www.hangdg.com 8.8.8.8
```

---

## Phần 2 – Tạo token GitHub

Repo mã nguồn `autolist` đang để Private. VPS cần một **token** (giống mật khẩu riêng, chỉ được đọc đúng repo này)
để tải mã nguồn.

1. Vào https://github.com, đăng nhập tài khoản **tienlv36-svg**.
2. Bấm **ảnh đại diện** (góc trên bên phải) → **Settings**.
3. Kéo xuống cuối menu bên trái → **Developer settings**.
4. Bên trái chọn **Personal access tokens** → **Fine-grained tokens** → nút **Generate new token**
   (GitHub có thể hỏi lại mật khẩu / mã xác thực).
5. Điền:
   - **Token name**: `vps-hangdg`
   - **Expiration**: chọn *Custom* → 1 năm sau (hoặc *No expiration*)
   - **Repository access**: chọn **Only select repositories** → ô *Select repositories* → chọn **`tienlv36-svg/autolist`**
   - **Permissions** → phần *Repository permissions* → tìm **Contents** → chọn **Read-only**
     (giao diện mới: bấm *Add permissions* → tích *Contents* → chọn *Read-only*)
6. Kéo xuống bấm **Generate token** → xác nhận.
7. GitHub hiện chuỗi bắt đầu bằng **`github_pat_`**. Bấm biểu tượng copy, **dán vào Notepad và lưu lại ngay** –
   đóng trang là không xem lại được nữa (mất thì tạo token mới).

---

## Phần 3 – Đăng nhập vào VPS

### 3.1. Mở PowerShell (Windows 10/11)

Bấm phím **Windows** → gõ `powershell` → bấm **Windows PowerShell**. Cửa sổ xanh/đen hiện ra với dòng
`PS C:\Users\TenBan>`.
(macOS: mở **Terminal** trong *Applications → Utilities*.)

### 3.2. Kết nối

```powershell
ssh root@<IP>
```

**Lần đầu** sẽ hiện:

```
The authenticity of host '103.199.17.25 (103.199.17.25)' can't be established.
ED25519 key fingerprint is SHA256:xxxxxxxx.
Are you sure you want to continue connecting (yes/no/[fingerprint])?
```

→ gõ **`yes`** rồi Enter. Sau đó:

```
root@103.199.17.25's password:
```

→ dán/gõ **mật khẩu root** (không hiện ký tự) → Enter.

**Đúng** khi thấy dấu nhắc dạng:

```
root@vps-xxxx:~#
```

| Báo lỗi | Nguyên nhân / xử lý |
|---|---|
| `Permission denied, please try again.` | Sai mật khẩu – thử lại; chú ý chữ hoa/thường. Quên → đặt lại mật khẩu trong Portal Vietnix |
| `Connection timed out` / `Connection refused` | Sai IP, hoặc VPS chưa chạy – kiểm tra trên Portal |
| `'ssh' is not recognized` | Windows quá cũ – cài bản cập nhật Windows, hoặc dùng phần mềm PuTTY |
| `WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED` | Bạn đã cài lại hệ điều hành VPS. Chạy `ssh-keygen -R <IP>` trên máy tính rồi `ssh` lại |

> Từ đây đến hết Phần 10, **mọi lệnh đều dán vào cửa sổ đang có dấu nhắc `root@...:~#`** này.
> Lỡ đóng cửa sổ thì mở PowerShell và `ssh root@<IP>` lại.

---

## Phần 4 – Kiểm tra VPS (1 lệnh)

```bash
grep PRETTY_NAME /etc/os-release; ss -ltnp | grep -E ':(80|443) ' || echo "CONG 80/443: TRONG - OK"; curl -s -o /dev/null -w "dgts: %{http_code}\n" https://dgts.moj.gov.vn; curl -s -o /dev/null -w "taisancong: %{http_code}\n" https://taisancong.vn; free -h | grep Mem; df -h / | tail -1
```

**Kết quả đúng** (số có thể khác chút):

```
PRETTY_NAME="Ubuntu 24.04.x LTS"
CONG 80/443: TRONG - OK
dgts: 200
taisancong: 200
Mem:           3.8Gi       ...
/dev/vda1        39G  ...
```

| Dòng | Đúng | Nếu sai |
|---|---|---|
| `PRETTY_NAME` | `Ubuntu 24.04...` (22.04 cũng được) | Hệ điều hành khác → Portal Vietnix → VPS → **Cài lại hệ điều hành (Reinstall)** → chọn **`Ubuntu-24.04-LTS-x64`** → làm lại từ Phần 3 |
| Cổng 80/443 | `TRONG - OK` | Thấy `nginx`/`apache2`/`httpd` → lúc đặt hàng đã chọn bản kèm aaPanel/1Panel → **Cài lại hệ điều hành** như trên, chọn bản **không** có chữ Aapanel/1Panel |
| `dgts:` / `taisancong:` | `200` (hoặc `301`, `302`) | `000` → VPS không kết nối được tới nguồn dữ liệu → báo Vietnix (1800 1093) |
| `Mem` | khoảng `3.8Gi` | — |
| ổ `/` | khoảng `39G` | — |

---

## Phần 5 – Cập nhật hệ điều hành

Lệnh dưới đây cập nhật **không bật hộp thoại hỏi** (tự chọn phương án an toàn):

```bash
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=a; apt-get update && apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade
```

Chữ chạy liên tục 3–10 phút. **Đúng** khi dấu nhắc `root@...:~#` hiện lại, các dòng cuối không có chữ `E:` hay
`Error`.

> Nếu vẫn hiện bảng màu tím/xanh hỏi *“Which services should be restarted?”* hay *“Pending kernel upgrade”* →
> nhấn **Enter**. Nếu hỏi về file cấu hình (*“What do you want to do about modified configuration file...”*) → chọn
> **keep the local version currently installed** → Enter.

Kiểm tra có cần khởi động lại không:

```bash
[ -f /var/run/reboot-required ] && echo "CAN KHOI DONG LAI" || echo "KHONG CAN KHOI DONG LAI"
```

Nếu in `CAN KHOI DONG LAI`:

```bash
reboot
```

Cửa sổ báo `Connection ... closed`. Đợi **1–2 phút**, rồi đăng nhập lại:

```powershell
ssh root@<IP>
```

---

## Phần 6 – Tải mã nguồn

Lưu token để lần cập nhật sau không phải nhập lại (token lưu trong file chỉ root đọc được):

```bash
git config --global credential.helper store
```

Tải mã nguồn:

```bash
git clone https://github.com/tienlv36-svg/autolist.git /root/autolist
```

Khi được hỏi:

```
Username for 'https://github.com': tienlv36-svg          <- gõ tên này, Enter
Password for 'https://tienlv36-svg@github.com':          <- dán token github_pat_... (không hiện), Enter
```

**Kết quả đúng:**

```
Cloning into '/root/autolist'...
remote: Enumerating objects: ...
Receiving objects: 100% (...), done.
Resolving deltas: 100% (...), done.
```

| Báo lỗi | Xử lý |
|---|---|
| `Authentication failed` / `Invalid username or token` | Dán nhầm mật khẩu GitHub thay vì token, hoặc token thiếu quyền *Contents: Read-only* cho repo `autolist` → làm lại Phần 2 rồi chạy lại lệnh `git clone` |
| `destination path '/root/autolist' already exists` | Đã tải trước đó – bỏ qua, sang Phần 7 |

---

## Phần 7 – Cài đặt phần mềm (1 lệnh)

**Trước khi chạy:** kiểm tra lại DNS (Phần 1.3) đã ra đúng IP. Nếu chưa, vẫn chạy được – xem ô *“Nếu DNS chưa có
hiệu lực”* bên dưới.

Thay `email-cua-ban@gmail.com` bằng email thật của bạn (để Let's Encrypt báo nếu chứng chỉ HTTPS có vấn đề):

```bash
sudo DOMAIN=hangdg.com EMAIL=email-cua-ban@gmail.com bash /root/autolist/deploy/install-vps.sh
```

Script chạy 3–5 phút, in lần lượt 8 mục. **Kết quả đúng** (đã rút gọn):

```
=== 1/8 Cài gói hệ thống ===
=== 2/8 Tài khoản hệ thống & mã nguồn ===
=== 3/8 Môi trường Python & thư viện ===
59 passed, 1 warning in 6.62s                       <- phải có chữ "passed", không có "failed"
=== 4/8 Cấu hình chạy thật ===
=== 5/8 Dịch vụ chạy nền & sao lưu ===
  auction-web: active | auction-scheduler: inactive  <- "inactive" ở đây là đúng (bật ở Phần 10)
  Sao lưu tự động 2:15 mỗi đêm vào /opt/autolist/backups
=== 6/8 Caddy – HTTPS thật (Let's Encrypt) cho hangdg.com ===
  Cấu hình Caddy hợp lệ
  caddy: active
=== 7/8 Tường lửa ===
Status: active
To                         Action      From
22/tcp (OpenSSH)           ALLOW       Anywhere
80/tcp                     ALLOW       Anywhere
443/tcp                    ALLOW       Anywhere
=== 8/8 Tài khoản quản trị web ===
  Tên đăng nhập quản trị [admin]:
```

**Mục 8/8 hỏi 4 câu:**

| Câu hỏi | Trả lời |
|---|---|
| `Tên đăng nhập quản trị [admin]:` | Enter (dùng `admin`) hoặc gõ tên khác, chữ thường không dấu |
| `Họ tên:` | ví dụ `Nguyen Van A` (gõ có dấu cũng được) |
| `Password:` | đặt mật khẩu ≥ 8 ký tự (không hiện ký tự) – **ghi lại** |
| `Repeat for confirmation:` | gõ lại mật khẩu |

Kết thúc:

```
Đã tạo admin (quản trị)
===================================================================
 XONG. Mở trình duyệt:  https://hangdg.com
 (lần đầu Caddy cần ~30 giây để xin chứng chỉ; nếu báo lỗi, đợi 1 phút rồi tải lại)
 Bước tiếp theo: lấy dữ liệu lần đầu – sudo -u auction bash /opt/autolist/deploy/first-load.sh (trong tmux)
===================================================================
```

> **Nếu DNS chưa có hiệu lực**, mục 6/8 sẽ báo:
> ```
>   (!) hangdg.com chưa trỏ về 103.199.17.25 (hiện: ...)
>       -> tạm dùng HTTPS trên IP. Tạo bản ghi A rồi chạy lại script sau 5-30 phút.
> === 6/8 Caddy – HTTPS trên địa chỉ IP 103.199.17.25 ===
> ```
> Không sao – phần mềm vẫn cài đầy đủ, tạm truy cập bằng `https://<IP>` (trình duyệt cảnh báo chứng chỉ, bấm
> *Nâng cao → Tiếp tục*). Khi `nslookup hangdg.com 8.8.8.8` đã ra đúng IP, chạy lại **chỉ lệnh này** (an toàn, giữ
> nguyên mọi thứ, tự nhớ tên miền):
> ```bash
> sudo bash /root/autolist/deploy/install-vps.sh
> ```

| Báo lỗi | Xử lý |
|---|---|
| Mục 3/8 có chữ `failed` | Chụp màn hình gửi người hỗ trợ kỹ thuật – không làm tiếp |
| `(!) Không cài được caddy` | Chạy `apt-get install -y caddy` xem lỗi, chụp màn hình gửi hỗ trợ |
| `caddy: failed` hoặc `activating` | Xem lý do: `journalctl -u caddy -n 30 --no-pager` (thường do cổng 80/443 bị chiếm – xem Phần 4) |
| Lỡ tắt cửa sổ giữa chừng | Đăng nhập lại, chạy lại đúng lệnh cài đặt ở trên (chạy lại an toàn) |

---

## Phần 8 – Mở phần mềm

1. Trên máy tính, mở Chrome/Edge/Cốc Cốc → gõ **`https://hangdg.com`** → Enter.
2. **Đúng:** thanh địa chỉ có biểu tượng ổ khoá/biểu tượng cài đặt (không có chữ đỏ “Không bảo mật”), hiện trang
   **◆ Đấu giá BĐS – Đăng nhập để tiếp tục**.
3. Đăng nhập bằng tài khoản quản trị vừa tạo → vào trang **Tài sản** báo **0 tài sản** (đúng, chưa có dữ liệu).
4. Thử `https://www.hangdg.com` → phải tự chuyển về `https://hangdg.com`.

| Hiện tượng | Xử lý |
|---|---|
| *This site can't be reached* / *ERR_CONNECTION_REFUSED* ngay sau khi cài | Đợi 1 phút (Caddy đang xin chứng chỉ) rồi tải lại |
| Cảnh báo chứng chỉ với hangdg.com | DNS chưa đúng lúc cài → kiểm tra Phần 1.3, chạy lại `sudo bash /root/autolist/deploy/install-vps.sh` |
| `www.hangdg.com` không vào được | Thiếu bản ghi A cho `www` (Phần 1) → thêm rồi chạy lại lệnh trên |
| *502 Bad Gateway* | Web chưa chạy: `systemctl restart auction-web`, đợi 10 giây, tải lại |

---

## Phần 9 – Lấy dữ liệu lần đầu

Việc này chạy **nhiều giờ**, nên dùng **tmux** – một “cửa sổ ảo” trên VPS vẫn chạy tiếp khi bạn tắt máy tính.

### 9.1. Mở tmux

```bash
tmux new -s napdulieu
```

Cửa sổ xoá trắng, có **thanh màu xanh ở đáy** ghi `[napdulieu]` – bạn đang ở trong tmux.

### 9.2. Chạy lấy dữ liệu

Mặc định lấy tin dgts đăng trong **180 ngày** gần nhất + toàn bộ taisancong:

```bash
sudo -u auction bash /opt/autolist/deploy/first-load.sh
```

(Muốn lấy 1 năm: dùng `sudo -u auction env DAYS=365 bash /opt/autolist/deploy/first-load.sh` thay cho lệnh trên.)

**Đúng** khi thấy các dòng dạng:

```
Lấy dữ liệu từ 2026-05-13 | nhật ký: data/first-load.log
[2026-11-09 10:00:01] >>> crawl -s dgts --since 2026-05-13 --no-detail -p 5000
                    INFO     [dgts] tổng số tin khớp: 120000 (240 trang)
                    INFO     [dgts] trang 1: 500 tin (0 đã có)
                    INFO     [dgts] trang 2: 500 tin (0 đã có)
...
```

### 9.3. Tách khỏi tmux để máy tự chạy

Nhấn **`Ctrl + B`** (giữ Ctrl, bấm B, **thả cả hai**), sau đó nhấn **`D`**.
Màn hình trở về cửa sổ thường, báo `[detached (from session napdulieu)]`. Giờ có thể đóng PowerShell, tắt máy tính.

### 9.4. Xem tiến độ (bất cứ lúc nào)

Đăng nhập lại (`ssh root@<IP>`), rồi:

```bash
tail -n 25 /opt/autolist/data/first-load.log
```

Hoặc quay lại màn hình đang chạy: `tmux attach -t napdulieu` (thoát ra lại bằng `Ctrl + B` rồi `D`).

Các giai đoạn trong nhật ký:

| Dòng `>>>` | Việc | Thời gian ước tính (180 ngày) |
|---|---|---|
| `crawl -s dgts ...` | danh sách tin dgts | 30–60 phút |
| `crawl -s taisancong ...` | danh sách tin taisancong | 1–2 giờ |
| `dedupe`, `re-build` | đánh dấu trùng, lọc BĐS, gom phiên – **xong bước này là đã xem được trên web** | vài phút |
| `enrich -s dgts ...` | lấy giá, tiền đặt trước, nơi có tài sản | **lâu nhất: 5–15 giờ** |
| `enrich -s taisancong ...` | chi tiết taisancong | 1–2 giờ |
| `tag-types`, `re-build` | loại tài sản chính thức, tính lại giá phiên / % giảm | 10–20 phút |

**Xong** khi dòng cuối là:

```
[2026-11-09 23:40:12] HOÀN TẤT. Bật thu thập tự động: sudo systemctl enable --now auction-scheduler
```

| Hiện tượng | Xử lý |
|---|---|
| Nhật ký có `DỪNG: bước '...' lỗi` | Thường do mạng tới dgts/taisancong. Kiểm tra `curl -s -o /dev/null -w "%{http_code}\n" https://dgts.moj.gov.vn` (phải `200`), rồi chạy lại lệnh 9.2 – phần đã lấy không bị lấy lại |
| `tmux attach` báo `no sessions` | Script đã kết thúc (xong hoặc dừng) – xem nhật ký bằng lệnh `tail` ở trên |
| Muốn dừng giữa chừng | `tmux attach -t napdulieu` → `Ctrl + C`. Chạy lại lệnh 9.2 để tiếp tục |

---

## Phần 10 – Bật thu thập tự động

Khi nhật ký đã có `HOÀN TẤT`:

```bash
sudo systemctl enable --now auction-scheduler
```

Kiểm tra cả 3 dịch vụ:

```bash
systemctl is-active auction-web auction-scheduler caddy
```

**Đúng:**

```
active
active
active
```

Từ đây cứ **6 giờ một lần** phần mềm tự lấy tin mới, giá, gom phiên, tính % giảm. Không cần làm gì thêm.

---

## Phần 11 – Tạo tài khoản nhân viên

1. Vào `https://hangdg.com`, đăng nhập quản trị.
2. Menu trên cùng → **Tài khoản**.
3. Khung **Tạo tài khoản** ở cuối trang:
   - **Tên đăng nhập**: chữ thường không dấu, 3–64 ký tự, được dùng `.` `-` `_` (ví dụ `lan.nguyen`)
   - **Họ tên**: `Nguyễn Thị Lan`
   - **Mật khẩu**: mật khẩu tạm ≥ 8 ký tự
   - **Quyền**: *Thành viên* (chỉ chọn *Quản trị* cho người quản lý tài khoản)
   - Bấm **Tạo** → trang báo `Đã tạo tài khoản lan.nguyen`.
4. Gửi cho nhân viên: địa chỉ `https://hangdg.com`, tên đăng nhập, mật khẩu tạm. Dặn họ đăng nhập rồi **bấm vào tên
   mình ở góc phải trên** → đổi mật khẩu.

Hướng dẫn sử dụng cho nhân viên: [HUONG_DAN.md – Phần C](HUONG_DAN.md#phần-c--hướng-dẫn-sử-dụng-cho-nhân-viên).

---

## Sau khi cài xong

### Việc hằng tuần (2 phút)

```powershell
ssh root@<IP>
```

```bash
systemctl is-active auction-web auction-scheduler caddy; df -h / | tail -1; ls -lh /opt/autolist/backups | tail -3
```

Đúng: 3 dòng `active`; cột `Use%` của ổ dưới 80%; có file sao lưu `autolist_YYYYMMDD_0215.tar.gz` của các đêm gần nhất.

### Chép bản sao lưu về máy tính (hằng tháng)

Chạy trên **PowerShell của máy tính** (không phải trong SSH). Lệnh tải bản mới nhất về thư mục hiện tại:

```powershell
scp root@<IP>:/opt/autolist/backups/autolist_*.tar.gz .
```

(Lệnh này tải tất cả các bản đang có; xoá bớt bản cũ trên máy tính nếu không cần.)

### Cập nhật phiên bản mới

Khi có thông báo phiên bản mới trên GitHub:

```bash
cd /root/autolist && git pull && sudo bash deploy/install-vps.sh
```

Tên miền, dữ liệu, tài khoản, cấu hình đều được giữ nguyên; dịch vụ tự khởi động lại.

### Bảo mật

Đổi mật khẩu root thành mật khẩu mạnh (gõ 2 lần, không hiện ký tự):

```bash
passwd
```

Các việc khác (chỉ cho IP văn phòng truy cập, khôi phục từ sao lưu, xử lý sự cố chung): xem
[HUONG_DAN_VPS.md](HUONG_DAN_VPS.md).
