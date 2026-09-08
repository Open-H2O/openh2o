<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Triage: every ledger disagreement, verified before it became an issue

**Why this file exists.** An audit result is a queue, not a verdict. A pass like
the figure ledger produces a list of *suspicions*, and a fair share of any such
list is the auditor's own error rather than the platform's. Filing the raw list
into `ISSUES.md` would hand the next phase a queue it cannot trust, and would
inflate this platform's defect count with mistakes made while checking it.

So every row in `docs/figure-ledger-2026-09.md` that is not a plain `MATCH` was
taken up again here and **re-derived by a third route**: a different SQL
identity, a different pinned instance, a second year, or the source of the build
step rather than the row count it produced. Only what survived that was filed.

**The ratio, with its denominator.** Twenty-two ledger rows carry something other
than `MATCH`. Of those:

| Classification | Rows | Distinct findings |
|---|---:|---:|
| **CONFIRMED**, the platform shows something its own rows do not support | 6 | 3 |
| **ALREADY KNOWN**, an existing issue wearing a different hat | 2 | 1 |
| **EXPLAINED**, a stated and verified reason that is not a measurement | 14 | n/a |
| **AUDITOR ERROR**, the first recomputation was wrong | 0 | n/a |
| **Total** | **22** | **4** |

No ledger row's arithmetic turned out to be the auditor's mistake. Every
recomputed number in the ledger reproduced on the third route, to the cent.

**But three claims carried *into* this plan were wrong, and two of them were
alarming.** They did not come from a ledger row's arithmetic. They came from
prose written around it, and they are set out in full in section B below.

| Claim | Where it was written | Verdict |
|---|---|---|
| The demonstration is missing its entire monitoring-station dataset | `STATE.md`, and the ledger's summary block | **WRONG.** The audited database is a `make fresh` database; the shipping artifact loads all 335 |
| "Nine rows carry an issue number" | `docs/figure-ledger-2026-09.md:69` | **WRONG.** It is eight, and the ledger's own table two paragraphs above says eight |
| The ISS-141/142/143 bookkeeping is already done | `135-03-PLAN.md`, Task 3 | **WRONG for ISS-141.** Its body was repaired, its index row was never added, so it appears in no table in the file |

**Claims checked: 25. Claims wrong: 3.** All three are prose about numbers, not
numbers.

---

## A. The twenty-two ledger rows

### A1. CONFIRMED: three findings, six rows

Each was re-derived by an identity the original recomputation did not use, and
each held.

---

#### CONFIRMED 1: the district page counts canal water as pumping

**Rows:** `FIG-geography-002` (Used, AF), `FIG-geography-003` (Remaining, AF).
**Screen:** `/map/zones/2/`, Halvern Irrigation-Urban GSA, WY 2025-2026.
**Filed as ISS-154.**

**What the screen says.** Used 1,313.07 AF against a 750.32 AF groundwater
allocation, so Remaining reads **-562.75 AF** and the district is over budget.
The column heading carries the word *pumped*.

**The first derivation** transcribed `geography/views.py:196-201` as written: the
absolute value of the sum of every negative billable ledger row, whatever its
source type.

**The third route** partitions those same negative rows by `source_type` and runs
it over **all three groundwater districts and both water years** rather than the
one pinned cell. If the column really were pumping, the canal partition would be
empty.

| District | Water year | Allocation | Used, as the screen computes it | Canal water inside that | Groundwater alone | Remaining as screened | Remaining on groundwater alone |
|---|---|---:|---:|---:|---:|---:|---:|
| Halvern Irrigation-Urban GSA | WY 2024-2025 | 750.32 | 1,267.62 | 1,130.03 | 137.59 | -517.30 | **+612.73** |
| Halvern Irrigation-Urban GSA | WY 2025-2026 | 750.32 | 1,313.07 | 1,170.93 | 142.14 | -562.75 | **+608.18** |
| Halvern Valley GSA | WY 2024-2025 | 9,689.40 | 13,653.28 | 11,134.82 | 2,518.46 | -3,963.88 | **+7,170.94** |
| Halvern Valley GSA | WY 2025-2026 | 9,689.40 | 13,379.29 | 10,236.78 | 3,142.51 | -3,689.89 | **+6,546.89** |
| Verdano Island Water District GSA | WY 2024-2025 | 731.74 | 1,028.48 | *(none)* | 1,028.48 | -296.74 | -296.74 |
| Verdano Island Water District GSA | WY 2025-2026 | 731.74 | 1,092.73 | *(none)* | 1,092.73 | -360.99 | -360.99 |

