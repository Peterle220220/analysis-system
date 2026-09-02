# analysis-system

Hệ thống xử lý dữ liệu multi-agent phục vụ Business Analysis, trọng tâm process mining
trên event log.

**Phase 0 ✅ · Phase 1 ✅ · Phase 2 ✅ · Phase 3 ✅ · Phase 4a ✅** — 8 agent, planner sinh DAG
bằng LLM, 2 human gate, thống kê suy diễn, khai thác quy trình, **chọn đặc trưng để phân
tích**, Docker chạy được.

**927 test · coverage 92% · `python3 tasks.py check` sạch · chi phí API tới nay: $0.**

| | |
|---|---|
| Cài và deploy | **[DEPLOY.md](DEPLOY.md)** — Ubuntu Server 24.04 và Docker |
| Tiến độ, checklist | [PROGRESS.md](PROGRESS.md) |
| Đặc tả đầy đủ | [BUILD_SPEC.md](BUILD_SPEC.md) |
| Quyết định thiết kế, lỗi đã gặp | [NOTES.md](NOTES.md) — 74 quyết định, 54 lỗi |

---

## Ý tưởng

Một model ngôn ngữ **đề xuất**; code **quyết định**. Ranh giới đó được cưỡng chế ở mọi
chỗ model chạm vào dữ liệu — không phải bằng lời nhắc trong prompt, mà bằng những lớp
kiểm mà model không đi vòng được.

---

## Chọn cái gì để phân tích

Đơn vị là **đặc trưng**, không phải cột. Bảng → cột · event log → hoạt động và người thực
hiện · (sau này) ảnh → vật thể · audio → người nói. Một cơ chế xây quanh "cột" sẽ phải vứt
đi ngay lần đầu đầu vào không còn là bảng.

Agent **tự khai** trong manifest tham số nào ăn đặc trưng. Đổi lựa chọn thì **đúng** những
task bị đổi lệnh chạy lại, và task phía sau chạy lại vì đầu vào khác — không phải nhờ code
theo dõi phụ thuộc, mà vì tham số nằm trong **danh tính** của task.

Tên đặc trưng không có trong dữ liệu thì **bị từ chối**. Phân tích bốn cái gõ đúng rồi im
lặng bỏ cái gõ sai là cách một người đọc được câu trả lời cho câu hỏi khác.

---

## Kiến trúc

```
                        ┌──────────────────────────────┐
                        │          MANAGER             │
   raw://file.csv ─────▶│  planner · dispatcher        │
                        │  verifier · state · gates    │
                        └───────┬──────────────────────┘
                                │ ScopeToken cắt từ manifest
        ┌───────────────────────┼───────────────────────────────┐
        ▼                       ▼                               ▼
   ┌─────────┐            ┌──────────┐                    ┌──────────┐
   │ A1 nạp  │            │ A4 SQL   │                    │ A7 phân  │
   │ A2 mô tả│            │ A5 chấm  │                    │ A8 báo   │
   │ A3 sạch │            │          │                    │   cáo    │
   └────┬────┘            └────┬─────┘                    └────┬─────┘
        │                      │                               │
        ▼                      ▼                               ▼
   staging:// ──▶ clean:// ──▶ mart:// ──▶ validation:// ──▶ artifacts://
                     ▲                          │
                     │                          ▼
              HUMAN GATE 1                 cổng rẽ nhánh:
              (duyệt rule)                 không đạt → DỪNG
                                                │
                                          HUMAN GATE 2
                                          (duyệt kết luận)
```

### Bốn lớp cưỡng chế

**1. Boundary 3 lớp.** Mỗi agent có manifest khai nó đọc tầng nào, ghi tầng nào, dùng công
cụ gì. Token quyền **cắt ra từ** manifest chứ không lắp tay — nên không thể cấp rộng hơn
manifest. Kiểm trước khi chạy, lúc chạy, và sau khi chạy. Một test AST chặn agent gọi
thẳng `open`, `os`, `pathlib`, `pd.read_*`, `duckdb.connect`.

**2. Chống bịa số bằng hình dạng.** Model viết `{price.mean}`; code thay số. Câu nào chứa
**chữ số model tự gõ** thì **bị loại**, không phải sửa — sửa nghĩa là tự đoán nó định nói
gì. Áp cho cả kết luận lẫn phần tóm tắt.

**3. SQL do model sinh, chạy trên DuckDB dựng-rồi-vứt.** Qua guard chặn 19 từ khoá phá
huỷ, chặn lệnh thứ hai sau `;`, chặn `CROSS JOIN`, chặn bảng không được cấp. Lineage do
model khai, code kiểm lại.

