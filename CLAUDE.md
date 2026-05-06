# CLAUDE.md — RVU Insight (RVU Tool)
# rvu.midfloridasurgical.com — Mid-Florida Surgical Associates

> Auto-loaded by Claude Code at session start.
> Read this before touching any code.

---

## What This App Does

RVU Insight is a mobile-first physician billing intelligence tool. Surgeons photograph an EMR charge screen; AI (OCR + LLM) extracts CPT codes and calculates RVU values and estimated reimbursement.

- **Users:** Surgeons authenticated via Cal (shared SSO cookie)
- **Domain:** `rvu.midfloridasurgical.com` → WAN IP 50.192.210.75

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python) — `backend/app/` |
| Frontend | React + Vite build output in `frontend/dist/` (served by FastAPI) |
| Auth | Shared surgeon SSO cookie + RVU portal/admin auth routes |
| Database | PostgreSQL `surgical_cal` on `atlas-postgres` — reads Cal tables, writes `rvu_scans` |
| OCR/AI | PaddleOCR (vision) + Ollama LLM (`OLLAMA_BASE` in `.env`) |
| Runtime | Production systemd; local Docker parity path supported |

---

## Project Structure

```
/home/dnaile748/rvu/
├── backend/                 ← working directory for the running service
│   ├── app/
│   │   ├── main.py          ← FastAPI entry; serves React SPA + API; create_all on startup
│   │   ├── auth.py          ← JWT helpers (ALGORITHM, SECRET_KEY)
│   │   ├── database.py      ← connects to surgical_cal on atlas-postgres
│   │   ├── cal_models.py    ← read-only mirrors of Cal tables (Surgeon, SurgeonDevice, etc.)
│   │   ├── models_rvu.py    ← RVU-owned models (RvuScan, etc.)
│   │   ├── api/
│   │   │   ├── deps.py      ← get_current_staff — validates surgeon_token cookie or Bearer header
│   │   │   ├── routes_auth.py ← auth routes
│   │   │   └── routes_rvu.py  ← rvu_router + portal_router
│   │   ├── rvu/             ← RVU business logic (OCR, CPT lookup, RVU calc)
│   │   └── services/        ← service layer
│   └── requirements.txt
├── frontend/
│   └── dist/                ← compiled React/Vite SPA (served by FastAPI's spa_fallback)
├── .venv/                   ← Python venv used by the systemd service
├── deploy/
│   ├── rvu-api.service      ← systemd unit (installed at /etc/systemd/system/rvu-api.service)
│   ├── nginx-rvu.conf       ← nginx config (installed at /etc/nginx/sites-available/rvu)
│   └── bootstrap-rvu-cert.sh
├── cursor/                  ← Cursor UI/brand guide docs (not code)
├── .env                     ← secrets — NEVER commit
├── Dockerfile               ← exists but NOT USED IN PRODUCTION (see Runtime below)
└── docker-compose.yml       ← exists but NOT USED IN PRODUCTION (see Runtime below)
```

---

## Runtime policy

Production runs as a systemd service. Local development may run either Docker Compose or host uvicorn, but must follow the same env contract.

Canonical reference: `docs/ENVIRONMENT_BASELINE.md`.

**Systemd service:** `rvu-api.service`
**Service file:** `/etc/systemd/system/rvu-api.service`
**Process:** `uvicorn app.main:app --host 0.0.0.0 --port 3010 --workers 2`
**Working dir:** `/home/dnaile748/rvu/backend/`
**Venv:** `/home/dnaile748/rvu/.venv/`
**Port:** `3010`

---

## Deploy / Restart

```bash
# After backend code changes — restart the service
sudo systemctl restart rvu-api.service

# Check status
sudo systemctl status rvu-api.service

# View logs
sudo journalctl -u rvu-api -f

# Verify running
curl -sf http://127.0.0.1:3010/api/health
```

**After frontend changes** (if editing `frontend/`):
```bash
cd /home/dnaile748/rvu/frontend
npm run build        # rebuilds frontend/dist/
sudo systemctl restart rvu-api.service
```

> If deps changed (`requirements.txt`), install before restarting:
> ```bash
> cd /home/dnaile748/rvu/backend
> pip install -r requirements.txt   # inside whatever venv the service uses
> sudo systemctl restart rvu-api.service
> ```

---

## Database

- **Container:** `atlas-postgres` (shared with Cal, Atlas)
- **Database:** `surgical_cal` (same DB as Cal)
- **Connect:** `127.0.0.1:5432` (Docker local parity uses host networking so this remains valid)
- **Tables RVU reads (Cal-owned, read-only):** `surgeons`, `surgeon_devices`, `magic_links`
- **Tables RVU owns:** `rvu_scans` — created automatically on startup (`checkfirst=True`)

