# SPDX-License-Identifier: AGPL-3.0-or-later
"""
ISS-179: the screen importers commit on every shape, and a failed commit says so.

Four faults, each proven RED against the unfixed code before this plan's fix
(146-01 Task 2; the exact RED quotes live in this phase's EVIDENCE.md):

  (a) `commit_rows` ran `from recharge.models import RechargeSite` before the
      type branch, unconditionally, so a `diversion` (or `well`) commit on any
      deployment that had switched `recharge` off (shapes 1-4) raised
      `RuntimeError` before a single row was looked at. Proven here with a real
      process booted WITHOUT `recharge` in `OPENH2O_MODULES`, because Django's
      app registry is fixed at process start; `override_settings` cannot
      simulate a module actually being gone (see
      tests/test_droppability_acceptance.py's own docstring, which this file's
      spawner/child split copies).
  (b) `infrastructure_import_commit` 500'd on anything that still reached past
      `commit_rows`' own per-row savepoints. HTMX swaps nothing on a 500, so the
      operator saw the SAME mapping table come back with no explanation at all
      (shape 1: three tries; shape 4: two). It must now render 200 with one
      line saying nothing was created and why.
  (c) `?type=parcel` (also `use_area`, `usearea`) fell through `_supported_type`'s
      "unrecognised value" fallback and silently served the Well importer
      (shape 6's own correction). It was made a 404 naming `import_parcels`;
      151.6-06 sends it to the Import use areas page instead.
  (d) The state's own OSWCR well export (`wells-oswcr.csv`, header read
      2026-09-20) matches none of the pre-existing alias spellings, which pins
      the crosswalk aliases added for it.
"""

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.contrib.gis.geos import Point
from django.test import Client
from django.urls import reverse

from core.modules import ALL_MODULE_NAMES
from infrastructure import importer
from infrastructure.views import (
    UNSUPPORTED_IMPORT_TYPE_MESSAGE,
    USE_AREA_IMPORT_TYPE_MESSAGE,
)
from tests.import_flow import infrastructure_import_rows

