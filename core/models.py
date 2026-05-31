# SPDX-License-Identifier: AGPL-3.0-or-later
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class User(AbstractUser):
    agency_admin = models.BooleanField(default=False)
    phone = models.CharField(max_length=20, blank=True)
    title = models.CharField(max_length=100, blank=True)


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
