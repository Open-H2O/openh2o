# SPDX-License-Identifier: AGPL-3.0-or-later
"""Demo-honesty marker gating (Phase 64 Plan 01).

The Merced demo is shown to outside evaluators. A surface water-right in the
``curtailed``/``revoked`` state renders the real Water Board legal term, which an
evaluator could mistake for an actual curtailment order on what is sample data.
A flag-gated ``DEMO`` meta-label disambiguates it — but ONLY when
``SiteConfig.demonstration_mode`` is on, so a real production instance renders
exactly as before.

These tests lock the gate through the request path (so the
``core.context_processors.site_config`` processor actually runs — rendering the
partial directly would bypass it):

  - present iff demonstration_mode, AND
  - only on legal-action statuses (curtailed/revoked), never on ``active``, AND
  - real-instance output (flag off) keeps the original Status caption untouched.

**Phase 101 added the second half of this file, and it is the same gate rather
than a new one.** ``templates/wells/partials/_detail_pane.html`` included the
marker UNCONDITIONALLY on the Identification header, so on the public
demonstration every well wore a "sample data" pill — including the municipal
supply sources a drinking-water system lists as its facilities, whose identity is
published record and whose coordinates are real GAMA publications. Those tests
live here, beside the four above, because the thing being changed is where this
marker is allowed to appear.
"""

import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from core.models import SiteConfig
from core.modules import is_enabled
from tests.factories import WaterRightFactory, WellFactory

if is_enabled("drinking"):
    from drinking import provenance


def _login():
    """A logged-in client (the detail view requires authentication)."""
    from core.models import User

    user = User.objects.create(
        username="evaluator",
        email="evaluator@example.com",
        password=make_password("testpass123"),
        is_active=True,
    )
    client = Client()
    client.force_login(user)
    return client


def _detail_body(status, *, demonstration_mode):
    SiteConfig.objects.create(
        agency_name="Demo GSA", demonstration_mode=demonstration_mode
    )
    water_right = WaterRightFactory(status=status)
    client = _login()
    resp = client.get(reverse("surface:detail", args=[water_right.pk]))
    assert resp.status_code == 200
    return resp.content.decode()


@pytest.mark.django_db
class TestDemoMarkerGating:
    def test_curtailed_shows_marker_in_demo_mode(self):
        body = _detail_body("curtailed", demonstration_mode=True)
        assert "badge-demo" in body
        assert ">DEMO<" in body

    def test_revoked_shows_marker_in_demo_mode(self):
        body = _detail_body("revoked", demonstration_mode=True)
        assert "badge-demo" in body
        assert ">DEMO<" in body

    def test_active_never_shows_marker_even_in_demo_mode(self):
        # `active` does not read as a legal action — the marker must not appear.
        body = _detail_body("active", demonstration_mode=True)
        assert "badge-demo" not in body
        assert ">DEMO<" not in body

    def test_curtailed_no_marker_and_original_caption_on_real_instance(self):
        body = _detail_body("curtailed", demonstration_mode=False)
        # Real instance: no marker at all.
        assert "badge-demo" not in body
        assert ">DEMO<" not in body
        # And the Status caption is byte-for-byte the pre-Phase-64 text — the
        # demo-only clause must be absent.
        assert "Curtailed rights are temporarily restricted." in body
        assert "illustrative sample data" not in body


# ---------------------------------------------------------------------------
# Phase 101: the wells Identification header
# ---------------------------------------------------------------------------

pytestmark_drinking = pytest.mark.skipif(
    not is_enabled("drinking"),
    reason="the drinking module is not installed in this process",
)


def _well_pane(well, *, demonstration_mode):
    """The rendered detail pane for one well, through the request path."""
    SiteConfig.objects.create(
        agency_name="Demo GSA", demonstration_mode=demonstration_mode
    )
    client = _login()
    resp = client.get(reverse("wells:detail", args=[well.pk]))
    assert resp.status_code == 200
    return resp.content.decode()


@pytest.mark.django_db
class TestWellsIdentificationMarker:
    """A well linked to a drinking-water facility is not sample data.

    The FK is the signal, never the ``MER-PWS-`` prefix — that prefix is a
    demonstration seed constant, and a production template that branched on it
    would make a real agency's behaviour depend on our demo's naming. Every test
    below builds its link through the factory and never names the prefix.
    """

    def test_unlinked_well_still_carries_the_demo_pill(self):
        body = _well_pane(WellFactory(), demonstration_mode=True)
        assert "badge-demo" in body
        assert ">DEMO<" in body

    def test_unlinked_well_on_a_real_instance_carries_nothing(self):
        body = _well_pane(WellFactory(), demonstration_mode=False)
        assert "badge-demo" not in body
        assert ">DEMO<" not in body

    @pytestmark_drinking
    def test_linked_well_drops_the_pill_and_names_its_publisher(self):
        from tests.factories import SystemFacilityFactory

        well = WellFactory()
        SystemFacilityFactory(well=well)
        body = _well_pane(well, demonstration_mode=True)

        # The blanket claim is gone...
        assert "badge-demo" not in body
        assert ">DEMO<" not in body
        # ...replaced by a statement of where the identity came from.
        assert "source-label" in body
        assert provenance.PUBLISHED_SUPPLY_SOURCE in body

    @pytestmark_drinking
    def test_linked_well_still_marks_the_composed_registration_id(self):
        """Half-right is the same error in the other direction.

        The name is published; ``well_registration_id`` is an identifier this
        deployment minted for its own registry and names no state or federal one.
        """
        from tests.factories import SystemFacilityFactory

        well = WellFactory()
        SystemFacilityFactory(well=well)
        body = _well_pane(well, demonstration_mode=True)
        assert provenance.LOCAL_REGISTRY in body

    @pytestmark_drinking
    def test_the_publisher_label_is_not_flag_gated(self):
        """The inverse of the four assertions at the top of this file.

        ``_demo_marker.html`` is gated because it claims "this value is fake".
        This label claims "this came from a published record", which is true on a
        real agency deployment too — and there it answers a live operator
        question, so suppressing it would strip information from the deployment
        that needs it most.
        """
        from tests.factories import SystemFacilityFactory

        well = WellFactory()
        SystemFacilityFactory(well=well)
        body = _well_pane(well, demonstration_mode=False)
        assert provenance.PUBLISHED_SUPPLY_SOURCE in body
        assert "badge-demo" not in body


@pytest.mark.django_db
class TestWellsIdentificationModuleGate:
    """With ``drinking`` dropped the pane must render exactly as it did before.

    ``drinking`` is truly optional, not schema-resident: dropped, its app leaves
    ``INSTALLED_APPS`` and ``well.drinking_facilities`` does not exist at all. The
    module set is fixed at process boot, so this cannot be simulated with
    ``override_settings`` — what IS testable in-process is that the resolver
    consults the module registry BEFORE it touches the accessor, which is the
    property that keeps the dropped deployment working.
    """

    def test_no_query_and_no_accessor_when_drinking_is_disabled(
        self, django_assert_num_queries, monkeypatch
    ):
        from wells import views as wells_views

        well = WellFactory()
        monkeypatch.setattr(
            "core.modules.is_enabled", lambda name, names=None: name != "drinking"
        )
        # Zero queries is the assertion: the accessor is never reached, so a
        # process that does not have the relation cannot fail on it.
        with django_assert_num_queries(0):
            assert wells_views.published_source_publisher(well) is None
