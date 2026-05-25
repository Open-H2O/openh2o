---
phase: 11-ui-quality-sweep
plan: 01
subsystem: ui, css, templates
tags: [django, css, responsive, forms, favicon, geojson, maplibre]

requires:
  - phase: 08-deploy-polish-handoff
    provides: breadcrumbs, toasts, semantic colors, card/table CSS components
  - phase: 10-kaweah-demo-data
    provides: real Kaweah seed data for landing page counts and map popups
provides:
  - responsive CSS breakpoints (tablet 1023px, mobile 767px)
  - CSS form classes replacing inline styles (form-input, form-select, form-textarea)
  - utility classes (table-scroll, page-narrow, page-medium, toolbar-row)
  - landing page with live entity counts
  - SVG favicon (California Gold water droplet)
  - SVG empty-state icons replacing emoji characters
  - GeoJSON pk injection for map popup "View details" links
affects: [phase-12-documentation, phase-13-final-polish]

tech-stack:
  added: []
  patterns: [css-utility-classes, responsive-breakpoints, geojson-property-injection]

key-files:
  created: []
  modified:
    - static/css/app.css
    - accounting/forms.py
    - reporting/forms.py
    - config/views.py
    - templates/index.html
    - templates/base.html
    - templates/partials/_header.html
    - wells/views.py
    - parcels/views.py

key-decisions:
  - "Post-process Django GeoJSON serialize() to inject pk into properties rather than rewriting views"
  - "Keep mobile sidebar overlay behavior unchanged (toggle via hamburger)"

patterns-established:
  - "CSS class pattern for form widgets: form-input, form-select, form-textarea"
  - "Responsive grid collapse: 1023px tablet, 767px mobile"
  - "SVG inline icons for empty states instead of emoji characters"

issues-created: []

duration: 21min
completed: 2026-05-25

quality-gates-run: []
quality-gates-passed: true
quality-gates-violations-fixed: 0
---

# Phase 11 Plan 01: UI Quality Sweep Summary

**Responsive CSS, form class cleanup, landing page with live data counts, favicon, and GeoJSON popup fix across 31 files**

## Performance

- **Duration:** 21 min
- **Started:** 2026-05-25T03:35:38Z
- **Completed:** 2026-05-25T03:56:46Z
- **Tasks:** 4 (3 auto + 1 checkpoint)
- **Files modified:** 31

## Accomplishments
- Replaced all inline form styles with CSS classes (form-input, form-select, form-textarea) enabling focus ring styling
- Added responsive breakpoints: tablet (1023px) collapses 2-col grids, mobile (767px) collapses all grids, reduces padding, hides header email
- Landing page shows live entity counts (40 parcels, 25 wells, 10 water rights, 4 recharge sites, 10 water accounts, 30 stations)
- Added SVG water-droplet favicon in California Gold
- Replaced 9 emoji empty-state icons with contextual inline SVGs
- Replaced inline styles with CSS utility classes across 8+ list templates and 3 form pages
- Fixed pre-existing bug: map popup "View details" links for wells and parcels returned /wells/undefined/ because Django's GeoJSON serializer puts pk at feature level, not in properties

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace inline form styles** - `e653b01` (style)
2. **Task 2: Responsive CSS breakpoints** - `bfcf6ea` (style)
3. **Task 3: Visual consistency sweep** - `e3bf8f6` (feat)
4. **Bug fix: GeoJSON pk injection** - `ada1763` + `2ed4292` (fix)

## Files Created/Modified
- `static/css/app.css` - responsive breakpoints, utility classes (table-scroll, page-narrow, page-medium, toolbar-row)
- `accounting/forms.py` - inline styles replaced with CSS classes, constants removed
- `reporting/forms.py` - inline styles replaced with CSS classes, constants removed
- `config/views.py` - landing page now queries 6 model counts
- `templates/index.html` - dashboard cards with live entity counts
- `templates/base.html` - SVG favicon added
- `templates/partials/_header.html` - redundant flex spacer removed
- `wells/views.py` - GeoJSON pk injected into properties
- `parcels/views.py` - GeoJSON pk injected into properties
- 8 list partial templates - table-scroll class, toolbar-row class, SVG empty-state icons
- 6 list/form page templates - page-narrow/page-medium classes

## Decisions Made
- Post-process Django GeoJSON serialize() output to inject pk into properties, matching the pattern stations already uses (manual construction with pk in properties)
- Keep existing mobile sidebar overlay/toggle behavior unchanged per plan instruction

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed GeoJSON "View details" popup links returning /wells/undefined/**
- **Found during:** Task 4 (checkpoint verification, user-reported)
- **Issue:** Django's `serialize("geojson")` puts pk at the feature level as `"id"`, not in `properties`. MapLibre only passes `feature.properties` to popup callbacks, so `p.pk` was undefined for wells and parcels.
- **Fix:** Post-process serialized GeoJSON to copy `feature["id"]` into `feature["properties"]["pk"]` in both wells and parcels views.
- **Files modified:** wells/views.py, parcels/views.py
- **Verification:** GeoJSON endpoint confirmed pk:167 in properties; map popup links resolve correctly
- **Commits:** ada1763, 2ed4292

---

**Total deviations:** 1 auto-fixed (pre-existing bug), 0 deferred
**Impact on plan:** Bug fix was necessary for map popup navigation. No scope creep.

## Issues Encountered
None beyond the GeoJSON bug (documented above as deviation).

## Next Phase Readiness
- UI quality sweep complete, all pages responsive and visually consistent
- Ready for Phase 12 (In-App Documentation)
- No blockers

---
*Phase: 11-ui-quality-sweep*
*Completed: 2026-05-25*
