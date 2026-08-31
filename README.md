# analysis-system

Hệ thống xử lý dữ liệu multi-agent phục vụ Business Analysis, trọng tâm là process mining
trên event log.

**Trạng thái: Phase 0 ✅ · Phase 1 ✅ · Phase 2 ✅** — 8 agent, planner sinh DAG bằng LLM,
2 human gate, golden test tất định.
**495 test pass · coverage 92% · `python3 tasks.py check` sạch · chi phí API tới nay: $0.**

| | |
|---|---|
| Cài và deploy | **[DEPLOY.md](DEPLOY.md)** — Ubuntu Server 24.04, từ server trắng đến lần chạy đầu |
| Tiến độ và checklist | [PROGRESS.md](PROGRESS.md) |
| Đặc tả đầy đủ | [BUILD_SPEC.md](BUILD_SPEC.md) |
| Quyết định thiết kế, lỗi đã gặp | [NOTES.md](NOTES.md) — 48 quyết định, 16 lỗi |

---

## Ý tưởng

Một model ngôn ngữ **đề xuất**; code **quyết định**. Ranh giới đó được cưỡng chế ở mọi chỗ
model chạm vào dữ liệu:

- **Boundary 3 lớp.** Mỗi agent có một manifest khai báo nó đọc tầng nào, ghi tầng nào, dùng
  công cụ gì. Token quyền được *cắt ra từ* manifest chứ không lắp tay, nên không thể cấp rộng
  hơn manifest. Kiểm tra trước khi chạy, lúc chạy, và sau khi chạy.
- **Chống bịa số bằng hình dạng.** Model viết câu có chỗ trống `{price.mean}`; code thay số.
  Câu nào có **chữ số model tự gõ** thì bị loại, không phải sửa — sửa nghĩa là tự đoán nó
  định nói gì.
- **SQL do model sinh, chạy trên DuckDB in-memory.** Qua guard chặn 19 từ khoá phá huỷ, chặn
  lệnh thứ hai sau `;`, chặn `CROSS JOIN`, chặn bảng không được cấp. Rồi chạy trên một database
  dựng tạm và vứt đi.
- **Human gate là dữ liệu, không phải câu hỏi.** Gate ghi ra file rồi thoát mã 0. Quyết định
  lưu vào state và **phát lại** khi chạy lại — nhờ vậy một lần chạy có người duyệt ở giữa vẫn
  tái lập được (tiêu chí S1).

---

## Các agent

| Agent | LLM? | Đọc | Ghi | Việc |
|---|---|---|---|---|
| **A1 Ingest** | Không | `raw://` `extracted://` | `staging://` | Nạp CSV/TSV/Parquet/JSON/JSONL/XLSX, tự nhận encoding và delimiter |
| **A2 Profiler** | Có (diễn giải) | `staging://` | `profile://` | Code đo, model chỉ đặt tên và diễn giải |
| **A3 Cleaner** | Có (đề xuất) | `staging://` `profile://` | `clean://` | Đề xuất rule → **GATE 1** → chỉ chạy rule đã duyệt |
| **A4 Transformer** | Có (sinh SQL) | `clean://` | `mart://` | Sinh SQL, guard + DuckDB in-memory, lineage do model khai và code kiểm |
| **A5 Validator** | **Không** | mọi tầng trừ `raw://` | `validation://` | Trọng tài. Cấm LLM tuyệt đối, và không được sửa dữ liệu cho pass |
| **A7 Analyst** | Có (diễn giải) | `mart://` | `artifacts://` | Code tính chỉ số, model viết câu có placeholder → **GATE 2** |
| **A8 Reporter** | Có (viết văn) | `mart://` `artifacts://` | `artifacts://` | Markdown + HTML + biểu đồ PNG tất định |

A0 Router, A6 Process Miner và E1–E4 extractor thuộc Phase 4/5 — xem [PROGRESS.md](PROGRESS.md).

---

## Chạy nhanh

```bash
./scripts/install.sh
source .venv/bin/activate

asys check-config
asys plan "Chi tiêu theo mảng ra sao?" --source raw://dulieu.csv --out plan.json
asys run-dag --input ~/analysis-data/raw/dulieu.csv --plan plan.json --run-id r1

asys gates r1                                        # xem cần duyệt gì
asys approve r1 --gate gate_t3_clean --select trim_whitespace
asys resume-dag r1                                   # chạy tiếp
```

