# Quy ước về phiên đấu giá, giá và mức giảm giá

Tài liệu này mô tả **đúng cách phần mềm đang tính**, để mọi người trong nhóm hiểu và dùng con số thống nhất.
Nguyên tắc chung: **chỉ dùng thông tin chính thức hoặc được ghi rõ; chưa đủ căn cứ thì để trống**, người dùng
đối chiếu hồ sơ rồi nhập tay.

---

## 1. Tài sản và phiên

| Khái niệm | Quy ước |
|---|---|
| **Tài sản** | Một bất động sản. Gồm mọi thông báo đấu giá của cùng BĐS đó, gom theo 1 trong các cách: cùng tỉnh + xã/phường + **đúng một** cặp tờ/thửa; cùng chủ tài sản + mô tả trùng khớp; cùng một cuộc đấu giá đăng ở 2 nguồn; **quét lịch sử** (mục 4); **người dùng gộp/tách** (luôn được tôn trọng) |
| **Phiên** | Các thông báo có **cùng ngày tổ chức đấu giá**. Đánh số 1, 2, 3… theo thời gian. Cùng phiên có thể có nhiều thông báo (nguồn đăng lại, hoặc đăng ở cả 2 nguồn) – hiển thị 1 dòng, ghi “(2 tin)” |
| **Giá của phiên** | **Giá khởi điểm chính thức** do nguồn đăng cho phiên đó (ưu tiên dgts.moj.gov.vn) |
| Thông báo **nhiều tài sản**, mỗi tài sản một giá | **Không cộng dồn**: giá của phiên để trống, bảng phiên ghi “nhiều tài sản”. Gói “trọn gói” nguồn đăng **một giá** thì dùng giá đó |
| Giá đọc từ PDF (taisancong) | Chỉ là **giá tham khảo** (khung xanh), không dùng làm giá phiên, không dùng để lọc |

## 2. Giá phiên 1, giá hiện tại, % giảm

| Chỉ số | Quy ước |
|---|---|
| **Giá phiên 1** | Giá của **phiên sớm nhất** trong tài sản. Phiên đó không có giá → **để trống** (không lấy phiên sau thế vào) |
| **Giá hiện tại** | Giá của **phiên gần nhất**. Phiên đó chưa có giá → **để trống** |
| **% giảm so phiên 1** | **(Giá phiên 1 − Giá hiện tại) ÷ Giá phiên 1 × 100**, làm tròn 0,1% |
| Cột **“So phiên trước”** (bảng phiên) | So với phiên gần nhất **phía trên có giá** |
| Cột **“So phiên 1”** (bảng phiên) | So với giá phiên 1 **hiệu lực** (giá nhập tay nếu có) |

**% giảm để trống khi:** thiếu một trong hai giá; tài sản mới có 1 phiên hoặc hai giá bằng nhau; có
**cảnh báo gộp phiên ⚠** – phiên sau **đắt hơn** phiên trước > 5%, hoặc tổng giảm **> 70%** (dấu hiệu gộp nhầm
tài sản khác).

**Giá nhập tay luôn được ưu tiên.** Nhập tay *Giá phiên 1* / *Giá hiện tại* → % giảm tính theo giá nhập tay
(kể cả khi có cảnh báo, vì đã có người xác nhận). Bộ lọc *“Đã giảm giá”* và sắp xếp *“Giảm giá nhiều nhất”*
dùng con số này.

## 3. Khi lịch sử chưa đầy đủ (“tin ghi đấu giá lần N”)

Phần mềm đọc số lần đấu giá **chỉ khi tin ghi rõ**: “đấu giá lần 5”, “đấu giá lại lần 2”, “(lần 3)”.
Không tính các cụm như “cập nhật biến động lần 01”, “đăng lần 2”.

Nếu tin ghi **lần N** mà phần mềm có **ít hơn N phiên** (các phiên đầu nằm ngoài dữ liệu thu thập được):

