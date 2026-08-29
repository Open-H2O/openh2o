<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Deploy: Open Water Accounting Platform

Complete deployment guide. Every command is copy-pasteable. Written for
an AI or operator deploying on a fresh VPS with zero prior knowledge.

---

## 1. Server Requirements

<!-- defines: docker -->
<!-- defines: docker_compose -->
<!-- defines: sudo -->
Three of the names in the table below are pieces an operator actually meets, so
they are worth a sentence each first. OpenH2O normally ships as three
*containers* — a container is a sealed, pre-packed box holding one piece of the
program plus everything it needs to run, so it behaves the same on any computer
— and **Docker** is the software that builds and runs those boxes. This
platform's three hold the web pages, the database, and the piece that manages
the address and the encryption. **Docker Compose** is a helper tool, installed
alongside Docker, that starts, stops and rebuilds all three boxes together from
one instruction file (`docker-compose.yml`) instead of handling each by hand;
every `docker compose …` line in this guide is that tool. And **`sudo`** in
front of a command is Linux for "do the next thing with full administrator
power" — needed for anything that changes the server itself, such as installing
software, as opposed to changes that stay inside OpenH2O.

| Requirement | Minimum |
|-------------|---------|
| OS | Ubuntu 22.04+ (tested on 24.04) |
| RAM | 2 GB (4 GB recommended) |
| Disk | 10 GB free |
| Docker Engine | 24+ |
| Docker Compose | v2 |
| Git | any recent version |
| make | any recent version (`sudo apt-get install -y make`) |
| cron | any recent version (`sudo apt-get install -y cron`). <!-- defines: cron --> This is Linux's built-in scheduler: the thing that runs a command on a repeating clock — "every night at 2am" — with nobody there to press a button. Section 11 installs jobs into it to fetch new stream and weather readings and to check the platform's own health. A bare server does not always have it, and `make install-cron` has nothing to install into if it is missing |
| Domain | Only if the instance must be reachable from outside its own machine or network. A single-computer or office-network deployment needs none — see [docs/AI-OPERATOR-GUIDE.md](docs/AI-OPERATOR-GUIDE.md) Phase 2 |

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
```

**That second command does not take effect in the terminal you typed it in.**
Linux decides which groups you belong to when a login session begins, so the
session you are already sitting in still holds the old list. The very next
`docker` command will fail with a flat `permission denied` that says nothing
about groups at all — it reads exactly like a broken install or a mistyped
password, and it is neither. Log out, log back in, and it works. If logging out
is awkward, put `sudo` in front of each `docker` command until you next do.

Then confirm Docker can actually run something:

```bash
docker run hello-world
```

**If that fails and the error mentions "cgroup" or "bpf", stop here.** Some
machines you rent are not a whole computer but a slice of one, walled off using
the very technology Docker itself needs, and that wall is enforced by the
machine's own host — one level up, outside anything you can see or change from
inside. No Docker setting, reinstall or version will get past it. There are two
real answers, and neither of them is more Docker: ask whoever provisioned the
machine to allow containers, or install the platform without Docker at all —
[docs/INSTALL-WITHOUT-DOCKER.md](docs/INSTALL-WITHOUT-DOCKER.md) is that path,
written out end to end.
The test itself is quick — the first run also downloads a small image — and it
is worth doing before anything else, because the alternative is hours spent on
Docker fixes that cannot work.

**That path is also there if you simply do not want Docker on this machine.** It
is not only the answer to a failure; an agency with a policy about what may be
installed, or a preference for managing the pieces directly, can start there
instead.

---

<!-- defines: repository -->

## 2. Clone the Repository

Copy the whole program onto this server. A *repository* is a folder holding all
of the program's files, kept on a website called GitHub with a complete history
of every change ever made to it; *cloning* it means copying that folder down to
this machine so it can be built and run here.

```bash
git clone https://github.com/Open-H2O/openh2o.git
cd openh2o
```

---

## 3. Environment Configuration

<!-- defines: env_file -->
This section fills in one file. `.env` is a plain text file of NAME=value lines
holding this deployment's settings and passwords — the one file that makes this
installation *this district's* rather than a generic copy, and one deliberately
kept out of the published copy of the program precisely because it holds
secrets. The repository ships an example of it to start from:

```bash
cp .env.example .env
```

<!-- defines: secret_key -->
Generate a `SECRET_KEY`. That is an internal password the software makes up for
itself and uses to scramble things like login session cookies; nobody ever types
it, it simply has to exist and stay private:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

Edit `.env` and set these values at minimum:

```bash
SECRET_KEY=<paste-generated-key-here>
POSTGRES_PASSWORD=<choose-a-strong-password>
DJANGO_SETTINGS_MODULE=config.settings.production
```

<!-- defines: allowed_hosts -->
The last two settings — `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS` — are two
safety lists. The program refuses to answer unless the web address in the
request matches one of them, which is what stops a stranger tricking it into
behaving as a different website; they have to carry this district's real address
exactly, or the site turns every visitor away. (`CSRF` is the attack that second
list exists to stop — somebody else's page quietly submitting a form to yours in
a logged-in visitor's name.) What you put in them depends on
**who can reach this instance**. That is the same question §4 and
[docs/AI-OPERATOR-GUIDE.md](docs/AI-OPERATOR-GUIDE.md) Phase 2 branch on, and
Phase 2 step 2 carries the authoritative table. The two shapes are:

**Reachable from the public internet, at a domain:**

```bash
ALLOWED_HOSTS=your-domain.com,www.your-domain.com
CSRF_TRUSTED_ORIGINS=https://your-domain.com,https://www.your-domain.com
```

<!-- defines: localhost -->
**Only this computer, or the office network.** `localhost` and `127.0.0.1` both
mean "this same computer", as opposed to an address anyone else could type — so
an instance nobody outside reaches names those, or names the machine's address
on the office network. There is no public domain, so `CSRF_TRUSTED_ORIGINS`
stays empty:

```bash
# only this computer
ALLOWED_HOSTS=localhost,127.0.0.1
CSRF_TRUSTED_ORIGINS=

