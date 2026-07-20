# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Envirofacts payload → ``drinking`` models: mapping and idempotent commit.

Separate from ``drinking/envirofacts.py`` on purpose. That module does network
I/O and nothing else; this one does interpretation and nothing else. The split
is what lets ``EnvirofactsCache`` store EPA's response VERBATIM — a mapping bug
fixed here takes effect on the very next read instead of surviving until every
cached row expires.

**The one decision everything downstream rests on.** EPA returns two identifiers
for the same physical facility::

    facility_id           14042   ← EPA's own key
    state_facility_id     010     ← the state's key

DDW's real published PS Code for that facility is ``CA1010001_010_010``,
confirmed against California's live SDWIS4.zip export. So
``SystemFacility.facility_id`` is populated from ``state_facility_id``, and
EPA's key is preserved separately in ``epa_facility_id`` for provenance. Mapping
EPA's key would make Phase 80's wizard compose ``CA1010001_14042_001`` and match
nothing in any genuine lab file. See 79-RESEARCH.md § ps_code_resolution.

**Prepare, never determine.** This module records what EPA says. It does not
compute a compliance judgment, and it does not invent a value EPA did not
supply — which is why the population and service-connection splits are left
NULL rather than being fed a single federal aggregate, and why an unrecognised
code is reported to the operator instead of being written into a field whose
published vocabulary it violates.

