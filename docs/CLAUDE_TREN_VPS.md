# Điều khiển VPS hangdg.com bằng Claude (Remote Control)

Sau khi làm xong, bạn mở **app Claude** (điện thoại / máy tính) hoặc **claude.ai/code**, chọn phiên **“VPS hangdg”** và
nhắn bằng tiếng Việt, ví dụ *“Kiểm tra tình hình lượt chạy đêm qua”*. Claude chạy lệnh **trực tiếp trên VPS** và trả
lời bạn. Lệnh có ảnh hưởng (xoá, sửa cấu hình, khởi động lại, cập nhật...) Claude sẽ **hỏi bạn duyệt trước**.

Claude trên VPS tự đọc file `CLAUDE.md` của phần mềm (cấu trúc hệ thống, lệnh vận hành, nguyên tắc dữ liệu, quy tắc an
toàn), nên hiểu hệ thống ngay từ đầu.

> **Yêu cầu:** tài khoản Claude gói **Pro** trở lên (bạn đang dùng Pro – được). Làm **sau khi đã cập nhật Đợt 1**
> (Phần A của `CAP_NHAT_DOT_1.md`) để VPS có sẵn `CLAUDE.md`.

---

## Bước 1 – Thêm bộ nhớ ảo (khuyến nghị)

Claude Code khuyến nghị máy có từ 4 GB RAM; VPS của bạn có ~3,8 GB và phần mềm thu thập cũng dùng RAM. Thêm 2 GB
bộ nhớ ảo cho an toàn (đăng nhập VPS bằng `ssh root@14.225.218.174` trước):

```bash
[ -f /swapfile ] || (fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab); free -h | grep -i swap
```

Đúng: dòng `Swap:` có khoảng `2.0Gi`.

