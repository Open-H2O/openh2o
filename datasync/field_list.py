# SPDX-License-Identifier: AGPL-3.0-or-later
"""OpenET's field list: the site's three kinds of request, and what a use area takes from the answers.

OpenET keeps its own fields, an outline and a number for each piece of land. The site asks in
three kinds of request:

* :func:`lookup` sends a rectangle and gets the numbers of the fields in it;
* :func:`outlines` sends field numbers and gets each field's outline;
* :func:`figures` sends field numbers and a span of months and gets each field's monthly
  crop ET and rain.

A use area takes from each field the acres of the field that lie inside it (its shares,
:func:`compute_shares`, measured in California Albers after any crossed edge is repaired). A
month's crop ET or rain over a use area is each field's depth over that field's acres inside
the use area, added up, over the use area's own acres (:func:`field_share_mm`). Land in no
OpenET field counts no crop use and no rain.

Every request is written down before it is sent (``OpenETRequest``), under the same lock the
older route reserves its slots under, so the monthly allowance is never overspent by two runs
at once. A refused request keeps its row, counts nothing, and raises :class:`OpenETRefused`
with OpenET's own words.
"""

import csv
import gzip
import io
import json
import logging
import math
import os
import zipfile
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext

import requests
from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry
from django.db import connection, transaction

logger = logging.getLogger(__name__)

BASE_URL = "https://openet-api.org"
LOOKUP_PATH = "/geodatabase/metadata/ids"
OUTLINES_PATH = "/geodatabase/metadata/boundaries"
FIGURES_PATH = "/geodatabase/timeseries"
STATUS_PATH = "/account/status"

ACRE_M2 = Decimal("4046.8564224")
#: Millimetre-acres in one acre-foot (1 mm over 1 acre is 1/304.8 acre-foot).
MM_ACRES_PER_AF = Decimal("304.8")
CENT = Decimal("0.01")

#: Rectangles lying within this many metres of each other become one lookup.
MERGE_GAP_M = 250
#: The largest rectangle a lookup may cover when the account does not say.
DEFAULT_MAX_AREA_ACRES = 50000
#: Read and send timeouts for one request, in seconds.
TIMEOUT = 120

#: The two collections a figures request returns, and the depth each one is.
_COLLECTIONS = {"ensemble_et": "et", "gridmet_pr": "pr"}


class OpenETRefused(Exception):
    """OpenET refused a request, or could not be reached. The message is OpenET's own ``detail``."""


class AllowanceUsed(Exception):
    """This month's OpenET allowance is used; nothing was sent."""


# -- The request ----------------------------------------------------------------------------


def _headers():
    return {"Authorization": os.environ.get("OPENET_API_KEY", ""), "Content-Type": "application/json"}


def _decode(content):
    """The bytes OpenET sent, read by their first bytes and never by the content type."""
    if content[:2] == b"\x1f\x8b":
        return gzip.decompress(content)
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            return archive.read(archive.namelist()[0])
    return content


def _detail(resp):
    """OpenET's own sentence for a refusal, never the body as it came."""
    try:
        detail = resp.json().get("detail")
    except (ValueError, AttributeError):
        detail = None
    text = detail if isinstance(detail, str) else (json.dumps(detail) if detail else "")
    text = text.strip()
    return text[:300] if text else f"OpenET answered HTTP {resp.status_code}."


def _post(kind, path, body, ids_count, note=""):
    """One paid request: counted first under the lock, sent, then OpenET's own count read.

    Returns the decoded bytes of the answer.
    """
    from datasync.models import OpenETCache, OpenETRequest

    with transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", [OpenETCache._BUDGET_LOCK_KEY])
        can_query, _used, _limit = OpenETCache.check_budget()
        if not can_query:
            raise AllowanceUsed("This month's OpenET allowance is used.")
        row = OpenETRequest.objects.create(kind=kind, ids_count=ids_count, answered=True, note=note)

    try:
        resp = requests.request("POST", BASE_URL + path, json=body, headers=_headers(), timeout=TIMEOUT)
    except requests.RequestException as exc:
        # exc's type only: its text can carry the address and headers.
        row.answered = False
        row.save(update_fields=["answered"])
        _read_provider_count(row)
        raise OpenETRefused(f"OpenET could not be reached ({type(exc).__name__}).") from None

    row.http_status = resp.status_code
    if resp.status_code >= 400:
        row.answered = False
        row.save(update_fields=["answered", "http_status"])
        detail = _detail(resp)
        _read_provider_count(row)
        raise OpenETRefused(detail)
    row.save(update_fields=["http_status"])
    _read_provider_count(row)
    return _decode(resp.content)


