# SPDX-License-Identifier: AGPL-3.0-or-later
"""System onboarding from EPA's public record, and the sampling-point builder that follows it."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST
from drinking import envirofacts, envirofacts_mapping, glossary
from drinking.ps_codes import (
    MAX_PS_CODE_LENGTH,
    compose_ps_code,
    uses_california_ps_codes,
)
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
from drinking.views.common import _describe


# ---------------------------------------------------------------------------
# System onboarding: page -> lookup -> commit
# ---------------------------------------------------------------------------
#
# The operator-facing door onto the Envirofacts adapter (drinking/envirofacts.py). Same three-step
# shape as the lab import above, for the same reason: nothing is written until
# the operator has seen exactly what a commit would do, including what it would
# SKIP.
#
# **The session holds only the PWSID.** Sessions are `signed_cookies`
# — there is no server-side store, the session IS the cookie, and a browser caps
# a cookie at roughly 4 KB. Bakman alone returns 36 facilities against a ~45-field
# WaterSystem; stashing the mapped payloads would blow that ceiling, and the
# failure mode is a silently dropped or truncated cookie rather than a clean
# exception — you would be debugging "the wizard forgets everything on step 2".
#
# Re-fetching on commit costs nothing: `fetch_water_system` / `fetch_facilities`
# / `fetch_geographic_area` are cache-backed by `EnvirofactsCache` (30-day TTL),
# so the commit step reads the same cached rows the review step read, with no
# second network call. It also guarantees review and commit see the same bytes,
# which a session copy could not if the cache refreshed in between.

#: The ONLY thing the wizard puts in the session. Read the block above before
#: adding a second key that carries a payload.
SESSION_KEY_ONBOARD_PWSID = "drinking_onboard_pwsid"


@login_required
@require_GET
def onboard_page(request):
    """The PWSID entry screen — one input and an honest note about scope."""
    return render(request, "drinking/onboard.html", {})


def _code_label(code, choices):
    """Show the published label, falling back to the raw code.

    A code that survived ``_coded`` is always in the vocabulary, so the fallback
    only fires for a value the mapping deliberately dropped — in which case
    showing the code beats showing an empty cell.
    """
    return dict(choices).get(code, code)


def _collect_federal_record(pwsid):
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
                "facility_type": _code_label(
                    mapped.get("facility_type", ""), FACILITY_TYPE_CHOICES
                ),
                "water_type": _code_label(
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


def _review_context(collected):
    """Shape one collected federal record for the review partial."""
    mapped = collected["mapped_system"]
    raw = collected["system_row"]
    pwsid = collected["pwsid"]

    existing = WaterSystem.objects.filter(pwsid=pwsid).first()

    return {
        "pwsid": pwsid,
        "name": mapped.get("name", ""),
        "activity_status": _code_label(
            mapped.get("activity_status", ""), ACTIVITY_STATUS_CHOICES
        ),
        "pws_type": _code_label(mapped.get("pws_type", ""), PWS_TYPE_CHOICES),
        "owner_type": _code_label(mapped.get("owner_type", ""), OWNER_TYPE_CHOICES),
        "primary_source": _code_label(
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


@login_required
@require_POST
def onboard_lookup(request):
    """Fetch and map a PWSID's federal record, and render the review. Writes nothing."""
    pwsid = (request.POST.get("pwsid") or "").strip().upper()
    if not pwsid:
        return render(
            request,
            "drinking/partials/_onboard_review.html",
            {"error_kind": "empty", "error": "Enter a PWSID to look up."},
        )

    # Specific first. PwsidNotFound and EnvirofactsUnavailable both subclass
    # EnvirofactsError, so putting the base class first would swallow both and
    # tell an operator holding a perfectly good PWSID that EPA has no such
    # system. Order here is load-bearing, not stylistic.
    try:
        collected = _collect_federal_record(pwsid)
    except envirofacts.PwsidNotFound as exc:
        return render(
            request,
            "drinking/partials/_onboard_review.html",
            {"error_kind": "not_found", "error": str(exc), "pwsid": pwsid},
        )
    except envirofacts.EnvirofactsUnavailable as exc:
        return render(
            request,
            "drinking/partials/_onboard_review.html",
            {"error_kind": "unavailable", "error": str(exc), "pwsid": pwsid},
        )
    except envirofacts.EnvirofactsError as exc:
        return render(
            request,
            "drinking/partials/_onboard_review.html",
            {"error_kind": "service_error", "error": str(exc), "pwsid": pwsid},
        )

    # Only the id, and only after a lookup actually succeeded. See the block at
    # the top of this section on why nothing else goes in here.
    request.session[SESSION_KEY_ONBOARD_PWSID] = pwsid

    return render(
        request, "drinking/partials/_onboard_review.html", _review_context(collected)
    )