**Scope call (2026-07-19).** EPA's administrative block carries a named
individual's phone, fax, email and name. Only the mailing ADDRESS is carried
here; nothing else is mapped at all.
"""

import logging
from dataclasses import dataclass, field

from django.db import transaction

from drinking.models import (
    ACTIVITY_STATUS_CHOICES,
    AVAILABILITY_CHOICES,
    FACILITY_TYPE_CHOICES,
    OWNER_TYPE_CHOICES,
    PRIMARY_SOURCE_CHOICES,
    PWS_TYPE_CHOICES,
    WATER_TYPE_CHOICES,
    SystemFacility,
    WaterSystem,
)

logger = logging.getLogger(__name__)


class UnmappableFacility(Exception):
    """EPA carries this facility with no state key, so it cannot be onboarded.

    A PS Code is ``{pwsid}_{facility_id}_{point_number}``; with no state key
    there is no middle segment, so the facility can never receive a lab result.
    Writing it with a blank ``facility_id`` would be worse than skipping it —
    the second such facility would collide on ``unique_together`` and the first
    would sit in the system looking legitimate.
    """


# ── Small helpers ───────────────────────────────────────────────────────────


def _text(value):
    """EPA sends JSON ``null`` for an absent string; the model wants ``""``."""
    return "" if value is None else str(value).strip()


def _flag(value):
    """EPA sends the STRINGS "Y" and "N", not booleans.

    ``bool("N")`` is ``True``, so assigning the raw value would set every flag
    on every system. Anything that is not an explicit "Y" is False.
    """
    return _text(value).upper() == "Y"


def _coded(value, choices, field_name, warnings):
    """Return ``value`` only if it is in a published vocabulary.

    An unrecognised code is REPORTED and dropped, never stored. The code lists
    in ``drinking/models.py`` are transcribed from published DDW and EPA
    valid-value tables, so a miss means EPA published something new — which an
    operator should see, not have quietly written into a field whose choices it
    violates.

    Returns a ``(found, value)`` pair so the caller can omit the key entirely
    rather than write a blank.
    """
    code = _text(value)
    if not code:
        return False, ""
    if code in {c for c, _ in choices}:
        return True, code
    warnings.append(
        f"EPA sent {field_name} \"{code}\", which is not a published value. "
        f"The field was left unset rather than storing an unknown code."
    )
    return False, ""


# ── Pure mapping ────────────────────────────────────────────────────────────


def map_water_system(payload, warnings=None):
    """One ``WATER_SYSTEM`` row → ``WaterSystem`` kwargs. Pure: no DB, no network.

    ``warnings`` is an optional list this appends operator-facing strings to —
    unrecognised codes, and the fact that a system is inactive. Returning them
    alongside the kwargs (rather than as a second return value) keeps the
    function subscriptable, which is what makes it pleasant to test.
    """
    warnings = warnings if warnings is not None else []

    kwargs = {
        "pwsid": _text(payload.get("pwsid")),
        "name": _text(payload.get("pws_name")),
        "is_wholesaler": _flag(payload.get("is_wholesaler_ind")),
        "is_school_or_daycare": _flag(payload.get("is_school_or_daycare_ind")),
        # Address only — see the module docstring's scope call. Nothing maps
        # phone_number, fax_number, alt_phone_number, email_addr, admin_name or
        # org_name, and nothing should be added that does.
        "mailing_address_line1": _text(payload.get("address_line1")),
        "mailing_address_line2": _text(payload.get("address_line2")),
        "mailing_city": _text(payload.get("city_name")),
        # EPA's state_code is the ADMINISTRATOR'S MAILING state, not the primacy
        # state. PWSID 083090017 is a Colorado system whose state_code is "CA".
        "mailing_state": _text(payload.get("state_code")),
        "mailing_zip": _text(payload.get("zip_code")),
    }

    for source_key, target, choices in (
        ("pws_activity_code", "activity_status", ACTIVITY_STATUS_CHOICES),
        ("pws_type_code", "pws_type", PWS_TYPE_CHOICES),
        ("owner_type_code", "owner_type", OWNER_TYPE_CHOICES),
        ("primary_source_code", "primary_source_code", PRIMARY_SOURCE_CHOICES),
    ):
        found, code = _coded(payload.get(source_key), choices, target, warnings)
        if found:
            kwargs[target] = code

    if kwargs.get("activity_status") == "I":
        deactivated = _text(payload.get("pws_deactivation_date"))
        warnings.append(
            f"EPA lists this system as inactive"
            f"{f' (deactivated {deactivated[:10]})' if deactivated else ''}. "
            f"That is not a reason to stop — an operator may legitimately be "
            f"researching a deactivated system — but it should be confirmed."
        )

    # NOT mapped, deliberately: population_residential / _non_transient /
    # _transient, and the five connections_* fields. EPA sends ONE
    # population_served_count and ONE service_connections_count. Feeding an
    # aggregate into the residential field would misattribute transient
    # population as residents. All eight stay NULL until a source that actually
    # breaks them down is imported.
    #
    # Also not mapped: state_classification (EPA does not send it),
    # regulating_agency (primacy_agency_code is a state code, not a DDW district
    # office — writing it there would be inventing a value).
    return kwargs


def map_facility(payload, warnings=None):
    """One ``WATER_SYSTEM_FACILITY`` row → ``SystemFacility`` kwargs.

    Raises :class:`UnmappableFacility` when EPA carries no ``state_facility_id``.
    Never returns a ``well`` key — see :func:`commit_system`.
    """
    warnings = warnings if warnings is not None else []

    epa_facility_id = _text(payload.get("facility_id"))
    # THE mapping. state_facility_id, not facility_id. Read the module docstring
    # before changing this line.
    state_facility_id = _text(payload.get("state_facility_id"))

    if not state_facility_id:
        raise UnmappableFacility(
            f"EPA facility {epa_facility_id or '(unidentified)'} "
            f"(\"{_text(payload.get('facility_name'))}\") has no "
            f"state_facility_id, so it cannot be given a PS Code. Skipped."
        )

    kwargs = {
        # Stored verbatim as a string. Never coerce to int, zero-pad, or sort
        # numerically: "DST" is a real, live key carrying CA1010001_DST_900.
        "facility_id": state_facility_id,
        "epa_facility_id": epa_facility_id,
        "name": _text(payload.get("facility_name")),
        "is_source": _flag(payload.get("is_source_ind")),
    }

    label = f"facility {state_facility_id}"
    for source_key, target, choices in (
        ("facility_activity_code", "activity_status", ACTIVITY_STATUS_CHOICES),
        ("facility_type_code", "facility_type", FACILITY_TYPE_CHOICES),
        ("water_type_code", "water_type", WATER_TYPE_CHOICES),
        ("availability_code", "availability", AVAILABILITY_CHOICES),
    ):
        found, code = _coded(
            payload.get(source_key), choices, f"{label} {target}", warnings
        )
        if found:
            kwargs[target] = code

    return kwargs


def map_geography(payload):
    """``GEOGRAPHIC_AREA`` → plain display strings for the review screen.

    Persists nothing and creates no model. ``area_type_code`` can be
    comma-joined (``"CN,CT"``), so it is not a single code and is not surfaced
    as one; the served-area names are the only useful part, and they are mostly
    null anyway. ``None`` (EPA has no geography row) is a normal answer.
    """
    payload = payload or {}
    return {
        "county_served": _text(payload.get("county_served")),
        "city_served": _text(payload.get("city_served")),
        "state_served": _text(payload.get("state_served")),
    }


# ── Idempotent commit ───────────────────────────────────────────────────────

# The explicit allow-list of EPA-derived facility fields. `defaults` is built
# from THIS, never by splatting the mapped dict, so that `well` can never be
# written by a refresh even if this module later grows a key by that name.
# SystemFacility.well is the quality<->quantity join and linking one is a
# deliberate operator act (ROADMAP.md:56). A regression here would silently
# erase operator work and nothing would fail loudly.
_FACILITY_REFRESHABLE_FIELDS = (
    "epa_facility_id",
    "name",
    "facility_type",
    "activity_status",
    "is_source",
    "water_type",
    "availability",
)

_SYSTEM_REFRESHABLE_FIELDS = (
    "name",
    "activity_status",
    "pws_type",
    "owner_type",
    "primary_source_code",
    "is_wholesaler",
    "is_school_or_daycare",
    "mailing_address_line1",
    "mailing_address_line2",
    "mailing_city",
    "mailing_state",
    "mailing_zip",
)


@dataclass
class CommitResult:
    """What a commit did, in terms the wizard's review screen can render."""

    system: WaterSystem = None
    created: bool = False
    facilities_created: int = 0
    facilities_updated: int = 0
    skipped: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


