# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wire the Plan-01 allocation kernel to real recorded data.

This is the v1.10 capability the platform was missing: an unmetered district
records ONE surface delivery total for a month (a ``DiversionRecord``), but the
parcels that point of diversion serves grow different crops with different water
demand. ``allocate_district_delivery`` reads those recorded diversions, finds the
served parcels, pulls each parcel's MEASURED ET demand for the diversion month
(the 54-01 consumptive-use spine), splits the delivery across them with the pure
``accounting.allocation_math.allocate_by_demand`` kernel, and writes the negative
``surface_diversion`` ledger rows the calculation engine's ``subtract_surface_water``
step consumes.

Invariants honored (must agree with the calc engine + the Plan-01 kernel):

* ``surface_diversion`` rows are stored NEGATIVE — a delivered magnitude as a
  negative number (the production convention ``subtract_surface_water`` and the
  CSV importer share). We write ``-share``.
* Demand is read for the SAME month as the diversion record, from
  ``CalculationRun.net_consumptive_use_af`` — the identical signal
  ``accounting.services.parcel_net_consumptive_use`` exposes, scoped to the month
  because allocation is inherently per-month (a summer crop should pull more of
  July's water, and its cap is that month's demand ÷ efficiency).
* No ET demand for any served parcel that month → the kernel returns ``{}`` and we
  FALL BACK to the static ``PointOfDiversionParcel.fraction`` split (the behavior
  of ``create_diversion_ledger_entries``), so a recorded delivery is never
  silently dropped.
* Idempotent: this service OWNS the rows it writes, and only those. Every split
  row carries ``ParcelLedger.divided_from_headgate=True`` (149-01); a re-run
  deletes those rows for the served parcels in the months it touches, then
  writes fresh ones, so a re-run is byte-identical — mirroring
  ``run_calculations`` / ``rollover_allocations`` delete-then-insert. A
  ``surface_diversion`` row with the flag False is a field's OWN recorded
  delivery (typed on the ledger form, or imported): it is never edited or
  deleted here, and the split divides only the REMAINDER of the headgate
  total among the served fields that have none (see
  ``allocate_district_delivery``).
* ``dry_run=True`` returns the would-be rows (unsaved) and writes nothing.

Efficiency is resolved PER PARCEL by ``field_efficiency`` (148-02, S1): a served
parcel with a recorded ``surface.ParcelIrrigationMethod`` (146-05) is capped at
its own method's assigned efficiency; a parcel with no method falls back to the
agency-wide ``SiteConfig.default_irrigation_efficiency`` (55-02). An explicit
``efficiency=`` override on this call still wins for every served parcel, so
the per-parcel lookup only runs when no override is given. Shared-well /
shared-POD apportionment is Phase 56, out of scope here.
"""

import logging
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounting.allocation_math import allocate_by_demand, apportion_shared_supply
from accounting.ledger_words import delivery_share_words
from accounting.models import CalculationRun, WaterType
from parcels.models import ParcelLedger
from surface.models import (
    DiversionRecord,
    PointOfDiversionParcel,
    UnallocatedDelivery,
)

logger = logging.getLogger(__name__)

_Q = Decimal("0.0001")


def field_efficiency(parcel):
    """One parcel's own field efficiency, and where it came from (148-02, S1).

    Returns ``(Decimal, source)``. ``source`` is ``"method"`` when the parcel
    carries a ``ParcelIrrigationMethod`` (146-05's one-to-one, related_name
    ``irrigation``), which gives the assigned efficiency off that method's
    row. Otherwise ``"agency"``, the deployment-wide
    ``SiteConfig.default_irrigation_efficiency``.

    This is the SAME figure ``allocate_district_delivery``'s per-parcel cap and
    ``subtract_surface_water``'s consumption math both read, so the split and
    the subtraction can never drift apart on a mixed-method headgate (a center
    pivot and a furrow field sharing one point of diversion must not share one
    cap; the 146-05 carry).

    ``SiteConfig.objects.first() or SiteConfig()`` rather than ``.get()``
    (the established idiom, ``surface/diversion_import.py``): a real deployment
    always carries exactly one row, but this reads safely before one exists,
    falling back to the field's own class default (0.750) instead of raising.
    """
    # Imported lazily so this module has no load-time dependency on core.
    from core.models import SiteConfig

    link = getattr(parcel, "irrigation", None)
    if link is not None:
        return link.method.assigned_efficiency, "method"
    config = SiteConfig.objects.first() or SiteConfig()
    return config.default_irrigation_efficiency, "agency"


def _resolve_efficiency(efficiency, parcel):
    """The explicit override if given, else this parcel's own field_efficiency."""
    if efficiency is not None:
        return Decimal(str(efficiency))
    return field_efficiency(parcel)[0]


