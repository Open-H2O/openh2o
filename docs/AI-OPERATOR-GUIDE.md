<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# AI Operator Guide

**Read this if you are an AI agent (or the person driving one) tasked with standing up OpenH2O for a water agency.**

OpenH2O is designed so that a capable coding agent — Claude Code, or similar — can take a bare Linux server and a domain name and deliver a running, secured, data-populated water-data management platform, then help the agency's staff see and manage their own data. [DEPLOY.md](../DEPLOY.md) is the exact command reference; **this guide is the decision-making layer on top of it** — what to ask, what to choose, and what order to do it in.

Work through the five phases in order. Stop at each ✋ checkpoint and confirm with the human before proceeding.

---

## What you need before you start

**Where this runs is the agency's choice, not this platform's.** OpenH2O is
meant to run the same way on an office computer, on a $15/month rented server,
and on a government data centre. None of those is a lesser deployment, and this
guide must never refuse one of them. What changes between them is **who can
reach the instance**, and that — not the price of the hardware — is what
decides the security settings in Phase 2.

Ask the agency staffer for these.

1. **A computer to run it on**, with Docker installed. Any of these is fine:
   their own machine (Windows, macOS or Linux, with Docker Desktop or OrbStack),
   a rented virtual server, or agency-managed infrastructure. 2–4 GB of memory
   is plenty. **Check Docker works before anything else: `docker run
   hello-world`.** If that fails mentioning "cgroup" or "bpf", the machine's own
   host is blocking containers and no setting inside it will fix that — ask
   whoever provisioned it.
2. **How the agency needs to reach it.** Ask directly, and write the answer
   down; every later choice follows from it:
   - *Only from this one computer* — no domain needed. Bind the service to
     loopback (`127.0.0.1`) so nothing else on their network can reach it.
   - *From other computers in their office* — no domain needed, but the
     instance is now exposed to their local network. Say so out loud.
   - *From outside — a board member, a consultant, the public* — **this is the
     only case that needs a domain and HTTPS.** They will need a domain or
     subdomain they control, with DNS pointed at the machine's address.
3. *(Optional, can be added later)* API keys for OpenET, CIMIS, and NOAA, and SMTP credentials for password-reset email. The platform runs fine without them; those features simply stay dark until provided.

If the agency wants public reach and has no server or domain yet, help them get
a virtual server from any provider and register a domain. **If they do not want
public reach, do not talk them into it** — a single-computer or office-network
deployment is a supported way to run this platform, not a trial version of a
real one.

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

**Always use `config.settings.production`, wherever this is running.** The
development settings module (`config.settings.local`) turns `DEBUG` on, which
prints the site's internals — stack traces, settings, SQL — to whoever is looking
at a broken page, and it forces `ALLOWED_HOSTS` to `*` no matter what you
configured. It is for working on the code, not for an agency's data. Django's
own `manage.py check --deploy` will tell you so; do not wave that away.

1. **Strong database password.** Set `POSTGRES_PASSWORD` in `.env` to a long random value. The dev default (`openh2o`) is rejected in production by design.
2. **`ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`** — set from the answer you wrote down in "What you need before you start":

   | How they reach it | `ALLOWED_HOSTS` | `CSRF_TRUSTED_ORIGINS` |
   |---|---|---|
   | Only this computer | `localhost,127.0.0.1` | leave empty |
   | Their office network | the machine's LAN address, e.g. `192.168.1.40` | leave empty |
   | From outside | the agency's domain | `https://theirdomain` |

