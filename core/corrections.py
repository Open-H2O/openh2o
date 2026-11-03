# SPDX-License-Identifier: AGPL-3.0-or-later
"""Records that can be voided, and the one rule that says which records count.

A record entered by mistake is not deleted: it is marked void with a reason,
stays on its page, and every calculation and total leaves it out. This module
holds the whole mechanism so no site invents its own:

- :class:`CorrectableQuerySet` and its :meth:`~CorrectableQuerySet.current`:
  THE rule for "which records count". A record counts when it is not voided and
  no other record replaces it (plan 02 writes the replacing rows). A model whose
  rows count only while another record counts (a ledger row counts only while its
  use area does) names that link in ``current_through``. No site adds a filter of
  its own; a test fails the build on a calculation that reads around it.
- :class:`CorrectableRecord`: the abstract model the eleven covered kinds take.
  The default manager returns every row, because pages show voided rows struck.
- :data:`KINDS`: one entry per kind a person can void, in page words.
- :func:`void`: the one way a record is voided.

Nothing here imports a project model at module scope (``kind.model_class()``
resolves one through the app registry when asked): every covered app's
``models.py`` imports this file. Django's own ``models`` is imported, which
needs the app registry ready, as it is whenever a ``models.py`` loads.
"""

import datetime as dt

from django.apps import apps
from django.conf import settings
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone

from core.history import change_note, clean_note

#: The shortest and longest reason a void takes.
REASON_MIN_LENGTH = 10
REASON_MAX_LENGTH = 500

#: The sentence for a reason outside those bounds.
REASON_SENTENCE = "Give a reason of 10 to 500 characters."


class AlreadyVoided(Exception):
    """The record is already voided."""


class NotVoidable(Exception):
    """The kind's own rule says this record cannot be voided (the engine wrote it)."""


class CorrectableQuerySet(models.QuerySet):
    def current(self):
        """The records that count: not voided, not replaced, and (where the
        model names a link in ``current_through``) attached to a record that
        counts too."""
        found = self.filter(voided_at__isnull=True, replaced_by__isnull=True)
        for name in getattr(self.model, "current_through", ()):
            found = found.filter(
                **{
                    f"{name}__voided_at__isnull": True,
                    f"{name}__replaced_by__isnull": True,
                }
            )
        return found


class CorrectableRecord(models.Model):
    """The columns a record needs to be voided, or replaced by a corrected one.

    ``current_through`` names the links whose records must count too for this
    one to count (``ParcelLedger``: its use area). Plan 02 fills ``replaces``
    and ``change_reason``; this plan reads ``replaces`` in :meth:`current`.
    """

    current_through = ()

    voided_at = models.DateTimeField("voided", null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        verbose_name="voided by",
    )
    void_reason = models.CharField("reason for voiding", max_length=500, blank=True)
    replaces = models.OneToOneField(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="replaced_by",
        verbose_name="replaces",
    )
    change_reason = models.CharField(
        "reason for the change", max_length=500, blank=True
    )

    objects = CorrectableQuerySet.as_manager()

    class Meta:
        abstract = True


# -- Words ------------------------------------------------------------------------


def _day_words(day):
    """A date as the pages print it: Sep 30, 2026."""
    return f"{day:%b} {day.day}, {day.year}"


def _af(value):
    return f"{value:,.2f} AF"


def _local_date(moment):
    return timezone.localtime(moment).date() if timezone.is_aware(moment) else moment.date()


def _month_text(day):
    return f"{day.year}-{day.month:02d}"


_METER_UNIT_WORDS = {
    "acre_feet": "AF",
    "gallons": "gal",
    "cubic_feet": "cu ft",
    "cfs": "cfs",
}

#: What a ledger row the person typed starts with and the engine's own rows
#: start with; kept here as words so this module imports nothing at module scope.
_WELL_SHARE_WORDS = "From the well's meter:"


# -- Per kind: the figure and date as the page prints them -----------------------------


def _meter_reading_summary(row):
    unit = _METER_UNIT_WORDS.get(row.meter.unit, row.meter.unit)
    figure = row.calculated_volume if row.calculated_volume is not None else row.current_value
    return f"{figure:,.2f} {unit}, {_day_words(_local_date(row.reading_date))}"


