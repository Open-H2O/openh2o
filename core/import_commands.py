# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared pieces of the import commands (``import_water_rights`` and
``import_infrastructure``).

Each helper says one thing the same way in both commands. The words a person
reads come from rows 20 to 33 of the approved wording list
(``.planning/phases/152-proven-by-strangers/152-03.1-ROWS.md``).
"""
import os

from django.core.management.base import CommandError


def require_file(path):
    """Raise a CommandError (row 30) unless ``path`` is a file."""
    if not os.path.isfile(path):
        raise CommandError(
            f"OpenH2O cannot find the file {path}. "
            "Copy the file into the container with docker compose cp first."
        )


def column_overrides(values, field_names):
    """Turn the repeated ``--column`` values into ``{field: column}``.

    ``values`` is the list argparse collected (``FIELD=COLUMN`` strings, or
    None); ``field_names`` is every name the import reads. Raises a
    CommandError for a value with no ``=`` (row 31) and for a name not in
    ``field_names`` (row 32).
    """
    names = list(field_names)
    overrides = {}
    for value in values or []:
        field, separator, column = value.partition("=")
        if not separator:
            raise CommandError(
                "Write each --column as OpenH2O's name for a value, "
                "an equals sign and a column name."
            )
        field = field.strip()
        if field not in names:
            raise CommandError(
                f"The import does not read a value named {field}. "
                f"Use one of these names: {', '.join(names)}."
            )
        overrides[field] = column.strip()
    return overrides


def check_columns(overrides, columns):
    """Raise a CommandError (row 33) for an override column the file lacks."""
    for column in overrides.values():
        if column not in columns:
            raise CommandError(
                f"The file does not have a column named {column}. "
                "Check the spelling against the file's first row."
            )


def write_columns(stdout, fields, mapping):
    """Write row 20, then one line per field: its column, or row 21."""
    stdout.write("Columns read:")
    for field in fields:
        stdout.write(f"  {field}: {mapping.get(field) or 'no column'}")


def write_rows(stdout, results):
    """Write ``Row {n}: {sentence}`` (row 22) for each error and warning.

    ``results`` are dicts with ``index`` (0-based position in the file's rows)
    and ``errors`` and / or ``warnings`` lists. ``n`` is ``index + 2``, the row
    number the import screen shows (the header line is row 1).
    """
    for result in results:
        for sentence in list(result.get("errors", [])) + list(result.get("warnings", [])):
            stdout.write(f"Row {result['index'] + 2}: {sentence}")


def count(n, singular, plural):
    """``n`` and its word: ``1 row``, ``2 rows`` (rows 28 and 29)."""
    return f"{n} {singular if n == 1 else plural}"
