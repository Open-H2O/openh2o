# SPDX-License-Identifier: AGPL-3.0-or-later
"""Wire the Plan-01 allocation kernel to real recorded data.

This is the v1.10 capability the platform was missing: an unmetered district
records ONE surface delivery total for a month (a ``DiversionRecord``), but the
parcels that point of diversion serves grow different crops with different water
demand. ``allocate_district_delivery`` reads those recorded diversions, finds the
served parcels, pulls each parcel's MEASURED ET demand for the diversion month
(the consumptive-use spine), splits the delivery across them with the pure
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
* The point's ``division_method`` picks the rule. "shares" (the default) divides
  by the ``PointOfDiversionParcel.fraction`` the district entered, or by the
  fields' acreage where it entered none, and books all of it. "crop_need" is the
  demand-weighted split below; with no ET demand for any served parcel that
  month the kernel returns ``{}`` and the shares split is used instead, so a
  recorded delivery is never silently dropped.
* Idempotent: this service OWNS the rows it writes, and only those. Every split
  row carries ``ParcelLedger.divided_from_headgate=True``; a re-run
  deletes those rows for the served parcels in the months it touches, then
  writes fresh ones, so a re-run is byte-identical — mirroring
  ``run_calculations`` / ``rollover_allocations`` delete-then-insert. A
  ``surface_diversion`` row with the flag False is a field's OWN recorded
  delivery (typed on the ledger form, or imported): it is never edited or
  deleted here, and the split divides only the REMAINDER of the headgate
  total among the served fields that have none (see
  ``allocate_district_delivery``).
* ``dry_run=True`` returns the would-be rows (unsaved) and writes nothing.
* Canal losses come off the top. The point's evaporation, seepage and
  spill fractions are taken from the month's consumed total before anything is
  divided; the remainder rule and the split start from what is left
  (``available``). Evaporation and spill are written off, credited to no one.
  Seepage is deposited to the district's seepage pool as a signed change
  against the last run's deposit, so a re-run never deposits twice. Each
  point-month's figures are stored on ``CanalMonthLoss`` for the canal's page.

Efficiency is resolved PER PARCEL by ``parcels.services.field_efficiency``
(in ``parcels``): a served
parcel with a recorded ``parcels.ParcelIrrigationMethod`` is capped at
its own method's assigned efficiency; a parcel with no method falls back to the
agency-wide ``SiteConfig.default_irrigation_efficiency``. An explicit
``efficiency=`` override on this call still wins for every served parcel, so
the per-parcel lookup only runs when no override is given. Shared-well /
shared-POD apportionment is out of scope here.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounting.allocation_math import allocate_by_demand, apportion_shared_supply
from accounting.carryover_math import water_year_of
from accounting.ledger_words import delivery_share_words, percent_words
from accounting.models import CalculationRun, ReportingPeriod, WaterType
from accounting.services import (
    CONVEYANCE_SEEPAGE_POOL,
    deposit_to_basin_pool,
    parcel_pool_zone,
)
from parcels.models import Parcel, ParcelLedger
from parcels.services import field_efficiency
from surface.models import (
    CanalMonthLoss,
    DiversionRecord,
    PointOfDiversion,
    PointOfDiversionParcel,
    UnallocatedDelivery,
)

if TYPE_CHECKING:
    from django.db.models import QuerySet

    from geography.models import Zone

logger = logging.getLogger(__name__)

_Q = Decimal("0.0001")


def _resolve_efficiency(efficiency: Decimal | float | None, parcel: Parcel) -> Decimal:
    """The explicit override if given, else this parcel's own field_efficiency."""
    if efficiency is not None:
        return Decimal(str(efficiency))
    return field_efficiency(parcel)[0]


def _month_demand(parcel: Parcel, month: date) -> Decimal:
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


def _records_for_period(
    point_of_diversion: PointOfDiversion,
    reporting_period: ReportingPeriod | None,
    months: Iterable[date] | None = None,
) -> QuerySet[DiversionRecord]:
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
    # (see seed_merced_ledgers._seed_recharge_diversion_records).
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


def _demand_rows(
    record: DiversionRecord,
    shares: dict[Parcel, Decimal],
    pod: PointOfDiversion,
    sw_type: WaterType | None,
    loss_fraction: Decimal | None = None,
) -> list[ParcelLedger]:
    """Unsaved demand-weighted ledger rows (NEGATIVE) for one diversion record."""
    today = timezone.now().date()
    return [
        ParcelLedger(
            parcel=parcel,
            transaction_date=today,
            effective_date=record.month,
            amount_acre_feet=-share,  # NEGATIVE: delivered magnitude (production convention)
            source_type="surface_diversion",
            description=delivery_share_words(
                record, pod, loss_fraction=loss_fraction
            ),
            reporting_period=record.reporting_period,
            water_type=sw_type,
            divided_from_headgate=True,
            divided_from_point_pk=pod.pk,
        )
        for parcel, share in shares.items()
    ]


