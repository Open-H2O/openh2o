# Figure ledger — September 2026

Every number this platform puts on a screen, traced to the rows it came from and
then worked out a second way, independently, to see whether the two agree.

**This ledger is complete.** All 106 figures the platform renders have a row, and
a test in the build refuses to let that stay true by accident: add a figure to a
template without tracing it, or leave a row behind after deleting a template, and
the suite goes red.

## What this is, and what it is not

The platform renders 106 figures across 24 page templates. Each one has a chain
behind it: a page, a template line, a view that put a value into that line, often
a service function that computed it, and underneath all of it some rows in the
database. This ledger walks that chain for every figure, and then does something
that sounds redundant and is not — it computes the same number again from the
raw rows, in SQL, without touching a single line of the platform's own code.

**That second computation is the whole point, and it is why the ledger is
written in SQL rather than in the platform's own language.** A check that calls
the function it is checking can only ever discover that the function is
consistent with itself. It would pass on a system whose arithmetic was wrong in
every figure. So the recomputation may name tables and columns and nothing else,
and it runs outside the application process entirely, where it could not call in
even by accident.

This is **not** a bug list, and it is not a promise that every figure is right.
It is a record of what the screens said on a stated day, beside what the stored
rows say they should have said. Where the two agree the row says so. Where they
differ the row carries the difference and an issue number, and the fix is
somebody else's plan.

A second honesty the ledger keeps: a recomputation that re-derives the same steps
the platform performs is a weaker check than one that starts from a different
idea of what the number is. Every row says which kind it is, in its Notes.

> **The numbers below are demonstration data.** This platform's demonstration
> mixes one invented groundwater district — invented basin, invented districts,
> invented growers — with one real, published drinking-water record. Every figure
> in this document belongs to the invented district. No row here describes a real
> water user.

## What the ledger found

**84 of the 106 figures agree with the rows behind them to the cent, and nothing
in this platform computes a number wrongly.** Not one figure disagrees with its
own arithmetic. What the ledger found instead is figures that are correct and
labelled wrongly, and figures that no screen can currently show.

| Verdict | Count of 106 | Meaning |
|---|---:|---|
| `MATCH` | 84 | The screen and the independent recomputation agree to the cent |
| `MATCH · ISS-###` | 4 | The number is right; a separate issue is raised against the words beside it |
| `ISS-###` | 4 | The screen states two things that cannot both be true |
| `EXPLAINED` | 1 | The two agree for a stated reason that is not a measurement |
| `UNVERIFIED` | 13 | The screen never rendered it, or nothing derives it |

Nine rows carry an issue number, and they name four problems:

**The district page counts canal water as pumping** ([ISS-154](#), reserved here
and filed by the next plan). A district's Allocation vs. use table has a column
headed Used with the word *pumped* beside it. It adds every negative entry in the
district's ledger, and canal deliveries are stored as negative numbers, so they
land inside it. Two of the three groundwater districts read as over budget when
their groundwater draw alone is comfortably under — not by a margin, but with the
opposite sign. The third takes no canal water, which is why the fault is
invisible to anyone reading one page. Section 5, finding 1.

**The parcel pane states two balances that disagree** ([ISS-148](#), already
filed). A card at the top of the pane says 174.13 acre-feet of water arrived and
was not consumed; a residual three inches below says the books close at 0.00,
Balanced. On about two thirds of parcels each year the two printed numbers
differ. Section 2, finding 1.

**The use ledger and the dashboard state the year with opposite signs**
([ISS-155](#), reserved). Over the same 1,130 rows on the same 76 parcels, the
dashboard says the district finished 1,249.07 acre-feet ahead and the use ledger
footer says 1,504.32 behind. Both arithmetics are correct. Section 3, finding 3.

**The allocations footer adds surface water to groundwater** ([ISS-156](#),
reserved). 148,500.00 acre-feet of surface-water allocation plus 11,171.46 of
groundwater allocation, printed as one number in acre-feet that no agency
manages. Section 3, finding 4.

Thirteen figures could not be independently recomputed, and they are named rather
than omitted: four monitoring-station figures (there is no station in this
database, and the file that pins the demonstration's contents says there should
be 335), four on the calculation page's banked-water block (no run in this
database carries a deposit or a draw), two in a notice shown only to a parcel
with no calculations yet (every parcel has them), two well fields a person types
by hand, and the setup wizard's confirmation step, which needs a form submission
to reach.

**One caution that applies to the whole document.** The guard that stops a
month's water being counted twice is stated in every recomputation that depends
on it, and it cannot fire: there are zero satellite-estimate rows anywhere in
this database. It is written down so the ledger stays correct the day the data
grows one. **No reader should take it as tested.**

## How to reproduce it

From the repository root. The inventory and the recomputations run on the host;
the capture runs inside the application container, because that is where the web
framework lives, and the copy after it exists because that container holds no
live link back to the working copy.

```
python3 scripts/figure_inventory.py --out audit/figure_ledger/inventory.json

docker compose exec -T web python scripts/figure_capture.py \
    --screens audit/figure_ledger/screens.json \
    --out audit/figure_ledger/rendered --sha "$(git rev-parse HEAD)"
docker compose cp web:/app/audit/figure_ledger/rendered/. audit/figure_ledger/rendered/

python3 audit/figure_ledger/extract_dashboard.py --help    # section 1
python3 audit/figure_ledger/extract_parcel_pane.py --help  # section 2
python3 audit/figure_ledger/extract_section_a.py --help    # section 3
python3 audit/figure_ledger/extract_section_c.py --help    # section 4

bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/accounting_dashboard.sql
bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/accounting_dashboard_crosschecks.sql
bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/parcel_detail_pane.sql
bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/accounting_detail.sql
bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/surface_reporting.sql
bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/remaining_subsystems.sql
```

⚠ **The application container carries no live link to the working copy, and that
has bitten this audit once already.** A recomputation file written on the host is
invisible inside the container, so the independence guard will run, collect only
the files already in the image, and report a confident pass having read nothing
new. Hand it the files first:

```
docker compose cp audit/figure_ledger/sql/. web:/app/audit/figure_ledger/sql/
docker compose exec -T web python -m pytest tests/test_figure_ledger_independence.py \
    -q --ds=config.settings.local
```

**The count of collected tests is the tell.** Six recomputation files means
twenty cases; if it says eight, it read two.

**Captured at commit `92e7ed87ee2c8de7259635e40941aaed959950bd`**, 2026-09-05, one commit
past tag `v2.15`; that commit added this ledger's own tooling and changed no
template, view, service or model. Pages saved under
`audit/figure_ledger/rendered/`, each with its size and content fingerprint in
`manifest.json` and in the per-section `manifest-a.json` through `manifest-d.json`
beside it. The database was left exactly as found: the capture creates one
throwaway sign-in and deletes it again, and prints the row count on both sides of
the run.

## The schema

| Column | Meaning |
|---|---|
| `id` | `FIG-<app>-<NNN>`, stable, assigned by the inventory script in file/line order |
| `screen` | The URL a person opens, e.g. `/accounting/dashboard/?period=2` |
| `site` | `template/path.html:LINE` — grep-verified, never guessed |
| `label` | The words next to the number on screen (what the reader thinks it means) |
| `context_var` | The template expression, verbatim: `row.net_vs_supply` |
| `view` | `app/views.py:LINE` where that key is set |
| `service` | The function that produced it, or `—` for a model field / annotation |
| `raw_tables` | The base tables the number ultimately comes from |
| `rendered` | The value read out of the served HTML, for the pinned instance |
| `recomputed` | The value the independent SQL returns |
| `delta` | `MATCH` when the two agree to the cent, the difference when they do not, `NO VALUE` when the screen showed nothing |
| `verdict` | `MATCH` · `EXPLAINED` · `UNVERIFIED` · `ISS-###` · `MATCH · ISS-###` |
| `notes` | Independence class and anything a reader needs |

**Pinned instance.** A table column renders once per row, so a column that
appears 76 times gets one named instance — a specific account, parcel, zone or
period — recorded in `screen` and in the notes, plus a whole-column check in the
SQL where that is cheap. Without the pin nobody can reproduce the number.

**The five verdicts, and why there are five.**

- **`MATCH`** — the screen and the recomputation agree to the cent.
- **`EXPLAINED`** — they differ, or agree, for a stated reason that is not a
  measurement: rounding at the display layer, or a term the platform hard-codes.
  It is **not** a synonym for `MATCH`, and a difference with no reason attached is
  an issue number rather than an explanation.
- **`UNVERIFIED`** — it could not be independently recomputed, and the notes say
  why. A screen that never renders it; a value a person typed that nothing
  derives. **This is a complete answer, and it is the one a partial ledger would
  have quietly left out.**
- **`ISS-###`** — the screen states two things that cannot both be true.
- **`MATCH · ISS-###`** — the number is right to the cent and the words beside it
  are wrong. Both halves are true and a reader needs both.

A row with a blank or hand-waved verdict cannot ship: `tests/test_figure_ledger_coverage.py`
refuses it.

---

## Section 1 — The accounting dashboard (23 figures)

**Screen:** `/accounting/dashboard/?period=2` — the water year running October
2025 to September 2026, the drier of the demonstration's two years. This is also
the page a visitor lands on with no year chosen; that was confirmed by capturing
both and comparing them, not by reading the code that picks the default. The two
saved pages differ only in a per-request security token.

**Pinned rows.** The account table's figures are pinned to `MER-ACCT-001`, Ashvale
Orchards Inc., the first row on screen — 18 parcels, 216 monthly calculation runs
in the period. The zone table's figures are pinned to Halvern Irrigation-Urban
GSA, also the first row on screen, 23 parcels. Both tables were also checked
whole-column in SQL where doing so cost nothing.

| `id` | `screen` | `site` | `label` | `context_var` | `view` | `service` | `raw_tables` | `rendered` | `recomputed` | `delta` | `verdict` | `notes` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `FIG-accounting-023` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:24` | Supplies | `grand_supply_total` | `accounting/views.py:194` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun, accounting_wateraccountparcel` | 17458.35 | 17458.35 | MATCH | MATCH | Independence: different identity. Summed over active accounts only. Also computed in ONE pass over the distinct union of those parcels — a second identity that would disagree if any parcel belonged to two active accounts. It does not: none does. |
| `FIG-accounting-024` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:39` | Consumptive use | `grand_consumptive_use` | `accounting/views.py:193` | `account_consumptive_balance` | `accounting_calculationrun` | 16209.28 | 16209.28 | MATCH | MATCH | Independence: different identity. Same single-pass cross-check, same agreement. |
| `FIG-accounting-025` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:48` | Balance | `grand_net` | `accounting/views.py:248` | `— (arithmetic in the view)` | `parcels_parcelledger, accounting_calculationrun` | 1249.07 | 1249.07 | MATCH | MATCH | Independence: different identity. Supplies minus consumptive use, both above. |
| `FIG-accounting-026` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:53` | Surface | `grand_supply_surface` | `accounting/views.py:195` | `account_consumptive_balance` | `parcels_parcelledger` | 11407.71 | 11407.71 | MATCH | MATCH | Independence: different identity. Magnitude of the delivery rows, which are stored as negative numbers by the platform's own convention. |
| `FIG-accounting-027` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:54` | Groundwater | `grand_supply_groundwater` | `accounting/views.py:196` | `account_consumptive_balance` | `parcels_parcelledger` | 4377.38 | 4377.38 | MATCH | MATCH | Independence: different identity. Absolute value OF THE SUM of the negative non-delivery rows, not the sum of absolute values. Transcribed as written; the two differ if a positive row ever lands in that set. |
| `FIG-accounting-028` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:55` | Rain | `grand_supply_precip` | `accounting/views.py:197` | `account_consumptive_balance` | `accounting_calculationrun` | 1673.27 | 1673.27 | MATCH | MATCH | Independence: different identity. Effective rainfall, from the calculation runs rather than the ledger. |
| `FIG-accounting-029` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:151` | Consumptive Use (AF) | `row.consumptive_use_gross` | `accounting/views.py:183` | `account_consumptive_balance` | `accounting_calculationrun` | 4589.61 | 4589.61 | MATCH | MATCH | Independence: restatement. Sum of gross evapotranspiration over the account's parcels' monthly runs. |
| `FIG-accounting-030` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:154` | Surface (AF) | `row.surface` | `accounting/views.py:185` | `account_consumptive_balance` | `parcels_parcelledger` | 5500.97 | 5500.97 | MATCH | MATCH | Independence: restatement. Same delivery-magnitude rule as FIG-accounting-026. |
| `FIG-accounting-031` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:157` | Groundwater (AF) | `row.groundwater` | `accounting/views.py:186` | `account_consumptive_balance` | `parcels_parcelledger` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. 0.00 is a real zero here, not a suppression: this account has 216 monthly calculation runs behind it over 18 parcels, and not one groundwater or meter row in the period. |
| `FIG-accounting-032` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:160` | Precip (AF) | `row.precip` | `accounting/views.py:187` | `account_consumptive_balance` | `accounting_calculationrun` | 420.12 | 420.12 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-033` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:163` | Supplies (AF) | `row.supply_total` | `accounting/views.py:188` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 5921.09 | 5921.09 | MATCH | MATCH | Independence: restatement. The three supply columns added. |
| `FIG-accounting-034` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:166` | Net (AF) | `row.net_vs_supply` | `accounting/views.py:189` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 1331.48 | 1331.48 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-035` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:170` | Allocation (AF) | `row.allocation` | `accounting/views.py:161` | `— (arithmetic in the view)` | `accounting_allocationplan, geography_parcelzone, accounting_wateraccountparcel` | 19101.42 | 19101.42 | MATCH | MATCH | Independence: restatement. Pro-rated by how many of the account's parcel-zone rows fall in each zone. The only figure on this screen computed in the view itself, and the reconciliation had to transcribe that division to reproduce it. |
| `FIG-accounting-036` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:173` | Remaining (AF) | `row.remaining` | `accounting/views.py:171` | `— (arithmetic in the view)` | `accounting_allocationplan, geography_parcelzone, accounting_calculationrun` | 14511.81 | 14511.81 | MATCH | MATCH | Independence: restatement. Allocation minus GROSS evapotranspiration today. Phase 136 changes this to allocation minus groundwater use; this row is the before-picture that change is judged against. |
| `FIG-accounting-037` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:223` | Consumptive Use (AF) | `row.consumptive_use_gross` | `accounting/views.py:235` | `zone_consumptive_balance` | `accounting_calculationrun` | 1189.75 | 1189.75 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-038` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:226` | Surface (AF) | `row.surface` | `accounting/views.py:237` | `zone_consumptive_balance` | `parcels_parcelledger` | 1170.93 | 1170.93 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-039` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:229` | Groundwater (AF) | `row.groundwater` | `accounting/views.py:238` | `zone_consumptive_balance` | `parcels_parcelledger` | 142.14 | 142.14 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-040` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:232` | Precip (AF) | `row.precip` | `accounting/views.py:239` | `zone_consumptive_balance` | `accounting_calculationrun` | 110.56 | 110.56 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-041` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:235` | Supplies (AF) | `row.supply_total` | `accounting/views.py:240` | `zone_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 1423.63 | 1423.63 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-042` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:238` | Net (AF) | `row.net_vs_supply` | `accounting/views.py:241` | `zone_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 233.88 | 233.88 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-043` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:242` | Allocation (AF) | `row.allocation` | `accounting/views.py:209` | `— (model aggregate)` | `accounting_allocationplan` | 750.32 | 750.32 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-044` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:245` | Carried fwd (AF) | `row.carryover` | `accounting/views.py:218` | `zone_carryover` | `accounting_allocationcarryover` | 303.40 | 303.40 | MATCH | MATCH | Independence: restatement. Looked up by water year, which is named for the calendar year the year ENDS in. This zone's rows for that label sum to the figure shown. |
| `FIG-accounting-045` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:248` | Remaining (AF) | `row.remaining` | `accounting/views.py:223` | `available_with_carryover` | `accounting_allocationplan, accounting_allocationcarryover, accounting_calculationrun` | -136.03 | -136.03 | MATCH | MATCH | Independence: restatement. Allocation plus carry-over, minus gross evapotranspiration. The one figure on the pinned screen that lands negative — this zone is over its budget. |

### What section 1 found

**All 23 figures agree with the rows behind them, to the cent.** The dashboard is
telling the truth about its own database. That is worth saying plainly, because
it is the baseline every later change in this milestone will be measured against,
and because it was not known before this document existed.

Four things the reconciliation turned up that a matching column does not show.

**1. The three guards that would have made this section hard cannot currently
fire.** Each was a real risk and each is inert on this data:

| Guard | Why it mattered | State on this data |
|---|---|---|
| The gross-estimate suppression | Without it every supply figure would double-count a month that has both an estimate and a calculated value | **0 estimate rows** exist in this period, so nothing is suppressed |
| One parcel in two accounts | The panel adds the accounts up one at a time, so a shared parcel would be counted twice | **0 parcels** belong to two active accounts |
| Parcels outside any account | The panel counts only parcels attached to an active account | **all 76** parcels are attached to one |

The recomputation states each rule anyway, so the section stays correct the day
the data grows one. But no reader should take these three as *tested*.

**2. The zone table does not add up to the panel above it, and cannot.** Add the
Supplies column of the zone table and you get **31,223.56 AF**. The panel at the
top of the same page says **17,458.35 AF**. The gap is not an error in either
number: 59 of the 76 parcels sit in two zones at once — a groundwater agency's
area and a surface-water district's service area — so the zone table counts them
twice by design. The page never says this. A visitor who adds the column up gets
a figure 79% too high and has no way to find out why.

**3. One figure on this screen is worked out in the page's own code rather than
in any shared calculation.** The account Allocation column divides each zone's
budget by how many parcels it holds and gives each account its share.
Reproducing it meant transcribing that division, because there is no function to
read it out of. It matches — but it is the only figure on the dashboard with no
shared implementation behind it, so it is the one no other screen can be checked
against, and the one most likely to drift if the rule is ever restated somewhere
else.

**4. Allocations are very large relative to use, and the pinned zone is
nonetheless over budget.** Ashvale Orchards is charged 4,589.61 AF of consumptive
use against a 19,101.42 AF allocation, leaving 14,511.81 AF — a budget three
quarters unused. Halvern Irrigation-Urban GSA, on the other hand, ends the year at
**−136.03 AF**. Both are correct arithmetic on the numbers seeded. Phase 136 both
re-sizes those allocations and changes what "Remaining" subtracts, so these two
rows are the before-picture that change gets judged against.

---


---

## Section 2 — The parcel detail pane (20 figures)

**Screens.** `/parcels/32/` and `/parcels/17/`. This is the pane a person lands on
when they click a use area in the parcel workspace, and the same body is served
on the parcel's own page. It is the densest single screen in the platform: three
summary cards, a three-way split of the supplies that met the crop's demand, a
supply-versus-use table, a residual with a coloured badge, the parcel's own
attributes, its wells, and its ten most recent ledger rows.

**Pinned instances, and why there are two.** This pane renders once per parcel,
76 times over. One pin would have been enough to check the arithmetic and not
enough to check the thing this section exists to record, because the pane's two
balances agree on some parcels and disagree on others. So two parcels are pinned,
both in the drier water year:

* **`MER-APN-032`, Ashvale Orchards Inc.** The disagreeing case. The card at the
  top of the pane reads a surplus of **174.13 AF**; the residual four inches
  below it reads **0.00 AF** with a grey *Balanced* badge.
* **`MER-APN-017`, Saddlebow Ag Holdings.** The agreeing case. Both numbers read
  **132.90 AF** and the badge reads *Surplus*.

Both pages were captured signed in, at commit `9f9e27b2543516a95cdc15743070e3746d04ddbe`
(tag `v2.15`), 2026-09-05, and both answered 200. The saved pages are
`audit/figure_ledger/rendered/parcel-detail-disagree-mer-apn-032.html` and
`parcel-detail-agree-mer-apn-017.html`, with their sizes and content fingerprints
in `manifest-b.json` beside them.

**The pane has no year selector, and adding one to the address does nothing.**
The parcel page builds its figures from the parcel alone and never reads the rest
of the request, so `?period=1` and `?period=2` are ignored. That was observed
rather than deduced: `/parcels/32/`, `/parcels/32/?period=1` and
`/parcels/32/?period=2` were all captured, and the three saved pages differ only
in the one-time security token each request carries. The year each pane shows is
chosen for the reader, by a rule in the page's own code: the most recent year in
which that parcel has any activity other than an allocation. On this data that
sends **70 of the 76** parcels to WY 2025-2026 and the remaining **6** to
WY 2024-2025. Both pinned parcels land on WY 2025-2026, and the pane says so, in
small grey type at the top right of the water balance card.

**Recomputation.** `audit/figure_ledger/sql/parcel_detail_pane.sql`, run on the
host with `bash audit/figure_ledger/run_sql.sh`. It names tables and columns only.
Every whole-column count below was measured by that file, for both years
separately, and every count in this section carries the year it belongs to.

---

### The ledger, pinned to `MER-APN-032` (the disagreeing case)

| `id` | `screen` | `site` | `label` | `context_var` | `view` | `service` | `raw_tables` | `rendered` | `recomputed` | `delta` | `verdict` | `notes` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `FIG-parcels-001` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:39` | Consumptive use (ET) | `consumptive_balance.consumptive_use_gross` | `parcels/views.py:168` | `parcel_consumptive_balance` | `accounting_calculationrun` | 591.28 | 591.28 | MATCH | MATCH | Independence: restatement. Gross satellite-estimated evapotranspiration, summed over the parcel's twelve monthly calculation runs in the year. |
| `FIG-parcels-002` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:44` | Total supplies | `consumptive_balance.supply_total` | `parcels/views.py:168` | `parcel_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 765.41 | 765.41 | MATCH | MATCH | Independence: restatement. Canal deliveries plus pumped groundwater plus effective rainfall. |
| `FIG-parcels-003` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:49` | Supplies − consumptive use | `consumptive_balance.net_vs_supply` | `parcels/views.py:168` | `parcel_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 174.13 | 174.13 | MATCH | ISS-148 | Independence: restatement. **The arithmetic of this figure is right to the cent. The issue is that it contradicts `FIG-parcels-015` on the same screen: this card says 174.13 AF of water arrived and was not consumed, and the residual below says the books close at 0.00 AF.** The difference is exactly the Recharge term, `FIG-parcels-011`, also 174.13 AF: the same water counted as an unused supply by one balance and as an output by the other. Reproduced whole-column as `CHK-parcels-031` and `CHK-parcels-037`. |
| `FIG-parcels-004` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:57` | Net consumptive demand of … AF | `consumptive_balance.consumptive_use_net` | `parcels/views.py:168` | `parcel_consumptive_balance` | `accounting_calculationrun` | 545.17 | 545.17 | MATCH | MATCH | Independence: restatement. Consumptive use after effective rainfall, stored per run rather than derived here. |
| `FIG-parcels-005` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:63` | Surface water | `consumptive_balance.supplies.surface` | `parcels/views.py:168` | `parcel_consumptive_balance` | `parcels_parcelledger` | 719.30 | 719.30 | MATCH | MATCH | Independence: restatement. Magnitude of the delivery rows, which the platform stores as negative numbers by its own convention. |
| `FIG-parcels-006` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:68` | Groundwater | `consumptive_balance.supplies.groundwater` | `parcels/views.py:168` | `parcel_consumptive_balance` | `parcels_parcelledger` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. A real zero, not a suppression: this parcel has twelve calculation runs in the year and no metered or calculated groundwater row in it. Absolute value OF THE SUM of the negative non-delivery rows, not the sum of absolute values; transcribed as written. |
| `FIG-parcels-007` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:73` | Precipitation | `consumptive_balance.supplies.precip` | `parcels/views.py:168` | `parcel_consumptive_balance` | `accounting_calculationrun` | 46.11 | 46.11 | MATCH | MATCH | Independence: restatement. Effective rainfall, from the calculation runs rather than the ledger. |
| `FIG-parcels-008` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:90` | Supplies: Surface | `mass_balance.inputs.surface` | `parcels/views.py:169` | `parcel_mass_balance` | `parcels_parcelledger` | 719.30 | 719.30 | MATCH | MATCH | Independence: restatement. The same quantity as `FIG-parcels-005`, printed a second time forty lines lower under a different heading. |
| `FIG-parcels-009` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:92` | Uses: ET | `mass_balance.outputs.et` | `parcels/views.py:169` | `parcel_mass_balance` | `accounting_calculationrun` | 591.28 | 591.28 | MATCH | MATCH | Independence: restatement. The same quantity as `FIG-parcels-001`. |
| `FIG-parcels-010` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:96` | Supplies: Precip | `mass_balance.inputs.precip` | `parcels/views.py:169` | `parcel_mass_balance` | `accounting_calculationrun` | 46.11 | 46.11 | MATCH | MATCH | Independence: restatement. The same quantity as `FIG-parcels-007`. |
| `FIG-parcels-011` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:98` | Uses: Recharge | `mass_balance.outputs.recharge` | `parcels/views.py:169` | `parcel_mass_balance` | `accounting_calculationrun` | 174.13 | 174.13 | MATCH | MATCH | Independence: restatement, and the one figure on this pane not read from a column. It is read out of a stored record of the calculation itself: the step called `clamp_floor`, field `incidental_recharge_af`. This is the term that carries the whole gap between the pane's two balances. |
| `FIG-parcels-012` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:102` | Supplies: Groundwater pumped | `mass_balance.inputs.gw_recovered` | `parcels/views.py:169` | `parcel_mass_balance` | `parcels_parcelledger` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. The same quantity as `FIG-parcels-006`, and the platform's own code says so. |
| `FIG-parcels-013` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:104` | Uses: Runoff | `mass_balance.outputs.runoff` | `parcels/views.py:169` | `parcel_mass_balance` | `n/a (no table)` | 0.00 | 0.00 | EXPLAINED | EXPLAINED | **This figure has no data behind it.** It is a fixed zero written into the code, a named placeholder for a term the platform does not model, and it will read 0.00 on every parcel in every year no matter what the rows say. The recomputation writes the same fixed zero, so the two agree for a reason that is not a measurement. Recorded as `EXPLAINED` rather than `MATCH` so nobody reads the agreement as evidence. |
| `FIG-parcels-014` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:109` | Uses: Net Banked/Drawn (credits) | `mass_balance.outputs.delta_storage` | `parcels/views.py:169` | `parcel_mass_balance` | `accounting_calculationrun` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. Credit banked less credit drawn. Zero here, and zero on all 152 parcel-years measured (`CHK-parcels-053`), so this term is carrying nothing anywhere on this data. |
| `FIG-parcels-015` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:115` | Residual | `mass_balance.residual_af` | `parcels/views.py:169` | `parcel_mass_balance` | `parcels_parcelledger, accounting_calculationrun` | 0.00 | 0.00 | MATCH | ISS-148 | Independence: restatement. **Right to the cent, and it contradicts `FIG-parcels-003` above it.** Recomputed at full precision the residual is −0.000117 AF, which prints as 0.00 and sits inside the 0.01 AF band the platform calls Balanced. So the reader sees 174.13 AF of surplus in one place and a closed book in another, three inches apart, with nothing on the page connecting them. |
| `FIG-parcels-016` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:178` | surface (in the "ET has not been computed" notice) | `consumptive_balance.supplies.surface` | `parcels/views.py:168` | `parcel_consumptive_balance` | `parcels_parcelledger` | not rendered | 719.30 | NO VALUE | UNVERIFIED | **This figure could not be checked, because nothing on this platform can currently display it.** It sits in the branch shown only when a parcel has no calculation runs for the year, and every one of the 76 parcels has runs in both years (`CHK-parcels-070`, `CHK-parcels-071`, both zero). The value it would print is recomputed and recorded, so the day the branch becomes reachable the number is already on file. |
| `FIG-parcels-017` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:179` | groundwater (in the "ET has not been computed" notice) | `consumptive_balance.supplies.groundwater` | `parcels/views.py:168` | `parcel_consumptive_balance` | `parcels_parcelledger` | not rendered | 0.00 | NO VALUE | UNVERIFIED | Same branch, same reason as `FIG-parcels-016`. |
| `FIG-parcels-018` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:216` | Area (Acres) | `ef.value` | `parcels/views.py:172` | `— (model field, read at parcels/views.py:157)` | `parcels_parcel` | 154.69 | 154.69 | MATCH | MATCH | Independence: restatement of a stored value, which is the weakest kind of check there is and is stated as such. The pane loops over five editable fields; Area is the only one typed as a number, so it is the only one that reaches the two-decimal display filter. |
| `FIG-parcels-019` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:266` | … fraction (Related wells) | `wip.fraction` | `parcels/views.py:165` | `— (model field, fetched at parcels/views.py:106)` | `wells_wellirrigatedparcel` | 1.00 | 1.00 | MATCH | MATCH | Independence: restatement of a stored value. The share of this well's pumping attributed to this parcel. One well is linked here, so 1.00 means all of it. Renders only while the wells module is switched on, which it is on this deployment (observed: the Related wells card is in the captured page). |
| `FIG-parcels-020` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:306` | Amount (AF), first row of Recent ledger entries | `entry.amount_acre_feet` | `parcels/views.py:166` | `— (model field, fetched at parcels/views.py:107)` | `parcels_parcelledger` | -75.23 | -75.23 | MATCH | MATCH | Independence: restatement of a stored value. The most recent of the parcel's ten latest rows, a canal delivery dated 15 September 2026. Note this list is NOT scoped to the year the balance card above it is showing, so the two halves of the pane can be describing different spans of time. |

### The same twenty figures, pinned to `MER-APN-017` (the agreeing case)

This table is a comparison, not a second set of ledger rows: the ledger
carries one row per figure and that is the table above. The identifiers
here are references back to it.

The `site`, `context_var`, `view`, `service` and `raw_tables` columns are the same
line of the same template rendered for a different parcel, so they are identical
to the table above and are not repeated. What changes is the numbers.

| `id` | `label` | `rendered` | `recomputed` | `delta` | `verdict` | `notes` |
|---|---|---|---|---|---|---|
| FIG-parcels-001 | Consumptive use (ET) | 263.07 | 263.07 | MATCH | MATCH |  |
| FIG-parcels-002 | Total supplies | 395.97 | 395.97 | MATCH | MATCH |  |
| FIG-parcels-003 | Supplies − consumptive use | 132.90 | 132.90 | MATCH | MATCH | Agrees with `FIG-parcels-015` below, exactly. This parcel banked no incidental recharge in the year, so the two balances have nothing to differ by. |
| FIG-parcels-004 | Net consumptive demand | 235.43 | 235.43 | MATCH | MATCH |  |
| FIG-parcels-005 | Surface water | 0.00 | 0.00 | MATCH | MATCH | A real zero: this parcel took no canal delivery in the year and met its demand by pumping. |
| FIG-parcels-006 | Groundwater | 368.34 | 368.34 | MATCH | MATCH |  |
| FIG-parcels-007 | Precipitation | 27.64 | 27.64 | MATCH | MATCH |  |
| FIG-parcels-008 | Supplies: Surface | 0.00 | 0.00 | MATCH | MATCH |  |
| FIG-parcels-009 | Uses: ET | 263.07 | 263.07 | MATCH | MATCH |  |
| FIG-parcels-010 | Supplies: Precip | 27.64 | 27.64 | MATCH | MATCH |  |
| FIG-parcels-011 | Uses: Recharge | 0.00 | 0.00 | MATCH | MATCH | Zero, which is why this parcel's two balances agree. |
| FIG-parcels-012 | Supplies: Groundwater pumped | 368.34 | 368.34 | MATCH | MATCH |  |
| FIG-parcels-013 | Uses: Runoff | 0.00 | 0.00 | EXPLAINED | EXPLAINED | The fixed zero again. Same reason as the table above. |
| FIG-parcels-014 | Uses: Net Banked/Drawn (credits) | 0.00 | 0.00 | MATCH | MATCH |  |
| FIG-parcels-015 | Residual | 132.90 | 132.90 | MATCH | MATCH | Equal to `FIG-parcels-003`. The badge beside it reads *Surplus* in orange, and the page prints a sentence saying more water is recorded arriving here than the parcel's uses account for. That is the pane behaving as designed. |
| FIG-parcels-016 | surface (ET-not-computed notice) | not rendered | 0.00 | NO VALUE | UNVERIFIED | Branch unreachable, as above. |
| FIG-parcels-017 | groundwater (ET-not-computed notice) | not rendered | 368.34 | NO VALUE | UNVERIFIED | Branch unreachable, as above. |
| FIG-parcels-018 | Area (Acres) | 89.84 | 89.84 | MATCH | MATCH |  |
| FIG-parcels-019 | … fraction (Related wells) | 1.00 | 1.00 | MATCH | MATCH |  |
| FIG-parcels-020 | Amount (AF), first ledger row | -47.48 | -47.48 | MATCH | MATCH | A meter reading dated 15 September 2026. |

---

### What section 2 found

**Eighteen of the twenty figures agree with the rows behind them, to the cent, on
both pinned parcels. Two could not be checked at all.** Nothing on this pane is
computing a wrong number. That is worth stating plainly before anything else,
because the rest of this section is about a screen that is arithmetically correct
and still tells a reader two incompatible things.

Six things the reconciliation turned up that a matching column does not show.

#### 1. The pane states two balances that disagree, and the count depends on which disagreement you mean

Both numbers were measured here, over all 76 parcels, in both years, by
`audit/figure_ledger/sql/parcel_detail_pane.sql`. They are not carried forward
from anywhere.

| What was counted | WY 2024-2025 (wet) | WY 2025-2026 (dry) | Check |
|---|---|---|---|
| Parcels where the card and the residual disagree on sign | **32 of 76** | **24 of 76** | `CHK-parcels-030`, `CHK-parcels-031` |
| Parcels printing a non-zero surplus beside a residual that prints 0.00 | **47 of 76** | **49 of 76** | `CHK-parcels-036`, `CHK-parcels-037` |
| Parcels where the two printed numbers differ at all | **59 of 76** | **50 of 76** | `CHK-parcels-034`, `CHK-parcels-035` |

The first row reproduces the figure this phase inherited, exactly, in both years.
**The second row is the one a reader would notice.** The sign disagreement is real
but it is sub-cent: on all 32 of those parcels in the wet year and all 24 in the
dry year, the residual is a few ten-thousandths of an acre-foot below zero, prints
as 0.00, and falls inside the band the platform calls *Balanced*, so the badge
reads *Balanced* on every single one (`CHK-parcels-042`, `CHK-parcels-043`). No
reader has ever seen that sign flip.

What a reader does see is the pair of numbers. On the pinned parcel the card says
**174.13 AF** of supplies over and above consumptive use, and the residual three
inches below says **0.00 AF, Balanced**. The largest such pair on this data is
**177.47 AF beside 0.00** in the dry year and **168.31 AF beside 0.00** in the wet
one (`CHK-parcels-044`, `CHK-parcels-045`). That happens on about two thirds of
parcels in each year, not a third.

**Both numbers belong in the record, and each needs its year said out loud.** The
plan this section inherited carried "32 of 76" with no year attached, and that is
how the wet year's figure came to be read as the whole picture.

#### 2. The gap between the two balances is one term, and it is the same term every time

Working from the two definitions rather than from either service, the residual is
always the card figure minus the recharge term minus net banked credit. That
relation was checked against all 152 parcel-years and holds on every one, with no
violations (`CHK-parcels-051`). Net banked credit is zero on all 152
(`CHK-parcels-053`), so the whole gap, wherever there is one, is the recharge
term alone, on all 109 parcel-years where recharge is non-zero (`CHK-parcels-052`,
`CHK-parcels-054`).

In plain terms: water delivered to a parcel beyond what the crop consumed is
booked as having soaked into the aquifer. One balance treats that water as
supply the parcel did not use, and shows a surplus. The other treats it as water
that left the parcel, and closes. The page prints both, with no sentence
connecting them. Diagnosing this is ISS-148's job and Phase 137's; this ledger
records it.

#### 3. Two of the twenty figures cannot be reached at all

`FIG-parcels-016` and `FIG-parcels-017` sit in the notice the pane shows when a
parcel has no computed evapotranspiration yet. Every one of the 76 parcels has
calculation runs in both years (`CHK-parcels-070`, `CHK-parcels-071`), so that
notice never renders and there is no rendered value to compare anything against.
They are recorded `UNVERIFIED`, with the value they would have printed recomputed
and stored beside them. **Nobody should read the eighteen matches as nineteen or
twenty.**

#### 4. One figure on the pane is a placeholder, not a measurement

Runoff, `FIG-parcels-013`, is a fixed zero written into the platform's code, a
named term for something it does not model. It reads 0.00 on every parcel in
every year regardless of the data. The recomputation writes the same fixed zero,
so the two agree, and the agreement means nothing. It is recorded `EXPLAINED`
rather than `MATCH` for exactly that reason. A reader looking at the
supply-versus-use table sees Runoff sitting in the Uses column beside ET and
Recharge, formatted identically, with nothing to tell them one of the three is
not a number about this parcel.

#### 5. The pane cannot be pointed at a year, and the two halves of it can describe different years

The parcel page ignores a year in the address. It picks a year for the reader,
and different parcels get different years: 70 land on WY 2025-2026 and 6 on
WY 2024-2025 (`CHK-parcels-080`, `CHK-parcels-081`). That was confirmed by
capturing `/parcels/32/` three ways and comparing the saved bytes, not by reading
the code.

Two consequences worth recording. A person cannot compare a parcel across the two
years from this screen at all. And the Recent ledger entries card at the bottom
right is not scoped to the year the balance card at the top is showing, so a pane
whose balance describes WY 2024-2025 can list rows from WY 2025-2026 underneath
it, with no date range printed on either.

#### 6. The double-counting guard is inert here too, exactly as it was on the dashboard

The rule that stops a month being counted twice, once as a satellite estimate and
once as a calculated figure, is written into the recomputation and cannot fire:
there are zero satellite-estimate rows in the entire database (`CHK-parcels-060`).
This is the same guard section 1 found inert on the accounting dashboard, and the
same caution applies. It is stated so the section stays correct the day the data
grows one, but no reader should take it as tested.


---

## Section 3 — The money layer (31 figures)

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

Four rows carry a verdict of the form `MATCH · ISS-155`. That is not a hedge.
The number rendered agrees with the independent recomputation to the cent, so
the arithmetic is right, and a separate issue is raised against the words
printed beside it. Both halves are true and a reader needs both.

The two pinned allocations are named here by their zone, water type and year,
which identify the row uniquely; `accounting_detail.sql` and
`extract_section_a.py` carry the stored names character for character, because
they have to match.

---

### The ledger

| `id` | `screen` | `site` | `label` | `context_var` | `view` | `service` | `raw_tables` | `rendered` | `recomputed` | `delta` | `verdict` | `notes` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `FIG-accounting-001` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:38` | acres | `parcel.area_acres` | `accounting/views.py:1231` | `— (model field)` | `parcels_parcel` | 149.73 | 149.73 | MATCH | MATCH | Independence: restatement. Read straight off the parcel row the view fetched. It is not an independent quantity, but it is load-bearing, because every acre-foot figure on this page is this number times a millimetre of rainfall or evaporation. |
| `FIG-accounting-002` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:46` | Billable groundwater | `run.final_af` | `accounting/views.py:1232` | `— (model field, written by accounting/management/commands/run_calculations.py:272)` | `accounting_calculationrun` | 27.9945 | 27.9945 | MATCH | MATCH | Independence: different identity. Also checked against the magnitude of the `calculated` ledger row for the same parcel-month, which is what the page's own result card claims it equals (agrees to 0.0000), and against the last step of the waterfall, likewise 0.0000. |
| `FIG-accounting-003` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:79` | In (AF) | `step.input_af` | `accounting/views.py:1266` | `— (read out of the stored breakdown)` | `accounting_calculationrun` | 0.0000 | 0.0000 | MATCH | MATCH | Independence: restatement, plus a whole-table identity. Pinned to step 1, which starts at zero. Every one of the five steps was also checked for continuity, each step's In against the step above it's Out, and none breaks. |
| `FIG-accounting-004` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:80` | Out (AF) | `step.output_af` | `accounting/views.py:1267` | `— (read out of the stored breakdown)` | `accounting_calculationrun, datasync_openetcache, parcels_parcel` | 39.8491 | 39.8491 | MATCH | MATCH | Independence: **different identity**. Rebuilt from the raw satellite reading, 81.119346 mm of evapotranspiration over 149.73 acres divided by 304.8, without reading the stored figure at all. The recomputation could have disagreed and did not. |
| `FIG-accounting-005` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:94` | Deposited this month | `run.banked_af` | `accounting/views.py:1232` | `— (model field)` | `accounting_calculationrun` | *(not rendered)* | 0.0000 | NO VALUE | UNVERIFIED | The whole banked-water block sits behind a condition no row in this database satisfies: **0 of 1,824 calculation runs** carry a non-zero deposit or draw. Nothing was on screen to read. The stored value is 0.0000, and that is not the same claim. |
| `FIG-accounting-006` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:98` | Drawn down this month | `run.drawn_af` | `accounting/views.py:1232` | `— (model field)` | `accounting_calculationrun` | *(not rendered)* | 0.0000 | NO VALUE | UNVERIFIED | Same block, same reason. |
| `FIG-accounting-007` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:114` | Drawn (AF) | `draw.amount_af` | `accounting/views.py:1273` | `— (queryset)` | `accounting_watercreditdraw` | *(not rendered)* | *(no rows)* | NO VALUE | UNVERIFIED | Nested one level deeper still: the draws table needs a `WaterCreditDraw` row and **there are none**, though five water-credit rows are held. |
| `FIG-accounting-008` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:132` | Final billable groundwater | `run.final_af` | `accounting/views.py:1232` | `— (model field)` | `accounting_calculationrun` | 27.9945 | 27.9945 | MATCH | MATCH | Independence: different identity, as `FIG-accounting-002`. The page states this figure twice, at the top and at the foot; both render the same value, which is a thing the page could get wrong and does not. |
| `FIG-accounting-009` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:11` | Supplies | `balance.supply_total` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun, accounting_wateraccountparcel` | 5,921.09 | 5921.09 | MATCH | MATCH | Independence: restatement. The gross-estimate suppression is stated as its own predicate in the recomputation; it removes 0 rows here, for the reason in finding 2. |
| `FIG-accounting-010` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:16` | Consumptive use | `balance.consumptive_use_gross` | `accounting/views.py:630` | `account_consumptive_balance` | `accounting_calculationrun` | 4,589.61 | 4589.61 | MATCH | MATCH | Independence: **different identity**. Rebuilt over all 216 of this account's parcel-months from the raw satellite readings and the parcels' acreage, never touching the stored evapotranspiration column. Agrees to the cent. |
| `FIG-accounting-011` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:21` | Balance | `balance.net_vs_supply` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 1,331.48 | 1331.48 | MATCH | MATCH | Independence: restatement. Supplies minus consumptive use, both above. |
| `FIG-accounting-012` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:25` | Surface | `balance.supplies.surface` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger` | 5,500.97 | 5500.97 | MATCH | MATCH | Independence: restatement. Magnitude of the canal-delivery rows, which the platform stores as negative numbers by its own production convention. |
| `FIG-accounting-013` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:26` | Groundwater | `balance.supplies.groundwater` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. A real zero, not a suppression: 216 calculation runs sit behind this account in the period and not one groundwater or meter row. |
| `FIG-accounting-014` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:27` | Rain | `balance.supplies.precip` | `accounting/views.py:630` | `account_consumptive_balance` | `accounting_calculationrun` | 420.12 | 420.12 | MATCH | MATCH | Independence: **different identity**. Rebuilt over the same 216 parcel-months from raw rainfall and evapotranspiration through the published USDA-SCS TR-21 formula, transcribed into the recomputation with its source lines. Agrees to the cent. |
| `FIG-accounting-015` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:56` | Consumptive Use | `pb.consumptive_use_gross` | `accounting/views.py:645` | `parcel_consumptive_balance` | `accounting_calculationrun` | 177.23 | 177.23 | MATCH | MATCH | Independence: restatement. Pinned to MER-APN-021. The whole column was also summed and held against the panel above it; see `FIG-accounting-019`'s note. |
| `FIG-accounting-016` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:59` | Surface | `pb.surface` | `accounting/views.py:647` | `parcel_consumptive_balance` | `parcels_parcelledger` | 210.17 | 210.17 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-017` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:62` | Groundwater | `pb.groundwater` | `accounting/views.py:648` | `parcel_consumptive_balance` | `parcels_parcelledger` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-018` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:65` | Precip | `pb.precip` | `accounting/views.py:649` | `parcel_consumptive_balance` | `accounting_calculationrun` | 17.92 | 17.92 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-019` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:68` | Supplies | `pb.supply_total` | `accounting/views.py:650` | `parcel_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 228.09 | 228.09 | MATCH | MATCH | Independence: restatement, plus a **different identity** the code could fail. The per-parcel table is built one parcel at a time while the panel above it is built in a single pass over all eighteen; the two agree only if the gross-estimate suppression really is per-parcel. Summed whole-column, all four supply and use columns land on the panel exactly: difference 0.00. |
| `FIG-accounting-020` | `/accounting/accounts/78/?period=2` | `templates/accounting/partials/_account_balances.html:71` | Net | `pb.net_vs_supply` | `accounting/views.py:651` | `parcel_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 50.87 | 50.87 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-021` | `/accounting/allocations/?period=2` | `templates/accounting/partials/_allocations_list_results.html:34` | Allocation (AF) | `alloc.allocation_acre_feet` | `accounting/views.py:478` | `— (model field; queryset built at accounting/views.py:454)` | `accounting_allocationplan` | 750.32 | 750.32 | MATCH | MATCH | Independence: restatement. The same 750.32 the dashboard's zone table shows for this zone, on a second screen. |
| `FIG-accounting-022` | `/accounting/allocations/?period=2` | `templates/accounting/partials/_allocations_list_results.html:50` | All 8 allocations | `allocation_total` | `accounting/views.py:474` | `— (queryset aggregate)` | `accounting_allocationplan` | 159,671.46 | 159671.46 | MATCH | MATCH · ISS-156 | Independence: restatement. The sum is right. It adds **148,500.00 AF of surface-water allocation to 11,171.46 AF of groundwater allocation** and prints one number in acre-feet, and no agency manages that quantity. See finding 4. |
| `FIG-accounting-046` | `/accounting/ledger/?period=2` | `templates/accounting/partials/_ledger_list_results.html:77` | Amount (AF) | `entry.amount_acre_feet` | `accounting/views.py:1009` | `— (model field)` | `parcels_parcelledger` | -8.56 | -8.56 | MATCH | MATCH | Independence: restatement, including the view's ordering. Pinned to the first row on screen, a metered groundwater reading on MER-APN-065 dated 15 September 2026, reproduced by restating the sort rather than by naming a row and hoping. |
| `FIG-accounting-047` | `/accounting/ledger/?period=2` | `templates/accounting/partials/_ledger_list_results.html:114` | net AF | `ledger_total_net` | `accounting/views.py:1011` | `— (queryset aggregate)` | `parcels_parcelledger` | -1,504.32 | -1504.32 | MATCH | MATCH · ISS-155 | Independence: restatement. Arithmetic correct over all 1,130 rows in the period. But this figure and the dashboard's Balance describe the same 76 parcels in the same water year and **disagree in sign**. See finding 3. |
| `FIG-accounting-048` | `/accounting/ledger/?period=2` | `templates/accounting/partials/_ledger_list_results.html:117` | credits | `ledger_total_credits` | `accounting/views.py:1012` | `— (queryset aggregate)` | `parcels_parcelledger` | 14,280.77 | 14280.77 | MATCH | MATCH · ISS-155 | Independence: restatement, plus the footer's own identity: credits plus debits equals net, difference 0.00. The 14,280.77 is 13,819.63 AF of allocation entries plus 461.14 AF of recharge. **Not one drop of it is water delivered to anybody.** Finding 3. |
| `FIG-accounting-049` | `/accounting/ledger/?period=2` | `templates/accounting/partials/_ledger_list_results.html:118` | debits | `ledger_total_debits` | `accounting/views.py:1013` | `— (queryset aggregate)` | `parcels_parcelledger` | -15,785.09 | -15785.09 | MATCH | MATCH · ISS-155 | Independence: restatement. The -15,785.09 is -11,407.71 AF of canal deliveries plus -4,377.38 AF of pumping, and the dashboard calls **both of those supplies**, in those exact figures. Finding 3. |
| `FIG-accounting-050` | `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `templates/accounting/partials/_methodology_preview.html:22` | Billable groundwater | `final_af` | `accounting/views.py:1559` | `evaluate_chain` | `accounting_calculationplan, accounting_calculationstep, datasync_openetcache, parcels_parcel` | 27.9945 | 27.9945 | MATCH | MATCH | Independence: **different identity**. This screen computes fresh and stores nothing, so there is no row of its own to check it against; it is held instead against the persisted calculation run for the same parcel-month, which was written by a different code path on a different day. The two agree exactly. |
| `FIG-accounting-051` | `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `templates/accounting/partials/_methodology_preview.html:52` | In (AF) | `step.input_af` | `accounting/views.py:1563` | `evaluate_chain` | `accounting_calculationstep, datasync_openetcache` | 0.0000 | 0.0000 | MATCH | MATCH | Independence: different identity, as above. Pinned to step 1. |
| `FIG-accounting-052` | `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `templates/accounting/partials/_methodology_preview.html:53` | Out (AF) | `step.output_af` | `accounting/views.py:1564` | `evaluate_chain` | `accounting_calculationstep, datasync_openetcache, parcels_parcel` | 39.8491 | 39.8491 | MATCH | MATCH | Independence: **different identity**. Same raw-satellite rebuild as `FIG-accounting-004`. The live preview reproduces all five stored steps identically, which is the thing this screen exists to promise and the thing nothing else tests. |
| `FIG-accounting-053` | `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `templates/accounting/partials/_methodology_preview.html:60` | final … AF | `final_af` | `accounting/views.py:1559` | `evaluate_chain` | `accounting_calculationplan, accounting_calculationstep` | *(not rendered)* | *(unreachable)* | NO VALUE | UNVERIFIED | This is the fallback sentence shown when the saved method produces no steps at all. **All 5 steps on the active method are enabled**, so the branch cannot be reached without turning every one of them off, a configuration change this phase is not permitted to make. |
| `FIG-accounting-054` | `/accounting/reporting-periods/2/` | `templates/accounting/period_detail.html:136` | Allocation (AF) | `alloc.allocation_acre_feet` | `accounting/views.py:404` | `— (model field; queryset built at accounting/views.py:397)` | `accounting_allocationplan` | 9689.40 | 9689.40 | MATCH | MATCH | Independence: restatement. The same database row the allocations list shows as **9,689.40**, printed here as **9689.40** with no thousands separator. See finding 5. |

**Second instance, the wet year.** `/accounting/accounts/78/?period=1`, WY
2024-2025, captured so a later plan can check the same twelve sites against a
different year without re-deriving the pin: Supplies **5,966.10**, Consumptive
use **4,667.86**, Balance **1,298.24**; Surface **5,177.09**, Groundwater
**0.00**, Rain **789.01**. First per-parcel row, MER-APN-021: 180.32 · 197.25 ·
0.00 · 33.32 · 230.57 · 50.25. These are recorded, not reconciled. The
recomputation in this section is pinned to the dry year.

---

### What section 3 found

**Twenty-seven of the thirty-one figures rendered a number, and all twenty-seven
agree with the rows behind them, to the cent.** Four never appeared on screen at
all, and are recorded as unverified rather than assumed. Of the twenty-seven that
matched, five were rebuilt from a genuinely different starting point, from the
raw satellite and rainfall readings through the published formula rather than
from the platform's own stored answer, and those five could have disagreed. They
did not.

That is the good news, and it is worth stating plainly before the rest, because
the rest is about what the numbers are called rather than whether they are right.

#### 1. The calculation the platform bills on can be rebuilt from scratch, and it holds

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

#### 2. Three guards on this pane cannot currently fire, and one has never had anything to bite on

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

#### 3. Two screens state a year's balance for the same parcels and disagree about the sign

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

`FIG-accounting-047`, `048` and `049` each carry this. The arithmetic in all
three is correct.

#### 4. The allocations footer adds surface water to groundwater

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

#### 5. Two reproducibility problems that belong to the screens, not to this audit

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

#### 6. What could not be checked, and why

Four of the thirty-one sites never rendered. Naming them:

- **`FIG-accounting-005`, `006`, `007`.** The banked-water block on the
  calculation-run page, and the credit-draw table nested inside it. No calculation
  run in this database has a non-zero deposit or draw, and no draw rows exist, so
  the block is unreachable with this demonstration data. Five water-credit rows
  are held, which is why the feature is not simply dead code.
- **`FIG-accounting-053`.** The methodology preview's fallback line, shown when
  the saved method yields no steps. All five steps on the active method are
  enabled, and reaching that branch would mean turning them off, which is a
  configuration change this phase may not make.

For each of the four, the value stored in the database is recorded in the
recomputation column, and the rendered column is empty. Those are different
claims and the ledger keeps them apart: the database holding a zero is not the
same as the screen having shown one.

---

### Cross-screen agreement, observed

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


---

## Section 4 — Surface water and state reporting (14 figures)

Six templates, 14 figures: the water rights list and a right's detail page, a
diversion point's detail page and its records table, the shared-supply check, and
the CalWATRS transcription worksheet. They are grouped together because the same
stored rows appear on both an operator's screen and the worksheet a person copies
into the state's portal, so each row is checked once against both.

**Screens.** Each is captured under `audit/figure_ledger/rendered/`, with its size
and content fingerprint in `manifest-c.json`.

| Screen | Figures | What is pinned |
|---|---|---|
| `/surface/diversion/9/` | `FIG-surface-001` to `005` | MER-POD-011-DEMO Snelling Re-Diversion. Records row pinned to **May 2026**. |
| `/surface/rights/7/` | `FIG-surface-007` to `009` | MER-WR-010-DEMO, Halvern Hydroelectric Co. |
| `/surface/rights/` | `FIG-surface-006` | First row by right identifier: MER-WR-004-DEMO. |
| `/reporting/reports/4/calwatrs-worksheet/` | `FIG-reporting-001`, `002` | Submission 4, CalWATRS To Storage, WY 2025-2026. First block, first row. |
| `/reporting/reports/shared-supply-check/?period=2` | `FIG-reporting-003` to `005` | First group, MER-POD-004-DEMO Atwater Canal Headgate; row MER-APN-058. |
| `/surface/diversion/10/` | none | MER-BPOD-001 El Nido Canal Recharge Intake. Captured as evidence, see finding 3. |
| `/reporting/reports/shared-supply-check/` | none | No period chosen. Captured to record which period the page picks by itself. |

**Why the May 2026 row and not the first row on screen.** A diversion record
carries three numbers that ought to differ: what was diverted, what was returned,
and the difference. Across all **173** diversion records in the demonstration,
**147** have a return flow of zero and **24** return the whole volume, so on 171 of
173 rows the third column is either a copy of the first or a zero. Only **two**
rows have a partial return, and both belong to this diversion point. The pinned
row is one of them: 250.00 diverted, 100.00 returned, 150.00 consumed. On any
other row a wrong subtraction would still have matched.

**Period.** WY 2025-2026, the drier of the demonstration's two years, matching
section 1's pin. The diversion point's own records table is not scoped to a
period at all (`surface/views.py:104-108`), so the choice does not reach
`FIG-surface-001` to `005`.

**Captured** at commit `9f9e27b2543516a95cdc15743070e3746d04ddbe`, 2026-09-05.
That commit is one past `v2.15`, the tag section 1 was captured at, and it added
only this ledger's own tooling: no template, view, service or model differs
between the two captures.

**Recomputation:** `audit/figure_ledger/sql/surface_reporting.sql`, run on the
host through `run_sql.sh`. It names tables and columns only. The independence
guard `tests/test_figure_ledger_independence.py` went from 17 passing cases to 20
when this file was added, which is how we know it actually read it rather than
skipping it.

> **Demonstration data.** Every figure below belongs to the invented Merced
> groundwater district. No row here describes a real water user, and none of it
> has been filed with anybody.

### The 14 figures

| `id` | `screen` | `site` | `label` | `context_var` | `view` | `service` | `raw_tables` | `rendered` | `recomputed` | `delta` | `verdict` | `notes` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `FIG-surface-001` | `/surface/diversion/9/` | `templates/surface/partials/_detail_pane.html:57` | Max rate (CFS) | `pod.max_rate_cfs` | `surface/views.py:166` | `—` | `surface_pointofdiversion` | 150.00 | 150.00 | MATCH | MATCH | Independence: different identity. Model field on the diversion point the view fetched at `surface/views.py:186`. Wrapped in a conditional, so it renders only where a rate is recorded; see finding 3. |
| `FIG-surface-002` | `/surface/diversion/9/` | `templates/surface/partials/_detail_pane.html:159` | Face value (AF) | `water_right.face_value_acre_feet` | `surface/views.py:172` | `—` | `surface_waterright, surface_pointofdiversion` | 60000.00 | 60000.00 | MATCH | MATCH | Independence: different identity. The linked right's field, reached through the diversion point. Also conditional: no linked right, or a right with no face value, and nothing renders. |
| `FIG-surface-003` | `/surface/diversion/9/` | `templates/surface/partials/_diversion_records.html:20` | Diverted (AF) | `record.volume_acre_feet` | `surface/views.py:167` | `—` | `surface_diversionrecord` | 250.00 | 250.00 | MATCH | MATCH | Independence: different identity. Whole column also checked, all 8 records on this diversion point, cross-check 3. |
| `FIG-surface-004` | `/surface/diversion/9/` | `templates/surface/partials/_diversion_records.html:21` | Return Flow (AF) | `record.returned_af` | `surface/views.py:167` | `—` | `surface_diversionrecord` | 100.00 | 100.00 | MATCH | MATCH | Independence: different identity. This is one of only two records in the whole demonstration where this column is neither 0 nor the full diverted volume, which is why the row was pinned here. |
| `FIG-surface-005` | `/surface/diversion/9/` | `templates/surface/partials/_diversion_records.html:23` | Consumptive Use (AF) | `record.consumed_acre_feet` | `surface/views.py:167` | `DiversionRecord.consumed_acre_feet` (`surface/models.py:162`) | `surface_diversionrecord` | 150.00 | 150.00 | MATCH | MATCH | Independence: restatement of one subtraction, `abs(volume) - returned`. Strengthened by cross-check 1, which applies the identity to all 173 records and finds 0 breaks and 0 rows where the return exceeds the volume. A method on the model, not a service. |
| `FIG-surface-006` | `/surface/rights/` | `templates/surface/partials/_list_results.html:30` | Face Value | `right.face_value_acre_feet` | `surface/views.py:288` | `—` | `surface_waterright` | 120000 | 120000 | MATCH | MATCH | Independence: different identity. Shown to zero decimal places, with the unit "AF" as template text beside it rather than part of the figure. All six rights checked whole-column, cross-check 2. |
| `FIG-surface-007` | `/surface/rights/7/` | `templates/surface/partials/_water_right_detail_pane.html:64` | Face value (AF) | `water_right.face_value_acre_feet` | `surface/views.py:343` | `—` | `surface_waterright` | 60000.00 | 60000.00 | MATCH | MATCH | Independence: different identity. The same stored column as `FIG-surface-006`, shown to two decimal places instead of none; the two screens agree. |
| `FIG-surface-008` | `/surface/rights/7/` | `templates/surface/partials/_water_right_detail_pane.html:113` | Max rate: N cfs | `pod.max_rate_cfs` | `surface/views.py:344` | `—` | `surface_pointofdiversion` | 400.00 | 400.00 | MATCH | MATCH | Independence: different identity. Renders once per diversion point on the right, ordered by name; the pin is the first, MER-POD-010-DEMO Merced Falls Hydroelectric Diversion. |
| `FIG-surface-009` | `/surface/rights/7/` | `templates/surface/partials/_water_right_detail_pane.html:174` | Volume (AF) | `record.volume_acre_feet` | `surface/views.py:345` | `—` | `surface_diversionrecord, surface_pointofdiversion` | 1200.00 | 1200.00 | MATCH | MATCH | Independence: different identity. First row of a 12-row list ordered by month alone; two diversion points sharing a month would be in an unspecified order, so the pin sits on September 2026, which only one has. This figure is a **diverted** volume with no return-flow column beside it, and all 1200.00 AF of it was returned to the stream: see finding 4. |
| `FIG-reporting-001` | `/reporting/reports/4/calwatrs-worksheet/` | `templates/reporting/calwatrs_worksheet.html:84` | Volume (AF) | `row.volume_af` | `reporting/views.py:443` | `—` | `surface_diversionrecord, surface_pointofdiversion, reporting_reportsubmission` | 877.47 | 877.47 | MATCH | MATCH | Independence: different identity. The stored volume, copied into a display dictionary at `reporting/views.py:437`. The worksheet shows this block; the generated state file withholds it, correctly, because the diversion point has no water right. See finding 2. |
| `FIG-reporting-002` | `/reporting/reports/4/calwatrs-worksheet/` | `templates/reporting/calwatrs_worksheet.html:85` | Max Rate (CFS) | `row.max_rate_cfs` | `reporting/views.py:443` | `—` | `surface_diversionrecord` | 312.07 | 312.07 | MATCH | MATCH | Independence: different identity. Stored as 312.0662 and shown to two places. Conditional: a record with no rate shows a dash. Note this is a peak rate stated against a whole month's volume, because a diversion record is monthly by design (`surface/models.py:160`). |
| `FIG-reporting-003` | `/reporting/reports/shared-supply-check/?period=2` | `templates/reporting/shared_supply_check.html:105` | Your share | `row.your_weight` | `reporting/views.py:296` | `build_shared_supply_comparison` then `apportion_shared_supply` | `surface_pointofdiversionparcel, parcels_parcel` | 0.2000 | 0.2000 | MATCH | MATCH | Independence: restatement. Reproduces the four-rung ladder, including which rung fires: some stored share here differs from the untouched default, so the whole group counts as hand-set and the stored shares are used as written. Cross-check 7 adds a different identity, that each group's shares sum to exactly 1.0000, and all 8 groups do. |
| `FIG-reporting-004` | `/reporting/reports/shared-supply-check/?period=2` | `templates/reporting/shared_supply_check.html:107` | ET-implied share | `row.et_weight` | `reporting/views.py:296` | `build_shared_supply_comparison` then `apportion_shared_supply` | `accounting_calculationrun, accounting_reportingperiod, surface_pointofdiversionparcel` | 0.1196 | 0.1196 | MATCH | MATCH | Independence: restatement, including the rule that the rounding residual lands on the last use area sorted as TEXT, not as a number. That rule is visible on this very screen: MER-APN-064 shows 0.0647 and MER-APN-063 shows 0.0648 although MER-APN-064's demand is fractionally the higher of the two. Cross-check 6 confirms no value in this data sits on an exact rounding tie, so the two rounding rules in play cannot differ here. |
| `FIG-reporting-005` | `/reporting/reports/shared-supply-check/?period=2` | `templates/reporting/shared_supply_check.html:110` | Gap | `row.divergence` | `reporting/views.py:296` | `build_shared_supply_comparison` (`reporting/generators.py:225`) | `accounting_calculationrun, surface_pointofdiversionparcel` | 0.0804 | 0.0804 | MATCH | MATCH | Independence: restatement. The absolute difference of the two shares above, not rounded again. Below the 0.15 flag threshold, so the pinned row carries no badge; one row in this group is flagged. |

### What section 4 found

**All 14 figures agree with the rows behind them, to the cent.** So do the seven
cross-checks that go with them: every diversion record's arithmetic across the
whole demonstration, every water right's face value on both screens that show it,
the pinned diversion point's whole records column, and every shared source's two
share columns. The recomputation is written to be able to disagree and it does
not.

Five things the reconciliation turned up that a matching column does not show.

**1. Three of these fourteen numbers can barely be wrong, given this data.** The
diversion records table's three columns are a genuine test of the platform's
arithmetic only where the return flow is a partial one. It is partial on **2 of
173** records. On the other 171 the Consumptive Use column is either a copy of the
Diverted column or a zero, and any formula at all would reproduce it. Both
discriminating rows belong to one diversion point, MER-POD-011-DEMO Snelling
Re-Diversion, and the ledger pins one of them deliberately. Nobody should read
`FIG-surface-005` as evidence that this arithmetic is exercised; it is evidence
that it is correct where it is exercised, which on this data is twice.

**2. The transcription worksheet and the file the state receives disagree about
87 percent of the volume, correctly, and the worksheet does not say so.** For
WY 2025-2026's To Storage filing the worksheet lays out **1,675.50 AF**. The
generated file carries **213.05 AF**. The missing **1,462.45 AF** all belongs to
MER-BPOD-001 El Nido Canal Recharge Intake, which has no water right, and the
generator withholds any row with a blank Water Right ID because that is what the
state flags as an unauthorized diversion (`reporting/generators.py:573-578`,
ISS-031b). That is the right behaviour. The gap is that the worksheet is a
page for a person to copy figures into the portal by hand, and it presents that
block exactly like the others, with a red "No linked water right" label and no
statement that these rows are absent from the file. The warning that does say so
lives on the report page, produced by `reporting/validators.py:318-328`, one
screen away from the person doing the typing.

**3. The one warning about an unpermitted diversion cannot appear on this data.**
`templates/surface/partials/_detail_pane.html:170` carries the line "CalWATRS
reports will flag this diversion as [INCOMPLETE]". It sits on the branch for a
diversion point with no water right and no recharge basin behind it. Exactly one
of the demonstration's nine diversion points has no water right, MER-BPOD-001,
and it has five recharge basin links, so it takes the branch above instead and
reads "Recharge diversion. It feeds a recharge basin rather than a consumptive
use, and no water right is linked." Confirmed by capturing the page: the string
"INCOMPLETE" does not appear on it. **0 of 9** diversion points can reach that
warning today. Nothing is broken; it is an untested guard, and no reader should
take it as a warning that has ever been seen.

The same diversion point renders **neither** of its template's two figures, for
the same reason: it has no maximum rate recorded and no linked right, and both
figures sit inside conditionals. Its detail page is the platform's own recharge
intake and it shows zero of that template's numbers.

**4. The same diverted volume reads very differently on two screens one click
apart.** A water right's page lists Recent diversion records with a single
Volume (AF) column. For MER-WR-010-DEMO that column's first row is
**1,200.00 AF**. The diversion point's own page shows the same record as
1,200.00 diverted, 1,200.00 returned, **0.00 consumed**, with a badge reading
"Non-consumptive (returned to stream)". Every one of that diversion point's 24
records is like this. A reader who stops at the water right's page sees 1,200 AF
a month and nothing to suggest none of it was consumed. Both numbers are right;
they answer different questions, and only one of the two screens says which.

**5. Two different rules pick "the records for this period", and only one of the
differences is live.** The worksheet selects on the reporting-period link alone
and filters on the diversion type (`reporting/views.py:411-418`). The allocation
selector at `surface/services.py:89` matches the reporting-period link **or** the
month falling inside the period's dates, and does not filter on type at all.
Measured across all 173 records: **0** have no period link, and **0** have a
period link that disagrees with their own month, so the "or" half of that
selector is currently inert and could not change any answer. The type filter is
live: **12** records are To Storage, and a caller that ignores the type is
reading those alongside the Direct Use ones. None of section C's 14 figures runs
through that selector, and this is recorded because it is a durable property of
the data that the next reader of either code path will want.

**One more thing observed, not inferred.** The shared-supply check reached with
no period chosen returns the same page as `?period=2`. The two captures differ
only in a per-request security token, which is how the section knows it rather
than by reading the code that picks the default.


---

## Section 5 — The remaining subsystems (18 figures)

Eighteen figures across ten page templates and five parts of the platform: the
zone page, the monitoring stations, the wells, the recharge basins, and the
first two steps of the setup wizard. They are the long tail of the figure
ledger. Most of these screens carry one or two numbers, not twenty, and most of
those numbers are a stored value shown back to the reader rather than the
result of a calculation.

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
| `FIG-geography-002` | `/map/zones/2/` | `templates/geography/partials/_zone_detail_pane.html:129` | Used (AF), with the word "pumped" beside it | `b.used` | `geography/views.py:221`, computed at `:197-204` | `billable_ledger` (`accounting/services.py:377`), then summed in the view | `parcels_parcelledger, geography_parcelzone` | 1313.07 | 1313.07 | MATCH | ISS-154 | Independence: restatement for the number, different identity for the finding. The page computes what it says it computes. What it says it is, it is not: of the 1,313.07 AF labelled "pumped", only 142.14 AF is groundwater. The other 1,170.93 AF is surface water delivered by canal, which the platform stores as a negative number and this figure therefore sweeps in. Detail below. |
| `FIG-geography-003` | `/map/zones/2/` | `templates/geography/partials/_zone_detail_pane.html:130` | Remaining (AF) | `b.remaining` | `geography/views.py:223` | `— (arithmetic in the view)` | `accounting_allocationplan, parcels_parcelledger, geography_parcelzone` | -562.75 | -562.75 | MATCH | ISS-154 | Independence: restatement. Allocation minus the figure above, so it inherits the same problem and turns it into a verdict: the page says this district is 562.75 AF over its groundwater budget. On its groundwater draw alone it is 608.18 AF under. The sign is wrong, not just the size. |
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

### What section 5 found

**Thirteen of the eighteen figures agree with the rows behind them to the cent.
The other five could not be put on a screen at all.** No figure in this section
disagrees with its own arithmetic. One of them disagrees with its label, and
that is the finding worth acting on.

Six things the reconciliation turned up that a matching column does not show.

#### 1. The district page counts canal water as pumping, and it changes who is over budget

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
`ISS-154` against `FIG-geography-002` and `FIG-geography-003`, a number reserved
here and filed by Plan 135-03. This section does not diagnose it further and changes nothing.

#### 2. A quarter of this section's figures have no screen to appear on

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

#### 3. Two thirds of these figures are values shown back, not values worked out

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

#### 4. The boundary area is the one stored figure with an independent answer

The setup wizard shows the district's area, and the platform deliberately
refuses to work that area out from the outline it holds. The reasoning is
written down and it is good: a computed area would be OpenH2O's number offered
as the district's. So the figure is whatever the uploaded file said.

The database will compute it, though, and it agrees: **800.949** square miles
measured off the stored outline against the **800.948** the file states. About
half an acre of difference across an 800 square mile basin. That is the only
figure in this section where a stored value could be checked against something
other than itself, and it held.

#### 5. The independence guard passed on this section's work without reading it

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

#### 6. Every page capture overwrites the previous run's index

`scripts/figure_capture.py` writes its list of captured pages to a fixed
filename in the output folder. Four sets of captures ran into that one folder,
so each run replaced the previous run's list. The saved pages themselves survive
because each carries its own name; only the index of what was captured, at what
size, with what fingerprint, is lost. This section's copy was preserved before
the overwrite as `manifest-d.json`, and the other three sections' copies are
beside it.

#### On the drinking-water module, which has no rows here

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

### Where this section's evidence lives

- Recomputation: `audit/figure_ledger/sql/remaining_subsystems.sql`
- Pinned screens: `audit/figure_ledger/screens-d.json`
- Captured pages: `audit/figure_ledger/rendered/d-*.html`, indexed by `manifest-d.json`
- Results: `audit/figure_ledger/results/section_d.csv`, with the two halves in
  `rendered_section_d.csv` and `recomputed_section_d.csv`, and the four-district
  check in `zone_used_column_section_d.csv`
