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
   - <!-- defines: localhost --> *Only this one computer.* The site does not need a domain
     name. Its address is `localhost`, the name a computer uses for itself, and
     `127.0.0.1` is the same address in numbers. No other computer can reach it.
   - *Other computers in the office.* The site does not need a domain name. It answers at
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

If the organization wants people outside the office to reach the site and has no server
or domain yet, help it rent a virtual server and register a domain. A site on one
computer or on the office network needs neither a rented server nor a domain, and is a
complete OpenH2O installation.

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
- Loading the demonstration, which builds some 66,000 records and saves them in one
  transaction at the end.
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

An organization that runs only a drinking-water system can switch water accounting
off. The sections `parcels` and `accounting` go on or off together. The sections
`wells`, `datasync`, `surface`, `recharge` and `reporting` need `parcels` and
`accounting`. Leave all seven out. The site keeps the sign-in, the map and Drinking
water. Use this line in `.env` for a drinking-water system without water accounting:

```bash
OPENH2O_MODULES=core,geography,measurements,standards,drinking,setup,infrastructure,health,feedback
```

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
`caddy` as `Up`. Caddy's row shows only `Up` because the compose file does not give
Caddy a health check. Wait until all three rows show these states before you go on.

On a new site the `web` container creates every database table before it reports
healthy. Creating the tables can take several minutes on a small computer. During
that time `docker compose ps` shows `web` as `health: starting`. If
`docker compose up` stops with a message that the `web` container is unhealthy, read
`docker compose logs web`. A log that still shows tables being created means the start
has not finished. Wait until `docker compose ps` shows `web` as `Up (healthy)`. Then run
`docker compose up -d` again to start Caddy.

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
   | The office network | the computer's address on that network, such as `192.168.1.40`. The command `hostname -I` prints the address on a Linux computer. Ask the person to set the office router to give this computer the same address every time. | leave empty |
   | People outside | the organization's domain, such as `water.example.org` | `https://` and the domain, such as `https://water.example.org` |

