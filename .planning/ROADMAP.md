# Roadmap: Open Water Accounting Platform

## Overview

Stand up an AI-deployable water accounting platform from scratch. Start with Docker infrastructure, build the 48-table domain model, add spatial CRUD and maps, wire up the accounting engine and external data feeds in parallel, layer on state reporting, add health monitoring, then polish the DEPLOY.md until an AI can stand the whole thing up on a fresh VPS unassisted.

## Milestones

- ✅ **v1.0 MVP** — Phases 1-8 (shipped 2026-05-24)
- 🚧 **v1.1 Production Polish** — Phases 9-14 (in progress)
- 📋 **v1.2 Enhancement Suite** — Phases 15-27 (planned, includes Math Validation in 22, UI Overhaul in 23-25, Geo Polish in 26-27)

## Completed Milestones

- ✅ [v1.0 MVP](milestones/v1.0-ROADMAP.md) (Phases 1-8) — SHIPPED 2026-05-24

<details>
<summary>v1.0 MVP phase list</summary>

- [x] Phase 1: Infrastructure Scaffold (1/1 plans) — completed 2026-05-23
- [x] Phase 2: Core Domain Models (7/7 plans) — completed 2026-05-23
- [x] Phase 3: Parcel and Well CRUD with Maps (4/4 plans) — completed 2026-05-24
- [x] Phase 4: Water Accounting Engine (3/3 plans) — completed 2026-05-24
- [x] Phase 5: External Data Aggregator (2/2 plans) — completed 2026-05-24
- [x] Phase 6: State Reporting (1/1 plan) — completed 2026-05-24
- [x] Phase 7: Health Check and Maintenance (1/1 plan) — completed 2026-05-24
- [x] Phase 8: Deploy, Polish, and Handoff (3/3 plans) — completed 2026-05-24

</details>

### 🚧 v1.1 Production Polish (In Progress)

**Milestone Goal:** Transform v1.0 MVP into a demo-ready, documented, tested platform with real watershed data from two California basins.

#### Phase 9: Schema Fixes & Test Infrastructure

**Goal**: Fix deferred FK issues (RechargeSite zone, WaterRight parcel) and stand up pytest with factory_boy for baseline test coverage
**Depends on**: v1.0 complete
**Research**: Unlikely (internal patterns)
**Plans**: 1

Plans:
- [x] 09-01: Schema FK fixes + pytest infrastructure + baseline tests

#### Phase 10: Kaweah Subbasin Demo Data

**Goal**: Build ETL pipeline for Mid-Kaweah or Eastern Kaweah GSA area; populate with real wells, parcels, water rights, MAR projects, and monitoring stations from public sources
**Depends on**: Phase 9
**Research**: Likely (external data APIs and portal formats)
**Research topics**: CDEC/USGS/CIMIS API endpoints for Kaweah region, eWRIMS query patterns, Tulare County GIS download formats, Mid-Kaweah DMS data access, EKGSA GSP appendix data extraction
**Plans**: TBD

Plans:
- [x] 10-01: Kaweah Subbasin seed data with real DWR boundaries and Tulare County parcels

#### Phase 11: UI Quality Sweep

**Goal**: Polish navigation flow, visual consistency, responsive behavior, and data entry UX with real data visible in the system
**Depends on**: Phase 10
**Research**: Unlikely (internal CSS/HTML patterns)
**Plans**: TBD

Plans:
- [x] 11-01: Responsive CSS, form class cleanup, landing page counts, favicon, visual consistency

#### Phase 11.1: Impeccable UI Audit (INSERTED)

**Goal**: Run `/impeccable critique` (heuristic UX scoring) and `/impeccable audit` (accessibility, responsive, performance) against the deployed OpenH2O UI. Fix any issues found before documentation phase.
**Depends on**: Phase 11
**Research**: Unlikely (evaluation of existing UI)
**Plans**: 2

Plans:
- [x] 11.1-01: Critique & audit discovery (run /impeccable critique + audit, compile prioritized fix list)
- [x] 11.1-02: Fix prioritized issues (apply fixes, re-verify scores, visual sign-off)

