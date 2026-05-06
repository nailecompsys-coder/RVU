# Cal — App Reference (single source of truth)

**Purpose:** One document that describes how the app runs, its structure, config, routes, models, rules engine, and templates so no questions are needed.

**Referenced by:** `.cursor/rules/CLAUDE.md` (session checklist), `.cursor/rules/build_app.md` (Cal project). Follow rules in CLAUDE.md, build_app.md, and `.cursor/rules/PALETTES.md` when changing UI or architecture.

---

## 1. What the app is

- **Name:** Mid Florida Surgical Calendar (Cal).
- **Role:** Scheduling app for a surgical group: admin portal (staff) + mobile PWA (surgeons). Manages call rotations, clinic schedule, surgical cases, days off, meetings, locations, conflict checks.
- **Stack:** FastAPI, SQLAlchemy, PostgreSQL, Jinja2, Tailwind, vanilla JS. Optional: Wasabi S3 backup, Web Push (VAPID).

---

## 2. How to run

### Env (required)

- **`DATABASE_URL`** — PostgreSQL, e.g. `postgresql://user:password@host:5432/surgical_cal`.
- **`SECRET_KEY`** — JWT signing (admin + surgeon tokens).

### Env (optional)

- **`APP_VERSION`** — Shown in admin sidebar (default `1.2.0` from `app/__init__.py`).
- **`BASE_URL`** — For magic links (e.g. `https://cal.midfloridasurgical.com`).
- **`MAGIC_LINK_EXPIRE_HOURS`** — Default 168 (7 days).
- **`VAPID_PUBLIC_KEY`**, **`VAPID_PRIVATE_KEY`**, **`VAPID_EMAIL`** — Web Push (surgeon notifications). If missing, push is no-op.
- **Wasabi backup:** `WASABI_BUCKET`, `WASABI_KEY_ID`, `WASABI_SECRET`, `WASABI_REGION` (default `us-east-1`), optional `WASABI_ENDPOINT`.

Ref: `.env.example`.

### Local (no Docker)

```bash
# From project root, with .env present
uvicorn app.main:app --reload --port 3005
```

### Docker

```bash
docker compose up --build
# App: http://127.0.0.1:3005
```

- **Dockerfile:** `python:3.11-slim`, installs `libpq-dev`, `postgresql-client`, runs `uvicorn app.main:app --host 0.0.0.0 --port 3005 --workers 2`.
- **Health:** `GET /health` → `{"status":"ok","version":"..."}`.

### First-time DB

- Tables: `Base.metadata.create_all(bind=engine)` on startup (no Alembic migrations).
- Seed (admin + locations + surgeons): `docker exec -it cal_api python seed.py` or `DATABASE_URL=... python seed.py`. Uses `ADMIN_USERNAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` from env if set.

---

## 3. Entry and auth

### Root `/`

- Cookie `surgeon_token` → redirect `/surgeon/schedule`.
- Else cookie `admin_token` → redirect `/admin/dashboard`.
- Else → redirect `/admin/login`.

### Admin

- **Login:** `GET/POST /admin/login`. Cookie `admin_token` (JWT, 12h). Logout: `GET /admin/logout` (delete cookie).
- **Dependency:** `get_current_admin` (auth.py) — requires valid `admin_token` cookie else redirect to `/admin/login`.

### Surgeon (mobile)

- **No password.** Registration via magic link: admin generates link (Surgeons → Magic link); surgeon opens `/register?token=...`, POST registers device and gets `surgeon_token` cookie (JWT, 1 year).
- **Logout:** `GET /surgeon/logout` → delete cookie, redirect `/surgeon/register`. Surgeon UI has “Log out” in top-right (base_surgeon.html).
- **Dependency:** `get_current_surgeon` returns `(Surgeon, SurgeonDevice)`.

---

## 4. Project layout

