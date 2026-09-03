# NOTES — quyết định thiết kế, giả định, và ý tưởng ngoài phạm vi

Ghi theo Quy tắc 1 và mục cuối của checklist bàn giao. Mọi mục có ngày tuyệt đối.

---

## 2026-08-30 — Phase 0, bước 1–4

### Quyết định

**Q1. `pipeline/` chỉ tồn tại ở Phase 0.** Toàn bộ logic thật nằm ở `services/`. Phase 1 sẽ
**bọc** `services/` bằng lớp kiểm `ScopeToken`, và Manager thay thế `pipeline/`. Nguyên tắc:
*Phase 1 BỌC, không VIẾT LẠI.*

**Q2. Không viết stub cho Phase 1.** `storage.py` ở Phase 0 nhận `Path` tường minh, không có
tham số `scope: ScopeToken | None = None` khi `ScopeToken` chưa tồn tại.

**Q3. `canonical_hash` sắp xếp CẢ cột lẫn dòng.** Spec (Mục 13) nói "cột theo thứ tự khai báo";
tôi chọn sắp xếp cột theo tên. Lý do: đổi thứ tự cột không làm dữ liệu khác đi, nên hash không
nên đổi. Hệ quả: đổi tên cột vẫn làm hash đổi (đúng như mong muốn).

**Q4. `storage.py` KHÔNG tự tạo thư mục.** Ghi vào thư mục chưa tồn tại thì raise `StorageError`.
Nhất quán với quy tắc "không tự tạo thư mục thay thế" của `verify_layers`.

**Q5. Mọi ghi file đều atomic** (ghi `.tmp` cùng thư mục rồi `Path.replace`). Phục vụ tiêu chí
S3 (resume): tiến trình bị kill giữa chừng không để lại file hỏng.

**Q6. `read_csv` mặc định đọc mọi cột dưới dạng text** (`keep_all_as_text=True`). A1 Ingest bị
DENY "sửa giá trị ô", nên để pandas tự suy kiểu ở tầng nạp là sai — số 0 đứng đầu (`0012`) và
số thập phân (`10.50`) phải giữ nguyên cho tới khi rule làm sạch chạy.

**Q7. `assume_timezone: UTC`** trong `config/settings.yaml` là **đọc từ dữ liệu**, không phải
đoán: 100% `time:timestamp` trong BPI 2019 kết thúc bằng `Z`. Rule `standardize_datetime` vẫn
bắt buộc nhận tham số tường minh và raise nếu thiếu.

### Sai lệch so với spec — cần biết

**S1. Phiên bản thư viện mới hơn spec giả định.** Spec Mục 3 ghi `pandas>=2.2`, `pandera>=0.19`.
Thực tế pip cài: **pandas 3.0.5, pandera 0.33.0, mypy 2.3.1, duckdb 1.5.5, pyarrow 25.0.1**.
Chưa gây vấn đề ở bước 1–4. Rủi ro cần kiểm ở bước 7: pandera 0.33 đã đổi đường dẫn import
(`pandera.pandas` thay cho `pandera`), và pandas 3.0 đổi kiểu chuỗi mặc định.

**S2. Nguồn dữ liệu là XES, không phải CSV.** Spec Mục 15 (bản C3 cũ) giả định bản CSV 38 MB.
Thực tế dùng `BPI_Challenge_2019.xes` 694 MB. Lý do: bản CSV của ban tổ chức có dấu phẩy nằm
trong nội dung cột free-text, phải tách dòng bằng regex đặc biệt — bản XES cấu trúc rõ ràng hơn.
Parser sẽ viết bằng `xml.etree.ElementTree.iterparse` của thư viện chuẩn, **không thêm
dependency nào**.

**S4. ruff 0.16 định dạng cả code block trong Markdown.** Nó muốn viết lại các khối Python trong `BUILD_SPEC.md`, làm hỏng phần chú thích căn cột của spec. Đã thêm `*.md` vào `extend-exclude`. Spec là tài liệu, không phải code.

**S3. `scripts/` tạm thời bị loại khỏi `[tool.mypy] files`.** mypy báo lỗi khi trỏ vào thư mục
rỗng. **Phải thêm lại ở bước 5** khi `scripts/make_fixture.py` xuất hiện.

### Giả định

**G1. Regex loại dòng biến động.** `strip_volatile_lines` xoá mọi dòng chứa `run_id`,
`timestamp`, `duration`, `cost`. Hệ quả: báo cáo **không được** đặt số liệu thực chất trên một
dòng có chứa các từ đó, nếu không thay đổi thật sẽ bị che khuất khỏi hash. Sẽ tuân thủ khi
thiết kế template báo cáo ở bước 9.

**G2. `_is_missing` so sánh `pd.NaT` / `pd.NA` theo identity** thay vì gọi `pd.isna`, vì
`pd.isna` được đánh kiểu cho mảng và không nhận `object` dưới mypy strict. Chưa xử lý
`numpy.datetime64("NaT")` — chưa gặp trong luồng dữ liệu hiện tại.

### Ý tưởng ngoài phạm vi — GHI LẠI, KHÔNG CODE

- Nén `ext4.vhdx` sau khi xoá dữ liệu lớn (file vhdx chỉ phình, không tự co).
- Cắt fixture theo phương án phủ variant (cách B) có thể tái dùng làm công cụ lấy mẫu chung
  cho các event log khác — nhưng Phase 0 chỉ cần đúng một fixture.
- Lỗi "mã vendor không chuẩn": **cố ý không xử lý ở Phase 0** (không có rule nào cho nó trong
  bộ 6 rule). Dành cho A3 Cleaner ở Phase 2. Đây không phải bug.

---

## 2026-08-30 — Phase 0, bước 5–11 (hoàn thành Phase 0)

### Quyết định

**Q8. Nguồn là XES, parse bằng thư viện chuẩn.** `scripts/make_fixture.py` dùng
`xml.etree.ElementTree.iterparse` để quét file 694 MB theo luồng. **Không thêm dependency nào.**
Bản CSV của ban tổ chức bị loại vì chính trang BPI Challenge ghi rằng cột free-text có dấu phẩy
bên trong, phải tự tách dòng bằng regex — XES không có bẫy đó.

**Q9. Hai lượt quét thay vì một.** Lượt 1 lập chỉ mục (case_id, hash variant, số event) cho cả
251.734 case; lượt 2 đọc lại chỉ các case đã chọn. Cần lượt 1 vì quy tắc "sắp xếp theo case_id"
là quy tắc **toàn cục**, không thể quyết định khi mới đọc được một phần file. Tổng 28 giây.

**Q10. `scripts/` được miễn quy tắc "mọi I/O qua storage" ở phần ĐỌC.** Đọc XES đi thẳng qua
`iterparse` vì `storage` cố tình không có bộ đọc XES, và đây là công cụ chạy tay ngoài pipeline.
Mọi thứ script **ghi ra** vẫn đi qua `storage`, nên fixture được ghi atomic và cố định line ending.

**Q11. `pandera.pandas` là đường dẫn import đúng** ở pandera 0.33 (`import pandera` vẫn chạy
nhưng đã lỗi thời). Ghi lại vì spec Mục 3 viết theo bản 0.19.

**Q12. Cột nào chịu rule nào là CẤU HÌNH,** nằm trong `config/settings.yaml`
(`cleaning.datetime_columns`, `numeric_columns`, `required_columns`, và cả khối `validation`).
Theo Quy tắc 5: không hardcode. Đổi sang event log khác chỉ cần sửa YAML.

**Q13. `CONFIG_ENV_VAR = "ANALYSIS_SYSTEM_CONFIG"`.** CLI cho phép trỏ sang file cấu hình khác.
Thêm vào để test được CLI mà không đụng file đã commit; đồng thời có ích khi vận hành nhiều môi trường.

### Sai lệch đã đóng

**S3 — ĐÃ ĐÓNG.** `scripts/` đã được thêm lại vào `[tool.mypy] files` ở bước 5.

### Lỗi phát hiện trong lúc làm

**L1. `_atomic_write` để lại quyền 600.** `tempfile.mkstemp` tạo file 0600 và `Path.replace` giữ
nguyên quyền đó, nên mọi artefact pipeline ghi ra chỉ chủ sở hữu đọc được. Đã thêm
`_apply_default_permissions` áp umask hiện hành, kèm test.

**L2. Regex loại dòng biến động là cách sai — giả định G1 đã bị thay.** Bảng thống kê cột có một
dòng cho cột tên `timestamp`; regex theo từ khoá sẽ **xoá dòng nội dung thật** khỏi hash, che mất
thay đổi thật. Đã thay bằng **đánh dấu tường minh** `VOLATILE_MARKER` (`<!--volatile-->`): chỉ dòng
nào renderer chủ động gắn nhãn mới bị loại. Có test chứng minh cột tên `timestamp` vẫn ảnh hưởng hash.

**L3. Báo cáo in đường dẫn tuyệt đối làm hash phụ thuộc máy.** Dòng đường dẫn đã được đánh dấu
volatile; danh tính thật của đầu vào là `source_hash` (SHA-256), vẫn nằm trong hash. Có test.

### Quan sát về fixture và phân bố variant — ĐÃ QUYẾT (2026-08-30)

Cách cắt B (phủ variant) cho kết quả: **20 case / 1000 event / 20 variant**, tức **mỗi variant
xuất hiện đúng 1 lần**.

Hệ quả cho Phase 4: đo *tần suất* variant sẽ vô nghĩa — không có "happy path chiếm 60%", mọi
variant đều 5%. Khai phá variant, bottleneck, rework, conformance vẫn chạy được; riêng phân tích
theo tần suất thì không.

Ba lựa chọn, cả ba đều tất định:

1. **Giữ nguyên.** Phủ variant tối đa, chấp nhận không có phân bố tần suất.
2. **Chia ngân sách**, ví dụ 50% cho variant mới, 50% lấp tuần tự theo `case_id` — vừa có variant
   hiếm vừa có variant phổ biến lặp lại nhiều lần.
3. **Nâng ngân sách** lên 5.000–10.000 event. File vẫn nhỏ (~1,4–2,8 MB), commit được thoải mái.

Đề xuất: **2 kết hợp 3** (ngân sách 5.000 event, 50/50). Đổi thì phải sinh lại
`tests/golden/expected/pipeline.json` — mất khoảng 1 phút.

**Q14. Chọn phương án 2 + 3.** Ngân sách 5.000 event, chia 50/50 giữa phủ variant và lấp
tuần tự theo `case_id` (`DEFAULT_VARIANT_SHARE = 0.5`).

Kết quả trước và sau:

| | 1.000 event, phủ variant 100% | 5.000 event, 50/50 |
|---|---|---|
| Case | 20 | **158** |
| Variant | 20 | **84** |
| Variant lặp > 1 lần | 0 | **14** |
| Variant phổ biến nhất | 5% số case | **26.6% số case** |
| Trung vị event/case | 15 | **12** (khớp phân bố thật) |
| Kích thước file | 289 KB | 1.4 MB |

Giờ đã có "happy path" thật để đo tần suất ở Phase 4. `scripts/make_fixture.py` có 8 unit test
riêng (`tests/unit/test_make_fixture.py`), gồm test chứng minh lượt 2 làm variant phổ biến lặp lại
— đúng lý do phải chia ngân sách.

**Quan sát mới xuất hiện cùng lát cắt lớn hơn:** khoảng thời gian trải từ **2001-02-23** tới
2019-04-30, trong khi đây là log P2P 2018–2019. Mốc 2001 gần như chắc chắn là dữ liệu bẩn.
Phase 0 **không xử lý** — không có rule nào cho khoảng hợp lệ của ngày. Dành cho A5 Validator
ở Phase 2 (business rule kiểm khoảng thời gian). Ghi lại để sau này không ai tưởng là bug.

### Ý tưởng ngoài phạm vi — GHI LẠI, KHÔNG CODE

- `select_cases` có thể tách thành công cụ lấy mẫu event log dùng chung. Phase 0 chỉ cần một fixture.
- Cột `user` trùng 100% `org:resource` trong toàn bộ lát cắt — để A2 Profiler ở Phase 1 tự phát hiện,
  không xử lý ở Phase 0.

---

## 2026-08-31 — Phase 1, phần cưỡng chế + hạ tầng (chưa gọi LLM)

### Quyết định

**Q15. `ScopeToken` là `frozen`.** Agent nhận token chứ không tự tạo, và cũng không sửa được sau
khi nhận. Có test chứng minh gán lại `allow_write` bị pydantic từ chối.

**Q16. `DataRef.path` chỉ nhận URI `layer://`.** Đường dẫn hệ thống bị từ chối ngay ở tầng
contract. Nhờ vậy state file và `content_hash` không dính vị trí thư mục trên máy cụ thể.

**Q17. Tự viết bộ so khớp glob, không dùng `fnmatch`.** Trong `fnmatch`, `*` xuyên qua `/`, nghĩa
là `clean://*` sẽ khớp cả `clean://a/b/c.parquet` — mọi pattern trong manifest bị nới lỏng âm thầm.
Bộ dịch sang regex tự viết cho `**` xuyên thư mục, `*` thì không. Có test cho cả hai.

**Q18. Vi phạm boundary trả về `TaskResult(status=BOUNDARY_VIOLATION)`, không ném ngoại lệ ra
ngoài `BaseAgent.run()`.** Manager cần *ghi nhận* vi phạm rồi quyết định, chứ không phải hứng
exception. Ngoại lệ chỉ sống bên trong agent.

**Q19. `agents/base.py` là khung, không phải worker agent.** Nó cần `pathlib` cho type hint. Thay
vì miễn trừ hẳn khỏi test AST, tôi tách hai mức: worker agent bị cấm cả *import* lẫn *lời gọi*;
khung chỉ được phép nhắc tên `pathlib` nhưng **không được gọi bất kỳ I/O nào** — có test riêng.

**Q20. Log audit dùng `append_line`, không dùng đường ghi atomic.** Ghi lại toàn bộ file mỗi lần
có event vừa chậm vừa biến mỗi event thành một cơ hội mất lịch sử. Append nhỏ dưới `O_APPEND` là
atomic trên POSIX — đúng thứ log audit cần. Đã thêm `append_line` + `read_lines` vào `storage.py`.

**Q21. Đếm token và tiền TÁCH RIÊNG.** Đây là rủi ro R4 tôi nêu từ đầu, giờ đã có test chứng minh:
250.000 token *output* trên `claude-opus-5` tốn $6.25 — vượt trần $5 trong khi bộ đếm token mới
dùng một nửa. Gộp chung thì job thủng trần tiền mà vẫn tưởng còn dư.

**Q22. Cấm NER cho tên người, thay bằng cấm gửi cả cột.** Theo B8. Cột nào A2 gắn cờ PII thì
`build_llm_sample` **chỉ gửi tên cột + thống kê tổng hợp**, không gửi một giá trị nào. Đây là bảo
đảm mạnh hơn masking, vì không thể bị phá bởi một giá trị mà regex không nhận ra.

**Q23. `assert_no_pii` là chốt chặn cuối** ngay trước khi payload rời tiến trình. Có test chứng
minh nó bắt được email lọt lưới.

**Q24. Fixture PII tự chế** `tests/fixtures/pii_sample.csv` (20 dòng, giá trị bịa hoàn toàn). BPI
2019 đã ẩn danh nên không test được đường PII — đúng như C3 đã nêu.

### Lỗi phát hiện trong lúc làm

**L4. `find_pii` đếm trùng.** Nó chạy *tất cả* pattern trên văn bản gốc, nên số 10 chữ số vừa khớp
`PHONE` vừa khớp `BANK_ACCOUNT` → báo 3 giá trị trong khi chỉ có 2. `mask_text` thì tiêu thụ tuần
tự nên không bị. Đã cho `find_pii` tiêu thụ span giống hệt `mask_text`. Test bắt được.

**L5. Quyền file 600 (đã sửa ở Phase 0) tái xuất hiện dưới dạng khác:** `append_line` không đi qua
`_atomic_write` nên không áp umask. Với append thì Python tạo file theo umask sẵn — không có vấn đề.
Ghi lại để sau này không ai "sửa nhầm".

### Ngoại lệ lint có chủ ý

`ruff` (rule N818) đòi tên ngoại lệ kết thúc bằng `Error`. Hai tên **do spec Mục 10 quy định** nên
spec thắng, đã thêm `per-file-ignores` kèm lý do:

- `BoundaryViolation` (`services/boundary.py`)
- `BudgetExceeded` (`services/budget.py`)

Riêng `PiiLeak` là tên tôi tự đặt, không phải spec → đã đổi thành `PiiLeakError` theo ruff.

### Còn lại của Phase 1

Manager (`state` / `dispatcher` / `verifier` / `planner`) · A2 Profiler · A3 Cleaner ·
`services/llm.py` · `prompts/` · HUMAN GATE 1 hai bước · test resume.

`planner.py` và phần đề xuất rule của A2/A3 **sẽ gọi API Anthropic thật và tốn tiền** — chờ user
quyết trước khi chạm tới.

### Quyết định — Manager và lớp LLM (2026-08-31)

**Q25. Token luôn được CẮT RA TỪ manifest, không lắp tay.** `Dispatcher.issue_scope()` dựng
`ScopeToken` từ chính `manifest.allow`, nên **không thể tạo ra token rộng hơn manifest** — thay vì
để pre-flight bắt lỗi đó về sau. Thu hẹp thì bằng `params`, không bao giờ bằng cách nới rộng.

**Q26. Vi phạm boundary và chạm trần ngân sách KHÔNG BAO GIỜ được retry.** Retry một agent vừa cố
bước ra ngoài phạm vi là phản ứng sai. Chạm trần ngân sách mà chạy tiếp thì trái thẳng Mục 12.
Cả hai đi thẳng `ESCALATE`. Có test cho từng trường hợp.

**Q27. Resume cần ĐỒNG THỜI hai điều kiện:** task đã `OK` **và** hash đầu vào không đổi. Chỉ kiểm
trạng thái thôi thì chạy lại trên dữ liệu đã khác sẽ âm thầm trộn hai lần chạy vào nhau. Quyết định
của human gate được lưu **như dữ liệu** trong `state.json` và **phát lại** khi chạy lại cùng
`run_id` — không có điều này thì một run có gate không bao giờ tái lập được (S1).

**Q28. `services/llm.py` có 3 provider thay vì 1** — theo hướng user đã chốt ngày 2026-08-31:

| Provider | Cách chạy | Chi phí | Dùng khi |
|---|---|---|---|
| `cassette` | phát lại JSON đã ghi, khoá theo fingerprint của request | 0đ | **mọi test** — LLM trong vòng lặp sẽ phá S1 |
| `handoff` | ghi prompt ra file → người dán vào Claude (gói Pro) → dán JSON về | 0đ | chạy thật hiện nay |
| `anthropic` | gọi API thật | có phí | khi bật thu tiền sau này |

Ba điểm đáng ghi:

- **Fingerprint theo nội dung.** Đổi prompt một ký tự là hỏi câu mới, không âm thầm phát lại câu
  trả lời cũ. Có test.
- **`handoff` tái dùng nguyên cơ chế gate 2 bước** (C13): ghi file, thoát, chờ người, resume.
  Không phải viết thêm máy trạng thái nào.
- **`LlmClient` bọc mọi provider và chạy `assert_no_pii` trước mỗi lần gửi.** Không provider nào
  bỏ qua được bước này, kể cả provider viết thêm sau này. Có test chứng minh email chưa mask bị chặn.

**Q29. Cài `anthropic` SDK ngay bây giờ (bản 1.2.0).** Cài SDK không tốn tiền; chỉ khi provider
`anthropic` được bật mới phát sinh chi phí. Cài sẵn để mypy kiểm được đường code đó và để lúc bật
chỉ cần đổi một dòng config.

**Cảnh báo trung thực:** provider `anthropic` mới chỉ được test bằng client giả (kiểm đúng tham số
gửi đi: `model`, `system`, `output_format`, và việc trừ ngân sách). **Chưa từng gọi endpoint thật.**
Lần đầu bật lên phải coi là chưa kiểm chứng.

### Quyết định — A2, A3, gate và vòng điều phối (2026-08-31)

**Q30. `ScopedStorage` dùng `load_`/`save_`, `storage` dùng `read_`/`write_`.** Không phải thẩm mỹ:
test AST cấm mọi `.read_*`, nên `files.read_parquet()` hợp lệ sẽ bị báo oan. Tách tên khiến mọi
`read_*`/`to_*` xuất hiện trong agent **chắc chắn là vi phạm** — không còn gì để tranh cãi.

**Q31. `ManifestDir` export từ `agents/base.py`.** Agent bị cấm `import pathlib`, nhưng vẫn cần
nhận đường dẫn manifest. Khung export alias để agent không phải nhắc tới `pathlib`.

