# SPDX-License-Identifier: AGPL-3.0-or-later
"""A list page may offer to create only the entity it lists.

Phase 119. Two shipped pages broke that rule and nothing in the suite could see
it. The Use Areas toolbar offered "+ Add use area" and "Import" with both
anchors pointed at ``infrastructure:add`` and no ``?type=`` at all, so the
fallback at ``infrastructure/views.py:93`` resolved them to
``ADD_TYPE_ORDER[0]`` and an operator asking for a use area was handed the Add
Well form. Water Rights offered "+ Add diversion" and "Import" at
``?type=diversion`` — a real form for a real entity, just not the one that page
lists.

**The rule this file encodes.** Every href a list page renders into the
infrastructure module must carry a ``?type=`` naming the entity that page lists,
or the page must render no such href at all.

**Why the table is DECLARED and not derived.** Deriving the entity from the URL
prefix is exactly what let this through: ``/surface/`` and ``/surface/rights/``
share a prefix and list different entities. One row per page with its reason
written down cannot mis-attribute.

**Why every assertion is about an href and never about a button's label.**
Labels are copy and later phases in this milestone may reword them; the href is
the fact. The one defect a ``?type=`` check cannot see — an "Import" button
aimed at the Add view, which is what ``templates/parcels/list.html:16`` shipped
— is caught by the paired-offer rule below instead, which is also href-only.

**Why each page is fetched twice.** The two defects lived in different renders.
A list page emits its toolbar on a full page load and its empty state through
``templates/partials/_empty_onboarding.html``, and
``core/workspace.py::list_response`` answers a request carrying ``HX-Request``
with the results partial alone. Checking one render would have missed the other:
on Use Areas the toolbar and the empty state were wrong independently.

**Why it does not walk the templates on disk.** A template's include chain
decides what actually renders, and ``templates/surface/partials/_list_results.html``
is the Water Rights partial despite its name, so the chain is not guessable from
a filename.
"""

import re
from urllib.parse import parse_qs, urlsplit

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from tests.factories import BoundaryFactory

#: (path, the ONE ``?type=`` this page may offer, or None for "may offer neither")
_PAGE_MAY_OFFER = (
    # Lists wells; the add form's "well" card creates one.
    ("/wells/", "well"),
    # Lists points of diversion; "diversion" creates one.
    ("/surface/", "diversion"),
    # Lists recharge sites; "recharge_site" creates one.
    ("/recharge/", "recharge_site"),
    # No parcel type exists in ``infrastructure.views.ADD_TYPE_ORDER``, and the
    # web importer reduces every polygon to a centroid
    # (``infrastructure/importer.py:453``) while a Use Area is a polygon whose
    # area drives the water balance. Use areas arrive through the Setup Wizard
    # (``setup/services.py:90-91``).
    ("/parcels/", None),
    # A water right is issued by the State Water Board. ``surface/urls.py``
    # routes only ``rights/`` and ``rights/<pk>/`` — this product has no create
    # view for one.
    ("/surface/rights/", None),
)

#: The two renders of a list page. Named rather than boolean so a failure says
#: which one produced the offending href.
_RENDERS = ("full page", "empty-state partial")

_HREF = re.compile(r'href="([^"]+)"')


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"offersuser{n}")
    email = factory.Sequence(lambda n: f"offersuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


def _client():
    """A signed-in operator on a CONFIGURED instance.

    ``BoundaryFactory`` plus a non-administrator is the same combination
    ``tests/test_empty_onboarding.py`` uses to force ``needs_setup`` False, so
    the empty state renders its configured branch. A fresh instance renders the
    Setup Wizard branch instead and would test nothing here.
    """
    c = Client()
    c.force_login(UserFactory())
    return c


def _fetch(client, path, render):
    """Fetch one of a list page's two renders.

    The HTMX half follows ``tests/test_empty_onboarding.py::_list_partial``;
    this one takes the path as an argument because five pages are probed here,
    not one.
    """
    extra = {"HTTP_HX_REQUEST": "true"} if render == "empty-state partial" else {}
    return client.get(path, **extra)


def _infrastructure_hrefs(body):
    """Every href on this render that lands inside the infrastructure module.

    The prefix is taken from ``reverse()`` rather than written down, so moving
    the module's mount point moves this test with it.
    """
    prefix = "/" + reverse("infrastructure:add").strip("/").split("/")[0] + "/"
    return [h for h in _HREF.findall(body) if urlsplit(h).path.startswith(prefix)]


@pytest.mark.django_db
@pytest.mark.parametrize("render", _RENDERS)
@pytest.mark.parametrize("path,may_offer", _PAGE_MAY_OFFER)
def test_page_offers_only_what_it_lists(path, may_offer, render):
    resp = _fetch(_client(), path, render)
    assert resp.status_code == 200, (
        f"{path} ({render}) returned {resp.status_code}, so this row proved nothing."
    )
    hrefs = _infrastructure_hrefs(resp.content.decode())

    add_url = reverse("infrastructure:add")
    import_url = reverse("infrastructure:import")

    if may_offer is None:
        assert not hrefs, (
            f"{path} ({render}) offers to create an entity it does not list: "
            f"{hrefs}. Its row in _PAGE_MAY_OFFER carries the reason nothing "
            f"reachable from the infrastructure module can create one."
        )
        return

    for href in hrefs:
        parts = urlsplit(href)
        assert parts.path in (add_url, import_url), (
            f"{path} ({render}) links into the infrastructure module at "
            f"{parts.path!r}, which is neither the add nor the import view: {href}"
        )
        offered = parse_qs(parts.query).get("type", [])
        assert offered, (
            f"{path} ({render}) offers {href} with no ?type=. "
            f"_supported_type() at infrastructure/views.py:93 resolves a blank "
            f"type to ADD_TYPE_ORDER[0], so this button opens whichever form "
            f"happens to be first — not {may_offer!r}."
        )
        assert offered[0] == may_offer, (
            f"{path} ({render}) lists {may_offer!r} but offers to create "
            f"{offered[0]!r}: {href}"
        )

    if hrefs:
        # The paired-offer rule. Every page in this product that offers to
        # create infrastructure offers Add and Import together, one href each.
        # A page showing only Add targets is the href-visible signature of an
        # "Import" button wired to the Add view — the defect
        # templates/parcels/list.html:16 shipped, which a ?type= check alone
        # cannot see and a label check would lose the moment the copy changes.
        targets = {urlsplit(h).path for h in hrefs}
        assert targets == {add_url, import_url}, (
            f"{path} ({render}) reaches {sorted(targets)} but every offering "
            f"page must reach both {add_url} and {import_url}. An Import button "
            f"pointed at the Add view looks exactly like this."
        )
