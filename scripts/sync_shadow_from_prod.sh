#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIGRATION_ROOT="/home/dnaile748/app-migration"
MIGRATE_PY="${MIGRATION_ROOT}/scripts/migrate_rvu_shadow.py"
VERIFY_PY="${MIGRATION_ROOT}/scripts/verify_rvu_shadow.py"
TARGET_HOST="${1:-192.168.5.61}"
LOCAL_TUNNEL_PORT="${RVU_SHADOW_TUNNEL_PORT:-15433}"
SSH_CTL="/tmp/rvu-shadow-sync-${TARGET_HOST//./-}.sock"
DRY_RUN="${DRY_RUN:-0}"

cleanup() {
  ssh -S "${SSH_CTL}" -O exit "dnaile748@${TARGET_HOST}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

require_file() {
  local path="$1"
  [[ -f "${path}" ]] || {
    echo "Missing required file: ${path}" >&2
    exit 1
  }
}

require_file "${ROOT_DIR}/.env"
require_file "${MIGRATE_PY}"
require_file "${VERIFY_PY}"

SOURCE_DB_URL="$(
  python3 - <<'PY'
from pathlib import Path
for line in Path(".env").read_text().splitlines():
    if line.startswith("DATABASE_URL="):
        print(line.split("=", 1)[1].strip())
        break
PY
)"

TARGET_DB_URL="$(
  ssh -o BatchMode=yes -o ConnectTimeout=8 "dnaile748@${TARGET_HOST}" "sudo python3 - <<'PY'
from pathlib import Path
for line in Path('/opt/rvu/.env.shadow').read_text().splitlines():
    if line.startswith('DATABASE_URL='):
        print(line.split('=', 1)[1].strip())
        break
PY"
)"

ssh -f -N -M -S "${SSH_CTL}" \
  -L "${LOCAL_TUNNEL_PORT}:127.0.0.1:5432" \
  -o BatchMode=yes -o ConnectTimeout=8 \
  "dnaile748@${TARGET_HOST}"

TUNNELED_TARGET_DB_URL="${TARGET_DB_URL/127.0.0.1:5432/127.0.0.1:${LOCAL_TUNNEL_PORT}}"

MIGRATE_ARGS=(
  --source-database-url "${SOURCE_DB_URL}"
  --target-database-url "${TUNNELED_TARGET_DB_URL}"
  --staff-scope rvu_only
  --include-devices
  --include-magic-links
)

if [[ "${DRY_RUN}" != "1" ]]; then
  MIGRATE_ARGS+=(--apply --prune-missing)
fi

echo "==> RVU shadow sync (${TARGET_HOST})"
python3 "${MIGRATE_PY}" "${MIGRATE_ARGS[@]}"

echo
echo "==> RVU shadow verify (${TARGET_HOST})"
python3 "${VERIFY_PY}" \
  --source-database-url "${SOURCE_DB_URL}" \
  --target-database-url "${TUNNELED_TARGET_DB_URL}" \
  --staff-scope rvu_only \
  --include-devices \
  --include-magic-links
