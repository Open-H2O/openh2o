"""
Base adapter for external data sources.

Every concrete adapter (CDEC, USGS, etc.) extends BaseAdapter and implements
the four abstract methods: fetch, parse, validate, discover_stations.

The sync() orchestrator runs the pipeline:
  fetch (or fetch_mock) -> parse -> validate -> stage -> publish
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests
from django.conf import settings
from django.utils import timezone

from datasync.models import DataRecordStaging, DataSource, DataSyncLog, MonitoredStation

logger = logging.getLogger(__name__)


class BaseAdapter(ABC):
    """Abstract base for all data-source adapters."""

    source_code: str = ""
    rate_limit_seconds: float = 1.0
    max_retries: int = 3

    def __init__(self):
        self._last_request_time = 0.0

    # ── Abstract methods ────────────────────────────────────────────────

    @abstractmethod
    def fetch(self, station, start_date, end_date):
        """Fetch raw data from the external API. Returns raw response data."""

    @abstractmethod
    def parse(self, raw_data):
        """
        Parse raw API response into a list of record dicts:
        [{"station_id": str, "observation_date": str/datetime,
          "parameter_code": str, "value": number, "unit": str, ...}]
        """

    @abstractmethod
    def validate(self, records):
        """
        Validate parsed records. Returns (valid_records, rejected_records).
        Each rejected record gets a 'rejection_reason' key.
        """

    @abstractmethod
    def discover_stations(self, boundary_geometry, radius_km=50):
        """
        Find stations near a boundary geometry.
        Returns list of dicts with keys:
        station_id, name, latitude, longitude, parameters
        """

    # ── Mock support ────────────────────────────────────────────────────

    def fetch_mock(self, station, start_date, end_date):
        """Load fixture data instead of calling the real API."""
        fixture_path = (
            Path(__file__).resolve().parent.parent / "fixtures" / f"{self.source_code}.json"
        )
        if not fixture_path.exists():
            raise FileNotFoundError(f"Mock fixture not found: {fixture_path}")
        with open(fixture_path) as f:
            data = json.load(f)
        return data.get("records", [])

    def _use_mock(self, data_source):
        """Decide whether to use mock mode."""
        mock_setting = getattr(settings, "DATASYNC_MOCK_MODE", False)
        return mock_setting or not data_source.is_active

    # ── HTTP helpers ────────────────────────────────────────────────────

    def _rate_limit(self):
        """Sleep if needed to respect rate limits."""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)
        self._last_request_time = time.time()

    def _request(self, method, url, **kwargs):
        """
        HTTP request with rate limiting and retry.
        Returns requests.Response on success, raises on exhausted retries.
        """
        self._rate_limit()
        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = requests.request(method, url, timeout=60, **kwargs)
                resp.raise_for_status()
                return resp
            except (requests.HTTPError, requests.ConnectionError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    backoff = 2 ** attempt
                    logger.warning(
                        "%s: attempt %d/%d failed (%s), retrying in %ds",
                        self.source_code, attempt, self.max_retries, exc, backoff,
                    )
                    time.sleep(backoff)
        raise last_exc

    # ── Pipeline: stage & publish ───────────────────────────────────────

    def stage(self, records, sync_log, station):
        """Bulk-create DataRecordStaging rows from validated records."""
        staging_objects = []
        for rec in records:
            try:
                obs_date = rec["observation_date"]
                if isinstance(obs_date, str):
                    try:
                        obs_date = datetime.fromisoformat(obs_date)
                    except ValueError:
                        obs_date = datetime.strptime(obs_date, "%Y-%m-%d %H:%M")
                if timezone.is_naive(obs_date):
                    obs_date = timezone.make_aware(obs_date)

                value = rec.get("value")
                if value is not None:
                    try:
                        value = Decimal(str(value))
                    except (InvalidOperation, ValueError):
                        value = None

                staging_objects.append(
                    DataRecordStaging(
                        data_source=sync_log.data_source,
                        station=station,
                        raw_data=rec,
                        observation_date=obs_date,
                        parameter_code=rec.get("parameter_code", ""),
                        value=value,
                        unit=rec.get("unit", ""),
                        status="staged",
                    )
                )
            except Exception as exc:
                logger.warning(
                    "%s: skipping record during staging: %s", self.source_code, exc
                )

        if staging_objects:
            DataRecordStaging.objects.bulk_create(staging_objects, ignore_conflicts=True)

        return len(staging_objects)

    def publish(self, sync_log):
        """Promote staged records to published and update station timestamps."""
        staged_qs = DataRecordStaging.objects.filter(
            data_source=sync_log.data_source,
            status="staged",
        )
        now = timezone.now()
        published_count = staged_qs.update(status="published", published_at=now)

        # Update last_data_at on each station that received data
        station_ids = (
            DataRecordStaging.objects.filter(
                data_source=sync_log.data_source,
                published_at=now,
            )
            .values_list("station_id", flat=True)
            .distinct()
        )
        MonitoredStation.objects.filter(id__in=station_ids).update(last_data_at=now)

        return published_count

    # ── Orchestrator ────────────────────────────────────────────────────

    def sync(self, station, start_date, end_date, sync_log=None):
        """
        Run the full pipeline for one station:
        fetch -> parse -> validate -> stage -> publish
        """
        data_source = station.data_source

        # Create a sync log if one wasn't provided (single-station mode)
        own_log = sync_log is None
        if own_log:
            sync_log = DataSyncLog.objects.create(
                data_source=data_source, status="running"
            )

        try:
            # Fetch
            if self._use_mock(data_source):
                raw_data = self.fetch_mock(station, start_date, end_date)
                logger.info("%s: using mock data for %s", self.source_code, station)
            else:
                raw_data = self.fetch(station, start_date, end_date)

            # Parse
            records = self.parse(raw_data)
            sync_log.records_fetched += len(records)

            # Validate
            valid, rejected = self.validate(records)
            if rejected:
                logger.info(
                    "%s: %d records rejected for %s",
                    self.source_code, len(rejected), station,
                )

            # Stage
            staged_count = self.stage(valid, sync_log, station)
            sync_log.records_staged += staged_count

            # Publish
            published_count = self.publish(sync_log)
            sync_log.records_published += published_count

            if own_log:
                sync_log.status = "success"

        except FileNotFoundError as exc:
            logger.error("%s: fixture missing: %s", self.source_code, exc)
            sync_log.error_message = str(exc)
            if own_log:
                sync_log.status = "failed"

        except (requests.RequestException, requests.ConnectionError) as exc:
            logger.error("%s: connection error for %s: %s", self.source_code, station, exc)
            sync_log.error_message = str(exc)
            if own_log:
                sync_log.status = "failed"

        except Exception as exc:
            logger.exception("%s: unexpected error for %s", self.source_code, station)
            sync_log.error_message = str(exc)
            if own_log:
                sync_log.status = "failed"

        finally:
            if own_log:
                sync_log.completed_at = timezone.now()
                delta = (sync_log.completed_at - sync_log.started_at).total_seconds()
                sync_log.duration_seconds = delta
                sync_log.save()

        return sync_log
