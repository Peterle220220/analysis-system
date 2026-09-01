# TIẾN ĐỘ

Cập nhật sau mỗi phần hoàn thành. Nguồn chân lý về "đã làm gì / còn gì".

**Trạng thái:** Phase 0 ✅ · Phase 1 ✅ · **Phase 2 ✅ HOÀN THÀNH (10/10)**
**631 test pass · coverage 92% · `python3 tasks.py check` sạch**

---

## Phase 0 — Baseline không AI ✅ HOÀN THÀNH

| | Hạng mục | Ghi chú |
|---|---|---|
| ✅ | Khung dự án | `pyproject.toml` `tasks.py` `Makefile` `config/settings.yaml` |
| ✅ | `settings.py` | 9 tầng khai báo độc lập, thiếu tầng → lỗi tiếng Việt rồi thoát |
| ✅ | `services/storage.py` | I/O duy nhất, ghi atomic |
| ✅ | `services/hashing.py` | `canonical_hash` — định nghĩa của tiêu chí S1 |
| ✅ | `services/rulebook.py` | **7 rule** (6 theo spec + `replace_sentinel_with_null`) |
| ✅ | `services/validation.py` | pandera + drift + range + comparison + reference |
| ✅ | `services/reporting.py` | Template Markdown, số chèn từ context |
| ✅ | `pipeline/run.py` + `cli.py` | Pipeline tuần tự Phase 0 |
| ✅ | `scripts/make_fixture.py` | Parser XES stdlib, cắt fixture bất biến |
| ✅ | Fixture BPI 2019 | 158 case · 5.000 event · 84 variant |
| ✅ | Golden test | Chạy 2 lần trùng `canonical_hash` |

## Phase 1 — Manager + 2 agent ✅ HOÀN THÀNH

| | Hạng mục | Ghi chú |
|---|---|---|
| ✅ | `contracts/base.py` | `ScopeToken` `DataRef` `TaskRequest` `TaskResult` — token frozen |
| ✅ | `services/boundary.py` | 3 lớp cưỡng chế, glob tự viết (`**` xuyên thư mục, `*` thì không) |
| ✅ | `services/scoped_storage.py` | Bọc storage, `load_*` / `save_*` |
| ✅ | `agents/base.py` | `BaseAgent` áp cả 3 lớp |
| ✅ | Test AST | Chặn `open` `os` `pathlib` `pd.read_*` `.to_parquet` `duckdb.connect` trong `agents/**` |
| ✅ | `services/audit.py` | JSONL append-only, 12 loại event |
| ✅ | `services/budget.py` | Đếm token/tiền/thời gian **tách riêng**, `pricing.yaml` |
| ✅ | `services/pii.py` | Regex 2 mức, cấm NER cho tên người, `assert_no_pii` |
| ✅ | `services/llm.py` | **4 provider**: `handoff` (0đ) · `cassette` (0đ) · `gemini` (free, nhưng Google huấn luyện trên dữ liệu gửi lên) · `anthropic` (có phí) |
| ✅ | `manager/state.py` | Resume cần task OK **và** hash đầu vào không đổi |
| ✅ | `manager/verifier.py` | PASS/RETRY/REPLAN/ESCALATE/GATE |
| ✅ | `manager/dispatcher.py` | Token cắt ra từ manifest, không lắp tay |
| ✅ | `manager/gates.py` + `runner.py` | HUMAN GATE 1, 2 bước, thoát mã 0 |
| ✅ | **A2 Profiler** | Code đo, LLM chỉ diễn giải. 4 chỉ số bổ sung: min/max, top_values, numeric_share, outlier IQR |
| ✅ | **A3 Cleaner** | Đề xuất → gate → chỉ chạy rule đã duyệt |
| ✅ | CLI gate | `run-agents` `gates` `approve` `resume` + lệnh `asys` |
| ✅ | `manager/planner.py` | **Cố ý hoãn ở Phase 1**, đã làm ở Phase 2 |

## Phase 2 — Đủ agent pool cho dữ liệu có cấu trúc ✅ HOÀN THÀNH

