# Figure ledger — September 2026

Every number this platform puts on a screen, traced to the rows it came from and
then worked out a second way, independently, to see whether the two agree.

This document is being built one screen at a time. It is **partial**, and the
last section says exactly how partial.

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

## How to reproduce it

Seven commands, in order, from the repository root:

```
python3 scripts/figure_inventory.py --out audit/figure_ledger/inventory.json
docker compose exec -T web python scripts/figure_capture.py \
    --screens audit/figure_ledger/screens.json \
    --out audit/figure_ledger/rendered --sha "$(git rev-parse HEAD)"
docker compose cp web:/app/audit/figure_ledger/rendered/. audit/figure_ledger/rendered/
python3 audit/figure_ledger/extract_dashboard.py \
    --html audit/figure_ledger/rendered/accounting-dashboard-wy2026.html \
    --out audit/figure_ledger/results/rendered_accounting_dashboard.csv
bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/accounting_dashboard.sql \
    > audit/figure_ledger/results/recomputed_accounting_dashboard.csv
bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/accounting_dashboard_crosschecks.sql
python3 audit/figure_ledger/merge_results.py \
    --rendered   audit/figure_ledger/results/rendered_accounting_dashboard.csv \
    --recomputed audit/figure_ledger/results/recomputed_accounting_dashboard.csv \
    --out        audit/figure_ledger/results/accounting_dashboard.csv
```

The capture step runs inside the application container, because that is where the
web framework lives, and the copy step after it exists because that container
holds no live link back to the working copy. The two SQL steps run on the host,
against the same database the page rendered from.

**Captured at commit `d12d778a56f5eaad1192744160d1a1f003b385ff`** (tag `v2.15`),
2026-09-05. Pages saved under `audit/figure_ledger/rendered/`, each with its
size and content fingerprint in `manifest.json`. The database was left exactly as
found: the capture creates one throwaway sign-in and deletes it again, and prints
the row count on both sides of the run.

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
| `delta` | `rendered − recomputed`, or `MATCH` when zero to the cent |
| `verdict` | `MATCH` · `ISS-###` · `EXPLAINED` (differs for a stated, correct reason) |
| `notes` | Independence class and anything a reader needs |

**Pinned instance.** A table column renders once per row, so a column that
appears 76 times gets one named instance — a specific account, zone or period —
recorded in `screen` and in the notes, plus a whole-column check in the SQL where
that is cheap. Without the pin nobody can reproduce the number.

**`EXPLAINED` is not a synonym for `MATCH`.** It is for a difference that is
legitimate and stated: rounding at the display layer, or a deliberate suppression
such as the dash this platform shows for a row with no calculation behind it. A
difference with no reason attached is an issue number, not an explanation.

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

## Sections still to write

A mechanical sweep of the templates finds **107 occurrences** of the display
formatter that marks a figure, in 25 files. One of those occurrences is prose
inside a template comment — a note in the drinking-water module explaining that
lab results deliberately do *not* go through it — so the platform renders **106
figures across 24 templates**, and this ledger will have 106 rows. The inventory
records all 107 and labels which is which, so the count stays reproducible
against a plain text search.

**23 are reconciled above. 83 remain, across 23 templates.**

| Template | Figures |
|---|---|
| `accounting/partials/_account_balances.html` | 12 |
| `accounting/calculation_run_detail.html` | 8 |
| `accounting/partials/_ledger_list_results.html` | 4 |
| `accounting/partials/_methodology_preview.html` | 4 |
| `accounting/partials/_allocations_list_results.html` | 2 |
| `accounting/period_detail.html` | 1 |
| `datasync/partials/_station_detail_pane.html` | 4 |
| `geography/partials/_zone_detail_pane.html` | 3 |
| `geography/partials/_zone_parcels.html` | 1 |
| `parcels/partials/_detail_pane.html` | 20 |
| `recharge/partials/_detail_pane.html` | 2 |
| `recharge/partials/_event_history.html` | 1 |
| `recharge/partials/_list_results.html` | 1 |
| `reporting/shared_supply_check.html` | 3 |
| `reporting/calwatrs_worksheet.html` | 2 |
| `setup/confirm.html` | 1 |
| `setup/wizard.html` | 1 |
| `surface/partials/_diversion_records.html` | 3 |
| `surface/partials/_water_right_detail_pane.html` | 3 |
| `surface/partials/_detail_pane.html` | 2 |
| `surface/partials/_list_results.html` | 1 |
| `wells/partials/_detail_pane.html` | 2 |
| `wells/partials/_editable_field.html` | 2 |

### Section 2 — The parcel detail pane (20 figures)

To be written. This is the heaviest screen after the dashboard and the one with a
known problem waiting for it: the pane states two balances that disagree about
whether the parcel ended the year in surplus or in deficit — on **32 of 76
parcels** in the wetter year and **24 of 76** in the drier one, measured
2026-09-05.

### Section 3 — The account balances pane (12 figures)

To be written. Same shape as the dashboard's account row, one account at a time.

### Sections 4 onward — the remaining 51 figures across 21 templates

To be written, in the table order above.
