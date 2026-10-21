# SPDX-License-Identifier: AGPL-3.0-or-later
"""143-05: the ledger's one merged "Water" column, in words, not two badges.

**143-11 added the engines' own sentences below the Water-column words.** The
Use Ledger's Description column is the one column written for a human, and
until this plan it carried the engines' internal shorthand verbatim ("demand-
weighted (ET-allocated)", "Derived groundwater extraction estimate (calculation
engine)"), ISS-170. The five sentences a reader now sees for every engine-
written row live here, beside the Water column's words, so every word the
ledger shows lives in one file rather than being composed again at each write
site. `surface/services.py` and `accounting/management/commands/run_calculations.py`
import from this module; neither writes a sentence of its own.

The two badge-styled columns this plan's Task 4 shipped (a colored Source
pill plus a plain Water type cell) were confusing: "Meter reading" stuck out
next to "surface water diversion", and "well meter" is not a California
term. The settled shape is one column,
plain text, naming the row's own water type first and the kind of record
second.

**One function, two templates.** ``_ledger_list_results.html`` (the Use
Ledger table) and ``templates/parcels/partials/_detail_pane.html`` (a
parcel's ledger card) both show this column, and prior drift between the
ledger's own labels and the pane's was exactly the shape of bug this
plan's task1-baseline reproduced (``_source_badge.html`` and the model's
``get_source_type_display`` had always been two independent word lists).
Routing both templates through one function instead of two copies of the
same "if source_type == ..." chain is what makes that drift impossible
rather than merely unlikely.

**Every phrase carries the row's own ``water_type``.** A ``meter_reading``
row is usually a Groundwater well, but the field is real data, not an
assumption -- a deployment could record a metered Recycled Water delivery,
and this function has to say that, not "Groundwater, metered" regardless of
what the row actually holds. ``water_type`` is nullable on the model, so
every branch below has a fallback to the source word alone.
"""

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


def sign_rule_sentence():
    """The ledger's sign rule as `docs/DATA-IMPORT.md` states it (ISS-196).

    Since 149.1-05 (2026-10-07) no screen prints it: the ledger list and the
    create form carry their own one-line rule. The import guide quotes it
    word for word, and `tests/test_ledger_import_sign_report.py` holds the
    guide to it. The wording was approved on 2026-10-18; it
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
#: "{Water type}, {word}". ``calculated`` and ``et_estimate`` are the same
#: reader-facing word: both are the platform's own
#: estimate of pumping, not a meter reading, so "estimated" is the honest
#: word for either. ``manual_entry`` and ``csv_import`` are likewise one
#: word, "entered": they are the same thing to a
#: reader, whichever door the row came in through.
_PAIRED_WORDS = {
    "meter_reading": "metered",
    "calculated": "estimated",
    "et_estimate": "estimated",
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
    written); "{Water type} allocation" names the type because a
    groundwater allocation and a surface allocation are managed by
    different agencies under different law (DESIGN.md's Allocation entry)
    and a reader needs to tell them apart at a glance.
    """
    source_type = entry.source_type
    water_type_name = _water_type_name(entry)

    if source_type == "recharge":
        return "Recharge credit"

    if source_type == "allocation":
        return f"{water_type_name} allocation" if water_type_name else "Allocation"

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
# 143-11: the engines' own sentences (ISS-170).
#
# `surface/services.py` (the demand-weighted and static-fraction allocation
# paths) and `run_calculations.py` (the incidental-recharge credit and the
# groundwater-extraction estimate) write these constants onto the
# `ParcelLedger.description` field they own, instead of composing engine
# shorthand at the write site. Every sentence here was scanned clean through
# `tests/test_domain_vocabulary.py::scan` at planning time.
# --------------------------------------------------------------------------

