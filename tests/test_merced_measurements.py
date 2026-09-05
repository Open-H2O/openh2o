# SPDX-License-Identifier: AGPL-3.0-or-later
"""Spec for seed_merced_measurements (Phase 132-01, ISS-105).

The command that gives the demonstration an INSTRUMENT RECORD: on-site
monitoring at the recharge basins, the monitoring wells, monthly totalizer reads
on the certified meters, one daily logger, and the hand-entered field readings
beside it.

These cover the four things that would silently rot, plus the one claim a domain
expert will actually check:

  - Idempotent — a re-run leaves every count where it was.
  - No user rows — ``read_by`` and ``recorded_by`` stay NULL, because promotion
    gate 2 requires ``core.User = 0`` and ``scripts/rebuild-golden.sh`` skips
    ``ensure_superuser`` specifically to keep it there.
  - The conformance audit has something to CHECK — zero null observed_property
    FKs **and** a non-zero total. A zero-row table also has zero nulls, and that
    vacuous pass is the whole reason half this phase exists.
  - The accounting spine did not move — ``ParcelLedger`` and ``DiversionRecord``
    are untouched. ``measurements.MeterReading`` and a ledger row of source type
    ``meter_reading`` are two different things with nearly the same name.
  - Cadence follows the well's OWN declaration, so a future change cannot
    quietly smuggle a streaming logger into a demonstration whose PROJECT.md
    puts real-time telemetry out of scope.
  - The totalizer reconciles to the ledger. A water master reading a well's
    meter against its parcel's metered groundwater will compare the two, and
    disagreement is a worse defect than emptiness.

Runs in the web container (needs the DB).
"""
from datetime import date
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.db.models import Sum

from measurements.models import (
    Meter, MeterReading, Sensor, SensorMeasurement, WaterMeasurement,
)
from parcels.models import ParcelLedger
from recharge.models import RechargeMeasurement
from standards.models import ObservedProperty
from surface.models import DiversionRecord
from wells.models import MonitoringWell, WellIrrigatedParcel, WellMeter

from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    RechargeSiteFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)

DEMO_OPERATOR = "Halvern Irrigation District"
# The months the ledger fixture carries metered groundwater for, and the
# magnitude of each. Two months only: enough to prove the totalizer sums what the
# ledger holds and stands still in a month with no pumping.
LEDGER_MONTHS = {
    date(2024, 10, 15): Decimal("40.5000"),
    date(2025, 5, 15): Decimal("12.2500"),
}


@pytest.fixture
def demo(db):
    """The slice of the Merced demo this command reads.

    A basin found by operator; the metered well MER-W-001 with its display meter,
    its irrigated parcel and that parcel's metered-groundwater ledger; the
    transducer well MER-W-004; and the standards vocabulary, seeded by its own
    command rather than hand-built, so the concept the meter reads is the same
    row a real build produces.
    """
    call_command("seed_observed_properties")

    RechargeSiteFactory(
        name="El Nido Recharge Basin 1",
        operator=DEMO_OPERATOR,
        site_type="spreading_basin",
        capacity_acre_feet=Decimal("637.1000"),
    )
    RechargeSiteFactory(
        name="Merced River Ag Parcel 1 (Flood-MAR)",
        operator=DEMO_OPERATOR,
        site_type="spreading_basin",
        capacity_acre_feet=Decimal("159.6000"),
    )

    metered = WellFactory(
        well_registration_id="MER-W-001", measurement_method="certified_meter"
    )
    parcel = ParcelFactory(parcel_number="MER-APN-002")
    WellIrrigatedParcelFactory(well=metered, parcel=parcel)
    meter = Meter.objects.create(
        serial_number="MTR-MER-W-001", meter_type="totalizer", unit="acre_feet"
    )
    WellMeter.objects.create(well=metered, meter=meter, is_current=True)
    for when, amount in LEDGER_MONTHS.items():
        ParcelLedgerFactory(
            parcel=parcel,
            transaction_date=when,
            effective_date=when,
            amount_acre_feet=-amount,
            source_type="meter_reading",
        )

    # The transducer well. Its declaration in the command's MONITORING_WELLS is
    # "Continuous", which is the only frequency that earns a logger.
    WellFactory(well_registration_id="MER-W-004", measurement_method="unmetered_estimate")
    # A diversion record so the spine assertion is measuring something rather
    # than comparing zero to zero.
    DiversionRecordFactory()
    return {"meter": meter, "parcel": parcel, "well": metered}


