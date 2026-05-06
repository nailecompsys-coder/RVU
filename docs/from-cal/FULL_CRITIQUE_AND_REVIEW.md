# Full Program Critique & Review — Cal Scheduler
**Date:** March 2026  
**Purpose:** Multi-perspective review for a growing scheduling app: auth, mobile, rules, UX, palette, and infrastructure.

**Current state:** See `docs/APP_REFERENCE.md` for full reference. A **rules engine** is implemented (`app/rules_engine/`); config in Admin → Settings → Scheduling rules (first card). Mobile logout link added. Some items below are done; use this doc for remaining gaps and design context.

---

## Executive Summary

The app has grown from a simple call schedule into a **full group calendar** with admin portal and surgeon mobile, multiple schedule types (call, clinic, surgical, days off, meetings), and conflict checks. **It does not yet function as it should** in several critical areas: mobile auth (no logout/login), surgical add flow (location not defaulted from context), conflict UX (warnings don’t clear), date/time pickers (native only), and a **rules engine** is now implemented (see APP_REFERENCE.md). Below is a structured critique from several “models” (technical, UX, rules, design, infrastructure) with concrete fixes and a path to a rules-based scheduling layer.

---

## 1. Technical / Architecture Perspective

### 1.1 Is this object-based?

**Yes, but loosely.** The backend is OOP (FastAPI, SQLAlchemy models, router classes). There is no domain “scheduling engine” or rule objects; logic is spread across:

- **`conflicts.py`** — one function `check_conflicts()` that returns a list of strings. No rule objects, no pluggable rules.
- **`routers/admin.py`** — large file (~1400+ lines) with many endpoints; surgical, clinic, call, days off, meetings, settings. Business logic lives in route handlers.
- **`models.py`** — clear ORM models (Surgeon, Location, CallRotation, DayOff, SurgicalCase, etc.). Relationships are well defined.

**Verdict:** Object-based in the small (models, auth helpers). Not object-based in the large: no SchedulingRule, ConflictResolver, or LocationContext abstractions. Good candidate to introduce a **rules layer** (see Section 3).

### 1.2 Infrastructure fit for growth

| Area | Current | Assessment |
|------|---------|------------|
| **Auth** | Cookie-based (admin_token, surgeon_token), JWT in cookies, magic-link for surgeon registration | Works for 2–15 users. Mobile has no logout (see Section 2). |
| **DB** | PostgreSQL, SQLAlchemy, `create_all` on startup | Adequate. No migrations tool (e.g. Alembic) — schema changes are manual. |
| **Routers** | auth, admin, surgeon, api | admin.py is a single large router; consider splitting by domain (call_schedule, clinic_schedule, daysoff, surgical, settings). |
| **Templates** | Jinja2, base_admin / base_surgeon | Two distinct “apps” (portal vs mobile). Shared tokens in PALETTES.md not consistently applied. |
| **Conflict detection** | One function, called at write time (days off, meetings, surgical add/edit) | No persistent “conflict state”; warnings are URL params only. |

**Recommendation:** Add a **rules engine** module (e.g. `scheduling_rules/` or `rules/`) with rule classes and a conflict resolver that returns structured results (not just strings). Keep `conflicts.py` as a thin wrapper that calls the engine. Plan for Alembic (or similar) if schema churn continues.

---

## 2. UX / Auth Perspective — “Mobile does not logout or login”

### 2.1 Mobile logout

**Finding:** The surgeon mobile layout (`base_surgeon.html`) has **no logout control**. The bottom nav has: Schedule, Call Schedule, Availability, Days Off, Patients. There is no link to `/surgeon/logout`. The route exists (`auth.py`: `@router.get("/surgeon/logout")` → redirect to `/surgeon/register` and delete cookie), but the UI never surfaces it.

**Fix:** Add a logout entry in the surgeon UI. Options:

- **Settings/Profile** screen with “Log out” that links to `/surgeon/logout`.
- Or a subtle “Log out” in the header/top bar of the surgeon schedule so it’s always available.

### 2.2 Mobile login

**Finding:** Surgeon “login” is **magic-link registration** (`/register?token=...`). There is no password login for surgeons. So “mobile does not login” may mean:

- Magic link expired or already used → user sees error and has no way to “log in” again except request a new link.
- Or: on first visit, user is sent to `/admin/login` (root `/` with no cookie → redirect to admin login). So from a cold start, **everyone** sees the admin login page. Surgeons must use a link that goes to `/register?token=...` to get a surgeon cookie; then root `/` will send them to `/surgeon/schedule`.

**Fix:**

