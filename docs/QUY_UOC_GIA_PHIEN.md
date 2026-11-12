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

**Khi nào quét:** trong lượt chính 2:00 (sau khi thu thập và gom phiên), tối đa 500 tài sản/lượt
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

## 5. Số liệu lấy từ file đính kèm (thông báo, quy chế đấu giá)

Trong lượt chính 2:00 (tin mới về trước) và các **lượt lấp dữ liệu** trong ngày, phần mềm **tải về và lưu lại file đính
kèm của TIN GẦN NHẤT** (thư mục `data/files/<nguồn>/<năm-tháng>/<mã tin>/`, không xoá) **của tài sản còn hạn đăng ký** – gồm file của
mọi phiên của tài sản đó – rồi đọc chữ trong file: PDF có lớp chữ đọc hết; PDF scan / ảnh nhận dạng bằng OCR
**từ trang đầu, dừng khi đã qua đoạn mô tả tài sản** (thường 1–3 trang, tối đa 8 trang/file); `.docx` đọc trực tiếp;
file khác (zip, rar, xls…) chỉ lưu. File “thông báo” đọc trước “quy chế”; khi đã có đủ diện tích + tờ/thửa thì các
file scan còn lại chỉ lưu, chưa OCR. Nhiều tin được đọc **song song** (OCR chạy ưu tiên thấp để web vẫn mượt).

Phiên cũ đã có file thì giữ, chưa có thì thôi. Thứ tự: (1) tin **mới về** của tài sản còn hạn; (2) tài sản **còn hạn ≥ 2
ngày**; (3) còn hạn < 2 ngày — trong mỗi nhóm, tài sản đang **thiếu xã/phường, tỉnh, diện tích hoặc tờ/thửa** trước; (4) khi
đã xong tài sản còn hạn: tài sản **năm 2026 đã hết hạn còn thiếu thông tin**, kết thúc gần đây trước. Ổ cứng dùng ≥ 85%
thì dừng tải và báo Telegram.

**Lưu trữ:** PDF scan > 1,5 MB được nén (150 dpi); file > 25 MB không tải (giữ link nguồn). Tài sản **hết hạn quá 30
ngày** mà không ra phiên mới: file gốc được **tự dọn** mỗi đêm, giữ chữ đã đọc và thông số (trừ tài sản trong giỏ hàng
hoặc ưu tiên Cao/Rất cao); tài sản như vậy khi lấp dữ liệu chỉ **đọc lấy thông số, không giữ file**.

**Trích thông số** (tổng DT đất, đất ở, đất khác, DT sàn, chiều ngang/dài, số tờ, số thửa) chỉ từ **đoạn mô tả tài
sản** của file (“Tên tài sản…”, “Tài sản đấu giá…” đến trước “Giá khởi điểm”), theo đúng quy tắc thận trọng: có nhãn
rõ và chỉ một giá trị; file nhiều thửa/lô → không lấy.

| Trường hợp | Kết quả |
|---|---|
| Tài liệu có số liệu, tin đăng không có | Dùng số trong tài liệu, nhãn **“từ tài liệu”** (hoặc **“từ tài liệu (OCR)”**) |
| Tài liệu (đọc chữ) khác tin đăng | **Dùng số trong tài liệu**, ghi chú chênh lệch |
| Tài liệu đọc bằng **OCR** khác tin đăng | **Để trống** (OCR có thể đọc nhầm số), ghi chú – kiểm tra file rồi nhập tay |
| Các file / các phiên ghi khác nhau | Để trống, ghi chú |
| Tin hoặc tài liệu gồm nhiều thửa/lô | Không dùng số liệu tài liệu |

**Giá** vẫn theo mục 1–2 (giá chính thức nguồn đăng); giá đọc từ PDF chỉ để tham khảo. Giá trị **nhập tay** luôn
được ưu tiên. Trên trang chi tiết: mục *“File đính kèm đã lưu trên máy chủ”* (mở file, xem chữ đã đọc); file nguồn
đã lưu được mở từ máy chủ kể cả khi website nguồn gỡ.

## 6. Xã/phường và tỉnh/thành (bộ lọc vị trí)

