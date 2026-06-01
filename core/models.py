# SPDX-License-Identifier: AGPL-3.0-or-later
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


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


class SiteConfig(models.Model):
    agency_name = models.CharField(max_length=200)
    timezone = models.CharField(max_length=50, default="America/Los_Angeles")
    native_srid = models.IntegerField(default=4326)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    logo = models.ImageField(upload_to="logos/", blank=True, null=True)
    allow_google_oauth = models.BooleanField(default=False)

    def save(self, *args, **kwargs):
        if self.pk is None and SiteConfig.objects.exists():
            raise ValidationError("Only one SiteConfig instance is allowed.")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.agency_name
