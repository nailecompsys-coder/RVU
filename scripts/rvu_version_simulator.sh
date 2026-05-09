#!/usr/bin/env bash
# Simulate / probe RVU server version: prefers live GET /api/version, falls back to local git/package metadata.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
URL="${RVU_VERSION_URL:-http://127.0.0.1:3010/api/version}"
PY="${ROOT}/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  PY="python3"
fi

if out="$(curl -sf --max-time 3 "$URL" 2>/dev/null)" && [[ -n "$out" ]] && [[ "$out" == \{* ]]; then
  if command -v jq >/dev/null 2>&1; then
    echo "$out" | jq .
  else
    echo "$out"
  fi
  exit 0
fi

echo "RVU API unreachable at ${URL}; printing local metadata only." >&2
cd "${ROOT}/backend"
exec "$PY" -c "from app.version_info import version_payload; import json; print(json.dumps(version_payload(), indent=2))"
