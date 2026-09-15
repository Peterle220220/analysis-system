# Kế hoạch tái cấu trúc backend theo domain (DDD)

Trạng thái: đã duyệt (2026-09-15). Mỗi phase là một commit cục bộ; chủ hệ thống nghiệm thu
xong phase trước thì mới chạy phase sau. Không push khi chưa được phép.

## 1. Hiện trạng đo được (trước Phase 0)

| Hạng mục | Kết quả |
|---|---|
| `services/` | 78 module phẳng; 526 chỗ import chúng trong 207 file |
| Test | 2962 test qua; coverage tổng 89,9% |
| Coverage theo thư mục | `services/` 94,9% · `manager/` 93,4% · `agents/` 92,1% · `web/` 82,8% · gốc package 67% |
| File coverage thấp | `catalogue.py` 37% · `cli.py` 53% · `a7_analyst.py` 74% · `api.py` 79% · `web/app.py` 80% |
| Frontend | Next.js, có `package.json`, `Dockerfile` và bước build riêng; gọi backend qua REST `/api/*` |
| Frontend còn lẫn trong backend | `web/render.py` (1.385 dòng) và 9 route HTML trong `web/app.py` |
| File không ai import | Không có (`cli.py` là điểm vào của lệnh `asys`) |
| Trùng tên | `analysis_system/api.py` sẽ trùng với thư mục `api/`, nên đổi tên trước |

Đã kiểm, không phụ thuộc đường dẫn module:

- Dấu vân tay cassette tính từ nội dung prompt và `schema.__name__` (tên class), không từ
  đường dẫn module.
- Dữ liệu đã lưu là JSON, không dùng `pickle`.
- Không có import tương đối, không có `from analysis_system import services`.
- `AGENT_TYPES` giữ tham chiếu class qua import thường.

## 2. Quyết định đã chốt

1. BUILD_SPEC: được sửa cấu trúc thư mục (dòng 246-270) và Mục 10 theo cấu trúc mới.
2. Frontend: giữ Next.js và quy trình build hiện tại, không chuyển sang Vite.
3. Giao diện Python cũ: xoá `web/render.py`, 9 route HTML trong `web/app.py` và test của
   chúng. Systemd: Next.js là cổng duy nhất mở ra ngoài; FastAPI chỉ nghe `127.0.0.1:8020`.
4. `models/`: chỉ gom hợp đồng dùng chung (`contracts/`). Pydantic model riêng của domain
   nào ở lại domain đó.
5. `secret_scan.py` chuyển vào `scripts/` và commit. Xoá hẳn `draftprobe_tmp.py`.
6. Xoá toàn bộ danh sách mã chết ở Mục 6, **trừ** `pii.find_pii` và `sql_guard.is_safe`
   (API phòng thủ, giữ cho các bản cập nhật sau).

## 3. Cấu trúc đích

```
src/analysis_system/
├── api/                 <- web/ (app.py tách thành router: auth, datasets, bi, dashboards, runs, system)
│   └── presenters/      <- web/view.py, state.py, tree.py, naming.py (dựng JSON, không nghiệp vụ)
├── application/         <- api.py thành workspace.py (điều phối ca sử dụng)
├── core/                <- settings + hạ tầng dùng chung
├── models/              <- contracts/ (hợp đồng dùng chung)
├── domains/
│   ├── data_ingestion/
│   ├── ai_planner/
│   ├── execution_engine/
│   └── visualization/
├── agents/  manager/  pipeline/  cli.py   (giữ nguyên)
```

Bảng ánh xạ từng module nằm trong `scripts/refactor_map.py` (một nguồn duy nhất, dùng chung
cho `scripts/move_module.py` và test kiến trúc). Tóm tắt:

| Đích | Module |
|---|---|
| `core` | settings, hashing, pii, vietnamese_text, punctuation, units, storage, scoped_storage, boundary, audit, budget, job_error, updater, retention |
| `domains.data_ingestion` | ingestion, readers, column_names, number_format, diagnosis, rulebook, rule_names, rule_intent, validation, extraction, documents, dataset_origin, dataset_labels, dataset_removal, dataset_context, catalogue, glossary_store, glossary_draft, display_names, value_labels |
| `domains.ai_planner` | llm, prompts, routing, instructions, question_parts, question_labels, asked_columns, answer_shape, shortlist, relevance, relevance_notice, narrowing, salience, findings, direct_answer, risk_notes |
| `domains.execution_engine` | sql_runner, sql_guard, sql_shape, cross_row, point_values, data_scope, metrics, metric_families, statistics, group_means, forecast, modelling, features, digging, thresholds, process_mining, bpmn, timeline |
| `domains.visualization` | charts, chart_choice, svg_chart, dashboards, bi_schema, bi_query, bi_views, reporting, exporters, export_answer, metric_gauge |

