<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# OpenH2O Design System

Inherits the VanderDev design token system. Dark mode only, OKLCH color ramps.

## What a finished page is (read this before any visual change)

A finished page is balanced and filled out logically, so that it looks right at
a 1,730-pixel viewport to a reader who knows nothing of the plan behind it. This
is the acceptance test for every visual change, and it comes before every rule
below. Three things follow from it:

1. **The unit of acceptance is the page, not the component.** A shared panel
   redesigned correctly on three pages was right on one page and wrong on two,
   because a card that sits well beside a table leaves a quadrant of dead space
   beside a short one. Every page a change touches is judged as a page.
2. **The width is 1,730 CSS pixels**, the maintainer's working window, measured
   from screenshots (an effective device pixel ratio of 2.2; a panel that is
   886 px in a capture renders at 882 px in a 1,730 viewport). It is not 2,560,
   the physical display, at which the account page shows a layout no one works
   in. If the window changes, re-measure it from a screenshot.
3. **The judge is not the author.** Before a page goes to staging, a reader who
   did not build it and knows nothing of the plan looks at every touched page at
   1,730 and answers *would you put this in front of a client?* A "no" (DO NOT
   SHIP) is a design task. Probes, measurements and tests stay as regression
   checks; none of them shows that a page looks right.

### A screen explains itself

A screen also has to say what its numbers mean. The test has two readers. A
reader who does not work in water can say what the screen is about and what the
biggest number on it means. A water professional (an engineer, a grower, a
ditch tender) can find the figure they came for without reading the page. Each
kind of surface has one job:

- **A data table:** the reader finds one row, reads one figure across it and
  compares it with its neighbours. The header row shows which columns belong
  together and which one they make, a derived column is visibly derived, and a
  column from a different framework sits apart from the measured ones.
- **A stat row or budget panel:** the reader reads the figure the page leads with
  and sees the two or three figures that make it.
- **A page head** (breadcrumb, title, description and actions): the reader
  confirms which screen this is, what its numbers are and where to act.
- **A filter bar:** the reader narrows a list to the rows they came for and sees
  what it is narrowed to.
- **A map:** the reader finds a record by where it is and opens it.
- **The sidebar:** the reader finds the section they need and knows which page
  they are on.
- **Body prose** (help pages, About and the explainers on data pages): the reader
  learns in a paragraph what a screen or figure is and how OpenH2O arrived at it.

### Kinds of page

Every list of records takes one of three layouts. Code comments call them
Bucket 1, 2 and 3.

- **Bucket 1, master-detail workspace.** For many records, each with a
  medium-sized story, where the reader compares and switches often: a searchable
  list on the left and the selected record's detail on the right, with a map at
  the top of the detail when the record has a location. Clicking a row swaps the
  detail in place and the list stays put; a heavy detail offers a link to its
  full page. Below about 720 px the layout becomes Bucket 3. Use areas, wells
  and water accounts.
- **Bucket 2, dense data table.** For many records that are data, with little
  to say about each one: the whole screen is one table, with filters across the
  top, sortable columns, a sticky header and totals at the foot. There is no
  detail pane; a row may link to a related record. The use ledger and
  allocations.
- **Bucket 3, overview then full detail page.** For few records, each with a lot
  to show: a wide map of all of them over full-width rows, and each record opens
  on its own full-width page. A record with no location of its own (a water
  right) has no overview map, and its page shows the places it relates to. Zones,
  recharge, water rights, surface diversions and monitoring stations.

## Colors

### Surfaces
The Deep Water elevation ladder — values match vadosehq.com's brand tokens
exactly, with inset/hover steps derived for app use. Authoritative values live
in `static/css/tokens.css`; this list mirrors them:
- Base: #090E14 (page ground)
- Nav: #0B121B (sidebar ground, one step below base)
- Tile: #111A24 (low-lift tiles, nav active)
- Card: #141E2A (panels and cards)
- Inset: #0E1620 (recessed: fields, wells for content)
- Elevated: #1A2633 (raised chips, hover-lit surfaces)
- Hover: #22303F (topmost interactive lift)

### Accent

OpenH2O is on the Vadose **Deep Water** colorway. Three accents, each with a
distinct job — authoritative values live in `static/css/tokens.css`:

- **Water Teal — the PRIMARY accent.** `--color-accent: #46B3C4` (hover
  `#5FC2D2`, muted `rgba(70,179,196,0.10)`, soft `rgba(70,179,196,0.18)`). This
  is the family's free/public-benefit line color and OpenH2O's identity: logo,
  page title, links, active states, and the everyday emphasis accent. When in
  doubt, the accent is teal.
- **California Gold — CTAs ONLY, used sparingly.** `--color-gold: #E0A446`
  (hover `#EAB25E`, muted `rgba(224,164,70,0.10)`). Reserved for "gold acts" —
  primary call-to-action buttons and the single figure a page produces. Do **not** use gold as a general-purpose emphasis or callout
  color; that is the mistake that makes a page look off-brand. (The pre-Deep-Water
  gold `#E4A317` that older rules hardcoded was migrated to `var(--color-gold)`
  color-mixes in 2026-08; if you see a raw gold hex in a diff, it is a regression.)
- **Pacific Blue — data affordances.** `--color-blue: #1B7FAF` (bright
  `#3DB4E0`). Parcels, map elements, and links that point out to water data.

**Emphasizing prose:** do not reach for a color at all. Body and intro text is
plain left-aligned prose; when a passage needs lifting, wrap it in the same
`.card-raised` panel the Help "short version" blocks use — no
colored left-stripe. A colored stripe or filled accent box around a lone
paragraph reads as a generic AI callout, not this design system.

### Text
- Primary: #E7EEF2 (body text, headings)
- Secondary: #8FA3AE (labels, descriptions, metadata)
- Tertiary: #7E93A4 (subtle text, placeholders — dimmest ink that still clears WCAG AA on the worst surface)

### Borders
- Default: rgba(255, 255, 255, 0.07) (hairline)
- Hover: rgba(255, 255, 255, 0.13)
- Interactive controls: rgba(125, 165, 205, 0.6) (a ≥3:1 perceivable boundary)

### Data Visualization
Three OKLCH tonal ramps (8 stops each, 100-800):
- Furnace Orange (hue 50): heat, usage, extraction
- Reservoir Blue (hue 200): water levels, supply, precipitation
- Forest Teal (hue 145): recharge, conservation, positive change

## Typography

- One typeface: Public Sans sitewide (system-like, government identity);
  numeric columns use `tabular-nums`, not a separate monospace face
- Body line length: 65-75ch max

## Elevation

- Pop shadow (small): 2px 2px 4px rgba(4,3,2,0.70), -2px -2px 4px rgba(42,32,24,0.50)
- Pop shadow (large): 6px 6px 12px rgba(4,3,2,0.80), -6px -6px 12px rgba(42,32,24,0.60)
- Inset shadow: inset 2px 2px 4px rgba(4,3,2,0.70), inset -2px -2px 4px rgba(42,32,24,0.50)

## Border Radius

The surface is square. Five tokens are the only place a corner is decided.
`static/css/tokens.css` is the authority; this section mirrors it.

