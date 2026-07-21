# SPDX-License-Identifier: AGPL-3.0-or-later
"""The composition rule, as a build-failing test.

`core/modules.py` states the rule; this file is what makes it true. Two
constraints, both enforced here:

1. A module everybody gets may not hold a database reference into a module they
   might not have. When it does, omitting the optional module leaves a dangling
   reference and ``migrate`` dies building the migration graph, before a single
   table is created.
2. Every real cross-module dependency must be declared in ``requires``.

**The graph is derived, never listed.** Every edge below comes from Django
itself — the live app registry and the on-disk migration graph. Nothing here
hardcodes today's edges as the expectation, because the entire point is to catch
the edge someone adds NEXT year, on the day they add it, rather than the day a
deployment breaks on it.

**Never grep for this.** Phase 82 found two couplings that were not imports at
all (a reverse accessor and an unconditional context key), and this codebase has
multi-line field declarations a same-line grep walks straight past.

**Why it lives in tests/ and not in core/modules.py.** The registry is imported
from ``config/settings/base.py``, so it must never touch the app registry —
doing so deadlocks app loading. This file needs the live registry, so it can
only ever live on this side of the line.

The eight tolerated violations are ``core.modules.SCHEMA_EXCEPTIONS``. A ninth
fails here. So does an exception record that no longer describes real code: the
allowlist can never quietly outlive the thing it excused.
"""

from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.db.migrations.loader import MigrationLoader
from django.db.models.fields.related import RelatedField

