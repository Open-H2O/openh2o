<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

<!-- defines: docker -->
# Installing OpenH2O without Docker

This guide installs OpenH2O directly on a Linux computer, without Docker. The usual
installation runs OpenH2O in three *containers*, which a program called Docker runs.
A container is a package that holds one part of the program and everything that
part needs. [DEPLOY.md](../DEPLOY.md) and the
[AI operator guide](AI-OPERATOR-GUIDE.md) describe that installation. This guide
installs the same parts as ordinary programs on the computer. It ends with a running
site that starts again by itself after the computer restarts.

A site installed this way is a complete OpenH2O installation. As with the Docker
installation, the settings depend on who needs to reach the site. This guide covers
a site that only this computer can reach and a site that everyone on the office
network can reach.

---

## 1. When to take this path

There are two reasons to install without Docker.

### The computer cannot run containers

Check this first:

```bash
docker run hello-world
```

If the command fails with a message about "cgroup" or "bpf", the computer is
probably a rented virtual server whose provider blocks containers. The provider
controls this from outside the server, so no Docker setting, reinstall or version on
the server can change it. Ask the provider to allow containers, or follow this
guide. If the command fails with "command not found", Docker is not installed.
Install it as section 1 of DEPLOY.md describes, or follow this guide.

### The organization prefers not to install Docker

An organization may not want Docker on an office computer that already does other
work. It may have a policy about what software can be installed, or prefer software
it can manage with the tools it already uses.

### What is different on this path

<!-- defines: reverse_proxy --><!-- defines: tls_https -->
On this path you install and update the database, the map libraries and the Python
packages yourself. The Docker build bundles them. This path also has no reverse
proxy. The Docker installation runs Caddy, a *reverse proxy* that receives web
traffic and passes it to the website. Caddy also handles HTTPS, the encrypted
connection a browser marks with a padlock. Because this path has no Caddy, this
guide covers only a site that this computer or the office network can reach.
Section 9 explains the choice.

---

## 2. What to install

<!-- defines: sudo -->
The commands in this section change the computer itself, so each starts with `sudo`,
the Linux command that runs the next command with administrator rights.

The commands are written for Ubuntu 24.04 LTS, the operating system named in
section 1 of [DEPLOY.md](../DEPLOY.md). Other Linux distributions give these
packages different names, and some ship different versions. On another distribution,
install the same software under that distribution's package names.

```bash
sudo apt-get update
sudo apt-get install -y \
    git curl \
    postgresql-16 postgresql-16-postgis-3 postgresql-16-postgis-3-scripts \
    gdal-bin \
    python3-venv
```

Here is what each package is for.

<!-- defines: repository -->
**`git`** copies OpenH2O onto the computer. OpenH2O's code is kept in a *repository*
on GitHub. A repository is a folder of the program's files together with the history
of every change.

**`curl`** downloads one file in section 6. Most computers already have it.

<!-- defines: postgis -->
**PostgreSQL 16 and PostGIS 3.4** are the database. PostgreSQL stores every record
the site shows, and PostGIS is its extension for maps, boundaries and locations. The
`-scripts` package holds the files that switch PostGIS on inside a database, and the
command in section 3 needs them. OpenH2O is built and tested against PostgreSQL 16
with PostGIS 3.4, the versions in the Docker installation's database image. Ubuntu
24.04's own package archive supplies those versions. Debian 12 supplies PostgreSQL
15, so these commands target Ubuntu.

<!-- defines: geospatial_libraries -->
**`gdal-bin`** brings in GDAL, GEOS and PROJ. These open-source libraries do
OpenH2O's map work with parcel outlines, well locations and distances. OpenH2O
cannot start without them.

<!-- defines: venv -->
**`python3-venv`** lets you create a *virtual environment*, a separate set of Python
packages for OpenH2O alone, so its package versions cannot clash with anything else
on the computer.

