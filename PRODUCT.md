# OpenH2O

## Register

product

## Users

GSA (Groundwater Sustainability Agency) staff and water district managers in California. Typically 1-3 people per agency, many non-technical. They manage their agency's water data — measurements, deliveries, wells, surface diversions, and recharge events — and, when they file with the state, generate the required reports (GEARS, CalWATRS). They work with the platform year-round, not only during reporting seasons.

## Brand

Government infrastructure tool. Serious, trustworthy, competent. Not flashy, not corporate SaaS. The platform should feel like a well-built piece of public infrastructure: reliable, clear, no-nonsense. Think USGS data portals crossed with a modern admin dashboard.

## Tone

Professional and direct. No marketing speak, no gamification. Labels should use domain terminology (parcels, wells, acre-feet, water rights) without explanation since users already know these terms. Error states should be clear and actionable.

## Anti-references

- Generic SaaS dashboards with gradient hero sections
- Overly playful consumer apps (Notion, Linear aesthetic)
- Government legacy systems (green-on-black, table-only layouts)
- Glassmorphism or frosted glass cards
- Neon-on-dark "developer tool" aesthetic

## Strategic Principles

1. **Low barrier to entry.** The platform is built so a small agency can run it on a $15/mo VPS instead of a $35K-$75K vendor engagement — and so the UI is usable without training. Engaging an ops person or consultant is a perfectly good path too; self-deployment is meant to be a real option, not the only one.
2. **Data density over decoration.** Water managers need to see numbers, not animations. Every pixel should serve a purpose.
3. **Domain-native.** The information architecture mirrors how water agencies actually think: their water data — measurements, parcels, wells, accounts, diversions, recharge.
4. **Map-first for spatial data.** Wells and parcels live on maps. The map is a primary navigation surface, not a decoration.
5. **Dark mode only.** Single theme (VanderDev design system). No light mode toggle needed.
