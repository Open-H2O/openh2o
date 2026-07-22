# SPDX-License-Identifier: AGPL-3.0-or-later
"""Render the pages Plan 88-01 touches and write them to a directory for diffing.

The milestone constraint is "zero behavior change for the default all-modules
deployment", and the honest way to hold that is a byte diff of the rendered
output before and after -- not an assertion that it should be fine. Run this at
the pre-change commit, run it again after, diff the two directories.

Fetched through Django's test Client against a scratch database so the output
depends on the templates and views alone: no live rows, no session state, no
timestamps. Both the anonymous and the signed-in render of "/" are captured,
because config.views.index serves index.html to one and home.html to the other.

Usage (inside the web container):
    python scripts/render_baseline.py /tmp/render-before
"""
import os
import re
import sys

import django

# Run as `python scripts/render_baseline.py`, so sys.path[0] is scripts/ rather
# than the project root -- put the root back or `config` does not import.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
django.setup()

from django.test import Client  # noqa: E402
from django.test.utils import setup_test_environment, teardown_test_environment  # noqa: E402
from django.db import connection  # noqa: E402

#: A fresh CSRF token is minted per request, so two runs of the same unchanged
#: page differ by ~64 random characters in three places. Masking it is what makes
#: "byte-identical" a claim that can be true at all -- without this every diff is
#: dominated by noise and the real differences hide inside it.
#:
#: **The home page's greeting is the second source, found by Plan 88-02 the hard
#: way.** 88-01's version of this file asserted the CSRF token was the ONLY
#: nondeterminism; `config.views.index` also stamps "Good morning / afternoon /
#: evening" from the wall clock, so a before-capture and an after-capture taken
#: either side of noon or 5pm differ on a line no code change touched. The
#: convergence control does not catch it -- two runs a second apart agree
#: perfectly -- and a plan whose deliverable is a byte diff would spend its
#: credibility explaining a false positive.
MASKS = (
    (re.compile(r'("X-CSRFToken": ")[A-Za-z0-9]+(")'), r"\1<CSRF-MASKED>\2"),
    (re.compile(r'(name="csrfmiddlewaretoken" value=")[A-Za-z0-9]+(")'),
     r"\1<CSRF-MASKED>\2"),
    (re.compile(r'("home-hero-greeting">)Good (?:morning|afternoon|evening)(<)'),
     r"\1<GREETING-MASKED>\2"),
)


def _mask_csrf(body: str) -> str:
    """Blank out everything that changes between two runs of unchanged code."""
    for pattern, replacement in MASKS:
        body = pattern.sub(replacement, body)
    return body


#: Pages that render meaningfully against an EMPTY database. Plan 88-02 widened
#: this list from 88-01's six: the demotion guards templates on the map, the
#: accounting dashboard, the setup wizard, drinking water and the shared-supply
#: check, and a proof that does not render a page cannot say anything about it.
PAGES = (
    ("index-anon", "/", False),
    ("home-auth", "/", True),
    ("getting-started", "/help/getting-started/", True),
    ("reports", "/reporting/reports/", True),
    ("generate-gears", "/reporting/reports/generate/?type=gears", True),
    ("generate-calwatrs", "/reporting/reports/generate/?type=calwatrs", True),
    ("map", "/map/", True),
    ("accounting-dashboard", "/accounting/dashboard/", True),
    ("setup-wizard", "/setup/", True),
    ("drinking-overview", "/drinking/", True),
    ("shared-supply-check", "/reporting/reports/shared-supply-check/", True),
)

#: Detail panes need a row to have a primary key at all, so they cannot be
#: reached from the empty-database pass above -- which is exactly the blind spot
#: Phase 82 named and 88-01 inherited. The rows are built with explicit literal
#: values rather than factory sequences so two runs produce the same bytes.
def _seed_detail_rows():
    """Minimal deterministic rows: one parcel, one well, one link between them.

    Returns the paths to render. Deliberately small -- the point is to reach
    ``parcels/partials/_detail_pane.html``'s Related Wells card, which reverses
    into ``wells`` and is one of the twelve sites this plan guards.
    """
    from decimal import Decimal

    from django.contrib.gis.geos import MultiPolygon, Point, Polygon

    from parcels.models import Parcel
    from wells.models import Well, WellIrrigatedParcel, WellType

    square = MultiPolygon(
        Polygon(
            ((-120.0, 37.0), (-120.0, 37.01), (-119.99, 37.01), (-119.99, 37.0), (-120.0, 37.0))
        )
    )
    parcel = Parcel.objects.create(
        parcel_number="APN-BASELINE",
        owner_name="Baseline Owner",
        area_acres=Decimal("80.00"),
        geometry=square,
        status="active",
    )
    well_type = WellType.objects.create(name="Baseline Well Type")
    well = Well.objects.create(
        name="Baseline Well",
        well_type=well_type,
        location=Point(-119.995, 37.005),
        status="active",
    )
    WellIrrigatedParcel.objects.create(well=well, parcel=parcel, fraction=Decimal("1.0000"))
    return (
        ("parcel-detail", f"/parcels/{parcel.pk}/", True),
        ("parcel-detail-pane", f"/parcels/{parcel.pk}/", True),
    )


def _write(outdir, label, response):
    body = _mask_csrf(response.content.decode("utf-8", errors="replace"))
    with open(os.path.join(outdir, f"{label}.html"), "w") as handle:
        handle.write(f"<!-- status: {response.status_code} -->\n")
        handle.write(body)


def main(outdir):
    os.makedirs(outdir, exist_ok=True)

    setup_test_environment()
    old_name = connection.creation.create_test_db(verbosity=0, autoclobber=True)
    try:
        from core.models import User

        user = User.objects.create_superuser(
            username="baseline", email="baseline@example.com", password="baseline-pass",
        )

        anon = Client()
        auth = Client()
        auth.force_login(user)
        auth.cookies["nav_mode"] = "admin"

        for label, path, needs_auth in PAGES:
            client = auth if needs_auth else anon
            response = client.get(path)
            _write(outdir, label, response)
            print(f"  {label:<22} {path:<48} {response.status_code}")

        for label, path, needs_auth in _seed_detail_rows():
            client = auth if needs_auth else anon
            extra = {"HTTP_HX_REQUEST": "true"} if label.endswith("-pane") else {}
            response = client.get(path, **extra)
            _write(outdir, label, response)
            print(f"  {label:<22} {path:<48} {response.status_code}")
    finally:
        connection.creation.destroy_test_db(old_name, verbosity=0)
        teardown_test_environment()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/render-baseline")
