# Deploy: Open Water Accounting Platform

## Prerequisites

- Ubuntu 22.04+ (tested on 24.04)
- Docker Engine 24+
- Docker Compose v2
- Git
- Domain pointing to server (for production HTTPS via Caddy)

Verify Docker is installed:

```bash
docker --version
# Expected: Docker version 24.x or newer

docker compose version
# Expected: Docker Compose version v2.x
```

## Clone and Configure

```bash
git clone git@github.com:vanderoffice/openh2o.git
cd openh2o
```

Create the environment file:

```bash
cp .env.example .env
```

Generate a secret key and update `.env`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
# Copy the output and set SECRET_KEY= in .env
```

Review `.env` and set at minimum:

- `SECRET_KEY` (generated above)
- `POSTGRES_PASSWORD` (change from default)

## Build and Start

```bash
docker compose up -d --build
```

Wait for the database health check to pass:

```bash
docker compose ps
```

Expected output: all 3 services running, db shows "healthy":

```
NAME              IMAGE                    STATUS                    PORTS
openh2o-caddy-1   caddy:2-alpine          Up                        0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
openh2o-db-1      postgis/postgis:16-3.4  Up (healthy)              5432/tcp
openh2o-web-1     openh2o-web             Up                        8000/tcp
```

## Verify Deployment

**1. HTTP response through Caddy:**

```bash
curl -s -o /dev/null -w '%{http_code}' http://localhost
# Expected: 200
```

**2. PostGIS loaded:**

```bash
docker compose exec db psql -U openh2o -d openh2o -c "SELECT PostGIS_Version();"
# Expected: 3.4 USE_GEOS=1 USE_PROJ=1 USE_STATS=1
```

**3. Django admin page:**

Visit `http://<server-ip>/admin/` in a browser. You should see the Django admin login page. No users exist yet (Phase 2 creates user management).

**4. No errors in logs:**

```bash
docker compose logs web
# Look for: "Listening at: http://0.0.0.0:8000"
# No tracebacks or errors
```

## Upgrade Path

```bash
cd /path/to/openh2o
git pull origin main
docker compose up -d --build
docker compose exec web python manage.py migrate
```

Verify after upgrade:

```bash
docker compose ps
curl -s -o /dev/null -w '%{http_code}' http://localhost
```

## Phase TODOs

These sections will be filled in as each phase is completed:

- **Phase 2:** Run migrations, create superuser, seed reference data
- **Phase 3:** Import parcels/wells, configure map layers
- **Phase 4:** Configure water accounts and allocation plans
- **Phase 5:** Set API keys for external data sources (CDEC, USGS, OpenET, CIMIS, CNRFC, DWR, NOAA)
- **Phase 6:** Configure reporting crosswalks, set up email for report delivery
- **Phase 7:** Set up health check cron job, configure monitoring
- **Phase 8:** Production HTTPS, security hardening, demo fixtures

## Production Configuration

For production deployment behind a domain:

1. Edit `Caddyfile`: replace `:80` with your domain (e.g., `openh2o.com`)
2. Set `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` in `.env`
3. Set `DJANGO_SETTINGS_MODULE=config.settings.production` in `.env`
4. Restart: `docker compose up -d`

Caddy handles HTTPS certificates automatically via Let's Encrypt.

## Troubleshooting

**Container won't start:**

```bash
docker compose logs <service-name>
# Check for specific error messages
```

**Database connection refused:**

```bash
docker compose ps
# Verify db shows "healthy"
# If not, check: docker compose logs db
```

**Port 80/443 already in use:**

```bash
sudo lsof -i :80
# Identify and stop the conflicting service
```

**Rebuild from scratch:**

```bash
docker compose down -v  # WARNING: deletes database volume
docker compose up -d --build
```

**Django collectstatic fails:**

```bash
docker compose exec web python manage.py collectstatic --noinput
# If this fails, check for import errors in the logs
```