# or, on the office network, the machine's address on that network
ALLOWED_HOSTS=192.168.1.40
CSRF_TRUSTED_ORIGINS=
```

Neither shape is a lesser deployment. `ALLOWED_HOSTS` is a safety list the
program checks against the address in each request; it simply has to hold the
address people will actually type, whatever that is.

See `.env.example` for all available variables with documentation.

---

<!-- defines: reverse_proxy -->
<!-- defines: tls_https -->

## 4. Caddy / HTTPS Configuration

Two pieces sit between a visitor and this platform, and this section is about
both of them.

The first is a **traffic router** — a middleman program that receives everything
arriving from outside and relays it inward to the real program. The name for
that arrangement is a *reverse proxy*, and the one shipped here is a program
called **Caddy**, configured by the file named `Caddyfile`. A district that
already runs a proxy of its own ends up with two in a row: theirs, outside your
control, in front of this machine, and Caddy inside Docker in front of OpenH2O.
That is a normal arrangement, not a fault to fix.

The second is the **lock on the connection**. *HTTPS* is the padlock-icon,
encrypted version of a web address; *TLS* is the encryption technology behind
that padlock; and a *certificate* is the file that proves the address really is
itself. A connection has to be unlocked somewhere before any program can read
what it carries, and *where* that unlocking happens is what the rest of this
section turns on.

So: what you do with the `Caddyfile` follows from exactly one question, **who
can reach this instance?** Not how big the machine is, not whether it is a
rented server or a computer in the office — only who can reach it.

| Who can reach this instance | What to do with the `Caddyfile` | Follow |
|---|---|---|
| Only this computer, or the office network | Leave it exactly as shipped | **Branch A** |
| The public internet, and this server obtains its own certificate | Replace `:80` with your bare domain | **Branch B** |
| The public internet, but something in front already handles the encryption | Leave `:80` as shipped, or write `http://your-domain.com` | **Branch C** |

This is the same question [docs/AI-OPERATOR-GUIDE.md](docs/AI-OPERATOR-GUIDE.md)
Phase 2 branches on. If the two ever seem to disagree, Phase 2 is the authority
for the `.env` settings and this section is the authority for the `Caddyfile`.

⚠ **The `Caddyfile` examples in the branches below are cut down to the lines
that differ between branches.** The shipped file carries more than they show — a
security header, tuned retry timings for the moment after a restart, and a
branded page for when the site is down — each with a comment saying why. Edit
the shipped file rather than replacing it with one of these blocks, or you will
quietly drop all three.

<!-- branch: no-public-access -->

### Branch A — Only this computer, or the office network

Leave the `Caddyfile` exactly as it ships. There is no domain to name and no
certificate to obtain, so there is nothing in this file to change. You will reach
the site at `http://localhost` or at the machine's address on the office network.

Then set these three in `.env`:

```bash
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
```

Without them, **every login returns 403 while unauthenticated pages render
perfectly** — which makes the site look like it works right up until someone
tries to log in. The reason is that a browser never sends a `Secure` cookie over
plain `http://`, and production settings mark the login cookies `Secure` by
default. This is a supported, documented posture, not a workaround;
[docs/AI-OPERATOR-GUIDE.md](docs/AI-OPERATOR-GUIDE.md) Phase 2 step 3 carries the
full table. You still keep `DEBUG=False`, a real `ALLOWED_HOSTS`, a database
password that is not one of the rejected defaults, and the closed-signup default.

⚠ **Nothing above narrows who can reach the machine, and this branch is the one
where that matters.** <!-- defines: port --> A *port* is a numbered door on the
computer that one particular kind of traffic knocks on: port 80 is the plain,
unencrypted web door — the one a browser uses when nobody types a number at all
— and port 443 is the encrypted one. As shipped, `docker-compose.yml` opens both
of those doors on every network the machine is attached to, so the site is
reachable by anything that can reach the machine.

If the answer was *"only this computer,"* change the two lines in
`docker-compose.yml` that open them, from `80:80` and `443:443` to
`127.0.0.1:80:80` and `127.0.0.1:443:443`, then confirm from a second machine
that the address refuses the connection. If the answer was *"the office
network,"* leave them and rely on the office network itself — but say so out
loud to the agency rather than letting it be an accident.

<!-- branch: own-certificate -->

### Branch B — Public internet, and this server obtains its own certificate

Replace `:80` with your domain written as a **bare address — no `http://` and no
`https://` in front of it**. The bare form is exactly what tells Caddy to obtain
a certificate for that name automatically, at no cost. Caddy tries two issuers
by default — Let's Encrypt first, then ZeroSSL if that fails — so a certificate
arriving from the second name is normal, not a sign anything went wrong.

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

**Two things should already be true before you start the containers.** The first
is a hard requirement; the second is strongly advised:

1. **The DNS A record for that name must already point at this server's public <!-- defines: dns -->
   IP.** *DNS* is the internet's phone book: it turns a web address into the
   numeric address of one specific computer, and an *A record* is one entry in
   that book, so "pointing the domain at this machine" means editing that one
   entry wherever the domain was bought. Certificates are issued to a name only
   after the issuer confirms the name really does lead to this machine, so the
   phone-book entry has to be in place first, not afterwards.
2. **Open both port 80 and port 443 to the internet** — the two doors Branch A
   describes above. Port 443 is where the finished site is served. The issuer's
   check can arrive at either door: Caddy enables both check methods by default
   and picks between them, so a certificate can still be issued with port 80
   closed. Opening both removes a variable rather than being strictly required.
   Note that closing 80 also means anyone who types the address without
   `https://` reaches nothing.

Keep `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE` and `CSRF_COOKIE_SECURE`
switched **on** for this branch — they are on by default and they are correct
here.

> **Say plainly what this branch is: reasoned, not proven.** This project has
> never once exercised it. Every machine we own is either behind a Cloudflare
> Tunnel — which terminates the encryption itself, so Caddy never runs its own
> certificate request — or is a rented server whose ports 80 and 443 are already
> taken by something else. The instructions above follow Caddy's own published
> documentation; they have not been watched working end to end. If you are the
> first to run this branch and it
> misbehaves, that is worth reporting: it is a genuine gap in what has been
> tested, not something we checked and got wrong.