| | Hạng mục | Ghi chú |
|---|---|---|
| ✅ | **A1 Ingest** | CSV/TSV/Parquet/JSON/JSONL/XLSX · tự nhận encoding, delimiter, header · nạp về text, không diễn giải |
| ✅ | **A5 Validator** | Trọng tài, **cấm LLM tuyệt đối** · 6 loại kiểm tra · không sửa dữ liệu để pass |
| ✅ | **SQL guard** | Chặn 19 từ khoá phá huỷ · chặn lệnh thứ hai sau `;` · chặn `CROSS JOIN` · chặn bảng không được cấp · hiểu CTE |
| ✅ | **A4 Transformer** | Sinh SQL qua LLM · guard + DuckDB in-memory · lineage do model khai, code kiểm · chặn nổ dòng |
| ✅ | **A7 Analyst** | Code tính chỉ số · model viết câu có placeholder · code thay số |
| ✅ | Chống bịa số | **Cưỡng chế bằng hình dạng**: câu có chữ số gõ tay bị loại, placeholder phải trỏ chỉ số có thật |
| ✅ | **A8 Reporter** | Markdown + HTML + biểu đồ PNG · tóm tắt có chữ số gõ tay bị loại · PNG tất định |
| ✅ | **`manager/planner.py`** | Model sinh DAG, code duyệt trước khi chạy: agent phải có manifest · `depends_on` phải trỏ task trong kế hoạch · cấm chu trình · cấm trùng `task_id`. Thứ tự tất định: trong nhóm sẵn sàng, id nhỏ chạy trước. `default_plan()` khi không có model |
| ✅ | **retry/backoff · replan · GATE 2** | `manager/dag_runner.py` + `manager/retry.py`. Backoff luỹ thừa **không jitter** (jitter phá S1). Gate đọc từ manifest, không hard-code agent id. Thất bại qua hết số lần thử → escalate → planner có model được **một lần** lập lại kế hoạch |
| ✅ | **Golden expected + test tất định** | `tests/golden/expected/phase2.json` — full DAG 7 agent trên fixture BPI thật. Hai lần chạy khác run_id, khác thư mục, qua 2 gate → **trùng từng hash** |
| ✅ | CLI Phase 2 | `asys plan` sinh kế hoạch · `asys run-dag --plan` chạy · `asys resume-dag` chạy tiếp · **`asys export` xem/xuất CSV bất kỳ tầng nào**. Kế hoạch viết tay bị kiểm tra y như kế hoạch model viết |

## Deploy ✅

| | Hạng mục | Ghi chú |
|---|---|---|
| ✅ | Đường dẫn khả chuyển | `config/settings.yaml` dùng `${ANALYSIS_DATA}` / `${ANALYSIS_RUNS}` — không còn tên máy nào trong git. Biến không có mặc định thì **báo lỗi**, không nở thành `/raw` |
| ✅ | `requirements.lock.txt` | 61 gói ghim đúng phiên bản đã kiểm chứng |
| ✅ | `scripts/install.sh` | Chạy lại bao nhiêu lần cũng được. Tạo venv, cài theo lock, tạo 9 tầng, tự kiểm tra |
| ✅ | Lệnh `asys` thật | `[project.scripts]` trong `pyproject.toml`, không cần script bao ngoài |
| ✅ | [DEPLOY.md](DEPLOY.md) | Ubuntu Server 24.04: từ server trắng → chạy thật, systemd timer, sao lưu, bảng lỗi |
| ✅ | Kiểm chứng clone sạch | Clone mới → `install.sh` → 504 test pass → chạy job thật trên fixture BPI |

## Việc còn treo sau lần chạy thật với Gemini ⬜

Chạy toàn tuyến 7 agent trên fixture BPI thật đã lộ 4 vấn đề **không test nào bắt được**,
vì mọi provider trước đó đều là file cục bộ, không bao giờ hỏng tạm thời. Chi tiết ở
[NOTES.md](NOTES.md) mục L20–L23.

| | Việc | Vì sao |
|---|---|---|
| ✅ | **Replan chỉ được thay phần chưa chạy** | `frozen_tasks()` khoá task đã OK, đang chờ duyệt, hoặc đã có quyết định gate. Kế hoạch mới đổi `agent_id`/`depends_on`/`inputs_from`/`params` của chúng → **bị từ chối cả kế hoạch** |
| ✅ | **Ghi lại kế hoạch thật sự đang chạy** | `DagRunner` ghi `plan.json` mỗi lần kế hoạch đổi, nên state và kế hoạch không thể lệch nhau |
| ✅ | **Replan chỉ cho lỗi thuộc về kế hoạch** | `ErrorDetail.replannable` mặc định **False**. Chỉ lỗi "bị giao sai đầu vào" mới bật. Lỗi đầu ra của model → RETRY tại chỗ, kèm **lý do bị loại nhồi vào prompt** |
| ✅ | **Phán quyết của A5 có hậu quả** | Manifest khai `halt_on: checks_failed > 0` → cổng rẽ nhánh cứng. Bảng không đạt thì **không agent nào phía sau được chạy**. Không phải escalation: replan trên cùng dữ liệu sẽ hỏng y hệt |
| ✅ | **Kiểm chứng `evidence_ref`** | Hai lớp độc lập: A7 hỏi storage file có thật không rồi **loại** finding dẫn nguồn ảo; post-check từ chối nguồn ngoài phạm vi đọc (thuần hợp đồng, không đụng đĩa) |
| ✅ | **Nối `BudgetTracker` vào CLI** | Mọi provider gọi ra ngoài đều có trần token/tiền/thời gian. Chạm trần → **dừng, thoát mã 1**, không bao giờ tự chạy tiếp. Mỗi lần chạy in ra token và chi phí |

