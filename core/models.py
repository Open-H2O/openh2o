# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Core models.

Cross-cutting models shared by every app. User is the custom AUTH_USER_MODEL
('core.User') and the home of the two-tier is_administrator access rule
(ISS-021); SiteConfig holds the single agency's deployment-wide settings,
including demonstration_mode. Role/UserRole are a deprecated, dormant RBAC
scheme kept only to avoid a destructive migration — do not build on them.
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
    )
)
class User(AbstractUser):
    agency_admin = models.BooleanField(default=False)
    phone = models.CharField(max_length=20, blank=True)
    title = models.CharField(max_length=100, blank=True)

    @property
    def is_administrator(self):
        """The single rule for "elevated" access (ISS-021, two-tier model).

        An administrator is an active user who is either Django staff/superuser
        OR carries agency_admin=True. is_staff ALWAYS implies administrator, so
        the deployed superuser (ensure_superuser sets is_staff=True) can never be
        locked out when the access-control switch flips on. See core.access for
        the switch-aware decorator that enforces this.
        """
        return bool(self.is_active and (self.is_staff or self.agency_admin))


# DEPRECATED (ISS-021): superseded by the two-tier agency_admin access model
# (see User.is_administrator + core.access). Role/UserRole are a dormant RBAC
# scheme that gated nothing; retained only to avoid a destructive migration.
# Safe to remove in a later cleanup phase. Do NOT build on these.
class Role(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class UserRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="user_roles")
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="user_roles")

    class Meta:
        unique_together = ("user", "role")

    def __str__(self):
        return f"{self.user} - {self.role}"


@track_changes()
class SiteConfig(models.Model):
    agency_name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=50, default="America/Los_Angeles")
    native_srid = models.IntegerField(default=4326)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True, null=True)
    allow_google_oauth = models.BooleanField(default=False)
    demonstration_mode = models.BooleanField(
        default=False,
        help_text="When on, every report surface and generated file is stamped "
        "'demonstration — not submittable'. Off for a real agency deployment; "
        "the Merced demo seed turns it on.",
    )

    # --- Agency-wide delivery accounting policy (Phase 55-02) ---
    # Efficiency is agronomic, not per-right: one agency-wide figure. Lifts the
    # hardcoded seed constant IRRIGATION_EFFICIENCY out of code so an agency can
    # tune it from a screen (the settings UI lands in Plan 03).
    default_irrigation_efficiency = models.DecimalField(
        max_digits=4,
        decimal_places=3,
        default=Decimal("0.750"),
        help_text="Share of delivered water the crop consumes.",
    )
    # The agency-wide default for what happens to an unused allocation at
    # year-end. A district may override it on its Zone; this default must always
    # resolve to a concrete value (never null), so existing rollover behavior is
    # preserved on migrate (carry_forward = the historic behavior).
    default_recovery_horizon = models.CharField(
        max_length=16,
        choices=RECOVERY_HORIZON_CHOICES,
        default="carry_forward",
        help_text="What happens to a district's unused allocation at year-end "
        "(agency-wide default; a district may override it).",
    )

    # --- Diversion records: the 145-01 memo's crosswalk layer (146-03 Task
    # 3). Both fields belong to `surface` exactly as
    # default_irrigation_efficiency does: DeliverySettingsForm shows them
    # only when `surface` is enabled, and a later plan's bulk importer is
    # the only reader -- nothing here reaches the accounting engine.
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
        "means here (the memo's J3).",
    )
    diversion_report_year_rule = models.CharField(
        max_length=20,
        choices=DIVERSION_REPORT_YEAR_RULE_CHOICES,
        default="water_year",
        help_text="How a YEAR and MONTH in the state's Water Use Reported "
        "file become a calendar month (the memo's J6 and M2).",
    )
    season_start_month = models.IntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text="The month (1-12) this deployment's irrigation season "
        "starts. Used only when the report year rule above is a season "
        "(the memo's J6).",
    )

    # --- Persistent identifiers (146-06 Task 1, ISS-019) ---
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
