# RVU Parity Checklist

Use this checklist before any release and after significant environment changes.

## 1) Runtime parity

- [ ] Production baseline document reviewed: `docs/ENVIRONMENT_BASELINE.md`
- [ ] Production runtime uses Docker Compose service `rvu_api` with `network_mode: host`
- [ ] Local runtime uses either Docker host-network mode or host uvicorn with same env contract
- [ ] App health responds at `GET /api/health` on port `3010`

## 2) Environment parity

- [ ] `.env` contains all required keys from `docs/ENV_VARS.md`
- [ ] Production `DATABASE_URL` points to `127.0.0.1:5432` for RVU
- [ ] `BASE_URL`, `RVU_CORS_ORIGINS`, and `RVU_COOKIE_SECURE` match environment intent
- [ ] `SECRET_KEY` alignment with Cal is verified when shared SSO is required

## 3) Database parity

- [ ] DB host/port reachable from runtime process
- [ ] App startup succeeds without schema errors
- [ ] `rvu_scans` read/write paths are healthy

## 4) Proxy/TLS parity (production)

- [ ] nginx config passes `nginx -t`
- [ ] `rvu.midfloridasurgical.com` vhost is active
- [ ] TLS SAN includes `rvu.midfloridasurgical.com`

## 5) Operational parity

- [ ] Deploy runbook followed: `docs/DEPLOY_RUNBOOK.md`
- [ ] `docker compose up -d rvu_api` completed without startup errors
- [ ] Post-deploy verification completed (`scripts/verify_runtime.sh`)
- [ ] Any runtime/env changes reflected in docs
