# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Build the Merced place-of-use parcels from Brent's QGIS field selection.

WHY this exists: parcels were previously placed by guessing coordinates,
which repeatedly landed fields on towns or bare ground because the platform
has no land-use layer. This command instead reads REAL DWR surveyed crop
fields that Brent hand-selected in QGIS (data/merced/parcel_selection/), each
tagged with the diversion that serves it and its water source. The geometry
is real, the served-by relationship is Brent's judgment, not a heuristic.

It REPLACES the guessed parcels/wells/links from seed_merced_operations
(which still owns the water rights + points of diversion). Run order:

    python manage.py seed_merced_base
    python manage.py seed_merced_operations          # rights + PODs
    python manage.py seed_merced_parcels_from_selection   # real parcels

Input fixture: data/merced/selected_parcels.geojson (EPSG:4326), one feature
per chosen field, properties:
    served_by    = POD code, e.g. "MER-POD-004"  (matches PointOfDiversion
                   whose name starts with that code); blank = not served by
                   surface water
    water_source = "surface" | "groundwater" | "conjunctive"
    crop_class, MAIN_CROP, COUNTY, ACRES, UniqueID  (carried for provenance)

Idempotent, additive: only touches MER- rows, never Kaweah/Demo.
"""
import json
import os
from decimal import Decimal

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from geography.models import ParcelZone, Zone
from parcels.models import Parcel
from surface.models import (
    PointOfDiversion, PointOfDiversionParcel, WaterRight, WaterRightParcel,
)
from wells.models import Well, WellIrrigatedParcel, WellType

FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "..", "..",
    "data", "merced", "selected_parcels.geojson",
)
GROUNDWATER_SOURCES = {"groundwater", "conjunctive"}

# Demo operators (parcel owner_name) so account-level accounting has real
# groups to roll up. A shared well belongs to one grower (they own all its
# fields); each canal district and the scattered groundwater fields get one too.
OWNER_BY_WELLGROUP = {
    "TI-W-1": "Turner Island Farms LLC",
    "TI-W-2": "Sandy Mush Growers",
}
OWNER_BY_POD = {
    "MER-POD-004": "Atwater Ranch Partners",
    "MER-POD-005": "Le Grand Orchards Inc.",
    "MER-POD-006": "Stevinson Land & Cattle",
    "MER-POD-007": "Plainsburg Ag Holdings",
    "MER-POD-008": "Crocker Bottoms Farming",
    "MER-POD-009": "San Joaquin Bottomlands Ranch",
}
GW_SOLO_OWNERS = [
    "Merced Valley Farms LLC", "Cressey Family Farms", "Snelling Ranch Co.",
]


class Command(BaseCommand):
    help = (
        "Rebuild Merced parcels + diversion/well links from Brent's QGIS "
        "field selection (data/merced/selected_parcels.geojson). Replaces the "
        "guessed parcels/wells from seed_merced_operations; keeps rights/PODs."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        if not os.path.exists(FIXTURE):
            raise CommandError(
                f"Selection fixture not found: {FIXTURE}\n"
                "Open data/merced/parcel_selection/merced_parcel_picker.qgz in "
                "QGIS, tag fields with served_by + water_source, save, then "
                "extract the tagged fields to that geojson."
            )
        with open(FIXTURE) as f:
            features = json.load(f)["features"]
        if not features:
            raise CommandError("Selection fixture has no features.")

        self._flush()

        # Resolve PODs by their code prefix once.
        pods_by_code = {}
        for code in {
            (ft["properties"].get("served_by") or "").strip()
            for ft in features
        }:
            if not code:
                continue
            pod = PointOfDiversion.objects.filter(name__startswith=code).first()
            if pod is None:
                raise CommandError(
                    f"served_by '{code}' matches no PointOfDiversion. Run "
                    "seed_merced_operations first."
                )
            pods_by_code[code] = pod

        ag_well_type, _ = WellType.objects.get_or_create(
            name="Agricultural",
            defaults={"description": "Agricultural irrigation well"},
        )

        # GSA zones (groundwater authority). Every parcel falls in exactly one.
        gsa_zones = list(Zone.objects.filter(
            zone_type="management_area", basin_code="5-022.04"))
        if not gsa_zones:
            raise CommandError(
                "No Merced GSA zones found. Run seed_merced_gsas first.")

        # --- Parcels (real geometry) + per-POD grouping for fractions ---
        parcels = []
        pod_to_parcels = {}     # pod.pk -> [parcels]
        wells = []
        well_members = {}       # well_group key -> [(parcel, geom)]
        seq = well_seq = gsa_links = gw_solo_i = 0
        for ft in features:
            seq += 1
            props = ft["properties"]
            geom = GEOSGeometry(json.dumps(ft["geometry"]))
            if geom.geom_type == "Polygon":
                geom = MultiPolygon(geom)
            served = (props.get("served_by") or "").strip()
            source = (props.get("water_source") or "").strip().lower()
            wg = (props.get("well_group") or "").strip()
            crop = props.get("MAIN_CROP") or props.get("crop_class") or "?"
            note = (
                f"DWR field {props.get('UniqueID', '?')} | {props.get('crop_class', '')}"
                f" ({crop}) | {props.get('COUNTY', '')} | source={source or 'n/a'}"
            )
            # Operator/owner (drives account-level accounting).
            if wg in OWNER_BY_WELLGROUP:
                owner = OWNER_BY_WELLGROUP[wg]
            elif served:
                owner = OWNER_BY_POD.get(served, "")
            else:
                owner = GW_SOLO_OWNERS[gw_solo_i % len(GW_SOLO_OWNERS)]
                gw_solo_i += 1
            parcel, _ = Parcel.objects.update_or_create(
                parcel_number=f"MER-APN-{seq:03d}",
                defaults={
                    "owner_name": owner,
                    "geometry": geom,
                    "status": "active",
                    "notes": note,
                },
            )
            parcels.append(parcel)

            # GSA association: every parcel sits in one GSA (groundwater
            # authority), independent of any surface-water delivery.
            gsa = self._gsa_for(geom, gsa_zones)
            if gsa is not None:
                ParcelZone.objects.update_or_create(parcel=parcel, zone=gsa)
                gsa_links += 1

            # Surface delivery (POD link) is created ONLY for fields a canal
            # actually serves — surface + conjunctive carry served_by;
            # groundwater fields had their canal tag cleared, so they get none.
            if served:
                pod_to_parcels.setdefault(pods_by_code[served].pk, []).append(parcel)

            # Collect groundwater/conjunctive fields for well assignment after
            # the loop. Fields sharing a well_group share ONE well (a single
            # high-capacity well irrigating many parcels); ungrouped fields get
            # their own well.
            if source in GROUNDWATER_SOURCES:
                well_members.setdefault(wg or f"solo-{seq}", []).append((parcel, geom))

        # --- Wells: one per well_group (shared) or per ungrouped field. A
        # shared well sits at the centroid of the parcels it irrigates; each
        # member gets an equal share (fractions sum to 1.0 per well). ---
        for key, members in well_members.items():
            well_seq += 1
            union = members[0][1]
            for _, gm in members[1:]:
                union = union.union(gm)
            centroid = union.centroid
            shared = len(members) > 1
            name = (f"Shared ag well ({key}) — {len(members)} parcels"
                    if shared else f"Ag well on {members[0][0].parcel_number}")
            well, _ = Well.objects.update_or_create(
                well_registration_id=f"MER-W-{well_seq:03d}",
                defaults={"name": name, "well_type": ag_well_type,
                          "location": centroid, "status": "active"},
            )
            frac = Decimal(str(round(1.0 / len(members), 4)))
            for parcel, _g in members:
                WellIrrigatedParcel.objects.update_or_create(
                    well=well, parcel=parcel, defaults={"fraction": frac},
                )
            wells.append(well)

        # --- POD -> parcel links, fraction normalized within each POD ---
        podp = 0
        for pod_pk, cluster in pod_to_parcels.items():
            pod = PointOfDiversion.objects.get(pk=pod_pk)
            fraction = Decimal(str(round(1.0 / len(cluster), 4)))
            for parcel in cluster:
                PointOfDiversionParcel.objects.update_or_create(
                    point_of_diversion=pod, parcel=parcel,
                    defaults={"fraction": fraction},
                )
                podp += 1

        # --- WaterRight -> parcel links: a right serves its PODs' parcels ---
        wrp = 0
        right_to_parcels = {}
        for pod_pk, cluster in pod_to_parcels.items():
            pod = PointOfDiversion.objects.get(pk=pod_pk)
            bucket = right_to_parcels.setdefault(pod.water_right_id, [])
            for parcel in cluster:
                if parcel not in bucket:
                    bucket.append(parcel)
        for wr_id, bucket in right_to_parcels.items():
            wr = WaterRight.objects.get(pk=wr_id)
            for parcel in bucket:
                WaterRightParcel.objects.update_or_create(
                    water_right=wr, parcel=parcel,
                )
                wrp += 1

        self.stdout.write(self.style.SUCCESS(
            f"\nMerced parcels rebuilt from QGIS selection:\n"
            f"  {len(parcels)} parcels (real DWR field geometry)\n"
            f"  SURFACE DISTRICT — {podp} POD-parcel deliveries across "
            f"{len(pod_to_parcels)} diversions; {wrp} water-right-parcel links\n"
            f"  GSA (groundwater) — {len(wells)} wells "
            f"({sum(1 for m in well_members.values() if len(m) > 1)} shared "
            f"across multiple parcels); {gsa_links} parcels in their GSA"
        ))

    @staticmethod
    def _gsa_for(geom, zones):
        """The GSA management area containing this parcel (nearest as fallback)."""
        c = geom.centroid
        for z in zones:
            if z.geometry.contains(c):
                return z
        return min(zones, key=lambda z: z.geometry.distance(c)) if zones else None

    @staticmethod
    def _flush():
        """Remove prior MER parcels/wells and their links (keep rights+PODs)."""
        parcel_ids = list(
            Parcel.objects.filter(parcel_number__startswith="MER-APN-")
            .values_list("id", flat=True)
        )
        well_ids = list(
            Well.objects.filter(well_registration_id__startswith="MER-W-")
            .values_list("id", flat=True)
        )
        WellIrrigatedParcel.objects.filter(well_id__in=well_ids).delete()
        WellIrrigatedParcel.objects.filter(parcel_id__in=parcel_ids).delete()
        PointOfDiversionParcel.objects.filter(parcel_id__in=parcel_ids).delete()
        WaterRightParcel.objects.filter(parcel_id__in=parcel_ids).delete()
        Well.objects.filter(id__in=well_ids).delete()
        Parcel.objects.filter(id__in=parcel_ids).delete()
