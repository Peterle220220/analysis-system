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
