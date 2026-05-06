# Scheduling Rules Engine — Spec & Persona
**Status:** Implemented. Config in Admin → Settings → Scheduling rules (first card).  
**Author (persona):** Valerie Reyes, Master Scheduler

**Implementation:** `app/rules_engine/` (registry, checkers, engine); DB table `scheduling_rule_config`. Entry point: `conflicts.check_conflicts()`. See `docs/APP_REFERENCE.md` for routes and where rules run.

---

## The Persona: Valerie Reyes

**Valerie Reyes** is the **Master Scheduler** for a 40-provider surgical group. She’s been building and running block schedules, clinic grids, and OR calendars for 15 years. She thinks in rules: minimum turn times, clinic-to-OR buffers, location-specific blocks, and “what happens when we move one thing.” She’s the voice we use to design the rules engine so it matches how a real scheduler works.

**Valerie’s critique (in her words):**

> Right now your app tells me “you have a conflict” but it doesn’t tell me *why* in a way I can fix, and it doesn’t know the rules I actually use. I need:
> - **Time rules:** How much gap between clinic and surgery? Between two cases in the same OR? Can someone do clinic AM and surgery PM at the same *site*?
> - **Location rules:** If I’m adding a case at Altamonte, the system should assume Altamonte and not ask me to pick again. And I need to know when a surgeon is at another site so we don’t double-book.
> - **Conflict clearing:** When I fix the conflict — move the case or change the day off — the warning should go away because the system **re-checks** the rules, not because I clicked somewhere else.
>
> So we need a **rules engine**: a set of named, configurable rules that run when we save or load a schedule. Each rule can say “this is allowed” or “this is a conflict,” and we get a clear list of conflicts that we can resolve and then re-run to confirm they’re cleared.

Below is the rules engine spec that Valerie (this persona) proposes. **Review it, add rules, change numbers or rule names, and only then should we implement.**

---

## 1. Design Principles (No Code Yet)

1. **Rules are first-class.** Each rule has a name, a type, and configurable parameters (e.g. minutes). We can turn rules on/off and tune them without rewriting app logic.
2. **Conflicts are structured.** A conflict is not just a string; it has type, who, when, what’s overlapping, and (optionally) how to fix it. That way the UI can show “Conflict: …” and “Re-check” to clear when fixed.
3. **Re-run on demand.** After any change (add/edit/delete case, day off, clinic, etc.), we run the engine again for the affected surgeon/date and refresh the conflict list. “Conflict clearing” = re-run and show only current conflicts.
4. **Persona-driven defaults.** Default rule values (e.g. 30 min between clinic and surgery) are what a master scheduler would expect; admins can override later.

---

## 2. Rule Categories

These are the **categories** of rules. Under each we’ll list specific rules you can add or change.

### 2.1 Same-day overlap (hard conflicts)

**What:** One person cannot be in two places at the same time.

| Rule ID | Name | Description | Config |
|--------|------|--------------|--------|
| `OVERLAP_DAY_OFF` | Day off overlap | Approved day off vs any other commitment that day | — |
| `OVERLAP_CALL` | Call overlap | On-call assignment vs clinic/surgery/day off that day | — |
| `OVERLAP_CLINIC` | Clinic overlap | Two clinic blocks (or clinic + surgery) at overlapping times | — |
| `OVERLAP_SURGERY` | Surgery overlap | Two surgical cases (same surgeon) at overlapping times | — |
| `OVERLAP_UNAVAILABLE` | Unavailable overlap | Marked unavailable vs any scheduled commitment | — |
| `OVERLAP_MEETING` | Meeting overlap | Meeting vs clinic/surgery at same time | — |

**Valerie:** “These are the ones you already kind of have. The difference is: each one is a *rule*. When we add a new commitment type later, we add a new overlap rule instead of hacking a big function.”

---

### 2.2 Timing / buffer rules (soft or configurable)

**What:** Minimum time between certain types of events. Violations can be “warning” or “block” depending on practice policy.

| Rule ID | Name | Description | Default | Config |
|--------|------|-------------|---------|--------|
| `BUFFER_CLINIC_TO_SURGERY` | Clinic → surgery buffer | Minimum minutes between end of clinic (AM or PM) and start of first surgery that day | 30 min | `minutes` (per location group?) |
| `BUFFER_SURGERY_TO_CLINIC` | Surgery → clinic buffer | Minimum minutes between end of last surgery and start of clinic | 30 min | `minutes` |
| `BUFFER_BETWEEN_CASES` | Turn time between cases | Minimum minutes between end of one surgical case and start of next (same surgeon, same location) | 15 min | `minutes` (maybe per location) |
| `BUFFER_SAME_SITE_AM_PM` | Same-site AM/PM | If clinic AM and surgery PM same site, minimum gap | 30 min | `minutes` |
| `MAX_CLINIC_AND_SURGERY_SAME_DAY` | Same-day clinic + surgery | Allow same day? If yes, enforce buffers above. If no, treat as hard conflict | Allow with buffers | `allow_same_day` (bool), then buffers |

**Valerie:** “I need to set these per practice. Some groups want 45 minutes between clinic and OR; some want 15. And we might want different turn times per hospital.”

---

### 2.3 Location and context rules

