# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Generate a second, drier water year of satellite demand from the committed one.

The demonstration's OpenET cache holds exactly one window — WY 2024-25, frozen
by ``dump_openet_fixture`` so a rebuild spends no OpenET quota. But the seed
creates *two* reporting periods, and the open one (WY 2025-2026) resolves to
nothing on every screen that offers a period selector, because there is no
weather behind it. This command supplies that weather.

**The rebuild is offline, so the dry year is generated rather than fetched.**
It is a fabricated basin by design (``data/demo/identity_policy.json`` records
that ruling), so what this command owes the demonstration is not a citation but
plausibility: numbers that behave the way a dry Central Valley year behaves, on
a basin whose spatial texture is already established.

**Derive, never invent.** Every value here comes from that same parcel's own
committed value for the matching month-of-year, transformed. Twelve invented
basin numbers would flatten two things Phase 131 built and this phase has no
business destroying: the 56%-of-mean spread of rainfall across the 76 parcels,
and the correlation between a parcel's ET and the crop planted on it.

What the transform does, per variable:

``precip`` (GRIDMET, items keyed ``precip``)
    Scaled to ``--precip-factor`` of the committed annual total, and
    redistributed within the year by ``DRY_YEAR_PRECIP_WEIGHTS`` so the year
    reads as *dry* rather than merely *quiet* — a dry Central Valley year loses
    its big midwinter storm months hardest and its shoulder months next, rather
    than losing the same fraction everywhere. The weights set the shape only;
    the per-parcel renormalisation below puts the annual total exactly on
    ``factor x committed`` for every parcel, so the factor means what it says.

``ET`` (Ensemble, items keyed ``et``)
    Growing season (Apr-Sep) is carried through UNCHANGED. Growing-season ET on
    this cropland is irrigation-driven, and a permanent-crop grower irrigates in
    a dry year regardless — that is the whole reason a dry year shows up as a
    groundwater problem rather than as a fallowing problem. Wet-season months
    (Nov-Feb) fall in proportion to their own rainfall reduction, floored at
    ``ET_WINTER_FLOOR`` of the committed value: winter ET here is largely
    bare-soil evaporation, which tracks the rain that wets the soil. October and
    March are transition months and are left unchanged rather than given an
    invented rule of their own.

``et_mad_min`` / ``et_mad_max`` (Ensemble)
    Recomputed as ``new_ET x (committed_bound / committed_ET)`` for the same
    parcel-month, so each parcel-month keeps its own ensemble spread ratio
    rather than being handed a constant band. Where committed ET is zero the
    committed bound is carried through unchanged.

``model_count`` (Ensemble)
    Copied verbatim. It counts how many ET models contributed to the ensemble,
    not weather. A synthetic year has no business inventing a different one.

**Determinism is a requirement, not a preference.** No ``random``, no
``datetime.now()``, no dependence on dict ordering. Arithmetic runs in
``Decimal`` and every emitted value is quantized to ``VALUE_PRECISION`` decimal
places, so re-running this command and re-dumping the fixture produces a
byte-identical file. That property is what makes ``git diff`` an honest answer
to "has the cache moved?" — see ``dump_openet_fixture``, which is deliberately
unstamped for the same reason.

WARNING: every item's ``date`` string is rewritten into the target window.
``accounting/steps.py::_read_cache_mm`` SKIPS (and logs) any item whose date
falls outside its own row's span — F-math-03 / ISS-032 — so a missed rewrite is
a silent zero, not a crash.

Usage:
    python manage.py synthesize_dry_year
    python manage.py synthesize_dry_year --precip-factor 0.65
    python manage.py synthesize_dry_year --dry-run
