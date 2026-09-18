[English](README.en.md) · **Tiếng Việt**

<div align="center">

# Hệ thống phân tích dữ liệu

**Nền tảng phân tích dữ liệu đa tác tử, chạy tại chỗ, mọi con số trong câu trả lời đều truy nguyên được về dòng dữ liệu gốc.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![FastAPI](https://img.shields.io/badge/FastAPI-backend-009688?logo=fastapi&logoColor=white)](src/analysis_system/api)
[![Next.js](https://img.shields.io/badge/Next.js-frontend-000000?logo=nextdotjs&logoColor=white)](frontend)
[![DuckDB](https://img.shields.io/badge/DuckDB-engine-FFF000?logo=duckdb&logoColor=black)](src/analysis_system/domains/execution_engine)

[![Tests](https://img.shields.io/badge/tests-2987%20passing-brightgreen)](tests)
[![Coverage](https://img.shields.io/badge/coverage-90.7%25-brightgreen)](#chất-lượng-mã-nguồn)
[![mypy](https://img.shields.io/badge/mypy-strict-blue)](pyproject.toml)
[![Ruff](https://img.shields.io/badge/ruff-clean-261230?logo=ruff&logoColor=white)](pyproject.toml)
[![Architecture](https://img.shields.io/badge/DDD-0%20vi%20ph%E1%BA%A1m%20t%E1%BA%A7ng-7B3FE4)](#kiến-trúc)
[![Deployment](https://img.shields.io/badge/deployment-on--premise-334155?logo=docker&logoColor=white)](DEPLOY.md)
[![API cost](https://img.shields.io/badge/ch%E1%BA%BF%20%C4%91%E1%BB%99%20handoff-%240-success)](#chi-phí-vận-hành)

</div>

---

Đưa dữ liệu vào, hệ thống làm sạch và trả lại bản sạch cho bạn xem. Bạn đặt câu hỏi, nó
giao việc cho các AI chuyên trách, rồi trả lời, **kèm bằng chứng cho từng con số**.

Bạn hỏi tiếp bao nhiêu lần cũng được.

| | |
|---|---|
| [Tổng quan](#tổng-quan) | [Điểm nhấn kỹ thuật](#điểm-nhấn-kỹ-thuật) |
| [Vòng làm việc](#vòng-làm-việc) | [Bắt đầu nhanh](#bắt-đầu-nhanh) |
| [Kiến trúc](#kiến-trúc) | [Cấu trúc thư mục](#cấu-trúc-thư-mục) |
| [Số liệu không bịa được](#số-liệu-không-bịa-được) | [Ai làm gì](#ai-làm-gì) |
| [Bảo mật và vận hành tại chỗ](#bảo-mật-và-vận-hành-tại-chỗ) | [Chất lượng mã nguồn](#chất-lượng-mã-nguồn) |
| [Chi phí vận hành](#chi-phí-vận-hành) | [Tài liệu](#tài-liệu) |

---

## Tổng quan

| | |
|---|---|
| **Bài toán** | Phân tích dữ liệu kinh doanh mà không phải tin lời một model nói suông |
| **Cách giải** | 14 agent (một Manager và 13 agent chuyên trách), mỗi agent chạy trong một phạm vi được cấp và không được vượt; mọi con số do code tính, model chỉ diễn giải |
| **Triển khai** | Tại chỗ (on-premise). Dữ liệu nằm trên máy của bạn; chỉ đoạn cần hỏi model mới được gửi đi, và chỉ khi bạn bật một provider gọi API |
| **Giao diện** | Web (Next.js) và dòng lệnh (`asys`) |
| **Lưu trữ** | DuckDB và Parquet trên đĩa cục bộ, chia theo tầng dữ liệu |
| **Chi phí API** | $0 ở chế độ `handoff`; toàn bộ quá trình thử nghiệm qua API thật tốn khoảng $7,6 cho 220 lượt gọi |

---

## Điểm nhấn kỹ thuật

| Hạng mục | Con số | Cưỡng chế bởi |
|---|---|---|
| **Độ phủ test** | **90,7%** (12.999 / 14.326 câu lệnh) | `pytest --cov`, đo lại ngày 18/09/2026 |
| Bộ test | **2.987 test** trên 150 file (unit, contract, criteria, golden, regression) | `make test` |
| Kiểu tĩnh | **mypy strict**, 0 lỗi trên 294 file | `mypy src tests` |
| Lint và định dạng | **ruff**, 0 cảnh báo | `ruff check` |
| Vi phạm tầng kiến trúc | **0**, không còn ngoại lệ nào | `tests/unit/test_architecture.py` |
| Agent chạm thẳng vào đĩa | **0** | quy tắc lint và một test AST |
| Dữ liệu gửi ra ngoài máy | **0 byte** ở chế độ `handoff` | `provider` trong `config/settings.yaml` |
| Bí mật lọt vào git | **0** | `scripts/secret_scan.py` chạy trên diff trước mỗi lần commit |

---

## Vòng làm việc

```
Bạn đưa file
   ↓
Hệ thống đọc và đề xuất cách làm sạch  →  DỪNG, chờ bạn duyệt
   ↓
Bạn nhận lại bản dữ liệu sạch
   ↓
Bạn đặt câu hỏi
   ↓
Manager chia việc → các AI chuyên trách xử lý → Manager tổng hợp
   ↓
Câu trả lời, kèm nguồn từng số           →  DỪNG, chờ bạn duyệt
   ↓
Bạn hỏi tiếp  →  quay lại bước trên
```

Hai chỗ **DỪNG** là cố ý. Hệ thống không tự sửa dữ liệu của bạn và không tự công bố kết
luận. Bạn là người chốt.

---

## Bắt đầu nhanh

```bash
# 1. Đưa file vào và làm sạch
asys clean --input ~/du_lieu/ban_hang.csv --run-id bh

# 2. Xem nó định làm gì, rồi duyệt
asys gates bh
asys approve bh --gate gate_t3_clean --select trim_whitespace

# 3. Nhận bản sạch
asys resume-dag bh

# 4. Hỏi
asys ask bh "Kênh nào có doanh thu cao nhất, và thấp nhất?"

# 5. Hỏi tiếp, bao nhiêu lần cũng được
asys ask bh "Doanh thu có xu hướng tăng theo thời gian không?"
```

Chưa biết file của mình là loại gì thì hỏi trước:

```bash
asys route ~/du_lieu/
```

Nó đọc vài byte đầu mỗi file và nói cái nào đọc được bằng gì. **Định dạng do nội dung
quyết định, không do đuôi file.** Một file PDF đặt tên `.csv` vẫn được nhận ra đúng.

### Giao diện web

```bash
asys set-password     # đặt mật khẩu, nó tự ghi vào .env
asys serve            # mở http://localhost:8020
```

Triển khai bằng Docker và systemd: xem [DEPLOY.md](DEPLOY.md).

### Đọc được những gì

| Loại | Định dạng |
|---|---|
| Bảng | CSV · Excel · JSON · Parquet |
| Tài liệu | PDF · **Word** · **Email** · **HTML** |
| Ảnh | PNG · JPEG · TIFF (đọc chữ trong ảnh) |
| Âm thanh | WAV · MP3 · M4A · MP4 (nghe và ghi lại lời nói) |

### Xuất ra những gì

```bash
asys export clean://ban_hang.parquet --out bao_cao.xlsx
```

CSV · Excel · Word · Markdown · HTML · JSON. **Định dạng ra là lựa chọn của bạn, không
dính gì tới định dạng vào.** Đọc PDF xuất Excel được, đọc CSV xuất Word được. Excel và
CSV mở thẳng trong Tableau hoặc Power BI.

---

## Kiến trúc

Hệ thống theo Clean Architecture và Domain-Driven Design. Mã nguồn chia thành năm tầng,
**mũi tên phụ thuộc chỉ đi xuống**: tầng trên gọi tầng dưới, không bao giờ ngược lại.

### Luồng một yêu cầu đi qua các tầng

```
     ┌──────────────────┐        ┌──────────────────┐
     │   Trình duyệt    │        │  Dòng lệnh asys  │
     └────────┬─────────┘        └────────┬─────────┘
              │ HTTP :3000                │
     ┌────────▼─────────┐                 │
     │ Next.js frontend │  cổng duy nhất  │
     │   (frontend/)    │  mở ra mạng     │
     └────────┬─────────┘                 │
              │ REST /api/* tới 127.0.0.1 │
╔═════════════▼═══════════════════════════▼═══════════════════════════════════╗
║ TẦNG 4   api/            Nhận request, kiểm phiên, gọi xuống, trả JSON.      ║
║                          Không một luật nghiệp vụ nào sống ở đây.            ║
║                          app.py 61 dòng · 6 router · presenter dựng JSON     ║
╠═════════════╪════════════════════════════════════════════════════════════════╣
║             ▼                                                                ║
║ TẦNG 3   application/    Điều phối ca sử dụng: làm sạch, hỏi, duyệt, xoá.    ║
║                          Biết thứ tự các bước, không biết HTTP là gì.        ║
╠═════════════╪════════════════════════════════════════════════════════════════╣
║             ▼                                                                ║
║ TẦNG 2   agents/         Manager lập kế hoạch, giao việc, tổng hợp.          ║
║          manager/        Mỗi agent làm việc trong boundary được cấp.         ║
║          domains/        Nghiệp vụ, mỗi lĩnh vực một thư mục:                ║
║                            data_ingestion    nạp · đọc · làm sạch · bộ dữ liệu║
║                            execution_engine  SQL và mọi phép tính tất định   ║
║                            ai_planner        prompt · gọi model · kiểm chứng ║
║                            visualization     biểu đồ · BI · báo cáo · xuất   ║
╠═════════════╪════════════════════════════════════════════════════════════════╣
║             ▼                                                                ║
║ TẦNG 1   models/         Hợp đồng dùng chung: ScopeToken, DataRef,           ║
║                          kết quả trả về của từng agent.                      ║
╠═════════════╪════════════════════════════════════════════════════════════════╣
║             ▼                                                                ║
║ TẦNG 0   core/           Cấu hình, lưu trữ theo tầng dữ liệu, ranh giới,     ║
║                          kiểm toán, ngân sách, chữ tiếng Việt.               ║
╚═════════════╪════════════════════════════════════════════════════════════════╝
              ▼
     ┌──────────────────────────────────────────────────────────────┐
     │  Đĩa cục bộ:  raw → extracted → staging → clean → mart        │
     │               DuckDB · Parquet · nhật ký kiểm toán JSONL      │
     └──────────────────────────────────────────────────────────────┘
```

### Luật phụ thuộc

```
api  ──▶  application  ──▶  agents · manager · domains  ──▶  models  ──▶  core
```

- `core` không import domain, agents, manager, application hay api.
- `models` chỉ import `core`.
- Domain không import `application` hay `api`.
- Domain này **không** import domain kia. Việc bắc cầu là của tầng trên.

Luật này có test cưỡng chế ([`tests/unit/test_architecture.py`](tests/unit/test_architecture.py)):
một import đi ngược tầng làm trượt test ngay, và hiện **không có ngoại lệ nào**. Một gói
cấp cao mới chưa được xếp tầng cũng làm trượt test, nên cấu trúc không trôi đi trong im
lặng.

Frontend là một ứng dụng Next.js tách hẳn trong [`frontend/`](frontend), nói chuyện với
backend chỉ qua REST. Không có một dòng HTML nào sinh ra từ Python.

---

## Cấu trúc thư mục

```
analysis-system/
│
├── src/analysis_system/            # Backend
│   ├── api/                        # TẦNG 4 · 10 module + 6 router
│   │   ├── app.py                  #   61 dòng, chỉ lắp router lại với nhau
│   │   ├── routers/                #   session · system · datasets · runs · bi · dashboards
│   │   ├── session.py  auth.py     #   phiên đăng nhập, mật khẩu, cookie
│   │   ├── replies.py  inputs.py   #   chuẩn hoá lỗi trả về, kiểm tra đầu vào
│   │   ├── once.py                 #   chống gửi trùng một thao tác
│   │   └── view.py  state.py  tree.py    # dựng JSON cho giao diện, không quyết định luật
│   │
│   ├── application/                # TẦNG 3 · 1 module
│   │   └── workspace.py            #   điều phối toàn bộ ca sử dụng
│   │
│   ├── agents/                     # TẦNG 2 · 13 module, 14 agent
│   │   ├── a1_ingest.py … a10_text_miner.py
│   │   ├── extractors.py           #   E1-E4: PDF · ảnh · âm thanh · tài liệu
│   │   └── base.py  feedback.py
│   │
│   ├── manager/                    # TẦNG 2 · 9 module
│   │   ├── planner.py  dispatcher.py  dag_runner.py  runner.py
│   │   ├── gates.py                #   hai điểm dừng chờ người duyệt
│   │   └── verifier.py  selection.py  retry.py  state.py
│   │
│   ├── domains/                    # TẦNG 2 · 65 module
│   │   ├── data_ingestion/         #   20 · nạp, đọc, luật làm sạch, bộ dữ liệu, từ điển
│   │   ├── execution_engine/       #   18 · SQL, thống kê, dự báo, khai phá quy trình
│   │   ├── ai_planner/             #   16 · prompt, gọi model, đọc câu hỏi, kiểm chứng
│   │   └── visualization/          #   11 · biểu đồ, Tự phân tích, bảng điều khiển, xuất
│   │
│   ├── models/                     # TẦNG 1 · 2 module
│   │   ├── base.py                 #   ScopeToken, DataRef, kiểu dùng chung
│   │   └── agents.py               #   hợp đồng đầu vào và đầu ra của từng agent
│   │
│   ├── core/                       # TẦNG 0 · 14 module
│   │   ├── settings.py             #   đọc config, không hằng số nào nằm trong code
│   │   ├── storage.py  scoped_storage.py    # tầng dữ liệu, đường dẫn có kiểm soát
│   │   ├── boundary.py             #   cưỡng chế phạm vi của agent
│   │   ├── audit.py                #   nhật ký chỉ ghi thêm, không sửa
│   │   ├── budget.py  retention.py #   trần chi phí, vòng đời dữ liệu
│   │   ├── pii.py  hashing.py      #   dò dữ liệu cá nhân, băm ẩn danh
│   │   └── vietnamese_text.py  punctuation.py  units.py  job_error.py  updater.py
│   │
│   ├── pipeline/                   # chạy trọn một lượt từ đầu tới cuối
│   └── cli.py                      # điểm vào của lệnh `asys`
│
├── frontend/                       # Next.js, TypeScript
│   └── src/  app/  components/  lib/
│
├── tests/                          # 2.987 test trên 150 file
│   ├── unit/                       #   111 file
│   ├── contract/                   #   34 file, hợp đồng vào và ra của từng agent
│   ├── criteria/                   #   4 file, các tiêu chí S1-S4 của đặc tả
│   ├── golden/  regression/        #   kết quả chuẩn, lỗi đã gặp không được tái diễn
│   └── cassettes/  fixtures/       #   câu trả lời model ghi sẵn, dữ liệu mẫu
│
├── config/                         # settings.yaml · budget.yaml · pricing.yaml · manifests/
├── prompts/                        # prompt của từng agent, tách khỏi code
├── deploy/                         # asys.service · asys-web.service · restart-services.sh
├── scripts/                        # secret_scan.py · install.sh · công cụ vận hành
├── plans/                          # kế hoạch các chiến dịch kỹ thuật
│
├── Dockerfile  docker-compose.yml  # triển khai tại chỗ
├── Makefile  tasks.py              # cổng kiểm tra: lint · type · test · coverage
└── pyproject.toml  requirements.lock.txt
```

---

## Số liệu không bịa được

Đây là chỗ hệ thống này khác một con AI thông thường.

**AI không được phép gõ một con số nào.** Nó viết câu văn với chỗ trống, code điền số vào:

```
AI viết  :  "Nhóm {ten:X.mean.by.kenh.app} xử lý lâu nhất, {X.mean.by.kenh.app}."
Bạn đọc  :  "Nhóm app xử lý lâu nhất, 24.53 giờ."
```

Câu nào có chữ số AI tự gõ thì **bị loại cả câu**, không sửa. Vì sửa là phải đoán nó
định nói gì.

Ngoài ra hệ thống còn tự chặn:

- **Nói sai nhóm đứng đầu.** Code so lại các con số; nói `sadness` cao nhất trong khi
  thật ra là `joy` thì cả câu bị loại
- **Nói đã chạy một phép kiểm chưa hề chạy.** *"T-test cho thấy khác biệt đáng kể"* mà
  không có phép t-test nào thì bị loại
- **Suy diễn nhân quả** từ số liệu chỉ đo được mối liên hệ
- **Xin dữ liệu không liên quan.** Hỏi về cảm xúc mà xin *"doanh số 2024"* thì bị loại
- **Trả lời nửa câu hỏi mà không nói.** Hỏi cao nhất *và* thấp nhất mà chỉ trả lời được
  một vế thì nó nói rõ vế còn lại bỏ ngỏ

Và thứ **không** tìm ra được thì luôn được ghi ngang hàng với thứ tìm ra. Một kết luận
vắt qua một lỗ hổng không ai nhắc tới là thứ cả hệ thống này dựng lên để ngăn.

---

## Ai làm gì

**Manager** không tự tính gì cả. Nó đọc câu hỏi, chia thành việc nhỏ, giao đúng agent,
rồi tổng hợp. Nó chạy trên model mạnh nhất vì đây là việc suy luận khó nhất.

**Các agent chuyên trách** mỗi con làm một việc:

| | Làm gì | Dùng AI? |
|---|---|---|
| A1 Ingest | đọc file thành bảng | Không |
| A2 Profiler | đo dữ liệu có gì, thiếu gì | Có, chỉ để diễn giải |
| A3 Cleaner | **đề xuất** luật làm sạch | Có, chỉ để đề xuất |
| A4 Transformer | dựng bảng phân tích bằng SQL | Có |
| A5 Validator | chấm dữ liệu theo tiêu chí đã khai | **Không** |
| A6 Process Miner | đo quy trình chạy ra sao | Có, chỉ để đặt tên |
| A7 Analyst | rút ra kết luận từ số đã tính | Có, chỉ để diễn giải |
| A8 Reporter | viết báo cáo | Có |
| A10 Text Miner | đếm từ, đo từ nào đặc trưng | **Không** |
| E1-E4 | đọc PDF, ảnh, âm thanh, tài liệu | **Không** |

Những chỗ ghi **Không** là cố ý: đếm từ và chấm điểm dữ liệu là **số học**. Một model
được hỏi *"từ nào quan trọng"* sẽ trả lời rất tự tin, không lặp lại được, và không có gì
để đối chiếu, trong khi các con số thì tính lại lúc nào cũng ra.

---

## Bảo mật và vận hành tại chỗ

Hệ thống được thiết kế để chạy trong mạng của bạn, trên máy của bạn.

**Dữ liệu ở đâu.** Toàn bộ dữ liệu nằm trên đĩa cục bộ, chia theo tầng
`raw → extracted → staging → clean → mart`, lưu bằng Parquet và đọc bằng DuckDB ngay
trong tiến trình. Không có máy chủ cơ sở dữ liệu ngoài, không có kho đám mây. Đường dẫn
từng tầng khai báo độc lập trong `config/settings.yaml`, nên trỏ một tầng sang ổ khác
không phải sửa một dòng code nào.

**Dữ liệu có rời khỏi máy không.** Ở chế độ `provider: handoff` thì **không**. Hệ thống
ghi câu hỏi ra file để bạn tự dán vào tài khoản AI của mình. Cấu hình trong repo đang bật
`openrouter` (bản trả phí) để hệ thống tự trả lời; đổi một dòng trong
`config/settings.yaml` là về `handoff`. Khi bật một provider gọi API thật, mỗi lượt gửi đều đi qua trần token, trần tiền và trần thời gian;
`config/settings.yaml` ghi rõ provider nào dùng dữ liệu gửi lên để huấn luyện, kèm cảnh
báo đừng dùng provider đó với dữ liệu khách hàng.

**Phạm vi của agent.** Mỗi agent chạy với một `ScopeToken` cấp theo manifest, và
`core/boundary.py` kiểm ba lớp: trước khi chạy, trong lúc chạy, và trên kết quả trả về.
*Nói thẳng giới hạn:* các agent chạy cùng tiến trình với Manager, nên lớp lúc chạy là một
hộp cát hợp tác chứ không phải hộp cát ở mức hệ điều hành. Nó được chống lưng bằng một
quy tắc lint và một test AST chặn agent với tay xuống hệ thống tệp sau lưng.

**SQL do model viết.** Không chạy cho tới khi `sql_guard` cho phép: chỉ `SELECT` và
`CREATE VIEW`, cấm `DROP` `DELETE` `UPDATE` `ATTACH`, cấm chạm bảng ngoài phạm vi được
giao, cấm cross join không điều kiện. Đây là tuyến phòng thủ thứ nhất trong hai tuyến:
A4 chạy truy vấn trên một cơ sở dữ liệu trong bộ nhớ nạp từ Parquet, nên kể cả có câu
nào lọt qua thì cũng không có gì bền vững để phá.

**Nhật ký kiểm toán.** `core/audit.py` ghi mỗi việc đã xảy ra thành một dòng JSON, chỉ
ghi thêm, không bao giờ sửa dòng cũ. Một lượt chạy được coi là sạch khi nhật ký không còn
`BOUNDARY_VIOLATION` nào chưa xử lý.

**Bề mặt mạng.** Backend FastAPI chỉ nghe `127.0.0.1:8020`; Next.js là cổng duy nhất mở
ra mạng. Đăng nhập bằng một mật khẩu, phiên giữ trong bộ nhớ tiến trình nên khởi động lại
máy chủ là hết phiên.

**Bí mật.** Khoá API và mật khẩu chỉ nằm trong `.env` (đã gitignore), không bao giờ có
trong `.env.example`. `scripts/secret_scan.py` quét diff trước mỗi lần commit.

**Dữ liệu cá nhân.** `core/pii.py` dò các trường nhạy cảm, `core/hashing.py` băm ẩn danh
khi cần. `core/retention.py` quản vòng đời: xoá là việc phải gõ tay xác nhận, và chỉ đụng
tới giấy tờ làm việc của một lượt chạy, không bao giờ đụng dữ liệu gốc của bạn.

---

## Chất lượng mã nguồn

Mỗi lần commit đều phải qua đủ các cổng dưới đây. Trượt cổng nào thì dừng.

| Cổng | Lệnh | Kết quả hiện tại |
|---|---|---|
| Lint và định dạng | `ruff check` | sạch |
| Kiểu tĩnh | `mypy src tests` (strict) | 0 lỗi trên 294 file |
| Toàn bộ test | `pytest` | 2.985 qua, 2 bỏ qua (cần file log có giấy phép) — đo 18/09/2026 |
| Độ phủ | `pytest --cov` | **90,7%**, 1.327 / 14.326 câu lệnh chưa phủ — đo 18/09/2026 |
| Kiến trúc | `pytest tests/unit/test_architecture.py` | 0 vi phạm tầng |
| Triển khai | `docker compose build` và curl | `/` 200 · `/api/health` 200 · `/api/data` 401 |
| Bí mật | `python scripts/secret_scan.py` | sạch |

Bộ test chia theo vai trò, không chia theo file mã nguồn:

- **unit** kiểm từng module một
- **contract** kiểm hợp đồng vào và ra của từng agent, để đổi ruột agent không làm gãy
  người gọi
- **criteria** kiểm bốn tiêu chí S1-S4 của đặc tả, trong đó S4 đòi mọi con số truy nguyên
  được về dòng dữ liệu gốc
- **golden** giữ kết quả chuẩn trên dữ liệu mẫu
- **regression** giữ lại từng lỗi đã gặp, để nó không quay lại

---

## Chi phí vận hành

Ở chế độ `provider: handoff`, **không gọi API nào, $0**. Hệ thống ghi câu hỏi ra file,
bạn dán vào tài khoản AI của mình rồi dán kết quả về.

Cấu hình trong repo đang dùng `openrouter` để tự động trả lời. Toàn bộ quá trình thử
nghiệm trên dữ liệu thật tốn **$7,57 cho 220 lượt gọi model** (cộng từ các file
`budget.json`, 06–16/09/2026). Mọi lượt chạy đều có trần
token, trần tiền và trần thời gian. Chạm trần là **dừng**, không bao giờ tự chạy tiếp.

### Dọn dẹp

```bash
asys runs                          # xem các lần chạy đang chiếm bao nhiêu
asys forget --giu 10               # LIỆT KÊ những gì sẽ xoá
asys forget --giu 10 --xac-nhan    # xoá thật
```

Không có `--xac-nhan` thì không xoá gì. Dữ liệu gốc của bạn không bao giờ bị đụng tới.

---

## Tài liệu

| | |
|---|---|
| Cài đặt, triển khai | [DEPLOY.md](DEPLOY.md) |
| Tiến độ từng phần | [PROGRESS.md](PROGRESS.md) |
| Đặc tả gốc | [BUILD_SPEC.md](BUILD_SPEC.md) |
| Kế hoạch tái cấu trúc DDD | [plans/refactor-ddd.md](plans/refactor-ddd.md) |
| **81 lỗi đã gặp và cách sửa** | [NOTES.md](NOTES.md) |

`NOTES.md` đáng đọc nhất nếu bạn muốn biết vì sao hệ thống được làm như vậy. Nó ghi lại
từng lỗi đúng như lúc gặp, không viết lại cho đẹp, gồm cả những lỗi mà mọi bài kiểm tra
đều cho qua và chỉ lộ ra khi chạy trên dữ liệu thật.
