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

**Every row in this file reaches the database. Nothing is dropped.**

| | In this file | Loaded by the seed |
|---|---|---|
| Window | 2023-05-21 → 2026-05-21 (exactly three years) | — |
| Results | 22,367 | 22,367 |
| Sample events | 334 by point and date | **559** by the platform's own key |
| Sampling points | 27 | 27 |
| Analytes | 159 distinct in the file | 159 carry a result, of **178** in the vocabulary |
| Non-detects | 21,615 | 21,615 |
| Detections | 752 | 752 |

*Measured 2026-07-30 by loading this file into an empty database, not carried
over from a previous version of this table.*

Two rows still need explaining, and neither is a gap.

**Sample events: 334 and 559 are both counts of this file** — two definitions,
not a discrepancy. This table used to say 334, which collapses every sample taken
at one point on one day into a single event. The platform keys an event on point
+ date + **time + sample type** (`drinking/importer.py`), so a point sampled
twice in a day is two collections, which is what happened. 559 is the count under
that rule.

**Analytes: 159 is a property of this file; 178 is a property of the database.**
`Analyte` is a shared vocabulary, not a per-file tally. `seed_drinking` seeds 33
federal analytes from EPA's NPDWR table, this file contributes 159, and 14 names
appear in both — so a database holding both reads 178, of which the 159 from
here are the ones carrying a result. Do not read 178 as a count of anything in
this directory.

> **This table read 22,311 / 21,584 / 727 until 2026-07-30**, because the
> importer discarded 56 rows it called duplicates. They were not duplicates; see
> *"A repeat is not always a repeat"* below for what they actually were and what
> changed.

**The 97% non-detect rate is real and is deliberately kept.** Most drinking
water monitoring is the work of proving absence; a demo that showed only the
detections would misrepresent what the job actually looks like, and it would
hide the exact distinction `SampleResult.less_than_rl` exists to draw — a
`<0.5` row is the floor of the instrument, not a measurement of 0.5.

A selection of the detections, not all of them — `NITRATE-NITRITE` is a separate
analyte with 32 more, and is left out here only because nitrate tells the same
story. Verified against the loaded database, 2026-07-30:

| Analyte | Detections | Range | For reference, the limit |
|---|---|---|---|
| Nitrate | 133 | 1.3 – 5.8 mg/L | 10 mg/L MCL |
| Arsenic | 24 | 2 – 8.1 µg/L | 10 µg/L MCL |
| Hexavalent chromium | 22 | 0.83 – 5 µg/L | CA MCL 10 µg/L, effective 2024-10-01 |
| Fluoride | 68 | 0.1 – 0.22 mg/L | 2 mg/L secondary MCL |

One column now, because the file and the database agree. Until 2026-07-30 nitrate
read 121 and fluoride 58 once loaded — those two carried 24 of the 56 discarded
rows between them.

Those limits are listed here as context for a reader of this file. **The
platform does not print them beside a result and does not compute a verdict** —
see `drinking/models.py` on "prepare, never determine".

### A repeat is not always a repeat

**Fixed 2026-07-30 (ISS-102). Kept here because the reasoning binds any agency
loading its own SDWIS export, not just this file.**

The importer used to identify a result by (event, analyte, method) and drop a
second row matching one it already had. Over this file that discarded 56 rows as
duplicates — and on measurement, **not one of them was a duplicate**:

| Of the 56 dropped rows | Count |
|---|---|
| Carried a different `Result` | 27 |
| Same result, different `Reporting Level` | 26 |
| Same result, different `Analysis Date` | 3 |
| **Byte-identical to the row kept** | **0** |

Every one was a second laboratory analysis of the same water — a re-run at a
different sensitivity, on a different day, or reaching a different number. Which
of the two survived was decided by the order the rows happened to appear in.

Four of them were the sharp case, because a non-detect and a detection are not
two versions of a number, they are opposite answers:

| Analyte | Sampling point | Date | Reading that was discarded |
|---|---|---|---|
| Copper, free | `CA2410009_DST_LCR` | 2024-07-17 06:30 | 300 µg/L |
| Copper, free | `CA2410009_DST_LCR` | 2024-07-19 06:00 | 82 µg/L |
| Copper, free | `CA2410009_DST_LCR` | 2024-07-17 06:00 | 57 µg/L |
| Fluoride | `CA2410009_023_023` | 2025-08-26 08:30 | 0.11 mg/L |

Three are Lead and Copper Rule tap samples — the monitoring done at a resident's
tap specifically to catch copper — and the demo read *non-detect* at each.

**Both readings are now stored.** The guard still exists, because re-importing a
file must not double it; it now identifies a result by the WHOLE measurement
(`drinking.importer._IDENTITY_FIELDS`: the value, the limits, the unit, the
method, the laboratory, the analysis date). Two rows are one result only when
they say the same thing in every respect. Loading this file twice is still a
no-op; loading it once now keeps all 22,367 rows.

The 2024-07-17 06:30 tap sample carries two results today: a non-detect at a
50 µg/L reporting level, and 300 µg/L. The platform shows both and picks
neither, which is what *"prepare, never determine"* means when the source itself
carries two answers.

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
