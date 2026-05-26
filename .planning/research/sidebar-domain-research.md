# Sidebar Domain Research: What Every Page Does

**Date:** 2026-05-25
**Purpose:** Map every sidebar link in OpenH2O to what it actually does, what questions it answers for a GSA manager, and how the pages relate to each other in a water district workflow.

**Method:** Code analysis of all 12 Django apps (models, views, urls, templates) cross-referenced with Perplexity research on California GSA workflows, GEARS/CalWATRS reporting, water budgets, managed aquifer recharge, monitoring stations, and water rights.

---

## Sidebar Structure (as built)

The sidebar has 6 sections: Primary (no label), Data, Reporting, System, Setup, and Help.

---

## Page-by-Page Analysis

### 1. Dashboard
- **Sidebar section:** Primary (top)
- **Route:** `/accounting/dashboard/`
- **Current name:** Dashboard

**What the page actually does:**
Shows the water budget summary for a selected reporting period. Three stat cards at top: Total Supply (acre-feet), Total Usage (acre-feet), Net Balance (acre-feet). Below that, two tables: one showing every active water account (with supply, usage, net, allocation, and remaining columns), and one showing every geographic zone (same columns). A period dropdown lets the user switch between reporting periods (typically water years). If no periods exist, shows an onboarding wizard with 4 steps.

**What question it answers for a GSA manager:**
"How is my basin doing this water year? Are we pumping more than our allocation? Which accounts are over-budget? Which zones are in deficit?" This is the single most important screen -- it is the water budget scorecard that a GSA board member or manager checks to know whether the district is on track for SGMA sustainability.

**How it connects to other pages:**
- Reads from: ParcelLedger (all transactions), AllocationPlan (budgets per zone), WaterAccount and WaterAccountParcel (groupings), ReportingPeriod (time windows)
- Links to: Account detail pages, period creation
- Fed by: Ledger entries (manual, CSV import, or from external data sync)

---

### 2. Map
- **Sidebar section:** Primary
- **Route:** `/map/`
- **Current name:** Map

**What the page actually does:**
Full-screen interactive MapLibre GL JS map with multiple layers: GSA boundary outline, management zones, parcel polygons, well points, points of diversion, recharge sites, monitoring stations (color-coded by data freshness), NHD flowlines (streams/rivers), and tie lines connecting wells/PODs to parcel centroids (showing which water source serves which land). The map auto-centers on the GSA boundary if one exists. Each layer can be toggled. Clicking features shows popups with details and links to detail pages.

**What question it answers for a GSA manager:**
"Where is everything in my district? Which wells serve which parcels? Where are my diversion points relative to streams? Where are my monitoring stations and are they reporting current data? What does my recharge infrastructure look like spatially?" This is the geographic command center -- every piece of physical infrastructure and data plotted on one map.

**How it connects to other pages:**
- Pulls GeoJSON from: parcels, wells, surface/PODs, recharge sites, stations, boundaries, zones, flowlines, tie lines
- Clicking features links to: parcel detail, well detail, station detail, etc.
- Does not write data -- pure visualization

---

### 3. Ledger
- **Sidebar section:** Data
- **Route:** `/accounting/ledger/`
- **Current name:** Ledger

**What the page actually does:**
Paginated list of every ParcelLedger transaction in the system. Each row shows: parcel number, effective date, amount in acre-feet (positive = supply/credit, negative = usage/debit), source type (meter reading, ET estimate, manual entry, CSV import, surface diversion, recharge, allocation, adjustment), water type, reporting period, and description. Filters for: text search, reporting period, source type, water type, date range. Actions: create single entry, upload CSV (bulk import with dry-run preview), download CSV template, export filtered entries as CSV.

**What question it answers for a GSA manager:**
"What are all the water transactions recorded for my district? How much was pumped from each parcel? What are the supply credits? Can I find a specific entry or filter to a specific period?" This is the transaction log -- the raw double-entry data that feeds the dashboard budget calculations. Think of it as the bank statement for water.

**How it connects to other pages:**
- Each entry links to a parcel
- Entries are tagged to reporting periods and water types
- Dashboard budget numbers are computed from ledger totals
- CSV upload is the primary bulk data entry path
- GEARS and CalWATRS reports are generated from ledger data

