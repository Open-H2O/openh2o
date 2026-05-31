"""
Publish-gate audit for the conformance registry.

This is the publish-gate the v1.3 milestone calls for, expressed as a
pre-publish audit (no live publish path exists until Phase 32 to wire it into).
It reports:
  - ObservedProperty rows that are not fully publishable (missing pcode and/or
    UCUM), split into BLOCKING (missing UCUM) and PENDING (missing pcode only);
  - SourceParameter rows missing an observed_property (a crosswalk gap);
  - a count of measurements still carrying a null observed_property FK.

Gating rule (decision 31-01): gate on UCUM for ALL properties — every publish
path needs a unit contract — but treat a blank USGS pcode as a known,
non-blocking exception, because several real concepts (reservoir storage,
reservoir flows, ET, weather) legitimately have no USGS parameter code. The
command exits non-zero only when a real publishable-blocking gap exists, so it
can gate CI or a future publish step.
"""

from django.core.management.base import BaseCommand

from measurements.models import MeterReading, SensorMeasurement, WaterMeasurement
from standards.models import ObservedProperty, SourceParameter


class Command(BaseCommand):
    help = "Audit the conformance registry; exit non-zero on publishable-blocking gaps."

    def handle(self, *args, **options):
        blocking = []   # missing UCUM — a real publish blocker
        pending = []    # missing pcode only — known, non-blocking exception

        for op in ObservedProperty.objects.all():
            if not op.ucum_unit:
                blocking.append(op)
            elif not op.usgs_pcode:
                pending.append(op)

        # SourceParameter.observed_property is a required FK, so this is a
        # belt-and-suspenders check that surfaces any orphaned crosswalk row.
        orphan_crosswalks = list(
            SourceParameter.objects.filter(observed_property__isnull=True)
        )

        null_fk_measurements = (
            SensorMeasurement.objects.filter(observed_property__isnull=True).count()
            + MeterReading.objects.filter(observed_property__isnull=True).count()
            + WaterMeasurement.objects.filter(observed_property__isnull=True).count()
        )

        # ── Report ──────────────────────────────────────────────────────────
        if pending:
            self.stdout.write("Pending a USGS pcode (non-blocking):")
            for op in pending:
                self.stdout.write(f"  - {op.key} ({op.name})")

        if null_fk_measurements:
            self.stdout.write(
                f"Measurements with a null observed_property FK: {null_fk_measurements}"
            )

        if blocking:
            self.stderr.write(
                self.style.ERROR("BLOCKING — ObservedProperty missing a UCUM unit:")
            )
            for op in blocking:
                self.stderr.write(f"  - {op.key} ({op.name})")
        if orphan_crosswalks:
            self.stderr.write(
                self.style.ERROR("BLOCKING — SourceParameter with no observed_property:")
            )
            for sp in orphan_crosswalks:
                self.stderr.write(f"  - {sp.source_code}:{sp.parameter_code}")

        if blocking or orphan_crosswalks:
            self.stderr.write(
                self.style.ERROR(
                    f"Conformance gate FAILED: {len(blocking)} property(ies) "
                    f"missing UCUM, {len(orphan_crosswalks)} orphan crosswalk(s)."
                )
            )
            # Non-zero exit so this can gate CI / a future publish step.
            raise SystemExit(1)

        self.stdout.write(
            self.style.SUCCESS(
                f"Conformance gate PASSED: "
                f"{ObservedProperty.objects.count()} properties "
                f"({len(pending)} pending a pcode), "
                f"{SourceParameter.objects.count()} crosswalk rows, all UCUM-complete."
            )
        )