| Token | Value | Used by |
|---|---|---|
| `--radius-sm` | 2px | buttons, inputs, chips, focus rings, swatches |
| `--radius-md` | 2px | cards, popups, map panels |
| `--radius-lg` | 2px | large containers, budget/result panels |
| `--radius-xl` | 2px | the largest surfaces |
| `--radius-pill` | 100px | status chips and switches only |

**The four non-pill tokens are deliberately the same value.** The scale is flat,
not a ladder. They keep separate names so a later pass can differentiate an
input from a modal by editing one line in `tokens.css` rather than re-pointing
100+ call sites. Do not "simplify" them into one token.

**Two exemptions, and a sweep must not touch either.**

1. **`border-radius: 50%` is a circle, not a radius.** Avatars, status dots,
   the data-freshness pips, the map legend's swatch dot. Squaring a circle is
   the blind-sweep failure that squaring every radius invites. Leave every `50%` alone.
2. **Pills stay pills.** A status chip and a switch read as a different kind of
   thing from a panel, and a squared pill reads as a different control. They
   read `--radius-pill`, not a literal.

**Never write a literal radius.** Every corner reads one of the five tokens.
Two deliberate `0` values remain (an input nested inside an already-bordered
wrapper, and MapLibre's scale bar); both are square by intent and carry a
comment saying so. `tests/test_radius_drift.py` fails the build on a new
hardcoded value.

## Spacing Scale

4px / 8px / 16px / 24px / 32px / 48px / 64px

## Components

- Cards: `.card-raised`: var(--color-card) background, 1px border, `--radius-lg`.
  Add `.card-inset` for a quieter, recessed variant (references, secondary aids).
- Form inputs: .form-input, .form-select, .form-textarea utility classes
- Tables: .table-scroll wrapper for horizontal overflow
- Toolbar: `.toolbar-row` for the filter bar above a table — bottom-aligns its
  controls with a 16px gap. `.row-end` is the other one: it right-aligns a row of
  action buttons with an 8px gap. Same flex row, opposite jobs — filters pack to
  the start and line up on their baselines, actions pack to the end.
- Layout: `.page-narrow` (max-width 640px), `.page-medium` (max-width 800px),
  `.page-wide` (max-width 1400px). All three centre with `margin-inline: auto`.
- Layout, full-bleed: the workspace pages (`/wells/`, `/accounting/accounts/`) are
  a different population. Their `<main>` runs at `max-width: none` and the content
  is a `.workspace-split` grid, so they take **no** page-width class at all —
  giving one to a workspace page would cap a layout designed uncapped.
- Responsive: tablet 1023px, mobile 767px breakpoints
- Empty states: SVG inline icons with secondary text
- Toasts: HTMX-driven notifications
- Breadcrumbs: "/" separated, gold active state

### House "concept" components

These are the shared visual vocabulary the data/accounting/help pages reuse so
the same idea always looks the same. All live in `static/css/app.css`.

- `.budget-panel` — a supply-vs-use summary: one gradient panel that reads as
  the balance equation (supplies − use = balance) with a supply breakdown foot.
  It is one summary view among many data surfaces, not the product's centerpiece.
  Used on the dashboard, period detail and account detail.
- `.statement-*`: the use area page's Water use card: the water year's figures
  lead (`.statement-lead`), one line for each thing that is off and only when it
  applies (`.statement-notes`), then the months in a `.data-table` whose foot is the
  year. A month that rounds to 0.00 is an empty cell. The month cells are rounded by
  largest remainder (`accounting.services.round_to_total`) so each column adds to
  the year exactly; the year is the exact sum rounded half up.
- `.step-card` / `.step-number` / `.step-eyebrow` — the ordered-sequence idiom
  (Help steps; the methodology editor uses `.methodology-step` + a numbered
  badge, with a muted dashed variant for disabled steps).
- `.card-grid` + `.card-link` — a responsive grid of linked cards (page footers);
  `.concept-panel-title` is the bold title line inside such a card.
- `.prose-link` — an underlined inline link inside prose (visibly a link).
- `.radio-option` / `.input-suffix` — on-brand radio tiles and an input with an
  attached unit (e.g. an efficiency percent + "%").

To lift a passage or a single figure, use a plain `.card-raised` (or a
`.budget-panel` row when the figure belongs beside the supplies, use and balance
equation). No page uses a left-accent card, a two-up comparison panel, a gold
figure card or a gold left-rule inset, so none of them is defined.

### The layout rules

Every fault a fresh reader named in the wording review and on the small-dataset instance
was measured live and fixed at its shared cause where one existed. The rules, each in
`static/css/app.css` under "The layout rules":

- **A form is a grid, not a column of bars.** `.form-grid` lays field groups in two tracks; a field
  whose value is a sentence or a name spans both (`.form-span-2`); a one-line form (a step with no
  options) is `.form-grid--row`. Form pages sit at `.page-medium` with `page-head--medium`; the 640 px
  measure is for a page of one or two fields. One-control cards two or three
  across, each ending at its content, were tried on the settings page and the wizard's
  two boundary cards; both read DO NOT SHIP on the cards' unequal heights, worse than the single
  column, so both keep the single column and the layout is not defined.
- **A record's fields across a wide card** sit on `.field-grid-auto` (as many 280 px tracks as
  fit), never two columns 700 px apart (the facility page).
- **A footer's figures wrap.** `.tfoot-figures` on a footer cell that holds several figures; a
  `nowrap` sentence in a `colspan` cell sets a floor under every column it spans (the ledger at
  1,024 was 830 px wide in a 722 px card for that reason alone).
- **The header of a table pins to the document, and a table wider than its card scrolls inside the
  card, never the page.** `.app-content` is not a scroll container (`overflow-x: clip; overflow-y:
  visible`); `static/js/table-scroll.js` marks each `.table-scroll` wrapper `data-overflow`: a
  fitting wrapper is `overflow-x: visible`, so `.data-table thead th { position: sticky }` pins to
  the document scroll; an overflowing one scrolls and its first column
  stays put. The dashboard's two grouped tables do this below 1,330 and 1,435 px; the canal tables fit at 1,440 and scroll below.
