# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write computed rows over the stored rows they stand for, changing only what differs.

The calculation works out every row of a month again each time it runs.
Deleting the stored rows and inserting the new ones recorded every row in the
change history twice, a removal and an insertion, even when no figure moved,
and gave every row a new id, creation time and transaction date.

:func:`write_changes` matches each computed row to a stored row that names
the same record, on a key (the keys :mod:`core.as_of` reads the past by), then:

- a stored row equal to its computed row on every compared column is left as
  it is: its id, creation time and transaction date are kept and nothing is
  recorded;
- a stored row that differs is updated in place, and its ``refresh`` columns
  (a ledger row's transaction date, a calculation's creation time) take the
  computed row's values, as a new row would;
- a computed row no stored row matches is inserted;
- a stored row no computed row matches is deleted.

The compared columns are every concrete column except the id, the times a row
was written (:data:`core.as_of.UNCOMPARED`) and the ``refresh`` columns.
Decimals are compared as the database keeps them (the field's decimal places)
and JSON as it reads back, so a computed figure equals its stored copy.

Two rows can share a key (two diversion records in a month, split onto the same
use area). Within a key, rows equal on every compared column pair first and the
rest pair in the order given.
"""

import json
from decimal import Decimal

from django.db import models, transaction
from django.db.backends.utils import format_number

from core.as_of import UNCOMPARED


def _compared_fields(model, refresh):
    skip = set(UNCOMPARED) | set(refresh)
    return [f for f in model._meta.concrete_fields if not f.primary_key and f.attname not in skip]


def _normal(field, value):
    """``value`` as the database would give it back for ``field``."""
    if value is None:
        return None
    if isinstance(field, models.DecimalField):
        return Decimal(format_number(Decimal(value), field.max_digits, field.decimal_places))
    if isinstance(field, models.JSONField):
        return json.loads(json.dumps(value, cls=field.encoder))
    return value


def _signature(row, fields):
    return tuple(_normal(f, getattr(row, f.attname)) for f in fields)


def write_changes(stored, computed, *, key, refresh=(), bulk=True):
    """Make ``stored`` (the saved rows of one scope) hold ``computed`` (unsaved rows), writing only what differs.

    ``key`` names the columns (attnames) that say two rows are the same record.
    ``bulk`` inserts new rows in one statement; pass False for a model whose
    ``save()`` sets a column. Returns the saved rows, in ``computed``'s order.
    Runs in one transaction.
    """
    computed = list(computed)
    stored = list(stored)
    if not computed and not stored:
        return []
    model = type(computed[0] if computed else stored[0])
    fields = _compared_fields(model, refresh)
    names = [f.attname for f in fields]

    def key_of(row):
        return tuple(getattr(row, k) for k in key)

    waiting = {}
    for row in stored:
        waiting.setdefault(key_of(row), []).append((_signature(row, fields), row))

    result = [None] * len(computed)
    unmatched = []
    for i, row in enumerate(computed):
        signature = _signature(row, fields)
        candidates = waiting.get(key_of(row), [])
        for j, (stored_signature, stored_row) in enumerate(candidates):
            if stored_signature == signature:
                result[i] = stored_row
                del candidates[j]
                break
        else:
            unmatched.append((i, signature))

    updates, inserts = [], []
    for i, signature in unmatched:
        row = computed[i]
        candidates = waiting.get(key_of(row), [])
        if not candidates:
            inserts.append(i)
            continue
        stored_signature, stored_row = candidates.pop(0)
        changed = [n for n, old, new in zip(names, stored_signature, signature) if old != new]
        for name in changed + list(refresh):
            setattr(stored_row, name, getattr(row, name))
        updates.append((stored_row, changed + list(refresh)))
        result[i] = stored_row

    gone = [stored_row.pk for candidates in waiting.values() for _sig, stored_row in candidates]
    with transaction.atomic():
        if gone:
            model.objects.filter(pk__in=gone).delete()
        for stored_row, update_fields in updates:
            stored_row.save(update_fields=update_fields)
        new_rows = [computed[i] for i in inserts]
        if new_rows:
            if bulk:
                new_rows = model.objects.bulk_create(new_rows)
            else:
                for row in new_rows:
                    row.save()
        for i, row in zip(inserts, new_rows):
            result[i] = row
    return result
