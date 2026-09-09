# Checklist: Next.js trên nền API Python

## Phase 0 — Contract và baseline

- [x] Task 1: Chuẩn hoá môi trường và ghi baseline (đã ghi; full suite còn lỗi môi trường/fixture bên dưới)
- [x] Task 2: Lập bảng contract route, state và kết quả mẫu

### Checkpoint: Contract

- [x] Baseline đã đo; blocker môi trường đã được ghi rõ
- [x] Chốt mode chuyển đổi: Next `:3000`, Python `:8020`; public `:8020` cần reverse proxy riêng

## Phase 1 — Kết nối và view-model

- [x] Task 3: Chuẩn hoá cấu hình cổng và health/session contract
- [ ] Task 4: Gom logic trạng thái dùng chung (view-model JSON đã dùng chung; HTML cũ còn logic trình bày cần gom tiếp)
- [x] Task 5: Xây API đọc cho bốn trang chính

### Checkpoint: Backend read path

- [x] Session và bốn trang chính đọc được qua Next `:3000 → Python :8020`
- [x] SSR cũ vẫn pass test tương đương

## Phase 2 — Dataset, clean và approve

- [x] Task 6: API upload/status và trang danh sách
- [x] Task 7: API/UI dataset, clean preview, context và glossary
- [x] Task 8: Gate approve/resume và chống gửi lặp

### Checkpoint: Dataset flow

- [ ] Upload → clean → gate → approve → clean preview chạy end-to-end (cần fixture/model để browser-smoke)
- [x] Backend từ chối request giả dù UI đã ẩn nút

## Phase 3 — Ask, analysis và export

- [x] Task 9: API ask/follow-up và dashboard material
- [x] Task 10: API/UI trang analysis đầy đủ
- [x] Task 11: Binary downloads và chart security

### Checkpoint: Full business flow

- [ ] Upload → clean → approve → ask → answer → chart/export chạy trên Next (cần browser-smoke với model/cassette)
- [ ] Golden analytics và artifacts khớp

## Phase 4 — UX, kiểm thử và deployment

- [x] Task 12: Hoàn thiện shell, loading/error/retry và performance guard
- [ ] Task 13: Chuyển test HTML thành contract/API/browser regression (API/SSR đã có; browser regression còn lại)
- [x] Task 14: System page, health, build và deployment dual-mode
- [ ] Task 15: Cutover có kiểm soát

### Checkpoint: Ready to switch

- [ ] `python tasks.py check` đạt (ruff/format đạt; mypy còn 9 lỗi cũ ở 5 test unit)
- [x] FE build đạt
- [ ] Browser smoke và golden/regression đạt
- [ ] Restart/health/update/rollback đã diễn tập
- [ ] Người dùng duyệt chuyển UI chính
