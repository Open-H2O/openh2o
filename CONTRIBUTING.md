<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Contributing to OpenH2O

Thanks for your interest. OpenH2O exists to put capable water-records software within reach of anyone who keeps water records. Every contribution, from a bug report to a new data adapter, moves that forward.

## License of contributions

OpenH2O is licensed under **AGPL-3.0-or-later**, and by submitting a contribution you agree to license it under the same terms. If you run a modified version as a network service, the AGPL requires you to offer its source to your users. Point the in-app "Source code" link at your published source (see [NOTICE](NOTICE)).

## Getting set up

```bash
git clone https://github.com/Open-H2O/openh2o.git
cd openh2o
cp .env.example .env        # set SECRET_KEY, and DJANGO_SETTINGS_MODULE=config.settings.local for dev
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_data
make test                   # confirm a green baseline
```

[ARCHITECTURE.md](ARCHITECTURE.md) explains how the code fits together, and [DEPLOY.md](DEPLOY.md) covers production deployment. [CLAUDE.md](CLAUDE.md) is the file AI coding tools read.

## Ground rules

- **Add tests.** Anything with logic needs a test in [tests/](tests/): a model method, a view, a data adapter or a report generator. The tests use pytest and factory_boy.
- **Write commit messages for the public change log.** After a type prefix such as `feat:` or `fix:`, say what changed and why. Leave out people's names and outside issue, plan, phase or decision numbers (`ISS-443`): they point to the maintainer's private planning record, which outsiders cannot open. Older commits keep them because history is not rewritten; don't copy them. Dates, hashes, file and test names and this repository's issues and pull requests (`#123`) are fine. Keep the two lines the release check reads, with plain reasons. The release check asks for a `Test-Change: <test file or folder>: <reason>` line for each older test file that changed since the release. You don't need to work these out: the pre-push hook prints every such line a push needs. The release check asks for a `Fix-Test: <commit>: <reason>` line when a commit it treats as a fix comes with a test that already passes before the fix. Its log prints the line to add. Run `make hooks` once after cloning to install two hooks. The commit-msg hook prints refused lines and reasons: rewrite and commit again. Passed commits can still fail the pre-push hook if a `Test-Change:` line is missing: add the lines it prints in a new commit. The pre-push hook does not refuse a push for a missing `Fix-Test:` line.

  ```
  fix: report generator drops the last day of a date range

  The end date was treated as exclusive. It is now included.
  ```
- **Run `make test` and `ruff check .` before you open a pull request.** `make test` uses the local settings, because under the production settings OpenH2O will not start with an empty ALLOWED_HOSTS or a database password that is empty, `openh2o`, `postgres`, `password` or `changeme`.
- **Run one test without rebuilding the image.** `make dev-up` starts the stack with `docker-compose.dev.yml`, so the web container runs the code in your folder and an edit takes effect at once. `make test T=tests/test_example.py` then runs one file or one test; without `T` it runs all of `tests/`. `make golden-update T=tests/test_nav_golden.py` rewrites the golden files of the tests you name. Golden files are the files under `tests/golden/` that hold the expected rendered HTML of the sidebar and of the dashboard's main area. Run it only when a change to the page is intended. Without `make dev-up`, `make test` first checks that the image holds your current code, and `make golden-update` copies `tests/golden` out of the container to your folder. The deploy scripts do not read `docker-compose.dev.yml`.
- **When a wording test fails, read its failure message.** Several tests guard the words on screens, and this bullet describes three of them. `tests/test_domain_vocabulary.py` fails when a screen explains a water term, because screens explain the software, never the water. `tests/test_writing_shapes.py` fails when a screen file or a public guide gains one of the sentence shapes listed in `scripts/writing_shapes.py`. The public guides include README.md, CONTRIBUTING.md, SECURITY.md and the guides in `docs/`. `tests/test_wording_tests_need_approval.py` fails when a new test checks only exact sentences, unless the sentence is approved default wording or is not wording a person reads. Approved wording is marked in the test that checks it ("Default wording, approved by the maintainer on <date>"). To change that wording, update the test in the same commit, because the test fails until it matches the new words.
- **Keep the standards check passing.** If you change the data model or an adapter, run `python manage.py check_conformance` and update the crosswalk if it reports a gap (see [docs/DATA-STANDARDS.md](docs/DATA-STANDARDS.md)).
- **Keep to the stack's limits.** OpenH2O has no Node.js build step, does not use Celery or Redis, and serves one organization per site. The reasons are under "Limits of the stack" in [ARCHITECTURE.md](ARCHITECTURE.md).
- **Use the design tokens.** Interface work uses the one typeface and the tokens in `static/css/tokens.css`. Do not add new fonts or one-off colors.
- **Give every new source file the SPDX header:** `# SPDX-License-Identifier: AGPL-3.0-or-later`.

## Adding a data adapter

New external data sources are the most common contribution. An adapter lives in `datasync/adapters/` and registers itself. An adapter that reports named measurements also defines a `PARAMETER_MAP` and goes on the list of sources in `datasync/adapters/registry.py`, where the crosswalk and its test find it. The OpenET adapters do not report named measurements. The field-list adapter in `openet_fields.py` does not call `register_adapter`, because `sync_openet_parcels` calls `datasync/field_list.py` directly. Then map the source's own codes to OpenH2O's measured quantities in the `CODE_TO_KEY` table in `standards/management/commands/seed_observed_properties.py`, which keeps the crosswalk and the conformance check complete. A test checks that every adapter code maps to an observed property. When a source publishes more than one daily statistic for a code, give each parsed record its `statistic_id`, as `datasync/adapters/usgs.py` does: OpenH2O keeps one reading per station, code, statistic and time, so when two readings at the same station, code and time both lack a `statistic_id`, it keeps only the first.

## Reporting bugs and ideas

**Open a GitHub issue** with what you expected, what happened and, for a bug, the steps to reproduce it. A GitHub issue always reaches the maintainer.

Some sites, including the hosted demo, also turn on the in-app feedback form. Its "Send feedback" link sits at the foot of the menu on every page. Choose a category (bug, idea, question or "data looks wrong"), describe what happened, and attach a screenshot if it helps. The form also records the page address, your browser, any JavaScript errors and the version running. Reports are stored in that site's own database, and a maintained site can forward them to a triage service. Name and email are optional and are used only to reply. The form is off by default, and a site's operator turns it on with `FEEDBACK_ENABLED=True`.

Report a security problem privately, as [SECURITY.md](SECURITY.md) describes, not in a public issue.