3. **HTTPS, and the three settings that depend on it.** The production settings
   assume HTTPS. `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE` and
   `CSRF_COOKIE_SECURE` are all on by default. A browser sends a cookie marked
   secure only over `https://`. With these settings on and no HTTPS, every sign-in
   fails with a 403 error, even though the pages that do not need a sign-in still load.

   | Who needs to reach it | What to do |
   |---|---|
   | People outside | Choose one of the two setups in section 4 of [DEPLOY.md](../DEPLOY.md). Where Caddy obtains the certificate (Branch B), point the domain's A record at this computer and set `OPENH2O_SITE_ADDRESS` in `.env` to the bare domain, then run `docker compose up -d`. Where a tunnel, the organization's own proxy or a load balancer in front of this computer handles the encryption (Branch C), leave `OPENH2O_SITE_ADDRESS` unset. Without the setting, Caddy answers at any address over plain HTTP, so pointing DNS at the computer does not by itself produce a certificate. Keep the three settings on. Leave `OPENH2O_FORWARDED_PROTO` unset. |
   | Only this computer, or the office network | There is no certificate to obtain. Turn the three settings off in `.env` and add a fourth line: <br>`SECURE_SSL_REDIRECT=False`<br>`SESSION_COOKIE_SECURE=False`<br>`CSRF_COOKIE_SECURE=False`<br>`OPENH2O_FORWARDED_PROTO=http`<br>The line `OPENH2O_FORWARDED_PROTO=http` makes Caddy pass each request to OpenH2O as plain HTTP. Every sign-in from an `http://` address fails with a 403 error until `.env` holds that line. |

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
c = Client(SERVER_NAME='water.example.org', HTTP_X_FORWARDED_PROTO='https')
r = c.post('/accounts/login/', {'login': 'ADMIN_EMAIL', 'password': 'ADMIN_PASSWORD'})
print(r.status_code)
"
```

`HTTP_X_FORWARDED_PROTO='https'` marks the test sign-in as an HTTPS request. In place
of `water.example.org`, give an address from `ALLOWED_HOSTS`. On a site without
HTTPS, use `SERVER_NAME='localhost'`. `localhost` works on every site, because the
production settings add it to `ALLOWED_HOSTS`. Put the administrator's email address
and password in place of `ADMIN_EMAIL` and `ADMIN_PASSWORD`. The command prints 302
when the sign-in works. It prints 200 when the sign-in form came back, which usually
means the email address or password is wrong.

---

## Phase 3: Load data

Start by asking the person whether the organization has its records ready or wants to
explore the demonstration first. The demonstration loads only into a site that does not
yet hold records of its own, and `remove_demonstration` removes it. To explore the
demonstration, load it on the new site before anything else, and remove it before you
load the organization's own records.

Before you load any records, set the organization's name with `set_organization`. Every
email the site sends starts its subject line with that name.

```bash
docker compose exec web python manage.py set_organization --name "Example Ditch Company"
```

For the organization's own records, start with the Setup Wizard. On a site that does
not hold records of its own and runs the default modules, the wizard first asks whether
to load the demonstration data or start with the organization's own records. It then
sets the area the site covers. The boundary it saves counts as a record of the site's
own, so load the demonstration before setting a boundary, not after.

### The Setup Wizard

The Setup Wizard at `/setup/` sets the area the site covers and fills that area in
from public sources. Use it when you have a browser. Only an administrator can open
it, so sign in as the administrator first. Click **Settings** in the top bar, beside
your sign-in name, then **Setup Wizard**. You can also go straight to `/setup/`.

<!-- defines: geojson --><!-- defines: shapefile --><!-- defines: kml -->
The wizard's first step offers four choices:

1. Select a boundary already on the site.
2. Upload a boundary file: a zipped shapefile, a KML file or a GeoJSON file. A
   *shapefile* is a map saved as several files that share one name and differ only in
   their endings, such as `.shp` and `.dbf`. Zip all of the files together for the
   upload. *KML* is the map format Google Earth saves. GeoJSON
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

On a server you reach only over SSH, run the same steps as commands. `import_boundary`
reads the same GeoJSON, zipped shapefile and KML files as the wizard's upload.
`auto_populate` then fills the area in from public sources, and `activate_stations`
turns on the stations that `auto_populate` found (Phase 4). If the parcel or stream
download stops partway, its failure message gives the last OBJECTID it reached. Run
`auto_populate` again with `--steps parcels` or `--steps flowlines` and `--resume-from`
that number. The Data import guide shows each command, including the `docker compose cp`
step that copies a file into the container.

### Option A: The demonstration data

```bash
docker compose exec web python manage.py load_demonstration    # the demonstration data
```

`load_demonstration` loads the demonstration: published records from a real groundwater
basin, with invented sample data. It gives the organization a complete site to explore
while you gather its own records. It loads the reference lists, the basin's boundary,
streams, parcels, wells, rights, recharge basins, the demonstration's 335 monitoring
stations with their readings, the stored satellite ET data and the calculated figures
for two water years. Of the stations, 42 are switched on, each with the date it last
published a reading. The load downloads nothing and does not need a key. It runs as one
transaction: a load that fails saves nothing.

The load refuses to start, says why and changes nothing when the site already holds
records of its own or a module it needs is switched off. An administrator can also load
the demonstration from Settings > Setup Wizard > Demonstration data.

When the organization is ready for its own records, remove the demonstration first:

```bash
docker compose exec web python manage.py remove_demonstration
```

The removal deletes every record the site holds and keeps the users and the reference
lists. While the site still carries the demonstration's name, its settings came from
the load, so the removal deletes them, and any setting changed while the demonstration
was on the site goes back to its default. Otherwise the removal keeps the settings and
turns Demonstration mode off. Either way the site is as it was before the load. The
Demonstration data page offers the same removal and first lists how many records of
each kind it deletes and how many of them people added since the load, so nobody
deletes their own work unawares. To rebuild the demonstration, remove it and load it
again.

### Look at the organization's records first

Before you load anything, read the organization's existing files and ask how it
keeps its records. OpenH2O is built to import records in the form the organization
already keeps them.

<!-- defines: csv -->
As you go, fill in the worksheet `docs/crosswalk-worksheet.csv`. A *CSV file* holds a
table as plain text. Each row is one line of text with commas between its columns. Any
spreadsheet program opens and saves this format. Add a row for each
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
| Which parcels each point of diversion serves, each field's share of that point's water, and whether to divide the water by share or by crop ET | `import_parcels` links each use area to its point when the file of use areas has a headgate column. The share on the link between the point and the parcel, set on the point's own page. Without a share, OpenH2O divides the water by acreage. To divide by crop ET, set **How the water is divided among the use areas** on the point's edit page. |
| Each measuring device's nickname, calibration date and accuracy | The device record, from **Add device** on the point's own page. |
| Which year a season belongs to | The Delivery Settings page (`/accounting/delivery-settings/`), under Reporting year. It is set once for the whole site. |
| Which month your water year starts in | The water year setting on the Delivery Settings page (`/accounting/delivery-settings/`). The default is 10, October. Before the first allocation, set the month. |
| The unit of the rows in a production file whose unit is blank | **Unit for rows with a blank unit**, on the preview of the production import screen. For a log with its own column headings, **Unit** on the same preview. That kind of log has no default unit. |
| Which facility each name in the organization's files means | The facility's local name, on its add or edit page under Drinking water > Facilities. |
| Whether any laboratory results exist only on paper | Type the results into a CSV file with the lab import's columns. Import the file with `import_lab_results` or at `/drinking/import/`. |
| Which meter feeds which water source | A production file gives figures for the whole system by type of water. The file does not name a meter. Before the import, add the meters for one type of water together into one figure a month. |
| Whether the organization wants OpenH2O to hold its sampling schedule | The Schedule page under Drinking water. Import the state's Last and Next Sample Report with **Import the state's schedule** or `import_schedule`. Add any other row with **+ Add to schedule**. |

### Option B: The organization's own records

Each kind of record has its own import screen or command, and several have both.
The table lists them in the order to load them. The Data import guide describes each
one in full.

<!-- defines: dry_run -->Every import command takes `--dry-run`. A *dry run* checks the
file and reports what the command would do without saving anything. Most import screens
show a preview and save only after you confirm. The Upload CSV page of the Use Ledger
saves the file at once unless you tick Dry run.

| The organization has | Use | Notes |
|---|---|---|
| Only a boundary | `import_boundary`, then `auto_populate` | `import_boundary` loads a boundary from a GeoJSON file, a zipped shapefile or a KML file. `auto_populate` then downloads basins, parcels, streams and monitoring stations for that boundary, which must already be on the site. |
| Parcel outlines, as a zipped shapefile, KML or GeoJSON | The Import use areas screen at `/parcels/import/`, or `import_parcels` | Both read the same files. Water accounts link to parcels, so import the parcels before you create accounts. |
| A list of wells, as a CSV file | The import screen at `/infrastructure/import/?type=well`, or `import_wells` | Both create the same records. The screen asks you to match the file's columns first. |
| Water levels measured at the wells, as a CSV file | `/wells/water-levels/import/` | The screen reads DWR's groundwater level data from its SGMA Portal, and the organization's own spreadsheet. Each row identifies its well by name, state well number or WCR number, so import the wells first. |
| A list of water rights | `import_water_rights` or the import screen at `/surface/rights/import/` | From the state's CSV list, the command creates the same water rights as the screen. Import the water rights before the points of diversion. |
| Points of diversion, as a CSV, GeoJSON, KML or shapefile | `import_infrastructure --type diversion` or the Import screen at `/infrastructure/import/?type=diversion` | The command reads the same files as the screen. It creates the same points of diversion. To link each use area to its point, run `import_parcels` again with a headgate column after the points are on the site. |
| Storage ponds or recharge sites | `import_infrastructure` with `--type storage` or `--type recharge_site`. On the Import screen, use `?type=storage` or `?type=recharge_site` at the end of the address. | Each of these import pages links to the others under "Importing something else?". |
| A public water system, by its PWSID | `add_water_system` or `/drinking/onboard/` | A PWSID is the identification number of a public water system in EPA's records. The command and the page add the system and its facilities from EPA's Envirofacts records. A site keeps the records of one water system. Once a system is on the site, OpenH2O refuses a different PWSID. To update the system from EPA's record, run the command again or look up the same PWSID and press Refresh. Add the sampling points with `add_sampling_point` or on the page that follows. |
| Laboratory results | `import_lab_results` or `/drinking/import/` | The command and the screen read the column headings of California's Division of Drinking Water and several headings that commercial labs use. |
| The state's sampling schedule | `import_schedule` or `/drinking/schedule/import/` | The command and the screen read the Last and Next Sample Report from California's Division of Drinking Water. A newer file changes the frequency and dates of rows already on the schedule. |
| A year of production by month and source | `/drinking/production/import/`, or `import_production` | It reads an eAR export or a monthly log. The screen and the command both save to the site's water system. The command needs `--pwsid` only when someone has added a second system another way, such as on the administration site. |
| Past ledger entries, as a CSV file | `import_ledger_csv`, or the Upload CSV page of the Use Ledger (`/accounting/ledger/upload/`) | The Upload CSV page imports the file at once unless you tick Dry run. Each entry counts in the water year its date falls in. Create the water years first with `create_water_year` or under Water accounting > Water Years. An entry dated outside every water year belongs to none until someone creates a water year that covers its date. With `--reporting-period` and a water year's name, the command imports only the rows dated inside that water year. |
| A year of diversion volumes, in California's Water Use Reported export or the organization's own book of deliveries | `/surface/diversion/import/`, or `import_diversion_records` | OpenH2O recognizes either layout by its column headings, and the preview lists the conversions OpenH2O made. Set the report year first, as the next paragraph describes. Then create each water year the file covers with `create_water_year` or under Water accounting > Water Years. When you create a water year, OpenH2O attaches each record dated inside it that is not yet in a water year. |

Before you import diversion records, ask how the organization counts a reporting year:
as an October-to-September water year, a calendar year, or an irrigation season that
starts in a month it chooses. Record the answer on the Delivery Settings page
(`/accounting/delivery-settings/`), under Reporting year. That part of the page appears
only when the site runs the `surface` section. The reporting year applies only to
diversion files, and is separate from the month the site's water year starts in.

Water accounts and allocations have no import. Create them on the Accounts and
Allocations pages under Water accounting. Before the first allocation, set the water
year's first month on the Delivery Settings page. Then create each water year with
`create_water_year` or on the Water Years page. A water year starts on the first day of
a month and ends on the last day of a month. You can also enter water levels one at a
time on the well's page. For a station the organization measures itself, an Operator or
Administrator first adds the station on Add monitoring station
(`/datasync/stations/add/`) with the data source Entered by hand; its readings then go
on the station's page under Add a reading. The Data import guide lists every record that
is entered by hand and the page for each.

✋ **Checkpoint:** before you create accounts, confirm with the person that the
boundary looks right on the map and which parcels the organization's accounts will
cover.

---

## Phase 4: Connect live data sources

### Create the calculation plan

A *calculation plan* is the list of steps OpenH2O follows to calculate a use area's
figures from its satellite ET. OpenH2O comes with a default plan. Loading the
demonstration installs the default plan. Removing the demonstration deletes the plan
again. Create the default plan before the first OpenET run on the organization's own
use areas:

```bash
docker compose exec web python manage.py seed_calculation_plan
```

An administrator can also create the plan with **Load the default calculation plan** on
the Methodology Settings page (`/accounting/methodology/`). The page then lists the
plan's steps. Until a plan exists the Dashboard shows "This site has no calculation
plan yet." and each use area's page shows "OpenH2O has not calculated crop ET for this
use area in this water year."

The schedule set up under **Keys and the schedule** runs the calculation at 3:30 every
night. The calculation uses this plan and the months of ET that OpenET has sent. Each
run calculates every use area's supplies, uses and water balance for the water year.
Run this command to calculate the figures immediately:

```bash
docker compose exec web python manage.py run_accounting --open-periods
```

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

Let the organization decide when to make the first satellite ET run. A run against the
demonstration spends part of the month's allowance on an area the organization does not
manage. A run against the organization's own parcels produces the figures it needs.
Load the organization's own parcels first, then fetch satellite ET. The demonstration
ships with its own ET figures, so it does not need an OpenET run.

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

USGS, CDEC (the California Data Exchange Center) and the Department of Water Resources'
Water Data Library and SGMA Portal do not need a key. CIMIS (the California Irrigation
Management Information System) needs `CIMIS_API_KEY`. NOAA's climate data needs
`NOAA_CDO_TOKEN`, and OpenET needs `OPENET_API_KEY`. USGS offers an optional free key,
`USGS_API_KEY`; with it, USGS accepts more requests an hour from the site. The comments
in `.env.example` say where to get each key. Add each key to `.env` and run
`docker compose up -d`. The monitoring dashboard shows a source whose key is missing as
"Needs API key".

<!-- defines: cron -->
The schedule runs on cron, the scheduler built into Linux and macOS. Leave
`crontab.txt` as shipped. `make install-cron` writes this checkout's folder into the
schedule as `OPENH2O_DIR`, and a log folder as `OPENH2O_LOG_DIR`: by default
`openh2o-logs` in the home folder of the account that runs the command. To put the logs
elsewhere, add the folder to the command, as in
`make install-cron OPENH2O_LOG_DIR=/var/log/openh2o`. If the account cannot write to
that folder's parent, create the folder first and give the account ownership of it.
Install the schedule:

```bash
make install-cron
make show-cron     # shows what is installed
```

`make install-cron` writes the jobs between a line that begins
`# BEGIN OpenH2O schedule` and a line that begins `# END OpenH2O schedule`, and keeps
every other line already installed. Running the command again replaces the block, so
the jobs never run twice; run it again after changing the log folder. Do not edit
inside the block, because the next run replaces it. When the installed schedule holds
OpenH2O jobs without those two lines, `make install-cron` changes nothing and says so;
Upgrades in section 11 of DEPLOY.md gives the fix. The schedule runs these jobs:

