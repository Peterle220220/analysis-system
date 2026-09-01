# Deploy lên Ubuntu Server 24.04

Hướng dẫn này đi từ một server trắng đến một lần chạy hoàn chỉnh. Mọi lệnh đều chạy dưới
**user thường**, không phải root.

Hệ thống này là một **CLI chạy theo lần**, không phải web service: không có port nào để mở,
không có daemon nào phải sống mãi. Nếu muốn chạy theo lịch thì dùng systemd timer — mục 8.

---

## 0. Đẩy code lên GitHub (làm trên máy đang dev)

Repo chưa có commit nào. Từ thư mục dự án:

```bash
git add -A
git commit -m "Phase 0-2: multi-agent data processing system"
```

Tạo repo rỗng trên github.com (**không** tick "Add a README"), rồi:

```bash
git remote add origin git@github.com:<tài-khoản>/analysis-system.git
git branch -M main
git push -u origin main
```

Dùng HTTPS thay vì SSH thì đổi URL thành `https://github.com/<tài-khoản>/analysis-system.git`
và đăng nhập bằng **personal access token**, không phải mật khẩu.

> **Không có bí mật nào trong repo.** `.env` bị `.gitignore` chặn; khoá API chỉ đọc từ biến
> môi trường. Kiểm tra trước khi push — lệnh này quét mọi định dạng khoá đang dùng:
>
> ```bash
> git grep -nE '(sk-ant-|AIza|AQ\.)[0-9A-Za-z._-]{20,}'
> ```
>
> Phải không ra gì. **Ghi khoá vào `.env`, không phải `.env.example`** — file `.example` là
> bản mẫu và **có** trong git; khoá đặt nhầm vào đó sẽ theo commit lên GitHub.

---

## 1. Server cần gì

| | Yêu cầu |
|---|---|
| OS | Ubuntu Server 24.04 LTS |
| Python | 3.11 trở lên — 24.04 có sẵn 3.12.3 |
| RAM | 2 GB cho dữ liệu cỡ fixture; **4 GB+** nếu event log vài triệu dòng |
| Đĩa | Code ~50 MB · thư viện ~500 MB · dữ liệu tuỳ bạn |
| Mạng | Chỉ cần lúc cài. Lúc chạy **không cần mạng**, trừ khi bật `provider: anthropic` |

```bash
sudo apt update
sudo apt install -y python3-venv git
```

Không cần `build-essential`: pandas, pyarrow, duckdb và matplotlib đều có sẵn wheel cho
Python 3.12 trên x86-64. Nếu server là ARM64 và pip phải build từ nguồn thì cài thêm
`build-essential python3-dev`.

---

## 2. Lấy code và cài

```bash
git clone https://github.com/<tài-khoản>/analysis-system.git
cd analysis-system

# Mặc định: dữ liệu ở ~/analysis-data, lần chạy ở ~/analysis-runs
./scripts/install.sh

# Hoặc đặt chỗ khác:
ANALYSIS_DATA=/srv/analysis-data ANALYSIS_RUNS=/srv/analysis-runs ./scripts/install.sh
```

Script này chạy lại bao nhiêu lần cũng được. Nó tạo `.venv`, cài **đúng** bộ thư viện trong
`requirements.lock.txt` (không phải khoảng phiên bản trong `pyproject.toml` — một bản vá của
thư viện khác có thể đổi hành vi mà không ai chọn), tạo 9 tầng dữ liệu, rồi tự kiểm tra.

Cài xong có lệnh `asys`:

```bash
source .venv/bin/activate
asys --help
```

---

## 3. Dữ liệu nằm ngoài repo — cố ý

```
~/analysis-system/     ← repo, CHỈ chứa code
~/analysis-data/       ← raw · extracted · staging · clean · mart
                          profile · validation · artifacts
~/analysis-runs/       ← <run_id>/ : state.json · audit.jsonl · gates/ · plan.json
```

Đường dẫn **từng tầng** khai báo độc lập trong [config/settings.yaml](config/settings.yaml),
không suy ra từ một thư mục gốc chung. Nhờ vậy trỏ riêng một tầng sang ổ khác (ví dụ `mart`
sang SSD) chỉ là sửa một dòng, không đụng code.

