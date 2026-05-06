#!/usr/bin/env bash
set -euo pipefail

BUNDLE_PATH="${1:-}"
DEPLOY_SHA="${2:-unknown}"
LIVE_DIR="/home/dnaile748/rvu"
LIVE_BACKEND_DIR="${LIVE_DIR}/backend"
BACKUP_DIR="${LIVE_DIR}/deploy/backups"
TMP_DIR="/home/dnaile748/rvu/deploy/tmp"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
HEALTH_URL="http://127.0.0.1:3010/api/health"
HEALTH_ATTEMPTS=120
HEALTH_SLEEP=3

if [ -z "${BUNDLE_PATH}" ]; then
  echo "usage: deploy_backend_from_bundle.sh <bundle_path> [sha]"
  exit 2
fi

log() {
  echo "[deploy-bundle][${TIMESTAMP}] $*"
}

wait_for_health() {
  for _ in $(seq 1 "${HEALTH_ATTEMPTS}"); do
    if curl -fsS "${HEALTH_URL}" >/dev/null; then
      return 0
    fi
    sleep "${HEALTH_SLEEP}"
  done
  return 1
}

rollback() {
  local backup_file="$1"
  log "deploy failed; rolling back backend files"
  rm -rf "${LIVE_BACKEND_DIR}"
  mkdir -p "${LIVE_BACKEND_DIR}"
  tar -xzf "${backup_file}" -C "${LIVE_BACKEND_DIR}" --strip-components=1
  cd "${LIVE_DIR}"
  docker compose build rvu_api
  docker compose up -d rvu_api
  wait_for_health
  log "rollback health check passed"
}

log "deploy sha ${DEPLOY_SHA}"
mkdir -p "${BACKUP_DIR}" "${TMP_DIR}"
BACKUP_FILE="${BACKUP_DIR}/backend-${TIMESTAMP}.tgz"

if [ -d "${LIVE_BACKEND_DIR}" ]; then
  tar -czf "${BACKUP_FILE}" -C "${LIVE_BACKEND_DIR}" .
else
  mkdir -p "${LIVE_BACKEND_DIR}"
  tar -czf "${BACKUP_FILE}" -C "${LIVE_BACKEND_DIR}" .
fi

WORK_DIR="${TMP_DIR}/release-${TIMESTAMP}"
mkdir -p "${WORK_DIR}"
tar -xzf "${BUNDLE_PATH}" -C "${WORK_DIR}"

if [ ! -d "${WORK_DIR}/app" ] || [ ! -f "${WORK_DIR}/requirements.txt" ]; then
  log "bundle missing app/ or requirements.txt"
  exit 3
fi

log "syncing bundle into live backend"
rm -rf "${LIVE_BACKEND_DIR}/app"
cp -a "${WORK_DIR}/app" "${LIVE_BACKEND_DIR}/app"
install -m 644 "${WORK_DIR}/requirements.txt" "${LIVE_BACKEND_DIR}/requirements.txt"

cd "${LIVE_DIR}"
log "docker build + restart"
docker compose build rvu_api
docker compose up -d rvu_api

if wait_for_health; then
  log "health check passed"
  rm -rf "${WORK_DIR}"
  rm -f "${BUNDLE_PATH}"
  echo "deployed_sha=${DEPLOY_SHA}"
  exit 0
fi

rollback "${BACKUP_FILE}"
rm -rf "${WORK_DIR}"
rm -f "${BUNDLE_PATH}"
log "deployment failed after rollback"
exit 1
