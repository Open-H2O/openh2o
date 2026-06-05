# SPDX-License-Identifier: AGPL-3.0-or-later
"""State-export defensibility (Phase 45 Plan 02).

These exports ARE the filing a GSA hands the Water Board, so every figure that
leaves the system must be defensible. Each test below locks one Phase 44 audit
finding:

  ISS-027  GEARS by-well must never SILENTLY drop a metered extraction whose
           parcel has no well link — it emits a marked, visible row instead.
  ISS-028  CalWATRS POD→parcel fractions normalize to 1.0, so the common
           un-edited two-parcels-at-1.0 case reports the diversion ONCE, not 2x;
           a populated POD whose fractions sum ≠ 1.0 raises a warning.
  ISS-031b A blank Water Right ID row is structurally invalid to the portal —
           it is withheld from the CSV and surfaced as a warning naming the POD.
  ISS-031c A null parcel acreage is reported as a blank Area cell, never a
           misleading literal 0 beside a real ET volume.

Rows live in reporting.generators; the operator-facing warnings live in
reporting.validators.validate_report (the existing validation_warnings channel
the report view + command already save onto every ReportSubmission).
"""

import csv
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client

from core.models import SiteConfig
from reporting.generators import generate_calwatrs_csv, generate_gears_csv
from reporting.models import ReportSubmission, ReportTemplate
from reporting.validators import validate_report
from tests.factories import (
    DiversionRecordFactory,
    ParcelFactory,
    ParcelLedgerFactory,
    PointOfDiversionFactory,
    PointOfDiversionParcelFactory,
    ReportingPeriodFactory,
    WaterRightFactory,
    WellFactory,
    WellIrrigatedParcelFactory,
)


def _period():
    return ReportingPeriodFactory(
        start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)
    )


def _data_rows(content):
    """All non-empty CSV rows after the header."""
    rows = list(csv.reader(content.splitlines()))
    return [r for r in rows[1:] if r]


# ---------------------------------------------------------------------------
# ISS-027 — GEARS by-well never silently drops metered extraction
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGearsOrphanMeteredParcel:
    def test_metered_parcel_with_no_well_link_is_surfaced_not_dropped(self):
        """A metered ParcelLedger entry on a parcel with NO WellIrrigatedParcel
        link must still appear in the GEARS by-well CSV — marked, never dropped."""
        period = _period()
        parcel = ParcelFactory()  # deliberately NO WellIrrigatedParcel
        ParcelLedgerFactory(
            parcel=parcel,
            source_type="meter_reading",
            effective_date=date(2024, 6, 15),
            amount_acre_feet=Decimal("-30.0000"),
        )

        rows = _data_rows(generate_gears_csv(period, method="by_well").read())

        # Today (unfixed): well_parcel_map.get(parcel_id, []) → [] → zero rows.
        assert len(rows) == 1, "metered volume was silently dropped"
        row = rows[0]
        # Columns: reg_id, name, lat, lon, month, volume, method
        assert Decimal(row[5]) == Decimal("30"), "full metered volume must survive"
        assert "[INCOMPLETE]" in row[1], "row must be marked incomplete"
        assert parcel.parcel_number in row[1], "row must be keyed to the parcel"

    def test_validate_report_warns_on_metered_parcel_with_no_well_link(self):
        period = _period()
        parcel = ParcelFactory()
        ParcelLedgerFactory(
            parcel=parcel,
            source_type="meter_reading",
            effective_date=date(2024, 6, 15),
            amount_acre_feet=Decimal("-30.0000"),
        )

        messages = " ".join(
            w["message"] for w in validate_report(period, "gears_by_well")
        )
        assert "no well link" in messages.lower()