**CONFIRMED, and the third route makes it stronger than the ledger stated, in two
ways.**

1. **It holds in both years, not just the pinned one.** The ledger pinned
   WY 2025-2026. The wet year is the same shape, and slightly worse in absolute
   terms for Halvern Valley (-3,963.88 screened against +7,170.94 real).
2. **Verdano Island is the negative control, and it behaves.** It takes no canal
   water at all, so its two columns are identical to the cent and its
   over-budget reading is true. A page that showed the fault everywhere would
   more likely be a bad query. A page where exactly the canal-fed districts flip
   and the canal-free one does not is the fault the issue describes.

**Owner: Phase 137** (the panel and the pages). The fix is a source-type filter
in `geography/views.py:196-201`, matching the one the surface branch at `:210`
already applies.

---

#### CONFIRMED 2: the use ledger and the dashboard state the year with opposite signs

**Rows:** `FIG-accounting-053` (net), `FIG-accounting-054` (credits),
`FIG-accounting-055` (debits).
**Screen:** the use ledger, WY 2025-2026. **Filed as ISS-155.**

**The first derivation** summed the ledger footer over the account-and-zone
membership union the dashboard SQL builds.

**The third route** drops the membership union entirely and runs a
whole-population pass over every row in the period: no account join, no zone
join, no suppression ladder. If the two screens were reading different row sets,
this route would disagree with both.

| Quantity | Third-route value | The screen |
|---|---:|---|
| Rows in the period | 1,130 | n/a |
| Distinct parcels | 76 | n/a |
| Credits (positive rows) | +14,280.77 | `FIG-accounting-054` ✓ |
| Debits (negative rows) | -15,785.09 | `FIG-accounting-055` ✓ |
| **Ledger footer, net** | **-1,504.32** | `FIG-accounting-053` ✓ |
| Canal deliveries, magnitude | 11,407.71 | n/a |
| Groundwater, magnitude | 4,377.38 | n/a |
| Effective rainfall | 1,673.2659 | n/a |
| **Dashboard supplies** (canal plus groundwater plus rainfall) | **17,458.35** | dashboard ✓ |
| Gross evapotranspiration | 16,209.28 | n/a |
| **Dashboard net vs supply** | **+1,249.07** | dashboard ✓ |

**CONFIRMED.** Both arithmetics are correct over exactly the same 1,130 rows.
The two screens differ because they classify the same water differently: the
ledger footer splits on the *stored sign*, so canal deliveries (-11,407.71) and
pumping (-4,377.38) book as debits, while the dashboard calls both of them
**supplies**. The 14,280.77 of credits is allocation paper plus recharge, no
water delivered to anybody. Neither page says any of this.

**One method note worth keeping, because it produced a one-cent phantom.**
Rounding the three supply terms to two decimals *before* subtracting gives
+1,249.08 and 17,458.36, a false one-cent disagreement with the screen. The
figures above are computed at full precision and rounded once, at the end. Any
future recomputation of a supplies total must do the same, or it will report a
delta that is its own rounding.

**Owner: Phase 136** (one vocabulary of water use). This is the same question
ISS-151 and ISS-153 ask at other scales.

---

#### CONFIRMED 3: the allocations footer adds surface water to groundwater

**Row:** `FIG-accounting-022`. **Screen:** the allocations page, WY 2025-2026.
**Filed as ISS-156.**

**The first derivation** summed `allocation_acre_feet` across the period's
allocation plans and got the printed 159,671.46.

**The third route** groups that same sum by the plan's water type, and runs both
years, so the partition is visible rather than asserted.

| Water year | Surface-water plans | Surface AF | Groundwater plans | Groundwater AF | Footer as printed |
|---|---:|---:|---:|---:|---:|
| WY 2024-2025 | 5 | 155,700.00 | 3 | 11,171.46 | 166,871.46 |
| WY 2025-2026 | 5 | 148,500.00 | 3 | 11,171.46 | **159,671.46** |

