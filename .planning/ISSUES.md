# Issues

Deferred items and nice-to-haves discovered during execution.

## Open

(No open issues)

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
