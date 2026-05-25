# Issues

Deferred items and nice-to-haves discovered during execution.

## Open

### ISSUE-003: Recharge sites should be polygons, not points
- **Phase:** 11.1-02 (discovered)
- **Priority:** P1 (data model correctness)
- **Description:** Recharge sites represent fields where water is applied and allowed to percolate back to groundwater. These are areas, not points. The current model uses a `PointField` geometry, but should use `PolygonField` (or `MultiPolygonField`). The map layer currently renders them as circles; it should render them as filled polygons similar to parcels.
- **Impact:** Affects `recharge/models.py` (geometry field), GeoJSON serializer, map layer config (change from `circle` to `fill`+`line`), and any existing data migration.

### ISSUE-004: Wells/PODs need association with Place of Use (parcels)
- **Phase:** 11.1-02 (discovered)
- **Priority:** P1 (domain model completeness)
- **Description:** Points of diversion (surface water) and wells (groundwater) need to be linked to the parcels they irrigate. The parcel represents the "Place of Use" in water rights terminology. This source-to-use association is fundamental for populating water modeling platforms like USGS MODFLOW. Consider renaming "Parcels" to "Place of Use" in the UI to align with water rights language. Implementation: junction tables or FK relationships linking Wells → Parcels and WaterRights/PODs → Parcels (ISSUE-002 partially addressed the WaterRight→Parcel link via `WaterRightParcel`).
- **Impact:** Affects data model (new Well→Parcel junction), UI (rename + association management), map (draw lines between source and use), and downstream reporting/export.

## Closed

### ISSUE-001: RechargeSite missing zone FK
- **Phase:** 04-02 (deferred), 09-01 (resolved)
- **Resolution:** Added optional `zone` FK to `RechargeSite` with `SET_NULL` on delete. `create_recharge_ledger_entries` now falls back to `recharge_event.recharge_site.zone` when no zone param supplied. Migration: `recharge/migrations/0002_rechargesite_zone.py`.

### ISSUE-002: WaterRight missing parcel FK
- **Phase:** 04-02 (deferred), 09-01 (resolved)
- **Resolution:** Added `WaterRightParcel` junction table (many-to-many via explicit model) with `unique_together` constraint. `create_diversion_ledger_entry` now looks up parcel via `WaterRightParcel` when no parcel param supplied. Migration: `surface/migrations/0002_waterrightparcel.py`.
