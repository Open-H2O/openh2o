# Roadmap: Open Water Accounting Platform

## Overview

Stand up an AI-deployable water accounting platform from scratch. Start with Docker infrastructure, build the 48-table domain model, add spatial CRUD and maps, wire up the accounting engine and external data feeds in parallel, layer on state reporting, add health monitoring, then polish the DEPLOY.md until an AI can stand the whole thing up on a fresh VPS unassisted.

## Domain Expertise

None (no matching skills installed)

## Phases

- [x] **Phase 1: Infrastructure Scaffold** - Docker Compose stack boots Django through Caddy with PostGIS
- [x] **Phase 2: Core Domain Models** - All 48 models, migrations, admin, seed data commands
- [x] **Phase 3: Parcel and Well CRUD with Maps** - Import, view, and manage parcels/wells on MapLibre map
- [x] **Phase 4: Water Accounting Engine** - ParcelLedger double-entry, accounts, allocations, dashboards
- [ ] **Phase 5: External Data Aggregator** - 8 API adapters with station discovery and geographic filtering
- [ ] **Phase 6: State Reporting** - GEARS CSV, CalWATRS CSV, email+JSON with prepare-review-send workflow
- [ ] **Phase 7: Health Check and Maintenance** - 8-category health system, /health endpoint, maintenance commands
- [ ] **Phase 8: UI/UX Overhaul** - Consistent styling, empty states, responsive layout, form polish
- [ ] **Phase 9: DEPLOY.md, Polish, and Handoff** - AI-consumable deployment guide, demo fixtures, security hardening

## Phase Details

### Phase 1: Infrastructure Scaffold
**Goal**: Docker Compose stack boots, Django serves a styled page through Caddy, PostGIS is ready
**Depends on**: Nothing (first phase)
**Research**: Unlikely (established Docker/Django/Caddy patterns)
**Plans**: 1/1 complete
**Completed**: 2026-05-23

Deliverables:
- docker-compose.yml (db, web, caddy)
- Dockerfile with GDAL/GEOS/PROJ for GeoDjango
- Caddyfile with auto-HTTPS and reverse proxy
- Django project skeleton with split settings (base/local/production)
- pyproject.toml with all dependencies including django-allauth
- VanderDev OKLCH design tokens ported to CSS custom properties
- Base template with HTMX, Tailwind, Public Sans + JetBrains Mono
- Tailwind standalone binary in Docker build
- DEPLOY.md skeleton, CLAUDE.md project context

Verification: `docker compose up -d` succeeds. `curl localhost` returns styled page. `psql` confirms PostGIS loaded.

### Phase 2: Core Domain Models
**Goal**: All 48 models exist with migrations, admin registered, seed data and auth working
**Depends on**: Phase 1
**Research**: Unlikely (Django ORM, django-allauth are well-documented)
**Plans**: 7/7 complete
**Completed**: 2026-05-23

Deliverables:
- All Django models across 11 apps with initial migrations
- Django admin registered for every model
- Management commands: seed_roles, seed_water_types, seed_data_sources
- Custom User model (extends AbstractUser)
- SiteConfig singleton with allow_google_oauth toggle
- django-allauth: email/password login, email verification, password reset
- Google OAuth provider (disabled by default, per-agency toggle)
- Styled login/logout/register/password-reset templates
- GeoDjango spatial fields on all geographic models

Verification: `manage.py migrate` succeeds. Seed commands populate reference data. Admin shows all 48 models. Password reset sends email. Google OAuth button appears only when enabled.

### Phase 3: Parcel and Well CRUD with Maps
**Goal**: Import parcels and wells, see them on a map, view details, manage surface water and recharge
**Depends on**: Phase 2
**Research**: Unlikely (MapLibre GL JS and HTMX patterns established from VanderDev)
**Plans**: 4/4 complete
**Completed**: 2026-05-24

