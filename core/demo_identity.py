# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one slug transform, shared by the composer and the scanner.

Two callers need the same transform for opposite reasons.
`core/management/commands/seed_merced_details.py::_fill_account_contacts`
COMPOSES a water-account contact address by slugifying a contact name, and
`core/management/commands/scan_demo_identity.py` must MATCH that same shape when
it looks for a real agency, district, farm or owner name sitting on invented
data. ISS-103 is exactly the gap between those two: a banned contact string such
as ``Merced Water Manager`` survives as ``merced.water.manager@example.com``, a
form no case-insensitive substring of the banned value matches.

The transform lives here, in one place, rather than being copied into the scan,
because a second copy would re-open ISS-103 on a slower clock — the day somebody
edits the composer's regex, the truncation length or the separator and the
scanner keeps looking for yesterday's shape, the blind spot is back and nothing
reports it. ISS-122 set this pattern when one boundary parse needed two callers:
extract, do not duplicate.

This module is deliberately NOT a management command. Command modules are not
importable as a stable API, and importing one command from another is a pattern
this codebase does not use.
"""

import re

#: Everything outside the slug alphabet collapses to a single separator.
_NON_SLUG_RUN = re.compile(r"[^a-z0-9]+")

#: The composer truncates to 40 characters, so the matcher must too — a longer
#: banned name only ever reaches the database in its truncated form.
SLUG_MAX_LENGTH = 40


def identity_slug(value: str) -> str:
    """Return ``value`` in the shape a composed contact address carries it.

    Lowercase, every run of characters outside ``[a-z0-9]`` collapsed to a
    single ``.``, leading and trailing ``.`` stripped, truncated to
    :data:`SLUG_MAX_LENGTH` characters.

    Empty or ``None`` input returns ``""``. The caller decides what to put in
    its place: the composer's ``or "contact"`` fallback is a seeding decision
    about what a blank account should be called, not a fact about slugs, and
    the scanner wants an empty string so it can skip the term entirely.
    """
    if not value:
        return ""
    return _NON_SLUG_RUN.sub(".", value.lower()).strip(".")[:SLUG_MAX_LENGTH]
