# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import sample results from a lab results file, through the Import lab results screen's code.

    python manage.py import_lab_results FILE [--dry-run]

The screen's preview calls ``drinking.importer.preview_counts`` and its worker calls
``drinking.importer.import_lab_rows``; so does this.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from core import import_commands
from drinking import importer

_EXTENSIONS = (".csv", ".tab", ".txt")


def _agency_lines(agency, dry_run):
    """The regulating agency sentences (rows 50 to 55), as the screen prints them."""
    lines = []
    for entry in agency or ():
        system = entry["system"].name
        value = entry["value"]
        existing = entry["existing"]
        if entry["outcome"] == importer.AGENCY_RECORDED:
            verb = "will record" if dry_run else "recorded"
            lines.append(
                f"OpenH2O {verb} {value} as the regulating agency of {system}."
            )
        elif entry["outcome"] == importer.AGENCY_ALREADY_SET:
            if existing == value:
                lines.append(
                    f"{system} already has {existing} on file as its regulating "
                    "agency. This file names the same agency."
                )
            elif dry_run:
                lines.append(
                    f"{system} already has {existing} on file as its regulating "
                    f"agency. OpenH2O will keep {existing} and will not record "
                    f"this file's {value}."
                )
            else:
                lines.append(
                    f"{system} already has {existing} on file as its regulating "
                    f"agency. OpenH2O kept {existing} and did not record this "
                    f"file's {value}."
                )
        else:
            values = entry["values"]
            lines.append(
                f"The rows of this file name {len(values)} different regulating "
                f"agencies for {system}: {', '.join(values[:-1])} and {values[-1]}. "
                "OpenH2O records a regulating agency only when every row names "
                "the same agency."
            )
    return lines


class Command(BaseCommand):
    help = (
        "Import sample results from a .csv, .tab or .txt lab results file. "
        "The Import lab results screen reads the same files."
    )

    def add_arguments(self, parser):
        parser.add_argument("file", help="The path of the file inside the container.")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Report what the import would do. "
                "The command does not save any record during a dry run."
            ),
        )

    def handle(self, *args, **options):
        path = options["file"]
        dry_run = options["dry_run"]
        import_commands.require_file(path)

        basename = os.path.basename(path)
        if not basename.lower().endswith(_EXTENSIONS):
            raise CommandError(
                "The command imports .csv, .tab and .txt files only. "
                "Save the file as CSV and run the command again."
            )

        try:
            with open(path, "rb") as handle:
                parsed = importer.parse_upload(handle, basename)
        except ImportError as exc:
            raise CommandError(str(exc))

        columns = parsed["columns"]
        rows = parsed["rows"]
        mapping = importer.auto_map_columns(columns)

        if dry_run:
            self.stdout.write("[DRY RUN] The command does not save any record.")
        labels = [label for _field, label in importer.import_fields()]
        by_label = {
            importer.FIELD_LABELS[field]: column for field, column in mapping.items()
        }
        import_commands.write_columns(self.stdout, labels, by_label)

        missing = [f for f in importer.REQUIRED_FIELDS if not mapping.get(f)]
        if missing:
            raise CommandError(importer.missing_columns_sentence(missing))

        if dry_run:
            validated = importer.validate_rows(rows, mapping)
            outcome = None
        else:
            outcome = importer.import_lab_rows(
                columns, rows, source_file=basename[:255]
            )
            validated = outcome["validated"]

        import_commands.write_rows(
            self.stdout,
            [item for item in validated if item["errors"] or item["warnings"]],
        )

        unknown = importer.unknown_ps_codes(validated)
        if unknown:
            self.stdout.write("No sampling point on the site has these PS Codes:")
            for ps_code in unknown:
                self.stdout.write(f"  {ps_code}")
            self.stdout.write(
                "Add each sampling point with add_sampling_point. "
                "Then import the file again."
            )

        count = import_commands.count
        if dry_run:
            figures = importer.preview_counts(validated)
            on_file = figures["duplicate_count"]
            repeats = figures["repeat_count"]
            errors = figures["error_count"]
            if figures["new_analytes"]:
                self.stdout.write("New analytes OpenH2O will add:")
                self.stdout.write(", ".join(figures["new_analytes"]))
            agency = importer.regulating_agency_outcomes(rows, mapping, validated)
        else:
            counts = outcome["counts"]
            on_file = counts["duplicates"] - counts["repeats"]
            repeats = counts["repeats"]
            errors = counts["skipped"]
            if counts["analytes"]:
                self.stdout.write(
                    "OpenH2O added "
                    f"{count(counts['analytes'], 'new analyte', 'new analytes')} "
                    "from this file."
                )
            agency = outcome["agency"]

        for line in _agency_lines(agency, dry_run):
            self.stdout.write(line)

        if on_file:
            self.stdout.write(
                f"{on_file} row is already on file."
                if on_file == 1
                else f"{on_file} rows are already on file."
            )
        if repeats:
            self.stdout.write(
                "1 row repeats an earlier row of the file."
                if repeats == 1
                else f"{repeats} rows repeat an earlier row of the file."
            )
        if errors:
            self.stdout.write(
                "1 row has errors." if errors == 1 else f"{errors} rows have errors."
            )

        if dry_run:
            if figures["limits_fill_count"]:
                self.stdout.write(
                    "OpenH2O would add this file's MCL and DLR to "
                    f"{count(figures['limits_fill_count'], 'result', 'results')} "
                    "already on file."
                )
            n = figures["committable"]
            skipped = count(len(rows) - n, "row", "rows")
            self.stdout.write(
                f"OpenH2O would import {n} sample "
                f"{'result' if n == 1 else 'results'} and skip {skipped}."
            )
        else:
            if counts["limits_filled"]:
                self.stdout.write(
                    "OpenH2O added this file's MCL and DLR to "
                    f"{count(counts['limits_filled'], 'result', 'results')} "
                    "already on file."
                )
            self.stdout.write(
                "OpenH2O added "
                f"{count(counts['events'], 'sample event', 'sample events')}."
            )
            n = counts["results"]
            skipped = count(len(rows) - n, "row", "rows")
            self.stdout.write(
                f"OpenH2O imported {n} sample "
                f"{'result' if n == 1 else 'results'} and skipped {skipped}."
            )
