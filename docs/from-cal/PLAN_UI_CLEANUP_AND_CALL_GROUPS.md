# Plan: UI Cleanup, Call Schedule Groups, and Consistency

Based on screenshots and feedback for Calendar, Clinic Schedule, Days Off, Settings, and Physicians.

**Status:** Call groups are implemented (call_groups, call_group_locations, call_rotations.call_group_id). Scheduling rules engine and Settings card are in place. See `docs/APP_REFERENCE.md` for current structure.

---

## 1. Call Schedule — Buildable Groups (Schema + UX)

**Current:** One "Primary" and one "Backup" per day globally. No link to hospitals or multiple call pools.

**Target:**
- Admin can create **call groups** (e.g. "Orlando Hospitals", "Winter Garden"). Each group has a name and a set of **locations** (hospitals/clinics) that this call covers.
- For each group, per date: assign **Primary**, **Backup**, or **NO call** (explicit no-coverage option).
- UI: "Call Schedule" screen becomes: list of call groups → for each, week grid with Primary / Backup / NO call per day → assign physician or PA to each cell (or "NO call").

**Implementation outline:**
- **New table `call_groups`:** id, name, sort_order.
- **New table `call_group_locations`:** call_group_id, location_id (many-to-many: a group can cover multiple hospitals/clinics).
- **Change `call_rotations`:** add `call_group_id` (FK, nullable for migration); `surgeon_id` nullable = "NO call". Keep rotation_type: primary | backup.
- **Admin UI:** Settings or Call Schedule area to CRUD call groups and attach locations. Call Schedule page: by call group, show week grid; each cell = primary or backup or NO call; assign modal with physician/PA list (grouped: doctors first, then PAs/staff).
- **API/calendar:** Events feed includes which call group each rotation belongs to; calendar can show by group or combined.

---

## 2. Remove "Dr" from All Names

**Current:** Some names display with a "Dr." prefix (e.g. from stored `first_name` like "Dr. Christopher", or from conflict messages that prepend "Dr. {last_name}").

**Target:** **No "Dr" in any user-facing name.** Display names are first name + last name + optional suffix (e.g. MD, PA-C) only.

**Implementation:**
- **Model ([app/models.py](app/models.py)):** In `Surgeon.full_name`, strip a leading "Dr." or "Dr " from `first_name` (and optionally from `last_name`) before concatenating, so existing DB data that includes "Dr." still displays without it. Example: if `first_name` is "Dr. Christopher", display as "Christopher"; then `full_name` = "Christopher Johnson" (+ suffix in templates).
- **Conflict messages ([app/routers/admin.py](app/routers/admin.py)):** Replace `f"Dr. {surgeon.last_name}: "` with `f"{surgeon.full_name}: "` (or `surgeon.last_name`) in all conflict strings (lines 289, 381, 405, 510, 731) so no "Dr." is added there.
- **Templates:** All name display already uses `full_name` (and optionally `suffix`). Once `full_name` strips "Dr", no template changes needed unless any template explicitly adds "Dr."
- **Seed/console:** Optional: [seed.py](seed.py) print statements can drop "Dr." for consistency; not user-facing.

---

## 3. Dropdowns and Lists — Physicians First, Then PAs/Staff; Alphabetical in Each Group

**Current:** Calendar sidebar already sorts physicians then staff. Clinic Schedule, Days Off, Physicians page, and others use `order_by(Surgeon.last_name)` only, so doctors and PAs are interleaved.

**Target:** Every dropdown and every list that shows physicians/staff: **physicians first, then PAs and support staff**; **within each group, sort alphabetically by last name** (A–Z).

**Implementation:**
- **Backend:** Use a shared sort everywhere surgeons are passed to templates:  
  `sorted(surgeons, key=lambda s: (0 if (s.staff_type or "physician") == "physician" else 1, s.last_name))`.  
  That gives Physicians A–Z, then Support Staff A–Z.  
  Apply in: `admin.py` for **surgeons** (Physicians page), clinic_schedule, daysoff, meetings, patients, call_schedule (assign modal), locations (if physician picker), and any other route that passes `surgeons`.
- **Templates:** Where dropdowns are built by hand (e.g. daysoff add form, meetings invite list), use the same pre-sorted list or build two optgroups: "Physicians" then "Support Staff", each sorted by last name.

---

## 4. Pastel / Softer Colors (65K Shades)

**Current:** Full saturation for event colors (e.g. days off red `#fca5a5`, on-call uses surgeon hex, clinic/location colors). Described as "drastic."

