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

Checkpoint ruling, 2026-09-12 (Brent, second read): the two badge-styled
columns this plan's Task 4 shipped (a colored Source pill plus a plain Water
type cell) read as "very confusing" -- "Meter reading in the source sticks
out compared to surface water diversion", "California wouldn't say well
meter", and the standing instruction to stop reaching for a short, simple
fix and instead make the row readable. The settled shape is one column,
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


def sign_rule_sentence(*, recharge_enabled=True, surface_enabled=True):
    """The one sign rule, said the same way at every door (ISS-196).

    Every screen that shows a ledger figure, the CLI importer, the web
    upload preview and `docs/DATA-IMPORT.md` all quote this sentence
    verbatim rather than composing their own version of it, so the rule
    cannot drift between doors the way it did before 146-01: the document
    said "positive = supply, negative = usage" while the screens said
    "negative amounts are water delivered or pumped", and neither one named
    a `source_type` code that actually exists.

    With the defaults (both flags ``True``) this returns the sentence
    exactly as written. Each flag drops its own module's example from the
    sentence's own list the same module-neutral way the ledger page's page
    description already handles "and recharge" one line above
    (`templates/accounting/ledger_list.html`): a deployment with no
    `recharge` module has no recharge credits to name, and one with no
    `surface` module has no surface diversions
    (`tests/droppability/checks.py::test_kept_pages_never_name_a_dropped_module`).
    """
    positive_examples = "allocations, recharge credits" if recharge_enabled else "allocations"
    negative_examples = "meter readings, ET estimates"
    if surface_enabled:
        negative_examples += ", surface diversions"
    negative_examples += ", calculated rows"
    return (
        f"Water taken against the allocation is a negative amount "
        f"({negative_examples}); water added to it is positive "
        f"({positive_examples}); manual entries, CSV-import rows and "
        f"adjustments carry the sign you give them."
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
#: reader-facing word (checkpoint ruling): both are the platform's own
#: estimate of pumping, not a meter reading, so "estimated" is the honest
#: word for either. ``manual_entry`` and ``csv_import`` are likewise one
#: word, "entered" -- the checkpoint ruling named these the same thing to a
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
    filled the basin, and the checkpoint ruling settled the words as
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
# shorthand at the write site. Every sentence here was ruled on by Brent,
# 2026-09-15 09:40 PDT, and scanned clean through
# `tests/test_domain_vocabulary.py::scan` at planning time.
# --------------------------------------------------------------------------

#: The tail of a demand-weighted delivery-share sentence: the share was split
#: across the use areas a point of diversion serves by each one's estimated
#: use for the month. Composed by ``delivery_share_words`` below.
DELIVERY_SHARE_BY_USE = (
    "split among the use areas it serves by each one's estimated use for the "
    "month"
)

#: The tail of a static-fraction delivery-share sentence: no served use area
#: had an estimated use for the month, so the split fell back to the fixed
#: share on file. The percentage and the "because no use area it serves has
#: an estimated use for the month" clause are composed by
#: ``delivery_share_words`` below, not part of this constant.
DELIVERY_SHARE_BY_FIXED = "the fixed share on file"

#: A recharge row credited to a use area (or the basin pool) for canal water
#: delivered beyond what the month's estimated use called for.
INCIDENTAL_RECHARGE_WORDS = (
    "Credit for canal water delivered beyond the use area's estimated use "
    "for the month"
)

#: The string every incidental-recharge row carried before 143-11. Matched on
#: delete, alongside `INCIDENTAL_RECHARGE_WORDS`, so a re-run on a database
#: written before this change replaces its own rows instead of doubling them
#: (ISS-052 preserved across the wording change). Never written by new code.
LEGACY_INCIDENTAL_RECHARGE_WORDS = (
    "Incidental recharge — deep percolation from surface over-delivery"
)

#: A `calculated` row's sentence when the month's residual is nonzero: the
#: platform's own estimate of pumping, derived from the month's estimated use
#: less rainfall and canal water delivered.
PUMPING_ESTIMATE_WORDS = (
    "Estimated pumping: the month's estimated use, less rainfall and canal "
    "water delivered"
)

#: The 143-05 zero-row sentence, moved into the engine verbatim (byte for
#: byte, including the full stop). `health/checks.py:265` carries the same
#: claim and `tests/test_health_checks.py:343` pins the two together; neither
#: is edited by 143-11.
NO_PUMPING_DERIVED_WORDS = (
    "No groundwater extraction was derived for this month; rainfall and "
    "delivered surface water covered the estimated use."
)


def delivery_share_words(record, pod, *, fixed_share=None):
    """The Description sentence for one surface-diversion allocation row.

    ``record`` is the ``surface.models.DiversionRecord`` the allocation was
    split from; ``pod`` is its ``PointOfDiversion``. The figure is
    ``record.consumed_acre_feet()`` -- the magnitude the shares actually sum
    to, not ``volume_acre_feet`` -- at the Amount column's two-decimal,
    thousands-separated precision (copy rule 9's spirit: the sentence is for
    a reader, not a debugger).

    ``fixed_share`` is the ``Decimal`` weight (4dp, from
    ``apportion_shared_supply``) this parcel received on the static-fraction
    fallback path; pass it only from ``_fraction_rows``. When omitted, the
    sentence closes with ``DELIVERY_SHARE_BY_USE``; when given, it closes with
    a colon, the percentage, ``DELIVERY_SHARE_BY_FIXED``, and the "because no
    use area it serves has an estimated use for the month" tail.

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

    if fixed_share is not None:
        sentence += (
            f": {fixed_share:.0%}, {DELIVERY_SHARE_BY_FIXED}, because no use "
            f"area it serves has an estimated use for the month"
        )
    else:
        sentence += ", " + DELIVERY_SHARE_BY_USE

    return sentence
