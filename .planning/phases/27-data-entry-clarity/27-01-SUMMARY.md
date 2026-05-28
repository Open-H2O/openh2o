---
phase: 27-data-entry-clarity
plan: 01
subsystem: ui
tags: [django, htmx, forms, ledger, recharge, badges]
requires: [22-01]
provides:
  - Recharge event entry from the site detail UI
  - Auto-generated positive ledger entries on recharge event creation
  - Color-coded ledger source-type pill badges
affects: [27-02]
tech-stack:
  added: []
  patterns:
    - Inline form lives inside its HTMX-swapped partial so validation errors and typed values survive the swap
    - Display-only label override in a badge include (allocation → "Water Budget")
key-files:
  created:
    - recharge/forms.py
    - templates/recharge/partials/_event_history.html
    - templates/accounting/partials/_source_badge.html
  modified:
    - recharge/views.py
    - recharge/urls.py
    - templates/recharge/site_detail.html
    - templates/accounting/partials/_ledger_list_results.html
key-decisions:
  - Inline entry form placed inside the swapped partial (not separate + JS reset) for correct validation-error rendering
  - Catch ValueError from the ledger service rather than pre-checking the zone rule (service is single source of truth)
  - "Water Budget" label is display-only on the badge; DB value stays "allocation"
  - Measurement entry form pulled before completion (user decision); will reassess after production deployment based on water-district demand
issues-created: none
duration: 23 min
completed: 2026-05-28
---

# Phase 27 Plan 01: Recharge Entry & Ledger Badges Summary

GSA admins can now record recharge events directly on the recharge site detail page, with events auto-distributing positive ledger entries across zone parcels, and the use-ledger source column now renders distinct color-coded pill badges.

## Accomplishments
- **Recharge event entry from the UI:** An HTMX inline "Log Recharge Event" form on the site detail page replaces the admin-only / seed-script entry path. Submitting an event runs the existing `create_recharge_ledger_entries` service and reports the result (e.g., "Created 9 ledger entries across zone parcels.") above the refreshed table — verified live: a 100 AF event on a zoned Mid-Kaweah site produced 9 area-weighted ledger entries.
- **Graceful no-zone handling:** Zone-less sites save the event and show an explanatory note instead of erroring (the service raises `ValueError`, the view catches it).
- **Ledger source pills:** The use-ledger Source column renders `.badge-pill` spans color-coded by type (ET Estimate teal, Meter Read blue, Surface Diversion orange, Recharge green, Water Budget gold, Adjustment red, Manual/CSV grey). Verified 50 pills render server-side.
- **Measurement entry form pulled (user decision):** The plan also built a "Log Measurement" form. The user opted to remove it before completion — the Recent Measurements table stays read-only, and whether districts want manual measurement entry will be decided after production deployment. The form class, view, URL, and partial were removed cleanly (no dead code).

## Files Created/Modified
- `recharge/forms.py` (new) — `RechargeEventForm` mirroring accounting widget conventions.
- `recharge/views.py` — added `recharge_event_create` (with ledger generation); detail view passes `event_form`.
- `recharge/urls.py` — `recharge:event_create`.
- `templates/recharge/site_detail.html` — event-history table extracted into swappable wrapper div (`#event-history`); Recent Measurements table left inline and read-only.
- `templates/recharge/partials/_event_history.html` (new) — event table + ledger-result note + inline Log Event form.
- `templates/accounting/partials/_source_badge.html` (new) — source_type → badge color + label map.
- `templates/accounting/partials/_ledger_list_results.html` — Source cell now includes the badge partial.

Built then removed within this plan (per user decision): `RechargeMeasurementForm`, `recharge_measurement_create` view + URL, and `templates/recharge/partials/_measurements.html`.

## Decisions Made
- **Inline form inside the swapped partial.** The plan sketched a separate form below the table with a JS reset on success. I placed the form inside the HTMX-swapped partial instead, so a failed submit re-renders with field errors and the user's typed values intact. Happy-path behavior is identical (fresh empty form after a successful submit). This is the only structural deviation from the plan.
- **Catch `ValueError`, don't pre-check the zone rule** — the ledger service owns that rule; duplicating it invites drift.
- **"Water Budget" is display-only** on the badge; the DB `source_type` value stays `allocation` (Plan 27-02 handles the model-level relabel).
- Added a friendlier zero-result message ("zone has no parcels") distinct from the plan's literal `Created 0 ...` string.
- **Measurement entry form pulled** at the verification checkpoint on user instruction: "When we deploy this tool to production, we'll see if the water districts actually want that or not." Removed the form class, view, URL, and partial; restored the read-only measurements table. Re-addable from commit history.

## Deviations from Plan
- **[Design] Inline form moved into the swapped partial** (see above) — required for validation-error rendering and input preservation; no behavior change on the success path.
- **[Scope, user-directed] Log Measurement form removed.** The plan specified both event and measurement entry forms; the user decided to ship only the event form and defer the measurement form pending real district demand.

## Issues Encountered
- The visual checkpoint could not be screenshotted in a live browser: the public Cloudflare tunnel was not running, and a sandboxed SSH port-forward to Butler's Caddy proxy had its data channel reset. Mitigation: verified both pages render 200 via an authenticated Django test client (forms, wrappers, 50 badge-pills, correct labels all present), confirmed every CSS class exists in the compiled stylesheet, and confirmed the markup reuses components already live in production. User visually approved the forms, in-place swap, and pill colors.

## Verification
- `manage.py check` — no issues (live container on Butler).
- Ledger side effect — 9 entries from a 100 AF event on a zoned site (rolled back, no residue).
- HTMX POST flow — returns refreshed table partial + "Created 9 ledger entries" note; new event row shown.
- Ledger list — 50 `.badge-pill` spans; "Water Budget" and "ET Estimate" present.
- Full test suite — **186 passed**, 0 failures. No migrations introduced.

## Next Step
Ready for 27-02-PLAN.md (Allocation → Water Budget terminology sweep).
