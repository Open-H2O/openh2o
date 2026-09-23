# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-04 Task 5: the ISS-140 ruling, applied.

Brent ruled **beside** at the 146-04 Task 1 checkpoint, 2026-09-22 07:31 PDT:

    Store the file's own MCL and DLR as reported and show them beside the
    finding. No colour, no comparison, no verdict word. The "prepares, never
    determines" line survives.

So the lab importer reads the state layout's ``MCL`` and ``DLR`` columns into
``SampleResult.mcl_as_reported`` / ``dlr_as_reported`` exactly as the file
carried them, records which file and on what date, and three screens show
the MCL beside the finding with the words "the laboratory's file carried".
Nothing compares the two numbers, and a finding above the file's limit
renders with exactly the markup of one below it.

The fixture ``drinking_le_grand_lab_results.tab`` is Le Grand Community
Services District's (CA2410011) own lab results as the State Water Board
publishes them: 160 rows, sampled 2025-02-25 to 2025-11-20, cut for the
six-shapes study on 2026-09-20. 79 rows carry an MCL and 71 a DLR; seven
findings sit above the MCL the file carried (six of them arsenic), which is
why the markup-parity test below uses a real above-limit row and not an
invented one.
"""
import re
from decimal import Decimal
from pathlib import Path

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from drinking import importer
from drinking.models import SampleResult, WaterSystem
from tests.factories import (
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
)

LE_GRAND = Path(__file__).parent / "fixtures" / "drinking_le_grand_lab_results.tab"
LE_GRAND_ROWS = 160
LE_GRAND_MCL_ROWS = 79
LE_GRAND_DLR_ROWS = 71


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"limits{n}")
    email = factory.Sequence(lambda n: f"limits{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    client = Client()
    client.force_login(UserFactory())
    return client


@pytest.fixture
def le_grand(db):
    """Le Grand's system, its four sampling points, and the seeded vocabulary.

    Other systems are cleared first: the views read the deployment's one
    system, and the Merced seed test leaves City of Merced behind.
    """
    WaterSystem.objects.all().delete()
    call_command("seed_drinking", verbosity=0)
    system = WaterSystemFactory(pwsid="CA2410011", name="LE GRAND COMM SERVICES DIST")
    for facility_id, codes in (
        ("002", ["CA2410011_002_002"]),
        ("005", ["CA2410011_005_005"]),
        ("DST", ["CA2410011_DST_901", "CA2410011_DST_LCR"]),
    ):
        facility = SystemFacilityFactory(system=system, facility_id=facility_id)
        for code in codes:
            SamplingPointFactory(ps_code=code, facility=facility)
    return system


def _parse():
    with LE_GRAND.open("rb") as handle:
        return importer.parse_upload(handle, LE_GRAND.name)


def _import(source_file=LE_GRAND.name):
    parsed = _parse()
    mapping = importer.auto_map_columns(parsed["columns"])
    validated = importer.validate_rows(parsed["rows"], mapping)
    return importer.commit_rows(validated, source_file=source_file)


def _arsenic_pair():
    """One arsenic finding above the MCL the file carried, and one below it.

    Found in the data rather than built, so the pair is the real thing: the
    file's own arsenic MCL is 10 UG/L and it carries findings on both sides.
    """
    arsenic = SampleResult.objects.filter(
        analyte__name__iexact="arsenic",
        mcl_as_reported__isnull=False,
        result_value__isnull=False,
    )
    above = next(r for r in arsenic if r.result_value > r.mcl_as_reported)
    below = next(r for r in arsenic if r.result_value <= r.mcl_as_reported)
    return above, below


# ---------------------------------------------------------------------------
# The importer
# ---------------------------------------------------------------------------


class TestTheImporterReadsTheLimitsAsReported:
    def test_both_columns_map_with_no_manual_assignment(self):
        mapping = importer.auto_map_columns(_parse()["columns"])
        assert mapping["mcl_as_reported"] == "MCL"
        assert mapping["dlr_as_reported"] == "DLR"

    def test_le_grand_lands_whole_with_its_limits_on_the_rows_that_carry_them(
        self, le_grand
    ):
        counts = _import()
        assert counts["results"] == LE_GRAND_ROWS
        assert counts["skipped"] == 0
        assert SampleResult.objects.filter(
            mcl_as_reported__isnull=False
        ).count() == LE_GRAND_MCL_ROWS
        assert SampleResult.objects.filter(
            mcl_as_reported__isnull=True
        ).count() == LE_GRAND_ROWS - LE_GRAND_MCL_ROWS
        assert SampleResult.objects.filter(
            dlr_as_reported__isnull=False
        ).count() == LE_GRAND_DLR_ROWS

    def test_the_value_is_stored_as_the_file_wrote_it(self, le_grand):
        _import()
        above, _below = _arsenic_pair()
        assert above.mcl_as_reported == Decimal("10")
        assert above.dlr_as_reported == Decimal("2")

    def test_each_row_says_which_file_and_when(self, le_grand):
        _import(source_file="le-grand-2025.tab")
        row = SampleResult.objects.filter(mcl_as_reported__isnull=False).first()
        assert row.limits_source_file == "le-grand-2025.tab"
        assert row.limits_file_date == timezone.localdate()

    def test_an_unreadable_limit_is_a_warning_and_stores_nothing(self, le_grand):
        parsed = _parse()
        rows = [dict(r) for r in parsed["rows"]]
        target = next(i for i, r in enumerate(rows) if r["MCL"].strip())
        rows[target]["MCL"] = "see note"
        mapping = importer.auto_map_columns(parsed["columns"])
        validated = importer.validate_rows(rows, mapping)
        assert validated[target]["errors"] == []
        assert any("MCL" in w for w in validated[target]["warnings"])
        assert validated[target]["data"]["mcl_as_reported"] is None

    def test_a_re_import_is_still_a_no_op(self, le_grand):
        """The limits are not part of a result's identity (ISS-102's guard).

        A second import on a later day, under another file name, must find
        every row already recorded rather than doubling the log because the
        provenance fields differ.
        """
        _import(source_file="first.tab")
        second = _import(source_file="second.tab")
        assert second["results"] == 0
        assert second["duplicates"] == LE_GRAND_ROWS
        assert SampleResult.objects.count() == LE_GRAND_ROWS

    def test_the_commit_view_carries_the_file_name_through(
        self, client_in, le_grand
    ):
        with LE_GRAND.open("rb") as handle:
            preview = client_in.post(reverse("drinking:import_preview"), {"file": handle})
        assert preview.context["source_file"] == LE_GRAND.name
        client_in.post(reverse("drinking:import_commit"), {
            "rows_json": preview.context["rows_json"],
            "source_file": preview.context["source_file"],
        })
        # Recorded on every row, limit or none: the date is what tells "the
        # file carried none" apart from "imported before limits were kept".
        assert SampleResult.objects.filter(
            limits_source_file=LE_GRAND.name
        ).count() == LE_GRAND_ROWS
        assert not SampleResult.objects.filter(limits_file_date__isnull=True).exists()


# ---------------------------------------------------------------------------
# The three screens
# ---------------------------------------------------------------------------


class TestTheScreensShowTheLimitBeside:
    def test_the_result_page_names_the_file_as_the_limits_source(
        self, client_in, le_grand
    ):
        _import()
        above, _below = _arsenic_pair()
        html = client_in.get(
            reverse("drinking:result_detail", args=[above.pk])
        ).content.decode()
        assert "the laboratory&#x27;s file carried" in html or (
            "the laboratory's file carried" in html
        )
        assert "Limit (file)" in html

    def test_a_row_without_a_limit_says_the_file_carried_none(
        self, client_in, le_grand
    ):
        _import()
        bare = SampleResult.objects.filter(mcl_as_reported__isnull=True).first()
        html = client_in.get(
            reverse("drinking:result_detail", args=[bare.pk])
        ).content.decode()
        assert "no limit in the file" in html

    def test_a_row_imported_before_limits_were_kept_says_not_recorded(
        self, client_in, le_grand
    ):
        """Not "no limit in the file": nobody read the file's limit for it."""
        _import()
        legacy = SampleResult.objects.filter(mcl_as_reported__isnull=True).first()
        SampleResult.objects.filter(pk=legacy.pk).update(
            limits_source_file="", limits_file_date=None
        )
        html = client_in.get(
            reverse("drinking:result_detail", args=[legacy.pk])
        ).content.decode()
        assert "no limit in the file" not in html
        assert "not recorded: imported before" in html

    def test_the_results_log_carries_the_column(self, client_in, le_grand):
        _import()
        html = client_in.get(reverse("drinking:results")).content.decode()
        assert "Limit (file)" in html

    def test_the_sampling_point_page_carries_the_column(self, client_in, le_grand):
        _import()
        above, _below = _arsenic_pair()
        html = client_in.get(
            reverse(
                "drinking:sampling_point_detail",
                args=[above.event.sampling_point_id],
            )
        ).content.decode()
        assert "Limit (file)" in html