def _fraction_rows(
    record: DiversionRecord,
    served_links: list[PointOfDiversionParcel],
    pod: PointOfDiversion,
    sw_type: WaterType | None,
    total: Decimal | None = None,
    loss_fraction: Decimal | None = None,
) -> list[ParcelLedger]:
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

    # The shares the district entered win; where it entered none, the fields'
    # acreage divides the water (the ladder's demand rung, fed acres).
    weights = apportion_shared_supply(
        (link.parcel.pk, link.fraction, link.parcel.area_acres or Decimal("0"))
        for link in served_links
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
                    record,
                    pod,
                    fixed_share=weights[link.parcel.pk],
                    loss_fraction=loss_fraction,
                ),
                reporting_period=record.reporting_period,
                water_type=sw_type,
                divided_from_headgate=True,
                divided_from_point_pk=pod.pk,
            )
        )
    return rows


def _next_month(month: date) -> date:
    return date(month.year + (month.month == 12), month.month % 12 + 1, 1)


def _month_start(day: date) -> date:
    """The first of ``day``'s calendar month.

    A month is a calendar month here, never one exact date: the demonstration
    dates its diversion records and their ledger rows on the 15th, a person may
    type the 1st or the 30th, and all of them are the same month's water.
    """
    return day.replace(day=1)


def _in_months(field: str, starts: Iterable[date]) -> Q:
    """``Q`` matching ``field`` inside any of the calendar months ``starts``."""
    q = Q(pk__in=[])
    for start in starts:
        q |= Q(**{f"{field}__gte": start, f"{field}__lt": _next_month(start)})
    return q


def _own_magnitudes(served: list[Parcel], month: date) -> dict[int, Decimal]:
    """``{parcel_pk: AF}`` for served fields with a recorded delivery of their own.

    A field's own delivery is any ``surface_diversion`` row for the month whose
    ``divided_from_headgate`` is False (typed on the ledger form or imported).
    The value is the magnitude of the field's own rows for the month, summed.
    """
    sums: dict[int, Decimal] = {}
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


def _own_total_for_pod(
    pod: PointOfDiversion, own: dict[int, Decimal], month: date
) -> Decimal:
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
    serving: dict[int, set[int]] = {}
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


class CanalLossesTooLarge(ValueError):
    """A point's three loss shares leave nothing for the fields in a month.

    ``sentence`` is the plain sentence ``accounting.engine_run`` shows as the
    reason the month stopped. The point's form refuses such shares, so this is
    reached only by data saved some other way.
    """

    def __init__(self, sentence: str) -> None:
        super().__init__(sentence)
        self.sentence = sentence


def _month_losses(
    pod: PointOfDiversion, month: date, diverted: Decimal
) -> dict[str, Decimal]:
    """The month's canal losses off the top of ``diverted``.

    Each loss is the point's own fraction of the consumed total, to four
    places; ``available`` is what is left and carries the rounding residual,
    so the four figures add back to ``diverted`` exactly. Raises
    :class:`CanalLossesTooLarge` when the three fractions together reach the
    whole.
    """
    total_fraction = (
        pod.evaporation_fraction + pod.seepage_fraction + pod.spill_fraction
    )
    if total_fraction >= 1:
        raise CanalLossesTooLarge(
            f"In {month:%B %Y}, the evaporation, seepage and spill shares at "
            f"{pod.name} add up to {percent_words(total_fraction)}% of the "
            f"diverted water and leave nothing for the fields."
        )
    evaporation = (diverted * pod.evaporation_fraction).quantize(_Q)
    seepage = (diverted * pod.seepage_fraction).quantize(_Q)
    spill = (diverted * pod.spill_fraction).quantize(_Q)
    return {
        "diverted_af": diverted,
        "evaporation_af": evaporation,
        "seepage_af": seepage,
        "spill_af": spill,
        "available_af": diverted - evaporation - seepage - spill,
        "loss_fraction": total_fraction,
    }


def _zone_containing(pod: PointOfDiversion) -> Zone | None:
    """The management-area zone that contains the point's location, or None."""
    from geography.models import Zone

    if pod.location is None:
        return None
    return (
        Zone.objects.filter(zone_type="management_area", geometry__contains=pod.location)
        .order_by("pk")
        .first()
    )


def _seepage_zone(
    contained: Zone | None, month_shares: dict[Parcel, Decimal] | None, month: date | None = None
) -> Zone | None:
    """The zone a point-month's seepage goes to, or None.

    The zone that contains the point; failing that, the pool zone of the
    served field that took the largest share that month
    (``accounting.services.parcel_pool_zone``, the function the incidental pool
    uses), read for the zone membership in force in ``month``. ``month_shares``
    is ``{parcel: AF}`` for the month's split rows.
    """
    if contained is not None:
        return contained
    if not month_shares:
        return None
    biggest = sorted(month_shares.items(), key=lambda kv: (-kv[1], kv[0].pk))[0][0]
    return parcel_pool_zone(biggest, month)


