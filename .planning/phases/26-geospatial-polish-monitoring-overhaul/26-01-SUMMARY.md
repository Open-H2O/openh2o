---
phase: 26-geospatial-polish-monitoring-overhaul
plan: 01
subsystem: ui
tags: [css-tokens, maplibre, font-sweep, layer-panel, color-system]

requires:
  - phase: 19.2-visual-overhaul-ux-refinement
    provides: Deep Pacific palette, design tokens
  - phase: 25-content-polish
    provides: Final UI naming and content

provides:
  - Centralized entity color system (CSS vars + JS OH2O.colors object)
  - Zero hardcoded entity hex in templates/JS
  - Grouped collapsible layer panel
  - Site-wide font consistency (no JetBrains Mono on data values)
  - Site-wide significant figures normalization (2 decimal places)

affects: [phase-26-monitoring-overhaul, phase-27-data-entry]

tech-stack:
  added: []
  patterns:
    - "OH2O.colors global JS object for MapLibre paint properties"
    - "CSS entity color vars (--color-entity-*) for non-JS contexts"
    - "tabular-nums on td-num without monospace font"
    - "Layer section grouping via MAP_CONFIG.layers[].section property"

key-files:
  created: []
  modified:
    - static/css/tokens.css
    - static/css/app.css
    - static/css/map-engine.css
    - static/js/map-engine.js
    - templates/base.html
    - templates/geography/map.html
    - templates/surface/pod_detail.html
    - templates/surface/water_right_detail.html
    - templates/recharge/site_detail.html
    - templates/datasync/station_detail.html
    - templates/wells/detail.html
    - templates/parcels/detail.html
    - templates/infrastructure/partials/_list_results.html

key-decisions:
  - "Public Sans with tabular-nums for numeric data instead of JetBrains Mono"
  - "OH2O.colors defined before map_scripts block in base.html for correct load order"
  - "text-mono kept only on technical identifiers (well IDs, station codes, parameter codes)"
  - "floatformat:2 as standard precision for all water accounting values"

issues-created: []

duration: 41min
completed: 2026-05-28
---

# Phase 26 Plan 01: Visual Polish Summary

**Unified entity color system, killed slashed-zero font bleed site-wide, grouped layer panel, normalized significant figures to 2 decimal places across all templates and map popups**

## Performance

- **Duration:** 41 min
- **Started:** 2026-05-28T12:19:34Z
- **Completed:** 2026-05-28T13:00:36Z
- **Tasks:** 5 (4 auto + 1 checkpoint)
- **Files modified:** 20+

## Accomplishments

- Created centralized entity color system: 5 CSS vars (`--color-entity-*`) plus `OH2O.colors` JS global object for MapLibre configs
- Fixed gold token mismatch (`#D49A2B` → `#E4A317`) and radius mismatch (8px → 10px) in tokens.css
- Swept all hardcoded entity hex from 12 templates and map-engine.js
- Fixed 3 entity color bugs: POD detail → teal, water_right detail → teal, recharge detail → purple
- Replaced all hardcoded `font-family:'Public Sans'` in map-engine.css with `var(--font-display)`
- Removed JetBrains Mono from `td-num`/`td-num-bold` CSS classes and 12 template data elements
- Normalized all numeric display to 2 decimal places (was 4 in some places, unformatted in others)
- Added type-aware formatting to editable field displays on wells and parcels detail pages
- Map popup JS values formatted with `toFixed()` for consistent precision
- Added grouped collapsible layer panel with 4 sections (Administrative, Land Use, Infrastructure, Monitoring)
- Map container breathing room (8px 12px margins, 10px radius)
- Coordinate toast: clipboard fallback for HTTP, "✓ Copied" text with pulse animation

## Task Commits

1. **Task 1: Reconcile design tokens and add entity color system** — `9fcca23`
2. **Task 2: Full hardcoded color sweep** — `ff20edc`
3. **Task 3: Font sweep, breathing room, toast upgrade** — `d16abf2`
4. **Task 4: Layer panel grouped redesign** — `dd1c8df`
5. **Task 5: Checkpoint verification** — auto-verified + human-approved

## Deviation Commits (auto-fixed during checkpoint)

