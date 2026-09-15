# BUILD SPEC v3 — Hệ thống xử lý dữ liệu Multi-Agent (Orchestrator + Worker Agents)

> **Đối tượng đọc:** Claude Code.
> **Nhiệm vụ:** Xây dựng hệ thống theo đúng spec này. Đọc hết file trước khi viết dòng code đầu tiên.
> **Ngôn ngữ code:** Python 3.11+. **Comment/docstring:** Tiếng Anh. **Báo cáo cho user:** Tiếng Việt.
>
> **Thay đổi v2 → v3 (chốt C1–C14 + bản sửa C3/C4):** môi trường WSL2 distro trên ổ D · **dữ liệu tách khỏi git repo** (`~/analysis-data`, `~/analysis-runs`) · package `analysis_system` (src-layout) · `tasks.py` là task runner, `Makefile` chỉ là vỏ · manifest dùng scheme tầng logic `layer://` · **golden fixture = dữ liệu thật BPI Challenge 2019**, không tự sinh · định nghĩa `canonical_hash` cho S1 · human gate 2 bước · `config/pricing.yaml` · test AST chặn I/O đi tắt.
>
> **Thay đổi v1 → v2:** chốt toàn bộ tham số Mục 2 · tách `manager_model`/`worker_model` · sửa cách làm PII · **thêm tầng A0 Router + họ Extractor (E1–E4) cho dữ liệu phi cấu trúc** · môi trường WSL2, Docker dời sang Phase 3 · phase đánh số lại.

---

## 0. QUY TẮC LÀM VIỆC CHO CLAUDE CODE

Ràng buộc bắt buộc. Vi phạm = làm lại.

1. **Không tự ý mở rộng phạm vi.** Ý tưởng thêm → ghi `NOTES.md`, không code.
2. **Làm đúng thứ tự Phase** (Mục 14). Không nhảy phase. Mỗi phase phải chạy được và pass Definition of Done.
3. **Không dùng LLM cho việc code thuần làm được.** Xem Mục 4. Đây là nguyên tắc số 1.
4. **Mọi hàm public phải có type hint đầy đủ và docstring.**
5. **Không hardcode secret, path tuyệt đối, magic number.** Tất cả vào `config/`.
6. **Mỗi module mới phải có test tương ứng.** Không test = chưa xong.
7. **Không cài dependency ngoài Mục 3** nếu chưa hỏi.
8. **Chạy `python tasks.py check` sạch trước khi báo cáo hoàn thành.** (`make check` chỉ là vỏ gọi lại lệnh này.)
9. Gặp điểm mơ hồ → **dừng lại hỏi**, không tự suy diễn.

---

## 1. MỤC TIÊU

Hệ thống xử lý dữ liệu end-to-end, trong đó:

- Một **AI Manager (Orchestrator)** làm đầu não: lập kế hoạch, phân việc, kiểm tra kết quả, quyết định tiếp/lặp/dừng.
- Nhiều **Worker Agent** nhỏ, mỗi agent một tác vụ, hoạt động **trong boundary được cấp** và không được vượt.
- Nhận **cả dữ liệu có cấu trúc lẫn phi cấu trúc** (PDF, ảnh scan, audio/video, email).
- Đầu ra phục vụ **Business Analysis**, trọng tâm **process mining** trên event log, tích hợp SAP Signavio.

### Tiêu chí thành công

| # | Tiêu chí | Cách đo |
|---|---|---|
| S1 | Chạy lại cùng input ra cùng output | Hash output 2 lần chạy phải trùng |
| S2 | Không agent nào vượt boundary | Audit log không có `BOUNDARY_VIOLATION` chưa xử lý |
| S3 | Resume được từ bước lỗi | Kill giữa chừng, chạy lại → tiếp từ task lỗi |
| S4 | Mọi kết luận truy ngược được về nguồn gốc | Mỗi finding có `evidence_ref`; dữ liệu từ PDF/ảnh/video phải có `source_locator` (trang, vùng, mốc thời gian) |
| S5 | Không vượt ngân sách | Job tự HALT khi chạm trần token/tiền/thời gian |
| S6 | Trích xuất kém chất lượng không lọt qua âm thầm | Bản trích xuất dưới ngưỡng confidence bắt buộc qua HUMAN GATE 0 |

---

## 2. THAM SỐ & BỐ CỤC — ĐÃ CHỐT
```yaml
deployment:      wsl2_venv          # Phase 0-3. Docker đóng gói ở Phase 3
os_host:         windows_11 + WSL2  # LÀM VIỆC HOÀN TOÀN TRONG WSL2
wsl_distro_path: D:\WSL\Ubuntu      # distro đặt trên ổ D. Không đặt gì lên ổ E
data_scale:      < 5_000_000 rows   # giữ duckdb kể cả khi vượt ngưỡng.
storage_engine:  duckdb             # Chỉ đổi Postgres nếu cần nhiều tiến trình ghi đồng thời
llm_provider:    anthropic
manager_model:   claude-opus-5      # gọi ít, quyết định plan → trả thêm tiền là đáng
worker_model:    claude-sonnet-5    # gọi nhiều, tác vụ hẹp, đã có schema ép output
dev_mode:        true               # true → ép cả hai về claude-sonnet-5 khi dev (cách tắt: README)
signavio_access: none               # A6 nhận event log qua lớp adapter (Mục 8)
pii_present:     yes                # bật masking theo cách ở Mục 12
ui_needed:       cli_only
python_package:  analysis_system    # src-layout. CLI = `python -m analysis_system.cli`
task_runner:     tasks.py           # nguồn chân lý. Makefile chỉ là vỏ mỏng gọi lại

input_formats:                      # ← quyết định phạm vi họ Extractor
  structured:   [csv, xlsx, parquet, json]     # Phase 0-2
  pdf:          true                            # Phase 5a
  image_scan:   true                            # Phase 5a
  audio_video:  true                            # Phase 5b
  document:     [docx, eml, msg, html]          # Phase 5a
```

### Bố cục trên đĩa — dữ liệu TÁCH khỏi git repo (bắt buộc)

| Đường dẫn | Nội dung | Trong git? |
|---|---|---|
| `~/projects/analysis-system/` | **chỉ code**: `src/`, `config/`, `prompts/`, `scripts/`, `tests/`, `tasks.py`, `Makefile`, `BUILD_SPEC.md` | Có |
| `~/analysis-data/` | `raw/ extracted/ staging/ clean/ mart/ profile/ validation/ artifacts/` | **Không** |
| `~/analysis-runs/` | `<run_id>/` — plan, state, audit, budget, gates | **Không** |

Lý do tách: không bao giờ có nguy cơ commit nhầm vài GB parquet, và dữ liệu di chuyển độc lập với code.

**Ràng buộc bắt buộc:**

