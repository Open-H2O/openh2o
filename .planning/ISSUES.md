# Issues

Deferred items and nice-to-haves discovered during execution.

## Open

### ISS-014: Demo account credentials are hardcoded in a public planning doc
- **Phase:** 28-01 (discovered 2026-05-28)
- **Priority:** P2 (acceptable for a public demo with throwaway data; must-fix before real users or real data)
- **Description:** The demo login (`demo@openh2o.com` / `OpenWaterDemo2026`) is committed in plaintext at `.planning/phases/28-public-deployment/28-01-SUMMARY.md:45`. The repo is public and the site is publicly reachable at openh2o.com, so anyone can read the credentials and log into the demo. Fine while the account is a non-admin user pointed at disposable seed data, but it becomes a real exposure the moment the platform holds anything beyond the demo dataset.
- **How to fix:** Before any non-demo use — (1) rotate the demo password to a fresh value and update it in the deploy/onboarding docs without committing the new value to git; or (2) drop the shared demo account entirely and have evaluators self-register; or (3) move the credentials out of the tracked planning doc into the gitignored `.env`/secrets store. Pairs with ISS-012 (default Postgres password) — both are "rotate before real data" items.

### ISS-012: Rotate default Postgres password before real data
- **Phase:** 28-01 (discovered during public deploy)
- **Priority:** P2 (low risk now, must-fix before any real district data)
- **Description:** The Postgres role still uses the default password `openh2o` (in Butler's `.env` `POSTGRES_PASSWORD` and `DATABASE_URL`). Low risk today: the DB port is NOT published to the host or internet — only the web app is reachable, through the Cloudflare Tunnel, and the DB is reachable only on the internal `openh2o_default` Docker network. Must rotate before the site holds anything beyond demo data.
- **How to fix:** Generate a strong password; `ALTER USER openh2o WITH PASSWORD '...'` in the db container; update both `POSTGRES_PASSWORD` and the inline password in `DATABASE_URL` in Butler's `.env`; `docker compose up -d`. Not in git (`.env` is gitignored).

### ISS-007: Get CIMIS API key and wire CIMIS adapter
- **Phase:** 26-02 (discovered during checkpoint)
- **Priority:** P2 (ET and precip data for water budgets)
- **Description:** CIMIS adapter exists but needs appKey from et.water.ca.gov. Free registration. Station: CIMIS 54 (Visalia).
- **Blocked by:** API key registration at https://et.water.ca.gov/Home/Register

### ISSUE-005: Open-source licensing and trademark protection
- **Phase:** None (non-code, do before public release)
- **Context:** Domain openh2o owned. Code intended to be open source, but must prevent corporations from forking and selling as a proprietary product. Need to select a license that allows free use by water districts/GSAs while blocking commercial appropriation.
- **Options to evaluate:**
  - AGPL-3.0 (strongest copyleft — any network use must share source, deters SaaS wrappers)
  - Server Side Public License (SSPL — MongoDB-style, explicitly blocks offering as a service without open-sourcing the full stack)
  - Business Source License (BSL — source-available with time-delayed open-source conversion)
  - Plain GPL-3.0 + Commons Clause (open source with explicit "no selling" rider)
- **Also needed:** LICENSE file in repo root, copyright header convention, README badge, and potentially a trademark notice for the "OpenH2O" name (state trademark filing is ~$70)
- **Decision required:** Which license best fits "free for public agencies, hostile to commercial capture"

## Closed

### ISS-011: Login page needs visual overhaul
- **Phase:** 26.1-01 (discovered), 2026-05-28 (resolved)
- **Root cause:** Not "unstyled Django default" as originally described — the auth templates DO use VanderDev classes. The real bug: `base_auth.html` loaded `output.css` and `app.css` but NOT `tokens.css`, where all the `--color-*` and `--space-*` custom properties are defined. Every `var(--color-card)` etc. resolved to nothing, so the login/signup/password-reset pages rendered with no background, no card styling, and default browser fonts despite the rule files loading correctly (HTTP 200, correct MIME).
- **Resolution:** Added `tokens.css` link to `base_auth.html` (with `?v=7` cache-bust matching `base.html`), widened the Public Sans weight range to match the main layout, and added the OpenH2O brand lockup (favicon + gold wordmark) above the login card for "proper branding." Commits e3db272, plus login branding commit. Deployed to Butler, verified live at openh2o.com/accounts/login/ via computed styles + screenshot.

### ISSUE-001: RechargeSite missing zone FK
- **Phase:** 04-02 (deferred), 09-01 (resolved)
- **Resolution:** Added optional `zone` FK to `RechargeSite` with `SET_NULL` on delete. `create_recharge_ledger_entries` now falls back to `recharge_event.recharge_site.zone` when no zone param supplied. Migration: `recharge/migrations/0002_rechargesite_zone.py`.

### ISSUE-003: Recharge sites should be polygons, not points
- **Phase:** 11.1-02 (discovered), post-12 (resolved)
- **Resolution:** Model already had MultiPolygonField. Updated GeoJSON views to prefer geometry over location, changed map layer from circle to fill+line with point fallback, updated seed data to generate polygon geometry. Commit 7e163d4.

### ISSUE-004: Wells/PODs need association with Place of Use (parcels)
- **Phase:** 11.1-02 (discovered), post-12 (resolved)
- **Resolution:** WellIrrigatedParcel already existed (Phase 2). Added PointOfDiversionParcel junction table mirroring the same pattern. Migration 0003. Admin registered. UI rename to "Place of Use" deferred as non-essential. Commit 7e163d4, 41c82f2.

### ISS-006: Wire remaining adapters for live telemetry sync
- **Phase:** 26-02 (discovered), 26.1-01 (resolved)
- **Resolution:** USGS adapter worked as-is (273 records from station 11208730). DWR WDL and DWR SGMA adapters rewritten from scratch — original endpoints (wdl.water.ca.gov and sgma.water.ca.gov/webservice) returned 404 (decommissioned). Both now query the CNRA Open Data Portal CKAN API (data.cnra.ca.gov Periodic Groundwater Level Measurements dataset). DWR WDL: 1,014 records from 2 Kaweah wells. DWR SGMA: 2 records (quarterly measurements). Commits 74c2ccc, b3bff39.

### ISS-008: Chart parameter dropdown shows raw codes ("15", "20")
- **Phase:** 26-02 (user feedback), 26.1-01 (resolved)
- **Resolution:** Created unified parameter registry (`datasync/adapters/registry.py`) merging all adapter PARAMETER_MAPs. Views now use `get_parameter_label()` instead of hardcoded dicts. Template renders `enriched_parameters` with human labels on first load. Commit 03d1134.

### ISS-009: Chart Y-axis needs unit label and contextual title
- **Phase:** 26-02 (user feedback), 26.1-01 (resolved)
- **Resolution:** Chart.js config updated with Y-axis title, dynamic chart card title, and tooltip callbacks appending units. All driven by registry labels via API response. Commits 03d1134, 7220008.

### ISS-010: Units and labels audit across all monitoring pages
- **Phase:** 26-02 (user feedback), 26.1-01 (resolved)
- **Resolution:** Sparkline hover tooltips show "Latest: {value} {unit}". Chart tooltips append units. Parameter pills on station detail show human names. Recent records table uses registry labels for all sources. Commit 7220008.

### ISSUE-002: WaterRight missing parcel FK
- **Phase:** 04-02 (deferred), 09-01 (resolved)
- **Resolution:** Added `WaterRightParcel` junction table (many-to-many via explicit model) with `unique_together` constraint. `create_diversion_ledger_entry` now looks up parcel via `WaterRightParcel` when no parcel param supplied. Migration: `surface/migrations/0002_waterrightparcel.py`.

### ISS-013: Pre-existing migration drift in datasync and recharge apps
- **Phase:** 27-02 (discovered during makemigrations --check)
- **Severity:** Low (state-only: index renames + a choices-label alter; no DB schema/data impact)
- **Detail:** `manage.py makemigrations --check` reports uncommitted model changes in two apps unrelated to this plan: `datasync` (index renames on OpenETCache, from Phase 18-01 commit 68a9882) and `recharge` (alter field `site_type` on RechargeSite, from a later edit). These are committed model definitions whose matching migrations were never generated. The accounting/parcels label migrations added in 27-02 are fully in sync.
- **Fix:** Run `docker compose exec web python manage.py makemigrations datasync recharge` on Butler, commit the generated files, redeploy. Trivial and low-risk, but out of scope for the Water Budget terminology plan.
