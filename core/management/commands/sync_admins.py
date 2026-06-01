# SPDX-License-Identifier: AGPL-3.0-or-later
"""Mark every superuser as an agency admin — the go-live safety net (ISS-021).

Run this on the server BEFORE flipping ACCESS_CONTROL_ENFORCED to True so the
deployer (the superuser created by ensure_superuser) is a full administrator
under the two-tier model and can never be locked out of the gated screens.

It is belt-and-suspenders: is_staff already implies is_administrator (see
User.is_administrator), so the switch alone would not lock out a superuser. But
this makes the data honest — agency_admin actually reflects who the admins are —
and doubles as the tool for granting the first real agency administrator.

Idempotent: re-running after everyone is synced reports 0 further changes.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Set agency_admin=True for every superuser (idempotent go-live safety net)."

    def handle(self, *args, **options):
        User = get_user_model()
        # Only the rows that still need it, so the count reflects real changes
        # and a second run reports 0 (idempotent).
        pending = User.objects.filter(is_superuser=True, agency_admin=False)
        updated = pending.update(agency_admin=True)

        total_admins = User.objects.filter(agency_admin=True).count()
        self.stdout.write(
            self.style.SUCCESS(
                f"sync_admins: marked {updated} superuser(s) as agency admin "
                f"({total_admins} agency admin(s) total)."
            )
        )
