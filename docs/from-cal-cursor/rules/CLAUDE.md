# CLAUDE.md — cal.midfloridasurgical
# Call Schedule System — Mid-Florida Surgical Associates

> This file is loaded automatically by Claude Code at session start.
> Read this fully before touching any code.

---

## What This App Does

A **call schedule management system** for Mid-Florida Surgical Associates (MFSA).
- **Production / beta** — in use by **2 users** at cal.midfloridasurgical.com
- **11 staff** (physicians, PAs, NPs) — scaling to 15 soon
- **Portal** (admin) = **hub** — assigns call schedule, clinic schedule, approves days off, manages meetings
- **Mobile** = **individual docs/staff** — each user sees own schedule + practice call schedule (read-only)
- **Backup:** Wasabi S3 via Settings → Backup & Restore; DB and app are production-critical

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python) |
| Templating | Jinja2 HTML templates (`templates/`) |
| Static Assets | `static/` directory (CSS, JS, images) |
| Auth | Cookie-based (`admin_token` / `surgeon_token`), bcrypt 4.0.1 pinned |
| Database | PostgreSQL — `surgical_cal` DB on `atlas-postgres` container |
| ORM | SQLAlchemy — `Base.metadata.create_all` on startup |
| Conflict Detection | Rules engine `app/rules_engine/`; entry point `conflicts.check_conflicts()` |
| Containerization | Docker + `docker-compose.yml` |
| Server | `llm-core` — `/home/dnaile748/cal/` |
| Domain | `cal.midfloridasurgical.com` (SSL via Certbot) |
| Container | `cal_api` on `127.0.0.1:3005` |

**Server-rendered app** — Jinja2 templates, no React, no Vite, no separate build step.

**Auth flow (from `main.py`):** Root `/` checks cookies → `surgeon_token` → `/surgeon/schedule`, `admin_token` → `/admin/dashboard`, neither → `/admin/login`.

---

## Project File Structure

```
/home/dnaile748/cal/
├── app/
│   ├── main.py              ← app entry point, lifespan (create_all, migrate_call_groups, rule seed)
│   ├── auth.py              ← JWT + bcrypt, magic link, device sessions
│   ├── database.py          ← PostgreSQL connection pool
│   ├── models.py            ← data models (see Core Tables)
│   ├── push.py              ← VAPID / web push
│   ├── conflicts.py         ← thin wrapper; calls rules_engine.evaluate()
│   ├── rules_engine/        ← registry, checkers, engine; config in scheduling_rule_config
│   ├── routers/
│   │   ├── admin.py         ← dashboard, calendar, surgeons, call-schedule, call-groups,
│   │   │                     daysoff, meetings, patients, surgical-schedule, locations,
│   │   │                     clinic-schedule, settings (first card = Scheduling rules)
│   │   ├── api.py           ← /events (FullCalendar feed), /my-events, push subscribe
│   │   ├── surgeon.py       ← schedule, call-schedule, availability, request-off, patients
│   │   └── auth.py          ← admin login, register (magic link), surgeon logout
│   ├── static/              ← sw.js, manifest.json, icons; uploads in static/uploads/
│   └── templates/
│       ├── base_admin.html
│       ├── base_surgeon.html
│       ├── admin/           ← login, dashboard, calendar, surgeons, call_schedule, call_groups,
│       │                     daysoff, meetings, patients, surgical_schedule, locations,
│       │                     clinic_schedule, settings
│       └── surgeon/         ← register, schedule, call_schedule, availability, request_off, patients
├── docs/
│   ├── APP_REFERENCE.md     ← single source of truth: run, routes, models, rules, templates
│   ├── RULES_ENGINE_SPEC.md ← rule spec & persona (Valerie Reyes)
│   ├── ABBREVIATIONS.md     ← calendar abbreviations
│   ├── CRITIQUE.md          ← program critique & doc sync
│   ├── FULL_CRITIQUE_AND_REVIEW.md
│   └── PLAN_UI_CLEANUP_AND_CALL_GROUPS.md
├── .cursor/rules/
│   ├── CLAUDE.md            ← this file
│   ├── build_app.md         ← ATLAS workflow
│   └── PALETTES.md          ← design tokens — never hardcode colors
├── .env                     ← secrets — never commit
├── Changes to Calendar.md   ← Don's product direction
├── Dockerfile
├── docker-compose.yml
├── memory.md                ← session state, next steps (update before closing)
├── requirements.txt         ← all versions pinned
└── seed.py                  ← database seeder
```

**Full app reference:** Read `docs/APP_REFERENCE.md` for run instructions, env, all routes, models, rules engine, and where to change things.

---

## Key Dependencies (requirements.txt — pinned)

- `bcrypt==4.0.1` — **pinned intentionally** — prevents passlib incompatibility bug
- All other versions locked — do not upgrade without testing

> ⚠️ Do NOT run `pip install --upgrade` or change `bcrypt` version. The 4.0.1 pin is deliberate.

---

## Surgeons / Physicians (canonical MFSA roster — reference only)

UI labels use **Physicians** (sidebar, pages, modals). DB table is `surgeons`. Production may differ from seed. Surgeon colors use PALETTES.md `--surgeon-N` tokens (index = DB id).

| Initials | Name |
|----------|------|
| JF | Jorge L. Florin, MD |
| CJ | Christopher Johnson, DO |
| JB | Jason Boardman, MD |
| AS | Alexander Schroeder, MD |
| OK | Owen Kieran, DO |
| LW | Lucy Woodley, MD |
| GY | Geoff Yurcisin, MD |
| LN | Lars Nelson, MD |
| NF | Nadia Froehling, MD |
| JP | Jennine L. Putnick, MD |

`Surgeon` model: `staff_type` (physician | staff), `suffix` (MD, DO, PA-C, NP, etc.) — no "Dr" prefix; use suffix.

