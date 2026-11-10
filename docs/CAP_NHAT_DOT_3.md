# Cập nhật Đợt 3 – Bộ lọc đã lưu, nhắc hạn, gợi ý gộp phiên, độ đầy đủ, cài lên điện thoại

## Có gì mới

| Menu / chỗ | Tính năng |
|---|---|
| **Tài sản → 💾 Lưu bộ lọc** | Chọn bộ lọc (vd Ngân hàng, Hà Nội, dưới 5 tỷ) → đặt tên → lưu. Sau mỗi lượt quét (0:00, 12:00) tài sản **mới** hoặc có **phiên mới** khớp bộ lọc được gửi vào **Telegram cá nhân** |
| **🔔 Bộ lọc** | Danh sách bộ lọc của bạn (riêng tư): số tài sản đang khớp, bật/tắt báo, xoá |
| **Tài khoản → Telegram cá nhân** | Liên kết Telegram riêng: bấm *Liên kết Telegram* → gửi `/start <mã>` cho bot → *Kiểm tra* |
| **⏰ Nhắc hạn** (dải vàng đầu trang Tài sản) | Tài sản trong **giỏ** hết hạn đăng ký trong 3 ngày; **việc được giao** sắp/đã quá hạn; (quản trị) tài sản ưu tiên Cao/Rất cao sắp hết hạn. Mỗi ngày gửi Telegram cá nhân 1 lần |
| **Gợi ý gộp** | Cặp tài sản nghi là cùng một BĐS đấu giá lại (cùng tờ/thửa, cùng số GCN, cùng diện tích + xã/chủ/mô tả…). Bấm **Đồng ý gộp** hoặc **Không phải** (không gợi ý lại) |
| **Độ đầy đủ** | % tài sản còn hạn đã có giá, diện tích, tờ/thửa, xã/phường…; nút *Xem danh sách thiếu* để nhập tay bổ sung. Bộ lọc mới **“Còn thiếu dữ liệu”** ở trang Tài sản |
| **Cài lên điện thoại** | Web mở như một ứng dụng (biểu tượng riêng, toàn màn hình) |
| Menu trên điện thoại | Menu xuống dòng riêng, vuốt ngang để thấy đủ mục |
| Gộp / tách phiên | Không còn phải chờ: phần mềm tính lại ở nền, tải lại trang sau ít phút |

Tin Telegram cá nhân cần bot Telegram của hệ thống (**Phần B** trong `CAP_NHAT_DOT_1.md`). Chưa làm Phần B thì các
tính năng vẫn dùng trên web, chỉ chưa gửi Telegram.

## Cập nhật

**Chỉ cập nhật khi `capnhat2` đã xong** (log có `=== XONG`). Cách dễ nhất: nhắn phiên **VPS hangdg**:

> Kiểm tra capnhat2 đã xong chưa. Nếu xong và không có tiến trình ghi CSDL nào đang chạy thì sao lưu rồi cập nhật
> phiên bản mới (git pull + install-vps.sh), sau đó chạy `merge-suggest` và báo kết quả.

Hoặc tự chạy qua SSH:

```bash
tail -n 2 /opt/autolist/data/capnhat2.log
```

```bash
sudo -u auction /opt/autolist/deploy/backup.sh && cd /root/autolist && git pull && sudo bash deploy/install-vps.sh
```

```bash
sudo -u auction /opt/autolist/.venv/bin/auction merge-suggest
```

## Cài web lên điện thoại

- **Android (Chrome):** mở https://hangdg.com → đăng nhập → menu ⋮ → **Thêm vào màn hình chính** / **Cài đặt ứng dụng**.
- **iPhone (Safari):** mở https://hangdg.com → nút **Chia sẻ** → **Thêm vào MH chính**.

## Liên kết Telegram cá nhân (mỗi người tự làm)

1. Web → tên mình (góc phải) → mục **Telegram cá nhân** → **Liên kết Telegram**.
2. Bấm link *mở bot* (hoặc tìm bot trong Telegram) → bấm **Start** / gửi `/start <mã>` (mã hiện trên trang).
3. Quay lại trang, bấm **Kiểm tra** → hiện “Đã liên kết”, bot gửi tin xác nhận.
4. Tạo bộ lọc ở trang Tài sản → **💾 Lưu bộ lọc** (tích *Báo tài sản mới qua Telegram*).
