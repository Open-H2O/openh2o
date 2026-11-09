# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the Add a water system page and the add_water_system command share.

Looking up a PWSID, shaping EPA's record for review, and adding a sampling point
live here so the page and the commands run one code path.
"""
from drinking import envirofacts, envirofacts_mapping
from drinking.models import (
    ACTIVITY_STATUS_CHOICES,
    FACILITY_TYPE_CHOICES,
    OWNER_TYPE_CHOICES,
    POINT_TYPE_CHOICES,
    PRIMARY_SOURCE_CHOICES,
    PWS_TYPE_CHOICES,
    WATER_TYPE_CHOICES,
    SamplingPoint,
    WaterSystem,
)
from drinking.ps_codes import (
    MAX_PS_CODE_LENGTH,
    compose_ps_code,
    uses_california_ps_codes,
)


def system_the_site_keeps_instead(pwsid):
    """The site's existing water system when ``pwsid`` is not one of its systems, else None.

    A site keeps one water system's records. Looking up or confirming the same
    PWSID again is a refresh and passes; a different one is turned down. A site
    with no water system takes any PWSID.
    """
    existing = list(WaterSystem.objects.order_by("pwsid"))
    if not existing or any(system.pwsid == pwsid for system in existing):
        return None
    return existing[0]


def code_label(code, choices):
    """Show the published label, falling back to the raw code.

    A code that survived ``_coded`` is always in the vocabulary, so the fallback
    only fires for a value the mapping deliberately dropped, in which case
    showing the code beats showing an empty cell.
    """
    return dict(choices).get(code, code)


def collect_federal_record(pwsid):
    """Fetch all three EPA tables for one PWSID and map them. **Writes nothing.**

    The single place the wizard talks to Envirofacts, so review and commit ask
    the same question the same way. Every call is cache-backed, so the commit
    step's repeat of this work is a DB read, not a second federal round-trip.

    Returns the raw rows alongside the mapped ones: ``commit_system`` takes raw
    payloads (it maps internally, so a mapping fix reaches it without a caller
    change), while the review screen needs the mapped values plus the two raw
    EPA aggregates that are deliberately never written.
    """
    warnings = []

    system_row = envirofacts.fetch_water_system(pwsid)
    facility_rows = envirofacts.fetch_facilities(pwsid)
    geography_row = envirofacts.fetch_geographic_area(pwsid)

    mapped_system = envirofacts_mapping.map_water_system(system_row, warnings=warnings)

    facilities = []
    skipped = []
    for row in facility_rows:
        try:
            mapped = envirofacts_mapping.map_facility(row, warnings=warnings)
        except envirofacts_mapping.UnmappableFacility as exc:
            # Kept as its own list rather than folded into `warnings`: a skip is
            # a facility that will not exist, which is a different fact from a
            # code that was not recognised.
            skipped.append(str(exc))
            continue
        facilities.append(
            {
                "facility_id": mapped["facility_id"],
                "epa_facility_id": mapped.get("epa_facility_id", ""),
                "name": mapped.get("name", ""),
                "facility_type": code_label(
                    mapped.get("facility_type", ""), FACILITY_TYPE_CHOICES
                ),
                "water_type": code_label(
                    mapped.get("water_type", ""), WATER_TYPE_CHOICES
                ),
                "is_source": mapped.get("is_source", False),
            }
        )

    return {
        "pwsid": pwsid,
        "system_row": system_row,
        "facility_rows": facility_rows,
        "mapped_system": mapped_system,
        "facilities": facilities,
        "skipped": skipped,
        "geography": envirofacts_mapping.map_geography(geography_row),
        "warnings": warnings,
    }


def review(collected):
    """Shape one collected federal record for the review page and the command's dry run."""
    mapped = collected["mapped_system"]
    raw = collected["system_row"]
    pwsid = collected["pwsid"]

    existing = WaterSystem.objects.filter(pwsid=pwsid).first()

    return {
        "pwsid": pwsid,
        "name": mapped.get("name", ""),
        "activity_status": code_label(
            mapped.get("activity_status", ""), ACTIVITY_STATUS_CHOICES
        ),
        "pws_type": code_label(mapped.get("pws_type", ""), PWS_TYPE_CHOICES),
        "owner_type": code_label(mapped.get("owner_type", ""), OWNER_TYPE_CHOICES),
        "primary_source": code_label(
            mapped.get("primary_source_code", ""), PRIMARY_SOURCE_CHOICES
        ),
        "mailing": mapped,
        # Straight off EPA's row, NOT off the model: these two aggregates are
        # shown because an operator should see what EPA holds, and are not
        # written because the model carries a 3-way and a 5-way split that no
        # single total can honestly be divided into.
        "epa_population_served": raw.get("population_served_count"),
        "epa_service_connections": raw.get("service_connections_count"),
        "geography": collected["geography"],
        "facilities": collected["facilities"],
        "facility_count": len(collected["facilities"]),
        "epa_facility_count": len(collected["facility_rows"]),
        "skipped": collected["skipped"],
        "warnings": collected["warnings"],
        "already_onboarded": existing is not None,
        "existing_facility_count": (
            existing.facilities.count() if existing is not None else 0
        ),
    }


def add_sampling_point(system, facility, *, point_number="", ps_code="", name="", point_type=""):
    """Add one sampling point to one facility of ``system``. Returns ``(point, created)``.

    A duplicate is reported and skipped, not raised: an operator re-walking a
    partially-completed system is the ordinary case, not an error. ``get_or_create``
    rather than an ``exists()`` check so two operators racing the same code get a
    plain "already there" instead of an IntegrityError.

    Raises ``ValueError`` with the sentence a person reads when the point cannot
    be added. The caller checks that ``facility`` belongs to ``system``.
    """
    point_number = (point_number or "").strip()
    name = (name or "").strip()
    point_type = (point_type or "").strip()

    if uses_california_ps_codes(system.pwsid):
        # Composition is the validator. Rather than re-implementing the rules
        # here (and drifting from them), the ValueError text is shown as-is: it
        # already names which part was wrong and why.
        ps_code = compose_ps_code(system.pwsid, facility.facility_id, point_number)
    else:
        # Another state's lab file writes the code its own way, so it is stored
        # as typed (outer whitespace only). Uniqueness is the same
        # ``get_or_create`` below, which reports a duplicate instead of raising.
        ps_code = (ps_code or "").strip()
        if not ps_code:
            raise ValueError("Enter the sampling point code.")
        if len(ps_code) > MAX_PS_CODE_LENGTH:
            raise ValueError(
                f"A sampling point code can have up to {MAX_PS_CODE_LENGTH} "
                f"characters, and this one has {len(ps_code)}."
            )

    if point_type and point_type not in dict(POINT_TYPE_CHOICES):
        raise ValueError(
            "Choose a point type: Source, Entry Point, Distribution or Tap."
        )

    return SamplingPoint.objects.get_or_create(
        ps_code=ps_code,
        defaults={"facility": facility, "name": name, "point_type": point_type},
    )
