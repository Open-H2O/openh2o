"""
OpenET pre-fill service.

Derives labeled, monthly water-volume values from the OpenET evapotranspiration
data that already lives in the parcel ledger (ParcelLedger entries with
source_type="et_estimate", written by accounting.management.commands
.sync_openet_to_ledger). The point is to save the user from typing twelve
monthly numbers from scratch when they prepare a GEARS or CalWATRS filing.

Three rules keep this honest — they are the whole reason the feature exists:

  1. Raw ET, no hidden math. The value is the satellite consumptive-use estimate
     converted to acre-feet exactly as the ledger stores it. We do NOT subtract
     precipitation or surface deliveries to "back-calculate" pumping. The honesty
     comes from the label, not from a model the user can't see.

  2. Every value carries OPENET_PREFILL_LABEL. ET (the water crops consumed) is
     NOT the same as metered pumping or a diverted volume — a well can pump less
     than its parcels' ET because rain and surface deliveries also feed the crop.
     The user must reconcile that before certifying in the state portal under
     penalty of perjury, so the label travels with every single value.

  3. Read-only. This service never writes to ParcelLedger. The user's reviewed and
     edited values are persisted on ReportSubmission.prefill_overrides instead, so
     they can never double-count against the et_estimate entries the report
     generators already read.
"""

from decimal import Decimal

from parcels.models import ParcelLedger
from surface.models import PointOfDiversionParcel

from reporting.generators import build_normalized_well_parcel_map

# The provenance label that MUST appear on every pre-filled value. Tested for
# exact-string equality (tests/test_reporting_prefill.py) because it is the
# correctness-critical guard that keeps the perjury certification honest.
OPENET_PREFILL_LABEL = "OpenET consumptive-use estimate — not metered pumping"

# report_template.report_type → pre-fill grouping method.
PREFILL_METHOD_BY_REPORT_TYPE = {
    "gears_by_well": "by_well",
    "gears_by_et": "by_parcel",
    "calwatrs_a1": "calwatrs",
    "calwatrs_a2": "calwatrs",
}


def _month_key(d):
    return d.strftime("%Y-%m")


def _et_estimate_entries(reporting_period):
    """The et_estimate ledger entries inside the reporting period.

    These are stored negative (ET is consumption); callers take abs() so the
    pre-fill shows positive acre-feet, matching how the CSV generators report.
    """
    return ParcelLedger.objects.filter(
        source_type="et_estimate",
        effective_date__gte=reporting_period.start_date,
        effective_date__lte=reporting_period.end_date,
    ).select_related("parcel")


def _value(month, value_af):
    """One labeled, editable monthly value object.

    Every value the pre-fill emits goes through here, so the provenance label is
    structurally impossible to omit.
    """
    return {
        "month": month,
        "value_af": value_af,
        "source": "openet",
        "label": OPENET_PREFILL_LABEL,
        "editable": True,
    }


def _entity(entity_type, entity_id, entity_label, entity_sublabel, months_by_key):
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "entity_label": entity_label,
        "entity_sublabel": entity_sublabel,
        "months": [_value(m, months_by_key[m]) for m in sorted(months_by_key)],
    }


def _prefill_by_well(reporting_period):
    """Per well: parcel ET attributed to wells via the normalized fraction map.

    Reuses build_normalized_well_parcel_map() — the SAME allocation the GEARS
    by-well CSV uses — so a multi-parcel well is never double-counted.
    """
    well_parcel_map = build_normalized_well_parcel_map()
    acc = {}  # well_id → {"well": well, "months": {month: Decimal}}
    for entry in _et_estimate_entries(reporting_period):
        month = _month_key(entry.effective_date)
        for well, fraction in well_parcel_map.get(entry.parcel_id, []):
            slot = acc.setdefault(well.pk, {"well": well, "months": {}})
            slot["months"][month] = (
                slot["months"].get(month, Decimal("0"))
                + abs(entry.amount_acre_feet) * fraction
            )

    entities = [
        _entity(
            "well",
            slot["well"].pk,
            str(slot["well"]),
            slot["well"].well_registration_id or "",
            slot["months"],
        )
        for slot in acc.values()
    ]
    entities.sort(key=lambda e: (e["entity_sublabel"], e["entity_label"]))
    return entities


