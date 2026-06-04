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

``apportion_shared_supply`` (Phase 56) is the sibling splitter: where
``allocate_by_demand`` splits a delivery TOTAL into volumes, this splits a single
SHARED source (one well or point-of-diversion serving several parcels) into
normalized weights that sum to exactly 1.0000. It follows a measurement-first
ladder so the platform's stored numbers always beat the ET reference layer:

  RUNG 2 — if a district hand-set ANY member's fraction away from the default
    ``Decimal("1.0")`` sentinel, the whole group is treated as hand-set: the raw
    fractions are normalized and ET demand is ignored. The human split wins.
  RUNG 3 — if every fraction is still the untouched sentinel AND some ET demand
    exists, normalize by demand so the thirsty crop gets the larger share.
  RUNG 4 — all fractions untouched and zero total demand: no signal at all, so
    fall back to an even 1/N split.

The same Decimal-only, 4dp-quantized, last-key-residual conventions apply, so a
shared-supply split agrees with the rest of the ledger to the cent.
"""

from decimal import Decimal

_Q = Decimal("0.0001")


def _dec(value):
    """Coerce to Decimal without going through binary float."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _q(value):
    """Quantize to the ledger's 4 decimal places."""
    return _dec(value).quantize(_Q)


def _place_residual(shares, target):
    """Force ``shares`` to sum to EXACTLY ``target`` after 4dp quantization.

    Quantizing each share independently leaves a rounding residual
    (``target - sum``). Drop it on the LAST key by sorted ``str(key)`` — the same
    last-key-residual convention as ``create_diversion_ledger_entries`` — so this
    layer and the ledger agree to the cent. Mutates and returns ``shares``.
    """
    residual = _dec(target) - sum(shares.values(), Decimal("0"))
    if residual != 0:
        last_key = sorted(shares, key=str)[-1]
        shares[last_key] = _q(shares[last_key] + residual)
    return shares


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
    return _place_residual(shares, total)


def apportion_shared_supply(members):
    """Split ONE shared well / point-of-diversion across its parcels, weighted.

    The measurement-first ladder (see the module docstring): a district's
    hand-set fractions win; absent any hand-set fraction, split by measured ET
    demand; absent demand, split evenly. The result is a set of normalized
    weights summing to EXACTLY ``1.0000`` — the caller multiplies the shared
    source's recorded volume by these to get each parcel's slice.

    Args:
        members: an iterable of ``(key, fraction, demand)`` triples for the
            parcels served by one shared source.

            * ``key`` — parcel id (int) or Parcel instance.
            * ``fraction`` — the stored ``PointOfDiversionParcel`` /
              ``WellIrrigatedParcel`` ``.fraction`` for this link (Decimal). The
              default ``Decimal("1.0")`` is the "untouched" sentinel; any other
              value is a deliberate human entry.
            * ``demand`` — this parcel's measured ET demand for the period
              (Decimal, ``>= 0``); ``0`` means "no ET signal for this parcel".

    Returns:
        ``{key: weight}`` quantized to 4dp and summing to exactly ``1.0000``
        (rounding residual on the last key by sorted ``str(key)``), or ``{}`` for
        empty input. A lone member always maps to ``Decimal("1.0000")``.

    Raises:
        ValueError: any negative fraction or negative demand (fail closed).
    """
    members = list(members)
    if not members:
        return {}

    fractions = {}
    demands = {}
    for key, fraction, demand in members:
        f = _dec(fraction)
        d = _dec(demand)
        if f < 0:
            raise ValueError(f"fraction for {key!r} must be >= 0, got {fraction!r}")
        if d < 0:
            raise ValueError(f"demand for {key!r} must be >= 0, got {demand!r}")
        fractions[key] = f
        demands[key] = d

    # RUNG 2: any fraction nudged off the 1.0 sentinel makes the WHOLE group
    # hand-set — the district decided the split, so ET demand is ignored.
    if any(f != Decimal("1.0") for f in fractions.values()):
        weights = dict(fractions)
    else:
        total_demand = sum(demands.values(), Decimal("0"))
        if total_demand > 0:
            weights = dict(demands)              # RUNG 3: ET demand split
        else:
            weights = {key: Decimal("1") for key in fractions}  # RUNG 4: even

    # Total weight is only zero if rung 2 fractions are all 0 (deliberate, but
    # un-normalizable) — fall back to an even split rather than divide by zero,
    # mirroring _normalize_fractions' total>0 guard.
    total_weight = sum(weights.values(), Decimal("0"))
    if total_weight <= 0:
        weights = {key: Decimal("1") for key in fractions}
        total_weight = sum(weights.values(), Decimal("0"))

    # Normalize to 1.0, quantize, then place the rounding residual on the last
    # key by sorted str(key) so the weights sum to EXACTLY 1.0000.
    shares = {key: _q(w / total_weight) for key, w in weights.items()}
    return _place_residual(shares, Decimal("1.0000"))
