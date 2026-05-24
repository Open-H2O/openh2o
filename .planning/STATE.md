# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-23)

**Core value:** Access is the product, not features. A $15/mo VPS replaces a $35K-$75K consulting engagement.
**Current focus:** Phase 2 -- Core Domain Models

## Current Position

Phase: 2 of 8 (Core Domain Models)
Plan: 4 of 7 in current phase
Status: In progress
Last activity: 2026-05-23 -- Completed 02-03 and 02-04 (batched)

Progress: █████░░░░░ 38%

## Performance Metrics

**Velocity:**
- Total plans completed: 5
- Average duration: 14 min
- Total execution time: 1.1 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 Infrastructure Scaffold | 1 | 50 min | 50 min |
| 02 Core Domain Models | 4 | 14 min | 3.5 min |

**Recent Trend:**
- Last 5 plans: 50 min, 2 min, 3 min, 4 min, 5 min
- Trend: Phase 2 plans averaging 3.5 min (mechanical model creation)

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
- All migrations generated in single pass (no circular FK issues)
- Pillow added to pyproject.toml for ImageField support
- Butler deploy key is read-only; migrations generated on Butler, committed locally
- django-allauth deprecation warnings noted (non-blocking, address in 02-06)

### Deferred Issues

None.

### Blockers/Concerns

- OpenET API key not yet requested (needed by Phase 5)

## Session Continuity

Last session: 2026-05-23
Stopped at: Completed 02-04-PLAN.md (4 of 7 plans in Phase 2)
Resume file: None
