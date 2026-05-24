# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-23)

**Core value:** Access is the product, not features. A $15/mo VPS replaces a $35K-$75K consulting engagement.
**Current focus:** Phase 8 -- Deploy, Polish, and Handoff

## Current Position

Phase: 8 of 8 (Deploy, Polish, and Handoff)
Plan: 2 of 3 in current phase
Status: In progress
Last activity: 2026-05-24 -- Completed 08-02-PLAN.md

Progress: █████████████████████░ 95% (20/21 plans complete)

## Performance Metrics

**Velocity:**
- Total plans completed: 8
- Average duration: 11 min
- Total execution time: 1.5 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 Infrastructure Scaffold | 1 | 50 min | 50 min |
| 02 Core Domain Models | 7 | 39 min | 5.6 min |

**Recent Trend:**
- Last 5 plans: 4 min, 5 min, 5 min, 6 min, 14 min
- Trend: Phase 2 averaging 5.6 min/plan (02-07 longer due to human verification)

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- register_adapter() at module level for auto-registration on import
- OpenET uses station.location point (not parcel polygon) for initial sync
- Mock mode: DATASYNC_MOCK_MODE setting OR DataSource.is_active=False
- Shared DataSyncLog per sync_source run (not per station)
- GeoJSON for stations built manually (PointField + custom properties, not Django serialize)
- discover_stations creates stations inactive by default (curation workflow)
- Toggle partial uses hx-target="this" outerHTML for list/detail portability
- Removed hardcoded GDAL/GEOS paths from Dockerfile; Django finds them automatically
- Created minimal User model stub; AUTH_USER_MODEL requires resolvable model at boot
- Butler deploy key added to GitHub for SSH clone access
- SiteConfig singleton via save() ValidationError, not metaclass
- Cross-app FKs use string references for deferred migration resolution
- Zone zone_type: CharField with choices, not separate lookup table
- All migrations generated in single pass (no circular FK issues)
- Pillow added to pyproject.toml for ImageField support
- Butler deploy key is read-only; migrations generated on Butler, committed locally
- django-allauth deprecation warnings fixed in 02-06 (ACCOUNT_LOGIN_METHODS/ACCOUNT_SIGNUP_FIELDS)
- django.contrib.sites added; django_site table created manually to fix migration ordering
- SiteConfig exposed to templates via context processor (not template tag)
- CARTO dark basemap for map page (matches VanderDev dark-mode aesthetic)
- GeoJSON endpoints use HttpResponse (not JsonResponse) since GeoDjango serialize returns string
- Sidebar collapse state persisted in localStorage
- Default basemap is CARTO dark (not aerial) for dark-mode consistency
- GeoJSON fetch gracefully falls back to empty FeatureCollection on failure
- parcels-fill and parcels-outline share group: 'parcels' for unified toggle
- EDITABLE_FIELDS dict pattern for inline editing (type/choices/validation in one config)
- PATCH body parsed via parse_qs (Django doesn't populate request.POST for PATCH)
- ParcelZone is the zone membership model (not ZoneMembership)
- _field_value.html partial completes the HTMX edit round-trip cycle
- import_parcels uses ParcelStaging for staged import with duplicate detection before promotion
- import_wells creates Well records directly (no staging table for simpler point data)
- Surface water and recharge views are read-only (no inline editing, data from external sources)
- Soft delete for WaterAccountParcel removal (removed_date) preserves historical assignment data
- All accounting ModelForms in single forms.py with shared dark-mode style constants
- Diversion/recharge integration functions accept explicit parcel/zone params (missing model FKs)
- Balance engine uses Django ORM aggregate(Sum); period selector defaults to most recent non-finalized period
- OKLCH inline colors for health badges (no --color-error token; used oklch(0.65 0.20 25))
- Health dashboard and API are public (no login_required) for monitoring tool access
- Phases 8+9 merged into single Phase 8 (Deploy, Polish, and Handoff)
- Template-logic conditional colors (Django if/else inside style attr) kept inline -- irreducible
- CSS component system: 40+ reusable classes in app.css (page-stack, section-header, field-group, data-table, form-input, badge, empty-state)

### Deferred Issues

- ISSUE-001: RechargeSite missing zone FK (Phase 04-02)
- ISSUE-002: WaterRight missing parcel FK (Phase 04-02)

### Blockers/Concerns

- OpenET API key not yet requested (needed by Phase 5)

## Session Continuity

Last session: 2026-05-24
Stopped at: Completed 08-02-PLAN.md (breadcrumbs, loading bar, toasts, color coding)
Resume file: None