Deliverables:
- Parcel list/detail views with HTMX search/filter
- Well list/detail views with HTMX search/filter
- MapLibre GL JS map: parcels as polygons, wells as points, water rights, recharge sites
- map-engine.js adapted from VanderDev (MAP_CONFIG pattern)
- Layer controls, popups, legend, basemap toggle
- Management commands: import_parcels (GeoJSON/Shapefile), import_wells (CSV/Shapefile)
- HTMX inline editing for parcel and well attributes
- Surface water views: water rights list, points of diversion on map
- Recharge sites on map with event history

Verification: Import test GeoJSON. See parcels on map. Click parcel, see detail. Wells render as points. HTMX filters work without full page reload.

### Phase 4: Water Accounting Engine
**Goal**: ParcelLedger double-entry system works with account balances, allocations, and budget dashboards
**Depends on**: Phase 3
**Research**: Unlikely (double-entry pattern documented from Rio repo analysis)
**Plans**: 3/3 complete
**Status**: Complete
**Completed**: 2026-05-24

Deliverables:
- ParcelLedger entry creation (manual and CSV bulk upload)
- Water account management (create, assign parcels, view balance)
- Allocation plan configuration per zone and water type
- Reporting period management (water years, finalization)
- Dashboard: account-level water budget (supply vs usage, surplus/deficit)
- import_ledger_csv management command
- Balance calculation: per-parcel, per-account, per-zone aggregations
- Surface water diversion records linked to water rights
- Recharge events creating positive ledger entries

Verification: Create account, assign parcels, add +100 AF supply and -75 AF usage. Dashboard shows 25 AF surplus. CSV upload adds entries in batch.

**Can run in parallel with Phase 5.**

### Phase 5: External Data Aggregator
**Goal**: 8 adapters fetch, stage, and publish external water data filtered to the agency's geographic area
**Depends on**: Phase 3
**Research**: Likely (8 external APIs with varying auth, formats, and quirks)
**Research topics**: Current USGS OGC API endpoints (legacy NWIS shutting down), OpenET API key acquisition process, CNRFC file format, DWR SGMA Portal REST endpoints, CIMIS AppKey registration
**Plans**: 1/2 complete

Deliverables:
- BaseAdapter abstract class: fetch/parse/validate/stage/publish pipeline
- 8 concrete adapters: CDEC, USGS (OGC API), OpenET (3-stage async), CIMIS, CNRFC, DWR WDL, DWR SGMA, NOAA
- OpenET 3-stage pipeline: trigger, poll, retrieve
- DataSyncLog and DataRecordStaging tables
- monitored_station model with discovery and curation workflow
- Management commands: sync_source, sync_all, check_source_health, discover_stations
- Station management UI: list on map, toggle active/inactive, add custom
- Rate limiting and retry logic per adapter
- Mock mode for development (fixture data, no network calls)

Verification: Set boundary. `discover_stations cdec --radius 50`. See stations on map. Activate 3. `sync_source cdec`. Data appears in staging and publishes. `check_source_health` reports all 8.

**Can run in parallel with Phase 4.**

### Phase 6: State Reporting
**Goal**: Generate GEARS CSV, CalWATRS CSV, and email+JSON reports with prepare-review-send workflow
**Depends on**: Phases 4 and 5 (needs ledger data and external data)
**Research**: Likely (GEARS CSV template format, CalWATRS A1/A2 specifications, Power Automate JSON schema)
**Research topics**: Current GEARS upload template columns, CalWATRS CSV specifications (5 templates), Power Automate shared mailbox trigger patterns, HMAC signature implementation
**Plans**: TBD

Deliverables:
- GEARS CSV generator (per-well and per-parcel ET methods)
- CalWATRS CSV generator (A1 and A2 templates)
- Email+JSON generator with Power Automate-compatible schema
- ReportingCrosswalk configuration UI
- Prepare-review-send workflow with validation warnings
- Report history view (all submissions with dates, periods, status)
- Management commands: generate_report, validate_report, submit_report

Verification: Generate GEARS CSV. Validate column headers match spec. Generate CalWATRS A1. Create email+JSON draft, inspect JSON structure and HMAC signature.