<!-- branch: upstream-terminator -->

### Branch C — Public internet, but something in front already handles the encryption

This is the branch for a Cloudflare Tunnel, an agency's existing proxy, or a load
balancer — anything that receives the encrypted traffic, unwraps it, and forwards
plain traffic on to this server. openh2o.com itself runs this way.

**Do not put a bare domain in the `Caddyfile` on this branch.** Either leave `:80`
exactly as shipped, or, if the name genuinely has to appear, write it with the
`http://` prefix:

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

The `http://` prefix is the whole mechanism: it is what tells Caddy to serve that
name as-is, over plain HTTP, and order no certificate. (Caddy's documentation,
Caddyfile → Concepts → Addresses.)

**The global `auto_https off` option is not a substitute, and it is worth
knowing why.** It does switch the certificate automation off — that much is
real — but it is a blunt instrument here. It is global, so it also turns off the
plain-to-encrypted redirect for *every* site in the file, and by Caddy's own
documentation it does not change the protocol a site is served on: an address
written as a bare domain still gets served over HTTPS, now with no certificate
behind it. Changing the address is what actually changes what is served, which
is why the `http://` prefix is the instruction here.

<!-- defines: x_forwarded_proto -->
Keep the `header_up X-Forwarded-Proto https` line. When the thing in front strips
the encryption, it can attach a note saying "this was encrypted when the visitor
sent it"; `X-Forwarded-Proto` is that note, and Django is configured to trust it
rather than insisting on seeing encryption that will never reach it.

**The trap, in one sentence:** a bare domain here makes Caddy order a certificate
through a check that has to reach this server from outside, while Django is
simultaneously redirecting every plain request to HTTPS — and the request loops
until it dies. The shipped `Caddyfile`'s own opening comment describes the
second half of that, the redirect loop, and why the `X-Forwarded-Proto` line
below prevents it. It is worth reading before you edit the file.

---

## 5. Build and Start

```bash
docker compose up -d --build
```

The three containers start in sequence, not together: the database has to report
healthy before the web container starts, and the web container then does its own
first-boot work — gathering up the site's styling and images, and building its
database tables — before it reports healthy in turn and Caddy starts. Give it a
minute or two on a first build, and check with:

```bash
docker compose ps
```

Expected output once all three are up:

```
NAME              IMAGE                    STATUS                    PORTS
openh2o-caddy-1   caddy:2-alpine          Up                        0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
openh2o-db-1      postgis/postgis:16-3.4  Up (healthy)              5432/tcp
openh2o-web-1     openh2o-web             Up (healthy)              8000/tcp
```

Only `db` and `web` report `(healthy)` — the Caddy image defines no health check
of its own, so a bare `Up` is the correct and only reading for that row.

---

<!-- defines: migrations -->

## 6. Run Migrations

*Migrations* are the step where the program builds or updates the actual tables
inside its database to match what this version of the software expects. Routine
and expected after every install and every update; skip it and you are left with
an empty, unusable database.

```bash
docker compose exec web python manage.py migrate
```

Expected: a list of applied migrations ending with `OK`.

---

<!-- defines: superuser -->

## 7. Create Superuser

A *superuser* is the one account inside OpenH2O that can do anything: add other
staff accounts, change settings, see everything. It is separate from and
unrelated to any login for the server itself, and it has to be created by hand
before anyone can sign in at all — there is no "first visitor becomes the
administrator" magic.

```bash
docker compose exec web python manage.py createsuperuser
```

Follow the prompts for username, email, and password.

**Nobody hands you this password.** An agency's paperwork supplies the things
only the agency can know — their web address, their data keys — and not this
one, because this account does not exist until you create it here. So invent it
properly: not blank, not reused from somewhere else, not something memorable.
Generate it the same way §3 generates `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(18))"
```

Then get it to the agency through a channel they already trust — the password
manager they use, or handed over in person. Not a chat message, not left sitting
in a file on the server. (§3's database password is under the same rule for the
same reason: the platform refuses to start in its secure mode if that one is
left empty or set to any of four well-known defaults, and that refusal is
deliberate.)

**The email address you type at that prompt is probably not a mailbox anyone
reads.** If you invent one — `admin@` the agency's own address is the usual
guess — then the **"Forgot password?"** link on the login page sends its reset
to an inbox that does not exist, and whoever is locked out simply never receives
anything. Put a real, monitored address on the account before the agency starts
depending on this deployment: **Django admin → Core → Users → (the account) →
Personal info → Email address**. Then check §11's *Email / Password Reset* section for whether
outgoing email is configured at all — until it is, that flow sends nothing no
matter whose address is on the account.

---

<!-- defines: seed_data -->

## 8. Seed Reference Data

*Seeding* means loading a starting set of data into a database that is otherwise
empty. It covers two different things here: the small reference lists such as
units and categories that every deployment needs, which is this section, and a
whole demonstration dataset so there is something to look at before the
district's own records arrive, which is §9.

These commands load required lookup tables (roles, the observed-property
crosswalk, water types, well types, water right types, data source
definitions, and report templates):

```bash
docker compose exec web python manage.py seed_data
```

This runs the seed commands in the order below on a deployment that has every
module switched on. The first two always run; the rest belong to modules a
deployment can switch off, and one whose module is off is skipped and said so in
the output.

- `seed_roles` (admin, manager, viewer)
- `seed_observed_properties` (the standards crosswalk: every adapter's native
  parameter code mapped to a canonical concept, which is what makes
  `check_conformance` able to check anything)
- `seed_water_types` (Groundwater, Surface Water, Recycled Water, etc.)
- `seed_well_types` (Production, Monitoring, Injection, Observation)
- `seed_data_sources` (CDEC, USGS, OpenET, CIMIS, CNRFC, DWR, NOAA)
- `seed_drinking` (federal MCL reference limits for the drinking-water module)
- `seed_water_right_types` (Appropriative, Pre-1914, Riparian, etc.)
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
section 11) and run the ET sync. Without a key the demo's face-value figures —
water rights, deliveries, parcels, ledger activity — are all seeded and
internally coherent, but **consumptive use is computed from satellite ET and has
no fallback**, so those figures stay empty until a key is supplied.

