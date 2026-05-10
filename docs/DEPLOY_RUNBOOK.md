# RVU Deploy Runbook

This is the canonical production deploy sequence for RVU.

## Preconditions

- You are on the production Linux host.
- Repo is updated to the desired commit.
- `.env` is present and valid.

## 1) Preflight checks

```bash
cd /home/dnaile748/rvu
scripts/preflight_env_parity.sh
```

## Shadow refresh before cutover

For the final RVU VM cutover window, refresh `rvu_prod` from live shared data first:

```bash
cd /home/dnaile748/rvu
scripts/sync_shadow_from_prod.sh 192.168.5.61
```

That sync preserves device/session continuity, imports current active magic links,
and prunes stale shadow-only rows.

## 2) Build frontend (if frontend changed)

```bash
cd /home/dnaile748/rvu/frontend
npm ci
npm run build
```

## 3) Update backend dependencies (if requirements changed)

```bash
cd /home/dnaile748/rvu/backend
/home/dnaile748/rvu/.venv/bin/pip install -r requirements.txt
```

## 4) Restart production container

```bash
cd /home/dnaile748/rvu
docker compose up -d rvu_api
docker logs --tail 80 rvu_api
```

## 5) Verify runtime and health

```bash
cd /home/dnaile748/rvu
scripts/verify_runtime.sh
curl -sf http://127.0.0.1:3010/api/health
```

## 6) Verify public ingress

```bash
curl -I https://rvu.midfloridasurgical.com
echo | openssl s_client -connect rvu.midfloridasurgical.com:443 -servername rvu.midfloridasurgical.com 2>/dev/null | openssl x509 -noout -subject -ext subjectAltName
```

## Coordinated cutover

On the old edge host, the native app still hits `cal.midfloridasurgical.com` for OTP.
During cutover, switch public RVU traffic and the CAL OTP bridge together:

```bash
cd /home/dnaile748/rvu
deploy/cutover_to_rvu_vm.sh 192.168.5.61
```

That script:

- points `rvu.midfloridasurgical.com` at the RVU VM
- bridges `cal.midfloridasurgical.com/api/surgeon/otp/*` to RVU auth on the VM
- backs up both nginx config files before reload

## Rollback procedure

1. Checkout previous known-good git commit.
2. Rebuild frontend if needed.
3. Reinstall backend dependencies if needed.
4. Recreate `rvu_api` with `docker compose up -d rvu_api`.
5. Re-run `scripts/verify_runtime.sh`.

## Related docs

- `docs/ENVIRONMENT_BASELINE.md`
- `docs/ENV_VARS.md`
- `docs/PARITY_CHECKLIST.md`
- `deploy/SHARED_WAN_AND_NGINX.md`
