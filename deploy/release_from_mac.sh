#!/usr/bin/env bash
# Build and deploy the single RVU app source of truth:
#   backend/ + frontend/ from this prod-rvu repository.
set -euo pipefail

REQUESTED_HOST="${1:-rvu-prod}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

resolve_host() {
  case "$1" in
    rvu-prod|rvu-vm|prod-vm|192.168.5.61)
      echo "${RVU_SSH_HOST:-rvu-5.61}"
      ;;
    *)
      echo "$1"
      ;;
  esac
}

SSH_HOST="$(resolve_host "${REQUESTED_HOST}")"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[release] ERROR: ${REPO_ROOT} is not a git repository." >&2
  exit 1
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "[release] ERROR: tracked working tree is not clean. Commit or stash, then retry." >&2
  git status --short >&2
  exit 1
fi

if [ "${SKIP_GIT_PUSH:-0}" != "1" ]; then
  echo "[release] pushing $(git rev-parse --abbrev-ref HEAD) to origin..."
  git push origin HEAD
else
  echo "[release] WARN: SKIP_GIT_PUSH=1 - deploy uses local HEAD plus freshly built frontend/dist." >&2
fi

DEPLOY_SHA="$(git rev-parse --short HEAD)"
REMOTE_BUNDLE="/tmp/rvu-${DEPLOY_SHA}.tgz"
LOCAL_BUNDLE="$(mktemp "/tmp/rvu-${DEPLOY_SHA}.XXXXXX.tgz")"

echo "[release] target host: ${REQUESTED_HOST}"
echo "[release] deploy sha: ${DEPLOY_SHA}"
echo "[release] building frontend from ${REPO_ROOT}/frontend"

(cd frontend && npm ci && npm run build)

if [ ! -d frontend/dist ]; then
  echo "[release] ERROR: frontend/dist missing after build" >&2
  exit 1
fi

trap 'rm -f "${LOCAL_BUNDLE}"' EXIT

export COPYFILE_DISABLE=1
export COPY_EXTENDED_ATTRIBUTES_DISABLE=1
tar -czf "${LOCAL_BUNDLE}" \
  backend/app \
  backend/requirements.txt \
  frontend/dist \
  Dockerfile \
  docker-compose.yml \
  deploy

REMOTE_LIVE_DIR="$(
  ssh "${SSH_HOST}" 'if [ -n "${RVU_LIVE_DIR:-}" ]; then echo "${RVU_LIVE_DIR}"; elif [ -f /opt/rvu/docker-compose.yml ]; then echo /opt/rvu; else exit 42; fi'
)"
REMOTE_DEPLOY_SCRIPT="${REMOTE_LIVE_DIR}/deploy/deploy_backend_from_bundle.sh"

echo "[release] ssh host: ${SSH_HOST}"
echo "[release] remote live dir: ${REMOTE_LIVE_DIR}"

if [ "${RVU_RELEASE_DRY_RUN:-0}" = "1" ]; then
  echo "[release] dry run only; would copy ${LOCAL_BUNDLE} to ${SSH_HOST}:${REMOTE_BUNDLE}"
  echo "[release] dry run only; would sync deploy helper to ${REMOTE_DEPLOY_SCRIPT}"
  exit 0
fi

scp "${LOCAL_BUNDLE}" "${SSH_HOST}:${REMOTE_BUNDLE}"
scp "${REPO_ROOT}/deploy/deploy_backend_from_bundle.sh" "${SSH_HOST}:/tmp/deploy_backend_from_bundle.sh"
ssh "${SSH_HOST}" "set -euo pipefail
sudo install -m 755 /tmp/deploy_backend_from_bundle.sh '${REMOTE_DEPLOY_SCRIPT}'
rm -f /tmp/deploy_backend_from_bundle.sh
sudo env RVU_LIVE_DIR='${REMOTE_LIVE_DIR}' bash '${REMOTE_DEPLOY_SCRIPT}' '${REMOTE_BUNDLE}' '${DEPLOY_SHA}'
"