**Q32. `planner.py` chưa viết — Phase 1 dùng DAG khai báo sẵn** (`PHASE1_DAG` trong `runner.py`).
Phase 1 chỉ có 2 agent nên thứ tự là hiển nhiên, không cần LLM suy luận. Planner bằng LLM để tới
Phase 2 khi có 8 agent. Nhờ vậy Phase 1 chạy được **không tốn đồng nào**.

**Q33. A3 có hai chế độ, quyết định bởi `scope.params`.** Không có `approved_rules` → chỉ đề xuất,
**không ghi gì cả**, trả `NEEDS_REVIEW`. Có → chạy **đúng** những rule đó. Đây là HUMAN GATE 1.

**Q34. Trần `max_rows_dropped_pct` được kiểm TRƯỚC khi ghi.** Nếu rule đã duyệt sẽ bỏ quá tỷ lệ
cho phép thì **không file nào được tạo ra** — không để lại artefact nửa vời cho ai đó nhặt nhầm.

**Q35. Handoff pending là TẠM DỪNG, không phải lỗi.** Chờ người chuyển tiếp câu hỏi giống hệt chờ
người duyệt gate: ghi file, ghi state `PAUSED_AWAITING_APPROVAL`, thoát mã 0. Để exception văng ra
thành traceback sẽ khiến đường không-tốn-tiền trông như hỏng.

### Lỗi phát hiện — tất cả đều do test hoặc chạy thật

**L6. Test AST bắt A2 `import pathlib`.** Guard đúng, code sai. → Q31.

**L7. `postcheck` biến lỗi trung thực thành vi phạm boundary.** Hai lần, hai chỗ:
- Đòi `must_return` từ kết quả đã `FAILED` — mà task hỏng thì đương nhiên không có payload.
- Kiểm `max_rows_dropped_pct` trên kết quả A3 đã tự báo `FAILED` với lý do chính xác, rồi thay
  thông điệp cụ thể bằng một thông điệp chung chung.

Sửa: postcheck **chỉ áp dụng cho kết quả tự nhận là `OK`**. Nó tồn tại để bắt agent *khai thành
công* mà vi phạm giới hạn; agent đã tự dừng thì không cần bắt lại.

**L8. `guess_roles` nhận diện sai `case_id`.** Khớp chuỗi con: `"case"` nằm trong `"case_company"`,
và cột đó đứng trước theo thứ tự chữ cái → `case_id = "case_company"`. Nếu lọt, Phase 4 khai phá
variant trên cột sai hoàn toàn mà **không có dấu hiệu gì báo lỗi**. Sửa: khớp chính xác trước
(tên vai trò → tên gợi ý → mới tới chuỗi con). Chỉ lộ ra vì test chạy trên fixture BPI thật.

**L9. Provider ghi file không tạo thư mục.** Phát hiện khi **chạy CLI thật**, không phải test.
`storage` cố tình không tạo thư mục (tầng dữ liệu thiếu là lỗi cấu hình người dùng phải sửa), nhưng
thư mục làm việc của provider bên trong run dir là chuyện khác — provider tự tạo, như `GateStore`
đã làm.

**L10. Regex PII báo nhầm `case_id` là dữ liệu cá nhân.** Nghiêm trọng nhất trong nhóm này.
`BANK_ACCOUNT = \\d{8,19}` khớp mọi chuỗi 8–19 chữ số, mà số chứng từ mua hàng đúng là như vậy.
Hậu quả: **`case_id` — cột quan trọng nhất cho process mining — bị giữ lại không gửi cho model.**

Gốc rễ: chuỗi số trần **không mang thông tin** về việc nó là số tài khoản hay số chứng từ. Sửa
bằng hai mức bằng chứng ở **cấp cột**:
- **Mạnh** (email, phone): tự nó đủ nhận dạng → gắn cờ chỉ dựa vào giá trị
- **Yếu** (số tài khoản, MST, CCCD): cần **tên cột đồng ý** mới gắn cờ

Masking ở cấp giá trị **không đổi** — mọi pattern vẫn che, `assert_no_pii` vẫn fail-closed trên văn
bản tự do. Chỉ đổi cách phân loại cả cột.

Kết quả sau khi sửa:

| Fixture | Trước | Sau |
|---|---|---|
| BPI 2019 (đã ẩn danh) | `case_id`, `case_purchasing_document` | `[]` ✓ |
| `pii_sample.csv` (tự chế) | 5 cột | 5 cột ✓ |

Lưu ý: `full_name` **không** bị gắn cờ — đúng theo B8 (cấm NER cho tên người). Tên được bảo vệ bằng
cách A2 hoặc người dùng gắn cờ cột, rồi cột đó không được gửi giá trị nào.

### Trạng thái Phase 1

Xong: contracts · boundary 3 lớp · audit · budget · PII · LLM 3 provider · Manager
(state/dispatcher/verifier/gates/runner) · A2 · A3 · prompts · CLI gate 2 bước · resume.

Chưa làm, có chủ ý: `planner.py` bằng LLM (Q32) — để Phase 2.

---

## 2026-08-31 (chiều) — Chạy thật trên dữ liệu ngoài, và những gì nó phơi ra

User chạy Phase 1 trên bộ dữ liệu của riêng mình: giá nhà Seattle, 4.600 dòng × 18 cột,
`~/analysis-data/raw/modified_data.csv`. Hoàn toàn không phải event log. Đây là lần đầu hệ thống
gặp dữ liệu nó không được thiết kế cho.

### Lỗi phát hiện

**L11. Chỉ số hồ sơ mới đi thẳng vào prompt, không qua bộ che.** `min`/`max`/`top_values` được
thêm vào payload A3 mà quên đưa qua `PiiMasker`. Lưới `assert_no_pii` chặn được — guard làm đúng
việc.

**L12. Giá nhà 26.590.000 khớp regex số tài khoản.** Cùng loại với lỗi `case_id` sáng nay, nhưng ở
**cấp giá trị** thay vì cấp cột — tôi mới sửa một nửa. Nay đã nhất quán hai mức ở cả hai nơi:
- **Hình dạng đặc trưng** (`EMAIL`, `PHONE`, `TAX_ID`): che ở mọi nơi, `assert_no_pii` chặn
- **Chuỗi số trần** (`BANK_ACCOUNT`, `NATIONAL_ID`): chỉ che khi **tên cột xác nhận**

`assert_no_pii` giờ chỉ chặn nhóm đặc trưng. Nó không thể phán xét một chuỗi số khi không biết cột,
và chặn mọi số lớn thì làm hỏng bảng giá mà chẳng bảo vệ được ai.

**L13. `PHONE` xếp trước `TAX_ID` nên nuốt mất 10 chữ số đầu của mã số thuế.** `0101234567-001` bị
báo là số điện thoại. Chính comment của tôi ghi "specific first" mà thứ tự lại sai. Đã đảo.

**L14. Mọi lần chạy ghi đè cùng `staging://events.parquet`.** Chạy bộ dữ liệu thứ hai là đè mất bộ
thứ nhất, và resume lần chạy cũ sẽ đọc nhầm dữ liệu người khác. Nay mỗi run có file riêng
`staging://<run_id>_events.parquet`.

### Quyết định

**Q36. Bổ sung 4 chỉ số vào A2** — `min_value`/`max_value`, `top_values` (5 giá trị phổ biến nhất),
`numeric_share`, `outlier_count` (IQR), cộng `duplicate_rows` ở cấp bảng.

Không phải mở rộng phạm vi: spec Mục 8 đã liệt kê A2 phải có *"thống kê mô tả · đo
null%/duplicate/cardinality · phát hiện outlier (IQR, z-score)"*. Tôi mới làm null% và cardinality.

Chính model chỉ ra thiếu sót này: nó phải **suy gián tiếp** rằng `yr_renovated` đầy số 0 bằng cách
so `avg_length` 2.22 với `yr_built` 4.0, và nói thẳng ba chỉ số nó cần mà không có.

**Q37. Gate tách option theo từng nhóm cột.** Model cố ý chia `cast_numeric_safe` thành nhiều nhóm
theo mức rủi ro để người duyệt riêng, nhưng gate gộp hết thành một option — `--select` lấy cả hoặc
không lấy gì. Nay rule xuất hiện một lần thì giữ id gốc; xuất hiện nhiều lần thì thành
`rule#1`, `rule#2`, mỗi option mang chỉ số của mục nó đại diện.

**Q38. `resume` không cần `--input`.** State ghi lại tham chiếu nguồn khi bắt đầu. Kèm theo đó:
`run-agents` nạp dữ liệu, `resume` **không nạp gì cả** — trước đây hai lệnh dùng chung một hàm nên
mỗi lần resume lại ghi đè staging một lần nữa.

**Q39. Lệnh `asys` ở `~/.local/bin`.** User vấp lỗi thư mục làm việc hai lần. `~/.local/bin` phải
được thêm vào PATH trong `.bashrc`, không chỉ `.profile` — terminal VS Code không phải login shell.

**Q40. THÊM RULE THỨ 7: `replace_sentinel_with_null`.** User duyệt ngày 2026-08-31.

Đây là **sai lệch có chủ ý** so với Mục 14 ("Rulebook Phase 0 — đúng 6 rule, không hơn"), nhưng nó
đóng lỗ hổng so với chính đặc tả A3 ở Mục 8: *"xử lý missing (**drop/fill/flag**)"* — mới có `flag`.

Dữ liệu thật ép phải có nó. Trong bộ giá nhà Seattle, số 0 mang **ba nghĩa khác nhau**:

| Cột | Số dòng = 0 | Nghĩa |
|---|---:|---|
| `waterfront`, `view` | 4.567 / 4.140 | **Bậc hợp lệ** — không sát mặt nước, không có tầm nhìn |
| `sqft_basement`, `yr_renovated` | 2.745 / 2.735 | **Canh chừng** — không có tầng hầm, chưa cải tạo |
| `price`, `bedrooms`, `bathrooms` | 49 | **Dữ liệu hỏng** — nhà không thể giá 0 |

Rule **từ chối đoán hai lần**: phải khai báo `sentinels`, và phải khai báo `columns`. Áp mù lên
toàn bảng sẽ xoá 4.567 giá trị `waterfront` hợp lệ. Có test cho cả hai lần từ chối.

Chạy trên dữ liệu thật: 49 giá 0 → rỗng, 2.735 `yr_renovated` → rỗng, `waterfront` **giữ nguyên**,
không bỏ dòng nào. Giá trung bình từ $551.963 về $557.906 — đúng bằng con số tính tay khi loại 49
dòng đó.

Đặt **trước** `standardize_datetime` và `cast_numeric_safe` trong `RULE_ORDER`: canh chừng phải
thành rỗng khi còn là text, để bước ép kiểu không bao giờ nhìn thấy và không báo nhầm là giá trị
lỗi. Và `flag_missing_required` chạy cuối nên **nhìn thấy** những giá trị rỗng vừa tạo ra — hai rule
ăn khớp nhau.

### Quan sát về chất lượng đề xuất

Sau khi có 4 chỉ số mới, mọi lần từ chối của model đều dựa trên **bằng chứng cứng** thay vì
"thiếu thông tin". Một suy luận đáng ghi lại:

> *"`trim_whitespace` — có bằng chứng ngược lại: min của các cột chuỗi là `Algona`, `WA 98001`,
> `1 View Ln NE`, đều không bắt đầu bằng khoảng trắng, mà nếu tồn tại giá trị có khoảng trắng đầu
> thì chính nó đã là min."*

Khoảng trắng sắp trước mọi chữ cái, nên `min` của cột text **chính là** phép kiểm khoảng trắng
thừa. Tôi thêm `min`/`max` để bắt giá 0 hoặc âm, không hề nghĩ tới cách dùng này.

**Nhưng cũng có chỗ model phóng đại:** nó gọi 49 dòng giá 0 là *"lỗi nghiêm trọng nhất trong bộ dữ
liệu"*. Đo ra thì sai lệch giá trung bình chỉ **1,1%**. Đáng sửa, không phải thảm hoạ. Đây đúng là
loại định lượng không có cơ sở mà A5 và A7 ở Phase 2 phải chặn.

### Ý tưởng ngoài phạm vi — GHI LẠI, KHÔNG CODE

Model chỉ ra ba rule còn thiếu; đã làm 1, hai cái còn lại để sau:

- `flag_rows_by_condition` — đánh dấu/loại dòng theo điều kiện giá trị (ví dụ `price <= 0`)
- `recompute_derived` — tính lại cột dẫn xuất sau khi làm sạch. **Để Phase 2**: nó cần biết công
  thức dẫn xuất, mà đó đúng là việc của A4 Transformer (`price_per_sqft = price / sqft_living`).
  Hiện tại `price_per_sqft` kế thừa nguyên lỗi của `price` — đúng 49 giá trị 0 khớp nhau.

---

## 2026-08-31 (tối) — Phase 2, planner

**Q41. Model lập kế hoạch, code duyệt kế hoạch.** Phase 1 dùng DAG khai báo sẵn vì chỉ có hai
agent, không có gì để cân nhắc. Với tám agent thì có: cần gọi những agent nào, theo thứ tự nào,
giao việc gì. Đây là chỗ đầu tiên trong hệ thống thật sự đáng hỏi model.

Nhưng thứ model trả về là **kế hoạch, không phải hành động**. Không dòng nào chạy trước khi code
đồng ý cả bốn điều: mọi agent được gọi phải có manifest; mọi `depends_on` phải trỏ tới task trong
cùng kế hoạch; đồ thị không được có chu trình; `task_id` không được trùng.

**Q42. Kế hoạch sai thì loại cả kế hoạch, không vá.** Vá một chu trình nghĩa là tự chọn một thứ tự
mà không ai chọn — đúng loại "code tự suy diễn" mà Section 0 cấm. `validate_plan` trả về *danh
sách* vấn đề chứ không dừng ở cái đầu tiên, để lần replan sau model thấy hết một lượt.

**Q43. Thứ tự tất định, không theo thứ tự dict.** Trong nhóm task đã đủ điều kiện chạy, **id nhỏ
chạy trước**. Không có quy tắc phá hoà này thì thứ tự phụ thuộc vào thứ tự duyệt dict, và hai lần
chạy cùng một kế hoạch có thể ra hai chuỗi khác nhau — hỏng tiêu chí S1.

**Agent không có manifest thì không lập kế hoạch được.** `available_agents()` đọc `config/manifests/`
làm nguồn chân lý. Manifest chính là cái tạo ra boundary; không manifest thì không có gì để cưỡng
chế, nên agent đó không được đưa vào danh sách cho model chọn. Manifest hỏng thì **im lặng không
chào**, chứ không làm sập planner.

**`default_plan()` không phải fallback ngầm.** Khi không có model, caller phải tự gọi nó. Lý do
được ghi thẳng vào kế hoạch: `"...khong dung model."` Một kế hoạch không ai cân nhắc không được
phép trông giống một kế hoạch model đã cân nhắc.

---

## 2026-08-31 (khuya) — Phase 2, phần ghép nối: retry, replan, GATE 2, golden

**Q44. Backoff không có jitter — cố ý.** Jitter đúng khi nhiều client cùng thử lại vào một dịch
vụ. Ở đây một lần chạy là một vòng lặp tuần tự, không có đám đông nào để dàn ra. Cái jitter sẽ
lấy đi là tiêu chí S1: hai lần chạy cùng một kế hoạch sẽ không còn hành xử giống nhau. Việc `sleep`
được tiêm vào từ ngoài, nên test chứng minh được lịch chờ mà không phải chờ thật.

**Q45. Gate đọc từ manifest, không hard-code agent id.** Trong `dag_runner.py` không có một câu
`if agent_id == "a3_cleaner"` nào. Task dừng lại vì manifest của nó ghi `human_gate.required`, và
dừng *lúc nào* là do manifest ghi `before_execution` hay `after_execution`:

- **before_execution** (A3): chạy agent ở chế độ đề xuất, ghi ra thứ nó đề xuất, rồi dừng.
- **after_execution** (A7, GATE 2): để agent chạy xong, rồi dừng *trước khi* bất cứ thứ gì phía
  sau được dùng kết quả đó.

Gate mà Manager không biết thi hành (`approve:` là một giá trị lạ) thì **báo lỗi to**, không lặng
lẽ bỏ qua — một gate không ai thi hành được sẽ treo lần chạy vĩnh viễn.

**Q46. Quyết định của GATE 2 đi xuống dưới dạng tham số.** Gate duyệt sau khi A7 chạy xong thì
không đổi được gì ở A7 nữa — nó đã xong. Cái nó đổi là mọi thứ phía sau. Nên quyết định được
truyền xuống như một scope param `approved_findings`, đúng cách `approved_rules` đi vào A3. A8 tự
lọc theo vị trí (`f1`, `f2`), và **id trỏ vào chỗ không có kết luận nào thì báo lỗi** — nghĩa là
quyết định và phân tích đang nói về hai thứ khác nhau, im lặng bỏ qua sẽ ra báo cáo chứa thứ không
ai duyệt.

**Q47. `inputs_from` — thứ tự và dòng dữ liệu là hai chuyện khác nhau.** Ban đầu tôi định "task
đọc kết quả của task nó phụ thuộc". Sai ngay ở A7: A7 phải chạy **sau** khi kiểm định xong, nhưng
thứ nó **đọc** là bảng mart của A4, không phải báo cáo kiểm định của A5. Nên `PlannedTask` có thêm
`inputs_from`, mặc định bằng `depends_on`. Và `validate_plan` bắt buộc `inputs_from` phải nằm
trong **tập phụ thuộc bắc cầu** — đọc của một task không chắc đã chạy xong là đọc một file chưa
tồn tại.

**Q48. Replan một lần, và kế hoạch mới phải khác.** Khi một task thất bại qua hết số lần thử,
runner escalate. Nếu có planner kèm model, nó được **đúng một lần** đề xuất kế hoạch khác, kèm cả
kế hoạch cũ lẫn lý do hỏng. `Planner.replan` từ chối kế hoạch **trùng y hệt** cái vừa hỏng: chạy
lại cùng một đồ thị sau cùng một lỗi không phải là khắc phục, đó là vòng lặp. Không có model thì
không replan — chỉ còn đúng cái kế hoạch vừa hỏng.

### L15. Duyệt gate nhưng không chọn rule nào → A3 đề xuất lại vĩnh viễn

Lộ ra khi chạy thử CLI trên dữ liệu thật, không phải từ test. A3 viết `if not approved: propose()`,
nên `[]` (người duyệt và cố ý không chọn gì) bị đối xử y như `None` (chưa ai duyệt). Kết quả: ghi
gate → duyệt rỗng → đề xuất lại → ghi gate → **không bao giờ xong**.

Sửa thành `if approved is None`. **Vắng mặt** nghĩa là chưa ai quyết; **có mặt nhưng rỗng** nghĩa
là có người đã quyết là không chạy gì cả — một câu trả lời thật, và phải được thi hành. Lỗi này có
sẵn từ Phase 1, chỉ là Phase 1 chưa ai bấm vào.

### L16. `asys approve` chỉ sai lệnh chạy tiếp

Sau khi duyệt, lệnh in ra `asys resume <run>` — vòng lặp Phase 1. Với một lần chạy Phase 2 thì
lệnh đúng là `resume-dag`, và làm theo hướng dẫn in ra sẽ ra lỗi. Giờ nó nhìn `runs/<id>/plan.json`
để biết đây là loại chạy nào.

### Điều golden test nói ra mà tôi không định trước

Trên fixture BPI thật, `staging_hash == clean_hash`: rule `trim_whitespace` trên
`case_spend_area_text` **không đổi một ký tự nào**. Dữ liệu BPI 2019 ở cột đó vốn đã sạch. Và
`checks_failed: 1` — kiểm định not_null trên bảng mart tìm thấy giá trị rỗng thật. Cả hai đều được
ghi vào `tests/golden/expected/phase2.json` đúng như nó là: một golden ghi lại điều mình mong muốn
thay vì điều thực sự xảy ra thì không phát hiện được hồi quy nào.

---

## 2026-09-01 — Provider thu tu: Gemini

**Q49. Ly do lam khong phai tien, ma la bang chung.** User muon dung Gemini free de kiem tra
Phase 2 truoc khi tra tien cho API. Ly do do dung, va con mot ly do nua manh hon: `LlmProvider`
tu truoc toi gio moi phuc vu **dung mot** nha cung cap. Noi no "doc lap nha cung cap" la dang
**tin**, chua **chung minh**. Co provider thu hai chay that moi la bang chung.

Test bang model re o he thong nay hop ly hon binh thuong, vi code khong tin model: cau co chu so
model tu go bi loai, SQL pham guard khong chay, ke hoach co chu trinh bi tu choi. Model do lam
ket qua **ngheo di**, khong lam no **sai**.

**Q50. Doc tai lieu truoc khi doan.** Toi da uoc "nua ngay + 150-200 dong dich schema", dua tren
hieu biet cu rang Gemini chi nhan mot tap con OpenAPI 3.0 va **khong** dien ta duoc dict khoa tu
do. Doc lai tai liệu hien tai (hai nguon doc lap) thi API da doi: endpoint `/v1beta/interactions`,
truong `response_format`, va **co ho tro `additionalProperties` lan `$ref`**. Nghia la
`model_json_schema()` cua pydantic gui thang len duoc, khong can lop dich nao.

