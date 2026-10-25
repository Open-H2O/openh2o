# SPDX-License-Identifier: AGPL-3.0-or-later
"""The administrator pages that tune the calculation: agency-wide delivery settings, and the methodology steps with a preview on a sample parcel."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.history import change_note
from accounting.calculation import evaluate_chain
from accounting.models import CalculationPlan, CalculationRun, CalculationStep
from accounting.precip_math import METHOD_LABELS
from core.access import admin_required
from core.models import SiteConfig
from parcels.models import Parcel
from accounting.views.calculation_runs import _delivery_split_kind, _step_detail_summary


# Methodology tuning is an administrator's job, gated by the shared, switch-aware
# @admin_required from core.access (ISS-021). It honors the two-tier model and
# deliberately bounces an authenticated non-admin back into the app rather than
# to Django's /admin/ login (which staff_member_required would do).


# ---------------------------------------------------------------------------
# Delivery Settings — agency-wide efficiency + year-end-unused-water policy (55-03)
# ---------------------------------------------------------------------------
#
# Plans 01-02 put two agency-wide knobs on the SiteConfig singleton
# (default_irrigation_efficiency + default_recovery_horizon). This staff-only
# page is their plain-language home: two questions a non-coder analyst answers
# once for the whole agency. Mirrors methodology_settings' @login_required +
# @admin_required gate.


@login_required
@admin_required
def delivery_settings(request):
    """Staff-only agency delivery-policy page (efficiency + year-end policy).

    GET renders the current SiteConfig values through DeliverySettingsForm
    (efficiency shown as a percent, stored as a Decimal fraction). POST validates
    and writes them back onto the one SiteConfig row, then redirects with a
    success message. SiteConfig is a singleton: we get_or_create the single row so
    a fresh install (no SiteConfig yet) still renders rather than 500-ing, and we
    never create a second row.
    """
    from core.forms import DeliverySettingsForm

    config, _ = SiteConfig.objects.get_or_create(
        defaults={"agency_name": "OpenH2O"}
    )

    if request.method == "POST":
        form = DeliverySettingsForm(request.POST, instance=config)
        if form.is_valid():
            with change_note(form.cleaned_data.get("note")):
                form.save()
            messages.success(request, "Delivery settings saved.")
            return redirect("accounting:delivery_settings")
    else:
        form = DeliverySettingsForm(instance=config)

    # The eyebrows count what is rendered, not what the form class declares:
    # the surface cards are gone when that module is (see
    # DeliverySettingsForm). A hardcoded "of 2" is the 88-03 defect.
    #
    # 146-03 Task 3 adds a third possible card ("Diversion records", the same
    # `surface` gate) after "efficiency" and "recovery horizon" -- each
    # card's own position is computed here, in DISPLAY order, rather than
    # assumed in the template (recovery horizon is no longer always last).
    position = 0
    if form.shows_efficiency:
        position += 1
    efficiency_number = position or None
    # 148-04: the over-delivery card follows the efficiency card, behind the
    # `surface` gate (only canal water can be over-delivered).
    over_delivery_number = None
    if form.shows_surface_settings:
        position += 1
        over_delivery_number = position
    position += 1
    recovery_number = position
    diversion_number = None
    if form.shows_diversion_settings:
        position += 1
        diversion_number = position
    # 146-06 Task 1: record addresses belong to `core`, so this card is always
    # shown and always last.
    position += 1
    identifier_number = position
    settings_total = position

    return render(
        request,
        "accounting/delivery_settings.html",
        {
            "form": form,
            "settings_total": settings_total,
            "efficiency_number": efficiency_number,
            "over_delivery_number": over_delivery_number,
            "recovery_number": recovery_number,
            "diversion_number": diversion_number,
            "identifier_number": identifier_number,
        },
    )


# ---------------------------------------------------------------------------
# Methodology Settings — the self-serve face of the calculation engine (38-07)
# ---------------------------------------------------------------------------
#
# Staff tune the config-as-data methodology (reorder / enable-disable steps, edit
# each step's knobs) and preview the effect on a sample parcel before it touches
# a real billing run. Every view here is gated with BOTH @login_required and
# @admin_required.


def _latest_calculated_period():
    """The most recent period that actually has a calculation run, as 'YYYY-MM'.

    Used to seed the preview picker so a staff user lands on a period with data
    rather than an empty one. Returns '' when the engine has never run.
    """
    run = CalculationRun.objects.order_by("-period").first()
    return run.period if run else ""


@login_required
@admin_required
def methodology_settings(request):
    """The staff-only methodology settings page (GET).

    Renders the active plan's ordered steps plus the parcel/period picker for the
    live preview. With no active plan we show a friendly empty state rather than
    letting evaluate_chain's ValueError become a 500.
    """
    plan = CalculationPlan.active()
    steps = list(plan.steps.order_by("order")) if plan is not None else []

    context = {
        "plan": plan,
        "steps": steps,
        "parcels": Parcel.objects.order_by("parcel_number")[:200],
        "default_period": _latest_calculated_period(),
        # R-046: the effective-precip method select renders from the SAME
        # labels the audit page's Detail cell uses, so the two pages can never
        # name a method differently.
        "method_labels": METHOD_LABELS.items(),
    }
    return render(request, "accounting/methodology_settings.html", context)


def _to_float(raw, default):
    """Coerce a posted form value to float, falling back to `default` on blank
    or garbage. The step primitives read these via Decimal(str(...)), so a clean
    float survives the round-trip without binary-noise surprises at these scales."""
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _render_steps(request, plan):
    """Render the steps-editor partial for an HTMX swap of #methodology-steps."""
    steps = list(plan.steps.order_by("order")) if plan is not None else []
    return render(
        request,
        "accounting/partials/_methodology_steps.html",
        {
            "plan": plan,
            "steps": steps,
            "method_labels": METHOD_LABELS.items(),
        },
    )


