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

# Flowline feature_type values as the USGS 3DHP loader (auto_populate) actually
# writes them for the Merced base layer. A natural watercourse — the Merced River
# main stem we snap river diversions onto — is a "Channel Line"; the MID network
# is "Canal". This MATCHES the map renderer's split (templates/geography/map.html:
# a canal is any feature_type containing "Canal", everything else is a river), so
# a POD's type here renders consistently with how the base layer is drawn.
RIVER = "Channel Line"
CANAL = "Canal"

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
    # source_name matches a REAL named canal/river in the 3DHP base layer (Atwater
    # Canal, Le Grand Canal, Diversion Canal, El Nido Canal all exist in the
    # Merced Subbasin flowlines), so the displayed source is truthful to geometry.
    ("MER-WR-004", 1, "Merced Irrigation District", "1930-04-10",
     Decimal("120000"), "Merced River", "active"),
    ("MER-WR-005", 1, "Le Grand-Athlone Water District", "1948-09-01",
     Decimal("18000"), "Le Grand Canal", "active"),
    ("MER-WR-006", 1, "Stevinson Water District", "1955-03-20",
     Decimal("22000"), "Diversion Canal", "active"),
    ("MER-WR-007", 0, "Merced Subbasin Riparian Holders", "1908-07-15",
     Decimal("6000"), "Merced River", "curtailed"),
    ("MER-WR-008", 2, "San Joaquin Bottomlands Ranch", None,
     Decimal("4000"), "Merced River", "active"),
    ("MER-WR-009", 1, "Plainsburg Irrigation District", "1962-05-05",
     Decimal("9000"), "El Nido Canal", "active"),
]

# ---------------------------------------------------------------------------
# Points of diversion. THE HEART of the phase. A diversion that sits ON a line
# but the WRONG line — a Merced Irrigation District take stranded on Fahrens
# Creek through downtown Merced — is the same credibility failure as one
# floating in a field. So each POD is ANCHORED to a real NAMED watercourse: we
# look up the actual flowline named (e.g.) "Merced River" or "Le Grand Canal" in
# the right boundary, then place the POD at a fraction `frac` ALONG that named
# segment (place_near_flowline with zero offset = a point exactly on the line).
# stream_name is the real name of that line — truthful by construction.
#
# `frac` (0..1) walks the named segments west→east so several PODs on the same
# river land at distinct, plausible reaches rather than stacking on one segment.
#
# Each entry: pod_name, right_id, story, line_name, feature_type, frac, max_rate_cfs.
# ---------------------------------------------------------------------------
POD_CONFIGS = [
    # --- Upper story: Merced River main-stem snowmelt diversions (simple) ---
    ("MER-POD-001 Merced River Upper Diversion", "MER-WR-001", "upper",
     "Merced River", RIVER, 0.55, Decimal("1200.0")),
    ("MER-POD-002 Merced Falls Diversion", "MER-WR-002", "upper",
     "Merced River", RIVER, 0.12, Decimal("40.0")),
    ("MER-POD-003 Foothill Riparian Take", "MER-WR-003", "upper",
     "Merced River", RIVER, 0.35, Decimal("12.0")),

    # --- Lower story: MID canal headgates (complex) + main-stem river diversions ---
    ("MER-POD-004 MID Atwater Canal Headgate", "MER-WR-004", "lower",
     "Atwater Canal", CANAL, 0.50, Decimal("900.0")),
    ("MER-POD-005 Le Grand Canal Headgate", "MER-WR-005", "lower",
     "Le Grand Canal", CANAL, 0.50, Decimal("220.0")),
    ("MER-POD-006 Stevinson Diversion Canal Headgate", "MER-WR-006", "lower",
     "Diversion Canal", CANAL, 0.50, Decimal("260.0")),
    ("MER-POD-007 Plainsburg El Nido Canal Headgate", "MER-WR-009", "lower",
     "El Nido Canal", CANAL, 0.50, Decimal("130.0")),
    ("MER-POD-008 Crocker-Huffman River Diversion", "MER-WR-004", "lower",
     "Merced River", RIVER, 0.88, Decimal("700.0")),
    ("MER-POD-009 Bottomlands Riparian Take", "MER-WR-008", "lower",
     "Merced River", RIVER, 0.15, Decimal("45.0")),
]