OpenH2O needs Python 3.12 or newer, the version the Docker image uses. Ubuntu
24.04's own `python3` is 3.12. Check the version:

```bash
python3 --version
# Expected: Python 3.12.x or newer
```

---

## 3. The database

<!-- defines: superuser -->
This section creates a database *role*, the account OpenH2O's code uses to reach the
database. The role is separate from OpenH2O's *superuser*, the first account a
person uses to sign in to the site. Section 8 creates the superuser.

Start the database, and set it to start again whenever the computer starts:

```bash
sudo systemctl enable --now postgresql
```

Generate a strong password for the role, and keep it, because section 7 needs it:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Under the production settings, OpenH2O refuses to start when the database password
is empty or is `openh2o`, `postgres`, `password` or `changeme`. Put the generated
password in place of `PASTE-THE-PASSWORD-HERE`, then create the role, the database
and the PostGIS extension:

```bash
sudo -u postgres psql -c "CREATE ROLE openh2o WITH LOGIN PASSWORD 'PASTE-THE-PASSWORD-HERE';"
sudo -u postgres createdb -O openh2o openh2o
sudo -u postgres psql -d openh2o -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

Confirm that PostGIS is on:

```bash
sudo -u postgres psql -d openh2o -c "SELECT PostGIS_Version();"
# Expected: a version string beginning 3.4
```

On Ubuntu, PostgreSQL accepts connections only from this computer unless you change
its settings. Leave it that way, so that nothing else on the network can reach the
database.

---

## 4. Copy OpenH2O onto the computer

Copy OpenH2O into your home folder:

```bash
cd ~
git clone https://github.com/Open-H2O/openh2o.git
cd openh2o
pwd
```

`pwd` prints the folder's full path, such as `/home/operator/openh2o`. Note it,
because the service file and the job schedule in section 8 need it. Run every
command from here on inside this folder.

---

## 5. The Python packages

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
```

<!-- defines: pip -->
`pip` downloads and installs Python packages. `requirements.lock` lists the exact
packages OpenH2O needs, each with a cryptographic fingerprint. With
`--require-hashes`, `pip` refuses any package whose fingerprint does not match, so
the install cannot pull in a newer or altered version.

Starting a command with `.venv/bin/` runs it with OpenH2O's own Python and packages.
Every Python command in the rest of this guide starts with `.venv/bin/`.

### If the install reports a build failure

The install uses prebuilt Python packages, so on an ordinary Ubuntu computer it
compiles nothing. On a less common processor, a package may have no prebuilt
version, and `pip` then has to compile it. If that happens, install a compiler and
the development headers, the files a compiler needs to build against the map
libraries and Python. Then run the `pip install` command above again:

```bash
sudo apt-get install -y gcc python3-dev libgdal-dev libgeos-dev libproj-dev
```

These packages pull in many others, so install them only if the build fails.

---

## 6. Build the site's styling

<!-- defines: collectstatic -->
The site's styling, scripts, fonts and images are its *static files*. They are
built and gathered into one folder before the site serves them. This section
compiles the styling, and `collectstatic` in section 8 gathers the result.

OpenH2O compiles its styling with Tailwind, a standalone program that you download.
The download has to match the computer's processor:

```bash
tw_arch="$(uname -m | sed -e 's/x86_64/x64/' -e 's/aarch64/arm64/')"
curl -sfLO "https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-$tw_arch"
mv "tailwindcss-linux-$tw_arch" tailwindcss
chmod +x tailwindcss
./tailwindcss -i static/css/input.css -o static/css/output.css --minify
```

Two parts of these commands need explaining:

- `uname -m` chooses the download for the computer's processor. The version built
  for Intel and AMD processors fails on an ARM computer with an error such as
  "Exec format error" or "illegal instruction", which does not mention the
  processor.
- The `-f` in `curl -sfLO` makes curl stop with an error when the download fails.
  Without it, curl saves the server's error page under the program's name and
  reports success.

