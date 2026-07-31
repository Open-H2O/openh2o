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

**The two columns below are different questions, and they were being read as one
(ISS-096).** The left is what is in this file; the right is what
`seed_merced_drinking` puts in the database. Every gap between them is accounted
for underneath — none of it is loss.

| | In this file | Loaded by the seed |
|---|---|---|
| Window | 2023-05-21 → 2026-05-21 (exactly three years) | — |
| Results | 22,367 | **22,311** |
| Sample events | 334 by point and date | **559** by the platform's own key |
| Sampling points | 27 | 27 |
| Analytes | 159 distinct in the file | 159 carry a result, of **178** in the vocabulary |
| Non-detects | 21,615 | 21,584 |
| Detections | 752 | 727 |

*Measured 2026-07-30 by loading this file into an empty database, not carried
over from a previous version of this table.*

**Results: 22,367 − 56 = 22,311.** Fifty-six rows repeat an (event, analyte)
pair that another row already carries, and `drinking.importer` drops a repeat
rather than storing the same analysis twice. The seed prints the arithmetic as
it runs: *"22311 results ... 56 already present ... 0 rows skipped"*. The 56 land
on both quality columns — 31 non-detects and 25 detections, which is exactly the
21,615 → 21,584 and 752 → 727 gaps.

**Sample events: 334 and 559 are both counts of this file.** They are two
definitions, not a discrepancy. This table used to say 334, which collapses
every sample taken at one point on one day into a single event. The platform
keys an event on point + date + **time + sample type**
(`drinking/importer.py`), so a point sampled twice in a day is two collections,
which is what happened — and 559 is the count under that rule.

**Analytes: 159 is a property of this file; 178 is a property of the database.**
`Analyte` is a shared vocabulary, not a per-file tally. `seed_drinking` seeds 33
federal analytes from EPA's NPDWR table, this file contributes 159, and 14 names
appear in both — so a database holding both reads 178, of which the 159 from
here are the ones carrying a result. Do not read 178 as a count of anything in
this directory.

**The 97% non-detect rate is real and is deliberately kept.** Most drinking
water monitoring is the work of proving absence; a demo that showed only the
detections would misrepresent what the job actually looks like, and it would
hide the exact distinction `SampleResult.less_than_rl` exists to draw — a
`<0.5` row is the floor of the instrument, not a measurement of 0.5.

A selection of the detections, not all of them — `NITRATE-NITRITE` is a separate
analyte with 32 more, and is left out here only because nitrate tells the same
story. Counts follow the same two-column rule as the table above (measured
2026-07-30):

| Analyte | Detections in the file | Loaded | Range | For reference, the limit |
|---|---|---|---|---|
| Nitrate | 133 | 121 | 1.3 – 5.8 mg/L | 10 mg/L MCL |
| Arsenic | 24 | 24 | 2 – 8.1 µg/L | 10 µg/L MCL |
| Hexavalent chromium | 22 | 22 | 0.83 – 5 µg/L | CA MCL 10 µg/L, effective 2024-10-01 |
| Fluoride | 68 | 58 | 0.1 – 0.22 mg/L | 2 mg/L secondary MCL |

Nitrate and fluoride are the two largest groups among the 56 dropped rows — 12
each, with 5 more on free copper and the remaining 27 spread one apiece across
PFAS analytes — which is why only those two move here.

**The four ranges above are unchanged after loading, and that was checked rather
than assumed.** It does not follow from the dedup rule: 27 of the 56 dropped
rows carry a *different* `Result` than the row kept in their place, so a drop
CAN in principle move a minimum or a maximum. It does not happen to for these
four. See "A repeat is not always a repeat" below.

Those limits are listed here as context for a reader of this file. **The
platform does not print them beside a result and does not compute a verdict** —
see `drinking/models.py` on "prepare, never determine".

### A repeat is not always a repeat

Measured 2026-07-30, and worth knowing before quoting any figure derived from
the loaded data. `drinking.importer` treats a second row with the same (event,
analyte) as a duplicate and drops it. That is right for 29 of the 56, which
repeat the value already stored.

**The other 27 carry a different `Result` for the same point, date, time, sample
type and analyte.** They are re-analyses of one collection, not clerical
repeats, and the importer keeps whichever row it read first — which is really
whichever order the file happens to be in, since nothing in the data orders
them. Classified:

| Of the 56 dropped rows | Count |
|---|---|
| Repeat the value already stored | 29 |
| Two detections with different numbers | 20 |
| **Kept a non-detect, discarded a detection** | **4** |
| Kept a detection, discarded a non-detect | 3 |

The four in bold are the ones worth knowing about, because a non-detect and a
detection are not two versions of a number — they are opposite answers:

| Analyte | Sampling point | Date | Discarded reading |
|---|---|---|---|
| Copper, free | `CA2410009_DST_LCR` | 2024-07-17 06:30 | 300 µg/L |
| Copper, free | `CA2410009_DST_LCR` | 2024-07-19 06:00 | 82 µg/L |
| Copper, free | `CA2410009_DST_LCR` | 2024-07-17 06:00 | 57 µg/L |
| Fluoride | `CA2410009_023_023` | 2025-08-26 08:30 | 0.11 mg/L |

Three of those are Lead and Copper Rule tap samples, and the loaded demo now
reads *non-detect* at each of them.

None of it makes a figure in this file wrong, and no range in the tables above
moves (checked, not assumed). It is recorded because "56 already present" reads
as a clerical tidy-up, and 27 of them are an editorial choice about which of two
published numbers to keep. An agency loading its own SDWIS export inherits that
rule, and should get to decide whether it is the rule they want. Filed as
**ISS-102**.

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
