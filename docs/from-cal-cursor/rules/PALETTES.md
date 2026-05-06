# Design Palette Library
# Don Naile — App Suite
# Last updated: March 2026

> This file is the **single source of truth** for all color palettes, typography,
> and component tokens across every app in the suite.
>
> Reference this file from any project's `CLAUDE.md` like this:
> ```
> Design tokens: see .cursor/rules/PALETTES.md
> Active palette for this app: Clinical Trust
> ```
>
> **Cal project:** Session checklist in CLAUDE.md says "Read .cursor/rules/PALETTES.md before any UI work". Cal uses **Clinical Trust**. Never hardcode hex values — always use token names from this file.
>
> To switch palettes: change the `Active palette` line in the project's CLAUDE.md only.

---

## Typography (Universal — All Apps)

| Role | Font | Weight | Notes |
|------|------|--------|-------|
| **Display / Hero** | `-apple-system, 'SF Pro Display'` → fallback `'DM Serif Display'` | 700–800 | Large headings, SNAP! button, confirmation titles |
| **UI / Body** | `-apple-system, 'SF Pro Text'` → fallback `'DM Sans'` | 300–600 | All body copy, labels, inputs, table data |
| **Monospace / IDs** | `'SF Mono'` → fallback `'DM Mono'` | 400–500 | Reference numbers, codes, data values |
| **Web fallback stack** | `'DM Serif Display', 'DM Sans', 'DM Mono'` | — | Google Fonts, free, load via CDN |

### Font Scale (Mobile — SF Pro sizing)

| Token | Size | Weight | Usage |
|-------|------|--------|-------|
| `--fs-hero` | 30px | 700 | Screen titles, confirmation |
| `--fs-title` | 22px | 700 | Section headings |
| `--fs-body-lg` | 17px | 400 | Primary list labels, button text |
| `--fs-body` | 15px | 400 | Body copy, subtitles |
| `--fs-label` | 13px | 500 | Secondary labels, metadata |
| `--fs-caption` | 12px | 400–600 | Badges, chips, timestamps |
| `--fs-micro` | 11px | 600 | ALL CAPS section headers, tab labels |
| `--fs-snap` | 30px | 800 | SNAP! button only |

### Font Scale (Portal — Desktop)

| Token | Size | Weight | Usage |
|-------|------|--------|-------|
| `--fs-page-title` | 20px | 700 | Page headings |
| `--fs-section` | 15px | 600 | Section titles, sidebar items |
| `--fs-table-head` | 11px | 700 | ALL CAPS table headers |
| `--fs-table-body` | 14px | 400–500 | Table rows |
| `--fs-kpi` | 26px | 700 | KPI numbers (tabular-nums) |
| `--fs-badge` | 12px | 500 | Status badges |
| `--fs-mono` | 12px | 500 | Reference numbers, IDs |

---

## Palette 1 — Clinical Trust

**Character:** Medical authority. Epic, Mayo Clinic, mass trust. Deep navy + royal blue.
**Use for:** SSS (active), Cal Scheduler (active)
**Status:** ✅ ACTIVE — SSS mobile + portal

### Light Mode

