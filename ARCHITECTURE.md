<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# How the OpenH2O code fits together

This page is for a programmer opening the repository for the first time. It names the files to
open for each part of the system. For what the product does and who it is for, read
[README.md](README.md); to install it, read [DEPLOY.md](DEPLOY.md).

## What OpenH2O is

OpenH2O is a Django 5 application on PostgreSQL with PostGIS. One site keeps the water records of
one organization: measurements, deliveries, wells, surface diversions, recharge and drinking-water
results, plus the water accounting that turns those records into a monthly balance per field and
per account. It runs in Docker Compose (`docker-compose.yml`): a `web` container (Gunicorn), a
`db` container (PostGIS) and a `caddy` container in front.

## Limits of the stack

- **No Node.js build step.** Tailwind CSS is compiled by its standalone binary while the image
  builds (`Dockerfile`), and htmx and MapLibre load from a CDN, so building the site needs only
  Docker.
- **No background job queue (such as Celery) and no Redis.** The platform is designed for a small
  server with 2 to 4 GB of memory (`config/settings/base.py`). Work longer than a request, such as
  the calculation, runs as its own `manage.py` process (see "The calculation" below), and
  scheduled work runs from cron (`crontab.txt`, installed by `make install-cron`).
- **Caddy in front** (`Caddyfile`). It answers at the address in `OPENH2O_SITE_ADDRESS` from `.env`.
  Unset, that is port 80 at any address over plain HTTP, for a site reached only from this computer or
  the office network, or one behind a service that handles the HTTPS (a tunnel, for example); a bare
  domain gets Caddy's own certificate. The
  `Caddyfile` itself is not edited.
- **One organization per site.** Each organization runs its own copy, so there is no tenant
  model; the site-wide settings are one `SiteConfig` row (`core/models.py`).
- **`AUTH_USER_MODEL` is `core.User`** (`config/settings/base.py`).

## How a request is served

1. `config/urls.py` holds the site-wide routes (admin, sign-in, help and about pages, search) and
   adds each switched-on module's routes from `core/modules.py` (`url_specs_for`).
2. Each app's `urls.py` maps a path to a view. The two apps with the most view code keep one
   view module per screen: `accounting/views/` (dashboard, ledger, periods, allocations, accounts,
   calculation_runs, settings_pages) and `drinking/views/` (overview, facilities, sampling_points,
   results, lab_import, onboard, production, schedule). Each package's `common.py` holds helpers two
   or more of its screens share (the Methodology Settings module also borrows two from
   `calculation_runs.py`). `accounting/urls.py` names every view by its module, so
   `periods.period_detail` is in `accounting/views/periods.py`.
3. A view gathers rows from the models, often through the app's `services.py`, and renders a
   template from `templates/<app>/`.
4. Lists, filters and forms update in place with htmx (`django_htmx` in
   `config/settings/base.py`). Some views check the `HX-Request` header and return only the part
   of the page that changes; others exist only to answer htmx requests and always return a part.
   Those parts are templates whose names start with an underscore, under
   `templates/<app>/partials/` and `templates/partials/` (which also hold plain includes).
5. Styling comes from `static/css/tokens.css` (the colour and spacing tokens), `static/css/app.css`
   (the shared components) and Tailwind, compiled from `static/css/input.css` while the image
   builds. htmx loads from a CDN in `templates/base.html`; each page with a map loads MapLibre from
   a CDN in its own template. `DESIGN.md` is the design system.

## Apps and modules

Each water domain is a Django app, and each app belongs to a module in the registry in
`core/modules.py` (`MODULE_REGISTRY`). A site runs the domains it has:

- `core`, `geography`, `measurements` and `standards` are always present.
- `parcels`, `accounting`, `wells`, `datasync`, `surface`, `recharge`, `health`, `setup`,
  `infrastructure`, `feedback`, `drinking` and `reporting` are optional. `reporting` is off unless
  a site names it.

