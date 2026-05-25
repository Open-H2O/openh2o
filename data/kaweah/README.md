# Kaweah Subbasin Data

Seed data for the Kaweah Subbasin (DWR Basin 5-022.11) in Tulare County,
California. Unlike the fictional "Demo Valley GSA" dataset, this seed uses
real geography, real monitoring station IDs, and representative water-right
holders drawn from the actual subbasin.

## Subbasin overview

| Attribute | Value |
|-----------|-------|
| DWR Basin Number | 5-022.11 |
| County | Tulare |
| Area | ~700 sq mi |
| Primary River | Kaweah River (four forks) |
| GSA | Kaweah Subbasin GSA (multiple member agencies) |
| SGMA Priority | High / Critically Overdrafted |

## Data sources and provenance

### Geography

- **Subbasin boundary**: Simplified 10-vertex polygon approximating the DWR
  Bulletin 118 boundary for Basin 5-022.11. Coordinates derived from the
  DWR SGMA Basin Boundary dataset (public, sgma.water.ca.gov).
- **Management zones**: Two zones split at approximately -119.25 longitude,
  representing western (Mid-Kaweah) and eastern management areas. These are
  illustrative; actual GSA management areas differ.

### Monitoring stations

| Source | Station IDs | Notes |
|--------|------------|-------|
| CDEC | TRM, KWR, VIS | Real CDEC station codes (cdec.water.ca.gov) |
| USGS | 11210100, 11208730 | Real NWIS gage numbers (waterdata.usgs.gov) |
| CIMIS | 54 | CIMIS station at Visalia (cimis.water.ca.gov) |
| DWR WDL | KAW-GWL-01, KAW-GWL-02 | Fictional IDs representing typical DWR groundwater monitoring wells |

### Water rights holders

Holder names reference real irrigation and water conservation districts
in the Kaweah Subbasin. The right IDs (KAW-WR-*), face values, and
priority dates are representative but not sourced from eWRIMS records.

### Wells, parcels, and accounting

Wells use Tulare County road naming conventions (Avenue/Road grid).
Parcel APNs and accounting entries are entirely fictional.

## Usage

```bash
make kaweah          # Load Kaweah seed data
make flush-kaweah    # Delete and reload
```

Or directly:

```bash
python manage.py seed_kaweah
python manage.py seed_kaweah --flush
```

## Relationship to demo data

Both datasets can coexist. The Kaweah seed uses the "KAW-" prefix for
account numbers, well registration IDs, parcel numbers, and water right
IDs, so flush operations target only Kaweah records.
