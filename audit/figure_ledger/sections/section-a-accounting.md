# Section A. The money layer (31 figures)

Six screens where the platform states a quantity of water in acre-feet and a
reader is expected to act on it: the balance pane on a water account, the audit
page that shows how one parcel-month's billable groundwater was worked out, the
live preview of the saved calculation method, the use-ledger table and its
footer totals, the allocations table, and the reporting-period page.

**Screens and pins.** Everything is pinned to **WY 2025-2026** (reporting period
2, the drier of the demonstration's two years), the same water year section 1
pinned on the dashboard, so the two sections can be held against each other and
not only against the database.

| Screen | Figures | Pinned to |
|---|---|---|
| `/accounting/accounts/78/?period=2` | `009`–`020` | MER-ACCT-001, Ashvale Orchards Inc., the same account section 1 pinned. Per-parcel row: MER-APN-021. |
| `/accounting/calculation-run/16/2026-03/` | `001`–`008` | MER-APN-016, March 2026. Chosen because effective rainfall actually bites there, so the step table's In and Out columns differ instead of repeating one number. |
| `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `050`–`053` | The same parcel-month as the run page, deliberately. |
| `/accounting/ledger/?period=2` | `046`–`049` | First entry row on screen; default sort, page size 100. |
| `/accounting/allocations/?period=2` | `021`, `022` | The Halvern Irrigation-Urban GSA groundwater allocation for WY 2025-2026. |
| `/accounting/reporting-periods/2/` | `054` | The Halvern Valley GSA groundwater allocation for WY 2025-2026. |

The wet year, `/accounting/accounts/78/?period=1`, was captured as a second
instance of the account pane and is recorded at the end of this section. All
seven pages answered 200. Sizes and content fingerprints are in
`audit/figure_ledger/rendered/manifest-a.json`.

**Two pins are not reproducible by position, and are pinned by name instead.**
Every one of MER-ACCT-001's eighteen parcel assignments carries the same
`added_date`, so the per-parcel table's sort key is a complete tie and "the first
row" is whatever the database returns that day; and the reporting-period page
applies no ordering at all to its allocation table. Both are pinned by the parcel
number and the allocation name a reader can see. This is noted again in the
findings, because it is a property of the screens, not of this audit.

**How to reproduce this section**, from the repository root:

```
docker compose exec -T web python scripts/figure_capture.py \
    --screens audit/figure_ledger/screens-a.json \
    --out audit/figure_ledger/rendered --sha "$(git rev-parse HEAD)"
docker compose cp web:/app/audit/figure_ledger/rendered/. audit/figure_ledger/rendered/
python3 audit/figure_ledger/extract_section_a.py \
    --rendered audit/figure_ledger/rendered \
    --out audit/figure_ledger/results/rendered_accounting_detail.csv
bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/accounting_detail.sql \
    > audit/figure_ledger/results/recomputed_accounting_detail.csv
python3 audit/figure_ledger/merge_results.py \
    --rendered   audit/figure_ledger/results/rendered_accounting_detail.csv \
    --recomputed audit/figure_ledger/results/recomputed_accounting_detail.csv \
    --out        audit/figure_ledger/results/accounting_detail.csv
```

The capture runs inside the application container, because that is where the web
framework lives, and the copy after it exists because that container holds no
live link back to the working copy. The recomputation runs on the host, against
the same database the pages rendered from, and cannot reach a line of the
platform's own code.

**Captured at commit `9f9e27b2543516a95cdc15743070e3746d04ddbe`**, 2026-09-05.
The database was left exactly as found: 4 user rows before the capture and 4
after.

**Two notes on how to read the ledger.**

Three rows carry the verdict `MATCH · ISS-pending`. That is not a hedge. The
number rendered agrees with the independent recomputation to the cent, so the
arithmetic is right, and a separate issue is raised against the words printed
beside it. Both halves are true and a reader needs both.

Where section 1's schema prints a dash in the `service` column to mean "no
service function produced this", this section prints `n/a`. Same meaning,
different mark, so that this file carries no em dashes at all. The two pinned
allocations are named here by their zone, water type and year, which identify the
row uniquely; `accounting_detail.sql` and `extract_section_a.py` carry the stored
names character for character, because they have to match.

---

## The ledger

| `id` | `screen` | `site` | `label` | `context_var` | `view` | `service` | `raw_tables` | `rendered` | `recomputed` | `delta` | `verdict` | `notes` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `FIG-accounting-001` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:38` | acres | `parcel.area_acres` | `accounting/views.py:1231` | `n/a (model field)` | `parcels_parcel` | 149.73 | 149.73 | MATCH | MATCH | Independence: restatement. Read straight off the parcel row the view fetched. It is not an independent quantity, but it is load-bearing, because every acre-foot figure on this page is this number times a millimetre of rainfall or evaporation. |
| `FIG-accounting-002` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:46` | Billable groundwater | `run.final_af` | `accounting/views.py:1232` | `n/a (model field, written by accounting/management/commands/run_calculations.py:272)` | `accounting_calculationrun` | 27.9945 | 27.9945 | MATCH | MATCH | Independence: different identity. Also checked against the magnitude of the `calculated` ledger row for the same parcel-month, which is what the page's own result card claims it equals (agrees to 0.0000), and against the last step of the waterfall, likewise 0.0000. |
| `FIG-accounting-003` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:79` | In (AF) | `step.input_af` | `accounting/views.py:1266` | `n/a (read out of the stored breakdown)` | `accounting_calculationrun` | 0.0000 | 0.0000 | MATCH | MATCH | Independence: restatement, plus a whole-table identity. Pinned to step 1, which starts at zero. Every one of the five steps was also checked for continuity, each step's In against the step above it's Out, and none breaks. |
| `FIG-accounting-004` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:80` | Out (AF) | `step.output_af` | `accounting/views.py:1267` | `n/a (read out of the stored breakdown)` | `accounting_calculationrun, datasync_openetcache, parcels_parcel` | 39.8491 | 39.8491 | MATCH | MATCH | Independence: **different identity**. Rebuilt from the raw satellite reading, 81.119346 mm of evapotranspiration over 149.73 acres divided by 304.8, without reading the stored figure at all. The recomputation could have disagreed and did not. |
| `FIG-accounting-005` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:94` | Deposited this month | `run.banked_af` | `accounting/views.py:1232` | `n/a (model field)` | `accounting_calculationrun` | *(not rendered)* | 0.0000 | NO VALUE | UNVERIFIED | The whole banked-water block sits behind a condition no row in this database satisfies: **0 of 1,824 calculation runs** carry a non-zero deposit or draw. Nothing was on screen to read. The stored value is 0.0000, and that is not the same claim. |
| `FIG-accounting-006` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:98` | Drawn down this month | `run.drawn_af` | `accounting/views.py:1232` | `n/a (model field)` | `accounting_calculationrun` | *(not rendered)* | 0.0000 | NO VALUE | UNVERIFIED | Same block, same reason. |
| `FIG-accounting-007` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:114` | Drawn (AF) | `draw.amount_af` | `accounting/views.py:1273` | `n/a (queryset)` | `accounting_watercreditdraw` | *(not rendered)* | *(no rows)* | NO VALUE | UNVERIFIED | Nested one level deeper still: the draws table needs a `WaterCreditDraw` row and **there are none**, though five water-credit rows are held. |
| `FIG-accounting-008` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:132` | Final billable groundwater | `run.final_af` | `accounting/views.py:1232` | `n/a (model field)` | `accounting_calculationrun` | 27.9945 | 27.9945 | MATCH | MATCH | Independence: different identity, as `FIG-accounting-002`. The page states this figure twice, at the top and at the foot; both render the same value, which is a thing the page could get wrong and does not. |
| `FIG-accounting-009` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:11` | Supplies | `balance.supply_total` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun, accounting_wateraccountparcel` | 5,921.09 | 5921.09 | MATCH | MATCH | Independence: restatement. The gross-estimate suppression is stated as its own predicate in the recomputation; it removes 0 rows here, for the reason in finding 2. |
| `FIG-accounting-013` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:16` | Consumptive use | `balance.consumptive_use_gross` | `accounting/views.py:630` | `account_consumptive_balance` | `accounting_calculationrun` | 4,589.61 | 4589.61 | MATCH | MATCH | Independence: **different identity**. Rebuilt over all 216 of this account's parcel-months from the raw satellite readings and the parcels' acreage, never touching the stored evapotranspiration column. Agrees to the cent. |
| `FIG-accounting-014` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:21` | Balance | `balance.net_vs_supply` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 1,331.48 | 1331.48 | MATCH | MATCH | Independence: restatement. Supplies minus consumptive use, both above. |
| `FIG-accounting-010` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:25` | Surface | `balance.supplies.surface` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger` | 5,500.97 | 5500.97 | MATCH | MATCH | Independence: restatement. Magnitude of the canal-delivery rows, which the platform stores as negative numbers by its own production convention. |
| `FIG-accounting-011` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:26` | Groundwater | `balance.supplies.groundwater` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. A real zero, not a suppression: 216 calculation runs sit behind this account in the period and not one groundwater or meter row. |
| `FIG-accounting-012` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:27` | Rain | `balance.supplies.precip` | `accounting/views.py:630` | `account_consumptive_balance` | `accounting_calculationrun` | 420.12 | 420.12 | MATCH | MATCH | Independence: **different identity**. Rebuilt over the same 216 parcel-months from raw rainfall and evapotranspiration through the published USDA-SCS TR-21 formula, transcribed into the recomputation with its source lines. Agrees to the cent. |
| `FIG-accounting-015` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:56` | Consumptive Use | `pb.consumptive_use_gross` | `accounting/views.py:645` | `parcel_consumptive_balance` | `accounting_calculationrun` | 177.23 | 177.23 | MATCH | MATCH | Independence: restatement. Pinned to MER-APN-021. The whole column was also summed and held against the panel above it; see `FIG-accounting-019`'s note. |
| `FIG-accounting-016` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:59` | Surface | `pb.surface` | `accounting/views.py:647` | `parcel_consumptive_balance` | `parcels_parcelledger` | 210.17 | 210.17 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-017` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:62` | Groundwater | `pb.groundwater` | `accounting/views.py:648` | `parcel_consumptive_balance` | `parcels_parcelledger` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-018` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:65` | Precip | `pb.precip` | `accounting/views.py:649` | `parcel_consumptive_balance` | `accounting_calculationrun` | 17.92 | 17.92 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-019` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:68` | Supplies | `pb.supply_total` | `accounting/views.py:650` | `parcel_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 228.09 | 228.09 | MATCH | MATCH | Independence: restatement, plus a **different identity** the code could fail. The per-parcel table is built one parcel at a time while the panel above it is built in a single pass over all eighteen; the two agree only if the gross-estimate suppression really is per-parcel. Summed whole-column, all four supply and use columns land on the panel exactly: difference 0.00. |
| `FIG-accounting-020` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:71` | Net | `pb.net_vs_supply` | `accounting/views.py:651` | `parcel_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 50.87 | 50.87 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-021` | `/accounting/allocations/?period=2` | `templates/accounting/partials/_allocations_list_results.html:34` | Allocation (AF) | `alloc.allocation_acre_feet` | `accounting/views.py:478` | `n/a (model field; queryset built at accounting/views.py:454)` | `accounting_allocationplan` | 750.32 | 750.32 | MATCH | MATCH | Independence: restatement. The same 750.32 the dashboard's zone table shows for this zone, on a second screen. |
| `FIG-accounting-022` | `/accounting/allocations/?period=2` | `templates/accounting/partials/_allocations_list_results.html:50` | All 8 allocations | `allocation_total` | `accounting/views.py:474` | `n/a (queryset aggregate)` | `accounting_allocationplan` | 159,671.46 | 159671.46 | MATCH · ISS-pending | MATCH · ISS-pending | Independence: restatement. The sum is right. It adds **148,500.00 AF of surface-water allocation to 11,171.46 AF of groundwater allocation** and prints one number in acre-feet, and no agency manages that quantity. See finding 4. |
| `FIG-accounting-052` | `/accounting/ledger/?period=2` | `templates/accounting/partials/_ledger_list_results.html:77` | Amount (AF) | `entry.amount_acre_feet` | `accounting/views.py:1009` | `n/a (model field)` | `parcels_parcelledger` | -8.56 | -8.56 | MATCH | MATCH | Independence: restatement, including the view's ordering. Pinned to the first row on screen, a metered groundwater reading on MER-APN-065 dated 15 September 2026, reproduced by restating the sort rather than by naming a row and hoping. |
| `FIG-accounting-053` | `/accounting/ledger/?period=2` | `templates/accounting/partials/_ledger_list_results.html:114` | net AF | `ledger_total_net` | `accounting/views.py:1011` | `n/a (queryset aggregate)` | `parcels_parcelledger` | -1,504.32 | -1504.32 | MATCH · ISS-pending | MATCH · ISS-pending | Independence: restatement. Arithmetic correct over all 1,130 rows in the period. But this figure and the dashboard's Balance describe the same 76 parcels in the same water year and **disagree in sign**. See finding 3. |
| `FIG-accounting-054` | `/accounting/ledger/?period=2` | `templates/accounting/partials/_ledger_list_results.html:117` | credits | `ledger_total_credits` | `accounting/views.py:1012` | `n/a (queryset aggregate)` | `parcels_parcelledger` | 14,280.77 | 14280.77 | MATCH · ISS-pending | MATCH · ISS-pending | Independence: restatement, plus the footer's own identity: credits plus debits equals net, difference 0.00. The 14,280.77 is 13,819.63 AF of allocation entries plus 461.14 AF of recharge. **Not one drop of it is water delivered to anybody.** Finding 3. |
| `FIG-accounting-055` | `/accounting/ledger/?period=2` | `templates/accounting/partials/_ledger_list_results.html:118` | debits | `ledger_total_debits` | `accounting/views.py:1013` | `n/a (queryset aggregate)` | `parcels_parcelledger` | -15,785.09 | -15785.09 | MATCH · ISS-pending | MATCH · ISS-pending | Independence: restatement. The -15,785.09 is -11,407.71 AF of canal deliveries plus -4,377.38 AF of pumping, and the dashboard calls **both of those supplies**, in those exact figures. Finding 3. |
| `FIG-accounting-056` | `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `templates/accounting/partials/_methodology_preview.html:22` | Billable groundwater | `final_af` | `accounting/views.py:1559` | `evaluate_chain` | `accounting_calculationplan, accounting_calculationstep, datasync_openetcache, parcels_parcel` | 27.9945 | 27.9945 | MATCH | MATCH | Independence: **different identity**. This screen computes fresh and stores nothing, so there is no row of its own to check it against; it is held instead against the persisted calculation run for the same parcel-month, which was written by a different code path on a different day. The two agree exactly. |
| `FIG-accounting-057` | `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `templates/accounting/partials/_methodology_preview.html:52` | In (AF) | `step.input_af` | `accounting/views.py:1563` | `evaluate_chain` | `accounting_calculationstep, datasync_openetcache` | 0.0000 | 0.0000 | MATCH | MATCH | Independence: different identity, as above. Pinned to step 1. |
| `FIG-accounting-058` | `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `templates/accounting/partials/_methodology_preview.html:53` | Out (AF) | `step.output_af` | `accounting/views.py:1564` | `evaluate_chain` | `accounting_calculationstep, datasync_openetcache, parcels_parcel` | 39.8491 | 39.8491 | MATCH | MATCH | Independence: **different identity**. Same raw-satellite rebuild as `FIG-accounting-004`. The live preview reproduces all five stored steps identically, which is the thing this screen exists to promise and the thing nothing else tests. |
| `FIG-accounting-059` | `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `templates/accounting/partials/_methodology_preview.html:60` | final … AF | `final_af` | `accounting/views.py:1559` | `evaluate_chain` | `accounting_calculationplan, accounting_calculationstep` | *(not rendered)* | *(unreachable)* | NO VALUE | UNVERIFIED | This is the fallback sentence shown when the saved method produces no steps at all. **All 5 steps on the active method are enabled**, so the branch cannot be reached without turning every one of them off, a configuration change this phase is not permitted to make. |
| `FIG-accounting-060` | `/accounting/reporting-periods/2/` | `templates/accounting/period_detail.html:136` | Allocation (AF) | `alloc.allocation_acre_feet` | `accounting/views.py:404` | `n/a (model field; queryset built at accounting/views.py:397)` | `accounting_allocationplan` | 9689.40 | 9689.40 | MATCH | MATCH | Independence: restatement. The same database row the allocations list shows as **9,689.40**, printed here as **9689.40** with no thousands separator. See finding 5. |

**Second instance, the wet year.** `/accounting/accounts/78/?period=1`, WY
2024-2025, captured so a later plan can check the same twelve sites against a
different year without re-deriving the pin: Supplies **5,966.10**, Consumptive
use **4,667.86**, Balance **1,298.24**; Surface **5,177.09**, Groundwater
**0.00**, Rain **789.01**. First per-parcel row, MER-APN-021: 180.32 · 197.25 ·
0.00 · 33.32 · 230.57 · 50.25. These are recorded, not reconciled. The
recomputation in this section is pinned to the dry year.

---

## What section A found

**Twenty-seven of the thirty-one figures rendered a number, and all twenty-seven
agree with the rows behind them, to the cent.** Four never appeared on screen at
all, and are recorded as unverified rather than assumed. Of the twenty-seven that
matched, five were rebuilt from a genuinely different starting point, from the
raw satellite and rainfall readings through the published formula rather than
from the platform's own stored answer, and those five could have disagreed. They
did not.

That is the good news, and it is worth stating plainly before the rest, because
the rest is about what the numbers are called rather than whether they are right.

### 1. The calculation the platform bills on can be rebuilt from scratch, and it holds

The audit page for MER-APN-016 in March 2026 says 39.8491 acre-feet of
evapotranspiration, less 11.8546 acre-feet of effective rainfall, leaves 27.9945
acre-feet of billable groundwater. None of those three numbers was taken on
trust. Starting from the satellite reading (81.119346 mm), the weather record
(34.466205 mm of rain), the parcel's acreage, and the published USDA-SCS TR-21
formula written out with its source lines, the recomputation produced **39.8491
and 11.8546**. The same rebuild, run across all 216 parcel-months behind the
account balance pane, reproduced its Consumptive use of **4,589.61 AF** and its
Rain of **420.12 AF** exactly.

This matters more than a matching column usually does. Every other figure in this
section is ultimately a sum of these. If the conversion from millimetres to
acre-feet were wrong, or the rainfall formula mis-transcribed, every acre-foot on
every screen in the section would be wrong together and every internal check
would still pass. It is the one thing an audit of this kind can genuinely
establish, and it is established.

Two smaller checks in the same family: the step table's arithmetic runs
continuously (each step's In equals the step above it's Out, no breaks), and the
final figure equals the magnitude of the ledger entry the page claims it equals,
to 0.0000.

### 2. Three guards on this pane cannot currently fire, and one has never had anything to bite on

Section 1 found the same about the dashboard. It is true here too, and one of the
three is stronger than section 1 could see from its own screen:

| Guard | What it prevents | State on this data |
|---|---|---|
| The gross-estimate suppression | Counting both a satellite estimate and the netted figure for the same parcel-month, doubling every supply | **0 estimate rows exist anywhere in the ledger**, not merely none in this period. Five row types are in use; that one is not among them |
| The per-parcel and per-account split | The parcel table and the panel above it disagreeing | Checked, not assumed: all four columns sum to the panel, difference **0.00** |
| Banked water | Understating a bill by ignoring a credit already deposited | **0 of 1,824 calculation runs** carry a deposit or a draw, and there are **0 draw rows**, so the whole block is unreachable |

The recomputation states the suppression rule as its own predicate anyway, so
this section stays correct the day the data grows an estimate row. **No reader
should take any of these three as tested.** The first in particular: it is the
rule that stops every supply figure in this section from doubling, and it has
never once been exercised by this data.

### 3. Two screens state a year's balance for the same parcels and disagree about the sign

The dashboard says the district ended WY 2025-2026 **1,249.07 AF ahead**. The use
ledger, filtered to the same water year, says **-1,504.32 AF**. These are not two
views of one quantity that happen to differ. They cover the same 1,130 ledger
rows on the same 76 parcels, and they are different quantities that share a unit
and a sign convention.

The ledger footer splits rows by the sign stored in the amount column:

| Footer says | Is made of | Which the rest of the platform calls |
|---|---|---|
| credits **+14,280.77** | allocation entries 13,819.63 plus recharge 461.14 | a budget, and water put back; not water delivered to anyone |
| debits **-15,785.09** | canal deliveries -11,407.71 plus pumping -4,377.38 | **supplies**, in exactly those two figures |

The 11,407.71 and the 4,377.38 are not near the dashboard's Surface and
Groundwater supply figures. They **are** the dashboard's Surface and Groundwater
supply figures, to the cent, on the same day. One screen books a canal delivery as
water arriving; the other books it as a debit, because the platform stores a
delivery as a negative number, a storage convention its own balance code
documents at length and deliberately overrides. The ledger footer is the one place
that reads the sign literally.

Nothing on the ledger page says any of this. A district manager who opens the use
ledger, sets the year, and reads the footer comes away believing the year ran
1,504 acre-feet in the red, on a platform whose own dashboard says it ran 1,249
acre-feet in the black.

`FIG-accounting-053`, `048` and `049` each carry this. The arithmetic in all
three is correct.

### 4. The allocations footer adds surface water to groundwater

The allocations table for WY 2025-2026 ends with **159,671.46 AF**. That is
148,500.00 AF of surface-water allocation plus 11,171.46 AF of groundwater
allocation, added together. They are separate budgets, held by separate agencies
under separate law, and there is no decision anyone makes for which their sum is
the input.

The template's own comment explains why the total is a single sum rather than the
ledger's credits-and-debits split, because allocations are unsigned positive
volumes, and that reasoning is sound as far as it goes. It just does not reach the
question of whether two kinds of water belong in one total.

Worth having beside it: **the district's surface allocation for the year is 13
times the surface water it actually delivered**, 148,500.00 AF allocated against
11,407.71 AF delivered. Section 1 found the same shape at account level and Phase
136 re-sizes these; this is the district-wide version of that before-picture.

One more caution for anyone reading across these screens. The word *allocation*
names two different things in this platform: the zone-level plans on the
allocations page, which total 159,671.46 AF for this year, and the per-parcel
ledger entries of the same name, which total 13,819.63 AF for the same year. Both
figures are correct. Neither screen mentions the other.

### 5. Two reproducibility problems that belong to the screens, not to this audit

**The reporting-period page applies no ordering at all** to its allocation table.
Its rows come back in whatever order the database happens to return, so the same
page can show the same rows in a different sequence on a different day, and no
figure on it can be pinned by position. The same is true of the account's
per-parcel table for a different reason: it sorts by a date that is identical on
all eighteen rows, so the sort settles nothing.

**And the same allocation figure is printed two ways.** Halvern Valley GSA's
groundwater allocation for this year is **9,689.40** on the allocations list and
**9689.40** on the reporting-period page: the same database row, one screen using
a thousands separator and the other not.

### 6. What could not be checked, and why

Four of the thirty-one sites never rendered. Naming them:

- **`FIG-accounting-005`, `006`, `007`.** The banked-water block on the
  calculation-run page, and the credit-draw table nested inside it. No calculation
  run in this database has a non-zero deposit or draw, and no draw rows exist, so
  the block is unreachable with this demonstration data. Five water-credit rows
  are held, which is why the feature is not simply dead code.
- **`FIG-accounting-059`.** The methodology preview's fallback line, shown when
  the saved method yields no steps. All five steps on the active method are
  enabled, and reaching that branch would mean turning them off, which is a
  configuration change this phase may not make.

For each of the four, the value stored in the database is recorded in the
recomputation column, and the rendered column is empty. Those are different
claims and the ledger keeps them apart: the database holding a zero is not the
same as the screen having shown one.

---

## Cross-screen agreement, observed

Two things fell out of this section that no single screen can show, both read
from two independently captured pages rather than inferred:

**The account balance pane and the dashboard's account row state the same six
figures and agree exactly.** For MER-ACCT-001 in WY 2025-2026, both screens read
Consumptive Use 4,589.61 · Surface 5,500.97 · Groundwater 0.00 · Precip 420.12 ·
Supplies 5,921.09 · Net 1,331.48. They come through different views but the same
shared calculation, and this is direct evidence that the sharing works.

**The live methodology preview reproduces the persisted calculation run, step for
step.** Same five labels, same five In and Out figures, same final number, for a
run written on a different day by a different code path. That is exactly the
promise the preview screen makes to an operator tuning the method, and nothing
else in the codebase checks it.
