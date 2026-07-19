---
phase: 78-drinking-core
plan: 01
subsystem: database
tags: [django, postgis, drinking-water, sdwis, ddw, epa-npdwr, module-registry, pytest, factory-boy]

# Dependency graph
requires:
  - phase: 77-module-config-layer
    provides: MODULE_REGISTRY / ModuleSpec, OPENH2O_MODULES composing INSTALLED_APPS, the droppability pins in tests/test_modules.py and tests/test_module_template_guards.py
provides:
  - "`drinking` Django app with the seven spine models and its initial migration"
  - "SampleResult.result_kind enforced by clean() AND two DB CheckConstraints"
  - "SystemFacility.well FK — the quality-to-quantity join into wells.Well"
  - "Registered, droppable `drinking` ModuleSpec (apps-only; no URLs or nav yet)"
  - "seed_drinking: 33 analytes + 32 EPA-verified federal NPDWR limits, idempotent"
  - "Seven factories in tests/factories.py and 35 tests in tests/test_drinking_models.py"
affects: [78-02, 78-03, drinking-water-csv-import, pwsid-onboarding, ear-survey-engine]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Published-vocabulary-only code lists, each annotated with its source table"
    - "Kind-discriminated results (result_kind) enforced at both the form and DB layer"
    - "Optional seed commands gated on module_enabled in core's seed_data umbrella"

key-files:
  created:
    - drinking/models.py
    - drinking/admin.py
    - drinking/migrations/0001_initial.py
    - drinking/management/commands/seed_drinking.py
    - tests/test_drinking_models.py
  modified:
    - core/modules.py
    - core/management/commands/seed_data.py
    - tests/factories.py
    - tests/test_modules.py
    - tests/test_module_template_guards.py

key-decisions:
  - "effective_start = 2000-01-01 as an explicit administrative placeholder wherever EPA publishes no date; arsenic (2006-01-23) and uranium (2003-12-08) use the dates the source states"
  - "Every seeded ddw_code is NULL — no published DDW analyte-code list exists in the reference set, so 78-03's importer must build the crosswalk from the state's own CSV files"
  - "facility_type carries 22 codes: the DDW dictionary's 21 plus federal WH"
  - "pws_type uses the federal SDWA codes CWS/NTNCWS/TNCWS, not the schema draft's CWS/NTNC/TNC shorthand"
  - "E. coli is seeded as an analyte with no RegulatoryLimit — EPA publishes no numeric MCL for it"

patterns-established:
  - "Every code list constant names the published table it was transcribed from, in a comment directly above it"
  - "tests/test_modules.py keeps HISTORICAL_LOCAL_APPS unedited and appends to a new DEFAULT_LOCAL_APPS, so parity and growth stay separately assertable"

issues-created: []

# Metrics
duration: 88min
completed: 2026-07-19
---

# Phase 78-01: Drinking Water Core Models Summary

**Seven-model `drinking` spine (WaterSystem → SampleResult) with SDWIS/DDW-transcribed vocabularies, a presence/absence discriminator enforced in the database, and 32 EPA-verified federal NPDWR limits behind an idempotent seed command.**

## Performance

- **Duration:** ~88 min
- **Started:** 2026-07-19T14:18:57-0700 (from HEAD `be3d6ba`)
- **Completed:** 2026-07-19T15:46:13-0700
- **Tasks:** 5
- **Files modified:** 13 (8 created, 5 modified)

## Accomplishments

- The `drinking` app exists with all seven spine models per schema draft §1.1–§1.2, minus the two deviations approved at plan time (`SampleResult.submission`, `MonitoringScheduleItem`), and its migration applies cleanly on staging.
- A presence/absence result is now *unrepresentable* as a number. `result_kind` is enforced in `clean()` for the admin path and by two `CheckConstraint`s for the import path — the tests prove the second by bypassing validation with a raw `.save()`.
- `drinking` is registered as the first genuinely droppable Phase-78-era module. Booting with `OPENH2O_MODULES` omitting it passes `manage.py check`, plans no drinking migrations, and makes `seed_data` skip `seed_drinking`.
- `seed_drinking` loads 33 analytes and 32 regulatory limits, every value transcribed from EPA's published NPDWR table at execution time. Re-running creates zero rows.
- Suite grew from 1048 to 1084 passing with zero regressions.

## Task Commits

1. **Task 1: seven spine models + migrations** — `2fd1980` (feat)
2. **Task 2: admin registrations + test factories** — `00ede0f` (feat)
3. **Task 3: module-registry registration** — `3b29485` (feat)
4. **Task 4: seed_drinking + umbrella wiring** — `fa7bfc5` (feat)
5. **Task 5: model, versioning and droppability tests** — `1b8d2de` (test)

