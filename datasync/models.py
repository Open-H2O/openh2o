# SPDX-License-Identifier: AGPL-3.0-or-later
"""
External monitoring-data sync models.

Defines the partner feeds (DataSource: USGS, CDEC, CIMIS, NOAA) and the stations
they publish (MonitoredStation, with USGS/WQX cross-walk IDs), plus the staging
pipeline that lands raw readings (DataRecordStaging), records each pull
(DataSyncLog), and caches satellite ET draws against the monthly budget
(OpenETCache). These supply the observed inputs the accounting layer reconciles;
OpenET evapotranspiration is the consumptive-use spine, not a supply.
"""
from django.contrib.gis.db import models


class DataSource(models.Model):
    AUTH_TYPE_CHOICES = [
        ("none", "None"),
        ("api_key", "API Key"),
        ("oauth", "OAuth"),
        ("token", "Token"),
    ]

    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    url = models.CharField(max_length=500, blank=True)
    auth_type = models.CharField(
        max_length=50, choices=AUTH_TYPE_CHOICES, default="none"
    )
    sync_interval_hours = models.IntegerField(default=24)
    is_active = models.BooleanField(default=True)
    description = models.TextField(blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class MonitoredStation(models.Model):
    data_source = models.ForeignKey(DataSource, on_delete=models.CASCADE)
    external_station_id = models.CharField(max_length=100)
    station_name = models.CharField(max_length=200)
    location = models.PointField(srid=4326)
    # Partner cross-walk identifiers — the same station seen in the federal/
    # state systems, so a self-published series can line up with theirs.
    usgs_site_id = models.CharField(
        max_length=50,
        blank=True,
        help_text="USGS NWIS site number (waterdata.usgs.gov), if this station "
        "is also a USGS site.",
    )
    wqx_monitoring_location_id = models.CharField(
        max_length=50,
        blank=True,
        help_text="EPA WQX MonitoringLocationIdentifier (Water Quality Portal).",
    )
    parameters = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    last_data_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("data_source", "external_station_id")]

    def __str__(self):
        return f"{self.data_source.code}:{self.external_station_id} - {self.station_name}"


class DataSyncLog(models.Model):
    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("partial", "Partial"),
        ("failed", "Failed"),
    ]

    data_source = models.ForeignKey(DataSource, on_delete=models.CASCADE)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    records_fetched = models.IntegerField(default=0)
    records_staged = models.IntegerField(default=0)
    records_published = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.data_source} {self.started_at}: {self.status}"


class DataRecordStaging(models.Model):
    STATUS_CHOICES = [
        ("staged", "Staged"),
        ("published", "Published"),
        ("rejected", "Rejected"),
        ("duplicate", "Duplicate"),
    ]

    data_source = models.ForeignKey(DataSource, on_delete=models.CASCADE)
    station = models.ForeignKey(MonitoredStation, on_delete=models.CASCADE)
    raw_data = models.JSONField()
    observation_date = models.DateTimeField()
    parameter_code = models.CharField(max_length=50)
    value = models.DecimalField(
        max_digits=14, decimal_places=4, null=True, blank=True
    )
    unit = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="staged")
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-observation_date"]
        constraints = [
            # One observation per station+parameter+timestamp. Lets repeated
            # syncs (hourly for live gauges) re-pull the same readings as a
            # no-op via bulk_create(ignore_conflicts=True) instead of piling up
            # duplicate rows that put multiple points per date on charts.
            models.UniqueConstraint(
                fields=["station", "parameter_code", "observation_date"],
                name="uniq_staging_station_param_obsdate",
            ),
        ]

    def __str__(self):
        return f"{self.station} {self.observation_date}: {self.parameter_code}={self.value}"


class OpenETCache(models.Model):
    # A reservation row carries this marker in model_name until its fetch lands.
    # It counts toward the monthly budget the moment it is created (see
    # reserve_query_slot) but is EXCLUDED from cache reads, so an in-flight
    # reservation is never served as an empty cache hit.
    PENDING_MARKER = "__PENDING__"
    # Stable key for the transaction-scoped advisory lock that serializes budget
    # reservations so the count-then-create can't race.
    _BUDGET_LOCK_KEY = 0x0E7B0001

    parcel = models.ForeignKey(
        "parcels.Parcel", null=True, blank=True, on_delete=models.CASCADE
    )
    geometry = models.MultiPolygonField(srid=4326, help_text="Queried geometry")
    start_date = models.DateField()
    end_date = models.DateField()
    variable = models.CharField(max_length=20, default="ET")
    model_name = models.CharField(max_length=50, default="Ensemble")
    et_data = models.JSONField(help_text="Monthly ET values from API response")
    queried_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["parcel", "start_date", "end_date"]),
            models.Index(fields=["queried_at"]),
        ]

    def __str__(self):
        label = self.parcel or "no-parcel"
        return f"OpenET {label} {self.start_date}–{self.end_date}"

    def is_stale(self, max_age_days=None):
        from django.conf import settings as django_settings
        from django.utils import timezone

        max_days = max_age_days or getattr(django_settings, "OPENET_CACHE_DAYS", 30)
        return (timezone.now() - self.queried_at).days > max_days

    @classmethod
    def monthly_query_count(cls):
        from django.utils import timezone

        month_start = timezone.now().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return cls.objects.filter(queried_at__gte=month_start).count()

    @classmethod
    def check_budget(cls, budget=None):
        from django.conf import settings as django_settings

        limit = budget or getattr(django_settings, "OPENET_MONTHLY_BUDGET", 400)
        used = cls.monthly_query_count()
        return used < limit, used, limit

    @classmethod
    def reserve_query_slot(cls, parcel, geometry, start_date, end_date, budget=None):
        """Atomically reserve one OpenET query slot against the monthly budget.

        check_budget() + create-row was check-then-act: two concurrent syncs near
        the ceiling both passed and both spent, defeating the only guard against
        an unbounded external-API bill. Serialize the check-and-reserve with a
        transaction-scoped Postgres advisory lock and materialize the reservation
        as a PENDING row so it counts immediately. Returns the pending row, or
        None if the budget is exhausted.

        The caller MUST then either finalize the row (fill et_data + real
        model_name) or delete it, releasing the slot, once the fetch resolves.
        The lock is held only across the count + insert, never across the fetch.
        """
        from django.db import connection, transaction

        with transaction.atomic():
            with connection.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(%s)", [cls._BUDGET_LOCK_KEY])
            can_query, _used, _limit = cls.check_budget(budget=budget)
            if not can_query:
                return None
            return cls.objects.create(
                parcel=parcel,
                geometry=geometry,
                start_date=start_date,
                end_date=end_date,
                variable="ET",
                model_name=cls.PENDING_MARKER,
                et_data=[],
            )