**CONFIRMED**, and the wet year shows it is not an artifact of one period. The
footer is a true sum of two quantities no agency manages together: a
surface-water district's diversion entitlement, and a groundwater sustainability
agency's pumping allowance. Printed as one number, in acre-feet, with no label
saying it is a mixture.

**Related, and recorded rather than filed separately.** The word *allocation*
names two different quantities on two screens in the same year: 159,671.46 AF of
zone plans here, 13,819.63 AF of per-parcel ledger entries on the use ledger
(third route, `source_type='allocation'`, both periods, identical at 13,819.63).
Neither screen mentions the other. That belongs inside ISS-156, not beside it.

**Owner: Phase 138** (presentation). The smallest honest fix is to stop printing
the total, or to print the two subtotals.

---

### A2. ALREADY KNOWN: one finding, two rows

#### `FIG-parcels-003` and `FIG-parcels-015`, the pane's two balances

Both carry `ISS-148`, **already filed**. Not re-opened, not given a new number.

The third route is the parcel band review in
`docs/figure-ledger-2026-09.md` ("The parcels outside the realistic band"), which
re-derives card 3 and the residual for all 76 parcels in both years from the
stored calculation runs rather than from the pane. The gap is one term every
time: incidental recharge, counted as an unused supply by the card and as an
output by the residual, over 152 parcel-years with zero exceptions.

**Owner: Phase 136**, answered together with ISS-143, ISS-151 and ISS-153, which
is what all four of their re-entry conditions ask for.

---

### A3. EXPLAINED: fourteen rows, each with a verified reason

None of these is a defect, and none was taken on trust. Each reason was checked
against source, or against the database, on a route the ledger did not use.

| Rows | Ledger's reason | Third-route check | Holds? |
|---|---|---|---|
| `FIG-parcels-013` (in both tables) | A fixed zero written into the code; the platform models no surface hydrology | Read the source: `accounting/services.py:767`, `runoff = Decimal("0")  # bookkeeping boundary: no surface-hydrology model.` The mass-balance identity at `:702` carries it as a named term | ✅ |
| `FIG-parcels-016`, `FIG-parcels-017` (in both tables) | The branch shows only when a parcel has no calculation runs for the year, and every parcel has them | Counted parcels with zero runs, per year, across all 76 MER parcels: **zero in both years**. The branch cannot be reached on this data | ✅ |
| `FIG-accounting-005`, `FIG-accounting-006`, `FIG-accounting-007` | The banked-water block, and no run in this database carries a deposit or a draw | 1,824 calculation runs: **0** with a non-zero `banked_af`, **0** with a non-zero `drawn_af`. Five `WaterCredit` rows exist, and **all five hold 0.0000 AF**, so there is nothing for the block to show even from the credit table | ✅ |
| `FIG-accounting-059` | The fallback sentence for a method that produces no steps; all five steps on the active method are enabled | Confirmed against `accounting_calculationstep`. Reaching it would need a configuration change this phase may not make | ✅ |
| `FIG-setup-001` | The confirmation step reads the boundary out of the visitor's session, which only the previous step's form submission writes | The capture performs page requests only, so the screen redirected. The same stored field renders on the previous step, and is verified there | ✅ |
| `FIG-wells-003`, `FIG-wells-004` | Values a person typed; nothing on the platform derives them | Confirmed at `wells/views.py:173-182`: every editable field is a plain `getattr` off the model. The two numbers agreeing shows the platform redisplays what was entered, and nothing more | ✅ |
| `FIG-datasync-001`, `FIG-datasync-002`, `FIG-datasync-003`, `FIG-datasync-004` | "No station exists to open" | **The verdict is right and the ledger's stated reason is misleading.** See B1 | ⚠️ reason corrected |

---

## B. Three claims that did not survive checking

### B1. The monitoring-station alarm is wrong, and it is the one worth the space

**What was written**, in `STATE.md` and echoed in the ledger's summary block:

> **THE DEMONSTRATION IS MISSING ITS ENTIRE MONITORING-STATION DATASET, and
> nothing was watching.** `datasync_monitoredstation` = 0 rows,
> `datasync_datarecordstaging` = 0 readings ... pins them at **335** and
> **30,217**, tolerance zero ... Four figures nobody has ever seen render.