### Phase 7: Health Check and Maintenance
**Goal**: Management commands for ongoing monitoring, health dashboard with green/yellow/red indicators
**Depends on**: Phase 3 (needs models and views in place)
**Research**: Unlikely (Django management commands, standard system checks)
**Plans**: TBD

Deliverables:
- run_health_checks command (8 categories: DB, disk, sync freshness, ledger integrity, orphans, SSL, Docker, migrations)
- Health dashboard page with color-coded indicators
- prune_old_data command (staging >90 days, health >365 days)
- /health JSON endpoint for external monitoring
- Cron-ready design for docker exec

Verification: Run health checks, see results on dashboard. Break a data source, re-run, see it flagged red.

**Can run in parallel with Phase 6.**

### Phase 8: UI/UX Overhaul
**Goal**: Every page is usable, self-explanatory, and visually consistent with VanderDev design system
**Depends on**: Phases 4 and 5 (all data screens exist)
**Research**: Unlikely (design system already established)
**Plans**: TBD

Deliverables:
- Consistent page headers with breadcrumbs and contextual description on every page
- Empty states with guided next-action on all list pages
- Form styling standardized (dark-mode inputs, validation feedback, loading states)
- Table styling standardized (sortable headers, zebra rows, responsive overflow)
- Dashboard stat cards with sparkline trends (not just current numbers)
- Mobile-responsive layout for all pages (sidebar overlay already works)
- Page-level loading indicators for HTMX transitions
- Consistent color-coding for supply/usage/net across all views
- CSS class extraction (replace inline styles with reusable classes in app.css)
- Toast notifications for create/update/delete actions
- Seed data improvements (realistic names, diverse scenarios)

Verification: Walk through every page on desktop and mobile. Each page should explain what it does. No unstyled form inputs, no broken layouts, no dead-end empty states.

### Phase 9: DEPLOY.md, Polish, and Handoff
**Goal**: AI-consumable deployment guide is complete, demo data loaded, ready for pilot
**Depends on**: All phases complete
**Research**: Unlikely (documentation and fixture generation)
**Plans**: TBD

Deliverables:
- DEPLOY.md: every step copy-pasteable with verification and failure modes
- DEPLOY.md section: "Set up Google OAuth (optional)" with Google Cloud Console walkthrough
- DEPLOY.md section: "Configure email for password reset" with SMTP setup
- CLAUDE.md: full project context for AI assistants
- Demo fixture: 1 GSA boundary, 3 zones, 50 parcels, 20 wells, 6 months ledger, 3 accounts
- Makefile shortcuts: make up, make migrate, make seed, make test, make health
- Security hardening: CSRF, SECURE_* settings, rate limiting
- GitHub Actions test workflow
- README.md with quick start

Verification: Clone to fresh VPS. Follow DEPLOY.md exactly. Platform boots with demo data. Health checks pass. Generate sample GEARS report.

## Critical Path

```
Phase 1 → Phase 2 → Phase 3 → Phase 4 (parallel) → Phase 6 → Phase 8 (UI) → Phase 9
                                Phase 5 (parallel) /         /
                                Phase 7 (parallel) ----------
```

Phases 4+5 can run in parallel after Phase 3.
Phases 6+7 can run in parallel, but Phase 6 needs 4+5 complete.
Phase 8 is the final integration phase.

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Infrastructure Scaffold | 1/1 | Complete | 2026-05-23 |
| 2. Core Domain Models | 7/7 | Complete | 2026-05-23 |
| 3. Parcel and Well CRUD with Maps | 4/4 | Complete | 2026-05-24 |
| 4. Water Accounting Engine | 3/3 | Complete | 2026-05-24 |
| 5. External Data Aggregator | 1/2 | In progress | - |
| 6. State Reporting | 0/TBD | Not started | - |
| 7. Health Check and Maintenance | 0/TBD | Not started | - |
| 8. UI/UX Overhaul | 0/TBD | Not started | - |
| 9. DEPLOY.md, Polish, and Handoff | 0/TBD | Not started | - |