The environment variable `OPENH2O_MODULES` lists the modules a site runs (`all` runs every one;
unset runs every one except `reporting`). `config/settings/base.py` reads it, and
`core/modules.py` turns it into `INSTALLED_APPS`, the URL list and the sidebar. A switched-off
module's routes are never registered, so they return 404. An unknown name, a missing required
module or an unmet dependency stops the site at startup with `ImproperlyConfigured`.

A module that every site has should hold no database reference (foreign key, one-to-one,
many-to-many or migration dependency) into an optional one, and every dependency between modules
should be declared in the module's `requires` tuple. `tests/test_composition_rule.py` reads every
reference between modules (field references from Django's app registry, migration dependencies
from the migration files) and fails on one that is neither declared
nor recorded as an exception, and on an exception record that no longer matches the code. The
exceptions are the ten records in `SCHEMA_EXCEPTIONS` in `core/modules.py`, each with its reason.
`tests/test_modules.py` checks that the always-present modules require no optional one.

Because of those references, `parcels`, `accounting`, `wells` and `datasync` are
`schema_resident`: switched off, they stay installed with their tables empty and show nothing.
`parcels` and `accounting` require each other, so they are on or off together. The other optional
modules leave `INSTALLED_APPS` when switched off, so most code outside such a module imports its
models inside the function that uses them. Imports of a schema-resident module's models can sit at the
top of a file, because those apps stay installed (`core/modules.py` explains this).

`make test-droppable` runs `tests/test_droppability_acceptance.py`: it boots the site once for
each optional module left out together with every module that requires it (`parcels` and
`accounting` share one case, because each requires the other) and once with every optional
module left out, and checks that the remaining pages render, the dropped routes return
404 and the sidebar has no dead links (`tests/droppability/README.md`).

## The calculation

The calculation turns each field's crop water use (evapotranspiration), rain, deliveries and well
records into a month's ledger.

- **What starts it.** Four things queue a calculation: the nightly cron job in `crontab.txt`
  (`manage.py run_accounting --open-periods --trigger schedule`); the Calculate button on a
  reporting period's page (`accounting/views/periods.py`, `period_calculate`), which queues
  nothing while one for that period is already waiting or running; saving ledger entries,
  surface records or a well's meter reading (`accounting/views/ledger.py`, `surface/views.py`,
  `wells/views.py`, through `engine_run.request_for_months`); and `run_accounting` run by hand. Each creates a
  `CalculationRequest` (`accounting/models.py`), and the queue in `accounting/engine_run.py`
  (`run_queue`) takes a database lock so one calculation runs at a time. A screen starts
  `run_accounting --request <pk>` as its own process (`start_calculation`), so the request returns
  at once.
- **One month.** `engine_run.run_month` runs in one transaction. It runs the per-field
  calculation; with the `surface` module on, it then deletes any diversion record of the retired
  crop-need estimate left in that month, divides each point of diversion's water among the fields it
  serves (`surface/services.py`), stores what is left after canal losses at a point that serves no
  field as `CanalMonthLoss.unserved_af`, credited to no one, and runs the per-field calculation again
  with the divided water. A diversion record counts in its month whatever day it is dated.
- **One field.** `accounting/management/commands/run_calculations.py` runs the methodology chain
  for each field through `accounting/calculation.py` (`evaluate_chain`). The steps are functions
  registered in `accounting/steps.py` (`STEP_REGISTRY`): gross crop water use (0 on a field marked
  fallow), less effective rain, less surface water, and a floor at zero. A retired facility-only
  step stays registered so that a plan saved before it was retired still runs; it changes
  nothing. Which steps run and in what order is data: `CalculationPlan` and `CalculationStep` rows in `accounting/models.py`. The
  Methodology Settings page (`accounting/views/settings_pages.py`) turns steps on and off,
  reorders them and edits the settings of two of them (effective rain and the floor). On a
  site with no active plan it gives an administrator a button that loads the default plan
  (`methodology_load_default`, which runs `seed_calculation_plan`).
