# 146-05 Task 1 (S1): seed surface.IrrigationMethod with East Turlock Subbasin
# GSA's published irrigation-efficiency table.
#
# Source: East Turlock Subbasin GSA, Rules and Regulations Phase 2 Final,
# 2025-08-28, Section 4.05 "Consumed Surface Water Credit", the table on
# printed pages 20-21, which cites "Zaccaria, Danielle, 2018. ANR Publication
# 8570, Field Irrigation Water Management in a Nutshell. September."
#
# 18 rows, counted off the PDF on 2026-09-23 (146-05-EVIDENCE.md): the table
# has 18 method rows under three group headings (Sprinkler 7, Surface 5, Micro
# Irrigation 6) that carry no numbers and are not stored. Names are as the PDF
# prints them; the order is the PDF's, spaced by 10. Every range and assigned
# figure matched the research transcription; the transcription's one name
# difference ("LEPA (sprinkler)") is the PDF's "LEPA" here.
#
# A data migration rather than a seed command, so every deployment (staging,
# the golden rebuild, a fresh install) carries the same rows after `migrate`.
# The rows are reference data, like water types; verify_clean_install does not
# count them.

from decimal import Decimal

from django.db import migrations

SOURCE = (
    "East Turlock Subbasin GSA, Rules and Regulations Phase 2 Final "
    "(2025-08-28), §4.05, citing Zaccaria 2018, ANR 8570"
)

# (name as printed, range low %, range high %, assigned %)
EAST_TURLOCK_4_05 = [
    ("LEPA", 80, 90, 88),
    ("Linear Move", 75, 85, 83),
    ("Center Pivot", 75, 90, 87),
    ("Traveling Gun", 65, 75, 73),
    ("Side-Roll", 65, 85, 80),
    ("Hand-Move", 65, 85, 80),
    ("Solid-Set", 70, 85, 82),
    ("Furrow (Conventional)", 45, 65, 60),
    ("Furrow (Surge)", 55, 75, 70),
    ("Furrow (with Tailwater Reuse)", 60, 80, 75),
    ("Basin", 60, 75, 72),
    ("Precision Level Basin", 65, 80, 77),
    ("Bubbler (Low Head)", 80, 90, 88),
    ("Microspray", 85, 90, 90),
    ("Micropoint Source", 85, 90, 90),
    ("Microline Source", 85, 90, 90),
    ("Surface Drip", 85, 95, 93),
    ("Subsurface Drip", 90, 95, 95),
]


def _fraction(percent):
    return (Decimal(percent) / 100).quantize(Decimal("0.001"))


def seed(apps, schema_editor):
    """Write the 18 rows, keyed by name so a re-run changes nothing."""
    IrrigationMethod = apps.get_model("surface", "IrrigationMethod")
    for position, (name, low, high, assigned) in enumerate(EAST_TURLOCK_4_05, start=1):
        IrrigationMethod.objects.update_or_create(
            name=name,
            defaults={
                "assigned_efficiency": _fraction(assigned),
                "range_low": _fraction(low),
                "range_high": _fraction(high),
                "source": SOURCE,
                "sort_order": position * 10,
            },
        )


def unseed(apps, schema_editor):
    """Remove the 18 rows. A use area still pointing at one blocks this
    (on_delete=PROTECT), which is the right answer: clear the method first."""
    IrrigationMethod = apps.get_model("surface", "IrrigationMethod")
    IrrigationMethod.objects.filter(
        name__in=[row[0] for row in EAST_TURLOCK_4_05]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("surface", "0015_irrigation_method"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
