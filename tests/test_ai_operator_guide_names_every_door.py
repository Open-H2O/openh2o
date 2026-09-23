# SPDX-License-Identifier: AGPL-3.0-or-later
"""The AI-operator guide's Option B table cannot fall behind the product (146-06 Task 2).

Every screen importer and every ``import_*`` management command is a door the
guide has to name, or an AI agent standing up a deployment never finds it.
Rather than a human re-reading the guide every time a door is added, this test
derives the door list itself: every URL name containing "import" or "onboard"
across the full module set, read through Django's own resolver (never grep,
which cannot see what a module conditionally registers), and every management
command whose name starts with ``import_`` (``django.core.management.get_commands``,
the same registry Django's own ``manage.py help`` reads). Each is asserted
present in the guide's Option B section — not the whole file, so a mention in
Phase 4 or the troubleshooting table does not count.

**Why the workflow's own preview/commit steps do not each need a line.** A
screen importer is one door with an upload-preview-commit flow inside it
(``surface/diversion/import/`` then its own ``preview/`` and ``commit/``
endpoints); the guide names the door an operator opens, not the three HTTP
requests behind it. So the collected names are reduced to their shortest
common path first: ``/drinking/onboard/`` covers ``onboard/lookup/``,
``onboard/commit/`` and ``onboard/<pwsid>/points/`` the same way
``/infrastructure/import/`` covers its own ``preview/`` and ``commit/``. A
brand-new door that is not a sub-step of one already named still stands on
its own after the reduction, which is the case this test exists to catch.
"""
from django.conf import settings
from django.urls import get_resolver

from core.modules import ALL_MODULE_NAMES

GUIDE_PATH = "docs/AI-OPERATOR-GUIDE.md"


def _guide_text() -> str:
    with open(GUIDE_PATH, encoding="utf-8") as fh:
        return fh.read()


def _option_b_section(guide_text: str) -> str:
    """The Option B subsection alone: from its heading to the next ``## ``/``### ``.

    Parses the table's own section rather than the whole file, so a door
    named only in passing elsewhere (Phase 4, troubleshooting) does not
    satisfy the guard.
    """
    start = guide_text.index("### Option B")
    rest = guide_text[start + len("### Option B"):]
    lines = rest.splitlines()
    end = len(lines)
    for i, line in enumerate(lines):
        if line.startswith("## ") or line.startswith("### "):
            end = i
            break
    return "### Option B" + "\n".join(lines[:end])


def _walk_url_names_containing(resolver, needle_names, prefix=""):
    """Every (full_path, name) pair whose name contains one of needle_names.

    Walks the live resolver tree (never grep on urls.py, which cannot see
    what ``core.modules.url_specs_for`` conditionally registers). Each
    pattern's own declared route string is concatenated with its parents',
    converters (``<int:pk>``) intact — good enough for the prefix reduction
    below, since no import/onboard route diverges from another except after
    a converter segment.
    """
    found = []
    for pattern in resolver.url_patterns:
        route_piece = str(pattern.pattern)
        full = prefix + route_piece
        nested = getattr(pattern, "url_patterns", None)
        if nested is not None:
            found.extend(_walk_url_names_containing(pattern, needle_names, full))
        else:
            name = pattern.name or ""
            if any(needle in name.lower() for needle in needle_names):
                found.append("/" + full)
    return found


def _reduce_to_shortest_prefixes(paths):
    """Drop any path that is itself prefixed by a shorter path already kept.

    ``/drinking/onboard/lookup/`` and ``/drinking/onboard/<str:pwsid>/points/``
    both start with the shorter, already-collected ``/drinking/onboard/`` and
    add nothing the guide needs to say twice.
    """
    ordered = sorted(set(paths), key=len)
    kept = []
    for path in ordered:
        if not any(path.startswith(shorter) for shorter in kept):
            kept.append(path)
    return kept


def test_full_module_set_is_what_this_guard_reads():
    """The guard's premise: nothing narrows OPENH2O_MODULES for this test run.

    If this fails, some setting or fixture has scoped the module list below
    the full set, and the door list below would silently under-count rather
    than fail loud — so this is checked first and named explicitly.
    """
    assert set(settings.OPENH2O_MODULES) == set(ALL_MODULE_NAMES), (
        "expected the full module set; got "
        f"{sorted(settings.OPENH2O_MODULES)} vs {sorted(ALL_MODULE_NAMES)}"
    )


def test_every_import_or_onboard_route_is_named_in_option_b():
    resolver = get_resolver()
    raw = _walk_url_names_containing(resolver, needle_names=("import", "onboard"))
    doors = _reduce_to_shortest_prefixes(raw)
    assert doors, "no import/onboard routes found at all — the resolver walk is broken"

    section = _option_b_section(_guide_text())
    missing = [d for d in doors if d not in section]
    assert not missing, (
        "Option B is missing these doors (by route): "
        f"{missing}. All doors found: {doors}"
    )


def test_every_import_management_command_is_named_in_option_b():
    from django.core.management import get_commands

    commands = sorted(name for name in get_commands() if name.startswith("import_"))
    assert commands, "no import_* management commands found — get_commands() is broken"

    section = _option_b_section(_guide_text())
    missing = [c for c in commands if c not in section]
    assert not missing, (
        f"Option B is missing these commands (by name): {missing}. "
        f"All import_* commands found: {commands}"
    )
