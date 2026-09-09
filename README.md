# Hệ thống phân tích dữ liệu

Đưa dữ liệu vào, hệ thống làm sạch và trả lại bản sạch cho bạn xem. Bạn đặt câu hỏi, nó
giao việc cho các AI chuyên trách, rồi trả lời — **kèm bằng chứng cho từng con số**.

Bạn hỏi tiếp bao nhiêu lần cũng được.

**1.414 test · 14 agent · chi phí API mặc định: $0**

---

## Vòng làm việc

```
Bạn đưa file
   ↓
Hệ thống đọc và đề xuất cách làm sạch  →  DỪNG, chờ bạn duyệt
   ↓
Bạn nhận lại bản dữ liệu sạch
   ↓
Bạn đặt câu hỏi
   ↓
Manager chia việc → các AI chuyên trách xử lý → Manager tổng hợp
   ↓
Câu trả lời, kèm nguồn từng số           →  DỪNG, chờ bạn duyệt
   ↓
Bạn hỏi tiếp  →  quay lại bước trên
```

Hai chỗ **DỪNG** là cố ý. Hệ thống không tự sửa dữ liệu của bạn và không tự công bố kết
luận — bạn là người chốt.

---

## Bắt đầu

```bash
# 1. Đưa file vào và làm sạch
asys clean --input ~/du_lieu/ban_hang.csv --run-id bh

# 2. Xem nó định làm gì, rồi duyệt
asys gates bh
asys approve bh --gate gate_t3_clean --select trim_whitespace

# 3. Nhận bản sạch
asys resume-dag bh

# 4. Hỏi
asys ask bh "Kênh nào có doanh thu cao nhất, và thấp nhất?"

# 5. Hỏi tiếp, bao nhiêu lần cũng được
asys ask bh "Doanh thu có xu hướng tăng theo thời gian không?"
```

Chưa biết file của mình là loại gì thì hỏi trước:

```bash
asys route ~/du_lieu/
```

Nó đọc vài byte đầu mỗi file và nói cái nào đọc được bằng gì. **Định dạng do nội dung
quyết định, không do đuôi file** — một file PDF đặt tên `.csv` vẫn được nhận ra đúng.

---

## Đọc được những gì

| Loại | Định dạng |
|---|---|
| Bảng | CSV · Excel · JSON · Parquet |
| Tài liệu | PDF · **Word** · **Email** · **HTML** |
| Ảnh | PNG · JPEG · TIFF (đọc chữ trong ảnh) |
| Âm thanh | WAV · MP3 · M4A · MP4 (nghe và ghi lại lời nói) |

## Xuất ra những gì

```bash
asys export clean://ban_hang.parquet --out bao_cao.xlsx
```

CSV · Excel · Word · Markdown · HTML · JSON. **Định dạng ra là lựa chọn của bạn, không
dính gì tới định dạng vào** — đọc PDF xuất Excel được, đọc CSV xuất Word được.

Excel và CSV mở thẳng trong Tableau hoặc Power BI.

---

## Giao diện web

```bash
asys set-password     # đặt mật khẩu, nó tự ghi vào .env
asys serve            # mở http://localhost:8020
```

---

## Điều quan trọng nhất: **số liệu không bịa được**

Đây là chỗ hệ thống này khác một con AI thông thường.

**AI không được phép gõ một con số nào.** Nó viết câu văn với chỗ trống, code điền số vào:

```
AI viết  :  "Nhóm {ten:X.mean.by.kenh.app} xử lý lâu nhất, {X.mean.by.kenh.app}."
Bạn đọc  :  "Nhóm app xử lý lâu nhất, 24.53 giờ."
```

Câu nào có chữ số AI tự gõ thì **bị loại cả câu**, không sửa. Vì sửa là phải đoán nó
định nói gì.

Ngoài ra hệ thống còn tự chặn:

- **Nói sai nhóm đứng đầu** — code so lại các con số; nói `sadness` cao nhất trong khi
  thật ra là `joy` thì cả câu bị loại
