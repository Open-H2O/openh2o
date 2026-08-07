# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Load an operator's own GeoJSON boundary file into a Boundary row (ISS-122).

**The gap this closes.** ``docs/AI-OPERATOR-GUIDE.md`` tells a headless
operator (no browser, SSH only) that the command-line path "reaches the same
end state" as the browser Setup Wizard, and offers ``auto_populate`` for an
agency that has "Only a basin boundary". That was never true:
``geography.management.commands.auto_populate --boundary`` only RESOLVES an
existing ``Boundary`` row by name or pk — it never creates one — and until
this command existed, the Setup Wizard's upload view
(``setup/views.py``) was the ONLY code in the whole platform that could turn
an operator's own GeoJSON file into a ``Boundary``. A headless operator
literally could not load their own boundary.

This command is the missing piece: the headless equivalent of the wizard's
own upload step. It shares its parsing, its validity repair, and its
operator-facing error wording with the wizard via ``setup/boundaries.py``, so
a file behaves identically whichever path loads it. Once it has run, the
obvious next step is the one ``auto_populate`` already does well:

    python manage.py import_boundary --file district.geojson
    python manage.py auto_populate --boundary "District Name"

Idempotent, matched by name — the same shape as
``core/management/commands/seed_merced_base.py``: re-running against the same
file updates the existing ``Boundary`` row in place rather than creating a
duplicate.

Lives in the ``setup`` app, not ``geography``. ``setup`` already declares
``requires=("geography",)`` in ``core/modules.py``, so setup -> geography is a
legal forward dependency; the reverse would be a backwards arrow into an
optional module and would trip the composition rule in
``tests/test_composition_rule.py``.
"""
import json
import os

from django.core.management.base import BaseCommand, CommandError

from geography.models import Boundary
from setup.boundaries import boundary_from_geojson_text


class Command(BaseCommand):
    help = (
        "Load an operator's own GeoJSON boundary file into a Boundary row — "
        "the headless equivalent of the Setup Wizard's upload step. "
        "Idempotent: re-running against the same file updates the boundary "
        "in place rather than duplicating it."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            dest="file_path",
            required=True,
            help="Path to the operator's GeoJSON file.",
        )
        parser.add_argument(
            "--name",
            default=None,
            help=(
                "Name for the Boundary. Defaults to the name inside the "
                "file, or the filename if the file carries none — the same "
                "precedence the Setup Wizard uses."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Parse and report what would be created or updated; write nothing.",
        )

    def handle(self, *args, **options):
        file_path = options["file_path"]
        name_override = options["name"]
        dry_run = options["dry_run"]

        if not os.path.isfile(file_path):
            raise CommandError(f"No such file: {file_path}")

        try:
            with open(file_path, "rb") as fh:
                raw = fh.read()
        except OSError as exc:
            raise CommandError(f"Couldn't read {file_path}: {exc}")

        fallback_name = os.path.splitext(os.path.basename(file_path))[0]

        # Reuse the Setup Wizard's own operator-facing wording for these three
        # failure shapes (setup/views.py) — they were written for a water
        # district engineer, and matching them verbatim is the reason this
        # command shares the wizard's parser instead of writing its own.
        try:
            name, geom, attrs = boundary_from_geojson_text(
                raw, fallback_name=fallback_name
            )
        except UnicodeDecodeError:
            raise CommandError(
                "That file couldn't be read as text. A GeoJSON file is a "
                "plain-text file — make sure you exported GeoJSON, not a "
                "shapefile or a zip archive."
            )
        except json.JSONDecodeError:
            raise CommandError(
                "The file isn't valid JSON. A GeoJSON file is text that "
                "starts with '{' — check you exported GeoJSON (not a "
                "shapefile, KML, or zip)."
            )
        except ValueError as exc:
            # Specific, plain-language reason from parse_geojson_boundary.
            raise CommandError(str(exc))

        if name_override:
            name = name_override

        if dry_run:
            existing = Boundary.objects.filter(name=name).exists()
            verb = "update" if existing else "create"
            self.stdout.write(
                self.style.WARNING(f"DRY RUN: would {verb} boundary '{name}'.")
            )
            self._report(name, geom, attrs)
            return

        boundary, created = Boundary.objects.update_or_create(
            name=name, defaults={"geometry": geom, **attrs},
        )
        verb = "Created" if created else "Updated existing"
        self.stdout.write(self.style.SUCCESS(f"{verb} boundary: {name}"))
        self._report(name, geom, attrs)

        self.stdout.write(
            f"\nNext: python manage.py auto_populate --boundary \"{name}\""
        )

    def _report(self, name, geom, attrs):
        """The parsed boundary's facts, in the style of seed_merced_base.

        Says plainly when the file carried no area rather than printing a
        computed one — this platform never derives an area from the geometry
        (decided 2026-08-05); a file with no area property keeps an empty
        area on purpose, and that has to be visible in the command's own
        output, not just in the database row.
        """
        if "area_sq_miles" in attrs:
            self.stdout.write(f"  Area: {attrs['area_sq_miles']} sq mi (from the file)")
        else:
            self.stdout.write("  Area: not specified in the file")
        if "huc" in attrs:
            self.stdout.write(f"  HUC: {attrs['huc']}")
        if "basin_code" in attrs:
            self.stdout.write(f"  Basin code: {attrs['basin_code']}")
        self.stdout.write(f"  Vertices: {geom.num_coords}")
