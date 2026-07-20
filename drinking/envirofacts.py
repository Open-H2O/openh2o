# SPDX-License-Identifier: AGPL-3.0-or-later
"""
EPA Envirofacts SDWIS client — turn a PWSID into raw federal data.

This module does network I/O and nothing else. It fetches three SDWIS tables for
one public water system, caches each raw response on a row, and fails with a
type the caller can branch on. It deliberately does NOT map anything onto
``drinking.models`` — that is Plan 79-02's job, and keeping the split means a
mapping change never has to invalidate a cache.

**Endpoint.** The V1 ``efservice`` endpoint, not ``dmapservice``. Both are live
as of 2026-07-19 and EPA publishes no deprecation date, but ``dmapservice``
requires a schema-qualified table name and returns HTTP 200 with ``[]`` when you
omit it — indistinguishable from "no such system." ``efservice`` at least 404s
on a bad table. URL construction is isolated in :func:`build_url` so a future
migration is one edit.

**Three failure modes, three types.** They are kept distinct because conflating
them misleads an operator:

* :class:`PwsidNotFound` — EPA has no such system. Signalled by HTTP **200 with
  an empty array**, never a 404. Naive code reads that as success and onboards a
  system with a blank name and zero facilities.
* :class:`EnvirofactsError` — the service answered, but not with the envelope we
  expect. A success body is a JSON *list*; an error body is a JSON *object*
  (``{"error": "…: The table is not available."}``). ``for row in resp.json()``
  on that path iterates dict KEYS and yields nonsense instead of raising.
* :class:`EnvirofactsUnavailable` — EPA did not answer in time. This must never
  surface as "not found", which would tell an operator their perfectly valid
  PWSID does not exist.

**Timeout is measured, not inherited.** ``BaseAdapter.discovery_timeout`` is
10.0s, tuned for CDEC/USGS. A live ``WATER_SYSTEM`` lookup measured **15.5s** on
2026-07-19, and even the 404 error path took 9.8s, so a 10s budget would fail
against a healthy service. 30s with 2 retries is the defensible number.

**Cadence is unknown, on purpose.** SDWIS is a periodic federal extract, so a
30-day TTL is reasonable — but EPA's actual refresh cadence is NOT documented
(``epa.gov/enviro/sdwis-model`` returns 404). This module states that rather
than asserting a cadence it cannot cite. Override with
``ENVIROFACTS_CACHE_DAYS``, and offer the operator a manual refresh
(``refresh=True``).

The HTTP retry/backoff structure is copied from ``datasync.adapters.base``'s
``_request``, not imported: ``BaseAdapter`` is station/timeseries-shaped
(``fetch(station, start_date, end_date)`` → ``DataRecordStaging``) and
Envirofacts returns entities, not observations. Keeping ``_request`` at module
scope also gives the tests exactly one seam to monkeypatch — the repo has no
HTTP-mocking library by choice. This client is operator-triggered, so it is
NOT registered in ``ADAPTER_REGISTRY``; that registry feeds the nightly
``sync_all`` cron.
"""

import logging
import time

import requests

from drinking.models import EnvirofactsCache

logger = logging.getLogger(__name__)

# ── Endpoint ────────────────────────────────────────────────────────────────

BASE_URL = "https://data.epa.gov/efservice"

TABLE_WATER_SYSTEM = "WATER_SYSTEM"
TABLE_FACILITIES = "WATER_SYSTEM_FACILITY"
TABLE_GEOGRAPHIC_AREA = "GEOGRAPHIC_AREA"

# 30s, not the repo's 10.0s discovery_timeout: measured WATER_SYSTEM latency was
# 15.5s on 2026-07-19 and the 404 error path took 9.8s. 10s would time out on a
# healthy service.
HTTP_TIMEOUT_SECONDS = 30
MAX_RETRIES = 2

# EPA documents no per-client quota and requires no API key; the only stated
# limit is that a request must complete within 15 minutes. Absence of a
# documented limit is not proof there is none, and we did not stress-test a
# federal service to find out. Sleep politely between calls, as the existing
# adapters' rate_limit_seconds does.
RATE_LIMIT_SECONDS = 0.5

_last_request_time = 0.0


# ── Exceptions ──────────────────────────────────────────────────────────────


class EnvirofactsError(Exception):
    """The service answered with something we cannot interpret.

    Also the base class for the other two, so a caller that only wants "the
    Envirofacts step failed" can catch this one — but the specific cases below
    are what an operator-facing message should branch on.
    """


class PwsidNotFound(EnvirofactsError):
    """EPA has no record of this PWSID (HTTP 200 with an empty array)."""

    def __init__(self, pwsid):
        self.pwsid = pwsid
        super().__init__(f"EPA has no water system with PWSID {pwsid}.")


class EnvirofactsUnavailable(EnvirofactsError):
    """EPA's service was unreachable or too slow. Never means 'not found'."""


# ── Transport ───────────────────────────────────────────────────────────────


def build_url(table, pwsid):
    """The one place an Envirofacts URL is assembled.

    ``build_url("WATER_SYSTEM", "CA1010001")`` →
    ``https://data.epa.gov/efservice/WATER_SYSTEM/PWSID/CA1010001/JSON``
    """
    return f"{BASE_URL}/{table}/PWSID/{pwsid}/JSON"


