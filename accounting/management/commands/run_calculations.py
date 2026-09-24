# SPDX-License-Identifier: AGPL-3.0-or-later
"""Run the calculation engine for a period over satellite-estimated consumptive use.

For each in-scope parcel that has gross-ET data for the period, evaluate the
active CalculationPlan and record its net consumptive use on a CalculationRun.
The `ET − precip − surface` residual then resolves by archetype (54-01 / 58-03):
a parcel WITH a well (no meter) gets exactly ONE ParcelLedger row with
source_type="calculated" (its groundwater extraction estimate); a no-well parcel
gets NO calculated row — its residual is recorded as `unmet_demand_af` on the run,
never a phantom groundwater extraction; a METERED parcel also gets NO calculated
row (its meter reading is the authoritative groundwater record — a calculated row
would double-count it) and its run is kept purely as the ET reference value, with
disposition "metered". Both the calculated row and the run are delete-then-insert per
(parcel, month) inside one transaction, so re-running is idempotent: running twice
yields identical balances (no drift, no double-count).

148-02: the rain bank is retired. In a wet month the chain nets below the
floor; clamp_floor surfaces that surplus as `rain_surplus_af` on the run's
breakdown: information about rain the crop did not need, not a credit.
Nothing is deposited and nothing is drawn: `_resolve_leftover` writes no
WaterCredit and no WaterCreditDraw, for any origin. It still CLEARS whatever
a pre-148-02 run of the engine wrote for this parcel-period (its own
WaterCreditDraw rows and its own `precip_surplus`-origin WaterCredit), so a
re-run on a database an older engine wrote removes what it wrote for that
month rather than leaving it stale. `final_af` passes through unchanged.

The WaterCredit / WaterCreditDraw tables and their `precip_surplus` choice
stay on the model so an old database still loads. Nothing writes either
table any more; year-end carry-over (`rollover_allocations`) writes
`AllocationCarryover`, a different model.

148-02 Task 3 (Q1): an over-delivery is nobody's credit. The month's canal
water a parcel could use beyond its net use — clamp_floor's
`incidental_recharge_af` — is recorded ONLY on the run, as
`CalculationRun.over_delivery_af`. No `recharge` ledger row is written for it
(a has-well parcel's old personal credit) and no basin-pool deposit is made
for it (a no-well parcel's old pooled credit); `deposit_to_basin_pool` and
`recharge_routes_to_personal` stay in this module only to CLEAN UP what a
pre-148-02 engine wrote — see `prior_is_pre_148_02`, below — and for the
managed-recharge path (`accounting.services.create_recharge_ledger_entries`),
which this plan does not touch.
"""

