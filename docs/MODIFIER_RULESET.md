# Modifier Ruleset (product + engineering)

Source of truth for how CPT modifiers and multi-procedure reduction affect wRVU / payment in RVU Insight.

Cursor rule: [`../../.cursor/rules/rvu-modifier-rules.mdc`](../../.cursor/rules/rvu-modifier-rules.mdc)

## Goal

After OCR (and on every recalculate):

1. Sort primary CPT lines **highest work RVU first**
2. Apply the modifier factors below
3. Apply multi-procedure reduction to 2nd+ primary lines

## Product rules (approved intent)

| Modifier | Meaning | App math |
|----------|---------|----------|
| **50** | Bilateral procedures | wRVU (and payment components) **× 1.5** |
| **51** | Multiple procedures | Label only at line level (**× 1.0**). Encounter rule: highest × 1, **2nd+ × 0.5** |
| **52** | Reduced procedure | **× 0.5** |
| **22** | Increased services | Varies in real billing — **no automatic RVU change** (× 1.0) |
| **53** | Discontinued procedure | **× 0.5** |
| **80** | Surgeon assist | **× 0.2** |

## Critical bug (fixed)

Mobile "Add modifier" / library PATCH used to save **`factor: 1`** with description **"Mobile-added modifier"**. That overwrote DB rules for known codes (50, 80, …), so preview/edit showed **full** wRVUs. Backend now ignores/repairs those poisoned overrides; mobile sends the known default factor.

Related existing codes (keep unless product says otherwise):

| Modifier | Current default | Notes |
|----------|-----------------|-------|
| **AS** | × 0.2 | PA/NP assist |
| **81** | × 0.10 | Minimum assistant |
| **82** | × 0.16 | Assistant, no resident |
| **62** | × 0.625 | Co-surgeons |
| **78** | × 0.70 | Unplanned return to OR |

## Pipeline (intended)

```text
OCR / edit lines
    → canonicalize providers
    → calc base RVU per line (fee schedule × CF × units)
    → apply per-line modifier_factor (50, 52, 53, 80, AS, …)
    → sort primary (non-assist) lines by work_rvu DESC
    → apply multiple_procedure_factor: rank1=1.0, rank2+=0.5
    → return ordered line_items + totals
```

## Current code vs intent (gaps)

| Area | Today | Needed |
|------|-------|--------|
| Sort for display | MPPR ranks by work RVU but **does not reorder** returned lines | Reorder primary lines highest work RVU first after OCR/recalc |
| `-51` factor | `1.00` in `DEFAULT_MODIFIER_FACTORS` | Keep `1.00` (encounter handles reduction) |
| Auto 0.5 on 2nd+ | Already in `build_rows` / `build_rows_from_lines` | Keep; document as 51 semantics |
| `-80` factor | Was **0.16**, mobile often overwrote to **1.0** | Product **0.20**; repair poisoned overrides |
| `-22` | 1.00 | Already matches (no change) |
| `-50` / `-52` / `-53` | 1.5 / 0.5 / 0.5 | Already matches |
| Mobile fallbacks | iOS/Android hardcode factors | Sync when `-80` changes |

## Open decisions (confirm before coding)

1. **`-80` = 0.20 or keep CMS-style 0.16?** (AS stays 0.20 either way.)
2. **3rd+ procedures:** also × 0.5 (recommended), or only the 2nd line?
3. **When user manually reorders lines:** ignore manual order and always re-sort by work RVU on save?
4. **Same work RVU tie-break:** CPT ascending? OCR original order?

## Implementation plan (when approved)

1. **Backend defaults** — `app/rvu/lookup.py` `DEFAULT_MODIFIER_FACTORS` (especially `80` if approved).
2. **Sort output** — after MPPR in `rvu_payment_service`, return primary rows sorted by work RVU desc; keep assist rows after (or grouped with parent CPT).
3. **OCR persist path** — ensure `_persist_capture_result` / enrich stores lines in that sorted order.
4. **Portal seed** — if DB `rvu_modifier_rules` overrides `80` to 0.16, patch/migrate effective rule to 0.2.
5. **Tests** — extend `tests/test_rvu_calculations.py`: sort order, 50/51/52/53/22/80, stacking, assist excluded from MPPR.
6. **Mobile fallbacks** — Swift `CPTModifier` + Compose `RvuModifier` factors match backend.
7. **Deploy API** — math is server-side; mobile release only needed for fallback picker factors / any UI copy.

## Non-goals

- Automatic uplift for `-22` (always manual / no change).
- Mobile-only math that diverges from API.
- Applying MPPR to assist/`AS` lines.
