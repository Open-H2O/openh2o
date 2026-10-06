# SPDX-License-Identifier: AGPL-3.0-or-later
"""Estimate the delivery of a ditch with no meter, capped at what the right allows (149-02).

A point of diversion that serves fields, carries a water right, has no measuring
device in service in a month and has no volume a person typed for it gets that
month's delivery estimated from what its fields used, and the estimate is stored
as an ordinary ``DiversionRecord`` marked ``method="estimated_from_use"`` and
``data_state="provisional"``. The canal split then divides it like any other
record, so the fields' surface figures stop landing as groundwater or as "water
use recorded, no supply reported" just because nobody wrote a number down.

The month's order is: crop water use, :func:`estimate_month`, the canal split
for each point, crop water use again (``accounting.engine_run.run_month``).

**The estimate.** For each qualifying point:

1. ``field_need`` is, for every served field WITHOUT a delivery record of its
   own that month, its ``CalculationRun.net_consumptive_use_af`` (use after
   rain) divided by ``surface.services.field_efficiency``, plus the fields' own
   recorded deliveries (``_own_total_for_pod``), because the split takes those
   out of what reaches the fields before it divides the rest. Quantized to four
   places once, at the end of the step.
2. ``headgate_estimate = field_need / (1 - evaporation - seepage - spill)``,
   the point's own three canal-loss shares, quantized once.
3. The cap. When the right records a direct season and the month lies wholly
   outside it, the figure is 0.0000 (a season may run over the year end; a
   month partly in season counts as in season). Otherwise it is the smaller of
   the estimate and ``face_value - already_used``, floored at zero, where
   ``already_used`` is every direct-use volume (typed and estimated) on every
   point of diversion linked to the right, for months of the same water year
   strictly BEFORE this month. A later point on the same right in the SAME
   month does not see the earlier one's volume, only earlier months count; that
   keeps the figure the same however the points are visited.
4. The record is written, or replaced, only when a value changed, so a re-run
   leaves the same row and adds no change history.

A point whose right is not active (curtailed, say) gets no estimate and loses
any it held: an estimate there would invent water the curtailment stopped. A
point with no right gets none either (an estimate needs a right to cap
against). The estimator only ever touches records whose method is
``estimated_from_use``.

**Nothing here recalculates anything.** The save hook that recalculates a month
when a diversion record is saved lives in the views (``surface.views``,
``_recalculate_months``); this module writes through the ORM and never calls it,
so its own writes cannot start a run.
"""

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q

from accounting.carryover_math import water_year_of
from accounting.models import CalculationRun, ReportingPeriod
from accounting.recharge_policy import recharge_routes_to_personal
from surface.models import (
    DiversionRecord,
    PointOfDiversion,
    PointOfDiversionDevice,
    PointOfDiversionParcel,
)
from surface.services import (
    _in_months,
    _month_demand,
    _next_month,
    _own_magnitudes,
    _own_total_for_pod,
    field_efficiency,
)

_Q = Decimal("0.0001")
ESTIMATE_METHOD = "estimated_from_use"


# --------------------------------------------------------------------------
# What a person typing a volume needs
# --------------------------------------------------------------------------


def _estimate_records(first, point=None):
    """The estimator's own direct-use records dated anywhere in the calendar month."""
    qs = DiversionRecord.objects.filter(
        _in_months("month", [first.replace(day=1)]),
        diversion_type="direct_use",
        method=ESTIMATE_METHOD,
    )
    if point is not None:
        qs = qs.filter(point_of_diversion=point)
    return qs


def discard_estimate(point, month, diversion_type="direct_use", *, exclude_pk=None):
    """Delete the estimate a point holds for ``month``; return the month it covered, or None.

    A person typing (or importing) a volume for a month that holds an estimate
    replaces it. Call this inside the same transaction as the save, before the
    uniqueness check: the unique key is the exact date, and the estimate is
    dated the 1st, as a typed record is. Only a direct-use estimate exists, so
    any other type returns None and deletes nothing.
    """
    if diversion_type != "direct_use":
        return None
    qs = _estimate_records(month, point)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    found = list(qs)
    if not found:
        return None
    for record in found:
        record.delete()
    return month.replace(day=1)


def replaced_sentence(month):
    """The line a saving page adds when a typed volume took an estimate's place."""
    return f"This replaces the estimate for {month:%B %Y}."


# --------------------------------------------------------------------------
# The estimate
# --------------------------------------------------------------------------


def _device_in_service(point, first, last):
    """True when a device link covers any part of the month, or carries no dates."""
    return PointOfDiversionDevice.objects.filter(
        Q(installed_on__isnull=True) | Q(installed_on__lte=last),
        Q(removed_on__isnull=True) | Q(removed_on__gte=first),
        point_of_diversion=point,
    ).exists()


def _has_typed_record(point, first):
    """True when a person's direct-use volume (any method but the estimate) covers the month."""
    return (
        DiversionRecord.objects.filter(
            _in_months("month", [first]),
            point_of_diversion=point,
            diversion_type="direct_use",
        )
        .exclude(method=ESTIMATE_METHOD)
        .exists()
    )


def _in_direct_season(right, first, last):
    """False only when a direct season is recorded and the month lies wholly outside it."""
    parts = (
        right.direct_season_start_month,
        right.direct_season_start_day,
        right.direct_season_end_month,
        right.direct_season_end_day,
    )
    if any(part is None for part in parts):
        return True
    start = (parts[0], parts[1])
    end = (parts[2], parts[3])
    month_start = (first.month, first.day)
    month_end = (last.month, last.day)
    if start <= end:
        return month_start <= end and month_end >= start
    # The season wraps the year end (November to March, say).
    return month_start <= end or month_end >= start