Hai biến môi trường điều khiển vị trí mặc định:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ANALYSIS_DATA` | `~/analysis-data` | Gốc của 8 tầng dữ liệu |
| `ANALYSIS_RUNS` | `~/analysis-runs` | Nơi ghi lại từng lần chạy |
| `ANALYSIS_SYSTEM_CONFIG` | (trống) | Dùng file cấu hình khác thay cho file trong repo |

Đặt cố định cho user:

```bash
echo 'export ANALYSIS_DATA=/srv/analysis-data' >> ~/.bashrc
echo 'export ANALYSIS_RUNS=/srv/analysis-runs' >> ~/.bashrc
```

**Chương trình không bao giờ tự tạo tầng dữ liệu.** Tầng thiếu là lỗi cấu hình phải sửa, không
phải thứ để lặng lẽ vá — `asys check-config` sẽ báo đúng tầng nào thiếu rồi thoát.

---

## 4. Chọn provider — đây là chỗ quyết định có tốn tiền không

Trong `config/settings.yaml`, mục `llm.provider`:

| provider | Làm gì | Chi phí | Dùng khi |
|---|---|---|---|
| `handoff` | Ghi prompt ra file, người dán vào Claude rồi lưu câu trả lời | **0đ** | Có gói Claude Pro, chạy tay |
| `cassette` | Phát lại câu trả lời đã ghi | **0đ** | Test, chạy lại y hệt |
| `anthropic` | Gọi API thật | **Có tính tiền** | Chạy tự động không người trực |
| `none` | Không dùng model | **0đ** | Chỉ chạy phần code thuần |

Trên server chạy tự động thì hầu như luôn là `anthropic`:

```bash
cp .env.example .env
# sửa .env, điền ANTHROPIC_API_KEY
chmod 600 .env
```

```yaml
llm:
  provider: anthropic
  dev_mode: true      # true -> ép cả hai vai trò về worker_model cho rẻ
```

Khoá đọc từ biến môi trường `ANTHROPIC_API_KEY`, **không bao giờ** từ file cấu hình trong git.

> `provider: handoff` không chạy tự động được: nó **dừng lại** và chờ người dán câu trả lời.
> Trên server không người trực, đây là lỗi cấu hình thường gặp nhất.

---

## 5. Kiểm tra trước khi tin

```bash
source .venv/bin/activate
asys check-config          # 9 tầng có đủ và ghi được không
python3 tasks.py check     # lint + typecheck + 495 test, khoảng 2 phút
```

`tasks.py check` là cổng bắt buộc. Nó chạy cả **golden test**: toàn bộ DAG 7 agent trên một
lát dữ liệu BPI Challenge 2019 thật, hai lần, khác `run_id` và khác thư mục — và bắt buộc
**trùng từng hash**. Nếu lệnh này sạch trên server thì hệ thống chạy đúng ở đó.

---

## 6. Chạy một việc thật

```bash
# 1. Đưa dữ liệu vào tầng raw
cp /đường/dẫn/dulieu.csv "$ANALYSIS_DATA/raw/"

# 2. Sinh kế hoạch (hoặc tự viết tay, xem mục 7)
asys plan "Chi tiêu theo mảng ra sao?" --source raw://dulieu.csv --out plan.json

# 3. Chạy — dừng ở HUMAN GATE 1
asys run-dag --input "$ANALYSIS_DATA/raw/dulieu.csv" --plan plan.json --run-id r1

# 4. Xem và duyệt
asys gates r1
asys approve r1 --gate gate_t3_clean --select trim_whitespace --reject cast_numeric_safe

# 5. Chạy tiếp — dừng ở HUMAN GATE 2 (duyệt kết luận)
asys resume-dag r1
asys gates r1
asys approve r1 --gate gate_t6_analyse --select f1 --select f3

