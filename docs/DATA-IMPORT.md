<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Importing Your Agency's Data

There are three ways to get data into OpenH2O. Most agencies use all three: demo data to learn the system, file imports for the data they already have, and auto-populate to fill in the rest from public sources.

Run every importer with `--dry-run` first — it validates and reports what *would* happen without writing anything.

---

## 1. Demo data (to learn the system)

```bash
docker compose exec web python manage.py seed_demo_data   # fictional "Demo Valley GSA"
docker compose exec web python manage.py seed_kaweah      # a real California basin
```

Both are idempotent and coexist. Add `--flush` to delete and reload (deliberately — it removes that dataset).

---

## 2. File imports (the data you already have)

### Parcels — `import_parcels`
The foundation: accounts, wells, and ledgers all hang off parcels. Accepts **GeoJSON or Shapefile**.

```bash
docker compose exec web python manage.py import_parcels parcels.geojson --dry-run
docker compose exec web python manage.py import_parcels parcels.geojson
```

Expected attributes (override the field names if yours differ):

| Field | Default name | Override flag | Required |
|---|---|---|---|
| Parcel number (APN) | `APN` | `--parcel-number-field` | yes |
| Owner name | `OWNER` | `--owner-field` | no |
| Geometry | (the feature geometry) | — | yes — polygons |

Records land in a staging table first, then promote to `Parcel`, so a bad file never half-corrupts your data.

### Wells — `import_wells`
Accepts **CSV or Shapefile**. For CSV, the geometry comes from latitude/longitude columns.

```bash
docker compose exec web python manage.py import_wells wells.csv --dry-run
```

| Field | Default column | Override flag |
|---|---|---|
| Well name | `WELL_NAME` | `--name-field` |
| Latitude | `LATITUDE` | `--lat-field` |
| Longitude | `LONGITUDE` | `--lon-field` |
| Well registration ID | `WELL_REG_ID` | `--reg-id-field` |

### Ledger entries — `import_ledger_csv`
For migrating usage/supply history from a prior system. **CSV**, with these columns:

| Column | Required | Notes |
|---|---|---|
| `parcel_number` | **yes** | must match an imported parcel's APN |
| `effective_date` | **yes** | the date the entry applies to |
| `amount_acre_feet` | **yes** | positive = supply, negative = usage |
| `source_type` | **yes** | e.g. groundwater, surface water |
| `water_type_code` | no | must match a seeded WaterType code |
| `transaction_date` | no | when it was recorded |
| `description` | no | free text |

```bash
docker compose exec web python manage.py import_ledger_csv ledger.csv \
  --reporting-period "2024 Water Year" --dry-run
```

---

## 3. Auto-populate (fill in from public sources)

If you only have a basin boundary, `auto_populate` queries DWR and USGS to pull the rest:

```bash
docker compose exec web python manage.py auto_populate --boundary "Kaweah Subbasin" --dry-run
docker compose exec web python manage.py auto_populate --boundary "Kaweah Subbasin"
```

| Step | Source | Creates |
|---|---|---|
| `basins` | DWR Bulletin 118 groundwater basins | management zones |
| `parcels` | DWR LightBox statewide parcels | parcel boundaries |
| `flowlines` | USGS 3DHP | stream flowlines |
| `stations` | CDEC / USGS / CIMIS | monitoring stations |

Run a subset with `--steps basins parcels`. The boundary must already exist (create it in the UI or via `import_parcels` first).

---

## What still needs hand entry

No public source provides these, so they're entered in the web UI under **Infrastructure**:

- **Water rights** — eWRIMS is not auto-imported
- **Water accounts** — the agency defines these
- **Allocations** — the agency's budget decisions

---

## A sensible order

1. `seed_data` (reference tables) → `seed_demo_data` (to explore)
2. `import_parcels` your real parcels — confirm the boundary on the map
3. `import_wells` if you have a well list; `auto_populate --steps stations` for monitoring
4. Create water accounts and allocations in the UI
5. `import_ledger_csv` if migrating history; otherwise the ledger fills from sync + meter readings
6. Connect live data sources and the sync schedule (see [DEPLOY.md](../DEPLOY.md))
