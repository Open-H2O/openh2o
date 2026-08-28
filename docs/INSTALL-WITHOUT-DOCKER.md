<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

<!-- defines: docker -->
# Installing OpenH2O without Docker

**Everywhere else in this project, OpenH2O ships as three *containers*. A
container is a sealed, pre-packed box holding one piece of the program plus
everything it needs to run, so it behaves the same on any computer, and Docker
is the software that builds and runs those boxes.** That is the usual path and
[DEPLOY.md](../DEPLOY.md) covers it.

This document is the other path, end to end: install the same pieces directly
onto the computer, the way you would install any other program, and finish with
a running instance that comes back by itself after a restart.

**This is a supported deployment, not a fallback and not a trial.** OpenH2O is
meant to run the same on an office computer, a rented server and agency
infrastructure. The thing that legitimately changes the configuration is **who
can reach the instance** — this one computer, the office network, or the public
internet — and that question is answered the same way here as anywhere else.

---

## 1. When you are on this path

Two reasons bring people here, and both are good ones.

### The machine cannot run containers, and nothing inside it will fix that

Run this before anything else. It takes five seconds:

```bash
docker run hello-world
```

**If it fails and the message mentions "cgroup" or "bpf", stop trying to fix
Docker.** Some computers you rent are not a whole machine but a slice of one,
walled off using the very technology Docker itself needs. That wall is enforced
one level up, by the machine's own host, outside anything you can see or change
from inside. No Docker setting, reinstall or version gets past it. You have two
real answers: ask whoever provisioned the machine to allow containers, or follow
this document.

This is not hypothetical. It is what happened when we last tested this platform
on a rented machine, and the whole shape of this document comes from it.

### You simply do not want Docker on this computer

Also legitimate, and it needs no justification. An office machine that already
does other work, an agency with a policy about what may be installed, or a
preference for software you can see and manage with the tools you already use —
any of those is a reason, and none of them makes the resulting deployment lesser.

### What this path gives up

Two things, stated plainly so neither is a surprise:

- **You install and update the pieces yourself.** The Docker path bundles the
  database, the geometry libraries and the exact Python packages into one
  build. Here you install them from your distribution, and keeping them current
  is your job rather than a rebuild's.
- **There is no traffic-router in front.** See section 10.

---

## 2. What to install

<!-- defines: sudo -->
Everything in this section changes the computer itself rather than anything
inside OpenH2O, so each command starts with `sudo` — a Linux command meaning
"do the next thing with full administrator power."

**These commands are written for Ubuntu 24.04 LTS**, which is what
[DEPLOY.md](../DEPLOY.md) section 1 names as the tested operating system. Package
names are not portable between Linux distributions: on Debian, Fedora, Alpine or
openSUSE the same software is packaged under different names and, in Debian's
case, at different versions. The *list of things* below is what matters; the
exact spelling is Ubuntu's.

```bash
sudo apt-get update
sudo apt-get install -y \
    git curl \
    postgresql-16 postgresql-16-postgis-3 postgresql-16-postgis-3-scripts \
    gdal-bin \
    python3-venv
```

Here is what each of those is for.

<!-- defines: repository -->
**`git`** copies the program onto this computer. OpenH2O lives in a *repository*
— a folder of the program's files kept on a website called GitHub, with a
complete history of every change ever made to it. Cloning it means copying that
whole folder here so it can be run.

**`curl`** downloads one file in section 6. Most systems already have it.

<!-- defines: postgis -->
**PostgreSQL 16 and PostGIS 3.4** are the database. PostgreSQL is the database
program that stores every record the website shows; PostGIS is an add-on that
teaches it to understand maps, boundaries and points on a map. The
`-scripts` package carries the definitions that switch PostGIS on inside a
database — without it, the command in section 3 fails.

<!-- defines: docker_compose -->
The version numbers are not a preference. Docker Compose — the helper tool,
installed alongside Docker, that starts, stops and rebuilds all three containers
together from one instruction file instead of doing each by hand — reads that
file, `docker-compose.yml`, and its line 3 pins the
database image to `postgis/postgis:16-3.4`, so PostgreSQL 16 with PostGIS 3.4 is
what the platform is built and tested against. Ubuntu 24.04's own package archive
supplies exactly those (16.14 and 3.4.2). This is the strongest single reason
these commands target Ubuntu: Debian 12 supplies PostgreSQL 15 and has no
version 16 at all, so the same commands there would need a third-party archive
added by hand before the first one could run.

