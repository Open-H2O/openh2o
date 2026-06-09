# SPDX-License-Identifier: AGPL-3.0-or-later
"""CSV formula-injection neutralization.

Spreadsheet apps (Excel, Google Sheets, LibreOffice) execute the contents of a
cell whose text begins with ``=``, ``+``, ``-``, ``@`` or a leading tab/CR/LF.
So an operator-typed free-text value (a ledger description, a parcel number, a
well or holder name) exported into one of our CSV downloads could run a formula
on whoever opens it — and for the GEARS/CalWATRS filings that "whoever" is a
state-agency reviewer. Prefixing such a value with a single quote forces the
spreadsheet to treat the whole cell as literal text. See OWASP "CSV Injection".

Only string cells are neutralized. Numeric cells (int/float/Decimal) and dates
are passed through untouched: they are not attacker-controlled formula vectors,
and prefixing a real negative number like ``-5.0`` with a quote would corrupt a
legitimate value in an official submission (it would arrive as text, not a
number). ``None`` becomes an empty string to match csv's own rendering.
"""

_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def csv_safe(value):
    """Return a single cell value, formula-neutralized if it is risky text."""
    if isinstance(value, str):
        if value and value[0] in _DANGEROUS_PREFIXES:
            return "'" + value
        return value
    return "" if value is None else value


def safe_row(cells):
    """Neutralize every cell in a row before handing it to csv.writer."""
    return [csv_safe(c) for c in cells]
