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

<!-- defines: docker -->
1. **A computer to run it on**, with Docker installed. OpenH2O ships as three
   *containers*. A container is a sealed, pre-packed box holding one piece of
   the program plus everything it needs to run, so it behaves the same on any
   computer; Docker is the software that builds and runs those boxes; and this
   platform's three hold the web pages, the database, and the piece that manages
   the address and the encryption. Any of these machines is fine:
   their own machine (Windows, macOS or Linux, with Docker Desktop or OrbStack),
   a rented virtual server, or agency-managed infrastructure. 2–4 GB of memory
   is plenty. **Check Docker works before anything else: `docker run
   hello-world`.** If that fails mentioning "cgroup" or "bpf", the machine's own
   host is blocking those boxes and no setting inside it will fix that — ask
   whoever provisioned it, or take the documented path that needs no Docker at
   all, [INSTALL-WITHOUT-DOCKER.md](INSTALL-WITHOUT-DOCKER.md). That path is
   equally the right answer when the agency would simply rather not install
   Docker on their machine.
2. **How the agency needs to reach it.** Ask directly, and write the answer
   down; every later choice follows from it:
   - *Only from this one computer* <!-- defines: localhost --> — no domain needed. Bind the service to
     loopback — `127.0.0.1`, which along with the word `localhost` means "this
     same computer" and nothing anyone else could type — so nothing else on
     their network can reach it.
   - *From other computers in their office* — no domain needed, but the
     instance is now exposed to their local network. Say so out loud.
   - *From outside — a board member, a consultant, the public* <!-- defines: tls_https --><!-- defines: dns --> — **this is the
     only case that needs a domain name and HTTPS.** *HTTPS* is the
     padlock-icon, encrypted version of a web address; the padlock rests on a
     *certificate*, a file proving the address really is itself. They will need
     a domain or subdomain they control, pointed at this machine through *DNS* —
     the internet's phone book, which turns a web address into the numeric
     address of one specific computer. Pointing a domain at a machine means
     editing one entry in that phone book, called an *A record*, wherever the
     domain was bought.
3. *(Optional, can be added later)* <!-- defines: api_key --><!-- defines: smtp --> API keys for OpenET, CIMIS, and NOAA, and SMTP credentials for password-reset email. An *API key* is a long password-like string that lets this program, rather than a person, fetch data automatically from another organisation's computers — treat it as a secret, exactly like a password. *SMTP* is the agreed method for handing an outgoing email to a mail provider, so the site can send "you forgot your password" messages instead of pretending to be its own mail server; the credentials are the login for that provider. The platform runs fine without any of them; those features simply stay dark until provided.

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

A first-time deployment to a running, secured, demonstration-populated instance is a single working session. Loading an agency's *real* data is the part that takes back-and-forth, because it depends on what data they have.

### Roughly how long it takes, and which steps run long on purpose

Four independent agents have each stood this platform up from nothing and
written down their own timings. **Their figures for reaching a working, secured,
populated instance an administrator could log into run from about 40 minutes to
about an hour**, and the one that also priced out a large parcel import put its
whole session at about an hour and three quarters. Read that as a range and
nothing more: they ran on different hardware, took different routes (one
installed without Docker at all), and one spent most of its clock waiting on a
slow government data service. Do not average them or subtract one from another —
they did not measure the same job.

Loading the agency's *own* records afterwards is a separate, open-ended task.
How long that takes depends entirely on what shape the agency's existing files
are in, and no honest estimate exists in advance.

Several steps take minutes and print a great deal of unfamiliar-looking output
while they work. **That is the step working, not failing** — as long as it
finishes and says so. The ones that legitimately run long:

- **The first build of the program.** A few minutes, once.
- **Loading the demonstration basin.** A few minutes, because part of it fetches
  live hydrography and monitoring stations from public government services
  rather than reading a bundled file.
