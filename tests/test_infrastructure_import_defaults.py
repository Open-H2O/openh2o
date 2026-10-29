# SPDX-License-Identifier: AGPL-3.0-or-later
"""The infrastructure import: the site type a file without that column gets,
and what the page's column table says about the three location fields."""

import pytest

from infrastructure import importer

MAPPING = {"name": "name", "latitude": "lat", "longitude": "lon"}


def _validate(infra_type, extra_cols=None, mapping=None):
    row = {"name": "Pond A", "lat": "36.5", "lon": "-119.5", **(extra_cols or {})}
    return importer.validate_rows(
        [row], mapping or MAPPING, infra_type, set(), set()
    )


def test_storage_file_without_a_site_type_column_defaults_to_storage_pond():
    result = _validate("storage")[0]
    assert result["errors"] == []
    assert result["data"]["site_type"] == "storage_pond"


def test_storage_file_keeps_a_site_type_it_names():
    result = _validate(
        "storage", {"kind": "storage_tank"}, {**MAPPING, "site_type": "kind"}
    )[0]
    assert result["data"]["site_type"] == "storage_tank"


def test_recharge_site_file_without_a_site_type_column_leaves_the_model_default():
    result = _validate("recharge_site")[0]
    assert "site_type" not in result["data"]


@pytest.mark.django_db
def test_storage_import_saves_the_row_as_a_storage_pond():
    from recharge.models import RechargeSite

    results = _validate("storage")
    assert importer.commit_rows(results, "storage") == 1
    assert RechargeSite.objects.get(name="Pond A").site_type == "storage_pond"


@pytest.mark.django_db
def test_recharge_import_saves_the_row_as_a_spreading_basin():
    from recharge.models import RechargeSite

    results = _validate("recharge_site")
    assert importer.commit_rows(results, "recharge_site") == 1
    assert RechargeSite.objects.get(name="Pond A").site_type == "spreading_basin"


def test_site_type_sentence_names_the_default_for_each_type():
    holds = importer.FIELD_HOLDS["site_type"]
    assert "storage_pond for a storage pond file" in holds
    assert "spreading_basin for a recharge site file" in holds


def test_location_fields_say_what_makes_them_optional():
    notes = importer.REQUIRED_NOTE
    assert notes["latitude"] == "Unless the file has a geometry"
    assert notes["longitude"] == "Unless the file has a geometry"
    assert notes["geometry"] == "Unless the file has latitude and longitude"
    assert "name" not in notes
