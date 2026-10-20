<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# AI Operator Guide

This guide is for an AI agent, or the person directing one, setting up OpenH2O for
an organization. It takes you from a bare computer to a running site that the
organization's staff can sign in to and use. [DEPLOY.md](../DEPLOY.md) is the
reference for each command. This guide says what to ask the organization, what to
choose and in what order to work.

Work through the five phases in order. At each ✋ checkpoint, stop and confirm with
the person you are working for before you go on.

---

## What you need before you start

OpenH2O runs the same way on an office computer, on a rented server costing about
$15 a month and in an organization's own data center. OpenH2O supports all three,
and this guide covers each of them. The security settings depend only on who needs
to reach the site, and Phase 2 sets them from the answer.

Ask the person for three things.

<!-- defines: docker -->
1. **A computer to run it on, with Docker installed.** Docker is software that runs
   programs in *containers*. A container holds one part of a program together with
   everything that part needs, so it runs the same way on any computer. OpenH2O
   runs as three containers: the website, the database, and the program that
   receives web traffic and handles the encryption. <!-- defines: postgis --> The
   database is the open-source PostgreSQL with PostGIS, its extension for map data.
   The computer can be a rented virtual server, a server the organization manages,
   or the person's own Windows, macOS or Linux machine running Docker Desktop or
   OrbStack. A computer with 2 to 4 GB of memory is enough. Check that Docker works
   before anything else:

   ```bash
   docker run hello-world
   ```

   If the command fails with a message about "cgroup" or "bpf", the system that
   hosts the machine is blocking containers, and no setting on the machine can fix
   it. Ask whoever provisioned the machine, or install OpenH2O without Docker by
   following [INSTALL-WITHOUT-DOCKER.md](INSTALL-WITHOUT-DOCKER.md). Follow that
   guide too when the organization prefers not to install Docker.

2. **Who needs to reach the site.** Ask this directly and write the answer down,
   because Phase 2 depends on it. There are three answers.
   - <!-- defines: localhost --> *Only this one computer.* The site needs no domain
     name. Its address is `localhost`, the name a computer uses for itself, and
     `127.0.0.1` is the same address in numbers. No other computer can reach it.
   - *Other computers in the office.* The site needs no domain name. It answers at
     the computer's address on the office network, such as `192.168.1.40`. Tell the
     person that anyone on that network will be able to reach the site.
   - <!-- defines: tls_https --><!-- defines: dns --> *People outside the office,
     such as a board member, a consultant or the public.* This is the only case that
     needs a domain name and HTTPS. HTTPS is the encrypted connection that a browser
     marks with a padlock. It depends on a *certificate*, a file that proves the
     address belongs to this site. The organization needs a domain or subdomain that
     it controls. DNS is the internet's directory, which turns a web address into
     the numeric address of one computer. To point a domain at a computer, sign in
     at the company where the domain was bought and edit the domain's *A record*,
     the DNS entry that holds the computer's address.

3. <!-- defines: api_key --><!-- defines: smtp --> **API keys and email settings.**
   These are optional and can be added later. An *API key* is a long password that
   lets OpenH2O fetch data from another organization's service without a person
   signing in. CIMIS, NOAA and OpenET each need one. Keep each key secret. *SMTP* is
   the standard way a program hands outgoing email to a mail provider. With an SMTP
   account, the site can send password-reset emails. OpenH2O runs without keys or
   email settings, and each feature that needs one stays off until someone adds it.

If the organization wants people outside the office to reach the site and has no
server or domain yet, help it rent a virtual server and register a domain. If it
wants the site on one computer or on the office network, it needs no server or
domain, and the result is a complete OpenH2O installation.

---

## The shape of the job

```
Phase 1  Start the platform     → the three containers running
Phase 2  Secure it              → passwords, the site's address, HTTPS where needed, an administrator
Phase 3  Load data              → the demonstration first, then the organization's own records
Phase 4  Connect live data      → API keys, monitoring stations, the schedule
Phase 5  Bring in the people    → accounts and roles, a first walkthrough
```

Loading the organization's own records takes the longest, because it depends on the
files the organization has. Expect several rounds of questions about them.

### The steps that run long

Several steps print a great deal of unfamiliar output while they work. The output is
normal as long as the step finishes and reports that it finished. These steps take
the longest:

- The first build, which downloads and installs the software OpenH2O runs on.
- Loading the demonstration, because one of its steps downloads streams and
  monitoring stations from public government services.
- The first sync of past readings from the slower public sources in Phase 4, which
  runs only as fast as those services answer. Start it and do other work while it
  runs.
- A parcel download for a large area, which can run for hours. If it stops partway,
  `auto_populate --resume-from` picks it up again (Phase 3).

---

## Phase 1: Start the platform

Sections 1 to 6 of [DEPLOY.md](../DEPLOY.md) give every step in full. In short:

```bash
git clone https://github.com/Open-H2O/openh2o.git
cd openh2o
cp .env.example .env
```

<!-- defines: repository -->
The first command copies OpenH2O's *repository* onto the computer. The repository is
every file of the program, with the history of every change, and it is published on
GitHub, a website that hosts such projects.

<!-- defines: env_file --><!-- defines: secret_key -->
The `.env` file holds this site's settings and passwords, one `NAME=value` line
each. Each installation has its own `.env` file, and git is set to ignore it so that
its secrets stay out of the published code. Before the first start, change two
values in it:

- `SECRET_KEY` is the key the site signs its sign-in cookies with. Generate one with
  the command at the top of the file and paste it in.
- `POSTGRES_PASSWORD` is the database password. The file ships with the password
  set to `openh2o`, and OpenH2O will not start with that password under the
  production settings. Set a long random value. The database stores its password
  when it is first created, so set `POSTGRES_PASSWORD` before the first start.
  Changing the value in `.env` later does not change the password the database
  already holds.

Phase 2 sets the rest of the file.

`OPENH2O_MODULES` chooses which sections of OpenH2O the site runs. When `.env` does
not set it, the site runs every section except reporting. The reporting section is
under development and off by default. It writes figures in California's reporting
format. OpenH2O does not submit reports to the state. To run fewer sections, list
the ones the organization uses, separated by commas. The sections are `core`,
`geography`, `parcels`, `wells`, `measurements`, `standards`, `accounting`,
`surface`, `recharge`, `datasync`, `reporting`, `health`, `setup`,
`infrastructure`, `feedback` and `drinking`, and the project layout in
[README.md](../README.md) says what each one holds. The list must include `core`,
`geography`, `measurements` and `standards`. If the list leaves out a section that
another section needs, the site does not start, and its error message names the
missing section.

Start the containers and load the reference lists:

```bash
docker compose up -d --build
docker compose exec web python manage.py seed_data   # reference lists; safe to run again
```

<!-- defines: docker_compose -->
Docker Compose is a tool installed with Docker. It starts, stops and rebuilds the
three containers together from one file, `docker-compose.yml`. Every command in
this guide that begins `docker compose` uses it.

<!-- defines: reverse_proxy -->
Caddy is the container that receives web traffic. It is a *reverse proxy*, a
program that receives requests from outside and passes them to the website behind
it. Caddy can also obtain the site's certificate by itself (Phase 2). Some
organizations already run a proxy of their own in front of their servers. In that
case the organization's proxy sits in front of this computer, Caddy sits behind it
in front of OpenH2O, and OpenH2O works normally.

<!-- defines: migrations -->
Each time the website container starts, it runs the *migrations*, which create or
update the database tables to match this version of OpenH2O. You can run
`docker compose exec web python manage.py migrate` by hand at any time, and it
changes nothing when the tables are up to date. Starting the container also creates
the administrator account when `.env` holds the two settings in Phase 2, step 5.

<!-- defines: seed_data -->
To *seed* a database is to load a starting set of records into it. `seed_data`
loads the reference lists every site needs, such as units and categories. Phase 3
seeds the demonstration data.

✋ **Checkpoint:** `docker compose ps` shows `db` and `web` as `Up (healthy)` and
`caddy` as `Up`. The compose file gives Caddy no health check, so its row shows only
`Up`. Wait until all three rows show these states before you go on.

---

## Phase 2: Secure it

Do this phase before anyone signs in.

<!-- defines: allowed_hosts -->
Under the production settings, OpenH2O refuses to start when `SECRET_KEY` is
missing, when `ALLOWED_HOSTS` is empty, or when the database password is empty or
one of four common defaults (`openh2o`, `postgres`, `password` and `changeme`). The
check looks only for those four values and does not measure a password's strength,
so choose a long random one. `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` are two lists
of web addresses. OpenH2O answers only requests sent to an address on the first
list. The second list holds the `https://` addresses from which OpenH2O accepts a
submitted form, such as the sign-in form. Each list has to hold the address people
will use.

Use the production settings, `config.settings.production`, on every site.
`DJANGO_SETTINGS_MODULE` in `.env` chooses the settings, and the file ships set to
the production settings. The development settings, `config.settings.local`, turn on
`DEBUG`. With `DEBUG` on, any error page shows its reader the site's error traces,
settings and database queries. Under the development settings the site also answers
at any address when `ALLOWED_HOSTS` is empty. Use them only for work on the code,
never on a site that holds an organization's records. `manage.py check --deploy`
warns about them. If it does, switch the site to the production settings.

1. **The database password and the secret key.** Phase 1 set both. Confirm that
   `POSTGRES_PASSWORD` is a long random value and that `SECRET_KEY` is the one you
   generated.

2. **`ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`.** Set them from the answer you
   wrote down before you started:

   | Who needs to reach it | `ALLOWED_HOSTS` | `CSRF_TRUSTED_ORIGINS` |
   |---|---|---|
   | Only this computer | `localhost,127.0.0.1` | leave empty |
   | The office network | the computer's address on that network, such as `192.168.1.40` | leave empty |
   | People outside | the organization's domain, such as `water.example.org` | `https://` and the domain, such as `https://water.example.org` |

