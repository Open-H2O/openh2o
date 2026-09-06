# Section D: the remaining subsystems (18 figures)

Eighteen figures across ten page templates and five parts of the platform: the
zone page, the monitoring stations, the wells, the recharge basins, and the
first two steps of the setup wizard. They are the long tail of the figure
ledger. Most of these screens carry one or two numbers, not twenty, and most of
those numbers are a stored value shown back to the reader rather than the
result of a calculation.

Section 1 of `docs/figure-ledger-2026-09.md` is the register this follows. The
number this section takes in the published ledger is Plan 135-03's to assign;
the identifiers below are fixed and come from the inventory.

**Screens and pins.** A figure inside a table renders once per row, so each one
is pinned to a named instance and the pin is recorded in
`audit/figure_ledger/screens-d.json`.

| Screen | What is pinned |
|---|---|
| `/map/zones/2/` | Halvern Irrigation-Urban GSA, the same district section 1 pinned on the dashboard, so the two screens can be laid side by side. The page has no year selector: its Allocation vs. use table lists every year at once, newest first, so the pinned row is the first, the water year running October 2025 to September 2026. Pinned parcel row: MER-APN-026, first by parcel number of the district's 23. |
| `/map/zones/1/`, `/map/zones/3/`, `/map/zones/39/` | The same three figures on every other district, captured so the finding below rests on four screens rather than one. |
| `/wells/32/` | Well MER-W-001, "Ag well on MER-APN-002". One screen carries all four wells figures: an irrigated parcel, a monitoring record with a reference elevation, a whole-number field and a two-decimal field. |
| `/recharge/6/` | El Nido Recharge Basin 1, first by name on the list. Pinned reading: the newest, 18 February 2026. Pinned recharge event: the newest, starting 15 February 2026. |
| `/recharge/` | The list shows every basin on one page in name order, so the pinned row is El Nido Recharge Basin 1 again. |
| `/setup/` | Merced Subbasin, the only district boundary on file. |
| `/datasync/stations/` and `/datasync/stations/1/` | Captured as evidence, not as figure sites. There is no station to open. |
| `/setup/confirm/` | Captured to record that it redirects rather than rendering. |

Captured at commit `9f9e27b25435`, 2026-09-05, into
`audit/figure_ledger/rendered/`, with each page's size and fingerprint in
`manifest-d.json`. Recomputed by
`bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/remaining_subsystems.sql`.

**One column needs a word of warning before the table.** `verdict` and `delta`
answer different questions. `delta` is arithmetic: did the number on the screen
equal the number worked out from the rows. `verdict` is judgment: what does that
agreement establish. Two rows below carry `delta` MATCH and `verdict`
UNVERIFIED, and that is not a contradiction. They are values a person typed into
the page. Reading them back proves the platform stored and redisplayed what was
typed. Nothing derives them, so nothing, including this ledger, can say whether
they are right.

