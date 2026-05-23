#!/usr/bin/env bash
set -euo pipefail

BUNDLE_PATH="${1:-}"
DEPLOY_SHA="${2:-unknown}"
LIVE_DIR="${RVU_LIVE_DIR:-/opt/rvu}"
LIVE_BACKEND_DIR="${LIVE_DIR}/backend"
LIVE_FRONTEND_DIR="${LIVE_DIR}/frontend"
BACKUP_DIR="${LIVE_DIR}/deploy/backups"
TMP_DIR="${LIVE_DIR}/deploy/tmp"
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
  log "deploy failed; rolling back app files"
  rm -rf "${LIVE_BACKEND_DIR}"
  mkdir -p "${LIVE_BACKEND_DIR}"
  tar -xzf "${backup_file}" -C "${LIVE_DIR}"
  cd "${LIVE_DIR}"
  docker compose build rvu_api
  docker compose up -d rvu_api
  wait_for_health
  log "rollback health check passed"
}

log "deploy sha ${DEPLOY_SHA}"
mkdir -p "${BACKUP_DIR}" "${TMP_DIR}"
BACKUP_FILE="${BACKUP_DIR}/app-${TIMESTAMP}.tgz"

mkdir -p "${LIVE_BACKEND_DIR}" "${LIVE_FRONTEND_DIR}"
tar -czf "${BACKUP_FILE}" -C "${LIVE_DIR}" backend frontend Dockerfile docker-compose.yml deploy 2>/dev/null || \
  tar -czf "${BACKUP_FILE}" -C "${LIVE_DIR}" backend frontend

WORK_DIR="${TMP_DIR}/release-${TIMESTAMP}"
mkdir -p "${WORK_DIR}"
tar -xzf "${BUNDLE_PATH}" -C "${WORK_DIR}"

if [ ! -d "${WORK_DIR}/backend/app" ] || [ ! -f "${WORK_DIR}/backend/requirements.txt" ]; then
  log "bundle missing backend/app or backend/requirements.txt"
  exit 3
fi

if [ ! -d "${WORK_DIR}/frontend/dist" ]; then
  log "bundle missing frontend/dist"
  exit 3
fi

log "syncing bundle into live docker context"
rm -rf "${LIVE_BACKEND_DIR}/app"
cp -a "${WORK_DIR}/backend/app" "${LIVE_BACKEND_DIR}/app"
install -m 644 "${WORK_DIR}/backend/requirements.txt" "${LIVE_BACKEND_DIR}/requirements.txt"

rm -rf "${LIVE_FRONTEND_DIR}/dist"
mkdir -p "${LIVE_FRONTEND_DIR}"
cp -a "${WORK_DIR}/frontend/dist" "${LIVE_FRONTEND_DIR}/dist"

if [ -f "${WORK_DIR}/Dockerfile" ]; then
  install -m 644 "${WORK_DIR}/Dockerfile" "${LIVE_DIR}/Dockerfile"
fi
if [ -f "${WORK_DIR}/docker-compose.yml" ]; then
  install -m 644 "${WORK_DIR}/docker-compose.yml" "${LIVE_DIR}/docker-compose.yml"
fi
if [ -d "${WORK_DIR}/deploy" ]; then
  mkdir -p "${LIVE_DIR}/deploy"
  cp -a "${WORK_DIR}/deploy/." "${LIVE_DIR}/deploy/"
fi

cd "${LIVE_DIR}"
log "docker build + restart"
docker compose build rvu_api
docker compose up -d rvu_api

if wait_for_health; then
  log "health check passed"
  printf "%s\n" "${DEPLOY_SHA}" > "${LIVE_DIR}/deploy/DEPLOYED_SHA"
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