- **What it writes.** A `CalculationRun` per field-month (with each step's result), calculated
  `ParcelLedger` rows, each field's share of a well's meter readings as a meter ledger row, the canal and delivery tables in `surface/` (with `surface` on), and the
  request's status and notes. Re-running a month that an older version credited removes that
  month's recharge ledger row and takes back its basin pool deposit. When Delivery Settings credit
  canal seepage to a water account, the canal division also writes `AccountCredit` rows
  (`surface/services.py`, `_store_seepage_credits`). With the `health` module on, a Site Health result is stored afterwards
  (`health/checks.py`, `check_calculation`).
- **Settings it reads.** Site-wide choices sit on the one `SiteConfig` row (`core/models.py`). For
  example `over_delivery_treatment` says what happens to surface water beyond the crop's use (by
  default it is recorded on the run and credited to no account); it is read in
  `run_calculations.py` and edited on the Delivery Settings page when `surface` is on.
  `water_year_start_month` (default 10) decides which water year every month belongs to; Python reads
  it through `core/water_year.py`, and the finalized-year lock reads the same column in SQL
  (`accounting/locks.py`).

- **Effective rain.** The default USDA-SCS method (`accounting/precip_math.py`) works in
  millimetres. With P the month's rain, ET the month's crop water use and D the soil storage in
  inches (3.0 by default), SF = 0.531747 + 0.295164 D - 0.057697 D^2 + 0.003804 D^3 and effective
  rain = SF x (1.25 x P^0.824 - 2.93) x 10^(0.000955 x ET), with P^0.824 taken as 0 when P is 0,
  evaluated in ordinary binary floating point. It is capped at the smaller of P and ET, floored at
  0, and converted to acre-feet over the field's area.
- **Rounding.** Every acre-foot figure the ledger and the runs store is quantized to four decimal places with
  Python's default `Decimal` context, which rounds half to even (2.50285 is stored as 2.5028).
  Irrigation efficiencies are stored to three places.
  Pages that print two places round half up, which changes only the printed figure.
- **Order of rounding on a run.** The chain carries gross crop water use and effective rain
  unrounded. `subtract_surface_water` (`accounting/steps.py`) rounds the canal water counted once,
  as the delivery times the field's efficiency, and, when it subtracted canal water, sets the running figure to 0 when it
  is not 0 but within 0.0001 of 0. `run_calculations.py` then stores each figure rounded on its
  own: gross, effective rain, net use (stored gross minus stored rain), the final figure, the
  groundwater extraction (the stored final figure divided by efficiency), deep percolation (the
  extraction minus the stored final figure), over-delivery and unmet demand. The stored surface
  water is the delivery times efficiency in full, even where it exceeds the crop's need. A month
  with no canal water has its delivery stored as 0.0000 (not blank) and a blank efficiency.
- **How a headgate's water is divided.** The point's `division_method` picks the rule
  (`surface/services.py`, `_split_record`). The default divides by the shares entered
  (`apportion_shared_supply` in `accounting/allocation_math.py`): when any field still to be divided among (those without their own recorded delivery) has a share other than the default 1.0, the shares are the weights, otherwise it divides by acreage, and
  evenly where no field has an acreage. Each weight is rounded to four places and the
  rounding difference goes to the field whose key sorts last as text; each field's amount is the
  water times its rounded weight, rounded to four places, and the last field takes what is left
  of the water. The other choice, crop need, caps each field at its need divided by its
  efficiency (rounded to four places); the water fills the caps when it covers them all, and
  otherwise is shared by need with any field that would pass its cap held at it and the rest
  re-shared, repeated until none passes (`allocate_by_demand`). In a month when no such field has a need, crop need divides by the shares rule. After rounding, the difference
  goes to the field with the most room below its cap, ties to the key that sorts last as
  text, spilling to the next when one field cannot take it all. A remainder of 0 writes no rows.
- **Where a divided row sits.** A divided row, like an undivided one, carries the diversion
  record's own date and its reporting period.

## Change history