1. Tất cả nằm trong filesystem WSL2. **TUYỆT ĐỐI không đặt ở `/mnt/c` hay `/mnt/e`** — I/O qua lớp dịch Windows↔Linux chậm nhiều lần, DuckDB đọc Parquet sẽ thấy rõ.
2. `config/settings.yaml` khai báo **đường dẫn từng tầng độc lập** (raw, extracted, staging, clean, mart, profile, validation, artifacts, runs). **Không suy ra từ một thư mục gốc chung.** Ràng buộc này cho phép sau này trỏ riêng `raw` sang ổ khác mà không sửa một dòng code.
3. **Kiểm tra lúc khởi động:** tầng nào trong `settings.yaml` không truy cập được → báo lỗi rõ ràng **bằng tiếng Việt** rồi thoát. **Không** tự tạo thư mục thay thế, **không** chạy tiếp với dữ liệu rỗng.
4. **Manifest không hardcode đường dẫn hệ thống** — dùng scheme tầng logic `layer://` (Mục 9).
5. Dùng `pathlib.Path` ở mọi nơi, không nối chuỗi đường dẫn.

**git:** `git init` tại `~/projects/analysis-system`. `.gitignore`: `.venv/`, `__pycache__/`, `*.duckdb`, `.env`. `BUILD_SPEC.md` copy vào repo và đưa vào commit đầu tiên.
## 3. TECH STACK (cố định) — MỞ THEO PHASE
**Quy tắc:** chỉ cài package khi tới phase cần nó. Không cài sớm.

### Lõi — Phase 0

```
python           >= 3.11
pydantic         >= 2.6      # data contract, validation
pydantic-settings            # config từ env/yaml
duckdb           >= 0.10     # storage/query engine
pandas           >= 2.2
pyarrow                      # parquet I/O
pandera          >= 0.19     # data quality test
structlog        >= 24.1     # structured logging
typer            >= 0.12     # CLI
pyyaml
rich

# dev
pytest, pytest-cov, ruff, mypy
```

### Bổ sung theo phase

| Phase | Package | Dùng cho |
|---|---|---|
| **Phase 1** | `anthropic >= 0.40`, `tenacity` | LLM client · retry/backoff |
| **Phase 2** | `matplotlib` | A8 vẽ biểu đồ PNG |
| **Phase 2** | `openpyxl` | A1 đọc xlsx · A8 xuất xlsx |
| **Phase 3** | `python-docx` | A8 xuất DOCX |
| — | *(xuất PDF)* | **hoãn** — chưa thêm thư viện nào |
| **Tầng 1** | `fastapi`, `uvicorn`, `python-multipart` | Dashboard điều hành. Đo trước khi cài: **4 gói mới** — pydantic và anyio đã có sẵn. So với 44 gói từng khiến diarization bị từ chối |

A8 ở Phase 2 chỉ cần Markdown + HTML + PNG là đủ đạt DoD.

### Extraction — Phase 5 (chỉ cài khi tới phase)

```
# Phase 5a — tài liệu & ảnh
filetype                     # nhận diện định dạng bằng magic bytes
pdfplumber                   # PDF có text layer: text + toạ độ + bảng
pypdfium2                    # render trang PDF → ảnh khi là bản scan
pytesseract + tesseract-ocr  # OCR; BẮT BUỘC cài gói ngôn ngữ `vie`
opencv-python-headless       # tiền xử lý ảnh: deskew, denoise, binarize
python-docx
extract-msg, mail-parser     # email .msg / .eml
selectolax                   # strip HTML

# Phase 5b — audio/video
ffmpeg (system package)      # tách audio khỏi video
faster-whisper               # ASR chạy local, miễn phí, hỗ trợ tiếng Việt
```

**Không dùng:** LangChain, LlamaIndex, CrewAI, AutoGen. Hệ thống tự viết orchestration để kiểm soát boundary hoàn toàn.
## 4. RANH GIỚI LLM ↔ CODE (nguyên tắc quan trọng nhất)

> **LLM quyết định. Code thực thi.**

| Việc | Ai làm | Lý do |
|---|---|---|
| Lập kế hoạch, chọn agent, thứ tự | **LLM** (Manager) | Cần suy luận |
| Nhận diện định dạng file | **Code** | Magic bytes, deterministic |
| Đề xuất rule làm sạch từ profile | **LLM** (A3) | Cần ngữ cảnh |
| **Thực thi** rule làm sạch | **Code** (rulebook) | Phải deterministic |
| OCR / ASR (đọc chữ, nghe tiếng) | **Code** (tesseract, whisper) | Rẻ hơn, chạy local |
| Map text đã trích vào schema đích | **LLM** (E1–E4) | Cần hiểu ngữ nghĩa |
| Tính chỉ số thống kê, KPI, cycle time | **Code** | Phải chính xác |
| Rút insight từ chỉ số | **LLM** (A7) | Cần diễn giải |
| Chấm PASS/FAIL data quality | **Code** (pandera) | Trọng tài phải khách quan |
| Viết diễn giải báo cáo | **LLM** (A8) | Cần ngôn ngữ |
| Render file báo cáo, chèn số liệu | **Code** (template) | LLM không được gõ lại số |

**Cấm tuyệt đối:**
- Đưa toàn bộ dataset vào prompt. LLM chỉ thấy **schema + thống kê tóm tắt + tối đa 20 dòng mẫu đã mask PII**.
- Cho LLM "đọc" trực tiếp PDF/ảnh khi OCR đã đủ tốt. Chỉ dùng vision model làm **fallback** khi OCR confidence thấp.

---

## 5. KIẾN TRÚC TỔNG THỂ

```
INTAKE (file bất kỳ)
   │
   ▼
A0 ROUTER ── phân loại bằng magic bytes (CODE, không LLM)
   │
   ├── có cấu trúc ──────────────► A1 INGEST
   │                                (csv/xlsx/parquet/json/sql)
   │                                      │
   └── phi cấu trúc ─► EXTRACTOR FAMILY   │
                        ├ E1 PDF          │
                        ├ E2 IMAGE/OCR    │
                        ├ E3 AUDIO/VIDEO  │
                        └ E4 DOCUMENT     │
                             │            │
                        ExtractionResult  │
                        (+ confidence     │
                         + source_locator)│
                             │            │
                    ┌────────┘            │
                    ▼                     │
            ★ HUMAN GATE 0                │
          (duyệt bản conf thấp)           │
                    │                     │
                    └──────────┬──────────┘
                               ▼
                        data/staging/
                               │
        A2 PROFILER ───────────┤
        ★ HUMAN GATE 1 (duyệt rule làm sạch)
        A3 CLEANER ────────────┤
        A5 VALIDATOR ──────────┤
        A4 TRANSFORMER ────────┤
        A6 PROCESS MINER ──────┤
        A7 ANALYST ────────────┤
        ★ HUMAN GATE 2 (duyệt kết luận)
        A8 REPORTER ───────────► artifacts/

        Toàn bộ do AI MANAGER điều phối.
        Manager KHÔNG đọc/ghi file dữ liệu — chỉ thấy DataRef + metrics.
```

---

## 6. CẤU TRÚC THƯ MỤC
### Repo — `~/projects/analysis-system/` (chỉ code, vào git)