def _already_used(right, first):
    """Direct-use volume on every point of the right, earlier months of this water year (AF)."""
    water_year = water_year_of(f"{first.year}-{first.month:02d}")
    year_start = date(water_year - 1, 10, 1)
    total = Decimal("0")
    for volume in DiversionRecord.objects.filter(
        point_of_diversion__water_right=right,
        diversion_type="direct_use",
        month__gte=year_start,
        month__lt=first,
    ).values_list("volume_acre_feet", flat=True):
        total += abs(volume)
    return total


def _residual_words(fields):
    """Which of the two ways the engine counts use the supply did not cover, for these fields."""
    wells = {recharge_routes_to_personal(field) for field in fields}
    if wells == {True}:
        return "groundwater"
    if wells == {False}:
        return "unmet"
    return "mixed"


def _store(point, first, volume, text, period):
    """Write or replace the point's estimate for the month; touch nothing that did not change."""
    existing = list(_estimate_records(first, point).order_by("pk"))
    for extra in existing[1:]:
        extra.delete()
    wanted = {
        "month": first,
        "volume_acre_feet": volume,
        "returned_af": Decimal("0"),
        "diversion_type": "direct_use",
        "method": ESTIMATE_METHOD,
        "data_state": "provisional",
        "reporting_period": period,
        "notes": text,
    }
    if not existing:
        return DiversionRecord.objects.create(point_of_diversion=point, **wanted)
    record = existing[0]
    changed = [name for name, value in wanted.items() if getattr(record, name) != value]
    if changed:
        for name in changed:
            setattr(record, name, wanted[name])
        record.save()
    return record


def _drop(point, first):
    """Remove the estimator's own record for the point-month; never any other."""
    for record in _estimate_records(first, point):
        record.delete()


def estimate_month(first, notes):
    """Estimate (or clear) the delivery of every unmetered point for one calendar month.

    ``first`` is the first of the month; ``notes`` is the list the canal split
    also fills, which ``accounting.engine_run`` turns into sentences. Returns
    nothing. Runs inside ``run_month``'s transaction.
    """
    first = first.replace(day=1)
    last = _next_month(first) - timedelta(days=1)
    period = ReportingPeriod.objects.filter(
        start_date__lte=first, end_date__gte=first
    ).first()
    text_month = f"{first.year}-{first.month:02d}"

    ids = set(
        PointOfDiversionParcel.objects.values_list("point_of_diversion_id", flat=True)
    )
    ids |= set(_estimate_records(first).values_list("point_of_diversion_id", flat=True))
    points = (
        PointOfDiversion.objects.filter(pk__in=ids)
        .select_related("water_right")
        .order_by("pk")
    )

    for point in points:
        links = list(
            PointOfDiversionParcel.objects.filter(point_of_diversion=point)
            .select_related("parcel")
            .order_by("id")
        )
        served = [link.parcel for link in links]
        if point.status != "active" or not served:
            _drop(point, first)
            continue
        if _device_in_service(point, first, last) or _has_typed_record(point, first):
            _drop(point, first)
            continue

        right = point.water_right
        if right is None:
            _drop(point, first)
            notes.append({"kind": "estimate_no_right", "pod": point.name})
            continue
        if right.status != "active":
            _drop(point, first)
            notes.append(
                {
                    "kind": "estimate_right_not_active",
                    "pod": point.name,
                    "status": right.get_status_display().lower(),
                }
            )
            continue

        fractions = (
            point.evaporation_fraction + point.seepage_fraction + point.spill_fraction
        )
        if fractions >= 1:
            # Nothing would reach the fields. Write nothing; a record already
            # there makes the canal split stop the month with its own sentence.
            notes.append({"kind": "estimate_losses_too_large", "pod": point.name})
            continue

        own = _own_magnitudes(served, first)
        own_total = _own_total_for_pod(point, own, first)
        free = [field for field in served if field.pk not in own]
        if own_total == 0 and not CalculationRun.objects.filter(
            parcel__in=free, period=text_month
        ).exists():
            # No crop water use for any of its fields yet: nothing to estimate from.
            _drop(point, first)
            continue

        need = Decimal("0")
        for field in free:
            efficiency = field_efficiency(field)[0]
            if efficiency and efficiency > 0:
                need += _month_demand(field, first) / efficiency
        field_need = need.quantize(_Q) + own_total
        headgate = (field_need / (1 - fractions)).quantize(_Q)
        if headgate == 0:
            # The fields used no water this month: the estimate is no delivery,
            # and a 0.00 AF record would only be noise on the canal's page.
            _drop(point, first)
            continue

        written = headgate
        cap_text = ""
        if not _in_direct_season(right, first, last):
            written = Decimal("0.0000")
            cap_text = (
                " Set to 0.00 AF because this month is outside the water "
                "right's direct season."
            )
        elif right.face_value_acre_feet is not None:
            remaining = right.face_value_acre_feet - _already_used(right, first)
            allowed = max(Decimal("0"), remaining).quantize(_Q)
            if allowed < headgate:
                written = allowed
                cap_text = (
                    f" Capped at {allowed:,.2f} AF, what remained of the water "
                    f"right this water year."
                )

        _store(
            point,
            first,
            written,
            f"Estimated from the fields' crop water use: {headgate:,.2f} AF.{cap_text}",
            period,
        )
        notes.append({"kind": "estimate_written", "pod": point.name, "month": first})
        if written < headgate:
            notes.append(
                {
                    "kind": "estimate_capped",
                    "pod": point.name,
                    "month": first,
                    "estimate_af": written,
                    "above_af": headgate - written,
                    "residual": _residual_words(served),
                }
            )
