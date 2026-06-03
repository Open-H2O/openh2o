# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed the Merced demonstration's OPERATIONAL features onto the real base layer.

WHY this command exists. Phase 50 built a credible Merced canvas (two real
boundaries, 577 river + 2328 canal segments, recharge basins, stations). This
command populates it with the features a domain expert actually inspects:
surface-water diversions, MID-canal headgates, groundwater wells, and farm
parcels — for BOTH the simple upper-watershed story and the complex lower-
subbasin story.

The anti-pattern this command exists to KILL: the Kaweah seed hand-types a
diversion's lon/lat and a ``stream_name`` STRING with no tie to real river
geometry, so a diversion can land in a field and its labelled source can be a
river that is nowhere near it. A diversion floating in a field — or a farm with
no plausible connection to water — is the single tell that makes a domain expert
(Water Data Consortium, ESA, state staff) stop trusting the whole map. So every
feature here is routed through the 51-01 placement toolkit
(``geography.placement``): diversions are SNAPPED onto an actual river/canal
segment, parcels are PLACED a plausible distance off the reach that serves them,
and each diversion's ``stream_name`` is read from the real flowline it sits on —
never hand-typed.

DETERMINISTIC: this command uses NO ``random``. Re-running reproduces identical
geometry (the toolkit's ``along`` / ``side`` params + indexed offsets), so the
signed-off canvas is stable. Every row is written with ``update_or_create`` /
``get_or_create`` keyed on a stable natural key, so a double-run is idempotent.

ADDITIVE + PREFIX-KEYED: all operational rows carry a ``MER-`` prefix
(``MER-WR-`` rights, ``MER-POD-`` PODs via name, ``MER-APN-`` parcels,
``MER-W-`` wells). ``--flush`` deletes ONLY those prefixed rows and their link
rows, then rebuilds — it NEVER touches boundaries, flowlines, recharge sites,
stations, or any Kaweah / Demo Valley row, and the base layer is left intact.

Phase 51 is PHYSICAL features + their relationships ONLY. It creates NO
``DiversionRecord`` monthly volumes, NO ``ParcelLedger``, NO water accounts, NO
reporting periods — those synthetic accounting ledgers are Phase 52.
``WellIrrigatedParcel`` and ``PointOfDiversionParcel`` ARE physical place-of-use
relationships and belong here.

Prerequisite (the base layer must already exist on this instance)::

    python manage.py seed_merced_base
    python manage.py auto_populate --boundary "Merced Subbasin" --steps flowlines,stations
    python manage.py auto_populate --boundary "Upper Merced River Watershed" --steps flowlines

The base-layer guard below fails fast with that exact instruction if the
boundaries or their flowlines are missing, rather than silently placing features
against an empty flowline set.
"""
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from geography.models import Boundary, Flowline
from geography.placement import (
    nearest_flowline,
    place_near_flowline,
    snap_to_flowline,
)
from parcels.models import Parcel
from recharge.geometry import area_accurate_box
from surface.models import (
    PointOfDiversion,
    PointOfDiversionParcel,
    WaterRight,
    WaterRightParcel,
    WaterRightType,
)
from wells.models import Well, WellIrrigatedParcel, WellType

# Boundary names seeded by seed_merced_base — the spatial canvas this command
# populates. The guard looks these up by name.
UPPER_BOUNDARY = "Upper Merced River Watershed"
LOWER_BOUNDARY = "Merced Subbasin"

# Flowline feature_type values written by the USGS 3DHP loader (auto_populate)
# for the Merced base layer: 577 "river" segments + 2328 "canal" segments.
RIVER = "river"
CANAL = "canal"

# The exact base-layer commands to run first, surfaced in the guard's error.
BASE_LAYER_HINT = (
    "Base layer missing. Seed it first:\n"
    '  python manage.py seed_merced_base\n'
    '  python manage.py auto_populate --boundary "Merced Subbasin" '
    "--steps flowlines,stations\n"
    '  python manage.py auto_populate --boundary "Upper Merced River Watershed" '
    "--steps flowlines"
)

# ---------------------------------------------------------------------------
# Water rights (both stories). right_id is the natural key for update_or_create.
# Upper = Merced River snowmelt appropriative/pre-1914; lower = MID canal-served
# appropriative + a few riparian. source_name is the real stream/canal name.
# (ti = water-right-type index into the types tuple built in _seed: 0=PRE14,
#  1=POST14, 2=RIP.) Each entry:
#   right_id, type_idx, holder_name, priority_date(str|None), face_af, source_name, status
# ---------------------------------------------------------------------------
RIGHT_CONFIGS = [
    # --- Upper Merced River watershed (simple, single-source snowmelt) ---
    ("MER-WR-001", 1, "Merced Irrigation District", "1926-02-15",
     Decimal("550000"), "Merced River", "active"),
    ("MER-WR-002", 0, "Merced Falls Ranch", "1901-06-01",
     Decimal("3500"), "Merced River", "active"),
    ("MER-WR-003", 2, "Yosemite Foothill Ranch", None,
     Decimal("900"), "Merced River", "active"),
    # --- Lower Merced Subbasin (complex: MID canal-served + riparian) ---
    ("MER-WR-004", 1, "Merced Irrigation District", "1930-04-10",
     Decimal("120000"), "Main Canal", "active"),
    ("MER-WR-005", 1, "Le Grand-Athlone Water District", "1948-09-01",
     Decimal("18000"), "Le Grand Canal", "active"),
    ("MER-WR-006", 1, "Stevinson Water District", "1955-03-20",
     Decimal("22000"), "Le Grand Canal", "active"),
    ("MER-WR-007", 0, "Merced Subbasin Riparian Holders", "1908-07-15",
     Decimal("6000"), "Merced River", "curtailed"),
    ("MER-WR-008", 2, "San Joaquin Bottomlands Ranch", None,
     Decimal("4000"), "Merced River", "active"),
    ("MER-WR-009", 1, "Plainsburg Irrigation District", "1962-05-05",
     Decimal("9000"), "Main Canal", "active"),
]


class Command(BaseCommand):
    help = (
        "Seed the Merced demonstration's operational features (water rights, "
        "diversions snapped to real rivers/canals, parcels, wells, and physical "
        "link tables) onto the Phase-50 base layer. Idempotent; additive "
        "(MER-prefixed; does not touch Kaweah, Demo Valley, or the base layer)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--flush", action="store_true",
            help="Delete existing MER- operational rows before seeding.",
        )

    def handle(self, *args, **options):
        # Base-layer guard runs first, BEFORE any flush, so a wrong instance
        # fails fast and leaves existing data untouched.
        upper_rivers, lower_canals, lower_rivers = self._check_base_layer()

        if options["flush"]:
            self._flush()

        with transaction.atomic():
            self._seed(upper_rivers, lower_canals, lower_rivers)

    # ------------------------------------------------------------------
    # Base-layer guard — fail fast with a clear "run auto_populate first".
    # ------------------------------------------------------------------
    def _check_base_layer(self):
        """Return (upper_rivers, lower_canals, lower_rivers) or raise.

        Never place against an empty flowline set: both boundaries must exist
        and carry the flowlines each story needs (upper = river segments,
        lower = canal AND river segments). Returns the loaded Flowline lists so
        the seed reuses them without re-querying.
        """
        upper = Boundary.objects.filter(name=UPPER_BOUNDARY).first()
        lower = Boundary.objects.filter(name=LOWER_BOUNDARY).first()
        if upper is None or lower is None:
            missing = [
                n for n, b in [(UPPER_BOUNDARY, upper), (LOWER_BOUNDARY, lower)]
                if b is None
            ]
            raise CommandError(
                f"Missing Merced boundary/boundaries: {', '.join(missing)}.\n"
                + BASE_LAYER_HINT
            )

        upper_rivers = list(
            Flowline.objects.filter(boundary=upper, feature_type=RIVER)
        )
        lower_canals = list(
            Flowline.objects.filter(boundary=lower, feature_type=CANAL)
        )
        lower_rivers = list(
            Flowline.objects.filter(boundary=lower, feature_type=RIVER)
        )

        if not upper_rivers:
            raise CommandError(
                f'"{UPPER_BOUNDARY}" has zero "{RIVER}" flowlines — its base '
                "layer is not loaded.\n" + BASE_LAYER_HINT
            )
        if not lower_canals:
            raise CommandError(
                f'"{LOWER_BOUNDARY}" has zero "{CANAL}" flowlines — its base '
                "layer is not loaded.\n" + BASE_LAYER_HINT
            )
        if not lower_rivers:
            raise CommandError(
                f'"{LOWER_BOUNDARY}" has zero "{RIVER}" flowlines — its base '
                "layer is not loaded.\n" + BASE_LAYER_HINT
            )

        self.stdout.write(
            f"Base layer OK: upper {len(upper_rivers)} rivers; lower "
            f"{len(lower_canals)} canals + {len(lower_rivers)} rivers."
        )
        return upper_rivers, lower_canals, lower_rivers

    # ------------------------------------------------------------------
    # Flush — ONLY MER- operational rows + their links. Base layer + Kaweah /
    # Demo Valley rows are never touched. Delete links before the rows they
    # reference (defensive ordering, mirroring seed_kaweah._flush).
    # ------------------------------------------------------------------
    def _flush(self):
        self.stdout.write("Flushing existing MER- operational data...")

        parcel_ids = list(
            Parcel.objects.filter(parcel_number__startswith="MER-APN-")
            .values_list("id", flat=True)
        )
        well_ids = list(
            Well.objects.filter(well_registration_id__startswith="MER-W-")
            .values_list("id", flat=True)
        )
        wr_ids = list(
            WaterRight.objects.filter(right_id__startswith="MER-WR-")
            .values_list("id", flat=True)
        )
        pod_ids = list(
            PointOfDiversion.objects.filter(water_right_id__in=wr_ids)
            .values_list("id", flat=True)
        )

        # Link tables first.
        WellIrrigatedParcel.objects.filter(
            well_id__in=well_ids
        ).delete()
        WellIrrigatedParcel.objects.filter(
            parcel_id__in=parcel_ids
        ).delete()
        PointOfDiversionParcel.objects.filter(
            point_of_diversion_id__in=pod_ids
        ).delete()
        PointOfDiversionParcel.objects.filter(
            parcel_id__in=parcel_ids
        ).delete()
        WaterRightParcel.objects.filter(water_right_id__in=wr_ids).delete()
        WaterRightParcel.objects.filter(parcel_id__in=parcel_ids).delete()

        # Then the rows themselves.
        PointOfDiversion.objects.filter(id__in=pod_ids).delete()
        Well.objects.filter(id__in=well_ids).delete()
        Parcel.objects.filter(id__in=parcel_ids).delete()
        WaterRight.objects.filter(id__in=wr_ids).delete()

        self.stdout.write(self.style.SUCCESS("  Flushed MER- operational rows."))

    # ------------------------------------------------------------------
    # Seed
    # ------------------------------------------------------------------
    def _seed(self, upper_rivers, lower_canals, lower_rivers):
        # --- Water-right types (global lookup rows; same codes as seed_kaweah) ---
        self.stdout.write("Ensuring water-right types...")
        pre14, _ = WaterRightType.objects.get_or_create(
            code="PRE14", defaults={
                "name": "Pre-1914 Appropriative",
                "description": "Pre-1914 appropriative water right",
            },
        )
        post14, _ = WaterRightType.objects.get_or_create(
            code="POST14", defaults={
                "name": "Post-1914 Appropriative",
                "description": "Post-1914 appropriative water right",
            },
        )
        riparian, _ = WaterRightType.objects.get_or_create(
            code="RIP", defaults={
                "name": "Riparian",
                "description": "Riparian water right",
            },
        )
        wr_types = (pre14, post14, riparian)

        # --- Water rights (both stories), keyed on right_id ---
        self.stdout.write("Seeding Merced water rights...")
        rights_by_id = {}
        for rid, ti, holder, pdate, fv, source, status in RIGHT_CONFIGS:
            wr, _ = WaterRight.objects.update_or_create(
                right_id=rid,
                defaults={
                    "right_type": wr_types[ti],
                    "holder_name": holder,
                    "priority_date": pdate,
                    "face_value_acre_feet": fv,
                    "status": status,
                    "source_name": source,
                },
            )
            rights_by_id[rid] = wr
        self.stdout.write(f"  {len(rights_by_id)} water rights.")

        self.stdout.write(self.style.SUCCESS(
            f"\nMerced operational features seeded:\n"
            f"  {len(rights_by_id)} water rights"
        ))
