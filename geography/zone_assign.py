# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assign use areas to zones by location, for the zones of one type at a time.

Each use area goes to the zone of the chosen type that holds most of its area,
measured in California Albers (EPSG 3310) as the use-area import measures acres. A use
area already in a zone of that type keeps it. One that lies across two or more zones
(a share of more than a square meter in each; touching a border is not lying across it) joins
the larger share and is listed; one outside every zone joins none and is listed. The
memberships written start and end blank: "always has been", "still is", as the
demonstration's own memberships do.

The Zones page's Assign use areas to zones and ``manage.py assign_zones`` call
:func:`plan` and :func:`assign`. The shares come from one query and the memberships are
written with ``bulk_create``, so a subbasin of thousands of use areas is assigned in
seconds.
"""
from django.db import connection, transaction

from core.modules import is_enabled
from geography.models import ParcelZone, Zone

#: The SRID areas are compared in (the use-area import's acres are measured in it too).
AREA_SRID = 3310

#: A share smaller than this (square meters) is a shared border, not land in the zone:
#: two outlines drawn edge to edge leave slivers of a few square centimeters once both
#: are projected.
SHARE_FLOOR_M2 = 1.0


def types_with_zones():
    """The zone types that have a zone on file, in the zone form's order."""
    present = set(Zone.objects.exclude(zone_type="").values_list("zone_type", flat=True))
    return [(value, label) for value, label in Zone.ZONE_TYPE_CHOICES if value in present]


def _shares(zone_type):
    """``(parcel_id, zone_id, area)`` for every current use area (not voided, not replaced:
    ``core/corrections.py``) not yet in a zone of ``zone_type``
    and every zone of that type it shares area with; and the ids of those use areas."""
    from parcels.models import Parcel

    parcels = Parcel._meta.db_table
    zones = Zone._meta.db_table
    memberships = ParcelZone._meta.db_table
    current_sql, current_params = Parcel.objects.current().values("pk").query.sql_with_params()
    candidates_sql = f"""
        SELECT p.id FROM {parcels} p
        WHERE p.id IN ({current_sql})
        AND NOT EXISTS (
            SELECT 1 FROM {memberships} pz JOIN {zones} z2 ON z2.id = pz.zone_id
            WHERE pz.parcel_id = p.id AND pz.end_date IS NULL AND z2.zone_type = %s
        )
    """
    # The zones are projected once (MATERIALIZED), and a use area wholly inside a zone takes
    # its own area without an intersection: at Merced size (5,735 use areas, three zones of
    # 10,538, 2,584 and 567 vertices) that is 3.9 s against 14.5 s for an intersection a pair.
    shares_sql = f"""
        WITH c AS ({candidates_sql}),
        zt AS MATERIALIZED (
            SELECT id, geometry, ST_MakeValid(ST_Transform(geometry, {AREA_SRID})) AS g
            FROM {zones} WHERE zone_type = %s
        )
        SELECT p.id, zt.id,
               CASE WHEN ST_CoveredBy(p.geometry, zt.geometry)
                    THEN ST_Area(ST_MakeValid(ST_Transform(p.geometry, {AREA_SRID})))
                    ELSE ST_Area(ST_Intersection(ST_MakeValid(ST_Transform(p.geometry, {AREA_SRID})), zt.g))
               END
        FROM c JOIN {parcels} p ON p.id = c.id
        JOIN zt ON ST_Intersects(p.geometry, zt.geometry)
    """
    with connection.cursor() as cursor:
        cursor.execute(candidates_sql, [*current_params, zone_type])
        candidates = [row[0] for row in cursor.fetchall()]
        cursor.execute(shares_sql, [*current_params, zone_type, zone_type])
        shares = [(pid, zid, area or 0.0) for pid, zid, area in cursor.fetchall()]
    return candidates, shares


def plan(zone_type):
    """What assigning the zones of ``zone_type`` would do. Writes nothing.

    Returns ``choice`` (``{parcel_id: zone_id}``), ``per_zone`` (a list of
    ``{"zone", "count"}`` in name order, zones with no use area left out), ``across`` and
    ``outside`` (parcel numbers, sorted), ``already`` (a count) and ``to_assign``.
    """
    from parcels.models import Parcel

    candidates, shares = _shares(zone_type)
    by_parcel = {}
    for pid, zid, area in shares:
        if area > SHARE_FLOOR_M2:
            by_parcel.setdefault(pid, []).append((area, zid))
    choice = {}
    across_ids = []
    for pid, options in by_parcel.items():
        options.sort(key=lambda item: (-item[0], item[1]))
        choice[pid] = options[0][1]
        if len(options) > 1:
            across_ids.append(pid)
    outside_ids = [pid for pid in candidates if pid not in choice]
    numbers = dict(
        Parcel.objects.filter(pk__in=across_ids + outside_ids).values_list("pk", "parcel_number")
    )
    counts = {}
    for zid in choice.values():
        counts[zid] = counts.get(zid, 0) + 1
    per_zone = [
        {"zone": zone, "count": counts[zone.pk]}
        for zone in Zone.objects.filter(pk__in=counts).order_by("name")
    ]
    total = Parcel.objects.current().count()
    return {
        "choice": choice,
        "per_zone": per_zone,
        "across": sorted(numbers[pid] for pid in across_ids),
        "outside": sorted(numbers[pid] for pid in outside_ids),
        "already": total - len(candidates),
        "to_assign": len(choice),
    }


def assign(planned):
    """Write the planned memberships, blank first and last day. Returns how many."""
    rows = [
        ParcelZone(parcel_id=pid, zone_id=zid, start_date=None, end_date=None)
        for pid, zid in planned["choice"].items()
    ]
    with transaction.atomic():
        ParcelZone.objects.bulk_create(rows, batch_size=2000)
    return len(rows)


def finalized_year_names():
    """The names of the finalized water years, oldest first (none without accounting)."""
    if not is_enabled("accounting"):
        return []
    from accounting.models import ReportingPeriod

    return list(
        ReportingPeriod.objects.filter(is_finalized=True).order_by("start_date").values_list("name", flat=True)
    )


def use_areas(count):
    return "use area" if count == 1 else "use areas"


def across_sentence(across, to_assign):
    verb = "lies" if across == 1 else "lie"
    return f"{across:,} of the {to_assign:,} use areas to assign {verb} across two or more zones."


def result_sentence(count):
    return f"OpenH2O assigned {count:,} {use_areas(count)} to their zones."


def outside_sentence(count):
    verb = "lies" if count == 1 else "lie"
    return (f"{count:,} {use_areas(count)} {verb} outside every zone. To assign one by hand, "
            "open a zone's page and use Assign use area.")


def preview_lines(planned):
    """The preview's table as (count, what, action), for the command."""
    lines = [(row["count"], use_areas(row["count"]), f"Assigned to {row['zone'].name}") for row in planned["per_zone"]]
    if planned["outside"]:
        n = len(planned["outside"])
        lines.append((n, f"{use_areas(n)} outside every zone", "Not assigned"))
    if planned["already"]:
        n = planned["already"]
        lines.append((n, f"{use_areas(n)} already in a zone of this type", "Unchanged"))
    return lines