3. **HTTPS, and the three settings that depend on it.** The production settings
   assume HTTPS. `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE` and
   `CSRF_COOKIE_SECURE` are all on by default. A browser sends a cookie marked
   secure only over `https://`. With these settings on and no HTTPS, every sign-in
   fails with a 403 error, even though the pages that need no sign-in still load.

   | Who needs to reach it | What to do |
   |---|---|
   | People outside | Choose one of the two setups in section 4 of [DEPLOY.md](../DEPLOY.md). In the first, Caddy obtains the certificate: point the domain's A record at this computer and name the domain in the `Caddyfile`. In the second, a tunnel, the organization's own proxy or a load balancer in front of this computer handles the encryption, and the `Caddyfile` stays as shipped. The shipped `Caddyfile` names no domain, so pointing DNS at the computer produces no certificate by itself. Keep the three settings on. |
   | Only this computer, or the office network | There is no certificate to obtain. Turn the three settings off in `.env`: <br>`SECURE_SSL_REDIRECT=False`<br>`SESSION_COOKIE_SECURE=False`<br>`CSRF_COOKIE_SECURE=False` |

   After you change `.env`, run `docker compose up -d` so the website container reads
   the new values. In every setup, keep `DEBUG` off, keep `ALLOWED_HOSTS` set to the
   site's own address, keep the strong database password and leave sign-up closed.
   People then get their accounts from an administrator (Phase 5). Who can reach the
   site decides the HTTPS settings. The size and kind of computer leave them
   unchanged.

4. **Limit who can reach the site on the network.** <!-- defines: port --> A *port*
   is a numbered entry point on a computer for one kind of network traffic. Port 80
   carries plain web traffic, and port 443 carries encrypted web traffic. As
   shipped, `docker-compose.yml` opens both on every network the computer is
   connected to. If only this computer needs the site, change the two lines in
   `docker-compose.yml` from `80:80` and `443:443` to `127.0.0.1:80:80` and
   `127.0.0.1:443:443`, then run `docker compose up -d`. From a second computer, try
   to open the site and confirm that the connection is refused. For the office
   network, leave both lines as they are, and tell the person that anyone on that
   network can reach the site.

5. **Create the administrator account.** <!-- defines: superuser --> The first
   account is a *superuser*, an account that can do everything in OpenH2O,
   including adding the other staff accounts. It is an OpenH2O account and is
   separate from any login to the computer. The Users page calls it a *host
   administrator*. A host administrator can also use the administration site at
   `/admin/`. Nobody can sign in until it exists. Give it an email address that
   someone reads, because password-reset emails go to that address once the site
   has SMTP settings. Create it in one of two ways:
   - Run `docker compose exec web python manage.py createsuperuser` and answer its
     questions.
   - Or set `DJANGO_SUPERUSER_EMAIL` and `DJANGO_SUPERUSER_PASSWORD` in `.env` and
     run `docker compose up -d`. The website container creates the account from
     those two settings when the site does not have an active host administrator. While the
     site has one, the container does not change any account. After the
     administrator first signs in, they change the password on their profile page.
     Keep both lines in `.env`, so a wiped site gets the account back at its next
     start.

✋ **Checkpoint:** the site loads at the address the organization will use. For a
public site the address is `https://` and the domain. For one computer it is
`http://localhost`, and for the office network it is `http://` and the computer's
address on that network. You can sign in as the administrator. Run
`docker compose exec web python manage.py check --deploy` and read its warnings. On a
site without HTTPS, expect the HTTPS warnings, because step 3 turned those settings
off. A warning about `DEBUG` means the site is running the development settings.
Confirm that the person has stored the administrator's password somewhere safe, such
as a password manager.

To check sign-in without a browser, run the command below inside the website
container. Where `CSRF_COOKIE_SECURE` is on, a plain `curl` over `http://` cannot
test sign-in. The sign-in returns 403 whatever you send, because the cookie it needs
travels only over HTTPS. The command below works in every setup:

```bash
docker compose exec web python manage.py shell -c "
from django.test import Client
c = Client(SERVER_NAME='water.example.org', secure=True)
r = c.post('/accounts/login/', {'login': 'ADMIN_EMAIL', 'password': 'ADMIN_PASSWORD'})
print(r.status_code)
"
```

In place of `water.example.org`, give an address from `ALLOWED_HOSTS`. On a site
without HTTPS, use `SERVER_NAME='localhost'` and leave out `secure=True`. `localhost`
works on every site, because the production settings add it to `ALLOWED_HOSTS`. Put
the administrator's email address and password in place of `ADMIN_EMAIL` and
`ADMIN_PASSWORD`. The command prints 302 when the sign-in works. It prints 200 when
the sign-in form came back, which usually means the email address or password is
wrong.

---

## Phase 3: Load data

Start by asking the person whether the organization has its records ready or wants
to explore the demonstration first. The demonstration's records stay on the site
beside the organization's, and OpenH2O has no command that removes them. If the
organization wants its site without them, explore the demonstration on a second
copy of OpenH2O, on a laptop for example, and keep the organization's site for its
own records.

The Setup Wizard comes first in either case. It sets the area the site covers.

### The Setup Wizard

The Setup Wizard at `/setup/` sets the area the site covers and fills that area in
from public sources. Use it when you have a browser. Only an administrator can open
it, so sign in as the administrator first. In the left sidebar, the Operations and
Admin switch sits at the bottom. Click **Admin**, then click **Setup Wizard** under
Administration. The Administration section is hidden in the Operations view, and
that is the usual reason someone cannot find the wizard. You can also go straight
to `/setup/`.

<!-- defines: geojson -->
The wizard's first step offers four choices:

1. Select a boundary already on the site.
2. Upload a boundary file: a zipped shapefile, a KML file or a GeoJSON file. GeoJSON
   is a plain-text format for map shapes and the facts attached to them, such as a
   name and an area. Most GIS programs can write it.