⚠ Do not use `scripts/build-css.sh` on this path. The script always downloads the
Intel and AMD version and leaves out the `-f`, so it can fail in both of the ways
above.

---

## 7. Settings

<!-- defines: env_file -->
OpenH2O reads its settings from a `.env` file, a plain text file with one
`NAME=value` line for each setting. Each installation has its own `.env` file, which
holds that site's settings and passwords. Git is set to ignore the file, so the
passwords stay out of the published code. Start from the example file, and make the
copy readable only by your own account:

```bash
cp .env.example .env
chmod 600 .env
```

<!-- defines: secret_key -->
Generate a `SECRET_KEY`, which the site uses to sign its sign-in cookies:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

<!-- defines: allowed_hosts --><!-- defines: localhost --><!-- defines: private_ip -->
Then open `.env` in a text editor, such as `nano .env`. For each setting below,
change the line the example file already has, or add the line where the file has
none. OpenH2O is built on Django, a Python web framework, and the settings whose
names begin `DJANGO_` are Django's. `ALLOWED_HOSTS` lists the addresses the site
answers at. `localhost` and `127.0.0.1` are two names for the address a computer
uses for itself, and no other computer can reach that address. Each computer on an
office network also has a numeric *IP address*, such as `192.168.1.40`, that works
only inside that network. `hostname -I` prints this computer's address.
`CSRF_TRUSTED_ORIGINS` lists `https://` addresses and stays empty on a site without
HTTPS. The last three settings are on by default and assume HTTPS. This path has no
HTTPS, so turn them off. Section 9 explains why sign-in fails if they stay on.

```bash
SECRET_KEY=<paste-the-generated-key>
DJANGO_SETTINGS_MODULE=config.settings.production
DATABASE_URL=postgis://openh2o:<the-database-password>@localhost:5432/openh2o
LOG_DIR=/var/log/openh2o

# Only this computer:
ALLOWED_HOSTS=localhost,127.0.0.1
# ...or, on the office network, this computer's address on that network:
# ALLOWED_HOSTS=192.168.1.40

CSRF_TRUSTED_ORIGINS=

SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
```

`DATABASE_URL` tells OpenH2O where the database is and how to sign in to it. Put the
password from section 3 in place of `<the-database-password>`. The database is on
this computer, so its address is `localhost`.

`LOG_DIR` is the folder for OpenH2O's logs. Under the production settings, OpenH2O
creates this folder when it starts, and stops with an error if it cannot. Its
default folder exists only inside the Docker container, and an ordinary account
cannot create a folder under `/var/log`. Create the folder now and make your account
its owner:

```bash
sudo mkdir -p /var/log/openh2o
sudo chown "$USER" /var/log/openh2o
```

<!-- defines: environment_variable -->
Before you run commands by hand, load `.env` into the terminal:

```bash
set -a && source .env && set +a
```

This turns each line of `.env` into an *environment variable*, a named value the
computer hands to every program the terminal starts. `manage.py` reads `.env` by
itself and chooses the production settings when nothing else is set. Other programs
read only the environment. If you start the web server by hand without loading
`.env`, it runs with the development settings, because the file it starts from
defaults to them. Load `.env` once in each new terminal, so every command runs on
the same settings.

---

## 8. Start OpenH2O and keep it running

### The first account

`ensure_superuser` creates the first account from the `DJANGO_SUPERUSER_EMAIL` and
`DJANGO_SUPERUSER_PASSWORD` settings in `.env`. When those settings are missing, it
does nothing. Add both to `.env` now. Use an email address that someone reads,
because password-reset emails go to it once the site has email settings (section 11
of DEPLOY.md, under Email / Password Reset). Generate the password with the same
`secrets.token_urlsafe` command, and store it in a password manager. Give the
password to the organization through a channel the organization already trusts.

### The four steps

Load `.env`, then run these four steps in order. The Docker container runs the same
steps each time it starts.