def _read_provider_count(row):
    """Store OpenET's own count after the request (the status read is free); None when it falls back."""
    from datasync.adapters.openet import OpenETAdapter

    try:
        status = OpenETAdapter().account_status(use_cache=False)
        used = status.get("used") if status.get("source") == "provider" else None
    except Exception as exc:  # the count is a note; it never fails a request already answered
        logger.warning("openet: account status unavailable (%s)", type(exc).__name__)
        used = None
    row.provider_used = used
    row.save(update_fields=["provider_used"])


def account_max_area_acres():
    """The largest area OpenET takes in one lookup, from the account's status; 50,000 when unreadable."""
    try:
        resp = requests.request("GET", BASE_URL + STATUS_PATH, headers=_headers(), timeout=30)
        value = resp.json().get("Max Area Acres")
        value = int(value)
        return value if value > 0 else DEFAULT_MAX_AREA_ACRES
    except Exception:
        return DEFAULT_MAX_AREA_ACRES


def _batches(ids):
    size = max(1, int(getattr(settings, "OPENET_FIELDS_PER_REQUEST", 100)))
    ids = [int(i) for i in ids]
    return [ids[n:n + size] for n in range(0, len(ids), size)]


# -- The three kinds of request ----------------------------------------------------------------


def round_rectangle(rectangle):
    return tuple(round(float(v), 6) for v in rectangle)


def rectangle_note(rectangle, whole_area=False):
    """The request's note: the rounded rectangle, and for a lookup over the site's boundary
    (``--whole-area``) a mark saying so, so a use area's own lookup is told apart from it."""
    rounded = list(round_rectangle(rectangle))
    if whole_area:
        return json.dumps({"rectangle": rounded, "whole_area": True}, separators=(",", ":"))
    return json.dumps(rounded, separators=(",", ":"))


def lookup(rectangle, whole_area=False):
    """The OpenET field numbers inside ``rectangle`` ``(west, south, east, north)``, in OpenET's order."""
    west, south, east, north = round_rectangle(rectangle)
    body = {"geometry": [west, south, west, north, east, north, east, south]}
    answer = _post("lookup", LOOKUP_PATH, body, 0, note=rectangle_note(rectangle, whole_area))
    return [int(i) for i in json.loads(answer)]


def store_listed(numbers, today, whole_area):
    """Store the fields a lookup listed that the site does not hold yet, with no outline.

    A field a whole-area lookup listed is marked ``whole_area_only``; a use area's lookup that
    lists it clears the mark, so its outline is asked by every run, not only by a whole-area run.
    """
    from datasync.models import OpenETField

    numbers = [int(n) for n in numbers]
    if not whole_area:
        OpenETField.objects.filter(field_id__in=numbers, whole_area_only=True).update(whole_area_only=False)
    held = set(OpenETField.objects.filter(field_id__in=numbers).values_list("field_id", flat=True))
    OpenETField.objects.bulk_create([
        OpenETField(field_id=n, geometry=None, received_on=today, whole_area_only=whole_area)
        for n in dict.fromkeys(numbers) if n not in held
    ])


def answered_rectangles(whole_area=None):
    """The rounded rectangles OpenET has answered a lookup for: the use areas' own lookups with
    ``whole_area=False``, the lookups over the site's boundary with ``True``, both with ``None``."""
    from datasync.models import OpenETRequest

    found = set()
    rows = OpenETRequest.objects.filter(kind="lookup", answered=True, http_status=200)
    for note in rows.values_list("note", flat=True):
        try:
            values = json.loads(note)
        except ValueError:
            continue
        boundary = isinstance(values, dict) and values.get("whole_area") is True
        if boundary:
            values = values.get("rectangle")
        if whole_area is not None and boundary != whole_area:
            continue
        if isinstance(values, list) and len(values) == 4:
            found.add(tuple(round(float(v), 6) for v in values))
    return found


def outlines(ids):
    """``[(field number, outline)]`` for ``ids``; each outline a GEOS Polygon or MultiPolygon in 4326."""
    found = []
    for batch in _batches(ids):
        answer = _post("outlines", OUTLINES_PATH, {"field_ids": batch}, len(batch))
        for feature in json.loads(answer).get("features", []):
            geometry = feature.get("geometry")
            number = (feature.get("properties") or {}).get("field_id")
            if not geometry or number is None:
                continue
            found.append((int(number), GEOSGeometry(json.dumps(geometry), srid=4326)))
    return found


def _depth(text):
    try:
        return Decimal(str(text).strip()) if str(text).strip() else None
    except InvalidOperation:
        return None