def _month_demand(parcel, month):
    """A parcel's net consumptive use (AF) for the diversion record's month.

    Reads ``CalculationRun.net_consumptive_use_af`` for the parcel-month — the
    same spine signal ``accounting.services.parcel_net_consumptive_use`` sums, but
    scoped to a single ``YYYY-MM`` because the allocation is per diversion record.
    Sums defensively in case more than one run exists for the month; returns
    ``Decimal("0")`` when the engine has not run for that parcel-month (the
    kernel then yields ``{}`` and the caller falls back to the fraction split).
    """
    period = f"{month.year}-{month.month:02d}"
    total = Decimal("0")
    for value in CalculationRun.objects.filter(
        parcel=parcel, period=period
    ).values_list("net_consumptive_use_af", flat=True):
        total += value or Decimal("0")
    return total


def _records_for_period(point_of_diversion, reporting_period, months=None):
    """DiversionRecords on this POD that belong to the reporting period.

    The ``reporting_period`` FK on a record is nullable, so a record counts if
    EITHER its FK matches OR its ``month`` falls inside the period's date span —
    catching both seeded-with-FK and bare monthly records. ``reporting_period``
    of ``None`` returns every record for the POD. ``months`` (an iterable of
    first-of-month dates), when given, narrows the records to those months so
    one month can be allocated alone.
    """
    # Only water delivered for use is divided among fields. A "to storage"
    # record is water put into a reservoir or a recharge basin: it reaches no
    # field that month, and a basin fill is already credited through the
    # recharge ledger, so dividing it onto fields would count it twice
    # (seed_merced_ledgers._seed_recharge_diversion_records; found by 149-01
    # re-running the demonstration year, where it put 85.22 AF of Bottomlands
    # Riparian Take's February basin fill onto its ten fields).
    qs = DiversionRecord.objects.filter(
        point_of_diversion=point_of_diversion, diversion_type="direct_use"
    )
    if months is not None:
        qs = qs.filter(_in_months("month", {_month_start(m) for m in months}))
    if reporting_period is not None:
        qs = qs.filter(
            Q(reporting_period=reporting_period)
            | Q(
                month__gte=reporting_period.start_date,
                month__lte=reporting_period.end_date,
            )
        )
    return qs.order_by("month").distinct()


def _demand_rows(record, shares, pod, sw_type):
    """Unsaved demand-weighted ledger rows (NEGATIVE) for one diversion record."""
    today = timezone.now().date()
    return [
        ParcelLedger(
            parcel=parcel,
            transaction_date=today,
            effective_date=record.month,
            amount_acre_feet=-share,  # NEGATIVE: delivered magnitude (production convention)
            source_type="surface_diversion",
            description=delivery_share_words(record, pod),
            reporting_period=record.reporting_period,
            water_type=sw_type,
            divided_from_headgate=True,
            divided_from_point_pk=pod.pk,
        )
        for parcel, share in shares.items()
    ]


