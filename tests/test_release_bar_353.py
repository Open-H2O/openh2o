# SPDX-License-Identifier: AGPL-3.0-or-later
"""When OpenET revises a month, the ledger's ET estimate and the calculation agree on it.

A refresh from the source replaces the month's ET in the cache. The calculation reads the cache
when it runs; the ledger's ET estimate row for the month was written by the first sync and the
sync skips a month that already has one. After a refresh and both runs, the two should state the
same ET for the month.

Which of the two values is right, and whether a revision is kept as a correction from the
source, is a question for the maintainer; the test is marked to fail until that is ruled.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from accounting.models import CalculationRun
from datasync.models import OpenETCache
from parcels.models import ParcelLedger
from tests import ledger_districts as ld

pytestmark = pytest.mark.django_db

JULY = "2025-07"


def _sync():
    call_command(
        "sync_openet_to_ledger", "--start-date", "2025-07-01", "--end-date", "2025-07-31",
        stdout=StringIO(),
    )


def _estimate(parcel):
    return ParcelLedger.objects.current().get(
        parcel=parcel, source_type="et_estimate", effective_date__year=2025, effective_date__month=7,
    ).amount_acre_feet


def _gross(parcel):
    return CalculationRun.objects.filter(parcel=parcel, period=JULY).order_by("-pk").first().gross_et_af


@pytest.mark.xfail(
    strict=True,
    reason="Which value the ledger row and the calculation agree on when the source revises a "
    "month, and whether the revision is kept, are for the maintainer to rule.",
)
def test_a_revised_month_reads_the_same_in_the_ledger_and_the_calculation():
    ld.seed_reference()
    field = ld.build_d1()["F4"]
    _sync()
    ld.run_months([JULY])
    assert -_estimate(field) == _gross(field)

    cache = OpenETCache.objects.get(parcel=field)
    cache.et_data = [
        {**item, "et": 121.92} if item["date"].startswith(JULY) else item for item in cache.et_data
    ]
    cache.save()
    _sync()
    ld.run_months([JULY])

    assert -_estimate(field) == _gross(field)