<!-- defines: geospatial_libraries -->
**`gdal-bin`** brings in GDAL, GEOS and PROJ — widely-used open-source code
libraries that do the actual geometry and map maths, for parcel boundaries and
well locations. Nobody interacts with them directly; the software simply does not
start without them, and inside Docker they install themselves as part of the
build. Installing `gdal-bin` also installs the two others, because it depends on
them.

<!-- defines: venv -->
**`python3-venv`** provides the machinery for a *virtual environment*: an
isolated copy of Python's package list just for this one project, so its exact
versions of things do not clash with anything else on the computer. This is the
one item on the list that the `Dockerfile` does not mention, because a container
is already an isolated environment and never needed a second one.

OpenH2O needs **Python 3.12 or newer** (`pyproject.toml` line 9; the Docker image
pins 3.12 at `Dockerfile` line 1). Ubuntu 24.04 ships 3.12 as its own `python3`,
so there is nothing extra to install. Check it if you like:

```bash
python3 --version
# Expected: Python 3.12.x or newer
```

> **Where this list comes from.** It is derived from `Dockerfile` lines 4-14 —
> the same recipe the container build follows — with three kinds of entry
> removed: packages the image needs only while *building* itself, packages that
> exist only to manage a container, and `gettext`, which compiles translation
> files this project does not have. A test in this repository fails the build if
> the list here and the list in the `Dockerfile` ever drift apart.

### If the Python install reports a build failure

The step in section 5 installs prebuilt Python packages and, on a normal Ubuntu
machine, compiles nothing. On an unusual processor architecture a package may
have no prebuilt form and try to compile itself. If that happens, install the
compiler and headers and run the step again:

```bash
sudo apt-get install -y gcc python3-dev libgdal-dev libgeos-dev libproj-dev
```

These are not part of the ordinary install. They pull in several hundred further
packages, so they are the remedy for a specific failure rather than something to
install up front.

---

## 3. The database, by hand

The Docker path never asked you to do any of this, because the database image
did it silently on its first start. Natively it is four steps.

<!-- defines: superuser -->
First, a word to avoid a confusion that bites people here. Below you will create
a database *role* with a password. That is not the same thing as OpenH2O's
**superuser** — the one account inside the platform that can do anything, add
other staff accounts, change settings and see everything. The database role is
how the software talks to the database; the superuser is how a person logs in to
the website. Section 7 creates the second one.

**Start the database and set it to come back after a restart:**

```bash
sudo systemctl enable --now postgresql
```

**Choose a strong password and create the role.** Do not reuse the development
default: OpenH2O refuses to start with `openh2o`, `postgres`, `password`,
`changeme` or an empty value, by design (`config/settings/production.py` line
40). Generate one:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Then, substituting that value:

```bash
sudo -u postgres psql -c "CREATE ROLE openh2o WITH LOGIN PASSWORD 'PASTE-THE-PASSWORD-HERE';"
sudo -u postgres createdb -O openh2o openh2o
sudo -u postgres psql -d openh2o -c "CREATE EXTENSION IF NOT EXISTS postgis;"
```

The last line is the one the `-scripts` package exists for. It switches map
awareness on inside this one database.

**Confirm it worked:**

```bash
sudo -u postgres psql -d openh2o -c "SELECT PostGIS_Version();"
# Expected: a version string beginning 3.4
```

PostgreSQL on Ubuntu already listens only on this computer, which is what you
want — nothing else on the network should be able to reach the database
directly.

---

## 4. Copy the program onto the computer

```bash
git clone https://github.com/Open-H2O/openh2o.git
cd openh2o
```

Everything from here runs from inside that folder.

---