```
cal/
├── app/
│   ├── __init__.py          # __version__ from APP_VERSION
│   ├── main.py               # FastAPI app, lifespan, /, /health
│   ├── database.py           # engine, SessionLocal, get_db
│   ├── models.py             # SQLAlchemy models (see below)
│   ├── auth.py               # admin/surgeon JWT, magic link, get_current_*
│   ├── conflicts.py          # check_conflicts() → calls rules engine, returns list[str]
│   ├── push.py               # send_push_to_surgeon, VAPID
│   ├── wasabi_backup.py      # list_backups, run_backup, restore
│   ├── migrate_call_groups.py # run_migration() on startup
│   ├── routers/
│   │   ├── auth.py           # /admin/login, /admin/logout, /register, /surgeon/logout
│   │   ├── admin.py          # prefix /admin — all admin HTML + POSTs
│   │   ├── surgeon.py        # prefix /surgeon — mobile pages
│   │   └── api.py            # prefix /api — events feed, push subscribe, health
│   ├── rules_engine/
│   │   ├── __init__.py       # re-exports evaluate, get_rule_config, Conflict, ALL_RULES
│   │   ├── registry.py       # RuleDef, Conflict, ALL_RULES (built from checkers)
│   │   ├── checkers.py       # one function per rule (overlap + buffer + location)
│   │   └── engine.py         # get_rule_config(db), ensure_rule_config_seeded(db), evaluate()
│   ├── templates/            # Jinja2
│   │   ├── base_admin.html   # sidebar, request + admin + settings + app_version + wasabi_configured (+ pending_count when passed)
│   │   ├── base_surgeon.html # mobile shell, bottom nav
│   │   ├── admin/*.html      # dashboard, calendar, surgeons, call_schedule, call_groups, daysoff, meetings, patients, surgical_schedule, locations, clinic_schedule, settings, login
│   │   └── surgeon/*.html    # register, schedule, call_schedule, availability, request_off, patients
│   └── static/               # sw.js, manifest.json, icons
├── docs/                     # ABBREVIATIONS.md, RULES_ENGINE_SPEC.md, FULL_CRITIQUE_AND_REVIEW.md, etc.
├── .env / .env.example
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── seed.py
```

---

## 5. Database models (app/models.py)

| Model | Table | Purpose |
|-------|--------|---------|
| AdminUser | admin_users | Portal login (username, email, password_hash). |
| SiteSettings | site_settings | id=1: practice_name, logo_filename. |
| SchedulingRuleConfig | scheduling_rule_config | rule_id (unique), enabled, config (JSON text). Used by rules engine. |
| Location | locations | name, address, city, location_type (clinic \| hospital), color. |
| Surgeon | surgeons | first_name, last_name, specialty, suffix, staff_type (physician \| staff), email, color. full_name, initials @property. |
| MagicLink | magic_links | surgeon_id, token_hash, expires_at, used_at. |
| SurgeonDevice | surgeon_devices | surgeon_id, device_name, user_agent, token_hash (session). |
| CallGroup | call_groups | name, sort_order. |
| CallGroupLocation | call_group_locations | call_group_id, location_id (M2M). |
| CallRotation | call_rotations | call_group_id, surgeon_id (null = NO call), date, rotation_type (primary \| backup). |
| Availability | availability | surgeon_id, date, is_available, start_time, end_time. |
| DayOff | days_off | surgeon_id, start_date, end_date, reason, status (pending \| approved \| denied), notes, admin_note. |
| Meeting | meetings | title, date, start_time, end_time, location_id, location_text, recurrence_rule. |
| MeetingAttendee | meeting_attendees | meeting_id, surgeon_id, status. |
| PatientAssignment | patient_assignments | surgeon_id, date, patient_count, location_id. |
| ClinicSchedule | clinic_schedules | surgeon_id, location_id, date, session (am \| pm \| full). |
| SurgicalCase | surgical_cases | surgeon_id, date, start_time, end_time, patient_name, procedure, location_id, room_text, status. |
| PushSubscription | push_subscriptions | surgeon_id, device_id, endpoint, p256dh, auth_key. |

---

## 6. Admin routes (prefix /admin)

All require `get_current_admin` unless noted.