**Domain context:**
In GSA practice, ledger entries come from: (1) well meter readings, (2) satellite ET estimates from OpenET, (3) surface water diversion records, (4) managed recharge events credited back, (5) manual adjustments. The positive/negative convention mirrors how GSAs think: supply is a deposit, pumping is a withdrawal.

---

### 4. Parcels
- **Sidebar section:** Data
- **Route:** `/parcels/`
- **Current name:** Parcels

**What the page actually does:**
Paginated list of all parcels (land plots) in the system. Each row shows: APN (Assessor Parcel Number), owner name, area in acres, status, and zone memberships. Search by APN or owner name. Filter by status (active/inactive/pending). Detail page for each parcel shows: all editable fields (inline edit via HTMX), zone memberships, related wells (which wells irrigate this parcel), recent ledger entries, and a map showing the parcel polygon.

**What question it answers for a GSA manager:**
"What parcels are in my district? Who owns parcel X? How big is it? Which wells pump water to it? What is its water transaction history?" Parcels are the fundamental unit of water accounting -- every water transaction is recorded against a parcel. In California, parcels are identified by APNs from county assessor records.

**How it connects to other pages:**
- Parcels are linked to: water accounts (via WaterAccountParcel), wells (via WellIrrigatedParcel), water rights (via WaterRightParcel), PODs (via PointOfDiversionParcel), zones (via ParcelZone)
- Ledger entries are recorded per parcel
- GEARS reports aggregate parcel-level data
- Auto-populated from DWR LightBox statewide parcel data via setup wizard

---

### 5. Wells
- **Sidebar section:** Data
- **Route:** `/wells/`
- **Current name:** Wells

**What the page actually does:**
Paginated list of all groundwater wells. Each row shows: name, well registration ID, type (production, monitoring, domestic, etc.), depth, capacity (GPM), status, and owner. Search by name or registration ID. Filter by status. Detail page shows: all editable fields, current meters attached, irrigated parcels (which parcels this well serves), monitoring well metadata if applicable, and a map showing the well location.

**What question it answers for a GSA manager:**
"What wells are in my district? What is the capacity and depth of well X? Which parcels does it irrigate? Is it metered? Is it a monitoring well?" Wells are the physical infrastructure that extracts groundwater. GEARS reporting requires per-well extraction data. The well-to-parcel linkage (WellIrrigatedParcel with fraction) is critical for allocating pumping to the right parcels.

**How it connects to other pages:**
- Wells link to parcels via WellIrrigatedParcel (with fraction -- one well can serve multiple parcels)
- Wells can have meters attached (WellMeter)
- Wells appear on the Map page
- Well data feeds GEARS reports (per-well extraction)
- Monitoring wells have extra metadata (agency, frequency, reference elevation)
- Tie lines on the map connect wells to their irrigated parcel centroids

---

### 6. Surface Water
- **Sidebar section:** Data
- **Route:** `/surface/`
- **Current name:** Surface Water

**What the page actually does:**
Paginated list of all water rights. Each row shows: right ID, type (appropriative, pre-1914, riparian, etc.), holder name, priority date, face value (acre-feet), status, and source stream. Search by right ID or holder name. Filter by status (active/inactive/curtailed/revoked). Detail page shows: right details, all points of diversion under this right (with map), recent diversion records (monthly volumes), and any active curtailment orders that affect this right based on priority date.

**What question it answers for a GSA manager:**
"What surface water rights does my district hold or manage? Where are our points of diversion? How much have we diverted this year? Are any of our rights curtailed?" Surface water is the other half of a GSA's water portfolio (besides groundwater). Water rights define how much surface water can legally be diverted, from where, and for what purpose. CalWATRS reporting requires this data.

**How it connects to other pages:**
- Water rights have points of diversion (PODs) with locations on the map
- PODs link to parcels via PointOfDiversionParcel (with fraction)
- Diversion records create ledger entries (surface_diversion source type)
- CalWATRS reports are generated from water right and diversion data
- Curtailment orders may restrict diversions based on priority date
- Tie lines on the map connect PODs to parcel centroids (yellow lines)

**Domain context:**
In California, a water right authorizes diversion from a specific point (POD) for use on specific land (place of use). The State Water Board tracks this through CalWATRS (formerly eWRIMS). A GSA that holds surface water rights must report diversions annually. Curtailment orders during drought can shut off junior rights.

---

### 7. Recharge
- **Sidebar section:** Data
- **Route:** `/recharge/`
- **Current name:** Recharge

