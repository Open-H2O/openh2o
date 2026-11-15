# SPDX-License-Identifier: AGPL-3.0-or-later
"""Import water accounts and the use areas in each from a spreadsheet.

Each row of the CSV file puts one use area (by its parcel number) in one account (by
its account number). The Accounts page's Import accounts and ``manage.py
import_accounts`` call the same functions, so a screen and a command write the same
accounts and links.

The rules:

* A new account number with a name makes an account, with the name and contact of its
  first row and the account type chosen once for the file. An account on file keeps
  its name and contact; a different name in the file is listed.
* A use area is put in its account with the link the Assign button on an account's page
  writes: no water year (``reporting_period`` empty). Every balance reads a link by its
  removed date only (``accounting.services.account_parcel_ids``), and no finalized
  year's lock is opened, because a link with no year belongs to no finalized year.
* A use area in another account is listed and not moved. A parcel number not on file,
  a row without a parcel number or an account number, a new account without a name, a
  use area the file puts in two accounts and a value longer than its field are listed
  and not imported. A row that repeats an earlier one changes nothing.
* Parcel numbers match with or without their dashes, capital letters aside
  (``parcels.parcel_list.normalize``).
* Nothing is written before Import.
"""
import csv
import io
from collections import OrderedDict

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from accounting.models import UNIT_KIND_CHOICES, WaterAccount, WaterAccountParcel
from core import pending_imports
from parcels.models import Parcel
from parcels.parcel_list import NOT_TEXT_EXTENSIONS, normalize

NUMBER_MAX_LENGTH = WaterAccount._meta.get_field("account_number").max_length
NAME_MAX_LENGTH = WaterAccount._meta.get_field("name").max_length
CONTACT_MAX_LENGTH = WaterAccount._meta.get_field("contact_name").max_length

#: The fields a file's columns are matched to, in the preview's order: (field, label, required).
FIELDS = (
    ("parcel_number", "Parcel number", True),
    ("account_number", "Account number", True),
    ("account_name", "Account name", False),
    ("contact_name", "Contact name", False),
    ("contact_email", "Contact email", False),
)

#: Headings (letters only, lower case) each field takes by itself.
HEADINGS = {
    "parcel_number": {"apn", "apns", "parcelnumber", "parcelno", "parcel", "parcelid",
                      "assessorparcelnumber", "assessorsparcelnumber"},
    "account_number": {"account", "accountnumber", "accountno", "accountid", "acct", "acctno",
                       "acctnumber", "wateraccount", "wateraccountnumber"},
    "account_name": {"name", "accountname", "acctname", "wateraccountname", "owner", "ownername"},
    "contact_name": {"contact", "contactname"},
    "contact_email": {"email", "contactemail", "emailaddress"},
}

NO_FILE_MESSAGE = "Choose a file to upload."
NO_TYPE_MESSAGE = "Choose the account type for the new accounts."


def not_csv_message(name):
    return f"Save {name} as CSV and choose the saved file."


def no_rows_message(name):
    return (f"OpenH2O did not find any rows in {name}. Check that the file has a heading row and one "
            "row for each use area, then choose the file again.")


def _letters(text):
    return "".join(ch for ch in str(text).lower() if ch.isalnum() and not ch.isdigit())


def read_file(file):
    """``{"rows", "columns"}`` of an uploaded or stored CSV file.

    Raises ImportError with the page's sentence for a spreadsheet's own format, bytes
    that are not text, a file over the size ceiling and a file with no rows.
    """
    name = getattr(file, "name", "") or "the file"
    name = name.rsplit("/", 1)[-1]
    if name.lower().endswith(NOT_TEXT_EXTENSIONS):
        raise ImportError(not_csv_message(name))
    size = getattr(file, "size", None)
    if size is not None and size > pending_imports.MAX_UPLOAD_BYTES:
        from core.geofiles import too_large_message

        raise ImportError(too_large_message(size))
    raw = file.read()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if raw.startswith(b"PK\x03\x04") or raw.startswith(b"\xd0\xcf\x11\xe0"):
        raise ImportError(not_csv_message(name))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            raise ImportError(not_csv_message(name))
    reader = csv.DictReader(io.StringIO(text))
    columns = [c for c in (reader.fieldnames or []) if c and c.strip()]
    rows = [
        {key: (value or "").strip() for key, value in row.items() if key}
        for row in reader
        if any((value or "").strip() for key, value in row.items() if key)
    ]
    if not rows or not columns:
        raise ImportError(no_rows_message(name))
    return {"rows": rows, "columns": columns}


def auto_map(columns):
    """The column each field takes by its heading, or none."""
    mapping = {}
    for field, _, _ in FIELDS:
        for column in columns:
            if _letters(column) in HEADINGS[field] and column not in mapping.values():
                mapping[field] = column
                break
    return mapping


