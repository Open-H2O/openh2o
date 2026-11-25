# SPDX-License-Identifier: AGPL-3.0-or-later
"""Removing the demonstration when a switched-off section still holds rows.

A section that is switched off leaves the app list, so the removal does not see its tables; their rows
stay in the database and still point at demonstration records. The removal refuses with a sentence and
removes nothing, rather than stopping on the database's error.
"""
import pytest

from accounting.models import ReportingPeriod
from core import demonstration as demo
from tests import factories as f
from tests.test_demonstration_06 import _hand_built

pytestmark = pytest.mark.django_db


def test_removal_refuses_when_a_switched_off_section_still_holds_rows(monkeypatch):
    _hand_built()
    f.ReportSubmissionFactory(reporting_period=ReportingPeriod.objects.get())
    installed = demo.content_models()
    monkeypatch.setattr(
        demo, "content_models", lambda: [(label, model) for label, model in installed if not label.startswith("reporting.")]
    )
    before = demo.content_counts()

    with pytest.raises(demo.Refused) as refusal:
        demo.remove()

    assert demo.content_counts() == before
    assert "1 report submission" in str(refusal.value)
    assert "Reporting" in str(refusal.value)
