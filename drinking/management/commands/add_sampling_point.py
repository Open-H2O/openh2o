# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add a sampling point to a facility of a water system.

    python manage.py add_sampling_point --facility ID (--point-number N | --ps-code CODE) [options]

The Sampling points page calls the same ``drinking.onboarding.add_sampling_point``.
"""
from django.core.management.base import BaseCommand, CommandError

from drinking import onboarding
from drinking.models import WaterSystem
from drinking.ps_codes import uses_california_ps_codes


class Command(BaseCommand):
    help = (
        "Add a sampling point to one of the water system's facilities. The command "
        "adds a point the same way as the water system's Sampling points page."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--facility", required=True, help="The facility ID, such as 010 or DST."
        )
        parser.add_argument(
            "--point-number",
            default="",
            help=(
                "For a California water system, the point number or label, such as "
                "010 or LCR. OpenH2O builds the PS Code from the PWSID, the facility "
                "ID and the point number."
            ),
        )
        parser.add_argument(
            "--ps-code",
            default="",
            help=(
                "For a water system outside California, the sampling point code "
                "exactly as it appears in the lab results file."
            ),
        )
        parser.add_argument(
            "--name",
            default="",
            help='The sampling point\'s name, such as "Lead testing tap".',
        )
        parser.add_argument(
            "--type",
            default="",
            choices=["source", "entry_point", "distribution", "tap"],
            help="The point type: source, entry_point, distribution or tap.",
        )
        parser.add_argument(
            "--pwsid",
            default="",
            help=(
                "The water system's PWSID. Give it only when the site has more than "
                "one water system."
            ),
        )

    def handle(self, *args, **options):
        system = self._find_system((options["pwsid"] or "").strip().upper())

        facility = system.facilities.filter(facility_id=options["facility"]).first()
        if facility is None:
            ids = ", ".join(
                system.facilities.order_by("facility_id").values_list(
                    "facility_id", flat=True
                )
            )
            raise CommandError(
                f"{system.name} has no facility with the facility ID "
                f"{options['facility']}. Its facility IDs are {ids}."
            )

        if uses_california_ps_codes(system.pwsid):
            if not options["point_number"].strip():
                raise CommandError("Give --point-number for a California water system.")
        elif not options["ps_code"].strip():
            raise CommandError("Give --ps-code for a water system outside California.")

        try:
            point, created = onboarding.add_sampling_point(
                system,
                facility,
                point_number=options["point_number"],
                ps_code=options["ps_code"],
                name=options["name"],
                point_type=options["type"],
            )
        except ValueError as exc:
            raise CommandError(str(exc))

        if not created:
            self.stdout.write(
                f"Sampling point {point.ps_code} is already on file. "
                "OpenH2O changed nothing."
            )
        elif point.name:
            self.stdout.write(
                f"OpenH2O added {point.name} as sampling point {point.ps_code}."
            )
        else:
            self.stdout.write(f"OpenH2O added sampling point {point.ps_code}.")

    def _find_system(self, pwsid):
        if pwsid:
            system = WaterSystem.objects.filter(pwsid=pwsid).first()
            if system is None:
                raise CommandError(
                    f"No water system in OpenH2O has the PWSID {pwsid}. "
                    "Add the water system first."
                )
            return system
        systems = list(WaterSystem.objects.order_by("pwsid"))
        if not systems:
            raise CommandError(
                "This site has no water system. Add the water system first with "
                "add_water_system."
            )
        if len(systems) > 1:
            raise CommandError(
                f"This site has {len(systems)} water systems. Give the system's "
                "PWSID with --pwsid."
            )
        return systems[0]
