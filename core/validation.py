# SPDX-License-Identifier: AGPL-3.0-or-later
"""Entry-boundary coercion for raw request input.

These helpers turn a raw POST string into a validated ``Decimal``/``int`` (or
``None`` for a blank, optional field) and raise :class:`FieldValidationError`
with a user-safe message when the value is non-numeric or out of range. They
exist so the imperative views that bypass Django Forms — the inline field
editors and the multi-type infrastructure "Add" form — still reject bad input
at the boundary instead of letting it reach a Decimal/Integer column, where a
non-numeric value 500s and a negative value silently corrupts the downstream
allocation, recharge, and GEARS math.
"""
from decimal import Decimal, InvalidOperation


class FieldValidationError(ValueError):
    """A numeric field value was non-numeric or out of range.

    The message is composed from the human field label and is safe to render
    straight back to the user.
    """


def _clean_raw(raw):
    if raw is None:
        return ""
    return str(raw).strip()


def coerce_decimal(raw, label, *, min_value=None, min_exclusive=False, allow_blank=True):
    """Coerce ``raw`` to a finite ``Decimal``.

    Returns ``None`` for a blank value when ``allow_blank`` (the nullable-column
    case). Raises :class:`FieldValidationError` for non-numeric input, NaN/inf,
    or a value below ``min_value`` (``min_exclusive`` makes the bound strict).
    """
    text = _clean_raw(raw)
    if text == "":
        if allow_blank:
            return None
        raise FieldValidationError(f"{label} is required.")
    try:
        value = Decimal(text)
    except (InvalidOperation, ValueError):
        raise FieldValidationError(f"{label} must be a number.")
    if not value.is_finite():
        raise FieldValidationError(f"{label} must be a number.")
    if min_value is not None:
        bound = Decimal(str(min_value))
        if min_exclusive:
            if value <= bound:
                raise FieldValidationError(f"{label} must be greater than {bound}.")
        elif value < bound:
            if bound == 0:
                raise FieldValidationError(f"{label} cannot be negative.")
            raise FieldValidationError(f"{label} must be at least {bound}.")
    return value


def coerce_int(raw, label, *, min_value=None, max_value=None, allow_blank=True):
    """Coerce ``raw`` to an ``int``.

    Returns ``None`` for a blank value when ``allow_blank``. Raises
    :class:`FieldValidationError` for non-integer input or a value outside
    ``[min_value, max_value]``.
    """
    text = _clean_raw(raw)
    if text == "":
        if allow_blank:
            return None
        raise FieldValidationError(f"{label} is required.")
    try:
        value = int(text)
    except (ValueError, TypeError):
        raise FieldValidationError(f"{label} must be a whole number.")
    if min_value is not None and value < min_value:
        raise FieldValidationError(f"{label} must be at least {min_value}.")
    if max_value is not None and value > max_value:
        raise FieldValidationError(f"{label} must be at most {max_value}.")
    return value
