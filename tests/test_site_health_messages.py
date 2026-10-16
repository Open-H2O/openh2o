# SPDX-License-Identifier: AGPL-3.0-or-later
"""Site health's sentences Brent approved (150.1-02 screen 16, message A,
2026-10-16 06:39): the page, the not-applicable sentence, and the database,
disk and database-name checks. Code change: the card heading Docker reads
Database name (the check reads the database's name).
"""
from collections import namedtuple
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from health import checks
from health.models import HealthCheckResult

pytestmark = pytest.mark.django_db

ALL = [c[0] for c in HealthCheckResult.CATEGORY_CHOICES]


def _persist(status_for=lambda c: "green"):
    for c in ALL:
        HealthCheckResult.objects.create(category=c, status=status_for(c), message=f"{c} probe")


def _signed_in():
    user = get_user_model().objects.create(username="hc-msg", email="hc-msg@example.com", is_active=True)
    client = Client()
    client.force_login(user)
    return client


def test_page_words():
    _persist(lambda c: "yellow" if c == "disk" else ("skipped" if c == "pod_fractions" else "green"))
    html = _signed_in().get(reverse("health:dashboard")).content.decode().replace("&#x27;", "'")
    assert (
        f"This page shows the latest result of each of OpenH2O's {len(ALL)} checks on "
        "this site's records and server."
    ) in html
    assert (
        "A check that does not apply to this site reports not applicable, and OpenH2O "
        "leaves it out of the counts on this page."
    ) in html
    n = len(ALL) - 1
    assert html.count(f"of {n} checks that apply") == 3
    assert "judged by their own rules" not in html and "checks marked" not in html
    assert "This fault is on the server, outside OpenH2O." in html
    assert "Database name" in html and ">\n                    Docker" not in html


def test_none_not_applicable_and_signed_out():
    _persist(lambda c: "yellow" if c == "disk" else "green")
    html = _signed_in().get(reverse("health:dashboard")).content.decode()
    assert '<span class="value-empty">None</span>' in html
    out = Client().get(reverse("health:dashboard")).content.decode()
    assert "Overall status: attention needed" in out
    assert "Sign in to see each check." in out


def test_no_checks_yet():
    html = _signed_in().get(reverse("health:dashboard")).content.decode()
    assert "OpenH2O has not checked this site yet." in html
    assert "Run the checks with the <code" in html and "run_health_checks</code> command." in html


def test_not_applicable_sentence():
    assert checks.not_applicable("pod_fractions", "surface", "x")["message"] == (
        "This site has turned off OpenH2O's surface water records, so this check does not apply."
    )


def test_database_sentence():
    msg = checks.check_database()["message"]
    assert msg.startswith("OpenH2O reached the database")
    assert msg.endswith(".") and "Connected" not in msg
    assert checks._and(["76 use areas", "45 wells", "2,080 ledger entries"]) == (
        "76 use areas, 45 wells and 2,080 ledger entries"
    )
    assert checks._count(2080, "ledger entry", "ledger entries") == "2,080 ledger entries"
    with mock.patch.object(checks.connection, "ensure_connection", side_effect=Exception("refused")):
        assert checks.check_database()["message"] == "OpenH2O cannot reach the database. Details: refused"


Usage = namedtuple("Usage", "total used free")
GB = 1024**3


def test_disk_sentences():
    with mock.patch.object(checks.shutil, "disk_usage", return_value=Usage(100 * GB, 41.8 * GB, 58.2 * GB)):
        assert checks.check_disk()["message"] == "The server's disk is 41.8% full, with 58.2 GB free."
    with mock.patch.object(checks.shutil, "disk_usage", return_value=Usage(100 * GB, 85 * GB, 15 * GB)):
        r = checks.check_disk()
        assert r["status"] == "yellow"
        assert r["message"] == (
            "The server's disk is 85.0% full, with 15.0 GB free. OpenH2O asks for attention "
            "when the disk is over 80% full and for action when it is over 90% full."
        )
    with mock.patch.object(checks.shutil, "disk_usage", side_effect=OSError("no such path")):
        assert checks.check_disk()["message"] == "OpenH2O cannot read the disk's size. Details: no such path"


def test_database_name_sentences():
    from django.conf import settings

    name = settings.DATABASES["default"]["NAME"]
    r = checks.check_docker()
    assert dict(HealthCheckResult.CATEGORY_CHOICES)["docker"] == "Database name"
    assert r["message"] in (
        f"OpenH2O is connected to {name}, the database named in OpenH2O's settings.",
        # pytest-django runs on test_<name>, which the settings do not name.
        f"OpenH2O is connected to test_{name}, but the database named in OpenH2O's settings is {name}.",
    )