## Thống kê suy diễn ✅

| | Hạng mục | Ghi chú |
|---|---|---|
| ✅ | `services/statistics.py` | Tương quan Pearson + Spearman · t-test Welch · ANOVA · **effect size và eta²** bên cạnh p-value |
| ✅ | **Từ chối khi giả định không thoả** | Dưới 8 cặp · nhóm dưới 5 dòng · trên 20 nhóm · cột không đổi giá trị → **từ chối kèm lý do**, không tính bừa |
| ✅ | Chặn ngôn ngữ nhân quả | `causal_overreach()` — chỉ số chỉ đo mối liên hệ thì câu không được viết "làm tăng", "tác động đến"… Áp cho **cả kết luận lẫn tóm tắt** |
| ✅ | Nối vào A7 | Tham số `tests` trong kế hoạch khai báo phép kiểm nào được chạy |
| ⬜ | ML dự đoán | **Cố ý chưa làm** — một dự đoán không truy ngược về dòng dữ liệu nào, cần định nghĩa lại `evidence_ref` trước |

## Phase 3 — Hardening + Docker ⬜

Coverage ≥80% trên `services/` và `manager/` · regression suite cho prompt · README + sơ đồ kiến trúc · `Dockerfile` + `docker-compose.yml` · S1–S5 mỗi tiêu chí có test

## Phase 4 — Process mining & Signavio ⬜

**A6 Process Miner** · `agents/adapters/` · variant · bottleneck · rework · conformance · SoD · **xuất BPMN 2.0 XML** mở được trong Signavio

## Phase 5a — Extractor tài liệu & ảnh ⬜

**A0 Router** (magic bytes) · **E1 PDF** · **E2 Image/OCR** · **E4 Document** · `ExtractionResult` + `SourceLocator` · HUMAN GATE 0

## Phase 5b — Extractor audio/video ⬜

**E3** ffmpeg + faster-whisper ASR tiếng Việt · diarization · cache theo content hash

---

## Bảng tra nhanh

| Agent | Trạng thái | LLM? | Đọc | Ghi |
|---|---|---|---|---|
| A0 Router | ⬜ Phase 5a | Không | `raw://` | `runs/` |
| **A1 Ingest** | ✅ | Không | `raw://` `extracted://` | `staging://` |
| **A2 Profiler** | ✅ | Có (diễn giải) | `staging://` | `profile://` |
| **A3 Cleaner** | ✅ | Có (đề xuất) | `staging://` `profile://` | `clean://` |
| **A4 Transformer** | ✅ | Có (sinh SQL) | `clean://` | `mart://` |
| **A5 Validator** | ✅ | **Không** | mọi tầng trừ `raw://` | `validation://` |
| A6 Process Miner | ⬜ Phase 4 | Có (đặt tên) | `mart://` | `artifacts://` |
| **A7 Analyst** | ✅ | Có (diễn giải) | `mart://` | `artifacts://` |
| **A8 Reporter** | ✅ | Có (viết văn) | `mart://` `artifacts://` | `artifacts://` |
| E1–E4 | ⬜ Phase 5 | Có | `raw://` | `extracted://` |

## Số liệu

| | |
|---|---|
| Test | **631 pass** |
| Coverage | **92%** |
| Manifest | 7/13 (`a1` `a2` `a3` `a4` `a5` `a7` `a8`) |
| Prompt | 6 (+ `manager_plan`) |
| Rule trong rulebook | 7 |
| Lỗi đã tìm và sửa | 33 (ghi ở `NOTES.md`) — **L20–L33 đều tìm được khi chạy thật** |
| Chi phí API tới nay | **$0** — `provider: handoff` |
