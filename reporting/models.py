# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Reporting models.

The state-filing layer. ReportingProfile carries the agency's GEARS filing
identity and certifier of record; ReportTemplate defines each report kind
(GEARS extraction, CalWATRS diversion); ReportSubmission is a single generated
report and its workflow status (draft/review/finalized — never a claim the
State Water Board accepted anything). ReportingCrosswalk maps internal fields
to the columns the state portals expect.
"""
from django.conf import settings
from django.contrib.gis.db import models

from core.history import track_changes


class ReportingProfile(models.Model):
    """The agency's state-issued filing identity and certifier of record.

    These values are NOT credentials OpenH2O uses to talk to the state. There
    is no API. A human logs into the GEARS and CalWATRS web portals and files
    by hand. The fields here are the identity tokens the state MAILS to the
    agency, transcribed so reports can be pre-addressed and the right person
    can be reminded who signs:

      - gears_correspondence_id: the Correspondence ID SWRCB mails to bind a
        GEARS account to an extractor/property. The human supplies it; OpenH2O
        only stores it. (CalWATRS PINs are issued per water right and live on
        surface.WaterRight, not here.)
      - certifier_*: the person who will swear the filing in the state portal
        under penalty of perjury (Water Code 5107). OpenH2O never certifies on
        anyone's behalf.

    Single-tenant deployment: one profile represents the one agency, optionally
    linked to the geography.Boundary that stands for its area. A district that
    holds several distinct GEARS extractors (and thus several Correspondence
    IDs) is a documented simplification of this single-field model.
    """

    boundary = models.OneToOneField(
        "geography.Boundary",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reporting_profile",
        help_text="The geography.Boundary representing this agency's area.",
    )
    legal_entity_name = models.CharField(
        max_length=255,
        help_text="Legal name of the agency as it appears on state filings.",
    )
    gears_correspondence_id = models.CharField(
        max_length=100,
        blank=True,
        help_text="Correspondence ID mailed by SWRCB to bind the GEARS account. "
        "Enter it here.",
    )
    certifier_name = models.CharField(
        max_length=200,
        blank=True,
        help_text="Person who certifies filings in the state portal under penalty of perjury.",
    )
    certifier_title = models.CharField(max_length=200, blank=True)
    certifier_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.legal_entity_name


class ReportTemplate(models.Model):
    REPORT_TYPE_CHOICES = [
        ("gears_by_well", "GEARS by Well"),
        ("gears_by_et", "GEARS by ET"),
        ("calwatrs_a1", "CalWATRS A1"),
        ("calwatrs_a2", "CalWATRS A2"),
    ]

    name = models.CharField(max_length=200)
    report_type = models.CharField(max_length=50, unique=True, choices=REPORT_TYPE_CHOICES)
    description = models.TextField(blank=True)
    template_version = models.CharField(max_length=20, default="1.0")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


@track_changes()
class ReportSubmission(models.Model):
    """A report OpenH2O prepared for a filing the user makes themselves.

    No status here means the State Water Board received or accepted anything.
    OpenH2O cannot submit to GEARS or CalWATRS — there is no intake API. The
    lifecycle tracks the agency's own internal progress toward a hand-filing:

      draft               -> generated, not yet signed off internally
      internally_approved -> the GSA/agency approved it for filing (internal)
      exported            -> the user marked the file downloaded or the worksheet opened
      filed               -> the user recorded that THEY filed and certified it
                             in the state portal (self-reported bookkeeping)

    `filed_at`, `certified_by`, and `state_confirmation_number` are the user's
    own record of a filing they performed and certified in person; they are not
    a confirmation from OpenH2O to the state.
    """

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("internally_approved", "Internally Approved"),
        ("exported", "Exported"),
        ("filed", "Filed at State"),
    ]

    report_template = models.ForeignKey(ReportTemplate, on_delete=models.PROTECT)
    reporting_period = models.ForeignKey(
        "accounting.ReportingPeriod", on_delete=models.PROTECT
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    generated_file = models.CharField(max_length=500, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    filed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the user recorded that they filed this in the state portal.",
    )
    certified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="User who recorded certifying this filing in the state portal.",
    )
    state_confirmation_number = models.CharField(
        max_length=100,
        blank=True,
        help_text="Confirmation number the state portal returned to the user after filing.",
    )
    internal_notes = models.TextField(
        blank=True,
        help_text="Internal GSA/agency sign-off notes. Not a Water Board reviewer's notes.",
    )
    prefill_overrides = models.JSONField(
        default=dict,
        blank=True,
        help_text="User-edited OpenET pre-fill values, keyed by entity+month "
        "(e.g. 'well:12:2024-03'). These are the agency's reviewed figures for "
        "data entry. Only the Prepare with OpenET page shows them.",
    )
    validation_warnings = models.JSONField(default=list, blank=True)
    method_name = models.CharField(
        "methodology",
        max_length=200,
        blank=True,
        help_text="Recorded when the file was made: the methodology behind the report's "
        "calculated months. Blank when there were none or more than one.",
    )
    settings_code = models.CharField(
        "methodology settings code",
        max_length=12,
        blank=True,
        help_text="The 12-character settings code of that methodology.",
    )
    method_count = models.PositiveSmallIntegerField(
        "number of methodologies",
        null=True,
        blank=True,
        help_text="How many methodologies the water year's calculated months came from. "
        "Blank on a report made before OpenH2O recorded it.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.report_template.report_type} - {self.reporting_period}"

    def record_method(self):
        """Set the methodology behind the water year's calculated months, as they stand now.

        The rule a filed figure's method uses (``accounting.statements.method_pairs``):
        one methodology names it; none or more than one leaves the name and code blank,
        and ``method_count`` says which. Called once, when the file is made, so the
        record names the methodology behind the file's own figures and keeps it after
        an open year is calculated again under another. Marking the report filed
        leaves it as it is: the file was not made again.
        """
        from accounting.models import CalculationRun
        from accounting.statements import method_pairs

        pairs = method_pairs(CalculationRun.objects.all(), self.reporting_period)
        self.method_count = len(pairs)
        self.method_name, self.settings_code = next(iter(pairs)) if len(pairs) == 1 else ("", "")


class ReportingCrosswalk(models.Model):
    report_template = models.ForeignKey(ReportTemplate, on_delete=models.CASCADE)
    internal_field = models.CharField(max_length=100)
    external_field = models.CharField(max_length=100)
    transform = models.CharField(max_length=200, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        unique_together = [("report_template", "internal_field")]

    def __str__(self):
        return f"{self.report_template}: {self.internal_field} → {self.external_field}"