```bash
set -a && source .env && set +a

.venv/bin/python manage.py collectstatic --noinput --clear
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py createcachetable
.venv/bin/python manage.py ensure_superuser
```

<!-- defines: migrations -->
`collectstatic` gathers the static files into one folder. `migrate` runs the
*migrations*, which create or update the database tables to match this version of
OpenH2O. Run it after every install and every update. `createcachetable` creates
one more table, where OpenH2O keeps short-lived values. `ensure_superuser` creates
the first account.

Once the account exists, remove the `DJANGO_SUPERUSER_PASSWORD` line from `.env`, so
the password is not left in the file. If `ensure_superuser` runs again with the line
in place, it sets the account's password back to the one in `.env`. You can also
create the account with `.venv/bin/python manage.py createsuperuser`, which asks for
each value. Section 7 of [DEPLOY.md](../DEPLOY.md) covers changing the account's
email address later.

<!-- defines: seed_data -->
Then load the reference lists every site needs, such as units and categories:

```bash
.venv/bin/python manage.py seed_data
```

To *seed* a database is to load a starting set of records into it. `seed_merced`
loads the demonstration data: published records from a real groundwater basin,
together with invented sample data. Phase 3 of the
[AI operator guide](AI-OPERATOR-GUIDE.md) describes the demonstration data,
including how its records stay on the site beside the organization's own records.
On this path, start each of Phase 3's commands with `.venv/bin/python manage.py`.

### The background service

<!-- defines: wsgi_gunicorn --><!-- defines: systemd --><!-- defines: port -->
The service file below uses a few terms.

**Gunicorn** is the web server. It receives each request from a browser and hands
it to OpenH2O's code. WSGI is the standard way a Python web server makes that
handover. Its workers and threads set how many requests it can handle at once.

**systemd** is the part of Linux that keeps programs running in the background and
starts them again after a crash or a restart of the computer. A *unit file*
describes one such program to systemd.

A **port** is a numbered entry point on a computer for one kind of network traffic.
Port 80 carries plain web traffic. A browser uses port 80 when the address has no
port number in it, so the site's address needs none, as in `http://localhost`.

Create the file `/etc/systemd/system/openh2o.service` with administrator rights,
for example with `sudo nano /etc/systemd/system/openh2o.service`, and write the
lines below into it. Put your account's name in place of `<the operator's account>`.
Put the full path from section 4 in place of `<the checkout>`.

```ini
[Unit]
Description=OpenH2O
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=simple
User=<the operator's account>
WorkingDirectory=<the checkout>
EnvironmentFile=<the checkout>/.env
ExecStart=<the checkout>/.venv/bin/gunicorn config.wsgi:application \
    --bind 127.0.0.1:80 --workers 3 --threads 4 \
    --worker-class gthread --timeout 60 \
    --access-logfile /var/log/openh2o/access.log
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

The service writes its access log to the folder from section 7, so that folder has
to exist before the service starts. Then start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openh2o
sudo systemctl status openh2o
```

Six lines in the file need explaining.

- **`EnvironmentFile=`** hands every value in `.env` to the web server as it starts,
  including `DJANGO_SETTINGS_MODULE`. Keep this line. Without it, the web server runs
  with the development settings, which show the site's internals on any error page.
  The pages still load, so nothing warns you of the mistake.
- **`AmbientCapabilities=CAP_NET_BIND_SERVICE`** lets the web server use port 80.
  Linux lets only the administrator open a port below 1024. This line grants the web
  server that one permission, so it can run under your account without
  administrator rights. Without the line, the service fails to start with a
  permission error that does not mention ports. If `systemctl status openh2o` shows
  a permission failure, check this line first.
- **`--bind 127.0.0.1:80`** decides who can reach the site. Section 9 explains the
  choice.
- **`--access-logfile`** records each request in `/var/log/openh2o/access.log`.
  Section 10 explains that file and how to keep its size in check.
- **`Restart=on-failure`** starts the web server again after a crash.
- **`WantedBy=multi-user.target`** starts it when the computer starts.

Open the site at `http://localhost`. On a server with no screen, check it with
`curl -I http://localhost`, which should print a status line with 200 or 302.

