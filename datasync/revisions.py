# SPDX-License-Identifier: AGPL-3.0-or-later
"""The one door a source's readings go through: new ones are added, revised ones replace.

``BaseAdapter.stage`` and ``load_reading_fixture`` both hand their unsaved rows to
:func:`record_readings`. For each reading (station, parameter, statistic and
observation date) it decides one of four things:

- the key is not stored: a NEW row (unless the reading is older than the day a
  change-date sync starts from, see ``since``: it is ignored);
- the key is stored with the same value after rounding to the column's places: nothing
  (another unit label with the same value is nothing too);
- the key is stored with a figure and the source sent a blank: nothing (a blank never
  replaces a figure);
- the key is stored and the value differs (a stored blank and a sent figure included): a
  REVISION. The revised reading is a new row that ``replaces`` the stored one, and the
  stored one gets ``replaced_at`` and nothing else.

One query reads the stored current rows of the whole batch, and the writes are bulk
writes, so the number of queries does not grow with the number of rows. The affected
``MonitoredStation`` rows are locked in primary-key order first, so a one-station fetch
running beside the scheduled sync cannot replace the same reading twice.
"""

from collections import namedtuple
from datetime import datetime
from decimal import ROUND_HALF_UP, Context, Decimal

from django.db import transaction
from django.utils import timezone

from datasync import freshness
from datasync.models import DataRecordStaging, MonitoredStation

#: How many rows one INSERT or one UPDATE carries.
BATCH = 2000

Counts = namedtuple("Counts", ["new", "revised"])


def _day_words(day):
    """A date as the site prints it in a sentence: Nov 3, 2026."""
    return f"{day:%b} {day.day}, {day.year}"


def rounded(value):
    """``value`` as the column will store it, or None for a blank.

    The column is a ``numeric(14, 4)`` and PostgreSQL rounds a value with more places
    half away from zero when it stores it (26.12345 is stored as 26.1235, -26.12345 as
    -26.1235). The comparison must agree with what is stored or an unchanged reading
    reads as a revision on every sync, so it rounds the same way, with the field's own
    ``decimal_places``. (``django.db.backends.utils.format_number`` rounds half to even,
    but the PostgreSQL backend does not use it to adapt a Decimal.)
    """
    if value is None:
        return None
    field = DataRecordStaging._meta.get_field("value")
    places = Decimal(1).scaleb(-field.decimal_places)
    return value.quantize(places, rounding=ROUND_HALF_UP, context=Context(prec=60))


def source_date(raw_data):
    """The local date the source puts on a value (``last_modified``), or None."""
    stamp = (raw_data or {}).get("last_modified")
    if not stamp or not isinstance(stamp, str):
        return None
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if timezone.is_naive(moment):
        moment = timezone.make_aware(moment)
    return timezone.localtime(moment).date()


def change_reason(row, today):
    """The sentence recorded on a revision: who revised it and when, as far as OpenH2O knows."""
    source = row.data_source
    name = freshness.source_display(source.code)
    day = source_date(row.raw_data)
    if day is not None:
        return f"Revised by {name} {_day_words(day)}"
    return f"Revised by {name}, fetched {_day_words(today)}"


def _key(row):
    return (row.station_id, row.parameter_code, row.statistic, row.observation_date)


def record_readings(rows, *, since=None):
    """Write ``rows`` (unsaved ``DataRecordStaging``, any stations) as new rows and revisions.

    ``since`` is a date: when given, a reading dated before it that is not already stored
    is ignored (a change-date request returns old readings the site never held). Returns
    ``Counts(new, revised)``.
    """
    first = {}
    for row in rows:
        first.setdefault(_key(row), row)
    if not first:
        return Counts(0, 0)

    station_ids = sorted({key[0] for key in first})
    codes = {key[1] for key in first}
    days = [key[3] for key in first]
    now = timezone.now()
    today = timezone.localdate(now)

    with transaction.atomic():
        # Lock in pk order so two runs over the same stations queue instead of crossing.
        list(
            MonitoredStation.objects.select_for_update()
            .filter(pk__in=station_ids)
            .order_by("pk")
            .values_list("pk", flat=True)
        )
        stored = {
            (station_id, code, statistic, moment): (pk, value)
            for pk, station_id, code, statistic, moment, value in (
                DataRecordStaging.objects.current()
                .filter(
                    station_id__in=station_ids,
                    parameter_code__in=codes,
                    observation_date__gte=min(days),
                    observation_date__lte=max(days),
                )
                .values_list("pk", "station_id", "parameter_code", "statistic", "observation_date", "value")
            )
        }

        new_rows = []
        revisions = []
        replaced_pks = []
        for key, row in first.items():
            held = stored.get(key)
            if held is None:
                if since is not None and timezone.localdate(row.observation_date) < since:
                    continue
                new_rows.append(row)
                continue
            old_pk, old_value = held
            incoming = rounded(row.value)
            if incoming is None or incoming == old_value:
                continue
            row.replaces_id = old_pk
            row.change_reason = change_reason(row, today)
            revisions.append(row)
            replaced_pks.append(old_pk)

        # The old rows first: the unique index reads replaced_at.
        for start in range(0, len(replaced_pks), BATCH):
            DataRecordStaging.objects.filter(pk__in=replaced_pks[start:start + BATCH]).update(
                replaced_at=now
            )
        if revisions:
            DataRecordStaging.objects.bulk_create(revisions, batch_size=BATCH)
        if new_rows:
            DataRecordStaging.objects.bulk_create(new_rows, batch_size=BATCH, ignore_conflicts=True)
    return Counts(len(new_rows), len(revisions))