@login_required
@admin_required
@require_POST
def methodology_step_toggle(request, step_id):
    """Flip one step's enabled flag, then re-render the steps list.

    Any toggle is allowed: the evaluator fails loud on a half-built chain and the
    preview surfaces the effect, so disabling et_gross (yielding 0) is a
    legitimate, visible outcome rather than something to guard against here.
    """
    step = get_object_or_404(CalculationStep, pk=step_id)
    step.enabled = not step.enabled
    with change_note(request.POST.get("note")):
        step.save(update_fields=["enabled"])
    return _render_steps(request, step.plan)


@login_required
@admin_required
@require_POST
def methodology_step_move(request, step_id, direction):
    """Move a step up or down one slot, then re-render the steps list.

    unique_together(plan, order) forbids two rows sharing an order even mid-swap
    (Postgres checks the unique constraint per statement, not at commit), so we
    never swap two values in place. Instead we compute the desired sequence in
    Python and renumber the list 1..N in a transaction, first lifting every row
    that moves out of the 1..N namespace (+10000) so the final write can never
    collide.
    """
    step = get_object_or_404(CalculationStep, pk=step_id)
    plan = step.plan
    ordered = list(plan.steps.order_by("order"))
    idx = next(i for i, s in enumerate(ordered) if s.pk == step.pk)

    if direction == "up" and idx > 0:
        ordered[idx - 1], ordered[idx] = ordered[idx], ordered[idx - 1]
    elif direction == "down" and idx < len(ordered) - 1:
        ordered[idx + 1], ordered[idx] = ordered[idx], ordered[idx + 1]
    # No-op cleanly at the ends (first can't move up, last can't move down).

    # Only the steps whose place actually changes are written (147-01): every
    # write is recorded in the change history, and a step that stays put has
    # no change to record.
    moving = [s for i, s in enumerate(ordered, start=1) if s.order != i]
    with change_note(request.POST.get("note")), transaction.atomic():
        for s in moving:
            s.order = s.order + 10000
            s.save(update_fields=["order"])
        for i, s in enumerate(ordered, start=1):
            if s.order != i:
                s.order = i
                s.save(update_fields=["order"])

    return _render_steps(request, plan)