```
analysis-system/
├── Makefile                     # vỏ mỏng: mỗi target gọi `python tasks.py <target>`
├── tasks.py                     # NGUỒN CHÂN LÝ: check/lint/typecheck/test/run/setup/clean
├── pyproject.toml               # package = analysis_system (src-layout)
├── README.md
├── NOTES.md                     # quyết định thiết kế, giả định, ý tưởng ngoài phạm vi
├── BUILD_SPEC.md                # bản copy của spec này
│
├── config/
│   ├── settings.yaml            # đường dẫn TỪNG TẦNG độc lập (Mục 2)
│   ├── budget.yaml              # Phase 1
│   ├── pricing.yaml             # Phase 1 — giá model, có last_verified
│   └── manifests/               # boundary từng agent — 1 file/agent, dùng layer://
│       ├── a0_router.yaml       # Phase 5
│       ├── a1_ingest.yaml
│       ├── ...
│       └── e1_pdf.yaml          # Phase 5
│
├── prompts/                     # tách khỏi code, version như code
│
├── scripts/
│   └── make_fixture.py          # cắt fixture bất biến từ file BPI 2019 gốc
│
├── src/analysis_system/
│   ├── __init__.py
│   ├── cli.py                   # typer entrypoint → python -m analysis_system.cli
│   ├── core/                    # hạ tầng dùng chung, không nghiệp vụ (tái cấu trúc DDD, Phase 2)
│   │   ├── settings.py          # nạp settings.yaml, resolve layer:// → Path
│   │   ├── storage.py           # I/O DUY NHẤT của hệ thống
│   │   ├── hashing.py           # canonical_hash — nền tảng S1 (Mục 13)
│   │   ├── boundary.py          # Phase 1 — 3 lớp cưỡng chế
│   │   └── audit.py · budget.py · pii.py      # Phase 1
│   ├── models/                  # Phase 1 — hợp đồng dùng chung (trước tái cấu trúc DDD: contracts/)
│   │   ├── base.py              # ScopeToken, DataRef, TaskRequest, TaskResult
│   │   ├── agents.py            # I/O contract từng agent
│   │   └── extraction.py        # ExtractionResult, SourceLocator  (Phase 5)
│   ├── manager/                 # Phase 1
│   │   └── planner.py · dispatcher.py · verifier.py · state.py
│   ├── agents/                  # Phase 1+
│   │   ├── base.py              # BaseAgent — enforce boundary
│   │   ├── a0_router.py … a8_reporter.py
│   │   ├── extractors/          # Phase 5: base.py, e1_pdf.py … e4_document.py
│   │   └── adapters/            # nguồn event log: base.py, generic_csv.py
│   ├── domains/                 # nghiệp vụ theo lĩnh vực (tái cấu trúc DDD, Phase 4-7)
│   │   ├── data_ingestion/      # nạp, đọc, làm sạch và quản lý bộ dữ liệu
│   │   │   ├── rulebook.py      # registry rule làm sạch (code thuần)
│   │   │   └── validation.py    # pandera schema + business rule
│   │   └── visualization/       # biểu đồ, Tự phân tích, bảng điều khiển, báo cáo
│   │       └── reporting.py     # render báo cáo bằng template
│   ├── services/                # LOGIC THỰC — Phase 0 viết ở đây, Phase 1 BỌC lại
│   │   └── llm.py               # Phase 1
│   └── pipeline/                # Phase 0 ONLY — driver tuần tự, Phase 1 Manager thay thế
│       └── run.py
│
└── tests/
    ├── fixtures/
    │   ├── bpi19_slice.csv      # NGUỒN CHÂN LÝ — bất biến, commit vào git
    │   ├── FIXTURE.md           # số case/event, activity, khoảng thời gian, vấn đề quan sát được
    │   └── pii_sample.csv       # ~20 dòng tự chế, CHỈ để unit test core/pii.py (Phase 1)
    ├── golden/expected/         # kết quả kỳ vọng của pipeline
    └── unit/ · contract/ · regression/
```

### Ngoài repo — không vào git

```
~/analysis-data/{raw,extracted,staging,clean,mart,profile,validation,artifacts}/
~/analysis-runs/<run_id>/{plan.json,state.json,audit.jsonl,budget.json,gates/}
```

**`raw/` là BẤT BIẾN** — không bao giờ ghi đè.
## 7. DATA CONTRACTS

Mọi giao tiếp Manager ↔ Agent đi qua các model này. Không ngoại lệ.

```python
# src/analysis_system/models/base.py

class ScopeToken(BaseModel):
    """Quyền hạn Manager cấp cho agent trong 1 lần gọi. Agent không tự tạo được."""
    run_id: str
    task_id: str
    agent_id: str
    allow_read:  list[str]          # glob paths
    allow_write: list[str]
    allow_tools: list[str]
    params: dict[str, Any]          # tham số đã được Manager duyệt
    limits: Limits
    issued_at: datetime
    expires_at: datetime

class DataRef(BaseModel):
    path: str
    format: Literal["parquet", "csv", "json", "duckdb_table", "blob"]
    content_hash: str               # sha256 — nền tảng của idempotency
    row_count: int | None
    schema_version: str

class TaskRequest(BaseModel):
    scope: ScopeToken
    input_refs: list[DataRef]       # TRỎ tới dữ liệu, KHÔNG nhúng dữ liệu
    instruction: str

class TaskResult(BaseModel):
    task_id: str
    agent_id: str
    status: Literal["OK", "FAILED", "HALTED_BUDGET",
                    "BOUNDARY_VIOLATION", "NEEDS_REVIEW"]
    output_refs: list[DataRef]
    metrics: dict[str, float]       # rows_in, rows_out, duration_s, tokens, cost
    payload: dict[str, Any]
    evidence: list[EvidenceRef]
    error: ErrorDetail | None
```

```python
# src/analysis_system/models/extraction.py   (Phase 5)

class SourceLocator(BaseModel):
    """Chỉ chính xác chỗ một giá trị được lấy ra. Nền tảng của tiêu chí S4."""
    file_ref: str
    page: int | None = None          # PDF, ảnh nhiều trang
    bbox: tuple[float,float,float,float] | None = None   # vùng trên trang
    char_span: tuple[int,int] | None = None              # văn bản
    time_start_s: float | None = None                    # audio/video
    time_end_s: float | None = None
    speaker: str | None = None

class ExtractionResult(BaseModel):
    source_ref: DataRef
    extractor_id: str
    records: list[dict[str, Any]]
    confidence: float                       # 0..1, tổng thể
    field_confidence: dict[str, float]      # per field
    locators: list[SourceLocator]
    needs_review: bool                      # True khi dưới ngưỡng
    method: str                             # "text_layer" | "ocr" | "vision" | "asr"
    warnings: list[str]
```

**Quy tắc về `DataRef.path`:** luôn ghi dưới dạng **URI tầng logic** (`staging://po_events.parquet`), không bao giờ là đường dẫn hệ thống. `settings.py` chịu trách nhiệm resolve sang `Path` thật theo `config/settings.yaml`. Nhờ vậy `content_hash` và state file không phụ thuộc vị trí thư mục trên máy.

**Quy tắc:** Manager nhận `TaskResult` → validate Pydantic → fail thì **reject ngay**, không cố diễn giải.

---

## 8. AGENT REGISTRY — KỸ NĂNG & BOUNDARY