| `id` | `screen` | `site` | `label` | `context_var` | `view` | `service` | `raw_tables` | `rendered` | `recomputed` | `delta` | `verdict` | `notes` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `FIG-datasync-001` | `/datasync/stations/<pk>/` | `templates/datasync/partials/_station_detail_pane.html:104` | Location (latitude, first half of the pair) | `station.location.y` | `datasync/views.py:318` | `— (model field)` | `datasync_monitoredstation` | not rendered | — | NO VALUE | UNVERIFIED | No station exists to open. `datasync_monitoredstation` holds zero rows, `/datasync/stations/` answers "No stations found.", and `/datasync/stations/1/` answered 404 at capture. This site and the next share one template line, one of the two lines in the platform that carry two figures. |
| `FIG-datasync-002` | `/datasync/stations/<pk>/` | `templates/datasync/partials/_station_detail_pane.html:104` | Location (longitude, second half of the pair) | `station.location.x` | `datasync/views.py:318` | `— (model field)` | `datasync_monitoredstation` | not rendered | — | NO VALUE | UNVERIFIED | Same line, same reason. |
| `FIG-datasync-003` | `/datasync/stations/<pk>/` | `templates/datasync/partials/_station_detail_pane.html:157` | Current readings, the newest published value per sensor | `r.value` | `datasync/views.py:320`, assembled at `:296-315` | `— (selection in the view: newest published reading per measured parameter)` | `datasync_datarecordstaging` | not rendered | — | NO VALUE | UNVERIFIED | Zero published readings exist, so this card would show its empty state even if a station did. |
| `FIG-datasync-004` | `/datasync/stations/<pk>/` | `templates/datasync/partials/_station_detail_pane.html:241` | Recent records, Value | `record.value` | `datasync/views.py:319`, queryset at `:237` | `— (model field)` | `datasync_datarecordstaging` | not rendered | — | NO VALUE | UNVERIFIED | Same reason. |
| `FIG-geography-001` | `/map/zones/2/` | `templates/geography/partials/_zone_detail_pane.html:128` | Allocation (AF) | `b.budget` | `geography/views.py:220`, assigned at `:216` | `— (arithmetic in the view)` | `accounting_allocationplan` | 750.32 | 750.32 | MATCH | MATCH | Independence: transcription. One stored allocation column, read back and rounded the same way. Agrees with the dashboard's Allocation for this district in section 1, which is a second screen showing the same stored number. |
| `FIG-geography-002` | `/map/zones/2/` | `templates/geography/partials/_zone_detail_pane.html:129` | Used (AF), with the word "pumped" beside it | `b.used` | `geography/views.py:221`, computed at `:197-204` | `billable_ledger` (`accounting/services.py:377`), then summed in the view | `parcels_parcelledger, geography_parcelzone` | 1313.07 | 1313.07 | MATCH | `ISS-###-pending` | Independence: restatement for the number, different identity for the finding. The page computes what it says it computes. What it says it is, it is not: of the 1,313.07 AF labelled "pumped", only 142.14 AF is groundwater. The other 1,170.93 AF is surface water delivered by canal, which the platform stores as a negative number and this figure therefore sweeps in. Detail below. |
| `FIG-geography-003` | `/map/zones/2/` | `templates/geography/partials/_zone_detail_pane.html:130` | Remaining (AF) | `b.remaining` | `geography/views.py:223` | `— (arithmetic in the view)` | `accounting_allocationplan, parcels_parcelledger, geography_parcelzone` | -562.75 | -562.75 | MATCH | `ISS-###-pending` | Independence: restatement. Allocation minus the figure above, so it inherits the same problem and turns it into a verdict: the page says this district is 562.75 AF over its groundwater budget. On its groundwater draw alone it is 608.18 AF under. The sign is wrong, not just the size. |
| `FIG-geography-004` | `/map/zones/2/` | `templates/geography/partials/_zone_parcels.html:30` | Area (acres) | `pz.parcel.area_acres` | `geography/views.py:275`, queryset at `:165-170` | `— (model field)` | `parcels_parcel, geography_parcelzone` | 12.74 | 12.74 | MATCH | MATCH | Independence: transcription. This partial has exactly one route that renders it for reading: as an include on the district page. Its two other routes both change data and accept POST only. |
| `FIG-recharge-001` | `/recharge/6/` | `templates/recharge/partials/_detail_pane.html:56` | Capacity (AF) | `site.capacity_acre_feet` | `recharge/views.py:119` | `— (model field)` | `recharge_rechargesite` | 637.10 | 637.10 | MATCH | MATCH | Independence: transcription. |
| `FIG-recharge-002` | `/recharge/6/` | `templates/recharge/partials/_detail_pane.html:128` | Recent measurements, Value | `m.value` | `recharge/views.py:122`, queryset at `:95-97` | `— (model field)` | `recharge_rechargemeasurement` | 315.26 | 315.26 | MATCH | MATCH | Independence: transcription. One column serves four different kinds of reading, each with its own unit, so the same figure is milligrams per litre on one row and feet on the next. The pinned row is a water quality reading in milligrams per litre. |
| `FIG-recharge-003` | `/recharge/6/` | `templates/recharge/partials/_event_history.html:22` | Volume (AF) | `event.volume_acre_feet` | `recharge/views.py:120`, queryset at `:82-84` | `— (model field)` | `recharge_rechargeevent` | 127.42 | 127.42 | MATCH | MATCH | Independence: transcription. |
| `FIG-recharge-004` | `/recharge/` | `templates/recharge/partials/_list_results.html:31` | Capacity | `site.capacity_acre_feet` | `recharge/views.py:60`, queryset at `:45` | `— (model field)` | `recharge_rechargesite` | 637 | 637 | MATCH | MATCH | Independence: transcription. Rounded to whole acre-feet here and to hundredths on the basin's own page, so the same basin reads 637 in the list and 637.10 one click later. Both are right; the list is choosing not to show the tenths. |
| `FIG-setup-001` | `/setup/confirm/` | `templates/setup/confirm.html:61` | Area, square miles | `area_sq_miles` | `setup/services.py:247` | `— (model field)` | `geography_boundary` | not rendered | 800.9 | NO VALUE | UNVERIFIED | The confirmation step reads the chosen boundary out of the visitor's session, which only the previous step's form submission writes. The capture performs page requests only, so this screen redirected rather than rendering. The recomputed value is recorded because the same stored field renders on the previous step and is verified there. |
| `FIG-setup-002` | `/setup/` | `templates/setup/wizard.html:66` | The district boundary dropdown: "Merced Subbasin (800.9 sq mi)" | `b.area_sq_miles` | `setup/views.py:115`, queryset at `:113` | `— (model field)` | `geography_boundary` | 800.9 | 800.9 | MATCH | MATCH | Independence: transcription, plus one genuinely independent check. The platform deliberately never computes this area, taking it from the uploaded file instead, on the reasoning that a computed figure would be OpenH2O's number rather than the district's. The database can compute it: the stored outline measures 800.949 square miles against the 800.948 the file states, a difference of about half an acre across an 800 square mile basin. |
| `FIG-wells-001` | `/wells/32/` | `templates/wells/partials/_detail_pane.html:146` | "1.00 fraction", beside the parcel the well irrigates | `wip.fraction` | `wells/views.py:188`, queryset at `:157` | `— (model field)` | `wells_wellirrigatedparcel` | 1.00 | 1.00 | MATCH | MATCH | Independence: transcription. The pinned well has one irrigated parcel, so "first row" is unambiguous. |
| `FIG-wells-002` | `/wells/32/` | `templates/wells/partials/_detail_pane.html:178` | Reference elevation, ft | `monitoring.reference_elevation_ft` | `wells/views.py:189`, fetched at `:158` | `— (model field)` | `wells_monitoringwell` | 182.4 | 182.4 | MATCH | MATCH | Independence: transcription. Only three of the district's 45 wells carry a monitoring record, and only two of those three carry a reference elevation, so this card is absent from most well pages. |
| `FIG-wells-003` | `/wells/32/` | `templates/wells/partials/_editable_field.html:24` | Year Pumping Began | `ef.value` (whole-number branch) | `wells/views.py:180` | `— (model field, read straight off the well)` | `wells_well` | 1987 | 1987 | MATCH | UNVERIFIED | Independence: transcription, and that is all it can be. This template renders whichever well field the page hands it, and every one of them is a value a person typed through the pencil control beside it. There is nothing to recompute it against. The two numbers agreeing shows the platform redisplays what was entered; it says nothing about whether 1987 is the year. This is the only whole-number field the platform has. |
| `FIG-wells-004` | `/wells/32/` | `templates/wells/partials/_editable_field.html:24` | Capacity (gpm) | `ef.value` (two-decimal branch) | `wells/views.py:180` | `— (model field, read straight off the well)` | `wells_well` | 2000.00 | 2000.00 | MATCH | UNVERIFIED | Same line as the row above, the second of the platform's two double-figure lines. Six well fields take this branch: capacity, depth, casing diameter, screen top, screen bottom and tested yield. The pin is capacity, the first of them in the page's own order. Same reasoning as above: nothing derives any of the six. |