def _water_level_summary(row):
    when = _day_words(_local_date(row.measurement_date))
    if row.value is None:
        return f"No depth read, {when}"
    return f"{row.value:,.2f} {row.unit}, {when}"


def _ledger_entry_summary(row):
    return f"{row.amount_acre_feet:,.2f} AF, {_day_words(row.effective_date)}"


def _fallow_period_summary(row):
    words = row.span_words()
    return f"Fallow {words}".strip() if words else "Fallow, no dates"


def _use_area_summary(row):
    if row.area_acres is None:
        return row.parcel_number
    return f"{row.parcel_number}, {row.area_acres:,.2f} acres"


def _diversion_record_summary(row):
    return f"{_af(row.volume_acre_feet)}, {_day_words(row.month)}"


def _recharge_event_summary(row):
    return f"{_af(row.volume_acre_feet)}, {_day_words(row.start_date)}"


def _recharge_measurement_summary(row):
    return (
        f"{row.value:,.2f} {row.unit}, "
        f"{_day_words(_local_date(row.measurement_date))}"
    )


def _lab_result_summary(row):
    if row.result_kind == "presence_absence":
        shown = {True: "present", False: "absent", None: "not stated"}[row.presence]
    else:
        shown = f"{row.result_value:,.2f} {row.unit}".strip() if row.result_value is not None else "no value"
    return f"{shown}, {_day_words(row.event.sample_date)}"


def _production_month_day(row):
    return dt.date(row.year, row.month or 1, 1)


def _production_record_summary(row):
    return f"{_af(row.volume_acre_feet)}, {row.year}-{(row.month or 1):02d}"


def _station_reading_summary(row):
    return f"{row.value:,.2f}, {_day_words(row.observation_date)}"


# -- Per kind: the date the finalized-year check reads -----------------------------------


def _meter_reading_date(row):
    return _local_date(row.reading_date)


def _water_level_date(row):
    return _local_date(row.measurement_date)


def _fallow_period_date(row):
    return row.start_month or row.end_month


def _lab_result_date(row):
    return row.event.sample_date


# -- Per kind: the months a void moves ----------------------------------------------


def _meter_reading_months(row):
    """The reading's month and the next current reading's, whose volume is figured again."""
    from measurements.models import MeterReading

    months = {_month_text(_local_date(row.reading_date))}
    following = (
        MeterReading.objects.current()
        .filter(meter_id=row.meter_id, reading_date__gt=row.reading_date)
        .order_by("reading_date")
        .first()
    )
    if following is not None:
        months.add(_month_text(_local_date(following.reading_date)))
    return months


def _ledger_entry_months(row):
    return {_month_text(row.effective_date)}


def _fallow_period_months(row):
    """The months the use area has a calculation for, inside the period's span."""
    from accounting.models import CalculationRun

    runs = CalculationRun.objects.filter(parcel_id=row.parcel_id)
    if row.start_month:
        runs = runs.filter(period_start__gte=row.start_month)
    if row.end_month:
        runs = runs.filter(period_start__lte=row.end_month)
    return set(runs.values_list("period", flat=True))


def _use_area_months(row):
    """Every month in which the use area has a calculation or a ledger row."""
    from accounting.models import CalculationRun
    from parcels.models import ParcelLedger

    months = set(CalculationRun.objects.filter(parcel=row).values_list("period", flat=True))
    months |= {
        _month_text(day)
        for day in ParcelLedger.objects.filter(parcel=row).dates("effective_date", "month")
    }
    return months


def _diversion_record_months(row):
    return {_month_text(row.month)}


def _no_months(row):
    return set()


# -- Per kind: what else a void does -------------------------------------------------------


def _nothing(row):
    return None


