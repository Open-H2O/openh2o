# The reading standard, 2026-09

*Written 2026-09-07 by Phase 140, Plan 01 of milestone v2.17 "Screens That Explain
Themselves".*

Four presentation passes brought every page onto one design system, and the dashboard's
account table is now perfectly on-system and still does not say that three of its columns
add up to a fourth. This document is the instrument for what those passes could not
measure: whether a screen tells its reader what the numbers on it mean. Phase 140-02
walks all 80 pages against it; Phases 141-144 work the register it produces.

## Part 1. The test, and what it is not

**The two-audience test.** A reader who does not work in water can say what the screen
is about and what the biggest number on it means; a district engineer can find the figure
they came for without reading the page.

That is not the test the prior passes ran. A pass that checks that every table uses
`.data-table` and every corner is square can be run by a script, ship green, and leave a
table of eight like-weighted columns where three are parts of a fourth, one is the
difference of two others and two belong to a different regulatory framework. Consistency
asks whether surfaces match each other; this standard asks whether each surface, alone,
lets the two readers do the two things above. Every criterion below is a question about
what a reader can *say* or *find*, never about a property a stylesheet has.

**How this relates to `DESIGN.md`.** `DESIGN.md` governs appearance and words (its
components, tokens and copy rules 1-12). This standard governs meaning: what a surface is
for and how a reader is meant to use it. Where the two seem to conflict, appearance
defers to meaning: `DESIGN.md` defers to this file on what a surface is for, and this
file defers to `DESIGN.md` on what it looks like once that is settled.
`docs/page-pass-2026-09.md` already states each page's purpose, lead figure and exit; a
finding cites that row rather than restating it. The three layout buckets of
`docs/2.0-UX-PATTERN-SPEC.md` (master-detail workspace, dense data table, overview then
detail) stay the only layout taxonomy.

## Part 2. What each surface is for

Seven surface types cover every rendered page. Each section says what a reader does with
the surface, asks the two-audience test as questions about it, shows a failing example
read off a staging capture (commit `241c22b`, 2026-09-07), and says what explaining
itself looks like, without prescribing how. Copy rule 11 holds throughout: a surface
explains the software and the data conventions, never the water.

**L** marks the reader who does not work in water; **E** the district engineer.

### Data table

**What a reader does with it.** Finds one row, reads one figure across it, and compares
it with its neighbours in the same column.

**The questions.**
1. *(L)* From the caption and the header row alone, can the reader say what one row *is*
   and what the largest number in the table measures?
2. *(E)* Can the reader land on the column they came for without reading across the row,
   and can they say why the columns are in the order they are in?
3. *(both)* Where columns are related by arithmetic (parts of another, the difference of
   two others, a share of another) or come from different frameworks (water measured
   against water allocated on paper), does the table *show* the relation, or print them as
   one flat row of like quantities?
4. *(E)* Can the reader say what order the rows are in, and does a row offer the way in
   that other tables offer for the same kind of thing?

**A failing one.** The dashboard's Active water accounts table
(`templates/accounting/partials/_dashboard_content.html:117-126`) heads eight numeric
columns identically: Consumptive Use, Surface, Groundwater, Precip, Supplies, Net, GW
allocation, GW remaining. Nothing says the middle three are the parts of Supplies, that
Net is Supplies less Consumptive Use, or that the last two are allocation on paper rather
than water that moved; at a 1440-pixel window the last header is cut off the card's edge. The Use Ledger
(`templates/accounting/partials/_ledger_list_results.html:24-62`) orders Date, Parcel,
Amount, Source, Water Type, Description; the reader cannot say why Amount sits between
Parcel and Source, nor, from the header, that a positive amount is paper and a negative
one is water leaving a canal or a well. That sentence is in the footer, a hundred rows
down.

**What explaining itself looks like.** The header row says which columns belong together
and which one they make; a derived column is visibly derived; a column from a different
framework sits apart from the measured ones; and a name that is a link in one table is a
link in the next.

### Stat and tile row, including the budget panel

A tile row is a short line of named figures; the house `.budget-panel` is one that states
an equation.

**What a reader does with it.** Reads the figure the page leads with, and sees at a glance
the two or three figures that make it.