**4. Human gate là dữ liệu, không phải câu hỏi.** Gate ghi ra file rồi thoát mã 0. Quyết
định lưu vào state và **phát lại** khi chạy lại — nhờ vậy một lần chạy có người duyệt ở
giữa vẫn tái lập được (tiêu chí S1). Quyết định gắn với **kết quả nó phán xét**: task chạy
lại ra kết luận khác thì phê duyệt cũ hết hiệu lực và gate được hỏi lại.

---

## Các agent

| Agent | LLM? | Đọc | Ghi | Việc |
|---|---|---|---|---|
| **A1 Ingest** | Không | `raw://` | `staging://` | 6 định dạng, tự nhận encoding và delimiter |
| **A2 Profiler** | Diễn giải | `staging://` | `profile://` | Code đo, model đặt tên |
| **A3 Cleaner** | Đề xuất | `staging://` | `clean://` | 7 rule → **GATE 1** → chỉ chạy rule đã duyệt |
| **A4 Transformer** | Sinh SQL | `clean://` | `mart://` | Guard + DuckDB in-memory. Câu lệnh lưu cạnh bảng |
| **A5 Validator** | **Cấm** | mọi tầng trừ `raw://` | `validation://` | Trọng tài. Không đạt → **dừng cả lần chạy**. Kiểm cả thứ tự bắt buộc và phân tách trách nhiệm |
| **A6 Process Miner** | Đặt tên | `clean://` `mart://` | `artifacts://` | Variant · điểm nghẽn · rework. **Không kết luận gì** |
| **A7 Analyst** | Diễn giải | `mart://` | `artifacts://` | Code tính chỉ số + thống kê → **GATE 2** |
| **A8 Reporter** | Viết văn | `mart://` `artifacts://` | `artifacts://` | Markdown + HTML + PNG tất định |

---

## Thống kê

Mô tả (`services/metrics.py`) và suy diễn (`services/statistics.py`) — tất cả đều là **chỉ
số có tên**, nên cơ chế chống bịa số chạy nguyên không sửa gì.

```
rows.total · {cột}.mean .median .min .max · {nhóm}.{giá trị}.share_pct
process.cases · .events · .variants · process.variant.{n}.share_pct
process.rework.cases_pct · process.duration.median_hours
process.wait.{a}__to__{b}.median_hours · .observations
{đo}.mean.by.{nhóm}.{giá trị}
{a}.corr.with.{b} · .p_value · .r2 · {a}.rank_corr.with.{b}
{đo}.ttest.by.{nhóm}.p_value · .effect_size · .anova. · .eta_sq
{y}.coef.{x} · .p_value · {y}.vif.{x} · {y}.regression.r2_adj
```

**Phần từ chối quan trọng hơn phần tính.** Dưới 8 cặp, nhóm dưới 5 dòng, trên 20 nhóm, cột
không đổi giá trị, dưới 10 dòng mỗi biến hồi quy, hai biến trùng lặp hoàn toàn — **từ chối
kèm lý do**, không tính bừa rồi in ba chữ số thập phân.

**Tương quan không được viết thành nhân quả.** `causal_overreach()` từ chối câu dùng "làm
tăng", "khiến", "tác động đến" khi chỉ số chỉ đo mối liên hệ, và nói luôn cách viết đúng.

**Không có ML dự đoán** — một dự đoán truy ngược về *một mô hình và một hạt giống ngẫu
nhiên*, không về dòng dữ liệu nào, nên nó cần một câu trả lời khác cho tiêu chí S4.

---

## Sáu tiêu chí nghiệm thu

| | Tiêu chí | Test |
|---|---|---|
| **S1** | Chạy lại cùng input ra cùng output | `tests/criteria/test_s1_s2.py` |
| **S2** | Không agent nào vượt boundary | `tests/criteria/test_s1_s2.py` |
| **S3** | Resume được từ bước lỗi | `tests/criteria/test_s3_s4_s5.py` |
| **S4** | Mọi kết luận truy ngược được | `tests/criteria/test_s3_s4_s5.py` |
| **S5** | Không vượt ngân sách | `tests/criteria/test_s3_s4_s5.py` |
| **S6** | Trích xuất kém không lọt âm thầm | Phase 5 |

Mỗi tiêu chí kiểm **cả hai chiều**: S1 kiểm hai lần chạy trùng hash **và** đổi một ô thì
hash phải khác. Thiếu vế sau thì một hàm hash trả về hằng số cũng pass.

---

## Chạy nhanh

```bash
./scripts/install.sh && source .venv/bin/activate

asys check-config
asys plan "Cau hoi cua ban" --source raw://dulieu.csv --out plan.json
asys run-dag --input ~/analysis-data/raw/dulieu.csv --plan plan.json --run-id r1

asys gates r1                                   # xem cần duyệt gì
asys approve r1 --gate gate_t3_clean --select trim_whitespace
asys resume-dag r1

asys clean --input ~/analysis-data/raw/dulieu.csv --run-id hs   # -> bang sach
asys ask hs "Cau hoi cua ban"                   # hoi bao nhieu lan cung duoc

asys features r1                                # xem chon duoc nhung gi
asys select r1 --feature column:diem --feature column:gio_hoc
asys resume-dag r1                              # chi chay lai phan bi anh huong

asys export mart://ket_qua.parquet --out ~/ket_qua.csv
```