Mỗi agent = 1 class kế thừa `BaseAgent`, 1 manifest YAML, 1 prompt file (nếu dùng LLM).

> **Ghi chú đường dẫn:** các bảng dưới viết `data/<tầng>/**` cho dễ đọc. Trong **manifest thật** bắt buộc dùng scheme tầng logic — `staging://**`, `clean://**`, … (Mục 2, Mục 9).

### A0 — ROUTER *(Phase 5)*

| Mục | Nội dung |
|---|---|
| **Nhiệm vụ** | Phân loại file đầu vào, định tuyến tới A1 hoặc extractor phù hợp |
| **Kỹ năng cần có** | Nhận diện định dạng bằng **magic bytes** (không tin đuôi file) · phát hiện PDF **có/không có text layer** · phát hiện file hỏng, mã hoá, rỗng · đọc metadata (số trang, thời lượng, codec, kích thước) · phát hiện encoding & delimiter cho text · tính content hash · sinh **routing plan** |
| **Dùng LLM?** | **Không.** 100% code |
| **Output** | `RoutingPlan`: `[{file, detected_type, target_agent, est_cost, warnings}]` |
| **ALLOW** | read: `data/raw/**` · write: `runs/<run_id>/routing.json` |
| **DENY** | trích xuất nội dung · sửa file · ghi vào `raw/` |
| **Limits** | max_files_per_job: 500 · max_recursion_depth: 3 (email lồng attachment) |

### A1 — INGEST

| Mục | Nội dung |
|---|---|
| **Nhiệm vụ** | Nạp dữ liệu có cấu trúc vào `staging/`, không sửa gì |
| **Kỹ năng cần có** | Đọc CSV/XLSX/Parquet/JSON/SQL · xử lý encoding & delimiter · phát hiện dòng header · đọc nhiều sheet XLSX · streaming file lớn (chunked) · tính content hash · ghi Parquet |
| **Dùng LLM?** | Không |
| **ALLOW** | read: nguồn chỉ định · write: `data/staging/**` |
| **DENY** | sửa giá trị ô · đổi tên cột · drop dòng · ghi vào `raw/` |
| **Limits** | max_file_size: 2GB · timeout: 600s |

### E1 — PDF EXTRACTOR *(Phase 5a)*

| Mục | Nội dung |
|---|---|
| **Nhiệm vụ** | PDF → bảng có cấu trúc + locator + confidence |
| **Kỹ năng cần có** | Phân biệt PDF text-layer vs scan · trích text kèm toạ độ · **nhận diện và trích bảng** · xử lý layout nhiều cột · đọc AcroForm field · render trang → ảnh và chuyển E2 khi là scan · ghi `SourceLocator(page, bbox)` cho **từng trường** · tính confidence |
| **Dùng LLM?** | Có — **chỉ để map text đã trích vào schema đích** (structured output). LLM không tự "đọc" PDF |
| **ALLOW** | read: `data/raw/**` · write: `data/extracted/**` · tools: `pdfplumber, pypdfium2` |
| **DENY** | **đoán/điền giá trị thiếu** · trả record không có locator · gửi > 10 trang/lần lên LLM |
| **Limits** | max_pages: 200 · confidence_threshold: 0.85 → dưới ngưỡng đặt `needs_review=True` |

### E2 — IMAGE / OCR EXTRACTOR *(Phase 5a)*

| Mục | Nội dung |
|---|---|
| **Nhiệm vụ** | Ảnh scan/chụp → dữ liệu có cấu trúc |
| **Kỹ năng cần có** | Tiền xử lý ảnh (deskew, denoise, binarize, chỉnh tương phản) · **OCR tiếng Việt có dấu** (tesseract `vie`) · phát hiện vùng bảng và vùng form · confidence **theo từng trường**, không phải cả trang · **fallback sang vision model của Claude khi OCR confidence thấp** · ghi bbox |
| **Dùng LLM?** | Có, 2 tầng: OCR trước (rẻ), vision model chỉ khi conf < ngưỡng |
| **ALLOW** | read: `data/raw/**` + ảnh render từ E1 · write: `data/extracted/**` |
| **DENY** | xuất giá trị conf thấp mà không gắn cờ · dùng vision model khi chưa thử OCR |
| **Limits** | max_images: 500 · max_vision_calls_per_job: 50 (chặn đốt tiền) |

### E3 — AUDIO / VIDEO EXTRACTOR *(Phase 5b)*

| Mục | Nội dung |
|---|---|
| **Nhiệm vụ** | Ghi âm/ghi hình → transcript → thông tin BA có cấu trúc |
| **Kỹ năng cần có** | Tách audio khỏi video (ffmpeg) · **ASR tiếng Việt** (faster-whisper) · chia đoạn file dài · **diarization** (phân biệt người nói) · timestamp từng câu · trích **requirement / quyết định / action item / pain point** từ transcript · gắn `SourceLocator(time_start, time_end, speaker)` cho mỗi trích dẫn |
| **Dùng LLM?** | Có — chỉ ở bước biến transcript thành record có cấu trúc |
| **ALLOW** | read: `data/raw/**` · write: `data/extracted/**` · tools: `ffmpeg, faster_whisper` |
| **DENY** | xử lý file vượt `max_duration_min` khi chưa được Manager duyệt · trích dẫn không kèm timestamp |
| **Limits** | max_duration_min: 120/file · **cache transcript theo content hash** (bắt buộc — ASR lại là lãng phí lớn nhất của hệ thống) |
| **Cảnh báo** | Đây là extractor đắt và chậm nhất. Luôn ước lượng thời lượng ở A0 và báo user trước khi chạy |

### E4 — DOCUMENT EXTRACTOR *(Phase 5a)*

| Mục | Nội dung |
|---|---|
| **Nhiệm vụ** | docx / eml / msg / html → có cấu trúc |
| **Kỹ năng cần có** | Parse docx giữ heading, bảng, list · parse email: header (from/to/date/subject), body, thread · **bóc attachment và đưa NGƯỢC về A0 Router** (đệ quy, giới hạn depth 3) · strip HTML giữ cấu trúc bảng |
| **Dùng LLM?** | Có — map nội dung vào schema |
| **DENY** | đệ quy quá depth 3 · tự mở link trong email (**không network access**) |

### A2 — PROFILER

| Mục | Nội dung |
|---|---|
| **Nhiệm vụ** | Mô tả dữ liệu: schema, chất lượng, bất thường |
| **Kỹ năng cần có** | Suy luận kiểu dữ liệu · thống kê mô tả · đo null%/duplicate/cardinality · phát hiện outlier (IQR, z-score) · nhận diện datetime hỗn hợp · tìm ứng viên khóa chính · **phát hiện cột PII** · **nhận diện cột event-log** (case_id, activity, timestamp, resource) |
| **Dùng LLM?** | Có — chỉ để *diễn giải* profile và đoán ý nghĩa cột. Thống kê do code tính |
| **Output** | `ProfileReport`: per-column stats + `pii_flags` + `eventlog_candidates` |
| **ALLOW** | read: `data/staging/**` · write: `data/profile/**` |
| **DENY** | **mọi thao tác ghi/sửa dữ liệu** — read-only tuyệt đối |