def figures(ids, start, end):
    """``[(field number, first of the month, crop ET mm, rain mm)]``, sorted, values read as text."""
    values = {}
    for batch in _batches(ids):
        body = {
            "date_range": [start.isoformat(), end.isoformat()],
            "interval": "monthly",
            "field_ids": batch,
            "models": ["ensemble"],
            "variables": ["et", "pr"],
            "file_format": "csv",
        }
        answer = _post("figures", FIGURES_PATH, body, len(batch))
        for line in csv.DictReader(io.StringIO(answer.decode("utf-8-sig"))):
            variable = _COLLECTIONS.get((line.get("collection") or "").strip())
            if variable is None:
                continue
            try:
                number = int(line["field_id"])
                year, month = int(line["time"][:4]), int(line["time"][5:7])
            except (KeyError, TypeError, ValueError):
                continue
            slot = values.setdefault((number, _first(year, month)), {"et": None, "pr": None})
            slot[variable] = _depth(line.get("value_mm"))
    return [(number, month, slot["et"], slot["pr"]) for (number, month), slot in sorted(values.items())]


def _first(year, month):
    import datetime as dt

    return dt.date(year, month, 1)


# -- The rectangles to look up ----------------------------------------------------------------


def _metres(latitude):
    return 111320 * math.cos(math.radians(latitude)), 110574


def _gap_m(a, b):
    mx, my = _metres((a[1] + a[3] + b[1] + b[3]) / 4)
    dx = max(0, max(a[0], b[0]) - min(a[2], b[2])) * mx
    dy = max(0, max(a[1], b[1]) - min(a[3], b[3])) * my
    return math.hypot(dx, dy)


def _acres(box):
    mx, my = _metres((box[1] + box[3]) / 2)
    return (box[2] - box[0]) * mx * (box[3] - box[1]) * my / float(ACRE_M2)


def lookup_areas(parcels, max_acres=None):
    """The rectangles ``(west, south, east, north)`` to look up for ``parcels``, west to east.

    Each use area's bounding box; boxes within 250 m of each other merge until nothing
    merges; a rectangle larger than ``max_acres`` (the account's "Max Area Acres", read from
    its status when not given) is cut into equal strips under the limit.
    """
    boxes = [list(p.geometry.extent) for p in parcels if p.geometry is not None]
    return _cut(_merge(boxes), max_acres)


def boundary_areas(max_acres=None):
    """The rectangles to look up for the site's whole boundary (``--whole-area``), west to east.

    Each boundary part's bounding box, merged and cut as ``lookup_areas`` does for use areas.
    """
    from geography.models import Boundary

    boxes = []
    for geometry in Boundary.objects.filter(geometry__isnull=False).values_list("geometry", flat=True):
        boxes.extend(list(part.extent) for part in geometry)
    return _cut(_merge(boxes), max_acres)


def _merge(boxes):
    """Boxes within 250 m of each other merged until nothing merges."""
    merged = True
    while merged:
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if _gap_m(boxes[i], boxes[j]) <= MERGE_GAP_M:
                    a, b = boxes[i], boxes.pop(j)
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    merged = True
                    break
            if merged:
                break
    return boxes


def _cut(boxes, max_acres):
    """Each box cut into equal strips under ``max_acres`` (the account's limit when not given)."""
    if not boxes:
        return []
    if max_acres is None:
        max_acres = account_max_area_acres()
    tiles = []
    for west, south, east, north in boxes:
        count = max(1, math.ceil(_acres((west, south, east, north)) / max_acres))
        # Cut along the longer side, so each strip stays as square as it can.
        mx, my = _metres((south + north) / 2)
        wide = (east - west) * mx >= (north - south) * my
        for n in range(count):
            if wide:
                step = (east - west) / count
                tiles.append((west + n * step, south, east if n == count - 1 else west + (n + 1) * step, north))
            else:
                step = (north - south) / count
                tiles.append((west, south + n * step, east, north if n == count - 1 else south + (n + 1) * step))
    return sorted({round_rectangle(t) for t in tiles})


def rectangle_covers(rectangles, parcel, tolerance=1.5e-6):
    """Whether one of ``rectangles`` holds the use area's bounding box (to the rounding of 6 decimals)."""
    if parcel.geometry is None:
        return False
    w, s, e, n = parcel.geometry.extent
    return any(
        r[0] <= w + tolerance and r[1] <= s + tolerance and r[2] >= e - tolerance and r[3] >= n - tolerance
        for r in rectangles
    )


# -- What a use area takes from the fields ---------------------------------------------------------


def _albers(geometry):
    """A repaired copy of an outline in California Albers (metres)."""
    copy = geometry.clone()
    if copy.srid is None:
        copy.srid = 4326
    copy.transform(3310)
    return copy.make_valid()