# ---------------------------------------------------------------------------
# ISS-028 — CalWATRS POD fractions normalize to 1.0
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCalwatrsPodNormalization:
    def test_two_parcels_at_default_fraction_do_not_double_diversion(self):
        """A POD with two parcels both at the un-edited default fraction=1.0 must
        report its diversion ONCE (split 0.5/0.5), not twice."""
        period = _period()
        pod = PointOfDiversionFactory(water_right=WaterRightFactory())
        PointOfDiversionParcelFactory(
            point_of_diversion=pod, parcel=ParcelFactory(), fraction=Decimal("1.0000")
        )
        PointOfDiversionParcelFactory(
            point_of_diversion=pod, parcel=ParcelFactory(), fraction=Decimal("1.0000")
        )
        DiversionRecordFactory(
            point_of_diversion=pod,
            reporting_period=period,
            month=date(2024, 3, 1),
            volume_acre_feet=Decimal("40.0000"),
            diversion_type="direct_use",
        )

        rows = _data_rows(generate_calwatrs_csv(period, template_type="a1").read())
        # Volume column index 7. Sum across both parcel rows must equal the
        # diversion once (40), not 2x (80, the un-normalized bug).
        total = sum(Decimal(r[7]) for r in rows)
        assert total == Decimal("40")

    def test_single_parcel_full_fraction_reports_full_volume(self):
        """Regression guard: one parcel at 1.0 still reports the whole volume."""
        period = _period()
        pod = PointOfDiversionFactory(water_right=WaterRightFactory())
        PointOfDiversionParcelFactory(
            point_of_diversion=pod, parcel=ParcelFactory(), fraction=Decimal("1.0000")
        )
        DiversionRecordFactory(
            point_of_diversion=pod,
            reporting_period=period,
            month=date(2024, 3, 1),
            volume_acre_feet=Decimal("40.0000"),
            diversion_type="direct_use",
        )

        rows = _data_rows(generate_calwatrs_csv(period, template_type="a1").read())
        assert sum(Decimal(r[7]) for r in rows) == Decimal("40")

    def test_validate_report_warns_when_pod_fractions_do_not_sum_to_one(self):
        """A POD with a HAND-SET split that doesn't add up to 100% (here a single
        parcel at 0.5 — off the 1.0 sentinel) raises a warning. Phase 56 reconciled
        this so untouched defaults stay silent but a real data-entry slip warns."""
        period = _period()
        pod = PointOfDiversionFactory(water_right=WaterRightFactory())
        PointOfDiversionParcelFactory(
            point_of_diversion=pod, parcel=ParcelFactory(), fraction=Decimal("0.5000")
        )
        DiversionRecordFactory(
            point_of_diversion=pod,
            reporting_period=period,
            month=date(2024, 3, 1),
            volume_acre_feet=Decimal("40.0000"),
            diversion_type="direct_use",
        )

        messages = " ".join(
            w["message"] for w in validate_report(period, "calwatrs_a1")
        )
        assert "doesn't add up to 100%" in messages


# ---------------------------------------------------------------------------
# ISS-031b — blank Water Right ID rows withheld + warned
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCalwatrsBlankRightId:
    def test_blank_water_right_row_is_withheld_from_csv(self):
        """A POD with no water right yields a blank Water Right ID — a key the
        portal rejects/orphans. No data row may be written for it."""
        period = _period()
        pod = PointOfDiversionFactory(water_right=None)
        DiversionRecordFactory(
            point_of_diversion=pod,
            reporting_period=period,
            month=date(2024, 3, 1),
            volume_acre_feet=Decimal("25.0000"),
            diversion_type="direct_use",
        )

        rows = _data_rows(generate_calwatrs_csv(period, template_type="a1").read())
        assert rows == [], "blank-key row must not be emitted"

    def test_validate_report_warns_naming_the_pod(self):
        period = _period()
        pod = PointOfDiversionFactory(water_right=None, name="Orphan POD Echo")
        DiversionRecordFactory(
            point_of_diversion=pod,
            reporting_period=period,
            month=date(2024, 3, 1),
            volume_acre_feet=Decimal("25.0000"),
            diversion_type="direct_use",
        )

        messages = " ".join(
            w["message"] for w in validate_report(period, "calwatrs_a1")
        )
        assert "Orphan POD Echo" in messages


