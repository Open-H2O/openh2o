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

[CLAUDE.md](CLAUDE.md) gives an orientation to the codebase, and [DEPLOY.md](DEPLOY.md) covers production deployment.

## Ground rules

- **Add tests.** Anything with logic needs a test in [tests/](tests/): a model method, a view, a data adapter or a report generator. The tests use pytest and factory_boy.
- **Run the suite with `make test` before you open a pull request.** It uses the local settings, because the production settings refuse to start without a strong database password.
- **Keep the standards check passing.** If you change the data model or an adapter, run `python manage.py check_conformance` and update the crosswalk if it reports a gap (see [docs/DATA-STANDARDS.md](docs/DATA-STANDARDS.md)).
- **Keep to the stack's limits.** OpenH2O has no Node.js build step, does not use Celery or Redis, and serves one organization per site. The "Key Constraints" section of [CLAUDE.md](CLAUDE.md) gives the reasons.
- **Use the design tokens.** Interface work uses the one typeface and the tokens in `static/css/tokens.css`. Add no new fonts or one-off colors.
- **Give every new source file the SPDX header:** `# SPDX-License-Identifier: AGPL-3.0-or-later`.

## Adding a data adapter

New external data sources are the most common contribution. An adapter lives in `datasync/adapters/`, defines a `PARAMETER_MAP` and registers itself. Then map the source's own codes to OpenH2O's measured quantities in the `CODE_TO_KEY` table in `standards/management/commands/seed_observed_properties.py`, which keeps the crosswalk and the conformance check complete. A test checks that every adapter code maps to an observed property.

## Reporting bugs and ideas

**Open a GitHub issue** with what you expected, what happened and, for a bug, the steps to reproduce it. A GitHub issue always reaches the maintainer.

Some sites, including the hosted demo, also turn on the in-app feedback form. Its "Send feedback" link sits at the foot of the menu on every page. Choose a category (bug, idea, question or "data looks wrong"), describe what happened, and attach a screenshot if it helps. The form also records the page address, your browser, any JavaScript errors and the version running. Reports are stored in that site's own database, and a maintained site can forward them to a triage service. Name and email are optional and are used only to reply. The form is off by default, and a site's operator turns it on with `FEEDBACK_ENABLED=True`.

Report a security problem privately, as [SECURITY.md](SECURITY.md) describes, not in a public issue.