Chi tiết từng bước, systemd timer, sao lưu, xử lý lỗi: **[DEPLOY.md](DEPLOY.md)**.

---

## Chi phí

`llm.provider` trong [config/settings.yaml](config/settings.yaml) quyết định có tốn tiền không:

| provider | Chi phí | Dùng khi |
|---|---|---|
| `handoff` | **0đ** | Ghi prompt ra file, người dán vào Claude (gói Pro) |
| `cassette` | **0đ** | Phát lại câu trả lời đã ghi — mọi test dùng cái này |
| `none` | **0đ** | Chỉ chạy phần code thuần |
| `anthropic` | **có tính tiền** | Chạy tự động không người trực |

Khi bật `anthropic`: khoảng **$0.05 mỗi lần chạy**, và con số đó **không tăng theo số dòng dữ
liệu** — model chỉ thấy schema, thống kê, và tối đa 20 dòng mẫu. A4, A7, A8 không nhìn một dòng
dữ liệu nào (`max_sample_rows: 0`).

---

## Lệnh

`tasks.py` là nguồn chân lý; `Makefile` chỉ là vỏ mỏng gọi lại nó, nên hai bên không lệch nhau.

| Lệnh | Việc |
|---|---|
| `python3 tasks.py check` | lint + typecheck + test — **cổng bắt buộc của mọi phase** |
| `python3 tasks.py lint` | ruff check + ruff format --check |
| `python3 tasks.py typecheck` | mypy strict |
| `python3 tasks.py test` | pytest + coverage |
| `python3 tasks.py clean` | xoá cache — không bao giờ đụng tới dữ liệu |

---

## Tính tất định (tiêu chí S1)

"Chạy lại cùng input ra cùng output" được định nghĩa bằng
[`services/hashing.py`](src/analysis_system/services/hashing.py), không phải bằng byte của file:

- **Không** hash byte Parquet — pyarrow nhúng metadata phiên bản nên hai lần ghi có thể khác byte.
- `canonical_hash(df)` chuẩn hoá từng ô về text, sắp xếp cả dòng lẫn cột rồi băm SHA-256.
- `canonical_hash_text(report)` loại các dòng chứa `run_id`, `timestamp`, `duration`, `cost`.
- Backoff khi retry **không có jitter** — jitter sẽ làm hai lần chạy khác nhau.
- Biểu đồ PNG xoá timestamp matplotlib nhúng vào, nên cùng số vẽ ra cùng byte.
- `tasks.py` đặt `PYTHONHASHSEED=0` cho mọi lệnh con.

Golden test chạy **toàn bộ DAG 7 agent** trên dữ liệu BPI thật, hai lần, khác `run_id` và khác
thư mục — và bắt buộc trùng từng hash.

---

## Dữ liệu test

Fixture lấy từ **BPI Challenge 2019** — event log Purchase-to-Pay thật, không phải dữ liệu tự
sinh. File gốc (`BPI_Challenge_2019.xes`, 694 MB) **không commit vào git**;
`scripts/make_fixture.py` cắt ra một lát bất biến (158 case · 5.000 event · 84 variant, cắt
trọn case chứ không cắt ngang), và chính lát đó được commit.

Dùng dữ liệu thật đã bắt được lỗi mà dữ liệu tự sinh không bao giờ bắt được — ví dụ
`guess_roles` khớp `"case"` bên trong `"case_company"` và gán `case_id = "case_company"`, sai
lặng lẽ toàn bộ phân tích variant về sau. Chi tiết trong [NOTES.md](NOTES.md).

Trích dẫn bắt buộc khi dùng bộ dữ liệu này:

> van Dongen, B.F., *Dataset BPI Challenge 2019*. 4TU.Centre for Research Data.
> https://doi.org/10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1

---

## Giới hạn đã biết

- Agent chạy **cùng tiến trình** với Manager, nên lớp cưỡng chế boundary lúc chạy là
  *cooperative sandbox*, không phải cưỡng chế ở mức hệ điều hành. Nâng lên subprocess isolation
  là việc của Phase 3.
- SQL guard chặn theo **từ khoá và định danh**, không phải parser đầy đủ. Lớp phòng thủ thật là
  DuckDB in-memory chạy xong rồi vứt.
- `provider: anthropic` **chưa từng gọi endpoint thật** — mới chỉ test bằng client giả.