**What the page actually does:**
Paginated list of all managed aquifer recharge (MAR) sites. Each row shows: name, site type (spreading basin, injection well, streambed, ASR well, storage pond, storage tank), capacity (acre-feet), status, and operator. Search by name. Filter by type. Detail page shows: site details, recharge events (date range, volume in acre-feet, water type, source description), recent measurements (water level, flow rate, water quality, infiltration rate), zone assignment, and a map showing the site location or polygon.

**What question it answers for a GSA manager:**
"Where are our recharge facilities? How much water have we recharged this year at each site? What is the capacity of our spreading basins? What measurements are we collecting?" Recharge is how a GSA puts water back into the ground. Under SGMA, recharge projects are a primary tool for achieving sustainability -- they offset pumping in the water budget. Tracking recharge volumes is essential for water budget calculations and for demonstrating progress in GSP annual reports.

**How it connects to other pages:**
- Recharge events create positive ledger entries (recharge source type) that show as supply on the dashboard
- Recharge sites can be assigned to zones
- Sites appear on the Map page
- Recharge volumes feed into the water budget calculations on the dashboard
- MAR data may be included in state reporting

**Domain context:**
MAR is a cornerstone of SGMA compliance. GSAs track recharge by event (where, when, how much, from what source). Recharge credits in the water budget offset pumping withdrawals. Most California MAR is done through spreading basins, but injection wells and ASR wells are used in confined aquifer or space-limited settings.

---

### 8. Stations
- **Sidebar section:** Data
- **Route:** `/datasync/stations/`
- **Current name:** Stations

**What the page actually does:**
Combined monitoring station list and status dashboard. Top section shows: summary stat cards (total active stations, fresh/stale counts), data source status (CDEC, USGS, CIMIS, OpenET, CNRFC, DWR -- each showing station count, last sync time, sync status), and OpenET API budget usage. Below that: a paginated table of all stations with sparkline charts (last 10 data points), freshness indicators (green = data within 24h, yellow = within 7 days, red = older), data source, external ID, and active/inactive toggle. Search by name or ID. Filter by source and active status. Stations are scoped to the GSA boundary. Detail page shows: station metadata, recent data records, sync logs, and a map. Users can add custom stations.

**What question it answers for a GSA manager:**
"Are my monitoring stations reporting data? Which ones are stale or dead? How is each external data source performing? Am I within my OpenET API budget? What does the latest data from station X look like?" This is the monitoring command center. GSA managers need to know that data is flowing from external sources (stream gauges, weather stations, groundwater level loggers) so they can trust their water budget numbers.

**How it connects to other pages:**
- Stations pull data from 8 external adapters (CDEC, USGS, OpenET, CIMIS, CNRFC, DWR WDL, DWR SGMA, NOAA)
- Data feeds into the staging pipeline (DataRecordStaging) which can be published to ledger entries
- Stations appear on the Map page with freshness color-coding
- Station data feeds water budget calculations indirectly (through published data)
- Health checks monitor sync freshness

**Domain context:**
GSAs typically track: groundwater levels (from monitoring wells, often USGS or DWR), stream flows (CDEC/USGS gauges), weather and reference ET (CIMIS), and satellite-based actual ET (OpenET). This monitoring data feeds the water budget, validates model predictions, and is required for GSP annual reports and 5-year evaluations.

---

### 9. Infrastructure
- **Sidebar section:** Data
- **Route:** `/infrastructure/`
- **Current name:** Infrastructure

**What the page actually does:**
Unified list of all physical water infrastructure: wells, standalone points of diversion (not attached to a water right), and recharge sites. Shows type, name, and creation date. Search across all types. The "Add Infrastructure" page provides a single form with a type selector (well, diversion point, recharge site, storage facility) that shows type-specific fields. Two data entry paths: (1) plot a point or draw a polygon on an interactive map, or (2) upload a GeoJSON, Shapefile, or KML file. Each feature can be linked to a parcel (search existing, or draw a new parcel polygon inline).

**What question it answers for a GSA manager:**
"How do I add a new well, diversion point, or recharge site to the system? How do I upload a shapefile of my infrastructure? How do I link infrastructure to the parcels it serves?" This is the manual data entry point for physical infrastructure that is not in public datasets and was not auto-populated by the setup wizard.

