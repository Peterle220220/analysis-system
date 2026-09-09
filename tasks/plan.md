# Kế hoạch hoàn thiện Next.js trên nền API Python

## Trạng thái và mục tiêu

Đây là kế hoạch thực thi đang được triển khai theo lát cắt. Mục tiêu là giữ toàn bộ quyết định nghiệp vụ trong Python/`Workspace`/services, hoàn thiện JSON API để Next.js thực hiện được toàn bộ quy trình đang có, kiểm thử tương đương với giao diện SSR cũ, rồi mới chuyển deployment và giao diện chính.

Phạm vi gồm frontend, backend, kiểm thử và deployment. Không thêm SSE, cache hoặc hệ thống job mới trước khi baseline chứng minh có nhu cầu.

## Baseline đã khảo sát

- Commit hiện tại: `da17d42 feat: migrate web interface to Next.js with JSON API integration`.
- Worktree sạch tại thời điểm lập kế hoạch.
- `src/analysis_system/web/app.py` hiện có các route HTML cho phiên, trang chính, upload, dataset/clean/analysis, approve, xoá round, glossary, context, ask, CSV, Excel/Word và chart.
- JSON API hiện mới có `GET/POST/DELETE /api/session`; `frontend/` mới có shell, đăng nhập, sidebar và bốn trang giữ chỗ.
- `frontend/next.config.ts` còn proxy `/api/*` về `127.0.0.1:8000`, không phù hợp mục tiêu backend Python ở `8020`.
- Chưa chạy được baseline test/build trong môi trường hiện tại: `.venv` chưa tồn tại, Python hệ thống không có `pytest`, `frontend/node_modules` chưa tồn tại. Đây là điều kiện cần xử lý ở Task 1, không phải kết quả xanh.

## Quyết định kiến trúc

1. **Trong giai đoạn chuyển đổi:** Next.js chạy nội bộ ở `3000`; Python chạy ở `8020`; Next rewrite `/api/*` tới `http://127.0.0.1:8020/api/*`. Trình duyệt chỉ gọi cùng origin của Next.
2. **Deployment có hai mode rõ ràng:**
   - mode chuyển đổi/dev: truy cập Next `:3000`, backend `:8020`;
   - mode public bằng `:8020`: reverse proxy phải chiếm `:8020`, còn Python chuyển sang cổng nội bộ khác, lấy từ cấu hình (mặc định đề xuất `8021`). Không cấu hình hai server cùng bind một cổng.
3. **Python là nguồn sự thật:** làm sạch, chọn phép kiểm định, gate, phê duyệt, kết luận, cảnh báo, nguồn dẫn, trạng thái running/stopped và phân biệt measured/forecast chỉ được tính ở Python. React chỉ hiển thị JSON và gửi thao tác.
4. **Một quyết định trạng thái dùng chung:** các cờ hiện rải ở `render.py` (`_dataset_state`, `_state_of`, `split_rounds`, các nhánh gate/answer) phải được tách thành hàm view-model dùng lại; HTML cũ và JSON cùng gọi hàm đó trong thời gian chuyển đổi.
5. **API lỗi thống nhất:** mọi JSON lỗi nghiệp vụ dùng envelope có `error.code`, `error.message`, `error.hint` và HTTP phù hợp (`401`, `400`, `404`, `409`, `500`). Không để exception nội bộ hoặc HTML lỗi lọt vào API.
6. **Polling có điều kiện:** upload/ask trả trạng thái chạy và id; client chỉ poll khi Python báo `running=true` hoặc còn gate, dừng khi hoàn tất/lỗi; mutation có khóa chống gửi lặp và retry không tạo job mới.
7. **Giữ binary ở Python:** CSV, Excel, Word và PNG tiếp tục được FastAPI phục vụ qua rewrite, giữ `content-disposition`, MIME type và kiểm tra quan hệ dataset–round/path traversal.

## Hợp đồng hành vi hiện tại: đối chiếu cũ → API → Next

