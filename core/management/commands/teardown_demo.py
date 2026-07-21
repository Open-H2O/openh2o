# SPDX-License-Identifier: AGPL-3.0-or-later
"""Surgically remove the retired Kaweah and Demo-Valley (Fresno) demo data.

WHY this command exists (Phase 53-01). openh2o.com carried Kaweah AND Merced at
once, so the dashboard's "Total Usage" silently summed two basins. The v1.9
Merced Demonstration must show ONE basin cleanly. This command deletes every
Kaweah and Demo-Valley object in a single atomic transaction, leaving the Merced
demo and all shared reference data untouched — which also resolves the
dashboard-totals commingling as a side effect.

It is DELETE-ONLY (no reseed) and IDEMPOTENT: a second run, or a run against a
basin that is already gone, is a clean no-op, not a crash.

Unlike ``seed_demo_data`` and ``seed_merced``, this command does NOT require a
full deployment. Its module-scope ``wells``/``datasync`` imports keep resolving
under demotion (those apps stay in INSTALLED_APPS, model-only), and a delete
against an empty table is the no-op the paragraph above already promises. A
deletion command cannot leave a switched-off module populated, so there is
nothing here for the schema-residency assertions to catch.

WHY it is a new command and not a chain of the existing ``--flush`` paths.
``seed_demo_data._flush`` deletes every ``WY ...`` ReportingPeriod — the SHARED
water-year buckets Merced also lives in — and both existing flushes delete their
own SiteConfig. SiteConfig is a SINGLETON (its ``save()`` refuses a second row),
so on a real deployment there is exactly one; deleting it would break the app.
This command therefore preserves ALL shared reference data: ReportingPeriod,
WaterType, WaterRightType, ReportTemplate, roles, DataSource, and SiteConfig.

Every delete keys off the basin's Boundary name + its ID prefixes
(Kaweah ``KAW-*`` / Demo Valley ``DEMO-*``) — never off a global filter like
``name__startswith="WY "``. Ids are resolved up front, before any delete, so the
SET_NULL relationships (``Sensor.well``, ``RechargeSite.zone``,
``PointOfDiversion.water_right``) cannot strand a child row.

Flags: ``--kaweah-only`` / ``--fresno-only`` for surgical use; the default
removes both.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounting.models import (
    AllocationPlan,
    WaterAccount,
    WaterAccountParcel,
)
from datasync.models import MonitoredStation
from geography.models import Boundary, Zone
from measurements.models import Meter, MeterReading, Sensor, SensorMeasurement
from parcels.models import Parcel, ParcelLedger, UsageLocation
from wells.models import (
    MonitoringWell,
    Well,
    WellIrrigatedParcel,
    WellMeter,
)

# Each basin is keyed by its Boundary name plus the ID prefixes its seed used.
# A None prefix means "no clean ID prefix" — resolve those objects relationally
# (Demo Valley parcels via the boundary's zones; its wells via the parcel links).
BASINS = {
    "kaweah": {
        "label": "Kaweah",
        "boundary_name": "Kaweah Subbasin",
        "parcel_prefix": "KAW-APN-",
        "well_prefix": "KAW-W-",
        "account_prefix": "KAW-ACCT-",
        "right_prefix": "KAW-WR-",
        # Stations the retired Kaweah demo placed ABOVE the subbasin (Terminus
        # Dam, Three Rivers) sit outside the boundary polygon, so the spatial
        # sweep alone misses them. List them explicitly so teardown still cleans
        # any leftover from an older install.
        "station_ext_ids": [
            "TRM", "KWR", "VIS", "11210100", "11208730", "54",
            "KAW-GWL-01", "KAW-GWL-02",
        ],
    },
    "fresno": {
        "label": "Demo Valley (Fresno)",
        "boundary_name": "Demo Valley GSA",
        "parcel_prefix": None,
        "well_prefix": None,
        "account_prefix": "DEMO-",
        "right_prefix": "DEMO-",
        "station_ext_ids": ["CHW", "11253500", "MDR"],
    },
}


class Command(BaseCommand):
    help = (
        "Delete ALL Kaweah and Demo-Valley (Fresno) demo data in one atomic "
        "transaction, preserving Merced and all shared reference data. "
        "Idempotent; delete-only (no reseed)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--kaweah-only", action="store_true",
            help="Remove only the Kaweah Subbasin demo data.",
        )
        parser.add_argument(
            "--fresno-only", action="store_true",
            help="Remove only the Demo Valley (Fresno) demo data.",
        )

    def handle(self, *args, **options):
        if options["kaweah_only"] and options["fresno_only"]:
            raise CommandError(
                "Pass at most one of --kaweah-only / --fresno-only "
                "(omit both to remove both)."
            )
        if options["kaweah_only"]:
            keys = ["kaweah"]
        elif options["fresno_only"]:
            keys = ["fresno"]
        else:
            keys = ["kaweah", "fresno"]

        with transaction.atomic():
            all_counts = {}
            for key in keys:
                self.stdout.write(self.style.MIGRATE_HEADING(
                    f"\nTearing down {BASINS[key]['label']}..."))
                all_counts[key] = self._teardown_basin(BASINS[key])

        self._summary(all_counts, keys)

    # ------------------------------------------------------------------
    def _del(self, qs, label, counts):
        """Delete a queryset, recording how many of the TARGET rows went."""
        n = qs.count()
        if n:
            qs.delete()
            counts[label] = counts.get(label, 0) + n
            self.stdout.write(f"    - {n} {label}")

    # ------------------------------------------------------------------
    def _teardown_basin(self, cfg):
        # Local imports: `recharge` and `surface` are optional modules, so these
        # must not run at module scope (ISS-072, Phase 87).
        from recharge.models import RechargeSite
        from surface.models import (
            DiversionRecord,
            PointOfDiversion,
            PointOfDiversionParcel,
            WaterRight,
            WaterRightParcel,
        )

        counts = {}
        boundary = Boundary.objects.filter(name=cfg["boundary_name"]).first()
        zone_ids = list(boundary.zones.values_list("id", flat=True)) if boundary else []

        # --- Resolve every id set BEFORE deleting anything ---
        if cfg["parcel_prefix"]:
            parcels = Parcel.objects.filter(
                parcel_number__startswith=cfg["parcel_prefix"])
        else:
            # No ID prefix (Demo Valley): the boundary's zones own its parcels.
            parcels = Parcel.objects.filter(
                parcel_zones__zone_id__in=zone_ids).distinct()
        parcel_ids = list(parcels.values_list("id", flat=True))

        if cfg["well_prefix"]:
            well_ids = list(Well.objects.filter(
                well_registration_id__startswith=cfg["well_prefix"]
            ).values_list("id", flat=True))
        else:
            well_ids = list(WellIrrigatedParcel.objects.filter(
                parcel_id__in=parcel_ids
            ).values_list("well_id", flat=True).distinct())

        account_ids = list(WaterAccount.objects.filter(
            account_number__startswith=cfg["account_prefix"]
        ).values_list("id", flat=True))
        right_ids = list(WaterRight.objects.filter(
            right_id__startswith=cfg["right_prefix"]
        ).values_list("id", flat=True))
        pod_ids = list(PointOfDiversion.objects.filter(
            water_right_id__in=right_ids).values_list("id", flat=True))

        # Sensor.well and RechargeSite.zone are SET_NULL, so capture their ids
        # now — once the wells/zones go, the link would read NULL.
        sensor_ids = list(Sensor.objects.filter(
            well_id__in=well_ids).values_list("id", flat=True))
        meter_ids = list(WellMeter.objects.filter(
            well_id__in=well_ids).values_list("meter_id", flat=True).distinct())
        recharge_ids = (
            list(RechargeSite.objects.filter(
                zone_id__in=zone_ids).values_list("id", flat=True))
            if zone_ids else []
        )
        # Monitoring stations: a spatial sweep of the polygon catches every
        # station inside it (seeded OR later discovered), and the explicit seed
        # IDs catch the ones the seed placed in the foothills ABOVE the basin
        # (outside the polygon). Union the two so none linger on the map. The
        # explicit list also lets a re-run clear stragglers after the boundary
        # is already gone.
        station_id_set = set()
        if boundary is not None:
            station_id_set.update(MonitoredStation.objects.filter(
                location__within=boundary.geometry).values_list("id", flat=True))
        if cfg.get("station_ext_ids"):
            station_id_set.update(MonitoredStation.objects.filter(
                external_station_id__in=cfg["station_ext_ids"]
            ).values_list("id", flat=True))
        station_ids = list(station_id_set)

        if not any([boundary, parcel_ids, well_ids, account_ids, right_ids,
                    recharge_ids, station_ids]):
            self.stdout.write("    (already absent — no-op)")
            return counts

        # --- Delete children -> parents (the seed _flush cascade order) ---
        self._del(ParcelLedger.objects.filter(parcel_id__in=parcel_ids),
                  "ledger rows", counts)
        self._del(WaterAccountParcel.objects.filter(parcel_id__in=parcel_ids),
                  "account-parcel links", counts)
        self._del(WellIrrigatedParcel.objects.filter(parcel_id__in=parcel_ids),
                  "well-parcel links", counts)
        self._del(PointOfDiversionParcel.objects.filter(parcel_id__in=parcel_ids),
                  "POD-parcel links", counts)
        self._del(WaterRightParcel.objects.filter(parcel_id__in=parcel_ids),
                  "right-parcel links", counts)
        self._del(UsageLocation.objects.filter(parcel_id__in=parcel_ids),
                  "usage locations", counts)

        self._del(SensorMeasurement.objects.filter(sensor_id__in=sensor_ids),
                  "sensor measurements", counts)
        self._del(Sensor.objects.filter(id__in=sensor_ids), "sensors", counts)
        self._del(MeterReading.objects.filter(meter_id__in=meter_ids),
                  "meter readings", counts)
        self._del(WellMeter.objects.filter(well_id__in=well_ids),
                  "well-meter links", counts)
        self._del(MonitoringWell.objects.filter(well_id__in=well_ids),
                  "monitoring wells", counts)
        self._del(Meter.objects.filter(id__in=meter_ids), "meters", counts)
        self._del(Well.objects.filter(id__in=well_ids), "wells", counts)

        self._del(DiversionRecord.objects.filter(point_of_diversion_id__in=pod_ids),
                  "diversion records", counts)
        self._del(PointOfDiversion.objects.filter(id__in=pod_ids),
                  "points of diversion", counts)
        self._del(WaterRight.objects.filter(id__in=right_ids), "water rights", counts)

        self._del(AllocationPlan.objects.filter(zone_id__in=zone_ids),
                  "allocations", counts)
        self._del(WaterAccount.objects.filter(id__in=account_ids),
                  "water accounts", counts)

        self._del(RechargeSite.objects.filter(id__in=recharge_ids),
                  "recharge sites", counts)
        self._del(MonitoredStation.objects.filter(id__in=station_ids),
                  "monitored stations", counts)

        # Parcels (cascades ParcelZone), then zones (cascades any remaining
        # ParcelZone / AllocationPlan / carryover), then the boundary itself
        # (cascades zones + flowlines). NEVER SiteConfig — it is shared.
        self._del(Parcel.objects.filter(id__in=parcel_ids), "parcels", counts)
        self._del(Zone.objects.filter(id__in=zone_ids), "zones", counts)
        if boundary is not None:
            boundary.delete()
            counts["boundary"] = 1
            self.stdout.write("    - 1 boundary")

        return counts

    # ------------------------------------------------------------------
    def _summary(self, all_counts, keys):
        self.stdout.write(self.style.SUCCESS(
            "\nTeardown complete. Shared reference data preserved "
            "(reporting periods, water types, report templates, roles, "
            "DataSources, SiteConfig)."
        ))
        for key in keys:
            counts = all_counts.get(key, {})
            label = BASINS[key]["label"]
            total = sum(counts.values())
            if total == 0:
                self.stdout.write(f"  {label}: nothing to remove (already absent).")
            else:
                self.stdout.write(
                    f"  {label}: {total} rows removed — "
                    f"{counts.get('parcels', 0)} parcels, "
                    f"{counts.get('water accounts', 0)} accounts, "
                    f"{counts.get('wells', 0)} wells, "
                    f"{counts.get('ledger rows', 0)} ledger rows, "
                    f"{counts.get('boundary', 0)} boundary."
                )
