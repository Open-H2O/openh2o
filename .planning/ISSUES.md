# Issues

Deferred items and nice-to-haves discovered during execution.

## Open

### ISSUE-001: RechargeSite missing zone FK
- **Phase:** 04-02
- **Rule:** 5 (nice-to-have)
- **Description:** The plan's `create_recharge_ledger_entries` assumes `recharge_site.zone` exists, but `RechargeSite` has no zone foreign key. The function was implemented to accept a `zone` parameter explicitly instead. Consider adding an optional `zone` FK to `RechargeSite` in a future migration.

### ISSUE-002: WaterRight missing parcel FK
- **Phase:** 04-02
- **Rule:** 5 (nice-to-have)
- **Description:** The plan's `create_diversion_ledger_entry` references "the first parcel linked to the water right's holder," but `WaterRight.holder_name` is a CharField with no FK to `Parcel`. The function accepts a `parcel` parameter explicitly. Consider adding a `WaterRightParcel` junction table or a FK from `WaterRight` to `Parcel` in a future phase.
