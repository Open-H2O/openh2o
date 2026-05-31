# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Seed the ObservedProperty registry and the SourceParameter crosswalk.

Idempotent: keyed on ObservedProperty.key and SourceParameter
(source_code, parameter_code), so re-running (and `make fresh`) creates no
duplicates.

Step 1 creates the canonical concept rows from OBSERVED_PROPERTIES below. UCUM
codes are a published lookup (unitsofmeasure.org) — they are hand-authored and
verified here, never guessed at runtime. Where a concept genuinely has no USGS
parameter code (CDEC reservoir sensors, OpenET ET, weather), usgs_pcode is left
blank; it stays publish-incomplete-as-pcode until a real code is assigned, which
is the conformance gate doing its job, not a bug.

Step 2 walks every (source_code, parameter_code) the adapters expose via
registry.get_all_parameter_maps() and builds the crosswalk, carrying the
source's native name + unit. Any source code with no mapped concept is logged
as an explicit gap rather than crashing.
"""

from django.core.management.base import BaseCommand

from datasync.adapters import registry
from standards.models import ObservedProperty, SourceParameter

# ── Step 1: canonical concepts ──────────────────────────────────────────────
# Each concept maps to its USGS parameter code, EPA WQX CharacteristicName, and
# UCUM unit. UCUM atoms used here: [cft_i]/s (cubic foot intl per second),
# [ft_i] (foot intl), Cel (degree Celsius), [acr_us].[ft_i] (acre-foot),
# mm (millimetre), W/m2 (watt per square metre), m/s (metre per second).
# The ucum_unit is the canonical unit of the CONCEPT; the value-as-recorded unit
# travels on SourceParameter.native_unit (augment, don't replace).
OBSERVED_PROPERTIES = [
    # key, name, usgs_pcode, wqx_characteristic_name, ucum_unit
    ("discharge", "Stream Discharge", "00060", "Stream flow", "[cft_i]/s"),
    ("gage_height", "Gage Height", "00065", "Gage height", "[ft_i]"),
    ("water_temperature", "Water Temperature", "00010", "Temperature, water", "Cel"),
    ("groundwater_level_depth", "Depth to Groundwater", "72019",
     "Depth to water level below land surface", "[ft_i]"),
    ("groundwater_level_elevation", "Groundwater Level Elevation", "72020",
     "Water level elevation above NAVD 1988", "[ft_i]"),
    ("groundwater_level", "Groundwater Level", "62610", "Groundwater level", "[ft_i]"),
    ("reservoir_storage", "Reservoir Storage", "", "Reservoir storage", "[acr_us].[ft_i]"),
    ("reservoir_elevation", "Reservoir Elevation", "",
     "Reservoir water surface elevation", "[ft_i]"),
    ("reservoir_inflow", "Reservoir Inflow", "", "Flow, inflow", "[cft_i]/s"),
    ("reservoir_outflow", "Reservoir Outflow", "", "Flow, outflow", "[cft_i]/s"),
    ("evapotranspiration", "Evapotranspiration", "", "Evapotranspiration", "mm"),
    ("precipitation", "Precipitation", "00045", "Precipitation", "mm"),
    ("reference_et", "Reference Evapotranspiration", "",
     "Evapotranspiration, reference", "mm"),
    ("air_temperature", "Air Temperature", "", "Temperature, air", "Cel"),
    ("snowfall", "Snowfall", "", "Snow depth", "mm"),
    ("solar_radiation", "Solar Radiation", "", "Solar radiation", "W/m2"),
    ("wind_speed", "Wind Speed", "", "Wind velocity", "m/s"),
]

# ── Step 2: source native code → canonical concept key ──────────────────────
# Covers every (source, code) registry.get_all_parameter_maps() emits across the
# seven adapters with a PARAMETER_MAP (cdec, usgs, dwr_wdl, dwr_sgma, cimis,
# noaa, cnrfc). A regression test locks this against adapter drift.
CODE_TO_KEY = {
    "usgs": {
        "00060": "discharge",
        "00065": "gage_height",
        "00010": "water_temperature",
        "72019": "groundwater_level_depth",
        "72020": "groundwater_level_elevation",
        "62610": "groundwater_level",
    },
    "cdec": {
        "15": "reservoir_storage",
        "6": "reservoir_elevation",
        "76": "reservoir_inflow",
        "23": "reservoir_outflow",
        "1": "gage_height",        # CDEC "River Stage" is a gage-height reading
        "20": "discharge",         # CDEC "Flow"
        "2": "precipitation",
    },
    "dwr_wdl": {
        "gw_level": "groundwater_level_depth",
    },
    "dwr_sgma": {
        "gw_level": "groundwater_level_depth",
    },
    "cimis": {
        "day-eto": "reference_et",
        "day-precip": "precipitation",
        "day-sol-rad-avg": "solar_radiation",
        "day-wind-spd-avg": "wind_speed",
        "day-air-tmp-avg": "air_temperature",
    },
    "noaa": {
        "PRCP": "precipitation",
        "TMAX": "air_temperature",
        "TMIN": "air_temperature",
        "SNOW": "snowfall",
    },
    "cnrfc": {
        "streamflow": "discharge",   # streamflow forecast = the discharge concept
        "precip": "precipitation",
    },
}


class Command(BaseCommand):
    help = "Seed the ObservedProperty registry and SourceParameter crosswalk."

    def handle(self, *args, **options):
        # Step 1 — canonical concepts.
        op_created = 0
        for key, name, pcode, wqx, ucum in OBSERVED_PROPERTIES:
            _, created = ObservedProperty.objects.get_or_create(
                key=key,
                defaults={
                    "name": name,
                    "usgs_pcode": pcode,
                    "wqx_characteristic_name": wqx,
                    "ucum_unit": ucum,
                },
            )
            if created:
                op_created += 1

        by_key = {op.key: op for op in ObservedProperty.objects.all()}

        # Step 2 — crosswalk from the adapters' merged PARAMETER_MAPs.
        sp_created = 0
        unmapped = []
        for (source_code, parameter_code), info in registry.get_all_parameter_maps().items():
            concept_key = CODE_TO_KEY.get(source_code, {}).get(parameter_code)
            if concept_key is None or concept_key not in by_key:
                unmapped.append((source_code, parameter_code))
                self.stderr.write(
                    self.style.WARNING(
                        f"  no ObservedProperty for {source_code}:{parameter_code} "
                        f"({info.get('name', '')}) — skipped"
                    )
                )
                continue
            _, created = SourceParameter.objects.get_or_create(
                source_code=source_code,
                parameter_code=parameter_code,
                defaults={
                    "observed_property": by_key[concept_key],
                    "native_name": info.get("name", ""),
                    "native_unit": info.get("unit", ""),
                },
            )
            if created:
                sp_created += 1

        op_total = ObservedProperty.objects.count()
        sp_total = SourceParameter.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"ObservedProperty: {op_total} rows ({op_created} created); "
                f"SourceParameter: {sp_total} rows ({sp_created} created); "
                f"unmapped source codes: {len(unmapped)}"
            )
        )
