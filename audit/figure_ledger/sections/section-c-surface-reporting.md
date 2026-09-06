# Section C: surface water and state reporting (14 figures)

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

## The 14 figures

`service` reads `none` where the value is a plain model field on an object the
view fetched, rather than the schema's dash.

| `id` | `screen` | `site` | `label` | `context_var` | `view` | `service` | `raw_tables` | `rendered` | `recomputed` | `delta` | `verdict` | `notes` |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `FIG-surface-001` | `/surface/diversion/9/` | `templates/surface/partials/_detail_pane.html:57` | Max rate (CFS) | `pod.max_rate_cfs` | `surface/views.py:166` | none | `surface_pointofdiversion` | 150.00 | 150.00 | MATCH | MATCH | Independence: different identity. Model field on the diversion point the view fetched at `surface/views.py:186`. Wrapped in a conditional, so it renders only where a rate is recorded; see finding 3. |
| `FIG-surface-002` | `/surface/diversion/9/` | `templates/surface/partials/_detail_pane.html:159` | Face value (AF) | `water_right.face_value_acre_feet` | `surface/views.py:172` | none | `surface_waterright, surface_pointofdiversion` | 60000.00 | 60000.00 | MATCH | MATCH | Independence: different identity. The linked right's field, reached through the diversion point. Also conditional: no linked right, or a right with no face value, and nothing renders. |
| `FIG-surface-003` | `/surface/diversion/9/` | `templates/surface/partials/_diversion_records.html:20` | Diverted (AF) | `record.volume_acre_feet` | `surface/views.py:167` | none | `surface_diversionrecord` | 250.00 | 250.00 | MATCH | MATCH | Independence: different identity. Whole column also checked, all 8 records on this diversion point, cross-check 3. |
| `FIG-surface-004` | `/surface/diversion/9/` | `templates/surface/partials/_diversion_records.html:21` | Return Flow (AF) | `record.returned_af` | `surface/views.py:167` | none | `surface_diversionrecord` | 100.00 | 100.00 | MATCH | MATCH | Independence: different identity. This is one of only two records in the whole demonstration where this column is neither 0 nor the full diverted volume, which is why the row was pinned here. |
| `FIG-surface-005` | `/surface/diversion/9/` | `templates/surface/partials/_diversion_records.html:23` | Consumptive Use (AF) | `record.consumed_acre_feet` | `surface/views.py:167` | `DiversionRecord.consumed_acre_feet` (`surface/models.py:162`) | `surface_diversionrecord` | 150.00 | 150.00 | MATCH | MATCH | Independence: restatement of one subtraction, `abs(volume) - returned`. Strengthened by cross-check 1, which applies the identity to all 173 records and finds 0 breaks and 0 rows where the return exceeds the volume. A method on the model, not a service. |
| `FIG-surface-006` | `/surface/rights/` | `templates/surface/partials/_list_results.html:30` | Face Value | `right.face_value_acre_feet` | `surface/views.py:288` | none | `surface_waterright` | 120000 | 120000 | MATCH | MATCH | Independence: different identity. Shown to zero decimal places, with the unit "AF" as template text beside it rather than part of the figure. All six rights checked whole-column, cross-check 2. |
| `FIG-surface-007` | `/surface/rights/7/` | `templates/surface/partials/_water_right_detail_pane.html:64` | Face value (AF) | `water_right.face_value_acre_feet` | `surface/views.py:343` | none | `surface_waterright` | 60000.00 | 60000.00 | MATCH | MATCH | Independence: different identity. The same stored column as `FIG-surface-006`, shown to two decimal places instead of none; the two screens agree. |
| `FIG-surface-008` | `/surface/rights/7/` | `templates/surface/partials/_water_right_detail_pane.html:113` | Max rate: N cfs | `pod.max_rate_cfs` | `surface/views.py:344` | none | `surface_pointofdiversion` | 400.00 | 400.00 | MATCH | MATCH | Independence: different identity. Renders once per diversion point on the right, ordered by name; the pin is the first, MER-POD-010-DEMO Merced Falls Hydroelectric Diversion. |
| `FIG-surface-009` | `/surface/rights/7/` | `templates/surface/partials/_water_right_detail_pane.html:174` | Volume (AF) | `record.volume_acre_feet` | `surface/views.py:345` | none | `surface_diversionrecord, surface_pointofdiversion` | 1200.00 | 1200.00 | MATCH | MATCH | Independence: different identity. First row of a 12-row list ordered by month alone; two diversion points sharing a month would be in an unspecified order, so the pin sits on September 2026, which only one has. This figure is a **diverted** volume with no return-flow column beside it, and all 1200.00 AF of it was returned to the stream: see finding 4. |
| `FIG-reporting-001` | `/reporting/reports/4/calwatrs-worksheet/` | `templates/reporting/calwatrs_worksheet.html:84` | Volume (AF) | `row.volume_af` | `reporting/views.py:443` | none | `surface_diversionrecord, surface_pointofdiversion, reporting_reportsubmission` | 877.47 | 877.47 | MATCH | MATCH | Independence: different identity. The stored volume, copied into a display dictionary at `reporting/views.py:437`. The worksheet shows this block; the generated state file withholds it, correctly, because the diversion point has no water right. See finding 2. |
| `FIG-reporting-002` | `/reporting/reports/4/calwatrs-worksheet/` | `templates/reporting/calwatrs_worksheet.html:85` | Max Rate (CFS) | `row.max_rate_cfs` | `reporting/views.py:443` | none | `surface_diversionrecord` | 312.07 | 312.07 | MATCH | MATCH | Independence: different identity. Stored as 312.0662 and shown to two places. Conditional: a record with no rate shows a dash. Note this is a peak rate stated against a whole month's volume, because a diversion record is monthly by design (`surface/models.py:160`). |
| `FIG-reporting-003` | `/reporting/reports/shared-supply-check/?period=2` | `templates/reporting/shared_supply_check.html:105` | Your share | `row.your_weight` | `reporting/views.py:296` | `build_shared_supply_comparison` then `apportion_shared_supply` | `surface_pointofdiversionparcel, parcels_parcel` | 0.2000 | 0.2000 | MATCH | MATCH | Independence: restatement. Reproduces the four-rung ladder, including which rung fires: some stored share here differs from the untouched default, so the whole group counts as hand-set and the stored shares are used as written. Cross-check 7 adds a different identity, that each group's shares sum to exactly 1.0000, and all 8 groups do. |
| `FIG-reporting-004` | `/reporting/reports/shared-supply-check/?period=2` | `templates/reporting/shared_supply_check.html:107` | ET-implied share | `row.et_weight` | `reporting/views.py:296` | `build_shared_supply_comparison` then `apportion_shared_supply` | `accounting_calculationrun, accounting_reportingperiod, surface_pointofdiversionparcel` | 0.1196 | 0.1196 | MATCH | MATCH | Independence: restatement, including the rule that the rounding residual lands on the last use area sorted as TEXT, not as a number. That rule is visible on this very screen: MER-APN-064 shows 0.0647 and MER-APN-063 shows 0.0648 although MER-APN-064's demand is fractionally the higher of the two. Cross-check 6 confirms no value in this data sits on an exact rounding tie, so the two rounding rules in play cannot differ here. |
| `FIG-reporting-005` | `/reporting/reports/shared-supply-check/?period=2` | `templates/reporting/shared_supply_check.html:110` | Gap | `row.divergence` | `reporting/views.py:296` | `build_shared_supply_comparison` (`reporting/generators.py:225`) | `accounting_calculationrun, surface_pointofdiversionparcel` | 0.0804 | 0.0804 | MATCH | MATCH | Independence: restatement. The absolute difference of the two shares above, not rounded again. Below the 0.15 flag threshold, so the pinned row carries no badge; one row in this group is flagged. |

## What section C found

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
