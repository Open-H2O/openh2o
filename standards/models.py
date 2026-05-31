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