"""

import datetime as dt
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError

from datasync.models import OpenETCache

DEFAULT_SOURCE_WINDOW = "2024-10-01:2025-09-30"
DEFAULT_TARGET_WINDOW = "2025-10-01:2026-09-30"
DEFAULT_PREFIX = "MER-"

# Brent's ruling at the 133-01 decision checkpoint, 2026-09-05: halve the rain.
# The committed year is 294.9 mm (11.6 in) basin-mean, which reads normal-to-wet
# for the valley floor; 0.50 takes it to 147.5 mm (5.8 in), which reads
# unmistakably dry beside it. Measured consequence, computed by running
# accounting/precip_math.py over the committed basin-mean months: effective
# precipitation falls 174.9 -> 92.2 mm, so every acre gains 0.2714 AF of net
# consumptive use with gross ET essentially unchanged.
DEFAULT_PRECIP_FACTOR = "0.50"

# Relative RETENTION of each month's rain in a dry year, keyed by month-of-year.
# These set the year's SHAPE only — the per-parcel renormalisation below rescales
# whatever these produce onto the exact annual target, so their absolute level
# does not matter and only their ratios do.
#
# The pattern being represented: a dry Central Valley year is dry mostly because
# the big midwinter storm sequences do not arrive. February and March carry the
# committed year's two largest totals (68.7 and 78.9 mm basin-mean) and take the
# deepest cut; the December-January core takes the next; the November and April
# shoulders lose least, because a dry year still gets its first and last rains.
# The dry-summer months (May-Sep) and October carry almost nothing in the
# committed year, so their weight is 1.0 — there is nothing there to take away.
DRY_YEAR_PRECIP_WEIGHTS = {
    10: Decimal("1.00"),  # Oct — transition, ~0 mm committed
    11: Decimal("0.90"),  # Nov — shoulder, first rains still arrive
    12: Decimal("0.80"),  # Dec — winter core
    1: Decimal("0.75"),  # Jan — winter core
    2: Decimal("0.60"),  # Feb — peak storm month, hit hardest
    3: Decimal("0.60"),  # Mar — peak storm month, hit hardest
    4: Decimal("0.90"),  # Apr — shoulder, last rains still arrive
    5: Decimal("1.00"),
    6: Decimal("1.00"),
    7: Decimal("1.00"),
    8: Decimal("1.00"),
    9: Decimal("1.00"),
}

# Months whose ET tracks the rain (bare-soil evaporation), and the floor below
# which their ET may not fall however dry the year gets.
#
# ⚠ THE FLOOR IS A LEGIBILITY CHOICE, NOT A HYDROLOGY CLAIM. Real bare-soil
# evaporation swings a good deal more than 15% between a wet winter and a dry
# one, so a physically-driven floor would sit far lower. It is set high on
# purpose, and the reason was MEASURED on 2026-09-05 rather than argued:
#
#   With the floor at 0.40, halving the rain moved basin net consumptive use by
#   only +3.7% (median parcel +3.6%, none falling), because the winter ET
#   reduction gave back 0.191 of the 0.279 AF/acre that the effective-precip
#   drop had won. Brent chose the 50% multiplier at the 133-01 checkpoint over a
#   65% option he rejected as "a difference a reader has to be told about" —
#   and that rejected option was worth 0.18 AF/acre. A 0.088 AF/acre result is
#   half of what he turned down, so the floor as first written defeated the
#   decision it was supposed to implement.
#
# The floor stays ABOVE zero rather than being removed because holding winter ET
# perfectly flat would make the satellite record byte-identical across a wet year
# and a dry one — a tell that this data is fabricated, in front of an audience
# that reads ET records for a living. A mild response is the honest compromise:
# the two years genuinely differ, and the demand signal survives.
ET_WET_SEASON_MONTHS = (11, 12, 1, 2)
ET_WINTER_FLOOR = Decimal("0.85")

# Every emitted value is quantized to this many decimal places. Millimetres to
# six places is a nanometre — far below anything the ledger can see — and the
# fixed precision is what makes a re-run byte-identical.
VALUE_PRECISION = Decimal("0.000001")

# variable -> (model_name, the key its items store their value under).
# WARNING: only variable="ET" keys its items under "et". A generator that emits
# the wrong key writes a silent zero — accounting/steps.py:36 calls this out.
VARIABLE_KEYS = {
    "ET": ("Ensemble", "et"),
    "precip": ("GRIDMET", "precip"),
    "et_mad_min": ("Ensemble", "et_mad_min"),
    "et_mad_max": ("Ensemble", "et_mad_max"),
    "model_count": ("Ensemble", "model_count"),
}


def _parse_window(text, label):
    """Parse a ``YYYY-MM-DD:YYYY-MM-DD`` window into two dates."""
    try:
        start_text, end_text = text.split(":")
        start = dt.date.fromisoformat(start_text)
        end = dt.date.fromisoformat(end_text)
    except ValueError as exc:
        raise CommandError(
            f"--{label} must look like 2024-10-01:2025-09-30, got {text!r} ({exc})"
        ) from exc
    if end <= start:
        raise CommandError(f"--{label} ends on or before it starts: {text!r}")
    return start, end


def _month_offset(source_start, target_start):
    """Whole months from the source window's first month to the target's."""
    return (target_start.year - source_start.year) * 12 + (
        target_start.month - source_start.month
    )


def _shift_month(date_text, offset):
    """Shift a ``YYYY-MM`` item date by a whole number of months."""
    year, month = int(date_text[:4]), int(date_text[5:7])
    index = year * 12 + (month - 1) + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _dec(value):
    """Coerce a JSON number to Decimal without binary-float noise."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _emit(value):
    """Quantize to the fixed precision and hand back a JSON-serialisable float."""
    return float(_dec(value).quantize(VALUE_PRECISION))


