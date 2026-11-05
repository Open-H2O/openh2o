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
from django.conf import settings
from django.contrib.gis.db import models
from django.urls import reverse
from django.utils import timezone

from accounting.locks import finalized_period_lock
from core.corrections import CorrectableRecord
from core.history import track_changes

# The data source whose stations never sync: a person types each reading on the
# station's page. Its code is how every list of "sources OpenH2O fetches from"
# leaves it out (datasync/fetch_now.py, sync_all, the health checks).
MANUAL_SOURCE_CODE = "manual"


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

    @property
    def is_manual(self):
        """True for the source whose readings are typed by hand and never fetched."""
        return self.code == MANUAL_SOURCE_CODE


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

    def get_absolute_url(self):
        """The record's own page (the /id/ address 303s here)."""
        return reverse("datasync:station_detail", args=[self.pk])


class DataSyncLog(models.Model):
    STATUS_CHOICES = [
        ("running", "Running"),
        ("success", "Success"),
        ("partial", "Partial"),
        ("failed", "Failed"),
    ]

    data_source = models.ForeignKey(DataSource, on_delete=models.CASCADE)
    # Set when the run fetched one station only (the station page's Fetch
    # readings now button); empty for a run over the whole source. A whole-source
    # view (source health, the failure streak) reads the empty ones.
    station = models.ForeignKey(
        "MonitoredStation",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sync_logs",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="running")
    records_fetched = models.IntegerField(default=0)
    records_staged = models.IntegerField(default=0)
    records_published = models.IntegerField(default=0)
    # Of the readings staged: how many were new to OpenH2O, and how many were a
    # source's revision of a reading OpenH2O already held.
    records_new = models.IntegerField("new readings", default=0)
    records_revised = models.IntegerField("revised readings", default=0)
    error_message = models.TextField(blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.data_source} {self.started_at}: {self.status}"


class DataRecordStaging(CorrectableRecord):
    """One reading a source sent, or a person typed on a hand station's page.

    A source that revises a reading it published is recorded the way a person's
    correction is: the revised reading is a NEW row that ``replaces`` the first,
    and the first gets ``replaced_at`` and nothing else. ``.current()`` is the
    rule for "which readings count". This table has no change history and no
    Void or Correct control: a source's reading is the source's, and the replaced
    row IS the history.
    """

    # The mixin's PROTECT would make deleting a station, a source or a pruned
    # chain raise on any replaced row. RESTRICT lets a delete that takes both rows
    # of a chain (a cascade from the station, or prune removing the pair) pass.
    replaces = models.OneToOneField(
        "self",
        on_delete=models.RESTRICT,
        null=True,
        blank=True,
        related_name="replaced_by",
        verbose_name="replaces",
    )

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
    # Which daily statistic the value is (USGS 00001 high, 00002 low, 00003
    # average); blank for a source that publishes none.
    statistic = models.CharField(max_length=10, blank=True, default="")
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
            # One CURRENT observation per station+parameter+statistic+timestamp.
            # Lets repeated syncs (hourly for live gauges) re-pull the same
            # readings as a no-op instead of piling up duplicate rows that put
            # multiple points per date on charts. A replaced row (a source's
            # revision wrote a newer one) is out of the index, so the chain's
            # rows share one key.
            models.UniqueConstraint(
                fields=["station", "parameter_code", "statistic", "observation_date"],
                condition=models.Q(replaced_at__isnull=True),
                name="uniq_staging_station_param_stat_obsdate",
            ),
        ]

    def __str__(self):
        return f"{self.station} {self.observation_date}: {self.parameter_code}={self.value}"


@track_changes()
class TypedReading(CorrectableRecord):
    """The record of one reading a person typed on a hand station's page.

    The reading itself is an ordinary published row in ``DataRecordStaging``,
    so the chart and the readings table need no special case. That table cannot
    be change-tracked: every sync writes thousands of rows into it. This small
    table carries the history instead: who typed the reading, when, and what
    they typed, with a trigger-written event for every later change.
    """

    station = models.ForeignKey(
        MonitoredStation,
        on_delete=models.CASCADE,
        related_name="typed_readings",
        verbose_name="monitoring station",
    )
    reading = models.OneToOneField(
        DataRecordStaging,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="typed_record",
        verbose_name="station reading",
    )
    typed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="typed by",
    )
    typed_by_email = models.CharField(max_length=254, blank=True, verbose_name="typed by (email)")
    typed_at = models.DateTimeField(default=timezone.now, verbose_name="typed at")
    parameter_code = models.CharField(max_length=50, verbose_name="parameter")
    observation_date = models.DateField(verbose_name="reading date")
    value = models.DecimalField(max_digits=14, decimal_places=4, verbose_name="value")
    notes = models.TextField(blank=True, verbose_name="notes")

    class Meta:
        ordering = ["-typed_at"]
        # A finalized water year is closed to change (accounting/locks.py).
        triggers = [finalized_period_lock(date_column="observation_date")]

    def __str__(self):
        return f"{self.station} {self.observation_date}: {self.parameter_code}={self.value}"