- Trang chi tiết ghi **“Giá phiên sớm nhất có dữ liệu”** và **“Giảm so phiên sớm nhất”** thay cho “phiên 1”,
  kèm khung vàng giải thích;
- **Không tự đoán** giá phiên đầu thật. Muốn chính xác: tra cứu rồi nhập tay ô *Giá phiên 1*.

## 4. Quét lịch sử giá (tự động mỗi ngày)

**Phạm vi:** chỉ tài sản **còn hạn đăng ký**. Tài sản đã hết hạn đăng ký **không quét**.

**Khi nào quét:** trong lượt chạy tự động 2:00 sáng (sau khi thu thập và gom phiên), tối đa 500 tài sản/lượt
(`schedule.history_limit` trong `config/settings.yaml`). Mỗi tài sản quét **1 lần**, quét lại khi tài sản có
phiên mới. Thứ tự: tài sản **thiếu lịch sử** (tin ghi lần N > số phiên) trước → mức ưu tiên cao → sắp hết hạn
đăng ký. Quét tay: `auction history-scan -n 1000`.

**Từ khoá** lấy từ tên/mô tả tài sản, theo độ đặc trưng giảm dần:

1. **Số giấy chứng nhận** (vd `BR 234700`);
2. **Tên chủ tài sản là cá nhân** (“ông/bà Nguyễn Văn A”);
3. **“thửa đất số N”** (chỉ khi không có 2 loại trên).

Tìm trên cổng dgts **không giới hạn thời gian** (lấy được cả phiên từ các năm trước).

**Chỉ nhận một thông báo cũ khi đủ căn cứ:**

| Trường hợp | Điều kiện nhận |
|---|---|
| Cùng số giấy chứng nhận | **và** cùng đúng tờ + thửa (hoặc cả hai không ghi tờ/thửa nhưng **cùng diện tích**) – vì một giấy chứng nhận có thể chứa nhiều thửa |
| Không có số giấy chứng nhận chung | Cùng đúng tờ + thửa + tỉnh, **và** trùng thêm ít nhất 1: diện tích, xã/phường, tên chủ |

**Luôn loại:** tờ/thửa mâu thuẫn hoặc chỉ một bên có; thông báo nhiều lô; thông báo nhiều tài sản (mỗi tài sản
một giá); thông báo **đang thuộc tài sản khác** (dấu hiệu từ khoá không duy nhất). Tài sản thuộc thông báo nhiều
lô thì **không quét**.

Thông báo được nhận: lưu vào hệ thống, lấy **giá chính thức**, gắn vào tài sản với nhãn **“lịch sử”**, ghi lý do
(vd *“cùng số giấy chứng nhận CS 776005, cùng tờ 48 thửa 343”*). Các phiên hiện có được khoá cùng tài sản để
không bị tách khi gom lại. Kết quả quét hiện trên trang chi tiết (*“Quét lịch sử: tìm thêm 5 thông báo cũ…”*) và
trong báo cáo Telegram hằng ngày.

## 5. Việc của người dùng

| Tình huống | Làm gì |
|---|---|
| Thấy **⚠ cảnh báo gộp phiên** | Xem bảng phiên, bấm **Tách** ở phiên không cùng tài sản |
| Thấy khung vàng **“tin ghi đấu giá lần N…”** | Tra cứu giá phiên đầu (tài liệu gốc trong *Tài liệu nguồn*, hoặc cổng dgts), nhập tay ô *Giá phiên 1* |
| Hai thẻ là cùng một BĐS | Mở một thẻ, nhập số **#id** thẻ kia vào ô *Gộp vào #* |
| Phiên “lịch sử” bị gộp sai | Bấm **Tách** ở phiên đó – lựa chọn được giữ cố định |
| Giá trên web khác hồ sơ | Nhập tay giá đúng, rồi **✓ Xác thực** |
