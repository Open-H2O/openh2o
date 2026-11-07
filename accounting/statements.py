# SPDX-License-Identifier: AGPL-3.0-or-later
"""The figures of a water year as they stood when it was filed, and how they have moved since.

Every balance on every page is computed when the page is read, so after a
correction the figure a year was filed with is gone from every screen. This
module keeps it. Finalizing a year writes one :class:`~accounting.models.PeriodStatement`
whose rows are the figures the pages print for that year, read off the SAME
functions the pages call and never a second computation:

* a use area, month by month and for the year: ``parcel_water_use_months`` and the
  balance line ``parcels.views._balance_line`` builds (only where the use area's
  page shows the Water use card);
* an account: the Dashboard's account rows (``_account_summary_row`` through
  ``dashboard._account_rollup``), ``account_consumptive_balance`` for its uses and
  ``account_groundwater_budget`` for its budget and credits;
* a zone: ``dashboard._zone_summary_rows`` and ``geography.views._zone_budget_row``;
* the district: the totals ``dashboard._account_rollup`` rolls up.

:func:`take_statement` saves them, :func:`figures_now` returns the same set
without saving (one collector, so the two cannot differ), and
:func:`moved_figures` compares the newest statement with the figures now.
A figure counts as moved when the two differ at the two places the pages print,
rounded half up. The view modules are imported inside the functions that need
them: they import this module's callers.

Values are held at four places, as the ledger stores them, so a figure read now
and the same figure read back from a row are the same number.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.apps import apps
from django.core.cache import cache
from django.db import transaction
from django.db.models import Max, Q
from django.urls import reverse
from django.utils import timezone

from accounting.models import (
    AllocationPlan,
    CalculationRequest,
    CalculationRun,
    PeriodStatement,
    PeriodStatementRow,
    WaterAccount,
    WaterType,
)
from accounting.services import (
    account_consumptive_balance,
    account_groundwater_budget,
    account_parcel_ids,
    parcel_consumptive_balance,
    runs_in_period,
    zone_parcel_ids,
)
from core.modules import is_enabled

# -- The figures -----------------------------------------------------------------------

#: Every figure a statement keeps: ``(key, the words a screen prints)``. One fixed
#: tuple; a row's ``figure`` is one of these keys. A credit's words are its own
#: description, kept on the row (``detail``).
FIGURES = (
    ("crop_et", "Crop ET"),
    ("surface_delivered", "Surface water delivered"),
    ("groundwater_extraction", "Groundwater extraction"),
    ("effective_precipitation", "Effective precipitation"),
    ("supplies", "Supplies"),
    ("uses", "Uses"),
    ("water_not_consumed", "Pumped water not consumed"),
    ("balance", "Balance"),
    ("allocation", "Allocation"),
    ("carryover", "Carry-over"),
    ("available", "Available"),
    ("credit", "Credit"),
    ("used", "Groundwater budget used"),
    ("remaining", "Groundwater budget remaining"),
    ("delivered", "Delivered"),
)
FIGURE_LABELS = dict(FIGURES)
FIGURE_KEYS = tuple(key for key, _ in FIGURES)

#: The order a place's page prints its figures in, which is the order of :data:`FIGURES`.
_ORDER = {key: i for i, key in enumerate(FIGURE_KEYS)}

#: The figures that read a calculation run, which therefore name the run's method.
RUN_FIGURES = frozenset(
    {
        "crop_et",
        "effective_precipitation",
        "supplies",
        "uses",
        "water_not_consumed",
        "balance",
    }
)

#: What an account's name is joined to its number with in ``scope_name``.
ACCOUNT_JOIN = " · "

#: The sentence a statement of a year finalized before OpenH2O kept figures starts with.
UPGRADE_HEAD = "Recorded when OpenH2O began keeping filed figures"

#: The reason the upgrade and the demonstration record their statements under.
UPGRADE_REASON = "Recorded when OpenH2O began keeping filed figures."

_CENTS = Decimal("0.01")
_FOUR = Decimal("0.0001")


def _q4(value):
    """A figure at the four places the ledger keeps, half up; None stays None."""
    if value is None:
        return None
    return Decimal(value).quantize(_FOUR, rounding=ROUND_HALF_UP)


def _q2(value):
    """A figure at the two places the pages print, half up, with no negative zero."""
    if value is None:
        return None
    return Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP) + Decimal("0")


def shown(value):
    """The two-place text a line prints: ``1,289.13``."""
    return f"{_q2(value):,.2f}"


@dataclass(frozen=True)
class Figure:
    """One figure of one place: a row of a statement, saved or not."""

    scope: str
    scope_id: int | None
    scope_name: str
    month: dt.date | None
    figure: str
    value: Decimal | None
    method: str = ""
    detail: str = ""

    @property
    def key(self):
        return (self.scope, self.scope_id, self.month, self.figure, self.detail)


# -- Collecting what the pages print -------------------------------------------------------


def _method(parcel_ids, period):
    """The calculation method and settings code every run behind a place came from, or "".

    Blank when the place has no run or its runs came from more than one method.
    """
    pairs = set(
        runs_in_period(CalculationRun.objects.filter(parcel_id__in=list(parcel_ids)), period)
        .order_by()
        .values_list("methodology_plan_name", "config_hash")
        .distinct()
    )
    if len(pairs) != 1:
        return ""
    name, code = next(iter(pairs))
    return f"{name} {code}".strip()


def _figure(scope, scope_id, scope_name, figure, value, *, method="", month=None, detail=""):
    return Figure(
        scope=scope,
        scope_id=scope_id,
        scope_name=scope_name,
        month=month,
        figure=figure,
        value=_q4(value),
        method=method if figure in RUN_FIGURES else "",
        detail=detail,
    )


def _use_area_figures(period):
    """Each use area whose page shows the Water use card: its months, its year and its balance line."""
    from parcels.models import Parcel
    from parcels.views import _balance_line, water_use_for

    surface_on = is_enabled("surface")
    found = []
    for parcel in Parcel.objects.current().order_by("parcel_number"):
        consumptive = parcel_consumptive_balance(parcel, period)
        water_use, has_well = water_use_for(parcel, period)
        if water_use is None:
            continue
        line = _balance_line(consumptive, water_use, has_well)
        method = _method([parcel.pk], period)

        def add(figure, value, month=None, _parcel=parcel, _method_text=method):
            found.append(
                _figure(
                    "use_area", _parcel.pk, _parcel.parcel_number, figure, value,
                    method=_method_text, month=month,
                )
            )

        columns = [("crop_et", "et")]
        if surface_on:
            columns.append(("surface_delivered", "surface"))
        if has_well:
            columns.append(("groundwater_extraction", "groundwater"))
        columns.append(("effective_precipitation", "precip"))
        for cell in water_use["months"]:
            for figure, column in columns:
                add(figure, cell[column], cell["month"])
        for figure, column in columns:
            add(figure, water_use["totals"][column])
        add("supplies", line["supplies"])
        add("uses", line["uses"])
        add("water_not_consumed", consumptive["water_not_consumed"])
        add("balance", line["balance"])
    return found


def _account_figures(period, rollup):
    found = []
    for row in rollup["account_summaries"]:
        account = row["account"]
        name = f"{account.account_number}{ACCOUNT_JOIN}{account.name}"
        method = _method(account_parcel_ids(account, period), period)

        def add(figure, value, _account=account, _name=name, _method_text=method, **extra):
            found.append(
                _figure("account", _account.pk, _name, figure, value, method=_method_text, **extra)
            )

        uses = account_consumptive_balance(account, reporting_period=period)["uses_total"]
        add("crop_et", row["consumptive_use_gross"])
        add("surface_delivered", row["surface"])
        add("groundwater_extraction", row["groundwater"])
        add("effective_precipitation", row["precip"])
        add("supplies", row["supply_total"])
        add("uses", uses)
        add("water_not_consumed", row["water_not_consumed"])
        add("balance", row["net_vs_supply"])
        budget = account_groundwater_budget(account, period)
        # The account page's Groundwater budget card: shown with a zone
        # ceiling, or with credits and no ceiling.
        if budget["allocation"] is not None or budget["credits"]:
            if budget["allocation"] is not None:
                add("allocation", budget["allocation"])
            for credit in budget["credits"]:
                add("credit", credit.amount_af, detail=credit.description)
            add("used", budget["used"])
            if budget["remaining"] is not None:
                add("remaining", budget["remaining"])
    return found


def _zone_figures(period, has_allocations):
    from accounting.views import dashboard
    from geography.views import _zone_budget_row

    found = []
    for row in dashboard._zone_summary_rows(period, has_allocations):
        zone = row["zone"]
        # The Dashboard dashes a zone's crop ET, pumped water not consumed,
        # balance and remaining when no run is behind it: the row keeps the dash.
        measured = row["has_calculations"]
        method = _method(zone_parcel_ids(zone, period), period)

        def add(figure, value, _zone=zone, _method_text=method):
            found.append(_figure("zone", _zone.pk, _zone.name, figure, value, method=_method_text))

        add("crop_et", row["consumptive_use_gross"] if measured else None)
        add("surface_delivered", row["surface"])
        add("groundwater_extraction", row["groundwater"])
        add("effective_precipitation", row["precip"])
        add("supplies", row["supply_total"])
        add("water_not_consumed", row["water_not_consumed"] if measured else None)
        add("balance", row["net_vs_supply"] if measured else None)
        if row["allocation"] is not None:
            add("allocation", row["allocation"])
            add("carryover", row["carryover"])
            add("remaining", row["remaining"] if measured else None)
        # The zone page's budget table: Available and Used for the groundwater
        # allocation, Delivered for a surface one.
        seen_groundwater = seen_surface = False
        plans = AllocationPlan.objects.filter(zone=zone, reporting_period=period)
        for plan in plans.select_related("water_type", "reporting_period").order_by("pk"):
            budget_row = _zone_budget_row(plan, zone, [])
            if (plan.water_type.code or "").upper() == "GW":
                if not seen_groundwater:
                    seen_groundwater = True
                    add("available", budget_row["available"])
                    add("used", budget_row["used"])
            elif not seen_surface:
                seen_surface = True
                add("delivered", budget_row["used"])
    return found


def _district_figures(period, rollup):
    ids = set()
    for row in rollup["account_summaries"]:
        ids.update(account_parcel_ids(row["account"], period))
    method = _method(ids, period)

    def add(figure, value):
        return _figure("site", None, "", figure, value, method=method)

    return [
        add("crop_et", rollup["grand_consumptive_use"]),
        add("surface_delivered", rollup["grand_supply_surface"]),
        add("groundwater_extraction", rollup["grand_supply_groundwater"]),
        add("effective_precipitation", rollup["grand_supply_precip"]),
        add("supplies", rollup["grand_supply_total"]),
        add("uses", rollup["grand_uses_total"]),
        add("water_not_consumed", rollup["grand_not_consumed"]),
        add("balance", rollup["grand_net"]),
    ]


def collect_figures(period):
    """Every figure the pages print for ``period``, as a list of :class:`Figure`.

    The one collector behind :func:`take_statement` and :func:`figures_now`.
    """
    from accounting.views import dashboard

    has_allocations = AllocationPlan.objects.filter(reporting_period=period).exists()
    groundwater_type = WaterType.objects.filter(code__iexact="GW").first()
    rollup = dashboard._account_rollup(period, has_allocations, groundwater_type)
    return [
        *_use_area_figures(period),
        *_account_figures(period, rollup),
        *_zone_figures(period, has_allocations),
        *_district_figures(period, rollup),
    ]


def figures_now(period):
    """The figures the pages print for ``period`` now, without saving them."""
    return collect_figures(period)


# -- Taking a statement ------------------------------------------------------------------------


def take_statement(period, *, kind, user=None, note=""):
    """Write down every figure ``period`` prints now. Returns the new :class:`PeriodStatement`.

    Called before a year is marked finalized (the lock lets the rows in while the
    year is still open) or inside ``accounting.locks.override``. One transaction:
    a failure keeps no half a statement.
    """
    if kind not in {key for key, _ in PeriodStatement.KIND_CHOICES}:
        raise ValueError(f"{kind!r} is not a kind of filed figures record.")
    figures = collect_figures(period)
    signed_in = user is not None and getattr(user, "is_authenticated", False)
    with transaction.atomic():
        statement = PeriodStatement.objects.create(
            period=period, kind=kind, taken_by=user if signed_in else None, note=note
        )
        PeriodStatementRow.objects.bulk_create(
            [
                PeriodStatementRow(
                    statement=statement,
                    period=period,
                    scope=f.scope,
                    scope_id=f.scope_id,
                    scope_name=f.scope_name,
                    month=f.month,
                    figure=f.figure,
                    value=f.value,
                    method=f.method,
                    detail=f.detail,
                )
                for f in figures
            ],
            batch_size=500,
        )
    return statement


def statement_figures(statement):
    """The figures a statement holds, as :class:`Figure` in the order they were written."""
    return [
        Figure(
            scope=row.scope,
            scope_id=row.scope_id,
            scope_name=row.scope_name,
            month=row.month,
            figure=row.figure,
            value=row.value,
            method=row.method,
            detail=row.detail,
        )
        for row in statement.rows.order_by("pk")
    ]


def period_statements(period):
    """The year's statements, oldest first."""
    return list(
        PeriodStatement.objects.filter(period=period)
        .select_related("taken_by")
        .order_by("taken_at", "pk")
    )


