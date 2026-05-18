# RVU Cutover And Mac Recovery

Last updated: 2026-05-14

This file is the authoritative handoff for Cursor/Codex when rebuilding or resuming RVU development from a Mac or any new workstation.

## Production Topology

- public hostname: `rvu.midfloridasurgical.com`
- edge ingress VM: `192.168.5.75`
- RVU app VM: `192.168.5.61`
- live RVU upstream behind edge: `192.168.5.61:3010`
- public flow: client -> `5.75` nginx -> `5.61:3010`

## Source Of Truth

Treat these in this order:

1. live app runtime checkout on `5.61`: `/opt/rvu`
2. git remote: `ssh://git@git.midfloridasurgical.com:2222/NCS/RVU.git`
3. this local Linux working copy: `/home/dnaile748/rvu`

If the Mac dev environment is being rebuilt, first compare against `/opt/rvu` on `5.61` before trusting any stale local copy.

## What Was Cut Over

- RVU was split off the old shared host onto its own VM at `192.168.5.61`.
- Public RVU traffic now enters through edge nginx on `192.168.5.75`.
- CAL login endpoints still bridge native OTP flows into RVU so mobile auth keeps working:
  - `/api/surgeon/otp/request`
  - `/api/surgeon/otp/verify`
- RVU uses its own local Postgres on the RVU VM, not the old shared CAL database on that box.

## Access

Primary SSH user:

- user: `dnaile748`

Known working key on the Linux workstation:

- `/home/dnaile748/.ssh/id_ed25519`

Important SSH targets:

- RVU VM: `ssh dnaile748@192.168.5.61`
- edge VM: `ssh dnaile748@192.168.5.75`

On the Mac, copy or use the matching private key before doing any deploy or inspection work.

## Live RVU VM (`192.168.5.61`)

Important paths:

- live repo: `/opt/rvu`
- backup script: `/opt/rvu/scripts/backup-prod.sh`
- compose project: `/opt/rvu/docker-compose.yml`
- backend health check: `http://127.0.0.1:3010/api/health`

Critical runtime facts:

- live port: `3010`
- production URL: `BASE_URL=https://rvu.midfloridasurgical.com`
- allowed origin: `RVU_CORS_ORIGINS=https://rvu.midfloridasurgical.com`
- secure cookie mode: `RVU_COOKIE_SECURE=true`
- live DB container: `rvu_shadow_postgres`
- live DB name: `rvu_prod`

## Known Production Pitfall

If RVU suddenly fails after a restart, check `/opt/rvu/.env` first.

The bad state seen before was:

- `DATABASE_URL=postgresql://cal_user:...@127.0.0.1:5432/surgical_cal`

That is wrong on `5.61`.

The working production pattern is:

- `DATABASE_URL=postgresql://rvu_app:...@127.0.0.1:5432/rvu_prod`

If logs show DB auth failures for `cal_user`, do not debug app code first. Fix `.env` and recreate `rvu_api`.

## Edge VM (`192.168.5.75`)

Role:

- shared nginx ingress for production domains

For RVU:

- `rvu.midfloridasurgical.com` -> `192.168.5.61:3010`

Source-controlled edge config on the Linux workstation:

- `/home/dnaile748/app-migration/edge-nginx/`
- RVU site file: `/home/dnaile748/app-migration/edge-nginx/sites/rvu.midfloridasurgical.com.conf`
- shared proxy headers: `/home/dnaile748/app-migration/edge-nginx/snippets/proxy_headers.conf`

## Current Recovery-Grade Checks

From the RVU VM:

```bash
cd /opt/rvu
git rev-parse --short HEAD
git status
docker compose ps
docker compose logs --tail 100 rvu_api
curl -sf http://127.0.0.1:3010/api/health
curl -sf http://127.0.0.1:3010/api/version
```

From the edge VM:

```bash
sudo nginx -t
sudo systemctl status nginx --no-pager
sudo tail -n 100 /var/log/nginx/access.log
sudo tail -n 100 /var/log/nginx/error.log
curl -sf http://192.168.5.61:3010/api/health
```

Public checks:

```bash
curl -I https://rvu.midfloridasurgical.com
curl -sf https://rvu.midfloridasurgical.com/api/health
curl -sf https://rvu.midfloridasurgical.com/api/version
```

## Current Mac Recovery Procedure

Use this if the Mac dev environment needs to be rebuilt from scratch.

1. Clone the repo fresh on the Mac.

```bash
git clone ssh://git@git.midfloridasurgical.com:2222/NCS/RVU.git
cd RVU
```

2. Compare the fresh clone against production `5.61` before doing any local work.

```bash
ssh dnaile748@192.168.5.61 'cd /opt/rvu && git rev-parse HEAD && git status --short'
git rev-parse HEAD
git status --short
```

3. Recreate the env file on the Mac from the production contract, not from memory.

Minimum critical values:

- `BASE_URL=https://rvu.midfloridasurgical.com` for production-like testing
- `RVU_CORS_ORIGINS=...`
- `RVU_COOKIE_SECURE=...`
- `DATABASE_URL=...`
- `SECRET_KEY=...`

For pure Mac local dev, use local-safe values only if you are intentionally running a local stack. Do not overwrite production `.env` assumptions in the repo.

4. Bring up the stack locally.

```bash
docker compose up -d --build
curl -sf http://127.0.0.1:3010/api/health
```

If not using Docker:

```bash
cd backend
pip install -r requirements.txt
export $(grep -v '^#' ../.env | xargs)
PYTHONPATH=. uvicorn app.main:app --reload --host 127.0.0.1 --port 3010
```

And separately:

```bash
cd frontend
npm install
npm run dev
```

5. Before any deploy from the Mac, verify that `5.61` is still the same target and `5.75` is still the ingress box.

## Mobile-Specific Note

As of 2026-05-14, iPhone and Android capture were hitting a duplicate workflow bug:

- the native app persisted OCR scans first
- if the client dropped the response, the user saw an error
- then manual entry created a duplicate row

The shared native fix lives in:

- `rvu-native/src/api/index.ts`
- `rvu-native/app/scan.tsx`

That is a mobile client issue, not a failure of the RVU save path on `5.61`.

## Backup / Safety

- production backup script: `/opt/rvu/scripts/backup-prod.sh`
- Wasabi backup config is documented outside this repo in `/home/dnaile748/WASABI_REFERENCE.md`

Do not do risky production work on RVU without confirming:

- current git HEAD on `5.61`
- current `.env` correctness
- current `docker compose ps`
- successful local backup path

## Files To Read First In Cursor

- `README.md`
- `CODEX_PROD_HANDOFF.md`
- `CURSOR_MAC_RECOVERY.md`
- `docs/DEPLOY_RUNBOOK.md`
- `deploy/cutover_to_rvu_vm.sh`
- `scripts/sync_shadow_from_prod.sh`

## Short Version

If Cursor only needs the essentials:

- prod app lives on `192.168.5.61` in `/opt/rvu`
- public ingress lives on `192.168.5.75`
- do not let `.env` drift back to `cal_user/surgical_cal`
- verify against `5.61` before rebuilding the Mac environment