#: The tail of a demand-weighted delivery-share sentence, in the settled words
#: (ISS-218, applied 2026-09-28): the field's figure was
#: divided up from the canal total in proportion to each field's crop water
#: use after rain (the weight is ``CalculationRun.net_consumptive_use_af``,
#: read by ``surface.services._month_demand``). Composed by
#: ``delivery_share_words`` below, and printed again, in the same words, on
#: the calculation page's canal line (``accounting/views.py``).
#:
#: 150.1-02 (2026-10-11): "crop water use
#: after rain" is ETAW. The rows written before are reworded by
#: parcels/migrations/0012.
DELIVERY_SHARE_BY_USE = (
    "divided up from the canal total in proportion to each field's ETAW"
)

#: The tail of a static-fraction delivery-share sentence: no served use area
#: had an estimated use for the month, so the split fell back to each use
#: area's share of the canal on file (``PointOfDiversionParcel.fraction``,
#: normalized by ``apportion_shared_supply``). 149.1-05: reworded from "the
#: fixed share on file", because "fixed share" was unclear. ``delivery_share_words`` below prints it after
#: "divided up from the canal total by", the same words the calculation
#: page's canal line puts before it (``accounting/views.py``), so it stays a
#: noun phrase; the percentage and the "because no use area the canal serves
#: has an estimated use for the month" clause follow it there and are not
#: part of this constant. The colon the sentence used to carry ("...Canal
#: Headgate: 20%, ...") read as a definition under the domain gate's copular
#: shape (`tests/test_domain_vocabulary.py::scan`), so it went.
DELIVERY_SHARE_BY_FIXED = "this use area's share of the canal on file"

#: A recharge row credited to a use area (or the basin pool) for canal water
#: delivered beyond what the month's estimated use called for.
#:
#: 148-02 Task 3 (Q1, an over-delivery is nobody's credit under the default):
#: under the default ("not_credited") or "named_line", `run_calculations`
#: writes no row carrying this text — the amount lives only on
#: `CalculationRun.over_delivery_af`. 148-04: under "credited",
#: `run_calculations` writes this row again, always as this exact prefix
#: (`over_delivery_credit_words`, below, composes it) so an old database's
#: rows and a "credited"-treatment row read the same way, and so
#: `run_calculations`'s delete-by-prefix (which runs every time, on every
#: treatment) still matches it.
#:
#: 150.1-02 (2026-10-11): reworded to the term surface water in excess
#: of ETAW. The words before are kept below as
#: `LEGACY_CANAL_CREDIT_WORDS` for the delete-by-prefix.
INCIDENTAL_RECHARGE_WORDS = "Credit for surface water in excess of ETAW"

#: The prefix every credit row carried from 143-11 to 150.1-02. Matched on
#: delete, like `LEGACY_INCIDENTAL_RECHARGE_WORDS` below, so a re-run on a
#: database whose rows were not reworded replaces them instead of doubling
#: them. Never written by new code.
LEGACY_CANAL_CREDIT_WORDS = (
    "Credit for canal water delivered beyond the use area's estimated use "
    "for the month"
)

#: The string every incidental-recharge row carried before 143-11. Matched on
#: delete, alongside `INCIDENTAL_RECHARGE_WORDS`, so a re-run on a database
#: written before this change replaces its own rows instead of doubling them
#: (ISS-052 preserved across the wording change). Never written by new code.
#:
#: 148-02 Task 3: for the same reason as `INCIDENTAL_RECHARGE_WORDS` above,
#: this is now doubly retired (no over-delivery caller writes it, and it was
#: already superseded by that constant at 143-11) but stays for the same
#: delete-by-prefix cleanup on a database two engines old.
LEGACY_INCIDENTAL_RECHARGE_WORDS = (
    "Incidental recharge — deep percolation from surface over-delivery"
)

#: A `calculated` row's sentence when the month's residual is nonzero: the
#: platform's own estimate of pumping, derived from the month's estimated use
#: less rainfall and canal water delivered.
#:
#: 148-02 Task 4 (Q2): reworded from "Estimated pumping" to "Estimated
#: groundwater consumed" -- the row still carries the CONSUMED amount
#: (final_af, unchanged), but Task 4 also stamps this run with a separate
#: extracted figure (gw_extracted_af) and "pumping" alone no longer says
#: which of the two the row means. "canal water delivered" -> "the canal
#: water the crop could use", the same Task 1 fix Task 3 already made to
#: NO_PUMPING_DERIVED_WORDS below.
#:
#: 150.1-02 (2026-10-11): the row's amount is ETAW met by groundwater
#: ("Groundwater consumed" is no California engineer's term),
#: written as the formula with its real sign.
PUMPING_ESTIMATE_WORDS = (
    "ETAW met by groundwater (estimated): ETAW \u2212 ETAW met by surface water."
)

