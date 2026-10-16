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
        assert checks.check_disk()["message"] == "The disk OpenH2O runs on is 41.8% full, with 58.2 GB free."
    with mock.patch.object(checks.shutil, "disk_usage", return_value=Usage(100 * GB, 85 * GB, 15 * GB)):
        r = checks.check_disk()
        assert r["status"] == "yellow"
        assert r["message"] == (
            "The disk OpenH2O runs on is 85.0% full, with 15.0 GB free. OpenH2O asks for attention "
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


# --- message B (2026-10-16 07:07) -------------------------------------------


def test_ssl_sentences(settings):
    settings.ALLOWED_HOSTS = ["butler", "butler.example.net"]
    settings.SITE_DOMAIN = None
    r = checks.check_ssl()
    assert r["status"] == "skipped"
    assert r["message"] == (
        "OpenH2O has no HTTPS certificate to check, because this site's address "
        "is butler, not a public domain name."
    )
    settings.ALLOWED_HOSTS = ["*"]
    assert checks.check_ssl()["message"] == (
        "This site has no public domain name, so OpenH2O has no HTTPS certificate to check."
    )
    assert checks._is_public_domain("openh2o.com")
    for name in ("butler", "localhost", "127.0.0.1", "box.local", "*", ""):
        assert not checks._is_public_domain(name)
    settings.ALLOWED_HOSTS = ["probe.example.org"]
    with mock.patch.object(checks.socket, "create_connection", side_effect=OSError("timed out")):
        assert checks.check_ssl()["message"] == (
            "OpenH2O cannot read the HTTPS certificate for probe.example.org. Details: timed out"
        )


def test_migrations_sentence():
    assert checks.check_migrations()["message"] == (
        "The database has every update this version of OpenH2O needs."
    )


def _source(code, name, *, synced_hours_ago=None):
    from datetime import timedelta

    from django.utils import timezone

    from datasync.models import DataSource, DataSyncLog

    src = DataSource.objects.create(code=code, name=name, is_active=True)
    if synced_hours_ago is not None:
        log = DataSyncLog.objects.create(data_source=src, status="success")
        DataSyncLog.objects.filter(pk=log.pk).update(
            started_at=timezone.now() - timedelta(hours=synced_hours_ago)
        )
    return src


def test_sync_sentences(settings, monkeypatch):
    from datasync.models import DataSource

    settings.HEALTH_DEMO_MODE = False
    DataSource.objects.update(is_active=False)
    monkeypatch.delenv("CIMIS_API_KEY", raising=False)
    _source("probe_never", "Department of Probe Records")
    _source("probe_old", "PROBE NCEI", synced_hours_ago=84)
    _source("probe_ok", "PROBE OK", synced_hours_ago=2)
    _source("cimis", "CIMIS")
    r = checks.check_sync_freshness()
    assert r["status"] == "red"
    assert r["message"] == (
        "OpenH2O has not synced the Department of Probe Records on this site yet. "
        "OpenH2O last synced PROBE NCEI 3.5 days ago. "
        "OpenH2O asks for attention when a data source last synced more than 48 hours "
        "ago, and for action after 7 days or when it has never synced. "
        "OpenH2O does not count CIMIS, which needs an API key."
    )
    DataSource.objects.filter(code__in=["probe_never", "probe_old"]).update(is_active=False)
    _source("probe_ok2", "PROBE OK TWO", synced_hours_ago=1)
    assert checks.check_sync_freshness()["message"] == (
        "OpenH2O synced each of the 2 data sources in the last 48 hours. "
        "OpenH2O does not count CIMIS, which needs an API key."
    )
    DataSource.objects.update(is_active=False)
    assert checks.check_sync_freshness()["message"] == "No data source is turned on."
    settings.HEALTH_DEMO_MODE = True
    assert checks.check_sync_freshness()["message"] == (
        "This demonstration site restores its data every night, so OpenH2O does not "
        "check how recently each data source synced."
    )


def test_ledger_and_use_area_sentences():
    r = checks.check_ledger_integrity()
    assert r["status"] == "green"
    assert r["message"].startswith("Every ledger entry belongs to a use area on file.")
    assert dict(HealthCheckResult.CATEGORY_CHOICES)["orphans"] == "Use areas without an account"
    assert checks.check_orphans()["message"] in (
        "Every active use area belongs to a water account.",
    ) or checks.check_orphans()["message"].endswith("have no water account.") \
        or checks.check_orphans()["message"].endswith("has no water account.")


def test_openet_and_share_sentences():
    assert checks.check_cache_duplication()["message"] == (
        "OpenH2O holds one OpenET estimate for each use area and month."
    )
    assert dict(HealthCheckResult.CATEGORY_CHOICES)["pod_fractions"] == "Point of diversion shares"
    r = checks.check_pod_fractions()
    assert "split to 100%" not in r["message"]
    assert "lost or invented" not in r["message"]


# --- the AI hand-off (2026-10-16 08:19 and 09:01) ----------------------------


def test_server_fault_line_hands_the_fix_to_the_ai():
    _persist(lambda c: "red" if c == "disk" else "green")
    html = _signed_in().get(reverse("health:dashboard")).content.decode().replace("&#x27;", "'")
    assert (
        "This fault is on the server, outside OpenH2O. Pass this card to the AI that "
        "maintains the site; the fix is in OpenH2O's operator guide."
    ) in html


def test_the_guide_has_a_row_for_every_server_card():
    from pathlib import Path

    from django.conf import settings

    guide = (Path(settings.BASE_DIR) / "docs" / "AI-OPERATOR-GUIDE.md").read_text()
    section = guide.split("## Keeping it running", 1)[1].split("\n## ", 1)[0]
    labels = dict(HealthCheckResult.CATEGORY_CHOICES)
    from health.views import HOST_LEVEL_CATEGORIES

    for category in sorted(HOST_LEVEL_CATEGORIES | {"sync_freshness", "calculation"}):
        assert f"\n| {labels[category]} | " in section, labels[category]
    assert "run_health_checks --json" in section
