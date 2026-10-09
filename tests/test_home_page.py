# SPDX-License-Identifier: AGPL-3.0-or-later
"""Plan 150-01: the signed-in home page offers what the deployment has.

The rule (Brent, 2026-10-08 19:54):

* **Start a task.** "Log water use" needs at least one use area to log against,
  and "Water balance" needs at least one water year to balance. Module flags
  alone cannot decide either tile: `surface` and `datasync` both pull `parcels`
  and `accounting` on, so a deployment can run accounting with no use area and
  no water year in it. Records decide.
* **Your data.** A counter renders only above zero, and the heading renders only
  when at least one counter does. Four counters join the five: Water rights,
  Monitoring stations, Water systems and Sample results, each behind its module.

Every assertion is scoped to the home page's own markup (`home-task-card`,
`home-stat`, `home-section-label`), never to the bare body: the sidebar prints
"Wells", "Water rights" and the rest on every page, so a body-wide `in` check
passes or fails on the nav and proves nothing about the page.

Rows are present in the module-off cases on purpose (ISS-091): an agency that
has been using a module and then switches it off still has the rows, and the
counter must follow the module, not the table.
"""
from html.parser import HTMLParser

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import get_resolver, reverse

from core import modules as mod
from tests.factories import (
    MonitoredStationFactory,
    ParcelFactory,
    PointOfDiversionFactory,
    RechargeSiteFactory,
    ReportingPeriodFactory,
    SampleResultFactory,
    WaterAccountFactory,
    WaterRightFactory,
    WaterSystemFactory,
    WellFactory,
)

#: Shape 2 of `scripts/shape_stack.sh`: the drinking-water utility flavor. The
#: `parcels`/`accounting` pair is off, which takes `wells`, `datasync`,
#: `surface`, `recharge` and `reporting` with it.
DRINKING_ONLY = [
    "core", "geography", "measurements", "standards", "drinking",
    "setup", "infrastructure", "health", "feedback",
]


def _without(*names):
    return [name for name in mod.ALL_MODULE_NAMES if name not in names]