def _settle_seepage(zone: Zone, water_year: int, delta: Decimal) -> None:
    """One signed change to the seepage pool; a row that nets to zero is removed."""
    if delta == 0:
        return
    water_type, _ = WaterType.objects.get_or_create(
        code="GW", defaults={"name": "Groundwater"}
    )
    row = deposit_to_basin_pool(
        zone, water_type, water_year, delta, origin=CONVEYANCE_SEEPAGE_POOL
    )
    if row.amount_af == Decimal("0"):
        row.delete()


def _store_seepage_credits(
    pod: PointOfDiversion,
    month: date,
    loss: dict[str, Decimal] | None,
    served: list[Parcel],
) -> None:
    """Replace the water-account credits this point-month's seepage earns.

    What the credit is depends on ``SiteConfig.canal_seepage_credit``. "none"
    (the default) writes nothing: the seepage stays the basin's pool row.
    "by_acre" shares the month's seepage less the share left in the basin
    among the served fields by acre, each part going to that field's water
    account in force that month; a field with no account has its part credited
    to no one. "owner" credits the point's owner account the whole of it less the
    share left in the basin, and no one when the point names no owner. The
    rows are keyed to the point and month, so a re-run, a changed setting or a
    month with no record left replaces or clears exactly them.
    """
    from accounting.services import leave_behind_share, parcel_account, replace_account_credits
    from core.models import SiteConfig

    config = SiteConfig.objects.first()
    choice = config.canal_seepage_credit if config else "none"
    key = f"canal_seepage:{pod.pk}:{month:%Y-%m}"
    seepage = loss["seepage_af"] if loss is not None else Decimal("0")
    credits: list[tuple[Any, WaterType, int, Decimal, str]] = []
    if choice != "none" and seepage > 0:
        water_type, _ = WaterType.objects.get_or_create(
            code="GW", defaults={"name": "Groundwater"}
        )
        water_year = water_year_of(f"{month.year}-{month.month:02d}")
        kept = seepage * (1 - leave_behind_share())
        line = f"Canal seepage from {pod.name}, {month:%B %Y}"
        if choice == "owner":
            if pod.owner_account is not None:
                credits.append((pod.owner_account, water_type, water_year, kept, line))
        else:
            acres = {p.pk: (p.area_acres or Decimal("0")) for p in served}
            whole = sum(acres.values(), Decimal("0"))
            if whole == 0:
                acres = {p.pk: Decimal("1") for p in served}
                whole = Decimal(len(served))
            by_account: dict[Any, Decimal] = {}
            for field in served:
                account = parcel_account(field, month)
                if account is not None:
                    by_account[account] = by_account.get(account, Decimal("0")) + (
                        kept * acres[field.pk] / whole
                    )
            credits = [
                (account, water_type, water_year, amount, line)
                for account, amount in sorted(by_account.items(), key=lambda kv: kv[0].pk)
            ]
    replace_account_credits("canal_seepage", key, credits)


def _store_month_loss(
    pod: PointOfDiversion,
    month: date,
    loss: dict[str, Decimal] | None,
    zone: Zone | None,
) -> None:
    """Write (or clear) one point-month's ``CanalMonthLoss`` and settle its seepage.

    The pool change is a signed delta against what the previous row for this
    point-month deposited: the new seepage less the old when the zone and year
    are unchanged; otherwise the old amount comes back out of the old zone and
    the new one goes in whole. ``loss`` of ``None`` means the month has no
    direct-use record left: the row goes and its deposit is reversed.
    """
    prior = CanalMonthLoss.objects.filter(point_of_diversion=pod, month=month).first()
    old_zone = prior.seepage_zone if prior is not None else None
    old_year = prior.seepage_water_year if old_zone is not None else None
    old_amount = prior.seepage_af if old_zone is not None else Decimal("0")

    if loss is None:
        new_zone, new_year, new_amount = None, None, Decimal("0")
    else:
        new_zone = zone
        new_year = water_year_of(f"{month.year}-{month.month:02d}") if zone else None
        new_amount = loss["seepage_af"] if zone else Decimal("0")

    if (
        old_zone is not None
        and new_zone is not None
        and old_zone.pk == new_zone.pk
        and old_year == new_year
    ):
        _settle_seepage(new_zone, new_year, new_amount - old_amount)
    else:
        if old_zone is not None:
            _settle_seepage(old_zone, old_year, -old_amount)
        if new_zone is not None:
            _settle_seepage(new_zone, new_year, new_amount)

    if loss is None:
        if prior is not None:
            prior.delete()
        return
    CanalMonthLoss.objects.update_or_create(
        point_of_diversion=pod,
        month=month,
        defaults={
            "diverted_af": loss["diverted_af"],
            "evaporation_af": loss["evaporation_af"],
            "seepage_af": loss["seepage_af"],
            "spill_af": loss["spill_af"],
            "available_af": loss["available_af"],
            "own_af": loss.get("own_af", Decimal("0")),
            "unserved_af": loss.get("unserved_af", Decimal("0")),
            "seepage_zone": new_zone,
            "seepage_water_year": new_year,
        },
    )


