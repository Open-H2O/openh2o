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

from decimal import Decimal

from django.contrib.gis.db import models as gis_models
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
    # A groundwater source sample required after a coliform-positive routine
    # sample. It carries its own regulatory meaning under the Ground Water Rule,
    # so it gets its own entry rather than being folded into routine/special
    # (EPA CMDP code `TG`). Added for ISS-076.
    ("triggered", "Triggered"),
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

    # EPA's published aggregates, carried ALONGSIDE the splits below and never
    # instead of them. The federal record sends one `population_served_count`
    # and one `service_connections_count`; the residential / non-transient /
    # transient and per-use-type splits beside them come from a different
    # source, the state's annual electronic report (eAR). A system may
    # legitimately have one shape without the other, which is the whole reason
    # both live on this model — do not "consolidate" them.
    population_served_total = models.IntegerField(
        null=True, blank=True,
        help_text="EPA WATER_SYSTEM.population_served_count — the published "
        "aggregate. The residential / non-transient / transient split beside "
        "it comes from the state eAR, not from EPA; a system may have this "
        "total with no split, or a split with no total.",
    )
    service_connections_total = models.IntegerField(
        null=True, blank=True,
        help_text="EPA WATER_SYSTEM.service_connections_count — the published "
        "aggregate. The per-use-type connection breakdown beside it comes from "
        "the state eAR, not from EPA; a system may have this total with no "
        "breakdown, or a breakdown with no total.",
    )

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

    # EPA's administrative contact block, address only. Phone, fax, email,
    # admin_name and org_name are deliberately NOT carried: they are a named
    # individual's contact details and carry a privacy/retention cost this
    # platform does not take on (scope call, 2026-07-19).
    mailing_address_line1 = models.CharField(max_length=100, blank=True)
    mailing_address_line2 = models.CharField(max_length=100, blank=True)
    mailing_city = models.CharField(max_length=100, blank=True)
    mailing_state = models.CharField(
        max_length=2, blank=True,
        help_text="The ADMINISTRATOR'S MAILING state, NOT the primacy state. "
        "EPA's WATER_SYSTEM.state_code is the address on file: PWSID 083090017 "
        "is a Colorado system (primacy_agency_code 08) whose state_code is CA "
        "because its administrator's address is in Anaheim. Never filter "
        "jurisdiction by this field — use primacy agency.",
    )
    mailing_zip = models.CharField(max_length=10, blank=True)

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
        max_length=30,
        help_text="State-assigned facility ID — the segment DDW's PS Codes are "
        "built from (CA1010001_010_010). From EPA this is state_facility_id, "
        "NEVER EPA's own facility_id. Not always numeric: DST is real.",
    )
    # EPA's internal key for the same facility, kept so a federal re-fetch can be
    # traced, but never used to compose a PS Code. For the facility above EPA
    # says 14042 while the state says 010; using 14042 would compose
    # CA1010001_14042_001 and match nothing in a real lab file.
    epa_facility_id = models.CharField(
        max_length=20, blank=True, db_index=True,
        help_text="EPA's own facility ID. Provenance only; never a PS Code "
        "segment.",
    )
    name = models.CharField(max_length=200, blank=True)
    # 146-04 Task 3 (D9, the memo's J8). The operator's own word for the
    # facility, shown BESIDE the state's padded name and never in place of it:
    # the state's name is what the lab file and the state's reports carry, so
    # it stays the one the record is matched on.
    local_name = models.CharField(
        max_length=200, blank=True,
        help_text="What the operator calls it: Cedar Well 02.",
    )
    # False for every row the federal record wrote (Envirofacts onboarding,
    # the demonstration's seed); True for a row typed in on this deployment's
    # facility form. It decides which publisher the facility page names, and
    # which fields the edit form offers: the state's fields on a federal row
    # stay the state's.
    added_by_hand = models.BooleanField(
        default=False,
        help_text="Entered on this deployment's facility form rather than "
        "written from the federal record.",
    )
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
    # The facility owns the coordinate, not the sampling point, because that is
    # what the published record actually describes: GAMA publishes the location
    # of the SOURCE WELL, which is the facility. A sampling point is a tap ON a
    # facility and inherits its position — which is also why one map can carry
    # both without drawing two sets of dots on the same spot.
    #
    # NOT copied from `well.location` on read: `wells` is schema-resident, so in
    # the drinking-water-utility flavor (parcels+accounting off takes wells with
    # it, core/modules.py) that table is empty by design and a facility reading
    # its position through the FK would be permanently unmapped.
    location = gis_models.PointField(
        srid=4326, null=True, blank=True,
        help_text="Published location of the facility, from GAMA, which "
                  "publishes coordinates for source wells only; most "
                  "facilities have none.",
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


# -- 1.3 Production by month and source (146-04 Task 2, D7, ISS-184) --------
#
# The record shape 2's operator never had: what the system produced or
# delivered, by month and by source. Two real-world layouts land here --
# the state's eAR export and the operator's own monthly log
# (``drinking/production_import.py``) -- so the type codes below are the
# eAR's own six, and the units are the eAR's own four.

# Source: the eAR's own TypeCode column. NonPotableSold is the file's
# seventh code and carries no entry here -- an eAR row typed NonPotableSold
# is a row error naming it, not silently dropped or folded into NonPotable.
PRODUCTION_TYPE_GW = "GW"
PRODUCTION_TYPE_SW = "SW"
PRODUCTION_TYPE_PU = "PU"
PRODUCTION_TYPE_SO = "SO"
PRODUCTION_TYPE_NP = "NP"
PRODUCTION_TYPE_RC = "RC"
PRODUCTION_TYPE_CHOICES = [
    (PRODUCTION_TYPE_GW, "Groundwater"),
    (PRODUCTION_TYPE_SW, "Surface water"),
    (PRODUCTION_TYPE_PU, "Purchased"),
    (PRODUCTION_TYPE_SO, "Sold"),
    (PRODUCTION_TYPE_NP, "Non-potable"),
    (PRODUCTION_TYPE_RC, "Recycled"),
]

# Source: the eAR's own "Units of Measure As Reported" column.
PRODUCTION_UNIT_GALLONS = "G"
PRODUCTION_UNIT_MG = "MG"
PRODUCTION_UNIT_AF = "AF"
PRODUCTION_UNIT_CCF = "CCF"
PRODUCTION_UNIT_CHOICES = [
    (PRODUCTION_UNIT_GALLONS, "Gallons"),
    (PRODUCTION_UNIT_MG, "Million gallons"),
    (PRODUCTION_UNIT_AF, "Acre-feet"),
    (PRODUCTION_UNIT_CCF, "Hundred cubic feet (CCF)"),
]

PRODUCTION_PROVENANCE_EAR = "ear_export"
PRODUCTION_PROVENANCE_OPERATOR_LOG = "operator_log"
PRODUCTION_PROVENANCE_TYPED = "typed"
PRODUCTION_PROVENANCE_CHOICES = [
    (PRODUCTION_PROVENANCE_EAR, "State eAR export"),
    (PRODUCTION_PROVENANCE_OPERATOR_LOG, "Operator's monthly log"),
    (PRODUCTION_PROVENANCE_TYPED, "Typed in"),
]

# Conversions to gallons, matching ``surface/diversion_import.py``'s own
# figures exactly. Repeated here rather than imported: ``drinking`` and
# ``surface`` are each independently droppable (core/modules.py's module
# composition rule), so neither module may import from the other, and a
# constant true in both places is worth restating rather than coupling two
# domains over three numbers.
PRODUCTION_GALLONS_PER_ACRE_FOOT = Decimal("325851")
PRODUCTION_GALLONS_PER_MG = Decimal("1000000")
PRODUCTION_GALLONS_PER_CCF = Decimal("748.05")

_TWO_PLACES = Decimal("0.01")


class SystemProduction(models.Model):
    """One month's production or delivery, by source type, for a water system.

    D7: shape 2's own gap. The state's eAR export gives one row per
    (PWSID, Year, Month, TypeCode); the operator's own monthly log gives one
    column per source and no PWSID or unit at all. Both land on this one
    table (see ``drinking/production_import.py`` for how each is read).

    ``volume_gallons`` and ``volume_acre_feet`` are computed at save from
    ``volume_as_reported`` and ``unit_as_reported`` -- stored rather than
    derived on read so the year table (``/drinking/production/``) can sum
    and sort without recomputing a conversion per row on every page load.
    """

    system = models.ForeignKey(
        WaterSystem, on_delete=models.CASCADE, related_name="production_records"
    )
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="1 to 12. Null means the year was reported as one figure -- "
        "the eAR puts that in the January row, so the importer keeps it as "
        "month 1 and sets annual_in_january rather than leaving this blank.",
    )
    type_code = models.CharField(max_length=2, choices=PRODUCTION_TYPE_CHOICES)
    facility = models.ForeignKey(
        SystemFacility,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="production_records",
        help_text="The source, when the operator's log names one.",
    )
    volume_as_reported = models.DecimalField(max_digits=14, decimal_places=2)
    unit_as_reported = models.CharField(
        max_length=3, choices=PRODUCTION_UNIT_CHOICES
    )
    volume_gallons = models.DecimalField(
        max_digits=18, decimal_places=2, editable=False
    )
    volume_acre_feet = models.DecimalField(
        max_digits=14, decimal_places=2, editable=False
    )
    provenance = models.CharField(
        max_length=20, choices=PRODUCTION_PROVENANCE_CHOICES
    )
    annual_in_january = models.BooleanField(
        default=False,
        help_text="This January row stands for the whole year; no other "
        "month of this year and type appears in the file it came from.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["system", "-year", "month", "type_code"]
        # Postgres treats NULL as distinct from NULL in a unique constraint,
        # so this enforces nothing for the common case (facility blank --
        # neither import layout names one). It still stops a genuine
        # double-entry once a facility IS attached, and it documents the
        # key the importer's own dedup query uses
        # (``drinking/production_import.py::commit_rows``), which is the
        # real guard against a duplicate row with no facility.
        unique_together = [("system", "year", "month", "type_code", "facility")]
        verbose_name = "System Production"
        verbose_name_plural = "System Production"

    def __str__(self):
        month_label = f"{self.month:02d}" if self.month else "year"
        return (
            f"{self.system.pwsid} {self.year}-{month_label} {self.type_code}: "
            f"{self.volume_as_reported} {self.unit_as_reported}"
        )

    def _gallons(self):
        if self.unit_as_reported == PRODUCTION_UNIT_GALLONS:
            return self.volume_as_reported
        if self.unit_as_reported == PRODUCTION_UNIT_MG:
            return self.volume_as_reported * PRODUCTION_GALLONS_PER_MG
        if self.unit_as_reported == PRODUCTION_UNIT_CCF:
            return self.volume_as_reported * PRODUCTION_GALLONS_PER_CCF
        if self.unit_as_reported == PRODUCTION_UNIT_AF:
            return self.volume_as_reported * PRODUCTION_GALLONS_PER_ACRE_FOOT
        raise ValueError(f"Unknown unit_as_reported: {self.unit_as_reported!r}")

    def save(self, *args, **kwargs):
        self.volume_gallons = self._gallons().quantize(_TWO_PLACES)
        self.volume_acre_feet = (
            self.volume_gallons / PRODUCTION_GALLONS_PER_ACRE_FOOT
        ).quantize(_TWO_PLACES)
        super().save(*args, **kwargs)


# -- 1.4 The operator's sampling schedule (146-04 Task 4, D8) ----------------

SCHEDULE_FREQUENCY_CHOICES = [
    ("daily", "Daily"),
    ("weekly", "Weekly"),
    ("monthly", "Monthly"),
    ("quarterly", "Quarterly"),
    ("annual", "Annual"),
    ("every_3_years", "Every 3 years"),
    ("every_9_years", "Every 9 years"),
    ("every_10_years", "Every 10 years"),
    ("other", "Other"),
]


class SamplingSchedule(models.Model):
    """One row of the operator's own sampling checklist.

    **Held, never computed.** ``next_due`` is the date the operator typed. The
    frequency is a label for the row, not an input to arithmetic: nothing here
    adds a month to ``last_done``, because the schedule is the one the state
    set for the system and the operator keeps, and a software-computed date
    that disagreed with it would be a second, wrong schedule. Brent's "the plan
    holds" (2026-09-20 19:06 PDT) answered the memo's J11: the product holds a
    schedule.

    A row names what is sampled either by ``analyte`` (the platform's own
    vocabulary) or by ``group_label`` (coliform, a siting plan, anything the
    operator's checklist groups), and the form requires one of the two.
    """

    system = models.ForeignKey(
        WaterSystem, on_delete=models.CASCADE, related_name="sampling_schedule"
    )
    sampling_point = models.ForeignKey(
        SamplingPoint, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="schedule_rows",
    )
    analyte = models.ForeignKey(
        Analyte, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="schedule_rows",
    )
    group_label = models.CharField(
        max_length=100, blank=True,
        help_text="What the row covers when it is not one analyte: coliform, "
        "nitrate, chlorine residual, siting plan.",
    )
    frequency = models.CharField(max_length=20, choices=SCHEDULE_FREQUENCY_CHOICES)
    last_done = models.DateField(null=True, blank=True)
    next_due = models.DateField(
        null=True, blank=True,
        help_text="Typed by the operator; never computed from the frequency.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Earliest date first, rows with no date last; the list page reads in
        # this order and the overview's one line takes the first dated row.
        ordering = [models.F("next_due").asc(nulls_last=True), "pk"]
        verbose_name = "Sampling Schedule Row"
        verbose_name_plural = "Sampling Schedule"

    @property
    def label(self):
        """What the row covers, in the operator's words first."""
        if self.group_label:
            return self.group_label
        if self.analyte_id:
            return self.analyte.name
        return "Sampling"

    def __str__(self):
        return f"{self.system.pwsid} {self.label} ({self.get_frequency_display()})"
