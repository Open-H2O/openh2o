# Figure ledger, September 2026

Every number this platform puts on a screen, traced to the rows it came from and
then worked out a second way, independently, to see whether the two agree.

**This ledger is complete.** All 120 figures the platform renders have a row, and
a test in the build refuses to let that stay true by accident: add a figure to a
template without tracing it, or leave a row behind after deleting a template, and
the suite goes red.

## What this is, and what it is not

The platform renders 120 figures across 24 page templates (114 until 2026-09-08,
when 143-01 gave the account balance panel's Use area table a footer carrying
the panel's six totals, FIG-accounting-021..026, six sites that repeat six
figures already traced, and reordered and renamed the same table's existing
columns into equation order (Surface, Groundwater, Rain, Total, Consumptive use,
Balance) without adding or removing a site; 108 until earlier that day, when
142-01 gave the dashboard's Active water accounts table a footer carrying
the panel's six totals, FIG-accounting-043..048, six sites that repeat six
figures already traced; 104 until later that
day, 2026-09-06, when 137-03 gave the well page a Measurement history card
(ISS-145), Totalizer and Delta per meter read and Close and Change per
water-level month, FIG-wells-001..004, one template, for a net four sites more;
100 until 2026-09-06, when 137-02 added the dashboard's district-wide "Fields
with water use recorded and no supply reported" list, surface 2 of ISS-157,
three sites (a per-row Consumptive Use cell, a per-row shortfall cell, and the
District total footer), and the district page's Allocation vs. use table gained
a Carried Forward cell of its own, one site, for a net four sites more; 105
until earlier that day, when
137-01 replaced the parcel pane's two-balance display, namely three stat
cards, a "Net consumptive demand" sentence, three supply-composition cards, a
seven-row supply-vs-use table and a free-standing residual row (20 figure sites
in all), with ONE `.budget-panel` (three segments plus a two-line foot, 9 sites)
and added the ISS-157 unmet-demand figure, a net five sites fewer; 106 before
that, when 136-01 retired the use ledger footer's net; see section 2 and section
3, finding 3). Each one has a chain
behind it: a page, a template line, a view that put a value into that line, often
a service function that computed it, and underneath all of it some rows in the
database. This ledger walks that chain for every figure, and then does something
that sounds redundant and is not: it computes the same number again from the
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
> mixes one invented groundwater district (invented basin, invented districts,
> invented growers) with one real, published drinking-water record. Every figure
> in this document belongs to the invented district. No row here describes a real
> water user.

## What the ledger found

**86 of the 100 figures agree with the rows behind them to the cent, and nothing
in this platform computes a number wrongly**, as of 2026-09-06 after 137-01 (88
of 105 after 136-02 earlier the same day, 86 after 136-01, and 84 of 106 on
2026-09-05; every same-day re-measure is set out at the top of its own section).
Not one figure disagrees with its own arithmetic. What the ledger found instead
is figures that are correct and labelled wrongly, and figures that no screen can
currently show.

The verdict counts, recounted from the five section ledgers on 2026-09-06 after
137-01:

| Verdict | Count of 100 | Meaning |
|---|---:|---|
| `MATCH` | 86 | The screen and the independent recomputation agree to the cent |
| `MATCH · ISS-###` | 1 | The number is right; a separate issue is raised against the words beside it |
| `ISS-###` | 2 | The screen states two things that cannot both be true |
| `EXPLAINED` | 0 | The two agree for a stated reason that is not a measurement |
| `UNVERIFIED` | 11 | The screen never rendered it, or nothing derives it |

Three rows carry an issue number, and they name two problems (five rows and
three problems until 137-01 closed ISS-148 the same day; eight rows and four
problems on 2026-09-05; ISS-155 was resolved by 136-01 on 2026-09-06 and its
three rows now read `MATCH`):