```css
/* ── BACKGROUNDS ── */
--bg:              #F4F6F9;   /* Page / app background */
--bg-elevated:     #FFFFFF;   /* Cards, surfaces, modals */
--bg-grouped:      #F4F6F9;   /* Grouped list background */
--bg-sidebar:      #F8FAFC;   /* Portal sidebar */

/* ── GRADIENTS (Mobile) ── */
--grad-screen:
  radial-gradient(ellipse 140% 70% at 50% -20%, rgba(0,90,200,.45) 0%, rgba(0,150,220,.15) 40%, transparent 70%),
  radial-gradient(ellipse 100% 60% at 90% 110%, rgba(0,100,180,.30) 0%, transparent 55%),
  radial-gradient(ellipse  80% 50% at -10% 80%, rgba(100,180,255,.20) 0%, transparent 55%),
  linear-gradient(175deg, #cfe0f5 0%, #ddeaf8 30%, #e8f2fc 55%, #f2f8ff 80%, #eaf3ff 100%);

--wave-1:          rgba(255,255,255,.52);
--wave-2:          rgba(210,230,255,.42);
--wave-3:          rgba(180,215,255,.28);

/* ── TEXT ── */
--text:            #14305A;   /* Primary label */
--text-2:          #4A6080;   /* Secondary label */
--text-3:          #7A90A8;   /* Tertiary / placeholder */
--text-4:          rgba(20,48,90,.18); /* Disabled */

/* ── ACCENT / BRAND ── */
--accent:          #0066CC;   /* Primary CTA, links, active states */
--accent-light:    #E8F0FC;   /* Accent tinted background */
--accent-text:     #FFFFFF;   /* Text on accent */

/* ── SEMANTIC ── */
--success:         #28A745;
--success-light:   rgba(40,167,69,.12);
--warning:         #FF9500;
--warning-light:   rgba(255,149,0,.12);
--danger:          #DC3545;
--danger-light:    rgba(220,53,69,.10);
--info:            #00A3E0;
--info-light:      rgba(0,163,224,.10);

/* ── SURFACES ── */
--sep:             rgba(20,48,90,.14);   /* Separators / dividers */
--sep-opaque:      #D1DCE8;
--fill:            rgba(20,48,90,.07);
--fill-2:          rgba(20,48,90,.05);

/* ── GLASS (Mobile) ── */
--glass-bg:        rgba(255,255,255,.38);
--glass-border:    rgba(255,255,255,.52);
--glass-blur:      blur(22px) saturate(1.8);

/* ── SNAP BUTTON ── */
--snap-grad:       radial-gradient(circle at 38% 32%, #4a96e8, #0048b0);
--snap-shadow:     0 10px 36px rgba(0,70,160,.55), inset 0 -3px 10px rgba(0,0,50,.25);
--snap-ring:       rgba(255,255,255,.38);
--snap-ring-shadow:0 10px 40px rgba(0,80,180,.22), inset 0 1px 0 rgba(255,255,255,.80);

/* ── BUTTONS (Portal) ── */
--btn-primary-bg:      linear-gradient(155deg, #1a7cf8, #0044c0);
--btn-primary-shadow:  0 6px 22px rgba(0,70,200,.40);
--btn-primary-text:    #FFFFFF;
--btn-secondary-bg:    #E8F0FC;
--btn-secondary-text:  #0050AA;

/* ── SURGEON COLORS (Cal — fixed, never change) ── */
--surgeon-0: #EF4444;   /* Florin    — Red    */
--surgeon-1: #F59E0B;   /* Boardman  — Amber  */
--surgeon-2: #10B981;   /* Woodley   — Green  */
--surgeon-3: #8B5CF6;   /* Schroeder — Violet */
--surgeon-4: #EC4899;   /* Froehling — Pink   */
--surgeon-5: #14B8A6;   /* Nelson    — Teal   */
--surgeon-6: #3B82F6;   /* Kieran    — Blue   */
--surgeon-7: #F97316;   /* Yurcisin  — Orange */
--surgeon-8: #6366F1;   /* Putnick   — Indigo */
--surgeon-9: #84CC16;   /* Johnson   — Lime   */
```

### Dark Mode