#### Phase 12: In-App Documentation

**Goal**: Add contextual help text and tooltips on every page, a Getting Started walkthrough for new GSA admins, and a field glossary for water accounting terms
**Depends on**: Phase 11
**Research**: Unlikely (internal content)
**Plans**: TBD

Plans:
- [x] 12-01: Help infrastructure, Getting Started, Glossary, page descriptions, field tooltips

#### Phase 12.1: VanderDev Design Alignment (INSERTED)

**Goal**: Bring OpenH2O's visual polish up to VanderDev standard. Wrap bare tables in card containers, add section headers, punch up dashboard stat cards, tune border visibility and spacing, polish health cards and search bars. CSS + template HTML only, no Python changes.
**Depends on**: Phase 12
**Research**: Unlikely (internal CSS/HTML patterns, existing VanderDev reference)
**Plans**: TBD

Plans:
- [x] 12.1-01: Surface contrast tokens, section labels, stat card accents, health CSS extraction, search icons

#### Phase 13: Cron, Health, & Final Polish

**Goal**: Configure scheduled sync and health check jobs, expand test coverage, verify full deploy cycle on clean VPS
**Depends on**: Phase 12
**Research**: Unlikely (Django management commands, existing health framework)
**Plans**: TBD

Plans:
- [x] 13-01: Crontab, test expansion (28→121), DEPLOY.md consolidation, Butler deploy verified

#### Phase 13.1: AI Operator Guide & District Onboarding (INSERTED)

**Goal**: Rewrite CLAUDE.md so a fresh Claude Code instance can deploy the platform autonomously on a stranger's server. Add an interactive onboarding workflow that collects district boundary, parcels, wells, water rights, stations, periods, allocations, and users by asking questions and orchestrating existing import commands.
**Depends on**: Phase 13
**Research**: Likely (county GIS portal patterns, eWRIMS query automation, CDEC station discovery by boundary)
**Research topics**: Common CA county ArcGIS Hub parcel download formats, eWRIMS API or scrape patterns for boundary-based water rights lookup, best practices for AI-facing CLAUDE.md files
**Plans**: TBD

Plans:
- [ ] 13.1-01: DEFERRED → Phase 20 in v1.2 (AI Operator Guide executes after auto-populate engine is built)

#### Phase 14: Merced Subbasin Demo Data

**Goal**: Replicate ETL pipeline for one Merced irrigation district area; prove platform portability across basins using real data
**Depends on**: Phase 10
**Research**: Likely (different basin data sources)
**Research topics**: Merced SGMA DMS data access (mercedsgma.org), Merced County GIS portal (ArcGIS Hub), Merced-area CDEC/USGS/CIMIS station networks, 2025 GSP monitoring well lists
**Plans**: 1

Plans:
- [ ] 14-01: DEFERRED → Phase 21 in v1.2 (Merced becomes automated deployment test case using auto-populate engine)

### 📋 v1.2 Enhancement Suite (Planned)

**Milestone Goal:** Major platform enhancements across branding, map visualization, content, telemetry, and automated GIS data population. No new infrastructure required; fits existing Docker Compose stack on Butler.

#### Phase 15: Branding & About Page

**Goal**: Generate professional water-themed logo and favicon via LLM Gateway, build About page with purpose statement, policy backstory timeline (AB1755/SGMA/GEARS/CalWATRS/OpenET/Newsom EOs), how-to guides, and organizational credits
**Depends on**: v1.1 complete
**Research**: Unlikely (content sources identified, LLM Gateway image gen available)
**Plans**: 1

Plans:
- [x] 15-01: Contour Basin v2 logo, blue favicon, public About page with policy timeline

#### Phase 16: Tie Lines & Source Fractions

**Goal**: Add GW/SW source-to-POU tie lines on map (yellow for surface water PODs, orange for groundwater wells to parcel centroids), source fraction labels, and combined-use fraction in reporting exports
**Depends on**: Phase 15
**Research**: Unlikely (data model exists: PointOfDiversionParcel, WellIrrigatedParcel; MapLibre line rendering established)
**Plans**: 1

