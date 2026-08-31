#!/usr/bin/env bash
#
# Cai dat analysis-system tren Ubuntu Server 24.04.
#
# Chay lai bao nhieu lan cung duoc: script chi tao thu muc con thieu va cai lai
# dung bo thu vien da khoa. No KHONG bao gio xoa du lieu.
#
#   ./scripts/install.sh
#   ANALYSIS_DATA=/srv/analysis-data ANALYSIS_RUNS=/srv/analysis-runs ./scripts/install.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DATA_DIR="${ANALYSIS_DATA:-$HOME/analysis-data}"
RUNS_DIR="${ANALYSIS_RUNS:-$HOME/analysis-runs}"
LAYERS=(raw extracted staging clean mart profile validation artifacts)

say()  { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\033[31mLOI: %s\033[0m\n' "$*" >&2; exit 1; }

# --- 1. Python ----------------------------------------------------------------

say "Kiem tra Python"
command -v python3 >/dev/null || fail "Chua co python3. Cai: sudo apt install -y python3"

PY_OK=$(python3 - <<'PY'
import sys
print("yes" if sys.version_info >= (3, 11) else "no")
PY
)
[ "$PY_OK" = "yes" ] || fail "Can Python >= 3.11, dang co $(python3 --version)"
echo "  $(python3 --version)"

if ! python3 -c "import venv" 2>/dev/null; then
    fail "Thieu module venv. Cai: sudo apt install -y python3-venv"
fi

# --- 2. Virtualenv ------------------------------------------------------------

say "Chuan bi virtualenv"
[ -d .venv ] || python3 -m venv .venv
./.venv/bin/pip install --upgrade pip --quiet

# Cai dung phien ban da khoa, roi cai chinh du an ma khong cho pip giai lai
# phu thuoc - neu khong, mot ban va moi co the lot vao ma khong ai chon.
say "Cai thu vien theo requirements.lock.txt"
./.venv/bin/pip install --quiet -r requirements.lock.txt
./.venv/bin/pip install --quiet --no-deps -e .

# --- 3. Thu muc du lieu -------------------------------------------------------
#
# Chuong trinh khong bao gio tu tao tang du lieu - mot tang thieu la loi cau
# hinh, khong phai thu de im lang vá. Viec tao la hanh dong co y cua nguoi cai.

say "Tao tang du lieu"
for layer in "${LAYERS[@]}"; do
    mkdir -p "$DATA_DIR/$layer"
done
mkdir -p "$RUNS_DIR"
echo "  du lieu : $DATA_DIR"
echo "  lan chay: $RUNS_DIR"

# --- 4. Kiem tra --------------------------------------------------------------

say "Kiem tra cau hinh"
ANALYSIS_DATA="$DATA_DIR" ANALYSIS_RUNS="$RUNS_DIR" ./.venv/bin/asys check-config

cat <<DONE

Xong. Dung tiep:

  source .venv/bin/activate          # de goi lenh 'asys' truc tiep
  asys check-config
  asys plan "cau hoi cua ban" --source raw://file.csv --out plan.json
  asys run-dag --input <file.csv> --plan plan.json --run-id r1

Neu dat ANALYSIS_DATA / ANALYSIS_RUNS khac mac dinh, nho export chung trong
moi phien - hoac ghi vao ~/.bashrc, hoac dung file .env cua systemd (xem DEPLOY.md).

DONE