def newest_statement(period):
    return (
        PeriodStatement.objects.filter(period=period)
        .select_related("taken_by")
        .order_by("-taken_at", "-pk")
        .first()
    )


def upgrade_note(period):
    """The words stored with a statement recorded for a year finalized before this feature."""
    if period.finalized_at:
        when = _day(period.finalized_at)
        return f"{UPGRADE_HEAD}; the year was finalized {when}."
    return f"{UPGRADE_HEAD}. The date this year was finalized is not on record."


def record_upgrade_statements():
    """Record a ``recorded_at_upgrade`` statement for each finalized year with none. Returns them.

    Runs inside ``accounting.locks.override``: the year is already finalized, so
    its lock would refuse the rows. Does nothing on an empty database. Called by
    the ``record_filed_figures`` command (the demonstration's last step, and an
    upgraded site's one-time step); a migration does not call it, because a
    migration never imports live code.
    """
    from accounting.locks import override
    from accounting.models import ReportingPeriod

    taken = []
    with override(UPGRADE_REASON):
        for pk in ReportingPeriod.objects.filter(is_finalized=True).order_by("start_date").values_list("pk", flat=True):
            # The period row is held while its figures are written, so two starts
            # at once (the container's boot and a person's command) write one record.
            with transaction.atomic():
                period = ReportingPeriod.objects.select_for_update().get(pk=pk)
                if not period.is_finalized or PeriodStatement.objects.filter(period=period).exists():
                    continue
                taken.append(
                    take_statement(period, kind="recorded_at_upgrade", note=upgrade_note(period))
                )
    return taken