#: The pending pin for the signed-in query count. STEP 2 replaces it with the
#: figure measured against the finished change, and nothing more.
HOME_QUERY_CEILING = 16


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention: every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"homepage{n}")
    email = factory.Sequence(lambda n: f"homepage{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def client_in(db):
    """A signed-in writer: the factory user is not a viewer, so
    `user_can_write` is True for it."""
    client = Client()
    client.force_login(UserFactory())
    return client


def _compose_full_urlconf():
    """Build the root URLconf under the full module set before a test narrows it.

    Same reason as `compose_urlconf_under_the_full_module_set` in
    tests/test_module_prose.py: `config/urls.py` composes its routes at import
    time, on the process's first request, so a test that narrows
    `OPENH2O_MODULES` and then makes that first request would leave every later
    test's `reverse(...)` dying with NoReverseMatch, in an order-dependent way.
    """
    get_resolver().url_patterns


# -- The home page parser ----------------------------------------------------


class _HomeAudit(HTMLParser):
    """The home page's task tiles, stat counters and section headings.

    Stdlib parser on purpose: this suite has no BeautifulSoup (same choice as
    tests/test_drinking_module_shows_what_to_do.py).
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        #: [{"href", "label"}] for every `a.home-task-card`, in page order.
        self.tasks = []
        #: [{"href", "value", "label"}] for every `a.home-stat`, in page order.
        self.stats = []
        #: Text of every `h2.home-section-label`, in page order.
        self.sections = []
        self._card = None
        self._field = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        if tag == "a" and "home-task-card" in classes:
            self._card = {"kind": "task", "href": attrs.get("href"), "label": ""}
        elif tag == "a" and "home-stat" in classes:
            self._card = {
                "kind": "stat", "href": attrs.get("href"), "value": "", "label": "",
            }
        elif tag == "span" and self._card is not None:
            if "home-task-label" in classes or "home-stat-label" in classes:
                self._field = "label"
            elif "home-stat-value" in classes:
                self._field = "value"
        elif tag == "h2" and "home-section-label" in classes:
            self.sections.append("")
            self._field = "section"

    def handle_data(self, data):
        if self._field == "section":
            self.sections[-1] += data
        elif self._field and self._card is not None:
            self._card[self._field] += data

    def handle_endtag(self, tag):
        if tag in ("span", "h2"):
            self._field = None
        elif tag == "a" and self._card is not None:
            card = {k: v.strip() if isinstance(v, str) else v for k, v in self._card.items()}
            kind = card.pop("kind")
            (self.tasks if kind == "task" else self.stats).append(card)
            self._card = None


def _home(client):
    response = client.get(reverse("index"))
    assert response.status_code == 200
    audit = _HomeAudit()
    audit.feed(response.content.decode())
    return audit


def _task_labels(audit):
    return [task["label"] for task in audit.tasks]


def _stat(audit, label):
    """The one counter carrying `label`, or None."""
    found = [stat for stat in audit.stats if stat["label"] == label]
    assert len(found) <= 1, f"{len(found)} counters labelled {label!r}"
    return found[0] if found else None


# -- 1, 2. Start a task: records decide two tiles ----------------------------


class TestStartATaskFollowsTheRecords:
    def test_log_water_use_needs_a_use_area(self, client_in):
        """Accounting on, a writer signed in, no use area: nothing to log
        against, so no tile. One use area brings it back."""
        assert "Log water use" not in _task_labels(_home(client_in))

        ParcelFactory()
        tasks = _home(client_in).tasks
        log = [task for task in tasks if task["label"] == "Log water use"]
        assert len(log) == 1
        assert log[0]["href"] == reverse("accounting:ledger_create")

    def test_water_balance_needs_a_water_year(self, client_in):
        """No water year: nothing to balance, so no tile. One brings it back."""
        assert "Water balance" not in _task_labels(_home(client_in))

        ReportingPeriodFactory()
        tasks = _home(client_in).tasks
        balance = [task for task in tasks if task["label"] == "Water balance"]
        assert len(balance) == 1
        assert balance[0]["href"] == reverse("accounting:dashboard")


# -- 3. A counter renders only above zero ------------------------------------


class TestACounterRendersOnlyAboveZero:
    def test_no_wells_counter_at_zero_and_one_at_one(self, client_in):
        """`wells` is on in the default set; with no well there is no "0 Wells"."""
        assert _stat(_home(client_in), "Wells") is None

        WellFactory()
        wells = _stat(_home(client_in), "Wells")
        assert wells is not None
        assert wells["value"] == "1"
        assert wells["href"] == reverse("wells:list")


# -- 4, 5. The four new counters ---------------------------------------------

#: (label, row factory, list URL name, module set with the owning module off).
#: `surface` cannot go alone: `recharge` requires it, so both leave together, as
#: WITHOUT_SURFACE does in tests/test_module_prose.py.
NEW_COUNTERS = [
    pytest.param(
        "Water rights", WaterRightFactory, "surface:water_rights_list",
        _without("surface", "recharge"), id="water-rights",
    ),
    pytest.param(
        "Monitoring stations", MonitoredStationFactory, "datasync:station_list",
        _without("datasync"), id="monitoring-stations",
    ),
    pytest.param(
        "Water systems", WaterSystemFactory, "drinking:overview",
        _without("drinking"), id="water-systems",
    ),
    pytest.param(
        "Sample results", SampleResultFactory, "drinking:results",
        _without("drinking"), id="sample-results",
    ),
]


class TestTheFourNewCounters:
    @pytest.mark.parametrize("label,row,url_name,modules_off", NEW_COUNTERS)
    def test_one_row_shows_the_counter_linking_to_its_list(
        self, client_in, label, row, url_name, modules_off
    ):
        row()
        stat = _stat(_home(client_in), label)
        assert stat is not None, f"no {label!r} counter with one row present"
        assert stat["value"] == "1"
        assert stat["href"] == reverse(url_name)

    @pytest.mark.parametrize("label,row,url_name,modules_off", NEW_COUNTERS)
    def test_the_counter_is_gone_with_its_module_off(
        self, client_in, settings, label, row, url_name, modules_off
    ):
        """The row stays in the table; the counter follows the module."""
        _compose_full_urlconf()
        row()
        settings.OPENH2O_MODULES = modules_off
        assert _stat(_home(client_in), label) is None


# -- 6. The drinking-water flavor, with rows ---------------------------------


def test_drinking_only_deployment_with_rows(client_in, settings):
    """Shape 2 with one water system and one sample result in it.

    No accounting, so neither accounting tile; the bar carries exactly the two
    drinking counters, in the rule's order.
    """
    _compose_full_urlconf()
    system = WaterSystemFactory()
    SampleResultFactory(event__sampling_point__facility__system=system)
    settings.OPENH2O_MODULES = DRINKING_ONLY

    audit = _home(client_in)  # asserts the 200
    labels = _task_labels(audit)
    assert "Log water use" not in labels
    assert "Water balance" not in labels
    assert "Your data" in audit.sections
    assert [(s["label"], s["value"], s["href"]) for s in audit.stats] == [
        ("Water systems", "1", reverse("drinking:overview")),
        ("Sample results", "1", reverse("drinking:results")),
    ]


# -- 7. No heading over an empty bar -----------------------------------------


def test_your_data_heading_absent_when_every_count_is_zero(client_in):
    """Every module on, no rows: no counter, and so no "Your data" heading
    standing over nothing."""
    audit = _home(client_in)
    assert audit.stats == []
    assert "Your data" not in audit.sections


# -- 8. The signed-in query count is bounded ---------------------------------


def test_signed_in_home_query_count_is_bounded(client_in):
    """Every module on, one row of each kind the page counts or tests.

    Measured: 16 queries on 2026-10-08 (12 before this plan's change; the water-year
    existence check and the three new counts add four), pinned plus nothing.

    One warm-up request comes first, so process-wide caches (content types,
    and anything else memoised on first use) are filled before the measured
    request and the figure does not depend on which test ran before this one.
    """
    ParcelFactory()
    WellFactory()
    PointOfDiversionFactory()  # brings its one WaterRight with it
    RechargeSiteFactory()
    WaterAccountFactory()
    MonitoredStationFactory()
    SampleResultFactory()  # brings its one WaterSystem with it
    ReportingPeriodFactory()

    client_in.get(reverse("index"))
    with CaptureQueriesContext(connection) as captured:
        response = client_in.get(reverse("index"))
    assert response.status_code == 200

    measured = len(captured)
    assert HOME_QUERY_CEILING is not None, (
        f"measured {measured} queries for the signed-in home page; pin this figure"
    )
    assert measured <= HOME_QUERY_CEILING, (
        f"the signed-in home page ran {measured} queries, ceiling {HOME_QUERY_CEILING}"
    )
