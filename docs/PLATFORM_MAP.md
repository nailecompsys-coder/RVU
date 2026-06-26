# RVU Platform Map

Git-tracked copy of the workspace platform map. Canonical path on the dev Mac:

`/Users/donnaile/dev/rvu/docs/PLATFORM_MAP.md`

Keep both files in sync when updating topology, repos, or routing rules.

See [PLATFORM_MAP workspace copy](/Users/donnaile/dev/rvu/docs/PLATFORM_MAP.md) — if paths differ, the workspace root file is authoritative for AI entry points; this copy travels with the `prod-rvu` repo.

For full content, read the workspace file or the sections in [`AGENTS.md`](../AGENTS.md) and [`docs/REPO_SOURCE_OF_TRUTH.md`](REPO_SOURCE_OF_TRUTH.md).

## Quick reference

| Surface | Local path | Production |
|---------|------------|------------|
| Backend API | `backend/` | `rvu-5.61:/opt/rvu/backend` |
| Admin portal (React) | `frontend/` | `rvu-5.61:/opt/rvu/frontend` |
| Native iOS | `../mobile-swiftui-overhaul/native-ios/` | TestFlight |
| Compose mirror | `../mobile-swiftui-overhaul/native-android-compose/` | Emulator |
| Edge SSL | — | `192.168.5.75` (nginx) |
| App VM | — | `192.168.5.61` (`rvu_api :3010`) |

Agent guides: [`AGENTS.md`](../AGENTS.md) · Workspace [`/Users/donnaile/dev/rvu/AGENTS.md`](/Users/donnaile/dev/rvu/AGENTS.md)