### A3 — CLEANER

| Mục | Nội dung |
|---|---|
| **Nhiệm vụ** | Đề xuất rule làm sạch, **chỉ thực thi rule đã duyệt** |
| **Kỹ năng cần có** | Chuẩn hoá text (trim, case, unicode NFC) · parse & thống nhất datetime + timezone · ép kiểu an toàn · xử lý missing (drop/fill/flag) · khử trùng lặp theo khóa · chuẩn hoá mã (vendor, currency) · **sinh diff log** |
| **Dùng LLM?** | Có — **chỉ đề xuất** rule dạng JSON. Thực thi 100% bằng code trong `rulebook.py` |
| **Cơ chế** | LLM đề xuất → Manager gom → **HUMAN GATE 1** → chạy đúng rule đã duyệt |
| **ALLOW** | read: `data/staging/**`, `data/profile/**` · write: `data/clean/**` · rules: chỉ id đã duyệt trong rulebook |
| **DENY** | tự chế rule ngoài rulebook · drop cột (phải xin Manager) · drop > 5% dòng · network access |
| **Limits** | max_rows_dropped_pct: 5 → vượt là HALT + escalate |

### A4 — TRANSFORMER

| Mục | Nội dung |
|---|---|
| **Nhiệm vụ** | Join, aggregate, feature, dựng bảng mart |
| **Kỹ năng cần có** | SQL DuckDB · join có kiểm cardinality · pivot/unpivot · window function · feature thời gian (lead time, cycle time) · **ghi lineage** (cột ra sinh từ cột nào) |
| **Dùng LLM?** | Có — sinh SQL. **Bắt buộc** qua SQL guard: chỉ SELECT / CREATE VIEW; cấm DROP/DELETE/UPDATE/ATTACH; cấm truy cập ngoài schema cho phép; cấm cross join không điều kiện |
| **ALLOW** | read: `data/clean/**` · write: `data/mart/**` |
| **DENY** | DDL phá hủy · ghi ngược vào `clean/` hoặc `raw/` |
| **Limits** | max_output_rows: 50M · query timeout: 300s |

### A5 — VALIDATOR

| Mục | Nội dung |
|---|---|
| **Nhiệm vụ** | Chấm PASS/FAIL khách quan tại mọi checkpoint |
| **Kỹ năng cần có** | Schema test (pandera) · uniqueness / not-null / range / referential integrity · business rule (VD `approval_date >= request_date`) · row count drift giữa các tầng · **kiểm mọi con số trong finding của A7 phải khớp một giá trị đã tính** (chống hallucination) · báo lỗi kèm dòng vi phạm mẫu |
| **Dùng LLM?** | **Không.** 100% code — đây là trọng tài |
| **ALLOW** | read: `staging://**`, `clean://**`, `mart://**`, `profile://**`, `extracted://**` · write: `validation://**` |
| **DENY** | **sửa dữ liệu để test pass** (cấm tuyệt đối) · đọc `raw://` — không cần, A1 đã ghi `row_count` vào metrics |

### A6 — PROCESS MINER *(trọng tâm BA)*

| Mục | Nội dung |
|---|---|
| **Nhiệm vụ** | Event log → hiểu quy trình thực tế |
| **Kỹ năng cần có** | Chuẩn hoá event log · **khai phá variant** & tần suất · throughput / cycle / waiting time · **phát hiện bottleneck** · **rework loop** & activity lặp · **conformance checking** (thực tế vs quy trình chuẩn) · phát hiện vi phạm **Segregation of Duties** · **sinh BPMN 2.0 XML** · directly-follows graph |
| **Dùng LLM?** | Có — chỉ diễn giải variant và đặt tên nhóm. Chỉ số do code tính |
| **Bắt buộc** | Nhận event log qua **lớp adapter** (`agents/adapters/`) ở dạng chuẩn `case_id, activity, timestamp, resource`. Sau này nối Signavio chỉ thêm 1 adapter, **không được sửa logic A6** |
| **ALLOW** | read: `data/mart/**` · write: `data/artifacts/process/**` |
| **DENY** | sửa event log · suy đoán activity thiếu |

### A7 — ANALYST

| Mục | Nội dung |
|---|---|
| **Nhiệm vụ** | Rút insight có bằng chứng |
| **Kỹ năng cần có** | So sánh KPI theo chiều (vendor, region, thời gian) · xu hướng & anomaly · root-cause phân tầng · **định lượng tác động** (VD "chậm 4.8 ngày ở Approval = 12% tổng lead time") |
| **Dùng LLM?** | Có — diễn giải. Số liệu do code tính |
| **DENY** | **đưa ra con số không có trong `metrics` đầu vào** — A5 kiểm tra điều này |
| **Output** | `list[Finding]`: `{claim, metric_value, evidence_ref, confidence}` |

### A8 — REPORTER

| Mục | Nội dung |
|---|---|
| **Nhiệm vụ** | Xuất deliverable |
| **Kỹ năng cần có** | Render Markdown/HTML · biểu đồ (matplotlib → PNG) · xuất DOCX/XLSX/PDF · nhúng BPMN · viết executive summary |
| **Dùng LLM?** | Có — viết văn. **Số liệu chèn bằng template, LLM không được gõ lại số** |
| **ALLOW** | read: `data/mart/**`, `data/artifacts/**` · write: `data/artifacts/report/**` |

---

## 9. MANIFEST — ĐỊNH DẠNG CHUẨN

Mỗi agent 1 file trong `config/manifests/`. Nguồn chân lý duy nhất về boundary.

**Bắt buộc:** đường dẫn viết bằng **scheme tầng logic** `layer://glob`, không bao giờ là đường dẫn hệ thống. Manifest ghi cứng `data/staging/**` sẽ vỡ ngay khi đổi vị trí tầng — đường dẫn đã là thứ cấu hình được (Mục 2).

```yaml
agent_id: e2_image
version: 1
description: "Trích xuất dữ liệu từ ảnh scan bằng OCR, fallback vision model"

allow:
  read:  ["raw://**", "extracted://_render/**"]
  write: ["extracted://**"]
  tools: ["tesseract", "opencv", "vision_model"]
  llm:
    enabled: true
    purpose: map_text_to_schema
    vision_fallback: true
    vision_trigger: "ocr_confidence < 0.75"

deny:
  - network_access
  - write_outside_scope
  - shell_exec
  - emit_unflagged_low_confidence
  - vision_before_ocr

limits:
  max_images: 500
  max_vision_calls: 50
  confidence_threshold: 0.85
  max_runtime_s: 900
  max_tokens: 60000
  max_retries: 3

must_return:
  schema: ExtractionResult
  required_fields: [records, confidence, field_confidence, locators, method]

human_gate:
  required: true
  at: after_execution
  condition: "needs_review == true"
  approve: low_confidence_records

on_violation: HALT_AND_ESCALATE
```

---

## 10. CƯỠNG CHẾ BOUNDARY — 3 LỚP
Implement trong `core/boundary.py` và `agents/base.py`.

