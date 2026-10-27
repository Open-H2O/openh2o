# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the calculation engine for a period over satellite-estimated consumptive use.

For each in-scope parcel that has gross-ET data for the period, evaluate the
active CalculationPlan and record its net consumptive use on a CalculationRun.
The `ET − precip − surface` residual then resolves by archetype:
a parcel WITH a well (no meter) gets exactly ONE ParcelLedger row with
source_type="calculated" (its groundwater extraction estimate); a no-well parcel
gets NO calculated row — its residual is recorded as `unmet_demand_af` on the run,
never a phantom groundwater extraction; a METERED parcel also gets NO calculated
row (its meter reading is the authoritative groundwater record — a calculated row
would double-count it) and its run is kept purely as the ET reference value, with
disposition "metered". Both the calculated row and the run are delete-then-insert per
(parcel, month) inside one transaction, so re-running is idempotent: running twice
yields identical balances (no drift, no double-count).

There is no rain bank. In a wet month the chain nets below the
floor; clamp_floor surfaces that surplus as `rain_surplus_af` on the run's
breakdown: information about rain the crop did not need, not a credit.
Nothing is deposited and nothing is drawn: `_resolve_leftover` writes no
WaterCredit and no WaterCreditDraw, for any origin. It still CLEARS whatever
an older run of the engine wrote for this parcel-period (its own
WaterCreditDraw rows and its own `precip_surplus`-origin WaterCredit), so a
re-run on a database an older engine wrote removes what it wrote for that
month rather than leaving it stale. `final_af` passes through unchanged.

The WaterCredit / WaterCreditDraw tables and their `precip_surplus` choice
stay on the model so an old database still loads. Nothing writes either
table any more; year-end carry-over (`rollover_allocations`) writes
`AllocationCarryover`, a different model.

An over-delivery is nobody's credit, under the DEFAULT
setting. The month's canal water a parcel could use beyond its net use —
clamp_floor's `incidental_recharge_af` — is always recorded on the run, as
`CalculationRun.over_delivery_af`.

