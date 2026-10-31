# SPDX-License-Identifier: AGPL-3.0-or-later
"""The grouped sidebar (plan 151.8-01, decisions D1, D2, D3, D5, D8, D11).

The sidebar has one shape. It groups the site's pages by what the records are
about (Water accounting, Sources and monitoring, Drinking water, Reporting),
holds no Operations/Admin switch, and draws the Drinking water group as a
collapsible block whose open state follows the page, then the reader's last
choice, then whether the site runs water accounting at all.

Every assertion reads HTML the Django test client rendered, so what is checked
is what a person gets, not how the registry produced it. The two checks that
need a deployment without water accounting render the sidebar partial with the
context the ``modules`` processor builds under a reduced ``OPENH2O_MODULES``;
the whole-process version of the same case is the droppability harness
(``tests/droppability/checks.py``).
"""
import re
from html import unescape

import pytest
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, override_settings

from core.modules import ALL_MODULE_NAMES

pytestmark = pytest.mark.django_db

User = get_user_model()

_SIDEBAR = re.compile(r'<aside id="sidebar".*?</aside>', re.S)
_TOKEN = re.compile(
    r'class="sidebar-link-text sidebar-section-label">([^<]+)</span>'
    r'|<a\s[^>]*class="sidebar-link( active)?"[^>]*>.*?'
    r'<span class="sidebar-link-text">([^<]+)</span>',
    re.S,
)
_DRINKING_DETAILS = re.compile(
    r'<details\s[^>]*class="[^"]*\bsidebar-group-drinking\b[^"]*"[^>]*>'
)
_SCRIPT = re.compile(r"<script[^>]*>(.*?)</script>", re.S)

SIDEBAR_AS_DESIGNED = [
    ("", "Home"),
    ("", "Dashboard"),
    ("", "Map"),
    ("Water accounting", "Use Ledger"),
    ("Water accounting", "Accounts"),
    ("Water accounting", "Use Areas"),
    ("Water accounting", "Zones"),
    ("Water accounting", "Allocations"),
    ("Water accounting", "Water Years"),
    ("Sources and monitoring", "Wells"),
    ("Sources and monitoring", "Surface Diversions"),
    ("Sources and monitoring", "Water Rights"),
    ("Sources and monitoring", "Recharge Sites"),
    ("Sources and monitoring", "Monitoring Stations"),
    ("Drinking water", "Water Systems"),
    ("Drinking water", "Facilities"),
    ("Drinking water", "Sampling Points"),
    ("Drinking water", "Sample Results"),
    ("Drinking water", "Production"),
    ("Drinking water", "Schedule"),
]


def _user(username, **flags):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.org",
        password="a-good-passw0rd",
        is_active=True,
        **flags,
    )


def _client(user=None, **cookies):
    client = Client()
    client.force_login(user or _user("groups-admin", is_staff=True))
    for name, value in cookies.items():
        client.cookies[name] = value
    return client


def _page(client, path):
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)
    return response.content.decode()


def _sidebar(html):
    found = _SIDEBAR.search(html)
    assert found, "the page has no sidebar"
    return found.group(0)


def _links(sidebar):
    """(section heading, label) for every link in the sidebar, top to bottom."""
    section, links = "", []
    for token in _TOKEN.finditer(sidebar):
        if token.group(1) is not None:
            section = unescape(token.group(1)).strip()
        else:
            links.append((section, unescape(token.group(3)).strip()))
    return links


def _drinking_is_open(sidebar):
    found = _DRINKING_DETAILS.search(sidebar)
    assert found, "the sidebar has no Drinking water <details class=\"sidebar-group-drinking\">"
    return bool(re.search(r"\sopen(\s|=|>)", found.group(0)))


# -- D1, D2: the groups and their order ----------------------------------------------


def test_the_sidebar_groups_and_entries_follow_the_design_on_a_full_site():
    links = _links(_sidebar(_page(_client(), "/")))
    designed = [pair for pair in links if pair[1] != "Reports"]
    # Reporting is on in the test suite (OPENH2O_MODULES=all); Help follows it.
    assert designed[: len(SIDEBAR_AS_DESIGNED)] == SIDEBAR_AS_DESIGNED
    assert ("Reporting", "Reports") in links
    headings = [s for s in dict.fromkeys(section for section, _ in links)]
    assert headings[:5] == [
        "", "Water accounting", "Sources and monitoring", "Drinking water", "Reporting",
    ]
    assert headings[-1] == "Help"


