# Issues

Deferred items and nice-to-haves discovered during execution.

## Open

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

### ISS-011: Login page needs visual overhaul
- **Phase:** 26.1-01 (user feedback during checkpoint)
- **Priority:** P1 (first impression for new users)
- **Description:** Login page uses unstyled Django default. Needs VanderDev design system treatment: dark mode, proper branding, centered card layout matching the rest of the platform.

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
