# SPDX-License-Identifier: AGPL-3.0-or-later
"""The footer names the version a site runs once `make upgrade` stamps one (ISS-173).

`make upgrade` builds with APP_VERSION set to `git describe`; the footer slot in
templates/base.html shows it whenever it is anything but "dev".
"""

import pytest
from django.test import override_settings


@pytest.mark.django_db
@override_settings(APP_VERSION="v2.17-300-g2222222")
def test_footer_shows_the_stamped_version(client):
    page = client.get("/about/").content.decode()
    assert '<span class="app-footer-version" title="Build version">v2.17-300-g2222222</span>' in page


@pytest.mark.django_db
@override_settings(APP_VERSION="dev")
def test_footer_shows_no_version_on_an_unstamped_build(client):
    assert "app-footer-version" not in client.get("/about/").content.decode()