def _counts():
    return {
        "recharge": RechargeMeasurement.objects.count(),
        "monitoring_wells": MonitoringWell.objects.count(),
        "meter_readings": MeterReading.objects.count(),
        "sensors": Sensor.objects.count(),
        "sensor_measurements": SensorMeasurement.objects.count(),
        "water_measurements": WaterMeasurement.objects.count(),
    }


@pytest.mark.django_db
def test_running_twice_changes_nothing(demo):
    """Idempotent: the command self-flushes its own rows before recreating them."""
    call_command("seed_merced_measurements")
    first = _counts()
    assert all(v > 0 for v in first.values()), first

    call_command("seed_merced_measurements")
    assert _counts() == first


@pytest.mark.django_db
def test_no_reading_carries_a_user(demo):
    """No row may name a reader.

    Promotion gate 2 requires ``core.User = 0`` in the candidate, and
    ``scripts/rebuild-golden.sh`` bypasses ``ensure_superuser`` to keep it there.
    A user FK on a reading would create the exact row that mechanism exists to
    prevent. Provenance belongs in ``notes``.
    """
    call_command("seed_merced_measurements")

    assert MeterReading.objects.exclude(read_by=None).count() == 0, (
        "A MeterReading names a reader. Promotion gate 2 requires core.User = 0 "
        "in the candidate; a read_by FK creates the user row rebuild-golden.sh "
        "skips ensure_superuser to avoid."
    )
    assert WaterMeasurement.objects.exclude(recorded_by=None).count() == 0, (
        "A WaterMeasurement names a recorder. Promotion gate 2 requires "
        "core.User = 0 in the candidate; put provenance in notes, not a user FK."
    )


@pytest.mark.django_db
def test_the_conformance_audit_has_something_to_check(demo):
    """Zero null FKs AND a non-zero total — both, or the pass means nothing.

    An empty table also reports zero nulls. That vacuous pass — green because it
    is empty, the worst shape a gate can take — is the failure this half of the
    phase exists to end, so asserting the null count alone would re-create it.
    """
    call_command("seed_merced_measurements")

    total = (
        MeterReading.objects.count()
        + SensorMeasurement.objects.count()
        + WaterMeasurement.objects.count()
    )
    nulls = (
        MeterReading.objects.filter(observed_property__isnull=True).count()
        + SensorMeasurement.objects.filter(observed_property__isnull=True).count()
        + WaterMeasurement.objects.filter(observed_property__isnull=True).count()
    )
    assert total > 0, (
        "check_conformance has no measurements to examine. A zero-row table "
        "reports zero null FKs and the gate passes green because it is empty — "
        "which is precisely the defect this command was written to end."
    )
    assert nulls == 0, f"{nulls} of {total} measurements name no observed property"


@pytest.mark.django_db
def test_the_accounting_spine_does_not_move(demo):
    """measurements.MeterReading is NOT what the engine reads.

    The accounting engine reads ``ParcelLedger`` rows of source type
    ``meter_reading`` — a different thing with nearly the same name. This command
    reads that ledger and writes to five instrument tables only.
    """
    before_ledger = ParcelLedger.objects.count()
    before_diversions = DiversionRecord.objects.count()
    assert before_ledger > 0 and before_diversions > 0

    call_command("seed_merced_measurements")

    assert ParcelLedger.objects.count() == before_ledger
    assert DiversionRecord.objects.count() == before_diversions


@pytest.mark.django_db
def test_the_totalizer_reconciles_to_the_ledger(demo):
    """Each month's delta equals that well's metered groundwater for the month.

    A water master will read the well's meter against its parcel's metered
    groundwater. Disagreement there is a worse defect than an empty table.
    """
    call_command("seed_merced_measurements")

    parcel_ids = list(
        WellIrrigatedParcel.objects.filter(well=demo["well"]).values_list(
            "parcel_id", flat=True
        )
    )
    readings = list(
        MeterReading.objects.filter(meter=demo["meter"]).order_by("reading_date")
    )
    assert len(readings) == 12, "one read a month across the water year"

    for reading in readings:
        read_on = reading.reading_date.date()
        first = read_on.replace(day=1)
        ledger = ParcelLedger.objects.filter(
            parcel_id__in=parcel_ids,
            source_type="meter_reading",
            effective_date__gte=first,
            effective_date__lte=read_on,
        ).aggregate(total=Sum("amount_acre_feet"))["total"] or Decimal("0")
        assert reading.calculated_volume == abs(ledger), (
            f"{read_on:%B %Y}: the meter read {reading.calculated_volume} AF and "
            f"the ledger holds {abs(ledger)} AF for the same well-month"
        )
        # A totalizer counts up and is never reset.
        assert reading.current_value - reading.previous_value == reading.calculated_volume

    values = [r.current_value for r in readings]
    assert values == sorted(values), "the totalizer went backwards"