def test_the_sidebar_shows_no_water_data_or_administration_heading():
    sidebar = _sidebar(_page(_client(), "/"))
    labels = {section for section, _ in _links(sidebar)}
    assert not labels & {"Water Data", "Administration", "Settings"}
    assert "Admin mode" not in sidebar and "Operations" not in sidebar


def test_the_sidebar_carries_no_settings_entry_and_no_old_write_entries():
    sidebar = _sidebar(_page(_client(), "/"))
    labels = [label for _section, label in _links(sidebar)]
    for gone in (
        "Methodology", "Delivery Settings", "Users", "Site Health", "Setup Wizard",
        "Infrastructure", "Add a water system", "Drinking Water", "Recharge sites",
    ):
        assert gone not in labels, gone
    for href in ('href="/setup/', 'href="/users/', 'href="/health/',
                 'href="/infrastructure/', 'href="/drinking/onboard',
                 'href="/accounting/methodology', 'href="/accounting/delivery-settings'):
        assert href not in sidebar, href


# -- D5: the switch is gone -----------------------------------------------------------


def test_no_element_carries_a_nav_mode_class_or_the_admin_mode_chip():
    html = _page(_client(), "/")
    assert not re.search(r'class="[^"]*nav-mode', html)
    assert "header-mode-badge" not in html
    assert "Admin mode" not in html
    assert "Sidebar view mode" not in html


@pytest.mark.parametrize("cookie", ["admin", "operations", "nonsense"])
def test_a_browser_still_sending_nav_mode_gets_the_same_page(cookie):
    user = _user("groups-cookie", is_staff=True)
    plain = _sidebar(_page(_client(user), "/"))
    with_cookie = _sidebar(_page(_client(user, nav_mode=cookie), "/"))
    assert with_cookie == plain


def test_the_nav_mode_route_is_a_404():
    client = _client()
    assert client.get("/nav-mode/", {"mode": "admin"}).status_code == 404
    assert client.get("/nav-mode/").status_code == 404


# -- D8: Drinking water collapses -------------------------------------------------------


def test_drinking_water_is_a_collapsible_details_with_the_help_summary_markup():
    sidebar = _sidebar(_page(_client(), "/"))
    block = sidebar[sidebar.index("sidebar-group-drinking"):]
    block = block[: block.index("</details>")]
    assert 'class="sidebar-collapsible' in sidebar
    assert "sidebar-collapsible-summary" in block
    assert "sidebar-collapsible-chevron" in block
    assert "Drinking water" in block
    assert [label for _s, label in _links(block)] == [
        "Water Systems", "Facilities", "Sampling Points", "Sample Results",
        "Production", "Schedule",
    ]


@pytest.mark.parametrize("cookie", [None, "open", "closed"])
@pytest.mark.parametrize(
    "path",
    ["/drinking/", "/drinking/facilities/", "/drinking/results/", "/drinking/onboard/"],
)
def test_the_group_is_open_on_a_drinking_page_whatever_the_cookie_says(path, cookie):
    cookies = {} if cookie is None else {"sidebar_drinking": cookie}
    assert _drinking_is_open(_sidebar(_page(_client(**cookies), path)))


def test_the_group_is_closed_on_home_of_a_full_site_with_no_cookie():
    assert not _drinking_is_open(_sidebar(_page(_client(), "/")))


def test_the_group_opens_on_home_when_the_reader_left_it_open():
    assert _drinking_is_open(_sidebar(_page(_client(sidebar_drinking="open"), "/")))


def test_the_group_stays_closed_on_home_when_the_reader_closed_it():
    assert not _drinking_is_open(
        _sidebar(_page(_client(sidebar_drinking="closed"), "/"))
    )


def test_the_group_stays_closed_on_another_group_page_with_no_cookie():
    assert not _drinking_is_open(_sidebar(_page(_client(), "/wells/")))


