# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fill the Merced demo's descriptive detail fields with plausible mock data.

The spatial + accounting layers of the Merced demo are real/derived, but the
*descriptive* fields a reviewer sees when they open a detail page were left blank
by the structural seeds: well construction (the DWR Well Completion Report
section), parcel addresses, CalWATRS PINs, account contacts, and the meters
behind "Certified Meter" wells. An empty Construction section or a "No active
meters" line under a metered well reads as an unfinished product, not a
demonstration. This command stamps those gaps so every detail page tells a
complete story.

DESIGN — reproducible, non-destructive, accounting-safe:
  * Deterministic: every value is drawn from a per-record ``random.Random`` seeded
    by the record's stable key (registration id / parcel number / right id), so a
    rebuild reproduces the exact same demo. No wall-clock, no global RNG.
  * Fill-only-when-blank: a field that already carries a value is never
    overwritten, so an operator's real entry survives and re-runs are idempotent.
  * Display-only meters: the ``Meter``/``WellMeter`` rows this mints are purely
    presentational. The accounting engine reads metered volumes from ledger
    ``meter_reading`` rows, NOT from ``Meter`` objects, so creating them does not
    touch the Phase 58-03 metered-disposition calibration. Meters are keyed on a
    deterministic serial, so update_or_create never duplicates them.