def dry_year_precip(committed_by_month, factor):
    """Redistribute and scale one parcel's twelve monthly rainfall values.

    Args:
        committed_by_month: {"YYYY-MM": Decimal mm} for the source window.
        factor: Decimal multiplier for the annual total.

    Returns:
        {"YYYY-MM": Decimal mm} whose total is exactly ``factor x committed``
        (to the arithmetic's own precision) and whose shape is the committed
        shape bent by DRY_YEAR_PRECIP_WEIGHTS.

    A parcel with no rain at all in the committed year gets none in the dry one,
    rather than a division by zero.
    """
    committed_total = sum(committed_by_month.values(), Decimal("0"))
    if committed_total <= 0:
        return {month: Decimal("0") for month in committed_by_month}

    weighted = {
        month: value * DRY_YEAR_PRECIP_WEIGHTS[int(month[5:7])]
        for month, value in committed_by_month.items()
    }
    weighted_total = sum(weighted.values(), Decimal("0"))
    if weighted_total <= 0:
        return {month: Decimal("0") for month in committed_by_month}

    # One rescale onto the exact annual target. The weights above changed the
    # shape; this puts the level where --precip-factor says it goes, per parcel,
    # so the factor is a promise about the annual total and not an approximation.
    scale = (committed_total * factor) / weighted_total
    return {month: value * scale for month, value in weighted.items()}


def dry_year_et(committed_et_by_month, committed_precip_by_month, dry_precip_by_month):
    """One parcel's twelve ET values for the dry year.

    Growing season and the two transition months pass through untouched; the
    wet-season months fall with their own rainfall, floored at ET_WINTER_FLOOR.
    A wet-season month with no committed rain has no rainfall signal to follow,
    so its ET is carried through unchanged rather than guessed at.
    """
    out = {}
    for month, committed in committed_et_by_month.items():
        month_of_year = int(month[5:7])
        if month_of_year not in ET_WET_SEASON_MONTHS:
            out[month] = committed
            continue
        committed_rain = committed_precip_by_month.get(month, Decimal("0"))
        if committed_rain <= 0:
            out[month] = committed
            continue
        ratio = dry_precip_by_month.get(month, Decimal("0")) / committed_rain
        ratio = min(ratio, Decimal("1"))
        ratio = max(ratio, ET_WINTER_FLOOR)
        out[month] = committed * ratio
    return out