def _rate_limit():
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < RATE_LIMIT_SECONDS:
        time.sleep(RATE_LIMIT_SECONDS - elapsed)
    _last_request_time = time.time()


def _request(method, url, timeout=HTTP_TIMEOUT_SECONDS, max_retries=MAX_RETRIES, **kwargs):
    """HTTP with rate limiting and retry — the single seam tests monkeypatch.

    Structure copied from ``BaseAdapter._request``, with one deliberate
    difference: a 4xx response is RETURNED rather than raised. Envirofacts puts
    its error message in the body of a 404 (``{"error": "…"}``), so raising on
    status would throw away the only thing worth telling the operator. Retrying
    a 404 would also be pointless. 5xx and transport errors still retry and then
    propagate, and :func:`_payload` translates them.
    """
    _rate_limit()
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.request(method, url, timeout=timeout, **kwargs)
            if 400 <= resp.status_code < 500:
                return resp
            resp.raise_for_status()
            return resp
        except (requests.HTTPError, requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt < max_retries:
                backoff = 2 ** attempt
                logger.warning(
                    "envirofacts: attempt %d/%d failed (%s), retrying in %ds",
                    attempt, max_retries, exc, backoff,
                )
                time.sleep(backoff)
    raise last_exc


def _payload(table, pwsid):
    """Fetch and validate one table's envelope. Returns a list of row dicts.

    Emptiness is NOT interpreted here. A system with no facilities and a system
    that does not exist both arrive as ``[]``, and only the caller knows which
    one is legitimate — so the not-found decision lives in the ``fetch_*``
    functions, never on this shared path.
    """
    url = build_url(table, pwsid)
    try:
        resp = _request("GET", url)
    except (requests.Timeout, requests.ConnectionError) as exc:
        raise EnvirofactsUnavailable(
            "EPA's Envirofacts service did not respond in time. It is often slow; "
            "try again in a few minutes."
        ) from exc
    except requests.RequestException as exc:
        raise EnvirofactsUnavailable(
            f"EPA's Envirofacts service did not respond usefully: {exc}"
        ) from exc

    try:
        payload = resp.json()
    except ValueError as exc:
        raise EnvirofactsError(
            f"Envirofacts returned a body that is not JSON for {table}/{pwsid}."
        ) from exc

    # The error envelope is a different TYPE than the success envelope: success
    # is a list, an error is an object. Check before iterating.
    if isinstance(payload, dict):
        if "error" in payload:
            # Verbatim: the server's own message is the most actionable thing
            # we have, and paraphrasing it hides which table actually failed.
            raise EnvirofactsError(str(payload["error"]))
        raise EnvirofactsError(
            f"Envirofacts returned an unexpected object for {table}/{pwsid}: "
            f"{sorted(payload)[:5]}"
        )
    if not isinstance(payload, list):
        raise EnvirofactsError(
            f"Envirofacts returned an unexpected payload type "
            f"{type(payload).__name__} for {table}/{pwsid}."
        )
    return payload


# ── Cache ───────────────────────────────────────────────────────────────────


def _cached_rows(table, pwsid, refresh=False):
    """Return the raw row list for one table, via the cache when it is fresh."""
    if not refresh:
        row = EnvirofactsCache.objects.filter(pwsid=pwsid, table_name=table).first()
        if row is not None and not row.is_stale():
            return row.payload

    rows = _payload(table, pwsid)
    # update_or_create on the unique_together key: a stale entry is refreshed in
    # place, so the table can never accumulate two answers for one question.
    EnvirofactsCache.objects.update_or_create(
        pwsid=pwsid, table_name=table, defaults={"payload": rows}
    )
    return rows


# ── Public API ──────────────────────────────────────────────────────────────


def fetch_water_system(pwsid, refresh=False):
    """The system record. Returns ONE dict — WATER_SYSTEM is one row per PWSID.

    Raises :class:`PwsidNotFound` when EPA returns no rows. An empty result here
    is the authoritative "no such system"; we do not pre-validate the PWSID with
    a regex, because EPA's formats vary (``CA1010001`` vs ``083090017``) and an
    invented pattern would reject valid tribal and territory IDs.
    """
    rows = _cached_rows(TABLE_WATER_SYSTEM, pwsid, refresh=refresh)
    if not rows:
        raise PwsidNotFound(pwsid)
    return rows[0]


def fetch_facilities(pwsid, refresh=False):
    """The system's facilities. Returns a list, possibly empty.

    An empty list is NOT an error: a real system with no facilities on record is
    legitimate. Only :func:`fetch_water_system` decides that a system does not
    exist, so a facility-less system can never be reported as a bad PWSID.
    """
    return _cached_rows(TABLE_FACILITIES, pwsid, refresh=refresh)


def fetch_geographic_area(pwsid, refresh=False):
    """Service-geography hints. Returns one dict, or None when absent.

    Returns None rather than raising: geography is advisory display text (its
    ``area_type_code`` can even be comma-joined, e.g. ``"CN,CT"``), not a
    requirement for onboarding a system.
    """
    rows = _cached_rows(TABLE_GEOGRAPHIC_AREA, pwsid, refresh=refresh)
    return rows[0] if rows else None
