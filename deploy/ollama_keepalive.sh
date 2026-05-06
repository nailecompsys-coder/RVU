#!/usr/bin/env bash
# Cheap liveness poke for Ollama on the RVU backend host (llm-core). Add to cron e.g.
# */5 * * * * /home/dnaile748/rvu/deploy/ollama_keepalive.sh
set -eu
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
curl -fsS -m "${OLLAMA_KEEPALIVE_TIMEOUT:-15}" "${OLLAMA_URL}/api/tags" >/dev/null