def _surface_water_type() -> WaterType | None:
    """The Surface Water type stamped on every split row, or None on an unseeded database."""
    # Surface deliveries are, by definition, Surface Water. Resolve the type ONCE
    # and stamp it on every row so the ledger's Water Type column is populated for
    # surface rows the way it already is for groundwater. .filter().first() (not
    # .get()) so a fresh DB without the seeded type yields None rather than raising;
    # the seed commands (e.g. seed_merced_ledgers) create it.
    return WaterType.objects.filter(code="SW").first()


def _served_links(pod: PointOfDiversion) -> list[PointOfDiversionParcel]:
    """The point's parcel links in creation order, each with its parcel loaded."""
    return list(
        PointOfDiversionParcel.objects.filter(point_of_diversion=pod)
        .select_related("parcel")
        .order_by("id")
    )


def _plan_allocation(
    pod: PointOfDiversion,
    reporting_period: ReportingPeriod | None,
    months: list[date] | None,
    efficiency: Decimal | float | None,
    notes: list[dict[str, Any]] | None,
) -> tuple[
    list[DiversionRecord],
    list[Parcel],
    list[ParcelLedger],
    list[UnallocatedDelivery],
    dict[date, dict[str, Decimal]],
]:
    """Work out every month's rows, unallocated surplus and canal losses; writes nothing.

    Returns ``(records, served parcels, rows to write, surplus rows, losses by month)``.
    """
    sw_type = _surface_water_type()
    served_links = _served_links(pod)
    served = [link.parcel for link in served_links]

    # Per-parcel cap: each served parcel's own field_efficiency,
    # unless the caller passed an explicit override, which wins for every
    # parcel. Resolved once here, not per record, since the served list and
    # each parcel's method do not change across a POD's diversion records.
    eff_by_parcel = {p: _resolve_efficiency(efficiency, p) for p in served}

    records = list(_records_for_period(pod, reporting_period, months))
    by_month: dict[date, list[DiversionRecord]] = {}
    for record in records:
        by_month.setdefault(_month_start(record.month), []).append(record)

    to_write: list[ParcelLedger] = []
    unallocated: list[UnallocatedDelivery] = []
    losses: dict[date, dict[str, Decimal]] = {}
    for month, month_records in by_month.items():
        losses[month] = _allocate_month(
            pod,
            month,
            month_records,
            served_links,
            eff_by_parcel,
            sw_type,
            notes,
            to_write,
            unallocated,
        )
    return records, served, to_write, unallocated, losses


def _allocate_month(
    pod: PointOfDiversion,
    month: date,
    month_records: list[DiversionRecord],
    served_links: list[PointOfDiversionParcel],
    eff_by_parcel: dict[Parcel, Decimal],
    sw_type: WaterType | None,
    notes: list[dict[str, Any]] | None,
    to_write: list[ParcelLedger],
    unallocated: list[UnallocatedDelivery],
) -> dict[str, Decimal]:
    """Divide one calendar month's records; extend ``to_write`` and ``unallocated``, return the month's losses."""
    served = [link.parcel for link in served_links]
    month_total = sum(
        (r.consumed_acre_feet() for r in month_records), Decimal("0")
    )
    # Canal losses come off the top. Computed for every month
    # before anything is divided or written, so a point whose shares leave
    # nothing for the fields raises with nothing changed.
    loss = _month_losses(pod, month, month_total)
    available = loss["available_af"]
    lost = loss["diverted_af"] - available
    if notes is not None and (loss["evaporation_af"] or loss["spill_af"]):
        notes.append(
            {
                "kind": "canal_losses",
                "pod": pod.name,
                "month": month,
                "evaporation_af": loss["evaporation_af"],
                "spill_af": loss["spill_af"],
            }
        )

    if not served_links:
        # A point that serves no field has nobody to divide the water among.
        # What is left after its losses is kept as its own figure (the canal
        # page names where it went) and credits no one: no ledger row, no
        # recharge event, no account credit, no unallocated delivery.
        loss["own_af"] = Decimal("0")
        loss["unserved_af"] = available
        return loss

    own = _own_magnitudes(served, month)
    own_total = _own_total_for_pod(pod, own, month)
    loss["own_af"] = own_total
    if own_total > available:
        _report_own_over_headgate(
            pod, month, own_total, available, lost, month_total, notes
        )
        return loss

    free_links = [link for link in served_links if link.parcel.pk not in own]
    free = [link.parcel for link in free_links]
    remainders = _record_remainders(
        month_records, available, own_total, month_total
    )
    for record in month_records:
        delivery_total = remainders[record.pk]
        if delivery_total == 0:
            # Nothing to divide: the own records already account for the
            # headgate, or the point delivered nothing (a typed 0, which is
            # how a month with no delivery is recorded). A
            # split row of 0 would put a delivery on each field's ledger
            # that never happened.
            continue
        rows, path, surplus = _split_record(
            pod,
            record,
            delivery_total,
            served,
            free,
            free_links,
            eff_by_parcel,
            sw_type,
            loss["loss_fraction"],
        )
        to_write.extend(rows)
        if surplus > 0:
            _record_unallocated(
                pod, record, delivery_total, surplus, unallocated, notes
            )
        logger.info(
            "allocate_district_delivery POD=%s month=%s: %s (%d parcels, %s AF)",
            pod.name,
            record.month,
            path,
            len(free),
            delivery_total,
        )
    return loss