def posted_mapping(data, columns):
    return {
        field: data.get(f"map:{field}", "")
        for field, _, _ in FIELDS
        if data.get(f"map:{field}", "") in columns
    }


def first_values(rows, column, limit=5):
    if not column:
        return []
    return [row.get(column, "") for row in rows[:limit] if row.get(column, "")]


def _value(row, mapping, field):
    column = mapping.get(field)
    return row.get(column, "").strip() if column else ""


def _valid_email(value):
    try:
        validate_email(value)
    except ValidationError:
        return False
    return True


def plan_accounts(rows, mapping):
    """What importing ``rows`` with ``mapping`` would do. Writes nothing.

    Every row lands in exactly one of: ``assign``, ``already``, ``repeat``,
    ``not_on_file``, ``other_account``, ``two_accounts``, ``no_parcel``, ``no_account``,
    ``no_name``, ``number_too_long``, ``name_too_long``.
    """
    # Accounts: each account number's first name and contact, in file order.
    first = OrderedDict()
    for row in rows:
        number = _value(row, mapping, "account_number")
        if not number or len(number) > NUMBER_MAX_LENGTH:
            continue
        entry = first.setdefault(number, {"name": "", "contact": "", "email": ""})
        name = _value(row, mapping, "account_name")
        if name and not entry["name"]:
            entry["name"] = name
            entry["contact"] = _value(row, mapping, "contact_name")[:CONTACT_MAX_LENGTH]
            entry["email"] = _value(row, mapping, "contact_email")
    on_file = {a.account_number: a for a in WaterAccount.objects.filter(account_number__in=list(first))}
    new_accounts = OrderedDict(
        (number, entry) for number, entry in first.items()
        if number not in on_file and entry["name"] and len(entry["name"]) <= NAME_MAX_LENGTH
    )
    bad_email = [n for n, e in new_accounts.items() if e["email"] and not _valid_email(e["email"])]
    differing = [
        (number, first[number]["name"], account.name)
        for number, account in on_file.items()
        if first[number]["name"] and first[number]["name"] != account.name
    ]

    # Use areas on file, by their normalized number.
    parcels = {}
    for pk, number in Parcel.objects.current().values_list("pk", "parcel_number"):
        parcels.setdefault(normalize(number), (pk, number))

    # A use area the file puts in two different accounts.
    accounts_of = {}
    for row in rows:
        key = normalize(_value(row, mapping, "parcel_number"))
        number = _value(row, mapping, "account_number")
        if key and number:
            accounts_of.setdefault(key, set()).add(number)
    two_accounts_keys = {key for key, numbers in accounts_of.items() if len(numbers) > 1}

    # The use areas' open links, account by account.
    open_links = {}
    for parcel_id, account_number in WaterAccountParcel.objects.filter(
        removed_date__isnull=True
    ).values_list("parcel_id", "water_account__account_number"):
        open_links.setdefault(parcel_id, set()).add(account_number)

    buckets = {k: [] for k in ("assign", "already", "repeat", "not_on_file", "other_account",
                               "two_accounts", "no_parcel", "no_account", "no_name",
                               "number_too_long", "name_too_long")}
    seen = set()
    for row in rows:
        raw_parcel = _value(row, mapping, "parcel_number")
        number = _value(row, mapping, "account_number")
        name = _value(row, mapping, "account_name")
        if not raw_parcel:
            buckets["no_parcel"].append(row)
            continue
        if not number:
            buckets["no_account"].append(row)
            continue
        if len(number) > NUMBER_MAX_LENGTH:
            buckets["number_too_long"].append(row)
            continue
        if name and len(name) > NAME_MAX_LENGTH and number not in on_file:
            buckets["name_too_long"].append(row)
            continue
        if number not in on_file and number not in new_accounts:
            buckets["no_name"].append(number)
            continue
        key = normalize(raw_parcel)
        if key in two_accounts_keys:
            buckets["two_accounts"].append(raw_parcel)
            continue
        if key not in parcels:
            buckets["not_on_file"].append(raw_parcel)
            continue
        parcel_id, parcel_number = parcels[key]
        if (key, number) in seen:
            buckets["repeat"].append(row)
            continue
        seen.add((key, number))
        held = open_links.get(parcel_id, set())
        if number in held:
            buckets["already"].append(row)
        elif held:
            other = sorted(held)[0]
            buckets["other_account"].append(f"{parcel_number} in {other}")
        else:
            buckets["assign"].append((parcel_id, number))
    left_out = sum(len(buckets[k]) for k in ("not_on_file", "other_account", "two_accounts",
                                             "no_parcel", "no_account", "no_name",
                                             "number_too_long", "name_too_long"))
    return {
        "row_count": len(rows),
        "new_accounts": new_accounts,
        "on_file_count": len(on_file),
        "differing": differing,
        "bad_email": bad_email,
        "left_out": left_out,
        **buckets,
    }


