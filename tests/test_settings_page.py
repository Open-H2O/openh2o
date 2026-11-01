# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Settings page and the Settings button in the top bar (plan 151.8-01, D4, D6, D7).

Brent's ruling 54 took the Operations/Admin switch out of the sidebar. The
settings that apply to the whole site (Methodology, Delivery Settings, Users,
Site Health, Setup Wizard) now open from one Settings page, reached by a
written-out Settings button beside the sign-in name. The button and the page
follow the rule `admin_required` already applies: an administrator always, any
signed-in person while ACCESS_CONTROL_ENFORCED is off.

Everything is read from rendered HTML.
"""
import re
from html import unescape

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

pytestmark = pytest.mark.django_db

User = get_user_model()

DESCRIPTION = (
    "This page lists the settings that apply to the whole site. "
    "Only an administrator sees it."
)

#: (label, href, sentence) in the order D2 and D6 give them.
ROWS = [
    (
        "Methodology Settings",
        "/accounting/methodology/",
        "Methodology sets the steps of the monthly calculation, their order, "
        "the rain method and the floor.",
    ),
    (
        "Delivery Settings",
        "/accounting/delivery-settings/",
        "Delivery Settings decide how OpenH2O divides surface deliveries among "
        "use areas and what happens to a zone's unused allocation at the end "
        "of the water year.",
    ),
    (
        "Users",
        "/users/",
        "Users lists who can sign in and each person's role.",
    ),
    (
        "Site Health",
        "/health/",
        "Site Health shows the latest result of each of OpenH2O's checks on "
        "this site's records and server.",
    ),
    (
        "Setup Wizard",
        "/setup/",
        "The Setup Wizard sets the area this site covers and loads the public "
        "records inside it.",
    ),
]

_HEADER = re.compile(r'<header class="app-header".*?</header>', re.S)
_MAIN = re.compile(r"<main\b.*?</main>", re.S)
_BUTTON = re.compile(r'<a\s[^>]*class="[^"]*\bheader-settings\b[^"]*"[^>]*>(.*?)</a>', re.S)
_BUTTON_TAG = re.compile(r'<a\s[^>]*class="[^"]*\bheader-settings\b[^"]*"[^>]*>')
_TAG = re.compile(r"<[^>]+>")


def _user(username, **flags):
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.org",
        password="a-good-passw0rd",
        is_active=True,
        **flags,
    )


def _client(user=None):
    client = Client()
    if user is not None:
        client.force_login(user)
    return client


def _text(fragment):
    """Visible text, with entities decoded and curly apostrophes made straight."""
    text = unescape(_TAG.sub(" ", fragment)).replace("’", "'")
    return re.sub(r"\s+", " ", text).strip()


def _main(html):
    found = _MAIN.search(html)
    assert found, "the page has no <main>"
    return found.group(0)


def _header(html):
    found = _HEADER.search(html)
    assert found, "the page has no header"
    return found.group(0)


def _button_tag(html):
    found = _BUTTON_TAG.search(_header(html))
    return found.group(0) if found else None


def _row_hrefs(main):
    return re.findall(r'<a\s[^>]*href="([^"]+)"', main)


@pytest.fixture
def enforced(settings):
    settings.ACCESS_CONTROL_ENFORCED = True


@pytest.fixture
def open_site(settings):
    settings.ACCESS_CONTROL_ENFORCED = False


# -- D6: who gets the page -----------------------------------------------------


def test_an_administrator_gets_the_settings_page(enforced):
    response = _client(_user("set-admin", is_staff=True)).get("/settings/")
    assert response.status_code == 200
    assert response.resolver_match.view_name == "settings"


def test_a_signed_in_non_administrator_is_sent_home_on_an_enforced_site(enforced):
    response = _client(_user("set-operator")).get("/settings/")
    assert response.status_code == 302
    assert response["Location"] == "/"


def test_an_anonymous_visitor_is_sent_to_sign_in(enforced):
    response = Client().get("/settings/")
    assert response.status_code == 302
    assert "/accounts/login/" in response["Location"]
    assert "next=/settings/" in response["Location"]


def test_the_route_is_named_settings():
    from django.urls import reverse

    assert reverse("settings") == "/settings/"


# -- D6: the page ----------------------------------------------------------------


def test_the_page_heading_description_and_crumb(enforced):
    html = _client(_user("set-head", is_staff=True)).get("/settings/").content.decode()
    heading = re.search(r'<h1 class="page-title">(.*?)</h1>', html, re.S)
    assert heading and _text(heading.group(1)) == "Settings"
    description = re.search(r'<p class="page-description">(.*?)</p>', html, re.S)
    assert description and _text(description.group(1)) == DESCRIPTION
    crumb = re.search(r'<nav class="breadcrumb"[^>]*>(.*?)</nav>', html, re.S)
    assert crumb and _text(crumb.group(1)) == "Settings"
    assert "breadcrumb-current" in crumb.group(1)


def test_an_open_demonstration_site_does_not_say_only_an_administrator_sees_it(settings):
    """With sign-in roles off, any signed-in person reaches the page, so it does not claim otherwise."""
    settings.ACCESS_CONTROL_ENFORCED = False
    html = _client(_user("set-open", is_staff=False)).get("/settings/").content.decode()
    description = re.search(r'<p class="page-description">(.*?)</p>', html, re.S)
    assert description
    assert _text(description.group(1)) == "This page lists the settings that apply to the whole site."


def test_an_administrator_sees_the_five_rows_in_order_with_their_sentences(enforced):
    html = _client(_user("set-rows", is_staff=True)).get("/settings/").content.decode()
    main = _main(html)
    text = _text(main)
    positions = []
    for label, href, sentence in ROWS:
        assert f'href="{href}"' in main, label
        assert sentence in text, f"{label}: the page does not carry its sentence"
        positions.append(main.index(f'href="{href}"'))
    assert positions == sorted(positions), "the rows are out of order"
    # Each sentence sits beside its own label, before the next row's label.
    for (label, _href, sentence), (next_label, _h, _s) in zip(ROWS, ROWS[1:]):
        assert text.index(label) < text.index(sentence) < text.index(next_label, text.index(label) + 1)


def test_the_rows_are_one_raised_card_with_the_settings_list_classes(enforced):
    main = _main(
        _client(_user("set-card", is_staff=True)).get("/settings/").content.decode()
    )
    assert main.count("settings-row") >= len(ROWS)
    assert "settings-list" in main
    card = main[main.index("card-raised"):]
    for _label, href, _sentence in ROWS:
        assert f'href="{href}"' in card, href


def test_each_row_has_an_icon_and_its_label_as_a_link(enforced):
    main = _main(
        _client(_user("set-icons", is_staff=True)).get("/settings/").content.decode()
    )
    for label, href, _sentence in ROWS:
        link = re.search(
            r'<a\s[^>]*href="' + re.escape(href) + r'"[^>]*>(.*?)</a>', main, re.S
        )
        assert link, label
        assert _text(link.group(1)) == label
    assert main.count("<svg") >= len(ROWS)


def test_every_row_link_opens_for_an_administrator(enforced):
    client = _client(_user("set-open", is_staff=True))
    for label, href, _sentence in ROWS:
        assert client.get(href).status_code == 200, label


def test_the_page_names_no_retired_word(enforced):
    html = _client(_user("set-words", is_staff=True)).get("/settings/").content.decode()
    text = _text(_main(html))
    for word in ("Administration", "Admin mode", "Operations"):
        assert word not in text, word


# -- D6: visibility predicates carry over -------------------------------------------


def test_a_non_administrator_on_an_open_site_gets_the_page_without_admin_rows(open_site):
    response = _client(_user("set-open-op")).get("/settings/")
    assert response.status_code == 200
    main = _main(response.content.decode())
    hrefs = _row_hrefs(main)
    for gone in ("/accounting/methodology/", "/accounting/delivery-settings/", "/users/"):
        assert gone not in hrefs, gone
    assert "/health/" in hrefs
    assert "/setup/" in hrefs


def test_a_viewer_does_not_get_the_setup_wizard_row(open_site):
    response = _client(_user("set-viewer", read_only=True)).get("/settings/")
    assert response.status_code == 200
    assert "/setup/" not in _row_hrefs(_main(response.content.decode()))


def test_an_administrator_who_is_a_viewer_does_not_get_the_setup_wizard_row(enforced):
    response = _client(_user("set-admin-viewer", is_staff=True, read_only=True)).get(
        "/settings/"
    )
    assert response.status_code == 200
    hrefs = _row_hrefs(_main(response.content.decode()))
    assert "/setup/" not in hrefs
    assert "/users/" in hrefs


# -- D7: the header button -------------------------------------------------------------


def test_the_header_button_says_settings_and_links_to_the_page(enforced):
    html = _client(_user("btn-admin", is_staff=True)).get("/wells/").content.decode()
    tag = _button_tag(html)
    assert tag, "an administrator's header has no Settings button"
    assert 'href="/settings/"' in tag
    assert "btn-secondary" in tag and "btn-sm" in tag
    label = _text(_BUTTON.search(_header(html)).group(1))
    assert label == "Settings"
    assert "<svg" in _BUTTON.search(_header(html)).group(1)


def test_the_button_sits_before_the_email_link_and_sign_out(enforced):
    user = _user("btn-order", is_staff=True)
    header = _header(_client(user).get("/wells/").content.decode())
    assert header.index("header-settings") < header.index(user.email)
    assert header.index(user.email) < header.index("Sign out")


def test_an_operator_on_an_enforced_site_has_no_button(enforced):
    html = _client(_user("btn-op")).get("/wells/").content.decode()
    assert _button_tag(html) is None
    assert 'href="/settings/"' not in html


def test_a_signed_in_person_on_an_open_site_has_the_button(open_site):
    html = _client(_user("btn-open")).get("/wells/").content.decode()
    assert _button_tag(html) is not None


def test_a_visitor_who_is_not_signed_in_has_no_button(open_site):
    html = Client().get("/about/").content.decode()
    assert _button_tag(html) is None


@pytest.mark.parametrize(
    "path",
    [
        "/settings/",
        "/accounting/methodology/",
        "/accounting/delivery-settings/",
        "/users/",
        "/health/",
        "/setup/",
    ],
)
def test_the_button_is_current_on_the_settings_page_and_each_of_its_entries(enforced, path):
    html = _client(_user("btn-lit", is_staff=True)).get(path).content.decode()
    tag = _button_tag(html)
    assert tag
    assert re.search(r'class="[^"]*\bactive\b', tag), tag
    assert 'aria-current="page"' in tag, tag


@pytest.mark.parametrize("path", ["/", "/wells/", "/accounting/dashboard/", "/help/glossary/"])
def test_the_button_is_not_current_elsewhere(enforced, path):
    html = _client(_user("btn-not-lit", is_staff=True)).get(path).content.decode()
    tag = _button_tag(html)
    assert tag
    assert not re.search(r'class="[^"]*\bactive\b', tag), tag
    assert "aria-current" not in tag


# -- D5: the switch is gone --------------------------------------------------------------


def test_the_old_route_is_a_404(enforced):
    client = _client(_user("gone-admin", is_staff=True))
    assert client.get("/nav-mode/").status_code == 404
    assert client.get("/nav-mode/?mode=admin").status_code == 404


def test_the_route_name_no_longer_reverses():
    from django.urls import NoReverseMatch, reverse

    with pytest.raises(NoReverseMatch):
        reverse("set_nav_mode")


@pytest.mark.parametrize("path", ["/", "/wells/", "/settings/", "/accounting/methodology/"])
def test_a_nav_mode_cookie_changes_nothing_on_the_page(enforced, path):
    user = _user("cookie-admin", is_staff=True)
    plain = _client(user).get(path).content.decode()
    client = _client(user)
    client.cookies["nav_mode"] = "admin"
    with_cookie = client.get(path).content.decode()
    client.cookies["nav_mode"] = "operations"
    with_other = client.get(path).content.decode()

    def stable(html):
        html = re.sub(r"hx-headers='[^']*'", "", html)
        html = re.sub(r'csrf: "[^"]*"', "", html)
        return re.sub(r'name="csrfmiddlewaretoken" value="[^"]*"', "", html)

    assert stable(with_cookie) == stable(plain)
    assert stable(with_other) == stable(plain)