**Lớp 1 — Pre-flight.** `BaseAgent.run()` kiểm `ScopeToken` khớp manifest: path đọc/ghi có trong `allow`? tool có được phép? token còn hạn? Sai → raise `BoundaryViolation`, **không chạy**.

**Lớp 2 — Runtime guard.**

- I/O **chỉ đi qua** `core/storage.py`, hàm này nhận `ScopeToken` và tự chặn path ngoài scope.
- Bộ đếm ngân sách chạy song song, chạm trần → raise `BudgetExceeded`.
- **Chặn mọi lối I/O đi tắt.** Test AST quét `src/analysis_system/agents/**` phải chặn **tất cả** những thứ sau, không chỉ `open()`:

  ```
  open(...)
  os.*          shutil.*        subprocess.*      pathlib.Path
  pd.read_*     .to_csv / .to_parquet / .to_excel / .to_json
  duckdb.connect
  ```

  Lý do: `pd.read_csv()` và `df.to_parquet()` đi thẳng ra filesystem, vượt qua `storage.py` hoàn toàn — lỗ hổng lớn hơn `open()`.
  **Ngoại lệ duy nhất được phép:** `src/analysis_system/core/storage.py` (trước tái cấu trúc
  DDD là `services/storage.py`; xem `plans/refactor-ddd.md`).
- Phân công: **ruff** lo phần *import* (`flake8-tidy-imports` banned-api); **test AST** lo phần *lời gọi*. Viết test này ở Phase 1, cùng lúc với boundary layer.

**Lớp 3 — Post-check.** Manager validate `TaskResult` bằng Pydantic + kiểm `limits`. Fail → `RETRY` / `ESCALATE`. Kết quả không hợp lệ **không bao giờ** ghi vào state.

Mọi vi phạm ghi `audit.jsonl` với `event: BOUNDARY_VIOLATION`.

> **Giới hạn cần biết:** agent chạy cùng tiến trình Manager nên Lớp 2 là *cooperative sandbox*, không phải cưỡng chế ở mức OS. Ghi rõ giới hạn này trong README. Nâng lên subprocess isolation là việc của Phase 3 nếu thấy cần.
## 11. MANAGER — VÒNG ĐIỀU PHỐI

```
1. ROUTE     A0 phân loại input → routing plan (code, trước khi LLM tham gia)
2. PLAN      LLM đọc yêu cầu + routing plan + agent registry → DAG (JSON, validate Pydantic)
3. DISPATCH  Mỗi task sẵn sàng: tạo ScopeToken → gọi agent
4. VERIFY    Nhận TaskResult → validate schema → kiểm limits → kiểm evidence
5. DECIDE    PASS         → ghi state, mở task kế
             RETRY        → chạy lại (max_retries, có backoff)
             REPLAN       → LLM sửa DAG (tối đa 2 lần/job)
             NEEDS_REVIEW → đẩy lên human gate
             ESCALATE     → dừng, hỏi user
6. GATE      Tới human gate → in tóm tắt, chờ user duyệt
7. LOOP      Tới khi DAG xong hoặc HALT
```

**Manager tuyệt đối không đọc/ghi file dữ liệu.** Chỉ thấy `DataRef` (path + hash + metadata) và `metrics`.

**State & resume:** sau mỗi task ghi `runs/<run_id>/state.json`. Chạy lại cùng `run_id` → bỏ qua task đã `OK` có `content_hash` input không đổi.

**Ba human gate:**

| Gate | Vị trí | Duyệt gì |
|---|---|---|
| **GATE 0** | sau extraction | Các record `needs_review=True` (confidence thấp) |
| **GATE 1** | trước khi làm sạch | Danh sách rule A3 đề xuất |
| **GATE 2** | trước khi xuất báo cáo | Kết luận của A7 |

### Cơ chế gate — 2 bước, KHÔNG treo chờ input

Đây là cách duy nhất tương thích với S3 (resume).

1. Chạm gate → ghi `<runs>/<run_id>/gates/<gate_id>.json` chứa nội dung cần duyệt → state chuyển `PAUSED_AWAITING_APPROVAL` → **tiến trình thoát mã 0**. Không `input()`, không treo chờ.
2. User duyệt bằng CLI:
   ```
   python -m analysis_system.cli gates   <run_id>
   python -m analysis_system.cli approve <run_id> --gate <id> [--select ...] [--reject ...]
   python -m analysis_system.cli resume  <run_id>
   ```
3. Quyết định duyệt được ghi vào state **như dữ liệu**.

**Quan trọng cho S1:** chạy lại cùng `run_id` phải **phát lại quyết định đã lưu**, không hỏi lại. Không có điều này thì hệ thống không bao giờ tất định được.

---

## 12. NGÂN SÁCH, LOG, PII

### Budget (`config/budget.yaml`)

```yaml
per_job:
  max_tokens: 500000
  max_cost_usd: 5.00
  max_wallclock_min: 30
per_agent_call:
  max_tokens: 50000
  max_retries: 3
extraction:                    # Phase 5 — tách riêng vì đặc tính khác
  max_vision_calls: 50
  max_asr_minutes: 240
  asr_cache: required          # cache theo content hash, bắt buộc
on_exceed: HALT_AND_REPORT     # không bao giờ tự động chạy tiếp
```

### Bảng giá (`config/pricing.yaml`) — Phase 1

Không hardcode giá trong code. File phải có:

- `last_verified: <ngày>` — quá **90 ngày** thì in cảnh báo khi chạy (giá model thay đổi).
- Đủ 4 mức, không chỉ input/output: `input`, `output`, `cache_read`, `cache_write` (prompt caching giảm tới 90% chi phí, sẽ dùng ở Phase 3).

Giá hiện hành ($/1M token, input / output):

```
claude-opus-5    :  5.00 / 25.00
claude-sonnet-5  :  2.00 / 10.00
claude-haiku-4-5 :  1.00 /  5.00
```

### Audit log — mỗi dòng 1 JSON

```json
{"ts":"2026-08-30T10:12:03Z","run_id":"r_8f3a","task_id":"t_04","agent_id":"a3_cleaner",
 "event":"TASK_COMPLETED","status":"OK","input_hash":"3f9a...","output_hash":"7c21...",
 "metrics":{"rows_in":482119,"rows_out":481808,"duration_s":41.2,
            "tokens_in":8210,"tokens_out":1420,"cost_usd":0.062}}
```

Bắt buộc log: `RUN_STARTED, FILES_ROUTED, PLAN_CREATED, SCOPE_ISSUED, TASK_STARTED, TASK_COMPLETED, EXTRACTION_LOW_CONFIDENCE, VALIDATION_RESULT, BOUNDARY_VIOLATION, BUDGET_WARNING, HUMAN_GATE, RUN_ENDED`.

### PII — cách làm bắt buộc

`core/pii.py` chạy **trước mọi lần gọi LLM**:

1. **Mask bằng regex** các mẫu xác định: email, số điện thoại, mã số thuế, số tài khoản, CCCD/CMND → thay bằng token (`<EMAIL_1>`). Bảng ánh xạ giữ **trong bộ nhớ**, không ghi file, không gửi LLM.
2. **KHÔNG dùng NER để mask tên người.** Tiếng Việt nhận diện kém, sai nhiều, tốn tiền.
3. Thay vào đó: cột nào A2 gắn cờ PII → **không gửi giá trị nào lên LLM**, chỉ gửi tên cột + thống kê tổng hợp (null%, cardinality, độ dài trung bình).
4. **Phase 5 lưu ý riêng:** ảnh scan hoá đơn/hợp đồng chứa PII dày đặc. Trước khi gọi vision model, phải che vùng đã nhận diện là PII hoặc cắt chỉ vùng cần đọc.

---

## 13. TẤT ĐỊNH & HASH — ĐỊNH NGHĨA CHO S1

Tiêu chí S1 ("chạy lại cùng input ra cùng output") chỉ có nghĩa khi định nghĩa rõ *hash cái gì*.

**1. KHÔNG hash byte của file parquet.** `pyarrow` nhúng metadata phiên bản/thời điểm ghi — hai lần ghi có thể khác byte dù dữ liệu giống hệt.

**2. Hash nội dung bảng.** Viết **một hàm duy nhất** `canonical_hash(df)` trong `core/hashing.py`, dùng chung ở mọi nơi:

```
sắp xếp theo khóa cố định
  → tuần tự hoá dạng chuẩn (định dạng số thực cố định, encoding cố định, cột theo thứ tự khai báo)
  → sha256
```

**3. Báo cáo:** loại bỏ `run_id`, `timestamp`, `duration`, `cost` **trước khi** hash.

**4. Chặn các nguồn phi tất định khác:**

- `PYTHONHASHSEED=0` (đặt trong `tasks.py`)
- luôn sort trước khi ghi
- không dùng thứ tự lặp của `set`/`dict` để sinh output
- `groupby(sort=True)`
- không dùng `datetime.now()` trong đường sinh dữ liệu — chỉ trong log/metrics đã bị loại khỏi hash

**5. Test S1 bắt buộc:** chạy pipeline 2 lần trên cùng input → so `canonical_hash` từng tầng đầu ra.
## 14. LỘ TRÌNH & DEFINITION OF DONE
Làm tuần tự. Kết thúc mỗi phase: `python tasks.py check` sạch → cập nhật README → **báo cáo cho user rồi mới sang phase sau**.

### Phase 0 — Baseline không AI

Pipeline Python thuần: CSV → ingest → clean (rule cứng) → validate → 1 report Markdown.

- CLI: `python -m analysis_system.cli run --input <raw>/sample.csv`
- `tasks.py` với target `check, lint, typecheck, test, run, setup, clean`; `Makefile` là vỏ mỏng gọi lại.
- **Không viết stub cho Phase 1.** Không viết `def read(path, scope: ScopeToken | None = None)` khi `ScopeToken` chưa tồn tại — vừa vi phạm Quy tắc 1, vừa bẩn. Phase 0 `storage.py` nhận path tường minh.

> **Nguyên tắc: Phase 1 BỌC, không VIẾT LẠI.** Lớp kiểm scope của Phase 1 là lớp bọc ngoài, gọi xuống đúng hàm Phase 0.

**Rulebook Phase 0 — đúng 6 rule, không hơn:**

`trim_whitespace` · `normalize_unicode_nfc` · `standardize_datetime` · `cast_numeric_safe` · `drop_exact_duplicates` · `flag_missing_required`

Ràng buộc:

1. **Thứ tự áp dụng phải cố định và khai báo tường minh** trong rulebook. Thứ tự khác nhau ra kết quả khác nhau → phá vỡ S1.
2. `standardize_datetime` **phải có tham số `assume_timezone` tường minh**. Cấm đoán timezone. Thiếu tham số → báo lỗi, **không** mặc định UTC.
3. `cast_numeric_safe`: giá trị ép kiểu thất bại phải ghi vào `diff_log` kèm số dòng, **không** được âm thầm thành null.

**DoD:** chạy end-to-end trên `tests/fixtures/bpi19_slice.csv` · ≥ 10 unit test pass · `python tasks.py check` sạch · **không có LLM call nào**.

### Phase 1 — Manager + 2 agent

Thêm: contracts, ScopeToken, `BaseAgent`, boundary 3 lớp (gồm **test AST** ở Mục 10), audit log, budget guard, `pricing.yaml`, PII service, Manager (planner/dispatcher/verifier/state), A2 + A3, HUMAN GATE 1 theo cơ chế 2 bước.

**DoD:** A3 bị chặn khi cố ghi ngoài scope (**có test chứng minh**) · audit log đầy đủ · kill giữa chừng → resume đúng · phát lại quyết định gate đã lưu · contract test pass.

### Phase 2 — Đủ agent pool cho dữ liệu có cấu trúc

Thêm A1, A4, A5, A7, A8. Thêm retry/backoff, replan, HUMAN GATE 2, SQL guard cho A4, chống hallucination số cho A7.

**DoD:** chạy full DAG trên fixture ra kết quả khớp `tests/golden/expected/` · 2 lần chạy cùng input → **`canonical_hash` trùng** (Mục 13).

### Phase 3 — Hardening + đóng gói

Test 4 tầng đầy đủ, regression suite cho prompt, coverage ≥ 80% trên `services/` và `manager/`, README + sơ đồ kiến trúc, xử lý lỗi mọi nhánh.
**Thêm Docker:** `Dockerfile` + `docker-compose.yml`. Quy tắc volume — `raw` mount **read-only**; `artifacts` và `runs` bind mount để user đọc được; dữ liệu trung gian dùng **named volume**.

**DoD:** `python tasks.py check` sạch · S1–S5 mỗi tiêu chí có test chứng minh · `docker compose up` chạy được job hoàn chỉnh.

### Phase 4 — Process mining & Signavio

Thêm A6 + lớp `adapters/`. Đọc event log chuẩn, khai phá variant, bottleneck, rework, conformance, SoD. Xuất **BPMN 2.0 XML** mở được trong Signavio Process Manager.

**DoD:** từ event log mẫu ra BPMN hợp lệ + báo cáo bottleneck có evidence · thêm 1 adapter mới **không cần sửa** `a6_process_miner.py` (có test chứng minh).

### Phase 5a — Extractor tài liệu & ảnh

Thêm A0 Router, E1 (PDF), E2 (ảnh/OCR), E4 (docx/email/html), contract `ExtractionResult` + `SourceLocator`, HUMAN GATE 0, cache theo content hash.

**DoD:** PDF text-layer, PDF scan, ảnh chụp, và 1 email có attachment đều chạy được · mọi record có `SourceLocator` · record dưới ngưỡng confidence bị chặn ở GATE 0 (có test) · vision model không bao giờ được gọi trước OCR (có test).

### Phase 5b — Extractor audio/video

Thêm E3. ffmpeg tách audio, faster-whisper ASR tiếng Việt, diarization, trích requirement/quyết định/action item kèm timestamp.

**DoD:** 1 file video mẫu ra transcript + record có timestamp và speaker · cache ASR hoạt động (chạy lần 2 không gọi lại ASR, có test) · vượt `max_duration_min` thì HALT chờ duyệt.

