<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Contributing to OpenH2O

Thanks for your interest. OpenH2O exists to put a capable water-data management platform within reach of every California agency, and contributions — from bug reports to new data adapters — move that forward.

## License of contributions

OpenH2O is licensed under **AGPL-3.0-or-later**. By submitting a contribution you agree it is licensed under the same terms. If you run a modified version as a network service, the AGPL requires you to offer your users its source — keep the in-app "Source code" link pointing at your published fork (see [NOTICE](NOTICE)).

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

See [CLAUDE.md](CLAUDE.md) for an orientation to the codebase and [DEPLOY.md](DEPLOY.md) for production deployment.

## Ground rules

- **Add tests.** Anything with logic — a model method, a view, a data adapter, a report generator — needs a test in [tests/](tests/). We use pytest + factory_boy.
- **Run the suite before opening a PR:** `make test`. It's pinned to local settings; production settings refuse to boot without a strong DB password by design.
- **Keep the standards gate green.** If you touch the data model or an adapter, run `python manage.py check_conformance` and update the crosswalk if needed (see [docs/DATA-STANDARDS.md](docs/DATA-STANDARDS.md)).
- **Match the stack's constraints.** No Node.js build step, no Celery/Redis, single-tenant. These are deliberate — see the "Key Constraints" section of [CLAUDE.md](CLAUDE.md).
- **One typeface, the design tokens.** UI work uses the tokens in `static/css/tokens.css`; don't introduce new fonts or ad-hoc colors.
- **Every new source file** gets the SPDX header: `# SPDX-License-Identifier: AGPL-3.0-or-later`.

## Adding a data adapter

New external sources are the most common contribution. An adapter lives in `datasync/adapters/`, exposes a `PARAMETER_MAP`, and registers itself. Then map its native codes to canonical concepts in `standards/management/commands/seed_observed_properties.py` (the `CODE_TO_KEY` table) so the crosswalk and conformance gate stay complete. A regression test enforces that every adapter code resolves to an observed property.

## Reporting bugs and ideas

**Open a GitHub issue** with what you expected, what happened, and (for bugs) the steps to reproduce. That's the path that always works.

Some deployments — including the hosted demo — also turn on the **in-app feedback widget**, the blue "Send feedback" bar docked at the bottom of every page. Where it's enabled, it's the quickest route: pick a category (bug, idea, question, or "data looks wrong"), write what happened, and optionally attach a screenshot (click, drag, or paste one in). It quietly captures useful diagnostics — the page URL, your browser, any JavaScript errors, and the build version — so you don't have to. Reports land in that instance's own database; a maintained deployment also forwards them to a triage pipeline. Name and email are optional and only used to reply. (It's off by default; an operator turns it on with `FEEDBACK_ENABLED=True`.)

For security-sensitive reports, please contact the maintainer privately rather than opening a public issue.