def _fraction_rows(record, served_links, pod, sw_type, total=None):
    """Unsaved static-fraction fallback rows (NEGATIVE) — the no-ET-demand path.

    Builds unsaved instances rather than writing, so ``dry_run`` can preview it
    and the single delete-then-bulk_create path stays idempotent.

    T3 (math eval 2026-07-18): the split now runs through
    ``apportion_shared_supply`` — the SAME normalized kernel the report layer
    uses — instead of multiplying by each link's raw ``fraction``. Raw fractions
    are not guaranteed to sum to 1, and nothing in the model forces them to, so
    the old math invented or lost water whenever they did not:

      * [0.6, 0.6, 0.6] on 100 AF gave 60/60/-20 — the last row took the
        remainder and came out POSITIVE, a phantom supply row on a diversion.
      * The untouched default [1.0, 1.0] gave parcel 1 the entire delivery and
        parcel 2 nothing.

    This path runs whenever no served parcel has ET demand for the month — i.e.
    every month before the engine first runs — so it is the common case, not an
    edge. State filings were already correct (the report layer normalizes), which
    is exactly why the internal ledger could be wrong for the same data without
    anything visibly breaking.

    Passing demand=0 for every member is deliberate and accurate: this is the
    no-demand fallback, so the kernel's ladder resolves to hand-set fractions
    when the district set any, and an even split when they are untouched.
    """
    if total is None:
        total = record.consumed_acre_feet()
    today = timezone.now().date()

    weights = apportion_shared_supply(
        (link.parcel.pk, link.fraction, Decimal("0")) for link in served_links
    )
    if not weights:
        return []

    # Weights are 4dp — the same resolution as the stored fraction field itself
    # (DecimalField(decimal_places=4)), so this claims no more precision than the
    # input carries. They sum to exactly 1.0000; the residual below keeps the
    # AMOUNTS summing to the delivery exactly, which is the invariant that
    # matters (nothing invented, nothing lost).
    amounts = {key: (total * w).quantize(_Q) for key, w in weights.items()}
    residual = total - sum(amounts.values(), Decimal("0"))
    if residual and amounts:
        last_key = sorted(amounts, key=str)[-1]
        amounts[last_key] += residual

    rows = []
    for link in served_links:
        amount = amounts.get(link.parcel.pk)
        if amount is None:
            continue
        rows.append(
            ParcelLedger(
                parcel=link.parcel,
                transaction_date=today,
                effective_date=record.month,
                amount_acre_feet=-amount,
                source_type="surface_diversion",
                description=delivery_share_words(
                    record, pod, fixed_share=weights[link.parcel.pk]
                ),
                reporting_period=record.reporting_period,
                water_type=sw_type,
                divided_from_headgate=True,
                divided_from_point_pk=pod.pk,
            )
        )
    return rows


def _next_month(month):
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def _month_start(day):
    """The first of ``day``'s calendar month.

    A month is a calendar month here, never one exact date: the demonstration
    dates its diversion records and their ledger rows on the 15th, a person may
    type the 1st or the 30th, and all of them are the same month's water.
    """
    return day.replace(day=1)


def _in_months(field, starts):
    """``Q`` matching ``field`` inside any of the calendar months ``starts``."""
    q = Q(pk__in=[])
    for start in starts:
        q |= Q(**{f"{field}__gte": start, f"{field}__lt": _next_month(start)})
    return q


def _own_magnitudes(served, month):
    """``{parcel_pk: AF}`` for served fields with a recorded delivery of their own.

    A field's own delivery is any ``surface_diversion`` row for the month whose
    ``divided_from_headgate`` is False (typed on the ledger form or imported).
    The value is the magnitude of the field's own rows for the month, summed.
    """
    sums = {}
    rows = ParcelLedger.objects.filter(
        parcel__in=served,
        source_type="surface_diversion",
        divided_from_headgate=False,
        effective_date__gte=month,
        effective_date__lt=_next_month(month),
    ).values_list("parcel_id", "amount_acre_feet")
    for parcel_id, amount in rows:
        sums[parcel_id] = sums.get(parcel_id, Decimal("0")) + amount
    return {pk: abs(total) for pk, total in sums.items()}


