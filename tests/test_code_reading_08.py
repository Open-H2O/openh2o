# SPDX-License-Identifier: AGPL-3.0-or-later
"""Code-reading fixes: the infrastructure import page's column table, two
CONTRIBUTING lines that must match the code, and five small defects.

Each test is its own case; none is pinned to a demonstration figure.
"""

import html as html_lib
import inspect
import json
import re
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client
from django.urls import reverse

from infrastructure import importer
from infrastructure import views as infra_views

REPO = Path(__file__).resolve().parent.parent
IMPORT_TYPES = ("well", "diversion", "recharge_site", "storage")
ROW = re.compile(
    r'<tr>\s*<td class="col-name">(.*?)</td>\s*<td>(.*?)</td>\s*<td>(.*?)</td>\s*</tr>',
    re.S,
)


@pytest.fixture
def client(db):
    user = get_user_model().objects.create_user(
        username="cr-reader", email="cr-reader@example.com", password="x-pass-1234"
    )
    c = Client()
    c.force_login(user)
    return c


def _table_rows(page_html):
    rows = []
    for name, required, holds in ROW.findall(page_html):
        strip = lambda s: html_lib.unescape(re.sub(r"<[^>]+>", "", s)).strip()  # noqa: E731
        rows.append((strip(name), strip(required), strip(holds)))
    return rows


# --- the import page lists each type's columns --------------------------------


@pytest.mark.parametrize("infra_type", IMPORT_TYPES)
def test_import_fields_returns_required_and_puts_required_first(infra_type):
    fields = importer.import_fields(infra_type)
    assert fields, infra_type
    flags = []
    for field, label, required in fields:
        assert label == importer.FIELD_LABELS[field]
        assert isinstance(required, bool)
        flags.append(required)
    assert any(flags) and not all(flags)
    # Every required field comes before every optional one.
    assert flags == sorted(flags, reverse=True)
    names = [field for field, _label, _required in fields]
    assert names[0] == "name"
    assert set(names) == set(importer.ALIASES[infra_type])


@pytest.mark.parametrize("infra_type", IMPORT_TYPES)
def test_import_page_has_one_row_per_field(client, infra_type):
    response = client.get(reverse("infrastructure:import"), {"type": infra_type})
    assert response.status_code == 200
    rows = _table_rows(response.content.decode())
    fields = importer.import_fields(infra_type)
    assert [r[0] for r in rows] == [label for _f, label, _r in fields]
    expected = []
    for field, _label, req in fields:
        if field in importer.REQUIRED_NOTE:
            expected.append(importer.REQUIRED_NOTE[field])
        else:
            expected.append("Yes" if req else "No")
    assert [r[1] for r in rows] == expected
    cells = dict(zip([f for f, _l, _r in fields], [r[1] for r in rows]))
    assert cells["name"] == "Yes"
    assert cells["latitude"] == "Unless the file has a geometry"
    assert cells["longitude"] == "Unless the file has a geometry"
    assert cells["geometry"] == "Unless the file has latitude and longitude"
    assert all(r[2] for r in rows), "every field says what it holds"
    assert not any("The other" in r[0] for r in rows)


def test_import_page_still_requires_login():
    response = Client().get(reverse("infrastructure:import"), {"type": "well"})
    assert response.status_code == 302


def test_mapping_step_still_offers_every_field(client):
    csv_bytes = b"name,lat,lon\nWell A,36.5,-119.5\n"
    from django.core.files.uploadedfile import SimpleUploadedFile

    response = client.post(
        reverse("infrastructure:import_preview"),
        {
            "infra_type": "well",
            "file": SimpleUploadedFile("w.csv", csv_bytes, content_type="text/csv"),
        },
    )
    assert response.status_code == 200
    body = response.content.decode()
    for _field, label, _required in importer.import_fields("well"):
        assert label in body


def test_geometry_col_label_is_gone():
    assert not hasattr(importer, "GEOMETRY_COL_LABEL")


# --- the two CONTRIBUTING lines say what the code does ------------------------


def _contributing():
    return (REPO / "CONTRIBUTING.md").read_text()


def test_contributing_names_the_checks_ci_runs():
    line = next(
        ln for ln in _contributing().splitlines() if "pull request" in ln and "make test" in ln
    )
    assert "ruff check ." in line


def test_contributing_names_what_production_refuses():
    text = _contributing()
    assert "strong database password" not in text
    line = next(ln for ln in text.splitlines() if "production settings" in ln)
    for known in ("openh2o", "postgres", "password", "changeme"):
        assert known in line
    assert "ALLOWED_HOSTS" in line


def test_contributing_says_which_adapters_lack_a_parameter_map():
    import importlib

    from datasync.adapters import ADAPTER_REGISTRY

    importlib.import_module("datasync.adapters.openet")
    importlib.import_module("datasync.adapters.openet_gee")
    lacking = {
        code
        for code, cls in ADAPTER_REGISTRY.items()
        if not hasattr(importlib.import_module(cls.__module__), "PARAMETER_MAP")
    }
    assert lacking == {"openet", "openet_gee"}
    paragraph = next(
        p for p in _contributing().split("\n\n") if "PARAMETER_MAP" in p
    )
    assert "OpenET" in paragraph


# --- five small defects -------------------------------------------------------


def test_unknown_type_post_still_falls_back_and_saves_nothing(client):
    from wells.models import Well

    response = client.post(
        reverse("infrastructure:add"), {"infra_type": "nonsense", "name": "cr-unknown"}
    )
    assert response.status_code == 200
    assert not Well.objects.filter(name="cr-unknown").exists()


def test_add_view_has_no_unreachable_fallback_and_keeps_its_login():
    assert "Invalid infrastructure type" not in inspect.getsource(
        infra_views.infrastructure_add
    )
    anonymous = Client().post(reverse("infrastructure:add"), {"infra_type": "well"})
    assert anonymous.status_code == 302
    assert anonymous["Location"].startswith("/accounts/login") or "login" in anonymous["Location"]


def _feature(apn, x):
    ring = [[[x, 36.5], [x + 0.01, 36.5], [x + 0.01, 36.51], [x, 36.51], [x, 36.5]]]
    return {
        "type": "Feature",
        "properties": {"APN": apn, "OWNER": "Owner"},
        "geometry": {"type": "Polygon", "coordinates": ring},
    }


@pytest.mark.django_db
def test_null_apn_is_skipped_and_named_not_staged_as_none(tmp_path):
    from parcels.models import Parcel, ParcelStaging

    path = tmp_path / "null-apn.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [_feature("CR-GOOD", -119.5), _feature(None, -119.4)],
            }
        )
    )
    out = StringIO()
    call_command("import_parcels", str(path), "--dry-run", stdout=out)
    assert "missing or empty 'APN' field" in out.getvalue()
    assert "0 duplicates skipped, 1 errors" in out.getvalue()
    assert not ParcelStaging.objects.exists()

    out = StringIO()
    call_command("import_parcels", str(path), stdout=out)
    assert list(Parcel.objects.values_list("parcel_number", flat=True)) == ["CR-GOOD"]
    assert "Imported 1 parcels" in out.getvalue()


def test_match_analyte_has_no_write_only_set():
    from drinking import importer as drinking_importer

    assert "new_analyte_names" not in inspect.getsource(drinking_importer)


def test_station_order_does_not_look_up_a_missing_key():
    from datasync import views as datasync_views

    source = inspect.getsource(datasync_views._health_ordered_stations)
    assert "HEALTH_RANK.get(" not in source