| Chức năng/route cũ | API đích | UI mới và tiêu chí giữ hành vi |
|---|---|---|
| `GET/POST /dang-nhap`, `POST /dang-xuat` | `GET/POST/DELETE /api/session` | Form đăng nhập, lỗi sai mật khẩu, cookie dùng chung, đăng xuất; chưa đăng nhập không đọc được API nghiệp vụ. |
| `GET /` | `GET /api/home` | Danh sách dataset gốc, số dataset chờ duyệt, upload; không liệt kê round như dataset độc lập. |
| `GET /du-lieu` | `GET /api/data` | Trạng thái từng dataset: running/waiting/stopped/ready/unclean/unreadable, số phân tích, liên kết đúng dataset. |
| `POST /tai-len` | `POST /api/datasets` (multipart) | Lưu file an toàn, trả nhanh `dataset_id`, job clean chạy nền, lỗi nền được ghi và đọc được. |
| meta-refresh sau upload | `GET /api/datasets/{dataset}/status` | Poll có giới hạn; dừng khi `running=false`; không reload toàn trang và không tạo clean job thứ hai. |
| `GET /bo/{dataset}` | `GET /api/datasets/{dataset}` | Context, source preview, clean preview, verdict/examination, gate, lỗi nền, cây round và trạng thái từng round. |
| `GET /bo/{dataset}/sach` | `GET /api/datasets/{dataset}/clean` | Bảng sạch, số dòng/cột, preview; thiếu dữ liệu trả lỗi rõ, không bảng rỗng giả. |
| `POST /bo/{dataset}/boi-canh` | `PUT /api/datasets/{dataset}/context` | Lưu/sửa/xoá context; context thuộc dataset gốc, không thuộc round. |
| `POST /bo/{dataset}/soan-chu-giai` | `POST /api/datasets/{dataset}/glossary-draft` | Draft không tự lưu; báo dòng bị bỏ; người dùng xem/sửa rồi mới gửi context. |
| `POST /bo/{dataset}/duyet` | `POST /api/datasets/{dataset}/approve` | Gửi đúng `gate_id`, lựa chọn và rule thêm; Python kiểm tra gate/options; approve rồi resume; trả state mới. |
| `POST /bo/{dataset}/hoi` | `POST /api/datasets/{dataset}/ask` | Câu hỏi rỗng không tạo round; follow-up giữ parent/claim lineage; trả `round_id`, trạng thái và câu hỏi. |
| `GET /bo/{dataset}/pt/{round}` | `GET /api/datasets/{dataset}/rounds/{round}` | Câu hỏi, tree, task state, answer trực tiếp, claim bị block, warning/risk/gap, nguồn dẫn, measured/forecast, gate và lý do không có answer. |
| `POST /bo/{dataset}/xoa-phan-tich` | `POST /api/datasets/{dataset}/rounds/delete` | Chỉ xoá round thuộc dataset; không xoá dataset gốc; round đang chạy trả `409`; chọn rỗng không xoá gì. |
| `GET /tai-ve/{dataset}` | `GET /api/datasets/{dataset}/clean.csv` | CSV sạch có BOM UTF-8, chỉ tải khi bảng tồn tại. |
| `GET /bo/{dataset}/pt/{round}/tai/excel|word` | `GET /api/datasets/{dataset}/rounds/{round}/export/{kind}` | Kiểm tra round thuộc dataset và answer tồn tại; tải xlsx/docx đúng MIME/tên file. |
| `GET /anh/{name}` | `GET /api/charts/{name}` | Chỉ PNG trong artifacts; basename/path traversal bị chặn; không tự vẽ chart khi thiếu measured numbers. |
| `GET /bang-dieu-khien` | `GET /api/dashboard` | Liệt kê material/answer có thật, không làm mất answer trực tiếp hay kết luận bị chặn. |
| `GET /he-thong` | `GET /api/system` | Version, branch, dirty, update và note. |
| `POST /he-thong/kiem-tra` | `POST /api/system/check` | Gọi updater hiện có, trả update JSON, giữ guard đăng nhập. |
| `POST /he-thong/cap-nhat` | `POST /api/system/apply` | Giữ chặn branch/remote trong updater, trả note restart; chỉ kích hoạt bản mới sau khi build/health check đạt. |

