# Issues

Deferred items and nice-to-haves discovered during execution.

## Open

No open issues.

## Closed

### ISSUE-001: RechargeSite missing zone FK
- **Phase:** 04-02 (deferred), 09-01 (resolved)
- **Resolution:** Added optional `zone` FK to `RechargeSite` with `SET_NULL` on delete. `create_recharge_ledger_entries` now falls back to `recharge_event.recharge_site.zone` when no zone param supplied. Migration: `recharge/migrations/0002_rechargesite_zone.py`.

### ISSUE-002: WaterRight missing parcel FK
- **Phase:** 04-02 (deferred), 09-01 (resolved)
- **Resolution:** Added `WaterRightParcel` junction table (many-to-many via explicit model) with `unique_together` constraint. `create_diversion_ledger_entry` now looks up parcel via `WaterRightParcel` when no parcel param supplied. Migration: `surface/migrations/0002_waterrightparcel.py`.