- Every hour, it syncs CDEC and USGS.
- Every day at 1:25, it backs up the database and the uploaded files into the
  `backups` folder in the checkout (Keeping it running, below).
- Every day at 2:00, it syncs the Water Data Library, the SGMA Portal, NOAA and CIMIS.
- Every day at 3:30, it calculates every reporting period that is not finalized.
- Every 6 hours, it runs the health checks.
- On the 1st of each month at 3:00, `prune_old_data` deletes published readings, sync
  logs and health-check results once they pass their retention period, counted from the
  day OpenH2O wrote them. It keeps every reading at an Entered by hand station,
  whatever its age. It deletes a revised reading with its earlier values once the
  newest of them passes the retention period.

The times are in the computer's own time zone. A station's page shows when OpenH2O next
reads that station's data. The page gives that time in the site's time zone. Set the
site's time zone with `set_organization --time-zone`. A site whose organization's name
was never set uses the `TIME_ZONE` setting in `.env`. Set the computer's clock to the
same zone. Until its key is set, the schedule skips CIMIS or NOAA with one line in the
log. OpenET is not on the schedule: run `sync_openet_parcels` when the organization
wants new months. The ntfy service sends notifications to a phone or a browser. For an
alert when a sync fails, put `OPENH2O_NTFY_URL=` in `.env`, followed by the address of
an ntfy topic, then run `make install-cron` again to copy the address into the schedule.