def _meter_reading_on_void(row):
    """Figure the next current reading again from the last one still in use.

    A reading stores its ``previous_value`` and ``calculated_volume`` from the
    reading before it (``wells/forms.py``), and the month's calculation reads the
    stored volume first. Voiding a reading between two others leaves the later
    one figured from a value that no longer counts. Only those two columns move,
    never the typed ``current_value``; the rule is the one the entry form uses.
    A volume that comes out negative is stored as no volume (the calculation
    reads it as none either way).
    """
    from accounting.locks import refuse_if_finalized
    from measurements.models import MeterReading

    following = (
        MeterReading.objects.current()
        .filter(meter_id=row.meter_id, reading_date__gt=row.reading_date)
        .order_by("reading_date")
        .first()
    )
    if following is None:
        return
    refuse_if_finalized(_local_date(following.reading_date))
    earlier = (
        MeterReading.objects.current()
        .filter(meter_id=row.meter_id, reading_date__lt=following.reading_date)
        .order_by("-reading_date")
        .first()
    )
    previous_value = earlier.current_value if earlier is not None else None
    if row.meter.meter_type == "totalizer":
        volume = (
            following.current_value - previous_value
            if previous_value is not None
            else None
        )
        if volume is not None and volume < 0:
            volume = None
    else:
        volume = following.current_value
    MeterReading.objects.filter(pk=following.pk).update(
        previous_value=previous_value, calculated_volume=volume
    )


def _recharge_event_on_void(row):
    """Take back the event's credit, as deleting the event used to."""
    from accounting.services import remove_recharge_ledger_entries

    remove_recharge_ledger_entries(row)


def _station_reading_on_void(row):
    """Take the published copy off the chart, so the day can be typed again."""
    from datasync.models import DataRecordStaging

    if row.reading_id:
        DataRecordStaging.objects.filter(pk=row.reading_id).delete()
        row.reading = None


# -- Per kind: whether a person may void it -------------------------------------------------


def _always(row):
    return True


def _ledger_entry_can_void(row):
    """Only a row a person entered. The engine rewrites its own rows every run."""
    source = row.source_type
    if source in ("manual_entry", "adjustment", "csv_import", "allocation"):
        return True
    description = row.description or ""
    if source == "meter_reading":
        return not description.startswith(_WELL_SHARE_WORDS)
    if source == "recharge":
        return not _is_engine_recharge_credit(description)
    if source == "surface_diversion":
        # A delivery typed on the use area's own ledger. The canal split's rows
        # carry the headgate mark and are replaced whenever the month runs.
        return not row.divided_from_headgate
    return False


def _is_engine_recharge_credit(description):
    from accounting.ledger_words import (
        INCIDENTAL_RECHARGE_WORDS,
        LEGACY_CANAL_CREDIT_WORDS,
        LEGACY_INCIDENTAL_RECHARGE_WORDS,
    )

    return description.startswith(
        (INCIDENTAL_RECHARGE_WORDS, LEGACY_INCIDENTAL_RECHARGE_WORDS, LEGACY_CANAL_CREDIT_WORDS)
    )


def _diversion_record_can_void(row):
    return row.method != "estimated_from_use"


# -- Per kind: the page the row lives on -----------------------------------------------------


def anchor(kind_key, row):
    """The element id a row carries on its page, so a link can land on it."""
    return f"record-{kind_key}-{row.pk}"


def _with_anchor(kind_key, row, url):
    return f"{url}#{anchor(kind_key, row)}"


def _meter_reading_url(row):
    from wells.models import WellMeter

    link = WellMeter.objects.filter(meter_id=row.meter_id).order_by("-is_current", "-pk").first()
    url = reverse("wells:detail", args=[link.well_id]) if link else reverse("wells:list")
    return _with_anchor("meter_reading", row, url)


def _water_level_url(row):
    url = reverse("wells:detail", args=[row.well_id]) if row.well_id else reverse("wells:list")
    return _with_anchor("water_level", row, url)


def _ledger_entry_url(row):
    return _with_anchor("ledger_entry", row, reverse("accounting:ledger_list"))


def _fallow_period_url(row):
    return _with_anchor("fallow_period", row, reverse("parcels:detail", args=[row.parcel_id]))


def _use_area_url(row):
    return reverse("parcels:detail", args=[row.pk])


def _diversion_record_url(row):
    return _with_anchor(
        "diversion_record", row, reverse("surface:pod_detail", args=[row.point_of_diversion_id])
    )


def _recharge_event_url(row):
    return _with_anchor("recharge_event", row, reverse("recharge:detail", args=[row.recharge_site_id]))


