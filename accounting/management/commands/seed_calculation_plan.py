# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed the default CalculationPlan and its step chain.

Idempotent (mirrors seed_observed_properties): get_or_create one active plan,
then update_or_create its 5 steps keyed on (plan, order). Running twice leaves
exactly one plan and exactly five steps.

The default chain nets effective precipitation out of gross ET: as of 38-03 the
subtract_effective_precip step is ENABLED with the USDA-SCS / TR-21 method
(soil_storage_in=3.0), now that its math is TDD-proven against published vectors.

et_gross config uses variable="ET" / model="Ensemble" to match the strings the
GEE adapter actually writes into OpenETCache (verified live in a deployment).
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
        "config": {},
        "label": "Subtract surface water delivered",
    },
    {
        "order": 4,
        "step_type": "facility_only_zero",
        "enabled": True,
        "config": {},
        "label": "Zero out facility-only parcels",
    },
    {
        "order": 5,
        "step_type": "clamp_floor",
        "enabled": True,
        # depreciation_rate 0 = banked surplus never decays; expiry_months None =
        # never expires. Both are agency-tunable from the 38-06 settings screen.
        "config": {
            "floor": 0,
            "bank": True,
            "depreciation_rate": 0,
            "expiry_months": None,
        },
        "label": "Clamp at floor",
    },
]


class Command(BaseCommand):
    help = "Seed the default CalculationPlan with its 5-step chain (idempotent)."

    @transaction.atomic
    def handle(self, *args, **options):
        plan, plan_created = CalculationPlan.objects.get_or_create(
            name=PLAN_NAME,
            defaults={"is_active": True},
        )

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
