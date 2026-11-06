# SPDX-License-Identifier: AGPL-3.0-or-later
"""The retired screen words, and the words that are the same thing under one name.

Plain data, no Django imports: ``tests/test_screen_words_are_consistent.py`` reads
it and it is listed in ``NOT_SCREEN_PYTHON`` in ``scripts/writing_shapes.py``,
because its strings are a term list and are never shown. Each entry has a
one-line reason. An entry forbids a retired word or sentence form; none of
them describes the water.
"""

#: "No" put on the object after a word the existing "no for not" check skips
#: ("no one", "nobody", a preposition before "no"). The plain form puts "not"
#: on the verb: "not credited to anyone", "not delivered to a field".
#: Measured 2026-10-31: 24 sentences in 13 files.
NO_ON_THE_OBJECT: tuple = (
    (r"\b[Nn]o one\b", 'say "not ... anyone" ("Not credited to anyone")'),
    (r"\b[Nn]obody\b", 'say "not ... anyone" ("It is not credited to anyone")'),
    (r"\b(?:to|for|by|on|in|from|at|of|into) no "
     r"(?!longer\b|more\b|less\b|later\b|earlier\b|sooner\b|matter\b|other\b|fewer\b)[A-Za-z]+",
     'say "not ... a <noun>" ("Not delivered to a field", "is not in a water year yet")'),
)

#: "Fetch" on a station's readings. Brent, 2026-11-05: "Fetched? More AI Slop language." A source
#: sends readings, OpenH2O receives them, and the button updates them (ruling 91).
RETIRED_FETCH: tuple = (
    (r"\b[Ff]irst fetched\b", 'say "received"'),
    (r"\bOpenH2O fetched\b", 'say what the source sent: "USGS sent 3 new readings."'),
    (r"\bFetched\b", 'the column is "Date received"'),
    (r"\bFetch(?:ing)? readings\b", 'the button is "Update readings now"'),
    (r"\b(?:OpenH2O|schedule) fetches\b", 'say "updates readings"'),
    (r"\bnext fetch\b", 'say "next update"'),
)

#: A sentence that names a page carries that page's name (DESIGN.md copy rule 4).
RETIRED_PAGE_REFERENCES: tuple = (
    (r"\bthe field(?:'|’)s page\b", 'the page is the use area page: "the use area\'s page"'),
    (r"\bheadgate page\b", 'the page is the point of diversion page: "the point of diversion page"'),
)

#: Sign in and Sign out are the pair; the header, the buttons, the titles and
#: the back links all say Sign in. Read in templates only, the site's own controls.
RETIRED_SIGN_IN: tuple = (
    # "the log in this unit" is a log, not a sign-in: a noun before "in" is not the verb.
    (r"(?<!the )(?<!a )(?<!this )\b[Ll]og in\b", 'say "Sign in"'),
    (r"\b[Ll]ogin\b", 'say "Sign in" ("Back to Sign in", "Go to Sign in")'),
)

#: A page that makes a new record, and its button, say "Add" (the majority, and
#: copy rule 4: the button carries the page's name).
NEW_RECORD_TITLE_STARTS: tuple = ("New ", "Create ")
NEW_RECORD_BUTTON = r"\+\s*New\b"

#: The record a crop sits on is called "use area" on every screen.
FIELD_WORD = r"\b[Ff]ields?\b|\b[Ff]ield(?:'|’)s\b"

#: Phrases where "field" is a data field (a form box, a column, a key, a model
#: attribute) or land outside the record, so the word stays. One reason each.
#: A run that is a single word (a column header "Field", a code token such as
#: "fields" or "edit-field") is skipped before these are tried.
FIELD_OTHER_SENSES: tuple = (
    (r"\bthis field is required\b", "a form box"),
    (r"\bform fields?\b", "a form box"),
    (r"\bInvalid field\b", "the inline editor names a form box it did not recognize"),
    (r"\beditable field\b", "a box on a page that can be edited in place"),
    (r"\b[Tt]he three (?:method|DWR) fields\b|\bthree DWR fields\b|\bthese fields say\b",
     "the well's three method boxes"),
    (r"\bState Well Number field\b", "a box on the well page"),
    (r"\bThe Status field\b", "a box on the water right page"),
    (r"\bfield test\b", "a test done in the field on a device, not a record"),
    (r"\bupdate these fields\b|\bchange every field\b", "boxes on the drinking-water form"),
    (r"\bIts fields include\b", "the boxes of an EPA record"),
    (r"\bmatches each column to a field by name\b|\bmatched (?:the|each) fields? below\b",
     "import mapping: a column of the file is matched to a box of the record"),
    (r"\bNever filter jurisdiction by this field\b", "a model attribute"),
    (r"\bbefore this field existed\b", "a model attribute"),
    (r"\bfollow(?:ing)? one field\b|\breader of the field\b", "developer text about a model attribute"),
)

#: Files left out of the "field" count, each with a reason.
FIELD_WORD_EXCLUDED_FILES: tuple = (
    ("accounting/ledger_words.py", "its sentences are stored on ledger rows and change only "
     "with a data migration"),
)