def test_the_toggle_script_listens_for_click_on_the_summary_and_never_for_toggle():
    """Chrome fires `toggle` for a details element parsed with `open`, which
    would overwrite a reader's "closed" every time a drinking page forces the
    group open. A click on the summary, reading the state it is about to take,
    does not."""
    html = _page(_client(), "/")
    scripts = [s for s in _SCRIPT.findall(html) if "sidebar_drinking" in s]
    assert scripts, "no inline script writes the sidebar_drinking cookie"
    script = "\n".join(scripts)
    assert re.search(r"""addEventListener\(\s*['"]click['"]|\.onclick\s*=""", script)
    assert not re.search(r"""addEventListener\(\s*['"]toggle['"]|\.ontoggle\s*=""", script)
    assert re.search(r"!\s*\w+\.open", script), "it must read the state the click leads to"
    for fragment in ("path=/", "max-age=31536000", "samesite=lax"):
        assert fragment in script.lower().replace(" ", ""), fragment
    assert "open" in script and "closed" in script


# -- D3, D8 without water accounting -----------------------------------------------------


def _without_accounting():
    from tests.test_droppability_acceptance import drop_closure

    gone = drop_closure("accounting")
    kept = tuple(n for n in ALL_MODULE_NAMES if n not in gone)
    assert "drinking" in kept and "accounting" not in kept
    return kept


def _render_sidebar(path, cookies=None, kept=None):
    """The sidebar partial, with the context the real processors build."""
    from core.context_processors import modules

    request = RequestFactory().get(path)
    request.COOKIES.update(cookies or {})
    context = {
        "request": request,
        "user_is_admin": True,
        "access_enforced": False,
        "user_can_write": True,
        **modules(request),
    }
    return render_to_string("partials/_sidebar.html", context)


def test_without_water_accounting_the_group_is_open_with_no_cookie():
    with override_settings(OPENH2O_MODULES=_without_accounting()):
        sidebar = _render_sidebar("/")
    assert _drinking_is_open(sidebar)


def test_without_water_accounting_a_closed_cookie_still_closes_it_off_a_drinking_page():
    with override_settings(OPENH2O_MODULES=_without_accounting()):
        closed = _render_sidebar("/", {"sidebar_drinking": "closed"})
        on_drinking = _render_sidebar("/drinking/", {"sidebar_drinking": "closed"})
    assert not _drinking_is_open(closed)
    assert _drinking_is_open(on_drinking)


def test_without_water_accounting_there_is_no_water_accounting_heading_and_zones_leads():
    with override_settings(OPENH2O_MODULES=_without_accounting()):
        links = _links(_render_sidebar("/"))
    headings = {section for section, _ in links}
    assert "Water accounting" not in headings
    top = [label for section, label in links if section == ""]
    assert "Zones" in top
    assert "Home" in top and "Map" in top
    assert ("Drinking water", "Water Systems") in links
    assert "water account" not in " ".join(label.lower() for _s, label in links)


def test_with_water_accounting_zones_sit_under_its_heading():
    links = _links(_render_sidebar("/"))
    assert ("Water accounting", "Zones") in links
    assert ("", "Zones") not in links


# -- D9: the Add a water system button ------------------------------------------------------


def test_water_systems_offers_add_a_water_system_to_a_writer_and_not_to_a_viewer():
    writer = _client(_user("groups-writer"))
    viewer = _client(_user("groups-viewer", read_only=True))
    write_html = _page(writer, "/drinking/")
    view_html = _page(viewer, "/drinking/")
    onboard = 'href="/drinking/onboard/"'
    assert onboard in write_html.split("</aside>", 1)[-1]
    assert onboard not in view_html.split("</aside>", 1)[-1]
    assert onboard not in _sidebar(write_html)


# -- D11: the search box ----------------------------------------------------------------------


def test_the_search_box_names_use_areas_and_not_parcels():
    html = _page(_client(), "/")
    placeholder = re.search(r'id="global-search-input"[^>]*placeholder="([^"]*)"', html, re.S)
    assert placeholder, "no search box"
    text = placeholder.group(1)
    assert text.startswith("Search use areas, ")
    assert "parcels" not in text.lower()
