# TIẾN ĐỘ

Cập nhật sau mỗi phần hoàn thành. Nguồn chân lý về "đã làm gì / còn gì".

**Trạng thái:** Phase 0 ✅ · Phase 1 ✅ · Phase 2 ✅ · Phase 3 ✅ · Phase 4a ✅ · **Phase 4b ✅**
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
| ✅ | **Phase 6 — đo, không đoán** | `services/modelling.py`. Biến nào mang kết quả (`.importance.`) và dòng nào giống dòng nào (`cluster.`). **Không dự đoán từng dòng** — `evidence_ref` không phải sửa. Xếp hạng bị vứt nếu đổi hạt giống là đổi thứ tự; phân cụm bị từ chối nếu không tách biệt hơn dữ liệu vô cấu trúc cùng hình dạng (L63) |
| ✅ | **Kiểm độ liên quan** | `services/relevance.py`. Mỗi luận điểm được chấm với **chính câu hỏi của người dùng**, ngưỡng 0.25 — cái không trả lời câu hỏi bị đặt sang bên **kèm điểm số**, không bao giờ im lặng. So nghĩa (embedding) chứ không so từ: đo trên 16 ca thật, so từ vứt nhầm **7 câu trả lời thật**, so nghĩa vứt nhầm **0** (L64). Lệch dấu tiếng Việt vứt nhầm **8/16** nên bị coi là *chưa chấm được*, giữ nguyên và nói rõ (L65). Câu hỏi thật giờ tới được A9 kể cả khi model tự xếp bước tổng hợp (L66) |
| ✅ | **Khớp hình dạng câu trả lời** | `services/answer_shape.py`. Câu hỏi đòi **loại** trả lời nào (con số / xếp hạng / nguyên nhân / so sánh / xu hướng / nhận định), và câu trả lời có đúng loại đó không — đọc từ **họ khoá chỉ số**, không dùng model. Hỏi nguyên nhân mà chỉ đưa `.mean` thì **nói rõ là chưa trả lời được**, nhưng **không xoá luận điểm nào** (L67). Chỉ số `answers_the_question` |
| ✅ | **Việc 2 — mỗi skill một model** | `OpenRouterProvider` + `LlmPolicy.model`. **4 model đã gán**: `gemma-3-12b` (a7/a8/a9 — tiếng Việt có dấu 4/4), `gpt-oss-20b` (a3/a4/a6 — lineage 2/4, tốt nhất), `glm-5.3-flash` (a2 — context 1,31M cho bảng nhiều cột). Ngân sách dùng chung; `pricing.yaml` chặn model chưa khai giá. Chạy thật `hs__q14` đầu-cuối, **$0,0147 tổng chi**. L70 (bắt model chép chuỗi code đã biết), L71 (provider chọn ở 2 nơi) |
| ✅ | **Sửa A4 + A7 cho model nhỏ** | `CREATE VIEW` được prompt cho phép nhưng trả về biên nhận DDL (`['Count']`, 0 dòng) → lineage **hỏng 100%** dù model viết đúng (L73). Thông báo lỗi lineage giờ kèm **danh sách cột thật** (L72). `evidence_ref` do **code** đặt, model không được hỏi nữa — nó chép URI ví dụ trong prompt (L74). Và **ví dụ trong prompt bị chép**: ví dụ A4 dùng đúng bảng đang test nên `gemma` đạt 4/4 giả; đổi sang lĩnh vực trung lập thì rớt 0/4 → A4 chuyển sang `gpt-oss-20b` |
| ✅ | **Việc 3 — văn xuôi thành bảng** | `services/salience.py` + `a10_text_miner` (**không dùng model**). Đếm tần suất **mọi từ**, chia 3 băng và **nói rõ mỗi băng nghĩa là gì** — không xếp hạng tầm quan trọng, vì tần suất một mình không phân biệt được. Ghép cụm (tiếng Việt đơn âm nên `buu dien` mới là đơn vị, không phải `buu`). **Bảng chỉ lập khi người đọc chỉ định từ** (L75: mỗi dòng trỏ đúng trang tìm được số của nó). Bảng ghi vào `extracted://` nên đường ống cũ chạy tiếp → **PDF → Excel** |
| ✅ | **Sổ chi phí mỗi lượt chạy** | `runs/<run_id>/budget.json` — **cộng dồn** qua nhiều lượt gọi, vì một câu hỏi thường tốn 2 lượt (`ask` + `resume-dag`) và ghi đè sẽ báo nửa sau là toàn bộ (L76). Ghi cả khi vượt trần. Gộp `api._execute` và `cli._execute_plan` thành một `drive()` — **bản sao này đã gây 2 lỗi** (L71 provider, L77 sổ) |

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

## Phase 4b.1 — Đào sâu là đặc tính, không phải phần thêm ✅ HOÀN THÀNH

Nhánh `phase-4b1`. Đây là **năng lực** của hệ thống, không phải một tính năng gắn thêm.