def has_work(plan):
    return bool(plan["new_accounts"] or plan["assign"])


def write_accounts(plan, unit_kind):
    """Make the new accounts and the links; returns ``(accounts made, use areas assigned)``."""
    if plan["new_accounts"] and unit_kind not in dict(UNIT_KIND_CHOICES):
        raise ImportError(NO_TYPE_MESSAGE)
    bad = set(plan["bad_email"])
    with transaction.atomic():
        made = {}
        for number, entry in plan["new_accounts"].items():
            made[number] = WaterAccount.objects.create(
                account_number=number,
                name=entry["name"],
                contact_name=entry["contact"],
                contact_email="" if number in bad else entry["email"],
                unit_kind=unit_kind,
                status="active",
            )
        ids = dict(WaterAccount.objects.filter(
            account_number__in={number for _, number in plan["assign"]}
        ).values_list("account_number", "pk"))
        WaterAccountParcel.objects.bulk_create(
            [
                WaterAccountParcel(water_account_id=ids[number], parcel_id=parcel_id, reporting_period=None)
                for parcel_id, number in plan["assign"]
            ],
            batch_size=2000,
        )
    return len(made), len(plan["assign"])


def commit_stored_accounts(pending):
    """The import worker's commit: read the stored file again and write it."""
    with pending_imports.stored_file(pending) as file:
        read = read_file(file)
    plan = plan_accounts(read["rows"], pending.settings.get("mapping", {}))
    made, assigned = write_accounts(plan, pending.settings.get("unit_kind", ""))
    return {"made": made, "assigned": assigned, "left_out": plan["left_out"]}


# ---------------------------------------------------------------------------
# Words
# ---------------------------------------------------------------------------


def _n(count, one, many):
    return one if count == 1 else many


def account_lines(plan):
    """The Accounts table: (count, what, action)."""
    lines = []
    n = len(plan["new_accounts"])
    if n:
        lines.append((n, _n(n, "new account", "new accounts"), "Imported"))
    m = plan["on_file_count"]
    if m:
        lines.append((m, _n(m, "account already on file", "accounts already on file"), "Use areas added"))
    return lines


def row_lines(plan):
    """The Rows of the file table: (count, what, action, listed items, one item a line)."""
    spec = [
        ("assign", "use area", "use areas", "Assigned to their accounts", False),
        ("already", "use area already in its account", "use areas already in their accounts", "Unchanged", False),
        ("repeat", "row that repeats an earlier row", "rows that repeat an earlier row", "Unchanged", False),
        ("not_on_file", "parcel number not on file", "parcel numbers not on file", "Not imported", True),
        ("other_account", "use area already in another account", "use areas already in another account",
         "Not assigned", "lines"),
        ("two_accounts", "row for a use area this file puts in two accounts",
         "rows for a use area this file puts in two accounts", "Not imported", True),
        ("no_parcel", "row without a parcel number", "rows without a parcel number", "Not imported", False),
        ("no_account", "row without an account number", "rows without an account number", "Not imported", False),
        ("no_name", "row for a new account without a name", "rows for a new account without a name",
         "Not imported", True),
        ("number_too_long", f"row with an account number over {NUMBER_MAX_LENGTH} characters",
         f"rows with an account number over {NUMBER_MAX_LENGTH} characters", "Not imported", False),
        ("name_too_long", f"row with an account name over {NAME_MAX_LENGTH} characters",
         f"rows with an account name over {NAME_MAX_LENGTH} characters", "Not imported", False),
    ]
    lines = []
    for key, one, many, action, listed in spec:
        items = plan[key]
        if not items:
            continue
        shown = list(dict.fromkeys(items)) if listed else []
        lines.append((len(items), _n(len(items), one, many), action, shown, listed == "lines"))
    return lines


def differing_sentence(plan):
    d, m = len(plan["differing"]), plan["on_file_count"]
    verb = _n(d, "has", "have")
    return (f"{d:,} of these {m:,} accounts {verb} another name on file. "
            "OpenH2O keeps the name and contact on file.")


def differing_items(plan):
    return [f"{number}: {in_file} in the file, {kept} on file" for number, in_file, kept in plan["differing"]]


def bad_email_sentence(plan):
    n = len(plan["bad_email"])
    has = _n(n, "has a contact email that is not a valid address", "have a contact email that is not a valid address")
    return f"{n:,} {_n(n, 'new account', 'new accounts')} {has}. OpenH2O imports {_n(n, 'it', 'them')} without the email."


def result_sentence(made, assigned):
    return (f"OpenH2O imported {made:,} {_n(made, 'account', 'accounts')} and assigned {assigned:,} "
            f"{_n(assigned, 'use area', 'use areas')} to their accounts.")


def left_out_sentence(left_out):
    return f"OpenH2O left out the {left_out:,} {_n(left_out, 'row', 'rows')} the preview listed."