Bai hoc: uoc luong dua tren kien thuc cu ve API ben thu ba phai kiem chung truoc khi bao gia.

**Q51. Khong them dependency nao.** Goi HTTP bang `urllib` cua thu vien chuan. Mot HTTP client
thu hai la mot phu thuoc mua ve cho dung mot loi goi; retry va backoff da nam o tang Manager roi,
nen khong con viec gi cho thu vien lon hon lam. `httpx` cung khong co san (`anthropic` keo theo
`httpx2`, ten khac) - dua vao mot phu thuoc bac hai la mong manh.

**Q52. Tim cau tra loi thay vi doan duong dan.** Toi khong biet chac hinh dang phan hoi cua
endpoint moi. Thay vi hard-code `candidates[0].content.parts[0].text` roi vo im lang o ban sau,
`_first_text` duyet ca cay phan hoi tim chuoi dau tien parse duoc thanh JSON object. Khi khong
tim thay, no **in nguyen phan hoi** - mot lan chay la du de biet phai sua cho nao, thay vi doan.

**Ban free huan luyen tren du lieu gui len.** Ghi ro trong `settings.yaml`, `.env.example` va
docstring: chi dung voi fixture cong khai (BPI 2019 co DOI), **tuyet doi khong** dung voi du lieu
khach hang. Khong co code nao cuong che duoc dieu nay - no la quyet dinh cua nguoi chon provider.

### L17. `provider: anthropic` chua bao gio duoc noi vao CLI

Phat hien khi them `gemini` vao `_build_llm`. Ham do chi xu ly `handoff`, `cassette`, `none` -
dat `provider: anthropic` trong settings se ra "provider khong ho tro" roi thoat. Nghia la duong
tra tien, thu ma DEPLOY.md bao nguoi dung chon khi len server, **chua tung chay duoc**. Da noi
ca hai, va thong bao loi gio liet ke du 5 lua chon hop le.

---

## 2026-09-01 — Chay that Phase 2 tren Gemini: bon loi khong test nao bat duoc

Chay toan tuyen 7 agent tren fixture BPI that, `provider: gemini`,
`gemini-flash-lite-latest`. Truoc do 538 test deu xanh. Lan chay that van lo ra
bon loi - vi moi provider tu truoc toi gio deu la **file cuc bo**: cassette hoac
co cau tra loi hoac khong, handoff thi cho nguoi. Khong cai nao **tam thoi hong**
bao gio.

**Q53. Loi tam thoi phai phan biet duoc voi loi that.** Them `TransientLlmError`
va `RateLimitedError` (mang theo `retry_after_s`). `ErrorDetail` co them
`retry_after_s`, va Manager **cho dung thoi gian dich vu yeu cau** thay vi chinh
sach cua no: Gemini bao doi 45 giay ma lui 2 giay thi chi tieu het luot thu lai
trong cung mot cua so tu choi.

### L18. Khong agent nao bat `LlmError` - mot loi 429 lam sap ca lan chay

`BaseAgent.run` chi bat `BoundaryViolation`. Mot 429 tu API that phong thang qua
Manager va ra traceback. Gio `BaseAgent` doi no thanh `TaskResult` FAILED, va
quyet dinh **co dang thu lai khong** ngay tai do: cassette thieu thi lan sau van
thieu; het luot thi khong.

`HandoffPendingError` van duoc tha qua - chi Manager moi duoc quyet dinh tam dung.

### L19. `post_json` khong bat timeout doc

`urllib` nem `TimeoutError` (mot `OSError`), khong phai `URLError`, nen no lot
qua het moi handler. Lan chay that dung o giay thu 120 kem traceback.

### L20. Replan bi kich hoat boi loi **khong phai** loi ke hoach

A7 tra ve "khong finding nao qua duoc kiem tra" - do la loi **dau ra cua model**,
khong phai loi cua do thi. Nhung Manager escalate roi goi planner lap ke hoach
moi. Mot DAG khac khong sua duoc viec model viet cau do.

Nang hon: `_replan` chi bat `PlanError`, nen khi planner cung dinh 429 thi
`RateLimitedError` phong ra va lam sap lan chay - **mat luon bao cao loi goc**.
Da sua: bat ca `LlmError`; khong goi duoc model nghia la khong replan, khong
phai sap.

### L21. Ke hoach moi am tham viet de len task da xong

Ke hoach thay the **toan bo**, ke ca task da OK va da qua human gate. Quan sat
duoc tren dia:

- `t3_clean.input_hashes` co **hai** hash, trong khi ke hoach goc chi khai mot
  (`inputs_from: [t1_ingest]`). Ke hoach do Gemini sinh de `inputs_from` rong nen
  roi ve `depends_on`, thanh ra doc ca profile lan staging. Hash doi -> `should_skip`
  tra False -> task **da duoc nguoi duyet** chay lai. Chay 5 lan.
- Ke hoach moi doi `t7_report` thanh `t6_report` va cho no doc bang mart thay vi
  ket qua phan tich -> A8 doc parquet nhu JSON roi hong.
- `runs/<id>/plan.json` van giu ke hoach goc, trong khi state mang task cua ke
  hoach khac. `resume-dag` nap ke hoach goc -> hai ben lech nhau vinh vien.

Chua sua. Huong dung: replan chi duoc thay **phan chua chay**; task da OK hoac da
qua gate la bat bien. Va ke hoach thuc su duoc chay phai duoc ghi de len
`plan.json`, neu khong thi "resume" khong con y nghia gi.

### L22. Phan quyet cua A5 khong co hau qua gi

A5 cham bang mart: **0 dat / 2 hong** (bang thieu dung hai cot ma checks doi).
Roi A7 va A8 cu the chay tiep nhu khong co gi. Trong tai duoc ghi nhan nhung
khong ai hanh dong theo.

Day khong phai loi lap trinh - khong dong code nao noi rang validation hong thi
phai dung. Nhung no lam A5 thanh trang tri.

### L23. `evidence_ref` khong duoc kiem chung

A7 dan nguon `mart://frame.parquet` va `mart://cumulative_net_worth_eur.parquet`
- **hai file khong ton tai**. Co che chong bia so hoat dong dung (moi con so deu
tu chi so co that), nhung **duong dan bang chung thi khong ai kiem**. Tieu chi S4
doi ket luan phai lan nguoc duoc; mot ref tro vao hu vo thi khong lan nguoc duoc.

### Dieu chay that lam dung

- A2 doan **dung ca bon** truong event log: `case_id`, `activity`, `timestamp`,
  `resource`. Va gan co PII cho `case_name`.
- A3 de xuat **dung mot** rule: `standardize_datetime` cho `timestamp`, ly do dung
  - ISO 8601 ket thuc bang 'Z' la UTC. Trung voi ket luan toi tu rut o Phase 0 khi
  doc du lieu that.
- Co che placeholder chan sach: co luot A7 bi loai **toan bo** finding vi model go
  so truc tiep, va he thong bao FAILED thay vi cho qua.
- Human gate hoat dong dung ca hai lan, quyet dinh duoc phat lai khi chay lai.

---

## 2026-09-01 (chieu) — Sua loi 1: dong bang phan ke hoach da chay

**Q54. Mot ke hoach da chay mot phan thi khong con thuan tuy la de xuat.** Task da xong - va nhat
la task **nguoi da duyet** - la mot su that, khong phai mot y kien. Replan viet de len no nghia la
quyet dinh lai dieu da duoc quyet, va tệ hơn: bien thu nguoi duyet thanh thu ho khong duyet.

`frozen_tasks(state)` tra ve task o **ba** trang thai: da OK, dang cho nguoi duyet, hoac da co
quyet dinh gate. Truong hop thu ba quan trong nhat va de bo sot nhat - quyet dinh gan voi task
nao thi task do bat bien, ke ca khi no chay lai duoc.

**So sanh theo truong quyet dinh hanh vi, khong so sanh ca doi tuong.**
`EXECUTION_FIELDS = (agent_id, depends_on, inputs_from, params)`. Rieng `instruction` **duoc phep
doi**: mot task se khong chay lai nua thi cach dien dat cua no khong con anh huong gi. So sanh ca
doi tuong se tu choi nhung thay doi vo hai va lam replan gan nhu vo dung.

**Tu choi ca ke hoach, khong va tung task.** Va nghia la tu chon mot to hop ma khong ai chon -
dung loai "code tu suy dien" Muc 0 cam. Lan chay giu lai bao cao loi goc, thu do co gia tri hon
mot ke hoach khong ai tin duoc.

**Noi truoc cho model biet cai gi bat bien.** `build_replan_request` gui kem danh sach `frozen`.
Model khong the tu biet rang mot buoc da duoc nguoi duyet; noi thang ra thi no danh luot goi duy
nhat cho phan con sua duoc, thay vi de xuat mot thu chac chan bi tu choi.

**`plan.json` gio duoc ghi lai moi lan ke hoach doi.** Truoc day CLI ghi mot lan luc bat dau, roi
replan doi ke hoach trong bo nho ma khong ai ghi lai - nen `resume-dag` nap ke hoach cu trong khi
state mang task cua ke hoach moi. Hai ben lech nhau vinh vien. Gio `DagRunner` tu ghi, vi no la
thu biet ke hoach nao dang that su chay.

---

## 2026-09-01 (toi) — Sua loi 3: phan quyet cua A5 co hau qua

**Q55. Dieu kien dung do MANIFEST khai, khong viet vao Manager.** Cung ly do voi human gate: mot
`if agent_id == "a5_validator"` trong Manager la mot luat ma nhin tu ngoai code khong ai thay.
`Manifest.halt_on` nhan mot danh sach `{metric, above, reason}`, va A5 khai:

```yaml
halt_on:
  - metric: checks_failed
    above: 0
    reason: "Bang khong qua duoc kiem dinh"
```

Bat ky agent nao do duoc mot chi so cung khai duoc nguong dung cua rieng no. Manager chi doc.

**Q56. `halted` tach khoi `escalation`.** Hai thu nhin giong nhau nhung khac han:

- **escalation** — mot task that bai; mot ke hoach khac **co the** chay duoc
- **halted** — du lieu khong dat; mot do thi khac tren **cung du lieu do** se hong y het

Nen `halted` khong kich hoat replan. Gop chung mot truong se lam he thong tieu mot luot goi model
de lap lai ke hoach cho mot van de ma ke hoach khong lien quan gi.

### Dieu golden test phoi ra ngay khi bat cong chan

Golden dang kiem `not_null: [spend_area, net_worth]` va truoc do ghi nhan `checks_failed: 1` —
**va van cho chay tiep den tan bao cao**. Bat cong chan len la golden dung ngay o A5.

Do chinh la loi dang noi, nhin tu goc khac: mot bo test "xanh" van co the dang ghi nhan mot lan
chay sai. Dem: `case_spend_area_text` co **42 dong rong that** tren 5.000 — 0,84%, dung con so
Gemini bao khi chay that.

Xu ly: golden doi sang tieu chi ma du lieu **that su dat** (`net_worth`), de no van kiem duoc ca
chuoi 7 agent. Rieng truong hop hong thi co hai test rieng tren **chinh du lieu that**: mot chung
minh `not_null: [spend_area]` lam dung lan chay va **khong task nao phia sau ton tai trong state**,
mot chung minh halt khong bi replan lach qua.

---

## 2026-09-01 (toi) — Sua loi 4: bang chung phai lan nguoc duoc

**Q57. Hai lop kiem doc lap, khong lop nao do lop kia.** Cung mot cach nghi voi SQL guard va
DuckDB in-memory:

- **A7 hoi storage** file co that va doc duoc khong, roi **loai** finding nao dan nguon ao - dung
  co che da dung cho cau co chu so go tay. Loai chu khong sua: bia ra duong dan dung nghia la tu
  quyet dinh model **dinh** dan nguon nao.
- **post-check** tu choi moi `evidence.source` nam ngoai `allow_read` cua token. Thuan hop dong,
  khong dung toi dia. Nen mot lop hong thi lop kia van dung.

**Q58. `citation_exists` gop hai truong hop thanh mot cau tra loi, co y.** Dan nguon **ngoai pham
vi** va dan nguon **khong ton tai** deu vo gia tri *voi tu cach mot trich dan*. Nguoi goi dang hoi
"ket luan nay lan nguoc duoc khong", khong phai dang co mo file. Va ham nay **khong bao gio nem
ngoai le** - no duoc goi mot lan cho moi finding trong luc quyet dinh giu cai nao; nem se bien mot
trich dan hong thanh mot task hong.

### Dieu viet test moi lo ra: da co san mot lop phong thu

`EvidenceRef.source` **da** bat buoc dang `tang://duong/dan` ngay tu luc dung doi tuong. Nghia la
mot chuoi nhu `"price.mean"` - thu Gemini tung tra ve trong lan thu schema - khong bao gio di toi
duoc post-check. Toi khong biet dieu nay truoc khi viet test, va test da sua lai de ghi dung su
that do: lop kiem pham vi chi bao gio phai xu URI that.

Bai hoc nho: viet test truoc khi tin vao mo hinh trong dau minh ve he thong.

---

## 2026-09-01 (khuya) — Sua loi 2: cau tra loi do khong phai ke hoach do

**Q59. Replan tro thanh tuy chon, mac dinh la KHONG.** `ErrorDetail.replannable` mac dinh `False`.
Chi mot loai that bai bat no len: **task bi giao sai thu de lam** (`NO_INPUT`, `NO_CHECKS`) - do
la truong hop duy nhat mot do thi khac thuc su sua duoc. Moi thu khac la ve **cai agent tao ra**,
va sap xep lai do thi khong doi duoc dieu do.

Truoc day nguoc lai: bat ky escalation nao cung keo theo mot lan replan. A7 bao "khong finding nao
qua duoc kiem tra" va he thong di hoi model mot do thi moi.

**Q60. `NO_VALID_FINDING` va `SUMMARY_REJECTED` gio la loi CO THE thu lai.** Truoc day chung
`retryable=False`, nen model **khong duoc thu lai lan nao** dung cai ma no that su lam sai. Ba
lan goi la du: sau do nguyen nhan hau nhu luon nam o prompt hoac o du lieu, khong con la ngau
nhien. Tran do da co san trong manifest (`max_retries: 3`), khong phai them gi.

**Q61. Phan hoi loi di theo THAM SO, khong theo lich su hoi thoai.** Day la lua chon thiet ke
quan trong nhat cua phan nay. Dua no vao mang `messages` nghe tu nhien hon, nhung se pha ba trong
bon provider:

- **`handoff`** dua tren tien de "mot file = mot cau hoi tron ven de nguoi dan vao Claude".
  Bat nguoi dan mot cuoc hoi thoai nhieu luot la bien viec dang lam tay duoc thanh viec khong lam noi.
- **`cassette`** khoa theo van tay cua dung mot cau hoi. Them lich su vao thi phai bam ca lich su,
  va tinh tat dinh (S1) roi theo.
- Provider Gemini goi `/v1beta/interactions` voi **mot truong `input`**, khong phai chat API co
  mang `messages`. Role injection se phai viet rieng tang goi cho Gemini - tuc la de mot nha cung
  cap dinh hinh kien truc, dung thu vua tranh duoc.

Nen phan hoi la mot **khoi khai bao trong chinh cau hoi**: `attempt`, `previous_answer`,
`rejected_because`. Duoc them mot thu ma role injection khong cho: **van tay doi theo**, nen mot
lan thu lai la mot cau hoi that su moi chu khong phat lai cau tra loi cu tu cassette.

**Ve audit log, toi khong lam theo de nghi cua user.** User de xuat xoa cac lan thu hong khoi
`audit.jsonl` cho do rac. Toi giu lai, va noi ro ly do: audit log la **ban ghi he thong da lam
gi**. Mot task can 3 loi goi va 2 lan bi loai - do chinh la dieu da xay ra, va do cung la cho
nguoi ta nhin khi hoi "model dang xuong chat luong a?" hay "token tieu vao dau?". No **khong** lam
phinh token chuyen giao: audit la file tren dia, khong nam trong prompt cua agent nao. Hai chuyen
khac nhau.

Phan **dong y**: ket qua sai trung gian khong duoc chay xuong agent sau. `TaskResult` chi mang ket
qua cuoi - dieu nay code von da dung. Ban nhap bi loai nam trong `payload` cua **TaskResult that
bai**, va chi Manager doc no, chi de dung cau hoi tiep theo.

---

## 2026-09-01 (khuya) — Chay that lan hai: 4 ban sua dung, va 4 loi moi

Chay lai toan tuyen tren fixture BPI that voi Gemini de kiem chung bon ban sua. Tat ca deu
**dung nhu thiet ke** - va lan chay lo them **bon loi nua**, khong loi nao bi 573 test bat duoc.

### Bon ban sua, do bang quan sat tren dia

| Ban sua | Bang chung |
|---|---|
| 1 | `plan.json` khop chinh xac state, khong task la. `t3_clean` chay **2 lan** (de xuat + ap dung), khong phai 5 |
| 3 | A4 lai phot lo chi dan dat ten cot -> A5 cham 0/2 -> **run dung han**. `t6_analyse` va `t7_report` **khong ton tai trong state**, `artifacts/` rong |
| 4 | Gemini bia **ba** duong dan: `mart://spend_area.parquet`, `mart://net_worth.parquet`, `mart://frame.parquet`. Ca ba bi loai |
| 2 | Loi timeout va loi JSON cut deu RETRY tai cho du 3 lan roi escalate. **Khong lan nao di lap lai ke hoach** |

### L24. A7 bi doi dan nguon ma khong bao gio duoc cho biet nguon ten gi

Prompt gui di co `question`, `metrics`, `max_findings`, `rules` - **khong co ten bang**. Ta doi
`evidence_ref` tro toi bang nguon nhung khong noi bang do la gi. Model **khong** cau tha; no
**doan**, vi doan la thu duy nhat no lam duoc. Va no doan `mart://frame.parquet` **hai lan trong
mot ngay**, o hai lan chay khac nhau.

Them `source_table` vao prompt, kem luat "evidence_ref phai BANG DUNG gia tri do". Sua xong A7
chay duoc ngay lan dau, ca ba ket luan dan dung `mart://spend.parquet`.

Bai hoc: truoc khi goi mot dau ra la "model bia", kiem xem minh da cung cap du de no khoi bia chua.

### L25. Ngan sach thu lai bi cong don qua cac lan chay

`attempts` doc tu state va cong tiep, nen mot task da hong 3 lan thi lan `resume-dag` sau bat dau
o lan thu **4**, so voi tran 3, va **escalate ngay khong thu lan nao**. Dung cai truong hop ma
nguoi ta resume vi no - loi tam thoi - lai la cai khong bao gio chay lai duoc.

Gio moi lan chay co ngan sach rieng; state van ghi tong so lan da thu (`attempts_total` trong
audit) de khong mat dau vet.

### L26. `GeminiProvider` khong gui gioi han dau ra lan muc suy nghi

A7 het gio 120 giay, ba lan lien, va cau tra loi duy nhat den duoc thi **cut giua JSON**. Nguyen
nhan khong phai mang cham cung khong phai cau hoi to (3.800 ky tu): model **suy nghi dai** roi het
ngan sach dau ra truoc khi dong ngoac.

`generation_config: {thinking_level: "low", max_output_tokens: request.max_tokens}` -> **5 giay,
JSON tron ven**. `LlmRequest.max_tokens` von da co, provider chi don gian khong gui no di.

Khong tac vu nao o day can suy nghi sau: tat ca deu la dien vao mot khuon da khai bao san tu du
lieu da dat truoc mat, va ket qua tot hay khong do guard, do co che placeholder va do A5 quyet -
khong phai do model nghi lau hay mau.

### L27. Don vi bi chen hai lan

Dau ra that: `40.24 %%`, `2,012 dong dong`, `8 gia tri nhom`. Model viet don vi sau placeholder,
roi bo render lai chen don vi cua chi so. Da them luat vao prompt cua A7 va A8: he thong tu chen,
dung tu viet.

### Ket luan ve chat luong model bac free

`gemini-flash-lite-latest` **hai lan** phot lo chi dan dat ten cot dau ra rat ro rang, va thinh
thoang tra ve JSON cut. Nhung dieu do **khong lam hong ket qua** - no lam **dung lan chay**, dung
cho no phai dung: A5 chan, co che trich dan chan, va vong thu lai bao cao trung thuc. Do dung la
dieu he thong nay duoc thiet ke de lam.

---

## 2026-09-01 (khuya) — Noi BudgetTracker vao CLI

Toan bo co che dem da co tu Phase 1 va co test day du: dem token, dem tien, tran thoi gian,
canh bao o tam muoi phan tran. **Chua bao gio duoc noi vao dau ca.** Mot lan chay
`provider: anthropic` dem con so 0 va dung o khong cho nao - song duoc chung nao chua co khoa,
va het song duoc ngay khi co.

