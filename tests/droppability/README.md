# Droppability acceptance harness

Run it: `make test-droppable`

## What this proves

`OPENH2O_MODULES` promises that a deployment can leave a module out. This harness
is what makes that a tested promise rather than a claim in a docstring. For every
module in `OPTIONAL_MODULE_NAMES` — and once more with all of them gone at the
same time — it boots a Django process that never had the module and asserts:

- the module's apps are absent from the app registry;
- its nav `url_name`s raise `NoReverseMatch` and its URL prefix returns **404**,
  not a 500 and not a redirect to login (a dropped module is *absent*, not
  *protected*);
- none of its database tables exist;
- the ten pages a deployment keeps still render 200 — in three database states:
  pristine, configured-but-empty, and populated;
- the rendered sidebar carries no `href` into the dropped module's prefix.

## Why it spawns a subprocess

`OPENH2O_MODULES` is read from the environment at settings *import* time and
composes `INSTALLED_APPS`. Django populates its app registry exactly once, at
startup, and builds the URLconf from whatever was installed then. By the time a
test body runs, the apps are loaded, the routes are registered and the tables
exist — `override_settings(INSTALLED_APPS=...)` changes a value nothing reads
again.

So the only honest way to prove a module can be dropped is to boot a process that
never had it. **Do not "simplify" this into an in-process test.** It would stay
green and stop proving anything.

## The two files

| File | Role | Collected by `pytest tests/`? |
|---|---|---|
| `tests/test_droppability_acceptance.py` | The spawner. One case per optional module, plus all-dropped. | **Yes** — it matches `test_*.py`, so `make test` carries it. |
| `tests/droppability/checks.py` | The body of the proof. Runs *inside* the reduced process. | **No** — `checks.py` matches none of `pyproject.toml`'s `python_files` patterns. |

That asymmetry is deliberate. Run with every module enabled, `checks.py` has
nothing to assert; if the default suite collected it, it would be a permanently
green no-op that looks like coverage. A guard test inside it fails loudly if the
dropped set turns out to be empty.

## Adding a module to the gate (Phases 82-85)

To bring a newly decoupled module under this harness, flip `required=False` in
`core/modules.py` and update `tests/test_modules.py::TestDroppabilityPromise` —
the harness reads `OPTIONAL_MODULE_NAMES` and picks it up with no edit here.

Two things to carry with you when you do:

- **Move that module's factories in `tests/factories.py` behind an
  `is_enabled()` guard.** A `DjangoModelFactory` resolves its `Meta.model` string
  through the app registry at class-definition time, so an unguarded factory for
  a dropped module turns `import tests.factories` itself into an error and takes
  down every check at once. The `drinking` block at the bottom of that file is
  the pattern.
- **Read the red output; do not re-baseline it.** The spawner puts the child's
  full stdout and stderr into the assertion message precisely so a failure tells
  you which page broke and which URL could not reverse.

## What a real failure looks like

Moving one `{% url 'infrastructure:import' %}` outside its
`{% if 'infrastructure' in enabled_modules %}` guard produces:

    FAILED tests/droppability/checks.py::test_kept_page_renders_on_a_fresh_instance[/wells/]
    FAILED tests/droppability/checks.py::test_kept_page_renders_on_a_configured_but_empty_instance[/wells/]
    FAILED tests/droppability/checks.py::test_kept_list_page_renders_with_rows[/wells/-WellFactory]
    FAILED tests/droppability/checks.py::test_nav_carries_no_link_into_a_dropped_module[infrastructure]

    django.urls.exceptions.NoReverseMatch: 'infrastructure' is not a registered namespace

The page and the namespace are both named, which is the whole point.
