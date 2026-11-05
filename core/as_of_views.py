# SPDX-License-Identifier: AGPL-3.0-or-later
"""The as-of date box on the pages: one wrapper for a view, read through :mod:`core.as_of`.

``reads_as_of`` wraps a GET view. With ``?as_of=<date>`` holding a real date today or
earlier it runs the WHOLE view, and the render of its response, inside
:func:`core.as_of.reading_as_of`, so every query reads the past as the temporary tables
shadow the real ones. A lazy read after the block closed would print today's figure under
a past date, which this feature cannot do, so a template response is rendered before the
block ends.

What the wrapper leaves on the request for the context processor
(:func:`core.context_processors.as_of_flags`) and the views:

* ``request.as_of_reading`` and ``request.as_of_day``: set only while a reading is made;
* ``request.as_of_line``: the sentence under "As of" (set when a ``scope`` is given);
* ``request.as_of_notice``: the sentence of a refused date, shown where the line would be.

A date that cannot be read, or lies in the future, gets today's page under its sentence. A
use area that did not exist on the day (the view raises ``Http404`` inside the block) gets
today's page under ``missing(day)``, but only when ``exists(...)`` says the record is there
today; an id that never existed still answers 404. POST and every other method pass
through untouched.
"""
from functools import wraps

from django.http import Http404
from django.template.loader import render_to_string

from core.as_of import parse_as_of, reading_as_of


def day_words(day):
    """A date as the pages print it: Nov 3, 2026."""
    return f"{day:%b} {day.day}, {day.year}"


def line_sentence(day, changed, has_records):
    """The sentence of the line for a reading."""
    head = f"As of the end of {day_words(day)}."
    if not has_records:
        return f"{head} No records had been entered by then."
    count = "no records" if changed == 0 else f"{changed} record{'' if changed == 1 else 's'}"
    return f"{head} Since then {count} changed."


def reads_as_of(scope=None, *, exists=None, missing=None):
    """Wrap a GET view so ``?as_of=`` reads the records as they were at the end of that day.

    ``scope(request, reading, *args, **kwargs)`` returns ``{"parcel_ids", "start", "end"}``
    for the count in the line (called inside the block, so a table it reads is the past's);
    leave it out for a view that prints its date elsewhere (the file). ``exists(*args, **kwargs)`` and
    ``missing(day)`` handle a record that did not exist yet, as described above.
    """

    def decorate(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method != "GET" or "as_of" not in request.GET:
                return view(request, *args, **kwargs)
            day, sentence = parse_as_of(request.GET.get("as_of"))
            if sentence:
                request.as_of_notice = sentence
                return view(request, *args, **kwargs)
            if day is None:
                return view(request, *args, **kwargs)
            try:
                with reading_as_of(day) as reading:
                    request.as_of_reading = reading
                    request.as_of_day = day
                    if scope is not None:
                        wanted = scope(request, reading, *args, **kwargs)
                        changed = reading.changed_count(**wanted)
                        request.as_of_line = line_sentence(day, changed, reading.has_records(**wanted))
                    response = view(request, *args, **kwargs)
                    if hasattr(response, "render") and not getattr(response, "is_rendered", True):
                        response.render()
                    if scope is not None and request.headers.get("HX-Request"):
                        # The line sits outside what a filter or a water year swaps, and it counts
                        # what is shown, so it goes with the swap or it speaks for the old scope.
                        response.content += render_to_string(
                            "partials/_as_of_line.html", {"swap": True}, request=request
                        ).encode()
                    return response
            except Http404:
                if exists is None or missing is None or not exists(*args, **kwargs):
                    raise
            for name in ("as_of_reading", "as_of_day", "as_of_line"):
                request.__dict__.pop(name, None)
            # The record is there today but was not on the day: today's page, with no reading.
            request.as_of_notice = missing(day)
            return view(request, *args, **kwargs)

        return wrapper

    return decorate


def as_of_box(action, hidden):
    """What the box partial needs: the page it leads to and the fields it keeps.

    ``hidden`` is a list of ``(name, value)``; a blank value is kept when it means something
    (All Time is ``period=``).
    """
    return {"action": action, "hidden": [(name, str(value)) for name, value in hidden]}
