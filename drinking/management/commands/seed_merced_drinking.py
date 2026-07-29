# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Seed the drinking-water half of the Merced Subbasin demonstration: the City of
Merced (``CA2410009``), its facilities, its municipal supply wells, its
sampling points, and three years of its real published laboratory results.

WHY THIS SYSTEM. The demonstration already models the subbasin's *quantity*
side. CA2410009 is a 100% groundwater community water system serving 93,692
people, and all 21 of its sampled source wells fall inside the same
``lower_merced_subbasin.geojson`` boundary the rest of the demo uses. The city
drinks the aquifer the rest of the platform is accounting for, which is what
makes ``SystemFacility.well`` a real join here rather than a diagram: the same
physical well, sampled on this side and metered on the other.

**Nothing here is synthesized.** Every value comes from a published federal or
state record committed under ``data/merced/drinking/`` — see the README there
for sources, retrieval dates and the two filters applied to the lab file. A
demonstration of a named real utility that invented its chemistry would be a
liability wearing a helpful coat.

**Everything is written through the production code path.** The system and its
facilities go in via ``envirofacts_mapping.commit_system`` — the same function
the onboarding wizard calls. The results go in via ``importer.validate_rows``
and ``importer.commit_rows`` — the same functions the import screen calls, on
the state's own unmodified export. The seed adds no writer of its own for
either, so this command doubles as an end-to-end exercise of both paths, and a
change that breaks onboarding or import breaks the demo seed too.

The one thing the seed does write directly is the municipal wells and the
``SystemFacility.well`` links, because no operator-facing surface creates those
yet.

Order matters:
  1. the Envirofacts cache rows, so the wizard can look CA2410009 up offline;
  2. the system + facilities, from the committed federal payloads;
  3. the municipal wells, and the facility links to them;
  4. the sampling points, which the importer requires before it will accept a
     single row (an unknown PS Code is a row error, never an implicit create);
  5. the lab results.