@login_required
@require_POST
def onboard_commit(request):
    """Re-fetch the session's PWSID from cache and write the system + facilities."""
    pwsid = request.session.get(SESSION_KEY_ONBOARD_PWSID)
    if not pwsid:
        # A stale tab or an expired cookie is an ordinary event, not an error.
        # Sending an operator to a 500 for closing their laptop overnight would
        # be the wizard's fault, not theirs.
        return render(
            request,
            "drinking/partials/_onboard_result.html",
            {"expired": True},
        )

    # Same order as the lookup, and for the same reason. The fetch is a cache
    # hit (EnvirofactsCache, 30-day TTL) so this costs a DB read, not a second
    # federal round-trip — but the cache can legitimately have been refreshed or
    # the service can have gone down between the two steps, so all three
    # failures still have to be handled here.
    try:
        collected = _collect_federal_record(pwsid)
    except envirofacts.PwsidNotFound as exc:
        return render(
            request,
            "drinking/partials/_onboard_result.html",
            {"error_kind": "not_found", "error": str(exc), "pwsid": pwsid},
        )
    except envirofacts.EnvirofactsUnavailable as exc:
        return render(
            request,
            "drinking/partials/_onboard_result.html",
            {"error_kind": "unavailable", "error": str(exc), "pwsid": pwsid},
        )
    except envirofacts.EnvirofactsError as exc:
        return render(
            request,
            "drinking/partials/_onboard_result.html",
            {"error_kind": "service_error", "error": str(exc), "pwsid": pwsid},
        )

    # `commit_system` is already @transaction.atomic, so a bad facility payload
    # cannot leave a half-onboarded system behind. Deliberately NOT wrapped in a
    # second transaction and given no compensating cleanup — both would fight a
    # guarantee that already holds. It also takes the RAW payloads and maps them
    # itself, which is why `_collect_federal_record` keeps them.
    result = envirofacts_mapping.commit_system(
        collected["system_row"], collected["facility_rows"]
    )

    del request.session[SESSION_KEY_ONBOARD_PWSID]

    return render(
        request,
        "drinking/partials/_onboard_result.html",
        {
            "result": result,
            "pwsid": pwsid,
            "epa_facility_count": len(collected["facility_rows"]),
        },
    )


# ---------------------------------------------------------------------------
# Sampling-point builder: the second half of onboarding
# ---------------------------------------------------------------------------
#
# Onboarding creates a system and its facilities. That looks finished and is
# not: `drinking.importer` matches every lab row on PS Code, and a PS Code lives
# on a SamplingPoint. Until points exist, a real lab file cannot import at all —
# every row is an unknown-PS-Code error. This is the surface that closes it.
#
# **Points are created here and only here** — by explicit operator action, never
# as an import side effect. The importer's refusal to invent structure is the
# guarantee that makes an unknown PS Code meaningful, so an "auto-create on
# import" convenience would quietly destroy the thing it appears to help.
#
# **Distribution-system program points need no special case.** LCR and DBPR
# points hang off the distribution system rather than a source facility, but the
# distribution system arrives from EPA as an ordinary SystemFacility
# (`facility_id` = `DST`). So `CA1010001_DST_LCR` is a normal point on a normal
# facility. The only thing this owes it is copy that does not assume "facility"
# means "well", and a point-number field that accepts letters.


def _facility_panels(system):
    """Every committed facility for one system, with the points already on it."""
    return (
        system.facilities
        .prefetch_related("sampling_points")
        .order_by("facility_id")
    )


def _facility_select_order(facilities):
    """Sources first, then the rest, each group in facility-id order.

    The builder's facility select is the one place
    order matters, since a source facility is disproportionately what an
    operator is adding a point to (it is where water enters the system, the
    thing a program most often samples). ``sorted`` is stable, so within each
    group ``_facility_panels``'s own facility-id order survives.
    """
    return sorted(facilities, key=lambda f: not f.is_source)


def _points_listed_context(system, facilities):
    """The grouped-table state for the builder's listed-points card.

    Shared by the full-page GET and by ``onboard_points_add``'s POST response
    so the two can never drift apart the way a hand-spliced row would: the
    add view calls this on a freshly refetched facility list, never patches
    the group it just added to.

    A facility with no points is left out of ``point_groups`` entirely (the
    head's "n of m" already says such facilities exist); it never disappears
    from the system, only from this table.
    """
    point_groups = []
    n_with = 0
    point_count = 0
    for facility in facilities:
        points = list(facility.sampling_points.all())
        if not points:
            continue
        n_with += 1
        point_count += len(points)
        point_groups.append({"facility": facility, "points": points})
    return {
        "system": system,
        "pwsid": system.pwsid,
        "facilities": facilities,
        "point_groups": point_groups,
        "point_count": point_count,
        "n_with": n_with,
        "california_codes": uses_california_ps_codes(system.pwsid),
    }


