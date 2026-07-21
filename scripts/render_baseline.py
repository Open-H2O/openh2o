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
#: dominated by noise and the real differences hide inside it. Nothing else in
#: these pages is nondeterministic (the scratch database has no rows and no
#: timestamps reach the markup), which is why this is the only mask.
CSRF_PATTERNS = (
    re.compile(r'("X-CSRFToken": ")[A-Za-z0-9]+(")'),
    re.compile(r'(name="csrfmiddlewaretoken" value=")[A-Za-z0-9]+(")'),
)


def _mask_csrf(body: str) -> str:
    for pattern in CSRF_PATTERNS:
        body = pattern.sub(r"\1<CSRF-MASKED>\2", body)
    return body


PAGES = (
    ("index-anon", "/", False),
    ("home-auth", "/", True),
    ("getting-started", "/help/getting-started/", True),
    ("reports", "/reporting/reports/", True),
    ("generate-gears", "/reporting/reports/generate/?type=gears", True),
    ("generate-calwatrs", "/reporting/reports/generate/?type=calwatrs", True),
)


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
            body = _mask_csrf(response.content.decode("utf-8", errors="replace"))
            with open(os.path.join(outdir, f"{label}.html"), "w") as handle:
                handle.write(f"<!-- status: {response.status_code} -->\n")
                handle.write(body)
            print(f"  {label:<20} {path:<45} {response.status_code}")
    finally:
        connection.creation.destroy_test_db(old_name, verbosity=0)
        teardown_test_environment()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/render-baseline")