Idempotent. Re-running refreshes the system from the federal payload, leaves
existing wells and points alone, and the importer's own duplicate guard drops
every result it already holds. ``--flush`` removes this system's demo rows
first, for a clean rebuild.
"""
import csv
import gzip
import io
import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.modules import is_enabled
from drinking import envirofacts_mapping, importer
from drinking.models import (
    EnvirofactsCache,
    SampleEvent,
    SampleResult,
    SamplingPoint,
    SystemFacility,
    WaterSystem,
)
from drinking.ps_codes import compose_ps_code

PWSID = "CA2410009"

DATA_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "data", "merced", "drinking",
)

#: The demo's key for a City of Merced supply well. Deliberately NOT written to
#: ``state_well_number`` or ``wcr_number``: those name real state registries and
#: this is a demonstration key, not a registry entry. The prefix matches the
#: demo's existing ``MER-W-###`` agricultural wells so a teardown or an audit
#: can see both belong to the Merced seed.
WELL_ID_PREFIX = "MER-PWS-"

#: Facility type (as the state's own export reports it) -> the monitoring role
#: the point plays. An operator picks this by hand in the wizard's point
#: builder; the seed reads it off the file rather than guessing, and the LCR tap
#: is special-cased because a Lead and Copper Rule sample is drawn at a
#: customer's tap, not from the distribution main.
POINT_TYPE_BY_FACILITY_TYPE = {
    "WL": "source",
    "TP": "entry_point",
    "DS": "distribution",
}

#: Chunk size for the import pipeline. ``importer.MAX_ROWS`` is an *upload*
#: guard on a browser form, not a data rule, so a seed reading a committed file
#: is not subject to it — but ``validate_rows`` holds a batch in memory and
#: re-reads the existing-result keys per call, so feeding 22k rows as one batch
#: would be wasteful rather than wrong. 2000 keeps both bounded.
CHUNK_ROWS = 2000


def _data_path(name):
    return os.path.normpath(os.path.join(DATA_DIR, name))


def _load_json(name):
    path = _data_path(name)
    if not os.path.exists(path):
        raise CommandError(
            f"Missing demonstration data file: {path}. See "
            "data/merced/drinking/README.md."
        )
    with open(path) as f:
        return json.load(f)


class Command(BaseCommand):
    help = (
        "Seed the City of Merced (CA2410009) drinking-water demonstration: "
        "system, facilities, municipal wells, sampling points and three years "
        "of published lab results. Idempotent."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush",
            action="store_true",
            help=(
                "Delete this system's demo rows (results, events, points, "
                "facilities, system, and its MER-PWS- wells) before seeding."
            ),
        )

    def handle(self, *args, **options):
        if options["flush"]:
            self._flush()

        self._seed_cache()
        system = self._seed_system()
        rows, columns = self._load_lab_file()
        self._apply_state_fields(system, rows)
        self._seed_facility_locations(system)
        self._seed_wells(system)
        self._seed_points(system)
        self._seed_results(rows, columns)

        self.stdout.write(self.style.SUCCESS(
            f"\nMerced drinking-water demo seeded: {PWSID} with "
            f"{system.facilities.count()} facilities, "
            f"{SamplingPoint.objects.filter(facility__system=system).count()} "
            f"sampling points and "
            f"{SampleResult.objects.filter(event__sampling_point__facility__system=system).count()} "
            "results."
        ))

    # -- 1. federal payload cache -------------------------------------------

    def _seed_cache(self):
        """Prime ``EnvirofactsCache`` from the committed payloads.

        Not decoration: with these rows present the onboarding wizard resolves
        CA2410009 from the database instead of the network, so the demo's
        "look up a PWSID" flow works on a box with no outbound internet and
        returns the same record the rest of this seed used.
        """
        for table, filename in (
            ("WATER_SYSTEM", "envirofacts_water_system.json"),
            ("WATER_SYSTEM_FACILITY", "envirofacts_facilities.json"),
            ("GEOGRAPHIC_AREA", "envirofacts_geographic_area.json"),
        ):
            EnvirofactsCache.objects.update_or_create(
                pwsid=PWSID,
                table_name=table,
                defaults={"payload": _load_json(filename)},
            )
        self.stdout.write(f"  Envirofacts cache primed for {PWSID} (3 tables).")

    # -- 2. system + facilities ---------------------------------------------

    def _seed_system(self):
        """Onboard the system through the wizard's own commit function."""
        system_rows = _load_json("envirofacts_water_system.json")
        facility_rows = _load_json("envirofacts_facilities.json")
        if not system_rows:
            raise CommandError(
                "envirofacts_water_system.json carries no system row."
            )

        result = envirofacts_mapping.commit_system(system_rows[0], facility_rows)

        self.stdout.write(
            f"  {'Created' if result.created else 'Refreshed'}: "
            f"{result.system.name} ({result.system.pwsid}) — "
            f"{result.facilities_created} facilities created, "
            f"{result.facilities_updated} updated"
            + (f", {len(result.skipped)} skipped" if result.skipped else "")
        )
        for note in result.skipped:
            self.stdout.write(f"    skipped: {note}")
        for warning in result.warnings:
            self.stdout.write(self.style.WARNING(f"    {warning}"))
        return result.system

    # -- 2b. the fields only the state publishes -----------------------------

    def _apply_state_fields(self, system, rows):
        """Fill the two identity fields EPA does not carry, from the state file.

        A neat division the data itself draws: the federal extract is the
        authority on federal facts (PWS type, owner type, primary source), and
        the state's own export is the authority on state ones. DDW's district
        office and the state water-system classification appear in every row of
        the lab file and in no Envirofacts table, which is why the wizard leaves
        both blank and why filling them here is not overriding anything.

        Safe against a re-run: neither field is in
        ``envirofacts_mapping._SYSTEM_REFRESHABLE_FIELDS``, so ``commit_system``
        never writes them back to blank.

        Refuses a file that disagrees with itself rather than taking the first
        row's word for it — one system's rows should carry one answer, and if
        they do not, the assumption behind this whole method is wrong.
        """
        updates = {}
        for field, column in (
            ("regulating_agency", "Regulating Agency"),
            ("state_classification", "State Water System Classification"),
        ):
            values = {(row.get(column) or "").strip() for row in rows}
            values.discard("")
            if not values:
                continue
            if len(values) > 1:
                raise CommandError(
                    f"The lab file reports {len(values)} different values for "
                    f"'{column}' on one system: {sorted(values)}. Refusing to "
                    "pick one."
                )
            updates[field] = values.pop()

        if not updates:
            return
        for field, value in updates.items():
            setattr(system, field, value)
        system.save(update_fields=list(updates))
        self.stdout.write(
            "  State record: "
            + ", ".join(f"{k} = {v}" for k, v in sorted(updates.items()))
        )

    # -- 2c. the coordinates, on the drinking side ---------------------------

    def _seed_facility_locations(self, system):
        """Write the published GAMA coordinate onto the facility itself.

        **Unconditional, and that is the entire point.** ``_seed_wells`` below is
        correctly gated on the ``wells`` module — writing rows into a
        schema-resident module's table is exactly the silent fill
        ``test_schema_resident_module_tables_are_present_and_empty`` catches. But
        that gate used to take the coordinates with it, so in the drinking-water
        utility flavor (``parcels``+``accounting`` off takes ``wells`` with it,
        ``core/modules.py``) nothing in this module knew where anything was.

        Runs BEFORE ``_seed_wells`` so the facility carries its own position
        whether or not the wells step ever executes.

        Only rows the state actually publishes a latitude for are touched. GAMA
        publishes source-well locations only, so the distribution-system and
        treatment-plant points have none — and NULL is the honest value for them,
        not ``(0, 0)``.
        """
        from django.contrib.gis.geos import Point

        points = _load_json("sampling_points.json")
        facilities = {
            facility.facility_id: facility
            for facility in system.facilities.all()
        }

        # Keyed by facility, not by point: several points can share one facility
        # and they all name the same published coordinate.
        located = {}
        for point in points:
            if "latitude" not in point:
                continue
            located[point["facility_id"]] = Point(
                point["longitude"], point["latitude"], srid=4326
            )

        written = 0
        for facility_id, location in located.items():
            facility = facilities.get(facility_id)
            if facility is None:
                self.stdout.write(self.style.WARNING(
                    f"    no facility {facility_id} for a located sampling "
                    "point; no coordinate set"
                ))
                continue
            # Re-writing an identical point is a no-op in the database and keeps
            # the count honest about how many facilities ARE located, which is
            # the number the map's coverage sentence is measured against.
            facility.location = location
            facility.save(update_fields=["location"])
            written += 1

        self.stdout.write(f"  Facility locations: {written} set.")

    # -- 3. municipal wells --------------------------------------------------

    def _seed_wells(self, system):
        """Create the city's supply wells and link the facilities to them.

        This is the quality-to-quantity join the whole demonstration exists to
        show, and it is the one thing here with no operator-facing surface to
        borrow — so it is written directly.

        Guarded on the module rather than assumed: ``wells`` is schema-resident,
        so on a deployment that switched it off the import still resolves and
        the table still exists, and writing rows into it would be exactly the
        silent fill that ``test_schema_resident_module_tables_are_present_and_empty``
        exists to catch. ``seed_merced`` requires a full deployment, so in the
        demo's own sequence this branch is always taken.
        """
        if not is_enabled("wells"):
            self.stdout.write(
                "  Wells module not enabled — skipping supply wells and the "
                "facility links to them."
            )
            return

        from django.contrib.gis.geos import Point
        from wells.models import Well, WellType

        well_type = WellType.objects.filter(name="Production").first()
        if well_type is None:
            raise CommandError(
                "WellType 'Production' not found. Run seed_well_types first."
            )

        points = _load_json("sampling_points.json")
        created = updated = linked = 0

        for point in points:
            if point["facility_type"] != "WL" or "latitude" not in point:
                continue
            facility_id = point["facility_id"]
            facility = system.facilities.filter(facility_id=facility_id).first()
            if facility is None:
                self.stdout.write(self.style.WARNING(
                    f"    no facility {facility_id} for {point['ps_code']}; "
                    "no well created"
                ))
                continue

            defaults = {
                # The state's own name for the facility, which is the name the
                # sample results carry ("WELL 08 - RAW").
                "name": point["name"],
                "well_type": well_type,
                "location": Point(
                    point["longitude"], point["latitude"], srid=4326
                ),
                "status": "active",
                "owner_name": system.name,
            }
            # Screen intervals are present for only three of these wells; see
            # the README on why the implausible ones are left NULL rather than
            # written down.
            if "screen_top_ft" in point:
                defaults["screen_top_ft"] = point["screen_top_ft"]
                defaults["screen_bottom_ft"] = point["screen_bottom_ft"]

            well, was_created = Well.objects.update_or_create(
                well_registration_id=f"{WELL_ID_PREFIX}{facility_id}",
                defaults=defaults,
            )
            created += was_created
            updated += not was_created

            if facility.well_id != well.pk:
                facility.well = well
                facility.save(update_fields=["well"])
                linked += 1

        self.stdout.write(
            f"  Municipal wells: {created} created, {updated} updated, "
            f"{linked} facility links set."
        )

    # -- 4. sampling points --------------------------------------------------

    def _seed_points(self, system):
        """Create the PS Codes the lab file will be matched on.

        Composed rather than copied, then checked against the code the state's
        own file carries. ``SamplingPoint.ps_code`` is documented as stored
        verbatim, so a composition that disagreed with the published code would
        mean the composer is wrong — and a code that silently never matches an
        import row is the failure that is hardest to see from the outside.
        """
        points = _load_json("sampling_points.json")
        facilities = {
            facility.facility_id: facility
            for facility in system.facilities.all()
        }

        created = existing = 0
        for point in points:
            facility = facilities.get(point["facility_id"])
            if facility is None:
                raise CommandError(
                    f"{point['ps_code']} names facility "
                    f"{point['facility_id']}, which this system does not "
                    "carry. The federal payload and the lab file disagree."
                )

            point_number = point["ps_code"].split("_", 2)[2]
            composed = compose_ps_code(
                system.pwsid, facility.facility_id, point_number
            )
            if composed != point["ps_code"]:
                raise CommandError(
                    f"Composed {composed} but the state's file publishes "
                    f"{point['ps_code']}. Refusing to seed a PS Code that "
                    "cannot match a real lab row."
                )

            point_type = POINT_TYPE_BY_FACILITY_TYPE.get(
                point["facility_type"], ""
            )
            # A Lead and Copper Rule sample is drawn at a customer's tap. It
            # hangs off the distribution system like the DBPR points do, so the
            # facility type alone cannot tell them apart.
            if point["ps_code"].endswith("_LCR"):
                point_type = "tap"

            _, was_created = SamplingPoint.objects.get_or_create(
                ps_code=point["ps_code"],
                defaults={
                    "facility": facility,
                    "name": point["name"],
                    "point_type": point_type,
                },
            )
            created += was_created
            existing += not was_created

        self.stdout.write(
            f"  Sampling points: {created} created, {existing} already present."
        )

    # -- 5. lab results ------------------------------------------------------

    def _load_lab_file(self):
        """Read the committed SDWIS4 slice once; both later steps use it."""
        path = _data_path("merced_lab_results_3yr.tab.gz")
        if not os.path.exists(path):
            raise CommandError(
                f"Missing lab results file: {path}. See "
                "data/merced/drinking/README.md."
            )

        with gzip.open(path, "rt", newline="") as f:
            reader = csv.DictReader(io.StringIO(f.read()), delimiter="\t")
            columns = reader.fieldnames or []
            rows = list(reader)

        if not rows:
            raise CommandError(f"{path} carries no rows.")
        return rows, columns

    def _seed_results(self, rows, columns):
        """Import the committed SDWIS4 slice through the importer itself."""
        mapping = importer.auto_map_columns(columns)
        missing = importer.missing_required(mapping)
        if missing:
            raise CommandError(
                "The committed lab file no longer auto-maps: missing "
                + ", ".join(missing)
            )

        totals = {"events": 0, "results": 0, "analytes": 0,
                  "duplicates": 0, "skipped": 0}
        errors = []

        for start in range(0, len(rows), CHUNK_ROWS):
            chunk = rows[start:start + CHUNK_ROWS]
            validated = importer.validate_rows(chunk, mapping)
            for entry in validated:
                if entry["errors"]:
                    errors.extend(entry["errors"])
            counts = importer.commit_rows(validated)
            for key in totals:
                totals[key] += counts.get(key, 0)

        self.stdout.write(
            f"  Lab results: {totals['results']} results across "
            f"{totals['events']} sample events; "
            f"{totals['analytes']} analytes learned from the file's own "
            f"vocabulary, {totals['duplicates']} already present, "
            f"{totals['skipped']} rows skipped."
        )
        if errors:
            # Loud, and capped. A committed file that starts producing row
            # errors means the file or the importer moved; the demo should say
            # so rather than seed a quietly smaller dataset.
            self.stdout.write(self.style.WARNING(
                f"    {len(errors)} row errors; first few:"
            ))
            for message in errors[:5]:
                self.stdout.write(self.style.WARNING(f"      {message}"))

    # -- flush ---------------------------------------------------------------

    def _flush(self):
        """Remove this system's demo rows. Scoped to CA2410009 only.

        Analytes and RegulatoryLimits are deliberately NOT deleted: they are
        shared reference vocabulary owned by ``seed_drinking``, not demo data,
        and ``SampleResult.analyte`` is PROTECT precisely so lab evidence
        cannot be lost to a vocabulary cleanup.
        """
        system = WaterSystem.objects.filter(pwsid=PWSID).first()
        if system is None:
            self.stdout.write("  Flush: nothing to remove.")
            return

        with transaction.atomic():
            results = SampleResult.objects.filter(
                event__sampling_point__facility__system=system
            )
            events = SampleEvent.objects.filter(
                sampling_point__facility__system=system
            )
            removed = (results.count(), events.count())
            results.delete()
            events.delete()
            SamplingPoint.objects.filter(facility__system=system).delete()

            if is_enabled("wells"):
                from wells.models import Well

                # Unlink before deleting so the FK's SET_NULL is not what does
                # it — an explicit clear is easier to read than a side effect.
                SystemFacility.objects.filter(system=system).update(well=None)
                Well.objects.filter(
                    well_registration_id__startswith=WELL_ID_PREFIX
                ).delete()

            SystemFacility.objects.filter(system=system).delete()
            system.delete()
            EnvirofactsCache.objects.filter(pwsid=PWSID).delete()

        self.stdout.write(
            f"  Flush: removed {removed[0]} results, {removed[1]} events and "
            f"the {PWSID} system."
        )