## Bước 2 – Cài Claude Code

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Lệnh **không hiện tiến trình** khi tải – đợi tới khi dấu nhắc hiện lại (khoảng 1 phút). Sau đó:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && source ~/.bashrc && claude --version
```

Đúng: in ra số phiên bản, ví dụ `2.1.211 (Claude Code)`.

## Bước 3 – Đăng nhập tài khoản Claude (1 lần)

```bash
cd /opt/autolist && claude
```

1. Chọn giao diện (Enter để mặc định), chọn cách đăng nhập **tài khoản Claude (gói trả phí / Claude account with
   subscription)**.
2. VPS không có trình duyệt nên Claude Code in ra **một đường link**: sao chép link đó, mở trên máy tính/điện thoại,
   đăng nhập tài khoản Claude của bạn, bấm **Cho phép (Authorize)**. Nếu trang web hiện **một mã**, sao chép mã và dán
   lại vào cửa sổ SSH (chuột phải), Enter.
3. Khi được hỏi có tin tưởng thư mục `/opt/autolist` không (**Trust this folder?**) → chọn **Yes**.
4. Thấy khung chat của Claude là xong. Gõ `/exit` rồi Enter để thoát.

## Bước 4 – Bật Remote Control (chạy nền trong tmux)

Mở phiên tmux tên `claude`:

```bash
tmux new -s claude
```

Trong tmux, chạy:

```bash
cd /opt/autolist && claude remote-control --name "VPS hangdg"
```

- Lần đầu hỏi `Enable Remote Control? (y/n)` → gõ `y`, Enter. Nếu hỏi `Trust /opt/autolist? [y/N]` → `y`.
- Màn hình hiện **đường link** (nhấn **phím cách** để hiện **mã QR**) và chờ kết nối.

Tách khỏi tmux để nó chạy nền: nhấn **`Ctrl + B`**, thả tay, nhấn **`D`**. Giờ có thể đóng cửa sổ SSH.

## Bước 5 – Kết nối từ app Claude

Một trong các cách:

- **Điện thoại:** mở app Claude → **Code** → chọn phiên **VPS hangdg** (hoặc quét mã QR ở Bước 4).
- **Máy tính:** vào **claude.ai/code** (hoặc app Claude Desktop → Code) → chọn **VPS hangdg**.

Thử nhắn: *“Kiểm tra 3 dịch vụ và lượt thu thập gần nhất”*.

---

## Dùng hằng ngày – ví dụ yêu cầu

| Bạn nhắn | Claude làm |
|---|---|
| “Tình hình lượt chạy đêm qua thế nào?” | Đọc nhật ký, bảng lượt thu thập, báo số tin mới, lỗi |
| “Lấy dữ liệu lần đầu xong chưa? Còn bao lâu?” | Đọc `first-load.log`, ước tính |
| “Cập nhật lên phiên bản mới nhất” | Kiểm tra không có tiến trình đang ghi, sao lưu, `git pull` + script cài đặt (hỏi bạn duyệt) |
| “Quét lịch sử giá thêm 1000 tài sản” | Chạy `history-scan` trong tmux, báo cách theo dõi |
| “Ổ cứng còn bao nhiêu? Sao lưu gần nhất lúc nào?” | `df`, danh sách bản sao lưu |
| “Ai đăng nhập web sai nhiều lần hôm nay?” | Đọc bảng đăng nhập sai (chỉ đọc), báo IP / tên đã thử |
| “Có bao nhiêu tài sản ngân hàng ở Hà Nội còn hạn đăng ký, giảm trên 20%?” | Truy vấn CSDL (chỉ đọc), trả số liệu |
| “Trang web báo lỗi 502” | Xem log `auction-web`, tìm nguyên nhân, đề xuất cách sửa |

Việc liên quan **mật khẩu** (tạo tài khoản, đặt lại mật khẩu) làm trên web → menu **Tài khoản**, không nhờ Claude, để
mật khẩu không nằm trong nội dung trò chuyện.

Claude **không sửa mã nguồn trên VPS** (sẽ lệch với GitHub). Muốn thêm tính năng/sửa lỗi phần mềm: nhờ Claude trên
VPS mô tả vấn đề kèm log, rồi gửi cho phiên phát triển; sau đó nhắn Claude trên VPS *“cập nhật phiên bản mới”*.

## Khi phiên “VPS hangdg” không hiện / mất kết nối

Phiên chạy chừng nào tiến trình `claude remote-control` trong tmux còn chạy. Nó dừng khi: VPS khởi động lại, mất mạng
khoảng 10 phút, hoặc bạn tắt nó. Bật lại (SSH vào VPS):

```bash
tmux kill-session -t claude 2>/dev/null; tmux new -d -s claude 'cd /opt/autolist && claude remote-control --name "VPS hangdg"' && sleep 5 && tmux ls
```

Đúng: có dòng `claude: 1 windows`. Mở lại app Claude → Code → **VPS hangdg**.

Tắt hẳn Remote Control:

```bash
tmux kill-session -t claude
```

## Bảo mật cần biết

- VPS chỉ **kết nối ra ngoài** tới Anthropic, không mở thêm cổng nào.
- Khi Remote Control đang kết nối, nội dung trò chuyện (tin nhắn, trả lời, lệnh đã chạy) được lưu trên máy chủ
  Anthropic – **không dán mật khẩu, token** vào cuộc trò chuyện.
- Ai đăng nhập được **tài khoản Claude của bạn** thì điều khiển được VPS qua phiên này: bật xác thực 2 lớp cho tài
  khoản Claude/Google, không chia sẻ tài khoản.
- Phần mềm có sẵn quy tắc quyền (`.claude/settings.json`): các lệnh chỉ xem (trạng thái, nhật ký, dung lượng) chạy
  ngay; các lệnh xoá dữ liệu/sao lưu và đọc file bí mật bị chặn; mọi lệnh khác Claude phải hỏi bạn. Chế độ quyền
  mặc định là **hỏi trước** (`default`), không dùng *auto mode* trên VPS sản xuất.
