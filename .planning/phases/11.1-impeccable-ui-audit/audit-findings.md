# OpenH2O Technical UI Audit Report

**Target:** openh2o.com (source at /Users/slate/GitHub/openh2o/)
**Date:** 2026-05-25
**Method:** Code-level audit of templates and CSS across 5 technical dimensions

---

## Audit Health Score

| # | Dimension | Score | Key Finding |
|---|-----------|:-----:|-------------|
| 1 | Accessibility | 2 | 45/47 labels lack `for=` binding. All 27 SVGs missing `aria-hidden`. No focus indicators on buttons/links. Tertiary text fails WCAG AA at 2.95:1. |
| 2 | Performance | 3 | No layout thrashing, no expensive animations. HTMX used efficiently with targeted swaps. Font loading uses `display=swap`. Minor: HTMX loaded from CDN without SRI hash. |
| 3 | Responsive Design | 3 | Two breakpoints (1023px, 767px) cover grids, sidebar, content. `table-scroll` prevents overflow. Minor: ledger 6-filter bar wraps awkwardly on tablet. |
| 4 | Theming | 2 | tokens.css well-structured. But 193 inline `style=` attributes, 18 with hardcoded hex colors. Status badges entirely inline-styled, duplicated across 6+ files. |
| 5 | Anti-Patterns | 3 | One borderline tell: toast side-stripe borders. `backdrop-filter: blur()` scoped to map overlays (appropriate). No gradient text, no glassmorphism in main UI, no bounce/elastic. |
| **Total** | | **13/20** | **Acceptable** |

**Rating band:** Acceptable (10-13). Significant work needed in accessibility and theming discipline.

---

## Issues by Severity

### P0: Blocking (0 issues)

No blocking accessibility or functional issues found.

### P1: Major (6 issues)

**P1-1. Form labels not programmatically associated with inputs.**
45 of 47 `<label>` elements use `class="form-label"` without a `for=` attribute or wrapping the input. Screen readers cannot associate the label with the form control. Only `accounting/ledger_create.html:34` correctly uses `for="{{ field.id_for_label }}"`.

Files affected: every list page toolbar (`parcels/list.html:24,40`, `wells/list.html:24,40`, `surface/water_rights_list.html:24,40`, `recharge/list.html:24,40`, `datasync/station_list.html:25,43,59`), `accounting/ledger_list.html:42,56,72,88,104,115`, `accounting/dashboard.html:50`, `reporting/report_generate.html:55,59`, `datasync/station_add.html:43,56,70,84,98`, `accounting/csv_upload.html:45,54`, and all `*_create.html` forms.

**P1-2. All 27 decorative SVGs lack `aria-hidden="true"`.**
SVG icons in sidebar links, header toggle, empty states, breadcrumbs, and buttons are decorative but exposed to assistive technology.

Files: `partials/_sidebar.html` (15 SVGs), `partials/_header.html` (1), empty state partials (several), breadcrumb partial (1), etc.

**P1-3. No focus indicators on buttons or links.**
`app.css` defines `:focus` styles only for `.form-input`, `.form-select`, and `.form-textarea`. No focus styles for `.btn-primary`, `.btn-secondary`, `.sidebar-link`, `.sidebar-toggle`, `.edit-btn`, `.data-table-link`, `.back-link`, or any `<a>` element.

File: `static/css/app.css` -- missing throughout.

