# SPDX-License-Identifier: AGPL-3.0-or-later
"""Template tags for the rows of a record table: the struck line and the menu's addresses.

``{% record_marks row colspan %}`` prints what sits under a record
(``templates/partials/_record_marks.html``): the one line under a voided or replaced
record, the one-time response after a correction, and the correction row while it is
open. The filters name a row's kind and its element id, so a link from Change history
can land on it (``core.corrections.anchor``).
"""

from decimal import Decimal

from django import template
from django.urls import reverse
from django.utils import timezone

from core import corrections, record_attachments

register = template.Library()


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


@register.simple_tag
def record_correct_url(row):
    """The address that opens the correction row for this record and takes the correction."""
    return reverse("core:record_correct", args=[corrections.kind_for(row)["key"], row.pk])


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
    # The day is the site's own (its time zone setting), read at call time.
    day = timezone.localtime(row.voided_at, timezone.get_default_timezone())
    reason = (row.void_reason or "").strip()
    if reason and reason[-1] not in ".!?":
        reason += "."
    return f"Voided {day:%b} {day.day}, {day.year} by {_who(row.voided_by)}: {reason}".rstrip(": ")


def _number(value):
    return f"{Decimal(value):,.2f}"


def _signed(value):
    value = Decimal(value)
    return f"\u2212{abs(value):,.2f}" if value < 0 else f"{value:,.2f}"


def _plain(value):
    return f"{Decimal(value):f}".rstrip("0").rstrip(".") if value is not None else ""


#: The figure each kind's table prints, as the table prints it.
_FIGURES = {
    "meter_reading": ("current_value", _number),
    "water_level": ("value", _number),
    "ledger_entry": ("amount_acre_feet", _signed),
    "diversion_record": ("volume_acre_feet", _number),
    "recharge_event": ("volume_acre_feet", _number),
    "lab_result": ("result_value", _plain),
    "production_record": ("volume_as_reported", _number),
    "station_reading": ("value", _number),
}


def _day(value):
    value = timezone.localtime(value).date() if hasattr(value, "hour") else value
    return f"{value:%b} {value.day}, {value.year}"


def _month(value):
    return f"{value:%b %Y}"


#: The date each kind's table prints, and how.
_DATES = {
    "meter_reading": ("reading_date", _day),
    "water_level": ("measurement_date", _day),
    "ledger_entry": ("effective_date", _day),
    "diversion_record": ("month", _month),
    "recharge_event": ("start_date", _day),
    "station_reading": ("observation_date", _day),
}


def _now_words(kind_key, old, new):
    """What changed, as the table prints it: the figure, the date, the estimate choice."""
    words = []
    figure = _FIGURES.get(kind_key)
    if figure is not None:
        name, show = figure
        if getattr(old, name) != getattr(new, name) and getattr(new, name) is not None:
            words.append(show(getattr(new, name)))
    date = _DATES.get(kind_key)
    if date is not None:
        name, show = date
        before, after = getattr(old, name), getattr(new, name)
        same = (
            timezone.localtime(before).date() == timezone.localtime(after).date()
            if hasattr(before, "hour") else before == after
        )
        if not same:
            words.append(show(after))
    if kind_key == "production_record" and (old.year, old.month) != (new.year, new.month):
        words.append(f"{new.year}-{new.month:02d}" if new.month else str(new.year))
    if kind_key == "fallow_period" and (old.start_month, old.end_month) != (new.start_month, new.end_month):
        span = f"from {_month(new.start_month)}"
        if new.end_month:
            span += f" to {_month(new.end_month)}"
        words.append(span)
    if kind_key == "meter_reading" and (old.quality == "estimated") != (new.quality == "estimated"):
        words.append("estimated" if new.quality == "estimated" else "read from the meter")
    return ", ".join(words)


_AUTHOR_FIELDS = ("read_by", "recorded_by", "created_by", "typed_by")


def _author(new):
    """The person who typed the replacing record: its own author column, else who the change history names."""
    for name in _AUTHOR_FIELDS:
        if hasattr(new, name) and getattr(new, name) is not None:
            return getattr(new, name)
    if hasattr(new, "events"):
        from django.contrib.auth import get_user_model

        event = new.events.filter(pgh_label="insert").select_related("pgh_context").first()
        user_id = event.pgh_context.metadata.get("user") if event and event.pgh_context else None
        if user_id:
            return get_user_model().objects.filter(pk=user_id).first()
    return None


def replaced_line(row):
    """``(text, attachment)`` for a record a corrected one replaces, else ``("", None)``.

    ``Replaced Nov 2, 2026 by J. Lopez, now 39,771.39: typed an 8 for a 7.`` and the
    file's link word (Photo or PDF) when the correction carried one.
    """
    if row.replaced_at is None:
        return "", None
    kind = corrections.kind_for(row)
    new = type(row).objects.filter(replaces=row).first()
    # The day is the site's own (its time zone setting), read at call time.
    day = timezone.localtime(row.replaced_at, timezone.get_default_timezone())
    if new is None:
        return f"Replaced {day:%b} {day.day}, {day.year}.", None
    now = _now_words(kind["key"], row, new)
    reason = (new.change_reason or "").strip()
    if reason and reason[-1] not in ".!?":
        reason += "."
    head = f"Replaced {day:%b} {day.day}, {day.year} by {_who(_author(new))}"
    if now:
        head += f", now {now}"
    attachment = record_attachments.attachment_for(kind["key"], new.pk)
    return (f"{head}: {reason}" if reason else f"{head}."), attachment


@register.inclusion_tag("partials/_record_marks.html", takes_context=True)
def record_marks(context, row, colspan=1, variant="row", lead="", target="", swap="innerHTML", include=""):
    """What sits under a record: a table row spanning ``colspan`` cells, or (``variant="note"``) a plain block.

    The line under a voided or replaced record, the one-time response line after a
    correction, and the correction row while this record's is open. Prints nothing for a
    record that counts and has none of those. ``lead`` names the record when the line sits
    under a row that holds several (the production table's month): "Groundwater: Voided ...".
    ``target``, ``swap`` and ``include`` are the address the correction row's form swaps into,
    the same ones the page's menu uses.
    """
    from core.corrections_views import correct_state

    key = corrections.kind_for(row)["key"]
    anchor = corrections.anchor(key, row)
    attachment = None
    line = void_line(row)
    if not line and row.replaced_at is not None:
        line, attachment = replaced_line(row)
    if lead and line:
        line = f"{lead}: {line}"
    state = correct_state()
    return {
        "line": line,
        "attachment": (
            {"url": reverse("core:record_attachment", args=[attachment.pk]),
             "word": record_attachments.word(attachment)}
            if attachment else None
        ),
        "anchor": anchor,
        "colspan": colspan,
        "variant": variant,
        "done_text": state.done_text if state and state.done_key == anchor else "",
        "state": state if state and state.key == anchor else None,
        "row": row,
        "correct_url": reverse("core:record_correct", args=[key, row.pk]),
        "target": target,
        "swap": swap,
        "include": include,
        "csrf_token": context.get("csrf_token"),
    }
