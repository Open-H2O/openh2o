---
phase: 13-cron-health-polish
plan: 01
subsystem: infra, testing
tags: [cron, pytest, factory-boy, health-checks, django-management-commands]

requires:
  - phase: 09-schema-fixes-test-infra
    provides: pytest + factory_boy infrastructure, 28 baseline tests
  - phase: 07-health-check-maintenance
    provides: 8 health check functions, health dashboard
  - phase: 08-deploy-polish-handoff
    provides: management commands, DEPLOY.md, Makefile

provides:
  - Installable crontab with 3 scheduled jobs (sync, health, prune)
  - 121-test suite covering health checks, views, and management commands
  - Consolidated deployment docs with cron and test sections

affects: [13.1-ai-operator-guide, 14-merced-demo-data]

tech-stack:
  added: []
  patterns: [crontab-variable-for-deploy-path, inline-UserFactory-in-test-views]

key-files:
  created: [crontab.txt, tests/test_health_checks.py, tests/test_views.py, tests/test_management_commands.py]
  modified: [Makefile, DEPLOY.md, static/css/app.css, .planning/PROJECT.md]

key-decisions:
  - "Used OPENH2O_DIR crontab variable for portable deploy paths across machines"
  - "Shifted health WARNING badge from orange (furnace-400) to yellow (--color-warning) for visual separation from CRITICAL"

patterns-established:
  - "Crontab append pattern: (crontab -l; cat crontab.txt) | crontab - preserves existing entries"
  - "View smoke tests: force_login + reverse() for every authenticated page, 302 assertions for anonymous"

issues-created: []

duration: 105min
completed: 2026-05-25
---

# Phase 13 Plan 1: Cron, Health, & Final Polish Summary

**Installable crontab with 3 scheduled jobs, test suite expanded from 28 to 121 tests, and consolidated deploy docs with warning badge color fix**

## Performance

- **Duration:** 105 min
- **Started:** 2026-05-25T14:24:00Z
- **Completed:** 2026-05-25T16:09:19Z
- **Tasks:** 4 (3 auto + 1 checkpoint)
- **Files modified:** 8

## Accomplishments

- Created crontab.txt with 3 scheduled jobs: daily data sync (mock mode), 6-hourly health checks, monthly data pruning
- Added Makefile targets: install-cron, show-cron, sync, and updated test target to use pytest
- Expanded test suite from 28 to 121 tests across 3 new modules (health checks, view smoke tests, management commands)
- Consolidated DEPLOY.md Section 11 with "Scheduled Jobs" subsection referencing crontab.txt
- Deployed and verified on Butler: all tests green, cron installed, health checks returning 8 categories
- Fixed health WARNING badge color from orange to yellow for better visual distinction from CRITICAL

## Task Commits

Each task was committed atomically:

1. **Task 1: Crontab + Makefile targets** - `b5805d9` (feat)
2. **Task 2: Health, view, and command tests** - `159444d` (test)
3. **Task 3: DEPLOY.md consolidation + PROJECT.md updates** - `ad4ac08` (docs)
4. **Task 4: Checkpoint** - deployed on Butler, verified 121 tests passing, cron installed
5. **Deviation fix: Warning badge color** - `5b16037` (fix)

## Files Created/Modified

- `crontab.txt` - 3 scheduled cron entries with OPENH2O_DIR variable
- `tests/test_health_checks.py` - 44 tests for all 8 health check functions
- `tests/test_views.py` - 30 view smoke tests with UserFactory
- `tests/test_management_commands.py` - 19 management command smoke tests
- `Makefile` - install-cron, show-cron, sync targets; pytest test target
- `DEPLOY.md` - Consolidated Scheduled Jobs, Data Sync, Running Tests sections
- `static/css/app.css` - Warning badge color shifted to yellow
- `.planning/PROJECT.md` - Checked off cron and test requirements

## Decisions Made

- Used OPENH2O_DIR crontab variable so the same file works across deploy paths (adjusted to /home/butler/openh2o on Butler during install)
- Shifted warning badge from --furnace-400 (orange, hue 50) to --color-warning (yellow, hue 85) per user feedback during checkpoint

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] parcel_create and well_create URL names don't exist**
- **Found during:** Task 2 (view smoke tests)
- **Issue:** Plan listed parcel_create and well_create as URL names to test, but those views/URLs don't exist in the codebase
- **Fix:** Tested actual parcel and well list views plus detail views using factory-created objects instead
- **Verification:** All view tests pass
- **Committed in:** 159444d (Task 2 commit)

**2. [User feedback] Warning badge too similar to Critical**
- **Found during:** Task 4 checkpoint (user screenshot)
- **Issue:** WARNING badge used furnace-400 (orange) which was too close to CRITICAL (red) in hue
- **Fix:** Changed to --color-warning (#fbbf24, yellow) with OKLCH background hue shifted from 50 to 85
- **Verification:** chrome-devtools computed styles + screenshot confirmed distinct colors
- **Committed in:** 5b16037

---

**Total deviations:** 1 auto-fixed (missing URLs), 1 user-requested (badge color). No scope creep.

## Issues Encountered

- Named Docker volume `static_files` overrides build-time collectstatic output at runtime. Required manual `collectstatic --clear` inside the running container + restart to pick up CSS changes. Same pattern as Phase 12.1.

## Next Phase Readiness

- Phase 13 complete (single-plan phase)
- Platform is operationally self-sustaining: automated sync, health monitoring, data pruning
- 121 tests provide regression safety for future changes
- Ready for Phase 13.1 (AI Operator Guide & District Onboarding)

---
*Phase: 13-cron-health-polish*
*Completed: 2026-05-25*