# -- Words ------------------------------------------------------------------------------------


def _pacific():
    """The site's own time zone (settings.TIME_ZONE), the day the lock reads too."""
    return timezone.get_default_timezone()


def _day(moment):
    """``Oct 15, 2025``, the day in Pacific time as the pages print it."""
    local = timezone.localtime(moment, _pacific()) if timezone.is_aware(moment) else moment
    return f"{local:%b} {local.day}, {local.year}"


def _who(user):
    from core.templatetags.record_marks import _who

    return _who(user)


def first_line(period, statements=None):
    """The card's first line: when the year was filed, by whom, and any restatement.

    ``""`` when the year has no statement.
    """
    statements = period_statements(period) if statements is None else statements
    if not statements:
        return ""
    first = statements[0]
    when = _day(first.taken_at)
    if first.kind == "recorded_at_upgrade":
        note = (first.note or "").strip()
        if note.startswith(UPGRADE_HEAD):
            text = f"Recorded {when}, when{note[len('Recorded when'):]}"
        else:
            text = f"Recorded {when}. {note}".strip()
    elif first.kind == "restated":
        text = f"Restated {when} by {_who(first.taken_by)}." if first.taken_by else f"Restated {when}."
    elif first.taken_by:
        text = f"Filed {when} by {_who(first.taken_by)}."
    else:
        text = f"Filed {when}."
    if len(statements) > 1:
        newest = statements[-1]
        again = _day(newest.taken_at)
        if newest.taken_by:
            text += f" Restated {again} by {_who(newest.taken_by)}."
        else:
            text += f" Restated {again}."
    return text


