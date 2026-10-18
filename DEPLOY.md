<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Deploying OpenH2O

<!-- defines: docker -->
This guide gives every command for installing OpenH2O with Docker, from a fresh
server to a site the organization uses every day. It is written for an AI agent or
a person who has never used OpenH2O. The
[AI operator guide](docs/AI-OPERATOR-GUIDE.md) says what to ask the organization and
in what order to do the work. This guide is the reference for each step.

---

## 1. Server Requirements

<!-- defines: docker_compose --><!-- defines: sudo --><!-- defines: reverse_proxy --><!-- defines: cron -->
OpenH2O runs as three *containers*. A container is a package that holds one part
of a program and everything that part needs, so it runs the same way on any
computer, and Docker is the software that runs containers. The three containers are
the website, the database and Caddy. Caddy receives web traffic and handles the
encryption (section 4). Docker Compose comes with Docker. It starts, stops and
rebuilds the three containers together from one file, `docker-compose.yml`, and
every command in this guide that begins `docker compose` runs it. A command that
begins `sudo` runs with administrator rights. Installing software on the server
needs those rights.

| Requirement | Minimum |
|-------------|---------|
| Operating system | Ubuntu 22.04 or newer (the commands here are written for 24.04) |
| Memory | 2 GB (4 GB recommended) |
| Disk | 10 GB free |
| Docker Engine | 24 or newer |
| Docker Compose | version 2 |
| Git | any recent version |
| make | any recent version (`sudo apt-get install -y make`) |
| cron | any recent version (`sudo apt-get install -y cron`). Cron is the standard Linux scheduler, and section 11 installs OpenH2O's jobs in it |
| Domain name | Needed only when people outside the office network must reach the site. Phase 2 of the [AI operator guide](docs/AI-OPERATOR-GUIDE.md) explains the choice. |

Check that Docker is installed:

```bash
docker --version
# Expected: Docker version 24.x or newer

docker compose version
# Expected: Docker Compose version v2.x
```

If Docker is not installed, install it and add your account to the `docker` group:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
```

The second command takes effect at your next sign-in. Linux reads your groups only
when you sign in, so a `docker` command in the same terminal still fails with
`permission denied`. Sign out and sign in again. Until you do, put
`sudo` in front of each `docker` command.

Then confirm that Docker can run a container:

```bash
docker run hello-world
```

If the command fails with a message about "cgroup" or "bpf", the server's provider
is blocking containers. The provider sets that limit outside the server, so no
change to Docker on the server can lift it. Ask the provider
to allow containers, or install OpenH2O without Docker by following
[docs/INSTALL-WITHOUT-DOCKER.md](docs/INSTALL-WITHOUT-DOCKER.md). Follow that guide
too when the organization prefers not to install Docker.

---

<!-- defines: repository -->
## 2. Clone the Repository

OpenH2O's code is kept in a *repository* on GitHub. A repository is a folder of the
program's files together with the history of every change to them. *Cloning* the
repository copies that folder onto the server. Clone it into your home folder:

```bash
cd ~
git clone https://github.com/Open-H2O/openh2o.git
cd openh2o
pwd
```

`pwd` prints the folder's full path, such as `/home/operator/openh2o`. Note it,
because the schedule in section 11 needs it.

---

## 3. Environment Configuration

<!-- defines: env_file -->
OpenH2O reads its settings from a `.env` file, a plain text file with one
`NAME=value` line for each setting. Each installation has its own `.env` file, which
holds that site's settings and passwords. Git is set to ignore the file, so the
passwords stay out of the published code. Start from the example file:

```bash
cp .env.example .env
```

<!-- defines: secret_key -->
The site signs its sign-in cookies with a value called `SECRET_KEY`. Generate one,
and generate a database password:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"   # SECRET_KEY
python3 -c "import secrets; print(secrets.token_urlsafe(32))"   # POSTGRES_PASSWORD
```

Edit `.env` and set these values before the first start:

```bash
SECRET_KEY=<paste-generated-key-here>
POSTGRES_PASSWORD=<choose-a-strong-password>
DJANGO_SETTINGS_MODULE=config.settings.production
```

The example file sets `POSTGRES_PASSWORD=openh2o`, and the production settings
refuse to start with that password. The database stores its password when it is
first created, so set `POSTGRES_PASSWORD` before the first start. Changing the value
in `.env` later does not change the password the database already holds. Docker
Compose writes the password into the address the website uses to reach the
database, so a password containing `@`, `:`, `/` or `#` breaks that connection. The
second command above generates a password without those characters. The example
file already sets `DJANGO_SETTINGS_MODULE` to `config.settings.production`. Leave
that line as it is.

<!-- defines: allowed_hosts --><!-- defines: localhost -->
Then set `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`. `ALLOWED_HOSTS` lists the
addresses the site answers at, and OpenH2O refuses a request made to any other
address. `CSRF_TRUSTED_ORIGINS` lists the `https://` addresses from which OpenH2O
accepts a submitted form, such as the sign-in form. What goes in them depends on who
needs to reach the site. Section 4 and Phase 2 of the AI operator guide ask the same
question.

For a site that people reach from the internet at a domain:

```bash
ALLOWED_HOSTS=your-domain.com
CSRF_TRUSTED_ORIGINS=https://your-domain.com
```

A site on this computer only, or on the office network, has no domain, so
`CSRF_TRUSTED_ORIGINS` stays empty. `localhost` and `127.0.0.1` are two names for the
address a computer uses for itself, and no other computer can reach that address.
For a site on the office network, list the computer's address on that network
instead. `hostname -I` prints it:

```bash
# only this computer
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=

# or, on the office network, the computer's address on that network
ALLOWED_HOSTS=192.168.1.40
CSRF_TRUSTED_ORIGINS=
```

The production settings always add `127.0.0.1` and `localhost` to `ALLOWED_HOSTS`,
so commands run on the server itself can reach the site.

Section 12 lists every setting the code reads, with its default.

---

<!-- defines: tls_https -->
## 4. Caddy / HTTPS Configuration

This section sets up two things: Caddy, and the encryption of the connection.

