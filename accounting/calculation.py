# SPDX-License-Identifier: AGPL-3.0-or-later
"""The calculation-engine evaluator.

evaluate_chain walks the active CalculationPlan's enabled steps in order,
threading a positive extraction magnitude (acre-feet) and a shared ctx dict
through each primitive, and returns the final magnitude plus a per-step
breakdown suitable for persisting (38-04) or display.
"""

from decimal import Decimal

from accounting.models import CalculationPlan
from accounting.steps import STEP_REGISTRY


def evaluate_chain(parcel, period):
    """Run the active plan's enabled steps for one parcel-month.

    Args:
        parcel: a parcels.models.Parcel instance.
        period: a "YYYY-MM" string.

    Returns:
        (final_af, breakdown) where final_af is a Decimal POSITIVE magnitude
        (acre-feet) and breakdown is a list of step_record dicts.

    Raises:
        ValueError: if there is no active CalculationPlan, or if an enabled step
            names a step_type that is not registered (a half-built chain must
            fail loudly rather than silently skip math).
    """
    plan = CalculationPlan.active()
    if plan is None:
        raise ValueError("no active CalculationPlan — run seed_calculation_plan")

    running_af = Decimal("0")
    ctx = {}
    breakdown = []

    for step in plan.steps.filter(enabled=True).order_by("order"):
        fn = STEP_REGISTRY.get(step.step_type)
        if fn is None:
            raise ValueError(
                f"enabled step '{step.step_type}' (order {step.order}) is not "
                f"registered in STEP_REGISTRY — cannot evaluate the chain"
            )
        running_af, record = fn(running_af, parcel, period, ctx, step.config or {})
        # The configured label and step_type are authoritative for the audit trail.
        record["step_type"] = step.step_type
        record["label"] = step.label
        breakdown.append(record)

    return running_af, breakdown
