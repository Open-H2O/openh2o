# Roadmap: Open Water Accounting Platform

## Overview

Stand up an AI-deployable water accounting platform from scratch. Start with Docker infrastructure, build the 48-table domain model, add spatial CRUD and maps, wire up the accounting engine and external data feeds in parallel, layer on state reporting, add health monitoring, then polish the DEPLOY.md until an AI can stand the whole thing up on a fresh VPS unassisted.

## Milestones

- ✅ **v1.0 MVP** — Phases 1-8 (shipped 2026-05-24)
- 🚧 **v1.1 Production Polish** — Phases 9-14 (in progress)

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
- [ ] 13.1-01: TBD (run /gsd:plan-phase 13.1 to break down)

#### Phase 14: Merced Subbasin Demo Data

**Goal**: Replicate ETL pipeline for one Merced irrigation district area; prove platform portability across basins using real data
**Depends on**: Phase 10
**Research**: Likely (different basin data sources)
**Research topics**: Merced SGMA DMS data access (mercedsgma.org), Merced County GIS portal (ArcGIS Hub), Merced-area CDEC/USGS/CIMIS station networks, 2025 GSP monitoring well lists
**Plans**: 1

Plans:
- [ ] 14-01: Merced Subbasin seed data with real DWR boundaries and Merced County parcels

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
| 13.1 AI Operator Guide & Onboarding | v1.1 | 0/? | Not started | - |
| 14. Merced Subbasin Demo Data | v1.1 | 0/1 | Planned | - |
