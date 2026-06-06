<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Roadmap

OpenH2O already does the core job: it tracks an agency's water and prepares
California's required reports. This page is about what comes next — and, just as
important, what's already finished.

A bit of background. An earlier version of this roadmap compared OpenH2O against
a more mature reference system (the Qanat / Groundwater Accounting Platform) and
listed three big pieces of accounting math as missing. All three have since been
built, so the list below reflects where the project actually stands.

*For engineers: where a piece is built, the OpenH2O module that holds it is
linked. The Qanat references are methodology to learn from, not code to copy —
it's a different technology stack.*

## Already built

These were the three headline gaps in the old roadmap. They're done:

- **The calculation engine.** The math that turns a satellite
  evapotranspiration (ET) measurement into a usable groundwater number —
  subtract effective rainfall, subtract the surface water that was delivered,
  and so on. Built and tested. *(See
  [`accounting/steps.py`](../accounting/steps.py),
  [`accounting/calculation.py`](../accounting/calculation.py), and
  [`accounting/services.py`](../accounting/services.py).)*
- **Multi-year allocations.** Unused water can roll forward to next year (losing
  a little value if the agency sets a decay rate), and an over-use can be carried
  as a debt against next year's budget. Built. *(See
  [`accounting/models.py`](../accounting/models.py) and
  [`accounting/carryover_math.py`](../accounting/carryover_math.py).)*
- **Splitting shared water across parcels.** When one diversion serves several
  fields, the water is divided among them by how much each crop actually needs.
  Built. *(See [`accounting/allocation_math.py`](../accounting/allocation_math.py).)*

## Next up: publishing open data

OpenH2O already stores its data in a standards-friendly shape. The remaining work
is the "out" side — web endpoints that publish that data so other systems can
read it automatically, without anyone re-keying it. This is deliberately
scheduled for later (on or after August 2026), but it is the next real feature
work, not abandoned. Details in [DATA-STANDARDS.md](DATA-STANDARDS.md).

- **OGC SensorThings API** — a standard web feed of sensor data that any
  compliant tool can read.
- **Frictionless Data Package** — a portable, self-describing bundle of the data
  as files.
- **WaDE 2.0** — the Western states' water-data exchange format.
- **Geoconnex** — permanent web addresses for water features, so they can be
  referenced nationally. (Needs an external registration step.)

## Still to build: meter-reading interpolation

One piece of accounting math genuinely isn't built yet. Real meter readings
arrive on irregular dates; turning them into clean monthly volumes — spread out
day by day between readings — is the missing step. OpenH2O stores the readings
today ([`measurements/models.py`](../measurements/models.py)) but doesn't yet
redistribute them over time. This becomes worth building the moment an agency
brings a real meter dataset.

## Nice to have, eventually

Lower-priority ideas, none of them started yet:

- **Landowner self-reporting** — a form for landowners to report their own
  monthly usage.
- **Billing statements** — per-account usage and allocation statements.
- **Sustainability-project intake** — richer tracking for land-fallowing,
  repurposing, and recharge projects.
- **Raster coverage warnings** — flag partial satellite coverage of a parcel
  instead of quietly averaging over the gaps.
