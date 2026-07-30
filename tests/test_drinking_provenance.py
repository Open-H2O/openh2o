# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Phase 101-01 — every drinking-water screen says who published its values.

**What these tests assert, and what they deliberately do not.** Following
``tests/test_drinking_readability.py``'s stated philosophy: a publisher IS NAMED,
never that a particular sentence appears. Plan 101-02 is a copy and formatting
pass over exactly these screens, and a suite that pinned the prose would turn red
on every improvement. What is pinned instead is the *property* — and it is driven
off the constants in ``drinking/provenance.py``, so renaming a constant fails
loudly here rather than silently un-labelling a page.

**Why a source label is not gated on ``demonstration_mode``, asserted rather than
asserted-about.** ``partials/_demo_marker.html`` is gated because it claims "this
value is fake", which is only true on a demonstration.
``partials/_source_label.html`` claims "this value came from EPA's federal
record", which is true on any deployment that onboarded through the wizard — and
on a real agency instance it answers a live operator question. The
``both_modes`` parametrisation below is the executable form of that ruling and is
the exact inverse of the four gating tests at the top of
``tests/test_demo_marker.py``.

**The Phase 64 substring trap, pinned.** ``tests/test_demo_marker.py`` asserts
``"badge-demo" not in body`` against RAW HTML, which means any new pill named as
a variant of that class turns those tests red without changing a word on screen.
It has now caught two components (``.notice-badge``, ``.source-label``); the
class here checks every drinking surface so the next one is caught at the surface
rather than in the surface-water suite.

**The vocabulary property is checked against the REAL gate.** ``visible_text`` and
``find_forbidden_word`` are imported from ``tests/droppability/checks.py`` rather
than re-implemented — 100-01 established that a private copy drifts from the
thing it stands in for. The check is scoped to the source labels themselves and
not to whole pages ON PURPOSE: a drinking facility of type ``WL`` renders the
label *Well*, which is that domain's own published facility type and not a
reference to the ``wells`` section (see ``tests/test_drinking_facilities.py`` and
ISS-097). The labels are the new copy, they are a SHARED component rendering on
pages owned by different modules, and they are what this plan is responsible for.

