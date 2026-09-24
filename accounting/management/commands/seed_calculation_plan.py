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

148-02, S1: subtract_surface_water's apply_efficiency knob defaults to True in
THIS seed. It is the deployment's own choice, made on the methodology page
(accounting.views.methodology_step_config), and it is NOT retroactively turned
on for an existing deployment's plan -- this command only runs at first seed,
and there is deliberately no data migration flipping the knob on a plan that
already exists. A deployment that seeded before 148-02 keeps its old plan's
config (missing the key, which behaves exactly as False) until an operator
turns it on themselves.
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
        # apply_efficiency (148-02, S1): the deployment's own choice, set here
        # for a first seed only -- see the module docstring above. On: only
        # the part of a canal delivery the field's own efficiency says the
        # crop could use is subtracted; the rest is deep percolation, named
        # on the parcel's balance, never crop use and never a credit.
        "config": {"apply_efficiency": True},
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
        # 148-02: the rain bank is retired -- bank / depreciation_rate /
        # expiry_months are gone, so the floor is the step's only knob.
        "config": {
            "floor": 0,
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
