# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Shared Google Earth Engine mechanics for the OpenET GEE tier.

This module is the single home for the proven Earth Engine plumbing — headless
service-account auth and polygon ``reduceRegions`` over the OpenET Ensemble
monthly collection. Both the ``prove_gee_auth`` proof command (Phase 37-01) and
the production ``GEEOpenETAdapter`` (Phase 37-02) import from here so the two can
never drift on the collection id, band, scale, auth flow, or reduce mechanics.

``ee`` is imported lazily inside ``init_earth_engine`` so that non-GEE deploys
and the test suite can import this module (and the adapter) without
``earthengine-api`` being configured.

Functions raise ``RuntimeError`` (not ``CommandError``) because this is library
code, not a management command. Callers that are commands re-raise as
``CommandError`` at their own boundary to preserve "fail loud" go/no-go behavior.
"""

import json
import os
from collections import defaultdict
from datetime import date

from django.conf import settings

# Same data, different faucet: this is the exact OpenET Ensemble monthly
# collection the REST tier serves, pulled here via Earth Engine instead.
EE_COLLECTION = "projects/openet/assets/ensemble/conus/gridmet/monthly/v2_1"
EE_BAND = "et_ensemble_mad"
EE_SCALE = 30  # OpenET native resolution (m). Polygon mean, not centroid point.

# Ensemble spread, carried on the SAME images as the value above. OpenET's
# ensemble is the mean of the six member models left after a median-absolute-
# deviation outlier filter (Melton et al. 2022); these bands expose what that
# filter did instead of discarding it.
#
# Verified against the live asset (bandNames() on v2_1): the collection also
# carries et_ensemble_mad_index and et_ensemble_sam, which we do not use.
#
# NOTE ON THE COUNT BAND: reduceRegions(mean) averages per-pixel values across
# the parcel, so the count comes back FRACTIONAL (e.g. 5.4 = most pixels kept 5
# models, some kept 6). That is a genuine spatial mean, not a defect; the display
# rounds it, and the underlying value stays in the cache row.
EE_SPREAD_BANDS = [
    "et_ensemble_mad",       # the ensemble value itself
    "et_ensemble_mad_min",   # lowest surviving member
    "et_ensemble_mad_max",   # highest surviving member
    "et_ensemble_mad_count",  # how many of the six survived
]

# Earth Engine band name -> (OpenETCache.variable, payload key). Mirrors the REST
# tier exactly so accounting.confidence reads one shape regardless of faucet.
EE_BAND_TO_VARIABLE = {
    "et_ensemble_mad": ("ET", "et"),
    "et_ensemble_mad_min": ("et_mad_min", "et_mad_min"),
    "et_ensemble_mad_max": ("et_mad_max", "et_mad_max"),
    "et_ensemble_mad_count": ("model_count", "model_count"),
}

# GRIDMET precipitation. The OpenET ensemble above is BUILT on gridmet, but the
# ensemble collection carries only ET bands — raw precip lives in the source
# GRIDMET collection, and its `pr` band is DAILY mm. So the precip path sums each
# month's daily images into one monthly image before reducing (see
# reduce_precip_by_parcel); it is NOT a band swap on the ET path.
GRIDMET_COLLECTION = "IDAHO_EPSCOR/GRIDMET"
GRIDMET_BAND = "pr"  # daily precipitation amount, mm
GRIDMET_NATIVE_SCALE = 4638  # GRIDMET native grid (~4.6 km), for reference only.

# We reduce precip at the OpenET native scale (30 m), NOT GRIDMET's 4.6 km. At the
# coarse native scale, reduceRegions(mean) returns NULL for a parcel smaller than
# one pixel when no pixel centroid falls inside it — proven live when KAW-APN-003
# (~20 acres) dropped out of a real run entirely. Resampling the coarse precip
# value to 30 m (nearest-neighbor) does not change the number, but guarantees
# every parcel overlaps pixels so none is silently lost. Same scale the ET path
# already uses reliably on these exact parcels.
PRECIP_REDUCE_SCALE = EE_SCALE


def _first_of_month(d):
    return date(d.year, d.month, 1)


def _first_of_next_month(d):
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _parcels_bbox(parcels, margin=0.0):
    """Combined lon/lat envelope ``(minx, miny, maxx, maxy)`` of all parcels.

    Geometries are EPSG:4326 (the same CRS the reduce treats them as when it
    builds features from ``parcel.geometry.geojson``), so the envelope is in
    degrees. Returns ``None`` when there are no parcels. Pure: no Earth Engine,
    no DB beyond reading each parcel's already-loaded geometry — unit-testable.
    """
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for parcel in parcels:
        x0, y0, x1, y1 = parcel.geometry.extent  # (xmin, ymin, xmax, ymax)
        minx, miny = min(minx, x0), min(miny, y0)
        maxx, maxy = max(maxx, x1), max(maxy, y1)
    if minx == float("inf"):
        return None
    return (minx - margin, miny - margin, maxx + margin, maxy + margin)


def _bbox_to_ee(ee, bbox):
    """Turn a ``(minx, miny, maxx, maxy)`` tuple into an ``ee.Geometry`` rectangle.

    Built as a GeoJSON Polygon (not ``ee.Geometry.Rectangle``) so the same call
    works against the hand-built fake ``ee`` in the tests, which only implements
    the ``ee.Geometry(geojson)`` constructor.
    """
    minx, miny, maxx, maxy = bbox
    return ee.Geometry(
        {
            "type": "Polygon",
            "coordinates": [
                [[minx, miny], [maxx, miny], [maxx, maxy], [minx, maxy], [minx, miny]]
            ],
        }
    )


def init_earth_engine():
    """Headless service-account auth. Returns the initialized ``ee`` module.

    Raises a clear ``RuntimeError`` if ``earthengine-api`` is missing, the GEE_*
    settings are blank, the key file is absent, or auth fails. Auth working
    headlessly is the whole point of the tier, so failure is loud, not swallowed.
    """
    missing = [
        name
        for name in (
            "GEE_PROJECT",
            "GEE_SERVICE_ACCOUNT_EMAIL",
            "GEE_SERVICE_ACCOUNT_KEY_FILE",
        )
        if not getattr(settings, name, "")
    ]
    if missing:
        raise RuntimeError(
            "Earth Engine tier is not configured: missing "
            + ", ".join(missing)
            + ". See docs/earth-engine-tier-setup.md and set OPENET_MODE=gee "
            "plus the GEE_* vars in .env."
        )

    key_file = settings.GEE_SERVICE_ACCOUNT_KEY_FILE
    if not os.path.exists(key_file):
        raise RuntimeError(
            f"Service-account key not found at {key_file}. Place the JSON key "
            "there (the docker mount expects ./secrets/gee-key.json). "
            "See docs/earth-engine-tier-setup.md."
        )

    try:
        import ee
    except ImportError as exc:
        raise RuntimeError(
            "earthengine-api is not installed. Rebuild the web container "
            "(docker compose up -d --build web)."
        ) from exc

    try:
        creds = ee.ServiceAccountCredentials(
            settings.GEE_SERVICE_ACCOUNT_EMAIL,
            settings.GEE_SERVICE_ACCOUNT_KEY_FILE,
        )
        ee.Initialize(creds, project=settings.GEE_PROJECT)
    except Exception as exc:
        # Do NOT swallow: headless auth working is the whole point.
        raise RuntimeError(
            "Earth Engine headless auth FAILED (this is the go/no-go gate). "
            f"Exact error: {exc!r}"
        ) from exc

    return ee


def _reduce_images_by_parcel(ee, parcels, monthly_images, scale):
    """Run one ``reduceRegions(mean)`` per monthly image over all parcels at once.

    This is the shared mechanic behind both faucets. ``monthly_images`` is an
    ordered list of ``(month_key, ee.Image)`` where each image is already reduced
    to the single band we want sampled. Builds ONE ``FeatureCollection`` of all
    parcels (each tagged with its pk) and reduces every image against it — the
    batching that is the entire reason the GEE tier exists: a district with
    thousands of parcels is reduced in a handful of compute calls, not one query
    per parcel.

    Returns ``{parcel_id: {"YYYY-MM": value}}`` (value in the image's units).
    """
    features = []
    for parcel in parcels:
        geojson = json.loads(parcel.geometry.geojson)
        features.append(
            ee.Feature(ee.Geometry(geojson), {"parcel_id": parcel.pk})
        )
    fc = ee.FeatureCollection(features)

    result = defaultdict(dict)
    for month_key, img in monthly_images:
        # Single-band image + Reducer.mean() -> output property is "mean".
        reduced = img.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.mean(),
            scale=scale,
        ).getInfo()
        for feat in reduced.get("features", []):
            props = feat.get("properties", {})
            pid = props.get("parcel_id")
            mean = props.get("mean")
            if pid is not None and mean is not None:
                result[pid][month_key] = mean
    return result


def _reduce_multiband_by_parcel(ee, parcels, monthly_images, scale, bands):
    """Multi-band sibling of _reduce_images_by_parcel.

    A SINGLE-band reduceRegions writes its output to a property called "mean";
    a MULTI-band one writes one property per band name instead. That difference
    is the whole reason this is a separate function rather than a flag — reading
    "mean" off a multi-band result silently yields nothing.

    Returns ``{parcel_id: {"YYYY-MM": {band: value}}}``.
    """
    features = []
    for parcel in parcels:
        geojson = json.loads(parcel.geometry.geojson)
        features.append(ee.Feature(ee.Geometry(geojson), {"parcel_id": parcel.pk}))
    fc = ee.FeatureCollection(features)

    result = defaultdict(dict)
    for month_key, img in monthly_images:
        reduced = img.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.mean(),
            scale=scale,
        ).getInfo()
        for feat in reduced.get("features", []):
            props = feat.get("properties", {})
            pid = props.get("parcel_id")
            if pid is None:
                continue
            values = {b: props.get(b) for b in bands if props.get(b) is not None}
            if values:
                result[pid][month_key] = values
    return result


def reduce_et_with_spread_by_parcel(ee, parcels, start, end):
    """ET plus its ensemble spread, in ONE pass over the same images.

    The Earth Engine ensemble asset already carries the spread alongside the
    value — et_ensemble_mad_min / _max are the envelope of member models that
    survived OpenET's outlier filter, and _count is how many survived. Selecting
    them costs no additional queries, only additional bands on a reduction we
    were running anyway. (The REST tier has to pay one call per variable; here
    it is free, which is why spread collection defaults ON in GEE mode.)

    Returns ``{parcel_id: {"YYYY-MM": {band: value}}}``, values in mm except the
    count band.
    """
    parcels = list(parcels)
    filter_start = _first_of_month(start).isoformat()
    filter_end = _first_of_next_month(end).isoformat()
    ic = ee.ImageCollection(EE_COLLECTION).filterDate(filter_start, filter_end)
    bbox = _parcels_bbox(parcels)
    if bbox is not None:
        ic = ic.filterBounds(_bbox_to_ee(ee, bbox))
    ic = ic.select(EE_SPREAD_BANDS)

    image_list = ic.toList(ic.size())
    count = int(ic.size().getInfo())
    if count == 0:
        raise RuntimeError(
            f"Earth Engine returned 0 monthly images for {filter_start}.."
            f"{filter_end}. Check the date window against the collection's "
            "coverage."
        )

    monthly_images = []
    for i in range(count):
        img = ee.Image(image_list.get(i))
        month_key = ee.Date(img.get("system:time_start")).format("YYYY-MM").getInfo()
        monthly_images.append((month_key, img))

    return _reduce_multiband_by_parcel(
        ee, parcels, monthly_images, EE_SCALE, EE_SPREAD_BANDS
    )


def reduce_et_by_parcel(ee, parcels, start, end):
    """Batched polygon ET reduce over the OpenET Ensemble monthly images.

    The ensemble collection is already monthly, so each image maps to one month.
    Returns ``{parcel_id: {"YYYY-MM": et_mm}}``. ET is in millimeters.
    """
    parcels = list(parcels)
    filter_start = _first_of_month(start).isoformat()
    filter_end = _first_of_next_month(end).isoformat()  # exclusive
    ic = ee.ImageCollection(EE_COLLECTION).filterDate(filter_start, filter_end)
    # The OpenET CONUS ensemble is spatially TILED — ~32 images per month, only
    # the tile(s) overlapping a district carry its parcels; the rest reduce to
    # null and are discarded. filterBounds to the parcels' envelope keeps only
    # the overlapping tile(s), so a year is ~12 reduces instead of ~384. Measured
    # ~2.3x less EECU for byte-identical results (docs/earth-engine-tier-setup.md,
    # scripts/benchmarks/gee_eecu_bench.py).
    bbox = _parcels_bbox(parcels)
    if bbox is not None:
        ic = ic.filterBounds(_bbox_to_ee(ee, bbox))
    ic = ic.select(EE_BAND)

    image_list = ic.toList(ic.size())
    count = int(ic.size().getInfo())
    if count == 0:
        raise RuntimeError(
            f"Earth Engine returned 0 monthly images for {filter_start}.."
            f"{filter_end}. Check the date window against the collection's "
            "coverage."
        )

    monthly_images = []
    for i in range(count):
        img = ee.Image(image_list.get(i))
        month_key = ee.Date(img.get("system:time_start")).format(
            "YYYY-MM"
        ).getInfo()
        monthly_images.append((month_key, img))

    return _reduce_images_by_parcel(ee, parcels, monthly_images, EE_SCALE)


def reduce_precip_by_parcel(ee, parcels, start, end):
    """Batched polygon precipitation reduce over GRIDMET.

    GRIDMET ``pr`` is DAILY mm, so for each month in the window we filter that
    month's daily images and ``.sum()`` them into one monthly precip image, then
    reduce all months over all parcels via the shared mechanic. Months are walked
    in Python (deterministic ``YYYY-MM`` keys, no reliance on EE date formatting).

    Returns ``{parcel_id: {"YYYY-MM": precip_mm}}``. Precip is in millimeters.
    """
    parcels = list(parcels)
    # Unlike the tiled OpenET ensemble, GRIDMET is ONE CONUS image per day, so
    # filterBounds trims no images here today — it is kept for symmetry with the
    # ET path and stays correct if the precip source is ever swapped for a tiled
    # one. Computed once; applied to each month's daily collection below.
    bbox = _parcels_bbox(parcels)
    monthly_images = []
    cursor = _first_of_month(start)
    last = _first_of_month(end)
    while cursor <= last:
        nxt = _first_of_next_month(cursor)
        month_key = cursor.strftime("%Y-%m")
        daily = ee.ImageCollection(GRIDMET_COLLECTION).filterDate(
            cursor.isoformat(), nxt.isoformat()  # [start, next) exclusive
        )
        if bbox is not None:
            daily = daily.filterBounds(_bbox_to_ee(ee, bbox))
        daily = daily.select(GRIDMET_BAND)
        count = int(daily.size().getInfo())
        if count == 0:
            raise RuntimeError(
                f"GRIDMET returned 0 daily images for {month_key} "
                f"({cursor.isoformat()}..{nxt.isoformat()}). Check the date "
                "window against GRIDMET coverage."
            )
        # Monthly total precip = sum of the month's daily pr images.
        monthly_images.append((month_key, daily.sum()))
        cursor = nxt

    return _reduce_images_by_parcel(ee, parcels, monthly_images, PRECIP_REDUCE_SCALE)


def build_et_data(et_by_month):
    """Convert a ``{YYYY-MM: et_mm}`` dict into the EXACT OpenETCache.et_data shape.

    The REST path writes ``[{"date": "YYYY-MM", "et": <float mm>, "unit": "mm"}]``
    and ``sync_openet_to_ledger`` reads exactly that. The GEE path must emit the
    same shape so the cache→ledger contract is satisfied unchanged.
    """
    return [
        {"date": month, "et": mm, "unit": "mm"}
        for month, mm in sorted(et_by_month.items())
    ]


def build_precip_data(precip_by_month):
    """Convert a ``{YYYY-MM: precip_mm}`` dict into the precip cache shape.

    Mirrors ``build_et_data`` but keys the value as ``precip`` (named for the
    variable) so a future generic reader can dispatch on ``OpenETCache.variable``.
    Written to ``OpenETCache.et_data`` with ``variable="precip"``.
    """
    return [
        {"date": month, "precip": mm, "unit": "mm"}
        for month, mm in sorted(precip_by_month.items())
    ]
