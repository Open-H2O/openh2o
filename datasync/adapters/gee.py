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


def _first_of_month(d):
    return date(d.year, d.month, 1)


def _first_of_next_month(d):
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


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


def reduce_et_by_parcel(ee, parcels, start, end):
    """Batched polygon ``reduceRegions`` over the OpenET Ensemble monthly images.

    Builds ONE ``FeatureCollection`` of all parcels (each tagged with its pk),
    then runs ONE ``reduceRegions(mean)`` per monthly image in the window. This
    batching is the entire reason the GEE tier exists: a district with thousands
    of parcels gets all of them reduced in a handful of compute calls instead of
    one REST query per parcel.

    Returns ``{parcel_id: {"YYYY-MM": et_mm}}``. ET is in millimeters.
    """
    features = []
    for parcel in parcels:
        geojson = json.loads(parcel.geometry.geojson)
        features.append(
            ee.Feature(ee.Geometry(geojson), {"parcel_id": parcel.pk})
        )
    fc = ee.FeatureCollection(features)

    filter_start = _first_of_month(start).isoformat()
    filter_end = _first_of_next_month(end).isoformat()  # exclusive
    ic = (
        ee.ImageCollection(EE_COLLECTION)
        .filterDate(filter_start, filter_end)
        .select(EE_BAND)
    )

    image_list = ic.toList(ic.size())
    count = int(ic.size().getInfo())
    if count == 0:
        raise RuntimeError(
            f"Earth Engine returned 0 monthly images for {filter_start}.."
            f"{filter_end}. Check the date window against the collection's "
            "coverage."
        )

    result = defaultdict(dict)
    for i in range(count):
        img = ee.Image(image_list.get(i))
        month_key = ee.Date(img.get("system:time_start")).format(
            "YYYY-MM"
        ).getInfo()
        reduced = img.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.mean(),
            scale=EE_SCALE,
        ).getInfo()
        for feat in reduced.get("features", []):
            props = feat.get("properties", {})
            pid = props.get("parcel_id")
            mean = props.get("mean")
            if pid is not None and mean is not None:
                result[pid][month_key] = mean
    return result


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