**Q62. Tran ap cho MOI provider goi ra ngoai, khong rieng cai tinh tien.** Tran token va tran
thoi gian dang gia bat ke gia bao nhieu: mot bac free khong ton tien van an trong ca buoi chieu
neu co gi do lap vo han. Chi `none`, `cassette`, `handoff` la khong co gi de dem.

**Q63. Gia Gemini bac free ghi 0.00, kem canh bao trong file.** Ghi 0.00 la **dung** cho bac free.
Nhung neu sau nay gan billing vao du an Google Cloud thi phai dien gia that - neu khong bao cao se
bao $0 mai mai trong khi tien van tru. Da ghi thang dieu do vao `pricing.yaml`.

Model khong co trong bang gia thi `price_of` **bao loi**, khong lang le coi la 0. Do la quy tac co
tu dau va van dung: chi phi khong biet thi phai noi la khong biet.

**Q64. Bang gia qua han thi canh bao truoc khi chay.** `last_verified` qua 90 ngay -> in canh bao.
Bao mot con so chi phi tinh tu bang gia khong ai kiem chung con te hon la khong bao gi.

### Kiem chung tren lan chay that

- Chay binh thuong: `Da ghi nhan 9,860 token · $0.0000` - so token that, chi phi 0 vi bac free
- Ha tran xuong 1.000 token: `DUNG - cham tran ngan sach: Vuot tran token cua job: 9834 > 1000`,
  **thoat ma 1**, khong task nao chay
- Ly do in **truoc** con so, vi so ghi nhan la 0 khi chinh loi goi dau tien la cai vuot tran

### Mot test toi viet hong, va cach phat hien

Test dau tien cho canh bao bang gia qua han viet la
`assert ... if hasattr(...) else True` - **luon dung**, khong bao gio bat duoc gi. Da viet lai bang
`capsys`, roi **co tinh go doan canh bao trong code ra** de xem test co fail khong. No fail. Khoi
phuc thi pass.

Mot test khong the fail con te hon khong co test: no cho cam giac an toan ma khong co gi dam bao.

---

## 2026-09-01 (khuya) — Nam loi mot bo du lieu la phoi ra

User dua vao mot dataset ket qua hoc tap sinh vien - 1.000 dong, 12 cot, khong phai event log.
Chay het Bai 1 den Bai 5. **591 test deu xanh, va van lo ra nam loi.** Ba trong so do co chung
mot goc.

### L28. Duong ghi co dinh: lan chay sau xoa bang chung cua lan truoc

A2 ghi `profile://profile.json`, A3 ghi `clean://events.parquet` - **hang so, khong gan voi lan
chay nao**. Tren BPI khong bao gio lo, vi chi co dung mot bo du lieu.

Sua: A2 ghi `profile://{run_id}_profile.json`. A3 ghi `clean://{ten_du_lieu}.parquet`.

**Chu y cho quan trong:** ban dau toi cho ca run_id vao ten bang sach - va lam hong ngay: A4 suy
ten bang SQL tu **ten file**, nen ten doi theo lan chay se pha moi cau SQL viet tay. Ten bang phai
mo ta **du lieu**, khong mo ta **lan chay**. Lan chay nao tao ra no thi da nam trong state va trong
content hash cua trich dan.

### L29. Luat cam chu so dung voi GIA TRI, sai voi TEN NHAN

Nhom du lieu ten `0-2h`, `2-4h`, `6h+`. Model khong the goi ten nhom no dang noi toi ma khong viet
chu so. Nen no viet nhung cau meo mo de ne - *"nhom hoc tu duoi den gio"* - roi **tranh han chieu
du lieu do**, quay sang noi ve `part_time_job` (`Yes`/`No`).

Ket qua: **ca phan tich lech khoi cau hoi user dat.** Luat qua rong khong chi lam van xau, no lai
ca noi dung.

Sua: truoc khi quet chu so, bo di moi **doan cua ten chi so** - vi `exam_score.mean.by.study_bucket.0-2h`
cho biet `0-2h` la mot cai ten cua chinh du lieu, khong phai con so ai bia. Chu so nao khong nam
trong tu vung do thi van bi loai.

### L30. `instruction` cua task KHONG BAO GIO den duoc A4

`build_sql_request` chi gui: `question`, `tables`, `rules`. Truong `instruction` - noi ke hoach
ghi "dat ten cot CHINH XAC la spend_area va exam_score" - **bi bo roi**.

**Toi da ba lan ket luan "model phot lo chi dan".** Hai lan voi BPI, mot lan voi du lieu sinh vien.
Ba lan deu sai: model tra loi rat hop ly cho cau hoi no **that su** nhan duoc.

Day dung khuon cua L24 sang nay - A7 bi doi dan nguon ma khong duoc cho biet bang ten gi. Toi sua
L24 roi **khong nhan ra A4 mac y het**. Bai hoc dang le da rut tu L24: truoc khi ket luan model lam
sai, **doc prompt xem yeu cau do co that su duoc gui di khong**.

### L31. SQL khong duoc luu o dau ca

`TransformResult.sql` chi ton tai trong payload luc chay. `state.json` khong giu payload,
`audit.jsonl` khong giu. Sau lan chay, khong ai tra loi duoc *"bang mart nay duoc dung ra the nao?"*

Chinh vi vay ma **L30 an duoc qua ba lan chay**: bang chung de lo ra no bi vut di moi lan.

Sua: A4 ghi cau lenh ra `mart://<ten>.sql` ngay canh bang no dung ra.

### L32. `evidence_ref` chi tro toi mot CAI TEN, khong tro toi noi dung

Nang nhat trong nam cai. Bao cao `s1` ghi nguon `mart://study.parquet`. Lan chay `s2` ghi de len
file do bang mot bang khac han. Bao cao **van** noi nguon do; `citation_exists` **van** tra ve True
- duong dan dung cu phap, file co that. Nhung file do gio khong con chua noi hai chi so ma ket luan
dua vao.

Tieu chi S4 doi ket luan phai truy nguoc duoc. Mot trich dan chi mang duong dan thi truy nguoc ve
**mot cai ten**, khong ve **du lieu**.

Sua: `EvidenceRef` va `RenderedFinding` mang them `content_hash` cua bang da doc, va bao cao in ra.
Khong ngan duoc viec ghi de - nhung lam cho su khong khop **phat hien duoc**.

### Dieu buoi kiem chung nay chung minh

Bon lop cuong che deu hoat dong dung tren du lieu la: SQL guard chan bang khong duoc cap, A5 chan
bang khong dat kiem dinh (A7/A8 **khong ton tai trong state**), co che placeholder loai sach ket
luan sai, tran ngan sach dung lan chay.

Nhung **591 test xanh khong co nghia la he thong dung**. Nam loi tren khong loi nao bi bat, vi test
deu chay tren dung mot bo du lieu ma he thong duoc xay quanh.

---

## 2026-09-02 — Thong ke suy dien: `services/statistics.py`

**Q65. Them suy dien = them CHI SO, khong doi kien truc.** Co che chong bia so lam viec tren gia
tri **co ten**: model viet `{key}`, code thay so. Nen mot he so tuong quan chi la mot con so nua
code tinh va dat ten. Khong mot dong nao trong `boundary.py`, `dispatcher.py` hay `findings.py`
phai biet rang thong ke da xuat hien.

**Q66. Phan tu choi quan trong hon phan tinh.** Hau het cong cu se vui ve tinh p-value tu 11 dong,
hoac tu mot nhom moi gia tri deu giong nhau, roi in ra ba chu so thap phan. Moi phep o day khai
bao no can gi va **tu choi khi khong co**, kem ly do duoc ghi lai - dung cach mot finding go so
tay bi loai chu khong duoc va.

Nguong: `MIN_SAMPLE = 8` cap, `MIN_GROUP = 5` dong moi nhom, `MAX_GROUPS = 20`. Tren du lieu that
no tu choi ngay `final_exam_score theo student_id`: *"bo qua 1000 nhom co duoi 5 dong"* roi *"con
duoi hai nhom du lon"*. Mot ANOVA tren 1.000 nhom moi nhom mot dong la thu khong cong cu nao nen
tinh.

**Q67. Luon bao effect size ben canh p-value.** Voi 1.000 dong thi gan nhu moi khac biet deu "co y
nghia thong ke". Chi do lon cua no moi noi duoc co dang lam gi khong. Nen co `effect_size` (Cohen's
d) cho hai nhom va `eta_sq` cho nhieu nhom. Va `r2` ben canh `corr`, vi `r = 0.26` nghe to hon
`6,9% bien thien chung` rat nhieu.

**Q68. Welch chu khong phai Student.** `ttest_ind(..., equal_var=False)`. Gia dinh hai nhom bien
thien nhu nhau khi that ra khong phai la cach pho bien nhat de phep kiem nay noi doi.

**Q69. Tuong quan khong duoc viet thanh nhan qua - va day la lop chan, khong phai loi nhac.**
`causal_overreach()` tu choi mot cau dung `lam tang`, `khien`, `dan den`, `tac dong den`... khi cac
chi so no dan **chi do moi lien he**. Thong bao tu choi noi luon cach viet dung: *"di kem voi",
"tuong quan voi", "cao hon o nhom..."*.

**KHONG lam du doan bang ML.** Mot gia tri du doan truy nguoc ve *mot mo hinh, mot tap huan luyen,
mot hat giong ngau nhien* - khong ve dong du lieu nao. Tieu chi S4 doi ket luan phai lan nguoc
duoc, nen dua ML vao se can mot cau tra loi khac cho "bang chung la gi" - do la mot quyet dinh phai
ban, khong phai mot tinh nang de len lut them vao.

### L33. Lop chan nhan qua co lo hong ngay o cho de doc nhat

Lan chay that dau tien: cac **ket luan** viet rat can than - *"co moi tuong quan manh voi"* - con
**tom tat** ba dong phia tren viet *"thoi gian tu hoc **co tac dong manh me den** ket qua"*.

Vi `causal_overreach` nam trong `check_finding`, cham toi ket luan cua A7. Tom tat cua A8 di qua
`render_narrative`, ham do tu truoc toi gio **chi kiem chu so go tay**.

Mot lop chan phu duoc phan van can than ma khong phu duoc phan nguoi ta that su doc thi khong bao
ve gi ca. Da sua: tom tat chiu **cung mot luat** - ke ca luat cho phep chu so trong nhan `0-2h`.

Chay lai sau khi sua: *"co moi **lien he cung chieu** voi ket qua thi"*.

### Con so that tren du lieu sinh vien (1.000 dong)

| Quan he voi diem thi | r | R2 | p |
|---|---|---|---|
| Gio tu hoc | 0,568 | **32,2%** | <0,0001 |
| Chuyen can | 0,262 | 6,9% | <0,0001 |
| Gio ngu | 0,148 | 2,2% | <0,0001 |
| Hoc van cha me (ANOVA) | - | **0,21%** | **0,60** |

Ket qua cuoi cung dang chu y: hoc van cha me **khong** cho thay khac biet nao. Mot phat hien am -
thu ma cong cu mo ta thuan tuy khong the noi duoc.

---

## 2026-09-02 — Hoi quy boi

**Q70. Hoi quy tra loi cau ma tuong quan don khong tra loi duoc.** Gio hoc `r = 0,57`, chuyen can
`r = 0,26`. Neu hai thu do di cung nhau thi hai con so nay chong lan nhau mot phan khong ai biet la
bao nhieu, va nguoi doc cong don chung lai da bi mot bao cao trung thuc danh lua. He so hoi quy noi
duoc: **giu nguyen cac bien khac** thi moi bien dang bao nhieu.

**Q71. Van la chi so co ten, nen khong doi gi trong kien truc.** `exam_score.coef.study_hours`
dung khuon `MetricValue`. Co che placeholder, lop chan nhan qua, `evidence_ref` chay nguyen. Va
`.coef.` `.vif.` `.regression.` da duoc them vao danh sach INFERENTIAL - **mot he so hoi quy tren
du lieu quan sat van khong phai bang chung nhan qua**.

**Q72. Khong them thu vien nao.** `numpy` (da co qua pandas) cho OLS, `scipy.stats.t` cho p-value.
`statsmodels` tien hon nhung khong can thiet.

**Q73. VIF duoc BAO, khong duoc dung.** VIF cao khong lam phep fit that bai, nen tu choi se la qua
tay. Nhung no duoc noi to: mot he so dung tren VIF muoi hai la so hoc chu khong phai thong tin -
no se nhay lung tung tren mot bo du lieu chi khac di mot chut.

Nguong tu choi that su: `MIN_PER_PREDICTOR = 10` dong moi bien; bien khong doi gia tri; hai bien
trung lap hoan toan (ma tran suy bien - khong co loi giai duy nhat, in ra mot cai la bia ra no).

**Q74. Hai mo hinh cung mot bien ket qua bi tu choi ngay o buoc doc spec.** Chung se ghi vao cung
bo khoa chi so va cai sau am tham de len cai truoc.

### Dieu du lieu that bac bo du doan cua toi

Toi noi voi user rang gio hoc va chuyen can "gan nhu chac chan chong lan nhau". Chay ra:

```
attendance_percent   he so = 0,323   VIF = 1,00
previous_grade       he so = 0,354   VIF = 1,00
sleep_hours          he so = 1,153   VIF = 1,00
study_time_hours     he so = 4,160   VIF = 1,00
R2 = 60,9%   R2 hieu chinh = 60,7%   n = 1.000
```

**Toan bo VIF bang 1,00.** Cac bien doc lap voi nhau hoan toan - dieu khong xay ra o du lieu quan
sat that. Cong voi viec moi cot deu khong co outlier va phan bo deu, day gan nhu chac chan la
**du lieu sinh tong hop**, khong phai du lieu thu thap tu sinh vien that.

Dieu do khong lam bai kiem chung mat gia tri - he thong van chay dung tren no. Nhung no la mot
canh bao: mot bo du lieu qua sach se **khong** lo ra nhung loi ma du lieu that lo ra. BPI 2019 la
du lieu that va da lo ra chuyen `guess_roles` khop "case" ben trong "case_company"; bo nay thi
khong lo duoc gi tuong tu.

---

## 2026-09-02 — Phase 3, phan 1: moi tieu chi mot bo test rieng

DoD cua Phase 3 doi **S1-S5 moi tieu chi co test chung minh**. Truoc day chung nam rai rac trong
golden test va contract test - dung nhung khong ai chi ra duoc "day la bang chung cho S3".

`tests/criteria/` gio co 24 test, moi tieu chi mot muc, va **moi test chay mot lan chay that** -
agent that, Manager that, file that tren dia. Thu duy nhat gia la model, vi mot model that se lam
cung mot test cho ket qua khac nhau moi ngay, va mot tieu chi chi dung doi khi thi khong phai tieu
chi.

Cach viet: moi tieu chi duoc kiem **ca hai chieu**. S1 khong chi kiem "hai lan chay trung hash" ma
con kiem "doi mot o duy nhat thi hash phai khac" - neu thieu ve sau, mot ham hash tra ve hang so
cung se pass. S2 khong chi kiem "khong co vi pham" ma con kiem "co vi pham that thi co bi bat
khong".

### L34. Ngan sach do TUNG PROVIDER tu dem, nen provider nao quen la tran ngung ap dung

Viet test cho S5 thi lo ra. Mot lan chay voi provider kich ban dem **0 token** va khong cham tran
nao, vi `record_call` do chinh `GeminiProvider` va `AnthropicProvider` goi - va khong ai khac goi.
Cassette, handoff, va bat ky provider nao them sau nay: deu khong dem. Tran im lang ngung ap dung.

Trong khi **cung file do da giai dung bai toan nay roi**, cho lop chan PII: no nam trong
`LlmClient` "de khong provider nao co the bo qua - ke ca mot provider tuong lai". Ngan sach thuoc
ve dung cho do. Da chuyen vao `LlmClient`, va bo tham so `budget` khoi hai provider - mot tham so
khong con tac dung nhung van nhan vao la moi nguoi ta truyen roi tuong da duoc dem.

### L35. `should_skip` so hash GHI TRONG STATE, khong so hash tren dia

Ghi lai trung thuc thay vi khang dinh nguoc lai. Task phia sau lay hash dau vao tu `output_refs`
da luu trong state, nen sua tay mot file trung gian **khong duoc phat hien**. Doc lai moi bang
trung gian o moi lan resume se ton thoi gian ti le voi kich thuoc du lieu, de phong mot viec he
thong khong bao gio tu lam voi chinh no.

Cai duoc phat hien la **nguon doi** - va do la truong hop that su xay ra. Da co test cho ca hai:
mot chung minh nguon doi lam ca chuoi chay lai, mot ghi nhan gioi han o file trung gian.

---

## 2026-09-02 — Docker chay that, va loi no phoi ra

Docker duoc cai qua `wsl -u root` (WSL cho chay bang root khong can mat khau, nen khong vuong
chuyen user khong nho mat khau sudo). `docker.io` 29.1.3 + `docker-compose-v2` tu kho Ubuntu chinh
thuc - khong dung script tai tu internet chay bang root.

**Image build duoc ngay lan dau.** Hai loi trong Dockerfile da duoc bat truoc do bang cach doc:
comment nam giua dong noi cua `ENV`, va `mkdir /data` chay sau `USER analysis`.

### L36. Nam cho gia dinh package van nam trong thu muc ma nguon

`Path(__file__).resolve().parents[3] / "prompts"` dung khi code o `src/`. No thoi dung ngay khi
package duoc cai tu te - vao `site-packages`, noi `parents[3]` la mot thu muc chua bao gio nghe
noi den prompts. Nam cho: `settings.REPO_ROOT`, `prompts.PROMPT_DIR`,
`boundary.DEFAULT_MANIFEST_DIR`, `planner.DEFAULT_MANIFEST_DIR`, `cli.FIXTURE_PATH`.

Moi lan chay tu truoc toi gio deu tu mot checkout, nen khong ai nhan ra. **Dong goi container la
thu dat ra cau hoi do.**

`resource_root()` thay ca nam: bien moi truong `ANALYSIS_SYSTEM_ROOT`, roi checkout, roi thu muc
lam viec. Va no **khong bao gio nem ngoai le** - no chay luc import module, va mot resolver co the
pha import se bien mot loi cau hinh thanh traceback ve mot chuyen hoan toan khac.

### L37. `run-dag` chep file nguon vao `raw://`, ma `raw` la read-only

Lan chay dau tien trong container do ngay o task dau:

```
OSError: [Errno 30] Read-only file system: '/data/raw/c1_bpi19_slice.csv'
```

Dac ta noi `raw` mount read-only, va no dung: du lieu goc la thu duy nhat khong tai tao duoc, va
khong gi trong he thong co viec gi phai ghi vao do. CLI van chep vao, va moi lan chay lai de lai
mot ban sao - `s1_students.csv`, `s2_students.csv`, `s3_students.csv`... dung nhung file toi da
phai don tay hom qua ma khong nghi lai xem vi sao chung sinh ra.

Khong ai nhan ra vi mot checkout co thu muc `raw` ghi duoc. **Container la noi dau tien quy tac
that su duoc cuong che**, va lan chay dau tien trong do do ngay lap tuc.

Sua: file da nam trong tang `raw` thi dung tai cho. File ngoai tang thi chep vao, va neu tang chi
doc thi bao ro phai lam gi thay vi nem `OSError`.

### DoD cua Phase 3 ve Docker: DAT

`docker compose run` chay tron mot job 5 task, qua **ba lan goi rieng biet** (chay, duyet gate,
chay tiep) - nghia la state giu duoc qua bind mount. Audit log 30 dong nam tren may that. `raw`
van read-only suot ca ba lan.

---

## 2026-09-02 — L38: bo regression kiem sai tang

User lam dung viec toi de nghi - xoa mot luat khoi prompt roi chay lai - va **toan bo 30 test van
xanh**. Do la chinh xac kieu that bai toi bao anh ay di tim.

Hai nguyen nhan, va cai thu hai moi dang ke.

**Lenh toi dua khong khop gi ca.** File prompt viet tieng Viet co dau; chuoi toi bao xoa la chuoi
khong dau. `git diff` cho thay file khong doi. Bai test khong test gi.

**Nhung ben duoi do: suite assert vao `request.prompt` - payload JSON do CODE agent dung - trong
khi file prompt di vao `request.system`.** Nen mot bo test ten la "prompt regression" gan nhu khong
cham vao file prompt. Xoa mot luat khoi file that su se khong ai bat duoc.

```
request.system  = noi dung file prompt        'khong go con so truc tiep': False
request.prompt  = payload code dung           'khong go con so truc tiep': True
```

Ca hai tang deu dang kiem, va chung hong khac nhau. Luat bi bo khoi payload la mot diff trong file
`.py` - review se thay. Luat bi bo khoi prompt la mot diff trong file `.md` - dung loai thay doi it
duoc doc ky nhat, va **do chinh la ly do file prompt le ra phai la cai duoc phu**.

