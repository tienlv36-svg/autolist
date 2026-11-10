# Cập nhật Đợt 2 – Đọc file đính kèm, quét 2 lần/ngày, sao lưu sau mỗi lượt

**Có gì mới**

| | |
|---|---|
| File đính kèm | Mọi file đính kèm của tin BĐS (thông báo, quy chế…) được **tải về và lưu lại** trên VPS (`data/files/`), **đọc hết** chữ (PDF chữ, PDF scan bằng OCR, .docx) |
| Số liệu ưu tiên từ tài liệu | Diện tích đất / đất ở / đất khác / sàn, chiều ngang / dài, tờ / thửa lấy từ file nếu ghi rõ; nhãn **“từ tài liệu”**. Quy tắc chi tiết: `QUY_UOC_GIA_PHIEN.md` mục 5 |
| Trang chi tiết | Mục **“File đính kèm đã lưu trên máy chủ”**: mở file, **xem chữ** đã đọc, tải về |
| Lịch tự động | **0:00 và 12:00** mỗi ngày (trước: 2:00) |
| Sao lưu | Tự động **sau mỗi lượt quét** (trước: 4:15 sáng), giữ 28 bản (= 14 ngày) |
| Trang Hệ thống | Số file đã lưu, dung lượng, số tin đã/chưa đọc file |
| Báo cáo Telegram | Thêm dòng “File đính kèm: đọc … tin, lưu … file …” |

> Mỗi lượt đọc file tối đa **5 giờ** rồi để phần còn lại cho lượt sau (tài sản **còn hạn đăng ký** được đọc trước).
> Lần đầu có nhiều tin, nên cần vài ngày để đọc hết tin cũ; tài sản còn hạn sẽ có số liệu sớm nhất.

---

## Bước 0 – Chờ việc đang chạy xong

Lệnh đang chạy trong tmux `capnhat` (lấy giá → gom phiên → quét lịch sử). Kiểm tra:

```bash
tail -n 3 /opt/autolist/data/capnhat.log
```

Có dòng `=== XONG … ===` mới làm tiếp. Chưa xong thì để đó, lúc khác kiểm tra lại.

## Bước 1 – Kiểm tra ổ cứng

File đính kèm chiếm nhiều chỗ (ước tính vài chục GB khi đọc hết tin cũ).

```bash
df -h / ; du -sh /opt/autolist/data
```

Gửi kết quả cho Claude nếu cột `Use%` trên 60%. Phần mềm tự **dừng tải file khi ổ cứng dùng tới 85%** và báo Telegram
(đổi ngưỡng: `docs_max_disk_pct` trong `config/settings.yaml`).

## Bước 2 – Sao lưu rồi cập nhật

```bash
sudo -u auction /opt/autolist/deploy/backup.sh
```

```bash
cd /root/autolist && git pull && sudo bash deploy/install-vps.sh
```

Đúng: cuối màn hình có `Lịch thu thập: 0:00 và 12:00 mỗi ngày`, `Sao lưu tự động sau mỗi lượt thu thập…`,
`auction-web: active | auction-scheduler: active`.

Kiểm tra lịch:

```bash
grep -n "cron:" /opt/autolist/config/settings.yaml && systemctl is-active auction-scheduler
```

Đúng: `cron: "0 0,12 * * *"` và `active`. (Nếu dòng `cron` khác – bạn từng tự sửa – báo Claude để sửa giúp.)

## Bước 3 – (Tuỳ chọn) Đọc file ngay, không chờ lượt tự động

Chỉ làm khi còn **hơn 4 tiếng** tới lượt tự động kế tiếp (0:00 hoặc 12:00):

```bash
tmux new -d -s docfile 'cd /opt/autolist && sudo -u auction .venv/bin/auction docs-fetch -m 210 2>&1 | tee -a data/docfile.log'
```

Theo dõi: `tail -n 3 /opt/autolist/data/docfile.log`. Lệnh và lượt tự động dùng chung khoá, không chạy chồng nhau.

## Bước 4 – Xem kết quả

- Web → **Hệ thống**: “File đính kèm đã lưu”, “Tin đã đọc file … còn …”.
- Mở một tài sản còn hạn → các ô diện tích có nhãn **“từ tài liệu”**; cuối trang có **File đính kèm đã lưu trên
  máy chủ** (bấm **xem chữ** để thấy nội dung phần mềm đọc được).
- Telegram sau mỗi lượt 0:00 / 12:00: dòng “File đính kèm …” và “Sao lưu gần nhất …”.

## (Tuỳ chọn) Đẩy cả file đính kèm lên Google Drive

Bản sao lưu nén chỉ gồm CSDL, file tải lên, cấu hình (file đính kèm quá lớn để nén mỗi lượt). Muốn giữ thêm bản
file đính kèm trên Google Drive (đã làm Phần C của Đợt 1; Drive miễn phí chỉ 15 GB):

```bash
sudo -u auction touch /opt/autolist/data/.drive_files
```

Từ lượt sau, mỗi lần sao lưu sẽ đẩy **phần file mới** lên thư mục `autolist-files` trên Drive. Tắt:
`sudo -u auction rm /opt/autolist/data/.drive_files`.