# Per-POD parcel cluster. Each diversion serves a small cluster of fields placed
# NEAR its snapped flowline via place_near_flowline (both banks, staggered along
# the reach). Keep counts legible; ~24 parcels total. Acres are realistic
# Central-Valley field sizes (~40-160 ac). offset_m keeps fields a plausible
# distance off the channel (not on it). Each entry:
#   pod_name, n_parcels, acres, offset_m, story
PARCEL_CLUSTER_CONFIGS = [
    # Upper: surface-water fields hugging the Merced River diversions.
    ("MER-POD-001 Merced River Upper Diversion", 3, 120.0, 800.0, "upper"),
    ("MER-POD-002 Merced Falls Diversion", 2, 80.0, 600.0, "upper"),
    ("MER-POD-003 Foothill Riparian Take", 2, 60.0, 500.0, "upper"),
    # Lower: MID-canal-served + river-served fields on the valley floor.
    ("MER-POD-004 MID Main Canal Headgate", 4, 160.0, 900.0, "lower"),
    ("MER-POD-005 Le Grand Canal Headgate", 3, 130.0, 800.0, "lower"),
    ("MER-POD-006 Stevinson Canal Headgate", 3, 140.0, 800.0, "lower"),
    ("MER-POD-007 Plainsburg Canal Headgate", 2, 100.0, 700.0, "lower"),
    ("MER-POD-008 Crocker-Huffman River Diversion", 3, 150.0, 900.0, "lower"),
    ("MER-POD-009 Bottomlands Riparian Take", 2, 90.0, 700.0, "lower"),
]

# Groundwater wells — LOWER SUBBASIN ONLY (the overdraft story). Each entry sets
# the share of lower parcels that host a well and the well's physical attributes.
# Wells sit at a lower parcel's centroid + a small deterministic offset, inside
# the Merced Subbasin. Each entry: name_suffix, well_type_name, depth_ft,
# capacity_gpm. The count (9) is matched to lower parcels in _seed.
WELL_SPECS = [
    ("Le Grand Ag Well", "Agricultural", Decimal("420"), Decimal("1600")),
    ("Plainsburg Ag Well", "Agricultural", Decimal("380"), Decimal("1450")),
    ("Stevinson Ag Well", "Agricultural", Decimal("510"), Decimal("2100")),
    ("El Nido Ag Well", "Agricultural", Decimal("460"), Decimal("1800")),
    ("Athlone Ag Well", "Agricultural", Decimal("400"), Decimal("1500")),
    ("Cressey Ag Well", "Agricultural", Decimal("350"), Decimal("1350")),
    ("Snelling Road Ag Well", "Agricultural", Decimal("440"), Decimal("1700")),
    ("Sandy Mush Ag Well", "Agricultural", Decimal("530"), Decimal("2300")),
    ("Bottomlands Ag Well", "Agricultural", Decimal("300"), Decimal("1200")),
]

# Small deterministic well offset off the parcel centroid, in degrees. A fixed
# table indexed by well number — NOT random — so a re-run reproduces it exactly.
# ~0.0015 deg ≈ 130 m at this latitude: the well sits at the edge of its field.
_WELL_OFFSETS = [
    (0.0015, 0.0010), (-0.0012, 0.0014), (0.0011, -0.0013),
    (-0.0015, -0.0009), (0.0013, 0.0012), (-0.0010, 0.0015),
    (0.0014, -0.0011), (-0.0013, 0.0010), (0.0009, -0.0014),
]

# Realistic demo OPERATOR / owner names (NOT a crop — the 47-02 lesson: the
# "Owner" column must read like a farm operator, not "Almonds"). Cycled by index.
MER_PARCEL_OWNERS = [
    "Merced Valley Farms LLC",
    "Snelling Ranch Co.",
    "Le Grand Orchards Inc.",
    "Stevinson Land & Cattle",
    "El Nido Growers",
    "Athlone Farming Partners",
    "Cressey Ag Holdings",
    "Sandy Mush Family Farm",
    "Plainsburg Field Co.",
    "Bear Creek Bottomlands LLC",
    "Foothill River Ranch",
    "Yosemite Gateway Farms",
]

