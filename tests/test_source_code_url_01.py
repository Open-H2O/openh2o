# SPDX-License-Identifier: AGPL-3.0-or-later
"""The footer's "Source code" link follows the SOURCE_CODE_URL setting.

A site that runs a modified copy points the link at its own copy. A value that
is not an http:// or https:// address is reported by a system check and the
links keep the default, so a typo never leaves a dead or unsafe link on the page.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.checks import run_checks
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

User = get_user_model()

DEFAULT = "https://github.com/Open-H2O/openh2o"
FORK = "https://git.example.org/water-district/openh2o-fork"
CHECK_ID = "openh2o.W003"


def _signed_in_page():
    user = User.objects.create_user(
        username="reader", email="reader@example.org", password="a-good-passw0rd"
    )
    client = Client()
    client.force_login(user)
    response = client.get(reverse("profile"), follow=True)
    assert response.status_code == 200
    return response.content.decode()


def _signed_out_page():
    response = Client().get(reverse("account_login"))
    assert response.status_code == 200
    return response.content.decode()


def _source_links(html):
    import re

    return re.findall(r'href="([^"]*)"[^>]*>Source code', html)


def _ids():
    return [message.id for message in run_checks()]


def test_both_layouts_link_the_default_address_when_nothing_is_set(settings):
    settings.SOURCE_CODE_URL = DEFAULT
    assert _source_links(_signed_in_page()) == [DEFAULT]
    assert _source_links(_signed_out_page()) == [DEFAULT]


def test_a_configured_address_changes_both_links(settings):
    settings.SOURCE_CODE_URL = FORK
    assert _source_links(_signed_in_page()) == [FORK]
    assert _source_links(_signed_out_page()) == [FORK]
    assert CHECK_ID not in _ids()


@pytest.mark.parametrize("bad", ["javascript:alert(1)", "git.example.org/fork", "ftp://example.org/x", "  "])
def test_a_bad_address_warns_and_the_links_keep_the_default(settings, bad):
    settings.SOURCE_CODE_URL = bad
    assert CHECK_ID in _ids()
    assert _source_links(_signed_in_page()) == [DEFAULT]
    assert _source_links(_signed_out_page()) == [DEFAULT]


def test_an_empty_value_is_the_same_as_not_set(settings):
    settings.SOURCE_CODE_URL = ""
    assert CHECK_ID not in _ids()
    assert _source_links(_signed_in_page()) == [DEFAULT]
    assert _source_links(_signed_out_page()) == [DEFAULT]


def test_the_warning_names_the_setting_and_says_what_the_link_does_instead(settings):
    settings.SOURCE_CODE_URL = "not-an-address"
    message = next(m for m in run_checks() if m.id == CHECK_ID)
    assert "SOURCE_CODE_URL" in message.msg
    assert DEFAULT in message.msg + (message.hint or "")
