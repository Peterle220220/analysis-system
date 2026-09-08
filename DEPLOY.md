# Đưa hệ thống lên máy chủ Ubuntu

Hướng dẫn này đi từ **một máy Ubuntu trắng** đến **một dashboard chạy được và tự cập nhật**.

Mọi lệnh chạy dưới **user thường**, không phải root. Chỗ nào cần `sudo` sẽ ghi rõ.

Hệ thống này là một **web service** — có cổng, có tiến trình chạy liên tục, và có
một trang quản trị để cập nhật code mà không cần SSH vào.

---

## Tóm tắt: bốn bước

| Bước | Làm gì                                  | Mất bao lâu |
| ---- | --------------------------------------- | ----------- |
| 1    | Cài những thứ hệ điều hành cần          | ~5 phút     |
| 2    | Lấy code về và cài thư viện             | ~5 phút     |
| 3    | Khai khoá API và mật khẩu dashboard     | ~3 phút     |
| 4    | Cho nó chạy nền và tự bật khi khởi động | ~3 phút     |

Sau đó mỗi lần có code mới: **bấm một nút trên dashboard**, không SSH.

---

## Bước 0 — Chuẩn bị

Cần:

- Một máy Ubuntu **22.04 hoặc mới hơn** (mini PC ở nhà là đủ).
- Quyền `sudo` trên máy đó.
- Một tài khoản GitHub đọc được kho `analysis-system`.
- Khoá API của nhà cung cấp model (OpenRouter, Anthropic, hoặc Gemini).

Kiểm máy:

```bash
lsb_release -a          # Ubuntu mấy
python3 --version       # cần 3.11 trở lên
free -h                 # cần ít nhất 2 GB RAM trống
df -h ~                 # cần ít nhất 5 GB trống
```

> **Về RAM.** Lớp chấm độ liên quan tải một model ngôn ngữ nhỏ (~120 MB) vào bộ nhớ
> lần đầu dùng. Máy 2 GB chạy được; máy 1 GB sẽ bị hệ điều hành giết tiến trình giữa
> chừng, và triệu chứng là dashboard "tự nhiên chết" mà nhật ký không nói gì.

---

## Bước 1 — Cài những thứ hệ điều hành cần

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git
```

Chỉ có thế. Không cần Docker, không cần nginx, không cần cơ sở dữ liệu — hệ thống
dùng DuckDB, chạy thẳng trong tiến trình.

---

## Bước 2 — Lấy code về

```bash
cd ~
git clone https://github.com/Peterle220220/analysis-system.git
cd analysis-system
```

GitHub sẽ hỏi tài khoản. **Mật khẩu GitHub không dùng được** — phải dùng
_personal access token_:

1. Vào `github.com` → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Generate new token, tích quyền **`repo`**
3. Dán token vào chỗ hỏi mật khẩu

Nhớ token vào máy để không phải dán lại mỗi lần (**nút Cập nhật trên dashboard cần
điều này** — nó không có chỗ nào để hỏi mật khẩu):

```bash
git config --global credential.helper store
git pull        # dán token một lần cuối; từ đây git tự nhớ
```

> Token nằm ở `~/.git-credentials` dưới dạng chữ thường. Trên một máy cá nhân ở nhà
> thì chấp nhận được. Máy dùng chung thì đừng làm cách này.

Chọn nhánh muốn chạy:

```bash
git checkout phase6b-relevance
```

Cài thư viện:

```bash
python3 -m venv .venv
./.venv/bin/pip install --upgrade pip
./.venv/bin/pip install -e .
```

Mất vài phút. Kiểm:

```bash
./.venv/bin/asys --help
```

---

## Bước 3 — Khai khoá và mật khẩu

### 3.1 Tạo `.env`

```bash
cp .env.example .env
nano .env
```

Điền khoá API. **Tệp `.env` đã nằm trong `.gitignore`** — nó không bao giờ lên GitHub.

Chặn người khác đọc:

```bash
chmod 600 .env
```

> **Không bao giờ** dán khoá vào `.env.example`. Tệp đó có trong git.

### 3.2 Đặt mật khẩu dashboard

Dashboard **không chạy nếu chưa có mật khẩu** — đó là chủ ý. Một dashboard mở
không mật khẩu là mở toàn bộ dữ liệu cho bất kỳ ai chạm tới cổng đó.

```bash
./.venv/bin/asys set-password
```

Nó in ra một dòng dạng `ASYS_PASSWORD_HASH=...`. Chép dòng đó vào cuối `.env`.

Mật khẩu **không được lưu** — chỉ lưu bản băm. Quên thì đặt lại, không tìm lại được.

### 3.3 Kiểm cấu hình

```bash
set -a && . ./.env && set +a
./.venv/bin/asys check-config
```

Phải in ra bảng năm tầng dữ liệu và dòng `Cau hinh hop le.`

---

## Bước 4 — Cho nó chạy nền

Chạy dưới **user systemd**, không cần `sudo` cho việc khởi động lại — và chính vì
thế mà nút Cập nhật trên dashboard mới bấm được.

### 4.1 Cho phép dịch vụ chạy khi chưa đăng nhập

```bash
sudo loginctl enable-linger $USER
```

Không có bước này thì dịch vụ tắt mỗi khi bạn thoát SSH.

### 4.2 Cài unit

```bash
mkdir -p ~/.config/systemd/user
cp deploy/asys.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now asys
```

### 4.3 Kiểm

```bash
systemctl --user status asys      # phải thấy "active (running)"
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8020/dang-nhap
```

Phải ra `200`.

Xem nhật ký:

```bash
journalctl --user -u asys -f
```

### 4.4 Mở cổng trong mạng nhà

```bash
sudo ufw allow 8020/tcp     # chỉ khi đang bật ufw
hostname -I                 # địa chỉ IP của máy chủ
```

Từ máy khác trong nhà: `http://<địa-chỉ-IP>:8020`