## Dependency graph

```text
Workspace + state trên đĩa
        ↓
view-model dùng chung + API error/validation contract
        ↓
API JSON theo từng luồng
        ↓
Next API client + shell/polling/mutation guard
        ↓
UI từng route và binary downloads
        ↓
API/React/browser/golden regression
        ↓
build, service, reverse proxy, health check, cutover/rollback
```

## Task List

### Phase 0 — Chốt hợp đồng và baseline

### Task 1: Chuẩn hoá môi trường và ghi baseline

**Description:** Chuẩn bị cách cài dependency Python/Node và chạy được bộ kiểm tra hiện có; ghi kết quả của web contract, golden, regression, frontend build và health smoke trước thay đổi.

**Acceptance criteria:**
- [ ] Có một lệnh hoặc tài liệu duy nhất để tạo `.venv`, cài `.[dev]`, chạy `pytest` và cài `frontend`.
- [ ] Baseline ghi rõ số test pass/fail/skip, lỗi môi trường và kết quả `npm run build`.
- [ ] Có fixture đại diện cho upload → clean gate → approve → ask → answer/export để dùng lại.

**Verification:** chạy `python tasks.py check`, nhóm test web/golden/regression và `npm run build` trong môi trường đã chuẩn bị; lưu kết quả vào artifact/ghi chú baseline.

**Dependencies:** None

**Files likely touched:** `tasks.py`, `README.md`, `frontend/package-lock.json`, `tests/fixtures/`, tài liệu baseline.

**Estimated scope:** Medium

### Task 2: Lập bảng contract route, state và kết quả mẫu

**Description:** Chuyển bảng đối chiếu ở trên thành contract có trường bắt buộc, status code, lỗi, điều kiện chặn, state trên đĩa và mẫu JSON/CSV/XLSX/DOCX/PNG. Mỗi hành vi trong `app.py`, `render.py`, `view.py`, `Workspace` phải có test đích.

**Acceptance criteria:**
- [ ] Mọi route cũ và thao tác hiện có có API đích, màn hình đích, fixture và tiêu chí kiểm chứng.
- [ ] Contract ghi rõ các trường giữ nguyên: answer trực tiếp, blocked conclusion, warning, citation/source, approval/examination, measured/forecast.
- [ ] Có danh sách invariants bảo mật: auth trước multipart, dataset–round ownership, safe path và không xoá round đang chạy.

**Verification:** review thủ công từng route với `rg`/test hiện có; không còn route nghiệp vụ không có dòng mapping.

**Dependencies:** Task 1

**Files likely touched:** `plans/nextjs-migration.md` hoặc tài liệu contract mới, `tests/contract/`.

**Estimated scope:** Medium

### Checkpoint: Contract

- [ ] Baseline đã được đo hoặc có blocker môi trường được ghi rõ.
- [ ] Người dùng duyệt API matrix, đặc biệt mode public `:8020`.

### Phase 1 — Kết nối, view-model và session

### Task 3: Chuẩn hoá cấu hình cổng và health/session contract

**Description:** Đưa backend URL vào cấu hình phía server, đổi proxy dev về Python `8020`, bổ sung health/readiness rõ ràng và giữ session cùng origin qua Next rewrite. Chưa chuyển public port nếu chưa có reverse proxy.

**Acceptance criteria:**
- [ ] Dev Next `:3000` gọi được `/api/session` qua backend `:8020`; sai/đúng mật khẩu và logout giữ nguyên semantics.
- [ ] Backend tắt thì UI hiện lỗi kết nối có thể thử lại, không spinner vô hạn.
- [ ] Service/docs/compose không còn cấu hình mâu thuẫn giữa `8000` và `8020`.

**Verification:** session contract test, smoke `GET /api/health`/readiness, test backend unavailable và `npm run build`.

**Dependencies:** Task 1, Task 2

