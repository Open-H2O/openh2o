# SPDX-License-Identifier: AGPL-3.0-or-later
"""In-app feedback intake (feedback app).

Locks the widget's server contract:

  1. A valid POST stores a Feedback row and returns {ok, ref}.
  2. An empty message is rejected (400); a filled honeypot is silently accepted
     with no row written.
  3. An unknown category falls back to "bug"; a valid one is stored.
  4. Image attachments are stored; non-images and oversize files are skipped
     without sinking the whole report.
  5. A signed-in user is linked and server-authoritative diagnostics are merged.
  6. The downstream n8n forward is fired with the new row's id.

Pinned to config.settings.local via the test runner (see Makefile / CLAUDE.md).
"""
import io
import json
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image

from feedback.models import Feedback, FeedbackAttachment

User = get_user_model()
SUBMIT_URL = reverse("feedback:submit")


def _png_bytes(color=(30, 120, 200)):
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    """Keep uploaded test files out of the repo's media dir."""
    settings.MEDIA_ROOT = str(tmp_path)


@pytest.fixture(autouse=True)
def _no_forward(settings):
    """Default: no downstream forward (store-only). Individual tests override."""
    settings.FEEDBACK_ENDPOINT = ""


@pytest.mark.django_db
def test_valid_submission_creates_row(client):
    resp = client.post(SUBMIT_URL, {"category": "bug", "message": "It broke"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    fb = Feedback.objects.get(pk=body["ref"])
    assert fb.message == "It broke"
    assert fb.category == "bug"
    assert fb.user is None


@pytest.mark.django_db
def test_empty_message_rejected(client):
    resp = client.post(SUBMIT_URL, {"category": "bug", "message": "   "})
    assert resp.status_code == 400
    assert Feedback.objects.count() == 0


@pytest.mark.django_db
def test_honeypot_is_silently_dropped(client):
    resp = client.post(
        SUBMIT_URL,
        {"message": "spam", "website": "http://bot.example"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["ref"] is None
    assert Feedback.objects.count() == 0


@pytest.mark.django_db
def test_unknown_category_falls_back_to_bug(client):
    resp = client.post(SUBMIT_URL, {"category": "nonsense", "message": "hi"})
    fb = Feedback.objects.get(pk=resp.json()["ref"])
    assert fb.category == "bug"


@pytest.mark.django_db
def test_data_category_preserved(client):
    resp = client.post(SUBMIT_URL, {"category": "data", "message": "numbers off"})
    fb = Feedback.objects.get(pk=resp.json()["ref"])
    assert fb.category == "data"


@pytest.mark.django_db
def test_get_not_allowed(client):
    assert client.get(SUBMIT_URL).status_code == 405


@pytest.mark.django_db
def test_image_attachment_stored(client):
    img = SimpleUploadedFile("shot.png", _png_bytes(), content_type="image/png")
    resp = client.post(
        SUBMIT_URL, {"message": "see screenshot", "attachments": img}
    )
    fb = Feedback.objects.get(pk=resp.json()["ref"])
    assert fb.attachments.count() == 1
    att = fb.attachments.first()
    assert att.original_name == "shot.png"
    assert att.content_type == "image/png"
    assert att.size > 0


@pytest.mark.django_db
def test_non_image_attachment_skipped_but_report_saved(client):
    bad = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")
    resp = client.post(SUBMIT_URL, {"message": "with a txt", "attachments": bad})
    assert resp.status_code == 200
    fb = Feedback.objects.get(pk=resp.json()["ref"])
    assert fb.attachments.count() == 0


@pytest.mark.django_db
def test_oversize_attachment_skipped(client, settings):
    settings.FEEDBACK_MAX_ATTACHMENT_BYTES = 10  # tiny cap
    img = SimpleUploadedFile("big.png", _png_bytes(), content_type="image/png")
    resp = client.post(SUBMIT_URL, {"message": "too big", "attachments": img})
    fb = Feedback.objects.get(pk=resp.json()["ref"])
    assert fb.attachments.count() == 0


@pytest.mark.django_db
def test_authenticated_user_linked_and_diagnostics_merged(client):
    user = User.objects.create_user(
        username="op", email="op@example.com", password="x"
    )
    client.force_login(user)
    diag = json.dumps({"viewport": {"w": 1280, "h": 720}})
    resp = client.post(
        SUBMIT_URL, {"message": "logged in", "diagnostics": diag}
    )
    fb = Feedback.objects.get(pk=resp.json()["ref"])
    assert fb.user_id == user.id
    assert fb.diagnostics["viewport"]["w"] == 1280
    assert fb.diagnostics["server"]["user_id"] == user.id
    assert fb.diagnostics["server"]["user_email"] == "op@example.com"


@pytest.mark.django_db
def test_malformed_diagnostics_does_not_crash(client):
    resp = client.post(
        SUBMIT_URL, {"message": "bad diag", "diagnostics": "{not json"}
    )
    assert resp.status_code == 200
    fb = Feedback.objects.get(pk=resp.json()["ref"])
    assert fb.diagnostics.get("_unparsed") is True


@pytest.mark.django_db
def test_forward_fires_with_new_id(client, settings):
    settings.FEEDBACK_ENDPOINT = "https://n8n.example/webhook/feedback"
    with mock.patch("feedback.views.forward_async") as forward:
        resp = client.post(SUBMIT_URL, {"message": "forward me"})
    ref = resp.json()["ref"]
    forward.assert_called_once_with(ref)


@pytest.mark.django_db
def test_attachment_served_to_staff_only(client):
    img = SimpleUploadedFile("shot.png", _png_bytes(), content_type="image/png")
    resp = client.post(SUBMIT_URL, {"message": "x", "attachments": img})
    att = Feedback.objects.get(pk=resp.json()["ref"]).attachments.first()
    url = reverse("feedback:attachment", args=[att.pk])

    # Anonymous → 404 (not even existence is leaked).
    assert client.get(url).status_code == 404

    # Non-staff logged-in → 404.
    op = User.objects.create_user(username="op2", email="op2@example.com", password="x")
    client.force_login(op)
    assert client.get(url).status_code == 404

    # Staff → 200 with the bytes.
    staff = User.objects.create_user(
        username="boss", email="boss@example.com", password="x", is_staff=True
    )
    client.force_login(staff)
    ok = client.get(url)
    assert ok.status_code == 200
    assert b"".join(ok.streaming_content)[:4] == b"\x89PNG"


@pytest.mark.django_db
def test_disabled_returns_404(client, settings):
    settings.FEEDBACK_ENABLED = False
    resp = client.post(SUBMIT_URL, {"message": "nope"})
    assert resp.status_code == 404
    assert Feedback.objects.count() == 0
