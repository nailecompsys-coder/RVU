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
3. Product -> Archive in Xcode.
4. Validate archive in Organizer.
5. Upload to App Store Connect.
6. Assign to internal testers in TestFlight.
7. Confirm smoke tests against production backend.

## Release readiness gates

- [ ] Backend deploy runbook complete (`docs/DEPLOY_RUNBOOK.md`)
- [ ] Backend health and TLS checks pass
- [ ] iOS simulator matrix completed
- [ ] TestFlight upload processed successfully
- [ ] Internal tester confirmation received

## Notes

- Keep mobile API endpoint switching explicit and auditable.
- Do not release a mobile build if backend parity checks are red.
