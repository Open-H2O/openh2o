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

    def __str__(self):
        return f"{self.station} {self.observation_date}: {self.parameter_code}={self.value}"