# -- Corrections since the figures were filed --------------------------------------------------


@dataclass
class CorrectionLine:
    """One correction or void: ``<a>label</a>`` then ``rest``, and the use areas it touches."""

    label: str
    url: str
    rest: str
    at: dt.datetime
    use_areas: frozenset = field(default_factory=frozenset)
    #: The words the fingerprint's answer uses: the kind (``ledger entry``), the record's
    #: own date, and what was done (``corrected Nov 3, 2026 by J. Lopez``).
    kind_label: str = ""
    day: dt.date | None = None
    said: str = ""

    @property
    def identity(self):
        return (self.label, self.url, self.rest)


def _sentence_end(reason):
    reason = (reason or "").strip()
    if reason and reason[-1] not in ".!?":
        reason += "."
    return reason


def _in_period(day, period):
    return day is None or period.start_date <= day <= period.end_date


def corrections_since(period, since, all_records=False):
    """The corrections and voids made after ``since`` that reach a figure of ``period``.

    Found through the registry (``core.corrections.KINDS``): the rows of each
    enabled kind marked replaced or voided after ``since`` whose own date falls
    in the year (a row with no date counts), and that touch at least one use
    area. Newest last. ``all_records=True`` also keeps the ones that touch no
    use area (a water level, a lab result), which the fingerprint's answer lists
    and the moved-figures card does not.
    """
    from core import corrections
    from core.templatetags.record_marks import _author

    pacific = _pacific()
    found = []
    for kind in corrections.KINDS.values():
        if not kind.enabled():
            continue
        model = kind.model_class()
        label = kind["label"][:1].upper() + kind["label"][1:]
        candidates = model.objects.filter(Q(replaced_at__gt=since) | Q(voided_at__gt=since))
        for row in candidates:
            corrected = row.replaced_at is not None and row.replaced_at > since
            replacement = model.objects.filter(replaces=row).first() if corrected else None
            use_areas = frozenset(kind["use_areas"](row))
            if replacement is not None:
                use_areas |= frozenset(kind["use_areas"](replacement))
            if not use_areas and not all_records:
                continue
            in_year = _in_period(kind["date_of"](row), period) or (
                replacement is not None and _in_period(kind["date_of"](replacement), period)
            )
            if not in_year:
                continue
            url = kind["page_url"](row)
            if corrected:
                local = timezone.localtime(row.replaced_at, pacific)
                who = _who(_author(replacement)) if replacement is not None else "a former user"
                reason = _sentence_end(replacement.change_reason if replacement else "")
                rest = f" corrected {local:%b} {local.day}, {local.year} by {who}: {reason}"
                said = f"corrected {local:%b} {local.day}, {local.year} by {who}"
                found.append(
                    CorrectionLine(
                        label, url, rest.rstrip(": "), row.replaced_at, use_areas,
                        kind["label"], kind["date_of"](row), said,
                    )
                )
            if row.voided_at is not None and row.voided_at > since:
                local = timezone.localtime(row.voided_at, pacific)
                reason = _sentence_end(row.void_reason)
                rest = f" voided {local:%b} {local.day}, {local.year} by {_who(row.voided_by)}: {reason}"
                said = f"voided {local:%b} {local.day}, {local.year} by {_who(row.voided_by)}"
                found.append(
                    CorrectionLine(
                        label, url, rest.rstrip(": "), row.voided_at, use_areas,
                        kind["label"], kind["date_of"](row), said,
                    )
                )
    found.sort(key=lambda c: (c.at, c.identity))
    return found


