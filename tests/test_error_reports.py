# SPDX-License-Identifier: AGPL-3.0-or-later
"""What the optional error reports may send (core/error_reports.py).

The rule under test: an exception's type and stack may leave the site, and nothing a
person typed, no record's contents, no request, header, cookie, address or local
variable. Events are caught by an in-memory transport, so nothing is sent anywhere.
"""

import io
import json
import os
from unittest import mock

import sentry_sdk
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.signals import got_request_exception
from django.http import Http404, HttpResponse
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import include, path
from sentry_sdk.envelope import Envelope, Item, PayloadRef
from sentry_sdk.transport import HttpTransport

from core import error_reports

def _raises_typed_text(request):
    well_name = request.POST.get("well_name", "")
    secret_local = request.POST.get("api_key", "")  # noqa: F841 - must never leave as a frame variable
    try:
        int(well_name)
    except ValueError as exc:
        raise RuntimeError(f"could not save the reading for {well_name}") from exc


def _raises_a_group(request):
    well_name = request.POST.get("well_name", "")
    raise ExceptionGroup(f"two readings failed for {well_name}", [ValueError(well_name), KeyError(well_name)])


def _not_found(request):
    raise Http404("no such well")


def _refused(request):
    raise PermissionDenied("not yours")


def _fine(request):
    return HttpResponse("ok")


urlpatterns = [
    path("boom", _raises_typed_text),
    path("group", _raises_a_group),
    path("missing", _not_found),
    path("refused", _refused),
    path("fine", _fine),
    # The site's own routes too: the 404 and 403 pages link to them by name.
    path("", include("config.urls")),
]

FAKE_DSN = "http://0123456789abcdef0123456789abcdef@localhost:9/2"


# Kept well away from the views above: a frame carries the source lines around it.
TYPED = "Reyes Ranch north well 7, meter 004471, owner Alma Reyes"


class ReportingOn:
    """Turns reporting on with a fake DSN; records what the site's own transport would send.

    The client keeps the transport init() gives it (error events only). Only the HTTP send
    underneath is replaced, so every envelope that would leave is recorded, whole.
    """

    def setUp(self):
        super().setUp()
        self.addCleanup(self._off)
        error_reports._enabled = False
        self.envelopes = []
        sender = mock.patch.object(HttpTransport, "capture_envelope", autospec=True,
                                   side_effect=lambda transport, envelope: self.envelopes.append(envelope))
        sender.start()
        self.addCleanup(sender.stop)
        with mock.patch.dict(os.environ, {"SENTRY_DSN": FAKE_DSN, "SENTRY_ENVIRONMENT": "staging"}):
            error_reports.init()

    def _off(self):
        # dsn="" and not None: None falls back to SENTRY_DSN from the environment, which would
        # start a live client with no scrubber wherever the suite runs beside a real DSN.
        sentry_sdk.init(dsn="", default_integrations=False)
        error_reports._enabled = False

    @property
    def events(self):
        for envelope in self.envelopes:
            self.assertEqual([item.type for item in envelope.items], ["event"])
            self.assertLessEqual(set(envelope.headers), {"event_id", "sent_at", "sdk"})
        return [envelope.get_event() for envelope in self.envelopes]

    def only_event(self):
        events = self.events
        self.assertEqual(len(events), 1, events)
        return events[0]

    def assert_nothing_private(self, event):
        text = json.dumps(event)
        for private in ("Alma", "Reyes", "004471", "sk-live", "0123456789abcdef", "testserver"):
            self.assertNotIn(private, text)
        for key in ("request", "user", "breadcrumbs", "extra", "modules", "message", "logentry",
                    "server_name", "transaction"):
            self.assertNotIn(key, event)