# ---------------------------------------------------------------------------
# No comparison, no colour, no verdict
# ---------------------------------------------------------------------------

_CLASS = re.compile(r'class="([^"]*)"')
_STYLE = re.compile(r'style="([^"]*)"')


def _markup_tokens(html):
    classes = {token for attr in _CLASS.findall(html) for token in attr.split()}
    styles = set(_STYLE.findall(html))
    return classes, styles


def _row_for(html, pk):
    """The results-log ``<tr>`` that links to result ``pk``."""
    link = reverse("drinking:result_detail", args=[pk])
    for row in re.findall(r"<tr\b.*?</tr>", html, flags=re.S):
        if f'href="{link}"' in row:
            return row
    raise AssertionError(f"no row links to {link}")


class TestNoComparison:
    def test_above_and_below_render_the_same_markup_on_the_result_page(
        self, client_in, le_grand
    ):
        _import()
        above, below = _arsenic_pair()
        above_html = client_in.get(
            reverse("drinking:result_detail", args=[above.pk])
        ).content.decode()
        below_html = client_in.get(
            reverse("drinking:result_detail", args=[below.pk])
        ).content.decode()
        above_classes, above_styles = _markup_tokens(above_html)
        below_classes, below_styles = _markup_tokens(below_html)
        assert above_classes - below_classes == set()
        assert above_styles - below_styles == set()

    def test_above_and_below_render_the_same_markup_in_the_log(
        self, client_in, le_grand
    ):
        _import()
        above, below = _arsenic_pair()
        html = client_in.get(
            reverse("drinking:results") + f"?analyte={above.analyte_id}"
        ).content.decode()
        above_classes, above_styles = _markup_tokens(_row_for(html, above.pk))
        below_classes, below_styles = _markup_tokens(_row_for(html, below.pk))
        assert above_classes == below_classes
        assert above_styles == below_styles

    def test_no_screen_says_a_verdict_word(self, client_in, le_grand):
        _import()
        above, _below = _arsenic_pair()
        for url in (
            reverse("drinking:result_detail", args=[above.pk]),
            reverse("drinking:results"),
            reverse("drinking:sampling_point_detail", args=[above.event.sampling_point_id]),
        ):
            lowered = client_in.get(url).content.decode().lower()
            for word in ("exceed", "violation", "non-compliant", "compliant",
                         "above the limit", "over the limit"):
                assert word not in lowered, (url, word)
