# SPDX-License-Identifier: AGPL-3.0-or-later
"""Persistent identifiers: one address per feature record (146-06, ISS-019).

Every feature record a deployment holds gets an address of the form
``https://<host>/id/<kind>/<pk>/``. It is DERIVED here on every read and never
stored, so it cannot drift from the record it names. ``<host>`` is
``SiteConfig.identifier_host`` when an operator has set one (which may carry a
path, e.g. ``geoconnex.us/<namespace>``, so the Geoconnex address itself can be
the identifier), and otherwise the site's own address as the request reached it.

The address answers two readers (``core.views.persistent_identifier``): a
browser is sent (303) to the record's own page, and a machine asking for
``application/ld+json`` gets the document :func:`jsonld_for` builds.

**The JSON-LD shape follows the Geoconnex contributor documentation as read on
2026-09-23** (quoted in the phase's ``146-06-EVIDENCE-T1.md``): a feature is a
``schema:Place`` whose WKT geometry sits under ``gsp:hasGeometry`` (schema.org's
``geo`` is carried too, for schema.org readers, but Geoconnex does not index
it); every term is prefixed and the prefixes are declared; places a record sits
inside are bare ``{"@id": ...}`` references, because a nested node typed
``schema:Place`` would itself be held to the Geoconnex shape and need a
geometry. The water right is a record, not a feature, so it is a
``schema:Thing`` and Geoconnex would not take it; it has an address because the
state's own crosswalk keys on the application number.

**Nothing a record does not hold is invented.** A blank crosswalk field is left
out, not emitted empty; a record with no geometry has no geometry in its
document; no ``hyf:HydroLocationType`` is guessed per kind.

**Composition rule.** ``core`` is required and most of these models belong to
optional modules, so nothing here imports a model at module scope. Models are
resolved through the app registry (``apps.get_model``) and only after
``is_enabled`` has said the module is running: a truly-removable module's app
(``surface``, ``recharge``, ``drinking``) is not even installed when it is off.
"""

from django.apps import apps
from django.http import Http404

from core.modules import is_enabled

#: slug -> (app label, model name, module name). The slug is the address's
#: second segment and the document's ``schema:additionalType``.
KINDS = {
    "boundary": ("geography", "Boundary", "geography"),
    "zone": ("geography", "Zone", "geography"),
    "use-area": ("parcels", "Parcel", "parcels"),
    "well": ("wells", "Well", "wells"),
    "point-of-diversion": ("surface", "PointOfDiversion", "surface"),
    "recharge-site": ("recharge", "RechargeSite", "recharge"),
    "station": ("datasync", "MonitoredStation", "datasync"),
    "water-system": ("drinking", "WaterSystem", "drinking"),
    "facility": ("drinking", "SystemFacility", "drinking"),
    "sampling-point": ("drinking", "SamplingPoint", "drinking"),
    "water-right": ("surface", "WaterRight", "surface"),
}

_KIND_BY_LABEL = {
    f"{app_label}.{model_name}": slug
    for slug, (app_label, model_name, _module) in KINDS.items()
}

#: The crosswalk identifiers each kind carries, as model field names. Each
#: becomes one ``schema:PropertyValue`` whose ``propertyID`` is the field name,
#: so a reader can tell a State Well Number from a WCR number without guessing.
IDENTIFIER_FIELDS = {
    "boundary": ("basin_code", "huc"),
    "zone": ("basin_code",),
    "use-area": ("parcel_number",),
    "well": (
        "well_registration_id",
        "state_well_number",
        "wcr_number",
        "usgs_site_id",
        "wqx_monitoring_location_id",
    ),
    # The point's name is the state's APPL_POD-style key (A001885_01) when
    # it came from the state's file, which is why it is an identifier here.
    "point-of-diversion": ("name",),
    "recharge-site": (),
    "station": ("external_station_id", "usgs_site_id", "wqx_monitoring_location_id"),
    "water-system": ("pwsid",),
    "facility": ("facility_id", "epa_facility_id"),
    "sampling-point": ("ps_code",),
    "water-right": ("right_id", "calwatrs_pin", "permit_number", "license_number"),
}

_CONTEXT = {
    "schema": "https://schema.org/",
    "gsp": "http://www.opengis.net/ont/geosparql#",
    "sf": "http://www.opengis.net/ont/sf#",
}


# -- The address ---------------------------------------------------------------


def normalize_host(value):
    """``https://water.example.org/`` -> ``water.example.org``.

    Applied when the setting is saved AND when it is read, so a value typed
    into the Django admin with its scheme still builds one ``https://``.
    """
    value = (value or "").strip()
    for scheme in ("https://", "http://"):
        if value.lower().startswith(scheme):
            value = value[len(scheme):]
    return value.strip("/")


def _configured_host():
    SiteConfig = apps.get_model("core", "SiteConfig")
    config = SiteConfig.objects.only("identifier_host").first()
    return normalize_host(config.identifier_host) if config else ""


def identifier_base(request=None, host=None):
    """The part of every identifier before ``/id/``, without a trailing slash.

    ``host`` lets a caller that has already read the setting (a template with
    ``site_config`` in its context) skip the query. With no host set and no
    request, the base is empty and the identifier is a site-relative path.
    """
    if host is None:
        host = _configured_host()
    else:
        host = normalize_host(host)
    if host:
        return f"https://{host}"
    if request is not None:
        return request.build_absolute_uri("/").rstrip("/")
    return ""


def kind_for(obj):
    """The kind slug for a model instance, or None for a model with no address."""
    return _KIND_BY_LABEL.get(obj._meta.label)


def identifier_for(obj, request=None, base=None):
    """``https://<host>/id/<kind>/<pk>/`` for a record."""
    if base is None:
        base = identifier_base(request)
    return f"{base}/id/{kind_for(obj)}/{obj.pk}/"


