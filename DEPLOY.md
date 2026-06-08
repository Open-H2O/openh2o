<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Deploy: Open Water Accounting Platform

Complete deployment guide. Every command is copy-pasteable. Written for
an AI or operator deploying on a fresh VPS with zero prior knowledge.

---

## 1. Server Requirements

| Requirement | Minimum |
|-------------|---------|
| OS | Ubuntu 22.04+ (tested on 24.04) |
| RAM | 2 GB (4 GB recommended) |
| Disk | 10 GB free |
| Docker Engine | 24+ |
| Docker Compose | v2 |
| Git | any recent version |
| Domain | Required for production HTTPS |

Verify Docker is installed:

```bash
docker --version
# Expected: Docker version 24.x or newer

docker compose version
# Expected: Docker Compose version v2.x
```

If Docker is not installed:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# Log out and back in, then verify with: docker run hello-world
```

---

## 2. Clone the Repository

```bash
git clone https://github.com/Open-H2O/openh2o.git
cd openh2o
```

---

## 3. Environment Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

Generate a secret key:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

Edit `.env` and set these values at minimum:

```bash
SECRET_KEY=<paste-generated-key-here>
POSTGRES_PASSWORD=<choose-a-strong-password>
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
CSRF_TRUSTED_ORIGINS=https://your-domain.com,https://www.your-domain.com
DJANGO_SETTINGS_MODULE=config.settings.production
```

See `.env.example` for all available variables with documentation.

---

## 4. Caddy / HTTPS Configuration

Edit `Caddyfile` to replace `:80` with your domain for automatic HTTPS:

```caddy
your-domain.com {
    encode gzip

    handle /static/* {
        root * /srv
        file_server
    }

    handle {
        reverse_proxy web:8000
    }
}
```

Caddy obtains TLS certificates from Let's Encrypt automatically. Your
domain's DNS A record must point to the server's public IP before starting.

For local/development use, keep the default `:80` configuration.

---

## 5. Build and Start

```bash
docker compose up -d --build
```

Wait for the database health check to pass (takes 10-15 seconds):

```bash
docker compose ps
```

Expected output showing all 3 services running:

```
NAME              IMAGE                    STATUS                    PORTS
openh2o-caddy-1   caddy:2-alpine          Up                        0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
openh2o-db-1      postgis/postgis:16-3.4  Up (healthy)              5432/tcp
openh2o-web-1     openh2o-web             Up                        8000/tcp
```

---

## 6. Run Migrations

```bash
docker compose exec web python manage.py migrate
```

Expected: a list of applied migrations ending with `OK`.

---

## 7. Create Superuser

```bash
docker compose exec web python manage.py createsuperuser
```

Follow the prompts for username, email, and password.

---

## 8. Seed Reference Data

These commands load required lookup tables (roles, water types, well types,
water right types, data source definitions, and report templates):

```bash
docker compose exec web python manage.py seed_data
```

This runs all six seed commands in order:
- `seed_roles` (admin, manager, viewer)
- `seed_water_types` (Groundwater, Surface Water, Recycled Water, etc.)
- `seed_water_right_types` (Appropriative, Pre-1914, Riparian, etc.)
- `seed_well_types` (Agricultural, Municipal, Monitoring, etc.)
- `seed_data_sources` (CDEC, USGS, OpenET, CIMIS, CNRFC, DWR, NOAA)
- `seed_report_templates` (GEARS CSV, CalWATRS CSV)

To run any seed command individually:

```bash
docker compose exec web python manage.py seed_roles
```

---

## 9. Load the Demonstration Dataset (Optional)

For testing or demonstration, load the Merced Subbasin demo — a real California
basin, the same dataset running at openh2o.com:

```bash
docker compose exec web python manage.py seed_merced
```

This builds the full demonstration: real boundary and hydrography, GSA and
district zones, water rights and points of diversion, hand-selected place-of-use
parcels, cropland, recharge basins, and a year of ledger activity. One step does
a live fetch of flowlines and monitoring stations from public APIs (a few
minutes, no key required). For real satellite-ET figures, set an OpenET key (see
section 11) and run the ET sync; without it the demo uses representative
face-value figures and is still internally coherent.

Each sub-step is idempotent, so re-running is safe.

---

## 10. Verify Deployment

Run these checks in order:

**HTTP response through Caddy:**

```bash
curl -s -o /dev/null -w '%{http_code}' http://localhost
# Expected: 200
```

**PostGIS loaded:**

```bash
docker compose exec db psql -U openh2o -d openh2o -c "SELECT PostGIS_Version();"
# Expected: 3.4 USE_GEOS=1 USE_PROJ=1 USE_STATS=1
```

**Health check API:**

```bash
curl -s http://localhost/health/api/ | python3 -m json.tool
# Expected: JSON with "status": "healthy" or "status": "warning"
```

**Health dashboard:**

Visit `http://<server-ip>/health/` in a browser.

**Django admin:**

Visit `http://<server-ip>/admin/` and log in with your superuser credentials.

**No errors in logs:**

```bash
docker compose logs web --tail=50
# Look for: "Listening at: http://0.0.0.0:8000"
# No tracebacks or errors
```

---

## 11. Ongoing Operations

### Upgrades

```bash
cd /path/to/openh2o
git pull origin main
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py collectstatic --noinput
```

### Scheduled Jobs

The jobs in `crontab.txt`:

| Job | Schedule | Purpose |
|-----|----------|---------|
| `run-sync.sh cdec usgs` | Hourly | Live stream / reservoir telemetry (near-real-time flow & stage) |
| `run-sync.sh cimis cnrfc dwr_wdl dwr_sgma noaa openet` | Daily 2:00 AM | Slower sources — ET, groundwater, river forecasts, climate |
| `run_health_checks` | Every 6 hours | Check database, disk, SSL, migrations, sync freshness |
| `prune_old_data --confirm` | 1st of month 3:00 AM | Delete old staging records and sync logs |

`scripts/run-sync.sh` is a resilient wrapper: it runs `docker compose up -d`
first (a no-op if the stack is already running, but it revives the container if
an unattended-upgrade reboot left it stopped — the original cause of silent
sync failures), logs to `$OPENH2O_LOG_DIR` (default `/opt/openh2o-logs`),
and pings ntfy on failure if you set `OPENH2O_NTFY_URL` to a topic URL.

Install the crontab. **Note:** `make install-cron` *appends*; if you are
replacing older OpenH2O cron lines, edit `crontab -e` and remove the old
entries first so you don't run two schedules.

```bash
make install-cron
# verify:
make show-cron
```

Edit `crontab.txt` to set `OPENH2O_DIR` (where you cloned the repo) and
`OPENH2O_LOG_DIR` (a writable log directory) to match your deployment. The
defaults are `/opt/openh2o` and `/opt/openh2o-logs`.

### External Data API Keys

CDEC, USGS, CNRFC and the DWR sources are public and need no credentials. Three
sources require a key, set in `.env` (then `docker compose up -d` to reload):

| Source | `.env` variable | Get a key from |
|--------|-----------------|----------------|
| CIMIS | `CIMIS_API_KEY` | https://cimis.water.ca.gov (register → App Key) |
| NOAA | `NOAA_CDO_TOKEN` | https://www.ncdc.noaa.gov/cdo-web/token |
| OpenET | `OPENET_API_KEY` | https://etdata.org (account → API key) |

Until a key is set, that source shows **"Needs API key"** on the monitoring
page rather than a misleading failure, and is skipped by the sync.

### Map Basemaps (streamed, no tile server to host)

The interactive maps do **not** self-host a basemap or run a tile server — both
basemaps stream their tiles live from third-party services on every page load:

| Basemap | Streams from | Needs a key? |
|---------|--------------|--------------|
| Aerial (default) | Esri World Imagery + labels, `server.arcgisonline.com` | No |
| Dark | OpenFreeMap vector tiles + fonts/sprites, `tiles.openfreemap.org`, with a Natural Earth raster underlay | No |

There is nothing to provision, configure, or back up for maps. The trade-off is a
live external dependency: if Esri or OpenFreeMap is unreachable (outage, firewall,
air-gapped network), the map backdrop fails to load. The platform's own data
layers (parcels, wells, diversions, boundaries — served as GeoJSON from this
deployment) still render on top. An operator who needs offline or self-hosted
maps would have to stand up their own tile server and repoint `static/js/map-core.js`.

### Email / Password Reset (SMTP)

Logged-in users can change their password with no setup — the **Change Password**
link in the header works out of the box. The **"Forgot password?"** flow on the
login page, however, emails a reset link, so it needs an outgoing mail server.
Until SMTP is configured, that flow silently fails (no email is sent).

Set these in `.env`, then `docker compose up -d` to reload:

```bash
EMAIL_HOST=smtp.your-provider.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<smtp-username>
EMAIL_HOST_PASSWORD=<smtp-password-or-app-password>
DEFAULT_FROM_EMAIL=noreply@your-domain.com
```

Any SMTP provider works. Two common choices:

- **Gmail:** host `smtp.gmail.com`, port `587`, user = your full Gmail address,
  password = a 16-character **App Password** (Google Account → Security →
  2-Step Verification → App passwords — *not* your normal login password).
  Fine for a single agency; subject to Gmail's daily send limits.
- **Transactional provider (Resend, Postmark, Amazon SES):** gives a real
  `noreply@your-domain.com` sender and higher limits. Preferred for public sites.

Verify by triggering a reset and watching the log:

```bash
docker compose exec web python manage.py sendtestemail you@example.com
```

### Health Checks

Run manually at any time:

```bash
docker compose exec web python manage.py run_health_checks
# Or: make health
```

For JSON output (useful for monitoring integrations):

```bash
docker compose exec web python manage.py run_health_checks --json
```

### Data Pruning

Run a dry-run to see what would be deleted (default, no action taken):

```bash
docker compose exec web python manage.py prune_old_data
# Or: make prune
```

Actually delete old records (requires `--confirm`):

```bash
docker compose exec web python manage.py prune_old_data --confirm
```

### Data Sync

Sync external data (CDEC, USGS, CIMIS, etc.) manually:

```bash
docker compose exec web python manage.py sync_all
# Or sync one source:
docker compose exec web python manage.py sync_source cdec
# Or: make sync
```

Sync runs against the live public APIs. Sources needing a key (CIMIS, NOAA,
OpenET) are skipped until their key is set in `.env` — see "External Data API
Keys" above.

### Running Tests

```bash
docker compose exec web python -m pytest tests/ -v
# Or: make test
```

### Database Backup

```bash
docker compose exec db pg_dump -U openh2o openh2o > backup-$(date +%Y%m%d).sql
```

### Database Restore

```bash
docker compose exec -T db psql -U openh2o -d openh2o < backup-20250101.sql
```

### View Logs

```bash
docker compose logs web          # Django/Gunicorn
docker compose logs db           # PostgreSQL
docker compose logs caddy        # Caddy reverse proxy
docker compose logs -f web       # Follow logs in real time
```

### Public Demo Reset (golden snapshot)

A **public** demo is single-tenant: one shared database, open self-signup, no
per-visitor isolation. Any logged-in visitor's parcels, wells, and reports
persist for everyone, and nothing prunes them. To keep the demo pristine, restore
it on a schedule from a "golden" snapshot of the clean state.

```bash
make snapshot-demo   # capture the golden snapshot (scripts/snapshot-demo.sh)
make reset-demo      # restore the demo to that snapshot now (scripts/reset-demo.sh)
```

`snapshot-demo` writes two files side by side: `golden.dump` (the database) and
`golden.meta` (a manifest stamping the schema **migration fingerprint**, the code
version, a timestamp, and per-model row counts). `reset-demo` pauses web, drops +
recreates the database from the dump, restarts web, and runs `migrate`. Wire it to
cron for an unattended nightly reset, e.g.:

```cron
0 4 * * * cd /path/to/openh2o && OPENH2O_NTFY_URL=http://your-ntfy-host:8080/your-topic bash scripts/reset-demo.sh /path/to/golden.dump >> ~/openh2o-logs/reset-demo-cron.log 2>&1
```

Set `OPENH2O_NTFY_URL` (optional) to receive ntfy notifications — high-priority on
a skipped/failed reset, a routine before→after row-count summary on success.

**Staleness guard (the safety net for the discipline below).** Before wiping,
`reset-demo` compares the live schema's migration fingerprint against the one in
`golden.meta`. If they differ — meaning a migration ran since the snapshot was
taken — it **refuses to wipe, fires a high-priority ntfy, and exits**, so a legit
change is never silently erased. To proceed anyway, re-stamp with
`make snapshot-demo`, or run with `FORCE=1` to bypass the guard.

This is automatic on deploy: `make deploy` runs `FORCE=1 reset-demo` (restore
golden, migrate forward to the new schema, drop visitor junk) then `snapshot-demo`
(re-stamp at the new fingerprint), so the golden auto-stays-current and the nightly
guard keeps passing. **Note:** `make deploy` now resets the public demo to golden —
visitor-added data does not survive a deploy (it does not survive the nightly reset
either, by design).

> **Discipline — refresh the snapshot when the golden CONTENT changes.** The guard
> catches *schema* drift, but a deliberate **content** change the schema can't see
> (a calc rebuild, edited demo data) still needs a re-stamp, or the next reset
> reloads the old content. After a recalculation use `make calc-rebuild PERIOD=YYYY-MM`,
> which recomputes the period and re-stamps in one step. After any other intentional
> content/admin change, run `make snapshot-demo`. The snapshot pins the admin
> accounts and seeded data — recreate those *before* snapshotting, not after.

---

## 12. Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | Yes | none | Django secret key for signing |
| `POSTGRES_DB` | No | `openh2o` | PostgreSQL database name |
| `POSTGRES_USER` | No | `openh2o` | PostgreSQL username |
| `POSTGRES_PASSWORD` | No | `openh2o` | PostgreSQL password (change in production) |
| `DJANGO_SETTINGS_MODULE` | No | `config.settings.local` | Use `config.settings.production` for prod |
| `ALLOWED_HOSTS` | Yes (prod) | `[]` | Comma-separated list of allowed hostnames |
| `CSRF_TRUSTED_ORIGINS` | Yes (prod) | `[]` | Comma-separated HTTPS origins |
| `ACCESS_CONTROL_ENFORCED` | No | `True` | Two-tier access model. On (default) closes public self-signup and gates admin-only screens — the right posture for a real agency. Set `False` only for an open demo where anyone should be able to self-register. Your superuser is always an administrator, so you can't lock yourself out |
| `TIME_ZONE` | No | `America/Los_Angeles` | Django timezone |
| `DEFAULT_FROM_EMAIL` | No | `noreply@openh2o.com` | Sender address for emails |
| `EMAIL_BACKEND` | No | console (dev), SMTP (prod) | Django email backend |
| `EMAIL_HOST` | No | empty | SMTP server hostname |
| `EMAIL_PORT` | No | `587` | SMTP port |
| `EMAIL_USE_TLS` | No | `True` | Use TLS for SMTP |
| `EMAIL_HOST_USER` | No | empty | SMTP username |
| `EMAIL_HOST_PASSWORD` | No | empty | SMTP password |
| `GOOGLE_OAUTH_CLIENT_ID` | No | empty | Google OAuth client ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | No | empty | Google OAuth client secret |
| `DATASYNC_MOCK_MODE` | No | `False` | Use mock data for external sync adapters instead of live APIs |
| `FEEDBACK_ENABLED` | No | `False` | Render the in-app feedback widget. Off by default; set `True` to turn it on (e.g. on a hosted/managed deployment with someone to read the reports) |
| `FEEDBACK_ENDPOINT` | No | empty | Optional URL to also POST each stored report to (e.g. an n8n triage pipeline); blank = store-only |
| `FEEDBACK_MAX_ATTACHMENTS` | No | `5` | Max screenshots allowed per report |
| `FEEDBACK_MAX_ATTACHMENT_BYTES` | No | `8388608` | Max size per attachment (bytes; default 8 MB) |
| `FEEDBACK_MAX_MESSAGE_CHARS` | No | `5000` | Max characters in a feedback message |
| `FEEDBACK_MAX_DIAGNOSTICS_BYTES` | No | `65536` | Max size of the auto-captured diagnostics blob (bytes; default 64 KB) |
| `FEEDBACK_RATE_LIMIT_PER_HOUR` | No | `20` | Max submissions accepted per client per hour |

---

## 13. Troubleshooting

**Container won't start:**

```bash
docker compose logs <service-name>
# Check for specific error messages
```

**Database connection refused:**

```bash
docker compose ps
# Verify db shows "healthy"
# If not: docker compose logs db
```

**"GDAL library not found" or GeoDjango errors:**

The Dockerfile installs GDAL, GEOS, and PROJ. If building locally without
Docker, install system packages:

```bash
# Ubuntu/Debian
sudo apt-get install gdal-bin libgdal-dev libgeos-dev libproj-dev
```

**Port 80/443 already in use:**

```bash
sudo lsof -i :80
# Identify and stop the conflicting service, or change ports in docker-compose.yml
```

**Migrations fail with "relation already exists":**

```bash
docker compose exec web python manage.py migrate --fake-initial
```

**Static files not loading (404 on /static/):**

```bash
docker compose exec web python manage.py collectstatic --noinput
docker compose restart caddy
```

**Rebuild from scratch (destroys database):**

```bash
docker compose down -v
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_data
```

**Check Django configuration for errors:**

```bash
docker compose exec web python manage.py check --deploy
```