```css
/* ── BACKGROUNDS ── */
--bg:              #0D1117;
--bg-elevated:     #161B22;
--bg-grouped:      #0D1117;
--bg-sidebar:      #0D1117;

/* ── GRADIENTS (Mobile) ── */
--grad-screen:
  radial-gradient(ellipse 140% 70% at 50% -20%, rgba(56,139,253,.35) 0%, rgba(30,90,180,.15) 40%, transparent 70%),
  radial-gradient(ellipse 100% 60% at 90% 110%, rgba(20,70,160,.30) 0%, transparent 55%),
  radial-gradient(ellipse  80% 50% at -10% 80%, rgba(56,100,200,.20) 0%, transparent 55%),
  linear-gradient(175deg, #050c1a 0%, #080f20 30%, #0a1428 55%, #0d1830 80%, #080f20 100%);

--wave-1:          rgba(56,139,253,.16);
--wave-2:          rgba(30,80,180,.12);
--wave-3:          rgba(10,50,130,.09);

/* ── TEXT ── */
--text:            #C8DEFF;
--text-2:          #8B949E;
--text-3:          #6A7888;
--text-4:          rgba(200,222,255,.18);

/* ── ACCENT ── */
--accent:          #388BFD;
--accent-light:    rgba(56,139,253,.16);
--accent-text:     #FFFFFF;

/* ── SEMANTIC ── */
--success:         #3FD068;
--success-light:   rgba(63,208,104,.14);
--warning:         #FF9F0A;
--warning-light:   rgba(255,159,10,.14);
--danger:          #FF453A;
--danger-light:    rgba(255,69,58,.12);
--info:            #5AC8FA;
--info-light:      rgba(90,200,250,.12);

/* ── SURFACES ── */
--sep:             #21262D;
--sep-opaque:      #21262D;
--fill:            rgba(200,222,255,.07);
--fill-2:          rgba(200,222,255,.05);

/* ── GLASS ── */
--glass-bg:        rgba(56,139,253,.10);
--glass-border:    rgba(56,139,253,.28);
--glass-blur:      blur(22px) saturate(1.8);

/* ── SNAP BUTTON ── */
--snap-grad:       radial-gradient(circle at 38% 32%, #5aa0ff, #1550d0);
--snap-shadow:     0 10px 40px rgba(56,139,253,.55), inset 0 -3px 10px rgba(0,0,60,.35);
--snap-ring:       rgba(56,139,253,.18);
--snap-ring-shadow:0 10px 40px rgba(56,139,253,.35), inset 0 1px 0 rgba(255,255,255,.08);

/* ── BUTTONS ── */
--btn-primary-bg:      linear-gradient(155deg, #3380ff, #1244c8);
--btn-primary-shadow:  0 6px 22px rgba(56,139,253,.40);
--btn-primary-text:    #FFFFFF;
--btn-secondary-bg:    rgba(56,139,253,.12);
--btn-secondary-text:  #7DB8FF;
```

---

## Palette 2 — Teal & Heal

**Character:** Modern telehealth. Fresh, calm, forward-thinking. Cyan + teal + sage.
**Use for:** Future apps — patient-facing wellness, telehealth, onboarding flows
**Status:** 🟡 RESERVED — available for next app

### Light Mode
```css
--bg:              #F0FDFA;
--bg-elevated:     #FFFFFF;
--text:            #0A2E38;
--text-2:          #2D6070;
--accent:          #0891B2;
--accent-light:    #CFFAFE;
--accent-text:     #FFFFFF;
--success:         #10B981;
--warning:         #F59E0B;
--danger:          #EF4444;
--sep:             #CCFBF1;
--glass-bg:        rgba(255,255,255,.42);
--glass-border:    rgba(255,255,255,.55);
--snap-grad:       radial-gradient(circle at 38% 32%, #16b8d8, #056878);
--snap-shadow:     0 10px 36px rgba(8,145,178,.60), inset 0 -3px 10px rgba(0,30,40,.25);
--btn-primary-bg:  linear-gradient(155deg, #0ab0cc, #056070);
--grad-screen:
  radial-gradient(ellipse 140% 70% at 50% -20%, rgba(8,145,178,.40) 0%, rgba(6,182,212,.15) 40%, transparent 70%),
  radial-gradient(ellipse 100% 60% at 90% 110%, rgba(16,185,129,.25) 0%, transparent 55%),
  linear-gradient(175deg, #c8f0f5 0%, #d8f8f8 30%, #e4faf8 55%, #f0fefb 100%);
--wave-1:          rgba(255,255,255,.52);
--wave-2:          rgba(180,245,240,.44);
--wave-3:          rgba(140,230,225,.30);
```