Plans:
- [x] 16-01: Tie-lines GeoJSON endpoint, map layers, fraction-weighted reporting exports

#### Phase 17: Static GIS & Auto-Populate Engine

**Goal**: Bundle county boundaries and Township/Range/Section as static fixtures, build auto_populate management command that queries DWR LightBox statewide parcel FeatureServer, DWR Bulletin 118 groundwater basins, and USGS NLDI for NHD flowlines by boundary polygon
**Depends on**: Phase 16
**Research**: Likely (external API pagination patterns, ArcGIS REST query limits)
**Research topics**: DWR LightBox FeatureServer pagination (1K-2K record limits), USGS NLDI basin delineation API, NHDPlus HR clipping strategies, CNRA PLSS data size/format
**Plans**: TBD

Plans: 3
- [x] 17-01: Auto-populate skeleton + ArcGIS REST client + Bulletin 118 basin step
- [x] 17-02: DWR LightBox parcel auto-population with pagination
- [x] 17-03: USGS 3DHP flowlines + county boundary loading from Census TIGERweb

#### Phase 18: Telemetry Discovery & OpenET

**Goal**: Auto-discover monitoring stations from CDEC, USGS (new OGC API), and CIMIS by boundary bounding box; build OpenET API adapter with aggressive PostGIS caching to stay within 100-400 queries/month limit
**Depends on**: Phase 17
**Research**: Likely (OpenET API auth and rate limits, USGS OGC API migration from legacy NWIS, CDEC servlet parsing patterns)
**Research topics**: OpenET API polygon query format, GEE account linking for higher quotas, CIMIS AppKey registration, USGS api.waterdata.usgs.gov OGC endpoints
**Plans**: TBD

Plans: 1
- [x] 18-01: Station auto-discovery + OpenET cache adapter + USGS groundwater

#### Phase 19: Streaming Dashboard & Setup Wizard

**Goal**: Build VanderDev-quality monitoring dashboard with station cards, sparkline charts, and freshness-colored map markers; add interactive setup wizard at /setup/ for boundary selection and automated data population
**Depends on**: Phase 18
**Research**: Unlikely (HTMX polling patterns established, VanderDev design tokens available, auto_populate engine built in Phase 17)
**Plans**: TBD

Plans: 1
- [x] 19-01: Monitoring dashboard, freshness map, setup wizard, sidebar navigation

#### Phase 19.1: Wizard Fix & Infrastructure Entry (INSERTED)

**Goal**: Fix broken wizard confirm map, build unified infrastructure entry with type-adaptive form, map draw modes, file upload, and parcel linkage.
**Depends on**: Phase 19
**Status**: Complete

Plans: 1
- [x] 19.1-01: Wizard confirm MapLibre fix, infrastructure app, type-adaptive form with map draw

#### Phase 19.2: Visual Overhaul & UX Refinement (INSERTED)

**Goal**: Professional visual overhaul: palette harmonization with logo, shadow/radius alignment to VanderDev Pacific Golden, navigation renaming ("Surface Water"), sidebar reorganization (By Domain structure), and reports page redesign.
**Depends on**: Phase 19.1
**Status**: Complete

Plans: 2
- [x] 19.2-01: Deep Pacific palette, single-source shadows, tighter radii, font weights, Surface Water rename, GEARS/CalWATRS tabs, input styling fixes
- [x] 19.2-02: Reports hero cards, boundary-scoped stations, sidebar reorg deferred

#### Phase 22: Engineering & Mathematics Validation Sweep

**Goal**: Audit and fix all water accounting calculations, unit conversions, and report generation logic. The platform's target users are engineers and water managers who will immediately spot incorrect math. Every formula must be defensible.
**Depends on**: Phase 19.2
**Research**: Likely (verify OpenET API unit conventions, confirm GEARS/CalWATRS field specs, review Rio/Qanat calculation patterns for comparison)
**Research topics**: OpenET API response units (mm vs inches, monthly vs daily granularity), GEARS CSV field specifications from Department of Water Resources, CalWATRS A1/A2 CSV specs from Division of Water Rights, Rio ParcelLedger double-entry patterns for fractional well allocation

