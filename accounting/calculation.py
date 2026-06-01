# SPDX-License-Identifier: AGPL-3.0-or-later
"""The calculation-engine evaluator.

evaluate_chain walks the active CalculationPlan's enabled steps in order,
threading a positive extraction magnitude (acre-feet) and a shared ctx dict
through each primitive, and returns the final magnitude plus a per-step
breakdown suitable for persisting (38-04) or display.

plan_config_hash distills that same plan into a short, stable methodology
fingerprint stamped onto every CalculationRun (42-01), so a filed number can
name the recipe that made it even after the live plan is later edited. It is a
methodology fingerprint, NOT a security hash.
"""

import hashlib
import json
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


def plan_config_hash(plan):
    """Return a 12-hex methodology fingerprint for a CalculationPlan.

    Hashes ONLY the enabled steps in `order` — each step's order, step_type, and
    config — because those are exactly the things that shape the number. Disabled
    steps never run, and `label` is cosmetic: renaming a step or toggling one that
    wasn't contributing must NOT change the fingerprint of an unchanged
    calculation. The config dict is serialized with sorted keys so a re-run with
    the same plan reproduces the same hash regardless of dict ordering.

    This is a methodology fingerprint for provenance, not a security hash — the
    12-hex prefix is plenty to distinguish methodology versions and stays readable
    on the audit page.
    """
    canonical = [
        {"order": s.order, "step_type": s.step_type, "config": s.config}
        for s in plan.steps.filter(enabled=True).order_by("order")
    ]
    serialized = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(serialized.encode()).hexdigest()[:12]
