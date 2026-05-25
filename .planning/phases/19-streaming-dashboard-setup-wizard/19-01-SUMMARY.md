---
phase: 19-streaming-dashboard-setup-wizard
plan: 01
subsystem: ui, datasync, setup
tags: [django, htmx, maplibre, sparklines, geojson, wizard, auto-populate]

requires:
  - phase: 18-telemetry-discovery-openet
    provides: Station auto-discovery, OpenETCache model, auto_populate station step
  - phase: 17-static-gis-auto-populate
    provides: auto_populate management command with step registry
  - phase: 12.1-vanderdev-design-alignment
    provides: VanderDev design tokens, stat-card-accent patterns, section labels
provides:
  - Monitoring dashboard at /datasync/dashboard/ with sparklines and freshness map
  - Setup wizard at /setup/ for boundary selection and auto-populate execution
  - Freshness GeoJSON endpoint for map-based station health
affects: [20-ai-operator-guide, 21-merced-automated-deployment]

tech-stack:
  added: []
  patterns: [inline-svg-sparklines, htmx-step-progress, service-layer-extraction]

key-files:
  created: [templates/datasync/monitoring_dashboard.html, templates/datasync/partials/_monitoring_content.html, templates/setup/wizard.html, templates/setup/confirm.html, templates/setup/run.html, templates/setup/partials/_progress.html, setup/__init__.py, setup/apps.py, setup/views.py, setup/urls.py, setup/services.py]
  modified: [datasync/views.py, datasync/urls.py, static/css/app.css, config/settings/base.py, config/urls.py, templates/partials/_sidebar.html]

key-decisions:
  - "source_status_list as flat list instead of dict-keyed to avoid custom template filter"
  - "Service layer wraps Command step methods directly, no code duplication"

patterns-established:
  - "Inline SVG sparklines computed in view, passed as template context"
  - "HTMX step-by-step progress via session-tracked step index"

issues-created: []

duration: 9min
completed: 2026-05-25
---

# Phase 19 Plan 01: Streaming Dashboard & Setup Wizard Summary

**Monitoring dashboard with station health cards, inline SVG sparklines, freshness-colored map markers, and a 4-step setup wizard that auto-populates data from boundary selection**

## Performance

- **Duration:** 9 min
- **Started:** 2026-05-25T20:38:57Z
- **Completed:** 2026-05-25T20:48:42Z
- **Tasks:** 5
- **Files modified:** 17

## Accomplishments
- Monitoring dashboard at /datasync/dashboard/ with 4 stat cards, source status cards, station card grid with inline SVG sparklines, and MapLibre freshness map
- Freshness GeoJSON endpoint classifying stations as fresh/stale/dead with hours_since_data for graduated styling
- Setup wizard app with boundary selection (dropdown or GeoJSON upload), map preview, and step-by-step auto_populate execution
- Service layer extracting auto_populate step logic for reuse without shelling out
- Sidebar navigation wired for both new pages with active state detection

## Task Commits

Each task was committed atomically:

1. **Task 1: Monitoring dashboard view + freshness GeoJSON endpoint** - `8f037e6` (feat)
2. **Task 2: Dashboard template with stat cards, sparklines, freshness map** - `8b3bd83` (feat)
3. **Task 3: Setup wizard app with multi-step views and service layer** - `b26487e` (feat)
4. **Task 4: Setup wizard templates with map preview and progress UI** - `2f27dc0` (feat)
5. **Task 5: Sidebar navigation wiring and CSS components** - `7a9c66d` (feat)

## Files Created/Modified
- `datasync/views.py` - monitoring_dashboard + stations_freshness_geojson views
- `datasync/urls.py` - dashboard/ and stations/freshness-geojson/ routes
- `templates/datasync/monitoring_dashboard.html` - wrapper with HTMX auto-refresh
- `templates/datasync/partials/_monitoring_content.html` - stat cards, sparklines, map
- `setup/views.py` - setup_wizard, setup_confirm, setup_run, setup_progress views
- `setup/services.py` - run_auto_populate_step wrapping Command logic
- `setup/urls.py` - /setup/ URL patterns
- `templates/setup/wizard.html` - boundary selection with GeoJSON upload
- `templates/setup/confirm.html` - MapLibre boundary preview
- `templates/setup/run.html` - progress page with HTMX trigger
- `templates/setup/partials/_progress.html` - step-by-step status partial
- `static/css/app.css` - sparkline, freshness-dot, wizard-step, spinner, upload-zone
- `config/settings/base.py` - setup app registered in INSTALLED_APPS
- `config/urls.py` - /setup/ include
- `templates/partials/_sidebar.html` - Monitoring and Setup Wizard links

## Decisions Made
- source_status_list as flat list (not dict) to avoid custom Django template filter for key lookup
- Service layer wraps Command step methods directly rather than duplicating logic
- Stations active path narrowed to /datasync/stations (was /datasync/ which was too broad)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Next Phase Readiness
- Phase 19 complete, ready for Phase 20 (AI Operator Guide)
- Setup wizard fully operational for automated deployment workflows
- Dashboard provides real-time station health visibility

---
*Phase: 19-streaming-dashboard-setup-wizard*
*Completed: 2026-05-25*
