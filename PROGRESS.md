# TIẾN ĐỘ

Cập nhật sau mỗi phần hoàn thành. Nguồn chân lý về "đã làm gì / còn gì".

**Trạng thái:** Phase 0 ✅ · Phase 1 ✅ · Phase 2 ✅ · Phase 3 ✅ · **Phase 4a ✅ HOÀN THÀNH (5/5)**
**643 test pass · coverage 92% · `python3 tasks.py check` sạch**

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
| ✅ | **Hồi quy bội** | Hệ số + p-value từng biến + R² hiệu chỉnh + VIF. Trả lời được câu tương quan đơn không trả lời được: mỗi biến đáng bao nhiêu **khi giữ nguyên các biến khác** |
| ⬜ | ML dự đoán (Phase 6) | **Cố ý để sau** — một dự đoán không truy ngược về dòng dữ liệu nào, cần định nghĩa lại `evidence_ref` trước |

## Phase 3 — Hardening + Docker ✅ HOÀN THÀNH

| | Hạng mục | Ghi chú |
|---|---|---|
| ✅ | Coverage ≥80% | `services` 94% · `manager` 93% · `agents` 96% · `contracts` 99% |
| ✅ | **S1–S6 mỗi tiêu chí một bộ test** | `tests/criteria/` — 27 test, mỗi test chạy một lần chạy thật. Kiểm **cả hai chiều**: S1 kiểm trùng hash *và* đổi một ô thì hash phải khác |
| ✅ | **Regression suite cho prompt** | `tests/regression/` — 52 test: mọi luật code cưỡng chế vẫn còn trong prompt, không prompt nào mồ côi, không prompt nào chứa khoá hay đường dẫn của một máy |
| ✅ | **Docker** | Build được, `docker compose run` chạy trọn job 5 task qua 3 lần gọi riêng biệt, qua human gate. `raw` read-only, user thường, `cap_drop: ALL` |
| ✅ | README + sơ đồ kiến trúc | Sơ đồ luồng dữ liệu và 4 lớp cưỡng chế |

## Phase 4a — Chọn lại & đào sâu quy trình ✅ HOÀN THÀNH

**Đã kiểm chứng** trên bộ study 200 dòng (Gemini free, $0): chọn đặc trưng → chạy lại đúng
phần bị ảnh hưởng → báo cáo chỉ còn chỉ số của đặc trưng đã chọn. Năm lỗi lộ ra, đã sửa
(L45–L49).

✅ **A6 và hai luật conformance đã kiểm** trên log cấp phép của một đô thị Hà Lan
(1.434 ca · 8.577 sự kiện · 27 hoạt động), khác lĩnh vực với BPI19. Hai luật kiểm soát
khớp **chính xác** với phép tính độc lập: 239 ca sai thứ tự, 2.105 sự kiện vi phạm phân
tách trách nhiệm. Hai lỗi lộ ra, đã sửa (L50–L51).

| | Hạng mục | Ghi chú |
|---|---|---|
| ✅ | **L40 — tham số vào danh tính task** | `TaskState.params_hash` + `params_fingerprint()`. Đổi SQL / cột / check / bộ rule đã duyệt → task chạy lại thay vì lặng lẽ trả kết quả cũ. Sửa ở **cả** `DagRunner` và `Phase1Runner`. 7 test mới, kiểm cả hai chiều |
| ✅ | **Chọn đặc trưng + chạy lại có chọn lọc** | `services/features.py` + `manager/selection.py` + `asys features` / `asys select`. Agent tự khai `consumes_features` trong manifest. Chạy lại đúng phần bị ảnh hưởng — **nhờ L40**, không phải nhờ code riêng |
| ✅ | **A6 Process Miner** | Code đo, model chỉ **đặt tên** — không kết luận gì, để khỏi dựng lại máy móc chống bịa số lần hai. Không có gate. A7 đọc bản đồ và hợp chỉ số vào |
| ✅ | `validation.py`: `sequence_order` | Luật thứ tự bắt buộc — chấm bởi A5. Không kiểm được thì báo **thất bại**, không im lặng đi qua |
| ✅ | `validation.py`: `segregation_of_duties` | Một người không được làm cả hai vai trong **một case**. Chạy được cả khi không có timestamp |

## Phase 4b.0 — Sửa lại nền, không đắp thêm ✅ HOÀN THÀNH

Ba chỗ cứng nhắc **nằm trong Phase 1 và 2**, không phải thiếu tính năng ở Phase 4. Đắp một
lớp mới lên trên là nhồi nhét; sửa ở nơi chúng thuộc về mới đúng.

