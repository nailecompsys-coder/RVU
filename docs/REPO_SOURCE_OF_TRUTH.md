# RVU Repo Source Of Truth

This document exists to prevent split-repo drift.

## Canonical Paths

| Surface | Local path | Production path | Git |
| --- | --- | --- | --- |
| Backend/API | `/Users/donnaile/dev/rvu/prod-rvu/backend` | `rvu-5.61:/opt/rvu/backend` | `git@github.com:nailecompsys-coder/RVU.git` on `main` |
| Portal/staff web | `/Users/donnaile/dev/rvu/prod-rvu/frontend` | `rvu-5.61:/opt/rvu/frontend` | Same repo as backend |
| Docker/deploy | `/Users/donnaile/dev/rvu/prod-rvu` | `rvu-5.61:/opt/rvu` | Same repo as backend |
| Mobile mainline | `/Users/donnaile/dev/rvu/mobile` | TestFlight/EAS | `git@github.com:nailecompsys-coder/rvu-native.git` on `main` |
| Native iOS overhaul | `/Users/donnaile/dev/rvu/mobile-swiftui-overhaul` | TestFlight native build line | Worktree of `mobile`, branch `ios-swiftui-overhaul` |

## Current Native Build Line

Native iOS beta `2.5 (46)` is in:

```text
/Users/donnaile/dev/rvu/mobile-swiftui-overhaul/native-ios/project.yml
```

The values are:

```yaml
MARKETING_VERSION: 2.5
CURRENT_PROJECT_VERSION: 46
```

That worktree tracks `origin/ios-swiftui-overhaul`.

## Retired Paths

Do not use these for current work:

| Path | Reason |
| --- | --- |
| `/Users/donnaile/dev/rvu/api` | Old split API repo. It is not the production backend source. |
| `/Users/donnaile/dev/rvu/portal` | Removed duplicate portal repo. The only portal is `prod-rvu/frontend`. |
| `/home/dnaile748/rvu` on the VM | Old deploy material. Active production runs from `/opt/rvu`. |

## Required Preflight

Run this before editing or deploying:

```bash
/Users/donnaile/dev/rvu/scripts/rvu-dev-status.sh
```

It prints the active repo map, Git status, the native build number, and production VM layout checks.
The committed copy lives at `prod-rvu/scripts/rvu-dev-status.sh`.

## Deploy Rule

Deploy backend/API plus portal from the Mac with:

```bash
cd /Users/donnaile/dev/rvu/prod-rvu
deploy/release_from_mac.sh rvu-prod
```

That script builds `frontend/dist`, bundles the backend, frontend build, Dockerfile, compose file, and deploy scripts, then installs them into `rvu-5.61:/opt/rvu`.