Every tracked model is decorated with `track_changes` from `core/history.py`, which installs
django-pghistory database triggers, so a change is recorded whichever way it was written: a form
save, `bulk_create`, `QuerySet.update()`, the admin, a management command or raw SQL. Geometry
columns and `updated_at` are not copied into history. Who made a change comes from context: `pghistory.middleware.HistoryMiddleware`
(`config/settings/base.py`) records the signed-in user for a web request, `command_context()` in
`core/history.py` names the management command (except the few in `UNATTRIBUTED_COMMANDS`, such
as `migrate`), and `change_note()` adds a reason. The Change history page (`/changes/`,
`core/views.py` `change_history`) reads the records back through `core/changes.py`.

**Nothing is pruned, and the event tables are append-only.** `track_changes` passes `append_only=True`
to `pghistory.track`, which puts a pgtrigger `Protect` trigger named `append_only` on every event
table. It refuses every `UPDATE` and `DELETE` that runs with the trigger in force, whether from a form,
the shell, `/admin/` or raw SQL. Code that names the trigger in `pgtrigger.ignore`, a SQL session
that sets `pgtrigger.ignore`, or the owner of the tables can still get past it. Inserts are
untouched, so recording is unchanged. A new tracked model is locked once its migration is made and
applied; there is no list to keep. `TRUNCATE` does not fire a row trigger, so
`clear_change_history --golden-build` (which refuses to run without that flag) still empties the
tables for the demonstration's golden build.

`pghistory_context`, the table that says who made a change, is not locked: pghistory updates a
context row when a nested context adds metadata (`change_note`), so a lock would refuse the note.
Anyone who can write to the database can still change who a change is attributed to.