What happens to it is a deployment
setting, `SiteConfig.over_delivery_treatment`, read ONCE per run:
`"not_credited"` (the default) and `"named_line"` are identical on the
engine side: no `recharge` ledger row and no basin-pool deposit (the amount is
shown elsewhere, never here). Nothing credits an over-delivery: a site stored as
the removed `"credited"` choice is run as `"not_credited"`. A run an older
version stamped as credited stays readable, and re-running its month clears the
`recharge` row and takes back the pool deposit that run wrote, as a signed
DELTA against what THIS field's prior run pooled (`prior_pooled`, below), which
folds in the one-time reversal of an older engine's deposit
(`prior_has_old_pool_deposit`) as one case of the same computation rather than
a second, separate step. Every run stamps `over_delivery_treatment`, so a later
change to the setting moves no figure until the month is re-run.
"""

from __future__ import annotations

import datetime as dt
import re
from contextlib import ExitStack
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q, QuerySet

from accounting.calculation import evaluate_chain, plan_config_hash
from accounting.carryover_math import water_year_of
from accounting.locks import override
from accounting.ledger_words import (
    INCIDENTAL_RECHARGE_WORDS,
    LEGACY_INCIDENTAL_RECHARGE_WORDS,
    LEGACY_CANAL_CREDIT_WORDS,
    NO_PUMPING_DERIVED_WORDS,
    PUMPING_ESTIMATE_WORDS,
)
from accounting.models import (
    CalculationPlan,
    CalculationRun,
    ReportingPeriod,
    WaterCredit,
    WaterCreditDraw,
    WaterType,
)
from accounting.recharge_policy import recharge_routes_to_personal
from accounting.services import (
    INCIDENTAL_RECHARGE_POOL,
    deposit_to_basin_pool,
    parcel_pool_zone as _parcel_pool_zone,
)
from core.models import SiteConfig
from parcels.models import Parcel, ParcelLedger
from parcels.services import field_efficiency

if TYPE_CHECKING:
    from geography.models import Zone

# The reason recorded on every change a forced recompute of a finalized period
# writes, so the change history says why a filed figure moved.
FORCE_REASON = "--force on a finalized period"

PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


def _incidental_recharge_af(breakdown):
    """Read the deep-percolation recharge magnitude off the clamp_floor step.

    Returns the positive incidental_recharge_af signalled by clamp_floor,
    or Decimal('0') when the step is absent or an older run lacks the surplus split.
    """
    clamp = next(
        (s for s in breakdown if s["step_type"] == "clamp_floor"), None
    )
    if clamp is None:
        return Decimal("0")
    return Decimal(str(clamp["detail"].get("incidental_recharge_af", "0")))


def _groundwater_extraction(final_af, efficiency):
    """Split a `groundwater`-disposition run's CONSUMED
    magnitude (``final_af``, the calculated row's amount, ETAW met by
    groundwater) into what the pump had to extract and what never reached
    the crop.

    ``gw_extracted_af = final_af / efficiency``;
    ``deep_percolation_gw_af = gw_extracted_af - final_af``. Both quantized to
    4dp, the ledger's own convention. ``efficiency`` is the field's own
    irrigation efficiency (``parcels.services.field_efficiency``:
    its irrigation method's, else the Delivery Settings default), the same
    figure its canal water is multiplied by, read by the caller at compute
    time and stamped on the run -- never re-read later, so a setting change
    after the run does not move a figure already stamped on it (the
    finalized-period lock protects runs, not settings). A zero-residual month
    (``final_af == 0``) divides to ``(0, 0)`` with no special-casing needed.

    Returns ``(gw_extracted_af, deep_percolation_gw_af)``, both ``Decimal``.
    """
    quant = Decimal("0.0001")
    extracted = (final_af / efficiency).quantize(quant)
    deep_percolation = (extracted - final_af).quantize(quant)
    return extracted, deep_percolation


def _over_delivery_note(over, treatment):
    """The fragment for a --dry-run / live line about this parcel-month's over-delivery, or ``None``."""
    if treatment == "named_line" and over > 0:
        return "shown as its own line"
    return None


def _resolve_leftover(parcel, period, final_af, breakdown, *, commit):
    """Clear this period's legacy rain-bank state; `final_af` is not touched.

    There is no rain bank. This writes NO WaterCredit and NO
    WaterCreditDraw, for any origin: `bank` was the only lever that ever made
    this function deposit or draw, and it is gone. What is left is cleanup:
    when committing, delete whatever an older run of the engine wrote for
    THIS parcel-period (its own WaterCreditDraw rows, and its own
    `precip_surplus`-origin WaterCredit), so a re-run on a database an older
    engine wrote removes what it wrote for that month instead of leaving it
    stale beside a run that no longer explains it. `breakdown` is accepted for
    call-site symmetry with the rest of the per-parcel pipeline; nothing in it
    is read here any more (the rain figure lives in the clamp_floor detail as
    `rain_surplus_af`, read directly by whatever wants to show it).

    Returns `(final_af, {"deposited": Decimal("0"), "drawn": Decimal("0")})`;
    the zero shape is kept so CalculationRun.banked_af / drawn_af, which stay
    on the model for old runs, keep writing 0 for every new one exactly the
    same way as any other absent term.

    MUST be called inside the per-parcel transaction.atomic() block when
    committing.
    """
    if commit:
        WaterCreditDraw.objects.filter(
            credit__parcel=parcel, draw_period=period
        ).delete()
        WaterCredit.objects.filter(
            parcel=parcel, origin_period=period, origin="precip_surplus"
        ).delete()
    return final_af, {"deposited": Decimal("0"), "drawn": Decimal("0")}


def _effective_precip_stamp(breakdown: list[dict[str, Any]]) -> Decimal | None:
    """Effective precip AF off the breakdown at 4dp, or None when the step did not run."""
    quant = Decimal("0.0001")
    precip_step = next(
        (s for s in breakdown if s["step_type"] == "subtract_effective_precip"), None
    )

    effective_precip_af = None
    if precip_step is not None:
        effective_precip_af = Decimal(
            str(precip_step["detail"]["effective_precip_af"])
        ).quantize(quant)
    return effective_precip_af


def _surface_water_stamps(
    breakdown: list[dict[str, Any]],
) -> tuple[Decimal | None, Decimal | None, Decimal | None]:
    """Surface water consumed, delivered and efficiency off the breakdown (None when absent)."""
    quant = Decimal("0.0001")
    surface_step = next(
        (s for s in breakdown if s["step_type"] == "subtract_surface_water"), None
    )

    # surface_water_af keeps its name and holds the CONSUMED part
    # (delivered x efficiency, when the apply_efficiency knob is on; the
    # delivered magnitude itself when it is off). surface_delivered_af and
    # surface_efficiency are only present in the step detail when the knob is
    # on ("delivered_af" / "efficiency" keys). An old breakdown, or the knob
    # off, stores null for both, exactly as it always has for the one column.
    surface_water_af = None
    surface_delivered_af = None
    surface_efficiency = None
    if surface_step is not None:
        detail = surface_step["detail"]
        surface_water_af = Decimal(str(detail["surface_water_af"])).quantize(quant)
        if "delivered_af" in detail:
            surface_delivered_af = Decimal(
                str(detail["delivered_af"])
            ).quantize(quant)
        if detail.get("efficiency") is not None:
            surface_efficiency = Decimal(str(detail["efficiency"])).quantize(
                Decimal("0.001")
            )
    return surface_water_af, surface_delivered_af, surface_efficiency


def _groundwater_stamps(
    residual_disposition: str,
    final_af: Decimal,
    groundwater_application_efficiency: Decimal,
    groundwater_efficiency_source: str,
) -> tuple[Decimal | None, Decimal | None, Decimal | None, str]:
    """The extraction split and efficiency stamp: ``(extracted, deep_percolation, efficiency, source)``."""
    # Only a `groundwater`-disposition run (has a well, no
    # meter) ever gets an extraction estimate -- a metered run's meter IS the
    # number, and a no-well run has no pump to have extracted anything.
    gw_extracted_af = None
    deep_percolation_gw_af = None
    efficiency_stamp = None
    source_stamp = ""
    if residual_disposition == "groundwater":
        gw_extracted_af, deep_percolation_gw_af = _groundwater_extraction(
            final_af, groundwater_application_efficiency
        )
        efficiency_stamp = groundwater_application_efficiency
        source_stamp = groundwater_efficiency_source
    return gw_extracted_af, deep_percolation_gw_af, efficiency_stamp, source_stamp


def _persist_calculation_run(
    parcel, period, gross_af, net_af, breakdown, info, plan_id, plan_name, plan_hash,
    *, residual_disposition, unmet_demand_af, groundwater_application_efficiency,
    groundwater_efficiency_source,
    over_delivery_treatment, over_delivery_leave_behind, over_delivery_credited_af,
    over_delivery_credit_pooled,
):
    """Write the one CalculationRun for this (parcel, period) — the audit trail.

    Delete-then-insert so a re-run leaves exactly one run with identical values
    (mirrors the calculated ledger row's idempotency). All AF figures are quantized
    to 4dp the same way the ledger row is, so ``final_af`` equals
    ``-ledger.amount_acre_feet`` exactly. Input magnitudes come straight off the
    breakdown the runner already evaluated; a step that did not run in this chain
    (e.g. effective precip disabled) stores NULL rather than a fabricated zero.

    ``gw_extracted_af`` / ``deep_percolation_gw_af`` are set
    only when ``residual_disposition == "groundwater"`` (a has-well, unmetered
    parcel) — ``_groundwater_extraction`` splits the CONSUMED magnitude
    (``final_af``, quantized) by ``groundwater_application_efficiency``, the
    field's own irrigation efficiency the CALLER resolved for this parcel,
    which is stamped beside them with its source ("method" or
    "agency"). All are null (the source blank) on a metered or no-well run,
    exactly as the model fields' help text says.

    The four ``over_delivery_*`` stamps are the CALLER's decision
    (read once per run, before this function runs) —
    passed straight through, never re-derived here, so this function stays a
    pure "write what I was told" persister for every field it owns.

    MUST be called inside the per-parcel transaction.atomic() block.
    """
    quant = Decimal("0.0001")
    effective_precip_af = _effective_precip_stamp(breakdown)
    surface_water_af, surface_delivered_af, surface_efficiency = (
        _surface_water_stamps(breakdown)
    )

    # Net consumptive use is the source-agnostic spine: gross ET minus effective
    # precip ONLY (never surface). It is recorded for every ET-bearing parcel
    # regardless of supply source or whether a well exists, so it is never NULL —
    # a chain with no precip step treats effective precip as 0. Computed from the
    # quantized gross + precip the run also stores, so net CU == gross − precip
    # holds exactly at 4dp.
    gross_q = gross_af.quantize(quant)
    net_consumptive_use_af = (
        gross_q - (effective_precip_af or Decimal("0"))
    ).quantize(quant)

    # The over-delivery amount lands on the run, read off
    # clamp_floor's over_delivery_af (same value as the legacy
    # incidental_recharge_af key; see steps.py::clamp_floor). No ledger row is
    # written for it any more — see the caller.
    over_delivery_af = _incidental_recharge_af(breakdown).quantize(quant)

    final_af = net_af.quantize(quant)
    gw_extracted_af, deep_percolation_gw_af, efficiency_stamp, source_stamp = (
        _groundwater_stamps(
            residual_disposition, final_af, groundwater_application_efficiency,
            groundwater_efficiency_source,
        )
    )

    CalculationRun.objects.filter(parcel=parcel, period=period).delete()
    CalculationRun.objects.create(
        parcel=parcel,
        period=period,
        gross_et_af=gross_q,
        effective_precip_af=effective_precip_af,
        surface_water_af=surface_water_af,
        surface_delivered_af=surface_delivered_af,
        surface_efficiency=surface_efficiency,
        over_delivery_af=over_delivery_af,
        over_delivery_treatment=over_delivery_treatment,
        over_delivery_leave_behind=over_delivery_leave_behind,
        over_delivery_credited_af=over_delivery_credited_af,
        over_delivery_credit_pooled=over_delivery_credit_pooled,
        net_consumptive_use_af=net_consumptive_use_af,
        residual_disposition=residual_disposition,
        unmet_demand_af=unmet_demand_af,
        gw_extracted_af=gw_extracted_af,
        deep_percolation_gw_af=deep_percolation_gw_af,
        groundwater_application_efficiency=efficiency_stamp,
        groundwater_efficiency_source=source_stamp,
        banked_af=info["deposited"],
        drawn_af=info["drawn"],
        final_af=final_af,
        breakdown=breakdown,
        methodology_plan_id=plan_id,
        methodology_plan_name=plan_name,
        config_hash=plan_hash,
    )


def _parcels_in_scope(parcel_number: str | None) -> QuerySet[Parcel]:
    """The parcels this run covers: all of them, or the one named by --parcel."""
    parcels = (
        Parcel.objects.select_related("irrigation__method")
        .all()
        .order_by("parcel_number")
    )
    if parcel_number:
        parcels = parcels.filter(parcel_number=parcel_number)
        if not parcels.exists():
            raise CommandError(
                f"no parcel with parcel_number={parcel_number!r}"
            )
    return parcels


#: What a field's ledger row for its share of a well's meter reading starts
#: with. The month's calculation writes these rows and replaces them every
#: time it runs; a meter row a person typed on the field never starts this way.
WELL_METER_SHARE_WORDS = "From the well's meter:"

_GALLONS_PER_ACRE_FOOT = Decimal("325851")
_CUBIC_FEET_PER_ACRE_FOOT = Decimal("43560")


def _reading_acre_feet(reading) -> Decimal | None:
    """One meter reading as acre-feet pumped, or ``None`` when it states no volume.

    The reading's own stored volume (``calculated_volume``) wins. Without one,
    the volume is the reading less its previous value; with no previous value
    on the reading, a totalizer is read against the last reading before it on
    the same meter, and any other meter type states the month's volume as the
    reading itself. The volume is in the meter's unit and is converted to
    acre-feet. A rate (cubic feet per second) states no volume and gives
    ``None``, as does a totalizer with nothing before it to subtract.
    """
    from measurements.models import MeterReading

    meter = reading.meter
    if reading.calculated_volume is not None:
        volume = reading.calculated_volume
    elif reading.previous_value is not None:
        volume = reading.current_value - reading.previous_value
    elif meter.meter_type == "totalizer":
        earlier = (
            MeterReading.objects.filter(
                meter=meter, reading_date__lt=reading.reading_date
            )
            .order_by("-reading_date")
            .first()
        )
        if earlier is None:
            return None
        volume = reading.current_value - earlier.current_value
    else:
        volume = reading.current_value
    if volume < 0:
        return None
    if meter.unit == "acre_feet":
        return volume
    if meter.unit == "gallons":
        return volume / _GALLONS_PER_ACRE_FOOT
    if meter.unit == "cubic_feet":
        return volume / _CUBIC_FEET_PER_ACRE_FOOT
    return None


def _well_meter_shares(year: int, month: int, parcel_ids: set[int]) -> dict[int, tuple[Decimal, str]]:
    """``{parcel id: (acre-feet, description)}`` for the fields a well's meter covers this month.

    A well's readings dated in the month are added up and divided among the
    fields the well waters by each field's share of the well (the shares
    scaled to add to one, so shares left at their default divide it evenly).
    A well whose fields include one that carries its own meter row for the
    month is left out: that row already holds the meter's water.
    """
    from django.utils import timezone

    from core.modules import is_enabled

    if not is_enabled("wells"):
        return {}
    from measurements.models import MeterReading
    from wells.models import WellIrrigatedParcel, WellMeter

    start = timezone.make_aware(dt.datetime(year, month, 1))
    end = timezone.make_aware(
        dt.datetime(year + (month == 12), month % 12 + 1, 1)
    )
    readings = MeterReading.objects.filter(
        reading_date__gte=start, reading_date__lt=end
    ).select_related("meter")
    by_meter: dict[int, Decimal] = {}
    for reading in readings:
        volume = _reading_acre_feet(reading)
        if volume is not None:
            by_meter[reading.meter_id] = by_meter.get(reading.meter_id, Decimal("0")) + volume

    typed_rows = set(
        ParcelLedger.objects.filter(
            source_type="meter_reading",
            effective_date__year=year,
            effective_date__month=month,
        )
        .exclude(description__startswith=WELL_METER_SHARE_WORDS)
        .values_list("parcel_id", flat=True)
    )
    quant = Decimal("0.0001")
    out: dict[int, tuple[Decimal, str]] = {}
    well_volumes: dict[int, Decimal] = {}
    wells: dict[int, Any] = {}
    for link in WellMeter.objects.filter(meter_id__in=by_meter).select_related("well"):
        wells[link.well_id] = link.well
        well_volumes[link.well_id] = (
            well_volumes.get(link.well_id, Decimal("0")) + by_meter[link.meter_id]
        )
    for well_id, volume in well_volumes.items():
        links = list(
            WellIrrigatedParcel.objects.filter(well_id=well_id).order_by("parcel_id")
        )
        if not links or any(k.parcel_id in typed_rows for k in links):
            continue
        total_share = sum((k.fraction for k in links), Decimal("0"))
        if total_share <= 0:
            continue
        volume = volume.quantize(quant)
        assigned = Decimal("0")
        for i, link in enumerate(links):
            if i == len(links) - 1:
                amount = volume - assigned
            else:
                amount = (volume * link.fraction / total_share).quantize(quant)
            assigned += amount
            if link.parcel_id in parcel_ids:
                pct = format(link.fraction / total_share, ".0%")
                out[link.parcel_id] = (
                    amount,
                    f"{WELL_METER_SHARE_WORDS} {wells[well_id].name} pumped {volume} AF "
                    f"this month, this field's share is {pct}",
                )
    return out


def _write_well_meter_shares(
    year: int,
    month: int,
    eff_date: dt.date,
    shares: dict[int, tuple[Decimal, str]],
    parcel_ids: set[int],
    reporting_period: ReportingPeriod | None,
) -> None:
    """Replace the month's well-meter rows on the fields in scope with ``shares``."""
    gw_type, _ = WaterType.objects.get_or_create(
        code="GW", defaults={"name": "Groundwater"}
    )
    with transaction.atomic():
        ParcelLedger.objects.filter(
            source_type="meter_reading",
            description__startswith=WELL_METER_SHARE_WORDS,
            effective_date__year=year,
            effective_date__month=month,
            parcel_id__in=parcel_ids,
        ).delete()
        for parcel_id, (amount, description) in shares.items():
            ParcelLedger.objects.create(
                parcel_id=parcel_id,
                transaction_date=dt.date.today(),
                effective_date=eff_date,
                amount_acre_feet=-amount,
                source_type="meter_reading",
                description=description,
                reporting_period=reporting_period,
                water_type=gw_type,
            )


def _metered_parcel_ids(year: int, month: int) -> set[int]:
    """Ids of the parcels that carry an authoritative meter reading for the month."""
    # The engine runs on EVERY parcel, including metered ones. A
    # parcel that carries an authoritative meter_reading row for this period is
    # not skipped. Instead it gets an ET-bearing
    # reference CalculationRun (what the crop actually consumed, the district
    # reference value for the dashboard + reports) but NO calculated groundwater
    # row — the meter reading already measured that groundwater, so a calculated
    # row would double-count it (expressed as a disposition, not an
    # exclusion). `metered_row_ids` is still the
    # authoritative-reading detector; we carry it INTO the loop as a per-parcel
    # `is_metered` flag rather than dropping those parcels up front.
    return set(
        ParcelLedger.objects.filter(
            source_type="meter_reading",
            effective_date__year=year,
            effective_date__month=month,
        ).values_list("parcel_id", flat=True)
    )


def _prior_run_state(
    parcel: Parcel, period: str
) -> tuple[CalculationRun | None, Decimal, bool]:
    """The parcel-month's earlier run, its incidental recharge, and whether it predates the over-delivery stamp."""
    prior_run = CalculationRun.objects.filter(
        parcel=parcel, period=period
    ).first()
    prior_clamp = (
        next(
            (s for s in prior_run.breakdown if s["step_type"] == "clamp_floor"),
            None,
        )
        if prior_run
        else None
    )
    prior_incidental = (
        Decimal(str(prior_clamp["detail"].get("incidental_recharge_af", "0")))
        if prior_clamp
        else Decimal("0")
    )
    # A run written by this engine always carries
    # over_delivery_af in its clamp_floor detail (see steps.py). Its
    # absence, alongside a positive incidental_recharge_af, means the
    # prior run predates this change and deposited that amount to the
    # basin pool — reverse it exactly once. A second re-run sees a
    # prior breakdown that already carries over_delivery_af (this
    # engine's own last write) and reverses nothing, so a re-run never
    # double-reverses.
    prior_has_old_pool_deposit = (
        prior_clamp is not None
        and "over_delivery_af" not in prior_clamp["detail"]
        and prior_incidental > 0
    )
    return prior_run, prior_incidental, prior_has_old_pool_deposit


def _dry_run_extra(
    breakdown: list[dict[str, Any]],
    net_af: Decimal,
    incidental_af: Decimal,
    credit_note: str | None,
    *,
    is_metered: bool,
    routes_personal: bool,
    gw_efficiency: Decimal,
) -> str:
    """The trailing "; ..." fragments of a --dry-run parcel line."""
    extra = ""
    if incidental_af > 0:
        extra += (
            f"; {incidental_af.quantize(Decimal('0.0001'))} AF canal "
            f"water beyond the month's use, would be recorded on the run"
        )
    if credit_note:
        extra += f"; {credit_note}"
    # A canal-served field's line also names what was
    # delivered, the field's own efficiency (and where it came
    # from), and what that leaves the crop to use. "delivered_af"
    # is only in the detail when apply_efficiency is on; delivered
    # 0 never reaches this line because subtract_surface_water
    # itself skips the efficiency lookup at 0.
    surface_step = next(
        (s for s in breakdown if s["step_type"] == "subtract_surface_water"),
        None,
    )
    if surface_step is not None and "delivered_af" in surface_step["detail"]:
        sd = surface_step["detail"]
        delivered = Decimal(str(sd["delivered_af"]))
        if delivered > 0:
            surface_eff = Decimal(str(sd["efficiency"]))
            consumed = Decimal(str(sd["consumed_af"]))
            extra += (
                f"; canal delivered {delivered} AF x {surface_eff} "
                f"({sd['efficiency_source']}) = {consumed} AF the "
                f"crop could use"
            )
    # An estimated field (has a well, no
    # meter) also names the extraction split the run would stamp
    # -- what the pump had to lift beyond what the crop consumed.
    # Metered and no-well parcels never divide (a meter is the
    # number; there is no pump to have extracted anything).
    if not is_metered and routes_personal:
        consumed_af = net_af.quantize(Decimal("0.0001"))
        extracted_af, deep_percolation_af = _groundwater_extraction(
            consumed_af, gw_efficiency
        )
        extra += (
            f"; groundwater consumed {consumed_af} AF / "
            f"{gw_efficiency} = {extracted_af} AF "
            f"extracted, {deep_percolation_af} AF deep percolation"
        )
    return extra


def _dry_run_line(
    parcel: Parcel,
    gross_af: Decimal,
    net_af: Decimal,
    extra: str,
    *,
    is_metered: bool,
    routes_personal: bool,
) -> tuple[str, str]:
    """The --dry-run output line for one parcel, with its summary bucket."""
    if is_metered:
        return "metered", (
            f"  {parcel.parcel_number}: gross {gross_af} AF -> "
            f"net {net_af} AF (metered — ET reference run, meter "
            f"authoritative, no GW row){extra}"
        )
    if routes_personal:
        return "written", (
            f"  {parcel.parcel_number}: gross {gross_af} AF -> "
            f"net {net_af} AF (would write {-net_af} AF GW){extra}"
        )
    unmet_preview = max(Decimal("0"), net_af).quantize(
        Decimal("0.0001")
    )
    return "unmet", (
        f"  {parcel.parcel_number}: gross {gross_af} AF -> "
        f"net {net_af} AF (no well — would record {unmet_preview} AF "
        f"unmet demand, no GW row){extra}"
    )


def _live_line(
    parcel: Parcel,
    gross_af: Decimal,
    net_af: Decimal,
    unmet_demand_af: Decimal,
    extra: str,
    *,
    is_metered: bool,
    routes_personal: bool,
) -> tuple[str, str]:
    """The output line for one parcel written for real, with its summary bucket."""
    if is_metered:
        return "metered", (
            f"  {parcel.parcel_number}: gross {gross_af} AF -> "
            f"net {net_af} AF (metered — ET reference run, meter "
            f"authoritative, no GW row){extra}"
        )
    if routes_personal:
        return "written", (
            f"  {parcel.parcel_number}: gross {gross_af} AF -> "
            f"net {net_af} AF (wrote {-net_af} AF GW){extra}"
        )
    return "unmet", (
        f"  {parcel.parcel_number}: gross {gross_af} AF -> "
        f"net {net_af} AF (no well — recorded {unmet_demand_af} AF "
        f"unmet demand, no GW row){extra}"
    )


def _write_residual_row(
    parcel: Parcel,
    eff_date: dt.date,
    net_af: Decimal,
    reporting_period: ReportingPeriod | None,
    gw_water_type: WaterType,
    *,
    is_metered: bool,
    routes_personal: bool,
) -> tuple[str, Decimal]:
    """Resolve the residual by archetype; returns ``(disposition, unmet_demand_af)``."""
    # The residual (ET − precip − surface, surfaced as
    # net_af) resolves by archetype. Always delete the stale calculated
    # row first so an archetype flip (well → no-well, or → metered)
    # clears it, THEN decide:
    #   * metered  — the parcel carries an authoritative meter_reading;
    #     the meter OWNS its groundwater, so the engine writes NO
    #     calculated row (that would double-count the meter). The run is
    #     kept purely as the ET reference value (gross ET / net CU) for
    #     the dashboard + reports. This branch wins FIRST.
    #   * groundwater — has a well, no meter: the residual is its pumped
    #     groundwater estimate, written as the one `calculated` row.
    #   * unmet_demand — no well: the residual is under-irrigation or a
    #     bad surface number, recorded on the run, NEVER a phantom GW row.
    ParcelLedger.objects.filter(
        parcel=parcel,
        effective_date=eff_date,
        source_type="calculated",
    ).delete()
    if is_metered:
        residual_disposition = "metered"
        unmet_demand_af = Decimal("0")
        # No calculated row: the meter reading is the authoritative
        # groundwater record. The reference run is still persisted below.
    elif routes_personal:
        residual_disposition = "groundwater"
        unmet_demand_af = Decimal("0")
        # The zero stays a zero. Nothing else in this
        # branch changes; only which sentence describes it.
        amount = (-net_af).quantize(Decimal("0.0001"))
        description = (
            NO_PUMPING_DERIVED_WORDS
            if amount == 0
            else PUMPING_ESTIMATE_WORDS
        )
        ParcelLedger.objects.create(
            parcel=parcel,
            transaction_date=dt.date.today(),
            effective_date=eff_date,
            amount_acre_feet=amount,
            source_type="calculated",
            description=description,
            reporting_period=reporting_period,
            water_type=gw_water_type,
        )
    else:
        residual_disposition = "unmet_demand"
        unmet_demand_af = max(Decimal("0"), net_af).quantize(
            Decimal("0.0001")
        )
    return residual_disposition, unmet_demand_af


def _clear_over_delivery_credit(parcel: Parcel, eff_date: dt.date) -> None:
    """Clear the field's stale credit row left by an older version of the engine."""
    # Nothing credits an over-delivery now, but a month an older version
    # credited still holds its row (either wording, INCIDENTAL_RECHARGE_WORDS
    # or the earlier LEGACY_INCIDENTAL_RECHARGE_WORDS); re-running the month
    # removes it.
    ParcelLedger.objects.filter(
        Q(description__startswith=INCIDENTAL_RECHARGE_WORDS)
        | Q(description__startswith=LEGACY_INCIDENTAL_RECHARGE_WORDS)
        | Q(description__startswith=LEGACY_CANAL_CREDIT_WORDS),
        parcel=parcel,
        effective_date=eff_date,
        source_type="recharge",
    ).delete()


def _adjust_basin_pool(
    pool_zone: Zone | None,
    gw_water_type: WaterType,
    period: str,
    prior_run: CalculationRun | None,
    prior_incidental: Decimal,
    prior_has_old_pool_deposit: bool,
    *,
    routes_personal: bool,
) -> None:
    """Take back what the prior run pooled for this field; nothing is pooled now."""
    # Nothing is pooled any more, so the new pooled amount is always zero and
    # the delta is a take-back of whatever a past run left: what an older
    # version pooled for this field (`prior_run.over_delivery_credit_pooled`),
    # or, the first time only, the deposit an older engine made
    # (`prior_has_old_pool_deposit`). A re-run's "prior" is always this
    # engine's own last write once it has run once.
    prior_pooled = (
        prior_incidental
        if prior_has_old_pool_deposit and not routes_personal
        else (
            (prior_run.over_delivery_credited_af or Decimal("0"))
            if prior_run is not None
            and prior_run.over_delivery_credit_pooled
            else Decimal("0")
        )
    )
    new_pooled = Decimal("0")
    if pool_zone is not None:
        delta = new_pooled - prior_pooled
        if delta != 0:
            pool_row = deposit_to_basin_pool(
                pool_zone,
                gw_water_type,
                water_year_of(period),
                delta,
                origin=INCIDENTAL_RECHARGE_POOL,
            )
            # An a→b→a (or any) round trip must leave the table as
            # it found it — an exact-zero row left standing is a
            # phantom the pool's readers would have to explain.
            if pool_row.amount_af == Decimal("0"):
                pool_row.delete()


def _commit_parcel_month(
    parcel: Parcel,
    period: str,
    eff_date: dt.date,
    final_af: Decimal,
    breakdown: list[dict[str, Any]],
    gross_af: Decimal,
    months_matched: int,
    *,
    plan_id: int | None,
    plan_name: str,
    plan_hash: str,
    gw_efficiency: Decimal,
    gw_efficiency_source: str,
    over_delivery_treatment: str,
    reporting_period: ReportingPeriod | None,
    gw_water_type: WaterType,
    is_metered: bool,
    routes_personal: bool,
    pool_zone: Zone | None,
    prior_run: CalculationRun | None,
    prior_incidental: Decimal,
    prior_has_old_pool_deposit: bool,
) -> tuple[Decimal, Decimal]:
    """Write one parcel-month's rows in a single transaction; returns ``(net_af, unmet_demand_af)``."""
    with transaction.atomic():
        net_af, info = _resolve_leftover(
            parcel, period, final_af, breakdown, commit=True,
        )
        # Invariant, explicit at the write site: a `calculated`
        # row is only ever written for a parcel with real matched ET. The
        # gate above already guarantees months_matched>0; assert it here so
        # a future refactor of that gate can never silently resurrect a
        # filed 0-AF row. A can't-happen guard, not flow control.
        if months_matched <= 0:  # pragma: no cover - guaranteed by the gate
            raise CommandError(
                f"internal invariant violated: refusing to write a "
                f"`calculated` row for {parcel.parcel_number} {period} "
                f"with months_matched={months_matched}"
            )
        residual_disposition, unmet_demand_af = _write_residual_row(
            parcel, eff_date, net_af, reporting_period, gw_water_type,
            is_metered=is_metered, routes_personal=routes_personal,
        )
        # Persist the reconstructable audit record in the SAME
        # transaction, delete-then-insert per (parcel, period). For a well
        # parcel it stays 1:1 with the calculated row; for a no-well parcel
        # it is the ONLY record of the parcel-month (consumptive use + unmet
        # demand, no groundwater row). Input magnitudes are pulled off the
        # breakdown the command already has (no re-derivation); steps absent
        # from the chain store NULL.
        _persist_calculation_run(
            parcel, period, gross_af, net_af, breakdown, info,
            plan_id, plan_name, plan_hash,
            residual_disposition=residual_disposition,
            unmet_demand_af=unmet_demand_af,
            groundwater_application_efficiency=gw_efficiency,
            groundwater_efficiency_source=gw_efficiency_source,
            over_delivery_treatment=over_delivery_treatment,
            over_delivery_leave_behind=None,
            over_delivery_credited_af=None,
            over_delivery_credit_pooled=False,
        )
        _clear_over_delivery_credit(parcel, eff_date)
        _adjust_basin_pool(
            pool_zone, gw_water_type, period,
            prior_run, prior_incidental, prior_has_old_pool_deposit,
            routes_personal=routes_personal,
        )
    return net_af, unmet_demand_af


def _assess_et(
    parcel: Parcel, period: str, site_config: SiteConfig
) -> tuple[Decimal, list[dict[str, Any]], Decimal, str, Decimal, int, Decimal] | None:
    """Evaluate the chain for one parcel-month; ``None`` when it has no matched ET.

    Returns ``(final_af, breakdown, gw_efficiency, gw_efficiency_source,
    incidental_af, months_matched, gross_af)``.
    """
    final_af, breakdown = evaluate_chain(parcel, period)
    # One irrigation efficiency per
    # field: ETAW met by groundwater is divided by the field's own
    # irrigation efficiency, the same lookup its canal water uses.
    gw_efficiency, gw_efficiency_source = field_efficiency(
        parcel, config=site_config
    )
    incidental_af = _incidental_recharge_af(breakdown)

    et_step = next(
        (s for s in breakdown if s["step_type"] == "et_gross"), None
    )
    # Gate on months_matched (items actually date-matched for THIS
    # month), NOT rows (the span-row count). A cache row can span the period
    # yet carry no item dated in it (months_matched==0, rows>0); gating on
    # rows would file a fabricated 0-AF `calculated` row for a parcel with
    # no real ET — the silent-zero trap.
    months_matched = (
        et_step["detail"].get("months_matched", 0) if et_step else 0
    )
    has_et = bool(et_step and months_matched > 0)
    if not has_et:
        return None

    gross_af = Decimal(et_step["output_af"]) if et_step else Decimal("0")
    return (
        final_af, breakdown, gw_efficiency, gw_efficiency_source,
        incidental_af, months_matched, gross_af,
    )


def _over_delivery_routing(
    parcel: Parcel, period: str
) -> tuple[bool, Zone | None, CalculationRun | None, Decimal, bool]:
    """Where the parcel's over-delivery goes, and what its earlier run pooled.

    Returns ``(routes_personal, pool_zone, prior_run, prior_incidental,
    prior_has_old_pool_deposit)``.
    """
    # `over_delivery_treatment` decides what happens to this
    # month's over-delivery — routes_personal / pool_zone say WHERE
    # (has-well -> the field's own ledger; no well -> its zone's
    # shared pool). `pool_zone` is read REGARDLESS of the parcel's
    # CURRENT well status: a field that gained a well since a prior
    # (b) run must still be able to find the zone that holds its old
    # deposit, to take it back down to 0 (see prior_pooled, below).
    routes_personal = recharge_routes_to_personal(parcel)
    pool_zone = _parcel_pool_zone(parcel, dt.date(int(period[:4]), int(period[5:7]), 1))
    prior_run, prior_incidental, prior_has_old_pool_deposit = _prior_run_state(
        parcel, period
    )
    return routes_personal, pool_zone, prior_run, prior_incidental, prior_has_old_pool_deposit


def _live_extra(incidental_af: Decimal, credit_note: str | None) -> str:
    """The trailing "; ..." fragments of a written parcel line."""
    extra = ""
    if incidental_af > 0:
        extra += (
            f"; {incidental_af.quantize(Decimal('0.0001'))} AF canal "
            f"water beyond the month's use, recorded on the run"
        )
    if credit_note:
        extra += f"; {credit_note}"
    return extra


class Command(BaseCommand):
    help = (
        "Evaluate the active CalculationPlan and write one idempotent "
        "`calculated` ledger row per parcel-month."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--period",
            required=True,
            help="Month to calculate, as YYYY-MM (e.g. 2024-06).",
        )
        parser.add_argument(
            "--parcel",
            help="Limit to a single parcel by parcel_number.",
        )
        parser.add_argument(
            "--unmetered-only",
            action="store_true",
            help="DEPRECATED and ignored. The engine now runs on ALL parcels by "
            "default and resolves each residual by archetype (well → calculated "
            "groundwater row; no-well → unmet demand; metered → ET reference run, "
            "no groundwater row), so a metered reading is never overwritten or "
            "double-counted. Passing this flag only prints a deprecation warning.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print the per-parcel result without writing ledger rows.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Recompute even if the period's ReportingPeriod is finalized. "
            "Overwrites a filed number — use deliberately.",
        )

    def handle(self, *args, **options):
        # Held open for the whole run so a reason added part-way (--force on a
        # finalized period, below) reaches every change the run writes, whether
        # or not a caller already opened a history context (core/history.py).
        with ExitStack() as history:
            self._history = history
            return self._handle(*args, **options)

    def _handle(self, *args, **options):
        period = options["period"]
        if not PERIOD_RE.match(period):
            raise CommandError(f"--period must be YYYY-MM, got {period!r}")

        year, month = int(period[:4]), int(period[5:7])
        eff_date = dt.date(year, month, 1)
        dry_run = options["dry_run"]

        parcels = _parcels_in_scope(options.get("parcel"))
        self._warn_unmetered_only_deprecated(options)

        reporting_period = ReportingPeriod.objects.filter(
            start_date__lte=eff_date, end_date__gte=eff_date
        ).first()
        self._guard_finalized_period(
            reporting_period, period, dry_run=dry_run, force=options["force"]
        )

        # A well's meter reading, entered once on the well, becomes each
        # field's share before anything asks which fields are metered.
        scope_ids = set(parcels.values_list("id", flat=True))
        well_shares = _well_meter_shares(year, month, scope_ids)
        if not dry_run:
            _write_well_meter_shares(
                year, month, eff_date, well_shares, scope_ids, reporting_period
            )
        metered_row_ids = _metered_parcel_ids(year, month) | set(well_shares)

        # Snapshot the methodology ONCE: the active plan is identical for every
        # parcel in a single run, so hashing per-parcel would be wasted work and
        # could tear if the plan were edited mid-run. These copied values (not a
        # FK) are stamped onto each CalculationRun so the filed number names its
        # recipe even after the live plan changes .
        active_plan = CalculationPlan.active()
        plan_hash = plan_config_hash(active_plan) if active_plan else ""
        plan_id = active_plan.id if active_plan else None
        plan_name = active_plan.name if active_plan else ""

        # GW water type for incidental-recharge rows ; resolved once.
        gw_water_type, _ = WaterType.objects.get_or_create(
            code="GW", defaults={"name": "Groundwater"}
        )

        # The deployment's settings, read ONCE for the whole run and never
        # re-read per parcel, so a setting edit mid-run cannot tear.
        # `SiteConfig.objects.first() or SiteConfig()` is the established
        # idiom (`parcels/services.py::field_efficiency`): reads safely before
        # a row exists, falling back to the fields' own class defaults.
        # The over-delivery treatment and leave-behind share, and the default irrigation efficiency, handed to
        # field_efficiency for each field with no irrigation method on file.
        site_config = SiteConfig.objects.first() or SiteConfig()

        counts = {"written": 0, "unmet": 0, "metered": 0}
        skipped_no_et = 0
        over_delivered = 0
        for parcel in parcels:
            outcome, was_over_delivered = self._process_parcel(
                parcel, period, eff_date,
                dry_run=dry_run,
                is_metered=parcel.id in metered_row_ids,
                reporting_period=reporting_period,
                plan_id=plan_id, plan_name=plan_name, plan_hash=plan_hash,
                gw_water_type=gw_water_type,
                site_config=site_config,
            )
            if outcome is None:
                skipped_no_et += 1
                continue
            counts[outcome] += 1
            if was_over_delivered:
                over_delivered += 1

        self._write_summary(
            period, dry_run, counts, skipped_no_et, over_delivered
        )

    def _warn_unmetered_only_deprecated(self, options: dict[str, Any]) -> None:
        """Print the deprecation warning when the ignored --unmetered-only flag is passed."""
        # --unmetered-only is now a deprecated alias: the engine runs on ALL
        # parcels by default and resolves each by archetype (well → calculated GW
        # row; no-well → unmet demand; metered → ET reference run, no GW row). The
        # flag is redundant. Accept it, warn, and otherwise change nothing.
        if options.get("unmetered_only"):
            self.stderr.write(
                self.style.WARNING(
                    "--unmetered-only is deprecated; the engine now runs on all "
                    "parcels by default and resolves each residual by archetype "
                    "(well, no-well, or metered). The flag changes nothing."
                )
            )

    def _guard_finalized_period(
        self,
        reporting_period: ReportingPeriod | None,
        period: str,
        *,
        dry_run: bool,
        force: bool,
    ) -> None:
        """Refuse to recompute a finalized period unless forced; open the override when forced."""
        # Finalized-period write guard. A finalized ReportingPeriod
        # is a number already filed with the state; re-running would silently
        # overwrite it. Refuse unless --force, and shout when forced. Guard ONCE
        # before the loop: finalization is a property of the period, not the
        # parcel, so a per-parcel raise would half-write the period. dry_run is
        # always allowed (it writes nothing — previewing a finalized recompute is
        # safe). A month with no ReportingPeriod has nothing to finalize: proceed.
        if (
            reporting_period is not None
            and reporting_period.is_finalized
            and not dry_run
        ):
            if not force:
                filed = (
                    f" (filed {reporting_period.finalized_at:%Y-%m-%d})"
                    if reporting_period.finalized_at
                    else ""
                )
                raise CommandError(
                    f"Refusing to recompute {period}: reporting period "
                    f"'{reporting_period.name}' is finalized{filed}. "
                    f"Re-running would overwrite the filed number. "
                    f"Pass --force to override."
                )
            self.stderr.write(
                self.style.WARNING(
                    f"--force: OVERWRITING finalized period {period} "
                    f"('{reporting_period.name}'). A number already filed with "
                    f"the state is being recomputed — this changes a filed figure."
                )
            )
            # The recorded door through the finalized-period lock:
            # every write below carries override=True and this reason in the
            # change history, and only the lock triggers are switched off.
            self._history.enter_context(override(FORCE_REASON))

    def _process_parcel(
        self,
        parcel: Parcel,
        period: str,
        eff_date: dt.date,
        *,
        dry_run: bool,
        is_metered: bool,
        reporting_period: ReportingPeriod | None,
        plan_id: int | None,
        plan_name: str,
        plan_hash: str,
        gw_water_type: WaterType,
        site_config: SiteConfig,
    ) -> tuple[str | None, bool]:
        """Calculate (and, unless dry-run, write) one parcel-month and print its line.

        Returns ``(outcome, was_over_delivered)``: ``outcome`` is "written",
        "unmet" or "metered" for the summary counts, or ``None`` when the
        parcel has no matched ET and was skipped.
        """
        # "credited" is no longer a choice; a site still holding it runs as
        # "not credited" until the migration has moved it.
        over_delivery_treatment = (
            "named_line"
            if site_config.over_delivery_treatment == "named_line"
            else "not_credited"
        )

        assessment = _assess_et(parcel, period, site_config)
        if assessment is None:
            return None, False
        (final_af, breakdown, gw_efficiency, gw_efficiency_source,
         incidental_af, months_matched, gross_af) = assessment

        routes_personal, pool_zone, prior_run, prior_incidental, prior_has_old_pool_deposit = (
            _over_delivery_routing(parcel, period)
        )

        # The line's note about the over-delivery, shared by the --dry-run
        # preview and the real write below, so the two can never say
        # something different happened.
        over = incidental_af.quantize(Decimal("0.0001"))
        credit_note = _over_delivery_note(over, over_delivery_treatment)

        if dry_run:
            net_af, info = _resolve_leftover(
                parcel, period, final_af, breakdown, commit=False,
            )
            extra = _dry_run_extra(
                breakdown, net_af, incidental_af, credit_note,
                is_metered=is_metered, routes_personal=routes_personal,
                gw_efficiency=gw_efficiency,
            )
            outcome, line = _dry_run_line(
                parcel, gross_af, net_af, extra,
                is_metered=is_metered, routes_personal=routes_personal,
            )
            self.stdout.write(line)
            return outcome, False

        net_af, unmet_demand_af = _commit_parcel_month(
            parcel, period, eff_date, final_af, breakdown, gross_af, months_matched,
            plan_id=plan_id, plan_name=plan_name, plan_hash=plan_hash,
            gw_efficiency=gw_efficiency,
            gw_efficiency_source=gw_efficiency_source,
            over_delivery_treatment=over_delivery_treatment,
            reporting_period=reporting_period, gw_water_type=gw_water_type,
            is_metered=is_metered, routes_personal=routes_personal,
            pool_zone=pool_zone, prior_run=prior_run,
            prior_incidental=prior_incidental,
            prior_has_old_pool_deposit=prior_has_old_pool_deposit,
        )
        extra = _live_extra(incidental_af, credit_note)
        outcome, line = _live_line(
            parcel, gross_af, net_af, unmet_demand_af, extra,
            is_metered=is_metered, routes_personal=routes_personal,
        )
        self.stdout.write(line)
        return outcome, incidental_af > 0

    def _write_summary(
        self,
        period: str,
        dry_run: bool,
        counts: dict[str, int],
        skipped_no_et: int,
        over_delivered: int,
    ) -> None:
        """Print the one-paragraph run summary."""
        written = counts["written"]
        unmet = counts["unmet"]
        metered = counts["metered"]
        verb = "Would write" if dry_run else "Wrote"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {written} calculated GW row(s) for {period}; "
                f"{unmet} no-well parcel(s) recorded as unmet demand; "
                f"{metered} metered parcel(s) given an ET reference run "
                f"(meter authoritative, no GW row); "
                f"{skipped_no_et} parcel(s) skipped (no ET data); "
                f"{over_delivered} field(s) with canal water beyond the "
                f"month's use."
            )
        )
