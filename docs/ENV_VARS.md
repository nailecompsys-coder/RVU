# RVU Environment Variables

This is the canonical env contract for RVU across local and production.

## Required in all environments

| Variable | Example | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql://user:pass@127.0.0.1:5432/surgical_cal` | Primary DB connection string |
| `SECRET_KEY` | long random string | JWT/session signing key |
| `BASE_URL` | `https://rvu.midfloridasurgical.com` | Absolute URL generation |
| `RVU_CORS_ORIGINS` | comma-separated URLs | Allowed browser origins |
| `RVU_COOKIE_SECURE` | `true`/`false` | Secure cookie enforcement |

## Required for current auth model

| Variable | Example | Notes |
|---|---|---|
| `CAL_URL` | `https://cal.midfloridasurgical.com` | Redirect target for shared surgeon flow |

## Required for OCR/AI features

| Variable | Example |
|---|---|
| `OLLAMA_BASE` | `http://127.0.0.1:11434` |
| `VISION_MODEL` | `qwen2.5vl:7b` |
| `TEXT_MODEL` | `llama3.2:3b` |
| `VISION_PROVIDER` | `paddle` |

## RVU behavior flags

| Variable | Default | Notes |
|---|---|---|
| `RVU_LOCK_LOCAL_ONLY` | `true` | Limit local behavior as configured by app |
| `RVU_DEFAULT_CF` | `41.0` | Conversion factor fallback |

## Email feature variables

Required only if email sending is enabled.

- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`

## Production-safe values

- `BASE_URL=https://rvu.midfloridasurgical.com`
- `RVU_CORS_ORIGINS=https://rvu.midfloridasurgical.com`
- `RVU_COOKIE_SECURE=true`
- `DATABASE_URL` points to production DB endpoint on the production host

## Parity notes

- Local and production must use the same variable names and semantic meaning.
- `.env.example` is the template contract; `.env` is instance-specific and never committed.