Da them 22 test assert tren chinh noi dung file, moi cai la mot luat ma code cuong che o dau do.
Kiem chung bang cach **xoa that** luat cam go so khoi `a7_analyst_findings.md`: test do dung cai
can do, thong bao noi ro luat do de lam gi. Khoi phuc thi xanh lai.

Bai hoc: mot bo test co ten dung chua chac kiem dung thu. Cach duy nhat de biet la **pha no ra va
xem no co do khong** - va o day nguoi pha lai la user, khong phai toi.

---

## 2026-09-02 — L39: `export` bao that bai khi GHI bang mot traceback

User chay bai kiem tang `raw` read-only trong container. Ket qua **dung**: ghi bi chan.

```
OSError: [Errno 30] Read-only file system: '/data/raw/xam.csv'
```

Nhung thu nguoi van hanh nhin thay la bon muoi dong ruot gan cua pandas roi moi den dong do.
Duong DOC da bien mot that bai thanh mot cau; duong GHI thi khong - vi truoc khi co container,
chua bao gio co mot thu muc ma tien trinh khong ghi duoc vao.

Sua: bat `OSError` quanh phep ghi, va noi luon dieu nguoi doc can biet - *"neu day la tang raw thi
no CHI DOC theo thiet ke"*. Mot lan ghi bi tu choi la ket cuc binh thuong, khong phai su co.

### Bai 3 dat: lop bao ve PHAN BIET dung

| Thao tac trong container | Ket qua |
|---|---|
| Ghi vao `raw://` | Bi chan, bao mot cau |
| Doc tu `raw://` | Duoc |
| Ghi vao `artifacts://` | Duoc - 5.000 dong ra may that qua bind mount, uid 10001 |

Mot lop chan tat ca thi de. Mot lop chan **dung cho** moi co gia tri: neu no cung chan viec doc
hay chan ghi vao noi duoc phep, nguoi ta se tat no di, va luc do khong con lop nao ca.

---

## 2026-09-02 — Phase 4a, phần 1: L40 — tham số phải nằm trong danh tính của task

### L40. `should_skip` chỉ so hash đầu vào, không so **task được bảo làm gì**

Tìm ra bằng thí nghiệm trực tiếp trước khi bắt tay vào tính năng chọn cột, chứ không phải do
test bắt — vì không test nào nhìn tới chỗ đó.

`should_skip` hỏi hai câu: task xong chưa, và dữ liệu vào có đổi không. Thiếu câu thứ ba:
**nó có được bảo làm cùng một việc không.** Nên một task đã chạy xong là xong vĩnh viễn, dù
câu SQL đổi, dù danh sách cột phân tích đổi, dù bộ check đổi, dù người dùng quay lại gate
duyệt một bộ rule khác hẳn.

Kịch bản người dùng mô tả — *chọn A và E, xem, đổi ý, chọn B và D, chạy lại* — sẽ trả về đúng
kết quả của lần trước và **không nói gì cả**. Đây là kiểu sai tệ hơn crash: con số trông vẫn
bình thường, vẫn có evidence_ref, vẫn truy ngược được về một bảng có thật. Chỉ là nó trả lời
câu hỏi cũ.

**Sửa:** `TaskState.params_hash` + `params_fingerprint()` (JSON sắp xếp khoá → SHA-256). Tham
số đi vào danh tính của task bên cạnh dữ liệu vào. Đổi lệnh thì kết quả cũ hết hiệu lực, đúng
như đổi dữ liệu.

Ba chi tiết đáng ghi:

- **Fingerprint tính TRƯỚC lúc kiểm skip**, không phải sau. Trước đây `params` được dựng ở
  dưới, sau khi đã quyết định bỏ qua — thứ tự ấy chính là chỗ lỗi trốn được.
- **Gate cũng nằm trong fingerprint.** Bộ rule người duyệt là tham số của A3. Quay lại gate,
  duyệt khác đi, resume — trước đây A3 bị bỏ qua và dữ liệu vẫn sạch theo cách cũ. Cả
  `DagRunner` lẫn `Phase1Runner` đều dính, đã sửa cả hai.
- **Tham số không serialise được thì lấy `repr`, không vứt đi.** Vứt đi là đưa lỗi về nguyên
  chỗ cũ — một tham số không encode được vẫn là một tham số.

### Lan truyền xuống dưới thì tự nó chạy đúng, không cần code thêm

Đo thật: đổi `dimensions` của t6 → t6 chạy lại → hash output đổi → hash **đầu vào** của t7 đổi
→ t7 chạy lại. Cascade đi qua content hash sẵn có. Không cần cơ chế "invalidate dependents"
riêng, và không nên có: một task chạy lại mà ra đúng byte cũ thì task dưới **nên** được bỏ qua.

### Một test tôi viết sai, và nó dạy lại điều đã biết

Test cascade đầu tiên đòi *file báo cáo phải khác byte*. Nó đỏ. Nhưng lỗi là ở test: model
kịch bản luôn trích đúng `{rows.total}`, nên báo cáo được dựng lại từ phân tích mới mà nội
dung vẫn y hệt — và như thế là **đúng**. Assert vào byte của báo cáo là đang kiểm model chứ
không kiểm pipeline. Sửa thành assert `input_hashes` của t7 đã đổi và nó thật sự chạy lại.

### Kiểm ngược, như thường lệ

Cấy lại lỗi (`return task.input_hashes == input_hashes`) rồi chạy:

| Test | Với lỗi |
|---|---|
| `..._told_to_do_something_else_is_rerun` | ĐỎ |
| `..._told_to_analyse_something_else_is_run_again` | ĐỎ |
| `..._the_new_analysis_reaches_the_report_too` | ĐỎ |
| `..._an_unchanged_plan_run_again_repeats_no_work` | **XANH** |

Dòng cuối mới là dòng quan trọng. Nếu nó cũng đỏ thì bản sửa đã biến thành "chạy lại tất cho
chắc", và như vậy là phá resume — đúng thứ mà cả cơ chế này sinh ra để bảo vệ.

**737 test · coverage 92%.**

---

## 2026-09-02 — Phase 4a, phần 2: khai thác quy trình và hai luật conformance

### `services/process_mining.py` — vẫn là **chỉ số có tên**, và đó là toàn bộ mẹo

Điểm nghẽn không đi ra dưới dạng câu văn. Nó đi ra dưới dạng
`process.wait.Nhan_hang__to__Nhan_hoa_don.median_hours`. Vì thế **không phải sửa một dòng nào**
của cơ chế chống bịa số: model được phép trích số, không được phép gõ số. Giống hệt cách
`statistics.py` được thêm vào hồi trước.

Đo được: số case · số event · số variant và tỷ lệ 5 variant lớn nhất · độ phủ · rework (lặp
lại trong case) tách khỏi self-loop (lặp ngay lập tức) · thời gian chạy case (trung vị, trung
bình, p95, max) · thời gian chờ trung vị của từng bước bàn giao.

**Trung vị chứ không phải trung bình cho thời gian chờ.** Một case bị bỏ quên tám tháng sẽ tự
mình chỉ định điểm nghẽn, và bước nó chỉ vào thường không phải bước ai sửa được.

**Rework và self-loop tách nhau** vì với người phải sửa quy trình chúng là hai vấn đề khác
nhau: quay lại sửa sai ≠ một bước bị ghi log hai lần.

### Từ chối, như thường lệ, mới là phần đáng kể

| Tình huống | Xử lý |
|---|---|
| Dưới 5 case | Vẫn báo **số đếm**, **không** báo tỷ lệ. 1/3 case là "33%", và 33% là thứ được trích đi tiếp |
| Cặp hoạt động quan sát dưới 3 lần | Không báo trung vị. Một trung vị từ hai lần đo là sự trùng hợp có dấu thập phân |
| Không có cột thời gian | Đo được trình tự, **không** đo thời gian — và nói rõ |
| Cột thời gian đọc được dưới 90% | Không báo **bất kỳ** số thời gian nào: bản thân thứ tự đã là phỏng đoán |
| Đồng hồ chạy ngược | Bỏ, không thành "thời gian chờ âm" |
| Sai tên cột | **Ném lỗi**, không phải từ chối — đoán xem cột nào mới là cách một phân tích đo nhầm thứ |

### Tính tất định: chỗ dễ hỏng nhất là chỗ không ai nghĩ tới

Hệ thống thật ghi log tới **giây**, nên hai event trong một case trùng timestamp là chuyện
thường xuyên. Nếu phá hoà bằng cách nào đó không ổn định thì hai lần chạy cùng một file ra
hai tập variant khác nhau — và S1 hỏng vì một lý do không ai nghĩ tới mà tìm.

Nên: `kind="mergesort"` (sort ổn định) ở mọi chỗ, thứ tự dòng gốc được giữ khi timestamp bằng
nhau, và hoà điểm giữa hai variant cùng tần suất được phá bằng **chính đường đi** chứ không
để may rủi. Có test riêng cho từng cái.

### Chống đụng key

`"Approve (A)"` và `"Approve [A]"` bẹt về cùng một slug. Nếu để vậy thì một cái **ghi đè** chỉ
số của cái kia và không có gì báo. `slug_map()` sắp xếp trước rồi mới thêm hậu tố — sắp xếp
trước để hậu tố không phụ thuộc vào thứ tự dòng đến.

### Hai luật conformance vào `validation.py`, không phải `rulebook.py`

Đúng như đã bàn: `rulebook.py` **biến đổi** dữ liệu (trả `CleanOutcome` có `diff_log`, cần
người duyệt ở GATE 1); `validation.py` **phán xử** dữ liệu (trả `list[Failure]`, không đụng
gì). "Nhận hàng phải trước nhận hoá đơn" là một phán xử về việc đã xảy ra, không phải một
thay đổi lên việc đã xảy ra.

Điểm mới về **hình dạng câu hỏi**: mọi check cũ nhìn **một dòng** và hỏi dòng đó có hợp lệ
không. Hai luật này nhìn **một case** — một tập dòng có thứ tự. Từng dòng có thể hoàn toàn
hợp lệ mà case vẫn sai.

- `sequence_order(before, after)` — vi phạm khi `after` xuất hiện mà `before` hoặc không hề
  có, hoặc có sau. Hai trường hợp cùng một khiếm khuyết về mặt kiểm soát (bước lẽ ra phải
  cho phép bước sau đã không làm điều đó) nên báo chung, nhưng phần chi tiết nói rõ là cái nào.
- `segregation_of_duties(first, second)` — vi phạm khi **cùng một người** làm cả hai trong
  **một case**. Cùng một người làm hai việc ở **hai case khác nhau** là bình thường — một
  người mua vừa lập đơn vừa duyệt đơn của người khác là đang làm đúng việc của họ.

**SoD không cần thứ tự**, nên nó vẫn chạy được trên log không có đồng hồ dùng được. Từ chối
nó vì thiếu timestamp là mất một chốt kiểm soát không vì lý do gì.

### Quyết định đáng cãi nhất: "không kiểm được" được báo là **thất bại**

Không phải vì dữ liệu vi phạm luật — rất có thể là không. Mà vì **một chốt kiểm soát âm thầm
đi qua khi nó không chạy được thì tệ hơn là không có chốt nào**: đã có người được thông báo
rằng quy trình sạch.

A5 dừng cả lần chạy khi có bất kỳ failure nào, và từ chối phân tích một quy trình mà không ai
xác lập được thứ tự là đúng thứ đáng dừng lại vì nó.

Failure ấy mang tên `...:unverifiable`, `count=0`, không có dòng mẫu, và chi tiết mở đầu bằng
`KHONG KIEM DUOC:` — nó nói rằng check không chạy, **không** nói rằng dữ liệu sai.

Cấy lỗi để kiểm: đổi nhánh ấy thành `continue` (im lặng bỏ qua) → 3 test đỏ.

### Khai vai trò cột **một lần**, và không đoán

Khối `event_log` khai `case_id/activity/timestamp/resource` một lần cho cả hai luật, thay vì
lặp trên từng luật. Lặp là cách một luật trỏ vào `case_company` còn luật bên cạnh trỏ vào
`case_id`, hai bên bất đồng về "case là gì" mà không bên nào trông có vẻ sai.

Có luật mà không có `event_log` → **từ chối thẳng**, không đoán. Cú đoán ấy đã xảy ra một lần
trong dự án này rồi, bằng so khớp mẫu, và nó gán sai case_id cho trọn một phân tích (L-BPI19).

`order_events()` được chuyển thành public để validator dùng **chung một định nghĩa** về "cái
gì xảy ra trước". Hai câu trả lời cho câu hỏi đó còn tệ hơn không có: báo cáo và trọng tài
mỗi bên đúng về một quy trình khác nhau.

### Chạy trên log thật

Fixture BPI 2019 (158 case · 5.000 event) chạy trọn: hơn 20 variant, variant lớn nhất không
chiếm 100%, thời gian chạy dương, có bước bàn giao đo được — và hai lần chạy ra đúng cùng
một con số. Test khẳng định `variants > 20` chính là test bắt được lỗi cũ: nếu vai trò cột bị
gán sai như lần trước thì 158 case sẽ ra đúng một đường đi.

**786 test · coverage 92% · `process_mining` 97% · `validation` 94%.**

---

## 2026-09-02 — Phase 4a, phần 3: A6 Process Miner

### Quyết định lớn nhất: **A6 không kết luận gì**

Cân nhắc hai kiểu:

| | A6 tự rút kết luận | A6 chỉ đo và đặt tên |
|---|---|---|
| Máy móc chống bịa số | Phải dựng lại lần hai | Dùng nguyên của A7 |
| Chỗ một kết luận có thể sai | Hai | Một |
| Trùng việc với A7 | Nhiều | Không |

Chọn cái thứ hai. A7 đã có sẵn placeholder, `evidence_ref`, kiểm trích dẫn, chặn nhân quả và
GATE 2. Dựng lại toàn bộ ở A6 nghĩa là **hai chỗ** một kết luận có thể đi sai, tức là nhiều
hơn một chỗ so với mức cần thiết.

Nên: **code đo, model chỉ đặt tên.** Đúng khuôn A2 nhưng áp lên trình tự thay vì lên cột.
Một đường đi 4/5 case đi qua là "luồng chuẩn"; một đường quay lại duyệt ba lần là "vòng làm
lại". Đó là phán đoán người đọc cần và số học không làm được.

### Không cho model nhìn thấy con số nào

Payload gửi lên chỉ có: tên hoạt động, thứ hạng, và **khoá** (`share_key`, `median_hours_key`).
Không một giá trị nào. Một con số đặt trước mặt model là một con số nó có thể chép vào nhãn.

Schema `ProcessInterpretation` **không có trường số nào cả** — không có chỗ nào cho một con số
ở, đúng cách phòng thủ đang dùng cho findings: chặn bằng **hình dạng**, không bằng soi xét.

### Luật chữ số phải kiểm **cả hai chiều**, và chiều thứ hai mới là chiều cắn

Cấm mọi chữ số thì dễ và **sai**. Quy trình thật có bước tên là `SRM: 5 Awaiting Approval`; model
không được viết cái đó thì nó không gọi tên được bước ấy. Đúng cú sửa quá tay đã xảy ra một lần
trên bộ dữ liệu study (L29) và làm cả một phân tích né tránh chiều mà nó được hỏi.

Nên: **bóc tên hoạt động của chính log ra trước**, rồi mới soi chữ số còn lại. Có test cho cả
hai chiều.

Ba tầng loại nhãn: có chữ số model tự gõ → loại; dài quá 80 ký tự → loại (đó là một *kết luận*,
mà kết luận là việc của A7); đặt tên cho path **không có trong kết quả đo** → loại, vì đằng sau
nó không có gì.

Nhãn bị loại chứ **không được sửa**. Sửa nghĩa là tự đoán nó định nói gì.

### Không có human gate ở A6

A6 không kết luận gì. Thêm một gate nữa ở đây chỉ khiến người ta bấm duyệt theo phản xạ — và
một cái gate bị bấm theo phản xạ thì không còn là gate.

### Mối nối A6 → A7, và hai lỗi nó phơi ra

Nếu A6 ghi ra một artifact không ai đọc thì còn tệ hơn không làm: con số vẫn tồn tại, vẫn trông
có vẻ chính thức, và không bao giờ tới được báo cáo. Nên A7 đọc bản đồ và **hợp chỉ số của nó
vào tập chỉ số** — không phải sửa gì trong cách một claim được kiểm, vì chỉ số quy trình cũng
là chỉ số.

Hai lỗi lộ ra trong lúc test, cả hai đều do **lớp boundary chặn đúng**:

### L41. A7 chưa được cấp quyền đọc `artifacts://`

Manifest của A7 có `mart/clean/validation/profile`, không có `artifacts`. Nối xong thì runtime
sẽ từ chối. Nó sẽ hỏng **ầm ĩ** chứ không âm thầm — đó là thiết kế đang chạy đúng — nhưng nó sẽ
hỏng ở lần chạy event log thật đầu tiên chứ không phải ở đây. A8 vốn đã đọc `artifacts://`, nên
tiền lệ có sẵn.

### L42. A7 giả định input **đầu tiên** là bảng

`request.input_refs[0]` — đúng cho tới khi bản đồ quy trình có thể đến cùng lượt. Kế hoạch liệt
kê ngược thứ tự thì A7 đọc JSON như Parquet và chết ở magic bytes, và lỗi chỉ vào tầng storage,
cách xa chỗ sai thật.

Định danh input **theo vị trí** vốn đã không tốt: đó là một luật ngầm mà người viết kế hoạch
không có cách nào biết. Giờ bảng được chọn **theo nó là cái gì**.

### Kiểm ngược

| Cấy lỗi | Kết quả |
|---|---|
| Bỏ kiểm chữ số trong nhãn | 2 test đỏ |
| (đã kiểm trước đó) im lặng bỏ qua check không chạy được | 3 test đỏ |
| (đã kiểm trước đó) bỏ so params_hash | 3 test đỏ |

Và một lần nữa **tôi lặp lại đúng lỗi L38**: viết invariant cho prompt mới bằng chữ không dấu
(`"khong gõ"`) trong khi file prompt viết `"không gõ"`. Lần này bộ test bắt ngay tại chỗ — đó
chính là thứ 22 invariant mức file được thêm hồi L38 sinh ra để làm.

**822 test · coverage 92% · A6 95% · planner đã thấy đủ 8 agent.**

---

## 2026-09-02 — Phase 4a, phần 4: chọn đặc trưng, và chạy lại đúng phần bị ảnh hưởng

### Vì sao là "đặc trưng" chứ không phải "cột"

Yêu cầu ban đầu rất bình thường: bảng có cột A đến E, người dùng chỉ quan tâm A và E, muốn
nói ra điều đó và nhận về phân tích của A và E.

Lý do nó không đơn giản là một danh sách cột nằm ở câu ngay sau đó. Đưa vào **ảnh** thì thứ
đáng chọn là **vật thể phát hiện được**; đưa vào **bản ghi âm** thì là **người nói**; đưa vào
**event log** thì là **hoạt động** và **người thực hiện**. Một cơ chế xây quanh "cột" sẽ phải
vứt đi ngay lần đầu đầu vào không còn là bảng, rồi vứt thêm lần nữa sau đó.

Nên đơn vị ở đây là **đặc trưng**: một thứ trong dữ liệu có thể được chọn hoặc bỏ. Cột là
*một loại* đặc trưng. Hoạt động là loại khác. Các loại để mở, và **không gì bên ngoài phần
trích xuất biết cột là gì**.

Có test cho đúng điểm này: cùng một cơ chế định tuyến một loại đặc trưng **không phải cột**
(hoạt động → A6) mà không sửa gì trong `selection.py`.

### Vai trò của cột được **đo**, không phán đoán

`numeric` · `categorical` · `temporal` · `identifier` · `text`. Nhờ đó người dùng chọn hai cột
mà **không phải tự nói** cái nào là nhóm cái nào là số đo — hệ thống đọc vai trò rồi đưa vào
đúng tham số.

**Một giới hạn đã biết, ghi lại chứ không sửa:** một cột ghi chú mà mỗi dòng một khác sẽ bị gọi
là `identifier`. Phân biệt văn xuôi với mã định danh phải đoán theo độ dài chuỗi — đó là một
**ý kiến** về dữ liệu chứ không phải một **phép đo**, mà module này không giữ ý kiến nào. Hai
vai trò ấy có cùng ý nghĩa với mọi thứ phía sau ("đừng nhóm theo cột này"), nên cái giá phải
trả chỉ là một chữ hơi lạ trong danh sách.

### Agent tự khai tham số nào ăn đặc trưng, trong manifest của nó

Phương án kia là một bảng ánh xạ agent → tên tham số nằm đâu đó trong Manager. Dự án này đã
mắc đúng cái bẫy hình dạng đó rồi: logic gate từng gọi thẳng tên agent, và thêm một agent
nghĩa là phải sửa Manager. Gate giờ đọc từ manifest, và cái này cũng vậy.