**Files likely touched:** `src/analysis_system/web/app.py`, `frontend/next.config.ts`, `frontend/src/lib/session.ts`, `.env.example`, `DEPLOY.md`, `deploy/asys.service`, `docker-compose.yml`.

**Estimated scope:** Medium

### Task 4: Gom logic trạng thái dùng chung

**Description:** Đối chiếu `render.py` với `view.py`; đưa dataset state, round grouping, pending approval, answer/no-answer reason, tree visibility và trạng thái clean vào hàm Python dùng chung. `render.py` gọi lại nguồn này trong thời gian SSR còn tồn tại.

**Acceptance criteria:**
- [ ] Không còn hai bản độc lập của các quyết định running/waiting/done/broken/blocked.
- [ ] JSON và HTML cũ cho cùng fixture trả cùng state, số round, tree numbering và lý do dừng.
- [ ] Các flag không làm mất examination/verdict sau khi gate đã approve.

**Verification:** unit/contract tests cho state matrix; so sánh JSON với HTML fixture trên dataset có running, stale, gate, answer, failed và no-result.

**Dependencies:** Task 2

**Files likely touched:** `src/analysis_system/web/view.py`, `src/analysis_system/web/render.py`, `src/analysis_system/web/app.py`, `tests/contract/`, `tests/unit/`.

**Estimated scope:** Large — phải tách tiếp nếu một PR vượt 5 file hoặc 2 giờ.

### Task 5: Xây API đọc cho bốn trang chính

**Description:** Bổ sung `GET /api/home`, `/api/data`, `/api/dashboard`, `/api/system` từ view-model và updater hiện có; chuẩn hoá lỗi đọc dữ liệu.

**Acceptance criteria:**
- [ ] Payload có schema ổn định, không trả dataclass/path/datetime không serialize được.
- [ ] Dataset gốc được lọc đúng `ROUND_MARK`; dashboard chỉ liệt kê answer thực sự tồn tại.
- [ ] System giữ version/update/note và guard đăng nhập.

**Verification:** API contract tests với fixture trống, đang chạy, hoàn tất, lỗi và nhiều round; assert cả JSON và state trên đĩa.

**Dependencies:** Task 4

**Files likely touched:** `src/analysis_system/web/app.py`, `src/analysis_system/web/view.py`, `tests/contract/test_web_api.py`.

**Estimated scope:** Medium

### Checkpoint: Backend read path

- [ ] Next có thể đăng nhập và đọc đủ bốn trang chính qua `:3000 → :8020`.
- [ ] SSR cũ vẫn pass nhóm test tương đương.

### Phase 2 — Luồng dataset, clean và phê duyệt

### Task 6: API upload/status và trang danh sách

**Description:** Chuyển upload multipart, clean background và status polling sang JSON, giữ auth trước khi đọc file và ghi lỗi nền cạnh run.

**Acceptance criteria:**
- [ ] Upload trả `dataset_id`/status mà không chờ clean hoàn tất.
- [ ] Poll có state phase/running/error/gates và kết thúc hữu hạn khi job xong, fail hoặc stale.
- [ ] Retry không tạo clean job thứ hai; tên file/dataset không thoát khỏi raw layer.

**Verification:** test upload unauthorized/missing file/safe name, background success/failure, status transitions và disk artifacts.

**Dependencies:** Task 3, Task 5

**Files likely touched:** `src/analysis_system/web/app.py`, `src/analysis_system/web/view.py`, `frontend/src/app/page.tsx`, `frontend/src/app/du-lieu/page.tsx`, tests.

**Estimated scope:** Large — tách API và UI thành hai task nếu cần.

### Task 7: API/UI dataset, clean preview, context và glossary

**Description:** Xây trang dataset và clean bằng payload Python: source/staged/clean table, examination/verdict, context, draft glossary và lỗi nền; giữ cây điều hướng.

