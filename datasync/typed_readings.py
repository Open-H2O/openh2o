# SPDX-License-Identifier: AGPL-3.0-or-later
"""Readings typed by hand at a station of the "Entered by hand" source.

A typed reading is an ordinary published ``DataRecordStaging`` row, so the
chart, the current readings and the readings table show it with no special
case. ``DataRecordStaging`` cannot carry change history (every sync writes
thousands of rows into it, and pghistory's decorator takes a whole table), so
each typed reading also gets a ``TypedReading`` row, which does: who typed it,
when, and what they typed.

A day's reading is stored at midnight in the site's time zone, the way the
daily readings from a provider are (07:00 or 08:00 UTC for a Pacific site).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from accounting.locks import PeriodFinalized, refuse_if_finalized
from datasync.adapters.registry import manual_parameter_choices, manual_parameter_unit
from datasync.models import DataRecordStaging, MonitoredStation, TypedReading

NEED_DATE = "Enter the date of the reading."
NEED_VALUE = "Enter the value as a number."
NEED_PARAMETER = "Choose a parameter."
DUPLICATE = "A reading for this measurement on this date is already on file."
ONLY_BY_HAND = "Only an Entered by hand station takes readings here."

# The column holds 14 digits, 4 of them after the point.
_VALUE_LIMIT = Decimal(10) ** 10
_FOUR_PLACES = Decimal("0.0001")


class DuplicateReading(Exception):
    """A reading for this station, parameter and date is already on file."""


@dataclass
class Clean:
    observation_date: date
    value: Decimal
    parameter_code: str
    notes: str


def site_zone():
    from datasync import schedule

    return schedule._site_zone()


def today():
    """Today's date in the site's time zone."""
    return timezone.now().astimezone(site_zone()).date()


def midnight(day: date) -> datetime:
    """The start of ``day`` in the site's time zone."""
    return datetime.combine(day, time.min, tzinfo=site_zone())


def validate(values):
    """``(Clean, [])`` for a good form, ``(None, [sentence, ...])`` for a bad one."""
    errors = []

    try:
        day = date.fromisoformat((values.get("observation_date") or "").strip())
    except ValueError:
        day = None
        errors.append(NEED_DATE)

    value = None
    raw = (values.get("value") or "").strip()
    try:
        value = Decimal(raw)
        if not value.is_finite() or abs(value) >= _VALUE_LIMIT:
            raise InvalidOperation
        value = value.quantize(_FOUR_PLACES, rounding=ROUND_HALF_EVEN)
    except InvalidOperation:
        value = None
        errors.append(NEED_VALUE)

    code = (values.get("parameter") or "").strip()
    if code not in {c for c, _ in manual_parameter_choices()}:
        code = ""
        errors.append(NEED_PARAMETER)

    if day is not None:
        # A reading dated inside a finalized water year is refused (an
        # administrator's correction is the way into one).
        try:
            refuse_if_finalized(day)
        except PeriodFinalized as exc:
            errors.append(str(exc))

    if errors:
        return None, errors
    return Clean(day, value, code, (values.get("notes") or "").strip()), []


def save_reading(station: MonitoredStation, user, clean: Clean) -> DataRecordStaging:
    """Store one typed reading as published, with its audit row. Raises ``DuplicateReading``."""
    observed = midnight(clean.observation_date)
    now = timezone.now()
    email = user.email or user.get_username()
    try:
        with transaction.atomic():
            if DataRecordStaging.objects.current().filter(
                station=station,
                parameter_code=clean.parameter_code,
                statistic="",
                observation_date=observed,
            ).exists():
                raise DuplicateReading
            row = DataRecordStaging.objects.create(
                data_source=station.data_source,
                station=station,
                raw_data={
                    "typed_by": email,
                    "typed_at": now.isoformat(),
                    "notes": clean.notes,
                },
                observation_date=observed,
                parameter_code=clean.parameter_code,
                statistic="",
                value=clean.value,
                unit=manual_parameter_unit(clean.parameter_code),
                status="published",
                published_at=now,
            )
            TypedReading.objects.create(
                station=station,
                reading=row,
                typed_by=user,
                typed_by_email=email,
                typed_at=now,
                parameter_code=clean.parameter_code,
                observation_date=clean.observation_date,
                value=clean.value,
                notes=clean.notes,
            )
            # The newest reading on file, as a sync sets it: a reading typed for
            # an earlier day does not move it back.
            newest = DataRecordStaging.objects.current().filter(
                station=station, status="published"
            ).aggregate(newest=Max("observation_date"))["newest"]
            MonitoredStation.objects.filter(pk=station.pk).update(last_data_at=newest)
    except IntegrityError as exc:
        # Two presses at once: the table's own unique key caught the second.
        raise DuplicateReading from exc
    return row
