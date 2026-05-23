# Open Water Accounting Platform

## What This Is

An AI-deployable water accounting platform for California Groundwater Sustainability Agencies (GSAs) and water districts. A poorly-funded agency buys a frontier AI subscription, points it at this GitHub repo and a $15/mo VPS, and the AI stands the platform up. Handles groundwater extraction, surface water diversions, mixed-use accounting, and groundwater recharge tracking with optional state reporting to the Water Board.

## Core Value

Access is the product, not features. A $15/mo VPS replaces a $35K-$75K consulting engagement. If nothing else works, this must: a non-technical water district manager can deploy and operate the platform with AI assistance alone.

## Requirements

### Validated

(None yet -- ship to validate)

### Active

- [ ] Docker Compose stack boots Django/PostGIS/Caddy with auto-HTTPS
- [ ] 48-table schema across 11 Django apps covering all 4 water domains
- [ ] Parcel and well CRUD with MapLibre GL JS map (import via GeoJSON/Shapefile)
- [ ] ParcelLedger double-entry water accounting (supply positive, usage negative)
- [ ] Water account management with allocation tracking and budget dashboards
- [ ] Surface water rights, points of diversion, diversion records, curtailment orders
- [ ] Managed aquifer recharge sites with event tracking
- [ ] 8 external data adapters (CDEC, USGS, OpenET, CIMIS, CNRFC, DWR WDL, DWR SGMA, NOAA)
- [ ] Geographic station discovery and curation workflow
- [ ] GEARS CSV generation (per-well and per-parcel ET methods)
- [ ] CalWATRS CSV generation (A1 and A2 templates)
- [ ] Email+JSON alternative reporting pathway via Power Automate
- [ ] Health check system (8 categories, green/yellow/red, /health JSON endpoint)
- [ ] django-allauth authentication: email/password login, password reset, optional Google OAuth
- [ ] AI-consumable DEPLOY.md with copy-paste commands and verification at every step
- [ ] Demo fixture data for pilot testing

### Out of Scope

- Multi-tenancy -- single-tenant by design, one VPS per agency
- Real-time telemetry (LoRaWAN/SCADA/webhook) -- external data is daily batch, not streaming
- Mobile app -- responsive web only
- Celery/Redis task queue -- management commands + cron on a 2-4GB VPS
- Node.js build tooling -- Tailwind standalone binary, HTMX/MapLibre via CDN
- State database connections -- local-first, government-optional
- CalWATRS API integration -- no public API exists yet, CSV upload only
- GETEngine/MODFLOW integration -- Olsson repo has no license

## Context

California has ~200 GSAs managing 94 basins under SGMA (the Sustainable Groundwater Management Act, 2014). The only existing digital platform is ESA's GAP, which runs on .NET/SQL Server/Azure. Zero community forks despite AGPL license -- the stack is the barrier. 40% of small water systems use zero digital monitoring.

Design informed by deep analysis of 3 ESA community repos:
- **Qanat** (126 tables) -- multi-tenant CA groundwater accounting
- **Zybach** (85 tables) -- TPNRD Nebraska telemetry (daily batch InfluxDB, not real-time)
- **Rio** (51 tables) -- Rosedale prototype, best OpenET code, water trading

Key patterns adopted: ParcelLedger double-entry (Rio), configurable measurement types (Qanat), staging-then-publish upserts (Zybach), OpenET 3-stage pipeline (Rio), dual SRID geospatial (all three).

DWR has a 5yr/$10M MSA with CA Water Data Consortium. ~$500K available for Merced expansion.

### Key files

- Build plan: `~/Documents/Work/Deliverables/open-water-platform-build-plan-2026-05-21.md`
- Ecosystem evaluation: `~/Documents/Work/Research/gap-platform-ecosystem-evaluation-2026-05-19.md`
- Strategy document: `~/Documents/Work/Deliverables/open-water-accounting-platform-fork-strategy-2026-05-12.md`
- Lifecycle support plan: `~/Documents/Work/Deliverables/open-water-platform-lifecycle-support-plan-2026-05-19.md`
- ESA repos: `~/GitHub/esassoc/{qanat-community,zybach-community,rio}`
- VanderDev design system: `~/GitHub/vanderoffice/VanderDev-Website/{DESIGN.md,DESIGN.json,tailwind.config.js}`
- Map engine: `~/.claude/skills/gis-map/assets/{map-engine.js,map-engine.css}`

## Constraints

- **Stack**: Django 5 + GeoDjango, PostgreSQL 16 + PostGIS 3.4, Caddy, Docker Compose, HTMX, Tailwind Standalone, MapLibre GL JS -- locked, no substitutions
- **Deploy target**: Butler server (192.168.0.114) via Cloudflare Tunnel at openh2o.com
- **Resource ceiling**: Must run on 2-4GB RAM VPS ($15/mo). No Celery, no Redis, Gunicorn 2 workers
- **AI-deployable**: Every step in DEPLOY.md must be copy-pasteable with verification. Zero ambiguity
- **Design**: VanderDev OKLCH token system (dark mode, California Gold accent, pop shadows, Public Sans + JetBrains Mono)
- **OpenET API key**: Must be requested from openetdata.org before Phase 5 (lead time unknown)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Single-tenant over multi-tenant | Simplest security, simplest deployment, each agency owns their data | -- Pending |
| Django templates + HTMX over SPA | Zero Node.js, one build system, AI deploys in one pass | -- Pending |
| Management commands + cron over Celery | 2-4GB VPS constraint, simpler stack | -- Pending |
| Staging-then-publish for external data | Never write directly to production from external sources (Zybach pattern) | -- Pending |
| Email+JSON over portal API for state reporting | GEARS/CalWATRS have no APIs; Power Automate on state side is FedRAMP-authorized | -- Pending |
| django-allauth for auth | Password reset built-in, Google OAuth for agencies on Google Workspace, per-agency toggle | -- Pending |
| Caddy over Nginx | Auto-renewing HTTPS, smaller memory footprint | -- Pending |
| openh2o.com domain | Short, memorable, matches repo name | -- Pending |

---
*Last updated: 2026-05-23 after initialization*