---

## Database

- **Container:** `atlas-postgres` (shared — also runs `snapsendseen` and `atlas` DBs)
- **Database name:** `surgical_cal`
- **Port:** `127.0.0.1:5432` (localhost only ✅)

### Core Tables (verify against models.py; full list in docs/APP_REFERENCE.md)

```
admin_users              — id, username, email, password_hash, role, is_active
site_settings            — id, practice_name, logo_filename
scheduling_rule_config   — rule_id, enabled, config (JSON); rules engine settings
surgeons                 — id, first_name, last_name, specialty, suffix, staff_type, email, phone, color, is_active (initials = property)
magic_links              — surgeon registration tokens
surgeon_devices          — per-device surgeon sessions (JWT keyed to device_id)
locations                — clinics, hospitals
call_groups              — name, sort_order
call_group_locations     — call_group_id, location_id (M2M)
surgeon_location_schedules — default weekly location
location_overrides       — per-day location changes
call_rotations           — call_group_id, surgeon_id (null = NO call), date, rotation_type (primary|backup)
availability             — surgeon availability per date
days_off                 — time-off requests (pending/approved/denied)
meetings                 — staff meetings
meeting_attendees        — surgeon ↔ meeting
patient_assignments      — patient count per surgeon per date
clinic_schedules         — who is at which clinic when (am/pm/full)
surgical_cases           — surgeon, date, start/end time, patient_name, procedure, location_id, status
push_subscriptions      — web push for surgeon devices
```

### ⚠️ Shared Container Warning
`atlas-postgres` runs ALL MFSA databases. Dropping it kills SSS instantly.
**Never restart or modify `atlas-postgres` without Don's explicit confirmation.**

### Backup
Wasabi S3 backup/restore is implemented: Admin → Settings → Backup & Restore. Requires `WASABI_BUCKET`, `WASABI_KEY_ID`, `WASABI_SECRET` in `.env`. Also keep codebase at `/home/dnaile748/cal/`, `.env`, and `app/static/uploads/` under version control or separate backup.

---

## Auth Model

- `bcrypt 4.0.1` for password hashing — do not change
- **Admins:** `admin_users` table, username/email + password, JWT in `admin_token` cookie
- **Surgeons:** Magic-link registration → `SurgeonDevice` + `surgeon_token` (JWT keyed to device_id, 365-day cookie)
- Surgeons see **only their own** schedule entries (enforced in `routers/surgeon.py`)
- Admins see all surgeons, can assign/edit/delete (enforced in `routers/admin.py`)
- Role enforcement is in **backend routers**, not templates

---

## All Running Containers (same server)

| Container | Port | Notes |
|-----------|------|-------|
| `cal_api` | 127.0.0.1:3005 | **This app** ✅ |
| `sss_api_prod` | 127.0.0.1:3002 | SSS API |
| `sss_portal_prod` | 127.0.0.1:3003 | SSS Staff Portal |
| `sss_patient_prod` | 127.0.0.1:3004 | SSS Patient app |
| `atlas-postgres` | 127.0.0.1:5432 | Shared DB — all apps |
| `atlas-metabase` | 0.0.0.0:3001 | ⚠️ Publicly exposed — verify firewall |
| `open-webui` | 127.0.0.1:3000 | Local AI UI |

---

## Deploy Command

```bash
cd /home/dnaile748/cal
docker compose up -d --build cal_api
```

> ⚠️ NEVER run `docker compose down` without specifying `cal_api`.
> Bare `docker compose down` will destroy atlas-postgres and take down SSS.

---

## Guardrails — NEVER DO THESE

- **NEVER change `bcrypt==4.0.1`** — pinned to prevent passlib breakage
- **NEVER run `pip install --upgrade`** without checking breakage against pinned deps
- **NEVER drop or truncate `surgical_cal` tables** without Don's explicit confirmation
- **NEVER expose one surgeon's data to another** — enforce in routers, not templates
- **NEVER skip auth checks** on admin write routes
- **NEVER hardcode credentials** — all secrets in `.env`
- **NEVER run bare `docker compose down`** — kills atlas-postgres, takes SSS offline
- **NEVER restart `atlas-postgres`** without Don confirming SSS downtime is acceptable
- **NEVER auto-deploy** — confirm with Don before every build
- **Flag `atlas-metabase`** — `0.0.0.0:3001` is publicly reachable. Verify UFW blocks port 3001 or this is intentional.

---

## Session Start Checklist

1. Read this file fully
2. Read `docs/APP_REFERENCE.md` for full app reference (run, routes, models, rules engine, templates)
3. Skim `main.py` to see any recent route changes since last session
4. Run `cat .env` to confirm actual env vars — never log or expose output
5. Read `memory.md` — current state and what to work on next
6. Read `.cursor/rules/PALETTES.md` before any UI work — never hardcode colors
7. Read `Changes to Calendar.md` and `docs/CRITIQUE.md` for product direction
8. Ask Don what to work on — never assume and start coding

---

## Related Projects (same server, same postgres)

| Project | Domain | DB | Container | Port |
|---------|--------|----|-----------|------|
| **This app** | cal.midfloridasurgical.com | surgical_cal | cal_api | 3005 |
| SSS API | referral.midfloridasurgical.com | snapsendseen | sss_api_prod | 3002 |
| SSS Portal | referral.midfloridasurgical.com | snapsendseen | sss_portal_prod | 3003 |
| SSS Patient | referral.midfloridasurgical.com | snapsendseen | sss_patient_prod | 3004 |

## Build Workflow

Follow ATLAS framework — see `.cursor/rules/build_app.md`. For Cal-specific reference (routes, models, rules, deploy), see `docs/APP_REFERENCE.md`.