def _own_total_for_pod(pod, own, month):
    """This point of diversion's share of its served fields' own deliveries (AF).

    A field served by one point contributes its whole own delivery. A field
    served by more than one point contributes to THIS point's total pro rata
    by each serving point's recorded consumed total for the month (each
    point's sum of ``DiversionRecord.consumed_acre_feet()``); when no serving
    point recorded anything that month, the field is split evenly among its
    serving points.
    """
    if not own:
        return Decimal("0")
    links = PointOfDiversionParcel.objects.filter(
        parcel_id__in=list(own)
    ).values_list("parcel_id", "point_of_diversion_id")
    serving = {}
    for parcel_id, pod_id in links:
        serving.setdefault(parcel_id, set()).add(pod_id)
    pod_ids = {pod_id for ids in serving.values() for pod_id in ids} | {pod.pk}
    recorded = {pod_id: Decimal("0") for pod_id in pod_ids}
    for record in DiversionRecord.objects.filter(
        _in_months("month", [month]),
        point_of_diversion_id__in=pod_ids,
        diversion_type="direct_use",
    ):
        recorded[record.point_of_diversion_id] += record.consumed_acre_feet()
    total = Decimal("0")
    for parcel_id, magnitude in own.items():
        ids = serving.get(parcel_id, {pod.pk})
        recorded_sum = sum((recorded[i] for i in ids), Decimal("0"))
        if recorded_sum > 0:
            weight = recorded[pod.pk] / recorded_sum
        else:
            weight = Decimal("1") / len(ids)
        total += magnitude * weight
    return total.quantize(_Q)