@login_required
@admin_required
@require_POST
def methodology_step_config(request, step_id):
    """Edit one step's config knobs (+ its audit label), then re-render the list.

    The cardinal rule (38-02 silent-zero trap): MERGE the posted keys into the
    existing config dict, never replace it — so et_gross's model/variable plumbing
    survives a save on a different step. Only the knobs relevant to the step_type
    are touched; the rest of the dict is left exactly as it was.
    """
    step = get_object_or_404(CalculationStep, pk=step_id)
    config = dict(step.config or {})  # MERGE base — preserve every existing key.

    if step.step_type == "subtract_effective_precip":
        method = request.POST.get("method", config.get("method", "usda_scs"))
        if method in ("raw", "fraction", "usda_scs"):
            config["method"] = method
        config["fraction"] = _to_float(
            request.POST.get("fraction"), config.get("fraction", 0.70)
        )
        config["soil_storage_in"] = _to_float(
            request.POST.get("soil_storage_in"), config.get("soil_storage_in", 3.0)
        )
    elif step.step_type == "clamp_floor":
        # 148-02: the rain bank is retired -- floor is the step's only knob.
        config["floor"] = _to_float(request.POST.get("floor"), config.get("floor", 0))
    # et_gross / subtract_surface_water / facility_only_zero: no editable knobs;
    # their config is left untouched (et_gross keeps its model/variable plumbing).

    step.config = config
    label = request.POST.get("label", "").strip()
    if label:
        step.label = label
    with change_note(request.POST.get("note")):
        step.save(update_fields=["config", "label"])
    return _render_steps(request, step.plan)


@login_required
@admin_required
def methodology_preview(request):
    """Live preview of the CURRENTLY-SAVED methodology on one sample parcel.

    Calls evaluate_chain, which is side-effect-FREE by the 38-04 design contract:
    it reads the active DB plan and writes NOTHING — no ledger row, no
    WaterCredit, no CalculationRun (run_calculations is the only writer). So the
    self-serve loop is: edit a knob → Save → Preview, and the preview reflects the
    saved chain. Degrades to a friendly message (never a 500) on a missing parcel,
    a blank/malformed period, or a no-active-plan state.
    """
    parcel_id = (request.POST.get("parcel_id") or request.GET.get("parcel_id") or "").strip()
    period = (request.POST.get("period") or request.GET.get("period") or "").strip()

    context = {
        "parcel": None,
        "period": period,
        "steps": [],
        "final_af": None,
        "error": None,
    }

    parcel = None
    if parcel_id:
        try:
            parcel = Parcel.objects.filter(pk=parcel_id).first()
        except (ValueError, TypeError):
            parcel = None
    if parcel is None:
        context["error"] = "Pick a parcel to preview."
        return render(request, "accounting/partials/_methodology_preview.html", context)
    context["parcel"] = parcel

    if not period:
        context["error"] = "Enter a period (YYYY-MM) to preview."
        return render(request, "accounting/partials/_methodology_preview.html", context)

    try:
        final_af, breakdown = evaluate_chain(parcel, period)
    except ValueError as exc:
        # No active plan, malformed period ("2024" / "abc-de"), etc. — surface it.
        context["error"] = f"Cannot preview: {exc}"
        return render(request, "accounting/partials/_methodology_preview.html", context)

    context["final_af"] = final_af
    delivery_split = _delivery_split_kind(parcel, period)
    context["steps"] = [
        {
            "label": s.get("label") or s.get("step_type"),
            "input_af": s.get("input_af"),
            "output_af": s.get("output_af"),
            "detail_text": _step_detail_summary(s, delivery_split=delivery_split),
        }
        for s in breakdown
    ]
    return render(request, "accounting/partials/_methodology_preview.html", context)
