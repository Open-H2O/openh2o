<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# OpenH2O Design System

Inherits the VanderDev design token system. Dark mode only, OKLCH color ramps.

## Colors

### Surfaces
The surfaces are OKLCH (a slightly blue-grey 260 hue), not flat hex — they read
as a tonal stack rather than near-black. Values from `static/css/tokens.css`:
- Base: #040608 (page background)
- Card: oklch(0.17 0.012 260) — ~#1a1e27 (card/panel backgrounds)
- Inset: oklch(0.12 0.010 260) — ~#12151b (recessed areas)
- Elevated: oklch(0.21 0.012 260) — ~#242a33 (raised elements, dropdowns)
- Hover: oklch(0.24 0.012 260) — ~#2c333d (hover states)

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
  primary call-to-action buttons and the single figure a page produces
  (`.result-card`). Do **not** use gold as a general-purpose emphasis or callout
  color; that is the mistake that makes a page look off-brand. (Note: some older
  components such as `.callout-rule` still hardcode the pre-Deep-Water gold
  `#E4A317` — treat that as legacy, not as the pattern to copy.)
- **Pacific Blue — data affordances.** `--color-blue: #1B7FAF` (bright
  `#3DB4E0`). Parcels, map elements, and links that point out to water data.

**Emphasizing prose:** do not reach for a color at all. Body and intro text is
plain left-aligned prose; when a passage needs lifting, wrap it in the same
`.card-raised` panel the credit cards and Help "short version" blocks use — no
colored left-stripe. A colored stripe or filled accent box around a lone
paragraph reads as a generic AI callout, not this design system.

### Text
- Primary: #e8edf4 (body text, headings)
- Secondary: #8899aa (labels, descriptions, metadata)
- Tertiary: #4d5e6f (subtle text, placeholders)

### Borders
- Default: rgba(100, 140, 180, 0.07)
- Hover: rgba(100, 140, 180, 0.13)

### Data Visualization
Three OKLCH tonal ramps (8 stops each, 100-800):
- Furnace Orange (hue 50): heat, usage, extraction
- Reservoir Blue (hue 200): water levels, supply, precipitation
- Forest Teal (hue 145): recharge, conservation, positive change

## Typography

- Display: Public Sans (system-like, government identity)
- Monospace: JetBrains Mono (data tables, code, IDs)
- Body line length: 65-75ch max

## Elevation

- Pop shadow (small): 2px 2px 4px rgba(4,3,2,0.70), -2px -2px 4px rgba(42,32,24,0.50)
- Pop shadow (large): 6px 6px 12px rgba(4,3,2,0.80), -6px -6px 12px rgba(42,32,24,0.60)
- Inset shadow: inset 2px 2px 4px rgba(4,3,2,0.70), inset -2px -2px 4px rgba(42,32,24,0.50)

## Border Radius

- Small: 6px (buttons, inputs)
- Medium: 10px (cards)
- Large: 12px (modals, large containers, budget/result panels)

## Spacing Scale

4px / 8px / 16px / 24px / 32px / 48px / 64px

## Components

- Cards: `.card-raised` — var(--color-card) background, 1px border, 10px radius.
  Add `.card-inset` for a quieter, recessed variant (references, secondary aids).
- Form inputs: .form-input, .form-select, .form-textarea utility classes
- Tables: .table-scroll wrapper for horizontal overflow
- Toolbar: .toolbar-row for action bars above tables
- Layout: .page-narrow (max-width 640px), .page-medium (max-width 960px)
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
  Used on the dashboard, period detail, account detail, and (as
  `.budget-panel--concept`, carrying descriptive text instead of live AF figures)
  the Help explainers.
- `.accent-card` — a left-accent feature card for a labeled entity with a
  description + an action (e.g. the report-type heroes). `--gold` / `--blue`
  modifiers tint the left edge and a small icon chip.
- `.concept-panel` (+ `-use` / `-supply`) — a two-up "use vs. supply"
  comparison with a colored top border.
- `.result-card` — a gold-accent hero for the single figure a page produces
  (e.g. final billable groundwater on the calculation-run page).
- `.callout-rule` — a gold left-border inset for "the rule" of a page.
- `.step-card` / `.step-number` / `.step-eyebrow` — the ordered-sequence idiom
  (Help steps; the methodology editor uses `.methodology-step` + a numbered
  badge, with a muted dashed variant for disabled steps).
- `.card-grid` + `.card-link` — a responsive grid of linked cards (page footers).
- `.prose-link` — an underlined inline link inside prose (visibly a link).
- `.radio-option` / `.input-suffix` — on-brand radio tiles and an input with an
  attached unit (e.g. an efficiency percent + "%").
- `.data-table.waterfall` — calculation-run tables shaded by step type
  (reduction = furnace, addition = forest, start/pass-through = neutral).

### Casing convention

UI labels, eyebrows, section headers, and disclosure triggers are **sentence
case**, not uppercase — "Account balance", not "ACCOUNT BALANCE". The two
deliberate exceptions are data-table column headers (`.data-table th` is
uppercased in CSS) and cartographic map/legend labels, which follow map
convention.