The demonstration is the one door through the lock. `forget_events` in `core/demonstration.py` deletes
the changes its own load or removal wrote, inside `pgtrigger.ignore(*history_lock_uris())` (the URIs
are built from the registered event models, so none is typed by hand). The history context stays
outside the ignore, as in `accounting/locks.py` `override` (django-pghistory issue #237), and the
context row's delete stays outside it because that table has no lock. Nothing else gets this door.

A tracked field with no `verbose_name` prints the name Django makes from the field's name in Change history
("Gross et af"). Give such a field a `verbose_name` in the words a page uses for the same figure;
`tests/test_change_labels_07.py` fails for a tracked field that has neither a written label nor a place
on its list of labels that already read as plain words.

## Data sources

External data (stream gauges, weather stations, groundwater levels, satellite evapotranspiration)
arrives through adapters in `datasync/adapters/`. Each adapter subclasses `BaseAdapter`
(`datasync/adapters/base.py`), directly or through another adapter, which requires `fetch`,
`parse`, `validate` and `discover_stations`, and registers itself with `register_adapter`
(`datasync/adapters/__init__.py`). Most also define a `PARAMETER_MAP` naming their measurements;
the two OpenET adapters do not. `manage.py sync_source` runs one source; `scripts/run-sync.sh` is
what the sync cron jobs call. To add a source, follow "Adding a data adapter" in
[CONTRIBUTING.md](CONTRIBUTING.md).

## Maps

Eight list pages draw a map of the records the list shows. Six overview-map partials draw seven
of them, for example `templates/surface/partials/_pods_overview_map.html` for diversion points
(the drinking-water partial serves both the facilities and the sampling points pages), and the
station list uses `templates/datasync/partials/_freshness_map.html`. The shared drawing code is
`static/js/map-core.js` (the `OH2O` object: colours, layer paint, `OH2O.addDetailLabel`,
`OH2O.followResults`).

On the diversion points page, the view puts the primary keys of the whole filtered list (before
paging) in the context as `result_pks`; the results partial writes them into the page with
`json_script`; the map partial fetches every point once from the app's GeoJSON view and calls
`OH2O.followResults`, which filters the layers to those keys and runs again each time htmx swaps
the results block. The filtering happens in the browser. The other list maps work the same way,
except that the sampling points map shows the facilities behind the listed points.

The partials stay separate files: each keeps its own data source and popup. The count line and
key above seven of the maps come from the shared `templates/partials/_map_card_head.html`; the
station list has its own, `templates/datasync/partials/_stations_map_card_head.html`.

## Tests

The suite is pytest with pytest-django and factory_boy, in `tests/` (`tests/factories.py`,
`tests/fixtures/`, `tests/golden/`).

- **Whole suite:** `make test`. It runs every module (`OPENH2O_MODULES=all`) with
  `--ds=config.settings.local`, because the production settings refuse to start with a known
  default database password or an empty `ALLOWED_HOSTS` (`config/settings/production.py`).
- **One file:** `docker compose exec -e OPENH2O_MODULES=all web python -m pytest tests/test_name.py --ds=config.settings.local`.
- **Before a commit or pull request:** `make test` and `ruff check .` both pass. On every push to
  `main` and every pull request, `.github/workflows/tests.yml` runs `ruff check .` (ruff pinned to
  0.16.10) and the pytest suite without the tests marked `network`;
  `.github/workflows/clean-install.yml` checks that no migration is missing, that a fresh install
  migrates and seeds with no demonstration content, and that the Merced seed sequence (`seed_merced`, one
  step of `load_demonstration`) names no real organization.
- **The image has no source mount.** The `web` image copies the code when it is built, so after
  adding or changing a file run `docker compose up -d --build web` before testing.
  `scripts/assert-image-fresh.sh`, which `make test` runs first, compares the container with
  the files the image is built from, tracked or not yet tracked, of nine types (Python, templates and
  data files), so it cannot see an edited JavaScript, CSS or Markdown file.

Some tests check the code and the documents themselves rather than running the site:

- `tests/test_composition_rule.py` and `tests/test_modules.py`: the module rules above.
- `tests/test_template_hygiene.py`: the mechanical parts of `DESIGN.md`.
- `tests/test_domain_vocabulary.py`: screens explain the software, not the water. It counts the
  on-screen sentences that match its pattern for defining a water term and fails when a screen's
  count rises above the one recorded for it.
- `tests/test_writing_shapes.py` and `tests/test_screen_text_shapes.py`: counts of sentence shapes
  that may only go down.
- `tests/document_sources.toml` with `tests/test_document_sources.py` and
  `tests/test_guide_names.py`: each section of the guides and help pages lists the code its
  sentences rest on; the commands, `make` targets and settings a guide writes in code formatting,
  and the labels the sources file lists, must exist. `scripts/guide_reread.py` lists the sections
  whose code changed since they were last read.
- `tests/test_no_planning_references.py`: no issue, phase or plan numbers, planning record names
  or review-row tags in the product code, its configuration files and the programmer documents
  (`tests/` and the migrations are not scanned).

## Adding a page

For a new page in the accounting app, as an example:

1. The view, in the module for its screen under `accounting/views/` (or a new module there).
2. The route, in `accounting/urls.py`.
3. The template, in `templates/accounting/`, and any htmx part in `templates/accounting/partials/`.
4. A sidebar link, if it needs one: a `NavEntry` in the module's entry in `core/modules.py`. If the
   page opens a write flow, give the entry `writes=True` so a viewer's sidebar leaves it out.
   `tests/test_modules.py` pins the number of module sidebar links, so that count changes too.
5. A test in `tests/`.
6. If the page's URL name contains `import` or `onboard`, the "Option B" section of
   `docs/AI-OPERATOR-GUIDE.md` must name its path:
   `tests/test_ai_operator_guide_names_every_door.py` fails until it does.

## Where decisions are written

In the product code, the reason for a piece of code is in the comment beside it; comments under
`tests/` can still cite the maintainer's private planning record. The design rules and the reasons
for them are in `DESIGN.md`; the user-facing guides are in `docs/` and the help pages in
`templates/help/`. `CLAUDE.md` is the file AI coding tools read: the stack, the design tokens, the
module composition rule and the commands. The maintainer keeps a private planning record outside
the repository; nothing in the code reads it.