from core.modules import (
    MODULE_REGISTRY,
    SCHEMA_EXCEPTIONS,
    SCHEMA_PRESENT_MODULE_NAMES,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The two legal ways to resolve a cross-module edge. Quoted verbatim in every
#: failure message, so a red build tells you what to do rather than only what
#: broke.
THE_TWO_FIXES = (
    "Either declare it — add the target to that module's `requires` tuple in "
    "core/modules.py, which is right when the holder genuinely cannot work "
    "without the target and forcing the target on is acceptable — or record a "
    "reasoned exception in core.modules.SCHEMA_EXCEPTIONS, which is right when "
    "forcing the target on would defeat the point of it being optional. An "
    "exception must say why the arrow stands and what turning it around would "
    "cost."
)


# ---------------------------------------------------------------------------
# Deriving the real graph
# ---------------------------------------------------------------------------


def _owner_by_app_label() -> dict:
    """Which registry module owns each app label.

    Total over registry apps by construction —
    ``test_every_registered_app_belongs_to_exactly_one_module`` in
    ``tests/test_modules.py`` guarantees no app has two owners. Anything not in
    here is a Django contrib or third-party app, and the rule does not govern
    those: nobody can switch ``django.contrib.auth`` off in OPENH2O_MODULES.
    """
    owners = {}
    for name, spec in MODULE_REGISTRY.items():
        for app in spec.apps:
            owners[app] = name
    # Index by Django's resolved label too. Identical to the app name for every
    # app in this codebase today; this costs one loop and stops the mapping
    # going silently partial the day an AppConfig sets a custom `label`.
    for config in django_apps.get_app_configs():
        if config.name in owners:
            owners.setdefault(config.label, owners[config.name])
    return owners


def model_relation_edges() -> tuple:
    """Every cross-module model relation, as (holder, model, field, target).

    ``RelatedField`` is the base class of ``ForeignKey``, ``OneToOneField`` and
    ``ManyToManyField``, so this catches all three and nothing else. Testing
    ``field.concrete`` instead would silently MISS every many-to-many — an M2M
    has no column of its own, so Django marks it non-concrete. Reverse
    accessors are not ``RelatedField`` instances and are correctly absent: an
    edge belongs to the side that declares it.
    """
    owners = _owner_by_app_label()
    edges = set()
    for model in django_apps.get_models():
        holder = owners.get(model._meta.app_label)
        if holder is None:
            continue
        for field in model._meta.get_fields():
            if not isinstance(field, RelatedField):
                continue
            related = field.related_model
            if related is None:
                continue
            target = owners.get(related._meta.app_label)
            if target is None or target == holder:
                continue
            edges.add((holder, model.__name__, field.name, target))
    return tuple(sorted(edges))


def migration_dependency_edges() -> tuple:
    """Every cross-module migration-graph dependency, as (holder, target).

    ``MigrationLoader(None)`` builds the graph with NO database connection —
    the technique 83-DISCOVERY used to prove a dropped module fails during
    graph construction rather than at migrate time. It matters that this is
    checked separately from the model relations above: a migration dependency
    is a real dependency even when no live field remains, because the recorded
    history still names the other app. Deleting a field does not delete the
    edge.
    """
    owners = _owner_by_app_label()
    loader = MigrationLoader(None, ignore_no_migrations=True)
    edges = set()
    for (app_label, _name), migration in loader.disk_migrations.items():
        holder = owners.get(app_label)
        if holder is None:
            continue
        for dep_app, _dep_name in migration.dependencies:
            if dep_app.startswith("__"):
                # `__setting__` markers — a swappable dependency resolves to a
                # real app label elsewhere in the same list.
                continue
            target = owners.get(dep_app)
            if target is None or target == holder:
                continue
            edges.add((holder, target))
    return tuple(sorted(edges))


MODEL_EDGES = model_relation_edges()
MIGRATION_EDGES = migration_dependency_edges()


# ---------------------------------------------------------------------------
# Resolving an edge
# ---------------------------------------------------------------------------


def _is_declared(holder: str, target: str) -> bool:
    return target in MODULE_REGISTRY[holder].requires


def _exception_for(holder: str, model: str, field: str, target: str):
    """The record covering one exact model relation, or None."""
    for record in SCHEMA_EXCEPTIONS:
        if (record.holder, record.model, record.field, record.target) == (
            holder,
            model,
            field,
            target,
        ):
            return record
    return None


def _exception_covers_pair(holder: str, target: str) -> bool:
    """Whether any record excuses this module pair.

    Migration edges carry no field, so a pair match is all that can honestly be
    asked of them. The model-relation test above is where the exact field is
    checked.
    """
    return any(
        record.holder == holder and record.target == target
        for record in SCHEMA_EXCEPTIONS
    )


# ---------------------------------------------------------------------------
# The law
# ---------------------------------------------------------------------------


def test_the_graph_is_not_empty():
    """Fail loudly if the derivation itself broke.

    Every assertion below iterates a derived collection. If the derivation
    silently produced nothing — a renamed Django internal, an app registry that
    was not ready — the whole file would report a serene green while checking
    absolutely nothing. This is the difference between a tripwire and a
    decoration.
    """
    assert MODEL_EDGES, "derived zero cross-module model relations"
    assert MIGRATION_EDGES, "derived zero cross-module migration dependencies"


@pytest.mark.parametrize(
    "edge", MODEL_EDGES, ids=[f"{h}.{m}.{f}->{t}" for h, m, f, t in MODEL_EDGES]
)
def test_every_model_relation_is_declared_or_excepted(edge):
    holder, model, field, target = edge
    if _is_declared(holder, target):
        return
    if _exception_for(holder, model, field, target) is not None:
        return
    pytest.fail(
        f"Undeclared cross-module relation: {holder}.{model}.{field} points at "
        f"{target}, and {holder!r} neither declares requires=(..., {target!r}, ...) "
        f"nor carries a SCHEMA_EXCEPTIONS record for this field.\n\n"
        f"{THE_TWO_FIXES}"
    )


@pytest.mark.parametrize(
    "edge", MIGRATION_EDGES, ids=[f"{h}->{t}" for h, t in MIGRATION_EDGES]
)
def test_every_migration_dependency_is_declared_or_excepted(edge):
    holder, target = edge
    if _is_declared(holder, target):
        return
    if _exception_covers_pair(holder, target):
        return
    pytest.fail(
        f"Undeclared cross-module migration dependency: a migration in "
        f"{holder!r} depends on {target!r}, and {holder!r} neither declares it "
        f"in `requires` nor carries a SCHEMA_EXCEPTIONS record naming "
        f"{target!r}.\n\n"
        f"A migration dependency is a real dependency even when no live field "
        f"remains — the recorded history still names the other app, so the "
        f"graph still cannot be built without it.\n\n"
        f"{THE_TWO_FIXES}"
    )


@pytest.mark.parametrize(
    "record",
    SCHEMA_EXCEPTIONS,
    ids=[f"{r.holder}.{r.model}.{r.field}->{r.target}" for r in SCHEMA_EXCEPTIONS],
)
class TestExceptionRecords:
    """A tolerated violation has to keep earning its place."""

    def test_record_describes_a_real_relation(self, record):
        """A stale record fails, so the allowlist cannot outlive the code.

        Without this, deleting the field would leave a written excuse behind
        that reads as though the arrow still exists — and would silently
        pre-authorise re-adding it.
        """
        assert (record.holder, record.model, record.field, record.target) in MODEL_EDGES, (
            f"SCHEMA_EXCEPTIONS still excuses "
            f"{record.holder}.{record.model}.{record.field} -> {record.target}, but "
            f"no such relation exists in the live app registry any more. Either "
            f"the field was removed or renamed (delete the record — the arrow is "
            f"gone, which is good news) or the record has a typo in it."
        )

    def test_record_target_keeps_its_schema(self, record):
        """An exception pointing at a truly-removable module is a contradiction.

        The only reason these arrows are survivable is that the target's tables
        exist in every valid configuration — it is either standard or
        schema-resident. Point one at a module that can actually be uninstalled
        and you have written an excuse for a reference that WILL dangle.
        """
        assert record.target in SCHEMA_PRESENT_MODULE_NAMES, (
            f"{record.holder}.{record.model}.{record.field} is excused as pointing "
            f"at {record.target!r}, but {record.target!r} is neither required nor "
            f"schema-resident — its tables can genuinely disappear, so this "
            f"reference would dangle. Either make {record.target!r} "
            f"schema_resident=True, or turn the arrow around; an exception "
            f"record cannot make a dangling foreign key safe."
        )

    def test_record_points_at_the_real_line(self, record):
        """`where` is a checked fact, not a decorative comment.

        Line numbers rot silently. This one cannot: it is read back off disk.
        """
        filename, _, lineno = record.where.rpartition(":")
        path = REPO_ROOT / filename
        assert path.is_file(), f"{record.where}: {filename} does not exist"

        lines = path.read_text(encoding="utf-8").splitlines()
        index = int(lineno) - 1
        assert 0 <= index < len(lines), (
            f"{record.where} is past the end of {filename} ({len(lines)} lines)."
        )
        assert f"{record.field} = models." in lines[index], (
            f"{record.where} no longer declares {record.field!r}. The line reads:\n"
            f"    {lines[index].strip()!r}\n"
            f"Re-measure and update the `where` field on this record."
        )

    def test_record_explains_itself(self, record):
        """Both prose fields must actually say something.

        The record's whole value is that a future decision gets made on stated
        reasoning and a stated price rather than on a shrug.
        """
        assert record.holder in MODULE_REGISTRY, record.holder
        assert record.target in MODULE_REGISTRY, record.target
        assert len(record.why) > 40, f"{record.where}: `why` is too thin to be a reason"
        assert len(record.reversing_it) > 40, (
            f"{record.where}: `reversing_it` is too thin to be a price"
        )
