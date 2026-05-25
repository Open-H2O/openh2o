# OpenH2O UX Critique Report

**Target:** openh2o.com (deployed via Cloudflare Tunnel on Butler)
**Date:** 2026-05-25
**Assessments:** LLM Design Review (Assessment A) + Automated Detection (Assessment B)

---

## Design Health Score (Nielsen's 10 Heuristics)

| # | Heuristic | Score | Key Issue |
|---|-----------|:-----:|-----------|
| 1 | Visibility of System Status | 3 | Loading bar fires on HTMX requests, toasts confirm actions. Missing: no skeleton/spinner for HTMX partial swaps. |
| 2 | Match System / Real World | 4 | Excellent domain language: "parcel," "acre-feet," "water right," "ledger entry," "recharge site." |
| 3 | User Control and Freedom | 3 | Breadcrumbs, back links, cancel on forms. Missing: no undo for inline edits, no delete confirmation visible. |
| 4 | Consistency and Standards | 3 | Consistent card/table/form patterns. Deduction: login page uses raw Tailwind utilities instead of app.css classes; status badges use inline styles instead of badge classes. |
| 5 | Error Prevention | 2 | Inline validation present. Missing: no destructive action confirmation, no input constraints on numeric fields, inline edit has no cancel affordance. |
| 6 | Recognition Rather Than Recall | 3 | Filters use dropdowns, status badges use color coding, breadcrumbs show path. Missing: no tooltips on domain fields. |
| 7 | Flexibility and Efficiency | 2 | HTMX search with debounce, CSV upload for bulk entry. Missing: no keyboard shortcuts, no bulk select, no export, no jump-to-page. |
| 8 | Aesthetic and Minimalist Design | 4 | Clean visual hierarchy. Three-tier text color creates scanning order. Semantic color for supply/usage/deficit. Nothing superfluous. |
| 9 | Error Recovery | 2 | Login error shown with styled box, field errors inline. Missing: errors not actionable, no HTMX failure recovery visible. |
| 10 | Help and Documentation | 1 | Onboarding stepper on empty dashboard. Sign convention hint on ledger. Beyond that: no tooltips, no field descriptions, no "what is this?" links. |
| **Total** | | **27/40** | **Acceptable** |

**Rating:** Acceptable (20-27 range). Significant improvements needed in error prevention, efficiency, and help/documentation before users are happy.

---

## Anti-Patterns Verdict

### AI Slop: PASS (Low Risk)

This does NOT read as AI-generated. Key reasons:

- **Color palette is domain-grounded.** California Gold (#E4A317) is state identity, Pacific Blue (#1B7FAF) maps to water. OKLCH ramps are semantically tied to domain concepts (furnace-orange for usage, forest-teal for supply).
- **No gradient text, no glassmorphism, no hero-metric templates.** Dashboard stat cards are functional with domain units (acre-feet), not vanity metrics.
- **No identical card grids.** Different layouts for dashboard, detail, list, and map pages. The index.html 6-card grid is the closest to a template pattern, but content is domain-specific.
- **No side-stripe borders** (toast left-borders are the established success/error pattern).
- **Typography is purposeful.** Public Sans (USWDS heritage) + JetBrains Mono (numeric data only).
- **Surface colors deliberately muted.** Base #040608 to card #080b10 is a 4-point jump, reading as "infrastructure tool" not "developer portfolio."

**One flag:** The 6-card entity-count dashboard is structurally close to a stats template, but justified by domain content.

### Automated Detection: 1 Finding (False Positive)

The `npx impeccable detect` scanner flagged `single-font` on base.html line 10. This is a false positive: both Public Sans (400/600/800) and JetBrains Mono (400) are loaded via Google Fonts on line 13. The detector read the comment line, not the actual link tag.

---

## Cognitive Load Assessment

| Check | Result | Notes |
|-------|:------:|-------|
| Single focus per page | PASS | Each page has one clear purpose. |
| Chunking (<=4 items/group) | PASS | Sidebar groups slightly exceed (Data: 6 items) but section dividers mitigate. |
| Grouping (related items together) | PASS | Detail pages group info, map, and related records logically. |
| Visual hierarchy | PASS | Three-tier text color system creates clear scanning. |
| One-thing-at-a-time | PASS | Forms are single-purpose. Lists show one entity type. |
| Minimal choices (<=4) | FAIL | Ledger filter bar: 6 simultaneous filter controls. |
| Working memory | PASS | Breadcrumbs maintain context. Detail pages show all relevant data. |
| Progressive disclosure | FAIL | Ledger filters all visible at once. 13 sidebar items without collapse. |

**Score: 2 failures = MODERATE.** The moderate rating is driven by the ledger page, the most complex view. Rest of the app maintains low cognitive load.

---

## What's Working

**1. Semantic color encoding for water accounting.** Supply, usage, surplus, and deficit each have distinct, meaningful colors. A district manager scanning the dashboard can immediately see which accounts are in trouble (red "Remaining" column) without reading numbers. This is the most important design decision and it is correct.

**2. The onboarding stepper on the empty dashboard.** When a new agency deploys with zero data, the dashboard shows a numbered sequence: (1) create a reporting period, (2) create accounts, (3) add ledger entries, (4) dashboard populates. This is exactly right for the target audience.

**3. The map page is a genuine spatial tool.** Layer toggles, measurement, coordinate display with copy-to-clipboard, basemap switching, legend, and popup detail with deep links to entity detail pages. This is a working GIS interface, not decoration.

---

## Priority Issues

### P1: Ledger filter bar overwhelms on tablet and mobile

**What:** The ledger_list.html toolbar-row contains 6 filter controls in a flex-wrap layout with inline min-width values (200px, 160px, 140px, 130px). On tablet (768-1023px), these wrap unpredictably into 2-3 rows. On mobile, each stacks vertically pushing data below the fold.

**Why it matters:** The ledger is the core workflow page for daily data entry. If filters eat the viewport on mobile/tablet, the primary content is invisible. Also fails the cognitive load "minimal choices" check.

**Fix:** Collapse date range and secondary filters behind an "Advanced Filters" toggle. Show only search + period by default (reduces from 6 to 2 visible controls).

### P1: Inline edit on detail pages has no cancel or undo

**What:** Parcel and well detail pages use an HTMX inline edit pattern (pencil icon triggers form swap). No visible Cancel button. No undo after save.

**Why it matters:** Government record-keeping where a wrong value has compliance implications. A mis-typed extraction rate could trigger a state violation notice.

**Fix:** Every inline edit swap must include Save + Cancel buttons. Cancel reverts via HTMX. Consider audit log link showing previous value.

### P2: Login page breaks the component system

**What:** login.html uses raw Tailwind utilities (w-full, mb-sm, text-xl, font-extrabold) instead of app.css component classes. It renders inside the sidebar+header shell (extends base.html), exposing unauthenticated users to an empty sidebar with navigation links they cannot use.

**Why it matters:** First thing a new user sees. Reads as "different product."

**Fix:** Create base_minimal.html (no sidebar) for auth pages. Refactor login template to use app.css form/button classes.

### P2: Status badges use duplicated inline styles instead of CSS classes

**What:** 9 template files contain the same inline badge styles (display: inline-flex; padding: 2px 10px; border-radius: 999px; background: rgba(34,197,94,0.15); color: #4ade80; ...) instead of using the badge-green/badge-orange/badge-red classes defined in app.css. Also contains 21 hard-coded hex colors in inline styles.

**Why it matters:** Maintenance burden (change requires editing 9 files), visual inconsistency (inline badges use 999px pill radius vs. CSS badge's --radius-sm), and 21 hex colors outside the token system.

**Fix:** Replace inline styles with existing badge classes. If pill shape is preferred, add a .badge-pill variant to app.css.

**Confirmed by automated detection:** 193 total inline styles across templates, 101 without CSS custom properties. This is the largest technical debt in the template layer.

### P2: 4 hard-coded colors outside the token system

**What:** app.css lines 720/729 use #ef4444 (red) and #eab308 (yellow). map-engine.css lines 125/153 use #78b8ff (blue) with no var() fallback.

**Why it matters:** Breaks token system consistency. If token values change, these 4 colors won't follow.

**Fix:** Add --color-error and --color-warning tokens. Replace map-engine.css hard-coded blue with a token.

### P3: No export capability on list/table views

**What:** Ledger list, parcel list, and dashboard tables have no CSV/PDF download.

**Why it matters:** The core use case is generating data for state reports. Users looking at filtered data have no way to extract it without going to a separate reporting page.

**Fix:** Add "Download CSV" button to ledger list toolbar and dashboard summary tables.

---

## Minor Observations

- The sidebar has 13 navigation items across 4 sections. For a user who primarily works in 3-4 areas, collapsible sections (Data expanded, Setup collapsed) would reduce scanning.
- No help/documentation system exists beyond 2 spots (onboarding stepper, sign convention hint). Phase 12 (In-App Documentation) will address this.
- Field edit form controls in wells/parcels (templates/wells/partials/_field_edit.html) duplicate inline styles that match the form-input class.
- Several inline styles like `style="color: var(--color-text-primary);"` could be utility classes to reduce template noise.

---

## Provocative Questions

1. **Should the landing page be a water budget summary instead of an entity counter?** A GSA manager doesn't log in to learn "I have 847 parcels." They log in to learn "Am I over-pumping?" The accounting dashboard already answers that question but is one click deeper.

2. **What happens when a user makes a mistake on a ledger entry?** No visible edit or delete path for existing entries. In double-entry accounting, corrections are typically reversing entries, not history edits. Which model does the platform use? The UI needs to guide whichever approach was chosen.

3. **Could the sidebar's 13 items be reduced by nesting?** Dashboard, Map, Ledger, Parcels, Wells, Water Rights, Recharge, Stations, Reports, Health, Accounts, Periods, Allocations. Would collapsible sections or role-based nav better match how users actually work?

---

*Assessment methods: LLM Design Review (independent sub-agent reading source templates/CSS, scoring heuristics), Automated Detection (npx impeccable detect --json --fast templates/), CSS hard-coded color grep, inline style audit.*