The first is Caddy, a *reverse proxy*: a program that receives the traffic arriving
from outside and passes it to the website behind it. Its settings are in the file
named `Caddyfile`. Some organizations already run a proxy of their own in front of
their servers. In that case the organization's proxy passes traffic to Caddy, and
Caddy passes it to OpenH2O. OpenH2O supports this setup.

The second is the encryption. *HTTPS* is the encrypted connection a browser marks
with a padlock. It depends on a *certificate*, a file that proves the address
belongs to this site. The table shows what to do with the `Caddyfile`, depending
on who needs to reach the site:

| Who needs to reach the site | What to do with the `Caddyfile` | Follow |
|---|---|---|
| Only this computer, or the office network | Leave it as shipped | **Branch A** |
| The public internet, and this server obtains its own certificate | Replace `:80` with your bare domain | **Branch B** |
| The public internet, and something in front of the server handles the encryption | Leave `:80` as shipped, or write `http://your-domain.com` | **Branch C** |

Phase 2 of [docs/AI-OPERATOR-GUIDE.md](docs/AI-OPERATOR-GUIDE.md) asks the same
question. Follow Phase 2 for the `.env` settings and this section for the
`Caddyfile`.

⚠ The `Caddyfile` examples below are shortened. The shipped file carries more: two access logs (section 11 reads them), a
security header, a caching rule for the styling and scripts, the header that tells
OpenH2O a request arrived over HTTPS, retry timings for the first moments after a restart,
and a page to show while the site is down. Edit the shipped file. If you replace it
with one of the examples, you lose all of these.

<!-- branch: no-public-access -->

### Branch A: Only this computer, or the office network

Leave the `Caddyfile` as it ships. There is no domain to name and no certificate to
obtain. You reach the site at `http://localhost`, or at the computer's address on
the office network.

Then set these three settings in `.env`:

```bash
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
```

The production settings mark the sign-in cookies secure, and a browser sends a
cookie marked secure only over HTTPS. Without these three lines, every sign-in over
plain `http://` fails with a 403 error, even though the pages that need no sign-in
still load. Phase 2, step 3 of the [AI operator guide](docs/AI-OPERATOR-GUIDE.md)
gives the same settings. Keep `DEBUG` off, keep `ALLOWED_HOSTS` set to the site's
own address and keep the strong database password.

<!-- defines: port -->
⚠ These settings do not narrow who can reach the computer. A *port* is a numbered
entry point on a computer for one kind of network traffic. Port 80 carries plain web
traffic, which a browser uses for an `http://` address with no port number. Port 443
carries encrypted web traffic. As shipped, `docker-compose.yml` opens both ports
on every network the computer is connected to, so anything that can reach the
computer can reach the site.

For a site on this computer only, change the two lines in `docker-compose.yml` from
`80:80` and `443:443` to `127.0.0.1:80:80` and `127.0.0.1:443:443`, and run
`docker compose up -d`. Then, from a second computer on the same network, run
`curl -I http://` followed by this computer's network address, and confirm that the
connection is refused. For a site on the office
network, leave both lines as they are, and tell the organization that anyone on that
network can reach the site.

<!-- branch: own-certificate -->

### Branch B: Public internet, and this server obtains its own certificate

Replace `:80` with your domain, written as a bare address with no `http://` or
`https://` in front of it. When the domain is written bare, Caddy obtains a free
certificate for it on its own.

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

<!-- defines: dns -->
Before you start the containers, make sure of two things.

1. **The domain's A record points at this server's public address.** DNS is the
   internet's directory. It matches a domain name to the numeric address of a
   computer. An *A record* is the DNS entry that holds that numeric address, and you
   edit it at the company where the domain was bought. The certificate's issuer
   checks that the name leads to this server before it issues a certificate, so the
   A record has to be in place first.
2. **Ports 80 and 443 are open to the internet.** The site is served on port 443. The
   issuer's check can arrive on either port, so open both. With port 80 closed,
   anyone who types the address without `https://` reaches nothing.

Keep `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` on for
this branch. They are on by default.

No test in this project runs this branch from start to finish. The steps follow
Caddy's own documentation. If something fails on this branch, please report it at
github.com/Open-H2O/openh2o/issues.

<!-- branch: upstream-terminator -->

### Branch C: Public internet, and something in front of the server handles the encryption

This branch is for a tunnel service, the organization's own proxy or a load
balancer: anything that receives the encrypted traffic, decrypts it and sends plain
traffic on to this server.

Leave `:80` as shipped. If you want the `Caddyfile` to answer only at your domain,
write the domain with the `http://` prefix. Do not write a bare domain on this
branch.

```caddy
http://your-domain.com {
    encode gzip

    handle /static/* {
        root * /srv
        file_server
    }

    handle {
        reverse_proxy web:8000 {
            header_up X-Forwarded-Proto https
        }
    }
}
```

The `http://` prefix tells Caddy to serve that name over plain HTTP and to order no
certificate. With a bare domain, Caddy orders a certificate. The service in front
of the server still sends plain traffic, so the requests loop until they fail.

<!-- defines: x_forwarded_proto -->
Keep the `header_up X-Forwarded-Proto https` line. It makes Caddy add a header to
each request it passes on. The `X-Forwarded-Proto` header tells OpenH2O that the
visitor's connection was encrypted, and OpenH2O's production settings trust it.
Without the header, OpenH2O sees plain traffic and redirects every request to HTTPS,
so the requests loop.

Keep `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE` on for
this branch.

---

## 5. Build and Start

```bash
docker compose up -d --build
```

The three containers start one after another. The database has to report healthy
before the website container starts. The website container then does its own
start-up work in this order. It gathers the styling and images, runs the
<!-- defines: migrations -->migrations that create or update the database tables (section 6),
creates a cache table, and creates the administrator account if `.env` asks for one
(section 7). It reports healthy after that, and Caddy starts. A first build takes a few minutes. Check with:

```bash
docker compose ps
```

Once all three are up, `db` and `web` show `Up (healthy)` and `caddy` shows `Up`.
The compose file gives Caddy no health check, so its row shows only `Up`.

---

## 6. Run Migrations

<!-- defines: migrations -->
The *migrations* create or update the database tables to match this version of
OpenH2O. The website container runs them each time it starts, so after section 5 the
tables are already in place. You can run them by hand at any time:

```bash
docker compose exec web python manage.py migrate
```