**Known issues (verified in code):**

1. **Recharge distribution ignores acreage** (`accounting/services.py:94`): Equal-share division across parcels in a zone. Must be area-weighted: `(parcel_area / total_zone_area) * recharge_volume`. Requires non-null `area_acres` on parcels — include PostGIS auto-calc in this phase as math prerequisite (Phase 23 handles the UI/override flag).

2. **GEARS by-well double-counts extraction** (`reporting/generators.py:67`): `WellIrrigatedParcel.fraction` defaults to 1.0. A well irrigating 3 parcels reports 300% actual extraction. Fix: validate fractions sum to 1.0 per well, add model constraint or normalization.

3. **Diversion ledger skips multi-parcel rights** (`accounting/services.py:40`): Uses `.first()` to pick one parcel from WaterRightParcel. Must distribute using `PointOfDiversionParcel` fractions, like GEARS does for wells.

4. **Dashboard overstates account allocations** (`accounting/views.py:72`): Shows full zone allocation for accounts owning partial zone coverage. Must pro-rate: `zone_allocation * (account_parcels_in_zone / total_parcels_in_zone)`.

5. **CalWATRS/Email JSON crash on null water_right** (`reporting/generators.py:155-156, 265`): `PointOfDiversion.water_right` is nullable but accessed unconditionally. Add null guards; skip or flag rows with missing water rights.

6. **OpenET data never becomes ledger entries**: Adapter caches raw mm values in `OpenETCache` but no pipeline converts to acre-feet and creates `ParcelLedger` entries. Required formula: `-(ET_mm / 304.8) * area_acres` per parcel per month.

7. **CSV import allows wrong-sign entries**: No validation that sign matches `source_type` (meter readings should be negative, allocations positive).

8. **No rounding residual handling**: Decimal division in recharge distribution produces values that may not sum to original total. Standard accounting practice: assign residual to last entry.

9. **OpenET 500mm validation threshold**: Per-record max of 500mm may reject valid annual totals for irrigated Central Valley crops (can exceed 1200mm/year). Threshold must account for temporal granularity.

**Additional sweep items:**
- Verify all unit labels and conversions (AF, CFS, GPM, mm) are consistent and documented
- Confirm `DecimalField` precision is sufficient for all calculations (max_digits, decimal_places)
- Add inline comments citing authoritative formulas (e.g., ET conversion, CFS-to-AF/day = CFS × 1.9835)
- Review allocation plan math: is zone-level allocation the right granularity, or should parcel-level be supported?
- Validate that the `_balance_dict` supply/usage split handles edge cases (zero entries, all-positive, all-negative)

Plans: 2
- [x] 22-01: PostGIS area auto-calc, area-weighted recharge, multi-parcel diversions, dashboard pro-rating, CSV sign validation, _balance_dict edge cases
- [x] 22-02: GEARS fraction normalization, CalWATRS/Email null guards, OpenET threshold, sync_openet_to_ledger, unit audit

#### Phase 23: Navigation Restructure & Naming (UI Overhaul A)

**Goal**: Streamline the sidebar from 5 groups to a cleaner hierarchy. Rename all tabs to domain-accurate names. Move Stations into Water Data, Health into Administration, Water Years into Compliance. Add per-page "Add" and "Import" buttons to Water Data pages. Auto-calculate parcel acreage from PostGIS geometry. Sweep all "DWR" acronyms to full agency names (Department of Water Resources vs Division of Water Rights).
**Depends on**: Phase 22
**Research**: Unlikely (internal template/model changes)
**Plans**: TBD

**Renames:**
- Parcels → Use Areas
- Wells → Extraction Wells
- Surface Water → Surface Diversions
- Recharge → Recharge Areas
- Ledger → Use Ledger
- Periods → Water Years (move to Compliance group)
- Stations → Monitoring Stations (move to Water Data group)
- Health → Site Health (move to Administration group)

