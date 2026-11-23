# SPDX-License-Identifier: AGPL-3.0-or-later
"""Two layouts readers named at 1,730 px.

The short month card (.receipt-short: a metered or no-well month, or a month waiting for OpenET)
takes the content width like every other full card, so its right edge lines up with the cards and
banner around it instead of stopping halfway across an empty page. Its sentence keeps its reading
measure (.receipt-lead).

On a finalized water year the Status cell's date and time sit together on their own line under
the Finalized badge, so the time never wraps onto a line by itself.
"""

import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from django.test import Client
from django.urls import reverse

from accounting.models import ReportingPeriod
from core.models import User
from tests.factories import ReportingPeriodFactory

APP_CSS = Path(__file__).resolve().parent.parent / "static" / "css" / "app.css"


def _rule(css, selector):
    """The declarations of the first rule whose selector is exactly this one."""
    match = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert match, f"no rule for {selector} in app.css"
    return match.group(1)


def test_the_short_receipt_card_is_not_shrunk_to_its_contents():
    css = APP_CSS.read_text()
    declarations = _rule(css, ".receipt-short")
    assert "fit-content" not in declarations
    assert "max-content" not in declarations


# not wording: the literal is a CSS declaration in app.css, not a sentence a person reads.
def test_the_short_receipts_sentence_keeps_its_reading_measure():
    css = APP_CSS.read_text()
    assert "max-width: 70ch" in _rule(css, ".receipt-lead")


@pytest.mark.django_db
def test_a_finalized_years_date_and_time_sit_together_under_the_badge():
    person = User.objects.create_user(
        username="finisher", email="finisher@example.org", password="a-good-passw0rd", is_active=True,
    )
    period = ReportingPeriodFactory()
    ReportingPeriod.objects.filter(pk=period.pk).update(
        is_finalized=True,
        finalized_at=datetime(2026, 11, 18, 13, 53, tzinfo=timezone.utc),
        finalized_by=person,
    )
    client = Client()
    client.force_login(person)
    page = client.get(reverse("accounting:period_detail", args=[period.pk])).content.decode()

    status = page[page.index('<div class="field-label">Status</div>'):]
    status = status[: status.index('<div class="field-label">Start date</div>')]
    # The badge, then a line of its own: the date and the time, each one unbreakable piece, so a
    # narrow card moves the time under the whole date instead of past its edge.
    assert re.search(
        r'Finalized</span>\s*<div class="[^"]*\bfinalized-when\b[^"]*">\s*'
        r'<span class="nowrap-item">\w{3} \d{2}, \d{4}</span> <span class="nowrap-item">\d{2}:\d{2}</span>',
        status,
    ), status
    # Who finalized it follows on the same line and may wrap; the date and time may not.
    assert " by " in re.sub(r"<[^>]+>", "", status)