import datetime as dt
import re
from contextlib import ExitStack
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from accounting.calculation import evaluate_chain, plan_config_hash
from accounting.carryover_math import water_year_of
from accounting.locks import override
from accounting.ledger_words import (
    INCIDENTAL_RECHARGE_WORDS,
    LEGACY_INCIDENTAL_RECHARGE_WORDS,
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
from accounting.services import INCIDENTAL_RECHARGE_POOL, deposit_to_basin_pool
from geography.models import ParcelZone
from parcels.models import Parcel, ParcelLedger

# The reason recorded on every change a forced recompute of a finalized period
# writes, so the change history says why a filed figure moved.
FORCE_REASON = "--force on a finalized period"

PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


def _incidental_recharge_af(breakdown):
    """Read the deep-percolation recharge magnitude off the clamp_floor step.

    Returns the positive incidental_recharge_af signalled by clamp_floor (ISS-052),
    or Decimal('0') when the step is absent or predates the surplus split.
    """
    clamp = next(
        (s for s in breakdown if s["step_type"] == "clamp_floor"), None
    )
    if clamp is None:
        return Decimal("0")
    return Decimal(str(clamp["detail"].get("incidental_recharge_af", "0")))


def _parcel_pool_zone(parcel):
    """The parcel's GSA management-area zone — where its basin pool lives (ISS-053).

    A no-well parcel's incidental recharge is deposited to this zone's basin pool
    rather than the parcel's own ledger. Mirrors the zone managed recharge pools
    into (``seed_merced_recharge_events`` resolves the basin's management_area
    zone the same way). Returns the first management-area zone, or None.
    """
    pz = (
        ParcelZone.objects.filter(
            parcel=parcel, zone__zone_type="management_area"
        )
        .select_related("zone")
        .first()
    )
    return pz.zone if pz else None


def _resolve_leftover(parcel, period, final_af, breakdown, *, commit):
    """Clear this period's legacy rain-bank state; `final_af` is not touched.

    148-02: the rain bank is retired. This writes NO WaterCredit and NO
    WaterCreditDraw, for any origin: `bank` was the only lever that ever made
    this function deposit or draw, and it is gone. What is left is cleanup:
    when committing, delete whatever a pre-148-02 run of the engine wrote for
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


def _persist_calculation_run(
    parcel, period, gross_af, net_af, breakdown, info, plan_id, plan_name, plan_hash,
    *, residual_disposition, unmet_demand_af,
):
    """Write the one CalculationRun for this (parcel, period) — the audit trail.

    Delete-then-insert so a re-run leaves exactly one run with identical values
    (mirrors the calculated ledger row's idempotency). All AF figures are quantized
    to 4dp the same way the ledger row is, so ``final_af`` equals
    ``-ledger.amount_acre_feet`` exactly. Input magnitudes come straight off the
    breakdown the runner already evaluated; a step that did not run in this chain
    (e.g. effective precip disabled) stores NULL rather than a fabricated zero.

    MUST be called inside the per-parcel transaction.atomic() block.
    """
    quant = Decimal("0.0001")
    precip_step = next(
        (s for s in breakdown if s["step_type"] == "subtract_effective_precip"), None
    )
    surface_step = next(
        (s for s in breakdown if s["step_type"] == "subtract_surface_water"), None
    )

    effective_precip_af = None
    if precip_step is not None:
        effective_precip_af = Decimal(
            str(precip_step["detail"]["effective_precip_af"])
        ).quantize(quant)

    # 148-02: surface_water_af keeps its name and holds the CONSUMED part
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

    # 148-02 Task 3 (Q1): the over-delivery amount lands on the run, read off
    # clamp_floor's over_delivery_af (same value as the legacy
    # incidental_recharge_af key; see steps.py::clamp_floor). No ledger row is
    # written for it any more — see the caller.
    over_delivery_af = _incidental_recharge_af(breakdown).quantize(quant)

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
        net_consumptive_use_af=net_consumptive_use_af,
        residual_disposition=residual_disposition,
        unmet_demand_af=unmet_demand_af,
        banked_af=info["deposited"],
        drawn_af=info["drawn"],
        final_af=net_af.quantize(quant),
        breakdown=breakdown,
        methodology_plan_id=plan_id,
        methodology_plan_name=plan_name,
        config_hash=plan_hash,
    )


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

        parcels = Parcel.objects.all().order_by("parcel_number")
        if options.get("parcel"):
            parcels = parcels.filter(parcel_number=options["parcel"])
            if not parcels.exists():
                raise CommandError(
                    f"no parcel with parcel_number={options['parcel']!r}"
                )

        # 58-03: the engine now runs on EVERY parcel — including metered ones. A
        # parcel that carries an authoritative meter_reading row for this period is
        # NO LONGER skipped (it was, in 54-01). Instead it gets an ET-bearing
        # reference CalculationRun (what the crop actually consumed, the district
        # reference value for the dashboard + reports) but NO calculated groundwater
        # row — the meter reading already measured that groundwater, so a calculated
        # row would double-count it (the same 54-01 reasoning, now expressed as a
        # disposition instead of an exclusion). `metered_row_ids` is still the
        # authoritative-reading detector; we carry it INTO the loop as a per-parcel
        # `is_metered` flag rather than dropping those parcels up front.
        metered_row_ids = set(
            ParcelLedger.objects.filter(
                source_type="meter_reading",
                effective_date__year=year,
                effective_date__month=month,
            ).values_list("parcel_id", flat=True)
        )

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

        reporting_period = ReportingPeriod.objects.filter(
            start_date__lte=eff_date, end_date__gte=eff_date
        ).first()

        # Finalized-period write guard (ISS-020 #1). A finalized ReportingPeriod
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
            if not options["force"]:
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
            # The recorded door through the finalized-period lock (147-02):
            # every write below carries override=True and this reason in the
            # change history, and only the lock triggers are switched off.
            self._history.enter_context(override(FORCE_REASON))

        # Snapshot the methodology ONCE: the active plan is identical for every
        # parcel in a single run, so hashing per-parcel would be wasted work and
        # could tear if the plan were edited mid-run. These copied values (not a
        # FK) are stamped onto each CalculationRun so the filed number names its
        # recipe even after the live plan changes (ISS-020 #2).
        active_plan = CalculationPlan.active()
        plan_hash = plan_config_hash(active_plan) if active_plan else ""
        plan_id = active_plan.id if active_plan else None
        plan_name = active_plan.name if active_plan else ""

        # GW water type for incidental-recharge rows (ISS-052); resolved once.
        gw_water_type, _ = WaterType.objects.get_or_create(
            code="GW", defaults={"name": "Groundwater"}
        )

        written = 0
        unmet = 0
        metered = 0
        skipped_no_et = 0
        over_delivered = 0
        for parcel in parcels:
            is_metered = parcel.id in metered_row_ids
            final_af, breakdown = evaluate_chain(parcel, period)
            incidental_af = _incidental_recharge_af(breakdown)

            et_step = next(
                (s for s in breakdown if s["step_type"] == "et_gross"), None
            )
            # ISS-025: gate on months_matched (items actually date-matched for THIS
            # month), NOT rows (the span-row count). A cache row can span the period
            # yet carry no item dated in it (months_matched==0, rows>0); gating on
            # rows would file a fabricated 0-AF `calculated` row for a parcel with
            # no real ET — the silent-zero trap Phase 38 exists to kill.
            months_matched = (
                et_step["detail"].get("months_matched", 0) if et_step else 0
            )
            has_et = bool(et_step and months_matched > 0)
            if not has_et:
                skipped_no_et += 1
                continue

            gross_af = Decimal(et_step["output_af"]) if et_step else Decimal("0")

            # 148-02 Task 3 (Q1): an over-delivery is nobody's credit. No ledger
            # row and no pool deposit is written for it any more — the amount
            # lands on the run as over_delivery_af (_persist_calculation_run,
            # below). routes_personal / pool_zone still decide WHERE a stale
            # pre-148-02 write needs cleaning up: a has-well parcel's old personal
            # row is caught by the delete-by-prefix inside the transaction; a
            # no-well parcel's old POOL deposit needs an explicit one-time
            # reversal, decided next.
            routes_personal = recharge_routes_to_personal(parcel)
            pool_zone = None if routes_personal else _parcel_pool_zone(parcel)
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
            # A run written by THIS (148-02) engine always carries
            # over_delivery_af in its clamp_floor detail (see steps.py). Its
            # absence, alongside a positive incidental_recharge_af, means the
            # prior run predates this change and deposited that amount to the
            # basin pool — reverse it exactly once. A second re-run sees a
            # prior breakdown that already carries over_delivery_af (this
            # engine's own last write) and reverses nothing, so a re-run never
            # double-reverses.
            prior_is_pre_148_02 = (
                prior_clamp is not None
                and "over_delivery_af" not in prior_clamp["detail"]
                and prior_incidental > 0
            )

            if dry_run:
                net_af, info = _resolve_leftover(
                    parcel, period, final_af, breakdown, commit=False,
                )
                extra = ""
                if incidental_af > 0:
                    extra += (
                        f"; {incidental_af.quantize(Decimal('0.0001'))} AF canal "
                        f"water beyond the month's use, would be recorded on the run"
                    )
                # 148-02: a canal-served field's line also names what was
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
                if is_metered:
                    self.stdout.write(
                        f"  {parcel.parcel_number}: gross {gross_af} AF -> "
                        f"net {net_af} AF (metered — ET reference run, meter "
                        f"authoritative, no GW row){extra}"
                    )
                    metered += 1
                elif routes_personal:
                    self.stdout.write(
                        f"  {parcel.parcel_number}: gross {gross_af} AF -> "
                        f"net {net_af} AF (would write {-net_af} AF GW){extra}"
                    )
                    written += 1
                else:
                    unmet_preview = max(Decimal("0"), net_af).quantize(
                        Decimal("0.0001")
                    )
                    self.stdout.write(
                        f"  {parcel.parcel_number}: gross {gross_af} AF -> "
                        f"net {net_af} AF (no well — would record {unmet_preview} AF "
                        f"unmet demand, no GW row){extra}"
                    )
                    unmet += 1
                continue

            with transaction.atomic():
                net_af, info = _resolve_leftover(
                    parcel, period, final_af, breakdown, commit=True,
                )
                # ISS-025 invariant, explicit at the write site: a `calculated`
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
                # 54-01 / 58-03: the residual (ET − precip − surface, surfaced as
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
                    # ISS-158: the zero stays a zero. Nothing else in this
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
                # 38-05: persist the reconstructable audit record in the SAME
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
                )
                # 148-02 Task 3 (Q1): an over-delivery is nobody's credit — no
                # `recharge` ledger row and no basin-pool deposit is written for
                # it, on either archetype. The amount is recorded ONLY on the
                # run, as over_delivery_af (_persist_calculation_run, above).
                # This delete-by-prefix still runs, unconditionally, so a re-run
                # on a database an OLDER engine wrote (either wording,
                # INCIDENTAL_RECHARGE_WORDS or the pre-143-11
                # LEGACY_INCIDENTAL_RECHARGE_WORDS) cleans up that engine's
                # stale PERSONAL row rather than leaving it stand unexplained
                # beside a run that no longer writes one.
                ParcelLedger.objects.filter(
                    Q(description__startswith=INCIDENTAL_RECHARGE_WORDS)
                    | Q(description__startswith=LEGACY_INCIDENTAL_RECHARGE_WORDS),
                    parcel=parcel,
                    effective_date=eff_date,
                    source_type="recharge",
                ).delete()
                if pool_zone is not None and prior_is_pre_148_02:
                    # No well, and the prior run at this (parcel, period) was
                    # written by an engine that deposited its incidental amount
                    # to the basin pool. Reverse exactly that deposit, once — a
                    # negative delta with nothing added back. A later re-run's
                    # "prior" is THIS run, which carries over_delivery_af, so
                    # prior_is_pre_148_02 is False and nothing reverses again.
                    deposit_to_basin_pool(
                        pool_zone,
                        gw_water_type,
                        water_year_of(period),
                        -prior_incidental,
                        origin=INCIDENTAL_RECHARGE_POOL,
                    )
            extra = ""
            if incidental_af > 0:
                extra += (
                    f"; {incidental_af.quantize(Decimal('0.0001'))} AF canal "
                    f"water beyond the month's use, recorded on the run"
                )
                over_delivered += 1
            if is_metered:
                self.stdout.write(
                    f"  {parcel.parcel_number}: gross {gross_af} AF -> "
                    f"net {net_af} AF (metered — ET reference run, meter "
                    f"authoritative, no GW row){extra}"
                )
                metered += 1
            elif routes_personal:
                self.stdout.write(
                    f"  {parcel.parcel_number}: gross {gross_af} AF -> "
                    f"net {net_af} AF (wrote {-net_af} AF GW){extra}"
                )
                written += 1
            else:
                self.stdout.write(
                    f"  {parcel.parcel_number}: gross {gross_af} AF -> "
                    f"net {net_af} AF (no well — recorded {unmet_demand_af} AF "
                    f"unmet demand, no GW row){extra}"
                )
                unmet += 1

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
