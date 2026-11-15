# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read a district's own list of parcel numbers.

The Setup Wizard's parcel step and ``auto_populate --parcel-list`` read the same
file the same way: a CSV or text file whose column headed APN or Parcel number
holds the numbers, or, when no column has either heading, its first column (a
file with no heading at all loses no number, because its first row is read as a
number too).

Numbers are compared with everything but letters and digits removed and capital
letters ignored, so ``030-031-016-000`` matches ``030031016000``. A shorter county
form is not matched to a longer one. Merced County's assessor prints twelve digits in
four groups (061-700-024-000), and no public source read on 2026-11-15 says a nine-digit
number names the twelve-digit parcel ending ``000``, so such a number is reported as
not found rather than guessed.
"""
import csv
import io
import re

#: Headings (letters only, lower case) that name the column of parcel numbers.
HEADINGS = frozenset({
    "apn", "apns", "apnnumber", "parcelnumber", "parcelno", "parcelnum", "parcel",
    "parcelid", "assessorparcelnumber", "assessorsparcelnumber",
})

#: Files that are a spreadsheet's own format, not text.
NOT_TEXT_EXTENSIONS = (".xlsx", ".xls", ".xlsm", ".ods", ".numbers")
_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0"


class ParcelListError(ValueError):
    """The sentence the page shows when a list cannot be read."""


def normalize(number):
    """A parcel number with only its letters and digits, in capitals."""
    return re.sub(r"[^0-9A-Za-z]", "", str(number or "")).upper()


def not_text(name):
    return f"Save {name} as a CSV file and choose the CSV file."


def no_numbers(name):
    return (f"OpenH2O did not find any parcel numbers in {name}. Put the numbers in a column "
            "headed APN or Parcel number and choose the file again.")


def read_parcel_list(handle, name):
    """The list's numbers: ``{normalized: as written}``, first spelling kept, in file order.

    ``handle`` is a binary file object. Raises ParcelListError with the page's
    sentence for a spreadsheet's own format, for bytes that are not text, and for
    a file with no number in it.
    """
    raw = handle.read()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if (name.lower().endswith(NOT_TEXT_EXTENSIONS) or raw.startswith(_ZIP_MAGIC)
            or raw.startswith(_OLE_MAGIC) or b"\x00" in raw[:4096]):
        raise ParcelListError(not_text(name))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    rows = [row for row in csv.reader(io.StringIO(text)) if any(cell.strip() for cell in row)]
    column = 0
    if rows:
        heads = [re.sub(r"[^a-z]", "", cell.lower()) for cell in rows[0]]
        named = [i for i, head in enumerate(heads) if head in HEADINGS]
        if named:
            column = named[0]
            rows = rows[1:]

    numbers = {}
    for row in rows:
        if column >= len(row):
            continue
        written = row[column].strip()
        key = normalize(written)
        if key and key not in numbers:
            numbers[key] = written
    if not numbers:
        raise ParcelListError(no_numbers(name))
    return numbers