**How it connects to other pages:**
- Creates new: Wells (redirect to well detail), PointOfDiversion records, RechargeSite records
- Links infrastructure to parcels (WellIrrigatedParcel, PointOfDiversionParcel)
- Uploaded features appear on the Map page
- Created records flow into the Wells, Surface Water, and Recharge pages

---

### 10. Reports
- **Sidebar section:** Reporting
- **Route:** `/reporting/reports/`
- **Current name:** Reports

**What the page actually does:**
Two hero cards at top: GEARS (Groundwater Extraction Annual Report, gold accent) and CalWATRS (California Water Transfer Reporting System, blue accent). Each card shows a description, count of generated reports, and a "Generate Report" button that pre-filters to that report type. Below: a report history table showing all generated submissions with status (draft/reviewed/submitted/accepted/rejected), template type, reporting period, and dates. Report generation flow: select template (GEARS by Well, GEARS by ET, CalWATRS A1, CalWATRS A2, or Email JSON) and reporting period, validate data completeness (warnings/errors), generate CSV file, save as a ReportSubmission. Reports follow a draft > reviewed > submitted workflow with state transitions.

**What question it answers for a GSA manager:**
"Am I ready to file my GEARS report with DWR? Have I generated my CalWATRS submission for the Water Board? What is the status of each report -- has it been reviewed and submitted? Are there data gaps I need to fix before filing?" These are the state compliance reports that every GSA must file. GEARS covers groundwater extraction (per-well pumping volumes, due around May 1). CalWATRS covers surface water diversions (due January 31).

**How it connects to other pages:**
- GEARS reports pull from: wells, parcels, ledger entries (meter readings and ET estimates), reporting periods
- CalWATRS reports pull from: water rights, points of diversion, diversion records
- Report validation checks data completeness across the system
- Generated CSV files can be downloaded and uploaded to the state's GEARS or CalWATRS portals
- Email JSON format provides an alternative submission path via Power Automate

**Domain context:**
GEARS is filed to DWR for groundwater extraction in state-regulated basins. It requires per-well extraction volumes. CalWATRS is filed to the State Water Board for surface water diversions. It requires monthly diversion volumes per point of diversion. Both have specific CSV formats. These reports are the primary compliance obligation for GSAs under SGMA and the Water Code.

---

### 11. Health
- **Sidebar section:** System
- **Route:** `/health/`
- **Current name:** Health

**What the page actually does:**
System health dashboard showing 8 automated checks, each with a green/yellow/red status: Database connectivity, Disk space, Sync freshness (are external data feeds current), Ledger integrity (accounting consistency), Orphans (records without required links), SSL certificate status, Docker container health, and Migration status (are all database migrations applied). Shows overall system status (healthy/degraded/unhealthy) and last check time. Also exposes a public JSON API endpoint at `/health/api/` for external monitoring tools like Uptime Kuma.

**What question it answers for a GSA manager:**
"Is the system working? Are there any technical problems I should know about?" For a non-technical manager, this is a simple "is it green?" check. For an AI operator or technical admin, the details help diagnose issues. The sync freshness check is particularly relevant -- it tells you whether external data feeds (CDEC, USGS, etc.) are current.

**How it connects to other pages:**
- Checks reference: database state, data sync logs (sync freshness), ledger records (integrity), foreign key relationships (orphans)
- Results are stored in HealthCheckResult model
- Public API endpoint for external monitoring
- Cron job runs health checks on schedule

---

### 12. Setup Wizard
- **Sidebar section:** System
- **Route:** `/setup/`
- **Current name:** Setup Wizard

**What the page actually does:**
3-step guided setup for new GSA deployments. Step 1: Select an existing boundary (GSA boundary polygon) or upload a GeoJSON file of the boundary. Step 2: Review the boundary on a map and confirm. Step 3: Auto-populate runs, executing 4 steps sequentially via HTMX polling: (1) fetch DWR Bulletin 118 groundwater basins that intersect the boundary, (2) fetch parcels from the DWR LightBox statewide parcel database, (3) fetch USGS 3DHP flowlines (streams/rivers), (4) discover monitoring stations from CDEC, USGS, and CIMIS within the boundary. Each step shows progress, record count, and any errors.

**What question it answers for a GSA manager:**
"How do I get started? I have my GSA boundary -- now what?" The wizard is the first-run experience. A new GSA uploads their boundary (or selects a DWR-defined one), and the system automatically populates the district with publicly available data: parcels from county records, groundwater basins, stream networks, and monitoring stations. This replaces weeks of manual data gathering.

