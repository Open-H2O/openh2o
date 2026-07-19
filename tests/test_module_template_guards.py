# SPDX-License-Identifier: AGPL-3.0-or-later
"""Kept templates must not hard-link into a module a deployment can switch off.

77-01 made `OPENH2O_MODULES` compose `INSTALLED_APPS` and the URL map, so an
omitted module's routes simply never register. That is the right behaviour — and
it is exactly what breaks a template that still says `{% url 'reporting:...' %}`.
Django raises `NoReverseMatch`, which is a 500 on a page that has nothing to do
with reporting.

So every reference from a *kept* template into an *optional* module has to sit
behind a `{% if '<module>' in enabled_modules %}` guard. (`enabled_modules` comes
from the `modules` context processor and is a list of names.)

Templates living inside an optional module's own directory are exempt: they only
ever render while that module is enabled.

This is a coarse check — it asserts the guard token is present in the file, not
that it wraps the specific line. The precise wrapping is proven at runtime by
actually booting with a reduced module list. What this catches is the common
regression: someone adds a link to an optional module and guards nothing at all.
"""
import re
from pathlib import Path

import pytest

from core.modules import MODULE_REGISTRY, OPTIONAL_MODULE_NAMES

TEMPLATES = Path(__file__).parent.parent / "templates"

#: Template subdirectories owned by an optional module. A file under one of
#: these renders only when its module is on, so it needs no guard.
OWNED_DIRS = {name: TEMPLATES / name for name in OPTIONAL_MODULE_NAMES}

#: Templates that live outside their module's directory but are still only ever
#: reached while that module is enabled. Each needs a reason, and the reason has
#: to be a guard somewhere else — not "it's probably fine".
EXEMPT = {
    # base.html includes this only inside {% if 'feedback' in enabled_modules %},
    # and that include is its single call site.
    ("feedback", "partials/_feedback_widget.html"),
}


def _kept_templates():
    for path in sorted(TEMPLATES.rglob("*.html")):
        yield path


@pytest.mark.parametrize("module", OPTIONAL_MODULE_NAMES)
def test_optional_module_links_are_guarded(module):
    pattern = re.compile(r"\{%\s*url\s*['\"]" + re.escape(module) + r":")
    guard = f"'{module}' in enabled_modules"

    unguarded = []
    for path in _kept_templates():
        # Skip the module's own templates — they imply the module is enabled.
        try:
            path.relative_to(OWNED_DIRS[module])
            continue
        except ValueError:
            pass

        rel = str(path.relative_to(TEMPLATES))
        if (module, rel) in EXEMPT:
            continue

        text = path.read_text(encoding="utf-8")
        if pattern.search(text) and guard not in text:
            unguarded.append(rel)

    assert not unguarded, (
        f"These templates link into the optional module {module!r} with no "
        f"\"{guard}\" guard. Dropping {module} would raise NoReverseMatch on "
        f"every page that renders them: {unguarded}"
    )


def test_optional_module_names_is_what_we_think():
    """Pin the droppable set, so this file's premise cannot drift silently.

    If a module becomes droppable (the ISS-072 decoupling work), it lands here
    and the guard test above immediately starts covering it.
    """
    assert set(OPTIONAL_MODULE_NAMES) == {
        "reporting", "health", "setup", "infrastructure", "feedback",
        # Phase 78. Droppable from the day it lands, by construction rather
        # than by later decoupling — nothing outside `drinking/` imports it.
        "drinking",
    }
    assert all(not MODULE_REGISTRY[n].required for n in OPTIONAL_MODULE_NAMES)
