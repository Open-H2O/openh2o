# SPDX-License-Identifier: AGPL-3.0-or-later
"""Visitor statistics are off unless a site names its own Umami server.

Until 2026-10-17 the default script address and the Caddyfile's
Content-Security-Policy named the maintainer's own analytics host, so every
installation shipped permission to load it. Both now come from the site's own
environment, and these tests keep any default host from coming back.
"""

from pathlib import Path

import pytest
from django.test import override_settings

ROOT = Path(__file__).resolve().parent.parent
TAG = 'data-website-id="site-123"'


@pytest.mark.django_db
@override_settings(UMAMI_WEBSITE_ID="site-123", UMAMI_SCRIPT_URL="")
def test_no_tag_without_a_script_address(client):
    response = client.get("/about/")
    assert response.status_code == 200
    assert TAG not in response.content.decode()


@pytest.mark.django_db
@override_settings(UMAMI_WEBSITE_ID="site-123", UMAMI_SCRIPT_URL="https://stats.example.org/script.js")
def test_tag_with_both_settings(client):
    response = client.get("/about/")
    page = response.content.decode()
    assert TAG in page
    assert 'src="https://stats.example.org/script.js"' in page


def test_script_address_has_no_default():
    text = (ROOT / "config" / "settings" / "base.py").read_text(encoding="utf-8")
    assert 'UMAMI_SCRIPT_URL = env("UMAMI_SCRIPT_URL", default="")' in text


def test_csp_takes_extra_origins_from_the_environment():
    caddyfile = (ROOT / "Caddyfile").read_text(encoding="utf-8")
    policy = next(line for line in caddyfile.splitlines() if "Content-Security-Policy" in line and "script-src" in line)
    script_src = policy.split("script-src", 1)[1].split(";", 1)[0]
    connect_src = policy.split("connect-src", 1)[1].split(";", 1)[0]
    assert "{$CSP_EXTRA_ORIGINS}" in script_src
    assert "{$CSP_EXTRA_ORIGINS}" in connect_src
    assert "vanderdev" not in caddyfile
    assert "cloudflareinsights" not in policy