When the tables are up to date, the command reports that there are no migrations to
apply.

---

<!-- defines: superuser -->
## 7. Create Superuser

The first account is a *superuser*. A superuser can do everything in OpenH2O,
including adding the other staff accounts. It is an OpenH2O account and is separate
from any login to the server, and nobody can sign in until it exists. You choose its
password yourself, because the account does not exist until you create it. Generate
a strong one:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(18))"
```

Give the password to the organization through its password manager, or hand it over
in person. Do not send it in a chat message or leave it in a file on the server.

Create the account in one of two ways.

Set `DJANGO_SUPERUSER_EMAIL` and `DJANGO_SUPERUSER_PASSWORD` in `.env`, then run
`docker compose up -d`. Each time the website container starts, it creates the
account if the account does not exist, and it sets the account's password to the one
in `.env`. If the administrator later changes the password on the site, remove the
password line from `.env`, or the next start sets it back.

Or create the account at a prompt:

```bash
docker compose exec web python manage.py createsuperuser
```

Answer the prompts for a username, an email address and a password.

Give the account an email address that someone reads. The **Forgot password?** link
on the sign-in page sends its reset link to that address. If the address is an
invented one, such as an `admin@` address nobody reads, the link reaches no one. To
change the address later, an administrator clicks **Change email** beside the account
on the Users page (`/users/`). The button changes the person's sign-in address in
every place OpenH2O keeps it. Then read *Email / Password Reset* in section 11. The
site sends reset links only after its email settings are in place.

---

<!-- defines: seed_data -->
## 8. Seed Reference Data

*Seeding* a database means loading a starting set of records into it. This section
loads the reference lists every site needs. Section 9 loads the demonstration data.

```bash
docker compose exec web python manage.py seed_data
```

`seed_data` runs these commands in this order. The first two always run. Each of
the others belongs to a module of OpenH2O that a site can switch off (section 12).
On a site without that module, `seed_data` skips the command and says so.

- `seed_roles` (admin, manager, viewer)
- `seed_observed_properties` (the standards crosswalk, which maps each data source's
  own parameter codes to a standard list of measured properties. `check_conformance`
  checks the data against it.)
- `seed_water_types` (Groundwater, Surface Water, Recycled Water and others)
- `seed_well_types` (Production, Monitoring, Injection, Observation)
- `seed_data_sources` (CDEC, USGS, OpenET, CIMIS, CNRFC, DWR, NOAA)
- `seed_drinking` (the federal maximum contaminant levels for the drinking-water
  module)
- `seed_water_right_types` (Appropriative, Pre-1914, Riparian and others)
- `seed_report_templates` (the report formats. Reporting is off by default, and this
  command is skipped while it is off.)

To run one of them on its own:

```bash
docker compose exec web python manage.py seed_roles
```

Running `seed_data` again changes nothing that is already in place.

---

## 9. Load the Demonstration Dataset (Optional)

The demonstration covers a real groundwater basin. It combines the basin's
published records with invented sample data, and it gives the organization a
complete site to explore.

```bash
docker compose exec web python manage.py seed_merced
```

`seed_merced` needs a site that runs every module of OpenH2O. Set
`OPENH2O_MODULES=all` in `.env` and run `docker compose up -d` first (section 12). It loads the basin's boundary, streams and
canals, management zones, water rights and points of diversion, selected parcels,
cropland, recharge basins and a year of ledger activity. One of its steps downloads
streams and monitoring stations from public government services and needs no key.
On a server with no internet connection, add `--skip-auto-populate` to leave that
step out.

The demonstration's records stay on the site beside the organization's own records,
and OpenH2O has no command that removes them. (The `make flush-demo` and
`make teardown-demo` targets handle two older sample datasets, and they leave this
one in place.) If the organization wants its site without the demonstration, load
it on a second copy of OpenH2O.

The demonstration's water rights, deliveries, parcels and ledger activity are all
seeded. Its consumptive use figures come from satellite evapotranspiration (ET)
data. That data needs an OpenET key (section 11) and a run of
`sync_openet_parcels`, which Phase 4 of the AI operator guide shows. Until then,
those figures stay empty.

The nightly calculation, `run_accounting`, runs `run_calculations` month by month,
and both need an active calculation method. Neither `seed_data` nor `seed_merced`
creates one. Create it with:

```bash
docker compose exec web python manage.py seed_calculation_plan
```

When `seed_merced` finishes, it prints a list of what the site still needs, and
`seed_calculation_plan` is on that list. If a method is in place but there is no ET
data yet, `run_calculations` skips every parcel and reports that it has no ET
data.

<!-- defines: idempotent -->
Every step of `seed_merced` but one is *idempotent*: running it again gives the
same result as running it once, because it skips what is already done. The
exception deletes and redraws the demonstration's parcel outlines and well
locations, so under the production settings `seed_merced` stops at that step when
demonstration records already exist. A first run on an empty database needs no flag. To
rebuild the demonstration:

```bash
docker compose exec web python manage.py seed_merced --allow-prod-clobber
```

The populate step that downloads monitoring stations creates every station switched
off, so a new demonstration shows no stations reporting until they are turned on.
OpenH2O ships with the demonstration's own list of 335 stations. Of those, 42 are
switched on, and each of the 42 carries the date it last published a reading. One
command loads the list over the stations the populate step created:

```bash
docker compose exec web python manage.py load_station_fixture
```

It downloads nothing, and a second run changes nothing. Run it after `seed_data`
(section 8), because `seed_data` creates the data sources the station list refers
to. Without them it stops with a
message and writes nothing. For the organization's own area, turn on the area's own
stations as Phase 4 of the AI operator guide describes.

The organization's own records come in through the Setup Wizard (section 11) and
the imports in [docs/DATA-IMPORT.md](docs/DATA-IMPORT.md). Once they are loaded,
run OpenH2O's two checks over them:

```bash
docker compose exec web python manage.py check_conformance
docker compose exec web python manage.py run_health_checks
```

`check_conformance` reports whether every kind of measurement in the database maps
to a known property with a unit. `run_health_checks` checks the database, the disk,
the certificate, the migrations and whether the data sources are current. Section 11
covers both.

---

## 10. Verify Deployment

Run the checks at the address the organization will use: `http://localhost` or the
computer's office-network address on Branch A, and `https://your-domain.com` on
Branch B and Branch C. A site that answers only on the server itself looks the same
from the server as a site that works.