def allocate_district_delivery(
    point_of_diversion,
    reporting_period,
    *,
    efficiency=None,
    dry_run=False,
    months=None,
    notes=None,
):
    """Allocate a POD's recorded diversions across served parcels by ET demand.

    For each ``DiversionRecord`` on ``point_of_diversion`` in ``reporting_period``,
    split the recorded delivery across the parcels the POD serves, weighted by each
    parcel's measured net consumptive use for the record's month and capped at
    ``demand / efficiency`` (the Plan-01 kernel). Where no served parcel has ET
    demand that month, fall back to the static ``PointOfDiversionParcel.fraction``
    split. Writes negative ``surface_diversion`` ``ParcelLedger`` rows, each
    marked ``divided_from_headgate=True``.

    **The remainder rule (149-01, Brent 2026-09-28).** A served field with a
    recorded delivery of its own for the month (one or more ``surface_diversion``
    rows with ``divided_from_headgate=False``) keeps it. The split divides only
    the REMAINDER, ``max(0, headgate total - own_total)``, among the served
    fields that have none; own fields get no split row, and an own row is never
    edited or deleted. ``own_total`` is the sum of the own fields' magnitudes,
    except that a field served by more than one point of diversion contributes
    to THIS point's ``own_total`` pro rata by each serving point's recorded
    consumed total for the month (each point's sum of
    ``DiversionRecord.consumed_acre_feet()``), or evenly among its serving
    points when none of them recorded anything that month. Two records on one
    point in one month are treated together: the month's totals are summed, the
    remainder is computed once, and each record takes its share of it in
    proportion to its own consumed total. If ``own_total`` exceeds the headgate
    total, no split rows are written for that month and the excess is reported.

    Args:
        point_of_diversion: a ``surface.models.PointOfDiversion``.
        reporting_period: the ``accounting.models.ReportingPeriod`` to allocate
            (``None`` = every recorded diversion on the POD).
        efficiency: optional irrigation-efficiency override in ``(0, 1]``, applied
            to EVERY served parcel; default is each parcel's own
            ``field_efficiency`` (146-05's ``ParcelIrrigationMethod`` where set,
            else the agency-wide ``SiteConfig.default_irrigation_efficiency``).
        dry_run: when ``True``, return the would-be rows (unsaved) and write nothing.
        months: optional iterable of dates narrowing the records to those
            CALENDAR months (any day in the month names it), so one month can
            be allocated alone. Every month named is cleared of this point's
            split rows even when it has no record left.
        notes: optional list; when given, dicts are appended to it for the
            caller to turn into sentences: ``{"kind": "own_over_headgate",
            "pod": name, "month": date, "excess_af": Decimal}`` (own deliveries
            add up to more than the headgate recorded) and ``{"kind":
            "unallocated", "pod": name, "month": date, "amount_af": Decimal}``
            (headgate water no served field's crop use explains).

    Returns:
        the list of ``ParcelLedger`` rows written (or, for ``dry_run``, the
        unsaved instances that would have been written).
    """
    pod = point_of_diversion
    if months is not None:
        months = list(months)  # read twice below; a generator would be spent

    # Surface deliveries are, by definition, Surface Water. Resolve the type ONCE
    # and stamp it on every row so the ledger's Water Type column is populated for
    # surface rows the way it already is for groundwater. .filter().first() (not
    # .get()) so a fresh DB without the seeded type yields None rather than raising;
    # the seed commands (e.g. seed_merced_ledgers) create it.
    sw_type = WaterType.objects.filter(code="SW").first()

    served_links = list(
        PointOfDiversionParcel.objects.filter(point_of_diversion=pod)
        .select_related("parcel")
        .order_by("id")
    )
    served = [link.parcel for link in served_links]

    # Per-parcel cap (148-02, S1): each served parcel's own field_efficiency,
    # unless the caller passed an explicit override, which wins for every
    # parcel. Resolved once here, not per record, since the served list and
    # each parcel's method do not change across a POD's diversion records.
    eff_by_parcel = {p: _resolve_efficiency(efficiency, p) for p in served}

    records = list(_records_for_period(pod, reporting_period, months))
    by_month = {}
    for record in records:
        by_month.setdefault(_month_start(record.month), []).append(record)

    to_write = []
    unallocated = []
    for month, month_records in by_month.items():
        month_total = sum(
            (r.consumed_acre_feet() for r in month_records), Decimal("0")
        )
        own = _own_magnitudes(served, month)
        own_total = _own_total_for_pod(pod, own, month)
        if own_total > month_total:
            excess = own_total - month_total
            if notes is not None:
                notes.append(
                    {
                        "kind": "own_over_headgate",
                        "pod": pod.name,
                        "month": month,
                        "excess_af": excess,
                    }
                )
            logger.warning(
                "allocate_district_delivery POD=%s month=%s: the fields' own "
                "delivery records add up to %s AF, %s AF more than the headgate "
                "recorded (%s AF). No split rows written for this month.",
                pod.name,
                month,
                own_total,
                excess,
                month_total,
            )
            continue

        free_links = [link for link in served_links if link.parcel.pk not in own]
        free = [link.parcel for link in free_links]

        # Each record's part of the month's remainder. With no own records it
        # is the record's whole consumed total (the pre-149 behavior, exactly).
        remainders = {}
        if own_total == 0:
            for record in month_records:
                remainders[record.pk] = record.consumed_acre_feet()
        else:
            remainder_total = month_total - own_total
            running = Decimal("0")
            for record in month_records[:-1]:
                part = (
                    remainder_total * record.consumed_acre_feet() / month_total
                ).quantize(_Q)
                remainders[record.pk] = part
                running += part
            remainders[month_records[-1].pk] = remainder_total - running

        for record in month_records:
            delivery_total = remainders[record.pk]
            if own_total > 0 and delivery_total == 0:
                continue  # the own records already account for the headgate
            demand_by_parcel = {p: _month_demand(p, record.month) for p in free}
            shares = allocate_by_demand(
                delivery_total,
                demand_by_parcel,
                {p: eff_by_parcel[p] for p in free},
            )

            if shares:
                to_write.extend(_demand_rows(record, shares, pod, sw_type))
                path = "demand-weighted"

                # T4 (math eval 2026-07-18): in the AMPLE case the kernel hands
                # out each parcel's cap and documents that the caller routes the
                # leftover — and this, the only caller, never did. The surplus
                # vanished: no row, no pool, no log, so the internal ledger
                # silently disagreed with the DiversionRecord CalWATRS files
                # from. Record it explicitly against the POD instead of
                # dropping it or inventing a destination. (149-01: against the
                # remainder, the headgate water the own records do not cover.)
                surplus = delivery_total - sum(shares.values(), Decimal("0"))
            else:
                to_write.extend(
                    _fraction_rows(record, free_links, pod, sw_type, delivery_total)
                )
                path = "static-fraction fallback (no ET demand)"
                # Every served field has its own record: nobody is left for the
                # remainder to go to, so it is unexplained headgate water.
                surplus = (
                    delivery_total if served and not free else Decimal("0")
                )

            if surplus > 0:
                unallocated.append(
                    UnallocatedDelivery(
                        point_of_diversion=pod,
                        reporting_period=record.reporting_period,
                        month=record.month,
                        amount_acre_feet=surplus,
                        delivery_acre_feet=delivery_total,
                    )
                )
                if notes is not None:
                    notes.append(
                        {
                            "kind": "unallocated",
                            "pod": pod.name,
                            "month": record.month,
                            "amount_af": surplus,
                        }
                    )
                logger.warning(
                    "allocate_district_delivery POD=%s month=%s: %s AF of %s AF "
                    "delivered is not explained by crop demand — recorded as "
                    "unallocated delivery. Check the diversion volume, the ET "
                    "estimate, and any non-crop use at this POD.",
                    pod.name,
                    record.month,
                    surplus,
                    delivery_total,
                )
            logger.info(
                "allocate_district_delivery POD=%s month=%s: %s (%d parcels, %s AF)",
                pod.name,
                record.month,
                path,
                len(free),
                delivery_total,
            )

    if dry_run:
        return to_write

    # Idempotency: this service owns the rows IT wrote (divided_from_headgate)
    # for its served parcels in the months it just allocated. Delete them up
    # front (ONCE for the whole month set — not per record, so two records
    # sharing a month don't clobber each other), then write fresh, mirroring
    # run_calculations. A field's own recorded delivery is never touched.
    #
    # Only THIS point's shares are replaced (``divided_from_point_pk``), so a
    # field two points serve keeps the other point's share. A split row written
    # before 149-01 carries no point and is replaced by whichever serving point
    # runs first, as every split row was before.
    #
    # When ``months`` is given, every asked-for month is cleared even if the
    # point has no record left in it: a deleted diversion record must take its
    # shares with it, not leave them standing.
    months_to_clear = {_month_start(record.month) for record in records}
    if months is not None:
        months_to_clear |= {_month_start(m) for m in months}
    with transaction.atomic():
        if served and months_to_clear:
            ParcelLedger.objects.filter(
                Q(divided_from_point_pk=pod.pk) | Q(divided_from_point_pk__isnull=True),
                _in_months("effective_date", months_to_clear),
                parcel__in=served,
                source_type="surface_diversion",
                divided_from_headgate=True,
            ).delete()
        # Unallocated surplus is owned by this service for the same POD-months,
        # and is cleared on every run so a re-allocation that now balances does
        # not leave a stale surplus behind.
        if months_to_clear:
            UnallocatedDelivery.objects.filter(
                _in_months("month", months_to_clear), point_of_diversion=pod
            ).delete()
            if unallocated:
                UnallocatedDelivery.objects.bulk_create(unallocated)
        return list(ParcelLedger.objects.bulk_create(to_write))