- **Pulling history from the slower public sources**, once the monitoring
  stations are switched on. In the run that measured it, about 30 minutes across
  all sources, of which the weather-station history from NOAA alone was roughly
  24 minutes for that one source. Almost all of it is unattended waiting on
  someone else's computers, so start it and do other work alongside.
- **A full property-parcel import for a large area.** In the run that priced it,
  a 1,485-square-mile watershed resolved to more than 150,000 parcels and the
  agency declined the import on those grounds. A small service area is minutes;
  a large multi-county one is several hours unattended, and you should budget
  for having to restart it at least once.

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

Three names in that sequence are worth knowing before you explain them to
anybody.

<!-- defines: docker_compose -->
**Docker Compose** is a helper tool, installed alongside Docker, that starts,
stops and rebuilds all three boxes together from a single instruction file
(`docker-compose.yml`) instead of handling each one by hand. Every `docker
compose …` line in this guide is that tool.

<!-- defines: reverse_proxy -->
**Caddy** is a *reverse proxy* — a middleman program that receives the traffic
arriving from outside and relays it inward to the real program — and it is also
what obtains the encryption certificate, by itself, with almost no
configuration. An agency that already runs a proxy of their own ends up with two
in a row: theirs, outside your control, in front of this machine, and Caddy
inside Docker in front of OpenH2O. That is a normal arrangement, not a fault.

<!-- defines: migrations -->
**Migrations** are the step where the program builds or updates the actual
tables inside its database to match what this version of the software expects.
Routine and expected after every install and every update; skip it and you are
left with an empty, unusable database.

✋ **Checkpoint:** `docker compose ps` shows `db` and `web` as `Up (healthy)`, `caddy` as `Up`, and the site responds. Don't move on until it does. Caddy's image defines no health check of its own, so a plain `Up` is the right and only reading for that row — do not wait for it to say healthy.

---

## Phase 2 — Secure it (do this before anyone logs in)

<!-- defines: allowed_hosts -->
This is the phase an AI must not skip. The platform's production settings **refuse to boot** on an empty database password, or on any of four well-known defaults including the development one, or with an empty `ALLOWED_HOSTS` — that guard is your friend; let it enforce the basics. (It checks that short list of known-bad passwords, not password strength, so it is a floor and not a substitute for choosing a real one.) `ALLOWED_HOSTS` and its companion `CSRF_TRUSTED_ORIGINS` are two safety lists in the program's settings: the program refuses to answer unless the web address in the request matches one of them, which stops a stranger tricking it into behaving as a different website. They have to carry the agency's real address exactly, or the site turns every visitor away.

**Always use `config.settings.production`, wherever this is running.** The
development settings module (`config.settings.local`) turns `DEBUG` on, which
prints the site's internals — stack traces, settings, SQL — to whoever is looking
at a broken page, and it falls back to an `ALLOWED_HOSTS` of `*` if you have set
none. It is for working on the code, not for an agency's data. Django's
own `manage.py check --deploy` will tell you so; do not wave that away.

<!-- defines: env_file -->
1. **Strong database password.** Set `POSTGRES_PASSWORD` in `.env` to a long random value. The dev default (`openh2o`) is rejected in production by design. (The `.env` file is a plain text file of NAME=value lines holding this deployment's settings and passwords. It is the one file that makes this installation *this agency's* rather than a generic copy, and it is deliberately kept out of the published copy of the program precisely because it holds secrets.)
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
   | **From outside (public internet)** | Point DNS at the machine, then pick one of two shapes: either this server obtains its own certificate, which means editing the `Caddyfile` to name the domain, or something in front of it — a tunnel, the agency's proxy, a load balancer — already handles the encryption and the `Caddyfile` stays as shipped. **DEPLOY.md §4 has both, and you must read it: pointing DNS alone does not produce a certificate, because the shipped file names no domain.** Never turn the three settings below off on a publicly reachable instance. |
   | **Only this computer, or their office network** | There is no certificate to get and no HTTPS to redirect to. Set all three `False` in `.env` — this is a supported, documented posture, not a workaround: <br>`SECURE_SSL_REDIRECT=False`<br>`SESSION_COOKIE_SECURE=False`<br>`CSRF_COOKIE_SECURE=False` |

   Either way you keep `DEBUG=False`, a real `ALLOWED_HOSTS`, a strong database
   password and the closed-signup default — which is the whole point: the
   security posture follows from **who can reach the instance**, not from where
   it happens to be running.