**Acceptance criteria:**
- [ ] Người dùng xem được dataset từ đầu đến cuối và vào được trang clean riêng.
- [ ] Context rỗng xoá được; draft glossary không tự lưu; dòng bị bỏ được báo rõ.
- [ ] UI không tự suy luận trạng thái từ row count hoặc chuỗi lỗi; chỉ dùng flag/label từ API.

**Verification:** API state tests và browser flow upload → clean → context → glossary; so sánh với HTML cũ trên fixture.

**Dependencies:** Task 4, Task 6

**Files likely touched:** `src/analysis_system/web/app.py`, `frontend/src/app/du-lieu/`, `frontend/src/app/bo/`, components/API client, tests.

**Estimated scope:** Large — chia tiếp thành API và UI nếu vượt giới hạn.

### Task 8: Gate approve/resume và chống gửi lặp

**Description:** Phơi gate report/options/examined và mutation approve; backend kiểm tra lại gate, lựa chọn, added rules, run ownership rồi resume.

**Acceptance criteria:**
- [ ] Gate cleaning không tự approve; gate claims hiển thị đúng loại và không có ô rule không phù hợp.
- [ ] Submit trùng/retry không ghi hai decision hoặc chạy resume hai lần.
- [ ] Lỗi gate/option/run state trả 4xx envelope; state trên đĩa chứng minh quyết định đã/ chưa ghi.

**Verification:** contract tests cho từng loại gate, option giả, gate cũ, unauthorized, retry; browser approve flow.

**Dependencies:** Task 4, Task 7

**Files likely touched:** `src/analysis_system/web/app.py`, `src/analysis_system/api.py` chỉ khi cần tái sử dụng validation, `frontend` gate components, tests.

**Estimated scope:** Medium

### Checkpoint: Dataset flow

- [ ] Upload → clean → gate → approve → clean preview chạy được trên Next.
- [ ] Backend vẫn chặn được request giả dù UI ẩn/vô hiệu hoá nút.

### Phase 3 — Hỏi, phân tích, kết quả và xuất file

### Task 9: API ask/follow-up và dashboard

**Description:** Bổ sung ask JSON, parent/claim lineage, round status và dashboard material; giữ câu hỏi rỗng không tạo job và gọi `Workspace.ask` một lần.

**Acceptance criteria:**
- [ ] Ask trên clean table trả round id/question/state; câu hỏi tiếp ghi `lineage.json` đúng parent/claim.
- [ ] UI khóa nút khi gửi, retry không tạo hai round; polling dừng khi answer/gate/failure.
- [ ] Dashboard không làm mất câu trả lời trực tiếp hoặc round bị chặn.

**Verification:** API + disk assertions cho ask, follow-up, empty question, missing clean/model error và duplicate submit; browser flow.

**Dependencies:** Task 7, Task 8

**Files likely touched:** `src/analysis_system/web/app.py`, `src/analysis_system/web/view.py`, `frontend/src/app/bang-dieu-khieu/`, dataset/analysis components, tests.

**Estimated scope:** Large — tách ask contract khỏi UI dashboard nếu cần.

### Task 10: API/UI trang analysis đầy đủ

**Description:** Chuyển nội dung `analysis_page` thành payload có task progress, direct answer, blocked claims, warnings, risks, gaps, citations, measured/forecast, gate và lý do không có answer; React chỉ render.

**Acceptance criteria:**
- [ ] Mỗi analysis thuộc đúng dataset mới đọc được; round khác dataset/round không tồn tại trả 404.
- [ ] Direct answer, blocked conclusion, warning, source/citation và forecast-vs-measured đều hiện đúng fixture cũ.
- [ ] Tree/list numbering và lineage nhất quán với SSR; refresh có kiểm soát.

**Verification:** golden payload comparison trên cùng fixture, API contract state tests và Playwright analysis flow.

**Dependencies:** Task 4, Task 9

**Files likely touched:** `src/analysis_system/web/view.py`, `src/analysis_system/web/app.py`, `frontend/src/app/bo/`, analysis components, golden tests.

**Estimated scope:** Large — chia theo payload và component renderer.

### Task 11: Binary downloads và chart security

