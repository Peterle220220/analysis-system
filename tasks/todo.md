# Checklist: Next.js trên nền API Python

## Phase 0 — Contract và baseline

- [ ] Task 1: Chuẩn hoá môi trường và ghi baseline
- [ ] Task 2: Lập bảng contract route, state và kết quả mẫu

### Checkpoint: Contract

- [ ] Baseline đã đo hoặc blocker môi trường đã được ghi rõ
- [ ] Chốt mode public `:8020` và cổng backend nội bộ nếu cần

## Phase 1 — Kết nối và view-model

- [ ] Task 3: Chuẩn hoá cấu hình cổng và health/session contract
- [ ] Task 4: Gom logic trạng thái dùng chung
- [ ] Task 5: Xây API đọc cho bốn trang chính

### Checkpoint: Backend read path

- [ ] Session và bốn trang chính đọc được qua Next `:3000 → Python :8020`
- [ ] SSR cũ vẫn pass test tương đương

## Phase 2 — Dataset, clean và approve

- [ ] Task 6: API upload/status và trang danh sách
- [ ] Task 7: API/UI dataset, clean preview, context và glossary
- [ ] Task 8: Gate approve/resume và chống gửi lặp

### Checkpoint: Dataset flow

- [ ] Upload → clean → gate → approve → clean preview chạy end-to-end
- [ ] Backend từ chối request giả dù UI đã ẩn nút

## Phase 3 — Ask, analysis và export

- [ ] Task 9: API ask/follow-up và dashboard
- [ ] Task 10: API/UI trang analysis đầy đủ
- [ ] Task 11: Binary downloads và chart security

### Checkpoint: Full business flow

- [ ] Upload → clean → approve → ask → answer → chart/export chạy trên Next
- [ ] Golden analytics và artifacts khớp

## Phase 4 — UX, kiểm thử và deployment

- [ ] Task 12: Hoàn thiện shell, loading/error/retry và performance guard
- [ ] Task 13: Chuyển test HTML thành contract/API/browser regression
- [ ] Task 14: System page, health, build và deployment dual-mode
- [ ] Task 15: Cutover có kiểm soát

### Checkpoint: Ready to switch

- [ ] `python tasks.py check` đạt
- [ ] FE test/build đạt
- [ ] Browser smoke và golden/regression đạt
- [ ] Restart/health/update/rollback đã diễn tập
- [ ] Người dùng duyệt chuyển UI chính