4. **Limit who can reach it, at the network.** <!-- defines: port --> A *port* is a numbered door on
   the computer that one particular kind of traffic knocks on: port 80 is the
   plain, unencrypted web door, the one a browser uses when nobody types a
   number at all, and port 443 is the encrypted one. If the answer was *"only
   this computer,"* bind the published port to loopback so nothing else on their
   network can connect — in `docker-compose.yml`, publish `127.0.0.1:80:80`
   rather than `80:80`. Confirm it: from another machine, the address should
   refuse the connection.
5. **Create the admin user** <!-- defines: superuser --> — in this software a *superuser*, the one account
   that can do anything: add other staff accounts, change settings, see
   everything. It is separate from and unrelated to any login for the computer
   itself, and it has to be created by hand before anyone can sign in at all;
   there is no "first visitor becomes the administrator" magic. Either `docker compose exec web python manage.py createsuperuser`, or set `DJANGO_SUPERUSER_EMAIL` / `DJANGO_SUPERUSER_PASSWORD` in `.env` and let `ensure_superuser` create it on startup.

✋ **Checkpoint:** the site loads at the address the agency will actually use —
`https://theirdomain` for a public deployment, `http://localhost` for a
single-computer one — and you can log in as the admin. Run
`docker compose exec web python manage.py check --deploy` and read what it says:
on a non-public deployment the HTTPS warnings are expected and the reason is
above, but **any warning about `DEBUG` means you are on the wrong settings
module.** Confirm the human has the admin password stored somewhere safe (a
password manager).

**Verify login works (no browser).** Don't test login with plain-HTTP `curl`
wherever `CSRF_COOKIE_SECURE` is left on — which is its default and the right
setting for any instance reached over HTTPS. There the POST returns 403 whatever
you send, and that is correct behaviour, not a bug: a cookie marked `Secure` is
never sent back over `http://`, so the browser-safety check cannot pass. (On a
single-computer instance, where step 3 above turns that setting off on purpose,
a plain-HTTP login can succeed — so a passing `curl` there proves less than it
looks.) Verify from inside the container instead, which works on every shape:

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

**Decide first: does the agency have their own data ready, or do they want to explore the demonstration first?**

<!-- defines: seed_data -->
Either way the first thing that happens is *seeding* — loading a starting set of
data into an empty database. That covers two different things here: the small
reference lists such as units and categories that every deployment needs, and a
whole demonstration dataset, which exists so there is something to look at
before the agency's own records arrive.

### If you have a browser: use the Setup Wizard at `/setup/`

<!-- defines: geojson -->
For a **real basin**, prefer the wizard over the command line. It is a guided
first-run flow that does the whole load in one pass: pick or upload the agency's
boundary as a *GeoJSON* file — a plain-text format for describing a shape drawn
on a map, along with a few labelled facts about it such as a name and an area,
and non-proprietary enough that a GIS contractor can hand over one file and
expect any capable program to read it — confirm it on a map, run `auto_populate` step by step
with progress on screen, and then **enable the monitoring stations inside that
boundary** — the step that is otherwise easy to miss, because discovery creates
every station switched off.

Find it in the left sidebar under **Administration → Setup Wizard** — that whole
block is hidden until you switch the sidebar out of its everyday view, using the
two-button toggle at the **bottom of the left sidebar** marked **Operations** and
**Admin**; click **Admin**. Not having clicked it is the usual reason someone
cannot find the wizard. Or go straight to `https://theirdomain/setup/`. You have to be signed
in either way: an anonymous visitor is sent to the login page whatever else is
configured. So log in as the admin user from Phase 2 first.