### Dark Mode
```css
--bg:              #020E12;
--bg-elevated:     #041520;
--text:            #A8F0F8;
--text-2:          #67E8F9;
--accent:          #22D3EE;
--accent-light:    rgba(34,211,238,.14);
--accent-text:     #020E12;
--sep:             #0F3040;
--glass-bg:        rgba(34,211,238,.08);
--glass-border:    rgba(34,211,238,.25);
--snap-grad:       radial-gradient(circle at 38% 32%, #18d0e8, #046880);
--snap-shadow:     0 10px 40px rgba(34,211,238,.50), inset 0 -3px 10px rgba(0,20,30,.40);
--btn-primary-bg:  linear-gradient(155deg, #0cc8e0, #055c70);
--grad-screen:
  radial-gradient(ellipse 140% 70% at 50% -20%, rgba(34,211,238,.28) 0%, rgba(8,145,178,.12) 40%, transparent 70%),
  linear-gradient(175deg, #020e12 0%, #031520 30%, #041a24 55%, #051e28 100%);
--wave-1:          rgba(34,211,238,.14);
--wave-2:          rgba(16,185,129,.10);
--wave-3:          rgba(8,145,178,.08);
```

---

## Palette 3 — Midnight Precise

**Character:** Dark-first surgical precision. Premium, focused, screen-optimized.
**Use for:** Northstar trading bot, any data-dense or power-user app
**Status:** 🟡 RESERVED — next use: Northstar Trading UI

### Light Mode
```css
--bg:              #EFF6FF;
--bg-elevated:     #FFFFFF;
--text:            #1A3060;
--text-2:          #4B6584;
--accent:          #2563EB;
--accent-light:    #DBEAFE;
--accent-text:     #FFFFFF;
--success:         #10B981;
--warning:         #F59E0B;
--danger:          #EF4444;
--sep:             #BFDBFE;
--glass-bg:        rgba(255,255,255,.42);
--glass-border:    rgba(255,255,255,.55);
--snap-grad:       radial-gradient(circle at 38% 32%, #4d80f5, #1030c0);
--snap-shadow:     0 10px 36px rgba(37,99,235,.55), inset 0 -3px 10px rgba(0,0,50,.28);
--btn-primary-bg:  linear-gradient(155deg, #2868f8, #1030c8);
--grad-screen:
  radial-gradient(ellipse 140% 70% at 50% -20%, rgba(37,99,235,.40) 0%, rgba(99,102,241,.18) 40%, transparent 70%),
  radial-gradient(ellipse 100% 60% at 90% 110%, rgba(79,70,229,.28) 0%, transparent 55%),
  linear-gradient(175deg, #d0dcf8 0%, #dce5fb 30%, #e6edfc 55%, #f0f5ff 100%);
--wave-1:          rgba(255,255,255,.52);
--wave-2:          rgba(205,218,255,.44);
--wave-3:          rgba(175,198,255,.30);
```

### Dark Mode
```css
--bg:              #040610;
--bg-elevated:     #070A18;
--text:            #C0D4F8;
--text-2:          #64748B;
--accent:          #3B82F6;
--accent-light:    rgba(59,130,246,.16);
--accent-text:     #FFFFFF;
--success:         #34D399;
--warning:         #FBBF24;
--danger:          #F472B6;
--sep:             #1A2740;
--glass-bg:        rgba(59,130,246,.10);
--glass-border:    rgba(59,130,246,.25);
--snap-grad:       radial-gradient(circle at 38% 32%, #5090ff, #1240d0);
--snap-shadow:     0 10px 40px rgba(59,130,246,.55), inset 0 -3px 10px rgba(0,0,50,.40);
--btn-primary-bg:  linear-gradient(155deg, #3572ff, #1040d0);
--grad-screen:
  radial-gradient(ellipse 140% 70% at 50% -20%, rgba(59,130,246,.30) 0%, rgba(99,102,241,.15) 40%, transparent 70%),
  linear-gradient(175deg, #040610 0%, #070a18 30%, #090c1e 55%, #0b1025 100%);
--wave-1:          rgba(59,130,246,.15);
--wave-2:          rgba(99,102,241,.11);
--wave-3:          rgba(37,99,235,.08);
```