def _acres_text(square_metres):
    return (Decimal(str(square_metres)) / ACRE_M2).quantize(CENT, rounding=ROUND_HALF_UP)


def outline_acres(geometry):
    """An outline's area in acres, measured in EPSG 3310 after repair, to 0.01."""
    return _acres_text(_albers(geometry).area)


def compute_shares(parcel):
    """Replace the use area's share rows: the acres of each outlined field that lie inside it."""
    from datasync.models import OpenETField, OpenETFieldShare

    if parcel.geometry is None:
        OpenETFieldShare.objects.filter(parcel=parcel, field__geometry__isnull=False).delete()
        return []
    mine = _albers(parcel.geometry)
    fields = OpenETField.objects.filter(geometry__isnull=False, geometry__intersects=parcel.geometry)
    made = []
    for field in fields:
        acres = _acres_text(mine.intersection(_albers(field.geometry)).area)
        if acres > 0:
            made.append((field, acres))
    with transaction.atomic():
        OpenETFieldShare.objects.filter(parcel=parcel, field__geometry__isnull=False).delete()
        for field, acres in made:
            OpenETFieldShare.objects.create(parcel=parcel, field=field, overlap_acres=acres)
        # A field inside a use area is that use area's, whichever lookup listed it first.
        OpenETField.objects.filter(pk__in=[f.pk for f, _ in made], whole_area_only=True).update(
            whole_area_only=False)
    return made


def has_shares(parcel):
    from datasync.models import OpenETFieldShare

    return OpenETFieldShare.objects.filter(parcel=parcel).exists()


def field_share_mm(parcel, period, variable):
    """The use area's depth for ``period`` ("YYYY-MM"): ``"et"`` or ``"pr"``, from its fields.

    Each field's depth over its acres inside the use area, added up, over the use area's own
    acres. None when it has no share or no area, or when any field has no figure for the month
    (never a partial figure). ``fetched_on`` is the newest day the fields' figures were received.
    """
    from datasync.crop_et import Fetched
    from datasync.models import OpenETFieldMonth, OpenETFieldShare

    if variable not in ("et", "pr"):
        raise ValueError(variable)
    acres = parcel.area_acres
    if not acres:
        return None
    shares = list(OpenETFieldShare.objects.filter(parcel=parcel))
    if not shares:
        return None
    month = _first(int(period[:4]), int(period[5:7]))
    rows = {
        row.field_id: row
        for row in OpenETFieldMonth.objects.filter(field_id__in=[s.field_id for s in shares], month=month)
    }
    with localcontext() as context:
        context.prec = 60
        total, days = Decimal("0"), []
        for share in shares:
            row = rows.get(share.field_id)
            depth = None if row is None else getattr(row, f"{variable}_mm")
            if depth is None:
                return None
            total += Decimal(depth) * Decimal(share.overlap_acres)
            days.append(row.received_on)
        return Fetched(mm=total / Decimal(acres), fetched_on=max(days))


def field_parts(parcel, period):
    """Each OpenET field's part of the use area's month, largest share first, or None.

    ``[{"field_id", "acres", "crop_et_af", "rainfall_af"}]``: the field's acres inside the use
    area, and its crop ET and rain over those acres in acre-feet (depth x acres / 304.8), at
    full precision, from the month's record (``datasync.crop_et.recorded_fields``), never from
    the field months as they now stand. ``rainfall_af`` is None on every row when any field's
    rain is missing (the month then counts no rain). None when the record holds no OpenET
    field, or any field has no crop ET in it.
    """
    from datasync.crop_et import recorded_fields

    fields = recorded_fields(parcel, period)
    if not fields or any(et_mm is None for _n, _a, et_mm, _p in fields):
        return None
    with_rain = all(pr_mm is not None for _n, _a, _e, pr_mm in fields)
    parts = []
    with localcontext() as context:
        context.prec = 60
        for number, acres, et_mm, pr_mm in sorted(fields, key=lambda f: (-f[1], f[0])):
            parts.append({
                "field_id": number,
                "acres": acres,
                "crop_et_af": et_mm * acres / MM_ACRES_PER_AF,
                "rainfall_af": pr_mm * acres / MM_ACRES_PER_AF if with_rain else None,
            })
    return parts


def outside_acres(parcel, parts):
    """The use area's acres in no OpenET field: its outline's acres less the fields' (never below 0).

    Measured from the outline in California Albers, the way the overlaps are; never from the
    acres on file, which a person may have typed below the overlaps. None with no outline.
    """
    if parcel.geometry is None:
        return None
    left = outline_acres(parcel.geometry) - sum((p["acres"] for p in parts), Decimal("0"))
    return max(left, Decimal("0"))
