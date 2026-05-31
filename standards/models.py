"""
Conformance vocabulary: the canonical observed-property registry.

This is the linchpin of v1.3. ``ObservedProperty`` is the controlled vocabulary
that maps every real-world measured thing (stream discharge, depth to
groundwater, reservoir storage, ...) to its USGS parameter code, EPA WQX
CharacteristicName, and UCUM unit. ``SourceParameter`` is the crosswalk that
records, for each data source, how that source's own native code
(``PARAMETER_MAP`` key) maps onto a canonical concept.

Promoted here from the runtime label helper in
``datasync/adapters/registry.py`` (decision 26.1-01), which only carried a
display name + unit and which nothing in the database referenced. The later
publishing layers read measurement vocabulary from this registry: the
SensorThings API (Phase 32) and the Frictionless/WaDE exports (Phase 33).
"""

from django.db import models


class ObservedProperty(models.Model):
    """One row per real-world measured concept (the canonical vocabulary)."""

    key = models.SlugField(
        unique=True,
        max_length=100,
        help_text="Stable machine key, e.g. groundwater_level_depth, discharge.",
    )
    name = models.CharField(
        max_length=200,
        help_text='Human label, e.g. "Depth to Groundwater".',
    )
    usgs_pcode = models.CharField(
        max_length=10,
        blank=True,
        help_text="5-digit USGS parameter code, e.g. 72019. Blank where the "
        "concept has no USGS code (CDEC reservoir sensors, OpenET ET).",
    )
    wqx_characteristic_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="EPA WQX CharacteristicName.",
    )
    ucum_unit = models.CharField(
        max_length=50,
        blank=True,
        help_text="UCUM unit code (unitsofmeasure.org), e.g. [cft_i]/s, [ft_i], Cel.",
    )
    description = models.TextField(blank=True)
    definition_url = models.URLField(
        blank=True,
        help_text="Optional canonical definition link.",
    )

    class Meta:
        ordering = ["key"]
        verbose_name = "Observed Property"
        verbose_name_plural = "Observed Properties"

    def __str__(self):
        return f"{self.name} ({self.key})"

    def is_publishable(self) -> bool:
        """
        True when the property carries both a USGS pcode and a UCUM unit.

        The full publish-readiness predicate: Phase 32/33 will refuse to
        serialize a property where this is False. Note the conformance audit
        (``check_conformance``) gates on UCUM for ALL properties but treats a
        blank pcode as a known, non-blocking exception, because several real
        concepts (reservoir storage, ET) legitimately have no USGS code.
        """
        return bool(self.usgs_pcode and self.ucum_unit)


class SourceParameter(models.Model):
    """Crosswalk: a data source's native code → a canonical ObservedProperty."""

    source_code = models.CharField(
        max_length=50,
        help_text='Adapter code: "usgs", "cdec", "dwr_wdl", etc.',
    )
    parameter_code = models.CharField(
        max_length=50,
        help_text="The source's native code (the PARAMETER_MAP dict key).",
    )
    observed_property = models.ForeignKey(
        ObservedProperty,
        on_delete=models.PROTECT,
        related_name="source_parameters",
    )
    native_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="The source's own label (from PARAMETER_MAP name).",
    )
    native_unit = models.CharField(
        max_length=50,
        blank=True,
        help_text="The source's own unit string (from PARAMETER_MAP unit).",
    )

    class Meta:
        ordering = ["source_code", "parameter_code"]
        unique_together = [("source_code", "parameter_code")]
        verbose_name = "Source Parameter"
        verbose_name_plural = "Source Parameters"

    def __str__(self):
        return f"{self.source_code}:{self.parameter_code} → {self.observed_property.key}"


class Datastream(models.Model):
    """
    A SensorThings Datastream: the addressable series binding a Thing
    (a well or an external/surface station) + a Sensor + an ObservedProperty.

    This is the one OGC SensorThings entity the 48-table model didn't already
    have. Phase 32 serializes each Datastream and attaches Observations to it
    (a SensorMeasurement *is* the Observation in that mapping — no separate
    Observation table). The FeatureOfInterest is derived from the well's screen
    interval + vertical datum, so there is no FeatureOfInterest table either.
    Datastream is therefore the only new structural entity v1.3 adds.
    """

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    observed_property = models.ForeignKey(
        ObservedProperty,
        on_delete=models.PROTECT,
        related_name="datastreams",
        help_text="What is measured (the canonical concept).",
    )
    sensor = models.ForeignKey(
        "measurements.Sensor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="datastreams",
        help_text="The SensorThings Sensor — the instrument/procedure.",
    )
    well = models.ForeignKey(
        "wells.Well",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="datastreams",
        help_text="The SensorThings Thing for a groundwater series.",
    )
    monitored_station = models.ForeignKey(
        "datasync.MonitoredStation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="datastreams",
        help_text="The SensorThings Thing for an external/surface telemetry series.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Datastream"
        verbose_name_plural = "Datastreams"
        # Soft guard against duplicate series. NOTE: Postgres treats NULLs as
        # distinct, so a row with a NULL sensor/well/monitored_station is not
        # blocked from repeating — this is a guard, not an airtight constraint
        # (adequate for the demo; tighten with partial unique indexes if needed).
        unique_together = [
            ("observed_property", "sensor", "well", "monitored_station")
        ]

    def __str__(self):
        return self.name

    @property
    def uom(self) -> str:
        """
        Unit of measurement, read live from the linked ObservedProperty's UCUM
        unit so it can never drift from the canonical vocabulary. Phase 32 would
        only add a stored column here if it ever needs a per-series override.
        """
        return self.observed_property.ucum_unit
