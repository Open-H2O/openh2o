# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import accounts: water accounts and their use areas from a spreadsheet.

Each row puts one use area (by its parcel number) in one account (by its account
number). A new account number makes an account with the row's name and contact and
the account type chosen on the preview; an account on file keeps its name and contact.
A use area is assigned with the link the Assign button writes, with no water year, so
no finalized year's lock is ever opened. A use area in another account is not moved.
Nothing is written before Import. ``import_accounts`` runs the same function. The
words asserted are the approved rows.
"""
import re
from datetime import date
from html import unescape

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse, reverse_lazy

from accounting.models import ReportingPeriod, WaterAccount, WaterAccountParcel
from core.models import User
from tests.factories import ParcelFactory, WaterAccountFactory, WaterAccountParcelFactory
from tests.import_flow import csv_text_of, import_and_read, token_of

pytestmark = pytest.mark.django_db

PREVIEW = reverse_lazy("accounting:account_import_preview")
COMMIT = reverse_lazy("accounting:account_import_commit")
MAPPING = {
    "map:parcel_number": "APN", "map:account_number": "Account", "map:account_name": "Name",
    "map:contact_name": "Contact", "map:contact_email": "Email",
}


@pytest.fixture
def site():
    parcels = {n: ParcelFactory(parcel_number=f"061-700-0{n}-000") for n in range(10, 18)}
    dutra = WaterAccountFactory(account_number="EX-1", name="Dutra Farms", contact_name="J. Dutra")
    WaterAccountFactory(account_number="EX-2", name="Halvern Orchards")
    other = WaterAccountFactory(account_number="OTHER-1", name="Silva Family Trust")
    WaterAccountParcelFactory(water_account=other, parcel=parcels[15])
    return {"parcels": parcels, "dutra": dutra, "other": other}


def _row(apn, account, name="", contact="", email=""):
    return {"APN": apn, "Account": account, "Name": name, "Contact": contact, "Email": email}


ROWS = [
    _row("061-700-010-000", "NEW-1", "Rios Ranch", "Ana Rios", "ana@rios.example"),
    _row("061700011000", "NEW-1", "Rios Ranch"),                      # dashes left out: still matches
    _row("061-700-012-000", "EX-1", "Dutra Farms LLC", "Someone Else"),  # account on file, another name
    _row("061-700-017-000", "EX-2", "Halvern Orchards"),               # account on file, same name
    _row("061-700-015-000", "NEW-2", "Silva", "", "not-an-address"),  # use area in another account
    _row("999-999-999-999", "NEW-3", "Ghost Farms"),                   # parcel number not on file
    _row("061-700-013-000", ""),                                       # no account number
    _row("", "NEW-4", "Nobody"),                                       # no parcel number
    _row("061-700-016-000", "NEW-5", ""),                              # new account with no name
    _row("061-700-010-000", "NEW-1", "Rios Ranch"),                    # repeats the first row
    _row("061-700-014-000", "NEW-6", "Lone Oak"),
    _row("061-700-014-000", "NEW-7", "Lone Oak Two"),                  # one use area under two accounts
]


def _text(response):
    """The page's words with the tags out and the spaces collapsed."""
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", response.content.decode()))).strip()