> **Đừng mở cổng này ra Internet.** Nó chỉ có một mật khẩu, không có HTTPS, không có
> giới hạn số lần thử. Cần truy cập từ ngoài thì dùng Tailscale hoặc WireGuard —
> không phải mở cổng trên router.

### Muốn đổi cổng khác (ví dụ 8020)

Cổng mặc định là **8020**. Muốn dùng cổng khác, sửa **một chỗ** là đủ:

1. Trong `deploy/asys.service`, đổi con số sau `--port` ở dòng `ExecStart`.
2. Nếu đang bật ufw, mở cổng mới: `sudo ufw allow <cổng>/tcp`.
3. Áp dụng rồi khởi động lại:

   ```bash
   systemctl --user daemon-reload
   systemctl --user restart asys
   ```

Làm việc với Docker? Cổng ra ngoài nằm ở dòng `- "8020:8020"` trong
[`docker-compose.yml`](docker-compose.yml) — sửa số bên trái dấu hai chấm là đổi cổng
nhìn từ máy thật, không cần sửa gì trong container.

---

## Cập nhật code mà không SSH

Đây là phần thay cho việc SSH vào gõ `git pull` rồi khởi động lại.

### Dùng thế nào

1. Vào dashboard → mục **Hệ thống** ở thanh bên trái
2. Bấm **Kiểm tra lại** — nó hỏi GitHub xem có commit mới không
3. Có thì hiện danh sách commit, bấm **Cập nhật ngay**
4. Hệ thống lấy code về rồi tự khởi động lại; đợi vài giây, tải lại trang

Bản đang chạy luôn hiện ở trên cùng, kèm mã commit — để biết chắc mình đang chạy cái gì.

### Nó **không** làm gì

Đây là chỗ đáng đọc kỹ, vì một nút chạy được code mới trên máy chủ là **một cửa để
chạy code từ xa**:

- **Không nhận lệnh từ trình duyệt.** Không có ô nhập nhánh, nhập remote, nhập gì cả.
  Chỉ đúng nhánh mà kho trên máy chủ đang theo dõi.
- **Chỉ tua tới** (`--ff-only`). Lịch sử rẽ nhánh thì nó dừng và nói ra, không tự trộn.
- **Cây phải sạch.** Có sửa tay trên máy chủ thì nó từ chối — không ghi đè lên việc của bạn.
- **Không tự cập nhật.** Kiểm tra và áp dụng là hai nút riêng. Máy chủ không bao giờ
  tự đổi code đang chạy khi không ai bấm.

### Khi nút không dùng được

Nút sẽ từ chối và nói lý do. Ba lý do hay gặp:

| Nó nói                                   | Nghĩa là                          | Làm gì                          |
| ---------------------------------------- | --------------------------------- | ------------------------------- |
| _cây làm việc đang có thay đổi chưa lưu_ | Có ai sửa file thẳng trên máy chủ | SSH vào, `git status` xem là gì |
| _lịch sử đã rẽ khỏi kho từ xa_           | Máy chủ có commit riêng           | SSH vào xử lý bằng tay          |
| _không kết nối được tới kho_             | Mất mạng, hoặc token hết hạn      | Kiểm mạng; đặt lại token        |

Cách làm bằng tay, khi cần:

```bash
cd ~/analysis-system
git status                        # xem chuyện gì
git fetch && git merge --ff-only origin/phase6b-relevance
systemctl --user restart asys
```

---

## Sao lưu

Dữ liệu **không** nằm trong thư mục code. Nó nằm ở:

```
~/analysis-data/     dữ liệu thô, đã làm sạch, và kết quả
~/analysis-runs/     nhật ký từng lần chạy
```

Sao lưu hai thư mục đó là đủ — code lấy lại được từ GitHub bất cứ lúc nào.

```bash
tar czf ~/sao-luu-$(date +%F).tar.gz ~/analysis-data ~/analysis-runs
```

`.env` **không** nằm trong đó, và cố ý như vậy. Chép riêng, để chỗ khác.

---

## (Tuỳ chọn) Chạy bằng Docker

Repo đã có [`Dockerfile`](Dockerfile) và [`docker-compose.yml`](docker-compose.yml). Có
**hai service**, dùng chung một image:

- `analysis` — job batch: chạy **một việc rồi thoát** (`run-dag`, `check-config`, …).
  Đây là service dựng sẵn từ trước; nó không phải dashboard chạy lâu.
- `dashboard` — máy chủ web chạy lâu, tương đương phần systemd ở trên, **mở cổng 8020**.

Nếu chỉ cần dashboard thì dùng `dashboard`. Các bước:

### 1. Sinh hash mật khẩu (chạy host, không cần chạy container)

```bash
./.venv/bin/asys set-password --in-ra
```

Bản thân `set-password` **không chạy được trong container** — nó hỏi mật khẩu bằng
`getpass` kiểu tương tác. Thay vào đó chạy bằng `--in-ra` (chỉ in dòng cần dán), rồi
dán dòng `ASYS_PASSWORD_HASH=<salt>:<hash>` vào `.env`. Dashboard sẽ **từ chối chạy**
nếu thiếu dòng này — đúng như ý muốn.

### 2. Khai `.env` (giống như phần systemd)

```bash
cp .env.example .env
nano .env
```

