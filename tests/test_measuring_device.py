# SPDX-License-Identifier: AGPL-3.0-or-later
"""
146-03 Task 1: the measuring device registry on the point of diversion.

23 CCR 934(b)(1) governs Water Year 2027 onward (October 1, 2026); the 2016
rule (23 CCR 937) is not modelled here. Three doors proven here, each RED
against the unfixed tree (the exact quotes live in 146-03-EVIDENCE.md):

  1. `/surface/diversion/<pk>/device/add/` creates a MeasuringDevice with two
     rights served, links it to the point as the current device, and the POD
     page's device panel shows it with its accuracy.
  2. `/surface/device/<pk>/edit/` edits the device in place.
  3. A POST to mark the current device removed closes the link
     (removed_on set, is_current=False) and the panel reads "no current
     device".

Plus the 934(d) five-year evidence sentence: present when blank or six years
old, absent when one year old.
"""
from datetime import date

import factory
import pytest
from django.contrib.auth.hashers import make_password
from django.test import Client
from django.urls import reverse

from surface.models import MeasuringDevice, PointOfDiversionDevice
from tests.factories import PointOfDiversionFactory, WaterRightFactory

pytestmark = pytest.mark.django_db


class _UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = "core.User"

    username = factory.Sequence(lambda n: f"deviceuser{n}")
    email = factory.Sequence(lambda n: f"deviceuser{n}@example.com")
    password = factory.LazyFunction(lambda: make_password("testpass123"))
    is_active = True


@pytest.fixture
def auth_client(db):
    c = Client()
    c.force_login(_UserFactory())
    return c


# ---------------------------------------------------------------------------
# 1. Add a device through the screen, with two rights served
# ---------------------------------------------------------------------------


def test_add_device_creates_current_link_with_two_rights(auth_client):
    pod = PointOfDiversionFactory()
    right_a = pod.water_right
    right_b = WaterRightFactory(right_id="A999901")

    resp = auth_client.post(
        reverse("surface:device_add", args=[pod.pk]),
        {
            "nickname": "Headgate 3 flow meter",
            "device_type": "inline_flow_meter",
            "make": "McCrometer",
            "model_number": "MF6000",
            "measured_parameter": "flow_rate",
            "raw_units": "cfs",
            "accuracy_percent": "5.00",
            "installed_on": "2024-03-01",
            "installer_contact": "Jane Roe, PE, jane@example.com",
            "last_evidence_on": "",
            "state_device_id": "",
            "status": "active",
            "notes": "",
            "water_rights": [right_a.pk, right_b.pk],
        },
    )

    assert resp.status_code == 302
    device = MeasuringDevice.objects.get(nickname="Headgate 3 flow meter")
    assert set(device.water_rights.values_list("pk", flat=True)) == {right_a.pk, right_b.pk}

    link = PointOfDiversionDevice.objects.get(point_of_diversion=pod, device=device)
    assert link.is_current is True
    assert link.removed_on is None

    detail = auth_client.get(reverse("surface:pod_detail", args=[pod.pk]))
    body = detail.content.decode()
    assert "Headgate 3 flow meter" in body
    assert "±5.00% by the device" in body and "stated accuracy" in body


def test_device_str_is_nickname_else_make_model(db):
    named = MeasuringDevice.objects.create(
        nickname="Turnout 4 meter", device_type="inline_flow_meter",
    )
    assert str(named) == "Turnout 4 meter"

    unnamed = MeasuringDevice.objects.create(
        device_type="rectangular_weir", make="Parshall", model_number="P-12",
    )
    assert str(unnamed) == "Parshall P-12"


def test_no_current_device_panel_says_so(auth_client):
    pod = PointOfDiversionFactory()
    resp = auth_client.get(reverse("surface:pod_detail", args=[pod.pk]))
    assert "no current device" in resp.content.decode()


# ---------------------------------------------------------------------------
# 2. Edit the device
# ---------------------------------------------------------------------------