The command-line path below is the alternative for a **headless deployment** —
no browser, SSH only. It reaches the same end state; it just asks you to run each
step yourself.

### Option A — Demo data (always do this first)
```bash
docker compose exec web python manage.py seed_merced   # the Merced Subbasin demonstration
```
This loads the Merced Subbasin demo — a real California basin, the same dataset running at openh2o.com — a fully populated example the agency can click through while you gather their real data. One step fetches hydrography and monitoring stations live from public APIs (a few minutes, no key needed); for real satellite-ET numbers, add an OpenET key and run the ET sync (Phase 4). Each sub-step is *idempotent* <!-- defines: idempotent --> — running it five times ends up the same as running it once, because it notices what is already done and skips it rather than duplicating or breaking anything — which is why re-running one after an interruption is safe.

**Then load the bundled station catalog.** The seed finds the basin's monitoring stations by calling the agencies that publish them, and creates every one of them switched **off** — so a freshly seeded demonstration reports "0 of 0 stations reporting" until somebody turns them on. The demonstration's own list of stations ships with the platform — 335 of them, 42 switched on, and 50 of the 335 (all 42 of the active ones, plus 8 others) carrying the real date they last published a reading — and one command loads it:

```bash
docker compose exec web python manage.py load_station_fixture   # the stations openh2o.com shows
```

It calls nobody, so it works on a machine with no way out to the internet, and running it twice changes nothing. `seed_merced` deliberately leaves it to you: a real agency standing this up against its own basin wants its **own** stations found, not Merced's — which is what the curation step in Phase 4 is for.

If you need to **rebuild** the demo later on this same server, add `--allow-prod-clobber`. The operations step regenerates parcel and well geometry, so on a production instance (`DEBUG=False`, which is what Phase 2 sets) it refuses a second run over demo rows that already exist unless you say so explicitly. ⚠ Under development settings that guard does not fire at all — a second run there rebuilds the geometry silently, hand-adjusted boundaries and all. The first run above needs no flag either way.

### Option B — Their real data
Three import routes, in rough order of preference:

| If they have… | Use | Notes |
|---|---|---|
| Parcel boundaries as GeoJSON/Shapefile | `import_parcels` | Required foundation — everything hangs off parcels |
| A well list as CSV | `import_wells` | Optional but valuable |
| Historical ledger entries as CSV | `import_ledger_csv` | For bringing records over from a prior system |
| Only a basin boundary | `auto_populate` | Queries DWR and USGS to pull parcels, boundaries, and flowlines automatically |

What still has to be entered by hand (no public source exists): **water rights**, **water accounts**, and **allocations**. They are not all in one place. Accounts and allocations each have a create form on the accounting pages. **Water rights have no create form in the app at all** — they are added through the Django admin at `/admin/`, which is worth knowing before you promise an agency a screen that does not exist.

✋ **Checkpoint:** confirm with the human which parcels are theirs and that the boundary looks right on the map before building accounts on top of it.

---

## Phase 4 — Connect live data sources

### Before you spend the agency's satellite-data allowance — stop and ask

**The OpenET key an agency hands you does not buy unlimited data.** It carries a
fixed number of requests per month, the count resets on the first, and the
number is smaller than most people assume. The allowance belongs to the
*account*, not to this deployment, so it is shared: anything spent here is gone
from anything else using the same key, which may be a colleague's work or
another instance entirely. It is not a spending limit in money — going over
costs nothing and simply stops working until the month turns over — but it is
hard-capped, and there is no buying your way past it mid-month.

That makes the first satellite-ET run a judgment call, and **it is a judgment
the software does not make for you.** Running it against the Merced
demonstration produces consumptive-use figures for a basin this agency does not
manage, and spends part of the month's allowance to do it. Running it against
the agency's own basin produces the numbers they actually need. Three of the
four independent agents who deployed this platform reached that fork on their
own and all three left the satellite feed switched off until real data was
loaded — and not one of them was prompted to think about it by these documents,
which is why the prompt is here now.

