# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-23)

**Core value:** Access is the product, not features. A $15/mo VPS replaces a $35K-$75K consulting engagement.
**Current focus:** Phase 2 -- Core Domain Models

## Current Position

Phase: 2 of 8 (Core Domain Models)
Plan: 2 of 7 in current phase
Status: In progress
Last activity: 2026-05-23 -- Completed 02-02-PLAN.md

Progress: ███░░░░░░░ 20%

## Performance Metrics

**Velocity:**
- Total plans completed: 3
- Average duration: 18 min
- Total execution time: 0.9 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 Infrastructure Scaffold | 1 | 50 min | 50 min |
| 02 Core Domain Models | 2 | 5 min | 2.5 min |

**Recent Trend:**
- Last 5 plans: 50 min, 2 min, 3 min
- Trend: --

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Removed hardcoded GDAL/GEOS paths from Dockerfile; Django finds them automatically
- Created minimal User model stub; AUTH_USER_MODEL requires resolvable model at boot
- Butler deploy key added to GitHub for SSH clone access
- SiteConfig singleton via save() ValidationError, not metaclass
- Cross-app FKs use string references for deferred migration resolution
- Zone zone_type: CharField with choices, not separate lookup table

### Deferred Issues

None.

### Blockers/Concerns

- OpenET API key not yet requested (needed by Phase 5)

## Session Continuity

Last session: 2026-05-23
Stopped at: Completed 02-02-PLAN.md (2 of 7 plans in Phase 2)
Resume file: None
