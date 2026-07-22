# Droppability acceptance harness

Run it: `make test-droppable`

## What this proves

`OPENH2O_MODULES` promises that a deployment can leave a module out. This harness
is what makes that a tested promise rather than a claim in a docstring. For every
module in `OPTIONAL_MODULE_NAMES` — and once more with all of them gone at the
same time — it boots a Django process that never had the module and asserts:

**For every dropped module, whichever class it is in:**

- its nav `url_name`s raise `NoReverseMatch` and its URL prefix returns **404**,
  not a 500 and not a redirect to login (a dropped module is *absent*, not
  *protected*);
- the rendered sidebar carries no `href` into the dropped module's prefix;
- every page a deployment *keeps* still renders 200 — in three database states:
  pristine, configured-but-empty, and populated;
- a detail page renders too (`/surface/diversion/<pk>/`), because detail panes
  reach into other modules in ways no list page does.

## Two assertion sets, chosen by the registry

Everything above is the half of the promise that is identical for every dropped
module: **what the operator can see is gone**. What happens to the *schema*
depends on which class the module is in, so the harness carries two sets and
picks per module from `spec.schema_resident` — declared by the owner, never
derived, the same discipline as the page table below.

| | Truly removed (`schema_resident=False`) | Schema-resident (`schema_resident=True`) |
|---|---|---|
| App in the registry | **absent** | **present** |
| Its database tables | **absent** | **present and empty** |
| Seed commands | not run | not run |
| Routes / nav / pages | gone | gone |

Schema-residency is how a module gets switched off without breaking the
relationships that point *into* it — the eight recorded in
`core/modules.py::SCHEMA_EXCEPTIONS`. Its tables have to keep existing or those
references dangle and `migrate` dies building the migration graph.

**The second set is dormant today.** No module is both optional and
schema-resident, so it collects zero cases — and rather than reporting that as
silent success, `test_schema_resident_coverage_is_declared` skips with a message
saying so. Phase 88 is its first real user, when `wells` and `datasync` are
demoted model-only.

## Cases are dependency-closure-aware

A case does not drop one module; it drops that module's **requires-closure** —
the module plus every *optional* module that transitively requires it. Dropping
X while something that needs X stays enabled is not a droppability test at all:
the child would die in `validate_module_names` before rendering a page, and the
harness would be testing the validator while looking like a gate.
`test_case_is_the_exact_requires_closure_and_validates` pins exactly that, per
case.

Today every closure is a single module, so the generated cases are identical to
the pre-closure ones. **Phase 87 is what changes it**: `recharge` declares
`requires=(..., "surface")`, so the day `surface` becomes optional, dropping it
validly takes `recharge` with it — and the harness generates that configuration
with no edit to any test file. `drop_closure()` carries a visited set because
`requires` may contain cycles (`measurements` and `standards` genuinely
reference each other).

## The page list is owner-declared

`checks.py` does not carry a flat list of pages. It carries `_PAGES`, where every
path is paired with the module that **owns** it, and `KEPT_PAGES` is that table
filtered down to the modules the current process actually booted with:

    _PAGES = (
        ("/",          None),        # no module owns it — must render always
        ("/map/",      "geography"),
        ("/recharge/", "recharge"),
        ...
    )

That filter is what lets a module join the gate by flag alone. Before it existed,
`/recharge/` was demanded unconditionally — so the moment `recharge` became
optional, the harness would have insisted a dropped module's own page return 200.

The owner is **declared, not derived from `url_prefix`**. Prefix matching happens
to work today (every prefix in `core/modules.py` is unique), but it holds by luck
rather than by construction — it breaks silently the day two modules share a
prefix or a module serves a page outside its own. One declared line per page
cannot mis-attribute.

**To add a page: append a row.** Never edit the test logic below the table.

## Three database states, and the vocabulary gate wants the empty one

Until Plan 90-01 this harness rendered every page against an **empty** database.
That is not a detail. 89-03 pointed a reduced module set at a copy of the real
demo database and found **eight live HTTP 500s** three phases of green gates had
missed: a CalWATRS `ReportSubmission` row outlives the `surface` module, and
`reporting/views.py` branches on the report *type* rather than on whether the
module is there. No row, no crash, no finding (ISS-091).

So the harness now runs on **two fixtures, deliberately**, and which one an
assertion gets is a decision rather than an accident:

| Assertion family | Fixture | Why that one |
|---|---|---|
| Route / 404 / nav-link / render (`test_kept_page_renders_on_a_populated_instance`, the list- and detail-page cases) | **seeded** — `seed_droppable_fixture()` | A code path that only runs when a row exists is the path nothing had ever executed. |
| The pristine and configured-but-empty render cases | **empty** | Their subject *is* the empty state — the two branches of `_empty_onboarding.html`. Seeding them deletes the case rather than strengthening it. |
| Vocabulary (`test_kept_pages_never_name_a_dropped_module`, its anonymous twin, and the hidden-explainer gate) | **empty** | Reads page prose. On a populated database it would fire on text that is CORRECT — see below. |

