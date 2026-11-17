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
from datetime import date, datetime

from django.conf import settings
from django.contrib.gis.geos import MultiPolygon
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from datasync import crop_et, field_list
from datasync.adapters import get_openet_adapter
from parcels.models import Parcel

logger = logging.getLogger(__name__)

STOPPED_WORDS = (
    "This month's OpenET allowance is used. The next run continues from where this one stopped."
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
            help="YYYY-MM-DD. Required for api and gee. For fields: today.",
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
            "--dry-run",
            action="store_true",
            default=False,
            help="Report what WOULD be asked of OpenET (no requests, no writes).",
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
                if options["end_date"] else timezone.localdate()
            )
        except ValueError as exc:
            raise CommandError(f"Invalid date format: {exc}. Use YYYY-MM-DD.") from exc
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
        today = timezone.localdate()
        return date(today.year if today.month >= 10 else today.year - 1, 10, 1)

    @staticmethod
    def _needing_setup(parcels, answered):
        """Use areas with no share rows and no answered lookup holding their bounding box."""
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
        today = timezone.localdate()
        stopped = False
        sent_fields, sent_months = set(), set()
        try:
            self._setup(parcels, today)
            sent_fields, sent_months = self._figures(parcels, start_date, end_date, today)
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
            self.stdout.write(self.style.WARNING(STOPPED_WORDS))
        return stopped

    def _setup(self, parcels, today):
        """Lookups, outlines and shares, only for what the stored records say is not done."""
        from datasync.models import OpenETField

        answered = field_list.answered_rectangles()
        needing = self._needing_setup(parcels, answered)
        if needing:
            for rectangle in field_list.lookup_areas(needing):
                if rectangle in answered:
                    continue
                for number in field_list.lookup(rectangle):
                    OpenETField.objects.get_or_create(
                        field_id=number, defaults={"geometry": None, "received_on": today}
                    )
                answered.add(rectangle)

        waiting = list(
            OpenETField.objects.filter(geometry__isnull=True, shares__isnull=True)
            .order_by("field_id").values_list("field_id", flat=True)
        )
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

    def _figures(self, parcels, start_date, end_date, today):
        """Ask for the monthly figures of every field with a share; returns (field numbers, months)."""
        from datasync.models import OpenETField, OpenETFieldMonth

        numbers = list(
            OpenETField.objects.filter(shares__parcel__in=[p.pk for p in parcels]).distinct()
            .order_by("field_id").values_list("field_id", flat=True)
        )
        ids = dict(OpenETField.objects.filter(field_id__in=numbers).values_list("field_id", "pk"))
        sent_fields, sent_months = set(), set()
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
                    row.et_mm, row.pr_mm = et_mm, pr_mm
                    row.save()
        return sent_fields, sent_months

    def _dry_run_fields(self, parcels, start_date, end_date):
        """Print the requests a run would send. Sends nothing, writes nothing."""
        from datasync.models import OpenETField

        self.stdout.write(self.style.WARNING("[DRY RUN] No requests to OpenET, no writes."))
        answered = field_list.answered_rectangles()
        needing = self._needing_setup(parcels, answered)
        count, open_ended = 0, False
        if needing:
            # The account's own limit is read from its status; a dry run sends nothing, so it assumes the default.
            for rectangle in field_list.lookup_areas(needing, max_acres=field_list.DEFAULT_MAX_AREA_ACRES):
                if rectangle in answered:
                    continue
                west, south, east, north = rectangle
                self.stdout.write(f"  lookup of the fields in {west}, {south}, {east}, {north}")
                count += 1
            open_ended = True
        size = self._per_request()
        waiting = OpenETField.objects.filter(geometry__isnull=True, shares__isnull=True).count()
        batches = -(-waiting // size)
        if batches:
            self.stdout.write(f"  {batches} request(s) for the outlines of {waiting} fields")
            count += batches
        with_shares = OpenETField.objects.filter(shares__parcel__in=[p.pk for p in parcels]).distinct().count()
        batches = -(-with_shares // size)
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
            self.style.WARNING(f"[DRY RUN] Would send {count}{' or more' if open_ended else ''} request(s) to OpenET.")
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