6. **[Rule 1 - Bug] OH2O script load order** — `40afd5b` — OH2O defined after map_scripts block, causing ReferenceError on every map page
7. **[Rule 1 - Bug] Slashed-zero font bleed + toast clipboard** — `114554e` — JetBrains Mono on td-num/text-mono data elements; navigator.clipboard fails on HTTP
8. **[Rule 1 - Bug] Significant figures** — `0c94770` — floatformat:4 and unformatted fields showing excessive decimal places

## Files Created/Modified

- `static/css/tokens.css` — Gold fix, radius fix, 5 entity color vars
- `static/css/app.css` — td-num/td-num-bold: removed font-mono, cache-bust v7
- `static/css/map-engine.css` — font-family vars, layer section CSS, toast positioning
- `static/js/map-engine.js` — OH2O.colors refs, buildLayerPanel grouping, toast fallback
- `templates/base.html` — OH2O script block (moved before map_scripts), cache-busts
- `templates/geography/map.html` — MAP_CONFIG sections, popup toFixed formatting
- `templates/surface/pod_detail.html` — teal color, text-mono removed, floatformat:2
- `templates/surface/water_right_detail.html` — teal color, text-mono removed, floatformat:2
- `templates/recharge/site_detail.html` — purple color, text-mono removed
- `templates/datasync/station_detail.html` — floatformat:2
- `templates/wells/detail.html` — type-aware formatting, floatformat:2
- `templates/parcels/detail.html` — type-aware formatting
- `templates/infrastructure/partials/_list_results.html` — floatformat on all numeric fields
- 5 additional detail/partial templates — color token refs

## Decisions Made

- Public Sans with `font-variant-numeric: tabular-nums` replaces JetBrains Mono for numeric table data. Keeps column alignment without slashed zeros.
- `text-mono` class preserved only for technical identifiers (well registration IDs, station codes, parameter codes, CSV column names).
- `floatformat:2` standardized for all water accounting values. Coordinates stay at `:5`, area sq miles at `:1`, depth at `:0`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] OH2O script execution order**
- **Found during:** Task 5 checkpoint auto-verify
- **Issue:** OH2O colors defined after `{% block map_scripts %}` in base.html, so MAP_CONFIG threw ReferenceError
- **Fix:** Moved OH2O script block before the map_scripts block
- **Committed in:** `40afd5b`

**2. [Rule 1 - Bug] Slashed-zero font bleed site-wide**
- **Found during:** Task 5 checkpoint (user-reported, 4th occurrence)
- **Issue:** `td-num`, `td-num-bold` CSS classes and `text-mono` on data elements applied JetBrains Mono to numeric values
- **Fix:** Removed font-family:var(--font-mono) from td-num/td-num-bold, removed text-mono from 12 data display elements
- **Committed in:** `114554e`

**3. [Rule 1 - Bug] Toast not firing on HTTP**
- **Found during:** Task 5 checkpoint (user-reported)
- **Issue:** `navigator.clipboard.writeText()` throws on non-secure contexts (HTTP), killing function before toast displays
- **Fix:** try/catch with execCommand('copy') fallback
- **Committed in:** `114554e`

**4. [Rule 1 - Bug] Excessive decimal places site-wide**
- **Found during:** Task 5 checkpoint (user-reported)
- **Issue:** floatformat:4 on some fields, no formatting on others, raw DecimalField values showing 4+ decimals
- **Fix:** Normalized to floatformat:2, added formatting to 5 unformatted fields, JS popup toFixed(), type-aware editable fields
- **Committed in:** `0c94770`

---

**Total deviations:** 4 auto-fixed bugs (all Rule 1), 0 deferred
**Impact on plan:** All fixes necessary for visual correctness. Font and precision issues were the primary user-facing problems.

## Issues Encountered

None beyond the deviations documented above.

## Next Phase Readiness

- Plan 26-01 (Visual Polish) complete
- Ready for Plan 26-02 (Monitoring Overhaul) if it exists, or next phase planning
- All maps use centralized color system, layer panel is grouped, fonts and precision are clean

---
*Phase: 26-geospatial-polish-monitoring-overhaul*
*Completed: 2026-05-28*
