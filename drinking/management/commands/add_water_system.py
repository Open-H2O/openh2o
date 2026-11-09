# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add a water system and its facilities from EPA's Envirofacts record.

    python manage.py add_water_system PWSID [--dry-run]

The Add a water system page calls the same functions in ``drinking.onboarding``.
"""
from django.core.management.base import BaseCommand, CommandError

from drinking import envirofacts, envirofacts_mapping, onboarding


class Command(BaseCommand):
    help = (
        "Add a water system and its facilities from EPA's Envirofacts records by the "
        "system's PWSID. The Add a water system page saves the same records. When the "
        "PWSID is already on the site, the command updates the system and its "
        "facilities from EPA's record."
    )

    def add_arguments(self, parser):
        parser.add_argument("pwsid", help="The water system's PWSID, such as CA1234567.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Show EPA's record and what the command would save. "
                "The command does not save any record during a dry run."
            ),
        )

    def handle(self, *args, **options):
        pwsid = (options["pwsid"] or "").strip().upper()
        dry_run = options["dry_run"]

        kept = onboarding.system_the_site_keeps_instead(pwsid)
        if kept is not None:
            raise CommandError(
                f"This site keeps the records of one water system, {kept.name} "
                f"({kept.pwsid}). OpenH2O did not look up {pwsid} or save anything."
            )

        # Specific first: PwsidNotFound and EnvirofactsUnavailable both subclass
        # EnvirofactsError, so the base class must come last.
        try:
            collected = onboarding.collect_federal_record(pwsid)
        except envirofacts.PwsidNotFound:
            raise CommandError(
                f"EPA's Envirofacts does not list a water system with the PWSID "
                f"{pwsid}. Check the PWSID against the regulator's listing and try again."
            )
        except envirofacts.EnvirofactsUnavailable:
            raise CommandError(
                f"OpenH2O could not get the record for {pwsid} from EPA's Envirofacts "
                "service. Your PWSID may still be correct; try again in a few minutes."
            )
        except envirofacts.EnvirofactsError as exc:
            raise CommandError(
                "EPA's Envirofacts service sent an answer OpenH2O cannot read. Your "
                f"PWSID may still be correct. Details: {exc}"
            )

        review = onboarding.review(collected)
        total = review["epa_facility_count"]
        saved = review["facility_count"]
        write = self.stdout.write

        if dry_run:
            write("[DRY RUN] The command does not save any record.")
        write(f"EPA's record for {pwsid}:")
        for label, value in (
            ("Name", review["name"]),
            ("Status", review["activity_status"]),
            ("System type", review["pws_type"]),
            ("Owner type", review["owner_type"]),
            ("Primary source", review["primary_source"]),
            ("County served", review["geography"].get("county_served", "")),
        ):
            write(f"{label}: {value or ''}")
        for facility in review["facilities"]:
            write(f"Facility {facility['facility_id']}: {facility['name']}")
        for reason in review["skipped"]:
            write(f"Left out: {reason}")
        for note in review["warnings"]:
            write(f"Note: {note}")

        if dry_run:
            verb = (
                f"OpenH2O would update {pwsid} from EPA's record."
                if review["already_onboarded"]
                else f"OpenH2O would create the water system {pwsid}."
            )
            write(
                f"{verb} OpenH2O would save {saved} of the {total} "
                f"{'facility' if total == 1 else 'facilities'} EPA sent."
            )
            return

        result = envirofacts_mapping.commit_system(
            collected["system_row"], collected["facility_rows"]
        )
        name = result.system.name or pwsid
        if result.created:
            write(f"OpenH2O added {name} ({pwsid}).")
        else:
            write(f"OpenH2O updated {name} ({pwsid}) from EPA's record.")
        write(
            f"Of the {total} {'facility' if total == 1 else 'facilities'} EPA sent, "
            f"OpenH2O created {result.facilities_created}, updated "
            f"{result.facilities_updated} and left out {len(result.skipped)}."
        )
        write(
            "Next: add a sampling point with add_sampling_point for each PS Code in "
            "your lab file."
        )