<!-- defines: cron -->
### Scheduled jobs

OpenH2O uses cron, the scheduler built into Linux, to fetch new stream and weather
readings, run its nightly calculation and check its own health. The schedule that
comes with OpenH2O, `crontab.txt`, runs every job through Docker, so it does not
work on this path. If the computer has no cron, install it with
`sudo apt-get install -y cron`. Then open your account's schedule with `crontab -e`
and add these lines. Put the full path from section 4 in place of
`/home/operator/openh2o`:

```
OPENH2O_DIR=/home/operator/openh2o
LOGS=/var/log/openh2o
0 * * * *   cd $OPENH2O_DIR && for s in cdec usgs; do .venv/bin/python manage.py sync_source $s; done >> $LOGS/sync.log 2>&1
0 2 * * *   cd $OPENH2O_DIR && for s in dwr_wdl dwr_sgma noaa; do .venv/bin/python manage.py sync_source $s; done >> $LOGS/sync.log 2>&1
30 3 * * *  cd $OPENH2O_DIR && .venv/bin/python manage.py run_accounting --open-periods --trigger schedule >> $LOGS/calculation.log 2>&1
0 */6 * * * cd $OPENH2O_DIR && .venv/bin/python manage.py run_health_checks >> $LOGS/health.log 2>&1
0 3 1 * *   cd $OPENH2O_DIR && .venv/bin/python manage.py prune_old_data --confirm >> $LOGS/prune.log 2>&1
```

These are the jobs in `crontab.txt`, at the same times. `manage.py` reads `.env` by
itself, so the jobs need no other settings. The last job deletes sync logs,
health-check results and published staging records older than a year. The jobs
sync a data source only after that source's stations are turned on. Phase 4 of the
[AI operator guide](AI-OPERATOR-GUIDE.md) describes turning stations on and explains
each job.

---

## 9. Who can reach it

Two settings decide who can reach the site: `--bind` in the unit file and
`ALLOWED_HOSTS` in `.env`. With `--bind 127.0.0.1:80`, only this computer can reach
the site. With `--bind 0.0.0.0:80`, every computer that can reach this computer can
reach the site. Ask the organization which choice it wants, and explain that the
office-network choice opens the site to everyone on that network.

| Who can reach it | `--bind` | `ALLOWED_HOSTS` |
|---|---|---|
| Only this computer | `127.0.0.1:80` | `localhost,127.0.0.1` |
| The office network | `0.0.0.0:80` | this computer's address on the network, such as `192.168.1.40` |
| People outside the office | This guide does not cover it. | |

⚠ On a rented server, keep `--bind 127.0.0.1:80`. A rented server is on the public
internet, so `0.0.0.0:80` puts the site there over plain HTTP, and passwords then
travel unencrypted. To use the site from your own computer, open an SSH tunnel to
the server with `ssh -L 8080:localhost:80` followed by your sign-in for the server,
then open `http://localhost:8080` on your own computer.

Turning off the three settings at the end of the `.env` block in section 7 is safe
only while the traffic stays on this computer or inside the office network. If those
settings stay on, every sign-in over plain `http://` fails with a 403 error, because
a browser sends a cookie marked secure only over HTTPS. A site that people outside
the office need must have HTTPS. On a computer that can run Docker, use the Docker
installation and the HTTPS setups in section 4 of [DEPLOY.md](../DEPLOY.md). This
guide does not yet give the steps for HTTPS without Docker.

After a change to the unit file, run `sudo systemctl daemon-reload` and
`sudo systemctl restart openh2o`. Then confirm the binding from this computer:

