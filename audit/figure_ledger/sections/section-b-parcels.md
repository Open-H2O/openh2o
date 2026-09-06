## Section 2. The parcel detail pane (20 figures)

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
| `FIG-parcels-003` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:49` | Supplies − consumptive use | `consumptive_balance.net_vs_supply` | `parcels/views.py:168` | `parcel_consumptive_balance` | `parcels_parcelledger, accounting_calculationrun` | 174.13 | 174.13 | MATCH | **`ISS-148-pending`** | Independence: restatement. **The arithmetic of this figure is right to the cent. The issue is that it contradicts `FIG-parcels-015` on the same screen: this card says 174.13 AF of water arrived and was not consumed, and the residual below says the books close at 0.00 AF.** The difference is exactly the Recharge term, `FIG-parcels-011`, also 174.13 AF: the same water counted as an unused supply by one balance and as an output by the other. Reproduced whole-column as `CHK-parcels-031` and `CHK-parcels-037`. |
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
| `FIG-parcels-015` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:115` | Residual | `mass_balance.residual_af` | `parcels/views.py:169` | `parcel_mass_balance` | `parcels_parcelledger, accounting_calculationrun` | 0.00 | 0.00 | MATCH | **`ISS-148-pending`** | Independence: restatement. **Right to the cent, and it contradicts `FIG-parcels-003` above it.** Recomputed at full precision the residual is −0.000117 AF, which prints as 0.00 and sits inside the 0.01 AF band the platform calls Balanced. So the reader sees 174.13 AF of surplus in one place and a closed book in another, three inches apart, with nothing on the page connecting them. |
| `FIG-parcels-016` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:178` | surface (in the "ET has not been computed" notice) | `consumptive_balance.supplies.surface` | `parcels/views.py:168` | `parcel_consumptive_balance` | `parcels_parcelledger` | not rendered | 719.30 | n/a | **`UNVERIFIED`** | **This figure could not be checked, because nothing on this platform can currently display it.** It sits in the branch shown only when a parcel has no calculation runs for the year, and every one of the 76 parcels has runs in both years (`CHK-parcels-070`, `CHK-parcels-071`, both zero). The value it would print is recomputed and recorded, so the day the branch becomes reachable the number is already on file. |
| `FIG-parcels-017` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:179` | groundwater (in the "ET has not been computed" notice) | `consumptive_balance.supplies.groundwater` | `parcels/views.py:168` | `parcel_consumptive_balance` | `parcels_parcelledger` | not rendered | 0.00 | n/a | **`UNVERIFIED`** | Same branch, same reason as `FIG-parcels-016`. |
| `FIG-parcels-018` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:216` | Area (Acres) | `ef.value` | `parcels/views.py:172` | `none (model field, read at parcels/views.py:157)` | `parcels_parcel` | 154.69 | 154.69 | MATCH | MATCH | Independence: restatement of a stored value, which is the weakest kind of check there is and is stated as such. The pane loops over five editable fields; Area is the only one typed as a number, so it is the only one that reaches the two-decimal display filter. |
| `FIG-parcels-019` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:266` | … fraction (Related wells) | `wip.fraction` | `parcels/views.py:165` | `none (model field, fetched at parcels/views.py:106)` | `wells_wellirrigatedparcel` | 1.00 | 1.00 | MATCH | MATCH | Independence: restatement of a stored value. The share of this well's pumping attributed to this parcel. One well is linked here, so 1.00 means all of it. Renders only while the wells module is switched on, which it is on this deployment (observed: the Related wells card is in the captured page). |
| `FIG-parcels-020` | `/parcels/32/` | `templates/parcels/partials/_detail_pane.html:306` | Amount (AF), first row of Recent ledger entries | `entry.amount_acre_feet` | `parcels/views.py:166` | `none (model field, fetched at parcels/views.py:107)` | `parcels_parcelledger` | -75.23 | -75.23 | MATCH | MATCH | Independence: restatement of a stored value. The most recent of the parcel's ten latest rows, a canal delivery dated 15 September 2026. Note this list is NOT scoped to the year the balance card above it is showing, so the two halves of the pane can be describing different spans of time. |

### The same twenty figures, pinned to `MER-APN-017` (the agreeing case)

The `site`, `context_var`, `view`, `service` and `raw_tables` columns are the same
line of the same template rendered for a different parcel, so they are identical
to the table above and are not repeated. What changes is the numbers.

| `id` | `label` | `rendered` | `recomputed` | `delta` | `verdict` | `notes` |
|---|---|---|---|---|---|---|
| `FIG-parcels-001` | Consumptive use (ET) | 263.07 | 263.07 | MATCH | MATCH | |
| `FIG-parcels-002` | Total supplies | 395.97 | 395.97 | MATCH | MATCH | |
| `FIG-parcels-003` | Supplies − consumptive use | 132.90 | 132.90 | MATCH | MATCH | Agrees with `FIG-parcels-015` below, exactly. This parcel banked no incidental recharge in the year, so the two balances have nothing to differ by. |
| `FIG-parcels-004` | Net consumptive demand | 235.43 | 235.43 | MATCH | MATCH | |
| `FIG-parcels-005` | Surface water | 0.00 | 0.00 | MATCH | MATCH | A real zero: this parcel took no canal delivery in the year and met its demand by pumping. |
| `FIG-parcels-006` | Groundwater | 368.34 | 368.34 | MATCH | MATCH | |
| `FIG-parcels-007` | Precipitation | 27.64 | 27.64 | MATCH | MATCH | |
| `FIG-parcels-008` | Supplies: Surface | 0.00 | 0.00 | MATCH | MATCH | |
| `FIG-parcels-009` | Uses: ET | 263.07 | 263.07 | MATCH | MATCH | |
| `FIG-parcels-010` | Supplies: Precip | 27.64 | 27.64 | MATCH | MATCH | |
| `FIG-parcels-011` | Uses: Recharge | 0.00 | 0.00 | MATCH | MATCH | Zero, which is why this parcel's two balances agree. |
| `FIG-parcels-012` | Supplies: Groundwater pumped | 368.34 | 368.34 | MATCH | MATCH | |
| `FIG-parcels-013` | Uses: Runoff | 0.00 | 0.00 | EXPLAINED | EXPLAINED | The fixed zero again. Same reason as the table above. |
| `FIG-parcels-014` | Uses: Net Banked/Drawn (credits) | 0.00 | 0.00 | MATCH | MATCH | |
| `FIG-parcels-015` | Residual | 132.90 | 132.90 | MATCH | MATCH | Equal to `FIG-parcels-003`. The badge beside it reads *Surplus* in orange, and the page prints a sentence saying more water is recorded arriving here than the parcel's uses account for. That is the pane behaving as designed. |
| `FIG-parcels-016` | surface (ET-not-computed notice) | not rendered | 0.00 | n/a | `UNVERIFIED` | Branch unreachable, as above. |
| `FIG-parcels-017` | groundwater (ET-not-computed notice) | not rendered | 368.34 | n/a | `UNVERIFIED` | Branch unreachable, as above. |
| `FIG-parcels-018` | Area (Acres) | 89.84 | 89.84 | MATCH | MATCH | |
| `FIG-parcels-019` | … fraction (Related wells) | 1.00 | 1.00 | MATCH | MATCH | |
| `FIG-parcels-020` | Amount (AF), first ledger row | -47.48 | -47.48 | MATCH | MATCH | A meter reading dated 15 September 2026. |

---

### What section B found

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