# 6. Chạy nốt
asys resume-dag r1
```

Kết quả:

```
$ANALYSIS_DATA/artifacts/report/r1.md      báo cáo Markdown
$ANALYSIS_DATA/artifacts/report/r1.html    bản HTML, không cần mạng để mở
$ANALYSIS_DATA/mart/                       bảng đã dựng
$ANALYSIS_RUNS/r1/audit.jsonl              từng việc đã làm, ghi thêm không sửa
$ANALYSIS_RUNS/r1/state.json               trạng thái, để chạy tiếp được sau khi bị giết
```

Bị giết giữa chừng thì `asys resume-dag r1` chạy tiếp đúng chỗ đã dừng: task nào xong rồi và
dữ liệu vào không đổi thì bỏ qua, quyết định đã duyệt được **phát lại** chứ không hỏi lại.

---

## 7. Kế hoạch viết tay

`asys plan` cần model. Không có model thì viết tay — và kế hoạch viết tay **bị kiểm tra y hệt**
kế hoạch model viết: agent phải có manifest, `depends_on` phải trỏ task trong kế hoạch, cấm chu
trình, cấm trùng `task_id`, `inputs_from` phải trỏ task chắc chắn đã chạy xong.

```json
{
  "reason": "chi tiêu theo mảng",
  "tasks": [
    {"task_id": "t1_ingest", "agent_id": "a1_ingest",
     "params": {"target": "staging://events.parquet"}},
    {"task_id": "t2_profile", "agent_id": "a2_profiler", "depends_on": ["t1_ingest"]},
    {"task_id": "t3_clean", "agent_id": "a3_cleaner", "depends_on": ["t2_profile"],
     "inputs_from": ["t1_ingest"]},
    {"task_id": "t4_transform", "agent_id": "a4_transformer", "depends_on": ["t3_clean"],
     "params": {"target": "mart://spend.parquet",
                "sql": {"sql": "SELECT ... FROM events",
                        "target_table": "spend",
                        "lineage": [{"output": "...", "sources": ["..."]}]}}},
    {"task_id": "t5_validate", "agent_id": "a5_validator", "depends_on": ["t4_transform"],
     "params": {"checks": {"not_null": ["..."]}}}
  ]
}
```

`depends_on` là **thứ tự**, `inputs_from` là **dòng dữ liệu** — hai chuyện khác nhau. A7 phải
chạy *sau* kiểm định nhưng thứ nó *đọc* là bảng mart của A4, không phải báo cáo của A5.

---

## 8. Chạy theo lịch bằng systemd (tuỳ chọn)

Chỉ có nghĩa khi `provider: anthropic` — một lần chạy có human gate sẽ **dừng ở gate và thoát
mã 0**, và timer không thể duyệt hộ ai.

`/etc/systemd/system/analysis.service`:

```ini
[Unit]
Description=analysis-system - mot lan chay
After=network-online.target

[Service]
Type=oneshot
User=analysis
WorkingDirectory=/home/analysis/analysis-system
EnvironmentFile=/home/analysis/analysis-system/.env
ExecStart=/home/analysis/analysis-system/.venv/bin/asys run-dag \
    --input /srv/analysis-data/raw/dulieu.csv \
    --plan /home/analysis/plan.json \
    --run-id daily-%%i

# Chi duoc ghi vao dung hai cho nay
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=/srv/analysis-data /srv/analysis-runs
PrivateTmp=true
NoNewPrivileges=true
```

`/etc/systemd/system/analysis.timer`:

```ini
[Unit]
Description=Chay analysis-system moi ngay

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now analysis.timer
systemctl list-timers analysis.timer
journalctl -u analysis.service -n 50
```

`run_id` phải khác nhau mỗi lần, nếu không lần chạy sau sẽ được coi là **chạy tiếp** lần trước
và bỏ qua mọi task đã xong.

---

## 8b. Chạy bằng Docker (tuỳ chọn)

> ⚠️ **Chưa kiểm chứng.** Máy phát triển không cài Docker nên `Dockerfile` và
> `docker-compose.yml` mới chỉ được đọc kỹ, **chưa từng build hay chạy thử một lần nào**.
> Coi mục này là bản nháp cần anh chạy thử, không phải quy trình đã được xác nhận.

```bash
mkdir -p data/raw data/artifacts runs
cp <file dữ liệu> data/raw/

