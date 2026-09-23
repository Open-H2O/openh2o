# SPDX-License-Identifier: AGPL-3.0-or-later
"""Management command that imports wells from a CSV or Shapefile.

Reads each record (deriving a Point location from lat/lon columns or
geometry, in SRID 4326) and creates Well rows. Run it to load an agency's
well inventory; use --dry-run to preview without writing to the database.

**The alias table (ISS-190).** The first four fields below keep their own
override flags from this command's first version; the rest read one fixed
column name each, matching the state's and an agency's own well exports
(six-shapes-2026-09 shape-4 `wells.csv`, header read 2026-09-20). This is the
whole table; `docs/DATA-IMPORT.md`'s wells section names the same columns and
a test (`tests/test_data_import_doc_matches_commands.py`) keeps the two from
drifting apart again.

    Well field              Column read           Override flag
    ----------------------  --------------------  ------------------
    name                    WELL_NAME             --name-field
    location (lat/lon)      LATITUDE / LONGITUDE  --lat-field / --lon-field
    well_registration_id    WELL_REG_ID           --reg-id-field
    wcr_number              wcr_number            (none)
    owner_name              owner_name            (none)
    depth_ft                depth_ft              (none)
    casing_diameter_in      casing_diameter_in    (none)
    capacity_gpm            capacity_gpm          (none)
    year_pumping_began      year_pumping_began    (none)
    well_type               well_type             (none)

`WELL_REG_ID` is this agency's OWN local registration id
(`Well.well_registration_id` -- the well page's own help text calls it "this
agency's local registry identifier"). `wcr_number` is the STATE's identifier,
the DWR Well Completion Report number -- a different field, never read from
the same column as `WELL_REG_ID` even when a file happens to carry the same
value in both (ISS-190: before this fix, the command had no `wcr_number`
column at all, so the state's number silently went nowhere).

`well_type` is matched case-insensitively against an existing `WellType`
name. `WellType` is seeded reference data, the same kind `WaterRightType` is
for the rights importer, so an unmatched value is never used to create a new
type: it is reported as a warning and the well imports with no type.

Any column in the file that is none of the above is read by the parser but
not written anywhere; each one is reported once as a warning ("column X not
read"), never an error -- the file still imports.

A row whose well name matches an existing well's is not a hard duplicate
(only `well_registration_id` is unique in the database); by default it still
imports as a second row, reported by name so the count is never silently 0,
and `--skip-duplicates` skips it instead.
"""
import csv
import os
from decimal import Decimal, InvalidOperation

from django.contrib.gis.gdal import DataSource
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from wells.models import Well, WellType

DEFAULT_NAME_FIELD = "WELL_NAME"
DEFAULT_LAT_FIELD = "LATITUDE"
DEFAULT_LON_FIELD = "LONGITUDE"
DEFAULT_REG_ID_FIELD = "WELL_REG_ID"

#: Extra Well fields read beyond the original four, added for ISS-190.
#: {Well field name: column name read}. Fixed spellings, no override flag --
#: see the module docstring's table.
EXTRA_COLUMNS = {
    "wcr_number": "wcr_number",
    "owner_name": "owner_name",
    "depth_ft": "depth_ft",
    "casing_diameter_in": "casing_diameter_in",
    "capacity_gpm": "capacity_gpm",
    "year_pumping_began": "year_pumping_began",
    "well_type": "well_type",
}

#: Which EXTRA_COLUMNS fields parse as Decimal (the rest are text, an int, or
#: the well_type lookup, each handled on its own below).
DECIMAL_EXTRA_FIELDS = {"depth_ft", "casing_diameter_in", "capacity_gpm"}

#: The `web` container carries no bind mount to the host filesystem (checked
#: against docker-compose.yml: no volume maps a host directory in) -- a bare
#: path the operator can see on their own machine only ever resolves inside
#: the container by accident. `docker compose cp` is the only way a file
#: gets from the host into it.
NO_BIND_MOUNT_MESSAGE = (
    "The web container has no bind mount to your host filesystem -- a bare "
    "path only resolves inside the container. Copy the file in first: "
    "`docker compose cp {path} web:/tmp/`, then re-run this command with "
    "the path under /tmp/ (for example `/tmp/{name}`)."
)