**What:** Rules that depend on *where* something is scheduled.

| Rule ID | Name | Description | Config |
|--------|------|--------------|--------|
| `LOCATION_DEFAULT_FROM_CONTEXT` | Default location from context | When adding a case from a hospital pill (e.g. Altamonte), default location = that hospital; no “Select location” required | Already UI; can be enforced by rule “suggested_location_id” |
| `LOCATION_CLINIC_VS_OR` | Clinic vs OR at same site | If surgeon has clinic at site A, can they have surgery at site A same day? | Allow / disallow / allow with buffer (reference buffer rules) |
| `LOCATION_DRIVE_TIME` | Drive time between sites | If surgeon has clinic at site A and surgery at site B same day, minimum gap = drive time (minutes) | `minutes_between_sites` (matrix or default) |

**Valerie:** “Drive time is a stretch for v1, but I want the *slot* for it. We can put in a default 60 minutes between sites and refine later.”

---

### 2.4 Conflict resolution and clearing

**What:** How we know a conflict is “fixed” and when to re-run.

| Concept | Description |
|---------|-------------|
| **Conflict record** | One conflict = one structured object: e.g. `{ rule_id, surgeon_id, date, message, conflicting_entity_type, conflicting_entity_id, severity }`. So the UI can say “Conflict with Surgery #42” and we know what to re-check. |
| **Re-run trigger** | After save (add/edit/delete) of any commitment, run the engine for that surgeon + date (and optionally adjacent dates). Return the new conflict list. |
| **Clearing** | “Conflict cleared” = re-run returned no conflicts for that surgeon/date. The banner or list updates from the new result; we do *not* rely on URL params or “last redirect” to decide what to show. |
| **Severity** | Optional: `block` (cannot save), `warning` (can save but show warning). For now we can treat all as warning and let practice decide later which rules block. |

**Valerie:** “If I change the case time and the conflict goes away, I need the app to *tell* me it’s gone. That means run the rules again and show me the new list.”

---

## 3. Rule Engine Shape (Design Only)

How we’ll structure this when we code (for you to agree or change):

1. **Rule registry**  
   A list of rule definitions: id, name, category, config schema (e.g. `minutes: int`), and a function or class that takes (surgeon_id, date, db, config) and returns zero or more **conflict objects**.

2. **Conflict object**  
   - `rule_id`, `surgeon_id`, `date`, `message` (human-readable), `severity`  
   - Optional: `conflicting_entity_type` (“surgical_case”, “day_off”, “clinic_schedule”, …), `conflicting_entity_id`  
   - So we can say “this conflict was about case #7” and when #7 is moved, we re-run and that conflict disappears.

3. **Engine entry point**  
   - `evaluate(surgeon_id, start_date, end_date, db, exclude_entity=None) → list[Conflict]`  
   - Optionally: `evaluate_for_commitment(commitment_type, commitment_id, db) → list[Conflict]` that figures out surgeon/date from the commitment and runs the engine.

4. **Where it’s called**  
   - On **save** (day off, clinic, surgical case, meeting, call, etc.): run engine for that surgeon/date; return conflicts to attach to redirect or response.  
   - On **load** (e.g. clinic schedule page, day-off list): optionally run engine for the visible surgeon/date range and show current conflicts so “clearing” is just “reload and see empty list.”

5. **Config storage**  
   - Rule parameters (e.g. 30 min buffer) live in **site_settings** or a small `scheduling_rules_config` table: rule_id → JSON config. So we can change “30” to “45” without code.

---

## 4. What You Can Add or Change Before Any Code

Use this section to edit the spec.

### 4.1 Add a rule

Copy this and fill in:

```text
| Rule ID | Name | Description | Default | Config |
|---------|------|--------------|---------|--------|
| YOUR_ID | Your rule name | What it checks | Default value | Parameters (e.g. minutes) |
```

### 4.2 Change a default

- List the rule ID and the new default (e.g. `BUFFER_CLINIC_TO_SURGERY` → 45 minutes).

### 4.3 Add a category

- Category name and 2–3 rules under it (same table format as in section 2).

### 4.4 Conflict clearing behavior

- Do you want conflicts re-run on **every page load** for the visible week, or only after **save** and then show the result on the next screen?
- Should any rules **block** save (hard stop) vs only **warn**?

### 4.5 Persona tweaks

- Change “Valerie Reyes” to a different name/role if you want.
- Add or remove “Valerie says” notes to reflect how your master scheduler would describe the rules.

---

## 5. Summary Checklist (Review Before Code)

- [ ] Persona name and role agreed (or replaced).
- [ ] Overlap rules (section 2.1) — add/remove; no code yet.
- [ ] Buffer/timing rules (section 2.2) — defaults and which ones are “block” vs “warn.”
- [ ] Location rules (section 2.3) — which to implement first (e.g. default from context only).
- [ ] Conflict object shape and re-run triggers agreed (section 2.4 and 3).
- [ ] Config storage: site_settings vs dedicated table (section 3).
- [ ] Any new categories or rules you added in section 4.

Once this spec is stable, the next step is to implement the engine (rule registry, conflict type, evaluate entry point) and then wire it into save/load and conflict clearing — without changing this doc until you’re ready to version the rules.