# ---------------------------------------------------------------------------
# ISS-031c — no literal 0 acres beside a real ET volume
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGearsByEtNullArea:
    def test_null_area_is_blank_not_zero_beside_et(self):
        """A parcel with null area_acres and a nonzero ET volume must NOT emit a
        literal 0 in the Area column — a blank cell, not a fabricated acreage."""
        period = _period()
        parcel = ParcelFactory(area_acres=None, geometry=None)
        ParcelLedgerFactory(
            parcel=parcel,
            source_type="et_estimate",
            effective_date=date(2024, 6, 15),
            amount_acre_feet=Decimal("-12.0000"),
        )

        rows = _data_rows(generate_gears_csv(period, method="by_et").read())
        assert len(rows) == 1
        row = rows[0]
        # Columns: Parcel Number, Area, Month, ET Volume (AF), Measurement Method
        assert Decimal(row[3]) == Decimal("12"), "ET volume must be real and nonzero"
        assert row[1] != "0", "must not fabricate 0 acres beside a real ET volume"
        assert row[1] == "", "null area is reported as a blank Area cell"

    def test_validate_report_warns_on_null_area_parcel_with_et(self):
        period = _period()
        parcel = ParcelFactory(area_acres=None, geometry=None)
        ParcelLedgerFactory(
            parcel=parcel,
            source_type="et_estimate",
            effective_date=date(2024, 6, 15),
            amount_acre_feet=Decimal("-12.0000"),
        )

        messages = " ".join(
            w["message"] for w in validate_report(period, "gears_by_et")
        )
        assert "acreage" in messages.lower()
        assert parcel.parcel_number in messages


# ---------------------------------------------------------------------------
# ISS-047a — GEARS measurement-method crosswalk to the state vocabulary
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestGearsMeasurementMethodVocab:
    """The "Measurement Method" column must emit the GEARS controlled value
    ("Metered" / "Unmetered/Estimated"), never our internal source_type code.
    State vocabulary confirmed from an Accepted GEARS report (WY2018), which
    prints "Unmetered/Estimated"; the fee schedule splits metered vs unmetered.
    """

    def test_by_well_metered_emits_metered_label(self):
        period = _period()
        parcel = ParcelFactory()
        well = WellFactory()
        WellIrrigatedParcelFactory(
            well=well, parcel=parcel, fraction=Decimal("1.0000")
        )
        ParcelLedgerFactory(
            parcel=parcel,
            source_type="meter_reading",
            effective_date=date(2024, 6, 15),
            amount_acre_feet=Decimal("-30.0000"),
        )

        rows = _data_rows(generate_gears_csv(period, method="by_well").read())
        assert len(rows) == 1
        # Columns: reg_id, name, lat, lon, month, volume, method
        assert rows[0][6] == "Metered"
        assert "meter_reading" not in rows[0][6]

    def test_by_et_estimate_emits_unmetered_label(self):
        period = _period()
        ParcelLedgerFactory(
            parcel=ParcelFactory(area_acres=Decimal("10.0")),
            source_type="et_estimate",
            effective_date=date(2024, 6, 15),
            amount_acre_feet=Decimal("-12.0000"),
        )

        rows = _data_rows(generate_gears_csv(period, method="by_et").read())
        assert len(rows) == 1
        # Columns: Parcel Number, Area, Month, ET Volume (AF), Measurement Method
        assert rows[0][4] == "Unmetered/Estimated"
        assert rows[0][4] not in ("et_estimate", "calculated")

    def test_by_et_calculated_emits_unmetered_label(self):
        period = _period()
        ParcelLedgerFactory(
            parcel=ParcelFactory(area_acres=Decimal("10.0")),
            source_type="calculated",
            effective_date=date(2024, 6, 15),
            amount_acre_feet=Decimal("-12.0000"),
        )

        rows = _data_rows(generate_gears_csv(period, method="by_et").read())
        assert len(rows) == 1
        assert rows[0][4] == "Unmetered/Estimated"
        assert rows[0][4] not in ("et_estimate", "calculated")


# ---------------------------------------------------------------------------
# Phase 53-02 — Demonstration framing (flag-gated, default-off)
# ---------------------------------------------------------------------------

