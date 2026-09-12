# SPDX-License-Identifier: AGPL-3.0-or-later
"""143-05: the ledger's one merged "Water" column, in words, not two badges.

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
