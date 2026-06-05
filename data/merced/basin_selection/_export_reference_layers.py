# SPDX-License-Identifier: AGPL-3.0-or-later
"""Export the two basin-picker reference layers from the live openh2o DB.

Run on Butler inside the web container via Django's shell, e.g.:

    docker compose exec -T web python manage.py shell \
        -c "exec(open('/tmp/_export_reference_layers.py').read())"

Writes two EPSG:4326 GeoJSON files to /tmp (scp'd back into
data/merced/basin_selection/ and committed as picker reference context):

  merced_river_flowlines.geojson  — NHD river hydrography (Channel Line +
      Waterbody Connector) for the Merced Subbasin, with name/feature_type so
      Brent can read the river-feed options and tag feeds_via to a real name.
  merced_existing_basins.geojson  — the v1.9 RechargeSite footprints, shown
      only for reference (they are wiped + re-picked).
"""
import json

from geography.models import Flowline
from recharge.models import RechargeSite
from surface.models import PointOfDiversion

RIVER_TYPES = ["Channel Line", "Waterbody Connector"]


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


# --- river flowlines (rivers only; canals come from merced_canals.geojson) ---
rivers = []
for f in Flowline.objects.filter(feature_type__in=RIVER_TYPES):
    if not f.geometry:
        continue
    rivers.append(
        {
            "type": "Feature",
            "properties": {
                "name": f.name or "",
                "feature_type": f.feature_type,
                "source_id": f.source_id or "",
            },
            "geometry": json.loads(f.geometry.geojson),
        }
    )
with open("/tmp/merced_river_flowlines.geojson", "w") as fh:
    json.dump(_fc(rivers), fh)
named = sum(1 for r in rivers if r["properties"]["name"])
print(f"river flowlines: {len(rivers)} ({named} named)")

# --- existing v1.9 basins (reference only; geometry = footprint polygon) ---
basins = []
for s in RechargeSite.objects.all():
    geom = s.geometry or s.location
    if not geom:
        continue
    basins.append(
        {
            "type": "Feature",
            "properties": {
                "name": s.name,
                "site_type": s.site_type,
                "operator": s.operator or "",
                "capacity_acre_feet": (
                    float(s.capacity_acre_feet)
                    if s.capacity_acre_feet is not None
                    else None
                ),
                "status": s.status,
            },
            "geometry": json.loads(geom.geojson),
        }
    )
with open("/tmp/merced_existing_basins.geojson", "w") as fh:
    json.dump(_fc(basins), fh)
print(f"existing basins: {len(basins)}")

# --- existing diversion headgates (reference: where surface water is pulled) ---
pods = []
for p in PointOfDiversion.objects.all():
    if not p.location:
        continue
    pods.append(
        {
            "type": "Feature",
            "properties": {
                "name": p.name,
                "stream_name": p.stream_name or "",
            },
            "geometry": json.loads(p.location.geojson),
        }
    )
with open("/tmp/merced_diversions.geojson", "w") as fh:
    json.dump(_fc(pods), fh)
print(f"diversion headgates: {len(pods)}")
