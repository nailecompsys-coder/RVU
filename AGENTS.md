# RVU Backend + Admin Portal — Agent Guide

Repo: [`prod-rvu`](.) — FastAPI backend and React admin portal. Deploys to `rvu-5.61:/opt/rvu`.

**Platform map:** [`/Users/donnaile/dev/rvu/docs/PLATFORM_MAP.md`](/Users/donnaile/dev/rvu/docs/PLATFORM_MAP.md)

## Layout

| Path | Stack | Edit for… |
|------|-------|-----------|
| [`backend/app/api/`](backend/app/api/) | FastAPI routes | REST API, mobile contract |
| [`backend/app/services/`](backend/app/services/) | Python services | OCR, CPT rules, RVU math, retention |
| [`backend/app/models_rvu.py`](backend/app/models_rvu.py) | SQLAlchemy | Domain models |
| [`frontend/src/pages/`](frontend/src/pages/) | React + Vite | Admin portal UI |
| [`frontend/src/api/`](frontend/src/api/) | TypeScript | Portal API client |
| [`deploy/`](deploy/) | Shell + nginx refs | Production deploy |

## Mobile API contract

Native apps (SwiftUI, Compose, Expo) call:
- Base: `https://rvu.midfloridasurgical.com`
- Routes: `/api/v1/rvu/*`, auth via `cal.midfloridasurgical.com`

When API response shape or semantics change, evaluate:
- `mobile-swiftui-overhaul/native-ios/`
- `mobile-swiftui-overhaul/native-android-compose/`

## Default task routing

| User asks for… | Work in… |
|----------------|----------|
| API endpoint, business logic, DB | `backend/` |
| Portal dashboard, staff pages, admin UI | `frontend/` |
| Docker, prod deploy | `deploy/` — explicit request |
| Mobile UI only | **Do not edit here** — go to `mobile-swiftui-overhaul/` |

## Local dev

```bash
cd backend && pip install -r requirements.txt
PYTHONPATH=. uvicorn app.main:app --reload --host 127.0.0.1 --port 3010

cd frontend && npm install && npm run dev
```

## Deploy

[`docs/DEPLOY_RUNBOOK.md`](docs/DEPLOY_RUNBOOK.md) — `deploy/release_from_mac.sh rvu-prod`

Never run deploy or SSH without explicit user request.

## Read first

- [`docs/REPO_SOURCE_OF_TRUTH.md`](docs/REPO_SOURCE_OF_TRUTH.md)
- [`docs/DEPLOY_RUNBOOK.md`](docs/DEPLOY_RUNBOOK.md)
- [`RVU_HARD_RULES.md`](/Users/donnaile/dev/rvu/RVU_HARD_RULES.md)
