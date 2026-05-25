---
phase: 12-in-app-documentation
plan: 01
subsystem: ui
tags: [django, htmx, css, tooltips, help-pages, documentation]

requires:
  - phase: 11.1-impeccable-ui-audit
    provides: WCAG AA contrast, badge classes, progressive disclosure patterns
provides:
  - CSS-only tooltip infrastructure (help-tooltip, help-icon, help-text)
  - Page-description component for contextual help
  - Getting Started walkthrough (8 steps)
  - Glossary page (21 water accounting terms)
  - Help section in sidebar navigation
  - Field-level tooltips on detail views
affects: [13-cron-health-polish]

tech-stack:
  added: []
  patterns: [css-only-tooltips, page-description-convention, help-page-pattern]

key-files:
  created:
    - templates/partials/_help_tooltip.html
    - templates/help/getting_started.html
    - templates/help/glossary.html
  modified:
    - static/css/app.css
    - config/views.py
    - config/urls.py
    - templates/partials/_sidebar.html
    - templates/base.html
    - Dockerfile

key-decisions:
  - "CSS-only tooltips (no JS libraries) to keep the stack dependency-free"
  - "Help views in config/ rather than new Django app (only 2 views)"
  - "Glossary terms as Python dict in view, not a database model"
  - "collectstatic --clear in Dockerfile to prevent stale manifest issues"

patterns-established:
  - "page-description: muted text below page titles for contextual help"
  - "help-tooltip: CSS-only hover/focus popup for field-level help"
  - "step-card: gold-accented numbered walkthrough cards"

issues-created: []

duration: 37min
completed: 2026-05-25
---

# Phase 12 Plan 01: In-App Documentation Summary

**CSS-only tooltip infrastructure, Getting Started walkthrough with gold step badges, alphabetical Glossary with blue letter dividers, page descriptions on all 20 views, and field tooltips on 4 detail pages.**

## Performance

- **Duration:** 37 min
- **Started:** 2026-05-25T11:57:10Z
- **Completed:** 2026-05-25T12:34:42Z
- **Tasks:** 4
- **Files modified:** 28

## Accomplishments
- Tooltip infrastructure: CSS-only hover/focus-within popups with semantic HTML (button + role=tooltip)
- Getting Started page: 8-step walkthrough with gold numbered badges and left-border accent cards
- Glossary page: 21 water accounting terms with blue letter dividers and styled jump-nav
- Page descriptions on all 20 list/detail pages (22 total instances)
- Field tooltips on parcel, well, water right, and station detail views (11 instances)
- Help section added to sidebar navigation with SVG icons

## Task Commits

Each task was committed atomically:

1. **Task 1: Help text infrastructure** - `1acecf1` (feat)
2. **Task 2: Help pages (Getting Started + Glossary)** - `0103ebf` (feat)
3. **Task 3: Per-page contextual help** - `a17adb8` (feat)
4. **Task 3b: Cache-bust fix** - `ab08068` (fix)
5. **Task 3c: Aesthetic polish** - `7feabab` (feat)
6. **Task 3d: Dockerfile collectstatic fix** - `5c32156` (fix)

## Files Created/Modified
- `templates/partials/_help_tooltip.html` - Reusable tooltip include partial
- `templates/help/getting_started.html` - 8-step setup walkthrough
- `templates/help/glossary.html` - 21-term water accounting glossary
- `static/css/app.css` - page-description, help-tooltip, step-card, glossary CSS
- `config/views.py` - getting_started and glossary views with @login_required
- `config/urls.py` - help/ URL prefix with two routes
- `templates/partials/_sidebar.html` - Help section with two links
- `templates/base.html` - Cache-bust param on app.css link
- `Dockerfile` - Added --clear to collectstatic
- 20 existing templates updated with page descriptions and/or field tooltips

## Decisions Made
- CSS-only tooltips rather than JS libraries: keeps the zero-dependency frontend philosophy
- Views in config/ not a new app: two views don't warrant a Django app
- Glossary terms as view context dict: content is static, no DB model needed
- Added --clear to Dockerfile collectstatic: WhiteNoise manifest was caching stale CSS

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Stale CSS not served by WhiteNoise**
- **Found during:** Checkpoint verification
- **Issue:** collectstatic manifest kept old app.css hash; new tooltip/step-card CSS not served
- **Fix:** Ran collectstatic --clear, added ?v=3 cache-bust, added --clear to Dockerfile
- **Files modified:** templates/base.html, Dockerfile
- **Verification:** Computed styles confirmed via chrome-devtools
- **Committed in:** ab08068, 5c32156

**2. [Rule 5 - Enhancement] Aesthetic polish requested by user**
- **Found during:** Checkpoint review
- **Issue:** Getting Started and Glossary pages were functional but visually plain
- **Fix:** Added gold step-number badges with left borders, blue letter dividers, styled jump-nav
- **Files modified:** static/css/app.css, templates/help/getting_started.html, templates/help/glossary.html
- **Verification:** Screenshots confirmed via chrome-devtools
- **Committed in:** 7feabab

---

**Total deviations:** 2 (1 bug fix, 1 user-requested enhancement)
**Impact on plan:** Bug fix was necessary for correct CSS delivery. Enhancement improved visual quality per user feedback.

## Issues Encountered
None

## Next Phase Readiness
- In-app documentation complete: all pages have contextual help
- Tooltip infrastructure available for future detail views
- Ready for Phase 13 (Cron, Health, & Final Polish)

---
*Phase: 12-in-app-documentation*
*Completed: 2026-05-25*
