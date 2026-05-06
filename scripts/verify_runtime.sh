#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="${1:-rvu-api.service}"
DOMAIN="${2:-rvu.midfloridasurgical.com}"
LOCAL_HEALTH_URL="${3:-http://127.0.0.1:3010/api/health}"
CONTAINER_NAME="${4:-rvu_api}"

info() {
  echo "INFO: $1"
}

warn() {
  echo "WARN: $1"
}

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

info "Checking local health endpoint: ${LOCAL_HEALTH_URL}"
curl -fsS "${LOCAL_HEALTH_URL}" >/dev/null || fail "Health check failed"

if command -v systemctl >/dev/null 2>&1; then
  if command -v docker >/dev/null 2>&1 && docker inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    info "Checking Docker container status: ${CONTAINER_NAME}"
    docker inspect -f '{{.State.Status}}' "${CONTAINER_NAME}" | grep -qx 'running' || warn "${CONTAINER_NAME} is not running"
  else
    info "Checking systemd service status: ${SERVICE_NAME}"
    systemctl is-active --quiet "${SERVICE_NAME}" || warn "${SERVICE_NAME} is not active"
  fi
fi

if command -v nginx >/dev/null 2>&1; then
  info "Validating nginx configuration"
  if nginx -t >/dev/null 2>&1; then
    info "nginx config test passed"
  elif command -v sudo >/dev/null 2>&1 && sudo -n nginx -t >/dev/null 2>&1; then
    info "nginx config test passed via sudo"
  else
    warn "Could not validate nginx config without elevated privileges"
  fi
fi

if [[ -d "/etc/letsencrypt/live/${DOMAIN}" ]]; then
  info "TLS certificate path exists for ${DOMAIN}"
else
  warn "TLS cert path missing for ${DOMAIN}"
fi

if command -v openssl >/dev/null 2>&1; then
  info "Checking TLS SAN includes ${DOMAIN}"
  SAN_OUT="$(echo | openssl s_client -connect "${DOMAIN}:443" -servername "${DOMAIN}" 2>/dev/null | openssl x509 -noout -ext subjectAltName 2>/dev/null || true)"
  if [[ "${SAN_OUT}" == *"${DOMAIN}"* ]]; then
    info "TLS SAN validation passed"
  else
    warn "TLS SAN check did not confirm ${DOMAIN}"
  fi
fi

echo "Runtime verification completed."
