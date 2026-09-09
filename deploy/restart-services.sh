#!/usr/bin/env bash
set -Eeuo pipefail

repo="${HOME}/analysis-system"
frontend="${repo}/frontend"
staged_name=".next.codex-staging"
backup_name=".next.codex-previous"

cd "${frontend}"
rm -rf "${staged_name}" "${backup_name}"

# Build away from the live artifact. A failed install/build leaves the running
# frontend untouched and therefore cannot activate a half-built release.
NEXT_DIST_DIR="${staged_name}" npm ci
NEXT_DIST_DIR="${staged_name}" npm run build
test -f "${staged_name}/standalone/server.js"

if [ -d .next ]; then
  mv .next "${backup_name}"
fi
mv "${staged_name}" .next

rollback() {
  rm -rf .next
  if [ -d "${backup_name}" ]; then
    mv "${backup_name}" .next
  fi
  systemctl --user restart asys-web || true
}

if ! systemctl --user restart asys; then
  rollback
  exit 1
fi
if ! curl --fail --silent --show-error --max-time 10 http://127.0.0.1:8020/api/health >/dev/null; then
  rollback
  exit 1
fi

if ! systemctl --user restart asys-web; then
  rollback
  exit 1
fi
if ! curl --fail --silent --show-error --max-time 10 http://127.0.0.1:3000/api/health >/dev/null; then
  rollback
  exit 1
fi

rm -rf "${backup_name}"
