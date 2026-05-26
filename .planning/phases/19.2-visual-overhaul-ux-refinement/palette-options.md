# Palette Options: OpenH2O Visual Overhaul

## Logo Color Extraction

The Contour Basin v2 water drop logo uses five concentric rings from outer to inner:

| Ring | Approximate Hex | OKLCH | Role |
|------|----------------|-------|------|
| Outer rim | #1E2D4D | oklch(0.27 0.06 250) | Deep navy anchor |
| Second band | #2C4A72 | oklch(0.37 0.07 245) | Mid-dark blue |
| Third band | #3B6A97 | oklch(0.48 0.08 240) | Core Pacific blue |
| Fourth band | #5A95BC | oklch(0.63 0.08 230) | Bright water blue |
| Inner drop | #C0D8E6 | oklch(0.87 0.03 225) | Ice blue highlight |

Silver-white accent lines separate some rings (metallic highlight effect).

**Key finding:** The logo's core blue (#3B6A97) is cooler and more desaturated than the current `--color-blue: #2089BB`. The logo leans slate-blue, not teal-blue.

## The Clash Problem

Current gold `#E4A317` (OKLCH hue 75) sits at warm-yellow. The logo blues sit at hue 230-250 (cold). On the color wheel, these are ~170 degrees apart: not complementary (180) and not analogous. The result is visual tension without harmony: they fight rather than complement.

## Typography Finding

**Public Sans is correct.** Both VanderDev and OpenH2O use Public Sans. The "too casual" impression comes from:
1. Missing font weights: OpenH2O loads 400/600/800; VanderDev loads 300-800
2. Body text at 400 feels heavy without 300 available for lighter secondary text
3. No 500 weight means buttons and labels can't hit "medium" emphasis

**Fix:** Expand Google Fonts load to `wght@300;400;500;600;700;800`. No font swap needed.

---

## Option A: "Deep Pacific" (Recommended)

**Philosophy:** Extract the primary blue directly from the logo's core band. Shift gold warmer (toward amber) to create true warm/cool complementary pair.

### Colors

| Token | Current | Proposed | OKLCH |
|-------|---------|----------|-------|
| `--color-blue` | #2089BB | **#2E6B96** | oklch(0.48 0.08 235) |
| `--color-blue-bright` | #3DB4E0 | **#5A95BC** | oklch(0.63 0.08 230) |
| `--color-gold` | #E4A317 | **#D49A2B** | oklch(0.72 0.13 68) |
| `--color-gold-hover` | #D4952A | **#C48B24** | oklch(0.67 0.12 65) |
| `--color-gold-muted` | rgba(212,149,42,0.06) | **rgba(196,139,36,0.08)** | - |
| NEW `--color-blue-muted` | - | **rgba(46,107,150,0.10)** | - |

### Why This Works

- Primary blue (#2E6B96) is the literal logo color, so sidebar and nav feel "same family" as the brand mark
- Gold shifted 7 degrees warmer (hue 75→68) moves it from yellow-gold to amber-gold, creating a clean warm/cool complement instead of a near-miss clash
- The amber tone (#D49A2B) reads as "California Gold" without the harsh yellow that fights cold blues
- Blue-bright (#5A95BC) pulled from the fourth logo ring works for hover states and active indicators
- New blue-muted token enables sidebar active-state backgrounds in blue instead of gold where contextually appropriate

### Trade-offs

- (+) Strongest brand connection: UI literally uses the logo's own palette
- (+) Amber-gold still reads "California" at a glance
- (-) More saturated than VanderDev's restrained grays; OpenH2O becomes visually "its own thing" rather than a strict VanderDev sibling
- (-) Blue primary in nav means less gold visible on typical pages

---

## Option B: "Muted Professional"

**Philosophy:** Desaturate the logo blue toward slate. Keep current gold but tone it down. Closest to VanderDev's restrained aesthetic.

### Colors

| Token | Current | Proposed | OKLCH |
|-------|---------|----------|-------|
| `--color-blue` | #2089BB | **#4A6B8A** | oklch(0.48 0.04 235) |
| `--color-blue-bright` | #3DB4E0 | **#6A90AB** | oklch(0.61 0.05 230) |
| `--color-gold` | #E4A317 | **#CFA430** | oklch(0.74 0.11 80) |
| `--color-gold-hover` | #D4952A | **#BF9528** | oklch(0.70 0.10 76) |
| `--color-gold-muted` | rgba(212,149,42,0.06) | **rgba(191,149,40,0.06)** | - |

### Why This Works

- Slate-blue (#4A6B8A) feels governmental and serious without being bold
- Toned-down gold (#CFA430) reduces the clash by pulling saturation from 0.145 to 0.11
- Minimal palette disruption from Phase 12.1 work

### Trade-offs

- (+) Most VanderDev-like; reads as "same organization, different product"
- (+) Least risky: small color shifts, existing styles mostly survive
- (-) Less distinctive; doesn't feel "water" as strongly
- (-) Gold is quieter but still on hue 80: the tension is reduced, not eliminated

---

## Option C: "High Contrast"

**Philosophy:** Blue dominates the interface. Gold is reserved exclusively for call-to-action buttons and badges. Navigation active states use blue.

### Colors

| Token | Current | Proposed | OKLCH |
|-------|---------|----------|-------|
| `--color-blue` | #2089BB | **#2C7DB5** | oklch(0.55 0.10 235) |
| `--color-blue-bright` | #3DB4E0 | **#3DB4E0** | (unchanged) |
| `--color-gold` | #E4A317 | **#E4A317** | (unchanged) |
| `--color-gold-hover` | #D4952A | **#D4952A** | (unchanged) |
| NEW `--color-nav-active` | - | **#1B5A8A** | oklch(0.42 0.08 240) |
| NEW `--color-nav-active-text` | - | **#9ECAE1** | oklch(0.80 0.06 225) |

### Why This Works

- Gold (#E4A317) stays exactly as-is but only appears on buttons and badges
- Blue (#2C7DB5) takes over sidebar active states, links, and borders
- Separation by function: blue = navigation/information, gold = action/attention
- Maximum readability on dark backgrounds

### Trade-offs

- (+) Clearest visual hierarchy; bold modern SaaS feel
- (+) Gold preserved exactly for maximum California identity on CTAs
- (-) Furthest from current look; most template/CSS changes needed
- (-) Gold-blue clash not solved, just separated spatially (they still appear near each other on pages with CTA buttons in the sidebar region)
- (-) May feel colder/less warm than the current design

---

## Recommendation: Option A (Deep Pacific)

Option A solves the root cause (gold hue fighting blue hue) rather than working around it. The amber shift is subtle enough that "California Gold" identity stays intact, while extracting blues directly from the logo makes the entire site feel like an extension of the brand mark. The new blue-muted token also solves a secondary problem: sidebar active states can use the brand blue where gold felt arbitrary.

Option B is safest but leaves the underlying clash partially unresolved. Option C has the boldest hierarchy but requires the most template changes and doesn't address the color tension.