@transaction.atomic
def commit_system(system_payload, facility_payloads):
    """Onboard or refresh one water system and its facilities, idempotently.

    ``update_or_create``, deliberately — and note this DIVERGES from the house
    idiom. ``datasync/management/commands/discover_stations.py:113`` uses
    ``get_or_create`` precisely so re-discovery never overwrites an operator's
    edits. Here the opposite is wanted: re-running against an already-onboarded
    system is how an operator pulls a fresh federal record, so EPA-derived
    fields are expected to be refreshed.

    The exception is ``SystemFacility.well``, which is never touched. Dedup
    relies on the models' own uniqueness (``WaterSystem.pwsid`` and
    ``unique_together("system", "facility_id")``) rather than a query-then-
    insert, which would race.

    Atomic across both halves: a bad facility payload must not leave a
    half-onboarded system behind for someone to clean up by hand.
    """
    warnings = []
    mapped_system = map_water_system(system_payload, warnings=warnings)
    pwsid = mapped_system["pwsid"]
    if not pwsid:
        raise ValueError("Cannot commit a water system with no PWSID.")

    system, created = WaterSystem.objects.update_or_create(
        pwsid=pwsid,
        defaults={
            key: mapped_system[key]
            for key in _SYSTEM_REFRESHABLE_FIELDS
            if key in mapped_system
        },
    )

    result = CommitResult(system=system, created=created, warnings=warnings)

    for payload in facility_payloads:
        try:
            mapped = map_facility(payload, warnings=warnings)
        except UnmappableFacility as exc:
            result.skipped.append(str(exc))
            logger.info("envirofacts: %s", exc)
            continue

        _, facility_created = SystemFacility.objects.update_or_create(
            system=system,
            facility_id=mapped["facility_id"],
            defaults={
                key: mapped[key]
                for key in _FACILITY_REFRESHABLE_FIELDS
                if key in mapped
            },
        )
        if facility_created:
            result.facilities_created += 1
        else:
            result.facilities_updated += 1

    return result
