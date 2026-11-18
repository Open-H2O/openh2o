# SPDX-License-Identifier: AGPL-3.0-or-later
"""An import skips a result already on file, whatever it carries (153.9-02).

A stored result with no lab file (no MCL, no DLR, no file date) is a result like any other:
an import that meets it counts the row in ``duplicates`` and writes nothing to it.
"""
import pytest

from drinking.models import SampleResult

# The fixture, the Le Grand file and the import helper of the limits tests.
from tests.test_limits_as_reported import LE_GRAND_ROWS, _import, le_grand  # noqa: F401

pytestmark = pytest.mark.django_db


def test_a_result_with_no_lab_file_is_skipped_and_left_as_it_was(le_grand):
    _import(source_file="first.tab")
    SampleResult.objects.update(
        mcl_as_reported=None, dlr_as_reported=None, limits_source_file="", limits_file_date=None
    )
    before = list(SampleResult.objects.order_by("pk").values_list(
        "pk", "result_value", "reporting_level", "less_than_rl", "unit",
        "mcl_as_reported", "dlr_as_reported", "limits_source_file", "limits_file_date",
    ))

    counts = _import(source_file="again.tab")

    assert counts["results"] == 0
    assert counts["duplicates"] == LE_GRAND_ROWS
    assert SampleResult.objects.count() == LE_GRAND_ROWS
    after = list(SampleResult.objects.order_by("pk").values_list(
        "pk", "result_value", "reporting_level", "less_than_rl", "unit",
        "mcl_as_reported", "dlr_as_reported", "limits_source_file", "limits_file_date",
    ))
    assert after == before
    assert not SampleResult.objects.filter(mcl_as_reported__isnull=False).exists()
    assert not SampleResult.objects.filter(dlr_as_reported__isnull=False).exists()
    assert not SampleResult.objects.filter(limits_file_date__isnull=False).exists()
