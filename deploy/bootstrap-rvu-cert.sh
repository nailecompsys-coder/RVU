#!/usr/bin/env bash
# Reference: docs/DEPLOY_RUNBOOK.md (canonical deploy flow)
# Run once as root/sudo:  sudo bash /home/dnaile748/rvu/deploy/bootstrap-rvu-cert.sh
#
# What this does:
#   1. Grants dnaile748 passwordless sudo for the specific commands needed
#      (nginx reload, systemctl reload nginx, docker, rm/ln for nginx sites)
#   2. Temporarily disables the broken rvu vhost (so nginx can reload cleanly)
#   3. Adds ACME challenge passthrough to the port-80 redirect block
#   4. Uses Docker certbot to issue the rvu.midfloridasurgical.com cert
#   5. Re-enables the rvu vhost and reloads nginx
#   6. Verifies TLS

set -euo pipefail

USER=dnaile748
EMAIL="$(grep -m1 'ADMIN_EMAIL\|CERTBOT_EMAIL\|BASE_URL' /home/$USER/rvu/.env 2>/dev/null | head -n1 | cut -d@ -f2 | sed 's/[^a-zA-Z0-9._@-]//g' || true)"
if [[ -z "$EMAIL" ]]; then
  EMAIL="admin@midfloridasurgical.com"
fi

DOMAIN="rvu.midfloridasurgical.com"
SITES_AVAIL="/etc/nginx/sites-available"
SITES_ENAB="/etc/nginx/sites-enabled"
WEBROOT="/var/www/html"
RVU_CONF="$SITES_AVAIL/rvu"

echo "==> [1/6] Adding passwordless sudo rules for $USER ..."
SUDOERS_FILE="/etc/sudoers.d/rvu-devops"
cat > "$SUDOERS_FILE" <<EOF
# Added by bootstrap-rvu-cert.sh — allows rvu dev ops without password
$USER ALL=(ALL) NOPASSWD: /usr/sbin/nginx, /usr/bin/nginx
$USER ALL=(ALL) NOPASSWD: /bin/systemctl reload nginx, /bin/systemctl reload nginx.service
$USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl reload nginx, /usr/bin/systemctl reload nginx.service
$USER ALL=(ALL) NOPASSWD: /bin/ln -sf $SITES_AVAIL/* $SITES_ENAB/*
$USER ALL=(ALL) NOPASSWD: /bin/rm -f $SITES_ENAB/rvu
$USER ALL=(ALL) NOPASSWD: /usr/bin/docker
$USER ALL=(ALL) NOPASSWD: /usr/local/bin/docker
$USER ALL=(ALL) NOPASSWD: /usr/bin/tee $SITES_AVAIL/*
$USER ALL=(ALL) NOPASSWD: /bin/cp /home/$USER/rvu/deploy/nginx-rvu.conf $SITES_AVAIL/rvu
$USER ALL=(ALL) NOPASSWD: /usr/bin/cp /home/$USER/rvu/deploy/nginx-rvu.conf $SITES_AVAIL/rvu
EOF
chmod 440 "$SUDOERS_FILE"
visudo -c -f "$SUDOERS_FILE" && echo "   sudoers file OK" || { echo "   sudoers syntax error — removing"; rm -f "$SUDOERS_FILE"; exit 1; }

echo "==> [2/6] Temporarily disabling rvu vhost so nginx can reload ..."
rm -f "$SITES_ENAB/rvu"
nginx -t
systemctl reload nginx

echo "==> [3/6] Adding ACME challenge passthrough to port-80 block ..."
LLM_GW="$SITES_AVAIL/llm-gateway"
if ! grep -q 'acme-challenge' "$LLM_GW"; then
  # Insert ACME location before the return 301 line
  sed -i 's|return 301 https://\$host\$request_uri;|location ^~ /.well-known/acme-challenge/ { root /var/www/html; }\n    return 301 https://$host$request_uri;|g' "$LLM_GW"
  echo "   ACME passthrough added to llm-gateway"
else
  echo "   ACME passthrough already present"
fi
mkdir -p "$WEBROOT"
nginx -t
systemctl reload nginx

echo "==> [4/6] Issuing Let's Encrypt cert via Docker certbot ..."
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /var/lib/letsencrypt:/var/lib/letsencrypt \
  -v "$WEBROOT":/var/www/html \
  certbot/certbot certonly --webroot \
  -w /var/www/html \
  -d "$DOMAIN" \
  --email "$EMAIL" \
  --agree-tos \
  --non-interactive \
  --keep-until-expiring

echo "==> [5/6] Enabling rvu vhost and reloading nginx ..."
cp /home/$USER/rvu/deploy/nginx-rvu.conf "$RVU_CONF"
ln -sf "$RVU_CONF" "$SITES_ENAB/rvu"
nginx -t
systemctl reload nginx

echo "==> [6/6] Verifying TLS cert SAN ..."
sleep 2
RESULT=$(echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null | openssl x509 -noout -subject -ext subjectAltName 2>/dev/null || true)
echo "$RESULT"
if echo "$RESULT" | grep -q "$DOMAIN"; then
  echo ""
  echo "SUCCESS: $DOMAIN is now serving the correct TLS certificate."
else
  echo ""
  echo "WARNING: SAN check did not match $DOMAIN — check output above."
fi