docker compose build
docker compose run --rm analysis check-config
docker compose run --rm analysis run-dag   --input /data/raw/students.csv --plan /data/raw/plan.json --run-id d1
```

### Cách gắn volume — có chủ đích, không tuỳ tiện

| Nơi | Kiểu | Vì sao |
|---|---|---|
| `data/raw` | bind mount **read-only** | Dữ liệu gốc là thứ duy nhất không tái tạo được. Container không có lý do gì để ghi vào đó, nên nó **không được phép** — cưỡng chế bởi hệ điều hành, không phải bởi thiện chí |
| `data/artifacts`, `runs` | bind mount đọc-ghi | Báo cáo sinh ra để người đọc; `runs` chứa audit log — bản ghi hệ thống đã làm gì |
| staging, clean, mart, profile, validation | **named volume** | Dữ liệu trung gian: dựng lại được từ `raw`, không ai cần nhìn, và để trong bind mount chỉ làm bẩn thư mục của anh |

### Những gì container bị siết

- **Không chạy bằng root** — user `analysis` (uid 10001)
- **Root filesystem read-only**, chỉ `/tmp` là tmpfs
- **`cap_drop: ALL`** và `no-new-privileges`
- Không mở cổng nào

Khoá API đọc từ `.env` của Docker Compose, **không bao giờ ghi vào image**.

## 9. Nâng cấp

```bash
cd ~/analysis-system
git pull
./scripts/install.sh      # cài lại theo lock file mới
python3 tasks.py check    # phải sạch trước khi tin bản mới
```

Dữ liệu không bị đụng tới: nó nằm ngoài repo.

---

## 10. Sao lưu

| Sao lưu | Vì sao |
|---|---|
| `$ANALYSIS_DATA/` | Dữ liệu. Tầng `raw` là thứ không tái tạo được. |
| `$ANALYSIS_RUNS/` | `audit.jsonl` là bản ghi hệ thống đã làm gì — dựng lại không được. |
| `config/settings.yaml` | Nếu đã sửa khác bản trong git. |

`staging`, `clean`, `mart` dựng lại được từ `raw` nếu còn `plan.json` và các quyết định trong
`state.json`. `raw` và `runs` thì không.

---

## 11. Gặp lỗi

| Hiện tượng | Nguyên nhân |
|---|---|
| `Cau hinh tang du lieu khong dung` | Thiếu thư mục. Chạy `./scripts/install.sh`, hoặc `ANALYSIS_DATA` chưa export trong phiên này. |
| `Duong dan dung bien ... khong duoc dat` | `settings.yaml` dùng một biến không có mặc định. Export nó, hoặc ghi đường dẫn tuyệt đối. |
| Dừng lại đòi "chuyen tiep cau hoi cho model" | `provider: handoff` trên môi trường không người trực. Đổi sang `anthropic`. |
| `Chua cai goi anthropic` | Cài thiếu. Chạy lại `./scripts/install.sh`. |
| `Ke hoach khong chay duoc: ...` | Kế hoạch sai — thông báo nói rõ sai chỗ nào. Nó bị từ chối **trước khi** chạy bất cứ thứ gì. |
| Chạy lại ra hash khác | Lỗi nghiêm trọng, phá tiêu chí S1. Chạy `python3 tasks.py check` và mở issue kèm output. |
| `Permission denied` khi ghi | User chạy không sở hữu `$ANALYSIS_DATA`. `sudo chown -R $USER: /srv/analysis-data` |

---

## 12. Giới hạn đã biết — nói trước cho rõ

- **Agent chạy cùng tiến trình với Manager.** Lớp cưỡng chế boundary lúc chạy là *cooperative
  sandbox*, không phải cưỡng chế ở mức hệ điều hành. Trên server dùng chung, hãy chạy dưới một
  user riêng với `ProtectSystem=strict` như mục 8.
- **SQL guard chặn theo từ khoá và định danh, không phải parser đầy đủ.** Lớp phòng thủ thật là
  DuckDB in-memory: query của model chạy trên một database dựng tạm rồi vứt, không đụng file nào.
- **`provider: anthropic` chưa từng gọi endpoint thật** — mới chỉ test bằng client giả. Lần đầu
  bật, hãy chạy một job nhỏ và xem `runs/<id>/audit.jsonl` để kiểm chứng chi phí.
