# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-24)

**Core value:** Access is the product, not features. A $15/mo VPS replaces a $35K-$75K consulting engagement.
**Current focus:** v1.0 shipped. Planning next milestone.

## Current Position

Phase: 19.2 of 21 (Visual Overhaul & UX Refinement)
Plan: 2 of 2 in current phase
Status: Phase complete + post-phase sidebar/infrastructure redesign
Last activity: 2026-05-26 - Sidebar redesign, infrastructure list redesign, Butler deploy fixes

Progress: ████████████ 96%

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

### Deferred Issues

- ISSUE-005: Infrastructure add page "Select on map" and "Draw new parcel" buttons are dead (no JS wired). Needs: parcel GeoJSON endpoint on map, polygon draw mode for new parcels, parcel click selection. See handoff doc.

### Open Items for Next Milestone

- OpenET API key not yet requested (needed for live adapter testing)
- Automated test suite established (28 tests, pytest + factory_boy)
- Cron scheduling configured: sync_all (daily 2AM mock), run_health_checks (6-hourly), prune_old_data (monthly)
- Test suite expanded to 121 tests (from 28)

### Roadmap Evolution

- Milestone v1.1 created: Production Polish, 6 phases (Phase 9-14)
- Phase 11.1 inserted after Phase 11: Impeccable UI Audit (critique + audit before docs)
- Phase 11.1-01: fix-all decision (21 issues: 7 P1, 8 P2, 6 P3)
- Phase 12.1 inserted after Phase 12: VanderDev Design Alignment (CSS + template polish)
- Milestone v1.2 created: Enhancement Suite, 5 phases (Phase 15-19) — branding, map tie lines, GIS auto-populate, telemetry/OpenET, streaming dashboard
- Phase 19.1 inserted: Wizard fix + infrastructure entry (type-adaptive form, map draw, file upload, parcel linkage)

## Session Continuity

Last session: 2026-05-26
Stopped at: Sidebar redesign shipped (task-based groupings). Infrastructure list redesigned (stat cards, type filters, richer cards). Butler deploy pipeline fixed (SSH alias, stale branch, Docker volume). Infrastructure add page map buttons still broken (deferred).
Resume file: ~/Documents/Work/SWRCB-Ops/handoff-infra-map-buttons-2026-05-26.md