## 5. The isolated Python package set

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
```

<!-- defines: pip -->
`pip` is the command that downloads and installs the exact Python add-on
packages this project needs. `requirements.lock` lists them with a cryptographic
fingerprint for each one, and `--require-hashes` makes `pip` refuse any package
whose fingerprint does not match — so this install cannot quietly pull a newer or
tampered-with version. It is the same file and the same flag the container build
uses (`Dockerfile` lines 27-28).

Note the `.venv/bin/` prefix. That is what selects this project's isolated
Python rather than the computer's own, and every command in the rest of this
document keeps it.

---

## 6. Build the site's styling

<!-- defines: collectstatic -->
The site's images, fonts, styling and scripts are *static files*: they have to be
gathered into one folder before they can be served. Two steps do that — one
compiles the styling, and `collectstatic` in section 8 gathers the result.

OpenH2O deliberately has no Node.js build step. The styling is compiled by a
single standalone program you download, and the download has to match this
computer's processor:

```bash
tw_arch="$(uname -m | sed -e 's/x86_64/x64/' -e 's/aarch64/arm64/')"
curl -sfLO "https://github.com/tailwindlabs/tailwindcss/releases/latest/download/tailwindcss-linux-$tw_arch"
mv "tailwindcss-linux-$tw_arch" tailwindcss
chmod +x tailwindcss
./tailwindcss -i static/css/input.css -o static/css/output.css --minify
```

Two details in there are load-bearing, and both are copied from `Dockerfile`
lines 38-41:

- **`uname -m` picks the right file.** The Intel/AMD build downloaded onto an
  Apple-silicon or other ARM machine dies with *illegal instruction*, an error
  that says nothing about processors.
- **The `-f` in `curl -sfLO` matters.** Without it, if the download fails, curl
  saves the web server's error page into the file and reports success. You then
  mark a web page executable and try to run it. With `-f`, curl fails where the
  failure actually happened.

⚠ There is a `scripts/build-css.sh` in this repository. **Do not use it on this
path.** It assumes an Intel/AMD processor and omits the `-f`, so on an ARM
machine it fails in exactly the two ways above. The commands here are the
`Dockerfile`'s.

---

## 7. Settings, and the one gotcha that will bite you

<!-- defines: env_file -->
OpenH2O reads its settings from a `.env` file: a plain text file of `NAME=value`
lines holding the program's settings and passwords. It is the one file that makes
this installation this district's rather than a generic copy, and it is
deliberately kept out of the copy of the program on GitHub, because it contains
secrets.

Start from the shipped example:

```bash
cp .env.example .env
```

<!-- defines: secret_key -->
Generate a `SECRET_KEY` — an internal password the software generates for
itself, used to scramble things like login session cookies. Nobody ever types it;
it just has to exist and stay private:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

<!-- defines: allowed_hosts -->
<!-- defines: localhost -->
<!-- defines: private_ip -->
<!-- defines: tls_https -->
Now edit `.env` and set the following. Three of the names need explaining before
you set them. `ALLOWED_HOSTS` is a safety list: the program refuses to answer
unless the address in the request matches one of the entries, which stops a
stranger tricking it into behaving as a different website. `localhost` and
`127.0.0.1` both mean "this same computer", as opposed to an address anyone else
could type. And an *IP address* is the numeric address every computer on a
network has — ranges like `192.168.x.x` work only inside one building or one
private network and mean nothing on the open internet, which is why an
office-network deployment names one of those.

The last three settings switch off behaviours that assume HTTPS — the
padlock-icon, encrypted version of a web address. There is no encryption to
redirect to on this path, and section 9 explains why leaving them on breaks
logging in.

```bash
SECRET_KEY=<paste-the-generated-key>
DJANGO_SETTINGS_MODULE=config.settings.production
DATABASE_URL=postgis://openh2o:<the-database-password>@localhost:5432/openh2o

# Only this computer:
ALLOWED_HOSTS=localhost,127.0.0.1
# ...or, on the office network, this machine's address on that network:
# ALLOWED_HOSTS=192.168.1.40

CSRF_TRUSTED_ORIGINS=

SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
```

`DATABASE_URL` is the line the Docker path never showed you: Docker Compose
builds that value itself and points it at a hostname called `db`, which is
another container. There is no `db` here, so the address is `localhost`.

### The gotcha: exporting `.env` before you run anything

<!-- defines: environment_variable -->
**Every command in the next two sections has to be preceded by this line**, in
the same terminal:

```bash
set -a && source .env && set +a
```

Here is why, because the failure is otherwise baffling. An *environment
variable* is a named value the operating system hands to a running program; the
`.env` file is a convenience for setting a lot of them at once. But OpenH2O reads
`DJANGO_SETTINGS_MODULE` — the setting that says which configuration to load —
**before** it has read the `.env` file, so a value written only into that file
arrives too late to be used. Docker Compose was quietly exporting these into the
environment for you. Running commands by hand, nothing does.

**The symptom, which is what makes this findable:** the program crashes
immediately complaining about *"production"* settings and a weak database
password, when you asked for neither. Run 004 lost time to this twice. The line
above exports every value in `.env` into the terminal, and the crash stops.

That line is needed for the by-hand commands only. The background service in
section 8 gets the same values a different way, and the unit file shows how.

---

## 8. Start it, and keep it running

### The four steps the container did on every start

These are `entrypoint.sh` lines 25-28, run by hand, in the same order. Export
`.env` first, as above:

```bash
set -a && source .env && set +a

.venv/bin/python manage.py collectstatic --noinput --clear
.venv/bin/python manage.py migrate --noinput
.venv/bin/python manage.py createcachetable
.venv/bin/python manage.py createsuperuser
```

<!-- defines: migrations -->
In order: `collectstatic` gathers the styling and images into one folder;
`migrate` runs the **migrations**, the step where the program builds or updates
the actual tables inside its database to match what this version of the software
expects — routine after every install and update, and skipping it leaves an
empty, unusable database; `createcachetable` creates one more table the platform
uses to remember short-lived things; and `createsuperuser` creates the first
login.

**Where that first password comes from:** nobody supplies it. You invent a strong
one — the same `secrets.token_urlsafe` command above works — and hand it to the
agency through whatever channel they already trust, then record it in a password
manager. The email address you give that account is the login name; if it is not
a mailbox somebody actually reads, the "forgot my password" link will send mail
into nowhere. [DEPLOY.md](../DEPLOY.md) section 7 covers both points and how to
change the address later.

<!-- defines: seed_data -->
Optionally load the demonstration: `seed_data` loads reference lists such as
units and categories, and `seed_merced` loads a full Merced Subbasin dataset so
there is something to look at before the agency's own records arrive. Both are
in [DEPLOY.md](../DEPLOY.md) sections 8 and 9 and run identically here, with the
`.venv/bin/python manage.py` prefix.

### The background service

<!-- defines: wsgi_gunicorn -->
<!-- defines: systemd -->
<!-- defines: port -->
Three things to know before the file below makes sense.

**Gunicorn** is the program that actually listens for browser visits and hands
each one to the site's own code; WSGI is the agreed shape of that handover.
"Workers" and "threads" just mean how many visits it can handle at the same
moment.

**systemd** is Linux's standard way of running a program continuously in the
background and restarting it automatically, including after the computer reboots,
without anyone leaving a window open. A *unit file* is how you describe such a
program to it.

A **port** is a numbered door on the computer that a particular kind of traffic
knocks on. Port 80 is the plain, unencrypted web door — the one a browser uses
when you type no number at all — which is what lets staff reach the site by
typing `http://localhost` with nothing after it.

Write this to `/etc/systemd/system/openh2o.service`, replacing the three
bracketed values with the account that owns the checkout and the checkout's full
path:

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

**Make the folder on the last line first.** The service will not start if it
names a folder that is not there, and the error it gives says nothing about
folders:

```bash
sudo mkdir -p /var/log/openh2o
sudo chown "$USER" /var/log/openh2o
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now openh2o
sudo systemctl status openh2o
```

Five lines in that file are doing real work.

**`EnvironmentFile=` is the section 7 gotcha, solved.** systemd reads the `.env`
file and hands every value to the program as it starts, so the service gets
`DJANGO_SETTINGS_MODULE` in time. **Do not omit this line.** Without it the web
server falls back to its own built-in default, which is the *development*
configuration (`config/wsgi.py` line 10) — and the program starts and serves
pages perfectly while printing the site's internals onto any error page. Nothing
about that failure announces itself.