| Nguồn | Cách dùng |
|---|---|
| Ô **nơi có tài sản** của nguồn | Dùng, **trừ** khi là địa chỉ ngân hàng / cơ quan thi hành án / người có tài sản, hoặc nhắc nhiều tỉnh |
| Cụm **“tọa lạc tại…”, “địa chỉ thửa đất/tài sản…”, “vị trí thửa đất…”, “nơi có tài sản…”** trong mô tả | Dùng. Không dùng “địa chỉ: …” trơn (thường là chỗ ở của chủ tài sản) |
| **File đính kèm** | Đọc chữ (PDF chữ/.docx): **ưu tiên nhất**, khác tin đăng thì dùng tài liệu. OCR: chỉ dùng khi tên xã/phường **đối chiếu được** với tên đã biết trong cùng tỉnh (trùng khi bỏ dấu, hoặc sai đúng 1 ký tự) |

- Tên **mới có nhãn thắng tên cũ**: phần sau “nay là / nay thuộc” (có hoặc không có ngoặc), hoặc phần ngoài ngoặc khi
  trong ngoặc ghi “(trước đây là …)”; tên cũ khác tên mới không coi là mâu thuẫn. Tên tỉnh cũ được quy đổi theo Nghị
  quyết sáp nhập.
- Tên tỉnh trùng tên xã/phường/huyện (“xã Bình Dương, tỉnh Gia Lai”, “phường Khánh Hòa, TP Cần Thơ”, “huyện Thạnh Hóa”)
  không bị hiểu là tỉnh; có chữ “tỉnh / thành phố” đi trước thì chỉ lấy tên đó. Tên lặp lại nhiều lần chỉ tính một.
- Ô nơi có tài sản ghi chữ mẫu (“Nơi tài sản tọa lạc”, “tại nơi có tài sản”, “Chi tiết trong Bảng kê”) coi như trống.
- Khi ô nơi có tài sản và cụm “tọa lạc tại…” không có vị trí, dùng tên/mô tả tài sản nếu chỉ có **một** xã/phường hoặc có
  nhãn “nay là”.
- Các nguồn ghi **khác nhau** → **tự chọn** (không duyệt tay) theo thứ tự ưu tiên: tài liệu đọc chữ > ô nơi có tài
  sản > cụm “tọa lạc tại…” > tên tài sản; OCR chỉ dùng khi tin đăng không ghi và tên đối chiếu được; các phiên ghi khác
  nhau → lấy theo **phiên gần nhất**. Ghi chú lý do chọn ở trang chi tiết. Tin nhiều tài sản ở nhiều nơi → để trống.
  Có thể sửa tay trong trang chi tiết (giá trị nhập tay luôn ưu tiên).

## 7. Gộp phiên tự động

Ngoài các cách ở mục 1, phần mềm **tự gộp** các tin cùng tỉnh + cùng đúng tờ/thửa **và** trùng diện tích hoặc số giấy
chứng nhận (kể cả khi xã/phường ghi tên cũ ở phiên trước, tên mới ở phiên sau); hoặc cùng số giấy chứng nhận + cùng
tờ/thửa (hay cùng diện tích khi cả hai không ghi tờ/thửa). Không gộp khi hai tin ghi xã/phường cùng thời kỳ mà khác nhau,
hoặc tin nhiều thửa/lô. Gộp sai → bấm **Tách** ở phiên đó (được giữ cố định).

## 8. Việc của người dùng

| Tình huống | Làm gì |
|---|---|
| Thấy **⚠ cảnh báo gộp phiên** | Xem bảng phiên, bấm **Tách** ở phiên không cùng tài sản |
| Thấy khung vàng **“tin ghi đấu giá lần N…”** | Tra cứu giá phiên đầu (tài liệu gốc trong *Tài liệu nguồn*, hoặc cổng dgts), nhập tay ô *Giá phiên 1* |
| Hai thẻ là cùng một BĐS | Mở một thẻ, nhập số **#id** thẻ kia vào ô *Gộp vào #* |
| Phiên “lịch sử” bị gộp sai | Bấm **Tách** ở phiên đó – lựa chọn được giữ cố định |
| Giá trên web khác hồ sơ | Nhập tay giá đúng, rồi **✓ Xác thực** |
| Ghi chú *“Tài liệu (OCR) và tin đăng ghi … khác nhau”* | Mở file trong *File đính kèm đã lưu*, nhập tay số đúng |