def _report_own_over_headgate(
    pod: PointOfDiversion,
    month: date,
    own_total: Decimal,
    available: Decimal,
    lost: Decimal,
    month_total: Decimal,
    notes: list[dict[str, Any]] | None,
) -> None:
    """Note and log a month whose fields' own deliveries exceed what the headgate has left."""
    excess = own_total - available
    if notes is not None:
        notes.append(
            {
                "kind": "own_over_headgate",
                "pod": pod.name,
                "month": month,
                "excess_af": excess,
                "lost_af": lost,
            }
        )
    logger.warning(
        "allocate_district_delivery POD=%s month=%s: the fields' own "
        "delivery records add up to %s AF, %s AF more than the %s AF "
        "left of the headgate's %s AF after canal losses. No split "
        "rows written for this month.",
        pod.name,
        month,
        own_total,
        excess,
        available,
        month_total,
    )


def _record_remainders(
    month_records: list[DiversionRecord],
    available: Decimal,
    own_total: Decimal,
    month_total: Decimal,
) -> dict[int, Decimal]:
    """Each record's part (by pk) of the month's remainder to divide among the free fields."""
    # Each record's part of the month's remainder. With no own records and
    # no losses it is the record's whole consumed total (the pre-149
    # behavior, exactly).
    remainders: dict[int, Decimal] = {}
    if own_total == 0 and available == month_total:
        for record in month_records:
            remainders[record.pk] = record.consumed_acre_feet()
    else:
        remainder_total = available - own_total
        running = Decimal("0")
        for record in month_records[:-1]:
            part = (
                remainder_total * record.consumed_acre_feet() / month_total
            ).quantize(_Q)
            remainders[record.pk] = part
            running += part
        remainders[month_records[-1].pk] = remainder_total - running
    return remainders


def _split_record(
    pod: PointOfDiversion,
    record: DiversionRecord,
    delivery_total: Decimal,
    served: list[Parcel],
    free: list[Parcel],
    free_links: list[PointOfDiversionParcel],
    eff_by_parcel: dict[Parcel, Decimal],
    sw_type: WaterType | None,
    loss_fraction: Decimal,
) -> tuple[list[ParcelLedger], str, Decimal]:
    """Split one record's remainder over the free fields; return (rows, path taken, surplus).

    The point's ``division_method`` picks the rule. "shares" (the default)
    divides everything by the shares the district entered, or by acreage where
    it entered none, so all of it is booked to the fields. "crop_need" divides
    by each field's crop need, capped at need over efficiency, and what no cap
    takes is the surplus.
    """
    if pod.division_method != "crop_need":
        rows = _fraction_rows(
            record, free_links, pod, sw_type, delivery_total, loss_fraction
        )
        surplus = delivery_total if served and not free else Decimal("0")
        return rows, "shares entered, or acreage", surplus
    demand_by_parcel = {p: _month_demand(p, record.month) for p in free}
    shares = allocate_by_demand(
        delivery_total,
        demand_by_parcel,
        {p: eff_by_parcel[p] for p in free},
    )

    if shares:
        rows = _demand_rows(record, shares, pod, sw_type, loss_fraction)
        path = "demand-weighted"

        # T4 (math eval 2026-07-18): in the AMPLE case the kernel hands
        # out each parcel's cap and documents that the caller routes the
        # leftover — and this, the only caller, never did. The surplus
        # vanished: no row, no pool, no log, so the internal ledger
        # silently disagreed with the DiversionRecord CalWATRS files
        # from. Record it explicitly against the POD instead of
        # dropping it or inventing a destination. (Against the
        # remainder, the headgate water the own records do not cover.)
        surplus = delivery_total - sum(shares.values(), Decimal("0"))
    else:
        rows = _fraction_rows(
            record,
            free_links,
            pod,
            sw_type,
            delivery_total,
            loss_fraction,
        )
        path = "static-fraction fallback (no ET demand)"
        # Every served field has its own record: nobody is left for the
        # remainder to go to, so it is unexplained headgate water.
        surplus = delivery_total if served and not free else Decimal("0")
    return rows, path, surplus


def _record_unallocated(
    pod: PointOfDiversion,
    record: DiversionRecord,
    delivery_total: Decimal,
    surplus: Decimal,
    unallocated: list[UnallocatedDelivery],
    notes: list[dict[str, Any]] | None,
) -> None:
    """Queue an ``UnallocatedDelivery`` for a record's surplus, note it and log a warning."""
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


