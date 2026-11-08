# SPDX-License-Identifier: AGPL-3.0-or-later
"""Sign-in over plain HTTP at an office network address (152-03).

All data here is invented: 192.168.1.40, office@example.org, water.example.org.

The fix lives in Caddy's ``X-Forwarded-Proto`` header, driven by
``OPENH2O_FORWARDED_PROTO`` in the site's ``.env``; Django's trust of that
header (``production.py``) does not change.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, override_settings

from core.identifiers import identifier_for
from tests.factories import WellFactory

REPO_ROOT = Path(__file__).resolve().parent.parent
OFFICE_ENV = {"OPENH2O_FORWARDED_PROTO": "http"}
ENV_WITHOUT_THE_SETTING = {}


def _caddy_environment(site_env):
    """The caddy container's environment, built the way Compose builds it.

    PyYAML is not in the web container, so the ``caddy:`` service's
    ``environment:`` block is read line by line. Each ``NAME: ${NAME:-default}``
    entry takes the site's ``.env`` value, or the default when that is unset or
    empty.
    """
    lines = (REPO_ROOT / "docker-compose.yml").read_text().splitlines()
    start = lines.index("  caddy:")
    resolved, in_env = {}, False
    for line in lines[start + 1:]:
        if re.match(r"^  \S", line):  # next service
            break
        if re.match(r"^    environment:\s*$", line):
            in_env = True
            continue
        if in_env and re.match(r"^    \S", line):  # next key of the service
            break
        entry = re.match(r"^\s{6}(\w+):\s*\$\{(\w+):-(.*)\}\s*$", line)
        if in_env and entry:
            name, var, default = entry.groups()
            resolved[name] = site_env.get(var) or default
    return resolved


def forwarded_proto_caddy_sends(site_env):
    """Resolve the Caddyfile's ``header_up X-Forwarded-Proto`` value."""
    text = (REPO_ROOT / "Caddyfile").read_text()
    value = re.search(r"^\s*header_up X-Forwarded-Proto (\S+)\s*$", text, re.M).group(1)
    placeholder = re.fullmatch(r"\{\$(\w+)(?::([^}]*))?\}", value)
    if not placeholder:
        return value
    name, default = placeholder.groups()
    return _caddy_environment(site_env).get(name) or default or ""


# (a) -----------------------------------------------------------------------


def test_office_env_makes_caddy_send_plain_http():
    assert forwarded_proto_caddy_sends(OFFICE_ENV) == "http"


def test_env_without_the_setting_makes_caddy_send_https():
    assert forwarded_proto_caddy_sends(ENV_WITHOUT_THE_SETTING) == "https"


# (c) -----------------------------------------------------------------------


def _sign_in_and_name_a_record(host, origin_scheme, proto):
    User = get_user_model()
    User.objects.create_user(
        username="office", email="office@example.org", password="Invented-Pass-4417"
    )
    well = WellFactory()
    client = Client(enforce_csrf_checks=True)
    extra = {"HTTP_HOST": host, "HTTP_X_FORWARDED_PROTO": proto}
    login_page = client.get("/accounts/login/", **extra)
    assert login_page.status_code == 200
    token = client.cookies["csrftoken"].value
    response = client.post(
        "/accounts/login/",
        {
            "login": "office@example.org",
            "password": "Invented-Pass-4417",
            "csrfmiddlewaretoken": token,
        },
        HTTP_ORIGIN=f"{origin_scheme}://{host}",
        HTTP_REFERER=f"{origin_scheme}://{host}/accounts/login/",
        **extra,
    )
    request = RequestFactory().get("/", **extra)
    return response, identifier_for(well, request=request)


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["192.168.1.40"],
    CSRF_TRUSTED_ORIGINS=[],
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
    SECURE_SSL_REDIRECT=False,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
)
def test_office_sign_in_over_plain_http_works_and_identifiers_stay_http():
    proto = forwarded_proto_caddy_sends(OFFICE_ENV)
    response, identifier = _sign_in_and_name_a_record("192.168.1.40", "http", proto)
    assert response.status_code == 302
    assert identifier.startswith("http://192.168.1.40/id/")


@pytest.mark.django_db
@override_settings(
    ALLOWED_HOSTS=["water.example.org"],
    CSRF_TRUSTED_ORIGINS=["https://water.example.org"],
    SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True,
    SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
)
def test_guard_encrypted_site_is_left_alone_by_the_fix():
    """Passes on the base too, by design: it guards the case the fix must not change."""
    proto = forwarded_proto_caddy_sends(ENV_WITHOUT_THE_SETTING)
    response, identifier = _sign_in_and_name_a_record("water.example.org", "https", proto)
    assert response.status_code == 302
    assert identifier.startswith("https://water.example.org/id/")


# (b) -----------------------------------------------------------------------


def test_guard_production_still_trusts_forwarded_proto_https():
    """Passes on the base and must keep passing: the fix lives in Caddy's
    header, not in Django's trust."""
    child_env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "DATABASE_URL": "postgis://openh2o:Invented-Db-Pass-90817-xq@db:5432/openh2o",
        "SECRET_KEY": "invented-secret-key-for-a-settings-test-0123456789abcdef0123456789",
        "ALLOWED_HOSTS": "192.168.1.40",
        "SECURE_SSL_REDIRECT": "False",
        "SESSION_COOKIE_SECURE": "False",
        "CSRF_COOKIE_SECURE": "False",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import django; django.setup(); "
            "from django.conf import settings; "
            "print(settings.SECURE_PROXY_SSL_HEADER)",
        ],
        env=child_env,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-1500:]
    assert result.stdout.strip().splitlines()[-1] == "('HTTP_X_FORWARDED_PROTO', 'https')"
