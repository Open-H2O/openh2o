# SPDX-License-Identifier: AGPL-3.0-or-later
"""The bulk import round trip, as the browser makes it (151.6-03).

A preview saves the upload and its form carries a token; Import posts that
token (plus the page's settings) and the page then polls the status route,
which shows the result block once the commit has run. The suite runs the
commit in process (``OPENH2O_IMPORT_INLINE``), so one status request after
Import returns the finished result.
"""
import re
from html import unescape

from django.urls import reverse


def token_of(response):
    """The token the preview's form carries."""
    for tag in re.findall(r"<input[^>]*>", response.content.decode()):
        if re.search(r'name="token"', tag):
            return unescape(re.search(r'value="([^"]+)"', tag).group(1))
    raise AssertionError("the preview form has no token field")


def status_of(client, token):
    """The status route's answer for ``token``."""
    return client.get(
        reverse("core:pending_import_status", args=[token]), HTTP_HX_REQUEST="true"
    )


def import_and_read(client, commit_url, token, data=None):
    """Press Import with ``token``, then read what the status route shows.

    Returns the status response, so a test reads ``.content`` or ``.context``.
    """
    pressed = client.post(
        commit_url, {"token": token, **(data or {})}, HTTP_HX_REQUEST="true"
    )
    assert pressed.status_code == 200
    return status_of(client, token)


def csv_text_of(rows):
    """``rows`` (dicts) as the text of a CSV file; the header is every key, in order."""
    import csv
    import io

    columns = list(dict.fromkeys(key for row in rows for key in row))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def infrastructure_import_rows(
    client, rows, mapping, infra_type="well", name="import.csv"
):
    """Upload ``rows`` to the infrastructure import, press Import with
    ``mapping`` (the posted ``map:`` fields), and return the status response."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    upload = SimpleUploadedFile(
        name, csv_text_of(rows).encode("utf-8"), content_type="text/csv"
    )
    preview = client.post(
        reverse("infrastructure:import_preview"),
        {"infra_type": infra_type, "file": upload},
    )
    return import_and_read(
        client,
        reverse("infrastructure:import_commit"),
        token_of(preview),
        {"infra_type": infra_type, **mapping},
    )