**The questions.**
1. *(L)* Does the row's title say what the figures *are* (the thing being summarised),
   before the reader has read a single figure?
2. *(both)* Is the largest type on the page the figure the page leads with, and does the
   row's space carry information rather than fill it?
3. *(E)* Where the row states an equation, is the operation visible and does the result
   carry a name that says what kind of number it is (a balance, a residual, a total)?
4. *(L)* Does the foot or breakdown say how it relates to the figures above it?

**A failing one.** The dashboard's panel is titled "Supply vs. use"
(`templates/accounting/partials/_dashboard_content.html:18`), which names an operation,
not the thing summarised; a reader cannot say from the title that this is the district's
whole-basin position for the year. Its three figures are the largest type on the page,
inside a panel far wider than they need, and the foot (`:52-56`) lists Surface,
Groundwater and Rain without saying they are the parts of the Supplies figure above.

**What explaining itself looks like.** The title names the thing (an overall basin
summary for the period); the figures are as large as their place warrants and no larger;
the result is named for what it is; and the breakdown reads as "of which".

### Page head: breadcrumb, title, description and actions

**What a reader does with it.** Confirms at a glance which screen this is, what its
numbers are, and where to act.

**The questions.**
1. *(L)* Can the reader say what this screen is about from the crumb, the title and the
   description in one read, and is there a visible title at all?
2. *(E)* Are the page's actions where the eye expects them, beside the thing they act on,
   and does their position say what they act on?
3. *(both)* Does the description state the data convention the page uses (what a positive
   number is, what period is shown, what the rows are), rather than describing the water?

**A failing one.** On Surface Diversions the Import and Add diversion buttons sit in a
row of their own under the description (`templates/surface/pod_list.html:25-30`), leaving
a wide empty band between the words and the buttons; the spacing reads as avoiding a
collision rather than using the space. The Use Ledger puts the same kind of buttons below
the demo banner instead (`templates/accounting/ledger_list.html:21-38`), so a reader who
learned where actions live on one page looks in the wrong place on the next. The only visible title on any page is the
last crumb (`templates/base.html:109`).

**What explaining itself looks like.** Crumb, title and description read as one block;
the actions sit with it, at its end; the description says in a sentence what the numbers
on the page are.

### Filter bar

**What a reader does with it.** Narrows a list to the rows they came for, and sees what
it is narrowed to.

**The questions.**
1. *(L)* Can the reader say what the filters narrow, and what is applied right now?
2. *(E)* Is the control the reader reaches for most (the period, the one record) in the
   first row, and is the bar's size in proportion to the ways a reader would actually
   narrow this list?
3. *(both)* After a filter is applied, does the page say what it now shows, and does
   every surface on the page (the map beside the list, the totals under it) follow the
   same filter?

**A failing one.** The Use Ledger's filter is a full card of four rows: quick-filter chips
(`templates/accounting/ledger_list.html:61-74`), a search-period-zone toolbar (`:84-141`),
a hidden advanced row, and rows-per-page with jump-to-page (`:208-239`); the card pins to
the top of the window as the reader scrolls (`:53`). To read one water year's entries the
reader gives up a third of the screen to controls they will not touch.

**What explaining itself looks like.** The one or two controls a reader uses on every
visit are in view and the rest a step away; the result line says what is showing; a map
or a total on the same page answers the same question the filtered list does.

### Map

**What a reader does with it.** Finds the record they came for by where it is, and opens
it.

**The questions.**
1. *(L)* Can the reader say what the marks on the map *are* from the map alone, without
   clicking one?
2. *(E)* Can the reader get from a mark to that record's own page, and can they leave the
   map by scrolling without the map capturing the scroll?
3. *(both)* Does the map answer the same question as the list beside it: same filter,
   same count?