**Sidebar target:**
- Overview: Dashboard, Map
- Water Data: Use Ledger, Use Areas, Extraction Wells, Surface Diversions, Recharge Areas, Monitoring Stations
- Compliance: Reports, Water Years
- Administration: Accounts, Allocations, Site Health, Setup Wizard
- Help: Getting Started, Glossary, About

**Infrastructure tab removal:** Add + Import buttons on each Water Data page replace the unified Infrastructure tab. Batch import (GeoJSON/Shapefile/KML) available per page.

**Acreage auto-calc:** Compute `area_acres` from PostGIS `ST_Area` on polygon save. Manual override with `area_override` flag.

**DWR sweep:** Replace all "DWR" with full agency name in templates, adapters, seed data, docs. Department of Water Resources (CDEC, Bulletin 118, SGMA Portal, Water Data Library) vs Division of Water Rights (CalWATRS, eWRIMS, water right permits).

Plans:
- [x] 23-01: Sidebar restructure, 8 renames, Add/Import buttons, area_override, DWR acronym sweep

#### Phase 24: Data Model UX Overhaul (UI Overhaul B)

**Goal**: Redesign the three hardest UX problems: allocation-optional accounting, surface diversions without water rights, and zone management. Make the platform work for agencies that just track water use without formal allocations or water rights data.
**Depends on**: Phase 23
**Research**: Likely (review how Rio/Qanat handle allocation-optional parcels, survey real GSA workflows)
**Research topics**: Rio ParcelLedger pattern for unallocated parcels, Qanat zone management UI, real-world GSA data entry workflows for districts without formal allocations

**Allocation-optional dashboard:**
- Dashboard gracefully handles missing allocations: usage-only view when no AllocationPlan exists
- Prompt "Set allocation to enable budget tracking" instead of broken math
- Zone balance calculations work regardless (sum ledger entries)
- No schema change to AllocationPlan (stays optional by nature)

**Surface Diversions redesign:**
- Lead with PointOfDiversion, not WaterRight (POD already has nullable FK to WaterRight)
- Diversion records (monthly volumes) are primary data entry
- Water right fields (type, priority, face value) become optional expandable "Compliance Details" section
- CalWATRS report generator flags diversions without linked water rights as incomplete

**Zone management UI:**
- New lightweight zone management page under Administration (or within Setup Wizard)
- Zone CRUD with map drawing tool (reuse infrastructure add pattern)
- ParcelZone assignment via map selection or bulk import
- Visible explanation of what zones are and why they matter

Plans:
- [x] 24-01: Allocation-optional dashboard, POD-centric surface diversions, zone management

#### Phase 25: Content & Polish (UI Overhaul C)

**Goal**: Rewrite the About page (professional intro, corrected timeline, impressive credits section), redesign Getting Started guide with page links and modern card layout, sweep all help tooltips for consistency with new names.
**Depends on**: Phase 24
**Research**: Unlikely (content and CSS work, credits research already done)
**Plans**: TBD

