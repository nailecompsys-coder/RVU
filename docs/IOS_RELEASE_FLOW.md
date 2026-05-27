# iOS Simulator And TestFlight Flow

This runbook standardizes local iOS validation and TestFlight release against the RVU backend baseline.

## Prerequisites

- macOS with Xcode installed.
- Apple Developer account access for the app bundle.
- Correct signing assets (team, certificates, provisioning profiles).
- Backend API reachable for the target environment.

## Environment mapping

| Target | API base URL | Intended use |
|---|---|---|
| Local simulator | `http://127.0.0.1:3010` (or Mac-resolved local endpoint) | Rapid development and smoke tests |
| Production validation | `https://rvu.midfloridasurgical.com` | Pre-release acceptance and TestFlight confidence |

## Build + simulator checklist

1. Ensure backend baseline checks pass:
   - `scripts/preflight_env_parity.sh`
   - `curl -sf http://127.0.0.1:3010/api/health` (if local backend)
2. Open iOS project/workspace in Xcode.
3. Select intended simulator device matrix (at minimum current iPhone size + one previous generation).
4. Build and run.
5. Validate critical flows:
   - Auth/session behavior
   - Capture/upload/API calls
   - Error handling for network failures

## Archive + TestFlight checklist

1. Switch app config to production API base URL.
2. Increment build/version metadata.
3. Write a `BETA FIX` tester summary with every fixed, added, and changed item.
4. Product -> Archive in Xcode.
5. Validate archive in Organizer.
6. Upload to App Store Connect.
7. Assign to internal testers in TestFlight.
8. Confirm smoke tests against production backend.

## BETA FIX Summary

Every TestFlight build must include a plain-language `BETA FIX` list before upload. This is the message Donna can text to testers.

Include:
- Fixes
- Added features
- Changed behavior
- Backend/API changes affecting the app
- Known issues still under watch

Do not upload a TestFlight build without this list.

## Release readiness gates

- [ ] Backend deploy runbook complete (`docs/DEPLOY_RUNBOOK.md`)
- [ ] Backend health and TLS checks pass
- [ ] iOS simulator matrix completed
- [ ] `BETA FIX` tester summary written
- [ ] TestFlight upload processed successfully
- [ ] Internal tester confirmation received

## Notes

- Keep mobile API endpoint switching explicit and auditable.
- Do not release a mobile build if backend parity checks are red.
