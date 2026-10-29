# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Core models.

Cross-cutting models shared by every app. User is the custom AUTH_USER_MODEL
('core.User') and the home of the two-tier is_administrator access rule;
SiteConfig holds the single agency's deployment-wide settings,
including demonstration_mode.
"""
from decimal import Decimal

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core.constants import RECOVERY_HORIZON_CHOICES
from core.history import track_changes


# Only who a person is and what they may do. The password hash and the last
# login time change without anyone changing a figure, and are not history.
@track_changes(
    fields=(
        "username",
        "first_name",
        "last_name",
        "email",
        "is_active",
        "is_staff",
        "is_superuser",
        "agency_admin",
        "read_only",
    )
)
class User(AbstractUser):
    agency_admin = models.BooleanField(default=False)
    # The third role: a Viewer signs in and reads every page but
    # changes nothing. Enforced for every unsafe request by
    # core.access.ReadOnlyMiddleware, whatever ACCESS_CONTROL_ENFORCED says,
    # because a viewer is an explicit assignment, not a deployment posture.
    read_only = models.BooleanField(default=False, verbose_name="Viewer (read only)")
    phone = models.CharField(max_length=20, blank=True)
    title = models.CharField(max_length=100, blank=True)
    # An administrator set this person's password (Add user, or Set
    # temporary password). core.access.MustChoosePasswordMiddleware sends them
    # to the Choose a new password page until they replace it. Not in the
    # tracked fields above: like the password hash, it is not a change of who
    # a person is or what they may do.
    must_choose_password = models.BooleanField(default=False)

    def clean(self):
        super().clean()
        if self.read_only and (self.agency_admin or self.is_staff):
            raise ValidationError(
                "A viewer cannot also be an administrator. Choose one role."
            )

    @property
    def can_write(self):
        """True for an active account that is not a viewer."""
        return bool(self.is_active and not self.read_only)

    @property
    def role_label(self):
        """The one role word the Users screen shows for this account.

        Read from the role flags alone: whether the account is active is a
        separate column on that screen.
        """
        if self.is_staff or self.agency_admin:
            return "Administrator"
        if self.read_only:
            return "Viewer"
        return "Operator"

    @property
    def is_administrator(self):
        """The single rule for "elevated" access (two-tier model).

        An administrator is an active user who is either Django staff/superuser
        OR carries agency_admin=True. is_staff ALWAYS implies administrator, so
        the deployed superuser (ensure_superuser sets is_staff=True) can never be
        locked out when the access-control switch flips on. See core.access for
        the switch-aware decorator that enforces this.
        """
        return bool(self.is_active and (self.is_staff or self.agency_admin))


@track_changes()
class SiteConfig(models.Model):
    agency_name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=50, default="America/Los_Angeles")
    native_srid = models.IntegerField(verbose_name="Native coordinate system (SRID)", default=4326)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True, null=True)
    allow_google_oauth = models.BooleanField(verbose_name="Allow Google sign-in", default=False)
    demonstration_mode = models.BooleanField(
        default=False,
        help_text="When Demonstration mode is on, every page shows the "
        "demonstration notice, and the first line of a ledger export says the "
        "file comes from the demonstration. Loading the demonstration data "
        "turns it on. Leave it on for as long as the demonstration data is on "
        "the site.",
    )

    # --- Agency-wide delivery accounting policy ---
    # Efficiency is agronomic, not per-right: one agency-wide figure. Lifts the
    # hardcoded seed constant IRRIGATION_EFFICIENCY out of code so an agency can
    # tune it from the Delivery Settings screen.
    default_irrigation_efficiency = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=Decimal("0.750"),
        help_text="The default irrigation efficiency, for a field with no irrigation method on file.",
    )

    # What a canal delivery that
    # went beyond what its field's crop could use does to the numbers. Belongs
    # to `surface` -- only canal water can be over-delivered, so
    # DeliverySettingsForm shows and saves both fields under its
    # `shows_surface_settings` gate. `run_calculations`
    # is the one reader; nothing here reaches the engine directly.
    #: Every value a month's calculation has ever been stamped with. A run
    #: written when "credited" was offered still reads "credited"; nothing
    #: offers or applies it now.
    OVER_DELIVERY_TREATMENT_CHOICES = [
        ("not_credited", "Not credited to anyone"),
        ("credited", "Credited to the landowner, less a share left in the basin"),
        ("named_line", "Shown on the field's page as its own line"),
    ]
    #: What a site can choose now.
    OVER_DELIVERY_TREATMENT_OFFERED = [
        ("not_credited", "Not credited to anyone"),
        ("named_line", "Shown on the field's page as its own line"),
    ]
    over_delivery_treatment = models.CharField(
        max_length=20,
        choices=OVER_DELIVERY_TREATMENT_OFFERED,
        default="not_credited",
        help_text="What happens to surface water in excess of ETAW on the "
        "month's calculation: not credited to anyone (the default), or shown "
        "as its own line that is not a credit.",
    )
    over_delivery_leave_behind = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=Decimal("0.100"),
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text="OpenH2O leaves this share of the water it credits from a "
        "recharge event or from canal seepage in the basin, credited to no one. "
        "Enter it as a fraction: the default, 0.100, is 10 percent.",
    )
    #: What happens to the water a canal loses to seepage. Belongs to `surface`
    #: (DeliverySettingsForm shows it under the same gate). The pool row the
    #: seepage adds to the basin stays whatever is chosen; this decides whether
    #: any water account is credited too.
    CANAL_SEEPAGE_CREDIT_CHOICES = [
        ("none", "Credited to no one"),
        ("by_acre", "Shared by acre among the fields the canal serves"),
        ("owner", "Credited to the canal's owner only"),
    ]
    canal_seepage_credit = models.CharField(
        max_length=10,
        choices=CANAL_SEEPAGE_CREDIT_CHOICES,
        default="none",
        help_text="Whether a canal's seepage is credited to water accounts. "
        "Credited to no one (the default) leaves it in the basin's water budget "
        "alone. Shared by acre credits the accounts of the fields the canal "
        "serves, and the owner choice credits the account named on the canal's "
        "headgate. Both choices leave the Share left in the basin out of the credit.",
    )

    # There is no separate groundwater efficiency: there is one irrigation
    # efficiency per field. run_calculations divides by parcels.services.field_efficiency,
    # which falls back to default_irrigation_efficiency above.
    # The agency-wide default for what happens to an unused allocation at
    # year-end. A district may override it on its Zone; this default must always
    # resolve to a concrete value (never null), so existing rollover behavior is
    # preserved on migrate (carry_forward = the historic behavior).
    default_recovery_horizon = models.CharField(
        max_length=16,
        choices=RECOVERY_HORIZON_CHOICES,
        default="carry_forward",
        help_text="What happens to a zone's unused allocation at year-end. An "
        "administrator can set a different choice for one zone on that zone's page.",
    )

    # --- Diversion records: the crosswalk layer for the state's Water Use
    # Reported file. These fields belong to `surface`: DeliverySettingsForm shows
    # the report-year rule only when `surface` is enabled, the import screen
    # writes the use-type rule, and the bulk diversion importer
    # (surface/diversion_import.py) is the only reader -- nothing here reaches
    # the accounting engine.
    DIVERSION_USE_TYPE_RULE_CHOICES = [
        ("drop", "Ignore USE rows"),
        ("returned", "USE minus DIRECT is the returned volume"),
        ("as_direct", "Treat USE as direct use"),
    ]
    DIVERSION_REPORT_YEAR_RULE_CHOICES = [
        ("water_year", "Water year (October to September)"),
        ("calendar_year", "Calendar year (January to December)"),
        ("season", "A single irrigation season each year"),
    ]

    diversion_use_type_rule = models.CharField(
        max_length=20,
        choices=DIVERSION_USE_TYPE_RULE_CHOICES,
        default="drop",
        help_text="What a USE row in the state's Water Use Reported file "
        "means here.",
    )
    diversion_report_year_rule = models.CharField(
        max_length=20,
        choices=DIVERSION_REPORT_YEAR_RULE_CHOICES,
        default="water_year",
        help_text="How a YEAR and MONTH in the state's Water Use Reported "
        "file become a calendar month.",
    )
    season_start_month = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="The month (1-12) this deployment's irrigation season "
        "starts. Used only when the report year rule above is a season.",
    )

    # --- Water year ---
    # The first month of the water year. One setting, read by every place that
    # decides which water year a month belongs to, and by the finalized-year
    # lock in the database (accounting/locks.py).
    water_year_start_month = models.PositiveSmallIntegerField(
        default=10,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        verbose_name="water year start month",
        help_text="Enter a month number from 1 to 12. The default is 10, "
        "October. A year that starts in January is named by its "
        "calendar year.",
    )

    # --- Persistent identifiers ---
    # The ONE stored piece of the identifier scheme; the identifiers themselves
    # are derived on read (core/identifiers.py), so they cannot drift from the
    # records they name. Blank means "this site's own address". A value may
    # carry a path as well as a host ("geoconnex.us/<namespace>"), so a
    # deployment that registers with Geoconnex can publish the geoconnex.us
    # address itself as every record's @id.
    identifier_host = models.CharField(
        max_length=200,
        blank=True,
        help_text="The host your persistent identifiers are published under. "
        "Leave blank to use this site's own address. Set it before "
        "registering with Geoconnex so the addresses never change.",
    )

    def save(self, *args, **kwargs):
        if self.pk is None and SiteConfig.objects.exists():
            raise ValidationError("Only one SiteConfig instance is allowed.")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.agency_name
