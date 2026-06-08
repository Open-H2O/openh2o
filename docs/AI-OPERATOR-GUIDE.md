<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# AI Operator Guide

**Read this if you are an AI agent (or the person driving one) tasked with standing up OpenH2O for a water agency.**

OpenH2O is designed so that a capable coding agent — Claude Code, or similar — can take a bare Linux server and a domain name and deliver a running, secured, data-populated water-data management platform, then help the agency's staff see and manage their own data. [DEPLOY.md](../DEPLOY.md) is the exact command reference; **this guide is the decision-making layer on top of it** — what to ask, what to choose, and what order to do it in.

Work through the five phases in order. Stop at each ✋ checkpoint and confirm with the human before proceeding.

---

## What you need before you start

Ask the agency staffer for these. You cannot proceed without the first two.

1. **A fresh Linux server** with SSH access and Docker installed (a 2–4 GB virtual server is plenty). Ubuntu LTS is the safe default.
2. **A domain or subdomain** they control, with DNS pointed at the server's IP (e.g. `water.theirdistrict.org`). HTTPS depends on this.
3. *(Optional, can be added later)* API keys for OpenET, CIMIS, and NOAA, and SMTP credentials for password-reset email. The platform runs fine without them; those features simply stay dark until provided.

If they don't have a server or domain yet, help them get a virtual server from any provider and register a domain first. Don't try to deploy to `localhost` for a real agency — they need a URL their board can reach.

---

## The shape of the job

```
Phase 1  Stand up the platform        → containers running, migrations applied
Phase 2  Secure it                    → strong DB password, real domain, HTTPS, admin user
Phase 3  Load data                    → demo first, then their real parcels/wells
Phase 4  Connect live data sources    → API keys + scheduled sync
Phase 5  Onboard the humans           → roles, a walkthrough, the first report
```

A first-time deployment to a running, secured, demo-populated instance is a single working session. Loading an agency's *real* data is the part that takes back-and-forth, because it depends on what data they have.

---

## Phase 1 — Stand up the platform

Follow [DEPLOY.md](../DEPLOY.md) sections 1–6. In short:

```bash
git clone https://github.com/Open-H2O/openh2o.git
cd openh2o
cp .env.example .env
# edit .env — at minimum set SECRET_KEY and DJANGO_SETTINGS_MODULE=config.settings.production
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_data   # reference tables (idempotent)
```

✋ **Checkpoint:** `docker compose ps` shows `db`, `web`, and `caddy` all healthy, and the site responds. Don't move on until it does.

---

## Phase 2 — Secure it (do this before anyone logs in)

This is the phase an AI must not skip. The platform's production settings **refuse to boot** with a weak database password or an empty `ALLOWED_HOSTS` — that guard is your friend; let it enforce the basics.

1. **Strong database password.** Set `POSTGRES_PASSWORD` in `.env` to a long random value. The dev default (`openh2o`) is rejected in production by design.
2. **Real `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.** Set them to the agency's domain.
3. **HTTPS.** Caddy issues a certificate automatically *once DNS points at the server*. Confirm the domain resolves to the server before expecting `https://` to work. (See DEPLOY.md's Caddyfile section.)
4. **Create the admin user.** Either `docker compose exec web python manage.py createsuperuser`, or set `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` in `.env` and let `ensure_superuser` create it on startup.

✋ **Checkpoint:** the site loads over `https://theirdomain`, and you can log in as the admin. Confirm the human has the admin password stored somewhere safe (a password manager).

---

## Phase 3 — Load data

**Decide first: does the agency have their own data ready, or do they want to explore the demo first?**

### Option A — Demo data (always do this first)
```bash
docker compose exec web python manage.py seed_merced   # the Merced Subbasin demonstration
```
This loads the Merced Subbasin demo — a real California basin, the same dataset running at openh2o.com — a fully populated example the agency can click through while you gather their real data. One step fetches hydrography and monitoring stations live from public APIs (a few minutes, no key needed); for real satellite-ET numbers, add an OpenET key and run the ET sync (Phase 4). Each sub-step is idempotent, so re-running is safe.

### Option B — Their real data
Three import routes, in rough order of preference:

| If they have… | Use | Notes |
|---|---|---|
| Parcel boundaries as GeoJSON/Shapefile | `import_parcels` | Required foundation — everything hangs off parcels |
| A well list as CSV | `import_wells` | Optional but valuable |
| Historical ledger entries as CSV | `import_ledger_csv` | For migrating from a prior system |
| Only a basin boundary | `auto_populate` | Queries DWR and USGS to pull parcels, boundaries, and flowlines automatically |

What still has to be entered by hand (no public source exists): **water rights**, **water accounts**, and **allocations**. The web UI has forms for these under the Infrastructure section.

✋ **Checkpoint:** confirm with the human which parcels are theirs and that the boundary looks right on the map before building accounts on top of it.

---

## Phase 4 — Connect live data sources

The free public sources (USGS, CDEC, DWR, CNRFC) work with no keys. CIMIS, NOAA, and OpenET need keys; add them to `.env` and restart (`docker compose up -d`). Then install the scheduled sync:

```bash
# set OPENH2O_DIR and OPENH2O_LOG_DIR in crontab.txt to match this deployment first
make install-cron
make show-cron     # verify
```

Run one sync by hand to prove it works before trusting the schedule:
```bash
docker compose exec web python manage.py sync_source usgs
docker compose exec web python manage.py check_conformance   # registry is publish-clean
```

### Curate the monitoring stations (do this for every new basin)

Station discovery (`auto_populate`'s station step) casts a **wide net** — it pulls
every gauge and well the public APIs report anywhere near the basin's bounding box,
created inactive. Many will never return data: a stream gauge that's been
decommissioned, a CDEC sensor that only posts event-duration readings, a
groundwater well whose last real measurement was a decade ago. If you leave them
on the map, the district's monitoring view reads as a field of dead red markers
and looks broken. So **analyse what actually reports, then prune the rest** before
handover.

1. **Sync every active source with the right window.** Daily gauges (cdec, usgs)
   are fine on the default 7-day window, but periodic groundwater (`dwr_wdl`,
   `dwr_sgma`) and lagging climate (`noaa`) report only every few months — sync
   them with a multi-year `--start` so each station lands a real history, not a
   single dot:
   ```bash
   docker compose exec web python manage.py sync_source cdec
   docker compose exec web python manage.py sync_source usgs
   docker compose exec web python manage.py sync_source dwr_sgma --start 2020-06-01
   docker compose exec web python manage.py sync_source dwr_wdl  --start 2020-06-01
   docker compose exec web python manage.py sync_source noaa     --start 2020-06-01
   ```
   Note any gauge whose source returns nothing — that station is dead at the
   source, not misconfigured.

2. **Eliminate the stations that carry no usable data.** This deletes (not just
   hides) any active station without enough readings to chart, plus the entire
   inactive discovery net (which carries no data by definition):
   ```bash
   docker compose exec web python manage.py prune_dataless_stations --delete --purge-inactive --dry-run
   docker compose exec web python manage.py prune_dataless_stations --delete --purge-inactive
   ```
   `--dry-run` first to see what goes. The default keeps any station with ≥2
   published readings; raise `--min-records` if you want a leaner map. Re-run this
   any time after a from-scratch re-seed — discovery re-creates the wide net, and
   one command clears it again.

✋ **Checkpoint:** the monitoring map is mostly green/amber (stations with recent
data), not a field of red, and every visible marker has a real reading behind it.

---

## Phase 5 — Onboard the humans

The platform has three roles. Set expectations before handing over:

- **Admin** — manages users, data, and reports (usually one person).
- **Manager** — edits the ledger, creates accounts, runs reports (one or two people).
- **Viewer** — read-only; for board members and outside agencies.

Then walk them through the first loop: log in → confirm their boundary → review their accounts, allocations, and recorded data. If the agency files with the state, show the optional reporting step too: open the reporting page → generate a draft GEARS or CalWATRS CSV, making clear that OpenH2O *prepares* the filing; a certifying official reviews and submits it in the state portal.

✋ **Done when:** an agency staffer can log in and see and manage their own basin data without you — and, if they report to the state, produce a draft report.

---

## Troubleshooting by symptom

| Symptom | Likely cause | Fix |
|---|---|---|
| `web` container won't start, mentions `ImproperlyConfigured` | Weak DB password or empty `ALLOWED_HOSTS` in production | Set a strong `POSTGRES_PASSWORD` and a real `ALLOWED_HOSTS` in `.env` — the guard is intentional |
| Docker build fails on GDAL/GEOS | Base image or platform mismatch | Confirm you're on a supported Linux/arch; see DEPLOY.md troubleshooting |
| Site loads but no HTTPS | DNS not pointing at the server yet | Fix the DNS A record, wait for propagation, then restart Caddy |
| A data source shows red/stale | Missing API key, or the source only publishes periodically | Check `check_conformance` and the source's freshness window; groundwater is quarterly, ET is monthly |
| Password-reset email never arrives | SMTP not configured | Add SMTP credentials to `.env`; until then, reset passwords via `manage.py` |
| 502 / Bad Gateway after a reboot | A container came up without a restart policy | The compose file sets `restart: unless-stopped`; run `docker compose up -d` to revive |

---

## Guardrails — what NOT to do

- **Never** commit the agency's `.env`, API keys, or `secrets/` directory. They are gitignored for a reason.
- **Never** run `make fresh` on a populated instance — it destroys the database volume. Use `make up` for routine rebuilds.
- **Never** flip `ACCOUNT_EMAIL_VERIFICATION` to require email before SMTP is configured, or signups will 500.
- **Don't** weaken the production security guard to "make it boot." If it's complaining, fix the password or hosts — that's the bug it's catching.
- **Do** keep the in-app "Source code" link pointing at wherever you publish your modified source. The AGPL (Section 13) requires it once the agency runs the platform for users. See [NOTICE](../NOTICE).