3. Type the north, south, east and west edges of the area in decimal degrees. The
   wizard draws a rectangle from them.
4. Start without a boundary. Everything except the map and the populate step works
   without one, and you can come back to `/setup/` later.

The second step shows the boundary on a map for the person to confirm. The third
step lists the populate steps with each box ticked. The populate steps download
basins, parcels, streams and monitoring stations for the area from public services.
Untick any the organization does not want, or click "I have my own data" to untick
them all. Then run the steps that are still ticked. The
[Data import guide](DATA-IMPORT.md) lists each populate step and its source. When
the steps finish, the wizard lists the monitoring stations inside the boundary, each
with its own switch, and offers **Enable all**. Click it, because the populate step
creates every station switched off.

On a server you reach only over SSH, run the same steps as commands.
`import_boundary` reads only GeoJSON, so convert a shapefile or a KML file to
GeoJSON first. `auto_populate` then fills the area in from public sources, and
`activate_stations` turns on the stations that `auto_populate` found (Phase 4). If
the parcel or stream download stops partway, its failure message gives the last
OBJECTID it reached. Run `auto_populate` again with `--steps parcels` or
`--steps flowlines` and `--resume-from` that number. The Data import guide shows
each command, including the `docker compose cp` step that copies a file into the
container.

### Option A: The demonstration data

```bash
docker compose exec web python manage.py seed_merced           # the demonstration data
docker compose exec web python manage.py load_station_fixture  # the demonstration's monitoring stations
```

`seed_merced` loads the demonstration, a real groundwater basin with published
records and invented sample data. It gives the organization a complete site to
explore while you gather its own records. One of its steps downloads streams and
monitoring stations from public government services and needs no key. On a
computer with no internet connection, first load the stored streams with
`python manage.py seed_merced_base` and
`python manage.py loaddata data/merced/flowlines.json`, then add
`--skip-auto-populate` to leave the download out.

The populate step creates every station it finds switched off, so the
demonstration's monitoring pages show no stations reporting until the stations are
turned on. `load_station_fixture` loads the demonstration's own station list, which
ships with OpenH2O. The list holds 335 stations. 42 of them are switched on, and
each of those carries the date it last published a reading. The command downloads
nothing, and a second run changes nothing. For the organization's own area, turn the
stations on as Phase 4 describes.

To rebuild the demonstration later on the same site, add `--allow-prod-clobber` to
`seed_merced`. One of its steps deletes and redraws the demonstration's parcel
outlines and well locations. Because of that step, under the production settings
`seed_merced` will not run over existing demonstration records unless you add the
flag. Under the development settings it redraws them without asking, including any
outline someone has edited. A first run needs no flag.

### Look at the organization's records first

Before you load anything, read the organization's existing files and ask how it
keeps its records. OpenH2O is built to import records in the form the organization
already keeps them.

As you go, fill in the worksheet `docs/crosswalk-worksheet.csv`. Add a row for each
file the organization gives you, with these columns:

- the file's own name;
- the kind of record it holds;
- the column that identifies each record;
- the unit of its numbers;
- the period it reports by, such as a water year, a calendar year or a season;
- the OpenH2O screen or command that imports it;
- the conversions that apply.

The first row is a filled-in example. When the worksheet is done, you know what each
file needs before you import it.

The [Data import guide](DATA-IMPORT.md) describes each import: the layouts it
reads, the columns it matches and the conversions it makes, such as gallons, CCF
and cfs-hours to acre-feet. Some answers are not in any file, and only a person at
the organization can give them. Ask these questions and record each answer in the
place the table gives:

| Ask the person | Where the answer goes |
|---|---|
| Which unit the delivery records use, such as a miner's inch | OpenH2O has no field for a miner's inch. Convert the figures to acre-feet, or to cfs and hours, before you import them. |
| Which headgate is which point of diversion | The point of diversion's local name, on its edit page. The point's page then shows it as "known locally as" that name. |
| How to count the `USE` rows in California's Water Use Reported export: left out, as water returned, or as direct diversions | The diversion import screen asks on its preview when a file has `USE` rows, and it keeps the answer for the next file. |
| Which parcels each point of diversion serves, and the share of each when two water rights serve one field | The share on the link between the point and the parcel, set on the point's own page. |
| Each measuring device's nickname, calibration date and accuracy | The device record, from **Add device** on the point's own page. |
| Which year a season belongs to | The report-year setting on the Delivery Settings page (`/accounting/delivery-settings/`), under Diversion records. It is set once for the whole site. |
| The unit of the rows in a production file whose unit is blank | **Unit for rows with a blank unit**, on the preview of the production import screen. |
| Which facility each name in the organization's files means | The facility's local name, on its add or edit page under Drinking Water facilities. |
| Whether any laboratory results exist only on paper | A CSV file with the lab import's columns, typed up from the paper and imported at `/drinking/import/`. |
| Which meter feeds which water source | The source column of the production file: one of the six source columns of a monthly log, or `TypeCode` in an export of California's Electronic Annual Report (eAR). |
| Whether the organization wants OpenH2O to hold its sampling schedule | The Schedule page under Drinking Water, from **+ Add row**. |

### Option B: The organization's own records

Each kind of record has its own import screen or command, and several have both.
The table lists them in the order to load them. The Data import guide describes each
one in full.

