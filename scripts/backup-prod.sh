#!/usr/bin/env bash
set -euo pipefail

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
BACKUP_DIR="${HOME}/rvu-backups/${TIMESTAMP}"
WASABI_DEST="${RVU_WASABI_DEST:-wasabi:mfsa-cal/rvu-backups/${TIMESTAMP}}"

mkdir -p "${BACKUP_DIR}"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing .env at ${ENV_FILE}"
  exit 1
fi

set -a
source "${ENV_FILE}"
set +a

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "DATABASE_URL is not set in ${ENV_FILE}"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to parse DATABASE_URL"
  exit 1
fi

readarray -t DB_PARTS < <(
  python3 - <<'PY'
import os
from urllib.parse import urlparse

url = os.environ["DATABASE_URL"]
if url.startswith("postgres://"):
    url = "postgresql://" + url[len("postgres://"):]
r = urlparse(url)
print(r.hostname or "127.0.0.1")
print(r.port or 5432)
print(r.username or "")
print(r.password or "")
print((r.path or "").lstrip("/").split("?", 1)[0] or "surgical_cal")
PY
)

DB_HOST="${DB_PARTS[0]}"
DB_PORT="${DB_PARTS[1]}"
DB_USER="${DB_PARTS[2]}"
DB_PASSWORD="${DB_PARTS[3]}"
DB_NAME="${DB_PARTS[4]}"

cat > "${BACKUP_DIR}/metadata.txt" <<EOF
timestamp=${TIMESTAMP}
app=rvu
database_name=${DB_NAME}
database_host=${DB_HOST}
database_port=${DB_PORT}
note=RVU currently depends on the shared surgical_cal database boundary in production.
EOF

echo "Creating RVU database dump ..."
if docker ps -a --format '{{.Names}}' | grep -q '^atlas-postgres$'; then
  docker exec -e PGPASSWORD="${DB_PASSWORD}" atlas-postgres \
    pg_dump -U "${DB_USER}" "${DB_NAME}" \
    | gzip > "${BACKUP_DIR}/db.sql.gz"
else
  PGPASSWORD="${DB_PASSWORD}" pg_dump \
    -h "${DB_HOST}" \
    -p "${DB_PORT}" \
    -U "${DB_USER}" \
    "${DB_NAME}" \
    | gzip > "${BACKUP_DIR}/db.sql.gz"
fi
echo "  OK: ${BACKUP_DIR}/db.sql.gz"

echo "Saving git-tracked files snapshot ..."
git -C "${ROOT_DIR}" archive --format=tar.gz \
  -o "${BACKUP_DIR}/repo-tracked.tar.gz" HEAD
echo "  OK: ${BACKUP_DIR}/repo-tracked.tar.gz"

echo "Uploading to Wasabi (${WASABI_DEST}) ..."
if ! command -v rclone >/dev/null 2>&1; then
  echo "  SKIP: rclone not installed - files kept locally only"
else
  rclone copy "${BACKUP_DIR}" "${WASABI_DEST}" \
    --progress \
    --transfers 4 \
    --s3-upload-cutoff 50M \
    --s3-chunk-size 10M
  echo "  OK: uploaded to ${WASABI_DEST}"

  rm -rf "${BACKUP_DIR}"
  echo "  OK: local copy removed"
fi

echo
echo "Backup complete - ${TIMESTAMP}"
echo "  Wasabi: ${WASABI_DEST}"