## Files Created/Modified

- `drinking/models.py` — The seven models plus the published code-list constants each model draws its choices from.
- `drinking/admin.py` — CRUD backstop for all seven, in the house admin style, until 78-02 ships real pages.
- `drinking/migrations/0001_initial.py` — Initial schema, including the two `SampleResult` check constraints.
- `drinking/management/commands/seed_drinking.py` — The federal analyte + limit seed, with EPA's verbatim cell text quoted beside every non-obvious value.
- `core/modules.py` — `drinking` ModuleSpec at the end of app order: `requires=("wells", "standards")`, `required=False`, `seed_commands=("seed_drinking",)`.
- `core/management/commands/seed_data.py` — New `OPTIONAL_SEED_COMMANDS` list, gated on `is_enabled()`.
- `tests/factories.py` — Seven drinking factories.
- `tests/test_drinking_models.py` — 35 tests.
- `tests/test_modules.py`, `tests/test_module_template_guards.py` — Pinned literals updated deliberately.

## Decisions Made

**`effective_start` placeholder (78-03 depends on this).** EPA's NPDWR table states an effective date for exactly two of the seeded standards — arsenic ("0.010 as of 01/23/06" → `2006-01-23`) and uranium ("30 ug/L as of 12/08/03" → `2003-12-08`). Both use the stated date. Every other limit uses `2000-01-01` as an **explicit administrative placeholder**, documented in the command's module docstring. `RegulatoryLimit`'s versioning semantics only need *a* start so "the limit on date D" resolves to one row; inventing a per-rule promulgation date would be a worse lie than an obviously round placeholder. Correcting these later is a data edit, not a schema change. **An importer must never treat `2000-01-01` as a factual promulgation date.**

**`ddw_code` availability (78-03 depends on this).** No DDW analyte-code list exists anywhere in `~/Documents/Vadose/Products/openh2o/drinking-water/reference/`. The SDWIS.CSV data dictionary describes `Analyte Code` only as "a unique, four-digit number referencing the analyte being measured" and publishes no values; the eAR artifacts cover the annual report, not the lab-result vocabulary. **Every seeded analyte therefore has `ddw_code = NULL`, and a test asserts it stays that way.** 78-03's CSV importer must populate codes from the `Analyte Code` column of the state's own SDWIS1/2/3.CSV files and match to existing rows on `name`, then backfill the code — it cannot look up a code table that does not exist. `Analyte.name` is `unique=True` specifically so that name-keyed matching has something to key on.

**E. coli has no limit row.** EPA groups it under Total Coliforms with a treatment-technique rule and publishes no numeric MCL of its own. It is seeded as an analyte (presence/absence results need one) with zero limits, rather than a guessed value.

**Total Coliforms' MCL is stored as `5.0` with unit `% positive samples`.** That is what EPA publishes — a monthly percentage of positive samples, not a concentration. Storing it verbatim keeps the field honest; any consumer must read the unit.

**Lead's action level is `0.010 mg/L`,** which is what the EPA page publishes today (the Lead and Copper Rule Improvements value, superseding the long-familiar 0.015). It is seeded as `action_level`, not `mcl`, because lead and copper are treatment techniques.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug/accuracy] `facility_type` carries 22 codes, not the plan's "20-code SDWIS list"**
- **Found during:** Task 1
- **Issue:** The plan said 20 codes. The DDW SDWIS.CSV data dictionary (rev 12/2021, the named source) actually publishes 21: CS, CW, CH, CC, DS, IG, IN, NN, NP, OT, PC, PF, RS, RC, SS, SP, ST, SI, TM, TP, WL. EPA's federal `SDWA_FACILITIES.FACILITY_TYPE_CODE` list adds a 22nd, WH (wellhead).
- **Fix:** Seeded all 22, with a comment explaining that WH comes from the federal list so a federal import cannot fail validation against a CA-only vocabulary.
- **Files modified:** `drinking/models.py`
- **Verification:** Both source lists fetched and quoted in the execution transcript.
- **Committed in:** `2fd1980`

**2. [Rule 1 — Bug/accuracy] `pws_type` uses the federal codes, not the draft's shorthand**
- **Found during:** Task 1
- **Issue:** The schema draft and the plan both wrote `CWS/NTNC/TNC`. The federal source (`SDWA_PUB_WATER_SYSTEMS.PWS_TYPE_CODE`) publishes `CWS`, `NTNCWS`, `TNCWS`. Design principle #1 is "store the regulator's vocabulary, don't invent one" — the shorthand is invented.
- **Fix:** Used the published codes.
- **Files modified:** `drinking/models.py`
- **Verification:** Codes quoted from the ECHO SDWA download documentation.
- **Committed in:** `2fd1980`

