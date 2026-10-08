# SPDX-License-Identifier: AGPL-3.0-or-later
"""Site Health's Calculation card (149-01 Task 4): one test per state, with
the status and the exact sentence, plus the skipped case and the dashboard for
each kind of reader (error_detail is for administrators only)."""
import datetime as dt

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from accounting.models import CalculationRequest, ReportingPeriod
from core import modules as mod
from health.checks import check_calculation, run_all_checks
from health.models import HealthCheckResult
from tests.test_module_prose import compose_urlconf_under_the_full_module_set

SECRET = "Traceback: KeyError 'secret-detail-xyz'"


def _period(name="WY 2026"):
    return ReportingPeriod.objects.create(
        name=name, start_date=dt.date(2025, 10, 1), end_date=dt.date(2026, 9, 30)
    )


def _request(status, *, period=None, requested_ago=None, started_ago=None,
             finished_ago=None, **fields):
    now = timezone.now()
    req = CalculationRequest.objects.create(
        status=status, reporting_period=period, **fields
    )
    # requested_at is auto_now_add, so set it with an update.
    updates = {"requested_at": now - (requested_ago or dt.timedelta(hours=1))}
    if started_ago is not None:
        updates["started_at"] = now - started_ago
    if finished_ago is not None:
        updates["finished_at"] = now - finished_ago
    CalculationRequest.objects.filter(pk=req.pk).update(**updates)
    req.refresh_from_db()
    return req


def _stamp(req):
    from django.utils.dateformat import format as fmt
    return fmt(timezone.localtime(req.finished_at), r"F j, Y \a\t g:i A")


class TestStates:
    def test_never_run_is_yellow(self):
        r = check_calculation()
        assert r["status"] == "yellow"
        assert r["message"] == (
            "The calculation has never run on this site. Run it from a "
            "water year's page."
        )

    def test_succeeded_is_green(self):
        p = _period()
        req = _request(
            "succeeded", period=p, months=["2026-01", "2026-02", "2026-03"],
            finished_ago=dt.timedelta(hours=3), outcome="Done.",
        )
        r = check_calculation()
        assert r["status"] == "green"
        assert r["message"] == f"Last calculated {_stamp(req)}, WY 2026, 3 months."
        assert r["details"]["request_id"] == req.pk
        assert r["details"]["reporting_period_id"] == p.pk
        assert "where_href" not in r["details"]

    def test_succeeded_without_a_period_omits_it(self):
        req = _request("succeeded", months=["2026-01"],
                       finished_ago=dt.timedelta(hours=3))
        assert check_calculation()["message"] == (
            f"Last calculated {_stamp(req)}, 1 month."
        )

    def test_finished_with_notes_is_yellow_with_first_note(self):
        p = _period()
        req = _request(
            "finished_with_notes", period=p, months=["2026-01", "2026-02"],
            finished_ago=dt.timedelta(hours=3),
            notes=["No satellite ET for February 2026.", "Second note."],
        )
        r = check_calculation()
        assert r["status"] == "yellow"
        assert r["message"] == (
            f"Last calculated {_stamp(req)}, WY 2026, 2 months. "
            "No satellite ET for February 2026."
        )
        assert r["details"]["where_href"] == reverse(
            "accounting:period_detail", args=[p.pk]
        )

    def test_failed_is_red_with_its_outcome(self):
        p = _period()
        _request("failed", period=p, finished_ago=dt.timedelta(hours=3),
                 outcome="This period is finalized, so it cannot be recalculated.")
        r = check_calculation()
        assert r["status"] == "red"
        assert r["message"] == (
            "This period is finalized, so it cannot be recalculated."
        )

    def test_latest_finished_decides(self):
        _request("failed", finished_ago=dt.timedelta(days=2), outcome="Old.")
        _request("succeeded", months=["2026-01"], finished_ago=dt.timedelta(hours=1))
        assert check_calculation()["status"] == "green"

    def test_queued_over_fifteen_minutes_is_yellow(self):
        req = _request("queued", requested_ago=dt.timedelta(minutes=20))
        from django.utils.dateformat import format as fmt
        when = fmt(timezone.localtime(req.requested_at), r"F j, Y \a\t g:i A")
        r = check_calculation()
        assert r["status"] == "yellow"
        assert r["message"] == (
            f"A calculation has been waiting to start since {when}. The "
            "program that runs it is not running; an administrator should "
            "check the server."
        )

    def test_queued_under_fifteen_minutes_is_not_flagged(self):
        _request("queued", requested_ago=dt.timedelta(minutes=5))
        assert check_calculation()["message"].startswith("The calculation has never run")

    def test_stale_running_is_marked_failed_and_red(self):
        p = _period()
        req = _request("running", period=p, requested_ago=dt.timedelta(hours=4),
                       started_ago=dt.timedelta(hours=3))
        r = check_calculation()
        sentence = (
            "The calculation stopped without finishing, probably because the "
            "server restarted. Run it again from the period's page."
        )
        assert r["status"] == "red"
        assert r["message"] == sentence
        req.refresh_from_db()
        assert req.status == "failed"
        assert req.finished_at is not None
        assert req.outcome == sentence

    def test_recent_running_is_left_alone(self):
        req = _request("running", started_ago=dt.timedelta(minutes=30))
        check_calculation()
        req.refresh_from_db()
        assert req.status == "running"