**Target:** Use a **pastel palette** across the app: softer, lower saturation. "65K shades" interpreted as a **wider, nuanced palette** (e.g. many pastel variants), not literally 65,536 colors.

**Implementation outline:**
- **PALETTES.md:** Add a "Pastel event" set: e.g. pastel red for days off, pastel blue for primary on-call, pastel purple/gray for backup, pastel green for approved, pastel amber for pending. Define CSS variables or a short list of hexes.
- **Calendar (api.py):** Map event types to pastel colors instead of raw surgeon/location colors (or use surgeon color at 40–50% opacity / blend with white for pastel effect). Keep surgeon identity via a small dot or label if needed.
- **Clinic Schedule:** Use pastel versions of location colors (or a single pastel palette by location type) so the grid is easier to scan.
- **Days Off:** Softer green for approved, softer amber for pending, softer red for deny/conflict.
- **FullCalendar and other components:** Override any hard-coded bright colors with pastel tokens from PALETTES or a small shared pastel map in the template/JS.

---

## 5. Settings — Who Is Logged In + Backup in Cards, No Long Scroll

**Current:** Settings has multiple sections stacked (Branding, Login & users, Backup & Restore); backup widget is already in a card. Long page if many users.

**Target:**
- **"Who is logged in":** Show clearly in Settings (e.g. card at top or sidebar summary): current user name and role (e.g. "Logged in as **admin**").
- **Backup widget:** Keep in a card; ensure it’s visible without excessive scroll.
- **Layout:** All sections in **cards**; consider a **two-column layout on desktop** (e.g. Branding + Login & users on left; Backup & Restore + "Logged in as" on right) so the page doesn’t "scroll a mile long." Optional: collapse sections (accordion) or tabs if needed.

**Files:** [app/templates/admin/settings.html](app/templates/admin/settings.html). Add a "Logged in as" card; refactor layout to grid/cards and optionally two columns.

---

## 6. Clinic and Hospital — Small Icons

**Current:** Location legend and event labels use colored dots and text only. No distinct icon for "clinic" vs "hospital."

**Target:**
- **Hospital:** Use a small icon (e.g. Font Awesome `fa-hospital` or `fa-house-medical`).
- **Clinic:** Use a small icon (e.g. `fa-building-user` or `fa-stethoscope` or `fa-clinic-medical`). Pick one and use consistently.
- Use these in: Calendar event labels, Clinic Schedule legend and grid cells, any location dropdown or list (e.g. Locations page, Call Schedule location picker).

**Files:** [app/templates/admin/calendar.html](app/templates/admin/calendar.html), [app/templates/admin/clinic_schedule.html](app/templates/admin/clinic_schedule.html), [app/routers/api.py](app/routers/api.py) (event title/labels if they include location type), and any other template that lists locations with type.

---

## 7. Calendar — Clean, Crisp, Less Busy

**Current:** Dense event blocks; strong colors; stacked "+N more"; hard to scan.

**Target:**
- **Event styling:** Pastel colors (see above); slightly smaller font or tighter padding; consistent border-radius.
- **Reduce clutter:** Prefer shorter labels where possible (e.g. last name + "Off", or "On-Call" + initial); consider limiting visible text and showing full detail in modal.
- **Whitespace:** Slightly more padding in day cells; ensure "today" is clear without overwhelming.
- **FullCalendar options:** Tune `eventDisplay`, `dayMaxEvents`, and event content to avoid excessive stacking; consider "more" popover that’s easy to read.

**Files:** [app/templates/admin/calendar.html](app/templates/admin/calendar.html) (CSS and FullCalendar config), [app/routers/api.py](app/routers/api.py) (event titles and extendedProps for modal).

---

## 8. Physicians Page — Ordering and Pastel Avatars

**Current:** Table of physicians/staff with avatars (initials in colored circles), contact, devices, status, and action icons. List is ordered by last name only, so doctors and PAs are interleaved. Avatar and status colors are strong (green, blue, purple, orange, red).

**Target:**
- **Ordering:** Same **physicians first, then PAs/staff** (by last_name within each group). Backend: pass surgeons through the same sort used on dashboard/calendar.
- **Avatars:** Use **pastel** versions of surgeon colors (or a shared pastel palette by index) so the table feels softer and consistent with the rest of the app.
- **Status pills:** Softer green for "Active" (pastel green); any inactive state in a muted pastel.
- **Optional:** Add table subheaders or visual separation between "Physicians" and "Support Staff" rows for quicker scanning.

