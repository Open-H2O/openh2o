# SPDX-License-Identifier: AGPL-3.0-or-later
"""ISS-196: one sign rule, said the same way at every door, naming the rows it touched.

The importer's sign convention itself is not changing (146-01 plan, "The
ledger's sign"): SUPPLY rows credit and must be > 0 (`allocation`, `recharge`);
USAGE rows debit and must be <= 0 (`meter_reading`, `et_estimate`,
`surface_diversion`, `calculated`); `manual_entry`, `csv_import` and
`adjustment` carry the sign the operator gives them. What was wrong on shape 6
(145-02 walk, S3) is that the count of coerced rows named none of them, the
importer document stated a different convention than the constraint actually
enforces, and it offered `groundwater, surface water` as example
`source_type` values, neither of which is a real code.

Three things pinned here:

1. `accounting.ledger_words.SOURCE_TYPE_SIGNS` covers every
   `ParcelLedger.SOURCE_TYPE_CHOICES` code, built from the same two sets the
   check constraints enforce -- never a second hand-typed list.
2. `docs/DATA-IMPORT.md`'s sign table cannot drift from that same table: its
   codes and signs are parsed out of the document and compared.
3. Importing the shape-6 district's own ledger file (`ledger.csv`, reproduced
   here verbatim rather than read from the walker's dataset folder, which the
   dev container cannot see -- no bind mount) reports the exact ten rows
   whose sign moved, each with its value before and after; and the ledger
   page's footer sums debits and credits separately rather than as one
   double-counted figure.
"""
import io
import re
from decimal import Decimal
from pathlib import Path

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from accounting.ledger_import import import_ledger_rows
from accounting.ledger_words import SOURCE_TYPE_SIGNS, sign_rule_sentence
from parcels.models import ParcelLedger
from tests.factories import ParcelFactory, WaterTypeFactory

pytestmark = pytest.mark.django_db

DOCS_PATH = Path(__file__).resolve().parent.parent / "docs" / "DATA-IMPORT.md"

# The shape-6 district's own file (`~/Documents/Vadose/Products/openh2o/
# six-shapes-2026-09/datasets/shape-6-district/ledger.csv`), reproduced
# verbatim. Ten parcels, one usage row (`manual_entry`, already negative in
# the file, unconstrained so untouched) and one supply row each (`surface_
# diversion` or `meter_reading`, positive in the file, NON_POSITIVE by the
# ledger's convention, so all ten are sign-normalized). 145-02's walk of
# shape 6 reported exactly "10 row(s) had their sign normalized" and a
# footer of 6,326.01 AF -- both reproduced by the assertions below.
SHAPE_6_LEDGER_CSV = """parcel_number,effective_date,amount_acre_feet,source_type,water_type_code,description
2406970,2025-09-30,-345.82,manual_entry,GW,"Constructed annual usage, 3.0 AF/acre x 115.27 acres (see PROVENANCE)"
2406970,2025-09-30,288.18,surface_diversion,SW,"Constructed annual surface water supply, 2.5 AF/acre x 115.27 acres (see PROVENANCE)"
2417185,2025-09-30,-395.23,manual_entry,GW,"Constructed annual usage, 3.0 AF/acre x 131.74 acres (see PROVENANCE)"
2417185,2025-09-30,329.36,surface_diversion,SW,"Constructed annual surface water supply, 2.5 AF/acre x 131.74 acres (see PROVENANCE)"
2408088,2025-09-30,-544.15,manual_entry,GW,"Constructed annual usage, 3.0 AF/acre x 181.38 acres (see PROVENANCE)"
2408088,2025-09-30,453.46,surface_diversion,SW,"Constructed annual surface water supply, 2.5 AF/acre x 181.38 acres (see PROVENANCE)"
2411754,2025-09-30,-321.28,manual_entry,GW,"Constructed annual usage, 3.0 AF/acre x 107.09 acres (see PROVENANCE)"
2411754,2025-09-30,267.73,surface_diversion,SW,"Constructed annual surface water supply, 2.5 AF/acre x 107.09 acres (see PROVENANCE)"
2415558,2025-09-30,-297.99,manual_entry,GW,"Constructed annual usage, 3.0 AF/acre x 99.33 acres (see PROVENANCE)"
2415558,2025-09-30,248.32,surface_diversion,SW,"Constructed annual surface water supply, 2.5 AF/acre x 99.33 acres (see PROVENANCE)"
2408325,2025-09-30,-180.64,manual_entry,GW,"Constructed annual usage, 3.0 AF/acre x 60.21 acres (see PROVENANCE)"
2408325,2025-09-30,150.53,surface_diversion,SW,"Constructed annual surface water supply, 2.5 AF/acre x 60.21 acres (see PROVENANCE)"
2404516,2025-09-30,-216.14,manual_entry,GW,"Constructed annual usage, 3.0 AF/acre x 72.05 acres (see PROVENANCE)"
2404516,2025-09-30,180.12,surface_diversion,SW,"Constructed annual surface water supply, 2.5 AF/acre x 72.05 acres (see PROVENANCE)"
2420641,2025-09-30,-384.08,manual_entry,GW,"Constructed annual usage, 3.0 AF/acre x 128.03 acres (see PROVENANCE)"
2420641,2025-09-30,320.06,surface_diversion,SW,"Constructed annual surface water supply, 2.5 AF/acre x 128.03 acres (see PROVENANCE)"
2410331,2025-09-30,-347.11,manual_entry,GW,"Constructed annual usage, 3.0 AF/acre x 115.70 acres (see PROVENANCE)"
2410331,2025-09-30,289.26,meter_reading,GW,"Constructed annual groundwater supply, 2.5 AF/acre x 115.70 acres (see PROVENANCE)"
2407519,2025-09-30,-418.12,manual_entry,GW,"Constructed annual usage, 3.0 AF/acre x 139.37 acres (see PROVENANCE)"
2407519,2025-09-30,348.43,surface_diversion,SW,"Constructed annual surface water supply, 2.5 AF/acre x 139.37 acres (see PROVENANCE)"
"""