**A response through Caddy:**

```bash
curl -s -o /dev/null -w '%{http_code}' http://localhost
# Expected: 200 or 302
```

This check works on Branch A and Branch C, where Caddy answers on port 80 at any
address. On Branch B the `Caddyfile` names one domain, so Caddy refuses a request
made to `localhost`. Run this check and the health API check below against the
domain over `https://` instead.

<!-- defines: postgis -->
**PostGIS:** PostgreSQL is the database that stores every record the site
shows. PostGIS is its extension for maps, boundaries and locations. Check that
PostGIS is installed:

```bash
docker compose exec db psql -U openh2o -d openh2o -c "SELECT PostGIS_Version();"
# Expected: a version string beginning 3.4
```

**The health API:**

```bash
docker compose exec web python manage.py run_health_checks
curl -s http://localhost/health/api/ | python3 -m json.tool
# Expected: "status" is "healthy" or "degraded"
```

The API reports `healthy`, `degraded` or `unhealthy`. It reports `unknown` until the
health checks have run once, which is why the first command runs them.

**The Site health page:** open `/health/` in a browser, at the address above.

**The administration site:** open `/admin/` at the same address and sign in as the
superuser.

**Sign-in without a browser:** on Branch B and Branch C, `CSRF_COOKIE_SECURE` stays
on, so a sign-in sent over plain `http://` returns 403. On Branch A the setting is
off, so a plain `http://` sign-in can succeed. Phase 2 of the
[AI operator guide](docs/AI-OPERATOR-GUIDE.md) gives a sign-in check that works on
every branch, under "To check sign-in without a browser".

**The website's log:**

```bash
docker compose logs web --tail=50
# Look for gunicorn listening at http://0.0.0.0:8000, and no tracebacks or errors
```

**The name the site's emails go out under:** every email the site sends starts its
subject line with the site's name. OpenH2O takes that name from the organization's
name, which is set at `/admin/` under Core > Site configs. It takes the site's
address from `ALLOWED_HOSTS`, and it saves both when the migrations run. Set the
organization's name there after the superuser exists. Check what it saved:

```bash
docker compose exec web python manage.py shell -c "from django.contrib.sites.models import Site; s = Site.objects.get_current(); print(s.name, '|', s.domain)"
```

The command should print the organization's name and the site's web address.
`docker compose exec web python manage.py check` also reports a missing name or
address, with the warning code `openh2o.W002`. If the name is missing, set the organization's name at
`/admin/` under Core > Site configs, then run the migrations again (section 6). A
site reached only at `localhost` keeps `example.com` as its address and keeps the
warning, because OpenH2O skips `localhost` and `127.0.0.1` when it works out the
address. On such a site the warning is harmless. A site on the office network takes
the computer's address on that network.

**Who can reach the site:** the checks above show that the site answers. They do not
show who can reach it. A site can work correctly and still be open to the whole
internet. Check which network addresses can reach ports 80 and 443. A plain Ubuntu
server usually has `ufw`, and other Linux computers have `firewalld` or `iptables`.
On a rented server, the controlling rule is often in the provider's control panel,
under a name such as "security group", "cloud firewall" or "networking". Check
whichever the server has. With `ufw`:

```bash
sudo ufw status verbose
```

⚠ Docker writes its own firewall rules for the ports in `docker-compose.yml`, and
those rules take effect ahead of `ufw`. A `ufw` rule that blocks port 80 therefore
does not block the site. To keep the site on this computer only, change the port
lines in `docker-compose.yml` as Branch A describes, and test from a second
computer.

Compare the answer with the branch you chose in section 4:

| Section 4 branch | Who should reach the site | A wrong answer |
|---|---|---|
| **Branch A** (`no-public-access`) | This computer only, or the office network only | Someone outside the office can open the site |
| **Branch B** (`own-certificate`) | The whole internet, on ports 443 and 80 | Nothing outside reaches the server on either port, so no certificate is issued and the site never comes up |
| **Branch C** (`upstream-terminator`) | Only the service in front of the server | The whole internet reaches port 80 directly and goes around that service |

Fix any wrong answer before you hand the site over. On Branch C, if the server
answers at its own address as well as through the service in front, anyone can go
around that service. `ALLOWED_HOSTS` does not stop them, because a visitor's own
request names the address it is sent to. Close the ports to everything except the
service in front.

---

## 11. Ongoing Operations

### The Setup Wizard (`/setup/`)

<!-- defines: geojson -->
The Setup Wizard loads the organization's area through the browser. It asks for
the boundary of the area the site covers and shows that boundary on a map for you to
confirm. It then runs the populate steps, which download basins, parcels, streams
and monitoring stations for the area from public services, shows their progress,
and turns on the stations those steps find. The boundary can be a zipped shapefile,
a KML file or a GeoJSON file. GeoJSON is a plain-text format for map shapes and the
facts attached to them, such as a name and an area. You can also type the area's
north, south, east and west edges by hand, or give no boundary at all.

- **Where it is.** The wizard is in the left sidebar, under Administration. The Administration
  section is hidden in the sidebar's everyday view. At the bottom of the sidebar, a
  switch reads **Operations** and **Admin**. Click **Admin**, then **Setup Wizard**.
  A new site opens in the Operations view, which is the usual reason someone cannot
  find the wizard.
- **Who can open it.** Only a signed-in administrator can open it. On a site with
  `ACCESS_CONTROL_ENFORCED=False`, any signed-in person can open it. Create the
  superuser (section 7) first.
- **Its last step.** **Enable all** turns on every switched-off station inside the
  boundary. The populate step creates stations switched off, and a sync fetches data
  only for stations that are on. Over SSH, `activate_stations` does the same:
  `docker compose exec web python manage.py activate_stations --boundary-name "<the boundary's name>"`.

### Upgrades

These commands upgrade a site that holds the organization's records. They update
the code and the database tables and leave the records as they are:

```bash
cd /path/to/openh2o
git pull origin main
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py collectstatic --noinput
```

