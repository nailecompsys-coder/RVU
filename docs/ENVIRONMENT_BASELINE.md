# RVU Environment Baseline

This document is the canonical runtime and environment policy for RVU.

## Source of truth

- Production Linux (`llm-core`) is the baseline.
- Local development on Mac must mirror production behavior and env contract.
- If docs conflict, this file wins.

## Runtime matrix

| Environment | Runtime | Reverse proxy | DB target | Healthcheck |
|---|---|---|---|---|
| Production | Docker Compose service `rvu_api` (`network_mode: host`) | nginx (`rvu.midfloridasurgical.com`) | PostgreSQL on `127.0.0.1:5432` | `GET /api/health` |
| Local dev (preferred) | Docker Compose (`network_mode: host`) | none (direct) | same DB contract as prod unless explicitly overridden | `GET /api/health` |
| Local dev (fallback) | host uvicorn from `backend/` | none (direct) | same DB contract as prod unless explicitly overridden | `GET /api/health` |

## Canonical network behavior

- App listens on port `3010`.
- Production ingress is nginx TLS -> upstream app on host.
- Production and local Docker both use host networking so the app reaches PostgreSQL at `127.0.0.1:5432`.
- The legacy systemd unit file in `deploy/rvu-api.service` is reference-only unless production is explicitly moved back to systemd.

## Canonical auth behavior

RVU supports two auth paths:

- Shared surgeon SSO cookie integration with Cal (`surgeon_token` path).
- RVU portal/admin login endpoints (`/api/v1/auth/portal/*`).

Do not remove either flow without explicit product approval.

## Required parity checks before deploy

1. `.env` satisfies required variables and production-safe values.
2. Production `DATABASE_URL` uses `127.0.0.1:5432` for RVU.
3. `docker compose up -d rvu_api` succeeds on the production host.
4. `curl -sf http://127.0.0.1:3010/api/health` succeeds.
5. nginx config test passes (`nginx -t`) and vhost points to RVU upstream.
6. Docs updated if runtime/env behavior changed.

## Guardrails

- Never treat ad-hoc local tweaks as source of truth.
- Never commit secrets (`.env`, private keys, tokens).
- Never assume Docker and host process are equivalent without parity checks.
- Prefer scripted verification (`scripts/preflight_env_parity.sh`, `scripts/verify_runtime.sh`).