**How it connects to other pages:**
- Creates: Boundary, Zone (basins), Parcel records, Flowline records, MonitoredStation records
- After setup: Parcels page is populated, Map page shows all layers, Stations page shows discovered stations
- The boundary is used to scope station queries and map centering throughout the app
- Subsequent manual entry (Infrastructure page) adds features not in public datasets

---

### 13. Accounts
- **Sidebar section:** Setup
- **Route:** `/accounting/accounts/`
- **Current name:** Accounts

**What the page actually does:**
Paginated list of water accounts. Each row shows: account number, name, status (active/inactive/suspended), parcel count, and contact info. Search by account number or name. Filter by status. Detail page shows: account metadata, assigned parcels (with add/remove), period selector, and a per-parcel balance breakdown showing supply, usage, and net for each assigned parcel within the selected reporting period. The account-level balance aggregates all parcel balances.

**What question it answers for a GSA manager:**
"Who are my water users? How many parcels does each account have? What is this account's water balance -- are they within their allocation?" Water accounts group parcels under a single water user (a farmer, a city, a mutual water company). This is how GSAs track individual users' water budgets. The account is the entity that gets billed, receives allocations, and is held accountable for over-pumping.

**How it connects to other pages:**
- Accounts link to parcels via WaterAccountParcel (many-to-many with time tracking)
- Account balances are computed from ParcelLedger entries on assigned parcels
- Account summaries appear on the Dashboard
- Allocations are applied per zone, which connects to parcels via ParcelZone

**Domain context:**
In GSA practice, a "water account" is like a bank account for water. Landowners are assigned accounts, their parcels are linked, and the account tracks: allocation (how much they can pump), actual use (metered or ET-estimated), and balance (remaining allocation). Some GSAs allow water trading between accounts.

---

### 14. Periods
- **Sidebar section:** Setup
- **Route:** `/accounting/reporting-periods/`
- **Current name:** Periods

**What the page actually does:**
Paginated list of reporting periods. Each row shows: name, start date, end date, and finalized status. Detail page shows: period metadata, allocation plans assigned to this period, count of ledger entries in this period, and a finalize/unfinalize toggle. Finalization locks the period (records who finalized and when).

**What question it answers for a GSA manager:**
"What time windows am I accounting for? Has this water year been finalized (closed)? How many transactions are in this period?" Reporting periods define the time boundaries for water accounting. Most GSAs use the California water year (October 1 to September 30). Finalizing a period is like closing the books -- it signals that the data is complete and ready for reporting.

**How it connects to other pages:**
- Every ledger entry is tagged to a reporting period
- Allocations are per-period
- The Dashboard shows data for a selected period
- Reports (GEARS, CalWATRS) are generated per period
- Period finalization is a prerequisite for generating final reports

**Domain context:**
The California water year runs October 1 through September 30 and is named for the ending year. GSAs typically have one reporting period per water year, though some track sub-annual periods (quarterly, monthly). GEARS is due around May 1 for the previous water year. CalWATRS annual reports are due January 31.

---

### 15. Allocations
- **Sidebar section:** Setup
- **Route:** `/accounting/allocations/`
- **Current name:** Allocations

**What the page actually does:**
Paginated list of allocation plans. Each row shows: name, zone, water type (groundwater, surface water, recycled, etc.), reporting period, and allocation amount in acre-feet. Search across name, zone, and water type. Filter by reporting period. Create form: select zone, water type, reporting period, and set the allocation amount.

**What question it answers for a GSA manager:**
"How much water has been budgeted for each zone and each water type this year? What are the allocation limits?" Allocation plans set the water budgets that the dashboard tracks against. Each zone gets an allocation for a specific water type during a specific period. When the dashboard shows "Remaining" for a zone or account, it is comparing actual usage against these allocations.

**How it connects to other pages:**
- Allocations are per zone, per water type, per reporting period
- The Dashboard uses allocations to compute "Remaining" columns
- Zones are geographic management areas (from geography app)
- Water types define the source category (groundwater, surface, etc.)
- Parcels are in zones via ParcelZone, so parcel-level use rolls up to zone allocations

**Domain context:**
Under SGMA, GSAs set sustainable yield allocations -- how much groundwater can be pumped from each management area without causing overdraft. Some GSAs also allow "transition water" (temporary extra allocation) that is ramped down over time. Allocations are the policy lever that controls pumping.