def recalculated_words(period, since):
    """``Changed. OpenH2O last recalculated on Nov 3, 2026.`` or the sentence for no recalculation on record."""
    newest = (
        CalculationRequest.objects.filter(
            reporting_period=period,
            finished_at__gt=since,
            status__in=["succeeded", "finished_with_notes"],
        )
        .order_by("-finished_at")
        .first()
    )
    if newest is None:
        return "Changed since the figures were filed."
    return f"Changed. OpenH2O last recalculated on {_day(newest.finished_at)}."


# -- Moved figures ------------------------------------------------------------------------------


@dataclass
class MovedRow:
    label: str
    filed: Decimal | None
    restated: Decimal | None
    now: Decimal | None


@dataclass
class MovedGroup:
    scope: str
    scope_id: int | None
    heading: str  # "Account", "Use area", "Zone" or "" for the district
    number: str  # the linked word: an account number, a use area number, a zone name, "The district"
    rest: str  # words after the link (an account's name)
    url: str  # "" when the place no longer exists
    rows: list = field(default_factory=list)
    corrections: list = field(default_factory=list)
    moved_words: str = ""


@dataclass
class Comparison:
    """The newest statement against the figures now, ready to print."""

    restated: bool  # three columns: As filed, Restated, Now
    groups: list
    figure_count: int
    correction_count: int
    corrections: list  # the distinct corrections the groups name, oldest first

    @property
    def moved(self):
        return self.figure_count > 0

    @property
    def summary(self):
        """The sentence after the first line."""
        if not self.moved:
            return "No figure has changed since."
        figures = f"{self.figure_count} figure{'' if self.figure_count == 1 else 's'}"
        # A restated year's table also lists figures that differ only between As filed and
        # Restated, so "since" reaches back to the first filing.
        since = "Since the first filing," if self.restated else "Since then"
        return f"{since} {figures} changed (acre-feet)."

    @property
    def single_correction(self):
        """The one correction named once above the table, or None."""
        return self.corrections[0] if len(self.corrections) == 1 else None


