# SPDX-License-Identifier: AGPL-3.0-or-later
"""Link-driven recharge archetype + routing policy (Phase 52.6, ISS-053).

The policy layer that decides whether a unit of managed/incidental recharge
becomes a *personal* (recoverable) groundwater credit on a parcel, or flows to
the GSA-level basin pool. It is a PURE decision layer — no ledger writes, no
Decimal math, no engine state — so the rest of Phase 52.6 is thin wiring around
these two functions.

The decision falls out entirely of a parcel's own links, sorting it into one of
three archetypes:

* ``CONJUNCTIVE`` — has a well. Banks surplus underground and pumps it back, so
  its recharge is a personal credit it recovers itself.
* ``FLOOD_MAR`` — no well, but has a crop (typically with surface delivery).
  Contributes to the basin-wide pool; recovers nothing itself.
* ``BASIN`` — no well, no crop (a fallow recharge basin). Dedicated infiltration
  straight to the basin pool.

ISS-053 is the bug this prevents: a surface-only parcel (e.g. MER-APN-031 — a
point of diversion and a crop, but no well) was receiving a per-parcel
groundwater recharge credit it has no well to pump against. The single
discriminator for personal-vs-pool is therefore ``has_well``: CONJUNCTIVE routes
personal, BASIN and FLOOD_MAR route to the pool. The three-way label exists for
reporting clarity, but the routing predicate stays robust even on odd link
combinations (crop + no surface + no well is still pool, never personal).
"""

# Archetype labels. Plain string constants — the accounting app has no
# TextChoices/Enum precedent for this kind of internal policy tag, and these
# never reach the DB, so strings keep the call sites readable.
BASIN = "basin"
CONJUNCTIVE = "conjunctive"
FLOOD_MAR = "flood_mar"

#: All recharge archetypes, in routing-precedence order (well first).
RECHARGE_ARCHETYPES = (CONJUNCTIVE, FLOOD_MAR, BASIN)


def parcel_recharge_archetype(parcel):
    """Classify ``parcel`` into one of the three recharge archetypes from its links.

    Keyed strictly on the parcel's own link tables:

    * a well link (``WellIrrigatedParcel``) -> ``CONJUNCTIVE``
    * else a crop (``UsageLocation``)        -> ``FLOOD_MAR``
    * else (fallow)                          -> ``BASIN``

    Surface (``parcel.pod_parcels``) is informational only and does not affect
    the split — a crop with or without surface is FLOOD_MAR all the same.
    """
    # Local imports avoid app-loading import cycles (accounting <-> wells/parcels).
    from wells.models import WellIrrigatedParcel
    from parcels.models import UsageLocation

    if WellIrrigatedParcel.objects.filter(parcel=parcel).exists():
        return CONJUNCTIVE
    if UsageLocation.objects.filter(parcel=parcel).exists():
        return FLOOD_MAR
    return BASIN


def recharge_routes_to_personal(parcel_or_archetype):
    """Return ``True`` iff this parcel's recharge is a personal (recoverable) credit.

    Accepts either a ``Parcel`` instance (which it classifies first) or a bare
    archetype string. Personal recovery requires a well, so only ``CONJUNCTIVE``
    routes personal; ``BASIN`` and ``FLOOD_MAR`` route to the GSA basin pool.
    This is the ISS-053 guard: no parcel earns a personal groundwater credit
    without a well to pump it back.
    """
    if isinstance(parcel_or_archetype, str):
        archetype = parcel_or_archetype
    else:
        archetype = parcel_recharge_archetype(parcel_or_archetype)
    return archetype == CONJUNCTIVE