**`AmbientCapabilities=CAP_NET_BIND_SERVICE` is what lets it hold port 80.**
Ports below 1024 are low-numbered doors, and Linux does not allow an ordinary
program to open one — historically, only the computer's administrator could.
There are two ways round that: run the whole web server as the administrator, or
grant it that one narrow permission and nothing else. This line does the second,
which is the safer of the two by a wide margin: the program that handles
uploaded files never runs with the power to change the computer.

**Name the symptom, because the error does not.** Without that line the service
refuses to start with a permission error that does not obviously mention ports at
all. If `systemctl status openh2o` shows a permission failure, this line is the
first thing to check.

**`--bind 127.0.0.1` is a decision, not a default.** Section 9.

**`--access-logfile` is the record of who visited what.** Every page request
lands in that file as one line: when it arrived, what was asked for, what was
sent back. Without it the site serves visitors and remembers nothing about
having done so, which leaves an ordinary question — *has anyone opened this
page yet?* — with no way to answer it. Section 11 is about that file: where it
is, what a line means, and the one thing it needs from you. It has no size
limit of its own, which is the one thing section 11 asks you to attend to.

**`Restart=on-failure` and `WantedBy=multi-user.target`** are what make it
survive: the first restarts the program if it crashes, the second starts it again
when the computer boots.

Reach the site at `http://localhost`.

### Scheduled data updates

<!-- defines: cron -->
OpenH2O fetches new stream and weather readings and checks its own health on a
repeating clock, using **cron**: Linux's built-in scheduler, the thing that runs a
command every night at 2am with nobody there to press a button.

**The shipped schedule does not work on this path, and you should know that
before you try it.** `crontab.txt` and `make install-cron` install jobs that call
`scripts/run-sync.sh`, which starts a container before doing anything. Write your
own entries instead, in the same shape as the shipped ones but calling this
installation's Python directly. `sudo apt-get install -y cron` first if the
machine has no scheduler at all — a bare server does not always have one. The job
list, and what each one is for, is in `crontab.txt` and in
[DEPLOY.md](../DEPLOY.md) section 11.

---

## 9. Who can reach it

**This is the decision this whole document turns on, and it is made by one word
in one line.** In the unit file above, `--bind 127.0.0.1:80` means *only this
computer can reach the site*. Changing it to `--bind 0.0.0.0:80` means every
machine on the office network can.

Say that out loud to the agency rather than arriving at it by default. It maps
exactly onto [DEPLOY.md](../DEPLOY.md) section 4's three branches:

| Who can reach it | What to bind to | DEPLOY.md section 4 |
|---|---|---|
| Only this computer | `127.0.0.1:80` | `no-public-access` |
| The office network | `0.0.0.0:80`, and `ALLOWED_HOSTS` holds this machine's network address | `no-public-access` |
| The public internet | **not this document** — see below | `own-certificate` or `upstream-terminator` |

**A publicly reachable instance does not belong on this path as written.** The
three `False` settings in section 7 are safe precisely because the traffic never
leaves the building; on the open internet they are not. If the agency needs a
board member or a consultant to reach it from outside, that deployment needs
encryption in front of it and belongs on [DEPLOY.md](../DEPLOY.md) section 4's
Branch B or C.

**Confirm the binding rather than assuming it.** From the computer itself:

```bash
ss -ltnp | grep ':80'
# Expect: 127.0.0.1:80  — not  0.0.0.0:80
```

And from a different machine on the same network, the address should refuse the
connection. Run 004 made this exact change on its own initiative — it was asked
for "this one computer" and reasoned that binding to everything did not match —
and that single decision is what made the rest of its posture defensible. It
appeared in no document anywhere. It does now.

---

## 10. Settings posture, and what you will find if you go looking

**Use `config.settings.production`, on this path as on every other**, with the
three plain-HTTP flips from section 7. `DEBUG` stays off, `ALLOWED_HOSTS` stays
real, the database password stays strong and the closed-signup default stays on.
The security posture follows from who can reach the instance, never from what the
hardware is.

There is a `config.settings.local` in this repository and it is **not** the
answer for an agency's data. It is the configuration for working on the code: it
turns `DEBUG` on, which prints the site's internals — the full error trace, the
settings, the database queries — onto any page that goes wrong. Run 004 chose it,
reasoning that a single office computer with no domain was a local case. Django's
own `manage.py check --deploy` reported five issues against that instance, one of
them naming `DEBUG=True` as a deployment defect in those words, and the run
recorded the warnings as expected and moved on. That is the decision this
document does not repeat.

