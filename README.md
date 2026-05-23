# RVU — Standalone app (Mid Florida Surgical)

Uses the **same PostgreSQL database** as other practice apps for shared tables: `surgeons`, `surgeon_devices`, `magic_links`, `admin_users`, `rvu_scans`, etc.

**Open this folder for backend, portal, and production deploy work.**

On the dev Mac, the source-of-truth path is:

```text
/Users/donnaile/dev/rvu/prod-rvu
```

On the production VM, the active runtime path is:

```text
rvu-5.61:/opt/rvu
```

There is no separate active portal repo. The only portal/staff web app is `frontend/`.
See [`docs/REPO_SOURCE_OF_TRUTH.md`](docs/REPO_SOURCE_OF_TRUTH.md).

## Layout

| Path | Purpose |
|------|---------|
| `backend/` | FastAPI API — OOP services in `app/services/`, JSON routes in `app/api/` |
| `frontend/` | React 18 + Vite + TypeScript — staff capture + portal |
| `docs/from-cal/` | Archived reference docs (legacy scheduling product) |
| `docs/from-cal-cursor/` | Archived editor rules from the same legacy project |

> **Note:** If you see a legacy `app/` or `.venv` at the **repo root** from older work, prefer **`backend/`** and **`frontend/`** for this project.

## Environment policy

Production Linux is the baseline for this repo. Local development must mirror the production env contract.

- Canonical policy: [`docs/ENVIRONMENT_BASELINE.md`](docs/ENVIRONMENT_BASELINE.md)
- Env contract: [`docs/ENV_VARS.md`](docs/ENV_VARS.md)

## Quick start

1. **Env** — copy `.env.example` → `.env` (use the same `DATABASE_URL` and `SECRET_KEY` as other apps that share this database).

2. **Backend** (host fallback; port **3010**):

```bash
cd backend
pip install -r requirements.txt
export $(grep -v '^#' ../.env | xargs)
PYTHONPATH=. uvicorn app.main:app --reload --host 127.0.0.1 --port 3010
```

3. **Frontend**:

```bash
cd frontend
npm install
npm run dev
```

Vite proxies `/api` → `http://127.0.0.1:3010`.

4. **Local Docker parity (preferred)**:

```bash
cd /home/dnaile748/rvu
docker compose up -d --build
curl -sf http://127.0.0.1:3010/api/health
```

5. **Production build** — `npm run build` in `frontend/`; API serves `/assets` from `frontend/dist` if that folder exists.

## Auth

- **Staff (MD / PA / MA):** magic-link registration. Links must use **this** app’s host, e.g. `https://rvu.midfloridasurgical.com/register?token=...`. If a magic link was generated with another app’s `BASE_URL`, paste the raw token into `/register` on the RVU site.
- **Portal:** practice admin users in `admin_users` — `POST /api/v1/auth/portal/login` (JSON); cookie `admin_token`.

## Deploy / reverse proxy

**Same WAN IP as other sites** (e.g. `50.192.210.75`): DNS `A` for **rvu.midfloridasurgical.com** → that IP — no second public address needed. The edge proxy on that host is **nginx** (see `sss/llm-gateway-updated.conf` in the monorepo for the Atlas + referral pattern). You must add a **dedicated** `server_name rvu.midfloridasurgical.com` block and a **Let’s Encrypt** cert for `rvu`; otherwise HTTPS falls back to the **default_server** (Atlas) and the browser gets the wrong certificate. Step-by-step: **[`deploy/SHARED_WAN_AND_NGINX.md`](deploy/SHARED_WAN_AND_NGINX.md)** and **[`deploy/nginx-rvu.conf`](deploy/nginx-rvu.conf)**.

Aprima Explorer (AEX) on **50.192.210.77** is a different host — unrelated to RVU.

Set `RVU_COOKIE_SECURE=true`, `RVU_CORS_ORIGINS=https://rvu.midfloridasurgical.com`, and `BASE_URL=https://rvu.midfloridasurgical.com` in production.
For the current production Docker setup, RVU must use `DATABASE_URL=...@127.0.0.1:5432/...`.

For deploy sequence and verification steps, use [`docs/DEPLOY_RUNBOOK.md`](docs/DEPLOY_RUNBOOK.md).

## API summary

- `POST /api/v1/auth/register` — `{ "token": "..." }`
- `GET /api/v1/auth/me` — staff session
- `GET /api/v1/rvu/localities`, `POST /api/v1/rvu/lookup`, `POST /api/v1/rvu/vision-stream`, `POST /api/v1/rvu/text-stream`
- `GET /api/v1/rvu/history` — staff’s scans
- `POST /api/v1/auth/portal/login`, `GET /api/v1/auth/portal/me`, `GET /api/v1/portal/rvu/scans`

## Next steps (product)

- OP notes capture + portal (see internal handoff docs).
- Optional: tighten magic-link `BASE_URL` handling so links always target RVU when sent from this app.