| The organization has | Use | Notes |
|---|---|---|
| Only a boundary | `import_boundary`, then `auto_populate` | `import_boundary` loads a GeoJSON boundary file. `auto_populate` then downloads basins, parcels, streams and monitoring stations for that boundary, which must already be on the site. |
| Parcel outlines, as GeoJSON or a shapefile | `import_parcels` | Water accounts link to parcels, so import the parcels before you create accounts. |
| A list of wells, as a CSV file | The import screen at `/infrastructure/import/?type=well`, or `import_wells` | Both create the same records. The screen asks you to match the file's columns first. |
| A list of water rights | `/surface/rights/import/` | It reads a CSV file. Import the water rights before the points of diversion. |
| Points of diversion, as a CSV, GeoJSON, KML or shapefile | The same import screen as the wells, at `/infrastructure/import/?type=diversion` | |
| Storage ponds or recharge sites | The same import screen, with `?type=storage` or `?type=recharge_site` | No page links to the storage pond import yet, so type its address. |
| A public water system, by its PWSID | `/drinking/onboard/` | A PWSID is the identification number of a public water system in EPA's records. The page looks the system up in EPA's Envirofacts records and adds the system and its facilities. Add the sampling points on the page that follows. |
| Laboratory results | `/drinking/import/` | It matches the column headings of California's Division of Drinking Water and several headings that commercial labs use. |
| A year of production by month and source | `/drinking/production/import/`, or `import_production` | It reads an eAR export or a monthly log. The screen saves to the first water system on the site. A site with several water systems imports with the command, which takes `--pwsid` to name the system. |
| Past ledger entries, as a CSV file | `import_ledger_csv`, or the Upload CSV page of the Use Ledger (`/accounting/ledger/upload/`) | The Upload CSV page imports the file at once unless you tick Dry run. |
| A year of diversion volumes, in California's Water Use Reported export or the organization's own book of deliveries | `/surface/diversion/import/`, or `import_diversion_records` | OpenH2O tells the two layouts apart by their column headings, and the preview names every conversion. Set the report year first, as the next paragraph describes. |

Before you import diversion records, ask how the organization counts a reporting
year: as a water year, a calendar year, or an irrigation season that starts in a
month it chooses. Set the answer on the Delivery Settings page
(`/accounting/delivery-settings/`), under Diversion records. That part of the page
appears only when the site runs the `surface` section.

Water accounts and allocations have no import. Create them on their pages under
Accounting. OpenH2O has no page yet for entering water-level readings at a well or
readings at a monitoring station. Someone with a staff account, such as the
superuser from Phase 2, can add them on the administration site at `/admin/`. The
Data import guide lists every record that is entered by hand and the page for each.

✋ **Checkpoint:** before you create accounts, confirm with the person that the
boundary looks right on the map and which parcels the organization's accounts will
cover.

---

## Phase 4: Connect live data sources

### Ask before you spend the OpenET allowance

An OpenET key comes with a fixed number of requests each month, and the count
starts again on the 1st. Every site or program that uses the same key draws on the
same allowance.

<!-- defines: openet_budget -->
OpenH2O counts this site's requests to OpenET. It stops sending them when the
month's count reaches `OPENET_MONTHLY_BUDGET`, which is 100 unless `.env` sets
another number. If the organization's account allows more requests, raise
`OPENET_MONTHLY_BUDGET` in `.env` to match. The count leaves out requests from
anything else that uses the same key. The monitoring dashboard
(`/datasync/monitoring/`) shows how many requests the site has used this month. It
shows OpenET's own count when OpenET answers and OpenH2O's count when it does not,
and it says which one you are seeing.

Let the organization decide when to make the first satellite ET run. A run against
the demonstration spends part of the month's allowance on an area the organization
does not manage. A run against the organization's own parcels produces the figures
it needs. Load the organization's own parcels first, then fetch satellite ET. If
someone wants the demonstration's ET figures filled in, say how many requests the
run will use before you start it, and let the organization decide.

```bash
docker compose exec web python manage.py sync_openet_parcels --start-date 2025-10-01 --end-date 2026-09-30 --dry-run
docker compose exec web python manage.py sync_openet_parcels --start-date 2025-10-01 --end-date 2026-09-30
```

Set `--start-date` to the first day of the first month you want and `--end-date` to
the last day of the last month. The dry run lists the parcels the command would ask
OpenET about, and it sends nothing. Count on at least one request for each parcel.
`--parcel-prefix` limits the run to parcels whose number starts with the letters you
give, and `--limit` caps the number of parcels for a small first test. The command
stores the estimates, and `--to-ledger` also writes them to the ledger.

### Keys and the schedule

USGS, CDEC (the California Data Exchange Center) and the Department of Water
Resources' Water Data Library and SGMA Portal need no key. CIMIS (the California
Irrigation Management Information System) needs `CIMIS_API_KEY`. NOAA's climate data
needs `NOAA_CDO_TOKEN`, and OpenET needs `OPENET_API_KEY`. The comments in
`.env.example` say where to get each key. Add each key to `.env` and run
`docker compose up -d`. The monitoring dashboard shows a source whose key is missing
as "needs key".

<!-- defines: cron -->
The schedule in `crontab.txt` runs on cron, the scheduler built into Linux and
macOS. At the top of `crontab.txt`, set `OPENH2O_DIR` to the folder that holds this
site's `docker-compose.yml`, and set `OPENH2O_LOG_DIR` to a folder for the logs.
Then install it:

```bash
make install-cron
make show-cron     # shows what is installed
```

`make install-cron` adds the lines to whatever is already installed, so run it only
once. To change the schedule after that, edit it with `crontab -e`. The schedule
runs these jobs:

- Every hour, it syncs CDEC and USGS.
- Every day at 1:25, it backs up the database and the uploaded files into the
  `backups` folder in the checkout (Keeping it running, below).
- Every day at 2:00, it syncs the Water Data Library, the SGMA Portal and NOAA.
- Every day at 3:30, it calculates every reporting period that is not finalized.
- Every 6 hours, it runs the health checks.
- On the 1st of each month at 3:00, `prune_old_data` deletes staging records and
  logs older than their retention period.

The times are in the computer's own time zone. The schedule does not sync CIMIS or
OpenET. To keep CIMIS current, add `cimis` to the end of the 2:00 line before you
install the schedule. Fetch OpenET with `sync_openet_parcels` when the organization
wants new months. To get an alert when a sync fails, add the line
`OPENH2O_NTFY_URL=` at the top of `crontab.txt`, followed by the address of a topic
on ntfy, a service that sends notifications to a phone or a browser.

Windows has no cron, and this guide does not yet give Windows steps for the
schedule. On a Windows computer, tell the organization that the syncs, the nightly
backup, the nightly calculation and the health checks every 6 hours will not run on
their own.

### Turn on the monitoring stations

Do this for every new area.

The populate step finds every gauge and well that public services report near the
boundary. Many of them never return data: a stream gauge that has been taken out of
service, a CDEC sensor that posts only event readings, a well last measured a decade
ago. Left on the map, they fill the monitoring view with red markers. Find out which
stations report, keep those, and remove the rest before you hand the site over.

1. **Turn on the stations in the boundary.** The populate step creates every station
   switched off, and `sync_source` fetches data only for stations that are on. With
   none on, it prints "No active stations for CDEC. Run discover_stations first."
   Ignore that advice. The stations are already found and only need to be turned on.
   Nothing below works until this step has run.

   In a browser, click **Enable all** in the Setup Wizard's last step (Phase 3). It
   turns on every station inside the boundary. Over SSH:

   ```bash
   docker compose exec web python manage.py activate_stations --boundary-name "My Basin" --dry-run
   docker compose exec web python manage.py activate_stations --boundary-name "My Basin"
   ```

   In place of `My Basin`, give the boundary's name as it was saved when you loaded
   the boundary. `--dry-run` prints the count and a sample and changes nothing.
   `--source cdec` turns on one source's stations at a time. Without
   `--boundary-name`, the command uses the first boundary on the site and says which
   one it used. `--all-boundaries` turns on stations everywhere, and the command
   never does this by default.

2. **Sync each source over the right period.** By default, `sync_source` fetches at
   least 7 days, and more for a source that publishes less often. That suits the
   daily gauges, `cdec` and `usgs`. The groundwater sources, `dwr_wdl` and
   `dwr_sgma`, publish every few months, and NOAA's climate data arrives late. Sync
   those three from a date a few years back, so each station gets a real history:

   ```bash
   docker compose exec web python manage.py sync_source cdec
   docker compose exec web python manage.py sync_source usgs
   docker compose exec web python manage.py sync_source dwr_sgma --start 2020-06-01
   docker compose exec web python manage.py sync_source dwr_wdl  --start 2020-06-01
   docker compose exec web python manage.py sync_source noaa     --start 2020-06-01
   ```

   Note each station that returns nothing. Such a station has stopped publishing,
   and its settings need no change.

3. **Remove the stations that have no usable data.** This command deletes every
   switched-on station with too few readings to draw a chart. With
   `--purge-inactive`, it also deletes every station that is still switched off:

   ```bash
   docker compose exec web python manage.py prune_dataless_stations --delete --purge-inactive --dry-run
   docker compose exec web python manage.py prune_dataless_stations --delete --purge-inactive
   ```

   ⚠ `--purge-inactive` cannot tell a dead gauge from one you have not turned on yet,
   and it deletes every station that is off. Run it only after step 1, once the
   stations you want to keep are on. On an area whose stations were just found, it
   deletes them all.

   Run it with `--dry-run` first to see what it would delete. It keeps every station
   with at least 2 published readings, and `--min-records` raises that number for a
   smaller map. Running the populate step again brings back the same wide set of
   stations, so turn the stations in the boundary back on before you remove the rest.

✋ **Checkpoint:** the monitoring map shows mostly green and amber markers, which
mark stations with recent readings, and every marker on it has a real reading
behind it.

---

## Phase 5: Bring in the people

OpenH2O has four roles. An administrator sets each person's role on the Users page
(`/users/`), under Administration in the Admin view of the sidebar. Only a host
administrator can make someone a host administrator.

- An **Administrator** manages users, runs the Setup Wizard, changes the
  methodology and delivery settings and finalizes a reporting period.
- A **Host administrator** can do everything an administrator does. They can also
  use `/admin/` and change other host administrators' accounts. The superuser from
  Phase 2 is a host administrator. Recommend a second one, so each can change the
  other's email address and password.
- An **Operator** works with the records on every other page.
- A **Viewer** reads every page and changes nothing.

