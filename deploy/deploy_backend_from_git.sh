#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'EOF'
deploy_backend_from_git.sh is retired.

Do not deploy RVU from the old split rvu-api repo.
Use the single source-of-truth release flow:

  cd /Users/donnaile/dev/rvu/prod-rvu
  deploy/release_from_mac.sh rvu-prod
EOF

exit 2
