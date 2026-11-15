# SPDX-License-Identifier: AGPL-3.0-or-later
"""A stand-in for DWR's LightBox parcel layer, for the parcel download tests.

It answers the three kinds of query the parcel step can send, the way the live
layer answered them on 2026-11-15 (153.3 setup facts F3, F4, P24):

- ``returnIdsOnly``: every OBJECTID inside the boundary, or ``null`` when there
  are none (a boundary outside California).
- ``objectIds``: the parcels for those IDs, all of them, unless a batch is set
  to come back short.
- ``resultOffset``: the paging the layer gets wrong: 16, 8, 7 and 5 parcels,
  each page overlapping the last, then empty pages still saying more remain.

No network: tests patch ``geography.services.arcgis.requests.post`` with
``FakeLightBox.post``.
"""
from unittest.mock import MagicMock

from django.contrib.gis.geos import MultiPolygon, Polygon

# A boundary that holds every fake parcel (each parcel is a 0.0009 degree
# square on a 100-wide grid starting at -120.5, 37.3).
BOUNDARY_BBOX = (-120.6, 37.2, -120.3, 37.5)


def boundary_geometry():
    return MultiPolygon(Polygon.from_bbox(BOUNDARY_BBOX))


def apn_of(oid):
    return f"{oid:012d}"


def ring_of(oid):
    x = -120.5 + (oid % 100) * 0.001
    y = 37.3 + (oid // 100) * 0.001
    return [[x, y], [x + 0.0009, y], [x + 0.0009, y + 0.0009], [x, y + 0.0009], [x, y]]


class FakeLightBox:
    def __init__(self, count=2500, ids=None, apns=None, no_outline=(), short=None,
                 ids_error=None):
        #: OBJECTIDs inside the boundary; None answers ``"objectIds": null``.
        self.ids = list(range(1, count + 1)) if ids is None else ids
        #: OBJECTID -> PARCEL_APN, overriding apn_of (None or "" for a blank).
        self.apns = dict(apns or {})
        self.no_outline = set(no_outline)
        #: batch number (1-based) -> how many times it comes back one short;
        #: "always" for every time.
        self.short = dict(short or {})
        self.ids_error = ids_error
        self.ids_calls = 0
        self.batch_calls = 0
        self.offset_calls = 0
        self._batch_seen = {}

    def apn(self, oid):
        return self.apns.get(oid, apn_of(oid))

    def feature(self, oid):
        return {
            "attributes": {
                "OBJECTID": oid,
                "PARCEL_APN": self.apn(oid),
                "SITE_ADDR": f"{oid} Canal Rd",
                "SITE_CITY": "Merced",
                "SITE_STATE": "CA",
                "SITE_ZIP": "95340",
            },
            "geometry": None if oid in self.no_outline else {"rings": [ring_of(oid)]},
        }

    def post(self, url, data=None, timeout=None):
        data = data or {}
        if str(data.get("returnIdsOnly", "")).lower() == "true":
            self.ids_calls += 1
            if self.ids_error:
                return _response({"error": self.ids_error})
            ids = None if self.ids is None else list(self.ids)
            return _response({"objectIdFieldName": "OBJECTID", "objectIds": ids})
        if "objectIds" in data:
            self.batch_calls += 1
            asked = [int(x) for x in str(data["objectIds"]).split(",") if x]
            batch = 1 + (self.ids.index(asked[0]) // 1000 if self.ids else 0)
            seen = self._batch_seen.get(batch, 0)
            self._batch_seen[batch] = seen + 1
            short = self.short.get(batch, 0)
            if short == "always" or seen < short:
                asked = asked[:-1]
            return _response({"features": [self.feature(oid) for oid in asked]})
        if "resultOffset" in data:
            self.offset_calls += 1
            sizes = [16, 8, 7, 5]
            page = min(int(data["resultOffset"]) // 16, len(sizes))
            if page >= len(sizes):
                return _response({"features": [], "exceededTransferLimit": True})
            top = 4775252
            return _response({
                "features": [self.feature(oid) for oid in range(top - sizes[page] + 1, top + 1)],
                "exceededTransferLimit": True,
            })
        return _response({"features": []})


def _response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = payload
    return resp
