# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build Merced recharge areas + their diversion links from Brent's QGIS pick.

WHY this exists. v1.9 placed two recharge basins as fixed-degree squares at
hardcoded coordinates (seed_merced_recharge). Phase 62 re-does them the same
trustworthy way the 74 crop fields were done: Brent hand-selects real parcels in
QGIS against the satellite + canal/river layers, and the export drives the seed.
Two hand-picked scenarios, both real-hydrography recharge tied to a real point of
diversion (POD):

  1. EL NIDO CANAL — PURE recharge. Five open, non-agricultural parcels beside
     the El Nido Canal (data/merced/selected_basins.geojson) become spreading
     basins. Each is fed by its own recharge intake snapped ONTO the real El Nido
     Canal flowline. No crops, no ET — water diverted from the canal purely to
     percolate into the aquifer. These intakes are NEW, recharge-only PODs,
     distinct from the existing El Nido ag headgate (MER-POD-007).

  2. MERCED RIVER — DUAL-PURPOSE (Flood-MAR). Two working cropland parcels on the
     Merced River (data/merced/selected_river_ag_parcels.geojson, served by the
     existing MER-POD-009 Merced River diversion) are normal ag parcels most of
     the year (seeded as places-of-use by seed_merced_parcels_from_selection) AND
     carry a Flood-MAR recharge area on the SAME footprint, linked to that SAME
     Merced River diversion, that floods during storm events. The dual purpose is
     real: crops + storm recharge, off one diversion.

Each recharge area is tied to its diversion through a RechargeSitePOD link
(surfaced on the detail pages, NOT a flow line on the map). Every POD this
command places sits on the real waterway: source_flowline + stream_name are read
FROM the flowline, never typed (geography.placement, the ISS-053 archetype rule).

REPLACES seed_merced_recharge in the seed sequence; runs AFTER
seed_merced_parcels_from_selection (it needs MER-POD-009) and BEFORE
seed_merced_recharge_events (which deposits the managed/storm recharge).

