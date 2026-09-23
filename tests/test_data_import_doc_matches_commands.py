# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISS-190: docs/DATA-IMPORT.md and `import_wells` describe the same door.

The document names an exact column list for `import_wells`; this test parses
that sentence back out of the document and compares it, both directions,
against the command's own alias table -- so neither can drift from the other
the way they did before this fix (145-02's walk of shape 4 found the document
naming four columns while the command silently read only two of them).

The ledger `source_type` sign list already has its own doc-vs-model guard
(146-01, `tests/test_ledger_import_sign_report.py`); per the 146-06 plan's own
instruction to extend rather than duplicate, this file does not re-implement
that test -- it only re-asserts the same one-line invariant as a guard that
this task did not disturb it.
"""
import re
from pathlib import Path

from accounting.ledger_words import SOURCE_TYPE_SIGNS
from parcels.models import ParcelLedger
from wells.management.commands import import_wells

DOCS_PATH = Path(__file__).resolve().parent.parent / "docs" / "DATA-IMPORT.md"


def _documented_wells_columns():
    text = DOCS_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"`import_wells` reads exactly these columns[^:]*:\s*(.+?)\.\n",
        text,
        re.DOTALL,
    )
    assert match, (
        "docs/DATA-IMPORT.md does not carry the 'import_wells reads exactly "
        "these columns' sentence this test parses"
    )
    return set(re.findall(r"`([A-Za-z_]+)`", match.group(1)))


def _command_columns():
    return {
        import_wells.DEFAULT_NAME_FIELD,
        import_wells.DEFAULT_LAT_FIELD,
        import_wells.DEFAULT_LON_FIELD,
        import_wells.DEFAULT_REG_ID_FIELD,
        *import_wells.EXTRA_COLUMNS.values(),
    }


def test_documented_wells_columns_match_the_command_alias_table_exactly():
    documented = _documented_wells_columns()
    command = _command_columns()
    assert documented == command, (
        f"document names {documented - command or '(nothing extra)'} that the "
        f"command does not read, and the command reads "
        f"{command - documented or '(nothing extra)'} that the document does "
        "not name"
    )


def test_ledger_source_type_list_still_matches_the_model():
    choice_codes = {code for code, _label in ParcelLedger.SOURCE_TYPE_CHOICES}
    assert set(SOURCE_TYPE_SIGNS) == choice_codes