class Command(BaseCommand):
    help = "Import wells from CSV or Shapefile."

    def add_arguments(self, parser):
        parser.add_argument(
            "file_path",
            type=str,
            help="Path to the input file (CSV or Shapefile).",
        )
        parser.add_argument(
            "--format",
            choices=["csv", "shapefile"],
            default=None,
            help="File format. Auto-detected from extension if not provided.",
        )
        parser.add_argument(
            "--name-field",
            default=DEFAULT_NAME_FIELD,
            help=f"Field name containing the well name (default: {DEFAULT_NAME_FIELD}).",
        )
        parser.add_argument(
            "--lat-field",
            default=DEFAULT_LAT_FIELD,
            help=f"Field name containing latitude (CSV only, default: {DEFAULT_LAT_FIELD}).",
        )
        parser.add_argument(
            "--lon-field",
            default=DEFAULT_LON_FIELD,
            help=f"Field name containing longitude (CSV only, default: {DEFAULT_LON_FIELD}).",
        )
        parser.add_argument(
            "--reg-id-field",
            default=DEFAULT_REG_ID_FIELD,
            help=(
                "Field name containing this agency's OWN local well "
                f"registration id (default: {DEFAULT_REG_ID_FIELD}). Not the "
                "state's WCR number -- see --help above."
            ),
        )
        parser.add_argument(
            "--skip-duplicates",
            action="store_true",
            help=(
                "Skip a row whose well name matches an existing well, "
                "instead of importing it as a second row."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be imported without writing to the database.",
        )

    def handle(self, *args, **options):
        file_path = options["file_path"]
        fmt = options["format"]
        name_field = options["name_field"]
        lat_field = options["lat_field"]
        lon_field = options["lon_field"]
        reg_id_field = options["reg_id_field"]
        skip_duplicates = options["skip_duplicates"]
        dry_run = options["dry_run"]

        if not os.path.exists(file_path):
            raise CommandError(
                f"File not found: {file_path}\n"
                + NO_BIND_MOUNT_MESSAGE.format(
                    path=file_path, name=os.path.basename(file_path)
                )
            )

        # Auto-detect format from extension
        if fmt is None:
            ext = os.path.splitext(file_path)[1].lower()
            if ext == ".csv":
                fmt = "csv"
            elif ext == ".shp":
                fmt = "shapefile"
            else:
                raise CommandError(
                    f"Cannot detect format from extension '{ext}'. Use --format."
                )

        if dry_run:
            self.stdout.write(self.style.WARNING("[DRY RUN] No records will be written."))

        known_columns = {name_field, lat_field, lon_field, reg_id_field, *EXTRA_COLUMNS.values()}
        self._report_columns(file_path, fmt, known_columns, dry_run)

        imported_count = 0
        duplicate_count = 0
        error_count = 0

        # WellType is seeded reference data (like WaterRightType for the
        # rights importer): looked up, never created here.
        type_by_name = {t.name.lower(): t for t in WellType.objects.all()}

        records = list(
            self._load_records(
                file_path, fmt, name_field, lat_field, lon_field, reg_id_field
            )
        )

        with transaction.atomic():
            for idx, rec in enumerate(records, start=1):
                try:
                    name = rec.get("name") or ""
                    reg_id = rec.get("reg_id") or None
                    location = rec.get("location")

                    # Skip records with no coordinates
                    if location is None:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  Record {idx}: missing coordinates -- skipped."
                            )
                        )
                        error_count += 1
                        continue

                    # Fall back to reg_id or sequential name
                    if not name:
                        name = reg_id or f"Well {idx}"

                    # Duplicate detection by registration ID: well_registration_id
                    # is unique in the database, so this is a hard skip regardless
                    # of --skip-duplicates.
                    if reg_id:
                        if Well.objects.filter(well_registration_id=reg_id).exists():
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  {name} (reg_id={reg_id}): duplicate registration id -- skipped."
                                )
                            )
                            duplicate_count += 1
                            continue

                    # Same-name warning (ISS-190): not a hard duplicate, since
                    # only well_registration_id is unique, but silently
                    # importing a second row under an existing name is exactly
                    # what shape 4's walk found ("0 duplicates skipped").
                    if Well.objects.filter(name=name).exists():
                        if skip_duplicates:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  a well named {name} exists; skipped (--skip-duplicates)."
                                )
                            )
                            duplicate_count += 1
                            continue
                        self.stdout.write(
                            self.style.WARNING(
                                f"  a well named {name} exists; imported as a "
                                "second row; pass --skip-duplicates to skip."
                            )
                        )

                    extra_fields = self._coerce_extra_fields(
                        rec, idx, name, type_by_name
                    )

                    if not dry_run:
                        Well.objects.create(
                            name=name,
                            well_registration_id=reg_id,
                            location=location,
                            **extra_fields,
                        )
                    imported_count += 1

                except Exception as exc:
                    self.stdout.write(
                        self.style.ERROR(f"  Record {idx}: error -- {exc}")
                    )
                    error_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {imported_count} wells, {duplicate_count} duplicates skipped, {error_count} errors"
            )
        )

    def _coerce_extra_fields(self, rec, idx, name, type_by_name):
        """Turn the raw string values EXTRA_COLUMNS collected into Well kwargs."""
        fields = {}

        for field in ("wcr_number", "owner_name"):
            fields[field] = rec.get(field) or ""

        for field in DECIMAL_EXTRA_FIELDS:
            raw = rec.get(field)
            if raw:
                try:
                    fields[field] = Decimal(raw)
                except InvalidOperation:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  {name}: '{field}' value '{raw}' is not a number -- left blank."
                        )
                    )

        raw_year = rec.get("year_pumping_began")
        if raw_year:
            try:
                fields["year_pumping_began"] = int(float(raw_year))
            except ValueError:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {name}: 'year_pumping_began' value '{raw_year}' is "
                        "not a number -- left blank."
                    )
                )

        raw_type = (rec.get("well_type") or "").strip()
        if raw_type:
            well_type = type_by_name.get(raw_type.lower())
            if well_type is not None:
                fields["well_type"] = well_type
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {name}: well type '{raw_type}' not found -- imported with no well type."
                    )
                )

        return fields

    def _report_columns(self, file_path, fmt, known_columns, dry_run):
        """Warn on every column the file carries that this command does not
        read, always; on --dry-run also print the full read/ignored split."""
        if fmt == "csv":
            with open(file_path, newline="", encoding="utf-8-sig") as f:
                header = list(csv.DictReader(f).fieldnames or [])
        elif fmt == "shapefile":
            try:
                ds = DataSource(file_path)
                header = list(ds[0].fields)
            except Exception:
                return
        else:
            return

        read_cols = [c for c in header if c in known_columns]
        ignored_cols = [c for c in header if c not in known_columns]

        for col in ignored_cols:
            self.stdout.write(self.style.WARNING(f"  column {col} not read"))

        if dry_run:
            self.stdout.write(f"Columns that will be read: {', '.join(read_cols)}")
            self.stdout.write(f"Columns that will be ignored: {', '.join(ignored_cols)}")

    def _load_records(self, file_path, fmt, name_field, lat_field, lon_field, reg_id_field):
        if fmt == "csv":
            with open(file_path, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    name = row.get(name_field, "").strip()
                    reg_id = row.get(reg_id_field, "").strip() or None
                    location = None
                    try:
                        lat_raw = row.get(lat_field, "")
                        lon_raw = row.get(lon_field, "")
                        if lat_raw and lon_raw:
                            location = Point(float(lon_raw), float(lat_raw), srid=4326)
                    except (ValueError, TypeError):
                        pass

                    rec = {"name": name, "reg_id": reg_id, "location": location}
                    for well_field, column in EXTRA_COLUMNS.items():
                        raw = row.get(column, "")
                        rec[well_field] = raw.strip() if raw else ""
                    yield rec

        elif fmt == "shapefile":
            try:
                ds = DataSource(file_path)
            except Exception as exc:
                raise CommandError(f"Failed to open shapefile with GDAL: {exc}")

            layer = ds[0]
            for feature in layer:
                name_val = ""
                reg_id_val = None
                try:
                    name_val = str(feature[name_field].value).strip()
                except Exception:
                    pass
                try:
                    reg_id_val = str(feature[reg_id_field].value).strip() or None
                except Exception:
                    pass

                location = None
                try:
                    geom = feature.geom
                    if geom is not None:
                        # Use centroid if not already a point
                        if geom.geom_type.upper() == "POINT":
                            lon, lat = geom.coords[0], geom.coords[1]
                        else:
                            centroid = geom.centroid
                            lon, lat = centroid.coords[0], centroid.coords[1]
                        srid = geom.srid or 4326
                        pt = Point(lon, lat, srid=srid)
                        if srid != 4326:
                            pt.transform(4326)
                        location = pt
                except Exception:
                    pass

                rec = {"name": name_val, "reg_id": reg_id_val, "location": location}
                for well_field, column in EXTRA_COLUMNS.items():
                    try:
                        raw = str(feature[column].value).strip()
                    except Exception:
                        raw = ""
                    rec[well_field] = raw
                yield rec
