# SPDX-License-Identifier: AGPL-3.0-or-later
"""The parcel download asks for the parcel IDs first, then the parcels 1,000 at a time.

DWR's LightBox parcel layer pages wrong by offset (measured 2026-11-15): asked the
way OpenH2O used to ask, it handed back 16, 8, 7 and 5 overlapping parcels and then
empty pages, so the Merced Subbasin failed 3 of 3 times. Asked for the IDs first, it
gave all 57,306 in 52 s. These tests hold the new route, the acreage saved with
each parcel, the district's own list of parcel numbers and the words the command
prints (approved word for word on 2026-11-15).
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from geography.models import Boundary
from parcels.models import Parcel
from parcels.signals import _compute_area_acres
from tests.lightbox_fake import FakeLightBox, apn_of, boundary_geometry, ring_of

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_backoff_sleep(monkeypatch):
    monkeypatch.setattr("geography.services.arcgis.time.sleep", lambda s: None)


@pytest.fixture
def boundary():
    return Boundary.objects.create(name="Merced Test Subbasin", geometry=boundary_geometry())


def run(boundary, fake, *extra, **options):
    out = StringIO()
    with patch("geography.services.arcgis.requests.post", side_effect=fake.post):
        call_command("auto_populate", "--boundary", str(boundary.pk), "--steps", "parcels",
                     *extra, stdout=out, **options)
    return out.getvalue()


def run_failing(boundary, fake, *extra):
    out = StringIO()
    with patch("geography.services.arcgis.requests.post", side_effect=fake.post):
        with pytest.raises(CommandError):
            call_command("auto_populate", "--boundary", str(boundary.pk), "--steps", "parcels",
                         *extra, stdout=out)
    return out.getvalue()


def list_file(tmp_path, text, name="parcels.csv"):
    path = tmp_path / name
    path.write_text(text)
    return str(path)


# -- The route: IDs first, then batches of 1,000; never by offset -------------------


def test_every_parcel_the_ids_list_names_is_saved_and_none_by_offset(boundary):
    fake = FakeLightBox(count=2500)
    out = run(boundary, fake)
    assert Parcel.objects.count() == 2500
    assert fake.ids_calls == 1
    assert fake.batch_calls == 3
    assert fake.offset_calls == 0
    assert "Batch 1 of 3: 1,000 new use areas, 0 already on file" in out
    assert "OpenH2O saved 2,500 new use areas." in out


def test_a_short_batch_is_asked_again(boundary):
    fake = FakeLightBox(count=2500, short={2: 1})
    run(boundary, fake)
    assert Parcel.objects.count() == 2500
    assert fake.batch_calls == 4


def test_a_batch_short_every_time_stops_naming_the_batch(boundary):
    fake = FakeLightBox(count=2500, short={2: "always"})
    out = run_failing(boundary, fake)
    assert Parcel.objects.count() == 1000
    assert ("After 6 attempts, DWR's parcel map had returned only 999 of the 1,000 parcels "
            "OpenH2O asked for in batch 2 of 3.") in out
    assert "Run the same command again to add the rest. OpenH2O saves only the parcels that are not yet on file." in out
    # The closing count is the rows written (it once said 0 when 15 were).
    assert "1000 record(s) created before the failure(s)" in out
    assert "--resume-from" not in out.split("parcels failed")[1].split("\n")[0]


def test_an_error_on_every_attempt_names_the_batch_and_the_code(boundary):
    fake = FakeLightBox(count=1500)
    calls = {"n": 0}
    real = fake.post

    def post(url, data=None, timeout=None):
        if "objectIds" in (data or {}) and str(data["objectIds"]).startswith("1001"):
            calls["n"] += 1
            from tests.lightbox_fake import _response
            return _response({"error": {"code": 500, "message": "Error performing query operation"}})
        return real(url, data=data, timeout=timeout)

    fake.post = post
    out = run_failing(boundary, fake)
    assert calls["n"] == 6
    assert ("DWR's parcel map returned error 500 on all 6 attempts at batch 2 of 2: "
            "Error performing query operation.") in out


def test_a_second_run_after_a_stop_saves_only_what_is_missing(boundary):
    run_failing(boundary, FakeLightBox(count=2500, short={2: "always"}))
    out = run(boundary, FakeLightBox(count=2500))
    assert Parcel.objects.count() == 2500
    assert "OpenH2O saved 1,500 new use areas." in out
    assert "1,000 other parcels were already use areas on this site." in out


def test_resume_from_skips_the_ids_at_or_below_it(boundary):
    out = run(boundary, FakeLightBox(count=2500), "--resume-from", "1000")
    assert Parcel.objects.count() == 1500
    assert not Parcel.objects.filter(parcel_number=apn_of(1000)).exists()
    assert Parcel.objects.filter(parcel_number=apn_of(1001)).exists()
    assert "OpenH2O saved 1,500 new use areas." in out


def test_a_run_that_finds_nothing_new_says_so(boundary):
    run(boundary, FakeLightBox(count=1200))
    out = run(boundary, FakeLightBox(count=1200))
    assert Parcel.objects.count() == 1200
    assert ("OpenH2O did not save any new use areas. 1,200 parcels were already use areas "
            "on this site.") in out


def test_the_closing_line_counts_the_rows_written(boundary):
    out = run(boundary, FakeLightBox(count=1200))
    assert "Done. 1200 total record(s) created." in out


def test_dry_run_saves_nothing_and_counts_per_batch(boundary):
    out = run(boundary, FakeLightBox(count=1200), dry_run=True)
    assert Parcel.objects.count() == 0
    assert "Batch 1 of 2: would save 1000 new use areas" in out.replace(",", "")


# -- Acreage in the same save ------------------------------------------------------------


def test_every_saved_parcel_has_the_receivers_acreage(boundary):
    run(boundary, FakeLightBox(count=1200))
    assert not Parcel.objects.filter(area_acres__isnull=True).exists()
    for parcel in Parcel.objects.order_by("?")[:25]:
        assert parcel.area_acres == _compute_area_acres(parcel.pk)
        assert parcel.area_acres > Decimal("0")


def test_recalc_fills_only_empty_acreage_that_is_not_an_override():
    from django.contrib.gis.geos import MultiPolygon, Polygon
    shape = MultiPolygon(Polygon(ring_of(5)))
    empty = Parcel.objects.create(parcel_number="EMPTY-1", geometry=shape)
    Parcel.objects.filter(pk=empty.pk).update(area_acres=None)
    kept = Parcel.objects.create(parcel_number="KEPT-1", geometry=shape)
    Parcel.objects.filter(pk=kept.pk).update(area_acres=Decimal("5.00"))
    override = Parcel.objects.create(parcel_number="OVER-1", geometry=shape, area_override=True)
    Parcel.objects.filter(pk=override.pk).update(area_acres=None)

    out = StringIO()
    call_command("recalc_parcel_areas", stdout=out)

    empty.refresh_from_db()
    kept.refresh_from_db()
    override.refresh_from_db()
    assert empty.area_acres == _compute_area_acres(empty.pk)
    assert kept.area_acres == Decimal("5.00")
    assert override.area_acres is None
    assert "Updated 1 parcel(s)." in out.getvalue()


# -- Parcels left out, and numbers on several outlines ----------------------------------


def test_parcels_with_no_number_or_no_outline_are_left_out_and_counted(boundary):
    fake = FakeLightBox(count=1200, apns={3: "", 4: None}, no_outline={9})
    out = run(boundary, fake)
    assert Parcel.objects.count() == 1197
    assert ("OpenH2O left out 2 parcels without a parcel number and 1 whose outline it "
            "cannot read.") in out


def test_a_number_on_several_outlines_is_saved_once_and_counted(boundary):
    # OBJECTIDs 1,500 and 2,400 repeat the number of OBJECTID 10, in later batches.
    fake = FakeLightBox(count=2500, apns={1500: apn_of(10), 2400: apn_of(10)})
    out = run(boundary, fake)
    assert Parcel.objects.count() == 2498
    assert Parcel.objects.filter(parcel_number=apn_of(10)).count() == 1
    assert ("DWR's map has 2 duplicate records of 1 parcel number. OpenH2O saved one use "
            "area for each number.") in out
    # A repeat inside this download is never counted as already on file.
    assert "already use area" not in out.split("OpenH2O saved")[1]


def test_a_use_area_on_file_with_dashes_counts_as_already_on_file(boundary):
    from django.contrib.gis.geos import MultiPolygon, Polygon
    for oid in (3, 4):
        Parcel.objects.create(parcel_number="0000-0000-000" + str(oid),
                              geometry=MultiPolygon(Polygon(ring_of(oid))))
    out = run(boundary, FakeLightBox(count=1200))
    assert Parcel.objects.count() == 1200
    assert not Parcel.objects.filter(parcel_number=apn_of(3)).exists()
    assert "2 other parcels were already use areas on this site." in out


def test_a_download_that_finds_no_parcels_says_so(boundary):
    out = run(boundary, FakeLightBox(none_found=True))
    assert Parcel.objects.count() == 0
    assert ("DWR's parcel map has no parcels that overlap this boundary. The map covers "
            "California only. For land outside California, load your parcel outlines with "
            "Import use areas on the Use Areas page.") in out


def test_a_refused_request_says_a_second_try_repeats_it(boundary):
    fake = FakeLightBox(ids_error={"code": 400, "message": "Failed to execute query."})
    out = run_failing(boundary, fake)
    assert fake.ids_calls == 1
    assert ("DWR's parcel map returned this error: Failed to execute query. Running the "
            "step again will return the same error.") in out


# -- The district's own list --------------------------------------------------------------


def test_a_list_keeps_only_its_numbers_and_names_the_ones_not_found(boundary, tmp_path):
    path = list_file(tmp_path, "Account,APN\nA-1,0000-0000-0001\nA-2,000000000002\n"
                               "A-3,00000000007ab\nA-4,900-000-001-000\nA-5,900-000-002-000\n")
    fake = FakeLightBox(count=1200, apns={7: "00000000007AB"})
    out = run(boundary, fake, "--parcel-list", path)
    assert set(Parcel.objects.values_list("parcel_number", flat=True)) == {
        apn_of(1), apn_of(2), "00000000007AB"}
    assert ("Your list holds 5 different parcel numbers. OpenH2O saved 3 of them as new use "
            "areas.") in out
    assert ("2 parcel numbers on your list do not match any parcel that overlaps the boundary: "
            "900-000-001-000, 900-000-002-000.") in out


def test_a_list_with_no_heading_reads_its_first_column_from_the_first_row(boundary, tmp_path):
    path = list_file(tmp_path, "000000000001\n000000000002\n", name="parcels.txt")
    run(boundary, FakeLightBox(count=1200), "--parcel-list", path)
    assert Parcel.objects.count() == 2


def test_a_shorter_county_number_matches_only_exactly(boundary, tmp_path):
    # No public source says 000-000-001 names 000000000001, so it does not match it.
    path = list_file(tmp_path, "APN\n000-000-001\n000000000002\n")
    out = run(boundary, FakeLightBox(count=1200), "--parcel-list", path)
    assert Parcel.objects.count() == 1
    assert "1 parcel number on your list does not match any parcel that overlaps the boundary: 000-000-001." in out


def test_a_listed_number_already_on_file_counts_as_on_file(boundary, tmp_path):
    from django.contrib.gis.geos import MultiPolygon, Polygon
    Parcel.objects.create(parcel_number=apn_of(1), geometry=MultiPolygon(Polygon(ring_of(1))))
    path = list_file(tmp_path, "APN\n000000000001\n000000000002\n")
    out = run(boundary, FakeLightBox(count=1200), "--parcel-list", path)
    assert Parcel.objects.count() == 2
    assert "Your list holds 2 different parcel numbers. OpenH2O saved 1 of them as new use areas." in out
    assert "1 other parcel was already a use area on this site." in out


def test_the_list_option_says_what_it_reads():
    from geography.management.commands.auto_populate import Command
    help_text = " ".join(Command().create_parser("manage.py", "auto_populate").format_help().split())
    assert ("A CSV file of the parcel numbers to save as use areas. OpenH2O reads it the same way "
            "as the list on the Setup Wizard's Populate page. Without this file, OpenH2O saves "
            "every parcel that overlaps the boundary and has a parcel number and an outline.") in help_text
    assert ("Start the flowlines download after the OBJECTID that a failed flowlines download "
            "prints. Use this option only with --steps flowlines.") in help_text


def test_reading_a_list_refuses_a_spreadsheet_and_an_empty_file(tmp_path):
    from parcels.parcel_list import ParcelListError, read_parcel_list

    xlsx = tmp_path / "parcels.xlsx"
    xlsx.write_bytes(b"PK\x03\x04binary")
    with pytest.raises(ParcelListError) as refused:
        with open(xlsx, "rb") as handle:
            read_parcel_list(handle, "parcels.xlsx")
    assert str(refused.value) == "Save parcels.xlsx as a CSV file and choose the CSV file."

    empty = tmp_path / "parcels.csv"
    empty.write_text("APN\n\n")
    with pytest.raises(ParcelListError) as refused:
        with open(empty, "rb") as handle:
            read_parcel_list(handle, "parcels.csv")
    assert str(refused.value) == (
        "OpenH2O did not find any parcel numbers in parcels.csv. Put the numbers in a column "
        "headed APN or Parcel number and choose the file again.")