`rulebook` nằm ở `data_ingestion` vì là luật làm sạch viết bằng code thuần (A3). `findings`,
`direct_answer`, `risk_notes` nằm ở `ai_planner` vì là lớp kiểm chứng đầu ra của model.

## 4. Quy tắc phụ thuộc

`api -> application -> agents / manager / domains -> models, core`

- `core` không import domain, agents, manager, application, api. `core` được dùng hợp đồng
  trong `models` (ranh giới cần `ScopeToken`), nên hai gói này cùng tầng dưới cùng.
- `models` chỉ import `core`.
- Domain không import `api`, `application`.

Vi phạm đang có lúc bắt đầu (danh sách nền của test):

| Vi phạm | Gỡ ở |
|---|---|
| ~~`vietnamese_text` (core) import `relevance` (ai_planner)~~ | Gỡ ở Phase 2: `fold`, `accented` về `vietnamese_text` |
| ~~`contracts.agents` (models) import `rulebook` (data_ingestion)~~ | Gỡ ở Phase 3: `RULE_ORDER` về hợp đồng |
| `api.py` (application) import `web/naming.py` (api) | Phase 8 |

Test `tests/unit/test_architecture.py` cưỡng chế theo kiểu bánh cóc: vi phạm đang có được
ghi tên trong danh sách nền và in ra báo cáo; vi phạm **mới** làm test trượt. Mỗi phase dọn
được vi phạm nào thì xoá khỏi danh sách nền; mục nào không còn thật thì test cũng báo.

## 5. Các phase

Cổng kiểm tra sau mỗi phase: ruff, mypy strict, toàn bộ pytest, coverage không thấp hơn
89,9%, build frontend, build Docker và curl cổng 8020, quét bí mật. Trượt cổng nào thì dừng.

- [x] **Phase 0: lưới an toàn** (chưa di chuyển file nào). Toàn bộ test qua, coverage 90,2%.
  - [x] Test import mọi module (`test_import_all.py`).
  - [x] Test kiến trúc bánh cóc (`test_architecture.py`) và bảng ánh xạ `refactor_map.py`.
  - [x] `scripts/move_module.py`: `git mv`, sửa mọi dạng import và chuỗi đường dẫn, chạy thử.
  - [x] Bổ sung test cho `catalogue.py`.
- [x] **Phase 1: dọn rác** (coverage 90,5%, mypy strict sạch) theo Mục 6; xoá giao diện Python cũ; sửa systemd;
  `secret_scan.py` vào `scripts/`; xoá `draftprobe_tmp.py`.
- [x] **Phase 2: `core/`**, kèm BUILD_SPEC Mục 6, 10, 12, 13, 15, `test_no_direct_io.py`,
  `per-file-ignores`. Coverage 90,5% (1.349 dòng chưa phủ, bằng Phase 1 đến từng file).
- [x] **Phase 3: `models/`** (đổi tên `contracts/`). Coverage 1.349/14.254, bằng Phase 2.
- [ ] **Phase 4-7: bốn domain**, rủi ro tăng dần: visualization, data_ingestion,
  execution_engine, ai_planner. Hết Phase 7 thì xoá `services/`.
  - [x] Phase 4: visualization (11 module). Coverage 1.349/14.255.
- [ ] **Phase 8: `application/` và `api/`**; rà `app.py` tìm nghiệp vụ và đẩy xuống domain.
- [ ] **Phase 9: tài liệu và triển khai** (DEPLOY, README, BUILD_SPEC cấu trúc thư mục).

## 6. Mã chết đã duyệt xoá (Phase 1)

Không nơi nào dùng:

- `agents/a1_ingest.py::staged_reference`
- `cli.py::_clean_profile`
- `services/features.py::kinds_in`
- `web/naming.py::phase_of`
- `web/view.py::_running_or_pending`
- `web/view.py::clean_report`

Chỉ test gọi (xoá cả test tương ứng):

- `agents/a3_cleaner.py::to_rule_specs`
- `manager/selection.py::bindings_for`
- `services/dataset_origin.py::origin_of`
- `services/digging.py::breakdown_by`
- `services/digging.py::worth_comparing`
- `services/features.py::restrict`
- `services/prompts.py::available_prompts`
- `services/question_parts.py::is_multi`

Giữ lại: `services/pii.py::find_pii`, `services/sql_guard.py::is_safe`.

Trước khi xoá từng mục vẫn đọc lại code, vì phép quét chỉ so tên và có thể sót lời gọi động.