**So: load the agency's own parcels first, then turn on satellite ET.** If
somebody does want to see the demonstration's consumptive-use figures filled in,
say out loud what it will take from the month's allowance before you run it, and
let the agency decide. You do not have to guess at the figure: OpenH2O asks
OpenET for the account's own numbers rather than assuming them, and the
monitoring dashboard shows how many requests have gone this month out of the
allowance — with a line on the card saying whether that count came from OpenET
itself or is this platform's own estimate because OpenET did not answer.

### Keys, then the schedule

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

**What the platform actually enforces is two tiers, not three.** A user is
either an administrator or is not. Administrators reach the admin-only screens;
everyone else is turned away from those and works normally everywhere else. That
is the whole of it, and it is what the closed-signup default rests on.

The reference data does create three named roles — admin, manager, viewer — and
they are visible in the admin. **Assigning one changes nothing about what a
person can do.** They are left over from an earlier design, kept only so that
removing them would not require a destructive database change. Do not build a
handover around them and do not promise an agency that "viewer" is read-only,
because it is not.

Set expectations on the two tiers instead: who needs to administer this, and who
just uses it.

Then walk them through the first loop: log in → confirm their boundary → review their accounts, allocations, and recorded data. If the agency files with the state, show the optional reporting step too: open the reporting page → generate a draft GEARS or CalWATRS CSV, making clear that OpenH2O *prepares* the filing; a certifying official reviews and submits it in the state portal.

**Before the first password reset, check what name the mail goes out under.** Every email the platform sends carries this deployment's own name at the front of the subject line — the first thing the recipient reads. The platform works that name out for itself, from the agency name typed into the Setup Wizard and the web address already in `ALLOWED_HOSTS`, and writes it down when the migration step runs. Confirm it landed:

```bash
docker compose exec web python manage.py shell -c "from django.contrib.sites.models import Site; s = Site.objects.get_current(); print(s.name, '|', s.domain)"
```

Expect the agency's name and their web address. If either still reads `example.com`, fill in whichever is blank — the agency name in the Setup Wizard, the address in `.env` — then run `docker compose exec web python manage.py migrate` and look again. `manage.py check` will also say so, as `openh2o.W002`.

✋ **Done when:** an agency staffer can log in and see and manage their own basin data without you — and, if they report to the state, produce a draft report.

---

## Troubleshooting by symptom

<!-- defines: geospatial_libraries -->
One row below names **GDAL, GEOS and PROJ**: widely-used open-source code
libraries that do the actual geometry and map arithmetic — parcel boundaries,
well locations, distances on a curved earth. Nobody ever interacts with them
directly; the software simply will not start without them, and inside Docker
they install themselves as part of the build, which is why a failure there is a
build problem rather than something to configure.

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
- **Never** run `make fresh` on a populated instance — it destroys the database volume. Use `docker compose up -d --build` for routine rebuilds. `make up` is not the answer here: on a checkout that has created the `.production-lock` marker (which DEPLOY.md §11 tells a live deployment to do), `make up`, `make down`, `make build` and `make fresh` all refuse to run. That refusal is the guard working.
- **Don't** set `ACCOUNT_EMAIL_VERIFICATION=mandatory` on an instance with no mail server. Nothing crashes — signup still succeeds — but the confirmation link is written to the container log instead of an inbox, so nobody except whoever can read that log is able to finish signing up. Leave it unset and it follows `EMAIL_HOST` on its own: confirmation required where SMTP is configured, off where it isn't.
- **Don't** weaken the production security guard to "make it boot." If it's complaining, fix the password or hosts — that's the bug it's catching.
- **Do** keep the in-app "Source code" link pointing at wherever you publish your modified source. The AGPL (Section 13) requires it once the agency runs the platform for users. See [NOTICE](../NOTICE).