**Description:** Expose CSV sạch, Excel/Word answer và PNG chart qua `/api` rewrite, không thay engine chart và không nới lỏng path/ownership guard.

**Acceptance criteria:**
- [ ] CSV có BOM; xlsx/docx mở được và đúng filename/MIME.
- [ ] Chỉ round thuộc dataset hiện tại và answer tồn tại mới export được.
- [ ] Chart chỉ đọc PNG basename trong artifacts; traversal/đuôi sai/thiếu file trả 404.

**Verification:** byte-level/MIME/download tests, unauthorized and cross-dataset tests, browser download smoke.

**Dependencies:** Task 10

**Files likely touched:** `src/analysis_system/web/app.py`, `frontend` export controls, `tests/contract/test_web.py`, `tests/contract/test_web_api.py`.

**Estimated scope:** Medium

### Checkpoint: Full business flow

- [ ] Một fixture chạy được upload → clean → approve → ask → answer → chart/export trên Next.
- [ ] Kết quả analytics và artifacts khớp golden; không mất cảnh báo, nguồn hoặc kết luận bị chặn.

### Phase 4 — UI mượt, test tương đương và system

### Task 12: Hoàn thiện shell, loading/error/retry và performance guard

**Description:** Giữ app shell/sidebar/local state khi chuyển route; thêm error boundary, retry có điều kiện, mutation lock, polling backoff/timeout và tránh tải lại lịch sử/bảng lớn.

**Acceptance criteria:**
- [ ] Chuyển route nội bộ không full reload và không mất state không cần thiết.
- [ ] Backend unavailable, timeout, 401, 409 và 5xx có thông báo/hành động phù hợp.
- [ ] Poll dừng đúng lúc; request không tăng theo toàn bộ history/bảng lớn; không job duplicate.

**Verification:** Playwright network assertions, double-click/retry tests, đo số request/payload và manual slow-backend smoke.

**Dependencies:** Task 6, Task 8, Task 9, Task 10

**Files likely touched:** `frontend/src/components/`, `frontend/src/lib/`, app layouts/routes, browser tests.

**Estimated scope:** Large — tách shell/polling và performance nếu cần.

### Task 13: Chuyển test HTML thành contract/API/browser regression

**Description:** Giữ ý nghĩa test cũ nhưng thay assertion HTML bằng API/state assertions; thêm React component tests tối thiểu và Playwright cho các luồng chính; giữ SSR cũ đến khi parity đạt.

**Acceptance criteria:**
- [ ] Mỗi test hành vi quan trọng trong `tests/contract/test_web.py` có test API/browser tương đương hoặc được ghi lý do loại bỏ.
- [ ] Có test auth, ownership, path safety, running-delete 409, binary export, state/polling, answer/block/warning/source.
- [ ] Golden/regression chạy trên cùng fixture trước/sau; không chỉ kiểm tra HTTP 200.

**Verification:** `python tasks.py check`, frontend test/build, Playwright Chromium smoke, diff report golden.

**Dependencies:** Task 1, Task 5, Task 8, Task 10, Task 11, Task 12

**Files likely touched:** `tests/contract/`, `tests/golden/`, `tests/regression/`, `frontend` test config/specs, `tasks.py`.

**Estimated scope:** Large — chia theo API, React và browser.

### Task 14: System page, health, build và deployment dual-mode

**Description:** Hoàn thiện build/start Next, service tự khởi động, log, health checks, proxy và cơ chế update build FE thành công trước khi restart. Chốt một deployment mode cụ thể.

**Acceptance criteria:**
- [ ] Restart máy khởi động đủ Python và Next; health check phân biệt backend ready và frontend ready.
- [ ] Chế độ dev/migration dùng Next `3000 → Python 8020`; chế độ public `:8020` dùng reverse proxy và Python cổng nội bộ khác, không bind trùng.
- [ ] Update không kích hoạt FE/BE lệch version; bản cũ có thể quay lại nếu build/health smoke fail.
- [ ] Log chỉ rõ service, port, request id/job id và lỗi người dùng cần hành động.

