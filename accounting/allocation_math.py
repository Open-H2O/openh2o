# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pure demand-weighted, efficiency-capped allocation of a delivery total.

Intentionally Django-free (imports only ``decimal`` + the standard library), the
same split that gave 38-03's effective-precip math and the WaterCredit banking
math a real RED->GREEN cycle in bare local Python. This is the heart of Phase 55
— the missing v1.10 capability: an unmetered district records ONE surface
delivery total for a period, but the parcels that diversion serves grow different
crops with different water demand. This kernel splits that one total across the
parcels by each parcel's measured ET demand, never giving any parcel more than it
can physically consume.

It generalizes the throwaway month-axis helper ``_demand_aware_deliveries``
(core/management/commands/seed_merced_ledgers.py) onto the PARCEL axis. The math
is mirrored, NOT imported, so this module stands alone with zero Django/seed
dependencies; the DB wiring (which DiversionRecord, which parcels, the negative
sign convention) is Plan 02's concern.

Three deliberate rules, each encoded below:

  1. CAP = demand / efficiency. To let a crop consume its net demand ``D`` when
     only a fraction ``eff`` of delivered water is actually consumed, the parcel
     needs a delivery of ``D / eff``. No parcel is ever allocated more than this
     ceiling — that ceiling is what kills the pre-052 over-delivery spikes.

  2. AMPLE vs SHORT. When the recorded delivery covers every parcel's cap, each
     parcel simply gets its cap and the leftover above ``sum(caps)`` is left for
     the caller to route (the recovery-horizon surplus of Plan 02/03) — so an
     ample result sums to ``sum(caps)``, NOT to ``delivery_total``. When the
     delivery is SHORT, the WHOLE delivery is distributed by demand weight; each
     parcel still lands at or below its cap (because ``total < sum(caps)``), and
     the result sums EXACTLY to ``delivery_total``.

  3. FAIL CLOSED. Garbage in — a negative delivery, a negative demand, an
     efficiency outside ``(0, 1]`` — raises rather than silently producing a
     wrong water number that an agency would then bill against.

Decimal throughout, quantized to 4 decimal places to match the ledger; a float
anywhere reintroduces binary-float drift on water volumes. The short-delivery
residual (delivery_total minus the sum of the rounded shares) is placed on the
LAST parcel by deterministic ``str(key)`` order, mirroring the
``create_diversion_ledger_entries`` last-parcel-residual convention so the two
layers agree to the cent. Keys may be ints (parcel ids) or Parcel instances;
sorting by ``str(key)`` keeps the function agnostic to key type.
"""

from decimal import Decimal

_Q = Decimal("0.0001")


def _dec(value):
    """Coerce to Decimal without going through binary float."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _q(value):
    """Quantize to the ledger's 4 decimal places."""
    return _dec(value).quantize(_Q)


def allocate_by_demand(delivery_total, demand_by_parcel, efficiency):
    """Split a recorded delivery total across parcels by ET demand, capped.

    Args:
        delivery_total: recorded district delivery for the period (AF, >= 0).
        demand_by_parcel: ``{parcel_key: net_consumptive_demand_af}`` (each >= 0).
            ``parcel_key`` may be an int id or a Parcel instance.
        efficiency: irrigation efficiency, ``0 < eff <= 1`` (e.g. ``0.75``).

    Returns:
        ``{parcel_key: delivery_af}`` quantized to 4dp. AMPLE: every parcel with
        positive demand mapped to its cap ``demand/eff`` (sum == ``sum(caps)``).
        SHORT: the whole ``delivery_total`` split by demand weight (sum ==
        ``delivery_total`` exactly). ZERO total demand or empty input: ``{}``.
        ZERO ``delivery_total`` (with positive demand): every input parcel mapped
        to ``Decimal("0.0000")`` — a recorded zero-delivery month is real data,
        distinct from "no demand".

    Raises:
        ValueError: efficiency outside ``(0, 1]``, a negative ``delivery_total``,
            or any negative demand (fail closed).
    """
    eff = _dec(efficiency)
    total = _dec(delivery_total)

    if eff <= 0 or eff > 1:
        raise ValueError(f"efficiency must be in (0, 1], got {efficiency!r}")
    if total < 0:
        raise ValueError(f"delivery_total must be >= 0, got {delivery_total!r}")

    demand = {}
    for key, value in demand_by_parcel.items():
        d = _dec(value)
        if d < 0:
            raise ValueError(f"demand for {key!r} must be >= 0, got {value!r}")
        demand[key] = d

    total_demand = sum(demand.values(), Decimal("0"))

    # No demand signal at all: the caller decides the fallback (Plan 02 uses the
    # static PointOfDiversionParcel.fraction split). Never divide by zero.
    if total_demand <= 0:
        return {}

    # A recorded zero-delivery month is real data, not "no demand" — record a
    # zero for every parcel so the period is accounted for, not silently dropped.
    if total == 0:
        return {key: Decimal("0.0000") for key in demand}

    # Quantize the caps up front: they are what the ample branch hands out, so the
    # ample/short boundary compares against the SAME 4dp sum we'd return — a raw
    # sum (e.g. 53.33333...) would make a delivery of exactly sum(caps) fall a
    # rounding-hair short and wrongly take the short branch.
    caps = {key: _q(d / eff) for key, d in demand.items() if d > 0}
    total_caps = sum(caps.values(), Decimal("0"))

    # AMPLE: the delivery covers every cap. Each parcel gets exactly its cap; the
    # leftover above sum(caps) is the recovery-horizon surplus the caller routes,
    # so this does NOT sum to delivery_total by design.
    if total >= total_caps:
        return dict(caps)

    # SHORT: distribute the whole delivery by DEMAND weight (demand_p / total_demand,
    # NOT the cap). Each share is <= its cap because total < sum(caps). Quantize,
    # then place the rounding residual on the last parcel by sorted str(key) so the
    # result sums EXACTLY to delivery_total with no Decimal drift.
    shares = {key: _q(total * (demand[key] / total_demand)) for key in caps}
    residual = total - sum(shares.values(), Decimal("0"))
    if residual != 0:
        last_key = sorted(shares, key=str)[-1]
        shares[last_key] = _q(shares[last_key] + residual)
    return shares
