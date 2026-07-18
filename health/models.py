# SPDX-License-Identifier: AGPL-3.0-or-later
"""
System self-check records.

Defines HealthCheckResult: one timestamped row per subsystem check (database,
disk, sync freshness, ledger integrity, orphans, cache duplication, POD
fractions, unallocated delivery, period alignment, ET/meter agreement, SSL,
Docker, migrations) with a green/yellow/red status, a message, and JSON details.
The health dashboard reads the latest row per category to report overall system
status.
"""
from django.contrib.gis.db import models


class HealthCheckResult(models.Model):
    CATEGORY_CHOICES = [
        ("database", "Database"),
        ("disk", "Disk"),
        ("sync_freshness", "Sync Freshness"),
        ("ledger_integrity", "Ledger Integrity"),
        ("orphans", "Orphans"),
        # Added by the 2026-07-18 math evaluation. These four checks shipped
        # earlier the same day writing categories that were never listed here —
        # harmless at the DB level (choices are not enforced by Postgres) but
        # full_clean() rejects them and the admin dropdown cannot show them.
        ("cache_duplication", "Cache Duplication"),
        ("pod_fractions", "POD Fractions"),
        ("unallocated_delivery", "Unallocated Delivery"),
        ("period_alignment", "Period Alignment"),
        ("et_meter_agreement", "ET / Meter Agreement"),
        ("ssl", "SSL"),
        ("docker", "Docker"),
        ("migrations", "Migrations"),
    ]
    STATUS_CHOICES = [
        ("green", "Green"),
        ("yellow", "Yellow"),
        ("red", "Red"),
    ]

    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    message = models.TextField()
    details = models.JSONField(default=dict, blank=True)
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-checked_at"]

    def __str__(self):
        return f"{self.category}: {self.status}"