# (row, source_type, before, after) for the ten rows the file's own supply
# rows land on -- every OTHER row (the ten manual_entry usage rows) is
# already negative and manual_entry carries no sign constraint, so none of
# those ten appear here.
EXPECTED_SIGN_NORMALIZED_ROWS = [
    (3, "surface_diversion", Decimal("288.18"), Decimal("-288.18")),
    (5, "surface_diversion", Decimal("329.36"), Decimal("-329.36")),
    (7, "surface_diversion", Decimal("453.46"), Decimal("-453.46")),
    (9, "surface_diversion", Decimal("267.73"), Decimal("-267.73")),
    (11, "surface_diversion", Decimal("248.32"), Decimal("-248.32")),
    (13, "surface_diversion", Decimal("150.53"), Decimal("-150.53")),
    (15, "surface_diversion", Decimal("180.12"), Decimal("-180.12")),
    (17, "surface_diversion", Decimal("320.06"), Decimal("-320.06")),
    (19, "meter_reading", Decimal("289.26"), Decimal("-289.26")),
    (21, "surface_diversion", Decimal("348.43"), Decimal("-348.43")),
]

SHAPE_6_PARCEL_NUMBERS = [
    "2406970", "2417185", "2408088", "2411754", "2415558",
    "2408325", "2404516", "2420641", "2410331", "2407519",
]