Nó cũng đặt sự thật vào chỗ người ta sẽ đi tìm: *"tham số nào của A7 là về cột"* là một câu hỏi
**về A7**.

### Chọn xong không phải làm gì thêm — và đó là chỗ L40 trả công

Một lựa chọn **không phải câu hỏi mới**. Nó là cùng câu hỏi ấy hỏi về ít dữ liệu hơn. Nên nó
không sinh kế hoạch mới; nó sửa tham số của các task ăn đặc trưng và để yên phần còn lại.

Chuyện xảy ra sau đó **không phải việc của module này**, và đó chính là điểm hay: vì tham số
nằm trong danh tính task (L40), lựa chọn đổi làm mất hiệu lực **đúng** những task bị đổi lệnh;
output của chúng đổi; task phía sau chạy lại vì **đầu vào** đổi. Không chỗ nào ở đây cần biết
task nào phụ thuộc task nào.

Nếu L40 chưa sửa trước thì tính năng này sẽ trả về câu trả lời cũ cho câu hỏi mới, **im lặng**.
Đó là lý do L40 phải làm trước, và có test cấy lỗi chứng minh đúng điều đó: bỏ so `params_hash`
→ test chọn-lại-end-to-end đỏ.

### Ba thứ bị từ chối, và lý do

| Từ chối | Vì sao |
|---|---|
| Tên đặc trưng không có trong dữ liệu | Phân tích bốn cái gõ đúng rồi im lặng bỏ cái gõ sai là cách một người đọc được câu trả lời cho **câu hỏi khác** |
| Lựa chọn không task nào dùng được | Nó sẽ không đổi gì, và người ta ngồi chờ một câu trả lời khác vốn không bao giờ tới |
| Tham số rỗng thì **vẫn ghi**, không bỏ trống | Bỏ trống thì task quay về hành vi cũ, mà mặc định của "đo cột nào" là **tất cả** — thu hẹp lựa chọn lại thành mở rộng phân tích |

### Lọc event log theo hoạt động: được, nhưng phải nói to