**3. [Rule 2 — Missing critical] `primary_source_code` includes GU and GUP**
- **Found during:** Task 1
- **Issue:** The plan listed four codes (GW/SW/GWP/SWP). The published list has six; GU ("groundwater under the influence of surface water") is a common and regulatorily significant California designation that triggers surface-water treatment requirements.
- **Fix:** Seeded all six.
- **Files modified:** `drinking/models.py`
- **Verification:** Same source as above.
- **Committed in:** `2fd1980`

**4. [Rule 3 — Blocking] A second pinned droppability literal needed updating**
- **Found during:** Task 3
- **Issue:** The plan named only `tests/test_modules.py`. `tests/test_module_template_guards.py::test_optional_module_names_is_what_we_think` pins the same set independently and failed on the registry change.
- **Fix:** Added `drinking` to that pin, with a comment distinguishing "droppable by construction" from "droppable after decoupling". This also enrolls `drinking` in that file's parametrized template-guard test for free.
- **Files modified:** `tests/test_module_template_guards.py`
- **Verification:** Full suite green.
- **Committed in:** `3b29485`

**5. [Rule 1 — Accuracy] `RegulatoryLimit.clean()` also rejects `effective_end < effective_start`**
- **Found during:** Task 1
- **Issue:** The plan specified only overlap rejection. A backwards range is silently accepted by an overlap check alone (it overlaps nothing) and corrupts every "the limit on date D" query.
- **Fix:** Added the ordering check with its own field error; covered by a test.
- **Files modified:** `drinking/models.py`, `tests/test_drinking_models.py`
- **Verification:** `test_end_before_start_is_rejected`.
- **Committed in:** `2fd1980` / `1b8d2de`

### Deferred Enhancements

None. Nothing surfaced that belonged in ISSUES.md rather than in the work itself.

---

**Total deviations:** 5 auto-fixed (3 Rule 1, 1 Rule 2, 1 Rule 3), 0 deferred
**Impact on plan:** All five are accuracy or completeness fixes to published-vocabulary transcription and validation. No scope creep — no field, model or surface exists that the plan did not call for.

## Issues Encountered

**Generating the migration before the app was installed.** Task 1 required `makemigrations drinking` while Task 3 still owned the registry entry, so `drinking` was not in `INSTALLED_APPS` yet. Resolved without touching the repo or reordering tasks: a throwaway settings shim inside the staging container (`from config.settings.local import *` plus `INSTALLED_APPS + ["drinking"]`) generated the identical migration file, which was copied back and the shim deleted. No repo state was perturbed and Task 1's "existing suite untouched" verify held.

**Constraint deprecation.** New `CheckConstraint`s use `condition=` rather than the deprecated `check=`, so the suite's four pre-existing `RemovedInDjango60Warning`s (parcels ×2, accounting, surface) stayed at four. Retrofitting those is out of scope.

## Verification

| Gate | Result |
|---|---|
| Full suite | `1 failed, 1084 passed, 4 warnings, 1 error in 105.34s` — the two pre-existing not-ours items only (`test_dashboard_tables_have_mobile_scroll_wrapper`, the `test_dbz_returns_503` teardown leak) |
| `makemigrations --check` | "No changes detected" |
| `check --deploy` | 3 warnings — the pre-existing SSL trio (W008, W012, W016). No new ones. |
| Boot without `drinking` | `manage.py check` clean; `migrate --plan` names no drinking migration; `seed_data` skips `seed_drinking` |
| `seed_drinking` idempotency | Run 1: 33 analytes / 32 limits created. Run 2: 0 created, 32 updated. |

## Next Phase Readiness

Ready for `78-02-PLAN.md` (pages, nav and the dashboard card). The ModuleSpec is deliberately apps-only, so 78-02 adds `url_prefix`, `url_module`, `url_order`, `nav` and `dashboard_cards` to the existing entry rather than creating one — and `test_nav_entry_count_matches_todays_sidebar` (pinned at 19) is the test that will need a conscious update when it does.

For 78-03, read the two Decisions above before writing the importer: `ddw_code` is universally NULL and must be learned from the state's files by matching on `Analyte.name`, and `2000-01-01` is a placeholder start date, never a fact.

---
*Phase: 78-drinking-core*
*Completed: 2026-07-19*