class Command(BaseCommand):
    help = (
        "Derive a second, drier OpenETCache window from the committed one — "
        "deterministic, offline, and spending no OpenET quota"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-window",
            default=DEFAULT_SOURCE_WINDOW,
            help=f"Window to derive from (default: {DEFAULT_SOURCE_WINDOW})",
        )
        parser.add_argument(
            "--target-window",
            default=DEFAULT_TARGET_WINDOW,
            help=f"Window to write (default: {DEFAULT_TARGET_WINDOW})",
        )
        parser.add_argument(
            "--precip-factor",
            default=DEFAULT_PRECIP_FACTOR,
            help=(
                "Fraction of the committed year's rainfall the dry year keeps "
                f"(default: {DEFAULT_PRECIP_FACTOR})"
            ),
        )
        parser.add_argument(
            "--prefix",
            default=DEFAULT_PREFIX,
            help=f"Only derive rows for parcels with this prefix (default: {DEFAULT_PREFIX})",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be written without writing anything",
        )

    def handle(self, *args, **options):
        source_start, source_end = _parse_window(
            options["source_window"], "source-window"
        )
        target_start, target_end = _parse_window(
            options["target_window"], "target-window"
        )
        if source_start <= target_start <= source_end:
            raise CommandError(
                f"The target window ({target_start}..{target_end}) starts inside "
                f"the source window ({source_start}..{source_end}). Overlapping "
                "cache spans are what health/checks.py::check_cache_duplication "
                "exists to catch — pick an adjacent window."
            )
        try:
            factor = Decimal(str(options["precip_factor"]))
        except Exception as exc:  # noqa: BLE001 — surface any malformed number
            raise CommandError(
                f"--precip-factor must be a number, got {options['precip_factor']!r}"
            ) from exc
        if factor <= 0:
            raise CommandError(f"--precip-factor must be positive, got {factor}")

        prefix = options["prefix"]
        offset = _month_offset(source_start, target_start)

        source_rows = (
            OpenETCache.objects.filter(
                parcel__parcel_number__startswith=prefix,
                start_date=source_start,
                end_date=source_end,
            )
            .exclude(model_name=OpenETCache.PENDING_MARKER)
            .exclude(parcel__isnull=True)
            .select_related("parcel")
            # Deterministic iteration order — never dict or database default.
            .order_by("parcel__parcel_number", "variable", "model_name")
        )

        # Group by parcel so ET can see its own parcel's rainfall and the spread
        # bounds can see their own parcel's ET. Keyed by parcel_number, which is
        # stable across deployments in the way a primary key is not.
        by_parcel = {}
        for row in source_rows:
            by_parcel.setdefault(row.parcel.parcel_number, {})[row.variable] = row

        if not by_parcel:
            raise CommandError(
                f"No cache rows found for prefix {prefix!r} in window "
                f"{source_start}..{source_end}. Load the committed fixture first:\n"
                "    python manage.py load_openet_fixture"
            )

        written = 0
        created_count = 0
        per_variable = {}
        annual_checks = []

        for parcel_number in sorted(by_parcel):
            rows = by_parcel[parcel_number]
            missing = sorted(set(VARIABLE_KEYS) - set(rows))
            if missing:
                raise CommandError(
                    f"Parcel {parcel_number} is missing cache variable(s) "
                    f"{', '.join(missing)} in the source window. Nothing further "
                    "was written; reload the fixture before deriving from it."
                )

            committed = {
                variable: self._items_by_month(rows[variable], VARIABLE_KEYS[variable][1])
                for variable in VARIABLE_KEYS
            }

            dry_precip = dry_year_precip(committed["precip"], factor)
            dry_et = dry_year_et(committed["ET"], committed["precip"], dry_precip)

            committed_annual = sum(committed["precip"].values(), Decimal("0"))
            annual_checks.append(
                (
                    parcel_number,
                    committed_annual * factor,
                    sum(dry_precip.values(), Decimal("0")),
                )
            )

            derived = {
                "precip": dry_precip,
                "ET": dry_et,
                "model_count": committed["model_count"],
                "et_mad_min": self._rescale_bound(
                    committed["et_mad_min"], committed["ET"], dry_et
                ),
                "et_mad_max": self._rescale_bound(
                    committed["et_mad_max"], committed["ET"], dry_et
                ),
            }

            for variable in sorted(VARIABLE_KEYS):
                model_name, key = VARIABLE_KEYS[variable]
                source_row = rows[variable]
                et_data = self._rebuild_items(
                    source_row.et_data, key, derived[variable], offset
                )
                self._assert_items_in_span(
                    parcel_number, variable, et_data, target_start, target_end
                )
                written += 1
                per_variable[variable] = per_variable.get(variable, 0) + 1
                if options["dry_run"]:
                    continue
                _, created = OpenETCache.objects.update_or_create(
                    parcel=source_row.parcel,
                    start_date=target_start,
                    end_date=target_end,
                    variable=variable,
                    model_name=model_name,
                    defaults={
                        "geometry": source_row.parcel.geometry,
                        "et_data": et_data,
                        # Derived offline from rows already paid for. This costs
                        # no OpenET request and must not count against the
                        # monthly allowance (ISS-128).
                        "origin": "fixture",
                    },
                )
                if created:
                    created_count += 1

        worst = max(
            (abs(target - actual), number)
            for number, target, actual in annual_checks
        )
        verb = "Would write" if options["dry_run"] else "Wrote"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} {written} rows for {target_start}..{target_end} "
                f"({len(by_parcel)} parcels, {len(per_variable)} variables, "
                f"precip factor {factor})"
            )
        )
        if not options["dry_run"]:
            self.stdout.write(
                f"  {created_count} created, {written - created_count} updated"
            )
        for variable in sorted(per_variable):
            self.stdout.write(f"  {variable}: {per_variable[variable]}")
        self.stdout.write(
            f"  worst per-parcel annual precip error: {float(worst[0]):.6f} mm "
            f"({worst[1]})"
        )

    def _items_by_month(self, row, key):
        """{"YYYY-MM": Decimal} for one cache row, keyed by its own value key."""
        out = {}
        for item in row.et_data or []:
            if not isinstance(item, dict):
                continue
            date_text = str(item.get("date", ""))
            if not date_text or item.get(key) is None:
                continue
            out[date_text[:7]] = _dec(item[key])
        return out

    def _rescale_bound(self, committed_bound, committed_et, dry_et):
        """Keep each parcel-month's own ensemble spread ratio against the new ET."""
        out = {}
        for month, bound in committed_bound.items():
            base = committed_et.get(month, Decimal("0"))
            if base <= 0:
                # No ratio to preserve. Carrying the committed bound through is
                # the honest move — inventing one around a zero ET is not.
                out[month] = bound
                continue
            out[month] = dry_et.get(month, Decimal("0")) * (bound / base)
        return out

    def _rebuild_items(self, source_items, key, derived_by_month, offset):
        """Rewrite one row's items into the target window with derived values.

        Item order follows the source row's order, so the emitted JSON is
        deterministic without depending on dict iteration for its meaning.
        """
        out = []
        for item in source_items or []:
            if not isinstance(item, dict):
                continue
            source_month = str(item.get("date", ""))[:7]
            if not source_month or item.get(key) is None:
                continue
            new_item = dict(item)
            new_item["date"] = _shift_month(source_month, offset)
            new_item[key] = _emit(derived_by_month.get(source_month, Decimal("0")))
            out.append(new_item)
        return out

    def _assert_items_in_span(self, parcel_number, variable, items, start, end):
        """Refuse to write an item _read_cache_mm would silently skip.

        F-math-03 / ISS-032: an item dated outside its own row's span is skipped
        with a log warning, which reads downstream as a zero rather than as an
        error. Catching it here turns a silent wrong number into a loud refusal.
        """
        for item in items:
            month = str(item.get("date", ""))
            first = dt.date(int(month[:4]), int(month[5:7]), 1)
            if first < dt.date(start.year, start.month, 1) or first > end:
                raise CommandError(
                    f"{parcel_number} {variable}: derived item dated {month} "
                    f"falls outside the target window {start}..{end}. "
                    "accounting/steps.py::_read_cache_mm would skip it and the "
                    "parcel would read as zero. Nothing further was written."
                )