Sign-up is closed by default, so each person gets an account from an administrator.
The administrator clicks **+ Add user** on the Users page and sets a starting
password there. The person chooses a new password the first time they sign in. Ask
the person you are working for who should administer the
site, who should work with the records and who only needs to read them.

`ACCESS_CONTROL_ENFORCED` is on by default. When `.env` sets it to `False`, every
signed-in person can open the administrator pages and anyone can sign up. That suits
only an open demonstration site. A viewer stays read-only either way.

The administration site at `/admin/` also lists three older roles: admin, manager
and viewer. They come from an earlier design and control nothing. Set roles on the
Users page.

Then walk the organization's staff through a first session: signing in, confirming
the boundary and reviewing the accounts, the allocations and the recorded data.
Reporting is under development and off by default, so leave it off. OpenH2O does not
submit reports to the state.

Before the first password reset, check the name the site's emails go out under.
Every email the site sends starts its subject line with the site's name. OpenH2O
takes the site's name from the organization's name, which is set at `/admin/` under
Core > Site configs. It takes the site's address from `ALLOWED_HOSTS`. It saves both
when the migrations run. Check what it saved:

```bash
docker compose exec web python manage.py shell -c "from django.contrib.sites.models import Site; s = Site.objects.get_current(); print(s.name, '|', s.domain)"
```

The command should print the organization's name and the site's web address. If
either one still reads `example.com`, set the missing value. The organization's name
goes in at `/admin/` under Core > Site configs, and the address goes in
`ALLOWED_HOSTS` in `.env`. After a change to `.env`, run `docker compose up -d`. Then
run `docker compose exec web python manage.py migrate` and check again.
`manage.py check` also reports a missing name or address, as `openh2o.W002`. A site
reached only at `localhost` keeps `example.com` as its address and keeps the
warning, because OpenH2O skips `localhost` when it works out the address.

If a consultant set up the site, finish with *Handing a site over* in section 11 of
DEPLOY.md. The organization's host administrator then deactivates the consultant's
account.

✋ **Done when:** a member of the organization's staff can sign in and see and manage
the organization's records without you.

---

## Keeping it running

Once the schedule is installed, OpenH2O checks itself every 6 hours and shows each
result as a card on the Site health page (`/health/`). When the organization asks
you to look at the site, run
`docker compose exec web python manage.py run_health_checks --json` to read every
result, including each card's JSON details. `--category` runs a single check. A card
that needs work is marked Attention needed or Action required.

The table gives the fix for the nine cards about the server, the schedule and
OpenH2O's stored data. The other six cards are Ledger Integrity, Use areas without
an account, Point of diversion shares, Unallocated Delivery, Period Alignment and
ET / Meter Agreement. They concern the organization's records, and each links to the
page where someone at the organization corrects them.

| Site health card | What it means, and the fix |
|---|---|
| Database | OpenH2O cannot reach the database. Run `docker compose ps`. If `db` is not `Up (healthy)`, run `docker compose up -d` and read `docker compose logs db`. |
| Disk | The disk is over 80% full. Over 90%, the card changes to Action required. Run `docker system df` to see what Docker holds, and `docker image prune` to remove images no container uses. Ask the organization before you delete anything else. On a Mac, Docker Desktop keeps OpenH2O on a virtual disk with a size limit set in Docker Desktop's settings. If pruning does not free enough space, raise that limit. |
| Database name | OpenH2O is connected to a database other than the one its settings name. With Docker, the database's name comes from `POSTGRES_DB` in `.env`, and the compose file builds the connection from it. Check `POSTGRES_DB`, then run `docker compose up -d`. Without Docker, the name comes from `DATABASE_URL` in `.env`. |
| SSL | The certificate expires in under 30 days, or OpenH2O cannot read it. Where the `Caddyfile` names the domain, Caddy renews the certificate by itself, so this card means the renewal is failing. Check that the domain's A record still points at this computer and that ports 80 and 443 are open, then read `docker compose logs caddy`. Where a tunnel or the organization's own proxy handles the encryption, renew the certificate there. On a site with no public domain, the card says there is no certificate to check, and it needs no fix. |
| Migrations | The database is missing updates this version of OpenH2O needs. Run `docker compose exec web python manage.py migrate`. |
| Sync Freshness | A data source with a station turned on has not synced for more than 48 hours. After 7 days, or when it has never synced, the card changes to Action required. Run `crontab -l` to check that the schedule is installed. Then run `docker compose exec web python manage.py sync_source` with the source's code, such as `usgs`, and read what it prints. The scheduled syncs write to `sync.log` in the log folder set in `crontab.txt`. The card leaves out a source whose key is missing, and the monitoring dashboard shows that source as "needs key". |
| Calculation | A calculation has waited more than 15 minutes to start, or it stopped before it finished. Run it with `docker compose exec web python manage.py run_accounting --request` and the request number from the card's JSON details, or ask the organization to run it again from the water year's page. The card also asks for attention when no calculation has finished in 48 hours while a water year is still open. For that, run `crontab -l` to check that the schedule is installed, and read `calculation.log` in the log folder set in `crontab.txt`. |
| Backup | The card asks for attention or action when OpenH2O cannot find the backups folder or read the record of the last backup, or when the last backup failed, ran 36 hours ago or more, or is missing tables. A failed backup's reason is in the card's JSON details; read it first. When OpenH2O cannot find the folder, check that `docker-compose.yml` mounts the checkout's `backups` folder at `/backups`, then run `docker compose up -d`. Otherwise run `crontab -l` to check that the schedule is installed, read `backup.log` in the log folder set in `crontab.txt`, then run `scripts/backup.sh` and read what it prints. |
| Cache Duplication | OpenH2O holds two OpenET estimates for the same months at some use areas. No figure changes, because OpenH2O uses the newer estimate. Report it as a bug at github.com/Open-H2O/openh2o/issues and attach the card's JSON details. |