- **Root behavior:** Document clearly: “Staff open the portal URL and log in with username/password; surgeons open the magic link from the office.” Optionally add a “Surgeon? Use your registration link” note on the admin login page.
- **Mobile:** Ensure surgeon logout redirects to a page that explains “You’re logged out; use the link from the office to sign in again” (e.g. `/surgeon/register` with no token, or a small “logged out” view) instead of a bare register form.

### 2.3 “When I login to Chrome it takes me to the cal portal screen”

**Finding:** Root `/` (e.g. `cal.midfloridasurgical.com`) logic is:

1. If `surgeon_token` cookie → redirect to `/surgeon/schedule`.
2. Else if `admin_token` cookie → redirect to `/admin/dashboard`.
3. Else → redirect to `/admin/login`.

So in Chrome, if you log in as **admin** (username/password), you correctly get the **portal** (dashboard). If you expect a different landing page for admin (e.g. calendar instead of dashboard), that’s a product choice; the code is consistent with “admin = portal, surgeon = schedule.”

**Recommendation:** If the desired behavior is “admin always lands on Calendar” (or another screen), change the post-login redirect in `auth.py` from `/admin/dashboard` to that URL. No technical bug; clarify product intent.

---

## 3. Rules Engine & Scheduling Logic Perspective

### 3.1 Current “rules”

- **Conflicts** are computed by `check_conflicts()` in `conflicts.py`: overlaps with days off, call rotations, clinic, unavailability, other surgeries. Returns a list of human-readable strings.
- **No explicit rules** for:
  - How to **time** surgical procedures (e.g. block length, buffer between cases, OR turnover).
  - **Location-scoped** rules (e.g. “this OR at Altamonte is available at this time”).
  - **Conflict resolution** (what “fixed” means; no re-evaluation on next load).

So: you have **reactive** conflict detection at save time, but no **rules engine** for scheduling constraints or for clearing conflicts once data is fixed.

### 3.2 “When I place surgical schedule in Altamonte the site asks for that site not another”

**Finding:** On Clinic Schedule, when you click a **hospital** pill (e.g. AdventHealth Altamonte) for a surgeon/date, the **surgical timeline** opens and “Add case” opens the add form. The add form has a **Location** dropdown defaulting to “— Select location —”. The **hospital you clicked (e.g. Altamonte) is not passed** into the modal. So the user must manually select the same site again.

**Fix:** Pass **location context** into the timeline and add form:

- In `clinic_schedule.html`, when rendering a hospital pill, pass `entry.location.id` (and optionally name) into `openHospitalTimeline(surgeonId, dateIso, surgeonName, dayLabel, locationId)`.
- In `openCaseAdd()` (and when opening add from timeline), set the location dropdown to that `locationId` so the default is the site you’re scheduling for.

This is a small front-end + template change; no new API.

### 3.3 “Scheduling conflicts do not clear after fixed”

**Finding:** Conflicts are shown via **URL query param** `warn=...` (e.g. after adding a day off or a surgical case). The banner is rendered from `request.query_params.get('warn')`. There is **no re-check** on page load:

- If the user fixes the underlying conflict (e.g. moves the case or removes the day off), the **URL may still** contain `warn=...` from the previous redirect, so the banner can still show.
- Or the next action does a new redirect without `warn`, and the banner disappears even if a conflict still exists.

So “don’t clear after fixed” can mean: (1) after fixing, the old warning still shows until you navigate, or (2) we never re-run conflict check on load to hide the banner when conflicts are gone.

**Fix:**

- **Option A:** On pages that show `warn`, do a **one-time re-check** (e.g. for the current surgeon/date) and only show the banner if conflicts still exist; otherwise clear or don’t render the banner and strip `warn` from links/redirects for the next action.
- **Option B:** Don’t persist `warn` in the URL across unrelated navigations; only add it on the redirect that follows the action that created the conflict. Then “fix and refresh” or “fix and click elsewhere” doesn’t keep showing the old message.

Either way, conflict display should be tied to **current data**, not only to the last redirect.

### 3.4 Toward a real rules engine

Recommendation for future work:

- **Rule types:** e.g. `OverlapRule`, `LocationAvailabilityRule`, `ProcedureTimingRule` (duration, buffers).
- **Conflict model:** Store or return structured conflicts (surgeon, date, type, message, suggested fix) so the UI can show “Conflict: …” and “Resolve” or “Ignore” consistently.
- **Surgical timing:** Introduce rules for procedure duration, turnaround, and (optionally) location capacity so “how to time surgical procedures” is configurable rather than ad hoc.

---

## 4. Date/Time Pickers & Forms Perspective

### 4.1 “Date and time pickers suck”

**Current state:** Templates use **native** HTML5:

- `<input type="date">` (e.g. daysoff, surgical_schedule, clinic_schedule).
- `<input type="time">` (surgical add/edit, clinic_schedule add case).

