#!/usr/bin/env bash
set -euo pipefail

TARGET_REF="${1:-main}"
REPO_URL="git@github.com:nailecompsys-coder/rvu-api.git"
SRC_DIR="/home/dnaile748/deploy-src/rvu-api"
LIVE_DIR="${RVU_LIVE_DIR:-/opt/rvu}"
LIVE_BACKEND_DIR="${LIVE_DIR}/backend"
BACKUP_DIR="${LIVE_DIR}/deploy/backups"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
HEALTH_URL="http://127.0.0.1:3010/api/health"

log() {
  echo "[deploy][${TIMESTAMP}] $*"
}

on_err() {
  log "error on line ${1}"
}

rollback() {
  local backup_file="$1"
  log "deploy failed; starting rollback"
  rm -rf "${LIVE_BACKEND_DIR}"
  mkdir -p "${LIVE_BACKEND_DIR}"
  tar -xzf "${backup_file}" -C "${LIVE_BACKEND_DIR}" --strip-components=1
  cd "${LIVE_DIR}"
  docker compose build rvu_api
  docker compose up -d rvu_api
  log "rollback complete; health check"
  curl -fsS "${HEALTH_URL}" >/dev/null
}

trap on_err 1 ERR

log "ensuring source checkout"
if [ ! -d "${SRC_DIR}/.git" ]; then
  rm -rf "${SRC_DIR}"
  git clone "${REPO_URL}" "${SRC_DIR}"
fi

cd "${SRC_DIR}"
git fetch --all --prune
git checkout "${TARGET_REF}"
git pull --ff-only origin "${TARGET_REF}"
DEPLOY_SHA="$(git rev-parse --short HEAD)"
log "deploying sha ${DEPLOY_SHA}"

mkdir -p "${BACKUP_DIR}"
BACKUP_FILE="${BACKUP_DIR}/backend-${TIMESTAMP}.tgz"

if [ -d "${LIVE_BACKEND_DIR}" ]; then
  tar -czf "${BACKUP_FILE}" -C "${LIVE_BACKEND_DIR}" .
else
  mkdir -p "${LIVE_BACKEND_DIR}"
  tar -czf "${BACKUP_FILE}" -C "${LIVE_BACKEND_DIR}" .
fi

log "syncing backend files into live docker context"
rsync -av --delete --exclude ".git" --exclude "__pycache__" "${SRC_DIR}/app/" "${LIVE_BACKEND_DIR}/app/"
install -m 644 "${SRC_DIR}/requirements.txt" "${LIVE_BACKEND_DIR}/requirements.txt"

cd "${LIVE_DIR}"
log "building and restarting rvu_api"
docker compose build rvu_api
docker compose up -d rvu_api

log "waiting for health"
for i in $(seq 1 20); do
  if curl -fsS "${HEALTH_URL}" >/dev/null; then
    log "health check passed"
    echo "deployed_sha=${DEPLOY_SHA}"
    exit 0
  fi
  sleep 2
done

rollback "${BACKUP_FILE}"
log "deployment failed after rollback"
exit 1