@override_settings(ROOT_URLCONF=__name__, APP_VERSION="v9.9-1-gabcdef0")
class ViewExceptionTests(ReportingOn, TestCase):
    def test_a_500_sends_its_types_and_stack_and_nothing_the_person_typed(self):
        response = Client(raise_request_exception=False).post(
            "/boom?search=Alma", {"well_name": TYPED, "api_key": "sk-live-abcdefghijklmnop"},
            HTTP_COOKIE="sessionid=Alma", HTTP_X_FORWARDED_FOR="203.0.113.9", HTTP_REFERER="/wells/Reyes/")
        self.assertEqual(response.status_code, 500)
        event = self.only_event()
        self.assert_nothing_private(event)
        values = event["exception"]["values"]
        self.assertEqual([v["type"] for v in values], ["ValueError", "RuntimeError"])
        self.assertEqual({v["value"] for v in values}, {error_reports.WITHHELD})
        frames = values[-1]["stacktrace"]["frames"]
        self.assertEqual(frames[-1]["function"], "_raises_typed_text")
        self.assertTrue(all("vars" not in f for f in frames))
        self.assertEqual(event["release"], "v9.9-1-gabcdef0")
        self.assertEqual(event["environment"], "staging")
        self.assertEqual(set(event.get("contexts", {})) - {"runtime"}, set())

    def test_an_exception_group_withholds_every_message(self):
        response = Client(raise_request_exception=False).post("/group", {"well_name": TYPED})
        self.assertEqual(response.status_code, 500)
        event = self.only_event()
        self.assert_nothing_private(event)
        values = event["exception"]["values"]
        self.assertEqual({v["type"] for v in values}, {"ExceptionGroup", "ValueError", "KeyError"})
        self.assertEqual({v["value"] for v in values}, {error_reports.WITHHELD})

    def test_the_signal_fallback_reports_an_exception_outside_a_view(self):
        try:
            raise RuntimeError(TYPED)
        except RuntimeError:
            got_request_exception.send(sender=None, request=None)
        event = self.only_event()
        self.assert_nothing_private(event)
        self.assertEqual(event["exception"]["values"][-1]["type"], "RuntimeError")

    def test_a_404_a_403_and_a_good_request_send_nothing(self):
        client = Client(raise_request_exception=False)
        self.assertEqual(client.get("/missing").status_code, 404)
        self.assertEqual(client.get("/refused").status_code, 403)
        self.assertEqual(client.get("/fine").status_code, 200)
        self.assertEqual(self.events, [])


@override_settings(APP_VERSION="v9.9-1-gabcdef0")
class TestEventTests(ReportingOn, SimpleTestCase):
    def test_the_command_sends_one_event_and_prints_its_id(self):
        out = io.StringIO()
        call_command("error_report_test_event", stdout=out)
        event = self.only_event()
        self.assertIn(event["event_id"], out.getvalue())
        self.assertIn("v9.9-1-gabcdef0", out.getvalue())
        value = event["exception"]["values"][-1]
        self.assertEqual(value["type"], "ErrorReportTestEvent")
        # not wording: the test event's fixed text is the one message allowed out
        self.assertEqual(value["value"], error_reports.TEST_EVENT_TEXT)
        self.assertEqual(event["tags"], {"test": "true"})


class TransportTests(ReportingOn, SimpleTestCase):
    def test_only_error_events_leave_through_the_transport(self):
        transport = sentry_sdk.get_client().transport
        self.assertIsInstance(transport, HttpTransport)
        other = [Item(payload=PayloadRef(json={"q": TYPED}), type=kind)
                 for kind in ("session", "log", "trace_metric", "transaction", "attachment", "check_in")]
        transport.capture_envelope(Envelope(headers={"trace": {"transaction": TYPED}}, items=other))
        self.assertEqual(self.envelopes, [])
        event = Item(payload=PayloadRef(json={"event_id": "e"}), type="event")
        transport.capture_envelope(Envelope(headers={"event_id": "e", "trace": {"transaction": TYPED}},
                                            items=[event, *other]))
        self.assertEqual(len(self.events), 1)
        self.assertNotIn(TYPED, json.dumps(self.envelopes[0].headers))


