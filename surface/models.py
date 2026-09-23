# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Surface models.

The surface-water supply domain. WaterRight (and WaterRightType) carry the
diversion entitlement and its CalWATRS PIN; PointOfDiversion is where that water
is taken from a stream, with PointOfDiversionParcel linking a diversion to the
parcels it serves. DiversionRecord logs each diversion event, including the
returned_af that distinguishes diverted from actually consumed water.
CurtailmentOrder records when a right is curtailed. MeasuringDevice is the
23 CCR 934(b)(1) device registry (146-03 Task 1), linked to a point of
diversion through PointOfDiversionDevice the way wells.WellMeter links a meter
to a well. IrrigationMethod is East Turlock Subbasin GSA's published
efficiency table, seeded by migration, and ParcelIrrigationMethod records which
method a use area uses (146-05 Task 1); nothing in the engine reads either yet.
"""
from datetime import date
from decimal import Decimal

from django.contrib.gis.db import models
from django.core.exceptions import ValidationError


class WaterRightType(models.Model):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class WaterRight(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("curtailed", "Curtailed"),
        ("revoked", "Revoked"),
    ]

    right_id = models.CharField(max_length=50, unique=True)
    right_type = models.ForeignKey(WaterRightType, on_delete=models.PROTECT)
    holder_name = models.CharField(max_length=200)
    priority_date = models.DateField(null=True, blank=True)
    face_value_acre_feet = models.DecimalField(
        max_digits=12, decimal_places=4, null=True, blank=True
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    source_name = models.CharField(max_length=200, blank=True)
    calwatrs_pin = models.CharField(
        max_length=50,
        blank=True,
        help_text="CalWATRS PIN mailed by SWRCB for this water right. The state "
        "issues one PIN per right; supplied by the agency, not fetched by OpenH2O.",
    )
    state_status = models.CharField(
        max_length=50,
        blank=True,
        help_text="WATER_RIGHT_STATUS in the state's rights list (Licensed, "
        "Permitted, Claimed...). Separate from the Status field above, which "
        "this platform tracks on its own.",
    )
    permit_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="PERMIT_ID in the state's rights list.",
    )
    license_number = models.CharField(
        max_length=50,
        blank=True,
        help_text="LICENSE_ID in the state's rights list.",
    )
    purpose_of_use = models.CharField(
        max_length=100,
        blank=True,
        help_text="USE_CODE in the state's rights list (Irrigation, Municipal...).",
    )
    net_acreage = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="USE_NET_ACREAGE in the state's rights list, in acres.",
    )
    max_rate_cfs = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="MAX_DD_APPL in the state's rights list, in cubic feet per second.",
    )
    direct_season_start_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="DIRECT_SEASON_START_MONTH_1 in the state's rights list.",
    )
    direct_season_start_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="DIRECT_DIV_SEASON_START_DAY_1 in the state's rights list.",
    )
    direct_season_end_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="DIRECT_DIV_SEASON_END_MONTH_1 in the state's rights list.",
    )
    direct_season_end_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="DIRECT_DIV_SEASON_END_DAY_1 in the state's rights list.",
    )
    storage_season_start_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="STORAGE_SEASON_START_MONTH_1 in the state's rights list.",
    )
    storage_season_start_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="STORAGE_SEASON_START_DAY_1 in the state's rights list.",
    )
    storage_season_end_month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="STORAGE_SEASON_END_MONTH_1 in the state's rights list.",
    )
    storage_season_end_day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="STORAGE_SEASON_END_DAY_1 in the state's rights list.",
    )
    watershed = models.CharField(
        max_length=200,
        blank=True,
        help_text="WATERSHED in the state's rights list.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.right_id

    def direct_season_display(self):
        """'Mar 1 to Oct 31 (direct diversion)', or '' with any part missing."""
        return _season_display(
            self.direct_season_start_month, self.direct_season_start_day,
            self.direct_season_end_month, self.direct_season_end_day,
            "direct diversion",
        )

    def storage_season_display(self):
        """'Nov 1 to Feb 28 (storage)', or '' with any part missing."""
        return _season_display(
            self.storage_season_start_month, self.storage_season_start_day,
            self.storage_season_end_month, self.storage_season_end_day,
            "storage",
        )


_MONTH_ABBR = [
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]


def _season_display(start_month, start_day, end_month, end_day, label):
    if not (start_month and start_day and end_month and end_day):
        return ""
    return (
        f"{_MONTH_ABBR[start_month]} {start_day} to "
        f"{_MONTH_ABBR[end_month]} {end_day} ({label})"
    )


class WaterRightParcel(models.Model):
    water_right = models.ForeignKey(
        WaterRight, on_delete=models.CASCADE, related_name="water_right_parcels"
    )
    parcel = models.ForeignKey(
        "parcels.Parcel", on_delete=models.CASCADE, related_name="water_right_parcels"
    )
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = [("water_right", "parcel")]

    def __str__(self):
        return f"{self.water_right} → {self.parcel}"


class PointOfDiversion(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    water_right = models.ForeignKey(WaterRight, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=200)
    location = models.PointField(srid=4326)
    rediverted_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rediversions",
        help_text="Upstream point of diversion this point re-diverts from "
        "(one hop; the return-flow source).",
    )
    stream_name = models.CharField(max_length=200, blank=True)
    source_flowline = models.ForeignKey(
        "geography.Flowline",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="diversions",
        help_text="Waterway (NHD or canal) this diversion is on, for provenance. "
        "stream_name stays the human-readable eWRIMS label.",
    )
    max_rate_cfs = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    notes = models.TextField(blank=True)

    # --- Canal losses (146-03 Task 3): three shares of the water diverted
    # that never reach a field, each with the band the district states.
    # Defaults are the design-implications document's own (2026-09-18,
    # convention 4): 0.01 for evaporation (about 1 percent, near-universal),
    # 0 for seepage and spill (not stated, rather than guessing a district's
    # figure). Phase 148 rules on who owns each share and what value is
    # right for a given canal; Phase 149's engine is the first thing that
    # computes with them. Nothing here does.
    LOSS_BASIS_CHOICES = [
        ("measured", "Measured"),
        ("district_estimate", "District estimate"),
        ("default", "Default (not district-specific)"),
    ]
    CONTRACT_UNIT_CHOICES = [
        ("cfs", "Cubic feet per second (cfs)"),
        ("miners_inch", "Miner's inch"),
        ("gpm", "Gallons per minute (gpm)"),
        ("acre_feet_per_day", "Acre-feet per day"),
    ]

    evaporation_fraction = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0.0100"),
        help_text="Share of the diverted volume lost to evaporation off the "
        "canal, about 1 percent by convention. An agency's own measured or "
        "district figure replaces this default.",
    )
    seepage_fraction = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0"),
        help_text="Share of the diverted volume lost to canal seepage. "
        "Defaults to 0 (not stated) rather than guessing a district's figure.",
    )
    spill_fraction = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0"),
        help_text="Share of the diverted volume that spills downstream, "
        "re-diverted at the point spill_device or rediverted_from names. "
        "Defaults to 0 (not stated).",
    )
    evaporation_band_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="The district's stated uncertainty; blank when none is "
        "stated; never a model spread.",
    )
    seepage_band_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="The district's stated uncertainty; blank when none is "
        "stated; never a model spread. Turlock publishes seepage at ±35%.",
    )
    spill_band_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="The district's stated uncertainty; blank when none is "
        "stated; never a model spread.",
    )
    loss_basis = models.CharField(
        max_length=20,
        choices=LOSS_BASIS_CHOICES,
        default="default",
        help_text="How the three shares above were set: measured on this "
        "canal, a district estimate, or this platform's own default.",
    )
    spill_device = models.ForeignKey(
        "MeasuringDevice",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="spill_points",
        help_text="Spill measured at the terminus where a device exists.",
    )

    # --- The 145-01 memo's crosswalk layer (146-03 Task 3): a local alias
    # and the contract unit a ditch company's own book uses, so a bulk
    # import (a later task) can resolve a headgate by the name the ditch
    # tender actually uses rather than only this platform's own name.
    local_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="The ditch tender's own name for this point, such as a "
        "headgate, a run or a turnout. Shown as \"known locally as\" beside "
        "the point's own name when set.",
    )
    contract_unit = models.CharField(
        max_length=20,
        choices=CONTRACT_UNIT_CHOICES,
        blank=True,
        help_text="The unit the operator's own delivery record is kept in, "
        "when it is not cfs.",
    )
    miners_inch_gpm = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("11.22"),
        help_text="The statute's 11.22 gallons a minute, unless the "
        "district's own contract says 10 or 9.",
    )

    def clean(self):
        """Reject canal losses that claim more than the whole diverted.

        Model.save() never calls this (the form is the entry boundary and
        carries the same check as a readable field error), but a guard
        belongs on the model too -- any future caller that builds a POD
        outside the form gets the same protection.
        """
        super().clean()
        fractions = [
            f
            for f in (
                self.evaporation_fraction,
                self.seepage_fraction,
                self.spill_fraction,
            )
            if f is not None
        ]
        if fractions and sum(fractions) > 1:
            raise ValidationError(
                "Evaporation, seepage and spill together cannot exceed the "
                "whole of what was diverted."
            )

    def _loss_display(self, fraction, band_percent):
        """'12.00%' or '12.00% ±35%' -- convention 11: the band is the

        district's stated uncertainty, never a model spread, and is shown
        beside the figure only when one was actually given.
        """
        percent = (fraction or Decimal("0")) * 100
        text = f"{percent:.2f}%"
        if band_percent is not None:
            text += f" ±{band_percent:.2f}%"
        return text

    def evaporation_display(self):
        return self._loss_display(self.evaporation_fraction, self.evaporation_band_percent)

    def seepage_display(self):
        return self._loss_display(self.seepage_fraction, self.seepage_band_percent)

    def spill_display(self):
        return self._loss_display(self.spill_fraction, self.spill_band_percent)

    def __str__(self):
        return self.name


class PointOfDiversionParcel(models.Model):
    point_of_diversion = models.ForeignKey(
        PointOfDiversion, on_delete=models.CASCADE, related_name="pod_parcels"
    )
    parcel = models.ForeignKey(
        "parcels.Parcel", on_delete=models.CASCADE, related_name="pod_parcels"
    )
    fraction = models.DecimalField(max_digits=5, decimal_places=4, default=1.0)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = [("point_of_diversion", "parcel")]

    def __str__(self):
        return f"{self.point_of_diversion} → {self.parcel} ({self.fraction})"


class IrrigationMethod(models.Model):
    """One row of a published irrigation-efficiency table (146-05 Task 1, S1).

    Seeded by a data migration (``0016_seed_irrigation_methods``), not a seed
    command, so every deployment carries the same rows after ``migrate``: East
    Turlock Subbasin GSA's Section 4.05 table, 18 rows counted off the PDF on
    2026-09-23. It lives in ``surface`` for the reason the agency-wide
    efficiency does: nothing reads an efficiency where there is no canal.
    Nothing reads this one yet either; Phase 148 decides what the engine does
    with it.
    """

    name = models.CharField(max_length=100, unique=True)
    assigned_efficiency = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        help_text="The share of applied water the table assigns this method, "
        "as a fraction (0.600 is 60%).",
    )
    range_low = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        help_text="Low end of the table's published range, as a fraction.",
    )
    range_high = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        help_text="High end of the table's published range, as a fraction.",
    )
    source = models.CharField(
        max_length=300,
        help_text="The published table this row is copied from.",
    )
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def percent(self):
        """The assigned efficiency as a whole percent: 0.600 -> 60."""
        return int((self.assigned_efficiency * 100).to_integral_value())

    def __str__(self):
        return f"{self.name}, {self.percent()}%"


class ParcelIrrigationMethod(models.Model):
    """How one use area is irrigated (146-05 Task 1, S1); no row means not set.

    A ``surface`` row rather than a ``Parcel.irrigation_method`` column, which
    is what the plan named: ``parcels`` stays installed when ``surface`` is
    dropped, and a column there pointing into ``surface`` would leave a
    dangling reference that stops ``migrate`` on every deployment without it
    (rule 1 of the composition rule, ``core/modules.py``). Pointing this way,
    the row leaves with ``surface``, like ``WaterRightParcel`` above.
    ``surface/services.py`` does not read it this phase.
    """

    parcel = models.OneToOneField(
        "parcels.Parcel", on_delete=models.CASCADE, related_name="irrigation"
    )
    method = models.ForeignKey(
        IrrigationMethod, on_delete=models.PROTECT, related_name="use_areas"
    )

    def __str__(self):
        return f"{self.parcel} → {self.method}"


class WaterAccountDeliveryPoint(models.Model):
    """Which point of diversion delivers to an account (146-05 Task 3, Q8).

    A ``surface`` row rather than a ``delivery_pod`` column on
    ``accounting.WaterAccount``, for the same reason ``ParcelIrrigationMethod``
    is a `surface` row rather than a `Parcel` column (146-05 Task 1):
    ``accounting`` is schema-resident and ``surface`` is truly removable, so a
    column on ``WaterAccount`` pointing into ``surface`` would dangle on every
    deployment without `surface` (rule 1, `core/modules.py`) and
    `SCHEMA_EXCEPTIONS` cannot excuse it -- `test_record_target_keeps_its_schema`
    requires an excepted target to keep its schema, and `surface`'s tables
    actually go. Pointing this way, the row leaves with `surface`, and the
    arrow (`surface` -> `accounting`) is one `surface.requires` already
    declares.

    One row per account (``OneToOneField``); no row means the account is not
    delivered through a point of diversion. It may still carry
    ``WaterAccount.delivery_well`` -- ``wells`` is schema-resident, so that
    arrow is safe and lives as a ``SCHEMA_EXCEPTIONS`` record instead, the same
    shape as ``drinking.SystemFacility.well``. ``WaterAccountForm`` refuses
    setting both; ``WaterAccount.clean()`` carries the same check for callers
    outside the form.
    """

    account = models.OneToOneField(
        "accounting.WaterAccount",
        on_delete=models.CASCADE,
        related_name="surface_delivery_point",
    )
    point_of_diversion = models.ForeignKey(
        PointOfDiversion, on_delete=models.PROTECT, related_name="delivery_accounts"
    )

    def __str__(self):
        return f"{self.account} → {self.point_of_diversion}"


class MeasuringDevice(models.Model):
    """A measuring or recording device under 23 CCR 934(b)(1) (146-03 Task 1).

    Current section 934(b)(1) governs Water Year 2027 onward (October 1,
    2026); the 2016 analogue (23 CCR 937) is not modelled on this table. Never
    a subclass of ``measurements.Meter``: that table is the well's meter
    registry, and a diversion device is a different regulatory object with
    different fields; merging them would put 934(b) columns on every well
    meter. Which point of diversion carries this device, and when, is
    ``PointOfDiversionDevice`` below (mirroring ``wells.WellMeter``), because a
    device can be replaced and the history has to stay.
    """

    DEVICE_TYPE_CHOICES = [
        ("inline_flow_meter", "Inline flow meter"),
        ("submerged_orifice_gate", "Submerged orifice gate"),
        ("rectangular_weir", "Rectangular weir"),
        ("v_notch_weir", "V-notch weir"),
        ("broad_crested_weir", "Broad-crested weir"),
        ("rated_gate", "Rated gate"),
        ("staff_gage_rating", "Staff gage rating"),
        ("other", "Other"),
    ]
    MEASURED_PARAMETER_CHOICES = [
        ("flow_rate", "Flow rate"),
        ("volume", "Volume"),
        ("stage", "Stage"),
        ("other", "Other"),
    ]
    STATUS_CHOICES = [
        ("active", "Active"),
        ("removed", "Removed"),
    ]

    nickname = models.CharField(
        max_length=100,
        blank=True,
        help_text="This platform's own name for the device, shown in place of "
        "make and model wherever one is set. Not a 934(b) field.",
    )
    device_type = models.CharField(
        max_length=30,
        choices=DEVICE_TYPE_CHOICES,
        help_text="934(b)(1)(C): type of measuring device. The state's own "
        "list is inline flow meters, submerged orifice gates, rectangular "
        "weirs, v-notch weirs and broad crested weirs; rated gate and staff "
        "gage rating are added here as common devices that list does not "
        "name, and Other covers anything else.",
    )
    make = models.CharField(
        max_length=100,
        blank=True,
        help_text="934(b)(1)(B): make and model number of the measuring device.",
    )
    model_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="934(b)(1)(B): make and model number of the measuring device.",
    )
    recording_make = models.CharField(
        max_length=100,
        blank=True,
        help_text="934(b)(1)(E): make, model number and type of the recording "
        "device, if different from the measuring device.",
    )
    recording_model = models.CharField(
        max_length=100,
        blank=True,
        help_text="934(b)(1)(E): make, model number and type of the recording "
        "device, if different from the measuring device.",
    )
    recording_type = models.CharField(
        max_length=100,
        blank=True,
        help_text="934(b)(1)(E): make, model number and type of the recording "
        "device, if different from the measuring device.",
    )
    measured_parameter = models.CharField(
        max_length=20,
        choices=MEASURED_PARAMETER_CHOICES,
        blank=True,
        help_text="934(b)(1)(F): measured parameter and associated units of "
        "the raw device output.",
    )
    raw_units = models.CharField(
        max_length=30,
        blank=True,
        help_text="934(b)(1)(F): measured parameter and associated units of "
        "the raw device output.",
    )
    accuracy_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="934(b)(1)(G): accuracy of the measurement data, as a percentage.",
    )
    installed_on = models.DateField(
        null=True,
        blank=True,
        help_text="934(b)(1)(H): date of installation.",
    )
    installer_contact = models.CharField(
        max_length=200,
        blank=True,
        help_text="934(b)(1)(I): contact information for the qualified "
        "individual who installed and verified the accuracy of the measuring "
        "device.",
    )
    last_evidence_on = models.DateField(
        null=True,
        blank=True,
        help_text="934(d): date of the calibration report, certification or "
        "field test that stands as this device's evidence of proper "
        "functioning, due on or before the first annual report after "
        "installation and at least once every five years after that.",
    )
    state_device_id = models.CharField(
        max_length=50,
        blank=True,
        help_text="The number the state's own registry generates for this "
        "device, once filed there. Not itself a 934(b) field.",
    )
    location = models.PointField(
        srid=4326,
        null=True,
        blank=True,
        help_text="934(b)(1)(D): location of the measuring device, when it "
        "sits apart from the point of diversion it is linked to below.",
    )
    water_rights = models.ManyToManyField(
        WaterRight,
        blank=True,
        related_name="measuring_devices",
        help_text="934(b)(1)(A): identification number of each claimed water "
        "right that uses the measuring device or recording device.",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.nickname:
            return self.nickname
        parts = [p for p in (self.make, self.model_number) if p]
        return " ".join(parts) if parts else f"Measuring device {self.pk}"

    def accuracy_display(self):
        """'±5.00% by the device's stated accuracy' (934(b)(1)(G)), or
        the plain statement that none was given."""
        if self.accuracy_percent is None:
            return "no accuracy stated"
        return f"±{self.accuracy_percent:.2f}% by the device's stated accuracy"

    def needs_evidence(self):
        """True when 934(d)'s five-year evidence window is blank or has passed."""
        if self.last_evidence_on is None:
            return True
        try:
            due = self.last_evidence_on.replace(
                year=self.last_evidence_on.year + 5
            )
        except ValueError:
            # Feb 29 with no Feb 29 five years later.
            due = self.last_evidence_on.replace(
                month=2, day=28, year=self.last_evidence_on.year + 5
            )
        return date.today() >= due