## What section D found

**Thirteen of the eighteen figures agree with the rows behind them to the cent.
The other five could not be put on a screen at all.** No figure in this section
disagrees with its own arithmetic. One of them disagrees with its label, and
that is the finding worth acting on.

Six things the reconciliation turned up that a matching column does not show.

### 1. The district page counts canal water as pumping, and it changes who is over budget

The Allocation vs. use table on a district page has a column headed **Used
(AF)** with the word **pumped** printed beside every number. For a groundwater
allocation the platform builds that figure by adding up every negative entry in
the district's ledger for the year. Canal deliveries are stored as negative
numbers, by the same convention the rest of the platform uses, so they land
inside it.

The code's own comment says this figure is "the magnitude of the negative
extraction rows". The code applies no such filter, and the surface-water branch
eight lines below it does. So this is not a house convention: it is one branch
of one `if` doing something the branch beside it does not, in a file whose
comment says otherwise.

Here is what that costs, read off all four district pages captured, water year
2025-2026:

| District | Allocation | "Used ... pumped" as shown | Of which is canal water | Remaining as shown | Remaining on groundwater alone |
|---|---:|---:|---:|---:|---:|
| Halvern Valley GSA | 9,689.40 | 13,379.29 | 10,236.78 | **−3,689.89** | **+6,546.89** |
| Halvern Irrigation-Urban GSA | 750.32 | 1,313.07 | 1,170.93 | **−562.75** | **+608.18** |
| Verdano Island Water District GSA | 731.74 | 1,092.73 | 0.00 | −360.99 | −360.99 |
| MER Surface Service Area, Halvern ID (surface allocation) | 108,000.00 | 1,993.82 | n/a | 106,006.18 | n/a |