The schedule backs up the database and the uploaded files every night at 1:25 into the
`backups` folder in the checkout, and checks that each backup can be read back. That
folder is on the same disk as the database. Ask the organization where a second copy
should live, such as another disk or another computer, and set up the copy. Database
Backup, Database Restore and Upgrades in section 11 of DEPLOY.md give the commands to
back up by hand, to restore a backup and to upgrade. Those commands need Docker. Without
Docker, follow section 11 of the no-Docker install guide.

On an installation without Docker, load the variables in `.env` into the terminal as
the [no-Docker install guide](INSTALL-WITHOUT-DOCKER.md) shows. Run each command
above with this installation's Python in place of `docker compose exec web`, and
restart OpenH2O's background service with the command that guide gives.

---

## Troubleshooting by symptom

<!-- defines: geospatial_libraries -->
One row below names GDAL, GEOS and PROJ. These are open-source libraries that do
OpenH2O's map calculations, such as parcel outlines, well locations and distances
on the curved earth. OpenH2O cannot start without them. The Docker build installs
them, so an error that names one of them means the build went wrong.

| Symptom | Likely cause | Fix |
|---|---|---|
| The `web` container will not start, and its log mentions `ImproperlyConfigured` | The production checks refused a setting. The database password is empty or a common default, `ALLOWED_HOSTS` is empty or `SECRET_KEY` is missing. Or `ACCOUNT_EMAIL_VERIFICATION` holds a value other than `none`, `optional` or `mandatory`. Or `OPENH2O_MODULES` names an unknown section or leaves out a section that another one needs. | Read `docker compose logs web`, where the message names the setting. Correct it in `.env` and run `docker compose up -d`. |
| The Docker build fails on GDAL, GEOS or PROJ | The build could not install the map libraries. | Read the first error in the build output, then see the troubleshooting section of DEPLOY.md. |
| The site loads at its public domain, but without HTTPS | The shipped `Caddyfile` serves plain web traffic on port 80 and names no domain, so pointing DNS at the computer produces no certificate. | Name the domain in the `Caddyfile` as section 4 of DEPLOY.md describes, then run `docker compose restart caddy`. |
| A source on the monitoring dashboard shows "needs key", "no stations" or "no recent data" | "Needs key": its key is missing from `.env`. "No stations": it has no station turned on. "No recent data": the source publishes rarely, as the groundwater sources do, or its sync is failing. | Add the key to `.env` and run `docker compose up -d`. Turn the stations on as Phase 4 describes. Run `sync_source` for the source with an earlier `--start` and read what it prints. |
| The reset page says the site does not send email, or a reset email never arrives | The site has no SMTP settings. | Add `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL` to `.env` and run `docker compose up -d`. Until then, an administrator sets a temporary password for the person on the Users page. For the only host administrator, run `docker compose exec web python manage.py changepassword` with the account's username. The username is the email address unless the account was given a different one. |
| 502 Bad Gateway after the computer restarts | The website container is still starting, or Docker did not start with the computer. | Set Docker to start when the computer starts. The compose file sets `restart: unless-stopped`, so the containers start again when Docker does. Run `docker compose ps`. If `web` is not `Up (healthy)`, run `docker compose up -d` and read `docker compose logs web`. |

---

## Guardrails

- **Never** commit the organization's `.env`, its API keys or the `secrets/` folder,
  which holds the key files that some data services require. Git is set to ignore
  them, so they stay out of the published code.
- **Never** run `make fresh` on a site that holds records, because it deletes the
  database. For a routine rebuild, run `docker compose up -d --build`. To upgrade,
  run `make upgrade` (Upgrades in section 11 of DEPLOY.md). On a live site, create
  the `.production-lock` file that section 11 describes. With that file in place,
  `make up`, `make down`, `make build` and `make fresh` refuse to run, and
  `make upgrade` still runs. Never run `make deploy`, which serves only the
  project's own demonstration site and will not run anywhere else.
- **Leave** `ACCOUNT_EMAIL_VERIFICATION` unset. When it is unset, it follows
  `EMAIL_HOST`. A person who signs up must confirm their email address when the site
  has a mail server, and need not when it has none. If it is set to `mandatory` on a
  site with no mail server, each person who signs up waits for an email the site
  cannot send. Accounts an administrator adds on the Users page need no
  confirmation.
- **Do not** weaken the production checks to get the site to start. Correct the
  setting that the message names.
- **Keep** the link that offers users the source code. If the organization changes
  OpenH2O's code and runs it for its users, the AGPL (section 13), the license
  OpenH2O is published under, requires the site to offer those users the changed
  source code. The Source code link at the foot of every page points at
  github.com/Open-H2O/openh2o, and no setting can change it yet. Change it in
  `templates/base.html` and `templates/base_auth.html` to wherever the organization
  publishes its changes. See [NOTICE](../NOTICE).
