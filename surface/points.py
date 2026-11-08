# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finding a point of diversion from a name a person typed in a file."""
from __future__ import annotations

from surface.models import PointOfDiversion


def point_named(value: str) -> PointOfDiversion | None:
    """Return the point whose local name is ``value``, else the one whose name is, else None.

    One lookup for every import that names a point: the diversion import's
    point column and the use area import's headgate column.
    """
    point = PointOfDiversion.objects.filter(local_name=value).first()
    if point is None:
        point = PointOfDiversion.objects.filter(name=value).first()
    return point