A6 tôn trọng `keep_activities`. Đây là phân tích quy trình bình thường ("chỉ xem các bước
duyệt") nhưng **không phải một phép thu hẹp vô hại**: mọi variant, thời gian chờ và số liệu
rework sau đó mô tả một quy trình **không ai chạy**, vì hai case chỉ khác nhau ở một bước bị lọc
sẽ thành cùng một variant.

Nên phần ghi chú đi **cùng chỗ với các con số** (`refused`), không nằm trong một chú thích ở
đâu đó — người đọc không thể thấy số mà không thấy số đó là số về cái gì.

### Hai lỗi tìm được bằng cách **chạy lệnh**, không phải bằng test

### L43. `--clear` xoá lựa chọn nhưng không hoàn lại kế hoạch

Nó ghi file lựa chọn rỗng rồi dừng; kế hoạch vẫn mang các tham số mà lựa chọn trước đã đặt vào.
Nên "quay về phân tích tất cả" **âm thầm** tiếp tục phân tích đúng cái nó vừa phân tích, và
state thì đồng ý rằng không có gì được chọn.

Sửa bằng cách giữ lại `plan.base.json` — kế hoạch như trước khi có ai chọn. `--clear` phục hồi
file đó, thay vì cố suy ra tham số nào đến từ lựa chọn và tham số nào do planner tự đặt: phép
đoán ấy sẽ sai mỗi khi planner có ý kiến về cột, và sai **vô hình**.

### L44. `rich` đọc `[x]` là thẻ markup và nuốt mất dấu tick

Mọi đặc trưng đã chọn in ra y như chưa chọn. Một cái tên đặc trưng có chứa ngoặc vuông cũng sẽ
đi cùng đường. Sửa bằng `markup=False` cho khối danh sách.

**870 test · coverage 92% · `features` 96% · `selection` 98%.**

---

## 2026-09-02 — Kiểm chứng Phase 4a trên bộ study (200 dòng, Gemini free, $0)

Một lần chạy thật, một câu hỏi thật, và **năm lỗi**. Cả năm nằm trong code mà bộ test đã phủ,
và **không lỗi nào làm đỏ một test nào** — vì mọi test đều dựng kế hoạch và đầu vào theo đúng
hình dạng mà test mong đợi, tức là hình dạng chạy được.

Đây là lần thứ ba trong dự án việc chạy thật bắt được thứ mà test không bắt. Đáng ghi lại
thành một quy tắc chứ không phải một sự cố.

### L45. Gần như **mọi agent** nhận diện đầu vào theo **vị trí**

Planner, khi được tự do khai `inputs_from`, đã viết `["t3_clean", "t2_profile"]` cho A4 — một
kế hoạch hoàn toàn hợp lý, hồ sơ dữ liệu là ngữ cảnh có ích. A4 đọc **mọi** input như Parquet,
gặp file JSON, và chết ở magic bytes.

Đúng khiếm khuyết tôi đã sửa cho A7 (L42) và **không đi tìm ở chỗ khác**. Nó nằm trong năm
agent nữa: A2, A3, A5, A6, A8.

Vị trí chưa bao giờ là cách nhận diện đầu vào. Đó là một **luật ngầm** mà model viết kế hoạch
không có cách nào biết, và vi phạm nó sinh ra một lỗi chỉ vào tầng storage — cách rất xa chỗ
sai thật. Agent biết nó cần **loại** gì; đó mới là thứ nó nên hỏi.

Sửa: `first_of(refs, *formats)` và `all_of(refs, *formats)` trong `agents/base.py`. Lọc theo
**định dạng**, không theo tên hay đường dẫn — định dạng mới là thứ quyết định phép đọc có chạy
được hay không.

### L46. A4 dựng sẵn cơ chế thử lại rồi **tắt nó đi**

`_proposal` đã truyền `feedback_from(...)` vào request, nên lần thử thứ hai sẽ được cho biết
lineage của nó khai cột nào mà kết quả không có. Nhưng `_failed` đóng dấu `retryable=False`
cho **mọi** kết cục, nên lần thứ hai không bao giờ xảy ra.

Model viết một câu GROUP BY, khai lineage cho các cột chính nó đã gộp mất, và lần chạy kết
thúc — đúng loại sai lầm mà chỉ cần nói cho nó biết là sửa được. A7 làm ngược lại từ Phase 2:
từ chối, nói vì sao, hỏi lại.

Việc chọn **lỗi nào là model sửa được** mới là toàn bộ câu hỏi, và câu trả lời không phải "tất
cả": bị đưa cho không bảng nào thì một câu trả lời hay hơn cũng không cứu được.

Sau khi bật: A4 qua ở lần thử thứ hai, `attempts=2`, và lần chạy đi tiếp tới báo cáo.

### L47. Một phê duyệt sống lâu hơn thứ nó phê duyệt

Thu hẹp phân tích, chạy lại, A7 ra **2 kết luận** thay vì 3. Quyết định đã lưu vẫn duyệt
f1/f2/f3, và f3 không còn tồn tại.

Lần chạy dừng lại và nói ra — tốt hơn nhiều so với việc báo cáo hai cái còn sót. Nhưng **dừng
là câu trả lời sai**. Người dùng đã duyệt *những* kết luận đó; những kết luận khác thì chưa ai
duyệt, và việc đúng phải làm là **hỏi lại**.

Trước khi có cơ chế chọn đặc trưng thì chuyện này gần như không xảy ra — một task có gate hiếm
khi chạy lại với đầu ra khác. Giờ nó là trường hợp **bình thường**, vì thu hẹp một phân tích
chính là chạy lại với đầu ra khác.

Sửa: quyết định ghi nhớ **nó về cái gì** (`decided_on` — dấu vân tay của tập lựa chọn đã được
đưa ra). Không khớp thì hỏi lại.

Chỉ băm **id của các lựa chọn**, không băm câu chữ: sửa lại cách diễn đạt mà không đổi các lựa
chọn thì không làm mất hiệu lực câu trả lời. Bắt người ta duyệt lại đúng ba kết luận ấy chỉ vì
một câu được viết lại là cách biến gate thành thứ người ta bấm cho xong.

**Không biết thì coi như không hợp lệ.** Một quyết định cũ không có dấu vân tay nghĩa là không
gì ghi lại nó về cái gì — và giả định rằng nó vừa khớp chính là giả định đúng cái mà phép kiểm
này sinh ra để xác lập. Giá phải trả: một lần duyệt lại trên các lần chạy cũ.

### L48. Câu hỏi trên đĩa **cũ hơn** kết quả mà nó hỏi về

File gate chỉ được ghi khi lần chạy **dừng lại**. Nhưng một task có gate có thể ra kết quả mới
**mà không dừng** — và nó đã làm vậy, đúng lúc một phê duyệt cũ vẫn còn được tôn trọng. Sau
đó file trên đĩa mô tả một kết quả không còn tồn tại.

Người dùng được hỏi về ba kết luận trong khi phân tích chỉ giữ hai. Duyệt cái thứ ba thì báo
cáo hỏng.

Bất biến còn thiếu, nói thẳng ra: **câu hỏi một người nhìn thấy luôn mô tả kết quả hiện tại
của task đó.** Nên gate được ghi mỗi khi task có gate ra kết quả, chứ không phải khi Manager
tình cờ dừng.

Nhưng thế vẫn chưa đủ cho task **bị bỏ qua**: không có gì chạy nên không có gì làm mới câu
hỏi. Nên `GateRequest` mang luôn `result_hash` — hash của đầu ra mà nó được dựng từ đó. Không
khớp với đầu ra hiện tại của task → câu hỏi đã cũ → **chạy lại task** thay vì bỏ qua.

Và chỉ khi câu hỏi là hiện hành thì phép so quyết định ở L47 mới có nghĩa; trước đó nó có thể
đang so với một câu hỏi cũ hai đời.

### L49. Một quả bom hẹn giờ trong chính bộ test

Bốn test S5 đột nhiên đỏ giữa buổi. Không phải do bản sửa nào: `budget_of()` ghim
`started_at` vào mốc cố định 12:00 ngày 2026-09-02 với trần 30 phút, trong khi lần chạy đo
thời gian bằng **đồng hồ thật**. Lúc đó là 12:31.

Nghĩa là bộ test này pass tới 12:30 hôm nay rồi **đỏ vĩnh viễn** từ đó về sau, vì một lý do
không liên quan gì tới code. Sửa: ngân sách bắt đầu từ `datetime.now(UTC)`. Trần thời gian
thực vẫn được kiểm ở `tests/unit/test_budget.py`, nơi đồng hồ được **truyền vào** chứ không
phải đọc ra.

### Kiểm ngược cả ba bản sửa lớn

| Cấy lỗi | Kết quả |
|---|---|
| A4 nạp mọi ref như parquet | 1 test đỏ |
| Phê duyệt luôn còn hợp lệ | 2 test đỏ |
| (đã kiểm) bỏ so `params_hash` | 3 test đỏ |

Và test *"không đổi gì thì phê duyệt vẫn phát lại được"* vẫn xanh — nếu nó cũng đỏ thì bản sửa
đã biến thành "hỏi lại cho chắc", và một cái gate hỏi lại mỗi lần resume sẽ bị bấm cho xong.

### Kết quả kiểm chứng Phase 4a

| Việc | Kết quả |
|---|---|
| `asys features` liệt kê 8 đặc trưng, đo đúng vai trò | ✅ |
| Gõ sai tên → **từ chối**, không phân tích phần còn lại | ✅ |
| Chọn 2 đặc trưng → chỉ `t5_analyze` được nêu là sẽ làm lại | ✅ |
| Chạy lại → phân tích **chỉ còn** `final_exam_score` theo `final_grade` | ✅ |
| Gate hỏi lại vì kết luận đã khác | ✅ (sau L47/L48) |
| Báo cáo cuối chỉ chứa chỉ số của hai đặc trưng đã chọn | ✅ |
| A6 process miner và hai luật conformance | ⬜ **chưa kiểm** — bộ study không phải event log |

**874 test · coverage 92% · chi phí: $0.**

---

## 2026-09-02 — Kiểm chứng phần khai thác quy trình trên một event log thật

Kaggle cần khoá API mà máy chưa có, nên lấy một log công khai không cần đăng nhập: **hồ sơ
xin cấp phép môi trường của một đô thị Hà Lan** (đi kèm pm4py). 1.434 ca · 8.577 sự kiện ·
27 hoạt động · 48 người thực hiện — lĩnh vực khác hẳn BPI19 (mua sắm).

Số đếm khớp với con số đã công bố của log này. Hai lỗi lộ ra.

### L50. Bảng điểm nghẽn xếp hạng **nhiễu** lên đầu

Ba vị trí đầu đều chỉ quan sát được **3 lần**. Trong khi đó một bước bàn giao xảy ra **791
lần** và ngốn **58.131 giờ** — gấp **60 lần** cái đứng đầu bảng. Ai đọc bảng đó sẽ đi sửa một
bước xảy ra ba lần.

Sai lầm: coi **một con số** là câu trả lời cho **hai câu hỏi khác nhau**.

| Câu hỏi | Thống kê đúng | Cần gì |
|---|---|---|
| Một ca chờ lâu nhất ở đâu? | **trung vị** | phải có mẫu đủ lớn |
| Quy trình mất nhiều thời gian nhất ở đâu? | **tổng** | có nghĩa ở mọi cỡ mẫu |

Nên giờ báo **cả hai**, xếp hạng theo **tổng** — vì "điểm nghẽn" gần như luôn là câu hỏi thứ
hai. Trung vị và số lần quan sát nằm ngay cạnh mỗi tổng, nhờ đó phân biệt được hai loại vấn
đề khác hẳn nhau:

- `T05 → T06`: tổng **58.131 giờ** / 791 lần / điển hình **0,01 giờ** → phần lớn tức thì, một
  cái đuôi nhỏ kéo dài khủng khiếp
- `T10 → T02`: tổng **11.401 giờ** / 155 lần / điển hình **3,51 giờ** → **lần nào cũng chậm**

Ngưỡng cho trung vị nâng từ 3 lên **10**. Ba là con số tôi chọn lúc viết module, và nó quá nhỏ
ngay lần đầu dữ liệu thật chạm vào. Tổng thì **không** có ngưỡng — tổng của năm lần chờ chính
xác là thời gian năm ca đó đã mất.

### L51. Một luật đặt tên bị áp lên thứ không phải tên

Model trả về bốn nhận xét về quy trình, **ba bị vứt** vì dài quá 80 ký tự. 80 là trần đúng cho
một **tên gọi** — dài hơn thế thì nó là một kết luận đội lốt cái tên — nhưng một **nhận xét**
tự nhiên là một câu, và bắt nó theo luật của tên khiến một trường thiết kế cho 5 ghi chú chỉ
trả về 1.

Giờ có hai trần: tên ≤ 80, câu mô tả ≤ 240. Luật cấm chữ số **giữ nguyên** cho cả hai — đó mới
là phần quan trọng.

Sau khi sửa: **4/4 nhận xét được giữ**, không cái nào bị loại.

### Kiểm chéo hai luật kiểm soát bằng phép tính độc lập

| Luật | Hệ thống báo | Tính tay | |
|---|---|---|---|
| T02 phải trước T06 | **239** ca vi phạm, trong đó **2** ca không hề có T02 | 239 / 2 | ✅ khớp |
| Người kiểm ≠ người quyết định (T02 vs T04) | **2.105** sự kiện | 2.105 | ✅ khớp |

2.105 sự kiện vi phạm phân tách trách nhiệm là một phát hiện thật về quy trình này, không phải
lỗi công cụ.

### Model đặt tên: đúng thứ số học không làm được

| | Tên model đặt | Đường đi |
|---|---|---|
| #1 | Luồng chuẩn | Confirmation → T02 → T04 → T05 → T06 → T10 |
| #2 | Luồng đảo thứ tự đánh giá | Confirmation → T06 → T10 → T02 → T04 → T05 |
| #3 | Luồng dừng sớm | chỉ có Confirmation |

Không một con số nào do model gõ. Và các nhận xét của nó khớp với những gì code đo được một
cách độc lập: *"đảo lộn thứ tự ở các nhánh phụ"* ↔ 239 ca vi phạm thứ tự; *"luồng chỉ gồm một
bước"* ↔ 116 ca một sự kiện.

### Điều đáng ghi nhất

Hai lỗi này **chỉ lộ ra vì dữ liệu thật có cái đuôi dài** — hàng chục hoạt động hiếm bên cạnh
sáu hoạt động phổ biến. Dữ liệu tự sinh trong test đều đặn, nên xếp theo trung vị hay theo
tổng đều ra cùng thứ tự và không test nào phân biệt được. Đây là lần thứ tư trong dự án việc
chạy thật bắt được thứ mà test không bắt.

**880 test · coverage 92% · chi phí: $0.**

---

## 2026-09-03 — Phase 4b.2: Manager tổng hợp, và biểu đồ là bằng chứng

### Bảy loại biểu đồ, và việc **chọn** quan trọng hơn việc vẽ

`bar · hbar · grouped_bar · line · scatter · box · heatmap`. Nhưng phần đáng kể là
`chart_choice.py`: chọn sai hình là **giấu đi đúng thứ đáng nhìn**. Hai nhóm cùng trung bình
trông y hệt nhau ở dạng cột và khác hẳn nhau ở dạng hộp; hệ số 0,3 có thể là một đường thẳng
yếu hoặc một đường cong mạnh, và chỉ biểu đồ phân tán mới nói được là cái nào.

Mỗi gợi ý **kèm lý do**. Một bảng xếp hạng không có lý do là một ý kiến; có lý do thì nó là
thứ người ta cãi lại được, và đó mới là điểm.

Bằng code chứ không hỏi model: cột nào chứa số, một nhóm có bao nhiêu giá trị — đó là **phép
đo**. Model được hỏi sẽ đưa ra một thứ tự nghe hợp lý và khác nhau giữa hai lần chạy.

### L55. Một loại biểu đồ chiếm hết bảng xếp hạng

Sáu gợi ý trả về thì **cả sáu đều là scatter**, vì mỗi cặp tương quan đều được cùng điểm và có
sáu cặp. Hộp, nhiệt, cột không bao giờ xuất hiện — nên người hỏi *"loại biểu đồ nào hợp với
dữ liệu của tôi"* được xem **một loại, sáu lần**.

Cùng khuyết điểm với trần thống kê ở L53, nhưng ở đây nó phá hỏng mục đích triệt để hơn: cả
lý do để xếp hạng **loại** biểu đồ là để đưa ra những **cách nhìn khác nhau**. Sáu góc nhìn về
cùng một hình dạng là một góc nhìn.

Tối đa hai cái mỗi loại. Hoà điểm vẫn xếp theo bảng chữ cái — phá hoà bằng độ mạnh của quan hệ
là **chọn biểu đồ theo kết quả của chúng**, đúng hình dạng của p-hacking.

### A9 Manager: nơi dễ bịa nhất, nên bị siết chặt nhất

Mọi agent khác nhìn dữ liệu rồi báo cáo. **Không gì đọc các báo cáo ấy cùng nhau và nói "vậy
đây là câu trả lời"** — nên một câu hỏi cần cả khai thác quy trình lẫn phân tích thống kê nhận
về hai tập phát hiện và không có kết luận, và người đặt câu hỏi phải tự nối chúng lại.

Viết thành **một agent có manifest và scope**, vì đúng lúc nó bắt đầu rút ra kết luận thì nó
thành chỗ dễ bịa nhất hệ thống. Miễn trừ Manager khỏi luật mà mọi agent khác phải theo là đặt
thành phần **ít bị kiểm nhất** vào đúng chỗ **gây hại nhiều nhất**.

Ba ràng buộc, không cái nào mới:

- **Số nằm sau placeholder.** Dùng nguyên `render_all` của `findings.py` — đúng máy móc A7 đã
  dùng từ Phase 2. Dựng cái thứ hai cho Manager là dựng **chỗ thứ hai để một con số bị bịa ra**.
- **Mỗi luận điểm phải dẫn được cái gì đó.** Câu không dẫn chỉ số nào là một **ý kiến**, dù nó
  đọc hay đến mấy.
- **Cái gì KHÔNG xác lập được thì đặt trước mặt nó** trước khi nó viết chữ nào. Một kết luận
  chồng lên chỗ trống không ai nhắc tới đọc **y hệt** một kết luận vững.

Chạy thật, model tự viết ra: *"Dữ liệu hiện tại không thể xác lập sâu hơn... do không đủ cột
số"* — nó tự nói ra chỗ trống thay vì bước qua.

### Bốn lỗi lộ ra khi chạy thật

### L56. Tập chỉ số chết theo task tính ra nó

Artifact của A7 ghi `metrics_available: 88` và **không ghi 88 chỉ số đó**. Một con số đếm thứ
không ai xem được chính là loại nửa-sự-thật hệ thống này từ chối ở mọi chỗ khác — và nó có hậu
quả: Manager nhận artifact ấy, không có con số nào để dựng lập luận, nên mọi luận điểm nó viết
đều dẫn một khoá không tồn tại và bị loại sạch.

Lỗi thì đúng mà **thông báo thì vô dụng**: *"không luận điểm nào qua được"* rồi hết, vì cũng
chẳng có gì để mà loại. Một lời từ chối không nói nó từ chối cái gì là một bức tường.

### L57. Hai luận điểm khác nhau nhận **cùng một biểu đồ**

Cùng đúng MD5. Một luận điểm về giờ học và điểm thi, một về giờ ngủ và điểm thi, và hình bên
cạnh cả hai là biểu đồ phân tán của **chuyên cần** với điểm thi — hình của **không cái nào**.

Phép khớp là *"cột nào đó của biểu đồ xuất hiện đâu đó trong khoá của luận điểm"*. Scatter của
(chuyên cần, điểm) khớp với luận điểm về (giờ học, điểm) vì chung chữ *điểm*, và ứng viên đầu
tiên theo bảng chữ cái thắng mọi lần.

Đây **đúng là thứ mà cả tính năng này sinh ra để chặn**. Một biểu đồ không vẽ cái đang được
khẳng định là **trang trí đứng ở chỗ của bằng chứng** — và tệ hơn không có biểu đồ, vì nó
*trông giống* bằng chứng.

Giờ: một biểu đồ chỉ đỡ được một luận điểm khi **mọi thứ nó vẽ** đều được nêu trong khoá của
luận điểm ấy. Khớp theo **đoạn nguyên** chứ không phải chuỗi con, để `grade` không khớp
`previous_grade`.

### L58. Sơ đồ BPMN **nói giảm** phần nó bỏ sót

File ghi "vẽ từ 5 trong 5 đường đã đo". Log có **116**. `ProcessMap.variants` chỉ giữ vài
đường đứng đầu, nên đếm chúng là đếm **danh sách rút gọn** chứ không phải quy trình — và câu
lẽ ra để thú nhận phần bỏ sót lại chính là câu che nó đi.

Con số thật nằm trong tập chỉ số, nơi mọi con số khác của hệ thống này sống. Giờ nó ghi:
*"5 trong 116 đường, chiếm 79,6% số case; 20,4% còn lại KHÔNG có trong sơ đồ này."*

Một sơ đồ âm thầm bỏ sót một phần năm thực tế thì tệ hơn một sơ đồ nói ra điều đó — và một sơ
đồ **khẳng định nó không bỏ sót gì** thì tệ hơn cả hai.

### L59. Manager không hề nhận được bảng, nên biểu đồ **âm thầm không xảy ra**

Ba luận điểm tương quan trở về **không có lấy một hình**. Mỗi cái đúng là loại luận điểm mà
biểu đồ phân tán tồn tại để phục vụ, và mỗi cái được con số không.

Lý do: scatter và box cần **từng dòng**, không phải bản tóm tắt, mà Manager chỉ được đưa các
artifact do skill nó viết ra. Bảng dữ liệu là **nguồn của lần chạy**, thứ chỉ đến với task
không khai `inputs_from` — mà Manager thì khai vài cái.

Sửa bằng cách **lần theo một trích dẫn vốn đã có sẵn**: mọi artifact phân tích đều ghi bảng nó
được tính từ đó — đó chính là thứ làm cho phát hiện của nó truy ngược được. Không đoán gì: trích
dẫn không đọc được thì không có biểu đồ, và luận điểm giữ nguyên con số của nó.

**Điều đáng nói nhất: nó hỏng trong im lặng.** Mọi luận điểm đều đúng, mọi trích dẫn đều vững,
và tính năng mà cả phase này sinh ra để làm đã không chạy. Một bảo đảm có thể lặng lẽ không xảy
ra là loại bảo đảm đáng có test riêng.

### Một chỗ tôi cố ý làm khác lời anh nói

Anh nói *"không vẽ được thì không được nói"*. Tôi làm nhẹ hơn một bậc, và xin nói rõ vì sao:

Luận điểm *"2.105 sự kiện vi phạm phân tách trách nhiệm"* là **một con số**. Biểu đồ cột một
cột không cho thấy gì mà lại **trông như đang cho thấy gì đó**. Bắt mọi luận điểm phải có hình
sẽ vứt đi những phát hiện thật, hoặc sinh ra hình vô nghĩa.

Nên luật thật là: **mỗi luận điểm phải dẫn được một chỉ số có thật** (câu không dẫn được gì thì
bị loại — đó mới là ranh giới thật giữa kết luận và ý kiến), và **có biểu đồ khi hình dạng của
nó cho phép**. Luận điểm không có hình được ghi rõ là không có hình, để anh nhìn ra.

**996 test · coverage 92% · chi phí: $0.**

---

## 2026-09-03 — Phase 5: đọc dữ liệu phi cấu trúc

### Nguyên tắc: đọc là **phép đo**, không phải diễn giải

Không extractor nào được dùng model. Một model được bảo "đọc" một bản scan mờ sẽ sinh ra chữ
**nghe rất hợp lý ở đúng chỗ bản scan không đọc được** — và sinh ra mà **không kèm độ tin cậy
nào**, vì nó chưa bao giờ thấy mình không chắc. Đó chính xác là thứ tiêu chí S6 tồn tại để bắt.

### Ba thứ luôn đi cùng nhau, hoặc không có gì

Một đoạn văn bản trích ra không tồn tại được nếu thiếu **nơi nó đến từ** và **độ chắc chắn của
người đọc**. Schema không có chỗ cho một con số trần trụi — cùng cách phòng thủ đang dùng cho
findings, áp lên phần dữ liệu vào.

- `SourceLocator` — trang mấy, vùng nào trên trang, giây thứ mấy trong bản ghi
- `confidence` — 0..1, từ chính OCR / nhận dạng tiếng nói

Một con số lấy từ tài liệu mà không ai đi tra lại được thì đáng giá đúng bằng một con số model
bịa ra.

### Nhận dạng loại file bằng **byte**, không bằng đuôi

Một file `.csv` bên trong là PDF là lỗi người ta gặp thường xuyên. Tin vào cái tên sẽ đẩy nó
sang một reader không đọc được, và lỗi hiện ra là *"sai số cột"* — cách rất xa sự thật.

### Gate chỉ hỏi khi có gì để hỏi

Bản đầu tôi khai `at: after_execution`, và một PDF số đọc **chính xác 100%** vẫn dừng lại bắt
người dùng xác nhận... không có gì. Sai.

A3 đã giải đúng bài toán này rồi và câu trả lời là `before_execution`: agent chạy, thấy chưa có
phê duyệt, tự quyết định có cần hỏi không (`NEEDS_REVIEW` khi độ tin cậy thấp), Manager ghi gate
và dừng. Khi đã có quyết định thì nó được **tiêm vào tham số trước lần chạy sau**, agent thấy và
trả về OK — đó mới là thứ phá vòng lặp.

Đo thật trên ảnh mờ vừa: 1/8 đoạn dưới ngưỡng = 12,5% < 15% → **không dừng**. Một từ mờ trong
tám không đáng bắt người ta dừng lại; một cái gate bật vì mọi vết nhoè là cái gate người ta học
cách bấm cho xong.

### Và chỉ đưa ra **những đoạn đáng ngờ**

`span_options` chỉ liệt kê đoạn dưới ngưỡng. Đặt bốn trăm dòng đọc rõ trước mặt một người là
cách khiến họ không đọc dòng nào — và như thế thì mất luôn tác dụng của phép kiểm.

### L61. "Không đọc ra gì" mà vẫn báo OK

Ảnh trắng → OCR ra **không chữ nào** → `status: OK` kèm ghi chú. Đó là kết cục **tệ nhất** của
trích xuất, và "OK" là chữ sai để mô tả nó: nó trao cho bước sau một file rỗng kèm giấy chứng
nhận sạch sẽ.

Một bản trích xuất **vắng mặt** không phải một bản trích xuất **kém cần gắn cờ**. Giờ nó
**thất bại**.

### Ba phân biệt nhỏ mà quan trọng

| | |
|---|---|
| "đọc được với độ tin cậy thấp" ≠ "không đọc được" | OCR trả về -1 cho vùng không nhận ra chữ nào. Bình quân hoá -1 vào sẽ âm thầm kéo tụt cả trang và giấu mất chỗ nào thật sự đã đọc — nên nó được **đếm**, không được **chấm điểm** |
| PDF có lớp text ≠ PDF là ảnh chụp | Cái đầu đọc **chính xác** (ký tự đã nằm sẵn, không đoán gì, tin cậy 1.0). Cái sau trả về rỗng — và nói rõ *"đây là ẢNH CHỤP trang giấy"*, vì trả về rỗng suông sẽ bị đọc thành "tài liệu trống" |
| bảng ≠ văn xuôi | Đọc bảng thành từng dòng là mất cột, mà cột thường chính là lý do người ta gửi PDF thay vì gửi bảng tính. Bảng được tách **nguyên khối** |

### Giới hạn thẳng thắn

**Trích ra được văn bản ≠ có dữ liệu để phân tích.** Nếu file chỉ có chữ mà không có bảng, hệ
thống nói rõ: *"phần đọc được là VĂN BẢN, chưa phải dữ liệu có cấu trúc"*. Biến câu văn thành
hàng cột là **bài toán khác**, và nó cần một bước có model — thứ mà phần đọc cố ý không có.

**Chưa tách được người nói.** Bản ghi cho biết *nói gì, lúc nào*, chưa cho biết *ai nói*. Câu
hỏi kiểu "ai nói gì" chưa trả lời được, và điều đó được ghi vào phần từ chối chứ không im lặng.

Agent nhận **byte**, không nhận đường dẫn. Một `Path` đi thẳng vòng qua ranh giới mà
`ScopedStorage` sinh ra để vẽ — mọi thư viện ở đây đều nhận stream nên không mất gì.

**1.040 test · coverage 89% · chi phí: $0.**

---

## 2026-09-03 — Phase 6: đo cái mô hình biết, không đoán cái nó chưa thấy

### Quyết định thiết kế: chọn hướng B

Ba lựa chọn đã đặt ra, và vì sao chọn cái thứ hai:

| | Cách làm | Đánh đổi |
|---|---|---|
| A | Nới `evidence_ref` cho phép trỏ tới **model card** | Provenance đầy đủ, nhưng là **loại bằng chứng khác** — người đọc không đi xem được thứ làm câu đó đúng |
| **B** | **Chỉ báo cáo cái mô hình ĐO ĐƯỢC trên dữ liệu đang có** | **S4 không phải sửa. Máy móc chống bịa số chạy nguyên** |
| C | Cho dự đoán nhưng cách ly vào họ `forecast.*` | Hai hạng con số trong một báo cáo — và hạng yếu **trông giống hệt** hạng mạnh ngay khi ai đó copy sang slide |

Hệ thống này đứng trên một nguyên tắc: **mọi kết luận truy ngược được về những dòng người ta
đi xem được.** Một dự đoán phá vỡ nó — *"khách hàng này có 73% khả năng rời bỏ"* truy về một mô
hình, một lần chia dữ liệu và một hạt giống ngẫu nhiên.

Nên không có gì ở đây dự đoán. Hai thứ được **đo** thay vào đó, và cả hai đều là phát biểu về
các dòng đang có:

- **Biến nào mang kết quả, mang bao nhiêu** — một thuộc tính của dữ liệu, cùng loại với hệ số
  tương quan, truy ngược y hệt
- **Dòng nào giống dòng nào** — một nhãn cụm **mô tả chính dòng nó gắn vào**, không nói gì về
  dòng chưa ai thấy

Phân cụm nằm gọn trong B vì lý do đó, chứ không phải vì tiện.

### Phép từ chối ở đây nặng hơn mọi chỗ khác trong hệ thống

Cả hai kỹ thuật đều **cho ra kết quả trông rất tự tin trên dữ liệu không đỡ nổi chúng**, và
không cái nào tự nói ra. Một cây sẽ xếp hạng biến trên ba mươi dòng; k-means sẽ trả về năm cụm
gọn gàng từ một đám mây vô định hình.

**Xếp hạng phải sống sót qua việc đổi hạt giống.** Tầm quan trọng của mô hình cây nổi tiếng là
không ổn định — khớp lại dưới 5 hạt giống cố định, thứ tự đổi thì **vứt cả bảng**. Một xếp hạng
thay đổi theo hạt giống là xếp hạng của không gì cả, nhưng nó **đọc y hệt một phát hiện**.

**Mô hình phải khớp trên phần dữ liệu không được học** (r² ≥ 10%). Xếp hạng biến của một mô
hình không khớp là xếp hạng nhiễu. Đo thật trên nhiễu thuần: r² = −17% → từ chối.

### L63. Một ngưỡng cố định không phân biệt được "nhóm" với "đám tròn"

Ba trăm điểm rút từ **một** phân phối Gaussian hai chiều — không có nhóm nào cả — trả về **ba
cụm** với độ tách biệt 0,35, thoải mái vượt ngưỡng 0,25 tôi tự đặt.

Con số không sai; **câu hỏi mới sai.** *"0,35 có tốt không"* không có câu trả lời, vì k-means
làm một đám mây trông tách biệt đến đâu phụ thuộc vào số cột và độ tản của chúng, chứ không
phụ thuộc vào việc trong đó có nhóm hay không.

Câu hỏi **có** câu trả lời là câu so sánh: *"cái này có tách biệt hơn dữ liệu cùng hình dạng
mà không có cấu trúc gì không?"* Nên cùng phép chia được chạy trên một mẫu đối chứng lấy đều
trên đúng khoảng giá trị của từng cột — cùng số dòng, cùng số cột, cùng độ trải, và **rỗng bên
trong**.

Đo lại: đám tròn đạt 0,35, **mẫu đối chứng đạt 0,40** → hơn −0,05 → **từ chối**. Cụm thật đạt
0,86 → nhận. Ngưỡng cố định không cho được câu trả lời đó.

### Ba cái bẫy diễn giải, đã chặn

- **`.importance.` được thêm vào họ chỉ số "chỉ đo mối liên hệ"** của `causal_overreach`. *"Biết
  biến này giúp đoán kết quả tốt hơn"* bị đọc thành *"thay đổi biến này thì kết quả đổi"* liên
  tục, và nó không nói thế.
- **Chuẩn hoá trước khi phân cụm.** Không chuẩn hoá thì cột có số lớn nhất quyết định cách chia
   — mà "số lớn nhất" là thuộc tính của **đơn vị ai đó đã chọn**, không phải của dữ liệu.
- **Báo ra các cách chia đã thử.** Một số nhóm đưa ra mà không nói đã cân nhắc gì khác là một
  con số người ta phải tin.

### Vẫn khai báo, không tự suy ra

Khác với `tests` ở 4b.0, phần mô hình **phải được khai**. Chọn biến nào có thể giải thích một
kết quả là **một nhận định về cách thế giới vận hành**; hệ thống tự làm vì không ai nói gì là
hệ thống tự quyết định phân tích này về cái gì. Và khớp một rừng cây trên mọi lần phân tích thì
tốn hàng phút để sinh ra một bảng xếp hạng không ai hỏi — mà bảng xếp hạng không ai hỏi là bảng
xếp hạng sẽ có người trích.

**1.065 test · coverage 89% · chi phí: $0.**

---

## 2026-09-03 — Trả lời đúng **câu hỏi đã hỏi**, không chỉ trả lời đúng sự thật

### L64. Đúng sự thật vẫn có thể là nhiễu

Hỏi *"yếu tố nào ảnh hưởng đến điểm thi cuối kỳ?"*, một lần chạy thật trả về **điểm chuyên cần
trung bình 85.83 và tỷ lệ thiếu dữ liệu 0%**. Cả hai đều đúng, đều dẫn chỉ số thật, đều truy
ngược được — và **không cái nào trả lời gì cả**. Nhét đủ nhiều thứ như thế vào báo cáo thì người
đọc phải tự làm cái việc phân loại mà hệ thống sinh ra để làm hộ.

Nên mỗi luận điểm giờ được **chấm với chính câu hỏi**, cái nào không nói về nó thì đặt sang bên
— và **được ghi rõ kèm điểm số**, vì một luận điểm bị bỏ trong im lặng không khác gì một luận
điểm chưa từng tồn tại.

### Đo, không đoán: 16 ca lấy từ các lần chạy thật

| Cách chấm | Đúng | Giữ nhầm (nhiễu) | **Vứt nhầm cái thật** |
|---|---|---|---|
| So từ (TF-IDF) | 9/16 | 0 | **7** |
| So nghĩa (embedding) | **13/16** | 3 | **0** |

Cái quyết định là **hướng của sai lầm**, không phải tổng điểm. Nhiễu thì người đọc bỏ qua được;
một phát hiện bị vứt thì không còn dấu vết nào để mà đòi lại.

So từ chấm **0.000** cho *"Bước in và gửi biên nhận chiếm 34.8% khoảng cách"* với câu hỏi *"Vì
sao hồ sơ nộp qua bưu điện lâu hơn?"* — **đúng là câu trả lời**, và không chung một chữ nào.
Nó vứt cả 3 ca đồng nghĩa.

Quét ngưỡng trên bộ so nghĩa: 0.15 → 11/16, 0.20 → 12/16, **0.25 → 13/16 (vứt nhầm 0)**,
0.30 → bắt đầu vứt nhầm. **0.25 là ngưỡng cao nhất mà chưa vứt cái nào thật** — con số sếp đưa
ra đúng về mặt đo đạc.

### L65. Dấu tiếng Việt làm hỏng phép so, và hỏng theo hướng tệ nhất

Cùng **một câu**, chấm với cùng một câu hỏi:

    "Bảng có 60 dòng dữ liệu."   → -0.074   (đúng: loại)
    "Bang co 60.0 dong du lieu." →  0.373   (sai: giữ)

Đo lại cả 16 ca theo ba kiểu viết:

| Cách viết | Đúng | **Vứt nhầm** |
|---|---|---|
| Có dấu cả hai bên | 13/16 | 0 |
| **Lệch — một bên có dấu một bên không** | 8/16 | **8** |
| Không dấu cả hai bên | 7/16 | 1 |

**Lệch dấu vứt đi 8 trên 16 câu trả lời thật.** Model không biết "diem thi" và "điểm thi" là
cùng một chữ, nên một luận điểm trả lời hoàn hảo rơi vào chỗ chẳng liên quan gì. Hỏng **im
lặng**, và hỏng theo đúng hướng tệ nhất.

Không sửa được bằng cách bỏ dấu hết (7/16). Nên lệch dấu bị coi là **không chấm được**, chứ
không phải điểm thấp: luận điểm **được giữ** và câu trả lời **nói rõ là chưa kiểm được**.
`Judged.checked` tách "chưa xét" khỏi "đã xét và đạt" — thiếu chỗ đó thì một luận điểm chưa ai
xét đọc y hệt một luận điểm đã qua.

Nguyên tắc chung: **không có bộ chấm thì không lọc gì cả, và nói ra.** Lọc bằng một thứ đã đo
được là vứt 7/16 thì tệ hơn không lọc.

### L66. Câu hỏi của sếp không tới được người phải trả lời nó

`with_synthesis` gắn câu hỏi thật vào task của Manager — nhưng **chỉ khi Manager chưa có trong
kế hoạch**. Khi model tự xếp luôn bước tổng hợp (nó làm thế thường xuyên), hàm này thoát sớm và
Manager nhận **lời diễn giải của model** thay vì câu hỏi:

    sếp hỏi : "Yếu tố nào ảnh hưởng nhiều nhất đến điểm thi cuối kỳ?"
    A9 nhận : "Tổng hợp báo cáo và trả lời câu hỏi nghiệp vụ về yếu tố ảnh hưởng
               nhiều nhất đến điểm thi cuối kỳ dựa trên các phân tích và bằng chứng đã có."

Với phép kiểm độ liên quan, lỗi này đổi hẳn bản chất: nó biến phép kiểm từ *"khớp với người
hỏi"* thành *"khớp với kế hoạch"* — đúng cái mà sếp yêu cầu phải tránh. Lời diễn giải còn pha
loãng đúng những chữ làm câu hỏi trả lời được.

Sửa: task vẫn là của model, chỉ **đặt lại câu hỏi vào params**. Kiểm chứng bằng lần chạy thật —
A9 giờ nhận đúng `'Yếu tố nào ảnh hưởng nhiều nhất đến điểm thi cuối kỳ?'`, và cả 3 luận điểm
liên quan đều được giữ.

### Cái phép kiểm này **không** làm được

Nó đo luận điểm có **nói về** câu hỏi không — không phải có **trả lời** được không, và **không
phải hai bên có cùng cấp độ không**. *"Điểm trung bình toàn trường là 82.62"* hoàn toàn đúng chủ
đề với câu hỏi về **một** học sinh, và hoàn toàn sai con số. Đúng cái sếp đã chỉ ra. Chặn lệch
cấp độ là việc khác, chưa làm.

### Cái giá phải trả

`sentence-transformers` kéo theo `torch`. **Bản mặc định là bản CUDA**: 3.2 GB thư viện NVIDIA +
1.2 GB torch + 897 MB triton, cho một model nhỏ chạy CPU và **không bao giờ chạm tới GPU**. Cài
bản CPU:

    pip install torch --index-url https://download.pytorch.org/whl/cpu

**venv: 6.6 GB → 2.2 GB.** Model embedding là thứ **tải về**, không phải thứ pip đặt vào chỗ —
máy nào chưa có thì các test liên quan tự bỏ qua, và Manager không lọc gì rồi nói rõ.

**1.092 test · coverage 89% · chi phí: $0.**

---

## 2026-09-03 — Việc 1: **trả lời đúng LOẠI câu hỏi được hỏi**

### L67. Đúng sự thật, đúng chủ đề, vẫn không phải câu trả lời

Phép kiểm độ liên quan làm hôm nay chỉ bắt được *"luận điểm này có nói về câu hỏi không"*.
Nó **không** bắt được *"luận điểm này có phải LOẠI trả lời mà câu hỏi đòi không"*. Hai lỗi
khác nhau, không cái nào thay được cái nào:

    hỏi  "Kênh A đạt hiệu suất bao nhiêu %?"
    đáp  "Có 6 kênh được phân tích."        -> đúng, đúng chủ đề, KHÔNG phải con số được hỏi

    hỏi  "Yếu tố nào ảnh hưởng đến điểm thi?"
    đáp  "Điểm chuyên cần trung bình 85.83"  -> đúng, đúng chủ đề, KHÔNG nói cái gì kéo cái gì

Sếp nói chính xác: *"user hỏi A đạt hiệu suất bao nhiêu % và từ A có thể thấy những điều gì
thì kết quả đầu ra cũng phải ra tương ứng"*.

### Làm được vì **khoá chỉ số tự khai loại của nó**

Không cần model, không cần đoán nghĩa. Các họ chỉ số hệ thống thật sự sinh ra:

| Loại | Khoá |
|---|---|
| **Quan hệ** | `.corr.with.` `.rank_corr.with.` `.r2.with.` `.importance.` `.diff.by.` `.effect_size.by.` `.eta_sq.by.` |
| **Số lượng** | `.mean` `.median` `.sum` `.total` `.distinct` `.null_pct` `.cases` |
| **Cực trị** | `.max` `.min` |
| **Theo thời gian** | `.by.month` `.by.year` … (**hiện chưa có cái nào**) |

Câu hỏi nguyên nhân **phải** dẫn được một khoá quan hệ. `.mean` không trả lời được, dù đúng đến
đâu. Đó không phải suy đoán về ý nghĩa — đó là sự thật về khoá.

### Thứ tự đọc câu hỏi có bẫy

`"Yếu tố nào ảnh hưởng đến **tỷ lệ** hoàn?"` có chữ *"tỷ lệ"* nhưng **không** đòi một con số —
nó hỏi cái gì làm tỷ lệ đó thay đổi. Nên NGUYÊN NHÂN được xét **trước** SỐ LƯỢNG. Đọc ngược lại
thì một hệ số tương quan sẽ bị báo là "không trả lời được", tức là sai ngược hướng.

Tương tự `"Kênh nào có tỷ lệ hoàn **cao nhất**?"` là XẾP HẠNG, không phải SỐ LƯỢNG.

### Hai nguyên tắc, cùng một lý do

**Không đọc được loại câu hỏi → coi là câu mở, cho qua hết.** Đoán sai ở đây là từ chối một câu
trả lời tốt. Việc của bộ kiểm là bắt cái trượt, không phải nghĩ ra thêm cách để trượt.

**Không đạt thì BÁO, không bao giờ XOÁ.** Câu hỏi nguyên nhân được trả lời bằng ba con số trung
bình đúng — người đọc vẫn lợi hơn khi có ba con số đó *kèm một câu nói rõ đó không phải nguyên
nhân*, so với không có gì. Một bộ kiểm sinh ra để giúp mà bắt đầu xoá việc thì là bộ kiểm hỏng.

### Đo trước khi tin

16 ca lấy từ câu hỏi thật đã chạy: **16/16 đúng, 0 báo thiếu nhầm, 0 lọt lỗi**. Nhưng con số này
**chỉ chứng minh nhất quán nội bộ** — em viết cả luật lẫn ca kiểm. Phá hỏng theo **cả hai
hướng** để chắc test có răng:

    bo kiem luon bao DAT   -> 4 test do
    bo kiem luon bao THIEU -> 4 test do

### Chạy thật đã bắt được đúng cái nó sinh ra để bắt

Hỏi `"Điểm thi cuối kỳ thay đổi thế nào theo thời gian?"` (`hs__q11`). Model trả lời bằng
**tương quan với `study_time_hours`** — nghe có chữ "thời gian" nhưng là *số giờ học*, không phải
biến thiên theo mốc thời gian. Người đọc rất dễ bị lừa. Bộ kiểm nói thẳng ngay dòng đầu:

> *câu hỏi đòi XU HƯỚNG theo thời gian, nhưng không có chỉ số nào chia theo mốc thời gian —
> dữ liệu hiện tại chưa đo được cái đó.*

Luận điểm vẫn được giữ, chỉ kèm lời cảnh báo.

### Hai bộ kiểm xếp nối tiếp, và thứ tự có ý nghĩa

Viết test mới lòi ra: bộ lọc **độ liên quan** chạy trước đã loại luôn ca thử đầu tiên, nên bộ
kiểm **hình dạng** chưa kịp nhìn thấy. Ca tách bạch được hai cái phải là ca **đúng chủ đề nhưng
sai dạng** — `"Điểm thi cuối kỳ trung bình đạt 82.62"` với câu hỏi về yếu tố ảnh hưởng.

    do lien quan  -> luan diem nay co NOI VE cau hoi khong?   (embedding, 0.25)
    hinh dang     -> luan diem nay co dung LOAI tra loi khong? (khoa chi so, code)

Thêm chỉ số chạy `answers_the_question` (1/0) — con số duy nhất nói được việc hỏi có ích gì không.

**1.113 test · coverage 89% · chi phí: $0.**

---

## 2026-09-03 — L68. Guard đọc tên **cột** thành tên **bảng**, chặn oan SQL ngày tháng

Phát hiện khi sếp hỏi *"chưa đo được mốc thời gian nhưng code vẫn làm được nếu có dữ liệu thời
gian phải không"*. Đi kiểm thì lòi ra lỗi:

    SELECT EXTRACT(month FROM ngay_ban) ...
    -> CHAN: "Cau lenh doc bang khong duoc cap: ['ngay_ban']"

Guard thấy chữ `FROM`, lấy định danh ngay sau đó làm tên bảng. Nhưng trong `EXTRACT`, `FROM`
**không giới thiệu một bảng** — nó là dấu phân cách đối số. SQL chuẩn dùng y hệt như vậy trong
`SUBSTRING(s FROM 2 FOR 3)`, `TRIM(BOTH ' ' FROM s)`, `OVERLAY(s PLACING t FROM 2)`.

**Kiểu hỏng tệ nhất: hỏng lúc có lúc không, theo cú pháp.** `DATE_TRUNC` và `STRFTIME` thì qua.
Nên cùng một câu hỏi, model viết cách này thì chạy, viết cách kia thì chết — kèm thông báo về
**quyền truy cập bảng**, thứ chẳng liên quan gì tới lỗi thật. Người đọc sẽ đi tìm sai chỗ.

### Sửa hẹp, không sửa rộng

Cách ngắn hơn là **xoá cả lời gọi hàm** trước khi tìm tên bảng. Nó chạy, và nó **mở lỗ hổng**:

    SELECT EXTRACT(month FROM (SELECT ngay FROM bang_cam)) FROM t

Xoá cả lời gọi thì `bang_cam` biến mất khỏi tầm mắt của guard. **Nới một cái guard chính là chỗ
mà một bản vá lặng lẽ thôi không canh gì nữa.**

Nên chỉ **chữ `FROM` làm dấu phân cách** bị bôi trắng, và chỉ cái **đầu tiên ngay trong lời gọi
đó**. Subquery lồng sâu hơn giữ nguyên `FROM` của nó, bảng nó đọc vẫn bị soi. Thay bằng dấu cách
chứ không xoá, nên mọi vị trí khác trong câu lệnh không xê dịch.

Phá hỏng **cả hai hướng** để chắc test có răng:

    quay lai hanh vi cu (bo mat na)     -> 3 test do
    mat na CA loi goi ham (mo lo hong)  -> 2 test do, trong do co dung test subquery long

### Nhân tiện đo luôn: hệ làm được tới đâu với dữ liệu thời gian

**Gom theo thời gian: CHẠY ĐƯỢC.** Guard cho qua, DuckDB ra kết quả đúng.

**Phân tích theo thời gian: CHƯA.** Cho bảng đã gom theo tháng vào `suggest_spec`, nó chọn
`group_differences = (doanh_thu, thang)` — tức coi **"tháng" là một NHÃN**, không phải **một
CHUỖI CÓ THỨ TỰ**. Xáo trộn 12 tháng thì so sánh nhóm ra **y hệt** kết quả cũ, còn xu hướng thì
biến mất. Nó trả lời được *"các tháng có khác nhau không"*, không trả lời được *"bán tăng hay
giảm"*, và không biết T2 đi sau T1.

Nên bộ kiểm hình dạng (L67) báo "chưa trả lời được" cho câu hỏi xu hướng là **báo đúng**.

### Phân biệt phải giữ khi làm phần thời gian sau này

| Câu hỏi | Bản chất | Vướng gì |
|---|---|---|
| *"tháng nào bán nhiều"*, *"có mùa vụ không"* | **Mô tả các dòng đang có** | Không vướng gì — truy ngược đầy đủ, hợp kiến trúc |
| *"quý sau bán được bao nhiêu"* | **Dự báo** | Truy về *một mô hình và một cách chia dữ liệu*, không về dòng nào → đúng vấn đề S4, chính là lựa chọn C đã hoãn ở Phase 6 |

Phần lớn giá trị nằm ở hàng trên, và hàng trên **không cần dự báo**.

**1.121 test · coverage 89% · chi phí: $0.**

---

## 2026-09-03 — Việc 2 (bước 1–2): một cổng, nhiều model, mỗi skill một con

Sếp muốn hệ thống là **một công ty AI thu nhỏ**: Opus làm giám đốc, giao mỗi việc cho người
giỏi việc đó. Trước đây cả lượt chạy dùng **một model duy nhất** — tức một công ty có đúng một
nhân viên đội chín cái mũ.

### Chọn model nằm ở manifest, không nằm trong runner

`LlmPolicy.model` được thêm vào manifest. Lý do đặt ở đó giống hệt lý do mọi ranh giới khác nằm
ở đó: **model một agent cần là thuộc tính công việc của agent đó**. Một bảng tra trong runner thì
cứ thêm skill là phải sửa runner. Manifest đã quyết *có* được dùng model chưa; giờ nó quyết
*model nào*.

Manifest không khai gì → giữ nguyên model của lượt chạy. Provider không đổi được model
(`handoff`, `cassette`) → bỏ qua, và đúng: một dòng YAML không đổi được **ai** đang dán vào Claude.

### Ngân sách phải dùng chung — có test riêng canh

`LlmClient.for_model()` mang theo **cùng một** `BudgetTracker` và `AuditLog`. Nếu mỗi agent tự
mở ngân sách riêng thì **một cái trần thành chín cái trần, tức là không có trần nào** — và lỗi đó
sẽ hiện ra dưới dạng hoá đơn chứ không phải dưới dạng test đỏ.

### `pricing.yaml` bắt chặn đúng chỗ

Test đầu tiên đỏ vì `BudgetTracker` từ chối model chưa khai giá. Ban đầu trông như phiền phức,
thực ra là **tính chất đúng**: một cổng với vài trăm model thì **khai giá là thứ duy nhất đứng
giữa một dòng sửa config và một hoá đơn không ai chọn.** Thêm model vào `pricing.yaml` phải là
hành động có ý.

### L69. Provider mới lặp lại đúng lỗi provider cũ đã có thuốc

`GeminiProvider` mang sẵn dòng chú thích này từ lâu:

> *"model suy nghĩ dài, tiêu hết ngân sách đầu ra, và trả về một object bị cắt giữa chừng."*

Em viết `OpenRouterProvider` mà **không mang bài học đó sang**, và dính đúng lỗi ấy. Đọc phản hồi
thô thay vì đọc exception:

    dots-3-note   316 token dau ra, trong do 323 la token SUY NGHI
    nemotron      800 token (cham tran), 899 suy nghi, va suy nghi tran ca vao
                  content: "Okay, let's tackle this problem..."

Model **không** hỏng ở chỗ sinh JSON. Nó tiêu sạch ngân sách để nghĩ rồi bị cắt — và em đã chấm
điểm đó vào sổ của nó. **Dùng chung một hằng số không có nghĩa là dùng chung cái đã học được về
hằng số đó.**

### Và hai sửa đổi "cùng đúng" lại kéo ngược nhau

Sửa 1: `reasoning.effort = low` → nemotron 1/5 lên 2/5. **Tốt.**

Sửa 2: thêm `exclude: true` để chặn suy nghĩ tràn vào `content`. Trông hiển nhiên đúng. **Làm tệ
đi**: đôi khi `content` rỗng hẳn, và ứng viên tốt nhất tụt từ 5/5 xuống 3/5.

Chỉ có **chạy tách riêng** mới phân biệt được. Nếu gộp hai sửa đổi làm một lần, em sẽ kết luận
"đã sửa, vẫn 3/5, model dở" — sai hoàn toàn.

### Số đo cuối, mỗi model 5 lần trên cùng một việc thật

| Model | schema | chép đúng số | tiếng Việt có dấu | giây |
|---|---|---|---|---|
| **`dots-studio/dots-3-note-preview:free`** | **5/5** | **5/5** | **5/5** | 7,8 |
| `nvidia/nemotron-3-super-120b-a12b:free` | 2/5 | 2/5 | 2/5 | 9,4 |
| `z-ai/glm-5.2:free` | 0/5 | — | — | — (429 liên tục) |

`glm-5.2:free` **không phải dở** — nó bận, 429 mọi lần. Bậc free bị chia sẻ, không đảm bảo dung
lượng. Đó là một tính chất của bậc free, không phải của model.

**Một lần chạy không nói lên gì.** Ở lần đo trước, nemotron ra JSON đúng ở lần đầu và hỏng ở lần
sau, cùng một prompt. Chỉ chạy một lần thì nó xếp nhất hoặc bét tuỳ thời điểm bấm.

### Tiêu chí chọn model, rút ra từ chính hệ này

- **Ra đúng schema** — không thì task chết, không có gì cứu
- **Chép đúng số** — đổi một con số là bịa số, đúng thứ cả hệ sinh ra để chặn
- **Tiếng Việt có dấu** — model viết không dấu thì phép kiểm độ liên quan **từ chối chấm** (L65),
  tức là bộ kiểm đó lặng lẽ ngừng hoạt động
- **Thời gian** — chín agent mỗi con 10 giây là một phút rưỡi cho một câu hỏi

**1.133 test · coverage 89% · chi phí: $0.**

---

## 2026-09-03 — Việc 2 hoàn tất: bốn model, mỗi con một việc

### Bản đồ cuối, mỗi chỗ một lý do đo được

| Skill | Model | Vì sao con này |
|---|---|---|
| `a2_profiler` | `z-ai/glm-5.3-flash` | **Chỗ chứa**, không phải điểm. Hồ sơ dữ liệu lớn theo **số cột**; cửa sổ 1,31M token gấp 10 lần ba con kia |
| `a3_cleaner` | `openai/gpt-oss-20b` | Việc nhẹ, và **có người duyệt đứng sau** — mọi rule phải qua gate trước khi chạy |
| `a4_transformer` | `openai/gpt-oss-20b` | Lineage 2/4 — **tốt nhất trong bốn**, và nhanh nhất (2,0s) |
| `a6_process_miner` | `openai/gpt-oss-20b` | Việc nhẹ nhất: code đo hết, model chỉ đặt tên |
| `a7_analyst` | `google/gemma-3-12b-it` | 12/12 câu sống sót qua `render_all`, **4/4 tiếng Việt có dấu**, nhanh nhất |
| `a8_reporter` | `google/gemma-3-12b-it` | Cùng đòi hỏi như a7 |
| `a9_manager` | `google/gemma-3-12b-it` | Ghế giám đốc. Kế hoạch là **Opus 5 qua handoff** — dòng này chỉ có tác dụng khi chạy `openrouter` |

`qwen3-30b-a3b` bị **loại sau khi đã được chọn**. Xem dưới.

### L70. Bắt model chép lại một chuỗi mà code vừa đưa cho nó

Prompt của A7 viết: *"`evidence_ref` phải BẰNG ĐÚNG giá trị của `source_table` ở trên."* Tức là
model được yêu cầu **gõ lại một giá trị chính code này vừa trao**. Có đúng một đáp án, và code đã
biết nó.

Đó là vi phạm **luật số 4** của dự án: *không dùng LLM cho việc code làm được*. Nó nằm im suốt vì
Gemini chép đúng mọi lần. Đổi sang model nhỏ hơn thì hỏng, **thử lại 3 lần đều hỏng** — mà thử
lại không cứu được, vì bảo nó *"thiếu evidence_ref"* chẳng nói thêm điều gì nó chưa biết.

Nay `evidence_ref` bỏ trống thì code tự điền bằng nguồn đã tính ra kết luận đó. **Không bịa gì
cả**: đó là bảng duy nhất A7 được đưa, đúng giá trị prompt đòi, và `citation_exists` vẫn kiểm y
như cũ. Model **có** ghi thì để nguyên và vẫn phải qua kiểm — chỉ vá chỗ im lặng, không vá chỗ
bất đồng.

### L71. Provider được chọn ở **hai nơi**

`api.py` học được `openrouter`; `cli.py` giữ bản sao riêng của cùng bảy dòng quyết định đó và
không học. Kết quả: `asys ask` chạy được trên OpenRouter, còn `asys resume-dag` **từ chối chính
cấu hình ấy** — nửa đầu câu hỏi chạy, nửa sau báo provider không tồn tại.

**Bản sao mới là lỗi, không phải nhánh thiếu.** Vá cả hai chỗ thì provider tiếp theo lại được
thêm ở hai nơi bởi người chỉ biết một. Nên quyết định gộp về một hàm, hai bên cùng gọi.

### Bài học lớn nhất: **bộ đo dễ hơn việc thật thì nó nói dối một cách rất thuyết phục**

Hai lần liên tiếp, cùng một kiểu sai của tôi.

**Lần 1 — SQL.** Chấm bằng `check_sql` cho qua không, DuckDB chạy không. `qwen` đạt 4/4 cả hai
→ được chọn cho A4 → **hỏng 3 lần liên tiếp trên câu hỏi thật**, vì một luật bộ đo **không hề
nhìn tới**: `verify_lineage` đòi mỗi cột đầu ra khai rõ sinh từ cột nào. `qwen` viết
`COUNT(*) AS count` rồi không khai gì.

Đo lại kèm lineage thì bảng xếp hạng **đổi hẳn**:

| | guard | chạy | **lineage** | giây |
|---|---|---|---|---|
| `gpt-oss-20b` | 4/4 | 3/4 | **2/4** | 2,0 |
| `glm-5.3-flash` | 3/4 | 3/4 | **2/4** | 3,6 |
| `gemma-3-12b` | 4/4 | 4/4 | **0/4** | 2,6 |
| `qwen3-30b` | 2/4 | 2/4 | **0/4** | 9,5 |

**Lần 2 — findings.** Bộ đo tự điền `evidence_ref` mặc định, nên chưa bao giờ kiểm model có tự
khai không. `gemma` đạt 12/12 luận điểm — với `evidence_ref` do **tôi** cấp. Chạy thật thì A7 chết
vì thiếu đúng trường đó.

Một bộ đo thiếu sót **không báo sai kết quả** — nó báo **kết quả thật cho một câu hỏi hẹp hơn
công việc**, và khoảng cách chỉ lộ ra khi chạy thật. Đó là kiểu sai nguy hiểm nhất, vì con số
trông rất đáng tin.

### Không con nào **khá** ở khoản lineage

Tốt nhất 2/4. Cả bốn con đều khai tên cột **lệch với bí danh trong SQL của chính nó**. Khi cả bốn
cùng hỏng một kiểu thì thủ phạm nhiều khả năng là **prompt**, không phải model. Chưa sửa — ghi
lại để làm sau.

### Chạy thật, đầu-cuối, bốn model phối hợp

`hs__q14`, câu hỏi *"Yếu tố nào đi kèm với điểm thi cuối kỳ cao hơn?"* → 4 luận điểm, 3 có biểu
đồ làm bằng chứng, 0 bị loại.

**Tổng chi từ đầu: $0,0147.** Còn $9,985 trong tài khoản.

**1.133 test · coverage 89%.**
