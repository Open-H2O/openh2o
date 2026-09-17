# The reading register, 2026-09

*Written 2026-09-07 by Phase 140, Plan 02 of milestone v2.17 "Screens That Explain Themselves". Companion to `docs/reading-standard-2026-09.md` (the instrument) and `docs/page-pass-2026-09.md` (each page's purpose).*

**146 findings across 80 pages. Pages failing: 74 for the reader who does not work in water (L), 70 for the district engineer (E), 68 for both; 4 pass. Rows per owner phase: 141 → 4 · 142 → 8 · 143 → 99 · 144 → 35; ISS-143 is `decided: keep`.**

## The short version

What the walk found, in a page, before any table. Read this and skip the rest unless you are planning a phase.

**Three faults are on every signed-in page.** No page has a visible title: the only thing that reads as one is the last word of the breadcrumb, so a facility page is titled "012". The floating Feedback button sits over content, including a column header and one page's lead figure. And the sidebar carries an entry, "Onboard System", that a layperson cannot place. On 26 pages the sidebar lights nothing at all, so a reader cannot tell where they are.

**The dashboard's faults are the ones Brent named, and they rank 1 to 3.** The accounts table prints eight number columns as equals when three are the parts of a fourth and one is a balance; the panel above it is titled for an operation ("Supply vs. use") rather than the thing; its three figures are huge and the result is no bigger than its inputs. The account pages repeat all three faults in a second template, so the dashboard's fix carries to three more pages.

**Tables have one recurring fault: figures related by arithmetic printed as a flat row.** It appears on the dashboard, the account breakdown, the zone's allocation table, the diversion records (Diverted, Return flow, Retained), the shared-supply check's Gap column and the monitoring dashboard's tiles. Seven record pages bury the one figure they exist to show (a zone's Remaining, a right's Face value, a lab result) as a cell like any other. Elsewhere a table's biggest number is unnamed: a depth with no word for what is measured, a count nobody calls a count, a Totalizer with no unit.

**Maps: dots with no legend, and maps that ignore the list.** Surface Diversions and Recharge Areas open on unlabelled marks; four maps keep showing every mark after the list beside them is filtered; the main map's legend names three of eight zones and its Layers panel is cut off mid-word.

**Words: nine pages explain the water to an engineer, and one thing is called two names.** Sentences like "A crop drinks part of the water; the rest sinks past the roots" fail copy rule 11 on six Help pages, the dashboard, Water Years and Delivery Settings. A parcel is also a use area; a water year is also a period and a reporting period; Wells is also Extraction Wells; three Help entries carry different names from the pages they open. The About page spends four paragraphs praising another platform. Fourteen glossary entries point at Help pages by names the menu does not use.

**Two arithmetic defects fell out of reading.** The Allocations footer adds one 108,000 AF entitlement across two water years and prints 304,200 AF (ISS-164). The use-area page's ledger card ignores the selected period (ISS-165).

**What passes.** The login page, both import forms and the layout shell pass whole; and every page has surfaces that pass, recorded as PASS lines in the slice files (248 of them), so the register is not a list of everything.

**Who fixes what.** Phase 141 (4 rows): one stylesheet rule that flattens every table, plus two account-page templates that name utilities the stylesheet lacks. Phase 142 (8 rows): the dashboard, all of it, then Brent sees the whole page. Phase 143 (99 rows): every other table, tile row, filter bar, page head and map, in rank order below. Phase 144 (35 rows): the words and the sidebar, independent of the rest.

## How the rows were produced

Every one of the 80 census pages (`.planning/phases/137-water-balance-panel-and-page-pass/137-03-census.json`) was captured from staging at the production commit `241c22b` on 2026-09-07 with `scripts/reading_capture.py` (a real browser at 1440 pixels wide; a screenshot, the visible text and the rendered page for each). Four readers (Opus), one per census slice, judged the screenshots against the standard's Parts 2 and 3 and proposed rows; the three calibration pages kept their 140-01 rows, re-read and confirmed (0 disagreements of 22 on the dashboard and the ledger; one measurement corrected on Surface Diversions). One adjudicator (Fable) decided every proposed row against the standard: kept, merged (one cause across templates is one row, as ISS-162 is), reworded, or rejected (three, listed at the end). 
One clean auditor (Opus) with no project history sampled 10 rows with seed 231783 and re-read each page cold: 2 of 10 disagreed with the finding; the disagreements and how each was resolved are in `140-02-EVIDENCE.md` §4.

Six pages could not be rendered as themselves and are judged from their templates, marked † in the per-page table: `/setup/confirm/` and `/setup/run/` answer 302 without a wizard session; the three report pages answer 404 because staging's rebuilt demonstration holds no past report (that 404 page is itself R-060); `/accounts/logout/` redirects when visited signed out; `signup_closed.html` never renders because self-signup is open on staging. The layout shell `allauth/layouts/base.html` is a row with nothing to judge.

## The register

**Ranked by the standard's rule, not by hand:** `both` outranks `L` and `E`, which tie; within a band, a fault Brent already named (ISS-159) is pinned to the top in ISS-159's item order, then rows sort by blast radius (pages, descending), then by the page-pass verdict of their page (a page with a lead figure outranks one with several figures and none leading, which outranks a router or a form), then by filing order. Owner: `141` type scale (and a template naming a utility the stylesheet does not have) · `142` the dashboard's table and tile row · `143` other tables, tile rows, filter bars, page heads, maps · `144` prose, the wording of descriptions and of names (a crumb label, a menu entry, a record type called two things), sidebar.

| rank | id | page | surface | finding | aud. | read | blast radius | owner |
|---|---|---|---|---|---|---|---|---|
| 1 | R-007 | c1 `/accounting/dashboard/?period=2` | data table | The Active water accounts table heads eight numeric columns identically; nothing shows that Surface + Groundwater + Precip is Supplies, that Net is Supplies minus Consumptive Use, or that GW allocation and GW remaining are an allocation on paper from a different framework rather than water that moved. (ISS-159 #1) | both | 01 PNG; `_dashboard_content.html:117-126` | 1 page, 2 tables (the Zones table repeats the shape) | 142 |
| 2 | R-003 | c1 `/accounting/dashboard/?period=2` | tile row | The panel is titled 'Supply vs. use', which names an operation, not the thing; a reader cannot say from the title that this is the district's whole-basin position for the year. (ISS-159 #2) | both | 01 PNG; `templates/accounting/partials/_dashboard_content.html:18` | 1 page (title); `.budget-panel` renders on 3 data pages | 142 |
| 3 | R-004 | c1 `/accounting/dashboard/?period=2` | tile row | Three figures are set at the largest type on the page inside a panel far wider than they need, and the result (Balance) is set no larger than the two that make it, so nothing says which figure the page leads with. (ISS-159 #2) | both | 01 PNG; `_dashboard_content.html:21-51` | 1 page | 142 |
| 4 | R-016 | c10 `/accounting/ledger/?period=2` | filter bar | The filter is a full card of four rows (quick-filter chips; search, period and zone; a hidden advanced row; rows-per-page and jump-to-page) pinned to the top of the window as the reader scrolls, so reading one water year's entries costs a third of the screen in controls the reader will not touch. (ISS-159 #4) | both | 10 PNG; `ledger_list.html:53-245` | 1 page | 143 |
| 5 | R-018 | c10 `/accounting/ledger/?period=2` | data table | The columns run Date, Parcel, Amount, Source, Water Type, Description, and the reader cannot say why they are in that order; nothing in the header says a negative Amount is water leaving a canal or a well and a positive one is paper. That sentence is in the footer, a hundred rows down. (ISS-159 #4) | both | 10 PNG; `_ledger_list_results.html:17-62` | 1 page | 143 |
| 6 | R-058 | 69 pages (c1 …) | page head | The only visible title on any signed-in page is the last breadcrumb, set at the size of the description under it, so on a record page the screen's title is a bare code ('012' on a facility, 'Worksheet' on the CalWATRS page) and the record's own name sits far below it; the real title is hidden from sight on every page. | both | 22, 38, 40, 48 PNG; `templates/base.html:109` (the one `<h1>` is screen-reader-only) | `base.html`, 69 signed-in pages | 143 |
| 7 | R-025 | 11 pages (c10 …) | data table | Inside any data table the type scale does not exist: a text utility on a cell is discarded, so a date, a note and a headline figure render at one size and one brightness (the ledger's dates, the recharge card's field notes, the facility list's types all render as the figures beside them). (ISS-162) | both | 10, 53, 21 PNG; `static/css/app.css:918` vs `:2227,2186` | 105 cells in 36 templates | 141 |
| 8 | R-028 | 26 pages (c2 …) | sidebar | On 26 of the platform's 68 signed-in pages no sidebar entry lights at all, so the reader has no way to say from the sidebar where they are or get back: every accounting page but the dashboard and the ledger (the entry match misses their routes), the setup and health pages, the water-rights, infrastructure, users and profile pages (which have no sidebar entry to light), two Help pages the Help group has no entry for, and the demonstration-data page (About lights only on /about/). | both | the 26 PNGs; `grep 'sidebar-link active'` returns 0 on each capture; `templates/partials/_sidebar.html:62` reading `core/modules.py:238-248`; `_sidebar.html:76-140` | `partials/_sidebar.html`, 26 pages | 144 |
| 9 | R-145 | 8 pages (c59 …) | sidebar | The sidebar's Help group opens by itself on every Help page and on About, and the six entries it adds push its own last three (Configs Explained, Glossary, About) and the Operations/Admin toggle below the bottom edge of the sidebar at a 1440 × 900 window, so on the Glossary, Configs and About pages the entry that is lit is off the screen and the reader has nothing telling them where they are. | both | 59-66 PNG (each sidebar ends at 'Methods'); `templates/partials/_sidebar.html:73`; `static/css/app.css:213-223` | sidebar, 8 pages | 144 |
| 10 | R-055 | 7 pages (c19 …) | tile row | On seven pages the figure the page exists to produce is set no larger than the fields around it: Site Health's '8/13 healthy' is smaller than the card titles; the lab result '7.4 MG/L' is one of sixteen equal values; the shared-supply check's '8 sources · 3 flagged' is the smallest text on the page, inside the filter bar; and the zone's Remaining, the diversion's Diverted, the right's Face value and the recharge event's Volume are each one cell like any other, so nothing on the screen says which number the reader came for. | both | 19, 26, 37, 43, 49, 51, 53 PNG; `health/dashboard.html`, `drinking/result_detail.html`, `reporting/shared_supply_check.html`, `_zone_detail_pane.html`, `surface/partials/_diversion_records.html`, `_water_right_detail_pane.html`, `recharge/partials/_event_history.html` | 7 pages | 143 |
| 11 | R-031 | c3, c6, c9, c11, c31, c43 | page head | Six pages carry no description at all, only a breadcrumb over the content: the four accounting create forms (so nothing says what a name should look like or that dates run October to September), the Add Station form (whose first required field is 'Data source'), and the zone detail page (so a reader arriving on a zone gets no sentence saying what the numbers below are or what period they cover). | both | 03, 06, 09, 11, 31, 43 PNG; `surfaces.json` `page_description: 0` for each; `period_create.html`, `account_create.html`, `allocation_create.html`, `ledger_create.html`, `datasync/station_add.html`, `geography/zone_detail.html:15-24` | 6 pages | 143 |
| 12 | R-097 | c40, c44, c45, c49 | page head | The platform prints two names for one thing on the same screen: the description and the sidebar say 'use areas', the map's Layers panel says 'Parcels', and on the Use Areas list the same rows are counted as '76 parcels found' under the heading '76 USE AREAS IN THIS DISTRICT', so a reader cannot say whether a parcel and a use area are the same record. (ISS-161's class: one name per thing.) | both | 40, 44, 45, 49 PNG; `geography/map.html:22`; `parcels/list.html`; `parcels/partials/_detail_pane.html` | 4 pages | 144 |
| 13 | R-023 | c48, c23, c41, c52 | map | Filtering the list does not filter the map: the overview-map partials on Surface Diversions, Sampling Points, Zones and Recharge Areas install no listener for the list's swap, so after a search the list says '2 found' and the map still shows every mark (on Sampling Points the sentence above the map keeps saying '21 of 27' too). Read off the partials, not the screenshots: an interaction cannot be captured. (ISS-136's class) | both | 48, 23, 41, 52 HTML; `_pods_overview_map.html`, `_zones_overview_map.html`, `_recharge_overview_map.html`, `drinking/sampling_points.html:56-75` vs `:122-123` | 4 pages, 4 partials | 143 |
| 14 | R-086 | c34, c35, c36, c39 | body prose | The report page states four separate times, in four stacked panels, that OpenH2O does not submit to the state (the red demonstration notice, the 'OpenH2O prepares your filing' card, the handoff alert and the internal-status note) before the reader reaches a single figure. (Template only for the report page itself, which answered 404.) | both | `_report_detail_pane.html:47-67`, `_handoff.html:4-10`, `_status_section.html:3-5` | `_handoff.html` + `_status_section.html`, 4 pages | 144 |
| 15 | R-012 | c1 `/accounting/dashboard/?period=2` | sidebar | The crumb reads 'Accounting / Dashboard' but the sidebar has no section called Accounting; the lit entry sits in an unlabelled group with Home and Map, so a reader looking for Accounting in the sidebar cannot find it. | both | 01 PNG; `templates/partials/_sidebar.html:46-59`; `dashboard.html:9` | 3 templates carry the Accounting crumb | 144 |
| 16 | R-036 | c5, c6, c7 | filter bar | On the account pages the control that says which water year the figures cover renders its own text jammed against the box edge and overlapping, so the year the whole page depends on is the hardest thing on it to read. | both | 07 PNG; `_account_detail_pane.html:114-123` | 3 pages | 143 |
| 17 | R-038 | c5, c6, c7 | tile row | On the account pages Supplies, Consumptive use and Balance are set at one size, so nothing says the Balance is the figure the page exists to produce (R-004's fault in a second template). | both | 07 PNG; `_account_balances.html:7-23` | 3 pages | 143 |
| 18 | R-039 | c5, c6, c7 | data table | The account page's Per-Parcel breakdown heads six numeric columns identically, so nothing shows that Surface + Groundwater + Precip is Supplies or that Net is Supplies minus Consumptive Use (R-007's fault in a second template). | both | 07 PNG; `_account_balances.html:36-45` | 3 pages | 143 |
| 19 | R-032 | c4, c8, c9 | data table | The allocation tables' NAME column prints the zone, the water type and the water year run together, and the next three columns print those same three things again, so the reader reads the same words three times before reaching the one figure that differs. | both | 04, 08 PNG; `period_detail.html:124-136`, `partials/_allocations_list_results.html:15-32` | 3 pages | 143 |
| 20 | R-060 | c36, c38, c39 | page head | A URL that no longer resolves drops the reader out of the platform onto a bare white 'Not Found' page with no platform name, no navigation and no link back (the three report pages rendered this way on staging, whose rebuilt demo has no past report). | both | 36, 38, 39 PNG; no 404 template exists under `templates/` | every not-found URL on the deployment | 143 |
| 21 | R-141 | c72, c73, c74, c76 | page head | On the sign-up and password-reset forms every label sits hard on top of its box and the gold submit button touches the bottom edge of the last box, so the last field and the button read as one merged control and the reader cannot see where the form ends. (The spacing classes those templates name do not exist in the stylesheet, ISS-162's class of fault.) | both | 72, 74 PNG; `account/signup.html:33-37`, `account/password_reset.html:14-18`, `account/password_reset_from_key.html:22-26` | 3 templates | 141 |
| 22 | R-035 | c7, c36 | page head | A detail pane offers 'Open full page →' on the full page itself (the account page, and the report page by its template), so a reader who follows the only forward link in the head lands back on the screen they are already reading. | both | 07 PNG; `_account_detail_pane.html:33`; `reporting/partials/_report_detail_pane.html:42` (template only, 404 on capture) | 2 partials, 2 pages | 143 |
| 23 | R-054 | c17, c18 | page head | Reaching setup step 2 or 3 without a live wizard session drops the reader back on step 1 with nothing said, so the reader cannot say whether the wizard restarted, failed, or was never started. | both | 17, 18 PNG (both render /setup/); `setup/views.py:125-127`, `:150-152` | 2 pages | 143 |
| 24 | R-138 | c68, c69 | tile row | A reader cannot say what '10 of 42' counts: the line does not say that 42 is the stations left switched on rather than the stations that exist, and the anonymous branch of the same front page prints 'Monitoring stations 335', so the platform gives two counts of its monitoring stations eight times apart with nothing distinguishing them. | both | 68 PNG, 71 PNG (the anonymous render of /); `home.html:22-23` vs `index.html:61`; `config/views.py:61,95-97` | 2 pages | 143 |
| 25 | R-014 | c10, c11 | body prose | Four sentences across two screens give four conventions for the same numbers: the ledger's description says positive amounts are supply, its inset says the running balance is allocation minus usage, its footer says credits are paper and never netted, and the New Entry form says positive amounts 'represent supply (recharge, allocation)', a flat contradiction of the footer. The reader is left to reconcile them. | both | 10, 11 PNG; `templates/accounting/ledger_list.html:13,44`; `partials/_ledger_list_results.html:118-122`; `ledger_create.html` (sign-convention card) | 2 pages | 144 |
| 26 | R-041 | c8, c9 | data table | With no period chosen the Allocations footer adds the same allocation in two different water years into one figure, so the largest number on the page, 304,200.00 AF of surface water, counts a single 108,000.00 AF entitlement twice and is not an amount anyone manages. (Filed as ISS-164 as well: a wrong sum, ISS-156's class along the other axis.) | both | 08 PNG and TXT (148,500 + 155,700 = 304,200); `_allocations_list_results.html:52-65` | 2 pages | 143 |
| 27 | R-100 | c42, c54 | map | The map the reader is told to draw on opens on a fixed point in the mountains (Mammoth Lakes, Madera and Clovis are the only places named) and draws no district boundary, so a reader cannot see where their own district is before drawing. | both | 42, 54 PNG; `geography/zone_create.html:109-110`; `infrastructure/add.html:402-403` | 2 pages | 143 |
| 28 | R-132 | c58, c66 | page head | Two pages have no breadcrumb strip at all and their real heading is hidden from sight: on Profile the only name on the screen is a card heading, and on About the first words a reader sees are the demo notice, so neither page says where the reader is or offers a link back. | both | 58, 66 PNG; `core/profile.html:1-4` (no breadcrumbs block); `about.html:8-17`; `base.html:109` | 2 pages | 143 |
| 29 | R-006 | c1 `/accounting/dashboard/?period=2` | body prose | The inset 'How this summary works' states the relation the table beneath it does not show (three supplies meet consumptive use), in prose between the panel and the table, belonging to neither; once R-007 is fixed this sentence is either redundant or the caption. | both | 01 PNG; `_dashboard_content.html:60-65` | 1 page | 144 |
| 30 | R-052 | c17 `/setup/confirm/` | tile row | The setup wizard's confirm step adds basins and flowlines into one figure under the label 'Existing data', so the reader cannot say what the number counts or how many of each it found. (Template only: the page answered 302.) | both | `templates/setup/confirm.html:64-68` | 1 page | 143 |
| 31 | R-077 | c32 `/datasync/stations/1/` | tile row | The station page's lead surface, the Telemetry panel, draws a full-height empty grid with an axis running 0 to 1.0 for a station that has never reported, so the page shows a scale no reading produced and a reader cannot say whether the values are zero or absent. | both | 32 PNG; `datasync/station_detail.html` (telemetry panel) | 1 page | 143 |
| 32 | R-090 | c37 `/reporting/reports/shared-supply-check/` | data table | The rule that flags a shared-supply row is stated in percentage points ('gap threshold 15 points') while the Gap column prints a decimal fraction (0.0804), so a reader has to convert before they can tell why one row is flagged and its neighbour is not. | both | 37 PNG; `shared_supply_check.html` (toolbar meta and Gap column) | 1 page | 143 |
| 33 | R-101 | c43 `/map/zones/2/` | data table | The zone's Allocation vs. use table prints Allocation, Carried forward, Used and Remaining as one flat row of like figures although the fourth is the first three worked out, and the sentence that says so is hidden behind a '?' the reader has to find. | both | 43 PNG; `geography/partials/_zone_detail_pane.html` (Remaining tooltip) | 1 page | 143 |
| 34 | R-102 | c43 `/map/zones/2/` | map | The zone's map shows the zone's outline and nothing else, while the list beneath it names twenty-three assigned use areas, so a reader cannot see on the map which parcels the page says belong to this zone. | both | 43 PNG; `_zone_detail_pane.html:164-176` | 1 page | 143 |
| 35 | R-104 | c43 `/map/zones/2/` | body prose | The zone's year-end setting calls the zone 'this district' and describes its unused surface-water allotment, while the head calls the same thing a Management Area and the only table on the page shows groundwater, so a reader cannot say what the setting acts on. | both | 43 PNG; `_zone_detail_pane.html` (Year-end unused water block) | 1 page | 144 |
| 36 | R-107 | c45 `/parcels/11/` | filter bar | The use-area page's water balance is set to WY 2025-2026 while the ledger card beside it lists entries from October 2024 to June 2025 under 'Recent ledger entries', so two surfaces on one screen answer for different years and neither says which. (Filed as ISS-165 as well: the card's query never filters on the period.) | both | 45 PNG; `parcels/views.py:116`; `parcels/partials/_detail_pane.html:309-345` | 1 page | 143 |
| 37 | R-108 | c45 `/parcels/11/` | data table | The use-area page's ledger card prints 241.56 and -36.55 in one Amount column with nothing on the card saying what a negative amount is, so a reader cannot say whether a minus sign means water leaving or a correction (R-018's fault on a second page). | both | 45 PNG; `_detail_pane.html:326-345` | 1 page | 143 |
| 38 | R-109 | c45 `/parcels/11/` | body prose | The same 330.37 AF appears twice within a hand's width on the use-area page, once as the Residual marked Deficit and once as 'Water use recorded, no supply reported', and nothing says the two are one quantity, so a reader may read the shortfall as counted twice. (A reading finding, not ISS-158's data question: the arithmetic is right and the screen is what misleads.) | both | 45 PNG; `_detail_pane.html` (balance panel foot and the finding line beneath) | 1 page | 144 |
| 39 | R-115 | c49 `/surface/diversion/9/` | data table | The diversion page's records table prints Diverted, Return flow and Retained as one flat row of like figures although the third is the first two worked out, so a reader cannot see that 584.98 retained is 584.98 diverted less nothing returned. | both | 49 PNG; `surface/partials/_diversion_records.html` | 1 page | 143 |
| 40 | R-117 | c49 `/surface/diversion/9/` | page head | The diversion page's description promises compliance information and the only compliance on the screen is a closed 'Compliance details' strip at the very bottom, so a reader cannot say whether this diversion is within its right without opening it. | both | 49 PNG; `surface/pod_detail.html` (collapsed block) with the head's description | 1 page | 143 |
| 41 | R-121 | c51 `/surface/rights/6/` | data table | The water-right page shows a right authorising 60,000 AF and twelve diversion records over eight months (Feb–Sep 2026) against it, and nothing adds the records up or sets them against the authorisation, so a reader cannot say from this screen how much of the right has been used. | both | 51 PNG; `_water_right_detail_pane.html` (Right information vs Recent diversion records) | 1 page | 143 |
| 42 | R-126 | c53 `/recharge/1/` | data table | The recharge basin's Recent measurements puts four different quantities in one Value column (a water-quality reading in mg/L, a depth in feet, a flow in cfs and a rate in inches per hour), ordered only by date, so a reader who came for the water levels has to pick them out of a mixed list. | both | 53 PNG; `recharge/partials/_event_history.html` (Recent measurements block) | 1 page | 143 |
| 43 | R-127 | c53 `/recharge/1/` | body prose | The recharge basin's Site information card says the basin is filled by a canal intake while every row of Event history is labelled Water type 'Groundwater', and nothing on the page says which sense of the phrase is meant, so a reader cannot say where the water in those events came from. | both | 53 PNG; `recharge/partials/_detail_pane.html` vs `_event_history.html` | 1 page | 144 |
| 44 | R-137 | c68 `/` | tile row | On the signed-in front page the largest words are the agency's name and 'Good morning'; the one figure the page exists to give, '10 of 42 stations reporting', is set small and grey underneath them, so the row's title names a time of day rather than the thing being summarised and nothing says which number the page leads with. | both | 68 PNG; `home.html:19-23` | 1 page | 143 |
| 45 | R-042 | c10 `/accounting/ledger/?period=2` | filter bar | A period filter is applied and the result line still reads only '1130 entries', so the reader cannot say from it whether they are looking at one water year or all of them. | both | 10 PNG; `ledger_list.html:41-46` | 1 page | 143 |
| 46 | R-079 | c33 `/datasync/monitoring/` | tile row | On the monitoring dashboard 'On schedule 10' and 'Behind schedule 32' are the two parts of 'Active stations 42' and print as a flat row of three like figures, with nothing showing that the last two are what the first is made of. | both | 33 PNG; `datasync/partials/_monitoring_content.html:14` onward | 1 page | 143 |
| 47 | R-081 | c33 `/datasync/monitoring/` | tile row | Five of the six source cards are stamped 'Not yet synced' while the same card counts active stations whose readings appear a month old on the station list, so a reader cannot say what 'Not yet synced' is telling them. | both | 33 PNG, 30 PNG; `datasync/partials/_status_pill.html` | 1 page | 143 |
| 48 | R-110 | c46 `/wells/` | data table | Each well row's one figure is printed as '340.00 ft' with no word anywhere saying what is being measured, so a reader cannot say whether the column is the depth of the hole, the depth to water, or something else. | both | 46 PNG; `wells/partials/_list_results.html` | 1 page | 143 |
| 49 | R-118 | c50 `/surface/rights/` | data table | One of the seven water-right rows carries a 'DEMO' badge in its Status cell while all seven identifiers end in -DEMO and a banner above already says the whole dataset is mixed, so a reader cannot say what the badge marks out. | both | 50 PNG; `surface/partials/_list_results.html` with `surface/partials/_status_badge.html` | 1 page | 143 |
| 50 | R-124 | c52 `/recharge/` | map | The recharge map shows two faint purple marks for the seven sites the list counts, with no labels and no legend, so a reader can neither say what a mark is nor find the seven the page says are there (R-022's fault with a count mismatch added). | both | 52 PNG; `recharge/list.html` with `recharge/partials/_recharge_overview_map.html` | 1 page | 143 |
| 51 | R-139 | c69 `/?anon` | page head | The anonymous front page has no title and no crumb, and its one line of description tells a signed-out visitor 'Overview of your water data. Each card counts one kind of record and links to where you manage it', when the visitor owns none of it and every 'View all …' link and every sidebar entry answers with a login form. | both | 71 PNG (the anonymous render); `index.html:16` | 1 page | 144 |
| 52 | R-140 | c69 `/?anon` | tile row | The anonymous front page's card grid is four columns wide and its last two rows use two of them and one of them, leaving half of one row and most of another empty; the final full-width card carries a single label, 'System status', with its status dot printed hard against the first letter. | both | 71 PNG; `index.html:59-78` | 1 page | 143 |
| 53 | R-044 | c11 `/accounting/ledger/create/` | body prose | The sentence that tells the reader what a positive or negative amount means sits below the Create button, well under the Amount box it governs, so the reader types the figure before meeting the rule for its sign. | both | 11 PNG; `ledger_create.html` (the sign-convention card, after the form's footer) | 1 page | 144 |
| 54 | R-048 | c14 `/accounting/delivery-settings/` | body prose | Delivery Settings says the settings are 'Set once for the whole agency' and the panel under it says 'a single district can differ from the default', so the reader cannot say what the page governs, and 'district' means the whole agency on the Accounts page ('11 accounts in this district'). | both | 14 PNG; `delivery_settings.html` vs `partials/_account_detail_empty.html` | 1 page | 144 |
| 55 | R-050 | c15 `/accounting/methodology/` | page head | Step 2 shows 'Fraction (method = fraction)' and 'Soil storage (in) (method = USDA-SCS)' side by side while only one method is selected, so the reader cannot say which of the two boxes is the live one. | both | 15 PNG; `_methodology_steps.html` | 1 page | 143 |
| 56 | R-065 | c22 `/drinking/facilities/1/` | body prose | The first panel on the facility page is four lines explaining why there is no map, above the record the page is about, so the first thing a reader reads is about something the screen does not show. | both | 22 PNG; `drinking/facility_detail.html` (no-coordinate branch) | 1 page | 144 |
| 57 | R-074 | c30 `/datasync/stations/` | map | The station list arrives already filtered to syncing stations while the map draws the whole network, dormant stations included, so on first load the map shows more stations than the '42 stations' the list counts and nothing on the page says why the two disagree. (ISS-136's class, visible without any interaction.) | both | 30 PNG; `datasync/station_list.html:43`, `datasync/partials/_freshness_map.html` | 1 page | 143 |
| 58 | R-087 | c36 `/reporting/reports/3/` | tile row | On the report page the download, which is what the page exists to produce, is the fourth of four equal metadata fields, set in the same small type as the 'Generated' timestamp beside it. (Template only.) | both | `_report_detail_pane.html:70-100` | 1 page | 143 |
| 59 | R-095 | c40 `/map/` | map | The map's legend names three zones in three near-identical greens while the Layers panel beside it counts eight GSA Zones, so a reader cannot say which shape on the map is which zone, nor why five are unnamed. | both | 40 PNG; `geography/map.html:501-505`; `geography/views.py:71-79` | 1 page | 143 |
| 60 | R-096 | c40 `/map/` | filter bar | The map's Layers panel is sliced through the word 'MONITORING' at its bottom edge with nothing saying the panel scrolls, so a reader looking for monitoring stations sees a cut-off word and no layer. | both | 40 PNG; `static/css/map-engine.css:77`; `static/js/map-engine.js:240-266` | 1 page | 143 |
| 61 | R-111 | c47 `/wells/10/` | data table | The well page's Totalizer column runs above forty thousand with no unit in the header, while the column beside it says Delta (AF), so a reader cannot say what the big number measures. | both | 47 PNG; `wells/measurement_history.py` via `wells/partials/_detail_pane.html` | 1 page | 143 |
| 62 | R-114 | c47 `/wells/10/` | data table | The well page's Irrigated parcels card prints '1.00 fraction' beside the parcel, and nothing says a fraction of what, so a reader cannot say what share the figure is a share of. | both | 47 PNG; `_detail_pane.html` (Irrigated parcels block) | 1 page | 143 |
| 63 | R-133 | c59 `/help/getting-started/` | body prose | Getting Started's Setup Wizard card says the wizard does 'Steps 2, 3, 9, and 10', but Step 10 is headed 'Add surface diversions and recharge areas' and its own eyebrow says only 'the Setup Wizard imports recharge basins for you', so the reader cannot say whether the wizard did the surface-diversion half of that step or left it for them. | both | 59 PNG; `help/getting_started.html:67` vs `:277-278` | 1 page | 144 |
| 64 | R-134 | c60 `/help/glossary/` | body prose | Fourteen glossary definitions end by pointing at a Help page by a name the platform does not use anywhere the reader can click: 'See Help > Allocations & Ceilings' and 'See Help > Surface Delivery Settings' name pages the Help menu has no entry for, and 'See Help > How Water Balances Work' and 'See Help > Configs & Settings, explained' name pages whose menu entries read 'Water Balance Info' and 'Configs Explained'. | both | 60 PNG; `config/views.py:532-565`; `templates/partials/_sidebar.html:76-140` | 1 page, 14 definitions | 144 |
| 65 | R-021 | 7 pages (c48 …) | page head | The Import and Add buttons sit in a row of their own under the description, leaving a wide empty band between the words and the buttons; the spacing reads as avoiding a collision rather than using the space. Confirmed rendering on seven list pages. (ISS-159 #5) | E | 48, 05, 25, 30, 41, 46, 52 PNG; `templates/surface/pod_list.html:25-30` and the six sibling list heads | 7 pages render the band (of 10 templates carrying a head `row-end`) | 143 |
| 66 | R-013 | c1 `/accounting/dashboard/?period=2` | sidebar | Under Drinking Water an entry reads 'Onboard System', a software verb a layperson cannot place; nothing nearby says it is where a system's records are first loaded. | L | 01 PNG; `core/modules.py:857` | sidebar, 69 pages | 144 |
| 67 | R-024 | 14 pages (c1 …) | page head | The floating Feedback button sits over the content's right edge on every page; it covers the 'RECORDS' header on Surface Diversions, the zone page's own lead figure (Remaining 911.58), the 'Syncing' column header on Monitoring Stations, and turns 'Direct Use' into 'Use' on a water right. | E | 48, 43, 30, 51 PNG; `templates/partials/_feedback_widget.html` via `templates/base.html:132` | every page that extends `base.html`, 67 templates | 143 |
| 68 | R-002 | 14 pages (c1 …) | page head | Two demo notices sit one above the other (the full banner, then a bare DEMO pill), and the second says nothing the first did not. | L | 01, 33, 38 PNG; `templates/base.html:115` + `partials/_demo_marker.html` | `_demo_marker.html`, 14 pages | 143 |
| 69 | R-026 | 9 pages (c1 …) | body prose | Nine pages each carry a sentence that explains the water to the engineer who reads it (copy rule 11): the dashboard inset says crop demand 'is met by three supplies'; Water Years says 'Most agencies use the water year (October through September)'; Delivery Settings says 'The rest soaks back into the aquifer. Typical: 75%'; the glossary defines Effective Precipitation and converts CFS to acre-feet per day; Allocations & Ceilings defines the acre-foot; Surface Delivery Settings says 'A crop drinks part of the water; the rest sinks past the roots and recharges the aquifer'; Water Balances says 'it's how irrigation actually behaves'; Methods says 'Rain that actually soaked in and was available to the crop'; Configs says 'the rest sinks past the roots and recharges the aquifer, typically around 75%'. | E | 01, 02, 14, 60-65 PNG; `_dashboard_content.html:60-65`, `periods_list.html:12`, `delivery_settings.html`, `config/views.py:538,546`, `help/budgets_allocations.html:50`, `help/surface_deliveries.html:38`, `help/water_balances.html:90`, `help/methods.html:94`, `help/settings_explained.html:82`; two more one click away in collapsed disclosures at `help/methods.html:122`, `help/settings_explained.html:74` | 9 pages | 144 |
| 70 | R-142 | 9 pages (c71 …) | page head | Nine of the ten account pages carry no OpenH2O name or mark anywhere on the screen (only the login page has one), so a visitor who arrives at 'Create account', 'Reset password' or 'Verify your email' from an emailed link cannot say what they are creating an account on except from a footer line in the smallest type on the page. | L | 72, 74-79 PNG; `account/login.html:6-9` is the only brand block; `base_auth.html:26-30` | 9 templates | 143 |
| 71 | R-143 | 9 pages (c71 …) | page head | The titles on the account pages ('Create account', 'Reset password', 'Check your email', 'Verify your email') render around three times the height of their own body text and larger than any page title elsewhere in the platform, so a reader crossing from the login page to the sign-up page cannot tell the two are the same kind of screen. (The heading class those templates name does not exist in the stylesheet, so the browser's own heading size is used.) | L | 72, 74-79 PNG against 70 PNG; every account template heads its `<h1>` with `text-xl` | 9 templates | 141 |
| 72 | R-029 | c2, c3, c4, c5, c6, c7 | page head | One record type carries a different name in the crumb, the count line, the button, the back link and the form heading, so a reader cannot say whether a 'water year', a 'period', a 'reporting period' and a 'new water year' are one thing or four; the accounts pages do the same with 'Accounts', 'Water Accounts' and 'water account'. | L | 02, 03, 06 PNG; `periods_list.html:11`, `partials/_periods_list_results.html:5`, `period_create.html`, `account_create.html` | 6 pages | 144 |
| 73 | R-112 | c43, c47, c49, c54 | data table | On four record pages one column of the two-column body runs out while the other runs on, leaving a tall empty column beside a long stack of tables, so a reader comparing two of those tables scrolls instead of looking across. | E | 43, 47, 49, 54 PNG; `geography/zone_detail.html`, `wells/detail.html`, `surface/pod_detail.html`, `infrastructure/add.html` | 4 pages | 143 |
| 74 | R-037 | c5, c6, c7 | tile row | The account balance panel's foot lists Surface, Groundwater and Rain with nothing saying they are the three parts of the Supplies figure above them (R-005's fault in a second template). | L | 07 PNG; `partials/_account_balances.html:24-28` | 3 pages | 143 |
| 75 | R-040 | c5, c6, c7 | data table | Both tables on the account page run MER-APN-021, 023, 024 … 038 and then 022 and 031 at the end, so a reader cannot say what order the rows are in and the two stragglers read as an error. | E | 07 PNG; `_account_balances.html:48`, `_parcel_assignment.html` | 3 pages | 143 |
| 76 | R-053 | c16, c17, c18 | page head | The setup wizard gives its own steps different names in different places (step 2 is 'Confirm' in the step bar and 'Confirm Boundary' in the crumb; step 3 is 'Populate', 'Running', 'Running Setup' and 'Population progress'), so a reader cannot say whether they are on the step the bar is pointing at. | L | 16 PNG; `setup/wizard.html:5`, `setup/confirm.html:5,17,36`, `setup/run.html:4,11,34,40` | 3 pages | 144 |
| 77 | R-059 | c24, c25, c26 | body prose | Wherever a lab finding is shown it can read '< 0.5 UG/L', and nothing on any of those pages says the '<' means the laboratory could not measure below that level rather than that the value is 0.5. | L | 24, 25, 26 PNG; `drinking/partials/_result_value.html:25` | `_result_value.html`, 3 pages | 144 |
| 78 | R-098 | c41, c42, c43 | sidebar | On the zone pages the sidebar lights 'Map' while the page head reads 'Administration / Zones', because the Zones entry itself sits on the sidebar's other tab (Admin), so the lit entry and the page's own name are different words. (ISS-133 as it renders today: the two-entries-lit fault is masked by the tab, not fixed.) | E | 41 PNG; `templates/partials/_sidebar.html:62`, `:143-146`; `core/modules.py:378,386` (Map has no exclusion for /map/zones) | 3 pages | 144 |
| 79 | R-033 | c4, c8, c9 | data table | No allocation name is a link, and on the Allocations list the only link in a row is the water year, so the way in leads away from the record the row is about while account and parcel names elsewhere are links. | E | 04, 08 PNG; `period_detail.html:133`, `_allocations_list_results.html:25` | 3 pages | 143 |
| 80 | R-146 | c63, c64, c65 | sidebar | Three of the Help group's entries carry a different name from the page they open ('Water Balance Info' opens 'How Water Balances Work', 'Methods' opens 'Methods Behind the Numbers', 'Configs Explained' opens 'Configs & Settings, explained'), and the glossary's own cross-references use the page names, not the menu names. | E | 63, 64, 65 PNG; `_sidebar.html:98,111,119` against each page's crumb | sidebar, 3 pages | 144 |
| 81 | R-072 | c28, c29 | sidebar | The lit sidebar entry on both onboarding pages reads 'Onboard System' while the page heads read 'Onboard' and 'Sampling Points', so the sidebar's name for the page never matches the page's own (and on the second, the entry called 'Sampling Points' is not the one lit). | E | 28, 29 PNG; `core/modules.py:857` vs the two crumb blocks | 2 pages | 144 |
| 82 | R-099 | c41, c42 | data table | The Zones table's Type column labels five of the eight rows 'Custom' and three 'Management Area', and nothing on the page (or on the create form that offers the same choices) says what the platform does differently with each, so a reader cannot say what kind of thing a Custom zone is. | L | 41 PNG; `geography/zone_list.html:66-75`; `geography/zone_create.html:48-49` | 2 pages | 144 |
| 83 | R-105 | c44, c46 | data table | On the Use Areas and Wells finders six of the rows are in view, in a narrow column that scrolls inside itself, while two thirds of the screen holds a placeholder telling the reader to pick one, so finding a record means working a six-row window. | E | 44, 46 PNG; `parcels/list.html`, `wells/list.html` | 2 pages | 143 |
| 84 | R-106 | c44, c46 | filter bar | On the same two finders the two filter controls are stacked one above the other at the top of that narrow column and take about a quarter of its height, so the controls cost the reader rows they could otherwise see. | E | 44, 46 PNG; `parcels/list.html`, `wells/list.html` | 2 pages | 143 |
| 85 | R-030 | c2, c8 | page head | The page's one action ('+ New water year', '+ New allocation') sits inside the search card beside the search box rather than with the title, so a reader who learned on the Accounts page that actions live under the description looks in the wrong place. | E | 02, 08 PNG; `periods_list.html:20-40` (the `toolbar-row` idiom) | 2 pages | 143 |
| 86 | R-061 | c35, c36 | page head | The reporting pages carry a second demonstration notice, in red and larger type, directly under the page's own demonstration banner, so a reader is warned twice about the data before being told what the screen does (R-002's class). | L | 35 PNG; `reporting/report_generate.html`, `reporting/partials/_report_detail_pane.html:47-58` | 2 pages | 143 |
| 87 | R-128 | c54, c55 | page head | The infrastructure pages' crumb begins 'Extraction Wells', a name that appears nowhere else in the platform (the sidebar, the list page and its crumb all say 'Wells'), so a reader cannot tell that the section they are in is the one the sidebar calls Wells; the crumb word and the back link do lead there. | L | 54, 55 PNG; `infrastructure/add.html`, `infrastructure/import.html` (breadcrumb blocks) | 2 pages | 144 |
| 88 | R-144 | c76, c79 | page head | On the expired-link screens the title still names the action the page has just refused: the biggest words are 'Set new password' above 'This reset link is invalid or has expired', and 'Confirm email' above 'This confirmation link is invalid or has expired', so the reader's first read of the page says the opposite of its second. | L | 76, 79 PNG; `account/password_reset_from_key.html:5-8`, `account/email_confirm.html:5,15` | 2 templates | 143 |
| 89 | R-001 | c1 `/accounting/dashboard/?period=2` | page head | The page's one control, the Period selector, sits below two demo notices and away from the title, so a reader asking which year they are looking at finds the answer third, in a small badge on the panel. | E | 01 PNG; `templates/accounting/dashboard.html:73-87` | 1 page | 143 |
| 90 | R-005 | c1 `/accounting/dashboard/?period=2` | tile row | The panel's foot lists Surface 11,407.71, Groundwater 4,377.38 and Rain 1,673.27 with nothing saying they are the three parts of the Supplies figure above them. | L | 01 PNG; `_dashboard_content.html:52-56` | 1 page | 142 |
| 91 | R-008 | c1 `/accounting/dashboard/?period=2` | data table | At a 1440-pixel window the accounts table's last column is clipped, header and values alike (957, -320, 610, -508, -1,002 all cut mid-figure), and the Zones table's last two columns are off-screen entirely, so the column an engineer came for is lost until they discover the card scrolls sideways. | E | 01 PNG; `_dashboard_content.html:113,194` | 1 page, 2 tables | 142 |
| 92 | R-009 | c1 `/accounting/dashboard/?period=2` | data table | Zone names are plain text while the account names in the table above are links, so half the names on the page are a way in and half are not. (ISS-163) | E | 01 PNG; `_dashboard_content.html:215` vs `:134` | 1 page | 141 |
| 93 | R-010 | c1 `/accounting/dashboard/?period=2` | data table | The Zones table mixes two kinds of row, two GSAs with a groundwater budget and five 'MER Surface Service Area' rows that print a dash in every budget column, and nothing on the page says why half the rows have dashes. | L | 01 PNG; `_dashboard_content.html:213-259` | 1 page | 142 |
| 94 | R-011 | c1 `/accounting/dashboard/?period=2` | tile row | The Drinking Water card's corner code 'CA2410009' is not named as the state's public water system number, so a reader cannot say what the code is. | L | 01 PNG; `templates/drinking/partials/_dashboard_card.html` | 1 page | 142 |
| 95 | R-027 | c1 `/accounting/dashboard/?period=2` | tile row | The Drinking Water card is titled 'CITY OF MERCED', a place name, so nothing says what its four figures are before the reader has read them, and the biggest of them, 22,367, is a count of stored sample rows. | L | 01 PNG; `templates/drinking/partials/_dashboard_card.html` | 1 page | 142 |
| 96 | R-045 | c13 `/accounting/calculation-run/11/2026-09/` | page head | The calculation page's head reads 'Methodology: Default Methodology (a3fee261ef37)' and nothing says what the twelve-character code is, so a reader cannot say whether it identifies a version, a run or a record. | L | 13 PNG; `calculation_run_detail.html` (head card) | 1 page | 143 |
| 97 | R-046 | c13 `/accounting/calculation-run/11/2026-09/` | data table | Step 2's DETAIL cell reads 'usda_scs: −0.3168 AF effective precip', printing a machine key in the one column on the page written for a person to read. | L | 13 PNG; `calculation_run_detail.html` (steps table) | 1 page | 143 |
| 98 | R-047 | c13 `/accounting/calculation-run/11/2026-09/` | data table | Step 1 shows '122.07 mm × 109.80 ac' producing 43.9731 AF, a metric depth multiplied by an imperial area to make an imperial volume with no conversion shown, so the one step that starts the chain is the one an auditor cannot check on the page built for checking. | E | 13 PNG; `calculation_run_detail.html` (steps table, row 1) | 1 page | 143 |
| 99 | R-069 | c24 `/drinking/sampling-points/1/` | data table | On the sampling-point page three of the five result columns print one repeated value down all twenty-five rows (the same date, method and laboratory), so most of the table's width carries nothing and the Result the reader came for is a narrow column between them. | E | 24 PNG; `drinking/sampling_point_detail.html` (recent-results table) | 1 page | 143 |
| 100 | R-073 | c29 `/drinking/onboard/CA2410009/points/` | data table | The sampling-point builder stacks one identical block per facility, twenty-three of them down a page six screens tall, with no search and no index, so adding a point to the twentieth facility means scrolling past nineteen other forms to reach it. | E | 29 PNG (1440 × 8954); `drinking/onboard_points.html` + `drinking/partials/_onboard_points.html` | 1 page | 143 |
| 101 | R-078 | c32 `/datasync/stations/1/` | page head | The one word that explains why every panel on the station page is empty, 'Dormant', is the smallest text on the page and sits at the far right of the title, away from the panels it accounts for. | L | 32 PNG; `datasync/station_detail.html` (title row) | 1 page | 143 |
| 102 | R-089 | c37 `/reporting/reports/shared-supply-check/` | filter bar | The shared-supply check's only control is the reporting period, so there is no way to show just the three flagged sources the page exists to surface; they sit scattered through eight blocks and five screens. | E | 37 PNG; `reporting/shared_supply_check.html` (period toolbar) | 1 page | 143 |
| 103 | R-091 | c37 `/reporting/reports/shared-supply-check/` | data table | Gap is the difference of the two columns immediately before it and prints in the same format beside them, with nothing marking it as the derived one. | L | 37 PNG (0.2000 − 0.1196 = 0.0804); `shared_supply_check.html` (block table header) | 1 page | 143 |
| 104 | R-103 | c43 `/map/zones/2/` | data table | The zone's Assigned use areas table gives neither a count nor an acreage total, so a reader must count twenty-three rows by hand to check the '23 use areas' the Zones list promised. | E | 43 PNG; `geography/partials/_zone_parcels.html` | 1 page | 143 |
| 105 | R-116 | c49 `/surface/diversion/9/` | data table | The form under the diversion table asks for 'Volume (AF)' while the table's own column for the same quantity is 'Diverted (AF)', so a reader adding a record cannot say which column their number will land in. | E | 49 PNG; `surface/partials/_diversion_form.html` vs `_diversion_records.html` | 1 page | 144 |
| 106 | R-120 | c51 `/surface/rights/6/` | data table | The water right's diversion table heads a column 'POD', an abbreviation the page never expands although its own description spells out 'points of diversion' two lines above, so a reader cannot say what the column holds. | L | 51 PNG; `surface/partials/_water_right_detail_pane.html` | 1 page | 144 |
| 107 | R-122 | c51 `/surface/rights/6/` | data table | Within one month the water right's two diversion points swap places from row to row (August lists Snelling first, June lists Merced Falls first), so a reader cannot say what the order inside a month is. | E | 51 PNG; `_water_right_detail_pane.html` | 1 page | 143 |
| 108 | R-123 | c51 `/surface/rights/6/` | map | The water right's map marks its two diversion points but their popups carry only a name, a stream and a flow rate with no link, so a reader who finds a diversion on the map cannot get to its record, while the same names in the list beside it are links. (Read off the partial.) | E | 51 HTML; `_water_right_detail_pane.html:205-214` vs `:106` | 1 page | 143 |
| 109 | R-015 | c10 `/accounting/ledger/?period=2` | page head | The page's actions (Download CSV, Upload CSV, + New entry) sit below the demo banner beside the entry count, not in the page head where Surface Diversions puts them, so a reader who learned where actions live on one page looks in the wrong place on the next. | E | 10 PNG; `ledger_list.html:21-38` | 1 page | 143 |
| 110 | R-017 | c10 `/accounting/ledger/?period=2` | filter bar | The page has two paging controls, 'Jump to page … of 12' inside the filter card and 'Page 1 of 12 · Next' under the table, and a reader cannot say which is current or why there are two. | E | 10 PNG; `ledger_list.html:223-238`; `_ledger_list_results.html:130-156` | 1 page | 143 |
| 111 | R-019 | c10 `/accounting/ledger/?period=2` | data table | The Description column is cut with an ellipsis on every row, so the one column written for a human is the one that cannot be read. | E | 10 PNG; `_ledger_list_results.html:91-92` | 1 page | 143 |
| 112 | R-020 | c10 `/accounting/ledger/?period=2` | data table | Within one date the rows run MER-APN-065, 061, 054, 053, 052 and then jump to 076 where the Source changes, and nothing says the rows are grouped by source; the Date header's arrow says newest-first and no more. | E | 10 PNG; `_ledger_list_results.html:17-24` | 1 page | 143 |
| 113 | R-022 | c48 `/surface/` | map | The map opens the page with nine unlabelled teal dots on aerial imagery and no legend, so a reader learns what a dot is only by clicking it; the count line ('9 diversion points found') sits under the map rather than with it. | L | 48 PNG; `pod_list.html:39-41`; `templates/surface/partials/_pods_overview_map.html` | 1 page | 143 |
| 114 | R-034 | c4 `/accounting/reporting-periods/2/` | tile row | The water-year page's tile row is titled 'Summary', which does not say what the two figures are, and the larger of them, 1130, is a count of ledger rows that is not this page's purpose. | L | 04 PNG; `period_detail.html:99-112` | 1 page | 143 |
| 115 | R-043 | c10 `/accounting/ledger/?period=2` | data table | Rows whose Source is 'Calculated' print an Amount of 0.00 among ordinary entries, while the platform's own Site Health page counts 253 zero-amount ledger entries as a warning, so the reader on the ledger cannot tell a flagged row from a normal one. | E | 10 PNG, 19 PNG; `_ledger_list_results.html:76-77` | 1 page | 143 |
| 116 | R-062 | c20 `/drinking/` | tile row | The drinking-water overview's three counts (Facilities 61, Sampling points 27, Sample results 22,367) have no title of their own and sit under a heading that names something else, 'Population and service connections', so nothing says what this row of figures is a count of. | L | 20 PNG; `drinking/overview.html:200-213` under `:88` | 1 page | 143 |
| 117 | R-080 | c33 `/datasync/monitoring/` | tile row | The monitoring dashboard's fourth tile is a satellite-request quota, '0 of 100 used this month', a different kind of quantity from the three station counts beside it, and nothing sets it apart from them. | L | 33 PNG; `_monitoring_content.html` (quota card) | 1 page | 143 |
| 118 | R-082 | c33 `/datasync/monitoring/` | tile row | One of the six source cards adds a third figure, '· 10 on schedule', and the other five do not, so a reader cannot say whether the others have none on schedule or the figure is simply missing. | E | 33 PNG; `_monitoring_content.html:58` | 1 page | 143 |
| 119 | R-083 | c33 `/datasync/monitoring/` | data table | The section headed 'Active stations' shows seventeen cards, every one from the same source, under a tile that says there are forty-two active, and nothing says which seventeen these are or how they were chosen. | E | 33 PNG; `_monitoring_content.html:94` | 1 page | 143 |
| 120 | R-084 | c34 `/reporting/reports/` | tile row | The third card in a row headed 'Start a filing' is a data check rather than a filing, and nothing says why 'Shared-supply check' is one of three ways to start one. | L | 34 PNG; `reporting/partials/_report_actions.html` | 1 page | 143 |
| 121 | R-085 | c34 `/reporting/reports/` | filter bar | On the reports page a search box and a status select render above an empty history, so the page offers to narrow a list of nothing. | L | 34 PNG; `reporting/partials/_report_history.html` | 1 page | 143 |
| 122 | R-119 | c50 `/surface/rights/` | body prose | 'Face value' heads the biggest number on the water-rights list with nothing saying what it is (the detail page explains it behind a '?', the list does not), so a reader outside the trade cannot say what the largest figure in the table measures. | L | 50 PNG; `surface/partials/_list_results.html` | 1 page | 144 |
| 123 | R-125 | c52 `/recharge/` | data table | The recharge list's Capacity column gives a volume in acre-feet with nothing saying what it is the capacity for (one filling, or a year of them), so a reader cannot say what 1281 AF would be compared against. | L | 52 PNG; `recharge/partials/_list_results.html` | 1 page | 143 |
| 124 | R-049 | c15 `/accounting/methodology/` | body prose | Every methodology step prints its name twice in its own heading, 'Gross ET (OpenET ensemble) (Gross ET)', and a third time inside the Label box beneath, and nothing says what the bracketed one is or which of the three the platform uses. | L | 15 PNG; `partials/_methodology_steps.html` | 1 page | 144 |
| 125 | R-051 | c15 `/accounting/methodology/` | body prose | 'Bank surplus', 'Depreciation / mo (0-1)' and 'Expiry (months)' are grouped under a step called 'Clamp at floor', so a reader cannot say why carrying a surplus forward is part of clamping a number at zero. | E | 15 PNG; `_methodology_steps.html` (step 5) | 1 page | 143 |
| 126 | R-056 | c19 `/health/` | tile row | Site Health's five cards that name a problem (a failed SSL check, six stale sources, 253 zero-amount ledger entries, an ET agreement outside range, unallocated delivery) offer nowhere to go, so an operator who reads the problem cannot reach the record it is about. | E | 19 PNG; `health/dashboard.html` | 1 page | 143 |
| 127 | R-057 | c19 `/health/` | body prose | A Site Health card reads '1 parcel-period(s) fall outside that range', printing a machine plural and disagreeing with its own verb, so the reader cannot say whether one thing or several are wrong. | L | 19 PNG; the check's own message text | 1 page | 144 |
| 128 | R-063 | c21 `/drinking/facilities/` | data table | Twenty-seven of the fifty visible facility rows print 'Not recorded' in the Water Type and Well columns, and nothing on the page says whether the federal record is silent for treatment plants or whether this deployment has not imported it. | L | 21 PNG; `drinking/partials/_facility_results.html:70,91` | 1 page | 143 |
| 129 | R-064 | c22 `/drinking/facilities/1/` | page head | The facility page's crumb runs Drinking Water → 012 and its one back link returns to the overview, so a reader who arrived from the 61-row facility list has no way back to it except the sidebar. | E | 22 PNG; `drinking/facility_detail.html` (crumb block) | 1 page | 143 |
| 130 | R-066 | c22 `/drinking/facilities/1/` | data table | The facility card has a section headed 'Well' whose only line reads 'Physical well — Not recorded', on a facility whose Type is 'Well', and a reader cannot say whether this facility is a well or is a facility that has no well attached. | L | 22 PNG; `drinking/facility_detail.html` (Well section) | 1 page | 143 |
| 131 | R-067 | c23 `/drinking/sampling-points/` | data table | Every sampling-point row names the facility the point sits on ('001 — WELL 01A - RAW'), a record with its own page, as plain text, so a reader who wants that facility has to go back to the facility list and search for it. | E | 23 PNG; `drinking/partials/_sampling_point_results.html:26` | 1 page | 143 |
| 132 | R-068 | c23 `/drinking/sampling-points/` | data table | The largest number in the sampling-points table, 11,827 in the Results column, is not named as a count of laboratory findings, so a reader cannot say whether it is a tally, a measurement or a volume. | L | 23 PNG; `_sampling_point_results.html:18,29-35` | 1 page | 143 |
| 133 | R-070 | c25 `/drinking/results/` | data table | In the lab-results log the cell that opens a finding is the Sample Date, which reads '2026-05-21' on every visible row, while the Analyte, the only cell that differs down the screen, is plain text, so the reader has to click a date they cannot tell apart from its neighbours. | E | 25 PNG; `drinking/partials/_result_results.html:24` vs `:26` | 1 page | 143 |
| 134 | R-071 | c25 `/drinking/results/` | data table | Four of the six columns in the lab-results log (Sample Date, PS Code, Method, Laboratory) hold one repeated value down the whole screen, so a screenful of a 22,367-row log shows two columns of information. | E | 25 PNG; `_result_results.html:13-18` | 1 page | 143 |
| 135 | R-075 | c30 `/datasync/stations/` | data table | A station whose Last Data column says it reported two years ago shows '--' in the Trend column, so a reader cannot tell a station with one reading from a station with none. (ISS-110 part 2, as it renders today.) | E | 30 PNG; `datasync/partials/_station_list_results.html:79-81` | 1 page | 143 |
| 136 | R-076 | c30 `/datasync/stations/` | data table | The station list's leftmost column is an unheaded coloured dot, and what the colour means is only written in the map's legend further up the page. | L | 30 PNG; `_station_list_results.html:14` | 1 page | 143 |
| 137 | R-088 | c36 `/reporting/reports/3/` | page head | The report's type and period print three times before any figure: in the breadcrumb, again as the pane header's title and subtitle, and again as the first two fields of the metadata card. (Template only.) | L | `report_detail.html:13`, `_report_detail_pane.html:29-30`, `:73-79` | 1 page | 143 |
| 138 | R-092 | c38 `/reporting/reports/3/calwatrs-worksheet/` | body prose | Nothing on the CalWATRS worksheet says how many blocks it holds or where the reader is in it, so an operator typing point after point into the state's portal cannot tell how much is left. (Template only.) | E | `reporting/calwatrs_worksheet.html:42` | 1 page | 144 |
| 139 | R-093 | c38 `/reporting/reports/3/calwatrs-worksheet/` | data table | The two blockers the worksheet names ('No linked water right', 'Add this right's PIN on the water right') identify a record the reader must go and fix, and neither is a link to it. (Template only.) | E | `calwatrs_worksheet.html:53,65` | 1 page | 143 |
| 140 | R-094 | c40 `/map/` | map | Where the district's features cluster east of Merced, dozens of markers and their white service-area labels overlap into a pile, so a reader can neither read which area is which nor pick out one mark to open. | L | 40 PNG; `geography/map.html:93` | 1 page | 143 |
| 141 | R-113 | c47 `/wells/10/` | body prose | The well page names GEARS, DWR, WCR, the State Well Number and CASGEM and explains none of them, while the one field that is explained is the platform's own Registration ID, so a reader cannot say which agency or programme any of those identifiers belongs to. | L | 47 PNG; `wells/partials/_detail_pane.html` (section heads and the Monitoring data note) | 1 page | 144 |
| 142 | R-129 | c54 `/infrastructure/add/` | body prose | The Add Well page's 'Link to parcel (optional)' card shows a heading over empty space with nothing saying it opens, so a reader who wants to attach the new well to a parcel sees a card that appears to be broken. | E | 54 PNG; `infrastructure/add.html:236-253` (a disclosure with no visible mark) | 1 page | 143 |
| 143 | R-130 | c55 `/infrastructure/import/` | page head | The bulk-import page is fixed to one record type ('Bulk import — Well') and unlike the Add page offers no way to switch, so a reader who arrived to import diversions has no route on the screen to the import they want. | E | 55 PNG; `infrastructure/import.html` | 1 page | 143 |
| 144 | R-131 | c56 `/users/` | data table | The user roster's Actions column's only content is the word 'You', so a reader cannot say what actions a row offers or why this row offers none. | E | 56 PNG; `core/users_list.html` | 1 page | 143 |
| 145 | R-135 | c66 `/about/` | body prose | About's one narrative section is titled 'Standing on the Groundwater Accounting Platform' and spends four paragraphs on another platform's merits ('proved something that was far from obvious when it started', 'raised the bar for every tool in the field', 'indebted to GAP's example and glad to keep learning from the people who built it'), so a reader who came to find out what OpenH2O does learns it only from the one card above, and nothing after that adds to the answer. | L | 66 PNG; `about.html:56`, `:82-87` | 1 page | 144 |
| 146 | R-136 | c67 `/about/demonstration-data/` | body prose | In the two prose cards on the demonstration-data page the paragraphs run together with no gap (the space between two paragraphs equals the space between two lines of one), so 'The short version' reads as a single nine-line block and the reader cannot see that it is making three separate points. | L | 67 PNG; `about_demonstration_data.html:22-32`; the shared `.about-purpose` rule, `static/css/app.css:3006-3012` | 1 page, 5 paragraphs | 144 |

## Every page, one verdict

A page fails an audience when any surface on it fails a question marked for that audience. Three rows fail on every signed-in page and are not repeated below: R-013, R-024, R-058 (the sidebar's 'Onboard System' entry, the floating Feedback button, and the title that is only the last crumb). † = judged from the template; the capture did not render the page as itself.

| c# | page | verdict | rows |
|---|---|---|---|
| 1 | `/accounting/dashboard/?period=2` | FAIL-both | R-007, R-003, R-004, R-012, R-006, R-002, R-026, R-001, R-005, R-008, R-009, R-010, R-011, R-027 |
| 2 | `/accounting/reporting-periods/` | FAIL-both | R-025, R-028, R-026, R-029, R-030 |
| 3 | `/accounting/reporting-periods/create/` | FAIL-both | R-028, R-031, R-029 |
| 4 | `/accounting/reporting-periods/2/` | FAIL-both | R-025, R-028, R-032, R-029, R-033, R-034 |
| 5 | `/accounting/accounts/` | FAIL-both | R-028, R-036, R-038, R-039, R-021, R-002, R-029, R-037, R-040 |
| 6 | `/accounting/accounts/create/` | FAIL-both | R-028, R-031, R-036, R-038, R-039, R-002, R-029, R-037, R-040 |
| 7 | `/accounting/accounts/12/?period=2` | FAIL-both | R-028, R-036, R-038, R-039, R-035, R-002, R-029, R-037, R-040 |
| 8 | `/accounting/allocations/` | FAIL-both | R-028, R-032, R-041, R-033, R-030 |
| 9 | `/accounting/allocations/create/` | FAIL-both | R-028, R-031, R-032, R-041, R-033 |
| 10 | `/accounting/ledger/?period=2` | FAIL-both | R-016, R-018, R-025, R-014, R-042, R-015, R-017, R-019, R-020, R-043 |
| 11 | `/accounting/ledger/create/` | FAIL-both | R-031, R-014, R-044 |
| 12 | `/accounting/ledger/upload/` | PASS | — |
| 13 | `/accounting/calculation-run/11/2026-09/` | FAIL-both | R-028, R-045, R-046, R-047 |
| 14 | `/accounting/delivery-settings/` | FAIL-both | R-028, R-048, R-026 |
| 15 | `/accounting/methodology/` | FAIL-both | R-028, R-050, R-049, R-051 |
| 16 | `/setup/` | FAIL-both | R-028, R-053 |
| 17 | `/setup/confirm/` † | FAIL-both | R-028, R-054, R-052, R-053 |
| 18 | `/setup/run/` † | FAIL-both | R-028, R-054, R-053 |
| 19 | `/health/` | FAIL-both | R-028, R-055, R-056, R-057 |
| 20 | `/drinking/` | FAIL-L | R-062 |
| 21 | `/drinking/facilities/` | FAIL-both | R-025, R-063 |
| 22 | `/drinking/facilities/1/` | FAIL-both | R-065, R-064, R-066 |
| 23 | `/drinking/sampling-points/` | FAIL-both | R-025, R-023, R-067, R-068 |
| 24 | `/drinking/sampling-points/1/` | FAIL-both | R-025, R-059, R-069 |
| 25 | `/drinking/results/` | FAIL-both | R-025, R-021, R-059, R-070, R-071 |
| 26 | `/drinking/results/1/` | FAIL-both | R-055, R-059 |
| 27 | `/drinking/import/` | PASS | — |
| 28 | `/drinking/onboard/` | FAIL-E | R-072 |
| 29 | `/drinking/onboard/CA2410009/points/` | FAIL-E | R-072, R-073 |
| 30 | `/datasync/stations/` | FAIL-both | R-074, R-021, R-075, R-076 |
| 31 | `/datasync/stations/add/` | FAIL-both | R-031 |
| 32 | `/datasync/stations/1/` | FAIL-both | R-077, R-078 |
| 33 | `/datasync/monitoring/` | FAIL-both | R-028, R-079, R-081, R-002, R-080, R-082, R-083 |
| 34 | `/reporting/reports/` | FAIL-both | R-086, R-084, R-085 |
| 35 | `/reporting/reports/generate/` | FAIL-both | R-086, R-061 |
| 36 | `/reporting/reports/3/` † | FAIL-both | R-086, R-060, R-035, R-087, R-061, R-088 |
| 37 | `/reporting/reports/shared-supply-check/` | FAIL-both | R-055, R-090, R-089, R-091 |
| 38 | `/reporting/reports/3/calwatrs-worksheet/` † | FAIL-both | R-060, R-002, R-092, R-093 |
| 39 | `/reporting/reports/3/prefill/` † | FAIL-both | R-086, R-060 |
| 40 | `/map/` | FAIL-both | R-097, R-095, R-096, R-094 |
| 41 | `/map/zones/` | FAIL-both | R-023, R-021, R-098, R-099 |
| 42 | `/map/zones/create/` | FAIL-both | R-100, R-098, R-099 |
| 43 | `/map/zones/2/` | FAIL-both | R-025, R-055, R-031, R-101, R-102, R-104, R-112, R-098, R-103 |
| 44 | `/parcels/` | FAIL-both | R-097, R-002, R-105, R-106 |
| 45 | `/parcels/11/` | FAIL-both | R-097, R-107, R-108, R-109, R-002 |
| 46 | `/wells/` | FAIL-both | R-110, R-021, R-002, R-105, R-106 |
| 47 | `/wells/10/` | FAIL-both | R-025, R-111, R-114, R-002, R-112, R-113 |
| 48 | `/surface/` | FAIL-both | R-023, R-021, R-002, R-022 |
| 49 | `/surface/diversion/9/` | FAIL-both | R-025, R-055, R-097, R-115, R-117, R-002, R-112, R-116 |
| 50 | `/surface/rights/` | FAIL-both | R-028, R-118, R-002, R-119 |
| 51 | `/surface/rights/6/` | FAIL-both | R-028, R-055, R-121, R-002, R-120, R-122, R-123 |
| 52 | `/recharge/` | FAIL-both | R-023, R-124, R-021, R-125 |
| 53 | `/recharge/1/` | FAIL-both | R-025, R-055, R-126, R-127 |
| 54 | `/infrastructure/add/` | FAIL-both | R-028, R-100, R-112, R-128, R-129 |
| 55 | `/infrastructure/import/` | FAIL-both | R-028, R-128, R-130 |
| 56 | `/users/` | FAIL-both | R-028, R-131 |
| 57 | `/users/add/` | FAIL-both | R-028 |
| 58 | `/profile/` | FAIL-both | R-028, R-132 |
| 59 | `/help/getting-started/` | FAIL-both | R-145, R-133 |
| 60 | `/help/glossary/` | FAIL-both | R-145, R-134, R-026 |
| 61 | `/help/budgets-allocations/` | FAIL-both | R-028, R-145, R-026 |
| 62 | `/help/surface-deliveries/` | FAIL-both | R-028, R-145, R-026 |
| 63 | `/help/water-balances/` | FAIL-both | R-145, R-026, R-146 |
| 64 | `/help/methods/` | FAIL-both | R-145, R-026, R-146 |
| 65 | `/help/settings/` | FAIL-both | R-145, R-026, R-146 |
| 66 | `/about/` | FAIL-both | R-145, R-132, R-135 |
| 67 | `/about/demonstration-data/` | FAIL-both | R-028, R-136 |
| 68 | `/` | FAIL-both | R-138, R-137 |
| 69 | `/?anon` | FAIL-both | R-138, R-139, R-140 |
| 70 | `/accounts/login/` | PASS | — |
| 71 | `/accounts/logout/` † | FAIL-L | R-142, R-143 |
| 72 | `/accounts/signup/` | FAIL-both | R-141, R-142, R-143 |
| 73 | `/accounts/signup/?closed` † | FAIL-both | R-141, R-142, R-143 |
| 74 | `/accounts/password/reset/` | FAIL-both | R-141, R-142, R-143 |
| 75 | `/accounts/password/reset/done/` | FAIL-L | R-142, R-143 |
| 76 | `/accounts/password/reset/key/1-x/` | FAIL-both | R-141, R-142, R-143, R-144 |
| 77 | `/accounts/password/reset/key/done/` | FAIL-L | R-142, R-143 |
| 78 | `/accounts/confirm-email/` | FAIL-L | R-142, R-143 |
| 79 | `/accounts/confirm-email/x/` | FAIL-L | R-142, R-143, R-144 |
| 80 | `(layout shell)` † | PASS | — |

## Phase 141: Make the type scale real

A CSS pass: the one specificity rule (ISS-162), the dashboard zone links (ISS-163), and every template that names a utility class the stylesheet does not carry. **4 rows.**

| rank | id | page | finding |
|---|---|---|---|
| 7 | R-025 | 11 pages (c10 …) | Inside any data table the type scale does not exist: a text utility on a cell is discarded, so a date, a note and a headline figure render at one size and one brightness (the ledger's dates, the recharge card's field notes, the facility list's types all render as the figures beside them). (ISS-162) |
| 21 | R-141 | c72, c73, c74, c76 | On the sign-up and password-reset forms every label sits hard on top of its box and the gold submit button touches the bottom edge of the last box, so the last field and the button read as one merged control and the reader cannot see where the form ends. (The spacing classes those templates name do not exist in the stylesheet, ISS-162's class of fault.) |
| 71 | R-143 | 9 pages (c71 …) | The titles on the account pages ('Create account', 'Reset password', 'Check your email', 'Verify your email') render around three times the height of their own body text and larger than any page title elsewhere in the platform, so a reader crossing from the login page to the sign-up page cannot tell the two are the same kind of screen. (The heading class those templates name does not exist in the stylesheet, so the browser's own heading size is used.) |
| 92 | R-009 | c1 | Zone names are plain text while the account names in the table above are links, so half the names on the page are a way in and half are not. (ISS-163) |

## Phase 142: One table redesigned, for Brent's eyes

The dashboard only. Everything here is on `/accounting/dashboard/`; the checkpoint shows him the whole page. **8 rows.**

| rank | id | page | finding |
|---|---|---|---|
| 1 | R-007 | c1 | The Active water accounts table heads eight numeric columns identically; nothing shows that Surface + Groundwater + Precip is Supplies, that Net is Supplies minus Consumptive Use, or that GW allocation and GW remaining are an allocation on paper from a different framework rather than water that moved. (ISS-159 #1) |
| 2 | R-003 | c1 | The panel is titled 'Supply vs. use', which names an operation, not the thing; a reader cannot say from the title that this is the district's whole-basin position for the year. (ISS-159 #2) |
| 3 | R-004 | c1 | Three figures are set at the largest type on the page inside a panel far wider than they need, and the result (Balance) is set no larger than the two that make it, so nothing says which figure the page leads with. (ISS-159 #2) |
| 90 | R-005 | c1 | The panel's foot lists Surface 11,407.71, Groundwater 4,377.38 and Rain 1,673.27 with nothing saying they are the three parts of the Supplies figure above them. |
| 91 | R-008 | c1 | At a 1440-pixel window the accounts table's last column is clipped, header and values alike (957, -320, 610, -508, -1,002 all cut mid-figure), and the Zones table's last two columns are off-screen entirely, so the column an engineer came for is lost until they discover the card scrolls sideways. |
| 93 | R-010 | c1 | The Zones table mixes two kinds of row, two GSAs with a groundwater budget and five 'MER Surface Service Area' rows that print a dash in every budget column, and nothing on the page says why half the rows have dashes. |
| 94 | R-011 | c1 | The Drinking Water card's corner code 'CA2410009' is not named as the state's public water system number, so a reader cannot say what the code is. |
| 95 | R-027 | c1 | The Drinking Water card is titled 'CITY OF MERCED', a place name, so nothing says what its four figures are before the reader has read them, and the biggest of them, 22,367, is a count of stored sample rows. |

Resolved by 142-01 (2026-09-08, commits `73aec22`..`c361d48`, staging only): all 8 rows, plus R-006 from §Phase 144 whose sentence became the panel captions and the group headers. Measured on staging after the deploy: both tables fit 1440 (scrollWidth 1032 = clientWidth 1032, against 1073 and 1253 before), Balance 32px against its two inputs at 22px, title "District water balance", no inset, two header rows in equation order, footer on the accounts table only. Pattern awaiting Brent's approval at the checkpoint.

## Phase 143: The approved pattern applied everywhere else

Tables, tile rows, filter bars, page heads and maps on every other page, in rank order. The rows that repeat a dashboard fault in another template (R-037, R-038, R-039, R-108) wait for 142's pattern. **99 rows.**

| rank | id | page | finding |
|---|---|---|---|
| 4 | R-016 | c10 | The filter is a full card of four rows (quick-filter chips; search, period and zone; a hidden advanced row; rows-per-page and jump-to-page) pinned to the top of the window as the reader scrolls, so reading one water year's entries costs a third of the screen in controls the reader will not touch. (ISS-159 #4) |
| 5 | R-018 | c10 | The columns run Date, Parcel, Amount, Source, Water Type, Description, and the reader cannot say why they are in that order; nothing in the header says a negative Amount is water leaving a canal or a well and a positive one is paper. That sentence is in the footer, a hundred rows down. (ISS-159 #4) |
| 6 | R-058 | 69 pages (c1 …) | The only visible title on any signed-in page is the last breadcrumb, set at the size of the description under it, so on a record page the screen's title is a bare code ('012' on a facility, 'Worksheet' on the CalWATRS page) and the record's own name sits far below it; the real title is hidden from sight on every page. |
| 10 | R-055 | 7 pages (c19 …) | On seven pages the figure the page exists to produce is set no larger than the fields around it: Site Health's '8/13 healthy' is smaller than the card titles; the lab result '7.4 MG/L' is one of sixteen equal values; the shared-supply check's '8 sources · 3 flagged' is the smallest text on the page, inside the filter bar; and the zone's Remaining, the diversion's Diverted, the right's Face value and the recharge event's Volume are each one cell like any other, so nothing on the screen says which number the reader came for. |
| 11 | R-031 | c3, c6, c9, c11, c31, c43 | Six pages carry no description at all, only a breadcrumb over the content: the four accounting create forms (so nothing says what a name should look like or that dates run October to September), the Add Station form (whose first required field is 'Data source'), and the zone detail page (so a reader arriving on a zone gets no sentence saying what the numbers below are or what period they cover). |
| 13 | R-023 | c48, c23, c41, c52 | Filtering the list does not filter the map: the overview-map partials on Surface Diversions, Sampling Points, Zones and Recharge Areas install no listener for the list's swap, so after a search the list says '2 found' and the map still shows every mark (on Sampling Points the sentence above the map keeps saying '21 of 27' too). Read off the partials, not the screenshots: an interaction cannot be captured. (ISS-136's class) |
| 16 | R-036 | c5, c6, c7 | On the account pages the control that says which water year the figures cover renders its own text jammed against the box edge and overlapping, so the year the whole page depends on is the hardest thing on it to read. |
| 17 | R-038 | c5, c6, c7 | On the account pages Supplies, Consumptive use and Balance are set at one size, so nothing says the Balance is the figure the page exists to produce (R-004's fault in a second template). |
| 18 | R-039 | c5, c6, c7 | The account page's Per-Parcel breakdown heads six numeric columns identically, so nothing shows that Surface + Groundwater + Precip is Supplies or that Net is Supplies minus Consumptive Use (R-007's fault in a second template). |
| 19 | R-032 | c4, c8, c9 | The allocation tables' NAME column prints the zone, the water type and the water year run together, and the next three columns print those same three things again, so the reader reads the same words three times before reaching the one figure that differs. |
| 20 | R-060 | c36, c38, c39 | A URL that no longer resolves drops the reader out of the platform onto a bare white 'Not Found' page with no platform name, no navigation and no link back (the three report pages rendered this way on staging, whose rebuilt demo has no past report). |
| 22 | R-035 | c7, c36 | A detail pane offers 'Open full page →' on the full page itself (the account page, and the report page by its template), so a reader who follows the only forward link in the head lands back on the screen they are already reading. |
| 23 | R-054 | c17, c18 | Reaching setup step 2 or 3 without a live wizard session drops the reader back on step 1 with nothing said, so the reader cannot say whether the wizard restarted, failed, or was never started. |
| 24 | R-138 | c68, c69 | A reader cannot say what '10 of 42' counts: the line does not say that 42 is the stations left switched on rather than the stations that exist, and the anonymous branch of the same front page prints 'Monitoring stations 335', so the platform gives two counts of its monitoring stations eight times apart with nothing distinguishing them. |
| 26 | R-041 | c8, c9 | With no period chosen the Allocations footer adds the same allocation in two different water years into one figure, so the largest number on the page, 304,200.00 AF of surface water, counts a single 108,000.00 AF entitlement twice and is not an amount anyone manages. (Filed as ISS-164 as well: a wrong sum, ISS-156's class along the other axis.) |
| 27 | R-100 | c42, c54 | The map the reader is told to draw on opens on a fixed point in the mountains (Mammoth Lakes, Madera and Clovis are the only places named) and draws no district boundary, so a reader cannot see where their own district is before drawing. |
| 28 | R-132 | c58, c66 | Two pages have no breadcrumb strip at all and their real heading is hidden from sight: on Profile the only name on the screen is a card heading, and on About the first words a reader sees are the demo notice, so neither page says where the reader is or offers a link back. |
| 30 | R-052 | c17 | The setup wizard's confirm step adds basins and flowlines into one figure under the label 'Existing data', so the reader cannot say what the number counts or how many of each it found. (Template only: the page answered 302.) |
| 31 | R-077 | c32 | The station page's lead surface, the Telemetry panel, draws a full-height empty grid with an axis running 0 to 1.0 for a station that has never reported, so the page shows a scale no reading produced and a reader cannot say whether the values are zero or absent. |
| 32 | R-090 | c37 | The rule that flags a shared-supply row is stated in percentage points ('gap threshold 15 points') while the Gap column prints a decimal fraction (0.0804), so a reader has to convert before they can tell why one row is flagged and its neighbour is not. |
| 33 | R-101 | c43 | The zone's Allocation vs. use table prints Allocation, Carried forward, Used and Remaining as one flat row of like figures although the fourth is the first three worked out, and the sentence that says so is hidden behind a '?' the reader has to find. |
| 34 | R-102 | c43 | The zone's map shows the zone's outline and nothing else, while the list beneath it names twenty-three assigned use areas, so a reader cannot see on the map which parcels the page says belong to this zone. |
| 36 | R-107 | c45 | The use-area page's water balance is set to WY 2025-2026 while the ledger card beside it lists entries from October 2024 to June 2025 under 'Recent ledger entries', so two surfaces on one screen answer for different years and neither says which. (Filed as ISS-165 as well: the card's query never filters on the period.) |
| 37 | R-108 | c45 | The use-area page's ledger card prints 241.56 and -36.55 in one Amount column with nothing on the card saying what a negative amount is, so a reader cannot say whether a minus sign means water leaving or a correction (R-018's fault on a second page). |
| 39 | R-115 | c49 | The diversion page's records table prints Diverted, Return flow and Retained as one flat row of like figures although the third is the first two worked out, so a reader cannot see that 584.98 retained is 584.98 diverted less nothing returned. |
| 40 | R-117 | c49 | The diversion page's description promises compliance information and the only compliance on the screen is a closed 'Compliance details' strip at the very bottom, so a reader cannot say whether this diversion is within its right without opening it. |
| 41 | R-121 | c51 | The water-right page shows a right authorising 60,000 AF and twelve diversion records over eight months (Feb–Sep 2026) against it, and nothing adds the records up or sets them against the authorisation, so a reader cannot say from this screen how much of the right has been used. |
| 42 | R-126 | c53 | The recharge basin's Recent measurements puts four different quantities in one Value column (a water-quality reading in mg/L, a depth in feet, a flow in cfs and a rate in inches per hour), ordered only by date, so a reader who came for the water levels has to pick them out of a mixed list. |
| 44 | R-137 | c68 | On the signed-in front page the largest words are the agency's name and 'Good morning'; the one figure the page exists to give, '10 of 42 stations reporting', is set small and grey underneath them, so the row's title names a time of day rather than the thing being summarised and nothing says which number the page leads with. |
| 45 | R-042 | c10 | A period filter is applied and the result line still reads only '1130 entries', so the reader cannot say from it whether they are looking at one water year or all of them. |
| 46 | R-079 | c33 | On the monitoring dashboard 'On schedule 10' and 'Behind schedule 32' are the two parts of 'Active stations 42' and print as a flat row of three like figures, with nothing showing that the last two are what the first is made of. |
| 47 | R-081 | c33 | Five of the six source cards are stamped 'Not yet synced' while the same card counts active stations whose readings appear a month old on the station list, so a reader cannot say what 'Not yet synced' is telling them. |
| 48 | R-110 | c46 | Each well row's one figure is printed as '340.00 ft' with no word anywhere saying what is being measured, so a reader cannot say whether the column is the depth of the hole, the depth to water, or something else. |
| 49 | R-118 | c50 | One of the seven water-right rows carries a 'DEMO' badge in its Status cell while all seven identifiers end in -DEMO and a banner above already says the whole dataset is mixed, so a reader cannot say what the badge marks out. |
| 50 | R-124 | c52 | The recharge map shows two faint purple marks for the seven sites the list counts, with no labels and no legend, so a reader can neither say what a mark is nor find the seven the page says are there (R-022's fault with a count mismatch added). |
| 52 | R-140 | c69 | The anonymous front page's card grid is four columns wide and its last two rows use two of them and one of them, leaving half of one row and most of another empty; the final full-width card carries a single label, 'System status', with its status dot printed hard against the first letter. |
| 55 | R-050 | c15 | Step 2 shows 'Fraction (method = fraction)' and 'Soil storage (in) (method = USDA-SCS)' side by side while only one method is selected, so the reader cannot say which of the two boxes is the live one. |
| 57 | R-074 | c30 | The station list arrives already filtered to syncing stations while the map draws the whole network, dormant stations included, so on first load the map shows more stations than the '42 stations' the list counts and nothing on the page says why the two disagree. (ISS-136's class, visible without any interaction.) |
| 58 | R-087 | c36 | On the report page the download, which is what the page exists to produce, is the fourth of four equal metadata fields, set in the same small type as the 'Generated' timestamp beside it. (Template only.) |
| 59 | R-095 | c40 | The map's legend names three zones in three near-identical greens while the Layers panel beside it counts eight GSA Zones, so a reader cannot say which shape on the map is which zone, nor why five are unnamed. |
| 60 | R-096 | c40 | The map's Layers panel is sliced through the word 'MONITORING' at its bottom edge with nothing saying the panel scrolls, so a reader looking for monitoring stations sees a cut-off word and no layer. |
| 61 | R-111 | c47 | The well page's Totalizer column runs above forty thousand with no unit in the header, while the column beside it says Delta (AF), so a reader cannot say what the big number measures. |
| 62 | R-114 | c47 | The well page's Irrigated parcels card prints '1.00 fraction' beside the parcel, and nothing says a fraction of what, so a reader cannot say what share the figure is a share of. |
| 65 | R-021 | 7 pages (c48 …) | The Import and Add buttons sit in a row of their own under the description, leaving a wide empty band between the words and the buttons; the spacing reads as avoiding a collision rather than using the space. Confirmed rendering on seven list pages. (ISS-159 #5) |
| 67 | R-024 | 14 pages (c1 …) | The floating Feedback button sits over the content's right edge on every page; it covers the 'RECORDS' header on Surface Diversions, the zone page's own lead figure (Remaining 911.58), the 'Syncing' column header on Monitoring Stations, and turns 'Direct Use' into 'Use' on a water right. |
| 68 | R-002 | 14 pages (c1 …) | Two demo notices sit one above the other (the full banner, then a bare DEMO pill), and the second says nothing the first did not. |
| 70 | R-142 | 9 pages (c71 …) | Nine of the ten account pages carry no OpenH2O name or mark anywhere on the screen (only the login page has one), so a visitor who arrives at 'Create account', 'Reset password' or 'Verify your email' from an emailed link cannot say what they are creating an account on except from a footer line in the smallest type on the page. |
| 73 | R-112 | c43, c47, c49, c54 | On four record pages one column of the two-column body runs out while the other runs on, leaving a tall empty column beside a long stack of tables, so a reader comparing two of those tables scrolls instead of looking across. |
| 74 | R-037 | c5, c6, c7 | The account balance panel's foot lists Surface, Groundwater and Rain with nothing saying they are the three parts of the Supplies figure above them (R-005's fault in a second template). |
| 75 | R-040 | c5, c6, c7 | Both tables on the account page run MER-APN-021, 023, 024 … 038 and then 022 and 031 at the end, so a reader cannot say what order the rows are in and the two stragglers read as an error. |
| 79 | R-033 | c4, c8, c9 | No allocation name is a link, and on the Allocations list the only link in a row is the water year, so the way in leads away from the record the row is about while account and parcel names elsewhere are links. |
| 83 | R-105 | c44, c46 | On the Use Areas and Wells finders six of the rows are in view, in a narrow column that scrolls inside itself, while two thirds of the screen holds a placeholder telling the reader to pick one, so finding a record means working a six-row window. |
| 84 | R-106 | c44, c46 | On the same two finders the two filter controls are stacked one above the other at the top of that narrow column and take about a quarter of its height, so the controls cost the reader rows they could otherwise see. |
| 85 | R-030 | c2, c8 | The page's one action ('+ New water year', '+ New allocation') sits inside the search card beside the search box rather than with the title, so a reader who learned on the Accounts page that actions live under the description looks in the wrong place. |
| 86 | R-061 | c35, c36 | The reporting pages carry a second demonstration notice, in red and larger type, directly under the page's own demonstration banner, so a reader is warned twice about the data before being told what the screen does (R-002's class). |
| 88 | R-144 | c76, c79 | On the expired-link screens the title still names the action the page has just refused: the biggest words are 'Set new password' above 'This reset link is invalid or has expired', and 'Confirm email' above 'This confirmation link is invalid or has expired', so the reader's first read of the page says the opposite of its second. |
| 89 | R-001 | c1 | The page's one control, the Period selector, sits below two demo notices and away from the title, so a reader asking which year they are looking at finds the answer third, in a small badge on the panel. |
| 96 | R-045 | c13 | The calculation page's head reads 'Methodology: Default Methodology (a3fee261ef37)' and nothing says what the twelve-character code is, so a reader cannot say whether it identifies a version, a run or a record. |
| 97 | R-046 | c13 | Step 2's DETAIL cell reads 'usda_scs: −0.3168 AF effective precip', printing a machine key in the one column on the page written for a person to read. |
| 98 | R-047 | c13 | Step 1 shows '122.07 mm × 109.80 ac' producing 43.9731 AF, a metric depth multiplied by an imperial area to make an imperial volume with no conversion shown, so the one step that starts the chain is the one an auditor cannot check on the page built for checking. |
| 99 | R-069 | c24 | On the sampling-point page three of the five result columns print one repeated value down all twenty-five rows (the same date, method and laboratory), so most of the table's width carries nothing and the Result the reader came for is a narrow column between them. |
| 100 | R-073 | c29 | The sampling-point builder stacks one identical block per facility, twenty-three of them down a page six screens tall, with no search and no index, so adding a point to the twentieth facility means scrolling past nineteen other forms to reach it. |
| 101 | R-078 | c32 | The one word that explains why every panel on the station page is empty, 'Dormant', is the smallest text on the page and sits at the far right of the title, away from the panels it accounts for. |
| 102 | R-089 | c37 | The shared-supply check's only control is the reporting period, so there is no way to show just the three flagged sources the page exists to surface; they sit scattered through eight blocks and five screens. |
| 103 | R-091 | c37 | Gap is the difference of the two columns immediately before it and prints in the same format beside them, with nothing marking it as the derived one. |
| 104 | R-103 | c43 | The zone's Assigned use areas table gives neither a count nor an acreage total, so a reader must count twenty-three rows by hand to check the '23 use areas' the Zones list promised. |
| 107 | R-122 | c51 | Within one month the water right's two diversion points swap places from row to row (August lists Snelling first, June lists Merced Falls first), so a reader cannot say what the order inside a month is. |
| 108 | R-123 | c51 | The water right's map marks its two diversion points but their popups carry only a name, a stream and a flow rate with no link, so a reader who finds a diversion on the map cannot get to its record, while the same names in the list beside it are links. (Read off the partial.) |
| 109 | R-015 | c10 | The page's actions (Download CSV, Upload CSV, + New entry) sit below the demo banner beside the entry count, not in the page head where Surface Diversions puts them, so a reader who learned where actions live on one page looks in the wrong place on the next. |
| 110 | R-017 | c10 | The page has two paging controls, 'Jump to page … of 12' inside the filter card and 'Page 1 of 12 · Next' under the table, and a reader cannot say which is current or why there are two. |
| 111 | R-019 | c10 | The Description column is cut with an ellipsis on every row, so the one column written for a human is the one that cannot be read. |
| 112 | R-020 | c10 | Within one date the rows run MER-APN-065, 061, 054, 053, 052 and then jump to 076 where the Source changes, and nothing says the rows are grouped by source; the Date header's arrow says newest-first and no more. |
| 113 | R-022 | c48 | The map opens the page with nine unlabelled teal dots on aerial imagery and no legend, so a reader learns what a dot is only by clicking it; the count line ('9 diversion points found') sits under the map rather than with it. |
| 114 | R-034 | c4 | The water-year page's tile row is titled 'Summary', which does not say what the two figures are, and the larger of them, 1130, is a count of ledger rows that is not this page's purpose. |
| 115 | R-043 | c10 | Rows whose Source is 'Calculated' print an Amount of 0.00 among ordinary entries, while the platform's own Site Health page counts 253 zero-amount ledger entries as a warning, so the reader on the ledger cannot tell a flagged row from a normal one. |
| 116 | R-062 | c20 | The drinking-water overview's three counts (Facilities 61, Sampling points 27, Sample results 22,367) have no title of their own and sit under a heading that names something else, 'Population and service connections', so nothing says what this row of figures is a count of. |
| 117 | R-080 | c33 | The monitoring dashboard's fourth tile is a satellite-request quota, '0 of 100 used this month', a different kind of quantity from the three station counts beside it, and nothing sets it apart from them. |
| 118 | R-082 | c33 | One of the six source cards adds a third figure, '· 10 on schedule', and the other five do not, so a reader cannot say whether the others have none on schedule or the figure is simply missing. |
| 119 | R-083 | c33 | The section headed 'Active stations' shows seventeen cards, every one from the same source, under a tile that says there are forty-two active, and nothing says which seventeen these are or how they were chosen. |
| 120 | R-084 | c34 | The third card in a row headed 'Start a filing' is a data check rather than a filing, and nothing says why 'Shared-supply check' is one of three ways to start one. |
| 121 | R-085 | c34 | On the reports page a search box and a status select render above an empty history, so the page offers to narrow a list of nothing. |
| 123 | R-125 | c52 | The recharge list's Capacity column gives a volume in acre-feet with nothing saying what it is the capacity for (one filling, or a year of them), so a reader cannot say what 1281 AF would be compared against. |
| 125 | R-051 | c15 | 'Bank surplus', 'Depreciation / mo (0-1)' and 'Expiry (months)' are grouped under a step called 'Clamp at floor', so a reader cannot say why carrying a surplus forward is part of clamping a number at zero. |
| 126 | R-056 | c19 | Site Health's five cards that name a problem (a failed SSL check, six stale sources, 253 zero-amount ledger entries, an ET agreement outside range, unallocated delivery) offer nowhere to go, so an operator who reads the problem cannot reach the record it is about. |
| 128 | R-063 | c21 | Twenty-seven of the fifty visible facility rows print 'Not recorded' in the Water Type and Well columns, and nothing on the page says whether the federal record is silent for treatment plants or whether this deployment has not imported it. |
| 129 | R-064 | c22 | The facility page's crumb runs Drinking Water → 012 and its one back link returns to the overview, so a reader who arrived from the 61-row facility list has no way back to it except the sidebar. |
| 130 | R-066 | c22 | The facility card has a section headed 'Well' whose only line reads 'Physical well — Not recorded', on a facility whose Type is 'Well', and a reader cannot say whether this facility is a well or is a facility that has no well attached. |
| 131 | R-067 | c23 | Every sampling-point row names the facility the point sits on ('001 — WELL 01A - RAW'), a record with its own page, as plain text, so a reader who wants that facility has to go back to the facility list and search for it. |
| 132 | R-068 | c23 | The largest number in the sampling-points table, 11,827 in the Results column, is not named as a count of laboratory findings, so a reader cannot say whether it is a tally, a measurement or a volume. |
| 133 | R-070 | c25 | In the lab-results log the cell that opens a finding is the Sample Date, which reads '2026-05-21' on every visible row, while the Analyte, the only cell that differs down the screen, is plain text, so the reader has to click a date they cannot tell apart from its neighbours. |
| 134 | R-071 | c25 | Four of the six columns in the lab-results log (Sample Date, PS Code, Method, Laboratory) hold one repeated value down the whole screen, so a screenful of a 22,367-row log shows two columns of information. |
| 135 | R-075 | c30 | A station whose Last Data column says it reported two years ago shows '--' in the Trend column, so a reader cannot tell a station with one reading from a station with none. (ISS-110 part 2, as it renders today.) |
| 136 | R-076 | c30 | The station list's leftmost column is an unheaded coloured dot, and what the colour means is only written in the map's legend further up the page. |
| 137 | R-088 | c36 | The report's type and period print three times before any figure: in the breadcrumb, again as the pane header's title and subtitle, and again as the first two fields of the metadata card. (Template only.) |
| 139 | R-093 | c38 | The two blockers the worksheet names ('No linked water right', 'Add this right's PIN on the water right') identify a record the reader must go and fix, and neither is a link to it. (Template only.) |
| 140 | R-094 | c40 | Where the district's features cluster east of Merced, dozens of markers and their white service-area labels overlap into a pile, so a reader can neither read which area is which nor pick out one mark to open. |
| 142 | R-129 | c54 | The Add Well page's 'Link to parcel (optional)' card shows a heading over empty space with nothing saying it opens, so a reader who wants to attach the new well to a parcel sees a card that appears to be broken. |
| 143 | R-130 | c55 | The bulk-import page is fixed to one record type ('Bulk import — Well') and unlike the Add page offers no way to switch, so a reader who arrived to import diversions has no route on the screen to the import they want. |
| 144 | R-131 | c56 | The user roster's Actions column's only content is the word 'You', so a reader cannot say what actions a row offers or why this row offers none. |

Resolved by 143-01 (2026-09-08, staging only, not yet deployed or checkpointed): 8 of the 99 rows. R-037, R-038, R-039, R-040 by commit `1a043d5`; R-035, R-036 by commit `b8bb296`; R-107, R-108 by commit `a6d96bf`. No after-probe is on file yet: 143-01's Task 7 (deploy, re-probe, `143-01-EVIDENCE.md`) has not run, so these read as fixed-in-template, not measured-on-staging, and the pattern still awaits Brent's approval at the checkpoint.

Resolved by 143-02 (2026-09-11, staging only, not yet checkpointed): 12 of the 99 rows, measured before and after at 1,730 by `.planning/phases/143-pattern-applied/143-02-probe.py` (counts in `143-02-EVIDENCE.md`). R-058 by commit `6709e8d` (the page head: one visible h1 per page; 61 of 63 signed-in pages hid it before, 0 of 69 after); R-021, R-031, R-030, R-015, R-132 by `d7f4747` (the sweep: actions on the title's line, the six descriptions, Profile and About's crumb strips); R-002, R-061, R-024, R-142, R-144 by `5209c86` (one demo notice, the feedback trigger in the sidebar, the OpenH2O mark on every account page, the expired-link titles). R-001 was closed the same day by 143-04 (`b12b75d`, the period card), not by this plan. **R-033 stays open**: an allocation has no page of its own (`accounting/urls.py` has only the list and the create form), so its name has nothing to link to; it goes to plan 143-06 with the allocations table. Two re-measurements at 1,730 differ from the register's 1440 counts: R-024 covered text on 18 pages, not 14 (c30's Syncing header is clear at the wider width); R-021's band rendered on 6 heads plus one content variant (c25).

Two corrections found while closing these rows. **R-036's page scope was wrong.** Filed against c5, c6, c7; measured 2026-09-08 on staging, `/accounting/accounts/create/` (c6) carries no period control at all, and `/accounting/accounts/` (c5) grows one only once an account is selected (`?selected=`); bare, it renders `_account_detail_empty.html`. The control exists in one partial, `_account_detail_pane.html`, reached from the account detail page and from the workspace with a selection. **R-035's page scope was incomplete.** Filed against c7, c36; this plan's own probe found the identical self-referential "Open full page →" link on c45 `/parcels/11/` too, fixed there in the same commit, `b8bb296`. The report page (c36) still carries it and is left for a later plan.

Resolved by 143-05 (2026-09-12, approved by Brent 13:09 PDT on staging `ae0c1be`; production untouched at `241c22b`): 7 of the 99 rows, measured before and after at 1,730 by `.planning/phases/143-pattern-applied/143-05-probe.py` and re-verified directly against the database and the rendered HTML (counts in `143-05-EVIDENCE.md`). Checkpoint ruling (08:04 PDT, Brent): candidate B, one Amount column with the sign sentence moved into the subtitle line, and the filter bar collapsed to one row. R-016 and R-017 by commit `0b2cf1d`: the filter card, three visible rows plus a chip row before, is one row after (`#ledger-filters` 432 to 660px, 228px tall before; 292 to 402px, 110px tall after); the first data row moves from y 723 to y 521; the two paging mechanisms (the jump-to-page input plus the Previous/Next bar) become one (Previous / Page N of M / Next), with rows-per-page kept as its own separate control. R-042 by commit `0b2cf1d`: the bare "1130 entries" line is gone; the subtitle now reads "WY 2025-2026 · 1,130 entries · All amounts in acre-feet (AF)." on a period, "All periods" with no period set, and names a zone or another active filter when one narrows the set. R-018, R-019, R-020 and R-043 by commit `872da0c`. R-018: the settled sentence prints once, in the subtitle, before the reader reaches a row, instead of three statements in three places, two of them contradicting the vocabulary Phase 136 settled (before: 3 statements, 2 wrong; after: 1, correct). R-019: the Description column wraps its full text instead of cutting at 60 characters with an ellipsis (78 of 100 rendered rows truncated before, 0 after; the real 125-character maximum in the period round-trips whole). R-020: within one date, rows now run by use-area number ascending instead of raw seed-insertion order. R-043: a `calculated` row at 0.00 AF carries a muted amount cell and the sentence "No groundwater extraction was derived for this month; rainfall and delivered surface water covered the estimated use." in its Description cell, in place of printing among ordinary rows unmarked (9 of the 100 rows on period 2's default first page, 107 of 215 in the period, 253 of 2,313 overall, all re-counted directly against the database); Site Health's own zero-row message now states the same claim. The pane's ledger card (R-108, closed by 143-01) kept its sentence unchanged under candidate B, since a three-column card with one signed Amount column still needs the sentence beside the numbers it explains; only its template comment was updated to name this plan and where the ledger's own copy of the sentence now lives.

Revised at the 143-05 checkpoint (2026-09-12 11:16 to 13:09 PDT, Brent). The badge Source column and the Water type column became ONE column headed Water whose words come from the reporting systems (GEARS: Metered / Unmetered-Estimated; CalWATRS: the reported diversion): "Groundwater, metered", "Groundwater, estimated", "Surface water, diverted", "{type}, entered" (form or CSV, the same thing), "{type}, adjusted", "Groundwater allocation" / "Surface water allocation", "Recharge credit", written by `accounting/ledger_words.py::ledger_row_words` for the ledger and the use-area pane alike (commits `5f2c33d`, `ae0c1be`; six value guards observed red first). His reason: "Meter reading in the source sticks out compared to surface water diversion"; a metered headgate diversion is still a Surface diversion row, and the platform carries no measurement-method field on a point of diversion. R-018 is therefore closed by structure after all, not by the sentence: the row's own words say whether it is water or paper, and the sentence above the table shrank to two facts at 14px, "Acre-feet. Negative amounts are water delivered or pumped; positive amounts are credits." (his words: the 30-word sentence "covers from a liability standpoint" but "the font is so tiny I wouldn't notice it"). The pane card carries the same column and the same line, and `tests/test_parcel_detail.py` and `tests/test_ledger_navigation.py` pin them together. First data row on staging: y=535 of 1,000 (the facts line is two lines). What the readable Description column exposed, the engines' own labels on ~2,000 rows, is ISS-170, its own plan.

Resolved by 143-11 (2026-09-15, Brent's checkpoint 11:40 PDT on staging `5d5ffcd`; production untouched at `241c22b`): the Description column's engine-written rows, 1,880 of 2,313, now carry one of five sentences kept in `accounting/ledger_words.py` beside the Water column's words and written by `surface/services.py` and `run_calculations.py` (commits `ed4a05e`, `c4f9ccc`). A headgate's delivery split by estimated use: "Share of 214.58 AF delivered from Stevinson Diversion Canal Headgate, split among the use areas it serves by each one's estimated use for the month" (1,141 rows, six headgates); the same split by the fixed share on file, with the percentage and "no estimated use on record for the month" (72 rows); "Credit for canal water delivered beyond the use area's estimated use for the month" (228); "Estimated pumping: the month's estimated use, less rainfall and canal water delivered" (186); and the R-043 zero-month sentence, moved from the template's display-time override into the engine verbatim (253). The POD code left the sentence (the 143-07 map-label ruling), the noun is "use area", and the figure is the delivered amount the shares sum to at the Amount column's two decimals. Not one amount moved: the per-period sums are identical before and after, and the rebuilt golden passed gate 2 exact at 66,505 rows. At 1,730 the column's line counts did not change (42 one-line, 58 two-line cells on page 1, before and after). His reading on staging: rows 1, 4 and 5 fine; the fixed-share sentence "I understand it, but I doubt other people will" (carried to 143.1); the credit sentence questioned the rule behind the credit rather than its words ("So is this supply water in excess of ET? Why would that be credited?"), reopened as ISS-174 for a later plan with the words kept as shipped. Copy rule 14.

Resolved by 143-06 (2026-09-12; staging `ca474be`, approved by Brent 17:17 PDT, production
untouched at `241c22b`): 8 of the 99 rows, before values from
`143-06-probe-before-local.json` and `143-06-probe-before-staging.json` (identical), after values
re-measured directly against the local build's rendered HTML in this task rather than copied from
a builder's own claim (counts in `143-06-EVIDENCE.md`). Checkpoint rulings (`143-06-work/rulings.md`,
14:08 PDT, Brent): "link-zone" (the allocation's row links to the zone page, no allocation page of
its own), footer candidate "A" (each water year closes with its own subtotal, never a cross-year
footer), and the zone-lead panel "as mocked, including the Available segment". R-032 and R-033 by
commit `181fb16`: the Name column, which repeated the zone, water type and water year a row already
stated in its own three columns, is gone from both the allocations list and the water-year page's
table (before: the name contained all three on 10/10 and 8/8 measured rows; after: Zone, Water type,
Allocation, each zone name printing once per row); the zone name is now each row's own link to the
zone page (before: 16/8/0 anchors across the all-periods list, the one-period list and the
period-detail table, all leading to the water year rather than the record the row is about; after:
16/8/8 anchors, one per row on every surface, each `<a href="/map/zones/<pk>/" class="data-table-link">`).
R-041 by the same commit, **closing ISS-164**: a bare landing now defaults to the current period
(`accounting.services.current_period_id`, the helper this plan extracted for the ledger, the
allocations list and the zone view to share) and an explicit "All periods" groups by water year,
each year closing with its own subtotal rows inside the body instead of one footer spanning every
row the filter matched (before: the landing's own Period select read "" (All Periods) and the
footer read 304,200.00 AF, exactly 148,500.00 + 155,700.00; after: "All periods" prints
148,500.00 and 155,700.00 each once, under "WY 2025-2026 · 8 allocations" and "WY 2024-2025 · 8
allocations" respectively, and 304,200.00 nowhere on the page; `?period=2`'s tfoot reads "All 5
surface-water allocations, WY 2025-2026" · 148,500.00 and "All 3 groundwater allocations, WY
2025-2026" · 4,621.27). Proof: `tests/test_allocations_footer.py::TestAllocationsAcrossWaterYears`
(added this task), a VALUE assertion against a fixture holding the same 108,000.00 AF entitlement
in two years, observed red against the pre-plan tree (`02e0359`) before green. R-034 by commit
`181fb16`: the "Summary" tile (Allocations 8, Ledger entries 1130, both plain text) is gone,
replaced by an "Allocations by water type" panel (before: a count of ledger rows was the page's
larger figure; after: Groundwater 4,621.27 AF and Surface Water 148,500.00 AF, a peer panel with
no `--result` since the period holds two types) and the ledger's 1,130 entries as a link,
`href="/accounting/ledger/?period=2"`, in the panel's foot line rather than a bare number. R-101,
R-103, R-055 (zone) and R-112 (zone) by commit `1d365bb`. R-101: before, the table carried no
`tr.th-group` and the Remaining header's "?" popout stated the equation (750.32 + 303.40 − 142.14 =
911.58); after, a `th-group-label` "Available" (`colspan="2"`) brackets Allocation and Carried
forward, one `.col-sep` separates Available from Used, and the popout markup (`class="explainer-popout"`)
is gone from the table. R-103: before, 23 rows and no `tfoot`; after, `tfoot` reads "All 23 use
areas" with 375.16 acres under Area, the view's own `Sum` over the same rows the table prints. R-055
(zone): before, Remaining's computed size (14px) sat smaller than `h2.section-header` (16px); after,
the page's one `.budget-seg--result`, "911.58" AF, renders at 32px, the largest text measured in the
content area (24px, the `.budget-op` "=" sign, next largest); the dashboard and the zone page still
read one `zone_groundwater_budget` call, so both print 911.58 for Halvern Irrigation-Urban GSA, WY
2025-2026, unchanged (`tests/test_zone_budget_shared.py`, green with no edit). R-112 (zone): before,
the two-column row's top sat at y=703 with the columns' own content spanning 1,740px and 314px, a
1,426px run-out; after, the same two columns span 455px and 484px, a 29px run-out, the shape already
measured and approved on the checkpoint's mock-up (`1d365bb`'s own commit message). The other six
R-055 pages (Site Health, the lab result, the shared-supply check, the diversion, the water right,
the recharge event) and the three R-112 pages (the well, POD and add-infrastructure pages) are not
this plan's: the three water pages among them (the diversion, the water right and the recharge
event's R-055, plus all three of R-112's) go to 143-10, which copies the lead-panel and group-header
shapes this plan settled rather than redesigning them; the remaining three R-055 pages (Site Health,
the lab result, the shared-supply check) go to 143-08 and 143-09. Task 6 deployed `0dcb8f0` to staging and re-ran the
probe there (`143-06-probe-after-staging.json`): every figure above identical to local (16
allocations, 148,500.00 and 155,700.00 once each and 304,200.00 nowhere, 23 use areas and 375.16,
911.58 at 32px, 455/484px). Verify checkpoint, first pass, Brent 17:11 PDT: "We should add a color or
some other formatting to the totals values. They just blend into the list. Hard to read." Built as
`ca474be`: `.td-total` on the closing figure of every totals row this plan touched (the one-period
tfoot, the per-year subtotals, the water-year page's tfoot, the use-areas tfoot), the accent the
label already carries, weight 700, 15px against the 13px body (measured on staging: rgb(70,179,196),
15px, 700 on all three pages). Second pass approved 17:17 PDT. Readers: 4 of 5 budgeted (the two
mock-ups, the built zone page locally, the allocations landing on staging; the session's sub-agent
guardrail refused the fifth), allocations SHIP at FINISH 4 both times, the zone page DO NOT SHIP at
FINISH 3 both times for the 380px map at first paint, which is 143-07's.

Resolved by 143-10 (built 2026-09-12; Brent "approved" 2026-09-13 12:06 PDT on staging `6090d2e` after three checkpoint rounds, his rulings recorded as DESIGN.md rules 11-17; production untouched at `241c22b`), applying 143-06's three
patterns class for class rather than redesigning them: 9 of the 99 rows plus the diversion,
water-right and recharge-site shares of R-055 and the POD, well and add-page shares of
R-112 (twelve register rows, fifteen measured keys). Before values from
`143-10-probe-before-local.json` / `143-10-probe-before-staging.json` (identical, captured
2026-09-12 17:46-17:48 PDT); after values from `143-10-probe-after-local.json`, measured
directly against the rebuilt local stack in this task rather than copied from a builder's
own claim (counts in `143-10-EVIDENCE.md`). Commits: `6f5a7d4` (the diversion page and the
water right page), `2721b32` (the recharge list and site page), `888c31f` (the wells list,
the well page, the add page); guards `1759f7d`; the checkpoint rounds `cead0f2`, `9e1d02b`, `6090d2e` (the by-point breakdown under the row, the recharge panel as three cells, the histories level, the map a landscape band, Pumped not Delta, stronger year headers). R-115 by `6f5a7d4`:
the records table's Period column is gone, replaced by `tr.row-group` per water year (before:
one flat row, Period repeating on 4 of 6 rows; after: 2 groups, "WY 2025-2026 · 2 months" and
"WY 2024-2025 · 4 months", each closing with its own `tr.row-subtotal`, `.col-sep` on Retained
alone). R-055 diversion by the same commit: before, Diverted's cell (14px) sat smaller than
the page's largest text (16px, the card head); after, the page's one `.budget-seg--result`,
Retained, renders at 32px against a 14px Diverted cell, the largest text on the page.
R-112 POD by the same commit: before, the two-column body's row (POD information beside the
panel) ran 1,508px against 525px, a 983px difference; after, the same row's content spans
244px and 244px, a 0px difference (the account grid's info/balance pair, not the old
`.page-grid-2col`). R-121 by `6f5a7d4`: before, the face value printed "60000.00" with no
comma and nothing summed the twelve records against it; after, the face value prints
"60,000.00" and the lead panel reads Face value 60,000.00 − Recorded 15,550.00 (a
`budget-breakdown-group` "By point of diversion" naming Merced Falls 14,400.00 and Snelling
1,150.00) = Remaining 44,450.00, all four figures from the same `current_totals` group the
table below is built from (guards assert these as the values, never re-derive them). R-122
by the same commit: before, 3 of 4 multi-POD months printed Snelling before Merced Falls;
after, ordering by `-month, point_of_diversion__name` makes every month (8 of 8 on the local
demo's fuller record set, not the register's original 4) read Merced Falls first, 0
differing from alphabetical. R-055 right by `6f5a7d4`: before, the Face value figure (15px)
sat smaller than the page's largest text (16px); after, the one `.budget-seg--result`,
Remaining, is 32px, the largest text on the page. R-118 by the same commit: before, one of
seven rows carried a DEMO pill in its Status cell; after, `_status_badge.html`'s
`demo_marker=False` on the list drops it from all seven rows (0 in the list body), the
detail page's own pill (`tests/test_demo_marker.py`) unchanged. R-125 by `2721b32`: before,
the list's Capacity header read "CAPACITY" with nothing saying capacity of what; after, the
header reads "CAPACITY PER FILL (AF)", the same words on the site page's field label and
both add-form cards (storage, recharge_site). R-126 by the same commit: before, one Value
column mixed mg/L, ft, cfs and in/hr ordered only by date, no divider; after, one
`tr.row-group` per type present ("WATER LEVEL, FT", "FLOW RATE, CFS", "WATER QUALITY, MG/L",
"INFILTRATION RATE, IN/HR", in `MEASUREMENT_TYPE_CHOICES` order), no header reading "Unit",
18 readings across 4 groups on the seeded site (the register's original count was 10; the
demo has grown since 2026-09-06). R-055 recharge by the same commit: before, the first Volume
cell (14px) sat smaller than the page's largest text (16px); after, the one
`.budget-seg--result`, "318.55" AF (the current water year's own subtotal, matching the
event-history table's own WY 2025-2026 row exactly), renders at 32px, the largest text on the
page; the prior year's subtotal, 637.10, prints only in its own row, never summed with the
current year's. R-110 by `888c31f`: before, the list read "340.00 ft" with no word for what
was measured; after, every row reads "Depth 340.00 ft" (340.00, 430.00, 750.00 ft on the
first three). R-111 by the same commit: before, the Totalizer header ran unitless beside a
"Delta (AF)" header; after, neither header carries a unit ("Date", "Totalizer", "Delta"),
the unit sits once in the meter's own facts line ("Meter MTR-MER-W-001 · reads in acre-feet
(AF) · the delta is the read less the previous read"), and each water year closes with its
own subtotal (811.73 AF, WY 2025-2026; 766.72 AF, WY 2024-2025). R-114 by the same commit:
before, the card read "1.00 fraction"; after, "100% of this well's pumping", worked out in
the view as a whole percent, never `{% widthratio %}`. R-112 add by `888c31f`: before, the
two `.map-form-layout` columns ran 1,385px and 560px, an 825px difference; after,
`align-items: stretch` makes both columns 1,385px, a 0px difference (the map canvas itself is
1,304px inside its 1,385px card, the remainder its own toolbar and coordinate strip, not a
gap between the two columns).

**R-112 well is NOT closed, and this paragraph says so rather than the plan's own assumption
that it would be.** Before, the well page's two-column row ran 1,293px against 2,943px, a
1,650px difference; after, the account grid's info/balance pair itself matches (932.6px /
932.6px, `page-grid-account--source-order` keeping Identification first in the stacked pane,
the main session's own build-time measurement), but the CONTENT inside those two cells does
not run the same length: Identification's own fields run to 880px while the three short cards
(Current meters, Irrigated parcels, Monitoring data) stop at 597px, a 283px run-out under the
short cards, measured by this task's own after-probe. The main session's build-time read of
the same page (`143-10-work/main-session-drift-checks.md`) found 335.6px by a different
method (absolute Y bottoms of the Identification card and the last short card, 1,619.8px and
1,284.2px, against a 1,650px before), a different number from a different measurement, same
direction and the same finding: a real, un-closed run-out, smaller than before (1,650px to
roughly 283-336px) but not gone. This is a genuine content-length mismatch (three short cards
are shorter than a six-section identification form), not a template defect, and it is carried
here rather than marked closed. Deferred and not built: the rights list's face values print
without a thousands separator ("120000 AF", not this plan's row); the recharge panel holds
one figure with nothing set against it (flagged for Brent, not built); the well page's run-out
above; the add page's tall map with a two-column-form alternative not built. R-055's last
three pages (Site Health, the lab result, the shared-supply check) remain for 143-08 and
143-09; R-112 is closed on the POD and add-infrastructure pages and, from 143-06, the zone
page, but NOT on the well page (above): three of the four R-112 pages closed, one carried.
Suite 2,609 → **2,631** (22 new guard tests, all observed red against the pre-change tree
before green). `make test-droppable` green, 30 passed. Staging and Brent's approval are
143-10 Task 6, not run by this task.

Resolved by 143-07 (built 2026-09-13; local stack only, staging deploy and Brent's approval
are Task 8, not this task), closing the twelve map rows: R-023, R-022, R-124, R-094, R-095,
R-096, R-100, R-102, R-123, R-074, R-075, R-076. Before values from
`143-07-probe-before-local.json` / `-staging.json` (Task 1, 12:50-13:00 PDT); after values
measured directly against the rebuilt local stack in this task. Commits, in order: `9310657`
(the overview map card, Surface Diversions), `69978e3` (Brent's 14:01 PDT bracket-header
ruling, applied platform-wide), `1dc1e67` (`map_label`, the code-prefix/parenthetical strip,
and `zone_labels_geojson`'s `pk`/`zone_type`/`label`), `133a767` (Recharge), `2b6f6cf`
(Zones), `7d1431c` (Sampling Points, Facilities), `9b8aac7` (Stations: R-074, R-075, R-076),
`e49abe2` (the main session's drift fixes after Task 4, below), `c93a0a2` (the district map:
R-094, R-095, R-096), `362427e` (the draw maps, ISS-171, the zone's use areas, the right's
popup link), `4868347` (the boundary label, one per feature). Guard commit and register
annotation follow in this task.

**R-023** (four overview maps and the stations list ignored the list's own filter). Before:
Surface Diversions, Recharge, Zones and Sampling Points installed no listener for `#results`'
htmx swap, so a one-row match still rendered every mark; Sampling Points' coverage sentence
kept saying "21 of 27" through a filter that had already narrowed the list to zero. After:
`OH2O.followResults` reads the filtered queryset's pks from a `results-map-pks` `json_script`
after every swap of `#results`, `setFilter`s every layer (marks and label alike) to them, and
re-frames; the card head above the map (never inside `#results`) is the one count line and is
re-rendered `hx-swap-oob="true"` on the same swap. Measured on the local demonstration at
first paint: 9 diversion points, 7 recharge sites, 9 zones (8 on staging), 21 of 27 sampling
points at a located facility, 42 stations syncing; after a one-row match on each, the map's
rendered-feature count equals the list's own count, in both directions (a widened filter
re-populates the map, never only narrows it). ISS-136 closes on Ruling A (below): every
overview map follows its list; the facilities/sampling-points sentence shrinks to the
located-subset gap it was already carrying, rather than growing a sentence to the other four
pages.

**R-022** (Surface Diversions: nine unlabelled dots, no legend, the count line under the map).
Before: "9 diversion points found" sat under the filter card, not with the map; nine plain
teal dots, no label, no key. After: the card head reads "9 diversion points, all on the map"
with a `.swatch-dot` and "Diversion point" beside it on the same line; an always-on label per
point (`OH2O.addDetailLabel`, collision-yield, never `text-allow-overlap`): 8 of 9 render at
the fitted zoom, the ninth two points ten pixels apart where no layout fits both labels at
once and it yields, the dot stays. Card approved by Brent 14:10 PDT with one change: the
label drops the stored name's code prefix ("Atwater Canal Headgate", not "MER-POD-004-DEMO
Atwater Canal Headgate", `map_label`, Step 0).

**R-124** (Recharge: two faint smudges for seven sites). Before: fill opacity 0.22, outline
1.5px, no label, five El Nido basins read as one faint cluster. After: opacity 0.35, outline
2.5px; a second client-side source (`{{ map_id }}-labels`, one point per site at its own
bbox centre, never per polygon ring) with an always-on label. The main session's drift read
after Task 4 (14:50-15:20 PDT) found the first pass had painted all seven names with
`text-allow-overlap`: seven labels on top of one another read as none, fixed in `e49abe2`
to the same collision-yield rule R-022 uses: 4 of 7 render at first paint, the rest yield as
the reader zooms in.

**R-074** (Monitoring Stations: the list and the map disagree). Not reproduced as written at
first load: `stations_freshness_geojson` filtered `is_active=True` (42) and the list defaulted
to `active=1` (42), so the two agreed at 42 = 42 by coincidence, not by design; the register's
reader had read the grey "Dormant" dots (a freshness state) as stations outside the list. Its
CLASS did reproduce on every filter: choosing "Not syncing" left the list at 293 and the map
still at 42. After: the endpoint serves every LOCATED station regardless of `is_active`, with
`is_active` riding in properties, and `OH2O.followResults` (never the endpoint) decides what
draws by filtering to the list's own pks; "Not syncing" now reads list 293 = map 293.

**R-075** (a bare `--` for both a one-reading station and a zero-reading one). Before: the
Trend cell read `--` either way. After: "No trend yet" (`reading_count == 1`, too few for a
sparkline but not "no data") and "No readings" (`reading_count == 0`), the view's own count,
never a dash.

**R-076** (an unheaded coloured-dot column). Before: the first `<th>` was empty, its meaning
only in the map's own legend box further up the page. After: the header reads "Reporting",
the cell carries the dot AND the word ("Up to date" / "Slightly behind" / "Dormant"), the
same three words the filter and the card's key (below) use, and the in-map legend box is
gone (the head above the map is the key now, one place, not two saying the same three things).

**R-094 / R-095** (the district map's pile and its legend). Before: the `zones` source drew
management-area GSA zones and surface service areas in one fill layer; the legend named three
near-identical greens (`#2d6a4f`/`#40916c`/`#52b788`) while the Layers panel counted eight GSA
Zones (five of them unnamed service areas), and the service areas' four-line white labels
piled against the wells cluster east of Merced. After: two layer groups on the SAME source,
filtered the way their MapLibre `filter` narrows (`zones-fill`/`zones-label` on
`management_area`; `service-areas-outline`/`service-areas-label`, dashed, outline only, on
everything else): Layers panel now counts GSA Zones 4 locally (3 on staging, no Debug Zone)
and Surface service areas 5. Three fills a reader can tell apart (`#3a9742` forest-teal,
`#00969f` reservoir-blue, `#cc5900` furnace-orange, from DESIGN.md's OKLCH ramps, none the
parcel/recharge/POD/drinking colours), derived in `map_view` and never hardcoded. Pile: the
service-area label sits at `minzoom` 11 (the layer and its popup don't exist below that),
`text-max-width` 10, sorts after the GSA labels, and reads `short_label` (the part of the name
after the em dash) rather than the full composed name. Measured after: 3 GSA labels at first
paint, 0 label-on-label overlap (the probe's residual "overlap" counts were dot circles, not
text). Accepted by the main session's read after Task 5 (15:45-16:20 PDT): service areas as a
gold dashed line beside the solid gold agency boundary, the same administrative class: every
other colour already taken.

**R-096** (the Layers panel sliced through "MONITORING"). Not reproduced as written at 1,730 x
1,000 (the panel fit; Task 1 measured it there); reproduces at 1,440 x 900, the register's own
viewport. After: `#controls.panel-can-scroll::after` (`static/css/map-engine.css`), a 28px
bottom fade in the card colour, shown only while `.panel-body` can scroll further
(`map-engine.js` toggles the class) and gone once scrolled to the end; `scrollbar-gutter:
stable` keeps the thin scrollbar off the last row's text. The DOM measurement at both
viewports (whether the fade actually shows, and where the panel's last row sits) is a browser
fact this suite cannot see (`tests/test_map_legend.py`'s own docstring); Task 8's staging
read is the measurement; the guard here only proves the stylesheet rule exists for the toggle
to reveal.

**R-100** (the two draw-your-own-geometry maps open with no district). Before: both
`/map/zones/create/` and `/infrastructure/add/?type=well` opened at `[-119.5, 37.3]` zoom 8
with no boundary layer: the probe's own `boundary_layer_present: true` on `/map/` was a
naming artifact (the BASEMAP style's `boundary_state`/`boundary_country` layers, not an agency
boundary). After: `OH2O.frameOnBoundary` fetches `geography:boundaries_geojson`, draws an
outline and an always-on label, and `fitBounds`es on it before the drawing layers go on top;
with no boundary rows a deployment degrades to today's centre/zoom, unchanged. The local
database carries a stray "Boundary 0" (pk 2, near Hanford) and a "Debug Zone", local test
debris, absent on staging (`boundaries_geojson` feature_count 1 there), left in place so
Task 8's after-probe compares like with like; staging is the judged host. The boundary label
itself painted twice for a two-part `MultiPolygon` boundary; fixed in `4868347` to one label
per feature from a bbox-centre point source, the same fix shape as R-124's per-site label.

**R-102** (the zone's own map draws the outline and none of its named use areas). Before:
`/map/zones/2/` showed the outline alone while the list beneath named twenty-three assigned
use areas; the same map's own zone label painted six times (once per polygon part). After:
`zone_detail`'s view adds `parcels_geojson` (the zone's assigned parcels, `parcel_number` +
`pk`), rendered beneath `zone-fill` in the parcel blue with a "View use area →" popup link;
23 parcels drawn under the outline on the demonstration's own populated zone. The six-times
label: `_addDetailLayers`'s polygon branch reads a new `label_point` property
(`point_on_surface`, the same mechanism `zone_labels_geojson` already used on the big map):
one label for the whole zone, not one per part.

**R-123** (the water right's map popups have no link). Before: a diversion point's popup
carried a name, a stream and a rate and nothing to click, while the same name in the table
beside it was a link. After: the popup gains a "View diversion →" link built from the
`pod_detail` sentinel URL (`'/surface/diversion/0/'`, swapped for the real pk client side, the
house pattern every overview partial already uses); `pods_geojson` for the right now carries
`pk` in `properties` (the serializer otherwise puts it at the feature's top level). Measured
after (staging demonstration, right pk 6): the popup's link resolves to
`/surface/diversion/8/`.

**Brent's three Task 3 rulings (2026-09-13 14:10 PDT, "proceed as suggested"), quoted, are
the authority for the shape above:** (1) **A**: every overview map follows its list; ISS-136
closes on A. (2) The card as built on Surface Diversions is **approved**, with one change:
drop the code prefix from every map label. (3) **Keep 380px** on the record pages; fix what is
in the band (R-102); DESIGN.md rule 15 is unchanged. A fourth ruling, 14:01 PDT, moved the
grouped-table bracket header from centred to left platform-wide (`.data-table--grouped
th.th-group-label`, `69978e3`) after Brent named it on the zone page's Available bracket;
carried here because Task 7's guard for it lives beside these twelve, not because it is one of
the twelve rows.

Guards: thirty-one new tests across `tests/test_overview_map_card.py` (new),
`tests/test_input_validation.py`, `tests/test_views.py`, `tests/test_map_legend.py`,
`tests/test_datasync_honesty.py`, `tests/test_zone_detail_page.py` and
`tests/test_template_hygiene.py`, each observed RED against the pre-change tree (the parent
commit of the row's own feature commit, copied into the running container over the built
image, `docker compose cp`, never `git stash`) before GREEN against the built tree; the
failing assertion for every guard is quoted in `143-07-EVIDENCE.md`. Suite 2,641 → **2,672**.
`make test-droppable` 30. Staging: the after-probe (`143-07-probe-after-staging.json`) matched
local on every row (8 zones and one boundary on staging, where local carries a Debug Zone and a
stray Boundary 0). Brent's staging round, 18:24 PDT, sent four things back and `8da1fcc` fixed
them the same hour: circles on every basin vertex (the list filter had replaced the dots layer's
own Point filter; it now ANDs the pks with each layer's own filter), the longitude box that
could not be edited (a typed pair no longer rewrites the inputs under the cursor), the zone
page's "Available" back to centre (DESIGN.md rule 18), and the sampling-points line in plain
words ("27 sampling points, 21 of them on the map"). **Approved 18:47 PDT on staging `8da1fcc`;
production untouched at `241c22b`.**

Resolved by 143-08 (built 2026-09-15; local stack only, staging deploy and Brent's approval
are Task 6, not this task), closing the drinking-water half of the eleven rows: R-062, R-063,
R-064, R-066, R-067, R-068, R-069, R-070, R-071, R-073, and the lab-result share of R-055.
ISS-135 closes with it. Before values from `143-08-probe-before-local.json` /
`-staging.json` (Task 1, byte-identical across hosts, captured 2026-09-15 12:36 PDT; local
`7c368d1`, staging `5d5ffcd`, production `241c22b`); after values measured directly against
the rebuilt local stack in this task, re-running Task 1's own probe script rather than
copying a builder's own claim (`/tmp/143-08-after-for-register.json`; the plan's official
after-probe, `143-08-probe-after.py`, is Task 6's). Commits: `a5bade8` (the three lists and
ISS-135), `7672b0e` (intcomma on the results-log count pill), `b3af011` (the three record
pages), `e96f442` (the points/results tables re-seated in a zero-padding card), `fcc4d11`
(the overview's records card and the builder as one form).

**R-062.** Before, the three tiles sat under "Population and service connections", a
heading naming something else. After, an `h2` reading "Records for this system" heads the
tiles at the foot of the identity card itself; the tiles are byte-identical to before this
task (`tests/test_drinking_module_shows_what_to_do.py` untouched, green). Task 4 first
built them as a second card beside the identity card (the account-grid row); Brent at the
checkpoint, 2026-09-15 17:18 PDT: "three boxes inside of a giant box with empty space is a
little awkward. Seems like these three boxes would be better in the box to the left that
holds the City of Merced data." Folded in on `52f623b`.

**R-063 / ISS-135.** Before, of the 50 visible facility rows 22 read "Not recorded" in
Water Type and 32 in Well (Task 1 measured 22/32, not the plan's rough guess of 27 for
either), no text on the page said why either cell was empty; the Type and Status selects'
`hx-include="[name='q'], …"` matched the header's own search box too, so a filter change
sent `q` twice (`?facility_type=DS&q=&q=&activity_status=`). After, the card head reads "61
facilities: 31 sources, 29 treatment plants, 1 distribution", a GW source's cell reads
"Ground water", a non-source facility's Water Type and Well cells both read "Not applicable"
(**a documented deviation from the plan's own literal dash**: `tests/test_template_hygiene.py`
forbids a bare dash between two angle brackets as a value, so the built wording is "Not
applicable", never a bare dash), and a
well with no link reads "Not linked", distinct from "Not applicable". Both selects and the
search input now scope their `hx-include` to `#filter-search, #filter-activity-status` /
`#filter-search, #filter-facility-type`, and `sampling_points.html`'s identical selector was
fixed in the same commit; re-verified live: `?facility_type=DS&q=&activity_status=`, once.

**R-064 / R-066.** Before, the facility page's crumb read Drinking Water → 012 with no link
back to the 61-row list, and the back link went to the overview; the "Well" section's only
line named the field "Physical well" and read "Not recorded" beside it, on every facility
type, well or not. After, the crumb carries a `Facilities` link to `/drinking/facilities/`
and the back link reads "← Back to Facilities"; the well field renders ONLY on a
`facility_type == "WL"` facility, as "Metered
well" (the link when one exists, "Not linked" when it does not), and a treatment plant or
the distribution facility carries no well field at all.

**R-067 / R-068.** Before, the sampling-points list's Facility cell was plain text on every
row (measured: 0 of the visible cells carried an anchor) and the "Results" header named
nothing. After, every Facility cell carries `<a href="/drinking/facilities/<pk>/">`
(measured: `all_facility_cells_have_anchor` true) and the header reads "Sample results"
(`th-stack`), intcomma'd (`tests/test_drinking_lists_explain_their_columns.py`'s own fixture:
1,234 results renders "1,234").

**R-069.** Before, point 1's results table repeated its Sample Date, Method and Laboratory
down all 25 rows (Task 1 measured 1 distinct date, **2** distinct methods, not the plan's
"1", and 1 distinct laboratory) under the heading "The 25 most recent of 796 results". After,
"Sampling history" is gone as a section; the results card's own head reads "796 sample
results · 151 analytes · sampled 2023-08-24 to 2026-02-04" and, truncated, "The 25 most
recent are below; the full log is at Sample results" (re-verified live against
`/drinking/sampling-points/1/`); the table carries 1 `tr.row-group` (point 1's most recent
event, 2026-02-04, holds 29 results and `RECENT_RESULT_LIMIT` shows 25 of them, cutting
inside the event, exactly as the plan's own measurement said it would).

**R-070 / R-071.** Before, the results log's link cell was Sample Date, reading
"2026-05-21" on every one of the 50 visible rows while the Analyte cell (the one that
differs) was plain text; four of six columns held one repeated value down the page (Sample
Date 1, PS Code 1, Method 1, Laboratory 1 distinct value; `RESULT` 3), no `tr.row-group`, 1
distinct event id on the whole first page (every row from one sample event). After, the
Sample Date and PS Code columns are gone, the Analyte cell carries the link, and the table
groups by sample event through `group_results_by_event` (the one helper both this page and
the sampling-point page call): measured live, the log's first page now carries a
`tr.row-group` divider ("Sampled 2026-05-21 at CA2410009_011_011 … 68 results, 44 on this
page") ahead of that event's rows. The new guard's own fixture (two points sampled the same
day, three results each) renders exactly 2 groups in PS Code order, never interleaved.

**R-055 (lab-result share).** Before, the finding sat in one of 18 equal `.field-group`
cells (Task 1 measured 18, not the plan's "sixteen"), the page's largest text was
`h2.section-header` at 16px (the Result value itself rendered at 15px), no
`.budget-seg--result` existed, and "Regulatory limit" did not appear. After, the finding
leads the account-grid panel in `.budget-seg--result` at 32px, the largest text measured on
the page (re-verified live), with two peers, Reporting level and Previous finding; the
`.field-group` count on the same page drops to 12 (the Result, Unit, Result type and
Reporting level fields moved into the panel); "Regulatory limit" is still absent, now with a
real `RegulatoryLimit` in TWO fixtures rather than one (the standing ISS-140 test, extended
rather than weakened, and this plan's own `tests/test_lab_result_page.py` fixture).

**R-073.** Before, the builder rendered 61 `form[hx-post]` elements and 61 facility panels,
no facility select, at a full-page height of 8,990px. After, one `form[hx-post]`, one
`select[name="facility"]` with 61 options (sources first), one grouped table (23
`tr.row-group`, one per facility that carries a point; the plan's own "(14)" was a guess,
not a measurement), at 3,827px. A duplicate POST returns "already listed" alongside the
regenerated whole table; a new POST adds its row under its own facility's group.

**Main-session drift checks**, run before each of Tasks 3 and 4's dispatches, per the plan's
own drift trap: "Task 2: `ledger-card-head` in the ledger list's no-h2 form and
`data-table--grouped` with `tr.row-group` > `td[colspan=4]`, the platform's group-header
style as on surface-diversion-9; classes match." / "Task 3: `.card-raised.page-grid-account-balance`
> `.page-grid-account-head.mb-md` > `.budget-panel` > `.budget-seg--result` + two
`.budget-seg` peers with empty `.budget-op`, as on recharge-1; the record pages' head+table
re-seated in a zero-padding card (e96f442) to match 143-06; classes match." / "Task 4:
`.page-grid-account` info + balance row as on the account page; the builder's
`data-table--grouped` divider as on surface-diversion-9; classes match."

**Brent's two rulings, quoted with their time.** [2026-09-15 12:09 PDT] the split (drinking
now, the monitoring-and-reporting half after this checkpoint, in 143-12) and **builder design
A**: one "Add a sampling point" form with a Facility select over one grouped table, applied
and not reopened. [2026-09-15, at plan time, "I don't know what this means"] on the
lab-result panel's two peers: it ships with the reporting level and the previous finding as
built above; he rules on it at the checkpoint, where he can see it (human-verify item 3), not
in a menu.

**Checkpoint, 2026-09-15 17:18 PDT, staging `57fce26`, then `52f623b`; approved 17:26 PDT.**
Results log "Looks fine"; lab result "Looks fine, but there's a lot of blank space. I guess
that's okay because it's the result you're looking for"; builder "Works". Two more rulings
built on `52f623b`: R-062 as above, and the map coverage sentence on the facilities and
sampling-points lists ("so distribution-system and treatment-plant facilities carry none and
cannot be placed on a map") named as awkward AI language and rewritten: "The state's
Groundwater Ambient Monitoring and Assessment Program (GAMA) publishes coordinates for
groundwater sources only, so the treatment plants and the distribution system are not on
it." Two questions answered by measurement, not built: the panel's colours do not change
above the reporting level (a detect, result 10012 at 0.71 against 0.5 UG/L, renders in the
same colour; only the caption changes), and the record holds no California MCL:
`RegulatoryLimit` has 32 rows, all federal, covering 32 of 159 sampled analytes and 2,055 of
22,367 results; his words ("any result in exceedance of the MCL would be red") are recorded
against ISS-140 as the reopen question.

**R-055's other two pages remain.** The shared-supply check and the monitoring-and-reporting
share of R-055 go to 143-12; Site Health's own share goes to 143-09. Neither is touched here.

Guards: 33 new tests across three new files: `tests/test_drinking_lists_explain_their_columns.py`
(R-063, ISS-135, R-067, R-068, R-064, R-066, R-062, R-073), `tests/test_results_grouped_by_event.py`
(the `group_results_by_event` helper tested directly, R-070/R-071, R-069), and
`tests/test_lab_result_page.py` (the R-055 share). Each was observed RED against the pre-change
tree (`git checkout 7c368d1 -- templates/drinking drinking/views.py static/css/app.css`,
rebuilt, run, then restored to HEAD and rebuilt again), the failing assertion for every guard
quoted in `143-08-EVIDENCE.md`. `tests/test_water_vocabulary.py`, `tests/test_domain_vocabulary.py`,
`tests/test_template_hygiene.py`, `tests/test_module_template_guards.py`,
`tests/test_composition_rule.py`, `tests/test_drinking_readability.py`, `tests/test_drinking_map.py`,
`tests/test_overview_map_card.py` and `tests/test_drinking_module_shows_what_to_do.py` all
green with no edit beyond the two files Tasks 2 and 4 already retargeted
(`tests/test_drinking_detail_views.py`, `tests/test_drinking_readability.py`). Suite 2,697 →
**2,730**. `make test-droppable` 30. Staging and Brent's approval are Task 6, not this task;
production untouched at `241c22b` (re-read from the host).

Resolved by 143-12 (built 2026-09-15; local stack only, staging deploy and Brent's approval
are Task 6, not this task), closing the monitoring-and-reporting half of the former 143-08:
R-077, R-078, R-079, R-080, R-081, R-082, R-083, R-084, R-085, R-087, R-088, R-089, R-090,
R-091, R-093, and the monitoring-and-reporting share of R-055 (the shared-supply check).
Sixteen entries, all closed by measurement rather than by the plan's own guesses. Before
values from `143-12-probe-before-local.json` / `-staging.json` (Task 1, captured 2026-09-15
18:22-18:23 PDT; local served `7fa0c4e`, staging served `52f623b`, production `241c22b`);
after values re-run directly against the rebuilt local stack in this task rather than copied
from a builder's own claim. Commits: `c9c4615` (station page), `f8679f5` (dashboard),
`e3b026b` (reports page), `96bb306` (report page), `1a65f70` (worksheet), `e30fb2e`
(generator + view: `your_pct`/`et_pct`/`gap_points`, `?show=flagged`, panel counts), `b8d152a`
(shared-supply template).

**R-077 / R-078.** Before, station 1's Telemetry card drew a 319px chart against a 0-to-1.0
axis with 11 tick labels for a station that had never published, `chart_empty` already
visible reading "No published data for this period.", and the freshness word appeared
nowhere on the full page (`freshness_word_hits` false for all three words; `page_head_meta_text`
empty). After, `.page-head-meta` carries a badge reading "Dormant" (measured live: 0
`id="telemetry-chart"` canvases, 0 `<button class="chart-range-btn">` elements, "No published
readings from this station." and "Syncing is switched off for it." both present); a station
with one fresh reading renders the canvas and "Up to date". The Current Readings card (before:
one of five one-sentence cards, "No published readings yet.") is gone when there is nothing to
read; the two empty history cards (Recent sync logs, Recent data records: two more of the
five one-sentence cards) merge into one "Sync history" card. "On schedule" / "Behind schedule"
appear nowhere on this page.

**R-079 / R-080.** Before, the dashboard's `stat_grid_4col` held four like 36px tiles: "Active
stations 42", "On schedule 2", "Behind schedule 40" (the register's original guess of "10 on
schedule" / "32 behind" was already stale by Task 1's own re-measure: 2 fresh, not 10, and the
true split is three-way (2 fresh, 15 stale, 25 dead), not the two `stat_grid_4col` ever
showed), "Satellite data requests 0", with no sentence saying the last three are parts of the
first. After, `stat-grid-4col` is gone (0 occurrences); the map card's head reads "42 active
stations: 2 up to date, 15 slightly behind, 25 dormant" (station-list vocabulary); the
satellite quota is a sentence under "Source status" ("... 0 of 100 requests used this
month ..."), not a fourth tile.

**R-081 / R-082.** Before, on local FOUR of six source cards read "Not yet synced" with no
sentence saying what that means (cimis and noaa read "Needs API key" locally: noaa has no key
set on local, so it takes the credential branch instead); on staging FIVE cards read "Not yet
synced" (noaa's key IS set there, so it clears the credential check and falls through to
"never"; cimis instead reads "None activated" on staging, because its 15 stations are
discovered but none switched on). Both are real, hosts-differ readings, not a bug: `never` vs
`needs_key` vs `none_activated` are three different classifications and the demo data differs
by host. Only one of six cards (`dwr_sgma`) carried the "· 2 on schedule" clause; the other
five carried none. After (measured against a fictional-source fixture, `tests/
test_monitoring_dashboard_counts.py`): every source card renders one shape,
"{active} active of {total} stations: {fresh} up to date, {stale} slightly behind, {dead}
dormant", zeros worded "none"; a `never`-status card also carries "This deployment has not run
a sync against {SOURCE} yet; the readings it holds were loaded, not synced."; a card with zero
active stations stops after "{total} station(s), none active" rather than printing three more
"none" clauses.

**R-083.** Before, "Active stations" showed 17 cards, all `dwr_sgma` (the only source with
fresh/stale members), under a dashboard claiming 42 active, with no sentence saying which 17
or why. After, the section's own line reads "{shown} of the {total_active} active stations:
the ones up to date or slightly behind. The {dead_count} dormant are on the
[station list](?reporting=dead)."; on local this reads "17 of the 42 active stations ... 25 dormant ...".
The `{% if item.freshness != 'dead' %}` filter is unchanged; the head now says it instead of
leaving it silent.

**R-084 / R-085.** Before, the reports page's third "Start a filing" card ("Shared-supply
check") carried no marker distinguishing it from the two filings beside it; on local the
toolbar (search + status select) rendered over 3 history rows (not empty, so not R-085's
fault there), but staging's `toolbar_row_present` was `true` over 0 rows: the register's own
read, reproduced. After, the third card carries `badge-grey` "A check, not a filing" and its
sentence names what it compares; `all_count` (every submission, unfiltered) gates the
toolbar, so a deployment with zero submissions anywhere renders no toolbar at all (measured:
`tests/test_reports_pages_explain_themselves.py`, no `ReportSubmission` rows -> 0 `toolbar-row`
occurrences). The `count-pill` span R-085's own guard used to key off is gone; the population
line in the table's own `ledger-card-head` carries the count instead (retargeted in
`tests/test_views.py::test_report_list_htmx_returns_history_partial`, done in Task 3).

**R-087 / R-088.** Before (report pk 5, the file this plan generated; pk 3, no file): the
template name printed 3 times (the head, a `.row-start` crumb row under the demo notice, and
the metadata card's first field) and the period name 3 (pk 5) / 2 (pk 3) times, before any
figure; Download sat as the fourth of four 14px metadata fields, `btn_primary_in_page_head_
actions_count` 0. On staging both report URLs (pks 3 and 4) 404 (0 rows: staging holds no
report rows until Task 6 generates one there). After, `page-head-actions` carries exactly one
`a.btn-primary` reading "Download CSV" linking `reporting:report_download`, and no button at
all when there is no file; the `.row-start` crumb row is gone, replaced by a plain "← Back to
Reports" link; the metadata card carries only Generated and File. The template name now prints
3 times total on the page (the `<title>` tag, the `h1.page-title`, and the breadcrumb's
current-page span), not "once below the head" as the plan's own `<verify>` block guessed;
0 additional occurrences anywhere in the body, confirmed live.

**R-089 / R-090 / R-091 / R-055 (shared-supply check).** Before, the page's only control was
the period select (`period_form_control_count` 1); the "8 hand-set shared sources · 3 flagged
· gap threshold 15 points" line was 13px text over the toolbar, no `.budget-seg--result`
existed; Gap printed a raw four-place fraction ("0.0804", "0.0842", "0.4351") against a rule
stated in points, with no `.th-group-label` or `.col-sep` marking it derived; eight
`card-raised` blocks ran the page to 4,393px. After: two selects (period, show); the panel's
one 32px result is "Sources flagged" with two peers ("Sources checked", "Fields to review");
Share and Gap both print in percent / percentage points from the SAME weight (`your_pct` /
`et_pct` / `gap_points`, added to `_compare_split`'s existing keys, quantized `Decimal("0.01")`
`ROUND_HALF_UP`); one `table.data-table--grouped` replaces the eight cards, Gap bracketed off
by `.th-group-label` "Share of the source water" (Brent's wording at the checkpoint, 2026-09-16) over "Entered"/"ET-implied" and a
`.col-sep` th-stack "Gap points"; `?show=flagged` narrows the table to the flagged groups
while the panel keeps counting the whole period. **Deviation, measured, not built to the
plan's guess:** Task 3's card sentence ("a shared well or canal") failed `make test-droppable`
2 of 30 (`without-wells`, `without-surface+recharge`) because the reports page renders in
every module set; reworded to "a shared water source", and an EXEMPT entry
(`("surface", "reporting/calwatrs_worksheet.html")`) was added to `tests/
test_module_template_guards.py` because that guard is the view's 404, not a template gate.
Task 4: the full page is 3,708px, not the plan's guessed under-2,600 (74 table rows at the
platform's row height are 2,898px alone); `?show=flagged` shows 18 rows on the real demo data,
not 22 (the three flagged groups hold 5+10+3); "15" (the threshold) prints twice as prose (the
paragraph and the panel caption), both mandated by the action's own text. The remap needed
`--alias` for the three shared-supply sites because the expression text changed (`your_weight`
to `your_pct` etc.); ids kept, no gains or losses. This task's own guard fixture (`tests/
test_shared_supply_check_page.py`, a hand-set well, 0.6/0.4 stored, 5/20 demand) found a
second plan guess wrong: BOTH parcels diverge past the 0.15 threshold (|0.6-0.25| and
|0.4-0.75| are both 0.35), so "Fields to review" reads 2, not the plan's guessed 1; the guard
asserts the measured value.

**R-093.** Before, on local (`report_type_is_available` false: `surface` reachable, but the
demo's two blocks both carry a right and a PIN, so `has_no_linked_water_right` and
`has_add_pin_text` were both `false`, proving the blockers by absence rather than by
appearance) both blockers were plain text, 0 anchors in either block's `.field-value-sm`; on
staging the same URL 404s (0 rows, no `surface` reachable path to prove against there either).
After (fixture-proven, `tests/test_reports_pages_explain_themselves.py`): a block with no
linked water right renders "No linked water right; link one on [the point of diversion]"
(`surface:pod_detail`); a block with a right and no PIN renders "Add this right's PIN on [the
water right]" (`surface:detail`).

**Drift checks, main session.** (a) After Task 2, the dashboard's map card is
`div.card-raised[style="padding: 0; overflow: hidden;"]` > `_stations_map_card_head.html`
with `head_id="monitoring-map-head"`, the same two lines as `station_list.html:43-44`: MATCH.
(b) After Task 3, `_report_history.html` is a zero-padding `card-raised` > `ledger-card-head`
with two `text-secondary text-base` lines > `table-scroll` > `data-table`, the shape of
`_diversion_records.html:16-25`, with no `h2.section-header-flush` inside the head because the
page already carries `h2.section-header` "Report history" above the toolbar (rule 6, one
name): MATCH. (c) After Task 4, the panel is `.page-grid-account-balance` >
`.page-grid-account-head.mb-md` > `.budget-panel` with one `.budget-seg--result` at 32px, two
peers and two empty `.budget-op`, and the table head is `tr.th-group` > `th[rowspan=2]` /
`th.th-group-label[colspan=2]` / `th.th-right.col-sep[rowspan=2] > .th-stack`, the classes of
`_zone_detail_pane.html:151-161`: MATCH. One composition fault named for the next reader: in
the first-paint capture the Gap column and the trailing flag column take roughly 330px and
470px of the 1,440px table, so each Gap figure sits ~250px right of the ET-implied figure:
browser auto-layout, not a class drift.

**Plan-level judgments, stated as the plan's until Brent rules (Task 6's checkpoint):** the
dashboard's counts sit in the map head and under the section headers because the page has no
identity card to fold them into; the OpenET quota is the Source status sentence rather than a
seventh card; percent to two decimal places is the reading of the shared-supply weights under
ISS-142.

Guards: 24 new tests across four new files: `tests/test_station_page_says_its_state.py`
(R-077, R-078), `tests/test_monitoring_dashboard_counts.py` (R-081, R-082, R-083),
`tests/test_reports_pages_explain_themselves.py` (R-084, R-085, R-087, R-088, R-093),
`tests/test_shared_supply_check_page.py` (R-055 share, R-089, R-090, R-091), plus an
extension of `tests/test_openet_budget_panel.py`'s own fixtures (R-079, R-080). Every guard
observed RED against the pre-change tree (`git checkout 7fa0c4e -- ` the thirteen template
and view files this plan touched, rebuilt, run: 26 of 26 failed, two by `KeyError` on
`your_pct`/`et_pct` proving the generator did not carry them yet, the rest by assertion, then
`git checkout HEAD --` the same files, rebuilt, GREEN), the failing assertion for every guard
quoted in `143-12-EVIDENCE.md`. `tests/test_water_vocabulary.py`, `tests/test_domain_
vocabulary.py`, `tests/test_template_hygiene.py`, `tests/test_module_template_guards.py`,
`tests/test_composition_rule.py`, `tests/test_figure_ledger_coverage.py` all green (296 tests).
Suite 2,730 → **2,754**. `make test-droppable` 30 passed. **R-055's Site Health share remains
for 143-09**; nothing on that page is touched here. Staging deploy, the staging after-probe,
and Brent's approval are Task 6, not this task; production untouched at `241c22b` (to be
re-read from the host by Task 6).

Resolved by 143-09 (built 2026-09-16; local stack only, staging deploy and Brent's approval
are Task 7, not this task), closing sixteen rows outright and R-055 on its seventh and last
page: R-045, R-046, R-047, R-050, R-051, R-052, R-054, R-056, R-060, R-117, R-129, R-130,
R-131, R-137, R-138, R-140, and the Site Health share of R-055. Seventeen entries, all closed
by measurement rather than by the plan's own 09:35 guesses, four of which differed: staging's
health chip read "8/13 healthy" where local reads "7/13 healthy" (a genuine host difference in
which checks are stale, the same class as 143-12's NOAA/CIMIS split); the anonymous grid
resolved to 5 columns per row at 1,730 (`grid_columns` `[5, 5, 5]`) where the register's 1440
capture read four; the hero's before-status read "2 of 42 stations reporting" where the
register's original finding named "10 of 42"; and the roster held 2 rows locally
(`admin@local.dev`, `dbg@example.com`) against the register's 1 row on staging. Before values
from `143-09-probe-before-local.json` / `-staging.json` (Task 1, captured 2026-09-16
11:54-11:55 PDT; local and staging both served `ea96977`); after values re-measured directly
against the rebuilt local stack in this task (both the fixture guards and, wherever a page
takes no fixture, a live authenticated request through Caddy at `http://localhost/`) rather
than copied from a builder's own claim. Commits: `343973f` (the calculation page, the
methodology editor), `cdabc4a` (the wizard, the 404 page, the roster, the import and add
pages, the diversion page), `094cddc` + `e5d838e` (Site Health; the second is the main
session's own drift-check fix, adding the two peers' captions), `be784e5` (the front pages).
Production `241c22b`, re-read from the host, unchanged.

**R-045 / R-046 / R-047 (the calculation page).** Before, the head read "Methodology: Default
Methodology (a3fee261ef37)" with nothing saying the code was a fingerprint; step 2's Detail
cell read "usda_scs: −0.3168 AF effective precip", printing the config key; step 1's Detail
read "122.07 mm × 109.80 ac" producing 43.9731 AF with no conversion shown, and neither
"inches" nor "÷ 12" appeared anywhere on the page. After (measured live on `/accounting/
calculation-run/11/2026-09/`, parcel 11, period 2026-09): the head reads "Methodology:
Default Methodology" and the code is gone. The plan's first answer printed it as "fingerprint
a3fee261ef37" with a sentence about a 12-character hash; Brent struck that at the checkpoint
(2026-09-16 15:39 PDT: "Nobody knows what that means"), and since no page lets a reader
compare two runs by the code, it is a machine key with no reader use and is not printed
(copy rule 9; `tests/test_calculation_page_words.py::TestCalculationPageDoesNotPrintTheConfigHash`);
step 1's Detail reads "4.8058 in of ET (122.07 mm) × 109.80 ac ÷ 12 in/ft" (4.8058 × 109.80 ÷
12 = 43.9731, the Out cell, the auditor's own check); step 2's Detail reads "USDA-SCS
(TR-21): 0.0346 in effective of 0.1422 in rain, 0.3168 AF taken off"; the string "usda_scs"
appears 0 times in the served HTML. `METHOD_LABELS` (`accounting/precip_math.py`) carries the
three keys, and the methodology editor's rendered `<option>` text equals its values, proven
by `tests/test_calculation_page_words.py::TestOneListOfMethodNames` against a live-rendered
page rather than by inspection.

**R-050 / R-051 (the methodology editor).** Before, the precipitation step showed "Fraction
(method = fraction)" and "Soil storage (in) (method = USDA-SCS)" side by side regardless of
which method was selected, and the clamp step laid Floor, Bank surplus, Depreciation and
Expiry in one grid with no heading. After: only the live method's field renders (the label
suffixes are gone), a plain JS toggle on `select[name=method]` shows the right field before
Save (chosen over an HTMX preview view because it needs no round trip and cannot clobber a
sibling field the reader has already typed into, the same idiom `infrastructure/add.html`
uses for its storage-type sub-fields), and the raw method's grid reads "No settings for this
method."; a `div.form-subsection` headed "Banked surplus" (with the sentence "When the chain
comes out below the floor, the difference is a surplus. These settings say whether it is
carried forward as a credit and how it decays.") now sits between Floor and Bank surplus.
Guards: `tests/test_methodology_editor_fields.py`, each method asserted by reading the exact
opening tag (`data-precip-method="…"`) for a server-rendered `display: none`, never a fixed
character window.

**R-052 / R-054 (the setup wizard).** Before, `GET /setup/confirm/` and `/setup/run/` with no
session 302'd to `/setup/` with no message; `confirm.html` printed `existing_basins|
add:existing_flowlines` under "Existing data" (on the real local demo, boundary 2 "Boundary
0": 1 basin + 0 flowlines = "1"). After, the same redirect renders `.alert-success` "Setup
starts here. Choose or upload a boundary, then confirm it; this session had none." (a deleted
boundary reads "...the boundary this session had chosen no longer exists." instead, proven by
`tests/test_setup_wizard_says_why.py::test_confirm_with_a_deleted_boundary_names_that_it_was_
deleted`); the tile now reads "Already inside this boundary" / "1 basin · 0 flowlines", the
same real boundary, measured live through the wizard's own POST, no sum. A fixture with 2
zones and 3 flowlines renders "2 basins · 3 flowlines", not "5" (`tests/
test_setup_wizard_says_why.py::TestBasinsAndFlowlinesCountApart`).

**R-060 (the not-found page).** Before, local served Django's technical 404 (`DEBUG=True`);
production/staging serve the bare "Not Found" the register read. After, `templates/404.html`
extends `base.html`: signed out and signed in, `@override_settings(DEBUG=False)` gets a 404
whose body holds "Page not found", "Back to Home" and the platform name, and never the
resolver's own exception text. Guard: `tests/test_not_found_page.py`, written by Task 3, 3
tests, each observed red against the pre-change tree before the template existed: RED here
meant the body fell back to Django's bare "Not Found / The requested resource was not found
on this server." The staging probe is Task 7's.

**R-117 (the diversion page).** Before, the description read "Point of diversion details,
diversion records, and compliance information." and the water right sat in a closed
`<details>` at y=2536 of a 2691px page, with "Right ID" not visible at first paint. After, the
description reads "Point of diversion details, diversion records, and the water right it
draws under."; the `<details>`/`<summary>`/chevron are gone and the water right is an ordinary
open `div.card-raised.page-grid-account-full` headed `h2.section-header` "Water right", the
account-info field-grid shape, with no `<details` anywhere inside that card (the sidebar's own
unrelated Help group is also a `<details>` element, so the guard scopes to the card, not the
page). Guards: `tests/test_admin_pages_explain_themselves.py::TestTheDiversionPageOpensThe
WaterRight`.

**R-129 (the add page's parcel link).** Before, `<details class="parcel-link-section">`'s
summary showed "Link to parcel (optional)" with `list-style: none` and no mark, over a 108px
card. After, the summary carries the 14px chevron (`svg.disclosure-mark`, `polyline 9 18 15
12 9 6`) before the words, `details[open] > summary .disclosure-mark { transform:
rotate(90deg) }`, and reads "Link to a use area / Optional. Open to search for a use area,
pick one on the map, or draw one."; "Link to parcel" appears nowhere (`tests/
test_admin_pages_explain_themselves.py::TestTheAddPageUseAreaLinkIsAVisibleDisclosure`).

**R-130 (the import page).** Before, `/infrastructure/import/?type=well` offered no link to
any other import type. After, the same page's description gains "Importing something else?
Surface water diversion · Storage pond or tank · Recharge site", built exactly as `add.html`'s
own "Adding something else?" line is; with only `wells` reachable (surface and recharge both
dropped, the droppability harness's own `without-surface+recharge` combination) the line is
absent rather than dead (`tests/test_admin_pages_explain_themselves.py::
TestTheImportPageOffersTheOtherTypes`).

**R-131 (the roster).** Before, the signed-in user's Actions cell read the whole word "You";
the local demo's second row (`dbg@example.com`, not staff) already carried real buttons, so
the fault reproduced on exactly one of the two local rows (both rows on staging, which holds
one user, read "You"). After, the self row reads "Your account. Another administrator changes
your role or status."; a fixture proves the `is_staff`-but-not-self row reads "Host
administrator; managed outside this page." (the real local demo has no second staff user to
show that cell on, the same "proven by fixture, not by the demo screen" shape 143-12 recorded
for R-093); "You" alone appears in no cell either way (`tests/
test_admin_pages_explain_themselves.py::TestTheRosterWordsItsOwnRow`).

**R-137 / R-138 (the signed-in hero).** Before, `.home-hero-greeting` read "GOOD MORNING"
(11.52px), `.home-hero-title` read "Halvern Valley GSA" (34px, the largest words on the page),
and `.home-hero-status` read "2 of 42 stations reporting" (14px): the register's own original
finding named "10 of 42" and "Good morning" was reproduced in kind, not to the letter. After,
the eyebrow (`.home-hero-greeting`, unchanged class) reads "HALVERN VALLEY GSA", the title
(`.home-hero-title`, still 34px, still the largest words) is a link, `<a href="/datasync/
stations/?reporting=fresh" class="home-hero-title-link">` wrapping the freshness dot and "2 of
42 syncing stations up to date", and "Good morning" / "Good afternoon" / "Good evening" appear
nowhere on the page. Brent at the checkpoint (2026-09-16 15:39 PDT) accepted the figure as
the lead and asked what the hero says for an agency with no monitoring stations: with
datasync on and no syncing station it read "0 of 0 syncing stations up to date", which is not
a figure to lead with, so that case now takes the datasync-off shape (the agency name as the
title, "Home" as the eyebrow, no station link;
`tests/test_front_pages.py::TestTheHeroLeadsWithTheStationFigure::test_no_syncing_station_means_the_agency_leads_not_a_zero`).

**R-138 / R-140 (the anonymous front page).** Before, `.dashboard-grid`s split 4/2/1 cards and
each resolved to 5 columns at 1,730 (not the 4 the register's 1440 capture read), the last
grid holding one wide "System status" card whose dot touched "System running" (`.gap-2`
resolved to no rule, ISS-166); "Monitoring stations 335" carried no syncing count. After, one
`h2.content-section-label` "Your data" over one `div.dashboard-grid.dashboard-grid--counts`
(`grid-template-columns: repeat(auto-fit, minmax(380px, 1fr))` against a 1,439px content width
at 1,730: three columns, measured live) holds all six count cards this deployment allows, in
two rows of three with no empty cell; the stations card's sublabel reads "42 syncing · view
stations" beside its "335" value; `page_meta` carries `span.badge.badge-dot.badge-green`
"System running" in the head, and no `.dashboard-card-wide` or "Methodology settings" card
remains (the latter was dead markup: gated on `request.user.is_staff`, but `config.views.index`
serves this template only to anonymous visitors). Guards: `tests/test_front_pages.py`.

**R-055 (Site Health, the last of its seven pages) / R-056.** Before, `/health/` printed
"7/13 healthy · 13 applicable of 13" at 14px in a `row-end` chip (staging read "8/13", a real
host difference in which checks are currently stale: `ledger_integrity`, `orphans`,
`et_meter_agreement`, `unallocated_delivery` and `ssl` are yellow locally, `sync_freshness`
red); the largest text on the page was 16px, `h2.section-header-flush` on a card title
("Cache Duplication"); 0 of 13 cards carried a link. After (measured live, the real local
demo's actual check rows): `div.page-grid-account` holds the info card ("This run": Last run,
Checks "13: 5 applicable, 8 not applicable", Not applicable, Re-run) beside the balance card's
panel: one `.budget-seg--result` "Healthy 7" at 32px, the largest text on the page, two peers
"Attention needed 5" (`text-deficit`) and "Action required 1" (`text-error`, a color-only
class next to `.text-deficit` since no `.text-error` utility existed before this plan) with
captions "checks reading Warning" / "check reading Critical" (added by the main session's own
drift check, `e5d838e`, after Task 4's first pass shipped the two peers with no caption); both
cards measure 290.6px. Every yellow/red platform-category card carries `a.text-link` to its
page (`sync_freshness` to the monitoring dashboard, `et_meter_agreement` to the water balance,
`ledger_integrity` to the calculated Use Ledger rows, `orphans` to the use areas,
`unallocated_delivery` to the surface diversions: 5 links, all present); the one host-level
red card (`ssl`) reads "Fixed on the host, not in the platform."; no green or skipped card
carries a link; cards order red, yellow, green, skipped (`Sync Freshness` first). Signed out:
no `budget-panel`, the aggregate sentence only. Guards: `tests/test_site_health_page.py` (the
panel, the peers, the ordering, the info card, signed-out); the link-gating mechanism itself
(module-off drops the link even on a yellow row) is `tests/
test_health_checks.py::TestWhereToLookLinksAreModuleGated`, written by Task 4 and not
duplicated here.

**Drift check, main session (143-09-drift-checks.md).** After Task 4: `health-after-1730.png`
opened beside `143-12-work/reporting-reports-shared-supply-check-after-1730.png`. The
`page-grid-account` / `budget-panel` classes matched, both cards 290.6px, but the two peers
carried no `budget-seg-caption` where the accepted shape captions all three segments; fixed in
`e5d838e` ("checks reading Warning" / "check reading Critical", the badges' own words) before
the next dispatch. After Task 5: `home-after-1730.png`, the largest words are "2 of 42
syncing stations up to date" (34px), the eyebrow "HALVERN VALLEY GSA" above, no greeting
anywhere; `index-anon-after-1730.png`, one "Your data" grid, six cards in three columns and
two rows, no empty cell, "System running" green badge-dot beside "Home"; both matched the
plan's verify with no drift.

Guards: 35 new tests across six new files: `tests/test_calculation_page_words.py` (R-045,
R-046, R-047, 7 tests), `tests/test_methodology_editor_fields.py` (R-050, R-051, 5 tests),
`tests/test_setup_wizard_says_why.py` (R-052, R-054, 4 tests), `tests/test_site_health_page.py`
(R-055, R-056, 8 tests), `tests/test_front_pages.py` (R-137, R-138, R-140, 5 tests),
`tests/test_admin_pages_explain_themselves.py` (R-131, R-130, R-129, R-117, 6 tests); plus the
3 tests in `tests/test_not_found_page.py` Task 3 already wrote for R-060 (referenced, not
duplicated). Every new guard observed RED against the pre-change tree (`git checkout ea96977
-- ` the twenty template and view files these six tasks touched, rebuilt, run:
`test_calculation_page_words.py` failed to even COLLECT (`ImportError: cannot import name
'METHOD_LABELS' from 'accounting.precip_math'`, proving the whole file's premise); the other
28 collected tests ran 25 failed / 3 passed, then `git checkout be784e5 -- ` the same files,
rebuilt, all 35 GREEN). The 3 that passed against the pre-change tree are principled, not
weak guards: `TestSignedOutGetsNoPanel` (the anonymous branch's wording was never touched, so
nothing there could regress); `test_no_methodology_settings_card` (the card was dead markup
gated on `is_staff` on a template only `AnonymousUser` ever sees, both before and after);
`test_with_only_wells_the_line_is_absent` (old `infrastructure_import` never built
`other_import_types` at all, so the line's absence held regardless; the discriminating half
of that pair, `test_well_import_page_links_to_the_other_types_not_itself`, was RED). Old
literals grepped across `tests/` before writing the list (`(method = fraction)`, `(method =
USDA-SCS)`, `Existing data`, `Compliance details`, `compliance information`, `Link to
parcel`, `Good morning`, `stations reporting`, `System status`, `System running`, `healthy ·`,
`applicable of`): zero hits except `tests/test_health_checks.py`'s own CLI-summary strings
("... applicable of 13 ..."), which belong to `run_health_checks`' JSON/stdout summary, a
surface this plan does not touch and did not retarget. `tests/test_water_vocabulary.py`,
`tests/test_domain_vocabulary.py`, `tests/test_template_hygiene.py`, `tests/
test_module_template_guards.py`, `tests/test_composition_rule.py`, `tests/
test_figure_ledger_coverage.py` (156 tests, green after the two remaps the plan's own context
names, Task 2's calculation-page sites and Task 3's surface pane), `tests/
test_health_checks.py`, `tests/test_setup_polish.py`, `tests/
test_access_control.py`, `tests/test_platform_readability.py`, `tests/
test_empty_onboarding.py`, `tests/test_methodology_settings.py` all green (459 tests). `make
test-droppable` 30 passed. Suite 2,763 → **2,798**. Staging deploy, the after-probe on both
hosts, the reader verdicts and the seven before/after pairs are Task 7, not this task;
production untouched at `241c22b` (re-read from the host, `ssh` not needed locally since this
task ran no deploy).

Resolved by 143-13 (built 2026-09-16; local stack only, staging deploy and Brent's approval
are Task 5, not this task), closing R-105 and R-106 on all three finders and the workspace
FRAME ruling carried in RESUME.md and STATE.md as "Brent's, open since 143-02" (that line is
the main session's to remove, not this task's). Checkpoint ruling (Brent, 2026-09-16, on the
Task 2 composite): 18:29 PDT, "For the first question - I like A because it matches the rest
of the system."; 18:34 PDT, "Let's go with accounts table." At 18:49 PDT he added a fourth
item, filed as ISS-175 for Phase 144, not touched by this task: "The map of the features owned
by the account seems very useful. If it's useful, lets plan it in somewhere." Mock-up verdicts
(`page-verdict/VERDICTS-2026-09-16.md`, `## 143-13`, two readers, reserve unspent): candidate A
SHIP, FINISH 4, worst fault the 380px map card reading as a shallow letterbox at the page's
1,439px width (Brent's own "keep 380" ruling, 143-07, recorded and not fixed); candidate B DO
NOT SHIP, FINISH 3, worst fault the two columns finishing at visibly different heights, a
property of the rail's own two-card structure this ruling does not carry forward. Before
values from `143-13-probe-before-local.json` / `-staging.json` (Task 1, captured
2026-09-16T16:09 PDT; both hosts served `84139bd`); after values from `143-13-work/
task3-after-measurements.json`, re-run directly against the rebuilt local stack rather than
copied from a builder's own claim. Commits: `2302af9` (Use Areas), `20479d6` (Wells), `4f59ee3`
(Water accounts), `5a06c18` (the workspace shell and its CSS retired), `cd6e915` (the guard
retargets), plus this task's own guard and register commits. No other row in this register
names `workspace.html`, the master-detail rail or the placeholder (grepped; only R-105's own
two occurrences, the master table and this phase's sub-table, both above). Production
`241c22b`, re-read from the host, unchanged.

**R-105 / R-106 (Use Areas, Wells, Water accounts).** Before, on both hosts alike (the rail is
identical CSS regardless of content): the rail was 361px wide; Use Areas held 8 rows wholly in
view at 692px tall, Wells and Water accounts 7 at 676px (the register's own guess of "six" was
already stale on all three); the last row straddled the fold on every page; the toolbar's own
`card-raised.toolbar-stack` was 185px tall, Search stacked over Status, no shared row
(`search_and_status_share_a_row: false`), 26.7% of the Use Areas rail and 27.4% of the other
two; the detail pane was 1,061px wide with the empty state's block covering 34.2% of it empty
below (Use Areas) or 32.7% (Wells, Accounts); the document did not scroll at 1,730×1,000
(`doc_scroll_height` 1000 = `doc_client_height`). After (candidate A, "the list is the page"):
Use Areas renders 1 row wholly in view at first paint and 17 once the reader scrolls past the
458px map card (`map_card_head_text`: "Use areas 79 use areas, all on the map Use area");
Wells renders 0 at first paint and 17 after the scroll (`"Wells 47 wells, all on the map
Well"`); the FIRST-PAINT number fell on both pages (8→1, 7→0) because the map card now leads
the page, the shape Brent chose at the checkpoint knowing that number from the Task 2
composite, not a regression this plan missed. The one-row `card-raised.toolbar-row` is 110px,
11% of the first 1,000px viewport on both pages (Search and Status share one row,
`search_and_status_share_a_row: true`); the document now scrolls (Use Areas 2,159px, Wells
2,175px tall, both at 79/47 total rows respectively). A search for "Brayfield" narrows Use
Areas to "3 of 79 match "Brayfield"; the map shows those 3" with exactly 3 features drawn (pks
6, 47, 62), proving the map still follows the list under the new shape (rule 19). Water
accounts took the "accounts-table" ruling instead of the Bucket-3 map-card shape: no map
card (accounts carry no geometry of their own; a per-account map is ISS-175), the dashboard's
own Active water accounts table shared through `_active_accounts_table.html` with Search and
the Period control on one `toolbar-row`; 8 of 11 rows wholly in view at first paint (accounts
carry no paging: all rows render, as the dashboard does), the full page 1,243px tall. The
workspace shell (`templates/workspace.html`, its three `_detail_empty.html` partials, and the
`.workspace-split` / `.master-*` / `.pane-empty*` / `.toolbar-stack` CSS and the
`.app-main:has(.workspace-split)` viewport pin) is deleted: no page on the platform extends it
any more (grepped before the delete, per ISS-089/091's droppability gate).

Closed on staging 2026-09-16: deployed `4aaf925` then `1220759`, served commit read off the
host; the after-probe on staging matched local on every layout value (Use Areas 1 row at first
paint and 21 with the table at the top, Wells 0 and 21, Accounts 8 of 11; toolbar 110px one
row on all three; no old class in any body; "Brayfield" narrows Use Areas to 3 of 76 with 3
features drawn). One checkpoint fix (`1220759`): the Wells search reached name and
registration id only and now reaches the Owner column too, its placeholder saying so, the
guard seen red first. Brent approved 21:14 PDT on staging `1220759`; production untouched at
`241c22b`. Readers 5 of 5: mock-up A SHIP 4, mock-up B DO NOT SHIP 3, the three built-page
reads DO NOT SHIP (3, 4, 3), each naming the 380px full-width map card that leaves the
table's first row at the fold, the shape he chose from the composite; "keep 380" stands.

## Phase 144: The words and the way in

Prose, the wording of descriptions and names, and the sidebar. Independent of 141-143. **35 rows.**

| rank | id | page | finding |
|---|---|---|---|
| 8 | R-028 | 26 pages (c2 …) | On 26 of the platform's 68 signed-in pages no sidebar entry lights at all, so the reader has no way to say from the sidebar where they are or get back: every accounting page but the dashboard and the ledger (the entry match misses their routes), the setup and health pages, the water-rights, infrastructure, users and profile pages (which have no sidebar entry to light), two Help pages the Help group has no entry for, and the demonstration-data page (About lights only on /about/). |
| 9 | R-145 | 8 pages (c59 …) | The sidebar's Help group opens by itself on every Help page and on About, and the six entries it adds push its own last three (Configs Explained, Glossary, About) and the Operations/Admin toggle below the bottom edge of the sidebar at a 1440 × 900 window, so on the Glossary, Configs and About pages the entry that is lit is off the screen and the reader has nothing telling them where they are. |
| 12 | R-097 | c40, c44, c45, c49 | The platform prints two names for one thing on the same screen: the description and the sidebar say 'use areas', the map's Layers panel says 'Parcels', and on the Use Areas list the same rows are counted as '76 parcels found' under the heading '76 USE AREAS IN THIS DISTRICT', so a reader cannot say whether a parcel and a use area are the same record. (ISS-161's class: one name per thing.) |
| 14 | R-086 | c34, c35, c36, c39 | The report page states four separate times, in four stacked panels, that OpenH2O does not submit to the state (the red demonstration notice, the 'OpenH2O prepares your filing' card, the handoff alert and the internal-status note) before the reader reaches a single figure. (Template only for the report page itself, which answered 404.) |
| 15 | R-012 | c1 | The crumb reads 'Accounting / Dashboard' but the sidebar has no section called Accounting; the lit entry sits in an unlabelled group with Home and Map, so a reader looking for Accounting in the sidebar cannot find it. |
| 25 | R-014 | c10, c11 | Four sentences across two screens give four conventions for the same numbers: the ledger's description says positive amounts are supply, its inset says the running balance is allocation minus usage, its footer says credits are paper and never netted, and the New Entry form says positive amounts 'represent supply (recharge, allocation)', a flat contradiction of the footer. The reader is left to reconcile them. |
| 29 | R-006 | c1 | The inset 'How this summary works' states the relation the table beneath it does not show (three supplies meet consumptive use), in prose between the panel and the table, belonging to neither; once R-007 is fixed this sentence is either redundant or the caption. |

R-006 was taken by 142-01 (2026-09-08): the inset is deleted, and its two claims live in the panel's segment captions and the tables' group headers. Nothing remains for Phase 144 on this row.

| 35 | R-104 | c43 | The zone's year-end setting calls the zone 'this district' and describes its unused surface-water allotment, while the head calls the same thing a Management Area and the only table on the page shows groundwater, so a reader cannot say what the setting acts on. |
| 38 | R-109 | c45 | The same 330.37 AF appears twice within a hand's width on the use-area page, once as the Residual marked Deficit and once as 'Water use recorded, no supply reported', and nothing says the two are one quantity, so a reader may read the shortfall as counted twice. (A reading finding, not ISS-158's data question: the arithmetic is right and the screen is what misleads.) |
| 43 | R-127 | c53 | The recharge basin's Site information card says the basin is filled by a canal intake while every row of Event history is labelled Water type 'Groundwater', and nothing on the page says which sense of the phrase is meant, so a reader cannot say where the water in those events came from. |
| 51 | R-139 | c69 | The anonymous front page has no title and no crumb, and its one line of description tells a signed-out visitor 'Overview of your water data. Each card counts one kind of record and links to where you manage it', when the visitor owns none of it and every 'View all …' link and every sidebar entry answers with a login form. |
| 53 | R-044 | c11 | The sentence that tells the reader what a positive or negative amount means sits below the Create button, well under the Amount box it governs, so the reader types the figure before meeting the rule for its sign. |
| 54 | R-048 | c14 | Delivery Settings says the settings are 'Set once for the whole agency' and the panel under it says 'a single district can differ from the default', so the reader cannot say what the page governs, and 'district' means the whole agency on the Accounts page ('11 accounts in this district'). |
| 56 | R-065 | c22 | The first panel on the facility page is four lines explaining why there is no map, above the record the page is about, so the first thing a reader reads is about something the screen does not show. |
| 63 | R-133 | c59 | Getting Started's Setup Wizard card says the wizard does 'Steps 2, 3, 9, and 10', but Step 10 is headed 'Add surface diversions and recharge areas' and its own eyebrow says only 'the Setup Wizard imports recharge basins for you', so the reader cannot say whether the wizard did the surface-diversion half of that step or left it for them. |
| 64 | R-134 | c60 | Fourteen glossary definitions end by pointing at a Help page by a name the platform does not use anywhere the reader can click: 'See Help > Allocations & Ceilings' and 'See Help > Surface Delivery Settings' name pages the Help menu has no entry for, and 'See Help > How Water Balances Work' and 'See Help > Configs & Settings, explained' name pages whose menu entries read 'Water Balance Info' and 'Configs Explained'. |
| 66 | R-013 | c1 | Under Drinking Water an entry reads 'Onboard System', a software verb a layperson cannot place; nothing nearby says it is where a system's records are first loaded. |
| 69 | R-026 | 9 pages (c1 …) | Nine pages each carry a sentence that explains the water to the engineer who reads it (copy rule 11): the dashboard inset says crop demand 'is met by three supplies'; Water Years says 'Most agencies use the water year (October through September)'; Delivery Settings says 'The rest soaks back into the aquifer. Typical: 75%'; the glossary defines Effective Precipitation and converts CFS to acre-feet per day; Allocations & Ceilings defines the acre-foot; Surface Delivery Settings says 'A crop drinks part of the water; the rest sinks past the roots and recharges the aquifer'; Water Balances says 'it's how irrigation actually behaves'; Methods says 'Rain that actually soaked in and was available to the crop'; Configs says 'the rest sinks past the roots and recharges the aquifer, typically around 75%'. |
| 72 | R-029 | c2, c3, c4, c5, c6, c7 | One record type carries a different name in the crumb, the count line, the button, the back link and the form heading, so a reader cannot say whether a 'water year', a 'period', a 'reporting period' and a 'new water year' are one thing or four; the accounts pages do the same with 'Accounts', 'Water Accounts' and 'water account'. |
| 76 | R-053 | c16, c17, c18 | The setup wizard gives its own steps different names in different places (step 2 is 'Confirm' in the step bar and 'Confirm Boundary' in the crumb; step 3 is 'Populate', 'Running', 'Running Setup' and 'Population progress'), so a reader cannot say whether they are on the step the bar is pointing at. |
| 77 | R-059 | c24, c25, c26 | Wherever a lab finding is shown it can read '< 0.5 UG/L', and nothing on any of those pages says the '<' means the laboratory could not measure below that level rather than that the value is 0.5. |
| 78 | R-098 | c41, c42, c43 | On the zone pages the sidebar lights 'Map' while the page head reads 'Administration / Zones', because the Zones entry itself sits on the sidebar's other tab (Admin), so the lit entry and the page's own name are different words. (ISS-133 as it renders today: the two-entries-lit fault is masked by the tab, not fixed.) |
| 80 | R-146 | c63, c64, c65 | Three of the Help group's entries carry a different name from the page they open ('Water Balance Info' opens 'How Water Balances Work', 'Methods' opens 'Methods Behind the Numbers', 'Configs Explained' opens 'Configs & Settings, explained'), and the glossary's own cross-references use the page names, not the menu names. |
| 81 | R-072 | c28, c29 | The lit sidebar entry on both onboarding pages reads 'Onboard System' while the page heads read 'Onboard' and 'Sampling Points', so the sidebar's name for the page never matches the page's own (and on the second, the entry called 'Sampling Points' is not the one lit). |
| 82 | R-099 | c41, c42 | The Zones table's Type column labels five of the eight rows 'Custom' and three 'Management Area', and nothing on the page (or on the create form that offers the same choices) says what the platform does differently with each, so a reader cannot say what kind of thing a Custom zone is. |
| 87 | R-128 | c54, c55 | The infrastructure pages' crumb begins 'Extraction Wells', a name that appears nowhere else in the platform (the sidebar, the list page and its crumb all say 'Wells'), so a reader cannot tell that the section they are in is the one the sidebar calls Wells; the crumb word and the back link do lead there. |
| 105 | R-116 | c49 | The form under the diversion table asks for 'Volume (AF)' while the table's own column for the same quantity is 'Diverted (AF)', so a reader adding a record cannot say which column their number will land in. |
| 106 | R-120 | c51 | The water right's diversion table heads a column 'POD', an abbreviation the page never expands although its own description spells out 'points of diversion' two lines above, so a reader cannot say what the column holds. |
| 122 | R-119 | c50 | 'Face value' heads the biggest number on the water-rights list with nothing saying what it is (the detail page explains it behind a '?', the list does not), so a reader outside the trade cannot say what the largest figure in the table measures. |
| 124 | R-049 | c15 | Every methodology step prints its name twice in its own heading, 'Gross ET (OpenET ensemble) (Gross ET)', and a third time inside the Label box beneath, and nothing says what the bracketed one is or which of the three the platform uses. |
| 127 | R-057 | c19 | A Site Health card reads '1 parcel-period(s) fall outside that range', printing a machine plural and disagreeing with its own verb, so the reader cannot say whether one thing or several are wrong. |
| 138 | R-092 | c38 | Nothing on the CalWATRS worksheet says how many blocks it holds or where the reader is in it, so an operator typing point after point into the state's portal cannot tell how much is left. (Template only.) |
| 141 | R-113 | c47 | The well page names GEARS, DWR, WCR, the State Well Number and CASGEM and explains none of them, while the one field that is explained is the platform's own Registration ID, so a reader cannot say which agency or programme any of those identifiers belongs to. |
| 145 | R-135 | c66 | About's one narrative section is titled 'Standing on the Groundwater Accounting Platform' and spends four paragraphs on another platform's merits ('proved something that was far from obvious when it started', 'raised the bar for every tool in the field', 'indebted to GAP's example and glad to keep learning from the people who built it'), so a reader who came to find out what OpenH2O does learns it only from the one card above, and nothing after that adds to the answer. |
| 146 | R-136 | c67 | In the two prose cards on the demonstration-data page the paragraphs run together with no gap (the space between two paragraphs equals the space between two lines of one), so 'The short version' reads as a single nine-line block and the reader cannot see that it is making three separate points. |

## Issues absorbed or declined

| issue | what it named | register |
|---|---|---|
| ISS-159 #1 | Nothing shows Surface + Groundwater + Precip is Supplies; Net is a balance; GW columns are another framework | R-007 |
| ISS-159 #2 | Dead space, gigantic figures; 'Supply vs. use' does not say what the panel is | R-003, R-004 |
| ISS-159 #3 | Plain scroll zooms the map | shipped in Phase 138; not a finding |
| ISS-159 #4 | The ledger's oversized quick-filter panel; why the columns are in that order | R-016, R-018 |
| ISS-159 #5 | Import / Add on their own line under the description | R-021 (now 7 pages) |
| ISS-162 | Every text utility on a table cell is discarded | R-025 (36 templates); the same class of fault outside tables is R-141, R-143 |
| ISS-163 | Zone rows not clickable | R-009 |
| ISS-023 | Methodology settings page off the design system | closed 2026-06-01; not a reading finding. What the page fails today is R-049, R-050, R-051 |
| ISS-022 | Calculation audit pages unreachable; ledger defaults to an empty period | closed 2026-06-01; not a reading finding. The ledger opens on a period today; that the result line does not say which is R-042 |
| ISS-110 part 2 | The trend column says 'No data' when it means too few points | R-075 (renders as '--' today) |
| ISS-136 | Filtering the list leaves the map alone | R-023 (four overview maps), R-074 (stations, visible on first load); `/drinking/facilities/` passes under Brent's ruling |
| ISS-161 | 'Allocation' names two quantities on two screens | not directly visible on one capture; its class is R-097 (use area / parcel) and R-029 (water year / period). Stays open as a naming issue |
| ISS-133 | `/map/zones/` lights two sidebar entries | R-098: does not reproduce because the Zones entry is on the hidden Admin tab; the source still has no exclusion, so it is masked, not fixed |
| ISS-143 | 'Surplus' reads as good news | `decided: keep` (Brent, 2026-09-06); the badge reads Balanced / Residual / Deficit |
| ISS-164 (new) | The Allocations footer adds one entitlement across two water years | R-041 |
| ISS-165 (new) | The use-area page's ledger card ignores the selected period | R-107 |

## Rejected by the adjudicator

| proposed | page | what the reader saw | why the standard declines it |
|---|---|---|---|
| B-37 | c36 | The report page paints the same status two colours in two places (pane header vs Internal status card). | A consistency finding: the standard's Part 1 excludes 'do surfaces match each other'; the status word itself reads on both. |
| C-29 | c50 | Face values print as 120000, 60000 with no thousands separator. | A number-format sweep item that DESIGN.md's formatting rules own (ISS-142's class, Phase 138's kind of work); the column still reads. |
| C-44 | c56 | The demonstration banner renders above the Users, Add User and Profile pages, over the reader's own real account. | The banner describes the deployment, not the screen, and says so ('This demo mixes…'); a demo deployment's own admin account is part of the demo, so the reader is not misled. |

## Declined at the edge of the standard

- c20: the three counts appear twice (tiles, then step-card eyebrows) — the eyebrow is a state marker ('done') carrying its evidence.
- c25: the results log pages 448 times with only Previous/Next — the filter is the way to a row; R-017 already files a jump control as a fault.
- c26: 'Result 7.4 MG/L' and 'Unit MG/L' print the unit twice — fidelity to the state's own record, where unit is its own column.
- c32: five panels each say there is nothing here in five wordings — five honest empty states, as the page pass ruled.
- c30/c33: whether the shared freshness map should follow the page's default filter is a product ruling of the kind Brent made for /drinking/facilities/, not a reading finding; R-074 files only what the reader sees on first load.
- c16: two gold buttons on one screen ('Use this boundary', 'Upload & continue') — genuine alternatives, and the divider says so.
- c40: the crumb reads 'Water Data / Map' while the Map entry sits in the sidebar's unlabelled top group — the entry's name matches the crumb exactly.
- c41/c48/c52: count columns repeat their unit in every cell — harmless redundancy.
- c53: the field notes under each measurement explain basin behaviour — they are the operator's own data (ISS-146 asked for them), not platform copy.
- c59-c65: the head sits flush left while the cards start further in — a layout choice no question in Part 2 names.
- c70-c79: six account titles are gold and four are teal — a colour, which the standard does not judge.
- c68/c69: the anonymous front page shows a management nav a visitor cannot open — a product question (shop window or login wall); the description half of it is R-139.
- Form fields are not one of the seven surfaces; four faults recorded for the record: required dropdowns read '---------' (c9, c11); the Parcel dropdown lists 76 parcels in no order (c11); 'Transaction date' and 'Effective date' sit together with nothing saying which the ledger sorts on (c11); the ledger upload defaults to 'No period (unassigned)' (c12).
- Not reading findings, handed on: the well page prints identical Delta figures for the matching months of both water years (c47) — a data question for the next seed check; the page-pass row for c19 /health/ is stale (13 categories render, two Critical; it records zero) — a docs/page-pass-2026-09.md correction.