DEMO_BANNER = "DEMONSTRATION — NOT SUBMITTABLE"
DEMO_FILE_PREFIX = "DEMONSTRATION-NOT-SUBMITTABLE"


def _login():
    """A logged-in client (the report views require authentication)."""
    from core.models import User

    user = User.objects.create(
        username="reporter",
        email="reporter@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _gears_template():
    return ReportTemplate.objects.create(
        name="GEARS by ET", report_type="gears_by_et", is_active=True,
    )


def _et_period_with_activity():
    """A period plus one et_estimate ledger row so the generated CSV is non-empty."""
    period = _period()
    ParcelLedgerFactory(
        parcel=ParcelFactory(area_acres=Decimal("10.0")),
        source_type="et_estimate",
        effective_date=date(2024, 6, 15),
        amount_acre_feet=Decimal("-12.0000"),
    )
    return period


@pytest.mark.django_db
class TestDemonstrationFramingFile:
    """The generated/stored filename carries the demo stamp iff demonstration_mode
    is on. The prefix is the format-safe disclaimer that survives download (a
    leading '#' CSV row could corrupt a strict GEARS/CalWATRS parser)."""

    def _generate(self):
        client = _login()
        template = _gears_template()
        period = _et_period_with_activity()
        resp = client.post(
            "/reporting/reports/generate/",
            {"report_template": template.pk, "reporting_period": period.pk},
        )
        # On success the view redirects to the detail page.
        assert resp.status_code == 302
        return ReportSubmission.objects.latest("created_at")

    def test_filename_stamped_when_demo_mode_on(self):
        SiteConfig.objects.create(agency_name="Demo GSA", demonstration_mode=True)
        submission = self._generate()
        assert DEMO_FILE_PREFIX in submission.generated_file

    def test_filename_clean_when_demo_mode_off(self):
        SiteConfig.objects.create(agency_name="Real GSA", demonstration_mode=False)
        submission = self._generate()
        assert DEMO_FILE_PREFIX not in submission.generated_file

    def test_filename_clean_when_no_site_config(self):
        # A bare install with no SiteConfig must not stamp filings.
        submission = self._generate()
        assert DEMO_FILE_PREFIX not in submission.generated_file


@pytest.mark.django_db
class TestDemonstrationFramingScreens:
    """The loud demo banner renders on both report surfaces iff demonstration_mode
    is on (the context processor injects site_config into every template)."""

    def test_generate_screen_shows_banner_when_demo_mode_on(self):
        SiteConfig.objects.create(agency_name="Demo GSA", demonstration_mode=True)
        client = _login()
        resp = client.get("/reporting/reports/generate/")
        assert resp.status_code == 200
        assert DEMO_BANNER in resp.content.decode()

    def test_generate_screen_hides_banner_when_demo_mode_off(self):
        SiteConfig.objects.create(agency_name="Real GSA", demonstration_mode=False)
        client = _login()
        resp = client.get("/reporting/reports/generate/")
        assert resp.status_code == 200
        assert DEMO_BANNER not in resp.content.decode()

    def _make_submission(self):
        template = _gears_template()
        period = _period()
        return ReportSubmission.objects.create(
            report_template=template,
            reporting_period=period,
            status="draft",
        )

    def test_detail_screen_shows_banner_when_demo_mode_on(self):
        SiteConfig.objects.create(agency_name="Demo GSA", demonstration_mode=True)
        submission = self._make_submission()
        client = _login()
        resp = client.get(f"/reporting/reports/{submission.pk}/")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert DEMO_BANNER in body
        # The existing "who files" gold-box disclaimer must remain intact.
        assert "OpenH2O prepares your filing." in body

    def test_detail_screen_hides_banner_when_demo_mode_off(self):
        SiteConfig.objects.create(agency_name="Real GSA", demonstration_mode=False)
        submission = self._make_submission()
        client = _login()
        resp = client.get(f"/reporting/reports/{submission.pk}/")
        assert resp.status_code == 200
        body = resp.content.decode()
        assert DEMO_BANNER not in body
        assert "OpenH2O prepares your filing." in body