```bash
ss -ltnp | grep ':80'
# Expect 127.0.0.1:80 for this computer only, or 0.0.0.0:80 for the office network
```

For a site on this computer only, also try to open it from a second computer on the
same network, and confirm that the connection is refused.

### The production settings

Use `config.settings.production` on this path, with the three settings from
section 7 turned off. The production settings keep `DEBUG` off and sign-up closed,
so people get accounts only from an administrator. They also require a strong
database password and the site's address in `ALLOWED_HOSTS`. The development
settings, `config.settings.local`, are for work on the code. They turn `DEBUG` on,
which shows the site's error traces, settings and database queries on any page that
hits an error. Check the settings:

```bash
set -a && source .env && set +a
.venv/bin/python manage.py check --deploy
```

On this path the warnings about HTTPS are expected, because you turned those
settings off in section 7. A warning about `DEBUG` means the site is running the
development settings.

---

## 10. The access log

The `--access-logfile` line in the unit file makes the web server write one line to
`/var/log/openh2o/access.log` for each request. To read the most recent requests, or
to watch them arrive:

```bash
tail -n 50 /var/log/openh2o/access.log
tail -f /var/log/openh2o/access.log
```

Each line gives the address the request came from, the date and time, the page or
file asked for, and a three-digit status code: `200` for served, `302` for sent to
another page, `404` for not found and `500` for an error in OpenH2O. Requests for
styling and images are recorded too, so one person opening one page adds several
lines. With no proxy in front of the web server, the address at the start of each
line is the visitor's own.

The access log and the scheduled jobs' logs have no size limit and grow for as long
as the site runs. Use logrotate, the program Ubuntu already uses for its own log
files, to keep them small. Create `/etc/logrotate.d/openh2o` with administrator
rights, as for the unit file, and write this into it:

```
/var/log/openh2o/access.log /var/log/openh2o/sync.log /var/log/openh2o/calculation.log /var/log/openh2o/health.log /var/log/openh2o/prune.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    copytruncate
}
```

This keeps eight weeks of records and compresses the older ones. `copytruncate`
copies each file aside and then empties the original, so the web server keeps
writing to the file it opened and needs no restart. Check the file now, without
waiting a week. This command reports what logrotate would do and changes nothing:

```bash
sudo logrotate --debug /etc/logrotate.d/openh2o
```

OpenH2O limits the size of its error log, `openh2o.log`, which is in the same
folder.

---

## 11. Upgrades and backups

To upgrade OpenH2O, run these commands in the `openh2o` folder:

```bash
set -a && source .env && set +a
git pull
.venv/bin/pip install --require-hashes -r requirements.lock
./tailwindcss -i static/css/input.css -o static/css/output.css --minify
.venv/bin/python manage.py collectstatic --noinput --clear
.venv/bin/python manage.py migrate --noinput
sudo systemctl restart openh2o
```

To back up the database to a file:

```bash
sudo -u postgres pg_dump openh2o > openh2o-backup.sql
```

Back up on a regular schedule, and keep the backups on another computer or another
disk.

To restore a backup, stop the site and delete the current database. Then create an
empty database with the PostGIS extension, with the `createdb` and
`CREATE EXTENSION` commands from section 3, load the file into it and start the site
again:

```bash
sudo systemctl stop openh2o
sudo -u postgres dropdb openh2o
sudo -u postgres createdb -O openh2o openh2o
sudo -u postgres psql -d openh2o -c "CREATE EXTENSION IF NOT EXISTS postgis;"
sudo -u postgres psql -d openh2o < openh2o-backup.sql
sudo systemctl start openh2o
```

---

## 12. What has been tested

Nobody has yet followed this guide from start to finish on a fresh computer with the
production settings and `LOG_DIR` in place. A test in this repository checks that
the guide names the same map libraries and the same Python, PostgreSQL and PostGIS
versions as the Docker build. If a step here fails, please report it at
github.com/Open-H2O/openh2o/issues.