3. **Encryption in transit — and the setting that bites if you skip this.**
   Production settings assume HTTPS: `SECURE_SSL_REDIRECT`,
   `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` all default **on**. A
   browser never sends a `Secure` cookie over plain `http://`, so on a
   deployment without HTTPS **every login returns 403 while unauthenticated
   pages render perfectly** — which makes it look like the site works right up
   until someone tries to log in.

   | How they reach it | What to do |
   |---|---|
   | **From outside (public internet)** | Point DNS at the machine and let Caddy issue a certificate automatically. **Never turn the three settings below off on a publicly reachable instance.** (See DEPLOY.md's Caddyfile section.) |
   | **Only this computer, or their office network** | There is no certificate to get and no HTTPS to redirect to. Set all three `False` in `.env` — this is a supported, documented posture, not a workaround: <br>`SECURE_SSL_REDIRECT=False`<br>`SESSION_COOKIE_SECURE=False`<br>`CSRF_COOKIE_SECURE=False` |

   Either way you keep `DEBUG=False`, a real `ALLOWED_HOSTS`, a strong database
   password and the closed-signup default — which is the whole point: the
   security posture follows from **who can reach the instance**, not from where
   it happens to be running.

4. **Limit who can reach it, at the network.** If the answer was *"only this
   computer,"* bind the published port to loopback so nothing else on their
   network can connect — in `docker-compose.yml`, publish `127.0.0.1:80:80`
   rather than `80:80`. Confirm it: from another machine, the address should
   refuse the connection.
5. **Create the admin user.** Either `docker compose exec web python manage.py createsuperuser`, or set `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` in `.env` and let `ensure_superuser` create it on startup.

✋ **Checkpoint:** the site loads at the address the agency will actually use —
`https://theirdomain` for a public deployment, `http://localhost` for a
single-computer one — and you can log in as the admin. Run
`docker compose exec web python manage.py check --deploy` and read what it says:
on a non-public deployment the HTTPS warnings are expected and the reason is
above, but **any warning about `DEBUG` means you are on the wrong settings
module.** Confirm the human has the admin password stored somewhere safe (a
password manager).

**Verify login works (no browser).** Don't test login with plain-HTTP `curl` —
the POST will return 403 no matter what you send, and that is correct behaviour,
not a bug: production settings default `SESSION_COOKIE_SECURE` and
`CSRF_COOKIE_SECURE` to on (`config/settings/production.py`), and a `Secure`
cookie is never sent back over `http://`, so the CSRF check cannot pass. Verify
from inside the container instead:

```bash
docker compose exec web python manage.py shell -c "
from django.test import Client
c = Client(SERVER_NAME='theirdomain', secure=True)   # a host from ALLOWED_HOSTS
                                                    # non-public deployment: use
                                                    # SERVER_NAME='localhost' and
                                                    # drop secure=True
r = c.post('/accounts/login/', {'login': 'ADMIN_EMAIL', 'password': 'ADMIN_PASSWORD'})
print(r.status_code)   # 302 = login works; 200 = form re-rendered (wrong credentials)
"
```

---

## Phase 3 — Load data

**Decide first: does the agency have their own data ready, or do they want to explore the demo first?**

### If you have a browser: use the Setup Wizard at `/setup/`

For a **real basin**, prefer the wizard over the command line. It is a guided
first-run flow that does the whole load in one pass: pick or upload the agency's
boundary as a GeoJSON file, confirm it on a map, run `auto_populate` step by step
with progress on screen, and then **enable the monitoring stations inside that
boundary** — the step that is otherwise easy to miss, because discovery creates
every station switched off.

Find it in the left sidebar under **Administration → Setup Wizard**, or go
straight to `https://theirdomain/setup/`. It is visible to an admin (and on an
instance that has not turned access control on yet, to anyone), so log in as the
admin user from Phase 2 first.

The command-line path below is the alternative for a **headless deployment** —
no browser, SSH only. It reaches the same end state; it just asks you to run each
step yourself.

### Option A — Demo data (always do this first)
```bash
docker compose exec web python manage.py seed_merced   # the Merced Subbasin demonstration
```
This loads the Merced Subbasin demo — a real California basin, the same dataset running at openh2o.com — a fully populated example the agency can click through while you gather their real data. One step fetches hydrography and monitoring stations live from public APIs (a few minutes, no key needed); for real satellite-ET numbers, add an OpenET key and run the ET sync (Phase 4). Each sub-step is idempotent, so re-running is safe.

If you need to **rebuild** the demo later on this same server, add `--allow-prod-clobber`. The operations step regenerates parcel and well geometry, so it refuses a second run over demo rows that already exist unless you say so explicitly. The first run above needs no flag.

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

1. **Activate the stations you intend to keep.** Discovery creates every station
   **inactive**, and `sync_source` only pulls data for active ones — with none
   on it stops and prints *"No active stations for CDEC. Run discover_stations
   first."*, which is misleading advice: discovery is what created those
   inactive rows. Activation, not more discovery, is what it needs. So nothing
   below works until this step has run.

   In a browser: open the Setup Wizard at `/setup/` (Phase 3) and use its enable
   step, which turns on every station inside the boundary you chose.

   Headless, over SSH:
   ```bash
   docker compose exec web python manage.py activate_stations --boundary-name "Their Basin" --dry-run
   docker compose exec web python manage.py activate_stations --boundary-name "Their Basin"
   ```
   `--dry-run` first: it prints the count and a sample and changes nothing. Add
   `--source cdec` to activate one source at a time. Omit `--boundary-name` and
   it falls back to the first boundary and says which one it used, so you can see
   the scope you got. `--all-boundaries` is the only way to activate everywhere,
   and it has to be typed on purpose.

2. **Sync every active source with the right window.** Daily gauges (cdec, usgs)
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

3. **Eliminate the stations that carry no usable data.** This deletes (not just
   hides) any active station without enough readings to chart, plus — with
   `--purge-inactive` — **every station that is still switched off**:
   ```bash
   docker compose exec web python manage.py prune_dataless_stations --delete --purge-inactive --dry-run
   docker compose exec web python manage.py prune_dataless_stations --delete --purge-inactive
   ```
   ⚠️ **`--purge-inactive` deletes the whole inactive discovery net, and it cannot
   tell a dead gauge from one you simply have not activated yet.** It is only
   correct *after* step 1 — once the stations you want to keep are active. Run it
   on a freshly discovered basin and you delete everything discovery just found.

   `--dry-run` first to see what goes. The default keeps any station with ≥2
   published readings; raise `--min-records` if you want a leaner map. Re-run this
   any time after a from-scratch re-seed — discovery re-creates the wide net, so
   activate the keepers again first, then clear the rest.

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
- **Don't** set `ACCOUNT_EMAIL_VERIFICATION=mandatory` on an instance with no mail server. Nothing crashes — signup still succeeds — but the confirmation link is written to the container log instead of an inbox, so nobody except whoever can read that log is able to finish signing up. Leave it unset and it follows `EMAIL_HOST` on its own: confirmation required where SMTP is configured, off where it isn't.
- **Don't** weaken the production security guard to "make it boot." If it's complaining, fix the password or hosts — that's the bug it's catching.
- **Do** keep the in-app "Source code" link pointing at wherever you publish your modified source. The AGPL (Section 13) requires it once the agency runs the platform for users. See [NOTICE](../NOTICE).
