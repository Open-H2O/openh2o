# SPDX-License-Identifier: AGPL-3.0-or-later
"""
OpenET pre-fill service.

Derives labeled, monthly water-volume values from the crop ET OpenH2O records for
each use area and month (datasync.crop_et.recorded_acre_feet: the record's depth
over the use area's acres, the figure the calculation and the month's page read).
The point is to save the user from typing twelve monthly numbers from scratch
when they prepare a GEARS or CalWATRS filing.

Three rules keep this honest — they are the whole reason the feature exists:

  1. Raw ET, no hidden math. The value is the satellite consumptive-use estimate
     converted to acre-feet. We do NOT subtract precipitation or surface
     deliveries to "back-calculate" pumping. The honesty comes from the label,
     not from a model the user can't see.

  2. Every value carries OPENET_PREFILL_LABEL. ET (the water crops consumed) is
     NOT the same as metered pumping or a diverted volume — a well can pump less
     than its parcels' ET because rain and surface deliveries also feed the crop.
     The user must reconcile that before certifying in the state portal under
     penalty of perjury, so the label travels with every single value.

  3. Read-only. This service never writes to ParcelLedger. The user's reviewed and
     edited values are persisted on ReportSubmission.prefill_overrides instead,
     which no report file reads.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable

from reporting.generators import (
    build_normalized_well_parcel_map,
    build_pod_split_by_month,
)

if TYPE_CHECKING:
    from datetime import date

    from accounting.models import ReportingPeriod

# The provenance label that MUST appear on every pre-filled value. Tested for
# exact-string equality (tests/test_reporting_prefill.py) because it is the
# correctness-critical guard that keeps the perjury certification honest.
OPENET_PREFILL_LABEL = "OpenET consumptive-use estimate, not metered pumping"

# report_template.report_type → pre-fill grouping method.
PREFILL_METHOD_BY_REPORT_TYPE = {
    "gears_by_well": "by_well",
    "gears_by_et": "by_parcel",
    "calwatrs_a1": "calwatrs",
    "calwatrs_a2": "calwatrs",
}


def _month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def _recorded_months(reporting_period: ReportingPeriod) -> list[Any]:
    """Each use area-month's recorded crop ET in the reporting period, in positive acre-feet."""
    from datasync.crop_et import recorded_acre_feet

    return recorded_acre_feet(reporting_period.start_date, reporting_period.end_date)


def _value(month: str, value_af: Decimal) -> dict[str, Any]:
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


def _entity(
    entity_type: str,
    entity_id: int,
    entity_label: str,
    entity_sublabel: str,
    months_by_key: dict[str, Decimal],
) -> dict[str, Any]:
    return {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "entity_label": entity_label,
        "entity_sublabel": entity_sublabel,
        "months": [_value(m, months_by_key[m]) for m in sorted(months_by_key)],
    }


def _prefill_by_well(reporting_period: ReportingPeriod) -> list[dict[str, Any]]:
    """Per well: parcel ET attributed to wells via the normalized fraction map.

    Reuses build_normalized_well_parcel_map() — the SAME allocation the GEARS
    by-well CSV uses — so a multi-parcel well is never double-counted, and the
    pre-fill follows the same measurement-first ET-demand split as the filing.
    """
    well_parcel_map = build_normalized_well_parcel_map(reporting_period)
    acc: dict[int, dict[str, Any]] = {}  # well_id → {"well": well, "months": {month: Decimal}}
    for figure in _recorded_months(reporting_period):
        month = _month_key(figure.month)
        for well, fraction in well_parcel_map.get(figure.parcel_id, []):
            slot = acc.setdefault(well.pk, {"well": well, "months": {}})
            slot["months"][month] = (
                slot["months"].get(month, Decimal("0")) + figure.acre_feet * fraction
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


def _prefill_by_parcel(reporting_period: ReportingPeriod) -> list[dict[str, Any]]:
    """Per parcel: the recorded crop ET volume, ungrouped (GEARS by-ET)."""
    acc: dict[int, dict[str, Any]] = {}  # parcel_id → {"number": str, "months": {month: Decimal}}
    for figure in _recorded_months(reporting_period):
        month = _month_key(figure.month)
        slot = acc.setdefault(figure.parcel_id, {"number": figure.parcel_number, "months": {}})
        slot["months"][month] = slot["months"].get(month, Decimal("0")) + figure.acre_feet

    entities = [
        _entity("parcel", parcel_id, slot["number"], "", slot["months"])
        for parcel_id, slot in acc.items()
    ]
    entities.sort(key=lambda e: e["entity_label"])
    return entities


def _prefill_calwatrs(reporting_period: ReportingPeriod) -> list[dict[str, Any]]:
    """Per Point of Diversion: each use area's crop ET attributed to the points that serve it.

    Uses the CalWATRS file's own split (``build_pod_split_by_month``): each point's
    water in a month divided the way the ledger divided it, else the shares entered,
    else acreage (ruling 226). A use area's figure for a month is attributed by that
    same month's split, so the pre-fill and the file never disagree about a shared
    point. ET is a consumptive-use estimate, not a diverted volume; the label makes
    that explicit; this is a starting figure to reconcile.
    """
    # Local import: `surface` is an optional module, so this must not
    # run at module scope. The CalWATRS pre-fill is surface-water only, so this
    # helper is unreachable without the module.
    from surface.models import PointOfDiversion

    pod_split = build_pod_split_by_month(reporting_period)
    pods_by_id = {
        pod.pk: pod
        for pod in PointOfDiversion.objects.filter(
            pk__in=pod_split.pod_ids()
        ).select_related("water_right")
    }

    # Invert each month's {pod_id: [(parcel_id, weight)]} to {parcel_id: [(pod, weight)]}
    # once per month, so each use area-month's figure is attributed to the points it feeds.
    inverted: dict[str, dict[int, list[tuple[Any, Decimal]]]] = {}

    def parcel_pods(month: str) -> dict[int, list[tuple[Any, Decimal]]]:
        if month not in inverted:
            by_parcel: dict[int, list[tuple[Any, Decimal]]] = {}
            for pod_id, pod in pods_by_id.items():
                for parcel_id, weight in pod_split.for_month(pod_id, month):
                    by_parcel.setdefault(parcel_id, []).append((pod, weight))
            inverted[month] = by_parcel
        return inverted[month]

    acc: dict[int, dict[str, Any]] = {}  # pod_id → {"pod": pod, "months": {month: Decimal}}
    for figure in _recorded_months(reporting_period):
        month = _month_key(figure.month)
        for pod, weight in parcel_pods(month).get(figure.parcel_id, []):
            slot = acc.setdefault(pod.pk, {"pod": pod, "months": {}})
            slot["months"][month] = (
                slot["months"].get(month, Decimal("0")) + figure.acre_feet * weight
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


_PREFILL_BUILDERS: dict[str, Callable[[ReportingPeriod], list[dict[str, Any]]]] = {
    "by_well": _prefill_by_well,
    "by_parcel": _prefill_by_parcel,
    "calwatrs": _prefill_calwatrs,
}


def build_openet_prefill(reporting_period: ReportingPeriod, method: str) -> dict[str, Any]:
    """Build labeled, raw-ET monthly pre-fill values for a reporting period.

    Args:
        reporting_period: accounting.ReportingPeriod to read the recorded crop ET for.
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
