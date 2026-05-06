# Cursor Workflow For RVU

Use this workflow so Cursor can operate safely without repeatedly inspecting production.

## Session start

1. Open project root: `/home/dnaile748/rvu`.
2. Read:
   - `docs/ENVIRONMENT_BASELINE.md`
   - `docs/ENV_VARS.md`
   - `docs/DEPLOY_RUNBOOK.md`
3. Confirm current branch and intended scope.

## Development workflow

1. Make code changes in small batches.
2. If runtime/env behavior changes, update docs in the same change.
3. Run local verification:
   - `scripts/preflight_env_parity.sh`
   - targeted app checks (`curl http://127.0.0.1:3010/api/health`)

## Pre-deploy checklist

1. Ensure changes are documented.
2. Ensure `.env.example` reflects any env contract change.
3. Run parity and runtime checks:
   - `scripts/preflight_env_parity.sh`
   - `scripts/verify_runtime.sh` (where applicable)

## Post-deploy checklist

1. Verify service and health:
   - `systemctl status rvu-api.service`
   - `curl -sf http://127.0.0.1:3010/api/health`
2. Verify public endpoint and TLS.
3. Record any drift findings and resolve immediately.

## Prompt templates

- Implement feature safely:
  - "Implement <feature>. Keep production as source of truth, update docs if env/runtime changes, and run parity checks."
- Deploy prep:
  - "Prepare this branch for production using docs/DEPLOY_RUNBOOK.md and report any parity blockers."
- Drift check:
  - "Compare local assumptions to docs/ENVIRONMENT_BASELINE.md and list mismatches with fixes."