**Files:** [app/routers/admin.py](app/routers/admin.py) (surgeons list and add/edit responses: sort surgeons physicians-first before passing to template), [app/templates/admin/surgeons.html](app/templates/admin/surgeons.html) (avatar and status pill styling using pastel tokens; optional subgroup headers).

---

## 9. Clinic Schedule — Cleanup and Consistency

**Current:** Grid with bright location colors; surgeon column and location legend; surgeons not grouped (doctors first then PAs).

**Target:**
- **Surgeon column:** Use same **physicians-first-then-staff** ordering as elsewhere (backend sort).
- **Location legend:** Add **small icons** for clinic vs hospital; use **pastel** location colors.
- **Grid cells:** Softer (pastel) colors; optional small clinic/hospital icon in each cell. Keep "click to assign" and "+ add" behavior; ensure layout stays readable.

**Files:** [app/routers/admin.py](app/routers/admin.py) (clinic_schedule_page: pass surgeons sorted physicians-first), [app/templates/admin/clinic_schedule.html](app/templates/admin/clinic_schedule.html) (legend icons, pastel styles, any location-type display).

---

## 10. Days Off — Less Scroll, Grouped Display

**Current:** Long vertical list of approved (and pending) cards; can feel like "scroll a mile long."

**Target:**
- **Ordering:** List physicians first, then PAs/staff (same sort as elsewhere).
- **Reduce scroll:** Paginate approved list (e.g. 10 per page) or show a **summary** (e.g. "Next 5" or "This month") with "View all" expanding or linking to a full list. Keep pending list compact.
- **Visual:** Softer (pastel) status colors; consistent card style; optional grouping by "Physicians" / "Support Staff" sections if it helps.

**Files:** [app/routers/admin.py](app/routers/admin.py) (daysoff: sort surgeons; optionally paginate or limit approved with offset/limit), [app/templates/admin/daysoff.html](app/templates/admin/daysoff.html) (grouping/pagination and pastel tweaks).

---

## 11. Summary of Backend Changes

| Area | Change |
|------|--------|
| Call schedule | New tables `call_groups`, `call_group_locations`; `call_rotations` gains `call_group_id`, nullable `surgeon_id` for NO call. New admin UI to manage groups and assign by group. |
| Name display | `Surgeon.full_name` strips leading "Dr." / "Dr " from first_name (and optionally last_name); conflict messages in admin.py use full_name (no "Dr." prefix). |
| Surgeons ordering | Single sort: physicians first, then staff; **alphabetically by last_name within each group** (A–Z). Use everywhere surgeons are sent to templates (dashboard, calendar, surgeons, clinic_schedule, daysoff, meetings, patients, call_schedule, etc.). |
| API events | Pastel color mapping; optional call_group_id in extendedProps; event titles/labels with clinic/hospital icon where relevant. |

---

## 12. Summary of Template/CSS Changes

| Page | Changes |
|------|--------|
| Physicians | Physicians-first ordering in table; pastel avatar and status pill colors; optional Physicians / Support Staff subheaders. |
| Calendar | Pastel event colors; smaller/clearer event styling; possible dayMaxEvents / more popover; clinic/hospital icon in modal or labels. |
| Clinic Schedule | Physicians-first ordering; location legend with clinic/hospital icons; pastel location colors in grid. |
| Days Off | Physicians-first ordering; pagination or summary to cut scroll; pastel status and avatar colors. |
| Settings | "Logged in as" card; layout in cards; two-column or compact grid to avoid long scroll; backup widget in card. |
| Call Schedule | After schema: UI by call group, Primary/Backup/NO call per day, assign modal with physicians-first list; small icons if locations shown. |
| Global | Shared pastel palette (PALETTES.md or inline vars); Font Awesome clinic/hospital icons wherever location type is shown. |

---

## Order of Work (Suggested)

1. **Quick wins (no schema):** Remove "Dr" from all names (full_name strip in model + conflict messages); physicians-first with alphabetical-by-last-name ordering in each group everywhere; "Logged in as" and Settings card layout; pastel palette and apply to Calendar, Physicians, Days Off, and Clinic Schedule; add clinic/hospital icons in legend and lists.
2. **Call groups (schema + UX):** Design and add migrations for `call_groups` and `call_group_locations`; migrate `call_rotations`; build Call Schedule group management and assignment UI; add NO call option; wire calendar/API to groups.
3. **Polish:** Days Off pagination/summary; any remaining pastel or icon tweaks; FullCalendar "more" and density tuning.