**The vocabulary gate runs empty on purpose, and the reasons are recorded in
code.** `checks.py::_DATA_DEPENDENT_TEXT_OUT_OF_SCOPE` carries two pages where a
populated pass would fail on true sentences: `/drinking/`'s "Well" column header,
which the design deliberately keeps with `wells` demoted, and `/health/`'s "Not
applicable — needs the 'parcels' module", whose entire job is to name the absent
module. A gate that cried wolf there would get weakened, and a weakened
`_FORBIDDEN_VOCABULARY` is the failure that file's own comment warns about.
`test_the_fixture_axis_is_what_we_think` fails if seeding ever leaks into the
vocabulary tier, so the split cannot quietly collapse into one.

`tests/droppability/fixture.py` seeds **one row per surviving domain** — a
`Boundary` so `needs_setup` is False, one row behind each kept list page, and one
CalWATRS submission when `reporting` and `accounting` both survive. It asks
`core.modules.is_enabled` per block rather than carrying a module list, makes
**zero network calls**, and uses fixed dates and explicit identifiers so two runs
produce the same rows. It runs 12 times per `make test-droppable`; that is why it
is a small purpose-built fixture and not the demo data.

**The real demo database is a second, separate tier** — Plan 90-03's staging
gate. `seed_merced` reaches external APIs, so a gate built on it would depend on
the network. Reading a green run here: it proves a reduced deployment survives
*a* row in every domain, not that it survives *Merced's* rows.

## It follows the links now, not just the declared pages

`_PAGES` is a list of front doors. Until Plan 90-02 the harness opened those
doors and inspected the sidebar's `href`s for dead links — but it never *walked
through* one. That is the reach half of ISS-091, and it is not academic: the two
views that crashed on staging sit **two hops** past a declared page
(`/reporting/reports/` → `report_detail` → `calwatrs_worksheet` /
`report_prefill`). No one-hop check could ever have reached them.

`tests/droppability/crawl.py` walks the app the way a person clicking through it
does. From every `KEPT_PAGES` seed it follows each in-app `<a href>`, then every
link on those pages, to **frontier exhaustion** — a `seen` set and a queue, not a
depth limit, because "depth 2" would stop being right the day a view moves one
link further out.

Measured on a full 16-module deployment with the 90-01 fixture (2026-07-22): 33
seeds reach **59 paths**, all 200, in about 0.6 s. Two consecutive runs visit the
same set — the queue drains in sorted order precisely so that stays true.

**What it deliberately does not open**, each row carrying its reason in
`crawl.py`'s `SKIPPED_*` tables:

| Skipped | Why |
|---|---|
| `/admin/` | Django's own admin renders from `ModelAdmin`, not these templates — and its delete confirmations sit one form-post from the fixture the rest of the crawl is reading. |
| `/accounts/logout/` | Ends the crawl's own session. Every later page becomes a redirect to the login wall, and the run still finishes green having proved nothing. |
| `/nav-mode/` | Sets the `nav_mode` cookie and bounces back. Since the crawl drops query strings, a bare GET defaults it to `operations` — silently flipping the client out of the mode the test chose, about a third of the way through. Nothing fails; the two-mode parametrization just stops meaning anything. |
| `*/export/`, `*/download/`, `*/template/` | Stream bytes rather than render a template, so they answer nothing about whether a page renders. |

**Two stated limits.** The crawl is GET-only — it never issues a POST, so a form
is proven to render and not to submit. And it dedupes by path, so query strings
collapse: `/accounting/ledger/?period=3` and `/accounting/ledger/` are one visit.
One view in this codebase genuinely branches on its query
(`reporting.views.report_generate` reads `?type=`), so that branch is crawled in
one of its two shapes. Widening to capped query variants is a real option; it was
not taken because the bar this feeds is zero 5xx and the collapsed shape reaches
every view.

**The bound is printed, never silent.** `crawl()` takes `max_pages` (default 400)
and returns the unvisited remainder alongside the visited set — and prints it. A
crawl that stopped early must never read like a crawl that finished; that is the
same failure shape as the empty database this phase exists to fix.

`crawl()` **returns rather than asserts**, so the assertion can live in
`checks.py` and the function stays reusable — Plan 90-03 points it at a copy of
the real demo database, where the bar is the same and the fixture is not.

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

## Adding a module to the gate (Phases 87-89)

To bring a newly decoupled module under this harness, flip `required=False` in
`core/modules.py` — and, if it is being demoted rather than removed,
`schema_resident=True` alongside it. The harness reads `OPTIONAL_MODULE_NAMES`
and `spec.schema_resident` and picks the module up with no edit to any assertion
here. If it owns a page the gate does not yet cover, append one row to `_PAGES`
with the module as its owner. That is the whole extension point.

**Two registry pins have to move with the flag, not one.**
`tests/test_modules.py::TestDroppabilityPromise` and
`tests/test_module_template_guards.py::test_optional_module_names_is_what_we_think`
both hold the droppable set. Phase 82 updated only the first and the second went
red on the flip.

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
