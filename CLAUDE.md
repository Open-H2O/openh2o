# Open Water Accounting Platform

## Project Overview

A water accounting platform for California Groundwater Sustainability Agencies (GSAs) and water districts. Tracks groundwater extraction, surface water diversions, mixed-use accounting, and managed aquifer recharge. Generates state reports (GEARS CSV, CalWATRS CSV) for the Water Board.

The core value: a poorly-funded agency buys a frontier AI subscription, points it at this repo and a $15/mo VPS, and the AI stands the platform up. Access is the product, not features.

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
├── core/                    # Core app (User model)
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
├── DEPLOY.md                # Deployment guide
└── CLAUDE.md                # This file
```

## Development Commands

All commands run on the server where Docker is running (Butler: REDACTED-LAN-IP).

```bash
# Start the stack
docker compose up -d --build

# Stop the stack
docker compose down

# View logs
docker compose logs web
docker compose logs -f web  # Follow

# Django management commands
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py collectstatic --noinput

# Database access
docker compose exec db psql -U openh2o -d openh2o

# Rebuild after code changes
docker compose up -d --build
```

## Design System

The VanderDev design system provides a dark-mode dashboard aesthetic with California state identity.

Design tokens live in `static/css/tokens.css`:
- Surface colors: base (#040608), card (#080b10), elevated (#0e1219)
- Accent: California Gold (#E4A317), Pacific Blue (#1B7FAF)
- Text: primary (#e8edf4), secondary (#8899aa), tertiary (#4d5e6f)
- OKLCH tonal ramps for data visualization (furnace-orange, reservoir-blue, forest-teal)
- Typography: Public Sans (display), JetBrains Mono (code)

Tailwind config extends the default theme with these tokens. CSS is compiled by the Tailwind standalone binary during Docker build (no Node.js required).

## Testing

TODO: Testing conventions will be established in later phases.

## Key Constraints

- **No Node.js.** Tailwind uses the standalone binary. HTMX and MapLibre load from CDN.
- **No Celery or Redis.** The platform targets 2-4GB RAM on a small server.
- **Caddy, not nginx.** Auto-HTTPS with smaller configuration footprint.
- **AUTH_USER_MODEL = 'core.User'** is set from day one. Never change this after migrations run.
- **PostGIS from day one.** All geographic models use spatial fields.
- **Deploy target: Butler** (REDACTED-LAN-IP) via Cloudflare Tunnel for public access.