The website container already runs the migrations and gathers the styling and images
when it starts, so the last two commands find nothing left to do. They do no harm. Back
up the database and `.env` before you upgrade (Database Backup, below).

Never use `make deploy` to upgrade. It is the target for the project's own
demonstration site, and it replaces that site's database with demonstration data.
It refuses to run in a checkout without a file named `.demo-host`. Never create that
file on a site that holds records.

### Protecting a Live Installation (`.production-lock`)

`make up`, `make down`, `make build` and `make fresh` stop, rebuild or reset the
containers, and `make fresh` deletes the database. Once the site holds the
organization's records, protect the site from these commands. Create an empty file named
`.production-lock` in the checkout:

```bash
touch .production-lock
```

With the file in place, those four commands refuse to run and say why. Git ignores
the file, so a new clone comes without one. Create it on each site as soon as real
records arrive. To run one of the four commands anyway, remove the file, run the
command and create the file again:

```bash
rm .production-lock
make down
touch .production-lock
```

The refusal message suggests `make deploy`. Never run it on an organization's site
(see Upgrades). The file does not guard the demonstration targets, such as
`make merced`, `make flush-demo`, `make teardown-demo` and `make reset-demo`, or
`docker compose down -v`, which deletes the database. Never run those on a site that
holds records.

<!-- defines: cron -->
### Scheduled Jobs

OpenH2O uses cron to fetch new readings, run its calculations and check its own
health. The jobs are in `crontab.txt`:

| Job | Schedule | Purpose |
|-----|----------|---------|
| `run-sync.sh cdec usgs` | Every hour | Stream and reservoir readings |
| `run-sync.sh dwr_wdl dwr_sgma noaa` | Every day at 2:00 | Groundwater levels and climate data |
| `run_accounting --open-periods --trigger schedule` | Every day at 3:30 | Calculates every reporting period that is not finalized, after the 2:00 sync. A finalized period is never changed. Each run's record shows on the period's page and on Site health |
| `run_health_checks` | Every 6 hours | Checks the database, the disk, the certificate, the migrations and the data sources |
| `prune_old_data --confirm` | The 1st of each month at 3:00 | Deletes sync logs, health-check results and published staging records older than a year |

The times are in the server's own time zone. The schedule does not sync CIMIS or
OpenET. To keep CIMIS current once its key is set, add `cimis` to the end of the
2:00 line. OpenET's figures arrive through `sync_openet_parcels`, which the
organization runs when it wants figures for new months (Phase 4 of the AI operator
guide).

You can also run the calculation by hand, for one water year or one month:
`docker compose exec web python manage.py run_accounting --period "WY 2025-2026"` or
`--month 2026-03`. Only one calculation runs at a time, and a second one waits for
the first.

`check_conformance` is not on the schedule, because its answer changes only when
someone loads data or turns on a new source. Run it after the organization's own
records are loaded (section 9), and before the data is shared or published. It exits
with an error code when it finds a gap, so a script can stop on it.

```bash
docker compose exec web python manage.py check_conformance
```

`scripts/run-sync.sh` runs `docker compose up -d` first, which starts the containers
again if a restart of the server left them stopped. It then runs each sync and
writes to `sync.log` in `$OPENH2O_LOG_DIR`. When a sync fails and `OPENH2O_NTFY_URL`
is set, it sends an alert through ntfy, a service that sends notifications to a
phone or a browser.

Before you install the schedule, edit the top of `crontab.txt`. Set `OPENH2O_DIR` to
the folder `pwd` printed in section 2, and `OPENH2O_LOG_DIR` to a folder your own
account can write logs to, such as `/home/operator/openh2o-logs`. The defaults are
`/opt/openh2o` and `/opt/openh2o-logs`. For failure alerts, also add a line at the top
of `crontab.txt` that reads `OPENH2O_NTFY_URL=` followed by the address of an ntfy
topic, the channel your alerts go to. The setting has to be in the schedule, because
a value in `.env` never reaches the script. Then install the schedule:

```bash
make install-cron
# check:
make show-cron
```

`make install-cron` copies `crontab.txt` as it is at that moment, and it adds the
lines to whatever is already installed. To change the schedule later, or to replace
older OpenH2O lines, edit the installed schedule with `crontab -e`. Running
`make install-cron` again adds the lines a second time, and every job would then run
twice.

<!-- defines: api_key -->
### External Data API Keys

An *API key* is a long password that lets OpenH2O fetch data from another
organization's service without a person signing in. Keep each key secret.

CDEC (the California Data Exchange Center), USGS and the Department of Water
Resources' Water Data Library and SGMA Portal need no key. Three sources need a key.
Set each key in `.env`, then run `docker compose up -d`:

| Source | `.env` setting | Get a key from |
|--------|----------------|----------------|
| CIMIS (the California Irrigation Management Information System) | `CIMIS_API_KEY` | https://cimis.water.ca.gov (register, then App Key) |
| NOAA's Climate Data Online | `NOAA_CDO_TOKEN` | https://www.ncdc.noaa.gov/cdo-web/token |
| OpenET (satellite evapotranspiration) | `OPENET_API_KEY` | https://etdata.org (account, then API key) |

Until its key is set, CIMIS or NOAA shows as needing a key on the monitoring page,
and a sync skips it. OpenET is not a station source. `sync_all` never syncs it, and
its figures arrive through `sync_openet_parcels`.

### Map Basemaps (streamed, no tile server to host)

The maps draw their background from two outside services on every page load:

| Basemap | Streams from | Needs a key? |
|---------|--------------|--------------|
| Aerial (the default) | Esri World Imagery and labels, `server.arcgisonline.com` | No |
| Dark | OpenFreeMap vector tiles, `tiles.openfreemap.org`, over a Natural Earth layer | No |

There is nothing to set up or back up for the background. When Esri or OpenFreeMap
cannot be reached, the background fails to load, and OpenH2O's own layers (parcels,
wells, diversions and boundaries) still draw on top. The map program itself and the
page scripting library load from `unpkg.com`, so on a network with no internet
access, no map appears at all.

<!-- defines: smtp -->
### Email / Password Reset (SMTP)

*SMTP* is the standard way a program hands outgoing email to a mail provider. With
an SMTP account, the site can send email. The most important email it sends is the
password-reset link.