def _client():
    user = User.objects.create_user(
        username="admin", email="admin@example.org", password="x", is_active=True,
        is_staff=True, is_superuser=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _upload(client, rows=ROWS, name="accounts.csv"):
    data = csv_text_of(rows).encode()
    return client.post(PREVIEW, {"file": SimpleUploadedFile(name, data)}, HTTP_HX_REQUEST="true")


def _import(client, preview, unit_kind="farm_unit"):
    return import_and_read(client, COMMIT, token_of(preview), {**MAPPING, "unit_kind": unit_kind})


def _links():
    return set(
        WaterAccountParcel.objects.filter(removed_date__isnull=True)
        .values_list("water_account__account_number", "parcel__parcel_number", "reporting_period_id")
    )


def test_the_preview_counts_and_writes_nothing(site):
    before = (WaterAccount.objects.count(), WaterAccountParcel.objects.count())
    page = _text(_upload(_client()))
    assert (WaterAccount.objects.count(), WaterAccountParcel.objects.count()) == before
    for words in [
        "Match the file's columns",
        "OpenH2O found 12 rows and 5 columns in accounts.csv. Changing a choice updates the counts below.",
        "Choose a type",
        "OpenH2O gives each new account the type you choose here.",
        "What Import would do",
        # Accounts: NEW-1, NEW-2, NEW-3, NEW-4, NEW-6 and NEW-7 are new; EX-1 and EX-2 are on file.
        "6 new accounts Imported",
        "2 accounts already on file Use areas added",
        "1 of these 2 accounts has another name on file. OpenH2O keeps the name and contact on file.",
        "EX-1: Dutra Farms LLC in the file, Dutra Farms on file",
        "1 new account has a contact email that is not a valid address. OpenH2O imports it without the email.",
        "Rows of the file",
        "4 use areas Assigned to their accounts",
        "1 row that repeats an earlier row Unchanged",
        "1 parcel number not on file 999-999-999-999 Not imported",
        "1 use area already in another account 061-700-015-000 in OTHER-1 Not assigned",
        "2 rows for a use area this file puts in two accounts 061-700-014-000 Not imported",
        "1 row without a parcel number Not imported",
        "1 row without an account number Not imported",
        "1 row for a new account without a name NEW-5 Not imported",
        "Import Choose another file",
    ]:
        assert words in page, words


def test_import_makes_accounts_and_assigns_use_areas(site):
    client = _client()
    result = _import(client, _upload(client)).content.decode()
    assert "Import complete" in result
    assert "OpenH2O imported 6 accounts and assigned 4 use areas to their accounts." in result
    assert "OpenH2O left out the 7 rows the preview listed." in result
    rios = WaterAccount.objects.get(account_number="NEW-1")
    assert (rios.name, rios.contact_name, rios.contact_email) == ("Rios Ranch", "Ana Rios", "ana@rios.example")
    assert {a.unit_kind for a in WaterAccount.objects.filter(account_number__startswith="NEW-")} == {"farm_unit"}
    assert not WaterAccount.objects.filter(account_number="NEW-5").exists()
    assert WaterAccount.objects.get(account_number="NEW-2").contact_email == ""
    assert _links() == {
        ("NEW-1", "061-700-010-000", None),
        ("NEW-1", "061-700-011-000", None),
        ("EX-1", "061-700-012-000", None),
        ("EX-2", "061-700-017-000", None),
        ("OTHER-1", "061-700-015-000", None),
    }


def test_an_account_on_file_keeps_its_name_and_contact(site):
    client = _client()
    _import(client, _upload(client))
    site["dutra"].refresh_from_db()
    assert (site["dutra"].name, site["dutra"].contact_name) == ("Dutra Farms", "J. Dutra")


def test_a_use_area_in_another_account_is_not_moved(site):
    client = _client()
    _import(client, _upload(client))
    assert list(
        WaterAccountParcel.objects.filter(parcel=site["parcels"][15]).values_list("water_account__account_number", flat=True)
    ) == ["OTHER-1"]


def test_a_finalized_year_is_named_and_its_lock_never_opened(site):
    ReportingPeriod.objects.create(
        name="WY 2024-2025", start_date=date(2024, 10, 1), end_date=date(2025, 9, 30), is_finalized=True
    )
    client = _client()
    preview = _upload(client)
    assert (
        "WY 2024-2025 is finalized. Its pages keep its figures as filed and show beside them any "
        "figure this import changes."
    ) in preview.content.decode()
    _import(client, preview)
    assert not WaterAccountParcel.objects.filter(reporting_period__is_finalized=True).exists()
    assert ("NEW-1", "061-700-010-000", None) in _links()


def test_import_with_new_accounts_and_no_type_is_refused(site):
    client = _client()
    preview = _upload(client)
    pressed = client.post(COMMIT, {"token": token_of(preview), **MAPPING, "unit_kind": ""}, HTTP_HX_REQUEST="true")
    assert "Choose the account type for the new accounts." in pressed.content.decode()
    assert not WaterAccount.objects.filter(account_number="NEW-1").exists()


def test_a_second_import_of_the_same_file_writes_nothing_new(site):
    client = _client()
    _import(client, _upload(client))
    accounts, links = WaterAccount.objects.count(), _links()
    preview = _upload(client)
    if "OpenH2O has nothing to import from this file." not in preview.content.decode():
        _import(client, preview)
    assert WaterAccount.objects.count() == accounts
    assert _links() == links


def test_the_command_gives_the_screen_result(site, tmp_path, capsys):
    path = tmp_path / "accounts.csv"
    path.write_text(csv_text_of(ROWS))
    call_command(
        "import_accounts", str(path), account_type="farm_unit",
        column=["parcel_number=APN", "account_number=Account", "account_name=Name",
                "contact_name=Contact", "contact_email=Email"],
    )
    out = capsys.readouterr().out
    assert "OpenH2O imported 6 accounts and assigned 4 use areas to their accounts." in out
    assert _links() == {
        ("NEW-1", "061-700-010-000", None),
        ("NEW-1", "061-700-011-000", None),
        ("EX-1", "061-700-012-000", None),
        ("EX-2", "061-700-017-000", None),
        ("OTHER-1", "061-700-015-000", None),
    }


def test_a_dry_run_writes_nothing(site, tmp_path, capsys):
    path = tmp_path / "accounts.csv"
    path.write_text(csv_text_of(ROWS))
    before = (WaterAccount.objects.count(), WaterAccountParcel.objects.count())
    call_command("import_accounts", str(path), account_type="farm_unit", dry_run=True,
                 column=["parcel_number=APN", "account_number=Account", "account_name=Name"])
    assert capsys.readouterr().out.strip().splitlines()[-1] == "Dry run: OpenH2O did not save anything."
    assert (WaterAccount.objects.count(), WaterAccountParcel.objects.count()) == before


def test_a_spreadsheet_file_is_refused(site):
    response = _upload(_client(), name="accounts.xlsx")
    assert "Save accounts.xlsx as CSV and choose the saved file." in response.content.decode()


def test_a_file_with_no_rows_is_refused(site):
    client = _client()
    response = client.post(
        PREVIEW, {"file": SimpleUploadedFile("accounts.csv", b"APN,Account,Name\n")}, HTTP_HX_REQUEST="true"
    )
    assert (
        "OpenH2O did not find any rows in accounts.csv. Check that the file has a heading row and one "
        "row for each use area, then choose the file again."
    ) in response.content.decode()


def test_the_accounts_page_carries_the_action_and_the_import_page_reads_as_approved(site):
    client = _client()
    assert "Import accounts" in client.get(reverse("accounting:accounts_list")).content.decode()
    page = client.get(reverse("accounting:account_import")).content.decode()
    assert "This page imports water accounts from a spreadsheet and assigns use areas already on file to them." in page
    assert "Accounts and their use areas" in page
    assert "On the preview you choose the account type for the new accounts." in page
    assert "Back to Accounts" in page