def _seepage_zones(
    pod: PointOfDiversion,
    to_write: list[ParcelLedger],
    losses: dict[date, dict[str, Decimal]],
    notes: list[dict[str, Any]] | None,
) -> dict[date, Zone | None]:
    """Where each month's seepage goes, noting the months that have no zone to take it."""
    # Where each month's seepage goes: read-only, so a dry run can say so too.
    contained = _zone_containing(pod)
    month_shares: dict[date, dict[Parcel, Decimal]] = {}
    for row in to_write:
        per_parcel = month_shares.setdefault(_month_start(row.effective_date), {})
        # split rows are stored negative; a share is the magnitude
        per_parcel[row.parcel] = (
            per_parcel.get(row.parcel, Decimal("0")) - row.amount_acre_feet
        )
    seepage_zones: dict[date, Zone | None] = {}
    for month, loss in losses.items():
        zone = _seepage_zone(contained, month_shares.get(month), month)
        seepage_zones[month] = zone
        if zone is None and loss["seepage_af"] > 0 and notes is not None:
            notes.append(
                {
                    "kind": "seepage_no_zone",
                    "pod": pod.name,
                    "month": month,
                    "amount_af": loss["seepage_af"],
                }
            )
    return seepage_zones


def _store_allocation(
    pod: PointOfDiversion,
    months: list[date] | None,
    records: list[DiversionRecord],
    served: list[Parcel],
    to_write: list[ParcelLedger],
    unallocated: list[UnallocatedDelivery],
    losses: dict[date, dict[str, Decimal]],
    seepage_zones: dict[date, Zone | None],
) -> list[ParcelLedger]:
    """Replace this point's split rows, surplus rows and canal-loss rows for the months touched."""
    # Idempotency: this service owns the rows IT wrote (divided_from_headgate)
    # for its served parcels in the months it just allocated. Delete them up
    # front (ONCE for the whole month set — not per record, so two records
    # sharing a month don't clobber each other), then write fresh, mirroring
    # run_calculations. A field's own recorded delivery is never touched.
    #
    # Only THIS point's shares are replaced (``divided_from_point_pk``), so a
    # field two points serve keeps the other point's share. A split row written
    # before the column existed carries no point and is replaced by whichever
    # serving point runs first, as every split row was before.
    #
    # When ``months`` is given, every asked-for month is cleared even if the
    # point has no record left in it: a deleted diversion record must take its
    # shares with it, not leave them standing.
    months_to_clear = {_month_start(record.month) for record in records}
    if months is not None:
        months_to_clear |= {_month_start(m) for m in months}
    with transaction.atomic():
        if months_to_clear:
            ParcelLedger.objects.filter(
                Q(divided_from_point_pk=pod.pk)
                | Q(divided_from_point_pk__isnull=True, parcel__in=served),
                _in_months("effective_date", months_to_clear),
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
        # Canal losses and the seepage pool, for every month named or recorded
        # (a month with no record left has its row removed and its seepage
        # taken back out of the pool).
        for month in sorted(months_to_clear):
            _store_month_loss(pod, month, losses.get(month), seepage_zones.get(month))
            _store_seepage_credits(pod, month, losses.get(month), served)
        return list(ParcelLedger.objects.bulk_create(to_write))


def allocate_district_delivery(
    point_of_diversion: PointOfDiversion,
    reporting_period: ReportingPeriod | None,
    *,
    efficiency: Decimal | float | None = None,
    dry_run: bool = False,
    months: Iterable[date] | None = None,
    notes: list[dict[str, Any]] | None = None,
) -> list[ParcelLedger]:
    """Allocate a POD's recorded diversions across the parcels it serves.

    By default (``division_method`` "shares") each month's water is divided by
    the shares the district entered, or by acreage where it entered none, and
    all of it is booked to the fields. When the point is set to "crop_need" the
    split is by ET demand as described next. For each ``DiversionRecord`` on ``point_of_diversion`` in ``reporting_period``,
    split the recorded delivery across the parcels the POD serves, weighted by each
    parcel's measured net consumptive use for the record's month and capped at
    ``demand / efficiency`` (the Plan-01 kernel). Where no served parcel has ET
    demand that month, fall back to the static ``PointOfDiversionParcel.fraction``
    split. Writes negative ``surface_diversion`` ``ParcelLedger`` rows, each
    marked ``divided_from_headgate=True``.

    **Canal losses come off the top.** Per point and calendar month,
    the consumed total the split starts from is the month's direct-use records'
    ``consumed_acre_feet()`` summed (``diverted``). The point's evaporation,
    seepage and spill fractions are taken from it to four places and
    ``available = diverted - evaporation - seepage - spill`` (the rounding
    residual lands on ``available``). Everything below, the remainder rule, the
    leftover canal water and each record's proportional part, works from
    ``available``: a field's own recorded delivery is water that already survived
    the canal, so it is subtracted from ``available``, not from ``diverted``.
    Fractions that reach 1 between them raise :class:`CanalLossesTooLarge` (a
    ``ValueError``) and nothing is written. Evaporation and spill are written
    off. Seepage is deposited to the pool of the management-area zone that
    contains the point (else the pool zone of the served field with the largest
    share that month) as a signed change against the stored ``CanalMonthLoss``
    row, and the figures of each month are stored there (replaced on every run,
    removed when the month has no record left).

    **The remainder rule.** A served field with a
    recorded delivery of its own for the month (one or more ``surface_diversion``
    rows with ``divided_from_headgate=False``) keeps it. The split divides only
    the REMAINDER, ``max(0, available - own_total)``, among the served
    fields that have none; own fields get no split row, and an own row is never
    edited or deleted. ``own_total`` is the sum of the own fields' magnitudes,
    except that a field served by more than one point of diversion contributes
    to THIS point's ``own_total`` pro rata by each serving point's recorded
    consumed total for the month (each point's sum of
    ``DiversionRecord.consumed_acre_feet()``), or evenly among its serving
    points when none of them recorded anything that month. Two records on one
    point in one month are treated together: the month's totals are summed, the
    remainder is computed once, and each record takes its share of it in
    proportion to its own consumed total. If ``own_total`` exceeds ``available``,
    no split rows are written for that month and the excess is reported.

    Args:
        point_of_diversion: a ``surface.models.PointOfDiversion``.
        reporting_period: the ``accounting.models.ReportingPeriod`` to allocate
            (``None`` = every recorded diversion on the POD).
        efficiency: optional irrigation-efficiency override in ``(0, 1]``, applied
            to EVERY served parcel; default is each parcel's own
            ``field_efficiency`` (the ``ParcelIrrigationMethod`` where set,
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
            (headgate water no served field's crop use explains), ``{"kind":
            "canal_losses", "pod": name, "month": date, "evaporation_af":
            Decimal, "spill_af": Decimal}`` (written off, only when either is
            above zero) and ``{"kind": "seepage_no_zone", "pod": name,
            "month": date, "amount_af": Decimal}`` (seepage with no zone to
            take it). An ``own_over_headgate`` note also carries ``lost_af``,
            the month's canal losses.

    Returns:
        the list of ``ParcelLedger`` rows written (or, for ``dry_run``, the
        unsaved instances that would have been written).
    """
    pod = point_of_diversion
    if months is not None:
        months = list(months)  # read twice below; a generator would be spent
    records, served, to_write, unallocated, losses = _plan_allocation(
        pod, reporting_period, months, efficiency, notes
    )
    seepage_zones = _seepage_zones(pod, to_write, losses, notes)
    if dry_run:
        return to_write
    return _store_allocation(
        pod, months, records, served, to_write, unallocated, losses, seepage_zones
    )


def _consumed_by_month(pod: PointOfDiversion) -> dict[date, dict[str, Any]]:
    """Per calendar month with a direct-use record: taken, returned, kept and whether any record is an estimate."""
    zero = Decimal("0")
    records = list(
        DiversionRecord.objects.filter(
            point_of_diversion=pod, diversion_type="direct_use"
        ).order_by("month")
    )
    by_month: dict[date, dict[str, Any]] = {}
    for record in records:
        entry = by_month.setdefault(
            _month_start(record.month),
            {
                "consumed": zero,
                "taken": zero,
                "returned": zero,
                "estimated": False,
            },
        )
        entry["consumed"] += record.consumed_acre_feet()
        entry["taken"] += abs(record.volume_acre_feet)
        entry["returned"] += record.returned_af
        if record.method == "estimated_from_use":
            entry["estimated"] = True
    return by_month


def _divided_by_month(pod: PointOfDiversion) -> dict[date, Decimal]:
    """The magnitude of this point's split ledger rows, summed per calendar month."""
    divided: dict[date, Decimal] = {}
    for amount, day in ParcelLedger.objects.filter(
        divided_from_headgate=True,
        divided_from_point_pk=pod.pk,
        source_type="surface_diversion",
    ).values_list("amount_acre_feet", "effective_date"):
        key = _month_start(day)
        divided[key] = divided.get(key, Decimal("0")) + abs(amount)
    return divided


def _unallocated_by_month(pod: PointOfDiversion) -> dict[date, Decimal]:
    """This point's unallocated delivery, summed per calendar month."""
    beyond: dict[date, Decimal] = {}
    for amount, day in UnallocatedDelivery.objects.filter(
        point_of_diversion=pod
    ).values_list("amount_acre_feet", "month"):
        key = _month_start(day)
        beyond[key] = beyond.get(key, Decimal("0")) + amount
    return beyond


def _period_of(month: date, periods: list[ReportingPeriod]) -> ReportingPeriod | None:
    """The first of ``periods`` that spans ``month``, or None."""
    month_end = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    for period in periods:
        if period.start_date < month_end and period.end_date >= month:
            return period
    return None


def _destination_of(pod: PointOfDiversion) -> str:
    """Where a point that serves no field delivers: its recharge site(s), else "no field"."""
    from core.modules import is_enabled

    if is_enabled("recharge"):
        names = sorted(
            {link.recharge_site.name for link in pod.basin_links.select_related("recharge_site")}
        )
        if names:
            return ", ".join(names)
    return "no field"


def _canal_month_row(
    month: date,
    info: dict[str, Any],
    loss: CanalMonthLoss | None,
    divided: dict[date, Decimal],
    beyond: dict[date, Decimal],
    destination: str = "no field",
) -> dict[str, Any]:
    """One month's row for the canal page, from its stored loss row or, lacking one, its records."""
    tolerance = Decimal("0.0001")
    zero = Decimal("0")
    if loss is None:
        row = {
            "month": month,
            "taken": info["taken"],
            "returned": info["returned"],
            "headgate": info["consumed"],
            "evaporation": None,
            "seepage": None,
            "spill": None,
            "losses": None,
            "own": None,
            "divided": None,
            "beyond": None,
            "unserved": None,
            "unserved_to": destination,
            "calculated": False,
            "adds_up": True,
        }
    else:
        losses = loss.evaporation_af + loss.seepage_af + loss.spill_af
        row = {
            "month": month,
            "taken": info["taken"],
            "returned": info["returned"],
            "headgate": loss.diverted_af,
            "evaporation": loss.evaporation_af,
            "seepage": loss.seepage_af,
            "spill": loss.spill_af,
            "losses": losses,
            "own": loss.own_af,
            "divided": divided.get(month, zero),
            "beyond": beyond.get(month, zero),
            "unserved": loss.unserved_af,
            "unserved_to": destination,
            "calculated": True,
        }
        parts = (
            losses + row["own"] + row["divided"] + row["beyond"] + row["unserved"]
        )
        row["adds_up"] = abs(row["headgate"] - parts) <= tolerance
    row["estimated"] = info["estimated"]
    return row


def _add_group_totals(ordered: list[dict[str, Any]]) -> None:
    """Give each period group its ``totals`` (None figures count as nothing)."""
    zero = Decimal("0")
    figure_keys = (
        "taken", "returned", "headgate", "evaporation", "seepage", "spill",
        "losses", "own", "divided", "beyond", "unserved",
    )
    for group in ordered:
        rows = group["rows"]
        totals = {key: sum((r[key] or zero for r in rows), zero) for key in figure_keys}
        totals["count"] = len(rows)
        totals["uncalculated"] = sum(1 for r in rows if not r["calculated"])
        totals["estimated"] = any(r["estimated"] for r in rows)
        totals["unserved_to"] = rows[0]["unserved_to"] if rows else "no field"
        totals["adds_up"] = all(r["adds_up"] for r in rows)
        group["totals"] = totals


def canal_water_by_month(pod: PointOfDiversion) -> list[dict[str, Any]]:
    """Where one canal's water went, month by month. Read-only.

    Returns one dict per reporting period that has a direct-use diversion
    record on ``pod``, newest first (months that fall in no period close into
    a last group with ``period`` of ``None``)::

        {"period": ReportingPeriod | None, "name": str, "is_open": bool,
         "rows": [row, ...], "totals": totals}

    Each ``row`` is one calendar month with a direct-use record (oldest first,
    so the year reads in order; a month with no record is no row and a
    to-storage record never makes one)::

        {"month": date, "headgate": Decimal, "evaporation", "seepage", "spill",
         "losses" (their sum), "own", "divided", "beyond", "unserved":
         Decimal | None, "taken" and "returned" (the records' volume and what
         was returned; "headgate" is the volume less the return), "unserved_to"
         (where a point that serves no field delivers), "estimated": bool, "calculated": bool, "adds_up": bool}

    Every figure is read from a stored row: the headgate figure and the three
    losses from ``CanalMonthLoss``; ``divided`` is the magnitude of this
    point's split rows on the ledger (stored negative); ``beyond`` is
    ``UnallocatedDelivery``. Nothing is recomputed. ``adds_up`` says whether
    headgate = losses + own + divided + beyond + unserved to 0.0001; a month where it
    does not stays on the page so a reader sees it. A month with records but no
    ``CanalMonthLoss`` row (it predates the canal-loss calculation) shows the
    records' consumed total as ``headgate``, ``calculated`` False, the other
    figures ``None`` and ``adds_up`` True (nothing was claimed).

    ``totals`` carries the same keys summed over the period's rows (``None``
    figures count as nothing), plus ``count``, ``uncalculated`` (months not yet
    calculated) and ``adds_up`` over the calculated months only.
    """
    by_month = _consumed_by_month(pod)
    if not by_month:
        return []

    stored = {
        loss.month: loss for loss in CanalMonthLoss.objects.filter(point_of_diversion=pod)
    }
    divided = _divided_by_month(pod)
    beyond = _unallocated_by_month(pod)

    periods = list(ReportingPeriod.objects.order_by("-start_date"))
    destination = _destination_of(pod)

    groups: dict[int | None, dict[str, Any]] = {}
    for month in sorted(by_month):
        row = _canal_month_row(
            month, by_month[month], stored.get(month), divided, beyond, destination
        )
        period = _period_of(month, periods)
        group = groups.setdefault(
            period.pk if period else None,
            {
                "period": period,
                "name": period.name if period else "No water year assigned",
                "is_open": bool(period and not period.is_finalized),
                "rows": [],
            },
        )
        group["rows"].append(row)

    ordered = [groups[p.pk] for p in periods if p.pk in groups]
    if None in groups:
        ordered.append(groups[None])

    _add_group_totals(ordered)
    if ordered and not any(g["is_open"] for g in ordered):
        ordered[0]["is_open"] = True  # nothing open: the newest year still opens
    return ordered
