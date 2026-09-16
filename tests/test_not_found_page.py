# SPDX-License-Identifier: AGPL-3.0-or-later
"""The not-found page (R-060).

Local's DEBUG=True serves Django's technical 500/404 page, which is why the
defect survived: nobody signed in locally ever saw the bare "Not Found" body
production (DEBUG=False) actually serves. `@override_settings(DEBUG=False)`
is the only way this test client reproduces what a reader on staging or
production sees; it does not depend on `templates/404.html` existing to pass
`urls.py` checks or module guards, because the view it exercises is Django's
own `django.views.defaults.page_not_found`, which renders `404.html` when
present and DEBUG is off.

Signed out AND signed in: `templates/404.html` extends `base.html`, whose
sidebar renders for both (`index.html` already proves the shell works
anonymous), so a 404 must not depend on being logged in to render its frame.
"""
from django.contrib.auth import get_user_model
from django.test import Client, override_settings

User = get_user_model()

NO_SUCH_PATH = "/no-such-page-143-09/"


def _admin():
    return User.objects.create_user(
        username="admin404", email="admin404@example.com", password="x",
        is_active=True, is_staff=True, is_superuser=True,
    )


@override_settings(DEBUG=False)
def test_not_found_page_signed_out(db):
    client = Client()
    resp = client.get(NO_SUCH_PATH)
    assert resp.status_code == 404
    body = resp.content.decode()
    assert "Page not found" in body
    assert "Back to Home" in body
    assert "Open Water Accounting Platform" in body
    # copy rule 9 / the drift this page exists to avoid: the resolver's own
    # exception text never reaches the reader.
    assert "Resolver404" not in body
    assert "django.urls.exceptions" not in body


@override_settings(DEBUG=False)
def test_not_found_page_signed_in(db):
    client = Client()
    client.force_login(_admin())
    resp = client.get(NO_SUCH_PATH)
    assert resp.status_code == 404
    body = resp.content.decode()
    assert "Page not found" in body
    assert "Back to Home" in body
    assert "Open Water Accounting Platform" in body


@override_settings(DEBUG=False)
def test_not_found_page_names_the_missing_path(db):
    client = Client()
    resp = client.get(NO_SUCH_PATH)
    assert resp.status_code == 404
    assert NO_SUCH_PATH in resp.content.decode()
