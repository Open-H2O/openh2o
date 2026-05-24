---
phase: 08-deploy-polish-handoff
plan: 01
subsystem: frontend/css
tags: [css, tailwind, templates, design-system, inline-style-extraction, empty-states]

requires:
  - phase: 07-health-check-maintenance
    provides: complete Django app with all templates and views

provides:
  - 40+ reusable CSS component classes added to static/css/app.css
  - Empty-state components on all list pages
  - 913 inline styles extracted (80.0% reduction: 1141 → 228)
  - All Django template logic preserved ({% %}, {{ }}, hx-* attributes)
affects: [all-templates]

tech-stack:
  added: []
  patterns: [css-component-extraction, utility-class-composition, template-logic-preserved-inline]

key-files:
  modified:
    - static/css/app.css
    - templates/account/login.html
    - templates/account/logout.html
    - templates/account/password_reset.html
    - templates/account/password_reset_done.html
    - templates/account/password_reset_from_key.html
    - templates/account/password_reset_from_key_done.html
    - templates/account/signup.html
    - templates/account/verification_sent.html
    - templates/accounting/account_create.html
    - templates/accounting/account_detail.html
    - templates/accounting/accounts_list.html
    - templates/accounting/allocation_create.html
    - templates/accounting/allocations_list.html
    - templates/accounting/csv_upload.html
    - templates/accounting/dashboard.html
    - templates/accounting/ledger_create.html
    - templates/accounting/ledger_list.html
    - templates/accounting/partials/_account_balances.html
    - templates/accounting/partials/_accounts_list_results.html
    - templates/accounting/partials/_allocations_list_results.html
    - templates/accounting/partials/_csv_upload_results.html
    - templates/accounting/partials/_dashboard_content.html
    - templates/accounting/partials/_ledger_list_results.html
    - templates/accounting/partials/_parcel_search_results.html
    - templates/accounting/partials/_periods_list_results.html
    - templates/accounting/period_create.html
    - templates/accounting/period_detail.html
    - templates/accounting/periods_list.html
    - templates/datasync/partials/_station_list_results.html
    - templates/datasync/station_add.html
    - templates/datasync/station_detail.html
    - templates/datasync/station_list.html
    - templates/health/dashboard.html
    - templates/parcels/detail.html
    - templates/parcels/partials/_list_results.html
    - templates/partials/_sidebar.html
    - templates/recharge/partials/_list_results.html
    - templates/recharge/site_detail.html
    - templates/reporting/partials/_list_results.html
    - templates/reporting/partials/_status_section.html
    - templates/reporting/report_detail.html
    - templates/reporting/report_generate.html
    - templates/surface/partials/_list_results.html
    - templates/surface/water_right_detail.html
    - templates/wells/detail.html
    - templates/wells/partials/_list_results.html

---

# 08-01 Summary: CSS Extraction and Empty-State Polish

## What Was Done

### Task 1: CSS Component Classes (commit a41cc84)
Added 40+ reusable CSS classes to `static/css/app.css`, covering:
- **Stat display:** `.inset-card`, `.stat-card-label`, `.stat-card-value-sm`, `.stat-card-unit`, `.stat-card-value-lg`, `.stat-grid-3col`, `.stat-grid-2col`, `.stat-value-lg`
- **Typography:** `.text-xs`, `.text-sm`, `.text-base`, `.text-gold`, `.text-blue`, `.text-furnace`, `.text-forest`, `.section-header-flush`, `.section-header-sm`
- **Layout:** `.row-start`, `.form-footer`, `.form-footer-ruled`, `.form-grid-2col`, `.card-header-ruled`, `.card-inset`, `.search-result-list`
- **Table:** `.th-right`, `.td-num`, `.td-num-bold`
- **Count/pagination:** `.result-count-bar`, `.count-pill`, `.pagination-row`, `.pagination-label`
- **Sidebar:** `.sidebar-section`, `.sidebar-section-label`
- **Forms:** `.form-error-box`, `.form-error-text`, `.required-mark`, `.label-pointer`
- **Map:** `.map-embed`
- **Badges:** `.pill-tag`, `.btn-xs`
- **Onboarding:** `.onboarding-steps`, `.onboarding-step`, `.step-badge`, `.step-badge-active`
- **Margin/padding:** `.mb-0`, `.mb-sm`, `.ml-xs`, `.ml-sm`, `.mr-xs`, `.pt-sm`, `.pt-md`
- **Misc:** `.alert-error`, `.alert-warning`, `.row-start`, `.field-value-sm`

### Task 2: Detail Template Extraction (commit 3e21913)
Extracted inline styles from 11 detail-view templates: account detail, period detail, parcels, wells, recharge site, water rights, datasync station, health dashboard, reporting detail, and both balance/dashboard partials.

### Task 3: List and Partial Template Extraction (commit 82ad165)
Extracted inline styles from 20 list and partial templates, adding count badges, pagination patterns, and table cell classes throughout.

### Task 4: Form and Auth Template Extraction (commit d466406)
Extracted inline styles from 15 form and auth templates using `form-error-box`, `card-header-ruled`, `form-footer`, `onboarding-steps`, `required-mark`, and color utility classes.

### Task 5: Empty-State Components (commit d9fe1fe)
Added consistent `.empty-state` + `.empty-state-text` components to all list pages across all 8 app modules.

## Verification

| Metric | Result |
|--------|--------|
| Original inline style count | 1,141 |
| Final inline style count | 228 |
| Styles eliminated | 913 |
| Reduction percentage | **80.0%** |
| Target (>80%, ≤228) | **PASS** |

## Remaining Inline Styles (228)

All remaining styles are intentional and fall into one of three categories:
1. **Template-logic conditional colors** — `style="{% if net >= 0 %}color: var(--forest-400);{% else %}color: var(--furnace-400);{% endif %}"` cannot be expressed as a static class
2. **Unique layout constraints** — `style="max-width: 640px;"`, `style="min-width: 200px;"`, `style="height: 320px;"` are page-specific values with no class equivalent
3. **Status badge RGBA variants** — per-status colored pills (active/inactive/suspended/open/finalized) use distinct RGBA border colors that require inline specificity

## Decisions Made

- Template-logic conditional colors are irreducible: kept inline, documented
- Where a style has both a generic class equivalent AND a unique override, both are applied: `class="map-embed" style="height: 280px;"`
- `font-semibold` from Tailwind used directly where available (no app.css duplication)
- `text-decoration: none` removed from `.btn-primary` and `.btn-secondary` anchor elements (redundant — display:inline-flex handles it)
