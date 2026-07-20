# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Drinking water models — the public-water-system (PWS) spine.

OpenH2O's second domain. Where ``wells``/``surface``/``accounting`` answer
*how much water*, this app answers *what is in it*: the system and its
facilities, the sampling points those facilities expose, the analytes measured
there, the regulatory limits those analytes are judged against, and the sample
events and results themselves.

Two rules shape every field below.

**Store the regulator's vocabulary, never invent one.** Every code list here is
transcribed from a published valid-value table — the DDW *Data Dictionary for
SDWIS.CSV Files* (rev 12/2021) for facility types, system status and system
classification, and EPA's SDWA/Envirofacts published code lists for owner type,
source type, PWS type, water type and availability. Codes are stored as the
regulator publishes them so imports and exports need no translation table.

**Prepare, never determine.** Nothing in this module calculates compliance.
``RegulatoryLimit`` records what the limit *is* and when it applied; comparing a
result against it is a later, rule-by-rule job.

The quality↔quantity join is ``SystemFacility.well`` → ``wells.Well``. A supply
well is ONE physical feature: the extraction ledger lives on the wells side, the
samples live here.
"""

from django.core.exceptions import ValidationError
from django.db import models

# -- Published code lists ----------------------------------------------------
# Source: DDW "Data Dictionary for SDWIS.CSV Files", rev 12/2021 (System Status).
ACTIVITY_STATUS_CHOICES = [
    ("A", "Active"),
    ("I", "Inactive"),
    ("P", "Proposed"),
]

# Source: EPA SDWA_PUB_WATER_SYSTEMS.PWS_TYPE_CODE.
PWS_TYPE_CHOICES = [
    ("CWS", "Community water system"),
    ("NTNCWS", "Non-transient non-community water system"),
    ("TNCWS", "Transient non-community water system"),
]

# Source: DDW SDWIS.CSV dictionary, "Water System Classification". CA adds NP.
STATE_CLASSIFICATION_CHOICES = [
    ("C", "Community"),
    ("NC", "Noncommunity (transient)"),
    ("NTNC", "Nontransient-noncommunity"),
    ("NP", "NonPublic"),
]

# Source: EPA SDWA_PUB_WATER_SYSTEMS.OWNER_TYPE_CODE.
OWNER_TYPE_CHOICES = [
    ("F", "Federal government"),
    ("L", "Local government"),
    ("M", "Public/Private"),
    ("N", "Native American"),
    ("P", "Private"),
    ("S", "State government"),
]

# Source: EPA SDWA_PUB_WATER_SYSTEMS.PRIMARY_SOURCE_CODE.
PRIMARY_SOURCE_CHOICES = [
    ("GW", "Ground water"),
    ("GWP", "Ground water purchased"),
    ("GU", "Ground water under the influence of surface water"),
    ("GUP", "Purchased ground water under the influence of surface water"),
    ("SW", "Surface water"),
    ("SWP", "Surface water purchased"),
]

# Source: DDW SDWIS.CSV dictionary "Facility Type" (21 codes), plus WH from
# EPA's federal SDWA_FACILITIES.FACILITY_TYPE_CODE list — a federal import that
# carried WH would otherwise fail validation against a CA-only vocabulary.
FACILITY_TYPE_CHOICES = [
    ("CC", "Consecutive Connection"),
    ("CH", "Common Headers"),
    ("CS", "Cistern"),
    ("CW", "Clear Well"),
    ("DS", "Distribution System"),
    ("IG", "Infiltration Gallery"),
    ("IN", "Intake"),
    ("NN", "Non-piped, Non-Purchased"),
    ("NP", "Non-piped, Purchased"),
    ("OT", "Other"),
    ("PC", "Pressure Control"),
    ("PF", "Pump Facility"),
    ("RC", "Roof Catchment"),
    ("RS", "Reservoir"),
    ("SI", "Surface Impoundment"),
    ("SP", "Spring"),
    ("SS", "Sampling Station"),
    ("ST", "Storage"),
    ("TM", "Transmission Main (Manifold)"),
    ("TP", "Treatment Plant"),
    ("WH", "Wellhead"),
    ("WL", "Well"),
]

# Source: EPA SDWA_FACILITIES.WATER_TYPE_CODE.
WATER_TYPE_CHOICES = [
    ("GW", "Ground water"),
    ("SW", "Surface water"),
    ("GU", "Ground water under the influence of surface water"),
]

# Source: EPA SDWA_FACILITIES.AVAILABILITY_CODE.
AVAILABILITY_CHOICES = [
    ("E", "Emergency"),
    ("I", "Interim"),
    ("P", "Permanent"),
    ("O", "Other"),
    ("S", "Seasonal"),
    ("U", "Unknown"),
]

POINT_TYPE_CHOICES = [
    ("source", "Source"),
    ("entry_point", "Entry Point"),
    ("distribution", "Distribution"),
    ("tap", "Tap"),
]

LIMIT_TYPE_MCL = "mcl"
LIMIT_TYPE_ACTION_LEVEL = "action_level"
LIMIT_TYPE_CHOICES = [
    (LIMIT_TYPE_MCL, "Maximum Contaminant Level"),
    ("secondary_mcl", "Secondary MCL"),
    ("mrdl", "Maximum Residual Disinfectant Level"),
    (LIMIT_TYPE_ACTION_LEVEL, "Action Level"),
    ("tt_trigger", "Treatment Technique Trigger"),
    ("dlr", "Detection Limit for Reporting"),
    ("notification_level", "Notification Level"),
]

SAMPLE_TYPE_CHOICES = [
    ("routine", "Routine"),
    ("repeat", "Repeat"),
    ("confirmation", "Confirmation"),
    ("special", "Special"),
]

RESULT_KIND_NUMERIC = "numeric"
RESULT_KIND_PRESENCE_ABSENCE = "presence_absence"
RESULT_KIND_CHOICES = [
    (RESULT_KIND_NUMERIC, "Numeric"),
    (RESULT_KIND_PRESENCE_ABSENCE, "Presence / Absence"),
]


# -- 1.1 System identity -----------------------------------------------------


class WaterSystem(models.Model):
    """A public water system. Usually one row per deployment, but a table so
    wholesalers and consecutive systems can be referenced by PWSID."""

    pwsid = models.CharField(
        max_length=20,
        unique=True,
        help_text="Public Water System ID, e.g. CA1910067. THE persistent "
        "identifier; joins the Water Data Standard crosswalk.",
    )
    name = models.CharField(max_length=200)
    activity_status = models.CharField(
        max_length=1, choices=ACTIVITY_STATUS_CHOICES, default="A"
    )
    pws_type = models.CharField(
        max_length=10, choices=PWS_TYPE_CHOICES, blank=True,
        help_text="Federal PWS type.",
    )
    state_classification = models.CharField(
        max_length=4, choices=STATE_CLASSIFICATION_CHOICES, blank=True,
        help_text="State classification. CA adds NP (non-public).",
    )
    owner_type = models.CharField(
        max_length=1, choices=OWNER_TYPE_CHOICES, blank=True
    )
    primary_source_code = models.CharField(
        max_length=3, choices=PRIMARY_SOURCE_CHOICES, blank=True
    )
    is_wholesaler = models.BooleanField(default=False)
    is_school_or_daycare = models.BooleanField(default=False)

    population_residential = models.IntegerField(null=True, blank=True)
    population_non_transient = models.IntegerField(null=True, blank=True)
    population_transient = models.IntegerField(null=True, blank=True)

    # Service connections by type. The DWW facilities export enumerates exactly
    # these five (AG/CB/CM/IN/RS); full-word names because `in` is a Python
    # keyword and half-abbreviated names would be worse than none.
    connections_agricultural = models.IntegerField(null=True, blank=True)
    connections_combined = models.IntegerField(null=True, blank=True)
    connections_commercial = models.IntegerField(null=True, blank=True)
    connections_industrial = models.IntegerField(null=True, blank=True)
    connections_residential = models.IntegerField(null=True, blank=True)

    regulating_agency = models.CharField(
        max_length=100, blank=True,
        help_text="DDW district office or Local Primacy Agency; NM: NMED DWB.",
    )
    # Deliberately NOT an FK: the seller may be a system this deployment does
    # not carry a row for. A soft link that can dangle beats an FK that cannot
    # be populated.
    seller_pwsid = models.CharField(
        max_length=20, blank=True,
        help_text="Consecutive-system link: the PWSID this system buys from.",
    )

    class Meta:
        ordering = ["pwsid"]
        verbose_name = "Water System"

    def __str__(self):
        return f"{self.name} ({self.pwsid})"


class SystemFacility(models.Model):
    """Mirrors SDWIS WATER_SYSTEM_FACILITY."""

    system = models.ForeignKey(
        WaterSystem, on_delete=models.CASCADE, related_name="facilities"
    )
    facility_id = models.CharField(
        max_length=30, help_text="State-assigned facility ID."
    )
    name = models.CharField(max_length=200, blank=True)
    facility_type = models.CharField(
        max_length=2, choices=FACILITY_TYPE_CHOICES, blank=True
    )
    activity_status = models.CharField(
        max_length=1, choices=ACTIVITY_STATUS_CHOICES, default="A"
    )
    is_source = models.BooleanField(default=False)
    water_type = models.CharField(
        max_length=2, choices=WATER_TYPE_CHOICES, blank=True
    )
    availability = models.CharField(
        max_length=1, choices=AVAILABILITY_CHOICES, blank=True
    )
    # The quality↔quantity join. SET_NULL because deleting a well record must
    # not delete the sampling history taken at it.
    well = models.ForeignKey(
        "wells.Well",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="drinking_facilities",
        help_text="The physical well this facility is, when it is a well.",
    )

    class Meta:
        ordering = ["system", "facility_id"]
        unique_together = [("system", "facility_id")]
        verbose_name = "System Facility"
        verbose_name_plural = "System Facilities"

    def __str__(self):
        return f"{self.facility_id} — {self.name or self.get_facility_type_display()}"


# -- 1.2 Sampling & results --------------------------------------------------


class SamplingPoint(models.Model):
    """A DDW PS Code location: where a sample is physically drawn."""

    ps_code = models.CharField(
        max_length=60,
        unique=True,
        help_text="Primary Station Code, the composite "
        "{pwsid}_{facility_id}_{point_number} exactly as DDW publishes it. "
        "Stored verbatim — never derived on read.",
    )
    name = models.CharField(
        max_length=200, blank=True,
        help_text='e.g. "LCR Tap Sample", "DBPR Sample".',
    )
    facility = models.ForeignKey(
        SystemFacility, on_delete=models.CASCADE, related_name="sampling_points"
    )
    point_type = models.CharField(
        max_length=20, choices=POINT_TYPE_CHOICES, blank=True
    )

    class Meta:
        ordering = ["ps_code"]
        verbose_name = "Sampling Point"

    def __str__(self):
        return f"{self.ps_code}{f' — {self.name}' if self.name else ''}"


class Analyte(models.Model):
    """A measured substance. Extends the ``standards`` vocabulary, does not
    replace it — the FK buys WQX CharacteristicName and UCUM units for free."""

    ddw_code = models.CharField(
        max_length=4,
        unique=True,
        null=True,
        blank=True,
        help_text="DDW's four-digit analyte code. NULL when no verifiable code "
        "is known — never fabricate one.",
    )
    name = models.CharField(max_length=200, unique=True)
    storet_code = models.CharField(
        max_length=10, blank=True, help_text="Legacy STORET code (historical files)."
    )
    observed_property = models.ForeignKey(
        "standards.ObservedProperty",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="drinking_analytes",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name}{f' ({self.ddw_code})' if self.ddw_code else ''}"


class RegulatoryLimit(models.Model):
    """A versioned regulatory threshold for one analyte in one jurisdiction.

    Versioning is the whole point of this table — limits change (hexavalent
    chromium, the lead action level). ``clean()`` refuses overlapping date
    ranges for the same (analyte, limit_type, jurisdiction) so "the limit on
    date D" always has exactly one answer. Deliberately NOT enforced with a
    btree_gist exclusion constraint: that needs an extension the small-VPS
    stock Postgres this platform targets does not ship enabled.
    """

    analyte = models.ForeignKey(
        Analyte, on_delete=models.CASCADE, related_name="limits"
    )
    limit_type = models.CharField(max_length=20, choices=LIMIT_TYPE_CHOICES)
    value = models.DecimalField(max_digits=16, decimal_places=6)
    unit = models.CharField(max_length=20, help_text="e.g. mg/L, ug/L, pCi/L.")
    jurisdiction = models.CharField(
        max_length=20, help_text='e.g. "federal", "CA", "NM".'
    )
    effective_start = models.DateField()
    effective_end = models.DateField(
        null=True, blank=True, help_text="NULL = still in force. Inclusive."
    )

    class Meta:
        ordering = ["analyte", "limit_type", "jurisdiction", "-effective_start"]
        verbose_name = "Regulatory Limit"

    def __str__(self):
        return (
            f"{self.analyte} {self.get_limit_type_display()} "
            f"{self.value} {self.unit} ({self.jurisdiction})"
        )

    def clean(self):
        super().clean()
        if self.effective_end and self.effective_start:
            if self.effective_end < self.effective_start:
                raise ValidationError(
                    {"effective_end": "effective_end cannot precede effective_start."}
                )
        if not (self.analyte_id and self.effective_start):
            return

        siblings = RegulatoryLimit.objects.filter(
            analyte_id=self.analyte_id,
            limit_type=self.limit_type,
            jurisdiction=self.jurisdiction,
        )
        if self.pk:
            siblings = siblings.exclude(pk=self.pk)

        for other in siblings:
            starts_before_other_ends = (
                other.effective_end is None or self.effective_start <= other.effective_end
            )
            ends_after_other_starts = (
                self.effective_end is None or self.effective_end >= other.effective_start
            )
            if starts_before_other_ends and ends_after_other_starts:
                raise ValidationError(
                    "Overlapping effective period for this analyte, limit type "
                    f"and jurisdiction: {other}."
                )


class SampleEvent(models.Model):
    """One physical collection at one sampling point."""

    sampling_point = models.ForeignKey(
        SamplingPoint, on_delete=models.CASCADE, related_name="events"
    )
    sample_date = models.DateField()
    sample_time = models.TimeField(null=True, blank=True)
    sample_type = models.CharField(
        max_length=20, choices=SAMPLE_TYPE_CHOICES, default="routine"
    )
    collector = models.CharField(max_length=200, blank=True)
    chain_of_custody_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-sample_date", "sampling_point"]
        verbose_name = "Sample Event"

    def __str__(self):
        return f"{self.sampling_point.ps_code} @ {self.sample_date}"


class SampleResult(models.Model):
    """One analyte's finding within a sample event.

    ``result_kind`` exists so a present/absent coliform result is
    *unrepresentable* as a number. Total coliform is reported present or
    absent, never as a concentration; folding it into the non-detect flag
    (``less_than_rl``) would silently turn "absent" into "below reporting
    level", which is a different claim. The rule is enforced twice — in
    ``clean()`` for forms and admin, and as DB CheckConstraints so a bulk
    import or a raw ``.save()`` cannot route around it.
    """

    event = models.ForeignKey(
        SampleEvent, on_delete=models.CASCADE, related_name="results"
    )
    # PROTECT, not CASCADE: results are evidence. Deleting a vocabulary row
    # must never take lab data with it.
    analyte = models.ForeignKey(
        Analyte, on_delete=models.PROTECT, related_name="results"
    )
    result_kind = models.CharField(
        max_length=20, choices=RESULT_KIND_CHOICES, default=RESULT_KIND_NUMERIC
    )
    result_value = models.DecimalField(
        max_digits=16, decimal_places=6, null=True, blank=True
    )
    presence = models.BooleanField(
        null=True, blank=True, help_text="True = present. Presence/absence results only."
    )
    unit = models.CharField(max_length=20, blank=True)
    less_than_rl = models.BooleanField(
        default=False, help_text="Non-detect flag (DDW 'Less Than Reporting Level' = Y)."
    )
    reporting_level = models.DecimalField(
        max_digits=16, decimal_places=6, null=True, blank=True
    )
    counting_error = models.DecimalField(
        max_digits=16,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Statistical variability of the analysis; radionuclides.",
    )
    analysis_date = models.DateField(null=True, blank=True)
    method = models.CharField(max_length=100, blank=True)
    lab_name = models.CharField(max_length=200, blank=True)
    lab_cert_no = models.CharField(
        max_length=20, blank=True, help_text="ELAP certification number."
    )

    class Meta:
        ordering = ["-event__sample_date", "analyte"]
        verbose_name = "Sample Result"
        constraints = [
            models.CheckConstraint(
                name="drinking_numeric_result_has_no_presence",
                condition=(
                    ~models.Q(result_kind=RESULT_KIND_NUMERIC)
                    | models.Q(presence__isnull=True)
                ),
            ),
            models.CheckConstraint(
                name="drinking_presence_result_has_no_value",
                condition=(
                    ~models.Q(result_kind=RESULT_KIND_PRESENCE_ABSENCE)
                    | (models.Q(result_value__isnull=True) & models.Q(less_than_rl=False))
                ),
            ),
        ]

    def __str__(self):
        if self.result_kind == RESULT_KIND_PRESENCE_ABSENCE:
            shown = {True: "present", False: "absent", None: "—"}[self.presence]
        else:
            shown = f"{self.result_value} {self.unit}".strip()
        return f"{self.analyte}: {shown}"

    def clean(self):
        super().clean()
        if self.result_kind == RESULT_KIND_NUMERIC and self.presence is not None:
            raise ValidationError(
                {"presence": "A numeric result cannot carry a presence/absence value."}
            )
        if self.result_kind == RESULT_KIND_PRESENCE_ABSENCE:
            errors = {}
            if self.result_value is not None:
                errors["result_value"] = (
                    "A presence/absence result cannot carry a numeric value."
                )
            if self.less_than_rl:
                errors["less_than_rl"] = (
                    "The non-detect flag does not apply to a presence/absence "
                    "result — 'absent' is not 'below reporting level'."
                )
            if errors:
                raise ValidationError(errors)


class EnvirofactsCache(models.Model):
    """A raw EPA Envirofacts response, kept on a row so it survives a demo reset.

    Why a real table and not ``django.core.cache``: the cache backend is
    ``DatabaseCache`` on the ``feedback_cache`` table
    (``config/settings/base.py``), and ``createcachetable`` drops and recreates
    it on every demo reset (``scripts/reset-demo.sh``). An onboarding cache has
    to outlive that. ``datasync.models.OpenETCache`` set this precedent for the
    same reason, and this model deliberately mirrors its shape.

    Why the payload is stored VERBATIM and never pre-mapped: caching a mapped
    result would freeze Plan 79-02's mapping decisions into the cache, so a
    later mapping bug would survive the code fix until every row expired.
    Storing what EPA sent means a mapping change takes effect on the next read.

    TTL is 30 days by default, matching ``OPENET_CACHE_DAYS``, because SDWIS is
    a periodic federal extract rather than live telemetry. EPA's actual refresh
    cadence is NOT documented — ``epa.gov/enviro/sdwis-model`` 404s — so this is
    a deliberate, overridable choice (``ENVIROFACTS_CACHE_DAYS``) and not a
    claim about how often the federal data changes.
    """

    pwsid = models.CharField(max_length=20, db_index=True)
    table_name = models.CharField(
        max_length=40,
        help_text="WATER_SYSTEM | WATER_SYSTEM_FACILITY | GEOGRAPHIC_AREA",
    )
    payload = models.JSONField(help_text="The raw Envirofacts response, verbatim")
    queried_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Envirofacts cache entry"
        verbose_name_plural = "Envirofacts cache entries"
        # One row per (system, table) so update_or_create can never duplicate:
        # a stale entry is refreshed in place, never shadowed by a second row.
        unique_together = [("pwsid", "table_name")]

    def __str__(self):
        return f"{self.pwsid} {self.table_name} @ {self.queried_at:%Y-%m-%d}"

    def is_stale(self, max_age_days=None):
        """Mirrors ``OpenETCache.is_stale``: older than the TTL, in whole days."""
        from django.conf import settings as django_settings
        from django.utils import timezone

        max_days = max_age_days or getattr(
            django_settings, "ENVIROFACTS_CACHE_DAYS", 30
        )
        return (timezone.now() - self.queried_at).days > max_days