#: The 143-05 zero-row sentence, moved into the engine verbatim (byte for
#: byte, including the full stop). `health/checks.py` carries the same claim
#: and `tests/test_health_checks.py` pins the two together.
#:
#: 148-02 Task 3: reworded from "delivered surface water" to "the canal water
#: the crop could use" — Task 1's per-field efficiency means the delivered
#: magnitude and what the crop could use are no longer the same number, and
#: this sentence describes what actually closed the month out (rule 14: no
#: "recharge", no "credit").
#:
#: 150.1-02 (2026-10-11): reworded in ETAW terms. It names no supply: on 41 of the
#: demo's 117 zero months effective precipitation alone met crop ET, so a
#: sentence naming surface water would be false there.
#:
#: 151.2-02 (2026-10-20): reworded to say the estimated groundwater extraction
#: is zero, where it used to read as if no estimate were made. The row is written with an amount
#: of 0 and the run stamps an extraction of 0, so an estimate is made and it is
#: zero; "does not estimate" would have said the month was skipped.
#: parcels/migrations/0014_parcelledger_zero_extraction_words.py carries the
#: new words onto rows already saved.
NO_PUMPING_DERIVED_WORDS = (
    "No ETAW met by groundwater this month, so the estimated groundwater "
    "extraction is zero."
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
    together (149-02). When it is above zero the sentence says the share is
    worked out after canal losses of that percent, so a reader knows the figure
    is not the headgate's own recorded volume. Left out when there are no losses.
    WORKING COPY: the clause is the one introduced at 149-02.

    ``fixed_share`` is the ``Decimal`` weight (4dp, from
    ``apportion_shared_supply``) this parcel received on the static-fraction
    fallback path; pass it only from ``_fraction_rows``. When omitted, the
    sentence closes with ``DELIVERY_SHARE_BY_USE``; when given, it closes with
    "divided up from the canal total by", ``DELIVERY_SHARE_BY_FIXED``, the
    percentage, and the "because no use area the canal serves has an estimated
    use for the month" tail.

    The verb phrase is "delivered from" for a `direct_use` record and "taken
    to storage from" otherwise (a to-storage record reaching this path is
    already the ISS-134 defect; the sentence must not lie about it).

    The POD's name is passed through ``core.map_labels.map_label`` so the
    stored ``MER-POD-...`` id never appears in the sentence -- the same
    stripper the overview maps use (143-07); this never writes a second one.

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
            f"{fixed_share:.0%}, because no use area the canal serves has an "
            f"estimated use for the month"
        )
    else:
        sentence += ", " + DELIVERY_SHARE_BY_USE

    return sentence


def over_delivery_credit_words(share):
    """The Description sentence for an over-delivery `recharge` row (148-04).

    `share` is `SiteConfig.over_delivery_leave_behind` in force when the run
    that writes this row was computed — the Decimal fraction (0..1) left in
    the basin rather than credited to the field. Starts with
    `INCIDENTAL_RECHARGE_WORDS` (unchanged from the pre-148-04 constant) so
    `run_calculations`'s delete-by-prefix still matches this row on a re-run
    or a later switch to "not_credited" / "named_line". The split is stated
    in whole percent points, both reading off the one `share` value so they
    always sum to 100%: `share=Decimal("0.100")` ->
    "..., 90% credited and 10% left in the basin".
    """
    left = format(share, ".0%")
    credited = format(Decimal("1") - share, ".0%")
    return f"{INCIDENTAL_RECHARGE_WORDS}, {credited} credited and {left} left in the basin"
