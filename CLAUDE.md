# Open Water Accounting Platform

## Project Overview

A water-data management platform for California Groundwater Sustainability Agencies (GSAs) and water districts. It manages an agency's water data — measurements, deliveries, wells, surface diversions, mixed-use accounting, and managed aquifer recharge. When an agency files with the state, it can generate the data for the required reports (GEARS CSV, CalWATRS CSV); reporting is an optional feature, not the platform's purpose.

The core goal is to lower the cost and access barrier for under-resourced agencies. A poorly-funded agency can point a frontier AI subscription at this repo and a $15/mo VPS and have the AI stand the platform up — and an engineering firm or consultant can run it just as well. Self-deployment is meant to be a real option, not a vendor contract by default.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | Django 5.x with GeoDjango |
| Database | PostgreSQL 16 + PostGIS 3.4 |
| Web Server | Gunicorn (2 workers) |
| Reverse Proxy | Caddy (auto-HTTPS) |
| Frontend | HTMX (CDN), Tailwind CSS (standalone binary) |
| Maps | MapLibre GL JS (CDN, added in Phase 3) |
| Static Files | WhiteNoise |
| Containerization | Docker Compose |
| Design System | VanderDev (tokens.css, OKLCH color ramps) |

## Project Structure

```
openh2o/
├── config/                  # Django project package
│   ├── settings/
│   │   ├── base.py          # Shared settings
│   │   ├── local.py         # Development (DEBUG=True)
│   │   └── production.py    # Production (SECURE_*)
│   ├── urls.py              # URL routing
│   ├── views.py             # Root views
│   ├── wsgi.py
│   └── asgi.py
├── core/                    # Core app (User model, seed commands)
│   ├── management/commands/
│   │   ├── seed_data.py     # Runs all seed commands
│   │   ├── seed_merced.py    # Full Merced Subbasin demonstration (the live demo)
│   │   └── seed_roles.py
│   ├── apps.py
│   └── models.py
├── static/
│   └── css/
│       ├── tokens.css       # VanderDev design tokens
│       └── input.css        # Tailwind input with base styles
├── templates/
│   ├── base.html            # Layout shell (HTMX, fonts, CSS)
│   └── index.html           # Landing page
├── scripts/
│   └── build-css.sh         # Tailwind standalone compiler
├── Dockerfile
├── docker-compose.yml
├── Caddyfile
├── pyproject.toml
├── tailwind.config.js
├── manage.py
├── Makefile                 # Development shortcuts (make help)
├── README.md                # Project overview and quick start
├── DEPLOY.md                # Deployment guide (13 sections)
└── CLAUDE.md                # This file
```

> **Deploying this platform with an AI agent?** Start with
> [docs/AI-OPERATOR-GUIDE.md](docs/AI-OPERATOR-GUIDE.md) — it walks a fresh
> agent from a bare server to a running, seeded instance. This file is for
> working *inside* the codebase once it is running.

## Development Commands

All commands run on the server where Docker is running.

A `Makefile` provides shortcuts for common operations. Run `make help` to see all targets.

```bash
# Makefile shortcuts
make up                # Start services (build + detach)
make down              # Stop services
make logs              # Follow web container logs
make shell             # Django shell_plus
make dbshell           # PostgreSQL shell
make migrate           # Run migrations
make seed              # Load all reference data
make demo              # Load demo dataset (fictional GSA)
make fresh             # Full reset: destroy, rebuild, migrate, seed, demo
make health            # Run health checks
make check             # Django deployment checks

# Direct Docker Compose commands
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py collectstatic --noinput
docker compose exec db psql -U openh2o -d openh2o
```

## Design System

The VanderDev design system provides a dark-mode dashboard aesthetic with California state identity.

