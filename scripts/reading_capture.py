# SPDX-License-Identifier: AGPL-3.0-or-later
"""Save what a READER SEES on staging, for later judgement by sub-agents.

This is deliberately a different instrument from ``scripts/figure_capture.py``.
That script runs inside the web container against the Django test client and
writes byte-exact served HTML for the figure ledger's ``rendered`` column -- the
number on the screen has to be the number a service actually delivered, not one
recomputed politely, so it authenticates via ``render_crawl._authenticated_client``
and never touches a browser. This script does the opposite job: it drives a real
Chromium browser (Playwright, sync API) against the live staging host, waits for
client-side rendering (MapLibre canvases, JS-populated tables) to finish, and
captures three artifacts a reader would actually encounter -- a full-page
screenshot, the rendered visible text (``document.body.innerText``), and the
post-JS DOM (``page.content()``). Byte-exact server output and reader-visible
output are different questions; this script answers the second one and leaves
the first to ``figure_capture.py``.

**Run from the host** (not inside a container) with the venv that already has
Playwright 1.58 and chromium-1217 installed::

    ~/.venv/bin/python scripts/reading_capture.py \
        --out .planning/phases/140-the-reading-standard/140-01-screens/

Do NOT run ``playwright install`` -- the browser binary is already present and
a reinstall is not needed and not authorized here.

**Authentication is solved once, at the top of the run, and proven before any
capture is trusted.** A wrong field name (this form's identifier field is named
``login``, not ``username`` -- see ``templates/account/login.html``) posts to a
200 re-render of the same login page, which looks identical to a bad password
from the HTTP status alone. So this script asserts two independent things after
submitting the form: the post-submit URL must not still contain
``/accounts/login/``, and a follow-up request to ``/profile/`` must answer 200
in the same browser context. Either failure aborts the whole run before a single
screenshot is taken, rather than silently saving 80 copies of the sign-in wall.

**The staging login is a standing, documented, non-secret credential**, not
something this script is inventing or hardening. MAINTAINER.md lines 17-20:
"Staging login is standing, documented, and NON-SECRET by design... It is
intentionally shareable in plain text -- the Tailscale network is the real
gate." Plain-text defaults below are correct, not a lapse.

**A non-200 (302 included) is a FINDING, not a retry.** Playwright's ``goto``
follows redirects transparently, so the response it hands back is the FINAL
one; the only way to see a 302 is to record the status of the first response
whose URL matches the requested URL, via a ``page.on("response", ...)``
listener installed before ``goto``. This script does that and still writes the
three capture files for whatever page rendered at the end of the chain -- the
point is to record what happened, not to paper over it.

**Signed-out pages need their own browser context.** Census rows in the
``/accounts/...`` family (login, logout, signup, password reset) are meant to
be read as an anonymous visitor would see them, so they are captured in a
second, fresh ``browser.new_context()`` that never sees the authenticated
cookie jar -- reusing the signed-in context would show the wrong audience the
wrong page.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright

# Staging's standing, documented, non-secret login -- see the module docstring
# and MAINTAINER.md lines 17-20 ("do not treat it as a secret").
DEFAULT_BASE = "https://butler.tail7ae369.ts.net"
DEFAULT_LOGIN = "admin@staging.local"
DEFAULT_PASSWORD = "staging-demo-2026"
DEFAULT_CENSUS = (
    ".planning/phases/137-water-balance-panel-and-page-pass/137-03-census.json"
)

VIEWPORT = {"width": 1440, "height": 900}
NETWORKIDLE_TIMEOUT_MS = 30_000
POST_LOAD_WAIT_MS = 800

# Rows in this family are captured signed OUT, in a fresh context -- see the
# "Signed-out pages need their own browser context" section of the docstring.
SIGNED_OUT_PATH_PREFIX = "/accounts/"


def slugify(pinned_url):
    """Turn a pinned URL into a filename slug.

    ``/accounting/dashboard/?period=2`` -> ``accounting-dashboard-period-2``
    ``/surface/`` -> ``surface``
    """
    slug = pinned_url.strip("/")
    slug = re.sub(r"[/?=&]+", "-", slug)
    slug = slug.strip("-")
    return slug or "root"


def load_census(path, only):
    with open(path) as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise SystemExit(f"census {path} is not a JSON list")
    for row in rows:
        if "n" not in row or "pinned_url" not in row:
            raise SystemExit(f"census row missing n/pinned_url: {row}")
    if only is not None:
        wanted = set(only)
        rows = [row for row in rows if row["n"] in wanted]
    return rows


def staging_commit():
    staging_path = os.path.expanduser("~/openh2o-staging")
    if not os.path.isdir(staging_path):
        return None
    try:
        result = subprocess.run(
            ["git", "-C", staging_path, "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
        return None


def sign_in(context, base, login, password):
    """Sign in once. Returns nothing; raises SystemExit with a clear message
    and exit code 2 if either post-login assertion fails."""
    page = context.new_page()
    login_url = base.rstrip("/") + "/accounts/login/"
    page.goto(login_url, wait_until="networkidle")
    page.fill('input[name="login"]', login)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"], input[type="submit"]')
    page.wait_for_load_state("networkidle")

    post_login_url = page.url
    if "/accounts/login/" in post_login_url:
        page.close()
        raise SystemExit(
            "LOGIN FAILED (assertion a): post-login URL still contains "
            f"/accounts/login/ -- got {post_login_url!r}. This looks like a "
            "200 re-render of the sign-in form, not a real login. Not "
            "capturing anything. Did not create an account or try a "
            "different password."
        )

    profile_url = base.rstrip("/") + "/profile/"
    profile_response = page.goto(profile_url, wait_until="networkidle")
    profile_status = profile_response.status if profile_response else None
    if profile_status != 200:
        page.close()
        raise SystemExit(
            "LOGIN FAILED (assertion b): /profile/ answered "
            f"{profile_status!r} in the post-login context, not 200. "
            f"post-login URL was {post_login_url!r}. Not capturing "
            "anything. Did not create an account or try a different "
            "password."
        )

    page.close()
    return post_login_url, profile_status


def capture_one(context, base, row, out_dir):
    pinned_url = row["pinned_url"]
    full_url = base.rstrip("/") + pinned_url
    n = row["n"]
    slug = slugify(pinned_url)

    page = context.new_page()
    page.set_viewport_size(VIEWPORT)

    # Record the FIRST response for the requested URL -- goto() follows
    # redirects and hands back the final response, so a 302 is only visible
    # here. See the docstring's "non-200 is a FINDING" section.
    first_status = {}

    def on_response(response):
        if response.url == full_url and "status" not in first_status:
            first_status["status"] = response.status

    page.on("response", on_response)

    note = row.get("note", "")
    final_url = full_url
    try:
        response = page.goto(full_url, wait_until="networkidle", timeout=NETWORKIDLE_TIMEOUT_MS)
        final_url = page.url
        if response is not None:
            status = first_status.get("status", response.status)
        else:
            status = first_status.get("status")
    except Exception as exc:  # noqa: BLE001 -- record and carry on, per spec
        final_url = page.url
        status = first_status.get("status")
        note = (note + "; " if note else "") + f"networkidle timeout: {exc}"

    page.wait_for_timeout(POST_LOAD_WAIT_MS)

    png_name = f"{n:02d}-{slug}.png"
    txt_name = f"{n:02d}-{slug}.txt"
    html_name = f"{n:02d}-{slug}.html"

    png_path = os.path.join(out_dir, png_name)
    txt_path = os.path.join(out_dir, txt_name)
    html_path = os.path.join(out_dir, html_name)

    try:
        page.screenshot(path=png_path, full_page=True)
    except Exception as exc:  # noqa: BLE001
        note = (note + "; " if note else "") + f"screenshot failed: {exc}"

    try:
        visible_text = page.evaluate("document.body.innerText")
    except Exception as exc:  # noqa: BLE001
        visible_text = ""
        note = (note + "; " if note else "") + f"innerText failed: {exc}"
    with open(txt_path, "w") as handle:
        handle.write(visible_text or "")

    try:
        html_content = page.content()
    except Exception as exc:  # noqa: BLE001
        html_content = ""
        note = (note + "; " if note else "") + f"content() failed: {exc}"
    with open(html_path, "w") as handle:
        handle.write(html_content or "")

    page.close()

    record = {
        "n": n,
        "url": pinned_url,
        "status": status,
        "final_url": final_url,
        "files": {"png": png_name, "txt": txt_name, "html": html_name},
    }
    if note:
        record["note"] = note

    print(f"{n:02d}  {status}  {pinned_url}")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--census", default=DEFAULT_CENSUS)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--login", default=DEFAULT_LOGIN)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--only",
        default=None,
        help="comma-separated census numbers to restrict to, e.g. 1,10,48",
    )
    args = parser.parse_args()

    only = None
    if args.only:
        only = [int(x) for x in args.only.split(",") if x.strip()]

    rows = load_census(args.census, only)
    os.makedirs(args.out, exist_ok=True)

    signed_out_rows = [r for r in rows if r["pinned_url"].startswith(SIGNED_OUT_PATH_PREFIX)]
    signed_in_rows = [r for r in rows if not r["pinned_url"].startswith(SIGNED_OUT_PATH_PREFIX)]

    entries = []
    login_proof = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()

        # --- signed-in context ---
        if signed_in_rows:
            signed_in_context = browser.new_context(viewport=VIEWPORT)
            post_login_url, profile_status = sign_in(
                signed_in_context, args.base, args.login, args.password
            )
            login_proof = {
                "post_login_url": post_login_url,
                "profile_status": profile_status,
            }
            print(f"signed in OK -- post-login URL {post_login_url!r}, /profile/ -> {profile_status}")
            for row in signed_in_rows:
                entries.append(capture_one(signed_in_context, args.base, row, args.out))
            signed_in_context.close()

        # --- signed-out context (fresh, never authenticated) ---
        if signed_out_rows:
            signed_out_context = browser.new_context(viewport=VIEWPORT)
            for row in signed_out_rows:
                entries.append(capture_one(signed_out_context, args.base, row, args.out))
            signed_out_context.close()

        browser.close()

    entries.sort(key=lambda e: e["n"])

    manifest = {
        "base": args.base,
        "captured_at": datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(),
        "commit": staging_commit(),
        "login_proof": login_proof,
        "entries": entries,
    }
    manifest_path = os.path.join(args.out, "manifest.json")
    with open(manifest_path, "w") as handle:
        json.dump(manifest, handle, indent=2)
    print(f"wrote {manifest_path}")


if __name__ == "__main__":
    main()
