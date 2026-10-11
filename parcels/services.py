# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lookups about a use area that every deployment needs, canals or not."""


def field_efficiency(parcel):
    """One parcel's own field efficiency, and where it came from (148-02, S1).

    Returns ``(Decimal, source)``. ``source`` is ``"method"`` when the parcel
    carries a ``ParcelIrrigationMethod`` (146-05's one-to-one, related_name
    ``irrigation``), which gives the assigned efficiency off that method's
    row. Otherwise ``"agency"``, the deployment-wide
    ``SiteConfig.default_irrigation_efficiency``.

    This is the SAME figure ``surface.services.allocate_district_delivery``'s
    per-parcel cap and ``subtract_surface_water``'s consumption math both read,
    so the split and the subtraction can never drift apart on a mixed-method
    headgate (a center pivot and a furrow field sharing one point of diversion
    must not share one cap; the 146-05 carry).

    Moved here from ``surface.services`` in 150.2-01 with the two models it
    reads, so a deployment without ``surface`` (a groundwater-only district)
    resolves a field's efficiency the same way.

    ``SiteConfig.objects.first() or SiteConfig()`` rather than ``.get()``
    (the established idiom, ``surface/diversion_import.py``): a real deployment
    always carries exactly one row, but this reads safely before one exists,
    falling back to the field's own class default (0.750) instead of raising.
    """
    # Imported lazily so this module has no load-time dependency on core.
    from core.models import SiteConfig

    link = getattr(parcel, "irrigation", None)
    if link is not None:
        return link.method.assigned_efficiency, "method"
    config = SiteConfig.objects.first() or SiteConfig()
    return config.default_irrigation_efficiency, "agency"
