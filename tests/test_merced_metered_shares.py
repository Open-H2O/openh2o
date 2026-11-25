# SPDX-License-Identifier: AGPL-3.0-or-later
"""A demonstration well with a meter is charged from its readings, as a real site's is.

The demonstration's ledger seed once wrote each metered field's groundwater as a row of its own, which
the calculation reads as a row a person typed: it then never divided the well's readings among its
fields, so a corrected or voided reading changed the well's page and not the field's account. The seed
now writes no such row; it sizes the well's monthly readings, and the calculation writes each field's
share from them.
"""
from io import StringIO

import pytest
from django.core.management import call_command

from accounting.ledger_words import WELL_METER_SHARE_WORDS
from core.management.commands.seed_merced_ledgers import Command as LedgerSeed
from parcels.models import ParcelLedger
from tests import factories as f

pytestmark = pytest.mark.django_db


def _metered_well_with_two_fields():
    well = f.WellFactory(name="MER-W-001", well_registration_id="MER-W-001")
    for number in ("MER-APN-001", "MER-APN-002"):
        f.WellIrrigatedParcelFactory(well=well, parcel=f.ParcelFactory(parcel_number=number), fraction="0.5000")
    return well


def test_a_demonstration_well_with_a_meter_is_charged_from_its_reads():
    well = _metered_well_with_two_fields()

    call_command("seed_merced_ledgers", stdout=StringIO())

    typed = ParcelLedger.objects.filter(source_type="meter_reading").exclude(
        description__startswith=WELL_METER_SHARE_WORDS
    )
    assert not typed.exists()
    well.refresh_from_db()
    assert well.measurement_method == "certified_meter"
    # The readings the measurement seed writes come from the same sizing, one figure a well and month.
    months = LedgerSeed().metered_well_months()
    assert {well_id for well_id, _month in months} == {well.pk}
    assert len(months) == 24
    assert sum(months.values()) > 0
