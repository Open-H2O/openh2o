# SPDX-License-Identifier: AGPL-3.0-or-later
"""Lookups about a use area that every deployment needs, canals or not."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import SiteConfig
    from parcels.models import Parcel


def field_efficiency(
    parcel: Parcel, config: SiteConfig | None = None
) -> tuple[Decimal, str]:
    """One parcel's own field efficiency, and where it came from.

    Returns ``(Decimal, source)``. ``source`` is ``"method"`` when the parcel
    carries a ``ParcelIrrigationMethod`` (a one-to-one, related_name
    ``irrigation``), which gives the assigned efficiency off that method's
    row. Otherwise ``"agency"``, the deployment-wide
    ``SiteConfig.default_irrigation_efficiency``.

    This is the SAME figure ``surface.services.allocate_district_delivery``'s
    per-parcel cap and ``subtract_surface_water``'s consumption math both read,
    so the split and the subtraction can never drift apart on a mixed-method
    headgate (a center pivot and a furrow field sharing one point of diversion
    must not share one cap).

    Lives here, not in ``surface.services``, with the two models it
    reads, so a deployment without ``surface`` (a groundwater-only district)
    resolves a field's efficiency the same way.

    ``config`` lets a caller that has already read the deployment's
    ``SiteConfig`` for a whole run pass it in (``run_calculations``
    reads it once, so a settings edit mid-run cannot give two fields two
    different defaults). Otherwise it is read here.

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
    if config is None:
        config = SiteConfig.objects.first() or SiteConfig()
    return config.default_irrigation_efficiency, "agency"
