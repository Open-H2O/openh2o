# SPDX-License-Identifier: AGPL-3.0-or-later
"""Prose that names only the water domains a deployment actually runs.

ISS-082's copy half. Some sentences survive being made module-neutral -- the
home page's map sublabel went from "every well, parcel, and diversion" to
"everything you manage", and lost nothing. Others cannot: Getting Started tells
an operator what the Setup Wizard will import, and "it populates your data" is
vague where "your use areas, wells, recharge basins, and nearby monitoring
stations" is useful. A sentence that enumerates has to keep enumerating, and
gate each noun instead.

``{% module_nouns %}`` is that gate. The nouns stay in the template beside the
sentence they belong to -- which is where someone editing the copy will look for
them, rather than in a view three files away -- and each carries the module that
earns it:

    it populates your {% module_nouns "parcels:use areas" "wells:wells" %} for you

**Declared per call site, never derived.** The noun is not the module label:
``datasync`` is "Data Sync" in the registry and "nearby monitoring stations" in
this sentence, and ``recharge`` is "Recharge" and "recharge basins". Deriving
prose from a label would produce sentences nobody wrote. Same discipline as
``_PAGES`` in the droppability harness: one declared row per thing, and adding a
module means adding a row rather than editing logic.

The join is Oxford-comma English, which is what these sentences already used --
so on a full deployment the rendered output is byte-identical to the hardcoded
text it replaced. That is the property the milestone constraint rests on, and
``tests/test_module_prose.py`` pins it.
"""
from django import template

from core.modules import is_enabled

register = template.Library()


def oxford_join(items, conjunction: str = "and") -> str:
    """``[a, b, c]`` -> ``"a, b, and c"``. Serial comma, because the copy uses it.

    An empty list renders as the empty string rather than raising. A sentence
    left with nothing to name is a copy problem for the caller to guard with an
    ``{% if %}``, not something this function can fix by inventing a noun.
    """
    items = [item for item in items if item]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conjunction} {items[1]}"
    return f"{', '.join(items[:-1])}, {conjunction} {items[-1]}"


def _split(pair: str):
    """``"wells:wells"`` -> ``("wells", "wells")``.

    Split on the FIRST colon only, so a noun may contain one -- and fail loudly
    on a pair with no colon at all, because the quiet alternative is a noun that
    silently never renders.
    """
    module, separator, noun = pair.partition(":")
    if not separator:
        raise template.TemplateSyntaxError(
            f"module_nouns expects 'module:noun' pairs; got {pair!r}. Without a "
            f"colon there is no module to gate on, and the noun would either "
            f"always render or never render depending on how it was read."
        )
    return module.strip(), noun.strip()


@register.simple_tag
def module_nouns(*pairs, conjunction="and"):
    """The enabled subset of ``module:noun`` pairs, joined as English.

    Order follows the call site, not the registry, because the sentence's order
    is the author's decision.
    """
    nouns = [noun for module, noun in map(_split, pairs) if is_enabled(module)]
    return oxford_join(nouns, conjunction)


@register.simple_tag
def any_module_enabled(*names):
    """Whether any of these modules is on -- the guard for a sentence that would
    otherwise be left naming nothing.

    A tag rather than a filter so a template can write
    ``{% any_module_enabled "wells" "surface" as can_file %}`` and branch on it,
    which Django's ``{% if %}`` cannot do across a variable number of arguments.
    """
    return any(is_enabled(name) for name in names)
