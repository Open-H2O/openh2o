# SPDX-License-Identifier: AGPL-3.0-or-later
"""One reading of a water year's records, and every sum the pages add up from it.

The dashboard, the water accounts list, a zone's page and the figures a filed year
keeps used to add up a year one place at a time: for each account, each zone and
each use area they asked the database again for the same rows. At 8,906 use areas
that was 202,785 questions for one dashboard. :class:`YearReading` asks for each
kind of record once (the ledger rows of the year, its calculation runs, the
account links, the zone memberships, the plans, credits and carry-over, the canal
records' methods, the fallow periods) in a fixed number of questions, keeps them
per use area, and adds up any set of use areas from that.

Nothing is stored. A reading lives for one page or one collection of figures, and
every figure is still worked out from the records when it is read. The rules are
the ones ``accounting.services`` states, applied to the same rows:

* a ledger row counts through ``ParcelLedger.objects.current()`` and the year's
  ``reporting_period``;
* groundwater rows are ``_groundwater_rows``'s, charged as ``charged_groundwater``
  charges them (a calculated row at its newest run's extraction figure), and every
  quantize happens where it happened before, on the same set's sum;
* runs are ``runs_in_period``'s; account links ``account_parcel_ids``'s; zone
  memberships ``zone_parcel_ids``'s; an account's zones for its allocation are
  every zone its use areas belong to, with no dates, as ``account_allocation``
  reads them.

A reading made with ``parcel_ids`` reads only those use areas' ledger rows and
runs: the single-place functions (``parcel_consumptive_balance`` and the rest)
make one for their own use areas, so a use area's page and the dashboard add up
the same rows the same way.

A past reading (``core.as_of``) puts temporary tables in front of the real ones;
every query here goes through the same models, so it reads the past too.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from functools import cached_property
from typing import Any, Iterable

from core.modules import is_enabled

ZERO = Decimal("0")
_Q4 = Decimal("0.0001")


@dataclass(slots=True)
class _Run:
    """The columns of one calculation run that a figure reads (the names ``CalculationRun`` gives them)."""

    parcel_id: int
    period: str
    period_start: date
    gross_et_af: Decimal | None
    net_consumptive_use_af: Decimal | None
    effective_precip_af: Decimal | None
    deep_percolation_gw_af: Decimal | None
    surface_water_af: Decimal | None
    surface_delivered_af: Decimal | None
    surface_efficiency: Decimal | None
    residual_disposition: str
    unmet_demand_af: Decimal | None
    methodology_plan_name: str
    config_hash: str


@dataclass(slots=True)
class _Month:
    """One use area's billable groundwater and canal water in one calendar month."""

    gw_other: Decimal = ZERO  # groundwater rows other than calculated ones, as stored (negative)
    gw_calculated: Decimal = ZERO  # calculated groundwater rows, as charged (positive)
    gw_calculated_stored: Decimal = ZERO  # the same rows as stored (negative)
    surface: Decimal = ZERO  # canal deliveries, as stored (negative)
    has_surface: bool = False


@dataclass(slots=True)
class _UseArea:
    """One use area's billable ledger rows of the year, summed the ways the figures read them."""

    gw_meter: Decimal = ZERO  # groundwater meter readings, as stored (negative)
    gw_unknown: Decimal = ZERO  # other groundwater rows that are neither meter nor calculated (negative)
    gw_calculated: Decimal = ZERO  # calculated groundwater rows, as stored (negative)
    gw_calculated_charged: Decimal = ZERO  # the same rows as charged (positive)
    has_gw_other: bool = False
    has_gw_calculated: bool = False
    surface: Decimal = ZERO  # every canal delivery, as stored (negative)
    has_surface: bool = False
    surface_own: Decimal = ZERO  # deliveries not divided from a headgate's point, as stored
    has_surface_own: bool = False
    surface_groups: dict = field(default_factory=dict)  # (point pk, first of month) -> sum as stored
    has_calculated: bool = False  # any calculated row (gw_is_estimated)
    has_meter: bool = False  # any meter reading row (gw_is_metered)
    months: dict = field(default_factory=dict)  # first of month -> _Month
    metered: dict = field(default_factory=dict)  # first of month -> groundwater meter readings, as stored