A signed-in person can change their own password without any email setup. They
click their email address at the top of the page to open their profile page, then
click **Change password**. The **Forgot password?** link on the sign-in page emails a reset link,
so it needs a mail provider. Until the site has SMTP settings, that link sends no
email.

Set these in `.env`, then run `docker compose up -d`:

```bash
EMAIL_HOST=smtp.your-provider.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=<smtp-username>
EMAIL_HOST_PASSWORD=<smtp-password-or-app-password>
DEFAULT_FROM_EMAIL=noreply@your-domain.com
```

Any SMTP provider works. Two common choices:

- **Gmail:** host `smtp.gmail.com`, port `587`, the full Gmail address as the user,
  and a 16-character App Password as the password (Google Account, Security, 2-Step
  Verification, App passwords). Gmail limits how much it sends in a day.
- **A transactional email provider, a service built to send a website's email, such
  as Resend, Postmark or Amazon SES:** these services send from an address at your
  own domain and allow more email per day than Gmail.

Send a test email:

```bash
docker compose exec web python manage.py sendtestemail you@example.com
```

#### Signup email verification

`ACCOUNT_EMAIL_VERIFICATION` decides whether a person who signs up must confirm
their email address before they can sign in. It takes `none`, `optional` or
`mandatory`.

Leave it unset. When it is unset, the site chooses a value from `EMAIL_HOST`. With a
mail server, a person who signs up must confirm (`mandatory`). Without one, they sign
in at once (`none`), so a site with no mail server never holds an account that is
waiting for an email it cannot send.
Accounts an administrator adds on the Users page and the account `ensure_superuser`
creates are confirmed when they are made. If the setting is `mandatory` on a site
with no mail server, each person who signs up waits for an email the site cannot
send. A value other than the three stops the container at start with an
error that names the value.

This matters only where sign-up is open. `ACCESS_CONTROL_ENFORCED` is `True` by
default. With that value, sign-up is closed and an administrator adds each account.

### Health Checks

Run them at any time:

```bash
docker compose exec web python manage.py run_health_checks
# or: make health
```

For output a monitoring tool can read:

```bash
docker compose exec web python manage.py run_health_checks --json
```

### Data Pruning

See what would be deleted, without deleting anything:

```bash
docker compose exec web python manage.py prune_old_data
# or: make prune
```

To delete those records:

```bash
docker compose exec web python manage.py prune_old_data --confirm
```

### Data Sync

Sync every data source that is turned on, or one source:

```bash
docker compose exec web python manage.py sync_all
docker compose exec web python manage.py sync_source cdec
# or: make sync
```

A sync fetches from the live public services. A source whose key is missing is
skipped until the key is in `.env`.

### Running Tests

```bash
make test
```

`make test` checks that the image matches the code, then runs the test suite with
every section of OpenH2O switched on, under the development settings the tests are
written for.

### Database Backup

```bash
docker compose exec -T db pg_dump -U openh2o openh2o > backup-$(date +%Y%m%d).sql
```

The dump holds every record. It leaves out two Docker volumes, the storage areas
Docker keeps outside the containers. `media_files` holds uploaded files, such as
feedback screenshots and the site's logo. `caddy_data` holds Caddy's certificates,
which Caddy can obtain again. To copy the uploaded files as well:

```bash
docker compose cp web:/app/media ./media-backup-$(date +%Y%m%d)
```

Keep a copy of `.env` with the backups, because it holds `SECRET_KEY` and the
database password, and store it as carefully as a password. Back up on a regular
schedule, for example with a cron line like the ones in `crontab.txt`, and keep the
backups on another computer or another disk. Back up before every upgrade. The
commands here use the database name and user `openh2o`. If `.env` sets
`POSTGRES_DB` or `POSTGRES_USER` to something else, use those names.

### Database Restore

Restore into an empty database. Stop the website, delete and recreate the database,
load the backup, then start the website again. Do this when no scheduled sync is
due, because `run-sync.sh` starts the website container again:

```bash
docker compose stop web
docker compose exec db dropdb -U openh2o openh2o
docker compose exec db createdb -U openh2o openh2o
docker compose exec -T db psql -U openh2o -d openh2o < backup-20250101.sql
docker compose start web
```

### View Logs

```bash
docker compose logs web          # the website
docker compose logs db           # the database
docker compose logs caddy        # Caddy
docker compose logs -f web       # follow the website's log as it is written
```

Those logs show whether something is broken. Caddy also keeps a record of each
visit, which shows when each page was opened:

```bash
docker compose logs caddy | grep 'handled request'       # recent visits
docker compose exec caddy cat /var/log/caddy/access.log  # the copy that is kept
```

The first command reads what the Caddy container has written since it last started.
A rebuild (`docker compose up -d --build`) replaces the container and its log. The
second command reads a file kept on its own Docker volume, and that file survives a
rebuild.
Use the first to watch visits as they arrive, and keep the second as the record.

Each line records one request: the time, the address it came from, the page or file
asked for, and a three-digit status code. The common codes are `200` for served,
`302` for sent to another page, `404` for not found and `500` for an error in
OpenH2O. One person
opening one page writes several lines, because the styling, the fonts and the map
tiles are each a request of their own. The kept file has one machine-readable record
per line, with its time as a count of seconds since 1 January 1970. To list the pages and files asked
for:

```bash
docker compose exec caddy grep -o '"uri":"[^"]*"' /var/log/caddy/access.log | tail -50
```

When the kept file reaches 10 MB, Caddy sets it aside and starts a new one, and
Caddy keeps five of the older files. The record therefore stays at 60 MB or less
without anything to install or schedule. On a busy site, that much log covers a
shorter span of time. Check how much yours holds:

```bash
docker compose exec caddy ls -lh /var/log/caddy/
```

To keep visits for longer, copy the file elsewhere on a schedule. Leave the size
limit as it is, because the limit stops the log from filling the disk.

The website checks its own health every few seconds from inside its container, so
those checks never pass through Caddy and stay out of this record. They do appear in
`docker compose logs web`.

---

<!-- defines: environment_variable --><!-- defines: wsgi_gunicorn --><!-- defines: oauth -->
## 12. Environment Variables Reference

