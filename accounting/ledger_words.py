# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ledger's one merged "Water" column, in words, and the engines' own sentences.

The Use Ledger's Description column is the one column written for a human, so
the engines' internal shorthand ("demand-weighted (ET-allocated)", "Derived
groundwater extraction estimate (calculation engine)") never appears in it.
The five sentences a reader sees for every engine-written row live here,
beside the Water column's words, so every word the ledger shows lives in one
file rather than being composed again at each write site.
`surface/services.py` and `accounting/management/commands/run_calculations.py`
import from this module; neither writes a sentence of its own.

The Water column is one column of plain text, naming the row's own water type
first and the kind of record second. Two badge-styled columns (a colored
Source pill plus a plain Water type cell) were confusing: "Meter reading"
stuck out next to "surface water diversion", and "well meter" is not a
California term.

**One function, two templates.** ``_ledger_list_results.html`` (the Use
Ledger table) and ``templates/parcels/partials/_detail_pane.html`` (a
parcel's ledger card) both show this column. Routing both templates through
one function instead of two copies of the same "if source_type == ..." chain
keeps their labels from drifting apart (``_source_badge.html`` and the
model's ``get_source_type_display`` were once two independent word lists).

**Every phrase carries the row's own ``water_type``.** A ``meter_reading``
row is usually a Groundwater well, but the field is real data, not an
assumption -- a deployment could record a metered Recycled Water delivery,
and this function has to say that, not "Groundwater, metered" regardless of
what the row actually holds. ``water_type`` is nullable on the model, so
every branch below has a fallback to the source word alone.
"""

import re
from decimal import Decimal

from core.map_labels import map_label
from parcels.models import (
    NON_POSITIVE_SOURCE_TYPES,
    POSITIVE_SOURCE_TYPES,
    ParcelLedger,
)


#: The first line of a ledger file downloaded from a demonstration site
#: (2026-10-18). The import skips it, so a downloaded export
#: re-imports as it is.
DEMONSTRATION_FILE_LINE = (
    "This file comes from the OpenH2O demonstration. Its figures are sample data."
)


#: The first line of a ledger file downloaded on a past reading (``?as_of=``): the day, in the
#: form the pages print it. The import skips a line of exactly this form, and only that.
_AS_OF_FILE_LINE = re.compile(
    r"As of the end of (Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{1,2}), (\d{4})\."
)


def as_of_file_line(day):
    """The line for a reading of ``day``: As of the end of Nov 3, 2026."""
    return f"As of the end of {day:%b} {day.day}, {day.year}."


#: What the import says of a file saved from a past reading.
PAST_FILE_REFUSED = (
    "This file holds the ledger as of a past date, so its rows may have been corrected or voided "
    "since. Download today's file to import."
)


def is_as_of_file_line(text):
    """True for a line of exactly the form :func:`as_of_file_line` writes."""
    return _AS_OF_FILE_LINE.fullmatch(text) is not None


def sign_rule_sentence():
    """The ledger's sign rule as `docs/DATA-IMPORT.md` states it.

    No screen prints it: the ledger list and the
    create form carry their own one-line rule. The import guide quotes it
    word for word, and `tests/test_ledger_import_sign_report.py` holds the
    guide to it. The wording
    names no module's source type, so it reads the same on every deployment,
    and the sign of each code is in the guide's table beside it.
    """
    return (
        "On the ledger, water taken against the allocation is a negative "
        "amount and water added to it is a positive amount. The table below "
        "gives the sign for each source type. Manual entries, CSV imports and "
        "adjustments keep the sign you give them."
    )


#: Every `ParcelLedger.SOURCE_TYPE_CHOICES` code, mapped to the sign it
#: carries. Built from the two sets the check constraints themselves enforce
#: (`parcels/models.py:52-67`) rather than a second hand-typed list, so this
#: table cannot drift from the constraint it describes. A code in neither set
#: is unconstrained -- the operator's own entries, which may go either way.
SOURCE_TYPE_SIGNS = {
    code: (
        "positive"
        if code in POSITIVE_SOURCE_TYPES
        else "negative" if code in NON_POSITIVE_SOURCE_TYPES else "either"
    )
    for code, _label in ParcelLedger.SOURCE_TYPE_CHOICES
}

#: Source types whose word pairs with the row's own water type name as
#: "{Water type}, {word}". ``manual_entry`` and ``csv_import`` are likewise one
#: word, "entered": they are the same thing to a
#: reader, whichever door the row came in through.
_PAIRED_WORDS = {
    "meter_reading": "metered",
    "calculated": "estimated",
    "surface_diversion": "diverted",
    "manual_entry": "entered",
    "csv_import": "entered",
    "adjustment": "adjusted",
}


def _water_type_name(entry):
    """Sentence case: "Surface Water" -> "Surface water", "Groundwater" stays
    "Groundwater". ``None`` when the row carries no water type at all."""
    water_type = entry.water_type
    if water_type is None or not water_type.name:
        return None
    return water_type.name.capitalize()


def ledger_row_words(entry):
    """The one Water column's text for one ``ParcelLedger`` row.

    ``recharge`` and ``allocation`` are paper, not a metering or estimating
    verb, so they get their own shapes: "Recharge credit" never names a
    water type (a recharge event is a credit regardless of which water
    filled the basin, and the words are settled as
    written); "{Water type} allocation credit" names the type because a
    groundwater allocation and a surface allocation are managed by
    different agencies under different law (DESIGN.md's Allocation entry)
    and a reader needs to tell them apart at a glance.
    """
    source_type = entry.source_type
    water_type_name = _water_type_name(entry)

    if source_type == "recharge":
        return "Recharge credit"

    if source_type == "allocation":
        return (
            f"{water_type_name} allocation credit"
            if water_type_name
            else "Allocation credit"
        )

    word = _PAIRED_WORDS.get(source_type)
    if word is None:
        # Every real SOURCE_TYPE_CHOICES value is covered above; this only
        # runs for a value added to the model later and not yet taught to
        # this function, and the model's own display string beats a blank
        # cell or a raised exception.
        return entry.get_source_type_display()

    if water_type_name:
        return f"{water_type_name}, {word}"
    return word.capitalize()


# --------------------------------------------------------------------------
# The engines' own sentences.
#
# `surface/services.py` (the demand-weighted and static-fraction allocation
# paths) and `run_calculations.py` (the incidental-recharge credit and the
# groundwater-extraction estimate) write these constants onto the
# `ParcelLedger.description` field they own, instead of composing engine
# shorthand at the write site. Every sentence here was scanned clean through
# `tests/test_domain_vocabulary.py::scan`.
# --------------------------------------------------------------------------

#: The tail of a demand-weighted delivery-share sentence, in the settled words:
#: the use area's figure was
#: divided up from the canal total in proportion to each use area's crop water
#: use after rain (the weight is ``CalculationRun.net_consumptive_use_af``,
#: read by ``surface.services._month_demand``). Composed by
#: ``delivery_share_words`` below, and printed again, in the same words, on
#: the calculation page's canal line (``accounting/views/calculation_runs.py``).
#:
#: "Crop water use after rain" is ETAW. Rows written before the wording
#: changed are reworded by parcels/migrations/0012. Rows that said "each
#: field's ETAW" are rewritten at their month's next calculation in an open
#: year; a finalized year's rows stay as written (they are in its code).
DELIVERY_SHARE_BY_USE = (
    "divided up from the canal total in proportion to each use area's ETAW"
)

#: The tail of a static-fraction delivery-share sentence: no served use area
#: had an estimated use for the month, so the split fell back to each use
#: area's share of the canal on file (``PointOfDiversionParcel.fraction``,
#: normalized by ``apportion_shared_supply``). The wording avoids "fixed
#: share", which was unclear. ``delivery_share_words`` below prints it after
#: "divided up from the canal total by", the same words the calculation
#: page's canal line puts before it (``accounting/views/calculation_runs.py``), so it stays a
#: noun phrase; the percentage and the "because no use area the canal serves
#: has an estimated use for the month" clause follow it there and are not
#: part of this constant. A colon in the sentence ("...Canal
#: Headgate: 20%, ...") would read as a definition under the domain gate's copular
#: shape (`tests/test_domain_vocabulary.py::scan`), so there is none.
DELIVERY_SHARE_BY_FIXED = "this use area's share of the canal on file"

#: Where that share came from, closing the sentence after the percentage. The
#: canal is divided by the shares the district entered for it, or by each use
#: area's acreage where it entered none; the row does not record which, so the
#: clause names both. Rows written with the earlier clause ("because no use area
#: the canal serves has an estimated use for the month", true only of the old
#: fallback) are reworded by parcels/migrations/0019.
DELIVERY_SHARE_SOURCE = (
    "taken from the shares entered for the canal, or from each use area's "
    "acreage where none were entered"
)

#: A `calculated` row's sentence when the month's residual is nonzero: the
#: platform's own estimate of pumping, derived from the month's estimated use
#: less rainfall and canal water delivered.
#:
#: The row's amount is ETAW met by groundwater ("Groundwater consumed" is
#: no California engineer's term), written as the formula with its real
#: sign. The row carries the CONSUMED amount (final_af); the run also
#: stamps a separate extracted figure (gw_extracted_af), so "pumping" alone
#: would not say which of the two the row means.
PUMPING_ESTIMATE_WORDS = (
    "ETAW met by groundwater (estimated): ETAW \u2212 ETAW met by surface water."
)

#: The zero-row sentence, kept byte for byte (including the full stop). `health/checks.py` carries the same claim
#: and `tests/test_health_checks.py` pins the two together.
#:
#: The sentence is in ETAW terms and names no supply: effective
#: precipitation alone can meet crop ET in a month, so a sentence naming
#: surface water would be false there. It says the estimated groundwater
#: extraction is zero, because the row is written with an amount of 0 and
#: the run stamps an extraction of 0, so an estimate is made and it is
#: zero; "does not estimate" would say the month was skipped.
#: parcels/migrations/0014_parcelledger_zero_extraction_words.py carries the
#: new words onto rows already saved.
NO_PUMPING_DERIVED_WORDS = (
    "Groundwater did not meet any of this month's ETAW, so the estimated "
    "groundwater extraction is zero."
)


def percent_words(fraction):
    """A fraction as a whole-number-or-decimal percent without trailing zeros.

    ``Decimal("0.1500")`` -> ``"15"``, ``Decimal("0.0125")`` -> ``"1.25"``,
    ``Decimal("1.0000")`` -> ``"100"``. The caller adds the percent sign.
    """
    return format((Decimal(fraction) * 100).normalize(), "f")


def delivery_share_words(record, pod, *, fixed_share=None, loss_fraction=None):
    """The Description sentence for one surface-diversion allocation row.

    ``record`` is the ``surface.models.DiversionRecord`` the allocation was
    split from; ``pod`` is its ``PointOfDiversion``. The figure is
    ``record.consumed_acre_feet()`` -- the magnitude the shares actually sum
    to, not ``volume_acre_feet`` -- at the Amount column's two-decimal,
    thousands-separated precision (copy rule 9's spirit: the sentence is for
    a reader, not a debugger).

    ``loss_fraction`` is the point's evaporation, seepage and spill shares added
    together. When it is above zero the sentence says the share is
    worked out after canal losses of that percent, so a reader knows the figure
    is not the headgate's own recorded volume. Left out when there are no losses.

    ``fixed_share`` is the ``Decimal`` weight (4dp, from
    ``apportion_shared_supply``) this parcel received on the static-fraction
    fallback path; pass it only from ``_fraction_rows``. When omitted, the
    sentence closes with ``DELIVERY_SHARE_BY_USE``; when given, it closes with
    "divided up from the canal total by", ``DELIVERY_SHARE_BY_FIXED``, the
    percentage, and ``DELIVERY_SHARE_SOURCE``.

    The verb phrase is "delivered from" for a `direct_use` record and "taken
    to storage from" otherwise (a to-storage record reaching this path is
    already a data error; the sentence must not lie about it).

    The POD's name is passed through ``core.map_labels.map_label`` so the
    stored ``MER-POD-...`` id never appears in the sentence -- the same
    stripper the overview maps use; this never writes a second one.

    A return-flow clause is inserted only when
    ``0 < record.returned_af < abs(record.volume_acre_feet)`` -- a partial
    return -- naming both the returned magnitude and the diverted volume.
    """
    consumed = record.consumed_acre_feet()
    verb = (
        "delivered from"
        if record.diversion_type == "direct_use"
        else "taken to storage from"
    )
    name = map_label(pod.name)

    sentence = f"Share of {consumed:,.2f} AF {verb} {name}"

    if Decimal("0") < record.returned_af < abs(record.volume_acre_feet):
        returned = record.returned_af
        volume = abs(record.volume_acre_feet)
        sentence += (
            f", after {returned:,.2f} AF of the {volume:,.2f} AF diverted "
            f"was returned to the stream"
        )

    if loss_fraction:
        sentence += f", after canal losses of {percent_words(loss_fraction)}%"

    if fixed_share is not None:
        sentence += (
            f", divided up from the canal total by {DELIVERY_SHARE_BY_FIXED}, "
            f"{fixed_share:.0%}, {DELIVERY_SHARE_SOURCE}"
        )
    else:
        sentence += ", " + DELIVERY_SHARE_BY_USE

    return sentence


#: What a use area's ledger row for its share of a well's meter reading starts
#: with. The month's calculation writes these rows and keeps them up to date
#: every time it runs; a meter row a person typed on the use area never starts
#: this way. The engine and the GEARS file find the rows by it.
WELL_METER_SHARE_WORDS = "From the well's meter:"


def well_share_words(well_name, volume, share):
    """The Description of a use area's share of a well's metered pumping for a month.

    ``volume`` is the acre-feet the well's readings add up to that month and
    ``share`` the use area's share as printed ("25%"). Starts with
    ``WELL_METER_SHARE_WORDS``, the prefix the engine finds these rows by.
    """
    return (
        f"{WELL_METER_SHARE_WORDS} {well_name} pumped {volume} AF this month, "
        f"this use area's share is {share}"
    )
