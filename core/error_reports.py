# SPDX-License-Identifier: AGPL-3.0-or-later
"""Optional error reports to a Sentry-protocol server (Sentry or GlitchTip).

Off unless ``SENTRY_DSN`` is set in the site's settings file. A site that leaves it
out sends nothing anywhere, and nothing in this module runs beyond reading that one
setting. ``SENTRY_ENVIRONMENT`` names the copy (``production`` when it is not set,
``staging`` for a test copy). The release is the version stamped into the image at
build (``APP_VERSION``, the same text the page footer shows).

What leaves the site, and what does not. A district's records, and anything a person
typed into a form, an import or a search, must never leave. So the SDK runs with NONE
of its automatic integrations (no Django, logging, stdlib or threading hooks: they
record request bodies, addresses, log lines and breadcrumbs), no tracing, no
profiling, no local variables and no request data. What is sent is the exception's
TYPE and its stack (file, function, line and the source lines around it, which are
this repository's public code), the release, the environment and the runtime.
Exception MESSAGES are withheld, every one, because a message can quote a value a
person typed or a record's contents, and there is no reliable way to tell which do;
the full message and traceback stay in the site's own log (``django.request`` logs
"Internal Server Error: ..." at the same moment), where the report's time finds
them. Two locks hold this, whatever a later change to the init might add: ``_scrub``
rewrites every error event to the reviewed fields, and the transport sends nothing but
error events (no sessions, logs, metrics, transactions, profiles, attachments or check-ins,
which never pass through ``_scrub``).

What is reported: an exception a view raises that Django turns into a 500 (the
middleware below), and, as a fallback, the ``got_request_exception`` signal. Http404,
PermissionDenied, BadRequest and SuspiciousOperation are the caller's doing and are
not reported. Scheduled commands report nothing.

A test event, from inside the running web container:
``python manage.py error_report_test_event`` sends one ErrorReportTestEvent and
prints its event id. Repeats come from the same code, so they group into one issue.
"""

import logging
import os
import re
import sys

from django.conf import settings
from django.core.exceptions import BadRequest, PermissionDenied, SuspiciousOperation
from django.http import Http404
from django.views.debug import SafeExceptionReporterFilter

logger = logging.getLogger(__name__)

_enabled = False

WITHHELD = "[message withheld: see the site's log at this time]"

# Event keys that may leave the site. Everything else is dropped, so a field a later SDK
# version adds (or a later change to the init turns on) does not leave without review.
_KEEP_KEYS = {
    "event_id", "timestamp", "platform", "level", "logger", "release", "environment",
    "exception", "tags", "contexts", "sdk", "fingerprint",
}
_KEEP_CONTEXTS = {"runtime"}
_FRAME_KEYS = {
    "filename", "abs_path", "function", "module", "lineno", "colno", "in_app",
    "pre_context", "context_line", "post_context",
}
_EXCEPTION_KEYS = {"type", "module", "value", "stacktrace", "mechanism"}
# mechanism.meta (errno, signal numbers) and mechanism.data are dropped: an exception class
# can fill them from its own attributes.
_MECHANISM_KEYS = {"type", "handled", "exception_id", "parent_id", "source", "is_exception_group"}
_KEEP_TAGS = {"test"}
_NOT_OURS = (Http404, PermissionDenied, BadRequest, SuspiciousOperation)


class ErrorReportTestEvent(Exception):
    """The test event. Its message is fixed text, so it is the one message sent."""


TEST_EVENT_TEXT = "Test event sent from inside the running site (manage.py error_report_test_event)"


def enabled():
    return _enabled


def _release():
    """The version stamped into the image at build, or None for an unstamped build."""
    version = (getattr(settings, "APP_VERSION", "") or "").strip()
    if not version or version == "dev":
        return None
    return version[:200]


def _scrub(event, hint=None):
    """Keep only the allowed fields; withhold every exception message but the test event's."""
    if isinstance(hint, dict):
        # Scope attachments ride in the hint and would be sent beside the event, unscrubbed.
        hint.pop("attachments", None)
    for key in list(event):
        if key not in _KEEP_KEYS:
            del event[key]
    contexts = event.get("contexts")
    if isinstance(contexts, dict):
        event["contexts"] = {k: v for k, v in contexts.items() if k in _KEEP_CONTEXTS}
    tags = event.get("tags")
    if isinstance(tags, dict):
        event["tags"] = {k: v for k, v in tags.items() if k in _KEEP_TAGS}
    elif "tags" in event:
        del event["tags"]
    exception = event.get("exception")
    values = exception.get("values", []) if isinstance(exception, dict) else []
    if not values:
        # Only exceptions are reported. A bare message event (capture_message) could carry
        # anything, so it does not leave.
        return None
    event["exception"] = {"values": values}
    for i, value in enumerate(values):
        value = values[i] = {k: v for k, v in value.items() if k in _EXCEPTION_KEYS}
        if isinstance(value.get("mechanism"), dict):
            value["mechanism"] = {k: v for k, v in value["mechanism"].items() if k in _MECHANISM_KEYS}
        if value.get("type") != ErrorReportTestEvent.__name__ or value.get("value") != TEST_EVENT_TEXT:
            value["value"] = WITHHELD
        stacktrace = value.get("stacktrace")
        if isinstance(stacktrace, dict):
            value["stacktrace"] = {"frames": [
                {k: v for k, v in frame.items() if k in _FRAME_KEYS}
                for frame in stacktrace.get("frames", [])
                if isinstance(frame, dict)
            ]}
    return event


