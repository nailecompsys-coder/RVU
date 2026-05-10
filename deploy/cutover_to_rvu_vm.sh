#!/usr/bin/env bash
set -euo pipefail

TARGET_VM="${1:-192.168.5.61}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
RVU_CONF="/etc/nginx/sites-available/rvu"
CAL_CONF="/etc/nginx/sites-available/cal.midfloridasurgical.com.conf"
BACKUP_DIR="/root/rvu-cutover-backups/${TIMESTAMP}"

mkdir -p "${BACKUP_DIR}"
cp -a "${RVU_CONF}" "${BACKUP_DIR}/rvu"
cp -a "${CAL_CONF}" "${BACKUP_DIR}/cal.midfloridasurgical.com.conf"

python3 - <<'PY' "${RVU_CONF}" "${CAL_CONF}" "${TARGET_VM}"
from pathlib import Path
import sys

rvu_conf = Path(sys.argv[1])
cal_conf = Path(sys.argv[2])
target_vm = sys.argv[3]

rvu_text = rvu_conf.read_text(encoding="utf-8")
rvu_text = rvu_text.replace("proxy_pass http://127.0.0.1:3010/;", f"proxy_pass http://{target_vm}:3010/;")
rvu_text = rvu_text.replace("proxy_pass http://127.0.0.1:3010/assets/;", f"proxy_pass http://{target_vm}:3010/assets/;")
rvu_conf.write_text(rvu_text, encoding="utf-8")

cal_text = cal_conf.read_text(encoding="utf-8")
marker = "    # RVU native cutover bridge"
if marker not in cal_text:
    otp_block = f"""{marker}
    location = /api/surgeon/otp/request {{
        proxy_pass         http://{target_vm}:3010/api/v1/auth/otp/request;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 60;
    }}

    location = /api/surgeon/otp/verify {{
        proxy_pass         http://{target_vm}:3010/api/v1/auth/otp/verify;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 60;
    }}

"""
    anchor = "    location / {\n"
    if anchor not in cal_text:
        raise SystemExit("Could not locate insertion point in CAL nginx config")
    cal_text = cal_text.replace(anchor, otp_block + anchor, 1)
else:
    import re
    cal_text = re.sub(
        r"(proxy_pass\s+)http://[0-9.]+:3010(/api/v1/auth/otp/request;)",
        rf"\1http://{target_vm}:3010\2",
        cal_text,
    )
    cal_text = re.sub(
        r"(proxy_pass\s+)http://[0-9.]+:3010(/api/v1/auth/otp/verify;)",
        rf"\1http://{target_vm}:3010\2",
        cal_text,
    )
cal_conf.write_text(cal_text, encoding="utf-8")
PY

nginx -t
systemctl reload nginx

cat <<EOF
RVU cutover config applied.

Backups:
  ${BACKUP_DIR}/rvu
  ${BACKUP_DIR}/cal.midfloridasurgical.com.conf

Current public RVU target:
  https://rvu.midfloridasurgical.com -> ${TARGET_VM}:3010

Current CAL OTP bridge:
  https://cal.midfloridasurgical.com/api/surgeon/otp/request -> ${TARGET_VM}:3010/api/v1/auth/otp/request
  https://cal.midfloridasurgical.com/api/surgeon/otp/verify  -> ${TARGET_VM}:3010/api/v1/auth/otp/verify
EOF