def _first(day: date) -> date:
    return day.replace(day=1)


class YearReading:
    """One water year's records read once, and the figures added up from them.

    ``period`` may be None ("all time": no period filter, open links and
    memberships only), as the single-place functions allow.
    """

    def __init__(self, period, parcel_ids: Iterable[int] | None = None):
        self.period = period
        self.scope = None if parcel_ids is None else set(parcel_ids)
        self._balances: dict[frozenset, dict[str, Any]] = {}

    # -- Reading -------------------------------------------------------------------------

    def _scoped(self, queryset, column="parcel_id"):
        if self.scope is None:
            return queryset
        return queryset.filter(**{f"{column}__in": self.scope})

    @cached_property
    def current(self) -> dict[int, str]:
        """The use areas that count (``Parcel.objects.current()``): pk -> number."""
        from parcels.models import Parcel

        return dict(self._scoped(Parcel.objects.current(), "pk").values_list("pk", "parcel_number"))

    @cached_property
    def well_parcels(self) -> set[int]:
        """Use areas a well irrigates (``WellIrrigatedParcel``, read with no module check, as ``_groundwater_rows`` does)."""
        from wells.models import WellIrrigatedParcel

        return set(self._scoped(WellIrrigatedParcel.objects.all()).values_list("parcel_id", flat=True))

    @cached_property
    def runs(self) -> dict[int, list[_Run]]:
        """The year's runs per use area, by ``runs_in_period``."""
        from accounting.models import CalculationRun
        from accounting.services import runs_in_period

        found: dict[int, list[_Run]] = defaultdict(list)
        names = [f for f in _Run.__dataclass_fields__]
        for row in runs_in_period(self._scoped(CalculationRun.objects.all()), self.period).order_by().values_list(*names):
            run = _Run(*row)
            found[run.parcel_id].append(run)
        return found

    @cached_property
    def ledger(self) -> dict[int, _UseArea]:
        """The year's billable ledger rows per use area, summed (``_groundwater_rows``)."""
        from accounting.models import CalculationRun
        from parcels.models import ParcelLedger

        rows = ParcelLedger.objects.current()
        if self.period is not None:
            rows = rows.filter(reporting_period=self.period)
        rows = list(
            self._scoped(rows).order_by().values_list(
                "parcel_id", "source_type", "effective_date", "amount_acre_feet", "water_type__code",
                "water_type_id", "divided_from_headgate", "divided_from_point_pk",
            )
        )
        # A calculated row charges its newest run's extraction figure, where the run stamped one.
        calculated_keys = {(pid, day) for pid, source, day, amount, *_ in rows if source == "calculated" and amount < 0}
        extracted: dict[tuple[int, date], Decimal | None] = {}
        if calculated_keys:
            runs = self._scoped(
                CalculationRun.objects.filter(period_start__in={day for _, day in calculated_keys})
            ).order_by("created_at").values_list("parcel_id", "period_start", "gw_extracted_af")
            for pid, start, figure in runs:
                if (pid, start) in calculated_keys:
                    extracted[(pid, start)] = figure  # oldest first, so the newest is kept

        found: dict[int, _UseArea] = defaultdict(_UseArea)
        for pid, source, day, amount, code, type_id, divided, point in rows:
            area = found[pid]
            month = area.months.get(_first(day))
            if month is None:
                month = area.months[_first(day)] = _Month()
            if source == "calculated":
                area.has_calculated = True
            elif source == "meter_reading":
                area.has_meter = True
            if source == "surface_diversion":
                area.surface += amount
                area.has_surface = True
                month.surface += amount
                month.has_surface = True
                if not divided or point is None:
                    area.surface_own += amount
                    area.has_surface_own = True
                else:
                    key = (point, _first(day))
                    area.surface_groups[key] = area.surface_groups.get(key, ZERO) + amount
            if amount >= 0:
                continue
            groundwater_typed = code is not None and code.upper() == "GW" and source != "surface_diversion"
            is_groundwater = (
                groundwater_typed
                or (source == "meter_reading" and type_id is None)
                or source == "calculated"
            )
            if not is_groundwater:
                continue
            if source == "calculated":
                figure = extracted.get((pid, day))
                charged = figure if figure is not None else amount * -1
                area.gw_calculated += amount
                area.gw_calculated_charged += charged
                area.has_gw_calculated = True
                month.gw_calculated += charged
                month.gw_calculated_stored += amount
            else:
                area.has_gw_other = True
                month.gw_other += amount
                if source == "meter_reading":
                    area.gw_meter += amount
                    area.metered[_first(day)] = area.metered.get(_first(day), ZERO) + amount
                else:
                    area.gw_unknown += amount
        return found

    @cached_property
    def links(self) -> list[tuple[int, int, date | None]]:
        """Every account link: (account pk, use area pk, removed date)."""
        from accounting.models import WaterAccountParcel

        return list(WaterAccountParcel.objects.order_by("pk").values_list("water_account_id", "parcel_id", "removed_date"))

    @cached_property
    def account_ids(self) -> dict[int, list[int]]:
        """Each account's use areas in the year (``account_parcel_ids``)."""
        start = None if self.period is None else self.period.start_date
        found: dict[int, dict[int, None]] = defaultdict(dict)
        for account, pid, removed in self.links:
            if (removed is None) if start is None else (removed is None or removed >= start):
                found[account][pid] = None
        return {account: list(pids) for account, pids in found.items()}

    @cached_property
    def memberships(self) -> list[tuple[int, int, date | None, date | None]]:
        """Every zone membership: (zone pk, use area pk, start date, end date)."""
        from geography.models import ParcelZone

        return list(ParcelZone.objects.order_by("pk").values_list("zone_id", "parcel_id", "start_date", "end_date"))

    @cached_property
    def zone_ids(self) -> dict[int, list[int]]:
        """Each zone's use areas in the year (``zone_parcel_ids``)."""
        found: dict[int, dict[int, None]] = defaultdict(dict)
        for zone, pid, start, end in self.memberships:
            if self.period is None:
                counts = end is None
            else:
                counts = (start is None or start <= self.period.end_date) and (
                    end is None or end >= self.period.start_date
                )
            if counts:
                found[zone][pid] = None
        return {zone: list(pids) for zone, pids in found.items()}

    @cached_property
    def zones_of_use_area(self) -> dict[int, list[int]]:
        """Every zone a use area belongs to, with no dates (``account_allocation`` reads them so)."""
        found: dict[int, dict[int, None]] = defaultdict(dict)
        for zone, pid, _, _ in self.memberships:
            found[pid][zone] = None
        return {pid: list(zones) for pid, zones in found.items()}

    @cached_property
    def acres(self) -> dict[int, Decimal]:
        """Every current use area's area as its page shows it (none is 0), as ``_field_acres`` reads it."""
        from parcels.models import Parcel

        return {pid: area or ZERO for pid, area in Parcel.objects.current().values_list("pk", "area_acres")}

    @cached_property
    def groundwater_type(self):
        from accounting.services import _groundwater_type

        return _groundwater_type()

    @cached_property
    def groundwater_plans(self) -> dict[int, Decimal]:
        """Each zone's groundwater allocation in the year (the sum of its plans); a zone with none is absent."""
        from accounting.models import AllocationPlan

        found: dict[int, Decimal] = {}
        if self.groundwater_type is None or self.period is None:
            return found
        for zone, amount in AllocationPlan.objects.filter(
            reporting_period=self.period, water_type=self.groundwater_type
        ).order_by().values_list("zone_id", "allocation_acre_feet"):
            found[zone] = found.get(zone, ZERO) + amount
        return found

    @cached_property
    def water_year(self) -> int:
        from accounting.services import account_water_year

        return account_water_year(self.period)

    @cached_property
    def carryover_by_origin(self) -> dict[int, dict[str, Decimal]]:
        """Each zone's groundwater carry-over rows of the water year, summed by origin (``_zone_rows_by_origin``)."""
        from accounting.models import AllocationCarryover

        found: dict[int, dict[str, Decimal]] = defaultdict(dict)
        for zone, origin, amount in AllocationCarryover.objects.filter(
            water_year=self.water_year, water_type__code__iexact="GW"
        ).order_by().values_list("zone_id", "origin", "amount_af"):
            found[zone][origin] = found[zone].get(origin, ZERO) + amount
        return found

    @cached_property
    def credits(self) -> dict[int, list]:
        """Each account's groundwater credits of the water year, ordered as ``account_credits`` orders them."""
        from accounting.models import AccountCredit

        found: dict[int, list] = defaultdict(list)
        for credit in AccountCredit.objects.filter(
            water_year=self.water_year, water_type__code__iexact="GW"
        ).order_by("origin", "source_key"):
            found[credit.water_account_id].append(credit)
        return found

    @cached_property
    def surface_methods(self) -> dict[tuple[int, date], dict[str, Decimal]]:
        """The direct-use canal records' volumes by kind of measurement, per (point, first of month)."""
        from accounting.services import SURFACE_METHOD_KINDS

        keys = {key for area in self.ledger.values() for key in area.surface_groups}
        found: dict[tuple[int, date], dict[str, Decimal]] = {}
        if not keys or not is_enabled("surface"):
            return found
        from surface.models import DiversionRecord

        first = min(month for _, month in keys)
        last = max(month for _, month in keys)
        after_last = date(last.year + (last.month == 12), last.month % 12 + 1, 1)
        records = DiversionRecord.objects.current().filter(
            diversion_type="direct_use",
            point_of_diversion_id__in={point for point, _ in keys},
            month__gte=first,
            month__lt=after_last,
        ).order_by().values_list("point_of_diversion_id", "month", "method", "volume_acre_feet")
        for point, month, method, volume in records:
            kind = SURFACE_METHOD_KINDS.get(method, "unknown")
            by_kind = found.setdefault((point, _first(month)), {})
            by_kind[kind] = by_kind.get(kind, ZERO) + (volume or ZERO)
        return found

    @cached_property
    def fallow(self) -> dict[int, list[tuple[date | None, date | None]]]:
        """Each use area's fallow periods that count: (start month, end month)."""
        from parcels.models import FallowPeriod

        found: dict[int, list] = defaultdict(list)
        for pid, start, end in self._scoped(FallowPeriod.objects.current()).values_list(
            "parcel_id", "start_month", "end_month"
        ):
            found[pid].append((start, end))
        return found

    @cached_property
    def waiting(self) -> dict[int, list[date]]:
        """Each use area's months of the year waiting for OpenET (``datasync.crop_et.waiting_months``)."""
        if self.period is None or not is_enabled("datasync"):
            return {}
        from datasync.crop_et import waiting_months

        ids = self.scope if self.scope is not None else self.current
        return waiting_months(ids, self.period.start_date, self.period.end_date)

    # -- Adding up -------------------------------------------------------------------------

    def _counted(self, parcel_ids: Iterable[int]) -> list[int]:
        """The given use areas that count, each once."""
        current = self.current
        return [pid for pid in dict.fromkeys(parcel_ids) if pid in current]

    def charged(self, parcel_ids: Iterable[int]) -> Decimal:
        """``charged_groundwater`` over the set's billable rows."""
        other = ZERO
        calculated = ZERO
        ledger = self.ledger
        for pid in self._counted(parcel_ids):
            area = ledger.get(pid)
            if area is not None:
                other += area.gw_meter + area.gw_unknown
                calculated += area.gw_calculated_charged
        return (abs(other) + calculated).quantize(_Q4)

    def consumptive_use_balance(self, parcel_ids: Iterable[int]) -> dict[str, Any]:
        """``accounting.services.consumptive_use_balance`` for the set, from this reading.

        The balance counts a use area's ledger water only in the months it has a calculation
        run in: a month waiting for OpenET is left out whole, its canal water and meter
        readings with its rain and crop use (ruling 211). ``groundwater_charged``, the
        allocation's figure, keeps every month. ``recorded`` is every month's canal water and
        groundwater, for a page that lists the recorded supplies of a use area with nothing
        counted. ``last_counted`` is the latest month with a run and ``waiting`` the months
        waiting for OpenET, for the line that says what the balance covers.
        """
        from accounting.services import _run_water_not_consumed

        ids = frozenset(parcel_ids)
        found = self._balances.get(ids)
        if found is None:
            counted = self._counted(ids)
            consumed = other = calculated_charged = surface = ZERO
            all_other = all_calculated_charged = all_surface = ZERO
            gross = net = precip = not_consumed = ZERO
            run_count = 0
            last_counted = None
            waiting: set[date] = set()
            use_areas_waiting = 0
            ledger = self.ledger
            for pid in counted:
                area = ledger.get(pid)
                runs = self.runs.get(pid, ())
                run_months = {run.period_start for run in runs}
                if area is not None:
                    all_other += area.gw_meter + area.gw_unknown
                    all_calculated_charged += area.gw_calculated_charged
                    all_surface += area.surface
                    for month, sums in area.months.items():
                        if month not in run_months:
                            continue
                        consumed += sums.gw_other + sums.gw_calculated_stored
                        other += sums.gw_other
                        calculated_charged += sums.gw_calculated
                        surface += sums.surface
                metered = area.metered if area is not None else {}
                for run in runs:
                    gross += run.gross_et_af or ZERO
                    net += run.net_consumptive_use_af or ZERO
                    precip += run.effective_precip_af or ZERO
                    month_metered = metered.get(run.period_start)
                    not_consumed += _run_water_not_consumed(
                        run, None if month_metered is None else abs(month_metered)
                    )
                    run_count += 1
                    if last_counted is None or run.period_start > last_counted:
                        last_counted = run.period_start
                months_waiting = self.waiting.get(pid)
                if months_waiting:
                    waiting.update(months_waiting)
                    use_areas_waiting += 1
            charged = (abs(other) + calculated_charged).quantize(_Q4)
            surface = abs(surface)
            supply_total = surface + charged + precip
            found = {
                "consumptive_use_gross": gross,
                "consumptive_use_net": net,
                "supplies": {"surface": surface, "groundwater": charged, "precip": precip},
                "supply_total": supply_total,
                "groundwater_consumed": abs(consumed),
                "water_not_consumed": not_consumed,
                "uses_total": gross + not_consumed,
                "net_vs_supply": supply_total - gross - not_consumed,
                "groundwater_charged": (abs(all_other) + all_calculated_charged).quantize(_Q4),
                "recorded": {
                    "surface": abs(all_surface),
                    "groundwater": (abs(all_other) + all_calculated_charged).quantize(_Q4),
                },
                "calculation_runs": run_count,
                "last_counted": last_counted,
                "waiting": sorted(waiting),
                "use_areas_waiting": use_areas_waiting,
            }
            self._balances[ids] = found
        return {
            **found,
            "supplies": dict(found["supplies"]),
            "recorded": dict(found["recorded"]),
            "waiting": list(found["waiting"]),
        }

    def covered(self, parcel_ids: Iterable[int]) -> dict[str, Any]:
        """What the set's balance covers: the latest month counted and the months waiting for OpenET."""
        balance = self.consumptive_use_balance(parcel_ids)
        return {
            "last": balance["last_counted"],
            "waiting": balance["waiting"],
            "use_areas_waiting": balance["use_areas_waiting"],
        }

    def surface_delivered(self, parcel_ids: Iterable[int]) -> Decimal:
        """The magnitude of the set's billable canal deliveries."""
        total = ZERO
        for pid in self._counted(parcel_ids):
            area = self.ledger.get(pid)
            if area is not None:
                total += area.surface
        return abs(total)

    def groundwater_kind_terms(self, parcel_ids: Iterable[int]) -> list[tuple[str, Decimal]]:
        """``groundwater_kind_terms`` over the set's billable rows: each kind's part charged and quantized on its own."""
        meter = unknown = calculated = ZERO
        for pid in self._counted(parcel_ids):
            area = self.ledger.get(pid)
            if area is not None:
                meter += area.gw_meter
                unknown += area.gw_unknown
                calculated += area.gw_calculated_charged
        terms = [
            ("metered", abs(meter).quantize(_Q4)),
            ("estimated", calculated.quantize(_Q4)),
            ("unknown", abs(unknown).quantize(_Q4)),
        ]
        return [(kind, amount) for kind, amount in terms if amount]

    def surface_kind_terms(self, parcel_ids: Iterable[int]) -> list[tuple[str, Decimal]]:
        """``surface_kind_terms`` over the set's billable rows."""
        from accounting.services import split_surface_kinds

        own = ZERO
        groups: dict[tuple[int, date], Decimal] = {}
        for pid in self._counted(parcel_ids):
            area = self.ledger.get(pid)
            if area is None:
                continue
            own += area.surface_own
            for key, amount in area.surface_groups.items():
                groups[key] = groups.get(key, ZERO) + amount
        methods = self.surface_methods if groups else {}
        return split_surface_kinds(own, groups, methods)

    def supply_kind_terms(self, parcel_ids: Iterable[int]) -> dict[str, list[tuple[str, Decimal]]]:
        ids = list(parcel_ids)
        return {"surface": self.surface_kind_terms(ids), "groundwater": self.groundwater_kind_terms(ids)}

    # -- Accounts and zones -------------------------------------------------------------

    def account_parcel_ids(self, account) -> list[int]:
        return list(self.account_ids.get(account.pk, ()))

    def zone_parcel_ids(self, zone) -> list[int]:
        return list(self.zone_ids.get(zone.pk, ()))

    def account_consumptive_balance(self, account) -> dict[str, Any]:
        return self.consumptive_use_balance(self.account_parcel_ids(account))

    def zone_consumptive_balance(self, zone) -> dict[str, Any]:
        return self.consumptive_use_balance(self.zone_parcel_ids(zone))

    def account_allocation(self, account) -> Decimal | None:
        """``account_allocation``: the account's acre share of each of its zones' groundwater allocation."""
        if self.groundwater_type is None:
            return None
        mine = set(self.account_parcel_ids(account))
        zones: dict[int, None] = {}
        for pid in mine:
            for zone in self.zones_of_use_area.get(pid, ()):
                zones[zone] = None
        total = None
        for zone in sorted(zones):
            plans = self.groundwater_plans.get(zone)
            if plans is None:
                continue
            acres = {pid: self.acres[pid] for pid in self.zone_ids.get(zone, ()) if pid in self.acres}
            members = list(acres)
            if not mine.intersection(members):
                continue
            zone_acres = sum(acres.values(), ZERO)
            if zone_acres > 0:
                share = sum((acres[p] for p in members if p in mine), ZERO) / zone_acres
            else:
                share = Decimal(len([p for p in members if p in mine])) / Decimal(len(members) or 1)
            total = (total or ZERO) + plans * share
        return None if total is None else total.quantize(_Q4)

    def account_credits(self, account) -> list:
        return list(self.credits.get(account.pk, ()))

    def account_groundwater_budget(self, account) -> dict[str, Any]:
        """``account_groundwater_budget`` from this reading."""
        allocation = self.account_allocation(account)
        credits = self.account_credits(account)
        used = self.account_consumptive_balance(account)["groundwater_charged"]
        if allocation is None:
            return {"allocation": None, "credits": credits, "used": used, "remaining": None}
        credit_total = sum((c.amount_af for c in credits), ZERO)
        return {"allocation": allocation, "credits": credits, "used": used, "remaining": allocation + credit_total - used}

    def zone_carryover(self, zone) -> Decimal:
        """``zone_carryover`` for the reading's water year."""
        return self.carryover_by_origin.get(zone.pk, {}).get("allocation_carryover") or ZERO

    def zone_rows_by_origin(self, zone) -> dict[str, Decimal]:
        return dict(self.carryover_by_origin.get(zone.pk, {}))

    def zone_groundwater_budget(self, zone) -> dict[str, Decimal | None]:
        """``zone_groundwater_budget`` from this reading."""
        from accounting.carryover_math import available_with_carryover

        used = self.charged(self.zone_parcel_ids(zone))
        allocation = self.groundwater_plans.get(zone.pk)
        if allocation is None:
            return {"allocation": None, "carryover": None, "available": None, "used": used, "remaining": None}
        carryover = self.zone_carryover(zone)
        available = available_with_carryover(allocation, carryover)
        return {
            "allocation": allocation,
            "carryover": carryover,
            "available": available,
            "used": used,
            "remaining": available - used,
        }

    # -- Use areas ------------------------------------------------------------------------

    def has_runs(self, pid: int) -> bool:
        return bool(self.runs.get(pid))

    def method(self, parcel_ids: Iterable[int]) -> str:
        """``statements._method``: the one method and settings code behind the set's runs, else ""."""
        pairs = {
            (run.methodology_plan_name, run.config_hash)
            for pid in set(parcel_ids)
            for run in self.runs.get(pid, ())
        }
        if len(pairs) != 1:
            return ""
        name, code = next(iter(pairs))
        return f"{name} {code}".strip()

    def is_fallow_in(self, pid: int, day: date) -> bool:
        first = _first(day)
        return any(
            (start is None or start <= first) and (end is None or end >= first)
            for start, end in self.fallow.get(pid, ())
        )

    def unmet_demand_by_parcel(self) -> tuple[list[dict[str, Any]], Decimal]:
        """``unmet_demand_by_parcel``: the use areas with unmet demand in the year, largest first."""
        grouped: dict[int, list[Decimal]] = {}
        for pid, runs in self.runs.items():
            for run in runs:
                if run.residual_disposition == "unmet_demand" and run.unmet_demand_af is not None and run.unmet_demand_af > 0:
                    sums = grouped.setdefault(pid, [ZERO, ZERO, False])
                    sums[0] += run.unmet_demand_af
                    if run.gross_et_af is not None:
                        sums[1] += run.gross_et_af
                        sums[2] = True
        rows = []
        total = ZERO
        for pid, (unmet, gross, has_gross) in sorted(
            grouped.items(), key=lambda item: (-item[1][0], self.current.get(item[0], ""))
        ):
            rows.append({
                "parcel": pid,
                "parcel_number": self.current.get(pid),
                "gross_et": gross if has_gross else ZERO,
                "unmet": unmet,
            })
            total += unmet
        return rows, total

    def water_use_months(self, parcel, with_groundwater: bool = True) -> dict[str, Any]:
        """``parcel_water_use_months`` for one use area of this reading."""
        from accounting.services import (
            _first_of_next_month,
            _month_starts,
            round_to_total,
            supply_kind_lines,
        )

        period = self.period
        starts = _month_starts(period.start_date, period.end_date)
        exact: dict[str, dict[date, Decimal]] = {
            key: {m: ZERO for m in starts} for key in ("et", "surface", "groundwater", "precip")
        }
        unmet_months: set[date] = set()
        efficiencies: set[Decimal | None] = set()
        for run in self.runs.get(parcel.pk, ()):
            month = run.period_start
            if month not in exact["et"]:
                continue
            exact["et"][month] += run.gross_et_af or ZERO
            exact["precip"][month] += run.effective_precip_af or ZERO
            if run.residual_disposition == "unmet_demand" and (run.unmet_demand_af or ZERO) > 0:
                unmet_months.add(month)
            if run.surface_delivered_af:
                efficiencies.add(run.surface_efficiency)
        area = self.ledger.get(parcel.pk) or _UseArea()
        for month, sums in area.months.items():
            if month in exact["surface"] and sums.has_surface:
                exact["surface"][month] = abs(sums.surface)
        if with_groundwater:
            for month in starts:
                sums = area.months.get(month)
                charged = ZERO if sums is None else abs(sums.gw_other) + sums.gw_calculated
                exact["groundwater"][month] = charged.quantize(_Q4)
        cents = Decimal("0.01")
        totals = {key: sum(exact[key].values(), ZERO).quantize(cents, rounding=ROUND_HALF_UP) for key in exact}
        shown = {key: round_to_total(exact[key][m] for m in starts) for key in exact}
        waiting = set(self.waiting.get(parcel.pk, ()))
        months = []
        for i, month in enumerate(starts):
            months.append({
                "month": month,
                "last": _first_of_next_month(month) - timedelta(days=1),
                "fallow": self.is_fallow_in(parcel.pk, month),
                "waiting": month in waiting,
                "et": shown["et"][i],
                "surface": shown["surface"][i],
                "groundwater": shown["groundwater"][i],
                "precip": shown["precip"][i],
            })
        return {
            "months": months,
            "totals": totals,
            "unmet_months": sorted(unmet_months),
            "efficiencies": efficiencies,
            "gw_is_estimated": area.has_calculated,
            "gw_is_metered": area.has_meter,
            "kinds": {
                "surface": supply_kind_lines(self.surface_kind_terms([parcel.pk])),
                "groundwater": supply_kind_lines(self.groundwater_kind_terms([parcel.pk])) if with_groundwater else [],
            },
        }