⚠ **`run_calculations` needs one more thing that no seed command runs for you.**
It will not start at all until an active calculation method exists, and the
command that creates one — `seed_calculation_plan` — is run by neither
`seed_data` nor `seed_merced`. Without it the command stops with an error naming
exactly that. `seed_merced` prints a list of what is still missing when it
finishes, and this is on it; that list is the authority, not this paragraph.
With the method in place but no ET data behind it, `run_calculations` then
reports every parcel as skipped ("no ET data").

<!-- defines: idempotent -->
Each sub-step is *idempotent* — running it five times ends up the same as
running it once, because it notices what is already done and skips it rather
than duplicating or breaking anything — so re-running after an interruption is
safe, with one deliberate
exception. The operations step deletes and regenerates parcel and well geometry,
so on a production instance (`DEBUG=False`) it refuses to run a *second* time
over demo rows that already exist, rather than silently destroying hand-adjusted
boundaries. A first-time seed on an empty database is unaffected and needs no
flag. To rebuild the demo on purpose:

```bash
docker compose exec web python manage.py seed_merced --allow-prod-clobber
```

**The bundled station catalog.** The seed above finds the basin's monitoring
stations by calling the agencies that publish them, and it creates every one of
them switched **off** — so a freshly seeded demonstration reports "0 of 0
stations reporting" until somebody turns them on, and it needs a working
connection to those agencies to find them at all. The demonstration's own list
of stations also ships with the platform — 335 of them, 42 switched on, and 50
of the 335 (all 42 of the active ones, plus 8 others) carrying the real date
they last published a reading — and one command loads it:

```bash
docker compose exec web python manage.py load_station_fixture
```

That is the set openh2o.com shows. It calls nobody, so it works on a machine
with no way out to the internet, and running it twice changes nothing. Run it
after the reference data in §8, which is what creates the list of upstream
services it names; it stops with a plain message rather than half-writing if
that list is missing. `seed_merced` deliberately does not run it, and that is
the reason this step exists as a step: a real agency standing this platform up
against its own basin wants its **own** stations discovered, not Merced's.

**Once the agency's own records are loaded** — by this route, by the setup
wizard (§11), or through [docs/DATA-IMPORT.md](docs/DATA-IMPORT.md) — run the
platform's two self-checks over the new data:

```bash
docker compose exec web python manage.py check_conformance
docker compose exec web python manage.py run_health_checks
```

The first reports whether every kind of measurement now in the database is
mapped to a known concept with a real unit — a reading with no unit behind it is
a number nobody can file. The second reports on the deployment underneath it:
database, disk, certificate, migrations, and whether the live data feeds are
current. Both are covered in §11; this is simply the moment to run them, because
new data is what changes their answers.

---

## 10. Verify Deployment

**Do the last two checks at the address the agency will actually use**, not only
at `http://localhost`. A site that answers on the machine itself and nowhere else
looks identical to a working one from here. Per §4's branches, that address is:
`http://localhost` or the machine's office-network address for **Branch A**, and
`https://your-domain.com` for **Branch B** and **Branch C**.

Run these checks in order:

**HTTP response through Caddy:**

```bash
curl -s -o /dev/null -w '%{http_code}' http://localhost
# Expected: 200
```

⚠ **That `200` is the expected answer on Branch A and Branch C only.** Both
leave the `Caddyfile` answering on `:80` for any address, which is what makes
`localhost` work. **Branch B** names one domain in that file, so a request
arriving as `localhost` matches nothing and is refused — correctly. On Branch B,
run this check against the real domain over `https://` instead.

<!-- defines: postgis -->
**PostGIS loaded.** *PostgreSQL* is the database program that stores every
record the site shows, and *PostGIS* is an add-on that teaches it to understand
maps, boundaries and points on a map. This check asks the database to say which
version of that add-on it is running, which is the quickest way to prove it is
switched on at all:

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

Visit `/health/` in a browser, at the address from the top of this section.

**Django admin:**

Visit `/admin/` at that same address and log in with your superuser credentials.

