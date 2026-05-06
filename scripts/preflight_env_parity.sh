#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

warn() {
  echo "WARN: $1"
}

pass() {
  echo "PASS: $1"
}

[[ -f "$ENV_FILE" ]] || fail ".env not found at ${ENV_FILE}"

while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
  line="${raw_line#"${raw_line%%[![:space:]]*}"}"
  [[ -z "$line" || "${line:0:1}" == "#" ]] && continue
  key="${line%%=*}"
  value="${line#*=}"
  key="${key%"${key##*[![:space:]]}"}"
  value="${value#"${value%%[![:space:]]*}"}"
  if [[ -n "$key" ]]; then
    export "$key=$value"
  fi
done < "$ENV_FILE"

required_vars=(
  DATABASE_URL
  SECRET_KEY
  BASE_URL
  RVU_CORS_ORIGINS
  RVU_COOKIE_SECURE
  OLLAMA_BASE
  VISION_MODEL
  TEXT_MODEL
)

for key in "${required_vars[@]}"; do
  [[ -n "${!key:-}" ]] || fail "Missing required env var: ${key}"
done
pass "Required variables present"

if [[ "${BASE_URL}" == https://* ]]; then
  [[ "${RVU_COOKIE_SECURE}" == "true" ]] || fail "RVU_COOKIE_SECURE must be true for https BASE_URL"
  pass "Cookie security matches HTTPS BASE_URL"
else
  warn "BASE_URL is not https; local/dev mode assumed"
fi

if [[ "${BASE_URL}" == "https://rvu.midfloridasurgical.com" ]]; then
  if [[ "${DATABASE_URL}" != *"@127.0.0.1:5432/"* ]]; then
    fail "Production RVU DATABASE_URL must target 127.0.0.1:5432"
  fi
  pass "Production DATABASE_URL matches RVU host-network PostgreSQL target"
fi

if command -v python3 >/dev/null 2>&1; then
  python3 - <<'PY'
import os
import re
import socket
import sys

url = os.getenv("DATABASE_URL", "")
m = re.match(r"^[a-zA-Z0-9+]+://[^@]+@([^:/]+):([0-9]+)", url)
if not m:
    print("FAIL: DATABASE_URL is not parseable for host/port", file=sys.stderr)
    sys.exit(1)
host, port = m.group(1), int(m.group(2))
s = socket.socket()
s.settimeout(2.5)
try:
    s.connect((host, port))
except Exception as exc:
    print(f"FAIL: DB reachability check failed for {host}:{port} ({exc})", file=sys.stderr)
    sys.exit(1)
finally:
    s.close()
print(f"PASS: DB host reachable at {host}:{port}")
PY
else
  warn "python3 not found; skipping DB reachability check"
fi

if ss -ltn '( sport = :3010 )' 2>/dev/null | grep -q LISTEN; then
  pass "Port 3010 has a listener"
else
  warn "Port 3010 is not currently listening (service may be stopped)"
fi

echo "Preflight parity checks completed."
