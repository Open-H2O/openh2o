# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Reason box: one rule for every change to a record that feeds a figure.

A void and every edit of a covered figure ask why. The answer is 10 to 500
characters (the bounds ``core.corrections`` holds for a void) and is saved as
the change's note (``core.history.change_note``), so Change history shows it
beside what changed.

- :class:`ReasonField`: the form field, for the edit forms that are Django forms.
- :func:`check_reason`: the same rule for a handler that reads its own parameters
  (the inline field editors).
"""

from django import forms

from core.corrections import REASON_MAX_LENGTH, REASON_MIN_LENGTH, REASON_SENTENCE


class ReasonField(forms.CharField):
    """A required Reason box, 10 to 500 characters, no placeholder."""

    default_error_messages = {
        "required": REASON_SENTENCE,
        "min_length": REASON_SENTENCE,
        "max_length": REASON_SENTENCE,
    }

    def __init__(self, **kwargs):
        kwargs.setdefault("label", "Reason")
        kwargs.setdefault("min_length", REASON_MIN_LENGTH)
        kwargs.setdefault("max_length", REASON_MAX_LENGTH)
        kwargs.setdefault("widget", forms.TextInput(attrs={"class": "form-input"}))
        super().__init__(**kwargs)


def check_reason(text):
    """``(reason, error)`` for a typed reason: the stripped text and ``""``, or ``""`` and the sentence."""
    reason = (text or "").strip()
    if REASON_MIN_LENGTH <= len(reason) <= REASON_MAX_LENGTH:
        return reason, ""
    return "", REASON_SENTENCE
