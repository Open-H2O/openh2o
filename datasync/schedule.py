# SPDX-License-Identifier: AGPL-3.0-or-later
"""When OpenH2O's schedule fetches a data source's readings.

Reads ``crontab.txt`` at the top of the checkout, the file the scheduled jobs are
installed from, and answers two questions for a source code: what its schedule is
in words, and when the next fetch is after a given moment.

Only the cron fields that file uses are understood: a minute that is a number, an
hour that is ``*``, a number or ``*/n``, and ``*`` in the day, month and weekday
fields. A line with anything else is not read and is never guessed at. A missing or
unreadable file says nothing, and the station page then leaves the sentence out.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

_RUN_SYNC = "run-sync.sh"
_NUMBER = re.compile(r"^\d{1,2}$")
_STEP = re.compile(r"^\*/(\d{1,2})$")


@dataclass(frozen=True)
class Entry:
    """One readable schedule line: the hours and minute it runs, and its sources."""

    minute: int
    hours: tuple[int, ...]
    hour_step: int | None  # n for "*/n", 1 for "*", None for one fixed hour
    sources: tuple[str, ...]


def crontab_path():
    return settings.BASE_DIR / "crontab.txt"


def _parse_line(line: str):
    """Return an Entry, "unreadable" for a sync line this reader cannot read, or None."""
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    fields = text.split()
    if len(fields) < 7 or _RUN_SYNC not in fields[5]:
        return None
    minute, hour, dom, month, dow = fields[:5]
    sources = tuple(fields[6:])
    if not (_NUMBER.match(minute) and dom == "*" and month == "*" and dow == "*"):
        return "unreadable"
    if int(minute) > 59:
        return "unreadable"
    if hour == "*":
        hours, step = tuple(range(24)), 1
    elif _NUMBER.match(hour) and int(hour) < 24:
        hours, step = (int(hour),), None
    elif _STEP.match(hour) and 1 <= int(_STEP.match(hour).group(1)) <= 23:
        step = int(_STEP.match(hour).group(1))
        hours = tuple(range(0, 24, step))
    else:
        return "unreadable"
    return Entry(int(minute), hours, step, sources)


def _read():
    """(entries, unreadable_sync_lines_seen), or None when the file cannot be read."""
    try:
        text = crontab_path().read_text()
    except (OSError, UnicodeDecodeError):
        return None
    entries, unreadable = [], False
    for line in text.splitlines():
        parsed = _parse_line(line)
        if parsed == "unreadable":
            unreadable = True
        elif parsed is not None:
            entries.append(parsed)
    return entries, unreadable


def _entries_for(source_code: str):
    read = _read()
    if read is None:
        return None, True
    entries, unreadable = read
    return [e for e in entries if source_code in e.sources], unreadable


def is_scheduled(source_code: str):
    """True or False when the file settles it; None when it cannot be read."""
    mine, unreadable = _entries_for(source_code)
    if mine is None:
        return None
    if mine:
        return True
    return None if unreadable else False


def _clock(hour: int, minute: int) -> str:
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def _words(entry: Entry) -> str:
    if entry.hour_step is None:
        return f"every day at {_clock(entry.hours[0], entry.minute)}"
    if entry.hour_step == 1:
        if entry.minute == 0:
            return "every hour, on the hour"
        return f"every hour, {entry.minute} minutes past the hour"
    tail = "on the hour" if entry.minute == 0 else f"at {entry.minute} minutes past"
    return f"every {entry.hour_step} hours, {tail}"


def describe(source_code: str):
    """The source's schedule in words, or None when it is not on the schedule."""
    mine, _ = _entries_for(source_code)
    if not mine:
        return None
    return " and ".join(dict.fromkeys(_words(e) for e in mine))


def _site_zone() -> ZoneInfo:
    from core.models import SiteConfig

    name = SiteConfig.objects.values_list("timezone", flat=True).first()
    for candidate in (name, settings.TIME_ZONE):
        try:
            return ZoneInfo(candidate)
        except Exception:  # unknown or empty zone name
            continue
    return ZoneInfo("UTC")


def _now():
    return timezone.now()


def next_run(source_code: str, after: datetime | None = None):
    """The first fetch after ``after``, in the site's time zone; None if not known."""
    mine, _ = _entries_for(source_code)
    if not mine:
        return None
    zone = _site_zone()
    start = (after if after is not None else _now()).astimezone(zone)
    best = None
    for offset in range(0, 3):
        day = (start + timedelta(days=offset)).date()
        for entry in mine:
            for hour in entry.hours:
                candidate = datetime(
                    day.year, day.month, day.day, hour, entry.minute, tzinfo=zone
                )
                if candidate > start and (best is None or candidate < best):
                    best = candidate
        if best is not None:
            break
    return best


def _key_missing(source_code: str) -> bool:
    from datasync.adapters import get_adapter

    adapter = get_adapter(source_code)
    return adapter is not None and adapter.missing_required_credential() is not None


def station_sentence(station, now: datetime | None = None):
    """The sentence a station's page carries about when readings are fetched."""
    name = station.data_source.name
    if not station.is_active:
        return "Syncing is off, so OpenH2O's schedule skips this station."
    if not station.data_source.is_active:
        return (
            f"OpenH2O's schedule skips {name}: the source is switched off in "
            "OpenH2O's list of data sources."
        )
    scheduled = is_scheduled(station.data_source.code)
    if scheduled is None:
        return None
    if scheduled is False:
        return f"OpenH2O's schedule does not fetch readings from {name}."
    words = describe(station.data_source.code)
    following = next_run(station.data_source.code, now)
    if words is None or following is None:
        return None
    if _key_missing(station.data_source.code):
        return (
            f"OpenH2O's schedule fetches readings from {name} {words} once its "
            "key is set. The key is not set on this server."
        )
    zone = following.tzinfo
    today = (now if now is not None else _now()).astimezone(zone).date()
    when = _clock(following.hour, following.minute)
    days = (following.date() - today).days
    if days == 1:
        when += " tomorrow"
    elif days > 1:
        when += f" on {following:%A}"
    return f"OpenH2O fetches readings from {name} {words}. The next fetch is at {when}."
