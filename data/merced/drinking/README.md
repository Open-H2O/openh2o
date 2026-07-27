<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Merced drinking-water demonstration data

Every file here is **published public record, carried verbatim**. Nothing in
this directory is synthesized, estimated, or filled in. It is the source data
for `seed_merced_drinking`, which extends the Merced Subbasin demonstration
with the drinking-water domain.

## Why the City of Merced

The demonstration already models the Merced Subbasin's *quantity* side — the
GSAs, the parcels, the wells that irrigate them, the accounting that balances
them. `CA2410009` (CITY OF MERCED) is a **100% groundwater** community water
system serving 93,692 people, and all 21 of its sampled source wells fall
inside the same `lower_merced_subbasin.geojson` boundary the rest of the demo
uses (verified by point-in-polygon, 2026-07-27).

That is the whole point. The city's drinking water is pumped from the aquifer
the rest of the platform is accounting for, so `SystemFacility.well` is not an
abstract join here — it is the same physical well, sampled on this side and
metered on the other.

## Files

| File | Source | Retrieved |
|---|---|---|
| `merced_lab_results_3yr.tab.gz` | DDW EDT Library, `SDWIS4.zip` → `SDWIS4.tab` (file dated 2026-06-11), rows for `CA2410009` only | 2026-07-27 |
| `envirofacts_water_system.json` | EPA Envirofacts `WATER_SYSTEM/PWSID/CA2410009` | 2026-07-27 |
| `envirofacts_facilities.json` | EPA Envirofacts `WATER_SYSTEM_FACILITY/PWSID/CA2410009` | 2026-07-27 |
| `envirofacts_geographic_area.json` | EPA Envirofacts `GEOGRAPHIC_AREA/PWSID/CA2410009` | 2026-07-27 |
| `sampling_points.json` | PS Codes and names from the lab file; coordinates and screen intervals from GAMA | 2026-07-27 |

Sources:

- DDW EDT Library — <https://www.waterboards.ca.gov/drinking_water/certlic/drinkingwater/EDTlibrary.html>
- EPA Envirofacts SDWIS REST — <https://data.epa.gov/efservice/>
- GAMA "Ground Water — Water Quality Results", *Division of Drinking Water
  (2020 – present)* — <https://data.ca.gov/dataset/ground-water-water-quality-results>

## The lab results

`merced_lab_results_3yr.tab.gz` is the state's own SDWIS4 export, **unedited
except for two filters**: rows whose Water System Number is `CA2410009`, and
sample dates within the three years ending on the file's last Merced sample.

| | |
|---|---|
| Window | 2023-05-21 → 2026-05-21 (exactly three years) |
| Results | 22,367 |
| Sample events | 334 |
| Sampling points | 27 |
| Analytes | 159 |
| Non-detects | 21,615 |
| Detections | 752 |

**The 97% non-detect rate is real and is deliberately kept.** Most drinking
water monitoring is the work of proving absence; a demo that showed only the
detections would misrepresent what the job actually looks like, and it would
hide the exact distinction `SampleResult.less_than_rl` exists to draw — a
`<0.5` row is the floor of the instrument, not a measurement of 0.5.

The detections carry the interesting stories on their own:

| Analyte | Detections | Range | For reference, the limit |
|---|---|---|---|
| Nitrate | 133 | 1.3 – 5.8 mg/L | 10 mg/L MCL |
| Arsenic | 24 | 2 – 8.1 µg/L | 10 µg/L MCL |
| Hexavalent chromium | 22 | 0.83 – 5 µg/L | CA MCL 10 µg/L, effective 2024-10-01 |
| Fluoride | 68 | 0.1 – 0.22 mg/L | 2 mg/L secondary MCL |

Those limits are listed here as context for a reader of this file. **The
platform does not print them beside a result and does not compute a verdict** —
see `drinking/models.py` on "prepare, never determine".

Because the file is the state's native layout, it also feeds the import screen
directly: `drinking.importer` parses it with no transformation, which is what
lets the seed create results through the same code path an operator uses.

## Sampling points

The 27 PS Codes in the lab file, all of which resolve to a real EPA facility
(verified 2026-07-27). `point_type` is assigned by the seed from the facility
type the state's own file reports:

| Facility type | Points | `point_type` |
|---|---|---|
| `WL` well | 21 | `source` |
| `TP` treatment plant | 1 | `entry_point` |
| `DS` distribution system | 5 | `distribution`, except the LCR tap (`tap`) |

Coordinates come from GAMA, which publishes a latitude and longitude per PS
Code. **Screen intervals are carried for only 3 of the 21 wells.** GAMA reports
a screen top of `0` for the rest, which would assert a municipal supply well
perforated from the ground surface; an implausible number is left out rather
than written down as fact. Well depth is `NaN` throughout and is likewise left
NULL.

## Personal contact details are stripped

EPA's `WATER_SYSTEM` record carries a named individual's name, email, phone and
fax. `drinking/models.py` deliberately maps the mailing **address only**, on a
2026-07-19 scope call about privacy and retention. Re-publishing those fields in
this repository would defeat that decision, so `admin_name`, `org_name`,
`email_addr`, `phone_number`, `phone_ext_number`, `alt_phone_number` and
`fax_number` are removed from the committed payload. Everything else is byte-
for-byte what EPA returned.