REPO_ROOT = Path(__file__).resolve().parent.parent


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"iss179user{n}")
    email = factory.Sequence(lambda n: f"iss179user{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# (a) a diversion (or well) commit must not require `recharge`
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_diversion_commit_child():
    """The child half of the without-recharge proof below.

    Also collected (and passes trivially) by the normal full-module suite:
    that run has `recharge` enabled, so it proves nothing about ISS-179 by
    itself. The only run that proves anything is
    `test_diversion_commit_works_without_recharge_module` below, which boots a
    real process with `recharge` OUT of `OPENH2O_MODULES` and points pytest at
    this exact node by name, the same spawner/child split
    tests/test_droppability_acceptance.py uses, for the same reason: Django's
    app registry is fixed at process start, so only a process that never had
    `recharge` installed can prove commit_rows survives without it.
    """
    from surface.models import PointOfDiversion

    results = [
        {
            "index": 0,
            "data": {
                "name": "Fixture POD",
                "location": Point(-120.0, 37.0, srid=4326),
            },
            "errors": [],
            "warnings": [],
        }
    ]
    before = PointOfDiversion.objects.count()
    created = importer.commit_rows(results, "diversion")
    assert created == 1
    assert PointOfDiversion.objects.count() == before + 1


DEFAULT_DATABASE_URL = "postgis://openh2o:openh2o@db:5432/openh2o"


def _database_url(suffix):
    """A DATABASE_URL whose database name is unique to this subprocess.

    Mirrors tests/test_droppability_acceptance.py::_database_url. The parent
    (this test run) is already holding `test_openh2o`, so a child that shares
    the name fails `CREATE DATABASE` before running a single check.
    """
    base = os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    parts = urlsplit(base)
    name = parts.path.lstrip("/") or "openh2o"
    return urlunsplit(parts._replace(path=f"/{name}_{suffix}"))


def test_diversion_commit_works_without_recharge_module():
    """ISS-179's actual fault: a `diversion` commit on a deployment that has
    switched `recharge` off, which is shapes 1 through 4 (every leading shape
    but 5 and 6). `recharge` is the only module dropped; `surface`, which owns
    `PointOfDiversion`, stays, the same as every real shape that hit this bug.

    Run against the UNFIXED importer (`from recharge.models import
    RechargeSite` at the top of `commit_rows`, before the type branch), the
    child process's one test fails with exactly the error the walk logs quote:
    `RuntimeError: Model class recharge.models.RechargeSite doesn't declare an
    explicit app_label and isn't in an application in INSTALLED_APPS`. That RED
    output is quoted verbatim in 146-01-EVIDENCE.md.
    """
    kept = [n for n in ALL_MODULE_NAMES if n != "recharge"]
    env = dict(os.environ)
    env["OPENH2O_MODULES"] = ",".join(kept)
    env["DATABASE_URL"] = _database_url("iss179_no_recharge")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_infrastructure_import_commit.py::test_diversion_commit_child",
            "-q",
            "--ds=config.settings.local",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, (
        "A diversion commit failed on a deployment without `recharge` "
        "(ISS-179).\n"
        f"OPENH2O_MODULES={env['OPENH2O_MODULES']}\n\n"
        f"--- child stdout ---\n{result.stdout}\n"
        f"--- child stderr ---\n{result.stderr}"
    )


# ---------------------------------------------------------------------------
# (b) a commit that raises renders 200 with the unexpected-error sentence, not a 500
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_commit_failure_renders_nothing_was_created(auth_client, monkeypatch, settings):
    """`commit_rows` already isolates a single bad row with its own per-row
    savepoint (see its docstring); this proves the OUTER catch that guards
    against anything else: a module Task 2.1's guard missed, a programming
    error, anything genuinely unexpected. Monkeypatches `commit_rows` itself
    to raise, so this is independent of the recharge-specific fix in (a).

    151.6-03: the commit runs in a worker, so a crash ends in the failed
    status result. The status route answers 200 with the unexpected-error
    sentence and no exception detail, and the stored file is gone.
    """

    def _boom(results, infra_type):
        raise RuntimeError("synthetic outer-path failure")

    monkeypatch.setattr(importer, "commit_rows", _boom)

    rows = [{"name": "Alpha Well", "LAT": "37.20", "LON": "-119.50"}]
    resp = infrastructure_import_rows(
        auth_client,
        rows,
        {"map:name": "name", "map:latitude": "LAT", "map:longitude": "LON"},
    )
    assert resp.status_code == 200, (
        "A commit-time crash must render 200 (HTMX swaps nothing on a 500, "
        "which was the ISS-179 silence), not propagate."
    )
    body = resp.content.decode()
    # 150.1-02 (2026-10-15): the surface imports' unexpected-error sentence,
    # without the exception detail (151.6-03: the detail goes to the log).
    assert (
        "An unexpected error stopped the import, and OpenH2O saved nothing "
        "from this file."
    ) in body
    assert "synthetic outer-path failure" not in body
    assert "RuntimeError" not in body
    assert list((Path(settings.MEDIA_ROOT) / "imports").glob("*")) == []


# ---------------------------------------------------------------------------
# (c) a use-area ?type goes to the Import use areas page; any other
#     unsupported ?type is a 404, never a fallback to a different importer
#     than the one asked for
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("use_area_type", ["parcel", "use_area", "usearea"])
def test_a_use_area_type_goes_to_the_use_area_import_page(auth_client, use_area_type):
    """`?type=parcel` (also `use_area`, `usearea`) once fell through
    `_supported_type`'s unrecognised-value fallback and returned 200 showing
    the Well importer's mapping page, headed "Well"; it was then a 404 naming
    the import_parcels command. Use areas now have their own import page, so
    the old address sends the person there.
    """
    resp = auth_client.get(reverse("infrastructure:import") + f"?type={use_area_type}")
    assert resp.status_code == 302
    assert resp["Location"] == reverse("parcels:use_area_import")


@pytest.mark.django_db
def test_an_unsupported_type_is_404_not_the_well_importer(auth_client):
    resp = auth_client.get(reverse("infrastructure:import") + "?type=nonsense")
    assert resp.status_code == 404
    body = resp.content.decode()
    assert body == UNSUPPORTED_IMPORT_TYPE_MESSAGE
    assert body == "The bulk import page does not import this type."
    assert "import_parcels" not in body


@pytest.mark.django_db
def test_unsupported_type_404_on_commit_too(auth_client):
    """The same guard, exercised on the commit endpoint directly: a
    hand-edited POST naming a type outside `supported_add_types()` must not
    reach `commit_rows` at all."""
    resp = auth_client.post(
        reverse("infrastructure:import_commit"),
        {"infra_type": "parcel", "token": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 404
    assert resp.content.decode() == USE_AREA_IMPORT_TYPE_MESSAGE
    assert resp.content.decode() == (
        "The bulk import page does not import use areas. "
        "Import them on the Import use areas page."
    )


# ---------------------------------------------------------------------------
# (d) the state's own OSWCR export maps without an operator override
# ---------------------------------------------------------------------------

#: `wells-oswcr.csv`'s header, read verbatim 2026-09-20 from the shape-4
#: well-registry test dataset (`head -1`). Pasted rather than read at test
#: time: the dataset is kept outside this repository.
OSWCR_HEADER = [
    "WCRNUMBER",
    "LEGACYLOGNUMBER",
    "OWNERASSIGNEDWELLNUMBER",
    "COUNTYNAME",
    "TOWNSHIP",
    "RANGE",
    "SECTION",
    "BASELINEMERIDIAN",
    "DECIMALLATITUDE",
    "DECIMALLONGITUDE",
    "HORIZONTALDATUM",
    "PLANNEDUSEFORMERUSE",
    "B118WELLUSE",
    "TOTALCOMPLETEDDEPTH",
    "CASINGDIAMETER",
    "DATEWORKENDED",
    "DRILLERNAME",
    "DRILLERLICENSENUMBER",
    "RECORDTYPE",
    "APN",
    "wcr_number_shape",
]


def test_oswcr_header_maps_latitude_longitude_and_name():
    """OSWCR carries no well-name column at all (confirmed against the real
    file: `OWNERASSIGNEDWELLNUMBER` is blank on 16 of its 20 rows, so it is
    not a usable name source either). `WCRNUMBER` is the one column present
    and non-blank on every row, so it is the best-guess source for BOTH `name`
    and `wcr_number`, and the mapping step still lets the operator override
    either one.
    """
    mapping = importer.auto_map_columns(OSWCR_HEADER, "well")
    assert mapping["latitude"] == "DECIMALLATITUDE"
    assert mapping["longitude"] == "DECIMALLONGITUDE"
    assert mapping["name"] == "WCRNUMBER"


def test_oswcr_header_also_maps_wcr_number_and_depth():
    """The other two crosswalk aliases Task 2.4 names, pinned separately from
    the narrower (d) so a future alias change to one field doesn't mask a
    regression in the other."""
    mapping = importer.auto_map_columns(OSWCR_HEADER, "well")
    assert mapping["wcr_number"] == "WCRNUMBER"
    assert mapping["depth_ft"] == "TOTALCOMPLETEDDEPTH"