Idempotent + Merced-scoped. A re-run wipes Merced Irrigation District recharge
areas (old hardcoded AND prior selection runs, keyed on operator), their POD
links, the recharge-intake PODs this command owns (MER-BPOD-*), and ONLY the
managed ``basin_recharge_pool`` slice for the Merced GSA zones — never the
engine's ``incidental_recharge_pool`` or the rollover's ``allocation_carryover``
(RESEARCH Pitfall 1). It never touches Kaweah/Demo rows.
"""
import json
import os
from decimal import Decimal

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounting.models import AllocationCarryover
from accounting.services import BASIN_RECHARGE_POOL
from geography.models import Boundary, Flowline, Zone
from geography.placement import nearest_flowline, snap_to_flowline
from recharge.models import RechargeSite, RechargeSitePOD
from surface.models import PointOfDiversion

DATA_DIR = os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "data", "merced"
)
BASINS_FIXTURE = os.path.join(DATA_DIR, "selected_basins.geojson")
RIVER_FIXTURE = os.path.join(DATA_DIR, "selected_river_ag_parcels.geojson")

# Every Merced recharge area carries this operator — the single, readable key the
# wipe and the recharge-events seed use to find "the Merced basins" without
# touching Kaweah ("Kaweah Delta WCD"…) or Demo Valley ("Demo Valley GSA").
MID_OPERATOR = "Merced Irrigation District"
# PODs this command owns (the El Nido recharge intakes). The wipe deletes these by
# prefix so a removed basin never leaves an orphan intake behind. Distinct from
# the operational MER-POD-### diversions, which this command never deletes.
BASIN_POD_PREFIX = "MER-BPOD-"
# Capacity convention: ~5 ft ponded depth × footprint acres, matching the prior
# two basins exactly (110 ac → 550 AF, 85 ac → 425 AF). Managed/storm recharge
# pools to the GSA basin pool, so this sizes the pool, NOT the closure headline.
PONDED_DEPTH_FT = Decimal("5.0")
MERCED_BOUNDARY = "Merced Subbasin"
GSA_BASIN_CODE = "5-022.04"
# The existing Merced River diversion the Flood-MAR cropland is served by.
RIVER_POD_CODE = "MER-POD-009"


class Command(BaseCommand):
    help = (
        "Build Merced recharge areas from Brent's QGIS selection: El Nido Canal "
        "spreading basins (new canal intakes) + Merced River Flood-MAR cropland "
        "(linked to MER-POD-009). Replaces the hardcoded seed_merced_recharge; "
        "idempotent, Merced-scoped."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        basins = self._load(BASINS_FIXTURE, "selected_basins.geojson")
        river = self._load(RIVER_FIXTURE, "selected_river_ag_parcels.geojson")

        boundary = Boundary.objects.filter(name=MERCED_BOUNDARY).first()
        if boundary is None:
            raise CommandError(
                f'"{MERCED_BOUNDARY}" boundary not found — run seed_merced_base '
                "and auto_populate first."
            )
        gsa_zones = list(
            Zone.objects.filter(
                zone_type="management_area", basin_code=GSA_BASIN_CODE
            )
        )
        if not gsa_zones:
            raise CommandError("No Merced GSA zones found. Run seed_merced_gsas first.")

        self._flush(gsa_zones)

        n_basins, n_intakes = self._seed_el_nido(basins, boundary, gsa_zones)
        n_floodmar = self._seed_river_floodmar(river, gsa_zones)

        self.stdout.write(self.style.SUCCESS(
            f"\nMerced recharge areas rebuilt from QGIS selection:\n"
            f"  EL NIDO (pure recharge) — {n_basins} spreading basins, each fed by "
            f"a recharge intake on the El Nido Canal ({n_intakes} intakes placed)\n"
            f"  MERCED RIVER (Flood-MAR) — {n_floodmar} dual-purpose recharge areas "
            f"on cropland served by {RIVER_POD_CODE}"
        ))

    # ------------------------------------------------------------------
    # El Nido Canal — pure recharge basins, each on its own canal intake
    # ------------------------------------------------------------------
    def _seed_el_nido(self, features, boundary, gsa_zones):
        n_basins = n_intakes = 0
        for idx, ft in enumerate(features, start=1):
            props = ft["properties"]
            geom = self._multipolygon(ft["geometry"])
            name = props["name"]
            feeds_via = (props.get("feeds_via") or "").strip()
            capacity = self._capacity(props, geom)

            site, _ = RechargeSite.objects.update_or_create(
                name=name,
                defaults={
                    "site_type": "spreading_basin",
                    "location": geom.centroid,
                    "geometry": geom,
                    "capacity_acre_feet": capacity,
                    "status": "active",
                    "operator": MID_OPERATOR,
                    "zone": self._gsa_for(geom, gsa_zones),
                    "notes": (
                        f"Pure-recharge spreading basin on open non-agricultural "
                        f"land beside the {feeds_via}. Flooded when water is "
                        f"diverted from the canal to percolate into the aquifer; "
                        f"no crops, no ET. Hand-selected in QGIS (Phase 62)."
                    ),
                },
            )
            n_basins += 1

            # The intake: a recharge-only POD snapped ONTO the named canal nearest
            # this basin (never a geometric offset — RESEARCH Pitfall 3).
            line = self._named_flowline(boundary, feeds_via, geom.centroid)
            if line is None:
                raise CommandError(
                    f'No "{feeds_via}" flowline in {MERCED_BOUNDARY} for {name}; '
                    "base layer incomplete or feeds_via misspelled."
                )
            pod, _ = PointOfDiversion.objects.update_or_create(
                name=f"{BASIN_POD_PREFIX}{idx:03d} {name} Intake",
                defaults={
                    "water_right": None,  # storm/high-flow recharge take, no consumptive right
                    "location": snap_to_flowline(geom.centroid, line),
                    "stream_name": line.name,        # read FROM the flowline
                    "source_flowline": line,
                    "status": "active",
                    "notes": (
                        f"Recharge intake on the {line.name}, feeding {name}. "
                        f"Operated during high-flow/storm events to divert water "
                        f"for managed aquifer recharge."
                    ),
                },
            )
            n_intakes += 1
            RechargeSitePOD.objects.update_or_create(
                recharge_site=site, point_of_diversion=pod,
                defaults={"notes": f"{name} is filled from the {line.name}."},
            )
        return n_basins, n_intakes

    # ------------------------------------------------------------------
    # Merced River — dual-purpose Flood-MAR on cropland (MER-POD-009)
    # ------------------------------------------------------------------
    def _seed_river_floodmar(self, features, gsa_zones):
        river_pod = PointOfDiversion.objects.filter(
            name__startswith=RIVER_POD_CODE
        ).first()
        if river_pod is None:
            raise CommandError(
                f"{RIVER_POD_CODE} not found — run seed_merced_operations first."
            )
        n = 0
        for ft in features:
            props = ft["properties"]
            geom = self._multipolygon(ft["geometry"])
            name = f"{props['name']} (Flood-MAR)"
            capacity = self._capacity(props, geom)

            site, _ = RechargeSite.objects.update_or_create(
                name=name,
                defaults={
                    "site_type": "spreading_basin",
                    "location": geom.centroid,
                    "geometry": geom,
                    "capacity_acre_feet": capacity,
                    "status": "active",
                    "operator": MID_OPERATOR,
                    "zone": self._gsa_for(geom, gsa_zones),
                    "notes": (
                        f"Dual-purpose Flood-MAR recharge area on working "
                        f"cropland served by the Merced River diversion "
                        f"({RIVER_POD_CODE}). Normal agricultural use most of the "
                        f"year; deliberately flooded during storm events to "
                        f"recharge the aquifer. Hand-selected in QGIS (Phase 62)."
                    ),
                },
            )
            # Link to the SAME Merced River diversion that irrigates the cropland —
            # so MER-POD-009's page shows both the fields it serves and the
            # recharge areas it floods (the dual purpose, made visible).
            RechargeSitePOD.objects.update_or_create(
                recharge_site=site, point_of_diversion=river_pod,
                defaults={"notes": (
                    f"{name} is flooded for recharge from the Merced River via "
                    f"{RIVER_POD_CODE} during storm events."
                )},
            )
            n += 1
        return n

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _load(path, label):
        if not os.path.exists(path):
            raise CommandError(
                f"Selection fixture not found: {path}\n"
                f"Export the hand-picked features to {label} from the QGIS picker."
            )
        with open(path) as f:
            features = json.load(f)["features"]
        if not features:
            raise CommandError(f"{label} has no features.")
        return features

    @staticmethod
    def _multipolygon(geometry):
        geom = GEOSGeometry(json.dumps(geometry))
        if geom.geom_type == "Polygon":
            geom = MultiPolygon(geom)
        if geom.srid is None:
            geom.srid = 4326
        return geom

    @staticmethod
    def _capacity(props, geom):
        """Capacity in AF: an explicit hint if present, else ~5 ft × footprint acres.

        ``GIS_ACRES`` carries the hand-pick acreage; if it is absent the true
        equal-area footprint (EPSG:3310) is used so the number is never guessed.
        """
        hint = (str(props.get("capacity_acre_feet") or "")).strip()
        if hint:
            return Decimal(hint)
        acres = props.get("GIS_ACRES")
        if acres is None:
            from recharge.geometry import SQ_M_PER_ACRE
            acres = geom.transform(3310, clone=True).area / SQ_M_PER_ACRE
        return (Decimal(str(acres)) * PONDED_DEPTH_FT).quantize(Decimal("0.1"))

    @staticmethod
    def _named_flowline(boundary, name, near_point):
        """The real Flowline named ``name`` nearest ``near_point``.

        Mirrors seed_merced_operations._named_line's soft-type preference: a
        watercourse is many 3DHP segments of MIXED feature_type, so prefer "Canal"
        segments for a canal feed (a recharge intake should render on the canal),
        falling back to every named segment. Returns the nearest qualifying
        segment in true metres, or None if the name matches nothing.
        """
        segs = list(Flowline.objects.filter(boundary=boundary, name__iexact=name))
        if not segs:
            return None
        prefer = "Canal" if "canal" in name.lower() else "Channel Line"
        typed = [s for s in segs if prefer in (s.feature_type or "")]
        return nearest_flowline(near_point, typed or segs)

    @staticmethod
    def _gsa_for(geom, zones):
        """The GSA management area containing this footprint (nearest as fallback)."""
        c = geom.centroid
        for z in zones:
            if z.geometry.contains(c):
                return z
        return min(zones, key=lambda z: z.geometry.distance(c)) if zones else None

    def _flush(self, gsa_zones):
        """Remove Merced recharge areas + the intakes/links/pool slice we own.

        Scoped by operator (Merced Irrigation District) so it clears BOTH the old
        hardcoded basins and any prior selection run, and by the MER-BPOD- prefix
        for the intakes — never the operational MER-POD-### diversions, never
        Kaweah/Demo. The pool delete is scoped to ``basin_recharge_pool`` ONLY, so
        the engine's incidental pool and the rollover carryover survive.
        """
        site_ids = list(
            RechargeSite.objects.filter(operator=MID_OPERATOR)
            .values_list("id", flat=True)
        )
        intake_ids = list(
            PointOfDiversion.objects.filter(name__startswith=BASIN_POD_PREFIX)
            .values_list("id", flat=True)
        )
        RechargeSitePOD.objects.filter(recharge_site_id__in=site_ids).delete()
        RechargeSitePOD.objects.filter(point_of_diversion_id__in=intake_ids).delete()
        AllocationCarryover.objects.filter(
            zone_id__in=[z.id for z in gsa_zones], origin=BASIN_RECHARGE_POOL
        ).delete()
        RechargeSite.objects.filter(id__in=site_ids).delete()
        PointOfDiversion.objects.filter(id__in=intake_ids).delete()