On two of the three groundwater districts the page reports a deficit where the
groundwater draw alone is a surplus. Not a rounding difference and not a
percentage: the sign is opposite. The third district takes no canal water, so
its figure is honest, which is why the fault is invisible to anyone who only
looks at one page.

This is the other end of the problem section 1 recorded on the dashboard. There,
adding the district table's Supplies column gave 31,223.56 AF against the panel's
17,458.35 AF, because 59 of the 76 parcels sit in two districts at once, a
groundwater agency's area and a surface water district's service area. Those 59
parcels are exactly the parcels whose canal deliveries land inside the
"pumped" figure here. One data shape, two screens, two different symptoms.

Both numbers in each row are correct arithmetic on the rows stored. Recorded as
`ISS-###-pending` against `FIG-geography-002` and `FIG-geography-003` for Plan
135-03 to file. This section does not diagnose it further and changes nothing.

### 2. A quarter of this section's figures have no screen to appear on

Four of the eighteen belong to the monitoring station page, and there is no
station. `datasync_monitoredstation` holds zero rows and
`datasync_datarecordstaging` holds zero readings. The station list renders its
empty state, "No stations found."; a request for the lowest possible station
answered 404 at capture.

That is worth stating precisely, because it is not the demonstration being
deliberately thin. The file that pins what this demonstration must contain,
`data/demo/expected_shape.json`, requires **335** stations and **30,217**
readings, both at tolerance zero, and describes them as "the demonstration's
frozen telemetry". Every other count this section touches reproduces its pin
exactly: 135 parcel-to-district memberships, 8 districts, 5,658 stream lines,
760 cached evapotranspiration records, 45 wells, 3 monitoring wells, 29
irrigated-parcel links, 12 meters, 7 recharge basins, 42 recharge events, 126
basin readings, 8 external data sources, 1 boundary. Two counts out of fifteen
are wrong and they are the two that would have populated this page.

So the monitoring section of this platform is, on this database, a set of pages
with nothing in them, and four figures nobody has ever seen render. Whether the
running database is meant to satisfy that file is Plan 135-03's question; what
is measured here is that it does not, in exactly two places.

The fifth unrendered figure is the setup wizard's confirmation step. It reads
the boundary a visitor chose out of their session, and only the previous step's
form submission puts it there, so a page request alone lands back at the start.
The figure itself is the same stored field the previous step shows, and that one
is verified.

