"""151.2-02: the zero row's sentence, in the engine and on rows already saved.

The engine writes NO_PUMPING_DERIVED_WORDS on a calculated row whose amount is
zero. Migration 0014 carries the new words onto rows written before the change,
and must move only the description: amounts, dates and other rows stay as they
were.
"""

import importlib
from datetime import date
from decimal import Decimal

import pytest

from accounting.ledger_words import NO_PUMPING_DERIVED_WORDS
from parcels.models import ParcelLedger
from tests.factories import ParcelFactory, ParcelLedgerFactory

pytestmark = pytest.mark.django_db

migration = importlib.import_module(
    "parcels.migrations.0014_parcelledger_zero_extraction_words"
)
# 151.3-05: the sentence changed again; 0016 carries 0014's words onward.
latest = importlib.import_module(
    "parcels.migrations.0016_parcelledger_zero_extraction_words_again"
)


def test_the_engine_and_the_migration_say_the_same_words():
    assert NO_PUMPING_DERIVED_WORDS == latest.NEW_NO_PUMPING
    # Each migration picks up the words the one before it wrote.
    assert latest.OLD_NO_PUMPING == migration.NEW_NO_PUMPING
    assert NO_PUMPING_DERIVED_WORDS == (
        "Groundwater did not meet any of this month's ETAW, so the estimated "
        "groundwater extraction is zero."
    )


def test_migration_rewords_only_old_zero_rows_and_moves_nothing_else():
    parcel = ParcelFactory()

    def row(description, source_type="calculated", amount="0"):
        return ParcelLedgerFactory(
            parcel=parcel,
            effective_date=date(2025, 1, 1),
            source_type=source_type,
            description=description,
            amount_acre_feet=Decimal(amount),
        )

    old = row(migration.OLD_NO_PUMPING)
    estimate = row(
        "ETAW met by groundwater (estimated): ETAW − ETAW met by surface water.",
        amount="-3.2500",
    )
    other_source = row(migration.OLD_NO_PUMPING, source_type="meter_reading")
    before = {
        r.pk: (r.amount_acre_feet, r.effective_date, r.transaction_date, r.source_type)
        for r in ParcelLedger.objects.filter(parcel=parcel)
    }

    assert migration.reword_rows(ParcelLedger) == 1

    rows = {r.pk: r for r in ParcelLedger.objects.filter(parcel=parcel)}
    assert rows[old.pk].description == migration.NEW_NO_PUMPING
    assert rows[estimate.pk].description == estimate.description
    assert rows[other_source.pk].description == migration.OLD_NO_PUMPING
    assert {
        pk: (r.amount_acre_feet, r.effective_date, r.transaction_date, r.source_type)
        for pk, r in rows.items()
    } == before

    # Running it again changes nothing; the reverse puts the old words back.
    assert migration.reword_rows(ParcelLedger) == 0
    assert (
        migration.reword_rows(
            ParcelLedger, migration.NEW_NO_PUMPING, migration.OLD_NO_PUMPING
        )
        == 1
    )
    assert (
        ParcelLedger.objects.get(pk=old.pk).description == migration.OLD_NO_PUMPING
    )


def test_0016_carries_0014s_words_onward_and_back():
    parcel = ParcelFactory()
    saved = ParcelLedgerFactory(
        parcel=parcel,
        effective_date=date(2025, 1, 1),
        source_type="calculated",
        description=latest.OLD_NO_PUMPING,
        amount_acre_feet=Decimal("0"),
    )

    assert latest.reword_rows(ParcelLedger) == 1
    assert ParcelLedger.objects.get(pk=saved.pk).description == latest.NEW_NO_PUMPING
    assert ParcelLedger.objects.get(pk=saved.pk).amount_acre_feet == Decimal("0")
    assert latest.reword_rows(ParcelLedger, latest.NEW_NO_PUMPING, latest.OLD_NO_PUMPING) == 1
    assert ParcelLedger.objects.get(pk=saved.pk).description == latest.OLD_NO_PUMPING