| | Hạng mục |
|---|---|
| ✅ | `services/digging.py` — tự tìm thuộc tính ca · chia nhỏ theo thuộc tính · so sánh hai nhóm · **phân rã khoảng cách theo từng bước** |
| ✅ | Nối `digging` vào A6 | A6 nhận tham số `compare` và trả lời khoảng cách nằm ở bước nào. Và **luôn báo lên so sánh được theo những gì**, dù có được hỏi hay không |
| ✅ | Vòng hỏi–đáp: `asys clean` một lần → `asys ask "câu hỏi"` nhiều lần | Xong ở 4b.0 |
| ✅ | Skill báo cáo lên theo một khuôn chung | `TaskResult.declined` — mọi skill đã biết phần từ chối của mình nhưng mỗi cái để một chỗ, nên **không gì ở trên hỏi được "cái gì CHƯA được xác lập"**. Giờ hiện ra cuối mỗi lần chạy |

## Phase 4b.2 — Bằng chứng và lập luận ✅ HOÀN THÀNH

Nhánh `phase-4b2`.

| | Hạng mục |
|---|---|
| ✅ | Chart engine: heat · box · bar · hbar · grouped bar · scatter · line | `services/charts.py`, PNG tất định |
| ✅ | **Xếp hạng** loại biểu đồ, kèm lý do | `services/chart_choice.py`. Tối đa 2 cái mỗi loại — sáu góc nhìn về cùng một hình dạng là **một** góc nhìn (L55) |
| ✅ | **Manager tổng hợp** | `a9_manager` — có manifest và scope như mọi agent. Dùng nguyên `render_all` của A7, không dựng chỗ thứ hai để bịa số. Phần **không xác lập được** đặt trước mặt nó trước khi nó viết chữ nào |
| ✅ | Gate duyệt lập luận | `approve: claims`, manifest-driven như mọi gate khác |
| ✅ | Chọn định dạng xuất theo dữ liệu | Biểu đồ chọn theo **hình dạng dữ liệu**, không theo cấu hình cứng |
| ✅ | **Xuất BPMN 2.0 XML** | `asys bpmn <run> --out x.bpmn`. Chỉ cấu trúc, không toạ độ. **Nói rõ nó bỏ sót bao nhiêu** (L58) |
| ⬜ | `validation.py`: `regex_must_match` · `time_window` (chờ E1–E4 ở Phase 5) |

> **Ghi nhận một sai sót về quy trình.** `services/digging.py` được viết **trước khi** nó có
> mặt trong bất kỳ kế hoạch nào. Nó hữu ích và đúng hướng, nhưng nó vào code mà chưa ai đồng
> ý rằng nó đang được xây. Quy tắc số 1 — ý tưởng thêm thì ghi vào `NOTES.md` trước — tồn tại
> để chặn đúng chuyện đó, và nó đã bị bỏ qua.

## Phase 5 — Đọc dữ liệu phi cấu trúc ✅ HOÀN THÀNH

| | Hạng mục | Ghi chú |
|---|---|---|
| ✅ | Nhận dạng loại file bằng **byte** | `services/extraction.py` — không bao giờ tin đuôi file |
| ✅ | **E1 PDF** | Text theo trang + **bảng tách nguyên khối**. PDF là ảnh chụp thì nói rõ |
| ✅ | **E2 ảnh / OCR** | Từng từ một, kèm độ tin cậy và **toạ độ trên trang**. Tiếng Việt + Anh |
| ✅ | **E3 âm thanh** | Từng đoạn kèm mốc thời gian. Chưa tách được người nói — và nói ra điều đó |
| ✅ | `ExtractionResult` + `SourceLocator` | Văn bản không tồn tại được nếu thiếu **nơi nó đến từ** và **độ chắc chắn** |
| ✅ | **HUMAN GATE 0** | Chỉ hỏi khi đọc không chắc, và **chỉ đưa ra đoạn đáng ngờ** |
| ✅ | **Tiêu chí S6** | Đọc kém thì dừng; đọc ra không gì thì **thất bại**, không phải OK (L61) |
| ⬜ | Tách người nói (diarization) | Cần thư viện thêm |
| ✅ | Biến văn xuôi thành bảng | Xong, và **không cần model**: đếm từ, ghép cụm, nhặt số là số học. Cái cần model là *phán đoán từ nào đáng theo đuổi*, mà phán đoán đó thuộc về người đọc |

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
| Test | **1.170 pass** |
| Coverage | **92%** |
| Manifest | 12/13 (`a1`–`a8`, **`a9`**, **`e1`** **`e2`** **`e3`**) |
| Prompt | 7 (+ `manager_plan`) |
| Rule trong rulebook | 7 |
| Lỗi đã tìm và sửa | 59 (ghi ở `NOTES.md`) — **L55–L59 lộ ra khi chạy thật. L59 hỏng trong IM LẶNG: mọi luận điểm đúng, mọi trích dẫn vững, và tính năng chính không chạy** |
| Chi phí API tới nay | **$0** — `provider: handoff` |
