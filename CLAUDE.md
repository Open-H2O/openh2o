# Open Water Accounting Platform

## Project Overview

A water accounting platform for California Groundwater Sustainability Agencies (GSAs) and water districts. Tracks groundwater extraction, surface water diversions, mixed-use accounting, and managed aquifer recharge. Generates state reports (GEARS CSV, CalWATRS CSV) for the Water Board.

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