def _recharge_measurement_url(row):
    return _with_anchor(
        "recharge_measurement", row, reverse("recharge:detail", args=[row.recharge_site_id])
    )


def _lab_result_url(row):
    return reverse("drinking:result_detail", args=[row.pk])


def _production_record_url(row):
    return _with_anchor("production_record", row, reverse("drinking:production"))


def _station_reading_url(row):
    return _with_anchor(
        "station_reading", row, reverse("datasync:station_detail", args=[row.station_id])
    )


# -- The registry ------------------------------------------------------------------------------


class Kind(dict):
    """One entry of :data:`KINDS`: read as ``kind["label"]`` or ``kind.label``."""

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None

    def model_class(self):
        """The model, resolved through the app registry on first use."""
        return apps.get_model(self["model"])

    def enabled(self):
        """False when the module that owns this kind is switched off."""
        from core.modules import is_enabled

        return is_enabled(self["module"])


def _kind(key, model, module, label, **hooks):
    entry = {
        "key": key,
        "model": model,
        "module": module,
        "label": label,
        "months": _no_months,
        "on_void": _nothing,
        "can_void": _always,
    }
    entry.update(hooks)
    return Kind(entry)


KINDS = {
    k["key"]: k
    for k in (
        _kind(
            "meter_reading", "measurements.MeterReading", "wells", "meter reading",
            summary=_meter_reading_summary, page_url=_meter_reading_url,
            date_of=_meter_reading_date, months=_meter_reading_months,
            on_void=_meter_reading_on_void,
        ),
        _kind(
            "water_level", "measurements.WaterMeasurement", "wells", "water level",
            summary=_water_level_summary, page_url=_water_level_url,
            date_of=_water_level_date,
        ),
        _kind(
            "ledger_entry", "parcels.ParcelLedger", "accounting", "ledger entry",
            summary=_ledger_entry_summary, page_url=_ledger_entry_url,
            date_of=lambda row: row.effective_date, months=_ledger_entry_months,
            can_void=_ledger_entry_can_void,
        ),
        _kind(
            "fallow_period", "parcels.FallowPeriod", "parcels", "fallow period",
            summary=_fallow_period_summary, page_url=_fallow_period_url,
            date_of=_fallow_period_date, months=_fallow_period_months,
        ),
        _kind(
            "use_area", "parcels.Parcel", "parcels", "use area",
            summary=_use_area_summary, page_url=_use_area_url,
            date_of=lambda row: None, months=_use_area_months,
        ),
        _kind(
            "diversion_record", "surface.DiversionRecord", "surface", "diversion record",
            summary=_diversion_record_summary, page_url=_diversion_record_url,
            date_of=lambda row: row.month, months=_diversion_record_months,
            can_void=_diversion_record_can_void,
        ),
        _kind(
            "recharge_event", "recharge.RechargeEvent", "recharge", "recharge event",
            summary=_recharge_event_summary, page_url=_recharge_event_url,
            date_of=lambda row: row.start_date, on_void=_recharge_event_on_void,
        ),
        _kind(
            "recharge_measurement", "recharge.RechargeMeasurement", "recharge",
            "recharge measurement",
            summary=_recharge_measurement_summary, page_url=_recharge_measurement_url,
            date_of=lambda row: _local_date(row.measurement_date),
        ),
        _kind(
            "lab_result", "drinking.SampleResult", "drinking", "lab result",
            summary=_lab_result_summary, page_url=_lab_result_url,
            date_of=_lab_result_date,
        ),
        _kind(
            "production_record", "drinking.SystemProduction", "drinking", "production record",
            summary=_production_record_summary, page_url=_production_record_url,
            date_of=_production_month_day,
        ),
        _kind(
            "station_reading", "datasync.TypedReading", "datasync", "station reading",
            summary=_station_reading_summary, page_url=_station_reading_url,
            date_of=lambda row: row.observation_date, on_void=_station_reading_on_void,
        ),
    )
}


def get_kind(word):
    """The kind a URL word names. Raises ``KeyError`` for a word that names none."""
    return KINDS[word]


def kind_for(instance):
    """The kind a record belongs to. Raises ``KeyError`` for a model that has none."""
    label = instance._meta.label
    for kind in KINDS.values():
        if kind["model"].lower() == label.lower():
            return kind
    raise KeyError(label)


