# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one reader of the site's water-year start month.

Everything that decides which water year a month belongs to passes this month
to ``accounting.carryover_math.water_year_of`` (which stays free of Django).
The finalized-year lock reads the same stored column inside the database.
"""

DEFAULT_START_MONTH = 10


def water_year_start_month():
    """The month the site's water year starts in (1 to 12); October with no site row."""
    from core.models import SiteConfig

    value = (
        SiteConfig.objects.order_by("pk")
        .values_list("water_year_start_month", flat=True)
        .first()
    )
    return value or DEFAULT_START_MONTH