- **Nói đã chạy một phép kiểm chưa hề chạy** — *"T-test cho thấy khác biệt đáng kể"* mà
  không có phép t-test nào thì bị loại
- **Suy diễn nhân quả** từ số liệu chỉ đo được mối liên hệ
- **Xin dữ liệu không liên quan** — hỏi về cảm xúc mà xin *"doanh số 2024"* thì bị loại
- **Trả lời nửa câu hỏi mà không nói** — hỏi cao nhất *và* thấp nhất mà chỉ trả lời được
  một vế thì nó nói rõ vế còn lại bỏ ngỏ

Và thứ **không** tìm ra được thì luôn được ghi ngang hàng với thứ tìm ra. Một kết luận
vắt qua một lỗ hổng không ai nhắc tới là thứ cả hệ thống này dựng lên để ngăn.

---

## Ai làm gì

**Manager** không tự tính gì cả. Nó đọc câu hỏi, chia thành việc nhỏ, giao đúng agent,
rồi tổng hợp. Nó chạy trên model mạnh nhất vì đây là việc suy luận khó nhất.

**Các agent chuyên trách** mỗi con làm một việc:

| | Làm gì | Dùng AI? |
|---|---|---|
| A1 Ingest | đọc file thành bảng | Không |
| A2 Profiler | đo dữ liệu có gì, thiếu gì | Có — chỉ để diễn giải |
| A3 Cleaner | **đề xuất** luật làm sạch | Có — chỉ để đề xuất |
| A4 Transformer | dựng bảng phân tích bằng SQL | Có |
| A5 Validator | chấm dữ liệu theo tiêu chí đã khai | **Không** |
| A6 Process Miner | đo quy trình chạy ra sao | Có — chỉ để đặt tên |
| A7 Analyst | rút ra kết luận từ số đã tính | Có — chỉ để diễn giải |
| A8 Reporter | viết báo cáo | Có |
| A10 Text Miner | đếm từ, đo từ nào đặc trưng | **Không** |
| E1–E4 | đọc PDF, ảnh, âm thanh, tài liệu | **Không** |

Những chỗ ghi **Không** là cố ý: đếm từ và chấm điểm dữ liệu là **số học**. Một model
được hỏi *"từ nào quan trọng"* sẽ trả lời rất tự tin, không lặp lại được, và không có gì
để đối chiếu — trong khi các con số thì tính lại lúc nào cũng ra.

---

## Chi phí

Mặc định `provider: handoff` — **không gọi API nào, $0**. Hệ thống ghi câu hỏi ra file,
bạn dán vào tài khoản AI của mình rồi dán kết quả về.

Muốn tự động thì đổi `provider` trong `config/settings.yaml`. Mọi lượt chạy đều có trần
token, trần tiền và trần thời gian — chạm trần là **dừng**, không bao giờ tự chạy tiếp.

---

## Dọn dẹp

```bash
asys runs                      # xem các lần chạy đang chiếm bao nhiêu
asys forget --giu 10           # LIỆT KÊ những gì sẽ xoá
asys forget --giu 10 --xac-nhan   # xoá thật
```

Không có `--xac-nhan` thì không xoá gì. Dữ liệu gốc của bạn không bao giờ bị đụng tới.

---

## Tài liệu khác

| | |
|---|---|
| Cài đặt, triển khai | [DEPLOY.md](DEPLOY.md) |
| Tiến độ từng phần | [PROGRESS.md](PROGRESS.md) |
| Đặc tả gốc | [BUILD_SPEC.md](BUILD_SPEC.md) |
| **108 lỗi đã gặp và cách sửa** | [NOTES.md](NOTES.md) |

`NOTES.md` đáng đọc nhất nếu bạn muốn biết vì sao hệ thống được làm như vậy. Nó ghi lại
từng lỗi đúng như lúc gặp, không viết lại cho đẹp — gồm cả những lỗi mà mọi bài kiểm tra
đều cho qua và chỉ lộ ra khi chạy trên dữ liệu thật.