def _prefill_by_parcel(reporting_period):
    """Per parcel: the raw et_estimate volume, ungrouped (GEARS by-ET)."""
    acc = {}  # parcel_id → {"parcel": parcel, "months": {month: Decimal}}
    for entry in _et_estimate_entries(reporting_period):
        month = _month_key(entry.effective_date)
        slot = acc.setdefault(entry.parcel_id, {"parcel": entry.parcel, "months": {}})
        slot["months"][month] = (
            slot["months"].get(month, Decimal("0")) + abs(entry.amount_acre_feet)
        )

    entities = [
        _entity("parcel", slot["parcel"].pk, slot["parcel"].parcel_number, "", slot["months"])
        for slot in acc.values()
    ]
    entities.sort(key=lambda e: e["entity_label"])
    return entities


def _prefill_calwatrs(reporting_period):
    """Per Point of Diversion: parcel ET attributed to PODs via PointOfDiversionParcel.

    Mirrors generate_calwatrs_csv's parcel→POD fraction handling (raw fractions,
    no extra normalization). ET is a consumptive-use estimate, not a diverted
    volume — the label makes that explicit; this is a starting figure to reconcile.
    """
    pod_parcel_map = {}  # parcel_id → [(pod, fraction)]
    for podp in PointOfDiversionParcel.objects.select_related(
        "point_of_diversion__water_right"
    ):
        pod_parcel_map.setdefault(podp.parcel_id, []).append(
            (podp.point_of_diversion, podp.fraction)
        )

    acc = {}  # pod_id → {"pod": pod, "months": {month: Decimal}}
    for entry in _et_estimate_entries(reporting_period):
        month = _month_key(entry.effective_date)
        for pod, fraction in pod_parcel_map.get(entry.parcel_id, []):
            slot = acc.setdefault(pod.pk, {"pod": pod, "months": {}})
            slot["months"][month] = (
                slot["months"].get(month, Decimal("0"))
                + abs(entry.amount_acre_feet) * fraction
            )

    entities = [
        _entity(
            "pod",
            slot["pod"].pk,
            slot["pod"].name,
            slot["pod"].water_right.right_id if slot["pod"].water_right_id else "",
            slot["months"],
        )
        for slot in acc.values()
    ]
    entities.sort(key=lambda e: e["entity_label"])
    return entities


_PREFILL_BUILDERS = {
    "by_well": _prefill_by_well,
    "by_parcel": _prefill_by_parcel,
    "calwatrs": _prefill_calwatrs,
}


def build_openet_prefill(reporting_period, method):
    """Build labeled, raw-ET monthly pre-fill values for a reporting period.

    Args:
        reporting_period: accounting.ReportingPeriod to read et_estimate entries for.
        method: "by_well" (GEARS by well), "by_parcel" (GEARS by ET), or
            "calwatrs" (per Point of Diversion).

    Returns:
        {
          "method": <method>,
          "label": OPENET_PREFILL_LABEL,
          "entities": [
            {"entity_type", "entity_id", "entity_label", "entity_sublabel",
             "months": [{"month", "value_af", "source", "label", "editable"}, ...]},
            ...
          ],
        }

    Values are raw ET in acre-feet (no precip/delivery subtraction). This never
    writes to ParcelLedger.
    """
    builder = _PREFILL_BUILDERS.get(method)
    if builder is None:
        raise ValueError(
            f"Unknown pre-fill method {method!r}; "
            f"expected one of {sorted(_PREFILL_BUILDERS)}."
        )
    return {
        "method": method,
        "label": OPENET_PREFILL_LABEL,
        "entities": builder(reporting_period),
    }