**Verification:** clean-machine/container build, compose/systemd restart, health smoke, proxy routing, simulated failed build and rollback.

**Dependencies:** Task 3, Task 13

**Files likely touched:** `Dockerfile`, `docker-compose.yml`, `deploy/asys.service`, `DEPLOY.md`, `.env.example`, `frontend/next.config.ts`, build/task scripts.

**Estimated scope:** Large — tách build/runtime và cutover/rollback.

### Task 15: Cutover có kiểm soát

**Description:** Chỉ sau khi parity đạt mới chuyển UI chính; giữ SSR cũ trong rollback window, có checklist và mốc quyết định rõ ràng.

**Acceptance criteria:**
- [ ] Toàn bộ checkpoint trước đều xanh và baseline sau thay đổi có số liệu so sánh.
- [ ] Người vận hành có lệnh quay lại UI cũ/phiên bản cũ mà không làm mất dữ liệu `raw`, `runs`, `artifacts`.
- [ ] Tài liệu vận hành mô tả URL, port, health, log, rollback và cách xác nhận dữ liệu sau update.

**Verification:** rehearsal cutover/rollback trên fixture copy, smoke toàn bộ luồng chính và review cuối với người dùng.

**Dependencies:** Task 14

**Files likely touched:** `DEPLOY.md`, runbook/release notes, deployment configuration.

**Estimated scope:** Medium

## Các rủi ro chính

| Rủi ro | Mức | Giảm thiểu |
|---|---:|---|
| Tách logic trạng thái làm HTML và JSON lệch nhau | Cao | Task 4 trước UI; test state matrix và so sánh HTML/JSON trên cùng fixture. |
| API trả 200 nhưng thao tác không ghi đúng state | Cao | Mỗi mutation assert file/state trên đĩa, không chỉ status code. |
| Upload/ask retry tạo job đôi | Cao | mutation key/lock ở UI, guard/idempotency phù hợp ở backend, test double submit. |
| Polling vô hạn hoặc tải lại history lớn | Trung bình | server trả running/phase rõ; client timeout/backoff/dừng khi terminal; đo request/payload. |
| Cookie/proxy/port sai khi deployment | Cao | test cùng origin ở `3000 → 8020`; deployment test riêng cho public `:8020` + backend nội bộ. |
| FE/BE lệch version khi updater chạy | Cao | build artifact/version stamp, health trước cutover, rollback giữ dữ liệu. |
| Test HTML cũ che khuất lỗi JSON hoặc ngược lại | Trung bình | duy trì SSR trong migration window, API contract + browser + golden song song. |

## Open questions cần chốt trước Phase 4

1. Production URL cuối cùng là Next `:3000` sau reverse proxy ngoài, hay bắt buộc người dùng truy cập đúng `:8020`? Nếu là `:8020`, backend Python cần cổng nội bộ cụ thể (đề xuất `8021`).
2. Có được thêm Playwright/React test dependency vào `frontend` hay dùng harness hiện có? Hiện package chưa có test script.
3. Ngưỡng hiệu năng cần ghi nhận là bao nhiêu cho tải trang, API read, upload acknowledgement, polling và memory khi phân tích chạy?
4. Khi updater chạy, service có được restart sau khi build Next tại cùng host, hay build artifact được tạo trước trong CI/container rồi mới promote?

## Definition of Done toàn dự án

- [ ] Mọi hành vi cũ có đường chuyển đổi được chứng minh bằng API/UI/test.
- [ ] Python vẫn là nơi duy nhất quyết định nghiệp vụ.
- [ ] Auth, ownership, path safety, approval gate và running-delete guard được kiểm thử cả khi gọi trực tiếp API.
- [ ] Không mất answer trực tiếp, blocked conclusion, warning, source, approval/examination hoặc measured/forecast distinction.
- [ ] Test Python, API contract, golden/regression, browser và FE build đều đạt; baseline sau thay đổi có số liệu.
- [ ] Deployment restart/health/update/rollback đã diễn tập; chỉ sau đó mới bỏ/ẩn UI cũ.
