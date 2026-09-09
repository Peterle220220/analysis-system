# Checklist: Next.js trên nền API Python

## Phase 0 — Contract và baseline

- [x] Task 1: Chuẩn hoá môi trường và ghi baseline (đã ghi; full suite còn lỗi môi trường/fixture bên dưới)
- [x] Task 2: Lập bảng contract route, state và kết quả mẫu

### Checkpoint: Contract

- [x] Baseline đã đo; blocker môi trường đã được ghi rõ
- [x] Chốt mode chuyển đổi: Next `:3000`, Python `:8020`; public `:8020` cần reverse proxy riêng

## Phase 1 — Kết nối và view-model

- [x] Task 3: Chuẩn hoá cấu hình cổng và health/session contract
- [x] Task 4: Gom logic trạng thái dùng chung (HTML và JSON cùng gọi `web/state.py`)
- [x] Task 5: Xây API đọc cho bốn trang chính

### Checkpoint: Backend read path

- [x] Session và bốn trang chính đọc được qua Next `:3000 → Python :8020`
- [x] SSR cũ vẫn pass test tương đương

## Phase 2 — Dataset, clean và approve

- [x] Task 6: API upload/status và trang danh sách
- [x] Task 7: API/UI dataset, clean preview, context và glossary
- [x] Task 8: Gate approve/resume và chống gửi lặp

### Checkpoint: Dataset flow

- [x] Upload → clean → gate → approve → clean preview chạy end-to-end (API contract + browser fixture smoke; phân tích cần model/cassette riêng)
- [x] Backend từ chối request giả dù UI đã ẩn nút

## Phase 3 — Ask, analysis và export

- [x] Task 9: API ask/follow-up và dashboard material
- [x] Task 10: API/UI trang analysis đầy đủ
- [x] Task 11: Binary downloads và chart security

### Checkpoint: Full business flow

- [ ] Upload → clean → approve → ask → answer → chart/export chạy trên Next (browser core flow đạt; answer cần fixture/model cassette)
- [x] Golden analytics và artifacts khớp (fixture line ending đã ghim LF; cả hai golden suite xanh)

### Evidence bổ sung gần nhất

- [x] JSON round giữ `summary`, cảnh báo, nguồn dẫn và phần chưa kết luận; CSV/Excel/Word/PNG có contract test.
- [x] JSON round giữ thêm kết luận bị chặn, kết luận được sửa nhưng vẫn giữ và forecast được Python tính riêng khỏi số đo.
- [x] Chromium smoke trên round fixture thấy blocked/forecast, tải được PNG chart hợp lệ và Excel đúng tên.
- [x] Approve dataset có request key; retry cùng key replay payload và không gọi `resume` lần hai.
- [x] Ask thành công có contract test cho parent/claim lineage trên đĩa và retry cùng key chỉ tạo một round.
- [x] `test_web_api.py`, `test_web_state.py` và `test_web.py` xanh sau các thay đổi trên; FE build xanh.
- [ ] Cần cassette/model fixture để chạy browser thật từ ask tới answer/chart/export.

## Phase 4 — UX, kiểm thử và deployment

- [x] Task 12: Hoàn thiện shell, loading/error/retry và performance guard
- [x] Task 13: Chuyển test HTML thành contract/API/browser regression (API/SSR + Chromium core smoke đã chạy)
- [x] Task 14: System page, health, build và deployment dual-mode
- [ ] Task 15: Cutover có kiểm soát

### Checkpoint: Ready to switch

- [ ] `python tasks.py check` đạt (ruff/format/mypy xanh; toàn bộ suite trừ OCR xanh; còn 5 test OCR do máy host thiếu binary Tesseract, Docker image đã cài dependency)
- [x] FE build đạt
- [ ] Browser smoke và golden/regression đạt (core smoke và golden xanh; cần chạy lại 5 OCR test sau khi cài binary trên host)
- [ ] Restart/health/update/rollback đã diễn tập
- [ ] Người dùng duyệt chuyển UI chính