---

### 16. Getting Started
- **Sidebar section:** Help
- **Route:** `/help/getting-started/`
- **Current name:** Getting Started

**What the page actually does:**
Walkthrough guide for new GSA administrators. Explains the setup sequence and key concepts.

**What question it answers for a GSA manager:**
"I just logged in for the first time. What do I do?"

---

### 17. Glossary
- **Sidebar section:** Help
- **Route:** `/help/glossary/`
- **Current name:** Glossary

**What the page actually does:**
Alphabetical glossary of 22 water accounting terms used throughout the platform: Allocation Plan, CalWATRS, CDEC, CIMIS, Data Source, GEARS, GSA, GSP, Health Check, Ledger Entry, MAR, Monitoring Station, OpenET, Parcel, Point of Diversion, Reporting Period, SGMA, USGS, Water Account, Water Right, Well. Includes jump navigation by first letter.

**What question it answers for a GSA manager:**
"What does this term mean?" Many GSA staff are not water engineers -- they are administrative, financial, or policy staff who need plain definitions.

---

### 18. About
- **Sidebar section:** Help
- **Route:** `/about/`
- **Current name:** About

**What the page actually does:**
Public (no login required) page showing the platform purpose, policy backstory timeline (AB 1755, SGMA, GEARS, CalWATRS, OpenET, Governor's executive orders), how-to guides, and organizational credits. Shows the logo.

**What question it answers for a GSA manager:**
"What is this platform and why does it exist? What policy mandates does it support?"

---

## How GSA Managers Think About Their Work

Based on domain research, GSA managers organize their work around **four primary concerns**, roughly in order of daily priority:

### 1. "Are we sustainable?" (Basin Health)
The overriding question. SGMA requires GSAs to avoid six "undesirable results": chronic lowering of groundwater levels, reduction of storage, seawater intrusion, degraded water quality, land subsidence, and depletion of interconnected surface water. Managers check groundwater levels, subsidence data, and water quality trends to know if their basin is on track.

### 2. "How much water is being used vs. allocated?" (Water Budget)
The operational question. Managers track pumping (from meters or ET estimates) against allocations per zone and per account. If an account is over-budget, they need to know immediately. The water budget is the GSA's financial statement -- supply deposits vs. usage withdrawals.

### 3. "Can we file our reports on time?" (Compliance)
The regulatory question. GEARS reports are due to DWR around May 1 (groundwater extraction by well). CalWATRS reports are due to the Water Board by January 31 (surface water diversions). Missing a deadline or filing incomplete data has consequences. Managers work backward from deadlines, checking data completeness weeks in advance.

### 4. "Is our data current and complete?" (Data Quality)
The infrastructure question. Are monitoring stations reporting? Are meter readings submitted? Is the OpenET data loaded for the current season? Data gaps undermine the water budget and make reports unreliable. Managers need to know which data feeds are stale before they can trust the numbers.

### Mental Model: The GSA Manager's Week

**Monday:** Check dashboard -- any accounts approaching allocation limits? Review station freshness -- any data feeds down?

**Midweek:** Enter new data (meter readings, manual entries), review ledger for the current period, check recharge event logs if MAR is active.

**End of week:** Review water budget trends by zone, check if any curtailment orders affect surface water rights.

**Monthly:** Generate and review draft reports, check data completeness for upcoming filing deadlines.

**Quarterly/Annually:** Finalize reporting period, generate GEARS/CalWATRS submissions, update allocations for next period, review health check results.

---

## Suggested Navigation Groupings

Based on how GSA managers think about their work (not how the code is organized), here is a proposed sidebar reorganization:

### Current Structure vs. Proposed Structure

**Current:** Dashboard, Map | (Data) Ledger, Parcels, Wells, Surface Water, Recharge, Stations, Infrastructure | (Reporting) Reports | (System) Health, Setup Wizard | (Setup) Accounts, Periods, Allocations | (Help) Getting Started, Glossary, About

**Proposed (organized by user mental model):**

```
--- Overview ---
  Dashboard           (water budget scorecard)
  Map                 (geographic command center)

--- Water Data ---
  Ledger              (all transactions)
  Parcels             (land registry)
  Wells               (groundwater extraction points)
  Surface Water       (water rights and diversions)
  Recharge            (managed aquifer recharge)

--- Monitoring ---
  Stations            (external data feeds)

--- Compliance ---
  Reports             (GEARS and CalWATRS)

--- Administration ---
  Accounts            (water user accounts)
  Periods             (reporting time windows)
  Allocations         (water budgets by zone)
  Infrastructure      (add physical features)
  Setup Wizard        (first-run configuration)

--- Help ---
  Getting Started
  Glossary
  About
```

### Rationale for Changes

1. **"Data" is too generic.** Split into "Water Data" (the things a manager works with daily) and "Monitoring" (the external data feeds they check for health). Stations are fundamentally different from parcels/wells -- they are about data freshness and external feeds, not about the district's own assets.

2. **Move "Accounts", "Periods", and "Allocations" into "Administration."** These are setup/configuration items that a manager touches infrequently (start of year, or when onboarding new users). Keeping them in the "Data" section buries them among daily-use pages. Keeping them separate from "System" (which is technical) makes the distinction clear: "Administration" is policy/business configuration, "System" is technical health.

3. **Move "Infrastructure" to "Administration."** Adding new wells, diversions, or recharge sites is an infrequent administrative task, not a daily data review. Once infrastructure is added, the user interacts with it through the Wells, Surface Water, or Recharge pages.

4. **Rename "System" section.** "System" currently holds Health and Setup Wizard, which are both technical. Move Setup Wizard to Administration (it is a one-time setup task). Keep Health under a "System" label or rename to "Technical."

5. **"Compliance" better names the reporting section.** GSA managers think "compliance" not "reporting" -- the reports exist because of regulatory deadlines. The word "Compliance" immediately signals urgency and importance.

---

## Name Evaluation: Current vs. Suggested

| Current Name | Keep/Change | Suggested Name | Reason |
|---|---|---|---|
| Dashboard | Keep | Dashboard | Universally understood |
| Map | Keep | Map | Clear and concise |
| Ledger | Keep | Ledger | Accurate domain term for water accounting |
| Parcels | Keep | Parcels | Standard term in California water management |
| Wells | Keep | Wells | Standard term |
| Surface Water | Keep | Surface Water | Already renamed from "Water Rights" in Phase 19.2; good choice because not all users are rights holders |
| Recharge | Consider | Recharge Sites | "Recharge" alone is a verb; "Recharge Sites" clarifies this is a facility list |
| Stations | Consider | Monitoring | "Stations" is technically correct but "Monitoring" better describes the purpose (checking data health) |
| Infrastructure | Keep | Infrastructure | Accurate for the unified add-feature form |
| Reports | Consider | Reports (under "Compliance" section label) | Keep the page name, change the section label |
| Health | Keep | Health | Clear |
| Setup Wizard | Keep | Setup Wizard | Descriptive |
| Accounts | Keep | Accounts | Standard term in water accounting |
| Periods | Consider | Reporting Periods | "Periods" alone is ambiguous; "Reporting Periods" matches the domain term |
| Allocations | Keep | Allocations | Standard term in GSA practice |
| Getting Started | Keep | Getting Started | Clear |
| Glossary | Keep | Glossary | Clear |
| About | Keep | About | Clear |

---

## Data Flow Summary

This diagram shows how data moves through the system from the perspective of a GSA manager's workflow:

```
SETUP (once)
  Setup Wizard
    --> uploads boundary
    --> auto-populates: parcels, basins/zones, flowlines, stations

CONFIGURATION (start of year)
  Periods       --> creates water year (Oct 1 - Sep 30)
  Accounts      --> creates user accounts, assigns parcels
  Allocations   --> sets water budgets per zone per period

DAILY OPERATIONS
  Infrastructure --> adds wells, PODs, recharge sites (+ map draw)
  Ledger         --> records transactions (manual, CSV, or from data sync)
    sources: meter readings, ET estimates, diversions, recharge events

MONITORING
  Stations       --> checks data freshness from CDEC/USGS/CIMIS/OpenET
  Map            --> visualizes everything spatially
  Dashboard      --> shows water budget: supply vs. usage vs. allocation

COMPLIANCE (deadlines)
  Reports        --> generates GEARS CSV (due ~May 1 for GW extraction)
                 --> generates CalWATRS CSV (due ~Jan 31 for SW diversions)
                 --> tracks submission status: draft > reviewed > submitted

MAINTENANCE
  Health         --> monitors system health (database, sync, data integrity)
```
