# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Tests for the OpenET pre-fill service (reporting.services.build_openet_prefill).

These lock the three properties that keep the pre-fill honest:
  1. Raw ET — returned values sum to the et_estimate ledger totals, with no
     scaling and no precip/delivery subtraction.
  2. Provenance — every value object carries the exact "not metered pumping" label.
  3. Read-only — the service never writes to ParcelLedger.
Plus the multi-parcel well normalization (no double-count), reusing the SAME
shared map the GEARS by-well CSV uses.
"""

import re
from datetime import date
from decimal import Decimal

import pytest
from django.urls import reverse

from parcels.models import ParcelLedger
from reporting.generators import build_normalized_well_parcel_map
from reporting.models import ReportSubmission, ReportTemplate
from reporting.services import OPENET_PREFILL_LABEL, build_openet_prefill
from tests.factories import (
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)

# The literal is hardcoded here (not referenced via the constant) on purpose:
# this is the user-facing string that keeps the perjury certification honest, so
# the test must fail if anyone edits either the constant or the rendered value.
EXPECTED_LABEL = "OpenET consumptive-use estimate — not metered pumping"


def _et_entry(parcel, month, af):
    """An et_estimate ledger entry: stored negative, like sync_openet_to_ledger writes."""
    return ParcelLedgerFactory(
        parcel=parcel,
        source_type="et_estimate",
        amount_acre_feet=Decimal(af),
        effective_date=date(2024, month, 1),
        transaction_date=date(2024, month, 1),
    )


def test_by_parcel_sums_match_ledger_totals_raw():
    """Returned values sum to the et_estimate totals — no scaling, no subtraction."""
    period = ReportingPeriodFactory()
    p1 = ParcelFactory()
    p2 = ParcelFactory()
    _et_entry(p1, 1, "-10.0000")
    _et_entry(p1, 2, "-5.5000")
    _et_entry(p2, 3, "-7.2500")
    # Noise that must be excluded: a non-ET source, and an ET entry before the period.
    ParcelLedgerFactory(
        parcel=p1, source_type="meter_reading",
        amount_acre_feet=Decimal("-100"), effective_date=date(2024, 1, 1),
    )
    ParcelLedgerFactory(
        parcel=p2, source_type="et_estimate",
        amount_acre_feet=Decimal("-99"), effective_date=date(2022, 1, 1),
    )

    result = build_openet_prefill(period, "by_parcel")
    total = sum(mv["value_af"] for e in result["entities"] for mv in e["months"])

    # 10 + 5.5 + 7.25 = 22.75 (raw abs of in-period et_estimate only)
    assert total == Decimal("22.75")


def test_every_value_carries_exact_provenance_label():
    period = ReportingPeriodFactory()
    parcel = ParcelFactory()
    _et_entry(parcel, 1, "-3.0000")

    result = build_openet_prefill(period, "by_parcel")
    assert result["label"] == EXPECTED_LABEL
    assert OPENET_PREFILL_LABEL == EXPECTED_LABEL

    values = [mv for e in result["entities"] for mv in e["months"]]
    assert values, "expected at least one pre-filled value"
    for mv in values:
        assert mv["label"] == EXPECTED_LABEL
        assert mv["source"] == "openet"
        assert mv["editable"] is True


def test_multi_parcel_well_fraction_normalized_no_double_count():
    """A well irrigating two parcels (each fraction 1.0) must not sum both raw."""
    period = ReportingPeriodFactory()
    well = WellFactory()
    p1 = ParcelFactory()
    p2 = ParcelFactory()
    WellIrrigatedParcelFactory(well=well, parcel=p1, fraction=Decimal("1.0000"))
    WellIrrigatedParcelFactory(well=well, parcel=p2, fraction=Decimal("1.0000"))
    _et_entry(p1, 1, "-12.0000")
    _et_entry(p2, 1, "-12.0000")

    result = build_openet_prefill(period, "by_well")
    assert len(result["entities"]) == 1
    months = result["entities"][0]["months"]
    assert len(months) == 1
    jan = months[0]

    # Normalized: each parcel contributes 0.5 → 0.5*12 + 0.5*12 = 12, NOT 24.
    assert jan["value_af"] == Decimal("12")

    # And it is exactly the shared map generate_gears_csv uses — never drifts apart.
    well_parcel_map = build_normalized_well_parcel_map()
    frac_p1 = dict((w.pk, f) for w, f in well_parcel_map[p1.pk])[well.pk]
    frac_p2 = dict((w.pk, f) for w, f in well_parcel_map[p2.pk])[well.pk]
    assert jan["value_af"] == Decimal("12") * frac_p1 + Decimal("12") * frac_p2


def test_calwatrs_attributes_et_to_pods_via_parcel_fraction():
    period = ReportingPeriodFactory()
    parcel = ParcelFactory()
    pod = PointOfDiversionFactory()
    PointOfDiversionParcelFactory(
        point_of_diversion=pod, parcel=parcel, fraction=Decimal("1.0000")
    )
    _et_entry(parcel, 1, "-15.0000")

    result = build_openet_prefill(period, "calwatrs")
    assert result["method"] == "calwatrs"
    assert len(result["entities"]) == 1
    entity = result["entities"][0]
    assert entity["entity_type"] == "pod"
    assert entity["months"][0]["value_af"] == Decimal("15")
    assert entity["months"][0]["label"] == EXPECTED_LABEL


def test_service_performs_zero_ledger_writes():
    period = ReportingPeriodFactory()
    parcel = ParcelFactory()
    _et_entry(parcel, 1, "-8.0000")

    before = ParcelLedger.objects.count()
    build_openet_prefill(period, "by_well")
    build_openet_prefill(period, "by_parcel")
    build_openet_prefill(period, "calwatrs")
    after = ParcelLedger.objects.count()

    assert after == before


def test_unknown_method_raises():
    period = ReportingPeriodFactory()
    with pytest.raises(ValueError):
        build_openet_prefill(period, "not_a_method")


def _gears_submission_with_et(month_values):
    """A draft gears_by_well submission whose single well has et_estimate data."""
    period = ReportingPeriodFactory()
    well = WellFactory()
    parcel = ParcelFactory()
    WellIrrigatedParcelFactory(well=well, parcel=parcel, fraction=Decimal("1.0000"))
    for month, af in month_values:
        _et_entry(parcel, month, af)
    template, _ = ReportTemplate.objects.get_or_create(
        report_type="gears_by_well", defaults={"name": "GEARS by Well"}
    )
    return ReportSubmission.objects.create(
        report_template=template, reporting_period=period, status="draft"
    )


def test_prefill_post_persists_only_genuine_edits(client, django_user_model):
    """Saving the whole form must flag ONLY values the user actually changed.

    Regression guard: the form re-posts every input on each save, so persisting
    every submitted value would mark all of them 'modified' — defeating the
    raw-OpenET vs user-edited distinction the feature exists to preserve.
    """
    submission = _gears_submission_with_et(
        [(1, "-12.0000"), (2, "-8.0000"), (3, "-4.0000")]
    )
    user = django_user_model.objects.create_user(username="prefiller", password="x")
    client.force_login(user)
    url = reverse("reporting:report_prefill", kwargs={"pk": submission.pk})

    get = client.get(url)
    assert get.status_code == 200
    html = get.content.decode()
    fields = re.findall(r'name="val:([^"]+)"\s+[^>]*value="([^"]*)"', html)
    assert fields, "expected pre-filled inputs in the rendered form"

    # Re-post every value unchanged → nothing should be recorded as an edit.
    unchanged = {f"val:{k}": v for k, v in fields}
    client.post(url, unchanged)
    submission.refresh_from_db()
    assert submission.prefill_overrides == {}

    # Change exactly one value → only that one is persisted as an override.
    edited_key = fields[0][0]
    payload = dict(unchanged)
    payload[f"val:{edited_key}"] = "777.77"
    client.post(url, payload)
    submission.refresh_from_db()
    assert set(submission.prefill_overrides) == {edited_key}
    assert submission.prefill_overrides[edited_key] == "777.77"
