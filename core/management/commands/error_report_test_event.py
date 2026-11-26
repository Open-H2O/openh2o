# SPDX-License-Identifier: AGPL-3.0-or-later
"""Send one test event to the error-report server, from inside the running site.

    docker compose exec web python manage.py error_report_test_event

Runs with the web container's own settings and image, so the event carries that site's
release and environment. Prints the event id, or stops when reporting is off (no
SENTRY_DSN). See core/error_reports.py.
"""

from django.core.management.base import BaseCommand, CommandError

from core import error_reports


class Command(BaseCommand):
    help = "Send one test event to the error-report server and print its event id."

    def handle(self, *args, **options):
        if not error_reports.enabled():
            raise CommandError("error reports are off (no SENTRY_DSN); nothing sent")
        event_id = error_reports.send_test_event()
        self.stdout.write(f"sent test event {event_id} (release {error_reports._release() or 'unknown'})")