def _label_of(f):
    if f.figure == "credit":
        words = f.detail or FIGURE_LABELS["credit"]
    else:
        words = FIGURE_LABELS[f.figure]
    if f.month is not None:
        words += f", {f.month:%b %Y}"
    return words


def _sort_key(f):
    return (f.month is None, f.month or dt.date.min, _ORDER[f.figure], f.detail)


def _index(figures):
    """``{key: (value, figure)}`` with equal keys added (two credits of one description)."""
    found = {}
    for f in figures:
        if f.key in found and f.value is not None:
            total, first = found[f.key]
            found[f.key] = ((total or Decimal("0")) + f.value, first)
        elif f.key not in found:
            found[f.key] = (f.value, f)
    return found


def _differs(a, b):
    return _q2(a) != _q2(b)


def _place_url(scope, scope_id, period, exists):
    if scope == "site":
        return f"{reverse('accounting:dashboard')}?period={period.pk}"
    if not exists:
        return ""
    names = {
        "account": "accounting:account_detail",
        "use_area": "parcels:detail",
        "zone": "geography:zone_detail",
    }
    return f"{reverse(names[scope], args=[scope_id])}?period={period.pk}"


def _existing(scope_ids):
    """``{scope: set of ids}`` that still exist, one query per kind of place."""
    from geography.models import Zone
    from parcels.models import Parcel

    return {
        "account": set(
            WaterAccount.objects.filter(pk__in=scope_ids["account"]).values_list("pk", flat=True)
        ),
        "use_area": set(
            Parcel.objects.filter(pk__in=scope_ids["use_area"]).values_list("pk", flat=True)
        ),
        "zone": set(Zone.objects.filter(pk__in=scope_ids["zone"]).values_list("pk", flat=True)),
    }


def _place_parcels(group, period):
    """The use areas a group's place holds now (the district holds every one)."""
    from geography.models import Zone

    if group.scope == "use_area":
        return {group.scope_id}
    if group.scope == "account":
        account = WaterAccount.objects.filter(pk=group.scope_id).first()
        return set(account_parcel_ids(account, period)) if account else set()
    if group.scope == "zone":
        zone = Zone.objects.filter(pk=group.scope_id).first()
        return set(zone_parcel_ids(zone, period)) if zone else set()
    return None  # the district: any correction