class TestModuleOff:
    def test_skipped_and_excluded_from_counts(self, settings, client, django_user_model):
        # parcels and accounting are an inseparable pair, and switching the
        # pair off takes wells, datasync, surface, recharge and reporting with
        # it (CLAUDE.md, the module composition rule): the drinking-water set.
        compose_urlconf_under_the_full_module_set()
        settings.OPENH2O_MODULES = [
            n for n in mod.ALL_MODULE_NAMES
            if n not in (
                "parcels", "accounting", "wells", "datasync", "surface",
                "recharge", "reporting",
            )
        ]
        r = check_calculation()
        assert r["status"] == "skipped"
        assert r["details"] == {"module_disabled": "accounting"}
        HealthCheckResult.objects.create(**r)
        HealthCheckResult.objects.create(
            category="database", status="green", message="ok", details={}
        )
        client.force_login(
            django_user_model.objects.create_user(username="u", password="x")
        )
        ctx = client.get(reverse("health:dashboard")).context
        assert ctx["skipped"] == 1
        assert ctx["applicable"] == 1

    def test_run_all_checks_includes_it(self):
        assert "calculation" in [c["category"] for c in run_all_checks()]


class TestDashboard:
    def _persist(self):
        p = _period()
        _request("failed", period=p, finished_ago=dt.timedelta(hours=1),
                 outcome="The calculation stopped at March 2026.",
                 error_detail=SECRET)
        HealthCheckResult.objects.create(**check_calculation())
        return p

    def _client(self, django_user_model, **flags):
        u = django_user_model.objects.create_user(
            username=f"u{len(flags)}{sorted(flags)}", password="x", **flags
        )
        c = Client()
        c.force_login(u)
        return c

    def test_anonymous_sees_aggregate_only(self):
        self._persist()
        r = Client().get(reverse("health:dashboard"))
        assert r.status_code == 200
        body = r.content.decode()
        assert SECRET not in body
        assert "The calculation stopped at March 2026." not in body

    def test_operator_sees_card_without_error_detail(self, django_user_model):
        p = self._persist()
        r = self._client(django_user_model).get(reverse("health:dashboard"))
        assert r.status_code == 200
        body = r.content.decode()
        assert "The calculation stopped at March 2026." in body
        assert reverse("accounting:period_detail", args=[p.pk]) in body
        assert SECRET not in body

    def test_viewer_never_sees_error_detail(self, django_user_model):
        self._persist()
        body = self._client(django_user_model, read_only=True).get(
            reverse("health:dashboard")
        ).content.decode()
        assert SECRET not in body

    def test_administrator_sees_error_detail(self, django_user_model):
        self._persist()
        r = self._client(django_user_model, agency_admin=True).get(
            reverse("health:dashboard")
        )
        assert r.status_code == 200
        assert "secret-detail-xyz" in r.content.decode()
