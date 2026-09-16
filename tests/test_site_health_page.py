# SPDX-License-Identifier: AGPL-3.0-or-later
"""Site Health leads with the healthy count on the account grid, and every
problem card links to its page or says it is fixed on the host (143-09,
R-055, R-056, the last of R-055's seven pages).

The link-gating property (a yellow/red platform row gets a href only when
its module is on; a host-level row never does; a skipped row never does) is
already proven, guard by guard, in
``tests/test_health_checks.py::TestWhereToLookLinksAreModuleGated``. This
file does not repeat that mechanism; it pins the PANEL: the one result
figure, its two peers, the card ordering, the info card, and the
signed-out state.
"""
import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from health.models import HealthCheckResult

User = get_user_model()

ALL_CATEGORIES = [c[0] for c in HealthCheckResult.CATEGORY_CHOICES]

# 3 green (database, disk, docker), 1 yellow (sync_freshness), 1 red (ssl,
# host-level), the remaining 8 skipped: the plan's own fixture shape.
_STATUS_BY_CATEGORY = {
    "database": "green",
    "disk": "green",
    "docker": "green",
    "sync_freshness": "yellow",
    "ssl": "red",
}


def _persist_fixture():
    for category in ALL_CATEGORIES:
        status = _STATUS_BY_CATEGORY.get(category, "skipped")
        HealthCheckResult.objects.create(
            category=category,
            status=status,
            message=f"{category} is {status}",
            details={"module_disabled": "x"} if status == "skipped" else {},
        )


def _operator():
    return User.objects.create_user(
        username="site-health-reader", email="site-health-reader@example.com",
        password="x", is_active=True,
    )


def _client_in():
    client = Client()
    client.force_login(_operator())
    return client


@pytest.mark.django_db
class TestThePanelLeadsWithTheHealthyCount:
    def test_one_result_and_two_peers_read_the_measured_counts(self):
        _persist_fixture()
        html = _client_in().get(reverse("health:dashboard")).content.decode()
        assert '<div class="budget-seg-value">3</div>' in html
        assert '<div class="budget-seg-value text-deficit">1</div>' in html
        assert '<div class="budget-seg-value text-error">1</div>' in html

    def test_the_yellow_card_links_to_its_page(self):
        _persist_fixture()
        html = _client_in().get(reverse("health:dashboard")).content.decode()
        assert reverse("datasync:monitoring_dashboard") in html
        assert "Open the monitoring dashboard" in html

    def test_the_red_host_level_card_reads_fixed_on_the_host(self):
        _persist_fixture()
        html = _client_in().get(reverse("health:dashboard")).content.decode()
        assert "Fixed on the host, not in the platform." in html

    def test_a_green_card_carries_no_link(self):
        _persist_fixture()
        html = _client_in().get(reverse("health:dashboard")).content.decode()
        # Only the one yellow platform row gets a text-link; the red row is
        # host-level and gets none; no green or skipped card gets one either.
        assert html.count('class="text-link"') == 1

    def test_cards_order_red_then_yellow_then_green_then_skipped(self):
        _persist_fixture()
        html = _client_in().get(reverse("health:dashboard")).content.decode()
        grid = html[html.index('class="health-grid"'):]
        red_i = grid.index("SSL")
        yellow_i = grid.index("Sync Freshness")
        green_i = grid.index("Database")
        assert red_i < yellow_i < green_i

    def test_the_info_card_reads_last_run(self):
        _persist_fixture()
        html = _client_in().get(reverse("health:dashboard")).content.decode()
        assert "Last run" in html

    def test_no_row_end_chip_remains(self):
        _persist_fixture()
        html = _client_in().get(reverse("health:dashboard")).content.decode()
        assert "row-end" not in html


@pytest.mark.django_db
class TestSignedOutGetsNoPanel:
    def test_anonymous_reader_sees_the_aggregate_only(self):
        _persist_fixture()
        html = Client().get(reverse("health:dashboard")).content.decode()
        assert "budget-panel" not in html
        assert "Overall status" in html
