# SPDX-License-Identifier: AGPL-3.0-or-later
"""143-12, R-084 / R-085 / R-087 / R-088 / R-093: the reports pages explain
themselves instead of repeating themselves or leaving a blocker unfixable.

R-084/R-085: the shared-supply card says it is a check, not a filing, and a
search box no longer renders over an empty history.
R-087/R-088: the download link (the one thing the report page produces) is
the page's one primary action, on the title line, and the report's type and
period print once in the head rather than three times before any figure.
R-093: the worksheet's two blockers link to the record the reader must go
fix, rather than naming it and leaving them to find it themselves.

Report, template, well and parcel identities here are fictional (`Probe ...`);
the two draft submissions the platform already seeds (pks 3/4) are never
touched or relied on.
"""
from datetime import date
from decimal import Decimal

import pytest
from django.contrib.gis.geos import Point
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from core.models import User
from reporting.models import ReportSubmission, ReportTemplate
from tests.factories import ReportingPeriodFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def auth_client():
    user = User.objects.create(
        username="r084-reader", email="r084-reader@example.com", is_active=True
    )
    client = Client()
    client.force_login(user)
    return client


class TestReportsPageEmptyHistoryHidesItsToolbar:
    def test_the_shared_supply_card_says_it_is_a_check(self, auth_client):
        resp = auth_client.get(reverse("reporting:report_list"))
        body = resp.content.decode()
        assert resp.status_code == 200
        assert "A check, not a filing" in body

    def test_no_rows_renders_no_toolbar(self, auth_client):
        resp = auth_client.get(reverse("reporting:report_list"))
        body = resp.content.decode()
        assert "toolbar-row" not in body
        assert "No reports yet" in body

    def test_one_row_renders_the_toolbar_and_a_head_naming_the_families(
        self, auth_client
    ):
        template, _ = ReportTemplate.objects.get_or_create(
            report_type="gears_by_well", defaults={"name": "Probe GEARS Template"}
        )
        ReportSubmission.objects.create(
            report_template=template, reporting_period=ReportingPeriodFactory(),
            status="draft",
        )
        resp = auth_client.get(reverse("reporting:report_list"))
        body = resp.content.decode()
        assert "toolbar-row" in body
        assert "1 report: 1 GEARS, 0 CalWATRS" in body
        assert "Not generated" in body


class TestReportPageLeadsWithItsDownload:
    def test_a_submission_with_a_file_shows_one_download_button_on_the_title_line(
        self, auth_client
    ):
        template, _ = ReportTemplate.objects.get_or_create(
            report_type="gears_by_well", defaults={"name": "Probe Download Template"}
        )
        sub = ReportSubmission.objects.create(
            report_template=template, reporting_period=ReportingPeriodFactory(),
            status="draft", generated_file="reports/probe-report.csv",
            generated_at=timezone.now(),
        )
        resp = auth_client.get(reverse("reporting:report_detail", args=[sub.pk]))
        body = resp.content.decode()
        assert resp.status_code == 200
        actions = body.split('class="page-head-actions"')[1].split("</div>", 1)[0]
        assert actions.count('class="btn-primary"') == 1
        assert "Download CSV" in actions
        assert reverse("reporting:report_download", args=[sub.pk]) in actions
        # The template name printed three times before this plan (the
        # breadcrumb, the pane-header title and subtitle standing in for the
        # crumb row, and the metadata card's first field) and now prints only
        # where the head itself says it once: the <title> tag, the page's h1
        # and the breadcrumb's current-page span.
        assert body.count(template.name) == 3

    def test_a_submission_with_no_file_shows_no_download_button(self, auth_client):
        template, _ = ReportTemplate.objects.get_or_create(
            report_type="gears_by_well", defaults={"name": "Probe No-File Template"}
        )
        sub = ReportSubmission.objects.create(
            report_template=template, reporting_period=ReportingPeriodFactory(),
            status="draft",
        )
        resp = auth_client.get(reverse("reporting:report_detail", args=[sub.pk]))
        body = resp.content.decode()
        actions = body.split('class="page-head-actions"')[1].split("</div>", 1)[0]
        assert actions.count('class="btn-primary"') == 0
        assert "No file yet" in body
        assert "Not generated" in body


class TestWorksheetBlockersLinkToTheFix:
    def test_no_linked_water_right_links_to_the_point_of_diversion(self, auth_client):
        from surface.models import DiversionRecord, PointOfDiversion

        template, _ = ReportTemplate.objects.get_or_create(
            report_type="calwatrs_a2", defaults={"name": "Probe CalWATRS Template"}
        )
        period = ReportingPeriodFactory()
        sub = ReportSubmission.objects.create(
            report_template=template, reporting_period=period, status="draft",
        )
        pod = PointOfDiversion.objects.create(
            name="Probe Unlinked POD", location=Point(-120.0, 37.0),
        )
        DiversionRecord.objects.create(
            point_of_diversion=pod, reporting_period=period,
            diversion_type="to_storage", month=date(2025, 1, 1),
            volume_acre_feet=Decimal("1.0"),
        )
        resp = auth_client.get(reverse("reporting:calwatrs_worksheet", args=[sub.pk]))
        body = resp.content.decode()
        assert resp.status_code == 200
        assert "No linked water right" in body
        assert (
            f'<a class="text-link" href="{reverse("surface:pod_detail", args=[pod.pk])}">'
            "the point of diversion</a>" in body
        )

    def test_a_right_with_no_pin_links_to_the_water_right(self, auth_client):
        from surface.models import DiversionRecord, PointOfDiversion, WaterRight, WaterRightType

        template, _ = ReportTemplate.objects.get_or_create(
            report_type="calwatrs_a2", defaults={"name": "Probe CalWATRS Template Two"}
        )
        period = ReportingPeriodFactory()
        sub = ReportSubmission.objects.create(
            report_template=template, reporting_period=period, status="draft",
        )
        right_type = WaterRightType.objects.create(name="Probe Right Type", code="PROBE")
        wr = WaterRight.objects.create(
            right_id="PROBE-WR-93", holder_name="Probe Holder", right_type=right_type,
            calwatrs_pin="",
        )
        pod = PointOfDiversion.objects.create(
            name="Probe No-Pin POD", location=Point(-120.0, 37.0), water_right=wr,
        )
        DiversionRecord.objects.create(
            point_of_diversion=pod, reporting_period=period,
            diversion_type="to_storage", month=date(2025, 1, 1),
            volume_acre_feet=Decimal("1.0"),
        )
        resp = auth_client.get(reverse("reporting:calwatrs_worksheet", args=[sub.pk]))
        body = resp.content.decode()
        assert "Add this right's PIN on" in body
        assert (
            f'<a class="text-link" href="{reverse("surface:detail", args=[wr.pk])}">'
            "the water right</a>" in body
        )