Cần có: `ASYS_PASSWORD_HASH`, và (nếu chưa có trong `.env`) `ANALYSIS_DATA`,
`ANALYSIS_RUNS`. Tuỳ provider đang bật trong `config/settings.yaml`, thêm khoá tương
ứng (`OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, hoặc `GEMINI_API_KEY`).

> `docker-compose.yml` **đọc biến từ biến môi trường máy chủ hoặc từ `.env`** ở cùng
> thư mục — chính là file `.env` này. Bạn **không** cần ghi biến môi trường Docker
> riêng; compose tự nạp `.env`.

### 3. Dựng và chạy

Trong container, tiến trình chạy dưới user `analysis` (uid **10001**). Ba thư mục bind
mount từ máy thật (`data/raw`, `data/artifacts`, `runs`) phải để user đó ghi được:

```bash
mkdir -p data/raw data/artifacts runs
sudo chown -R 10001:10001 data/raw data/artifacts runs
docker compose build
docker compose up -d dashboard
```

> Không cần làm gì với các tầng trung gian (staging/clean/mart/...): chúng là named
> volume, Docker tự tạo và giữ đúng chủ sở hữu của thư mục trong image.

Mở `http://localhost:8020` (hoặc `http://<địa-chỉ-IP>:8020` từ máy khác trong nhà).
Muốn đổi cổng nhìn từ ngoài, sửa số bên trái trong `- "8020:8020"` trong
[`docker-compose.yml`](docker-compose.yml).

Xem nhật ký:

```bash
docker compose logs -f dashboard
```

Dọn cấu trúc dữ liệu trung gian (nếu cần) nhưng giữ `raw` và `artifacts`:

```bash
docker compose down
docker compose down -v   # xoá luôn volume staging/clean/mart/profile/validation
```

### Khi chạy job batch

```bash
docker compose run --rm analysis run-dag --input ... --plan ...
```

### Sao lưu khi chạy Docker

Dữ liệu nằm trong chính repo (khác với `~/analysis-data`, `~/analysis-runs` khi chạy
systemd):

```bash
tar czf ~/sao-luu-docker-$(date +%F).tar.gz data/raw data/artifacts runs
```

`.env` vẫn phải chép riêng, để chỗ khác.

### Khác biệt so với cách systemd (đọc kỹ chỗ này)

- **Nút "Cập nhật" trên dashboard không hoạt động.** Nó dựa vào lệnh `git` trong thư
  mục code và lệnh `systemctl --user restart asys`. Image không chứa `.git`, và không
  có systemd trong container. Cách an toàn như nó mô tả — một nút chạy được code mới
  trên máy chủ là một cửa để chạy code từ xa — nên cố ý **không** có tương đương Docker:
  muốn cập nhật thì `git pull` trên host rồi `docker compose up -d --build dashboard`.
- **`ASYS_SESSION_SECRET`.** Để trống, mỗi lần container khởi động lại là hết phiên
  đăng nhập (điểm an toàn mặc định). Muốn giữ phiên qua các lần restart thì đặt một
  giá trị cố định trong `.env`.
- **Lớp chấm độ liên quan** tải model ~120 MB vào bộ nhớ lần đầu dùng. Volume
  `model_cache` giữ model đã tải giữa các lần khởi động container.

---

## Khi có chuyện

### Dashboard không mở được

```bash
systemctl --user status asys
journalctl --user -u asys -n 50 --no-pager
```

Hay gặp nhất:

- `AuthError: chua dat mat khau` → chưa làm bước 3.2, hoặc `.env` thiếu dòng hash
- `Address already in use` → có tiến trình cũ. `pkill -f "asys serve"` rồi khởi động lại
- Chết ngay sau khi khởi động → `EnvironmentFile` sai đường dẫn trong unit

Chạy Docker? Tương ứng:

```bash
docker compose logs -f dashboard       # xem vì sao chết
docker compose exec dashboard asys check-config
```

- `Loi cau hinh ... khong ton tai` → thiếu thư mục bind mount; nhớ `mkdir -p` ở bước 3
- `Khong mo duoc dashboard` dù container chạy → kiểm `docker compose ps`, cổng 8020 đã
  khai trong `ports`, và `sudo ufw allow 8020/tcp` nếu đang bật ufw

### Chạy được nhưng câu hỏi nào cũng hỏng

```bash
set -a && . ./.env && set +a
./.venv/bin/asys check-config
```

Thường là khoá API sai hoặc hết hạn mức.

### Sau khi cập nhật thì hỏng

Lùi về bản trước:

```bash
cd ~/analysis-system
git log --oneline -5              # tìm mã commit chạy được
git checkout <mã-commit>
systemctl --user restart asys
```

Chạy lại được rồi thì báo để sửa, rồi:

```bash
git checkout phase6b-relevance
```

### Bắt đầu lại từ đầu

```bash
systemctl --user stop asys
rm -rf ~/analysis-data ~/analysis-runs
systemctl --user start asys
```

Xoá hết dữ liệu, giữ nguyên code và cấu hình.

---

## Những lệnh dùng thường xuyên

```bash
systemctl --user status asys        # đang chạy không
systemctl --user restart asys       # khởi động lại
systemctl --user stop asys          # dừng hẳn
journalctl --user -u asys -f        # xem nhật ký chạy
du -sh ~/analysis-data              # dữ liệu đang chiếm bao nhiêu
```

---

## Nhắc lại về an toàn

1. **`.env` không bao giờ vào git.** `.gitignore` đã chặn; đừng gỡ.
2. **Khoá API không bao giờ vào `.env.example`.** Tệp đó có trong git.
3. **Trước khi push, quét lại:**
   ```bash
   git grep -nE '(sk-ant-|AIza|AQ\.|sk-or-v1-)[0-9A-Za-z._-]{20,}'
   ```
   Không ra gì mới được push.
4. **Đừng mở cổng dashboard ra Internet** (mặc định 8020). Dùng Tailscale hoặc WireGuard.
5. **Mật khẩu dashboard là thứ duy nhất chắn giữa Internet nhà bạn và toàn bộ dữ liệu.**
   Đặt cho dài.