An *environment variable* is a named value a program receives when it starts. Each
line of `.env` sets one environment variable, and every name in the tables below is
an environment variable.

Two terms in the tables need explaining:

- **Gunicorn** is the web server inside the website container. It receives each
  request and hands it to OpenH2O's code. WSGI is the standard way a Python web
  server makes that handover, which is why one of OpenH2O's files is named
  `wsgi.py`.
- **OAuth** lets staff sign in with an existing Google account in place of a
  separate OpenH2O password. Google confirms who they are. The *client ID* and
  *client secret* are the two values Google issues so that it recognizes this site.

### The site and its security

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | Yes | none | The key the site signs its cookies with. The site refuses to start without it |
| `DJANGO_SETTINGS_MODULE` | Yes | `config.settings.production` in the compose file and `manage.py`. `config.settings.local` in `config/wsgi.py` and `config/asgi.py` | Use `config.settings.production` on every site. Outside Docker, the web server needs it in its environment, as [docs/INSTALL-WITHOUT-DOCKER.md](docs/INSTALL-WITHOUT-DOCKER.md) shows |
| `ALLOWED_HOSTS` | Yes, under production | empty | The addresses the site answers at, separated by commas. The production settings refuse to start when it is empty, and they always add `127.0.0.1` and `localhost` |
| `CSRF_TRUSTED_ORIGINS` | For a site at a domain | empty | The `https://` addresses from which the site accepts a submitted form, separated by commas. Leave it empty on a site without HTTPS |
| `SECURE_SSL_REDIRECT` | No | `True` | Redirects plain `http://` requests to `https://`. Set `False` on Branch A |
| `SESSION_COOKIE_SECURE` | No | `True` | Sends the sign-in cookie only over HTTPS. Set `False` on Branch A |
| `CSRF_COOKIE_SECURE` | No | `True` | Sends the form-check cookie only over HTTPS. Set `False` on Branch A |
| `ACCESS_CONTROL_ENFORCED` | No | `True` | Closes sign-up and keeps the administrator pages for administrators. Set `False` only on an open demonstration site, where anyone may sign up. A viewer stays read-only either way |
| `OPENH2O_MODULES` | No | every module except `reporting` | The modules of OpenH2O the site runs, separated by commas, or `all`. The list must include `core`, `geography`, `measurements` and `standards`. A list that leaves out a module another module needs stops the site at start with an error that names the missing module. The demonstration needs `all` |
| `TIME_ZONE` | No | `America/Los_Angeles` | The site's time zone |
| `LOG_DIR` | No | `/app/logs` | The folder for the error log, `openh2o.log`, which rotates at 10 MB and keeps five files. Inside Docker it is on the `logs_data` volume |
| `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD` | No | empty | Create the first administrator at each start, and set its password to this value (section 7) |
| `DJANGO_SUPERUSER_USERNAME` | No | the email address | The username for that account |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT` | No | `3`, `4`, `60` | How many requests the web server handles at once, and how many seconds it gives each one |

### The database

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POSTGRES_DB` | No | `openh2o` | The database's name |
| `POSTGRES_USER` | No | `openh2o` | The database user |
| `POSTGRES_PASSWORD` | Yes, under production | `openh2o` | The database password. The production settings refuse to start when it is empty or is one of `openh2o`, `postgres`, `password` or `changeme`. They check those values only and do not measure strength. Set it before the first start (section 3), and avoid `@`, `:`, `/` and `#` |
| `DATABASE_URL` | No | built by the compose file | The database's address. The compose file builds it from the three settings above and ignores a value in `.env`. Outside Docker, set it in `.env` |

### Email

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `EMAIL_HOST` | No | empty | The SMTP server |
| `EMAIL_PORT` | No | `587` | The SMTP port |
| `EMAIL_USE_TLS` | No | `True` | Encrypt the connection to the SMTP server |
| `EMAIL_HOST_USER` | No | empty | The SMTP user |
| `EMAIL_HOST_PASSWORD` | No | empty | The SMTP password |
| `DEFAULT_FROM_EMAIL` | No | `noreply@openh2o.com` | The sender address. Set it to an address at your own domain |
| `EMAIL_BACKEND` | No | SMTP under production; printing to the log under the development settings | How the site sends email |
| `ACCOUNT_EMAIL_VERIFICATION` | No | follows `EMAIL_HOST`: `mandatory` with a mail server, `none` without | Whether a person who signs up must confirm their email address: `none` lets them in at once, `optional` sends the email without waiting, `mandatory` waits for the confirmation. Any other value stops the site at start |

### Data sources

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CIMIS_API_KEY` | For CIMIS | empty | CIMIS's key (section 11) |
| `NOAA_CDO_TOKEN` | For NOAA | empty | NOAA's key (section 11) |
| `OPENET_API_KEY` | For OpenET | empty | OpenET's key (section 11) |
| `OPENET_MONTHLY_BUDGET` <!-- defines: openet_budget --> | No | `100` | OpenH2O stops sending OpenET requests when the month's count reaches this number. Raise it to the account's allowance |
| `OPENET_CACHE_DAYS` | No | `30` | How long OpenH2O keeps an OpenET estimate before asking again |
| `OPENET_MODE` | No | `api` | `api` fetches ET from OpenET's service. <!-- defines: google_earth_engine -->`gee` fetches the same data from Google Earth Engine, Google's service for analysing satellite imagery, as [docs/earth-engine-tier-setup.md](docs/earth-engine-tier-setup.md) describes |
| `GEE_PROJECT`, `GEE_SERVICE_ACCOUNT_EMAIL`, `GEE_SERVICE_ACCOUNT_KEY_FILE` | With `OPENET_MODE=gee` | empty | The Google Earth Engine project, its service account and the path to the account's key file. The compose file makes the `secrets/` folder readable inside the container at `/run/secrets` |
| `DATASYNC_MOCK_MODE` | No | `False` | Use sample data in place of the live public services |

### Sign-in with Google, feedback and visitor statistics

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GOOGLE_OAUTH_CLIENT_ID` | No | empty | Google's client ID for this site, described after this table |
| `GOOGLE_OAUTH_CLIENT_SECRET` | No | empty | Google's client secret for this site, described after this table |
| `FEEDBACK_ENABLED` | No | `False` | Shows the feedback form on every page. Turn it on where someone will read the reports |
| `FEEDBACK_ENDPOINT` | No | empty | An address to send each stored report to as well. Blank keeps the reports on the site only |
| `FEEDBACK_MAX_ATTACHMENTS` | No | `5` | The most screenshots one report may carry |
| `FEEDBACK_MAX_ATTACHMENT_BYTES` | No | `8388608` | The largest screenshot, in bytes (8 MB) |
| `FEEDBACK_MAX_MESSAGE_CHARS` | No | `5000` | The longest message, in characters |
| `FEEDBACK_MAX_DIAGNOSTICS_BYTES` | No | `65536` | The largest block of browser details a report may carry, in bytes (64 KB) |
| `FEEDBACK_RATE_LIMIT_PER_HOUR` | No | `20` | The most reports one visitor may send in an hour |
| `UMAMI_SCRIPT_URL`, `UMAMI_WEBSITE_ID` | No | empty | Counts visitors with an Umami statistics server. Blank counts nothing |
| `CSP_EXTRA_ORIGINS` | No | empty | Extra addresses the site's pages may load scripts from and connect to. Caddy reads this setting. Add the Umami server's address when the two settings above are set |