def moved_figures(period, *, now=None):
    """Compare the year's newest statement with the figures now. None when the year has no statement.

    A figure is listed when its value differs at two places (half up). A year
    restated since it was filed lists a figure when any two of As filed,
    Restated and Now differ. Groups run in the drawing's order: each account
    with a moved figure and then its moved use areas, the use areas in no
    account, the zones by name, the district. Each group names the corrections
    made since the year was first filed that touch its use areas; a group no
    correction reaches says when OpenH2O recalculated it.
    """
    statements = period_statements(period)
    if not statements:
        return None
    first, newest = statements[0], statements[-1]
    restated = len(statements) > 1
    filed = _index(statement_figures(first))
    latest = _index(statement_figures(newest)) if restated else filed
    current_figures = figures_now(period) if now is None else now
    current = _index(current_figures)

    moved = {}
    for key in {*filed, *latest, *current}:
        a = filed.get(key, (None, None))[0]
        b = latest.get(key, (None, None))[0]
        c = current.get(key, (None, None))[0]
        pairs = [(a, b), (a, c), (b, c)] if restated else [(a, c)]
        if any(_differs(x, y) for x, y in pairs):
            sample = (current.get(key) or latest.get(key) or filed.get(key))[1]
            moved.setdefault((sample.scope, sample.scope_id), []).append((sample, a, b, c))

    # The names a place was printed under: the statement's, else today's.
    names = {}
    for source in (latest, filed, current):
        for _, f in source.values():
            names.setdefault((f.scope, f.scope_id), f.scope_name)

    scope_ids = {"account": set(), "use_area": set(), "zone": set()}
    for scope, scope_id in moved:
        if scope in scope_ids:
            scope_ids[scope].add(scope_id)
    still = _existing(scope_ids)

    groups = {}
    for (scope, scope_id), items in moved.items():
        items.sort(key=lambda item: _sort_key(item[0]))
        name = names.get((scope, scope_id), "")
        number, _, rest = name.partition(ACCOUNT_JOIN) if scope == "account" else (name, "", "")
        heading = {"account": "Account", "use_area": "Use area", "zone": "Zone"}.get(scope, "")
        if scope == "site":
            # The Dashboard's totals are the active accounts rolled up; a site may be a
            # district, a farm or a ditch company, so the label names what the figure is.
            number = "All active accounts"
        group = MovedGroup(
            scope=scope,
            scope_id=scope_id,
            heading=heading,
            number=number,
            rest=rest,
            url=_place_url(scope, scope_id, period, scope_id in still.get(scope, ())),
            rows=[
                MovedRow(_label_of(sample), a, b if restated else None, c)
                for sample, a, b, c in items
            ],
        )
        groups[(scope, scope_id)] = group

    found = corrections_since(period, first.taken_at)
    placed = {}
    for key, group in groups.items():
        parcels = _place_parcels(group, period)
        if parcels is None:
            group.corrections = list(found)
        else:
            group.corrections = [c for c in found if parcels & c.use_areas]
        placed[key] = parcels
        if not group.corrections:
            group.moved_words = recalculated_words(period, first.taken_at)

    # Order: each account by number with its moved use areas, the use areas in
    # no account, the zones by name, the district.
    accounts = sorted(
        (g for g in groups.values() if g.scope == "account"), key=lambda g: g.number
    )
    use_areas = {g.scope_id: g for g in groups.values() if g.scope == "use_area"}
    ordered = []
    for account in accounts:
        ordered.append(account)
        mine = placed[("account", account.scope_id)] or set()
        for scope_id in sorted(use_areas, key=lambda i: use_areas[i].number):
            if scope_id in mine:
                ordered.append(use_areas.pop(scope_id))
    ordered += sorted(use_areas.values(), key=lambda g: g.number)
    ordered += sorted((g for g in groups.values() if g.scope == "zone"), key=lambda g: g.number)
    ordered += [g for g in groups.values() if g.scope == "site"]

    distinct = {}
    for group in ordered:
        for correction in group.corrections:
            distinct.setdefault(correction.identity, correction)
    corrections_named = sorted(distinct.values(), key=lambda c: (c.at, c.identity))
    return Comparison(
        restated=restated,
        groups=ordered,
        figure_count=sum(len(g.rows) for g in ordered),
        correction_count=len(corrections_named),
        corrections=corrections_named,
    )