On Windows, Task Scheduler runs the schedule. The jobs run in Git
Bash, which comes with Git for Windows (https://git-scm.com/download/win), so install
Git for Windows first. Then open PowerShell in the checkout and install the schedule:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\windows\install-schedule.ps1
Get-ScheduledTask -TaskPath '\OpenH2O\' | Get-ScheduledTaskInfo     # shows what is installed
```

The script writes one task for each job above into Task Scheduler's OpenH2O folder, to
run at the same times. It writes the logs to `openh2o-logs` in the home folder; to put
the logs elsewhere, add `-LogDir` and the folder. Running the script again replaces the
tasks, so the jobs never run twice. The tasks run as the account that installed them,
and only while that account is signed in to Windows; Docker Desktop also runs only
then. Each run adds a line to `schedule.log` in the log folder with the time, the job
and its exit code. On Windows, the schedule reads the alert address from `.env` at each
run, so a changed `OPENH2O_NTFY_URL` takes effect at the next run.

### Turn on the monitoring stations

Do this for every new area.

The populate step finds every gauge and well that public services report near the
boundary. Many of them never return data: a stream gauge that has been taken out of
service, a CDEC sensor that posts only event readings, a well last measured a decade
ago. Stations like these fill the monitoring view with grey Dormant markers. Find out
which stations report, keep those, and remove the rest before you hand the site over.

1. **Turn on the stations in the boundary.** The populate step creates every station
   switched off, and the schedule fetches data only for stations that are on. For a
   source with every station switched off, `sync_source` says how many are switched off
   and names `activate_stations` and the Setup Wizard's Enable all. The stations are
   already found and only need to be turned on. Nothing below works until this step has
   run.

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

   Note each station that returns nothing; it has stopped publishing, and its settings
   stay as they are.

   Later syncs compare each reading a source sends with the one OpenH2O holds. A
   different value becomes the reading, and the earlier value stays on the station's
   list of revised readings; no water figure changes. A `usgs` sync with no start or
   end date asks USGS only for its changes of the last 7 days, so after a gap of more
   than 7 days, sync `usgs` once with `--start`.

3. **Remove the stations that have no usable data.** This command deletes every
   switched-on station with too few readings to draw a chart. With `--purge-inactive`,
   the command also deletes every station still switched off. It never deletes a
   station of the Entered by hand source, with or without readings:

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

✋ **Checkpoint:** the monitoring map shows mostly green and amber markers, the colors
of stations with recent readings. Every marker for a station OpenH2O syncs has a real
reading behind it.

---

## Phase 5: Bring in the people

OpenH2O has four roles. An administrator sets each person's role on the Users page
(`/users/`), reached from the Settings page. Only a host administrator can make someone
a host administrator.

- An **Administrator** manages users, runs the Setup Wizard, changes the methodology
  and delivery settings and finalizes a reporting period. Finalizing records the year's
  figures, and the water year page lists any figure that has changed since.
- A **Host administrator** can do everything an administrator does. They can also
  use `/admin/` and change other host administrators' accounts. The superuser from
  Phase 2 is a host administrator. Recommend a second one, so each can change the
  other's email address and password.
- An **Operator** works with the records on every other page. An operator voids a wrong
  record and never deletes it: **Void this record**, in the `...` menu at the end of
  the record's row or in the page heading for a use area or a lab result, asks for a
  reason. The voided record stays on the page, struck through, and counts in no figure.
  **Correct this record** fixes a wrong figure the same way: OpenH2O keeps the old
  record, struck, with a line naming what replaced it, and recalculates the months the
  old record touched when a calculation uses it. Inside a finalized water year, only an
  administrator can correct or void a record, with a reason for each.
- A **Viewer** reads every page and changes nothing.

Sign-up is closed by default, so each person gets an account from an administrator.
The administrator clicks **+ Add user** on the Users page and sets a starting
password there. The person chooses a new password the first time they sign in. Ask
the person you are working for who should administer the
site, who should work with the records and who only needs to read them.

`ACCESS_CONTROL_ENFORCED` is on by default. When `.env` sets it to `False`, every
signed-in person can open the administrator pages and anyone can sign up. That suits
only an open demonstration site. A viewer stays read-only either way.

Then walk the organization's staff through a first session: signing in, confirming
the boundary and reviewing the accounts, the allocations and the recorded data.
Reporting is under development and off by default, so leave it off. OpenH2O does not
submit reports to the state.

Before the first password reset, check the name the site's emails go out under. Every
email the site sends starts its subject line with the site's name. The command
`set_organization` sets the organization's name. The site's emails use that name. The
site's address comes from `ALLOWED_HOSTS`. The migrations save that address in place of
the placeholder `example.com`. Check what it saved:

```bash
docker compose exec web python manage.py shell -c "from django.contrib.sites.models import Site; s = Site.objects.get_current(); print(s.name, '|', s.domain)"
```

The command should print the organization's name and the site's web address. If the name
still reads `example.com`, run `set_organization` with the organization's name. If the
address still reads `example.com`, put the address in `ALLOWED_HOSTS` in `.env`. After a
change to `.env`, run `docker compose up -d`. Then run
`docker compose exec web python manage.py migrate` and check again. `manage.py check`
also reports a missing name or address, as `openh2o.W002`. A site reached only at
`localhost` takes `localhost` as its address. `manage.py check` stops reporting
`openh2o.W002` once `set_organization` has set the organization's name.

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
| SSL | The certificate expires in under 30 days, or OpenH2O cannot read it. Where `OPENH2O_SITE_ADDRESS` names the domain, Caddy renews the certificate on its own, so a warning here means the renewal is failing. Check that the domain's A record still points at this computer and that ports 80 and 443 are open, then read `docker compose logs caddy`. Where a tunnel or the organization's own proxy handles the encryption, renew the certificate there. On a site with no public domain, the card says there is no certificate to check, and nothing needs fixing. |
| Migrations | The database is missing updates this version of OpenH2O needs. Run `docker compose exec web python manage.py migrate`. |
| Sync Freshness | A data source with a station turned on has not synced for more than 48 hours. After 7 days, or when it has never synced, the card changes to Action required. Run `crontab -l` to check that the schedule is installed. Then run `docker compose exec web python manage.py sync_source` with the source's code, such as `usgs`, and read what it prints. The scheduled syncs write to `sync.log` in the log folder: `openh2o-logs` in the home folder, unless `make install-cron` named another. The card leaves out a source whose key is missing, and the monitoring dashboard shows that source as "Needs API key". The card also leaves out the Entered by hand source, whose readings a person types. Update readings now on a station's page does not count as a sync of its source. |
| Calculation | A calculation has waited more than 15 minutes to start, or it stopped before it finished. Run it with `docker compose exec web python manage.py run_accounting --request` and the request number from the card's JSON details, or ask the organization to run it again from the water year's page. In a finalized water year the page refuses the run; an administrator instead corrects again the record the last correction created, and that correction starts the calculation. The card also shows Attention needed when a water year is open and no calculation has finished in 48 hours. In that case, run `crontab -l` to check that the schedule is installed, and read `calculation.log` in the log folder. |
| Backup | The card shows Attention needed or Action required when OpenH2O cannot find the backups folder or read the record of the last backup, or when the last backup failed, ran 36 hours ago or more, or is missing tables. Read a failed backup's reason in the card's JSON details first. When OpenH2O cannot find the folder, check that `docker-compose.yml` mounts the checkout's `backups` folder at `/backups`, then run `docker compose up -d`. Otherwise run `crontab -l` to check that the schedule is installed, read `backup.log` in the log folder, then run `scripts/backup.sh` and read what it prints. |
| Cache Duplication | OpenH2O holds two OpenET estimates for the same months at some use areas. No figure changes, because OpenH2O uses the newer estimate. Report it as a bug at github.com/Open-H2O/openh2o/issues and attach the card's JSON details. |

The schedule backs up the database and the uploaded files every night at 1:25 into the
`backups` folder in the checkout, and checks that each backup can be read back. That
folder is on the same disk as the database. Ask the organization where a second copy
should live, such as another disk or another computer, and set up the copy. Database
Backup, Database Restore and Upgrades in section 11 of DEPLOY.md give the commands to
back up by hand, to restore a backup and to upgrade. Those commands need Docker. Without
Docker, follow section 11 of the no-Docker install guide.

Each finalized water year's page has a Changes to this year's records card, showing a
code OpenH2O issued from that year's records. When someone reports that Check for
changes says "Changes found with no correction on record", read the parts the answer
names after "Look at", and tell the organization what the answer says. If the answer
says the stored code no longer agrees with its own parts, compare the code on the page
with the organization's downloaded copy. Do not change anything to clear the answer.
Reopening the year and finalizing it again issues a new code, and that is the
organization's decision. Check for changes runs inside OpenH2O, so it cannot detect a
change to the software itself; the one-page file from Download a copy to keep is the
record the organization keeps outside OpenH2O.

The As of box on an account, a use area and the Use Ledger shows the records and
figures as they were at the end of a chosen day. Download CSV on the Use Ledger then
saves the rows as they were that day. Names, a water year's status, settings and map
shapes shown there are today's, and today's version of OpenH2O adds up the totals. For
a date before the site's first record, an account and the Use Ledger show zero, and a
use area's page says the use area was not on record and shows today. On the
demonstration, no record is older than its last load. The ledger import rejects a file
downloaded with a past date in the As of box.

<!-- defines: terminal -->A *terminal* is the window where you type a command for the computer
to run. On an installation without Docker, load the variables in `.env` into the
terminal as the [no-Docker install guide](INSTALL-WITHOUT-DOCKER.md) shows. Run each command
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
| The `web` container will not start, and its log mentions `ImproperlyConfigured` | The production checks refused a setting. The database password is empty or a common default, `ALLOWED_HOSTS` is empty or `SECRET_KEY` is missing. Or `ACCOUNT_EMAIL_VERIFICATION` holds a value other than `none`, `optional` or `mandatory`. Or `OPENH2O_MODULES` names an unknown section, lists a section twice, leaves out `core`, `geography`, `measurements` or `standards`, or leaves out a section another section needs. | Read `docker compose logs web`, where the message names the setting. Correct it in `.env` and run `docker compose up -d`. |
| The Docker build fails on GDAL, GEOS or PROJ | The build could not install the map libraries. | Read the first error in the build output, then see the troubleshooting section of DEPLOY.md. |
| The site loads at its public domain, but without HTTPS | With `OPENH2O_SITE_ADDRESS` unset, Caddy serves plain web traffic on port 80 at any address, so pointing DNS at the computer does not produce a certificate. | Set `OPENH2O_SITE_ADDRESS` in `.env` to the bare domain as section 4 of DEPLOY.md describes, then run `docker compose up -d`. |
| A source on the monitoring dashboard shows "Needs API key", "No stations" or "None up to date" | "Needs API key": the source's key is missing from `.env`. "No stations": it has no station turned on. "None up to date": the source publishes rarely, as the groundwater sources do, or its sync is failing. | Add the key to `.env` and run `docker compose up -d`. Turn the stations on as Phase 4 describes. Run `sync_source` for the source with an earlier `--start` and read what it prints. |
| The reset page says the site does not send email, or a reset email never arrives | The site has no SMTP settings. | Add `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` and `DEFAULT_FROM_EMAIL` to `.env` and run `docker compose up -d`. Until then, an administrator sets a temporary password for the person on the Users page. For the only host administrator, run `docker compose exec web python manage.py changepassword` with the account's username. The username is the email address unless the account was given a different one. |
| 502 Bad Gateway after the computer restarts | The website container is still starting, or Docker did not start with the computer. | Set Docker to start when the computer starts. The compose file sets `restart: unless-stopped`, so the containers start again when Docker does. Run `docker compose ps`. If `web` is not `Up (healthy)`, run `docker compose up -d` and read `docker compose logs web`. |

---

## Guardrails

- **Never** commit the organization's `.env`, its API keys or the `secrets/` folder,
  which holds the key files that some data services require. Git is set to ignore
  them, so they stay out of the published code.
- **Never** run `make fresh` on a site that holds records, because it deletes the
  database. For a routine rebuild, run `docker compose up -d --build`. To upgrade, run
  `make upgrade` (Upgrades in section 11 of DEPLOY.md). On a live site, create the
  `.production-lock` file that section 11 describes. With that file in place,
  `make up`, `make down`, `make build` and `make fresh` refuse to run, and
  `make upgrade` still runs. The file also stops the demonstration targets
  (`make demo`, `make remove-demo`, `make reset-demo`, `make snapshot-demo` and
  `make calc-rebuild`), unless the checkout also holds `.demo-host`. Never run
  `make deploy`, which serves only the project's own demonstration site and will not
  run anywhere else.
- **Leave** `ACCOUNT_EMAIL_VERIFICATION` unset. When it is unset, it follows
  `EMAIL_HOST`. A person who signs up must confirm their email address when the site
  has a mail server, and need not when it has none. If it is set to `mandatory` on a
  site with no mail server, each person who signs up waits for an email the site cannot
  send. A person added by an administrator on the Users page does not need to confirm
  their email address.
- **Do not** weaken the production checks to get the site to start. Correct the
  setting that the message names.
- **Keep** the link that offers users the source code. If the organization changes
  OpenH2O's code and runs it for its users, the AGPL (section 13), the license
  OpenH2O is published under, requires the site to offer those users the changed
  source code. The Source code link at the foot of every page points at
  github.com/Open-H2O/openh2o. Set `SOURCE_CODE_URL` in `.env` to wherever the
  organization publishes its changes, then run `docker compose up -d`. See
  [NOTICE](../NOTICE).
