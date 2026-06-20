# Third-Party Notices

OpenH2O (the Open Water Accounting Platform) is licensed under AGPL-3.0-or-later.
It is built with open-source components that carry their own licenses. This file
acknowledges those components and points to their license texts, as several of
them require.

It is **not** a statement that any of this code is part of OpenH2O's own source —
these are independent libraries OpenH2O depends on. OpenH2O's first-party source
is licensed under AGPL-3.0-or-later; see `LICENSE` and `NOTICE`.

Licenses change between releases. The authoritative license for any component is
the one shipped in that component's own distribution. If you find an error or
omission here, please open an issue.

---

## Components with copyleft (LGPL) terms — attribution required

These libraries are distributed inside the OpenH2O Docker image and ask, at
minimum, that they be named with a pointer to their license. LGPL nests cleanly
inside AGPL: each is dynamically linked, and because OpenH2O ships its complete
corresponding source, the LGPL relinking condition is inherently satisfied.

| Component | Role | License | Project | License text |
|-----------|------|---------|---------|--------------|
| **psycopg** (psycopg 3, `[binary]`) | PostgreSQL database adapter | **LGPL-3.0-only** | https://github.com/psycopg/psycopg | https://www.gnu.org/licenses/lgpl-3.0.html |
| **GEOS** (`libgeos`) | Geometry engine used by GeoDjango/PostGIS | **LGPL-2.1-or-later** | https://libgeos.org/ | https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html |
| **GNU gettext** (`libintl` runtime) | Message translation runtime | **LGPL-2.1-or-later** | https://www.gnu.org/software/gettext/ | https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html |

> The PostGIS database and the GEOS/GDAL/PROJ system libraries are installed in
> the runtime image but are not modified. The corresponding source for each is
> available from its project above and from the Debian package archive.

---

## Permissively licensed components

Permissive licenses (MIT, BSD, Apache-2.0, HPND) require only that their
copyright and license notice be preserved on redistribution. They impose no
copyleft obligation on OpenH2O. Listed here for completeness.

### Python dependencies (shipped in the Docker image)

| Component | License |
|-----------|---------|
| Django | BSD-3-Clause |
| django-environ | MIT |
| gunicorn | MIT |
| whitenoise | MIT |
| django-allauth | MIT |
| django-extensions | MIT |
| django-htmx | MIT |
| Pillow | HPND (MIT-CMU) |
| requests | Apache-2.0 |
| earthengine-api | Apache-2.0 |
| pytest, factory-boy | MIT |
| pytest-django | BSD-3-Clause |

### System libraries and build tools (in the Docker image)

| Component | License |
|-----------|---------|
| GDAL (`libgdal`) | MIT/X11-style (permissive) |
| PROJ (`libproj`) | MIT |
| Tailwind CSS (standalone binary) | MIT |

### Loaded from a CDN at runtime (not redistributed by OpenH2O)

These are referenced by URL and served to the browser by a third-party CDN, so
OpenH2O does not distribute them. Credited as a courtesy.

| Component | License |
|-----------|---------|
| HTMX | BSD-2-Clause |
| MapLibre GL JS | BSD-3-Clause |

---

## A note on the native app

The OpenH2O native (Apple) application currently bundles **no third-party
packages** — its dependency list is empty. If that changes, this notice (or an
in-app "Licenses" / acknowledgments screen) must be updated to credit whatever
it ships, the same way this file credits the web platform's dependencies.