Check yours the same way, and read what it says:

```bash
set -a && source .env && set +a
.venv/bin/python manage.py check --deploy
```

On this path the HTTPS-related warnings are expected and section 7 is the reason.
**Any warning about `DEBUG` means you are on the wrong configuration.**

---

## 11. No traffic-router on this path, and where the visit record lives

<!-- defines: reverse_proxy -->
The Docker path runs Caddy in front — a middleman program that receives web
traffic and relays it inward to the real program. **This path has no such
middleman.** The web server serves the site directly and WhiteNoise, a piece of
code inside the program itself, hands the styling and images to visitors'
browsers. That is a complete and correct arrangement for an instance nobody
outside can reach.

**The record of who visited what is written here by the web server itself.** The
unit file in section 8 already carries the line that does it, so there is nothing
to turn on:

```
/var/log/openh2o/access.log
```

Read the most recent visits, or watch them arrive as they happen:

```bash
tail -n 50 /var/log/openh2o/access.log
tail -f /var/log/openh2o/access.log
```

**One line per request**, in the order they arrived: the address the request came
from, the date and time, what was asked for, and the three-digit code saying how
it went — `200` served, `302` sent somewhere else, `404` not found, `500` the
program failed. Requests for styling and images are in there too, so one person
opening one page writes several lines.

**This path records one thing the Docker path cannot.** With no middleman in
front, the address at the start of each line is the visiting machine's own. On
the Docker path every line carries the middleman's address instead, because that
is genuinely who handed the request over, and recovering the visitor's own takes
a second step. Here it is simply there.

**The one thing this file needs from you: it has no size limit.** It grows for as
long as the site is up and nothing trims it. A quiet office instance will take
years to become a nuisance and a busy public one will not, so hand it to the
tool the machine already has for this. Write `/etc/logrotate.d/openh2o`:

```
/var/log/openh2o/access.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    copytruncate
}
```

That keeps eight weeks and compresses the older ones. `copytruncate` is the line
that matters: it copies the file aside and empties the original in place, so the
running program keeps writing to the same file it opened at boot and needs no
restart. Check the file you just wrote without waiting a week — this reads it and
reports what it would do, and changes nothing:

```bash
sudo logrotate --debug /etc/logrotate.d/openh2o
```

---

## 12. What is proven here, and what is reasoned

This section exists because a document that quietly presents reasoning as
experience is worse than one that admits the difference.

**Proven.** We have watched this overall shape work, once. On 2026-08-04 an
installation on an Ubuntu machine whose host would not allow containers at all
reached a working site, with data loaded and a login confirmed — the same
database, the same isolated Python package set, the same styling build, the same
background service, the same port-80 permission, the same loopback binding as
above.

**Measured separately.** Four specific claims here were tested on throwaway
machines rather than reasoned out: that the map and geometry libraries load from
`gdal-bin` alone; that `requirements.lock` installs under `--require-hashes` with
no compiler present; that Ubuntu 24.04 supplies PostgreSQL 16 with PostGIS 3.4.2
while Debian 12 supplies neither; and that section 11's rotation file does what
it says — run on a throwaway Ubuntu 24.04 machine on 2026-08-28, it compressed
the old visits into `access.log.1.gz` and left the original in place at zero
bytes, which is the behaviour `copytruncate` is there for.

**Reasoned, not exercised.** The package list above is derived from the
`Dockerfile` line by line rather than watched installing on a fresh machine as
one continuous run, and it is deliberately shorter than the list that
installation used — six packages the container needs only in order to build
itself have been left out. A test in this repository re-checks the list against
the `Dockerfile` on every change, so the two cannot silently drift, but a test is
not the same as a fresh machine.

**Also not covered.** The settings posture in section 10 is not the one that
installation ended on; it is the one this platform's other documents prescribe
everywhere else, applied here. And nothing on this path has been exercised with a
second staff member, a browser session or a real agency's records.

If you are the first to walk this end to end and something here is wrong, that is
worth reporting. It is a genuine gap in what has been tested, not something
checked and got wrong.
