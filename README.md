# Open Water Accounting Platform

A water accounting platform for California Groundwater Sustainability Agencies (GSAs) and water districts. Tracks groundwater extraction, surface water diversions, mixed-use accounting, and managed aquifer recharge. Generates state reports (GEARS CSV, CalWATRS CSV) for the State Water Resources Control Board.

## Why This Exists

California's Sustainable Groundwater Management Act (SGMA) requires hundreds of local agencies to track and report water use. Most are small, underfunded, and lack technical staff. This platform gives them a production-ready system that an AI agent can deploy on a $15/month VPS in under an hour.

The core value: **access is the product, not features.** A poorly-funded agency buys a frontier AI subscription, points it at this repo and a cheap server, and the AI stands the platform up.

## Quick Start

```bash
git clone https://github.com/vanderoffice/openh2o.git
cd openh2o
cp .env.example .env                          # Edit SECRET_KEY at minimum
docker compose up -d --build                  # Start all services
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_data
```

Visit `http://localhost` to see the dashboard. Run `make help` for all available shortcuts.

For full deployment instructions including HTTPS, production settings, and ongoing operations, see [DEPLOY.md](DEPLOY.md).

## Features

- **Parcel and well management** with spatial data (GeoDjango + PostGIS)
- **Water accounting ledger** tracking supply, usage, and allocations by water type
- **Surface water rights** with points of diversion and diversion records
- **Managed aquifer recharge** site and event tracking
- **External data sync** adapters for CDEC, USGS, OpenET, CIMIS, CNRFC, DWR, and NOAA
- **State reporting** with GEARS CSV and CalWATRS CSV export
- **Health monitoring** dashboard with automated checks
- **Interactive maps** via MapLibre GL JS
- **Dark-mode dashboard** using the VanderDev design system

## Tech Stack

| Component | Technology |
|-----------|------------|
| Framework | Django 5.x with GeoDjango |
| Database | PostgreSQL 16 + PostGIS 3.4 |
| Frontend | HTMX + Tailwind CSS (standalone binary, no Node.js) |
| Maps | MapLibre GL JS |
| Reverse Proxy | Caddy (automatic HTTPS) |
| Containerization | Docker Compose |

## Project Layout

```
openh2o/
  config/settings/     Django settings (base, local, production)
  core/                User model, roles, site config
  geography/           GSA boundaries, management zones
  parcels/             Parcel registry and ledger
  wells/               Well inventory and meters
  measurements/        Meter readings and sensors
  accounting/          Water accounts, allocations, reporting periods
  surface/             Water rights and diversions
  recharge/            Recharge sites and events
  datasync/            External data source adapters
  reporting/           State report generators
  health/              System health checks
  templates/           Django templates (HTMX partials)
  static/css/          Design tokens and Tailwind input
```

## Development

```bash
make up               # Start services
make logs             # Follow web container logs
make shell            # Django shell_plus
make migrate          # Run migrations
make seed             # Load all reference data
make demo             # Load demo dataset (fictional GSA)
make fresh            # Full reset: volumes, rebuild, migrate, seed, demo
make help             # Show all targets
```

## License

MIT
