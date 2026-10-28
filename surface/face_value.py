# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every water year of a right set against its face value.

The right's page compares each water year on record with the face value: the
current year in its equation row (Face value less Recorded is Remaining, read
off ``current_totals`` in ``surface.views._water_right_detail_context``), and
every year in the "By water year" table under it, which is this module's one
caller.

:func:`years_against_face_value` reads the groups
``surface.views._group_diversion_records`` builds from the right's records, so
the table can never disagree with the records table on the same page: each
row's total IS the group's ``diverted``, never a second query. A year whose
total passes the face value is "over its face value" by the difference; the
platform states the arithmetic and stops there.
"""

from decimal import Decimal

_Q = Decimal("0.0001")


def years_against_face_value(water_right, record_groups):
    """One row per water-year group, newest first, set against the right's face value.

    ``record_groups`` is what ``_group_diversion_records`` returns for every
    record on the right. Each row carries ``period_key`` and ``period_name``
    (the group's own), ``total_af`` (the group's ``diverted``), ``months``
    (distinct calendar months with a record), ``record_count``, and
    ``over_by_af`` /
    ``remaining_af``. ``over_by_af`` is the total less the face value when
    that is above zero, else None; ``remaining_af`` is the face value less the
    total when that is zero or more, else None. A right with no face value
    gets None for both on every row. Figures are quantized to four places.
    """
    face_value = water_right.face_value_acre_feet
    rows = []
    for group in record_groups:
        months = {(record.month.year, record.month.month) for record in group["rows"]}
        total = group["diverted"]
        over_by = None
        remaining = None
        if face_value is not None:
            if total > face_value:
                over_by = (total - face_value).quantize(_Q)
            else:
                remaining = (face_value - total).quantize(_Q)
        rows.append(
            {
                "period_key": group["period_key"],
                "period_name": group["period_name"],
                "total_af": total.quantize(_Q),
                "months": len(months),
                "record_count": group["count"],
                "over_by_af": over_by,
                "remaining_af": remaining,
            }
        )
    return rows