> **Ghi chú phạm vi:** Phase 5b là phần đắt và chậm nhất. Nếu tới Phase 5a thấy audio/video ít dùng thực tế, hoãn 5b lại là quyết định hợp lý.
## 15. YÊU CẦU TEST
### Dữ liệu test — dùng DỮ LIỆU THẬT, không tự sinh

**Nguồn:** BPI Challenge 2019 — event log Purchase-to-Pay thật, từ 4TU.ResearchData.
<https://data.4tu.nl/articles/dataset/BPI_Challenge_2019/12715853>

**Luồng:**

1. User tải file full về `~/analysis-data/raw/`. **Không commit vào git.**
2. `scripts/make_fixture.py` cắt ra fixture cố định → `tests/fixtures/bpi19_slice.csv` (~1000 event).
3. Fixture này **commit vào git và từ đó BẤT BIẾN**. Test đọc file đã commit, **không cắt lại lúc chạy test**.

**Quy tắc cắt — bắt buộc:**

- Lấy nguyên **CASE HOÀN CHỈNH**, KHÔNG cắt theo dòng. Cắt giữa case sẽ làm process mining ở Phase 4 ra kết quả sai.
- Cách làm: sort theo `case_id` → lấy lần lượt từng case trọn vẹn cho tới khi đủ ~1000 event → dừng.
- **Tất định tuyệt đối:** cùng file gốc phải ra cùng fixture. Không `random`, không `sample()`.
- Ghi `tests/fixtures/FIXTURE.md`: số case, số event, danh sách activity, khoảng thời gian, và các **vấn đề chất lượng quan sát được** (null, định dạng ngày, giá trị lạ). Đây là **tài liệu quan sát**, không phải lỗi tự cài.

**PII:** BPI 2019 đã ẩn danh, **không có cột PII** → đường PII không test được bằng fixture này. Tách riêng: `tests/fixtures/pii_sample.csv` (~20 dòng tự chế) chỉ để unit test `core/pii.py`.

**Bản quyền:** ghi rõ nguồn và giấy phép của BPI 2019 trong README (dữ liệu công khai phục vụ nghiên cứu, cần ghi nguồn).

**`raw/sample.csv`:** **không commit**. `python tasks.py setup` copy fixture → `<raw>/sample.csv` để demo CLI. Nếu file BPI gốc chưa có trong `raw/`, `setup` phải **báo lỗi rõ ràng bằng tiếng Việt kèm link tải, KHÔNG tự tải về**.

### 4 tầng test

| Tầng | Nội dung | Vị trí |
|---|---|---|
| **Unit** | Từng hàm rulebook, storage, hashing, boundary, budget, pii, extractor | `tests/unit/` |
| **Contract** | Mỗi agent trả đúng schema; ScopeToken sai bị từ chối | `tests/contract/` |
| **Golden** | Fixture cố định → output khớp `canonical_hash` (Mục 13), **không** so byte parquet | `tests/golden/` |
| **Regression** | Đổi prompt không làm hỏng kết quả golden | `tests/regression/` |

**Test tiêu cực bắt buộc:**

- Agent ghi ngoài `allow.write` → `BoundaryViolation`
- Agent dùng tool không trong `allow.tools` → bị chặn
- Agent gọi `pd.read_csv` / `open()` / `duckdb.connect` trực tiếp → **test AST fail**
- ScopeToken hết hạn → bị từ chối
- Cleaner drop > 5% dòng → HALT
- Vượt budget → `HALTED_BUDGET`, không chạy tiếp
- Agent trả sai schema → Manager reject, không ghi state
- A7 đưa số không có trong metrics → A5 bắt lỗi
- **E2 gọi vision model trước khi thử OCR → bị chặn**
- **Extractor trả record không có `SourceLocator` → reject**
- **Record confidence dưới ngưỡng lọt qua GATE 0 → test phải fail**
- **E4 đệ quy attachment quá depth 3 → HALT**
- **E3 chạy lần 2 trên cùng file → không gọi lại ASR (cache hit)**
## 16. CHECKLIST BÀN GIAO
- [ ] Repo tại `~/projects/analysis-system` (WSL2), dữ liệu ở `~/analysis-data`, runs ở `~/analysis-runs` — không thứ nào nằm trên `/mnt/*`
- [ ] Cây thư mục đúng Mục 6, package `analysis_system` (src-layout)
- [ ] `python tasks.py check` sạch (ruff + mypy + pytest); `Makefile` chỉ là vỏ
- [ ] `config/settings.yaml` khai báo từng tầng độc lập; thiếu tầng → lỗi tiếng Việt rồi thoát
- [ ] Manifest YAML đầy đủ cho mọi agent, dùng scheme `layer://`, không hardcode path
- [ ] Prompt tách riêng trong `prompts/`
- [ ] 3 lớp boundary có test chứng minh, **gồm test AST chặn I/O đi tắt**
- [ ] Audit log JSONL đủ 12 loại event
- [ ] Budget guard hoạt động; `pricing.yaml` có `last_verified`, cảnh báo khi quá 90 ngày
- [ ] PII masking đúng cách ở Mục 12 (regex, **không NER**)
- [ ] Human gate 2 bước; chạy lại cùng `run_id` phát lại quyết định đã lưu
- [ ] Resume từ state hoạt động
- [ ] `canonical_hash` là hàm duy nhất; test S1 chạy 2 lần trùng hash
- [ ] Fixture `bpi19_slice.csv` bất biến + `FIXTURE.md`; nguồn & giấy phép BPI 2019 ghi trong README
- [ ] Mọi dữ liệu phi cấu trúc có `SourceLocator` truy ngược được
- [ ] Cache ASR + cache extraction theo content hash
- [ ] Docker compose chạy được, volume đúng quy tắc Phase 3
- [ ] README: kiến trúc, cách chạy, **cách tắt `dev_mode`**, **cách thêm agent mới**, **cách thêm adapter event log mới**
- [ ] `NOTES.md` ghi mọi quyết định thiết kế và giả định
## 17. LỆNH ĐẦU TIÊN CHO CLAUDE CODE
```
Đọc toàn bộ BUILD_SPEC.md v3.
Tham số Mục 2 và các quyết định C1-C14 đã chốt, không hỏi lại.

Điều kiện tiên quyết — kiểm tra trước, không được bỏ qua:
  1. WSL2 đã cài distro; python3 >= 3.11, git, make có sẵn trong distro đó.
  2. File BPI Challenge 2019 gốc đã nằm trong ~/analysis-data/raw/.
     Nếu chưa: DỪNG, báo user, KHÔNG tự tải, KHÔNG tự sinh dữ liệu thay thế.
  3. Đọc 50 dòng đầu file gốc và báo user schema thật:
     tên cột + kiểu · cột nào là case_id/activity/timestamp/resource ·
     định dạng timestamp · vấn đề chất lượng nhìn thấy ngay.
     KHÔNG đoán schema trước khi nhìn dữ liệu thật.

Sau khi user chốt schema → trình kế hoạch Phase 0 chi tiết → chờ duyệt → code.
Chỉ Phase 0. Không nhảy phase.
```