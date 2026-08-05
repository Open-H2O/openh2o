# SPDX-License-Identifier: AGPL-3.0-or-later
"""The words the operator documents use and never explain.

Four zero-context agents deployed this platform from the repository alone in
v2.9 — three onto x86 servers with a real public address, one as a local install
on Apple silicon — and each kept a log of every word the documentation used
without defining it. Their reader was named for them: a civil engineer at a
sister water district, thirty years in groundwater and irrigation, who has never
heard of DNS, a rented server, what sends an email, or what an API key is.

This module is those four lists, merged, one record per concept. The logs:

    .planning/telemetry/cleanroom-runs/x86-blind-run-001/logs/OUTSIDE-KNOWLEDGE-LOG.md
    .planning/telemetry/cleanroom-runs/x86-blind-run-002/logs/OUTSIDE-KNOWLEDGE-LOG.md
    .planning/telemetry/cleanroom-runs/x86-blind-run-003/logs/OUTSIDE-KNOWLEDGE-LOG.md
    .planning/telemetry/cleanroom-runs/arm64-local-run-004/logs/OUTSIDE-KNOWLEDGE-LOG.md

Those logs live under ``.planning/``, which ``.dockerignore`` excludes, and the
test suite runs inside the ``web`` container. The gate can therefore never read
them at test time. They are transcribed here once and cited as provenance;
``reported_by`` on every record names the run or runs that wrote the term down.
Nothing on this list was invented by us.

**What a record claims, and what it does not.** A record claims that a
participant hit this word and could not get past it without knowing something
the repository never told them — so an operator document that uses the word owes
the reader a definition before it does. It claims *nothing* about whether any
particular definition is adequate. No test can read a sentence and judge whether
a groundwater engineer would understand it. ``plain_english`` below is the run's
own wording, kept because four agents already wrote definitions aimed squarely
at that reader; it is Phase 114's starting text, not its finish line, and Phase
114 pairs the machine gate with a human read for exactly this reason.

**Pure data.** No Django import, no model import, no settings access. The gate
runs without a database and cannot be broken by an unrelated app change.
"""

import re
from dataclasses import dataclass

#: The four clean-room runs, as they are named in ``.planning/telemetry/``.
RUN_001 = "x86-blind-run-001"
RUN_002 = "x86-blind-run-002"
RUN_003 = "x86-blind-run-003"
RUN_004 = "arm64-local-run-004"


@dataclass(frozen=True)
class OperatorTerm:
    """One concept an operator document may not use before defining it."""

    #: Stable lowercase identifier. This is the string a document names in its
    #: ``<!-- defines: SLUG -->`` marker, so renaming one silently un-defines
    #: every place that already claimed it.
    slug: str
    #: The human name, used verbatim in failure messages.
    label: str
    #: Case-insensitive regexes matching the term in prose. Word-bounded
    #: without exception — see the module note on pattern discipline below.
    patterns: tuple
    #: Which clean-room run or runs reported this term. Provenance is the point.
    reported_by: tuple
    #: The runs' own plain-English definition, quoted or lightly merged.
    #: Phase 114's starting text.
    plain_english: str


# Pattern discipline
# ------------------
# Word boundaries always. ``\b`` is what keeps ``\bports?\b`` off *important*,
# *support*, *portal*, *export* and *reporting* — all common in this repository
# — while still catching "port 80". A pattern without them is a false-positive
# generator, and a gate that cries wolf is a gate nobody reads.
#
# Several precise patterns beat one loose one: ``\.env\b`` not ``env``,
# ``\bAPI keys?\b`` not ``\bkeys?\b``.
#
# Where a term genuinely cannot be matched precisely, the looser candidate is
# left OUT and the record carries a comment saying which one and why. Those
# omissions are deliberate under-reach: this gate would rather miss a use than
# manufacture one.

