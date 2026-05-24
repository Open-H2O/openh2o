# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-23)

**Core value:** Access is the product, not features. A $15/mo VPS replaces a $35K-$75K consulting engagement.
**Current focus:** Phase 2 -- Core Domain Models

## Current Position

Phase: 2 of 8 (Core Domain Models)
Plan: 6 of 7 in current phase
Status: In progress
Last activity: 2026-05-23 -- Completed 02-05 and 02-06 (batched)

Progress: ███████░░░ 50%

## Performance Metrics

**Velocity:**
- Total plans completed: 7
- Average duration: 11 min
- Total execution time: 1.3 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 Infrastructure Scaffold | 1 | 50 min | 50 min |
| 02 Core Domain Models | 6 | 25 min | 4.2 min |

**Recent Trend:**
- Last 5 plans: 3 min, 4 min, 5 min, 5 min, 6 min
- Trend: Phase 2 averaging 4.2 min/plan (mechanical Django work)

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
- django-allauth deprecation warnings fixed in 02-06 (ACCOUNT_LOGIN_METHODS/ACCOUNT_SIGNUP_FIELDS)
- django.contrib.sites added; django_site table created manually to fix migration ordering
- SiteConfig exposed to templates via context processor (not template tag)

### Deferred Issues

None.

### Blockers/Concerns

- OpenET API key not yet requested (needed by Phase 5)

## Session Continuity

Last session: 2026-05-23
Stopped at: Completed 02-06-PLAN.md (6 of 7 plans in Phase 2)
Resume file: None
