#!/usr/bin/env bash
# Run after boot or via cron so the RVU vision model exists on disk AND gets one GPU warm pass.
# Ollama stores models under its Docker volume forever; reboot does not delete them.
# VRAM preload decays unless you periodically infer — this script optionally keeps weights hot briefly.
#
# Cron examples:
#   @reboot sleep 45 && /home/dnaile748/rvu/deploy/ollama_warm_rvu_vision.sh >>/tmp/rvu_ollama_warm.log 2>&1
#   */30 * * * * /home/dnaile748/rvu/deploy/ollama_warm_rvu_vision.sh >/dev/null 2>&1
set -eu
OLLAMA_URL="${OLLAMA_URL:-http://127.0.0.1:11434}"
RVU_ENV="${RVU_ENV_FILE:-/home/dnaile748/rvu/.env}"
MODEL="$(grep '^VISION_MODEL=' "${RVU_ENV}" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r')"
MODEL="${MODEL:-qwen2.5vl:7b}"

for _ in $(seq 1 60); do
  if curl -fsS "${OLLAMA_URL}/api/tags" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

export MODEL OLLAMA_URL
python3 <<'PY'
import json, os, urllib.request

ollama = os.environ["OLLAMA_URL"].rstrip("/")
model = os.environ["MODEL"]
# Text-only warm is enough for Ollama to load weights into VRAM; multimodal path warms on first real photo.
payload = json.dumps({
    "model": model,
    "prompt": "Say OK.",
    "stream": False,
    "keep_alive": "30m",
    "options": {"num_predict": 8, "temperature": 0},
}).encode()
req = urllib.request.Request(f"{ollama}/api/generate", data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=600) as r:
    body = json.loads(r.read().decode())
err = body.get("error")
if err:
    raise SystemExit(f"ollama warm failed: {err}")
print(json.dumps({"ok": True, "model": model, "total_duration_ns": body.get("total_duration")}))
PY