| Method | Path | Purpose |
|--------|------|---------|
| GET | /dashboard | Dashboard (on-call today, pending days off, meetings, surgeons). |
| GET | /calendar | FullCalendar view; events from /api/events. |
| GET | /surgeons | List surgeons; add/edit/delete, magic link, revoke device. |
| GET | /call-schedule | Call rotation grid by week; assign, reclaim-orphans, copy-week, clear. |
| GET | /call-groups | Call groups CRUD, attach locations. |
| GET | /daysoff | Days off list; add, approve, deny, edit, delete. Passes pending_count for sidebar badge. |
| GET | /meetings | Meetings list; add, delete. |
| GET | /patients | Patient assignments by date. |
| GET | /surgical-schedule | Surgical cases; add, edit, delete (by week). |
| GET | /locations | Locations CRUD. |
| GET | /clinic-schedule | Clinic grid by week; assign, clear, copy-week. |
| GET | /settings | Settings page: **first card = Scheduling rules** (rule_config, all_rules from rules engine). Then Branding, Login & users, Session, Mobile devices, Backup & Restore. |
| POST | /settings | Save practice_name, logo. |
| POST | /settings/rules | Save scheduling rule config (enabled + config JSON per rule). |
| POST | /settings/remove-logo | Remove logo. |
| POST | /settings/users/add | Add admin user. |
| POST | /settings/users/{id}/set-password | Set password. |
| POST | /settings/users/{id}/toggle | Activate/deactivate admin. |
| POST | /settings/backup/run | Wasabi backup (pg_dump, gzip, upload). |
| POST | /settings/backup/restore | Restore from Wasabi (password + confirm). |

Admin template context: `_base(request, admin, **kwargs)` injects request, admin, today, settings, app_version, wasabi_configured. Settings page also injects rule_config, all_rules (with try/except; on failure passes [] and {} so page still renders).

---

## 7. Surgeon routes (prefix /surgeon)

All require `get_current_surgeon` (except register). Router also defines GET /register (duplicate of auth router for same path).

| Method | Path | Purpose |
|--------|------|---------|
| GET | /schedule | Mobile schedule (week view, clinic/surgery/day off/meetings). Hospital pills open surgical bottom sheet. |
| POST | /surgical-case/{id}/notes | Update surgeon_notes on a case. |
| GET | /call-schedule | Call schedule view. |
| GET | /availability | Set available/unavailable by date. |
| POST | /availability/save | Save availability; runs check_conflicts for warnings. |
| GET | /request-off | Request days off form. |
| POST | /request-off | Submit day off request. |
| GET | /patients | Patient list. |

---

## 8. API routes (prefix /api)

| Method | Path | Purpose |
|--------|------|---------|
| GET | /health | Same as root /health (if mounted). |
| GET | /vapid-public-key | For push subscription. |
| GET | /events | FullCalendar event feed (query params start/end). Returns compact events (abbreviations, day-off grouping). |
| GET | /my-events | Filtered by surgeon (for mobile). |
| POST | /push/subscribe | Register push subscription (surgeon). |

---

## 9. Rules engine (conflict checks)

- **Entry:** `conflicts.check_conflicts(surgeon_id, start_date, end_date, db, exclude_*_id=...)` → `list[str]` (messages). Used after saving day off, clinic, surgical case, meeting, call rotation; and on surgeon availability save.
- **Flow:** `check_conflicts` builds `exclude_entity` from exclude_* args, calls `rules_engine.evaluate(...)`, returns `[c.message for c in conflicts]`.
- **Config:** Stored in DB table `scheduling_rule_config` (rule_id, enabled, config JSON). On startup `ensure_rule_config_seeded(db)` inserts missing rules with defaults. Settings page loads via `get_rule_config(db)` and saves via POST /admin/settings/rules.
- **Rules (registry.py + checkers.py):** Overlap: OVERLAP_DAY_OFF, OVERLAP_CALL, OVERLAP_CLINIC, OVERLAP_SURGERY, OVERLAP_UNAVAILABLE, OVERLAP_MEETING. Buffer: BUFFER_CLINIC_TO_SURGERY, BUFFER_SURGERY_TO_CLINIC, BUFFER_BETWEEN_CASES, BUFFER_SAME_SITE_AM_PM (config: minutes). Location: LOCATION_DRIVE_TIME (minutes_between_sites). Each checker can take exclude_entity to skip the entity being saved.
- **Settings UI:** Admin → Settings. **Scheduling rules is the first card** (open by default). Checkboxes to enable/disable, number inputs for buffer/location params. “Save scheduling rules” → POST /admin/settings/rules.

