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
* Idempotent: this service OWNS the ``surface_diversion`` rows for its served
  parcels in the months it touches. It deletes those rows up front, then writes
  fresh ones, so a re-run is byte-identical — mirroring ``run_calculations`` /
  ``rollover_allocations`` delete-then-insert.
* ``dry_run=True`` returns the would-be rows (unsaved) and writes nothing.

Efficiency defaults to the agency-wide ``SiteConfig.default_irrigation_efficiency``
(55-02); a caller may override it per call. Shared-well / shared-POD apportionment
is Phase 56 — out of scope here.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounting.allocation_math import allocate_by_demand
from accounting.models import CalculationRun
from parcels.models import ParcelLedger
from surface.models import DiversionRecord, PointOfDiversionParcel

logger = logging.getLogger(__name__)

_Q = Decimal("0.0001")


def _resolve_efficiency(efficiency):
    """The explicit override if given, else the agency-wide SiteConfig default."""
    if efficiency is not None:
        return Decimal(str(efficiency))
    # Imported lazily so this module has no load-time dependency on core.
    from core.models import SiteConfig

    return SiteConfig.objects.get().default_irrigation_efficiency


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


def _records_for_period(point_of_diversion, reporting_period):
    """DiversionRecords on this POD that belong to the reporting period.

    The ``reporting_period`` FK on a record is nullable, so a record counts if
    EITHER its FK matches OR its ``month`` falls inside the period's date span —
    catching both seeded-with-FK and bare monthly records. ``reporting_period``
    of ``None`` returns every record for the POD.
    """
    qs = DiversionRecord.objects.filter(point_of_diversion=point_of_diversion)
    if reporting_period is not None:
        qs = qs.filter(
            Q(reporting_period=reporting_period)
            | Q(
                month__gte=reporting_period.start_date,
                month__lte=reporting_period.end_date,
            )
        )
    return qs.order_by("month").distinct()


def _demand_rows(record, shares, pod):
    """Unsaved demand-weighted ledger rows (NEGATIVE) for one diversion record."""
    today = timezone.now().date()
    return [
        ParcelLedger(
            parcel=parcel,
            transaction_date=today,
            effective_date=record.month,
            amount_acre_feet=-share,  # NEGATIVE: delivered magnitude (production convention)
            source_type="surface_diversion",
            description=(
                f"Diversion from {pod.name}: {record.volume_acre_feet} AF "
                f"({record.get_diversion_type_display()}) — demand-weighted "
                f"(ET-allocated)"
            ),
            reporting_period=record.reporting_period,
            water_type=None,
        )
        for parcel, share in shares.items()
    ]


def _fraction_rows(record, served_links, pod):
    """Unsaved static-fraction fallback rows (NEGATIVE) — the no-ET-demand path.

    Mirrors ``accounting.services.create_diversion_ledger_entries`` exactly (split
    by each link's ``fraction``, rounding residual on the LAST row) but builds
    unsaved instances rather than writing, so ``dry_run`` can preview it and the
    single delete-then-bulk_create path stays idempotent.
    """
    total = abs(record.volume_acre_feet)
    today = timezone.now().date()
    rows = []
    distributed = Decimal("0")
    last = len(served_links) - 1
    for i, link in enumerate(served_links):
        if i == last:
            amount = total - distributed
        else:
            amount = (total * link.fraction).quantize(_Q)
            distributed += amount
        rows.append(
            ParcelLedger(
                parcel=link.parcel,
                transaction_date=today,
                effective_date=record.month,
                amount_acre_feet=-amount,
                source_type="surface_diversion",
                description=(
                    f"Diversion from {pod.name}: {record.volume_acre_feet} AF "
                    f"({record.get_diversion_type_display()}) — static fraction "
                    f"fallback (no ET demand), fraction={link.fraction}"
                ),
                reporting_period=record.reporting_period,
                water_type=None,
            )
        )
    return rows


def allocate_district_delivery(
    point_of_diversion, reporting_period, *, efficiency=None, dry_run=False
):
    """Allocate a POD's recorded diversions across served parcels by ET demand.

    For each ``DiversionRecord`` on ``point_of_diversion`` in ``reporting_period``,
    split the recorded delivery across the parcels the POD serves, weighted by each
    parcel's measured net consumptive use for the record's month and capped at
    ``demand / efficiency`` (the Plan-01 kernel). Where no served parcel has ET
    demand that month, fall back to the static ``PointOfDiversionParcel.fraction``
    split. Writes negative ``surface_diversion`` ``ParcelLedger`` rows.

    Args:
        point_of_diversion: a ``surface.models.PointOfDiversion``.
        reporting_period: the ``accounting.models.ReportingPeriod`` to allocate
            (``None`` = every recorded diversion on the POD).
        efficiency: optional irrigation-efficiency override in ``(0, 1]``; default
            is the agency-wide ``SiteConfig.default_irrigation_efficiency``.
        dry_run: when ``True``, return the would-be rows (unsaved) and write nothing.

    Returns:
        the list of ``ParcelLedger`` rows written (or, for ``dry_run``, the
        unsaved instances that would have been written).
    """
    eff = _resolve_efficiency(efficiency)
    pod = point_of_diversion

    served_links = list(
        PointOfDiversionParcel.objects.filter(point_of_diversion=pod)
        .select_related("parcel")
        .order_by("id")
    )
    served = [link.parcel for link in served_links]

    records = list(_records_for_period(pod, reporting_period))

    to_write = []
    for record in records:
        delivery_total = abs(record.volume_acre_feet)
        demand_by_parcel = {p: _month_demand(p, record.month) for p in served}
        shares = allocate_by_demand(delivery_total, demand_by_parcel, eff)

        if shares:
            to_write.extend(_demand_rows(record, shares, pod))
            path = "demand-weighted"
        else:
            to_write.extend(_fraction_rows(record, served_links, pod))
            path = "static-fraction fallback (no ET demand)"
        logger.info(
            "allocate_district_delivery POD=%s month=%s: %s (%d parcels, %s AF)",
            pod.name,
            record.month,
            path,
            len(served),
            delivery_total,
        )

    if dry_run:
        return to_write

    # Idempotency: this service owns the surface_diversion rows for its served
    # parcels in the months it just allocated. Delete them up front (ONCE for the
    # whole month set — not per record, so two records sharing a month don't
    # clobber each other), then write fresh, mirroring run_calculations.
    months = {record.month for record in records}
    with transaction.atomic():
        if served and months:
            ParcelLedger.objects.filter(
                parcel__in=served,
                effective_date__in=months,
                source_type="surface_diversion",
            ).delete()
        return list(ParcelLedger.objects.bulk_create(to_write))