# -- Can this row be voided --------------------------------------------------------------------


def finalized_ranges():
    """``[(start, end), ...]`` of the finalized water years: ONE query for a whole page.

    Pass the result to :func:`can_void` for every row on the page, so a page of
    rows asks the database once, not once per row.
    """
    from accounting.models import ReportingPeriod

    return list(
        ReportingPeriod.objects.filter(is_finalized=True).values_list("start_date", "end_date")
    )


def can_void(row, finalized=None):
    """Whether the row's menu should offer Void.

    Answers from the row's own columns and its kind's rule, with no query:
    not already voided, and not a row the engine writes (``can_void`` of the
    kind). Pass ``finalized`` (from :func:`finalized_ranges`) to also leave out
    a row dated inside a finalized year. A use area has no date; :func:`void`
    checks its rows instead.
    """
    if row.voided_at is not None:
        return False
    kind = kind_for(row)
    if not kind["can_void"](row):
        return False
    if finalized:
        day = kind["date_of"](row)
        if day is not None and any(start <= day <= end for start, end in finalized):
            return False
    return True


# -- Void --------------------------------------------------------------------------------------


def _refuse_if_use_area_in_finalized_year(row):
    """A use area is refused when any of its rows falls in a finalized year."""
    from accounting.locks import PeriodFinalized
    from accounting.models import CalculationRun, ReportingPeriod
    from parcels.models import ParcelLedger

    for period in ReportingPeriod.objects.filter(is_finalized=True).order_by("start_date"):
        in_year = ParcelLedger.objects.filter(
            parcel=row, effective_date__gte=period.start_date, effective_date__lte=period.end_date
        ).exists() or CalculationRun.objects.filter(
            parcel=row,
            period_start__gte=period.start_date.replace(day=1),
            period_start__lte=period.end_date,
        ).exists()
        if in_year:
            raise PeriodFinalized(period)


def void(row, *, user, reason):
    """Void ``row``: mark it, run the kind's own consequence, return the months to recalculate.

    Raises :class:`AlreadyVoided`, :class:`NotVoidable`, ``ValueError`` (the
    reason sentence) or ``accounting.locks.PeriodFinalized``, in that order,
    before anything is written. Inside one transaction and one change note the
    row's ``voided_at``, ``voided_by`` and ``void_reason`` are set and nothing
    else on it moves, then the kind's ``on_void`` runs. It does NOT start the
    recalculation: the caller does, with trigger ``record_voided``, on the
    returned months (``"YYYY-MM"``, oldest first).
    """
    from accounting.locks import refuse_if_finalized

    kind = kind_for(row)
    model = type(row)
    text = (reason or "").strip()
    with transaction.atomic():
        locked = model.objects.select_for_update().get(pk=row.pk)
        if locked.voided_at is not None:
            raise AlreadyVoided("This record is already voided.")
        if not kind["can_void"](locked):
            raise NotVoidable(
                f"This {kind['label']} was written by OpenH2O's own calculation "
                "and cannot be voided. Void the record it came from."
            )
        if not REASON_MIN_LENGTH <= len(text) <= REASON_MAX_LENGTH:
            raise ValueError(REASON_SENTENCE)
        note = clean_note(text)
        if note is None or not REASON_MIN_LENGTH <= len(note) <= REASON_MAX_LENGTH:
            raise ValueError(REASON_SENTENCE)
        day = kind["date_of"](locked)
        if day is not None:
            refuse_if_finalized(day)
        if kind["key"] == "use_area":
            _refuse_if_use_area_in_finalized_year(locked)
        months = set(kind["months"](locked))
        now = timezone.now()
        changes = {"voided_at": now, "voided_by": user, "void_reason": note}
        if any(f.name == "updated_at" for f in model._meta.concrete_fields):
            changes["updated_at"] = now
        with change_note(note):
            model.objects.filter(pk=locked.pk).update(**changes)
            for name, value in changes.items():
                setattr(locked, name, value)
            kind["on_void"](locked)
    row.voided_at = locked.voided_at
    row.voided_by = locked.voided_by
    row.void_reason = locked.void_reason
    return sorted(months)
