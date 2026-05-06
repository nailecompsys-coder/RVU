# RVU app architecture

## Backend (OOP)

| Layer | Path | Role |
|-------|------|------|
| **Models** | `app/cal_models.py` | Shared practice DB schema (surgeons, devices, admin users, etc.). |
| | `app/models_rvu.py` | `RvuScan` — RVU scan rows (`rvu_scans` table). |
| **Services** | `app/services/rvu_payment_service.py` | CPT cleanup, `calc_payment` rows, `save_scan`, localities payload. |
| | `app/services/ollama_cpt_service.py` | Image shrink, Ollama streaming, CPT JSON parse. |
| **API** | `app/api/routes_auth.py` | Magic link register (JSON), staff `me`, portal login, cookies. |
| | `app/api/routes_rvu.py` | `/api/v1/rvu/*`, `/api/v1/portal/rvu/scans`. |
| | `app/api/deps.py` | `get_current_staff` → 401 JSON. |

## Frontend (React)

| Route | Page |
|-------|------|
| `/` | Home |
| `/register` | Paste magic-link token |
| `/capture` | Staff CPT lookup (extend with camera + SSE) |
| `/history` | Staff scan history |
| `/portal/login` | Admin JSON login |
| `/portal` | Aggregate scans table |

## Database

Single PostgreSQL shared with other practice services that use the same `DATABASE_URL`. **Do not** run conflicting Alembic from multiple apps unless coordinated; services typically use `create_all(checkfirst=True)` on startup.

## Runtime

- Production baseline: systemd service + nginx + TLS.
- Local preferred parity: Docker Compose with `network_mode: host`.
- Local fallback: host uvicorn from `backend/`.
- Canonical policy: `docs/ENVIRONMENT_BASELINE.md`.

## Docker

Build order: `npm run build` in `frontend/`, then `docker build` at repo root (Dockerfile copies `frontend/dist`).