TERMS: tuple = (
    OperatorTerm(
        slug="repository",
        label="repository / repo / cloning",
        patterns=(r"\brepositor(?:y|ies)\b", r"\brepos?\b", r"\bgit clone\b",
                  r"\bGitHub\b", r"\bcloning\b"),
        reported_by=(RUN_001, RUN_002),
        # Run 001 wrote the folder framing; run 002 the filing-cabinet framing.
        plain_english=(
            "A repository is just a folder of the program's files, kept on a "
            "website called GitHub, with a complete history of every change "
            "ever made to it. Cloning it means copying that whole folder onto "
            "our own server so it can be built and run here."
        ),
    ),
    OperatorTerm(
        slug="docker",
        label="Docker / container",
        # Bare `\bimages?\b` is deliberately absent: this repository also talks
        # about map images and the images WhiteNoise serves, and one loose
        # pattern here would fire on both. "Docker image" is matched instead.
        patterns=(r"\bDocker\b", r"\bcontainers?\b", r"\bDocker images?\b",
                  r"\bcontainerized\b"),
        reported_by=(RUN_001, RUN_002, RUN_003, RUN_004),
        # All four runs defined this. Run 001's sealed-box wording, with run
        # 002's image-vs-container distinction folded in.
        plain_english=(
            "A container is a sealed, pre-packed box holding one piece of the "
            "program plus everything it needs to run, so it behaves the same "
            "on any computer. Docker is the software that builds and runs "
            "those boxes. An image is the packaged blueprint; a container is "
            "one running copy of it. This program ships as three containers: "
            "one for the web pages, one for the database, and one that manages "
            "the address and encryption."
        ),
    ),
    OperatorTerm(
        slug="docker_compose",
        label="Docker Compose",
        patterns=(r"\bDocker Compose\b", r"\bdocker[- ]compose\b"),
        reported_by=(RUN_001, RUN_003, RUN_004),
        # Run 001's definition; run 004 flagged the bare `docker compose up`.
        plain_english=(
            "A helper tool, installed alongside Docker, that starts, stops and "
            "rebuilds all three containers together from one instruction file "
            "(docker-compose.yml), instead of doing each by hand."
        ),
    ),
    OperatorTerm(
        slug="nested_container",
        label="nested container (a rented computer that is itself a container)",
        # This phrase appears nowhere in the documents today, so the gate will
        # never report it. The record exists because run 004 lost its entire
        # Docker path to this and Phase 114 has to decide, on purpose, whether
        # the documents say anything about it — not discover the gap by
        # deploying into one again.
        patterns=(r"\bnested container\b",),
        reported_by=(RUN_004,),
        plain_english=(
            "Some computers you rent from a cloud provider are not a real "
            "physical machine but a slice of one, walled off by the same "
            "container technology Docker uses. Normally that is invisible. It "
            "matters because Docker then tries to create its own containers "
            "inside an already-walled-off computer, and cannot. No fix inside "
            "the computer will ever work; the block is one level up, on the "
            "host."
        ),
    ),
    OperatorTerm(
        slug="env_file",
        label=".env file",
        patterns=(r"\.env\b", r"\benvironment file\b"),
        reported_by=(RUN_001, RUN_002, RUN_003, RUN_004),
        # Run 001's wording, with run 002's "makes this installation ours" line.
        plain_english=(
            "A plain text file of NAME=value lines holding the program's "
            "settings and passwords. It is the one file that makes this "
            "installation this district's rather than a generic copy, and it "
            "is deliberately kept out of the copy of the program that lives on "
            "GitHub, because it often contains secrets."
        ),
    ),
    OperatorTerm(
        slug="environment_variable",
        label="environment variable",
        patterns=(r"\benvironment variables?\b",),
        reported_by=(RUN_002, RUN_003, RUN_004),
        plain_english=(
            "A named value the operating system hands to a running program — "
            "the more general idea that .env files are a convenience for."
        ),
    ),
    OperatorTerm(
        slug="secret_key",
        label="SECRET_KEY",
        patterns=(r"\bSECRET_KEY\b",),
        reported_by=(RUN_001, RUN_004),
        plain_english=(
            "An internal password the software generates for itself, used to "
            "scramble things like login session cookies. Not a password anyone "
            "types in; it just has to exist and stay private."
        ),
    ),
    OperatorTerm(
        slug="reverse_proxy",
        label="reverse proxy / Caddy",
        patterns=(r"\breverse[- ]prox(?:y|ies)\b", r"\bCaddy\b",
                  r"\bCaddyfile\b", r"\bproxy\b"),
        reported_by=(RUN_001, RUN_002),
        # Run 002's middleman framing; run 001 added the two-in-a-row case.
        plain_english=(
            "A middleman program that receives the public traffic and relays "
            "it inward to the real program — here, Caddy. A deployment behind "
            "a district's own proxy has two of these in a row: theirs, out of "
            "our control, in front of this server, and Caddy inside Docker in "
            "front of OpenH2O itself."
        ),
    ),
    OperatorTerm(
        slug="tls_https",
        label="TLS / HTTPS / certificate",
        # `\bHTTPS\b(?!://)` — a link target like `https://openh2o.com` is not
        # the document using the word "HTTPS"; it is an address. Matching it
        # would report the badge line at the top of README.md, which says
        # nothing about encryption at all.
        patterns=(r"\bHTTPS\b(?!://)", r"\bTLS\b", r"\bSSL\b",
                  r"\bcertificates?\b", r"\bterminates? upstream\b"),
        reported_by=(RUN_001, RUN_002, RUN_003),
        # Run 003's wording, which is the one that also names the failure mode.
        plain_english=(
            "HTTPS is the padlock-icon, encrypted version of a web address; "
            "TLS is the encryption technology behind that padlock, and a "
            "certificate is what proves the address is really itself. A "
            "connection has to be decrypted somewhere before a program can "
            "read it. 'Terminates upstream' means that happens on someone "
            "else's equipment before traffic ever reaches this server, so this "
            "server only ever sees plain, unencrypted traffic. That is normal "
            "and not a fault to fix."
        ),
    ),
    OperatorTerm(
        slug="port",
        label="port",
        patterns=(r"\bports?\b",),
        reported_by=(RUN_001, RUN_002, RUN_003, RUN_004),
        plain_english=(
            "A numbered door on the server that a particular kind of traffic "
            "knocks on. Port 80 is the plain, unencrypted web door — the one a "
            "browser uses when you type no number at all. Port 443 is the "
            "encrypted one."
        ),
    ),
    OperatorTerm(
        slug="dns",
        label="DNS / A record / pointing a domain",
        patterns=(r"\bDNS\b", r"\bA record\b", r"\bnameservers?\b",
                  r"\bpoint(?:ed|ing|s)? (?:the|your) domain\b"),
        reported_by=(RUN_001, RUN_002, RUN_003),
        plain_english=(
            "The internet routes by number, not by name. DNS is the phone book "
            "that turns a web address into the numeric address of a specific "
            "computer, and an A record is one entry in it. 'Pointing the "
            "domain at this machine' means editing that phone-book entry."
        ),
    ),
    OperatorTerm(
        slug="x_forwarded_proto",
        label="X-Forwarded-Proto header",
        patterns=(r"\bX-Forwarded-Proto\b", r"\bSECURE_PROXY_SSL_HEADER\b"),
        reported_by=(RUN_003,),
        plain_english=(
            "When a proxy strips the encryption before forwarding a request, "
            "it can attach a note saying 'this was encrypted when the visitor "
            "sent it.' X-Forwarded-Proto is that note, and the software is "
            "configured to trust it instead of insisting on seeing encryption "
            "it will never see."
        ),
    ),
    OperatorTerm(
        slug="allowed_hosts",
        label="ALLOWED_HOSTS / CSRF_TRUSTED_ORIGINS",
        patterns=(r"\bALLOWED_HOSTS\b", r"\bCSRF_TRUSTED_ORIGINS\b", r"\bCSRF\b"),
        reported_by=(RUN_001, RUN_002, RUN_003),
        plain_english=(
            "Two safety lists in the program's settings. The program refuses "
            "to answer unless the address in the request matches one of them, "
            "which stops a stranger tricking it into behaving as a different "
            "website. They have to hold the district's real address exactly, "
            "or the site refuses every visitor."
        ),
    ),
    OperatorTerm(
        slug="api_key",
        label="API key / token",
        patterns=(r"\bAPI keys?\b", r"\bAPI tokens?\b", r"\baccess tokens?\b",
                  r"\bbearer tokens?\b"),
        reported_by=(RUN_001, RUN_002, RUN_003, RUN_004),
        plain_english=(
            "A long password-like string that lets this program — not a person "
            "— fetch data automatically from another organisation's computer "
            "system, such as weather or satellite data, without a human "
            "logging in each time. Treated as a secret, same as a password."
        ),
    ),
    OperatorTerm(
        slug="oauth",
        label="OAuth / Sign in with Google",
        patterns=(r"\bOAuth\b", r"\b(?:Sign|Log|Continue) in with Google\b",
                  r"\bContinue with Google\b", r"\bclient secrets?\b",
                  r"\bclient IDs?\b"),
        reported_by=(RUN_001, RUN_002, RUN_004),
        plain_english=(
            "A way for staff to log in using an existing Google account "
            "instead of a separate OpenH2O password, by having Google vouch "
            "for who they are. The client ID and client secret are the two "
            "values Google issues so it recognises this particular "
            "installation."
        ),
    ),
    OperatorTerm(
        slug="superuser",
        label="superuser / admin account",
        patterns=(r"\bsuperusers?\b", r"\bcreatesuperuser\b"),
        reported_by=(RUN_001, RUN_002, RUN_003, RUN_004),
        plain_english=(
            "The one account inside OpenH2O that can do anything — add other "
            "staff accounts, change settings, see everything. It is separate "
            "from and unrelated to any login for the server itself, and it has "
            "to be created by hand before anyone can sign in at all. There is "
            "no 'first visitor becomes admin' magic."
        ),
    ),
    OperatorTerm(
        slug="sudo",
        label="sudo",
        patterns=(r"\bsudo\b",),
        reported_by=(RUN_001, RUN_003, RUN_004),
        plain_english=(
            "A Linux command meaning 'do the next thing with full "
            "administrator power.' Needed for anything that changes the server "
            "itself — installing software, changing who may run Docker — as "
            "opposed to changes that stay inside the OpenH2O program."
        ),
    ),
    OperatorTerm(
        slug="migrations",
        label="migrations",
        patterns=(r"\bmigrations?\b", r"\bmigrate\b", r"\bmigrating\b"),
        reported_by=(RUN_001, RUN_002, RUN_004),
        plain_english=(
            "A step where the program builds or updates the actual tables "
            "inside its database to match what the current version of the "
            "software expects. Routine and expected after every install or "
            "update; skipping it leaves an empty, unusable database."
        ),
    ),
    OperatorTerm(
        slug="cron",
        label="cron / crontab / scheduled job",
        patterns=(r"\bcron\b", r"\bcrontab\b", r"\bscheduled jobs?\b"),
        reported_by=(RUN_001, RUN_002, RUN_003),
        plain_english=(
            "Linux's built-in scheduler: 'run this command every night at "
            "2am.' A task the server runs by itself on a repeating clock with "
            "nobody there to click a button. OpenH2O uses it to fetch new "
            "weather and stream data and to check its own health."
        ),
    ),
    OperatorTerm(
        slug="seed_data",
        label="seed data / demo data",
        patterns=(r"\bseed(?:s|ed|ing)?\b", r"\bdemo data\b", r"\bfixtures?\b"),
        reported_by=(RUN_001, RUN_004),
        plain_english=(
            "Seeding means loading a starting set of data into the empty "
            "database — either small reference lists such as units and "
            "categories, or a full demonstration dataset so there is something "
            "to look at before the agency's own records are loaded."
        ),
    ),
    OperatorTerm(
        slug="idempotent",
        label="idempotent",
        patterns=(r"\bidempoten(?:t|cy|tly)\b",),
        reported_by=(RUN_002, RUN_003),
        plain_english=(
            "A command is idempotent if running it five times has the same end "
            "result as running it once — it notices what is already done and "
            "skips it, rather than duplicating or breaking things. Which is "
            "why re-running one after an interruption is usually safe."
        ),
    ),
    OperatorTerm(
        slug="private_ip",
        label="IP address / private vs public address",
        patterns=(r"\bIP address(?:es)?\b", r"\bprivate IP\b", r"\binternal IP\b"),
        reported_by=(RUN_002,),
        plain_english=(
            "Every computer on a network has a numeric address. Some ranges — "
            "192.168.x.x and the like — only work inside one building or one "
            "provider's private network and mean nothing on the open internet. "
            "Seeing one in a log tells you the request came from something on "
            "the same private network, not from a stranger."
        ),
    ),
    OperatorTerm(
        slug="google_earth_engine",
        label="Google Earth Engine",
        patterns=(r"\bGoogle Earth Engine\b", r"\bGEE\b",
                  r"\bEarth Engine\b"),
        reported_by=(RUN_002,),
        plain_english=(
            "A separate, heavier-duty Google service for processing satellite "
            "imagery at large scale. A district may hold a key for it without "
            "needing it at their size."
        ),
    ),
    OperatorTerm(
        slug="geospatial_libraries",
        label="GDAL / GEOS / PROJ",
        patterns=(r"\bGDAL\b", r"\bGEOS\b", r"\bPROJ\b", r"\blibgdal\b"),
        reported_by=(RUN_001, RUN_004),
        plain_english=(
            "Widely-used open-source code libraries that do the actual "
            "geometry and map maths — parcel boundaries, well locations. "
            "Nobody interacts with them directly; the software simply does not "
            "start without them, and inside Docker they install themselves as "
            "part of the build."
        ),
    ),
    OperatorTerm(
        slug="postgis",
        label="PostgreSQL / PostGIS",
        patterns=(r"\bPostGIS\b", r"\bPostgreSQL\b", r"\bPostgres\b", r"\bpsql\b"),
        reported_by=(RUN_001, RUN_004),
        plain_english=(
            "PostgreSQL is the database program that stores every record the "
            "website shows. PostGIS is an add-on that teaches it to understand "
            "maps, boundaries and points on a map."
        ),
    ),
    OperatorTerm(
        slug="smtp",
        label="SMTP / transactional email",
        patterns=(r"\bSMTP\b", r"\btransactional email\b", r"\bmail servers?\b",
                  r"\bPostmark\b"),
        reported_by=(RUN_003, RUN_004),
        plain_english=(
            "The plumbing that lets a website send outgoing email — here, "
            "'you forgot your password' messages — through an outside mail "
            "provider rather than pretending to be its own mail server. SMTP "
            "is the protocol used to hand the message over."
        ),
    ),
    OperatorTerm(
        slug="geojson",
        label="GeoJSON",
        patterns=(r"\bGeoJSON\b",),
        reported_by=(RUN_003,),
        plain_english=(
            "A plain-text file format for describing a shape drawn on a map — "
            "a district boundary, say — along with a few labelled facts about "
            "it such as a name and an area. Widely used and non-proprietary, "
            "which is why a GIS contractor can hand over one file and expect "
            "any capable program to read it."
        ),
    ),
    OperatorTerm(
        slug="openet_budget",
        label="OPENET_MONTHLY_BUDGET",
        patterns=(r"\bOPENET_MONTHLY_BUDGET\b", r"\bmonthly budget\b"),
        reported_by=(RUN_003,),
        plain_english=(
            "Not a money figure — a count of how many times per month this "
            "deployment may ask the satellite-imagery service for data. "
            "Exceeding it does not cost money; it simply stops working until "
            "the count resets on the first of the month."
        ),
    ),
    OperatorTerm(
        slug="venv",
        label="virtual environment (venv)",
        patterns=(r"\bvenv\b", r"\bvirtualenv\b", r"\bvirtual environments?\b"),
        reported_by=(RUN_004,),
        plain_english=(
            "An isolated copy of Python's package list just for this one "
            "project, so its exact versions of things do not clash with "
            "anything else on the computer."
        ),
    ),
    OperatorTerm(
        slug="pip",
        label="pip",
        patterns=(r"\bpip\b", r"\bpip3\b"),
        reported_by=(RUN_004,),
        plain_english=(
            "The command that downloads and installs the exact Python add-on "
            "packages this project needs, as listed in requirements.lock."
        ),
    ),
    OperatorTerm(
        slug="systemd",
        label="systemd / service",
        patterns=(r"\bsystemd\b", r"\bsystemctl\b"),
        reported_by=(RUN_004,),
        # `\bservices?\b` is deliberately absent: this repository uses "service"
        # for outside data services, for Docker Compose services and for the
        # district's service area, and one pattern cannot tell them apart.
        plain_english=(
            "Linux's standard way of running a program continuously in the "
            "background and restarting it automatically, including after the "
            "computer reboots, without anyone leaving a window open."
        ),
    ),
    OperatorTerm(
        slug="localhost",
        label="localhost / 127.0.0.1",
        patterns=(r"\blocalhost\b", r"\b127\.0\.0\.1\b"),
        reported_by=(RUN_004,),
        plain_english=(
            "Both mean 'this same computer,' as opposed to a web address "
            "anyone else could type. Typing http://localhost into a browser "
            "only reaches the site from the computer it is running on."
        ),
    ),
    OperatorTerm(
        slug="wsgi_gunicorn",
        label="WSGI / Gunicorn",
        patterns=(r"\bWSGI\b", r"\bgunicorn\b"),
        reported_by=(RUN_004,),
        # `\bworkers?\b` and `\bthreads?\b` are deliberately absent — both are
        # ordinary English in a document about people and about data feeds.
        plain_english=(
            "Gunicorn is the program that actually listens for browser visits "
            "and hands each one to the site's own code; WSGI is the agreed "
            "shape of that handover. 'Workers' and 'threads' just mean how "
            "many visits it can handle at the same moment."
        ),
    ),
    OperatorTerm(
        slug="collectstatic",
        label="static files / collectstatic / WhiteNoise",
        patterns=(r"\bcollectstatic\b", r"\bstatic files\b", r"\bWhiteNoise\b"),
        reported_by=(RUN_004,),
        plain_english=(
            "The site's images, fonts, styling and scripts have to be gathered "
            "into one folder before they can be served; collectstatic is the "
            "step that gathers them, and WhiteNoise is the piece of code that "
            "then hands them to a visitor's browser efficiently."
        ),
    ),
)


#: Compiled once. Case-insensitive throughout — the documents write "Docker",
#: "docker" and "DOCKER" and all three are the same word to a reader.
COMPILED: dict = {
    term.slug: tuple(re.compile(pattern, re.IGNORECASE) for pattern in term.patterns)
    for term in TERMS
}

TERMS_BY_SLUG: dict = {term.slug: term for term in TERMS}