### 3. Two thirds of these figures are values shown back, not values worked out

Twelve of the eighteen are a single stored column passed through a display
formatter. There is no calculation, no service, and nothing for a second opinion
to disagree with. For those rows the check reads the column, applies the same
rounding, and confirms the screen reports the row faithfully. Every one did.

That is a real property and worth having. It is not what most of this ledger is
for, and a reader should not read twelve MATCH verdicts as twelve audited
numbers. The two well fields are marked UNVERIFIED to make the distinction
impossible to miss, because those are typed in by a person through the pencil
control on the page, and the platform will store and redisplay whatever is
typed. The other ten are the same in kind: a basin's capacity, a parcel's
acreage, a well's reference elevation. Each is a fact about the district that
arrived with the district's own data.

The place this actually bites is the recharge basins. A basin's capacity, every
recharge event's volume, and every on-site reading are all stored values with no
derivation, so the entire managed aquifer recharge section of the platform is
unauditable by this method. The volumes do reach the accounting: recharge shows
up in the water balance and in the carry-over pools. But this ledger can confirm
only that the number in the balance is the number in the event record, not that
the event record is right.

### 4. The boundary area is the one stored figure with an independent answer

The setup wizard shows the district's area, and the platform deliberately
refuses to work that area out from the outline it holds. The reasoning is
written down and it is good: a computed area would be OpenH2O's number offered
as the district's. So the figure is whatever the uploaded file said.

The database will compute it, though, and it agrees: **800.949** square miles
measured off the stored outline against the **800.948** the file states. About
half an acre of difference across an 800 square mile basin. That is the only
figure in this section where a stored value could be checked against something
other than itself, and it held.

### 5. The independence guard passed on this section's work without reading it

`tests/test_figure_ledger_independence.py` collects the recomputation files it
finds and checks each one. Run first, it reported eight tests passed. It had
found two files, both belonging to section 1. This section's file was not among
them, because the application container carries no live link to the working
copy, so a file written on this machine does not exist inside it.

Eight green tests, none of them about the work being guarded. After copying the
file in, the run collects fourteen and this section's file passes all three
checks: no import of application code, no call to an application function, and a
header declaring which figures it recomputes.

The guard is sound. The instrument was simply not attached to the thing it was
pointed at, and it reported success either way. Anyone running it against a
recomputation written outside the container needs the copy step first, and the
count of collected tests is the tell: two files means four parameterised
checks plus two fixed ones.

### 6. Every page capture overwrites the previous run's index

`scripts/figure_capture.py` writes its list of captured pages to a fixed
filename in the output folder. Four sets of captures ran into that one folder,
so each run replaced the previous run's list. The saved pages themselves survive
because each carries its own name; only the index of what was captured, at what
size, with what fingerprint, is lost. This section's copy was preserved before
the overwrite as `manifest-d.json`, and the other three sections' copies are
beside it.

### On the drinking-water module, which has no rows here

A reader looking for the drinking-water system in this ledger will not find it,
and the reason is the best thing in the whole demonstration.

The only place that module touches the display formatter is a note inside a
template comment, explaining that lab results deliberately do not go through it.
Those results are real, published California public record, and they are carried
through the platform unaltered: no rounding, no unit conversion, no formatting
of any kind between the published record and the screen. There is no figure to
reconcile because nothing is done to the number.

Everything else in this section belongs to the invented groundwater district:
invented basin, invented districts, invented growers. No row above describes a
real water user.

## Files

- Recomputation: `audit/figure_ledger/sql/remaining_subsystems.sql`
- Pinned screens: `audit/figure_ledger/screens-d.json`
- Captured pages: `audit/figure_ledger/rendered/d-*.html`, indexed by `manifest-d.json`
- Results: `audit/figure_ledger/results/section_d.csv`, with the two halves in
  `rendered_section_d.csv` and `recomputed_section_d.csv`, and the four-district
  check in `zone_used_column_section_d.csv`
