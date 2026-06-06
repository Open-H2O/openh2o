<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# OpenH2O Design System

Inherits the VanderDev design token system. Dark mode only, OKLCH color ramps.

## Colors

### Surfaces
- Base: #040608 (page background)
- Card: #080b10 (card/panel backgrounds)
- Inset: #050709 (recessed areas)
- Elevated: #0e1219 (raised elements, dropdowns)
- Hover: #141a22 (hover states)

### Accent
- California Gold: #E4A317 (primary accent, CTAs, active states)
- Gold Hover: #D4952A
- Gold Muted: rgba(212, 149, 42, 0.06) (subtle gold backgrounds)
- Pacific Blue: #1B7FAF (secondary accent, links, map elements)
- Blue Bright: #3DB4E0 (hover state for blue elements)

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
- Large: 16px (modals, large containers)

## Spacing Scale

4px / 8px / 16px / 24px / 32px / 48px / 64px

## Components

- Cards: #080b10 background, 1px border rgba(100,140,180,0.07), 10px radius
- Form inputs: .form-input, .form-select, .form-textarea utility classes
- Tables: .table-scroll wrapper for horizontal overflow
- Toolbar: .toolbar-row for action bars above tables
- Layout: .page-narrow (max-width 640px), .page-medium (max-width 960px)
- Responsive: tablet 1023px, mobile 767px breakpoints
- Empty states: SVG inline icons with secondary text
- Toasts: HTMX-driven notifications
- Breadcrumbs: "/" separated, gold active state