def _drop(item, hint=None):
    return None


def _events_only_transport():
    """The SDK's HTTP transport, narrowed to send error events and nothing else."""
    from sentry_sdk.envelope import Envelope
    from sentry_sdk.transport import HttpTransport

    class EventsOnlyTransport(HttpTransport):
        def capture_envelope(self, envelope):
            items = [item for item in envelope.items if item.type == "event"]
            if not items:
                return None
            headers = {k: v for k, v in envelope.headers.items() if k in ("event_id", "sent_at", "sdk")}
            return super().capture_envelope(Envelope(headers=headers, items=items))

    return EventsOnlyTransport


def init():
    """Start reporting if SENTRY_DSN is set. Called once from CoreConfig.ready()."""
    global _enabled
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn or _enabled:
        return
    import sentry_sdk
    from sentry_sdk.integrations.dedupe import DedupeIntegration

    release = _release()
    environment = os.environ.get("SENTRY_ENVIRONMENT", "").strip() or "production"
    sentry_sdk.init(
        dsn=dsn,
        release=release,
        environment=environment,
        default_integrations=False,
        auto_enabling_integrations=False,
        integrations=[DedupeIntegration()],
        send_default_pii=False,
        include_local_variables=False,
        include_source_context=True,
        max_request_body_size="never",
        max_breadcrumbs=0,
        attach_stacktrace=False,
        traces_sample_rate=None,
        profiles_sample_rate=None,
        send_client_reports=False,
        spotlight=False,
        debug=False,
        before_send=_scrub,
        # Every other kind of data the SDK can send is closed here as well as at the transport.
        before_send_transaction=_drop,
        enable_logs=False,
        before_send_log=_drop,
        enable_metrics=False,
        before_send_metric=_drop,
        auto_session_tracking=False,
        transport=_events_only_transport(),
    )
    _enabled = True
    if os.path.basename(sys.argv[0] if sys.argv else "") == "gunicorn":
        # One line per web worker at start, so the site's log shows reporting is on.
        # Scheduled commands start Django too and stay quiet.
        logger.warning("error reports: sending to %s (release %s, environment %s)",
                       _host_of(dsn), release or "unknown", environment)


def _host_of(dsn):
    """The DSN's host only, for the start line: the key before the @ is never logged."""
    rest = dsn.split("://", 1)[-1]
    return rest.rsplit("@", 1)[-1].split("/", 1)[0]


def report(exception):
    """Send one exception. A no-op when reporting is off or the exception is the caller's doing."""
    if not _enabled or isinstance(exception, _NOT_OURS):
        return None
    if getattr(exception, "_error_reported", False):
        return None
    import sentry_sdk

    try:
        exception._error_reported = True
    except AttributeError:
        pass
    return sentry_sdk.capture_exception(exception)


class HidingDsnFilter(SafeExceptionReporterFilter):
    """Django's own filter, also hiding any setting or environment value named like a DSN."""

    hidden_settings = re.compile(
        SafeExceptionReporterFilter.hidden_settings.pattern + "|DSN", flags=re.I
    )


class ReportExceptionsMiddleware:
    """Reports an exception a view raised. Returns nothing, so Django's 500 handling goes on.

    First in MIDDLEWARE, so its process_exception runs last: an exception another
    middleware turns into a page of its own (the finalized-period 409) is not reported.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        report(exception)
        return None


def on_request_exception(sender, request=None, **kwargs):
    """got_request_exception fallback: an exception outside a view, while it is still visible."""
    exception = sys.exc_info()[1]
    if exception is not None:
        report(exception)


def send_test_event():
    """Send one ErrorReportTestEvent; return its event id, or None when reporting is off."""
    if not _enabled:
        return None
    import sentry_sdk

    try:
        raise ErrorReportTestEvent(TEST_EVENT_TEXT)
    except ErrorReportTestEvent as exc:
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("test", "true")
            event_id = sentry_sdk.capture_exception(exc)
    sentry_sdk.flush(timeout=10)
    return event_id