Design tokens live in `static/css/tokens.css`:
- Surface colors: base (#040608), card (#080b10), elevated (#0e1219)
- Accent: California Gold (#E4A317), Pacific Blue (#1B7FAF)
- Text: primary (#e8edf4), secondary (#8899aa), tertiary (#4d5e6f)
- OKLCH tonal ramps for data visualization (furnace-orange, reservoir-blue, forest-teal)
- Typography: Public Sans sitewide (one typeface; numeric columns use `tabular-nums`)

Tailwind config extends the default theme with these tokens. CSS is compiled by the Tailwind standalone binary during Docker build (no Node.js required).

### Before ANY visual change (BLOCKING)

This site has a written design system and a named component vocabulary. Follow
it — do not eyeball a new look.

1. **Read `DESIGN.md` first**, then find the existing component before writing CSS.
   The house "concept" components live in `static/css/app.css` and are catalogued
   in `DESIGN.md` → *House "concept" components*: `.callout-rule` (gold left-rule
   for "the rule" of a page), `.accent-card`, `.budget-panel`, `.concept-panel`,
   `.result-card`, `.step-card`, `.card-raised`/`.card-inset`. The same idea must
   always look the same — reuse the component, don't reinvent it.
2. **Emphasize prose with the site's own panel, never a bespoke accent box.**
   Body and intro text is plain left-aligned prose at a 65–75ch measure (see
   `.about-purpose`, Help page bodies). To lift a passage, wrap it in a plain
   `.card-raised` — the same panel the credit cards and Help "short version"
   blocks use — with **no colored left-stripe**. A colored stripe or filled
   accent box around a lone paragraph is the generic-AI-callout look; that is
   exactly what to avoid.
3. **Accent discipline (authority: `static/css/tokens.css`).** Teal
   (`--color-accent`, `#46B3C4`) is the PRIMARY accent and OpenH2O's identity —
   logo, title, links, active states, everyday emphasis. Gold (`--color-gold`,
   `#E0A446`) is for primary CTAs ONLY, used sparingly ("gold acts"); do NOT use
   it as general emphasis. Pacific Blue (`--color-blue`, `#1B7FAF`) is parcels
   and links to water data. `.callout-rule` hardcodes a legacy pre-Deep-Water
   gold — treat it as legacy, not the pattern to copy.
4. **Casing:** section headers, eyebrows, and labels are sentence case (the two
   exceptions are data-table column headers and map/legend labels).
5. **Preview on staging and screenshot before calling it done** — Tailscale-only
   at **`https://butler.tail7ae369.ts.net`** (HTTPS, no port number). Compare
   against the surrounding page, not in isolation.

   **Use that URL, not `http://…:8081`.** 8081 is the internal Caddy port; the
   canonical URL is `tailscale serve` terminating real Let's Encrypt TLS on 443
   and proxying to it. Django's production settings force
   `SECURE_SSL_REDIRECT` / `SESSION_COOKIE_SECURE` / `CSRF_COOKIE_SECURE`, so
   over plain `http://…:8081` the browser drops the secure cookies and **login
   fails with a CSRF 403** — pages you can reach without logging in will render,
   which makes the port URL look like it works right up until it doesn't.
   Full rationale: `~/dotfiles/docs/INFRASTRUCTURE.md` (OpenH2O staging).

## Staging & production access (READ before authenticating to either)

**Staging login is standing, documented, and NON-SECRET by design.**
`admin@staging.local` / `staging-demo-2026`, applied by `ensure_superuser` from
`~/openh2o-staging/.env` on every container boot (so it survives rebuilds and
`make fresh`). It is intentionally shareable in plain text — the Tailscale
network is the real gate, exactly like AgenticOS/VanderOps. Do **not** treat it
as a secret, do **not** store it in Bitwarden, and do **not** mirror it on prod.

- **Never invent access.** If a login does not work, the answer is in this file
  or `~/dotfiles/docs/INFRASTRUCTURE.md` (line ~193) — read it. Never create an
  account, generate a password, or hand-build identity in a shared environment:
  staging's whole value is that its state is reproducible from config. A
  hand-made account is undocumented drift in the one place that must have none.
  (Incident 2026-07-20: post-mortem in
  `~/Documents/Infrastructure/Claude-Tooling/staging-environment-mutation-postmortem-2026-07-20.md`.)
- **Two deployments on Butler.** `~/openh2o` = PRODUCTION (openh2o.com);
  `~/openh2o-staging` = STAGING. Confirm which with
  `docker ps --format '{{.Names}}\t{{.Label "com.docker.compose.project.working_dir"}}'`
  before touching anything.
- **Staging deploy** = git checkout on Butler: `git fetch && git reset --hard
  origin/main`, then `docker compose up -d --build web` (code is baked into the
  image, not bind-mounted — a sync alone changes nothing the container serves).
  Never rsync with `--delete`. **Production deploy is Brent's separate, explicit
  call** — `deploy.sh` / `make deploy` in the prod checkout, never run as a side
  effect.

## Testing

The suite uses pytest + pytest-django + factory_boy and lives in `tests/`.

```bash
make test          # runs pytest pinned to local settings
```

Tests are pinned to `config.settings.local` via `--ds` because the production
settings refuse to boot without a strong DB password and a real ALLOWED_HOSTS.
Add tests alongside any new model, view, or data adapter.

## Key Constraints

- **No Node.js.** Tailwind uses the standalone binary. HTMX and MapLibre load from CDN.
- **No Celery or Redis.** The platform targets 2-4GB RAM on a small server.
- **Caddy, not nginx.** Auto-HTTPS with smaller configuration footprint.
- **AUTH_USER_MODEL = 'core.User'** is set from day one. Never change this after migrations run.
- **PostGIS from day one.** All geographic models use spatial fields.
- **Single-tenant.** One deployment serves one agency. Multi-tenancy is out of scope by design.
- **License: AGPL-3.0-or-later.** If you modify and host it, you must offer users the source (see NOTICE).