def resolve(kind, pk):
    """The record an address names, or ``Http404`` saying why there is none.

    Three different misses, each with its own sentence: a kind this platform
    does not have, a kind whose module this deployment does not run, and a row
    that does not exist. The module check comes BEFORE the model lookup: a
    removable module's app is not installed when it is off, so
    ``apps.get_model`` would raise rather than miss.
    """
    spec = KINDS.get(kind)
    if spec is None:
        raise Http404(f"There is no record kind called {kind}.")
    app_label, model_name, module = spec
    if not is_enabled(module):
        raise Http404(f"This deployment does not run the {module} module.")
    model = apps.get_model(app_label, model_name)
    try:
        return model.objects.get(pk=pk)
    except model.DoesNotExist:
        raise Http404(f"There is no {kind.replace('-', ' ')} with id {pk}.")


# -- The document --------------------------------------------------------------


def _record_name(kind, obj):
    if kind == "use-area":
        return obj.parcel_number
    if kind == "station":
        return obj.station_name
    if kind == "facility":
        return obj.name or obj.local_name or obj.facility_id
    if kind == "sampling-point":
        return obj.name or obj.ps_code
    if kind == "water-right":
        return obj.right_id
    if kind == "well":
        return str(obj)
    return obj.name


def _geometry(kind, obj):
    """(geometry for the WKT, a point for GeoCoordinates or None)."""
    if kind in ("boundary", "zone", "use-area"):
        return obj.geometry, None
    if kind in ("well", "point-of-diversion", "station", "facility"):
        return obj.location, obj.location
    if kind == "recharge-site":
        return (obj.geometry or obj.location), obj.location
    if kind == "sampling-point":
        # The facility owns the coordinate and a sampling point inherits it
        # (drinking/models.py, SystemFacility.location's own comment).
        location = obj.facility.location
        return location, location
    return None, None


def _geo_nodes(geometry, point):
    nodes = {
        "gsp:hasGeometry": {
            "@type": f"sf:{geometry.geom_type}",
            "gsp:asWKT": {"@type": "gsp:wktLiteral", "@value": geometry.wkt},
        }
    }
    if point is not None:
        nodes["schema:geo"] = {
            "@type": "schema:GeoCoordinates",
            "schema:latitude": point.y,
            "schema:longitude": point.x,
        }
    else:
        # schema.org's GeoShape.box: "lat lon lat lon", lower corner first.
        xmin, ymin, xmax, ymax = geometry.extent
        nodes["schema:geo"] = {
            "@type": "schema:GeoShape",
            "schema:box": f"{ymin} {xmin} {ymax} {xmax}",
        }
    return nodes


def _ref(kind, obj, base):
    return {"@id": f"{base}/id/{kind}/{obj.pk}/"}


def _contained_in(kind, obj, geometry, base):
    """Bare references to the places this record sits inside, boundaries first.

    Boundaries by containment of the record's point (an area's point on its
    surface); zones, systems and facilities only where the record is linked to
    one. ``geography`` is required, so its models are always there to ask.
    """
    refs = []
    if kind == "zone":
        refs.append(_ref("boundary", obj.boundary, base))
    elif kind != "boundary" and geometry is not None:
        point = geometry if geometry.geom_type == "Point" else geometry.point_on_surface
        Boundary = apps.get_model("geography", "Boundary")
        for boundary in Boundary.objects.filter(geometry__contains=point).order_by("pk"):
            refs.append(_ref("boundary", boundary, base))

    if kind == "use-area":
        ParcelZone = apps.get_model("geography", "ParcelZone")
        for link in ParcelZone.objects.filter(parcel=obj).select_related("zone").order_by("zone__pk"):
            refs.append(_ref("zone", link.zone, base))
    elif kind == "recharge-site" and obj.zone_id:
        refs.append(_ref("zone", obj.zone, base))
    elif kind == "facility":
        refs.append(_ref("water-system", obj.system, base))
    elif kind == "sampling-point":
        refs.append(_ref("facility", obj.facility, base))
    return refs


def _identifiers(kind, obj):
    out = []
    for field in IDENTIFIER_FIELDS[kind]:
        value = getattr(obj, field, "")
        if value in (None, ""):
            continue
        out.append({
            "@type": "schema:PropertyValue",
            "schema:propertyID": field,
            "schema:value": str(value),
        })
    return out


def jsonld_for(obj, request=None, base=None):
    """The record's JSON-LD document, built from the record's own fields only."""
    kind = kind_for(obj)
    if base is None:
        base = identifier_base(request)
    doc = {
        "@context": dict(_CONTEXT),
        "@id": identifier_for(obj, base=base),
        "@type": "schema:Thing" if kind == "water-right" else "schema:Place",
        "schema:additionalType": kind,
        "schema:name": _record_name(kind, obj),
    }
    description = getattr(obj, "description", "")
    if description and kind in ("boundary", "zone"):
        doc["schema:description"] = description
    local_name = getattr(obj, "local_name", "")
    if local_name:
        doc["schema:alternateName"] = local_name

    identifiers = _identifiers(kind, obj)
    if identifiers:
        doc["schema:identifier"] = identifiers

    if kind == "water-right":
        if obj.holder_name:
            # schema.org has no `holder`; `owner` is Thing -> Organization or
            # Person, left untyped so the document does not claim which.
            doc["schema:owner"] = {"schema:name": obj.holder_name}
        return doc

    geometry, point = _geometry(kind, obj)
    if geometry is not None:
        doc.update(_geo_nodes(geometry, point))
    contained = _contained_in(kind, obj, geometry, base)
    if contained:
        doc["schema:containedInPlace"] = contained
    return doc