@pytest.mark.django_db
def test_logger_cadence_follows_the_wells_own_declaration(demo):
    """A sensor logs at the interval its well declares, and never faster.

    PROJECT.md puts real-time telemetry out of scope. The guard is not "daily" as
    a constant — it is that the interval is read off ``MonitoringWell
    .measurement_frequency``, so changing the declaration is the only way to
    change the cadence.
    """
    from core.management.commands.seed_merced_measurements import FREQUENCY_DAYS

    call_command("seed_merced_measurements")

    assert Sensor.objects.exists()
    for sensor in Sensor.objects.select_related("well"):
        monitoring = MonitoringWell.objects.get(well=sensor.well)
        expected = FREQUENCY_DAYS[monitoring.measurement_frequency]
        dates = sorted(
            {
                m.measurement_date.date()
                for m in SensorMeasurement.objects.filter(sensor=sensor)
            }
        )
        intervals = {
            (dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)
        }
        assert intervals == {expected}, (
            f"{sensor.name} logs every {sorted(intervals)} day(s) but its well "
            f"declares {monitoring.measurement_frequency!r} "
            f"({expected} day(s)). A cadence not derived from the well's own "
            f"declaration is how streaming telemetry gets in."
        )

    # A sensor only ever goes on a well whose declaration earns one.
    for sensor in Sensor.objects.select_related("well"):
        assert MonitoringWell.objects.filter(well=sensor.well).exists()


@pytest.mark.django_db
def test_field_readings_shadow_the_logger_without_matching_it(demo):
    """The manual check disagrees with the instrument by a little, on purpose.

    A steel tape and a pressure transducer never agree exactly, and that small
    disagreement is what a ``quality`` flag exists to carry. Identical numbers
    would be the tell that one of them was copied from the other.
    """
    call_command("seed_merced_measurements")

    sensor = Sensor.objects.select_related("well").first()
    checks = WaterMeasurement.objects.filter(well=sensor.well)
    assert checks.exists(), "the logger well has no hand check against it"

    compared = 0
    for check in checks:
        logged = SensorMeasurement.objects.filter(
            sensor=sensor, measurement_date__date=check.measurement_date.date()
        ).first()
        if logged is None:
            continue
        gap = abs(check.value - logged.value)
        assert gap != 0, "the hand check copied the logger exactly"
        assert gap < Decimal("0.25"), (
            f"tape and transducer differ by {gap} ft on "
            f"{check.measurement_date:%Y-%m-%d} — that is a fault, not a reading"
        )
        compared += 1
    assert compared > 0


@pytest.mark.django_db
def test_a_totalizer_read_names_the_volume_it_measures(demo):
    """The concept a meter reads had no word in the vocabulary until this phase.

    ``reservoir_storage`` carries the right UCUM atom and entirely the wrong
    concept, so every read would either have been mislabelled or left with a null
    FK past the conformance audit.
    """
    call_command("seed_merced_measurements")

    extracted = ObservedProperty.objects.get(key="extracted_volume")
    assert extracted.ucum_unit == "[acr_us].[ft_i]"
    assert extracted.usgs_pcode == "", (
        "extracted_volume must keep a blank USGS pcode — the documented "
        "non-blocking exception (decision 31-01), not an oversight to fill in"
    )
    assert MeterReading.objects.exclude(observed_property=extracted).count() == 0


@pytest.mark.django_db
def test_every_basin_gets_readings_that_differ_from_its_neighbours(demo):
    """A uniform grid across seven basins is the tell that stops a reader trusting
    the map. The card sits beside the event history on the same page."""
    call_command("seed_merced_measurements")

    depths = list(
        RechargeMeasurement.objects.filter(measurement_type="water_level")
        .values_list("recharge_site__name", "value")
    )
    assert depths
    by_site = {}
    for name, value in depths:
        by_site.setdefault(name, set()).add(value)
    assert len(by_site) == 2, "both seeded basins carry readings"
    # Every basin reads differently, and within a basin the fills differ too.
    assert len({frozenset(v) for v in by_site.values()}) == 2
    for name, values in by_site.items():
        assert len(values) > 1, f"{name} ponded to exactly one depth all season"