**P1-4. Tertiary text fails WCAG AA contrast.**
`--color-text-tertiary` (#4d5e6f) on `--color-card` (#080b10) = 2.95:1 (needs 4.5:1 for AA normal, 3.0:1 for AA large). Used for field labels, timestamps, dashboard card labels, stat-card labels, and empty state text. These contain functional information.

Files: `static/css/app.css` lines 324, 269, 597, 559. Used across all detail page field labels.

**P1-5. Blue link color fails AA contrast on card backgrounds.**
`--color-blue` (#1B7FAF) on `--color-card` (#080b10) = 4.41:1 (needs 4.5:1). Used for `.data-table-link` (every list table's primary navigation link).

File: `static/css/app.css:384`.

**P1-6. Status badge inline styles duplicated across 6+ files.**
Identical 100+ character inline style strings with hardcoded hex colors (`#4ade80`, `#f87171`, `#22c55e`, `#eab308`, `#94a3b8`) instead of token system.

Files: `parcels/partials/_status_badge.html`, `wells/partials/_status_badge.html`, `surface/partials/_status_badge.html`, `recharge/partials/_status_badge.html`, `accounting/account_detail.html:53-59`, `accounting/partials/_accounts_list_results.html:32-38`, `accounting/partials/_periods_list_results.html:32`, `datasync/station_detail.html:122-131`.

### P2: Minor (7 issues)

**P2-1. Login page has no centering layout.**
`account/login.html:4` renders a card with `max-width: 420px` but no centering mechanism.

**P2-2. Login page labels not bound to inputs.**
`account/login.html:15,19` use `<label>` without `for=`. Email/password labels don't bind to inputs.

**P2-3. Sidebar `<aside>` lacks `aria-label`.**
`partials/_sidebar.html:2` uses `<aside>` without `aria-label="Main navigation"`.

**P2-4. Report table rows use `onclick` for navigation.**
`reporting/partials/_list_results.html:19` uses `onclick="window.location='...'"` on `<tr>`. Not keyboard-accessible, not announced by screen readers.

**P2-5. CDN scripts loaded without SRI hashes.**
`base.html:24` loads HTMX from unpkg without `integrity` attribute. MapLibre GL JS similarly loaded without SRI across 5 detail templates.

**P2-6. Map page references Font Awesome icons but no Font Awesome CSS loaded.**
`geography/map.html:44-58` uses 5 Font Awesome classes (`fa-map`, `fa-satellite`, `fa-home`, `fa-compass`, `fa-ruler`). Neither base.html nor map.html loads Font Awesome CSS. Icons render as invisible/blank.

**P2-7. `stat-grid-2col` has no responsive override.**
`app.css:926` defines the grid but has no breakpoint rule. Will not collapse on mobile.

### P3: Polish (5 issues)

**P3-1. 193 inline `style` attributes across templates.**
Many set flex, min-width, max-width, margin, padding values that should be utility classes.

**P3-2. Dashboard card value uses inline style instead of utility class.**
`index.html:27` uses `style="color: var(--reservoir-500);"` instead of a class.

**P3-3. Map overlay hardcoded colors in JavaScript.**
`geography/map.html:100-158` hardcodes 7+ hex colors in MAP_CONFIG. Match token values but not pulled from CSS variables.

**P3-4. Wells inline edit uses inline styles instead of form classes.**
`wells/partials/_field_edit.html:9-30` duplicates form styling via inline attributes instead of `.form-input` etc.

**P3-5. Toast side-stripe border is borderline AI slop tell.**
`app.css:1111,1115` uses `border-left: 3px solid` on toasts. Functional but matches the AI pattern.

---

## Executive Summary

OpenH2O has a solid foundation: a well-structured token system, consistent dark-mode surfaces, and clean HTMX interactions. The design system in tokens.css and app.css covers core patterns well.

The primary weakness is accessibility. No buttons or links have focus indicators, nearly all form labels are unbound, all decorative SVGs lack aria-hidden, and the tertiary text color fails WCAG AA. These affect every page.

The secondary weakness is theming discipline. Status badges exist as inline style strings copy-pasted across 6+ files with hardcoded Tailwind-palette hex colors instead of design tokens. This is the biggest maintenance risk, and the fix is mechanical.

The codebase is clean of AI slop. No gradient text, no glassmorphism in the main UI, no bounce animations, no generic fonts.

---

*Audit method: Code-level scan of 66 Django HTML templates, 3 CSS files, across 5 technical dimensions. Contrast ratios calculated from token hex values.*