**Overlap with ``tests/test_demo_marker.py`` is deliberate and small.** The pill
GATING lives there, beside the gate it changed. What lives here is the publisher
being NAMED — the same two branches, asserted for a different property, so
deleting either file leaves a real hole rather than a duplicate.
"""

import re

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.contrib.gis.geos import Point
from django.test import Client
from django.urls import reverse

from core.models import SiteConfig
from drinking import provenance
from tests.droppability.checks import (
    FORBIDDEN_VOCABULARY,
    find_forbidden_word,
    visible_text,
)
from tests.factories import (
    AnalyteFactory,
    SampleEventFactory,
    SampleResultFactory,
    SamplingPointFactory,
    SystemFacilityFactory,
    WaterSystemFactory,
    WellFactory,
)

#: Extracts the rendered text of every provenance label on a page.
_SOURCE_LABEL = re.compile(r'<span class="source-label">(.*?)</span>', re.S)

#: The words a source label may never carry.
#:
#: Built from the REAL gate's table, for the droppable modules that own no source
#: label — a label is a shared component and renders on pages belonging to
#: several of them, so naming any of these would fail
#: ``test_kept_pages_never_name_a_dropped_module`` on a deployment that dropped
#: that module. ``drinking``'s own vocabulary is excluded because a drinking page
#: legitimately names it, and the labels are only reachable where it is enabled.
_LABELS_MAY_NOT_SAY = tuple(
    word
    for module in ("wells", "parcels", "surface", "recharge", "accounting")
    for word in FORBIDDEN_VOCABULARY[module]
)


class UserFactory(factory.django.DjangoModelFactory):
    """Local, matching the house convention — every suite file defines its own."""

    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"provenance{n}")
    email = factory.Sequence(lambda n: f"provenance{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


def _page_text(client, path):
    """The words a reader sees, entities unescaped.

    Raw HTML is the wrong thing to match a publisher against: Django escapes the
    apostrophe in "State Water Board's" to ``&#x27;``, so a constant containing
    one would never be found by a naive substring check even while it renders
    perfectly. ``visible_text`` unescapes LAST, after the tags are gone, which is
    exactly the order that makes this safe.
    """
    return visible_text(client.get(path).content.decode())


def _client(demonstration_mode=True):
    SiteConfig.objects.create(
        agency_name="Demo GSA", demonstration_mode=demonstration_mode
    )
    client = Client()
    client.force_login(UserFactory())
    return client


@pytest.fixture
def surfaces(db):
    """One system deep enough to reach all seven read surfaces.

    The local database holds no drinking rows, so every assertion in this file
    stands on rows it created itself. The facility carries a coordinate because
    the GAMA row-level label lives inside the map card, which the view omits
    entirely when ``location`` is NULL.
    """
    system = WaterSystemFactory(pwsid="CA2410009", name="CITY OF MERCED")
    facility = SystemFacilityFactory(
        system=system,
        facility_id="001",
        name="North source",
        facility_type="WL",
        location=Point(-120.48, 37.30, srid=4326),
    )
    point = SamplingPointFactory(
        facility=facility, ps_code="CA2410009_001_001", name="Raw tap"
    )
    analyte = AnalyteFactory(name="Nitrate")
    event = SampleEventFactory(sampling_point=point)
    result = SampleResultFactory(event=event, analyte=analyte, lab_name="State lab")
    return {
        "system": system,
        "facility": facility,
        "point": point,
        "result": result,
    }


def _paths(surfaces):
    """The seven read surfaces, paired with the publishers each must name."""
    return (
        (reverse("drinking:overview"), (provenance.EPA_SDWIS,)),
        (reverse("drinking:facilities"), (provenance.EPA_SDWIS,)),
        (
            reverse("drinking:facility_detail", args=[surfaces["facility"].pk]),
            (provenance.EPA_SDWIS, provenance.GAMA),
        ),
        (reverse("drinking:sampling_points"), (provenance.PS_CODE_COMPOSED,)),
        (
            reverse("drinking:sampling_point_detail", args=[surfaces["point"].pk]),
            (
                provenance.PS_CODE_COMPOSED,
                provenance.EPA_SDWIS,
                provenance.DDW_LAB,
                provenance.GAMA,
            ),
        ),
        (reverse("drinking:results"), (provenance.DDW_LAB,)),
        (
            reverse("drinking:result_detail", args=[surfaces["result"].pk]),
            # EPA_SDWIS and PS_CODE_COMPOSED are here because the breadcrumb —
            # sampling point, facility, water system, PWSID — is NOT the lab
            # file. It sat inside the DDW section until this was pinned, which
            # attributed EPA's identity fields and a locally composed PS code to
            # the State Water Board's laboratory export.
            (
                provenance.DDW_LAB,
                provenance.EPA_SDWIS,
                provenance.PS_CODE_COMPOSED,
                provenance.CCR_SYSTEM,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# The module itself
# ---------------------------------------------------------------------------


class TestThePublisherVocabulary:
    def test_every_write_path_has_a_constant(self):
        """One constant per row of the write-path table, at minimum.

        A missing name here means a screen somewhere has no constant to point at
        and will grow a literal string instead, which is the drift this module
        exists to stop.
        """
        for name in (
            "EPA_SDWIS",
            "DDW_LAB",
            "GAMA",
            "PS_CODE_COMPOSED",
            "LOCAL_REGISTRY",
        ):
            assert name in provenance.PUBLISHERS
            assert provenance.PUBLISHERS[name] == getattr(provenance, name)

    def test_the_lookup_refuses_an_unknown_publisher(self):
        """Loudly, rather than rendering "Source: " and shipping.

        A label that silently loses its publisher looks deliberate on the page,
        which is worse than an error in development.
        """
        with pytest.raises(KeyError):
            provenance.publisher("NOT_A_PUBLISHER")

    def test_no_constant_names_a_droppable_module(self):
        """These strings reach rendered page text on shared components."""
        for name, wording in provenance.PUBLISHERS.items():
            hit = find_forbidden_word(visible_text(wording), _LABELS_MAY_NOT_SAY)
            assert hit is None, f"provenance.{name} says {hit!r}"


# ---------------------------------------------------------------------------
# The seven read surfaces
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEverySurfaceNamesItsPublisher:
    def test_each_surface_names_the_publisher_of_its_values(self, surfaces):
        client = _client()
        for path, publishers in _paths(surfaces):
            text = _page_text(client, path)
            for publisher in publishers:
                assert publisher in text, f"{path} does not name {publisher!r}"

    def test_each_surface_renders_the_shared_label_component(self, surfaces):
        client = _client()
        for path, _ in _paths(surfaces):
            body = client.get(path).content.decode()
            assert "source-label" in body, f"{path} carries no provenance label"

    @pytest.mark.parametrize("demonstration_mode", [True, False])
    def test_the_label_is_not_flag_gated(self, surfaces, demonstration_mode):
        """The inverse of ``tests/test_demo_marker.py``'s gating assertions.

        A real agency deployment has ``demonstration_mode`` off and still needs
        this label: it answers "can I change this, and where do I go to fix it".
        """
        client = _client(demonstration_mode=demonstration_mode)
        for path, publishers in _paths(surfaces):
            assert "source-label" in client.get(path).content.decode()
            text = _page_text(client, path)
            for publisher in publishers:
                assert publisher in text

    def test_no_drinking_page_emits_the_phase_64_marker_class(self, surfaces):
        """The trap that has now bitten twice, pinned at the surface.

        ``tests/test_demo_marker.py`` matches this on raw HTML, so a future
        "tidy-up" that renames ``.source-label`` into a variant of that class
        turns the surface-water suite red for reasons no one reading it would
        guess. Demonstration mode is ON here, which is when the marker could
        appear at all.
        """
        client = _client(demonstration_mode=True)
        for path, _ in _paths(surfaces):
            body = client.get(path).content.decode()
            assert "badge-demo" not in body, f"{path} emits the Phase 64 class"

    def test_no_rendered_label_names_a_droppable_module(self, surfaces):
        """Read through the REAL droppability helpers, not a private copy."""
        client = _client()
        for path, _ in _paths(surfaces):
            body = client.get(path).content.decode()
            labels = _SOURCE_LABEL.findall(body)
            assert labels, f"{path} carries no provenance label"
            for label in labels:
                hit = find_forbidden_word(
                    visible_text(label), _LABELS_MAY_NOT_SAY
                )
                assert hit is None, f"{path} label says {hit!r}"


# ---------------------------------------------------------------------------
# The wells Identification section
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTheWellsIdentificationSection:
    """The publisher being NAMED. The pill GATING is in test_demo_marker.py."""

    def test_a_well_behind_a_drinking_facility_names_both_publishers(self):
        """Published where it is published, composed where it is composed."""
        well = WellFactory()
        SystemFacilityFactory(well=well)
        client = _client()
        path = reverse("wells:detail", args=[well.pk])
        text = _page_text(client, path)

        assert provenance.PUBLISHED_SUPPLY_SOURCE in text
        assert provenance.LOCAL_REGISTRY in text

    def test_an_ordinary_well_names_no_publisher_at_all(self):
        """A well with no drinking facility renders exactly as it did before."""
        well = WellFactory()
        client = _client()
        path = reverse("wells:detail", args=[well.pk])
        body = client.get(path).content.decode()

        assert "source-label" not in body
        text = _page_text(client, path)
        assert provenance.PUBLISHED_SUPPLY_SOURCE not in text
        assert provenance.LOCAL_REGISTRY not in text

    def test_the_label_on_a_supply_source_names_no_droppable_module(self):
        well = WellFactory()
        SystemFacilityFactory(well=well)
        body = _client().get(reverse("wells:detail", args=[well.pk])).content.decode()

        for label in _SOURCE_LABEL.findall(body):
            assert find_forbidden_word(visible_text(label), _LABELS_MAY_NOT_SAY) is None

    def test_the_accessor_is_never_reached_with_drinking_dropped(
        self, django_assert_num_queries, monkeypatch
    ):
        """The ``drinking``-dropped branch, as far as one process can prove it.

        ``drinking`` is truly optional rather than schema-resident, so a
        deployment without it has no ``drinking_facilities`` relation at all — not
        an empty one. The module set is fixed at process boot and cannot be
        simulated with ``override_settings``, but the property that keeps such a
        deployment working IS testable here: the registry is consulted BEFORE the
        accessor, so nothing touches a relation that does not exist. Zero queries
        is that assertion.
        """
        from wells import views as wells_views

        well = WellFactory()
        monkeypatch.setattr(
            "core.modules.is_enabled", lambda name, names=None: name != "drinking"
        )
        with django_assert_num_queries(0):
            assert wells_views.published_source_publisher(well) is None


# ---------------------------------------------------------------------------
# /about/demonstration-data/
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTheAboutPageSaysTheSameWordsAsTheScreens:
    """Two statements of one fact drift. This is the thing that notices.

    The about page cannot ``{% load drinking_display %}`` — ``drinking`` is truly
    optional and this page is not — so its publisher names are literal strings.
    That is exactly why the assertion belongs here: the page carried three
    different shapes for the same two publishers before Phase 101.
    """

    def test_the_two_drinking_publishers_use_the_constants_wording(self):
        text = _page_text(_client(), reverse("demonstration_data"))
        for wording in (
            provenance.EPA_SDWIS,
            provenance.DDW_LAB,
            provenance.GAMA,
        ):
            assert wording in text, f"about page does not say {wording!r}"

    def test_the_page_points_a_reader_at_the_per_screen_labels(self):
        """Asserted as a property, not as a sentence — 101-02 rewrites this copy.

        What must survive is that the page tells a reader the screens carry the
        answer too; the wording is free to improve.
        """
        text = _page_text(_client(), reverse("demonstration_data")).lower()
        assert "label" in text

    def test_the_record_versus_limit_claim_is_untouched(self):
        """Load-bearing, and Phase 98 built the result page around it."""
        text = _page_text(_client(), reverse("demonstration_data"))
        assert "it does not compare them and does" in text
