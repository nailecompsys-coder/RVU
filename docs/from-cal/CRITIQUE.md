# Cal Scheduler — Program Critique & Document Sync
**Date:** March 2026

**See also:** `docs/APP_REFERENCE.md` for current app reference (routes, models, rules engine, run). Rules engine is implemented; config in Admin → Settings → Scheduling rules (first card).

---

## Executive Summary

The app is a **full group calendar** with call schedule, call groups, clinic schedules, surgical cases, days off, meetings, patient assignments, locations, push notifications, magic-link auth, and a **rules engine** for conflict detection. **Architecture:** Portal = hub; Mobile = individual docs/staff. **11 staff** now, scaling to 15.

---

## 1. Schema & Structure (Synced)

CLAUDE.md Core Tables match models.py. Actual tables:

- **admin_users** — Admin login (username/email, password)
- **site_settings** — Practice name, logo
- **surgeons** — Physicians, PAs, NPs (staff_type)
- **magic_links** — One-time surgeon registration links
- **surgeon_devices** — Per-device sessions for surgeons
- **locations** — Clinics, hospitals
- **surgeon_location_schedules** — Default weekly location
- **location_overrides** — Per-day location changes
- **call_rotations** — Primary/backup on-call (user-facing: "Call Schedule")
- **availability** — Surgeon availability per date
- **days_off** — Time-off requests (pending/approved/denied)
- **meetings** — Staff meetings with attendees
- **meeting_attendees** — Surgeon ↔ meeting
- **patient_assignments** — Patient count per surgeon per date
- **clinic_schedules** — Who is at which clinic when (am/pm/full)
- **push_subscriptions** — Web push for surgeon devices

### File Structure

CLAUDE.md project structure lists all admin and surgeon templates including `call_schedule.html`, `clinic_schedule.html`, `daysoff.html`, `meetings.html`, `patients.html`, `locations.html`, `settings.html`, `request_off.html`, `availability.html`.

### memory.md

- In project root. Update before closing (see build_app.md). Surgeon color index = DB id (see `.cursor/rules/PALETTES.md`).

---

## 2. What the App Actually Does

| Feature | Status |
|---------|--------|
| Admin login (username/email + password) | ✅ |
| Surgeon magic-link registration | ✅ |
| Per-device surgeon sessions (365-day cookie) | ✅ |
| Call schedule (primary/backup on-call) | ✅ |
| Clinic schedules (location + session am/pm/full) | ✅ |
| Days off (request, approve, deny) | ✅ |
| Meetings with attendees | ✅ |
| Patient assignments (count per surgeon per date) | ✅ |
| Locations (clinics, hospitals) | ✅ |
| Conflict detection (rules engine; conflicts.py entry) | ✅ |
| FullCalendar event feed (API) | ✅ |
| Surgeon mobile: schedule, call schedule (practice-wide), availability, request-off, patients | ✅ |
| Push notifications (VAPID, pywebpush) | ✅ |
| Site settings (logo, practice name) | ✅ |

---

## 3. Product Direction (Changes to Calendar.md)

Status as of code review — most items implemented:

| Request | Status | Notes |
|---------|--------|-------|
| Single calendar screen, less repetition | ✅ | Calendar + filter; Clinic Schedule, Call Schedule separate |
| Rename "Surgeons" → "Physicians" | ✅ | Sidebar, surgeons.html, calendar, call assign modal |
| Remove Specialty field | ✅ | Not in add/edit forms; DB column remains, shown only in call assign modal if present |
| Remove "Dr" prefix (PAs, NPs) | ✅ | full_name + suffix (MD, DO, PA-C, NP) everywhere |
| Calendar: list ALL, filter by person on left | ✅ | Physicians & Staff sidebar, All/On-Call/Meetings/Days Off filters |
| Settings: Hospital/Clinic locations | ✅ | locations.html under Settings |
| Under Calendar: Clinic Schedule + Call Schedule | ✅ | Both exist |
| Dashboard: cards (On Call, Meetings, Days Off, etc.) | ✅ | Stat cards + Today's Coverage + Upcoming Meetings + Days Off Pending |
| Big buttons for On Call + Calendar on dashboard | ✅ | Assign On-Call, View calendar, Assign when no primary |
| Mobile: super simple | ✅ | Good morning [name], blue today card |
| Tap day → single-day timeline (7am–8pm, 30-min marks) | ✅ | openDayView bottom sheet with hour labels, gridlines, event blocks |
| Spelled-out labels (not just colored pills) | ✅ | On-Call, Backup, location names, meeting titles, pts count, Day Off |

---

## 4. Critique — Strengths

- **Separation of concerns:** auth.py, conflicts.py, routers, models well separated.
- **Security:** bcrypt 4.0.1 pinned, JWT in httponly cookies.
- **Conflict detection:** conflicts.py used in days-off approval flow.
- **Flexible staff model:** `staff_type` (physician, staff), `suffix` (MD, DO, PA-C, NP).
- **PALETTES.md** — Single source for design tokens; surgeon colors locked.

---

## 5. Critique — Gaps & Risks

| Area | Issue |
|------|-------|
| **Staff roster** | 11 staff now, 15 soon. Production DB may differ from seed placeholders. |
| **specialty column** | Still in DB; not in add/edit forms. Optional display in call assign modal only. |

---

## 6. Document Sync (Completed)

Docs: `docs/APP_REFERENCE.md` is the single app reference. CLAUDE.md, build_app.md, PALETTES.md in `.cursor/rules/`. memory.md in project root. Product Direction table reflects implemented features.