@login_required
@require_GET
def onboard_points(request, pwsid):
    """The system-wide sampling-point builder: one form, one grouped table.

    Guarded rather than rendered empty: a system that was never onboarded has no
    facilities to hang points on, and an empty page would read as "this system
    has no facilities" instead of "you have not onboarded this system yet".
    """
    pwsid = (pwsid or "").strip().upper()
    system = WaterSystem.objects.filter(pwsid=pwsid).first()

    if system is None:
        messages.warning(
            request,
            f"No water system in OpenH2O has the PWSID {pwsid}. Add the water "
            "system first.",
        )
        return redirect("drinking:onboard")

    facilities = [_describe(f) for f in _facility_panels(system)]
    if not facilities:
        messages.warning(
            request,
            f"{system.name} has no facilities on file. Add a facility first.",
        )
        return redirect("drinking:onboard")

    # ONE ordered list, reused everywhere on the page: the select's options,
    # the grouped table's row order, and the "n of m" count line's length.
    # Sorted once here rather than per-consumer so the select and the table
    # below it never present two different orders for the same facilities.
    facilities = _facility_select_order(facilities)

    return render(
        request,
        "drinking/onboard_points.html",
        {
            "system": system,
            "point_type_choices": POINT_TYPE_CHOICES,
            # Only the abbreviations that actually appear on this page.
            "shorthand": glossary.shorthand_in_use(
                [f.name for f in facilities]
                + [f.facility_id for f in facilities]
                + [p.name for f in facilities for p in f.sampling_points.all()]
            ),
            **_points_listed_context(system, facilities),
        },
    )


@login_required
@require_POST
def onboard_points_add(request, pwsid):
    """Add one sampling point to one facility. Renders the WHOLE listed-points
    table back, regrouped, plus the status alert out of band.

    A duplicate is reported and skipped, not raised: an operator re-walking a
    partially-completed system is the ordinary case, not an error. ``get_or_create``
    rather than an ``exists()`` check so two operators racing the same code get a
    plain "already there" instead of an IntegrityError 500.

    Every branch below renders
    ``_onboard_points_listed.html``, never the bare alert the old per-facility
    panel returned on an error: the operator's whole table has to stay on
    screen (``hx-target="#points-listed"``, ``hx-swap="outerHTML"``) whatever
    the outcome, with the alert riding along as an out-of-band swap into
    ``#point-add-status``.
    """
    pwsid = (pwsid or "").strip().upper()
    system = WaterSystem.objects.filter(pwsid=pwsid).first()
    if system is None:
        return render(
            request,
            "drinking/partials/_onboard_points_listed.html",
            {
                "system": None,
                "pwsid": pwsid,
                "facilities": [],
                "point_groups": [],
                "point_count": 0,
                "n_with": 0,
                "error": (
                    f"No water system in OpenH2O has the PWSID {pwsid}. Add "
                    "the water system first."
                ),
            },
        )

    def _listed(**status):
        facilities = _facility_select_order(
            [_describe(f) for f in _facility_panels(system)]
        )
        return render(
            request,
            "drinking/partials/_onboard_points_listed.html",
            {**_points_listed_context(system, facilities), **status},
        )

    facility = system.facilities.filter(
        pk=(request.POST.get("facility") or "").strip() or None
    ).first()
    if facility is None:
        return _listed(
            error=f"The facility you chose does not belong to {system.name}."
        )

    point_number = (request.POST.get("point_number") or "").strip()
    name = (request.POST.get("name") or "").strip()
    point_type = (request.POST.get("point_type") or "").strip()

    if uses_california_ps_codes(system.pwsid):
        # Composition is the validator. Rather than re-implementing the rules
        # here (and drifting from them), the ValueError text is shown as-is: it
        # already names which part was wrong and why.
        try:
            ps_code = compose_ps_code(
                system.pwsid, facility.facility_id, point_number
            )
        except ValueError as exc:
            return _listed(error=str(exc))
    else:
        # Another state's lab file writes the code its own way, so it is stored
        # as typed (outer whitespace only). Uniqueness is the same
        # ``get_or_create`` below, which reports a duplicate instead of raising.
        ps_code = (request.POST.get("ps_code") or "").strip()
        if not ps_code:
            return _listed(
                error="Enter the sampling point code."
            )
        if len(ps_code) > MAX_PS_CODE_LENGTH:
            return _listed(
                error=(
                    f"A sampling point code can have up to {MAX_PS_CODE_LENGTH} "
                    f"characters, and this one has {len(ps_code)}."
                )
            )

    if point_type and point_type not in dict(POINT_TYPE_CHOICES):
        return _listed(
            error="Choose a point type: Source, Entry Point, Distribution or Tap."
        )

    point, created = SamplingPoint.objects.get_or_create(
        ps_code=ps_code,
        defaults={"facility": facility, "name": name, "point_type": point_type},
    )

    return _listed(
        added=point if created else None,
        duplicate=None if created else point,
    )