---

## Component Tokens (Universal)

### Radius
```css
--radius-sm:   8px;    /* Row icons, small chips */
--radius-md:   12px;   /* Cards, inputs */
--radius-lg:   16px;   /* Large cards, modals */
--radius-xl:   20px;   /* Portal frame, calendar */
--radius-full: 9999px; /* Pills, badges, home bar */
```

### Spacing Scale
```css
--space-1:  4px;
--space-2:  8px;
--space-3: 12px;
--space-4: 16px;
--space-5: 20px;
--space-6: 24px;
--space-8: 32px;
```

### Shadows
```css
/* Light */
--shadow-card:   0 2px 8px rgba(0,0,0,.06), 0 0 1px rgba(0,0,0,.04);
--shadow-float:  0 8px 32px rgba(0,0,0,.12), 0 2px 8px rgba(0,0,0,.06);
/* Dark */
--shadow-card-dark:  0 2px 12px rgba(0,0,0,.50);
--shadow-float-dark: 0 8px 40px rgba(0,0,0,.70);
```

### Animation
```css
--ease-spring: cubic-bezier(.34, 1.56, .64, 1);  /* Buttons, popovers */
--ease-smooth: cubic-bezier(.45, 0, .55, 1);      /* Waves, transitions */
--dur-fast:    150ms;
--dur-base:    250ms;
--dur-slow:    400ms;
--wave-1-dur:  7s;    /* Foreground wave */
--wave-2-dur:  10s;   /* Mid wave */
--wave-3-dur:  14s;   /* Background wave */
```

---

## Mobile-Specific Rules (SSS + any future mobile app)

- **NO word "referral"** on any mobile UI surface
- **NO practice branding** on mobile home screen — universal tool only
- **SNAP! button** — primary CTA always uses this word
- **"Patient Medical Management"** — app category positioning
- **"Reference #"** — never "Ref #", never just "REF"
- Background: full gradient mesh (`--grad-screen`) + animated SVG wave morph (3 layers)
- Glass surfaces: `backdrop-filter: blur(22px) saturate(1.8)` + `--glass-border`
- Tab bar: frosted glass, not native tab bar

## Portal-Specific Rules (SSS portal + Cal admin)

- Sidebar navigation, never hamburger
- KPI strip at top of every list view
- Filter chips above data tables — never dropdowns for primary filters
- Table-first layout for list data — never cards on desktop
- Surgeon color dots must match `--surgeon-N` tokens exactly — consistent across portal + cal

---

## How to Reference This File

In any project's `CLAUDE.md`, add:

```markdown
## Design Tokens
- Source: `PALETTES.md` (in project root or shared docs dir)
- Active palette: **Clinical Trust**
- Mode: respects `prefers-color-scheme` — implement both light + dark
- Font CDN: https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=DM+Sans:wght@300;400;500;600;700&family=DM+Mono
- See PALETTES.md for full token reference before writing any CSS or styling code
```

## Palette Assignment Map

| App | Palette | Status |
|-----|---------|--------|
| SSS Mobile (`app.snapsendseen.com`) | Clinical Trust | ✅ Active |
| SSS Portal (`portal.snapsendseen.com`) | Clinical Trust | ✅ Active |
| Cal Scheduler (`cal.midfloridasurgical.com`) | Clinical Trust | ✅ Active |
| Northstar Trading Bot | Midnight Precise | 🟡 Planned |
| Naile Outdoor Services | TBD | ⬜ Not started |
| Future patient wellness app | Teal & Heal | 🟡 Reserved |
