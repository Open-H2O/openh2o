"""
GEE-backed OpenET adapter — the batched Earth Engine tier.

``GEEOpenETAdapter`` subclasses ``OpenETAdapter`` so it INHERITS the mm
validation thresholds (``validate``) and the geometry helpers — the two tiers
can never drift on what counts as a sane ET value. It OVERRIDES only the fetch
path: where the REST tier loops one query per parcel (and burns one of the
OpenET API's ~100 monthly queries each time), the GEE tier batches ALL parcels
into one ``FeatureCollection`` and runs ONE ``reduceRegions`` per monthly image.
That batching is the entire reason this tier exists.

It also adds permanent caching of finalized months: OpenET monthly ET for a
settled past month never changes, so a parcel-month that is both already cached
AND finalized is never re-fetched. ``OpenETCache.is_stale()``'s flat 30-day rule
would wrongly re-query it; the skip logic here is the correction.
"""

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta

from datasync.adapters import register_adapter
from datasync.adapters.gee import (
    _first_of_month,
    _first_of_next_month,
    build_et_data,
    init_earth_engine,
    reduce_et_by_parcel,
)
from datasync.adapters.openet import OpenETAdapter
from datasync.freshness import EXPECTED_DATA_INTERVAL_HOURS

logger = logging.getLogger(__name__)

# OpenET finalizes a month's ET roughly 45 days after the month ends. Derive
# the lag from the freshness module's openet cadence (24*45 hours) so the two
# can never disagree. A month is only skipped permanently once today is at
# least this many days past the month's END — the conservative choice, so we
# never skip-forever a value that might still be revised.
OPENET_SETTLE_LAG_DAYS = EXPECTED_DATA_INTERVAL_HOURS["openet"] // 24  # 45


def _iter_months(start, end):
    """List the YYYY-MM month keys touching the window [start, end]."""
    month = _first_of_month(start)
    last = _first_of_month(end)
    months = []
    while month <= last:
        months.append(month.strftime("%Y-%m"))
        month = _first_of_next_month(month)
    return months


class GEEOpenETAdapter(OpenETAdapter):
    source_code = "openet_gee"

    def _month_finalized(self, month_key, today):
        """True once `today` is >= OPENET_SETTLE_LAG_DAYS past the month's end."""
        month_first = datetime.strptime(month_key, "%Y-%m").date()
        settled_on = _first_of_next_month(month_first) + timedelta(
            days=OPENET_SETTLE_LAG_DAYS
        )
        return today >= settled_on

    def _cached_months(self, parcels, start, end):
        """{parcel_id: set(YYYY-MM)} already present in OpenETCache for the window."""
        from datasync.models import OpenETCache

        pids = [p.pk for p in parcels]
        rows = OpenETCache.objects.filter(
            parcel_id__in=pids,
            start_date__lte=end,
            end_date__gte=start,
        )
        cached = defaultdict(set)
        for row in rows:
            for item in row.et_data or []:
                raw_date = item.get("date", "")
                if item.get("et") is None or len(raw_date) < 7:
                    continue
                cached[row.parcel_id].add(raw_date[:7])
        return cached

    def _months_needing_fetch(self, parcels, start, end, today):
        """Pure skip-logic core: which parcel-months still need a fetch.

        For each parcel, a month needs fetching when it is either (a) missing
        from the cache, or (b) cached but NOT yet finalized (it may still be
        updating). Finalized months already in the cache are skipped forever.
        No EE calls, no DB writes — `today` is a parameter so tests are
        deterministic. Returns {parcel_id: [months_to_fetch]} (empty list when a
        parcel is fully served by the cache).
        """
        window_months = _iter_months(start, end)
        cached = self._cached_months(parcels, start, end)
        needs = {}
        for parcel in parcels:
            parcel_cached = cached.get(parcel.pk, set())
            to_fetch = []
            for month in window_months:
                if month not in parcel_cached:
                    to_fetch.append(month)
                elif not self._month_finalized(month, today):
                    to_fetch.append(month)
                # else: cached AND finalized -> permanent skip
            needs[parcel.pk] = to_fetch
        return needs

    def sync_parcel_et(self, parcels, start_date, end_date, today=None):
        """Batched live entry point — overrides the REST per-parcel loop.

        One Earth Engine compute job per month over ALL parcels that still need
        work, written into OpenETCache in the exact REST-shaped et_data so the
        unchanged sync_openet_to_ledger contract consumes it as-is.
        """
        from datasync.models import OpenETCache

        parcels = list(parcels)
        if today is None:
            today = date.today()

        window_months = _iter_months(start_date, end_date)
        needs = self._months_needing_fetch(parcels, start_date, end_date, today)

        summary = {"fetched": 0, "cached": 0, "failed": 0, "skipped_final": 0}
        for parcel in parcels:
            summary["skipped_final"] += len(window_months) - len(
                needs.get(parcel.pk, [])
            )

        parcels_with_work = [p for p in parcels if needs.get(p.pk)]
        summary["cached"] = len(parcels) - len(parcels_with_work)

        # Full cache hit: skip EE init entirely — don't pay the auth cost.
        if not parcels_with_work:
            return summary

        ee = init_earth_engine()

        # Minimal window covering every month that still needs a fetch.
        needed_months = sorted(
            {m for p in parcels_with_work for m in needs[p.pk]}
        )
        win_start = datetime.strptime(needed_months[0], "%Y-%m").date()
        win_end = _first_of_next_month(
            datetime.strptime(needed_months[-1], "%Y-%m").date()
        ) - timedelta(days=1)

        result = reduce_et_by_parcel(ee, parcels_with_work, win_start, win_end)

        for parcel in parcels_with_work:
            parcel_result = result.get(parcel.pk, {})
            records = [
                {
                    "station_id": parcel.parcel_number,
                    "observation_date": month,
                    "parameter_code": "ET",
                    "value": parcel_result[month],
                    "unit": "mm",
                }
                for month in needs[parcel.pk]
                if month in parcel_result
            ]
            # Inherited threshold validation — shared with the REST tier.
            valid, _rejected = self.validate(records, temporal_resolution="monthly")
            et_by_month = {r["observation_date"]: r["value"] for r in valid}
            if not et_by_month:
                summary["failed"] += 1
                continue

            OpenETCache.objects.create(
                parcel=parcel,
                geometry=parcel.geometry,
                start_date=win_start,
                end_date=win_end,
                variable="ET",
                model_name="Ensemble",
                et_data=build_et_data(et_by_month),
            )
            summary["fetched"] += 1

        return summary


register_adapter("openet_gee", GEEOpenETAdapter)