class PointOfDiversionDevice(models.Model):
    """Which measuring device sits on a point of diversion, and when.

    Mirrors ``wells.WellMeter``'s shape: the point-device relationship is its
    own table rather than a FK on ``PointOfDiversion`` because a device gets
    replaced: the history stays, and ``is_current`` says which link the POD
    page's device panel reads.
    """

    point_of_diversion = models.ForeignKey(PointOfDiversion, on_delete=models.CASCADE)
    device = models.ForeignKey(MeasuringDevice, on_delete=models.CASCADE)
    installed_on = models.DateField(null=True, blank=True)
    removed_on = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=True)

    class Meta:
        unique_together = [("point_of_diversion", "device")]

    def __str__(self):
        return f"{self.point_of_diversion} - {self.device}"


class DiversionRecord(models.Model):
    DIVERSION_TYPE_CHOICES = [
        ("direct_use", "Direct Use"),
        ("to_storage", "To Storage"),
    ]
    #: How this record's number is known, in the state's own vocabulary
    #: (146-03 Task 2). Blank means "not stated" -- most existing rows, and
    #: any newly-entered one where the operator hasn't said, land here rather
    #: than guessing a method the operator never named.
    METHOD_CHOICES = [
        ("device", "A measuring device"),
        ("methodology", "A measurement methodology on file"),
        ("alternative_compliance", "An alternative compliance plan (for example remote sensing)"),
        ("apportioned", "Apportioned from a shared aggregate, 934(a)(8)"),
        ("below_threshold", "Under 10 acre-feet a year: no standard applies"),
        ("outage_estimate", "Estimated during a device outage, 937(b)(4)"),
        ("estimated_from_use", "Estimated forward from use (Phase 149's estimator)"),
    ]
    #: 931(s) and 931(j)(3): raw device output, provisional (not yet quality
    #: assured or apportioned), and non-provisional. Only non-provisional data
    #: may go in an annual report.
    DATA_STATE_CHOICES = [
        ("raw", "Raw"),
        ("provisional", "Provisional"),
        ("non_provisional", "Non-provisional"),
    ]

    point_of_diversion = models.ForeignKey(PointOfDiversion, on_delete=models.CASCADE)
    reporting_period = models.ForeignKey(
        "accounting.ReportingPeriod", on_delete=models.SET_NULL, null=True, blank=True
    )
    month = models.DateField()
    volume_acre_feet = models.DecimalField(max_digits=12, decimal_places=4)
    returned_af = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        default=Decimal("0"),
        help_text="Agency-asserted acre-feet of this diversion returned to the "
        "stream (0 = fully consumed; = full volume for non-consumptive / "
        "hydropower passthrough).",
    )
    max_flow_rate_cfs = models.DecimalField(
        max_digits=10, decimal_places=4, null=True, blank=True
    )
    diversion_type = models.CharField(
        max_length=50, choices=DIVERSION_TYPE_CHOICES, default="direct_use"
    )
    method = models.CharField(
        max_length=30,
        choices=METHOD_CHOICES,
        blank=True,
        help_text="How this number is known, in the state's own words (Water "
        "Code 5002(b): 'the method of measurement used'). Blank means not "
        "stated.",
    )
    device = models.ForeignKey(
        MeasuringDevice,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The measuring device behind this record's number, when "
        "method is 'a measuring device'.",
    )
    data_state = models.CharField(
        max_length=20,
        choices=DATA_STATE_CHOICES,
        default="provisional",
        help_text="931(s) and 931(j)(3): raw, provisional or non-provisional. "
        "Only non-provisional data goes in an annual report.",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-month"]
        unique_together = [("point_of_diversion", "month", "diversion_type")]

    #: The first month the 2026 rewrite (23 CCR 934) governs -- Water Year
    #: 2027 opens October 1, 2026. Every earlier month is still Water Year
    #: 2026 or before, governed by the preserved 2016 text (23 CCR 937).
    _REWRITE_STARTS = date(2026, 10, 1)

    @property
    def rule_version(self):
        """Which measurement rule governs this record's month.

        Derived from ``month`` on every read, never stored: a platform
        carrying multi-year history needs the rule version attached to the
        record so an old compliance state is never re-evaluated under the
        wrong test (research file 05, section on accuracy semantics). The
        2016 rule (23 CCR 937) governs Water Year 2026 and earlier; the 2026
        rewrite (23 CCR 934) governs from Water Year 2027, October 1, 2026.
        """
        if self.month is None:
            return ""
        if self.month >= self._REWRITE_STARTS:
            return "2026 rewrite (23 CCR 934)"
        return "2016 rule (23 CCR 937)"

    def consumed_acre_feet(self):
        """The consumed magnitude of this diversion: abs(volume) − returned.

        Single source of truth for every ledger writer. Returned water (hydro
        passthrough, return flow) is withheld here so only the consumed portion
        ever reaches ``net_consumptive_use_af``. ``abs`` because surface
        diversions are stored negative by production convention.
        """
        return abs(self.volume_acre_feet) - self.returned_af

    def is_non_consumptive(self):
        """True when the full diverted volume is returned to the stream.

        A hydropower / run-of-river passthrough returns everything it takes, so
        its consumed magnitude is zero — the detail page labels it
        "Non-consumptive (returned to stream)" to distinguish it from an ordinary
        irrigation diversion that consumes what it diverts.
        """
        return self.returned_af > 0 and self.consumed_acre_feet() == 0

    def is_partial_return(self):
        """True when SOME but not all of the diverted volume is returned."""
        return Decimal("0") < self.returned_af < abs(self.volume_acre_feet)

    def clean(self):
        """Reject a return flow larger than the diverted volume.

        A typo where returned > diverted would make ``consumed`` negative and
        flip the consumptive spine the wrong way, so guard it at the model.
        """
        super().clean()
        if (
            self.returned_af is not None
            and self.volume_acre_feet is not None
            and self.returned_af > abs(self.volume_acre_feet)
        ):
            raise ValidationError(
                {"returned_af": "Return flow cannot exceed the diverted volume."}
            )

    def method_display(self):
        """The "How known" column's method label, "Not stated" when blank.

        ``get_method_display()`` returns "" for a blank CharField (the seven
        choices are the state's own vocabulary, not an "operator didn't say"
        entry) -- this is the one place that turns that blank into the word
        a reader sees.
        """
        return self.get_method_display() if self.method else "Not stated"

    def __str__(self):
        return f"{self.point_of_diversion} {self.month}: {self.volume_acre_feet} AF"


class CurtailmentOrder(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("expired", "Expired"),
        ("rescinded", "Rescinded"),
    ]

    order_id = models.CharField(max_length=50, unique=True)
    title = models.CharField(max_length=300)
    effective_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    watershed = models.CharField(
        max_length=200,
        blank=True,
        help_text="As the order names it; matched against a right's watershed or source name.",
    )
    priority_date_cutoff = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.order_id


class UnallocatedDelivery(models.Model):
    """Delivered surface water that no served parcel's crop demand can explain.

    T4 (math eval 2026-07-18). When a POD's delivery for a month exceeds what the
    served parcels could beneficially use (each capped at demand / irrigation
    efficiency), the allocator hands out the caps and the remainder used to go
    nowhere: no ledger row, no pool, no log. The internal ledger then disagreed
    with the DiversionRecord that CalWATRS files from, and district conservation
    silently failed to balance.

    The surplus is recorded HERE rather than on a parcel because that is the
    honest statement: the water was delivered, and crop demand does not account
    for it. Attributing it to parcels would claim consumption the ET data
    contradicts; crediting it to the basin pool would assume percolation nobody
    measured. In practice a non-zero value is usually a data-quality signal — an
    overstated diversion, understated ET, or real non-crop use (spill, stock,
    a recharge basin) that should be recorded as such.

    ``ParcelLedger`` cannot hold this: its ``parcel`` FK is not nullable, and
    making it nullable to fit one parcel-less case would weaken every ledger
    query. A surplus belongs to the point of diversion, not to a parcel.
    """

    point_of_diversion = models.ForeignKey(
        "surface.PointOfDiversion", on_delete=models.CASCADE
    )
    reporting_period = models.ForeignKey(
        "accounting.ReportingPeriod",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    month = models.DateField(help_text="First of the month this surplus arose in.")
    amount_acre_feet = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="Positive magnitude of delivered water not explained by demand.",
    )
    delivery_acre_feet = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        help_text="The month's total consumed delivery, for context.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-month", "point_of_diversion_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["point_of_diversion", "month"],
                name="unallocated_delivery_one_per_pod_month",
            ),
            models.CheckConstraint(
                check=models.Q(amount_acre_feet__gt=0),
                name="unallocated_delivery_amount_positive",
            ),
        ]
        verbose_name_plural = "unallocated deliveries"

    def __str__(self):
        return (
            f"{self.point_of_diversion} {self.month:%Y-%m}: "
            f"{self.amount_acre_feet} AF unallocated"
        )
