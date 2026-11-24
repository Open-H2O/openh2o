# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Drive the OpenET route over use areas: the live crop ET and rain sync.

This is the single live entry point for all three routes, chosen by `OPENET_MODE`:

* "fields" (the default): OpenET's field list. A use area is set up once (a lookup of
  the fields in its rectangle, the fields' outlines, the acres of each field inside the
  use area), then each run asks for the fields' monthly crop ET and rain and records
  each month. A setup the monthly allowance stops picks up where it stopped.
* "api": one request per use area. * "gee": the batched Earth Engine adapter.

Populates the route's own tables and records each month's crop ET the first time it
arrives (`datasync/crop_et.py`). The calculation and the reports read that record.

Usage:
  python manage.py sync_openet_parcels
  python manage.py sync_openet_parcels --start-date 2024-06-01 --end-date 2024-08-31
  python manage.py sync_openet_parcels --parcel-prefix KAW- --limit 5 --dry-run
"""

import logging
from datetime import date, datetime, timedelta

from django.conf import settings
from django.contrib.gis.geos import MultiPolygon
from django.core.management.base import BaseCommand, CommandError

from datasync import crop_et, field_list
from datasync.adapters import get_openet_adapter
from parcels.models import Parcel

logger = logging.getLogger(__name__)

STOPPED_WORDS = (
    "This month's OpenET allowance is used. The next run continues from where this one stopped."
)
WHOLE_AREA_STOPPED_WORDS = (
    "This month's OpenET allowance is used. Run sync_openet_parcels --whole-area again to continue "
    "the whole area; a run without --whole-area continues only the use areas."
)


class Command(BaseCommand):
    help = (
        "Sync OpenET crop ET into use areas, via the route selected by OPENET_MODE "
        "(fields=OpenET's field list, the default; api=one request per use area; "
        "gee=batched Earth Engine)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            default=None,
            help="YYYY-MM-DD. Required for api and gee. For fields: the first day of the "
            "earliest water year not finalized (else this water year).",
        )
        parser.add_argument(
            "--end-date",
            default=None,
            help="YYYY-MM-DD. Required for api and gee. For fields: the last day of last month.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Cap the number of use areas (cheap test runs).",
        )
        parser.add_argument(
            "--parcel-prefix",
            default=None,
            help="Only use areas whose number starts with this (e.g. KAW-).",
        )
        parser.add_argument(
            "--whole-area",
            action="store_true",
            default=False,
            help="Fields route only: also ask for every OpenET field inside the site's boundary, "
            "not only those overlapping a use area (the Map page's crop ET layer). The monthly "
            "scheduled job does not pass it.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Report what WOULD be asked of OpenET (no paid requests, no writes).",
        )

    def handle(self, *args, **options):
        mode = getattr(settings, "OPENET_MODE", "fields")
        fields = mode not in ("api", "gee")
        if not fields and not (options["start_date"] and options["end_date"]):
            raise CommandError("--start-date and --end-date are required unless OPENET_MODE is fields.")
        try:
            start_date = (
                datetime.strptime(options["start_date"], "%Y-%m-%d").date()
                if options["start_date"] else self._default_start()
            )
            end_date = (
                datetime.strptime(options["end_date"], "%Y-%m-%d").date()
                if options["end_date"] else self._default_end()
            )
        except ValueError as exc:
            raise CommandError(f"Invalid date format: {exc}. Use YYYY-MM-DD.") from exc
        if not options["end_date"] and end_date < start_date:
            self.stdout.write("The month in progress is the only month to ask OpenET for, so this run asks for nothing.")
            return
        if end_date < start_date:
            raise CommandError("--end-date must be >= --start-date.")

        # Select use areas. area_acres is required because the calculation and the
        # reports convert mm -> acre-feet over the use area's area.
        qs = Parcel.objects.filter(
            geometry__isnull=False, area_acres__isnull=False
        )
        prefix = options["parcel_prefix"]
        if prefix:
            qs = qs.filter(parcel_number__startswith=prefix)
        qs = qs.order_by("parcel_number")
        if options["limit"]:
            qs = qs[: options["limit"]]
        parcels = list(qs)

        if not parcels:
            raise CommandError(
                "No parcels match the filters (need geometry + area_acres"
                + (f", prefix {prefix!r}" if prefix else "")
                + "). Load parcel data first (e.g. seed_merced)."
            )

        adapter = get_openet_adapter()
        self.stdout.write(
            f"OPENET_MODE={mode} -> {type(adapter).__name__} "
            f"({len(parcels)} parcel(s), {start_date} .. {end_date})"
        )

        if fields:
            self.whole_area = options["whole_area"]
            if options["dry_run"]:
                self._dry_run_fields(parcels, start_date, end_date)
                return
            self._sync_fields(parcels, start_date, end_date)
        else:
            if options["dry_run"]:
                self._dry_run(adapter, parcels, start_date, end_date)
                return
            try:
                summary = adapter.sync_parcel_et(parcels, start_date, end_date)
            except Exception as exc:
                # A batch EE failure (auth/coverage) is systemic — report cleanly
                # rather than dumping a traceback at the operator.
                raise CommandError(f"OpenET sync failed: {exc}") from exc

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("sync_openet_parcels complete"))
            for key, value in summary.items():
                self.stdout.write(f"  {key + ':':<16} {value}")

        # A sync never changes a month's recorded figure; it says which months
        # OpenET now reports differently, for a person to accept on the month's page.
        months = crop_et.months_between(start_date, end_date)
        lines = crop_et.differing_lines(parcels, months)
        if lines:
            self.stdout.write("")
            for line in lines:
                self.stdout.write(self.style.WARNING(line) if line is lines[0] else line)


    # -- the field list route ------------------------------------------------------------------

    @staticmethod
    def _default_start():
        """The first day of the earliest water year not finalized; else this water year's Oct 1."""
        from accounting.models import ReportingPeriod

        period = ReportingPeriod.objects.filter(is_finalized=False).order_by("start_date").first()
        if period is not None:
            return period.start_date
        today = crop_et.today()
        return date(today.year if today.month >= 10 else today.year - 1, 10, 1)

    @staticmethod
    def _default_end():
        """The last day of last month: a month still in progress is never asked for, so a
        part-month figure can never become its recorded crop ET."""
        return crop_et.this_month() - timedelta(days=1)

    @staticmethod
    def _needing_setup(parcels, answered):
        """Use areas with no share rows and none of their own answered lookups holding their
        bounding box (``answered`` holds the use areas' lookups only: a lookup over the boundary
        may have listed their fields, but leaves their outlines to a whole-area run)."""
        return [
            p for p in parcels
            if not field_list.has_shares(p) and not field_list.rectangle_covers(answered, p)
        ]

    @staticmethod
    def _per_request():
        return max(1, int(getattr(settings, "OPENET_FIELDS_PER_REQUEST", 100)))

    def _sync_fields(self, parcels, start_date, end_date):
        """Run the field-list route. Returns True when the monthly allowance stopped it."""
        from datasync.models import OpenETCache, OpenETRequest

        first_request = OpenETRequest.objects.order_by("-pk").values_list("pk", flat=True).first() or 0
        today = crop_et.today()
        stopped = False
        sent_fields, sent_months = set(), set()
        try:
            # The figures of the fields the use areas already share go first, so no lookup or
            # outline (a stopped whole-area run's included) can spend the allowance before them.
            # sent_fields and sent_months fill as each answer is stored, so a run the allowance
            # stops still records the months it received.
            first = self._shared_numbers(parcels)
            self._figures(first, today, start_date, end_date, sent_fields, sent_months)
            self._setup(parcels, today)
            asked = set(first)
            rest = [n for n in self._figure_numbers(parcels, start_date, end_date) if n not in asked]
            self._figures(rest, today, start_date, end_date, sent_fields, sent_months)
        except field_list.AllowanceUsed:
            stopped = True
        except field_list.OpenETRefused as exc:
            raise CommandError(f"OpenET refused a request: {exc}") from exc
        finally:
            if sent_months:
                for parcel in parcels:
                    if field_list.has_shares(parcel):
                        crop_et.record_received_months(parcel, sorted(sent_months))

        sent = OpenETRequest.objects.filter(pk__gt=first_request).count()
        _can, used, limit = OpenETCache.check_budget()
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("sync_openet_parcels complete" if not stopped else "sync_openet_parcels stopped"))
        self.stdout.write(f"  Requests sent this run: {sent}")
        if sent_months:
            self.stdout.write(
                f"  OpenET sent figures for {len(sent_fields)} fields, {len(sent_months)} months "
                f"(received {crop_et._day_words(today)})"
            )
        self.stdout.write(f"  Allowance used: {used} of {limit}")
        if stopped:
            words = WHOLE_AREA_STOPPED_WORDS if getattr(self, "whole_area", False) else STOPPED_WORDS
            self.stdout.write(self.style.WARNING(words))
        return stopped

    def _setup(self, parcels, today):
        """Lookups, outlines and shares, only for what the stored records say is not done."""
        from datasync.models import OpenETField

        answered = field_list.answered_rectangles(whole_area=False)
        needing = self._needing_setup(parcels, answered)
        if needing:
            for rectangle in field_list.lookup_areas(needing):
                if rectangle in answered:
                    continue
                field_list.store_listed(field_list.lookup(rectangle), today, whole_area=False)
                answered.add(rectangle)

        if getattr(self, "whole_area", False):
            boundary = field_list.answered_rectangles(whole_area=True)
            for rectangle, outline in field_list.boundary_lookups(answered=boundary):
                listed = field_list.lookup(rectangle, whole_area=True, outline=outline)
                field_list.store_listed(listed, today, whole_area=True)

        waiting = self._waiting_outlines()
        size = self._per_request()
        for n in range(0, len(waiting), size):
            for number, outline in field_list.outlines(waiting[n:n + size]):
                if outline.geom_type == "Polygon":
                    outline = MultiPolygon(outline, srid=4326)
                OpenETField.objects.filter(field_id=number).update(
                    geometry=outline, area_acres=field_list.outline_acres(outline)
                )
        for parcel in parcels:
            if not field_list.has_shares(parcel) and field_list.rectangle_covers(answered, parcel):
                field_list.compute_shares(parcel)

    def _waiting_outlines(self):
        """The listed fields with no outline and no share whose outlines this run asks for, the use
        areas' first: on a ``--whole-area`` run every one; otherwise only those a use area's lookup
        listed, so a whole-area run the allowance stopped continues its outlines only when it is
        run again with ``--whole-area``."""
        from datasync.models import OpenETField

        waiting = OpenETField.objects.filter(geometry__isnull=True, shares__isnull=True)
        if not getattr(self, "whole_area", False):
            waiting = waiting.filter(whole_area_only=False)
        return list(waiting.order_by("whole_area_only", "field_id").values_list("field_id", flat=True))

    @staticmethod
    def _shared_numbers(parcels):
        """The fields that ``parcels`` already share, in field number order."""
        from datasync.models import OpenETField

        return sorted(set(
            OpenETField.objects.filter(shares__parcel__in=[p.pk for p in parcels])
            .values_list("field_id", flat=True)
        ))

    def _figures(self, numbers, today, start_date, end_date, sent_fields, sent_months):
        """Ask for the monthly figures of ``numbers``, adding to ``sent_fields`` and
        ``sent_months`` as each answer is stored."""
        from datasync.models import OpenETField, OpenETFieldMonth

        ids = dict(OpenETField.objects.filter(field_id__in=numbers).values_list("field_id", "pk"))
        size = self._per_request()
        for n in range(0, len(numbers), size):
            for number, month, et_mm, pr_mm in field_list.figures(numbers[n:n + size], start_date, end_date):
                sent_fields.add(number)
                sent_months.add(crop_et.month_text(month))
                row = OpenETFieldMonth.objects.filter(field_id=ids[number], month=month).first()
                if row is None:
                    OpenETFieldMonth.objects.create(
                        field_id=ids[number], month=month, et_mm=et_mm, pr_mm=pr_mm, received_on=today
                    )
                elif row.et_mm != et_mm or row.pr_mm != pr_mm:
                    # The month's record keeps the first answer (datasync/crop_et.py); the
                    # field month holds the newest, with the day it arrived.
                    row.et_mm, row.pr_mm, row.received_on = et_mm, pr_mm, today
                    row.save()
                elif crop_et.is_provisional(row.received_on, row.month) and not crop_et.is_provisional(
                    today, row.month
                ):
                    # The same figure sent again after the month's 120 days: OpenET has
                    # confirmed it, so the field month takes today and the month's mark
                    # turns Final (crop_et.mark). Written once in a field month's life.
                    row.received_on = today
                    row.save(update_fields=["received_on"])

    def _figure_numbers(self, parcels, start_date, end_date):
        """The fields whose figures a run asks for: those with a share in ``parcels`` (every run,
        so a revised month is seen), and with ``--whole-area`` each field inside the site's
        boundary that overlaps no use area and is missing a month of the range. A whole-area run
        the allowance stops therefore continues on the next run with the fields still missing."""
        from django.db.models import Count, Q

        from datasync import whole_area
        from datasync.models import OpenETField

        numbers = set(
            OpenETField.objects.filter(shares__parcel__in=[p.pk for p in parcels])
            .values_list("field_id", flat=True)
        )
        if getattr(self, "whole_area", False):
            wanted = len(crop_et.months_between(start_date, end_date))
            first = date(start_date.year, start_date.month, 1)
            numbers.update(
                whole_area.fields_in_area().filter(shares__isnull=True)
                .annotate(held=Count("months", filter=Q(months__month__gte=first, months__month__lte=end_date)))
                .filter(held__lt=wanted).values_list("field_id", flat=True)
            )
        return sorted(numbers)

    def _dry_run_fields(self, parcels, start_date, end_date):
        """Print the requests a run would send. Sends no paid request and writes nothing; it reads
        the account's area limit from its status (free), as a run does, so it cuts the same strips."""
        self.stdout.write(self.style.WARNING("[DRY RUN] No requests to OpenET, no writes."))
        answered = field_list.answered_rectangles(whole_area=False)
        needing = self._needing_setup(parcels, answered)
        whole = getattr(self, "whole_area", False)
        limit = field_list.account_max_area_acres() if (needing or whole) else None
        count, open_ended = 0, False
        if needing:
            for rectangle in field_list.lookup_areas(needing, max_acres=limit):
                if rectangle in answered:
                    continue
                west, south, east, north = rectangle
                self.stdout.write(f"  lookup of the fields in {west}, {south}, {east}, {north}")
                count += 1
            open_ended = True
        if whole:
            boundary = field_list.answered_rectangles(whole_area=True)
            for rectangle, outline in field_list.boundary_lookups(max_acres=limit, answered=boundary):
                west, south, east, north = rectangle
                self.stdout.write(
                    f"  lookup of the fields in the boundary's part of {west}, {south}, {east}, {north} "
                    f"({len(outline) // 2} corners)"
                )
                count += 1
                open_ended = True
        size = self._per_request()
        waiting = len(self._waiting_outlines())
        batches = -(-waiting // size)
        if batches:
            self.stdout.write(f"  {batches} request(s) for the outlines of {waiting} fields")
            count += batches
        # The fields waiting on their outlines get figures once outlined (those inside a use area or
        # the boundary): at most one request a batch of them. With lookups still to send the total
        # is already open-ended, so they are shown but not added.
        waiting_figures = -(-waiting // size)
        up_to = False
        if waiting_figures:
            self.stdout.write(
                f"  up to {waiting_figures} request(s) for the figures of the {waiting} fields waiting on "
                f"their outlines, once they are outlined"
            )
            if not open_ended:
                count += waiting_figures
                up_to = True
        # A run sends figures in two steps, the use areas' fields and then the rest, each in its
        # own batches.
        first = set(self._shared_numbers(parcels))
        numbers = self._figure_numbers(parcels, start_date, end_date)
        with_shares = len(numbers)
        rest = len([n for n in numbers if n not in first])
        batches = -(-len(first) // size) + -(-rest // size)
        if batches:
            self.stdout.write(
                f"  {batches} request(s) for the figures of {with_shares} fields, "
                f"{start_date} .. {end_date}"
            )
            count += batches
        if open_ended:
            self.stdout.write(
                "  Outlines and figures for the fields those lookups name are asked once the lookups are answered."
            )
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                f"[DRY RUN] Would send {'up to ' if up_to else ''}{count}{' or more' if open_ended else ''} "
                "request(s) to OpenET."
            )
        )

    # -- the other routes ----------------------------------------------------------------------

    def _dry_run(self, adapter, parcels, start_date, end_date):
        """Report months-to-ask per use area without initializing Earth Engine."""
        months_needing = getattr(adapter, "_months_to_ask", None)
        if months_needing is None:
            # REST tier has no finalized-skip preview; just show the selection.
            self.stdout.write(
                self.style.WARNING(
                    "[DRY RUN] REST tier has no month-skip preview. Selected parcels:"
                )
            )
            for parcel in parcels:
                self.stdout.write(f"  {parcel.parcel_number}")
            return

        needs = months_needing(parcels, start_date, end_date, date.today())
        self.stdout.write(self.style.WARNING("[DRY RUN] No Earth Engine calls, no writes."))
        total = 0
        for parcel in parcels:
            to_ask = needs.get(parcel.pk, [])
            total += len(to_ask)
            months = ", ".join(to_ask) if to_ask else "(fully cached)"
            self.stdout.write(f"  {parcel.parcel_number:<16} {len(to_ask)} month(s): {months}")
        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                f"[DRY RUN] Would ask for {total} parcel-month(s) across "
                f"{len(parcels)} parcel(s)."
            )
        )