**The district page counts canal water as pumping** ([ISS-154](#), reserved here
and filed by the next plan). A district's Allocation vs. use table has a column
headed Used with the word *pumped* beside it. It adds every negative entry in the
district's ledger, and canal deliveries are stored as negative numbers, so they
land inside it. One of the three groundwater districts reads as 562.75 acre-feet
over budget when its groundwater draw alone leaves 608.18 in hand: not a margin,
the opposite sign. A second reads 10,569.36 over when its groundwater draw alone
is 332.58 over, an overstatement of about thirty-two times. The third takes no
canal water, which is why the fault is invisible to anyone reading one page. On
2026-09-05, before 136-02 re-sized the allocations, the sign was reversed on two
of the three rather than one. Section 5, finding 1.

**The parcel pane stated two balances that disagreed** ([ISS-148](#), resolved
2026-09-06 by 137-01). A card at the top of the pane said 174.13 acre-feet of
water arrived and was not consumed; a residual three inches below said the books
closed at 0.00, Balanced. On about two thirds of parcels each year the two
printed numbers differed. 137-01 removed the card: the pane now states the mass
balance alone, so there is nothing left on the screen for the residual to
disagree with. Section 2, finding 1.

**The use ledger and the dashboard stated the year with opposite signs**
([ISS-155](#), resolved 2026-09-06 by 136-01). Over the same 1,130 rows on the
same 76 parcels, the dashboard said the district finished 1,249.07 acre-feet
ahead and the use ledger footer said 1,504.32 behind. Both arithmetics were
correct. The footer no longer prints a net: it names its two subtotals by kind.
Section 3, finding 3.

**The allocations footer adds surface water to groundwater** ([ISS-156](#),
reserved). 148,500.00 acre-feet of surface-water allocation plus 4,621.27 of
groundwater allocation, printed as one number in acre-feet that no agency
manages. 136-02 changed the size of the groundwater half on 2026-09-06 and not
the mixture: the total is now 153,121.27, and it was 159,671.46. Section 3, finding 4.

Eleven figures could not be independently recomputed, and they are named rather
than omitted: four on the calculation page's banked-water block (no run in this
database carries a deposit or a draw, and the five credit rows that do exist all
hold 0.0000 acre-feet), two in a notice shown only to a parcel with no
calculations yet (every parcel has them, in both years), two well fields a person
types by hand, two monitoring-station reading figures, and the setup wizard's
confirmation step, which needs a form submission to reach. It was thirteen on
2026-09-05, when the monitoring station page could not be opened at all: 136-02's
rebuilt data carries all 335 stations and 30,217 staged readings, so that page
now renders and its two location figures agree to five decimal places. The two
reading figures stay unverified because the station with the lowest id happens to
carry no staged record.

**Every one of those eight was then re-derived a THIRD time before it was
filed**, by an identity neither of the first two derivations used, and the
working is in `audit/figure_ledger/triage.md`. Three survived and became
ISS-154, ISS-155 and ISS-156; one was already ISS-148; none turned out to be the
auditor's arithmetic. Three claims written *around* those numbers did not
survive, and they are set out there too.

**Section 6 is the other half of this document's job.** Every section before it
asks whether a figure matches its rows. Section 6 asks, of the 21 field-years
whose water balance sits outside the platform's own acceptance band, whether the
platform is wrong or the water is. Twenty-one flags turned out to have three
causes, and only one of them is a defect.

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
twenty cases; if it says eight, it read two. Eight files means twenty-six.

**Captured again at commit `2555a68`**, 2026-09-06, after 136-02 changed the
demonstration's seed data: every district's groundwater allocation is now its own
demonstration sustainable-yield rate, and the El Nido recharge intake diverts
under a water right of its own. This capture was taken on the rebuilt
demonstration database restored into the development database, not on the
hand-seeded copy the 2026-09-05 and 136-01 captures ran against. The hand-seeded copy had
gaps in its primary keys; the rebuilt data numbers its rows in a clean sequence,
and that sequence is what the promoted demonstration and any new deployment will
carry. So eight pinned addresses changed number without a single figure changing
meaning: `/accounting/accounts/78/` became `/accounting/accounts/12/`
(MER-ACCT-001), `/surface/diversion/9/` became `/surface/diversion/8/`
(MER-POD-011-DEMO Snelling Re-Diversion), `/surface/diversion/10/` became
`/surface/diversion/9/` (MER-BPOD-001 El Nido Canal Recharge Intake),
`/surface/rights/7/` became `/surface/rights/6/` (MER-WR-010-DEMO), `/wells/32/`
became `/wells/10/` (MER-W-001), `/recharge/6/` became `/recharge/1/` (El Nido
Recharge Basin 1), and `/map/zones/39/` became `/map/zones/9/` (MER Surface
Service Area, Halvern Irrigation District). The parcels, the three groundwater
districts, the monitoring station and the report submission kept the numbers they
had. `audit/figure_ledger/screens.json` and its four per-section files were
repointed to the new addresses, the pins inside the recomputation SQL with them,
and the `screen` column of every ledger row now carries the rebuilt data's
numbers.
Two addresses answer differently as a result: `/datasync/stations/1/` returns a
page (SAN JOAQUIN R - MONITORING WELL #142) where it returned 404 before, and
`/setup/confirm/` still redirects.

**Captured again at commit `e22cb84`**, 2026-09-06, after 136-01 changed the
budget basis and the words on five templates (the first product-code change
since `v2.15`). The 2026-09-05 capture below is kept in the row notes as the
before-picture wherever a value moved.

**First captured at commit `92e7ed87ee2c8de7259635e40941aaed959950bd`**, 2026-09-05, one commit
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
| `site` | `template/path.html:LINE`, grep-verified, never guessed |
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
appears 76 times gets one named instance: a specific account, parcel, zone or
period, recorded in `screen` and in the notes, plus a whole-column check in the
SQL where that is cheap. Without the pin nobody can reproduce the number.

**The five verdicts, and why there are five.**

- **`MATCH`**: the screen and the recomputation agree to the cent.
- **`EXPLAINED`**: they differ, or agree, for a stated reason that is not a
  measurement: rounding at the display layer, or a term the platform hard-codes.
  It is **not** a synonym for `MATCH`, and a difference with no reason attached is
  an issue number rather than an explanation.
- **`UNVERIFIED`**: it could not be independently recomputed, and the notes say
  why. A screen that never renders it; a value a person typed that nothing
  derives. **This is a complete answer, and it is the one a partial ledger would
  have quietly left out.**
- **`ISS-###`**: the screen states two things that cannot both be true.
- **`MATCH · ISS-###`**: the number is right to the cent and the words beside it
  are wrong. Both halves are true and a reader needs both.

A row with a blank or hand-waved verdict cannot ship: `tests/test_figure_ledger_coverage.py`
refuses it.

---

## Section 1: The accounting dashboard (29 figures)

**Re-numbered and re-labelled 2026-09-08 after 142-01 redesigned the dashboard.** The
columns now run Supplies (Surface, Groundwater, Rain, Total) → Consumptive use →
Balance → Groundwater budget, the accounts table gained a footer (six sites,
`FIG-accounting-043..048`, each the same context value as a panel figure and so
covered by that figure's recomputation), and no number changed. Because figure ids
number by position, every accounting id from 029 on was renumbered by
`audit/figure_ledger/remap_ids.py` (k-th occurrence of an expression per template) and
every `site` and `label` in this section was rewritten from the regenerated
inventory. The 2026-09-06 measurements below stand; only the ids, lines and header
words moved.

**Re-measured 2026-09-06 after 136-02 re-sized the groundwater allocations.**
Before this plan the three groundwater districts shared one flat rate. Each now
carries its own demonstration sustainable-yield rate: Halvern Valley GSA 0.58
acre-feet per acre, which takes its allocation from 9,689.40 to **2,809.93 AF**;
Verdano Island Water District GSA 2.90, which takes it from 731.74 to
**1,061.02 AF**; Halvern Irrigation-Urban GSA 2.00, which is the rate it already
had, so its 750.32 AF did not move. Two of the 23 rows moved in value and all 23
still match to the cent: `FIG-accounting-041` 2,901.42 to **957.22** and
`FIG-accounting-042` 2,901.42 to **957.22**, both because the pinned account's
share is pro-rated from the re-sized Halvern Valley plan. Rows `043`, `044` and
`045` did not move, because the pinned zone is the one district whose rate was
already right.

Here is what the three districts now read, in both years. **GW remaining** is the
figure the dashboard's zone table prints, allocation plus carry-over minus
groundwater use. **On allocation alone** drops the carry-over, which is the basis
the account rows and the attention strip use.

| District | Year | GW allocation | Carry-over | GW remaining | On allocation alone |
|---|---|---:|---:|---:|---:|
| Halvern Valley GSA | WY 2024-2025 | 2,809.93 | 5,109.01 | 5,400.48 | +291.47 |
| Halvern Valley GSA | WY 2025-2026 | 2,809.93 | 3,336.08 | 3,003.50 | −332.58 |
| Halvern Irrigation-Urban GSA | WY 2024-2025 | 750.32 | 407.93 | 1,020.66 | +612.73 |
| Halvern Irrigation-Urban GSA | WY 2025-2026 | 750.32 | 303.40 | 911.58 | +608.18 |
| Verdano Island Water District GSA | WY 2024-2025 | 1,061.02 | 0.00 | 32.54 | +32.54 |
| Verdano Island Water District GSA | WY 2025-2026 | 1,061.02 | 0.00 | −31.71 | −31.71 |

Two things that table is worth reading for. Halvern Valley GSA's zone row cannot
go negative at any rate the plan could have chosen, because its recharge-pool
carry-over of 3,336.08 AF in the dry year is larger than the 3,142.51 AF it
pumped; on allocation alone it crosses, from 291.47 AF under in the wet year to
332.58 AF over in the dry one. Verdano Island holds no pool at all, so its zone
row is the same figure on either basis, and it crosses too: 32.54 under, then
31.71 over. The attention strip above these tables counts **4 accounts over
groundwater budget in WY 2024-2025 and 5 in WY 2025-2026**. The fifth is
MER-ACCT-007, the curtailed Saddlebow growers, which crosses only in the dry year
because its pumping more than doubles when the canal stops.

**Re-measured 2026-09-06 after 136-01 changed the budget basis (ISS-151, option
A).** The two budget columns on both tables are now the groundwater budget: an
account's allocation counts groundwater plans only, and Remaining is allocation
(plus carry-over on the zone table) minus groundwater use, the metered or
calculated pumping the Groundwater column already shows, instead of gross crop
water use. Three of the 23 rows moved in value and all 23 match to the cent on
the new basis: `FIG-accounting-041` 19,101.42 to **2,901.42** (the 16,200.00 AF
of surface entitlement it used to add is no longer counted as groundwater),
`FIG-accounting-042` 14,511.81 to **2,901.42** (this account pumps nothing), and
`FIG-accounting-057` −136.03 to **911.58** (750.32 + 303.40 carry-over − 142.14
pumped). The five surface service-area zones now show a dash in all three budget
cells. Sites on the zone table moved down nine lines for a template comment;
the ids did not change.

**Screen:** `/accounting/dashboard/?period=2`, the water year running October
2025 to September 2026, the drier of the demonstration's two years. This is also
the page a visitor lands on with no year chosen; that was confirmed by capturing
both and comparing them, not by reading the code that picks the default. The two
saved pages differ only in a per-request security token.

**Pinned rows.** The account table's figures are pinned to `MER-ACCT-001`, Ashvale
Orchards Inc., the first row on screen (18 parcels, 216 monthly calculation runs)
in the period. The zone table's figures are pinned to Halvern Irrigation-Urban
GSA, also the first row on screen, 23 parcels. Both tables were also checked
whole-column in SQL where doing so cost nothing.

| `id` | `screen` | `site` | `label` | `context_var` | `view` | `service` | `raw_tables` | `rendered` | `recomputed` | `delta` | `verdict` | `notes` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `FIG-accounting-029` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:44` | Supplies | `grand_supply_total` | `accounting/views.py:194` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun, accounting_wateraccountparcel` | 17458.35 | 17458.35 | MATCH | MATCH | Independence: different identity. Summed over active accounts only. Also computed in ONE pass over the distinct union of those parcels, a second identity that would disagree if any parcel belonged to two active accounts. It does not: none does. |
| `FIG-accounting-033` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:72` | Consumptive use | `grand_consumptive_use` | `accounting/views.py:193` | `account_consumptive_balance` | `accounting_calculationrun` | 16209.28 | 16209.28 | MATCH | MATCH | Independence: different identity. Same single-pass cross-check, same agreement. |
| `FIG-accounting-034` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:94` | Balance | `grand_net` | `accounting/views.py:248` | `— (arithmetic in the view)` | `parcels_parcelledger, accounting_calculationrun` | 1249.07 | 1249.07 | MATCH | MATCH | Independence: different identity. Supplies minus consumptive use, both above. |
| `FIG-accounting-030` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:54` | Supplies by source › Surface | `grand_supply_surface` | `accounting/views.py:195` | `account_consumptive_balance` | `parcels_parcelledger` | 11407.71 | 11407.71 | MATCH | MATCH | Independence: different identity. Magnitude of the delivery rows, which are stored as negative numbers by the platform's own convention. |
| `FIG-accounting-031` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:55` | Supplies by source › Groundwater | `grand_supply_groundwater` | `accounting/views.py:196` | `account_consumptive_balance` | `parcels_parcelledger` | 4377.38 | 4377.38 | MATCH | MATCH | Independence: different identity. Absolute value OF THE SUM of the negative non-delivery rows, not the sum of absolute values. Transcribed as written; the two differ if a positive row ever lands in that set. |
| `FIG-accounting-032` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:56` | Supplies by source › Rain | `grand_supply_precip` | `accounting/views.py:197` | `account_consumptive_balance` | `accounting_calculationrun` | 1673.27 | 1673.27 | MATCH | MATCH | Independence: different identity. Effective rainfall, from the calculation runs rather than the ledger. |
| `FIG-accounting-039` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:246` | Consumptive use | `row.consumptive_use_gross` | `accounting/views.py:183` | `account_consumptive_balance` | `accounting_calculationrun` | 4589.61 | 4589.61 | MATCH | MATCH | Independence: restatement. Sum of gross evapotranspiration over the account's parcels' monthly runs. |
| `FIG-accounting-035` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:234` | Supplies › Surface | `row.surface` | `accounting/views.py:185` | `account_consumptive_balance` | `parcels_parcelledger` | 5500.97 | 5500.97 | MATCH | MATCH | Independence: restatement. Same delivery-magnitude rule as FIG-accounting-030. |
| `FIG-accounting-036` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:237` | Supplies › Groundwater | `row.groundwater` | `accounting/views.py:186` | `account_consumptive_balance` | `parcels_parcelledger` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. 0.00 is a real zero here, not a suppression: this account has 216 monthly calculation runs behind it over 18 parcels, and not one groundwater or meter row in the period. |
| `FIG-accounting-037` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:240` | Supplies › Rain | `row.precip` | `accounting/views.py:187` | `account_consumptive_balance` | `accounting_calculationrun` | 420.12 | 420.12 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-038` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:243` | Supplies › Total | `row.supply_total` | `accounting/views.py:188` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 5921.09 | 5921.09 | MATCH | MATCH | Independence: restatement. The three supply columns added. |
| `FIG-accounting-040` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:249` | Balance | `row.net_vs_supply` | `accounting/views.py:189` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 1331.48 | 1331.48 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-041` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:253` | Groundwater budget › Allocation | `row.allocation` | `accounting/views.py:181` | `— (arithmetic in the view)` | `accounting_allocationplan, accounting_watertype, geography_parcelzone, accounting_wateraccountparcel` | 957.22 | 957.22 | MATCH | MATCH | Re-measured 2026-09-06 after 136-02 (was 2,901.42): the two groundwater plans this account's share is pro-rated from were re-sized to their own demonstration sustainable-yield rates, and Halvern Valley GSA's fell from 9,689.40 to 2,809.93 at 0.58 AF/acre. Thirteen of that district's 46 parcel-zone rows and five of Halvern Irrigation-Urban GSA's 23 belong to this account, so 13/46 of 2,809.93 plus 5/23 of 750.32 gives 957.22. Re-measured 2026-09-06 after 136-01 (was 19,101.42): groundwater plans only, so the 16,200.00 AF surface entitlement this account also holds is no longer added in (like with like; DESIGN.md rule 12). Independence: restatement. Pro-rated by how many of the account's parcel-zone rows fall in each zone. The only figure on this screen computed in the view itself, and the reconciliation had to transcribe that division to reproduce it. |
| `FIG-accounting-042` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:256` | Groundwater budget › Remaining | `row.remaining` | `accounting/views.py:200` | `— (arithmetic in the view)` | `accounting_allocationplan, accounting_watertype, geography_parcelzone, parcels_parcelledger` | 957.22 | 957.22 | MATCH | MATCH | Re-measured 2026-09-06 after 136-02 (was 2,901.42): the re-sized allocation above, and this account still pumps 0.00 (`FIG-accounting-036`), so Remaining moved with it and nothing else changed. Re-measured 2026-09-06 after 136-01 (was 14,511.81): groundwater allocation minus groundwater use, and this account pumps 0.00 (`FIG-accounting-036`), so it equals the allocation. Before 136-01 the column subtracted gross evapotranspiration (ISS-151). Independence: restatement. |
| `FIG-accounting-043` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:273` | All 11 active accounts › Surface | `grand_supply_surface` | `accounting/views.py:227` | `account_consumptive_balance` | `parcels_parcelledger` | 11407.71 | 11407.71 | MATCH | MATCH | New site, 142-01 (2026-09-08): the Active water accounts table's footer, added so the panel and the table are visibly one thing. It renders the SAME context value as `FIG-accounting-030` above, one variable and one number, so the recomputation at that row is the recomputation here; the rendered figure was read off the served footer on staging after the deploy. What makes the rows addable (DESIGN.md rule 12): one quantity, one period, every active account, and the footer's label says so. |
| `FIG-accounting-044` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:274` | All 11 active accounts › Groundwater | `grand_supply_groundwater` | `accounting/views.py:228` | `account_consumptive_balance` | `parcels_parcelledger` | 4377.38 | 4377.38 | MATCH | MATCH | New site, 142-01 (2026-09-08): the Active water accounts table's footer, added so the panel and the table are visibly one thing. It renders the SAME context value as `FIG-accounting-031` above, one variable and one number, so the recomputation at that row is the recomputation here; the rendered figure was read off the served footer on staging after the deploy. What makes the rows addable (DESIGN.md rule 12): one quantity, one period, every active account, and the footer's label says so. |
| `FIG-accounting-045` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:275` | All 11 active accounts › Rain | `grand_supply_precip` | `accounting/views.py:229` | `account_consumptive_balance` | `accounting_calculationrun` | 1673.27 | 1673.27 | MATCH | MATCH | New site, 142-01 (2026-09-08): the Active water accounts table's footer, added so the panel and the table are visibly one thing. It renders the SAME context value as `FIG-accounting-032` above, one variable and one number, so the recomputation at that row is the recomputation here; the rendered figure was read off the served footer on staging after the deploy. What makes the rows addable (DESIGN.md rule 12): one quantity, one period, every active account, and the footer's label says so. |
| `FIG-accounting-046` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:276` | All 11 active accounts › Total | `grand_supply_total` | `accounting/views.py:226` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 17458.35 | 17458.35 | MATCH | MATCH | New site, 142-01 (2026-09-08): the Active water accounts table's footer, added so the panel and the table are visibly one thing. It renders the SAME context value as `FIG-accounting-029` above, one variable and one number, so the recomputation at that row is the recomputation here; the rendered figure was read off the served footer on staging after the deploy. What makes the rows addable (DESIGN.md rule 12): one quantity, one period, every active account, and the footer's label says so. |
| `FIG-accounting-047` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:277` | All 11 active accounts › Consumptive use | `grand_consumptive_use` | `accounting/views.py:225` | `account_consumptive_balance` | `accounting_calculationrun` | 16209.28 | 16209.28 | MATCH | MATCH | New site, 142-01 (2026-09-08): the Active water accounts table's footer, added so the panel and the table are visibly one thing. It renders the SAME context value as `FIG-accounting-033` above, one variable and one number, so the recomputation at that row is the recomputation here; the rendered figure was read off the served footer on staging after the deploy. What makes the rows addable (DESIGN.md rule 12): one quantity, one period, every active account, and the footer's label says so. |
| `FIG-accounting-048` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:278` | All 11 active accounts › Balance | `grand_net` | `accounting/views.py:283` | `— (arithmetic in the view)` | `parcels_parcelledger, accounting_calculationrun` | 1249.07 | 1249.07 | MATCH | MATCH | New site, 142-01 (2026-09-08): the Active water accounts table's footer, added so the panel and the table are visibly one thing. It renders the SAME context value as `FIG-accounting-034` above, one variable and one number, so the recomputation at that row is the recomputation here; the rendered figure was read off the served footer on staging after the deploy. What makes the rows addable (DESIGN.md rule 12): one quantity, one period, every active account, and the footer's label says so. |
| `FIG-accounting-053` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:371` | Consumptive use | `row.consumptive_use_gross` | `accounting/views.py:235` | `zone_consumptive_balance` | `accounting_calculationrun` | 1189.75 | 1189.75 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-049` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:359` | Supplies › Surface | `row.surface` | `accounting/views.py:237` | `zone_consumptive_balance` | `parcels_parcelledger` | 1170.93 | 1170.93 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-050` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:362` | Supplies › Groundwater | `row.groundwater` | `accounting/views.py:238` | `zone_consumptive_balance` | `parcels_parcelledger` | 142.14 | 142.14 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-051` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:365` | Supplies › Rain | `row.precip` | `accounting/views.py:239` | `zone_consumptive_balance` | `accounting_calculationrun` | 110.56 | 110.56 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-052` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:368` | Supplies › Total | `row.supply_total` | `accounting/views.py:240` | `zone_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 1423.63 | 1423.63 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-054` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:374` | Balance | `row.net_vs_supply` | `accounting/views.py:241` | `zone_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 233.88 | 233.88 | MATCH | MATCH | Independence: restatement. |
| `FIG-accounting-055` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:378` | Groundwater budget › Allocation | `row.allocation` | `accounting/views.py:247`, computed via `zone_groundwater_budget` at `:246` | `zone_groundwater_budget` | `accounting_allocationplan` | 750.32 | 750.32 | MATCH | MATCH | 136-02 left this where it was: Halvern Irrigation-Urban GSA's demonstration sustainable-yield rate is 2.00 AF/acre, which is the rate the plan already carried, so its allocation stayed 750.32 while the other two districts moved. Independence: restatement. Re-cited 2026-09-06 after 137-02 (ISS-154 closed): this cell now reads off the shared `zone_groundwater_budget` helper (`accounting/services.py:1134`), the same one `geography/views.py` calls for `FIG-geography-001`, instead of being computed twice. The value did not move. |
| `FIG-accounting-056` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:381` | Groundwater budget › Carried fwd | `row.carryover` | `accounting/views.py:269`, computed via `zone_groundwater_budget` at `:246` | `zone_groundwater_budget` calls `zone_carryover` | `accounting_allocationcarryover` | 303.40 | 303.40 | MATCH | MATCH | 136-02 changed allocations only, not the recharge pool this column reads, so the carry-over did not move. Independence: restatement. Looked up by water year, which is named for the calendar year the year ENDS in. This zone's rows for that label sum to the figure shown. Re-cited 2026-09-06 after 137-02 (ISS-154 closed): reads off the same shared `zone_groundwater_budget` helper as `FIG-accounting-055`, and now equals the district page's own Carried forward cell for this zone and period (`FIG-geography-002`) to the cent. |
| `FIG-accounting-057` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:384` | Groundwater budget › Remaining | `row.remaining` | `accounting/views.py:270`, computed via `zone_groundwater_budget` at `:246` | `zone_groundwater_budget` calls `available_with_carryover` | `accounting_allocationplan, accounting_watertype, accounting_allocationcarryover, parcels_parcelledger` | 911.58 | 911.58 | MATCH | MATCH | 136-02 moved none of this row's three terms, so it still reads 911.58. Re-measured 2026-09-06 after 136-01 (was −136.03): allocation 750.32 plus carry-over 303.40 (`FIG-accounting-056`) minus 142.14 of groundwater use (`FIG-accounting-050`). Re-cited 2026-09-06 after 137-02 (ISS-154 closed): this is the same `zone_groundwater_budget` call `FIG-geography-004` now reads, so the dashboard and the district page print the same 911.58 for this zone and period, to the cent, for the first time. Before ISS-154 was fixed the district page read this same zone at −562.75, because it counted canal water as pumping; without the carry-over the correct figure would have been 608.18. Independence: restatement. |

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
number: 59 of the 76 parcels sit in two zones at once, a groundwater agency's
area and a surface-water district's service area, so the zone table counts them
twice by design. The page never says this. A visitor who adds the column up gets
a figure 79% too high and has no way to find out why.

**3. One figure on this screen is worked out in the page's own code rather than
in any shared calculation.** The account Allocation column divides each zone's
budget by how many parcels it holds and gives each account its share.
Reproducing it meant transcribing that division, because there is no function to
read it out of. It matches, but it is the only figure on the dashboard with no
shared implementation behind it, so it is the one no other screen can be checked
against, and the one most likely to drift if the rule is ever restated somewhere
else.

**4. Allocations are very large relative to use, and the pinned zone was
nonetheless over budget (as measured 2026-09-05, before 136-01).** Ashvale
Orchards was charged 4,589.61 AF of consumptive use against a 19,101.42 AF
allocation, leaving 14,511.81 AF, a budget three quarters unused. Halvern
Irrigation-Urban GSA, on the other hand, ended the year at **−136.03 AF**. Both
were correct arithmetic on the numbers seeded. 136-01 changed what "Remaining"
subtracts and which plans count (the paragraph at the top of this section):
those two rows read 2,901.42 and 911.58 after it.

136-02 then re-sized the allocations, and the gap closed. Ashvale Orchards now
holds **957.22 AF** of groundwater allocation and pumps none of it, so its
Remaining is the whole 957.22: still unused, but a plausible district-scale
figure rather than a budget nobody could spend. Halvern Irrigation-Urban GSA is
unchanged at 750.32 AF and 911.58 AF, because it is the one district whose rate
was already 2.00 acre-feet per acre. Two of the six district-years now sit over
budget on allocation alone, and both are the dry one: Halvern Valley GSA by
332.58 AF and Verdano Island by 31.71 AF. The attention strip counts 4 accounts
over budget in the wet year and 5
in the dry one, which is what a demonstration of a groundwater budget needs to
show and what the 2026-09-05 figures could not.

---


---

## Section 2: The parcel detail pane (15 figures)

**Rewritten 2026-09-06 by 137-01.** Before this plan the pane stated TWO
balances that could disagree (ISS-148): a card near the top read supplies minus
gross consumptive use, and a residual near the bottom read the full mass-balance
identity, and the two differed by exactly the recharge and storage terms. 137-01
removed the card, the "Net consumptive demand" sentence, the three supply
composition cards and the seven-row supply-vs-use table, twenty figure sites
retired in all, and replaced them with ONE `.budget-panel`: three segments
(Supplies, Uses, Residual) and a two-line foot, nine figure sites. It also added
a new figure, `unmet_demand_af` (ISS-157), which renders one line under the
panel on a field whose consumptive use no supply on record explains. Net: 20
sites retired, 15 added, five fewer than before. The retirement follows the same
procedure 136-01 used for the use-ledger footer's net (`docs/figure-ledger-2026-09.md`
at commit `b55fb80`): every retired id is named below, and every new id was
assigned by `scripts/figure_inventory.py` in template order, never by hand.

**Screens.** `/parcels/11/`, `/parcels/32/` and `/parcels/17/`, each with an
explicit `?period=`. This is the pane a person lands on when they click a use
area in the parcel workspace, and the same body is served on the parcel's own
page. The pane now carries a period control (ISS-147, 137-01 Task 3): `?period=<pk>` is honoured on all three render paths, and a screen's pin is
therefore its URL, not just its parcel.

**Pinned instances, and why there are three.** This pane renders once per
parcel, 76 times over, in either of two years. One pin would have checked the
arithmetic and shown nothing about the two things this plan changed: the
unmet-demand figure, which renders on some fields and not others, and the
Recharge foot cell, which reads zero on most parcels and something else on a
few. So three parcels are pinned, and a fourth capture of one of them:

* **`MER-APN-011`, Saddlebow Ag Holdings, the ISS-157 instance.** A no-well
  field. Its balance panel reads Supplies **32.89 AF**, Uses **363.26 AF**,
  Residual **&minus;330.37 AF**, Deficit, in WY 2025-2026 (period id 2, the dry
  year), and the new line underneath reads *Water use recorded, no supply
  reported: 330.37 AF*. Captured three ways: `?period=2` (the primary pin),
  `?period=1` (the wet year, where the same line reads 181.57 AF instead of
  disappearing, the finding named in "What section 2 found" item 2 below) and
  with no `?period=` at all, to prove the ISS-147 default now resolves to the
  dry year for this parcel without being asked.
* **`MER-APN-032`, Ashvale Orchards Inc., the recharge instance.** The one
  pinned parcel-year where the Uses foot's Recharge cell is non-zero
  (174.13 AF), so a wrong subtraction there, or in the Uses segment total that
  includes it, could actually fail. This was the DISAGREEING pinned instance
  for the retired card-vs-residual comparison before 137-01; it is repinned
  here for the recharge case the panel's foot still needs exercised. Also
  carries the pane's other five figures (Area, well share, first ledger row),
  pinned here rather than to `MER-APN-011` because `MER-APN-011` has no well
  to show one.
* **`MER-APN-017`, Saddlebow Ag Holdings, the plain instance.** No recharge, no
  storage change, no unmet demand: the panel's ordinary case, given as a full
  second worked example rather than a bare comparison table.

All five pages were captured signed in, at commit `a320e77` (the last commit
before this plan's ledger pass), 2026-09-06, and all five answered 200. Saved
under `audit/figure_ledger/rendered/parcel-detail-mer-apn-011-dry.html`,
`-wet.html`, `-default.html`, `parcel-detail-recharge-mer-apn-032.html` and
`parcel-detail-plain-mer-apn-017.html`, with sizes and content fingerprints in
`manifest.json` beside them. Every captured page's `<title>` was checked against
its pinned parcel number before anything else ran: the dev database holds the
candidate's own primary keys, so a pinned id can silently point at a different
row, and all five titles matched.

**The pane now has a period control (ISS-147), and the default changed with
it.** Before 137-01, `?period=` was ignored (observed by diffing three captures
of one parcel byte for byte); the pane picked a year for the reader by the most
recent period with any non-allocation ledger activity, which put six curtailed
fields (MER-APN-010/011/012/013/014/019) on the wrong year. 137-01 Task 3
changed the default to the most recent period the parcel has a CalculationRun
in, falling back to the old rule and then to the most recent period overall.
Reproduced here: with no `?period=` given, all 76 parcels still resolve, 0 to
WY 2024-2025 and 76 to WY 2025-2026 (`CHK-parcels-080`, `CHK-parcels-081`), and
of the six ISS-147 parcels named above, all six now resolve to WY 2025-2026
(`CHK-parcels-082`, expected and observed: 6). `MER-APN-011`'s own default
capture is byte-identical to its `?period=2` capture apart from the one-time
security token, confirming the observation for that parcel directly rather than
only through the SQL.

**Recomputation.** `audit/figure_ledger/sql/parcel_detail_pane.sql` for the
balance panel's nine segment and foot figures and the pane's five unrelated
attribute figures (Area, well share, first ledger row, the unreachable
ET-not-computed branch), and the new
`audit/figure_ledger/sql/parcel_unmet_demand.sql` for `unmet_demand_af`, both
run on the host with `bash audit/figure_ledger/run_sql.sh`. Neither file's
underlying identity changed from before 137-01: the segments and foot cells are
`parcel_mass_balance`'s existing terms, reused rather than rewritten, and the
unmet-demand file is new arithmetic entirely independent of the mass balance.
Both name tables and columns only.

---

### The ledger, pinned to `MER-APN-011` (the ISS-157 instance, WY 2025-2026) and `MER-APN-032` (the recharge instance)

| `id` | `screen` | `site` | `label` | `context_var` | `view` | `service` | `raw_tables` | `rendered` | `recomputed` | `delta` | `verdict` | `notes` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `FIG-parcels-001` | `/parcels/11/?period=2` | `templates/parcels/partials/_detail_pane.html:102` | Supplies (segment) | `mass_balance.inputs_total` | `parcels/views.py:176` | `parcel_mass_balance` | `parcels_parcelledger, accounting_calculationrun` | 32.89 | 32.89 | MATCH | MATCH | Independence: restatement. Rain alone: this no-well field took no canal delivery and has no pumping to show. New field, added by 137-01: `inputs_total` did not exist on `parcel_mass_balance`'s return dict before this plan; it sums the same three inputs the foot cells below print. |
| `FIG-parcels-005` | `/parcels/11/?period=2` | `templates/parcels/partials/_detail_pane.html:113` | Uses (segment) | `mass_balance.outputs_total` | `parcels/views.py:176` | `parcel_mass_balance` | `accounting_calculationrun` | 363.26 | 363.26 | MATCH | MATCH | Independence: restatement. Gross ET alone: no recharge, no storage change on this field-year. New field, added by 137-01, summing the three outputs below. |
| `FIG-parcels-009` | `/parcels/11/?period=2` | `templates/parcels/partials/_detail_pane.html:133` | Residual (segment) | `mass_balance.residual_af` | `parcels/views.py:176` | `parcel_mass_balance` | `parcels_parcelledger, accounting_calculationrun` | -330.37 | -330.37 | MATCH | MATCH | Independence: restatement. The same identity `mass_balance.residual_af` computed before 137-01 (the old free-standing "Residual: N AF" row, `FIG-parcels-015` in the pre-137-01 numbering); only its position on the screen moved, into this segment, with the badge now rendered inside it. Equals the negative of the unmet-demand figure below on this field, because a no-well field with no other supply has nowhere else for the shortfall to go. |
| `FIG-parcels-002` | `/parcels/11/?period=2` | `templates/parcels/partials/_detail_pane.html:105` | Foot: Surface | `mass_balance.inputs.surface` | `parcels/views.py:176` | `parcel_mass_balance` | `parcels_parcelledger` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. A real zero: this field took no canal delivery in the year. |
| `FIG-parcels-003` | `/parcels/11/?period=2` | `templates/parcels/partials/_detail_pane.html:106` | Foot: Groundwater | `mass_balance.inputs.gw_recovered` | `parcels/views.py:176` | `parcel_mass_balance` | `parcels_parcelledger` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. A real zero: this field has no well, which is the whole of ISS-157's story. |
| `FIG-parcels-004` | `/parcels/11/?period=2` | `templates/parcels/partials/_detail_pane.html:107` | Foot: Rain | `mass_balance.inputs.precip` | `parcels/views.py:176` | `parcel_mass_balance` | `accounting_calculationrun` | 32.89 | 32.89 | MATCH | MATCH | Independence: restatement. The field's only recorded supply. |
| `FIG-parcels-006` | `/parcels/11/?period=2` | `templates/parcels/partials/_detail_pane.html:116` | Foot: Consumptive use | `mass_balance.outputs.et` | `parcels/views.py:176` | `parcel_mass_balance` | `accounting_calculationrun` | 363.26 | 363.26 | MATCH | MATCH | Independence: restatement. Gross satellite-estimated evapotranspiration, summed over the parcel's runs in the period. |
| `FIG-parcels-007` | `/parcels/11/?period=2` | `templates/parcels/partials/_detail_pane.html:117` | Foot: Recharge | `mass_balance.outputs.recharge` | `parcels/views.py:176` | `parcel_mass_balance` | `accounting_calculationrun` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. A real measured zero, not the old fixed placeholder: this term reads out of each run's stored `clamp_floor` step and can be non-zero, as it is on `MER-APN-032` below. |
| `FIG-parcels-008` | `/parcels/11/?period=2` | `templates/parcels/partials/_detail_pane.html:118` | Foot: Storage change | `mass_balance.outputs.delta_storage` | `parcels/views.py:176` | `parcel_mass_balance` | `accounting_calculationrun` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. Credit banked less credit drawn. Zero here, and zero on all 152 parcel-years measured (`CHK-parcels-053`). |
| `FIG-parcels-010` | `/parcels/11/?period=2` | `templates/parcels/partials/_detail_pane.html:183` | Water use recorded, no supply reported | `unmet_demand_af` | `parcels/views.py:183` | `parcel_unmet_demand` | `accounting_calculationrun` | 330.37 | 330.37 | MATCH | MATCH | Independence: separate recomputation, `audit/figure_ledger/sql/parcel_unmet_demand.sql`, never touching the mass-balance identity above. New figure (ISS-157): the platform's engine has always recorded this on a no-well field's runs (`residual_disposition="unmet_demand"`); 137-01 is the first screen to read it back. Renders only because it is positive; DESIGN.md rule 8 says a zero here prints nothing. |
| `FIG-parcels-011` | `/parcels/32/?period=2` | `templates/parcels/partials/_detail_pane.html:242` | ET-not-computed branch: surface (branch not rendered) | `consumptive_balance.supplies.surface` | `parcels/views.py:175` | `parcel_consumptive_balance` | `parcels_parcelledger` | not rendered | 719.30 | NO VALUE | UNVERIFIED | **This figure could not be checked, because nothing on this platform can currently display it.** It sits in the branch shown only when a parcel has no calculation runs for the year, and every one of the 76 parcels has runs in both years (`CHK-parcels-070`, `CHK-parcels-071`, both zero). The value it would print is recomputed and recorded, so the day the branch becomes reachable the number is already on file. Unchanged by 137-01 apart from its id and line number. |
| `FIG-parcels-012` | `/parcels/32/?period=2` | `templates/parcels/partials/_detail_pane.html:243` | ET-not-computed branch: groundwater (branch not rendered) | `consumptive_balance.supplies.groundwater` | `parcels/views.py:175` | `parcel_consumptive_balance` | `parcels_parcelledger` | not rendered | 0.00 | NO VALUE | UNVERIFIED | Same branch, same reason as `FIG-parcels-011`. |
| `FIG-parcels-013` | `/parcels/32/?period=2` | `templates/parcels/partials/_detail_pane.html:280` | Area (Acres) | `ef.value` | `parcels/views.py:202` | `— (model field, read at parcels/views.py:202)` | `parcels_parcel` | 154.69 | 154.69 | MATCH | MATCH | Independence: restatement of a stored value, which is the weakest kind of check there is and is stated as such. Unchanged by 137-01 apart from its id and line number. |
| `FIG-parcels-014` | `/parcels/32/?period=2` | `templates/parcels/partials/_detail_pane.html:330` | … fraction (Related wells) | `wip.fraction` | `parcels/views.py:115` | `— (model field, fetched at parcels/views.py:115)` | `wells_wellirrigatedparcel` | 1.00 | 1.00 | MATCH | MATCH | Independence: restatement of a stored value. Pinned to `MER-APN-032` rather than the primary instance because `MER-APN-011` has no well linked (ISS-157: that is the whole reason it carries unmet demand), so its Related wells card has nothing to show. |
| `FIG-parcels-015` | `/parcels/32/?period=2` | `templates/parcels/partials/_detail_pane.html:405` | Amount (AF), first row of Recent ledger entries | `entry.amount_acre_feet` | `parcels/views.py:116` | `— (model field, fetched at parcels/views.py:116)` | `parcels_parcelledger` | -75.23 | -75.23 | MATCH | MATCH | Independence: restatement of a stored value. Note this list is NOT scoped to the year the balance panel above it is showing, so the two halves of the pane can be describing different spans of time; unchanged since before 137-01. Site line moved from :402 to :405 at 143-05's second checkpoint (2026-09-12), when the card's Source column became the merged Water column; the value did not move. |

### The same nine balance-panel figures, `MER-APN-011` in the wet year and `MER-APN-032`, `MER-APN-017` in the dry year

This table is a comparison, not a second set of ledger rows: the ledger carries
one row per figure and that is the table above. The identifiers here are
references back to it. The `site`, `context_var`, `view`, `service` and
`raw_tables` columns are the same line of the same template rendered for a
different parcel or period, so they are identical to the table above and are
not repeated. What changes is the numbers.

| `id` | `screen` | `label` | `rendered` | `recomputed` | `delta` | `verdict` | `notes` |
|---|---|---|---|---|---|---|---|
| FIG-parcels-001 | `/parcels/11/?period=1` | Supplies (segment) | 224.64 | 224.64 | MATCH | MATCH | `MER-APN-011`, WY 2024-2025 (the wet year). |
| FIG-parcels-005 | `/parcels/11/?period=1` | Uses (segment) | 406.21 | 406.21 | MATCH | MATCH | |
| FIG-parcels-009 | `/parcels/11/?period=1` | Residual (segment) | -181.57 | -181.57 | MATCH | MATCH | |
| FIG-parcels-002 | `/parcels/11/?period=1` | Foot: Surface | 161.78 | 161.78 | MATCH | MATCH | Non-zero, unlike the dry year: this field DID take a canal delivery in the wet year. |
| FIG-parcels-003 | `/parcels/11/?period=1` | Foot: Groundwater | 0.00 | 0.00 | MATCH | MATCH | Still no well, both years. |
| FIG-parcels-004 | `/parcels/11/?period=1` | Foot: Rain | 62.85 | 62.85 | MATCH | MATCH | |
| FIG-parcels-006 | `/parcels/11/?period=1` | Foot: Consumptive use | 370.26 | 370.26 | MATCH | MATCH | |
| FIG-parcels-007 | `/parcels/11/?period=1` | Foot: Recharge | 35.95 | 35.95 | MATCH | MATCH | Non-zero, unlike the dry year. |
| FIG-parcels-008 | `/parcels/11/?period=1` | Foot: Storage change | 0.00 | 0.00 | MATCH | MATCH | |
| FIG-parcels-010 | `/parcels/11/?period=1` | Water use recorded, no supply reported | 181.57 | 181.57 | MATCH | MATCH | **Renders in the wet year too**, at a smaller figure. See finding 2 below: the checkpoint this plan was scoped against expected the line to disappear here, and it does not. |
| FIG-parcels-001 | `/parcels/32/?period=2` | Supplies (segment) | 765.41 | 765.41 | MATCH | MATCH | `MER-APN-032`, the recharge instance, WY 2025-2026. |
| FIG-parcels-005 | `/parcels/32/?period=2` | Uses (segment) | 765.41 | 765.41 | MATCH | MATCH | |
| FIG-parcels-009 | `/parcels/32/?period=2` | Residual (segment) | 0.00 | 0.00 | MATCH | MATCH | Inside the 0.01 AF Balanced band. |
| FIG-parcels-002 | `/parcels/32/?period=2` | Foot: Surface | 719.30 | 719.30 | MATCH | MATCH | |
| FIG-parcels-003 | `/parcels/32/?period=2` | Foot: Groundwater | 0.00 | 0.00 | MATCH | MATCH | |
| FIG-parcels-004 | `/parcels/32/?period=2` | Foot: Rain | 46.11 | 46.11 | MATCH | MATCH | |
| FIG-parcels-006 | `/parcels/32/?period=2` | Foot: Consumptive use | 591.28 | 591.28 | MATCH | MATCH | |
| FIG-parcels-007 | `/parcels/32/?period=2` | Foot: Recharge | 174.13 | 174.13 | MATCH | MATCH | **The non-zero case.** Before 137-01 this was the exact term the pane's two balances disagreed over (ISS-148); the panel now states it once, in the Uses total, and nowhere else. |
| FIG-parcels-008 | `/parcels/32/?period=2` | Foot: Storage change | 0.00 | 0.00 | MATCH | MATCH | |
| FIG-parcels-001 | `/parcels/17/?period=2` | Supplies (segment) | 395.97 | 395.97 | MATCH | MATCH | `MER-APN-017`, the plain instance, WY 2025-2026. |
| FIG-parcels-005 | `/parcels/17/?period=2` | Uses (segment) | 263.07 | 263.07 | MATCH | MATCH | |
| FIG-parcels-009 | `/parcels/17/?period=2` | Residual (segment) | 132.90 | 132.90 | MATCH | MATCH | The same value the pane's two identities already agreed on before 137-01, because this parcel banks no recharge. |
| FIG-parcels-002 | `/parcels/17/?period=2` | Foot: Surface | 0.00 | 0.00 | MATCH | MATCH | A real zero: this parcel took no canal delivery and met its demand by pumping. |
| FIG-parcels-003 | `/parcels/17/?period=2` | Foot: Groundwater | 368.34 | 368.34 | MATCH | MATCH | |
| FIG-parcels-004 | `/parcels/17/?period=2` | Foot: Rain | 27.64 | 27.64 | MATCH | MATCH | |
| FIG-parcels-006 | `/parcels/17/?period=2` | Foot: Consumptive use | 263.07 | 263.07 | MATCH | MATCH | |
| FIG-parcels-007 | `/parcels/17/?period=2` | Foot: Recharge | 0.00 | 0.00 | MATCH | MATCH | Zero, which is why this parcel's Residual matched the pre-137-01 card exactly. |
| FIG-parcels-008 | `/parcels/17/?period=2` | Foot: Storage change | 0.00 | 0.00 | MATCH | MATCH | |
| FIG-parcels-010 | `/parcels/17/?period=2` | Water use recorded, no supply reported | not rendered | 0.00 | NO VALUE | MATCH | Has a well; zero on the disposition the figure sums. The line correctly does not render (DESIGN.md rule 8: a zero prints nothing). |

---

### What section 2 found

**Every one of the fifteen figures agrees with the rows behind it, to the cent,
on every pinned screen.** Nothing on this pane computes a wrong number, before
137-01 or after it. That was already true of the pane's old twenty figures
(eighteen matched, two were unreachable); this plan changed which figures the
screen shows, not the correctness of any of them.

Three things the reconciliation turned up.

#### 1. ISS-148 is closed: the pane now states one balance, and there is nothing left to disagree with

Before 137-01 the pane printed two identities four inches apart on the same
screen. On the pinned recharge instance, `MER-APN-032`, the retired card read a
surplus of 174.13 AF and the retired residual row read 0.00 AF, Balanced, over
the same field-year, differing by exactly the Recharge term (`CHK-parcels-054`
on the old basis). The old ledger measured this at 32 of 76 wet-year parcels
and 24 of 76 dry-year parcels disagreeing in sign, on the reasoning laid out in
`docs/figure-ledger-2026-09.md`'s pre-137-01 section 2.

137-01 removed the card, the composition cards, the summary table and the
free-standing residual row, and kept the mass balance alone as the panel's one
statement: Supplies minus Uses equals Residual, with the badge inside the
Residual segment because that is the number it judges. The design decision and
its rejected alternatives are recorded in the panel's own template comment and
in `.planning/ISSUES.md`'s ISS-148 entry. On `MER-APN-032` the panel now shows
Uses **765.41 AF**, of which the foot names 174.13 AF as Recharge, so the same
water that used to read as an unaccounted surplus in one place and a closed
book in another now reads once, as part of what the field's uses spent.

**This is not a claim that recharge water is well understood everywhere.** The
missing bookkeeping term for pumped water that percolates (as opposed to canal
water, which already has one) is ISS-139, unchanged and still open; see section
6, "The meter measures pumping, and the books have nowhere to put the
difference." 137-01 closed the SCREEN issue (two numbers, one page, disagreeing)
without touching the MODEL issue (one output term, still missing for one supply
source). The residual size and sign on every affected parcel-year are unchanged
by this plan: only how many times, and where, the pane states them.

#### 2. The unmet-demand line renders in both years on `MER-APN-011`, not only the dry one

This plan's own checkpoint text assumed the ISS-157 line would disappear on the
wet-year capture of the pinned parcel. It does not: `MER-APN-011` carries
181.57 AF of unmet demand in WY 2024-2025 and 330.37 AF in WY 2025-2026, both
positive, both rendering. Measured whole-column: six parcels carry unmet demand
in EACH year (`audit/figure_ledger/sql/parcel_unmet_demand.sql`, block D), the
same six named in ISS-157 (MER-APN-010/011/012/013/014/019), totalling
962.6696 AF in the wet year and 1,986.5015 AF in the dry one (block A). The
figure is real and correctly computed either year; the plan text's expectation
about which screen would show it, not the platform, was wrong. Recorded here so
a later reader does not go looking for a bug that is not there.

#### 3. The pane's period control now resolves the six ISS-147 parcels correctly, and the whole-column proof travels with the plan rather than by hand

Before 137-01, `?period=` did nothing (observed by byte-diffing three captures
of one parcel) and the pane's silent default put six curtailed fields on the
wrong water year. 137-01 Task 3 fixed the default and added the control; this
section's SQL reproduces the new four-step resolution independently
(`resolved_period` in `parcel_detail_pane.sql`) rather than trusting the six
named parcels by inspection. All 76 parcels resolve to WY 2025-2026 with no
`?period=` given (`CHK-parcels-081`), and specifically all six of the ISS-147
parcels do (`CHK-parcels-082`, expected and observed: 6 of 6). `MER-APN-011`'s
own default capture is byte-identical to its explicit `?period=2` capture
(apart from the one-time security token), so this is not resting on the SQL's
transcription of the view alone.

---

**Carried forward from before 137-01, unchanged.** The pane's remaining
UNVERIFIED figures (`FIG-parcels-011`, `-012`, the ET-not-computed branch) are
still unreachable for the same reason: every one of the 76 parcels has
calculation runs in both years (`CHK-parcels-070`, `CHK-parcels-071`, both
zero). The double-counting guard against a satellite estimate and a calculated
figure both landing on one month is still inert on this data: there are zero
satellite-estimate rows in the whole database (`CHK-parcels-060`). Both cautions
apply exactly as they did before this plan; no reader should take either as
tested by its continued presence here.

---

## Section 3: The money layer (37 figures, 31 until 143-01 added the Use area table's footer)

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
| `/accounting/accounts/12/?period=2` | `009`–`026` (`009`–`020` until 143-01 added the Use area table's footer) | MER-ACCT-001, Ashvale Orchards Inc., the same account section 1 pinned. Per-parcel row: MER-APN-021. |
| `/accounting/calculation-run/16/2026-03/` | `001`–`008` | MER-APN-016, March 2026. Chosen because effective rainfall actually bites there, so the step table's In and Out columns differ instead of repeating one number. |
| `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `049`–`052` (`050`–`053` until 136-01) | The same parcel-month as the run page, deliberately. |
| `/accounting/ledger/?period=2` | `046`–`048` (`046`–`049` until 136-01 retired the footer's net) | First entry row on screen; default sort, page size 100. |
| `/accounting/allocations/?period=2` | `027`, `028` (`021`, `022` until 143-01) | The Halvern Irrigation-Urban GSA groundwater allocation for WY 2025-2026. |
| `/accounting/reporting-periods/2/` | `053` (`054` until 136-01) | The Halvern Valley GSA groundwater allocation for WY 2025-2026. |

The wet year, `/accounting/accounts/12/?period=1`, was captured as a second
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

**Re-captured at commit `2555a68`**, 2026-09-06, after 136-02 re-sized the
groundwater allocations and the rebuilt demonstration data renumbered the pinned
account from 78 to 12. Two figures in this section moved,
`FIG-accounting-028` and `FIG-accounting-065`, and both are allocation totals;
nothing on the calculation, balance or ledger screens changed by a cent.

**First captured at commit `9f9e27b2543516a95cdc15743070e3746d04ddbe`**,
2026-09-05. The database was left exactly as found: 4 user rows before the
capture and 4 after.

**Two notes on how to read the ledger.**

Three rows carried a verdict of the form `MATCH · ISS-155` on 2026-09-05 (a
fourth row, `FIG-accounting-028`, carries `MATCH · ISS-156` and still does).
That was not a hedge. The number rendered agreed with the independent
recomputation to the cent, so the arithmetic was right, and a separate issue was
raised against the words printed beside it. 136-01 resolved ISS-155 on
2026-09-06: the footer's net row is retired and the two subtotals are named by
kind, so those rows now read `MATCH` and every id after the retired one moved up
by one.

The two pinned allocations are named here by their zone, water type and year,
which identify the row uniquely; `accounting_detail.sql` and
`extract_section_a.py` carry the stored names character for character, because
they have to match.

---

### The ledger

| `id` | `screen` | `site` | `label` | `context_var` | `view` | `service` | `raw_tables` | `rendered` | `recomputed` | `delta` | `verdict` | `notes` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `FIG-accounting-001` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:59` | acres | `parcel.area_acres` | `accounting/views.py:1231` | `— (model field)` | `parcels_parcel` | 149.73 | 149.73 | MATCH | MATCH | Independence: restatement. Read straight off the parcel row the view fetched. It is not an independent quantity, but it is load-bearing, because every acre-foot figure on this page is this number times a millimetre of rainfall or evaporation. |
| `FIG-accounting-002` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:67` | Billable groundwater | `run.final_af` | `accounting/views.py:1232` | `— (model field, written by accounting/management/commands/run_calculations.py:272)` | `accounting_calculationrun` | 27.9945 | 27.9945 | MATCH | MATCH | Independence: different identity. Also checked against the magnitude of the `calculated` ledger row for the same parcel-month, which is what the page's own result card claims it equals (agrees to 0.0000), and against the last step of the waterfall, likewise 0.0000. |
| `FIG-accounting-003` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:100` | In (AF) | `step.input_af` | `accounting/views.py:1266` | `— (read out of the stored breakdown)` | `accounting_calculationrun` | 0.0000 | 0.0000 | MATCH | MATCH | Independence: restatement, plus a whole-table identity. Pinned to step 1, which starts at zero. Every one of the five steps was also checked for continuity, each step's In against the step above it's Out, and none breaks. |
| `FIG-accounting-004` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:101` | Out (AF) | `step.output_af` | `accounting/views.py:1267` | `— (read out of the stored breakdown)` | `accounting_calculationrun, datasync_openetcache, parcels_parcel` | 39.8491 | 39.8491 | MATCH | MATCH | Independence: **different identity**. Rebuilt from the raw satellite reading, 81.119346 mm of evapotranspiration over 149.73 acres divided by 304.8, without reading the stored figure at all. The recomputation could have disagreed and did not. |
| `FIG-accounting-005` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:115` | Deposited this month | `run.banked_af` | `accounting/views.py:1232` | `— (model field)` | `accounting_calculationrun` | *(not rendered)* | 0.0000 | NO VALUE | UNVERIFIED | The whole banked-water block sits behind a condition no row in this database satisfies: **0 of 1,824 calculation runs** carry a non-zero deposit or draw. Nothing was on screen to read. The stored value is 0.0000, and that is not the same claim. |
| `FIG-accounting-006` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:119` | Drawn down this month | `run.drawn_af` | `accounting/views.py:1232` | `— (model field)` | `accounting_calculationrun` | *(not rendered)* | 0.0000 | NO VALUE | UNVERIFIED | Same block, same reason. |
| `FIG-accounting-007` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:135` | Drawn (AF) | `draw.amount_af` | `accounting/views.py:1273` | `— (queryset)` | `accounting_watercreditdraw` | *(not rendered)* | *(no rows)* | NO VALUE | UNVERIFIED | Nested one level deeper still: the draws table needs a `WaterCreditDraw` row and **there are none**, though five water-credit rows are held. |
| `FIG-accounting-008` | `/accounting/calculation-run/16/2026-03/` | `templates/accounting/calculation_run_detail.html:153` | Final billable groundwater | `run.final_af` | `accounting/views.py:1232` | `— (model field)` | `accounting_calculationrun` | 27.9945 | 27.9945 | MATCH | MATCH | Independence: different identity, as `FIG-accounting-002`. The page states this figure twice, at the top and at the foot; both render the same value, which is a thing the page could get wrong and does not. |
| `FIG-accounting-009` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:47` | Supplies | `balance.supply_total` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun, accounting_wateraccountparcel` | 5,921.09 | 5921.09 | MATCH | MATCH | Independence: restatement. The gross-estimate suppression is stated as its own predicate in the recomputation; it removes 0 rows here, for the reason in finding 2. Site moved from `:11` to `:23` when 143-01 wrapped the panel row in `.budget-panel-body` and added per-segment captions (R-037); the id did not move. |
| `FIG-accounting-013` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:66` | Consumptive use | `balance.consumptive_use_gross` | `accounting/views.py:630` | `account_consumptive_balance` | `accounting_calculationrun` | 4,589.61 | 4589.61 | MATCH | MATCH | Independence: **different identity**. Rebuilt over all 216 of this account's parcel-months from the raw satellite readings and the parcels' acreage, never touching the stored evapotranspiration column. Agrees to the cent. Site moved from `:16` to `:29` (143-01); the id did not move. |
| `FIG-accounting-014` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:83` | Balance | `balance.net_vs_supply` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 1,331.48 | 1331.48 | MATCH | MATCH | Independence: restatement. Supplies minus consumptive use, both above. Site moved from `:21` to `:35` (143-01); the id did not move. |
| `FIG-accounting-010` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:58` | Surface | `balance.supplies.surface` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger` | 5,500.97 | 5500.97 | MATCH | MATCH | Independence: restatement. Magnitude of the canal-delivery rows, which the platform stores as negative numbers by its own production convention. Site moved from `:25` to `:47` when 143-01 replaced the bare `.budget-panel-foot` with a titled "Supplies by source" breakdown (R-037); the id did not move, and the row is now also repeated verbatim by the Use area table's footer, `FIG-accounting-021`. |
| `FIG-accounting-011` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:59` | Groundwater | `balance.supplies.groundwater` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. A real zero, not a suppression: 216 calculation runs sit behind this account in the period and not one groundwater or meter row. Site moved from `:26` to `:48` (143-01); the id did not move, and the row is now also repeated verbatim by `FIG-accounting-022`. |
| `FIG-accounting-012` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:60` | Rain | `balance.supplies.precip` | `accounting/views.py:630` | `account_consumptive_balance` | `accounting_calculationrun` | 420.12 | 420.12 | MATCH | MATCH | Independence: **different identity**. Rebuilt over the same 216 parcel-months from raw rainfall and evapotranspiration through the published USDA-SCS TR-21 formula, transcribed into the recomputation with its source lines. Agrees to the cent. Site moved from `:27` to `:49` (143-01); the id did not move, and the row is now also repeated verbatim by `FIG-accounting-023`. |
| `FIG-accounting-015` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:158` | Surface | `pb.surface` | `accounting/views.py:647` | `parcel_consumptive_balance` | `parcels_parcelledger` | 210.17 | 210.17 | MATCH | MATCH | Independence: restatement. Was `FIG-accounting-016` before 143-01 reordered the Use area table's columns into equation order (Surface, Groundwater, Rain, Total, Consumptive use, Balance, R-039) under a bracketed "Supplies" group header. |
| `FIG-accounting-016` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:161` | Groundwater | `pb.groundwater` | `accounting/views.py:648` | `parcel_consumptive_balance` | `parcels_parcelledger` | 0.00 | 0.00 | MATCH | MATCH | Independence: restatement. Was `FIG-accounting-017` before 143-01's column reorder (R-039). |
| `FIG-accounting-017` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:164` | Rain | `pb.precip` | `accounting/views.py:649` | `parcel_consumptive_balance` | `accounting_calculationrun` | 17.92 | 17.92 | MATCH | MATCH | Independence: restatement. Was `FIG-accounting-018` before 143-01's column reorder; label renamed from Precip to Rain (DESIGN.md rule 6, R-039). |
| `FIG-accounting-018` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:167` | Total | `pb.supply_total` | `accounting/views.py:650` | `parcel_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 228.09 | 228.09 | MATCH | MATCH | Independence: restatement, plus a **different identity** the code could fail. The per-parcel table is built one parcel at a time while the panel above it is built in a single pass over all eighteen; the two agree only if the gross-estimate suppression really is per-parcel. Summed whole-column, all four supply and use columns land on the panel exactly: difference 0.00. Was `FIG-accounting-019` before 143-01's column reorder; label renamed from "Supplies" to "Total" now that "Supplies" is the bracketed group header over all four columns (DESIGN.md → *Tables that explain their numbers*, rule 2). |
| `FIG-accounting-019` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:170` | Consumptive use | `pb.consumptive_use_gross` | `accounting/views.py:645` | `parcel_consumptive_balance` | `accounting_calculationrun` | 177.23 | 177.23 | MATCH | MATCH | Independence: restatement. Pinned to MER-APN-021. The whole column was also summed and held against the panel above it; see `FIG-accounting-018`'s note. Was `FIG-accounting-015` before 143-01 moved this column to fifth position, ahead of Balance only (R-039); label recased from "Consumptive Use" to "Consumptive use" (sentence case). |
| `FIG-accounting-020` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:173` | Balance | `pb.net_vs_supply` | `accounting/views.py:651` | `parcel_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 50.87 | 50.87 | MATCH | MATCH | Independence: restatement. The id did not move (last column before and after R-039's reorder); label renamed from Net to Balance (DESIGN.md rule 6). |
| `FIG-accounting-021` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:194` | All 18 assigned use areas › Surface | `balance.supplies.surface` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger` | 5,500.97 | 5500.97 | MATCH | MATCH | New site, 143-01 (2026-09-08): the Use area breakdown table's footer, added so the panel and the table are visibly one thing (R-039). It renders the SAME context value as `FIG-accounting-010` above, one variable and one number, so the recomputation at that row is the recomputation here. What makes the rows addable (DESIGN.md → *Tables that explain their numbers*, rule 5): one quantity, one period, every use area assigned to this account (eighteen, per MER-ACCT-001's own parcel-assignment count in this section's own screens note above), and the footer's label says so. |
| `FIG-accounting-022` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:195` | All 18 assigned use areas › Groundwater | `balance.supplies.groundwater` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger` | 0.00 | 0.00 | MATCH | MATCH | New site, 143-01 (2026-09-08). Renders the SAME context value as `FIG-accounting-011` above; same independence and same addability note as `FIG-accounting-021`. |
| `FIG-accounting-023` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:196` | All 18 assigned use areas › Rain | `balance.supplies.precip` | `accounting/views.py:630` | `account_consumptive_balance` | `accounting_calculationrun` | 420.12 | 420.12 | MATCH | MATCH | New site, 143-01 (2026-09-08). Renders the SAME context value as `FIG-accounting-012` above; same independence and same addability note as `FIG-accounting-021`. |
| `FIG-accounting-024` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:197` | All 18 assigned use areas › Total | `balance.supply_total` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun, accounting_wateraccountparcel` | 5,921.09 | 5921.09 | MATCH | MATCH | New site, 143-01 (2026-09-08). Renders the SAME context value as `FIG-accounting-009` above; same independence and same addability note as `FIG-accounting-021`. |
| `FIG-accounting-025` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:198` | All 18 assigned use areas › Consumptive use | `balance.consumptive_use_gross` | `accounting/views.py:630` | `account_consumptive_balance` | `accounting_calculationrun` | 4,589.61 | 4589.61 | MATCH | MATCH | New site, 143-01 (2026-09-08). Renders the SAME context value as `FIG-accounting-013` above; same independence and same addability note as `FIG-accounting-021`. |
| `FIG-accounting-026` | `/accounting/accounts/12/?period=2` | `templates/accounting/partials/_account_balances.html:199` | All 18 assigned use areas › Balance | `balance.net_vs_supply` | `accounting/views.py:630` | `account_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 1,331.48 | 1331.48 | MATCH | MATCH | New site, 143-01 (2026-09-08). Renders the SAME context value as `FIG-accounting-014` above; same independence and same addability note as `FIG-accounting-021`. `tests/test_account_balances.py` holds the footer's own six cells equal to the panel's, so this row and the panel row cannot drift apart unnoticed. |
| `FIG-accounting-027` | `/accounting/allocations/?period=2` | `templates/accounting/partials/_allocations_list_results.html:34` | Allocation (AF) | `alloc.allocation_acre_feet` | `accounting/views.py:478` | `— (model field; queryset built at accounting/views.py:454)` | `accounting_allocationplan` | 750.32 | 750.32 | MATCH | MATCH | Independence: restatement. The same 750.32 the dashboard's zone table shows for this zone, on a second screen. |
| `FIG-accounting-028` | `/accounting/allocations/?period=2` | `templates/accounting/partials/_allocations_list_results.html:61` | Surface Water · 5 allocations | `subtotal.total` (loop `subtotal in allocation_subtotals`) | `accounting/views.py:534` | `— (queryset aggregate, GROUP BY water type)` | `accounting_allocationplan, accounting_watertype` | 148,500.00 | 148500.00 | MATCH | MATCH | **Re-pointed 2026-09-06 by 138-02, which closed ISS-156.** This site used to render `allocation_total`, one figure that added the surface-water district's diversion entitlement to the groundwater sustainability agency's pumping allowance — 153,121.27 AF at the last capture, 159,671.46 before 136-02 re-sized the groundwater plans. The footer now prints one subtotal per water type and nothing across them, so this row is pinned to the **surface** subtotal, the larger of the two on screen; the groundwater subtotal beside it reads 4,621.27 AF. The recomputation is `alloc_by_water_type` in `audit/figure_ledger/sql/accounting_detail.sql`, which groups the period's plans by water type in SQL and cannot call the view. Independence: restatement, plus the grouping the view no longer sums across. `alloc_total` is kept in that file as the row-count cross-check it always was. See finding 4.
| `FIG-accounting-058` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:464` | Consumptive use | `row.gross_et` | `accounting/views.py:326` | `unmet_demand_by_parcel` | `accounting_calculationrun` | 363.26 | 363.26 | MATCH | MATCH | New figure, 137-02 (ISS-157, surface 2): the dashboard's district-wide list of fields with water use recorded and no supply reported. Pinned to MER-APN-011, WY 2025-2026, the same field and period `FIG-parcels-010` pins on the field's own page. Independence: restatement, the same grouping `dashboard_unmet_demand.sql` recomputes; block D there reproduces this row within the six the section lists. |
| `FIG-accounting-059` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:465` | Not met by supplies (column, under the card title 'Fields with water use recorded and no supply reported') | `row.unmet` | `accounting/views.py:326` | `unmet_demand_by_parcel` | `accounting_calculationrun` | 330.37 | 330.37 | MATCH | MATCH | Same pinned row as above: the 330.37 AF the field's own page also shows (`FIG-parcels-010`), now on the district-wide list. Independence: restatement. |
| `FIG-accounting-060` | `/accounting/dashboard/?period=2` | `templates/accounting/partials/_dashboard_content.html:473` | District total | `unmet_demand_total` | `accounting/views.py:326` | `unmet_demand_by_parcel` | `accounting_calculationrun` | 1,986.50 | 1986.50 | MATCH | MATCH | Sum of the six fields carrying a non-zero shortfall in WY 2025-2026: MER-APN-010, 011, 012, 013, 014, 019. The wet year (period id 1) carries the SAME six fields at 962.67 AF; the plan's premise that the wet year would be silent for unmet demand did not reproduce (137-02-EVIDENCE.md section 3.1), and the empty state is proved instead by the fixture test written for it. Independence: restatement. |
| `FIG-accounting-061` | `/accounting/ledger/?period=2` | `templates/accounting/partials/_ledger_list_results.html:124` | Amount | `entry.amount_acre_feet` | `accounting/views.py:965` | `— (model field)` | `parcels_parcelledger` | -84.76 | -84.7556 | MATCH | MATCH | New site, 143-05 (candidate B): the `{% if entry.amount_acre_feet < 0 %}` branch, added so a negative Amount prints a true minus sign (U+2212) instead of the ASCII hyphen `floatformat` writes. The template strips that hyphen with the `cut` filter and supplies `&minus;` itself as static markup. Same context var and same model field as `FIG-accounting-062`, the sibling `{% else %}` branch for a zero-or-positive amount; exactly one of the two renders per row. Pinned to the first row on screen under the new default order (143-05, R-020: `-effective_date, parcel__parcel_number, -created_at`), a surface diversion on MER-APN-001 dated 15 September 2026. Independence: restatement. Site line moved from :120 to :124 at 143-05's second checkpoint, when the Source and Water type columns merged into one Water column ahead of it; the value did not move. |
| `FIG-accounting-062` | `/accounting/ledger/?period=2` | `templates/accounting/partials/_ledger_list_results.html:124` | Amount | `entry.amount_acre_feet` | `accounting/views.py:965` | `— (model field)` | `parcels_parcelledger` | 3.63 | 3.6270 | MATCH | MATCH | Re-pinned 2026-09-12 (143-05): the default order gained a `parcel__parcel_number` tiebreak (R-020), which moved the first row on screen from a metered groundwater reading on MER-APN-065 at -8.56 to a surface diversion on MER-APN-001 at -84.76; that row now renders through the sibling negative branch, `FIG-accounting-061`, so THIS row (the `{% else %}` branch, zero or positive) is pinned instead to the first non-negative row on screen, a recharge entry on MER-APN-003 dated 1 September 2026. Was `FIG-accounting-058` before 137-02 inserted the dashboard's new unmet-demand section ahead of it, then `FIG-accounting-061` before 143-05's renumbering (the header lost its "(AF)" too: the unit now lives in the subtitle line, rule 4). Site line moved from :120 to :124 at 143-05's second checkpoint, when the Source and Water type columns merged into one Water column ahead of it; the value did not move. Independence: restatement, including the view's ordering. |
| `FIG-accounting-063` | `/accounting/ledger/?period=2` | `templates/accounting/partials/_ledger_list_results.html:160` | Credits (allocation and recharge entries) | `ledger_total_credits` | `accounting/views.py:1057` | `— (queryset aggregate)` | `parcels_parcelledger` | 14,280.77 | 14280.77 | MATCH | MATCH | Was `FIG-accounting-060` until 136-01 retired the net row above it on 2026-09-06 (ISS-155 resolved; the value did not move), then `FIG-accounting-059` until 137-02's renumbering, then `FIG-accounting-062` before 143-05's renumbering (site line moved from :119 to :156 when the table's columns were reordered; the value did not move), then site line moved again from :156 to :160 at 143-05's second checkpoint (the Source and Water type columns merged into one Water column ahead of it; the value did not move). Independence: restatement. The 14,280.77 is 13,819.63 AF of allocation entries plus 461.14 AF of recharge. Not one drop of it is water delivered to anybody, and the subtitle line now says so: negative amounts are water delivered or pumped, positive amounts are credits. Finding 3. |
| `FIG-accounting-064` | `/accounting/ledger/?period=2` | `templates/accounting/partials/_ledger_list_results.html:162` | Delivered and pumped | `ledger_total_water` | `accounting/views.py:1058` | `— (queryset aggregate)` | `parcels_parcelledger` | 15,785.09 | 15785.09 | MATCH | MATCH | Re-measured 2026-09-06 after 136-01 (was −15,785.09 under the label *debits*, as `FIG-accounting-061`), then `FIG-accounting-060` until 137-02's renumbering, then `FIG-accounting-063` before 143-05's renumbering (site line moved from :121 to :158; the value did not move), then site line moved again from :158 to :162 at 143-05's second checkpoint (the Source and Water type columns merged into one Water column ahead of it; the value did not move): the same rows, shown as a magnitude and named for what they are. Independence: restatement. The 15,785.09 is 11,407.71 AF of canal deliveries plus 4,377.38 AF of pumping, and the dashboard calls both of those supplies, in those exact figures. Finding 3. |
| `FIG-accounting-065` | `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `templates/accounting/partials/_methodology_preview.html:30` | Billable groundwater | `final_af` | `accounting/views.py:1609` | `evaluate_chain` | `accounting_calculationplan, accounting_calculationstep, datasync_openetcache, parcels_parcel` | 27.9945 | 27.9945 | MATCH | MATCH | Independence: **different identity**. This screen computes fresh and stores nothing, so there is no row of its own to check it against; it is held instead against the persisted calculation run for the same parcel-month, which was written by a different code path on a different day. The two agree exactly. Was `FIG-accounting-061` before 137-02's renumbering. |
| `FIG-accounting-066` | `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `templates/accounting/partials/_methodology_preview.html:60` | In (AF) | `step.input_af` | `accounting/views.py:1618` | `evaluate_chain` | `accounting_calculationstep, datasync_openetcache` | 0.0000 | 0.0000 | MATCH | MATCH | Independence: different identity, as above. Pinned to step 1. Was `FIG-accounting-062` before 137-02's renumbering. |
| `FIG-accounting-067` | `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `templates/accounting/partials/_methodology_preview.html:61` | Out (AF) | `step.output_af` | `accounting/views.py:1619` | `evaluate_chain` | `accounting_calculationstep, datasync_openetcache, parcels_parcel` | 39.8491 | 39.8491 | MATCH | MATCH | Independence: **different identity**. Same raw-satellite rebuild as `FIG-accounting-004`. The live preview reproduces all five stored steps identically, which is the thing this screen exists to promise and the thing nothing else tests. Was `FIG-accounting-063` before 137-02's renumbering. |
| `FIG-accounting-068` | `/accounting/methodology/preview/?parcel_id=16&period=2026-03` | `templates/accounting/partials/_methodology_preview.html:68` | final … AF | `final_af` | `accounting/views.py:1609` | `evaluate_chain` | `accounting_calculationplan, accounting_calculationstep` | *(not rendered)* | *(unreachable)* | NO VALUE | UNVERIFIED | This is the fallback sentence shown when the saved method produces no steps at all. **All 5 steps on the active method are enabled**, so the branch cannot be reached without turning every one of them off, a configuration change this phase is not permitted to make. Was `FIG-accounting-064` before 137-02's renumbering. |
| `FIG-accounting-069` | `/accounting/reporting-periods/2/` | `templates/accounting/period_detail.html:136` | Allocation (AF) | `alloc.allocation_acre_feet` | `accounting/views.py:449`, assigned at `:456` | `— (model field; queryset built at accounting/views.py:449)` | `accounting_allocationplan` | 2809.93 | 2809.93 | MATCH | MATCH | Re-measured 2026-09-06 after 136-02 (was 9,689.40): this is the Halvern Valley GSA groundwater plan, re-sized to that district's own demonstration sustainable-yield rate of 0.58 AF/acre. Independence: restatement. The same database row the allocations list shows as **2,809.93**, printed here as **2809.93** with no thousands separator. See finding 5. Was `FIG-accounting-065` before 137-02's renumbering; its own view line moved from `:404` to `:449` when the dashboard view grew earlier in the same file. |

**Second instance, the wet year.** `/accounting/accounts/12/?period=1`, WY
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

`FIG-accounting-053`, `048` and `049` each carried this on 2026-09-05. The
arithmetic in all three was correct.

**Resolved 2026-09-06 by 136-01 under review question 3** (a figure that adds
rows must say what makes them addable), pointing at ISS-155: the net was
removed rather than relabelled, because paper and water are not addable and a
number nobody manages, in acre-feet, is ISS-156's shape on a second screen. The
footer now reads *Credits (allocation and recharge entries) +14,280.77 ·
Delivered and pumped 15,785.09* with a sentence saying that water leaving a
canal or a well is stored as a negative entry and that credits are not a supply.
The two surviving figures are `FIG-accounting-053` and `048`.

#### 4. The allocations footer adds surface water to groundwater

The allocations table for WY 2025-2026 ends with **153,121.27 AF** (159,671.46
before 136-02 re-sized the groundwater plans on 2026-09-06). That is
148,500.00 AF of surface-water allocation plus 4,621.27 AF of groundwater
allocation, added together. They are separate budgets, held by separate agencies
under separate law, and there is no decision anyone makes for which their sum is
the input.

The template's own comment explains why the total is a single sum rather than the
ledger's credits-and-debits split, because allocations are unsigned positive
volumes, and that reasoning is sound as far as it goes. It just does not reach the
question of whether two kinds of water belong in one total.

Worth having beside it: **the district's surface allocation for the year is 13
times the surface water it actually delivered**, 148,500.00 AF allocated against
11,407.71 AF delivered. 136-02 re-sized the groundwater plans and left the
surface ones alone, so that ratio is untouched and the mixture is now a much
more lopsided one: 97 percent of this total is surface entitlement.

One more caution for anyone reading across these screens. The word *allocation*
names two different things in this platform: the zone-level plans on the
allocations page, which total 153,121.27 AF for this year, and the per-parcel
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
groundwater allocation for this year is **2,809.93** on the allocations list and
**2809.93** on the reporting-period page: the same database row, one screen using
a thousands separator and the other not. 136-02 moved the value and not the
formatting, so the difference is still there.

#### 6. What could not be checked, and why

Four of the thirty-one sites never rendered. Naming them:

- **`FIG-accounting-005`, `006`, `007`.** The banked-water block on the
  calculation-run page, and the credit-draw table nested inside it. No calculation
  run in this database has a non-zero deposit or draw, and no draw rows exist, so
  the block is unreachable with this demonstration data. Five water-credit rows
  are held, which is why the feature is not simply dead code.
- **`FIG-accounting-058`** (`053` until 136-01)**.** The methodology preview's fallback line, shown when
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

## Section 4: Surface water and state reporting (14 figures)

Six templates, 14 figures: the water rights list and a right's detail page, a
diversion point's detail page and its records table, the shared-supply check, and
the CalWATRS transcription worksheet. They are grouped together because the same
stored rows appear on both an operator's screen and the worksheet a person copies
into the state's portal, so each row is checked once against both.

**Screens.** Each is captured under `audit/figure_ledger/rendered/`, with its size
and content fingerprint in `manifest-c.json`.

| Screen | Figures | What is pinned |
|---|---|---|
| `/surface/diversion/8/` | `FIG-surface-001` to `005` | MER-POD-011-DEMO Snelling Re-Diversion. Records row pinned to **May 2026**. |
| `/surface/rights/6/` | `FIG-surface-007` to `009` | MER-WR-010-DEMO, Halvern Hydroelectric Co. |
| `/surface/rights/` | `FIG-surface-006` | First row by right identifier: MER-WR-004-DEMO. |
| `/reporting/reports/4/calwatrs-worksheet/` | `FIG-reporting-001`, `002` | Submission 4, CalWATRS To Storage, WY 2025-2026. First block, first row. |
| `/reporting/reports/shared-supply-check/?period=2` | `FIG-reporting-003` to `005` | First group, MER-POD-004-DEMO Atwater Canal Headgate; row MER-APN-058. |
| `/surface/diversion/9/` | none | MER-BPOD-001 El Nido Canal Recharge Intake. Captured as evidence, see finding 3. Since 136-02 it renders one of its template's two figures, the linked right's face value of 3,500.00 AF, and still not a maximum rate. |
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

**Re-captured at commit `2555a68`**, 2026-09-06, after 136-02 gave the El Nido
recharge intake a water right of its own and the rebuilt demonstration data
renumbered the pinned pages. The screen addresses in the table above are the new
ones; no figure in this section changed value.

**First captured** at commit `9f9e27b2543516a95cdc15743070e3746d04ddbe`, 2026-09-05.
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
| `FIG-surface-001` | `/surface/diversion/8/` | `templates/surface/partials/_detail_pane.html:57` | Max rate (CFS) | `pod.max_rate_cfs` | `surface/views.py:166` | `—` | `surface_pointofdiversion` | 150.00 | 150.00 | MATCH | MATCH | Independence: different identity. Model field on the diversion point the view fetched at `surface/views.py:186`. Wrapped in a conditional, so it renders only where a rate is recorded; see finding 3. |
| `FIG-surface-002` | `/surface/diversion/8/` | `templates/surface/partials/_detail_pane.html:159` | Face value (AF) | `water_right.face_value_acre_feet` | `surface/views.py:172` | `—` | `surface_waterright, surface_pointofdiversion` | 60000.00 | 60000.00 | MATCH | MATCH | Independence: different identity. The linked right's field, reached through the diversion point. Also conditional: no linked right, or a right with no face value, and nothing renders. |
| `FIG-surface-003` | `/surface/diversion/8/` | `templates/surface/partials/_diversion_records.html:20` | Diverted (AF) | `record.volume_acre_feet` | `surface/views.py:167` | `—` | `surface_diversionrecord` | 250.00 | 250.00 | MATCH | MATCH | Independence: different identity. Whole column also checked, all 8 records on this diversion point, cross-check 3. |
| `FIG-surface-004` | `/surface/diversion/8/` | `templates/surface/partials/_diversion_records.html:21` | Return Flow (AF) | `record.returned_af` | `surface/views.py:167` | `—` | `surface_diversionrecord` | 100.00 | 100.00 | MATCH | MATCH | Independence: different identity. This is one of only two records in the whole demonstration where this column is neither 0 nor the full diverted volume, which is why the row was pinned here. |
| `FIG-surface-005` | `/surface/diversion/8/` | `templates/surface/partials/_diversion_records.html:23` | Retained (AF) | `record.consumed_acre_feet` | `surface/views.py:167` | `DiversionRecord.consumed_acre_feet` (`surface/models.py:162`) | `surface_diversionrecord` | 150.00 | 150.00 | MATCH | MATCH | Re-checked 2026-09-06 after 136-01: the value did not move; the column heading changed from *Consumptive Use (AF)* to *Retained (AF)* and a `to_storage` record now carries a *To storage* badge (ISS-153 resolved; the method keeps its name). Independence: restatement of one subtraction, `abs(volume) - returned`. Strengthened by cross-check 1, which applies the identity to all 173 records and finds 0 breaks and 0 rows where the return exceeds the volume. A method on the model, not a service. |
| `FIG-surface-006` | `/surface/rights/` | `templates/surface/partials/_list_results.html:30` | Face Value | `right.face_value_acre_feet` | `surface/views.py:288` | `—` | `surface_waterright` | 120000 | 120000 | MATCH | MATCH | Independence: different identity. Shown to zero decimal places, with the unit "AF" as template text beside it rather than part of the figure. All seven rights checked whole-column, cross-check 2. 136-02 added a seventh right, `MER-WR-011-DEMO` at 3,500 AF, which sorts last on this list, so the pinned first row and its value did not move. |
| `FIG-surface-007` | `/surface/rights/6/` | `templates/surface/partials/_water_right_detail_pane.html:64` | Face value (AF) | `water_right.face_value_acre_feet` | `surface/views.py:343` | `—` | `surface_waterright` | 60000.00 | 60000.00 | MATCH | MATCH | Independence: different identity. The same stored column as `FIG-surface-006`, shown to two decimal places instead of none; the two screens agree. |
| `FIG-surface-008` | `/surface/rights/6/` | `templates/surface/partials/_water_right_detail_pane.html:113` | Max rate: N cfs | `pod.max_rate_cfs` | `surface/views.py:344` | `—` | `surface_pointofdiversion` | 400.00 | 400.00 | MATCH | MATCH | Independence: different identity. Renders once per diversion point on the right, ordered by name; the pin is the first, MER-POD-010-DEMO Merced Falls Hydroelectric Diversion. |
| `FIG-surface-009` | `/surface/rights/6/` | `templates/surface/partials/_water_right_detail_pane.html:174` | Volume (AF) | `record.volume_acre_feet` | `surface/views.py:345` | `—` | `surface_diversionrecord, surface_pointofdiversion` | 1200.00 | 1200.00 | MATCH | MATCH | Independence: different identity. First row of a 12-row list ordered by month alone; two diversion points sharing a month would be in an unspecified order, so the pin sits on September 2026, which only one has. This figure is a **diverted** volume with no return-flow column beside it, and all 1200.00 AF of it was returned to the stream: see finding 4. |
| `FIG-reporting-001` | `/reporting/reports/4/calwatrs-worksheet/` | `templates/reporting/calwatrs_worksheet.html:84` | Volume (AF) | `row.volume_af` | `reporting/views.py:443` | `—` | `surface_diversionrecord, surface_pointofdiversion, reporting_reportsubmission` | 877.47 | 877.47 | MATCH | MATCH | 136-02 took ISS-152 option (a) and gave this diversion point a water right, `MER-WR-011-DEMO`, held by Halvern Irrigation District: the value did not move, but the block it sits in is now headed with that right identifier instead of a red *No linked water right*, and the generated state file carries these rows instead of withholding them. Independence: different identity. The stored volume, copied into a display dictionary at `reporting/views.py:437`. See finding 2. |
| `FIG-reporting-002` | `/reporting/reports/4/calwatrs-worksheet/` | `templates/reporting/calwatrs_worksheet.html:85` | Max Rate (CFS) | `row.max_rate_cfs` | `reporting/views.py:443` | `—` | `surface_diversionrecord` | 312.07 | 312.07 | MATCH | MATCH | Same block as the row above, now headed `MER-WR-011-DEMO` and no longer withheld from the generated file; the value did not move. Independence: different identity. Stored as 312.0662 and shown to two places. Conditional: a record with no rate shows a dash. Note this is a peak rate stated against a whole month's volume, because a diversion record is monthly by design (`surface/models.py:160`). |
| `FIG-reporting-003` | `/reporting/reports/shared-supply-check/?period=2` | `templates/reporting/shared_supply_check.html:112` | Your share | `row.your_weight` | `reporting/views.py:296` | `build_shared_supply_comparison` then `apportion_shared_supply` | `surface_pointofdiversionparcel, parcels_parcel` | 0.2000 | 0.2000 | MATCH | MATCH | Independence: restatement. Reproduces the four-rung ladder, including which rung fires: some stored share here differs from the untouched default, so the whole group counts as hand-set and the stored shares are used as written. Cross-check 7 adds a different identity, that each group's shares sum to exactly 1.0000, and all 8 groups do. |
| `FIG-reporting-004` | `/reporting/reports/shared-supply-check/?period=2` | `templates/reporting/shared_supply_check.html:114` | ET-implied share | `row.et_weight` | `reporting/views.py:296` | `build_shared_supply_comparison` then `apportion_shared_supply` | `accounting_calculationrun, accounting_reportingperiod, surface_pointofdiversionparcel` | 0.1196 | 0.1196 | MATCH | MATCH | Independence: restatement, including the rule that the rounding residual lands on the last use area sorted as TEXT, not as a number. That rule is visible on this very screen: MER-APN-064 shows 0.0647 and MER-APN-063 shows 0.0648 although MER-APN-064's demand is fractionally the higher of the two. Cross-check 6 confirms no value in this data sits on an exact rounding tie, so the two rounding rules in play cannot differ here. |
| `FIG-reporting-005` | `/reporting/reports/shared-supply-check/?period=2` | `templates/reporting/shared_supply_check.html:117` | Gap | `row.divergence` | `reporting/views.py:296` | `build_shared_supply_comparison` (`reporting/generators.py:225`) | `accounting_calculationrun, surface_pointofdiversionparcel` | 0.0804 | 0.0804 | MATCH | MATCH | Independence: restatement. The absolute difference of the two shares above, not rounded again. Below the 0.15 flag threshold, so the pinned row carries no badge; one row in this group is flagged. |

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

**2. The worksheet and the file the state receives disagreed about 87 percent of
the volume; 136-02 closed that on the data, and the worksheet still does not say
when it happens.** As measured on 2026-09-05, WY 2025-2026's To Storage filing
laid out **1,675.50 AF** on the worksheet and the generated file carried
**213.05 AF**. The missing **1,462.45 AF** all belonged to MER-BPOD-001 El Nido
Canal Recharge Intake, which had no water right, and the generator withholds any
row with a blank Water Right ID because that is what the state flags as an
unauthorized diversion (`reporting/generators.py:573-578`, ISS-031b). The
withholding was right; the demonstration was the thing that was wrong, because a
real district's recharge intake diverts under a permit.

136-02 took ISS-152 option (a) and gave the intake one: `MER-WR-011-DEMO`, held
by Halvern Irrigation District, a Post-1914 appropriative right on the El Nido
Canal with a face value of 3,500.00 AF, one diversion point and no use area
attached to it. Cross-check 4 re-run on 2026-09-06 reads **worksheet 1,675.50 AF,
generated file 1,675.50 AF, withheld 0.00 AF, 0 diversion points withheld**.
Queried directly, **0 of the demonstration's 9 diversion points now lack a water
right**, so the generator has nothing left to withhold in either year. The To
Storage records behind the file are 4 for the intake and 4 for MER-POD-009-DEMO
in WY 2024-2025, and 2 and 2 in WY 2025-2026; MER-POD-009-DEMO is linked to ten
use areas and the generator writes one row per use area, which is how the wetter
year's 8 records become 44 data rows in the file and the drier year's 4 become
22.

What did not change is the worksheet page. It still presents every block the same
way and still says nothing about a block being absent from the generated file,
because the code that would say it does not exist. On this data no block is
withheld, so nobody can see the omission today; the warning that does say so
still lives on the report page, produced by `reporting/validators.py:318-328`,
one screen away from the person doing the typing. That half of the finding stands
and is now untestable on the demonstration, which is worth knowing before anyone
reads the closed cross-check as a fix.

**3. Two branches of the diversion point template are now unreachable on this
data, not one.** `templates/surface/partials/_detail_pane.html:189` carries the
line "CalWATRS reports will flag this diversion as [INCOMPLETE]". It sits on the
branch for a diversion point with no water right and no recharge basin behind it.
On 2026-09-05, exactly one of the demonstration's nine diversion points had no
water right, MER-BPOD-001, and it had five recharge basin links, so it took the
branch above and read "Recharge diversion. It feeds a recharge basin rather than
a consumptive use, and no water right is linked."

Since 136-02 that point has a water right, so it takes the first of the
template's three branches, the one that names the right, and that branch carries
its own recharge sentence: "Recharge diversion. Water retained here is taken to
storage in the basins below, not consumed." The other two branches are now dead
on this data. **0 of 9** diversion points reach the `elif` sentence, "It feeds a
recharge basin rather than a consumptive use, and no water right is linked", and
**0 of 9** reach the `else` branch that carries the "[INCOMPLETE]" line.
Confirmed by capturing the page again: the string "INCOMPLETE" does not appear on
it. Nothing is broken; two untested branches where there was one, and no reader
should take either as a warning that has ever been seen.

The same page renders **one** of its template's two figures now rather than
neither: the linked right's face value, 3,500.00 AF, appears where before nothing
did. The maximum rate still does not, because no rate is recorded on this
diversion point and that figure sits inside its own conditional. Its records
table carries To storage badges.

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

## Section 5: The remaining subsystems (22 figures)

Twenty-two figures across ten page templates and five parts of the platform:
the zone page, the monitoring stations, the wells, the recharge basins, and the
first two steps of the setup wizard. They are the long tail of the figure
ledger. Most of these screens carry one or two numbers, not twenty, and most of
those numbers are a stored value shown back to the reader rather than the
result of a calculation. Four of the twenty-two are new: 137-03 (ISS-145) gave
the well page a Measurement history card, and two of its four figures, the
meter Delta and the water-level Change, are the first figures on this page
whose derivation is arithmetic rather than a column shown back unchanged.

**Screens and pins.** A figure inside a table renders once per row, so each one
is pinned to a named instance and the pin is recorded in
`audit/figure_ledger/screens-d.json`.

| Screen | What is pinned |
|---|---|
| `/map/zones/2/` | Halvern Irrigation-Urban GSA, the same district section 1 pinned on the dashboard, so the two screens can be laid side by side. The page has no year selector: its Allocation vs. use table lists every year at once, newest first, so the pinned row is the first, the water year running October 2025 to September 2026. Pinned parcel row: MER-APN-026, first by parcel number of the district's 23. |
| `/map/zones/1/`, `/map/zones/3/`, `/map/zones/9/` | The same three figures on every other district, captured so the finding below rests on four screens rather than one. |
| `/wells/10/` | Well MER-W-001, "Ag well on MER-APN-002". One screen carries all eight wells figures: the newest meter read's Totalizer and Delta and the newest water-level month's Close and Change (137-03, ISS-145), an irrigated parcel, a monitoring record with a reference elevation, a whole-number field and a two-decimal field. |
| `/wells/13/` | Evidence, not a figure site. MER-W-004, "Ag well on MER-APN-006", the transducer well the ISS-145 finding's two-year decline is measured on. Its water-level digest reads a September 2025 close of 94.15 ft and a September 2026 close of 109.65 ft. |
| `/recharge/1/` | El Nido Recharge Basin 1, first by name on the list. Pinned reading: the newest, 18 February 2026. Pinned recharge event: the newest, starting 15 February 2026. |
| `/recharge/` | The list shows every basin on one page in name order, so the pinned row is El Nido Recharge Basin 1 again. |
| `/setup/` | Merced Subbasin, the only district boundary on file. |
| `/datasync/stations/1/` | SAN JOAQUIN R - MONITORING WELL #142, the lowest station id. Since 136-02 rebuilt the demonstration data this page opens and prints the station's stored location, so it is a figure site for `FIG-datasync-001` and `002`. It holds no staged data record, so the two reading figures still have nothing to show. `/datasync/stations/` is captured as evidence, not as a figure site. |
| `/setup/confirm/` | Captured to record that it redirects rather than rendering. |

First captured at commit `9f9e27b25435`, 2026-09-05, and re-captured at
`2555a68` on 2026-09-06 after 136-02 rebuilt the demonstration data, into
`audit/figure_ledger/rendered/`, with each page's size and fingerprint in
`manifest-d.json`. Three of this section's pinned addresses changed number in the
rebuild and none of them changed meaning, and a fourth, the monitoring station,
went from a 404 to a page: see the capture note under "How to reproduce it". Recomputed by
`bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/remaining_subsystems.sql`.

Re-captured again at commit `54edc81`, 2026-09-06, after 137-03 (ISS-145) gave
the well page its Measurement history card. `/wells/10/` is the same pinned
address as before, now with the four new figures on it, and `/wells/13/` joins
the section's screens for the first time, as evidence rather than a figure
site. FIG-wells-001..004, the four new figures, are recomputed separately, by
`bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/well_measurement_history.sql`,
because they did not exist when `remaining_subsystems.sql` was written; that
file's own four wells figures were renumbered FIG-wells-005..008 to make room
ahead of them and did not otherwise change.

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
| `FIG-datasync-001` | `/datasync/stations/1/` | `templates/datasync/partials/_station_detail_pane.html:104` | Location (latitude, first half of the pair) | `station.location.y` | `datasync/views.py:318` | `— (model field)` | `datasync_monitoredstation` | 37.18610 | 37.18610 | MATCH | MATCH | Re-measured 2026-09-06 after 136-02 (was *not rendered*): the candidate's data carries all 335 monitoring stations, so the pinned lowest-id station, SAN JOAQUIN R - MONITORING WELL #142, now opens and prints its stored location. The old development database held zero station rows and `/datasync/stations/1/` answered 404. Independence: transcription. This site and the next share one template line, one of the two lines in the platform that carry two figures. |
| `FIG-datasync-002` | `/datasync/stations/1/` | `templates/datasync/partials/_station_detail_pane.html:104` | Location (longitude, second half of the pair) | `station.location.x` | `datasync/views.py:318` | `— (model field)` | `datasync_monitoredstation` | -120.68290 | -120.68290 | MATCH | MATCH | Re-measured 2026-09-06 after 136-02 (was *not rendered*): same line, same station, same reason. Independence: transcription. |
| `FIG-datasync-003` | `/datasync/stations/1/` | `templates/datasync/partials/_station_detail_pane.html:157` | Current readings, the newest published value per sensor | `r.value` | `datasync/views.py:320`, assembled at `:296-315` | `— (selection in the view: newest published reading per measured parameter)` | `datasync_datarecordstaging` | not rendered | — | NO VALUE | UNVERIFIED | Still unverified after 136-02, for a different reason: the page now opens, and the Current readings card prints its empty state, "No published readings yet.", because this particular station carries no staged data record. 30,217 staged records exist on other stations. |
| `FIG-datasync-004` | `/datasync/stations/1/` | `templates/datasync/partials/_station_detail_pane.html:241` | Recent records, Value | `record.value` | `datasync/views.py:319`, queryset at `:237` | `— (model field)` | `datasync_datarecordstaging` | not rendered | — | NO VALUE | UNVERIFIED | Same station, same reason: the Recent records table has no staged row on station 1 to pin. |
| `FIG-geography-001` | `/map/zones/2/` | `templates/geography/partials/_zone_detail_pane.html:129` | Allocation (AF) | `b.budget` | `geography/views.py:214`, assigned at `:208` | `— (arithmetic in the view)` | `accounting_allocationplan` | 750.32 | 750.32 | MATCH | MATCH | Independence: transcription. One stored allocation column, read back and rounded the same way. Agrees with the dashboard's Allocation for this district in section 1, which is a second screen showing the same stored number. Site line moved from `:147` to `:129` after 137-02 added the Carried forward column beside it; the value did not move. |
| `FIG-geography-002` | `/map/zones/2/` | `templates/geography/partials/_zone_detail_pane.html:137` | Carried forward (AF) | `b.carryover` | `geography/views.py:215`, computed via `zone_groundwater_budget` at `:207` | `zone_groundwater_budget` calls `zone_carryover` | `accounting_allocationcarryover` | 303.40 | 303.40 | MATCH | MATCH | New figure, 137-02 (ISS-154): the Carried forward column added to the district page's Allocation vs. use table, between Allocation and Used, signed and dashed on surface rows the same way the dashboard's own carry-over cell is (`FIG-accounting-056`). Pinned to Halvern Irrigation-Urban GSA, WY 2025-2026 (period id 2): the same 303.40 AF the dashboard's zone row shows for this zone and period, because both now read `zone_carryover` through the same `zone_groundwater_budget` call. Independence: restatement. |
| `FIG-geography-003` | `/map/zones/2/` | `templates/geography/partials/_zone_detail_pane.html:139` | Used (AF), with the word "pumped" beside it | `b.used` | `geography/views.py:216`, computed via `zone_groundwater_budget` at `:207` | `zone_groundwater_budget` calls `zone_consumptive_balance` | `parcels_parcelledger, geography_parcelzone` | 142.14 | 142.14 | MATCH | MATCH | Was `FIG-geography-002` before 137-02's renumbering, rendered 1,313.07 under verdict `ISS-154`: the branch used to sum every negative billable row for the period, and canal deliveries are stored negative, so 1,170.93 AF of surface water sat inside a column headed "pumped". Re-measured 2026-09-06 after 137-02 (ISS-154 closed): the branch now calls the shared `zone_groundwater_budget` helper, the same one the dashboard's zone row calls, so only metered and calculated groundwater pumping counts here. What the label says it is, it now is: of the 142.14 AF labelled "pumped", all 142.14 AF is groundwater. Independence: restatement. |
| `FIG-geography-004` | `/map/zones/2/` | `templates/geography/partials/_zone_detail_pane.html:141` | Remaining (AF) | `b.remaining` | `geography/views.py:218`, computed via `zone_groundwater_budget` at `:207` | `zone_groundwater_budget` calls `available_with_carryover` | `accounting_allocationplan, accounting_watertype, accounting_allocationcarryover, parcels_parcelledger, geography_parcelzone` | 911.58 | 911.58 | MATCH | MATCH | Was `FIG-geography-003` before 137-02's renumbering, rendered −562.75 under verdict `ISS-154`: allocation minus the figure above inherited the same problem and turned it into a verdict, that this district was 562.75 AF over its groundwater budget when on its groundwater draw alone it was 608.18 AF under. Re-measured 2026-09-06 after 137-02 (ISS-154 closed): allocation 750.32 plus carry-over 303.40 (`FIG-geography-002`) minus 142.14 AF of groundwater use (`FIG-geography-003`) reads 911.58, the same figure the dashboard's zone row shows for this zone and period (`FIG-accounting-057`) to the cent. The sign is no longer wrong: this district is 911.58 AF under its groundwater budget. Independence: restatement. |
| `FIG-geography-005` | `/map/zones/2/` | `templates/geography/partials/_zone_parcels.html:30` | Area (acres) | `pz.parcel.area_acres` | `geography/views.py:295`, queryset at `:165-170` | `— (model field)` | `parcels_parcel, geography_parcelzone` | 12.74 | 12.74 | MATCH | MATCH | Independence: transcription. This partial has exactly one route that renders it for reading: as an include on the district page. Its two other routes both change data and accept POST only. Was `FIG-geography-004` before 137-02's renumbering; the value did not move. |
| `FIG-recharge-001` | `/recharge/1/` | `templates/recharge/partials/_detail_pane.html:56` | Capacity (AF) | `site.capacity_acre_feet` | `recharge/views.py:119` | `— (model field)` | `recharge_rechargesite` | 637.10 | 637.10 | MATCH | MATCH | Independence: transcription. |
| `FIG-recharge-002` | `/recharge/1/` | `templates/recharge/partials/_detail_pane.html:128` | Recent measurements, Value | `m.value` | `recharge/views.py:122`, queryset at `:95-97` | `— (model field)` | `recharge_rechargemeasurement` | 315.26 | 315.26 | MATCH | MATCH | Independence: transcription. One column serves four different kinds of reading, each with its own unit, so the same figure is milligrams per litre on one row and feet on the next. The pinned row is a water quality reading in milligrams per litre. |
| `FIG-recharge-003` | `/recharge/1/` | `templates/recharge/partials/_event_history.html:22` | Volume (AF) | `event.volume_acre_feet` | `recharge/views.py:120`, queryset at `:82-84` | `— (model field)` | `recharge_rechargeevent` | 127.42 | 127.42 | MATCH | MATCH | Independence: transcription. |
| `FIG-recharge-004` | `/recharge/` | `templates/recharge/partials/_list_results.html:31` | Capacity | `site.capacity_acre_feet` | `recharge/views.py:60`, queryset at `:45` | `— (model field)` | `recharge_rechargesite` | 637 | 637 | MATCH | MATCH | Independence: transcription. Rounded to whole acre-feet here and to hundredths on the basin's own page, so the same basin reads 637 in the list and 637.10 one click later. Both are right; the list is choosing not to show the tenths. |
| `FIG-setup-001` | `/setup/confirm/` | `templates/setup/confirm.html:61` | Area, square miles | `area_sq_miles` | `setup/services.py:247` | `— (model field)` | `geography_boundary` | not rendered | 800.9 | NO VALUE | UNVERIFIED | The confirmation step reads the chosen boundary out of the visitor's session, which only the previous step's form submission writes. The capture performs page requests only, so this screen redirected rather than rendering. The recomputed value is recorded because the same stored field renders on the previous step and is verified there. |
| `FIG-setup-002` | `/setup/` | `templates/setup/wizard.html:66` | The district boundary dropdown: "Merced Subbasin (800.9 sq mi)" | `b.area_sq_miles` | `setup/views.py:115`, queryset at `:113` | `— (model field)` | `geography_boundary` | 800.9 | 800.9 | MATCH | MATCH | Independence: transcription, plus one genuinely independent check. The platform deliberately never computes this area, taking it from the uploaded file instead, on the reasoning that a computed figure would be OpenH2O's number rather than the district's. The database can compute it: the stored outline measures 800.949 square miles against the 800.948 the file states, a difference of about half an acre across an 800 square mile basin. |
| `FIG-wells-001` | `/wells/10/` | `templates/wells/partials/_detail_pane.html:164` | Totalizer | `read.current_value` | `wells/views.py:163` | `meter_history` (`wells/measurement_history.py:60-77`) | `measurements_meterreading, wells_wellmeter` | 41,241.64 | 41241.64 | MATCH | MATCH | New figure, 137-03 (ISS-145): the Measurement history card's meter table. Pinned to the well's one current meter, MTR-MER-W-001, its newest read, 30 September 2026. Independence: transcription, one stored column read back and rounded the same way the template does. |
| `FIG-wells-002` | `/wells/10/` | `templates/wells/partials/_detail_pane.html:166` | Delta (AF) | `read.calculated_volume` | `wells/views.py:163` | `meter_history` reads the stored column; no arithmetic in the view | `measurements_meterreading` | 65.91 | 65.91 | MATCH | MATCH | Same pinned read as the row above. Independence: different identity, recomputed two ways that could disagree with the stored column and with each other: current_value minus this row's own previous_value, and current_value minus the prior read's current_value. Both read 65.9112 AF against the stored 65.9112, on this read and, whole-column, on all 24 reads on this meter (`audit/figure_ledger/sql/well_measurement_history.sql`, cross-check X1). |
| `FIG-wells-003` | `/wells/10/` | `templates/wells/partials/_detail_pane.html:195` | Close (ft) | `row.close` | `wells/views.py:164` | `water_level_history` (`wells/measurement_history.py:103-126`) | `measurements_watermeasurement` | 101.92 | 101.92 | MATCH | MATCH | New figure, 137-03 (ISS-145): the Measurement history card's water-level digest. No stored column holds a month's close; the view builds it in Python as the last reading in the month, taken in America/Los_Angeles. Well 10 carries no Sensor row, so the digest reads the hand-entered WaterMeasurement record, 24 monthly rows; pinned to the newest, September 2026. Independence: restatement, the check re-derives the same selection rule rather than reading a number back. |
| `FIG-wells-004` | `/wells/10/` | `templates/wells/partials/_detail_pane.html:196` | Change (ft) | `row.change` | `wells/views.py:164` | `water_level_history` (`wells/measurement_history.py:128-132`) | `measurements_watermeasurement` | 3.13 | 3.13 | MATCH | MATCH | Same pinned month as the row above: September 2026's close (101.9163) minus August 2026's close (98.7905). Independence: restatement, same reasoning as FIG-wells-003. A second well, MER-W-004 (well id 13, `/wells/13/`, captured as evidence rather than a figure site), carries the two-year dry-year decline ISS-145 names: its logger's close moves from 94.15 ft in September 2025 to 109.65 ft in September 2026, a 15.50 ft rise, now visible on a screen rather than only in a seed note. |
| `FIG-wells-005` | `/wells/10/` | `templates/wells/partials/_detail_pane.html:218` | "1.00 fraction", beside the parcel the well irrigates | `wip.fraction` | `wells/views.py:188`, queryset at `:157` | `— (model field)` | `wells_wellirrigatedparcel` | 1.00 | 1.00 | MATCH | MATCH | Independence: transcription. The pinned well has one irrigated parcel, so "first row" is unambiguous. Was `FIG-wells-001` until 137-03 added the measurement-history figures above it. |
| `FIG-wells-006` | `/wells/10/` | `templates/wells/partials/_detail_pane.html:250` | Reference elevation, ft | `monitoring.reference_elevation_ft` | `wells/views.py:189`, fetched at `:158` | `— (model field)` | `wells_monitoringwell` | 182.4 | 182.4 | MATCH | MATCH | Independence: transcription. Only three of the district's 45 wells carry a monitoring record, and only two of those three carry a reference elevation, so this card is absent from most well pages. Was `FIG-wells-002` until 137-03 added the measurement-history figures above it. |
| `FIG-wells-007` | `/wells/10/` | `templates/wells/partials/_editable_field.html:24` | Year Pumping Began | `ef.value` (whole-number branch) | `wells/views.py:180` | `— (model field, read straight off the well)` | `wells_well` | 1987 | 1987 | MATCH | UNVERIFIED | Independence: transcription, and that is all it can be. This template renders whichever well field the page hands it, and every one of them is a value a person typed through the pencil control beside it. There is nothing to recompute it against. The two numbers agreeing shows the platform redisplays what was entered; it says nothing about whether 1987 is the year. This is the only whole-number field the platform has. Was `FIG-wells-003` until 137-03 added the measurement-history figures above it. |
| `FIG-wells-008` | `/wells/10/` | `templates/wells/partials/_editable_field.html:24` | Capacity (gpm) | `ef.value` (two-decimal branch) | `wells/views.py:180` | `— (model field, read straight off the well)` | `wells_well` | 2000.00 | 2000.00 | MATCH | UNVERIFIED | Same line as the row above, the second of the platform's two double-figure lines. Six well fields take this branch: capacity, depth, casing diameter, screen top, screen bottom and tested yield. The pin is capacity, the first of them in the page's own order. Same reasoning as above: nothing derives any of the six. Was `FIG-wells-004` until 137-03 added the measurement-history figures above it. |

### What section 5 found

**Nineteen of the twenty-two figures agree with the rows behind them to the
cent. The other three showed nothing on screen** (thirteen and five on
2026-09-05; the monitoring station's two location figures rendered for the
first time on 2026-09-06, after 136-02 rebuilt the demonstration data; 137-03
then added four figures on 2026-09-06, all four MATCH). No figure in this
section disagrees with its own arithmetic. One of them disagrees with its label,
and that is the finding worth acting on.

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
| Halvern Valley GSA | 2,809.93 | 13,379.29 | 10,236.78 | **−10,569.36** | **−332.58** |
| Halvern Irrigation-Urban GSA | 750.32 | 1,313.07 | 1,170.93 | **−562.75** | **+608.18** |
| Verdano Island Water District GSA | 1,061.02 | 1,092.73 | 0.00 | −31.71 | −31.71 |
| MER Surface Service Area, Halvern ID (surface allocation) | 108,000.00 | 1,993.82 | n/a | 106,006.18 | n/a |

Re-measured 2026-09-06 after 136-02 re-sized the groundwater allocations. Two
rows moved: Halvern Valley GSA's allocation went from 9,689.40 to 2,809.93 and
Verdano Island's from 731.74 to 1,061.02. The "Used" column did not move at all,
because 136-02 changed no ledger entry.

The defect the smaller allocations expose more sharply is the size of the error
rather than its sign. Halvern Irrigation-Urban GSA still reports a 562.75 AF
deficit where its groundwater draw alone leaves 608.18 AF in hand, the sign
reversed outright. Halvern Valley GSA now reads over budget on both bases, but by
10,569.36 AF as shown against 332.58 AF on its groundwater draw, an overstatement
of thirty-two times. Verdano Island takes no canal water, so its two figures are
the same number, which is why the fault stays invisible to anyone who only looks
at one page. Before 136-02 the first two districts each showed a deficit where
the groundwater draw alone was a surplus; that is now true of one of them.

This is the other end of the problem section 1 recorded on the dashboard. There,
adding the district table's Supplies column gave 31,223.56 AF against the panel's
17,458.35 AF, because 59 of the 76 parcels sit in two districts at once, a
groundwater agency's area and a surface water district's service area. Those 59
parcels are exactly the parcels whose canal deliveries land inside the
"pumped" figure here. One data shape, two screens, two different symptoms.

Both numbers in each row are correct arithmetic on the rows stored. Recorded as
`ISS-154` against `FIG-geography-002` and `FIG-geography-003`, a number reserved
here and filed by Plan 135-03. This section does not diagnose it further and changes nothing.

#### 2. Three of this section's figures still have nothing to show, and it used to be five

**Re-measured 2026-09-06 after 136-02.** On 2026-09-05 four of the eighteen
belonged to the monitoring station page and there was no station:
`datasync_monitoredstation` held zero rows, `datasync_datarecordstaging` held
zero readings, the station list rendered its empty state "No stations found.",
and a request for the lowest possible station answered 404. The cause was the
development database, a hand-seeded copy that never loaded the telemetry.

The rebuilt demonstration data does load it, and the counts now reproduce the
pins. The file that says what this demonstration must contain,
`data/demo/expected_shape.json`, requires **335** stations and **30,217**
readings, both at tolerance zero, and describes them as "the demonstration's
frozen telemetry". Cross-check 6 re-run against the rebuilt data reads **335
stations, 30,217 staged records and 8 external data sources**, all three on their
pins. Every other count this section touches still reproduces its pin exactly:
135 parcel-to-district memberships, 8 districts, 5,658 stream lines, 760 cached
evapotranspiration records, 45 wells, 3 monitoring wells, 29 irrigated-parcel
links, 12 meters, 7 recharge basins, 42 recharge events, 126 basin readings, 1
boundary. Fifteen counts out of fifteen now hold, where two were wrong before,
and the two that were wrong are exactly the two that populate this page.

So the station page renders. `/datasync/stations/1/` opens SAN JOAQUIN R -
MONITORING WELL #142 and prints its stored location, 37.18610 and −120.68290,
which is `FIG-datasync-001` and `002` seen for the first time. The two reading
figures still show nothing, and the reason has changed: this particular station
carries no staged data record, so the Current readings card prints "No published
readings yet." and the Recent records table has no row. That is a property of
which station has the lowest id, not of the database being empty.

The third figure with nothing to show is the setup wizard's confirmation step. It
reads the boundary a visitor chose out of their session, and only the previous
step's form submission puts it there, so a page request alone lands back at the
start; `/setup/confirm/` still answered a redirect at capture. The figure itself
is the same stored field the previous step shows, and that one is recomputed and
agrees.

#### 3. Two thirds of these figures are values shown back, not values worked out

Fourteen of the eighteen are a single stored column passed through a display
formatter (twelve before 136-02, which added the monitoring station's two
location figures to the set). There is no calculation, no service, and nothing for a second opinion
to disagree with. For those rows the check reads the column, applies the same
rounding, and confirms the screen reports the row faithfully. Every one did.

That is a real property and worth having. It is not what most of this ledger is
for, and a reader should not read twelve MATCH verdicts as twelve audited
numbers. The two well fields are marked UNVERIFIED to make the distinction
impossible to miss, because those are typed in by a person through the pencil
control on the page, and the platform will store and redisplay whatever is
typed. The other twelve are the same in kind: a basin's capacity, a parcel's
acreage, a well's reference elevation, a monitoring station's coordinates. Each is a fact about the district that
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

#### 7. ISS-145 is closed: the well page now renders the measurement history it promised

The well page's description has said "measurement history" since it was
written, and until 137-03 the page rendered none. That is closed by rendering,
not by argument: `/wells/10/` now shows a table of meter reads with a Totalizer
and a Delta column, and a table of monthly water-level closes with a Change
column, both pulled straight off the stored rows with no chart and no library.
FIG-wells-001 through FIG-wells-004 are those four figures, and all four
MATCH.

The Delta figure is the more interesting of the two new kinds. It looks like a
transcription, one stored column shown back, but the recomputation checks it
two ways that could have disagreed with each other and with the stored value:
current_value minus the row's own previous_value, and current_value minus the
prior read's current_value. On the pinned meter, MTR-MER-W-001, both read
65.9112 AF against a stored 65.9112, and the same holds on all 24 reads on that
meter with zero breaks in the chain. Close and Change have no stored column at
all behind them; `wells/measurement_history.py` builds both in Python from the
month's last reading, so the check re-derives that selection rule rather than
reading a number back.

The card also puts a number behind the finding ISS-145 was written to surface.
MER-W-004 (well id 13, `/wells/13/`), the one well on a pressure transducer
that the seed data runs dry, now shows its own water-level table: a September
2025 close of 94.15 ft against a September 2026 close of 109.65 ft, a 15.50 ft
drop in one dry year, on a screen a reader can open rather than only in a
seed-data note.

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

---

## Section 6: The parcels outside the realistic band

Every section above asks whether a number on a screen matches the rows behind
it. They all do. This section asks a different question, and it is the one a
water professional would ask first: **when the parcel pane says a field's books
did not close, is the platform wrong, or is the water?**

**The bar this section is judged against is not zero, and it was set
deliberately.** Real water accounting never closes to nothing. A meter measures
water lifted out of the ground, which is more than the crop consumed. Deficit
irrigation in a drought leaves a real shortfall. Salt-flush and operational
flooding put water on a field that the crop never uses. Shallow groundwater and
a stream at the edge of a field feed the root zone with water nobody delivered.
So the platform carries an acceptance band: a residual within a quarter of the
field's gross crop water use is *small, realistic, and never alarming*
(`REALISTIC_RESIDUAL_BAND = 0.25`, `accounting/services.py:581`). **A field
outside that band is not automatically a defect. It needs a reason**, and "the
demonstration sized this one badly" and "the arithmetic is wrong" are different
findings.

Twenty-one field-years sit outside the band: **10 of 76 fields in WY 2024-2025
and 11 of 76 in WY 2025-2026.** Every one of them has a reason below, and the
reasons are three, not twenty-one.

**Reproduce it with** `bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/parcel_band_review.sql`.
That file re-derives both balances for all 76 fields in both years from the
stored rows, independently of the code that renders them, and reproduces the
four already-worked fields to the cent before anything downstream of it is
trusted.

### The three reasons, and how many field-years each one carries

| Reason | Field-years | Direction | Is it a defect? |
|---|---:|---|---|
| **The junior canal right was curtailed, and the field kept its crop** | 6 | Deficit, −81.8% to −90.9% of gross ET | **Not a defect. It is water use with no accountable supply, which the platform already measures and no screen shows.** ISS-157 |
| **The same curtailment, caught part-way through the earlier year** | 5 | Deficit, −36.8% to −51.7% | No. This is the scarcity demonstration behaving as designed |
| **The meter measures pumping, and the books have nowhere to put the difference** | 10 | Surplus, +31.6% to +55.8% | No new issue. It was ISS-148's shape with the sign reversed; 137-01 closed ISS-148 (the screen showed it twice, now it shows it once), but the missing output term itself is still ISS-139 |

---

### Reason 1: the junior canal right was curtailed, and the field kept its crop

**Six fields, WY 2025-2026 only.** MER-APN-010, -011, -012, -013, -014, -019, all
farmed by Saddlebow Ag Holdings.

**What the demonstration set up.** A drought curtailment order, `MER-CURT-001`,
takes effect 1 July 2025 and cuts the junior El Nido Canal right
(`MER-WR-009-DEMO`, Saddlebow Irrigation District). Its own note says what is
supposed to happen next: *"Surface deliveries stop after June; conjunctive
growers substitute groundwater."* Nine fields sit on that right.

**Three of the nine did substitute.** MER-APN-015, -016 and -017 each carry
twelve monthly groundwater rows in the dry year. MER-APN-017 substituted so
completely that it appears further down this page as a *surplus*.

**The other six received nothing at all.** Their only ledger row in the whole dry
year is a paper allocation. No canal delivery, no meter reading, no calculated
pumping. Checked twice: once through the same suppression rules the platform
applies, and once against the raw rows with no filtering of any kind.

**And their crops did not notice.** Satellite-measured crop water use is
essentially unchanged from the wet year:

| Field | Crop | Gross crop water use, WY 2024-25 | WY 2025-26 | Change | Water delivered, WY 2025-26 |
|---|---|---:|---:|---:|---:|
| MER-APN-010 | Tomatoes | 408.22 | 401.11 | −1.7% | **0.00** |
| MER-APN-011 | Almonds | 370.26 | 363.26 | −1.9% | **0.00** |
| MER-APN-012 | Alfalfa | 190.28 | 183.44 | −3.6% | **0.00** |
| MER-APN-013 | Corn | 328.67 | 321.84 | −2.1% | **0.00** |
| MER-APN-014 | Grapes | 506.24 | 496.09 | −2.0% | **0.00** |
| MER-APN-019 | Grapes | 457.41 | 448.46 | −2.0% | **0.00** |

**The first reading of this was wrong, and the correction is worth more than the
finding was.** It was written up on 2026-09-05 as a defect in the demonstration's
data: a field cannot grow a full crop on no water, so the seed owed these six
either meter rows or a collapsed crop. That is true as far as it goes, and it
misses what the pattern actually is.

**A field consuming water with no water right and no groundwater source is a real
thing, and finding it is a large part of what a water-rights regulator does.**
Water gets used that nobody has reported. Reconciling satellite-measured crop
water use against what was actually reported is how that becomes visible. So
these six fields are not only a gap in the demonstration; they are the shape of
the case the demonstration should be able to show.

**And the platform already computes it.** Every monthly calculation carries an
`unmet_demand_af` figure. Where a field has a well, the leftover after crop use
minus rainfall minus surface water is booked as a calculated groundwater
extraction. Where a field has **no** well, that same leftover is recorded as
unmet demand instead, and the platform's own help page states the principle:
*"It is never phantom pumping. The platform refuses to invent groundwater out of
a missing meter"* (`templates/help/water_balances.html:87`).

**Measured over the dry year, it names exactly these six and nothing else.**
Forty-seven fields carry the unmet-demand disposition, because 47 fields have no
well. Only six carry an amount above zero, totalling **1,986.50 acre-feet**, and
they are the six in the table above. The other 41 sit at zero because canal water
covered them.

**What is missing is the screen.** Nothing in the platform displays the number.
Two help pages explain a concept no page shows.

⚠ **A screen for this states arithmetic and stops:** *water use recorded, no
supply reported*. It does not say unauthorized, unpermitted or unlawful, and it
does not imply them. What the rows show is what a regulator's page may say; the
conclusion belongs to the reader.

**One thing the six do share that a real drought would not:** they carry on at
full crop identically, all six. In a real dry year some of those growers fallow.
Making them differ, so that some fallow and some pump and one or two remain
genuinely unaccounted, would make the flag mean more, because it would stop
firing on six identical cases. That is a change to the demonstration's seed data,
it moves counts that are pinned exactly, and it is **not** a prerequisite for the
screen.

⚠ **Not fixed here. Phase 135 is read-only on product code and on the seed.**
Filed as **ISS-157** and scheduled for **Phase 137** with the rest of the page
pass. Decided by Brent 2026-09-06: build the view first, on the field page and as
a district-wide list, and leave the seed data as it stands for now.

---

### Reason 2: the same curtailment, caught part-way through the earlier year

**Five fields, WY 2024-2025 only.** MER-APN-010, -011, -013, -014, -019.

The water year runs October 2024 to September 2025, and the curtailment lands on
1 July 2025, inside it, and at the peak of the irrigation season. So these
fields took canal water for nine months and then lost it for the three that
matter most.

| Field | Canal delivery | Effective rainfall | Total supplies | Gross crop water use | Deep percolation credited | Residual | Residual as % of crop use |
|---|---:|---:|---:|---:|---:|---:|---:|
| MER-APN-013 | 126.11 | 62.33 | 188.43 | 328.67 | 29.73 | −169.96 | −51.7% |
| MER-APN-019 | 189.45 | 80.27 | 269.72 | 457.41 | 41.71 | −229.39 | −50.2% |
| MER-APN-011 | 161.78 | 62.85 | 224.64 | 370.26 | 35.95 | −181.57 | −49.0% |
| MER-APN-014 | 281.90 | 89.07 | 370.97 | 506.24 | 57.97 | −193.23 | −38.2% |
| MER-APN-010 | 227.17 | 75.78 | 302.95 | 408.22 | 45.14 | −150.40 | −36.8% |

**This is the demonstration working, and the pane is right to say so.** A grower
who loses their surface water in July finishes the year short, and a page that
reported anything else would be hiding the point of the exercise. The deficit is
roughly half a season's water, which is what losing the last quarter of the year
costs a crop that was already being irrigated at a loss.

**No issue.** The one thing worth carrying forward is that these five field-years
and the six above are the same six growers in two consecutive years, and a reader
looking at one year cannot tell which situation they are in. That is a
presentation question for Phase 137, not a defect here.

---

### Reason 3: the meter measures pumping, and the books have nowhere to put the difference

**Ten field-years across five fields**, in both years: MER-APN-002, -017, -048,
-052, -053. Every one is a surplus, and every one sits between +31.6% and +55.8%
of the field's gross crop water use.

**Why a surplus happens at all.** A flow meter on a well measures water lifted
out of the aquifer. The crop consumes less than that: some runs off the end of
the field, and some percolates back down past the root zone. So applied water
routinely exceeds crop water use by a fifth or more, and the difference is real
water that went somewhere.

**The platform records where that water went, but only when it arrived by
canal.** The calculation chain runs rainfall and canal deliveries down against
crop demand and, where they overshoot, writes the excess out as deep percolation
to the aquifer (`accounting/steps.py:279`: *"the remainder, which is surface
water delivered beyond crop demand … physically this is deep percolation that
recharges the aquifer"*). Pumped groundwater is not one of the chain's inputs. It
is what the chain **computes**, how much pumping the field needed, so pumping
in excess of that never meets the overshoot rule, and no deep-percolation row is
ever written for it.

**Measured across the whole demonstration, and this is what makes it a mechanism
rather than a story:**

| How the field was supplied | Field-years | With deep percolation recorded | Outside the band | Average residual, % of crop use | Applied water, % of crop use |
|---|---:|---:|---:|---:|---:|
| Canal water only | 101 | **101 of 101** | 5 | −2.4% | 120.0% |
| Both canal and pumped | 8 | **8 of 8** | 1 | +7.2% | 125.6% |
| Pumped groundwater only | 37 | **0 of 37** | 9 | **+15.1%** | 115.1% |
| No delivered supply at all | 6 | 0 of 6 | 6 | −89.0% | 11.0% |

Fields in the first two groups over-apply *more* than fields in the third
(120.0% and 125.6% of crop use, against 115.1%), and their books still close,
because their excess has a name. The pumped-only fields over-apply less and their
books do not close, because their excess has nowhere to go and lands in the
residual entire.

**The ten field-years, with each term beside them:**

| Water year | Field | Crop | Pumped groundwater | Effective rainfall | Total supplies | Gross crop water use | Residual | % of crop use |
|---|---|---|---:|---:|---:|---:|---:|---:|
| WY 2024-2025 | MER-APN-017 | Alfalfa | 220.29 | 53.83 | 379.84¹ | 268.97 | +84.97 | +31.6% |
| WY 2024-2025 | MER-APN-053 | Corn | 152.28 | 19.05 | 171.33 | 127.89 | +43.45 | +34.0% |
| WY 2024-2025 | MER-APN-048 | Corn | 330.11 | 49.84 | 379.95 | 277.20 | +102.75 | +37.1% |
| WY 2024-2025 | MER-APN-002 | Alfalfa | 766.72 | 78.46 | 845.18 | 564.23 | +280.94 | +49.8% |
| WY 2024-2025 | MER-APN-052 | Alfalfa | 196.01 | 21.26 | 217.27 | 143.01 | +74.26 | +51.9% |
| WY 2025-2026 | MER-APN-053 | Corn | 161.44 | 10.02 | 171.46 | 125.76 | +45.70 | +36.3% |
| WY 2025-2026 | MER-APN-048 | Corn | 351.48 | 26.68 | 378.15 | 272.37 | +105.78 | +38.8% |
| WY 2025-2026 | MER-APN-017 | Alfalfa | 368.34 | 27.64 | 395.97 | 263.07 | +132.90 | +50.5% |
| WY 2025-2026 | MER-APN-002 | Alfalfa | 811.73 | 39.41 | 851.14 | 553.70 | +297.44 | +53.7% |
| WY 2025-2026 | MER-APN-052 | Alfalfa | 208.05 | 11.09 | 219.14 | 140.64 | +78.50 | +55.8% |

¹ MER-APN-017 also took 105.72 AF of canal water in the wet year, and 25.90 AF
of deep percolation is credited against it. It is the only field in this group
that was supplied both ways in either year.

**These residuals are real water, and the pane is not wrong about any of them.**
Between a third and a half of a crop's water use, applied and not consumed, is
what flood-irrigated alfalfa and furrow-irrigated corn look like on a meter. It
is the class of residual the acceptance bar was written to accept.

**What the platform is missing is a name for it.** The books have an output term
for canal water that percolates and none for pumped water that percolates, so the
same physical event is bookkeeping on one field and an unexplained surplus on the
next. Until there is such a term the badge on these ten field-years will keep
reading as a warning about fields that are behaving normally.

**No new issue.** This was [ISS-148](#) seen from the other side: the pane used
to print two balances that differed by exactly the deep-percolation term, and
these are the fields where that term is zero when it should not be. Phase 136
answered it with the vocabulary and 137-01 settled it with the panel: the pane
now states the mass balance alone, so there is no second number for these
residuals to disagree with, though the residual itself and the badge on it are
unchanged. The missing output term itself is still the substance of ISS-139,
which this milestone deliberately leaves out because it changes the
mass-balance identity and you validate before you change.

---

### What this section is not

It is **not** a finding that the platform's arithmetic is wrong anywhere. Every
one of these 21 field-years reproduces to the cent from the stored rows, and the
identity `residual = card three − deep percolation − net banked` holds on all
**152** field-years with **zero** violations.

It is **not** a claim that all 21 should read as balanced. Eleven of them are a
drought curtailment doing exactly what a drought curtailment does, and the pane
should say so loudly.

It **is** the first time anyone has looked at all of them together, and looking
at them together is what turned twenty-one flags into three causes.

### Where this section's evidence lives

- Recomputation: `audit/figure_ledger/sql/parcel_band_review.sql`
- Triage of every disagreement, with the third-route derivations:
  `audit/figure_ledger/triage.md`
- The band and the identity: `accounting/services.py:581`, `:702`, `:767`
- The deep-percolation rule: `accounting/steps.py:270-330`
- The curtailment: `surface_curtailmentorder`, order `MER-CURT-001`
