# SPDX-License-Identifier: AGPL-3.0-or-later
"""Save what a signed-in operator actually SEES, for the figure ledger.

The ledger's `rendered` column has to be the number on the screen, not the number
a service returns when asked politely. So this fetches each pinned screen as an
authenticated operator and writes the served HTML to disk, exactly as delivered.

**Authentication is reused, never re-solved.** ``scripts/render_crawl.py`` already
handles the three things that make a naive crawl vacuous -- a login that must be
proven live (every data route 302s to the sign-in page, so an anonymous crawler
collects 200s having read the login wall over and over), ``SECURE_SSL_REDIRECT``,
and an ``ALLOWED_HOSTS`` that has never heard of ``testserver``. Its
``_prepare_settings`` and ``_authenticated_client`` are imported here. Copying
them would fork a solved problem and let the two drift.

**This half is allowed to be the application, and only this half.** Reading the
page is not the service checking itself: the rendered HTML is the artifact under
test. The other half of every ledger row -- the recomputation -- runs as SQL on
the host and cannot reach a single line of project code. See
``audit/figure_ledger/sql/README.md``.

**Read-only, and it leaves the database as it found it.** No template gains a
``data-figure`` attribute and no view is touched: instrumenting the page would
change the very output being audited, and would break the byte-diff precedent
``scripts/render_baseline.py`` set in 88-01. ``_authenticated_client`` does write
one throwaway superuser row (that is correct in its own context, a scratch
restore), so this script deletes it again in a ``finally`` and prints the user
count before and after. Every row count in this deployment is pinned at tolerance
zero in ``data/demo/expected_shape.json``.

A non-200 is a FINDING, not a retry. It is recorded and the run carries on -- a
screen that 500s against real rows is exactly the class ISS-091 named.

Run INSIDE the web container, because that is where the framework lives::

    docker compose exec -T web python scripts/figure_capture.py \
        --screens audit/figure_ledger/screens.json \
        --out audit/figure_ledger/rendered \
        --sha "$(git rev-parse HEAD)"

⚠ The web container has NO code bind mount, and that cuts both ways. A new or
edited script is invisible until ``docker compose up -d --build web``; and the
pages this writes land inside the container, not in the working copy. Bring them
back with::

    docker compose cp web:/app/audit/figure_ledger/rendered/. \
        audit/figure_ledger/rendered/
"""

import argparse
import hashlib
import json
import os
import sys

# Run as `python scripts/figure_capture.py`, so sys.path[0] is scripts/ rather
# than the project root -- put the root back or `config` does not import. Same
# repair scripts/render_crawl.py and scripts/render_baseline.py both make.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Importing render_crawl runs django.setup() with the settings module this
# container already exports, and defines the two helpers below.
from render_crawl import _authenticated_client, _prepare_settings  # noqa: E402


def _user_count():
    from core.models import User

    return User.objects.count()


def capture(screens, out_dir, sha):
    """Fetch each screen signed in; return the manifest records."""
    _prepare_settings()

    before = _user_count()
    client, user = _authenticated_client()
    records = []
    try:
        # PROVE the session before trusting anything below. If force_login
        # silently failed, every page would be the sign-in wall answering 200 and
        # this capture would be 80 copies of one page that no ledger row is about.
        probe = client.get("/profile/", secure=True)
        if probe.status_code != 200 or b"/accounts/login/" in probe.content:
            print(
                "  FIGURE CAPTURE COULD NOT AUTHENTICATE. /profile/ answered "
                f"{probe.status_code} and looks like the sign-in wall. Refusing "
                "rather than saving the login page under every screen's name.",
                file=sys.stderr,
            )
            return None
        print(f"  authenticated as {user.username} — /profile/ answers 200")

        os.makedirs(out_dir, exist_ok=True)
        for screen in screens:
            slug = screen["slug"]
            url = screen["url"]
            response = client.get(url, secure=True)
            body = response.content
            path = os.path.join(out_dir, f"{slug}.html")
            with open(path, "wb") as handle:
                handle.write(body)
            record = {
                "slug": slug,
                "url": url,
                "status": response.status_code,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "note": screen.get("note", ""),
                "commit": sha,
            }
            records.append(record)
            flag = "" if response.status_code == 200 else "   <-- FINDING"
            print(f"  {response.status_code}  {len(body):>8,} B  {url}{flag}")
    finally:
        user.delete()
        after = _user_count()
        print(f"  user rows: {before} before, {after} after (throwaway deleted)")
        if after != before:
            print(
                "  WARNING: user count moved. This script must leave the "
                "database exactly as it found it.",
                file=sys.stderr,
            )
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screens", default="audit/figure_ledger/screens.json")
    parser.add_argument("--out", default="audit/figure_ledger/rendered")
    parser.add_argument(
        "--sha",
        default="",
        help="commit the capture ran at; pass `git rev-parse HEAD` from the "
        "host, because the build context excludes .git",
    )
    args = parser.parse_args()

    with open(args.screens) as handle:
        screens = json.load(handle)

    records = capture(screens, args.out, args.sha)
    if records is None:
        return 1

    manifest = os.path.join(args.out, "manifest.json")
    with open(manifest, "w") as handle:
        json.dump(records, handle, indent=2)
        handle.write("\n")
    print(f"  manifest -> {manifest}")

    non_200 = [r for r in records if r["status"] != 200]
    if non_200:
        print(
            f"  {len(non_200)} screen(s) did not answer 200. Recorded, not "
            "retried — each is a ledger finding.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