# -- The cache the water year page reads -----------------------------------------------------


#: Models whose rows a figure reads, beyond every model a correction can touch.
_FIGURE_MODELS = (
    "parcels.ParcelLedger",
    "accounting.CalculationRun",
    "parcels.Parcel",
    "geography.ParcelZone",
    "geography.Zone",
    "accounting.WaterAccount",
    "accounting.WaterAccountParcel",
    "accounting.AllocationPlan",
    "accounting.AccountCredit",
    "accounting.AllocationCarryover",
    "accounting.ReportingPeriod",
    "wells.WellIrrigatedParcel",
    "wells.WellMeter",
    "surface.PointOfDiversionParcel",
    "core.SiteConfig",
)


def change_token(period):
    """A short text that changes whenever a record a figure or a correction reads changes.

    The newest change-history row of every model :data:`_FIGURE_MODELS` and the
    correction registry name (the Event tables are append-only, so their newest
    key only grows), plus the newest calculation request and statement. The
    cache key carries it, so a change makes the next read compute again.
    """
    from core import corrections

    labels = list(_FIGURE_MODELS)
    for kind in corrections.KINDS.values():
        if kind.enabled():
            labels.append(kind["model"])
    parts = []
    for label in sorted(set(labels)):
        try:
            event = apps.get_model(f"{label}Event")
        except LookupError:
            continue  # not tracked, or its module is not installed
        parts.append(f"{label}={event.objects.aggregate(top=Max('pgh_id'))['top'] or 0}")
    parts.append(f"requests={CalculationRequest.objects.aggregate(top=Max('pk'))['top'] or 0}")
    parts.append(f"statements={PeriodStatement.objects.aggregate(top=Max('pk'))['top'] or 0}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


#: How long a comparison is kept. The change token ends it sooner whenever a record changes.
CACHE_SECONDS = 7 * 24 * 60 * 60


def cached_comparison(period):
    """:func:`moved_figures`, kept in the default cache under the statement and the change token.

    The computation reads every figure the pages print (seconds on a full
    district), so the page asks for it after it has loaded and a second reader
    gets it at once. None when the year has no statement.
    """
    newest = newest_statement(period)
    if newest is None:
        return None
    oldest_pk = (
        PeriodStatement.objects.filter(period=period).order_by("taken_at", "pk").values_list("pk", flat=True).first()
    )
    key = f"filed-figures:{period.pk}:{oldest_pk}:{newest.pk}:{change_token(period)}"
    found = cache.get(key)
    if found is None:
        found = moved_figures(period)
        cache.set(key, found, CACHE_SECONDS)
    return found


# -- The card and the two lines ---------------------------------------------------------------


def card_context(period, comparison=None):
    """What the water year page's Figures as filed card needs, or None when the year has no statement."""
    statements = period_statements(period)
    if not statements:
        return None
    return {
        "first_line": first_line(period, statements),
        "figures_url": reverse("accounting:period_figures", args=[period.pk]),
        "comparison": comparison,
    }


def filed_line_context(period, scope, scope_id, current):
    """The one line under an account's or a use area's balance, or None when nothing moved.

    ``current`` maps ``supplies``, ``uses`` and ``balance`` to the figures the page
    printed. Compares them with the newest statement's rows for the place and
    names only the ones that differ at two places, in that order. Reads the
    stored rows only: nothing is computed again.
    """
    if period is None:
        return None
    newest = newest_statement(period)
    if newest is None:
        return None
    stored = {
        row.figure: row.value
        for row in newest.rows.filter(
            scope=scope, scope_id=scope_id, month__isnull=True,
            figure__in=("supplies", "uses", "balance"),
        )
    }
    parts = [
        (name, shown(stored[name]))
        for name in ("supplies", "uses", "balance")
        if name in stored and _differs(stored[name], _q4(current[name]))
    ]
    if not parts:
        return None
    return {
        "period": period,
        "restated": newest.kind == "restated",
        "parts": parts,
        "anchor_url": f"{reverse('accounting:period_detail', args=[period.pk])}#figures-as-filed",
    }
