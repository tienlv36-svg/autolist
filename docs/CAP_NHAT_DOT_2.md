# Cập nhật VPS hangdg.com – Đợt 1 + Đợt 2 (làm một lần)

Bạn chưa cập nhật Đợt 1, nên làm **gộp cả hai đợt** theo các bước dưới đây. Sau khi xong mới làm tiếp phần
Telegram / Google Drive / khoá SSH (Phần B, C, D của `CAP_NHAT_DOT_1.md`).

**Có gì mới sau khi cập nhật**

| | |
|---|---|
| Sắp xếp “Sắp hết hạn đăng ký” | Sửa lỗi: tài sản **còn hạn** lên đầu (hạn gần nhất trước) → đã hết hạn → không có hạn. Ngày sai của nguồn (01/01/1970, năm 2003…) để trống |
| 🛒 Giỏ hàng | Mỗi tài khoản có giỏ riêng (nút **＋ Giỏ** trên thẻ tài sản / trang chi tiết, kèm ghi chú). Thành viên **không xem được** giỏ của nhau; **quản trị xem được giỏ của mọi tài khoản** (menu Giỏ hàng → Tất cả / từng người) |
| File đính kèm | Chỉ tài sản **còn hạn đăng ký**: tải về, **lưu lại** trên VPS, **đọc hết** (PDF chữ, PDF scan bằng OCR, .docx). Tài sản hết hạn không tải; khi **ra phiên mới** thì tự tải bổ sung |
| Số liệu từ tài liệu | Diện tích, kích thước, tờ/thửa ưu tiên lấy từ file, nhãn **“từ tài liệu”** (quy tắc: `QUY_UOC_GIA_PHIEN.md` mục 5) |
| Quét lịch sử giá | Tìm phiên cũ cho tài sản còn hạn để có giá phiên 1 và lịch sử giảm giá |
| Lịch tự động | **0:00 và 12:00** mỗi ngày; **sao lưu ngay sau mỗi lượt** (giữ 28 bản) |
| Quản trị | Trang **Hệ thống**, nút **Xuất Excel**, chặn dò mật khẩu, báo cáo Telegram |

---

## Bước 0 – Kiểm tra việc đang chạy

Đăng nhập VPS (`ssh root@14.225.218.174`), rồi:

```bash
tmux ls; tail -n 4 /opt/autolist/data/capnhat.log 2>/dev/null
```

- Thấy dòng `enrich` vẫn đang chạy (có `capnhat: 1 windows`, log chưa có lỗi) → **chờ**, lúc khác kiểm tra lại.
- Log báo lỗi kiểu `No such command 'history-scan'` → bình thường (bản cũ chưa có lệnh này). Đóng phiên tmux rồi
  làm tiếp:
  ```bash
  tmux kill-session -t capnhat 2>/dev/null; tmux ls
  ```
- Không có `capnhat` (bạn chưa chạy lệnh đó) → làm tiếp luôn.

## Bước 1 – Kiểm tra ổ cứng

```bash
df -h / ; du -sh /opt/autolist/data
```

Ghi lại cột `Size` và `Use%` (gửi Claude nếu `Use%` trên 60%). Phần mềm tự dừng tải file khi ổ dùng tới 85%.

## Bước 2 – Sao lưu

```bash
sudo -u auction /opt/autolist/deploy/backup.sh && ls -lh /opt/autolist/backups | tail -2
```

Đúng: thấy file `autolist_….tar.gz` vừa tạo.

## Bước 3 – Cập nhật phần mềm

```bash
cd /root/autolist && git pull && sudo bash deploy/install-vps.sh
```

Đúng (rút gọn):

```
  Lịch thu thập: 0:00 và 12:00 mỗi ngày
  ... passed ...                      <- không có "failed"
  auction-web: active | auction-scheduler: ...
  Sao lưu tự động sau mỗi lượt thu thập (0:00 và 12:00) vào /opt/autolist/backups
  fail2ban: active
```

Nếu thấy `(!) Lịch thu thập ... khác mặc định` → chụp gửi Claude.

Mở https://hangdg.com: menu có **🛒 Giỏ hàng**, **Hệ thống**; sắp xếp “Sắp hết hạn đăng ký” đưa tài sản còn hạn lên
đầu.

## Bước 4 – Chạy bù các bước mới (một lần, trong tmux)

Lệnh nối tiếp: **gom phiên lại** (áp dụng sửa ngày sai) → **lấy giá tin dgts còn thiếu** → **gom phiên** → **quét lịch sử
giá** 1.500 tài sản còn hạn → **tải + đọc file đính kèm** tài sản còn hạn (tối đa 4 giờ) → **bật lịch tự động**:

```bash
tmux new -d -s capnhat2 'cd /opt/autolist && A="sudo -u auction .venv/bin/auction"; { $A re-build && $A enrich -s dgts --realestate -n 50000 && $A re-build && $A history-scan -n 1500 && $A docs-fetch -m 240 && systemctl enable --now auction-scheduler && echo "=== XONG $(date) ==="; } 2>&1 | tee -a data/capnhat2.log'
```

Theo dõi (đóng cửa sổ SSH thoải mái, lệnh vẫn chạy):

```bash
tail -n 5 /opt/autolist/data/capnhat2.log
```

Lấy giá dgts lâu nhất (có thể 8–10 tiếng). Xong khi có dòng `=== XONG … ===`. Từ đó lịch **0:00 và 12:00** tự chạy,
mỗi lượt tự đọc tiếp file đính kèm còn lại và tự sao lưu.

Kiểm tra lịch đã bật:

```bash
systemctl is-active auction-scheduler && grep -n "cron:" /opt/autolist/config/settings.yaml
```

Đúng: `active` và `cron: "0 0,12 * * *"`.

## Bước 5 – Xem kết quả

- **Hệ thống**: số tài sản, “File đính kèm đã lưu”, “Tin đã đọc file … còn …”, sao lưu gần nhất.
- Một tài sản còn hạn: ô diện tích có nhãn **“từ tài liệu”**; cuối trang **File đính kèm đã lưu trên máy chủ**
  (bấm **xem chữ** để thấy phần mềm đọc được gì).
- **Giỏ hàng**: thử thêm vài tài sản, ghi chú; đăng nhập tài khoản thành viên để kiểm tra không thấy giỏ người khác.

## Tiếp theo

1. `CAP_NHAT_DOT_1.md` → **Phần B** (Telegram), **Phần C** (Google Drive), **Phần D** (khoá SSH). Bỏ qua Phần A
   (đã làm ở trên).
2. (Tuỳ chọn) đẩy cả file đính kèm lên Google Drive sau khi làm Phần C (Drive miễn phí 15 GB):
   ```bash
   sudo -u auction touch /opt/autolist/data/.drive_files
   ```
3. `CLAUDE_TREN_VPS.md` – điều khiển VPS bằng Claude.
