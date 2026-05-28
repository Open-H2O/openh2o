# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-24)

**Core value:** Access is the product, not features. A $15/mo VPS replaces a $35K-$75K consulting engagement.
**Current focus:** v1.0 shipped. Planning next milestone.

## Current Position

Phase: 28 of 28 COMPLETE — Phase 27 also COMPLETE (2/2 plans)
Plan: 27-02 complete (Allocation → Water Budget rename, deployed + verified)
Status: openh2o.com LIVE and publicly reachable (DNS fixed this session). All planned phases done.
Last activity: 2026-05-28 - Completed 27-02 (Water Budget rename) + fixed openh2o.com public DNS.

Progress: ███████████████ 100%

## Performance Metrics

**v1.0 MVP totals:**
- Total plans completed: 22
- Total execution time: ~5 hours code work (across 2 days)
- Files: 292 created/modified
- Lines: ~48,000 Python
- Commits: 123

## Accumulated Context

### Decisions

All decisions logged in PROJECT.md Key Decisions table.
All marked ✓ Good after v1.0 validation.

| Phase | Decision | Rationale |
|-------|----------|-----------|
| 26-01 | Public Sans + tabular-nums for numeric data | Eliminates slashed-zero font bleed while keeping column alignment |
| 26-01 | OH2O.colors JS global for MapLibre | CSS vars can't be used in MapLibre paint properties; JS object is the bridge |
| 26-01 | floatformat:2 as standard precision | Water accounting values don't need 4 decimal places |
| 26-02 | DATASYNC_MOCK_MODE default=False | Live API calls are the norm; mock is opt-in |
| 26-02 | Removed boundary filter from station list | Watershed stations in foothills must be visible |
| 26-02 | Deleted 21 non-Kaweah stations | Demo scoped to Kaweah subbasin only |
| 26.1-01 | DWR adapters rewritten for CNRA CKAN API | Original WDL and SGMA endpoints decommissioned (404) |
| 26.1-01 | Lazy importlib in parameter registry | Avoids circular imports with adapter registration |
| 26.1-01 | CIMIS deferred (ISS-007) | Works without it; OpenET provides ET data |
| 27-01 | Inline entry form lives inside its HTMX-swapped partial | Lets validation errors + typed values survive the swap |
| 27-01 | Catch ValueError from ledger service vs pre-checking zone | Service is single source of truth for the zone rule |
| 27-01 | Measurement entry form pulled (user decision) | Defer until production shows whether districts want manual measurement entry |
| 28-01 | Public URL = openh2o.com apex; app-login only; single environment (no staging) | Demo site, no real users; 186-test suite is the deploy gate |
| 28-01 | Cloudflare Tunnel (no exposed ports) on Butler | Home-hosted; outbound-only connection keeps the network closed |

### Deferred Issues

- ~~Map buttons: Infrastructure add page "Select on map" and "Draw new parcel" wired up. Commits 9c183b5, 70eabc5. Deployed to Butler.~~

### Open Items for Next Milestone

- OpenET API key not yet requested (needed for live adapter testing)
- Automated test suite established (28 tests, pytest + factory_boy)
- Cron scheduling configured: sync_all (daily 2AM mock), run_health_checks (6-hourly), prune_old_data (monthly)
- Test suite expanded to 186 tests (from 121 pre-Phase 22, originally 28)

### Roadmap Evolution

- Milestone v1.1 created: Production Polish, 6 phases (Phase 9-14)
- Phase 11.1 inserted after Phase 11: Impeccable UI Audit (critique + audit before docs)
- Phase 11.1-01: fix-all decision (21 issues: 7 P1, 8 P2, 6 P3)
- Phase 12.1 inserted after Phase 12: VanderDev Design Alignment (CSS + template polish)
- Milestone v1.2 created: Enhancement Suite, 5 phases (Phase 15-19) — branding, map tie lines, GIS auto-populate, telemetry/OpenET, streaming dashboard
- Phase 19.1 inserted: Wizard fix + infrastructure entry (type-adaptive form, map draw, file upload, parcel linkage)
- Phase 22 added: Engineering & Mathematics Validation Sweep (9 known issues in accounting/reporting math)
- Phases 23-25 added: Comprehensive UI Overhaul (navigation/naming, data model UX, content/polish). Phases 20-21 depend on 25 completing first.
- Phase 26 added: Geospatial Polish & Monitoring Overhaul (map visual polish + monitoring station telemetry + Cloudflare tunnel)
- Phase 27 added: Data Entry & UX Clarity (recharge event form, ledger source badges, "Allocation" → "Water Budget" rename)
- Phase 26.1 inserted after Phase 26: Monitoring Completion (URGENT) — wire USGS/DWR WDL/DWR SGMA/CIMIS adapters, fix chart labels/units, audit monitoring pages. Covers ISS-006 through ISS-010.

## Session Continuity

Last session: 2026-05-28
Stopped at: Completed 27-02 (Allocation→Water Budget rename, deployed to Butler, 186 tests pass, verified rendering). Phase 27 complete. ALSO fixed openh2o.com public DNS: it was serving Hostinger's parked page because the home network's PRIMARY DNS (NetSentry, 192.168.0.113) had stale data at two layers — Unbound cached Hostinger's old nameserver delegation, and Pi-hole/FTL cached the old IP. Cloudflare DNS record (CNAME→tunnel, proxied), the tunnel, and ALL public resolvers were correct the whole time. Fix: `unbound-control flush_zone openh2o.com` + `sudo systemctl restart pihole-FTL` on NetSentry (NOT Butler's Pi-hole — Butler forwards to 1.1.1.1 and was already correct). Site verified live from Mac + public resolvers.
Open items: ISS-011 (login page visual polish — user called it bare/ugly, wants it fixed), ISS-012 (rotate default Postgres password 'openh2o'), ISS-013 (pre-existing datasync/recharge migration drift). Next roadmap phase: Phase 20 (AI Operator Guide).
Resume file: None
Resume file: None