Hoặc bằng Docker — xem [DEPLOY.md](DEPLOY.md).

---

## Chi phí

`llm.provider` quyết định có tốn tiền không:

| provider | Chi phí | Dùng khi |
|---|---|---|
| `handoff` | **0đ** | Ghi prompt ra file, người dán vào Claude (gói Pro) |
| `cassette` | **0đ** | Phát lại câu trả lời đã ghi — mọi test dùng cái này |
| `gemini` | **0đ** bậc free | ⚠️ Google dùng dữ liệu gửi lên để huấn luyện |
| `anthropic` | **có tính tiền** | Chạy tự động không người trực |
| `none` | **0đ** | Chỉ chạy phần code thuần |

Trần token/tiền/thời gian áp cho **mọi** provider gọi ra ngoài, đếm trong `LlmClient` để
không provider nào bỏ qua được. Chạm trần → dừng, thoát mã 1.

---

## Lệnh

`tasks.py` là nguồn chân lý; `Makefile` chỉ là vỏ mỏng gọi lại nó.

| Lệnh | Việc |
|---|---|
| `python3 tasks.py check` | lint + typecheck + test — **cổng bắt buộc của mọi phase** |
| `python3 tasks.py lint` / `typecheck` / `test` | từng phần |
| `python3 tasks.py clean` | xoá cache — không bao giờ đụng dữ liệu |

---

## Tính tất định (S1)

"Chạy lại cùng input ra cùng output" định nghĩa bằng
[`services/hashing.py`](src/analysis_system/services/hashing.py), **không** bằng byte của file:

- Không hash byte Parquet — pyarrow nhúng metadata phiên bản
- `canonical_hash(df)` chuẩn hoá từng ô về text, sắp xếp dòng và cột, rồi băm SHA-256
- `canonical_hash_text` loại các dòng chứa `run_id`, `timestamp`, `duration`, `cost`
- Backoff khi retry **không có jitter** — jitter làm hai lần chạy khác nhau
- PNG xoá timestamp matplotlib nhúng vào
- `PYTHONHASHSEED=0` ở mọi lệnh con và trong image

---

## Dữ liệu test

Fixture cắt từ **BPI Challenge 2019** — event log Purchase-to-Pay thật, cắt trọn case
(158 case · 5.000 event · 84 variant). File gốc 694 MB không commit.

Dùng dữ liệu thật đã bắt được lỗi mà dữ liệu tự sinh không bao giờ bắt được — `guess_roles`
khớp `"case"` bên trong `"case_company"`, gán `case_id = "case_company"`, sai lặng lẽ toàn bộ
phân tích variant về sau.

> van Dongen, B.F., *Dataset BPI Challenge 2019*. 4TU.Centre for Research Data.
> https://doi.org/10.4121/uuid:d06aff4b-79f0-45e6-8ec8-e19730c248f1

---

## Giới hạn đã biết

- Agent chạy **cùng tiến trình** với Manager, nên lớp cưỡng chế lúc chạy là *cooperative
  sandbox*, không phải cưỡng chế mức hệ điều hành. Trong Docker thì user và
  `cap_drop: ALL` là phần hệ điều hành cưỡng chế.
- SQL guard chặn theo **từ khoá và định danh**, không phải parser đầy đủ. Lớp phòng thủ
  thật là DuckDB in-memory chạy xong rồi vứt.
- `should_skip` so hash **ghi trong state**, không so hash trên đĩa — sửa tay một file
  trung gian không được phát hiện. Nguồn đổi thì được, và **tham số đổi cũng được** (L40).
- Khai thác quy trình cần **khai vai trò cột** (`event_log`), không tự đoán. A2 gợi ý,
  kế hoạch xác nhận — vì một lần đoán bằng so khớp mẫu đã gán sai `case_id` cho trọn
  một phân tích.
- `provider: anthropic` **chưa từng gọi endpoint thật** — mới test bằng client giả.
- Khai thác quy trình chỉ áp dụng cho dữ liệu **có ba cột** ca/bước/thời gian. Dữ liệu
  không có thì hệ thống bỏ qua A6 và chạy tiếp bình thường — 7/8 agent không cần tới nó.
- Điểm nghẽn xếp theo **tổng thời gian quy trình mất**, không theo thời gian chờ điển
  hình: xếp theo trung vị đưa những bước quan sát được ba lần lên đầu bảng.