**A failing one.** Surface Diversions opens with a map that fills the first screen
(`templates/surface/pod_list.html:39-41`): nine unlabelled teal dots on aerial imagery,
no legend, and the count ("9 diversion points found") a scroll below. The reader learns
what a dot is only by clicking it. Scroll capture (ISS-159 #3) shipped in Phase 138 and
is not a finding; question 2 keeps it true.

**What explaining itself looks like.** The map says what it shows and how many; a mark is
visibly a way in; filtering the list filters the map.

### Sidebar

**What a reader does with it.** Finds the section of the platform they need, and knows
which page they are on.

**The questions.**
1. *(L)* Can the reader say from each section label what that group of links is for,
   without knowing the platform's module names?
2. *(E)* Does exactly one entry light on every page, and does it carry the same name as
   the page head does?
3. *(both)* Are the sections in the order a reader would use them?

**A failing one.** On the dashboard the crumb reads "Accounting / Dashboard" while the
sidebar, whose sections come from the module registry
(`templates/partials/_sidebar.html:55-59`), has no section called Accounting; the lit
entry sits in an unlabelled group with Home and Map. Under Drinking Water an entry reads
"Onboard System", a software verb a layperson cannot place. On `/map/zones/` two entries
light (ISS-133).

**What explaining itself looks like.** A section label names what a reader would call
that group; one entry lights; the sidebar and the page head use the same words for a
page.

### Body prose: help, about, and the inset explainers on data pages

**What a reader does with it.** Learns in a paragraph what a screen or figure is and how
the platform arrived at it.

**The questions.**
1. *(L)* After the first paragraph, can the reader say what the page or the panel is for?
2. *(E)* Does the prose explain only the software and the data conventions, never the
   water? A sentence that tells an engineer what a well is fails this reader.
3. *(both)* Does an explainer sit beside the figure it explains, and say the same thing
   the figure's own surface shows?

**A failing one.** The dashboard's inset "How this summary works"
(`templates/accounting/partials/_dashboard_content.html:60-65`) says consumptive use is
met by three supplies: the relation the table beneath does not show, stated in prose
between the panel and the table and belonging to neither. On the Use Ledger the inset
says the running balance is allocation minus usage
(`templates/accounting/ledger_list.html:44`) and the footer says the two are never netted
(`templates/accounting/partials/_ledger_list_results.html:122`).

**What explaining itself looks like.** An explainer says in words what the surface beside
it shows; two sentences on one page never define the same quantity differently; and no
sentence explains the water.

## Part 3. The register

Phase 140-02's readers propose rows in this format; the rank is computed, not chosen.

**Columns.**

| Column | What goes in it |
|---|---|
| id | `R-###`, in order of filing, never reused |
| page | census number and path (`c1 /accounting/dashboard/?period=2`) |
| surface | one of the seven above |
| finding | one sentence a layperson could read: what the reader cannot say or find |
| audience | `L`, `E` or `both` |
| read | the screenshot file and `template:line` |
| blast radius | the template or partial and how many pages render it; a shared partial is one finding with N pages, never N findings |
| owner | `141` type scale · `142` dashboard table and tile row · `143` other tables, filter bars, page heads, maps · `144` prose and sidebar · `decided: keep`, with the reason |
| rank | by the rule below |

**The ranking rule.** It is mechanical so that the rank is a measurement.

1. Band by audience: `both` outranks `L` and `E`, which tie.
2. Within a band, by blast radius, pages descending.
3. A fault Brent already named is pinned to the top of its band, in ISS-159's item order.
4. Ties break on the page-pass table's verdict: a page whose purpose is a lead figure
   outranks one with several figures and none leading, which outranks a router page;
   then filing order.

**The per-page verdict.** Each of the 80 pages gets one: `PASS`, `FAIL-L`, `FAIL-E` or
`FAIL-both`, with the register ids that make it fail. A page fails an audience when any
surface on it fails a question marked for that audience.

**Open issues the register absorbs or declines.** ISS-159 (#1, #2, #4, #5), ISS-162
(one row, blast radius 36 templates, owner 141, never once per page), ISS-163, ISS-023,
ISS-022, ISS-110 part 2, ISS-136, ISS-161, ISS-133. ISS-143 is `decided: keep` (Brent,
2026-09-06). ISS-159 #3 shipped in Phase 138 and is not a finding.

## Part 4. The calibration rule

This standard is an instrument only if, applied cold to the dashboard, it yields ISS-159
items #1 and #2; to the Use Ledger, item #4; to Surface Diversions, item #5, with no
question naming those faults. If it does not, Part 2's questions are wrong and are
revised until the fault falls out of them. Plan 140-01 performs that check and records
the ratio of rows produced to rows already named.