MER_WELL_OWNERS = [
    "Le Grand Orchards Inc.",
    "Plainsburg Field Co.",
    "Stevinson Land & Cattle",
    "El Nido Growers",
    "Athlone Farming Partners",
    "Cressey Ag Holdings",
    "Snelling Ranch Co.",
    "Sandy Mush Family Farm",
    "Bear Creek Bottomlands LLC",
]


def _dist_sq(a, b):
    """Squared planar (degree) distance — fine for RANKING nearby parcels."""
    dx = a.x - b.x
    dy = a.y - b.y
    return dx * dx + dy * dy


def _nearest_parcels(point, parcels, n):
    """The ``n`` parcels whose centroid is closest to ``point`` (deterministic).

    Degree-space ranking is adequate here: we only need a stable nearest-first
    order over a small local cluster, not a true-metre distance. No randomness,
    so a re-run links the same well to the same parcel(s).
    """
    ranked = sorted(parcels, key=lambda p: _dist_sq(point, p.geometry.centroid))
    return ranked[: min(n, len(ranked))]


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
        upper, lower = self._check_base_layer()

        if options["flush"]:
            self._flush()

        with transaction.atomic():
            self._seed(upper, lower)

    # ------------------------------------------------------------------
    # Base-layer guard — fail fast with a clear "run auto_populate first".
    # ------------------------------------------------------------------
    def _check_base_layer(self):
        """Return (upper_boundary, lower_boundary) or raise CommandError.

        Never place against an empty flowline set: both boundaries must exist
        and carry the flowlines each story needs (upper = river segments,
        lower = canal AND river segments). We check existence by COUNT rather
        than materializing the rows — the upper watershed holds ~40k "Channel
        Line" segments and the seed pulls only the index-nearest handful per
        diversion, so loading them all here would be pure waste.
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

        n_upper_rivers = Flowline.objects.filter(
            boundary=upper, feature_type=RIVER).count()
        n_lower_canals = Flowline.objects.filter(
            boundary=lower, feature_type=CANAL).count()
        n_lower_rivers = Flowline.objects.filter(
            boundary=lower, feature_type=RIVER).count()

        if not n_upper_rivers:
            raise CommandError(
                f'"{UPPER_BOUNDARY}" has zero "{RIVER}" flowlines — its base '
                "layer is not loaded.\n" + BASE_LAYER_HINT
            )
        if not n_lower_canals:
            raise CommandError(
                f'"{LOWER_BOUNDARY}" has zero "{CANAL}" flowlines — its base '
                "layer is not loaded.\n" + BASE_LAYER_HINT
            )
        if not n_lower_rivers:
            raise CommandError(
                f'"{LOWER_BOUNDARY}" has zero "{RIVER}" flowlines — its base '
                "layer is not loaded.\n" + BASE_LAYER_HINT
            )

        self.stdout.write(
            f"Base layer OK: upper {n_upper_rivers} river segments; lower "
            f"{n_lower_canals} canal + {n_lower_rivers} river segments."
        )
        return upper, lower

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
    def _named_line(self, boundary, name, ftype, frac):
        """A real flowline named ``name`` (e.g. "Merced River") at fraction ``frac``.

        The base layer splits each watercourse into many short 3DHP segments, so
        "Merced River" is ~dozens of rows. We order those segments deterministically
        west→east (centroid x, then y, then pk) and pick the one at ``frac`` of the
        way along — so two PODs on the Merced River at frac 0.12 and 0.88 land on
        genuinely different reaches, not the same segment. Returns ``None`` if no
        segment carries that name (caught by the caller as a placement error).
        """
        segs = list(
            Flowline.objects.filter(
                boundary=boundary, feature_type=ftype, name__iexact=name)
        )
        if not segs:
            return None
        segs.sort(key=lambda f: (
            f.geometry.centroid.x, f.geometry.centroid.y, f.pk))
        idx = min(int(frac * len(segs)), len(segs) - 1)
        return segs[idx]

    def _seed(self, upper, lower):
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

        # --- Points of diversion, ANCHORED to named watercourses ---
        # Each POD is placed on the real flowline named in its config (Merced
        # River / a specific MID canal) within the right boundary, so a diversion
        # never lands on the wrong creek and its stream_name is truthful.
        self.stdout.write("Placing points of diversion on named rivers/canals...")
        boundary_for = {"upper": upper, "lower": lower}
        pods = []
        pod_river_lines = {}  # pod.pk -> the named Flowline it sits on (reused in Task 3)
        for name, rid, story, line_name, ftype, frac, max_cfs in POD_CONFIGS:
            line = self._named_line(boundary_for[story], line_name, ftype, frac)
            if line is None:
                # The named watercourse is missing from the base layer — fail
                # loudly rather than silently snap the POD onto some other creek.
                raise CommandError(
                    f'No "{line_name}" ({ftype}) flowline in the {story} boundary '
                    f"for {name}; base layer incomplete or renamed."
                )
            # Zero perpendicular offset = a point exactly ON the named segment.
            location = place_near_flowline(line, 0.0, along=frac)
            if location is None:
                location = snap_to_flowline(line.geometry.centroid, line)
            stream_name = self._stream_name(line, ftype)
            pod, _ = PointOfDiversion.objects.update_or_create(
                name=name,
                defaults={
                    "water_right": rights_by_id[rid],
                    "location": location,
                    "stream_name": stream_name,
                    "max_rate_cfs": max_cfs,
                    "status": "active",
                },
            )
            pods.append(pod)
            pod_river_lines[pod.pk] = line
        pods_by_name = {p.name: p for p in pods}
        self.stdout.write(f"  {len(pods)} PODs snapped onto real river/canal segments.")

        # --- Parcels: clusters placed NEAR each POD's snapped flowline ---
        # place_near_flowline fans fields onto both banks (side=±1), staggered
        # along the reach, so each field sits a plausible distance off the
        # channel that serves it — never floating, never on the line. Footprint
        # = area_accurate_box (true acreage, latitude-corrected), not a fixed box.
        self.stdout.write("Placing parcels near their source reaches...")
        parcel_seq = 0
        # pod.pk -> list of its parcels (drives POD-parcel + right-parcel links)
        pod_to_parcels = {}
        lower_parcels = []  # parcels in the lower subbasin (well candidates)
        for cfg in PARCEL_CLUSTER_CONFIGS:
            pod_name, n_parcels, acres, offset_m, story = cfg
            pod = pods_by_name[pod_name]
            line = pod_river_lines[pod.pk]
            cluster = []
            for j in range(n_parcels):
                # Stagger along the reach (0.25..0.75) and alternate banks so
                # the cluster fans deterministically onto both sides.
                along = 0.25 + (0.5 * j / max(1, n_parcels - 1)) if n_parcels > 1 else 0.5
                side = 1 if j % 2 == 0 else -1
                center = place_near_flowline(line, offset_m, along=along, side=side)
                if center is None:
                    continue
                parcel_seq += 1
                owner = MER_PARCEL_OWNERS[(parcel_seq - 1) % len(MER_PARCEL_OWNERS)]
                geom = area_accurate_box(center.x, center.y, acres)
                parcel, _ = Parcel.objects.update_or_create(
                    parcel_number=f"MER-APN-{parcel_seq:03d}",
                    defaults={
                        "owner_name": owner,
                        "geometry": geom,
                        "status": "active",
                    },
                )
                cluster.append(parcel)
                if story == "lower":
                    lower_parcels.append(parcel)
            pod_to_parcels[pod.pk] = cluster
        all_parcels = [p for c in pod_to_parcels.values() for p in c]
        self.stdout.write(
            f"  {len(all_parcels)} parcels "
            f"({len(all_parcels) - len(lower_parcels)} upper, "
            f"{len(lower_parcels)} lower)."
        )

        # --- Wells: groundwater wells in the LOWER subbasin only ---
        # The overdraft story lives on the valley floor, so wells sit at lower
        # parcels' centroids + a small deterministic offset, and we verify each
        # falls inside the Merced Subbasin polygon before saving.
        self.stdout.write("Placing groundwater wells in the lower subbasin...")
        ag_well_type, _ = WellType.objects.get_or_create(
            name="Agricultural",
            defaults={"description": "Agricultural irrigation well"},
        )
        n_wells = min(len(WELL_SPECS), len(lower_parcels))
        wells = []
        well_to_parcels = {}
        for i in range(n_wells):
            host = lower_parcels[i]
            wname, _wt, depth, cap = WELL_SPECS[i]
            centroid = host.geometry.centroid
            dx, dy = _WELL_OFFSETS[i % len(_WELL_OFFSETS)]
            loc = Point(centroid.x + dx, centroid.y + dy, srid=4326)
            # Keep the well inside the subbasin; if the offset pushed it out,
            # fall back to the parcel centroid (always inside its own field).
            if not lower.geometry.contains(loc):
                loc = Point(centroid.x, centroid.y, srid=4326)
            well, _ = Well.objects.update_or_create(
                well_registration_id=f"MER-W-{i + 1:03d}",
                defaults={
                    "name": wname,
                    "well_type": ag_well_type,
                    "location": loc,
                    "depth_ft": depth,
                    "capacity_gpm": cap,
                    "status": "active",
                    "owner_name": MER_WELL_OWNERS[i % len(MER_WELL_OWNERS)],
                },
            )
            wells.append(well)
        self.stdout.write(f"  {len(wells)} wells (lower subbasin).")

        # --- Physical links ---
        # PointOfDiversionParcel: each POD serves its own cluster, fraction
        # normalized to sum 1.0 across the cluster.
        self.stdout.write("Linking PODs, rights, and wells to parcels...")
        podp_count = 0
        for pod in pods:
            cluster = pod_to_parcels.get(pod.pk, [])
            if not cluster:
                continue
            fraction = Decimal(str(round(1.0 / len(cluster), 4)))
            for parcel in cluster:
                PointOfDiversionParcel.objects.update_or_create(
                    point_of_diversion=pod, parcel=parcel,
                    defaults={"fraction": fraction},
                )
                podp_count += 1

        # WaterRightParcel: a right serves the union of its PODs' parcels.
        wrp_count = 0
        right_to_parcels = {}
        for pod in pods:
            wr_id = pod.water_right_id
            right_to_parcels.setdefault(wr_id, [])
            for parcel in pod_to_parcels.get(pod.pk, []):
                if parcel not in right_to_parcels[wr_id]:
                    right_to_parcels[wr_id].append(parcel)
        for wr in rights_by_id.values():
            for parcel in right_to_parcels.get(wr.pk, []):
                WaterRightParcel.objects.update_or_create(
                    water_right=wr, parcel=parcel,
                )
                wrp_count += 1

        # WellIrrigatedParcel: each lower well irrigates its nearest parcel(s),
        # fraction normalized. Deterministic nearest-by-centroid (no random).
        wip_count = 0
        for i, well in enumerate(wells):
            n_links = 1 + (i % 2)  # 1 or 2 parcels, deterministic
            linked = _nearest_parcels(well.location, lower_parcels, n_links)
            if not linked:
                continue
            fraction = Decimal(str(round(1.0 / len(linked), 4)))
            for parcel in linked:
                WellIrrigatedParcel.objects.update_or_create(
                    well=well, parcel=parcel,
                    defaults={"fraction": fraction},
                )
                wip_count += 1
            well_to_parcels[well.pk] = linked

        self.stdout.write(self.style.SUCCESS(
            f"\nMerced operational features seeded:\n"
            f"  {len(rights_by_id)} water rights\n"
            f"  {len(pods)} points of diversion "
            f"({podp_count} POD-parcel links)\n"
            f"  {len(all_parcels)} parcels "
            f"({len(all_parcels) - len(lower_parcels)} upper, "
            f"{len(lower_parcels)} lower)\n"
            f"  {len(wells)} wells ({wip_count} well-parcel links)\n"
            f"  {wrp_count} water right-parcel links"
        ))

    @staticmethod
    def _stream_name(line, ftype):
        """Truthful source name drawn from the real flowline, not hand-typed.

        Uses the flowline's GNIS name when present; otherwise a clear fallback
        built from the feature type + the segment's source id (e.g.
        "Canal segment 12345"), so the displayed source is always tied to the
        geometry the POD actually sits on.
        """
        if line.name:
            return line.name
        sid = line.source_id or str(line.pk)
        return f"{ftype.capitalize()} segment {sid}"
