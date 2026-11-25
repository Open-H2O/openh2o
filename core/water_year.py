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


def start_month_is_locked():
    """True once moving the start month would make OpenH2O read the wrong year.

    The finalized-year lock names a closed year's carry-over and account credit
    rows from today's start month, and voiding a recharge event works out its
    pool's year the same way. So the month stays as it is once any water year is
    finalized or any recharge event is on file.
    """
    from accounting.models import ReportingPeriod
    from core.modules import is_enabled

    if ReportingPeriod.objects.filter(is_finalized=True).exists():
        return True
    if is_enabled("recharge"):
        from recharge.models import RechargeEvent

        return RechargeEvent.objects.exists()
    return False
