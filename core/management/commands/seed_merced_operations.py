# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed the Merced demonstration's OPERATIONAL features onto the real base layer.

WHY this command exists. Phase 50 built a credible Merced canvas (real
boundaries, river + canal segments, recharge basins, stations). This command
populates the LOWER subbasin (the valley floor, where the agencies who will use
this platform actually do their accounting) with the features a domain expert
inspects: Merced River diversions, MID-canal headgates, groundwater wells, and
farm parcels — the complex conjunctive-use story of surface water + groundwater.
The upper Merced River watershed is intentionally out of scope (see RIGHT_CONFIGS).

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
import math
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

# Boundary seeded by seed_merced_base — the spatial canvas this command populates.
# The demo is the lower subbasin only, so the guard looks up just this boundary.
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
    "--steps flowlines,stations"
)

# ---------------------------------------------------------------------------
# Water rights — Lower Merced Subbasin ONLY. The upper Merced River watershed was
# removed by design: in this 3DHP base layer the only free-flowing reaches of the
# upper river sit high in the Sierra (Yosemite country, the foothill stretch being
# Lake McClure reservoir), so a district-scale diversion placed there reads as
# implausible — and the upper watershed adds little for the agencies who will use
# this platform, whose accounting lives on the valley floor. The demo is the
# valley story: MID canal-served districts + a couple of Merced River diversions.
#
# right_id is the natural key for update_or_create. source_name matches a REAL
# named canal/river in the base layer (Atwater Canal, Le Grand Canal, Diversion
# Canal, El Nido Canal, Merced River all exist in the Merced Subbasin flowlines),
# so the displayed source is truthful to geometry. (ti = water-right-type index:
# 0=PRE14, 1=POST14, 2=RIP.) Each entry:
#   right_id, type_idx, holder_name, priority_date(str|None), face_af, source_name, status
# ---------------------------------------------------------------------------
RIGHT_CONFIGS = [
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
# `story` is "lower" for every diversion now (the upper watershed was removed).
#
# Headgates legitimately sit ON the canal — and a canal often runs through the
# town it is named for, so a headgate near a town is CORRECT. The fields it serves
# do NOT belong next to the headgate; they live on the open cropland of the
# service area (see PARCEL_CLUSTER_CONFIGS).
#
# Each entry: pod_name, right_id, story, line_name, feature_type, frac, max_rate_cfs.
# ---------------------------------------------------------------------------
POD_CONFIGS = [
    # MID canal headgates (complex) + two Merced River main-stem diversions.
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

# Per-POD parcel cluster, placed on SATELLITE-VERIFIED OPEN CROPLAND.
#
# THE FIX (why these are explicit anchors, not an offset off the headgate). The
# first pass placed each field a fixed distance off its diversion point. But the
# diversion sits on a canal named for the town it runs through (the Atwater Canal
# runs through Atwater), so "a few hundred metres off the headgate" dropped farm
# parcels onto the city. There is no land-use data in the geometry to stop that.
# So each cluster is anchored to a hand-picked (lon, lat) that was confirmed on
# the aerial basemap to be open cropland clear of any town — the same satellite
# check used to site the Phase-50 recharge basins. The field is SERVED BY its
# diversion (a canal-routed link in _seed), but LOCATED on real farmland in the
# service area, which is how irrigation actually works.
#
# Each entry: pod_name, anchor_lon, anchor_lat, n_parcels, acres.
PARCEL_CLUSTER_CONFIGS = [
    # Atwater Canal (MID): orchards/fields by the approved Cressey-Winton basin.
    ("MER-POD-004 MID Atwater Canal Headgate", -120.665, 37.345, 4, 150.0),
    # Le Grand Canal: open field blocks east of Planada.
    ("MER-POD-005 Le Grand Canal Headgate", -120.270, 37.270, 3, 130.0),
    # Diversion Canal (Stevinson): Central-Valley crop mosaic near El Nido.
    ("MER-POD-006 Stevinson Diversion Canal Headgate", -120.520, 37.100, 3, 140.0),
    # El Nido Canal (Plainsburg): irrigated fields SW of Plainsburg.
    ("MER-POD-007 Plainsburg El Nido Canal Headgate", -120.475, 37.205, 3, 110.0),
    # Crocker-Huffman river diversion: valley orchards in the MID service area
    # (the intake itself is at the foothill edge; the served land is downvalley).
    ("MER-POD-008 Crocker-Huffman River Diversion", -120.490, 37.420, 3, 150.0),
    # Bottomlands riparian: river-bottom fields west of Livingston.
    ("MER-POD-009 Bottomlands Riparian Take", -120.825, 37.375, 2, 90.0),
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


def _grid_centers(anchor_lon, anchor_lat, n, acres):
    """``n`` field-centre (lon, lat) pairs in a compact grid around an anchor.

    The cluster is a little block of adjacent fields. Spacing is the field's own
    side length (from its acreage) plus a small gap, converted to degrees with the
    cos(lat) longitude correction, so the fields sit next to each other without
    heavy overlap and the whole cluster stays within ~1-2 km of the verified-ag
    anchor. Deterministic (row-major, centred on the anchor) — a re-run reproduces
    identical geometry.
    """
    side_m = math.sqrt(float(acres) * 4046.86)      # square field, side in metres
    step_m = side_m * 1.12                            # adjacent + a thin margin
    dlat = step_m / 111_320.0
    dlon = step_m / (111_320.0 * math.cos(math.radians(anchor_lat)))
    cols = max(1, int(math.ceil(math.sqrt(n))))
    centers = []
    for k in range(n):
        row, col = divmod(k, cols)
        rows = math.ceil(n / cols)
        cx = anchor_lon + (col - (cols - 1) / 2.0) * dlon
        cy = anchor_lat + (row - (rows - 1) / 2.0) * dlat
        centers.append((cx, cy))
    return centers


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
        lower = self._check_base_layer()

        if options["flush"]:
            self._flush()

        with transaction.atomic():
            self._seed(lower)

    # ------------------------------------------------------------------
    # Base-layer guard — fail fast with a clear "run auto_populate first".
    # ------------------------------------------------------------------
    def _check_base_layer(self):
        """Return the Merced Subbasin boundary, or raise CommandError.

        The demo is the lower subbasin only (the upper watershed was removed), so
        we require just the Merced Subbasin boundary carrying both canal AND river
        flowlines. Existence is checked by COUNT rather than materializing rows.
        """
        lower = Boundary.objects.filter(name=LOWER_BOUNDARY).first()
        if lower is None:
            raise CommandError(
                f"Missing Merced boundary: {LOWER_BOUNDARY}.\n" + BASE_LAYER_HINT
            )

        n_lower_canals = Flowline.objects.filter(
            boundary=lower, feature_type=CANAL).count()
        n_lower_rivers = Flowline.objects.filter(
            boundary=lower, feature_type=RIVER).count()

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
            f"Base layer OK: Merced Subbasin {n_lower_canals} canal + "
            f"{n_lower_rivers} river segments."
        )
        return lower

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
    def _named_line(self, boundary, name, prefer_type, frac):
        """A real flowline named ``name`` (e.g. "Merced River") at fraction ``frac``.

        The base layer splits each watercourse into many short 3DHP segments, so
        "Merced River" is dozens of rows — and crucially a single watercourse
        carries MIXED feature_types: the Merced main stem is mostly "Waterbody
        Connector" (wide/ponded reaches) with only its free-flowing stretches as
        "Channel Line", and a named canal has both "Canal" and "Waterbody
        Connector" segments. So we anchor on the NAME and treat ``prefer_type`` as
        a soft preference: use the segments of that type if any exist (a river
        diversion prefers a flowing "Channel Line" reach; a canal headgate prefers
        a "Canal" segment so it renders as a canal), otherwise fall back to every
        named segment. Segments are ordered deterministically west→east so two
        PODs on the same river at frac 0.15 and 0.88 land on distinct reaches.
        Returns ``None`` if no segment carries that name.
        """
        segs = list(Flowline.objects.filter(boundary=boundary, name__iexact=name))
        if not segs:
            return None
        if prefer_type:
            typed = [s for s in segs if prefer_type in (s.feature_type or "")]
            if typed:
                segs = typed
        segs.sort(key=lambda f: (
            f.geometry.centroid.x, f.geometry.centroid.y, f.pk))
        idx = min(int(frac * len(segs)), len(segs) - 1)
        return segs[idx]

    def _seed(self, lower):
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
        pods = []
        pod_lines = {}  # pod.pk -> the named Flowline it sits on (for stream_name)
        for name, rid, story, line_name, ftype, frac, max_cfs in POD_CONFIGS:
            # Prefer a free-flowing "Channel Line" reach for a river diversion and
            # a "Canal" segment for a canal headgate, but fall back to any named
            # segment (the lower Merced main stem is all "Waterbody Connector").
            prefer = CANAL if ftype == CANAL else RIVER
            line = self._named_line(lower, line_name, prefer, frac)
            if line is None:
                # The named watercourse is missing from the base layer — fail
                # loudly rather than silently snap the POD onto some other creek.
                raise CommandError(
                    f'No "{line_name}" ({ftype}) flowline in the Merced Subbasin '
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
            pod_lines[pod.pk] = line
        pods_by_name = {p.name: p for p in pods}
        self.stdout.write(f"  {len(pods)} PODs placed on real river/canal segments.")

        # --- Parcels: compact field blocks on satellite-verified cropland ---
        # Each cluster is laid out as a small adjacent grid around its verified
        # ag anchor (see PARCEL_CLUSTER_CONFIGS). The fields are SERVED BY their
        # diversion (the link below) but LOCATED on real farmland in the service
        # area — decoupled from the headgate so a canal that runs through a town
        # can no longer drag farm parcels onto the city. Footprint =
        # area_accurate_box (true acreage, latitude-corrected).
        self.stdout.write("Placing parcels on verified cropland...")
        parcel_seq = 0
        pod_to_parcels = {}  # pod.pk -> its parcels (drives POD/right-parcel links)
        lower_parcels = []   # every MER parcel (all in the lower subbasin now)
        for pod_name, anchor_lon, anchor_lat, n_parcels, acres in PARCEL_CLUSTER_CONFIGS:
            pod = pods_by_name[pod_name]
            cluster = []
            for cx, cy in _grid_centers(anchor_lon, anchor_lat, n_parcels, acres):
                parcel_seq += 1
                owner = MER_PARCEL_OWNERS[(parcel_seq - 1) % len(MER_PARCEL_OWNERS)]
                geom = area_accurate_box(cx, cy, acres)
                parcel, _ = Parcel.objects.update_or_create(
                    parcel_number=f"MER-APN-{parcel_seq:03d}",
                    defaults={
                        "owner_name": owner,
                        "geometry": geom,
                        "status": "active",
                    },
                )
                cluster.append(parcel)
                lower_parcels.append(parcel)
            pod_to_parcels[pod.pk] = cluster
        all_parcels = list(lower_parcels)
        self.stdout.write(f"  {len(all_parcels)} parcels on verified cropland.")

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
            f"\nMerced operational features seeded (lower subbasin):\n"
            f"  {len(rights_by_id)} water rights\n"
            f"  {len(pods)} points of diversion "
            f"({podp_count} POD-parcel links)\n"
            f"  {len(all_parcels)} parcels on verified cropland\n"
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
