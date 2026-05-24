---
phase: 02-core-domain-models
plan: 07
subsystem: database
tags: [django, management-commands, seed-data, get_or_create]

requires:
  - phase: 02-core-domain-models (plans 01-06)
    provides: All 48 models with migrations, admin registration, auth templates
provides:
  - Idempotent seed commands for all reference data (32 records total)
  - seed_data umbrella command for one-step population
affects: [03-parcel-well-crud, 05-external-data-aggregator, 06-state-reporting]

tech-stack:
  added: []
  patterns: [idempotent-seed-commands, get_or_create-pattern, umbrella-management-command]

key-files:
  created:
    - core/management/commands/seed_roles.py
    - core/management/commands/seed_data.py
    - accounting/management/commands/seed_water_types.py
    - surface/management/commands/seed_water_right_types.py
    - wells/management/commands/seed_well_types.py
    - datasync/management/commands/seed_data_sources.py
    - reporting/management/commands/seed_report_templates.py
  modified: []

key-decisions:
  - "get_or_create keyed on unique field (code or name) for idempotency"
  - "Umbrella seed_data command uses call_command for clean stdout chaining"

patterns-established:
  - "Seed command pattern: CONSTANT list + get_or_create loop + created/existing counter"

issues-created: []

duration: 14min
completed: 2026-05-23
---

# Phase 2 Plan 7: Seed Data Commands Summary

**6 idempotent seed commands populating 32 reference records (roles, water types, right types, well types, data sources, report templates) plus umbrella seed_data command**

## Performance

- **Duration:** 14 min
- **Started:** 2026-05-24T01:14:33Z
- **Completed:** 2026-05-24T01:28:49Z
- **Tasks:** 3 (2 auto + 1 checkpoint)
- **Files modified:** 19

## Accomplishments
- 6 seed commands across 5 apps, all idempotent via get_or_create
- 32 reference records: 3 roles, 6 water types, 6 water right types, 4 well types, 8 data sources, 5 report templates
- seed_data umbrella runs all seeds in one command
- Full Phase 2 verified on Butler: 48 models, admin, auth, seed data all working

## Task Commits

Each task was committed atomically:

1. **Task 1: seed_roles command** - `693b1e2` (feat)
2. **Task 2: all remaining seed commands + umbrella** - `31fc5ed` (feat)
3. **Task 3: human verification on Butler** - checkpoint (no commit)

## Files Created/Modified
- `core/management/commands/seed_roles.py` - Seeds admin/manager/viewer roles
- `core/management/commands/seed_data.py` - Umbrella command calling all 6 seeds
- `accounting/management/commands/seed_water_types.py` - 6 water types (GW, SW, RW, ST, IW, MX)
- `surface/management/commands/seed_water_right_types.py` - 6 CA water right types with legal descriptions
- `wells/management/commands/seed_well_types.py` - 4 well types
- `datasync/management/commands/seed_data_sources.py` - 8 external data APIs with URLs and auth types
- `reporting/management/commands/seed_report_templates.py` - 5 state reporting templates
- 12 `__init__.py` files for management command package structure

## Decisions Made
- Keyed get_or_create on unique fields (code for most, name for roles/well types) rather than name, so display names can change without creating duplicates
- Umbrella seed_data uses Django's call_command rather than subprocess for clean stdout handling

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Auto-push hook did not fire; commits had to be pushed manually before Butler could pull
- User needed to create superuser before admin verification (not a code issue)

## Next Phase Readiness
- Phase 2 complete: 48 models, admin, auth flow, seed data all verified on Butler
- Ready for Phase 3: Parcel and Well CRUD with Maps
- No blockers

---
*Phase: 02-core-domain-models*
*Completed: 2026-05-23*