### rvu_scans schema
```
id, surgeon_id (FK), scanned_at, cpts (JSON text), locality_num, locality_name,
facility (bool), total_rvu, total_payment, cf, ai_model, image_kb, elapsed_secs
```

---

## Auth

RVU accepts Cal's shared `surgeon_token` cookie and also supports RVU portal/admin login endpoints.

How it works:
1. Surgeon logs into `cal.midfloridasurgical.com` — gets `surgeon_token` cookie
2. Cookie is set on `.midfloridasurgical.com` parent domain (shared)
3. Surgeon visits `rvu.midfloridasurgical.com` — same cookie is sent
4. RVU validates it using the same `SECRET_KEY` as Cal
5. If no valid cookie → redirect to `CAL_URL/surgeon/register`

**Critical:** `SECRET_KEY` in `rvu/.env` MUST match `SECRET_KEY` in `cal/.env`. If Cal rotates its key, RVU must also be updated or all surgeons get logged out of RVU.

---

## Environment Variables (.env)

```
DATABASE_URL=postgresql://cal_user:...@127.0.0.1:5432/surgical_cal
SECRET_KEY=<must match cal/.env>
BASE_URL=https://rvu.midfloridasurgical.com
CAL_URL=https://cal.midfloridasurgical.com

OLLAMA_BASE=http://192.168.5.67:11434   ← ⚠️ verify this IP — may be another LAN machine
VISION_MODEL=qwen2.5vl:7b
TEXT_MODEL=llama3.2:3b
VISION_PROVIDER=paddle

RVU_LOCK_LOCAL_ONLY=true
RVU_COOKIE_SECURE=true
RVU_DEFAULT_CF=41.0
```

> ⚠️ `OLLAMA_BASE` points to `192.168.5.67` — this is NOT llm-core's LAN IP (192.168.20.10).
> Verify this is a different machine on the LAN, or change to `http://127.0.0.1:11434` to use local Ollama.

---

## Relationship to Cal

| What | Where it lives | RVU's access |
|------|---------------|-------------|
| Surgeon list | `surgeons` table (Cal-owned) | Read-only mirror in `rvu/app/models.py` |
| Auth sessions | `surgeon_devices` table (Cal-owned) | Read-only — validates JWT device_id |
| Magic links | `magic_links` table (Cal-owned) | Read-only mirror |
| RVU scan history | `rvu_scans` table (RVU-owned) | Full read/write |
| Login flow | Cal handles it | RVU redirects to CAL_URL |
| Logout | Cal handles it | `/logout` → redirects to CAL_URL/surgeon/logout |

**Do NOT modify Cal's surgeon auth, token format, or SECRET_KEY without also updating RVU.**
**Do NOT add Cal's tables to RVU's `Base.metadata.create_all` — they already exist in Cal.**

---

## Nginx

- **Config:** `/etc/nginx/sites-available/rvu` (symlinked to sites-enabled, active)
- **Proxies:** `rvu.midfloridasurgical.com:443` → `127.0.0.1:3010`
- **SSL:** Let's Encrypt cert at `/etc/letsencrypt/live/rvu.midfloridasurgical.com/` (87 days remaining as of 2026-03-27)

---

## Design System (from `cursor/rvu-insight-guide.md`)

- **Brand:** RVU Insight — premium, calm, clinical
- **Primary Blue:** `#6FA8DC` | **Primary Green:** `#A8D5BA` | **Accent Teal:** `#5BC0BE`
- **Background:** `#FFFFFF` / `#F5F7FA` | **Text:** `#2A3F54` / `#6B7C93`
- **Gradient:** `linear-gradient(135deg, #6FA8DC 0%, #A8D5BA 100%)`
- **Font:** Inter / SF Pro / Geist — no condensed fonts

---

## Guardrails

- **NEVER** treat local runtime experiments as source of truth; production baseline rules
- **NEVER** skip parity checks before deploy
- **NEVER** change `SECRET_KEY` without simultaneously updating `cal/.env` to match
- **NEVER** run `Base.metadata.create_all` on Cal's tables — only create `rvu_scans`
- **NEVER** write to Cal's tables from RVU — read-only mirrors only
- **NEVER** hardcode credentials — all secrets in `.env`

---

## Session Start Checklist

1. Read this file
2. Check `sudo systemctl status rvu-api.service` — confirm it's running
3. Verify `curl -sf http://127.0.0.1:3010/api/health`
4. Read `rvu/.env` — confirm OLLAMA_BASE is pointing to the right host
5. Ask Don what to work on

---

## Server Context

- **Server:** `llm-core` at 192.168.20.10
- **Full server doc:** `/home/dnaile748/SERVER_MASTER.md`
- **This app path:** `/home/dnaile748/rvu/`
- **Domain:** `rvu.midfloridasurgical.com` → WAN IP 50.192.210.75 → host nginx → 127.0.0.1:3010