**Both row counts are correct. The conclusion drawn from them is not.**

The audited database is a **development** database, built by `make fresh`. The
counts pinned in `data/demo/expected_shape.json` describe the **shipping golden
artifact**, built by `scripts/rebuild-golden.sh`. They are different builds, and
the difference is exactly these two tables:

| Build step | `make fresh` (`Makefile:280-291`) | `rebuild-golden.sh` |
|---|---|---|
| `seed_merced` | yes, **with** live `auto_populate` | yes, `--skip-auto-populate` |
| `load_station_fixture` | **never runs** | `:178`, loads all 335 |
| `load_reading_fixture` | **never runs** | `:186`, loads the readings |
| `load_openet_fixture` | n/a | `:187` |

`rebuild-golden.sh:172-175` states the mechanism in its own comment, written
before this audit existed:

> Station discovery is part of `auto_populate`, which `--skip-auto-populate`
> above omits, so **without this the build carries ZERO monitoring stations and
> the landing page reads "0 of 0 stations reporting"**.

`seed_merced.py:82-98` says the same from the other side. The fixture is
deliberately not part of `seed_merced`, because `auto_populate` is the right
behaviour for a genuine first-time deployment discovering its *own* stations, and
`discover_stations` creates rows with `is_active=False` regardless, so even a
successful live discovery would not produce the 42 active stations the hero
counts.

**Verified three ways, none of which is the row count that raised the alarm:**

1. `data/merced/stations.json` on disk holds exactly **335 records**.
2. `rebuild-golden.sh` runs both loads, in the order its comments require.
3. The `Makefile`'s `fresh` target runs neither.

**Classification: AUDITOR ERROR.** Not a platform defect, not a seed defect, and
**no issue is filed.** The four `FIG-datasync-*` rows keep their `UNVERIFIED`
verdict, because they genuinely could not be recomputed here, but their stated
reason changes from "the demonstration is missing its stations" to "the audited
build does not load them; the shipping build does."

**What is left over, and it is small.** Nothing in the repository *checks* that a
development database differs from the golden only in ways somebody chose. Gate 2
runs against the golden, correctly. That gap is worth a note in the next
milestone's scoping, not an issue against the platform: it is a property of the
audit environment, and inventing an issue for it would be exactly the inflation
this file exists to prevent.

### B2. The ledger contradicts its own table by one row

`docs/figure-ledger-2026-09.md:69` reads "Nine rows carry an issue number, and
they name four problems." The verdict table sixteen lines above it says
`MATCH · ISS-###` = 4 and `ISS-###` = 4. Parsing every row in the document gives
**eight**: `FIG-parcels-003`, `FIG-parcels-015` (ISS-148); `FIG-geography-002`,
`FIG-geography-003` (ISS-154); `FIG-accounting-053`, `FIG-accounting-054`,
`FIG-accounting-055` (ISS-155);
and `FIG-accounting-022` (ISS-156). Four problems is right. Nine rows is not.
Corrected to eight in this plan.

### B3. ISS-141 appears in no index table in `ISSUES.md`

The plan for this task records the ISS-141/142/143 bookkeeping as already
repaired, and says not to redo it. That is right for ISS-142 and ISS-143, whose
index rows exist at `ISSUES.md:155` and `:156`. It is **wrong for ISS-141**. Its
body at `:472` does read `✅ CLOSED 2026-09-05 (Phase 131)`, but no index row for
it exists in the Open table or the Closed table. Parsing the whole file gives 150
index rows against 148 bodies, and the difference is ISS-154/155/156 (index rows
with no body, which this plan writes) and ISS-141 (a body with no index row,
which this plan also writes). Its closure is recorded at `ISSUES.md:42` and in
`MILESTONES.md`, so nothing was lost. But a reader working from either index
table cannot see that the issue exists.

---

## C. Method

Every derivation above ran through `audit/figure_ledger/run_sql.sh`, which pipes
SQL text into `psql` in the `db` container **from the host**. It never enters the
Python process that owns the object-relational mapper, so it cannot call the code
whose arithmetic it checks. The reusable file is
`audit/figure_ledger/sql/triage_third_route.sql`. Source-file claims were checked
by reading the file and quoting the line.

*Triaged 2026-09-05, against the working tree at `a493211`.*