Google sign-in needs three things: the client ID and client secret in `.env`, this
site's address in the Google account that issued those two values, and a switch on
the site itself.

The Google account's control panel, Google Cloud Console, has to list this site's
address among the addresses allowed to use the two values. That account usually
belongs to whoever runs the organization's email, so find out who that is before you
start. If the site's address is missing there, the **Continue with Google** button
still appears once the other two are in place, and it looks normal. When someone
clicks it, Google refuses, with an error about a "redirect" that means little to
anyone but a web developer. If you cannot finish the Google side, leave the feature
off.

The switch is the setting `allow_google_oauth`, and it is off in a new installation.
The **Continue with Google** button on the sign-in and sign-up pages, and the pages
it leads to, appear only when the switch is on and the two values are set. With
either missing, no button appears, and the pages it would lead to answer "page not
found". Turn the switch on at `/admin/` under Core > Site configs: open the
organization's entry, tick **Allow google oauth** and save. The order of the steps
does not matter. You can tick the box now and add the values next week, or the
other way round, and nothing breaks or opens in between. To turn the feature off
later, untick the box and save.

Turning on Google sign-in can clear an existing OpenH2O password. Once it is on, a
person who already has an OpenH2O account and clicks **Continue with Google** signs
straight in to that account whenever Google confirms the same email address. If that
address has never been confirmed on this site, their OpenH2O password is *cleared*
on the way in, and from then on they sign in with Google. They keep their account
and their records, and nobody is locked out. If the address has been confirmed, the
password stays as it was.

Whether an address is confirmed depends on how the account was made and on
`ACCOUNT_EMAIL_VERIFICATION` (section 11). Accounts an administrator adds on the
Users page and the account `ensure_superuser` creates are confirmed when they are
made. An account made with `createsuperuser` stays unconfirmed whatever the setting
is. So does an account made by a person who signed up on a site whose
`ACCOUNT_EMAIL_VERIFICATION` is `none`. On a site with a mail server, the unset
setting becomes `mandatory`, so people who sign up there confirm their addresses.
Check the setting:

```bash
docker compose exec web python manage.py shell -c "from django.conf import settings; print(settings.ACCOUNT_EMAIL_VERIFICATION)"
```

If any account was made with `createsuperuser`, or the command prints `none` and
some accounts were made by sign-up, tell those people before you turn the switch
on, because nothing on screen warns them. If every account was added on the Users
page or by `ensure_superuser`, the switch changes nothing for anyone's password.

---

## 13. Troubleshooting

**A container will not start:**

```bash
docker compose logs <service-name>
# read the error message it ends on
```

**The database refuses connections:**

```bash
docker compose ps
# db should show "healthy"
# if not: docker compose logs db
```

<!-- defines: private_ip -->
**The log fills with refused requests addressed to a number in place of the site's
address.** On its own, this is no sign of an attack. Every computer on a network has
a numeric *IP address*, and some ranges of them, such as `192.168.…`, work only
inside one building or one provider's private network. A request addressed by number
is refused because the number is not in `ALLOWED_HOSTS`, and Django writes a line
about a disallowed host each time. That is the check doing its job, and nothing
needs fixing. If a tool you run yourself, such as a monitor, addresses the site by
number and should be let in, add its number to `ALLOWED_HOSTS` in `.env` and run
`docker compose up -d`. Do not add a number only to quiet the log.

<!-- defines: geospatial_libraries -->
**"GDAL library not found" or another map-library error:** GDAL, GEOS and PROJ are
open-source libraries that OpenH2O uses for its map work: parcel outlines, well
locations and distances. OpenH2O cannot start without them. The Docker build
installs all three, so inside Docker this error means the build went wrong: read
the first error in the build output. On an installation without Docker, install
them as [docs/INSTALL-WITHOUT-DOCKER.md](docs/INSTALL-WITHOUT-DOCKER.md) describes.

**Port 80 or 443 is already in use:**

```bash
sudo lsof -i :80
# stop the program holding the port, or change the ports in docker-compose.yml
```

**The migrations fail with "relation already exists":**

```bash
docker compose exec web python manage.py migrate --fake-initial
```

`--fake-initial` marks a first migration as applied when its tables already exist,
which happens when a database was restored or built by hand. Back up first.

<!-- defines: collectstatic -->
**The pages load without styling (404 on /static/):** the site's styling, scripts,
fonts and images are its *static files*. The website container gathers them into a
Docker volume at each start with `collectstatic`, and Caddy serves them from that
volume. Gather them again and restart Caddy:

```bash
docker compose exec web python manage.py collectstatic --noinput
docker compose restart caddy
```

**Rebuild from scratch. This deletes the database, so back it up first:**

```bash
docker compose down -v
docker compose up -d --build
docker compose exec web python manage.py seed_data
```

When the website container starts, it runs the migrations. It also creates the
superuser if `.env` holds the two settings from section 7. Otherwise create it with
`docker compose exec web python manage.py createsuperuser`.

**Check the settings for problems:**

```bash
docker compose exec web python manage.py check --deploy
```
