# RVU Project Structure Standard

This is the required structure for RVU and future products. It exists so humans,
Cursor, Codex, and production deploy scripts all use the same paths.

## Decision

Use one product workspace with explicit app surfaces inside it.

Do not create random sibling repos per feature. Do not create duplicate portal,
API, or mobile folders. Every surface has one owner path.

## Product Workspace

The local product workspace is:

```text
/Users/donnaile/dev/rvu
```

The production VM runtime is:

```text
rvu-5.61:/opt/rvu
```

The Git source of truth is the repo listed for each surface below.

## Required Layout

```text
rvu/
  prod-rvu/                  # canonical backend, portal, deploy, docs
    backend/                 # FastAPI API and services
    frontend/                # React portal/staff web hub
    deploy/                  # prod bundle/deploy scripts
    docs/                    # source-of-truth docs
    scripts/                 # repo-owned status/preflight tools

  mobile/                    # React Native / Expo mobile mainline

  mobile-swiftui-overhaul/   # SwiftUI native iOS worktree

  scripts/                   # local workspace guardrails
  WORKSPACE_SETUP.md         # local map for this Mac workspace
```

## Surface Ownership

| Surface | Required path | Git repo | Deploy target |
| --- | --- | --- | --- |
| Product docs that must travel with Git | `prod-rvu/docs` | `nailecompsys-coder/RVU.git` | N/A |
| Backend/API | `prod-rvu/backend` | `nailecompsys-coder/RVU.git` | `rvu-5.61:/opt/rvu/backend` |
| Portal PC hub | `prod-rvu/frontend` | `nailecompsys-coder/RVU.git` | `rvu-5.61:/opt/rvu/frontend` |
| Docker/deploy context | `prod-rvu` | `nailecompsys-coder/RVU.git` | `rvu-5.61:/opt/rvu` |
| React Native mobile | `mobile` | `nailecompsys-coder/rvu-native.git` | EAS/TestFlight/Android build pipeline |
| Native SwiftUI iOS | `mobile-swiftui-overhaul` | `rvu-native.git`, worktree branch `ios-swiftui-overhaul` | Xcode/TestFlight |

## Naming Rules

- Product workspace uses the product name: `rvu`.
- The PC web hub is always called `frontend` inside the canonical app repo.
- The API is always called `backend` inside the canonical app repo.
- Native iOS code can live in a mobile repo/worktree when Xcode tooling needs its own structure.
- Android should be a React Native target under `mobile` unless there is a proven reason to split it.
- There is no folder named `portal` at the workspace root.
- There is no active split repo named `api`.

## Why Not One Giant Directory

One giant directory is fine only when one toolchain owns everything. RVU has
different deployment and build systems:

- backend plus portal deploy together to the production VM
- SwiftUI iOS uses Xcode/TestFlight
- React Native mobile uses EAS and will own Android

Keeping those surfaces separate avoids toolchain noise while preserving one
clear product workspace.

## Why Not Many Loose Repos

Loose repos caused drift. RVU no longer uses one repo for API, another for
portal, another for deploy, and another for docs. Backend, portal, deploy, and
production docs live together in `prod-rvu` because they ship together.

## Agent Rules

Every AI agent must do this before work:

```bash
/Users/donnaile/dev/rvu/scripts/rvu-dev-status.sh
```

Then follow these rules:

- If the task says portal, dashboard, reporting, staff web, admin web, PC hub, or C-suite dashboard, edit `prod-rvu/frontend`.
- If the task says API, database, RVU math, CPT, OCR, auth, Docker, or prod deploy, edit `prod-rvu/backend` or `prod-rvu/deploy`.
- If the task says Expo, React Native, or Android, edit `mobile`.
- If the task says SwiftUI, Xcode, native iOS, TestFlight build `2.5 (46)`, edit `mobile-swiftui-overhaul`.
- If a path conflicts with this document, stop and update the source-of-truth docs before coding.

## Documentation Rules

Docs do not live wherever an agent happens to be.

- Product-wide and production docs live in `prod-rvu/docs`.
- Mobile-specific docs live in `mobile/docs`.
- SwiftUI-specific docs live in `mobile-swiftui-overhaul/docs`.
- Local machine notes may live at workspace root, but must not be treated as the Git source of truth.
- Any changed path, deploy target, branch, build number, or retired folder must be updated in `prod-rvu/docs/REPO_SOURCE_OF_TRUTH.md`.

## Current Retired Paths

Do not create or use:

```text
/Users/donnaile/dev/rvu/api
/Users/donnaile/dev/rvu/portal
```

The retired `api` repo may remain only as a historical repo with guard scripts
that fail loudly. The retired `portal` folder should not exist.