def _login():
    from core.models import User

    user = User.objects.create(
        username="ledgersignreader",
        email="ledgersignreader@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _import_shape_6():
    """Create the parcels and water types the file's rows reference, then
    import it (not dry-run) through the shared service. Self-contained: no
    filesystem or `import_parcels` GDAL parsing needed."""
    for apn in SHAPE_6_PARCEL_NUMBERS:
        ParcelFactory(parcel_number=apn)
    WaterTypeFactory(code="GW")
    WaterTypeFactory(code="SW")
    return import_ledger_rows(io.StringIO(SHAPE_6_LEDGER_CSV))


# ---------------------------------------------------------------------------
# 1. The sign table covers every SOURCE_TYPE_CHOICES code.
# ---------------------------------------------------------------------------


def test_source_type_signs_covers_every_ledger_choice():
    choice_codes = {code for code, _label in ParcelLedger.SOURCE_TYPE_CHOICES}
    assert set(SOURCE_TYPE_SIGNS) == choice_codes


def test_source_type_signs_matches_the_check_constraints():
    # Built from the same two sets the constraints enforce
    # (`parcels/models.py:52-67`); this pins the values, not just the keys.
    assert SOURCE_TYPE_SIGNS["allocation"] == "positive"
    assert SOURCE_TYPE_SIGNS["recharge"] == "positive"
    assert SOURCE_TYPE_SIGNS["meter_reading"] == "negative"
    assert SOURCE_TYPE_SIGNS["et_estimate"] == "negative"
    assert SOURCE_TYPE_SIGNS["surface_diversion"] == "negative"
    assert SOURCE_TYPE_SIGNS["calculated"] == "negative"
    assert SOURCE_TYPE_SIGNS["manual_entry"] == "either"
    assert SOURCE_TYPE_SIGNS["csv_import"] == "either"
    assert SOURCE_TYPE_SIGNS["adjustment"] == "either"


# ---------------------------------------------------------------------------
# 2. docs/DATA-IMPORT.md cannot drift from that same table.
# ---------------------------------------------------------------------------


def test_data_import_doc_sign_table_matches_source_type_signs():
    text = DOCS_PATH.read_text(encoding="utf-8")
    rows = re.findall(
        r"^\| `(\w+)` \| (negative|positive|either) \|$", text, re.MULTILINE
    )
    assert rows, "no `source_type` sign rows found in docs/DATA-IMPORT.md"
    doc_signs = dict(rows)
    assert doc_signs == SOURCE_TYPE_SIGNS


def test_data_import_doc_no_longer_gives_invalid_source_type_examples():
    text = DOCS_PATH.read_text(encoding="utf-8")
    # The bug this closes: the document named "groundwater, surface water" as
    # example source_type values, and neither is a real SOURCE_TYPE_CHOICES
    # code (145-02 walk, S3).
    assert "groundwater, surface water" not in text
    assert "positive = supply, negative = usage" not in text


def test_data_import_doc_carries_the_sign_rule_sentence():
    text = DOCS_PATH.read_text(encoding="utf-8")
    assert sign_rule_sentence() in text


# ---------------------------------------------------------------------------
# 3. The shape-6 ledger names every row whose sign moved, before and after.
# ---------------------------------------------------------------------------


def test_shape_6_import_names_every_sign_normalized_row():
    result = _import_shape_6()

    assert result["created_count"] == 20
    assert result["error_count"] == 0
    assert result["sign_normalized"] == 10

    # RED before this key existed: `sign_normalized_rows` is new.
    reported = [
        (row["row"], row["source_type"], row["before"], row["after"])
        for row in result["sign_normalized_rows"]
    ]
    assert reported == EXPECTED_SIGN_NORMALIZED_ROWS


def test_shape_6_ledger_page_footer_sums_debits_and_credits_separately():
    result = _import_shape_6()
    assert result["created_count"] == 20

    # Every row in this file lands negative once normalized (manual_entry's
    # usage rows were already negative; the ten supply rows all flip to
    # negative too, per the settled convention -- there is no allocation or
    # recharge row in this district's file, so credits is genuinely zero).
    debits = -sum(
        entry.amount_acre_feet
        for entry in ParcelLedger.objects.filter(amount_acre_feet__lt=0)
    )
    credits = sum(
        entry.amount_acre_feet
        for entry in ParcelLedger.objects.filter(amount_acre_feet__gte=0)
    )
    assert debits == Decimal("6326.01")
    assert credits == Decimal("0")

    client = _login()
    resp = client.get(reverse("accounting:ledger_list"), {"period": ""})
    assert resp.status_code == 200
    body = resp.content.decode("utf-8")

    assert sign_rule_sentence() in body
    assert "6,326.01" in body
    assert "+0.00" in body
