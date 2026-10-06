# SPDX-License-Identifier: AGPL-3.0-or-later
"""Calculate whole reporting periods or single months, in order, with a record.

Crop water use, then the canal division, then the groundwater / no-supply
residual, month by month, oldest first, one transaction per month, one run at a
time. The same sequence the period page's button, the nightly schedule and a
saved diversion record use (``accounting/engine_run.py``); every run leaves a
``CalculationRequest`` saying in words what happened.

    python manage.py run_accounting --period "WY 2025-2026"
    python manage.py run_accounting --month 2026-03 --month 2026-04
    python manage.py run_accounting --open-periods --trigger schedule
    python manage.py run_accounting --request 41      # one the screen created

There is NO ``--force`` option on this command, on purpose. A finalized period
is refused, naming the period, and nothing is changed. A technician who really
means to overwrite a filed figure uses ``run_calculations --force`` month by
month, which records the reason in the change history.

Exits non-zero when a request ends ``failed``. Months that have no crop water
use data yet are not a failure: they are reported as a note, and the request
ends ``finished_with_notes``.
"""

from django.core.management.base import BaseCommand, CommandError

from accounting.engine_run import (
    MONTH_RE,
    create_request,
    month_date,
    run_queue,
)
from accounting.models import CalculationRequest, ReportingPeriod


class Command(BaseCommand):
    help = (
        "Calculate reporting periods or months in order (crop water use, canal "
        "division, residual), one month at a time, and record how it went. "
        "Never forces a finalized period."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--period",
            action="append",
            dest="periods",
            default=None,
            metavar="NAME",
            help="Name of a reporting period to calculate. Repeatable.",
        )
        parser.add_argument(
            "--month",
            action="append",
            dest="months",
            default=None,
            metavar="YYYY-MM",
            help="A single month to calculate. Repeatable. Not with --period.",
        )
        parser.add_argument(
            "--open-periods",
            action="store_true",
            help="Calculate every reporting period that is not finalized.",
        )
        parser.add_argument(
            "--request",
            type=int,
            default=None,
            metavar="PK",
            help="Run a request that already exists (the screen creates one "
            "and launches this).",
        )
        parser.add_argument(
            "--trigger",
            default="command",
            choices=[value for value, _label in CalculationRequest.TRIGGER_CHOICES],
            help="What to record as the reason for the run (default: command).",
        )

    def handle(self, *args, **options):
        if options["request"] is not None:
            requests = self._existing(options["request"])
        else:
            requests = self._create(options)

        run_queue()

        failed = []
        for req in requests:
            req.refresh_from_db()
            self._report(req)
            if req.status == "failed":
                failed.append(req)
        if failed:
            raise CommandError(
                "; ".join(f"request {r.pk}: {r.outcome}" for r in failed)
            )

    # -- which requests -----------------------------------------------------

    def _existing(self, pk):
        req = CalculationRequest.objects.filter(pk=pk).first()
        if req is None:
            raise CommandError(f"There is no calculation request {pk}.")
        return [req]

    def _create(self, options):
        names = options["periods"] or []
        months = options["months"] or []
        if months and (names or options["open_periods"]):
            raise CommandError("Give --month, or --period / --open-periods, not both.")
        if not (names or months or options["open_periods"]):
            raise CommandError(
                "Say what to calculate: --period NAME, --month YYYY-MM, "
                "--open-periods or --request PK."
            )

        trigger = options["trigger"]
        periods = []
        for name in names:
            found = list(ReportingPeriod.objects.filter(name=name).order_by("start_date"))
            if not found:
                raise CommandError(f"There is no reporting period named {name!r}.")
            periods.extend(found)
        if options["open_periods"]:
            seen = {p.pk for p in periods}
            periods.extend(
                p
                for p in ReportingPeriod.objects.filter(is_finalized=False).order_by(
                    "start_date"
                )
                if p.pk not in seen
            )

        if months:
            for month in months:
                if not MONTH_RE.match(month):
                    raise CommandError(f"--month must be YYYY-MM, got {month!r}")
            first = month_date(sorted(months)[0])
            period = ReportingPeriod.objects.filter(
                start_date__lte=first, end_date__gte=first
            ).first()
            return [create_request(trigger, reporting_period=period, months=months)]

        return [create_request(trigger, reporting_period=p) for p in periods]

    # -- output ---------------------------------------------------------------

    def _report(self, req):
        label = req.reporting_period.name if req.reporting_period_id else "months"
        line = f"[{req.status}] {label}: {req.outcome or 'Waiting to start.'}"
        if req.status == "failed":
            self.stderr.write(self.style.ERROR(line))
        elif req.status == "finished_with_notes":
            self.stdout.write(self.style.WARNING(line))
        elif req.status == "succeeded":
            self.stdout.write(self.style.SUCCESS(line))
        else:
            self.stdout.write(line)
        for note in req.notes or []:
            self.stdout.write(f"  - {note}")

