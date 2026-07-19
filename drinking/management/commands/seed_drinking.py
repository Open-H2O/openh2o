# SPDX-License-Identifier: AGPL-3.0-or-later
"""Seed the federal drinking-water analyte vocabulary and its NPDWR limits.

Every value below was transcribed from EPA's published *National Primary
Drinking Water Regulations* table
(https://www.epa.gov/ground-water-and-drinking-water/national-primary-drinking-water-regulations)
on 2026-07-19. Nothing here is written from memory, and nothing is inferred:
where EPA publishes no numeric threshold for an analyte (E. coli, whose rule is
a treatment technique rather than a concentration), the analyte is seeded with
no ``RegulatoryLimit`` rather than a guessed one.

Two things this command deliberately does NOT do:

* **It does not invent DDW analyte codes.** DDW's SDWIS.CSV data dictionary
  describes ``Analyte Code`` as "a unique, four-digit number" but publishes no
  code list, and no other authoritative list is in hand. Every ``ddw_code``
  therefore stays NULL; the CSV importer (78-03) will populate them from the
  codes the state's own files carry.
* **It does not determine compliance.** A ``RegulatoryLimit`` records what the
  limit is and when it applied. Comparing a result against one is a later,
  rule-by-rule job.

**On ``effective_start``:** where EPA's table states the date a standard took
effect (arsenic, uranium), that date is used. For everything else the table
gives no date, so ``2000-01-01`` is used as an explicit ADMINISTRATIVE
PLACEHOLDER — ``RegulatoryLimit``'s versioning semantics only need *a* start so
that "the limit on date D" resolves, and a fabricated per-rule promulgation date
would be a worse lie than an obvious placeholder. Per-rule start dates are
pending research; revising them is a data edit, not a schema change.
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from drinking.models import Analyte, RegulatoryLimit

#: See the module docstring. Not a real promulgation date for any rule.
PLACEHOLDER_START = date(2000, 1, 1)

FEDERAL = "federal"

# (analyte name, storet_code, limit_type, value, unit, effective_start)
# `limit_type=None` seeds the analyte with no limit row.
#
# Verbatim source text is quoted in the trailing comment wherever EPA's cell
# carries more than a bare number.
SEED = [
    # -- Microorganisms ------------------------------------------------------
    # "Total Coliforms (including fecal coliform and E. Coli) | zero | 5.0%"
    # The MCL is a percentage of monthly samples positive, not a concentration.
    ("Total Coliforms", "", "mcl", "5.0", "% positive samples", PLACEHOLDER_START),
    # E. coli is regulated within the same rule with no numeric MCL of its own,
    # so it gets an analyte row (presence/absence results need one) and no limit.
    ("E. coli", "", None, None, "", None),

    # -- Inorganic chemicals -------------------------------------------------
    ("Nitrate (as N)", "", "mcl", "10", "mg/L", PLACEHOLDER_START),
    ("Nitrite (as N)", "", "mcl", "1", "mg/L", PLACEHOLDER_START),
    # "0.010 as of 01/23/06"
    ("Arsenic", "", "mcl", "0.010", "mg/L", date(2006, 1, 23)),
    ("Antimony", "", "mcl", "0.006", "mg/L", PLACEHOLDER_START),
    ("Barium", "", "mcl", "2", "mg/L", PLACEHOLDER_START),
    ("Cadmium", "", "mcl", "0.005", "mg/L", PLACEHOLDER_START),
    ("Chromium (total)", "", "mcl", "0.1", "mg/L", PLACEHOLDER_START),
    ("Cyanide (as free cyanide)", "", "mcl", "0.2", "mg/L", PLACEHOLDER_START),
    ("Fluoride", "", "mcl", "4.0", "mg/L", PLACEHOLDER_START),
    ("Mercury (inorganic)", "", "mcl", "0.002", "mg/L", PLACEHOLDER_START),
    ("Selenium", "", "mcl", "0.05", "mg/L", PLACEHOLDER_START),
    # "Lead | zero | TT; Action Level=0.010" — a treatment technique with an
    # action level, NOT an MCL. Same for copper.
    ("Lead", "", "action_level", "0.010", "mg/L", PLACEHOLDER_START),
    # "Copper | 1.3 | TT; Action Level=1.3"
    ("Copper", "", "action_level", "1.3", "mg/L", PLACEHOLDER_START),

    # -- Disinfection byproducts and disinfectants ---------------------------
    # TTHM and HAA5 are enforced as a running annual average.
    ("Total Trihalomethanes (TTHM)", "", "mcl", "0.080", "mg/L", PLACEHOLDER_START),
    ("Haloacetic Acids (HAA5)", "", "mcl", "0.060", "mg/L", PLACEHOLDER_START),
    ("Bromate", "", "mcl", "0.010", "mg/L", PLACEHOLDER_START),
    ("Chlorite", "", "mcl", "1.0", "mg/L", PLACEHOLDER_START),
    ("Chlorine", "", "mrdl", "4.0", "mg/L", PLACEHOLDER_START),
    ("Chloramines", "", "mrdl", "4.0", "mg/L", PLACEHOLDER_START),
    ("Chlorine Dioxide", "", "mrdl", "0.8", "mg/L", PLACEHOLDER_START),

    # -- Organic chemicals ---------------------------------------------------
    ("Benzene", "", "mcl", "0.005", "mg/L", PLACEHOLDER_START),
    ("Trichloroethylene", "", "mcl", "0.005", "mg/L", PLACEHOLDER_START),
    ("Tetrachloroethylene", "", "mcl", "0.005", "mg/L", PLACEHOLDER_START),
    ("Carbon Tetrachloride", "", "mcl", "0.005", "mg/L", PLACEHOLDER_START),
    ("1,2-Dichloroethane", "", "mcl", "0.005", "mg/L", PLACEHOLDER_START),
    ("Vinyl Chloride", "", "mcl", "0.002", "mg/L", PLACEHOLDER_START),
    ("Atrazine", "", "mcl", "0.003", "mg/L", PLACEHOLDER_START),

    # -- Radionuclides -------------------------------------------------------
    # "30 ug/L as of 12/08/03"
    ("Uranium", "", "mcl", "30", "ug/L", date(2003, 12, 8)),
    ("Gross Alpha Particle Activity", "", "mcl", "15", "pCi/L", PLACEHOLDER_START),
    ("Combined Radium 226/228", "", "mcl", "5", "pCi/L", PLACEHOLDER_START),
    # "4 millirems per year"
    ("Beta Particle and Photon Activity", "", "mcl", "4", "mrem/yr", PLACEHOLDER_START),
]


class Command(BaseCommand):
    help = "Seed federal NPDWR analytes and regulatory limits (EPA-verified)."

    @transaction.atomic
    def handle(self, *args, **options):
        analytes_created = 0
        limits_created = 0
        limits_updated = 0

        for name, storet, limit_type, value, unit, start in SEED:
            analyte, made = Analyte.objects.get_or_create(
                name=name, defaults={"storet_code": storet}
            )
            analytes_created += int(made)

            if limit_type is None:
                continue

            _, made = RegulatoryLimit.objects.update_or_create(
                analyte=analyte,
                limit_type=limit_type,
                jurisdiction=FEDERAL,
                effective_start=start,
                defaults={
                    "value": Decimal(value),
                    "unit": unit,
                    "effective_end": None,
                },
            )
            limits_created += int(made)
            limits_updated += int(not made)

        self.stdout.write(
            f"Analytes: {analytes_created} created, "
            f"{Analyte.objects.count()} total."
        )
        self.stdout.write(
            f"Regulatory limits: {limits_created} created, "
            f"{limits_updated} updated, {RegulatoryLimit.objects.count()} total."
        )
        self.stdout.write(
            self.style.SUCCESS("Federal drinking water reference data loaded.")
        )