---

## 10. Conflict redirect behavior

- After save (day off, clinic, surgery, meeting, call), admin routes call `check_conflicts` and `_warn_redirect(base_url, conflicts)`: if conflicts, redirect with `?warn=<encoded messages>` so the target page can show “Scheduling conflict: …”. Clearing = fix data and re-save; re-run returns no conflicts.

---

## 11. Startup (main.py lifespan)

1. `Base.metadata.create_all(bind=engine)`
2. `migrate_call_groups.run_migration()` — add call_group_id column if missing, seed call groups, reclaim orphans
3. `admin._get_settings(db)` — prime SiteSettings cache (id=1)
4. `ensure_rule_config_seeded(db)` — ensure every rule has a row in scheduling_rule_config
5. db.close()

---

## 12. Templates (quick map)

- **base_admin.html:** Sidebar (Calendar, Surgeons, Call Schedule, Meetings, Days Off, Patients, Locations, Settings), main content block, optional pending_count for Days Off badge.
- **base_surgeon.html:** Mobile shell, bottom nav (Schedule, Call, Availability, Days Off, Patients), “Log out” top-right.
- **admin/settings.html:** First section = Scheduling rules (id=scheduling-rules), then Branding, Login & users, then right column Session, Mobile devices, Backup & Restore. Flash messages via `request.query_params.get('msg')` (saved, rules_saved, user_added, etc.).
- **admin/calendar.html:** FullCalendar; events from /api/events; filter buttons; legend.
- **surgeon/schedule.html:** Week view; location pills (hospital pills open surgical bottom sheet); day sheet and surgical sheet.

---

## 13. Static and uploads

- **Static:** `app/static` mounted at `/static` (sw.js, manifest.json, icons).
- **Uploads:** Logo stored in `app/static/uploads/` (path in code: `UPLOADS_DIR = "app/static/uploads"` in admin.py). SiteSettings.logo_filename references filename only.

---

## 14. Other docs and rules

- **.cursor/rules/CLAUDE.md** — Session start checklist; references this file. Follow guardrails and checklist.
- **.cursor/rules/build_app.md** — ATLAS workflow; Cal reference = this file; memory = project root `memory.md`.
- **.cursor/rules/PALETTES.md** — Design tokens; Cal uses Clinical Trust. Never hardcode colors.
- **memory.md** (project root) — Session state, next steps; update before closing (per build_app.md).
- **docs/RULES_ENGINE_SPEC.md** — Spec and persona (Valerie Reyes) for rules; implementation in app/rules_engine.
- **docs/ABBREVIATIONS.md** — Calendar event abbreviations (initials, locations, types).
- **docs/CRITIQUE.md**, **docs/FULL_CRITIQUE_AND_REVIEW.md** — Critique and remaining gaps.
- **docs/PLAN_UI_CLEANUP_AND_CALL_GROUPS.md** — Plan; call groups and rules engine implemented.
- **Changes to Calendar.md** — Don's product direction.

---

## 15. Quick reference: key files to touch

| Need to… | File(s) |
|----------|--------|
| Change port or startup | Dockerfile CMD, docker-compose ports, uvicorn. |
| Add env var | .env.example, then use in app (e.g. database.py, auth.py, push.py, wasabi_backup.py). |
| Add DB table/column | app/models.py; if migration needed before create_all, add in migrate_* or lifespan. |
| Add admin page | app/routers/admin.py (GET + POST), app/templates/admin/*.html, sidebar link in base_admin.html. |
| Add surgeon page | app/routers/surgeon.py, app/templates/surgeon/*.html, base_surgeon.html nav. |
| Add API endpoint | app/routers/api.py. |
| Change conflict rules | app/rules_engine/registry.py (RuleDef), app/rules_engine/checkers.py (new checker), engine.py get_rule_config if new config keys. |
| Change Settings layout | app/templates/admin/settings.html. Scheduling rules is first card; Branding and Login & users follow. |

This document is the single reference for the app; use it before asking how things work or where to change something.
