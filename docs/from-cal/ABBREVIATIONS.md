# Calendar & UI Abbreviations — Master List

Used across the admin calendar and related views for compact, scannable cells. For full app reference (routes, models, events feed), see `docs/APP_REFERENCE.md`.

---

## People

| Abbrev | Meaning | Example |
|--------|---------|--------|
| **Initials** | First letter of first name + first letter of last name (uppercase) | Jorge Florin → JF, Christopher Johnson → CJ |

---

## Event types

| Abbrev | Meaning |
|--------|--------|
| **OFF** | Days Off (approved time off) |
| **NC** | No Call / Unavailable (no coverage that day) |
| **MTG** | Meeting |
| **Sx** | Surgery / surgical case |
| **pts** | Patient assignment (e.g. "5 pts") |

---

## Call coverage (hospital groups)

We do **not** use "On-Call" / "Backup" as labels. We use **call group names** (e.g. from Call Schedule).

| Abbrev | Meaning | Notes |
|--------|---------|--------|
| **WG** | Winter Garden / Apopka / Minneola Hospital (or first group) | Call group abbreviation |
| **ALT** | Altamonte Hospital (or second group) | Call group abbreviation |
| *Other* | Derived from group name (first letters or short form) | See `_call_group_abbrev()` in API |

---

## Locations

| Abbrev | Meaning | Notes |
|--------|---------|--------|
| **AH** | Advent Health (hospital) | All hospitals are Advent Health; AH may be combined with site, e.g. AH-Cler |
| **CL** | Clinic (medical office / clinic location) | Differentiates from hospital |
| **AH-*** | Advent Health + short site name | e.g. AH-Cler (Clermont), AH-Alt (Altamonte) |
| **CL-*** | Clinic + short name | e.g. CL-Cler, CL-Apk |

Abbreviations are generated from location name (strip "Advent Health", "Hospital", "Clinic"; take first word or 3–4 chars). See `_location_abbrev()` in `app/routers/api.py`.

---

## Cell display order (top → bottom)

1. **OFF** — Days off (initials only, e.g. "JF CJ SO")
2. **NC** — No call / unavailable
3. **Call group** — Group abbrev + initials (e.g. "WG: JF")
4. **CL/AH** — Clinic/hospital (initials + location, e.g. "JF CL-Cler")
5. **MTG** — Meetings
6. **Sx** — Surgeries
7. **pts** — Patient counts

---

## Font sizing

- **Days off / call / clinic** — Slightly larger (emphasized) so initials and abbrevs are readable.
- **Meetings / surgery / pts** — Standard or slightly smaller to fit more lines.

Controlled via CSS classes on the compact event pills (e.g. `.fc-event--dayoff`, `.fc-event--clinic`).