No browser? On **Branch B** and **Branch C**, where `CSRF_COOKIE_SECURE` stays
on, a login sent over plain `http://` returns 403 by design: the browser-safety
cookie is marked so that it travels only over an encrypted connection, so it
never comes back and the check fails. That is correct behaviour, not a fault. On
**Branch A** the three flags are deliberately off, so a plain-HTTP login can
succeed. Either way, the headless check in
[docs/AI-OPERATOR-GUIDE.md](docs/AI-OPERATOR-GUIDE.md) ("Verify login works
(no browser)") works on every branch and is the one to use.

**No errors in logs:**

```bash
docker compose logs web --tail=50
# Look for: "Listening at: http://0.0.0.0:8000"
# No tracebacks or errors
```

**The name this deployment sends mail under:**

Every email this platform sends — password resets above all — carries the
deployment's own name at the front of the subject line, where the person
receiving it will read it before anything else. Nothing has to be configured for
that: the platform works the name out for itself from the agency name typed into
the Setup Wizard (§11) and the web address already in `ALLOWED_HOSTS`, and
writes it down when §6's migration step runs. It is still worth one look, because
a deployment that has been told neither introduces itself as `example.com`.

```bash
docker compose exec web python manage.py shell -c "from django.contrib.sites.models import Site; s = Site.objects.get_current(); print(s.name, '|', s.domain)"
```

Expect the agency's name and this deployment's own web address.
`docker compose exec web python manage.py check` reports the same thing as
`openh2o.W002` if you would rather be told than look.

If the name is missing, it is because nobody has typed the agency's name into
the Setup Wizard (§11) yet; do that and run §6's migration step again, which is
what applies it and which changes nothing else.

**On Branch A the address will stay `example.com`, and that is expected.** The
platform deliberately refuses to treat `localhost` or `127.0.0.1` as a public
web address, so a single-computer deployment has none to derive and the warning
stays. Nothing is broken and there is no value to fill in; on an instance that
sends no outside email it changes nothing anyone sees.

**Who can actually reach it:**

Everything above proves the deployment answers. None of it proves that the
people who can reach it are the people you intended in §4 — a site can answer
perfectly and still be answering the whole internet. So confirm which network
addresses can reach this machine's port 80.

There is no one tool to check that with, and this guide will not pretend
otherwise. A plain Ubuntu server usually has `ufw`; other Linux machines have
`firewalld` or bare `iptables`; and on a rented server the rule that actually
decides often is not on the machine at all but in the provider's control panel,
under a name like "security group", "cloud firewall" or "networking". Check
whichever one your machine has. On a machine using `ufw` it is:

```bash
sudo ufw status verbose
```

Then hold the answer against the branch you chose in §4:

| §4 branch | Who should reach port 80 | What a wrong answer looks like |
|---|---|---|
| **Branch A** (`no-public-access`) | This computer only, or the office network only | Somebody outside the office can open the site |
| **Branch B** (`own-certificate`) | The whole internet, on port 443, and port 80 as well unless you have a reason not to | Nothing outside can reach the machine on either door, so the certificate is never issued and the site never comes up |
| **Branch C** (`upstream-terminator`) | Only the thing in front of it — the tunnel, proxy or load balancer | The whole internet reaches port 80 directly, going around the very thing that was meant to guard it |

A mismatch here is worth settling before handover rather than after. On
**Branch C** in particular, if the machine answers on its own address as well as
through the proxy, then `ALLOWED_HOSTS` is the only thing left between this
deployment and the open internet — which it is built to do, but not built to do
alone.

---

## 11. Ongoing Operations

### The Setup Wizard (`/setup/`)

The platform ships a guided first-run flow at `/setup/`, reached at whatever
address §4's branch gave you for this instance. It is
the browser equivalent of the load-data commands: pick or **upload a map file
holding the outline of the district's service area**, confirm it on a map, run
the `auto_populate` discovery steps with progress on screen, and enable the
monitoring stations that were found.

<!-- defines: geojson -->
That map file has to be in the *GeoJSON* format — a plain-text way of describing
a shape drawn on a map, along with a few labelled facts about it such as a name
and an area. It is non-proprietary and widely supported, which is why a GIS
contractor can hand over one file and expect any capable program to read it.

- **Where it is:** left sidebar, **Administration → Setup Wizard** — but the
  whole Administration block is hidden until you switch the sidebar out of its
  everyday view. The switch is a two-button toggle at the **bottom of the left
  sidebar**, marked **Operations** and **Admin**; click **Admin**. A fresh
  install opens on Operations, so an operator hunting for the wizard and not
  finding it has almost always not clicked that yet.
- **Who can see it:** you have to be signed in — an anonymous visitor is sent to
  the login page whatever else is configured. Beyond that, an administrator can
  always open it, and on an instance that has switched access control off, so
  can any signed-in user. Set up your admin account (§7) before you expose the
  site.
- **What its last step does:** `setup/activate-stations/` bulk-enables **every
  inactive station inside the chosen boundary** in one action. Station discovery
  creates stations switched off, and syncing only pulls data for active ones, so
  a basin stays empty until something turns them on. Over SSH the equivalent is
  `docker compose exec web python manage.py activate_stations --boundary-name "<basin>"`.

### Upgrades

**This block is the upgrade path for an agency running real data.** It updates
the code and the database structure and leaves your records untouched.

```bash
cd /path/to/openh2o
git pull origin main
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py collectstatic --noinput
```

`make deploy` is **not** an upgrade path and must not be used here. It belongs to
the maintainer's public demonstration site: it discards every local change in the
checkout and then replaces the live database with the canned demonstration
snapshot. It refuses to run unless the checkout carries a `.demo-host` marker
file, which only that one demonstration host has.

### Protecting a Live Installation (`.production-lock`)

Once this deployment holds the agency's real records, a single careless command
can destroy them. `make up`, `make down`, `make build` and `make fresh` all
rebuild or reset the stack, and `fresh` deletes the database outright — and
`fresh` is exactly the name somebody reaches for when they want a clean start.

The repository ships a guard against that, and it is opt-in: put an empty file
named `.production-lock` in the checkout, and all four of those commands refuse
to run.

```bash
touch .production-lock
```

That is the whole mechanism. Nothing ever reads the file's contents, only
whether it is there; the `guard-prod` target in the `Makefile` is what checks,
and it prints what it refused and why. The file is listed in `.gitignore`, so a
fresh clone never arrives carrying one — **every deployment that wants this
protection has to create its own, and nothing prompts you to.** Do it as soon as
real data lands.

To run one of those commands deliberately, take the marker off, run it, and put
it back:

```bash
rm .production-lock
make down
touch .production-lock
```

⚠ **`.production-lock` and `.demo-host` mean opposite things — they are not a
pair of related switches.** `.production-lock` says *"this checkout is protected,
refuse anything destructive."* `.demo-host` says the reverse: *"this checkout is
the public demonstration and its database is disposable"*, which is precisely
what lets `make deploy` overwrite it. Creating the wrong one arms the wrong
behaviour on the wrong machine.

### Scheduled Jobs

The jobs in `crontab.txt`:

| Job | Schedule | Purpose |
|-----|----------|---------|
| `run-sync.sh cdec usgs` | Hourly | Live stream / reservoir telemetry (near-real-time flow & stage) |
| `run-sync.sh dwr_wdl dwr_sgma noaa` | Daily 2:00 AM | Slower sources — groundwater, climate. CNRFC and OpenET ship switched off; add them here if you turn them on. CIMIS ships switched **on** but syncs nothing until its key is set |
| `run_health_checks` | Every 6 hours | Check database, disk, SSL, migrations, sync freshness |
| `prune_old_data --confirm` | 1st of month 3:00 AM | Delete old staging records and sync logs |

**`check_conformance` is deliberately not on that schedule, and that is a
decision rather than an oversight.** It answers "is every measurement in here
mapped to a known concept with a real unit?", and that answer only moves when
somebody loads data or switches on a new source — so a clock is the wrong
trigger. Run it by hand at the two moments it matters: right after the agency's
own records are loaded (§9), and before a filing deadline rather than during
one.

```bash
docker compose exec web python manage.py check_conformance
```

It exits non-zero when it finds a real gap, so it can also gate a script.

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

<!-- defines: api_key -->

### External Data API Keys

An *API key* is a long, password-like string that lets this program — rather
than a person — fetch data automatically from another organisation's computers,
without anybody logging in each time. Treat one exactly as you would a password.

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

<!-- defines: smtp -->

### Email / Password Reset (SMTP)

*SMTP* is the agreed method for handing an outgoing email over to a mail
provider, so a website can send messages — "you forgot your password" above all
— instead of pretending to be its own mail server. The settings below are the
login for whichever provider the district uses.

Logged-in users can change their password with no setup — the **Change password**
button on their own profile page (reached by clicking their email address in the
header) works out of the box. The **"Forgot password?"** flow on the
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

#### Signup email verification

The same SMTP settings also drive signup confirmation — whether a new account
must click a link in an email before it can log in. It is controlled by
`ACCOUNT_EMAIL_VERIFICATION`, which takes `none`, `optional` or `mandatory`.

You normally do not set it. Left alone it follows `EMAIL_HOST` above: configure
a mail server and new signups must confirm (`mandatory`); leave `EMAIL_HOST`
empty and they are let straight in (`none`). **An instance with no mail server
therefore never creates an account that can never be confirmed** — which matters
if you are running this on a single office computer.

Two cases where you should set it explicitly:

- **A public demo with SMTP configured** wants `none`, so a visitor looking
  around is not asked to confirm an address.
- **An agency that wants confirmation before its mail server exists** can set
  `mandatory` now and configure SMTP later — but until SMTP is real, the
  confirmation goes to the container log instead of an inbox, and nobody but
  you can complete a signup.

A value that is not one of the three stops the container at boot with an error
naming what you typed. That is deliberate: a silent fallback would read as
"verification is on" while nothing was ever sent.

Note that this only matters where signup is open at all. With
`ACCESS_CONTROL_ENFORCED` at its default (`True`), public self-registration is
closed and an administrator creates accounts directly, so verification never
comes into play.

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

Those four answer *is it broken*. The two below answer a different question —
*has anyone opened this page, and when* — which for a public agency is also the
record that answers a request about the agency's own system:

```bash
docker compose logs caddy | grep 'handled request'       # what visitors asked for, readable
docker compose exec caddy cat /var/log/caddy/access.log  # the copy that survives a deploy
```

**Why the same visits are written down twice, and why you need both.** The first
command reads what the container has said since it last started, and a deploy
(`docker compose up -d --build`) replaces that container and throws all of it
away. The second reads a file kept on a storage area of its own, outside the
container, so it is still there tomorrow and still there after the next deploy.
The first is how you watch traffic arriving now and is the easier of the two to
read; the second is the record you keep.

**Reading a line.** One line per request, in the order they arrived: the time,
the address the request came from, what was asked for, and the three-digit code
saying how it went — `200` served, `302` sent somewhere else, `404` not found,
`500` the program failed. One person opening one page writes several lines,
because the styling, the fonts and the map tiles are each their own request.

The kept copy is written as one machine-readable record per line, which is
thorough but dense to read by eye, and its time is a count of seconds rather
than a date. To pull just what was asked for:

```bash
docker compose exec caddy grep -o '"uri":"[^"]*"' /var/log/caddy/access.log | tail -50
```

**How much is kept, and it is less than it sounds.** The file holds ten
megabytes; when it fills, it is set aside and compressed and a fresh one
started, and five of those older copies are kept. That bounds the whole record
at roughly fifty megabytes and needs nothing installed or scheduled. But each
request costs about two kilobytes here — measured at 1,979 bytes on 2026-08-28,
most of it the security header being written out again on every line — so fifty
megabytes is on the order of **thirty thousand requests**, not millions. A busy
public instance can turn that over in days. Read yours rather than guessing:

```bash
docker compose exec caddy ls -lh /var/log/caddy/
```

If you need to keep visits for longer than that, copy the file somewhere else on
a schedule (section 11 covers scheduling) rather than raising the limit here —
the cap is what stops a quiet instance filling its own disk unattended.

**What is deliberately not in there.** The platform checks its own health every
few seconds, and that check never passes through Caddy — it is asked and
answered inside the app container — so it does not bury the real visits here. It
does appear in `docker compose logs web`, which is why that one is much noisier
and this one is the cleaner record of who actually came to the site.

### Public Demo Reset (golden snapshot)

A **public** demo is single-tenant: one shared database, open self-signup, no
per-visitor isolation. Any logged-in visitor's parcels, wells, and reports
persist for everyone, and nothing prunes them. To keep the demo pristine, restore
it on a schedule from a "golden" snapshot of the clean state.

The golden snapshot is **built from the repository by `make deploy`** (see
*The golden is a build output* below) — that is the path that keeps a deployment's
demonstration reachable from its own source. These two targets are the manual
handles beside it:

```bash
make snapshot-demo   # ESCAPE HATCH: stamp a golden from the LIVE database — the next deploy replaces it
make reset-demo      # restore the demo to the current golden now (scripts/reset-demo.sh)
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

**Where the snapshot lives — one directory per checkout, derived automatically.**
Every demo script resolves its snapshot directory as
`${OPENH2O_SNAPSHOT_DIR:-$HOME/$(basename "$OPENH2O_DIR")-demo-snapshot}`, so a
checkout at `~/openh2o` uses `~/openh2o-demo-snapshot` and a checkout at
`~/openh2o-staging` uses `~/openh2o-staging-demo-snapshot`. The scratch compose
project that `rebuild-golden` and `verify-candidate` build in is derived the same
way (`<checkout>-rebuild`). **Two deployments on one host therefore get two
snapshot directories and two scratch projects, and neither can write or tear down
the other's.** That separation is not cosmetic: `promote-golden` is the only step
inside a deploy that writes `golden.dump` — `make snapshot-demo` writes one too,
by hand, as the escape hatch described above — and before this derivation existed
a deploy run in a staging checkout would have installed a staging-built database
as production's golden. Each script echoes its resolved directory on startup, so the path that was
actually used is in the log of the run that used it. Set `OPENH2O_SNAPSHOT_DIR`, or
pass a path argument, to override.

**Staleness guard (the safety net for the discipline below).** Before wiping,
`reset-demo` compares the live schema's migration fingerprint against the one in
`golden.meta`. If they differ — meaning a migration ran since the snapshot was
taken — it **refuses to wipe, fires a high-priority ntfy, and exits**, so a legit
change is never silently erased. The normal way past it is a deploy, which
promotes a golden built at the current commit and therefore at the current
fingerprint; `FORCE=1` bypasses the guard (which is what the deploy's own
restore step uses, because it has just promoted a matching golden), and
`make snapshot-demo` re-stamps from the live database as a last resort.

**The golden is a BUILD OUTPUT, not a photocopy.** `make deploy` resets to the
ref, **builds** the whole demonstration database from the repository's seed
commands in a disposable compose stack, runs the four promotion gates against a
restore of that build, promotes it to `golden.dump` only if every gate passes,
*then* ships the code and restores the new golden into the live database. The
order matters: Make aborts on the first non-zero line, so a refused promotion
stops the deploy with the old code still serving, the old golden still installed,
and the demo database untouched.

`make deploy` no longer calls `snapshot-demo`. It used to — restore the golden,
then immediately re-stamp a new golden from the database it had just restored.
That closed loop is what let production's demonstration content drift out of
reach of the repository for eight weeks: a fix to demo *content* reached staging
(which rebuilds from the seeds) automatically and production (which only ever
restored a photocopy) never.

**Visitor-added data does not survive a deploy**, and does not survive the
nightly reset either, by design.

> **Discipline — to change what the demonstration shows, change the SEED.** Edit
> the seed command or its committed fixture, commit it, and deploy. The next
> deploy rebuilds from your commit, gates it, and promotes it, so the change
> reaches every deployment that ships that commit — which is the whole point.
>
> Two manual paths still write a golden from the live database, and what they
> write is **temporary by construction — the next `make deploy` replaces it**:
> `make calc-rebuild PERIOD=YYYY-MM` (recompute a period, then re-stamp) and
> `make snapshot-demo` (the bare escape hatch). Reach for them when you need the
> live demo corrected *now*; reach for a seed change when you need it corrected
> *durably*.

---

<!-- defines: environment_variable -->
<!-- defines: wsgi_gunicorn -->
<!-- defines: oauth -->

## 12. Environment Variables Reference

An *environment variable* is a named value the operating system hands to a
program as that program starts. The `.env` file from §3 is simply a convenient
place to write a whole list of them down, and every name in the table below is
one of them.

Two of those names carry ideas the table has no room to explain:

- **Gunicorn** is the program that actually listens for browser visits and hands
  each one to the site's own code; *WSGI* is the agreed shape of that handover,
  which is why one of the files named below is called `wsgi.py`.
- **OAuth** is a way for staff to sign in with an existing Google account
  instead of a separate OpenH2O password, by having Google vouch for who they
  are. The *client ID* and *client secret* are the two values Google issues so
  that it recognises this particular installation.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SECRET_KEY` | Yes | none | Django secret key for signing |
| `POSTGRES_DB` | No | `openh2o` | PostgreSQL database name |
| `POSTGRES_USER` | No | `openh2o` | PostgreSQL username |
| `POSTGRES_PASSWORD` | **Yes (prod)** | `openh2o` | PostgreSQL password. Production settings refuse to boot if it is left empty or set to any of four known-insecure defaults — `openh2o`, `postgres`, `password`, `changeme` — so a real deployment must set it. The check is that blocklist, not a strength test: it will accept a short password that is merely unusual |
| `DJANGO_SETTINGS_MODULE` | **Yes — set it explicitly** | **split by entry point:** `manage.py` defaults to `config.settings.production`; `config/wsgi.py` and `config/asgi.py` default to `config.settings.local` | Always set `config.settings.production` for a real deployment, on any hardware. ⚠ This one variable is read before Django loads its settings, so unlike the rest of the file it is not picked up from `.env` on a host shell — running `manage.py` outside the container needs it exported into the shell first (`set -a`, source this file, `set +a`), or `manage.py` loads its own default instead |
| `ALLOWED_HOSTS` | Yes (prod) | `[]` | Comma-separated list of allowed hostnames |
| `CSRF_TRUSTED_ORIGINS` | No (but set it with a public domain) | `[]` | Comma-separated HTTPS origins. Nothing refuses to boot without it, and §3 tells single-computer and office-network deployments to leave it empty; a deployment served over HTTPS at a domain needs it, or logins from that domain are rejected |
| `ACCESS_CONTROL_ENFORCED` | No | `True` | Two-tier access model. On (default) closes public self-signup and gates admin-only screens — the right posture for a real agency. Set `False` only for an open demo where anyone should be able to self-register. Your superuser is always an administrator, so you can't lock yourself out |
| `TIME_ZONE` | No | `America/Los_Angeles` | Django timezone |
| `DEFAULT_FROM_EMAIL` | No | `noreply@openh2o.com` | Sender address for emails |
| `EMAIL_BACKEND` | No | console (dev), SMTP (prod) | Django email backend |
| `EMAIL_HOST` | No | empty | SMTP server hostname |
| `EMAIL_PORT` | No | `587` | SMTP port |
| `EMAIL_USE_TLS` | No | `True` | Use TLS for SMTP |
| `EMAIL_HOST_USER` | No | empty | SMTP username |
| `EMAIL_HOST_PASSWORD` | No | empty | SMTP password |
| `ACCOUNT_EMAIL_VERIFICATION` | No | **derived from `EMAIL_HOST`:** `mandatory` when a mail server is set, `none` when it is empty | Whether a new signup must confirm its email address before it can log in. `none` = let them straight in; `optional` = send the email but don't block; `mandatory` = block login until confirmed. The derivation means an install with no mail server can never lock out its own operator, while an agency that has configured SMTP gets confirmation without asking for it. Set it explicitly to override — an open demo with SMTP configured wants `none`. An unrecognised value stops the container at boot rather than falling back silently |
| `GOOGLE_OAUTH_CLIENT_ID` | No | empty | Google OAuth client ID (see the note below — the keys are one of the two halves that make Google sign-in exist, and on their own they do nothing anyone can see) |
| `GOOGLE_OAUTH_CLIENT_SECRET` | No | empty | Google OAuth client secret (see the note below) |
| `DATASYNC_MOCK_MODE` | No | `False` | Use mock data for external sync adapters instead of live APIs |
| `FEEDBACK_ENABLED` | No | `False` | Render the in-app feedback widget. Off by default; set `True` to turn it on (e.g. on a hosted/managed deployment with someone to read the reports) |
| `FEEDBACK_ENDPOINT` | No | empty | Optional URL to also POST each stored report to (e.g. an n8n triage pipeline); blank = store-only |
| `FEEDBACK_MAX_ATTACHMENTS` | No | `5` | Max screenshots allowed per report |
| `FEEDBACK_MAX_ATTACHMENT_BYTES` | No | `8388608` | Max size per attachment (bytes; default 8 MB) |
| `FEEDBACK_MAX_MESSAGE_CHARS` | No | `5000` | Max characters in a feedback message |
| `FEEDBACK_MAX_DIAGNOSTICS_BYTES` | No | `65536` | Max size of the auto-captured diagnostics blob (bytes; default 64 KB) |
| `FEEDBACK_RATE_LIMIT_PER_HOUR` | No | `20` | Max submissions accepted per client per hour |

**Google sign-in is configured in two separate places, and this file is only one
of them.** Putting `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` in
`.env` is half of it. The other half happens inside the Google account that
issued those two values: that account's own control panel has to be told which
web addresses are allowed to use them, and this deployment's address has to be
one of the addresses on that list. **Expect that second login to belong to
somebody else** — a district's Google account is usually held by whoever
administers their email, not by the person standing this platform up. Find out
who that is before you start, rather than halfway through.

**A half-finished setup does not look broken, and that is the expensive part.**
With the two values set here and this deployment's address never added on
Google's side, the sign-in button appears exactly as it should and behaves
normally right up until somebody clicks it. Google then refuses, with an error
about a "redirect" that means nothing at all to a reader who is not a web
developer. If you cannot complete both halves, leave the feature switched off: a
login page with no Google button is obviously a login page with no Google
button, and a broken one is not obviously anything.

**A third switch decides whether Google sign-in exists here at all.** Setting
the two keys makes it *possible* and changes nothing anyone can see. It becomes
real — the **"Continue with Google"** button on the login and sign-up pages, and
the web addresses that button leads to — only once the per-agency database flag
`allow_google_oauth` is switched on, and it ships off. Turn it on at **Django
admin → Core → Site configs → (your agency)**, tick **Allow google oauth**, and
save.

**The keys and the switch are two halves of one thing, and either half missing
gives the same result: there is no Google sign-in on this deployment.** No
button appears, and the web addresses the button would have led to are not there
either — somebody who types one in gets the ordinary "page not found", because
there genuinely is no page. **So the order does not matter.** Tick the box now
and paste the keys next week, or the other way round; nothing is broken in
between and nothing is exposed in between. If you decide against the feature
later, untick the box and it is gone again the moment you save.

**Before you turn it on, know that on some deployments it changes what an
existing password does.** Once Google sign-in is live, somebody who already has
an OpenH2O account and clicks **"Continue with Google"** is signed straight into
that same account whenever Google confirms the same address they registered
with. **If that address has never been confirmed on this deployment, their
OpenH2O password is *cleared* on the way through.** From then on that person
signs in with Google, and the password they had been using stops working. Nobody
loses their account or their data, and nobody is locked out. If the address
*has* been confirmed here, nothing happens to the password at all.

**Which case you are in was decided by whether you set up a mail server.**
`ACCOUNT_EMAIL_VERIFICATION` (covered in §11 "Signup email verification", and in
the environment variable table in §12) derives to `mandatory` the moment
`EMAIL_HOST` is set, so an agency with SMTP configured has every address
confirmed and **no password is ever cleared**. With no mail server it derives to
`none`, addresses stay unconfirmed, and the clearing described above is what
your staff will meet. Read it back rather than guessing:

```bash
docker compose exec web python manage.py shell -c "from django.conf import settings; print(settings.ACCOUNT_EMAIL_VERIFICATION)"
```

If that prints `none`, it is a change to how your staff get in, it happens the
first time each of them uses the button, and nothing on screen warns them, so
tell them before you save the switch, not after. If it prints `mandatory` or
`optional` and your people have confirmed their addresses, the switch costs them
nothing and there is nothing to announce.

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

<!-- defines: private_ip -->
**The log is full of rejected requests addressed by number instead of by the
site's web address — is somebody attacking us?** By itself, that is not evidence
of one. Every computer on a network also has a numeric address, and some ranges
of those numbers — `192.168.…` and the like — only work inside one building or
one provider's private network and mean nothing at all on the open internet.
This document cannot tell you what is sending yours, and will not guess. What it
can tell you is that a request being addressed by number is not, on its own,
evidence of anything: the log lines themselves are not a sign of trouble.

The rejection is `ALLOWED_HOSTS` doing precisely its job. A request whose
address is not on that safety list is refused, and Django writes a line about a
disallowed host into the log every time. That is the guard working, not the
guard being defeated, and nothing needs fixing on account of it. If you would
rather the checks succeed than be turned away — a monitoring tool you run
yourself, say — add the number it uses to `ALLOWED_HOSTS` in `.env` and
`docker compose up -d` to reload. Do not add it just to quieten the log.

<!-- defines: geospatial_libraries -->
**"GDAL library not found" or GeoDjango errors:**

GDAL, GEOS and PROJ are widely-used open-source code libraries that do the
actual geometry and map arithmetic — parcel boundaries, well locations,
distances on a curved earth. Nobody ever interacts with them directly; the
software simply will not start without them. The Dockerfile installs all three,
which is why an error here is a build problem rather than something to
configure. If building locally without Docker, install the system packages
yourself:

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

<!-- defines: collectstatic -->
**Static files not loading (404 on /static/):**

The site's images, fonts, styling and scripts are its *static files*, and they
have to be gathered into one folder before they can be served. `collectstatic`
is the step that gathers them, and a piece of code called WhiteNoise is what
then hands them to a visitor's browser. A page that loads with no styling at all
usually means that gathering step has not run:

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
