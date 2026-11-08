# SPDX-License-Identifier: AGPL-3.0-or-later
"""152-03.1: the approved guide sentences are in the guides.

Each Fixed sentence of rows 43 to 72 of ``152-03.1-ROWS.md`` is copied here word
for word. A guide is read as text and every run of whitespace is collapsed to one
space, because the guides wrap their lines. A row whose Fixed text holds "..." is
checked part by part. The old sentences that rows 55, 65, 66, 67, 68 and 71
replace must be gone.
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA = "docs/DATA-IMPORT.md"
GUIDE = "docs/AI-OPERATOR-GUIDE.md"
DEPLOY = "DEPLOY.md"


def _flat(name):
    return re.sub(r"\s+", " ", (REPO_ROOT / name).read_text())


def _sentences(text):
    """Split on a full stop followed by a space; the full stop stays with its sentence."""
    return [s.strip() for s in re.split(r"(?<=\.) ", text) if s.strip()]


# (row, file, Fixed text)
FIXED = [
    (43, DATA, "To load a boundary file with a command instead, use `import_boundary`. It reads the same files as the wizard's upload:"),
    (45, DATA, "With a headgate column, `import_parcels` links each use area to its point of diversion. Each value in the column must be the local name of a point already on the site. A point's name works too. Import the points of diversion before you run the command with this column. The command links new use areas and use areas already on the site. It skips a use area that is already linked to that point. It never changes a share you set. OpenH2O divides a point's water among its use areas by acreage until you set a share for each use area on the point's page. If a value is not the name of a point on the site, the command lists the value. It then stops without importing any use area."),
    (46, DATA, "The command ignores a crop column. OpenH2O's figures for a use area are the same whatever crop the use area grows."),
    (47, DATA, "The `import_infrastructure` command reads the same files as the Import screen. It checks each row by the screen's rules. Give the kind of record after `--type`: `well`, `diversion`, `storage` or `recharge_site`. To read a value from a column the screen would not recognize, give `--column`, such as `--column local_name=HEADGATE`. A dry run lists OpenH2O's name for each value and the column the command reads for it."),
    (48, DATA, 'The `import_water_rights` command reads the same file as the Water Rights Import screen. The command creates the same water rights as the screen. To read a value from a column the screen would not recognize, give `--column`, such as `--column net_acreage=ACRES`.'),
    (49, DATA, 'In the state\'s list, "NA" and "NaN" stand for a blank. OpenH2O imports "NA" and "NaN" as blanks.'),
    (50, DATA, 'You create each water year on the Water Years page or with `create_water_year`. A water year starts on the first day of a month and ends on the last day of a month. Give each water year a name.'),
    (51, DATA, "Set the organization's name with `set_organization` or at `/admin/` under Core > Site configs."),
    (52, DATA, 'Without a browser, load the boundary with `import_boundary` and run `auto_populate`.'),
    (53, DATA, 'Import your water rights with `import_water_rights` or the Water Rights Import screen. You can also add a right by hand on the Water Rights page. Next, import points of diversion, storage ponds and recharge sites with `import_infrastructure` or the Import screen. A point that names a water right needs that right on the site first. Then run `import_parcels` again with the headgate column to link each use area to its point.'),
    (54, DATA, 'Create the water years with `create_water_year` or on the Water Years page. Then import ledger history with `import_ledger_csv` or the Upload CSV page. Import diversion records with `import_diversion_records` or the diversion import screen.'),
    (55, GUIDE, "`import_boundary` reads the same GeoJSON, zipped shapefile and KML files as the wizard's upload."),
    (56, GUIDE, "Before you load any records, set the organization's name with `set_organization`. Every email the site sends starts its subject line with that name."),
    (57, GUIDE, '`import_parcels` links each use area to its point when the file of use areas has a headgate column.'),
    (58, GUIDE, '`import_water_rights` or the import screen at `/surface/rights/import/`'),
    (59, GUIDE, "From the state's CSV list, the command creates the same water rights as the screen. Import the water rights before the points of diversion."),
    (60, GUIDE, '`import_infrastructure --type diversion` or the Import screen at `/infrastructure/import/?type=diversion`'),
    (61, GUIDE, 'The command reads the same files as the screen. It creates the same points of diversion. To link each use area to its point, run `import_parcels` again with a headgate column after the points are on the site.'),
    (62, GUIDE, '`import_infrastructure` with `--type storage` or `--type recharge_site`. On the Import screen, use `?type=storage` or `?type=recharge_site` at the end of the address.'),
    (63, GUIDE, 'Each entry counts in the water year its date falls in. Create the water years first with `create_water_year` or under Water accounting > Water Years.'),
    (64, GUIDE, "Before the first allocation, set the water year's first month on the Delivery Settings page. Then create each water year with `create_water_year` or on the Water Years page. A water year starts on the first day of a month and ends on the last day of a month."),
    (65, GUIDE, "A station's page shows when OpenH2O next reads that station's data. The page gives that time in the site's time zone. Set the site's time zone with `set_organization --time-zone`. A site whose organization's name was never set uses the `TIME_ZONE` setting in `.env`."),
    (66, GUIDE, "The command `set_organization` sets the organization's name. The site's emails use that name. The site's address comes from `ALLOWED_HOSTS`. The migrations save that address in place of the placeholder `example.com`."),
    (67, GUIDE, "If the name still reads `example.com`, run `set_organization` with the organization's name. If the address still reads `example.com`, put the address in `ALLOWED_HOSTS` in `.env`."),
    (68, GUIDE, "A site reached only at `localhost` takes `localhost` as its address. `manage.py check` stops reporting `openh2o.W002` once `set_organization` has set the organization's name."),
    (69, DEPLOY, "The site's emails use the organization's name. The command `set_organization` sets the organization's name. The site's address comes from `ALLOWED_HOSTS`."),
    (70, DEPLOY, "OpenH2O saves the address when the migrations run. The migrations replace a saved address only when it is the placeholder `example.com`. ... Set the organization's name after the superuser exists."),
    (71, DEPLOY, "If the name is missing, run `set_organization` with the organization's name. A site reached only at `localhost` takes `localhost` as its address. `manage.py check` stops reporting `openh2o.W002` once `set_organization` has set the organization's name."),
    (72, DEPLOY, "A station's page shows when OpenH2O next reads that station's data. The page gives that time in the site's time zone. Set the site's time zone with `set_organization --time-zone`. A site whose organization's name was never set uses the `TIME_ZONE` setting in `.env`."),  # row 72 is row 65's text
]


# (row, file, Now text): sentences these rows replace
OLD = [
    (55, GUIDE, '`import_boundary` reads only GeoJSON, so convert a shapefile or a KML file to GeoJSON first.'),
    (65, GUIDE, "The page of each switched-on station that OpenH2O syncs shows its next scheduled fetch in the site's time zone, set at `/admin/` under Core > Site configs or, without that, by `TIME_ZONE`."),
    (65, DEPLOY, "The page of each switched-on station that OpenH2O syncs shows its next scheduled fetch in the site's time zone, set at `/admin/` under Core > Site configs or, without that, by `TIME_ZONE`."),
    (66, GUIDE, "OpenH2O takes the site's name from the organization's name, which is set at `/admin/` under Core > Site configs. It takes the site's address from `ALLOWED_HOSTS`. It saves both when the migrations run."),
    (67, GUIDE, "If either one still reads `example.com`, set the missing value. The organization's name goes in at `/admin/` under Core > Site configs, and the address goes in `ALLOWED_HOSTS` in `.env`."),
    (68, GUIDE, "A site reached only at `localhost` takes `localhost` as its address; the warning clears once the organization's name is set and the migrations have run again."),
    (71, DEPLOY, "If the name is missing, set the organization's name at `/admin/` under Core > Site configs, then run the migrations again (section 6). A site reached only at `localhost` takes `localhost` as its address; the warning clears once the organization's name is set and the migrations have run again."),
]


@pytest.mark.parametrize("row,name,fixed", FIXED, ids=[f"row{r}" for r, _, _ in FIXED])
def test_the_guide_holds_the_approved_text(row, name, fixed):
    text = _flat(name)
    parts = [p.strip() for p in fixed.split("...")] if "..." in fixed else [fixed]
    for part in parts:
        assert part in text, f"row {row}: not in {name}: {part!r}"


@pytest.mark.parametrize("row,name,now", OLD, ids=[f"row{r}-{n}" for r, n, _ in OLD])
def test_the_replaced_sentences_are_gone(row, name, now):
    text = _flat(name)
    fixed = {r: f for r, _, f in FIXED}.get(row, "")
    gone = [s for s in _sentences(now) if s not in fixed]
    assert gone, f"row {row}: no sentence left to check"
    still_there = [s for s in gone if s in text]
    assert not still_there, f"row {row}: still in {name}: {still_there!r}"


def test_the_headgate_row_is_in_the_use_areas_table():
    rows = [
        line for line in (REPO_ROOT / DATA).read_text().splitlines()
        if re.match(r"\|\s*Headgate\s*\|", line)
    ]
    assert rows, "row 44: no table row begins with the cell Headgate"
    assert "`HEADGATE`" in rows[0] and "`--headgate-field`" in rows[0]


# Rows 76 to 80 (ruling 108), the follow-up sentences the post-build re-read called for.
_FOLLOW_UP = [
    ("docs/DATA-IMPORT.md", "`import_parcels` differs from the Import use areas screen in four ways: it imports parcels outside the boundary, it reads the parcel number from the `APN` column unless you name another column, it stops at an outline it cannot read, and it links each use area to its headgate from a headgate column:"),
    ("README.md", "`import_parcels` does not import any use area when an outline cannot be read, a parcel cannot be saved or the file names a headgate that is not on the site."),
    ("docs/DATA-IMPORT.md", "If the file of use areas has a headgate column, run `import_parcels` on that file after you import the points of diversion in step 5."),
    ("docs/AI-OPERATOR-GUIDE.md", "`import_boundary` loads a boundary from a GeoJSON file, a zipped shapefile or a KML file."),
    ("docs/DATA-IMPORT.md", "Before you give a shapefile to `import_boundary` or `import_infrastructure`, zip its files together."),
]


@pytest.mark.parametrize("path,sentence", _FOLLOW_UP)
def test_the_follow_up_sentences_are_in_place(path, sentence):
    from pathlib import Path

    text = " ".join(Path(path).read_text().split())
    assert sentence in text