class StartLineTests(SimpleTestCase):
    def tearDown(self):
        sentry_sdk.init(dsn="", default_integrations=False)
        error_reports._enabled = False

    def test_the_web_server_logs_the_host_and_never_the_key(self):
        error_reports._enabled = False
        with mock.patch.dict(os.environ, {"SENTRY_DSN": FAKE_DSN}), \
                mock.patch.object(error_reports.sys, "argv", ["/usr/local/bin/gunicorn"]), \
                self.assertLogs("core.error_reports", "WARNING") as logs:
            error_reports.init()
        self.assertEqual(len(logs.output), 1)
        self.assertIn("localhost:9", logs.output[0])
        self.assertNotIn("0123456789abcdef", logs.output[0])

    def test_the_debug_page_filter_hides_a_dsn(self):
        from django.views.debug import SafeExceptionReporterFilter

        from core.error_reports import HidingDsnFilter

        self.assertEqual(HidingDsnFilter().cleanse_setting("SENTRY_DSN", FAKE_DSN),
                         SafeExceptionReporterFilter.cleansed_substitute)


class ScrubTests(SimpleTestCase):
    def test_unknown_fields_tags_contexts_and_frame_variables_are_dropped(self):
        event = {
            "event_id": "x", "level": "error", "request": {"data": TYPED}, "user": {"ip_address": "1.2.3.4"},
            "breadcrumbs": {"values": [{"message": TYPED}]}, "extra": {"q": TYPED},
            "some_future_field": TYPED, "server_name": "district-server", "transaction": "/wells/Reyes/",
            "tags": {"url": TYPED, "test": "true"},
            "contexts": {"runtime": {"name": "CPython"}, "response": {"body": TYPED}, "os": {"name": "Linux"}},
            "exception": {"values": [{"type": "KeyError", "value": TYPED, "stacktrace": {
                "frames": [{"function": "f", "lineno": 3, "vars": {"q": TYPED}}], "registers": {"r": TYPED}}}]},
        }
        scrubbed = error_reports._scrub(event)
        self.assertNotIn(TYPED, json.dumps(scrubbed))
        self.assertNotIn("district-server", json.dumps(scrubbed))
        self.assertEqual(scrubbed["contexts"], {"runtime": {"name": "CPython"}})
        self.assertEqual(scrubbed["tags"], {"test": "true"})
        self.assertEqual(scrubbed["exception"]["values"][0]["stacktrace"], {"frames": [{"function": "f", "lineno": 3}]})

    def test_exception_entries_keep_only_reviewed_keys_and_attachments_are_dropped(self):
        hint = {"attachments": ["bytes a person uploaded"]}
        event = {"exception": {"values": [{
            "type": "OSError", "value": TYPED, "some_future_field": TYPED,
            "mechanism": {"type": "generic", "handled": True, "meta": {"errno": {"number": TYPED}},
                          "data": {"q": TYPED}}}]}}
        scrubbed = error_reports._scrub(event, hint)
        self.assertNotIn(TYPED, json.dumps(scrubbed))
        self.assertEqual(scrubbed["exception"]["values"][0]["mechanism"], {"type": "generic", "handled": True})
        self.assertNotIn("attachments", hint)

    def test_the_test_event_type_with_other_text_is_withheld_too(self):
        event = {"exception": {"values": [{"type": "ErrorReportTestEvent", "value": TYPED}]}}
        self.assertEqual(error_reports._scrub(event)["exception"]["values"][0]["value"], error_reports.WITHHELD)

    def test_a_message_only_event_is_not_sent(self):
        self.assertIsNone(error_reports._scrub({"message": TYPED, "level": "error"}))


class OffTests(SimpleTestCase):
    def test_without_a_dsn_nothing_starts_and_the_command_says_so(self):
        error_reports._enabled = False
        with mock.patch.dict(os.environ, {"SENTRY_DSN": ""}):
            error_reports.init()
        self.assertFalse(error_reports.enabled())
        self.assertIsNone(error_reports.report(RuntimeError("x")))
        with self.assertRaises(CommandError):
            call_command("error_report_test_event", stdout=io.StringIO())

    @override_settings(APP_VERSION="dev")
    def test_an_unstamped_build_has_no_release(self):
        self.assertIsNone(error_reports._release())
