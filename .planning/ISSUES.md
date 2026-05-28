# Issues

Deferred items and nice-to-haves discovered during execution.

## Open

### ISS-006: Wire remaining adapters for live telemetry sync
- **Phase:** 26-02 (discovered during checkpoint)
- **Priority:** P1 (monitoring tab shows 1/7 active stations reporting)
- **Description:** USGS, DWR WDL, and DWR SGMA adapters exist but never ran live (DATASYNC_MOCK_MODE was True). Run `sync_source` for each, fix date/field parsing bugs, verify data.
- **Stations:** USGS 11210100, USGS 11208730, DWR WDL KAW-GWL-01/02, DWR SGMA TUL-001
- **Effort:** ~30 min (adapters exist, just need live testing)

### ISS-007: Get CIMIS API key and wire CIMIS adapter
- **Phase:** 26-02 (discovered during checkpoint)
- **Priority:** P2 (ET and precip data for water budgets)
- **Description:** CIMIS adapter exists but needs appKey from et.water.ca.gov. Free registration. Station: CIMIS 54 (Visalia).
- **Blocked by:** API key registration at https://et.water.ca.gov/Home/Register

### ISS-008: Chart parameter dropdown shows raw codes ("15", "20")
- **Phase:** 26-02 (user feedback)
- **Priority:** P1 (meaningless numbers in dropdown)
- **Description:** `<select>` populated from `station.parameters` raw codes. JS label update fails when API returns fewer params than template. Fix: populate from API response or use PARAMETER_MAP labels server-side.
- **File:** `templates/datasync/station_detail.html` JS block

### ISS-009: Chart Y-axis needs unit label and contextual title
- **Phase:** 26-02 (user feedback)
- **Priority:** P1 (numbers without units are meaningless)
- **Description:** Y-axis shows bare numbers. Title says "Telemetry" not parameter name. Use Chart.js `scales.y.title.text` and dynamic card title.

### ISS-010: Units and labels audit across all monitoring pages
- **Phase:** 26-02 (user feedback)
- **Priority:** P2 (values without units throughout monitoring section)
- **Description:** Audit station detail records table, sparkline tooltips, chart tooltips, station list for missing units. Each adapter needs PARAMETER_MAP with display names and units.

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

### ISSUE-002: WaterRight missing parcel FK
- **Phase:** 04-02 (deferred), 09-01 (resolved)
- **Resolution:** Added `WaterRightParcel` junction table (many-to-many via explicit model) with `unique_together` constraint. `create_diversion_ledger_entry` now looks up parcel via `WaterRightParcel` when no parcel param supplied. Migration: `surface/migrations/0002_waterrightparcel.py`.
