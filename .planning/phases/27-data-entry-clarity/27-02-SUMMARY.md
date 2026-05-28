---
phase: 27-data-entry-clarity
plan: 02
subsystem: ui
tags: [django, htmx, templates, migrations, terminology]

requires:
  - phase: 27-01
    provides: ledger source-type pill badges (already relabeled "allocation" badge to "Water Budget")
provides:
  - Display-only "Allocation → Water Budget" rename across all user-facing labels
  - Glossary "Water Budget" + "Usage" entries
  - Balance-sheet explainer notes on dashboard and ledger list
affects: [phase-20-ai-operator-guide]

tech-stack:
  added: []
  patterns: ["Display-only rename: change verbose_name/choice-labels/template text, preserve URL names + model class + DB choice values"]

key-files:
  created:
    - accounting/migrations/0003_allocationplan_verbose_name.py
    - parcels/migrations/0003_alter_parcelledger_source_type.py
  modified:
    - templates/partials/_sidebar.html
    - templates/accounting/allocations_list.html
    - templates/accounting/allocation_create.html
    - templates/accounting/period_detail.html
    - templates/accounting/partials/_allocations_list_results.html
    - templates/accounting/partials/_dashboard_content.html
    - templates/geography/zone_detail.html
    - templates/accounting/dashboard.html
    - templates/accounting/ledger_create.html
    - templates/geography/zone_list.html
    - accounting/forms.py
    - accounting/models.py
    - parcels/models.py
    - config/views.py
    - templates/help/glossary.html (verified; terms live in config/views.py)
    - templates/accounting/ledger_list.html

key-decisions:
  - "Display-only rename: URL names (allocations_list), AllocationPlan class, and the 'allocation' source_type DB value all preserved. Zero behavior/data change."
  - "Glossary 'Allocation Plan' term renamed to 'Water Budget' in config/views.py (terms dict), not the template."

issues-created: [ISS-013]

duration: ~15 min code work (session dominated by an unrelated DNS infra fix — see below)
completed: 2026-05-28

quality-gates-run: []
quality-gates-passed: true
---

# Phase 27 Plan 02: Water Budget Terminology Summary

**Display-only "Allocation → Water Budget" rename across every visible label, plus glossary Water Budget/Usage entries and balance-sheet explainers — internals (URL names, model class, "allocation" DB value) untouched, two state-only migrations.**

## Performance

- **Duration:** ~15 min for the actual plan; the session as a whole ran long due to an unrelated DNS/Pi-hole outage discovered during verification (see Issues).
- **Completed:** 2026-05-28
- **Tasks:** 2 (+ human-verify checkpoint)
- **Files modified:** 16 (+ 2 migrations created)

## Accomplishments
- Every user-facing "Allocation"/"Allocations" now reads "Water Budget"/"Water Budgets": sidebar, list/create/detail pages, dashboard, period and zone pages, form field label ("Water Budget (AF)"), and the `AllocationPlan` model verbose_name.
- `ParcelLedger` source_type `"allocation"` display label → "Water Budget" (`get_source_type_display()`), value unchanged.
- Glossary defines "Water Budget" and a cross-referenced "Usage" entry (in `config/views.py` terms dict).
- Dashboard and Use Ledger pages carry a "How the ledger works" balance-sheet explainer, with Water Budget/Usage colored to match the existing positive/negative column colors.
- Swept four lowercase prose hits (dashboard, ledger_create, zone_list) that the plan's case-sensitive grep missed.

## Task Commits
1. **Task 1: Display-name sweep across templates/sidebar/forms/models** — `9da5dda` (feat)
2. **Task 2: Glossary entries + balance-sheet explainers** — `898ff9e` (feat)

## Files Created/Modified
See key-files frontmatter. Two state-only migrations (verbose_name + choices-label) hand-written to match Django's output; applied on Butler, `makemigrations --check` clean for accounting/parcels.

## Decisions Made
- Display-only rename (URL names / class / DB value preserved) — per the 2026-05-28 constraining decision.
- Glossary term lives in the view, not the template; renamed the "Allocation Plan" entry to "Water Budget" there.

## Deviations from Plan
- **Extra prose sweep (objective completion):** Found and fixed 4 lowercase "allocation" prose strings in dashboard.html, ledger_create.html, zone_list.html — not in the plan's named file list (its grep was case-sensitive), but the objective said rename "everywhere a user can see it." Committed in Task 1.
- **Glossary location:** Plan assumed entries were inline in glossary.html; they're built in config/views.py. Edited the view instead.

## Issues Encountered
- **ISS-013 (deferred):** `makemigrations --check` surfaced pre-existing, unrelated migration drift in `datasync` and `recharge` (from Phases 18/19.1) — state-only, no DB impact. Logged to ISSUES.md; out of scope here.
- **DNS outage (fixed, unrelated to this plan):** Final visual sign-off revealed openh2o.com served Hostinger's parked page. Root cause was NOT the website — it was stale DNS on the home network's primary resolver (NetSentry): Unbound held Hostinger's old nameserver delegation and Pi-hole (FTL) cached the old address. Cloudflare, the tunnel, and all public resolvers were correct the whole time. Fixed by `unbound-control flush_zone openh2o.com` + `systemctl restart pihole-FTL` on NetSentry. The Cloudflare DNS record (CNAME → tunnel, proxied) was already correct. Verified openh2o.com now serves the app (`server: cloudflare`, login page) from the Mac and all public resolvers.

## Verification
- All 186 tests pass (run with `--ds=config.settings.local`; the prod container's SSL-redirect setting causes false 301 failures if settings aren't overridden — noted for future runs).
- `manage.py check` clean. Pages render "Water Budget" with zero visible "Allocation" (verified via authenticated Django test client against the live DB).
- Migration state in sync for accounting/parcels.

## Next Phase Readiness
- **Phase 27 complete.** Next roadmap phase: Phase 20 (AI Operator Guide).
- Open items for next session: ISS-011 (login page visual polish — user flagged it as bare), ISS-012 (rotate default Postgres password), ISS-013 (datasync/recharge migration drift).

---
*Phase: 27-data-entry-clarity*
*Completed: 2026-05-28*