def test_edit_device_changes_field_and_redirects_to_pod(auth_client):
    pod = PointOfDiversionFactory()
    device = MeasuringDevice.objects.create(
        nickname="Old name", device_type="v_notch_weir",
    )
    PointOfDiversionDevice.objects.create(
        point_of_diversion=pod, device=device, installed_on=date(2023, 1, 1),
    )

    resp = auth_client.post(
        reverse("surface:device_edit", args=[device.pk]),
        {
            "nickname": "New name",
            "device_type": "v_notch_weir",
            "make": "",
            "model_number": "",
            "measured_parameter": "",
            "raw_units": "",
            "accuracy_percent": "",
            "installed_on": "2023-01-01",
            "installer_contact": "",
            "last_evidence_on": "",
            "state_device_id": "",
            "status": "active",
            "notes": "",
            "water_rights": [],
        },
    )

    assert resp.status_code == 302
    device.refresh_from_db()
    assert device.nickname == "New name"


# ---------------------------------------------------------------------------
# 3. Mark removed closes the link
# ---------------------------------------------------------------------------


def test_mark_removed_closes_link_and_panel_says_no_current_device(auth_client):
    pod = PointOfDiversionFactory()
    device = MeasuringDevice.objects.create(
        nickname="Retiring meter", device_type="inline_flow_meter",
    )
    link = PointOfDiversionDevice.objects.create(
        point_of_diversion=pod, device=device, installed_on=date(2020, 1, 1),
    )

    resp = auth_client.post(reverse("surface:device_mark_removed", args=[pod.pk]))
    assert resp.status_code == 200

    link.refresh_from_db()
    assert link.is_current is False
    assert link.removed_on == date.today()

    detail = auth_client.get(reverse("surface:pod_detail", args=[pod.pk]))
    body = detail.content.decode()
    assert "no current device" in body
    # Scoped to the device panel itself (id="pod-device-panel", ending where
    # the next section, "Linked use areas", begins), not the whole page:
    # 146-03 Task 2 adds a diversion record form ABOVE this panel on the same
    # page whose device select legitimately still offers a removed device
    # (current first) so a past record can be attributed to the device that
    # was on the point when it was entered.
    panel = body.split('id="pod-device-panel"')[1].split("Linked use areas")[0]
    assert "Retiring meter" not in panel


def test_mark_removed_a_bare_get_is_405(auth_client):
    pod = PointOfDiversionFactory()
    resp = auth_client.get(reverse("surface:device_mark_removed", args=[pod.pk]))
    assert resp.status_code == 405


# ---------------------------------------------------------------------------
# 4. The 934(d) five-year evidence sentence
# ---------------------------------------------------------------------------

EVIDENCE_SENTENCE = "evidence of proper functioning is due at least every five years (934(d))"


def _years_ago(years):
    """A same-day date `years` years before today (no leap-day fixtures used)."""
    today = date.today()
    return today.replace(year=today.year - years)


def test_evidence_sentence_shows_when_blank(auth_client):
    pod = PointOfDiversionFactory()
    device = MeasuringDevice.objects.create(
        nickname="No evidence yet", device_type="inline_flow_meter",
        last_evidence_on=None,
    )
    PointOfDiversionDevice.objects.create(point_of_diversion=pod, device=device)

    resp = auth_client.get(reverse("surface:pod_detail", args=[pod.pk]))
    assert EVIDENCE_SENTENCE in resp.content.decode()


def test_evidence_sentence_shows_when_six_years_old(auth_client):
    pod = PointOfDiversionFactory()
    device = MeasuringDevice.objects.create(
        nickname="Stale evidence", device_type="inline_flow_meter",
        last_evidence_on=_years_ago(6),
    )
    PointOfDiversionDevice.objects.create(point_of_diversion=pod, device=device)

    resp = auth_client.get(reverse("surface:pod_detail", args=[pod.pk]))
    assert EVIDENCE_SENTENCE in resp.content.decode()


def test_evidence_sentence_absent_when_one_year_old(auth_client):
    pod = PointOfDiversionFactory()
    device = MeasuringDevice.objects.create(
        nickname="Fresh evidence", device_type="inline_flow_meter",
        last_evidence_on=_years_ago(1),
    )
    PointOfDiversionDevice.objects.create(point_of_diversion=pod, device=device)

    resp = auth_client.get(reverse("surface:pod_detail", args=[pod.pk]))
    assert EVIDENCE_SENTENCE not in resp.content.decode()