**About page:**
- Professional intro paragraph (no sales pitch, no shots at consulting firms)
- Timeline corrections: remove GEARS modernized tile, remove CalWATRS (2025 not 2023), remove Newsom EOs (didn't mention water)
- Credits section with 4 tiers:
  1. Pioneering implementations: Rosedale-Rio Bravo Water Storage District, Twin Platte Natural Resources District
  2. Open-source foundations: Environmental Science Associates, Sitka Technology Group (Qanat/Rio/Zybach), California Water Data Consortium (AB 1755)
  3. Data infrastructure: OpenET (NASA, USGS, Desert Research Institute, Environmental Defense Fund), CDEC, USGS National Water Information System
  4. Technology stack: Django, PostGIS, MapLibre GL JS, HTMX, Docker

**Getting Started guide:**
- Same 8-step content, upgraded presentation
- Clickable links to each referenced page
- Step cards with icons instead of plain numbered list
- Updated terminology to match new tab names

**Help tooltip sweep:**
- Update all tooltips and help text to use new names (Use Areas, Extraction Wells, etc.)
- Ensure consistency with renamed sidebar items

Plans:
- [x] 25-01: About page rewrite, Getting Started redesign, glossary name sweep

#### Phase 20: AI Operator Guide (DEFERRED from v1.1 Phase 13.1)

**Goal**: Rewrite CLAUDE.md so a fresh Claude Code instance can deploy the platform and run the auto-populate setup wizard autonomously. Document the full onboarding flow that the setup wizard (Phase 19) enables.
**Depends on**: Phase 25 (must reflect final UI and corrected math after overhaul)
**Research**: Unlikely (auto-populate engine and setup wizard already built by this point)
**Plans**: 1

Plans:
- [ ] 20-01: TBD (run /gsd:plan-phase 20 to break down)

#### Phase 21: Merced Automated Deployment Test (DEFERRED from v1.1 Phase 14)

**Goal**: Use Merced Subbasin as the end-to-end test case for automated deployment. Run the setup wizard with a Merced GSA boundary, verify auto-populated parcels/basins/stations/NHD, validate OpenET integration, and confirm the full platform works with real data pulled entirely through the auto-populate engine.
**Depends on**: Phase 20
**Research**: Likely (Merced-specific boundary IDs, station coverage verification)
**Research topics**: Merced GSA boundary ID in DWR SGMA portal, expected parcel/station counts for validation
**Plans**: 1

Plans:
- [ ] 21-01: TBD (run /gsd:plan-phase 21 to break down)

#### Phase 26: Geospatial Polish & Monitoring Overhaul

**Goal**: Make every map world-class and get monitoring stations showing real data. Two sub-sections: (A) Visual polish across all 13 maps, (B) monitoring station overhaul with real telemetry.
**Depends on**: Phase 25
**Research**: Unlikely (internal CSS/JS/template work, Chart.js CDN integration)
**Plans**: 1

**Sub-section A — Visual Polish:**
- Shrink main map with breathing room to match site spacing (card container with consistent padding)
- Full font sweep: kill slashed-zero font bleed where Public Sans is not applied (station info card, other elements)
- Unify all map colors into CSS token variables (fix `#D49A2B` vs `#E4A317` gold mismatch across tokens.css, map-engine.js, and 10+ templates)
- Redesign layers panel with collapsible grouped sections (Administrative / Land Use / Infrastructure / Monitoring) and logical ordering
- Fix POD detail pages to use teal (`#4ECDC4`) matching main map instead of gold
- Make coordinate copy toast more visible with brief animation
- Enlarge earth/globe icon slightly for better visibility
- Add ledger source-type pill badges (ET Estimate / Meter Read / Water Budget in distinct colors, keeping green/red positive/negative sign coloring)
- Rename "Allocation" to "Water Budget" across all templates, models, and help text

**Sub-section B — Monitoring Overhaul:**
- Add Chart.js via CDN for real time-series telemetry graphs
- Redesign station detail page with full telemetry chart (parameter selector + date range picker)
- Replace four stat tiles with clearer labels (rename "Fresh" to "Reporting" or add explanatory subtitles)
- Improve station list sparklines (larger, interactive)
- Configure Cloudflare tunnel on Butler for public API access to data adapters
- Wire up CDEC adapter (auth-free) as first live data source
- Test data sync pipeline end-to-end (fetch → stage → publish → sparkline)

Plans: 2
- [x] 26-01: Visual polish — unified color tokens, entity-color bug fixes, font sweep, layer panel redesign, significant figures normalization
- [x] 26-02: Monitoring overhaul — Chart.js telemetry, live CDEC sync (Terminus Dam 87 records), stat labels, freshness map consolidation, 8 bug fixes

#### Phase 27: Data Entry & UX Clarity

**Goal**: Add missing data entry forms and clarify accounting terminology so the platform is self-explanatory to first-time users.
**Depends on**: Phase 26
**Research**: Unlikely (internal template/view/form work)
**Plans**: 0

**Recharge event entry:**
- HTMX-powered inline form on recharge site detail page for creating RechargeEvent records
- On save, auto-call `create_recharge_ledger_entries()` to generate positive ParcelLedger entries immediately
- Also add RechargeMeasurement entry form (water level, flow rate, infiltration rate)

**Ledger source-type differentiation:**
- Color-coded pill badges on ledger entries showing source type (ET Estimate, Meter Read, Water Budget, Recharge, Manual, CSV Import)
- Distinct colors per source type alongside existing green/red sign coloring
- Source type filter on ledger list page

**Terminology clarity:**
- Rename "Allocation" → "Water Budget" across all templates, views, models display names, help text, and glossary
- Add contextual explanations: "Water Budget: the amount assigned to this area for the period" vs "Usage: water consumed via extraction or evapotranspiration"
- Clarify ledger as a balance sheet: budget entries (positive, what you're allowed) vs usage entries (negative, what was consumed)

Plans:
- [ ] 27-01: TBD (run /gsd:plan-phase 27 to break down)

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Infrastructure Scaffold | v1.0 | 1/1 | Complete | 2026-05-23 |
| 2. Core Domain Models | v1.0 | 7/7 | Complete | 2026-05-23 |
| 3. Parcel and Well CRUD with Maps | v1.0 | 4/4 | Complete | 2026-05-24 |
| 4. Water Accounting Engine | v1.0 | 3/3 | Complete | 2026-05-24 |
| 5. External Data Aggregator | v1.0 | 2/2 | Complete | 2026-05-24 |
| 6. State Reporting | v1.0 | 1/1 | Complete | 2026-05-24 |
| 7. Health Check and Maintenance | v1.0 | 1/1 | Complete | 2026-05-24 |
| 8. Deploy, Polish, and Handoff | v1.0 | 3/3 | Complete | 2026-05-24 |
| 9. Schema Fixes & Test Infrastructure | v1.1 | 1/1 | Complete | 2026-05-24 |
| 10. Kaweah Subbasin Demo Data | v1.1 | 1/1 | Complete | 2026-05-25 |
| 11. UI Quality Sweep | v1.1 | 1/1 | Complete | 2026-05-25 |
| 11.1 Impeccable UI Audit | v1.1 | 2/2 | Complete | 2026-05-25 |
| 12. In-App Documentation | v1.1 | 1/1 | Complete | 2026-05-25 |
| 12.1 VanderDev Design Alignment | v1.1 | 1/1 | Complete | 2026-05-25 |
| 13. Cron, Health, & Final Polish | v1.1 | 1/1 | Complete | 2026-05-25 |
| 13.1 AI Operator Guide & Onboarding | v1.1 | 0/? | Deferred → Phase 20 | - |
| 14. Merced Subbasin Demo Data | v1.1 | 0/1 | Deferred → Phase 21 | - |
| 15. Branding & About Page | v1.2 | 1/1 | Complete | 2026-05-25 |
| 16. Tie Lines & Source Fractions | v1.2 | 1/1 | Complete | 2026-05-25 |
| 17. Static GIS & Auto-Populate Engine | v1.2 | 3/3 | Complete | 2026-05-25 |
| 18. Telemetry Discovery & OpenET | v1.2 | 1/1 | Complete | 2026-05-25 |
| 19. Streaming Dashboard & Setup Wizard | v1.2 | 1/1 | Complete | 2026-05-25 |
| 19.1 Wizard Fix & Infrastructure Entry | v1.2 | 1/1 | Complete | 2026-05-25 |
| 19.2 Visual Overhaul & UX Refinement | v1.2 | 2/2 | Complete | 2026-05-26 |
| 22. Engineering & Math Validation | v1.2 | 2/2 | Complete | 2026-05-27 |
| 23. Navigation Restructure & Naming | v1.2 | 1/1 | Complete | 2026-05-27 |
| 24. Data Model UX Overhaul | v1.2 | 1/1 | Complete | 2026-05-27 |
| 25. Content & Polish | v1.2 | 1/1 | Complete | 2026-05-28 |
| 20. AI Operator Guide | v1.2 | 0/1 | Not started | - |
| 21. Merced Automated Deployment Test | v1.2 | 0/1 | Not started | - |
| 26. Geospatial Polish & Monitoring Overhaul | v1.2 | 2/2 | Complete | 2026-05-28 |
| 27. Data Entry & UX Clarity | v1.2 | 0/1 | Not started | - |
