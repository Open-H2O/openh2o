# SPDX-License-Identifier: AGPL-3.0-or-later
"""Template tags for the rows of a record table: the struck line and the menu's addresses.

``{% record_marks row colspan %}`` prints the one line under a voided record
(``templates/partials/_record_marks.html``); the filters name a row's kind and
its element id, so a link from Change history can land on it
(``core.corrections.anchor``).
"""

from zoneinfo import ZoneInfo

from django import template
from django.urls import reverse
from django.utils import timezone

from core import corrections

register = template.Library()

#: Dates on a void line are the district's day, which is Pacific here as everywhere on the pages.
_PACIFIC = ZoneInfo("America/Los_Angeles")


@register.filter
def record_kind(row):
    """The kind word of a covered record: ``meter_reading``, ``diversion_record`` and so on."""
    return corrections.kind_for(row)["key"]


@register.filter
def record_anchor(row):
    """The element id the record's row carries."""
    return corrections.anchor(corrections.kind_for(row)["key"], row)


@register.simple_tag
def record_void_url(row):
    """The address that opens the reason row for this record and takes the void."""
    return reverse("core:record_void", args=[corrections.kind_for(row)["key"], row.pk])


def _who(user):
    """``J. Lopez`` for a user with both names, otherwise the name the Change history shows."""
    if user is None:
        return "a former user"
    first = (user.first_name or "").strip()
    last = (user.last_name or "").strip()
    if first and last:
        return f"{first[0]}. {last}"
    return user.get_full_name().strip() or user.email or user.username


def void_line(row):
    """``Voided Nov 2, 2026 by J. Lopez: typed on the wrong well.``, or ``""`` for a record that counts."""
    if row.voided_at is None:
        return ""
    day = timezone.localtime(row.voided_at, _PACIFIC)
    reason = (row.void_reason or "").strip()
    if reason and reason[-1] not in ".!?":
        reason += "."
    return f"Voided {day:%b} {day.day}, {day.year} by {_who(row.voided_by)}: {reason}".rstrip(": ")


@register.inclusion_tag("partials/_record_marks.html")
def record_marks(row, colspan=1, variant="row", lead=""):
    """The line under a voided record: a table row spanning ``colspan`` cells, or (``variant="note"``) a plain line.

    Prints nothing for a record that counts. ``lead`` names the record when the line sits
    under a row that holds several (the production table's month): "Groundwater: Voided ...".
    """
    line = void_line(row)
    return {
        "line": f"{lead}: {line}" if lead and line else line,
        "anchor": corrections.anchor(corrections.kind_for(row)["key"], row),
        "colspan": colspan,
        "variant": variant,
    }