- **A reference row is secondary** (`tr.receipt-aside` on the receipt's meter row); **a block's title
  carries the head's weight** above its fields (the worksheet); **the primary action sits after the
  statement that qualifies it** (the report's Download beside the no-filing sentence, not above it);
  **a detail map's one mark is sized for its band**, not the overview's zoom ramp.
- **A sidebar label wraps** rather than clipping at the rail (`.sidebar-link-text`); **a code string
  wraps** (`.text-mono { overflow-wrap: anywhere }`); **the health cards' badges are the pill size**
  and every badge colour is a token (`--color-muted` joined `tokens.css`; the last hard-coded badge
  colour went).
- **A class a template names is defined** (`.font-semibold`, `.text-primary`, `.row-clickable`), and a hygiene test keeps the list from growing back.

What was tried and withdrawn, so it is not tried again: **a short page's void has no layout fix.**
With the footer pinned to the frame (the shell), a four-row list, the home page on a
small instance and the signed-out front page read DO NOT SHIP for "the dead void between the cards
and the footer"; with the footer riding the content, the same pages read DO NOT SHIP for "the footer
floating mid-page" (one read SHIP 4 with that as its worst fault). The same reader faulted a panel
beside a taller card both stretched ("mostly an empty dark box") and at its content's height ("a
large dead gap under the stats panel"). Two readers contradicting each other on one element is the
stop rule: the shell and the matched row stay, and the one shape that fills the gap is the
field page's card-beside-map grid.

### Casing convention

UI labels, eyebrows, section headers, and disclosure triggers are **sentence
case**, not uppercase — "Account balance", not "ACCOUNT BALANCE".

**This governs the text you write, not how a component chooses to set it.** Two
components uppercase their own label in CSS — `.data-table th` and
`.content-section-label`, the teal tracked-out eyebrow above a section — and the
markup underneath still reads `Station freshness`. Write sentence case and let
the component decide; do not hand-type `STATION FRESHNESS`, and do not "fix" the
`text-transform` to match the rule. Cartographic map and legend labels follow
map convention and are exempt outright.

Two further exceptions, both measured across the whole template tree rather than
chosen: a **breadcrumb crumb** and a **`← Back to …` link** name a destination
page in Title Case ("Back to Sample Results"), and a **filter `<select>`'s
default option** is Title Case ("All Statuses"). Those are what 19 of 19
Water Data breadcrumbs, 20-plus back-links and 18 of 20 default options already
do.

### Tables that explain their numbers

The dashboard's tables were the worked example (`templates/accounting/partials/_dashboard_content.html`,
`.data-table--grouped` in `app.css`). Four consistency passes never reached these faults because none is a
design-system violation; the test is *can a reader say from the layout what the numbers mean*. Every rule
below was judged on the whole page, not a table in isolation, and they apply to every other table.

1. **Columns run in the order of the equation the page states.** Supplies (Surface, Groundwater, Rain,
   Total) → Consumptive use → Balance, then the groundwater budget. A reader must be able to say why the
   columns are in that order.
2. **Where columns sum, a group header names the sum** and its underline brackets exactly its own columns
   (`.th-group-label`). Structure, not a caption sentence: the "How this summary works" inset that used to
   say it in prose is gone.
3. **One vertical rule where the kind of number changes** (`.col-sep`), and only there. The groundwater
   budget is paper from a different framework; the rule keeps a reader from reading across it as one row of
   like quantities. No rule before Balance; the Supplies bracket already marks where measured water ends.
4. **A unit is stated once per single-unit table**, in the card's subtitle ("All figures in acre-feet
   (AF)."), never on each column. A table mixing units keeps the unit on each column. Short leaf headers
   are also what makes a nine-column table fit a 1440-pixel window.
5. **A footer only where rows are addable**, and its label says what makes them addable ("All 11 active
   accounts": one quantity, one period, every active account). The Zones table has none, because a parcel
   can lie in more than one zone, and its subtitle says so. A footer sits on a tinted band with the header's
   accent rule and a header-styled label (`.tfoot-total`); bold alone did not call it out.
6. **One name per thing, matching the panel above:** Balance, not Net; Rain, not Precip; Total under the
   Supplies group. The word *groundwater* stays beside the budget columns, in the group header.
7. **Two kinds of row are said once**, with a divider row (`tr.row-group`) left-aligned over the names,
   not a note repeated on five rows. The divider names the condition (a groundwater budget exists for the
   period), never the deployment's zone types.
8. **The lead panel names the thing, not the operation** ("District water balance"), leads with its result
   at the only large size (`.budget-seg--result`), captions each figure with where the platform got it,
   breaks a total down "by source" beside it, and names its population in a foot line when the total is not
   the whole basin.
9. **Two-word headers that wrap stack the second word centred under the first** (`.th-stack`), and the same
   word has the same shape on every table. **A header cell that spans both rows is bottom-aligned**, so
   every leaf-level word sits on one line; a spanning cell otherwise centres over the two-row height and
   floats half a line above its neighbours.
10. *Retired 2026-10-17.*

Rules 11 to 18 come from reading the pages on staging at 1,730. Each is pinned by a guard so it is not
re-learned, and each holds on every page that copies these shapes:

11. **A lead panel never holds one lone figure.** A single segment in the panel's five-track row read as
    "a giant blank box to the right of the recharged value". Where the page's figure is a sum with nothing
    to set it against, the row carries its peers: the figure, what it is made of (the same rows the table
    below prints), and the period before it (a peer, never added). `templates/recharge/partials/_detail_pane.html`;
    guard `tests/test_recharge_site_page.py`.
12. **A breakdown whose labels are names goes UNDER the equation row**, full width, ruled off
    (`.budget-breakdown-group--under`). Inside a segment a point of diversion's id and name ran across the
    divider into the next cell, and shrunk to the cell it wrapped seven lines deep. Word labels ("Allocation",
    "Carried forward") stay in the segment. `templates/surface/partials/_water_right_detail_pane.html`.
13. **Two grouped tables side by side keep step by structure.** The same rows per water year on both
    (group header, the rows, a closing row), their head lines in one subgrid row (`.history-grid`), and the
    closing label on one line. A closing row on a LEVELS table prints the year's net change, never a sum of
    closes; the Close cell stays empty. `templates/wells/partials/_detail_pane.html`; guard
    `tests/test_wells_measurement_history.py::test_each_water_year_of_the_depth_digest_closes_on_its_net_change`.
14. **A column header is the thing, in a word a reader would use.** "Delta" asked whether it meant
    difference; the meter's column is **Pumped** (the read less the previous read, said once in the head
    line); the level column is **Change**. Never a Greek letter, an abbreviation, or an engine's own word.
15. **A map on a form page is a landscape band above the form**, the record pages' 380px, the form's cards
    two across under it. A map beside a form at the form's height is portrait and mostly out of view.
    `templates/infrastructure/add.html`; guard `tests/test_views.py::test_add_page_map_is_a_landscape_band_above_the_form`.
16. **Water-year group headers stand out**: primary text at 700 on a fuller band, ruled above and below
    (`tr.row-group td`, platform-wide). The secondary-text version blended into the rows.
17. **A card's subtitle is a noun phrase, not a sentence with a story in it.** "What came through the meter,
    and what the water table did beneath it" became "Meter reads and depth to water, by water year."
    18. **A grouped table's bracket header sits centred over its bracket.** Left alignment was tried and
    read worse: the bracket is the group's extent and the word balances it from the middle. `.data-table--grouped
    th.th-group-label`, platform-wide; guard
    `tests/test_template_hygiene.py::TestGroupedTableBracketHeaderIsCentred`.
19. **A map's marks are named on the map and keyed above it; the map follows its list.** Every overview
    map sits under a card head that counts what the list counts with the key on the same line
    (`partials/_map_card_head.html`, `.map-card-head`), carries an always-on label per mark that
    YIELDS when it collides (never `text-allow-overlap`: seven names painted over one another read as
    none), and filters to the list's pks on every swap (`OH2O.followResults`, which keeps each layer's
    own geometry filter). A typed coordinate is never rewritten under the cursor. Ruled 2026-09-13
    14:10 (A, the card) and 18:24 (the round on staging); guards `tests/test_overview_map_card.py`.

## Copy rules

House rules for the words on screen. Written 2026-07-30 during the drinking
module's copy pass; each one exists because a defect was **counted** on the
screens.
A rule with no measured instance behind it does not belong here.

They are stated for the platform, not for one module. The drinking module is
where they were first enforced, and `tests/test_drinking_readability.py` pins
the mechanical ones there.

### 1. Casing

The section above. It governs labels *we* author. It does not govern a name
somebody else owns — see rule 2.

### 2. A published identifier keeps the publisher's own casing

Write a state or federal identifier exactly as the body that publishes it writes
it, even where that disagrees with sentence case. It is a proper name, not a
label of ours.

The authority is the source file, not preference. California's own SDWIS4 export
(`data/merced/drinking/merced_lab_results_3yr.tab.gz`) heads its column
**`PS Code`**, so that is the spelling — in prose, in a field label and in a
placeholder alike. Same for `PWSID`, `ELAP`, `MCL`.

`ID` is capitalised in prose as well as in labels. The platform writes
"Facility ID" seven times; four prose sentences wrote "id" and were the
outliers, not the rule.

### 3. American spelling in anything a reader sees

A California program's proper name spelled the British way is the one thing on
these screens that must look authoritative and does not. `GAMA programme`
once shipped to staging and was caught by eye rather than by a gate.

This binds **rendered text only** — page copy, labels, `help_text`, and the
strings in `drinking/provenance.py` and `drinking/glossary.py`. Template and
code comments are not copy and are left alone.

### 4. One name per thing, module-wide

If two screens in the same flow name one object two ways, one of them is wrong.
Plain-English *teaching* prose may still use a friendlier word where a phase
deliberately chose one — but a **control that navigates to a named page carries
that page's name**, so a button reading "View all sampling places" may not land
on a page titled "Sampling points".

### 5. Expand an acronym at its first appearance in prose on each page

Once per page, in prose, at first use: "the state's Groundwater Ambient
Monitoring and Assessment Program (GAMA)". Later uses on the same page are the
acronym alone.

**Not** in a `{% source_label %}` citation, **not** in a field label, and
**not** in a `<th>`. Those three are short by design — `drinking/provenance.py`
says in its own docstring that a publisher label "renders inline beside a
section header, not as body copy" — and a six-word expansion in a two-column
field grid breaks the grid the reader is scanning.

Chosen over a glossary-link layer because the module already does this and it
already survived review: `result_detail.html` expands ELAP in prose at its only
prose use, and that page passed review. Copying an accepted
precedent beats building a second explanation mechanism.

A name that is a *file layout* rather than a system is not expandable —
`SDWIS.CSV` is the literal name of the state's export format and stays as it is.

### 6. Prose measure

Body prose caps at **75ch**, inside the 65–75ch band CLAUDE.md states. Every
`max-width: <n>ch` in the repository is currently in the drinking templates;
75ch is that set's own dominant value.

### 7. No emphatic filler

"…arrives with no coordinates **at all**" says nothing "…arrives with no
coordinates" does not. Cut the intensifier and keep the fact. Same family as the
sentence once deleted from the map caption for restating the label beneath it.

### 8. An empty state states the fact and stops

It may say what the thing is and what to do next. It may **not** assert a cause
it has not counted: a draft once explained an unlocated facility by its type,
and measured, 10 of the 40 unlocated were neither of the types named. Count how
many rows a cause holds for before writing it.

### 9. A message an operator reads may not name a database column

An error or status string that reaches a screen is copy, and it is bound by every
rule above. Field names, model attributes and payload keys are developer
vocabulary: they belong in a log line, an exception attribute, or a docstring.

The measured instance is `drinking/envirofacts_mapping.py`'s
`UnmappableFacility`, which told an operator a facility *"has no
**state_facility_id**"* on the onboarding review screen — two lines above that
same screen's own English for the same fact, *"missing the state-assigned ID that
sample codes are built from"*. The page stated one thing twice, once in English
and once in Python.

Two properties made it durable, and both are worth recognising elsewhere:

* **It was not in a template.** The whole copy pass swept 22 templates
  and `drinking/glossary.py` and never saw it, because the string is raised in a
  mapping module. Rule 3's list of code files that hold copy is a list to keep
  extending, not a boundary.
* **A test was holding it in place.** `tests/test_drinking_onboard.py` asserted
  the literal `state_facility_id` appeared in the response body. The assertion
  was right that the reason must be on screen and wrong about what the reason
  should say, so the suite went green on the defect. Both assertions now require
  the readable wording **and** forbid the field name.

Splitting the two audiences is the fix: `str(exc)` is the operator's sentence,
`UnmappableFacility.field` and the `logger.info` on the skip path carry the key.
A message written to serve both ends up serving the one who is not reading it.

### 10. Multi-line template comments use `{% comment %}`

Not `<!-- -->`, which ships to the browser, and not `{# #}`, which closes at end
of line and renders its second line onward as page text — the defect
`test_no_template_syntax_leaks_into_the_page` was written to catch.

### 11. Explain the software and the data conventions, never the water

**The rule, in one sentence: explain the software and the data conventions;
never explain the water.**

**Who is reading.** OpenH2O is for anyone who keeps water records, anywhere in the United States: engineers and managers at water agencies and districts, growers, ditch tenders and drinking-water system operators.
Every one of these readers knows water, so OpenH2O explains its own software and data and never the water. Many of them have spent thirty years on what a well is, what a
canal does or what evapotranspiration means. A sentence telling that reader what a well is does not merely waste a line; it
tells them the product does not know who they are.

**The axis is ownership, not difficulty.** This rule is not "no jargon" and not
"keep it short" — both of those readings are what produced the defect it
corrects. A hard software word gets explained. An easy water word does not. The
only question is *whose domain the word belongs to*.

**Three things are explainable, and stay explainable:**

1. **This platform's own coined concepts** — an Allocation Ceiling, a Use Area,
   a Water Account, a Zone, a Ledger Entry, a Closing Balance, a Recovery
   Horizon, a Methodology / Calculation Plan, a Health Check, a Monitoring
   Station, an ET-Demand Allocation. The operator cannot possibly know these:
   they are software, invented here, and the platform owes a definition.
2. **Agency and program names** — GEARS, CalWATRS, SGMA, GSA, GSP, CDEC, CIMIS,
   USGS, OpenET, EPA, DDW. These are filing conventions, not hydrology.
3. **Codes and abbreviations inside data the platform did not author** — EPA's
   `STBY`, `DST`, `RAW`, `GAC`, `IX`, `NO3`, and DDW's analyte codes. A federal
   record is shown verbatim, so the reader needs the key to it.

**The operational form of the rule for codes: expand the code, never describe
the thing.** `GAC` → "granular activated carbon" is the platform doing its job.
"— a filter that removes organic chemicals" is the platform explaining
treatment to the person who runs the treatment.

**No exception for a clause about the filing.** This was decided on 2026-08-06,
against a measured list of every such clause. The strongest case was `LCR`,
whose clause — "Lead and Copper Rule — samples taken
at customer taps to check for lead" — describes what the regulation makes a
district collect rather than describing water, and so had a real claim to stay.
The ruling is **decode only, with no exceptions**: one rule anyone can follow
and a test can hold beats a per-entry judgment a later contributor re-derives
differently. Do not reopen this as though it were an oversight.

**The worked example, because it is the clearest statement of the rule that
exists.** `FACILITY_TYPE_CHOICES` in `drinking/models.py` already carries EPA's
own label for all 22 codes, and the facility panel already renders "Well" from
it. Stacked beneath that heading, a second line read:

> **Well**
> A drilled well. Water comes up out of the ground here.

The first line is the data convention and is correct. The second is the defect —
and the fix is a deletion, not a rewrite, because the professional-reader
version already ships two lines above it.

**A test may never mandate a domain description.** The failure this rule ends
was not 41 bad strings; it was that three tests asserted the strings had to be
there, so every correction made by hand was reverted by the suite on the next
run. The guard for this rule is `tests/test_domain_vocabulary.py`, and the term
list it scans against is `core/domain_vocabulary.py`.

**Its mirror image is `tests/test_operator_vocabulary.py`, and the two must not
be confused.** That gate says *you must define an infrastructure term before you
use it*; this one says *you must not define a water term at all*. Both are true
at once, and holding only one of them is how the platform ended up lecturing
hydrologists about hydrology while assuming they knew what DNS was.

**The help-page exception.** Two help pages, How water balances work and Methods
behind the numbers, carry four sentences that explain the water: the acre-foot
sentence, "Plants give off water as they grow, and satellites can pick that up.",
"Not all the canal water reaches the crop: some soaks past the roots and some runs
off the end of the field.", and "A pump has to lift more water than the crop ends
up using, because some water soaks past the roots." They stay because those two
pages are written for a reader who does not work in water. Every other
page stays under the rule, and no other sentence of that kind may be added
anywhere without a ruling.

### 12. One vocabulary of water

**The rule, in one sentence: name each quantity once, and the same way on
every screen.**

**What was counted.** An audit traced all 106 figures the platform renders and
recomputed every one of them a second way, in SQL that cannot call the
platform's own code. Not one figure computed a wrong number. Every defect it
could confirm was a correct number under a label naming something else, or two
screens describing the same rows differently: a diversion table headed
"Consumptive Use" over water spread into a recharge basin; a use
ledger footer and a dashboard stating the same year with opposite signs, because
one file called a canal delivery a debit and the other a supply; a
budget that subtracted gross crop water use, a quantity that falls in a drought; and a parcel badge reading "Surplus" to an audience for whom surplus
is good news. Three different quantities were all called "consumptive
use". The product had two live definitions of "supply" and had never chosen.
This rule chooses, and the table below is where the choice is written down.

**The operating form, for every test that touches a figure.** Three review
questions, from the 2026-09-06 write-up on how those defects survived fifteen
months of green builds. (1) A numeric test asserts a value, never a direction:
`> 0`, `!= None` and `status == 200` all survive the defect they were written
to prevent. (2) A test may not re-derive the formula it tests: compute the
expected number by hand from the fixture, once, and paste the literal;
`assert remaining == budget - used` is true whatever `used` contains. (3) Any
figure that adds rows must say what makes them addable, and if the honest answer
is "they are all numbers", the total is wrong and the fix is to stop printing it.

**Rule 11 and this rule hold at once.** Rule 11 says never explain the water:
the reader knows what evapotranspiration is. This rule says name each quantity
once: the reader cannot know which of three quantities this product means by
"consumptive use" unless every screen means the same one. A sentence saying
"this column counts metered and calculated pumping" is a data convention and is
allowed under both.

**The guard is `tests/test_water_vocabulary.py`**, which reads the table below
through `core/water_vocabulary.py` and holds every gated phrase at a strict zero
inside its scope. The gate finds the table by the two HTML-comment markers, not
by this heading. The "Never called" column has a machine-readable shape: one or
more entries of the form `` `phrase` in `templates/<dir>/` `` or
`` `phrase` anywhere ``, or the words `no gated phrase` where the misuse is a
concept rather than a string. Phrases match case-sensitively, exactly as written,
and word-bounded, so `Surplus` (a badge) is a hit and `text-surplus` (a CSS
token) is not. "Computed as" names the function or field that already produces
the number; nothing in this table asks for a new calculation.

<!-- vocabulary: begin -->
| Term | Means | Computed as | Never called |
|---|---|---|---|
| **Crop ET** | The crop's evapotranspiration for one field and month, OpenET's satellite estimate. Gross, before effective precipitation. The headline use figure on the dashboard, the account page, the field page, the help pages and the glossary. The engineer's term replaces "crop water use" and the dashboard's "consumptive use", because DWR's handbook ties consumptive use to ETAW and the screen meant gross ET. | `consumptive_use_gross` = sum of `CalculationRun.gross_et_af` | `crop water use` in `templates/help/`, `crop water use` in `templates/accounting/`, `crop water use` in `templates/parcels/`, `Crop water use` in `templates/help/`, `Crop water use` in `templates/accounting/`, `Crop water use` in `templates/parcels/`, `Consumptive use` in `templates/help/`, `Consumptive use` in `templates/accounting/`, `Consumptive use` in `templates/parcels/`, `consumptive use` in `templates/help/`, `consumptive use` in `templates/accounting/`, `consumptive use` in `templates/parcels/` |
| **ETAW** | Evapotranspiration of applied water: crop ET minus effective precipitation, for one field and month. OpenH2O assigns it first to surface water, up to the delivery times the field's irrigation efficiency, and the rest to groundwater. Written "ETAW" on every screen; the glossary expands it. | `consumptive_use_net` = sum of `CalculationRun.net_consumptive_use_af` | `net consumptive use` in `templates/help/`, `net consumptive use` in `templates/accounting/`, `net consumptive use` in `templates/parcels/`, `Net consumptive use` in `templates/help/`, `Net consumptive use` in `templates/accounting/`, `Net consumptive use` in `templates/parcels/` |
| **Supplies** | Water that reached the field in the period: surface water delivered, groundwater extraction, effective precipitation. Never a credit, an allocation, or paper of any kind. Every screen adds the same groundwater figure. The dashboard and account pages list the pumped water the crop did not consume under Uses as Pumped water not consumed. The field's mass balance (`parcel_mass_balance()`, which no page prints) counts it, with the canal water the crop did not use, under Uses as Applied water not consumed. A satellite `et_estimate` row stands in for a month without a `calculated` or `meter_reading` row only on a field with a well. | dashboard and account pages: `consumptive_use_balance()`, where `supplies.groundwater` = `charged_groundwater(billable_ledger(qs))` (extraction) and uses = `consumptive_use_gross` + `water_not_consumed`; the field page lists them by month and does not add them (`parcel_water_use_months()`), and `parcel_mass_balance()["inputs"]` = `surface` + `precip` + `gw_recovered`, where `gw_recovered` = `_balance_dict(billable)["usage"]` (extraction) | no gated phrase |
| **Groundwater use** | What the groundwater budget is spent by, and the groundwater figure every Supplies column adds: groundwater extraction, never ETAW met by groundwater. A negative row counts when it is typed groundwater, is a `calculated` row, is a `meter_reading` row without a water type, or is an `et_estimate` row on a field with a well. A `calculated` row charges the extracted figure its run stamped, or its recorded amount when the run stamped none; every other counted row charges as recorded. A hand entry or upload without a water type does not count. Never "consumptive use", and never "pumped" when the number also holds canal water. | `charged_groundwater(billable_ledger(qs))`, read as `_balance_dict(...)["usage"]` and as `consumptive_use_balance()["groundwater_charged"]`; `consumptive_use_balance()["supplies"]["groundwater"]`; the rows are those `_groundwater_rows()` selects | no gated phrase |
| **Allocation** | Paper. A zone's ceiling for one water type in one period; an account's pro-rated share of it. A groundwater allocation and a surface allocation are managed by different agencies under different law and are never added. Never a supply. | `AllocationPlan.allocation_acre_feet`, filtered by `water_type` | no gated phrase |
| **Remaining** | Allocation, plus any carry-over, minus the use of the same water type: a groundwater allocation minus groundwater extraction; a surface allocation minus water delivered. Never "allocation minus consumptive use", and never allocation minus ETAW met by groundwater. | groundwater: `zone_groundwater_budget()["remaining"]` = `available` minus `zone_consumptive_balance(...)["groundwater_charged"]`, and the account row's `allocation - cu["groundwater_charged"]` in `accounting/views/common.py`; surface: the "allocation less delivered" branch in `geography/views.py` | `Allocation minus estimated consumptive use` anywhere; `Allocation minus usage` anywhere |
| **Credit** | Paper or banked water on a field's ledger: an allocation entry, a managed recharge entry, or, under the credited setting for surface water in excess of ETAW, the landowner's credited share of that water (the month's amount less the share left in the basin). Stored positive. A field with no well has its share go to the zone's shared account instead, because it has no well to pump it back; that account is not a ledger entry but the zone's pool row, and a no-well field whose zone has no such account is credited nothing. Never a supply, and never part of the field's water balance, which reads the same under every setting. | `source_type in ("allocation", "recharge")`, `amount_acre_feet > 0` (the `parcelledger_supply_rows_positive` constraint); the credited share is the `recharge` row `over_delivery_credit_words()` describes, amount `CalculationRun.over_delivery_credited_af`; the zone's shared account is an `AllocationCarryover` row from `deposit_to_basin_pool()` with origin `INCIDENTAL_RECHARGE_POOL` | no gated phrase |
| **Delivered** | Surface water the ledger records as reaching the field in the month, from the district's own record: a meter at the gate, or the ditch tender's estimate. Where the district recorded only the canal total, the field's figure was divided up from the canal total by the shares entered on the point of diversion, or by acreage where none is entered, and its ledger row says so. Stored negative by the ledger's convention (water leaving its source). Never "debits", and never "usage" in a footer that also holds credits. Never the figure the calculation subtracts: that is the delivery times the field's irrigation efficiency. On a point of diversion's page, a point that serves no field shows what is left after canal losses as Delivered to its recharge site, or Delivered to no field. That figure is `CanalMonthLoss.unserved_af`: it is not a ledger entry, is on no field and is credited to no one. | `surface_diversion` rows, magnitude; on the run, `CalculationRun.surface_delivered_af` | `debits` in `templates/accounting/` |
| **Effective precipitation** | The month's rainfall for a field that OpenH2O counts against crop ET, estimated from gridMET rainfall by the method set on Methodology Settings (USDA-SCS unless changed). The dashboard's and the balances' short label for it as a supply is "Rain". | `CalculationRun.effective_precip_af`, from `accounting/steps.py::subtract_effective_precip` | `rain the crop could use` in `templates/help/`, `rain the crop could use` in `templates/accounting/`, `rain the crop could use` in `templates/parcels/`, `rain the crop could use` in `templates/surface/`, `rain the crop could use` in `templates/geography/`, `rain the crop could use` in `templates/reporting/` |
| **ETAW met by surface water** | The part of a field's ETAW that OpenH2O assigns to surface water: the month's delivery times the field's irrigation efficiency (its irrigation method's assigned efficiency, else the deployment's default on Delivery Settings, 75% unless changed), up to the month's ETAW. Any part of delivery times efficiency above ETAW is surface water in excess of ETAW. The field's mass balance (`parcel_mass_balance()`) counts the rest of the delivery and surface water in excess of ETAW together under Uses, as part of Applied water not consumed. | `CalculationRun.surface_water_af` = `surface_delivered_af` x `surface_efficiency` (`accounting/steps.py::subtract_surface_water`), of which the part up to `net_consumptive_use_af` meets ETAW | `canal water the crop could use` in `templates/help/`, `canal water the crop could use` in `templates/accounting/`, `canal water the crop could use` in `templates/parcels/`, `canal water the crop could use` in `templates/surface/`, `canal water the crop could use` in `templates/geography/`, `canal water the crop could use` in `templates/reporting/`, `Canal water the crop could use` in `templates/help/`, `Canal water the crop could use` in `templates/accounting/`, `Canal water the crop could use` in `templates/parcels/`, `Canal water the crop could use` in `templates/surface/`, `Canal water the crop could use` in `templates/geography/`, `Canal water the crop could use` in `templates/reporting/` |
| **ETAW met by groundwater** | The part of a field's ETAW that surface water does not meet, on a field with a well and no meter reading. The engine's estimate, not a reading. It is the `calculated` ledger row's magnitude. Never "pumped" or "pumping" (those mean groundwater extraction), never "measured", never "groundwater consumed" (no engineer uses it). | `CalculationRun.final_af`; the `calculated` row `run_calculations.py` writes with `PUMPING_ESTIMATE_WORDS` (or `NO_PUMPING_DERIVED_WORDS` at zero) | `Groundwater consumed` in `templates/help/`, `Groundwater consumed` in `templates/accounting/`, `Groundwater consumed` in `templates/parcels/`, `Groundwater consumed` in `templates/surface/`, `Groundwater consumed` in `templates/geography/`, `Groundwater consumed` in `templates/reporting/`, `groundwater consumed` in `templates/help/`, `groundwater consumed` in `templates/accounting/`, `groundwater consumed` in `templates/parcels/`, `groundwater consumed` in `templates/surface/`, `groundwater consumed` in `templates/geography/`, `groundwater consumed` in `templates/reporting/`, `well water the crop used` in `templates/help/`, `well water the crop used` in `templates/accounting/`, `well water the crop used` in `templates/parcels/`, `well water the crop used` in `templates/surface/`, `well water the crop used` in `templates/geography/`, `well water the crop used` in `templates/reporting/`, `billable groundwater` in `templates/help/`, `billable groundwater` in `templates/accounting/`, `billable groundwater` in `templates/parcels/`, `billable groundwater` in `templates/surface/`, `billable groundwater` in `templates/geography/`, `billable groundwater` in `templates/reporting/`, `Billable groundwater` in `templates/help/`, `Billable groundwater` in `templates/accounting/`, `Billable groundwater` in `templates/parcels/`, `Billable groundwater` in `templates/surface/`, `Billable groundwater` in `templates/geography/`, `Billable groundwater` in `templates/reporting/` |
| **Groundwater extraction** | What the well pumped: SGMA's term. On a metered field the meter reading. On a field with a well and no meter reading, ETAW met by groundwater divided by the field's irrigation efficiency (its irrigation method's, else the default on Delivery Settings, 75% unless changed; the same figure its surface water is multiplied by), stamped on the run so a later change to the setting moves no month already run, and called groundwater extraction (estimated) where it is shown. This is the figure the groundwater allocation is charged with, and the groundwater figure every Supplies column adds. Extraction minus ETAW met by groundwater is Pumped water not consumed on the dashboard and account pages and part of Applied water not consumed on the field's water balance. On a metered field the dashboard and account pages take it as the reading less the part of ETAW that surface water does not meet, never below 0, and the field's water balance does not count it. | `CalculationRun.gw_extracted_af`, from `run_calculations._groundwater_extraction()` = `final_af` / `parcels.services.field_efficiency()` at compute time, stamped as `groundwater_application_efficiency` with its source; null on a metered or no-well run; a metered field's `meter_reading` row is the figure | `Groundwater extracted` in `templates/help/`, `Groundwater extracted` in `templates/accounting/`, `Groundwater extracted` in `templates/parcels/`, `Groundwater extracted` in `templates/surface/`, `Groundwater extracted` in `templates/geography/`, `Groundwater extracted` in `templates/reporting/`, `groundwater extracted` in `templates/help/`, `groundwater extracted` in `templates/accounting/`, `groundwater extracted` in `templates/parcels/`, `groundwater extracted` in `templates/surface/`, `groundwater extracted` in `templates/geography/`, `groundwater extracted` in `templates/reporting/`, `share of pumped` in `templates/help/`, `share of pumped` in `templates/accounting/`, `share of pumped` in `templates/parcels/`, `share of pumped` in `templates/surface/`, `share of pumped` in `templates/geography/`, `share of pumped` in `templates/reporting/`, `Share of pumped` in `templates/help/`, `Share of pumped` in `templates/accounting/`, `Share of pumped` in `templates/parcels/`, `Share of pumped` in `templates/surface/`, `Share of pumped` in `templates/geography/`, `Share of pumped` in `templates/reporting/` |
| **Surface water in excess of ETAW** | The part of a month's delivery times the field's irrigation efficiency that exceeds the field's ETAW. Effective precipitation that on its own exceeded crop ET is not in it; the calculation keeps that apart. Recorded on every run. What else happens to it is a Delivery Settings choice: credited to no one (the default); credited to the landowner less a share left in the basin (10% unless changed; a field with no well has its share go to the zone's shared account); or shown on the field's page as its own line, not a credit and not charged. Under every choice, the field's mass balance (`parcel_mass_balance()`) counts it under Uses, as part of Applied water not consumed. Every run records the choice it ran under. | `CalculationRun.over_delivery_af` (the floor step's `incidental_recharge_af`, `accounting/steps.py::clamp_floor`); the choice stamped as `CalculationRun.over_delivery_treatment`; the share `over_delivery_leave_behind`; what was credited `over_delivery_credited_af` and `over_delivery_credit_pooled`; the field page's own line `parcel_over_delivery_shown()` | `Canal water beyond` in `templates/help/`, `Canal water beyond` in `templates/accounting/`, `Canal water beyond` in `templates/parcels/`, `Canal water beyond` in `templates/surface/`, `Canal water beyond` in `templates/geography/`, `Canal water beyond` in `templates/reporting/`, `canal water beyond` in `templates/help/`, `canal water beyond` in `templates/accounting/`, `canal water beyond` in `templates/parcels/`, `canal water beyond` in `templates/surface/`, `canal water beyond` in `templates/geography/`, `canal water beyond` in `templates/reporting/`, `beyond crop use` in `templates/help/`, `beyond crop use` in `templates/accounting/`, `beyond crop use` in `templates/parcels/`, `beyond crop use` in `templates/surface/`, `beyond crop use` in `templates/geography/`, `beyond crop use` in `templates/reporting/`, `beyond what the crop could use` in `templates/help/`, `beyond what the crop could use` in `templates/accounting/`, `beyond what the crop could use` in `templates/parcels/`, `beyond what the crop could use` in `templates/surface/`, `beyond what the crop could use` in `templates/geography/`, `beyond what the crop could use` in `templates/reporting/` |
| **Residual** | The field's mass balance leftover: supplies minus uses (crop ET, applied water not consumed, managed recharge, storage change). Positive or negative. Since 2026-10-31 no page prints it: the use area page states the field's water use instead (its Water use card), and the closure checks read `parcel_mass_balance()`. The words below are kept for any page that prints it again. Badge words: Estimated / Residual / Deficit, and no word on a metered field (the three cases of the field page's badge, 2026-09-28; the earlier trio was Balanced / Residual / Deficit, and Balanced retired because on a field with a well and no meter the balance closes on the engine's own remainder, so the badge must say what closed it, not that the records agree). Estimated, grey, where the balance closes on the engine's estimate; Residual for a positive leftover and Deficit for a negative one on a field with no meter; no word on a metered field, where the figure is a difference between records and there is nothing to name it but the number. Never "Surplus", never "Balanced". | `parcel_mass_balance()["residual_af"]`; the band from `residual_band_status()` (`closes` within 0.01 AF, `realistic` within a quarter of crop ET, else `large`); whether the groundwater row is the engine's estimate from `parcel_mass_balance()["gw_is_estimated"]` | `Surplus` in `templates/parcels/`; `Balanced` in `templates/parcels/` |
| **Diverted / Returned to stream / Retained** | A diversion record's volume; the part returned to the stream; the difference. Retained water is delivered (direct use) or taken to storage (recharge) according to the record's `diversion_type`, and only delivered water can be consumed. The method keeps its name because 173 records and the CalWATRS generator read it; the column does not. | `volume_acre_feet`; `returned_af`; `consumed_acre_feet()` | `Consumptive Use` in `templates/surface/` |
| **Water use recorded, no supply reported** | The part of a field's ETAW in the period that no surface water on record meets, on a field with no well. The platform's stored unmet demand (`residual_disposition = "unmet_demand"`). It states what the rows show and stops: it is never a finding about the grower, and it is never invented pumping (the help pages already say so). Zero renders nothing. | sum of `CalculationRun.unmet_demand_af` over the runs `runs_in_period()` selects for the parcel and period, where `residual_disposition == "unmet_demand"` | `unauthorized` in `templates/parcels/`, `unauthorized` in `templates/accounting/`, `unauthorized` in `templates/geography/`, `Unauthorized` in `templates/parcels/`, `Unauthorized` in `templates/accounting/`, `Unauthorized` in `templates/geography/`, `unpermitted` anywhere, `Unpermitted` anywhere, `unlawful` anywhere, `Unlawful` anywhere, `illegal` anywhere, `Illegal` anywhere, `stolen` anywhere, `Stolen` anywhere |
| **Uses** | The dashboard's and account page's uses: crop ET plus pumped water not consumed. | `consumptive_use_balance()` `consumptive_use_gross` + `water_not_consumed` | no gated phrase |
| **Pumped water not consumed** | Groundwater extraction minus ETAW met by groundwater on an estimated field; on a metered field the reading less the part of ETAW that surface water does not meet, never below 0. | `consumptive_use_balance()["water_not_consumed"]` | no gated phrase |
| **Applied water not consumed** | A term of the field's mass balance, which no page prints: canal water the crop did not use, surface water in excess of ETAW, and pumped water not consumed on an estimated field. | `parcel_mass_balance()` `deep_percolation_af` | no gated phrase |
<!-- vocabulary: end -->

### 13. A label under a heading says the remainder, never the heading again

The fields table's column header once repeated its card title word for word ("Water use recorded, no
supply reported" under "Fields with water use recorded and no supply reported"), and the panel's breakdown
was titled "Supplies, of which", an idiom a reader had to ask about.
A label is read under the heading above it. If the heading already says the thing, the label says what is
left to say: the arithmetic ("Not met by supplies"), the unit, the scope ("by source"). The settled phrase
stays the quantity's NAME where it stands alone (the use area page's popout is titled "Water use recorded,
no supply reported"); only the repeat under its own title goes. Rule 4 still holds: this stops a restating,
it never renames a quantity.

### 14. Text an engine writes onto a record is a sentence a reader can use

Once the ledger's Description column could be read in full, its descriptions proved accurate and hard
to understand ("demand-weighted ET allocated"). The strings were engine output stored on 1,880 of the demonstration's 2,313
rows, not template text, so no template edit could fix them. Rule 9 is the nearest rule and forbids a
column name in a message; this rule requires more: a description an engine stores is copy, and it must
say what the row is in words the reader would use.

The five sentences are kept in ONE module,
`accounting/ledger_words.py`, beside the Water column's words, so every word the ledger shows lives in one
file: a share of a headgate's delivery split by estimated use ("Share of 214.58 AF delivered from Stevinson
Diversion Canal Headgate, divided up from the canal total in proportion to each field's crop water use after
rain" (every description of a demand-weighted split says it in those words, and the weight is each
field's net consumptive use));
the same split by each use area's share of the canal on file ("…, divided up from the canal total by this use
area's share of the canal on file, 20%, because no use area the canal serves has an estimated use for the
month" (worded this way because "fixed share" was not a phrase a reader knew)); the incidental credit ("Credit for canal water delivered beyond the use area's
estimated use for the month"); the pumping estimate ("Estimated pumping: the month's estimated use, less
rainfall and canal water delivered"); and the month with none ("No groundwater extraction was derived for
this month; rainfall and delivered surface water covered the estimated use."). The guards:
`tests/test_ledger_words.py` scans every constant through `tests/test_domain_vocabulary.py::scan` and the
rule-12 table, and `tests/test_template_hygiene.py` fails a template that carries an engine sentence or the
phrase "calculation engine" (the template prints the stored description; it composes nothing).

Two carry-overs. The figure in the sentence is the one the shares actually sum to
(`consumed_acre_feet()`, not the diverted volume), at the Amount column's precision (two decimals, a
thousands separator), never the four decimals the model stores. And a re-run on rows written before a
wording change must replace them, not double them: the old string stays in the module as a legacy prefix
matched on delete and never written (`LEGACY_INCIDENTAL_RECHARGE_WORDS`). Identifiers
follow the map-card rule (table rule 19, `core.map_labels.map_label`): the headgate's name, never its `MER-POD-…` code.

### 15. Explanatory prose is short, complete sentences

The facility page once described itself as "One facility of CITY OF MERCED, and the sampling points on
it." Nobody writes like this. A noun-phrase fragment
presented as a statement is the shape this platform's prose fell into most often: a reviewer with no
project history flagged 43 of the 77 page descriptions for it the same hour, and none of the rules above
names it, so none of the checks caught it.

**The rule, in one sentence: a page description, a card intro, a help line, an instruction or an
empty-state line is one or more short, complete sentences, each with a subject and a finite verb.**

The About page once shipped the heading "What it owes to the Groundwater Accounting Platform, and what is
its own". A heading is held to this rule too, and so is wording approved before 2026-10-09.

Seven shapes are faults, in any heading or sentence a reader sees:

1. **Two clauses joined by a comma and posing as one heading or sentence.** "Who made it, and where the
   code is" becomes "Who made OpenH2O" or "Where to find the code". "Three sources, and how each is
   known" fails the same way.
2. **A trailing clause tacked on with a comma.** "How the month ends, by what the field has" becomes
   "How a month's figures depend on the field's supplies". "Setting up the platform, in order" fails the
   same way.
3. **A noun phrase presented as a statement.** "One facility of CITY OF MERCED, and the sampling points
   on it." says nothing has happened to anything. "This page holds the facility's record and lists its
   sampling points." is the sentence. A relationship left to "of", "on it", "with" or a colon-list where a
   verb would say it is the same fault.
4. **An em dash in running text.** It becomes a colon, a comma, a full stop or parentheses. A double
   hyphen used as a dash is the same fault.
5. **A filler word:** actually, genuinely, really, simply. It comes out.
6. **A thing acting like a person.** A page does not notice, a record does not arrive with anything, and
   software is not glad to keep learning. The sentence names who does it, or says what the software does.
7. **A slogan or a clever pairing.** "OpenH2O treats that work as the work." and "Real shapes, invented
   owners" are slogans. The plain statement of the fact replaces them.

What is not a fault: a complete imperative ("Pick a zone from the list."); a label of one to three words;
a column header, a map or legend label, a quantity's own name (rules 1 and 12); a colon that introduces
a genuine list after a complete clause ("The file needs three columns: name, date and value."). A heading
may be a plain question ("Who made OpenH2O?") or a plain statement; it may not be two clauses joined by a
comma. Rule 7 still holds: short does not mean padded, and a sentence that only restates its heading is
rule 13's fault, not this rule's cure.

**A table cell that ends with a full stop is a statement, and it has to be a sentence.** A cell with no
full stop is a label, and only shapes 4 to 7 apply to it.

**A definition may stay in dictionary form.** A short line that says what one field or one glossary word
means ("The date establishing seniority.") is a definition, not a statement, and may keep that form. It still carries no em dash.

**The guards.** `tests/test_writing_shapes.py` counts the shapes a pattern can find, in every template,
in the Python that writes onto a screen and in the public guides: an em dash or double hyphen between two
words, the four filler words, a heading of two clauses joined by ", and what" (or who, how, where, why,
when, which), and a heading ending in ", by what". Each file's count may only fall. The other shapes (a
noun phrase posing as a statement, a thing acting like a person, a slogan, and pairs the pattern misses)
need a reader with no project history, reading against this rule's text. A prose instruction to the writer
measured as no help (the writing-layer trial, 2026-09-10 to 09-21); the check at write time is what works.