Runs LAST in the seed_merced sequence: it enriches records the structural seeds
already created, and ``seed_merced_ledgers`` rebuilds accounts (rotating their
PKs), so account contacts must be filled after that.
"""
import datetime
import random

from django.core.management.base import BaseCommand
from django.db import transaction

CASING_MATERIALS = ["Steel", "PVC", "Stainless Steel", "Low-Carbon Steel"]
# Turbine pumps dominate deep San Joaquin Valley ag wells; weight accordingly.
PUMP_TYPES = ["turbine", "turbine", "turbine", "submersible", "centrifugal"]
METER_MAKES = [
    ("McCrometer", "Mc Propeller FS100"),
    ("Seametrics", "WMP-Series"),
    ("Netafim", "Octave Ultrasonic"),
    ("Badger Meter", "M-Series M2000"),
]
# DWR State Well Number components for the Merced subbasin (T6S-T9S, R12E-R16E).
SWN_TOWNSHIPS = [6, 7, 8, 9]
SWN_RANGES = [12, 13, 14, 15, 16]
SWN_TRACTS = "ABCDEFGHJKLMNPQR"
COUNTY_ROADS = [
    "Sandy Mush", "Le Grand", "Childs", "Bert Crane", "Vincent", "Gurr",
    "Plainsburg", "Ashby", "Robin", "Almond", "Westside", "River", "Santa Fe",
    "Shaffer", "Bradbury", "Arboleda",
]
COUNTY_TOWNS = [
    ("Merced", "95340"), ("Atwater", "95301"), ("Le Grand", "95333"),
    ("Planada", "95365"), ("El Nido", "95317"), ("Snelling", "95369"),
    ("Ballico", "95303"), ("Hilmar", "95324"), ("Cressey", "95312"),
    ("Winton", "95388"),
]


class Command(BaseCommand):
    help = "Fill the Merced demo's descriptive detail fields with mock data."

    @transaction.atomic
    def handle(self, *args, **options):
        wells = self._fill_wells()
        meters = self._mint_meters()
        parcels = self._fill_parcel_addresses()
        rights = self._fill_water_right_pins()
        accounts = self._fill_account_contacts()
        self.stdout.write(self.style.SUCCESS(
            f"Merced detail fields filled: {wells} well(s) enriched, "
            f"{meters} meter(s) minted, {parcels} parcel address(es), "
            f"{rights} CalWATRS PIN(s), {accounts} account contact(s)."))

    # --- Wells: the DWR Well Completion Report section -------------------------
    def _fill_wells(self):
        from wells.models import Well, WellIrrigatedParcel

        count = 0
        for w in Well.objects.all():
            rng = random.Random(f"well:{w.well_registration_id}")
            changed = []

            if not w.owner_name:
                link = (WellIrrigatedParcel.objects
                        .filter(well=w).select_related("parcel").first())
                if link and link.parcel.owner_name:
                    w.owner_name = link.parcel.owner_name
                    changed.append("owner_name")

            if w.depth_ft in (None, ""):
                w.depth_ft = rng.randrange(280, 760, 10)
                changed.append("depth_ft")
            depth = float(w.depth_ft or 400)

            if w.capacity_gpm in (None, ""):
                w.capacity_gpm = rng.randrange(600, 2600, 50)
                changed.append("capacity_gpm")
            if w.tested_yield_gpm in (None, ""):
                base = float(w.capacity_gpm or 1200)
                w.tested_yield_gpm = round(base * rng.uniform(0.85, 1.05))
                changed.append("tested_yield_gpm")

            if w.casing_diameter_in in (None, ""):
                w.casing_diameter_in = rng.choice([10, 12, 14, 16])
                changed.append("casing_diameter_in")
            if not w.casing_material:
                w.casing_material = rng.choice(CASING_MATERIALS)
                changed.append("casing_material")

            # Screen interval sits within the lower bore.
            if w.screen_top_ft in (None, ""):
                w.screen_top_ft = round(depth * rng.uniform(0.40, 0.55))
                changed.append("screen_top_ft")
            if w.screen_bottom_ft in (None, ""):
                w.screen_bottom_ft = round(depth * rng.uniform(0.85, 0.95))
                changed.append("screen_bottom_ft")

            if not w.pump_type:
                w.pump_type = rng.choice(PUMP_TYPES)
                changed.append("pump_type")
            if w.year_pumping_began in (None, ""):
                w.year_pumping_began = rng.randint(1978, 2016)
                changed.append("year_pumping_began")

            if not w.wcr_number:
                w.wcr_number = f"E{rng.randint(100000, 999999):06d}"
                changed.append("wcr_number")
            if not w.state_well_number:
                w.state_well_number = (
                    f"{rng.choice(SWN_TOWNSHIPS):02d}S"
                    f"{rng.choice(SWN_RANGES):03d}E"
                    f"{rng.randint(1, 36):02d}"
                    f"{rng.choice(SWN_TRACTS)}{rng.randint(1, 4):03d}M")
                changed.append("state_well_number")
            # USGS IDs only exist for the minority of wells in a federal network.
            if not w.usgs_site_id and rng.random() < 0.25:
                w.usgs_site_id = (
                    f"{rng.randint(370000, 372500):06d}"
                    f"{rng.randint(1200000, 1210000):07d}01")
                changed.append("usgs_site_id")

            if changed:
                w.save(update_fields=changed)
                count += 1
        return count

    # --- Tier 2: a real meter behind every "Certified Meter" well --------------
    def _mint_meters(self):
        from measurements.models import Meter
        from wells.models import Well, WellMeter

        count = 0
        for w in Well.objects.filter(measurement_method="certified_meter"):
            rng = random.Random(f"meter:{w.well_registration_id}")
            make, model = rng.choice(METER_MAKES)
            cal = datetime.date(2024, rng.randint(1, 12), rng.randint(1, 28))
            meter, _ = Meter.objects.update_or_create(
                serial_number=f"MTR-{w.well_registration_id}",
                defaults={
                    "meter_type": "totalizer",
                    "unit": "acre_feet",
                    "manufacturer": make,
                    "model": model,
                    "last_calibration_date": cal,
                    "status": "active",
                },
            )
            WellMeter.objects.update_or_create(
                well=w, meter=meter,
                defaults={
                    "installed_date": datetime.date(
                        w.year_pumping_began or 2005, 6, 1),
                    "calibration_date": cal,
                    "is_current": True,
                },
            )
            count += 1
        return count

    # --- Parcel mailing addresses (Merced County) -----------------------------
    def _fill_parcel_addresses(self):
        from parcels.models import Parcel

        count = 0
        for p in Parcel.objects.all():
            if p.address:
                continue
            rng = random.Random(f"addr:{p.parcel_number}")
            town, zip_code = rng.choice(COUNTY_TOWNS)
            p.address = (f"{rng.randint(1000, 28000)} "
                         f"{rng.choice(COUNTY_ROADS)} Rd, {town}, CA {zip_code}")
            p.save(update_fields=["address"])
            count += 1
        return count

    # --- CalWATRS PIN per water right -----------------------------------------
    def _fill_water_right_pins(self):
        from surface.models import WaterRight

        count = 0
        for r in WaterRight.objects.all():
            if r.calwatrs_pin:
                continue
            rng = random.Random(f"pin:{r.right_id}")
            r.calwatrs_pin = f"P{rng.randint(100000, 999999)}"
            r.save(update_fields=["calwatrs_pin"])
            count += 1
        return count

    # --- Water account contact emails -----------------------------------------
    def _fill_account_contacts(self):
        import re

        from accounting.models import WaterAccount

        count = 0
        for a in WaterAccount.objects.all():
            if a.contact_email:
                continue
            basis = a.contact_name or a.name
            slug = re.sub(r"[^a-z0-9]+", ".", basis.lower()).strip(".")[:40]
            a.contact_email = f"{slug or 'contact'}@example.com"
            a.save(update_fields=["contact_email"])
            count += 1
        return count