# Module scope, not just a class attribute: OpenETCache.Meta's uniqueness
# condition needs it, and a nested class body cannot see the enclosing class's
# namespace. OpenETCache.PENDING_MARKER stays the name the rest of the code uses.
PENDING_MARKER = "__PENDING__"


class OpenETCache(models.Model):
    # A reservation row carries this marker in model_name until its fetch lands.
    # It counts toward the monthly budget the moment it is created (see
    # reserve_query_slot) but is EXCLUDED from cache reads, so an in-flight
    # reservation is never served as an empty cache hit.
    PENDING_MARKER = PENDING_MARKER  # noqa: F821 — resolves to the module constant
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
    # How this row came to exist. monthly_query_count() is the monthly-allowance
    # figure the budget guard compares against, and rows arrive two ways: a real
    # API call charged through reserve_query_slot, and a bulk load from the
    # committed fixture that spends nothing. Recorded at the moment it is known
    # rather than inferred later — inferring it from row timing is exactly what
    # made a freshly-seeded demonstration read as 380 requests spent.
    origin = models.CharField(
        max_length=10,
        choices=[
            ("api", "OpenET API call"),
            ("fixture", "Loaded from a committed fixture"),
            ("unknown", "Origin not recorded"),
        ],
        default="unknown",
        help_text="Whether this row cost an OpenET request",
    )

    class Meta:
        indexes = [
            models.Index(fields=["parcel", "start_date", "end_date"]),
            models.Index(fields=["queried_at"]),
        ]
        constraints = [
            # At most ONE real cache row per
            # parcel-window-variable-model. The GEE re-fetch path used to create a
            # second row over the same span and the engine summed both, doubling
            # gross ET and effective precip. Writers upsert on exactly this tuple.
            #
            # PENDING reservation rows are EXCLUDED: reserve_query_slot
            # materializes a placeholder to charge the OpenET budget the moment a
            # fetch is in flight, and two in-flight reservations for one window
            # must not raise IntegrityError — the budget lock, not this
            # constraint, is what governs them.
            #
            # Rows with parcel=NULL (ad-hoc geometry queries) are not covered:
            # Postgres treats NULLs as distinct. That is fine — every engine read
            # filters on a concrete parcel.
            models.UniqueConstraint(
                fields=["parcel", "start_date", "end_date", "variable", "model_name"],
                condition=~models.Q(model_name=PENDING_MARKER),
                name="openetcache_one_row_per_parcel_window",
            ),
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
        """Rows written this calendar month that actually cost an OpenET request.

        Fixture rows are excluded and NOTHING ELSE IS. "unknown" — every row
        predating the origin field — still counts, so the guard stays
        conservative on a database whose history we cannot see. Back-filling
        those to "fixture" would fabricate history in the direction that
        UNDER-reports spend, which is the dangerous direction for a guard.
        load_openet_fixture upserts on the uniqueness tuple, so its next run
        stamps origin="fixture" on exactly the rows it owns, pre-existing ones
        included, and a demonstration corrects itself.
        """
        from django.utils import timezone

        month_start = timezone.now().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        return (
            cls.objects.filter(queried_at__gte=month_start)
            .exclude(origin="fixture")
            .count()
        )

    @classmethod
    def check_budget(cls, budget=None):
        from django.conf import settings as django_settings

        # 100 is Tier 1, what a new OpenET account gets, and it must match
        # config/settings/base.py's default. A guard's fallback errs toward the
        # SMALLER allowance — erring high is not a bigger budget, it is a
        # disabled guard. The live figure comes from
        # OpenETAdapter.account_status(); it is deliberately not read here,
        # because this method runs under an advisory lock inside
        # reserve_query_slot's transaction and must not make an HTTP call.
        limit = budget or getattr(django_settings, "OPENET_MONTHLY_BUDGET", 100)
        used = cls.monthly_query_count()
        return used < limit, used, limit

    @classmethod
    def reserve_query_slot(
        cls, parcel, geometry, start_date, end_date, budget=None, variable="ET"
    ):
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
                variable=variable,
                model_name=cls.PENDING_MARKER,
                et_data=[],
                # The single point where an OpenET request is charged, so the
                # single place origin="api" is set.
                origin="api",
            )
