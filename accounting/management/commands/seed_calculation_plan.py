# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed the default CalculationPlan and its step chain.

Idempotent (mirrors seed_observed_properties): get_or_create one active plan,
then update_or_create its 4 steps keyed on (plan, order). Running twice leaves
exactly one plan and exactly four steps.

The default chain nets effective precipitation out of gross ET: the
subtract_effective_precip step is ENABLED with the USDA-SCS / TR-21 method
(soil_storage_in=3.0); its math is tested against published vectors.

et_gross config uses variable="ET" / model="Ensemble" to match the strings the
GEE adapter actually writes into OpenETCache (verified live in a deployment).

subtract_surface_water always multiplies a canal delivery by the field's
irrigation efficiency; its config carries no switch for it, and a plan that
still holds the old ``apply_efficiency`` key behaves the same with it on or off.

The chain has four steps. A plan saved with the older no-crop step has that
step taken out when this command runs again (the step no longer zeroes
anything in any case).
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from accounting.models import CalculationPlan, CalculationStep

PLAN_NAME = "Default Methodology"

DEFAULT_STEPS = [
    {
        "order": 1,
        "step_type": "et_gross",
        "enabled": True,
        "config": {"model": "Ensemble", "variable": "ET"},
        "label": "Gross ET (OpenET ensemble)",
    },
    {
        "order": 2,
        "step_type": "subtract_effective_precip",
        "enabled": True,
        "config": {"method": "usda_scs", "soil_storage_in": 3.0},
        "label": "Subtract effective precipitation (USDA-SCS)",
    },
    {
        "order": 3,
        "step_type": "subtract_surface_water",
        "enabled": True,
        # Only the part of a canal delivery the field's own efficiency says
        # the crop could use is subtracted; the rest is deep percolation,
        # named on the parcel's balance, never crop use and never a credit.
        "config": {},
        "label": "Subtract delivery × irrigation efficiency",
    },
    {
        "order": 4,
        "step_type": "clamp_floor",
        "enabled": True,
        # The floor is the step's only knob (there is no bank, depreciation
        # rate or expiry).
        "config": {
            "floor": 0,
        },
        "label": "Clamp at floor",
    },
]


class Command(BaseCommand):
    help = "Seed the default CalculationPlan with its 4-step chain (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        plan, plan_created = CalculationPlan.objects.get_or_create(
            name=PLAN_NAME,
            defaults={"is_active": True},
        )

        # The retired no-crop step: out of any plan that still holds it, and
        # the final step takes the freed place so no order is skipped.
        plan.steps.filter(step_type="facility_only_zero").delete()
        plan.steps.filter(step_type="clamp_floor", order=5).update(order=4)

        created = 0
        updated = 0
        for spec in DEFAULT_STEPS:
            _, was_created = CalculationStep.objects.update_or_create(
                plan=plan,
                order=spec["order"],
                defaults={
                    "step_type": spec["step_type"],
                    "enabled": spec["enabled"],
                    "config": spec["config"],
                    "label": spec["label"],
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        plan_verb = "created" if plan_created else "exists"
        self.stdout.write(
            self.style.SUCCESS(
                f"Plan '{PLAN_NAME}' {plan_verb}; steps: {created} created, "
                f"{updated} updated ({plan.steps.count()} total)."
            )
        )