| | Hạng mục | Vì sao đó là lỗi nền |
|---|---|---|
| ✅ | **Planner phải thấy hồ sơ dữ liệu trước khi lập kế hoạch** | Hiện nó chỉ thấy câu hỏi + đường dẫn file + danh sách agent. Nó lập kế hoạch **khi chưa biết trong dữ liệu có gì** — nên không thể biết bộ này có cột thời gian không, có đáng chạy hồi quy không |
| ✅ | **Bỏ ràng buộc khai trước `tests`** | Muốn có tương quan thì phải viết tay `tests: {correlations: [[a,b]]}` vào kế hoạch. Nghĩa là **người dùng phải biết trước câu trả lời nằm ở đâu** mới hỏi được |
| ✅ | **Tách hai giai đoạn: làm sạch ↔ hỏi** — $ /home/phongle/projects/analysis-system/.venv/bin/python -m analysis_system.cli clean rồi $ /home/phongle/projects/analysis-system/.venv/bin/python -m analysis_system.cli ask nhiều lần | Hiện là **một lần chạy duy nhất** nạp→sạch→phân tích→báo cáo. Đúng hình dạng phải là: làm sạch một lần, trả dữ liệu sạch cho người dùng xem, rồi hỏi nhiều lần trên đó |

## Phase 4b.1 — Đào sâu là đặc tính, không phải phần thêm 🔄

Nhánh `phase-4b1`. Đây là **năng lực** của hệ thống, không phải một tính năng gắn thêm.

| | Hạng mục |
|---|---|
| ✅ | `services/digging.py` — tự tìm thuộc tính ca · chia nhỏ theo thuộc tính · so sánh hai nhóm · **phân rã khoảng cách theo từng bước** |
| ⬜ | Nối `digging` vào A6 để Manager giao được việc "so sánh X với Y" |
| ⬜ | Vòng hỏi–đáp: `asys clean` một lần → `asys ask "câu hỏi"` nhiều lần |
| ⬜ | Skill báo cáo lên theo một khuôn chung: phát hiện · bằng chứng · **và những gì nó không trả lời được** |

## Phase 4b.2 — Bằng chứng và lập luận ⬜

Nhánh `phase-4b2`, merge với 4b.1 khi xong.

| | Hạng mục |
|---|---|
| ⬜ | Chart engine dùng lại được: heat · box · bar · hbar · grouped bar · scatter · line |
| ⬜ | **Xếp hạng** loại biểu đồ phù hợp, kèm lý do từng gợi ý |
| ⬜ | **Manager tổng hợp**: luận điểm → dẫn chứng → biểu đồ. Câu không dẫn được phát hiện nào thì **bị loại** |
| ⬜ | Gate: người dùng duyệt lập luận trước khi thành báo cáo |
| ⬜ | Manager chọn định dạng xuất từ chỉ số profile của A2, truyền xuống A8 |
| ⬜ | **Xuất BPMN 2.0 XML** mở được trong Signavio |
| ⬜ | `validation.py`: `regex_must_match` · `time_window` (chờ E1–E4 ở Phase 5) |

> **Ghi nhận một sai sót về quy trình.** `services/digging.py` được viết **trước khi** nó có
> mặt trong bất kỳ kế hoạch nào. Nó hữu ích và đúng hướng, nhưng nó vào code mà chưa ai đồng
> ý rằng nó đang được xây. Quy tắc số 1 — ý tưởng thêm thì ghi vào `NOTES.md` trước — tồn tại
> để chặn đúng chuyện đó, và nó đã bị bỏ qua.

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
| A6 Process Miner | ✅ | Có (**chỉ** đặt tên) | `clean://` `mart://` `staging://` | `artifacts://` |
| **A7 Analyst** | ✅ | Có (diễn giải) | `mart://` | `artifacts://` |
| **A8 Reporter** | ✅ | Có (viết văn) | `mart://` `artifacts://` | `artifacts://` |
| E1–E4 | ⬜ Phase 5 | Có | `raw://` | `extracted://` |

## Số liệu

| | |
|---|---|
| Test | **927 pass** |
| Coverage | **92%** |
| Manifest | 8/13 (`a1` `a2` `a3` `a4` `a5` **`a6`** `a7` `a8`) |
| Prompt | 7 (+ `manager_plan`) |
| Rule trong rulebook | 7 |
| Lỗi đã tìm và sửa | 54 (ghi ở `NOTES.md`) — **L45–L54 đều lộ ra khi chạy thật; không lỗi nào làm đỏ một test nào** |
| Chi phí API tới nay | **$0** — `provider: handoff` |
