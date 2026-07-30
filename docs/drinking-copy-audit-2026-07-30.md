# Drinking-water copy audit — 2026-07-30

The evidence behind the **Copy rules** section of [`DESIGN.md`](../DESIGN.md).
Every rule there cites a row here; a rule with no row is invention and was not
written.

**Scope measured:** the 22 templates under `templates/drinking/` (10 pages, 12
partials) plus `drinking/glossary.py`. **Method:** counts are of *prose* — text
a reader sees. `{% comment %}`, `{# #}`, `<!-- -->`, `<script>` and `<th>` are
excluded, because a template comment is not copy and a data-table column header
is exempt from the casing rule by DESIGN.md and is uppercased in CSS anyway.
`{% source_label "KEY" %}` was resolved to the string `drinking/provenance.py`
actually renders before counting, so the counts are of words on screen and not
of constant names in markup.

Counts were taken against the tree at `ba93040` (the end of plan 101-01).

---

## Defects

| # | Defect | Measured | Where |
|---|---|---|---|
| D1 | The state's field name is written two ways | `PS Code` 3, `PS code` 4 | `_import_preview.html:54,78`, `_onboard_result.html:122` / `sampling_point_detail.html:103`, `sampling_points.html:32,91`, `_sampling_point_results.html:76` |
| D2 | `id` in prose against `ID` in labels | `id` 4, `ID` 7 | `onboard_points.html:48`, `_onboard_points.html:51`, `_onboard_review.html:29,117` |
| D3 | British spelling in visible text | 4 | `onboard_points.html:40` (*neighbourhood*), `_import_preview.html:104` (*recognised*), `_import_result.html:67` (*recognised*), `glossary.py:39` (*neighbourhood*) |
| D4 | Emphatic filler where the sentence already carries the fact | 2 | `facility_detail.html:101`, `sampling_points.html:79` — both "at all" |
| D5 | Bare `DDW` where the module writes the same body out in full | 2 | `import.html:35` (prose), `result_detail.html:57` (field label) |
| D6 | `GAMA` never expanded on any page that uses it | 5 prose uses, 0 expansions, 3 pages | `facility_detail.html:98`, `sampling_point_detail.html:80,90`, `sampling_points.html:70,77` |
| D7 | `SDWIS` never expanded where it names the system | 1 (the other 3 prose uses name the *file layout* `SDWIS.CSV`, which is not expandable) | `onboard.html:40` |
| D8 | `PWSID`'s letters never spelled out anywhere | 15 prose uses, 1 conceptual definition, 0 letter expansions | definition at `onboard.html:38`; bare labels on `overview.html:41`, `facility_detail.html:167`, `result_detail.html:195`, `_onboard_review.html:143` |
| D9 | The onboarding flow calls one thing two names | *sampling place* 7, *sampling point* 28 | `onboard_points.html:60,71,88,136,141,147`, `_onboard_points.html:36` |
| D10 | Breadcrumb missing the `Water Data` section root | 6 of 10 drinking pages missing it; 19 of 19 non-drinking Water Data pages carry it | `facilities.html`, `results.html`, `sampling_points.html`, `import.html`, `onboard.html`, `onboard_points.html` |
| D11 | The same page name breadcrumbed two ways | `Sampling Points` 2, `Sampling points` 1 | `onboard_points.html:13` is the outlier |
| D12 | HTML comment where the module uses `{% comment %}` | 1 of 22 templates | `overview.html:35` |
| D13 | Prose measure wider than the house 65–75ch | 2 at `90ch`, against `75ch` ×4 and `70ch` ×3 | `facility_detail.html:83`, `sampling_point_detail.html:78` |

**D13 note:** every `max-width: <n>ch` declaration in the entire repository is
inside `templates/drinking/`. There is no site-wide value to conform to, so the
module's own dominant value (75ch, and inside the 65–75ch band CLAUDE.md states)
is the one adopted.

---

## Measured, and deliberately left alone

A consistency pass that "fixes" these would create the drift it exists to
remove. Each was checked against the rest of the platform before being left.

| # | Thing | Why it stands |
|---|---|---|
| N1 | Title Case filter options — `All Analytes`, `All Types`, `All Statuses`, `All Point Types`, `All Sampling Points` | 18 of 20 `<option value="">` labels across the platform are Title Case. Drinking's 5 match the house; changing them alone would make drinking the outlier. |
| N2 | `...` in search placeholders | Matches `Search by parcel number or owner...` and `Zone name...` elsewhere. `&hellip;` is used for spinners, in 8 files site-wide. Two contexts, two conventions, both consistent. |
| N3 | `&mdash;` (10 files) vs a literal `—` (19 files) | Renders identically. Not visible to a reader; churning 29 files buys nothing. |
| N4 | Title Case back-links — `← Back to Sample Results` | 20+ instances site-wide, all Title Case naming a destination page. |
| N5 | Title Case `<th>` — `PS Code`, `Latest Sample`, `Water Type` | DESIGN.md's own stated exception, and `.data-table th` is uppercased in CSS. |
| N6 | `No sample results match these filters.` differs from `No facilities found matching "X" of that type.` | `results.html` filters on a date *range*; the "of that X" enumeration the other two use cannot express it. |
| N7 | *sampling place* in the onboarding builder's explanatory prose | Deliberate plain-English from `34c3cc1` (80-03), written after the review verdict "It's just a bunch of random letters and acronyms." The word teaches; it is not drift. Only the **navigation control** that carries it is a defect — see D9 and rule 6. |
| N8 | `sampling_points.html` uses `.page-description` three times, twice as a map caption | Changing the class is a visual change with no copy defect behind it. Both blocks are prose about the map and read correctly where they are. |

---

## Where the plan's starting numbers were wrong

The plan wrote its figures at planning time and told this task to re-measure.
It was right to. Four of its five starting points did not survive:

- **"`PS Code` in prose 14 times vs `PS code` 5."** Prose-only it is **3 vs 4**.
  The 14 counted seven `<th>` column headers, which the plan itself names as
  exempt, plus four occurrences inside `{% comment %}` blocks.
- **"`PWSID` … expanded on no user-facing screen."** Half right. `onboard.html:38`
  defines the concept in prose — "the identifier the regulator carries for a
  public water system" — and has since Phase 79. What is genuinely absent
  anywhere is the letters (D8).
- **"`ELAP` (3)"** with no expansion. ELAP appears **twice**, and its one prose
  use at `result_detail.html:138` **is already expanded**. It is not a defect; it
  is the precedent rule 5 copies.
- **"`eAR` (1)"** with no expansion. **Zero.** `overview.html:80` already writes
  "annual electronic report (eAR)" — Phase 100 closed it.
- **"Two `page-description` blocks that render empty or near-empty."** **None**
  render empty. All ten pages carry one. `sampling_points.html` carries three,
  two of which are map captions (N8).

`SDWIS` (10 raw occurrences), `GAMA` (7) and `DDW` (2) held up, though the raw
counts fold together three different things — a source citation, a file-format
name, and prose — which is why rules 5 and 7 treat them differently.