On mobile, native pickers are often clunky (iOS/Android behavior varies, no shared look and feel).

**Recommendation:**

- **Short term:** Ensure inputs use `min`, `max`, and `step` where appropriate (e.g. time step 15 min), and that labels and tap targets are large enough on mobile.
- **Medium term:** Introduce a **small shared component** (or a single JS lib) for date/time used in admin and (if needed) surgeon flows. Options: Flatpickr, a Tailwind-friendly component, or a minimal custom wrapper that still uses native inputs but improves layout and validation. Avoid a heavy framework; keep server-rendered forms.

---

## 5. Design System / Palette Perspective

### 5.1 “I want my palette followed”

**Current state:** `PALETTES.md` defines **Clinical Trust** (and others) with CSS variables (e.g. `--bg`, `--text`, `--accent`, `--success`, typography scale). Usage:

- **base_surgeon.html** — Tailwind `theme.extend.colors` with slate/blue hex values that align with the palette; custom gradient background; DM Sans.
- **base_admin.html** — Same Tailwind extend (slate/blue), sidebar uses `#0066CC` and rgba; some hardcoded colors in templates.

**Gaps:**

- Many templates still use **Tailwind semantic names** (e.g. `bg-blue-600`, `text-slate-500`) instead of CSS variables from PALETTES.md. So palette changes require searching and replacing in many files.
- No single “design token” file (e.g. one CSS or JS file) that both bases import so that **one** place defines `--accent`, `--text`, etc., and components use `var(--accent)`.

**Recommendation:**

- Add a **single shared palette file** (e.g. `static/palette.css` or in base templates) that defines Clinical Trust variables from PALETTES.md.
- In `base_admin.html` and `base_surgeon.html`, load that file and use `var(--accent)` (and similar) for key UI elements. Gradually replace hardcoded hex in critical components (buttons, sidebar, cards, alerts).
- Reference PALETTES.md in CLAUDE.md and in a short “Design” section of the repo so new work follows the same tokens.

---

## 6. Summary Table — What’s Broken vs What Exists

| Area | Issue | Severity | Fix (short) |
|------|--------|----------|-------------|
| **Mobile logout** | No link to logout in surgeon UI | High | Add “Log out” (e.g. in header or Settings) → `/surgeon/logout` |
| **Mobile login** | Surgeons only get in via magic link; root shows admin login | Medium | Document flow; optionally add “Surgeon? Use your link” on login page |
| **Portal redirect** | Admin login → dashboard; may want Calendar | Low | Change post-login redirect if product wants different default |
| **Surgical add location** | Add-case form doesn’t default to the hospital you clicked | High | Pass location into timeline/add modal; set location dropdown default |
| **Conflicts don’t clear** | Warn banner from URL doesn’t re-check after fix | High | Re-check on load or stop persisting warn in URL; tie banner to current data |
| **Date/time pickers** | Native only; poor on mobile | Medium | Add shared component or small lib; improve mobile UX |
| **Rules engine** | No pluggable rules; no procedure timing rules | Medium | Introduce rules module; structured conflicts; later procedure/location rules |
| **Palette** | Not consistently applied; hardcoded colors | Medium | Shared palette CSS; use var(--…) in bases and key components |
| **admin.py size** | One large router | Low | Split by domain when touching those areas |
| **Conflict model** | Only strings; no “resolved” or re-check on load | Medium | Structured conflict type; re-check when showing warn |

---

## 7. Recommended Order of Work

1. **Mobile logout** — Add logout to surgeon UI (quick win).
2. **Surgical add default location** — Pass hospital from timeline into add form and set default (quick win).
3. **Conflict clearing** — Re-check when displaying `warn` or avoid persisting `warn` across navigations; show banner only when conflicts still exist.
4. **Palette** — One palette CSS file; use in both bases and high-traffic pages.
5. **Date/time** — One shared date/time input pattern or small lib for admin (and surgeon if needed).
6. **Rules engine** — Design a small `scheduling_rules` (or `rules`) module; move conflict logic into rule objects; add structured conflict result and optional “procedure timing” rules later.

---

## 8. Document References

- **CLAUDE.md** — Tech stack, project structure, auth flow.
- **CRITIQUE.md** — Previous critique and doc sync.
- **PALETTES.md** — Design tokens; target for single source of truth.
- **ABBREVIATIONS.md** — Calendar abbreviations (OFF, NC, AH, CL, etc.).
- **PLAN_UI_CLEANUP_AND_CALL_GROUPS.md** — Call groups, ordering, pastel UI.

This document is the **full review** across technical, UX, rules, design, and infrastructure perspectives and should be updated as fixes are implemented and as the rules engine is introduced.
